# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

from civiccast.cg.service import build_emergency_overlay, build_overlay_contract
from civiccast.egress.cg_bridge import CG_EGRESS_PROOF_BOUNDARY, build_cg_overlay_egress_proof
from civiccast.egress.models import (
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.supervisor import PlayoutSupervisor
from tests.egress.virtual_headend_gate import ExpectedOnAirWindow, VirtualHeadendReport
from tests.egress.virtual_headend_impairment import NetemProfile
from tests.egress.virtual_headend_lifecycle import (
    EncoderProcessController,
    PlayoutSupervisorLifecycleDriver,
    ProcessRestartProbe,
)
from tests.egress.virtual_headend_media import GeneratedTestMediaSet
from tests.egress.virtual_headend_receiver import ReceiverCaptureResult
from tests.egress.virtual_headend_scenario import (
    build_virtual_headend_lifecycle_events,
    run_virtual_headend_scenario,
)


def test_playout_supervisor_lifecycle_driver_runs_required_e2_events(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    process_controller = EncoderProcessController(first_pid=500)
    schedule_labels = [
        "Program 001",
        "Program 002",
        "Program 003",
        "Program 004",
        "Program 005",
    ]
    clock_value = 0.0

    def clock() -> float:
        nonlocal clock_value
        clock_value += 1.0
        return clock_value

    def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
        return [
            _program_plan(tmp_path, schedule_labels.pop(0), channel_id=channel_id)
            for _index in range(min(window, len(schedule_labels)))
        ]

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        lookahead_source_plan_provider=lookahead_provider,
        lookahead_window=1,
        fallback_source_provider=lambda config: _slate_plan(tmp_path, channel_id=config.channel_id),
        ffmpeg_starter=process_controller.start,
    )
    proof = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )
    driver = PlayoutSupervisorLifecycleDriver(
        channel_id="gov",
        store=store,
        supervisor=supervisor,
        process_controller=process_controller,
        fallback_reason="virtual-headend removed the scheduled asset",
        cg_overlay_proof=proof,
        restart_daemon=lambda: 2.5,
        clock=clock,
    )

    evidence = driver(
        events=build_virtual_headend_lifecycle_events(boundary_count=1),
        media_set=_media_set(tmp_path),
    )

    assert evidence.daemon_restart_recovery_seconds == 2.5
    assert evidence.ffmpeg_child_restart_recovery_seconds == 1.0
    assert len(process_controller.started) >= 6
    final_state = store.read_state("gov")
    assert final_state is not None
    assert final_state.state == "STOPPED"
    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 20)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert [event.source_label for event in overlay_events[:2]] == [
        "CivicCast emergency banner cleared",
        "CivicCast emergency banner",
    ]


def test_process_restart_probe_relaunches_real_child_process() -> None:
    elapsed = ProcessRestartProbe(timeout_seconds=5.0)()

    assert elapsed >= 0.0
    assert elapsed < 5.0


