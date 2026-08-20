# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the POST /api/staff/assets/upload endpoint.

Four classes:

  TestUploadEndpointNoDB            — 503 when get_postgres_store returns None
  TestUploadEndpointFormValidation  — 422 on missing / malformed form fields
  TestUploadEndpointFfprobeGate     — 422 when ffprobe validation fails (mocked)
  TestUploadEndpointHappyPath       — 201 + UploadedAssetResponse with all fields
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import ASSET_STATE_VALIDATED, UploadedAssetResponse
from civiccast.schedule.router import get_postgres_store
from civiccast.vod.store import AssetAlreadyExistsError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FFPROBE_RESULT = FfprobeResult(
    duration_seconds=60,
    codec_video="h264",
    codec_audio="aac",
    width_px=1920,
    height_px=1080,
    bitrate_bps=5_000_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


def _fake_video_bytes() -> bytes:
    return b"\x00" * 1024  # placeholder — not parsed by real ffprobe in unit tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def no_db_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Client with no Postgres store override (upload returns 503)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


@pytest.fixture
def upload_client(tmp_path) -> Iterator[TestClient]:
    """Client with a mocked Postgres store and CIVICCAST_UPLOAD_DIR set."""
    app = create_app()

    mock_store = MagicMock()
    mock_store.get_staff_row.return_value = None
    mock_store.ingest_upload.return_value = UploadedAssetResponse(
        asset_id="test-upload-01",
        title="Test Upload",
        description=None,
        state=ASSET_STATE_VALIDATED,
        file_path=str(tmp_path / "test-upload-01" / "test.mp4"),
        file_size_bytes=1024,
        duration_seconds=60,
        codec_video="h264",
        codec_audio="aac",
        width_px=1920,
        height_px=1080,
        bitrate_bps=5_000_000,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
    )
    app.dependency_overrides[get_postgres_store] = lambda: mock_store

    with (
        patch.dict(os.environ, {"CIVICCAST_UPLOAD_DIR": str(tmp_path)}),
        TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c,
    ):
        yield c


# ---------------------------------------------------------------------------
# TestUploadEndpointNoDB
# ---------------------------------------------------------------------------


class TestUploadEndpointNoDB:
    """503 when no Postgres store is wired (DATABASE_URL not set)."""

    def test_returns_503_when_no_postgres_store(self, no_db_client: TestClient) -> None:
        response = no_db_client.post(
            "/api/staff/assets/upload",
            data={"asset_id": "test-asset-01", "title": "Test"},
            files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
        )
        assert response.status_code == 503
        assert "Durable storage is not ready" in response.json()["detail"]


# ---------------------------------------------------------------------------
# TestUploadEndpointFormValidation
# ---------------------------------------------------------------------------


class TestUploadEndpointFormValidation:
    """422 on missing or malformed required form fields."""

    def test_missing_asset_id(self, upload_client: TestClient, tmp_path) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"title": "No asset_id"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 422

    def test_missing_title(self, upload_client: TestClient) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "test-asset-01"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 422

    def test_invalid_asset_id_pattern(self, upload_client: TestClient) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "INVALID_ID!", "title": "Test"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 422

    def test_missing_file(self, upload_client: TestClient) -> None:
        response = upload_client.post(
            "/api/staff/assets/upload",
            data={"asset_id": "test-asset-01", "title": "Test"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# TestUploadEndpointFfprobeGate
# ---------------------------------------------------------------------------


class TestUploadEndpointFfprobeGate:
    """422 when the validation gate rejects the file."""

    def test_unsupported_format_returns_422(self, upload_client: TestClient, tmp_path) -> None:
        bad_result = FfprobeResult(
            duration_seconds=30,
            codec_video="wmv2",
            codec_audio=None,
            width_px=640,
            height_px=480,
            bitrate_bps=None,
            format_name="asf",
        )
        with patch("civiccast.schedule.router.run_ffprobe", return_value=bad_result):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "bad-format-01", "title": "Bad Format"},
                files={"file": ("test.wmv", _fake_video_bytes(), "video/x-ms-wmv")},
            )
        assert response.status_code == 422
        assert "wmv2" in response.json()["detail"]
        asset_dir = (tmp_path / "bad-format-01").resolve()
        if asset_dir.exists():
            assert list(asset_dir.iterdir()) == []

    def test_no_video_stream_returns_422(self, upload_client: TestClient, tmp_path) -> None:
        audio_only = FfprobeResult(
            duration_seconds=60,
            codec_video=None,
            codec_audio="mp3",
            width_px=None,
            height_px=None,
            bitrate_bps=None,
            format_name="mp3",
        )
        with patch("civiccast.schedule.router.run_ffprobe", return_value=audio_only):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "audio-only-01", "title": "Audio Only"},
                files={"file": ("test.mp3", _fake_video_bytes(), "audio/mpeg")},
            )
        assert response.status_code == 422
        assert "No video stream" in response.json()["detail"]
        asset_dir = (tmp_path / "audio-only-01").resolve()
        if asset_dir.exists():
            assert list(asset_dir.iterdir()) == []

    def test_store_collision_removes_uploaded_file(self, tmp_path) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.ingest_upload.side_effect = AssetAlreadyExistsError(asset_id="collision-01")
        app.dependency_overrides[get_postgres_store] = lambda: mock_store

        with (
            patch.dict(os.environ, {"CIVICCAST_UPLOAD_DIR": str(tmp_path)}),
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
            TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client,
        ):
            response = client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "collision-01", "title": "Collision"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )

        assert response.status_code == 409
        asset_dir = (tmp_path / "collision-01").resolve()
        if asset_dir.exists():
            assert list(asset_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# TestUploadEndpointHappyPath
# ---------------------------------------------------------------------------


class TestUploadEndpointHappyPath:
    """201 + UploadedAssetResponse on a valid upload."""

    def test_returns_201_with_full_response(self, upload_client: TestClient) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "test-upload-01", "title": "Test Upload"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 201
        body = response.json()
        assert body["asset_id"] == "test-upload-01"
        assert body["state"] == ASSET_STATE_VALIDATED
        assert body["codec_video"] == "h264"
        assert body["codec_audio"] == "aac"
        assert body["width_px"] == 1920
        assert body["height_px"] == 1080
        assert body["duration_seconds"] == 60

    def test_response_has_no_manifest_url(self, upload_client: TestClient) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "test-upload-01", "title": "Test Upload"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert "manifest_url" not in response.json()

    def test_optional_description_accepted(self, upload_client: TestClient) -> None:
        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={
                    "asset_id": "test-upload-01",
                    "title": "Test Upload",
                    "description": "A test video",
                },
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 201

    def test_store_ingest_upload_called_with_correct_args(self, tmp_path) -> None:
        """Verify the router passes the expected kwargs to store.ingest_upload."""
        from civiccast.schedule.router import get_postgres_store as _dep

        app = create_app()
        captured: dict = {}
        mock_store = MagicMock()

        def _capture(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return UploadedAssetResponse(
                asset_id=kwargs["asset_id"],
                title=kwargs["title"],
                description=kwargs.get("description"),
                state=ASSET_STATE_VALIDATED,
                file_path=kwargs["file_path"],
                file_size_bytes=kwargs["file_size_bytes"],
            )

        mock_store.ingest_upload.side_effect = _capture
        mock_store.get_staff_row.return_value = None
        app.dependency_overrides[_dep] = lambda: mock_store

        with (
            patch.dict(os.environ, {"CIVICCAST_UPLOAD_DIR": str(tmp_path)}),
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
            TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client,
        ):
            client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "capture-test-01", "title": "Capture Test"},
                files={"file": ("vid.mp4", _fake_video_bytes(), "video/mp4")},
            )

        assert captured["asset_id"] == "capture-test-01"
        assert captured["title"] == "Capture Test"
        assert captured["ffprobe_result"] is _VALID_FFPROBE_RESULT

    def test_upload_file_writes_run_through_threadpool(self, upload_client: TestClient) -> None:
        calls: list[str] = []

        async def _immediate_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(getattr(func, "__name__", repr(func)))
            return func(*args, **kwargs)

        with (
            patch("civiccast.schedule.router.asyncio.to_thread", side_effect=_immediate_thread),
            patch("civiccast.schedule.router.run_ffprobe", return_value=_VALID_FFPROBE_RESULT),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "threaded-write-01", "title": "Threaded Write"},
                files={"file": ("test.mp4", _fake_video_bytes(), "video/mp4")},
            )

        assert response.status_code == 201
        assert "write" in calls


