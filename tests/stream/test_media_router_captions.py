# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Public serving of offline-generated VOD captions (keystone K3).

The public caption surface for a *channel* is the live sidecar route in
``civiccast.cable.router``. For a *published recording* it is this one: the
offline caption job writes the reviewed WebVTT track into the asset's HLS
package, and ``/media/vod`` serves the package -- already gated on
``published_at``, so the caption track inherits the same publication gate as
the video it belongs to rather than growing a second access rule.
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
from civiccast.captions.models import CaptionCue
from civiccast.captions.vod import attach_reviewed_captions, published_caption_sidecar
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.models import LiveFinalizationJob
from civiccast.schedule.models import Asset
from civiccast.stream.config import ABR_LADDER, SLATE_RENDITION
from civiccast.stream.media_router import router

_ASSET_ID = "council-2026-08-16"


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


def _write_package(base: Path) -> Path:
    for config in (*ABR_LADDER, SLATE_RENDITION):
        playlist = base / config.name / "playlist.m3u8"
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
    manifest = base / "playlist.m3u8"
    manifest.write_text("#EXTM3U\n", encoding="utf-8")
    return manifest


def _seed_asset(engine: Engine, manifest: Path, *, published: bool = True) -> None:
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id=_ASSET_ID,
                title=_ASSET_ID,
                state="validated",
                manifest_url=f"/media/vod/{_ASSET_ID}/playlist.m3u8",
                published_at=datetime(2026, 8, 16, tzinfo=UTC) if published else None,
            )
        )
        session.add(
            LiveFinalizationJob(
                live_session_id=_ASSET_ID,
                asset_id=_ASSET_ID,
                local_package_manifest_path=str(manifest),
            )
        )
        session.commit()


@pytest.fixture
def captioned_package(engine: Engine, tmp_path: Path) -> Path:
    package_dir = tmp_path / _ASSET_ID
    manifest = _write_package(package_dir)
    attach_reviewed_captions(
        package_dir,
        [
            CaptionCue(
                cue_id="cue-000000",
                start_seconds=0.0,
                end_seconds=1.8,
                text="Motion carries.",
                confidence=0.95,
            )
        ],
    )
    _seed_asset(engine, manifest)
    return package_dir


class TestServeOfflineCaptions:
    def test_flat_records_sidecar_is_served_as_webvtt(
        self, client: TestClient, captioned_package: Path
    ) -> None:
        response = client.get(f"/media/vod/{_ASSET_ID}/captions/captions.vtt")

        assert response.status_code == 200
        # text/vtt, not octet-stream: a browser must render this as a
        # caption track, and a records request must open it as text.
        assert response.headers["content-type"].startswith("text/vtt")
        assert response.text.startswith("WEBVTT")
        assert "Motion carries." in response.text

    def test_hls_caption_playlist_and_segments_are_served(
        self, client: TestClient, captioned_package: Path
    ) -> None:
        playlist = client.get(f"/media/vod/{_ASSET_ID}/captions/en/playlist.m3u8")
        assert playlist.status_code == 200
        assert playlist.headers["content-type"] == "application/vnd.apple.mpegurl"

        segment = client.get(f"/media/vod/{_ASSET_ID}/captions/en/seg000.vtt")
        assert segment.status_code == 200
        assert segment.headers["content-type"].startswith("text/vtt")
        assert "Motion carries." in segment.text

    def test_multivariant_manifest_advertises_the_caption_track(
        self, client: TestClient, captioned_package: Path
    ) -> None:
        response = client.get(f"/media/vod/{_ASSET_ID}/playlist.m3u8")

        assert response.status_code == 200
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in response.text
        assert 'URI="captions/en/playlist.m3u8"' in response.text

    def test_an_unpublished_recording_does_not_leak_its_captions(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        package_dir = tmp_path / _ASSET_ID
        manifest = _write_package(package_dir)
        attach_reviewed_captions(
            package_dir,
            [
                CaptionCue(
                    cue_id="cue-000000",
                    start_seconds=0.0,
                    end_seconds=1.8,
                    text="Not public yet.",
                    confidence=0.95,
                )
            ],
        )
        _seed_asset(engine, manifest, published=False)

        response = client.get(f"/media/vod/{_ASSET_ID}/captions/captions.vtt")

        assert response.status_code == 404

    def test_an_uncaptioned_published_recording_404s_rather_than_serving_empty(
        self, engine: Engine, client: TestClient, tmp_path: Path
    ) -> None:
        package_dir = tmp_path / _ASSET_ID
        _seed_asset(engine, _write_package(package_dir))

        assert not published_caption_sidecar(package_dir).exists()
        response = client.get(f"/media/vod/{_ASSET_ID}/captions/captions.vtt")

        assert response.status_code == 404
