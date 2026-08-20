# Copyright (c) The CivicCast Authors

from __future__ import annotations

import argparse
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.egress.models import EgressSourcePlan, EgressSourceSegment
from tests.egress.virtual_headend_scenario import build_virtual_headend_lifecycle_events

runner = importlib.import_module("scripts.run_egress_virtual_headend_proof")


def test_negative_control_self_test_proves_analyzer_can_fail() -> None:
    evidence = runner.run_negative_control_self_test()

    assert len(evidence) == 5
    assert {control.status for control in evidence} == {"PASS"}
    assert "OUTPUT_PTS_DISCONTINUITY" in {control.expected_code for control in evidence}


def test_runner_fails_closed_when_required_prerequisite_is_missing(tmp_path: Path) -> None:
    args = argparse.Namespace(
        work_dir=tmp_path,
        proof_report_path=tmp_path / "proof.json",
        channel_id="gov",
        receiver_input_url="generated:first",
        srt_loopback_port=19001,
        srt_loopback_startup_seconds=0.1,
        netem_interface="veth-headend",
        impairment_profile="clean",
        boundary_count=1,
        ffmpeg="definitely-missing-ffmpeg",
        ffprobe="definitely-missing-ffprobe",
        tc="definitely-missing-tc",
        impairment_matrix=False,
        verify_loudness=False,
        loudness_target_lufs=-16.0,
        loudness_tolerance_lufs=2.0,
        verify_caption_decode_back=False,
        self_test_only=False,
        process_restart_probe=False,
        ffmpeg_child_restart_probe=False,
        exit_mode="pass-only",
    )

    evidence = runner.run_proof_from_args(args)

    assert evidence.status == "FAIL"
    assert evidence.blocker == "MISSING_PREREQUISITE_FFMPEG"
    assert evidence.proof_report is None


def test_self_test_only_passes_without_optional_tc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "collect_prerequisites",
        lambda **_kwargs: (
            runner.PrerequisiteEvidence(
                name="ffmpeg",
                executable="ffmpeg",
                status="PASS",
                detail="found",
            ),
            runner.PrerequisiteEvidence(
                name="ffprobe",
                executable="ffprobe",
                status="PASS",
                detail="found",
            ),
            runner.PrerequisiteEvidence(
                name="tc",
                executable=None,
                status="PASS",
                detail="not required for this run",
            ),
        ),
    )
    args = argparse.Namespace(
        work_dir=tmp_path,
        proof_report_path=tmp_path / "proof.json",
        channel_id="gov",
        receiver_input_url="generated:first",
        srt_loopback_port=19001,
        srt_loopback_startup_seconds=0.1,
        netem_interface=None,
        impairment_profile="clean",
        boundary_count=1,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        tc="tc",
        impairment_matrix=False,
        verify_loudness=False,
        loudness_target_lufs=-16.0,
        loudness_tolerance_lufs=2.0,
        verify_caption_decode_back=False,
        self_test_only=True,
        process_restart_probe=False,
        ffmpeg_child_restart_probe=False,
        exit_mode="pass-only",
    )

    evidence = runner.run_proof_from_args(args)

    assert evidence.status == "PASS"
    assert evidence.blocker is None
    assert evidence.proof_report is None


def test_impairment_matrix_requires_netem_interface(tmp_path: Path) -> None:
    args = argparse.Namespace(
        work_dir=tmp_path,
        proof_report_path=tmp_path / "proof.json",
        channel_id="gov",
        receiver_input_url="generated:first",
        srt_loopback_port=19001,
        srt_loopback_startup_seconds=0.1,
        netem_interface=None,
        impairment_profile="clean",
        impairment_matrix=True,
        boundary_count=1,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        tc="tc",
        verify_loudness=False,
        loudness_target_lufs=-16.0,
        loudness_tolerance_lufs=2.0,
        verify_caption_decode_back=False,
        self_test_only=False,
        process_restart_probe=False,
        ffmpeg_child_restart_probe=False,
        exit_mode="pass-only",
    )

    evidence = runner.run_proof_from_args(args)

    assert evidence.status == "FAIL"
    assert evidence.blocker == "MISSING_NETEM_INTERFACE_FOR_IMPAIRMENT_MATRIX"
    assert evidence.matrix_reports == ()


