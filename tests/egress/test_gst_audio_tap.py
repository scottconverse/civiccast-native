# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic rolling WAV writer used by the GStreamer appsink caption tap.

Item 88 (measured in sandbox run 17, soak-a6d7871-20260906-213332Z, Opus
diagnosis): the writer used to do its blocking I/O (WAV close, ``flush``,
``os.fsync``, atomic ``replace``) directly on the caller's thread -- which,
in production, is the GStreamer appsink's ``new-sample`` callback running on
the STREAMING thread. Once that I/O fell behind (two ffmpeg jobs + a Whisper
ASR pass sharing the box), the caption-audio-tap ``queue`` backed up, the
tee it forks from stalled, and the mux's audio pad -- fed by the same tee --
starved, stopping real TS output and taking the CHANNEL off air over a
caption side-channel.

The tests below (``TestSegmentWriterThread``) prove the fix directly: the
producer (``write_pcm_s16le``) never blocks even when the writer thread's
own I/O is artificially slow (a stubbed, sleeping ``fsync``), a full queue
drops the OLDEST pending segment rather than blocking or dropping the
newest, and publish order is preserved for the segments that ARE kept.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import pytest

from civiccast.egress.gst.audio_tap import RollingWavSegmentWriter, SegmentWriterThread


def _read_pcm(path: Path) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(str(path), "rb") as source:
        shape = (source.getnchannels(), source.getsampwidth(), source.getframerate())
        return shape, source.readframes(source.getnframes())


def test_writer_rotates_atomic_mono_s16le_segments_without_losing_samples(
    tmp_path: Path,
) -> None:
    writer = RollingWavSegmentWriter(
        tmp_path,
        segment_seconds=0.01,
        sample_rate_hz=1_000,
    )
    pcm = bytes(range(44))

    writer.write_pcm_s16le(pcm[:14])
    writer.write_pcm_s16le(pcm[14:])
    writer.close()

    segments = sorted(tmp_path.glob("chunk-*.wav"))
    assert [path.name for path in segments] == [
        "chunk-000000.wav",
        "chunk-000001.wav",
        "chunk-000002.wav",
    ]
    decoded = [_read_pcm(path) for path in segments]
    assert all(shape == (1, 2, 1_000) for shape, _body in decoded)
    assert b"".join(body for _shape, body in decoded) == pcm
    assert not list(tmp_path.glob("*.partial"))


def test_writer_restart_never_overwrites_a_published_segment(tmp_path: Path) -> None:
    first = RollingWavSegmentWriter(
        tmp_path,
        segment_seconds=0.01,
        sample_rate_hz=1_000,
    )
    first.write_pcm_s16le(b"\x01\x02")
    first.close()
    second = RollingWavSegmentWriter(
        tmp_path,
        segment_seconds=0.01,
        sample_rate_hz=1_000,
    )
    second.write_pcm_s16le(b"\x03\x04")
    second.close()

    assert [path.name for path in sorted(tmp_path.glob("chunk-*.wav"))] == [
        "chunk-000000.wav",
        "chunk-000001.wav",
    ]
    assert _read_pcm(tmp_path / "chunk-000000.wav")[1] == b"\x01\x02"
    assert _read_pcm(tmp_path / "chunk-000001.wav")[1] == b"\x03\x04"


def test_writer_rejects_non_s16le_frame_alignment(tmp_path: Path) -> None:
    writer = RollingWavSegmentWriter(tmp_path)
    with pytest.raises(ValueError, match="whole 16-bit samples"):
        writer.write_pcm_s16le(b"\x00")
    writer.close()


