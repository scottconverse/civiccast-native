#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Prove the native Windows live-caption transport on three real channels.

The input sidecars must already have been produced by the real caption tap
runtime.  This proof then drives the production feed path:

active.vtt -> CaptionFeedWorker -> GstPlayoutStrategy -> Win32 named pipe ->
worker.py -> live appsrc -> CEA-708 insertion -> emitted MPEG-TS -> decode-back.

The GStreamer child and decoder run with the packaged runtime as their only
plugin/typelib/DLL source.  The report fails unless all three required channels
round-trip the exact cue text.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.captions.models import CaptionCue  # noqa: E402
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text  # noqa: E402
from civiccast.egress.caption_feed import CaptionFeedWorker  # noqa: E402
from civiccast.egress.gst.graph import (  # noqa: E402
    PlayoutGraph,
    caption_embed_leg_live,
    demo_test_graph,
    graph_to_json,
)
from civiccast.egress.gst.strategy import (  # noqa: E402
    GstPlayoutStrategy,
    WindowsWorkerPipeServer,
    _WindowsPipeChannel,
)
from scripts.verify_native_runtime_closure import (  # noqa: E402
    _child_caption_decode_back,
    _child_init_gst,
    build_hostile_environment,
    check_manifest_verification,
)

REQUIRED_CHANNELS: Final[tuple[str, ...]] = (
    "government",
    "education",
    "public",
)
WORKER_PATH: Final[Path] = ROOT / "civiccast" / "egress" / "gst" / "worker.py"
FEED_DEADLINE_SECONDS: Final[float] = 30.0
WORKER_EXIT_SECONDS: Final[float] = 15.0


def build_live_caption_graph(output_ts: Path) -> PlayoutGraph:
    """Return a self-contained live graph using the production caption leg."""

    return replace(
        demo_test_graph(
            out=str(output_ts.resolve()),
            nsrc=1,
            bitrate_kbps=750,
        ),
        captions=caption_embed_leg_live(),
    )


def current_process_pipe_sddl() -> str:
    """SYSTEM plus this proof process identity, matching the service-identity rule."""

    import win32api
    import win32con  # type: ignore[import-untyped]
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_QUERY,
    )
    sid, _attributes = win32security.GetTokenInformation(
        token,
        win32security.TokenUser,
    )
    identity = win32security.ConvertSidToStringSid(sid)
    return f"D:P(A;;GA;;;SY)(A;;GA;;;{identity})"


def _caption_sidecar(sidecar_root: Path, channel_id: str) -> Path:
    return sidecar_root / channel_id / "captions" / "active.vtt"


def _child_environment(runtime_tree: Path, registry_path: Path) -> dict[str, str]:
    environment = build_hostile_environment(
        runtime_tree,
        base_env=os.environ,
        registry_path=registry_path,
    )
    # The installed application payload supplies pywin32.  The proof process
    # supplies it from this exact interpreter's site-packages while the hostile
    # environment still confines all GStreamer discovery to runtime_tree.
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _launch_worker(
    *,
    channel_id: str,
    graph_path: Path,
    pipe_name: str,
    runtime_tree: Path,
    channel_dir: Path,
    python_executable: Path | None = None,
    source_root: Path | None = None,
) -> tuple[subprocess.Popen[str], Any]:
    stdout_path = channel_dir / "worker.stdout.log"
    stderr_path = channel_dir / "worker.stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    environment = _child_environment(
        runtime_tree,
        channel_dir / "gst-registry.bin",
    )
    command = [str(python_executable or sys.executable)]
    if source_root is None:
        command.extend([str(WORKER_PATH), str(graph_path), pipe_name])
    else:
        launcher = (
            "import runpy,sys; "
            f"sys.path.insert(0, {str(runtime_tree / 'python')!r}); "
            f"sys.path.insert(0, {str(source_root)!r}); "
            f"sys.argv={[str(WORKER_PATH), str(graph_path), pipe_name]!r}; "
            f"runpy.run_path({str(WORKER_PATH)!r}, run_name='__main__')"
        )
        command.extend(["-I", "-B", "-c", launcher])
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process, (stdout_handle, stderr_handle)


