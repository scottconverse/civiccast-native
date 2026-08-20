"""Contracts for the Windows installer helper executable manifest."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_RS = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "build.rs"


def test_installer_helper_runs_as_invoker_to_avoid_uac_heuristics() -> None:
    """The helper name contains "installer", so the manifest must disable heuristics."""

    build_script = BUILD_RS.read_text(encoding="utf-8")

    assert "WindowsAttributes::new().app_manifest" in build_script
    assert 'requestedExecutionLevel level="asInvoker"' in build_script
    assert "requireAdministrator" not in build_script


def test_installer_helper_embeds_common_controls_v6_for_task_dialog() -> None:
    """TaskDialogIndirect is provided by Common Controls v6 on Windows."""

    build_script = BUILD_RS.read_text(encoding="utf-8")

    assert "Microsoft.Windows.Common-Controls" in build_script
    assert 'version="6.0.0.0"' in build_script
    assert 'publicKeyToken="6595b64144ccf1df"' in build_script
