# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-Postgres tests bound by ADR 0008 §Compliance.

Per Director Decision 1: testcontainers spins up `postgres:17` per session.
Skip-marked when Docker / testcontainers is unavailable so non-Docker dev
environments still get a green pytest run on everything else.

Per plan.md §4 `tests/schedule/test_real_postgres.py`. Closes the
SQLite-vs-Postgres divergence risk that ADR 0008 §Compliance deferred from
task 1a — the SINGLE most load-bearing test in this run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

# Importing the schedule module's models forces SA registration with
# Base.metadata so the migration's reversibility introspection works.
import civiccast.schedule.models  # noqa: F401
from tests.support.docker_engine import docker_engine_available

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _docker_available() -> bool:
    """Probe for a reachable container engine without opening a socket.

    Delegates to the shared helper so all real-Postgres/real-boundary suites
    share one probe. The filesystem/pipe fast paths open no socket, so pytest's
    ``filterwarnings=error`` never promotes a leaked-connection ResourceWarning
    into a teardown ERROR (CI cleanroom on PR #7 caught that twice).
    """
    return docker_engine_available()


_TESTCONTAINERS_OK: bool
try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    _TESTCONTAINERS_OK = True
except ImportError:
    _TESTCONTAINERS_OK = False
    PostgresContainer = None  # type: ignore[misc,assignment]


_SKIP_REASON = "Docker unavailable; ADR 0008 §Compliance test cannot run"


def _skip_if_no_postgres() -> None:
    """Honor CIVICCAST_RUN_POSTGRES_TESTS — when set, fail loud rather than skip."""
    import os

    if not _TESTCONTAINERS_OK or not _docker_available():
        if os.environ.get("CIVICCAST_RUN_POSTGRES_TESTS"):
            pytest.fail("Postgres tests required by env but Docker unavailable")
        pytest.skip(_SKIP_REASON)


@pytest.fixture(scope="module")
def postgres_url():
    from tests._postgres_harness import fresh_database_from_env

    with fresh_database_from_env() as external_url:
        if external_url is not None:
            yield external_url
            return
        _skip_if_no_postgres()
        # driver="psycopg" tells testcontainers to construct
        # postgresql+psycopg://... URLs (psycopg v3) instead of the
        # default postgresql+psycopg2://... (legacy v2). ADR 0008
        # standardizes on psycopg v3; psycopg2 is not a project dep,
        # so the default URL would crash with ModuleNotFoundError on
        # any environment without psycopg2 stale-installed.
        container = PostgresContainer("postgres:17", driver="psycopg")
        container.start()
        try:
            yield container.get_connection_url()
        finally:
            container.stop()


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


# Asset IDs the schedule-conflict tests in this file create ScheduleItem
# rows against. Audit-team v0.3.0 QA-004 added a foreign-existence check
# at the application layer (see ``PostgresScheduleStore.create``). Each
# real-Postgres test seeds these Asset rows after ``alembic upgrade head``
# so the existence check passes; the conflict-detection contract — which
# is what these tests are about — remains the thing under test.
_REAL_PG_TEST_ASSET_IDS = (
    "meeting-1",
    "meeting-2",
    "meeting-x",
    "meeting-y",
    "live-meeting",
    "embargo-1",
    # NOTE: ``real-pg-create-1`` and ``real-pg-list-1`` are deliberately
    # NOT in this list. The AssetStore round-trip tests
    # (TestRealPostgresStoreListAndCreate) insert those asset_ids
    # themselves via ``store.create(AssetMetadata(...))`` to exercise the
    # AssetStore Protocol. Pre-seeding them here would IntegrityError on
    # the duplicate insert. The downgrade test (TestRealPostgresDowngrade-
    # CleansSchema) also depends on the only rows present at that point
    # being the round-trip-tests' rows (which have manifest_url filled),
    # not the schedule-tests' seeded rows (which have manifest_url=NULL
    # and would trip migration 0002's down NOT-NULL re-imposition).
)


