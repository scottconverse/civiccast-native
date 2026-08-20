#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate a fail-closed local stage completion report."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state

CheckStatus = Literal["passed", "blocked", "failed", "skipped"]
ReportStatus = Literal["passed", "blocked"]
EvidenceStatus = Literal["passed", "blocked", "partial", "missing", "invalid"]
STAGE_3_3_REQUIRED_CHECKS = {
    "full-stack",
    "release-identity",
    "first-run-attestation",
    "release-artifacts",
    "clean-windows-proof",
    "stage1-lifecycle-proof",
    "gauntletgate-all",
}


@dataclass(frozen=True)
class StageCheck:
    """One required check named by the stage completion report."""

    id: str
    label: str
    status: CheckStatus
    command: str
    evidence: str
    notes: str = ""


@dataclass(frozen=True)
class EvidenceRef:
    """Status for a required evidence artifact."""

    status: EvidenceStatus
    path: str
    message: str


@dataclass(frozen=True)
class StageReport:
    """Machine-readable stage completion envelope."""

    stage_id: str
    stage_name: str
    status: ReportStatus
    generated_at_unix: int
    source_state: dict[str, Any]
    release_manifest: EvidenceRef
    clean_windows_proof: EvidenceRef
    required_checks: list[StageCheck]


def build_stage_report(
    *,
    stage_id: str,
    stage_name: str,
    repo_root: Path,
    artifact_root: Path,
    required_checks: list[StageCheck],
    clean_windows_evidence: Path,
    release_manifest: Path,
    source_state: dict[str, Any] | None = None,
) -> StageReport:
    """Build a report that blocks advancement unless every required proof passed."""

    _ = artifact_root
    resolved_source_state = source_state or collect_source_state(repo_root=repo_root)
    release = _read_release_manifest(release_manifest, resolved_source_state)
    clean_proof = _read_clean_windows_proof(
        clean_windows_evidence,
        resolved_source_state,
        release_manifest,
    )
    checks = [
        _validate_check_evidence(check, repo_root, resolved_source_state)
        for check in required_checks
    ]
    if stage_id == "3.3":
        present = {_stage_3_3_required_key(check.id) for check in checks}
        for missing in sorted(STAGE_3_3_REQUIRED_CHECKS - present):
            checks.append(
                StageCheck(
                    id=missing,
                    label=_stage_3_3_required_label(missing),
                    status="blocked",
                    command=_stage_3_3_required_command(missing),
                    evidence=_stage_3_3_required_evidence(missing),
                    notes="Stage 1 requires this evidence check to be declared and passed.",
                )
            )
    if release.status != "passed":
        checks.append(
            StageCheck(
                id="release-manifest",
                label="Release artifact manifest",
                status="blocked",
                command=f"read {release_manifest}",
                evidence=str(release_manifest),
                notes=release.message,
            )
        )
    if clean_proof.status != "passed":
        checks.append(
            StageCheck(
                id="clean-windows-install-proof",
                label="Clean Windows install proof",
                status="blocked",
                command=f"read {clean_windows_evidence}",
                evidence=str(clean_windows_evidence),
                notes=clean_proof.message,
            )
        )
    status: ReportStatus = (
        "passed" if all(check.status == "passed" for check in checks) else "blocked"
    )
    return StageReport(
        stage_id=stage_id,
        stage_name=stage_name,
        status=status,
        generated_at_unix=int(time.time()),
        source_state=resolved_source_state,
        release_manifest=release,
        clean_windows_proof=clean_proof,
        required_checks=checks,
    )


def _validate_check_evidence(
    check: StageCheck, repo_root: Path, source_state: dict[str, Any]
) -> StageCheck:
    if check.status != "passed":
        return check
    evidence = Path(check.evidence)
    if not evidence.is_absolute():
        evidence = repo_root / evidence
    if not evidence.exists():
        return StageCheck(
            id=check.id,
            label=check.label,
            status="blocked",
            command=check.command,
            evidence=check.evidence,
            notes="Passed check evidence path is missing.",
        )
    if evidence.is_dir() and not any(evidence.iterdir()):
        return StageCheck(
            id=check.id,
            label=check.label,
            status="blocked",
            command=check.command,
            evidence=check.evidence,
            notes="Passed check evidence directory is empty.",
        )
    if evidence.is_file() and evidence.stat().st_size == 0:
        return StageCheck(
            id=check.id,
            label=check.label,
            status="blocked",
            command=check.command,
            evidence=check.evidence,
            notes="Passed check evidence file is empty.",
        )
    semantic_error = _semantic_check_error(check.id, evidence, source_state)
    if semantic_error:
        return StageCheck(
            id=check.id,
            label=check.label,
            status="blocked",
            command=check.command,
            evidence=check.evidence,
            notes=semantic_error,
        )
    return check


