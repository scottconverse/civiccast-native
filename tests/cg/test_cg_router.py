# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.app import create_app
from civiccast.cg.board_service import CgBoardService, FeedInput, ZoneInput
from civiccast.cg.board_store import CgBoardStore
from civiccast.cg.router import get_cg_board_service
from civiccast.cg.router import public_router as cg_public_router
from civiccast.db import Base

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def test_multi_zone_snapshot_public_route(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    response = client.get("/api/public/cg/channels/public/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel_id"] == "public"
    assert payload["template"]["template_id"] == "standard-community-board"
    assert payload["hls_render_path"] == "/api/public/cg/channels/public/stream.m3u8"
    assert {zone["kind"] for zone in payload["zones"]} >= {
        "primary",
        "ticker",
        "schedule",
        "logo",
        "audio",
        "alert",
    }


def test_feed_catalog_public_route_is_empty_by_default(monkeypatch: MonkeyPatch) -> None:
    # WP-06: production (and ephemeral/no-DB mode without the explicit demo
    # flag) must never invent example.invalid feeds -- a station that hasn't
    # configured anything gets an honest, empty, actionable catalog.
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_CG_DEMO_FEEDS", raising=False)
    client = TestClient(create_app())

    response = client.get("/api/public/cg/channels/public/feeds")

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel_id"] == "public"
    assert payload["adapters"] == []
    assert payload["proof_boundary"] == "configured-feed-adapters-to-approved-cg-zone-items"
    assert "example.invalid" not in response.text


def test_feed_catalog_demo_mode_requires_explicit_env_flag(monkeypatch: MonkeyPatch) -> None:
    # The sample RSS/iCal/weather/social adapters only appear when an operator
    # has explicitly opted into the demo flag -- never by default.
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CG_DEMO_FEEDS", "1")
    client = TestClient(create_app())

    response = client.get("/api/public/cg/channels/public/feeds")

    assert response.status_code == 200
    payload = response.json()
    assert {adapter["kind"] for adapter in payload["adapters"]} == {
        "rss",
        "ical",
        "weather",
        "social",
    }
    assert "example.invalid" in response.text


@pytest.fixture
def _durable_factory() -> Iterator[Callable[[], Session]]:
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


def _durable_public_app(factory: Callable[[], Session]) -> tuple[FastAPI, CgBoardService]:
    app = FastAPI()
    app.include_router(cg_public_router)
    service = CgBoardService(CgBoardStore(factory))
    app.dependency_overrides[get_cg_board_service] = lambda: service
    return app, service


def test_feed_catalog_durable_reflects_station_configuration(
    _durable_factory: Callable[[], Session],
) -> None:
    app, service = _durable_public_app(_durable_factory)
    client = TestClient(app)

    # Nothing configured yet -> empty, actionable catalog (never sample rows).
    empty = client.get("/api/public/cg/channels/public/feeds")
    assert empty.status_code == 200
    assert empty.json()["adapters"] == []

    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    feed = service.add_feed(
        "public",
        payload=FeedInput(
            kind="rss",
            label="City news",
            source_url="https://city.example.gov/news.rss",
            trust_tier="operator_curated",
        ),
        operator_id="op_a",
    )
    service.add_zone(
        "public",
        payload=ZoneInput(
            region="lower",
            zone_kind="ticker",
            content_source="feed_adapter",
            feed_source_id=feed.feed_source_id,
        ),
        operator_id="op_a",
    )

    configured = client.get("/api/public/cg/channels/public/feeds")
    assert configured.status_code == 200
    payload = configured.json()
    assert len(payload["adapters"]) == 1
    assert payload["adapters"][0]["source_url"] == "https://city.example.gov/news.rss"
    assert "example.invalid" not in configured.text

    # The portal display contract's embedded feed_catalog agrees.
    display = client.get("/api/public/cg/channels/public/display")
    assert display.status_code == 200
    assert display.json()["feed_catalog"]["adapters"][0]["adapter_id"] == feed.feed_source_id
    assert "example.invalid" not in display.text


def test_production_app_factory_exposes_no_example_feed(monkeypatch: MonkeyPatch) -> None:
    """Done-means (WP-06): the production app factory never surfaces sample
    example.invalid content as a configured feed on either endpoint that
    carries the feed catalog."""

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_CG_DEMO_FEEDS", raising=False)
    client = TestClient(create_app())

    feeds = client.get("/api/public/cg/channels/public/feeds")
    display = client.get("/api/public/cg/channels/public/display")

    assert feeds.status_code == 200
    assert display.status_code == 200
    assert "example.invalid" not in feeds.text
    assert "example.invalid" not in display.text


def test_template_library_and_portal_display_routes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    templates = client.get("/api/public/cg/channels/public/templates")
    display = client.get("/api/public/cg/channels/public/display")

    assert templates.status_code == 200
    assert templates.json()["active_template_id"] == "standard-community-board"
    assert len(templates.json()["templates"]) == 3
    assert display.status_code == 200
    display_payload = display.json()
    assert display_payload["snapshot"]["template"]["template_id"] == "standard-community-board"
    assert display_payload["template_library"]["templates"]
    assert display_payload["approved_bulletins"]["approved_zone_items"]
    assert display_payload["render_plan"]["manifest_url"].endswith("/stream.m3u8")

    alternate = client.get(
        "/api/public/cg/channels/public/display?template_id=schedule-forward-board"
    )
    assert alternate.status_code == 200
    assert alternate.json()["snapshot"]["template"]["template_id"] == "schedule-forward-board"


def test_bulletins_routes_separate_public_approved_view_from_staff_queue(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    public = client.get("/api/public/cg/channels/public/bulletins")
    staff = client.get("/api/staff/cg/channels/public/bulletins", headers=_STAFF_HEADERS)

    assert public.status_code == 200
    public_payload = public.json()
    assert [submission["state"] for submission in public_payload["submissions"]] == ["scheduled"]
    assert public_payload["approved_zone_items"][0]["content"]["submission_id"] == "arts-fair"
    assert (
        public_payload["proof_boundary"] == "approved-community-bulletins-to-public-cg-zone-items"
    )
    assert staff.status_code == 200
    staff_payload = staff.json()
    assert [submission["state"] for submission in staff_payload["submissions"]] == [
        "scheduled",
        "needs_changes",
    ]


def test_hls_render_plan_and_manifest_routes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    plan = client.get("/api/public/cg/channels/public/render-plan")
    manifest = client.get("/api/public/cg/channels/public/stream.m3u8")

    assert plan.status_code == 200
    assert plan.json()["manifest_url"] == "/api/public/cg/channels/public/stream.m3u8"
    assert plan.json()["linear_overlay_contract_url"].endswith("/overlay-contract")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "#EXTM3U" in manifest.text
    assert "/api/public/cg/channels/public/segments/cg-00001.ts" in manifest.text

    overlay_contract = client.get("/api/public/cg/channels/public/overlay-contract")
    assert overlay_contract.status_code == 200
    assert overlay_contract.json()["snapshot_url"] == "/api/public/cg/channels/public/snapshot"
    assert overlay_contract.json()["format"] == "json-overlay-v1"