def test_virtual_headend_scenario_runner_uses_playout_lifecycle_driver(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    process_controller = EncoderProcessController(first_pid=800)
    schedule_labels = [
        "Program 001",
        "Program 002",
        "Program 003",
        "Program 004",
        "Program 005",
    ]
    clock_value = 0.0

    def clock() -> float:
        nonlocal clock_value
        clock_value += 1.0
        return clock_value

    def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
        return [
            _program_plan(tmp_path, schedule_labels.pop(0), channel_id=channel_id)
            for _index in range(min(window, len(schedule_labels)))
        ]

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path / "supervisor",
        source_plan_provider=lambda _channel_id: None,
        lookahead_source_plan_provider=lookahead_provider,
        lookahead_window=1,
        fallback_source_provider=lambda config: _slate_plan(tmp_path, channel_id=config.channel_id),
        ffmpeg_starter=process_controller.start,
    )
    lifecycle_driver = PlayoutSupervisorLifecycleDriver(
        channel_id="gov",
        store=store,
        supervisor=supervisor,
        process_controller=process_controller,
        fallback_reason="virtual-headend removed the scheduled asset",
        cg_overlay_proof=build_cg_overlay_egress_proof(
            overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
            overlay_contract=build_overlay_contract(channel_id="gov"),
        ),
        restart_daemon=lambda: 2.0,
        clock=clock,
    )

    result = run_virtual_headend_scenario(
        channel_id="gov",
        work_dir=tmp_path / "scenario",
        profile=_profile(),
        receiver_input_url="srt://127.0.0.1:19000?mode=listener",
        impairment_profile=NetemProfile(name="clean"),
        netem_interface=None,
        proof_report_path=tmp_path / "proof" / "report.json",
        ffmpeg_version="ffmpeg 6.1",
        libsrt_version="libsrt 1.5",
        lifecycle_driver=lifecycle_driver,
        artifact_analyzer=lambda received_path, expected_timeline: VirtualHeadendReport(
            status="PASS",
            boundary_count=max(0, len(expected_timeline) - 1),
            findings=(),
        ),
        boundary_count=1,
        media_generator=lambda channel_id, output_dir, profile, specs: _media_set(tmp_path),
        receiver_capture_runner=_receiver_capture_success,
        loudness_status="ok",
        caption_decode_back_status="pass",
    )

    assert result.proof_report.status == "PASS"
    assert result.proof_report.daemon_restart_recovery_seconds == 2.0
    assert result.proof_report.ffmpeg_child_restart_recovery_seconds == 1.0
    assert result.proof_report_path.exists()
    final_state = store.read_state("gov")
    assert final_state is not None
    assert final_state.state == "STOPPED"


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _profile():
    from civiccast.egress.models import CanonicalProfile

    return CanonicalProfile()


def _program_plan(tmp_path: Path, label: str, *, channel_id: str) -> EgressSourcePlan:
    path = tmp_path / f"{label.lower().replace(' ', '-')}.ts"
    path.write_text(label, encoding="utf-8")
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(path),
                duration_seconds=1.0,
                source_ref=label.lower().replace(" ", "-"),
            )
        ],
    )


def _slate_plan(tmp_path: Path, *, channel_id: str) -> EgressSourcePlan:
    path = tmp_path / "slate.ts"
    path.write_text("slate", encoding="utf-8")
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label="Fallback slate",
                path=str(path),
                duration_seconds=1.0,
                kind="slate",
                source_ref="fallback-slate",
            )
        ],
    )


def _media_set(tmp_path: Path) -> GeneratedTestMediaSet:
    live_path = tmp_path / "live.ts"
    live_path.write_text("live", encoding="utf-8")
    program_path = tmp_path / "program.ts"
    program_path.write_text("program", encoding="utf-8")
    source_plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Program 001",
                path=str(program_path),
                duration_seconds=1.0,
                source_ref="program-001",
            ),
            EgressSourceSegment(
                label="Live source",
                path=str(live_path),
                duration_seconds=1.0,
                kind="live",
                source_ref="live-source",
            ),
        ],
    )
    return GeneratedTestMediaSet(
        source_plan=source_plan,
        expected_timeline=(
            ExpectedOnAirWindow(
                start_seconds=0.0,
                end_seconds=1.0,
                source_label="Program 001",
                marker="SEGMENT 001",
            ),
            ExpectedOnAirWindow(
                start_seconds=1.0,
                end_seconds=2.0,
                source_label="Live source",
                marker="LIVE SOURCE",
            ),
        ),
        output_paths=(program_path, live_path),
        ffmpeg_args=(),
    )


def _receiver_capture_success(
    *,
    input_url: str,
    output_path: Path,
    duration_seconds: float | None,
) -> ReceiverCaptureResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("received", encoding="utf-8")
    return ReceiverCaptureResult(
        status="PASS",
        receiver_output_path=output_path,
        ffmpeg_returncode=0,
        blocker=None,
        ffmpeg_args=("-i", input_url),
    )
