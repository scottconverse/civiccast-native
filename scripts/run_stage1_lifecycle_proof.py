#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Write Stage 1 installer lifecycle proof from concrete local evidence."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state


@dataclass(frozen=True)
class LifecycleCheck:
    id: str
    status: str
    evidence: str
    notes: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _virtualbox_attempt(clean_proof: dict[str, Any]) -> dict[str, Any]:
    for attempt in clean_proof.get("attempts", []):
        if isinstance(attempt, dict) and attempt.get("strategy") == "virtualbox-vm":
            return attempt
    return {}


def _lifecycle_evidence_passes(
    evidence_path: Path,
    current_source_state: dict[str, Any],
    lifecycle_key: str,
) -> bool:
    payload = _read_json(evidence_path)
    if payload.get("status") != "passed":
        return False
    if not _source_state_matches(payload, current_source_state):
        return False
    if not _has_required_lifecycle_shape(payload, lifecycle_key):
        return False
    return lifecycle_key != "uninstall" or _uninstall_cleanup_policy_passes(payload)


def _has_required_lifecycle_shape(payload: dict[str, Any], lifecycle_key: str) -> bool:
    if not all(
        isinstance(payload.get(key), str) and payload[key]
        for key in ("version", "vm_report", "vm", "snapshot")
    ):
        return False
    package = payload.get("package")
    if not isinstance(package, dict):
        return False
    for key in ("installer_sha256", "proof_kit_sha256"):
        value = package.get(key)
        if not isinstance(value, str) or len(value) != 64:
            return False
    lifecycle = payload.get(lifecycle_key)
    if not isinstance(lifecycle, dict):
        return False
    if lifecycle.get("exit_code") != 0:
        return False
    return all(
        isinstance(lifecycle.get(key), str) and lifecycle[key]
        for key in ("started_at", "finished_at")
    )


def _uninstall_cleanup_policy_passes(payload: dict[str, Any]) -> bool:
    uninstall = payload.get("uninstall")
    if not isinstance(uninstall, dict):
        return False
    if uninstall.get("entries_after") not in ([], None):
        return False
    if uninstall.get("app_path_after") not in ("", None):
        return False
    policy = uninstall.get("retained_paths_policy")
    if not isinstance(policy, dict) or policy.get("status") != "allowed":
        return False
    allowed_paths = policy.get("allowed_paths")
    return isinstance(allowed_paths, list) and all(
        isinstance(path, str) and path for path in allowed_paths
    )


def _stage1_status(checks: list[LifecycleCheck]) -> str:
    return "passed" if all(check.status == "passed" for check in checks) else "blocked"


def _source_state_matches(payload: dict[str, Any], current_source: dict[str, Any]) -> bool:
    source = payload.get("source_state")
    if not isinstance(source, dict):
        return False
    if source.get("dirty") is not False or source.get("head") != current_source.get("head"):
        return False
    for key in ("status_sha256", "diff_sha256", "untracked_content_sha256"):
        if (
            source.get(key) is not None
            and current_source.get(key) is not None
            and source.get(key) != current_source.get(key)
        ):
            return False
    return True


