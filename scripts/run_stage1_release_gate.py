#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the Stage 1 release gate and write the fail-closed stage report."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STAGE_ID = "3.3"
STAGE_NAME = "Install, First Run, Local Gate Foundation"


@dataclass(frozen=True)
class GateStep:
    """One command in the Stage 1 local release gate."""

    id: str
    label: str
    command: list[str]
    evidence: str


@dataclass(frozen=True)
class StepResult:
    """Result summary passed into the final stage-report command."""

    id: str
    exit_code: int
    evidence: str


@dataclass(frozen=True)
class Stage1GatePlan:
    """Fully resolved command plan for Stage 1."""

    repo_root: Path
    version: str
    release_manifest: Path
    clean_windows_evidence: Path
    steps: list[GateStep]


def build_plan(
    *,
    repo_root: Path,
    version: str,
    release_out_dir: Path | None = None,
    clean_evidence_dir: Path | None = None,
    stage_report_dir: Path | None = None,
) -> Stage1GatePlan:
    """Build the Stage 1 command sequence with stage-report checks assumed passing."""

    release_dir = release_out_dir or repo_root / "artifacts" / "release" / "v3.3.0-stage1"
    clean_dir = clean_evidence_dir or repo_root / "artifacts" / "clean-windows" / "3.3-stage1-final"
    report_dir = stage_report_dir or repo_root / "artifacts" / "stage-reports" / "3.3-stage1-final"
    manifest = release_dir / f"civiccast-{version}-release-artifacts-manifest.json"
    clean_json = clean_dir / "clean-windows-install.json"
    lifecycle_dir = repo_root / "artifacts" / "stage1-lifecycle" / "3.3-stage1-final"
    lifecycle_json = lifecycle_dir / "stage1-installer-lifecycle-proof.json"
    uninstall_json = lifecycle_dir / "uninstall-proof.json"
    reinstall_json = lifecycle_dir / "reinstall-proof.json"
    upgrade_json = lifecycle_dir / "upgrade-proof.json"
    gauntlet_dir = repo_root / "artifacts" / "gauntletgate" / "3.3-stage1-final"

    full_stack = GateStep(
        id="full-stack",
        label="Full stack baseline",
        command=[
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/run_full_test_stack.ps1",
        ],
        evidence="artifacts/test-runs",
    )
    release_identity = GateStep(
        id="release-identity",
        label="Release identity policy",
        command=[
            "uv",
            "run",
            "python",
            "scripts/policy/check_release_identity.py",
        ],
        evidence=_rel(repo_root, release_dir),
    )
    first_run = GateStep(
        id="first-run-attestation",
        label="Isolated first-run attestation",
        command=[
            "uv",
            "run",
            "python",
            "scripts/run_isolated_first_run_attestation.py",
            "--artifact-root",
            "artifacts/first-run/3.3-stage1-final",
            "--profile-root",
            "artifacts/first-run/3.3-stage1-final/profile",
        ],
        evidence="artifacts/first-run/3.3-stage1-final",
    )
    release = GateStep(
        id="release-artifacts",
        label="Release artifact build",
        command=[
            "uv",
            "run",
            "python",
            "scripts/build_release_artifacts.py",
            "--version",
            version,
            "--out-dir",
            _rel(repo_root, release_dir),
            "--all-portable",
            "--python",
            "--wheelhouse",
            "--windows-installer",
        ],
        evidence=_rel(repo_root, release_dir),
    )
    clean = GateStep(
        id="clean-windows-proof",
        label="Clean Windows proof runner",
        command=[
            "uv",
            "run",
            "python",
            "scripts/run_clean_windows_install_proof.py",
            "--execute",
            "--evidence-dir",
            _rel(repo_root, clean_dir),
            "--release-manifest",
            _rel(repo_root, manifest),
        ],
        evidence=_rel(repo_root, clean_dir),
    )
    lifecycle = GateStep(
        id="stage1-lifecycle-proof",
        label="Stage 1 installer lifecycle proof",
        command=[
            "uv",
            "run",
            "python",
            "scripts/run_stage1_lifecycle_proof.py",
            "--artifact-root",
            _rel(repo_root, lifecycle_dir),
            "--clean-windows-evidence",
            _rel(repo_root, clean_json),
            "--first-run-evidence",
            "artifacts/first-run/3.3-stage1-final/first-run-attestation.json",
            "--release-manifest",
            _rel(repo_root, manifest),
            "--uninstall-evidence",
            _rel(repo_root, uninstall_json),
            "--reinstall-evidence",
            _rel(repo_root, reinstall_json),
            "--upgrade-evidence",
            _rel(repo_root, upgrade_json),
        ],
        evidence=_rel(repo_root, lifecycle_json),
    )
    gauntlet = GateStep(
        id="gauntletgate-all",
        label="GauntletGate all lanes",
        command=[
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"if (-not (Test-Path -LiteralPath '{gauntlet_dir / '00-gate-report.md'}')) {{ exit 1 }}",
        ],
        evidence=_rel(repo_root, gauntlet_dir),
    )
    plan = Stage1GatePlan(
        repo_root=repo_root,
        version=version,
        release_manifest=manifest,
        clean_windows_evidence=clean_json,
        steps=[full_stack, release_identity, first_run, release, clean, lifecycle, gauntlet],
    )
    report = stage_report_step_with_results(
        plan,
        {
            full_stack.id: StepResult(full_stack.id, 0, full_stack.evidence),
            release_identity.id: StepResult(
                release_identity.id,
                0,
                release_identity.evidence,
            ),
            first_run.id: StepResult(first_run.id, 0, first_run.evidence),
            release.id: StepResult(release.id, 0, release.evidence),
            clean.id: StepResult(clean.id, 0, clean.evidence),
            lifecycle.id: StepResult(lifecycle.id, 0, lifecycle.evidence),
            gauntlet.id: StepResult(gauntlet.id, 0, gauntlet.evidence),
        },
        stage_report_dir=report_dir,
    )
    return Stage1GatePlan(
        repo_root=repo_root,
        version=version,
        release_manifest=manifest,
        clean_windows_evidence=clean_json,
        steps=[
            full_stack,
            release_identity,
            first_run,
            release,
            clean,
            lifecycle,
            gauntlet,
            report,
        ],
    )


