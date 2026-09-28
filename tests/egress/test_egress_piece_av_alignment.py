# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Every emitted prepared piece must be A/V-aligned (U59).

Live C9, 2026-09-27 19:15:49 (government, reload_id=13)::

    switch-at-shorter-leg reload_id=13 video_end=23466.200 audio_end=23471.381
    trimmed=none spread=5.181 bound=2.000 bound_exceeded=yes

That leg was the day's first TWO-piece leg (its 38 single-piece predecessors
all spread 0.57-0.80 s), and the aired result was a 4.148 s frozen picture
(``freezedetect`` on the keeper segment: freeze_start 1.7, freeze_end 5.848).

The pieces themselves carry the asymmetry.  The non-trim emission path is a
``-ss <inpoint> -i <conform> -t <duration> -c copy`` slice: the audio starts at
the requested inpoint, but the video can only resume at the next keyframe, so
each piece is **audio-long by the video's own start lag**.  Measured on the
live education pair (same C9 bytes): segment 1 emitted audio start 1.400 /
duration 593.813 against video start 2.253 / duration 593.000 -- a 0.853 s lag,
reproduced offline from that leg's own conform (head lag 0.533 s, span delta
0.480 s).

The engine chains a leg's pieces per stream (a video concat and a parallel
audio concat, each rebased independently), so a leg's spread is the SUM of its
pieces' lags.  ``_SWITCH_SHORTER_LEG_MAX_TRIM_S`` (2.000 s) is a single-asset
value; a two-piece leg multiplies past it, fail-opens, and the mux is left with
no video input for the spread -- the frozen picture.

These tests hold the invariant at the layer that creates it: the emitter.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from civiccast.egress.models import EgressSourceSegment
from civiccast.egress.preparer import SourcePreparer

_FPS = 30
_FRAME = 1.0 / _FPS
_GOP_SECONDS = 2.0
#: The canonical conform's IDR cadence, measured on the station's own cache
#: (``80cdcd4c`` and ``9f10c9e3``: an exact 2.000 s grid at 1.400 + 2k).
_GOP_FRAMES = int(_GOP_SECONDS * _FPS)
#: One AAC frame at 48 kHz. The alignment pass pins each stream to the video's
#: own first and last packet, so the audio's first and last kept packet can each
#: sit up to one AAC frame away from the video's -- the whole tolerance this
#: suite asserts, against per-piece lags of 0.53-0.85 s before the fix.
_AUDIO_FRAME = 1024 / 48000
_ALIGN_TOLERANCE = 2 * _AUDIO_FRAME


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _make_conform(path: Path, *, seconds: float = 12.0) -> None:
    """A small stand-in for a conform-cache asset: strict IDR grid, AAC audio.

    ``-g`` with ``-keyint_min`` and ``-sc_threshold 0`` is what makes the grid
    strict -- the emitted piece's video lag is exactly the grid phase, which is
    what the live conforms carry.
    """
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate={_FPS}:duration={seconds:g}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=48000:duration={seconds:g}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-g",
        str(_GOP_FRAMES),
        "-keyint_min",
        str(_GOP_FRAMES),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-f",
        "mpegts",
        str(path),
    )


def _packet_pts(path: Path, stream: str) -> list[float]:
    """Every packet PTS of one stream, read raw from the file itself.

    NOT ``stream=start_time,duration``: the mpegts container's declared duration
    is a different number from the span its packets actually carry (measured on
    the fixture below: a piece whose packets span 5.248 s is declared 5.141 s
    for audio). The pads see packets, so this test measures packets.
    """
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            "-i",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [
        float(row.split(",")[0]) for row in out.splitlines() if row.split(",")[0] not in ("", "N/A")
    ]


def _stream_window(path: Path, stream: str) -> tuple[float, float, float]:
    """``(first_pts, last_pts, span)`` for one stream of a piece."""
    pts = _packet_pts(path, stream)
    assert pts, f"no {stream} packets in {path.name}"
    return pts[0], pts[-1], pts[-1] - pts[0]


def _emit(tmp_path: Path, conform: Path, *, inpoint: float, duration: float) -> Path:
    preparer = SourcePreparer(work_dir=tmp_path)
    output = tmp_path / f"piece-{inpoint:g}.ts"
    segment = EgressSourceSegment(
        label="U59 probe window",
        path=str(conform),
        duration_seconds=duration,
        inpoint_seconds=inpoint,
    )
    preparer._emit_prepared_from_cache(
        conform,
        segment,
        source_path=conform,
        output_path=output,
        loudness_status="ok",
        measured_lufs=None,
        normalized=False,
    )
    return output


@pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0,
    reason="ffmpeg is required to build the fixture and emit the piece",
)
def test_emitted_piece_starts_both_streams_together(tmp_path: Path) -> None:
    """A mid-GOP inpoint must not leave the piece audio-long by the start lag.

    Inpoint 3.3 s on a 2.000 s IDR grid is mid-GOP, so the video can only resume
    at its own keyframe and a raw copy-out is audio-long by that lag -- measured
    on this exact fixture at 0.770666 s, the per-piece shape that summed to the
    live C9 government spread of 5.181 s against a 2.000 s single-asset bound.
    Both streams are pinned to the video's own first and last packets, so the
    piece's two streams cover one window: one AAC frame at each end at worst.
    """
    conform = tmp_path / "conform.ts"
    _make_conform(conform)

    piece = _emit(tmp_path, conform, inpoint=3.3, duration=6.0)

    video_start, _, video_span = _stream_window(piece, "v:0")
    audio_start, _, audio_span = _stream_window(piece, "a:0")
    assert abs(video_start - audio_start) <= _ALIGN_TOLERANCE, (
        f"piece streams must start together: video {video_start} vs audio {audio_start}"
    )
    assert abs(video_span - audio_span) <= _ALIGN_TOLERANCE, (
        f"piece streams must span one window: video {video_span} vs audio {audio_span}"
    )


@pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0,
    reason="ffmpeg is required to build the fixture and emit the piece",
)
def test_alignment_pass_is_what_removes_the_lag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion above must be able to fail: disable the pass and it does.

    A test that passes with the fix disabled would be measuring nothing. The
    same emit, with ``_align_piece_stream_starts`` answering ``None`` (the
    pre-U59 emitter), is audio-long by the video's start lag -- 0.77 s on this
    fixture, an order of magnitude over the tolerance the other test asserts.
    """
    conform = tmp_path / "conform.ts"
    _make_conform(conform)
    monkeypatch.setattr(SourcePreparer, "_align_piece_stream_starts", lambda *a, **k: None)

    piece = _emit(tmp_path, conform, inpoint=3.3, duration=6.0)

    _, _, video_span = _stream_window(piece, "v:0")
    _, _, audio_span = _stream_window(piece, "a:0")
    assert audio_span - video_span > _ALIGN_TOLERANCE * 10, (
        "the unaligned slice must show the defect this suite exists for: "
        f"video span {video_span} vs audio span {audio_span}"
    )


@pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0,
    reason="ffmpeg is required to build the fixture and emit the piece",
)
def test_two_piece_leg_does_not_accumulate_lag(tmp_path: Path) -> None:
    """The live arithmetic: a leg's spread is the SUM of its pieces' lags.

    The engine chains a leg's pieces per stream, so two pieces cut at different
    grid phases summed their lags before the fix (measured on this fixture:
    0.770666 + 0.770666 = 1.541 s). With every piece pinned to its own video,
    the leg sums one audio frame at each end of each piece -- 0.085 s for the
    pair, against the live leg's 5.181 s and the 2.000 s fail-open bound.
    """
    conform = tmp_path / "conform.ts"
    _make_conform(conform)

    total = 0.0
    for inpoint in (3.3, 5.1):
        piece = _emit(tmp_path, conform, inpoint=inpoint, duration=6.0)
        video_start, _, video_span = _stream_window(piece, "v:0")
        audio_start, _, audio_span = _stream_window(piece, "a:0")
        total += abs(video_span - audio_span)
        assert abs(video_start - audio_start) <= _ALIGN_TOLERANCE
    assert total <= 2 * _ALIGN_TOLERANCE, f"two-piece leg lag must not accumulate: {total:.3f}s"


@pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0,
    reason="ffmpeg is required to build the fixture and emit the piece",
)
def test_piece_without_a_video_stream_still_emits(tmp_path: Path) -> None:
    """The C7 fail-open contract: a probe that cannot answer must not block.

    An audio-only piece has no video packet to pin to, so the alignment pass
    answers ``None`` and the piece is emitted on the historic path -- the step
    is an addition, never a gate.
    """
    conform = tmp_path / "audio-only.ts"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=6",
        "-c:a",
        "aac",
        "-f",
        "mpegts",
        str(conform),
    )

    piece = _emit(tmp_path, conform, inpoint=1.0, duration=4.0)

    assert piece.exists() and piece.stat().st_size > 0
    _, _, audio_span = _stream_window(piece, "a:0")
    # The ``-t`` cut lands a little under the request (measured 3.861333 s for a
    # 4.0 s window); the point is that the piece carries the window's audio.
    assert audio_span > 3.8
