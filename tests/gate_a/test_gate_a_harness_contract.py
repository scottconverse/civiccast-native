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

Gate A run 7 added three more (see ``docs/ops/gate-a.md``, "Run 7: what the
shipper cost the installer"):

5. **The shipper quiesces while the installer runs.** Every mapped folder in
   the VM shares one VSMB transport. A 25s shipper tick underneath a 21 GB
   install measured 1.6-4.2x slowdowns on exactly the installer steps that
   cross it, and the run's activation step failed.
6. **The quiesce interval stays well under the host's quiet-share bound**, or
   a healthy throttled run would be declared a dead channel.
7. **The finalization path is instrumented per statement.** Three separate
   runs stalled in the same handful of unlabelled statements, and none of the
   three post-mortems can name which one, because there was no step between
   them.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _find_repo_root(start: Path) -> Path:
    """Walk upward from ``start`` to the CivicCast repo root.

    A fixed ``parents[2]`` offset assumes this file always sits two
    directories below the repo root. That breaks under mutmut: the
    mutation-report job copies only the diff-scoped Python source (and a
    fixed ``also_copy`` list that does not include ``sandbox-lab``) into a
    ``mutants/`` directory, so ``mutants/tests/gate_a/<this file>`` has no
    ``sandbox-lab`` sibling at the depth the fixed offset expects --
    ``mutants/`` itself is nested inside the real checkout, though, so
    walking upward past it lands back on the real repo root, which does
    have ``sandbox-lab``. Recognise the root by a marker instead of a
    hardcoded depth: the presence of the PowerShell driver this module
    tests, falling back to ``.git`` for any other caller that lands here
    without ``sandbox-lab`` on disk at all.
    """
    for candidate in (start, *start.parents):
        if (candidate / "sandbox-lab" / "scripts" / "In-Sandbox-Report.ps1").is_file():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        f"could not locate the CivicCast repo root by walking up from {start} -- "
        "expected to find sandbox-lab/scripts/In-Sandbox-Report.ps1 or a .git marker"
    )


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
_SANDBOX_LAB = _REPO_ROOT / "sandbox-lab"
_DRIVER = _SANDBOX_LAB / "scripts" / "In-Sandbox-Report.ps1"
_HOST_LAUNCHER = _SANDBOX_LAB / "Host-Launch-Sandbox-Test.ps1"
_RUN_GATE_A = _SANDBOX_LAB / "Run-GateA.ps1"
_JUDGE = _REPO_ROOT / "scripts" / "gate_a_verdict.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "gate-a-station-acceptance.yml"
_WSB_TEMPLATE = _SANDBOX_LAB / "CivicCastSandboxTest.wsb.template"
_UPGRADE_BASELINE = _SANDBOX_LAB / "upgrade-baseline.json"

#: Matches a PowerShell single-quoted here-string body. The driver embeds the
#: watchdog, the shipper supervisor, and the shipper tick as here-strings;
#: those ARE allowed to touch the mapped folder (they are the separate,
#: disposable processes the design relies on), so they are stripped before
#: the driver's own executable text is inspected.
_HERE_STRING = re.compile(r"@'\r?\n.*?\r?\n'@", re.DOTALL)

#: The installer LAUNCH, not the ``silent_flag_used`` assignment that carries
#: the same literal a few lines earlier. Anchoring on the bare flag string
#: silently matched the assignment and inverted an ordering assertion.
_INSTALLER_LAUNCH = "Start-Process -FilePath $exe.FullName"


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


