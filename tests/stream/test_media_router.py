# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for civiccast.stream.media_router — VOD local-serve mount.

These use the FastAPI app with an in-memory SQLite engine bound directly
(no full create_app() durable-storage wiring needed — the router only
depends on civiccast.db.get_session) and write a fake packaged HLS tree to
disk, so they run without ffmpeg. The ffmpeg+ffprobe end-to-end proof lives
in test_finalization_worker_app_wiring.py (playable-HLS acceptance bar).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.live.models  # noqa: F401 - registers LiveFinalizationJob on Base
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.models import LiveFinalizationJob
from civiccast.schedule.models import Asset
from civiccast.stream.media_router import router


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed_job(engine: Engine, *, asset_id: str, manifest_path: Path) -> None:
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title=asset_id,
                state="validated",
                manifest_url=f"http://127.0.0.1:8000/media/vod/{asset_id}/playlist.m3u8",
                published_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        )
        session.add(
            LiveFinalizationJob(
                live_session_id=asset_id,
                asset_id=asset_id,
                local_package_manifest_path=str(manifest_path),
            )
        )
        session.commit()


def _write_fake_package(base: Path) -> Path:
    """A minimal but shaped-correctly HLS package tree (no real ffmpeg)."""
    manifest = base / "playlist.m3u8"
    manifest.write_text(
        "#EXTM3U\n#EXT-X-VERSION:7\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=320x240\n"
        "240p/playlist.m3u8\n",
        encoding="utf-8",
    )
    rend_dir = base / "240p"
    rend_dir.mkdir()
    (rend_dir / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:2.0,\nseg000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    (rend_dir / "seg000.ts").write_bytes(b"\x47" * 188)
    return manifest


class TestServeManifest:
    def test_serves_multivariant_manifest_with_hls_content_type(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="council-2026-01-01", manifest_path=manifest)

        response = client.get("/media/vod/council-2026-01-01/playlist.m3u8")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/vnd.apple.mpegurl"
        assert response.text.startswith("#EXTM3U")
        assert "240p/playlist.m3u8" in response.text

    def test_serves_variant_playlist_and_segment(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="council-2026-01-01", manifest_path=manifest)

        variant = client.get("/media/vod/council-2026-01-01/240p/playlist.m3u8")
        segment = client.get("/media/vod/council-2026-01-01/240p/seg000.ts")

        assert variant.status_code == 200
        assert variant.headers["content-type"] == "application/vnd.apple.mpegurl"
        assert segment.status_code == 200
        assert segment.headers["content-type"] == "video/MP2T"
        assert segment.content == b"\x47" * 188

    def test_segment_cache_control_is_long_lived_immutable(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="a1", manifest_path=manifest)

        response = client.get("/media/vod/a1/240p/seg000.ts")

        assert "immutable" in response.headers["cache-control"]

    def test_manifest_cache_control_is_short(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="a1", manifest_path=manifest)

        response = client.get("/media/vod/a1/playlist.m3u8")

        assert "immutable" not in response.headers["cache-control"]

    def test_unknown_asset_id_is_404(self, client: TestClient) -> None:
        response = client.get("/media/vod/does-not-exist/playlist.m3u8")
        assert response.status_code == 404

    def test_asset_with_no_completed_job_is_404(self, engine: Engine, client: TestClient) -> None:
        with Session(bind=engine) as session:
            session.add(
                LiveFinalizationJob(
                    live_session_id="pending-one",
                    asset_id="pending-one",
                    local_package_manifest_path=None,
                )
            )
            session.commit()

        response = client.get("/media/vod/pending-one/playlist.m3u8")
        assert response.status_code == 404

    def test_serves_packaged_uploaded_asset_without_finalization_job(
        self,
        engine: Engine,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        asset_dir = tmp_path / "uploaded-one"
        asset_dir.mkdir()
        source = asset_dir / "source.mp4"
        source.write_bytes(b"source")
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
        package_dir = tmp_path / ".civiccast-packages" / "uploaded-one"
        package_dir.mkdir(parents=True)
        manifest = _write_fake_package(package_dir)
        with Session(bind=engine) as session:
            session.add(
                Asset(
                    asset_id="uploaded-one",
                    title="Uploaded one",
                    state="validated",
                    file_path=str(source),
                    manifest_url=("http://127.0.0.1:8000/media/vod/uploaded-one/playlist.m3u8"),
                    published_at=datetime(2026, 7, 15, tzinfo=UTC),
                )
            )
            session.commit()

        response = client.get("/media/vod/uploaded-one/playlist.m3u8")

        assert response.status_code == 200
        assert response.text.replace("\r\n", "\n") == manifest.read_text(encoding="utf-8")

    def test_packaged_uploaded_asset_is_not_servable_before_publish_approval(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        asset_dir = tmp_path / "packaged-draft"
        asset_dir.mkdir()
        source = asset_dir / "source.mp4"
        source.write_bytes(b"source")
        package_dir = asset_dir / "hls"
        package_dir.mkdir()
        _write_fake_package(package_dir)
        with Session(bind=engine) as session:
            session.add(
                Asset(
                    asset_id="packaged-draft",
                    title="Packaged draft",
                    state="validated",
                    file_path=str(source),
                    manifest_url=("http://127.0.0.1:8000/media/vod/packaged-draft/playlist.m3u8"),
                    published_at=None,
                )
            )
            session.commit()

        response = client.get("/media/vod/packaged-draft/playlist.m3u8")

        assert response.status_code == 404

    def test_missing_file_within_a_known_package_is_404(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="a1", manifest_path=manifest)

        response = client.get("/media/vod/a1/360p/playlist.m3u8")
        assert response.status_code == 404

    def test_path_traversal_outside_package_dir_is_404(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        manifest = _write_fake_package(tmp_path)
        _seed_job(engine, asset_id="a1", manifest_path=manifest)
        secret = tmp_path.parent / "secret.txt"
        secret.write_text("should never be servable", encoding="utf-8")

        response = client.get("/media/vod/a1/../secret.txt")

        assert response.status_code in (307, 404)
        if response.status_code == 307:
            # Starlette normalizes ../ before routing; follow and confirm 404.
            followed = client.get(response.headers["location"])
            assert followed.status_code == 404
