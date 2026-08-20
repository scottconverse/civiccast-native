# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff token lifecycle tests for v1.2 hardening."""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from civiccast.app import create_app
from civiccast.auth.store import (
    InMemoryStaffTokenStore,
    PostgresStaffTokenStore,
    StaffTokenRevokedError,
    StaffTokenUpgradeRequiredError,
    new_audit_event_id,
)
from tests.support.docker_engine import docker_engine_available

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:
    PostgresContainer = None  # type: ignore[misc,assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def real_postgres_url() -> Iterator[str]:
    """Provide real Postgres or fail loud when CI requires the boundary."""

    from tests._postgres_harness import fresh_database_from_env

    with fresh_database_from_env() as external_url:
        if external_url is not None:
            yield external_url
            return
        if PostgresContainer is None or not docker_engine_available():
            if os.environ.get("CIVICCAST_RUN_POSTGRES_TESTS"):
                pytest.fail("Staff-auth Postgres tests required by env but Docker unavailable")
            pytest.skip("No external Postgres or Docker available for staff-auth tests")
        container = PostgresContainer("postgres:17", driver="psycopg")
        container.start()
        try:
            yield container.get_connection_url()
        finally:
            container.stop()


def _make_cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_in_memory_lifecycle_hashes_revokes_rotates_and_audits() -> None:
    store = InMemoryStaffTokenStore()

    issued = store.issue_token(
        operator_id="clerk-a",
        operator_display_name="Clerk A",
        scopes=("operator", "records"),
    )
    assert issued.secret.startswith(f"ccst_{issued.metadata.token_id}_")
    identity = store.verify_token(issued.secret)
    assert identity.operator_id == "clerk-a"
    assert identity.token_id == issued.metadata.token_id

    store.revoke_token(issued.metadata.token_id, reason="offboarding")
    with pytest.raises(StaffTokenRevokedError):
        store.verify_token(issued.secret)

    replacement_source = store.issue_token(
        operator_id="clerk-b",
        operator_display_name="Clerk B",
    )
    replacement = store.rotate_token(replacement_source.metadata.token_id)
    assert replacement.metadata.rotated_from_token_id == replacement_source.metadata.token_id
    assert store.verify_token(replacement.secret).operator_id == "clerk-b"
    with pytest.raises(StaffTokenRevokedError):
        store.verify_token(replacement_source.secret)

    event_types = [event.event_type for event in store.audit_events()]
    assert event_types.count("issued") == 3
    assert "used" in event_types
    assert "revoked" in event_types
    assert "rotated" in event_types


def test_lifecycle_store_can_match_full_token_fingerprint_without_pbkdf2() -> None:
    store = InMemoryStaffTokenStore()
    issued = store.issue_token(
        operator_id="operator-a",
        operator_display_name="Operator A",
    )

    assert store.matches_token_fingerprint(issued.secret) is True
    assert store.matches_token_fingerprint(f"{issued.secret}-wrong") is False
    assert store.matches_token_fingerprint("ccst_unknown_guess") is False


def test_database_lifecycle_never_persists_bearer_secret(tmp_path: Path) -> None:
    db_file = tmp_path / "auth.sqlite"
    db_url = f"sqlite:///{db_file.as_posix()}"
    command.upgrade(_make_cfg(db_url), "head")
    engine = create_engine(db_url, future=True)

    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresStaffTokenStore(session_factory)
        issued = store.issue_token(
            operator_id="clerk-a",
            operator_display_name="Clerk A",
        )

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT token_hash, salt_b64 FROM staff_tokens WHERE token_id = :token_id"),
                {"token_id": issued.metadata.token_id},
            ).one()
        assert issued.secret not in row.token_hash
        assert issued.secret not in row.salt_b64
        assert store.verify_token(issued.secret).operator_display_name == "Clerk A"

        store.revoke_token(issued.metadata.token_id, reason="lost-device")
        with pytest.raises(StaffTokenRevokedError):
            store.verify_token(issued.secret)
        events = store.audit_events()
        assert [event.event_type for event in events] == ["issued", "used", "revoked"]
        assert all(event.operator_id == "clerk-a" for event in events)
    finally:
        engine.dispose()


