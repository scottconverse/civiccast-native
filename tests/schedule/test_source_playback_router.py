# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Focused contract tests for scoped source and packaged-media playback."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import civiccast.schedule.router as schedule_router
from civiccast.app import create_app
from civiccast.live.router import get_live_finalization_worker, get_recording_target_store
from civiccast.schedule.models import StaffAssetRow
from civiccast.schedule.router import get_postgres_store


@pytest.fixture
def playback_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, dict[str, StaffAssetRow], Path]]:
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        "records-token:records-user:Records Clerk:records_clerk",
    )
    rows: dict[str, StaffAssetRow] = {}
    postgres_store = SimpleNamespace(get_staff_row=lambda asset_id: rows.get(asset_id))
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: postgres_store
    app.dependency_overrides[get_recording_target_store] = lambda: None
    with TestClient(
        app,
        client=("127.0.0.1", 50000),
        headers={"Authorization": "Bearer records-token"},
    ) as client:
        yield client, rows, upload_root


def _asset(asset_id: str, file_path: Path, **updates: object) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title=f"Meeting {asset_id}",
        state="recorded",
        file_path=str(file_path),
        trim_in_seconds=12.5,
        **updates,
    )


def test_grant_streams_source_with_real_range_and_role_scoped_cookie(
    playback_context: tuple[TestClient, dict[str, StaffAssetRow], Path],
) -> None:
    client, rows, upload_root = playback_context
    source = upload_root / "meeting-15.mp4"
    source.write_bytes(b"0123456789")
    rows["meeting-15"] = _asset("meeting-15", source)

    denied_without_cookie = client.get("/media/staff-source/meeting-15/source")
    assert denied_without_cookie.status_code == 401

    response = client.post("/api/staff/assets/meeting-15/playback-grant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["url"] == "/media/staff-source/meeting-15/source"
    assert payload["packaged_url"] is None
    assert payload["playback_kind"] == "source"
    assert payload["source_content_type"] == "video/mp4"
    assert payload["source_offset_seconds"] == 0
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/media/staff-source/meeting-15/" in cookie
    assert "max-age=900" in cookie
    assert "secure" not in cookie

    ranged = client.get(payload["url"], headers={"Range": "bytes=2-5"})

    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    assert ranged.content == b"2345"
    assert ranged.headers["cache-control"] == "private, no-store"


def test_grant_refuses_paths_outside_configured_roots_and_missing_sources(
    playback_context: tuple[TestClient, dict[str, StaffAssetRow], Path],
    tmp_path: Path,
) -> None:
    client, rows, _upload_root = playback_context
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    rows["outside-asset"] = _asset("outside-asset", outside)

    outside_response = client.post("/api/staff/assets/outside-asset/playback-grant")
    assert outside_response.status_code == 409

    missing = tmp_path / "uploads" / "missing.mp4"
    rows["missing-asset"] = _asset("missing-asset", missing)
    missing_response = client.post("/api/staff/assets/missing-asset/playback-grant")
    assert missing_response.status_code == 404


def test_cookie_is_expiring_and_hls_manifest_and_segments_are_asset_scoped(
    playback_context: tuple[TestClient, dict[str, StaffAssetRow], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rows, upload_root = playback_context
    asset_id = "meeting-16"
    source = upload_root / "meeting-16.mp4"
    source.write_bytes(b"source")
    package_root = upload_root / ".civiccast-packages" / asset_id
    rendition = package_root / "720p"
    rendition.mkdir(parents=True)
    (package_root / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\n720p/playlist.m3u8\n",
        encoding="utf-8",
    )
    (rendition / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXTINF:4.0,\nseg000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    (rendition / "seg000.ts").write_bytes(b"segment-data")
    rows[asset_id] = _asset(
        asset_id,
        source,
        manifest_url=f"/media/vod/{asset_id}/playlist.m3u8",
    )
    marker = schedule_router._package_preview_marker_path(asset_id, package_root.parent)
    marker.write_text(
        json.dumps(
            {
                "asset_id": asset_id,
                "source_path": str(source.resolve()),
                "source_size_bytes": source.stat().st_size,
                "source_mtime_ns": source.stat().st_mtime_ns,
                "trim_in_seconds": rows[asset_id].trim_in_seconds,
                "trim_out_seconds": rows[asset_id].trim_out_seconds,
            }
        ),
        encoding="utf-8",
    )

    response = client.post(f"/api/staff/assets/{asset_id}/playback-grant")
    assert response.status_code == 200
    payload = response.json()
    packaged_url = payload["packaged_url"]
    assert packaged_url == f"/media/staff-source/{asset_id}/hls/playlist.m3u8"
    assert payload["playback_kind"] == "hls"
    assert payload["source_offset_seconds"] == 12.5

    manifest = client.get(packaged_url)
    assert manifest.status_code == 200
    assert "720p/playlist.m3u8" in manifest.text
    segment = client.get(f"/media/staff-source/{asset_id}/hls/720p/seg000.ts")
    assert segment.status_code == 200
    assert segment.content == b"segment-data"
    traversal = client.get(f"/media/staff-source/{asset_id}/hls/../../outside.mp4")
    assert traversal.status_code == 404

    rows[asset_id] = rows[asset_id].model_copy(update={"trim_in_seconds": 13.0})
    stale = client.post(f"/api/staff/assets/{asset_id}/playback-grant")
    assert stale.status_code == 200
    assert stale.json()["packaged_url"] is None

    expiry = schedule_router._source_playback_now() + timedelta(minutes=16)
    monkeypatch.setattr(schedule_router, "_source_playback_now", lambda: expiry)
    expired = client.get(payload["url"])
    assert expired.status_code == 401


def test_finalized_transport_stream_uses_only_the_current_local_package(
    playback_context: tuple[TestClient, dict[str, StaffAssetRow], Path],
) -> None:
    client, rows, upload_root = playback_context
    asset_id = "recorded-ts"
    source = upload_root / "recordings" / "live-session-1.ts"
    source.parent.mkdir()
    source.write_bytes(b"transport-stream-source")
    package_root = source.parent / "live-session-1-hls"
    package_root.mkdir()
    manifest = package_root / "playlist.m3u8"
    manifest.write_text("#EXTM3U\n#EXTINF:4.0,\nseg000.ts\n#EXT-X-ENDLIST\n", encoding="utf-8")
    (package_root / "seg000.ts").write_bytes(b"packaged-transport-stream")
    rows[asset_id] = _asset(
        asset_id,
        source,
        source_live_session_id="live-session-1",
    )
    finalization = SimpleNamespace(
        get_status=lambda session_id: SimpleNamespace(
            state="completed",
            asset_id=asset_id,
            local_package_manifest_path=str(manifest),
            packaged_trim_in_seconds=12.5,
            packaged_trim_out_seconds=None,
        )
    )
    client.app.dependency_overrides[get_live_finalization_worker] = lambda: finalization

    response = client.post(f"/api/staff/assets/{asset_id}/playback-grant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_content_type"] == "video/mp2t"
    assert payload["playback_kind"] == "hls"
    assert payload["source_offset_seconds"] == 12.5
    assert payload["packaged_url"] == f"/media/staff-source/{asset_id}/hls/playlist.m3u8"
    manifest_response = client.get(payload["packaged_url"])
    assert manifest_response.status_code == 200
    segment = client.get(
        f"/media/staff-source/{asset_id}/hls/seg000.ts",
        headers={"Range": "bytes=0-7"},
    )
    assert segment.status_code == 206
    assert segment.headers["content-type"].startswith("video/mp2t")
    assert segment.content == b"packaged"

    finalization.get_status = lambda session_id: SimpleNamespace(
        state="completed",
        asset_id=asset_id,
        local_package_manifest_path=str(manifest),
        packaged_trim_in_seconds=11.0,
        packaged_trim_out_seconds=None,
    )
    stale = client.post(f"/api/staff/assets/{asset_id}/playback-grant")
    assert stale.status_code == 200
    assert stale.json()["packaged_url"] is None


def test_remote_http_grant_is_refused_but_https_cookie_is_secure(
    playback_context: tuple[TestClient, dict[str, StaffAssetRow], Path],
) -> None:
    _client, rows, upload_root = playback_context
    source = upload_root / "remote.mp4"
    source.write_bytes(b"remote")
    rows["remote-media"] = _asset("remote-media", source)
    app = _client.app
    headers = {"Authorization": "Bearer records-token"}

    with TestClient(
        app,
        base_url="http://station.example",
        client=("192.0.2.25", 43120),
        headers=headers,
    ) as remote_http:
        refused = remote_http.post("/api/staff/assets/remote-media/playback-grant")
    assert refused.status_code == 403

    with TestClient(
        app,
        base_url="https://station.example",
        client=("192.0.2.25", 43120),
        headers=headers,
    ) as remote_https:
        granted = remote_https.post("/api/staff/assets/remote-media/playback-grant")
    assert granted.status_code == 200
    assert "secure" in granted.headers["set-cookie"].lower()