def test_impairment_matrix_runs_every_required_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles_seen: list[str] = []

    monkeypatch.setattr(
        runner,
        "collect_prerequisites",
        lambda **_kwargs: (
            runner.PrerequisiteEvidence(
                name="ffmpeg",
                executable="ffmpeg",
                status="PASS",
                detail="found",
            ),
            runner.PrerequisiteEvidence(
                name="ffprobe",
                executable="ffprobe",
                status="PASS",
                detail="found",
            ),
            runner.PrerequisiteEvidence(
                name="tc",
                executable="tc",
                status="PASS",
                detail="found",
            ),
        ),
    )

    def fake_run_one_profile(**kwargs):
        profile = kwargs["profile"]
        profiles_seen.append(profile.name)
        return SimpleNamespace(
            proof_report=_passing_proof_report(profile.name),
            proof_report_path=tmp_path / profile.name / "proof.json",
        )

    monkeypatch.setattr(runner, "_run_one_profile", fake_run_one_profile)
    args = argparse.Namespace(
        work_dir=tmp_path,
        proof_report_path=tmp_path / "proof.json",
        channel_id="gov",
        receiver_input_url="generated:first",
        srt_loopback_port=19001,
        srt_loopback_startup_seconds=0.1,
        netem_interface="veth-headend",
        impairment_profile="clean",
        impairment_matrix=True,
        boundary_count=1,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        tc="tc",
        verify_loudness=False,
        loudness_target_lufs=-16.0,
        loudness_tolerance_lufs=2.0,
        verify_caption_decode_back=False,
        self_test_only=False,
        process_restart_probe=False,
        ffmpeg_child_restart_probe=False,
        exit_mode="pass-only",
    )

    evidence = runner.run_proof_from_args(args)

    assert evidence.status == "PASS"
    assert evidence.blocker is None
    assert profiles_seen == ["clean", "delay-jitter", "loss", "loss-reorder", "bad-link"]
    assert len(evidence.matrix_reports) == 5
    assert evidence.proof_report["profile_count"] == 5
    assert evidence.proof_report["passed_profiles"] == profiles_seen


def test_metadata_lifecycle_driver_can_use_process_restart_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProbe:
        def __call__(self) -> float:
            return 0.25

    monkeypatch.setattr(runner, "ProcessRestartProbe", lambda: FakeProbe())

    evidence = runner._metadata_only_lifecycle_driver(
        process_restart_probe=True,
        ffmpeg_child_restart_probe=True,
    )(
        events=(),
        media_set=object(),
    )

    assert evidence.daemon_restart_recovery_seconds == 0.25
    assert evidence.ffmpeg_child_restart_recovery_seconds == 0.25


def test_playout_supervisor_lifecycle_driver_exercises_real_supervisor(
    tmp_path: Path,
) -> None:
    args = argparse.Namespace(
        channel_id="gov",
        boundary_count=1,
        process_restart_probe=False,
        ffmpeg_child_restart_probe=True,
    )
    driver = runner._playout_supervisor_lifecycle_driver(args=args, work_dir=tmp_path)

    evidence = driver(
        events=build_virtual_headend_lifecycle_events(boundary_count=1),
        media_set=_runner_lifecycle_media_set(tmp_path),
    )

    assert evidence.daemon_restart_recovery_seconds == 0.0
    assert evidence.ffmpeg_child_restart_recovery_seconds is not None
    assert evidence.ffmpeg_child_restart_recovery_seconds >= 0.0


