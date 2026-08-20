# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S24 underwriting + affidavits API: role gating, 503 unwired, CRUD, affidavit join + export.

A minimal FastAPI app mounts the real underwriting router, installs an
operator-identity middleware (so ``require_any_role`` runs), and overrides
the DI seams with a SQLite-backed ``UnderwritingStore`` + ``ReportingStore``
+ ``AffidavitService``. Covers:

* role gating on every staff route (``publish_operator`` / ``setup_admin``
  manage; ``support_admin`` reads affidavits; 401 without identity; 403 for
  wrong scope);
* 503 when either DI seam is unwired;
* spot CRUD (create / get / patch / delete + 404s);
* flight CRUD + ``active_on`` filter + 422 on bad date;
* placements GET (window + channel + flight filters);
* affidavits GET (period + underwriter) + export (CSV / XML / PDF
  filename + Content-Type).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.reporting.models import AsRunLogEntry
from civiccast.reporting.store import ReportingStore
from civiccast.underwriting.models import (
    SpotFlight,
    SpotPlacement,
    UnderwritingSpot,
)
from civiccast.underwriting.router import (
    get_affidavit_service,
    get_underwriting_store,
    staff_router,
)
from civiccast.underwriting.service import AffidavitService
from civiccast.underwriting.store import UnderwritingStore

_STATION = "civiccast-station"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _build(
    *,
    scopes: tuple[str, ...] | None = ("publish_operator", "setup_admin", "support_admin"),
    wire_store: bool = True,
    wire_affidavit: bool = True,
) -> tuple[FastAPI, UnderwritingStore, ReportingStore, AffidavitService]:
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

    underwriting_store = UnderwritingStore(factory)
    reporting_store = ReportingStore(factory)
    affidavit_service = AffidavitService(
        underwriting_store=underwriting_store,
        reporting_store=reporting_store,
    )

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
    if wire_store:
        app.dependency_overrides[get_underwriting_store] = lambda: underwriting_store
    if wire_affidavit:
        app.dependency_overrides[get_affidavit_service] = lambda: affidavit_service
    return app, underwriting_store, reporting_store, affidavit_service


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _spot_payload(spot_id: str = "sp-acme", **overrides: object) -> dict:
    body = {
        "spot_id": spot_id,
        "station_id": _STATION,
        "underwriter": "Acme Co.",
        "asset_id": "asset-acme-15",
        "fcc_compliant_ack": True,
    }
    body.update(overrides)  # type: ignore[arg-type]
    return body


def _flight_payload(flight_id: str = "fl-a", spot_id: str = "sp-acme") -> dict:
    return {
        "flight_id": flight_id,
        "spot_id": spot_id,
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "frequency_cap_per_day": 3,
        "channels": ["pub-1"],
    }


# --- 503 when unwired --------------------------------------------------------


def test_503_when_store_unwired() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).get("/api/staff/underwriting/spots")
    assert r.status_code == 503
    assert "not ready" in r.text


def test_503_when_affidavit_service_unwired() -> None:
    app, *_ = _build(wire_affidavit=False)
    params = {"underwriter": "Acme", "from": "2026-06-01", "to": "2026-06-30"}
    r = TestClient(app).get("/api/staff/underwriting/affidavits", params=params)
    assert r.status_code == 503


# --- role gating: spot CRUD --------------------------------------------------


def test_list_spots_requires_manage_role() -> None:
    assert _client(scopes=None).get("/api/staff/underwriting/spots").status_code == 401
    # support_admin reads affidavits, NOT spots
    assert (
        _client(scopes=("support_admin",)).get("/api/staff/underwriting/spots").status_code == 403
    )
    assert (
        _client(scopes=("publish_operator",)).get("/api/staff/underwriting/spots").status_code
        == 200
    )
    assert _client(scopes=("setup_admin",)).get("/api/staff/underwriting/spots").status_code == 200


