# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Recording finalization worker tests."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.live.models
import civiccast.schedule.models
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.finalization_worker import LiveFinalizationWorker
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    FINALIZATION_STATE_FAILED,
    FINALIZATION_STATE_PENDING,
    FINALIZATION_STATE_RUNNING,
    LIVE_SESSION_STATE_ENDING,
    LiveFinalizationJob,
    LiveSession,
    RecordingTarget,
)
from civiccast.live.store import LiveSessionStore
from civiccast.schedule.ingest import FfprobeResult, run_ffprobe
from civiccast.schedule.models import Asset
from civiccast.stream._ffmpeg import resolve_h264_encoder, run_ffmpeg


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
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _probe(duration: int = 120) -> FfprobeResult:
    return FfprobeResult(
        duration_seconds=duration,
        codec_video="h264",
        codec_audio="aac",
        width_px=1280,
        height_px=720,
        bitrate_bps=800_000,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
    )


def _fake_packager(calls: list[dict[str, object]]):
    def packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):
        manifest = output_dir / "playlist.m3u8"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        calls.append(
            {
                "input_path": input_path,
                "output_dir": output_dir,
                "trim_in_seconds": trim_in_seconds,
                "trim_out_seconds": trim_out_seconds,
            }
        )
        return SimpleNamespace(manifest_path=manifest)

    return packager


def _seed_ending_session(
    engine: Engine, target_dir: Path, *, live_session_id: str = "council-2026-06-09"
) -> Path:
    recording = target_dir / f"{live_session_id}.mp4"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"recording")
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id=live_session_id,
                channel_id="gov-ch12",
                title="City Council",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
            )
        )
        session.add(
            RecordingTarget(
                recording_target_id="fs-primary",
                name="Primary recordings",
                target_uri=target_dir.as_uri(),
            )
        )
        session.commit()
    return recording


def _asset_rows(engine: Engine) -> list[Asset]:
    with Session(bind=engine) as session:
        return list(session.execute(select(Asset)).scalars())


def test_worker_finalizes_settled_recording_and_packages_outside_installer_self_test(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    recording = _seed_ending_session(engine, tmp_path)
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    statuses = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    assert statuses[0].state == FINALIZATION_STATE_COMPLETED
    assert statuses[0].asset_id == "council-2026-06-09"
    assert statuses[0].local_package_manifest_path == str(
        (tmp_path / "council-2026-06-09-hls" / "playlist.m3u8").resolve()
    )
    assert calls[0]["input_path"] == recording
    asset = _asset_rows(engine)[0]
    assert asset.source_live_session_id == "council-2026-06-09"
    # VOD local-serve (no CDN, no CIVICCAST_LIVE_MANIFEST_BASE_URL configured):
    # manifest_url defaults to the app's own media_router URL rather than
    # staying null, so the portal always has something playable.
    assert asset.manifest_url == (
        "http://127.0.0.1:8000/media/vod/council-2026-06-09/playlist.m3u8"
    )


def test_worker_does_not_finalize_unsettled_recording(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    recording = _seed_ending_session(engine, tmp_path)
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=10,
    )
    first = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]
    recording.write_bytes(b"recording still growing")
    second = worker.run_once(now=datetime(2026, 6, 9, 18, 1, 11, tzinfo=UTC))[0]

    assert first.state == FINALIZATION_STATE_PENDING
    assert second.state == FINALIZATION_STATE_PENDING
    assert calls == []
    assert _asset_rows(engine) == []


def test_partial_recording_failure_retries_then_persists_failed_reason(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    _seed_ending_session(engine, tmp_path)
    worker = LiveFinalizationWorker(
        session_factory,
        packager=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("encode failed")),
        probe=lambda _: _probe(),
        settle_seconds=0,
        max_attempts=2,
        backoff_seconds=0,
    )

    first = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]
    second = worker.run_once(now=datetime(2026, 6, 9, 18, 2, tzinfo=UTC))[0]

    assert first.state == FINALIZATION_STATE_FAILED
    assert second.state == FINALIZATION_STATE_FAILED
    assert second.attempts == 2
    assert second.next_attempt_at is None
    # Contract since the Stage B+D hardening pass (UX-003): raw exception text
    # lives in failure_detail; failure_reason carries operator copy.
    assert "encode failed" in (second.failure_detail or "")
    assert second.failure_reason, "operator copy must be present on failure"


