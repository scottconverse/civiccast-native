from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wait_native_uninstall_cleanup.ps1"

# These tests create real registry uninstall entries and invoke Windows
# PowerShell.  The Linux unit lane exercises the platform-independent suite;
# the Windows-native job is the execution proof for this module.
pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(sys.platform != "win32", reason="requires Windows registry and PowerShell"),
]


def _powershell(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _remove_test_arp(registry_root: str) -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-Command",
            f"Remove-Item -LiteralPath '{registry_root}' -Recurse -Force -ErrorAction SilentlyContinue",
        ],
        check=False,
    )


def _create_test_arp(registry_root: str) -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-Command",
            (
                f"New-Item -Path '{registry_root}\\entry' -Force | Out-Null; "
                f"Set-ItemProperty -Path '{registry_root}\\entry' "
                "-Name DisplayName -Value 'CivicCast (Native)'"
            ),
        ],
        check=True,
    )


def test_wait_succeeds_only_after_arp_and_install_root_disappear(tmp_path: Path) -> None:
    install_root = tmp_path / "CivicCast (Native)"
    install_root.mkdir()
    registry_root = rf"HKCU:\Software\CivicCastWaitTest\{uuid.uuid4()}"
    _create_test_arp(registry_root)

    def delayed_cleanup() -> None:
        time.sleep(0.35)
        install_root.rmdir()
        _remove_test_arp(registry_root)

    cleanup = threading.Thread(target=delayed_cleanup)
    cleanup.start()
    try:
        result = _powershell(
            "-InstallLocation",
            str(install_root),
            "-RegistryRoots",
            registry_root,
            "-TimeoutMilliseconds",
            "3000",
            "-PollMilliseconds",
            "50",
        )
    finally:
        cleanup.join()
        _remove_test_arp(registry_root)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "PASS"
    assert receipt["elapsed_ms"] >= 250
    assert receipt["final_arp_count"] == 0
    assert receipt["install_location_removed"] is True
    assert len(receipt["timeline"]) >= 2
    assert receipt["timeline"][0]["arp_count"] == 1
    assert receipt["timeline"][0]["install_location_exists"] is True


def test_wait_times_out_when_cleanup_never_completes(tmp_path: Path) -> None:
    install_root = tmp_path / "CivicCast (Native)"
    install_root.mkdir()
    registry_root = rf"HKCU:\Software\CivicCastWaitTest\{uuid.uuid4()}"
    _create_test_arp(registry_root)
    try:
        result = _powershell(
            "-InstallLocation",
            str(install_root),
            "-RegistryRoots",
            registry_root,
            "-TimeoutMilliseconds",
            "250",
            "-PollMilliseconds",
            "50",
        )
    finally:
        _remove_test_arp(registry_root)

    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "TIMEOUT"
    assert receipt["final_arp_count"] == 1
    assert receipt["install_location_removed"] is False


def test_wait_times_out_when_only_arp_remains(tmp_path: Path) -> None:
    registry_root = rf"HKCU:\Software\CivicCastWaitTest\{uuid.uuid4()}"
    _create_test_arp(registry_root)
    try:
        result = _powershell(
            "-InstallLocation",
            str(tmp_path / "already-removed"),
            "-RegistryRoots",
            registry_root,
            "-TimeoutMilliseconds",
            "250",
            "-PollMilliseconds",
            "50",
        )
    finally:
        _remove_test_arp(registry_root)

    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "TIMEOUT"
    assert receipt["final_arp_count"] == 1
    assert receipt["install_location_removed"] is True


def test_wait_times_out_when_only_install_root_remains(tmp_path: Path) -> None:
    install_root = tmp_path / "CivicCast (Native)"
    install_root.mkdir()
    registry_root = rf"HKCU:\Software\CivicCastWaitTest\{uuid.uuid4()}"

    result = _powershell(
        "-InstallLocation",
        str(install_root),
        "-RegistryRoots",
        registry_root,
        "-TimeoutMilliseconds",
        "250",
        "-PollMilliseconds",
        "50",
    )

    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "TIMEOUT"
    assert receipt["final_arp_count"] == 0
    assert receipt["install_location_removed"] is False


def test_default_roots_detect_standard_hkcu_arp_entry(tmp_path: Path) -> None:
    display_name = f"CivicCast Wait Test {uuid.uuid4()}"
    test_key = (
        rf"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
        rf"\CivicCastWaitTest-{uuid.uuid4()}"
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-Command",
            (
                f"New-Item -Path '{test_key}' -Force | Out-Null; "
                f"Set-ItemProperty -Path '{test_key}' "
                f"-Name DisplayName -Value '{display_name}'"
            ),
        ],
        check=True,
    )
    try:
        result = _powershell(
            "-InstallLocation",
            str(tmp_path / "already-removed"),
            "-DisplayName",
            display_name,
            "-TimeoutMilliseconds",
            "250",
            "-PollMilliseconds",
            "50",
        )
    finally:
        _remove_test_arp(test_key)

    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "TIMEOUT"
    assert receipt["final_arp_count"] >= 1
    assert receipt["install_location_removed"] is True
