# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the E.2 virtual-headend proof harness.

This is test-only infrastructure. It composes the virtual-headend harness under
``tests/egress`` and writes machine-readable evidence. It must not be imported
from station runtime code.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from civiccast.captions.models import CaptionCue
from civiccast.cg.service import build_emergency_overlay, build_overlay_contract
from civiccast.egress.caption_embed import (
    evaluate_caption_decode_back,
    load_caption_cues_from_timed_text,
)
from civiccast.egress.cg_bridge import build_cg_overlay_egress_proof
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
)
from civiccast.egress.runtime import write_concat_plan
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.supervisor import PlayoutSupervisor
from civiccast.stream.loudness import check_streaming_loudness
from tests.egress.virtual_headend_gate import (
    ExpectedOnAirWindow,
    ObservedHeadendSample,
    analyze_virtual_headend_output,
)
from tests.egress.virtual_headend_impairment import (
    NetemProfile,
    apply_netem_profile,
    remove_netem_profile,
    required_netem_profiles,
)
from tests.egress.virtual_headend_lifecycle import (
    EncoderProcessController,
    PlayoutSupervisorLifecycleDriver,
    ProcessRestartProbe,
)
from tests.egress.virtual_headend_media import default_virtual_headend_media_specs
from tests.egress.virtual_headend_receiver import (
    MarkerReader,
    ReceiverCaptureResult,
    build_audio_tone_marker_reader,
    run_virtual_headend_receiver_capture,
    samples_from_receiver_probe,
)
from tests.egress.virtual_headend_scenario import (
    GeneratedTestMediaSet,
    ScenarioRecoveryEvidence,
    VirtualHeadendProofReport,
    run_virtual_headend_scenario,
)

ScenarioExitMode = Literal["pass-only", "allow-partial"]


@dataclass(frozen=True)
class PrerequisiteEvidence:
    """One required command-line prerequisite."""

    name: str
    executable: str | None
    status: Literal["PASS", "FAIL"]
    detail: str


@dataclass(frozen=True)
class NegativeControlEvidence:
    """Proof that the analyzer rejects known-bad receiver observations."""

    name: str
    expected_code: str
    status: Literal["PASS", "FAIL"]
    observed_codes: tuple[str, ...]


