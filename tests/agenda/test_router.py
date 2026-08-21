# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S25 meeting-agenda API: role gating, 503 unwired, CRUD, publish gate, sync, import, public read.

A minimal FastAPI app mounts the real agenda staff + public routers, installs
an operator-identity middleware (so ``require_any_role`` runs), and overrides
the DI seams with a SQLite-backed ``AgendaStore`` + ``AgendaService``. Covers:

* 503 when either DI seam (store, service) is unwired;
* role gating on every staff route (``records_clerk`` / ``meeting_operator``
  author; 401 without identity; 403 for wrong scope; public endpoint has no
  role gate);
* agenda CRUD round-trip + 404 / 409;
* item CRUD round-trip + 404 / 409;
* PATCH ``status="published"`` empty-agenda → 422 (publish gate);
* PATCH ``status="published"`` with items → 200 + published;
* sync-from-chapters seeds items through a DI-mocked chapter provider;
* import: ``text/plain`` parses; ``application/pdf`` parses via the heuristic
  extractor (confidence-scored, reopens a published agenda to draft); an
  unreadable PDF → 422; any other content type → 415;
* public GET: draft → 404; published → 200 with the PublicMeetingAgenda
  shape (no ``status`` / ``station_id`` / timestamps / per-item ``notes``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from io import BytesIO

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.agenda.router import (
    get_agenda_service,
    get_agenda_store,
    public_router,
    staff_router,
)
from civiccast.agenda.service import AgendaService
from civiccast.agenda.store import AgendaStore
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.schedule.models import Chapter

_STATION = "civiccast-station"
_AUTHOR_SCOPES = ("records_clerk", "meeting_operator")


def _build(
    *,
    scopes: tuple[str, ...] | None = _AUTHOR_SCOPES,
    wire_store: bool = True,
    wire_service: bool = True,
    chapter_provider: Callable[[str], list[Chapter]] | None = None,
) -> tuple[FastAPI, AgendaStore, AgendaService]:
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

    store = AgendaStore(factory)
    service = AgendaService(store, asset_chapter_provider=chapter_provider)

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
    if wire_store:
        app.dependency_overrides[get_agenda_store] = lambda: store
    if wire_service:
        app.dependency_overrides[get_agenda_service] = lambda: service
    return app, store, service


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _write_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()
    return buffer.getvalue()


def _agenda_payload(agenda_id: str = "ag-jan-2026", **overrides) -> dict:
    body = {
        "agenda_id": agenda_id,
        "station_id": _STATION,
        "meeting_asset_id": "meeting-jan-2026",
    }
    body.update(overrides)
    return body


def _item_payload(
    item_id: str = "it-1",
    agenda_id: str = "ag-jan-2026",
    order: int = 0,
    **overrides,
) -> dict:
    body = {
        "item_id": item_id,
        "agenda_id": agenda_id,
        "order": order,
        "title": "Roll call",
    }
    body.update(overrides)
    return body


# --- 503 when unwired --------------------------------------------------------


def test_503_when_store_unwired() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).get("/api/staff/agendas")
    assert r.status_code == 503
    assert "not ready" in r.text


def test_503_when_service_unwired_on_public_view() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).get("/api/public/agendas/meeting-x")
    assert r.status_code == 503


def test_503_when_service_unwired_on_sync() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).post("/api/staff/agendas/ag-jan-2026/sync-from-chapters")
    assert r.status_code == 503


def test_503_when_service_unwired_on_import() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=b"1 Roll call",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 503


# --- role gating: staff routes ----------------------------------------------


def test_list_agendas_requires_author_role() -> None:
    assert _client(scopes=None).get("/api/staff/agendas").status_code == 401
    # support_admin / publish_operator are NOT authors here
    assert _client(scopes=("support_admin",)).get("/api/staff/agendas").status_code == 403
    assert _client(scopes=("publish_operator",)).get("/api/staff/agendas").status_code == 403
    assert _client(scopes=("records_clerk",)).get("/api/staff/agendas").status_code == 200
    assert _client(scopes=("meeting_operator",)).get("/api/staff/agendas").status_code == 200


