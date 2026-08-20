# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c EAS staff API — role gating, source CRUD, display + forced-slate guard, 503."""

from __future__ import annotations

import contextlib
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
from civiccast.eas.models import EasCapAlert, EasCapSource
from civiccast.eas.router import get_eas_service, get_eas_store, staff_router
from civiccast.eas.service import EasDisplayService
from civiccast.eas.store import EasStore

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


_ENGINES_TO_DISPOSE: list = []


@pytest.fixture(autouse=True)
def _dispose_test_engines() -> Iterator[None]:
    """Dispose throwaway SQLite engines at each test's end.

    Each _build() call traps a fresh engine in a closure; undisposed, its
    sqlite3.Connection lingers until GC finalizes it at an arbitrary later
    point, raising an "Exception ignored in" unraisable that the
    filterwarnings=error policy turns into a failure pinned to a random
    unrelated test. Disposing here closes them deterministically.
    """
    yield
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


def _build(scopes: tuple[str, ...] | None = ("setup_admin",), *, wire: bool = True):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _ENGINES_TO_DISPOSE.append(engine)
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()

    @contextmanager
    def factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    store = EasStore(factory)
    service = EasDisplayService(store, clock=lambda: _T0)
    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    if wire:
        app.dependency_overrides[get_eas_store] = lambda: store
        app.dependency_overrides[get_eas_service] = lambda: service
    return app, store


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _ingest_alert(store: EasStore, alert_id: str = "a1", *, severity: str = "extreme") -> None:
    store.ingest_alert(
        EasCapAlert(
            alert_id=alert_id,
            source_id="src",
            sender="snd",
            identifier=alert_id,
            sent=_T0,
            msg_type="alert",
            event="Tornado Warning",
            severity=severity,  # type: ignore[arg-type]
            expires=_T0 + timedelta(hours=1),
        )
    )


_SOURCE_BODY = {
    "source_id": "src_nws",
    "label": "NWS",
    "kind": "nws-cap",
    "endpoint_url": "https://api.weather.gov/alerts/active",
    "severity_floor": "severe",
}


# --- role gate ---------------------------------------------------------------


def test_source_read_forbidden_for_records_clerk() -> None:
    assert _client(scopes=("records_clerk",)).get("/api/staff/eas/sources").status_code == 403


def test_no_identity_is_unauthorized() -> None:
    assert _client(scopes=None).get("/api/staff/eas/sources").status_code == 401


def test_source_write_forbidden_for_meeting_operator() -> None:
    r = _client(scopes=("meeting_operator",)).put(
        "/api/staff/eas/sources/src_nws", json=_SOURCE_BODY
    )
    assert r.status_code == 403


def test_read_allowed_for_support_admin() -> None:
    assert _client(scopes=("support_admin",)).get("/api/staff/eas/sources").status_code == 200


# --- source CRUD -------------------------------------------------------------


def test_source_upsert_list_delete() -> None:
    client = _client()
    assert client.put("/api/staff/eas/sources/src_nws", json=_SOURCE_BODY).status_code == 200
    listed = client.get("/api/staff/eas/sources").json()
    assert [s["source_id"] for s in listed] == ["src_nws"]
    assert client.delete("/api/staff/eas/sources/src_nws").status_code == 204
    assert client.get("/api/staff/eas/sources").json() == []


def test_source_id_mismatch_rejected() -> None:
    assert _client().put("/api/staff/eas/sources/other", json=_SOURCE_BODY).status_code == 400


# --- display + forced-slate guard --------------------------------------------


def test_display_alert_creates_decision() -> None:
    app, store = _build(scopes=("meeting_operator",))
    _ingest_alert(store)
    client = TestClient(app)
    r = client.post("/api/staff/eas/alerts/a1/display", json={"channel_id": "gov", "mode": "crawl"})
    assert r.status_code == 200
    assert r.json()["eas_claim"] == "not_eas"
    assert r.json()["state"] == "displayed"


def test_display_unknown_alert_404() -> None:
    app, _ = _build(scopes=("meeting_operator",))
    r = TestClient(app).post(
        "/api/staff/eas/alerts/missing/display", json={"channel_id": "gov", "mode": "crawl"}
    )
    assert r.status_code == 404


def test_forced_slate_without_confirmation_409() -> None:
    app, store = _build(scopes=("meeting_operator",))
    _ingest_alert(store)
    client = TestClient(app)
    r = client.post(
        "/api/staff/eas/alerts/a1/display",
        json={"channel_id": "gov", "mode": "forced_slate", "operator_confirmed": False},
    )
    assert r.status_code == 409
    # confirmed → allowed
    ok = client.post(
        "/api/staff/eas/alerts/a1/display",
        json={"channel_id": "gov", "mode": "forced_slate", "operator_confirmed": True},
    )
    assert ok.status_code == 200
    assert ok.json()["mode"] == "forced_slate"


def _manual_source(store: EasStore) -> None:
    store.upsert_source(EasCapSource(source_id="manual", label="Operator manual", kind="manual"))


_MANUAL_BODY = {
    "source_id": "manual",
    "identifier": "M-1",
    "event": "Boil Water Notice",
    "severity": "severe",
    "instruction": "Boil water before use.",
}


def test_manual_alert_creation() -> None:
    app, store = _build(scopes=("setup_admin",))
    _manual_source(store)
    r = TestClient(app).post("/api/staff/eas/alerts/manual", json=_MANUAL_BODY)
    assert r.status_code == 201
    assert r.json()["event"] == "Boil Water Notice"
    assert len(store.list_alerts()) == 1


def test_manual_alert_unknown_source_404() -> None:
    app, _ = _build(scopes=("setup_admin",))
    r = TestClient(app).post("/api/staff/eas/alerts/manual", json=_MANUAL_BODY)
    assert r.status_code == 404  # no 'manual' source configured


def test_manual_alert_rejects_non_manual_source() -> None:
    # provenance guard: cannot attribute a manual alert to a live feed's id
    app, store = _build(scopes=("setup_admin",))
    store.upsert_source(
        EasCapSource(
            source_id="src_nws",
            label="NWS",
            kind="nws-cap",
            endpoint_url="https://api.weather.gov/alerts/active",
        )
    )
    body = {**_MANUAL_BODY, "source_id": "src_nws"}
    r = TestClient(app).post("/api/staff/eas/alerts/manual", json=body)
    assert r.status_code == 400


# --- unwired (503) -----------------------------------------------------------


def test_list_sources_503_when_unwired() -> None:
    assert _client(wire=False).get("/api/staff/eas/sources").status_code == 503