@dataclass(frozen=True)
class RunnerEvidence:
    """Top-level proof runner evidence."""

    status: Literal["PASS", "PARTIAL", "FAIL"]
    proof_report_path: str | None
    work_dir: str
    prerequisites: tuple[PrerequisiteEvidence, ...]
    negative_controls: tuple[NegativeControlEvidence, ...]
    proof_report: dict[str, object] | None
    matrix_reports: tuple[dict[str, object], ...]
    blocker: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--proof-report-path", type=Path)
    parser.add_argument("--channel-id", default="gov")
    parser.add_argument("--receiver-input-url", default="generated:first")
    parser.add_argument("--srt-loopback-port", type=int, default=19001)
    parser.add_argument("--srt-loopback-startup-seconds", type=float, default=0.75)
    parser.add_argument("--netem-interface")
    parser.add_argument("--impairment-profile", default="clean")
    parser.add_argument(
        "--impairment-matrix",
        action="store_true",
        help="Run every required tc netem profile; requires --netem-interface.",
    )
    parser.add_argument("--boundary-count", type=int, default=3)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--tc", default="tc")
    parser.add_argument(
        "--tested-commit",
        help="Commit hash to record in the E.2 proof report; defaults to git HEAD.",
    )
    parser.add_argument(
        "--tested-ref",
        help="Branch or tag name to record in the E.2 proof report; defaults to the current git ref.",
    )
    parser.add_argument("--verify-loudness", action="store_true")
    parser.add_argument("--loudness-target-lufs", type=float, default=-16.0)
    parser.add_argument("--loudness-tolerance-lufs", type=float, default=2.0)
    parser.add_argument(
        "--verify-caption-decode-back",
        action="store_true",
        help="Embed generated timed-text into a test artifact and decode it back.",
    )
    parser.add_argument("--self-test-only", action="store_true")
    parser.add_argument(
        "--process-restart-probe",
        action="store_true",
        help="Use a real child-process kill/relaunch probe for daemon restart evidence.",
    )
    parser.add_argument(
        "--ffmpeg-child-restart-probe",
        action="store_true",
        help="Use a real child-process kill/relaunch probe for FFmpeg-child restart evidence.",
    )
    parser.add_argument("--exit-mode", choices=("pass-only", "allow-partial"), default="pass-only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    evidence = run_proof_from_args(args)
    output_path = args.proof_report_path or args.work_dir / "proof" / "virtual-headend-proof.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if evidence.proof_report_path is None:
        output_path.write_text(evidence.to_json(), encoding="utf-8")
    print(evidence.to_json())
    if evidence.status == "PASS":
        return 0
    if evidence.status == "PARTIAL" and args.exit_mode == "allow-partial":
        return 0
    return 1


def run_proof_from_args(args: argparse.Namespace) -> RunnerEvidence:
    work_dir = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    proof_report_path = args.proof_report_path or work_dir / "proof" / "virtual-headend-proof.json"
    prerequisites = collect_prerequisites(
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        tc=args.tc,
        require_tc=args.netem_interface is not None or args.impairment_matrix,
    )
    negative_controls = run_negative_control_self_test()
    blocker = (
        "MISSING_NETEM_INTERFACE_FOR_IMPAIRMENT_MATRIX"
        if args.impairment_matrix and not args.netem_interface
        else _first_blocker(prerequisites=prerequisites, negative_controls=negative_controls)
    )
    if blocker is not None:
        return RunnerEvidence(
            status="FAIL",
            proof_report_path=None,
            work_dir=str(work_dir),
            prerequisites=prerequisites,
            negative_controls=negative_controls,
            proof_report=None,
            matrix_reports=(),
            blocker=blocker,
        )
    if args.self_test_only:
        return RunnerEvidence(
            status="PASS",
            proof_report_path=None,
            work_dir=str(work_dir),
            prerequisites=prerequisites,
            negative_controls=negative_controls,
            proof_report=None,
            matrix_reports=(),
            blocker=None,
        )
    if args.impairment_matrix:
        return _run_impairment_matrix(args, prerequisites, negative_controls)
    profile = _profile_by_name(args.impairment_profile)
    media_holder: list[GeneratedTestMediaSet] = []
    sequence_holder: list[Path] = []
    scenario_result = _run_one_profile(
        args=args,
        work_dir=work_dir,
        proof_report_path=proof_report_path,
        profile=profile,
        media_holder=media_holder,
        sequence_holder=sequence_holder,
    )
    proof = json.loads(scenario_result.proof_report.to_json())
    return RunnerEvidence(
        status=scenario_result.proof_report.status,
        proof_report_path=str(scenario_result.proof_report_path),
        work_dir=str(work_dir),
        prerequisites=prerequisites,
        negative_controls=negative_controls,
        proof_report=proof,
        matrix_reports=(),
        blocker=_proof_blocker(scenario_result.proof_report),
    )


def _run_one_profile(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    proof_report_path: Path,
    profile: NetemProfile,
    media_holder: list[GeneratedTestMediaSet],
    sequence_holder: list[Path] | None = None,
):
    return run_virtual_headend_scenario(
        channel_id=args.channel_id,
        work_dir=work_dir,
        profile=CanonicalProfile(width=640, height=360),
        receiver_input_url=args.receiver_input_url,
        receiver_input_url_provider=_receiver_input_url_provider(
            args,
            work_dir,
            media_holder,
            sequence_holder=sequence_holder,
        ),
        impairment_profile=profile,
        netem_interface=args.netem_interface,
        proof_report_path=proof_report_path,
        ffmpeg_version=_tool_version(args.ffmpeg, fallback="ffmpeg version unavailable"),
        libsrt_version=_libsrt_version(args.ffmpeg),
        git_commit=getattr(args, "tested_commit", None) or _git_value(("rev-parse", "HEAD")),
        git_ref=getattr(args, "tested_ref", None) or _git_ref_value(),
        lifecycle_driver=_playout_supervisor_lifecycle_driver(
            args=args,
            work_dir=work_dir,
        ),
        artifact_analyzer=lambda received_path, expected_timeline: analyze_virtual_headend_output(
            expected_timeline=expected_timeline,
            samples=samples_from_receiver_probe(
                probe_json=_ffprobe_json(args.ffprobe, received_path),
                expected_timeline=expected_timeline,
                marker_reader=_marker_reader_for_received_output(
                    received_path=received_path,
                    media_holder=media_holder,
                ),
            ),
        ),
        boundary_count=args.boundary_count,
        media_specs=_media_specs_for_runner(args.receiver_input_url, args.boundary_count),
        receiver_capture_runner=_receiver_capture_runner_for_args(
            args,
            sequence_holder=sequence_holder,
        ),
        netem_applier=lambda interface, profile: apply_netem_profile(
            interface=interface,
            profile=profile,
            tc=args.tc,
        ),
        netem_cleaner=lambda interface: remove_netem_profile(
            interface=interface,
            tc=args.tc,
        ),
        loudness_target_lufs=args.loudness_target_lufs,
        loudness_checker=_loudness_checker(args) if args.verify_loudness else None,
        caption_decode_back_checker=(
            _caption_decode_back_checker(
                args=args,
                work_dir=work_dir,
                media_holder=media_holder,
            )
            if args.verify_caption_decode_back
            else None
        ),
    )


def _run_impairment_matrix(
    args: argparse.Namespace,
    prerequisites: tuple[PrerequisiteEvidence, ...],
    negative_controls: tuple[NegativeControlEvidence, ...],
) -> RunnerEvidence:
    matrix_reports: list[dict[str, object]] = []
    blocker: str | None = None
    status: Literal["PASS", "PARTIAL", "FAIL"] = "PASS"
    for profile in required_netem_profiles():
        profile_work_dir = args.work_dir / "impairment-matrix" / profile.name
        profile_report_path = profile_work_dir / "proof" / "virtual-headend-proof.json"
        media_holder: list[GeneratedTestMediaSet] = []
        sequence_holder: list[Path] = []
        scenario_result = _run_one_profile(
            args=args,
            work_dir=profile_work_dir,
            proof_report_path=profile_report_path,
            profile=profile,
            media_holder=media_holder,
            sequence_holder=sequence_holder,
        )
        proof = json.loads(scenario_result.proof_report.to_json())
        matrix_reports.append(
            {
                "profile": profile.name,
                "proof_report_path": str(scenario_result.proof_report_path),
                "proof_report": proof,
            }
        )
        profile_blocker = _proof_blocker(scenario_result.proof_report)
        if profile_blocker is not None and blocker is None:
            blocker = f"{profile.name}:{profile_blocker}"
        if scenario_result.proof_report.status == "FAIL":
            status = "FAIL"
        elif scenario_result.proof_report.status == "PARTIAL" and status == "PASS":
            status = "PARTIAL"
    aggregate_report: dict[str, object] = {
        "status": status,
        "profiles": [report["profile"] for report in matrix_reports],
        "profile_count": len(matrix_reports),
        "passed_profiles": [
            report["profile"]
            for report in matrix_reports
            if isinstance(report["proof_report"], dict)
            and report["proof_report"].get("status") == "PASS"
        ],
        "not_claimed": (
            "This matrix does not validate a real cable headend.",
            "This matrix does not validate QAM modulation, SDI output, or a specific operator box.",
        ),
    }
    return RunnerEvidence(
        status=status,
        proof_report_path=None,
        work_dir=str(args.work_dir),
        prerequisites=prerequisites,
        negative_controls=negative_controls,
        proof_report=aggregate_report,
        matrix_reports=tuple(matrix_reports),
        blocker=blocker,
    )


def collect_prerequisites(
    *,
    ffmpeg: str,
    ffprobe: str,
    tc: str,
    require_tc: bool,
) -> tuple[PrerequisiteEvidence, ...]:
    return (
        _command_prerequisite("ffmpeg", ffmpeg, required=True),
        _command_prerequisite("ffprobe", ffprobe, required=True),
        _command_prerequisite("tc", tc, required=require_tc),
    )


def run_negative_control_self_test() -> tuple[NegativeControlEvidence, ...]:
    timeline = _negative_control_timeline()
    cases: tuple[tuple[str, tuple[ObservedHeadendSample, ...], str], ...] = (
        (
            "black gap",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001", black=True),
            ),
            "UNEXPECTED_BLACK_VIDEO",
        ),
        (
            "codec switch",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(
                    pts_seconds=1.0,
                    marker="SEGMENT 001",
                    profile_id="wrong-profile",
                ),
            ),
            "CODEC_OR_PROFILE_SWITCH",
        ),
        (
            "connection drop",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=4.0, marker="SLATE", connected=False),
            ),
            "CONNECTION_DROP_OR_DEAD_AIR",
        ),
        (
            "audio silence",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001", audio_rms=0.0),
            ),
            "UNEXPECTED_AUDIO_SILENCE",
        ),
        (
            "output pts discontinuity",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=0.5, marker="SEGMENT 001"),
            ),
            "OUTPUT_PTS_DISCONTINUITY",
        ),
    )
    evidence: list[NegativeControlEvidence] = []
    for name, samples, expected_code in cases:
        report = analyze_virtual_headend_output(expected_timeline=timeline, samples=samples)
        observed_codes = tuple(finding.code for finding in report.findings)
        evidence.append(
            NegativeControlEvidence(
                name=name,
                expected_code=expected_code,
                status=(
                    "PASS"
                    if report.status == "FAIL" and expected_code in observed_codes
                    else "FAIL"
                ),
                observed_codes=observed_codes,
            )
        )
    return tuple(evidence)


