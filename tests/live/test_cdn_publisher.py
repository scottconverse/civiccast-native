# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the live CDN publish path (LiveCDNPublisher)."""

from __future__ import annotations

from pathlib import Path

from civiccast.live.cdn_publisher import LiveCDNPublisher


class _RecordingAdapter:
    """A CDNAdapter that records upload/delete order for invariant assertions."""

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.deletes: list[str] = []

    def upload_file(self, local_path: Path, remote_key: str) -> str:
        self.uploads.append(remote_key)
        return f"https://cdn.example.org/{remote_key}"

    def delete_file(self, remote_key: str) -> None:
        self.deletes.append(remote_key)

    def public_url(self, remote_key: str) -> str:
        return f"https://cdn.example.org/{remote_key}"

    def health_check(self) -> bool:
        return True


def _write_live(directory: Path, segments: list[str], *, manifest: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in segments:
        (directory / name).write_bytes(b"x" * 64)
    if manifest:
        (directory / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")


def test_sync_uploads_segments_first_then_manifest_last(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts", "seg000000001.ts"])
    rec = _RecordingAdapter()

    url = LiveCDNPublisher("gov-ch12", live, rec).sync()

    # segments first, manifest strictly last
    assert rec.uploads == [
        "live/gov-ch12/seg000000000.ts",
        "live/gov-ch12/seg000000001.ts",
        "live/gov-ch12/playlist.m3u8",
    ]
    assert url == "https://cdn.example.org/live/gov-ch12/playlist.m3u8"


def test_sync_returns_none_before_the_sink_writes_a_manifest(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts"], manifest=False)
    assert LiveCDNPublisher("c", live, _RecordingAdapter()).sync() is None


def test_second_sync_only_uploads_new_segments(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts"])
    rec = _RecordingAdapter()
    pub = LiveCDNPublisher("c", live, rec)
    pub.sync()
    rec.uploads.clear()

    (live / "seg000000001.ts").write_bytes(b"y" * 64)
    pub.sync()

    # the already-uploaded seg0 is skipped; only the new seg + manifest go up
    assert rec.uploads == ["live/c/seg000000001.ts", "live/c/playlist.m3u8"]


def test_rolled_out_segment_is_evicted_from_the_cdn(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts", "seg000000001.ts"])
    rec = _RecordingAdapter()
    pub = LiveCDNPublisher("c", live, rec)
    pub.sync()

    # window rolls: seg0 drops locally, seg2 appears
    (live / "seg000000000.ts").unlink()
    (live / "seg000000002.ts").write_bytes(b"z" * 64)
    rec.uploads.clear()
    pub.sync()

    assert "live/c/seg000000002.ts" in rec.uploads
    assert rec.deletes == ["live/c/seg000000000.ts"]


def test_manifest_url_points_at_the_cdn_key(tmp_path: Path) -> None:
    pub = LiveCDNPublisher("gov-ch12", tmp_path, _RecordingAdapter())
    assert pub.manifest_url() == "https://cdn.example.org/live/gov-ch12/playlist.m3u8"


def test_evict_all_deletes_the_manifest_first_then_all_segments(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts", "seg000000001.ts"])
    rec = _RecordingAdapter()
    pub = LiveCDNPublisher("c", live, rec)
    pub.sync()
    rec.deletes.clear()

    pub.evict_all()

    assert rec.deletes[0] == "live/c/playlist.m3u8"  # manifest gone first
    assert set(rec.deletes) == {
        "live/c/playlist.m3u8",
        "live/c/seg000000000.ts",
        "live/c/seg000000001.ts",
    }


def test_sync_via_the_real_stub_adapter_lands_files(tmp_path: Path) -> None:
    from civiccast.stream.cdn.stub import StubCDNAdapter

    live = tmp_path / "live"
    _write_live(live, ["seg000000000.ts"])
    cdn_root = tmp_path / "cdn"

    url = LiveCDNPublisher("gov-ch12", live, StubCDNAdapter(cdn_root)).sync()

    assert (cdn_root / "live" / "gov-ch12" / "seg000000000.ts").is_file()
    assert (cdn_root / "live" / "gov-ch12" / "playlist.m3u8").is_file()
    assert url == (cdn_root / "live" / "gov-ch12" / "playlist.m3u8").as_uri()
