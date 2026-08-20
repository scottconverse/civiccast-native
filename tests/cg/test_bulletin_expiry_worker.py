# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 4b — daily bulletin expiry purge worker.

Covers civiccast.cg.bulletin_expiry_worker.BulletinExpiryWorker: the interval
gate (first tick fires, gated within the interval, fires again past it), the
retention grace (only bulletins expired longer than retention_days are swept),
and failure isolation (a raising purge is swallowed and does not hot-loop).
SQLite-backed store; a fixed clock + monotonic gate make it deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.cg.bulletin_expiry_worker import BulletinExpirySettings, BulletinExpiryWorker
from civiccast.cg.bulletin_store import PostgresCgBulletinStore
from civiccast.cg.models import CgBulletinSubmission
from civiccast.db import Base

# Fixed reference instant — must NEVER be made relative to datetime.now(). A
# wall-clock-relative seed here is the time-bomb pattern that broke the alerting
# support-bundle + programlog tests; bulletins below are seeded relative to this.
_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PostgresCgBulletinStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'expiry.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield PostgresCgBulletinStore(factory)
    finally:
        eng.dispose()


def _add(store: PostgresCgBulletinStore, submission_id: str, *, end: datetime) -> None:
    store.create(
        "public",
        CgBulletinSubmission(
            submission_id=submission_id,
            organization="Org",
            submitter_label="Volunteer",
            title="Notice",
            message="Body",
            target_zone_kind="ticker",
            state="scheduled",
            requested_end=end,
            approved_by_operator="op",
        ),
    )


def _worker(store: PostgresCgBulletinStore, **kwargs: object) -> BulletinExpiryWorker:
    return BulletinExpiryWorker(
        lambda: None,  # session factory unused: the store is injected
        store=store,
        clock=lambda: _NOW,
        settings=BulletinExpirySettings(**kwargs),  # type: ignore[arg-type]
    )


def test_first_tick_purges_then_gates_until_interval(store: PostgresCgBulletinStore) -> None:
    _add(store, "old", end=_NOW - timedelta(days=30))
    worker = _worker(store, purge_interval_seconds=3600.0, retention_days=7)
    assert worker.tick(monotonic=0.0) == 1  # first tick fires + purges the old bulletin
    assert worker.tick(monotonic=100.0) is None  # within the interval -> gated
    assert worker.tick(monotonic=3700.0) == 0  # past the interval -> fires, nothing left


def test_retention_grace_keeps_recently_expired(store: PostgresCgBulletinStore) -> None:
    _add(store, "recent", end=_NOW - timedelta(days=1))  # within the 7-day grace
    _add(store, "stale", end=_NOW - timedelta(days=10))  # beyond the grace
    worker = _worker(store, retention_days=7)
    assert worker.tick(monotonic=0.0) == 1  # only the stale one is swept
    assert {b.submission_id for b in store.list(channel_id="public")} == {"recent"}


def test_purge_failure_is_swallowed_and_does_not_hot_loop(store: PostgresCgBulletinStore) -> None:
    class _Boom:
        def delete_expired(self, *, before: datetime, channel_id: str | None = None) -> int:
            raise RuntimeError("db down")

    worker = BulletinExpiryWorker(
        lambda: None,
        store=_Boom(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
        settings=BulletinExpirySettings(purge_interval_seconds=3600.0),
    )
    assert worker.tick(monotonic=0.0) is None  # no exception escapes
    assert worker.tick(monotonic=100.0) is None  # interval advanced -> no hot loop
