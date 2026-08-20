# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.schedule.router — list/get/create endpoints.

Locks the HTTP contract for the three new schedule endpoints landing at
v0.3 task 2:

  - GET  /api/public/assets             -> 200 + JSON array
  - GET  /api/public/assets/{asset_id}  -> 200 + AssetMetadata or 404
  - POST /api/staff/assets              -> 201 + canonical asset
                                            or 422 (invalid) or 409 (duplicate)

The router is wired through ``get_asset_store`` (per Decision Q4b in
director-decisions.md). The schedule routers are mounted into the FastAPI
app inside ``create_app()``. Both router test bodies depend on those two
facts being live — until they are, every test in this file fails with
``ImportError`` (router module missing) or ``404`` (routes not mounted).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.router import get_asset_store
from civiccast.vod.models import AssetMetadata
from civiccast.vod.store import InMemoryAssetStore


def _make_asset(
    asset_id: str = "abc123",
    *,
    title: str = "Test asset",
    manifest_url: str = "https://cdn.example/abc/playlist.m3u8",
    description: str | None = None,
    poster_url: str | None = None,
    duration_seconds: int | None = None,
    published_at: str | None = "2026-05-09T12:00:00+00:00",
) -> AssetMetadata:
    return AssetMetadata(
        asset_id=asset_id,
        title=title,
        description=description,
        manifest_url=manifest_url,  # type: ignore[arg-type]
        poster_url=poster_url,  # type: ignore[arg-type]
        duration_seconds=duration_seconds,
        published_at=published_at,  # type: ignore[arg-type]
    )


@pytest.fixture
def store() -> InMemoryAssetStore:
    return InMemoryAssetStore()


@pytest.fixture
def client(store: InMemoryAssetStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_asset_store] = lambda: store
    # vod router uses get_store; override to the same store so the embed
    # endpoint sees what the schedule router writes (round-trip test below).
    from civiccast.vod.router import get_store

    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def _valid_payload(asset_id: str = "new-asset") -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "title": "New asset",
        "description": "A description",
        "manifest_url": "https://cdn.example/new/playlist.m3u8",
        "poster_url": "https://cdn.example/new/poster.jpg",
        "duration_seconds": 1800,
        "published_at": "2026-05-09T12:00:00+00:00",
    }


