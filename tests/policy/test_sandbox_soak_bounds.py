# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = (ROOT / "sandbox-lab/Run-SandboxSoak.ps1").read_text(encoding="utf-8")
GUEST = (ROOT / "sandbox-lab/scripts/In-Sandbox-Soak.ps1").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "sandbox-lab/CivicCastSandboxSoak.wsb.template").read_text(encoding="utf-8")


def test_install_and_health_bounds_cross_host_template_and_guest() -> None:
    for name in ("INSTALL_BOUND_MINUTES", "HEALTH_BOUND_MINUTES"):
        parameter = "".join(part.title() for part in name.lower().split("_"))
        assert f"{{{{{name}}}}}" in TEMPLATE
        assert f"[regex]::Escape('{{{{{name}}}}}'), \"${parameter}\"" in HOST
    rendered = TEMPLATE.replace("{{INSTALL_BOUND_MINUTES}}", "45").replace(
        "{{HEALTH_BOUND_MINUTES}}", "17"
    )
    assert "-InstallBoundMinutes 45 -HealthBoundMinutes 17" in rendered
    assert "[ValidateRange(1, 180)][int]$InstallBoundMinutes = 20" in HOST
    assert "[ValidateRange(1, 180)][int]$HealthBoundMinutes = 10" in HOST
    assert "[ValidateRange(1, 180)][int]$InstallBoundMinutes = 20" in GUEST
    assert "[ValidateRange(1, 180)][int]$HealthBoundMinutes = 10" in GUEST


def test_hermetic_runner_contract_exercises_the_real_dry_run_renderer() -> None:
    contract = ROOT / "sandbox-lab/scripts/Test-SandboxSoakBounds.ps1"
    source = contract.read_text(encoding="utf-8")
    assert "[string]$SandboxRoot = ''" in source
    assert "& $hostRunner -Sha $sha -Root $harnessRoot -KitRoot $kitRoot -Minutes 15" in source
    assert "-InstallBoundMinutes 45 -HealthBoundMinutes 17 -DryRun" in source
    assert "-Filter 'CivicCastSandboxSoak-soak-*.wsb'" in source
    assert "guest body does not reset an install or health parameter after binding" in source
    assert "Assert-HostRejectsBoundBeforeFiles" in source
    assert "Assert-OwnedTemporaryTree" in source