def _metadata_only_lifecycle_driver(
    *,
    process_restart_probe: bool,
    ffmpeg_child_restart_probe: bool,
) -> Callable[..., ScenarioRecoveryEvidence]:
    def drive(
        *,
        events: tuple[object, ...],
        media_set: object,
    ) -> ScenarioRecoveryEvidence:
        _ = (events, media_set)
        daemon_restart_seconds = ProcessRestartProbe()() if process_restart_probe else None
        ffmpeg_restart_seconds = ProcessRestartProbe()() if ffmpeg_child_restart_probe else None
        return ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=daemon_restart_seconds,
            ffmpeg_child_restart_recovery_seconds=ffmpeg_restart_seconds,
        )

    return drive


def _playout_supervisor_lifecycle_driver(
    *,
    args: argparse.Namespace,
    work_dir: Path,
) -> Callable[..., ScenarioRecoveryEvidence]:
    def drive(
        *,
        events: tuple[object, ...],
        media_set: GeneratedTestMediaSet,
    ) -> ScenarioRecoveryEvidence:
        store = InMemoryEgressStore()
        store.upsert_config(
            EgressConfig(
                channel_id=args.channel_id,
                enabled=True,
                slate_message="CivicCast virtual-headend slate.",
                sinks=[
                    EgressSinkSpec(
                        kind="file",
                        label="Virtual headend supervisor proof",
                        uri=str(work_dir / "supervisor" / "proof.ts"),
                    )
                ],
            )
        )
        process_controller = EncoderProcessController()
        program_plans = _program_source_plans(
            media_set=media_set,
            channel_id=args.channel_id,
        )
        next_program_index = 0

        def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
            nonlocal next_program_index
            plans: list[EgressSourcePlan] = []
            for _index in range(window):
                plans.append(program_plans[next_program_index % len(program_plans)])
                next_program_index += 1
            return [plan.model_copy(update={"channel_id": channel_id}) for plan in plans]

        supervisor = PlayoutSupervisor(
            store,
            work_dir=work_dir / "supervisor",
            source_plan_provider=lambda _channel_id: None,
            lookahead_source_plan_provider=lookahead_provider,
            lookahead_window=max(1, args.boundary_count + 1),
            fallback_source_provider=lambda config: _single_kind_source_plan(
                media_set=media_set,
                channel_id=config.channel_id,
                kind="slate",
            ),
            ffmpeg_starter=process_controller.start,
        )
        restart_daemon = ProcessRestartProbe() if args.process_restart_probe else (lambda: 0.0)
        lifecycle_driver = PlayoutSupervisorLifecycleDriver(
            channel_id=args.channel_id,
            store=store,
            supervisor=supervisor,
            process_controller=process_controller,
            fallback_reason="virtual-headend removed the scheduled asset",
            cg_overlay_proof=build_cg_overlay_egress_proof(
                overlay=build_emergency_overlay(
                    overlay_id="virtual-headend-emergency-overlay",
                    severity="warning",
                ),
                overlay_contract=build_overlay_contract(channel_id=args.channel_id),
            ),
            restart_daemon=restart_daemon,
            clock=time.monotonic,
        )
        evidence = lifecycle_driver(
            events=events,  # type: ignore[arg-type]
            media_set=media_set,
        )
        if not args.ffmpeg_child_restart_probe:
            return evidence
        return evidence

    return drive