class TestListEndpoint:
    """Locks: GET /api/public/assets returns the active store's contents."""

    def test_GET_assets_empty_store_returns_200_and_empty_array(self, client: TestClient) -> None:
        r = client.get("/api/public/assets")
        assert r.status_code == 200
        assert r.json() == []

    def test_GET_assets_populated_store_returns_all_assets(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(_make_asset(asset_id="alpha-1", title="Alpha"))
        store.put(_make_asset(asset_id="beta-2", title="Beta"))
        store.put(_make_asset(asset_id="gamma-3", title="Gamma"))
        r = client.get("/api/public/assets")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert {row["asset_id"] for row in body} == {"alpha-1", "beta-2", "gamma-3"}

    def test_GET_assets_hides_packaged_asset_until_publish_is_approved(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(_make_asset(asset_id="approved", title="Approved"))
        store.put(_make_asset(asset_id="packaged-draft", title="Draft", published_at=None))

        body = client.get("/api/public/assets").json()

        assert [row["asset_id"] for row in body] == ["approved"]

    def test_GET_assets_carries_the_meeting_body_tag(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        # Audit TEST-002: the portal facet depends on this leg of the pipe;
        # both Playwright suites mock it, so this is the only runtime pin.
        tagged = _make_asset(asset_id="tagged-1", title="Tagged")
        tagged = tagged.model_copy(update={"meeting_body": "City Council"})
        store.put(tagged)
        store.put(_make_asset(asset_id="untagged-2", title="Untagged"))

        body = client.get("/api/public/assets").json()

        by_id = {row["asset_id"]: row for row in body}
        assert by_id["tagged-1"]["meeting_body"] == "City Council"
        assert by_id["untagged-2"]["meeting_body"] is None


class TestGetEndpoint:
    """Locks: GET /api/public/assets/{asset_id} mirrors the embed-endpoint
    404 pattern and returns the canonical AssetMetadata on hit."""

    def test_GET_asset_by_id_returns_200_and_asset(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(_make_asset(asset_id="hit-1", title="Hit"))
        r = client.get("/api/public/assets/hit-1")
        assert r.status_code == 200
        body = r.json()
        assert body["asset_id"] == "hit-1"
        assert body["title"] == "Hit"

    def test_GET_asset_by_id_missing_returns_404_with_detail(self, client: TestClient) -> None:
        r = client.get("/api/public/assets/missing-asset")
        assert r.status_code == 404
        body = r.json()
        assert "missing-asset" in body["detail"]

    def test_GET_asset_by_id_hides_packaged_asset_until_publish_is_approved(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(_make_asset(asset_id="packaged-draft", published_at=None))

        response = client.get("/api/public/assets/packaged-draft")

        assert response.status_code == 404

    def test_local_manifest_is_same_origin_for_remote_resident_host(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(
            _make_asset(
                asset_id="local-package",
                manifest_url=("http://127.0.0.1:8000/media/vod/local-package/playlist.m3u8"),
            )
        )

        response = client.get(
            "/api/public/assets/local-package",
            headers={"Host": "civiccast.lpm.test"},
        )

        assert response.status_code == 200
        assert response.json()["manifest_url"] == "/media/vod/local-package/playlist.m3u8"
        assert "127.0.0.1" not in response.text


class TestCreateEndpoint:
    """Locks: POST /api/staff/assets persists, returns canonical, 422s on
    invalid payload, 409s on duplicate asset_id (per Decision 3)."""

    def test_POST_create_valid_asset_returns_201_and_canonical_asset(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        r = client.post("/api/staff/assets", json=_valid_payload("new-asset"))
        assert r.status_code == 201
        body = r.json()
        assert body["asset_id"] == "new-asset"
        # Body must equal store.get(asset_id) — the canonical row, per Q6.
        canonical = store.get("new-asset")
        assert canonical is not None
        assert body["title"] == canonical.title
        assert body["manifest_url"] == str(canonical.manifest_url)

    def test_POST_create_persists_to_store(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        assert store.get("new-asset") is None
        r = client.post("/api/staff/assets", json=_valid_payload("new-asset"))
        assert r.status_code == 201
        assert store.get("new-asset") is not None

    def test_POST_create_invalid_asset_id_pattern_returns_422(self, client: TestClient) -> None:
        bad = _valid_payload()
        bad["asset_id"] = "UPPERCASE-NOT-ALLOWED"
        r = client.post("/api/staff/assets", json=bad)
        assert r.status_code == 422

    def test_POST_create_missing_required_field_returns_422(self, client: TestClient) -> None:
        bad = _valid_payload()
        del bad["title"]
        r = client.post("/api/staff/assets", json=bad)
        assert r.status_code == 422

    def test_POST_create_duplicate_asset_id_returns_409_with_detail(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(_make_asset(asset_id="dup-1"))
        r = client.post("/api/staff/assets", json=_valid_payload("dup-1"))
        assert r.status_code == 409
        body = r.json()
        assert "dup-1" in body["detail"]


class TestEmbedRoundTrip:
    """Locks: an asset created via POST is immediately embeddable through
    the v0.2 vod embed endpoint (per Q8). Guards against the embed endpoint
    being silently broken by the AssetStore Protocol extension."""

    def test_POST_create_then_GET_embed_returns_well_formed_html(self, client: TestClient) -> None:
        payload = _valid_payload("round-trip-1")
        post = client.post("/api/staff/assets", json=payload)
        assert post.status_code == 201
        r = client.get("/api/public/embed/round-trip-1")
        assert r.status_code == 200
        body = r.json()
        assert body["embed_html"].startswith("<iframe")
        assert "playlist.m3u8" in body["manifest_url"]


class TestStaffRouteDocstring:
    """Locks: the staff create handler's docstring carries auth posture."""

    def test_POST_endpoint_docstring_warns_about_auth(self) -> None:
        from civiccast.schedule import router as schedule_router_module

        # Find the create handler. Convention: ``create_asset`` exported from
        # the router module. If renamed, the test surfaces the rename.
        handler = getattr(schedule_router_module, "create_asset", None)
        assert handler is not None, (
            "civiccast.schedule.router must expose a `create_asset` handler "
            "for the staff POST endpoint"
        )
        doc = (handler.__doc__ or "").lower()
        assert "bearer authentication" in doc and "loopback" in doc, (
            f"staff create_asset docstring must describe auth posture; got: {doc!r}"
        )
