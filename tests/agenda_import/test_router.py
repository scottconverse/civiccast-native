# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API-surface tests for the agenda-import routes (plan §6).

Mirrors ``tests/agenda/test_router.py``'s pattern: a minimal FastAPI app
mounts the real router, installs an operator-identity middleware, and
overrides the DI seams. No live network -- ``LegistarSource`` is swapped out
via monkeypatching :func:`civiccast.agenda_import.registry.build_source`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.agenda.models import MeetingAgenda
from civiccast.agenda.router import get_agenda_store
from civiccast.agenda.store import AgendaItemOrderConflictError, AgendaStore
from civiccast.agenda_import import router as agenda_import_router
from civiccast.agenda_import.base import (
    AgendaSourceAuthRequiredError,
    AgendaSourceNotAvailableError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.config import AgendaImportSettings
from civiccast.agenda_import.models import (
    ExternalAgenda,
    ExternalAgendaItem,
    ExternalMeetingSummary,
)
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base

_AUTHOR_SCOPES = ("records_clerk", "meeting_operator")


class _StubSource:
    def __init__(self, *, meetings=None, agenda=None, error: Exception | None = None):
        self._meetings = meetings or []
        self._agenda = agenda
        self._error = error

    def fetch_meetings(self, client_code, *, since=None):
        if self._error:
            raise self._error
        return self._meetings

    def fetch_agenda(self, client_code, event_id):
        if self._error:
            raise self._error
        assert self._agenda is not None
        return self._agenda


def _build(
    *,
    scopes: tuple[str, ...] | None = _AUTHOR_SCOPES,
    wire_store: bool = True,
    settings: AgendaImportSettings | None = None,
    source: _StubSource | None = None,
) -> tuple[FastAPI, AgendaStore]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    store = AgendaStore(factory)

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

    app.include_router(agenda_import_router.router)
    if wire_store:
        app.dependency_overrides[get_agenda_store] = lambda: store
    resolved_settings = settings or AgendaImportSettings(source="legistar", timeout_seconds=10.0)
    app.dependency_overrides[agenda_import_router.get_agenda_import_settings] = lambda: (
        resolved_settings
    )
    if source is not None:

        def _fake_build_source(name, *, timeout_seconds, token):
            return source

        app.dependency_overrides[get_agenda_store] = lambda: store
        agenda_import_router.build_source = _fake_build_source  # type: ignore[assignment]
    return app, store


@pytest.fixture(autouse=True)
def _restore_build_source():
    original = agenda_import_router.build_source
    yield
    agenda_import_router.build_source = original


def _seed_agenda(store: AgendaStore, agenda_id: str = "ag-1") -> None:
    store.upsert_agenda(
        MeetingAgenda(agenda_id=agenda_id, station_id="civiccast-station", meeting_asset_id="m-1")
    )


class TestDisabledByDefault:
    def test_off_source_returns_404_on_import(self) -> None:
        app, store = _build(settings=AgendaImportSettings(source="off"))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )

        assert resp.status_code == 404
        assert "CIVICCAST_AGENDA_SOURCE" in resp.json()["detail"]

    def test_off_source_returns_404_on_discover(self) -> None:
        app, _store = _build(settings=AgendaImportSettings(source="off"))
        client = TestClient(app)

        resp = client.get("/api/staff/agenda-sources/legistar/seattle/meetings")

        assert resp.status_code == 404


class TestRoleGating:
    def test_no_identity_is_401(self) -> None:
        app, store = _build(scopes=None)
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )
        assert resp.status_code == 401

    def test_wrong_scope_is_403(self) -> None:
        app, store = _build(scopes=("support_admin",))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )
        assert resp.status_code == 403


