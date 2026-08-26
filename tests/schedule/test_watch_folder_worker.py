# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S7 watch-folder poll daemon tests.

tmp-dir-based end-to-end coverage: real files on a real filesystem, a real
SQLite database, and (where ffmpeg/ffprobe are on PATH) real generated
video content run through the real ffprobe ingest pipeline -- not mocks of
that pipeline. Mirrors ``tests/schedule/test_media_lifecycle_worker.py``'s
fixture shape (SQLite session-factory, ``run_once``) but needs a real
file-backed database with a per-checkout connection pool (see the
``engine`` fixture below) since :meth:`WatchFolderWorker.run_once` fans
folder scans out across real OS threads.
"""

from __future__ import annotations

import shutil
import subprocess as sp
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.media_lifecycle_models import (
    FILE_STATE_INGESTED,
    FILE_STATE_PENDING,
    PROCESSED_FILE_MODE_MOVE_TO_SUBFOLDER,
    WATCH_FOLDER_HEALTH_DEGRADED,
    WATCH_FOLDER_HEALTH_OK,
    WATCH_FOLDER_HEALTH_UNKNOWN,
    MediaIngestJob,
    WatchFolderConfig,
    WatchFolderFileState,
)
from civiccast.schedule.models import Asset
from civiccast.schedule.watch_folder_worker import WatchFolderWorker, WatchFolderWorkerSettings
from civiccast.stream._ffmpeg import resolve_h264_encoder

_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_FFMPEG_SKIP = pytest.mark.skipif(
    not _FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not on PATH; integration test skipped"
)


def _generate_test_video(dest: Path, *, duration: int = 2, size: str = "320x240") -> Path:
    """Real H.264 video via ffmpeg lavfi, matching tests/schedule/test_ingest.py's helper."""
    sp.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={duration}:size={size}:rate=10",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    # File-backed (not :memory:), default pool (NOT StaticPool): run_once
    # fans folder scans out across real OS threads (ThreadPoolExecutor),
    # each opening its own session concurrently. A bare sqlite:///:memory:
    # engine would give each connection an empty, unrelated database.
    # StaticPool hands every checkout the SAME single sqlite3.Connection
    # object, so two folders' threads doing DB work at literally the same
    # instant share one live connection -- observed as rare, non-
    # reproducible-in-isolation flakes (a lost row in one thread's result)
    # when this suite ran alongside other tests. The default pool gives
    # concurrent checkouts distinct connections against the same file,
    # which is what genuinely concurrent access needs;
    # check_same_thread=False is still required because a pooled
    # connection can be reused by a different thread on a later checkout.
    db_path = tmp_path / "watch-folder-worker-test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        # timeout=30: sqlite3's busy-wait, not SQLAlchemy's own timeout.
        # Separate real connections concurrently writing to the same file
        # need this -- without it, SQLite's default ~5s busy timeout (and
        # the default rollback journal, not WAL) makes a genuine "two
        # threads insert at literally the same moment" collision surface
        # as OperationalError("database is locked") instead of one writer
        # just waiting briefly for the other's transaction to finish.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _make_config(engine: Engine, **overrides: object) -> WatchFolderConfig:
    defaults: dict[str, object] = {
        "monitor_path": "unset",
        "enabled": True,
        "settle_window_seconds": 10,
        "poll_interval_seconds": 1,
        "processed_file_mode": "leave_with_ledger",
        "processed_subfolder_name": "processed",
    }
    defaults.update(overrides)
    with Session(bind=engine) as session:
        config = WatchFolderConfig(**defaults)  # type: ignore[arg-type]
        session.add(config)
        session.commit()
        session.refresh(config)
        return config


def _worker(
    session_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    *,
    max_concurrent_folders: int = 2,
    max_files_per_pass: int = 25,
) -> WatchFolderWorker:
    settings = WatchFolderWorkerSettings(
        mode="inline",
        poll_seconds=1.0,
        upload_dir=str(tmp_path / "uploads"),
        max_concurrent_folders=max_concurrent_folders,
        max_files_ingested_per_pass_per_folder=max_files_per_pass,
    )
    return WatchFolderWorker(session_factory, settings=settings)


def _refresh_config(engine: Engine, config_id: str) -> WatchFolderConfig:
    with Session(bind=engine) as session:
        row = session.get(WatchFolderConfig, config_id)
        assert row is not None
        session.expunge(row)
        return row


