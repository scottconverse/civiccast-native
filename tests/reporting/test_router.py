# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 reporting + EPG-export API: role gating, 503 unwired, push fail-safe, public surface.

A minimal FastAPI app mounts the real reporting routers, installs an operator-identity
middleware (so ``require_any_role`` runs), and overrides the DI seams with a SQLite-backed
``ReportingService`` / ``ReportingStore`` + an ``EpgExporter`` with an in-memory committed
schedule. Covers:

* role gating on each staff route (``support_admin`` reads reports; ``setup_admin`` +
  ``publish_operator`` manage EPG configs; 401 without identity; 403 for wrong scopes);
* 503 when the relevant DI seam is unwired (an explicit "storage not ready" signal,
  not a silent 200);
* report happy paths (as-run, shows, hours-by-category, export download CSV+XML);
* EPG config CRUD (list / get / create / patch / delete) + 404s;
* ``POST /epg/configs/{id}/generate`` returns the document inline when ``endpoint=None``,
  and surfaces a push error as ``error=str(...)`` on the result (never a 500);
* public ``GET /api/public/reports/as-run`` is reachable without an identity.
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

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.reporting.epg import (
    CommittedSlot,
    EpgExporter,
    InMemoryCommittedScheduleReader,
)
from civiccast.reporting.models import AsRunLogEntry, EpgExportConfig
from civiccast.reporting.router import (
    get_epg_exporter,
    get_reporting_service,
    get_reporting_store,
    public_router,
    staff_router,
)
from civiccast.reporting.service import ReportingService
from civiccast.reporting.store import ReportingStore

_STATION = "civiccast-station"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _build(
    *,
    scopes: tuple[str, ...] | None = ("support_admin", "setup_admin", "publish_operator"),
    wire_service: bool = True,
    wire_store: bool = True,
    wire_exporter: bool = True,
    seeded_slots: list[CommittedSlot] | None = None,
    push_fn: Callable[[str, str, str], None] | None = None,
) -> tuple[FastAPI, ReportingStore, ReportingService, EpgExporter]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    store = ReportingStore(factory)
    service = ReportingService(factory)
    reader = InMemoryCommittedScheduleReader(slots=tuple(seeded_slots or []))
    exporter = EpgExporter(schedule_reader=reader, http_post=push_fn)

    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana",
                operator_display_name="Dana",
                scopes=scopes,
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.include_router(public_router)
    if wire_service:
        app.dependency_overrides[get_reporting_service] = lambda: service
    if wire_store:
        app.dependency_overrides[get_reporting_store] = lambda: store
    if wire_exporter:
        app.dependency_overrides[get_epg_exporter] = lambda: exporter
    return app, store, service, exporter


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


# --- 503 when unwired --------------------------------------------------------


def test_503_when_reporting_service_unwired() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).get(
        "/api/staff/reports/shows",
        params={"from": _now().isoformat(), "to": (_now() + timedelta(days=1)).isoformat()},
    )
    assert r.status_code == 503
    assert "not ready" in r.text


def test_503_when_reporting_store_unwired() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).get("/api/staff/epg/configs")
    assert r.status_code == 503


def test_503_when_epg_exporter_unwired() -> None:
    app, store, *_ = _build(wire_exporter=False)
    store.upsert_config(
        EpgExportConfig(
            config_id="cfg-test",
            station_id=_STATION,
            channel_id="ch1",
            format="csv",
        )
    )
    r = TestClient(app).post("/api/staff/epg/configs/cfg-test/generate")
    assert r.status_code == 503


# --- role gating: staff reports ---------------------------------------------


@pytest.mark.parametrize("path", ["/api/staff/reports/as-run", "/api/staff/reports/shows"])
def test_staff_reports_require_support_admin(path: str) -> None:
    params = {"from": _now().isoformat(), "to": (_now() + timedelta(days=1)).isoformat()}
    assert _client(scopes=None).get(path, params=params).status_code == 401
    assert _client(scopes=("publish_operator",)).get(path, params=params).status_code == 403
    assert _client(scopes=("support_admin",)).get(path, params=params).status_code == 200


def test_hours_by_category_requires_support_admin() -> None:
    params = {
        "from": _now().isoformat(),
        "to": (_now() + timedelta(days=1)).isoformat(),
        "field": "category",
    }
    assert (
        _client(scopes=("publish_operator",))
        .get("/api/staff/reports/hours-by-category", params=params)
        .status_code
        == 403
    )
    assert (
        _client(scopes=("support_admin",))
        .get("/api/staff/reports/hours-by-category", params=params)
        .status_code
        == 200
    )