def test_duplicate_worker_scan_is_noop_after_completion(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    _seed_ending_session(engine, tmp_path)
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))
    worker.run_once(now=datetime(2026, 6, 9, 18, 2, tzinfo=UTC))

    assert len(_asset_rows(engine)) == 1
    assert len(calls) == 1


def test_packaging_runs_after_finalize_transaction_commits(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    _seed_ending_session(engine, tmp_path)
    observed_asset_ids: list[str] = []

    def packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):
        with Session(bind=engine) as session:
            observed_asset_ids.extend(session.execute(select(Asset.asset_id)).scalars())
        manifest = output_dir / "playlist.m3u8"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest)

    worker = LiveFinalizationWorker(
        session_factory,
        packager=packager,
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    assert observed_asset_ids == ["council-2026-06-09"]


def test_packaging_retry_skips_existing_manifest(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    _seed_ending_session(engine, tmp_path)
    calls = 0

    def flaky_packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):
        nonlocal calls
        calls += 1
        manifest = output_dir / "playlist.m3u8"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        raise RuntimeError("crashed after writing manifest")

    worker = LiveFinalizationWorker(
        session_factory,
        packager=flaky_packager,
        probe=lambda _: _probe(),
        settle_seconds=0,
        max_attempts=2,
        backoff_seconds=0,
    )

    first = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]
    second = worker.run_once(now=datetime(2026, 6, 9, 18, 2, tzinfo=UTC))[0]

    assert first.state == FINALIZATION_STATE_FAILED
    assert second.state == FINALIZATION_STATE_COMPLETED
    assert calls == 1


def test_trim_values_persist_and_propagate_through_worker_packaging(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    # SYNTHETIC SEEDING (TEST-004): no production surface writes trim onto a
    # finalization job yet — this test covers the worker's trim *plumbing*
    # only, not operator reachability. The real trim writer
    # (repackage-on-trim-update) is the tracked follow-up story on the
    # next-sprint watchlist; when it lands, add a writer-path test through the
    # public surface and keep this one as the plumbing regression net.
    _seed_ending_session(engine, tmp_path)
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="council-2026-06-09",
                recording_uri=(tmp_path / "council-2026-06-09.mp4").as_uri(),
                recording_size_bytes=9,
                last_observed_size_bytes=9,
                last_observed_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                trim_in_seconds=1.25,
                trim_out_seconds=2.75,
            )
        )
        session.commit()
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(duration=5),
        settle_seconds=0,
    )

    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    assert calls[0]["trim_in_seconds"] == 1.25
    assert calls[0]["trim_out_seconds"] == 2.75
    asset = _asset_rows(engine)[0]
    assert asset.trim_in_seconds == 1.25
    assert asset.trim_out_seconds == 2.75


def test_invalid_trim_is_rejected_before_asset_write(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    # SYNTHETIC SEEDING (TEST-004): see the note on
    # test_trim_values_persist_and_propagate_through_worker_packaging.
    _seed_ending_session(engine, tmp_path)
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="council-2026-06-09",
                recording_uri=(tmp_path / "council-2026-06-09.mp4").as_uri(),
                recording_size_bytes=9,
                last_observed_size_bytes=9,
                last_observed_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                trim_in_seconds=4.0,
                trim_out_seconds=2.0,
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(duration=5),
        settle_seconds=0,
    )

    status = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]

    assert status.state == FINALIZATION_STATE_FAILED
    # Raw validation text is diagnostic detail since the Stage B+D hardening
    # pass (UX-003); the classified code/copy is asserted in
    # test_invalid_trim_failure_is_classified.
    assert "trim_in_seconds" in (status.failure_detail or "")
    assert _asset_rows(engine) == []


