# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Scenario proof-report layer for the E.2 virtual-headend gate."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from civiccast.egress.models import CanonicalProfile
from tests.egress.virtual_headend_gate import (
    ExpectedOnAirWindow,
    VirtualHeadendFinding,
    VirtualHeadendReport,
)
from tests.egress.virtual_headend_impairment import (
    CommandResult,
    NetemProfile,
    apply_netem_profile,
    remove_netem_profile,
)
from tests.egress.virtual_headend_media import (
    GeneratedTestMediaSet,
    VirtualHeadendMediaSpec,
    default_virtual_headend_media_specs,
    generate_virtual_headend_media_set,
)
from tests.egress.virtual_headend_receiver import (
    ReceiverCaptureResult,
    run_virtual_headend_receiver_capture,
)

ScenarioStatus = Literal["PASS", "PARTIAL", "FAIL"]

VIRTUAL_HEADEND_PROOF_NOT_CLAIMED: tuple[str, ...] = (
    "This proof does not validate a real cable headend.",
    "This proof does not validate QAM modulation.",
    "This proof does not validate SDI hardware output.",
    "This proof does not validate EAS certification.",
    "This proof does not validate a specific operator ingest box.",
)


@dataclass(frozen=True)
class BoundaryMarkerResult:
    """Expected-vs-observed marker result for one scheduled boundary."""

    index: int
    expected_start_seconds: float
    expected_marker: str
    observed_marker: str | None
    matched: bool


@dataclass(frozen=True)
class VirtualHeadendScenarioEvent:
    """One expected lifecycle action in the long E.2 scenario."""

    name: str
    expected_marker: str | None = None
    boundary_index: int | None = None


@dataclass(frozen=True)
class ScenarioRecoveryEvidence:
    """Recovery timings captured by the scenario driver."""

    daemon_restart_recovery_seconds: float | None = None
    ffmpeg_child_restart_recovery_seconds: float | None = None


@dataclass(frozen=True)
class VirtualHeadendProofReport:
    """Machine-readable E.2 proof report."""

    status: ScenarioStatus
    boundary_count: int
    impairment_profile: dict[str, object]
    connection_drop_count: int
    timestamp_discontinuity_count: int
    black_frame_intervals: tuple[dict[str, object], ...]
    silence_intervals: tuple[dict[str, object], ...]
    loudness_status: str
    loudness_target_lufs: float
    caption_decode_back_status: str
    daemon_restart_recovery_seconds: float | None
    ffmpeg_child_restart_recovery_seconds: float | None
    caption_decode_back_proof: dict[str, object] | None
    per_boundary_marker_match: tuple[BoundaryMarkerResult, ...]
    ffmpeg_version: str
    libsrt_version: str
    findings: tuple[VirtualHeadendFinding, ...]
    loudness_measured_lufs: float | None = None
    loudness_operator_action: str | None = None
    git_commit: str = "unknown"
    git_ref: str = "unknown"
    not_claimed: tuple[str, ...] = VIRTUAL_HEADEND_PROOF_NOT_CLAIMED

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


@dataclass(frozen=True)
class VirtualHeadendScenarioRunResult:
    """Artifacts from one automated virtual-headend scenario run."""

    proof_report: VirtualHeadendProofReport
    proof_report_path: Path
    receiver_capture: ReceiverCaptureResult
    media_set: GeneratedTestMediaSet
    lifecycle_events: tuple[VirtualHeadendScenarioEvent, ...]
    impairment_apply_results: tuple[CommandResult, ...]
    impairment_cleanup_result: CommandResult | None


class MediaGenerator(Protocol):
    def __call__(
        self,
        *,
        channel_id: str,
        output_dir: Path,
        profile: CanonicalProfile,
        specs: tuple[VirtualHeadendMediaSpec, ...],
    ) -> GeneratedTestMediaSet: ...


class LifecycleDriver(Protocol):
    def __call__(
        self,
        *,
        events: tuple[VirtualHeadendScenarioEvent, ...],
        media_set: GeneratedTestMediaSet,
    ) -> ScenarioRecoveryEvidence: ...


class ReceiverCaptureRunner(Protocol):
    def __call__(
        self,
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ) -> ReceiverCaptureResult: ...


class ReceiverInputUrlProvider(Protocol):
    def __call__(self, media_set: GeneratedTestMediaSet) -> str: ...


class ArtifactAnalyzer(Protocol):
    def __call__(
        self,
        *,
        received_path: Path,
        expected_timeline: tuple[ExpectedOnAirWindow, ...],
    ) -> VirtualHeadendReport: ...


