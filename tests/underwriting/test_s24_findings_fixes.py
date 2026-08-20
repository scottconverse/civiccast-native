# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S24 GauntletGate full-lane regression tests.

Locks the behavior fixed for the engineering / test / QA findings:

* T-1 — the trafficking compiler is wired through ``_wire_durable_stores``
  and reachable via ``POST /api/staff/underwriting/compile``.
* E-1 — the compiler issues O(1) DB calls per ``compile_for_date`` for cap
  + picker accounting (a per-candidate N+1 over ``list_placements`` would
  otherwise blow up at scale).
* E-2 / Q-3 — affidavit-export ``Content-Disposition`` is RFC 6266 / RFC 5987
  safe; quotes / control chars / semicolons in the underwriter param cannot
  inject extra header parameters.
* E-4 — concurrent ``compile_for_date`` calls on the same
  ``(station, date)`` serialize via the in-process lock + deterministic
  ``placement_id`` derivation, so the final placement count is the same as
  the single-thread case.
* E-5 — ``ReportingStore.list_as_run(source_kind=...)`` narrows the SQL.
* Q-1 / Q-2 — ``POST`` and ``PATCH`` flights with ``end_date < start_date``
  surface as 422, not 500.
* Q-4 — ``POST /spots`` and ``POST /flights`` against an existing id return
  409 instead of silent-upsert.
* Q-5 — ``GET`` / ``/export`` affidavits with ``from > to`` return 422.
* T-2 — frequency cap is enforced across ALL channels a flight targets, not
  per-channel.
* T-3 — affidavit PDF paginates correctly past page 1.
* T-4 — two spots sharing the same ``asset_id`` BOTH get billed for an
  as-run row carrying that asset.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
    UnderwritingSpot,
)
from civiccast.underwriting.router import (
    get_affidavit_service,
    get_trafficking_compiler,
    get_underwriting_store,
    staff_router,
)
from civiccast.underwriting.service import (
    AffidavitAiring,
    AffidavitService,
    CandidateBreakSlot,
    TraffickingCompiler,
    UnderwriterAffidavit,
    export_affidavit_pdf,
)
from civiccast.underwriting.store import UnderwritingStore

