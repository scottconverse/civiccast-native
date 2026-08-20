# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared fixtures for the civiccast.schedule test suite.

Mirrors:
  - tests/db/conftest.py:25-38  — bind_engine + reset_engine SQLite fixture (Pattern B)
  - tests/vod/test_store.py:11-16 — Pydantic-validated AssetMetadata factory (Pattern E)

Per plan.md §2 Files-to-create row `tests/schedule/conftest.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base, bind_engine, reset_engine
from civiccast.vod.models import AssetMetadata


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Per-test ephemeral SQLite engine bound via the public bind_engine API.

    Mirrors tests/db/conftest.py:25-38. Imports civiccast.schedule.models so the
    Asset SA model is registered against Base.metadata before create_all runs.
    """
    # Import the schedule package's SA model so it registers against
    # Base.metadata before create_all. This import is also the trigger
    # for the failing-tests "ModuleNotFoundError: civiccast.schedule.models"
    # mode prior to executor implementation.
    import civiccast.schedule.models  # noqa: F401

    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):
    """Yield a session-factory callable shaped like the PostgresAssetStore
    constructor parameter: a context-manager-yielding factory bound to the
    ephemeral SQLite engine.

    Does NOT seed any Asset rows — the AssetStore conformance tests need
    a clean store. Schedule-side tests that need pre-existing assets (the
    QA-004 existence check) use ``schedule_session_factory`` instead,
    which wraps this fixture and seeds.
    """

    @contextmanager
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    return _factory


# Asset IDs used by the schedule-side test fixtures (test_payload helpers,
# test_schedule_router fixtures, test_schedule_store helpers, etc.). Add
# new ids here when a new schedule test introduces one. Do NOT add ids
# used by the AssetStore conformance suite — those tests insert assets
# themselves and a pre-seed would IntegrityError.
_SCHEDULE_TEST_ASSET_IDS = (
    "abc-123",
    "city-council-2026-05-08",
    "gov-1",
    "gov-2",
    "edu-1",
    "meeting-x",
    "meeting-y",
    "embargo-1",
    "full-1",
    "rt-full",
    "rt-min",
    "real-pg-create-1",
    "real-pg-list-1",
    "test-upload-01",
    "live-meeting",
    "rejected-1",
    "council-2026-05-08",
)


def _seed_schedule_assets(factory) -> None:
    """Insert canonical Asset rows for the schedule-store test suite.

    Idempotent: skips ids already present so the fixture can be re-applied
    without IntegrityError on shared engines.
    """
    from sqlalchemy import select

    from civiccast.schedule.models import Asset

    with factory() as sess:
        existing = {
            row[0]
            for row in sess.execute(
                select(Asset.asset_id).where(Asset.asset_id.in_(_SCHEDULE_TEST_ASSET_IDS))
            )
        }
        for asset_id in _SCHEDULE_TEST_ASSET_IDS:
            if asset_id in existing:
                continue
            sess.add(
                Asset(
                    asset_id=asset_id,
                    title=f"Test asset {asset_id}",
                    state="validated",
                )
            )
        sess.commit()


@pytest.fixture
def schedule_session_factory(session_factory):
    """Schedule-suite session factory: pre-seeds Asset rows referenced by
    schedule tests so the QA-004 asset-existence check doesn't 404 every
    schedule_items insert.
    """
    _seed_schedule_assets(session_factory)
    return session_factory


def _make_asset(
    asset_id: str = "abc123",
    *,
    title: str = "Test asset",
    manifest_url: str = "https://cdn.example/abc/playlist.m3u8",
    description: str | None = None,
    poster_url: str | None = None,
    duration_seconds: int | None = None,
    published_at=None,
) -> AssetMetadata:
    """Pydantic factory mirroring tests/vod/test_store.py:11-16."""
    return AssetMetadata(
        asset_id=asset_id,
        title=title,
        description=description,
        manifest_url=manifest_url,  # type: ignore[arg-type]
        poster_url=poster_url,  # type: ignore[arg-type]
        duration_seconds=duration_seconds,
        published_at=published_at,
    )