def test_export_requires_support_admin() -> None:
    params = {
        "type": "shows",
        "format": "csv",
        "from": _now().isoformat(),
        "to": (_now() + timedelta(days=1)).isoformat(),
    }
    assert (
        _client(scopes=("publish_operator",))
        .get("/api/staff/reports/export", params=params)
        .status_code
        == 403
    )
    r = _client(scopes=("support_admin",)).get("/api/staff/reports/export", params=params)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


# --- role gating: EPG configs -----------------------------------------------


def test_list_epg_configs_role_gating() -> None:
    assert _client(scopes=None).get("/api/staff/epg/configs").status_code == 401
    assert _client(scopes=("support_admin",)).get("/api/staff/epg/configs").status_code == 403
    assert _client(scopes=("publish_operator",)).get("/api/staff/epg/configs").status_code == 200
    assert _client(scopes=("setup_admin",)).get("/api/staff/epg/configs").status_code == 200


def test_create_epg_config_requires_epg_write_role() -> None:
    payload = {
        "config_id": "cfg-a",
        "station_id": _STATION,
        "channel_id": "ch1",
        "format": "csv",
    }
    assert (
        _client(scopes=("support_admin",)).post("/api/staff/epg/configs", json=payload).status_code
        == 403
    )
    r = _client(scopes=("publish_operator",)).post("/api/staff/epg/configs", json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["config_id"] == "cfg-a"


# --- reports: happy paths ----------------------------------------------------


def _seed_as_run(store: ReportingStore, *, count: int = 3) -> datetime:
    start = _now()
    for i in range(count):
        store.append_as_run(
            AsRunLogEntry(
                entry_id=f"asrun-{i}",
                station_id=_STATION,
                channel_id="ch1",
                asset_id=f"asset-{i % 2}",
                actual_start=start + timedelta(minutes=i),
                actual_end=start + timedelta(minutes=i + 1),
                duration_s=60,
                source_kind="program",
                verified=True,
            )
        )
    return start


def test_shows_report_returns_aggregated_rows() -> None:
    app, store, *_ = _build()
    start = _seed_as_run(store, count=4)
    r = TestClient(app).get(
        "/api/staff/reports/shows",
        params={
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    asset_ids = sorted(row["asset_id"] for row in body["rows"])
    assert asset_ids == ["asset-0", "asset-1"]


def test_as_run_report_round_trip() -> None:
    app, store, *_ = _build()
    start = _seed_as_run(store, count=2)
    r = TestClient(app).get(
        "/api/staff/reports/as-run",
        params={
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 2


def test_export_csv_attaches_filename() -> None:
    app, store, *_ = _build()
    start = _seed_as_run(store, count=1)
    r = TestClient(app).get(
        "/api/staff/reports/export",
        params={
            "type": "as-run",
            "format": "csv",
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert ".csv" in r.headers["content-disposition"]


def test_export_xml_attaches_filename() -> None:
    app, store, *_ = _build()
    start = _seed_as_run(store, count=1)
    r = TestClient(app).get(
        "/api/staff/reports/export",
        params={
            "type": "shows",
            "format": "xml",
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert ".xml" in r.headers["content-disposition"]


def test_hours_by_category_field_not_found_returns_200_with_flag() -> None:
    app, store, *_ = _build()
    start = _seed_as_run(store, count=1)
    r = TestClient(app).get(
        "/api/staff/reports/hours-by-category",
        params={
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
            "field": "does_not_exist",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["field_not_found"] is True
    assert body["rows"] == []


# --- EPG configs CRUD --------------------------------------------------------


def test_get_missing_epg_config_returns_404() -> None:
    r = _client().get("/api/staff/epg/configs/no-such-config")
    assert r.status_code == 404
    assert "not found" in r.text


def test_patch_missing_epg_config_returns_404() -> None:
    r = _client().patch("/api/staff/epg/configs/no-such-config", json={"format": "xmltv"})
    assert r.status_code == 404


def test_delete_missing_epg_config_returns_404() -> None:
    r = _client().delete("/api/staff/epg/configs/no-such-config")
    assert r.status_code == 404


def test_epg_config_round_trip_create_get_patch_delete() -> None:
    app, store, *_ = _build()
    client = TestClient(app)

    payload = {
        "config_id": "cfg-zeta",
        "station_id": _STATION,
        "channel_id": "ch1",
        "format": "csv",
        "horizon_days": 7,
    }
    r = client.post("/api/staff/epg/configs", json=payload)
    assert r.status_code == 201, r.text

    r = client.get("/api/staff/epg/configs/cfg-zeta")
    assert r.status_code == 200
    assert r.json()["format"] == "csv"

    r = client.patch("/api/staff/epg/configs/cfg-zeta", json={"format": "xmltv"})
    assert r.status_code == 200
    assert r.json()["format"] == "xmltv"
    assert r.json()["horizon_days"] == 7  # unchanged

    r = client.delete("/api/staff/epg/configs/cfg-zeta")
    assert r.status_code == 204

    assert store.get_config("cfg-zeta") is None


# --- EPG generate ------------------------------------------------------------


def _seed_committed_slot(*, start: datetime, asset_id: str = "asset-0") -> CommittedSlot:
    return CommittedSlot(
        slot_id=f"slot-{asset_id}",
        asset_id=asset_id,
        title="Council Meeting",
        start=start,
        end=start + timedelta(minutes=30),
        duration_s=30 * 60,
        description=None,
        category=None,
        rating=None,
    )


def test_generate_returns_document_when_endpoint_is_none() -> None:
    start = _now() + timedelta(hours=1)
    app, store, *_ = _build(seeded_slots=[_seed_committed_slot(start=start)])
    store.upsert_config(
        EpgExportConfig(
            config_id="cfg-download",
            station_id=_STATION,
            channel_id="ch1",
            format="csv",
            horizon_days=14,
            endpoint=None,
        )
    )
    r = TestClient(app).post("/api/staff/epg/configs/cfg-download/generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "csv"
    assert body["slot_count"] == 1
    assert body["document"] is not None
    assert "Council Meeting" in body["document"]
    assert body["pushed_to"] is None
    assert body["error"] is None


def test_generate_with_push_fail_surfaces_error_not_500() -> None:
    """A flaky aggregator must NOT crash the staff API."""

    def boom(_url: str, _body: str, _ct: str) -> None:
        raise RuntimeError("aggregator down")

    start = _now() + timedelta(hours=1)
    app, store, *_ = _build(
        seeded_slots=[_seed_committed_slot(start=start)],
        push_fn=boom,
    )
    store.upsert_config(
        EpgExportConfig(
            config_id="cfg-push",
            station_id=_STATION,
            channel_id="ch1",
            format="csv",
            horizon_days=14,
            endpoint="https://aggregator.example.com/ingest",
        )
    )
    r = TestClient(app).post("/api/staff/epg/configs/cfg-push/generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is not None
    assert "aggregator down" in body["error"]
    assert body["pushed_to"] is None


def test_generate_missing_config_returns_404() -> None:
    r = _client().post("/api/staff/epg/configs/no-such/generate")
    assert r.status_code == 404


# --- public as-run -----------------------------------------------------------


def test_public_as_run_reachable_without_identity() -> None:
    app, store, *_ = _build(scopes=None)
    start = _seed_as_run(store, count=1)
    r = TestClient(app).get(
        "/api/public/reports/as-run",
        params={
            "from": start.isoformat(),
            "to": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 1
    # Public projection: category must be None (no S22 cf join on the public route).
    assert body["rows"][0]["category"] is None
    # Q-1 + T-4: the public projection must DROP engine-internal metadata —
    # ``verified`` (internal engine state), ``created_at`` / ``updated_at``
    # (ledger-write timestamps that hint at internal scheduling latency).
    entry = body["rows"][0]["entry"]
    assert "verified" not in entry
    assert "created_at" not in entry
    assert "updated_at" not in entry
    # And the projection is exactly the documented public field set — every
    # other AsRunLogEntry field is preserved, no more, no less.
    assert set(entry.keys()) == {
        "entry_id",
        "station_id",
        "channel_id",
        "schedule_item_id",
        "asset_id",
        "scheduled_start",
        "actual_start",
        "actual_end",
        "duration_s",
        "source_kind",
    }


# --- T-3: empty-state at the router surface ---------------------------------


def test_shows_report_empty_returns_200_empty_rows() -> None:
    """An empty as-run ledger must return 200 + ``rows: []`` from the shows
    report, not 500, not null. Locks the Lite-probe finding in CI.
    """
    app, _store, *_ = _build()
    r = TestClient(app).get(
        "/api/staff/reports/shows",
        params={
            "from": _now().isoformat(),
            "to": (_now() + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == []


def test_as_run_report_empty_returns_200_empty_rows() -> None:
    """Same empty-state lock for the as-run report."""
    app, _store, *_ = _build()
    r = TestClient(app).get(
        "/api/staff/reports/as-run",
        params={
            "from": _now().isoformat(),
            "to": (_now() + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == []


def test_list_epg_configs_empty_returns_200_empty_list() -> None:
    """An empty config store returns ``[]`` from the list endpoint, not 500."""
    app, _store, *_ = _build()
    r = TestClient(app).get("/api/staff/epg/configs")
    assert r.status_code == 200
    assert r.json() == []