def stage_report_step_with_results(
    plan: Stage1GatePlan,
    results: dict[str, StepResult],
    *,
    stage_report_dir: Path | None = None,
) -> GateStep:
    """Create the stage-report command with passed/blocked checks from prior steps."""

    report_dir = (
        stage_report_dir or plan.repo_root / "artifacts" / "stage-reports" / "3.3-stage1-final"
    )
    command = [
        "uv",
        "run",
        "python",
        "scripts/stage_report.py",
        "--stage-id",
        STAGE_ID,
        "--stage-name",
        STAGE_NAME,
        "--artifact-root",
        _rel(plan.repo_root, report_dir),
        "--release-manifest",
        _rel(plan.repo_root, plan.release_manifest),
        "--clean-windows-evidence",
        _rel(plan.repo_root, plan.clean_windows_evidence),
    ]
    for step in plan.steps:
        if step.id == "stage-report":
            continue
        result = results.get(step.id, StepResult(step.id, 1, step.evidence))
        status = "passed" if result.exit_code == 0 else "blocked"
        command.extend(
            [
                "--check",
                f"{step.id}|{step.label}|{status}|{' '.join(step.command)}|{result.evidence}",
            ]
        )
    return GateStep(
        id="stage-report",
        label="Stage report",
        command=command,
        evidence=_rel(plan.repo_root, report_dir),
    )


def run_plan(plan: Stage1GatePlan, *, dry_run: bool) -> int:
    """Run all non-report steps, then always run the stage report."""

    results: dict[str, StepResult] = {}
    for step in plan.steps:
        if step.id == "stage-report":
            continue
        print(f"\n=== {step.label} ===", flush=True)
        print(" ".join(step.command), flush=True)
        if dry_run:
            results[step.id] = StepResult(step.id, 0, step.evidence)
            continue
        if step.id == "release-artifacts":
            seed_cached_gstreamer_runtime(plan.repo_root, plan.release_manifest.parent)
        if step.id == "first-run-attestation":
            reset_first_run_profile(plan.repo_root)
        completed = subprocess.run(step.command, cwd=plan.repo_root, check=False)
        evidence = step.evidence
        if step.id == "full-stack":
            evidence = latest_test_run_evidence(plan.repo_root) or step.evidence
        results[step.id] = StepResult(step.id, completed.returncode, evidence)

    report_step = stage_report_step_with_results(plan, results)
    print(f"\n=== {report_step.label} ===", flush=True)
    print(" ".join(report_step.command), flush=True)
    if dry_run:
        return 0
    report = subprocess.run(report_step.command, cwd=plan.repo_root, check=False)
    return report.returncode


def seed_cached_gstreamer_runtime(repo_root: Path, release_dir: Path) -> None:
    """Copy the shared cached GStreamer runtime into a versioned release dir."""

    source = repo_root / "artifacts" / "release" / "gstreamer-runtime"
    target = release_dir / "gstreamer-runtime"
    if not source.exists():
        print(
            f"No cached GStreamer runtime found at {source}; release build will validate this.",
            flush=True,
        )
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)


def latest_test_run_evidence(repo_root: Path) -> str | None:
    runs_root = repo_root / "artifacts" / "test-runs"
    if not runs_root.exists():
        return None
    candidates = [path for path in runs_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return _rel(repo_root, latest)


def reset_first_run_profile(repo_root: Path) -> None:
    profile = repo_root / "artifacts" / "first-run" / "3.3-stage1-final" / "profile"
    if profile.exists():
        shutil.rmtree(profile)


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", default="3.3.0")
    parser.add_argument("--release-out-dir", type=Path)
    parser.add_argument("--clean-evidence-dir", type=Path)
    parser.add_argument("--stage-report-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    plan = build_plan(
        repo_root=args.repo_root,
        version=args.version,
        release_out_dir=args.release_out_dir,
        clean_evidence_dir=args.clean_evidence_dir,
        stage_report_dir=args.stage_report_dir,
    )
    return run_plan(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
