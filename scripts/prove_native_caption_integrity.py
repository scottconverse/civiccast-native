#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bind real native tap/ASR/review evidence to CEA-708 decode-back proof.

This is deliberately a composition proof, not another caption simulator.  It
first runs the production three-channel capacity producer, seals the producer
receipt, and only then gives those exact sidecars to the Win32 named-pipe and
GStreamer transport proof.  Every sidecar and retained review-audio file is
rehashed after transport so a report cannot claim a hand-authored VTT as live
caption output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED_CHANNELS = ("government", "education", "public")
_APPROVED_UNTRACKED_PATHS = frozenset(
    {
        "tests/native/test_caption_integrity_proof.py",
        "tests/policy/test_native_caption_workflow_policy.py",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_source_sha() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    dirty_paths = {
        line[3:].replace("\\", "/")
        for line in status.stdout.splitlines()
        if len(line) >= 4 and line[3:].replace("\\", "/") not in _APPROVED_UNTRACKED_PATHS
    }
    if dirty_paths:
        raise RuntimeError(
            "refusing to bind a live proof to a dirty source tree: "
            + ", ".join(sorted(dirty_paths))
        )
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} is not a JSON object: {path}")
    return parsed


def _file_matches(path_value: object, expected_sha: object) -> bool:
    if not isinstance(path_value, str) or not _is_sha256(expected_sha):
        return False
    path = Path(path_value)
    return path.is_file() and _sha256(path) == expected_sha


def validate_caption_integrity_report(
    report: dict[str, object],
    *,
    expected_source_sha: str,
) -> list[str]:
    """Return every fail-closed reason a composed proof cannot be accepted."""

    problems: list[str] = []
    if report.get("source_sha") != expected_source_sha:
        problems.append("report source SHA does not match the checked-out source SHA")

    runtime = report.get("runtime")
    if not isinstance(runtime, dict):
        problems.append("runtime identity is missing")
    else:
        from civiccast.native.app_payload import CAPTION_PACK_CONTRACT

        expected_runtime = {
            "backend": "faster-whisper",
            "runtime_version": CAPTION_PACK_CONTRACT["runtime_version"],
            "ctranslate2_version": CAPTION_PACK_CONTRACT["ctranslate2_version"],
            "device": CAPTION_PACK_CONTRACT["runtime_device"],
            "compute_type": CAPTION_PACK_CONTRACT["runtime_compute_type"],
        }
        if any(runtime.get(key) != value for key, value in expected_runtime.items()):
            problems.append("runtime identity does not match the accepted caption pack")
    model = report.get("model")
    if not isinstance(model, dict):
        problems.append("verified model identity is missing")
    else:
        from civiccast.native.app_payload import WHISPER_MODEL_FILES

        expected_model = {
            name: {"bytes": bytes_, "sha256": digest}
            for name, (bytes_, digest) in WHISPER_MODEL_FILES.items()
        }
        if model != expected_model:
            problems.append("verified model identity does not match the signed caption pack")

    receipt_descriptor = report.get("upstream_producer_receipt")
    receipt: dict[str, Any] | None = None
    if not isinstance(receipt_descriptor, dict) or not _file_matches(
        receipt_descriptor.get("path"), receipt_descriptor.get("sha256")
    ):
        problems.append("upstream producer receipt is missing or unhashed")
    else:
        try:
            receipt = _read_json(
                Path(str(receipt_descriptor["path"])), label="upstream producer receipt"
            )
        except RuntimeError as exc:
            problems.append(str(exc))
        else:
            if receipt.get("source_sha") != expected_source_sha:
                problems.append("upstream producer receipt source SHA does not match")

    channels = report.get("channels")
    if not isinstance(channels, dict) or set(channels) != set(REQUIRED_CHANNELS):
        problems.append("report does not contain exactly the required channels")
        return problems

    receipt_channels = receipt.get("channels") if isinstance(receipt, dict) else None
    if not isinstance(receipt_channels, dict):
        problems.append("upstream producer receipt lacks channel evidence")
        receipt_channels = {}

    for channel_id in REQUIRED_CHANNELS:
        channel = channels[channel_id]
        if not isinstance(channel, dict):
            problems.append(f"{channel_id} channel report is malformed")
            continue
        producer_channel = receipt_channels.get(channel_id)
        if not isinstance(producer_channel, dict):
            problems.append(f"{channel_id} is absent from the producer receipt")
            continue
        if channel.get("upstream_receipt_channel") != channel_id:
            problems.append(f"{channel_id} is not bound to its producer receipt channel")

        producer_sidecar_path = producer_channel.get("active_vtt_path")
        producer_sidecar_sha = producer_channel.get("active_vtt_sha256")
        if (
            channel.get("active_vtt_path") != producer_sidecar_path
            or channel.get("active_vtt_sha256") != producer_sidecar_sha
            or not _file_matches(producer_sidecar_path, producer_sidecar_sha)
        ):
            problems.append("fabricated sidecar")

        producer_ids = producer_channel.get("review_item_ids")
        if (
            not isinstance(producer_ids, list)
            or not producer_ids
            or channel.get("review_item_ids") != producer_ids
        ):
            problems.append(f"{channel_id} review rows are missing or do not match the producer")

        producer_evidence = producer_channel.get("evidence")
        channel_evidence = channel.get("evidence")
        if (
            not isinstance(producer_evidence, list)
            or not producer_evidence
            or channel_evidence != producer_evidence
        ):
            problems.append(
                f"{channel_id} retained evidence is missing or does not match the producer"
            )
        else:
            for entry in producer_evidence:
                if not isinstance(entry, dict) or not _file_matches(
                    entry.get("path"), entry.get("sha256")
                ):
                    problems.append(f"{channel_id} retained evidence is missing or unhashed")
                    break

        if channel.get("feed_delivery") != "PASS":
            problems.append(f"caption feed did not deliver {channel_id}")
        if channel.get("cea708_decode_back") != "PASS":
            problems.append(f"CEA-708 decode-back did not pass for {channel_id}")
        stream_path = channel.get("transport_stream_path")
        stream_sha256 = channel.get("transport_stream_sha256")
        stream_bytes = channel.get("transport_stream_bytes")
        if (
            not isinstance(stream_bytes, int)
            or stream_bytes <= 0
            or not _file_matches(stream_path, stream_sha256)
            or Path(str(stream_path)).stat().st_size != stream_bytes
        ):
            problems.append(f"{channel_id} emitted transport stream is missing or unhashed")
    return problems


def _default_audio_segments() -> list[Path]:
    """Use recorded native tap material only when this workstation has it.

    This preserves the plan's three required CLI arguments without silently
    generating a fake transcript.  Other venues must supply three real tap WAVs
    explicitly with ``--audio``.
    """

    tap = ROOT / "build" / "wp1-live-tap-spike-2" / "tap" / "government"
    candidates = [
        tap / "processed" / "chunk-000000.wav",
        tap / "processed" / "chunk-000001.wav",
        tap / "chunk-000002.wav",
    ]
    if all(path.is_file() for path in candidates):
        return candidates
    raise RuntimeError(
        "no recorded native tap WAVs were found; provide exactly three --audio paths "
        "from the live station tap rather than supplying a synthesized transcript"
    )


def _capacity_command(
    *,
    caption_python: Path,
    model_dir: Path,
    audio_segments: list[Path],
    work_dir: Path,
    output: Path,
) -> list[str]:
    script = ROOT / "scripts" / "prove_native_caption_capacity.py"
    audio_args = list(_audio_arguments(audio_segments))
    launcher = (
        "import runpy,sys; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        f"sys.argv={[str(script), *audio_args, '--model-dir', str(model_dir), '--work-dir', str(work_dir), '--output', str(output)]!r}; "
        f"runpy.run_path({str(script)!r}, run_name='__main__')"
    )
    return [str(caption_python), "-I", "-B", "-c", launcher]


def _audio_arguments(paths: Iterable[Path]) -> Iterable[str]:
    for path in paths:
        yield "--audio"
        yield str(path)


def _producer_receipt(capacity_report: dict[str, Any], *, source_sha: str) -> dict[str, Any]:
    channels = capacity_report.get("channels")
    if not isinstance(channels, dict):
        raise RuntimeError("capacity producer report lacks channels")
    return {
        "schema_version": 1,
        "source_sha": source_sha,
        "model": capacity_report.get("model"),
        "runtime": {
            key: capacity_report.get("model", {}).get(key)
            if isinstance(capacity_report.get("model"), dict)
            else None
            for key in (
                "backend",
                "runtime_version",
                "ctranslate2_version",
                "device",
                "compute_type",
            )
        },
        "channels": {
            channel_id: {
                "active_vtt_path": channel.get("active_vtt_path"),
                "active_vtt_sha256": channel.get("active_vtt_sha256"),
                "evidence": channel.get("evidence"),
                "review_item_ids": channel.get("review_item_ids"),
                "review_item_statuses": channel.get("review_item_statuses"),
            }
            for channel_id, channel in channels.items()
            if isinstance(channel, dict)
        },
    }


def run_caption_integrity_proof(
    *,
    runtime_tree: Path,
    model_dir: Path,
    output: Path,
    audio_segments: list[Path],
    caption_python: Path,
) -> dict[str, Any]:
    """Execute the real producer and transport proof and seal one report."""

    if output.exists():
        raise RuntimeError(f"refusing to reuse caption-integrity evidence directory: {output}")
    if len(audio_segments) != 3 or not all(path.is_file() for path in audio_segments):
        raise RuntimeError("caption-integrity proof requires exactly three readable live tap WAVs")
    if not caption_python.is_file():
        raise RuntimeError(f"caption runtime Python is missing: {caption_python}")
    output.mkdir(parents=True)
    source_sha = _git_source_sha()
    producer_dir = output / "producer"
    producer_dir.mkdir()
    capacity_report_path = producer_dir / "capacity-report.json"
    command = _capacity_command(
        caption_python=caption_python,
        model_dir=model_dir,
        audio_segments=audio_segments,
        work_dir=producer_dir / "work",
        output=capacity_report_path,
    )
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    (producer_dir / "capacity.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (producer_dir / "capacity.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            "real tap/ASR/review producer failed; see "
            f"{producer_dir / 'capacity.stderr.log'} and {capacity_report_path}"
        )
    capacity_report = _read_json(capacity_report_path, label="capacity producer report")
    if capacity_report.get("status") != "PASS":
        raise RuntimeError("capacity producer reported a non-PASS status")

    receipt_path = producer_dir / "tap-asr-review-receipt.json"
    receipt = _producer_receipt(capacity_report, source_sha=source_sha)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    from scripts.prove_native_live_caption_transport import run_transport_proof

    transport = run_transport_proof(
        runtime_tree=runtime_tree,
        sidecar_root=producer_dir / "work" / "nominal" / "egress",
        output_dir=output / "transport",
        python_executable=caption_python,
        source_root=ROOT,
    )
    producer_channels = receipt["channels"]
    transport_channels = transport.get("channels")
    if not isinstance(transport_channels, dict):
        raise RuntimeError("transport proof lacks per-channel results")
    channels: dict[str, dict[str, Any]] = {}
    for channel_id in REQUIRED_CHANNELS:
        upstream = producer_channels.get(channel_id)
        transport_channel = transport_channels.get(channel_id)
        if not isinstance(upstream, dict) or not isinstance(transport_channel, dict):
            raise RuntimeError(f"required channel missing after transport: {channel_id}")
        stream_path = Path(str(transport_channel.get("transport_stream", "")))
        channels[channel_id] = {
            "upstream_receipt_channel": channel_id,
            "active_vtt_path": upstream.get("active_vtt_path"),
            "active_vtt_sha256": upstream.get("active_vtt_sha256"),
            "review_item_ids": upstream.get("review_item_ids"),
            "review_item_statuses": upstream.get("review_item_statuses"),
            "evidence": upstream.get("evidence"),
            "feed_delivery": (
                "PASS"
                if channel_id in transport.get("feed", {}).get("sent_channels", [])
                else "MISSING"
            ),
            "cea708_decode_back": transport_channel.get("status"),
            "transport_stream_path": str(stream_path),
            "transport_stream_sha256": _sha256(stream_path) if stream_path.is_file() else None,
            "transport_stream_bytes": transport_channel.get("transport_stream_bytes"),
        }
    report: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_sha": source_sha,
        "runtime": receipt["runtime"],
        "model": receipt["model"].get("model_files", {})
        if isinstance(receipt["model"], dict)
        else {},
        "audio_inputs": [
            {"path": str(path.resolve()), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in audio_segments
        ],
        "upstream_producer_receipt": {
            "path": str(receipt_path.resolve()),
            "sha256": _sha256(receipt_path),
        },
        "capacity_report": {
            "path": str(capacity_report_path.resolve()),
            "sha256": _sha256(capacity_report_path),
        },
        "transport": transport,
        "channels": channels,
        "fail_to_slate_or_refusal": capacity_report.get("overload_negative_control"),
    }
    report["problems"] = validate_caption_integrity_report(report, expected_source_sha=source_sha)
    report["status"] = "PASS" if not report["problems"] else "FAIL"
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-tree", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audio", action="append", type=Path)
    parser.add_argument(
        "--caption-python",
        type=Path,
        help="the signed packaged Python runtime containing faster-whisper; defaults to this process",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    audio_segments = (
        [path.resolve() for path in args.audio] if args.audio else _default_audio_segments()
    )
    report = run_caption_integrity_proof(
        runtime_tree=args.runtime_tree.resolve(),
        model_dir=args.model_dir.resolve(),
        output=args.output.resolve(),
        audio_segments=audio_segments,
        caption_python=(
            args.caption_python.resolve() if args.caption_python else Path(sys.executable)
        ),
    )
    output_path = args.output.resolve() / "caption-integrity-report.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
