#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run an empirical CivicCast caption runtime benchmark.

This script is intended for Sprint 0.5 release evidence on the Blackwell
self-hosted runner. It loads mono signed 16-bit PCM WAV audio, runs the same
runtime adapter used by live captions, and emits machine-readable JSON with
latency, transcript, optional WER, and best-effort GPU memory samples.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from civiccast.captions.benchmark import load_wav_chunks, run_caption_benchmark
from civiccast.captions.models import CustomVocabulary
from civiccast.captions.runtime import FasterWhisperRuntime, FasterWhisperRuntimeUnavailableError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path, help="Mono 16-bit PCM WAV input.")
    parser.add_argument("--truth", type=Path, help="UTF-8 ground-truth transcript for WER.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    parser.add_argument("--model", default="large-v3", help="faster-whisper model name/path.")
    parser.add_argument("--device", default="cuda", help="Runtime device, usually cuda or cpu.")
    parser.add_argument("--compute-type", default="int8_float16", help="CTranslate2 compute type.")
    parser.add_argument("--language", default="en", help="Language hint passed to faster-whisper.")
    parser.add_argument("--beam-size", default=5, type=int, help="Beam size for decoding.")
    parser.add_argument("--chunk-seconds", default=4.0, type=float, help="Seconds per audio chunk.")
    parser.add_argument("--max-chunks", type=int, help="Limit chunks for smoke benchmarks.")
    parser.add_argument(
        "--vocabulary-term",
        action="append",
        default=[],
        help="Civic term/name to bias; repeat for multiple terms.",
    )
    parser.add_argument("--initial-prompt", help="Optional initial prompt for civic vocabulary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.audio.exists():
        print(f"FAIL: audio file does not exist: {args.audio}", file=sys.stderr)
        print("Next step: provide a mono 16-bit PCM WAV fixture with --audio.", file=sys.stderr)
        return 2

    truth = args.truth.read_text(encoding="utf-8") if args.truth else None
    vocabulary = CustomVocabulary(
        terms=args.vocabulary_term,
        initial_prompt=args.initial_prompt,
    )
    runtime = FasterWhisperRuntime(
        model_size_or_path=args.model,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
        language=args.language,
    )

    try:
        chunks = load_wav_chunks(
            args.audio,
            chunk_seconds=args.chunk_seconds,
            max_chunks=args.max_chunks,
        )
        result = run_caption_benchmark(
            runtime,
            chunks,
            audio_path=args.audio,
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            vocabulary=vocabulary,
            ground_truth=truth,
        )
    except FasterWhisperRuntimeUnavailableError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print(
            "Next step: install CivicCast with `.[captions-runtime]` on the runner "
            "and confirm CUDA/cuDNN with scripts/verify-blackwell-runtime.py.",
            file=sys.stderr,
        )
        return 3
    except Exception as exc:
        print(f"FAIL: benchmark failed: {exc}", file=sys.stderr)
        print(
            "Next step: confirm the audio is mono signed 16-bit PCM WAV and that "
            "the selected model/device/compute-type are available on this host.",
            file=sys.stderr,
        )
        return 4

    rendered = result.to_json()
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
