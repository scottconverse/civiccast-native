# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 6 (recording/ingest hardening): mid-recording source-dropout tests.

These simulate a real dropout two ways — a killed/crashed ffmpeg child and a
stalled-but-alive one (output stops growing) — and assert the full chain: the
pipeline detects it, attempts reconnect, the job's dropout fields are
durably updated, and an alert-hub event is recorded. Each test can fail: the
fake ffmpeg processes really stop producing bytes, and the assertions check
real state (DB rows, dropout counters, alert records), not fixtures that
assert themselves.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from civiccast.alerting.models import AlertEventDb
from civiccast.db import Base
from civiccast.live.models import RecordingTarget
from civiccast.live.recording_paths import REHEARSAL_RECORDING_TARGET_ID
from civiccast.recording.models import (
    RecordingJob,
    RecordingSchedule,
    RecordingSource,
    RecurrenceSpec,
)
from civiccast.recording.runtime import (
    FfmpegScheduledCapturePipeline,
    RecordingAlertSink,
    ScheduledRecordingAssetFinalizer,
    ScheduledRecordingSettings,
    _ffmpeg_concat_quote,
)
from civiccast.recording.service import RecordingService
from civiccast.recording.store import RecordingStore
from civiccast.schedule.ingest import FfprobeResult

_NOW = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
_STATION = "civiccast-station"

_ENGINES_TO_DISPOSE: list = []


@pytest.fixture(autouse=True)
def _dispose_test_engines() -> Iterator[None]:
    """Dispose throwaway SQLite engines at each test's end.

    _make_store_and_dirs() traps a fresh engine in a factory closure; undisposed,
    its sqlite3.Connection lingers until GC finalizes it, raising an
    "Exception ignored in" unraisable that the filterwarnings=error policy turns
    into a failure pinned to a random unrelated test.
    """
    yield
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


@contextmanager
def _factory_for(engine) -> Iterator[Session]:
    with Session(bind=engine) as session:
        yield session