def test_legacy_lifecycle_token_requires_rotation_before_authentication(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy-auth.sqlite"
    db_url = f"sqlite:///{db_file.as_posix()}"
    command.upgrade(_make_cfg(db_url), "head")
    engine = create_engine(db_url, future=True)
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresStaffTokenStore(session_factory)
        issued = store.issue_token(
            operator_id="legacy-operator",
            operator_display_name="Legacy Operator",
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE staff_tokens SET token_hash = "
                    "substr(token_hash, 1, instr(token_hash, '$sha256$') - 1) "
                    "WHERE token_id = :token_id"
                ),
                {"token_id": issued.metadata.token_id},
            )

        assert store.matches_token_fingerprint(issued.secret) is False
        with pytest.raises(StaffTokenUpgradeRequiredError, match="civiccast token rotate"):
            store.verify_token(issued.secret)

        replacement = store.rotate_token(issued.metadata.token_id)
        assert store.matches_token_fingerprint(replacement.secret) is True
        assert store.verify_token(replacement.secret).operator_id == "legacy-operator"
    finally:
        engine.dispose()


def test_audit_event_ids_are_strictly_increasing_under_timestamp_collisions() -> None:
    """Regression pin for issue #120 (fixed in d60a0e6).

    Audit-event ordering once flipped nondeterministically on Postgres when
    issue/use/revoke collided on ``created_at`` (the Windows wall clock
    quantizes at ~15.6ms). The fix made ``new_audit_event_id()`` a time-ordered
    id with a per-process monotonic sequence so ``ORDER BY created_at,
    event_id`` is stable insertion order. A tight generation loop guarantees
    timestamp collisions; the ids must still sort in generation order.
    """

    ids = [new_audit_event_id() for _ in range(10_000)]
    assert all(a < b for a, b in itertools.pairwise(ids)), (
        "new_audit_event_id() must be strictly increasing even when "
        "consecutive ids share a wall-clock timestamp"
    )


def test_postgres_audit_order_is_deterministic_under_collisions(
    real_postgres_url: str,
) -> None:
    """Regression pin for issue #120 on the real flake surface (Postgres).

    SQLite masked the original flake with stable scan order; only Postgres
    reordered same-``created_at`` rows. Run the full lifecycle repeatedly in a
    tight loop (deliberate ``created_at`` collisions) on a fresh real-Postgres
    database and require the exact audit order every time.
    """

    command.upgrade(_make_cfg(real_postgres_url), "head")
    engine = create_engine(real_postgres_url, future=True)
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresStaffTokenStore(session_factory)
        expected: list[str] = []
        tracked_token_ids: set[str] = set()
        for round_number in range(20):
            issued = store.issue_token(
                operator_id=f"clerk-{round_number}",
                operator_display_name=f"Clerk {round_number}",
            )
            tracked_token_ids.add(issued.metadata.token_id)
            store.verify_token(issued.secret)
            store.revoke_token(issued.metadata.token_id, reason="cycle")
            rotated_source = store.issue_token(
                operator_id=f"clerk-{round_number}",
                operator_display_name=f"Clerk {round_number}",
            )
            tracked_token_ids.add(rotated_source.metadata.token_id)
            replacement = store.rotate_token(rotated_source.metadata.token_id)
            tracked_token_ids.add(replacement.metadata.token_id)
            expected += ["issued", "used", "revoked", "issued", "revoked", "rotated"]
            observed = [
                event.event_type
                for event in store.audit_events()
                if event.token_id in tracked_token_ids
            ]
            assert observed == expected, (
                f"audit order diverged in round {round_number}: {observed[-8:]!r}"
            )
    finally:
        engine.dispose()


def test_real_postgres_valid_token_survives_shared_ip_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
    real_postgres_url: str,
) -> None:
    """The production token store preserves valid access behind a noisy NAT."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    command.upgrade(_make_cfg(real_postgres_url), "head")
    engine = create_engine(real_postgres_url, future=True)
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresStaffTokenStore(session_factory)
        issued = store.issue_token(
            operator_id="postgres-operator",
            operator_display_name="Postgres Operator",
            scopes=("operator",),
        )
        app = create_app()
        app.state.staff_token_store = store
        client = TestClient(app)
        bad = {"Authorization": "Bearer guessed-token"}
        valid = {"Authorization": f"Bearer {issued.secret}"}

        assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
        assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
        assert client.get("/api/staff/installer/summary", headers=valid).status_code == 200
        limited = client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer another-guessed-token"},
        )
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
    finally:
        engine.dispose()


def test_staff_middleware_uses_lifecycle_store_and_rejects_revoked_token() -> None:
    store = InMemoryStaffTokenStore()
    issued = store.issue_token(
        operator_id="operator-a",
        operator_display_name="Operator A",
    )
    app = create_app()
    app.state.staff_token_store = store
    client = TestClient(app, headers={"Authorization": f"Bearer {issued.secret}"})

    ok = client.get("/api/staff/installer/first-run-plan")
    assert ok.status_code == 200

    store.revoke_token(issued.metadata.token_id, reason="rotation-test")
    revoked = client.get("/api/staff/installer/first-run-plan")
    assert revoked.status_code == 401
    assert "revoked" in revoked.json()["detail"]