def _decode_child(
    runtime_tree: Path,
    output_ts: Path,
    expected_text: str,
    *,
    python_executable: Path | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    environment = _child_environment(
        runtime_tree,
        output_ts.with_suffix(".decode-registry.bin"),
    )
    command = [str(python_executable or sys.executable)]
    if source_root is None:
        command.extend(
            [
                str(Path(__file__).resolve()),
                "--decode-child",
                "--runtime-tree",
                str(runtime_tree),
                "--transport-stream",
                str(output_ts),
                "--expected-text",
                expected_text,
            ]
        )
    else:
        script = Path(__file__).resolve()
        launcher = (
            "import runpy,sys; "
            f"sys.path.insert(0, {str(runtime_tree / 'python')!r}); "
            f"sys.path.insert(0, {str(source_root)!r}); "
            f"sys.argv={[str(script), '--decode-child', '--runtime-tree', str(runtime_tree), '--transport-stream', str(output_ts), '--expected-text', expected_text]!r}; "
            f"runpy.run_path({str(script)!r}, run_name='__main__')"
        )
        command.extend(["-I", "-B", "-c", launcher])
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        decoded = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"caption decoder emitted invalid JSON: {completed.stdout!r}; "
            f"stderr={completed.stderr!r}"
        ) from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"caption decoder emitted a non-object result: {completed.stdout!r}")
    payload = cast(dict[str, Any], decoded)
    payload["exit_code"] = completed.returncode
    payload["stderr"] = completed.stderr
    return payload