def _code_only(text: str) -> str:
    """Drop whole-line ``#`` comments.

    Every design note in this harness necessarily quotes the construct it
    forbids ("never use /MIR", "never use a unary-comma array", "the quiesce
    is no longer lifted here"), so a naive substring assertion matches the
    warning instead of the violation. Three tests in this file have been
    written wrong that way; strip comments first.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


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


# --------------------------------------------------------------------------
# 5-7. Run 7: the shipper must get out of the installer's way, and the
#      finalization path must name its own statements
# --------------------------------------------------------------------------


def test_shipper_quiesces_around_the_installer() -> None:
    """The driver must raise the quiesce marker before the installer.

    SUPERSEDED IN PART by <gate-a-hoststore-wedge>: this test used to also
    require ``Exit-ShipperQuiesce`` inside a ``finally`` attached to the
    install itself. That contract was wrong -- lifting there put the 25s tick
    back underneath the post-install hoststore reads. The lift point moved to
    the station-up wait and is asserted by
    ``test_quiesce_spans_the_post_install_discovery_not_just_the_installer``.
    What survives here is the half that is still true: the quiesce is raised
    before the installer, and the marker's expiry is what covers a lift that
    never happens.
    """
    text = _read(_DRIVER)
    assert "function Enter-ShipperQuiesce" in text
    assert "function Exit-ShipperQuiesce" in text
    code = _code_only(text)
    enter = code.index("Enter-ShipperQuiesce -Reason")
    installer = code.index(_INSTALLER_LAUNCH)
    assert enter < installer, "the quiesce must be raised before the installer is launched"


def test_quiesce_marker_carries_a_self_healing_expiry() -> None:
    """A marker the driver never gets to remove must stop mattering by itself.

    The failure mode of a lost removal has to be "shipping speeds back up",
    never "shipping stays throttled and the host declares a dead channel".
    """
    text = _read(_DRIVER)
    assert "quiesce_until_utc=" in text
    assert "function Get-EffectiveInterval" in text, (
        "the shipper supervisor must decide its interval from the marker, expiry included"
    )
    fn = text[text.index("function Get-EffectiveInterval") :][:1400]
    assert "quiesce_until_utc=(\\S+)" in fn
    assert "return $Fast" in fn, (
        "every failure path in the interval decision must fall back to fast"
    )


def test_quiesce_interval_stays_inside_the_host_quiet_share_bound() -> None:
    driver = _driver_executable_text()
    quiesce_seconds = _int_setting(
        driver,
        r"\[int\]\$ShipQuiesceIntervalSeconds\s*=\s*(\d+)",
        "In-Sandbox-Report.ps1 -ShipQuiesceIntervalSeconds default",
    )
    ship_seconds = _int_setting(
        driver,
        r"\[int\]\$ShipIntervalSeconds\s*=\s*(\d+)",
        "In-Sandbox-Report.ps1 -ShipIntervalSeconds default",
    )
    quiet_minutes = _int_setting(
        _read(_HOST_LAUNCHER),
        r"\[int\]\$QuietShareMinutes\s*=\s*(\d+)",
        "Host-Launch-Sandbox-Test.ps1 -QuietShareMinutes default",
    )
    assert quiesce_seconds > ship_seconds, "the quiesce interval must actually be slower"
    # Two full quiesced ticks must still fit inside the quiet-share bound, so
    # one missed tick cannot trip the host's dead-channel detector.
    assert quiesce_seconds * 2 < quiet_minutes * 60, (
        f"a quiesced heartbeat every {quiesce_seconds}s must leave room inside the host's "
        f"{quiet_minutes}-minute quiet-share bound even if one tick is missed"
    )


def test_install_progress_capture_is_relocated_out_of_the_finalization_path() -> None:
    text = _read(_DRIVER)
    assert "function Invoke-InstallProgressCapture" in text
    # Primary call site: right after the installer, before the grace sleep.
    assert "Invoke-InstallProgressCapture -Phase 'post-install'" in text
    # Secondary, guarded call site in the finalization block.
    assert "Invoke-InstallProgressCapture -Phase 'finalization'" in text
    post_install = text.index("Invoke-InstallProgressCapture -Phase 'post-install'")
    finalization = text.index("Invoke-InstallProgressCapture -Phase 'finalization'")
    assert post_install < finalization, "the post-install capture must come first"
    assert "$script:InstallProgressCaptured" in text, (
        "the finalization call must be able to no-op when the post-install capture succeeded"
    )
    # The old shape -- copy the file, then immediately read the copy back with
    # -Tail on the Sandbox's differencing disk -- is what three runs died
    # near. It must not come back.
    assert "-Tail 80" not in text, (
        "the read-after-write tail on the just-copied file is retired; read the source once "
        "and slice the tail in memory"
    )


def test_finalization_statements_each_record_their_own_step() -> None:
    """Runs 4, 6 and 7 all stalled between two Save-Summary calls with three
    or four bare statements between them, so no post-mortem can name the
    operation. Every one of those statements now has a step."""
    text = _read(_DRIVER)
    for step in (
        "install-progress-probe-begin-",
        "install-progress-probed-",
        "install-progress-sized-",
        "install-progress-read-",
        "install-progress-copied-",
        "install-progress-captured-",
        "transcript-flushed-pre-finalization",
        "event-log-query-begin",
        "final-diag-begin",
        "final-diag-captured",
    ):
        assert step in text, f"missing finalization instrumentation step: {step}"


def test_watchdog_arming_predicate_recognises_the_new_step_names() -> None:
    """The sticky marker is the primary arming path, but the redundant
    step-name predicate must not silently stop covering the finalization
    steps just because they were renamed."""
    text = _read(_DRIVER)
    predicate = text[text.index("function Test-PostRuntimeVerdictStep") :][:1600]
    for pattern in (
        "'install-progress*'",
        "'transcript-flushed*'",
        "'event-log-*'",
        "'final-diag-*'",
    ):
        assert pattern in predicate, f"arming predicate no longer covers {pattern}"


def test_transcript_is_flushed_at_checkpoints() -> None:
    """PS 5.1 buffers transcripts in user space and only flushes on
    Stop-Transcript. Any run that ends via the watchdog never reaches it, so
    run7 shipped a 686-byte header-only transcript. Checkpoint flushes are
    the fix."""
    text = _read(_DRIVER)
    assert "function Sync-Transcript" in text
    assert "Start-Transcript -Path (Join-Path $OutDir 'sandbox-transcript.log') -Append" in text
    for checkpoint in ("post-install", "station-up-verdict", "pre-finalization"):
        assert f"Sync-Transcript -Checkpoint '{checkpoint}'" in text, (
            f"missing transcript flush checkpoint: {checkpoint}"
        )


def test_mapped_folders_are_resolved_to_physical_paths_before_the_wsb_is_written() -> None:
    text = _read(_HOST_LAUNCHER)
    assert "function Resolve-PhysicalPath" in text
    assert "<HostFolder>$physical</HostFolder>" in text, (
        "the rendered .wsb must carry the physical directory, not a junction chain"
    )
    # A MatchEvaluator scriptblock is not something a PS 5.1-only script
    # should rely on; the substitution is an explicit loop.
    assert "$mappedRx.Replace(" not in text
    assert "$mappedRx.Matches($rendered)" in text


def test_run_gate_a_junctions_kit_download_at_the_physical_kit() -> None:
    text = _read(_RUN_GATE_A)
    assert "New-Item -ItemType Junction -Path $kitDownload -Target $kitPhysicalDir" in text, (
        "kit-download must point at the physical kit, not at another junction"
    )
    assert "$kitPhysicalDir = $kitSourceDir" in text
    assert "Station bundle inventory:" in text, (
        "run7's installer failed on 'station-index.json AND ITS PACKS'; the pre-launch log has "
        "to record what was actually in the bundle directory, not just that the index existed"
    )


# --------------------------------------------------------------------------
# 8-10. The hoststore wedge: C:\CivicCastHostStore is a mapped folder AND the
#       install target, and the driver still read it synchronously
# --------------------------------------------------------------------------


def test_quiesce_spans_the_post_install_discovery_not_just_the_installer() -> None:
    """The quiesce used to be lifted in a `finally` on the install itself,
    which put the 25s tick back underneath the post-install phase -- and that
    phase reads C:\\CivicCastHostStore (10,683 files) for install-dir
    discovery, the tree listing, Test-KnownPaths and the service checks. It is
    now lifted at the station-up wait, which is HTTP-bound.
    """
    text = _read(_DRIVER)
    assert "Enter-ShipperQuiesce -Reason 'installer-and-post-install-discovery'" in text
    assert "Save-Summary -Step 'shipper-unquiesced-at-station-up-wait'" in text, (
        "the lift point must be instrumented, so evidence shows when shipping resumed"
    )
    enter = text.index("Enter-ShipperQuiesce -Reason 'installer-and-post-install-discovery'")
    lift = text.index("Save-Summary -Step 'shipper-unquiesced-at-station-up-wait'")
    assert enter < lift, "the quiesce must be raised before it is lifted"
    # The old install-scoped lift must be gone: no Exit-ShipperQuiesce may sit
    # between the installer's Start-Process and _AFTER_INSTALL.marker.
    code = _code_only(text)
    install_window = code[code.index(_INSTALLER_LAUNCH) :]
    install_window = install_window[: install_window.index("_AFTER_INSTALL.marker")]
    assert "Exit-ShipperQuiesce" not in install_window, (
        "lifting the quiesce when the installer returns re-exposes the post-install phase"
    )


def test_bounded_probe_exists_and_times_out_rather_than_waiting() -> None:
    text = _read(_DRIVER)
    assert "function Invoke-BoundedProbe" in text
    fn = text[text.index("function Invoke-BoundedProbe") :][:2600]
    assert "Invoke-BoundedProcess" in fn, "the probe must run in a child with a hard timeout"
    assert "if (-not $run.completed)" in fn and "return $null" in fn, (
        "a probe that times out must return null and record it, never block the caller"
    )


@pytest.mark.parametrize(
    "probe_name",
    ["known-paths:$FileName", "install-tree-top-levels", "diag-station-markers:$Label"],
)
def test_every_hoststore_read_goes_through_a_bounded_probe(probe_name: str) -> None:
    """The three remaining synchronous readers of C:\\CivicCastHostStore."""
    text = _read(_DRIVER)
    assert f'-Name "{probe_name}"' in text or f"-Name '{probe_name}'" in text, (
        f"hoststore read '{probe_name}' is not routed through Invoke-BoundedProbe"
    )


def test_probe_results_use_a_named_envelope_not_a_unary_comma_array() -> None:
    """Windows PowerShell 5.1's ConvertTo-Json turns ``(, @(...))`` into
    ``{"value":[...],"Count":n}`` -- an object, not a JSON array -- so every
    probe caller would receive one wrapper instead of its list. Found by the
    host-side probe smoke test, not by reading the code.
    """
    text = _read(_DRIVER)
    probe_bodies = re.findall(r"-ScriptText @'\r?\n(.*?)\r?\n'@", text, re.DOTALL)
    assert probe_bodies, "no bounded-probe script bodies found"
    for body in probe_bodies:
        code = _code_only(body)
        assert "(, " not in code, (
            "probe results must use @{ items = @(...) }, never a unary-comma array"
        )
        assert "@{ items = @(" in code and "$ResultPath" in code, (
            "every probe must write a named-envelope result to $ResultPath"
        )


def test_watchdog_records_whether_the_driver_process_is_still_alive() -> None:
    """Four runs have ended with 'last step written, nothing after, other
    processes healthy' -- a signature identical whether the driver's thread
    blocked or its process died. This is the observation that separates them,
    and it can only be made while the VM still exists."""
    text = _read(_DRIVER)
    assert "_DRIVER-PID.txt" in text, "the driver must record its own PID for the watchdog"
    assert "function Get-DriverLiveness" in text
    assert "driver_process_alive=true" in text and "driver_process_alive=false" in text
    assert "'-DriverPid', $PID" in text, "the watchdog must be told which PID to watch"
    # Both watchdog triggers must carry it, not just one.
    assert text.count("Get-DriverLiveness -DriverPid $DriverPid") >= 2, (
        "both the staleness trigger and the overall-deadline trigger must record liveness"
    )
    assert "driver_liveness      = $liveness" in text, (
        "the placeholder DONE.json must carry it too, so the judge's evidence has it"
    )


def test_stale_quiesce_marker_is_retracted_from_the_host() -> None:
    """The mirror is additive, so a marker shipped during the quiesce window
    outlived the driver's local removal and told a reader the run was still
    quiesced when it was not."""
    text = _read(_DRIVER)
    retraction = text[text.index("foreach ($name in @('WATCHDOG-TIMEOUT.txt'") :][:400]
    assert "'_SHIPPER-QUIESCE.marker'" in retraction


def test_local_install_target_alternative_is_documented_as_rejected() -> None:
    """The tidier-sounding fix -- move the install target off the mapped
    folder -- is not viable, and the reason must stay written down where the
    next person will look before re-proposing it."""
    text = _read(_DRIVER)
    assert "C:\\CivicCastLocalInstall" in text, (
        "name the rejected alternative explicitly so it is searchable"
    )
    assert "os error 112" in text, "cite the recorded reason it fails (virtual disk exhaustion)"
    assert "REFUSES junction/symlink install-roots" in text, "cite the second closed dodge"


# --------------------------------------------------------------------------
# 11-13. The summary-JSON explosion
#
# Five runs (4, 6, 7, and both candidate-#11 runs) stopped at the first
# Save-Summary after install_progress_log_tail was assigned. The liveness
# instrument answered it: driver alive, CPU-hot, 8.3 GB resident. Get-Content
# emits strings decorated with PSProvider/PSDrive note properties whose object
# graph contains a cycle, and ConvertTo-Json -Depth 8 walks it. Measured: ONE
# such line costs 98 MB of JSON at depth 7 and never finishes at depth 8.
# --------------------------------------------------------------------------


def test_get_content_results_are_cast_to_plain_strings_at_the_source() -> None:
    text = _read(_DRIVER)
    assert "$lines = [string[]]@(Get-Content -LiteralPath $progressLog" in text, (
        "the install-progress read must strip PSObject decoration at the source"
    )
    assert "$summary.install_progress_log_tail = [string[]]@(" in text, (
        "the summary member must be a plain string array"
    )


def test_summary_is_sanitized_before_serialization() -> None:
    text = _read(_DRIVER)
    assert "function ConvertTo-PlainForSummary" in text
    save = text[text.index("function Save-Summary") :][:900]
    assert "ConvertTo-PlainForSummary -Value $summary" in save, (
        "Save-Summary must sanitize before it serializes -- the source-site cast alone "
        "protects only the one member we already know about"
    )


def test_summary_json_depth_is_bounded() -> None:
    """Depth is a blast-radius multiplier for this bug class, not a
    formatting preference. The deepest real member is install_tree_top_levels
    (summary -> array -> entry -> children -> string = 5)."""
    text = _read(_DRIVER)
    depth = _int_setting(
        text, r"\$script:SummaryJsonDepth\s*=\s*(\d+)", "Save-Summary ConvertTo-Json depth"
    )
    assert 5 <= depth <= 6, f"summary serialization depth {depth} is outside the justified range"
    code = _code_only(text)
    assert "$summary | ConvertTo-Json -Depth 8" not in code, (
        "the unsanitized depth-8 serialization of $summary is what exploded; it must not return"
    )
    assert "ConvertTo-Json -Depth $script:SummaryJsonDepth" in code


def test_sanitizer_avoids_the_ps51_generic_list_trap() -> None:
    """`@($list)` over a System.Collections.Generic.List[object] throws
    "Argument types do not match" in Windows PowerShell 5.1, which silently
    degraded every array member of the summary into one space-joined string.
    Caught by the host-side sanitizer test, not by reading the code."""
    text = _read(_DRIVER)
    fn = text[text.index("function ConvertTo-PlainForSummary") :]
    fn = fn[: fn.index("\nfunction ")]
    code = _code_only(fn)
    assert "System.Collections.ArrayList" in code
    assert "System.Collections.Generic.List[object]" not in code, (
        "the generic List is the shape that throws under @() in PS 5.1"
    )
    assert "return , ($out.ToArray())" in code, (
        "the leading comma keeps a single-element array an ARRAY in summary.json -- the judge "
        "counts those fields"
    )
    # It must render unknown objects rather than walking them; that single
    # line is what makes a cyclic graph impossible to expand.
    assert "return [string]$Value" in code


def test_watchdog_forensics_run_only_when_the_driver_is_alive() -> None:
    text = _read(_DRIVER)
    assert "function Get-DriverForensics" in text
    # Both triggers, and both gated on liveness.
    assert text.count("Get-DriverForensics -DriverPid $DriverPid") == 2, (
        "both the staleness trigger and the overall-deadline trigger must collect forensics"
    )
    assert text.count("if ($liveness -like '*driver_process_alive=true*')") == 2, (
        "a dead driver has nothing to sample or dump -- do not pay for it"
    )


# --------------------------------------------------------------------------
# 14-17. The teardown drain: run 32926056071's VM outlived job SUCCESS and
#         run 32929704614's Checkout hit EBUSY a minute later
# --------------------------------------------------------------------------


def test_host_launcher_drains_teardown_only_on_the_normal_completion_path() -> None:
    """The drain must sit after step 5 (Stop-Process) and be reachable only
    through $launchedPids.Count -gt 0 -- the same condition step 5's own
    teardown guard already uses. The busy guard (exit 3), the quiet-share
    detector (exit 4), and the plain timeout (exit 2) must all appear BEFORE
    the drain block in the file, since PowerShell runs top-to-bottom and each
    of those is a hard `exit` -- textual ordering is what makes the drain
    unreachable on any of those three paths."""
    text = _read(_HOST_LAUNCHER)
    assert "function Test-DirectoryHandlesFree" in text
    assert "if ($launchedPids.Count -gt 0) {" in text
    drain_idx = text.index("Draining sandbox teardown")
    assert text.index("exit 3") < drain_idx, "the busy guard must exit before the drain block"
    assert text.index("exit 4") < drain_idx, (
        "the quiet-share detector must exit before the drain block"
    )
    assert text.index("exit 2") < drain_idx, "the plain timeout must exit before the drain block"
    assert text.index("Stopping this run's own sandbox process(es)") < drain_idx, (
        "the drain must run after Stop-Process, not before"
    )


def test_teardown_drain_probe_renames_the_directory_not_a_file_inside_it() -> None:
    """A write-inside-the-folder probe would miss a handle held on a
    READ-ONLY mapped folder (e.g. sandbox-lab/scripts, ReadOnly=true in the
    .wsb template) since the guest never writes there -- only a probe on the
    directory object itself, the same rmdir/rename Checkout's workspace
    clean performs, reproduces run 32929704614's actual failure."""
    text = _read(_HOST_LAUNCHER)
    fn = text[text.index("function Test-DirectoryHandlesFree") :][:2200]
    assert "Rename-Item -LiteralPath $Path -NewName $probeLeaf" in fn
    assert "Rename-Item -LiteralPath $probePath -NewName $leaf" in fn


