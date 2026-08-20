#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Prove real native caption transcription with every network socket denied."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
import wave
from pathlib import Path

from civiccast.captions.models import AudioChunk
from civiccast.captions.runtime import FasterWhisperRuntime


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-word", action="append", default=[])
    args = parser.parse_args()

    model_dir = args.model_dir.resolve()
    os.environ["CIVICCAST_WHISPER_MODEL_PATH"] = str(model_dir)
    os.environ["CIVICCAST_WHISPER_DEVICE"] = "cpu"
    os.environ["CIVICCAST_WHISPER_COMPUTE_TYPE"] = "int8"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    socket_attempts: list[str] = []

    class DeniedSocket(socket.socket):
        def connect(self, address: object) -> None:
            socket_attempts.append(repr(address))
            raise OSError("network denied by native caption proof")

        def connect_ex(self, address: object) -> int:
            socket_attempts.append(repr(address))
            return 10013

    def denied_create_connection(
        address: object,
        *args: object,
        **kwargs: object,
    ) -> socket.socket:
        del args, kwargs
        socket_attempts.append(repr(address))
        raise OSError("network denied by native caption proof")

    socket.socket = DeniedSocket  # type: ignore[misc]
    socket.create_connection = denied_create_connection

    with wave.open(str(args.audio.resolve()), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if channels != 1 or sample_width != 2 or not frames:
        raise SystemExit("audio fixture must be non-empty mono signed 16-bit PCM")

    chunk = AudioChunk(
        chunk_id="native-offline-caption-proof",
        start_seconds=0.0,
        end_seconds=len(frames) / 2 / sample_rate,
        sample_rate_hz=sample_rate,
        pcm_s16le=frames,
    )
    runtime = FasterWhisperRuntime(
        model_size_or_path="large-v3",
        device="cpu",
        compute_type="int8",
        language="en",
        vad_filter=False,
    )
    started = time.perf_counter()
    hypotheses = list(runtime.transcribe([chunk]))
    elapsed = time.perf_counter() - started
    transcript = " ".join(item.text for item in hypotheses).strip()
    normalized = _normalized(transcript)
    missing = [word for word in args.expected_word if _normalized(word) not in normalized]
    passed = bool(transcript) and not missing and not socket_attempts
    result = {
        "status": "PASS" if passed else "FAIL",
        "audio": str(args.audio.resolve()),
        "audio_seconds": chunk.end_seconds,
        "model_dir": str(model_dir),
        "model_source": "packaged-local-path",
        "device": runtime.device,
        "compute_type": runtime.compute_type,
        "network_policy": "socket-connect-denied",
        "network_attempts": socket_attempts,
        "elapsed_seconds": round(elapsed, 3),
        "hypothesis_count": len(hypotheses),
        "transcript": transcript,
        "expected_words": args.expected_word,
        "missing_expected_words": missing,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
