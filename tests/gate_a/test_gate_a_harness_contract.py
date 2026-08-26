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