def _semantic_check_error(check_id: str, evidence: Path, source_state: dict[str, Any]) -> str:
    normalized = check_id.replace("_", "-")
    if normalized in {"full-stack", "full-stack-baseline"}:
        summary = _read_json(evidence / "summary.json") if evidence.is_dir() else None
        if summary is None or summary.get("status") != "passed":
            return "Full-stack evidence summary is missing or not passed."
        source = summary.get("source_state")
        if not isinstance(source, dict):
            return "Full-stack evidence is missing source-state binding."
        source_error = _source_binding_error(
            source,
            source_state,
            label="Full-stack evidence",
            require_clean=True,
        )
        if source_error:
            return source_error
        if evidence.is_dir() and not any(evidence.glob("*.log")):
            return "Full-stack evidence has no retained command logs."
        skip_error = _full_stack_skip_ledger_error(summary, evidence)
        if skip_error:
            return skip_error
    if normalized == "first-run-attestation":
        payload = _read_json(evidence / "first-run-attestation.json") if evidence.is_dir() else None
        if payload is None or payload.get("verdict") != "pass":
            return "First-run attestation is missing or not passed."
        source_error = _source_binding_error(
            payload.get("source_state"),
            source_state,
            label="First-run attestation",
            require_clean=True,
        )
        if source_error:
            return source_error
    if normalized == "stage1-lifecycle-proof":
        payload = (
            _read_json(evidence)
            if evidence.is_file()
            else _read_json(evidence / "stage1-installer-lifecycle-proof.json")
        )
        if payload is None or payload.get("status") != "passed":
            return "Stage 1 lifecycle proof is missing or not passed."
        source_error = _source_binding_error(
            payload.get("source_state"),
            source_state,
            label="Stage 1 lifecycle proof",
            require_clean=True,
        )
        if source_error:
            return source_error
        checks = payload.get("checks")
        if not isinstance(checks, list):
            return "Stage 1 lifecycle proof does not list lifecycle checks."
        expected_executed = {
            "clean-install",
            "first-run",
            "repair",
            "release-artifact-binding",
            "uninstall",
            "reinstall",
            "upgrade",
        }
        present_executed = {check.get("id") for check in checks if isinstance(check, dict)}
        if not expected_executed.issubset(present_executed):
            return "Stage 1 lifecycle proof is missing executed lifecycle checks."
        for check in checks:
            if not isinstance(check, dict):
                return "Stage 1 lifecycle proof contains an invalid check."
            if check.get("status") != "passed":
                return "Stage 1 lifecycle proof contains a blocked lifecycle check."
    if normalized == "gauntletgate-all":
        report_path = evidence if evidence.is_file() else evidence / "00-gate-report.md"
        try:
            text = report_path.read_text(encoding="utf-8")
        except OSError:
            return "GauntletGate all-lane report is missing."
        if "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0" not in text:
            return "GauntletGate all-lane report is not zeroed."
        if "Verdict: PASS" not in text:
            return "GauntletGate all-lane report does not declare a passing verdict."
        if "Lanes: lite, walkthrough, full" not in text:
            return "GauntletGate all-lane report does not declare all required lanes."
        if "Skipped/Waived Required Checks: none" not in text:
            return (
                "GauntletGate all-lane report does not rule out skipped or waived required checks."
            )
        head = source_state.get("head")
        if not isinstance(head, str) or not head:
            return "Current source head is unavailable for GauntletGate binding."
        if f"Source HEAD: {head}" not in text:
            return "GauntletGate all-lane report is not bound to the current source head."
        lowered = text.lower()
        if "do not advance" in lowered or "verdict: fail" in lowered:
            return "GauntletGate all-lane report includes a non-advancement verdict."
    return ""


