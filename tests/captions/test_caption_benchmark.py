# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for caption runtime benchmark evidence helpers."""

from __future__ import annotations

import json
import wave
from collections.abc import Iterable
from pathlib import Path

import pytest

from civiccast.captions.benchmark import (
    CaptionBenchmarkGpuSample,
    load_wav_chunks,
    percentile,
    run_caption_benchmark,
    word_error_rate,
)
from civiccast.captions.models import AudioChunk, CaptionHypothesis, CustomVocabulary


def _write_wav(path: Path, *, sample_rate: int = 16_000, seconds: float = 1.0) -> None:
    frame_count = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


class FakeRuntime:
    def __init__(self) -> None:
        self.seen_vocabulary: CustomVocabulary | None = None

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        self.seen_vocabulary = vocabulary
        for chunk in chunks:
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-h",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text="motion carries",
                confidence=0.94,
            )


def test_load_wav_chunks_splits_mono_pcm_audio(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    _write_wav(audio_path, seconds=1.2)

    chunks = load_wav_chunks(audio_path, chunk_seconds=0.5)

    assert [chunk.chunk_id for chunk in chunks] == [
        "meeting-00000",
        "meeting-00001",
        "meeting-00002",
    ]
    assert chunks[0].start_seconds == 0
    assert chunks[0].end_seconds == 0.5
    assert chunks[-1].end_seconds == 1.2


def test_load_wav_chunks_rejects_non_mono_wav(tmp_path: Path) -> None:
    audio_path = tmp_path / "stereo.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 100)

    with pytest.raises(ValueError, match="mono WAV"):
        load_wav_chunks(audio_path)


def test_word_error_rate_normalizes_civic_transcripts() -> None:
    assert word_error_rate("Motion carries, 7-0.", "motion carried 7 0") == 0.25
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "unexpected words") == 1.0


def test_percentile_uses_nearest_rank_for_small_samples() -> None:
    assert percentile([0.1, 0.4, 0.2], 0.95) == 0.4


def test_run_caption_benchmark_returns_machine_readable_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "meeting.wav"
    _write_wav(audio_path, seconds=1.0)
    chunks = load_wav_chunks(audio_path, chunk_seconds=1.0)
    runtime = FakeRuntime()
    sample = CaptionBenchmarkGpuSample(
        name="NVIDIA GeForce RTX 5070 Ti",
        used_mb=1024.0,
        free_mb=15_000.0,
        total_mb=16_024.0,
    )
    monkeypatch.setattr("civiccast.captions.benchmark.sample_gpu", lambda: sample)

    result = run_caption_benchmark(
        runtime,
        chunks,
        audio_path=audio_path,
        model="large-v3",
        device="cuda",
        compute_type="int8_float16",
        vocabulary=CustomVocabulary(terms=["Councilmember Rivera"]),
        ground_truth="motion carries",
    )

    payload = json.loads(result.to_json())
    assert result.transcript == "motion carries"
    assert result.word_error_rate == 0
    assert result.chunk_count == 1
    assert payload["gpu_before"]["name"] == "NVIDIA GeForce RTX 5070 Ti"
    assert runtime.seen_vocabulary == CustomVocabulary(terms=["Councilmember Rivera"])