def _make_store_and_dirs(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    _ENGINES_TO_DISPOSE.append(engine)
    Base.metadata.create_all(engine)

    def factory():
        return _factory_for(engine)

    target_dir = tmp_path / "recordings"
    rehearsal_dir = tmp_path / "private-rehearsals"
    with factory() as session:
        session.add_all(
            [
                RecordingTarget(
                    recording_target_id=REHEARSAL_RECORDING_TARGET_ID,
                    name="Installer rehearsal recordings",
                    target_uri=rehearsal_dir.as_uri(),
                    created_at=_NOW - timedelta(minutes=2),
                ),
                RecordingTarget(
                    recording_target_id="local",
                    name="Local recordings",
                    target_uri=target_dir.as_uri(),
                    created_at=_NOW - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()
    return engine, factory, target_dir


class _ScriptedHandle:
    """A fake ffmpeg child whose lifecycle a test scripts explicitly.

    ``kill()`` simulates the source hanging up (process exits nonzero, as a
    real ffmpeg does when an RTSP/SRT/RTMP source vanishes). ``write(n)``
    simulates frames landing on disk (a real, growing output file); not
    calling it simulates a stalled-but-alive source.
    """

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.returncode: int | None = None
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"")
        self.terminate_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def write(self, extra_bytes: int) -> None:
        with self.output_path.open("ab") as fh:
            fh.write(b"x" * extra_bytes)

    def kill(self, returncode: int = 1) -> None:
        self.returncode = returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int:
        self.terminate_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def close(self) -> None:
        return None


def _fake_ffprobe(_path: Path) -> FfprobeResult:
    return FfprobeResult(
        duration_seconds=30,
        codec_video="h264",
        codec_audio="aac",
        width_px=1920,
        height_px=1080,
        bitrate_bps=4_000_000,
        format_name="mpegts",
    )


class _ConcatCapture:
    """Fake ``run_ffmpeg`` for the concat-merge step: really concatenates
    the listed segment files' bytes, so a test that checks merged content
    can fail if the merge step is skipped or wrong."""

    def __call__(self, args: list[str]):
        concat_list = Path(args[args.index("-i") + 1])
        output_path = Path(args[-1])
        merged = b""
        for line in concat_list.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("file "):
                continue
            segment_path = Path(line.split("'")[1])
            merged += segment_path.read_bytes()
        output_path.write_bytes(merged)
        return _FakeFfmpegResult(returncode=0, stdout="", stderr="")


class _FakeFfmpegResult:
    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_check_dropout_detects_crashed_process_and_reconnects(tmp_path: Path, monkeypatch) -> None:
    """The ffmpeg child dies mid-recording (source hung up); check_dropout must
    detect it on the very next poll (no stall wait needed for a hard exit),
    launch a fresh process against the same source, and report reconnected."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)

    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        ffmpeg_runner=_ConcatCapture(),
    )

    source = RecordingSource(kind="hls", uri="https://example.test/live.m3u8")
    pipeline.arm(job_id="job-1", source=source, encoder_profile="copy", loudness_regime="inherit")
    pipeline.start("job-1")
    assert len(handles) == 1
    first_handle = handles[0]
    first_handle.write(1000)

    # No dropout yet — the source is alive and producing bytes.
    result = pipeline.check_dropout("job-1")
    assert result.dropout_detected is False

    # Source hangs up: the ffmpeg child exits non-zero.
    first_handle.kill(returncode=1)
    result = pipeline.check_dropout("job-1")
    assert result.dropout_detected is True
    assert result.reconnected is True
    assert "exited unexpectedly" in result.detail

    # A second ffmpeg process was launched for the reconnect.
    assert len(handles) == 2
    second_handle = handles[1]
    assert second_handle is not first_handle
    second_handle.write(500)

    captured = pipeline.stop("job-1")
    assert captured.bytes_written == 1000 + 500
    assert Path(captured.capture_path).read_bytes() == b"x" * 1000 + b"x" * 500


def test_check_dropout_detects_stalled_source_after_threshold(tmp_path: Path) -> None:
    """The process stays alive but the output file stops growing (a stalled
    RTSP/SRT connection with no clean EOF). Must NOT false-positive on a
    single stalled poll (encoder buffering jitter) but must fire once the
    configured stall-poll threshold is reached."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        stall_polls_before_dropout=2,
    )
    source = RecordingSource(kind="rtsp", uri="rtsp://example.test/cam1")
    pipeline.arm(
        job_id="job-stall", source=source, encoder_profile="copy", loudness_regime="inherit"
    )
    pipeline.start("job-stall")
    handles[0].write(200)

    # First poll after growth: not stalled.
    assert pipeline.check_dropout("job-stall").dropout_detected is False
    # Poll #1 with no growth: below threshold, not yet a dropout.
    result = pipeline.check_dropout("job-stall")
    assert result.dropout_detected is False
    # Poll #2 with no growth: threshold reached — dropout confirmed + reconnect.
    result = pipeline.check_dropout("job-stall")
    assert result.dropout_detected is True
    assert result.reconnected is True
    assert "stalled" in result.detail
    assert len(handles) == 2  # reconnect launched a second process


def test_check_dropout_stops_reconnecting_past_the_attempt_cap(tmp_path: Path) -> None:
    """A source that never comes back must not hot-loop ffmpeg forever."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        max_reconnect_attempts=1,
    )
    source = RecordingSource(kind="rtsp", uri="rtsp://example.test/cam1")
    pipeline.arm(job_id="job-cap", source=source, encoder_profile="copy", loudness_regime="inherit")
    pipeline.start("job-cap")

    # First crash: reconnect allowed (attempt 1 of 1).
    handles[0].kill(returncode=1)
    result = pipeline.check_dropout("job-cap")
    assert result.reconnected is True
    assert len(handles) == 2

    # Second crash: cap already spent — detected, but NOT reconnected.
    handles[1].kill(returncode=1)
    result = pipeline.check_dropout("job-cap")
    assert result.dropout_detected is True
    assert result.reconnected is False
    assert "cap" in result.detail.lower()
    assert len(handles) == 2  # no third process launched


def test_service_tick_records_dropout_on_job_and_emits_alert(tmp_path: Path, monkeypatch) -> None:
    """End-to-end through RecordingService.tick: a dropout detected during a
    poll must durably bump the job's dropout_count/last_dropout_at AND land
    an alert-hub event a support bundle / dashboard can show."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    monkeypatch.setattr("civiccast.recording.runtime.run_ffprobe", _fake_ffprobe)

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
    )
    store = RecordingStore(factory)
    service = RecordingService(
        store,
        capture_pipeline=pipeline,
        asset_finalizer=ScheduledRecordingAssetFinalizer(factory),
        alert_sink=RecordingAlertSink(factory),
        clock=lambda: _NOW,
    )
    schedule = store.upsert_schedule(
        RecordingSchedule(
            station_id=_STATION,
            schedule_id="council-dropout",
            name="Council Dropout Test",
            source=RecordingSource(kind="hls", uri="https://example.test/live.m3u8"),
            recurrence=RecurrenceSpec(kind="one_shot", start=_NOW + timedelta(hours=1)),
            duration_seconds=3600,
            encoder_profile="copy",
            loudness_regime="inherit",
            enabled=True,
        )
    )
    job = service.record_now(schedule.schedule_id)
    assert job.state == "recording"
    assert job.dropout_count == 0
    handles[0].write(100)

    # Simulate the source hanging up mid-recording.
    handles[0].kill(returncode=1)

    detected = service.poll_active_recordings(_STATION)
    assert detected == 1

    reloaded = store.get_job(job.job_id)
    assert reloaded is not None
    assert reloaded.dropout_count == 1
    assert reloaded.last_dropout_at == _NOW
    assert reloaded.state == "recording"  # reconnect kept it alive

    # The event landed in the alert hub — support-bundle / dashboard visible.
    with factory() as session:
        rows = session.execute(select(AlertEventDb)).scalars().all()
    dropout_events = [r for r in rows if r.condition == "scheduled-recording-dropout"]
    assert len(dropout_events) == 1
    assert job.job_id in dropout_events[0].resource_ref

    # A second poll with no new dropout must NOT double-count.
    handles[-1].write(50)
    detected_again = service.poll_active_recordings(_STATION)
    assert detected_again == 0
    reloaded_again = store.get_job(job.job_id)
    assert reloaded_again is not None
    assert reloaded_again.dropout_count == 1


def test_poll_active_recordings_is_noop_without_check_dropout_support(tmp_path: Path) -> None:
    """A capture pipeline that doesn't implement check_dropout (e.g. a future
    non-ffmpeg engine) must degrade to a no-op, not crash the scheduler tick."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    store = RecordingStore(factory)

    class _MinimalPipeline:
        def arm(self, **_kwargs) -> None:
            return None

        def start(self, job_id: str) -> None:
            return None

        def finalize(self, job_id: str):
            raise AssertionError("not exercised")

        def stop(self, job_id: str):
            raise AssertionError("not exercised")

    service = RecordingService(
        store,
        capture_pipeline=_MinimalPipeline(),
        clock=lambda: _NOW,
    )
    schedule = store.upsert_schedule(
        RecordingSchedule(
            station_id=_STATION,
            schedule_id="no-dropout-support",
            name="No Dropout Support",
            source=RecordingSource(kind="hls", uri="https://example.test/live.m3u8"),
            recurrence=RecurrenceSpec(kind="one_shot", start=_NOW + timedelta(hours=1)),
            duration_seconds=3600,
            encoder_profile="copy",
            loudness_regime="inherit",
            enabled=True,
        )
    )
    job = service.record_now(schedule.schedule_id)
    assert job.state == "recording"

    assert service.poll_active_recordings(_STATION) == 0
    reloaded = store.get_job(job.job_id)
    assert reloaded is not None
    assert reloaded.dropout_count == 0


def test_record_dropout_store_method_increments_and_stamps(tmp_path: Path) -> None:
    """Direct store-level test: record_dropout increments the counter and
    stamps last_dropout_at without touching job state."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    store = RecordingStore(factory)
    job = store.create_job(
        RecordingJob(
            job_id="direct-dropout-job",
            station_id=_STATION,
            planned_start=_NOW,
            planned_end=_NOW + timedelta(hours=1),
            state="recording",
            source_snapshot=RecordingSource(kind="hls", uri="https://example.test/live.m3u8"),
            encoder_profile="copy",
        )
    )
    assert job.dropout_count == 0

    first = store.record_dropout(job.job_id, observed_at=_NOW)
    assert first.dropout_count == 1
    assert first.last_dropout_at == _NOW
    assert first.state == "recording"

    second_time = _NOW + timedelta(minutes=5)
    second = store.record_dropout(job.job_id, observed_at=second_time)
    assert second.dropout_count == 2
    assert second.last_dropout_at == second_time


def test_record_dropout_raises_on_unknown_job(tmp_path: Path) -> None:
    from civiccast.recording.store import RecordingJobNotFoundError

    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    store = RecordingStore(factory)
    with pytest.raises(RecordingJobNotFoundError):
        store.record_dropout("does-not-exist")


class _PausablePollHandle(_ScriptedHandle):
    """A ``_ScriptedHandle`` whose ``poll()`` pauses (once) after reporting
    the crash, releasing only when the test says so.

    ``check_dropout`` calls ``active.handle.poll()`` as its very first
    step, with no lock held (pre-fix). Gating there reproduces exactly the
    window the finding describes: check_dropout has read ``active`` and
    is about to decide "dropout, go terminate + reconnect" while
    completely unsynchronized with a concurrent ``stop()``.
    """

    def __init__(
        self, output_path: Path, *, entered: threading.Event, release: threading.Event
    ) -> None:
        super().__init__(output_path)
        self._entered = entered
        self._release = release
        self._paused_once = False

    def poll(self) -> int | None:
        result = super().poll()
        if result is not None and not self._paused_once:
            self._paused_once = True
            self._entered.set()
            self._release.wait(timeout=5.0)
        return result


def test_concurrent_stop_and_check_dropout_do_not_race(tmp_path: Path) -> None:
    """An operator's stop() and the scheduler's check_dropout() must never
    interleave on the same job's _ActiveCapture.

    Reproduces the reported race directly: check_dropout is parked right
    after it observes the crashed handle (inside its very first,
    unsynchronized ``active.handle.poll()`` call, pre-fix) while stop()
    runs concurrently on another thread. Pre-fix, ``stop()`` needs only
    ``self._lock`` for the dict-pop and then reads/finalizes the segment
    list with NO lock at all — so it races straight past check_dropout,
    pops the job, terminates the SAME still-live handle, and finalizes on
    the single-segment (pre-reconnect) list while check_dropout, released
    a moment later, goes on to append a segment and launch a reconnect
    ffmpeg process against a job that no longer exists in ``_active`` —
    an orphaned process/file, and a `stop()`-delivered capture whose
    segment count doesn't reflect what check_dropout was doing. With the
    fix, check_dropout and stop() for the SAME job_id are mutually
    exclusive for their entire critical sections, so stop() cannot start
    until check_dropout (including its reconnect) has completely
    finished.
    """
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: list[_ScriptedHandle] = []
    entered = threading.Event()
    release = threading.Event()

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        if not handles:
            handle = _PausablePollHandle(Path(args[-1]), entered=entered, release=release)
        else:
            handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        ffmpeg_runner=_ConcatCapture(),
    )
    source = RecordingSource(kind="hls", uri="https://example.test/live.m3u8")
    pipeline.arm(
        job_id="job-race", source=source, encoder_profile="copy", loudness_regime="inherit"
    )
    pipeline.start("job-race")
    handles[0].write(1000)
    handles[0].kill(returncode=1)

    dropout_result: dict[str, object] = {}
    dropout_exc: dict[str, BaseException] = {}

    def run_check_dropout() -> None:
        try:
            dropout_result["result"] = pipeline.check_dropout("job-race")
        except BaseException as exc:  # pragma: no cover - captured for assertion
            dropout_exc["exc"] = exc

    checker_thread = threading.Thread(target=run_check_dropout)
    checker_thread.start()
    assert entered.wait(timeout=5.0), "check_dropout never reached the paused poll()"

    stop_result: dict[str, object] = {}
    stop_exc: dict[str, BaseException] = {}

    def run_stop() -> None:
        try:
            stop_result["result"] = pipeline.stop("job-race")
        except BaseException as exc:  # pragma: no cover - captured for assertion
            stop_exc["exc"] = exc

    stopper_thread = threading.Thread(target=run_stop)
    stopper_thread.start()
    # Give stop() a real chance to race in before we let check_dropout
    # proceed. If stop() is (incorrectly) not blocked on a per-job lock,
    # it completes during this window — before check_dropout ever
    # appends the dead segment or installs a reconnect handle.
    stopper_thread.join(timeout=0.5)
    stop_finished_early = not stopper_thread.is_alive()

    release.set()
    checker_thread.join(timeout=5.0)
    stopper_thread.join(timeout=5.0)

    assert not stop_finished_early, (
        "stop() completed while check_dropout still had the same job's capture "
        "in flight — the per-job critical section is not atomic."
    )
    assert "exc" not in stop_exc, f"stop() raised: {stop_exc.get('exc')!r}"
    assert "exc" not in dropout_exc, f"check_dropout raised: {dropout_exc.get('exc')!r}"

    # With stop() forced to wait, check_dropout's reconnect fully lands
    # first (a second ffmpeg process, the dead segment appended) before
    # stop() ever reads the segment list — so the delivered capture must
    # be the two-segment merge, not a single truncated segment.
    dropout_res = dropout_result["result"]
    assert dropout_res.dropout_detected is True
    assert dropout_res.reconnected is True
    assert len(handles) == 2, "check_dropout must have launched the reconnect handle"

    captured = stop_result["result"]
    assert captured is not None
    merged_bytes = Path(captured.capture_path).read_bytes()
    assert b"x" * 1000 in merged_bytes