def test_teardown_drain_probes_the_runs_own_mapped_folders() -> None:
    text = _read(_HOST_LAUNCHER)
    assert "$mappedHostFolders = @($mappedRx.Matches($rendered)" in text, (
        "the drain must probe the exact folders VSMB shared into THIS run's VM, "
        "read back from the rendered .wsb rather than a hardcoded list"
    )
    drain_fn_area = text[text.index("Draining sandbox teardown") :][:2200]
    assert "foreach ($folder in $mappedHostFolders)" in drain_fn_area
    assert "Test-DirectoryHandlesFree -Path $folder" in drain_fn_area


def test_teardown_drain_is_bounded_and_does_not_change_the_verdict() -> None:
    text = _read(_HOST_LAUNCHER)
    drain_seconds = _int_setting(
        text, r"\[int\]\$TeardownDrainSeconds\s*=\s*(\d+)", "-TeardownDrainSeconds default"
    )
    poll_seconds = _int_setting(
        text, r"\[int\]\$TeardownDrainPollSeconds\s*=\s*(\d+)", "-TeardownDrainPollSeconds default"
    )
    assert 60 <= drain_seconds <= 600, (
        f"teardown drain bound ({drain_seconds}s) should be a few minutes, not unbounded "
        "and not so short it can't outlast normal VM exit"
    )
    assert 1 <= poll_seconds <= 30
    assert "TEARDOWN-DRAIN-TIMEOUT.txt" in text
    assert "Set-Content -Path (Join-Path $OutDir 'TEARDOWN-DRAIN-TIMEOUT.txt')" in text, (
        "the timeout marker must land in $OutDir so Run-GateA.ps1's unconditional evidence "
        "copy carries it into evidence\\<source_sha>\\<utc-timestamp>\\ for free"
    )
    drain_block = text[text.index("Draining sandbox teardown") : text.index('Write-Host "Done.')]
    assert "exit " not in _code_only(drain_block), (
        "the drain must never exit non-zero or otherwise change this script's own exit code -- "
        "it is runner hygiene, decided after the product verdict, never a station-acceptance finding"
    )


def test_run_gate_a_passes_teardown_drain_settings_through() -> None:
    text = _read(_RUN_GATE_A)
    assert "[int]$TeardownDrainSeconds = 300" in text
    assert "[int]$TeardownDrainPollSeconds = 5" in text
    assert "-TeardownDrainSeconds $TeardownDrainSeconds" in text
    assert "-TeardownDrainPollSeconds $TeardownDrainPollSeconds" in text


def test_workflow_waits_for_prior_run_teardown_before_checkout() -> None:
    """Belt-and-suspenders in CI: a rename-probe loop must run BEFORE
    Checkout so a leftover VM from the prior job (the host-side drain above
    only covers the run that just finished) cannot repeat run 32929704614's
    EBUSY on this job's own workspace clean."""
    text = _read(_WORKFLOW)
    wait_idx = text.index("Wait for prior run's workspace to be clean")
    checkout_idx = text.index("name: Checkout")
    assert wait_idx < checkout_idx, "the teardown wait must run before Checkout, not after"
    pre_checkout = text[wait_idx:checkout_idx]
    assert "Test-DirectoryHandlesFree" in pre_checkout
    assert "shell: pwsh" in pre_checkout, "match the shell every other step in this workflow uses"
    for folder in ("scripts", "hoststore", "output", "soak-4h"):
        assert f"'{folder}'" in pre_checkout, f"pre-checkout probe must cover sandbox-lab/{folder}"


def test_forensics_distinguish_spinning_from_blocked_and_bound_the_dump() -> None:
    """One cumulative CPU number cannot tell 'spinning now' from 'burned CPU
    earlier and now blocked'. Two samples can, and that is the bit that picks
    where to look next."""
    text = _read(_DRIVER)
    fn = text[text.index("function Get-DriverForensics") :][:3600]
    assert "driver_cpu_delta_seconds" in fn and "driver_busy_percent" in fn
    assert "SPINNING (compute-bound right now)" in fn
    assert "NOT-SPINNING (idle or blocked right now)" in fn
    # The dump must be bounded by size AND time, and must never land in the
    # shipped evidence directory -- a full dump of the 8.3 GB process this was
    # written for would be 8.3 GB.
    assert "DumpMaxWorkingSetMb" in fn
    assert "Join-Path $env:TEMP" in fn, "the dump must go to TEMP, never to the shipped $OutDir"
    assert "$OutDir" not in fn, "Get-DriverForensics must not write into the evidence directory"
    assert "Wait-Process -Id $dp.Id -Timeout 120" in fn, "the dump itself must be time-bounded"
    assert "comsvcs.dll,MiniDump" in fn


# --------------------------------------------------------------------------
# 18-22. The orphan guard: run 32930110802 burned its full 90-minute
#         -SandboxWaitMinutes window on an orphaned WindowsSandboxServer
#         (PID 17548, 81 MB) with no vmmemWindowsSandbox anywhere in sight,
#         no WindowsSandboxClient window, and `wsb list` reporting zero
#         sessions the whole time.
# --------------------------------------------------------------------------


def _busy_guard_block(text: str) -> str:
    """Slice out just the pre-launch busy/orphan guard, not the whole file.

    Step 5 (far below, teardown of THIS run's own recorded launch PIDs)
    legitimately calls Stop-Process -- a naive whole-file assertion would
    either false-positive on that safe call or have to special-case it. The
    guard block itself runs from its own header comment up to where the
    script actually launches Windows Sandbox.
    """
    start = text.index("1b. Guard: wait for a free sandbox")
    end = text.index("# 2. Launch Windows Sandbox")
    return text[start:end]


