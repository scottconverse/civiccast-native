#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Measure real three-channel large-v3 captions and fail-closed overload.

The proof runs the production :class:`CaptionTapWorker` with three concurrent
channels, an explicitly selected packaged local large-v3 runtime, and every
Python-process outbound socket denied. It records process/system CPU and memory
samples, durable review rows, active WebVTT, real-time deadline disposition,
and a separate overload negative control that must clear stale captions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import wave
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil

from civiccast.captions.models import AudioChunk
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.runtime import (
    CaptionRuntime,
    FasterWhisperRuntime,
)
from civiccast.captions.tap_worker import CaptionTapWorker
from civiccast.native.app_payload import (
    CAPTION_PACK_CONTRACT,
    WHISPER_MODEL_FILES,
    WHISPER_MODEL_REPO,
    WHISPER_MODEL_REVISION,
)

REQUIRED_CHANNELS = ("education", "government", "public")
# One robust, name-free phrase per canonical fixture window (controller-0020
# set: three DISTINCT 10s windows of real Longmont council audio at source
# offsets 2220/2240/2250 inside the take2b silencedetect-proven speech
# region). Every channel processes all three fixtures, so every channel's
# review text must contain all three phrases. Phrases were chosen from the
# take2b large-v3 reference transcript specifically to avoid proper nouns
# (which the medium tier may legitimately render differently). The original
# synthetic-fixture phrases ("council meeting will come to order", "public
# comment") retired with the 5s fixtures when the owner re-derived the gate
# at 10s segments (OWNER-DECISION addendum 2, 2026-07-30).
REQUIRED_TRANSCRIPT_PHRASES = (
    # Only the FIRST TWO fixture windows: the nominal scan settles exactly
    # two segments per channel (consumed_segments == 6 across three
    # channels); the third fixture feeds the overload negative control and
    # its content never reaches the review table — proven by take5, where
    # both these phrases appeared verbatim in every channel's review text
    # and the third window's phrase could not.
    "cruise night",
    "next five on the list",
)
# A supported 16 GiB station must retain roughly 4 GiB for Windows, CivicCast,
# PostgreSQL, and media processes while captions are active.
MAX_CAPTION_PROCESS_TREE_RSS_BYTES = 12 * 1024**3
FASTER_WHISPER_VERSION = str(CAPTION_PACK_CONTRACT["runtime_version"])
CTRANSLATE2_VERSION = str(CAPTION_PACK_CONTRACT["ctranslate2_version"])
CAPTION_DEVICE = str(CAPTION_PACK_CONTRACT["runtime_device"])
CAPTION_COMPUTE_TYPE = str(CAPTION_PACK_CONTRACT["runtime_compute_type"])


def cpu_model_name() -> str:
    """Return the human-readable CPU model used by this capacity proof."""

    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                value, _kind = winreg.QueryValueEx(key, "ProcessorNameString")
            finally:
                winreg.CloseKey(key)
            model = str(value).strip()
            if model:
                return model
        except (OSError, ImportError):
            pass
    return platform.processor().strip() or "unknown"