def test_local_package_sets_local_serve_manifest_url_without_a_cdn(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    """No CDN, no CIVICCAST_LIVE_MANIFEST_BASE_URL: manifest_url still gets
    populated (VOD local-serve default), not left null.
    """
    _seed_ending_session(engine, tmp_path)
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    asset = _asset_rows(engine)[0].to_staff_row()
    assert asset.manifest_url == (
        "http://127.0.0.1:8000/media/vod/council-2026-06-09/playlist.m3u8"
    )


def test_staff_status_surface_reports_each_finalization_state(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    _seed_ending_session(engine, tmp_path, live_session_id="pending-session")
    with Session(bind=engine) as session:
        for state in (
            FINALIZATION_STATE_RUNNING,
            FINALIZATION_STATE_FAILED,
            FINALIZATION_STATE_COMPLETED,
        ):
            session.add(
                LiveFinalizationJob(
                    live_session_id=f"{state}-session",
                    state=state,
                    failure_reason="boom" if state == FINALIZATION_STATE_FAILED else None,
                )
            )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory, packager=_fake_packager([]), probe=lambda _: _probe()
    )
    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    by_id = {row.live_session_id: row.state for row in worker.list_statuses()}

    assert by_id["pending-session"] == FINALIZATION_STATE_PENDING
    assert by_id["running-session"] == FINALIZATION_STATE_RUNNING
    assert by_id["failed-session"] == FINALIZATION_STATE_FAILED
    assert by_id["completed-session"] == FINALIZATION_STATE_COMPLETED


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH; real-media trim proof skipped",
)
def test_real_media_trim_proof_duration_matches_trim_window(
    engine: Engine,
    session_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SYNTHETIC SEEDING (TEST-004): see the note on
    # test_trim_values_persist_and_propagate_through_worker_packaging.
    recording = _seed_ending_session(engine, tmp_path)
    result = run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(recording),
        ]
    )
    assert result.returncode == 0, result.stderr
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="council-2026-06-09",
                recording_uri=recording.as_uri(),
                recording_size_bytes=recording.stat().st_size,
                last_observed_size_bytes=recording.stat().st_size,
                last_observed_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                trim_in_seconds=1.0,
                trim_out_seconds=2.0,
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(session_factory, settle_seconds=0)

    status = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]

    assert status.state == FINALIZATION_STATE_COMPLETED
    package_dir = tmp_path / "council-2026-06-09-hls"
    # The packager never upscales, so this deliberately tiny 160x90 source
    # produces one content variant at its own resolution rather than the
    # ladder's 240p rung (the worker passes no dimensions, so this also
    # proves pack_vod_asset probes the input for itself). Discover the
    # variant instead of hard-coding a rung name.
    content_variants = sorted(
        path.name for path in package_dir.iterdir() if path.is_dir() and path.name != "slate"
    )
    assert content_variants == ["90p"]
    packaged_variant = package_dir / content_variants[0] / "playlist.m3u8"
    probe = run_ffprobe(packaged_variant)
    assert probe.duration_seconds is not None
    assert abs(probe.duration_seconds - 1) <= 1


def test_end_broadcast_to_worker_path_reaches_recorded_asset(
    engine: Engine,
    session_factory,
    tmp_path: Path,
) -> None:
    store = LiveSessionStore(session_factory)
    store.create_session(
        civiccast.live.models.LiveSessionCreate(
            live_session_id="api-created-session",
            channel_id="gov-ch12",
            title="API-created meeting",
        )
    )
    store.start_preflight("api-created-session")
    store.go_on_air("api-created-session")
    store.end_broadcast("api-created-session")
    with Session(bind=engine) as session:
        session.add(
            RecordingTarget(
                recording_target_id="fs-primary",
                name="Primary recordings",
                target_uri=tmp_path.as_uri(),
            )
        )
        session.commit()
    (tmp_path / "api-created-session.mp4").write_bytes(b"recording")
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))

    asset = _asset_rows(engine)[0]
    assert asset.asset_id == "api-created-session"
    assert asset.state == "recorded"


# ===========================================================================
# Self-healing pass (Stage B+D audit ENG-007/008/009/011, QA-004/005,
# W-5/6/7; TDD per TEST-006) and the status contract (UX-002/003, DOC-009).
# ===========================================================================


def test_stale_running_job_is_recovered_after_lease_timeout(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    """A crash mid-attempt (stale `running`) self-heals via the started_at lease."""

    recording = _seed_ending_session(engine, tmp_path, live_session_id="wedge-session")
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="wedge-session",
                state=FINALIZATION_STATE_RUNNING,
                recording_uri=recording.as_uri(),
                recording_size_bytes=recording.stat().st_size,
                last_observed_size_bytes=recording.stat().st_size,
                last_observed_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                started_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
            )
        )
        session.commit()
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=0,
        backoff_seconds=0,
        running_lease_seconds=900,
    )

    within_lease = worker.run_once(now=datetime(2026, 6, 9, 18, 5, tzinfo=UTC))[0]
    recovered = worker.run_once(now=datetime(2026, 6, 9, 18, 20, tzinfo=UTC))[0]
    retried = worker.run_once(now=datetime(2026, 6, 9, 18, 30, tzinfo=UTC))[0]

    assert within_lease.state == FINALIZATION_STATE_RUNNING, (
        "A running job inside its lease must not be touched"
    )
    assert recovered.state == FINALIZATION_STATE_FAILED
    assert recovered.failure_code == "worker.interrupted"
    assert recovered.attempts == 1
    assert recovered.next_attempt_at is not None, "lease recovery must requeue"
    assert retried.state == FINALIZATION_STATE_COMPLETED, (
        "the recovered job must retry to completion on the next scan"
    )