def _program_source_plans(
    *,
    media_set: GeneratedTestMediaSet,
    channel_id: str,
) -> list[EgressSourcePlan]:
    plans = [
        EgressSourcePlan(channel_id=channel_id, segments=[segment])
        for segment in media_set.source_plan.segments
        if segment.kind == "program"
    ]
    if not plans:
        raise RuntimeError("generated media set does not include program sources")
    return plans


def _single_kind_source_plan(
    *,
    media_set: GeneratedTestMediaSet,
    channel_id: str,
    kind: str,
) -> EgressSourcePlan:
    for segment in media_set.source_plan.segments:
        if segment.kind == kind:
            return EgressSourcePlan(channel_id=channel_id, segments=[segment])
    raise RuntimeError(f"generated media set does not include a {kind!r} source")


def _loudness_checker(
    args: argparse.Namespace,
) -> Callable[[Path], tuple[str, float, float | None, str]]:
    def check(received_path: Path) -> tuple[str, float, float | None, str]:
        result = check_streaming_loudness(
            media_path=received_path,
            target_lufs=args.loudness_target_lufs,
            tolerance_lufs=args.loudness_tolerance_lufs,
        )
        return result.status, result.target_lufs, result.measured_lufs, result.operator_action

    return check


def _caption_decode_back_checker(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    media_holder: list[GeneratedTestMediaSet],
) -> Callable[[Path], tuple[str, dict[str, object]]]:
    def check(received_path: Path) -> tuple[str, dict[str, object]]:
        expected_path = work_dir / "captions" / "expected.vtt"
        decoded_path = work_dir / "captions" / "decoded.vtt"
        artifact_path = work_dir / "captions" / "caption-proof.mkv"
        expected_cues = _write_expected_caption_vtt(
            output_path=expected_path,
            media_holder=media_holder,
        )
        embed = _run_caption_embed_artifact(
            ffmpeg=args.ffmpeg,
            received_path=received_path,
            expected_caption_path=expected_path,
            artifact_path=artifact_path,
        )
        if embed.returncode != 0:
            return "fail", _caption_failure_proof(
                channel_id=args.channel_id,
                received_path=received_path,
                artifact_path=artifact_path,
                expected_cues=expected_cues,
                decoded_cues=(),
                blocker="EGRESS_CAPTION_DECODE_BACK_EMBED_FAILED",
                detail=embed.stderr,
            )
        decode = _run_caption_decode_back(
            ffmpeg=args.ffmpeg,
            artifact_path=artifact_path,
            decoded_path=decoded_path,
        )
        if decode.returncode != 0:
            return "fail", _caption_failure_proof(
                channel_id=args.channel_id,
                received_path=received_path,
                artifact_path=artifact_path,
                expected_cues=expected_cues,
                decoded_cues=(),
                blocker="EGRESS_CAPTION_DECODE_BACK_DECODE_FAILED",
                detail=decode.stderr,
            )
        decoded_cues = tuple(
            load_caption_cues_from_timed_text(decoded_path, source_id="decoded-caption-proof")
        )
        proof = evaluate_caption_decode_back(
            channel_id=args.channel_id,
            emitted_stream_path=artifact_path,
            expected_cues=list(expected_cues),
            decoded_cues=list(decoded_cues),
            decoder_name="ffmpeg-webvtt-decode-back",
        )
        proof_data = proof.model_dump(mode="json")
        proof_data["expected_caption_path"] = str(expected_path)
        proof_data["decoded_caption_path"] = str(decoded_path)
        proof_data["caption_artifact_path"] = str(artifact_path)
        proof_data["source_receiver_artifact_path"] = str(received_path)
        proof_data["not_claimed"] = [
            *proof_data["not_claimed"],
            "This test-only proof embeds WebVTT into a software receiver artifact.",
            "This test-only proof does not claim CEA-708 ancillary data survived MPEG-TS.",
        ]
        return ("pass" if proof.status == "PASS" else "fail"), proof_data

    return check