def test_create_agenda_requires_author_role() -> None:
    r = _client(scopes=("publish_operator",)).post("/api/staff/agendas", json=_agenda_payload())
    assert r.status_code == 403
    r = _client(scopes=("records_clerk",)).post("/api/staff/agendas", json=_agenda_payload())
    assert r.status_code == 201
    assert r.json()["agenda_id"] == "ag-jan-2026"
    assert r.json()["status"] == "draft"


def test_patch_agenda_requires_author_role() -> None:
    # seed
    auth_client = _client()
    auth_client.post("/api/staff/agendas", json=_agenda_payload())
    # wrong role
    r = _client(scopes=("publish_operator",)).patch(
        "/api/staff/agendas/ag-jan-2026", json={"source_doc_url": "https://x"}
    )
    assert r.status_code == 403


def test_delete_agenda_requires_author_role() -> None:
    r = _client(scopes=("publish_operator",)).delete("/api/staff/agendas/ag-jan-2026")
    assert r.status_code == 403


def test_create_item_requires_author_role() -> None:
    r = _client(scopes=("publish_operator",)).post(
        "/api/staff/agendas/ag-jan-2026/items", json=_item_payload()
    )
    assert r.status_code == 403


def test_sync_from_chapters_requires_author_role() -> None:
    r = _client(scopes=("publish_operator",)).post(
        "/api/staff/agendas/ag-jan-2026/sync-from-chapters"
    )
    assert r.status_code == 403


def test_import_requires_author_role() -> None:
    r = _client(scopes=("publish_operator",)).post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=b"1 Roll call",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 403


def test_public_get_requires_no_auth() -> None:
    # No identity — public endpoint must not gate on it. Empty store → 404, NOT 401.
    r = _client(scopes=None).get("/api/public/agendas/meeting-x")
    assert r.status_code == 404


# --- agenda CRUD round-trip --------------------------------------------------


def test_agenda_round_trip_create_get_patch_delete() -> None:
    app, store, _ = _build()
    client = TestClient(app)

    r = client.post("/api/staff/agendas", json=_agenda_payload())
    assert r.status_code == 201

    r = client.get("/api/staff/agendas/ag-jan-2026")
    assert r.status_code == 200
    assert r.json()["meeting_asset_id"] == "meeting-jan-2026"

    r = client.patch(
        "/api/staff/agendas/ag-jan-2026",
        json={"source_doc_url": "https://example.com/agenda.pdf"},
    )
    assert r.status_code == 200
    assert r.json()["source_doc_url"] == "https://example.com/agenda.pdf"

    # Explicit null clears the field.
    r = client.patch("/api/staff/agendas/ag-jan-2026", json={"source_doc_url": None})
    assert r.status_code == 200
    assert r.json()["source_doc_url"] is None

    r = client.delete("/api/staff/agendas/ag-jan-2026")
    assert r.status_code == 204
    assert store.get_agenda("ag-jan-2026") is None


def test_list_agendas_status_filter() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload("ag-a"))
    client.post(
        "/api/staff/agendas",
        json=_agenda_payload("ag-b", meeting_asset_id="meeting-b"),
    )
    r = client.get("/api/staff/agendas", params={"status": "draft"})
    assert r.status_code == 200
    assert {a["agenda_id"] for a in r.json()} == {"ag-a", "ag-b"}

    r = client.get("/api/staff/agendas", params={"status": "published"})
    assert r.status_code == 200
    assert r.json() == []


def test_get_missing_agenda_returns_404() -> None:
    r = _client().get("/api/staff/agendas/no-such")
    assert r.status_code == 404


def test_patch_missing_agenda_returns_404() -> None:
    r = _client().patch(
        "/api/staff/agendas/no-such",
        json={"source_doc_url": "https://example.com/a.pdf"},
    )
    assert r.status_code == 404


