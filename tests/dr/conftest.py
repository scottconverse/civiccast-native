# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared fixtures for the disaster-recovery drill tests.

A real, alembic-migrated SQLite database (not ``Base.metadata.create_all``,
which lands tables in the wrong place for a file-based engine — see
``civiccast.dr.backup.build_sqlite_engine``'s docstring) seeded with a
handful of representative rows via the app's own stores.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from civiccast.dr.backup import build_sqlite_engine
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.store import PostgresEgressStore
from civiccast.installer.storage import _run_migrations
from civiccast.schedule.models import ScheduleItemCreate
from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore
from civiccast.vod.models import AssetMetadata


@pytest.fixture
def seeded_station_db(tmp_path: Path) -> Iterator[Path]:
    """A real alembic-migrated station SQLite file with representative rows."""

    db_path = tmp_path / "station.sqlite3"
    _run_migrations(f"sqlite:///{db_path}")

    engine = build_sqlite_engine(db_path)
    session_factory = sessionmaker(bind=engine, future=True)
    asset_store = PostgresAssetStore(session_factory)
    schedule_store = PostgresScheduleStore(session_factory)
    egress_store = PostgresEgressStore(session_factory)

    for i in range(2):
        asset_store.create(
            AssetMetadata(
                asset_id=f"council-meeting-{i}",
                title=f"City Council Meeting {i}",
                manifest_url=f"https://media.example.gov/council-{i}/master.m3u8",
                duration_seconds=1800 + i,
                published_at=datetime.now(UTC),
            )
        )
    schedule_store.create(
        ScheduleItemCreate(
            asset_id="council-meeting-0",
            channel_id="gov-ch12",
            mode="premiere",
            scheduled_at=datetime.now(UTC),
            duration_seconds=1800,
        )
    )
    egress_store.upsert_config(
        EgressConfig(
            channel_id="gov-ch12",
            enabled=True,
            slate_message="Test slate.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
        )
    )
    engine.dispose()
    yield db_path
