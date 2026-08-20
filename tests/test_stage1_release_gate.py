"""Contracts for the Stage 1 release-gate runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_stage1_release_gate",
    Path(__file__).resolve().parents[1] / "scripts" / "run_stage1_release_gate.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
run_stage1_release_gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = run_stage1_release_gate
_SPEC.loader.exec_module(run_stage1_release_gate)


def _portable_command(command: str) -> str:
    return command.replace("\\", "/")


def test_stage1_gate_plan_runs_full_stack_release_clean_proof_and_report(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    release_dir = repo / "artifacts" / "release" / "v3.3.0-stage1"
    clean_dir = repo / "artifacts" / "clean-windows" / "3.3-stage1-final"
    report_dir = repo / "artifacts" / "stage-reports" / "3.3-stage1-final"

    plan = run_stage1_release_gate.build_plan(
        repo_root=repo,
        version="3.3.0",
        release_out_dir=release_dir,
        clean_evidence_dir=clean_dir,
        stage_report_dir=report_dir,
    )

    commands = [_portable_command(" ".join(step.command)) for step in plan.steps]
    assert commands[:6] == [
        "powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
        "uv run python scripts/policy/check_release_identity.py",
        (
            "uv run python scripts/run_isolated_first_run_attestation.py --artifact-root "
            "artifacts/first-run/3.3-stage1-final --profile-root "
            "artifacts/first-run/3.3-stage1-final/profile"
        ),
        (
            "uv run python scripts/build_release_artifacts.py --version 3.3.0 "
            "--out-dir artifacts/release/v3.3.0-stage1 --all-portable --python "
            "--wheelhouse --windows-installer"
        ),
        (
            "uv run python scripts/run_clean_windows_install_proof.py --execute "
            "--evidence-dir artifacts/clean-windows/3.3-stage1-final "
            "--release-manifest artifacts/release/v3.3.0-stage1/"
            "civiccast-3.3.0-release-artifacts-manifest.json"
        ),
        (
            "uv run python scripts/run_stage1_lifecycle_proof.py --artifact-root "
            "artifacts/stage1-lifecycle/3.3-stage1-final --clean-windows-evidence "
            "artifacts/clean-windows/3.3-stage1-final/clean-windows-install.json "
            "--first-run-evidence artifacts/first-run/3.3-stage1-final/first-run-attestation.json "
            "--release-manifest artifacts/release/v3.3.0-stage1/"
            "civiccast-3.3.0-release-artifacts-manifest.json "
            "--uninstall-evidence artifacts/stage1-lifecycle/3.3-stage1-final/uninstall-proof.json "
            "--reinstall-evidence artifacts/stage1-lifecycle/3.3-stage1-final/reinstall-proof.json "
            "--upgrade-evidence artifacts/stage1-lifecycle/3.3-stage1-final/upgrade-proof.json"
        ),
    ]
    assert commands[6].startswith("powershell -NoProfile -ExecutionPolicy Bypass -Command")
    assert "artifacts/gauntletgate/3.3-stage1-final/00-gate-report.md" in commands[6]
    assert commands[7].startswith(
        "uv run python scripts/stage_report.py --stage-id 3.3 --stage-name "
        "Install, First Run, Local Gate Foundation"
    )
    assert (
        "--check gauntletgate-all|GauntletGate all lanes|passed|powershell -NoProfile "
        in commands[7]
    )
    assert "|artifacts/gauntletgate/3.3-stage1-final" in commands[7]


def test_stage1_gate_marks_prior_failed_steps_blocked_in_stage_report(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    plan = run_stage1_release_gate.build_plan(repo_root=repo, version="3.3.0")
    results = {
        "full-stack": run_stage1_release_gate.StepResult(
            id="full-stack",
            exit_code=1,
            evidence="artifacts/test-runs",
        ),
        "release-identity": run_stage1_release_gate.StepResult(
            id="release-identity",
            exit_code=0,
            evidence="artifacts/release/v3.3.0-stage1",
        ),
        "first-run-attestation": run_stage1_release_gate.StepResult(
            id="first-run-attestation",
            exit_code=0,
            evidence="artifacts/first-run/3.3-stage1-final",
        ),
        "release-artifacts": run_stage1_release_gate.StepResult(
            id="release-artifacts",
            exit_code=0,
            evidence="artifacts/release/v3.3.0-stage1",
        ),
        "clean-windows-proof": run_stage1_release_gate.StepResult(
            id="clean-windows-proof",
            exit_code=1,
            evidence="artifacts/clean-windows/3.3-stage1-final",
        ),
        "stage1-lifecycle-proof": run_stage1_release_gate.StepResult(
            id="stage1-lifecycle-proof",
            exit_code=1,
            evidence="artifacts/stage1-lifecycle/3.3-stage1-final/stage1-installer-lifecycle-proof.json",
        ),
        "gauntletgate-all": run_stage1_release_gate.StepResult(
            id="gauntletgate-all",
            exit_code=1,
            evidence="artifacts/gauntletgate/3.3-stage1-final",
        ),
    }

    report_step = run_stage1_release_gate.stage_report_step_with_results(plan, results)
    command = " ".join(report_step.command)

    assert "--check full-stack|Full stack baseline|blocked|" in command
    assert "--check release-identity|Release identity policy|passed|" in command
    assert "--check first-run-attestation|Isolated first-run attestation|passed|" in command
    assert "--check release-artifacts|Release artifact build|passed|" in command
    assert "--check clean-windows-proof|Clean Windows proof runner|blocked|" in command
    assert "--check stage1-lifecycle-proof|Stage 1 installer lifecycle proof|blocked|" in command
    assert "--check gauntletgate-all|GauntletGate all lanes|blocked|" in command


def test_stage1_gate_seeds_cached_gstreamer_runtime_for_release_build(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "artifacts" / "release" / "gstreamer-runtime"
    target = repo / "artifacts" / "release" / "v3.3.0-stage1" / "gstreamer-runtime"
    source.mkdir(parents=True)
    (source / "gstreamer-runtime-linux-x86_64.tar.gz").write_bytes(b"runtime")
    (source / "gstreamer-runtime-linux-x86_64.tar.gz.sha256").write_text(
        "abc  gstreamer-runtime-linux-x86_64.tar.gz\n",
        encoding="utf-8",
    )

    run_stage1_release_gate.seed_cached_gstreamer_runtime(repo, target.parent)

    assert (target / "gstreamer-runtime-linux-x86_64.tar.gz").read_bytes() == b"runtime"
    assert (target / "gstreamer-runtime-linux-x86_64.tar.gz.sha256").exists()


def test_stage1_gate_resets_first_run_profile(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    profile = repo / "artifacts" / "first-run" / "3.3-stage1-final" / "profile"
    profile.mkdir(parents=True)
    (profile / "station-state.json").write_text("stale", encoding="utf-8")

    run_stage1_release_gate.reset_first_run_profile(repo)

    assert not profile.exists()
