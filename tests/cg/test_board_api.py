# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the CG board-designer staff router (S6 V1 — build step 7, 3b).

A minimal FastAPI app mounts the real board router, sets the operator identity
via middleware (so the real require_any_role gate runs), and overrides
get_cg_board_service with a real CgBoardService on SQLite. Covers role-gating,
full CRUD round-trips, preview, audit, 404s, 422 on a content-source/trust-tier
violation, and 503 when storage is unwired.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.cg.board_router import (
    _preview_ffmpeg_runner,
    board_staff_router,
    get_cg_board_service,
)
from civiccast.cg.board_service import CgBoardService
from civiccast.cg.board_store import CgBoardStore
from civiccast.db import Base
from civiccast.stream._ffmpeg import FfmpegResult


@pytest.fixture
def factory() -> Iterator[Callable[[], Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()

    @contextmanager
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    try:
        yield _factory
    finally:
        engine.dispose()


def _build_app(
    factory,
    *,
    scopes=("publish",),
    wire: bool = True,
    ffmpeg_runner: Callable[[list[str]], FfmpegResult] | None = None,
):  # type: ignore[no-untyped-def]
    app = FastAPI()

    @app.middleware("http")
    async def _set_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(board_staff_router)
    if wire:
        service = CgBoardService(CgBoardStore(factory))
        app.dependency_overrides[get_cg_board_service] = lambda: service
    if ffmpeg_runner is not None:
        app.dependency_overrides[_preview_ffmpeg_runner] = lambda: ffmpeg_runner
    return app


def _client(factory, **kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_app(factory, **kwargs))


def _stub_png_runner(*, payload: bytes = b"PNG") -> Callable[[list[str]], FfmpegResult]:
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return run_ffmpeg


def _always_failing_png_runner() -> Callable[[list[str]], FfmpegResult]:
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        return FfmpegResult(returncode=1, stdout="", stderr="boom: missing font")

    return run_ffmpeg


_BOARD = "/api/staff/cg/channels/public/board"
_ZONES = "/api/staff/cg/channels/public/zones"
_FEEDS = "/api/staff/cg/channels/public/feeds"
_TICKER = {
    "region": "lower",
    "zone_kind": "ticker",
    "content_source": "manual",
    "manual_text": "Hi",
}
_RSS = {
    "kind": "rss",
    "label": "City news",
    "source_url": "https://x.gov/news.rss",
    "trust_tier": "operator_curated",
}


# ---------------------------------------------------------------------------
# Role gate + 503
# ---------------------------------------------------------------------------


class TestRoleGate:
    def test_write_forbidden_for_non_write_role(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=("meeting",)).post(
            _BOARD, json={"template_id": "standard-community-board"}
        )
        assert resp.status_code == 403

    def test_write_forbidden_for_read_only_support_admin(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=("support",)).post(
            _BOARD, json={"template_id": "standard-community-board"}
        )
        assert resp.status_code == 403

    def test_support_admin_may_read(self, factory) -> None:  # type: ignore[no-untyped-def]
        # No board yet -> 404 (not 403): the read gate admits support_admin.
        resp = _client(factory, scopes=("support",)).get(_BOARD)
        assert resp.status_code == 404

    def test_503_when_storage_unwired(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, wire=False).post(
            _BOARD, json={"template_id": "standard-community-board"}
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Timeout / 504 for hung feed fetch (QA-003)
# ---------------------------------------------------------------------------


def test_feed_review_returns_504_when_fetch_hangs(factory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import time

    import civiccast.cg.board_router as br

    monkeypatch.setattr(br, "_FEED_FETCH_TIMEOUT", 0.05)

    class _HangingSvc:
        def list_feed_items_for_review(self, channel_id, *, feed_source_id, **_):
            time.sleep(0.2)
            return []

    app = _build_app(factory, scopes=("publish_operator",), wire=False)
    app.dependency_overrides[get_cg_board_service] = lambda: _HangingSvc()
    resp = TestClient(app).get("/api/staff/cg/channels/ch1/feeds/feed1/items")
    assert resp.status_code == 504


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


class TestBoardLifecycle:
    def test_full_round_trip(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)

        # Create + read the board.
        created = client.post(_BOARD, json={"template_id": "standard-community-board"})
        assert created.status_code == 201
        assert created.json()["active"] is True

        view = client.get(_BOARD)
        assert view.status_code == 200
        assert view.json()["board"]["template_id"] == "standard-community-board"
        assert view.json()["zones"] == [] and view.json()["feeds"] == []

        # Update the board template.
        patched = client.patch(_BOARD, json={"template_id": "live-lower-banner"})
        assert patched.status_code == 200 and patched.json()["template_id"] == "live-lower-banner"

        # Add a zone + a feed.
        zone = client.post(_ZONES, json=_TICKER)
        assert zone.status_code == 201
        zone_id = zone.json()["zone_id"]
        feed = client.post(_FEEDS, json=_RSS)
        assert feed.status_code == 201
        feed_id = feed.json()["feed_source_id"]

        assert {z["zone_id"] for z in client.get(_BOARD).json()["zones"]} == {zone_id}
        assert [f["feed_source_id"] for f in client.get(_FEEDS).json()] == [feed_id]

        # Update + delete the zone.
        upd = client.patch(f"{_ZONES}/{zone_id}", json={"manual_text": "Updated"})
        assert upd.status_code == 200 and upd.json()["manual_text"] == "Updated"
        assert client.delete(f"{_ZONES}/{zone_id}").status_code == 204

        # Preview renders a valid snapshot (required kinds back-filled).
        preview = client.get("/api/staff/cg/channels/public/preview")
        assert preview.status_code == 200
        kinds = {z["kind"] for z in preview.json()["snapshot"]["zones"]}
        assert {"primary", "ticker", "schedule", "logo"} <= kinds

        # Audit reflects the mutations (newest first), operator id from identity.
        audit = client.get(f"{_BOARD}/audit")
        assert audit.status_code == 200
        events = audit.json()
        assert events[0]["operator_id"] == "dana"
        assert "board_created" in {e["event_kind"] for e in events}

        # Delete the feed.
        assert client.delete(f"{_FEEDS}/{feed_id}").status_code == 204

    def test_approve_feed_item(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        client.post(_BOARD, json={"template_id": "standard-community-board"})
        feed_id = client.post(_FEEDS, json=_RSS).json()["feed_source_id"]
        resp = client.post(f"{_FEEDS}/{feed_id}/items/item-1/approve")
        assert resp.status_code == 201
        assert resp.json()["item_id"] == "item-1"
        assert resp.json()["approved_by_operator"] == "dana"

    def test_preview_png_route_via_format_query(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, ffmpeg_runner=_stub_png_runner())
        client.post(_BOARD, json={"template_id": "standard-community-board"})

        response = client.get("/api/staff/cg/channels/public/preview?format=png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"PNG"

    def test_preview_png_route_suffix_path(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, ffmpeg_runner=_stub_png_runner(payload=b"PNG_SUFFIX"))
        client.post(_BOARD, json={"template_id": "standard-community-board"})

        response = client.get("/api/staff/cg/channels/public/preview.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"PNG_SUFFIX"


class TestPreviewPngRenderFailure:
    """Gate audit gap: the PNG preview render-failure path had no coverage.

    ``_render_board_preview`` (civiccast/cg/board_router.py) retries once with
    text disabled (``include_text=False``) after a non-zero ffmpeg return, same
    posture as the board/slide filler paths; if BOTH attempts fail it raises a
    500 with an operator-actionable detail message (gate finding m-2 -- the
    prior message told the operator to "inspect FFmpeg output," which the
    operator UI never exposes).
    """

    def test_format_query_route_returns_500_with_actionable_detail_on_render_failure(
        self, factory
    ) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, ffmpeg_runner=_always_failing_png_runner())
        client.post(_BOARD, json={"template_id": "standard-community-board"})

        response = client.get("/api/staff/cg/channels/public/preview?format=png")

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "inspect FFmpeg output" not in detail
        assert "fonts are missing or misconfigured" in detail
        assert "system administrator" in detail

    def test_suffix_route_returns_500_with_actionable_detail_on_render_failure(
        self, factory
    ) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, ffmpeg_runner=_always_failing_png_runner())
        client.post(_BOARD, json={"template_id": "standard-community-board"})

        response = client.get("/api/staff/cg/channels/public/preview.png")

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "inspect FFmpeg output" not in detail
        assert "fonts are missing or misconfigured" in detail
        assert "system administrator" in detail


class TestPreviewPngDegradedSignal:
    """Gate finding M-1: silent preview text degradation.

    When the first (text-on) ffmpeg attempt fails and the retry
    (``include_text=False``) succeeds, the operator previously got a PNG that
    silently omitted text zones with no signal it didn't match the designed
    board. The router now (a) logs a WARNING naming the channel and board and
    (b) sets ``X-CivicCast-Preview-Degraded`` on the response so the UI can
    surface it.
    """

    def _text_fails_then_image_only_succeeds_runner(
        self,
    ) -> Callable[[list[str]], FfmpegResult]:
        calls: list[bool] = []

        def run_ffmpeg(args: list[str]) -> FfmpegResult:
            include_text = any("drawtext" in a for a in args)
            calls.append(include_text)
            if include_text:
                return FfmpegResult(returncode=1, stdout="", stderr="boom: missing font")
            out_path = Path(args[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"PNG_DEGRADED")
            return FfmpegResult(returncode=0, stdout="", stderr="")

        return run_ffmpeg

    def test_degraded_header_set_when_text_retry_succeeds(self, factory, caplog) -> None:  # type: ignore[no-untyped-def]
        import logging

        client = _client(factory, ffmpeg_runner=self._text_fails_then_image_only_succeeds_runner())
        client.post(_BOARD, json={"template_id": "standard-community-board"})
        # A backfilled default board renders no drawtext at all (empty ticker,
        # no bulletin for the primary zone) -- add a real clock-mode schedule
        # zone so the "text-on" ffmpeg attempt actually emits a drawtext
        # filter and this test exercises the real degrade path.
        client.post(
            _ZONES,
            json={"region": "lower", "zone_kind": "schedule", "content_source": "clock"},
        )

        with caplog.at_level(logging.WARNING, logger="civiccast.cg.board_router"):
            response = client.get("/api/staff/cg/channels/public/preview.png")

        assert response.status_code == 200
        assert response.headers["X-CivicCast-Preview-Degraded"] == "text-omitted"
        assert response.content == b"PNG_DEGRADED"
        assert any(
            "public" in record.message and "preview text render failed" in record.message
            for record in caplog.records
        )

    def test_no_degraded_header_when_text_render_succeeds(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, ffmpeg_runner=_stub_png_runner())
        client.post(_BOARD, json={"template_id": "standard-community-board"})

        response = client.get("/api/staff/cg/channels/public/preview.png")

        assert response.status_code == 200
        assert "X-CivicCast-Preview-Degraded" not in response.headers


# Error mapping
# ---------------------------------------------------------------------------


class TestErrors:
    def test_get_and_patch_board_404_without_board(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        assert client.get(_BOARD).status_code == 404
        assert client.patch(_BOARD, json={"template_id": "x"}).status_code == 404
        assert client.get("/api/staff/cg/channels/public/preview").status_code == 404

    def test_add_zone_without_board_is_404(self, factory) -> None:  # type: ignore[no-untyped-def]
        assert _client(factory).post(_ZONES, json=_TICKER).status_code == 404

    def test_feed_adapter_zone_without_feed_is_422(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        client.post(_BOARD, json={"template_id": "standard-community-board"})
        resp = client.post(
            _ZONES,
            json={"region": "lower", "zone_kind": "ticker", "content_source": "feed_adapter"},
        )
        assert resp.status_code == 422

    def test_weather_public_feed_is_422(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        client.post(_BOARD, json={"template_id": "standard-community-board"})
        resp = client.post(
            _FEEDS,
            json={
                "kind": "weather",
                "label": "WX",
                "source_url": "https://x.gov/wx.json",
                "trust_tier": "public_permitted",
            },
        )
        assert resp.status_code == 422

    def test_update_unknown_zone_and_feed_are_404(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        client.post(_BOARD, json={"template_id": "standard-community-board"})
        assert client.patch(f"{_ZONES}/ghost", json={"manual_text": "x"}).status_code == 404
        assert client.patch(f"{_FEEDS}/ghost", json={"label": "x"}).status_code == 404
        assert client.post(f"{_FEEDS}/ghost/items/i/approve").status_code == 404