def _decode_child_main(args: argparse.Namespace) -> int:
    gst = _child_init_gst()
    result = _child_caption_decode_back(
        gst,
        args.transport_stream.resolve(),
        probe_text=args.expected_text,
    )
    # The runtime verifier's ``ok`` value is itself the exact normalized-text
    # assertion; its detail string is human-readable evidence, not decoder input.
    survived = result["ok"]
    payload = {
        "status": "PASS" if result["ok"] else "FAIL",
        "detail": result["detail"],
        "normalized_text_check": survived,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result["ok"] else 1


def _required_sidecar_cues(
    sidecar_root: Path,
) -> dict[str, list[CaptionCue]]:
    cues: dict[str, list[CaptionCue]] = {}
    for channel_id in REQUIRED_CHANNELS:
        path = _caption_sidecar(sidecar_root, channel_id)
        if not path.is_file():
            raise RuntimeError(f"required caption sidecar is missing: {path}")
        loaded = load_caption_cues_from_timed_text(path, source_id=channel_id)
        if not loaded:
            raise RuntimeError(f"required caption sidecar has no cues: {path}")
        cues[channel_id] = loaded
    return cues


def _caption_transport_hold_seconds(
    cues_by_channel: dict[str, list[CaptionCue]],
) -> float:
    """Keep workers live through both late-rebased and genuinely future cues."""

    cues = [cue for channel_cues in cues_by_channel.values() for cue in channel_cues]
    latest_requested_end = max(cue.end_seconds for cue in cues)
    longest_duration = max(cue.end_seconds - cue.start_seconds for cue in cues)
    return max(2.0, latest_requested_end + 1.0, longest_duration + 1.0)


def run_transport_proof(
    *,
    runtime_tree: Path,
    sidecar_root: Path,
    output_dir: Path,
    python_executable: Path | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Run the real three-channel Win32-pipe and GStreamer transport proof."""

    if os.name != "nt":
        raise RuntimeError("native caption transport proof requires Windows")
    verification = check_manifest_verification(runtime_tree)
    if verification.status != "PASS":
        raise RuntimeError(f"packaged runtime manifest verification failed: {verification.detail}")
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite proof directory: {output_dir}")
    output_dir.mkdir(parents=True)

    cues_by_channel = _required_sidecar_cues(sidecar_root)
    strategy = GstPlayoutStrategy(embed_captions=True)
    processes: dict[str, subprocess.Popen[str]] = {}
    log_handles: dict[str, tuple[Any, Any]] = {}
    sddl = current_process_pipe_sddl()
    started_at = time.perf_counter()
    try:
        for channel_id in REQUIRED_CHANNELS:
            channel_dir = output_dir / channel_id
            channel_dir.mkdir()
            output_ts = channel_dir / "captioned.ts"
            graph_path = channel_dir / "playout-graph.json"
            graph_path.write_text(
                graph_to_json(build_live_caption_graph(output_ts)),
                encoding="utf-8",
            )
            server = WindowsWorkerPipeServer(
                channel_id,
                security_descriptor_sddl=sddl,
            )
            pipe_channel = _WindowsPipeChannel(channel_id, server=server)
            pipe_channel.start()
            strategy._pipe_channels[channel_id] = pipe_channel
            process, handles = _launch_worker(
                channel_id=channel_id,
                graph_path=graph_path,
                pipe_name=server.pipe_name,
                runtime_tree=runtime_tree,
                channel_dir=channel_dir,
                python_executable=python_executable,
                source_root=source_root,
            )
            processes[channel_id] = process
            log_handles[channel_id] = handles

        feed = CaptionFeedWorker(
            work_dir=sidecar_root,
            on_air_channels=lambda: list(REQUIRED_CHANNELS),
            caption_cue_provider=lambda channel_id: cues_by_channel[channel_id],
            send_caption_cue=strategy.send_caption_cue,
        )
        deadline = time.monotonic() + FEED_DEADLINE_SECONDS
        feed_result = feed.run_once()
        delivered_channels = set(feed_result.sent_channels)
        dropped_attempts = feed_result.cues_dropped
        while len(delivered_channels) < len(REQUIRED_CHANNELS) and time.monotonic() < deadline:
            failed = {
                channel_id
                for channel_id, process in processes.items()
                if process.poll() is not None
            }
            if failed:
                raise RuntimeError(f"caption worker exited before feed: {sorted(failed)}")
            time.sleep(0.25)
            feed_result = feed.run_once()
            delivered_channels.update(feed_result.sent_channels)
            dropped_attempts += feed_result.cues_dropped
        if len(delivered_channels) < len(REQUIRED_CHANNELS):
            raise RuntimeError(
                "caption feed did not reach all channels: "
                f"delivered={sorted(delivered_channels)} last={feed_result}"
            )

        # The command ack proves appsrc accepted each buffer.  Keep the live
        # pipelines running through cue duration plus the lead window before
        # requesting their normal control-path stop.
        time.sleep(_caption_transport_hold_seconds(cues_by_channel))

        for channel_id in REQUIRED_CHANNELS:
            if not strategy.send_command(sidecar_root, channel_id, "stop"):
                raise RuntimeError(f"worker {channel_id} did not acknowledge stop")
        for channel_id, process in processes.items():
            try:
                process.wait(timeout=WORKER_EXIT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                raise RuntimeError(f"worker {channel_id} did not exit") from exc
            if process.returncode != 0:
                raise RuntimeError(f"worker {channel_id} exited with {process.returncode}")
    finally:
        for channel_id, process in processes.items():
            if process.poll() is None:
                process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
            strategy.close_channel(channel_id)
        for stdout_handle, stderr_handle in log_handles.values():
            stdout_handle.close()
            stderr_handle.close()

    channel_results: dict[str, Any] = {}
    for channel_id in REQUIRED_CHANNELS:
        channel_dir = output_dir / channel_id
        output_ts = channel_dir / "captioned.ts"
        expected_text = " ".join(cue.text for cue in cues_by_channel[channel_id])
        decoded = _decode_child(
            runtime_tree,
            output_ts,
            expected_text,
            python_executable=python_executable,
            source_root=source_root,
        )
        channel_results[channel_id] = {
            "status": decoded["status"],
            "expected_text": expected_text,
            "cue_count": len(cues_by_channel[channel_id]),
            "transport_stream": str(output_ts.resolve()),
            "transport_stream_bytes": output_ts.stat().st_size,
            "decode_back": decoded,
        }

    passed = all(
        result["status"] == "PASS" and result["transport_stream_bytes"] > 0
        for result in channel_results.values()
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "runtime_tree": str(runtime_tree.resolve()),
        "runtime_manifest": verification.detail,
        "sidecar_root": str(sidecar_root.resolve()),
        "required_channels": list(REQUIRED_CHANNELS),
        "feed": {
            "channels": len(REQUIRED_CHANNELS),
            "cues_sent": sum(len(cues) for cues in cues_by_channel.values()),
            "cues_dropped_before_delivery": dropped_attempts,
            "sent_channels": sorted(delivered_channels),
        },
        "channels": channel_results,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-tree", required=True, type=Path)
    parser.add_argument("--sidecar-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--decode-child", action="store_true")
    parser.add_argument("--transport-stream", type=Path)
    parser.add_argument("--expected-text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.decode_child:
        if args.transport_stream is None or not args.expected_text:
            raise SystemExit("--decode-child requires --transport-stream and --expected-text")
        return _decode_child_main(args)
    if args.sidecar_root is None or args.output is None:
        raise SystemExit("transport proof requires --sidecar-root and --output")
    report = run_transport_proof(
        runtime_tree=args.runtime_tree.resolve(),
        sidecar_root=args.sidecar_root.resolve(),
        output_dir=args.output.resolve(),
    )
    report_path = args.output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
