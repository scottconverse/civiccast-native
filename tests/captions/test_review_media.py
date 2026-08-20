# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bounded media evidence for caption review."""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.captions.models import AudioChunk, CaptionCue
from civiccast.captions.review_media import (
    CaptionReviewClipError,
    build_caption_review_clip,
    cue_relative_to_audio_evidence,
    resolve_caption_review_source,
    verify_caption_review_audio_evidence,
    verify_caption_review_audio_evidence_for_cue,
    write_caption_review_audio_evidence,
)
from civiccast.stream._ffmpeg import FfmpegResult


def _cue(*, start: float = 65.1, end: float = 68.9) -> CaptionCue:
    return CaptionCue(
        cue_id="cue-1",
        start_seconds=start,
        end_seconds=end,
        text="motion carries",
        confidence=0.62,
        low_confidence=True,
    )


def test_retains_and_verifies_the_exact_live_audio_window(tmp_path: Path) -> None:
    chunk = AudioChunk(
        chunk_id="gov-tap-1",
        start_seconds=10.0,
        end_seconds=11.0,
        sample_rate_hz=16_000,
        pcm_s16le=b"\x01\x00" * 16_000,
    )
    output = tmp_path / "evidence" / "window.wav"

    evidence = write_caption_review_audio_evidence(chunk, output)

    assert verify_caption_review_audio_evidence(evidence) == output.resolve()
    assert evidence.source_start_seconds == 10.0
    relative = cue_relative_to_audio_evidence(
        _cue(start=10.25, end=10.75),
        evidence,
    )
    assert relative.start_seconds == 0.25
    assert relative.end_seconds == 0.75
    assert list(output.parent.glob("*.tmp")) == []

    output.write_bytes(output.read_bytes() + b"tampered")
    with pytest.raises(CaptionReviewClipError, match="size changed"):
        verify_caption_review_audio_evidence(evidence)


def test_retained_audio_evidence_must_cover_the_whole_cue(tmp_path: Path) -> None:
    chunk = AudioChunk(
        chunk_id="audio-1",
        start_seconds=10.0,
        end_seconds=15.0,
        sample_rate_hz=16_000,
        pcm_s16le=b"\0\0" * 16_000 * 5,
    )
    evidence = write_caption_review_audio_evidence(chunk, tmp_path / "evidence.wav")

    assert verify_caption_review_audio_evidence_for_cue(
        evidence,
        _cue(start=12.0, end=14.5),
    ) == (tmp_path / "evidence.wav").resolve()

    with pytest.raises(CaptionReviewClipError, match="cover"):
        verify_caption_review_audio_evidence_for_cue(
            evidence,
            _cue(start=9.5, end=12.0),
        )
    with pytest.raises(CaptionReviewClipError, match="cover"):
        verify_caption_review_audio_evidence_for_cue(
            evidence,
            _cue(start=14.0, end=15.5),
        )


def test_builds_bounded_mono_wav_around_the_cue(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"source")
    captured: dict[str, object] = {}

    def runner(args: list[str], *, timeout: float | None = None) -> FfmpegResult:
        captured["args"] = args
        captured["timeout"] = timeout
        Path(args[-1]).write_bytes(b"RIFF-review-clip")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    clip = build_caption_review_clip(source, _cue(), ffmpeg_runner=runner)

    try:
        args = captured["args"]
        assert isinstance(args, list)
        assert args[:4] == ["-nostdin", "-hide_banner", "-loglevel", "error"]
        assert args[args.index("-ss") + 1] == "63.100"
        assert args[args.index("-t") + 1] == "7.800"
        assert args[args.index("-i") + 1] == str(source.resolve())
        assert args[-8:-1] == ["-vn", "-ac", "1", "-ar", "16000", "-f", "wav"]
        assert captured["timeout"] == 30.0
        assert clip.read_bytes() == b"RIFF-review-clip"
    finally:
        clip.unlink(missing_ok=True)


def test_caps_long_cues_to_fifteen_seconds(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"source")
    captured: list[str] = []

    def runner(args: list[str], *, timeout: float | None = None) -> FfmpegResult:
        del timeout
        captured.extend(args)
        Path(args[-1]).write_bytes(b"RIFF")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    clip = build_caption_review_clip(source, _cue(start=5.0, end=90.0), ffmpeg_runner=runner)
    try:
        assert captured[captured.index("-t") + 1] == "15.000"
    finally:
        clip.unlink(missing_ok=True)


def test_removes_partial_output_when_ffmpeg_fails(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"source")
    output: Path | None = None

    def runner(args: list[str], *, timeout: float | None = None) -> FfmpegResult:
        nonlocal output
        del timeout
        output = Path(args[-1])
        output.write_bytes(b"partial")
        return FfmpegResult(returncode=1, stdout="", stderr="invalid media")

    with pytest.raises(CaptionReviewClipError, match="could not decode"):
        build_caption_review_clip(source, _cue(), ffmpeg_runner=runner)

    assert output is not None
    assert not output.exists()


@pytest.mark.parametrize(
    ("stored_path", "expected"),
    [
        (
            "C:\\CivicCast\\recordings\\meeting.mp4",
            Path("C:\\CivicCast\\recordings\\meeting.mp4"),
        ),
        (
            "file:///C:/CivicCast/recordings/meeting.mp4",
            Path("C:/CivicCast/recordings/meeting.mp4"),
        ),
        ("https://media.example/meeting.mp4", None),
        ("relative/meeting.mp4", None),
    ],
)
def test_resolves_only_local_absolute_asset_media(
    stored_path: str,
    expected: Path | None,
) -> None:
    assert resolve_caption_review_source(stored_path) == expected
