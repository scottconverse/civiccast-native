# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the rc17 uninstall/clean-probe residuals.

Two findings from the rc17 clean-host walkthrough, both non-blocking but both
capable of misleading someone:

F-5  The pre-uninstall hook writes a shutdown-request marker into the install
     directory to close the running app. The delete path removes $INSTDIR
     wholesale; the keep path removed nothing, so an empty CivicCast program
     folder survived an uninstall the operator watched succeed.

F-1  The clean-machine verifier trusted Win32_OptionalFeature, which reports
     the *configured* state. Between disabling WSL and the reboot that applies
     it, a fully working machine reports the feature absent -- so the tool
     could certify a dirty machine clean and let leftovers quietly assist an
     install that was supposed to prove itself from nothing.

Also pinned here: the silent (/S) uninstall leaves its "data kept" notice on
disk, because DetailPrint has no window to draw in during a silent run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NSIS_HOOKS = REPO_ROOT / "civiccast/apps/installer/src-tauri/nsis-hooks.nsh"


def _post_uninstall_branches() -> tuple[str, str]:
    """Return (delete_data_branch, keep_data_branch) of NSIS_HOOK_POSTUNINSTALL."""
    text = NSIS_HOOKS.read_text(encoding="utf-8")
    start = text.index("!macro NSIS_HOOK_POSTUNINSTALL")
    body = text[start : text.index("!macroend", start)]
    head, _, tail = body.partition("${Else}")
    keep = tail.split("${EndIf}")[0]
    delete = head.split("$DeleteAppDataCheckboxState = 1")[-1]
    return delete, keep


def test_keep_path_removes_the_shutdown_marker_it_wrote() -> None:
    _, keep = _post_uninstall_branches()
    assert 'Delete "$INSTDIR\\shutdown-request"' in keep, (
        "The keep-data uninstall path must delete the shutdown-request marker "
        "that NSIS_HOOK_PREUNINSTALL wrote into $INSTDIR, or an empty CivicCast "
        "program folder survives the uninstall."
    )


def test_keep_path_removes_the_now_empty_install_dir() -> None:
    _, keep = _post_uninstall_branches()
    assert 'RMDir "$INSTDIR"' in keep


def test_keep_path_never_recursively_deletes_the_install_dir() -> None:
    """Safety: only an *empty* $INSTDIR may go on the keep path.

    `RMDir /r` here would destroy anything an operator or another product left
    in the folder. Without /r the directory is removed only when it is empty,
    so a genuine leftover survives for diagnosis instead of being silently
    destroyed by an uninstall the operator asked to keep things.
    """
    _, keep = _post_uninstall_branches()
    rmdir_lines = [ln.strip() for ln in keep.splitlines() if ln.strip().startswith("RMDir")]
    assert rmdir_lines, "expected an RMDir on the keep path"
    for line in rmdir_lines:
        assert "/r" not in line, f"keep path must not recursively delete: {line}"


def test_delete_path_still_removes_everything() -> None:
    """The keep-path tidy-up must not have weakened the delete path."""
    delete, _ = _post_uninstall_branches()
    assert "--unregister CivicCast-Ubuntu-24.04" in delete
    assert 'RMDir /r /REBOOTOK "$INSTDIR"' in delete


def test_silent_uninstall_leaves_the_data_kept_notice_on_disk() -> None:
    """DetailPrint has no window during /S, so the notice must reach a file.

    A scripted uninstall otherwise finishes with no indication that the
    recordings and database -- roughly 19 GB -- were kept.
    """
    _, keep = _post_uninstall_branches()
    assert 'FileOpen $4 "$PROFILE\\.civiccast\\uninstall.log" w' in keep
    assert "KEPT" in keep
    assert "wsl --unregister CivicCast-Ubuntu-24.04" in keep, (
        "the on-disk notice must carry the removal command, not just say data was kept"
    )


@pytest.fixture(scope="module")
def verifier_script() -> str:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_release_artifacts as builder

    return builder._clean_windows_proof_verifier(
        "1.0.0-rc17", "CivicCast_1.0.0-rc17_x64-setup.exe", "0" * 64
    )


def test_clean_probe_corroborates_features_against_wsl_itself(verifier_script: str) -> None:
    assert "wsl.exe --status" in verifier_script, (
        "Win32_OptionalFeature alone reports configured state and reads stale "
        "before a reboot; the probe must ask wsl.exe whether it still responds."
    )
    assert "$wslStatusWorking = $true" in verifier_script


def test_a_responding_wsl_disqualifies_the_machine(verifier_script: str) -> None:
    """A working wsl.exe must flip the verdict, not merely be recorded."""
    assert "if ($wslStatusWorking) {" in verifier_script
    tail = verifier_script.split("if ($wslStatusWorking) {", 1)[1]
    assert "$requiredFeaturesAbsent = $false" in tail.split("}", 1)[0]


def test_clean_probe_records_the_corroboration_in_its_report(verifier_script: str) -> None:
    """The evidence file must show *why* a machine passed or failed."""
    assert "wsl_status_working = $wslStatusWorking" in verifier_script


def test_clean_probe_shields_native_stderr_from_powershell(verifier_script: str) -> None:
    """The documented NativeCommandError trap: `2>$null` does not suppress it.

    `wsl.exe --status` on a clean machine writes to stderr, which under
    ErrorActionPreference=Stop becomes terminating and would crash this tool on
    exactly the clean machines it exists to certify.
    """
    assert 'cmd.exe /c "wsl.exe --status 2>nul"' in verifier_script