class LoudnessChecker(Protocol):
    def __call__(
        self, received_path: Path
    ) -> tuple[str, float] | tuple[str, float, float | None, str]: ...


class CaptionDecodeBackChecker(Protocol):
    def __call__(self, received_path: Path) -> tuple[str, dict[str, object]]: ...


class NetemApplier(Protocol):
    def __call__(self, *, interface: str, profile: NetemProfile) -> tuple[CommandResult, ...]: ...


class NetemCleaner(Protocol):
    def __call__(self, *, interface: str) -> CommandResult: ...


def build_virtual_headend_lifecycle_events(
    *,
    boundary_count: int,
) -> tuple[VirtualHeadendScenarioEvent, ...]:
    """Build the required E.2 lifecycle event sequence."""

    if boundary_count < 1:
        raise ValueError("boundary_count must be at least 1")
    events: list[VirtualHeadendScenarioEvent] = [
        VirtualHeadendScenarioEvent(name="start-daemon", expected_marker="SEGMENT 001"),
    ]
    events.extend(
        VirtualHeadendScenarioEvent(
            name="program-boundary",
            expected_marker=f"SEGMENT {index + 1:03d}",
            boundary_index=index,
        )
        for index in range(1, boundary_count + 1)
    )
    events.extend(
        [
            VirtualHeadendScenarioEvent(name="remove-scheduled-asset", expected_marker="SLATE"),
            VirtualHeadendScenarioEvent(
                name="restore-scheduled-asset", expected_marker="SEGMENT 001"
            ),
            VirtualHeadendScenarioEvent(name="live-takeover", expected_marker="LIVE SOURCE"),
            VirtualHeadendScenarioEvent(name="live-handback", expected_marker="SEGMENT 001"),
            VirtualHeadendScenarioEvent(
                name="raise-cg-emergency", expected_marker="EMERGENCY OVERLAY"
            ),
            VirtualHeadendScenarioEvent(name="clear-cg-emergency", expected_marker="SEGMENT 001"),
            VirtualHeadendScenarioEvent(name="kill-ffmpeg-child", expected_marker="SEGMENT 001"),
            VirtualHeadendScenarioEvent(name="kill-daemon-process", expected_marker="SEGMENT 001"),
            VirtualHeadendScenarioEvent(name="reload", expected_marker="SEGMENT 001"),
            VirtualHeadendScenarioEvent(name="drain-stop"),
        ]
    )
    return tuple(events)


