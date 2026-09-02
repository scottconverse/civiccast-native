# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0085 + the durable notification-delivery outcome store (WP-05).

The schema is the load-bearing part of the fix: the UNIQUE constraint on the
logical delivery identity is what makes two concurrent approvals unable to
double-send a resident. ``create_all`` (the ORM) would pass even if the
migration were broken, so these tests drive the real alembic upgrade and
downgrade, then exercise the store against the schema the migration produced.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.subscribe.models  # noqa: F401 -- register the WP-05 tables on Base.metadata
from civiccast.db import Base
from civiccast.subscribe.outcome_store import (
    InMemoryNotificationDeliveryStore,
    PostgresNotificationDeliveryStore,
    logical_delivery_key,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_WP05_TABLES = {"notification_delivery_outcomes", "notification_delivery_attempts"}
_PRIOR_TABLE = "subscription_webhook_retries"
_REVISION = "0085_notification_delivery_outcomes"
_PARENT = "0082_egress_graphics_overlay"


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tables(url: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alembic_graph_still_has_exactly_one_head() -> None:
    """0085 must not fork the graph -- `alembic upgrade head` is the install path."""

    heads = tuple(ScriptDirectory.from_config(_cfg("sqlite://")).get_heads())
    assert heads == (_REVISION,), (
        f"expected the single head to be {_REVISION}; got {sorted(heads)}. "
        "If WP-04's 0084 or PR #131's 0083 has landed, re-parent 0085's "
        "down_revision onto the new head."
    )


def test_0085_parent_is_the_current_head_at_authoring_time() -> None:
    script = ScriptDirectory.from_config(_cfg("sqlite://"))
    revision = script.get_revision(_REVISION)
    assert revision.down_revision == _PARENT


def test_upgrade_creates_both_delivery_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0085.sqlite'}"
    command.upgrade(_cfg(url), "head")

    missing = _WP05_TABLES - _tables(url)
    assert not missing, f"0085 did not create tables: {missing}"

    # The idempotency guard has to be in the schema the MIGRATION produces,
    # not only in the ORM metadata create_all builds.
    engine = create_engine(url, future=True)
    try:
        constraints = inspect(engine).get_unique_constraints("notification_delivery_outcomes")
    finally:
        engine.dispose()
    by_name = {constraint["name"]: constraint["column_names"] for constraint in constraints}
    assert by_name.get("notification_delivery_outcomes_logical_key") == [
        "publication_id",
        "subscription_id",
        "target_type",
        "target_id",
        "transport",
    ]


def test_downgrade_removes_them_and_leaves_prior_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0085_down.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, _PARENT)

    tables = _tables(url)
    assert not (_WP05_TABLES & tables), f"0085 downgrade left tables: {_WP05_TABLES & tables}"
    assert _PRIOR_TABLE in tables, "0085 downgrade removed a prior migration's table"


def test_upgrade_backfills_nothing_because_no_receipt_ever_existed(tmp_path: Path) -> None:
    """No prior release wrote a delivery receipt, so there is nothing to backfill.

    This is the assertion behind the migration's backfill note: the tables come
    up EMPTY rather than seeded with invented receipts for historical publish
    runs. Publish reads that emptiness as ``unverified``.
    """

    url = f"sqlite:///{tmp_path / 'm0085_empty.sqlite'}"
    command.upgrade(_cfg(url), "head")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            outcomes = conn.execute(
                text("SELECT COUNT(*) FROM notification_delivery_outcomes")
            ).scalar_one()
            attempts = conn.execute(
                text("SELECT COUNT(*) FROM notification_delivery_attempts")
            ).scalar_one()
    finally:
        engine.dispose()
    assert (outcomes, attempts) == (0, 0)


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """A schema-qualified SQLite engine, matching this repo's store-test shape.

    The ORM addresses ``civiccast.<table>``, which SQLite resolves through the
    ``ATTACH DATABASE ':memory:' AS civiccast`` connect hook in
    ``civiccast.db.base``. The migration tests above drive the real alembic
    upgrade against a file database (where SQLite gets unqualified names); this
    fixture is the store-level counterpart, the same split every other
    ``Postgres*Store`` test in this repo uses.
    """

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def store(sqlite_engine: Engine) -> PostgresNotificationDeliveryStore:
    @contextmanager
    def session_factory() -> Iterator[Session]:
        session = Session(bind=sqlite_engine)
        try:
            yield session
        finally:
            session.close()

    return PostgresNotificationDeliveryStore(session_factory)


_CLAIM = {
    "publication_id": "pub:meeting-42",
    "asset_id": "meeting-42",
    "subscription_id": "sub-abc",
    "target_type": "channel",
    "target_id": "government",
    "transport": "email",
}


def test_logical_key_excludes_the_attempt_number() -> None:
    """The key IS the duplicate-send guard, so attempts must collide on it."""

    first = logical_delivery_key(
        publication_id="pub:a",
        subscription_id="sub-1",
        target_type="channel",
        target_id="government",
        transport="email",
    )
    second = logical_delivery_key(
        publication_id="pub:a",
        subscription_id="sub-1",
        target_type="channel",
        target_id="government",
        transport="email",
    )
    other_transport = logical_delivery_key(
        publication_id="pub:a",
        subscription_id="sub-1",
        target_type="channel",
        target_id="government",
        transport="webhook",
    )
    assert first == second
    assert first != other_transport


def test_second_claim_returns_the_same_row_and_never_a_duplicate(
    store: PostgresNotificationDeliveryStore,
) -> None:
    first = store.claim(**_CLAIM)
    second = store.claim(**_CLAIM)

    assert first.created is True
    assert second.created is False
    assert second.record.delivery_key == first.record.delivery_key
    assert len(store.list_for_publication("pub:meeting-42")) == 1


def test_unique_constraint_rejects_a_second_row_for_the_same_logical_delivery(
    store: PostgresNotificationDeliveryStore, sqlite_engine: Engine
) -> None:
    """The guard is in the SCHEMA, not in memory.

    Written straight through SQL with a different primary key, so it bypasses
    the store's own read-before-insert entirely -- which is what a second
    process racing the first would effectively do.
    """

    from sqlalchemy.exc import IntegrityError

    store.claim(**_CLAIM)
    with sqlite_engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO civiccast.notification_delivery_outcomes ("
                "delivery_key, publication_id, asset_id, subscription_id, "
                "target_type, target_id, transport, outcome, attempts, detail, "
                "created_at, updated_at) VALUES ("
                "'ndk-a-different-primary-key', :publication_id, :asset_id, "
                ":subscription_id, :target_type, :target_id, :transport, "
                "'pending', 0, '', :now, :now)"
            ),
            {**_CLAIM, "now": datetime.now(UTC).isoformat()},
        )


