# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S7 media lifecycle worker tests.

Mirrors ``tests/schedule/test_retention_worker.py`` / ``test_media_integrity_worker.py``'s
structure and fixture style (env-gated settings, ``run_once``, SQLite
session-factory fixture) by design -- all three workers share the same shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.media_lifecycle_models import (
    READINESS_MISSING_FILE,
    READINESS_NOT_READY,
    READINESS_PENDING_TRANSCODE,
    READINESS_READY,
    READINESS_REJECTED,
    AssetArchiveProof,
    AssetReadiness,
    MediaLifecycleAuditEntry,
    TranscodeJob,
)
from civiccast.schedule.media_lifecycle_worker import (
    FfmpegTranscodeExecutor,
    MediaLifecycleWorker,
    MediaLifecycleWorkerSettings,
    StubTranscodeExecutor,
    TranscodeExecutionResult,
)
from civiccast.schedule.models import Asset, ScheduleItem

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
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


def _seed_asset(engine: Engine, **overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "asset_id": "a1",
        "title": "Council Meeting",
        "state": "validated",
        "file_path": None,
        "file_status": "ok",
    }
    defaults.update(overrides)
    with Session(bind=engine) as session:
        asset = Asset(**defaults)  # type: ignore[arg-type]
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def _worker(
    session_factory,  # type: ignore[no-untyped-def]
    *,
    dry_run: bool = False,
    executor=None,  # type: ignore[no-untyped-def]
) -> MediaLifecycleWorker:
    return MediaLifecycleWorker(
        session_factory,
        settings=MediaLifecycleWorkerSettings(mode="inline", poll_seconds=1.0, dry_run=dry_run),
        transcode_executor=executor or StubTranscodeExecutor(),
    )


# ---------------------------------------------------------------------------
# Table-driven readiness state computation
# ---------------------------------------------------------------------------


