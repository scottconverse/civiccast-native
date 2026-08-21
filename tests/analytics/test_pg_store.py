# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S14 durable analytics store + rollup worker tests.

Covers the spec's §9.1 unit-test list against the real Postgres-shaped ORM
models (via SQLite, matching the repo's established store-test pattern —
see ``tests/captions/test_offline_caption_job_persistence.py``): privacy
shape, stream-type derivation, rollup bucket math (VOD 24h, Live 30-min,
Live hourly, midnight-UTC crossover), the two headline metrics, peak
concurrent, year-over-year with prior==0, and idempotent JSON backfill.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.analytics.models import ViewershipEventDb, ViewershipRollupDb
from civiccast.analytics.pg_store import (
    AnalyticsRollupSettings,
    AnalyticsRollupWorker,
    PostgresAnalyticsStore,
    backfill_json_events,
)
from civiccast.app_platform.models import AnalyticsEvent
from civiccast.db import Base


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _factory_for(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _event(
    *,
    event_id: str,
    event_name: str,
    occurred_at: datetime,
    channel_id: str | None = None,
    content_id: str | None = None,
    properties: dict | None = None,
) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_id=event_id,
        event_name=event_name,  # type: ignore[arg-type]
        occurred_at=occurred_at,
        app_target="web_pwa",
        channel_id=channel_id,
        content_id=content_id,
        properties=properties or {},
    )


