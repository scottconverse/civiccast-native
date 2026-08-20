# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import json
from pathlib import Path

from civiccast.egress.models import (
    CanonicalProfile,
    EgressSourcePlan,
    EgressSourceSegment,
)
from tests.egress.virtual_headend_gate import (
    ExpectedOnAirWindow,
    VirtualHeadendFinding,
    VirtualHeadendReport,
)
from tests.egress.virtual_headend_impairment import CommandResult, NetemProfile
from tests.egress.virtual_headend_media import (
    GeneratedTestMediaSet,
    VirtualHeadendMediaSpec,
)
from tests.egress.virtual_headend_receiver import ReceiverCaptureResult
from tests.egress.virtual_headend_scenario import (
    ScenarioRecoveryEvidence,
    build_virtual_headend_lifecycle_events,
    build_virtual_headend_proof_report,
    run_virtual_headend_scenario,
    write_virtual_headend_proof_report,
)


def _timeline() -> tuple[ExpectedOnAirWindow, ...]:
    return (
        ExpectedOnAirWindow(
            start_seconds=0,
            end_seconds=2,
            source_label="Program 001",
            marker="SEGMENT 001",
        ),
        ExpectedOnAirWindow(
            start_seconds=2,
            end_seconds=4,
            source_label="Program 002",
            marker="SEGMENT 002",
        ),
        ExpectedOnAirWindow(
            start_seconds=4,
            end_seconds=6,
            source_label="Fallback slate",
            marker="SLATE",
            allow_freeze=True,
            allow_silence=True,
        ),
    )


def test_build_virtual_headend_proof_report_passes_with_full_recovery_evidence() -> None:
    report = build_virtual_headend_proof_report(
        analyzer_report=VirtualHeadendReport(status="PASS", boundary_count=2, findings=()),
        expected_timeline=_timeline(),
        impairment_profile=NetemProfile(name="loss", loss_percent=2.0),
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        git_commit="abc1234",
        git_ref="work/egress-e2-virtual-headend-gate",
        loudness_status="ok",
        loudness_measured_lufs=-16.1,
        loudness_operator_action="Loudness is within tolerance.",
        caption_decode_back_status="pass",
        daemon_restart_recovery_seconds=3.2,
        ffmpeg_child_restart_recovery_seconds=1.1,
    )

    assert report.status == "PASS"
    assert report.boundary_count == 2
    assert report.impairment_profile["name"] == "loss"
    assert report.connection_drop_count == 0
    assert report.timestamp_discontinuity_count == 0
    assert report.loudness_measured_lufs == -16.1
    assert report.loudness_operator_action == "Loudness is within tolerance."
    assert report.git_commit == "abc1234"
    assert report.git_ref == "work/egress-e2-virtual-headend-gate"
    assert [item.matched for item in report.per_boundary_marker_match] == [True, True]
    assert "real cable headend" in report.not_claimed[0]


def test_build_virtual_headend_proof_report_is_partial_without_recovery_evidence() -> None:
    report = build_virtual_headend_proof_report(
        analyzer_report=VirtualHeadendReport(status="PASS", boundary_count=2, findings=()),
        expected_timeline=_timeline(),
        impairment_profile=NetemProfile(name="clean"),
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        loudness_status="not-verified",
    )

    assert report.status == "PARTIAL"
    assert report.daemon_restart_recovery_seconds is None
    assert report.ffmpeg_child_restart_recovery_seconds is None