def run_virtual_headend_scenario(
    *,
    channel_id: str,
    work_dir: Path,
    profile: CanonicalProfile,
    receiver_input_url: str,
    impairment_profile: NetemProfile,
    netem_interface: str | None,
    proof_report_path: Path,
    ffmpeg_version: str,
    libsrt_version: str,
    git_commit: str = "unknown",
    git_ref: str = "unknown",
    lifecycle_driver: LifecycleDriver,
    artifact_analyzer: ArtifactAnalyzer,
    boundary_count: int = 50,
    media_specs: tuple[VirtualHeadendMediaSpec, ...] | None = None,
    media_generator: MediaGenerator = generate_virtual_headend_media_set,
    receiver_input_url_provider: ReceiverInputUrlProvider | None = None,
    receiver_capture_runner: ReceiverCaptureRunner = run_virtual_headend_receiver_capture,
    netem_applier: NetemApplier = apply_netem_profile,
    netem_cleaner: NetemCleaner = remove_netem_profile,
    loudness_status: str = "not-verified",
    loudness_target_lufs: float = -16.0,
    loudness_checker: LoudnessChecker | None = None,
    caption_decode_back_status: str = "not-verified",
    caption_decode_back_checker: CaptionDecodeBackChecker | None = None,
) -> VirtualHeadendScenarioRunResult:
    """Run one E.2 virtual-headend scenario and persist its proof report.

    The lifecycle driver is explicit so this test-only harness can execute the
    real daemon/supervisor in CI while unit tests keep the orchestration fast
    and deterministic.
    """

    media_set = media_generator(
        channel_id=channel_id,
        output_dir=work_dir / "media",
        profile=profile,
        specs=media_specs
        or default_virtual_headend_media_specs(program_segments=boundary_count + 1),
    )
    lifecycle_events = build_virtual_headend_lifecycle_events(boundary_count=boundary_count)
    impairment_apply_results: tuple[CommandResult, ...] = ()
    impairment_cleanup_result: CommandResult | None = None
    recovery_evidence = ScenarioRecoveryEvidence()
    receiver_capture: ReceiverCaptureResult | None = None
    proof_report: VirtualHeadendProofReport | None = None
    active_loudness_status = loudness_status
    active_loudness_target_lufs = loudness_target_lufs
    active_loudness_measured_lufs: float | None = None
    active_loudness_operator_action: str | None = None
    active_caption_decode_back_status = caption_decode_back_status
    active_caption_decode_back_proof: dict[str, object] | None = None
    try:
        if netem_interface is not None:
            impairment_apply_results = netem_applier(
                interface=netem_interface,
                profile=impairment_profile,
            )
        recovery_evidence = lifecycle_driver(events=lifecycle_events, media_set=media_set)
        active_receiver_input_url = (
            receiver_input_url_provider(media_set)
            if receiver_input_url_provider is not None
            else receiver_input_url
        )
        receiver_output_path = work_dir / "receiver" / f"{channel_id}-{impairment_profile.name}.ts"
        duration_seconds = _timeline_duration(media_set.expected_timeline)
        receiver_capture = receiver_capture_runner(
            input_url=active_receiver_input_url,
            output_path=receiver_output_path,
            duration_seconds=duration_seconds,
        )
        if receiver_capture.status == "PASS":
            analyzer_report = artifact_analyzer(
                received_path=receiver_capture.receiver_output_path,
                expected_timeline=media_set.expected_timeline,
            )
            if loudness_checker is not None:
                loudness_result = loudness_checker(receiver_capture.receiver_output_path)
                active_loudness_status = loudness_result[0]
                active_loudness_target_lufs = loudness_result[1]
                if len(loudness_result) >= 4:
                    active_loudness_measured_lufs = loudness_result[2]
                    active_loudness_operator_action = loudness_result[3]
            if caption_decode_back_checker is not None:
                (
                    active_caption_decode_back_status,
                    active_caption_decode_back_proof,
                ) = caption_decode_back_checker(receiver_capture.receiver_output_path)
        else:
            analyzer_report = _receiver_failure_report(
                expected_timeline=media_set.expected_timeline,
                blocker=receiver_capture.blocker or "VIRTUAL_HEADEND_RECEIVER_FAILED",
            )
        proof_report = build_virtual_headend_proof_report(
            analyzer_report=analyzer_report,
            expected_timeline=media_set.expected_timeline,
            impairment_profile=impairment_profile,
            ffmpeg_version=ffmpeg_version,
            libsrt_version=libsrt_version,
            git_commit=git_commit,
            git_ref=git_ref,
            loudness_status=active_loudness_status,
            loudness_target_lufs=active_loudness_target_lufs,
            loudness_measured_lufs=active_loudness_measured_lufs,
            loudness_operator_action=active_loudness_operator_action,
            caption_decode_back_status=active_caption_decode_back_status,
            caption_decode_back_proof=active_caption_decode_back_proof,
            daemon_restart_recovery_seconds=recovery_evidence.daemon_restart_recovery_seconds,
            ffmpeg_child_restart_recovery_seconds=(
                recovery_evidence.ffmpeg_child_restart_recovery_seconds
            ),
        )
        write_virtual_headend_proof_report(
            output_path=proof_report_path,
            proof_report=proof_report,
        )
    finally:
        if netem_interface is not None:
            impairment_cleanup_result = netem_cleaner(interface=netem_interface)
    if proof_report is None or receiver_capture is None:
        raise RuntimeError("virtual-headend scenario did not produce a proof report")
    return VirtualHeadendScenarioRunResult(
        proof_report=proof_report,
        proof_report_path=proof_report_path,
        receiver_capture=receiver_capture,
        media_set=media_set,
        lifecycle_events=lifecycle_events,
        impairment_apply_results=impairment_apply_results,
        impairment_cleanup_result=impairment_cleanup_result,
    )