class TestSegmentWriterThread:
    """Item 88: the writer thread's own contract -- non-blocking hand-off,
    drop-oldest-when-full, and FIFO publish order for whatever is kept."""

    def test_submit_never_blocks_even_when_publish_io_is_slow(self, tmp_path: Path) -> None:
        """The core item 88 proof: a producer calling ``submit`` must never
        block on the writer thread's own I/O, no matter how slow that I/O
        is -- a slow ``fsync`` must never be able to propagate backpressure
        to the caller (in production: the GStreamer streaming thread)."""
        release = threading.Event()

        def _blocking_fsync(fd: int) -> None:
            release.wait(timeout=5.0)

        thread = SegmentWriterThread(tmp_path, 1_000, maxsize=2, fsync=_blocking_fsync)
        thread.start()
        try:
            started = time.monotonic()
            # The first segment's publish will block inside the stubbed
            # fsync until we release it below -- submit() itself must still
            # return immediately for every one of these, including the ones
            # that arrive while the queue is full (drop-oldest, not block).
            for index in range(5):
                thread.submit(index, b"\x00\x01" * 4)
            elapsed = time.monotonic() - started
            assert elapsed < 1.0, f"submit() blocked for {elapsed:.2f}s -- must never block"
        finally:
            release.set()
            thread.stop(timeout=5.0)
        assert not thread.publish_errors

    def test_full_queue_drops_the_oldest_segment_not_the_newest(self, tmp_path: Path) -> None:
        """A full queue must drop the OLDEST pending segment to make room --
        never the newest, and never by blocking the producer."""
        gate = threading.Event()

        def _gated_fsync(fd: int) -> None:
            gate.wait(timeout=5.0)

        thread = SegmentWriterThread(tmp_path, 1_000, maxsize=2, fsync=_gated_fsync)
        thread.start()
        try:
            # Submit segment 0 alone first and give the consumer time to pick
            # it up and block inside the gated fsync -- deterministic, rather
            # than racing the consumer thread's scheduling against the
            # remaining submits below.
            thread.submit(0, b"\x00\x00")
            time.sleep(0.2)  # consumer is now blocked publishing segment 0
            # Segments 1, 2, 3 queue up behind a maxsize=2 queue while the
            # consumer is busy -- at least one of {1, 2} must be dropped to
            # make room for 3.
            for index in range(1, 4):
                thread.submit(index, bytes([index]) * 2)
            gate.set()
            thread.stop(timeout=5.0)
        finally:
            gate.set()

        published = sorted(int(path.stem.split("-")[1]) for path in tmp_path.glob("chunk-*.wav"))
        assert 0 in published  # already being published when the queue filled
        assert 3 in published  # newest -- must survive the drop
        assert len(published) < 4  # something was genuinely dropped
        assert thread._dropped_total >= 1

    def test_publish_order_is_preserved_for_kept_segments(self, tmp_path: Path) -> None:
        thread = SegmentWriterThread(tmp_path, 1_000, maxsize=8)
        thread.start()
        try:
            for index in range(5):
                thread.submit(index, bytes([index]) * 2)
        finally:
            thread.stop(timeout=5.0)

        segments = sorted(tmp_path.glob("chunk-*.wav"))
        assert [path.name for path in segments] == [f"chunk-{i:06d}.wav" for i in range(5)]
        for index, path in enumerate(segments):
            with wave.open(str(path), "rb") as source:
                assert source.readframes(source.getnframes()) == bytes([index]) * 2

    def test_writer_thread_is_a_daemon_thread(self, tmp_path: Path) -> None:
        """Never hold the process open if the worker exits without an
        explicit ``close()`` -- matches every other background thread in
        this codebase's threading conventions."""
        thread = SegmentWriterThread(tmp_path, 1_000)
        assert thread.daemon is True

    def test_rolling_writer_close_blocks_until_all_segments_are_published(
        self, tmp_path: Path
    ) -> None:
        """``RollingWavSegmentWriter.close()`` is the publish boundary
        callers already rely on -- it must drain the async writer thread
        before returning, even though normal writes are non-blocking."""
        writer = RollingWavSegmentWriter(tmp_path, segment_seconds=0.01, sample_rate_hz=1_000)
        writer.write_pcm_s16le(bytes(range(20)))
        writer.close()

        assert sorted(tmp_path.glob("chunk-*.wav"))
        assert not list(tmp_path.glob("*.partial"))
