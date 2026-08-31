# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Anti-theater proof: scheduled recording captures a real network stream
into a real, playable VOD asset (S21, migration 0056).

The Recording page (S21) has claimed since it first rendered that scheduled
recording can capture SDI/HDMI *and* network streams (RTSP/SRT/HLS/RTMP/
MPEG-TS/NDI), but nothing in the test suite ever drove the real
:class:`~civiccast.recording.runtime.FfmpegScheduledCapturePipeline` against
a real, continuously-streamed source end to end. Every existing recording
test injects a stub/scripted capture pipeline (by design -- the service
layer's own tests must not depend on ffmpeg). This test is the missing
network-stream proof: no stubs anywhere in the capture path.

A real ffmpeg process streams a real (non-trivial, multi-second, audio+video)
source to a local UDP/MPEG-TS listener -- the same shape an RTSP/SRT/RTMP/
MPEG-TS camera or encoder would present to the station, and the one network
kind (``mpegts``) that needs no external listener/relay to prove. The real
:class:`RecordingService` (backed by a real SQLite-backed
:class:`~civiccast.recording.store.RecordingStore`) drives the real
:class:`FfmpegScheduledCapturePipeline` and the real
:class:`~civiccast.recording.runtime.ScheduledRecordingAssetFinalizer`
end to end: ``record_now_from_source`` (arm + start) -> real ffmpeg captures
the live stream -> ``stop_job`` (finalize) -> a real :class:`Asset` row,
whose file this test independently re-probes with ffprobe.

Regression this pins: before the ``-flush_packets 1`` fix in
``FfmpegScheduledCapturePipeline._launch``, ffmpeg's mpegts muxer buffered
output in the process's own memory (observed on this box: ~256 KiB) before
an OS-level write, and ``FfmpegProcessHandle.terminate()`` maps to Win32
``TerminateProcess`` -- an unconditional kill that gives ffmpeg no chance to
flush or write a trailer (unlike POSIX SIGTERM, which ffmpeg traps to shut
down cleanly). Every capture whose total output never crossed that buffer
threshold -- which includes any short recording, and always includes the
final unflushed tail of a longer one -- finalized to a 0-byte file, and
``finalize``/``stop`` raised "ffmpeg created a zero-byte recording file" so
the job landed ``failed`` with no asset produced. Without the fix this test
reproducibly fails the same way on a real Windows box.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.live.models import RecordingTarget
from civiccast.live.recording_paths import DEFAULT_RECORDING_TARGET_ID
from civiccast.recording.models import RecordingSource
from civiccast.recording.runtime import (
    FfmpegScheduledCapturePipeline,
    ScheduledRecordingAssetFinalizer,
    ScheduledRecordingSettings,
)
from civiccast.recording.service import RecordingService
from civiccast.recording.store import RecordingStore
from civiccast.schedule.ingest import run_ffprobe
from civiccast.schedule.models import ASSET_STATE_RECORDED, Asset

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH; network-capture live proof skipped",
)

# Real, decodable, multi-second audio+video content -- not a single static
# frame. libx264 + a sine tone, muxed to MPEG-TS and streamed over loopback
# UDP in real time (``-re``), the same "continuous packets arriving over the
# wire" shape a live RTSP/SRT/RTMP/MPEG-TS source presents to the capture
# pipeline. Generated via ffmpeg's own lavfi sources rather than a checked-in
# video fixture so the proof is fully self-contained and portable to CI.
_STREAM_DURATION_SECONDS = 30
# ffmpeg's own format probe on the receiving end (avformat_find_stream_info
# against a live mpegts/UDP source) reliably takes several real seconds
# before it even opens the output file -- measured on this box, 5-6s.
# ``_CAPTURE_SECONDS`` has to comfortably outlast that probe AND leave
# enough real capture time behind it, or every run (fixed or not) fails the
# same way ("ffmpeg did not create a recording segment") for a reason that
# has nothing to do with the regression this test exists to pin.
_CAPTURE_SECONDS = 11.0
_STARTUP_WAIT_SECONDS = 1.5