def test_recording_never_appearing_fails_terminal_with_expected_path(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    """No recording file forever -> terminal failed with actionable reason."""

    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id="ghost-session",
                channel_id="gov-ch12",
                title="Recorder never wrote a file",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
            )
        )
        session.add(
            RecordingTarget(
                recording_target_id="fs-primary",
                name="Primary recordings",
                target_uri=tmp_path.as_uri(),
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(),
        settle_seconds=0,
        never_appeared_seconds=1800,
    )

    early = worker.run_once(now=datetime(2026, 6, 9, 18, 10, tzinfo=UTC))[0]
    late = worker.run_once(now=datetime(2026, 6, 9, 19, 0, tzinfo=UTC))[0]

    assert early.state == FINALIZATION_STATE_PENDING
    assert late.state == FINALIZATION_STATE_FAILED
    assert late.failure_code == "recording.never_appeared"
    expected_path = str(tmp_path / "ghost-session.mp4")
    assert expected_path in (late.failure_reason or ""), (
        "operator copy must include the expected path so a target "
        "misconfiguration is immediately visible"
    )
    assert late.attempts == late.max_attempts
    assert late.next_attempt_at is None
    assert late.terminal is True


def test_run_forever_survives_scan_exception_and_logs_it(
    engine: Engine, session_factory, caplog: pytest.LogCaptureFixture
) -> None:
    """A transient scan error must not kill the loop thread (W-7)."""

    import logging
    import threading
    import time as time_module

    state = {"calls": 0}

    def flaky_factory():
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("transient db error")
        return session_factory()

    worker = LiveFinalizationWorker(
        flaky_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )
    stop = threading.Event()
    with caplog.at_level(logging.ERROR, logger="civiccast.live.finalization_worker"):
        thread = threading.Thread(
            target=worker.run_forever,
            kwargs={"poll_seconds": 0.01, "stop_event": stop},
            daemon=True,
        )
        thread.start()
        deadline = time_module.monotonic() + 5.0
        while state["calls"] < 3 and time_module.monotonic() < deadline:
            time_module.sleep(0.01)
        stop.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert state["calls"] >= 3, "the loop must keep scanning after the exception"
    assert any(
        "scan failed" in record.message.lower() and record.exc_info for record in caplog.records
    ), "the scan exception must be logged with its traceback"


def test_terminal_failed_job_is_excluded_from_scans(engine: Engine, session_factory) -> None:
    """Terminal failures stop being re-observed and rewritten forever (ENG-011)."""

    failed_at = datetime(2026, 6, 9, 18, 0, tzinfo=UTC)
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="dead-session",
                state=FINALIZATION_STATE_FAILED,
                attempts=3,
                max_attempts=3,
                failure_reason="boom",
                updated_at=failed_at,
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory, packager=_fake_packager([]), probe=lambda _: _probe()
    )

    statuses = worker.run_once(now=datetime(2026, 6, 9, 19, 0, tzinfo=UTC))

    assert statuses == [], "terminal failed jobs must not be in the scan set"
    with Session(bind=engine) as session:
        row = session.get(LiveFinalizationJob, "dead-session")
        assert row is not None
        assert _utc(row.updated_at) == failed_at, (
            "the 'when did it fail' signal must not be clobbered by scans"
        )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def test_resolution_skips_rehearsal_target_and_tries_later_targets(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    """The installer's rehearsal target must not swallow real recordings
    (ENG-005 interim), and a file under a later target resolves."""

    rehearsal_dir = tmp_path / "private-rehearsals"
    real_dir = tmp_path / "real-recordings"
    rehearsal_dir.mkdir()
    real_dir.mkdir()
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id="real-session",
                channel_id="gov-ch12",
                title="Real meeting after install rehearsal",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
            )
        )
        # Rehearsal target is OLDEST (created first on fresh installs).
        session.add(
            RecordingTarget(
                recording_target_id="local-rehearsal-recordings",
                name="Local rehearsal recordings",
                target_uri=rehearsal_dir.as_uri(),
                created_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
            )
        )
        session.add(
            RecordingTarget(
                recording_target_id="fs-real",
                name="Real recordings",
                target_uri=real_dir.as_uri(),
                created_at=datetime(2026, 6, 9, 11, 0, tzinfo=UTC),
            )
        )
        session.commit()
    (real_dir / "real-session.mp4").write_bytes(b"recording")
    calls: list[dict[str, object]] = []
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    status = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]

    assert status.state == FINALIZATION_STATE_COMPLETED
    assert calls[0]["input_path"] == real_dir / "real-session.mp4"