def test_expected_caption_vtt_is_built_from_generated_timeline(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media = runner.GeneratedTestMediaSet(
        source_plan=EgressSourcePlan(
            channel_id="gov",
            segments=(
                EgressSourceSegment(
                    label="Program 001",
                    path=str(media_dir / "program.ts"),
                    duration_seconds=2.0,
                ),
            ),
        ),
        expected_timeline=(
            runner.ExpectedOnAirWindow(
                start_seconds=0.0,
                end_seconds=2.0,
                source_label="Program 001",
                marker="SEGMENT 001",
            ),
        ),
        output_paths=(media_dir / "program.ts",),
        ffmpeg_args=(),
    )

    cues = runner._write_expected_caption_vtt(
        output_path=tmp_path / "captions" / "expected.vtt",
        media_holder=[media],
    )

    assert cues[0].text == "CivicCast caption proof SEGMENT 001."
    assert cues[0].start_seconds == 0.2


def test_generated_sequence_media_specs_cover_requested_boundaries() -> None:
    specs = runner._media_specs_for_runner("generated:sequence", 3)

    assert [spec.marker for spec in specs[:4]] == [
        "SEGMENT 001",
        "SEGMENT 002",
        "SEGMENT 003",
        "SEGMENT 004",
    ]


def test_generated_first_media_specs_are_long_enough_for_loudness_smoke() -> None:
    specs = runner._media_specs_for_runner("generated:first", 1)

    assert [spec.marker for spec in specs[:4]] == [
        "SEGMENT 001",
        "SEGMENT 002",
        "SEGMENT 003",
        "SEGMENT 004",
    ]
    assert {spec.marker for spec in specs} >= {"SLATE", "LIVE SOURCE", "EMERGENCY OVERLAY"}


def test_generated_sequence_provider_builds_receiver_input_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, Path]] = []

    def fake_sequence_artifact(
        *,
        ffmpeg: str,
        concat_plan_path: Path,
        sequence_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert ffmpeg == "ffmpeg"
        sequence_path.parent.mkdir(parents=True, exist_ok=True)
        sequence_path.write_bytes(b"sequence")
        calls.append((concat_plan_path, sequence_path))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_generated_sequence_artifact", fake_sequence_artifact)
    media_dir = tmp_path / "media"
    media = runner.GeneratedTestMediaSet(
        source_plan=EgressSourcePlan(
            channel_id="gov",
            segments=(
                EgressSourceSegment(
                    label="Program 001",
                    path=str(media_dir / "program-001.ts"),
                    duration_seconds=2.0,
                ),
                EgressSourceSegment(
                    label="Program 002",
                    path=str(media_dir / "program-002.ts"),
                    duration_seconds=2.0,
                ),
            ),
        ),
        expected_timeline=(
            runner.ExpectedOnAirWindow(
                start_seconds=0.0,
                end_seconds=2.0,
                source_label="Program 001",
                marker="SEGMENT 001",
            ),
            runner.ExpectedOnAirWindow(
                start_seconds=2.0,
                end_seconds=4.0,
                source_label="Program 002",
                marker="SEGMENT 002",
            ),
        ),
        output_paths=(media_dir / "program-001.ts", media_dir / "program-002.ts"),
        ffmpeg_args=(),
    )
    holder: list[runner.GeneratedTestMediaSet] = []

    provider = runner._generated_sequence_media_url(
        work_dir=tmp_path,
        ffmpeg="ffmpeg",
        media_holder=holder,
    )
    input_url = provider(media)

    assert input_url == str(tmp_path / "receiver-input" / "generated-sequence.ts")
    assert calls == [
        (
            tmp_path / "receiver-input" / "generated-sequence.ffconcat",
            tmp_path / "receiver-input" / "generated-sequence.ts",
        )
    ]
    assert holder == [media]
    assert "program-001.ts" in calls[0][0].read_text(encoding="utf-8")


def test_generated_sequence_srt_provider_records_sender_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_sequence_artifact(
        *,
        ffmpeg: str,
        concat_plan_path: Path,
        sequence_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        _ = (ffmpeg, concat_plan_path)
        sequence_path.parent.mkdir(parents=True, exist_ok=True)
        sequence_path.write_bytes(b"sequence")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_generated_sequence_artifact", fake_sequence_artifact)
    media_dir = tmp_path / "media"
    media = runner.GeneratedTestMediaSet(
        source_plan=EgressSourcePlan(
            channel_id="gov",
            segments=(
                EgressSourceSegment(
                    label="Program 001",
                    path=str(media_dir / "program-001.ts"),
                    duration_seconds=2.0,
                ),
            ),
        ),
        expected_timeline=(
            runner.ExpectedOnAirWindow(
                start_seconds=0.0,
                end_seconds=2.0,
                source_label="Program 001",
                marker="SEGMENT 001",
            ),
        ),
        output_paths=(media_dir / "program-001.ts",),
        ffmpeg_args=(),
    )
    media_holder: list[runner.GeneratedTestMediaSet] = []
    sequence_holder: list[Path] = []

    provider = runner._generated_sequence_srt_media_url(
        work_dir=tmp_path,
        ffmpeg="ffmpeg",
        port=19101,
        media_holder=media_holder,
        sequence_holder=sequence_holder,
    )

    assert provider(media) == "srt://127.0.0.1:19101?mode=listener&latency=200000"
    assert sequence_holder == [tmp_path / "receiver-input" / "generated-sequence.ts"]
    assert media_holder == [media]


def test_proof_runner_passes_tested_git_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def fake_run_scenario(**kwargs):
        seen["git_commit"] = kwargs["git_commit"]
        seen["git_ref"] = kwargs["git_ref"]
        return SimpleNamespace(
            proof_report=_passing_proof_report("clean"),
            proof_report_path=tmp_path / "proof.json",
        )

    monkeypatch.setattr(runner, "run_virtual_headend_scenario", fake_run_scenario)
    runner._run_one_profile(
        args=argparse.Namespace(
            channel_id="gov",
            receiver_input_url="generated:first",
            netem_interface=None,
            boundary_count=1,
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            tc="tc",
            tested_commit="abc1234",
            tested_ref="work/test",
            verify_loudness=False,
            loudness_target_lufs=-16.0,
            verify_caption_decode_back=False,
            process_restart_probe=False,
            ffmpeg_child_restart_probe=False,
            srt_loopback_port=19001,
            srt_loopback_startup_seconds=0.1,
        ),
        work_dir=tmp_path,
        proof_report_path=tmp_path / "proof.json",
        profile=runner.NetemProfile(name="clean"),
        media_holder=[],
        sequence_holder=[],
    )

    assert seen == {"git_commit": "abc1234", "git_ref": "work/test"}


def test_git_ref_value_falls_back_to_remote_work_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        ("branch", "--show-current"): "unknown",
        (
            "branch",
            "--remotes",
            "--contains",
            "HEAD",
            "--format",
            "%(refname:short)",
        ): "origin/main\norigin/work/egress-e2-virtual-headend-gate\n",
    }

    monkeypatch.setattr(runner, "_git_value", lambda args: values[args])

    assert runner._git_ref_value() == "work/egress-e2-virtual-headend-gate"


def test_srt_loopback_ffmpeg_args_split_mode_from_urls(tmp_path: Path) -> None:
    receiver_args = runner._srt_loopback_receiver_args(
        ffmpeg="ffmpeg",
        input_url="srt://127.0.0.1:19101?mode=listener&latency=200000",
        output_path=tmp_path / "receiver.ts",
        duration_seconds=4.0,
    )
    sender_args = runner._srt_loopback_sender_args(
        ffmpeg="ffmpeg",
        sender_input_path=tmp_path / "sequence.ts",
        sender_url="srt://127.0.0.1:19101?mode=caller&latency=200000&linger=5",
    )

    assert "-mode" in receiver_args
    assert "listener" in receiver_args
    assert "srt://127.0.0.1:19101?latency=200000" in receiver_args
    assert "-mode" in sender_args
    assert "caller" in sender_args
    assert "-re" in sender_args
    assert sender_args.index("-mode") > sender_args.index("-f")
    assert "srt://127.0.0.1:19101?latency=200000&linger=5" in sender_args


@pytest.mark.parametrize(
    (
        "sender_returncode",
        "receiver_returncode",
        "output_exists",
        "receiver_stderr",
        "expected",
    ),
    [
        (1, 0, True, "", "VIRTUAL_HEADEND_SRT_SENDER_FAILED"),
        (0, 0, False, "", "VIRTUAL_HEADEND_SRT_RECEIVER_OUTPUT_MISSING"),
        (0, 1, True, "receiver error", "VIRTUAL_HEADEND_SRT_RECEIVER_FAILED"),
        (0, 1, True, "", None),
    ],
)
def test_srt_loopback_blocker_allows_intentional_receiver_stop(
    sender_returncode: int,
    receiver_returncode: int,
    output_exists: bool,
    receiver_stderr: str,
    expected: str | None,
) -> None:
    assert (
        runner._srt_loopback_blocker(
            sender_returncode=sender_returncode,
            receiver_returncode=receiver_returncode,
            output_exists=output_exists,
            receiver_stderr=receiver_stderr,
        )
        == expected
    )


def _passing_proof_report(profile_name: str):
    return runner.VirtualHeadendProofReport(
        status="PASS",
        boundary_count=1,
        impairment_profile={"name": profile_name},
        connection_drop_count=0,
        timestamp_discontinuity_count=0,
        black_frame_intervals=(),
        silence_intervals=(),
        loudness_status="ok",
        loudness_target_lufs=-16.0,
        caption_decode_back_status="pass",
        daemon_restart_recovery_seconds=1.0,
        ffmpeg_child_restart_recovery_seconds=1.0,
        caption_decode_back_proof=None,
        per_boundary_marker_match=(),
        ffmpeg_version="ffmpeg",
        libsrt_version="libsrt",
        findings=(),
    )


def _runner_lifecycle_media_set(tmp_path: Path):
    program_001 = tmp_path / "program-001.ts"
    program_002 = tmp_path / "program-002.ts"
    slate = tmp_path / "slate.ts"
    live = tmp_path / "live.ts"
    for path in (program_001, program_002, slate, live):
        path.write_text(path.stem, encoding="utf-8")
    source_plan = EgressSourcePlan(
        channel_id="gov",
        segments=(
            EgressSourceSegment(
                label="Program 001",
                path=str(program_001),
                duration_seconds=1.0,
                kind="program",
            ),
            EgressSourceSegment(
                label="Program 002",
                path=str(program_002),
                duration_seconds=1.0,
                kind="program",
            ),
            EgressSourceSegment(
                label="Fallback slate",
                path=str(slate),
                duration_seconds=1.0,
                kind="slate",
            ),
            EgressSourceSegment(
                label="Live source",
                path=str(live),
                duration_seconds=1.0,
                kind="live",
            ),
        ),
    )
    return runner.GeneratedTestMediaSet(
        source_plan=source_plan,
        expected_timeline=(
            runner.ExpectedOnAirWindow(
                start_seconds=0.0,
                end_seconds=1.0,
                source_label="Program 001",
                marker="SEGMENT 001",
            ),
            runner.ExpectedOnAirWindow(
                start_seconds=1.0,
                end_seconds=2.0,
                source_label="Program 002",
                marker="SEGMENT 002",
            ),
        ),
        output_paths=(program_001, program_002, slate, live),
        ffmpeg_args=(),
    )