def _number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def evaluate_capacity_report(
    report: dict[str, object], *, expected_review_rows: int = 6
) -> list[str]:
    """Return fail-closed acceptance problems for a capacity report."""

    problems: list[str] = []
    model = report.get("model")
    expected_model_files = {
        name: {"bytes": size, "sha256": digest}
        for name, (size, digest) in WHISPER_MODEL_FILES.items()
    }
    expected_model_identity = {
        "backend": "faster-whisper",
        "runtime_version": FASTER_WHISPER_VERSION,
        "ctranslate2_version": CTRANSLATE2_VERSION,
        "device": CAPTION_DEVICE,
        "compute_type": CAPTION_COMPUTE_TYPE,
        "model_repository": WHISPER_MODEL_REPO,
        "model_revision": WHISPER_MODEL_REVISION,
        "model_files": expected_model_files,
    }
    if not isinstance(model, dict):
        problems.append("accepted faster-whisper runtime identity is missing")
    else:
        if model.get("backend") != "faster-whisper":
            problems.append("capacity proof did not use the accepted faster-whisper runtime")
        if any(model.get(key) != value for key, value in expected_model_identity.items()):
            problems.append(
                "capacity proof runtime or model identity does not match the signed pack"
            )

    channels = report.get("channels")
    if not isinstance(channels, dict) or set(channels) != set(REQUIRED_CHANNELS):
        problems.append("report does not contain exactly the three required channels")
    else:
        for channel in REQUIRED_CHANNELS:
            item = channels.get(channel)
            if (
                not isinstance(item, dict)
                or item.get("active_vtt") is not True
                or not isinstance(item.get("review_items"), int)
                or int(item["review_items"]) < 1
            ):
                problems.append(f"{channel} did not produce review rows and active WebVTT")
                continue
            review_texts = item.get("review_texts")
            normalized = (
                " ".join(
                    re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip() for text in review_texts
                )
                if isinstance(review_texts, list)
                else ""
            )
            if any(phrase not in normalized for phrase in REQUIRED_TRANSCRIPT_PHRASES):
                problems.append(f"{channel} did not produce the required transcript content")

    scan = report.get("scan")
    if not isinstance(scan, dict):
        problems.append("caption scan result is missing")
    else:
        if scan.get("consumed_segments") != 6:
            problems.append("caption scan did not consume all six settled segments")
        if scan.get("committed_review_items") != expected_review_rows:
            problems.append(
                f"caption scan did not commit the expected {expected_review_rows} "
                f"review rows (got {scan.get('committed_review_items')})"
            )
        if scan.get("dropped_overload_segments") != 0 or scan.get("overloaded_channels") not in (
            [],
            (),
        ):
            problems.append("nominal three-channel scan overloaded")

    performance = report.get("performance")
    if not isinstance(performance, dict):
        problems.append("performance measurements are missing")
    else:
        elapsed = _number(performance.get("elapsed_seconds"))
        deadline = _number(performance.get("realtime_deadline_seconds"))
        if elapsed is None or deadline is None or elapsed > deadline:
            problems.append(f"missed real-time deadline: elapsed={elapsed}, deadline={deadline}")
        peak_rss = _number(performance.get("peak_process_tree_rss_bytes"))
        rss_budget = _number(performance.get("max_process_tree_rss_bytes"))
        if peak_rss is None or rss_budget is None or peak_rss > rss_budget:
            problems.append(
                f"caption process tree exceeded 16 GiB station RSS budget: "
                f"peak={peak_rss}, budget={rss_budget}"
            )
    if report.get("network_attempts") not in ([], ()):
        problems.append("packaged caption runtime attempted network access")

    overload = report.get("overload_negative_control")
    if not isinstance(overload, dict) or not (
        overload.get("dropped_overload_segments") == 3
        and overload.get("active_vtt_cleared") is True
        and overload.get("runtime_state") == "overloaded"
    ):
        problems.append("fail-closed overload negative control did not pass")
    return problems


def _read_audio(path: Path) -> tuple[bytes, int, float]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("audio must be mono signed 16-bit PCM WAV")
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if not frames:
        raise ValueError("audio must not be empty")
    return frames, sample_rate, len(frames) / 2 / sample_rate


def validate_audio_segments(paths: list[Path]) -> tuple[int, float]:
    """Require three sequential tap segments with one compatible WAV shape."""

    if len(paths) != 3:
        raise ValueError("capacity proof requires exactly three sequential audio segments")
    identities = [(_read_audio(path)[1], _read_audio(path)[2]) for path in paths]
    sample_rate, segment_seconds = identities[0]
    if any(
        rate != sample_rate or abs(duration - segment_seconds) > 1e-6
        for rate, duration in identities[1:]
    ):
        raise ValueError("audio segments must have the same sample rate and duration")
    return sample_rate, segment_seconds