class TestRecordEventPrivacyShape:
    def test_no_session_or_viewer_identity_persisted(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        store.record_event(
            AnalyticsEvent(
                event_id="evt-1",
                event_name="playback_start",
                occurred_at=now,
                app_target="web_pwa",
                content_id="asset-1",
                anonymous_session_id="should-not-persist",
                hashed_viewer_id="should-not-persist-either",
                properties={"device": "roku", "unsafe_custom_key": "dropped"},
            )
        )
        with _factory_for(engine)() as session:
            row = session.get(ViewershipEventDb, "evt-1")
        assert row is not None
        assert "should-not-persist" not in json.dumps(
            {c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str
        )
        # Only allowlisted safe property keys survive into properties_json.
        assert "unsafe_custom_key" not in row.properties_json
        assert json.loads(row.properties_json) == {"device": "roku"}


class TestStreamTypeDerivation:
    def test_content_id_is_vod(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        store.record_event(_event(event_id="e1", event_name="playback_start", occurred_at=_now(), content_id="asset-1"))
        with _factory_for(engine)() as session:
            row = session.get(ViewershipEventDb, "e1")
        assert row.stream_type == "vod"

    def test_channel_only_is_live(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        store.record_event(_event(event_id="e2", event_name="playback_start", occurred_at=_now(), channel_id="public"))
        with _factory_for(engine)() as session:
            row = session.get(ViewershipEventDb, "e2")
        assert row.stream_type == "live"


def _now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _naive(moment: datetime) -> datetime:
    """SQLite round-trips a naive datetime; compare on that footing."""
    return moment.replace(tzinfo=None)


class TestViewerCountAndTimeViewed:
    def test_viewer_count_is_playback_start_count(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        day = datetime.now(UTC) - timedelta(days=1)
        store.record_event(_event(event_id="s1", event_name="playback_start", occurred_at=day, content_id="a1"))
        store.record_event(_event(event_id="s2", event_name="playback_start", occurred_at=day, content_id="a1"))
        store.record_event(
            _event(
                event_id="h1",
                event_name="playback_heartbeat",
                occurred_at=day,
                content_id="a1",
                properties={"view_seconds": 60},
            )
        )
        report = store.report(range_days=30)
        views_by_content = {p.content_id: p.views for p in report.asset_views}
        assert views_by_content["a1"] == 2  # heartbeat doesn't count as a "view"

    def test_time_viewed_sums_heartbeats_and_complete_tail(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        day = datetime.now(UTC) - timedelta(days=1)
        store.record_event(_event(event_id="s1", event_name="playback_start", occurred_at=day, content_id="a1"))
        store.record_event(
            _event(
                event_id="h1",
                event_name="playback_heartbeat",
                occurred_at=day + timedelta(seconds=60),
                content_id="a1",
                properties={"view_seconds": 60},
            )
        )
        store.record_event(
            _event(
                event_id="c1",
                event_name="playback_complete",
                occurred_at=day + timedelta(seconds=125),
                content_id="a1",
                properties={"position_seconds": 125},
            )
        )
        report = store.report(range_days=30)
        seconds_by_content = {p.content_id: p.view_seconds for p in report.asset_views}
        assert seconds_by_content["a1"] == 60 + 125


class TestRollupBucketMath:
    def test_vod_24h_bucket(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        day = datetime(2026, 6, 10, 3, 0, tzinfo=UTC)
        store.record_event(_event(event_id="s1", event_name="playback_start", occurred_at=day, content_id="a1"))
        store.record_event(
            _event(event_id="s2", event_name="playback_start", occurred_at=day + timedelta(hours=20), content_id="a1")
        )
        worker.run_once(now=day + timedelta(days=1))
        with _factory_for(engine)() as session:
            rows = session.query(ViewershipRollupDb).filter_by(stream_type="vod", bucket_kind="day").all()
        assert len(rows) == 1  # both events fall in the same UTC day bucket
        assert rows[0].viewer_count == 2
        assert _naive(rows[0].bucket_start) == datetime(2026, 6, 10, tzinfo=UTC).replace(tzinfo=None)

    def test_midnight_utc_crossover_splits_into_two_day_buckets(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        before_midnight = datetime(2026, 6, 10, 23, 59, tzinfo=UTC)
        after_midnight = datetime(2026, 6, 11, 0, 1, tzinfo=UTC)
        store.record_event(
            _event(event_id="s1", event_name="playback_start", occurred_at=before_midnight, content_id="a1")
        )
        store.record_event(
            _event(event_id="s2", event_name="playback_start", occurred_at=after_midnight, content_id="a1")
        )
        worker.run_once(now=after_midnight + timedelta(hours=1))
        with _factory_for(engine)() as session:
            rows = (
                session.query(ViewershipRollupDb)
                .filter_by(stream_type="vod", bucket_kind="day")
                .order_by(ViewershipRollupDb.bucket_start)
                .all()
            )
        assert len(rows) == 2
        assert _naive(rows[0].bucket_start) == datetime(2026, 6, 10, tzinfo=UTC).replace(tzinfo=None)
        assert _naive(rows[1].bucket_start) == datetime(2026, 6, 11, tzinfo=UTC).replace(tzinfo=None)
        assert rows[0].viewer_count == 1
        assert rows[1].viewer_count == 1

    def test_live_halfhour_bucket_boundary(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        first_half = datetime(2026, 6, 10, 14, 29, tzinfo=UTC)
        second_half = datetime(2026, 6, 10, 14, 31, tzinfo=UTC)
        store.record_event(
            _event(event_id="s1", event_name="playback_start", occurred_at=first_half, channel_id="public")
        )
        store.record_event(
            _event(event_id="s2", event_name="playback_start", occurred_at=second_half, channel_id="public")
        )
        worker.run_once(now=second_half + timedelta(hours=1))
        with _factory_for(engine)() as session:
            rows = (
                session.query(ViewershipRollupDb)
                .filter_by(stream_type="live", bucket_kind="halfhour")
                .order_by(ViewershipRollupDb.bucket_start)
                .all()
            )
        assert len(rows) == 2
        assert _naive(rows[0].bucket_start) == datetime(2026, 6, 10, 14, 0, tzinfo=UTC).replace(tzinfo=None)
        assert _naive(rows[1].bucket_start) == datetime(2026, 6, 10, 14, 30, tzinfo=UTC).replace(tzinfo=None)

    def test_live_hourly_single_day_bucket(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        moment = datetime(2026, 6, 10, 14, 45, tzinfo=UTC)
        store.record_event(
            _event(event_id="s1", event_name="playback_start", occurred_at=moment, channel_id="public")
        )
        worker.run_once(now=moment + timedelta(hours=1))
        with _factory_for(engine)() as session:
            rows = session.query(ViewershipRollupDb).filter_by(stream_type="live", bucket_kind="hour").all()
        assert len(rows) == 1
        assert _naive(rows[0].bucket_start) == datetime(2026, 6, 10, 14, 0, tzinfo=UTC).replace(tzinfo=None)

    def test_peak_concurrent_per_bucket(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        moment = datetime(2026, 6, 10, 14, 5, tzinfo=UTC)
        for i, viewers in enumerate([10, 25, 15]):
            store.record_event(
                _event(
                    event_id=f"hb{i}",
                    event_name="playback_heartbeat",
                    occurred_at=moment + timedelta(minutes=i),
                    channel_id="public",
                    properties={"concurrent_viewers": viewers},
                )
            )
        worker.run_once(now=moment + timedelta(hours=1))
        with _factory_for(engine)() as session:
            row = (
                session.query(ViewershipRollupDb)
                .filter_by(stream_type="live", bucket_kind="halfhour")
                .one()
            )
        assert row.peak_concurrent == 25
        assert row.avg_concurrent == pytest.approx(round((10 + 25 + 15) / 3, 2), rel=1e-6)
        assert row.samples == 3

    def test_rollup_is_idempotent_upsert(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        moment = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
        store.record_event(_event(event_id="s1", event_name="playback_start", occurred_at=moment, content_id="a1"))
        worker.run_once(now=moment + timedelta(hours=1))
        worker.run_once(now=moment + timedelta(hours=2))  # re-run over same window
        with _factory_for(engine)() as session:
            rows = session.query(ViewershipRollupDb).filter_by(stream_type="vod", bucket_kind="day").all()
        assert len(rows) == 1  # no duplicate rows
        assert rows[0].viewer_count == 1  # not double-counted


class TestYearOverYear:
    def test_prior_zero_returns_none_delta(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        now = datetime.now(UTC) - timedelta(days=1)
        store.record_event(_event(event_id="s1", event_name="playback_start", occurred_at=now, content_id="a1"))
        worker.run_once(now=now + timedelta(hours=1))
        report = store.report(range_days=30)
        yoy = {p.metric: p for p in report.year_over_year}
        assert yoy["viewer_count"].current_period == 1
        assert yoy["viewer_count"].prior_period == 0
        assert yoy["viewer_count"].delta_pct is None

    def test_delta_pct_computed_when_prior_nonzero(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        worker = AnalyticsRollupWorker(_factory_for(engine), settings=AnalyticsRollupSettings())
        now = datetime.now(UTC) - timedelta(days=1)
        prior_year = now - timedelta(days=365)
        for i in range(4):
            store.record_event(
                _event(event_id=f"cur{i}", event_name="playback_start", occurred_at=now, content_id="a1")
            )
        for i in range(2):
            store.record_event(
                _event(event_id=f"pri{i}", event_name="playback_start", occurred_at=prior_year, content_id="a1")
            )
        worker.run_once(now=now + timedelta(hours=1))
        # First run_once only backfills relative to "now"; the prior-year
        # event needs its own bucket recomputed too since it's outside the
        # default lookback window on a non-empty rollup table.
        worker.run_once(now=prior_year + timedelta(hours=1))
        report = store.report(range_days=30)
        yoy = {p.metric: p for p in report.year_over_year}
        assert yoy["viewer_count"].current_period == 4
        assert yoy["viewer_count"].prior_period == 2
        assert yoy["viewer_count"].delta_pct == 100.0


class TestSnapshot:
    def test_save_and_read_back(self, engine: Engine) -> None:
        store = PostgresAnalyticsStore(_factory_for(engine))
        store.save_snapshot(
            snapshot_id="snap-1",
            generated_at=_now(),
            range_start=_now() - timedelta(days=7),
            range_end=_now(),
            report_json='{"ok": true}',
            created_by="op-1",
        )
        from civiccast.analytics.models import AnalyticsReportSnapshotDb

        with _factory_for(engine)() as session:
            row = session.get(AnalyticsReportSnapshotDb, "snap-1")
        assert row is not None
        assert row.created_by == "op-1"
        assert row.report_json == '{"ok": true}'


class TestJsonBackfill:
    def test_backfill_is_idempotent(self, engine: Engine, tmp_path) -> None:
        json_path = tmp_path / "analytics-events.json"
        json_path.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "event_id": "legacy-1",
                            "event_name": "playback_start",
                            "occurred_at": _now().isoformat(),
                            "app_target": "web_pwa",
                            "channel_id": None,
                            "content_id": "asset-legacy",
                            "properties": {},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        factory = _factory_for(engine)
        migrated_first = backfill_json_events(factory, json_path)
        migrated_second = backfill_json_events(factory, json_path)
        assert migrated_first == 1
        assert migrated_second == 0  # events table is non-empty -> no-op
        with factory() as session:
            row = session.get(ViewershipEventDb, "legacy-1")
        assert row is not None
        assert row.stream_type == "vod"

    def test_backfill_missing_file_is_a_noop(self, engine: Engine, tmp_path) -> None:
        assert backfill_json_events(_factory_for(engine), tmp_path / "does-not-exist.json") == 0