def test_build_virtual_headend_proof_report_fails_and_counts_findings() -> None:
    report = build_virtual_headend_proof_report(
        analyzer_report=VirtualHeadendReport(
            status="FAIL",
            boundary_count=2,
            findings=(
                VirtualHeadendFinding(
                    code="CONNECTION_DROP_OR_DEAD_AIR",
                    pts_seconds=3.0,
                    detail="gap",
                    expected_source_label="Program 002",
                    observed_marker="SEGMENT 002",
                ),
                VirtualHeadendFinding(
                    code="OUTPUT_PTS_DISCONTINUITY",
                    pts_seconds=2.0,
                    detail="reset",
                ),
                VirtualHeadendFinding(
                    code="UNEXPECTED_BLACK_VIDEO",
                    pts_seconds=1.0,
                    detail="black",
                    expected_source_label="Program 001",
                    observed_marker="SEGMENT 001",
                ),
                VirtualHeadendFinding(
                    code="UNEXPECTED_AUDIO_SILENCE",
                    pts_seconds=1.5,
                    detail="silence",
                    expected_source_label="Program 001",
                    observed_marker="SEGMENT 001",
                ),
                VirtualHeadendFinding(
                    code="MARKER_MISMATCH",
                    pts_seconds=2.1,
                    detail="wrong marker",
                    expected_source_label="Program 002",
                    observed_marker="SEGMENT 999",
                ),
            ),
        ),
        expected_timeline=_timeline(),
        impairment_profile=NetemProfile(name="bad-link", delay_ms=120, jitter_ms=35),
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
    )

    assert report.status == "FAIL"
    assert report.connection_drop_count == 1
    assert report.timestamp_discontinuity_count == 1
    assert report.black_frame_intervals[0]["expected"] is False
    assert report.silence_intervals[0]["expected_source_label"] == "Program 001"
    assert report.per_boundary_marker_match[0].matched is False
    assert report.per_boundary_marker_match[0].observed_marker == "SEGMENT 999"


def test_write_virtual_headend_proof_report_writes_json(tmp_path: Path) -> None:
    output_path = tmp_path / "proof.json"
    report = build_virtual_headend_proof_report(
        analyzer_report=VirtualHeadendReport(status="PASS", boundary_count=1, findings=()),
        expected_timeline=_timeline(),
        impairment_profile=NetemProfile(name="clean"),
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
    )

    write_virtual_headend_proof_report(output_path=output_path, proof_report=report)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["status"] == "PARTIAL"
    assert data["not_claimed"][0] == "This proof does not validate a real cable headend."


def test_build_virtual_headend_lifecycle_events_includes_required_e2_steps() -> None:
    events = build_virtual_headend_lifecycle_events(boundary_count=3)

    assert events[0].name == "start-daemon"
    assert [event.boundary_index for event in events if event.name == "program-boundary"] == [
        1,
        2,
        3,
    ]
    assert [event.name for event in events[-10:]] == [
        "remove-scheduled-asset",
        "restore-scheduled-asset",
        "live-takeover",
        "live-handback",
        "raise-cg-emergency",
        "clear-cg-emergency",
        "kill-ffmpeg-child",
        "kill-daemon-process",
        "reload",
        "drain-stop",
    ]


