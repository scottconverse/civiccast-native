# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the public embed-widget API endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.vod.models import AssetMetadata
from civiccast.vod.router import get_store
from civiccast.vod.store import InMemoryAssetStore


@pytest.fixture
def store() -> InMemoryAssetStore:
    s = InMemoryAssetStore()
    s.put(
        AssetMetadata(
            asset_id="city-council-2026-05-08",
            title="City Council Meeting — May 8, 2026",
            description="Regular session.",
            manifest_url="https://cdn.example/city-council-2026-05-08/playlist.m3u8",  # type: ignore[arg-type]
            poster_url="https://cdn.example/city-council-2026-05-08/poster.jpg",  # type: ignore[arg-type]
            duration_seconds=5400,
            published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
        )
    )
    return s


@pytest.fixture
def client(store: InMemoryAssetStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c


class TestEmbedEndpoint:
    def test_returns_404_for_unknown_asset(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/does-not-exist")
        assert r.status_code == 404

    def test_returns_404_for_packaged_but_unpublished_asset(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(
            AssetMetadata(
                asset_id="packaged-draft",
                title="Packaged draft",
                manifest_url="https://cdn.example/draft/playlist.m3u8",  # type: ignore[arg-type]
                published_at=None,
            )
        )

        response = client.get("/api/public/embed/packaged-draft")

        assert response.status_code == 404

    def test_returns_200_for_known_asset(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/city-council-2026-05-08")
        assert r.status_code == 200

    def test_response_includes_manifest_url(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        assert body["manifest_url"] == "https://cdn.example/city-council-2026-05-08/playlist.m3u8"

    def test_local_manifest_never_sends_remote_resident_to_loopback(
        self, client: TestClient, store: InMemoryAssetStore
    ) -> None:
        store.put(
            AssetMetadata(
                asset_id="local-package",
                title="Local package",
                manifest_url=("http://127.0.0.1:8000/media/vod/local-package/playlist.m3u8"),
                published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
            )
        )

        response = client.get(
            "/api/public/embed/local-package",
            headers={"Host": "civiccast.lpm.test"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["manifest_url"] == "/media/vod/local-package/playlist.m3u8"
        assert "127.0.0.1" not in body["portal_url"]
        assert "127.0.0.1" not in body["embed_html"]

    def test_response_includes_iframe_html(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        assert body["embed_html"].startswith("<iframe")
        assert "</iframe>" in body["embed_html"]

    def test_portal_url_contains_manifest_query_param(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        assert "?manifest=" in body["portal_url"]
        assert "playlist.m3u8" in body["portal_url"]

    def test_portal_url_uses_root_path_not_per_asset_route(self, client: TestClient) -> None:
        # The Sprint 0.2 portal SPA serves only /. Embedding to a /v/{asset_id}
        # route would 404 in every iframe in the wild — guard against
        # regression to that shape.
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        portal_url = body["portal_url"]
        # Strip the query string before checking the path.
        path_part = portal_url.split("?", 1)[0]
        assert path_part.endswith("/"), (
            f"portal_url must point at the SPA root, got path={path_part!r}"
        )
        assert "/v/" not in path_part, (
            f"portal_url must not use the deferred /v/ route, got {path_part!r}"
        )

    def test_portal_url_honors_civiccast_portal_base_env_var(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PORTAL_BASE", "https://portal.example.org")
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        assert body["portal_url"].startswith("https://portal.example.org/?manifest=")

    def test_portal_url_strips_trailing_slash_on_env_var(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PORTAL_BASE", "https://portal.example.org/")
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        # Must not produce a double slash.
        assert "//?" not in body["portal_url"]
        assert body["portal_url"].startswith("https://portal.example.org/?manifest=")

    def test_default_dimensions_are_640x360(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/city-council-2026-05-08")
        body = r.json()
        assert body["embed_width"] == 640
        assert body["embed_height"] == 360

    def test_invalid_asset_id_pattern_is_404(self, client: TestClient) -> None:
        # asset_id is constrained at the model level, not the router; the
        # router treats anything not in the store as 404, including ids
        # that would not validate as Asset metadata themselves.
        r = client.get("/api/public/embed/UPPERCASE_NOT_VALID")
        assert r.status_code == 404

    def test_404_includes_asset_id_in_detail(self, client: TestClient) -> None:
        r = client.get("/api/public/embed/missing-asset")
        assert r.status_code == 404
        assert "missing-asset" in r.json()["detail"]


class TestAssetMetadataValidation:
    def test_asset_id_must_match_pattern(self) -> None:
        with pytest.raises(ValueError, match="asset_id"):
            AssetMetadata(
                asset_id="UPPERCASE-NOT-OK",
                title="Test",
                manifest_url="https://cdn.example/a/playlist.m3u8",  # type: ignore[arg-type]
            )

    def test_title_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError):
            AssetMetadata(
                asset_id="abc",
                title="",
                manifest_url="https://cdn.example/a/playlist.m3u8",  # type: ignore[arg-type]
            )

    def test_manifest_url_rejects_plain_http_by_default(self) -> None:
        """HTTPS-only enforcement (Sprint 0.3 cleanup batch C). Plain http://
        URLs raise ValueError unless CIVICCAST_ALLOW_INSECURE_MANIFEST is set.
        """
        with pytest.raises(ValueError, match="https"):
            AssetMetadata(
                asset_id="abc",
                title="T",
                manifest_url="http://insecure.example/a/playlist.m3u8",  # type: ignore[arg-type]
            )

    def test_poster_url_rejects_plain_http_by_default(self) -> None:
        with pytest.raises(ValueError, match="https"):
            AssetMetadata(
                asset_id="abc",
                title="T",
                manifest_url="https://cdn.example/a/playlist.m3u8",  # type: ignore[arg-type]
                poster_url="http://insecure.example/a/poster.jpg",  # type: ignore[arg-type]
            )

    def test_manifest_url_accepts_http_when_escape_hatch_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dev escape hatch: CIVICCAST_ALLOW_INSECURE_MANIFEST=1 lets http://
        through for local development against plain-HTTP origins."""
        monkeypatch.setenv("CIVICCAST_ALLOW_INSECURE_MANIFEST", "1")
        asset = AssetMetadata(
            asset_id="abc",
            title="T",
            manifest_url="http://insecure.example/a/playlist.m3u8",  # type: ignore[arg-type]
        )
        assert str(asset.manifest_url).startswith("http://")

    def test_manifest_url_https_always_accepted(self) -> None:
        asset = AssetMetadata(
            asset_id="abc",
            title="T",
            manifest_url="https://cdn.example/a/playlist.m3u8",  # type: ignore[arg-type]
        )
        assert str(asset.manifest_url).startswith("https://")

    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1:8000", "localhost:8000", "127.0.0.1"],
    )
    def test_manifest_url_loopback_http_is_exempt_without_escape_hatch(self, host: str) -> None:
        """VOD local-serve default: http://127.0.0.1:8000/media/... must
        validate with NO env var set — it's the stock-install default, not
        a dev-only escape hatch.
        """
        asset = AssetMetadata(
            asset_id="abc",
            title="T",
            manifest_url=f"http://{host}/media/vod/abc/playlist.m3u8",  # type: ignore[arg-type]
        )
        assert str(asset.manifest_url).startswith("http://")

    def test_manifest_url_rejects_plain_http_for_non_loopback_host_still(self) -> None:
        """The loopback exemption must not widen into a general http:// pass —
        a real external host still needs https:// (or the explicit escape
        hatch), same as before this exemption existed.
        """
        with pytest.raises(ValueError, match="https"):
            AssetMetadata(
                asset_id="abc",
                title="T",
                manifest_url="http://127.0.0.1.evil.example/a/playlist.m3u8",  # type: ignore[arg-type]
            )