class TestReadinessStateComputation:
    def test_rejected_asset_reads_rejected(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(engine, asset_id="a1", state="rejected")
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.readiness_state == READINESS_REJECTED

    def test_missing_file_asset_reads_missing_file(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(engine, asset_id="a1", state="validated", file_status="missing")
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.readiness_state == READINESS_MISSING_FILE

    def test_pending_ingest_asset_reads_not_ready(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(engine, asset_id="a1", state="pending_ingest")
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.readiness_state == READINESS_NOT_READY

    def test_validated_no_file_path_skips_transcode_seed_stays_ready(
        self,
        engine: Engine,
        session_factory,  # type: ignore[no-untyped-def]
    ) -> None:
        # No file_path -> nothing to transcode; the asset is as "ready" as
        # a manifest-only row can be (no in-flight jobs, none possible).
        _seed_asset(engine, asset_id="a1", state="validated", file_path=None)
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.readiness_state == READINESS_READY

    def test_validated_with_file_seeds_transcode_jobs_first_pass(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(
            session_factory,
            executor=StubTranscodeExecutor(),
        )
        result = worker.run_once(now=_NOW)
        assert result.transcode_jobs_seeded == 3  # DEFAULT_TRANSCODE_FORMATS
        with Session(bind=engine) as session:
            jobs = session.query(TranscodeJob).filter(TranscodeJob.asset_id == "a1").all()
            assert len(jobs) == 3
            assert {j.status for j in jobs} == {"completed"}
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert (
                row.readiness_state == READINESS_PENDING_TRANSCODE
            )  # not dispatched yet this pass

    def test_second_pass_after_dispatch_reads_ready(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(session_factory, executor=StubTranscodeExecutor())
        worker.run_once(now=_NOW)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.readiness_state == READINESS_READY


# ---------------------------------------------------------------------------
# Dry-run mode: audit entries written, nothing else mutated
# ---------------------------------------------------------------------------


class TestDryRunVsApply:
    def test_dry_run_writes_no_readiness_row(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(session_factory, executor=StubTranscodeExecutor())

        result = worker.run_once(now=_NOW, dry_run=True)
        assert result.dry_run is True

        with Session(bind=engine) as session:
            assert session.get(AssetReadiness, "a1") is None
            assert session.query(TranscodeJob).count() == 0

    def test_dry_run_still_writes_audit_entries_tagged_dry_run(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(session_factory, executor=StubTranscodeExecutor())

        worker.run_once(now=_NOW, dry_run=True)

        with Session(bind=engine) as session:
            entries = (
                session.query(MediaLifecycleAuditEntry)
                .filter(MediaLifecycleAuditEntry.asset_id == "a1")
                .all()
            )
            assert entries, "dry run must still record what it would have done"
            assert all(e.dry_run for e in entries)

    def test_apply_mode_writes_readiness_row_and_unflagged_audit_entries(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(session_factory, executor=StubTranscodeExecutor())

        worker.run_once(now=_NOW, dry_run=False)

        with Session(bind=engine) as session:
            assert session.get(AssetReadiness, "a1") is not None
            entries = (
                session.query(MediaLifecycleAuditEntry)
                .filter(MediaLifecycleAuditEntry.asset_id == "a1")
                .all()
            )
            assert entries
            assert all(not e.dry_run for e in entries)


# ---------------------------------------------------------------------------
# Transcode dispatch: success + failure paths
# ---------------------------------------------------------------------------


class _FailingExecutor:
    def run(self, *, asset, output_format, output_dir):  # type: ignore[no-untyped-def]
        return TranscodeExecutionResult(success=False, error_detail="synthetic failure")


class TestTranscodeDispatch:
    def test_failed_transcode_job_records_error_detail(
        self,
        engine: Engine,
        session_factory,
        tmp_path: Path,  # type: ignore[no-untyped-def]
    ) -> None:
        media_file = tmp_path / "meeting.mp4"
        media_file.write_bytes(b"\x00")
        _seed_asset(engine, asset_id="a1", state="validated", file_path=str(media_file))
        worker = _worker(session_factory, executor=_FailingExecutor())

        result = worker.run_once(now=_NOW)
        assert result.transcode_jobs_failed == 3
        assert result.transcode_jobs_completed == 0

        with Session(bind=engine) as session:
            jobs = session.query(TranscodeJob).filter(TranscodeJob.asset_id == "a1").all()
            assert all(j.status == "failed" for j in jobs)
            assert all(j.error_detail == "synthetic failure" for j in jobs)

    def test_ffmpeg_executor_reports_missing_source_file_as_failure(self, tmp_path: Path) -> None:
        executor = FfmpegTranscodeExecutor()
        asset = Asset(
            asset_id="a1", title="x", state="validated", file_path=str(tmp_path / "missing.mp4")
        )
        result = executor.run(asset=asset, output_format="h264_720p_5mbps", output_dir=tmp_path)
        assert result.success is False
        assert result.error_detail is not None and "not found" in result.error_detail


# ---------------------------------------------------------------------------
# Archival gate (CLAUDE.md §4.6): portal + IA + NAS all verified, non-simulated
# ---------------------------------------------------------------------------


class TestArchiveCompleteGate:
    def test_no_proofs_never_archive_complete(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(
            engine,
            asset_id="a1",
            state="recorded",
            manifest_url="https://portal.example/a1.m3u8",
            published_at=_NOW,
        )
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.archive_complete is False

    def test_simulated_proofs_never_count_toward_archive_complete(
        self,
        engine: Engine,
        session_factory,  # type: ignore[no-untyped-def]
    ) -> None:
        _seed_asset(
            engine,
            asset_id="a1",
            state="recorded",
            manifest_url="https://portal.example/a1.m3u8",
            published_at=_NOW,
        )
        with Session(bind=engine) as session:
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="internet_archive",
                    target_url_or_path="https://simulated.invalid/a1",
                    verification_hash="sha256:" + "0" * 64,
                    simulated=True,
                )
            )
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="local_nas_rsync",
                    target_url_or_path="/nas/a1.mp4",
                    verification_hash="sha256:" + "1" * 64,
                    simulated=True,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.archive_complete is False, (
                "a mock/simulated proof must never satisfy the gate"
            )

    def test_real_proofs_across_all_three_tiers_flip_archive_complete_true(
        self,
        engine: Engine,
        session_factory,  # type: ignore[no-untyped-def]
    ) -> None:
        _seed_asset(
            engine,
            asset_id="a1",
            state="recorded",
            manifest_url="https://portal.example/a1.m3u8",
            published_at=_NOW,
        )
        with Session(bind=engine) as session:
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="internet_archive",
                    target_url_or_path="https://archive.org/details/a1",
                    verification_hash="sha256:" + "0" * 64,
                    simulated=False,
                )
            )
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="local_nas_zfs",
                    target_url_or_path="zfs://civiccast/archive@a1",
                    verification_hash="sha256:" + "1" * 64,
                    simulated=False,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.archive_complete is True
            assert row.archive_portal_verified_at is not None
            assert row.archive_ia_verified_at is not None
            assert row.archive_nas_verified_at is not None

    def test_missing_portal_publish_blocks_archive_complete_even_with_both_proofs(
        self,
        engine: Engine,
        session_factory,  # type: ignore[no-untyped-def]
    ) -> None:
        _seed_asset(engine, asset_id="a1", state="recorded", manifest_url=None, published_at=None)
        with Session(bind=engine) as session:
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="internet_archive",
                    target_url_or_path="https://archive.org/details/a1",
                    verification_hash="sha256:" + "0" * 64,
                    simulated=False,
                )
            )
            session.add(
                AssetArchiveProof(
                    asset_id="a1",
                    target_type="local_nas_zfs",
                    target_url_or_path="zfs://civiccast/archive@a1",
                    verification_hash="sha256:" + "1" * 64,
                    simulated=False,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        worker.run_once(now=_NOW)
        with Session(bind=engine) as session:
            row = session.get(AssetReadiness, "a1")
            assert row is not None
            assert row.archive_complete is False


# ---------------------------------------------------------------------------
# Missing media (live join, not a durable flag)
# ---------------------------------------------------------------------------


class TestMissingMedia:
    def test_scheduled_item_with_unvalidated_asset_is_flagged(
        self,
        engine: Engine,
        session_factory,  # type: ignore[no-untyped-def]
    ) -> None:
        _seed_asset(engine, asset_id="a1", state="pending_ingest")
        with Session(bind=engine) as session:
            session.add(
                ScheduleItem(
                    asset_id="a1",
                    channel_id="public",
                    mode="premiere",
                    state="scheduled",
                    scheduled_at=_NOW + timedelta(days=1),
                    duration_seconds=3600,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        missing = worker.list_missing_media(now=_NOW)
        assert len(missing) == 1
        assert missing[0]["asset_id"] == "a1"

    def test_validated_asset_is_not_flagged(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(engine, asset_id="a1", state="validated")
        with Session(bind=engine) as session:
            session.add(
                ScheduleItem(
                    asset_id="a1",
                    channel_id="public",
                    mode="premiere",
                    state="scheduled",
                    scheduled_at=_NOW + timedelta(days=1),
                    duration_seconds=3600,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        missing = worker.list_missing_media(now=_NOW)
        assert missing == []

    def test_item_beyond_horizon_is_not_flagged(self, engine: Engine, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(engine, asset_id="a1", state="pending_ingest")
        with Session(bind=engine) as session:
            session.add(
                ScheduleItem(
                    asset_id="a1",
                    channel_id="public",
                    mode="premiere",
                    state="scheduled",
                    scheduled_at=_NOW + timedelta(days=30),
                    duration_seconds=3600,
                )
            )
            session.commit()
        worker = _worker(session_factory)
        missing = worker.list_missing_media(now=_NOW)
        assert missing == []
