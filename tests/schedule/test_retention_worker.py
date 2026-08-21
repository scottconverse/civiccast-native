# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retention enforcement worker tests (Stage F).

Nothing previously acted on ``assets.retention_until`` — retention schedules
were decorative. The worker makes expiry visible and auditable: expired,
non-permanent assets are flagged exactly once into the durable disposition
review queue surfaced to records clerks. It never deletes anything —
automatic purge is an explicit pending product decision (see the stage plan).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.models import Asset
from civiccast.schedule.retention_worker import (
    RetentionEnforcementWorker,
    RetentionWorkerSettings,
)

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _seed_asset(
    engine: Engine,
    asset_id: str,
    *,
    retention_policy: str = "meeting",
    retention_until: datetime | None = None,
    legal_hold: bool = False,
) -> None:
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title=f"Asset {asset_id}",
                state="validated",
                manifest_url=None,
                retention_policy=retention_policy,
                retention_until=retention_until,
                legal_hold=legal_hold,
            )
        )
        session.commit()


def _worker(session_factory) -> RetentionEnforcementWorker:  # type: ignore[no-untyped-def]
    return RetentionEnforcementWorker(
        session_factory,
        settings=RetentionWorkerSettings(mode="inline", poll_seconds=3600.0),
    )


class TestFlagging:
    def test_expired_asset_is_flagged_for_review(self, engine: Engine, session_factory) -> None:
        _seed_asset(engine, "expired-1", retention_until=_NOW - timedelta(days=3))
        worker = _worker(session_factory)

        flagged = worker.run_once(now=_NOW)

        assert [row.asset_id for row in flagged] == ["expired-1"]
        assert flagged[0].status == "pending_review"
        assert flagged[0].retention_policy == "meeting"
        assert flagged[0].retention_until == _NOW - timedelta(days=3)

    def test_flagging_is_idempotent_across_scans(self, engine: Engine, session_factory) -> None:
        _seed_asset(engine, "expired-1", retention_until=_NOW - timedelta(days=3))
        worker = _worker(session_factory)

        first = worker.run_once(now=_NOW)
        second = worker.run_once(now=_NOW + timedelta(hours=1))

        assert len(first) == 1
        assert second == [], "an already-flagged asset must not be re-flagged"
        assert len(worker.list_disposition_reviews()) == 1

    def test_legal_hold_blocks_flagging_even_when_expired(
        self, engine: Engine, session_factory
    ) -> None:
        # S7 media lifecycle / CLAUDE.md §4.6: a legal hold blocks expiry
        # outright, no matter how far past retention_until the asset is.
        _seed_asset(
            engine,
            "held-1",
            retention_until=_NOW - timedelta(days=400),
            legal_hold=True,
        )
        assert _worker(session_factory).run_once(now=_NOW) == []
        assert _worker(session_factory).list_disposition_reviews() == []

    def test_clearing_legal_hold_lets_the_next_scan_flag_it(
        self, engine: Engine, session_factory
    ) -> None:
        _seed_asset(
            engine,
            "held-1",
            retention_until=_NOW - timedelta(days=400),
            legal_hold=True,
        )
        worker = _worker(session_factory)
        assert worker.run_once(now=_NOW) == []

        with Session(bind=engine) as session:
            row = session.get(Asset, "held-1")
            assert row is not None
            row.legal_hold = False
            session.commit()

        flagged = worker.run_once(now=_NOW + timedelta(hours=1))
        assert [row.asset_id for row in flagged] == ["held-1"]

    def test_permanent_assets_are_never_flagged(self, engine: Engine, session_factory) -> None:
        _seed_asset(
            engine,
            "permanent-1",
            retention_policy="permanent",
            retention_until=_NOW - timedelta(days=400),
        )
        assert _worker(session_factory).run_once(now=_NOW) == []

    def test_future_and_null_retention_are_not_flagged(
        self, engine: Engine, session_factory
    ) -> None:
        _seed_asset(engine, "future-1", retention_until=_NOW + timedelta(days=30))
        _seed_asset(engine, "no-schedule-1", retention_until=None)
        assert _worker(session_factory).run_once(now=_NOW) == []

    def test_worker_never_mutates_or_deletes_assets(self, engine: Engine, session_factory) -> None:
        _seed_asset(engine, "expired-1", retention_until=_NOW - timedelta(days=3))
        _worker(session_factory).run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(Asset, "expired-1")
            assert row is not None
            assert row.state == "validated"
            stored_until = row.retention_until
            if stored_until is not None and stored_until.tzinfo is None:
                stored_until = stored_until.replace(tzinfo=UTC)  # SQLite drops tz
            assert stored_until == _NOW - timedelta(days=3)


class TestSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("CIVICCAST_RETENTION_WORKER", "CIVICCAST_RETENTION_POLL_SECONDS"):
            monkeypatch.delenv(name, raising=False)
        settings = RetentionWorkerSettings.from_env()
        assert settings.mode == "inline"
        assert settings.poll_seconds == 3600.0

    def test_invalid_mode_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_RETENTION_WORKER", "auto")
        with pytest.raises(ValueError, match="CIVICCAST_RETENTION_WORKER"):
            RetentionWorkerSettings.from_env()


class TestDispositionQueueEndpoint:
    def test_records_clerk_can_read_disposition_queue(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pathlib import Path

        from alembic import command
        from alembic.config import Config
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        db_path = tmp_path / "retention.db"
        repo_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS",
            "records-token:records-1:Records Clerk:records_clerk",
        )
        monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
        monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
        monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_RETRY_WORKER", "off")
        monkeypatch.setenv("CIVICCAST_RETENTION_WORKER", "off")

        engine = create_engine(f"sqlite:///{db_path}", future=True).execution_options(
            schema_translate_map={"civiccast": None}
        )
        _seed_asset(engine, "expired-q1", retention_until=_NOW - timedelta(days=10))

        @contextmanager
        def factory() -> Iterator[Session]:
            with Session(bind=engine) as session:
                yield session

        RetentionEnforcementWorker(
            factory, settings=RetentionWorkerSettings(mode="inline", poll_seconds=3600.0)
        ).run_once(now=_NOW)
        engine.dispose()

        with TestClient(create_app()) as client:
            unauthenticated = client.get("/api/staff/records/disposition-queue")
            assert unauthenticated.status_code == 401
            response = client.get(
                "/api/staff/records/disposition-queue",
                headers={"Authorization": "Bearer records-token"},
            )
            assert response.status_code == 200, response.text
            rows = response.json()
            assert [row["asset_id"] for row in rows] == ["expired-q1"]
            assert rows[0]["status"] == "pending_review"
