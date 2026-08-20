# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the local stage report generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "stage_report",
    Path(__file__).resolve().parents[1] / "scripts" / "stage_report.py",
)
stage_report = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = stage_report
_SPEC.loader.exec_module(stage_report)


def _source_state(head: str) -> dict[str, object]:
    return {
        "branch": "local/3.3-stage1-install-first-run-gate",
        "head": head,
        "dirty": False,
        "changed_files": [],
        "status_sha256": "0" * 64,
        "diff_sha256": "1" * 64,
        "untracked_content_sha256": "2" * 64,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_clean_windows_evidence(
    path: Path,
    status: str,
    *,
    head: str = "a" * 40,
    release_manifest: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = None
    if release_manifest is not None:
        manifest_payload = json.loads(release_manifest.read_text(encoding="utf-8"))
        identity = {
            "path": str(release_manifest),
            "sha256": _sha256(release_manifest),
            "version": manifest_payload.get("version"),
            "source_head": manifest_payload.get("source_state", {}).get("head"),
        }
    path.write_text(
        json.dumps(
            {
                "status": status,
                "dry_run": False,
                "will_boot_vm": False,
                "vm_booted": status == "passed",
                "release_manifest": str(release_manifest) if release_manifest else None,
                "release_manifest_identity": identity,
                "source_state": _source_state(head),
                "generated_at_unix": 1,
                "attempts": [
                    {
                        "strategy": "virtualbox-vm",
                        "status": status,
                        "stdout": json.dumps(
                            {
                                "manifest_match": True,
                                "first_run_setup_path": True,
                                "pending_reboot_clear": True,
                                "report_fresh": True,
                                "report_sha256": "f" * 64,
                                "snapshot": "clean-windows-base-20260602",
                            }
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_release_manifest(path: Path, *, head: str = "a" * 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = path.parent / "civiccast-3.3.0-windows-setup.exe"
    artifact.write_bytes(b"installer")
    path.write_text(
        json.dumps(
            {
                "version": "3.3.0",
                "artifacts": [
                    {
                        "filename": "civiccast-3.3.0-windows-setup.exe",
                        "size_bytes": artifact.stat().st_size,
                        "sha256": _sha256(artifact),
                    }
                ],
                "source_state": _source_state(head),
            }
        ),
        encoding="utf-8",
    )


def _write_gauntlet_report(path: Path, *, head: str, extra: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                "# GauntletGate All",
                "",
                "Verdict: PASS",
                f"Source HEAD: {head}",
                "Lanes: lite, walkthrough, full",
                "Skipped/Waived Required Checks: none",
                "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
                extra,
            ]
        ),
        encoding="utf-8",
    )


def _write_full_stack_summary(path: Path, *, head: str, skip_ledger: dict | None = None) -> None:
    payload = {
        "status": "passed",
        "source_state": _source_state(head),
    }
    if skip_ledger is not None:
        payload["skip_ledger"] = skip_ledger
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_first_run_attestation(path: Path, *, head: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"verdict": "pass", "source_state": _source_state(head)}),
        encoding="utf-8",
    )


def _write_lifecycle_proof(path: Path, *, head: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_state": _source_state(head),
                "scope": "executed Stage 1 checks only",
                "checks": [
                    {"id": "clean-install", "status": "passed"},
                    {"id": "first-run", "status": "passed"},
                    {"id": "repair", "status": "passed"},
                    {"id": "release-artifact-binding", "status": "passed"},
                    {"id": "uninstall", "status": "passed"},
                    {"id": "reinstall", "status": "passed"},
                    {"id": "upgrade", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_stage_report_fails_closed_without_clean_windows_proof(tmp_path: Path) -> None:
    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        required_checks=[
            stage_report.StageCheck(
                id="full-stack-baseline",
                label="Full stack baseline",
                status="passed",
                command="powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
                evidence="artifacts/test-runs/20260702-130007",
            )
        ],
        clean_windows_evidence=tmp_path / "missing-clean-proof.json",
        release_manifest=tmp_path / "missing-release-manifest.json",
        source_state={
            "branch": "local/3.3-stage1-install-first-run-gate",
            "head": "a" * 40,
            "dirty": False,
            "changed_files": [],
        },
    )

    assert report.status == "blocked"
    assert report.clean_windows_proof.status == "missing"
    assert report.release_manifest.status == "missing"
    assert any(check.status == "blocked" for check in report.required_checks)


def test_stage_report_passes_when_required_checks_and_clean_proof_pass(
    tmp_path: Path,
) -> None:
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    head = "b" * 40
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    full_stack_evidence = tmp_path / "artifacts/test-runs/20260702-130007"
    gauntlet_evidence = tmp_path / "artifacts/gauntletgate/3.3-stage1-final"
    first_run_evidence = tmp_path / "artifacts/first-run/3.3-stage1-final"
    lifecycle_evidence = (
        tmp_path
        / "artifacts/stage1-lifecycle/3.3-stage1-final/stage1-installer-lifecycle-proof.json"
    )
    full_stack_evidence.mkdir(parents=True)
    gauntlet_evidence.mkdir(parents=True)
    _write_full_stack_summary(full_stack_evidence / "summary.json", head=head)
    (full_stack_evidence / "01-uv.log").write_text("4506 passed", encoding="utf-8")
    _write_gauntlet_report(gauntlet_evidence / "00-gate-report.md", head=head)
    _write_first_run_attestation(first_run_evidence / "first-run-attestation.json", head=head)
    _write_lifecycle_proof(lifecycle_evidence, head=head)

    artifact_root = tmp_path / "stage-report"
    report = stage_report.write_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=artifact_root,
        required_checks=[
            stage_report.StageCheck(
                id="full-stack-baseline",
                label="Full stack baseline",
                status="passed",
                command="powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
                evidence="artifacts/test-runs/20260702-130007",
            ),
            stage_report.StageCheck(
                id="gauntletgate-all",
                label="GauntletGate all",
                status="passed",
                command="gauntletgate all",
                evidence="artifacts/gauntletgate/3.3-stage1-final",
            ),
            stage_report.StageCheck(
                id="release-identity",
                label="Release identity policy",
                status="passed",
                command="identity",
                evidence=str(release_manifest.parent),
            ),
            stage_report.StageCheck(
                id="first-run-attestation",
                label="First run",
                status="passed",
                command="first-run",
                evidence="artifacts/first-run/3.3-stage1-final",
            ),
            stage_report.StageCheck(
                id="release-artifacts",
                label="Release artifact build",
                status="passed",
                command="release",
                evidence=str(release_manifest.parent),
            ),
            stage_report.StageCheck(
                id="clean-windows-proof",
                label="Clean Windows proof runner",
                status="passed",
                command="clean",
                evidence=str(clean_proof.parent),
            ),
            stage_report.StageCheck(
                id="stage1-lifecycle-proof",
                label="Lifecycle",
                status="passed",
                command="lifecycle",
                evidence=str(lifecycle_evidence),
            ),
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state={
            **_source_state(head),
        },
    )

    payload = json.loads((artifact_root / "stage-report.json").read_text(encoding="utf-8"))
    markdown = (artifact_root / "stage-report.md").read_text(encoding="utf-8")
    assert report.status == "passed"
    assert payload["status"] == "passed"
    assert payload["clean_windows_proof"]["status"] == "passed"
    assert "0 required checks blocked" in markdown
    assert "GauntletGate all" in markdown


def test_stage_report_reads_bom_encoded_full_stack_summary(tmp_path: Path) -> None:
    head = "b" * 40
    full_stack_evidence = tmp_path / "artifacts/test-runs/20260702-130007"
    full_stack_evidence.mkdir(parents=True)
    payload = {"status": "passed", "source_state": _source_state(head)}
    (full_stack_evidence / "summary.json").write_text(
        json.dumps(payload),
        encoding="utf-8-sig",
    )
    (full_stack_evidence / "01-uv.log").write_text("4506 passed", encoding="utf-8")

    error = stage_report._semantic_check_error(
        "full-stack",
        full_stack_evidence,
        _source_state(head),
    )

    assert error == ""


def test_stage_report_blocks_missing_stage1_required_checks(tmp_path: Path) -> None:
    head = "b" * 40
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    missing = {check.id for check in report.required_checks if check.status == "blocked"}
    assert stage_report.STAGE_3_3_REQUIRED_CHECKS.issubset(missing)
    assert report.status == "blocked"


def test_stage_report_blocks_magic_string_only_gauntlet_report(tmp_path: Path) -> None:
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    gauntlet_evidence = tmp_path / "artifacts/gauntletgate/3.3-stage1-final"
    head = "d" * 40
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    gauntlet_evidence.mkdir(parents=True)
    (gauntlet_evidence / "00-gate-report.md").write_text(
        "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
        encoding="utf-8",
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="gauntletgate-all",
                label="GauntletGate all",
                status="passed",
                command="gauntletgate all",
                evidence="artifacts/gauntletgate/3.3-stage1-final",
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state={
            **_source_state(head),
        },
    )

    assert report.status == "blocked"
    gauntlet = next(check for check in report.required_checks if check.id == "gauntletgate-all")
    assert gauntlet.status == "blocked"
    assert "passing verdict" in gauntlet.notes


def test_stage_report_blocks_full_stack_skips_without_ledger(tmp_path: Path) -> None:
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    full_stack_evidence = tmp_path / "artifacts/test-runs/20260702-130007"
    head = "e" * 40
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    full_stack_evidence.mkdir(parents=True)
    _write_full_stack_summary(full_stack_evidence / "summary.json", head=head)
    (full_stack_evidence / "04-uv.log").write_text(
        "SKIPPED [1] tests/example.py:12: dependency missing\n1 passed, 1 skipped",
        encoding="utf-8",
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="full-stack-baseline",
                label="Full stack baseline",
                status="passed",
                command="powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
                evidence="artifacts/test-runs/20260702-130007",
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state={
            **_source_state(head),
        },
    )

    assert report.status == "blocked"
    full_stack = next(
        check for check in report.required_checks if check.id == "full-stack-baseline"
    )
    assert full_stack.status == "blocked"
    assert "skip ledger" in full_stack.notes


def test_stage_report_blocks_full_stack_summary_only_skips_without_entries(
    tmp_path: Path,
) -> None:
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    full_stack_evidence = tmp_path / "artifacts/test-runs/20260702-130007"
    head = "f" * 40
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    full_stack_evidence.mkdir(parents=True)
    _write_full_stack_summary(
        full_stack_evidence / "summary.json",
        head=head,
        skip_ledger={"status": "none", "total_skipped": 0, "required_skipped": 0, "entries": []},
    )
    (full_stack_evidence / "04-uv.log").write_text(
        "4512 passed, 22 skipped in 403.22s",
        encoding="utf-8",
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="full-stack-baseline",
                label="Full stack baseline",
                status="passed",
                command="powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
                evidence="artifacts/test-runs/20260702-130007",
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    full_stack = next(
        check for check in report.required_checks if check.id == "full-stack-baseline"
    )
    assert report.status == "blocked"
    assert full_stack.status == "blocked"
    assert "not classified" in full_stack.notes


def test_stage_report_blocks_stale_release_manifest(tmp_path: Path) -> None:
    head = "a" * 40
    release_manifest = tmp_path / "release-manifest.json"
    clean_proof = tmp_path / "clean-windows-install.json"
    _write_release_manifest(release_manifest, head="b" * 40)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    assert report.status == "blocked"
    assert report.release_manifest.status == "invalid"
    assert "current source head" in report.release_manifest.message


def test_stage_report_blocks_release_manifest_artifact_hash_mismatch(tmp_path: Path) -> None:
    head = "a" * 40
    release_manifest = tmp_path / "release-manifest.json"
    clean_proof = tmp_path / "clean-windows-install.json"
    _write_release_manifest(release_manifest, head=head)
    (tmp_path / "civiccast-3.3.0-windows-setup.exe").write_bytes(b"tampered")
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    assert report.status == "blocked"
    assert report.release_manifest.status == "invalid"
    assert "wrong" in report.release_manifest.message


def test_stage_report_blocks_stale_clean_windows_proof(tmp_path: Path) -> None:
    head = "a" * 40
    release_manifest = tmp_path / "release-manifest.json"
    clean_proof = tmp_path / "clean-windows-install.json"
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof,
        "passed",
        head="b" * 40,
        release_manifest=release_manifest,
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    assert report.status == "blocked"
    assert report.clean_windows_proof.status == "invalid"
    assert "current source head" in report.clean_windows_proof.message


def test_stage_report_blocks_stale_first_run_attestation(tmp_path: Path) -> None:
    head = "a" * 40
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    first_run_dir = tmp_path / "artifacts/first-run"
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    first_run_dir.mkdir(parents=True)
    (first_run_dir / "first-run-attestation.json").write_text(
        json.dumps({"verdict": "pass", "source_state": _source_state("b" * 40)}),
        encoding="utf-8",
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="first-run-attestation",
                label="First run",
                status="passed",
                command="attest",
                evidence="artifacts/first-run",
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    first_run = next(
        check for check in report.required_checks if check.id == "first-run-attestation"
    )
    assert report.status == "blocked"
    assert first_run.status == "blocked"
    assert "current source head" in first_run.notes


def test_stage_report_blocks_stale_lifecycle_proof(tmp_path: Path) -> None:
    head = "a" * 40
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    lifecycle = tmp_path / "stage1-installer-lifecycle-proof.json"
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    lifecycle.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_state": _source_state("b" * 40),
                "checks": [{"id": "clean-install", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="stage1-lifecycle-proof",
                label="Lifecycle",
                status="passed",
                command="lifecycle",
                evidence=str(lifecycle),
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state=_source_state(head),
    )

    lifecycle_check = next(
        check for check in report.required_checks if check.id == "stage1-lifecycle-proof"
    )
    assert report.status == "blocked"
    assert lifecycle_check.status == "blocked"
    assert "current source head" in lifecycle_check.notes


def test_stage_report_blocks_incomplete_lifecycle_checks(tmp_path: Path) -> None:
    head = "a" * 40
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    lifecycle = tmp_path / "stage1-installer-lifecycle-proof.json"
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    lifecycle.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_state": _source_state(head),
                "checks": [
                    {"id": "clean-install", "status": "passed"},
                    {"id": "first-run", "status": "passed"},
                    {"id": "repair", "status": "passed"},
                    {"id": "release-artifact-binding", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    error = stage_report._semantic_check_error(
        "stage1-lifecycle-proof",
        lifecycle,
        _source_state(head),
    )

    assert "missing executed lifecycle checks" in error


def test_stage_report_blocks_passed_check_with_empty_evidence_dir(tmp_path: Path) -> None:
    clean_proof = tmp_path / "clean-windows-install.json"
    release_manifest = tmp_path / "release-manifest.json"
    empty_evidence = tmp_path / "artifacts/test-runs/20260702-130007"
    head = "c" * 40
    _write_release_manifest(release_manifest, head=head)
    _write_clean_windows_evidence(
        clean_proof, "passed", head=head, release_manifest=release_manifest
    )
    empty_evidence.mkdir(parents=True)

    report = stage_report.build_stage_report(
        stage_id="3.3",
        stage_name="Install, First Run, Local Gate Foundation",
        repo_root=tmp_path,
        artifact_root=tmp_path / "stage-report",
        required_checks=[
            stage_report.StageCheck(
                id="full-stack-baseline",
                label="Full stack baseline",
                status="passed",
                command="powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
                evidence="artifacts/test-runs/20260702-130007",
            )
        ],
        clean_windows_evidence=clean_proof,
        release_manifest=release_manifest,
        source_state={
            **_source_state(head),
        },
    )

    assert report.status == "blocked"
    assert report.required_checks[0].status == "blocked"
    assert "empty" in report.required_checks[0].notes