# ---------------------------------------------------------------------------
# TestUploadEndpointSecurity (audit-team v0.3.0 — ENG-001)
# ---------------------------------------------------------------------------


class TestUploadEndpointSecurity:
    """Locks the path-traversal hardening landed for ENG-001.

    The multipart filename header is client-controlled. The router
    sanitizes it to a basename, strips non-portable characters, and
    confirms the resolved destination is under the asset directory before
    writing. These tests pin all three layers.
    """

    def test_traversal_filename_is_sanitized_to_basename(
        self, upload_client: TestClient, tmp_path
    ) -> None:
        with (
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=_VALID_FFPROBE_RESULT,
            ),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "trav-test-01", "title": "Traversal Test"},
                files={
                    "file": (
                        "../../../../etc/passwd",
                        _fake_video_bytes(),
                        "video/mp4",
                    )
                },
            )
        assert response.status_code == 201
        # The sanitizer must drop directory components and map the result
        # into the per-asset directory. Portable assertions:
        # 1. Exactly one file in the asset_dir, whose parent IS asset_dir.
        # 2. The filename contains no separators or traversal segments.
        # The earlier `not (host_root / "etc" / "passwd").exists()` check
        # was bogus on Linux runners — /etc/passwd is an OS fixture
        # unrelated to whether THIS upload escaped.
        asset_dir = (tmp_path / "trav-test-01").resolve()
        assert asset_dir.is_dir(), "Asset directory was not created."
        files_in_asset_dir = list(asset_dir.iterdir())
        assert len(files_in_asset_dir) == 1, (
            f"Expected exactly one file in asset_dir; got {[f.name for f in files_in_asset_dir]}"
        )
        landed = files_in_asset_dir[0]
        assert landed.parent == asset_dir, f"File landed outside the asset directory: {landed}"
        # No path separators survive the sanitizer.
        assert "/" not in landed.name
        assert "\\" not in landed.name
        # The filename is not a literal "..".
        assert landed.name != ".."

    def test_backslash_traversal_filename_is_sanitized(
        self, upload_client: TestClient, tmp_path
    ) -> None:
        with (
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=_VALID_FFPROBE_RESULT,
            ),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "trav-test-02", "title": "Windows Traversal"},
                files={
                    "file": (
                        r"..\..\..\windows\system32\drivers\hosts",
                        _fake_video_bytes(),
                        "video/mp4",
                    )
                },
            )
        assert response.status_code == 201
        asset_dir = (tmp_path / "trav-test-02").resolve()
        files_in_asset_dir = list(asset_dir.iterdir())
        assert len(files_in_asset_dir) == 1
        # No backslashes survive; the saved filename is one segment.
        assert "\\" not in files_in_asset_dir[0].name
        assert "/" not in files_in_asset_dir[0].name

    def test_filename_with_only_special_chars_falls_back_to_upload(
        self, upload_client: TestClient, tmp_path
    ) -> None:
        with (
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=_VALID_FFPROBE_RESULT,
            ),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "trav-test-03", "title": "Special Chars"},
                files={"file": ("///", _fake_video_bytes(), "video/mp4")},
            )
        assert response.status_code == 201
        asset_dir = (tmp_path / "trav-test-03").resolve()
        files_in_asset_dir = list(asset_dir.iterdir())
        assert len(files_in_asset_dir) == 1
        # The sanitizer falls back to "upload" when everything else is stripped.
        assert files_in_asset_dir[0].name == "upload"

    def test_upload_size_cap_returns_413(self, upload_client: TestClient, tmp_path) -> None:
        # Set a tiny cap and submit something larger.
        with (
            patch.dict(
                os.environ,
                {
                    "CIVICCAST_UPLOAD_DIR": str(tmp_path),
                    "CIVICCAST_UPLOAD_MAX_BYTES": "256",
                },
            ),
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=_VALID_FFPROBE_RESULT,
            ),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "size-test-01", "title": "Size Test"},
                files={
                    "file": (
                        "test.mp4",
                        b"\x00" * 4096,
                        "video/mp4",
                    )
                },
            )
        assert response.status_code == 413
        assert "maximum size" in response.json()["detail"]
        # Partial file must be cleaned up so size-cap rejections don't
        # leave bytes on disk.
        asset_dir = (tmp_path / "size-test-01").resolve()
        if asset_dir.exists():
            assert list(asset_dir.iterdir()) == []
        incoming_dir = (tmp_path / ".incoming").resolve()
        if incoming_dir.exists():
            assert list(incoming_dir.iterdir()) == []

    def test_operator_upload_can_select_the_exact_file_for_private_rehearsal(
        self,
        upload_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        ops_state = tmp_path / "ops-state.json"
        monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(ops_state))
        video = b"operator-selected-rehearsal-media"

        with (
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=_VALID_FFPROBE_RESULT,
            ),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = upload_client.post(
                "/api/staff/assets/upload",
                data={
                    "asset_id": "test-upload-01",
                    "title": "Test Upload",
                    "select_for_rehearsal": "true",
                },
                files={"file": ("test.mp4", video, "video/mp4")},
            )

        assert response.status_code == 201
        selected = json.loads(ops_state.read_text(encoding="utf-8"))["sample_rehearsal_media"]
        assert selected["asset_id"] == "test-upload-01"
        selected_path = Path(selected["file_path"])
        assert selected_path.read_bytes() == video
        assert selected_path.is_relative_to(tmp_path.resolve())
