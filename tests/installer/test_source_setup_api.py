# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for operator-facing source and rehearsal media setup endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer.router import get_live_source_store, get_postgres_store
from civiccast.live.models import LiveSourceCreate, LiveSourceResponse
from civiccast.schedule.ingest import FfprobeResult, UnsupportedFormatError
from civiccast.schedule.models import ASSET_STATE_VALIDATED, UploadedAssetResponse


class FakeLiveSourceStore:
    def __init__(self) -> None:
        self.created: list[LiveSourceCreate] = []

    def create(self, payload: LiveSourceCreate) -> LiveSourceResponse:
        self.created.append(payload)
        return LiveSourceResponse(
            live_source_id=payload.live_source_id,
            channel_id=payload.channel_id,
            name=payload.name,
            source_type=payload.source_type,
            endpoint_url=str(payload.endpoint_url),
            credentials_handle=payload.credentials_handle,
            created_at=datetime.now(UTC),
        )

    def get(self, live_source_id: str) -> LiveSourceResponse | None:
        for payload in self.created:
            if payload.live_source_id == live_source_id:
                return LiveSourceResponse(
                    live_source_id=payload.live_source_id,
                    channel_id=payload.channel_id,
                    name=payload.name,
                    source_type=payload.source_type,
                    endpoint_url=str(payload.endpoint_url),
                    credentials_handle=payload.credentials_handle,
                    created_at=datetime.now(UTC),
                )
        return None

    def list(self, *, channel_id: str | None = None) -> list[LiveSourceResponse]:
        return [
            LiveSourceResponse(
                live_source_id=payload.live_source_id,
                channel_id=payload.channel_id,
                name=payload.name,
                source_type=payload.source_type,
                endpoint_url=str(payload.endpoint_url),
                credentials_handle=payload.credentials_handle,
                created_at=datetime.now(UTC),
            )
            for payload in self.created
            if channel_id is None or payload.channel_id == channel_id
        ]


class FakeAssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ingested: list[dict[str, object]] = []

    def get_staff_row(self, asset_id: str) -> None:
        return None

    def ingest_upload(
        self,
        *,
        asset_id: str,
        title: str,
        description: str | None,
        file_path: str,
        file_size_bytes: int,
        ffprobe_result: FfprobeResult,
    ) -> UploadedAssetResponse:
        self.ingested.append(
            {
                "asset_id": asset_id,
                "file_path": file_path,
                "file_size_bytes": file_size_bytes,
            }
        )
        return UploadedAssetResponse(
            asset_id=asset_id,
            title=title,
            description=description,
            state=ASSET_STATE_VALIDATED,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            duration_seconds=ffprobe_result.duration_seconds,
            codec_video=ffprobe_result.codec_video,
            codec_audio=ffprobe_result.codec_audio,
            width_px=ffprobe_result.width_px,
            height_px=ffprobe_result.height_px,
            bitrate_bps=ffprobe_result.bitrate_bps,
            format_name=ffprobe_result.format_name,
        )


_FFPROBE_SAMPLE = FfprobeResult(
    duration_seconds=2,
    codec_video="h264",
    codec_audio="aac",
    width_px=640,
    height_px=360,
    bitrate_bps=300_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


def _client_with_live_store(store: FakeLiveSourceStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_live_source_store] = lambda: store
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def _client_with_asset_store(
    store: FakeAssetStore,
    live_source_store: FakeLiveSourceStore | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: store
    if live_source_store is not None:
        app.dependency_overrides[get_live_source_store] = lambda: live_source_store
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def test_source_setup_creates_real_live_source_contract() -> None:
    store = FakeLiveSourceStore()
    with _client_with_live_store(store) as client:
        response = client.post(
            "/api/staff/installer/source-setup/live-source",
            json={
                "kind": "encoder",
                "label": "Council Room Encoder",
                "endpoint": "rtsp://encoder.example.local/live",
                "channel_id": "gov-ch12",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["live_source_id"].startswith("council-room-encoder-")
    assert payload["source_type"] == "rtsp"
    assert store.created[0].endpoint_url == "rtsp://encoder.example.local/live"
    assert store.created[0].channel_id == "gov-ch12"


def test_source_setup_rejects_credentials_and_unsupported_schemes() -> None:
    store = FakeLiveSourceStore()
    with _client_with_live_store(store) as client:
        credential_response = client.post(
            "/api/staff/installer/source-setup/live-source",
            json={
                "kind": "encoder",
                "label": "Bad Encoder",
                "endpoint": "rtsp://user:password@encoder.example.local/live",
            },
        )
        http_response = client.post(
            "/api/staff/installer/source-setup/live-source",
            json={
                "kind": "encoder",
                "label": "HTTP Probe",
                "endpoint": "http://169.254.169.254/latest/meta-data",
            },
        )

    assert credential_response.status_code == 422
    assert "passwords" in credential_response.json()["detail"]
    assert http_response.status_code == 422
    assert "rtmp" in http_response.json()["detail"]
    assert store.created == []


def test_source_setup_rejects_ndi_path_traversal_shape() -> None:
    store = FakeLiveSourceStore()
    with _client_with_live_store(store) as client:
        response = client.post(
            "/api/staff/installer/source-setup/live-source",
            json={
                "kind": "ndi",
                "label": "NDI Camera",
                "endpoint": "../private/key",
            },
        )

    assert response.status_code == 422
    assert "not a path" in response.json()["detail"]
    assert store.created == []


def test_sample_setup_generates_and_ingests_media(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    store = FakeAssetStore(tmp_path)
    source_store = FakeLiveSourceStore()

    def write_sample(path: Path) -> None:
        path.write_bytes(b"sample-video")

    with (
        _client_with_asset_store(store, source_store) as client,
        patch("civiccast.installer.service._write_sample_video", side_effect=write_sample),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        response = client.post("/api/staff/installer/source-setup/sample-upload")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["asset_id"].startswith("sample-rehearsal-")
    assert payload["live_source_id"] == "civiccast-sample-test-source"
    assert payload["source_type"] == "rtmp"
    assert Path(payload["file_path"]).is_file()
    assert store.ingested[0]["file_size_bytes"] == len(b"sample-video")
    assert source_store.created[0].name == "CivicCast sample test source"
    assert (
        source_store.created[0].endpoint_url == "rtmp://127.0.0.1/live/civiccast-sample-rehearsal"
    )


def test_sample_setup_returns_503_without_upload_storage(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    store = FakeAssetStore(tmp_path)
    source_store = FakeLiveSourceStore()
    with _client_with_asset_store(store, source_store) as client:
        response = client.post("/api/staff/installer/source-setup/sample-upload")

    assert response.status_code == 503
    assert "Upload storage is not ready" in response.json()["detail"]
    assert store.ingested == []
    assert source_store.created == []


def test_sample_setup_cleans_generated_file_on_validation_failure(monkeypatch, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(upload_root))
    store = FakeAssetStore(tmp_path)
    source_store = FakeLiveSourceStore()

    def write_sample(path: Path) -> None:
        path.write_bytes(b"sample-video")

    with (
        _client_with_asset_store(store, source_store) as client,
        patch("civiccast.installer.service._write_sample_video", side_effect=write_sample),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch(
            "civiccast.installer.service.validate_ingest",
            side_effect=UnsupportedFormatError("bad video"),
        ),
    ):
        response = client.post("/api/staff/installer/source-setup/sample-upload")

    assert response.status_code == 422
    assert response.json()["detail"] == "bad video"
    assert list(upload_root.glob("sample-rehearsal-*")) == []
    assert store.ingested == []
    assert source_store.created == []