def test_create_spot_requires_manage_role() -> None:
    r = _client(scopes=("support_admin",)).post(
        "/api/staff/underwriting/spots", json=_spot_payload()
    )
    assert r.status_code == 403
    r = _client(scopes=("publish_operator",)).post(
        "/api/staff/underwriting/spots", json=_spot_payload()
    )
    assert r.status_code == 201
    assert r.json()["spot_id"] == "sp-acme"


# --- spot CRUD round-trip ----------------------------------------------------


def test_spot_round_trip_create_get_patch_delete() -> None:
    app, store, *_ = _build()
    client = TestClient(app)
    client.post("/api/staff/underwriting/spots", json=_spot_payload())
    r = client.get("/api/staff/underwriting/spots/sp-acme")
    assert r.status_code == 200
    assert r.json()["underwriter"] == "Acme Co."
    r = client.patch("/api/staff/underwriting/spots/sp-acme", json={"underwriter": "Acme NEW"})
    assert r.status_code == 200
    assert r.json()["underwriter"] == "Acme NEW"
    r = client.delete("/api/staff/underwriting/spots/sp-acme")
    assert r.status_code == 204
    assert store.get_spot("sp-acme") is None


def test_get_missing_spot_returns_404() -> None:
    r = _client().get("/api/staff/underwriting/spots/no-such-spot")
    assert r.status_code == 404


def test_patch_missing_spot_returns_404() -> None:
    r = _client().patch("/api/staff/underwriting/spots/no-such", json={"underwriter": "X"})
    assert r.status_code == 404


def test_delete_missing_spot_returns_404() -> None:
    r = _client().delete("/api/staff/underwriting/spots/no-such")
    assert r.status_code == 404


def test_delete_spot_cascades_flights_and_placements_via_api() -> None:
    app, store, *_ = _build()
    client = TestClient(app)
    client.post("/api/staff/underwriting/spots", json=_spot_payload())
    client.post("/api/staff/underwriting/flights", json=_flight_payload())
    store.record_placement(
        SpotPlacement(
            placement_id="pl-1",
            flight_id="fl-a",
            channel_id="pub-1",
            scheduled_at=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
            schedule_item_id="si-1",
        )
    )
    r = client.delete("/api/staff/underwriting/spots/sp-acme")
    assert r.status_code == 204
    assert store.get_flight("fl-a") is None
    assert store.get_placement("pl-1") is None


# --- flight CRUD ------------------------------------------------------------


def test_flight_round_trip() -> None:
    app, store, *_ = _build()
    client = TestClient(app)
    client.post("/api/staff/underwriting/spots", json=_spot_payload())
    r = client.post("/api/staff/underwriting/flights", json=_flight_payload())
    assert r.status_code == 201, r.text
    r = client.get("/api/staff/underwriting/flights/fl-a")
    assert r.status_code == 200
    assert r.json()["channels"] == ["pub-1"]
    r = client.patch("/api/staff/underwriting/flights/fl-a", json={"frequency_cap_per_day": 5})
    assert r.status_code == 200
    assert r.json()["frequency_cap_per_day"] == 5
    r = client.delete("/api/staff/underwriting/flights/fl-a")
    assert r.status_code == 204
    assert store.get_flight("fl-a") is None


def test_list_flights_filters_active_on() -> None:
    app, *_ = _build()
    client = TestClient(app)
    client.post("/api/staff/underwriting/spots", json=_spot_payload())
    client.post("/api/staff/underwriting/flights", json=_flight_payload())
    # outside window
    r = client.get("/api/staff/underwriting/flights", params={"active_on": "2026-07-15"})
    assert r.status_code == 200
    assert r.json() == []
    # inside window
    r = client.get("/api/staff/underwriting/flights", params={"active_on": "2026-06-10"})
    assert len(r.json()) == 1


def test_list_flights_bad_active_on_returns_422() -> None:
    r = _client().get("/api/staff/underwriting/flights", params={"active_on": "not-a-date"})
    assert r.status_code == 422


# --- placements view -------------------------------------------------------