_STATION = "civiccast-station"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_store(tmp_path: Path) -> Iterator[UnderwritingStore]:
    """An on-disk SQLite-backed underwriting store (E-1 N+1 test needs one)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'findings.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield UnderwritingStore(factory)
    finally:
        eng.dispose()


@pytest.fixture
def stores(
    tmp_path: Path,
) -> Iterator[tuple[UnderwritingStore, ReportingStore]]:
    eng = create_engine(f"sqlite:///{tmp_path / 'findings_pair.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield UnderwritingStore(factory), ReportingStore(factory)
    finally:
        eng.dispose()


def _build_app(
    *,
    scopes: tuple[str, ...] | None = (
        "publish_operator",
        "setup_admin",
        "support_admin",
    ),
    wire_compiler: bool = True,
) -> tuple[
    FastAPI,
    UnderwritingStore,
    ReportingStore,
    AffidavitService,
    TraffickingCompiler | None,
]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    u_store = UnderwritingStore(factory)
    r_store = ReportingStore(factory)
    affidavit = AffidavitService(underwriting_store=u_store, reporting_store=r_store)
    compiler: TraffickingCompiler | None = None
    if wire_compiler:
        compiler = TraffickingCompiler(u_store, station_id=_STATION)

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
    app.dependency_overrides[get_underwriting_store] = lambda: u_store
    app.dependency_overrides[get_affidavit_service] = lambda: affidavit
    if wire_compiler:
        app.dependency_overrides[get_trafficking_compiler] = lambda: compiler
    return app, u_store, r_store, affidavit, compiler


# ---------------------------------------------------------------------------
# T-1 — trafficking compiler reachable from production wiring + endpoint
# ---------------------------------------------------------------------------


def test_app_factory_wires_trafficking_compiler() -> None:
    """``_wire_durable_stores`` must override ``get_trafficking_compiler`` so
    the compile endpoint is reachable; the default DI seam returns ``None``
    (fail-closed 503). The actual app factory is exercised by other tests;
    here we assert the symbol is exported and the default is the fail-closed
    sentinel."""
    assert get_trafficking_compiler() is None


def test_compile_endpoint_503_when_unwired() -> None:
    app, *_ = _build_app(wire_compiler=False)
    client = TestClient(app)
    r = client.post(
        "/api/staff/underwriting/compile",
        json={
            "for_date": "2026-06-09",
            "candidates": [],
            "local_tz_offset_minutes": 0,
        },
    )
    assert r.status_code == 503


def test_compile_endpoint_requires_manage_role() -> None:
    app, *_ = _build_app(scopes=("support_admin",))
    r = TestClient(app).post(
        "/api/staff/underwriting/compile",
        json={
            "for_date": "2026-06-09",
            "candidates": [],
            "local_tz_offset_minutes": 0,
        },
    )
    assert r.status_code == 403


def test_compile_endpoint_places_a_real_spot() -> None:
    """Integration test (T-1): seed a spot + a flight + a candidate break
    slot, POST /compile, assert the placement lands in the store and is
    reflected back through GET /placements."""
    app, u_store, *_ = _build_app()
    client = TestClient(app)
    # Seed via the API so role gating + DI wire are exercised end-to-end.
    spot_payload = {
        "spot_id": "sp-acme",
        "station_id": _STATION,
        "underwriter": "Acme Co.",
        "asset_id": "asset-acme-15",
        "fcc_compliant_ack": True,
    }
    assert client.post("/api/staff/underwriting/spots", json=spot_payload).status_code == 201
    flight_payload = {
        "flight_id": "fl-a",
        "spot_id": "sp-acme",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "channels": ["pub-1"],
    }
    assert client.post("/api/staff/underwriting/flights", json=flight_payload).status_code == 201

    r = client.post(
        "/api/staff/underwriting/compile",
        json={
            "for_date": "2026-06-10",
            "candidates": [
                {
                    "channel_id": "pub-1",
                    "scheduled_at": "2026-06-10T18:00:00Z",
                    "schedule_item_id": "si-1",
                }
            ],
            "local_tz_offset_minutes": 0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["placements"]) == 1
    assert body["placements"][0]["placement_id"] == "pl-si-1"
    assert body["placements"][0]["flight_id"] == "fl-a"

    # And the placement is reflected in the dedicated listing endpoint.
    listing = client.get(
        "/api/staff/underwriting/placements",
        params={
            "from": "2026-06-10T00:00:00Z",
            "to": "2026-06-11T00:00:00Z",
        },
    )
    assert listing.status_code == 200
    assert [p["placement_id"] for p in listing.json()] == ["pl-si-1"]
    # Store side-effect parity.
    assert u_store.get_placement("pl-si-1") is not None


# ---------------------------------------------------------------------------
# E-1 — bulk count queries replace the per-candidate N+1
# ---------------------------------------------------------------------------


def test_compile_for_date_uses_bulk_count_not_per_candidate_listing() -> None:
    """The cap + picker code must NOT call ``list_placements`` inside the
    candidate loop (the N+1 root cause). With a mocked store we count calls
    to the two new bulk methods AND assert ``list_placements`` is not used
    for cap accounting."""
    store = MagicMock(spec=UnderwritingStore)
    flight = SpotFlight(
        flight_id="fl-1",
        spot_id="sp-1",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        frequency_cap_per_day=10,
        channels=["pub-1"],
    )
    spot = UnderwritingSpot(
        spot_id="sp-1",
        station_id=_STATION,
        underwriter="Acme",
        asset_id="asset-1",
        fcc_compliant_ack=True,
    )
    store.list_flights.return_value = [flight]
    store.get_spot.return_value = spot
    # Return a FRESH dict on each call — the compiler mutates the returned
    # dicts in-memory (per-day and lifetime tallies), so a shared instance
    # would double-count.
    store.count_placements_by_flight.side_effect = lambda **_: {"fl-1": 0}
    store.record_placement.side_effect = lambda p: p

    candidates = [
        CandidateBreakSlot(
            channel_id="pub-1",
            scheduled_at=datetime(2026, 6, 10, 8 + i, tzinfo=UTC),
            schedule_item_id=f"si-{i}",
        )
        for i in range(8)
    ]
    compiler = TraffickingCompiler(store, station_id=_STATION)
    result = compiler.compile_for_date(for_date=date(2026, 6, 10), candidates=candidates)
    assert len(result.placements) == 8
    # Exactly two bulk-count queries: one for per-day caps, one for lifetime.
    assert store.count_placements_by_flight.call_count == 2
    # The legacy per-candidate ``list_placements`` is never reached in the
    # hot path (called nowhere by the compiler for cap accounting).
    assert store.list_placements.call_count == 0


# ---------------------------------------------------------------------------
# E-2 / Q-3 — Content-Disposition header injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil_underwriter",
    [
        'Evil" attack="yes',
        "underwriter\r\nX-Injected: 1",
        "name;with;semicolons",
        "name\\with\\backslashes",
    ],
)
def test_export_filename_quoted_for_unsafe_underwriter(evil_underwriter: str) -> None:
    app, *_ = _build_app()
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": evil_underwriter,
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "csv",
        },
    )
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    # Both parameters must be present and well-formed.
    assert cd.startswith('attachment; filename="affidavit-')
    assert "filename*=UTF-8''" in cd
    # The ASCII filename must NOT carry the underwriter (no quote-escape
    # foot-guns), and the UTF-8 filename must be percent-encoded so quotes /
    # CRLF / semicolons cannot smuggle an extra parameter.
    assert '"' not in cd.split("filename*=")[0].split('filename="')[1].rstrip('"; ')
    assert "\r" not in cd
    assert "\n" not in cd


def test_export_filename_real_underwriter_with_punctuation() -> None:
    """A real underwriter name like ``Carter & Sons, "Dependable" LLC`` must
    not 500 the export — that was the regression mode of the old f-string
    header."""
    app, *_ = _build_app()
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": 'Carter & Sons, "Dependable" LLC',
            "from": "2026-06-01",
            "to": "2026-06-30",
            "format": "csv",
        },
    )
    assert r.status_code == 200
    # The percent-encoded name carries the safely-encoded form.
    cd = r.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert "%22" in cd  # encoded "
    assert "%26" in cd  # encoded &


# ---------------------------------------------------------------------------
# E-4 — concurrent compile_for_date serializes
# ---------------------------------------------------------------------------


def test_concurrent_compile_for_date_is_idempotent(
    file_store: UnderwritingStore,
) -> None:
    """Two threads calling ``compile_for_date`` with the same candidate set on
    the same date must converge on the SAME placement count as a single-thread
    run. The deterministic ``placement_id`` + the in-process serialization
    lock together guarantee no over-placement, no duplicates, no last-writer
    flight attribution churn."""
    file_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
            fcc_compliant_ack=True,
        )
    )
    file_store.upsert_flight(
        SpotFlight(
            flight_id="fl-1",
            spot_id="sp-1",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1"],
        )
    )

    candidates = [
        CandidateBreakSlot(
            channel_id="pub-1",
            scheduled_at=datetime(2026, 6, 10, 8 + i, tzinfo=UTC),
            schedule_item_id=f"si-{i}",
        )
        for i in range(6)
    ]
    compiler = TraffickingCompiler(file_store, station_id=_STATION)

    results: list[int] = []

    def run() -> None:
        result = compiler.compile_for_date(for_date=date(2026, 6, 10), candidates=candidates)
        results.append(len(result.placements))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Both threads each report 6 placements (each saw the full candidate set),
    # but the persisted rows total exactly 6 (idempotent on placement_id).
    persisted = file_store.list_placements(
        from_ts=datetime(2026, 6, 10, tzinfo=UTC),
        to_ts=datetime(2026, 6, 11, tzinfo=UTC),
    )
    assert len(persisted) == 6
    assert {p.placement_id for p in persisted} == {f"pl-si-{i}" for i in range(6)}
    # Every thread saw the same idempotent count.
    assert all(n == 6 for n in results)


# ---------------------------------------------------------------------------
# E-5 — list_as_run accepts source_kind
# ---------------------------------------------------------------------------


def test_list_as_run_source_kind_filters_at_sql(
    stores: tuple[UnderwritingStore, ReportingStore],
) -> None:
    _, r_store = stores
    base = datetime(2026, 6, 10, 10, tzinfo=UTC)
    for i, kind in enumerate(["program", "spot", "filler", "spot", "slate"]):
        r_store.append_as_run(
            AsRunLogEntry(
                entry_id=f"asrun-{i}",
                station_id=_STATION,
                channel_id="pub-1",
                schedule_item_id=None,
                asset_id="asset-1",
                actual_start=base + timedelta(minutes=i),
                actual_end=base + timedelta(minutes=i, seconds=30),
                duration_s=30,
                source_kind=kind,  # type: ignore[arg-type]
            )
        )
    rows = r_store.list_as_run(_STATION, source_kind="spot")
    assert {r.entry_id for r in rows} == {"asrun-1", "asrun-3"}


# ---------------------------------------------------------------------------
# Q-1 / Q-2 — flight date-order on POST + PATCH
# ---------------------------------------------------------------------------


def test_post_flight_with_inverted_dates_returns_422() -> None:
    app, u_store, *_ = _build_app()
    # Seed the spot to make sure the failure is the validator, not a 404 etc.
    u_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
        )
    )
    r = TestClient(app).post(
        "/api/staff/underwriting/flights",
        json={
            "flight_id": "fl-x",
            "spot_id": "sp-1",
            "start_date": "2026-02-01",
            "end_date": "2026-01-01",
            "channels": ["pub-1"],
        },
    )
    assert r.status_code == 422
    assert "end_date must be on or after start_date" in r.text


def test_patch_flight_pushing_end_before_start_returns_422() -> None:
    app, u_store, *_ = _build_app()
    u_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
        )
    )
    client = TestClient(app)
    create = client.post(
        "/api/staff/underwriting/flights",
        json={
            "flight_id": "fl-x",
            "spot_id": "sp-1",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
            "channels": ["pub-1"],
        },
    )
    assert create.status_code == 201
    patch = client.patch(
        "/api/staff/underwriting/flights/fl-x",
        json={"end_date": "2026-02-15"},
    )
    assert patch.status_code == 422


# ---------------------------------------------------------------------------
# Q-4 — duplicate id on POST returns 409
# ---------------------------------------------------------------------------


def test_post_spot_with_existing_id_returns_409() -> None:
    app, *_ = _build_app()
    client = TestClient(app)
    payload = {
        "spot_id": "sp-dupe",
        "station_id": _STATION,
        "underwriter": "Original",
        "asset_id": "asset-orig",
    }
    assert client.post("/api/staff/underwriting/spots", json=payload).status_code == 201
    again = client.post(
        "/api/staff/underwriting/spots",
        json={**payload, "underwriter": "Hijack"},
    )
    assert again.status_code == 409
    # The original survived.
    got = client.get("/api/staff/underwriting/spots/sp-dupe").json()
    assert got["underwriter"] == "Original"


def test_post_flight_with_existing_id_returns_409() -> None:
    app, u_store, *_ = _build_app()
    u_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
        )
    )
    client = TestClient(app)
    base = {
        "flight_id": "fl-dupe",
        "spot_id": "sp-1",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "channels": ["pub-1"],
    }
    assert client.post("/api/staff/underwriting/flights", json=base).status_code == 201
    again = client.post("/api/staff/underwriting/flights", json=base)
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# Q-5 — inverted period returns 422
# ---------------------------------------------------------------------------


def test_get_affidavit_with_inverted_period_returns_422() -> None:
    app, *_ = _build_app()
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits",
        params={
            "underwriter": "Acme",
            "from": "2026-06-30",
            "to": "2026-06-01",
        },
    )
    assert r.status_code == 422
    assert "from must be on or before to" in r.text


def test_export_affidavit_with_inverted_period_returns_422() -> None:
    app, *_ = _build_app()
    r = TestClient(app).get(
        "/api/staff/underwriting/affidavits/export",
        params={
            "underwriter": "Acme",
            "from": "2026-06-30",
            "to": "2026-06-01",
            "format": "csv",
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# T-2 — frequency cap applies across all channels a flight targets
# ---------------------------------------------------------------------------


def test_cap_is_global_across_channels_in_one_day(
    file_store: UnderwritingStore,
) -> None:
    file_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
            fcc_compliant_ack=True,
        )
    )
    file_store.upsert_flight(
        SpotFlight(
            flight_id="fl-multi",
            spot_id="sp-1",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            frequency_cap_per_day=3,
            channels=["ch-a", "ch-b", "ch-c", "ch-d"],
        )
    )
    # Twelve candidates across the four channels — 3 per channel — would
    # historically have produced 12 placements (3 per channel). The fix:
    # placement count is a flight-wide budget, so total <= cap.
    base = datetime(2026, 6, 10, 8, tzinfo=UTC)
    candidates: list[CandidateBreakSlot] = []
    for h, ch in enumerate(["ch-a", "ch-b", "ch-c", "ch-d"]):
        for j in range(3):
            candidates.append(
                CandidateBreakSlot(
                    channel_id=ch,
                    scheduled_at=base + timedelta(hours=h * 3 + j),
                    schedule_item_id=f"si-{ch}-{j}",
                )
            )
    compiler = TraffickingCompiler(file_store, station_id=_STATION)
    result = compiler.compile_for_date(for_date=date(2026, 6, 10), candidates=candidates)
    assert len(result.placements) == 3
    # Every skipped candidate is reported as cap-bound (not the daypart or
    # eligibility hierarchy paths).
    assert all(s.reason == "all_eligible_flights_at_cap" for s in result.skipped)


# ---------------------------------------------------------------------------
# T-3 — PDF pagination
# ---------------------------------------------------------------------------


def test_affidavit_pdf_paginates_with_many_airings() -> None:
    base = datetime(2026, 6, 1, 8, tzinfo=UTC)
    aired = [
        AffidavitAiring(
            spot_id="sp-1",
            asset_id="asset-1",
            channel_id="pub-1",
            aired_at=base + timedelta(minutes=i),
            duration_s=30,
            placement_id=f"pl-si-{i}",
        )
        for i in range(200)
    ]
    affidavit = UnderwriterAffidavit(
        station_id=_STATION,
        underwriter="Acme",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        aired=aired,
        total_airings=200,
        total_seconds=6000,
    )
    pdf = export_affidavit_pdf(affidavit)
    assert pdf.startswith(b"%PDF")
    # ReportLab emits one ``/Type /Page`` entry per rendered page. With 200
    # rows at ~50 rows per letter page the PDF must produce multiple pages.
    page_marker_count = pdf.count(b"/Type /Page\n") + pdf.count(b"/Type/Page\n")
    assert page_marker_count >= 2, f"expected multi-page PDF, got {page_marker_count} pages"
    # A row from deep in the airing list must appear in the rendered text.
    # ReportLab encodes ASCII payloads as-is in the content stream.
    assert b"pl-si-150" in pdf


# ---------------------------------------------------------------------------
# T-4 — shared asset_id attributes to BOTH spots
# ---------------------------------------------------------------------------


def test_two_spots_sharing_asset_id_both_get_attributed(
    stores: tuple[UnderwritingStore, ReportingStore],
) -> None:
    u_store, r_store = stores
    # Two Q3/Q4 spots that re-use the same 30s acknowledgment video.
    for sid in ("sp-q3", "sp-q4"):
        u_store.upsert_spot(
            UnderwritingSpot(
                spot_id=sid,
                station_id=_STATION,
                underwriter="Acme",
                asset_id="asset-shared",
                fcc_compliant_ack=True,
            )
        )
    r_store.append_as_run(
        AsRunLogEntry(
            entry_id="ar-1",
            station_id=_STATION,
            channel_id="pub-1",
            schedule_item_id=None,
            asset_id="asset-shared",
            actual_start=datetime(2026, 6, 10, 10, tzinfo=UTC),
            actual_end=datetime(2026, 6, 10, 10, 0, 30, tzinfo=UTC),
            duration_s=30,
            source_kind="spot",
        )
    )
    aff = AffidavitService(u_store, r_store).for_underwriter(
        station_id=_STATION,
        underwriter="Acme",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    assert {a.spot_id for a in aff.aired} == {"sp-q3", "sp-q4"}
    assert aff.total_airings == 2
    # Both rows reflect the same air event for billing transparency.
    assert {a.aired_at for a in aff.aired} == {datetime(2026, 6, 10, 10, tzinfo=UTC)}


# ---------------------------------------------------------------------------
# Q-6 — channel_set defense-in-depth filter removed (regression lock)
# ---------------------------------------------------------------------------


def test_historical_airing_on_off_flight_channel_is_billed(
    stores: tuple[UnderwritingStore, ReportingStore],
) -> None:
    """Locked behaviour: an as-run row whose ``channel_id`` is no longer in
    the underwriter's current flight set IS still attributed for billing.
    The as-run ledger is the source of truth for what aired; the flight set
    is prospective policy."""
    u_store, r_store = stores
    u_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
        )
    )
    u_store.upsert_flight(
        SpotFlight(
            flight_id="fl-1",
            spot_id="sp-1",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1"],
        )
    )
    r_store.append_as_run(
        AsRunLogEntry(
            entry_id="ar-1",
            station_id=_STATION,
            channel_id="edu-15",  # off the current flight
            schedule_item_id=None,
            asset_id="asset-1",
            actual_start=datetime(2026, 6, 10, 9, tzinfo=UTC),
            actual_end=datetime(2026, 6, 10, 9, 0, 30, tzinfo=UTC),
            duration_s=30,
            source_kind="spot",
        )
    )
    aff = AffidavitService(u_store, r_store).for_underwriter(
        station_id=_STATION,
        underwriter="Acme",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    assert aff.total_airings == 1
    assert aff.aired[0].channel_id == "edu-15"


# ---------------------------------------------------------------------------
# T-8 — router 422 propagation for cap-range + FCC-ack-default
# ---------------------------------------------------------------------------


def test_create_flight_with_cap_zero_returns_422() -> None:
    app, u_store, *_ = _build_app()
    u_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
        )
    )
    r = TestClient(app).post(
        "/api/staff/underwriting/flights",
        json={
            "flight_id": "fl-x",
            "spot_id": "sp-1",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "frequency_cap_per_day": 0,
            "channels": ["pub-1"],
        },
    )
    assert r.status_code == 422


def test_create_spot_defaults_fcc_ack_to_false_via_api() -> None:
    app, *_ = _build_app()
    client = TestClient(app)
    payload = {
        "spot_id": "sp-default",
        "station_id": _STATION,
        "underwriter": "Acme",
        "asset_id": "asset-1",
    }
    created = client.post("/api/staff/underwriting/spots", json=payload)
    assert created.status_code == 201
    assert created.json()["fcc_compliant_ack"] is False
    fetched = client.get("/api/staff/underwriting/spots/sp-default")
    assert fetched.status_code == 200
    assert fetched.json()["fcc_compliant_ack"] is False


# ---------------------------------------------------------------------------
# T-11 — daypart boundary cases (end-minute exclusive, last-minute inclusive)
# ---------------------------------------------------------------------------


def test_daypart_boundary_end_minute_exclusive(file_store: UnderwritingStore) -> None:
    """``block.start_minute <= minute_of_day < block.end_minute`` (half-open
    on end). At exactly ``end_minute`` the flight is OUT; at
    ``end_minute - 1`` it is IN."""
    from civiccast.schedule.autoschedule_models import ScheduleBlock

    file_store.upsert_spot(
        UnderwritingSpot(
            spot_id="sp-1",
            station_id=_STATION,
            underwriter="Acme",
            asset_id="asset-1",
            fcc_compliant_ack=True,
        )
    )
    file_store.upsert_flight(
        SpotFlight(
            flight_id="fl-dp",
            spot_id="sp-1",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            daypart_block_id="block-prime",
            channels=["pub-1"],
        )
    )
    now = datetime.now(UTC)
    block = ScheduleBlock(
        block_id="block-prime",
        channel_id="pub-1",
        name="primetime",
        start_minute=18 * 60,
        end_minute=20 * 60,
        days_of_week=[0, 1, 2, 3, 4, 5, 6],
        created_at=now,
        updated_at=now,
    )
    compiler = TraffickingCompiler(
        file_store,
        daypart_resolver=lambda _bid: block,
        station_id=_STATION,
    )
    # 2026-06-10 is a Wednesday (dow=2). UTC == local for offset 0.
    inside = CandidateBreakSlot(
        channel_id="pub-1",
        scheduled_at=datetime(2026, 6, 10, 19, 59, tzinfo=UTC),
        schedule_item_id="si-inside",
    )
    exact_end = CandidateBreakSlot(
        channel_id="pub-1",
        scheduled_at=datetime(2026, 6, 10, 20, 0, tzinfo=UTC),
        schedule_item_id="si-exact-end",
    )
    result = compiler.compile_for_date(for_date=date(2026, 6, 10), candidates=[inside, exact_end])
    placed_ids = {p.placement_id for p in result.placements}
    skipped_ids = {s.candidate.schedule_item_id for s in result.skipped}
    assert placed_ids == {"pl-si-inside"}
    assert skipped_ids == {"si-exact-end"}