def _full_stack_skip_ledger_error(summary: dict[str, Any], evidence: Path) -> str:
    pytest_logs = sorted(evidence.glob("*.log")) if evidence.is_dir() else []
    skipped_in_logs = False
    for log in pytest_logs:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "SKIPPED [" in text or " skipped" in text:
            skipped_in_logs = True
            break
    if not skipped_in_logs:
        return ""
    ledger = summary.get("skip_ledger")
    if not isinstance(ledger, dict):
        return "Full-stack evidence has pytest skips but no skip ledger."
    if ledger.get("status") not in {"none", "classified"}:
        return "Full-stack skip ledger has an invalid status."
    total_skipped = ledger.get("total_skipped")
    entries = ledger.get("entries")
    if skipped_in_logs and (total_skipped in {0, None} or not entries):
        return "Full-stack evidence has pytest skips that were not classified in the skip ledger."
    if ledger.get("required_skipped") not in {0, None}:
        return "Full-stack skip ledger contains required skipped checks."
    if total_skipped not in {0, None} and not isinstance(entries, list):
        return "Full-stack skip ledger does not list skipped checks."
    if isinstance(entries, list):
        entry_total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                return "Full-stack skip ledger contains an invalid entry."
            count = entry.get("count")
            if not isinstance(count, int) or count <= 0:
                return "Full-stack skip ledger entry has an invalid count."
            entry_total += count
            if entry.get("required_for_stage") is not False:
                return "Full-stack skip ledger contains an unclassified required skip."
            if not entry.get("classification") or not entry.get("equivalent_or_scope_evidence"):
                return "Full-stack skip ledger entry lacks classification or scope evidence."
        if isinstance(total_skipped, int) and entry_total != total_skipped:
            return "Full-stack skip ledger entries do not account for every skipped test."
    return ""


def _stage_3_3_required_label(check_id: str) -> str:
    labels = {
        "full-stack": "Full stack baseline",
        "release-identity": "Release identity policy",
        "first-run-attestation": "Isolated first-run attestation",
        "release-artifacts": "Release artifact build",
        "clean-windows-proof": "Clean Windows proof runner",
        "stage1-lifecycle-proof": "Stage 1 installer lifecycle proof",
        "gauntletgate-all": "GauntletGate all lanes",
    }
    return labels.get(check_id, check_id)


def _stage_3_3_required_key(check_id: str) -> str:
    normalized = check_id.replace("_", "-")
    aliases = {
        "full-stack-baseline": "full-stack",
    }
    return aliases.get(normalized, normalized)


def _stage_3_3_required_command(check_id: str) -> str:
    commands = {
        "full-stack": "powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1",
        "release-identity": "uv run python scripts/policy/check_release_identity.py",
        "first-run-attestation": "uv run python scripts/run_isolated_first_run_attestation.py",
        "release-artifacts": "uv run python scripts/build_release_artifacts.py",
        "clean-windows-proof": "uv run python scripts/run_clean_windows_install_proof.py",
        "stage1-lifecycle-proof": "uv run python scripts/run_stage1_lifecycle_proof.py",
        "gauntletgate-all": "gauntletgate all",
    }
    return commands.get(check_id, check_id)


def _stage_3_3_required_evidence(check_id: str) -> str:
    evidence = {
        "full-stack": "artifacts/test-runs/<run-id>",
        "release-identity": "artifacts/release/v3.3.0-stage1",
        "first-run-attestation": "artifacts/first-run/3.3-stage1-final",
        "release-artifacts": "artifacts/release/v3.3.0-stage1",
        "clean-windows-proof": "artifacts/clean-windows/3.3-stage1-final",
        "stage1-lifecycle-proof": (
            "artifacts/stage1-lifecycle/3.3-stage1-final/stage1-installer-lifecycle-proof.json"
        ),
        "gauntletgate-all": "artifacts/gauntletgate/<run-id>/00-gate-report.md",
    }
    return evidence.get(check_id, check_id)


