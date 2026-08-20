# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Router tests for 4.0 media-library-hardening (scope item 5).

Covers: pagination on ``GET /api/staff/assets``, ``GET /api/staff/assets
/broken``, ``POST /api/staff/assets/{id}/relink``, ``GET /api/staff/assets
/duplicates``, and ``GET /api/staff/assets/{id}/thumbnail``. Follows
``tests/schedule/test_staff_list_router.py``'s TestClient + dependency-
override style. Real ffmpeg-generated files back the relink/thumbnail
happy-path tests (skipped if ffmpeg is absent), per the domain's existing
convention.
"""

from __future__ import annotations

import os
import shutil
import subprocess as sp
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import ASSET_STATE_VALIDATED, StaffAssetRow
from civiccast.schedule.router import get_postgres_store
from civiccast.schedule.store import AssetNotFoundError
from civiccast.stream._ffmpeg import resolve_h264_encoder

_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
_FFMPEG_SKIP = pytest.mark.skipif(
    not _FFMPEG_AVAILABLE, reason="ffmpeg not on PATH; integration test skipped"
)


def _generate_video(tmp_path: Path, name: str, *, duration: int = 2) -> Path:
    path = tmp_path / name
    sp.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={duration}:size=320x240:rate=10",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


def _row(asset_id: str, **overrides: object) -> StaffAssetRow:
    defaults: dict[str, object] = {
        "asset_id": asset_id,
        "title": f"Asset {asset_id}",
        "state": ASSET_STATE_VALIDATED,
    }
    defaults.update(overrides)
    return StaffAssetRow(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def client_with_mock_store() -> Iterator[tuple[TestClient, MagicMock]]:
    app = create_app()
    mock_store = MagicMock()
    app.dependency_overrides[get_postgres_store] = lambda: mock_store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c, mock_store


# ---------------------------------------------------------------------------
# TestPagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_default_limit_and_offset_are_applied(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.list_all_page.return_value = ([], 0)

        response = client.get("/api/staff/assets")

        assert response.status_code == 200
        mock_store.list_all_page.assert_called_once_with(limit=50, offset=0)
        assert response.headers["X-Total-Count"] == "0"

    def test_custom_limit_and_offset_are_forwarded(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.list_all_page.return_value = ([_row("a")], 30)

        response = client.get("/api/staff/assets?limit=10&offset=20")

        assert response.status_code == 200
        mock_store.list_all_page.assert_called_once_with(limit=10, offset=20)
        assert response.headers["X-Total-Count"] == "30"

    def test_limit_above_max_is_rejected(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, _ = client_with_mock_store
        response = client.get("/api/staff/assets?limit=501")
        assert response.status_code == 422

    def test_negative_offset_is_rejected(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, _ = client_with_mock_store
        response = client.get("/api/staff/assets?offset=-1")
        assert response.status_code == 422

    def test_response_body_is_still_a_bare_array(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        """Portal client (listStaffAssets) and its e2e specs assume a bare
        array — the envelope must not change shape."""
        client, mock_store = client_with_mock_store
        mock_store.list_all_page.return_value = ([_row("a"), _row("b")], 2)

        response = client.get("/api/staff/assets")

        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 2


# ---------------------------------------------------------------------------
# TestListBrokenEndpoint
# ---------------------------------------------------------------------------


class TestListBrokenEndpoint:
    def test_returns_broken_assets(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.list_broken.return_value = [_row("missing-1", file_status="missing")]

        response = client.get("/api/staff/assets/broken")

        assert response.status_code == 200
        body = response.json()
        assert [row["asset_id"] for row in body] == ["missing-1"]

    def test_broken_route_does_not_shadow_asset_id_lookup(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        """GET /assets/broken must hit list_broken(), never
        get_staff_row("broken") — this pins the route-ordering fix."""
        client, mock_store = client_with_mock_store
        mock_store.list_broken.return_value = []
        mock_store.get_staff_row.return_value = None

        response = client.get("/api/staff/assets/broken")

        assert response.status_code == 200
        mock_store.list_broken.assert_called_once()
        mock_store.get_staff_row.assert_not_called()


# ---------------------------------------------------------------------------
# TestListDuplicatesEndpoint
# ---------------------------------------------------------------------------


class TestListDuplicatesEndpoint:
    def test_returns_duplicate_groups(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        shared = "sha256:" + "a" * 64
        mock_store.list_duplicates.return_value = [
            [_row("dup-a", content_hash=shared), _row("dup-b", content_hash=shared)]
        ]

        response = client.get("/api/staff/assets/duplicates")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert {row["asset_id"] for row in body[0]} == {"dup-a", "dup-b"}

    def test_duplicates_route_does_not_shadow_asset_id_lookup(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.list_duplicates.return_value = []
        mock_store.get_staff_row.return_value = None

        response = client.get("/api/staff/assets/duplicates")

        assert response.status_code == 200
        mock_store.list_duplicates.assert_called_once()
        mock_store.get_staff_row.assert_not_called()


# ---------------------------------------------------------------------------
# TestRelinkEndpoint
# ---------------------------------------------------------------------------


def _upload_env(root: Path):  # type: ignore[no-untyped-def]
    """Context manager pinning CIVICCAST_UPLOAD_DIR to ``root``.

    The relink endpoint requires the upload root to be configured (same
    503 contract as the upload handler) so the containment check has a
    boundary to enforce.
    """
    return patch.dict(os.environ, {"CIVICCAST_UPLOAD_DIR": str(root)})


class TestRelinkEndpoint:
    def test_404_when_asset_does_not_exist(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = None

        with _upload_env(tmp_path):
            response = client.post(
                "/api/staff/assets/nonexistent/relink",
                json={"new_file_path": str(tmp_path / "x.mp4")},
            )

        assert response.status_code == 404

    def test_503_when_upload_dir_not_configured(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        """Without CIVICCAST_UPLOAD_DIR there is no containment boundary to
        enforce, so relink refuses outright — same contract as upload."""
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = _row("asset-1")
        env = {k: v for k, v in os.environ.items() if k != "CIVICCAST_UPLOAD_DIR"}

        with patch.dict(os.environ, env, clear=True):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(tmp_path / "x.mp4")},
            )

        assert response.status_code == 503
        mock_store.relink.assert_not_called()

    def test_404_when_candidate_file_does_not_exist(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=60, codec_video="h264"
        )

        with _upload_env(tmp_path):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(tmp_path / "does-not-exist.mp4")},
            )

        assert response.status_code == 404
        mock_store.relink.assert_not_called()

    # -- Path containment (adversarial-review blocker) ---------------------

    def test_422_when_path_is_outside_upload_root(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        """A real, readable file OUTSIDE the upload root must be rejected
        before ffprobe ever runs — a staff token must not be able to
        repoint an asset at arbitrary files on the box or mounted shares
        (the thumbnails-backfill command writes a sibling thumbnail.jpg
        next to file_path, so escaping the root is an attacker-directed
        write outside the media root)."""
        client, mock_store = client_with_mock_store
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"real bytes, wrong place")
        mock_store.get_staff_row.return_value = _row("asset-1")

        with _upload_env(root):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(outside)},
            )

        assert response.status_code == 422
        assert "outside the upload directory" in response.json()["detail"]
        mock_store.relink.assert_not_called()

    def test_422_when_symlink_inside_root_points_outside(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        """resolve() runs BEFORE the containment check (same order as the
        upload handler), so a symlink that lives inside the root but
        targets a file outside it cannot smuggle the target in."""
        client, mock_store = client_with_mock_store
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"escape target")
        link = root / "link.mp4"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation not permitted (Windows without privilege)")
        mock_store.get_staff_row.return_value = _row("asset-1")

        with _upload_env(root):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(link)},
            )

        assert response.status_code == 422
        mock_store.relink.assert_not_called()

    def test_422_when_dotdot_traversal_escapes_root(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"escape target")
        traversal = str(root / ".." / "outside.mp4")
        mock_store.get_staff_row.return_value = _row("asset-1")

        with _upload_env(root):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": traversal},
            )

        assert response.status_code == 422
        mock_store.relink.assert_not_called()

    # -----------------------------------------------------------------------

    @_FFMPEG_SKIP
    def test_409_when_duration_outside_tolerance(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        # Recorded duration is 60s; tolerance is max(5, 60*0.02)=5s. The
        # real generated file is ~2s — nowhere close.
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=60, codec_video="h264"
        )
        candidate = _generate_video(tmp_path, "candidate.mp4", duration=2)

        with _upload_env(tmp_path):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(candidate)},
            )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["expected_duration_seconds"] == 60
        assert detail["actual_duration_seconds"] == 2
        mock_store.relink.assert_not_called()

    @_FFMPEG_SKIP
    def test_409_when_codec_differs(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        candidate = _generate_video(tmp_path, "candidate.mp4", duration=2)
        # h264 candidate, but the asset is recorded as hevc.
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=2, codec_video="hevc"
        )

        with _upload_env(tmp_path):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(candidate)},
            )

        assert response.status_code == 409
        mock_store.relink.assert_not_called()

    @_FFMPEG_SKIP
    def test_relinks_when_candidate_matches_within_tolerance(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        candidate = _generate_video(tmp_path, "candidate.mp4", duration=2)
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=2, codec_video="h264"
        )
        mock_store.relink.return_value = _row(
            "asset-1", duration_seconds=2, codec_video="h264", file_status="relinked"
        )

        with _upload_env(tmp_path):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(candidate)},
            )

        assert response.status_code == 200
        assert response.json()["file_status"] == "relinked"
        mock_store.relink.assert_called_once()
        call_kwargs = mock_store.relink.call_args.kwargs
        # The persisted path is the RESOLVED candidate (symlinks followed).
        assert call_kwargs["new_file_path"] == str(candidate.resolve())

    def test_skips_comparison_fields_that_have_never_been_probed(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        """An asset with no recorded duration/codec (legacy manifest-only
        row) has nothing to compare against, so the gate can't reject it
        on those grounds — only containment, file-existence, and a
        readable ffprobe are required."""
        client, mock_store = client_with_mock_store
        candidate = tmp_path / "candidate.mp4"
        candidate.write_bytes(b"placeholder")  # never actually probed (mocked below)
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=None, codec_video=None
        )
        mock_store.relink.return_value = _row("asset-1", file_status="relinked")

        with (
            _upload_env(tmp_path),
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=FfprobeResult(
                    duration_seconds=99,
                    codec_video="vp9",
                    codec_audio=None,
                    width_px=320,
                    height_px=240,
                    bitrate_bps=None,
                    format_name="webm",
                ),
            ),
        ):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(candidate)},
            )

        assert response.status_code == 200
        mock_store.relink.assert_called_once()

    def test_asset_not_found_race_surfaces_as_404(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        candidate = tmp_path / "candidate.mp4"
        candidate.write_bytes(b"placeholder")
        mock_store.get_staff_row.return_value = _row(
            "asset-1", duration_seconds=None, codec_video=None
        )
        mock_store.relink.side_effect = AssetNotFoundError(asset_id="asset-1")

        with (
            _upload_env(tmp_path),
            patch(
                "civiccast.schedule.router.run_ffprobe",
                return_value=FfprobeResult(
                    duration_seconds=2,
                    codec_video="h264",
                    codec_audio=None,
                    width_px=320,
                    height_px=240,
                    bitrate_bps=None,
                    format_name="mp4",
                ),
            ),
        ):
            response = client.post(
                "/api/staff/assets/asset-1/relink",
                json={"new_file_path": str(candidate)},
            )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestThumbnailEndpoint
# ---------------------------------------------------------------------------


class TestThumbnailEndpoint:
    def test_404_when_asset_has_no_thumbnail(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = _row("asset-1", thumbnail_path=None)

        response = client.get("/api/staff/assets/asset-1/thumbnail")

        assert response.status_code == 404

    def test_404_when_asset_does_not_exist(
        self, client_with_mock_store: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = None

        response = client.get("/api/staff/assets/nonexistent/thumbnail")

        assert response.status_code == 404

    def test_404_when_thumbnail_path_recorded_but_file_gone(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        mock_store.get_staff_row.return_value = _row(
            "asset-1", thumbnail_path=str(tmp_path / "gone.jpg")
        )

        response = client.get("/api/staff/assets/asset-1/thumbnail")

        assert response.status_code == 404

    def test_serves_thumbnail_with_cache_headers(
        self, client_with_mock_store: tuple[TestClient, MagicMock], tmp_path: Path
    ) -> None:
        client, mock_store = client_with_mock_store
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"\xff\xd8fake jpeg bytes")
        mock_store.get_staff_row.return_value = _row("asset-1", thumbnail_path=str(thumb))

        response = client.get("/api/staff/assets/asset-1/thumbnail")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "max-age=31536000" in response.headers["cache-control"]
        assert response.content == b"\xff\xd8fake jpeg bytes"
