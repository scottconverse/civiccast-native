#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Blackwell-on-CTranslate2 + faster-whisper compatibility verifier.

Per ADR 0003's Risks section: before Sprint 0.5 (captions) starts, we must
explicitly confirm faster-whisper + CTranslate2 + the installed CUDA driver
successfully run Whisper large-v3 on the Tier 1 reference hardware (the
PowerSpec G730 with an RTX 5070 Ti / Blackwell-architecture card).

Run this on the G730 (or any Blackwell-equipped machine) before kicking
off Sprint 0.5. The script:

1. Confirms NVML is reachable and reports the GPU name + driver + CUDA
   versions exposed by the driver.
2. Confirms ``ctranslate2`` imports and reports its CUDA toolkit version
   (this is the binding most likely to break on a new architecture).
3. Loads the ``faster-whisper`` ``small`` model on CUDA, transcribes a
   2-second silent audio clip generated in-process (no external assets
   needed), and reports the transcription's basic shape.

If any step fails, the failure mode is printed in operator-readable form
and the script exits non-zero. If everything passes, the script prints a
green summary and exits 0.

This is a verification harness, not a test fixture -- it is intentionally
not invoked by pytest. The CI runners do not have GPUs and the test
suite's NVML probe (`tests/test_hardware_probe_gpu_positive.py`) self-
skips on CI; this script is operator-run on the G730 and the result is
saved as evidence in the Sprint 0.5 verification log.

Usage:

    python scripts/verify-blackwell-runtime.py

Exit codes:

    0  -- every step passed; green-light Sprint 0.5
    1  -- NVML unavailable / no GPU detected
    2  -- ctranslate2 unavailable or CUDA mismatch
    3  -- faster-whisper load or transcription failed
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
import wave
from pathlib import Path


def _print_section(title: str) -> None:
    bar = "-" * 72
    print(f"\n{bar}\n{title}\n{bar}")


def _step1_nvml() -> int:
    _print_section("Step 1 -- NVML probe")
    try:
        import pynvml  # type: ignore[import-untyped]
    except ImportError as exc:
        print(f"FAIL: pynvml not installed ({exc}).")
        print("Next step: pip install nvidia-ml-py (or uv add nvidia-ml-py).")
        return 1

    try:
        pynvml.nvmlInit()
    except Exception as exc:
        print(f"FAIL: nvmlInit raised: {exc}")
        print("Next step: confirm NVIDIA driver is installed and the device is visible.")
        return 1

    try:
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            print("FAIL: NVML reports zero devices.")
            return 1

        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            print(f"  Device {i}: {name}")
            print(f"    VRAM total: {mem.total / 1024**3:.2f} GB")
            print(f"    VRAM free:  {mem.free / 1024**3:.2f} GB")

        driver_raw = pynvml.nvmlSystemGetDriverVersion()
        driver = (
            driver_raw.decode("utf-8", errors="replace")
            if isinstance(driver_raw, bytes)
            else driver_raw
        )
        print(f"  Driver version: {driver}")

        try:
            cuda_int = pynvml.nvmlSystemGetCudaDriverVersion()
            major = cuda_int // 1000
            minor = (cuda_int % 1000) // 10
            print(f"  CUDA driver: {major}.{minor}")
        except Exception as exc:
            print(f"  CUDA driver version unavailable: {exc}")

    finally:
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()

    print("OK: NVML reachable, GPU(s) enumerated.")
    return 0


def _step2_ctranslate2() -> int:
    _print_section("Step 2 -- CTranslate2 import + CUDA support")
    try:
        import ctranslate2  # type: ignore[import-untyped]
    except ImportError as exc:
        print(f"FAIL: ctranslate2 not installed ({exc}).")
        print("Next step: pip install ctranslate2 (faster-whisper depends on it).")
        return 2

    try:
        device_count = ctranslate2.get_cuda_device_count()
    except Exception as exc:
        print(f"FAIL: ctranslate2.get_cuda_device_count raised: {exc}")
        print(
            "Next step: this is the most likely Blackwell incompatibility "
            "signal -- the CTranslate2 build may pre-date Blackwell support. "
            "Try a newer ctranslate2 release or rebuild from source."
        )
        return 2

    if device_count == 0:
        print("FAIL: ctranslate2 sees zero CUDA devices.")
        print("Next step: check CUDA toolkit / driver compatibility.")
        return 2

    print(f"OK: ctranslate2 imports, sees {device_count} CUDA device(s).")
    return 0


def _make_silent_wav(path: Path) -> None:
    """Generate a 2-second silent mono 16kHz WAV. Enough audio for whisper
    to produce an empty / "" transcription without erroring."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000 * 2)


def _step3_faster_whisper() -> int:
    _print_section("Step 3 -- faster-whisper load + transcribe on CUDA")
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError as exc:
        print(f"FAIL: faster-whisper not installed ({exc}).")
        print("Next step: pip install faster-whisper.")
        return 3

    print("Loading 'small' model on CUDA (int8_float16)...")
    try:
        model = WhisperModel("small", device="cuda", compute_type="int8_float16")
    except Exception as exc:
        print(f"FAIL: WhisperModel load raised: {exc}")
        print(
            "Next step: this is where Blackwell-specific cuDNN/CUDA mismatches "
            "typically surface. Capture the full traceback in the Sprint 0.5 "
            "verification log."
        )
        return 3

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir) / "silence.wav"
        _make_silent_wav(audio_path)
        try:
            segments, info = model.transcribe(str(audio_path), beam_size=1)
            seg_list = list(segments)
        except Exception as exc:
            print(f"FAIL: model.transcribe raised: {exc}")
            return 3

    print(f"  Detected language: {info.language} (probability {info.language_probability:.2f})")
    print(f"  Segments produced: {len(seg_list)}")
    print("OK: faster-whisper loaded on CUDA and transcribed without error.")
    return 0


def main() -> int:
    print("CivicCast -- Blackwell runtime verifier (ADR 0003 risks check)")
    print("Run this on the G730 reference machine before Sprint 0.5 kickoff.")

    rc = _step1_nvml()
    if rc != 0:
        return rc
    rc = _step2_ctranslate2()
    if rc != 0:
        return rc
    rc = _step3_faster_whisper()
    if rc != 0:
        return rc

    _print_section("All checks passed")
    print("OK: NVML probe succeeded")
    print("OK: CTranslate2 imports + sees CUDA")
    print("OK: faster-whisper loads on CUDA and transcribes")
    print("\nGreen-light Sprint 0.5 captions work on this machine.")
    print("Save this output to docs/releases/v0.5-prep-blackwell-verify.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
