# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 4 — community-bulletin expiration purge.

Covers PostgresCgBulletinStore.delete_expired: rows whose requested_end is
strictly before the cutoff are removed; open-ended bulletins (no requested_end)
and not-yet-expired bulletins are kept. The filler's time-window filter (tested
in tests/egress/test_bulletin_filler.py) already stops expired bulletins from
airing — this is the housekeeping that keeps the table bounded.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.cg.bulletin_store import PostgresCgBulletinStore
from civiccast.cg.models import CgBulletinSubmission
from civiccast.db import Base

_NOW = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PostgresCgBulletinStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'bulletins.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield PostgresCgBulletinStore(factory)
    finally:
        eng.dispose()


def _add(store: PostgresCgBulletinStore, submission_id: str, *, end: datetime | None) -> None:
    submission = CgBulletinSubmission(
        submission_id=submission_id,
        organization="Org",
        submitter_label="Volunteer",
        title="Notice",
        message="Body",
        target_zone_kind="ticker",
        state="scheduled",
        requested_end=end,
        approved_by_operator="op",
    )
    store.create("public", submission)


def test_delete_expired_removes_only_past_end_bulletins(store: PostgresCgBulletinStore) -> None:
    _add(store, "expired", end=_NOW - timedelta(hours=1))
    _add(store, "live", end=_NOW + timedelta(hours=1))
    _add(store, "open", end=None)  # open-ended -> never purged
    removed = store.delete_expired(before=_NOW)
    assert removed == 1
    remaining = {b.submission_id for b in store.list(channel_id="public")}
    assert remaining == {"live", "open"}


def test_delete_expired_is_idempotent(store: PostgresCgBulletinStore) -> None:
    _add(store, "expired", end=_NOW - timedelta(hours=2))
    assert store.delete_expired(before=_NOW) == 1
    assert store.delete_expired(before=_NOW) == 0  # nothing left to purge


def test_delete_expired_scopes_to_channel(store: PostgresCgBulletinStore) -> None:
    _add(store, "pub_expired", end=_NOW - timedelta(hours=1))
    store.create(
        "gov",
        CgBulletinSubmission(
            submission_id="gov_expired",
            organization="Org",
            submitter_label="Vol",
            title="Notice",
            message="Body",
            target_zone_kind="ticker",
            state="scheduled",
            requested_end=_NOW - timedelta(hours=1),
            approved_by_operator="op",
        ),
    )
    removed = store.delete_expired(before=_NOW, channel_id="public")
    assert removed == 1
    assert {b.submission_id for b in store.list(channel_id="gov")} == {"gov_expired"}
