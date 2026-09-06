# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic rolling WAV segments for the GStreamer live-caption audio fork.

Item 88 (measured in sandbox run 17, soak-a6d7871-20260906-213332Z, Opus
diagnosis): every worker reached PLAYING and pushed real TS output at
~3.2 Mbps for 26-100s, then output stopped and the 10s stall watchdog killed
the worker. Root cause: this writer used to do its blocking I/O (WAV close,
``flush``, ``os.fsync``, atomic ``replace``) directly on the appsink's
``new-sample`` callback -- which runs on the GStreamer STREAMING thread, the
same thread the caption-audio-tap ``queue`` element's default (non-leaky,
1s-deep) buffering can only absorb for so long. Once ``fsync``/rename took
long enough (two ffmpeg jobs + a Whisper ASR pass sharing the box), the
queue backed up, the tee it forks from stalled, and the mpegtsmux audio pad
that shares the same tee starved -- taking the CHANNEL off air over a
caption side-channel that was never supposed to be able to do that.

The fix: this module now only ever does fast, in-memory work
(``write_pcm_s16le`` appends PCM bytes to a plain ``bytearray`` under a
lock that guards ONLY that bookkeeping, never I/O) and hands a finished
segment's bytes to ``SegmentWriterThread``, a dedicated background thread
that owns all the blocking I/O. The hand-off itself
(``SegmentWriterThread.submit``) is non-blocking: a bounded queue that
drops the OLDEST pending segment (not the newest, and never by blocking)
when full, logging the drop at most once a minute. A slow disk now degrades
caption continuity -- a dropped few seconds of caption audio -- instead of
ever being able to stall the tee, and therefore the mux, and therefore the
channel.

Companion fix on the GStreamer graph side (``engine.py``'s
``_build_audio_tap``): the ``caption_audio_tap_queue`` element is now
``leaky=2`` (downstream -- drop the OLDEST buffered data rather than block
upstream) with a much deeper buffer cap, and the appsink is ``drop=True``.
Both layers exist because they guard different failure points: the queue
protects the tee from a slow appsink callback; this module's own bounded
queue protects the appsink callback from a slow disk. Removing either layer
re-opens a path for the caption side-channel to take the channel off air.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Final

TAP_SAMPLE_RATE_HZ: Final[int] = 16_000
_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"chunk-(\d{6})\.wav(?:\.partial)?\Z")

#: How many finished-but-unpublished segments the writer thread's queue holds
#: before it starts dropping the OLDEST one to accept a new one. 8 segments
#: at the default 5s ``segment_seconds`` is 40s of caption audio buffered
#: against transient disk contention -- generous headroom without letting an
#: indefinitely wedged disk grow unbounded memory.
_DEFAULT_QUEUE_MAXSIZE: Final[int] = 8

#: Rate-limit for the "queue full, dropped a segment" warning -- item 88's
#: own root cause was an I/O path calling into a lock-holding fsync on the
#: streaming thread; a log line printed on every single drop under sustained
#: contention would itself become a (much smaller, but real) source of
#: streaming-thread-adjacent overhead. One line per minute is plenty to see
#: the condition on a live soak without spamming it.
_DROP_LOG_INTERVAL_S: Final[float] = 60.0


