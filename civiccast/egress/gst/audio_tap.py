# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic rolling WAV segments for the GStreamer live-caption audio fork."""

from __future__ import annotations

import os
import re
import threading
import wave
from pathlib import Path
from typing import BinaryIO, Final

TAP_SAMPLE_RATE_HZ: Final[int] = 16_000
_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"chunk-(\d{6})\.wav(?:\.partial)?\Z")


class RollingWavSegmentWriter:
    """Turn a stream of mono signed-16-bit PCM into atomically published WAVs."""

    def __init__(
        self,
        tap_dir: str | Path,
        *,
        segment_seconds: float = 5.0,
        sample_rate_hz: int = TAP_SAMPLE_RATE_HZ,
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
        self._raw_file: BinaryIO | None = None
        self._wave_file: wave.Wave_write | None = None
        self._partial_path: Path | None = None
        self._target_path: Path | None = None
        self._written_bytes = 0
        self._closed = False
        self._lock = threading.Lock()

    def _discover_next_index(self) -> int:
        observed = -1
        for path in self.tap_dir.rglob("chunk-*.wav*"):
            match = _SEGMENT_RE.fullmatch(path.name)
            if match is not None and path.is_file():
                observed = max(observed, int(match.group(1)))
        return observed + 1

    def _open_segment(self) -> None:
        if self._next_index > 999_999:
            raise RuntimeError("caption audio tap exhausted its six-digit segment sequence")
        target = self.tap_dir / f"chunk-{self._next_index:06d}.wav"
        partial = target.with_suffix(".wav.partial")
        if target.exists() or partial.exists():
            raise RuntimeError(f"caption audio tap segment path already exists: {target}")
        raw_file = partial.open("xb")
        try:
            wave_file = wave.open(raw_file, "wb")  # noqa: SIM115 - same lifecycle
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(self.sample_rate_hz)
        except Exception:
            raw_file.close()
            partial.unlink(missing_ok=True)
            raise
        self._raw_file = raw_file
        self._wave_file = wave_file
        self._partial_path = partial
        self._target_path = target
        self._written_bytes = 0

    def _publish_segment(self) -> None:
        wave_file = self._wave_file
        raw_file = self._raw_file
        partial = self._partial_path
        target = self._target_path
        if wave_file is None or raw_file is None or partial is None or target is None:
            return
        try:
            wave_file.close()
            raw_file.flush()
            os.fsync(raw_file.fileno())
            raw_file.close()
            if target.exists():
                raise RuntimeError(f"caption audio tap refuses to overwrite: {target}")
            partial.replace(target)
        finally:
            if not raw_file.closed:
                raw_file.close()
            self._wave_file = None
            self._raw_file = None
            self._partial_path = None
            self._target_path = None
            self._written_bytes = 0
        self._next_index += 1

    def write_pcm_s16le(self, pcm: bytes | bytearray | memoryview) -> None:
        """Append whole mono s16le samples, rotating at the configured duration."""

        body = bytes(pcm)
        if len(body) % 2:
            raise ValueError("caption audio tap accepts only whole 16-bit samples")
        if not body:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("caption audio tap writer is closed")
            offset = 0
            while offset < len(body):
                if self._wave_file is None:
                    self._open_segment()
                available = self._segment_bytes - self._written_bytes
                count = min(available, len(body) - offset)
                assert self._wave_file is not None
                self._wave_file.writeframesraw(body[offset : offset + count])
                self._written_bytes += count
                offset += count
                if self._written_bytes == self._segment_bytes:
                    self._publish_segment()

    def close(self) -> None:
        """Publish a non-empty trailing segment and make subsequent writes fail."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._written_bytes:
                self._publish_segment()
            elif self._wave_file is not None:
                self._wave_file.close()
                if self._raw_file is not None:
                    self._raw_file.close()
                if self._partial_path is not None:
                    self._partial_path.unlink(missing_ok=True)

    def __enter__(self) -> RollingWavSegmentWriter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["TAP_SAMPLE_RATE_HZ", "RollingWavSegmentWriter"]