# Deliberately low: total output accumulated during the real (post-probe)
# capture time must stay well under ffmpeg's own mpegts-muxer write-buffer
# threshold (measured on this box: ~256 KiB) so this test actually exercises
# the "capture window never crosses a flush boundary" case the
# ``-flush_packets 1`` fix addresses -- at ~165 kbps combined that's roughly
# 120-150 KiB over the real capture window, comfortably short of 256 KiB. A
# higher-bitrate encode would flush "for free" on some runs and make this a
# flaky, not-actually-pinning regression check.
_VIDEO_BITRATE = "80k"
_AUDIO_BITRATE = "32k"


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextmanager
def _udp_mpegts_source(port: int) -> Iterator[None]:
    """Stream real, decodable audio+video to ``udp://127.0.0.1:<port>`` in
    real time for the lifetime of the context -- the local stand-in for a
    live RTSP/SRT/RTMP/MPEG-TS network source."""

    sender = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-re",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=640x360:rate=25:duration={_STREAM_DURATION_SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=44100:duration={_STREAM_DURATION_SECONDS}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-b:v",
            _VIDEO_BITRATE,
            "-maxrate",
            _VIDEO_BITRATE,
            "-bufsize",
            "160k",
            "-g",
            "25",
            "-c:a",
            "aac",
            "-b:a",
            _AUDIO_BITRATE,
            "-f",
            "mpegts",
            f"udp://127.0.0.1:{port}?pkt_size=1316",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(_STARTUP_WAIT_SECONDS)
        yield
    finally:
        if sender.poll() is None:
            sender.terminate()
            try:
                sender.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sender.kill()
                sender.wait(timeout=10)


@pytest.fixture
def service_and_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'r.sqlite'}", future=True)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    capture_root = tmp_path / "captures"
    capture_root.mkdir()
    with factory() as sess:
        sess.add(
            RecordingTarget(
                recording_target_id=DEFAULT_RECORDING_TARGET_ID,
                name="Local recordings",
                target_uri=capture_root.as_uri(),
            )
        )
        sess.commit()

    store = RecordingStore(factory)
    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(capture_subdir="scheduled-recordings"),
    )
    finalizer = ScheduledRecordingAssetFinalizer(factory)
    service = RecordingService(store, capture_pipeline=pipeline, asset_finalizer=finalizer)
    try:
        yield service, factory
    finally:
        engine.dispose()


def test_network_stream_capture_produces_real_playable_asset(service_and_engine) -> None:
    """arm -> start -> (real ffmpeg captures a real live UDP/MPEG-TS
    source) -> stop/finalize -> a real Asset backed by a real, ffprobe-
    verified media file with nonzero duration, matching dimensions, and the
    expected codecs. No stub anywhere in the capture path."""

    service, factory = service_and_engine
    port = _free_udp_port()

    with _udp_mpegts_source(port):
        source = RecordingSource(kind="mpegts", uri=f"udp://127.0.0.1:{port}?pkt_size=1316")
        job = service.record_now_from_source(
            station_id="proof-station",
            source=source,
            duration_seconds=3600,  # long planned window; this test stops it explicitly
            encoder_profile="copy",
            loudness_regime="inherit",
            job_id="network-capture-proof-job",
        )
        assert job.state == "recording", (
            f"expected the job to be recording a live source, got {job.state!r}: "
            f"{job.failure_reason}"
        )

        time.sleep(_CAPTURE_SECONDS)

        done = service.stop_job(job.job_id)

    assert done.state == "done", f"expected done, got {done.state!r}: {done.failure_reason}"
    assert done.bytes_written > 0, "capture pipeline reported zero bytes written"
    assert done.asset_id is not None

    with factory() as sess:
        asset = sess.get(Asset, done.asset_id)

    assert asset is not None, f"finalize reported asset_id={done.asset_id!r} but no row exists"
    assert asset.state == ASSET_STATE_RECORDED
    assert asset.file_path is not None
    capture_path = Path(asset.file_path)
    assert capture_path.exists(), f"asset row points at a missing file: {capture_path}"

    on_disk_size = capture_path.stat().st_size
    assert on_disk_size > 0, "captured file exists but is empty on disk"
    assert asset.file_size_bytes == on_disk_size

    # Independently re-probe the captured file (not trusting the finalizer's
    # own ffprobe call) -- the actual bar this test exists to clear.
    probe = run_ffprobe(capture_path)
    assert probe.codec_video == "h264"
    assert probe.codec_audio == "aac"
    assert probe.width_px == 640
    assert probe.height_px == 360
    assert probe.duration_seconds is not None and probe.duration_seconds >= 1, (
        f"captured file's real duration was {probe.duration_seconds!r}s; "
        f"expected at least a few seconds of {_CAPTURE_SECONDS}s of real streamed content"
    )

    # Cross-check against the Asset row's own stamped values (DC-1-style
    # provenance: what the finalizer wrote must match what's really there).
    assert asset.codec_video == "h264"
    assert asset.codec_audio == "aac"
    assert asset.width_px == 640
    assert asset.height_px == 360
    assert asset.duration_seconds == probe.duration_seconds
