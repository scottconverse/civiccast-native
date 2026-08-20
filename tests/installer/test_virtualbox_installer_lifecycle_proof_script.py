# SPDX-License-Identifier: Apache-2.0
"""Contracts for the VirtualBox installer lifecycle proof runner."""

from pathlib import Path


def test_virtualbox_lifecycle_runner_restores_clean_snapshot_and_covers_lifecycle() -> None:
    script = Path("scripts/run_virtualbox_installer_lifecycle_proof.ps1").read_text(
        encoding="utf-8"
    )

    assert script.lstrip().startswith("# SPDX-License-Identifier: Apache-2.0\nparam(")
    assert "$guestScript = @'\nparam(" in script
    assert "snapshot" in script
    assert "restore" in script
    assert "clean-windows-base-20260602" in script
    assert "GuestAdditionsRunLevel=3" in script
    assert "cmd.exe /c ver" in script
    assert "guestcontrol" in script
    assert "Resolve-Path -LiteralPath $Source" in script
    assert "reinstall" in script
    assert "uninstall" in script
    assert "upgrade" in script
    assert "vbox-cleanwin-v2-final-lifecycle-proof-report.json" in script
    assert "ExpectedInstallerHash" in script
    assert "ExpectedProofKitHash" in script
    assert "retained_paths_policy" in script
    assert "Uninstall removes installed executables and registry entries" in script