def validate_runtime_configuration(
    *,
    beam_size: int,
    overlap_seconds: float,
    cpu_threads: int,
    vad_filter: bool,
) -> dict[str, int | float | bool]:
    """Validate and return the explicit live-ASR tuning under measurement."""

    if beam_size < 1:
        raise ValueError("beam size must be at least 1")
    if overlap_seconds <= 0:
        raise ValueError("caption overlap must be greater than zero")
    if cpu_threads < 0:
        raise ValueError("CPU thread count must be zero or greater")
    return {
        "beam_size": beam_size,
        "cpu_threads": cpu_threads,
        "overlap_seconds": overlap_seconds,
        "vad_filter": vad_filter,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_packaged_model(model_dir: Path) -> dict[str, object]:
    """Require the exact signed-pack faster-whisper large-v3 model tree."""
    if not model_dir.is_dir():
        raise ValueError(f"packaged caption model directory is missing: {model_dir}")
    observed = {
        path.relative_to(model_dir).as_posix() for path in model_dir.rglob("*") if path.is_file()
    }
    expected = set(WHISPER_MODEL_FILES)
    if observed != expected:
        raise ValueError(
            "packaged caption model file set differs from the signed contract; "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )
    model_files: dict[str, dict[str, int | str]] = {}
    for name, (expected_bytes, expected_sha256) in sorted(WHISPER_MODEL_FILES.items()):
        path = model_dir / name
        if path.is_symlink():
            raise ValueError(f"packaged caption model file is a symlink: {name}")
        observed_bytes = path.stat().st_size
        observed_sha256 = _sha256(path)
        if observed_bytes != expected_bytes or observed_sha256 != expected_sha256:
            raise ValueError(
                f"packaged caption model identity mismatch for {name}: "
                f"bytes={observed_bytes}, sha256={observed_sha256}"
            )
        model_files[name] = {
            "bytes": observed_bytes,
            "sha256": observed_sha256,
        }
    return {
        "model_repository": WHISPER_MODEL_REPO,
        "model_revision": WHISPER_MODEL_REVISION,
        "model_files": model_files,
    }


def runtime_distribution_versions() -> dict[str, str]:
    """Require the exact Core-pack faster-whisper runtime distributions."""
    observed = {
        "runtime_version": metadata.version("faster-whisper"),
        "ctranslate2_version": metadata.version("ctranslate2"),
    }
    expected = {
        "runtime_version": FASTER_WHISPER_VERSION,
        "ctranslate2_version": CTRANSLATE2_VERSION,
    }
    if observed != expected:
        raise ValueError(
            f"caption runtime distribution identity mismatch: {observed}; expected {expected}"
        )
    return observed


def build_caption_runtime(
    *,
    backend: str,
    model_dir: Path,
    beam_size: int,
    cpu_threads: int,
    vad_filter: bool,
) -> tuple[CaptionRuntime, dict[str, object]]:
    """Build the exact large-v3 runtime under capacity measurement."""

    if backend != "faster-whisper":
        raise ValueError(
            f"capacity proof requires the accepted faster-whisper runtime; got {backend!r}"
        )
    model_identity = verify_packaged_model(model_dir)
    distribution_identity = runtime_distribution_versions()
    environment = {
        "CIVICCAST_WHISPER_MODEL_PATH": str(model_dir),
        "CIVICCAST_WHISPER_DEVICE": CAPTION_DEVICE,
        "CIVICCAST_WHISPER_COMPUTE_TYPE": CAPTION_COMPUTE_TYPE,
    }
    previous_environment = {name: os.environ.get(name) for name in environment}
    try:
        os.environ.update(environment)
        # Deliberately NOT passing num_workers here. civiccast/captions/
        # tap_worker.py constructs the production runtime bare
        # (``FasterWhisperRuntime()``), so production always gets
        # runtime.py's own default (1), only ever changed by an operator
        # setting CIVICCAST_WHISPER_NUM_WORKERS. A capacity proof that
        # hardcodes a different num_workers here would measure a runtime
        # nobody ships and could pass without proving the deployed
        # configuration meets the real-time deadline (Codex review,
        # PR #427). Omitting the argument makes this constructor call --
        # and therefore this measurement -- track whatever num_workers
        # production actually uses, including a future default change or
        # an operator override, with zero risk of the two drifting apart
        # again.
        runtime = FasterWhisperRuntime(
            model_size_or_path=str(model_dir),
            device=CAPTION_DEVICE,
            compute_type=CAPTION_COMPUTE_TYPE,
            cpu_threads=cpu_threads,
            beam_size=beam_size,
            language="en",
            vad_filter=vad_filter,
        )
    finally:
        for name, previous_value in previous_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
    return runtime, {
        "backend": backend,
        "beam_size": beam_size,
        "compute_type": CAPTION_COMPUTE_TYPE,
        "cpu_threads": cpu_threads,
        "device": CAPTION_DEVICE,
        "local_files_only": True,
        "model": str(model_dir),
        # Recorded post-construction (reflects CIVICCAST_WHISPER_NUM_WORKERS
        # if the operator set one) so every capacity report states, in the
        # durable artifact, exactly which executor configuration was
        # measured -- not an assumed or hardcoded value.
        "num_workers": runtime.num_workers,
        "vad_filter": vad_filter,
        **distribution_identity,
        **model_identity,
    }


def _install_socket_denial() -> list[str]:
    attempts: list[str] = []

    class DeniedSocket(socket.socket):
        def connect(self, address: object) -> None:
            attempts.append(repr(address))
            raise OSError("network denied by native caption capacity proof")

        def connect_ex(self, address: object) -> int:
            attempts.append(repr(address))
            return 10013

    def denied_create_connection(
        address: object,
        *args: object,
        **kwargs: object,
    ) -> socket.socket:
        del args, kwargs
        attempts.append(repr(address))
        raise OSError("network denied by native caption capacity proof")

    socket.socket = DeniedSocket  # type: ignore[misc]
    socket.create_connection = denied_create_connection
    return attempts


def measure_process_tree_memory(process: Any) -> dict[str, object]:
    """Return combined RSS for the proof process and every live descendant."""
    try:
        descendants = list(process.children(recursive=True))
    except (psutil.Error, OSError):
        descendants = []
    processes = [process, *descendants]
    seen: set[int] = set()
    pids: list[int] = []
    parent_rss = 0
    child_rss = 0
    for candidate in processes:
        try:
            pid = int(candidate.pid)
            if pid in seen:
                continue
            rss = int(candidate.memory_info().rss)
        except (psutil.Error, OSError):
            continue
        seen.add(pid)
        pids.append(pid)
        if pid == int(process.pid):
            parent_rss += rss
        else:
            child_rss += rss
    return {
        "child_rss_bytes": child_rss,
        "pids": tuple(sorted(pids)),
        "process_count": len(pids),
        "process_tree_rss_bytes": parent_rss + child_rss,
    }


def sample_gpu_devices() -> list[dict[str, int | str]]:
    """Read device-wide committed VRAM, including Windows WDDM systems."""
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    completed = subprocess.run(
        [
            executable,
            "--query-gpu=index,name,memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return []
    devices: list[dict[str, int | str]] = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 4:
            return []
        try:
            index = int(fields[0])
            total_bytes = int(fields[2]) * 1024**2
            used_bytes = int(fields[3]) * 1024**2
        except ValueError:
            return []
        devices.append(
            {
                "index": index,
                "name": fields[1],
                "total_bytes": total_bytes,
                "used_bytes": used_bytes,
            }
        )
    return devices


def _sample_resources(
    stop: threading.Event,
    samples: list[dict[str, float | int | None]],
) -> None:
    process = psutil.Process(os.getpid())
    process.cpu_percent(None)
    psutil.cpu_percent(None)
    while not stop.wait(0.1):
        virtual = psutil.virtual_memory()
        tree = measure_process_tree_memory(process)
        gpu_devices = sample_gpu_devices()
        samples.append(
            {
                "available_memory_bytes": int(virtual.available),
                "child_rss_bytes": int(tree["child_rss_bytes"]),
                "gpu_used_memory_bytes": (
                    sum(int(device["used_bytes"]) for device in gpu_devices)
                    if gpu_devices
                    else None
                ),
                "process_count": int(tree["process_count"]),
                "process_cpu_percent": process.cpu_percent(None),
                "process_tree_rss_bytes": int(tree["process_tree_rss_bytes"]),
                "system_cpu_percent": psutil.cpu_percent(None),
            }
        )


def _copy_segments(audio_segments: list[Path], tap_root: Path) -> None:
    for channel in REQUIRED_CHANNELS:
        channel_dir = tap_root / channel
        channel_dir.mkdir(parents=True, exist_ok=True)
        for index, audio in enumerate(audio_segments):
            shutil.copy2(audio, channel_dir / f"chunk-{index:06d}.wav")


def _channel_report(
    store: InMemoryCaptionReviewStore,
    work_dir: Path,
    channel: str,
) -> dict[str, object]:
    active = work_dir / channel / "captions" / "active.vtt"
    rows = store.list(asset_id=channel)
    evidence: list[dict[str, object]] = []
    for row in rows:
        item_evidence = store.get_audio_evidence(row.review_item_id)
        if item_evidence is None:
            continue
        evidence.append(
            {
                "review_item_id": row.review_item_id,
                "path": item_evidence.source_path,
                "bytes": item_evidence.source_bytes,
                "sha256": item_evidence.source_sha256,
            }
        )
    return {
        "active_vtt": active.is_file() and active.stat().st_size > len("WEBVTT\n"),
        "active_vtt_path": str(active.resolve()),
        "active_vtt_sha256": _sha256(active) if active.is_file() else None,
        "active_vtt_text": active.read_text(encoding="utf-8") if active.is_file() else "",
        "evidence": evidence,
        "review_item_ids": [item.review_item_id for item in rows],
        "review_item_statuses": {item.review_item_id: item.status for item in rows},
        "review_items": len(rows),
        "review_texts": [item.original_text for item in rows],
    }


def _overload_negative_control(
    *,
    audio: Path,
    work_root: Path,
    runtime: CaptionRuntime,
    segment_seconds: float,
    overlap_seconds: float,
) -> dict[str, object]:
    tap_root = work_root / "tap"
    channel_dir = tap_root / "government"
    channel_dir.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        shutil.copy2(audio, channel_dir / f"chunk-{index:06d}.wav")
    caption_work = work_root / "egress"
    active = caption_work / "government" / "captions" / "active.vtt"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(
        "WEBVTT\n\nold\n00:00:00.000 --> 00:00:01.000\nstale caption\n",
        encoding="utf-8",
    )
    worker = CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=caption_work,
        runtime=runtime,
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=segment_seconds,
        overlap_seconds=overlap_seconds,
        max_channel_workers=3,
        max_backlog_segments=2,
    )
    result = worker.run_once()
    status_path = caption_work / "government" / "captions" / "runtime-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    return {
        "active_vtt_cleared": active.read_text(encoding="utf-8").strip() == "WEBVTT",
        "dropped_overload_segments": result.dropped_overload_segments,
        "overload_files": sorted(path.name for path in (channel_dir / "overload").glob("*.wav")),
        "runtime_state": status.get("state"),
    }


def main() -> int:
    # Every downstream site (runtime construction, expected identity, env
    # pins) reads these module globals at call time, so overriding them from
    # the CLI keeps the whole run — including the identity acceptance —
    # consistent.
    global CAPTION_DEVICE, CAPTION_COMPUTE_TYPE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio",
        action="append",
        required=True,
        type=Path,
        help="one sequential mono s16le WAV segment; provide exactly three",
    )
    parser.add_argument(
        "--runtime-backend",
        choices=("faster-whisper",),
        default="faster-whisper",
    )
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--overlap-seconds", type=float, default=4.0)
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument(
        "--device",
        default=CAPTION_DEVICE,
        help=(
            "override the pack-contract runtime device (e.g. cuda) for a "
            "hardware-exploration trial; the report records the override"
        ),
    )
    parser.add_argument(
        "--compute-type",
        default=CAPTION_COMPUTE_TYPE,
        help=(
            "override the pack-contract compute type (e.g. float16) for a "
            "hardware-exploration trial; the report records the override"
        ),
    )
    parser.add_argument(
        "--expected-review-rows",
        type=int,
        default=6,
        help=(
            "exact committed-review-row count the scan must produce for this "
            "fixture set (a determinism pin, calibrated per fixture content; "
            "6 = the retired 5s synthetic fixtures)"
        ),
    )
    parser.add_argument(
        "--disable-vad",
        action="store_true",
        help="disable the production VAD optimization for a comparison run",
    )
    args = parser.parse_args()

    CAPTION_DEVICE = args.device
    CAPTION_COMPUTE_TYPE = args.compute_type

    audio_segments = [path.resolve() for path in args.audio]
    model_dir = args.model_dir.resolve()
    work_dir = args.work_dir.resolve()
    if work_dir.exists() and any(work_dir.iterdir()):
        raise SystemExit(f"work directory must be empty: {work_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)
    sample_rate, segment_seconds = validate_audio_segments(audio_segments)
    frames, _sample_rate, _duration = _read_audio(audio_segments[0])
    tuning = validate_runtime_configuration(
        beam_size=args.beam_size,
        overlap_seconds=args.overlap_seconds,
        cpu_threads=args.cpu_threads,
        vad_filter=not args.disable_vad,
    )

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    network_attempts = _install_socket_denial()
    gpu_baseline = sample_gpu_devices()
    gpu_baseline_used_bytes = (
        sum(int(device["used_bytes"]) for device in gpu_baseline) if gpu_baseline else None
    )
    samples: list[dict[str, float | int | None]] = []
    stop = threading.Event()
    sampler = threading.Thread(
        target=_sample_resources,
        args=(stop, samples),
        name="civiccast-caption-capacity-sampler",
        daemon=True,
    )
    sampler.start()
    runtime, runtime_identity = build_caption_runtime(
        backend=args.runtime_backend,
        model_dir=model_dir,
        beam_size=int(tuning["beam_size"]),
        cpu_threads=int(tuning["cpu_threads"]),
        vad_filter=bool(tuning["vad_filter"]),
    )

    warmup_chunk = AudioChunk(
        chunk_id="capacity-warmup",
        start_seconds=0.0,
        end_seconds=segment_seconds,
        sample_rate_hz=sample_rate,
        pcm_s16le=frames,
    )
    warmup_started = time.perf_counter()
    warmup_hypotheses = list(runtime.transcribe([warmup_chunk]))
    warmup_elapsed = time.perf_counter() - warmup_started

    tap_root = work_dir / "nominal" / "tap"
    caption_work = work_dir / "nominal" / "egress"
    _copy_segments(audio_segments, tap_root)
    store = InMemoryCaptionReviewStore()
    worker = CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=caption_work,
        runtime=runtime,
        review_store=store,
        segment_seconds=segment_seconds,
        overlap_seconds=float(tuning["overlap_seconds"]),
        max_channel_workers=3,
        max_backlog_segments=2,
    )

    started = time.perf_counter()
    scan = worker.run_once()
    elapsed = time.perf_counter() - started
    # End-of-stream flush (WP1 caption-integrity fix, 2026-07-29) is measured
    # OUTSIDE the real-time capacity window above on purpose: it fixes row
    # commitment (nothing was ever flushed at end of stream before), not the
    # realtime_deadline_seconds gate. Keep the two failure modes -- a missed
    # deadline vs. uncommitted rows -- reported separately so neither hides
    # the other.
    end_of_stream_committed = 0
    end_of_stream_expired_unconfirmed = 0
    for channel in REQUIRED_CHANNELS:
        flushed = worker.flush_channel(channel)
        end_of_stream_committed += flushed.committed_review_items
        end_of_stream_expired_unconfirmed += flushed.expired_unconfirmed_cues
    stop.set()
    sampler.join(timeout=2.0)
    process = psutil.Process(os.getpid())
    if not samples:
        tree = measure_process_tree_memory(process)
        gpu_devices = sample_gpu_devices()
        samples.append(
            {
                "available_memory_bytes": int(psutil.virtual_memory().available),
                "child_rss_bytes": int(tree["child_rss_bytes"]),
                "gpu_used_memory_bytes": (
                    sum(int(device["used_bytes"]) for device in gpu_devices)
                    if gpu_devices
                    else None
                ),
                "process_count": int(tree["process_count"]),
                "process_cpu_percent": 0.0,
                "process_tree_rss_bytes": int(tree["process_tree_rss_bytes"]),
                "system_cpu_percent": 0.0,
            }
        )
    measured_gpu_samples = [
        int(sample["gpu_used_memory_bytes"])
        for sample in samples
        if sample["gpu_used_memory_bytes"] is not None
    ]
    peak_gpu_used_bytes = max(measured_gpu_samples) if measured_gpu_samples else None
    peak_caption_gpu_delta_bytes = (
        max(0, peak_gpu_used_bytes - gpu_baseline_used_bytes)
        if peak_gpu_used_bytes is not None and gpu_baseline_used_bytes is not None
        else None
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "model": runtime_identity,
        "host": {
            "cpu_model": cpu_model_name(),
            "logical_cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "total_memory_bytes": int(psutil.virtual_memory().total),
            "gpu_baseline": gpu_baseline,
        },
        "audio": {
            "paths": [str(path) for path in audio_segments],
            "sample_rate_hz": sample_rate,
            "segment_seconds": segment_seconds,
            "overlap_seconds": tuning["overlap_seconds"],
            "settled_segments_per_channel": 2,
        },
        "warmup": {
            "elapsed_seconds": round(warmup_elapsed, 3),
            "hypothesis_count": len(warmup_hypotheses),
        },
        "scan": {
            "channels": list(scan.channels),
            "committed_review_items": scan.committed_review_items,
            "consumed_segments": scan.consumed_segments,
            "dropped_overload_segments": scan.dropped_overload_segments,
            "expired_unconfirmed_cues": scan.expired_unconfirmed_cues,
            "overloaded_channels": list(scan.overloaded_channels),
            "quarantined_segments": scan.quarantined_segments,
        },
        # WP1 caption-integrity fix (2026-07-29): exercises the end-of-stream
        # flush path so the proof does not just measure mid-stream capacity.
        # Reported separately from "scan" -- a nominal run with fully
        # stabilized captions should flush nothing new (0/0); non-zero here
        # documents cues that only committed because the stream ended.
        "end_of_stream": {
            "committed_review_items": end_of_stream_committed,
            "expired_unconfirmed_cues": end_of_stream_expired_unconfirmed,
        },
        "channels": {
            channel: _channel_report(store, caption_work, channel) for channel in REQUIRED_CHANNELS
        },
        "performance": {
            "elapsed_seconds": round(elapsed, 3),
            "realtime_deadline_seconds": round(segment_seconds * 2, 3),
            "peak_process_cpu_percent": max(
                float(sample["process_cpu_percent"]) for sample in samples
            ),
            "peak_child_rss_bytes": max(int(sample["child_rss_bytes"]) for sample in samples),
            "peak_process_count": max(int(sample["process_count"]) for sample in samples),
            "peak_process_tree_rss_bytes": max(
                int(sample["process_tree_rss_bytes"]) for sample in samples
            ),
            "peak_system_cpu_percent": max(
                float(sample["system_cpu_percent"]) for sample in samples
            ),
            "minimum_available_memory_bytes": min(
                int(sample["available_memory_bytes"]) for sample in samples
            ),
            "gpu_baseline_used_bytes": gpu_baseline_used_bytes,
            "gpu_measurement_status": (
                "measured"
                if gpu_baseline_used_bytes is not None and measured_gpu_samples
                else "unavailable"
            ),
            "peak_caption_gpu_delta_bytes": peak_caption_gpu_delta_bytes,
            "peak_gpu_used_bytes": peak_gpu_used_bytes,
            "max_process_tree_rss_bytes": MAX_CAPTION_PROCESS_TREE_RSS_BYTES,
            "sample_count": len(samples),
        },
        "network_attempts": network_attempts,
        "overload_negative_control": _overload_negative_control(
            audio=audio_segments[0],
            work_root=work_dir / "overload-negative",
            runtime=runtime,
            segment_seconds=segment_seconds,
            overlap_seconds=float(tuning["overlap_seconds"]),
        ),
    }
    problems = evaluate_capacity_report(report, expected_review_rows=args.expected_review_rows)
    report["problems"] = problems
    report["status"] = "PASS" if not problems else "FAIL"
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