def test_run_virtual_headend_scenario_orchestrates_components_and_writes_report(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def media_generator(
        *,
        channel_id: str,
        output_dir: Path,
        profile: CanonicalProfile,
        specs: tuple[VirtualHeadendMediaSpec, ...],
    ) -> GeneratedTestMediaSet:
        calls.append(f"media:{channel_id}:{len(specs)}:{profile.width}")
        return _media_set(output_dir)

    def lifecycle_driver(
        *,
        events: tuple[object, ...],
        media_set: GeneratedTestMediaSet,
    ) -> ScenarioRecoveryEvidence:
        calls.append(f"lifecycle:{len(events)}:{len(media_set.expected_timeline)}")
        return ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=2.0,
            ffmpeg_child_restart_recovery_seconds=0.8,
        )

    def receiver_capture_runner(
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ) -> ReceiverCaptureResult:
        calls.append(f"receiver:{input_url}:{duration_seconds}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("received", encoding="utf-8")
        return ReceiverCaptureResult(
            status="PASS",
            receiver_output_path=output_path,
            ffmpeg_returncode=0,
            blocker=None,
            ffmpeg_args=("-i", input_url),
        )

    def artifact_analyzer(
        *,
        received_path: Path,
        expected_timeline: tuple[ExpectedOnAirWindow, ...],
    ) -> VirtualHeadendReport:
        calls.append(f"analyze:{received_path.name}:{len(expected_timeline)}")
        return VirtualHeadendReport(status="PASS", boundary_count=1, findings=())

    def netem_applier(*, interface: str, profile: NetemProfile) -> tuple[CommandResult, ...]:
        calls.append(f"netem-apply:{interface}:{profile.name}")
        return (CommandResult(returncode=0, stdout="applied"),)

    def netem_cleaner(*, interface: str) -> CommandResult:
        calls.append(f"netem-clean:{interface}")
        return CommandResult(returncode=0, stdout="clean")

    result = run_virtual_headend_scenario(
        channel_id="gov",
        work_dir=tmp_path,
        profile=CanonicalProfile(width=640, height=360),
        receiver_input_url="srt://127.0.0.1:19000?mode=listener",
        impairment_profile=NetemProfile(name="loss", loss_percent=2.0),
        netem_interface="veth-headend",
        proof_report_path=tmp_path / "proof" / "report.json",
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        lifecycle_driver=lifecycle_driver,
        artifact_analyzer=artifact_analyzer,
        boundary_count=1,
        media_generator=media_generator,
        receiver_capture_runner=receiver_capture_runner,
        netem_applier=netem_applier,
        netem_cleaner=netem_cleaner,
        loudness_status="ok",
        caption_decode_back_status="pass",
    )

    assert result.proof_report.status == "PASS"
    assert result.impairment_apply_results[0].stdout == "applied"
    assert result.impairment_cleanup_result is not None
    assert result.proof_report_path.exists()
    assert json.loads(result.proof_report_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert calls == [
        "media:gov:5:640",
        "netem-apply:veth-headend:loss",
        "lifecycle:12:2",
        "receiver:srt://127.0.0.1:19000?mode=listener:4.0",
        "analyze:gov-loss.ts:2",
        "netem-clean:veth-headend",
    ]


def test_run_virtual_headend_scenario_uses_loudness_checker_result(tmp_path: Path) -> None:
    def receiver_capture_runner(
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ) -> ReceiverCaptureResult:
        _ = (input_url, duration_seconds)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("received", encoding="utf-8")
        return ReceiverCaptureResult(
            status="PASS",
            receiver_output_path=output_path,
            ffmpeg_returncode=0,
            blocker=None,
            ffmpeg_args=("-i", "file.ts"),
        )

    result = run_virtual_headend_scenario(
        channel_id="gov",
        work_dir=tmp_path,
        profile=CanonicalProfile(width=640, height=360),
        receiver_input_url="file.ts",
        impairment_profile=NetemProfile(name="clean"),
        netem_interface=None,
        proof_report_path=tmp_path / "proof" / "report.json",
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        lifecycle_driver=lambda events, media_set: ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=1.0,
            ffmpeg_child_restart_recovery_seconds=1.0,
        ),
        artifact_analyzer=lambda received_path, expected_timeline: VirtualHeadendReport(
            status="PASS",
            boundary_count=1,
            findings=(),
        ),
        boundary_count=1,
        media_generator=lambda channel_id, output_dir, profile, specs: _media_set(output_dir),
        receiver_capture_runner=receiver_capture_runner,
        loudness_checker=lambda _path: ("ok", -24.0),
        caption_decode_back_status="pass",
    )

    assert result.proof_report.status == "PASS"
    assert result.proof_report.loudness_status == "ok"
    assert result.proof_report.loudness_target_lufs == -24.0


def test_run_virtual_headend_scenario_uses_caption_decode_back_checker(
    tmp_path: Path,
) -> None:
    def receiver_capture_runner(
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ) -> ReceiverCaptureResult:
        _ = (input_url, duration_seconds)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("received", encoding="utf-8")
        return ReceiverCaptureResult(
            status="PASS",
            receiver_output_path=output_path,
            ffmpeg_returncode=0,
            blocker=None,
            ffmpeg_args=("-i", "file.ts"),
        )

    result = run_virtual_headend_scenario(
        channel_id="gov",
        work_dir=tmp_path,
        profile=CanonicalProfile(width=640, height=360),
        receiver_input_url="file.ts",
        impairment_profile=NetemProfile(name="clean"),
        netem_interface=None,
        proof_report_path=tmp_path / "proof" / "report.json",
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        lifecycle_driver=lambda events, media_set: ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=1.0,
            ffmpeg_child_restart_recovery_seconds=1.0,
        ),
        artifact_analyzer=lambda received_path, expected_timeline: VirtualHeadendReport(
            status="PASS",
            boundary_count=1,
            findings=(),
        ),
        boundary_count=1,
        media_generator=lambda channel_id, output_dir, profile, specs: _media_set(output_dir),
        receiver_capture_runner=receiver_capture_runner,
        loudness_status="ok",
        caption_decode_back_checker=lambda _path: (
            "pass",
            {"status": "PASS", "caption_status": "on"},
        ),
    )

    assert result.proof_report.status == "PASS"
    assert result.proof_report.caption_decode_back_status == "pass"
    assert result.proof_report.caption_decode_back_proof == {
        "status": "PASS",
        "caption_status": "on",
    }