class TestImportExternal:
    def test_successful_import_returns_items(self) -> None:
        agenda = ExternalAgenda(
            external_id="5705",
            title="City Council — 2024-01-09",
            items=[ExternalAgendaItem(order=1, title="CALL TO ORDER", number="A.")],
        )
        app, store = _build(source=_StubSource(agenda=agenda))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "CALL TO ORDER"
        assert store.get_agenda("ag-1").status == "draft"  # type: ignore[union-attr]

    def test_agenda_not_found_is_404(self) -> None:
        agenda = ExternalAgenda(external_id="5705", title="x", items=[])
        app, _store = _build(source=_StubSource(agenda=agenda))
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/does-not-exist/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )
        assert resp.status_code == 404

    def test_source_not_available_is_422(self) -> None:
        app, store = _build(source=_StubSource(error=AgendaSourceNotAvailableError("nope")))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "primegov", "client_code": "longmont", "event_id": "1"},
        )
        assert resp.status_code == 422

    def test_auth_required_is_502_with_actionable_message(self) -> None:
        app, store = _build(
            source=_StubSource(
                error=AgendaSourceAuthRequiredError(
                    "Legistar tenant 'nyc' requires an API token (HTTP 403)."
                )
            )
        )
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "nyc", "event_id": "1"},
        )
        assert resp.status_code == 502
        assert "token" in resp.json()["detail"].lower()

    def test_upstream_error_is_502(self) -> None:
        app, store = _build(source=_StubSource(error=AgendaSourceUpstreamError("upstream boom")))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "1"},
        )
        assert resp.status_code == 502

    def test_hostile_doc_url_is_502(self) -> None:
        agenda = ExternalAgenda(
            external_id="5705",
            title="x",
            items=[ExternalAgendaItem(order=1, title="Hostile", doc_url="javascript:alert(1)")],
        )
        app, store = _build(source=_StubSource(agenda=agenda))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )
        assert resp.status_code == 502
        assert store.list_items("ag-1") == []

    def test_order_conflict_from_the_mapper_write_is_409(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A write collision (another request took the same (agenda_id,
        # order) between the mapper's existing_orders read and its
        # store.upsert_item call) must surface as a controlled 409, same as
        # civiccast/agenda/router.py's own item-write endpoint -- not an
        # unhandled 500.
        agenda = ExternalAgenda(
            external_id="5705",
            title="x",
            items=[ExternalAgendaItem(order=1, title="CALL TO ORDER")],
        )
        app, store = _build(source=_StubSource(agenda=agenda))
        _seed_agenda(store)
        client = TestClient(app)

        def _raise_conflict(*_args, **_kwargs):
            raise AgendaItemOrderConflictError(
                "Another agenda item already occupies (agenda_id='ag-1', order=1)."
            )

        monkeypatch.setattr(agenda_import_router, "import_external_agenda", _raise_conflict)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )
        assert resp.status_code == 409

    def test_provenance_write_race_does_not_fail_an_already_successful_import(
        self,
    ) -> None:
        # A concurrent import for the same agenda_id races on the
        # provenance table's primary key (provenance.py record_import) and
        # raises IntegrityError -- bookkeeping only, must never turn an
        # already-committed import into a reported failure.
        class _RacingProvenanceStore:
            def record_import(self, **_kwargs: object) -> None:
                raise IntegrityError("INSERT INTO agenda_import_provenance ...", {}, Exception())

        agenda = ExternalAgenda(
            external_id="5705",
            title="x",
            items=[ExternalAgendaItem(order=1, title="CALL TO ORDER")],
        )
        app, store = _build(source=_StubSource(agenda=agenda))
        _seed_agenda(store)
        app.dependency_overrides[agenda_import_router.get_agenda_import_provenance_store] = lambda: (
            _RacingProvenanceStore()
        )
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "5705"},
        )

        assert resp.status_code == 200
        assert resp.json()[0]["title"] == "CALL TO ORDER"
        assert len(store.list_items("ag-1")) == 1

    def test_store_not_wired_is_503(self) -> None:
        app, _store = _build(wire_store=False)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={"source": "legistar", "client_code": "seattle", "event_id": "1"},
        )
        assert resp.status_code == 503


class TestDiscoverMeetings:
    def test_returns_summaries(self) -> None:
        summary = ExternalMeetingSummary(external_id="5705", title="City Council")
        app, _store = _build(source=_StubSource(meetings=[summary]))
        client = TestClient(app)

        resp = client.get("/api/staff/agenda-sources/legistar/seattle/meetings")

        assert resp.status_code == 200
        assert resp.json() == [
            {"external_id": "5705", "title": "City Council", "meeting_datetime": None}
        ]

    def test_accepts_since_query_param(self) -> None:
        app, _store = _build(source=_StubSource(meetings=[]))
        client = TestClient(app)

        resp = client.get(
            "/api/staff/agenda-sources/legistar/seattle/meetings",
            params={"since": date(2026, 1, 1).isoformat()},
        )
        assert resp.status_code == 200

    def test_unavailable_source_is_422(self) -> None:
        app, _store = _build(source=_StubSource(error=AgendaSourceNotAvailableError("nope")))
        client = TestClient(app)

        resp = client.get("/api/staff/agenda-sources/primegov/longmont/meetings")
        assert resp.status_code == 422


class TestClientCodeSsrfGuard:
    """SEC-1: client_code is spliced straight into the outbound request host
    (``https://{client_code}.primegov.com``), so a hostile value must be
    rejected at the trust boundary (422) before it ever reaches build_source or
    an httpx client. The stub source + seeded agenda would return 200/[] if the
    guard failed, so a 422 is attributable to the validator alone.
    """

    def test_import_external_rejects_ssrf_client_code(self) -> None:
        agenda = ExternalAgenda(external_id="5705", title="x", items=[])
        app, store = _build(source=_StubSource(agenda=agenda))
        _seed_agenda(store)
        client = TestClient(app)

        resp = client.post(
            "/api/staff/agenda/ag-1/import-external",
            json={
                "source": "primegov",
                "client_code": "169.254.169.254/latest/meta-data/#",
                "event_id": "5705",
            },
        )
        assert resp.status_code == 422

    def test_discover_meetings_rejects_ssrf_client_code(self) -> None:
        app, _store = _build(source=_StubSource(meetings=[]))
        client = TestClient(app)

        # '@' would inject userinfo/host into the spliced URL; %40 decodes to it.
        resp = client.get("/api/staff/agenda-sources/primegov/evil%40host/meetings")
        assert resp.status_code == 422

    def test_valid_client_code_is_accepted(self) -> None:
        app, _store = _build(source=_StubSource(meetings=[]))
        client = TestClient(app)

        resp = client.get("/api/staff/agenda-sources/primegov/longmont/meetings")
        assert resp.status_code == 200
