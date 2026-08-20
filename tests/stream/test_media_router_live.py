# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for civiccast.stream.media_router's live-HLS mount.

Uses ``InMemoryEgressStore`` (no DB needed — the live route resolves the
served directory from the channel's egress config, not a DB-backed job
row) and writes a fake rolling HLS tree to disk, so these run without
ffmpeg. The ffmpeg+ffprobe end-to-end rolling-manifest proof lives in
test_hls_sink_live_playability.py (playable, updating HLS acceptance bar).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import InMemoryEgressStore
from civiccast.stream.media_router import live_router


@pytest.fixture
def store() -> InMemoryEgressStore:
    return InMemoryEgressStore()


@pytest.fixture
def client(store: InMemoryEgressStore) -> TestClient:
    app = FastAPI()
    app.include_router(live_router)
    app.dependency_overrides[get_egress_store] = lambda: store
    return TestClient(app)


def _configure_hls_sink(store: InMemoryEgressStore, *, channel_id: str, directory: Path) -> None:
    store.upsert_config(
        EgressConfig(
            channel_id=channel_id,
            enabled=True,
            slate_message="Off air",
            sinks=[EgressSinkSpec(kind="hls", label="Web", uri=str(directory))],
        )
    )


def _write_fake_live_tree(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:3\n#EXTINF:2.0,\nseg000000003.ts\n",
        encoding="utf-8",
    )
    (base / "seg000000003.ts").write_bytes(b"\x47" * 188)


class TestServeLiveManifest:
    def test_serves_live_manifest_with_hls_content_type(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        _configure_hls_sink(store, channel_id="gov-ch12", directory=tmp_path)
        _write_fake_live_tree(tmp_path)

        response = client.get("/media/live/gov-ch12/playlist.m3u8")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/vnd.apple.mpegurl"
        assert response.text.startswith("#EXTM3U")
        assert "seg000000003.ts" in response.text

    def test_serves_live_segment(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        _configure_hls_sink(store, channel_id="gov-ch12", directory=tmp_path)
        _write_fake_live_tree(tmp_path)

        response = client.get("/media/live/gov-ch12/seg000000003.ts")

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/MP2T"
        assert response.content == b"\x47" * 188

    def test_live_manifest_cache_control_is_very_short(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        _configure_hls_sink(store, channel_id="gov-ch12", directory=tmp_path)
        _write_fake_live_tree(tmp_path)

        response = client.get("/media/live/gov-ch12/playlist.m3u8")

        assert "immutable" not in response.headers["cache-control"]
        assert "max-age=1" in response.headers["cache-control"]

    def test_live_segment_cache_control_is_long_lived_immutable(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        _configure_hls_sink(store, channel_id="gov-ch12", directory=tmp_path)
        _write_fake_live_tree(tmp_path)

        response = client.get("/media/live/gov-ch12/seg000000003.ts")

        assert "immutable" in response.headers["cache-control"]

    def test_unconfigured_channel_is_404(self, client: TestClient) -> None:
        response = client.get("/media/live/no-such-channel/playlist.m3u8")
        assert response.status_code == 404

    def test_channel_without_hls_sink_is_404(
        self, store: InMemoryEgressStore, client: TestClient
    ) -> None:
        store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="file", label="CI", uri="build/out.ts")],
            )
        )

        response = client.get("/media/live/gov-ch12/playlist.m3u8")
        assert response.status_code == 404

    def test_no_egress_store_configured_is_404(self) -> None:
        app = FastAPI()
        app.include_router(live_router)
        # No dependency_overrides — get_egress_store's default None seam.
        response = TestClient(app).get("/media/live/gov-ch12/playlist.m3u8")
        assert response.status_code == 404

    def test_missing_file_is_404(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        _configure_hls_sink(store, channel_id="gov-ch12", directory=tmp_path)
        _write_fake_live_tree(tmp_path)

        response = client.get("/media/live/gov-ch12/seg999999999.ts")
        assert response.status_code == 404

    def test_path_traversal_outside_live_dir_is_404(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        live_dir = tmp_path / "live"
        _configure_hls_sink(store, channel_id="gov-ch12", directory=live_dir)
        _write_fake_live_tree(live_dir)
        secret = tmp_path / "secret.txt"
        secret.write_text("should never be servable", encoding="utf-8")

        response = client.get("/media/live/gov-ch12/../secret.txt")

        assert response.status_code in (307, 404)
        if response.status_code == 307:
            followed = client.get(response.headers["location"])
            assert followed.status_code == 404