def test_delete_missing_agenda_returns_404() -> None:
    r = _client().delete("/api/staff/agendas/no-such")
    assert r.status_code == 404


def test_create_agenda_duplicate_returns_409() -> None:
    client = TestClient(_build()[0])
    assert client.post("/api/staff/agendas", json=_agenda_payload()).status_code == 201
    r = client.post("/api/staff/agendas", json=_agenda_payload())
    assert r.status_code == 409
    assert "already exists" in r.text


def test_delete_agenda_cascades_items() -> None:
    app, store, _ = _build()
    client = TestClient(app)
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("it-2", order=1, title="Approve minutes"),
    )
    assert len(store.list_items("ag-jan-2026")) == 2
    r = client.delete("/api/staff/agendas/ag-jan-2026")
    assert r.status_code == 204
    assert store.list_items("ag-jan-2026") == []


# --- item CRUD --------------------------------------------------------------


def test_item_round_trip_create_list_patch_delete() -> None:
    app, _, _ = _build()
    client = TestClient(app)
    client.post("/api/staff/agendas", json=_agenda_payload())

    r = client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    assert r.status_code == 201
    assert r.json()["title"] == "Roll call"

    r = client.get("/api/staff/agendas/ag-jan-2026/items")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.patch(
        "/api/staff/agendas/ag-jan-2026/items/it-1",
        json={"video_timecode_s": 90, "title": "Call to order"},
    )
    assert r.status_code == 200
    assert r.json()["video_timecode_s"] == 90
    assert r.json()["title"] == "Call to order"

    r = client.delete("/api/staff/agendas/ag-jan-2026/items/it-1")
    assert r.status_code == 204
    assert client.get("/api/staff/agendas/ag-jan-2026/items").json() == []


def test_list_items_order_by_timecode() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("a", order=0, title="A", video_timecode_s=600),
    )
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("b", order=1, title="B", video_timecode_s=120),
    )
    r = client.get("/api/staff/agendas/ag-jan-2026/items", params={"order_by": "timecode"})
    assert r.status_code == 200
    ids = [it["item_id"] for it in r.json()]
    assert ids == ["b", "a"]


def test_list_items_order_by_invalid_returns_422() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.get("/api/staff/agendas/ag-jan-2026/items", params={"order_by": "nope"})
    assert r.status_code == 422


def test_list_items_missing_agenda_returns_404() -> None:
    r = _client().get("/api/staff/agendas/no-such/items")
    assert r.status_code == 404


def test_create_item_under_missing_agenda_returns_404() -> None:
    r = _client().post("/api/staff/agendas/no-such/items", json=_item_payload())
    assert r.status_code == 404


def test_create_item_duplicate_returns_409() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    assert (
        client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload()).status_code == 201
    )
    r = client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    assert r.status_code == 409


def test_create_item_path_body_agenda_mismatch_returns_422() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload("ag-a"))
    client.post("/api/staff/agendas", json=_agenda_payload("ag-b", meeting_asset_id="b"))
    # body's agenda_id targets ag-b but path is ag-a
    r = client.post(
        "/api/staff/agendas/ag-a/items",
        json=_item_payload("i-1", agenda_id="ag-b"),
    )
    assert r.status_code == 422


def test_patch_missing_item_returns_404() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.patch("/api/staff/agendas/ag-jan-2026/items/no-such", json={"title": "X"})
    assert r.status_code == 404


def test_delete_missing_item_returns_404() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.delete("/api/staff/agendas/ag-jan-2026/items/no-such")
    assert r.status_code == 404


# --- publish gate via PATCH status ------------------------------------------


def test_patch_status_published_empty_agenda_returns_422() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "published"})
    assert r.status_code == 422
    assert "zero items" in r.text


def test_patch_status_published_with_items_succeeds() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload(video_timecode_s=10),
    )
    r = client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "published"})
    assert r.status_code == 200
    assert r.json()["status"] == "published"


