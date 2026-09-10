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

import os
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import InMemoryEgressStore
from civiccast.stream.media_router import live_router


@pytest.fixture(autouse=True)
def _live_hls_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The route serves only folders inside CIVICCAST_LIVE_HLS_ROOT (else the
    # egress work dir); every tree these tests write lives under tmp_path.
    monkeypatch.setenv("CIVICCAST_LIVE_HLS_ROOT", str(tmp_path))


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


# ---------------------------------------------------------------------------
# Round-2 delta review, BLOCKER 2 + MINOR 4: this route is public and
# unauthenticated and used to serve whatever folder the ``hls`` sink named,
# verbatim. Containment is now checked HERE, on the resolved path, at serve
# time -- so a sink written by any path (the config PUT, a future writer, a
# hand-edited row) or a junction swapped in after the config was written
# cannot re-point the file server outside the allowed root.
# ---------------------------------------------------------------------------


def _make_junction(link: Path, target: Path) -> None:
    """An NTFS junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        subprocess.run(  # fixed argv, test-only
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:  # pragma: no cover - exercised on POSIX CI only
        link.symlink_to(target, target_is_directory=True)


class TestLiveDirectoryContainment:
    def test_sink_outside_the_root_is_404_even_when_the_folder_exists(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path, monkeypatch
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("CIVICCAST_LIVE_HLS_ROOT", str(root))
        elsewhere = tmp_path / "elsewhere"
        _write_fake_live_tree(elsewhere)
        # Written straight into the store: no route validated this sink.
        _configure_hls_sink(store, channel_id="gov-ch12", directory=elsewhere)

        assert client.get("/media/live/gov-ch12/playlist.m3u8").status_code == 404
        assert client.get("/media/live/gov-ch12/seg000000003.ts").status_code == 404

    @pytest.mark.parametrize(
        "uri", ["\\\\fileserver\\share\\hls", "relative/live", "file://fileserver/live"]
    )
    def test_unc_and_relative_sinks_are_404(
        self, store: InMemoryEgressStore, client: TestClient, uri: str
    ) -> None:
        store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="hls", label="Web", uri=uri)],
            )
        )
        assert client.get("/media/live/gov-ch12/playlist.m3u8").status_code == 404

    def test_junction_inside_the_root_pointing_outside_is_404(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path, monkeypatch
    ) -> None:
        # The TOCTOU half: the sink names a folder INSIDE the root (it would
        # pass any apply-time check), but that folder is a junction to a tree
        # outside it. Containment on the RESOLVED path catches it at serve time.
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("CIVICCAST_LIVE_HLS_ROOT", str(root))
        secret = tmp_path / "secret"
        _write_fake_live_tree(secret)
        link = root / "gov-ch12"
        _make_junction(link, secret)
        assert (link / "playlist.m3u8").is_file()  # the junction itself works
        _configure_hls_sink(store, channel_id="gov-ch12", directory=link)

        assert client.get("/media/live/gov-ch12/playlist.m3u8").status_code == 404

    def test_sink_inside_the_root_still_serves(
        self, store: InMemoryEgressStore, client: TestClient, tmp_path: Path
    ) -> None:
        inside = tmp_path / "live-hls" / "gov-ch12"
        _write_fake_live_tree(inside)
        _configure_hls_sink(store, channel_id="gov-ch12", directory=inside)

        assert client.get("/media/live/gov-ch12/playlist.m3u8").status_code == 200