def _write_expected_caption_vtt(
    *,
    output_path: Path,
    media_holder: list[GeneratedTestMediaSet],
) -> tuple[CaptionCue, ...]:
    if not media_holder:
        raise RuntimeError("generated media set is required for caption decode-back proof")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for index, window in enumerate(media_holder[0].expected_timeline, start=1):
        start = window.start_seconds + 0.2
        end = max(start + 0.5, window.end_seconds - 0.2)
        lines.extend(
            [
                f"caption-{index:03d}",
                f"{_vtt_timestamp(start)} --> {_vtt_timestamp(end)}",
                f"CivicCast caption proof {window.marker}.",
                "",
            ]
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return tuple(load_caption_cues_from_timed_text(output_path, source_id="expected-caption-proof"))


def _run_caption_embed_artifact(
    *,
    ffmpeg: str,
    received_path: Path,
    expected_caption_path: Path,
    artifact_path: Path,
) -> subprocess.CompletedProcess[str]:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(received_path),
            "-i",
            str(expected_caption_path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-map",
            "1:s:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "webvtt",
            "-f",
            "matroska",
            str(artifact_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _run_caption_decode_back(
    *,
    ffmpeg: str,
    artifact_path: Path,
    decoded_path: Path,
) -> subprocess.CompletedProcess[str]:
    decoded_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(artifact_path),
            "-map",
            "0:s:0",
            "-f",
            "webvtt",
            str(decoded_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _caption_failure_proof(
    *,
    channel_id: str,
    received_path: Path,
    artifact_path: Path,
    expected_cues: tuple[CaptionCue, ...],
    decoded_cues: tuple[CaptionCue, ...],
    blocker: str,
    detail: str,
) -> dict[str, object]:
    proof = evaluate_caption_decode_back(
        channel_id=channel_id,
        emitted_stream_path=artifact_path,
        expected_cues=list(expected_cues),
        decoded_cues=list(decoded_cues),
        decoder_name="ffmpeg-webvtt-decode-back",
    ).model_dump(mode="json")
    proof["source_receiver_artifact_path"] = str(received_path)
    proof["caption_artifact_path"] = str(artifact_path)
    proof["blocker"] = blocker
    proof["detail"] = detail
    return proof


def _vtt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _media_specs_for_runner(receiver_input_url: str, boundary_count: int) -> object:
    if receiver_input_url == "generated:first":
        _ = boundary_count
        return default_virtual_headend_media_specs(program_segments=4)
    if receiver_input_url in {"generated:sequence", "generated:sequence-srt"}:
        return default_virtual_headend_media_specs(program_segments=max(1, boundary_count + 1))
    return None


def _receiver_input_url_provider(
    args: argparse.Namespace,
    work_dir: Path,
    media_holder: list[GeneratedTestMediaSet],
    *,
    sequence_holder: list[Path] | None = None,
) -> Callable[[GeneratedTestMediaSet], str] | None:
    if args.receiver_input_url == "generated:first":
        return _generated_first_media_url(media_holder)
    if args.receiver_input_url == "generated:sequence":
        return _generated_sequence_media_url(
            work_dir=work_dir,
            ffmpeg=args.ffmpeg,
            media_holder=media_holder,
        )
    if args.receiver_input_url == "generated:sequence-srt":
        return _generated_sequence_srt_media_url(
            work_dir=work_dir,
            ffmpeg=args.ffmpeg,
            port=args.srt_loopback_port,
            media_holder=media_holder,
            sequence_holder=sequence_holder if sequence_holder is not None else [],
        )
    return None


def _generated_first_media_url(
    media_holder: list[GeneratedTestMediaSet],
) -> Callable[[GeneratedTestMediaSet], str]:
    def provide(media_set: GeneratedTestMediaSet) -> str:
        media_holder.clear()
        media_holder.append(media_set)
        if not media_set.output_paths:
            raise RuntimeError("generated media set did not include output paths")
        return str(media_set.output_paths[0])

    return provide


def _generated_sequence_media_url(
    *,
    work_dir: Path,
    ffmpeg: str,
    media_holder: list[GeneratedTestMediaSet],
) -> Callable[[GeneratedTestMediaSet], str]:
    def provide(media_set: GeneratedTestMediaSet) -> str:
        media_holder.clear()
        media_holder.append(media_set)
        if not media_set.output_paths:
            raise RuntimeError("generated media set did not include output paths")
        sequence_path = work_dir / "receiver-input" / "generated-sequence.ts"
        concat_plan_path = work_dir / "receiver-input" / "generated-sequence.ffconcat"
        write_concat_plan(concat_plan_path, media_set.source_plan)
        result = _run_generated_sequence_artifact(
            ffmpeg=ffmpeg,
            concat_plan_path=concat_plan_path,
            sequence_path=sequence_path,
        )
        if result.returncode != 0:
            raise RuntimeError(f"generated sequence artifact failed: {result.stderr}")
        return str(sequence_path)

    return provide


def _generated_sequence_srt_media_url(
    *,
    work_dir: Path,
    ffmpeg: str,
    port: int,
    media_holder: list[GeneratedTestMediaSet],
    sequence_holder: list[Path],
) -> Callable[[GeneratedTestMediaSet], str]:
    sequence_provider = _generated_sequence_media_url(
        work_dir=work_dir,
        ffmpeg=ffmpeg,
        media_holder=media_holder,
    )

    def provide(media_set: GeneratedTestMediaSet) -> str:
        sequence_path = Path(sequence_provider(media_set))
        sequence_holder.clear()
        sequence_holder.append(sequence_path)
        return f"srt://127.0.0.1:{port}?mode=listener&latency=200000"

    return provide


def _run_generated_sequence_artifact(
    *,
    ffmpeg: str,
    concat_plan_path: Path,
    sequence_path: Path,
) -> subprocess.CompletedProcess[str]:
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    profile = CanonicalProfile(width=640, height=360)
    return subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_plan_path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-vf",
            f"fps={profile.fps},scale={profile.width}:{profile.height},format=yuv420p",
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-maxrate",
            f"{profile.video_bitrate_kbps}k",
            "-bufsize",
            f"{profile.video_bitrate_kbps * 2}k",
            "-g",
            str(profile.gop_size),
            "-r",
            str(profile.fps),
            "-af",
            "aresample=async=1:first_pts=0",
            "-c:a",
            profile.audio_codec,
            "-b:a",
            f"{profile.audio_bitrate_kbps}k",
            "-ar",
            str(profile.audio_sample_rate),
            "-ac",
            str(profile.audio_channels),
            "-f",
            "mpegts",
            str(sequence_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _receiver_capture_runner_for_args(
    args: argparse.Namespace,
    *,
    sequence_holder: list[Path] | None,
):
    if args.receiver_input_url != "generated:sequence-srt":
        return run_virtual_headend_receiver_capture

    def capture(
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ):
        if not sequence_holder:
            raise RuntimeError("generated sequence SRT capture has no sender artifact")
        return _run_srt_loopback_receiver_capture(
            ffmpeg=args.ffmpeg,
            input_url=input_url,
            sender_input_path=sequence_holder[0],
            output_path=output_path,
            duration_seconds=duration_seconds,
            startup_seconds=args.srt_loopback_startup_seconds,
        )

    return capture


def _run_srt_loopback_receiver_capture(
    *,
    ffmpeg: str,
    input_url: str,
    sender_input_path: Path,
    output_path: Path,
    duration_seconds: float | None,
    startup_seconds: float,
):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    receiver_args = _srt_loopback_receiver_args(
        ffmpeg=ffmpeg,
        input_url=input_url,
        output_path=output_path,
        duration_seconds=duration_seconds,
    )
    sender_url = input_url.replace("mode=listener", "mode=caller")
    if "linger=" not in sender_url:
        separator = "&" if "?" in sender_url else "?"
        sender_url = f"{sender_url}{separator}linger=5"
    sender_args = _srt_loopback_sender_args(
        ffmpeg=ffmpeg,
        sender_input_path=sender_input_path,
        sender_url=sender_url,
    )
    receiver = subprocess.Popen(
        receiver_args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sender = None
    try:
        time.sleep(max(0.0, startup_seconds))
        sender = subprocess.Popen(
            sender_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        timeout = (duration_seconds or 30.0) + 15.0
        _sender_stdout, sender_stderr = sender.communicate(timeout=timeout)
        time.sleep(0.5)
        if receiver.poll() is None:
            receiver.terminate()
        try:
            _receiver_stdout, receiver_stderr = receiver.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            receiver.kill()
            _receiver_stdout, receiver_stderr = receiver.communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        _terminate_process(sender)
        _terminate_process(receiver)
        return _receiver_capture_result(
            output_path=output_path,
            returncode=1,
            blocker="VIRTUAL_HEADEND_SRT_LOOPBACK_TIMEOUT",
            args=tuple(receiver_args + sender_args),
            stderr=str(exc),
        )
    finally:
        _terminate_process(sender)
        _terminate_process(receiver)
    stderr = "\n".join(part for part in (sender_stderr, receiver_stderr) if part)
    blocker = _srt_loopback_blocker(
        sender_returncode=sender.returncode,
        receiver_returncode=receiver.returncode,
        output_exists=output_path.exists(),
        receiver_stderr=receiver_stderr,
    )
    return _receiver_capture_result(
        output_path=output_path,
        returncode=0 if blocker is None else 1,
        blocker=blocker,
        args=tuple(receiver_args + sender_args),
        stderr=stderr,
    )


def _srt_loopback_blocker(
    *,
    sender_returncode: int | None,
    receiver_returncode: int | None,
    output_exists: bool,
    receiver_stderr: str,
) -> str | None:
    if sender_returncode != 0:
        return "VIRTUAL_HEADEND_SRT_SENDER_FAILED"
    if not output_exists:
        return "VIRTUAL_HEADEND_SRT_RECEIVER_OUTPUT_MISSING"
    if receiver_returncode != 0 and receiver_stderr.strip():
        return "VIRTUAL_HEADEND_SRT_RECEIVER_FAILED"
    return None


def _srt_loopback_receiver_args(
    *,
    ffmpeg: str,
    input_url: str,
    output_path: Path,
    duration_seconds: float | None,
) -> list[str]:
    receiver_mode, receiver_input_url = _split_srt_mode_preserving_query(input_url)
    duration_args = ["-t", f"{duration_seconds:g}"] if duration_seconds is not None else []
    mode_args = ["-mode", receiver_mode or "listener"]
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        *mode_args,
        *duration_args,
        "-i",
        receiver_input_url,
        "-c",
        "copy",
        "-f",
        "mpegts",
        str(output_path),
    ]


def _srt_loopback_sender_args(
    *,
    ffmpeg: str,
    sender_input_path: Path,
    sender_url: str,
) -> list[str]:
    sender_mode, sender_output_url = _split_srt_mode_preserving_query(sender_url)
    mode_args = ["-mode", sender_mode or "caller"]
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-i",
        str(sender_input_path),
        "-c",
        "copy",
        "-f",
        "mpegts",
        *mode_args,
        sender_output_url,
    ]


def _receiver_capture_result(
    *,
    output_path: Path,
    returncode: int,
    blocker: str | None,
    args: tuple[str, ...],
    stderr: str,
):
    return ReceiverCaptureResult(
        status="PASS" if blocker is None else "FAIL",
        receiver_output_path=output_path,
        ffmpeg_returncode=returncode,
        blocker=blocker,
        ffmpeg_args=args if not stderr else (*args, f"stderr:{stderr}"),
    )


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _split_srt_mode_preserving_query(url: str) -> tuple[str | None, str]:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "srt":
        return None, url
    query = parse_qsl(parsed.query, keep_blank_values=True)
    mode = None
    kept_query: list[tuple[str, str]] = []
    for key, value in query:
        if key.lower() == "mode" and mode is None:
            mode = value
        else:
            kept_query.append((key, value))
    return mode, urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(kept_query),
            parsed.fragment,
        )
    )


def _marker_reader_for_received_output(
    *,
    received_path: Path,
    media_holder: list[GeneratedTestMediaSet],
) -> MarkerReader:
    if not media_holder or not media_holder[0].marker_tones_hz:
        return _unavailable_audio_marker_reader
    return build_audio_tone_marker_reader(
        received_path=received_path,
        marker_tones_hz=media_holder[0].marker_tones_hz,
    )


def _unavailable_audio_marker_reader(
    pts_seconds: float,
    expected: ExpectedOnAirWindow | None,
) -> str:
    _ = (pts_seconds, expected)
    return "AUDIO_MARKER_UNAVAILABLE"


def _ffprobe_json(ffprobe: str, received_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_frames",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate:"
            "frame=media_type,best_effort_timestamp_time,pts_time",
            "-of",
            "json",
            str(received_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for received output: {completed.stderr}")
    return json.loads(completed.stdout)


def _command_prerequisite(name: str, command: str, *, required: bool) -> PrerequisiteEvidence:
    executable = shutil.which(command)
    if executable is None:
        return PrerequisiteEvidence(
            name=name,
            executable=None,
            status="FAIL" if required else "PASS",
            detail="missing" if required else "not required for this run",
        )
    return PrerequisiteEvidence(name=name, executable=executable, status="PASS", detail="found")


def _first_blocker(
    *,
    prerequisites: tuple[PrerequisiteEvidence, ...],
    negative_controls: tuple[NegativeControlEvidence, ...],
) -> str | None:
    failed_prerequisite = next(
        (prerequisite for prerequisite in prerequisites if prerequisite.status == "FAIL"),
        None,
    )
    if failed_prerequisite is not None:
        return f"MISSING_PREREQUISITE_{failed_prerequisite.name.upper()}"
    failed_negative_control = next(
        (control for control in negative_controls if control.status == "FAIL"),
        None,
    )
    if failed_negative_control is not None:
        return f"NEGATIVE_CONTROL_DID_NOT_FAIL_{failed_negative_control.expected_code}"
    return None


def _proof_blocker(proof_report: VirtualHeadendProofReport) -> str | None:
    if proof_report.status == "PASS":
        return None
    if proof_report.findings:
        return proof_report.findings[0].code
    if proof_report.daemon_restart_recovery_seconds is None:
        return "DAEMON_RESTART_NOT_PROCESS_REAL"
    if proof_report.ffmpeg_child_restart_recovery_seconds is None:
        return "FFMPEG_CHILD_RESTART_NOT_OBSERVED"
    if proof_report.loudness_status == "not-verified":
        return "LOUDNESS_NOT_VERIFIED"
    if proof_report.loudness_status not in {"ok", "pass"}:
        return "LOUDNESS_FAILED"
    if proof_report.caption_decode_back_status == "not-verified":
        return "CAPTION_DECODE_BACK_NOT_VERIFIED"
    if proof_report.caption_decode_back_status not in {"ok", "pass"}:
        return "CAPTION_DECODE_BACK_FAILED"
    return f"VIRTUAL_HEADEND_{proof_report.status}"


def _profile_by_name(name: str) -> NetemProfile:
    for profile in required_netem_profiles():
        if profile.name == name:
            return profile
    choices = ", ".join(profile.name for profile in required_netem_profiles())
    raise ValueError(f"unknown impairment profile {name!r}; expected one of {choices}")


def _negative_control_timeline() -> tuple[ExpectedOnAirWindow, ...]:
    return (
        ExpectedOnAirWindow(
            start_seconds=0.0,
            end_seconds=4.0,
            source_label="Program 001",
            marker="SEGMENT 001",
        ),
        ExpectedOnAirWindow(
            start_seconds=4.0,
            end_seconds=8.0,
            source_label="Fallback slate",
            marker="SLATE",
            allow_freeze=True,
            allow_silence=True,
        ),
    )


def _tool_version(command: str, *, fallback: str) -> str:
    try:
        completed = subprocess.run(
            [command, "-version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return fallback
    if completed.returncode != 0:
        return fallback
    return completed.stdout.splitlines()[0] if completed.stdout else fallback


def _libsrt_version(ffmpeg: str) -> str:
    try:
        completed = subprocess.run(
            [ffmpeg, "-version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "libsrt unavailable: ffmpeg not found"
    if completed.returncode != 0:
        return "libsrt unavailable: ffmpeg -version failed"
    for token in completed.stdout.replace("--", " ").split():
        if "libsrt" in token.lower():
            return token
    return "libsrt not reported by ffmpeg -version"


def _git_value(args: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    value = completed.stdout.strip()
    return value or "unknown"


def _git_ref_value() -> str:
    current_branch = _git_value(("branch", "--show-current"))
    if current_branch != "unknown":
        return current_branch
    containing_refs = _git_value(
        ("branch", "--remotes", "--contains", "HEAD", "--format", "%(refname:short)")
    )
    if containing_refs == "unknown":
        return "unknown"
    for ref in containing_refs.splitlines():
        ref = ref.strip()
        if ref.startswith("origin/work/"):
            return ref.removeprefix("origin/")
    for ref in containing_refs.splitlines():
        ref = ref.strip()
        if ref.startswith("origin/") and "HEAD" not in ref:
            return ref.removeprefix("origin/")
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