def _seed_test_assets(engine: object, asset_ids: tuple[str, ...] = _REAL_PG_TEST_ASSET_IDS) -> None:
    """Insert canonical Asset rows on the given real-Postgres engine.

    Idempotent: skips ids already present so a test that runs in the same
    session-scoped Postgres container does not IntegrityError.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from civiccast.schedule.models import Asset

    with Session(bind=engine) as sess:  # type: ignore[arg-type]
        existing = {
            row[0]
            for row in sess.execute(select(Asset.asset_id).where(Asset.asset_id.in_(asset_ids)))
        }
        for asset_id in asset_ids:
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


class TestRealPostgresSchemaNamespace:
    """Locks: after `upgrade head`, the assets table lands in the `civiccast`
    schema namespace on a real Postgres dialect (not the SQLite no-op path).
    This is the ADR 0008 §Compliance-bound assertion."""

    def test_civiccast_assets_table_exists_in_information_schema(self, postgres_url) -> None:
        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            with eng.connect() as conn:
                # Ensure the schema exists (the migration or env should create it).
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS civiccast"))
                rows = conn.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema = 'civiccast' AND table_name = 'assets'"
                    )
                ).fetchall()
            assert len(rows) == 1
        finally:
            eng.dispose()


class TestRealPostgresAlembicVersionTable:
    """Locks: alembic_version table lives in the civiccast schema namespace
    (proves version_table_schema='civiccast' is honored at DDL time, the
    runtime evolution of the static-text assertion at
    tests/db/test_alembic_env.py:163-183)."""

    def test_alembic_version_table_in_civiccast_schema(self, postgres_url) -> None:
        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema = 'civiccast' AND table_name = 'alembic_version'"
                    )
                ).fetchall()
            assert len(rows) == 1
        finally:
            eng.dispose()


class TestRealPostgresStoreListAndCreate:
    """Locks (per Q7 + plan-gate amendment): one list() round-trip + one
    create() round-trip on real Postgres confirm the new methods work at
    the SA dialect boundary, complementing the SQLite conformance suite."""

    def test_list_round_trip_against_real_postgres(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from sqlalchemy.orm import Session

        from civiccast.schedule.store import PostgresAssetStore
        from civiccast.vod.models import AssetMetadata

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            # No _seed_test_assets() here — this is an AssetStore round-
            # trip test that inserts its own asset via store.create().

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresAssetStore(_factory)
            asset = AssetMetadata(
                asset_id="real-pg-list-1",
                title="Real PG list",
                manifest_url="https://cdn.example/rpg/playlist.m3u8",  # type: ignore[arg-type]
            )
            store.create(asset)
            result = store.list()
            assert any(a.asset_id == "real-pg-list-1" for a in result)
        finally:
            eng.dispose()

    def test_create_round_trip_against_real_postgres(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from sqlalchemy.orm import Session

        from civiccast.schedule.store import PostgresAssetStore
        from civiccast.vod.models import AssetMetadata

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            # No _seed_test_assets() here — this is an AssetStore round-
            # trip test that inserts its own asset via store.create().

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresAssetStore(_factory)
            asset = AssetMetadata(
                asset_id="real-pg-create-1",
                title="Real PG create",
                manifest_url="https://cdn.example/rpg2/playlist.m3u8",  # type: ignore[arg-type]
            )
            returned = store.create(asset)
            assert returned.asset_id == "real-pg-create-1"
            out = store.get("real-pg-create-1")
            assert out is not None
            assert out.asset_id == "real-pg-create-1"
            assert out.title == "Real PG create"
        finally:
            eng.dispose()


class TestRealPostgresDowngradeCleansSchema:
    """Locks: `downgrade base` removes the civiccast.assets table on real
    Postgres — proves symmetry on a dialect that actually honors schemas."""

    def test_downgrade_base_removes_assets_from_civiccast_schema(self, postgres_url) -> None:
        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            # This module's ``postgres_url`` fixture is module-scoped: every
            # test in this file shares one throwaway Postgres DB. Several
            # other tests seed ``civiccast.assets`` rows and do not delete
            # them afterward -- e.g. ``_seed_test_assets`` (manifest_url is
            # NULL on those rows, which migration 0002's downgrade would
            # reject when it re-imposes the NOT NULL constraint) and
            # TestRealPostgresAssetStateMigrationReversible (leaves
            # state='recorded' rows behind, which migration 0006's
            # downgrade guard refuses to run past). Under a fixed file
            # order this test happens to run before those seed rows exist;
            # under pytest-randomly it can run after, and `downgrade base`
            # would then fail on data this test neither created nor has any
            # interest in. This test's only claim is "downgrade base drops
            # the civiccast.assets table" -- clear both tables first (FK
            # order: schedule_items before assets) so the test is
            # order-independent without weakening either migration guard.
            with eng.begin() as conn:
                conn.execute(text("DELETE FROM civiccast.schedule_items"))
                conn.execute(text("DELETE FROM civiccast.assets"))
            command.downgrade(cfg, "base")
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema = 'civiccast' AND table_name = 'assets'"
                    )
                ).fetchall()
            assert len(rows) == 0
        finally:
            eng.dispose()


class TestRealPostgresFractionalTrim:
    """Locks: Sprint 0.4 fractional trims survive the real Postgres boundary."""

    def test_fractional_trim_columns_are_numeric_and_round_trip(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import AssetMetadataUpdate
        from civiccast.schedule.store import PostgresAssetStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            with eng.connect() as conn:
                column_rows = conn.execute(
                    text(
                        "SELECT column_name, data_type, numeric_precision, numeric_scale "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'civiccast' "
                        "AND table_name = 'assets' "
                        "AND column_name IN ('trim_in_seconds', 'trim_out_seconds') "
                        "ORDER BY column_name"
                    )
                ).fetchall()
            assert [(r[1], r[2], r[3]) for r in column_rows] == [
                ("numeric", 10, 3),
                ("numeric", 10, 3),
            ]

            _seed_test_assets(eng, ("fractional-trim-asset",))

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresAssetStore(_factory)
            row = store.update_metadata(
                "fractional-trim-asset",
                AssetMetadataUpdate(
                    expected_version=1,
                    trim_in_seconds=1.5,
                    trim_out_seconds=2.333,
                ),
            )
            assert row.trim_in_seconds == 1.5
            assert row.trim_out_seconds == 2.333

            reloaded = store.get_staff_row("fractional-trim-asset")
            assert reloaded is not None
            assert reloaded.trim_in_seconds == 1.5
            assert reloaded.trim_out_seconds == 2.333
        finally:
            eng.dispose()

    def test_fractional_trim_migration_downgrades_and_reupgrades(self, postgres_url) -> None:
        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0009_live_sources_index")
        eng = create_engine(postgres_url, future=True)
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, data_type "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'civiccast' "
                        "AND table_name = 'assets' "
                        "AND column_name IN ('trim_in_seconds', 'trim_out_seconds') "
                        "ORDER BY column_name"
                    )
                ).fetchall()
            assert [(r[0], r[1]) for r in rows] == [
                ("trim_in_seconds", "integer"),
                ("trim_out_seconds", "integer"),
            ]
        finally:
            eng.dispose()
        command.upgrade(cfg, "head")


class TestRealPostgresScheduleConflictDetection:
    """Locks: the btree_gist EXCLUDE constraint from migration 0003 (rebuilt
    by migration 0005) actually rejects overlapping premiere events on the
    same channel.

    SQLite cannot enforce the EXCLUDE constraint, so this is the only
    place the conflict-detection contract gets exercised end-to-end. The
    hypothesis-based property tests in
    ``tests/schedule/test_schedule_conflict_properties.py`` lock the
    *logic* of overlap independent of the DB; this fixture proves the
    constraint *is wired* on real Postgres.
    """

    def test_overlapping_live_on_same_channel_rejected(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import (
            PostgresScheduleStore,
            ScheduleConflictError,
        )

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            base_when = datetime.now(UTC) + timedelta(hours=1)

            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-1",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base_when,
                    duration_seconds=3 * 3600,
                )
            )

            # Insert a second live event that starts inside the first's
            # window — must be rejected as a ScheduleConflictError.
            with pytest.raises(ScheduleConflictError) as exc_info:
                store.create(
                    ScheduleItemCreate(
                        asset_id="meeting-2",
                        channel_id="gov-ch12",
                        mode=SCHEDULE_MODE_PREMIERE,
                        scheduled_at=base_when + timedelta(hours=1),
                        duration_seconds=3600,
                    )
                )
            # The store should have looked up the existing conflicting row.
            assert exc_info.value.conflicting_item is not None
            assert exc_info.value.conflicting_item.asset_id == "meeting-1"
        finally:
            eng.dispose()

    def test_non_overlapping_same_channel_succeeds(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            base = datetime.now(UTC) + timedelta(hours=1)

            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-x",
                    channel_id="channel-non-overlap",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base,
                    duration_seconds=3600,
                )
            )
            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-y",
                    channel_id="channel-non-overlap",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base + timedelta(hours=2),
                    duration_seconds=3600,
                )
            )
            assert len(store.list(channel_id="channel-non-overlap")) == 2
        finally:
            eng.dispose()

    def test_overlapping_different_channels_succeeds(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            when = datetime.now(UTC) + timedelta(hours=1)

            # Identical times, different channels — must not conflict.
            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-x",
                    channel_id="channel-diff-a",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=when,
                    duration_seconds=3600,
                )
            )
            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-y",
                    channel_id="channel-diff-b",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=when,
                    duration_seconds=3600,
                )
            )
            assert (
                len(store.list(channel_id="channel-diff-a"))
                + len(store.list(channel_id="channel-diff-b"))
                == 2
            )
        finally:
            eng.dispose()

    def test_embargo_never_conflicts(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_EMBARGO,
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            when = datetime.now(UTC) + timedelta(hours=1)

            # Live event occupies a 3-hour block on gov-ch12.
            store.create(
                ScheduleItemCreate(
                    asset_id="live-meeting",
                    channel_id="channel-embargo",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=when,
                    duration_seconds=3 * 3600,
                )
            )
            # An embargo at the same moment on the same channel — must succeed
            # (embargo is exempt from the EXCLUDE WHERE clause).
            store.create(
                ScheduleItemCreate(
                    asset_id="embargo-1",
                    channel_id="channel-embargo",
                    mode=SCHEDULE_MODE_EMBARGO,
                    scheduled_at=when,
                )
            )
            assert len(store.list(channel_id="channel-embargo")) == 2
        finally:
            eng.dispose()

    def test_cancelled_event_frees_the_slot(self, postgres_url) -> None:
        """Locks: an event in 'cancelled' state no longer occupies its slot.
        A new live event for the same window must succeed after cancel."""
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            when = datetime.now(UTC) + timedelta(hours=1)

            first = store.create(
                ScheduleItemCreate(
                    asset_id="meeting-x",
                    channel_id="channel-cancel",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=when,
                    duration_seconds=3600,
                )
            )
            # Cancel it → state moves to 'cancelled'; EXCLUDE clause excludes it.
            store.cancel(first.id)
            # Now a new event in the same slot must succeed.
            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-y",
                    channel_id="channel-cancel",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=when,
                    duration_seconds=3600,
                )
            )
            assert (
                len([r for r in store.list(channel_id="channel-cancel") if r.state == "scheduled"])
                == 1
            )
        finally:
            eng.dispose()


class TestRealPostgres0071PublishedBlocksOverlap:
    """Locks migration 0071_published_blocks_overlap: the
    ``schedule_items_no_overlap`` EXCLUDE constraint now rejects an
    overlapping insert against an already-``published`` premiere (not
    just ``scheduled``), and the downgrade restores the migration-0005
    scheduled-only predicate.
    """

    def test_overlapping_published_on_same_channel_rejected(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_PUBLISHED,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import (
            PostgresScheduleStore,
            ScheduleConflictError,
        )

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            base_when = datetime.now(UTC) + timedelta(hours=1)

            published = store.create(
                ScheduleItemCreate(
                    asset_id="meeting-1",
                    channel_id="ch-0071-published",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base_when,
                    duration_seconds=3 * 3600,
                )
            )
            store.mark_published([published.id])

            # A new scheduled premiere overlapping the published item's
            # window must be rejected, exactly like it would be against a
            # still-scheduled item.
            with pytest.raises(ScheduleConflictError) as exc_info:
                store.create(
                    ScheduleItemCreate(
                        asset_id="meeting-2",
                        channel_id="ch-0071-published",
                        mode=SCHEDULE_MODE_PREMIERE,
                        scheduled_at=base_when + timedelta(hours=1),
                        duration_seconds=3600,
                    )
                )
            assert exc_info.value.conflicting_item is not None
            assert exc_info.value.conflicting_item.asset_id == "meeting-1"
            assert exc_info.value.conflicting_item.state == SCHEDULE_STATE_PUBLISHED
        finally:
            eng.dispose()

    def test_downgrade_restores_scheduled_only_predicate(self, postgres_url) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            _seed_test_assets(eng)
            command.downgrade(cfg, "0070_grandfather_scheduled_to_published")

            @contextmanager
            def _factory() -> Iterator[Session]:
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresScheduleStore(_factory)
            base_when = datetime.now(UTC) + timedelta(hours=1)

            published = store.create(
                ScheduleItemCreate(
                    asset_id="meeting-1",
                    channel_id="ch-0071-downgrade",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base_when,
                    duration_seconds=3 * 3600,
                )
            )
            store.mark_published([published.id])

            # At the 0070 predicate (scheduled-only), an overlapping insert
            # against a published item must SUCCEED.
            store.create(
                ScheduleItemCreate(
                    asset_id="meeting-2",
                    channel_id="ch-0071-downgrade",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=base_when + timedelta(hours=1),
                    duration_seconds=3600,
                )
            )
            assert len(store.list(channel_id="ch-0071-downgrade")) == 2
        finally:
            # These two rows overlap and are only legal under the 0070
            # (scheduled-only) predicate. The module-scoped Postgres DB is
            # shared, so they must be deleted BEFORE re-upgrading: otherwise
            # re-applying the widened 0071 EXCLUDE constraint over them
            # raises ExclusionViolation, which fails this test's own restore
            # and every later test in the module that runs `upgrade head`.
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM civiccast.schedule_items "
                        "WHERE channel_id = 'ch-0071-downgrade'"
                    )
                )
            eng.dispose()
            # Restore head so subsequent tests in this module see the
            # widened (0071) constraint.
            command.upgrade(_make_cfg(postgres_url), "head")


class TestRealPostgresAssetStateMigrationReversible:
    """Locks: migration 0006_widen_asset_state_check adds 'recorded' to
    assets_state_check on Postgres, and the downgrade refuses to narrow
    the constraint while any assets.state = 'recorded' rows exist.

    Sprint 0.4 Slice 1 Commit 2. The 'recorded' state is the terminal
    state the v0.4 live-broadcast finalization path writes when a
    recording becomes a queued asset; this migration is the design gate
    that must land before any code can emit that state.
    """

    def test_upgrade_accepts_recorded_state(self, postgres_url) -> None:
        from sqlalchemy.orm import Session

        from civiccast.schedule.models import Asset

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            with Session(bind=eng) as sess:
                sess.add(
                    Asset(
                        asset_id="recorded-after-0006",
                        title="Recorded after migration 0006",
                        state="recorded",
                    )
                )
                sess.commit()

            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT asset_id, state FROM civiccast.assets "
                        "WHERE asset_id = 'recorded-after-0006'"
                    )
                ).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == "recorded"
        finally:
            eng.dispose()

    def test_downgrade_refuses_while_recorded_rows_exist(self, postgres_url) -> None:
        from sqlalchemy.orm import Session

        from civiccast.schedule.models import Asset

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")
        eng = create_engine(postgres_url, future=True)
        try:
            with Session(bind=eng) as sess:
                sess.add(
                    Asset(
                        asset_id="downgrade-blocker",
                        title="Blocks downgrade",
                        state="recorded",
                    )
                )
                sess.commit()

            # Downgrade must fail loudly while the recorded row exists.
            with pytest.raises(Exception) as excinfo:
                command.downgrade(cfg, "0005_schema_hardening_audit_v030")
            assert "recorded" in str(excinfo.value).lower() or (
                excinfo.value.__cause__ is not None
                and "recorded" in str(excinfo.value.__cause__).lower()
            )

            # Constraint must still accept 'recorded' (widened CHECK still
            # in place because the downgrade refused).
            with eng.connect() as conn:
                rows = conn.execute(
                    text("SELECT asset_id FROM civiccast.assets WHERE state = 'recorded'")
                ).fetchall()
            assert len(rows) >= 1
        finally:
            eng.dispose()

    def test_downgrade_allowed_when_no_recorded_rows(self, postgres_url) -> None:
        from sqlalchemy.exc import IntegrityError

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")

        # Confirm we are at 0006 head, with no 'recorded' rows from prior
        # tests leaking in (other tests in this class create such rows,
        # but pytest-collected test order + session-scoped postgres
        # container means we explicitly clean before downgrade).
        eng = create_engine(postgres_url, future=True)
        try:
            with eng.connect() as conn:
                conn.execute(text("DELETE FROM civiccast.assets WHERE state = 'recorded'"))
                conn.commit()

            command.downgrade(cfg, "0005_schema_hardening_audit_v030")

            # Inserting a 'recorded' state asset now must fail the
            # narrowed CHECK constraint. The INSERT uses raw SQL with
            # the column set that exists at the 0005 head so the SA
            # model's HEAD-state column set does not drift into this
            # assertion. The Asset SA model gained the Slice 1 Commit 7
            # ``source_live_session_id`` column which only exists at
            # 0008+; a model-based INSERT after a downgrade past 0008
            # would surface a column-does-not-exist ProgrammingError,
            # not the CHECK violation this test exists to prove.
            with eng.connect() as conn, pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO civiccast.assets "
                        "(asset_id, title, state) VALUES "
                        "('recorded-after-downgrade', "
                        "'Should be rejected by narrowed CHECK', "
                        "'recorded')"
                    )
                )
                conn.commit()
        finally:
            eng.dispose()
            # Restore head so subsequent tests in this session see the
            # widened constraint.
            cfg2 = _make_cfg(postgres_url)
            command.upgrade(cfg2, "head")


# ===========================================================================
# QA-005 (audit-team v0.3.0) -- conflict-409 race; relaxed-state retry proof
# ===========================================================================


class TestRealPostgresQA005ConflictRace:
    """Locks: when the conflicting schedule row transitions out of
    ``scheduled`` between the EXCLUDE rejection and the
    ``_find_conflicting`` lookup, the relaxed-state retry path recovers
    the row so the ScheduleConflictError detail body still names it.

    Without QA-005's relaxed retry, the strict ``state='scheduled'``
    filter would miss the now-cancelled row and the 409 response would
    lose the conflicting-item enrichment. The audit's complaint:
    operators see a bare 409 with no actionable detail.

    The full cross-transaction race (cancel + lookup interleaved across
    two engines) is exercised via the helper's strict-vs-relaxed
    behavior in isolation here; the deeper threading-barrier proof is
    deferred to a TEST-008 promotion once the recovery semantics are
    pinned in single-transaction form.
    """

    def test_relaxed_retry_recovers_cancelled_conflicting_row(self, postgres_url) -> None:
        from contextlib import contextmanager
        from datetime import UTC, datetime
        from uuid import uuid4

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            _SCHEDULE_STATES,
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_CANCELLED,
            SCHEDULE_STATE_SCHEDULED,
            Asset,
            ScheduleItem,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")

        eng = create_engine(postgres_url, future=True)
        try:

            @contextmanager
            def _factory():
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            asset_id = f"qa005-{uuid4().hex[:8]}"
            channel_id = f"qa005-ch-{uuid4().hex[:8]}"
            target_at = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)

            with _factory() as seed_sess:
                seed_sess.add(Asset(asset_id=asset_id, title="QA-005 target", state="validated"))
                seed_sess.commit()

            store = PostgresScheduleStore(_factory)
            existing = store.create(
                ScheduleItemCreate(
                    asset_id=asset_id,
                    channel_id=channel_id,
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=target_at,
                    duration_seconds=3600,
                )
            )
            assert existing.state == SCHEDULE_STATE_SCHEDULED

            # Cancel the existing row, mirroring the mid-lookup race.
            with _factory() as cancel_sess:
                row = cancel_sess.get(ScheduleItem, existing.id)
                assert row is not None
                row.state = SCHEDULE_STATE_CANCELLED
                cancel_sess.commit()

            # Strict lookup misses (cancelled state filtered out).
            strict = store._find_conflicting(
                channel_id=channel_id,
                scheduled_at=target_at,
                duration_seconds=3600,
            )
            assert strict is None, (
                "Strict-state lookup must miss the cancelled row; if it "
                "returned a row, the relaxed retry path would be unreachable."
            )

            # Relaxed lookup recovers the cancelled row with state visible.
            relaxed = store._find_conflicting(
                channel_id=channel_id,
                scheduled_at=target_at,
                duration_seconds=3600,
                states=_SCHEDULE_STATES,
            )
            assert relaxed is not None, (
                "QA-005 relaxed retry must recover the cancelled row so "
                "the 409 detail body keeps the conflicting-item enrichment."
            )
            assert relaxed.state == SCHEDULE_STATE_CANCELLED, (
                "Relaxed lookup surfaces the row's current state so the "
                "caller can compose a state-aware 409 message."
            )
            assert relaxed.id == existing.id

            with _factory() as cleanup_sess:
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.schedule_items WHERE channel_id = :ch"),
                    {"ch": channel_id},
                )
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.assets WHERE asset_id = :a"),
                    {"a": asset_id},
                )
                cleanup_sess.commit()
        finally:
            eng.dispose()


# ===========================================================================
# QA-007 (audit-team v0.3.0) -- published-schedule-item guard proof
# ===========================================================================


class TestRealPostgresScheduleRouterConflict:
    """TEST-008 (audit-team v0.3.0) -- promote the mocked-store 409
    conflict-response test to real-Postgres.

    The router's 409 shape is locked at SQLite level via mocks in
    ``tests/schedule/test_schedule_router.py::TestConflictResponse``.
    That test cannot run against a real conflict because SQLite has no
    btree_gist EXCLUDE constraint -- the mock fakes the
    ``ScheduleConflictError``. The audit's complaint: a regression in
    how the store translates the IntegrityError into
    ScheduleConflictError, or how the router maps the exception to
    HTTP 409, would not be caught.

    This class promotes the path end-to-end:
    1. Stand up a TestClient with the FastAPI app wired to a real
       PostgresScheduleStore against the testcontainer.
    2. POST a premiere; assert 201.
    3. POST an overlapping premiere on the same channel; assert 409 +
       structured detail body carries the conflicting_item.
    """

    def test_overlapping_premiere_returns_409_with_conflicting_item(self, postgres_url) -> None:
        from contextlib import contextmanager
        from datetime import UTC, datetime
        from uuid import uuid4

        from fastapi.testclient import TestClient
        from sqlalchemy.orm import Session

        from civiccast.app import create_app
        from civiccast.schedule.models import Asset
        from civiccast.schedule.router import get_schedule_store
        from civiccast.schedule.store import PostgresScheduleStore

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")

        eng = create_engine(postgres_url, future=True)

        asset_id = f"router-conflict-{uuid4().hex[:8]}"
        channel_id = f"router-conflict-ch-{uuid4().hex[:8]}"
        scheduled_at = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)

        with Session(bind=eng) as seed_sess:
            seed_sess.add(
                Asset(asset_id=asset_id, title="router-conflict target", state="validated")
            )
            seed_sess.commit()

        @contextmanager
        def _factory():
            sess = Session(bind=eng)
            try:
                yield sess
            finally:
                sess.close()

        app = create_app()
        store = PostgresScheduleStore(_factory)
        app.dependency_overrides[get_schedule_store] = lambda: store

        try:
            with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
                payload_first = {
                    "asset_id": asset_id,
                    "channel_id": channel_id,
                    "mode": "premiere",
                    "scheduled_at": scheduled_at.isoformat(),
                    "duration_seconds": 3600,
                }
                first = client.post("/api/staff/schedule", json=payload_first)
                assert first.status_code == 201, first.text

                # Overlapping second insert: starts inside the first
                # range's window; same channel + premiere mode + 30min
                # duration -> EXCLUDE fires.
                payload_second = dict(payload_first)
                payload_second["scheduled_at"] = datetime(
                    2026, 5, 15, 18, 30, 0, tzinfo=UTC
                ).isoformat()
                payload_second["duration_seconds"] = 1800

                second = client.post("/api/staff/schedule", json=payload_second)
                assert second.status_code == 409, second.text
                detail = second.json()["detail"]
                # The 409 detail body must carry the conflicting_item
                # enrichment (the entire point of QA-005's relaxed-state
                # retry; this test pins that the router surfaces it).
                assert "Schedule conflict" in detail["message"]
                assert detail["conflicting_item"] is not None
                assert detail["conflicting_item"]["channel_id"] == channel_id
                assert detail["conflicting_item"]["mode"] == "premiere"
                assert detail["conflicting_item"]["state"] == "scheduled"
        finally:
            with _factory() as cleanup_sess:
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.schedule_items WHERE channel_id = :ch"),
                    {"ch": channel_id},
                )
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.assets WHERE asset_id = :a"),
                    {"a": asset_id},
                )
                cleanup_sess.commit()
            eng.dispose()


class TestRealPostgresHypothesisPropertyPromotion:
    """TEST-004 (audit-team v0.3.0) -- promote pure-Python hypothesis
    properties to a real-Postgres harness so the EXCLUDE constraint
    behavior is asserted against the actual btree_gist machinery.

    The pure-Python property tests at
    ``tests/schedule/test_schedule_conflict_properties.py`` exercise the
    overlap-detection LOGIC that mirrors what the EXCLUDE constraint's
    SQL encodes. They prove the Python prediction is internally
    consistent. They do NOT prove the Python prediction matches what
    Postgres actually does.

    This class promotes one property (P3: overlapping times on the
    same channel DO conflict) to a real-Postgres harness. Each
    hypothesis example INSERTs the second row via PostgresScheduleStore
    and asserts the EXCLUDE constraint's behavior matches the Python
    prediction. Bounded to a small max_examples count to keep CI fast:
    the goal is "the Python prediction agrees with Postgres" coverage,
    not exhaustive search (the pure-Python pass already does that).
    """

    def test_overlapping_premiere_on_same_channel_raises_integrity_error(
        self, postgres_url
    ) -> None:
        from contextlib import contextmanager
        from datetime import UTC, datetime, timedelta
        from uuid import uuid4

        from hypothesis import HealthCheck, given, settings
        from hypothesis import strategies as st
        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            Asset,
            ScheduleItemCreate,
        )
        from civiccast.schedule.store import (
            PostgresScheduleStore,
            ScheduleConflictError,
        )

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")

        eng = create_engine(postgres_url, future=True)

        # Seed one asset for every example to point at; we delete the
        # schedule_items rows between examples but reuse the asset.
        asset_id = f"prop-asset-{uuid4().hex[:8]}"
        with Session(bind=eng) as seed_sess:
            seed_sess.add(Asset(asset_id=asset_id, title="property-test target", state="validated"))
            seed_sess.commit()

        @contextmanager
        def _factory():
            sess = Session(bind=eng)
            try:
                yield sess
            finally:
                sess.close()

        store = PostgresScheduleStore(_factory)
        channel_id = f"prop-ch-{uuid4().hex[:8]}"

        # Strategy: two start times within a fixed day, two durations
        # in [60s, 4h]. The pair is constrained so the time ranges
        # ALWAYS overlap (the second range starts inside the first
        # range's window). This locks the EXCLUDE-fires invariant
        # without spending examples on non-overlapping pairs.
        @given(
            base_offset_seconds=st.integers(min_value=0, max_value=12 * 3600),
            first_duration_seconds=st.integers(min_value=300, max_value=4 * 3600),
            second_offset_within_first=st.integers(min_value=1, max_value=60),
            second_duration_seconds=st.integers(min_value=60, max_value=4 * 3600),
        )
        @settings(
            max_examples=8,
            deadline=None,
            suppress_health_check=[HealthCheck.function_scoped_fixture],
        )
        def _check_property(
            base_offset_seconds: int,
            first_duration_seconds: int,
            second_offset_within_first: int,
            second_duration_seconds: int,
        ) -> None:
            base = datetime(2026, 5, 15, 0, 0, 0, tzinfo=UTC)
            first_start = base + timedelta(seconds=base_offset_seconds)
            second_start = first_start + timedelta(seconds=second_offset_within_first)
            # Second start is inside first's window; ranges overlap.
            assert second_start < first_start + timedelta(seconds=first_duration_seconds)

            # Clean any leftover rows on this channel from a prior example.
            with _factory() as cleanup_sess:
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.schedule_items WHERE channel_id = :ch"),
                    {"ch": channel_id},
                )
                cleanup_sess.commit()

            # First insert succeeds (channel is empty).
            store.create(
                ScheduleItemCreate(
                    asset_id=asset_id,
                    channel_id=channel_id,
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=first_start,
                    duration_seconds=first_duration_seconds,
                )
            )

            # Second insert must raise ScheduleConflictError because
            # the EXCLUDE constraint rejects the overlap. The pure-
            # Python _conflicts() function would predict True here;
            # we assert Postgres agrees.
            try:
                store.create(
                    ScheduleItemCreate(
                        asset_id=asset_id,
                        channel_id=channel_id,
                        mode=SCHEDULE_MODE_PREMIERE,
                        scheduled_at=second_start,
                        duration_seconds=second_duration_seconds,
                    )
                )
            except ScheduleConflictError:
                pass  # expected
            else:
                pytest.fail(
                    "Overlapping premiere on same channel did NOT raise "
                    "ScheduleConflictError. The Python prediction is True "
                    "but Postgres allowed the insert. EXCLUDE constraint "
                    "may be missing or misconfigured."
                )

        try:
            _check_property()
        finally:
            # Final cleanup so subsequent tests don't see leftover rows.
            with _factory() as cleanup_sess:
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.schedule_items WHERE channel_id = :ch"),
                    {"ch": channel_id},
                )
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.assets WHERE asset_id = :a"),
                    {"a": asset_id},
                )
                cleanup_sess.commit()
            eng.dispose()


class TestRealPostgresQA007PublishedGuard:
    """Locks: ``PostgresAssetStore.update_metadata`` refuses the edit
    when a linked ``schedule_items`` row is in state ``published``,
    against real Postgres.

    SQLite covers the happy + reject paths in
    ``tests/schedule/test_metadata_edit.py``. This test pins the
    behavior at the real-Postgres path so a regression that's
    SQLite-only (subtle SA dialect difference) gets caught.
    """

    def test_update_metadata_refused_when_linked_published(self, postgres_url) -> None:
        from contextlib import contextmanager
        from datetime import UTC, datetime
        from uuid import uuid4

        from sqlalchemy.orm import Session

        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_PUBLISHED,
            Asset,
            AssetMetadataUpdate,
            ScheduleItem,
        )
        from civiccast.schedule.store import (
            AssetAlreadyPublishedError,
            PostgresAssetStore,
        )

        cfg = _make_cfg(postgres_url)
        command.upgrade(cfg, "head")

        eng = create_engine(postgres_url, future=True)
        try:

            @contextmanager
            def _factory():
                sess = Session(bind=eng)
                try:
                    yield sess
                finally:
                    sess.close()

            asset_id = f"qa007-{uuid4().hex[:8]}"
            channel_id = f"qa007-ch-{uuid4().hex[:8]}"

            with _factory() as seed_sess:
                seed_sess.add(
                    Asset(
                        asset_id=asset_id,
                        title="QA-007 target",
                        state="validated",
                    )
                )
                seed_sess.add(
                    ScheduleItem(
                        asset_id=asset_id,
                        channel_id=channel_id,
                        mode=SCHEDULE_MODE_PREMIERE,
                        state=SCHEDULE_STATE_PUBLISHED,
                        scheduled_at=datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC),
                        duration_seconds=3600,
                        scheduled_at_end=datetime(2026, 5, 15, 19, 0, 0, tzinfo=UTC),
                    )
                )
                seed_sess.commit()

            store = PostgresAssetStore(_factory)
            with pytest.raises(AssetAlreadyPublishedError) as exc_info:
                store.update_metadata(
                    asset_id,
                    AssetMetadataUpdate(expected_version=1, title="Blocked edit"),
                )
            assert exc_info.value.asset_id == asset_id
            assert len(exc_info.value.published_schedule_item_ids) == 1

            with _factory() as cleanup_sess:
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.schedule_items WHERE asset_id = :a"),
                    {"a": asset_id},
                )
                cleanup_sess.execute(
                    text("DELETE FROM civiccast.assets WHERE asset_id = :a"),
                    {"a": asset_id},
                )
                cleanup_sess.commit()
        finally:
            eng.dispose()
