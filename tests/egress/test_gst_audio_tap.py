# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic rolling WAV writer used by the GStreamer appsink caption tap."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from civiccast.egress.gst.audio_tap import RollingWavSegmentWriter


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
