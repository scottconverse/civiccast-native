# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the clean Windows install proof runner."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

ISOLATION_STRATEGIES = {
    "hyper-v-vm",
    "windows-sandbox",
    "virtualbox-vm",
    "wsl2-fresh-distro",
    "wsl2-fresh-user",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TestCleanWindowsInstallProofContract:
    def test_dry_run_plan_records_all_isolation_strategies_without_booting_vm(
        self,
        tmp_path: Path,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        release_manifest = tmp_path / "civiccast-1.2.0-release-artifacts-manifest.json"
        release_manifest.write_text(
            json.dumps(
                {
                    "version": "1.2.0",
                    "beta_handoff_acquisition": {
                        "install_command": "python -m pip install --no-index --find-links wheelhouse wheelhouse/civiccast-1.2.0-py3-none-any.whl",
                    },
                    "artifacts": [],
                }
            ),
            encoding="utf-8",
        )

        plan = proof.plan_clean_windows_install_proof(
            release_manifest=release_manifest,
            evidence_dir=tmp_path / "evidence",
            dry_run=True,
        )

        payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
        assert payload["status"] in {"blocked", "planned"}
        assert payload["dry_run"] is True
        assert payload["will_boot_vm"] is False
        strategies = {attempt["strategy"] for attempt in payload["attempts"]}
        assert strategies >= ISOLATION_STRATEGIES
        for attempt in payload["attempts"]:
            assert attempt["command"]
            assert attempt["blocker_evidence"] or attempt["status"] == "available"

    def test_blocked_evidence_records_exact_host_commands_and_outputs(
        self,
        tmp_path: Path,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        evidence_path = tmp_path / "clean-windows-install.json"

        result = proof.write_clean_windows_install_evidence(
            evidence_path=evidence_path,
            attempts=[
                {
                    "strategy": "hyper-v-vm",
                    "status": "blocked",
                    "command": "Get-VM -Name civiccast-beta-clean",
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "Hyper-V module is not available",
                    "blocker_evidence": "Hyper-V module is not available",
                },
                {
                    "strategy": "virtualbox-vm",
                    "status": "blocked",
                    "command": "VBoxManage list vms",
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "VirtualBox target is locked",
                    "blocker_evidence": "VirtualBox target is locked",
                },
                {
                    "strategy": "windows-sandbox",
                    "status": "blocked",
                    "command": "Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM",
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "feature name unknown",
                    "blocker_evidence": "feature name unknown",
                },
            ],
            dry_run=True,
        )

        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert result.status == "blocked"
        assert payload["status"] == "blocked"
        assert payload["dry_run"] is True
        assert payload["vm_booted"] is False
        assert payload["attempts"][0]["command"] == "Get-VM -Name civiccast-beta-clean"
        assert payload["attempts"][0]["stderr"] == "Hyper-V module is not available"
        assert payload["attempts"][1]["strategy"] == "virtualbox-vm"

    def test_detects_installed_ubuntu_distro_without_hardcoded_name(
        self,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")

        class CompletedList:
            returncode = 0
            stdout = "Debian\nUbuntu-24.04\n"
            stderr = ""

        class CompletedPython:
            returncode = 0
            stdout = "3.12.3\n"
            stderr = ""

        calls = []

        def fake_run(*args, **kwargs):
            calls.append(args[0])
            if args[0][:3] == ["wsl.exe", "-d", "Ubuntu-24.04"]:
                return CompletedPython()
            return CompletedList()

        monkeypatch.setattr(proof.subprocess, "run", fake_run)

        distro, evidence = proof._detect_ubuntu_wsl_distro()

        assert distro == "Ubuntu-24.04"
        assert "Ubuntu-24.04" in evidence
        assert any(call[:3] == ["wsl.exe", "-d", "Ubuntu-24.04"] for call in calls)

    def test_rejects_ubuntu_distro_without_python312(self, monkeypatch) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")

        class CompletedList:
            returncode = 0
            stdout = "Ubuntu\n"
            stderr = ""

        class CompletedPython:
            returncode = 1
            stdout = "3.14.4\n"
            stderr = ""

        def fake_run(*args, **kwargs):
            if args[0][:3] == ["wsl.exe", "-d", "Ubuntu"]:
                return CompletedPython()
            return CompletedList()

        monkeypatch.setattr(proof.subprocess, "run", fake_run)

        distro, evidence = proof._detect_ubuntu_wsl_distro()

        assert distro is None
        assert "Python 3.12" in evidence
        assert "3.14.4" in evidence

    def test_markdown_evidence_uses_release_manifest_version(self, tmp_path: Path) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        release_manifest = tmp_path / "civiccast-1.3.0-release-artifacts-manifest.json"
        release_manifest.write_text(
            json.dumps({"version": "1.3.0", "artifacts": []}),
            encoding="utf-8",
        )
        evidence_path = tmp_path / "clean-windows-install.json"
        markdown_path = tmp_path / "clean-windows-install.md"

        result = proof.write_clean_windows_install_evidence(
            evidence_path=evidence_path,
            attempts=[
                {
                    "strategy": "wsl2-fresh-user",
                    "status": "passed",
                    "command": "wsl.exe -d Ubuntu-24.04 --exec bash -lc 'python -V'",
                    "returncode": 0,
                    "stdout": "1.3.0",
                    "stderr": "",
                    "blocker_evidence": "",
                }
            ],
            dry_run=False,
            release_manifest=release_manifest,
        )

        proof._write_markdown_evidence(markdown_path, result)

        assert result.status == "partial"
        assert markdown_path.read_text(encoding="utf-8").startswith(
            "# v1.3.0 clean Windows install proof"
        )
        assert (
            "native isolated Windows installer proof is still required"
            in markdown_path.read_text(encoding="utf-8")
        )

    def test_overall_pass_requires_booted_native_isolated_windows_target(
        self,
        tmp_path: Path,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        evidence_path = tmp_path / "clean-windows-install.json"

        result = proof.write_clean_windows_install_evidence(
            evidence_path=evidence_path,
            attempts=[
                {
                    "strategy": "windows-sandbox",
                    "status": "passed",
                    "command": "start sandbox and run installer transcript",
                    "returncode": 0,
                    "stdout": "dashboard opened",
                    "stderr": "",
                    "blocker_evidence": "",
                },
                {
                    "strategy": "wsl2-fresh-user",
                    "status": "passed",
                    "command": "wsl.exe -d Ubuntu-24.04 --exec bash -lc 'python -V'",
                    "returncode": 0,
                    "stdout": "1.3.0",
                    "stderr": "",
                    "blocker_evidence": "",
                },
            ],
            dry_run=False,
        )

        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert result.status == "passed"
        assert result.vm_booted is True
        assert payload["status"] == "passed"
        assert payload["vm_booted"] is True

    def test_virtualbox_probe_reports_available_target(self, monkeypatch) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        monkeypatch.delenv("CIVICAST_CLEANROOM_VBOX_REPORT", raising=False)
        monkeypatch.delenv("CIVICAST_CLEANROOM_VBOX_VM", raising=False)

        class Completed:
            returncode = 0
            stdout = '"civiccast-v3-r6-cleanwin" {8f87c443-4ad6-4125-8f4e-11617a07e210}\n'
            stderr = ""

        monkeypatch.setattr(proof.subprocess, "run", lambda *args, **kwargs: Completed())

        attempt = proof._run_virtualbox_vm_check("civiccast-v3-r6-cleanwin")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "available"
        assert "civiccast-v3-r6-cleanwin" in attempt.stdout

    def test_virtualbox_probe_accepts_explicit_passed_vm_report(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        report.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_keys": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": False,
                    },
                }
            ).encode("utf-8")
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "passed"
        assert attempt.returncode == 0
        assert str(report) in attempt.command
        assert "passed_native_package_install_launch" in attempt.stdout

    def test_virtualbox_probe_rejects_report_for_different_release_artifact(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        release_manifest = tmp_path / "civiccast-3.3.0-release-artifacts-manifest.json"
        release_manifest.write_text(
            json.dumps(
                {
                    "version": "3.3.0",
                    "beta_handoff_acquisition": {
                        "hashes": {
                            "windows_installer": "current-installer-sha",
                            "clean_windows_proof_kit": "current-proof-kit-sha",
                        }
                    },
                    "artifacts": [],
                }
            ),
            encoding="utf-8",
        )
        report = tmp_path / "post-proof-state.json"
        report.write_text(
            json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {
                        "proof_kit_sha256": "old-proof-kit-sha",
                        "installer_sha256": "old-installer-sha",
                        "installer_exit_code": 0,
                    },
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_keys": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check(
            "civiccast-cleanwin-v2",
            release_manifest=release_manifest,
        )

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "blocked"
        assert attempt.returncode == 1
        assert "does not match release manifest" in attempt.blocker_evidence

    def test_virtualbox_probe_rejects_report_with_pending_reboot(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        report.write_text(
            json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_keys": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "blocked"
        assert "pending reboot" in attempt.blocker_evidence

    def test_virtualbox_probe_accepts_unchanged_edgeupdate_pending_rename_residue(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        pending = {
            "cbs_reboot_pending": False,
            "windows_update_reboot_required": False,
            "pending_file_rename": True,
            "pending_file_rename_operations": [
                "*1\\??\\C:\\Program Files (x86)\\Microsoft\\EdgeUpdate\\1.3.237.7",
                "",
            ],
        }
        report.write_text(
            json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_baseline": pending,
                    "pending_reboot_keys": pending,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "passed"
        assert json.loads(attempt.stdout)["pending_reboot_clear"] is True

    def test_virtualbox_probe_accepts_edgeupdate_only_pending_rename_residue(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        report.write_text(
            json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_baseline": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": False,
                        "pending_file_rename_operations": [None],
                    },
                    "pending_reboot_keys": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": True,
                        "pending_file_rename_operations": [
                            "*1\\??\\C:\\Program Files (x86)\\Microsoft\\EdgeUpdate\\1.3.237.7",
                            "",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "passed"
        assert json.loads(attempt.stdout)["pending_reboot_clear"] is True

    def test_virtualbox_probe_rejects_report_without_first_run_setup_path(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        report.write_text(
            json.dumps(
                {
                    "generated_at": _now_iso(),
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "blocked"
        assert "first-run state" in attempt.blocker_evidence

    def test_virtualbox_probe_rejects_stale_explicit_report(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        proof = importlib.import_module("scripts.run_clean_windows_install_proof")
        report = tmp_path / "post-proof-state.json"
        report.write_text(
            json.dumps(
                {
                    "generated_at": "2020-01-01T00:00:00Z",
                    "status": "passed_native_package_install_launch",
                    "version": "3.3.0",
                    "vm": "civiccast-cleanwin-v2",
                    "snapshot": "clean-windows-base-20260602",
                    "package": {"installer_exit_code": 0},
                    "installed_app": {
                        "product_version": "3.3.0",
                        "launch_started": True,
                        "launch_still_running_after_15s": True,
                    },
                    "first_run_state": {
                        "installer_state_exists": True,
                        "installer_state": {
                            "current_lane_id": "wsl2",
                            "status": "blocked",
                            "message": "CivicCast needs the Windows helper before it can finish setup. Choose Set up Windows helper to continue.",
                            "reboot_required": False,
                        },
                        "expected_dependency_absent_action": "Choose Set up Windows helper",
                        "bootstrap_log_exists": False,
                    },
                    "pending_reboot_keys": {
                        "cbs_reboot_pending": False,
                        "windows_update_reboot_required": False,
                        "pending_file_rename": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CIVICAST_CLEANROOM_VBOX_REPORT", str(report))

        attempt = proof._run_virtualbox_vm_check("civiccast-cleanwin-v2")

        assert attempt.strategy == "virtualbox-vm"
        assert attempt.status == "blocked"
        assert "stale" in attempt.blocker_evidence


class TestCleanWindowsInstallProofCli:
    def test_script_exposes_dry_run_and_evidence_cli_options(self) -> None:
        script = Path("scripts/run_clean_windows_install_proof.py")

        assert script.exists()
        text = script.read_text(encoding="utf-8")
        assert "--dry-run" in text
        assert "--evidence-dir" in text
        assert "--release-manifest" in text
        assert "--execute" in text