def test_busy_guard_classifies_by_vmmem_presence_not_just_process_name() -> None:
    """The old guard treated ANY of $SandboxProcessNames as "busy" -- exactly
    what misread run 32930110802's lone orphaned server process as a live
    session. The fix must specifically distinguish vmmemWindowsSandbox (the
    actual VM, multi-GB when real) from the server/client/remote-session
    shells that can outlive it during teardown or be left behind entirely."""
    text = _read(_HOST_LAUNCHER)
    assert "function Get-SandboxBusyEvidence" in text
    fn = text[text.index("function Get-SandboxBusyEvidence") :][:1400]
    assert "'vmmemWindowsSandbox'" in fn or '"vmmemWindowsSandbox"' in fn
    assert "VmmemAlive" in fn
    assert "$vmmem.Count -gt 0" in fn, (
        "vmmem presence, not mere process-name membership, must decide 'genuinely busy'"
    )


def test_busy_guard_evidence_records_working_set_and_start_time_per_process() -> None:
    """The ORPHAN-vs-BUSY call has to be defensible after the fact -- the
    evidence recorded per poll must carry pid, name, working-set size, and
    start time for every process, not just a bare process-name list (the
    original SANDBOX-WAIT.txt shape, which is what left run 32930110802's
    81 MB / hours-old PID indistinguishable from a real multi-GB VM)."""
    text = _read(_HOST_LAUNCHER)
    assert "function Format-SandboxProcessEvidence" in text
    fn = text[text.index("function Format-SandboxProcessEvidence") :][:900]
    assert "WorkingSet64" in fn
    assert "StartTime" in fn
    assert "ws_mb=" in fn
    assert "start_utc=" in fn


def test_orphan_grace_window_is_parameterized_and_threaded_through_run_gate_a() -> None:
    host_text = _read(_HOST_LAUNCHER)
    run_gate_a_text = _read(_RUN_GATE_A)
    grace = _int_setting(
        host_text, r"\[int\]\$OrphanGraceMinutes\s*=\s*(\d+)", "-OrphanGraceMinutes default"
    )
    assert grace == 10, (
        "a real launch spawns vmmemWindowsSandbox within seconds to a couple of minutes -- "
        "10 minutes of continuous absence is not something a live launch produces"
    )
    run_gate_a_grace = _int_setting(
        run_gate_a_text,
        r"\[int\]\$OrphanGraceMinutes\s*=\s*(\d+)",
        "Run-GateA.ps1 -OrphanGraceMinutes default",
    )
    assert run_gate_a_grace == grace, "the two defaults must agree"
    assert "-OrphanGraceMinutes $OrphanGraceMinutes" in run_gate_a_text, (
        "Run-GateA.ps1 must pass its own -OrphanGraceMinutes through to the host launcher, "
        "not silently drop the caller's override"
    )


def test_orphan_classification_seeds_from_the_oldest_non_vmmem_process_start_time() -> None:
    """Run 32930110802's orphan PID was already hours old by the time the
    guard looked at it. Seeding the grace clock from 'now' would force every
    future run to burn a fresh -OrphanGraceMinutes wait on an already-stale
    process; seeding from the process's own StartTime lets an old orphan
    classify on this run's very first evidence read instead."""
    guard = _busy_guard_block(_read(_HOST_LAUNCHER))
    assert "$orphanSinceUtc" in guard
    assert "Sort-Object StartTime" in guard, (
        "the orphan clock must be seeded from a real process StartTime, not just the poll loop's "
        "own wall-clock arrival"
    )
    assert "$orphanSinceUtc = $null" in guard, (
        "vmmemWindowsSandbox appearing must reset the orphan clock -- a genuine in-flight launch "
        "(server process visible a moment before its own VM spawns) must never be misclassified "
        "as an orphan"
    )


def test_orphan_marker_filename_and_evidence_fields() -> None:
    text = _read(_HOST_LAUNCHER)
    assert "$orphanMarkerPath = Join-Path $OutDir 'SANDBOX-ORPHAN.txt'" in text, (
        "the orphan marker filename is SANDBOX-ORPHAN.txt, parallel to the existing "
        "SANDBOX-BUSY.txt/SANDBOX-WAIT.txt family"
    )
    orphan_body = text[text.index("$orphanBody = @(") :][:1400]
    for field in (
        "orphan_detected_utc=",
        "orphan_since_utc=",
        "grace_minutes=",
        "reason=",
        "action=",
    ):
        assert field in orphan_body, f"SANDBOX-ORPHAN.txt evidence is missing {field}"
    assert "Set-Content -Path $orphanMarkerPath -Value $orphanBody" in text


def test_busy_guard_never_stops_a_discovered_process() -> None:
    """Proceed-not-kill: an orphan classification changes whether this script
    WAITS before launching; it must never authorize touching a process this
    run did not itself start. Only step 5's teardown (this run's own
    recorded launch PIDs, captured after this guard already runs) may call
    Stop-Process -- see the 2026-08-24 hardening's own header and the
    "NEVER kill by image name" lesson it was written to avoid repeating."""
    guard = _code_only(_busy_guard_block(_read(_HOST_LAUNCHER)))
    assert "Stop-Process" not in guard, (
        "the busy/orphan guard classifies evidence from processes it never launched -- it must "
        "never call Stop-Process against them, orphan or not"
    )


def test_judge_stays_ignorant_of_the_orphan_marker() -> None:
    """An orphan classification never writes SANDBOX-BUSY.txt -- it proceeds
    to launch instead -- so gate_a_verdict.py's existing BUSY short-circuit
    is untouched and needs no shape change for the new evidence fields. An
    orphaned run either produces real evidence (judged normally) or fails
    post-launch through the existing, honest "no VM process" path."""
    judge_text = _read(_JUDGE)
    assert "SANDBOX-BUSY.txt" in judge_text
    assert "SANDBOX-ORPHAN.txt" not in judge_text


# --------------------------------------------------------------------------
# 8. Dirty-box remnant lane <gate-a-dirty-lane>
# --------------------------------------------------------------------------


def test_dirty_lane_timeout_budgets_are_ordered() -> None:
    """A dirty run performs two install cycles: the driver raises its own
    watchdog to 210 minutes when DIRTY_MODE.txt is present, the host launcher
    enforces a 230-minute poll floor alongside -DirtyMode, and the workflow's
    dirty job passes -TimeoutMinutes 230 explicitly -- the dirty analogue of
    the clean lane's 150 < 170 ordering. Three files, one contract."""
    driver = _driver_executable_text()
    dirty_watchdog = _int_setting(
        driver,
        r"if \(\$MaxScriptMinutes -lt (\d+)\) \{ \$MaxScriptMinutes = \d+ \}",
        "In-Sandbox-Report.ps1 dirty-mode watchdog raise",
    )
    assert dirty_watchdog == 210, "the dirty in-sandbox bound is 210 minutes (two install cycles)"

    host = _read(_HOST_LAUNCHER)
    assert "[switch]$DirtyMode" in host, "the host launcher must expose the -DirtyMode opt-in"
    host_floor = _int_setting(
        host,
        r"if \(\$TimeoutMinutes -lt (\d+)\) \{",
        "Host-Launch-Sandbox-Test.ps1 dirty-mode -TimeoutMinutes floor",
    )
    assert host_floor > dirty_watchdog, (
        f"the host's dirty poll floor ({host_floor}m) must outlast the dirty in-sandbox "
        f"watchdog ({dirty_watchdog}m), or the host gives up before the watchdog it depends on"
    )

    workflow = _read(_WORKFLOW)
    dirty_line = next(
        (ln for ln in workflow.splitlines() if "Run-GateA.ps1" in ln and "-DirtyLane" in ln),
        None,
    )
    assert dirty_line is not None, "the workflow must carry a dirty-lane Run-GateA.ps1 invocation"
    match = re.search(r"-TimeoutMinutes (\d+)", dirty_line)
    assert match is not None, "the dirty-lane invocation must pass -TimeoutMinutes explicitly"
    assert int(match.group(1)) == host_floor, (
        "keep the workflow's dirty -TimeoutMinutes and the host launcher's dirty floor on the "
        "same number"
    )


def test_dirty_mode_file_is_the_single_opt_in_channel() -> None:
    """The host writes DIRTY_MODE.txt into output\\ (the same host-to-guest
    input channel as SOAK_MINUTES.txt); the driver reads it from its LOCAL
    seeded copy, before the shipper and watchdog spawn."""
    host = _read(_HOST_LAUNCHER)
    assert "Join-Path $OutDir 'DIRTY_MODE.txt'" in host
    driver = _read(_DRIVER)
    assert "$script:DirtyMode = Test-Path (Join-Path $OutDir 'DIRTY_MODE.txt')" in driver
    code = _code_only(_driver_executable_text())
    read_at = code.index("DIRTY_MODE.txt")
    shipper_at = code.index("_SHIPPER_SPAWNED.marker")
    watchdog_at = code.index("_WATCHDOG_SPAWNED.marker")
    assert read_at < shipper_at and read_at < watchdog_at, (
        "the dirty flag must be resolved before the shipper/watchdog spawn, or the raised "
        "210-minute bound never reaches them"
    )