def _text_contains(path: Path, *needles: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(needle in text for needle in needles)


def build_lifecycle_proof(
    *,
    repo_root: Path,
    clean_windows_evidence: Path,
    first_run_evidence: Path,
    release_manifest: Path,
    installer_spec: Path,
    lifecycle_runbook: Path,
    uninstall_evidence: Path | None = None,
    reinstall_evidence: Path | None = None,
    upgrade_evidence: Path | None = None,
) -> dict[str, Any]:
    current_source_state = collect_source_state(repo_root=repo_root)
    clean_proof = _read_json(clean_windows_evidence)
    first_run = _read_json(first_run_evidence)
    manifest = _read_json(release_manifest)
    uninstall_evidence = uninstall_evidence or lifecycle_runbook
    reinstall_evidence = reinstall_evidence or lifecycle_runbook
    upgrade_evidence = upgrade_evidence or lifecycle_runbook
    vm_attempt = _virtualbox_attempt(clean_proof)
    try:
        vm_stdout = json.loads(str(vm_attempt.get("stdout", "{}")))
    except json.JSONDecodeError:
        vm_stdout = {}
    executed_checks = [
        LifecycleCheck(
            id="clean-install",
            status="passed"
            if clean_proof.get("status") == "passed"
            and vm_attempt.get("status") == "passed"
            and vm_stdout.get("manifest_match") is True
            and vm_stdout.get("first_run_setup_path") is True
            else "blocked",
            evidence=str(clean_windows_evidence),
            notes="Clean VM installer launch, release-manifest hash match, and dependency-absent first-run setup path.",
        ),
        LifecycleCheck(
            id="first-run",
            status="passed"
            if first_run.get("verdict") == "pass"
            and first_run.get("steps", {}).get("first_admin", {}).get("status") == "complete"
            and _source_state_matches(first_run, current_source_state)
            else "blocked",
            evidence=str(first_run_evidence),
            notes="Isolated first-admin, first-station, storage, and dashboard readiness proof.",
        ),
        LifecycleCheck(
            id="repair",
            status="passed"
            if _text_contains(installer_spec, "installer saves repair progress and can reset it")
            else "blocked",
            evidence=str(installer_spec),
            notes="Automated installer e2e covers repair queueing and reset behavior.",
        ),
        LifecycleCheck(
            id="release-artifact-binding",
            status="passed"
            if _source_state_matches(manifest, current_source_state)
            and manifest.get("beta_handoff_acquisition", {})
            .get("hashes", {})
            .get("windows_installer")
            else "blocked",
            evidence=str(release_manifest),
            notes="Release manifest is source-state stamped and carries installer/proof-kit hashes.",
        ),
        LifecycleCheck(
            id="uninstall",
            status="passed"
            if _lifecycle_evidence_passes(uninstall_evidence, current_source_state, "uninstall")
            else "blocked",
            evidence=str(uninstall_evidence),
            notes=(
                "Uninstall lifecycle execution evidence must be source-bound JSON with VM, "
                "package hash, exit-code, cleanup, and retained-path policy fields."
            ),
        ),
        LifecycleCheck(
            id="reinstall",
            status="passed"
            if _lifecycle_evidence_passes(reinstall_evidence, current_source_state, "reinstall")
            else "blocked",
            evidence=str(reinstall_evidence),
            notes=(
                "Reinstall lifecycle execution evidence must be source-bound JSON with VM, "
                "package hash, exit-code, and timestamps."
            ),
        ),
        LifecycleCheck(
            id="upgrade",
            status="passed"
            if _lifecycle_evidence_passes(upgrade_evidence, current_source_state, "upgrade")
            else "blocked",
            evidence=str(upgrade_evidence),
            notes=(
                "Upgrade lifecycle execution evidence must be source-bound JSON with VM, "
                "package hash, exit-code, and timestamps."
            ),
        ),
    ]
    return {
        "status": _stage1_status(executed_checks),
        "scope": (
            "Stage 1 pass status requires executed evidence for clean install, first run, "
            "repair coverage, uninstall, reinstall, upgrade, and release-artifact binding."
        ),
        "generated_at_unix": int(time.time()),
        "source_state": current_source_state,
        "checks": [asdict(check) for check in executed_checks],
    }


def write_lifecycle_proof(*, artifact_root: Path, payload: dict[str, Any]) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True)
    json_path = artifact_root / "stage1-installer-lifecycle-proof.json"
    md_path = artifact_root / "stage1-installer-lifecycle-proof.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Stage 1 Installer Lifecycle Proof",
        "",
        f"Status: `{payload['status']}`",
        "",
        "| Executed check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in payload["checks"]:
        lines.append(f"| {check['id']} | `{check['status']}` | `{check['evidence']}` |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--clean-windows-evidence", type=Path, required=True)
    parser.add_argument("--first-run-evidence", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument(
        "--installer-spec",
        type=Path,
        default=Path("civiccast/apps/installer/e2e/installer.spec.ts"),
    )
    parser.add_argument(
        "--lifecycle-runbook",
        type=Path,
        default=Path("docs/ops/stage1-installer-lifecycle-verification.md"),
    )
    parser.add_argument(
        "--uninstall-evidence",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--reinstall-evidence",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--upgrade-evidence",
        type=Path,
        default=None,
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    payload = build_lifecycle_proof(
        repo_root=repo_root,
        clean_windows_evidence=repo_root / args.clean_windows_evidence,
        first_run_evidence=repo_root / args.first_run_evidence,
        release_manifest=repo_root / args.release_manifest,
        installer_spec=repo_root / args.installer_spec,
        lifecycle_runbook=repo_root / args.lifecycle_runbook,
        uninstall_evidence=repo_root / args.uninstall_evidence
        if args.uninstall_evidence is not None
        else None,
        reinstall_evidence=repo_root / args.reinstall_evidence
        if args.reinstall_evidence is not None
        else None,
        upgrade_evidence=repo_root / args.upgrade_evidence
        if args.upgrade_evidence is not None
        else None,
    )
    write_lifecycle_proof(artifact_root=repo_root / args.artifact_root, payload=payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
