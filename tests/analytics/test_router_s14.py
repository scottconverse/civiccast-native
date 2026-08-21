# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S14 API tests: role gating + shape for the net-new analytics endpoints.

Covers the spec's §9.2 API-test list for the S14-added surface:
``/reports/overview`` (extended with stream_type/metric), ``/rollups``,
``/export.csv``, ``/reports/board-pdf``. Every route requires
``support_admin`` OR ``publish_operator``; every other role gets 403; no
identity gets 401.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.analytics.pg_store import (
    AnalyticsRollupSettings,
    AnalyticsRollupWorker,
    PostgresAnalyticsStore,
)
from civiccast.analytics.router import get_analytics_store, staff_router
from civiccast.app_platform.models import AnalyticsEvent
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base


def _build(*, scopes: tuple[str, ...] | None = ("support_admin",)) -> tuple[FastAPI, PostgresAnalyticsStore]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    store = PostgresAnalyticsStore(factory)
    app = FastAPI()

    @app.middleware("http")
    async def _ident(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.dependency_overrides[get_analytics_store] = lambda: store
    app.state._test_worker_factory = factory
    return app, store


def _seed(store: PostgresAnalyticsStore, engine_factory) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC) - timedelta(hours=2)
    store.record_event(
        AnalyticsEvent(
            event_id="e1",
            event_name="playback_start",
            occurred_at=now,
            app_target="web_pwa",
            content_id="asset-1",
        )
    )
    worker = AnalyticsRollupWorker(engine_factory, settings=AnalyticsRollupSettings())
    worker.run_once(now=now + timedelta(minutes=5))


class TestRoleGating:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/staff/analytics/reports/overview",
            "/api/staff/analytics/rollups?stream_type=vod",
            "/api/staff/analytics/export.csv?stream_type=vod",
        ],
    )
    def test_no_identity_is_401(self, path: str) -> None:
        app, _ = _build(scopes=None)
        resp = TestClient(app).get(path)
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/staff/analytics/reports/overview",
            "/api/staff/analytics/rollups?stream_type=vod",
            "/api/staff/analytics/export.csv?stream_type=vod",
        ],
    )
    def test_wrong_role_is_403(self, path: str) -> None:
        app, _ = _build(scopes=("meeting_operator",))
        resp = TestClient(app).get(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("scopes", [("support_admin",), ("publish_operator",)])
    def test_either_analytics_role_reads_overview(self, scopes: tuple[str, ...]) -> None:
        app, _ = _build(scopes=scopes)
        resp = TestClient(app).get("/api/staff/analytics/reports/overview")
        assert resp.status_code == 200

    def test_openapi_carries_x_required_roles(self) -> None:
        app, _ = _build()
        schema = app.openapi()
        overview = schema["paths"]["/api/staff/analytics/reports/overview"]["get"]
        assert overview.get("x-required-roles") == ["support_admin", "publish_operator"]


class TestRollupsEndpoint:
    def test_vod_only_supports_bucket_day(self) -> None:
        app, store = _build()
        _seed(store, app.state._test_worker_factory)
        resp = TestClient(app).get("/api/staff/analytics/rollups?stream_type=vod&bucket=halfhour")
        assert resp.status_code == 422

    def test_returns_seeded_rollup(self) -> None:
        app, store = _build()
        _seed(store, app.state._test_worker_factory)
        resp = TestClient(app).get("/api/staff/analytics/rollups?stream_type=vod")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stats"]["total_viewer_count"] == 1
        assert len(body["rollups"]) == 1
        assert body["rollups"][0]["subject_id"] == "asset-1"

    def test_empty_state_is_honest_not_500(self) -> None:
        app, _store = _build()
        resp = TestClient(app).get("/api/staff/analytics/rollups?stream_type=live")
        assert resp.status_code == 200
        body = resp.json()
        assert body["rollups"] == []
        assert body["stats"]["total_viewer_count"] == 0
        assert body["stats"]["peak_concurrent"] is None


class TestIngestConfiguredFlag:
    """S14 §5/§9.2: the dashboard's honest 'telemetry off' empty state."""

    def test_not_configured_when_no_key_or_origins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", raising=False)
        monkeypatch.delenv("CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS", raising=False)
        app, _store = _build()
        resp = TestClient(app).get("/api/staff/analytics/reports/overview")
        assert resp.status_code == 200
        assert resp.json()["ingest_configured"] is False

    def test_configured_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-key")
        app, _store = _build()
        resp = TestClient(app).get("/api/staff/analytics/reports/overview")
        assert resp.json()["ingest_configured"] is True

    def test_configured_when_allowed_origins_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", raising=False)
        monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS", "https://portal.example.org")
        app, _store = _build()
        resp = TestClient(app).get("/api/staff/analytics/reports/overview")
        assert resp.json()["ingest_configured"] is True


class TestOverviewStreamTypeFilter:
    def test_stream_type_vod_drops_live_rollups(self) -> None:
        app, store = _build()
        _seed(store, app.state._test_worker_factory)
        resp = TestClient(app).get("/api/staff/analytics/reports/overview?stream_type=vod")
        body = resp.json()
        assert body["live_rollups"] == []


class TestCsvExport:
    def test_download_headers_and_shape(self) -> None:
        app, store = _build()
        _seed(store, app.state._test_worker_factory)
        resp = TestClient(app).get("/api/staff/analytics/export.csv?stream_type=vod")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        text = resp.text
        assert text.startswith("﻿stream_type,bucket_kind,bucket_start,subject_id")
        assert "asset-1" in text


class TestBoardPdf:
    def test_generates_pdf_and_persists_snapshot(self) -> None:
        app, store = _build()
        _seed(store, app.state._test_worker_factory)
        now = datetime.now(UTC)
        resp = TestClient(app).post(
            "/api/staff/analytics/reports/board-pdf",
            json={
                "range_start": (now - timedelta(days=7)).isoformat(),
                "range_end": now.isoformat(),
                "station_label": "Test PEG Station",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")

        from civiccast.analytics.models import AnalyticsReportSnapshotDb

        with app.state._test_worker_factory() as session:
            snapshots = session.query(AnalyticsReportSnapshotDb).all()
        assert len(snapshots) == 1
        assert snapshots[0].created_by == "dana"

    def test_invalid_range_is_422(self) -> None:
        app, _store = _build()
        now = datetime.now(UTC)
        resp = TestClient(app).post(
            "/api/staff/analytics/reports/board-pdf",
            json={"range_start": now.isoformat(), "range_end": (now - timedelta(days=1)).isoformat()},
        )
        assert resp.status_code == 422