def build_virtual_headend_proof_report(
    *,
    analyzer_report: VirtualHeadendReport,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    impairment_profile: NetemProfile,
    ffmpeg_version: str,
    libsrt_version: str,
    git_commit: str = "unknown",
    git_ref: str = "unknown",
    loudness_status: str = "not-verified",
    loudness_target_lufs: float = -16.0,
    loudness_measured_lufs: float | None = None,
    loudness_operator_action: str | None = None,
    caption_decode_back_status: str = "not-verified",
    caption_decode_back_proof: dict[str, object] | None = None,
    daemon_restart_recovery_seconds: float | None = None,
    ffmpeg_child_restart_recovery_seconds: float | None = None,
) -> VirtualHeadendProofReport:
    """Build the JSON-ready report for one scenario run."""

    findings = analyzer_report.findings
    status: ScenarioStatus
    if analyzer_report.status == "FAIL":
        status = "FAIL"
    elif (
        daemon_restart_recovery_seconds is None
        or ffmpeg_child_restart_recovery_seconds is None
        or loudness_status not in {"ok", "pass"}
        or caption_decode_back_status not in {"ok", "pass"}
    ):
        status = "PARTIAL"
    else:
        status = "PASS"
    return VirtualHeadendProofReport(
        status=status,
        boundary_count=analyzer_report.boundary_count,
        impairment_profile=_profile_dict(impairment_profile),
        connection_drop_count=_count(findings, "CONNECTION_DROP_OR_DEAD_AIR"),
        timestamp_discontinuity_count=_count(findings, "OUTPUT_PTS_DISCONTINUITY"),
        black_frame_intervals=_intervals(findings, "UNEXPECTED_BLACK_VIDEO"),
        silence_intervals=_intervals(findings, "UNEXPECTED_AUDIO_SILENCE"),
        loudness_status=loudness_status,
        loudness_target_lufs=loudness_target_lufs,
        loudness_measured_lufs=loudness_measured_lufs,
        loudness_operator_action=loudness_operator_action,
        caption_decode_back_status=caption_decode_back_status,
        daemon_restart_recovery_seconds=daemon_restart_recovery_seconds,
        ffmpeg_child_restart_recovery_seconds=ffmpeg_child_restart_recovery_seconds,
        caption_decode_back_proof=caption_decode_back_proof,
        per_boundary_marker_match=_boundary_results(expected_timeline, findings),
        ffmpeg_version=ffmpeg_version,
        libsrt_version=libsrt_version,
        findings=findings,
        git_commit=git_commit,
        git_ref=git_ref,
    )


def write_virtual_headend_proof_report(
    *,
    output_path: Path,
    proof_report: VirtualHeadendProofReport,
) -> None:
    """Persist a JSON proof report artifact."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(proof_report.to_json() + "\n", encoding="utf-8")


def _count(findings: tuple[VirtualHeadendFinding, ...], code: str) -> int:
    return sum(1 for finding in findings if finding.code == code)


def _intervals(
    findings: tuple[VirtualHeadendFinding, ...],
    code: str,
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "pts_seconds": finding.pts_seconds,
            "expected_source_label": finding.expected_source_label,
            "observed_marker": finding.observed_marker,
            "expected": False,
        }
        for finding in findings
        if finding.code == code
    )


def _boundary_results(
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    findings: tuple[VirtualHeadendFinding, ...],
) -> tuple[BoundaryMarkerResult, ...]:
    marker_mismatches = {
        finding.expected_source_label: finding.observed_marker
        for finding in findings
        if finding.code == "MARKER_MISMATCH"
    }
    results: list[BoundaryMarkerResult] = []
    for index, window in enumerate(expected_timeline[1:], start=1):
        observed = marker_mismatches.get(window.source_label, window.marker)
        results.append(
            BoundaryMarkerResult(
                index=index,
                expected_start_seconds=window.start_seconds,
                expected_marker=window.marker,
                observed_marker=observed,
                matched=observed == window.marker,
            )
        )
    return tuple(results)


def _profile_dict(profile: NetemProfile) -> dict[str, object]:
    return {
        "name": profile.name,
        "delay_ms": profile.delay_ms,
        "jitter_ms": profile.jitter_ms,
        "loss_percent": profile.loss_percent,
        "reorder_percent": profile.reorder_percent,
    }


def _timeline_duration(expected_timeline: tuple[ExpectedOnAirWindow, ...]) -> float | None:
    if not expected_timeline:
        return None
    return max(window.end_seconds for window in expected_timeline)


def _receiver_failure_report(
    *,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    blocker: str,
) -> VirtualHeadendReport:
    expected = expected_timeline[0] if expected_timeline else None
    return VirtualHeadendReport(
        status="FAIL",
        boundary_count=max(0, len(expected_timeline) - 1),
        findings=(
            VirtualHeadendFinding(
                code="CONNECTION_DROP_OR_DEAD_AIR",
                pts_seconds=expected.start_seconds if expected else None,
                detail=blocker,
                expected_source_label=expected.source_label if expected else None,
            ),
        ),
    )