class SegmentWriterThread(threading.Thread):
    """Background daemon thread that owns every blocking write for the
    caption audio tap -- WAV encode, ``flush``, ``os.fsync``, and the atomic
    ``partial.replace(target)`` publish. Runs OFF the GStreamer streaming
    thread; see the module docstring for why that boundary is load-bearing.

    ``submit()`` is the only method the producer (the appsink's
    ``new-sample`` callback, via ``RollingWavSegmentWriter``) ever calls, and
    it never blocks: a full queue drops its OLDEST entry (never the newest,
    and never by waiting) to make room, then enqueues the new segment. If a
    concurrent consumer races the drop and refills the slot first, the NEW
    segment is dropped instead rather than retrying in a way that could
    block -- either way ``submit`` returns immediately.
    """

    def __init__(
        self,
        tap_dir: Path,
        sample_rate_hz: int,
        *,
        maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
        fsync: Callable[[int], None] = os.fsync,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(name="caption-audio-tap-writer", daemon=True)
        self.tap_dir = tap_dir
        self.sample_rate_hz = sample_rate_hz
        self._fsync = fsync
        self._monotonic = monotonic
        self._queue: queue.Queue[tuple[int, bytes] | None] = queue.Queue(maxsize=maxsize)
        self._dropped_total = 0
        self._last_drop_log_t = 0.0
        self._drop_lock = threading.Lock()
        self.publish_errors: list[BaseException] = []
        self._errors_lock = threading.Lock()

    def submit(self, index: int, pcm: bytes) -> None:
        """Non-blocking hand-off of one finished segment's PCM bytes."""

        try:
            self._queue.put_nowait((index, pcm))
            return
        except queue.Full:
            pass
        dropped = True
        try:
            self._queue.get_nowait()  # drop the OLDEST pending segment
        except queue.Empty:
            dropped = False  # a consumer drained it first; no drop needed
        try:
            self._queue.put_nowait((index, pcm))
        except queue.Full:
            # A consumer refilled the freed slot before we could -- drop
            # THIS segment rather than ever retrying/blocking.
            dropped = True
        if dropped:
            self._log_drop()

    def _log_drop(self) -> None:
        with self._drop_lock:
            self._dropped_total += 1
            now = self._monotonic()
            if now - self._last_drop_log_t < _DROP_LOG_INTERVAL_S:
                return
            self._last_drop_log_t = now
            total = self._dropped_total
        print(
            f"WARN: caption audio tap writer queue full; dropped {total} segment(s) "
            "so far (rate-limited: at most one line per 60s)",
            flush=True,
        )

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:  # stop() sentinel
                return
            index, pcm = item
            try:
                self._publish(index, pcm)
            except Exception as exc:  # never let the writer thread die silently
                with self._errors_lock:
                    self.publish_errors.append(exc)
                print(
                    f"ERROR: caption audio tap writer failed to publish segment {index}: {exc}",
                    flush=True,
                )

    def _publish(self, index: int, pcm: bytes) -> None:
        target = self.tap_dir / f"chunk-{index:06d}.wav"
        partial = target.with_suffix(".wav.partial")
        if target.exists() or partial.exists():
            raise RuntimeError(f"caption audio tap segment path already exists: {target}")
        raw_file: BinaryIO = partial.open("xb")
        try:
            wave_file = wave.open(raw_file, "wb")  # noqa: SIM115 - same lifecycle
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(self.sample_rate_hz)
            wave_file.writeframesraw(pcm)
            wave_file.close()
            raw_file.flush()
            self._fsync(raw_file.fileno())
            raw_file.close()
            partial.replace(target)
        except Exception:
            if not raw_file.closed:
                raw_file.close()
            partial.unlink(missing_ok=True)
            raise

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Drain the queue and join. Blocking by design -- called from
        ``RollingWavSegmentWriter.close()``, which is the publish boundary
        callers already expect to wait on."""
        self._queue.put(None)
        self.join(timeout=timeout)


class RollingWavSegmentWriter:
    """Turn a stream of mono signed-16-bit PCM into atomically published WAVs.

    ``write_pcm_s16le`` never blocks on disk I/O: it only appends bytes to an
    in-memory buffer and, once a segment's worth has accumulated, hands the
    finished segment to a ``SegmentWriterThread`` for publishing. See the
    module docstring for why (item 88)."""

    def __init__(
        self,
        tap_dir: str | Path,
        *,
        segment_seconds: float = 5.0,
        sample_rate_hz: int = TAP_SAMPLE_RATE_HZ,
        queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
        fsync: Callable[[int], None] = os.fsync,
    ) -> None:
        if segment_seconds <= 0:
            raise ValueError("caption audio tap segment_seconds must be positive")
        if sample_rate_hz <= 0:
            raise ValueError("caption audio tap sample_rate_hz must be positive")
        self.tap_dir = Path(tap_dir).expanduser()
        self.tap_dir.mkdir(parents=True, exist_ok=True)
        self.segment_seconds = float(segment_seconds)
        self.sample_rate_hz = int(sample_rate_hz)
        frames = max(1, round(self.segment_seconds * self.sample_rate_hz))
        self._segment_bytes = frames * 2
        self._next_index = self._discover_next_index()
        self._buffer = bytearray()
        self._closed = False
        self._lock = threading.Lock()  # guards ONLY the in-memory buffer/index bookkeeping
        self._writer_thread = SegmentWriterThread(
            self.tap_dir, self.sample_rate_hz, maxsize=queue_maxsize, fsync=fsync
        )
        self._writer_thread.start()

    def _discover_next_index(self) -> int:
        observed = -1
        for path in self.tap_dir.rglob("chunk-*.wav*"):
            match = _SEGMENT_RE.fullmatch(path.name)
            if match is not None and path.is_file():
                observed = max(observed, int(match.group(1)))
        return observed + 1

    def _submit_locked(self, segment: bytes) -> None:
        """Caller must hold ``self._lock``. Hands one finished segment to
        the writer thread -- non-blocking (see ``SegmentWriterThread.submit``)."""
        index = self._next_index
        self._next_index += 1
        self._writer_thread.submit(index, segment)

    def write_pcm_s16le(self, pcm: bytes | bytearray | memoryview) -> None:
        """Append whole mono s16le samples, rotating at the configured duration.

        Non-blocking: this method only touches the in-memory buffer and the
        writer thread's non-blocking queue -- it never waits on disk I/O, so
        it is safe to call from a GStreamer streaming-thread callback."""

        body = bytes(pcm)
        if len(body) % 2:
            raise ValueError("caption audio tap accepts only whole 16-bit samples")
        if not body:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("caption audio tap writer is closed")
            self._buffer.extend(body)
            while len(self._buffer) >= self._segment_bytes:
                segment = bytes(self._buffer[: self._segment_bytes])
                del self._buffer[: self._segment_bytes]
                self._submit_locked(segment)

    def close(self) -> None:
        """Publish a non-empty trailing segment and make subsequent writes
        fail. Blocks until the writer thread has drained its queue -- the
        publish boundary callers already rely on (segments existing on disk
        once ``close()`` returns)."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._buffer:
                segment = bytes(self._buffer)
                self._buffer.clear()
                self._submit_locked(segment)
        self._writer_thread.stop()

    def __enter__(self) -> RollingWavSegmentWriter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["TAP_SAMPLE_RATE_HZ", "RollingWavSegmentWriter", "SegmentWriterThread"]
