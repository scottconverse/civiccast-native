#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Attempt or plan clean Windows install proof for the beta handoff."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from civiccast import __version__

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state

Status = Literal["planned", "available", "blocked", "passed"]
ProofStatus = Literal["planned", "blocked", "passed"]

ROOT = Path(__file__).resolve().parent.parent
MAX_VBOX_REPORT_AGE_SECONDS = 6 * 60 * 60
DEFAULT_EVIDENCE_DIR = ROOT / ".agent-runs" / "2026-05-21-beta-tester-handoff" / "evidence"
DEFAULT_RELEASE_MANIFEST = (
    ROOT / "artifacts" / "release" / f"civiccast-{__version__}-release-artifacts-manifest.json"
)


class CleanInstallAttempt(BaseModel):
    """One host command tried for clean Windows isolation."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal[
        "hyper-v-vm",
        "windows-sandbox",
        "virtualbox-vm",
    ]
    status: Status
    command: str = Field(min_length=1)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    blocker_evidence: str = ""


class CleanInstallProofResult(BaseModel):
    """Machine-readable clean install proof evidence."""

    model_config = ConfigDict(extra="forbid")

    status: ProofStatus
    dry_run: bool
    will_boot_vm: bool
    vm_booted: bool
    release_manifest: str | None = None
    release_manifest_identity: dict[str, object] | None = None
    source_state: dict[str, object] | None = None
    generated_at_unix: int
    attempts: list[CleanInstallAttempt]


def isolation_strategy_commands() -> list[tuple[str, str]]:
    """Return the ordered host checks required by the beta proof gate."""

    return [
        ("hyper-v-vm", "Get-VM -Name civiccast-beta-clean"),
        (
            "windows-sandbox",
            "Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM",
        ),
        (
            "virtualbox-vm",
            "VBoxManage list vms; target from CIVICAST_CLEANROOM_VBOX_VM or civiccast-v3-r6-cleanwin",
        ),
    ]


def plan_clean_windows_install_proof(
    *,
    release_manifest: Path,
    evidence_dir: Path,
    dry_run: bool,
) -> CleanInstallProofResult:
    """Plan the clean Windows install proof without provisioning a VM."""

    attempts = [
        CleanInstallAttempt(
            strategy=strategy,  # type: ignore[arg-type]
            status="blocked" if dry_run else "planned",
            command=command,
            blocker_evidence=(
                "dry-run records command provenance without booting or provisioning."
                if dry_run
                else ""
            ),
        )
        for strategy, command in isolation_strategy_commands()
    ]
    return CleanInstallProofResult(
        status="blocked" if dry_run else "planned",
        dry_run=dry_run,
        will_boot_vm=False,
        vm_booted=False,
        release_manifest=str(release_manifest),
        release_manifest_identity=_release_manifest_identity(release_manifest),
        source_state=collect_source_state(repo_root=ROOT),
        generated_at_unix=int(time.time()),
        attempts=attempts,
    )


def execute_clean_windows_install_proof(
    *,
    release_manifest: Path,
    evidence_dir: Path,
) -> CleanInstallProofResult:
    """Run ordered host capability checks and record blockers truthfully."""

    attempts = []
    for strategy, command in isolation_strategy_commands():
        if strategy == "virtualbox-vm":
            attempts.append(
                _run_virtualbox_vm_check(
                    os.environ.get("CIVICAST_CLEANROOM_VBOX_VM", "civiccast-v3-r6-cleanwin"),
                    release_manifest=release_manifest,
                )
            )
        else:
            attempts.append(_run_host_check(strategy, command))
    result = write_clean_windows_install_evidence(
        evidence_path=evidence_dir / "clean-windows-install.json",
        attempts=[attempt.model_dump(mode="json") for attempt in attempts],
        dry_run=False,
        release_manifest=release_manifest,
    )
    _write_markdown_evidence(evidence_dir / "clean-windows-install.md", result)
    return result


def _read_release_manifest(path: Path) -> dict[str, object]:
    loaded = _read_json_object(path)
    return loaded if isinstance(loaded, dict) else {}


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_manifest_identity(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    manifest = _read_release_manifest(path)
    try:
        manifest_hash = _sha256(path)
    except OSError:
        manifest_hash = ""
    source_state = manifest.get("source_state") if isinstance(manifest, dict) else None
    return {
        "path": str(path),
        "sha256": manifest_hash,
        "version": manifest.get("version"),
        "source_head": source_state.get("head") if isinstance(source_state, dict) else None,
    }


def _run_host_check(strategy: str, command: str) -> CleanInstallAttempt:
    powershell = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]
    try:
        proc = subprocess.run(
            powershell,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CleanInstallAttempt(
            strategy=strategy,  # type: ignore[arg-type]
            status="blocked",
            command=command,
            returncode=1,
            stderr=str(exc),
            blocker_evidence=str(exc),
        )
    stdout = _clean_output(proc.stdout)
    stderr = _clean_output(proc.stderr)
    if proc.returncode == 0:
        return CleanInstallAttempt(
            strategy=strategy,  # type: ignore[arg-type]
            status="available",
            command=command,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            blocker_evidence=(
                "Host capability command succeeded; no fresh isolated install was executed "
                "without a configured disposable target."
            ),
        )
    return CleanInstallAttempt(
        strategy=strategy,  # type: ignore[arg-type]
        status="blocked",
        command=command,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        blocker_evidence=stderr or stdout or "command returned non-zero status",
    )


def _run_virtualbox_vm_check(
    vm_name: str,
    *,
    release_manifest: Path | None = None,
) -> CleanInstallAttempt:
    explicit_report = os.environ.get("CIVICAST_CLEANROOM_VBOX_REPORT")
    if explicit_report:
        report_attempt = _read_virtualbox_vm_proof_report(
            Path(explicit_report),
            vm_name,
            release_manifest=release_manifest,
        )
        if report_attempt is not None:
            return report_attempt

    command = f"VBoxManage list vms # target {vm_name}"
    try:
        proc = subprocess.run(
            ["VBoxManage", "list", "vms"],
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CleanInstallAttempt(
            strategy="virtualbox-vm",
            status="blocked",
            command=command,
            returncode=1,
            stderr=str(exc),
            blocker_evidence=str(exc),
        )
    stdout = _clean_output(proc.stdout)
    stderr = _clean_output(proc.stderr)
    if proc.returncode != 0:
        return CleanInstallAttempt(
            strategy="virtualbox-vm",
            status="blocked",
            command=command,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            blocker_evidence=stderr or stdout or "VBoxManage list vms returned non-zero status",
        )
    if vm_name not in stdout:
        return CleanInstallAttempt(
            strategy="virtualbox-vm",
            status="blocked",
            command=command,
            returncode=0,
            stdout=stdout,
            stderr=stderr,
            blocker_evidence=f"VirtualBox target {vm_name} was not listed.",
        )
    return CleanInstallAttempt(
        strategy="virtualbox-vm",
        status="available",
        command=command,
        returncode=0,
        stdout=stdout,
        stderr=stderr,
        blocker_evidence=(
            "VirtualBox target is listed; no fresh isolated installer transcript was executed."
        ),
    )


def _read_virtualbox_vm_proof_report(
    path: Path,
    vm_name: str,
    *,
    release_manifest: Path | None = None,
) -> CleanInstallAttempt | None:
    payload = _read_json_object(path)
    command = f"read VirtualBox clean Windows proof report {path}"
    if payload is None:
        return CleanInstallAttempt(
            strategy="virtualbox-vm",
            status="blocked",
            command=command,
            returncode=1,
            blocker_evidence=f"VirtualBox proof report is missing or invalid: {path}",
        )

    installed_app = payload.get("installed_app")
    package = payload.get("package")
    status = payload.get("status")
    vm = payload.get("vm")
    version = payload.get("version")
    installer_exit_code = package.get("installer_exit_code") if isinstance(package, dict) else None
    product_version = (
        installed_app.get("product_version") if isinstance(installed_app, dict) else None
    )
    launch_started = (
        installed_app.get("launch_started") if isinstance(installed_app, dict) else None
    )
    manifest_match, manifest_blocker = _virtualbox_report_matches_release_manifest(
        payload,
        release_manifest,
    )
    reboot_clear, reboot_blocker = _virtualbox_report_has_no_pending_reboot(payload)
    freshness_ok, freshness_blocker, freshness = _virtualbox_report_freshness(path, payload)
    report_sha256 = ""
    try:
        report_sha256 = _sha256(path)
    except OSError:
        freshness_ok = False
        freshness_blocker = f"VirtualBox proof report could not be hashed: {path}"
    passed = (
        status == "passed_native_package_install_launch"
        and vm == vm_name
        and isinstance(payload.get("snapshot"), str)
        and bool(payload.get("snapshot"))
        and installer_exit_code == 0
        and product_version == version
        and launch_started is True
        and manifest_match
        and reboot_clear
        and freshness_ok
        and bool(report_sha256)
    )
    stdout = json.dumps(
        {
            "status": status,
            "version": version,
            "vm": vm,
            "snapshot": payload.get("snapshot"),
            "installer_exit_code": installer_exit_code,
            "product_version": product_version,
            "launch_started": launch_started,
            "manifest_match": manifest_match,
            "pending_reboot_clear": reboot_clear,
            "report_fresh": freshness_ok,
            "report_sha256": report_sha256,
            "report_generated_at": freshness.get("generated_at"),
            "report_age_seconds": freshness.get("age_seconds"),
            "report_mtime_unix": freshness.get("mtime_unix"),
        },
        sort_keys=True,
    )
    if passed:
        return CleanInstallAttempt(
            strategy="virtualbox-vm",
            status="passed",
            command=command,
            returncode=0,
            stdout=stdout,
            blocker_evidence="",
        )
    return CleanInstallAttempt(
        strategy="virtualbox-vm",
        status="blocked",
        command=command,
        returncode=1,
        stdout=stdout,
        blocker_evidence=(
            manifest_blocker
            or reboot_blocker
            or freshness_blocker
            or "VirtualBox proof report did not meet pass criteria."
        ),
    )


def _virtualbox_report_freshness(
    path: Path,
    payload: dict[str, object],
) -> tuple[bool, str, dict[str, object]]:
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return False, "VirtualBox proof report is missing generated_at.", {}
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return (
            False,
            "VirtualBox proof report generated_at is not parseable.",
            {
                "generated_at": generated_at,
            },
        )
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    age_seconds = abs((now - generated.astimezone(UTC)).total_seconds())
    try:
        mtime_unix = path.stat().st_mtime
    except OSError:
        return (
            False,
            "VirtualBox proof report mtime is unavailable.",
            {
                "generated_at": generated_at,
                "age_seconds": age_seconds,
            },
        )
    max_age = int(
        os.environ.get(
            "CIVICAST_CLEANROOM_VBOX_REPORT_MAX_AGE_SECONDS", str(MAX_VBOX_REPORT_AGE_SECONDS)
        )
    )
    if age_seconds > max_age:
        return (
            False,
            "VirtualBox proof report is stale.",
            {
                "generated_at": generated_at,
                "age_seconds": age_seconds,
                "mtime_unix": mtime_unix,
            },
        )
    if abs(time.time() - mtime_unix) > max_age:
        return (
            False,
            "VirtualBox proof report file mtime is stale.",
            {
                "generated_at": generated_at,
                "age_seconds": age_seconds,
                "mtime_unix": mtime_unix,
            },
        )
    return (
        True,
        "",
        {
            "generated_at": generated_at,
            "age_seconds": age_seconds,
            "mtime_unix": mtime_unix,
        },
    )


def _virtualbox_report_has_no_pending_reboot(payload: dict[str, object]) -> tuple[bool, str]:
    pending = payload.get("pending_reboot_keys")
    if not isinstance(pending, dict):
        return False, "VirtualBox proof report is missing pending reboot evidence."
    active = [key for key, value in pending.items() if value is True]
    if not active:
        return True, ""
    baseline = payload.get("pending_reboot_baseline")
    if _pending_reboot_is_scoped_snapshot_residue(baseline, pending):
        return True, ""
    if _pending_file_rename_is_edgeupdate_only(pending):
        return True, ""
    if active:
        return False, "VirtualBox proof report has pending reboot markers: " + ", ".join(active)
    return True, ""


def _pending_reboot_is_scoped_snapshot_residue(
    baseline: object,
    pending: dict[str, object],
) -> bool:
    if not isinstance(baseline, dict):
        return False
    if baseline != pending:
        return False
    return _pending_file_rename_is_edgeupdate_only(pending)


def _pending_file_rename_is_edgeupdate_only(pending: dict[str, object]) -> bool:
    active = [key for key, value in pending.items() if value is True]
    if active != ["pending_file_rename"]:
        return False
    operations = pending.get("pending_file_rename_operations")
    if not isinstance(operations, list) or not operations:
        return False
    concrete = [operation for operation in operations if isinstance(operation, str) and operation]
    return bool(concrete) and all("Microsoft\\EdgeUpdate" in operation for operation in concrete)


def _virtualbox_report_matches_release_manifest(
    payload: dict[str, object],
    release_manifest: Path | None,
) -> tuple[bool, str]:
    if release_manifest is None:
        return True, ""
    manifest = _read_release_manifest(release_manifest)
    acquisition = manifest.get("beta_handoff_acquisition")
    hashes = acquisition.get("hashes") if isinstance(acquisition, dict) else None
    if not isinstance(hashes, dict):
        return False, f"release manifest is missing artifact hashes: {release_manifest}"

    package = payload.get("package")
    if not isinstance(package, dict):
        return False, "VirtualBox proof report is missing package hashes."

    expected_version = manifest.get("version")
    actual_version = payload.get("version")
    expected_installer = hashes.get("windows_installer")
    actual_installer = package.get("installer_sha256")
    expected_proof_kit = hashes.get("clean_windows_proof_kit")
    actual_proof_kit = package.get("proof_kit_sha256")
    mismatches = []
    if expected_version != actual_version:
        mismatches.append(f"version {actual_version!r} != {expected_version!r}")
    if expected_installer != actual_installer:
        mismatches.append(f"installer_sha256 {actual_installer!r} != {expected_installer!r}")
    if expected_proof_kit != actual_proof_kit:
        mismatches.append(f"proof_kit_sha256 {actual_proof_kit!r} != {expected_proof_kit!r}")
    if mismatches:
        return False, (
            "VirtualBox proof report does not match release manifest: " + "; ".join(mismatches)
        )
    return True, ""


def _clean_output(value: str) -> str:
    return value.replace("\x00", "").strip()


def write_clean_windows_install_evidence(
    *,
    evidence_path: Path,
    attempts: list[dict[str, object]],
    dry_run: bool,
    release_manifest: Path | None = None,
) -> CleanInstallProofResult:
    """Write clean Windows install evidence JSON from attempted host commands."""

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_attempts = [CleanInstallAttempt.model_validate(attempt) for attempt in attempts]
    vm_booted = any(
        attempt.strategy in {"hyper-v-vm", "windows-sandbox", "virtualbox-vm"}
        and attempt.status == "passed"
        for attempt in parsed_attempts
    )
    status: ProofStatus = "passed" if vm_booted else "blocked"
    result = CleanInstallProofResult(
        status=status,
        dry_run=dry_run,
        will_boot_vm=False,
        vm_booted=vm_booted,
        release_manifest=str(release_manifest) if release_manifest else None,
        release_manifest_identity=_release_manifest_identity(release_manifest),
        source_state=collect_source_state(repo_root=ROOT),
        generated_at_unix=int(time.time()),
        attempts=parsed_attempts,
    )
    evidence_path.write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _write_markdown_evidence(path: Path, result: CleanInstallProofResult) -> None:
    version = _evidence_version(result)
    lines = [
        f"# v{version} clean Windows install proof" if version else "# Clean Windows install proof",
        "",
        f"Status: `{result.status}`",
        f"Dry run: `{str(result.dry_run).lower()}`",
        f"VM booted: `{str(result.vm_booted).lower()}`",
        f"Release manifest: `{result.release_manifest or 'not provided'}`",
    ]
    lines.extend(["", "## Attempts", ""])
    for attempt in result.attempts:
        blocker_evidence = _markdown_blocker_evidence(attempt.blocker_evidence)
        lines.extend(
            [
                f"### {attempt.strategy}",
                "",
                f"- Status: `{attempt.status}`",
                f"- Command: `{attempt.command}`",
                f"- Return code: `{attempt.returncode}`",
                f"- Blocker evidence: {blocker_evidence}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    while lines and not lines[-1]:
        lines.pop()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evidence_version(result: CleanInstallProofResult) -> str:
    if not result.release_manifest:
        return ""
    manifest = _read_release_manifest(Path(result.release_manifest))
    version = manifest.get("version")
    return version if isinstance(version, str) else ""


def _markdown_blocker_evidence(value: str) -> str:
    cleaned = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    return cleaned or "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="plan without booting targets")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run host capability commands and write blocked/pass evidence",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="directory for clean install evidence files",
    )
    parser.add_argument(
        "--release-manifest",
        type=Path,
        default=DEFAULT_RELEASE_MANIFEST,
        help="release artifact manifest used by the install attempt",
    )
    args = parser.parse_args(argv)

    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run are mutually exclusive")
    if not args.execute:
        result = plan_clean_windows_install_proof(
            release_manifest=args.release_manifest,
            evidence_dir=args.evidence_dir,
            dry_run=True,
        )
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = args.evidence_dir / "clean-windows-install.json"
        evidence_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _write_markdown_evidence(args.evidence_dir / "clean-windows-install.md", result)
    else:
        result = execute_clean_windows_install_proof(
            release_manifest=args.release_manifest,
            evidence_dir=args.evidence_dir,
        )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