def test_list_placements_window_and_channel() -> None:
    app, store, *_ = _build()
    # seed via the store directly (placements are written by the compiler, not the API)
    spot = UnderwritingSpot(
        spot_id="sp-1",
        station_id=_STATION,
        underwriter="X",
        asset_id="asset-x",
        fcc_compliant_ack=True,
    )
    store.upsert_spot(spot)
    store.upsert_flight(
        SpotFlight(
            flight_id="fl-1",
            spot_id="sp-1",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1"],
        )
    )
    for i in range(3):
        store.record_placement(
            SpotPlacement(
                placement_id=f"pl-{i}",
                flight_id="fl-1",
                channel_id="pub-1" if i < 2 else "edu-1",
                scheduled_at=datetime(2026, 6, 10 + i, 18, 0, tzinfo=UTC),
                schedule_item_id=f"si-{i}",
            )
        )
    client = TestClient(app)
    r = client.get(
        "/api/staff/underwriting/placements",
        params={
            "from": "2026-06-10T00:00:00Z",
            "to": "2026-06-13T00:00:00Z",
            "channel": "pub-1",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert {p["placement_id"] for p in body} == {"pl-0", "pl-1"}


# --- affidavits ------------------------------------------------------------


def _seed_underwriter_airings(store: UnderwritingStore, reporting_store: ReportingStore) -> None:
    spot = UnderwritingSpot(
        spot_id="sp-acme",
        station_id=_STATION,
        underwriter="Acme Co.",
        asset_id="asset-acme-15",
        fcc_compliant_ack=True,
    )
    store.upsert_spot(spot)
    store.upsert_flight(
        SpotFlight(
            flight_id="fl-acme",
            spot_id="sp-acme",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1"],
        )
    )
    for i in range(3):
        sched_at = datetime(2026, 6, 10 + i, 18, 0, tzinfo=UTC)
        store.record_placement(
            SpotPlacement(
                placement_id=f"pl-{i}",
                flight_id="fl-acme",
                channel_id="pub-1",
                scheduled_at=sched_at,
                schedule_item_id=f"si-{i}",
            )
        )
        reporting_store.append_as_run(
            AsRunLogEntry(
                entry_id=f"asrun-{i}",
                station_id=_STATION,
                channel_id="pub-1",
                schedule_item_id=f"si-{i}",
                asset_id="asset-acme-15",
                actual_start=sched_at,
                actual_end=sched_at + timedelta(seconds=30),
                duration_s=30,
                source_kind="spot",
                verified=True,
            )
        )


def test_affidavit_role_gating() -> None:
    params = {"underwriter": "Acme Co.", "from": "2026-06-01", "to": "2026-06-30"}
    # publish_operator does NOT read affidavits
    assert (
        _client(scopes=("publish_operator",))
        .get("/api/staff/underwriting/affidavits", params=params)
        .status_code
        == 403
    )
    assert (
        _client(scopes=("support_admin",))
        .get("/api/staff/underwriting/affidavits", params=params)
        .status_code
        == 200
    )


def test_affidavit_returns_airings_and_totals() -> None:
    app, store, reporting, *_ = _build()
    _seed_underwriter_airings(store, reporting)
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits",
        params={
            "underwriter": "Acme Co.",
            "from": "2026-06-01",
            "to": "2026-06-30",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["underwriter"] == "Acme Co."
    assert body["total_airings"] == 3
    assert body["total_seconds"] == 90
    assert len(body["aired"]) == 3


def test_affidavit_bad_date_returns_422() -> None:
    r = _client().get(
        "/api/staff/underwriting/affidavits",
        params={"underwriter": "Acme Co.", "from": "BAD", "to": "2026-06-30"},
    )
    assert r.status_code == 422


def test_affidavit_export_csv() -> None:
    app, store, reporting, *_ = _build()
    _seed_underwriter_airings(store, reporting)
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": "Acme Co.",
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "csv",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert ".csv" in r.headers["content-disposition"]


def test_affidavit_export_xml() -> None:
    app, store, reporting, *_ = _build()
    _seed_underwriter_airings(store, reporting)
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": "Acme Co.",
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "xml",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")


def test_affidavit_export_pdf() -> None:
    app, store, reporting, *_ = _build()
    _seed_underwriter_airings(store, reporting)
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": "Acme Co.",
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "pdf",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


def test_affidavit_export_bad_format_rejected() -> None:
    r = _client().get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": "Acme Co.",
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "wat",
        },
    )
    assert r.status_code == 422


# --- station policy: CIVICCAST_REQUIRE_FCC_ACK env (DC-5) -------------------


def test_create_spot_rejects_unacked_when_require_fcc_ack_env_set(
    monkeypatch,
) -> None:
    """When the station sets ``CIVICCAST_REQUIRE_FCC_ACK=1``, a create of a spot
    whose ``fcc_compliant_ack`` is False returns 422 with a 47 CFR 73.503
    explanation — the operator must attest sponsor-ID-only before save."""
    monkeypatch.setenv("CIVICCAST_REQUIRE_FCC_ACK", "1")
    client = _client()
    r = client.post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-noack", fcc_compliant_ack=False),
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert "CIVICCAST_REQUIRE_FCC_ACK" in body["detail"]
    assert "47 CFR 73.503" in body["detail"]


def test_create_spot_accepts_acked_when_require_fcc_ack_env_set(monkeypatch) -> None:
    """With the env on, ``fcc_compliant_ack=True`` is accepted — the gate is
    on the attestation, not on every spot."""
    monkeypatch.setenv("CIVICCAST_REQUIRE_FCC_ACK", "1")
    client = _client()
    r = client.post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-ok", fcc_compliant_ack=True),
    )
    assert r.status_code == 201, r.text
    assert r.json()["fcc_compliant_ack"] is True


