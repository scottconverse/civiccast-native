# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.router import get_postgres_store
from civiccast.schedule.store import PostgresAssetStore

_PROBE = FfprobeResult(
    duration_seconds=8,
    codec_video="h264",
    codec_audio="aac",
    width_px=1280,
    height_px=720,
    bitrate_bps=1_000_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


def test_validated_asset_can_be_packaged_for_local_resident_playback(
    monkeypatch,
    tmp_path: Path,
    session_factory,
) -> None:
    source_dir = tmp_path / "sample-asset"
    source_dir.mkdir()
    source = source_dir / "sample.mp4"
    source.write_bytes(b"real bytes are replaced by the fake packager")
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="sample-asset",
        title="Sample asset",
        description=None,
        file_path=str(source),
        file_size_bytes=source.stat().st_size,
        ffprobe_result=_PROBE,
    )
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", "http://127.0.0.1:8000")

    def fake_packager(input_path: Path, output_dir: Path, **kwargs):
        assert input_path == source.resolve()
        output_dir.mkdir(parents=True)
        manifest = output_dir / "playlist.m3u8"
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest, output_dir=output_dir)

    asset_row = store.get_staff_row("sample-asset")
    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = asset_row
    expected_url = "/media/vod/sample-asset/playlist.m3u8"
    mock_store.mark_packaged.return_value = asset_row.model_copy(
        update={"manifest_url": expected_url}
    )
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: mock_store
    with (
        patch("civiccast.schedule.router.pack_vod_asset", side_effect=fake_packager),
        TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client,
    ):
        response = client.post("/api/staff/assets/sample-asset/package")

    assert response.status_code == 200
    body = response.json()
    assert body["manifest_url"] == expected_url
    assert (tmp_path / ".civiccast-packages" / "sample-asset" / "playlist.m3u8").read_text(
        encoding="utf-8"
    ) == ("#EXTM3U\n")
    mock_store.mark_packaged.assert_called_once_with("sample-asset", expected_url)


def test_recorded_asset_can_be_packaged_for_local_resident_playback(
    monkeypatch,
    tmp_path: Path,
    session_factory,
) -> None:
    # Scheduled/live captures finalize as ``recorded`` (see recording/runtime.py
    # and live/finalization.py), having passed the same ffprobe + validate_ingest
    # gate as an upload. They must be packageable for the resident portal — this
    # closes the recording -> portal dead end.
    source_dir = tmp_path / "recorded-asset"
    source_dir.mkdir()
    source = source_dir / "council.ts"
    source.write_bytes(b"real bytes are replaced by the fake packager")
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="recorded-asset",
        title="Recorded council meeting",
        description=None,
        file_path=str(source),
        file_size_bytes=source.stat().st_size,
        ffprobe_result=_PROBE,
    )
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", "http://127.0.0.1:8000")

    def fake_packager(input_path: Path, output_dir: Path, **kwargs):
        assert input_path == source.resolve()
        output_dir.mkdir(parents=True)
        manifest = output_dir / "playlist.m3u8"
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest, output_dir=output_dir)

    # A captured recording carries state="recorded", not "validated".
    asset_row = store.get_staff_row("recorded-asset").model_copy(update={"state": "recorded"})
    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = asset_row
    expected_url = "/media/vod/recorded-asset/playlist.m3u8"
    mock_store.mark_packaged.return_value = asset_row.model_copy(
        update={"manifest_url": expected_url}
    )
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: mock_store
    with (
        patch("civiccast.schedule.router.pack_vod_asset", side_effect=fake_packager),
        TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client,
    ):
        response = client.post("/api/staff/assets/recorded-asset/package")

    assert response.status_code == 200
    assert response.json()["manifest_url"] == expected_url
    mock_store.mark_packaged.assert_called_once_with("recorded-asset", expected_url)


def test_packaging_rejects_media_that_has_not_passed_validation(
    monkeypatch,
    tmp_path: Path,
    session_factory,
) -> None:
    source = tmp_path / "pending.mp4"
    source.write_bytes(b"pending")
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="pending-asset",
        title="Pending asset",
        description=None,
        file_path=str(source),
        file_size_bytes=source.stat().st_size,
        ffprobe_result=_PROBE,
    )
    pending = store.get_staff_row("pending-asset").model_copy(update={"state": "pending_ingest"})
    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = pending
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: mock_store

    with TestClient(
        app,
        headers={"Authorization": "Bearer operator-token-a"},
    ) as client:
        response = client.post("/api/staff/assets/pending-asset/package")

    assert response.status_code == 409
    assert "validated" in response.json()["detail"].lower()
    mock_store.mark_packaged.assert_not_called()


def test_packaging_rejects_asset_without_a_local_source(
    monkeypatch,
    tmp_path: Path,
    session_factory,
) -> None:
    source = tmp_path / "missing.mp4"
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="missing-asset",
        title="Missing asset",
        description=None,
        file_path=str(source),
        file_size_bytes=10,
        ffprobe_result=_PROBE,
    )
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    asset_row = store.get_staff_row("missing-asset")
    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = asset_row
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: mock_store

    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
        response = client.post("/api/staff/assets/missing-asset/package")

    assert response.status_code == 409
    assert "source file is missing" in response.json()["detail"].lower()


