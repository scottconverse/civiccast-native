# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""ActivityPub durable store and migration coverage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401
from civiccast.activitypub.models import DeliveryRecord, FollowerRecord, OutboxRecord
from civiccast.activitypub.store import PostgresActivityPubStore
from civiccast.db import Base, bind_engine, reset_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@contextmanager
def _session_factory(engine) -> Iterator[Session]:
    sess = Session(bind=engine)
    try:
        yield sess
    finally:
        sess.close()


def _follower() -> FollowerRecord:
    return FollowerRecord(
        actor="https://neighbor.example/users/alex",
        domain="neighbor.example",
        status="accepted",
        activity_id="https://neighbor.example/follows/1",
        inbox_url="https://neighbor.example/users/alex/inbox",
        shared_inbox_url="https://neighbor.example/inbox",
        public_key_id="https://neighbor.example/users/alex#main-key",
        public_key_pem="-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
        created_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )


def test_postgres_activitypub_store_round_trips_with_sqlalchemy_engine() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)
    try:
        store = PostgresActivityPubStore(lambda: _session_factory(engine))
        follower = store.upsert_follower(_follower())
        outbox = store.append_outbox(
            OutboxRecord(
                activity_id="https://station.example/ap/actor/activities/1",
                activity={"type": "Create", "actor": "https://station.example/ap/actor"},
                created_at=datetime(2026, 5, 21, 12, 5, tzinfo=UTC),
            )
        )
        delivery = store.append_delivery(
            DeliveryRecord(
                delivery_id="apd-test-1",
                activity_id=outbox.activity_id,
                inbox_url=follower.shared_inbox_url or follower.inbox_url,
                status_code=202,
                response_body="accepted",
                created_at=datetime(2026, 5, 21, 12, 6, tzinfo=UTC),
            )
        )

        assert store.get_follower(follower.actor) == follower
        assert store.list_followers(status="accepted") == [follower]
        assert store.list_outbox()[0].activity == outbox.activity
        assert store.list_deliveries(activity_id=outbox.activity_id) == [delivery]
        rejected = store.set_follower_status(actor=follower.actor, status="rejected")
        assert rejected is not None
        assert rejected.status == "rejected"
        assert store.list_followers(status="rejected") == [rejected]
        removed = store.set_follower_status(actor=follower.actor, status="removed")
        assert removed is not None
        assert removed.status == "removed"
        assert store.list_followers(status="removed") == [removed]
    finally:
        reset_engine()
        engine.dispose()


def test_activitypub_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_file = tmp_path / "activitypub.sqlite"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")

    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    try:
        inspector = inspect(engine)
        assert "activitypub_followers" in inspector.get_table_names()
        assert "activitypub_outbox" in inspector.get_table_names()
        assert "activitypub_delivery_attempts" in inspector.get_table_names()
    finally:
        engine.dispose()

    command.downgrade(cfg, "0016_staff_tokens_v12")
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    try:
        inspector = inspect(engine)
        assert "activitypub_followers" not in inspector.get_table_names()
        assert "activitypub_outbox" not in inspector.get_table_names()
        assert "activitypub_delivery_attempts" not in inspector.get_table_names()
    finally:
        engine.dispose()