def test_patch_status_unpublish_succeeds() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "published"})
    r = client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "draft"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_patch_status_and_source_doc_url_together() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    r = client.patch(
        "/api/staff/agendas/ag-jan-2026",
        json={"status": "published", "source_doc_url": "https://example.com/a.pdf"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "published"
    assert r.json()["source_doc_url"] == "https://example.com/a.pdf"


# --- sync-from-chapters -----------------------------------------------------


def test_sync_from_chapters_seeds_items() -> None:
    def provider(meeting_asset_id: str) -> list[Chapter]:
        assert meeting_asset_id == "meeting-jan-2026"
        return [
            Chapter(t=0.0, name="Call to order"),
            Chapter(t=120.0, name="Roll call"),
            Chapter(t=360.0, name="New business"),
        ]

    app, _, _ = _build(chapter_provider=provider)
    client = TestClient(app)
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.post("/api/staff/agendas/ag-jan-2026/sync-from-chapters")
    assert r.status_code == 200
    body = r.json()
    assert [it["title"] for it in body] == ["Call to order", "Roll call", "New business"]
    assert [it["video_timecode_s"] for it in body] == [0, 120, 360]


def test_sync_from_chapters_missing_agenda_returns_404() -> None:
    app, _, _ = _build(chapter_provider=lambda _: [])
    client = TestClient(app)
    r = client.post("/api/staff/agendas/no-such/sync-from-chapters")
    assert r.status_code == 404


def test_sync_from_chapters_no_provider_returns_500() -> None:
    # No chapter provider wired — the service raises AgendaServiceError →
    # 500 (it's an unwired-provider config error, not a 4xx user mistake).
    app, _, _ = _build(chapter_provider=None)
    client = TestClient(app)
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.post("/api/staff/agendas/ag-jan-2026/sync-from-chapters")
    assert r.status_code == 500


# --- import -----------------------------------------------------------------


def test_import_text_plain_parses() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    body = b"1 Call to order\n2 Roll call\n3.a New business"
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=body,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3
    assert items[0]["number"] == "1"
    assert items[0]["title"] == "Call to order"
    assert items[2]["number"] == "3.a"
    assert items[2]["title"] == "New business"


def test_import_docx_returns_415() -> None:
    # Any content type other than text/plain / application/pdf is 415.
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=b"PK\x03\x04...",
        headers={
            "content-type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        },
    )
    assert r.status_code == 415


def test_import_unreadable_pdf_returns_422() -> None:
    # Content type IS supported, but the bytes aren't a real PDF -- 422
    # (distinct from the 415 "wrong format" cases), never a silent empty
    # import or a raw 500.
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=b"%PDF-1.4...",
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 422


def test_import_recognized_pdf_returns_200_with_confidence() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    pdf_bytes = _write_pdf(["1. Call to order", "2. Roll call"])
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=pdf_bytes,
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 200
    items = r.json()
    assert [i["title"] for i in items] == ["Call to order", "Roll call"]
    assert all(i["confidence"] == pytest.approx(0.95) for i in items)


def test_import_pdf_into_published_agenda_reopens_to_draft() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    # Seeded at a non-zero order so it doesn't collide with the PDF item's
    # order=0 under the skip-by-order idempotency rule.
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload(item_id="seed-5", order=5, title="Seed"),
    )
    published = client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "published"})
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    pdf_bytes = _write_pdf(["1. New item"])
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=pdf_bytes,
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 200

    refreshed = client.get("/api/staff/agendas/ag-jan-2026")
    assert refreshed.json()["status"] == "draft"