def test_mark_packaged_persists_manifest_url(session_factory, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="persisted-package",
        title="Persisted package",
        description=None,
        file_path=str(source),
        file_size_bytes=source.stat().st_size,
        ffprobe_result=_PROBE,
    )

    updated = store.mark_packaged(
        "persisted-package",
        "http://127.0.0.1:8000/media/vod/persisted-package/playlist.m3u8",
    )

    assert updated.manifest_url.endswith("/media/vod/persisted-package/playlist.m3u8")
    assert store.get_staff_row("persisted-package").manifest_url == updated.manifest_url


@pytest.mark.parametrize("review_state", ["approved", "pending", "stale", "english_only"])
def test_repackage_preserves_reviewed_tracks_or_keeps_original_package(
    monkeypatch, tmp_path: Path, session_factory, review_state: str
) -> None:
    from civiccast.captions.models import CaptionCue
    from civiccast.captions.review import (
        CaptionReviewDecision,
        CaptionReviewItemCreate,
        InMemoryCaptionReviewStore,
    )
    from civiccast.captions.vod import attach_reviewed_captions
    from civiccast.stream.config import ABR_LADDER, SLATE_RENDITION
    from civiccast.translate.service import translated_cue_id

    source = tmp_path / "source.mp4"
    source.write_bytes(b"retained source")
    store = PostgresAssetStore(session_factory)
    store.ingest_upload(
        asset_id="captioned-asset",
        title="Captioned",
        description=None,
        file_path=str(source),
        file_size_bytes=source.stat().st_size,
        ffprobe_result=_PROBE,
    )
    asset = store.get_staff_row("captioned-asset").model_copy(
        update={"trim_in_seconds": 2.0, "trim_out_seconds": 7.0}
    )
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    package = tmp_path / ".civiccast-packages" / "captioned-asset"

    def fake_packager(input_path, output_dir, **kwargs):
        output_dir.mkdir(parents=True)
        manifest = output_dir / "playlist.m3u8"
        manifest.write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000\n720p/playlist.m3u8\n")
        for config in [*ABR_LADDER, SLATE_RENDITION]:
            rendition = output_dir / config.name
            rendition.mkdir(exist_ok=True)
            (rendition / "playlist.m3u8").write_text(
                "#EXTM3U\n#EXTINF:8,\nsegment.ts\n#EXT-X-ENDLIST\n"
            )
        (output_dir / "playback-timeline.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "source_start_seconds": kwargs.get("trim_in_seconds", 0),
                    "source_end_seconds": kwargs.get("trim_out_seconds"),
                }
            )
        )
        return SimpleNamespace(manifest_path=manifest, output_dir=output_dir)

    fake_packager(source, package)
    english = CaptionCue(
        cue_id="sentence",
        start_seconds=3,
        end_seconds=6,
        text="The meeting is open.",
        confidence=0.95,
    )
    spanish = english.model_copy(
        update={
            "cue_id": translated_cue_id(english.cue_id, "es", source_text=english.text),
            "text": "La sesion esta abierta.",
        }
    )
    attach_reviewed_captions(
        package, [english], spanish_cues=None if review_state == "english_only" else [spanish]
    )
    old_manifest = (package / "playlist.m3u8").read_bytes()
    reviews = InMemoryCaptionReviewStore()
    for cue, language in [(english, "en"), (spanish, "es")]:
        reviews.create(
            CaptionReviewItemCreate(
                review_item_id=language, asset_id=asset.asset_id, cue=cue, language=language
            )
        )
        if language == "en" or review_state != "pending":
            reviews.approve(language, CaptionReviewDecision())
    if review_state == "stale":
        from civiccast.captions.review import CaptionReviewEdit

        reviews.edit("en", CaptionReviewEdit(text="The meeting is now open."))
    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = asset
    mock_store.mark_packaged.return_value = asset
    app = create_app()
    app.state.store_bundle = replace(app.state.store_bundle, caption_review_store=lambda: reviews)
    app.dependency_overrides[get_postgres_store] = lambda: mock_store
    with (
        patch("civiccast.schedule.router.pack_vod_asset", side_effect=fake_packager),
        TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client,
    ):
        response = client.post("/api/staff/assets/captioned-asset/package")
    if review_state in {"pending", "stale"}:
        assert response.status_code == 422
        assert (package / "playlist.m3u8").read_bytes() == old_manifest
        mock_store.mark_packaged.assert_not_called()
        assert (
            "00:00:03.000 --> 00:00:06.000" in (package / "captions" / "captions.vtt").read_text()
        )
    else:
        assert response.status_code == 200
        filenames = ["captions.vtt"]
        if review_state != "english_only":
            filenames.append("captions.es.vtt")
        for filename in filenames:
            assert "00:00:01.000 --> 00:00:04.000" in (package / "captions" / filename).read_text()
        assert (package / "playlist.m3u8").read_text().count("TYPE=SUBTITLES") == len(filenames)
    assert source.read_bytes() == b"retained source"