def test_wrong_recording_uri_reresolves_after_target_fix(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    """A mis-resolved recording_uri is not sticky: fixing the targets lets the
    next scan re-resolve (ENG-005: dropped the `or`-sticky assignment)."""

    wrong_dir = tmp_path / "wrong"
    right_dir = tmp_path / "right"
    wrong_dir.mkdir()
    right_dir.mkdir()
    _seed_ending_session(engine, right_dir, live_session_id="fixed-session")
    with Session(bind=engine) as session:
        # Job row stamped with a stale, wrong resolution (file never existed).
        session.add(
            LiveFinalizationJob(
                live_session_id="fixed-session",
                recording_uri=(wrong_dir / "fixed-session.mp4").as_uri(),
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(),
        settle_seconds=0,
    )

    status = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]

    assert status.recording_uri == (right_dir / "fixed-session.mp4").as_uri()
    assert status.state == FINALIZATION_STATE_COMPLETED


def test_failure_contract_uses_codes_and_operator_copy(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    """failure_code is a stable identifier, failure_reason is operator copy,
    and raw exception text is demoted to failure_detail (UX-002/UX-003)."""

    _seed_ending_session(engine, tmp_path)
    worker = LiveFinalizationWorker(
        session_factory,
        packager=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("encode failed")),
        probe=lambda _: _probe(),
        settle_seconds=0,
        max_attempts=2,
        backoff_seconds=0,
    )

    first = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]
    second = worker.run_once(now=datetime(2026, 6, 9, 18, 2, tzinfo=UTC))[0]

    assert first.failure_code == "package.failed"
    assert "encode failed" not in (first.failure_reason or ""), (
        "raw exception text must not be the operator-facing reason"
    )
    assert "original recording is safe" in (first.failure_reason or "").lower()
    assert "encode failed" in (first.failure_detail or "")
    assert first.terminal is False, "retries remain -> not terminal"
    assert second.terminal is True, "attempts exhausted -> terminal"
    assert second.next_attempt_at is None


def test_invalid_trim_failure_is_classified(
    engine: Engine, session_factory, tmp_path: Path
) -> None:
    _seed_ending_session(engine, tmp_path)
    with Session(bind=engine) as session:
        session.add(
            LiveFinalizationJob(
                live_session_id="council-2026-06-09",
                recording_uri=(tmp_path / "council-2026-06-09.mp4").as_uri(),
                recording_size_bytes=9,
                last_observed_size_bytes=9,
                last_observed_at=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                trim_in_seconds=4.0,
                trim_out_seconds=2.0,
            )
        )
        session.commit()
    worker = LiveFinalizationWorker(
        session_factory,
        packager=_fake_packager([]),
        probe=lambda _: _probe(duration=5),
        settle_seconds=0,
    )

    status = worker.run_once(now=datetime(2026, 6, 9, 18, 1, tzinfo=UTC))[0]

    assert status.state == FINALIZATION_STATE_FAILED
    assert status.failure_code == "finalize.invalid_trim"
    assert "trim" in (status.failure_reason or "").lower()
    assert "trim_in_seconds" in (status.failure_detail or "")


def test_local_recording_path_handles_windows_and_posix_shapes(tmp_path: Path) -> None:
    """QA-003/ENG-013: plain Windows drive paths are the natural operator
    input on the documented target platform and must resolve; relative paths
    and non-file schemes must be rejected (None), never CWD-resolved."""

    from civiccast.live.finalization_worker import _local_recording_path

    assert _local_recording_path("C:\\recordings") == Path("C:\\recordings")
    assert _local_recording_path("C:/recordings") == Path("C:/recordings")
    assert _local_recording_path("file:///C:/recordings") == Path("C:/recordings")
    assert _local_recording_path("/srv/recordings") == Path("/srv/recordings")
    assert _local_recording_path(tmp_path.as_uri()) == tmp_path
    assert _local_recording_path("relative/path") is None
    assert _local_recording_path("http://example.org/recordings") is None
    assert _local_recording_path("s3://bucket/recordings") is None