def write_stage_report(
    *,
    stage_id: str,
    stage_name: str,
    repo_root: Path,
    artifact_root: Path,
    required_checks: list[StageCheck],
    clean_windows_evidence: Path,
    release_manifest: Path,
    source_state: dict[str, Any] | None = None,
) -> StageReport:
    """Write JSON and Markdown stage reports under ``artifact_root``."""

    report = build_stage_report(
        stage_id=stage_id,
        stage_name=stage_name,
        repo_root=repo_root,
        artifact_root=artifact_root,
        required_checks=required_checks,
        clean_windows_evidence=clean_windows_evidence,
        release_manifest=release_manifest,
        source_state=source_state,
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "stage-report.json").write_text(
        json.dumps(_report_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_root / "stage-report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _source_binding_error(
    evidence_source: object,
    current_source: dict[str, Any],
    *,
    label: str,
    require_clean: bool,
) -> str:
    if not isinstance(evidence_source, dict):
        return f"{label} is missing source-state binding."
    if require_clean and evidence_source.get("dirty") is not False:
        return f"{label} was not generated from a clean source state."
    current_head = current_source.get("head")
    if not isinstance(current_head, str) or not current_head:
        return f"Current source head is unavailable for {label} binding."
    if evidence_source.get("head") != current_head:
        return f"{label} is not bound to the current source head."
    for key in ("status_sha256", "diff_sha256", "untracked_content_sha256"):
        evidence_value = evidence_source.get(key)
        current_value = current_source.get(key)
        if evidence_value is None:
            return f"{label} is missing source-state {key} binding."
        if current_value is None:
            return f"Current source state is missing {key} for {label} binding."
        if evidence_value != current_value:
            return f"{label} source-state {key} does not match the current source state."
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_clean_windows_proof(
    path: Path,
    source_state: dict[str, Any],
    release_manifest: Path,
) -> EvidenceRef:
    payload = _read_json(path)
    if payload is None:
        return EvidenceRef("missing", str(path), "Clean Windows install proof JSON is missing.")
    source_error = _source_binding_error(
        payload.get("source_state"),
        source_state,
        label="Clean Windows proof",
        require_clean=True,
    )
    if source_error:
        return EvidenceRef("invalid", str(path), source_error)
    identity = payload.get("release_manifest_identity")
    if not isinstance(identity, dict):
        return EvidenceRef(
            "invalid",
            str(path),
            "Clean Windows proof is missing release-manifest identity binding.",
        )
    try:
        manifest_sha = _sha256(release_manifest)
    except OSError:
        return EvidenceRef("invalid", str(path), "Release manifest is unavailable.")
    if identity.get("sha256") != manifest_sha:
        return EvidenceRef(
            "invalid",
            str(path),
            "Clean Windows proof is not bound to the current release manifest.",
        )
    status = payload.get("status")
    if status == "passed" and _clean_windows_proof_semantics_pass(payload):
        return EvidenceRef("passed", str(path), "Native clean Windows installer proof passed.")
    if status == "passed":
        return EvidenceRef(
            "invalid",
            str(path),
            "Clean Windows proof lacks manifest-matched first-run setup evidence.",
        )
    if status == "partial":
        return EvidenceRef(
            "partial",
            str(path),
            "Runtime-only proof is recorded; native clean Windows installer proof is still required.",
        )
    if status == "blocked":
        return EvidenceRef("blocked", str(path), "Clean Windows proof is blocked by evidence.")
    return EvidenceRef("invalid", str(path), "Clean Windows proof JSON has no recognized status.")


def _read_release_manifest(path: Path, source_state: dict[str, Any]) -> EvidenceRef:
    payload = _read_json(path)
    if payload is None:
        return EvidenceRef("missing", str(path), "Release artifact manifest is missing.")
    version = payload.get("version")
    artifacts = payload.get("artifacts")
    if not (isinstance(version, str) and isinstance(artifacts, list) and artifacts):
        return EvidenceRef(
            "invalid",
            str(path),
            "Release artifact manifest lacks version or artifacts.",
        )
    source_error = _source_binding_error(
        payload.get("source_state"),
        source_state,
        label="Release artifact manifest",
        require_clean=True,
    )
    if source_error:
        return EvidenceRef("invalid", str(path), source_error)
    artifact_error = _release_manifest_artifact_error(path, artifacts)
    if artifact_error:
        return EvidenceRef("invalid", str(path), artifact_error)
    return EvidenceRef("passed", str(path), f"Release artifact manifest is present for {version}.")


def _release_manifest_artifact_error(path: Path, artifacts: list[Any]) -> str:
    manifest_dir = path.resolve().parent
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            return f"Release artifact manifest entry {index} is invalid."
        filename = artifact.get("filename")
        expected_size = artifact.get("size_bytes")
        expected_sha = artifact.get("sha256")
        if not isinstance(filename, str) or not filename:
            return f"Release artifact manifest entry {index} has no filename."
        if not isinstance(expected_size, int) or not isinstance(expected_sha, str):
            return f"Release artifact manifest entry {filename} lacks size or SHA-256."
        artifact_path = (manifest_dir / filename).resolve()
        try:
            artifact_path.relative_to(manifest_dir)
        except ValueError:
            return f"Release artifact manifest entry {filename} escapes the release directory."
        if not artifact_path.is_file():
            return f"Release artifact manifest entry {filename} is missing."
        if artifact_path.stat().st_size != expected_size:
            return f"Release artifact manifest entry {filename} has the wrong size."
        try:
            actual_sha = _sha256(artifact_path)
        except OSError:
            return f"Release artifact manifest entry {filename} could not be hashed."
        if actual_sha != expected_sha:
            return f"Release artifact manifest entry {filename} has the wrong SHA-256."
    return ""


def _clean_windows_proof_semantics_pass(payload: dict[str, Any]) -> bool:
    for attempt in payload.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("strategy") != "virtualbox-vm" or attempt.get("status") != "passed":
            continue
        try:
            stdout = json.loads(str(attempt.get("stdout", "{}")))
        except json.JSONDecodeError:
            return False
        return (
            stdout.get("manifest_match") is True
            and stdout.get("first_run_setup_path") is True
            and stdout.get("pending_reboot_clear") is True
            and stdout.get("report_fresh") is True
            and isinstance(stdout.get("report_sha256"), str)
            and bool(stdout.get("report_sha256"))
            and isinstance(stdout.get("snapshot"), str)
            and bool(stdout.get("snapshot"))
        )
    return False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _report_dict(report: StageReport) -> dict[str, Any]:
    return {
        "stage_id": report.stage_id,
        "stage_name": report.stage_name,
        "status": report.status,
        "generated_at_unix": report.generated_at_unix,
        "source_state": report.source_state,
        "release_manifest": asdict(report.release_manifest),
        "clean_windows_proof": asdict(report.clean_windows_proof),
        "required_checks": [asdict(check) for check in report.required_checks],
    }


def _render_markdown(report: StageReport) -> str:
    blocked = sum(1 for check in report.required_checks if check.status != "passed")
    lines = [
        f"# CivicCast Stage {report.stage_id} Report",
        "",
        f"Stage: {report.stage_name}",
        f"Status: `{report.status}`",
        f"Source branch: `{report.source_state.get('branch', '')}`",
        f"Source HEAD: `{report.source_state.get('head', '')}`",
        f"Dirty source: `{str(bool(report.source_state.get('dirty'))).lower()}`",
        "",
        "## Required Checks",
        "",
        f"{blocked} required checks blocked",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in report.required_checks:
        lines.append(f"| {check.label} | `{check.status}` | `{check.evidence}` |")
    lines.extend(
        [
            "",
            "## Required Evidence",
            "",
            f"- Release manifest: `{report.release_manifest.status}` - {report.release_manifest.path}",
            (
                f"- Clean Windows proof: `{report.clean_windows_proof.status}` - "
                f"{report.clean_windows_proof.path}"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_check(value: str) -> StageCheck:
    parts = value.split("|")
    if len(parts) < 5:
        raise argparse.ArgumentTypeError(
            "--check must be 'id|label|status|command|evidence[|notes]'"
        )
    status = parts[2]
    if status not in {"passed", "blocked", "failed", "skipped"}:
        raise argparse.ArgumentTypeError(f"invalid check status: {status}")
    return StageCheck(
        id=parts[0],
        label=parts[1],
        status=status,  # type: ignore[arg-type]
        command=parts[3],
        evidence=parts[4],
        notes=parts[5] if len(parts) > 5 else "",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--stage-name", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--clean-windows-evidence", type=Path, required=True)
    parser.add_argument("--check", action="append", type=_parse_check, default=[])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = write_stage_report(
        stage_id=args.stage_id,
        stage_name=args.stage_name,
        repo_root=args.repo_root,
        artifact_root=args.artifact_root,
        required_checks=args.check,
        clean_windows_evidence=args.clean_windows_evidence,
        release_manifest=args.release_manifest,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