def test_create_spot_allows_unacked_when_env_unset(monkeypatch) -> None:
    """When the env is unset (or "0"), the legacy behavior holds: a spot with
    ``fcc_compliant_ack=False`` is stored as posted (no API-level rejection)."""
    monkeypatch.delenv("CIVICCAST_REQUIRE_FCC_ACK", raising=False)
    r = _client().post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-legacy", fcc_compliant_ack=False),
    )
    assert r.status_code == 201, r.text
    assert r.json()["fcc_compliant_ack"] is False


def test_create_spot_allows_unacked_when_env_zero(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_REQUIRE_FCC_ACK", "0")
    r = _client().post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-zero", fcc_compliant_ack=False),
    )
    assert r.status_code == 201


def test_patch_spot_rejects_unack_landing_when_require_fcc_ack_env_set(
    monkeypatch,
) -> None:
    """A patch that would land a spot at ``fcc_compliant_ack=False`` while the
    station-policy env is on is refused with 422 — the gate fires on the
    merged spot, not just the inbound payload."""
    # Seed an acked spot with the env off, then turn the env on and patch.
    monkeypatch.delenv("CIVICCAST_REQUIRE_FCC_ACK", raising=False)
    app, *_ = _build()
    client = TestClient(app)
    create = client.post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-flip", fcc_compliant_ack=True),
    )
    assert create.status_code == 201
    monkeypatch.setenv("CIVICCAST_REQUIRE_FCC_ACK", "1")
    r = client.patch(
        "/api/staff/underwriting/spots/sp-flip",
        json={"fcc_compliant_ack": False},
    )
    assert r.status_code == 422, r.text
    assert "CIVICCAST_REQUIRE_FCC_ACK" in r.json()["detail"]


def test_patch_spot_allows_ack_landing_when_require_fcc_ack_env_set(monkeypatch) -> None:
    """A patch is accepted as long as the merged spot ends with
    ``fcc_compliant_ack=True`` — including an unrelated patch that does not
    touch the ack flag at all."""
    monkeypatch.setenv("CIVICCAST_REQUIRE_FCC_ACK", "1")
    app, *_ = _build()
    client = TestClient(app)
    client.post(
        "/api/staff/underwriting/spots",
        json=_spot_payload(spot_id="sp-edit", fcc_compliant_ack=True),
    )
    r = client.patch(
        "/api/staff/underwriting/spots/sp-edit",
        json={"underwriter": "Acme NEW"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["underwriter"] == "Acme NEW"
    assert r.json()["fcc_compliant_ack"] is True