def test_attempts_are_numbered_beneath_one_logical_delivery(
    store: PostgresNotificationDeliveryStore,
) -> None:
    claimed = store.claim(**_CLAIM)
    key = claimed.record.delivery_key

    store.record_attempt(delivery_key=key, outcome="failed", error_code="SMTPDataError")
    store.record_attempt(delivery_key=key, outcome="queued", retry_id="swr_1")
    final = store.record_attempt(delivery_key=key, outcome="sent")

    attempts = store.list_attempts(key)
    assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]
    assert [attempt.outcome for attempt in attempts] == ["failed", "queued", "sent"]
    assert final.attempts == 3
    assert final.outcome == "sent"
    assert final.succeeded_at is not None
    assert final.first_attempted_at is not None
    assert len(store.list_for_publication("pub:meeting-42")) == 1


def test_in_memory_store_matches_the_durable_store_semantics() -> None:
    """The ephemeral fallback must not have looser rules than the real store."""

    store = InMemoryNotificationDeliveryStore()

    first = store.claim(**_CLAIM)
    store.record_attempt(delivery_key=first.record.delivery_key, outcome="sent")
    second = store.claim(**_CLAIM)

    assert first.created is True
    assert second.created is False
    assert second.already_sent is True
    assert len(store.list_for_publication("pub:meeting-42")) == 1


def test_stored_rows_carry_no_recipient_handle(
    store: PostgresNotificationDeliveryStore,
) -> None:
    claimed = store.claim(**_CLAIM)
    store.record_attempt(
        delivery_key=claimed.record.delivery_key,
        outcome="failed",
        error_code="SMTPRecipientsRefused",
        detail="Mail provider refused the address.",
    )

    rendered = store.get(claimed.record.delivery_key)
    assert rendered is not None
    assert "@" not in rendered.model_dump_json()