def test_import_missing_agenda_returns_404() -> None:
    r = _client().post(
        "/api/staff/agendas/no-such/import",
        content=b"1 X",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 404


# --- public GET --------------------------------------------------------------


def test_public_get_draft_returns_404() -> None:
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post("/api/staff/agendas/ag-jan-2026/items", json=_item_payload())
    # Agenda is still a draft — public endpoint must hide it (DC-6).
    r = client.get("/api/public/agendas/meeting-jan-2026")
    assert r.status_code == 404


def test_public_get_missing_returns_404() -> None:
    r = _client().get("/api/public/agendas/no-such-meeting")
    assert r.status_code == 404


def test_public_get_published_returns_public_shape() -> None:
    client = TestClient(_build()[0])
    client.post(
        "/api/staff/agendas",
        json=_agenda_payload(source_doc_url="https://example.com/a.pdf"),
    )
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("i-1", order=0, title="Call to order", video_timecode_s=0),
    )
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload(
            "i-2",
            order=1,
            title="Roll call",
            video_timecode_s=120,
            notes="operator-only note",
        ),
    )
    r = client.patch("/api/staff/agendas/ag-jan-2026", json={"status": "published"})
    assert r.status_code == 200

    r = client.get("/api/public/agendas/meeting-jan-2026")
    assert r.status_code == 200
    body = r.json()
    # Public shape: agenda_id + meeting_asset_id + source_doc_url + items.
    # NO status / station_id / timestamps.
    assert set(body.keys()) == {
        "agenda_id",
        "meeting_asset_id",
        "source_doc_url",
        "items",
    }
    assert body["agenda_id"] == "ag-jan-2026"
    assert body["meeting_asset_id"] == "meeting-jan-2026"
    assert body["source_doc_url"] == "https://example.com/a.pdf"
    assert len(body["items"]) == 2
    # Public items strip ``notes`` + timestamps.
    item_keys = set(body["items"][0].keys())
    assert "notes" not in item_keys
    assert "created_at" not in item_keys
    assert "updated_at" not in item_keys
    assert item_keys == {
        "item_id",
        "order",
        "number",
        "title",
        "video_timecode_s",
        "doc_anchor",
    }
    # The notes field on i-2 must not leak.
    assert "operator-only note" not in r.text


# --- OpenAPI x-required-roles mirror ----------------------------------------


def test_openapi_carries_x_required_roles_on_staff_routes() -> None:
    app, *_ = _build()
    schema = app.openapi()
    extra = schema["paths"]["/api/staff/agendas"]["get"]
    assert extra.get("x-required-roles") == list(_AUTHOR_SCOPES)
    # Public endpoint has no role gate — must NOT carry the marker.
    public_op = schema["paths"]["/api/public/agendas/{meeting_asset_id}"]["get"]
    assert "x-required-roles" not in public_op


# --- E-1 / Q-3 — source_doc_url scheme allowlist on the wire ---------------

_BAD_URLS = (
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
)


def test_post_agenda_rejects_javascript_and_data_urls() -> None:
    """A stored-XSS payload in ``source_doc_url`` must 422 at the API
    boundary — the public portal renders this value as an ``<a href>`` so
    accepting it would leak the attack to every viewer (E-1 / Q-3)."""
    client = TestClient(_build()[0])
    for bad in _BAD_URLS:
        r = client.post("/api/staff/agendas", json=_agenda_payload(source_doc_url=bad))
        assert r.status_code == 422, f"expected 422 for {bad!r}, got {r.status_code}"


def test_patch_agenda_rejects_javascript_and_data_urls() -> None:
    """PATCH must also enforce the allowlist — an operator with stolen
    credentials would otherwise tamper with an existing row."""
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    for bad in _BAD_URLS:
        r = client.patch("/api/staff/agendas/ag-jan-2026", json={"source_doc_url": bad})
        assert r.status_code == 422, f"expected 422 for {bad!r}, got {r.status_code}"


def test_post_agenda_empty_source_doc_url_coerced_to_none() -> None:
    """E-4 — ``source_doc_url=""`` is treated as "no link", not stored as
    an empty string the portal would render as an empty href."""
    client = TestClient(_build()[0])
    r = client.post("/api/staff/agendas", json=_agenda_payload(source_doc_url=""))
    assert r.status_code == 201
    assert r.json()["source_doc_url"] is None