def test_run_virtual_headend_scenario_fails_closed_when_receiver_capture_fails(
    tmp_path: Path,
) -> None:
    analyzer_called = False

    def receiver_capture_runner(
        *,
        input_url: str,
        output_path: Path,
        duration_seconds: float | None,
    ) -> ReceiverCaptureResult:
        return ReceiverCaptureResult(
            status="FAIL",
            receiver_output_path=output_path,
            ffmpeg_returncode=1,
            blocker="VIRTUAL_HEADEND_RECEIVER_FFMPEG_FAILED",
            ffmpeg_args=("-i", input_url),
        )

    def artifact_analyzer(
        *,
        received_path: Path,
        expected_timeline: tuple[ExpectedOnAirWindow, ...],
    ) -> VirtualHeadendReport:
        nonlocal analyzer_called
        analyzer_called = True
        return VirtualHeadendReport(status="PASS", boundary_count=1, findings=())

    result = run_virtual_headend_scenario(
        channel_id="gov",
        work_dir=tmp_path,
        profile=CanonicalProfile(),
        receiver_input_url="srt://127.0.0.1:19000?mode=listener",
        impairment_profile=NetemProfile(name="clean"),
        netem_interface=None,
        proof_report_path=tmp_path / "proof.json",
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        lifecycle_driver=lambda events, media_set: ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=1.0,
            ffmpeg_child_restart_recovery_seconds=1.0,
        ),
        artifact_analyzer=artifact_analyzer,
        boundary_count=1,
        media_generator=_fake_media_generator,
        receiver_capture_runner=receiver_capture_runner,
        loudness_status="ok",
    )

    assert analyzer_called is False
    assert result.proof_report.status == "FAIL"
    assert result.proof_report.connection_drop_count == 1
    assert result.proof_report.findings[0].detail == "VIRTUAL_HEADEND_RECEIVER_FFMPEG_FAILED"


def _fake_media_generator(
    *,
    channel_id: str,
    output_dir: Path,
    profile: CanonicalProfile,
    specs: tuple[VirtualHeadendMediaSpec, ...],
) -> GeneratedTestMediaSet:
    return _media_set(output_dir, channel_id=channel_id)


def _media_set(output_dir: Path, *, channel_id: str = "gov") -> GeneratedTestMediaSet:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = (output_dir / "program-001.ts", output_dir / "program-002.ts")
    for path in paths:
        path.write_text("media", encoding="utf-8")
    timeline = (
        ExpectedOnAirWindow(
            start_seconds=0.0,
            end_seconds=2.0,
            source_label="Program 001",
            marker="SEGMENT 001",
        ),
        ExpectedOnAirWindow(
            start_seconds=2.0,
            end_seconds=4.0,
            source_label="Program 002",
            marker="SEGMENT 002",
        ),
    )
    return GeneratedTestMediaSet(
        source_plan=EgressSourcePlan(
            channel_id=channel_id,
            segments=(
                EgressSourceSegment(label="Program 001", path=str(paths[0]), duration_seconds=2.0),
                EgressSourceSegment(label="Program 002", path=str(paths[1]), duration_seconds=2.0),
            ),
        ),
        expected_timeline=timeline,
        output_paths=paths,
        ffmpeg_args=(("-i", "program-001"), ("-i", "program-002")),
    )