def test_dirty_prologue_runs_before_the_clean_flow_and_uses_the_real_uninstaller() -> None:
    text = _read(_DRIVER)
    assert "function Invoke-DirtyRemnantPrologue" in text
    code = _code_only(text)
    prologue_call = (
        code.index("Invoke-DirtyRemnantPrologue\n")
        if "Invoke-DirtyRemnantPrologue\n" in code
        else code.rindex("Invoke-DirtyRemnantPrologue")
    )
    clean_install = code.index(_INSTALLER_LAUNCH)
    assert prologue_call < clean_install, (
        "the remnant prologue must run BEFORE the normal acceptance flow's installer"
    )
    # The uninstall is the REAL uninstaller, bounded, never a hand-faked
    # deletion of the install tree.
    assert "uninstall.exe" in text
    assert re.search(
        r"Invoke-BoundedProcess -FilePath \(Join-Path \$installRoot 'uninstall\.exe'\)", text
    ), "the prologue must run the product's own uninstaller through a bounded child process"
    # The orphan shape is never authored by deleting product state.
    normalized = text.replace("\r\n", "\n")
    prologue = normalized[
        normalized.index("function Invoke-DirtyRemnantPrologue") : normalized.index(
            "try {\n    if ($script:DirtyMode)"
        )
    ]
    assert "RECEIPT_PRESENT_IN_PROGRAMDATA" in prologue
    assert "Remove-Item" not in _code_only(prologue).replace(
        "Remove-Item -LiteralPath $u", ""
    ).replace("Remove-Item -LiteralPath $ProbeArgs['Root']", ""), (
        "the prologue may remove only the `_?=` uninstaller leftovers, never other state"
    )


def test_dirty_evidence_filenames_agree_between_powershell_and_judge() -> None:
    """DIRTY-PREP-RESULT.txt / DIRTY-RESULT.txt: one contract, two languages
    -- the same shape rule as the quiet-share marker test above."""
    driver = _read(_DRIVER)
    judge_text = _read(_JUDGE)
    for name in ("DIRTY-PREP-RESULT.txt", "DIRTY-RESULT.txt"):
        assert name in driver, f"the driver never writes {name}"
        assert name in judge_text, f"the judge never reads {name}"
    for key in (
        "PHASE1_INSTALL_EXIT",
        "UNINSTALL_EXIT",
        "PGDATA_PRESERVED_AFTER_UNINSTALL",
        "UPLOADS_PRESERVED_AFTER_UNINSTALL",
        "INSTALL_TREE_REMOVED_AFTER_UNINSTALL",
        "DIRTY_PGDATA_PRESERVED",
        "DIRTY_UPLOADS_PRESERVED",
        "DIRTY_ORPHAN_SEEDED",
        "DIRTY_ORPHAN_WARNING",
        "D3_ROUTE",
        "D3_ENGINE_EXIT",
    ):
        assert key in driver, f"the driver never writes {key}"
        assert key in judge_text, f"the judge never checks {key}"


def test_dirty_orphan_warning_pattern_matches_the_product_log_line() -> None:
    """The grep the harness runs against the supervisor log must actually
    match the WARNING station_runtime.py emits on the orphaned-tier degrade
    path (PR #80). The product's exact text: '... is staged but has no valid
    activation self-test receipt at ...'."""
    driver = _read(_DRIVER)
    match = re.search(r"-Pattern '([^']*staged but has no valid[^']*)'", driver)
    assert match is not None, "the driver must grep for the orphaned-tier WARNING"
    pattern = match.group(1)
    product_line = (
        "Caption tier large-v3 at C:\\x is staged but has no valid activation "
        "self-test receipt at C:\\y -- it was likely preserved from a previous install"
    )
    assert re.search(pattern, product_line), (
        f"the harness grep pattern {pattern!r} does not match the product's own WARNING text"
    )


def test_run_gate_a_threads_the_dirty_lane_through_launcher_and_judge() -> None:
    text = _read(_RUN_GATE_A)
    assert "[switch]$DirtyLane" in text
    # -DownloadOnlyLane implies the dirty lane's -DirtyMode opt-in too (both
    # perform the same two-install-cycle upgrade prologue), so the launcher
    # is threaded a combined flag rather than the raw -DirtyLane switch --
    # see test_download_only_lane_implies_dirty_mode_on_the_launcher below
    # for the -DownloadOnlyLane-specific assertions on that combined flag.
    assert "-DirtyMode:$dirtyLaneActive" in text, "the launcher must receive the dirty opt-in"
    assert "$dirtyLaneActive = [bool]$DirtyLane -or [bool]$DownloadOnlyLane" in text
    assert "--lane $judgeLane" in text or "--lane $forensicLane" in text, (
        "the judge must be told which lane produced the evidence"
    )


def test_clean_lane_flow_is_untouched_by_dirty_mode() -> None:
    """Without DIRTY_MODE.txt nothing changes: the prologue and the survival
    verify are both gated on $script:DirtyMode, and the clean lane's numbers
    (150/170, SOAK 20) are asserted unchanged by the earlier ordering test."""
    text = _read(_DRIVER)
    code = _code_only(text)
    assert "if ($script:DirtyMode) {\n        Invoke-DirtyRemnantPrologue" in code.replace(
        "\r\n", "\n"
    ), "the prologue call must be gated on the dirty flag"
    # The dirty watchdog raise must live inside the same gate.
    raise_at = code.index("$MaxScriptMinutes = 210")
    gate_at = code.rindex("if ($script:DirtyMode) {", 0, raise_at)
    assert gate_at != -1


# --------------------------------------------------------------------------
# 9. Cross-version install-over-existing extension
# --------------------------------------------------------------------------