# --- E-2 / Q-2 / T-1 — (agenda_id, order) conflict → 409, never 500 --------


def test_create_item_duplicate_order_returns_409_not_500() -> None:
    """Two distinct item_ids at the same (agenda_id, order) used to bubble
    a raw ``IntegrityError`` to a 500. The store now raises a typed
    ``AgendaItemOrderConflictError`` and the router translates it to 409."""
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    a = client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("it-a", order=5, title="A"),
    )
    assert a.status_code == 201
    b = client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("it-b", order=5, title="B"),
    )
    assert b.status_code == 409
    assert "order=5" in b.text
    assert "ag-jan-2026" in b.text


def test_patch_item_to_duplicate_order_returns_409_not_500() -> None:
    """A PATCH that moves item B onto item A's order must 409 — the
    operator dragging-and-dropping into an occupied slot sees a controlled
    conflict, not a raw 500."""
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("it-a", order=0, title="A"),
    )
    client.post(
        "/api/staff/agendas/ag-jan-2026/items",
        json=_item_payload("it-b", order=1, title="B"),
    )
    r = client.patch("/api/staff/agendas/ag-jan-2026/items/it-b", json={"order": 0})
    assert r.status_code == 409
    assert "order=0" in r.text


def test_create_agenda_duplicate_station_asset_returns_409_not_500() -> None:
    """Two distinct agenda_ids at the same (station_id, meeting_asset_id)
    collide on the unique constraint — that must be a 409 (E-2 follow-up),
    not a raw 500."""
    client = TestClient(_build()[0])
    a = client.post("/api/staff/agendas", json=_agenda_payload("ag-a"))
    assert a.status_code == 201
    # Same station + meeting_asset_id, different agenda_id.
    b = client.post("/api/staff/agendas", json=_agenda_payload("ag-b"))
    assert b.status_code == 409
    assert "meeting-jan-2026" in b.text


# --- E-3 / Q-1 — /import 415 on missing Content-Type + invalid UTF-8 -------


def test_import_no_content_type_returns_415() -> None:
    """Missing ``Content-Type`` no longer silently defaults to text/plain;
    the contract is explicit so binary bodies can't reach the UTF-8 decode
    and 500 (E-3)."""
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    # Drop the content-type the TestClient would otherwise set.
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=b"1 Roll call",
        headers={"content-type": ""},
    )
    # An empty content-type header is treated as missing (header.get returns
    # the empty string, which our router treats as a non-text/plain value).
    # Either way the runtime must respond 415, not 500.
    assert r.status_code == 415


def test_import_invalid_utf8_text_plain_returns_415() -> None:
    """A ``text/plain`` body with non-UTF-8 bytes must 415 with a clean
    diagnostic, never a raw 500 (Q-1 / E-3)."""
    client = TestClient(_build()[0])
    client.post("/api/staff/agendas", json=_agenda_payload())
    body = b"\xff\xfe" + b"some text"  # invalid UTF-8 leading bytes
    r = client.post(
        "/api/staff/agendas/ag-jan-2026/import",
        content=body,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 415
    assert "UTF-8" in r.text


# --- Q-4 — public 404 detail does not echo user-supplied path --------------


def test_public_404_detail_does_not_echo_meeting_asset_id() -> None:
    """The 404 body must be a fixed string regardless of the path the
    requester sent — no reflection of the user input back into the
    response (Q-4)."""
    client = TestClient(_build()[0])
    arbitrary_ids = (
        "some-meeting",
        "another-meeting-xyz",
        "PRIVATE-LOOKING-NAME",
    )
    seen_details: set[str] = set()
    for mid in arbitrary_ids:
        r = client.get(f"/api/public/agendas/{mid}")
        assert r.status_code == 404
        assert mid not in r.json()["detail"]
        seen_details.add(r.json()["detail"])
    # And every 404 returns the SAME detail — no probing surface.
    assert len(seen_details) == 1
    assert "Meeting agenda not found." in seen_details
