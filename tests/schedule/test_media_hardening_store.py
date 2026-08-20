# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Store-level tests for 4.0 media-library-hardening (scope item 5).

Covers :class:`civiccast.schedule.store.PostgresAssetStore`'s new surface:
pagination (``list_all_page``), missing-file bookkeeping (``list_broken``),
relink (``relink``), duplicate detection (``list_duplicates``), and the
thumbnail-backfill helpers (``list_missing_thumbnails``,
``set_thumbnail_path``). Uses real small ffmpeg-generated video files for
the hash/relink tests rather than mocking the filesystem, per the domain's
existing convention (see ``tests/schedule/test_ingest.py``).
"""

from __future__ import annotations

import shutil
import subprocess as sp
from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.schedule.ingest import hash_file, run_ffprobe
from civiccast.schedule.models import Asset
from civiccast.schedule.store import AssetNotFoundError, PostgresAssetStore
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


def _seed_asset(session_factory, asset_id: str, **overrides: object) -> None:
    defaults: dict[str, object] = {
        "asset_id": asset_id,
        "title": f"Asset {asset_id}",
        "state": "validated",
        "manifest_url": None,
    }
    defaults.update(overrides)
    with session_factory() as session:
        session.add(Asset(**defaults))
        session.commit()


# ---------------------------------------------------------------------------
# TestListAllPage
# ---------------------------------------------------------------------------


class TestListAllPage:
    def test_empty_store_returns_empty_page_and_zero_total(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        rows, total = store.list_all_page()
        assert rows == []
        assert total == 0

    def test_total_count_reflects_full_row_count_regardless_of_limit(self, session_factory) -> None:
        for i in range(5):
            _seed_asset(session_factory, f"asset-{i}")
        store = PostgresAssetStore(session_factory)

        rows, total = store.list_all_page(limit=2, offset=0)

        assert len(rows) == 2
        assert total == 5

    def test_offset_advances_through_pages(self, session_factory) -> None:
        for i in range(5):
            _seed_asset(session_factory, f"asset-{i}")
        store = PostgresAssetStore(session_factory)

        page1, _ = store.list_all_page(limit=2, offset=0)
        page2, _ = store.list_all_page(limit=2, offset=2)
        page3, _ = store.list_all_page(limit=2, offset=4)

        ids = [row.asset_id for row in page1 + page2 + page3]
        assert len(ids) == len(set(ids)) == 5  # no overlap, no gaps

    def test_list_all_unbounded_method_is_unaffected(self, session_factory) -> None:
        """The pre-existing list_all() stays unbounded — other callers
        (civiccast.publish.router) rely on that and are out of scope here."""
        for i in range(3):
            _seed_asset(session_factory, f"asset-{i}")
        store = PostgresAssetStore(session_factory)

        assert len(store.list_all()) == 3


# ---------------------------------------------------------------------------
# TestListBroken
# ---------------------------------------------------------------------------


class TestListBroken:
    def test_only_missing_status_assets_are_returned(self, session_factory) -> None:
        _seed_asset(session_factory, "ok-1", file_status="ok")
        _seed_asset(session_factory, "missing-1", file_status="missing")
        _seed_asset(session_factory, "relinked-1", file_status="relinked")

        store = PostgresAssetStore(session_factory)
        broken = store.list_broken()

        assert [row.asset_id for row in broken] == ["missing-1"]

    def test_ordered_oldest_flagged_first(self, session_factory) -> None:
        older = datetime(2026, 1, 1, tzinfo=UTC)
        newer = datetime(2026, 6, 1, tzinfo=UTC)
        _seed_asset(
            session_factory, "flagged-later", file_status="missing", file_status_checked_at=newer
        )
        _seed_asset(
            session_factory, "flagged-first", file_status="missing", file_status_checked_at=older
        )

        store = PostgresAssetStore(session_factory)
        broken = store.list_broken()

        assert [row.asset_id for row in broken] == ["flagged-first", "flagged-later"]


# ---------------------------------------------------------------------------
# TestRelink
# ---------------------------------------------------------------------------


class TestRelink:
    def test_raises_when_asset_missing(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        from civiccast.schedule.ingest import FfprobeResult

        with pytest.raises(AssetNotFoundError):
            store.relink(
                "nonexistent",
                new_file_path="/tmp/x.mp4",
                ffprobe_result=FfprobeResult(
                    duration_seconds=2,
                    codec_video="h264",
                    codec_audio=None,
                    width_px=320,
                    height_px=240,
                    bitrate_bps=None,
                    format_name="mp4",
                ),
                content_hash=None,
            )

    @_FFMPEG_SKIP
    def test_relink_updates_path_status_and_ffprobe_fields(
        self, session_factory, tmp_path: Path
    ) -> None:
        video = _generate_video(tmp_path, "replacement.mp4")
        probe = run_ffprobe(video)
        digest = hash_file(video)

        _seed_asset(
            session_factory,
            "asset-1",
            file_path=str(tmp_path / "gone.mp4"),
            file_status="missing",
            duration_seconds=2,
            codec_video="h264",
            version=1,
        )
        store = PostgresAssetStore(session_factory)

        result = store.relink(
            "asset-1",
            new_file_path=str(video),
            ffprobe_result=probe,
            content_hash=digest,
        )

        assert result.file_path == str(video)
        assert result.file_status == "relinked"
        assert result.file_status_checked_at is not None
        assert result.duration_seconds == probe.duration_seconds
        assert result.codec_video == probe.codec_video
        assert result.content_hash == digest
        assert result.version == 2  # bumped like update_metadata does

    def test_relink_preserves_prior_hash_when_none_given(self, session_factory) -> None:
        from civiccast.schedule.ingest import FfprobeResult

        _seed_asset(session_factory, "asset-1", content_hash="sha256:" + "a" * 64)
        store = PostgresAssetStore(session_factory)

        result = store.relink(
            "asset-1",
            new_file_path="/tmp/new.mp4",
            ffprobe_result=FfprobeResult(
                duration_seconds=2,
                codec_video="h264",
                codec_audio=None,
                width_px=320,
                height_px=240,
                bitrate_bps=None,
                format_name="mp4",
            ),
            content_hash=None,
        )

        assert result.content_hash == "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# TestListDuplicates
# ---------------------------------------------------------------------------


class TestListDuplicates:
    def test_no_duplicates_when_hashes_differ(self, session_factory) -> None:
        _seed_asset(session_factory, "a", content_hash="sha256:" + "a" * 64)
        _seed_asset(session_factory, "b", content_hash="sha256:" + "b" * 64)

        store = PostgresAssetStore(session_factory)
        assert store.list_duplicates() == []

    def test_groups_assets_sharing_a_hash(self, session_factory) -> None:
        shared = "sha256:" + "c" * 64
        _seed_asset(session_factory, "dup-a", content_hash=shared)
        _seed_asset(session_factory, "dup-b", content_hash=shared)
        _seed_asset(session_factory, "unique", content_hash="sha256:" + "d" * 64)

        store = PostgresAssetStore(session_factory)
        groups = store.list_duplicates()

        assert len(groups) == 1
        assert {row.asset_id for row in groups[0]} == {"dup-a", "dup-b"}

    def test_null_hash_assets_are_never_grouped(self, session_factory) -> None:
        _seed_asset(session_factory, "no-hash-1", content_hash=None)
        _seed_asset(session_factory, "no-hash-2", content_hash=None)

        store = PostgresAssetStore(session_factory)
        assert store.list_duplicates() == []

    def test_three_way_duplicate_forms_one_group_of_three(self, session_factory) -> None:
        shared = "sha256:" + "e" * 64
        for asset_id in ("x", "y", "z"):
            _seed_asset(session_factory, asset_id, content_hash=shared)

        store = PostgresAssetStore(session_factory)
        groups = store.list_duplicates()

        assert len(groups) == 1
        assert len(groups[0]) == 3


# ---------------------------------------------------------------------------
# TestThumbnailBackfillHelpers
# ---------------------------------------------------------------------------


class TestThumbnailBackfillHelpers:
    def test_list_missing_thumbnails_excludes_assets_without_a_file(self, session_factory) -> None:
        _seed_asset(session_factory, "no-file", file_path=None)
        store = PostgresAssetStore(session_factory)
        assert store.list_missing_thumbnails() == []

    def test_list_missing_thumbnails_excludes_assets_that_already_have_one(
        self, session_factory
    ) -> None:
        _seed_asset(
            session_factory,
            "has-thumb",
            file_path="/data/has-thumb/x.mp4",
            thumbnail_path="/data/has-thumb/thumbnail.jpg",
        )
        store = PostgresAssetStore(session_factory)
        assert store.list_missing_thumbnails() == []

    def test_list_missing_thumbnails_finds_assets_needing_backfill(self, session_factory) -> None:
        _seed_asset(
            session_factory, "needs-thumb", file_path="/data/needs-thumb/x.mp4", thumbnail_path=None
        )
        store = PostgresAssetStore(session_factory)
        assert [row.asset_id for row in store.list_missing_thumbnails()] == ["needs-thumb"]

    def test_set_thumbnail_path_persists(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-1", file_path="/data/asset-1/x.mp4")
        store = PostgresAssetStore(session_factory)

        store.set_thumbnail_path("asset-1", "/data/asset-1/thumbnail.jpg")

        row = store.get_staff_row("asset-1")
        assert row is not None
        assert row.thumbnail_path == "/data/asset-1/thumbnail.jpg"

    def test_set_thumbnail_path_is_a_noop_for_missing_asset(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        store.set_thumbnail_path("nonexistent", "/data/nonexistent/thumbnail.jpg")  # no raise