def _ledger_row(engine: Engine, config_id: str, file_path: Path) -> WatchFolderFileState | None:
    with Session(bind=engine) as session:
        row = session.execute(
            select(WatchFolderFileState).where(
                WatchFolderFileState.config_id == config_id,
                WatchFolderFileState.file_path == str(file_path),
            )
        ).scalar_one_or_none()
        if row is not None:
            session.expunge(row)
        return row


# ---------------------------------------------------------------------------
# Settle window / partial-copy safety
# ---------------------------------------------------------------------------


class TestSettleWindow:
    @_FFMPEG_SKIP
    def test_new_file_not_ingested_until_stable_across_two_polls(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        config = _make_config(engine, monitor_path=str(watch_dir))
        worker = _worker(session_factory, tmp_path)

        video = _generate_test_video(watch_dir / "meeting.mp4")

        # Poll 1: first observation -- establishes the baseline, never ingests.
        result1 = worker.run_once(force_all=True)
        assert result1.files_ingested == 0
        with Session(bind=engine) as session:
            assert session.execute(select(Asset)).scalars().first() is None
            assert session.execute(select(MediaIngestJob)).scalars().first() is None
        ledger = _ledger_row(engine, config.config_id, video)
        assert ledger is not None
        assert ledger.status == FILE_STATE_PENDING

        # Poll 2: size+mtime unchanged since poll 1 -- two consecutive
        # matching observations -- now it's safe to ingest.
        result2 = worker.run_once(force_all=True)
        assert result2.files_ingested == 1
        assert result2.folders_degraded == 0

        with Session(bind=engine) as session:
            assets = list(session.execute(select(Asset)).scalars())
            assert len(assets) == 1
            assert assets[0].file_size_bytes == video.stat().st_size

            jobs = list(session.execute(select(MediaIngestJob)).scalars())
            assert len(jobs) == 1
            assert jobs[0].source_kind == "watch_folder"
            assert jobs[0].source_path == str(video)
            assert jobs[0].asset_id == assets[0].asset_id

        ledger = _ledger_row(engine, config.config_id, video)
        assert ledger is not None
        assert ledger.status == FILE_STATE_INGESTED
        assert ledger.asset_id is not None
        assert ledger.ingested_at is not None

        # The original file is NEVER deleted (delete-safety posture) and,
        # in the default leave_with_ledger mode, never moved either.
        assert video.exists()

    @_FFMPEG_SKIP
    def test_growing_file_is_not_ingested_mid_write(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        """A file still being copied (size changing between polls) must never
        be handed to ingest -- this is the D13 partial-copy-safety guard.
        Simulates an in-progress copy by writing the real generated video in
        two chunks with a poll (and a size change the worker must notice)
        in between."""

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        _make_config(engine, monitor_path=str(watch_dir))
        worker = _worker(session_factory, tmp_path)

        source_video = _generate_test_video(tmp_path / "source.mp4", duration=2)
        full_bytes = source_video.read_bytes()
        assert len(full_bytes) > 200, "generated video should have real content to split"
        split = len(full_bytes) // 2

        dest = watch_dir / "in-progress.mp4"
        dest.write_bytes(full_bytes[:split])

        # Poll 1: baseline on the partial file.
        result1 = worker.run_once(force_all=True)
        assert result1.files_ingested == 0

        # Simulate the copy continuing: size (and very likely mtime) change.
        time.sleep(0.05)
        dest.write_bytes(full_bytes[:split] + b"\x00" * 10)  # still not the final content

        # Poll 2: size changed since poll 1 -- must reset the settle window,
        # NOT ingest a truncated/corrupt file.
        result2 = worker.run_once(force_all=True)
        assert result2.files_ingested == 0
        assert result2.files_failed == 0
        with Session(bind=engine) as session:
            assert session.execute(select(Asset)).scalars().first() is None

        # The "copy" finishes.
        time.sleep(0.05)
        dest.write_bytes(full_bytes)

        # Poll 3: another change since poll 2 -- still must not ingest yet.
        result3 = worker.run_once(force_all=True)
        assert result3.files_ingested == 0
        with Session(bind=engine) as session:
            assert session.execute(select(Asset)).scalars().first() is None

        # Poll 4: unchanged since poll 3 -- now, and only now, stable.
        result4 = worker.run_once(force_all=True)
        assert result4.files_ingested == 1
        with Session(bind=engine) as session:
            asset = session.execute(select(Asset)).scalars().one()
            assert asset.file_size_bytes == len(full_bytes)


# ---------------------------------------------------------------------------
# Unreachable path -> visible degraded state (never silent)
# ---------------------------------------------------------------------------


class TestDegradedState:
    def test_missing_monitor_path_marks_config_degraded(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        missing = tmp_path / "does-not-exist"
        config = _make_config(engine, monitor_path=str(missing))
        assert config.health_status == WATCH_FOLDER_HEALTH_UNKNOWN
        worker = _worker(session_factory, tmp_path)

        result = worker.run_once(force_all=True)
        assert result.folders_degraded == 1
        assert result.folder_results[0].healthy is False
        assert result.folder_results[0].error

        updated = _refresh_config(engine, config.config_id)
        assert updated.health_status == WATCH_FOLDER_HEALTH_DEGRADED
        assert updated.degraded_reason
        assert updated.degraded_since is not None
        assert updated.last_poll_at is not None

    def test_recovered_path_clears_degraded_state(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        config = _make_config(engine, monitor_path=str(watch_dir))
        worker = _worker(session_factory, tmp_path)

        worker.run_once(force_all=True)  # unreachable -- degraded
        degraded = _refresh_config(engine, config.config_id)
        assert degraded.health_status == WATCH_FOLDER_HEALTH_DEGRADED

        watch_dir.mkdir()  # "USB plugged back in" / SMB share reachable again
        worker.run_once(force_all=True)

        recovered = _refresh_config(engine, config.config_id)
        assert recovered.health_status == WATCH_FOLDER_HEALTH_OK
        assert recovered.degraded_reason is None
        assert recovered.degraded_since is None
        assert recovered.last_scanned_at is not None

    def test_one_degraded_folder_does_not_block_another_configs_scan(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        """Per-folder isolation: a NAS share going down for one config must
        not stop the daemon from continuing to poll a healthy config."""

        healthy_dir = tmp_path / "healthy"
        healthy_dir.mkdir()
        missing_dir = tmp_path / "missing"
        _make_config(engine, monitor_path=str(missing_dir))
        _make_config(engine, monitor_path=str(healthy_dir))
        worker = _worker(session_factory, tmp_path, max_concurrent_folders=2)

        result = worker.run_once(force_all=True)
        assert result.folders_scanned == 2
        assert result.folders_degraded == 1
        healthy_result = next(
            r for r in result.folder_results if r.monitor_path == str(healthy_dir)
        )
        assert healthy_result.healthy is True


# ---------------------------------------------------------------------------
# Reprocess-on-change
# ---------------------------------------------------------------------------


class TestReprocessOnChange:
    @_FFMPEG_SKIP
    def test_changed_file_reingests_the_same_asset(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        _make_config(engine, monitor_path=str(watch_dir))
        worker = _worker(session_factory, tmp_path)

        video = watch_dir / "meeting.mp4"
        _generate_test_video(video, duration=2)

        worker.run_once(force_all=True)  # baseline
        first_pass = worker.run_once(force_all=True)  # stable -> ingest
        assert first_pass.files_ingested == 1

        with Session(bind=engine) as session:
            first_asset = session.execute(select(Asset)).scalars().one()
            first_asset_id = first_asset.asset_id
            first_hash = first_asset.content_hash
            first_size = first_asset.file_size_bytes
            first_job_count = len(
                list(
                    session.execute(
                        select(MediaIngestJob).where(MediaIngestJob.asset_id == first_asset_id)
                    ).scalars()
                )
            )
        assert first_job_count == 1

        # The file at the SAME path changes (longer duration -> different
        # size/content/hash) -- e.g. an operator re-exported the recording
        # to the same watch-folder location.
        time.sleep(0.05)
        _generate_test_video(video, duration=4, size="640x480")

        worker.run_once(force_all=True)  # baseline for the new content
        second_pass = worker.run_once(force_all=True)  # stable -> reprocess
        assert second_pass.files_reprocessed == 1
        assert second_pass.files_ingested == 0

        with Session(bind=engine) as session:
            assets = list(session.execute(select(Asset)).scalars())
            # Still exactly one asset -- reprocess-on-change updates the
            # EXISTING asset rather than creating a duplicate.
            assert len(assets) == 1
            assert assets[0].asset_id == first_asset_id
            assert assets[0].content_hash != first_hash
            assert assets[0].file_size_bytes != first_size

            jobs = list(
                session.execute(
                    select(MediaIngestJob).where(MediaIngestJob.asset_id == first_asset_id)
                ).scalars()
            )
            # A second, distinct ingest job records the reprocess.
            assert len(jobs) == 2
            assert {j.source_kind for j in jobs} == {"watch_folder"}

        ledger = _ledger_row(engine, next(iter(_iter_config_ids(engine))), video)
        assert ledger is not None
        assert ledger.asset_id == first_asset_id
        assert ledger.status == FILE_STATE_INGESTED


def _iter_config_ids(engine: Engine) -> Iterator[str]:
    with Session(bind=engine) as session:
        for row in session.execute(select(WatchFolderConfig)).scalars():
            yield row.config_id


# ---------------------------------------------------------------------------
# Processed-file disposition (ADR 0024) -- never deletes the source
# ---------------------------------------------------------------------------


class TestProcessedFileDisposition:
    @_FFMPEG_SKIP
    def test_move_to_subfolder_mode_moves_but_never_deletes(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        config = _make_config(
            engine,
            monitor_path=str(watch_dir),
            processed_file_mode=PROCESSED_FILE_MODE_MOVE_TO_SUBFOLDER,
            processed_subfolder_name="done",
        )
        worker = _worker(session_factory, tmp_path)
        video = _generate_test_video(watch_dir / "meeting.mp4")

        worker.run_once(force_all=True)
        worker.run_once(force_all=True)

        assert not video.exists(), "source should have moved out of monitor_path"
        moved = watch_dir / "done" / "meeting.mp4"
        assert moved.exists(), "moved file must still exist on disk -- never deleted"

        # The daemon must not re-descend into the processed subfolder and
        # treat the moved file as a brand-new candidate.
        result = worker.run_once(force_all=True)
        assert result.files_ingested == 0
        with Session(bind=engine) as session:
            assert len(list(session.execute(select(Asset)).scalars())) == 1
        assert config.processed_subfolder_name == "done"

    @_FFMPEG_SKIP
    def test_leave_with_ledger_mode_never_moves_the_source(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        _make_config(engine, monitor_path=str(watch_dir))  # default: leave_with_ledger
        worker = _worker(session_factory, tmp_path)
        video = _generate_test_video(watch_dir / "meeting.mp4")

        worker.run_once(force_all=True)
        worker.run_once(force_all=True)

        assert video.exists(), "leave_with_ledger must never move the source file"
        with Session(bind=engine) as session:
            assert len(list(session.execute(select(Asset)).scalars())) == 1


# ---------------------------------------------------------------------------
# Bad content -> per-file failure, not a folder-wide crash
# ---------------------------------------------------------------------------


class TestUnsupportedFile:
    def test_unsupported_file_marks_ledger_failed_without_crashing_the_pass(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        _make_config(engine, monitor_path=str(watch_dir))
        worker = _worker(session_factory, tmp_path)

        garbage = watch_dir / "not-a-video.mp4"
        garbage.write_bytes(b"this is not a real video container" * 10)

        worker.run_once(force_all=True)
        result = worker.run_once(force_all=True)

        assert result.files_failed == 1
        assert result.files_ingested == 0
        with Session(bind=engine) as session:
            assert session.execute(select(Asset)).scalars().first() is None
        ledger = _ledger_row(engine, next(iter(_iter_config_ids(engine))), garbage)
        assert ledger is not None
        assert ledger.error_detail
        # The unreadable file is never deleted.
        assert garbage.exists()


# ---------------------------------------------------------------------------
# Poll-interval due-check
# ---------------------------------------------------------------------------


class TestPollDueCheck:
    def test_config_not_due_before_its_own_poll_interval(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        config = _make_config(engine, monitor_path=str(watch_dir), poll_interval_seconds=300)
        worker = _worker(session_factory, tmp_path)

        now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
        first = worker.run_once(now=now)
        assert first.folders_scanned == 1  # never polled before -> due

        soon_after = now.replace(second=30)  # 30s later, well under the 300s interval
        second = worker.run_once(now=soon_after)
        assert second.folders_scanned == 0  # not due yet -- config untouched

        well_after = now.replace(minute=now.minute + 6)
        third = worker.run_once(now=well_after)
        assert third.folders_scanned == 1
        assert config.config_id  # sanity: fixture still valid
