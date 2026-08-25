# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Static contract tests for the Gate A PowerShell harness.

These do not run Windows Sandbox. They lock the small number of invariants
that, when they silently drifted, produced the three real Gate A stalls this
module was written alongside (see ``docs/ops/gate-a.md``, "Mapped-folder
stalls"):

1. **The in-sandbox driver never writes to the mapped folder.** All three
   stalls were a synchronous, timeout-less write to ``C:\\CivicCastOutput``
   from the one thread carrying the whole run. The driver now writes to a
   local directory and a separate shipper process mirrors it out.
2. **The three timeouts stay ordered.** The in-sandbox watchdog must fire
   before the host's poll deadline, or every long run degrades into an
   unexplained host timeout with no watchdog evidence. They live in three
   files, so a test is the only thing that keeps them consistent.
3. **The staleness watchdog arms on a sticky marker.** It previously armed by
   matching a momentary in-file value with a 30s poller and, on the run that
   mattered, never armed at all.
4. **The host's quiet-share marker filename matches the judge's registry.**
   The PowerShell side writes it; the Python judge keys ``HARNESS_ERROR``
   off it. One string, two languages.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_LAB = _REPO_ROOT / "sandbox-lab"
_DRIVER = _SANDBOX_LAB / "scripts" / "In-Sandbox-Report.ps1"
_HOST_LAUNCHER = _SANDBOX_LAB / "Host-Launch-Sandbox-Test.ps1"
_RUN_GATE_A = _SANDBOX_LAB / "Run-GateA.ps1"
_JUDGE = _REPO_ROOT / "scripts" / "gate_a_verdict.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "gate-a-station-acceptance.yml"

#: Matches a PowerShell single-quoted here-string body. The driver embeds the
#: watchdog, the shipper supervisor, and the shipper tick as here-strings;
#: those ARE allowed to touch the mapped folder (they are the separate,
#: disposable processes the design relies on), so they are stripped before
#: the driver's own executable text is inspected.
_HERE_STRING = re.compile(r"@'\r?\n.*?\r?\n'@", re.DOTALL)


def _load_judge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_a_verdict_contract", _JUDGE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _driver_executable_text() -> str:
    return _HERE_STRING.sub("\n<<here-string elided>>\n", _read(_DRIVER))


def _int_setting(text: str, pattern: str, label: str) -> int:
    match = re.search(pattern, text)
    assert match is not None, f"could not find {label} -- pattern {pattern!r} did not match"
    return int(match.group(1))


# --------------------------------------------------------------------------
# 1. The driver never writes to the mapped folder on its own thread
# --------------------------------------------------------------------------


def test_driver_out_dir_is_local_and_ship_dir_is_the_mapped_folder() -> None:
    text = _driver_executable_text()
    assert re.search(r"^\$ShipDir\s*=\s*'C:\\CivicCastOutput'", text, re.MULTILINE), (
        "the mapped folder must be bound to $ShipDir, not $OutDir"
    )
    assert re.search(r"^\$OutDir\s*=\s*'C:\\CivicCastLocalOut'", text, re.MULTILINE), (
        "$OutDir must be a local, VM-owned directory -- every step in the driver writes there"
    )


@pytest.mark.parametrize(
    "writer",
    ["Set-Content", "Add-Content", "Out-File", "Copy-Item", "Start-Transcript", "New-Item"],
)
def test_driver_never_writes_to_ship_dir_inline(writer: str) -> None:
    """No statement outside the shipper here-strings may write to $ShipDir.

    There are no exceptions. Windows Sandbox creates the MappedFolder mount
    before the LogonCommand runs and robocopy creates its own destination, so
    the driver never needs even a ``New-Item`` against the share.
    """
    offenders = [
        line.strip()
        for line in _driver_executable_text().splitlines()
        if writer in line and "$ShipDir" in line and not line.strip().startswith("#")
    ]
    assert offenders == [], (
        f"{writer} writes to the mapped folder from the driver's own thread: {offenders}"
    )


def test_driver_touches_ship_dir_only_through_bounded_child_processes() -> None:
    """The two places the driver itself reaches the share -- the one-time
    inbound seed and the final flush -- must both go through
    Invoke-BoundedProcess, which kills the child rather than waiting forever."""
    text = _driver_executable_text()
    assert "function Invoke-BoundedProcess" in text
    assert "Wait-Process -Id $p.Id -Timeout $TimeoutSeconds" in text
    bounded_calls = re.findall(r"Invoke-BoundedProcess", text)
    # definition + seed + final flush
    assert len(bounded_calls) >= 3, (
        f"expected the seed and the final flush to be bounded: {bounded_calls}"
    )


def test_driver_spawns_a_shipper_with_a_per_tick_child_process() -> None:
    text = _read(_DRIVER)
    assert "_SHIPPER_SPAWNED.marker" in text
    assert "_SHIPPER-HEARTBEAT.txt" in text, (
        "the shipper must emit a heartbeat -- it is what the host's quiet-share detector reads"
    )
    assert "civiccast-gate-a-ship-tick.ps1" in text
    # Additive mirror only: a purge would delete host-owned files in the
    # mapped folder (.gitkeep, SOAK_MINUTES.txt, HOST-QUIET-SHARE.txt).
    # Comment lines are excluded -- the design note explaining why /MIR is
    # wrong necessarily contains the string it forbids.
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    mir_lines = [ln.strip() for ln in code_lines if "/MIR" in ln]
    assert mir_lines == [], (
        f"the shipper must mirror additively (/E), never purge (/MIR): {mir_lines}"
    )
    assert any("robocopy.exe $LocalDir $ShipDir /E" in ln for ln in code_lines)


def test_shipper_delivers_done_json_last() -> None:
    """DONE.json must be excluded from the bulk mirror and copied on its own.

    Host-Launch-Sandbox-Test.ps1 polls for DONE.json every 10s and tears the
    VM down the moment it appears, so DONE.json's presence on the host has to
    mean "everything else already arrived". robocopy does not copy in write
    order, so without the exclusion a tick could hand the host a DONE.json
    ahead of evidence files that sort after it -- the same shape as the
    documented Watch-Run.ps1 race, moved one layer down.
    """
    code_lines = [
        ln for ln in _read(_DRIVER).splitlines() if not ln.strip().startswith("#") and ln.strip()
    ]
    mirror = [ln for ln in code_lines if "robocopy.exe $LocalDir $ShipDir" in ln]
    assert len(mirror) == 1, f"expected exactly one bulk mirror invocation, found {mirror}"
    assert "/XF DONE.json" in mirror[0], (
        "the bulk mirror must exclude DONE.json so it cannot arrive before the evidence"
    )
    assert any(
        "Copy-Item -LiteralPath $localDone" in ln and "$ShipDir" in ln for ln in code_lines
    ), "DONE.json must then be copied across on its own, after the mirror returns"


# --------------------------------------------------------------------------
# 2. Timeout ordering across the three files
# --------------------------------------------------------------------------


def test_timeout_budgets_are_ordered_watchdog_then_host() -> None:
    max_script_minutes = _int_setting(
        _driver_executable_text(),
        r"\[int\]\$MaxScriptMinutes\s*=\s*(\d+)",
        "In-Sandbox-Report.ps1 -MaxScriptMinutes default",
    )
    host_timeout = _int_setting(
        _read(_HOST_LAUNCHER),
        r"\[int\]\$TimeoutMinutes\s*=\s*(\d+)",
        "Host-Launch-Sandbox-Test.ps1 -TimeoutMinutes default",
    )
    run_gate_a_timeout = _int_setting(
        _read(_RUN_GATE_A),
        r"\[int\]\$TimeoutMinutes\s*=\s*(\d+)",
        "Run-GateA.ps1 -TimeoutMinutes default",
    )
    assert max_script_minutes == 150, (
        "run6 proved a healthy full run plus margin needs more than the old 100"
    )
    assert host_timeout > max_script_minutes, (
        f"host poll deadline ({host_timeout}m) must outlast the in-sandbox watchdog "
        f"({max_script_minutes}m) so the watchdog is always the first bound to fire"
    )
    assert run_gate_a_timeout == host_timeout, (
        "Run-GateA.ps1 passes -TimeoutMinutes straight through; the two defaults must agree"
    )

    # The CI workflow passes -TimeoutMinutes explicitly, which OVERRIDES both
    # defaults above -- a fourth copy of the same setting, and the one that
    # actually governs every gate run in CI. It was left at 150 when the
    # watchdog moved to 150, which would have made the host give up at
    # exactly the moment the watchdog was due to fire.
    workflow_timeout = _int_setting(
        _read(_WORKFLOW),
        r"Run-GateA\.ps1[^\r\n]*-TimeoutMinutes (\d+)",
        "gate-a-station-acceptance.yml -TimeoutMinutes argument",
    )
    assert workflow_timeout > max_script_minutes, (
        f"the CI workflow's -TimeoutMinutes ({workflow_timeout}m) must outlast the in-sandbox "
        f"watchdog ({max_script_minutes}m); it overrides the script defaults"
    )
    assert workflow_timeout == host_timeout, (
        "keep the workflow's explicit -TimeoutMinutes and the script defaults on the same number"
    )


def test_workflow_reports_a_harness_error_without_asserting_a_product_finding() -> None:
    text = _read(_WORKFLOW)
    assert "$verdict -eq 'HARNESS_ERROR'" in text, (
        "the workflow must handle the judge's HARNESS_ERROR verdict distinctly from a FAIL, "
        "the same way it already handles BUSY"
    )
    assert "$verdict -eq 'BUSY'" in text, "the pre-existing BUSY branch must survive"
    assert "NOT a candidate failure" in text


def test_host_quiet_share_bound_is_well_under_the_poll_deadline() -> None:
    text = _read(_HOST_LAUNCHER)
    quiet = _int_setting(
        text, r"\[int\]\$QuietShareMinutes\s*=\s*(\d+)", "-QuietShareMinutes default"
    )
    host_timeout = _int_setting(text, r"\[int\]\$TimeoutMinutes\s*=\s*(\d+)", "-TimeoutMinutes")
    assert 0 < quiet < host_timeout, (
        "a quiet-share bound at or above the poll deadline could never fire, which is the "
        "state run6 was effectively in"
    )


# --------------------------------------------------------------------------
# 3. The staleness watchdog arms on something a coarse poller cannot miss
# --------------------------------------------------------------------------


def test_verdict_stage_marker_is_written_by_the_driver_and_read_by_the_watchdog() -> None:
    text = _read(_DRIVER)
    assert "Write-Marker -Name '_VERDICT-STAGE.marker'" in text, (
        "the driver must drop a sticky arming marker at the station-up verdict"
    )
    assert "$verdictStageMarker = Join-Path $OutDir '_VERDICT-STAGE.marker'" in text
    assert "(Test-Path $verdictStageMarker) -or (Test-PostRuntimeVerdictStep" in text, (
        "arming must not depend solely on catching a momentary last_completed_step value"
    )


def test_summary_carries_a_monotonic_step_seq_the_watchdog_stalls_on() -> None:
    text = _read(_DRIVER)
    assert "step_seq                   = 0" in text
    assert "$summary.step_seq = [int]$summary.step_seq + 1" in text
    assert '$progress = "seq:$seq"' in text, (
        "the stall detector must key on the monotonic counter, not on step-name equality"
    )


def test_watchdog_reads_and_writes_the_local_dir_not_the_share() -> None:
    """The watchdog polled summary.json across the mapped folder. Had that read
    wedged instead of the main script's write, nothing would have fired at
    all -- so it now lives entirely on local storage."""
    text = _read(_DRIVER)
    assert re.search(
        r"'-OutDir',\s*\"`\"\$OutDir`\"\",\s*'-Minutes',\s*\$MaxScriptMinutes", text
    ), "the watchdog must be pointed at the LOCAL $OutDir"


# --------------------------------------------------------------------------
# 4. One marker filename, two languages
# --------------------------------------------------------------------------


def test_quiet_share_marker_filename_agrees_across_powershell_and_python() -> None:
    judge = _load_judge()
    (marker_name,) = [
        name for name in judge.HARNESS_ERROR_MARKERS if name == "HOST-QUIET-SHARE.txt"
    ]
    host_text = _read(_HOST_LAUNCHER)
    assert marker_name in host_text, (
        f"{marker_name} is what the judge keys HARNESS_ERROR off; the host launcher must write it"
    )
    # The quiet-share path needs its OWN exit code. 2 is the plain timeout
    # and 3 is already taken by the shared-sandbox busy guard ("never
    # launched"), which is a different condition from "launched and went
    # dark" -- two harness outcomes must not collide on one code.
    assert "exit 4" in host_text
    assert "exit 3" in host_text, "the busy guard's own exit code must survive"
    assert "SANDBOX-BUSY.txt" in host_text


def test_run_gate_a_maps_every_launcher_exit_code_to_a_harness_error() -> None:
    """Run-GateA collapses the launcher's finer codes into its own 2.

    Exit 3 (busy) has its own BUSY-verdict branch; everything else non-zero
    falls through to the generic harness-error path. Neither may reach the
    caller as a 1 (product FAIL).
    """
    text = _read(_RUN_GATE_A)
    assert "if ($launcherExit -eq 3) {" in text, "the BUSY branch must survive"
    assert "if ($launcherExit -eq 4) {" in text, (
        "the quiet-share branch must name itself before the generic fall-through"
    )
    assert "if ($launcherExit -ne 0) {" in text
    assert "-QuietShareMinutes $QuietShareMinutes" in text, (
        "the quiet-share bound must be reachable from the orchestrator, not only the launcher"
    )


def test_run_gate_a_reports_judge_exit_2_as_a_harness_error_not_a_fail() -> None:
    text = _read(_RUN_GATE_A)
    assert "elseif ($judgeExit -eq 2)" in text
    assert "HARNESS ERROR" in text
    assert "NOT a station-acceptance FAIL" in text