def test_current_product_version_advances_past_the_pinned_previous_candidate() -> None:
    baseline = json.loads(_UPGRADE_BASELINE.read_text(encoding="utf-8"))
    current_version = (
        (_REPO_ROOT / "civiccast" / "_version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "', 1)[1]
        .split('"', 1)[0]
    )
    previous_version = baseline.get("product_version", current_version)

    assert current_version != previous_version, (
        "Gate A cannot prove an upgrade when the current and pinned previous "
        f"product versions are both {current_version}; the installer routes "
        "that case to SAME_VERSION_NO_OP."
    )


def test_upgrade_baseline_is_immutable_candidate_identity_not_a_latest_glob() -> None:
    baseline = json.loads(_UPGRADE_BASELINE.read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 2
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["source_sha"])
    assert str(baseline["run_id"]).isdigit()
    assert str(baseline["gate_a_run_id"]).isdigit()
    assert baseline["run_id"] != baseline["gate_a_run_id"]
    assert baseline["candidate_label"]
    assert re.fullmatch(r"[0-9a-f]{64}", baseline["installer_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", baseline["station_index_sha256"])
    assert baseline["product_version"]

    workflow = _read(_WORKFLOW)
    assert "sandbox-lab/upgrade-baseline.json" in workflow
    assert "previous_source_sha" in workflow
    assert "previous_run_id" in workflow
    assert "previous_installer_sha256" in workflow
    assert "previous_station_index_sha256" in workflow
    assert "previous_product_version" in workflow
    assert "Get-FileHash" in workflow
    assert "C:\\CivicCastTester\\kit-staging" in workflow
    assert "previous-kit-staging" in workflow
    assert "Previous full kit is absent" in workflow
    assert "latest" not in "\n".join(
        line.lower() for line in workflow.splitlines() if "previous" in line.lower()
    ), "the previous candidate must be an explicit immutable identity, never newest/latest"


def test_run_gate_a_requires_and_maps_a_distinct_previous_kit_for_upgrade_mode() -> None:
    text = _read(_RUN_GATE_A)
    assert "[string]$PreviousKitDir" in text
    assert "[string]$PreviousSourceSha" in text
    assert "$PreviousSourceSha -eq $sourceSha" in text
    assert "previous-kit-download" in text
    assert "{{PREVIOUS_KIT_MAPPING}}" in _read(_WSB_TEMPLATE)
    assert "CivicCastPreviousPayload" in _read(_HOST_LAUNCHER)
    assert "-UpgradeMode:$upgradeMode" in text
    assert "-PreviousSourceSha $PreviousSourceSha" in text


def test_upgrade_mode_is_an_additive_dirty_lane_opt_in_and_uses_previous_payload_first() -> None:
    host = _read(_HOST_LAUNCHER)
    driver = _read(_DRIVER)
    assert "[switch]$UpgradeMode" in host
    assert "Join-Path $OutDir 'UPGRADE_MODE.txt'" in host
    assert "$script:UpgradeMode = Test-Path (Join-Path $OutDir 'UPGRADE_MODE.txt')" in driver
    assert "C:\\CivicCastPreviousPayload" in driver
    assert "PREVIOUS_INSTALLER_SHA256" in driver
    assert "CURRENT_INSTALLER_SHA256" in driver
    assert "PREVIOUS_PRODUCT_VERSION" in driver
    assert "CURRENT_PRODUCT_VERSION" in driver
    assert "UPGRADE_OVER_LIVE_REQUESTED=1" in driver
    assert "UPGRADE_CURRENT_INSTALL_EXIT" in driver
    assert "D3_ROUTE" in driver
    assert "D3_ENGINE_EXIT" in driver
    assert "D3_ROUTE" in _read(_JUDGE)
    assert "D3_ENGINE_EXIT" in _read(_JUDGE)

    code = _code_only(driver).replace("\r\n", "\n")
    assert "if ($script:UpgradeMode)" in code
    assert "if (-not $script:UpgradeMode)" in code, (
        "the real-uninstaller remnant path must remain available when no previous kit is supplied"
    )


def test_workflow_dirty_lane_supplies_the_previous_candidate_to_gate_a() -> None:
    workflow = _read(_WORKFLOW)
    clean_job = workflow.split("  station-acceptance:", 1)[1].split(
        "  station-acceptance-dirty:", 1
    )[0]
    dirty_job = workflow.split("  station-acceptance-dirty:", 1)[1]
    assert "id: upgrade_baseline" not in clean_job
    assert "id: upgrade_baseline" in dirty_job
    assert "Require the pinned previous full kit" in dirty_job
    dirty_line = next(
        line for line in dirty_job.splitlines() if "Run-GateA.ps1" in line and "-DirtyLane" in line
    )
    assert "-PreviousKitDir" in dirty_line
    assert "-PreviousSourceSha" in dirty_line


def test_upgrade_failure_evidence_captures_a_redacted_journal_and_engine_log() -> None:
    driver = _read(_DRIVER)
    assert "function Invoke-UpgradeEngineEvidenceCapture" in driver
    assert "upgrade-engine.log" in driver
    assert "upgrade-journal.redacted.json" in driver
    assert "$journal.context.database_url = '<database-url-redacted>'" in driver
    assert "Copy-Item -LiteralPath $journalPath" not in driver
    assert (
        "Invoke-UpgradeEngineEvidenceCapture"
        in driver.split("Invoke-InstallProgressCapture -Phase 'post-install'", 1)[1]
    )


def test_manual_gate_dispatch_can_run_only_the_cross_version_diagnostic_lane() -> None:
    workflow = _read(_WORKFLOW)
    assert "lane:" in workflow
    assert "cross-version-only" in workflow
    clean_job = workflow.split("  station-acceptance:", 1)[1].split(
        "  station-acceptance-dirty:", 1
    )[0]
    dirty_job = workflow.split("  station-acceptance-dirty:", 1)[1].split(
        "  station-acceptance-download-only:", 1
    )[0]
    assert "inputs.lane != 'cross-version-only'" in clean_job
    assert "always()" in dirty_job
    assert "inputs.lane == 'cross-version-only'" in dirty_job


# --------------------------------------------------------------------------
# 10. Download-only lane <gate-a-download-only-lane>
# --------------------------------------------------------------------------


def _split_download_only_job(workflow: str) -> str:
    assert "  station-acceptance-download-only:" in workflow, (
        "the workflow must carry a station-acceptance-download-only job"
    )
    return workflow.split("  station-acceptance-download-only:", 1)[1]


def test_workflow_carries_a_required_download_only_job() -> None:
    workflow = _read(_WORKFLOW)
    download_only_job = _split_download_only_job(workflow)
    assert "name: Download-only upgrade lane" in download_only_job
    assert "needs: station-acceptance-dirty" in download_only_job
    assert "runs-on: [self-hosted, windows, sandbox-lab]" in download_only_job


def test_workflow_defensively_unlinks_download_only_junctions_before_failing_the_job() -> None:
    """<gate-a-download-only-lane-review> BLOCKER 1: belt-and-suspenders on
    top of Run-GateA.ps1's own try/finally -- covers the runner-died-
    mid-job case (cancellation, crash, timeout-minutes kill) where that
    script's own finally never got to run. Must appear, `if: always()`,
    BEFORE the final "Fail the job" step -- same placement as the dirty
    job's own "Unlink the pinned previous-kit junction" step."""
    workflow = _read(_WORKFLOW)
    download_only_job = _split_download_only_job(workflow)
    unlink_at = download_only_job.index("name: Unlink download-only payload junctions")
    fail_at = download_only_job.index("name: Fail the job on a non-PASS verdict or harness error")
    assert unlink_at < fail_at, (
        "the defensive unlink step must run before the fail-the-job step, like the dirty job's own"
    )
    unlink_step = download_only_job[unlink_at:fail_at]
    assert "if: always()" in unlink_step
    assert "kit-download-filtered" in unlink_step
    assert "Remove-Item -LiteralPath $filteredPayload -Recurse -Force" in unlink_step


def test_download_only_job_lane_input_option_and_bypass() -> None:
    workflow = _read(_WORKFLOW)
    assert "download-only-only" in workflow, (
        "workflow_dispatch must carry the download-only-only diagnostic lane option"
    )
    clean_job = workflow.split("  station-acceptance:", 1)[1].split(
        "  station-acceptance-dirty:", 1
    )[0]
    dirty_job = workflow.split("  station-acceptance-dirty:", 1)[1].split(
        "  station-acceptance-download-only:", 1
    )[0]
    download_only_job = _split_download_only_job(workflow)

    # 'download-only-only' must bypass BOTH the clean and dirty lanes (their
    # own guards must exclude it, or all three jobs run every time) and must
    # be an explicit bypass on the download-only job's own needs check.
    assert "inputs.lane != 'download-only-only'" in clean_job
    assert "'download-only-only'" not in dirty_job.split("if:", 1)[1].split("\n", 1)[0], (
        "the dirty job's own if-guard must not special-case download-only-only -- it should "
        "fall through to the unchanged needs.station-acceptance check and be skipped"
    )
    assert "inputs.lane == 'download-only-only'" in download_only_job
    assert "needs.station-acceptance-dirty.result == 'success'" in download_only_job
    assert "always()" in download_only_job


def test_download_only_job_filtered_payload_step_and_lane_flag() -> None:
    workflow = _read(_WORKFLOW)
    download_only_job = _split_download_only_job(workflow)
    assert "id: upgrade_baseline" in download_only_job
    assert "Require the pinned previous full kit" in download_only_job
    run_gate_a_line = next(
        line
        for line in download_only_job.splitlines()
        if "Run-GateA.ps1" in line and "-DownloadOnlyLane" in line
    )
    assert "-PreviousKitDir" in run_gate_a_line
    assert "-PreviousSourceSha" in run_gate_a_line
    assert "-DirtyLane" not in run_gate_a_line, (
        "the workflow invokes -DownloadOnlyLane only -- Run-GateA.ps1 itself derives the "
        "combined dirty-mode flag, the workflow must not pass both"
    )


def test_download_only_job_timing_matches_the_dirty_lane_contract() -> None:
    workflow = _read(_WORKFLOW)
    download_only_job = _split_download_only_job(workflow)
    timeout_match = re.search(r"timeout-minutes:\s*(\d+)", download_only_job)
    assert timeout_match is not None
    assert int(timeout_match.group(1)) == 340, (
        "the download-only job must carry the same 340-minute timeout as the dirty lane -- "
        "same two-install-cycle budget"
    )
    run_gate_a_line = next(
        line
        for line in download_only_job.splitlines()
        if "Run-GateA.ps1" in line and "-DownloadOnlyLane" in line
    )
    match = re.search(r"-TimeoutMinutes (\d+)", run_gate_a_line)
    assert match is not None
    assert int(match.group(1)) == 230, (
        "the download-only lane's -TimeoutMinutes must match the dirty lane's 230-minute floor"
    )


def test_run_gate_a_exposes_download_only_lane_switch_and_requires_previous_kit() -> None:
    text = _read(_RUN_GATE_A)
    assert "[switch]$DownloadOnlyLane" in text
    assert "-DownloadOnlyLane requires -PreviousKitDir and -PreviousSourceSha" in text, (
        "download-only lane's phase 1 needs a full previous kit, same as the dirty lane"
    )
    assert "-DownloadOnlyMode:$DownloadOnlyLane" in text, (
        "the launcher must receive the download-only opt-in as its own distinct switch"
    )


_DOWNLOAD_ONLY_BUILDER = _SANDBOX_LAB / "scripts" / "Build-DownloadOnlyPayload.ps1"


def test_run_gate_a_builds_a_filtered_payload_with_no_station_dir() -> None:
    text = _read(_RUN_GATE_A)
    assert "kit-download-filtered" in text
    # <gate-a-download-only-lane-review> BLOCKER 2: the filtered payload's
    # packs\ tree must never be built as a single junctioned directory --
    # the builder is factored into its own dot-sourceable script (asserted
    # below in test_download_only_payload_builder_never_uses_a_junction),
    # and Run-GateA.ps1 itself must call into it rather than junctioning
    # packs\ directly.
    assert "New-Item -ItemType Junction -Path (Join-Path $filteredPayload 'packs')" not in text, (
        "packs\\ must never be junctioned directly inside the mapped payload tree -- see "
        "Build-DownloadOnlyPayload.ps1's New-DownloadOnlyPayload (hard links only)"
    )
    assert ". (Join-Path $Root 'scripts\\Build-DownloadOnlyPayload.ps1')" in text
    assert "New-DownloadOnlyPayload -KitPhysicalDir $kitPhysicalDir" in text
    # kit-download is repointed at the filtered directory -- no separate .wsb
    # mapping is needed since the template already maps kit-download ->
    # C:\CivicCastPayload.
    assert "New-Item -ItemType Junction -Path $kitDownload -Target $filteredPayload" in text


def test_run_gate_a_cleans_up_the_filtered_payload_on_every_exit_path() -> None:
    """<gate-a-download-only-lane-review> BLOCKER 1: the filtered payload and
    the kit-download repoint must be undone on every exit path (success,
    judge FAIL, BUSY/HARNESS_ERROR, or a thrown harness error), not left for
    the next job's `git clean -ffdx` to walk through and delete the real
    kit it's junctioned to -- exactly how a 26 GB pinned kit was already
    lost once (see the dirty job's own "Unlink the pinned previous-kit
    junction" step)."""
    text = _read(_RUN_GATE_A)
    # A script-scope try/finally wraps the rest of the script (steps 4-8):
    # PowerShell `exit` inside a try unwinds through `finally` before the
    # process actually terminates, so this covers every exit call in the
    # script, not only a normal fall-through completion.
    assert "\ntry {\n" in text or "\ntry {\r\n" in text
    finally_block = text.rsplit("} finally {", 1)
    assert len(finally_block) == 2, (
        "expected exactly one script-scope try/finally wrapping steps 4-8"
    )
    cleanup_body = finally_block[1]
    assert "if ($DownloadOnlyLane) {" in cleanup_body
    assert (
        "Restore-DownloadOnlyKitDownload -KitDownloadPath $kitDownload -KitPhysicalDir $kitPhysicalDir"
        in cleanup_body
    )
    assert "Remove-DownloadOnlyPayload -PayloadDir $filteredPayload" in cleanup_body


def test_download_only_payload_builder_script_exists_and_is_dot_sourceable() -> None:
    assert _DOWNLOAD_ONLY_BUILDER.is_file(), f"builder script missing at {_DOWNLOAD_ONLY_BUILDER}"
    text = _read(_DOWNLOAD_ONLY_BUILDER)
    assert "function New-DownloadOnlyPayload" in text
    assert "function Remove-DownloadOnlyPayload" in text
    assert "function Restore-DownloadOnlyKitDownload" in text


def test_download_only_payload_builder_never_uses_a_junction_inside_the_payload() -> None:
    """<gate-a-download-only-lane-review> BLOCKER 2: Host-Launch-Sandbox-
    Test.ps1's own Resolve-PhysicalPath resolves the OUTER MappedFolder
    HostFolder through reparse points precisely because VSMB is not trusted
    to traverse one -- a junction planted INSIDE the mapped tree (the
    original packs\\ junction this review flagged) is exactly that failure
    mode one level down. New-DownloadOnlyPayload (which builds the INSIDE
    of the mapped payload tree) must hard-link every file instead, with a
    Copy-Item fallback only, and must never call `New-Item -ItemType
    Junction` or `-ItemType SymbolicLink` anywhere in its own body.

    Restore-DownloadOnlyKitDownload is a DIFFERENT function -- it recreates
    the OUTER kit-download junction (the same top-level mapping the harness
    has always used, which Host-Launch-Sandbox-Test.ps1's own
    Resolve-PhysicalPath already resolves through reparse points before
    handing it to VSMB) and legitimately uses New-Item -ItemType Junction;
    this test scopes its assertion to New-DownloadOnlyPayload's own body
    only, not the whole file.
    """
    text = _read(_DOWNLOAD_ONLY_BUILDER)
    builder_fn = text.split("function New-DownloadOnlyPayload", 1)[1].split(
        "function Remove-DownloadOnlyPayload", 1
    )[0]
    assert "New-Item -ItemType HardLink" in builder_fn
    assert "Copy-Item" in builder_fn
    assert "-ItemType Junction" not in builder_fn
    assert "-ItemType SymbolicLink" not in builder_fn
    assert "filtered payload unexpectedly contains station" in builder_fn, (
        "the builder must refuse to build a payload that ends up carrying station\\"
    )


def test_download_only_payload_cleanup_functions_never_throw_and_are_idempotent() -> None:
    """Both cleanup functions are called from a `finally` block -- a cleanup
    function that itself throws would mask the real verdict this script
    already printed. Both must catch internally rather than propagate."""
    text = _read(_DOWNLOAD_ONLY_BUILDER)
    remove_fn = text.split("function Remove-DownloadOnlyPayload", 1)[1].split(
        "function Restore-DownloadOnlyKitDownload", 1
    )[0]
    restore_fn = text.split("function Restore-DownloadOnlyKitDownload", 1)[1]
    assert "try {" in remove_fn and "catch {" in remove_fn
    assert "try {" in restore_fn and "catch {" in restore_fn
    # Idempotent: repointing kit-download only happens when it is not
    # already pointed at the real kit.
    assert "if ($currentTarget -eq $KitPhysicalDir) { return }" in restore_fn


def test_host_launcher_download_only_mode_requires_dirty_and_upgrade_mode() -> None:
    host = _read(_HOST_LAUNCHER)
    assert "[switch]$DownloadOnlyMode" in host
    assert "Join-Path $OutDir 'DOWNLOAD_ONLY_MODE.txt'" in host
    assert "if ($DownloadOnlyMode -and -not ($DirtyMode -and $UpgradeMode)) {" in host, (
        "download-only mode must require both -DirtyMode and -UpgradeMode -- it rides their prologue"
    )


def test_driver_download_only_mode_requires_dirty_and_upgrade_mode_and_records_evidence() -> None:
    driver = _read(_DRIVER)
    code = _code_only(driver).replace("\r\n", "\n")
    assert (
        "$script:DownloadOnlyMode = Test-Path (Join-Path $OutDir 'DOWNLOAD_ONLY_MODE.txt')" in code
    )
    assert (
        "if ($script:DownloadOnlyMode -and -not ($script:DirtyMode -and $script:UpgradeMode)) {"
        in code
    )
    assert "STATION_DIR_PRESENT" in driver
    assert "DOWNLOAD-ONLY-RESULT.txt" in driver
    assert "PHASE2_INSTALL_EXIT" in driver
    assert "STATION_SET_PRODUCT_VERSION" in driver
    # The station-dir presence check must run BEFORE the phase-2 install (the
    # "staged-payload" step), and the install/activation result recording
    # must run AFTER it -- both anchored on the same shared marker text.
    before_install = code.index("Save-Summary -Step 'staged-payload'")
    station_check_at = code.index("STATION_DIR_PRESENT=$stationDirPresent")
    assert station_check_at < before_install, (
        "STATION_DIR_PRESENT must be recorded before the phase-2 install runs"
    )
    result_recorded_at = code.index("Save-Summary -Step 'download-only-result-recorded'")
    assert result_recorded_at > before_install


def test_judge_download_only_lane_is_registered() -> None:
    judge = _read(_JUDGE)
    assert '"download-only"' in judge or "'download-only'" in judge
    assert "download_only_no_station_dir" in judge
    assert "DOWNLOAD_ONLY_CHECKS" in judge
    assert (
        "dirty_orphaned_tier" not in judge.split("DOWNLOAD_ONLY_CHECKS", 1)[1].split("}", 1)[0]
    ), "DOWNLOAD_ONLY_CHECKS must never include dirty_orphaned_tier"


# --------------------------------------------------------------------------
# Installer-path audit batch (2026-09-03). The audit's own finding was that
# "the entire PowerShell half of PR #143 has zero tests" -- these close that
# for the harness contracts this batch establishes. Static, like everything
# else in this file: they read the script text, they do not run Sandbox.
# --------------------------------------------------------------------------


def test_harness_completed_is_promoted_by_the_try_not_the_finally() -> None:
    """<gate-a-audit-BL-09> A crashed lane must not report completion.

    The `finally` block used to set ``harness_completed = $true``
    unconditionally -- including after the `catch` that swallows any throw
    from the 1500-line `try` -- so a run that died on
    ``throw "No *setup.exe found in mapped payload"`` still shipped
    DONE.json.harness_completed=true and the judge called it complete.
    """
    code = _code_only(_driver_executable_text())
    assert "harness_completed          = $false" in code, (
        "the summary must initialise harness_completed to $false"
    )
    promotion = "$summary.harness_completed = $true"
    assert code.count(promotion) == 1, (
        "there must be exactly ONE promotion of harness_completed, at the end of the try block"
    )
    promoted_at = code.index(promotion)
    catch_at = code.index('$summary.errors += "top-level failure: $_"')
    assert promoted_at < catch_at, "the promotion must be the try block's last statement"
    assert "$summary.harness_completed = $false" in code, "the catch must demote it"
    assert '$summary.top_level_error = "$_"' in code
    # The finally must consume the flag, never author it.
    finally_tail = code[code.index("Save-Summary -Step 'finally-block'") :]
    assert "harness_completed     = [bool]$summary.harness_completed" in finally_tail
    assert promotion not in finally_tail


def test_watchdog_timeout_retraction_is_gated_on_real_completion() -> None:
    """<gate-a-audit-BL-09> A run the watchdog declared dead cannot erase it."""
    code = _code_only(_driver_executable_text())
    retraction = "$wd = Join-Path $OutDir 'WATCHDOG-TIMEOUT.txt'"
    assert retraction in code
    guard = "if ($summary.harness_completed -eq $true) {"
    assert guard in code
    assert code.index(guard) < code.index(retraction), (
        "the WATCHDOG-TIMEOUT.txt retraction must sit inside the completion guard"
    )


def test_post_upgrade_revision_has_two_independent_operands() -> None:
    """<gate-a-audit-BL-10> The audit's central finding.

    Both operands of the old guard came from one ``SchemaStatus`` in one
    process, and ``schema=="current"`` is DEFINED as those two being equal,
    so the guard was 1 whenever the station-up check passed. The database's
    own ``alembic_version`` row and the CI job's build-time head are the two
    origins that cannot agree by construction.
    """
    driver = _driver_executable_text()
    assert "function Get-CivicCastDbRevisionViaPsql" in driver
    assert "alembic_version" in driver
    assert "function Get-CivicCastKitExpectedHead" in driver
    assert "EXPECTED-MIGRATION-HEAD.txt" in driver
    # Both upgrade lanes, not just one.
    assert driver.count("POST_UPGRADE_DB_REVISION_PSQL=$") == 2
    assert driver.count("KIT_EXPECTED_HEAD=$(Get-CivicCastKitExpectedHead)") == 2


def test_expected_migration_head_flows_from_the_workflow_to_the_guest() -> None:
    """<gate-a-audit-BL-10> The build-time head's whole path, end to end."""
    workflow = _read(_WORKFLOW)
    assert "scripts/gate_a_expected_head.py" in workflow
    assert workflow.count("-ExpectedMigrationHead") == 3, (
        "all three lanes must pass the build-time head"
    )
    run_gate_a = _read(_RUN_GATE_A)
    assert "[string]$ExpectedMigrationHead" in run_gate_a
    assert "-ExpectedMigrationHead $resolvedExpectedHead" in run_gate_a
    launcher = _read(_HOST_LAUNCHER)
    assert "[string]$ExpectedMigrationHead" in launcher
    assert "'EXPECTED-MIGRATION-HEAD.txt'" in launcher


def test_the_health_body_predicate_is_shared_by_station_up_t3_and_t5() -> None:
    """<gate-a-audit-MA-26> PR #143 fixed the station-up loop and left T3/T5
    reading ``.StatusCode`` alone -- which is how one run recorded
    ``T5_RESULT=PASS beats=2 unhealthy=0`` and ``T3 health-200 -> 200 ok``
    over a body reading ``{"status":"degraded","schema":"behind",...}``."""
    code = _code_only(_driver_executable_text())
    assert "function Invoke-CivicCastHealthProbe" in code
    # One definition, three consumers.
    assert code.count("Invoke-CivicCastHealthProbe -Url") >= 3
    # The T5 beat no longer grades a bare status code.
    assert "if (-not $hp.ok) { $soakFail++ }" in code
    assert "$hs = [int](Invoke-WebRequest" not in code, (
        "the T5 soak beat must not read a bare status code any more"
    )
    # And it records what the body said, per beat.
    assert "body_status=$($hp.body_status) body_schema=$($hp.body_schema)" in code


def test_tsduck_proof_fails_closed_on_an_empty_or_incomplete_report() -> None:
    """<gate-a-audit-MA-27> ``Get-Content -Raw`` on a 0-byte file returns
    ``$null``; PowerShell's pipeline drops ``$null``, so the old
    ``... | ConvertFrom-Json`` never ran and never threw, the counters stayed
    at 0, and the verdict was ``pass`` over zero analysed packets."""
    code = _code_only(_driver_executable_text())
    assert "fail-empty-report" in code
    assert "fail-zero-packets" in code
    assert "fail-timed-out" in code
    assert "fail-no-ts-packets-node" in code
    assert "$raw = Get-Content -Raw -LiteralPath $report" in code, (
        "the report must be read into a variable before parsing, never piped straight from "
        "Get-Content -Raw (which silently vanishes on an empty file)"
    )
    assert "[string]::IsNullOrWhiteSpace($raw)" in code
    assert "packets_total" in code


def test_install_progress_capture_is_scoped_to_this_phase() -> None:
    """<gate-a-audit-MA-23> install-progress.log is append-only across both
    install phases; the capture used to keep the last match in the WHOLE file,
    so a phase-2 installer that died before its d3-engine line inherited
    phase 1's ``route=FRESH_INSTALL engine_exit=11``."""
    code = _code_only(_driver_executable_text())
    assert "$script:InstallProgressPhase2Mark" in code
    assert "Select-Object -Skip $script:InstallProgressPhase2Mark" in code
    mark_at = code.index("$script:InstallProgressPhase2Mark = 0\n        try {")
    install_at = code.index(_INSTALLER_LAUNCH)
    assert mark_at < install_at, "the phase mark must be taken before setup.exe launches"


def test_d4_and_postinstall_breadcrumbs_are_captured_and_shipped() -> None:
    """<gate-a-audit-MA-24/MA-25> D3's exit code is not D4's, and the clean
    lane had no check on install-progress.log at all."""
    code = _code_only(_driver_executable_text())
    assert "step d4-activate-station: returned (-?\\d+)" in code
    assert "postinstall: (SUCCESS|FAILED|COMPLETED WITH A D3 ROLLBACK)" in code
    assert "INSTALL-PROGRESS-RESULT.txt" in code
    for field in (
        "D4_ACTIVATE_EXIT=",
        "POSTINSTALL_OUTCOME=",
        "POSTINSTALL_ALERTS=",
        "POSTINSTALL_NONZERO_STEPS=",
    ):
        assert field in code, f"{field} must be shipped for the judge to grade"
    judge = _read(_JUDGE)
    assert "check_install_progress" in judge
    assert '"install_progress": check_install_progress' in judge


def test_tsduck_firewall_rules_are_authored_before_the_first_bind() -> None:
    """<gate-a-batch-item-1> The Windows Security prompt the operator saw on
    every install test, raised inside the sandbox when ``tsp -I ip <port>``
    first opened its listening socket. The harness runs elevated; it authors
    the allow rules itself."""
    code = _code_only(_driver_executable_text())
    assert "function Add-CivicCastFirewallAllowRule" in code
    assert "netsh.exe advfirewall firewall add rule" in code
    assert "dir=$direction action=allow" in code
    assert "foreach ($direction in @('in', 'out'))" in code, (
        "both directions must be authored, not just the inbound one that raises the prompt"
    )
    authored_at = code.index("Add-CivicCastFirewallAllowRule -Name 'CivicCast Gate A - TSDuck tsp'")
    first_tsp_at = code.index("$tsProof = Test-TsProof")
    assert authored_at < first_tsp_at, "the rules must be authored before tsp ever runs"


def test_hoststore_reset_states_its_post_condition() -> None:
    """<gate-a-audit-MN-19> The delete is -ErrorAction SilentlyContinue and
    ``hoststore\\install`` IS the guest's install root, so a silent no-op
    means the next run installs over the previous run's tree and calls it
    clean."""
    code = _code_only(_read(_RUN_GATE_A))
    assert "$hoststoreRemnants" in code
    assert "hoststore reset did NOT complete" in code
    assert "-- verified empty" in code


def test_tsproof_caches_the_process_handle_before_waiting() -> None:
    """<gate-a-tsp-exit-code> Windows PowerShell 5.1 returns $null for
    $proc.ExitCode unless the handle was cached before the process exited.
    Gate A run 33826665417 captured a full 1229-packet engine report and still
    judged 'fail-exit-' because of that. The fix touches $proc.Handle right after
    Start-Process and waits on the object, never via Wait-Process -Id."""
    text = _read(_DRIVER)
    code = _code_only(text)
    start = code.index("function Test-TsProof")
    end = code.index("$result.ran = $true", start)
    block = code[start:end]
    assert "$null = $proc.Handle" in block
    assert block.index("$null = $proc.Handle") < block.index("WaitForExit(")
    assert "Wait-Process -Id $proc.Id" not in block


def test_psql_proof_reads_the_registry_key_the_installer_writes() -> None:
    """<gate-a-dburl-registry-key> The NSIS hook reads/writes DatabaseUrl under
    HKLM\\Software\\CivicCast\\Native; the independent psql proof must read that
    same subkey, never the parent key (which made every upgrade run that reached
    the proof judge '<no-database-url>')."""
    text = _read(_DRIVER)
    code = _code_only(text)
    start = code.index("function Get-CivicCastDbRevisionViaPsql")
    block = code[start : code.index("$probe.database_url_found = $true", start)]
    assert "HKLM:\\SOFTWARE\\CivicCast\\Native" in block
    assert "-Path 'HKLM:\\SOFTWARE\\CivicCast' " not in block
    nsh_path = (
        _SANDBOX_LAB.parent
        / "civiccast"
        / "apps"
        / "installer"
        / "src-tauri"
        / "nsis-hooks-bootstrap.nsh"
    )
    nsh = nsh_path.read_text(encoding="utf-8", errors="replace")
    assert 'HKLM "Software\\CivicCast\\Native" "DatabaseUrl"' in nsh


def test_psql_proof_quotes_the_sql_argument_for_start_process() -> None:
    """<gate-a-psql-quote> Start-Process -ArgumentList joins elements with spaces
    and never quotes them; an unquoted -c SQL reaches psql as many arguments and
    psql runs a bare SELECT (exit 0, no rows). The proof must pass the SQL as one
    double-quoted argument and must refuse an exit-0 result whose stderr shows
    psql ignoring 'extra command-line argument's."""
    text = _read(_DRIVER)
    code = _code_only(text)
    start = code.index("function Get-CivicCastDbRevisionViaPsql")
    block = code[start : code.index("POST_UPGRADE_DB_REVISION_SOURCE=psql exit=", start)]
    assert "'-c', ('\"' + $sql + '\"')" in block
    assert "'-c', $sql\n" not in block and "'-c', $sql)" not in block
    assert "extra command-line argument" in block
    assert "<psql-args-split>" in block
