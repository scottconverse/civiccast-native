"""Contracts for the Stage 1 installer lifecycle proof."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "run_stage1_lifecycle_proof",
    Path(__file__).resolve().parents[1] / "scripts" / "run_stage1_lifecycle_proof.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
run_stage1_lifecycle_proof = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = run_stage1_lifecycle_proof
_SPEC.loader.exec_module(run_stage1_lifecycle_proof)


def _clean_source_state() -> dict[str, Any]:
    return {
        "branch": "test",
        "head": "a" * 40,
        "dirty": False,
        "changed_files": [],
        "status_sha256": "0" * 64,
        "diff_sha256": "1" * 64,
        "untracked_content_sha256": "2" * 64,
    }


def _write_inputs(
    tmp_path: Path,
    *,
    first_run_setup_path: bool = True,
    source_state: dict[str, Any] | None = None,
    uninstall_status: str = "passed",
    reinstall_status: str = "passed",
    upgrade_status: str = "passed",
    lifecycle_shape: bool = True,
) -> dict[str, Path]:
    source_state = source_state or _clean_source_state()
    clean = tmp_path / "clean.json"
    first_run = tmp_path / "first-run.json"
    manifest = tmp_path / "manifest.json"
    installer_spec = tmp_path / "installer.spec.ts"
    runbook = tmp_path / "runbook.md"
    uninstall_evidence = tmp_path / "uninstall-proof.json"
    reinstall_evidence = tmp_path / "reinstall-proof.json"
    upgrade_evidence = tmp_path / "upgrade-proof.json"
    clean.write_text(
        json.dumps(
            {
                "status": "passed",
                "attempts": [
                    {
                        "strategy": "virtualbox-vm",
                        "status": "passed",
                        "stdout": json.dumps(
                            {
                                "manifest_match": True,
                                "first_run_setup_path": first_run_setup_path,
                            }
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first_run.write_text(
        json.dumps(
            {
                "verdict": "pass",
                "source_state": source_state,
                "steps": {"first_admin": {"status": "complete"}},
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "version": "3.3.0",
                "artifacts": [{"filename": "installer.exe"}],
                "source_state": source_state,
                "beta_handoff_acquisition": {
                    "hashes": {"windows_installer": "sha", "clean_windows_proof_kit": "kit"}
                },
            }
        ),
        encoding="utf-8",
    )
    installer_spec.write_text(
        'test("installer saves repair progress and can reset it", async () => {});',
        encoding="utf-8",
    )
    runbook.write_text(
        "\n".join(
            [
                "## Uninstall verification",
                "uninstall.exe",
                "## Reinstall verification",
                "same-version reinstall",
                "## Upgrade verification",
                "v3.2.0-beta1",
                "3.3.0",
            ]
        ),
        encoding="utf-8",
    )

    def lifecycle_payload(status: str, lifecycle_key: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status, "source_state": source_state}
        if lifecycle_shape:
            payload.update(
                {
                    "version": "4.0.0-rc.2",
                    "vm_report": "vbox-cleanwin-v2-final-lifecycle-proof-report.json",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "preinstall",
                    "package": {
                        "installer_sha256": "a" * 64,
                        "proof_kit_sha256": "b" * 64,
                    },
                    lifecycle_key: {
                        "exit_code": 0,
                        "started_at": "2026-07-03T00:00:00Z",
                        "finished_at": "2026-07-03T00:01:00Z",
                    },
                }
            )
        return payload

    uninstall_payload = lifecycle_payload(uninstall_status, "uninstall")
    if lifecycle_shape:
        uninstall_payload["uninstall"]["entries_after"] = []
        uninstall_payload["uninstall"]["app_path_after"] = ""
        uninstall_payload["uninstall"]["retained_paths_policy"] = {
            "status": "allowed",
            "allowed_paths": [
                "C:\\Users\\tester\\AppData\\Local\\CivicCast",
                "C:\\Users\\tester\\AppData\\Local\\CivicCast Installer",
            ],
        }
    uninstall_evidence.write_text(json.dumps(uninstall_payload, indent=2), encoding="utf-8")
    reinstall_evidence.write_text(
        json.dumps(lifecycle_payload(reinstall_status, "reinstall"), indent=2),
        encoding="utf-8",
    )
    upgrade_evidence.write_text(
        json.dumps(lifecycle_payload(upgrade_status, "upgrade"), indent=2),
        encoding="utf-8",
    )
    return {
        "clean": clean,
        "first_run": first_run,
        "manifest": manifest,
        "installer_spec": installer_spec,
        "runbook": runbook,
        "uninstall_evidence": uninstall_evidence,
        "reinstall_evidence": reinstall_evidence,
        "upgrade_evidence": upgrade_evidence,
    }


def test_lifecycle_proof_passes_with_all_required_evidence(tmp_path: Path, monkeypatch) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state)

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "passed"
    assert {check["id"] for check in payload["checks"]} == {
        "clean-install",
        "first-run",
        "repair",
        "release-artifact-binding",
        "uninstall",
        "reinstall",
        "upgrade",
    }
    statuses = {check["id"]: check["status"] for check in payload["checks"]}
    assert statuses["clean-install"] == "passed"
    assert statuses["first-run"] == "passed"
    assert statuses["repair"] == "passed"
    assert statuses["release-artifact-binding"] == "passed"
    assert statuses["uninstall"] == "passed"
    assert statuses["reinstall"] == "passed"
    assert statuses["upgrade"] == "passed"


def test_lifecycle_proof_does_not_overstate_documented_paths_as_passed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state)

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "passed"
    statuses = {check["id"]: check["status"] for check in payload["checks"]}
    assert statuses["uninstall"] == "passed"
    assert statuses["reinstall"] == "passed"
    assert statuses["upgrade"] == "passed"


def test_lifecycle_proof_blocks_without_first_run_setup_path(tmp_path: Path, monkeypatch) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, first_run_setup_path=False, source_state=source_state)

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "blocked"
    clean_install = next(check for check in payload["checks"] if check["id"] == "clean-install")
    assert clean_install["status"] == "blocked"


def test_lifecycle_proof_blocks_stale_first_run_attestation(tmp_path: Path, monkeypatch) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state)
    first_run = json.loads(paths["first_run"].read_text(encoding="utf-8"))
    first_run["source_state"]["head"] = "0" * 40
    paths["first_run"].write_text(json.dumps(first_run), encoding="utf-8")

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "blocked"
    first_run_check = next(check for check in payload["checks"] if check["id"] == "first-run")
    assert first_run_check["status"] == "blocked"


def test_lifecycle_proof_blocks_stale_release_manifest(tmp_path: Path, monkeypatch) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["source_state"]["head"] = "0" * 40
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
    )

    assert payload["status"] == "blocked"
    release_binding = next(
        check for check in payload["checks"] if check["id"] == "release-artifact-binding"
    )
    assert release_binding["status"] == "blocked"


def test_lifecycle_proof_blocks_without_uninstall_reinstall_upgrade_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(
        tmp_path,
        source_state=source_state,
        uninstall_status="blocked",
        reinstall_status="blocked",
        upgrade_status="blocked",
    )

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "blocked"
    for check_id in ("uninstall", "reinstall", "upgrade"):
        check = next(check for check in payload["checks"] if check["id"] == check_id)
        assert check["status"] == "blocked"


def test_lifecycle_proof_blocks_thin_lifecycle_json_without_execution_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state, lifecycle_shape=False)

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    assert payload["status"] == "blocked"
    for check_id in ("uninstall", "reinstall", "upgrade"):
        check = next(check for check in payload["checks"] if check["id"] == check_id)
        assert check["status"] == "blocked"


def test_lifecycle_proof_blocks_uninstall_without_retention_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_state = _clean_source_state()
    monkeypatch.setattr(
        run_stage1_lifecycle_proof,
        "collect_source_state",
        lambda *, repo_root: source_state,
    )
    paths = _write_inputs(tmp_path, source_state=source_state)
    uninstall = json.loads(paths["uninstall_evidence"].read_text(encoding="utf-8"))
    del uninstall["uninstall"]["retained_paths_policy"]
    paths["uninstall_evidence"].write_text(json.dumps(uninstall), encoding="utf-8")

    payload = run_stage1_lifecycle_proof.build_lifecycle_proof(
        repo_root=Path.cwd(),
        clean_windows_evidence=paths["clean"],
        first_run_evidence=paths["first_run"],
        release_manifest=paths["manifest"],
        installer_spec=paths["installer_spec"],
        lifecycle_runbook=paths["runbook"],
        uninstall_evidence=paths["uninstall_evidence"],
        reinstall_evidence=paths["reinstall_evidence"],
        upgrade_evidence=paths["upgrade_evidence"],
    )

    uninstall_check = next(check for check in payload["checks"] if check["id"] == "uninstall")
    assert payload["status"] == "blocked"
    assert uninstall_check["status"] == "blocked"