class _CriticalSectionMonitor:
    """Tracks how many of {check_dropout, stop, stop_arming} are inside
    their (whole-method) critical section at once, for any job — the
    invariant under test is that this never exceeds 1, regardless of
    which lock object (if any) each caller happened to acquire.

    Wired around each thread's call to check_dropout/stop/stop_arming
    (see ``run()`` in the test below) — the entire method body is
    documented to be the mutually-exclusive critical section. If two
    callers' spans overlap in time, two critical sections ran
    concurrently — mutual exclusion is broken.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active_count = 0
        self.max_concurrent = 0
        self.overlap_pairs: list[tuple[str, str]] = []
        self._current_callers: list[str] = []

    @contextmanager
    def enter(self, caller: str) -> Iterator[None]:
        with self._lock:
            self.active_count += 1
            self.max_concurrent = max(self.max_concurrent, self.active_count)
            if self._current_callers:
                self.overlap_pairs.append((self._current_callers[-1], caller))
            self._current_callers.append(caller)
        try:
            yield
        finally:
            with self._lock:
                self.active_count -= 1
                self._current_callers.remove(caller)


class _ThreeCallerHandle(_ScriptedHandle):
    """A ``_ScriptedHandle`` that lets a test pin down the exact
    create/destroy-lifecycle gap the round-2 finding describes.

    ``terminate()`` is where every one of check_dropout/stop/stop_arming
    actually mutates the job's ffmpeg state — it registers with a shared
    ``_CriticalSectionMonitor`` and then blocks on a caller-specific gate
    (if given, else a short fixed pause) before returning. A caller
    merely blocked trying to ACQUIRE a lock never reaches here, so this
    only measures genuine overlap of the mutating work itself — not
    "the method was called."
    """

    def __init__(
        self,
        output_path: Path,
        *,
        monitor: _CriticalSectionMonitor,
        caller: str,
        gate: threading.Event | None = None,
        entered: threading.Event | None = None,
    ) -> None:
        super().__init__(output_path)
        self._monitor = monitor
        self._caller = caller
        self._gate = gate
        self._entered = entered

    def terminate(self, *, grace_seconds: float = 5.0) -> int:
        with self._monitor.enter(self._caller):
            if self._entered is not None:
                self._entered.set()
            if self._gate is not None:
                self._gate.wait(timeout=5.0)
            else:
                # No explicit gate for this caller — hold briefly anyway so
                # a genuine overlap with another caller's critical section
                # has a real (not just theoretical) chance to be observed.
                time.sleep(0.2)
            return super().terminate(grace_seconds=grace_seconds)


def test_three_callers_never_overlap_across_lock_create_destroy(tmp_path: Path) -> None:
    """The round-2 adversarial finding: with a per-job lock dict entry
    deleted right after release, a THIRD caller for the same job_id can
    fetch a brand-new lock object while an earlier caller still
    holds/awaits the OLD one — so two "serialized" critical sections run
    concurrently anyway. Pairwise (2-thread) exclusion is not enough to
    catch this; it only shows up across three overlapping lifecycles.

    Reproduces the exact gap directly, at the point each caller resolves
    "which lock object do I use for this job_id":

      1. check_dropout (A) resolves its lock and enters its critical
         section, then is held open (paused inside terminate()).
      2. stop (B) resolves ITS lock reference for the same job_id while A
         is still inside — under the old scheme this is the SAME object
         A holds, so B correctly blocks on ``lock.acquire()``.
      3. A finishes and releases/discards its lock. This is the exact
         instant the old scheme deletes the dict entry.
      4. stop_arming (C) resolves ITS lock reference for the same job_id
         immediately after step 3, before B's pending ``acquire()`` has
         woken up. Under the old scheme the dict entry is gone, so C
         creates a FRESH lock, acquires it uncontended, and enters its
         critical section — while B's blocked acquire on the orphaned old
         lock is about to succeed too. B and C now both run "inside the
         lock" concurrently.

    A single instance-level lock (or any registry that never deletes a
    live entry) has no such gap: whichever object C resolves in step 4 is
    the SAME object B is already waiting on, so C cannot get in first.

    The test drives the pipeline's real ``_job_lock_for``/lock-acquire
    call if present (old scheme); against an implementation with no such
    per-job registry (the fix), the monkeypatch hooks are simply never
    invoked and the callers fall back to whatever single serializing lock
    the implementation actually uses — so the assertions below (based on
    a shared critical-section monitor, not on internals) are what
    actually prove or disprove mutual exclusion either way.
    """
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    monitor = _CriticalSectionMonitor()

    dropout_gate = threading.Event()
    dropout_entered = threading.Event()

    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        if not handles:
            handle = _ThreeCallerHandle(
                Path(args[-1]),
                monitor=monitor,
                caller="check_dropout",
                gate=dropout_gate,
                entered=dropout_entered,
            )
        else:
            # The reconnect handle check_dropout installs as the job's new
            # active.handle — this is what stop()/stop_arming() will call
            # terminate() on. A short fixed pause (see _ThreeCallerHandle)
            # gives a genuine overlap between stop's and stop_arming's
            # critical sections a real chance to be observed, not just
            # asserted from lock identity.
            handle = _ThreeCallerHandle(
                Path(args[-1]), monitor=monitor, caller=f"reconnect-handle-{len(handles)}"
            )
        handles.append(handle)
        return handle

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        ffmpeg_runner=_ConcatCapture(),
    )
    source = RecordingSource(kind="hls", uri="https://example.test/live.m3u8")
    pipeline.arm(
        job_id="job-three", source=source, encoder_profile="copy", loudness_regime="inherit"
    )
    pipeline.start("job-three")
    handles[0].write(1000)
    handles[0].kill(returncode=1)  # ffmpeg child exited -> check_dropout will detect + reconnect

    # --- Choreograph the exact "resolve lock reference" timing ---------
    # If the implementation exposes the old per-job lock registry, wrap
    # _job_lock_for so the test can observe/control exactly when each
    # caller resolves its lock object, and wrap the release path so we
    # know precisely when A's lock is discarded. Against the fixed
    # implementation (no such method), these hooks are inert — the real
    # pipeline calls are unaffected and the test instead simply proves
    # (or fails to prove) mutual exclusion via the monitor timings below.
    b_resolved_lock = threading.Event()
    a_discarded = threading.Event()
    c_may_resolve = threading.Event()
    resolved_locks: dict[str, object] = {}

    if hasattr(pipeline, "_job_lock_for"):
        real_job_lock_for = pipeline._job_lock_for
        real_discard = pipeline._discard_job_lock
        call_count = {"n": 0}

        def patched_job_lock_for(job_id: str):
            call_count["n"] += 1
            n = call_count["n"]
            if n == 3:  # stop_arming (C) resolving its reference
                # Force C to resolve its lock reference only after A has
                # discarded its lock — the exact window the finding
                # describes — and only after B has already grabbed (and is
                # blocked on) the old one. The wait must happen BEFORE the
                # real lookup, not after: the lookup itself is what decides
                # whether C gets the (still-present) old lock or a fresh one.
                assert c_may_resolve.wait(timeout=5.0)
            lock = real_job_lock_for(job_id)
            if n == 2:  # stop (B) resolving its reference
                resolved_locks["stop"] = lock
                b_resolved_lock.set()
            elif n == 3:
                resolved_locks["stop_arming"] = lock
            return lock

        def patched_discard(job_id: str) -> None:
            real_discard(job_id)
            a_discarded.set()
            # Let C proceed to resolve its lock reference now that A's
            # entry is gone from the registry.
            c_may_resolve.set()

        pipeline._job_lock_for = patched_job_lock_for  # type: ignore[method-assign]
        pipeline._discard_job_lock = patched_discard  # type: ignore[method-assign]
    else:
        # No per-job registry to intercept — nothing to gate; let C
        # proceed whenever it naturally gets scheduled.
        c_may_resolve.set()

    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def run(name: str, fn: Callable[[], object]) -> None:
        # NOTE: deliberately does NOT wrap the whole call in the monitor —
        # a caller blocked trying to ACQUIRE the real lock is correctly
        # "not yet in the critical section" and must not count as an
        # overlap. Overlap is measured only where actual mutation of the
        # shared _ActiveCapture happens: inside the fake handles'
        # terminate() (see _ThreeCallerHandle / fake_start_ffmpeg above).
        try:
            results[name] = fn()
        except BaseException as exc:  # pragma: no cover - captured for assertion
            errors[name] = exc

    # Caller 1 (A): check_dropout. Its terminate() call (closing the dead
    # segment) is gated open by dropout_gate — it stays inside its
    # critical section until we release it below.
    t_dropout = threading.Thread(
        target=run, args=("check_dropout", lambda: pipeline.check_dropout("job-three"))
    )
    t_dropout.start()
    assert dropout_entered.wait(timeout=5.0), "check_dropout never entered its critical section"

    # Caller 2 (B): stop(), started while A is still inside. It resolves
    # its lock reference (the SAME object A holds, pre-fix) and then
    # blocks trying to acquire it.
    t_stop = threading.Thread(target=run, args=("stop", lambda: pipeline.stop("job-three")))
    t_stop.start()
    if hasattr(pipeline, "_job_lock_for"):
        assert b_resolved_lock.wait(timeout=5.0), "stop() never resolved its lock reference"
    else:
        t_stop.join(timeout=0.2)
    assert t_stop.is_alive(), (
        "stop() returned/raised while check_dropout was still mid-critical-section."
    )

    # Release A. It finishes its critical section and (pre-fix) discards
    # its lock entry — which is precisely when C is allowed to resolve.
    dropout_gate.set()

    # Caller 3 (C): stop_arming(), the "duplicated operator click" / next
    # scheduler tick retry — resolves its lock reference only once A has
    # discarded (see patched_discard above), i.e. exactly in the gap the
    # finding describes, while B is still parked on the old lock.
    t_arming = threading.Thread(
        target=run, args=("stop_arming", lambda: pipeline.stop_arming("job-three"))
    )
    t_arming.start()

    t_dropout.join(timeout=5.0)
    t_stop.join(timeout=5.0)
    t_arming.join(timeout=5.0)

    assert not errors, f"a caller raised unexpectedly: {errors}"
    if hasattr(pipeline, "_job_lock_for"):
        assert a_discarded.is_set(), "check_dropout's lock was never discarded"
        if "stop" in resolved_locks and "stop_arming" in resolved_locks:
            assert resolved_locks["stop"] is resolved_locks["stop_arming"], (
                "stop() and stop_arming() resolved DIFFERENT lock objects for the same "
                "job_id — the lock registry handed out a fresh lock while an earlier "
                "caller still held a reference to the old one."
            )
    assert monitor.max_concurrent == 1, (
        f"two or more of check_dropout/stop/stop_arming were inside their critical "
        f"section at the same time (max_concurrent={monitor.max_concurrent}); "
        f"overlap pairs: {monitor.overlap_pairs}"
    )


class _BlockingConcatRunner:
    """Fake ``run_ffmpeg`` for the concat-merge step whose call for one
    specific job blocks on a controllable barrier, simulating a hung ffmpeg
    merge (corrupt/truncated segment, disk contention). Calls for any other
    job pass straight through to a real (fast) concat, so a second job's
    finalize genuinely completes rather than merely "not raising"."""

    def __init__(
        self, *, blocked_job_id: str, entered: threading.Event, release: threading.Event
    ) -> None:
        self._blocked_job_id = blocked_job_id
        self._entered = entered
        self._release = release

    def __call__(self, args: list[str]):
        concat_list = Path(args[args.index("-i") + 1])
        if self._blocked_job_id in concat_list.name:
            self._entered.set()
            self._release.wait(timeout=5.0)
        output_path = Path(args[-1])
        merged = b""
        for line in concat_list.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("file "):
                continue
            segment_path = Path(line.split("'")[1])
            merged += segment_path.read_bytes()
        output_path.write_bytes(merged)
        return _FakeFfmpegResult(returncode=0, stdout="", stderr="")


def test_stop_does_not_hold_job_lock_across_ffmpeg_merge(tmp_path: Path) -> None:
    """The round-3 adversarial finding: stop() must not hold the single
    instance-level ``_job_lock`` across the unbounded ffmpeg concat merge
    in ``_finalize_segments``. If it does, a hung/slow merge for job A
    freezes ``check_dropout``/``stop``/``stop_arming`` for EVERY other job
    on the box (``poll_active_recordings`` loops all jobs on one thread).

    Job A has a reconnect (so ``stop()`` takes the merge path) and its
    merge is gated open on a barrier. While A's merge is blocked, job B
    (a completely separate, single-segment job with no merge needed) must
    still be stoppable — proving the merge runs outside the lock that
    would otherwise serialize it against B.

    Against the pre-fix code (b1ab5b02), stop() holds ``_job_lock`` for
    its ENTIRE body including the ``_finalize_segments`` call, so B's
    ``stop()`` blocks until A's merge is released — this assertion fails.
    """
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: dict[str, list[_ScriptedHandle]] = {"A": [], "B": []}

    def fake_start_ffmpeg_for(job_key: str):
        def _start(args: list[str], **_kwargs) -> _ScriptedHandle:
            handle = _ScriptedHandle(Path(args[-1]))
            handles[job_key].append(handle)
            return handle

        return _start

    merge_entered = threading.Event()
    merge_release = threading.Event()
    runner = _BlockingConcatRunner(
        blocked_job_id="job-a", entered=merge_entered, release=merge_release
    )

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg_for("A"),
        ffmpeg_runner=runner,
    )
    source = RecordingSource(kind="hls", uri="https://example.test/live.m3u8")

    # Job A: force a reconnect so stop() must take the merge path.
    pipeline.arm(job_id="job-a", source=source, encoder_profile="copy", loudness_regime="inherit")
    pipeline.start("job-a")
    handles["A"][0].write(1000)
    handles["A"][0].kill(returncode=1)
    dropout = pipeline.check_dropout("job-a")
    assert dropout.reconnected is True
    handles["A"][1].write(500)

    # Job B: a second, independent, single-segment job (no merge needed —
    # its stop() returns fast once the lock is actually released promptly).
    pipeline._ffmpeg_starter = fake_start_ffmpeg_for("B")
    pipeline.arm(job_id="job-b", source=source, encoder_profile="copy", loudness_regime="inherit")
    pipeline.start("job-b")
    handles["B"][0].write(200)

    stop_a_result: dict[str, object] = {}
    stop_a_exc: dict[str, BaseException] = {}

    def run_stop_a() -> None:
        try:
            stop_a_result["result"] = pipeline.stop("job-a")
        except BaseException as exc:  # pragma: no cover - captured for assertion
            stop_a_exc["exc"] = exc

    thread_a = threading.Thread(target=run_stop_a)
    thread_a.start()
    assert merge_entered.wait(timeout=5.0), "job A's merge never started"

    # While A's merge is blocked, B must still be independently stoppable —
    # this is the crux of the fix: the lock must already be released.
    start = time.monotonic()
    stop_b_result = pipeline.stop("job-b")
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, (
        f"stop('job-b') took {elapsed:.2f}s while job A's merge was blocked — "
        "it was serialized behind A's unbounded ffmpeg merge under _job_lock."
    )
    assert stop_b_result.bytes_written == 200

    merge_release.set()
    thread_a.join(timeout=5.0)
    assert "exc" not in stop_a_exc, f"stop('job-a') raised: {stop_a_exc.get('exc')!r}"
    captured_a = stop_a_result["result"]
    assert captured_a is not None
    assert Path(captured_a.capture_path).read_bytes() == b"x" * 1000 + b"x" * 500


def test_finalize_segments_merge_timeout_fails_only_that_job(tmp_path: Path) -> None:
    """A hung ffmpeg concat merge must raise (via run_ffmpeg's timeout)
    rather than block forever, and that failure must be scoped to the one
    job whose merge hung — proven here by finalizing a second, unrelated
    job cleanly right after."""
    _engine, factory, _target_dir = _make_store_and_dirs(tmp_path)
    handles: list[_ScriptedHandle] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        handle = _ScriptedHandle(Path(args[-1]))
        handles.append(handle)
        return handle

    def fake_slow_ffmpeg_runner(args: list[str], **kwargs):
        # Mirrors run_ffmpeg's real contract: subprocess.run(..., timeout=X)
        # raises TimeoutExpired when the child doesn't finish in time.
        raise subprocess.TimeoutExpired(cmd=["ffmpeg", *args], timeout=kwargs.get("timeout", 1))

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        ffmpeg_runner=fake_slow_ffmpeg_runner,
    )
    source = RecordingSource(kind="hls", uri="https://example.test/live.m3u8")
    pipeline.arm(
        job_id="job-hang", source=source, encoder_profile="copy", loudness_regime="inherit"
    )
    pipeline.start("job-hang")
    handles[0].write(1000)
    handles[0].kill(returncode=1)
    dropout = pipeline.check_dropout("job-hang")
    assert dropout.reconnected is True
    handles[1].write(500)

    with pytest.raises(subprocess.TimeoutExpired):
        pipeline.stop("job-hang")

    # The job's own bookkeeping was already popped before the merge ran
    # (the merge is outside the lock) — a retry attempt correctly reports
    # "not active" rather than re-entering a half-torn-down state.
    with pytest.raises(RuntimeError, match="No active ffmpeg capture"):
        pipeline.stop("job-hang")

    # A second, unrelated job is completely unaffected: arm/start/stop it
    # end to end with the real (fast) concat runner and confirm it finalizes.
    pipeline2 = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
        ffmpeg_runner=_ConcatCapture(),
    )
    pipeline2.arm(
        job_id="job-fine", source=source, encoder_profile="copy", loudness_regime="inherit"
    )
    pipeline2.start("job-fine")
    handles[-1].write(300)
    result = pipeline2.stop("job-fine")
    assert result.bytes_written == 300


def test_ffmpeg_concat_quote_escapes_apostrophe_in_path() -> None:
    """Direct unit test for the concat-demuxer quoting helper: a literal
    apostrophe in a segment path must be escaped per ffmpeg's own
    single-quote convention (close quote, escaped quote, reopen quote —
    the same rule as POSIX shell single-quoting), or the generated
    concat list corrupts/misparses at the apostrophe."""
    path = Path("/data/O'Brien's Recordings/job-seg1.ts")
    quoted = _ffmpeg_concat_quote(path)
    assert quoted == "/data/O'\\''Brien'\\''s Recordings/job-seg1.ts"
    # Round-trip sanity: wrapping in the demuxer's outer single-quotes and
    # unescaping via the documented rule recovers the original path.
    wrapped = f"'{quoted}'"
    # ffmpeg's own unescape: 'X'\''Y' -> X'Y (concatenate quoted runs,
    # dropping the escape sequence's own quote pairs).
    unescaped = wrapped[1:-1].replace("'\\''", "'")
    assert unescaped == path.as_posix()
