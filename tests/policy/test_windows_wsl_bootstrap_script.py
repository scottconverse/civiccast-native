# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAURI_MAIN = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs"
INSTALLER_API = ROOT / "civiccast" / "apps" / "installer" / "src" / "api.ts"
TAURI_CONFIG = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
BUILD_RELEASE = ROOT / "scripts" / "build_release_artifacts.py"
TAURI_CAPABILITY = (
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "capabilities" / "default.json"
)
TAURI_INSTALLER_ACTIONS_PERMISSION = (
    ROOT
    / "civiccast"
    / "apps"
    / "installer"
    / "src-tauri"
    / "permissions"
    / "installer-actions.toml"
)
NSIS_HOOKS = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "nsis-hooks.nsh"
HEADLESS_BOOTSTRAP = (
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "resources" / "headless-bootstrap.ps1"
)


def _runtime_bash() -> str:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    marker = "$runtimeScript = @'\n"
    start = source.index(marker) + len(marker)
    return source[start : source.index("'@", start)]


def _bash_function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    end = script.index("\n}\n", start) + len("\n}\n")
    return script[start:end]


def _migration_function() -> str:
    rendered = _runtime_bash().replace("__CIVICCAST_VERSION__", "1.0.0rc11")
    return _bash_function(rendered, "migrate_legacy_state")


def _rendered_elevated_wsl_script(tmp_path: Path) -> str:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    start_marker = 'r#"$ErrorActionPreference = "Continue"\n'
    start = source.index(start_marker) + len('r#"')
    end = source.index('\n"#,', start)
    script = source[start:end]

    def ps_quote(value: object) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    replacements = {
        "{result_path}": ps_quote(tmp_path / "result.txt"),
        "{result_json_path}": ps_quote(tmp_path / "result.json"),
        "{installer_state_path}": ps_quote(tmp_path / "installer-state.json"),
        "{log_path}": ps_quote(tmp_path / "bootstrap.log"),
        "{lane_id}": "'wsl2'",
        "{service_url}": "'http://127.0.0.1:8000'",
        "{operator_console_url}": "'http://127.0.0.1:8000/operator/'",
        "{resident_portal_url}": "'http://127.0.0.1:8000/'",
    }
    for placeholder, value in replacements.items():
        script = script.replace(placeholder, value)
    return script.replace("{{", "{").replace("}}", "}")


def _embedded_python_after(script: str, marker: str) -> str:
    command = script.index(marker)
    start = script.index("<<'PY'\n", command) + len("<<'PY'\n")
    return script[start : script.index("\nPY", start)]


def _bash() -> str:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    resolved = str(git_bash) if git_bash.exists() else shutil.which("bash")
    assert resolved is not None, "Bash is required to exercise the embedded WSL bootstrap"
    return resolved


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        return f"/{resolved.drive[0].lower()}/{resolved.as_posix()[3:]}"
    return resolved.as_posix()


def test_windows_wsl_bootstrap_stages_elevated_core_before_user_ubuntu_install() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    core_preflight = source.index('"wsl-status-preflight"')
    feature_gate = source.index('$enableWsl = Run-ServicingStep "enable-wsl-feature"')
    core_update = source.index('$updateCore = Run-Step "update-wsl-core"')
    core_install = source.index('$installCore = Run-Step "install-wsl-core"')
    core_status = source.index('$statusAfterCore = Run-Step "wsl-status-after-core"')
    core_ready = source.index('Finish "wsl_core_ready"')
    user_install_helper = source.index("fn install_wsl_ubuntu_for_current_user")
    user_install = source.index('"install-ubuntu-2404-user"', user_install_helper)

    # wsl.exe --update runs BEFORE --install: an outdated wsl.exe launcher is
    # what triggers the raw, unattended "must be updated... press any key...
    # times out in 60 seconds" console outside CivicCast's own UI (rc.5
    # fast-follow). Updating the launcher first heads that off.
    assert core_preflight < feature_gate < core_update < core_install < core_status < core_ready
    assert user_install_helper < user_install < core_install
    assert "Windows Subsystem for Linux is not installed" in source
    assert "Windows turned on the helper, but it is not ready yet" in source
    assert "Windows could not update the helper CivicCast needs" in source
    assert "Windows updated the helper CivicCast needs and now needs a restart" in source
    assert "install_wsl_ubuntu_for_current_user(&log_path, lane_id)" in source
    assert "wsl_core_available_for_current_user(&log_path)" in source
    assert '$installUbuntu = Run-Step "install-ubuntu-2404"' not in source


def test_user_ubuntu_install_reports_live_activity_and_rejects_disabled_features() -> None:
    """Clean-host regression: ``wsl --status`` can exit successfully while
    reporting that WSL1/WSL2 is unsupported because the Windows features are
    disabled. That output must force the elevated feature lane, and any later
    user-level Ubuntu download must heartbeat rather than sit silently for its
    two-hour timeout window.
    """
    source = TAURI_MAIN.read_text(encoding="utf-8")

    classifier_start = source.index("fn output_wsl_not_ready(")
    classifier_end = source.index("\n}", classifier_start)
    classifier = source[classifier_start:classifier_end]
    assert "wsl1 is not supported with your current machine configuration" in classifier
    assert "wsl2 is not supported with your current machine configuration" in classifier
    assert 'enable the \\"windows subsystem for linux\\" optional component' in classifier
    assert "enable the virtual machine platform windows feature" in classifier

    install_start = source.index("fn install_wsl_ubuntu_for_current_user(")
    install_end = source.index('\n}\n\n#[cfg(target_os = "windows")]', install_start)
    install = source[install_start:install_end]
    assert "run_user_wsl_step_with_progress(" in install
    assert "write_installer_activity_state(" in install
    assert "Downloading and installing Ubuntu 24.04" in install
    assert "seconds elapsed" in install

    bounded_start = source.index("fn run_bounded_command_with_progress")
    bounded_end = source.index("fn install_wsl_ubuntu_for_current_user", bounded_start)
    bounded = source[bounded_start:bounded_end]
    assert "on_progress(now.duration_since(started).as_secs())" in bounded
    assert "Duration::from_secs(3)" in bounded


def test_wsl_core_preflight_explicitly_requires_both_windows_features() -> None:
    """A successful ``wsl --status`` is not enough: after the first reboot
    WSL can be enabled while Virtual Machine Platform is still disabled.
    The explicit feature-state probe must run first and fail closed.
    """
    source = TAURI_MAIN.read_text(encoding="utf-8")

    gate_start = source.index("fn wsl_core_available_for_current_user(")
    gate_end = source.index("\n}", gate_start)
    gate = source[gate_start:gate_end]
    assert "required_windows_features_available" in gate
    assert gate.index("required_windows_features_available") < gate.index('"wsl-status-preflight"')

    probe_start = source.index("fn required_windows_features_available(")
    probe_end = source.index("\n}", probe_start)
    probe = source[probe_start:probe_end]
    assert "windows-feature-preflight" in probe
    assert "Microsoft-Windows-Subsystem-Linux" in probe
    assert "VirtualMachinePlatform" in probe
    assert "required_windows_features_enabled" in probe


def test_elevated_run_step_wsl_invocations_cannot_hang_on_interactive_prompts() -> None:
    """release: 0.1.0-rc6 hang-guard. The elevated 'Set up Windows helper'
    Run-Step (used for bounded wsl.exe core-provisioning calls in
    launch_wsl_ubuntu_install's generated PowerShell) must not hang forever on
    a Windows 'press any key' prompt. It invokes via Start-Process with stdin
    INHERITED (a stdin-closing ProcessStartInfo broke `wsl --install`/`--status`
    -- do NOT reintroduce it), and enforces a hard timeout plus a taskkill /T
    tree-kill on timeout (microsoft/WSL#9032 / #11652 / #13589 class)."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("function Run-Step(")
    function_end = source.index("function Needs-Reboot(", function_start)
    function_body = source[function_start:function_end]

    # Hard timeout + tree-kill guard (replaces the old, wsl-breaking stdin-close).
    assert "[int]$TimeoutSeconds = 900" in function_body
    assert "$proc = Start-Process @spParams" in function_body
    assert "while (-not $proc.HasExited)" in function_body
    assert "$TimeoutSeconds -gt 0" in function_body
    assert "Start-Sleep -Milliseconds 500" in function_body
    assert "Write-ProgressState" in function_body
    assert "taskkill.exe /T /F /PID $proc.Id" in function_body
    assert "$proc.Kill()" in function_body
    assert "timed out after $TimeoutSeconds seconds" in function_body
    # multi-word args must be Win32-quoted, not silently re-split by Start-Process
    assert "ConvertTo-NativeArgumentString" in function_body
    # the stdin-closing ProcessStartInfo (which broke `wsl --install`/`--status`)
    # must NOT come back, and neither may the legacy no-timeout scriptblock form
    assert "$psi.RedirectStandardInput = $true" not in function_body
    assert "& $Block 2>&1" not in function_body
    assert "[scriptblock]$Block" not in function_body

    call_sites = [
        '$updateCore = Run-Step "update-wsl-core" "wsl.exe" @("--update")',
        '$installCore = Run-Step "install-wsl-core" "wsl.exe" @("--install", "--no-distribution")',
        '$statusAfterCore = Run-Step "wsl-status-after-core" "wsl.exe" @("--status")',
    ]
    for call_site in call_sites:
        assert call_site in source


def test_ui_status_prechecks_route_through_the_bounded_command_core() -> None:
    """v1.0.0-rc2 clean-machine finding (DESKTOP-2BR3SJR): the installer's UI
    status pre-checks (wsl_ubuntu_distribution / civiccast_ubuntu_runtime_ready)
    spawned wsl.exe via bare .output() with NO timeout, so a machine whose inbox
    wsl.exe stub hangs (missing/broken WSL runtime) wedged the installer on
    'checking Windows helper setup...' forever. Every pre-check must route
    through the bounded tree-kill core instead."""
    source = TAURI_MAIN.read_text(encoding="utf-8")

    core_start = source.index("fn run_bounded_command(")
    core_end = source.index("fn install_wsl_ubuntu_for_current_user", core_start)
    core_body = source[core_start:core_end]
    assert "taskkill.exe" in core_body
    assert "timed out after {timeout_secs} seconds" in core_body

    for precheck_fn in ("fn civiccast_ubuntu_runtime_ready(", "fn wsl_ubuntu_distribution()"):
        start = source.index(precheck_fn)
        end = source.index("\nfn ", start + 1)
        body = source[start:end]
        # windows and non-windows variants share the name; only the windows one
        # spawns anything -- the first occurrence is the windows cfg block.
        if "wsl.exe" in body or "run_bounded_command" in body:
            assert "run_bounded_command(" in body, f"{precheck_fn} must use the bounded core"
            assert ".output()" not in body, f"{precheck_fn} must not spawn unbounded"
            assert "WSL_PRECHECK_TIMEOUT_SECS" in body

    assert "const WSL_PRECHECK_TIMEOUT_SECS: u64" in source


def test_wsl_update_store_breakage_gets_an_actionable_blocked_message() -> None:
    """v1.0.0-rc2 clean-machine finding (DESKTOP-2BR3SJR): on debloated or
    IT-locked-down Windows images, `wsl --update` fails with
    REGDB_E_CLASSNOTREG / Wsl/CallMsi (broken Store/MSI-COM path) and can NEVER
    succeed on retry. The elevated bootstrap must name the actual fix (install
    WSL directly from microsoft/WSL releases) for that case, before falling
    back to the generic retry message."""
    source = TAURI_MAIN.read_text(encoding="utf-8")

    specific = source.index("REGDB_E_CLASSNOTREG|Class not registered|Wsl/CallMsi")
    assert "github.com/microsoft/WSL" in source
    generic = source.index("Windows could not update the helper CivicCast needs.")
    assert specific < generic, (
        "the actionable Store-breakage branch must run before the generic one"
    )
    specific_message = source.index("cannot install WSL through Windows Update")
    assert specific < specific_message < generic


def test_windows_wsl_bootstrap_leaves_observable_state_before_uac() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    script_write = source.index("Could not write WSL2 bootstrap script")
    log_write = source.index("Could not write WSL2 bootstrap log file")
    result_write = source.index("Could not write WSL2 bootstrap result file")
    state_write = source.index(
        'write_installer_state(\n        lane_id,\n        "wsl_install_requested"'
    )
    elevation_launch = source.index("Start-Process -FilePath powershell.exe")

    assert "bootstrap-wsl2-ubuntu.result.json" in source
    assert "bootstrap-wsl2-ubuntu-result.txt" in source
    assert "installer-state.json" in source
    assert script_write < log_write < result_write < state_write < elevation_launch
    assert "CivicCast is checking Windows helper setup" in source
    assert "CivicCast is asking Windows for permission to set up the helper it needs." in source
    assert '\\"status\\": \\"wsl_install_requested\\"' in source
    assert '\\"reboot_required\\": false' in source
    assert (
        "write_installer_state(\n"
        "        lane_id,\n"
        '        "wsl_install_requested",\n'
        '        "CivicCast is asking Windows for permission to set up the helper it needs.",\n'
        "        false,"
    ) in source
    assert "ConvertTo-Json -Depth 4" in source


def test_elevated_bootstrap_quotes_script_paths_as_one_native_argument_string() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]

    assert "windows_command_line_quote" in source
    assert "elevated_argument_list" in function_body
    assert "powershell_single_quote(&elevated_argument_list)" in function_body
    assert "-ArgumentList @(" not in function_body


def test_windows_wsl_bootstrap_script_writes_final_installer_state() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]
    state_start = function_body.index("function Write-InstallerState")
    state_body = function_body[
        state_start : function_body.index("function Write-ProgressState", state_start)
    ]
    finish_start = function_body.index("function Finish")
    finish_body = function_body[
        finish_start : function_body.index("function ConvertTo-", finish_start)
    ]

    assert "$installerStatePath" in function_body
    assert "current_lane_id = $laneId" in state_body
    assert "status = $Status" in state_body
    assert "message = $clean" in state_body
    assert "reboot_required = $RebootRequired" in state_body
    assert "operator_console_url = $operatorConsoleUrl" in state_body
    assert "Write-TextAtomically $installerStatePath" in state_body
    assert "Write-InstallerState $Status $RebootRequired $clean" in finish_body


def test_read_local_installer_state_reconciles_both_health_directions() -> None:
    """The live window must promote stale non-ready state when health is up and
    revoke stale ready state when health is down, without losing the operator
    URL carried by the state writer."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    # QA-6 (gate-civiccast): the public Tauri command is async and offloads the
    # blocking read (with its /health probe) to the blocking pool, off the UI thread.
    wrap_start = source.index("async fn read_local_installer_state()")
    wrap_body = source[wrap_start : source.index("\nfn ", wrap_start + 1)]
    assert "spawn_blocking(read_local_installer_state_blocking)" in wrap_body
    # The blocking body holds the two-way health decision and preserves the lane.
    read_start = source.index("fn read_local_installer_state_blocking()")
    read_body = source[read_start : source.index("\nfn ", read_start + 1)]
    assert "headless_bundled_runtime_build_id()" in read_body
    assert "expected_build_id.as_deref()" in read_body
    assert 'installer_state_string_field(&raw, "current_lane_id")' in read_body
    assert "RuntimeStateTransition::MarkReady" in read_body
    assert "RuntimeStateTransition::MarkUnavailable" in read_body
    assert '"unavailable"' in read_body
    assert "installer_state_reboot_required(&raw)" in read_body


def test_same_version_repair_reprovisions_when_runtime_build_differs() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    start = source.index("fn launch_startup_wsl_bootstrap_if_missing")
    body = source[start : source.index("\nfn ", start + 1)]
    assert "app_bundled_runtime_build_id(&app)" in body
    assert "service_health_reachable_once(None, expected_build_id.as_deref())" in body
    assert "expected_build_id.is_some() && service_health_reachable_once(None, None)" in body
    assert 'launch_civiccast_runtime_bootstrap(app, "runtime".to_string())' in body


def test_run_local_installer_action_offloads_to_blocking_pool() -> None:
    """The rc8 'Not Responding' freeze fix: run_local_installer_action's
    multi-minute work must run OFF the UI thread. The Rust compile-time guard only
    proves the command kept an async signature; this source-scan additionally
    proves it still dispatches to spawn_blocking (audit-lite: catches a regression
    that keeps `async fn` but drops the spawn_blocking call)."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    start = source.index("async fn run_local_installer_action(")
    body = source[start : source.index("\nfn ", start + 1)]
    assert "spawn_blocking(" in body
    assert "run_local_installer_action_blocking(app, lane_id, action)" in body


def test_windows_wsl_ready_detection_requires_ubuntu_wsl2() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn parse_ubuntu_distributions")
    function_end = source.index('\n#[cfg(target_os = "windows")]', function_start + 1)
    function_body = source[function_start:function_end]

    assert "let version = parts.last().copied().unwrap_or_default();" in function_body
    assert 'version != "2"' in function_body
    assert "CIVICCAST_WSL_DISTRO_NAME" in source
    assert "CIVICCAST_WSL_HEALTH_PROBE" in source
    assert "civiccast_ubuntu_runtime_ready(candidate)" in source
    assert "candidate == CIVICCAST_WSL_DISTRO_NAME" in source


def test_windows_wsl_bootstrap_shows_only_uac_and_hides_helper_consoles() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    launcher_start = source.index("let elevated = format!(")
    launcher_end = source.index(
        '.map_err(|error| format!("Unable to launch Windows helper setup', launcher_start
    )
    launcher = source[launcher_start:launcher_end]

    assert "-Verb RunAs -WindowStyle Hidden -Wait -PassThru" in launcher
    assert "exit $process.ExitCode" in launcher
    assert "Windows did not return a helper setup process." in launcher
    assert "hide_windows_command(&mut command);" in launcher


def test_windows_wsl_bootstrap_is_single_instance_across_clicks_and_processes() -> None:
    """The clean-Windows rc13 incident launched two elevated bootstrap chains.
    The native caller and the elevated script both need lifetime guards so a
    second click, window, or relaunch cannot race the active servicing run."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]

    assert "WSL_BOOTSTRAP_MUTEX_ADDR" in source
    assert "persisted_wsl_bootstrap_is_freshly_active()" in function_body
    assert "TcpListener::bind(WSL_BOOTSTRAP_MUTEX_ADDR)" in function_body
    assert "Windows helper setup is already running" in function_body
    assert "Local\\CivicCastWslBootstrap" in function_body
    assert "System.Threading.Mutex" in function_body
    assert "WaitOne(0)" in function_body

    startup_start = source.index("fn launch_startup_wsl_bootstrap_if_missing")
    startup_end = source.index('\n#[cfg(not(target_os = "windows"))]', startup_start)
    startup_body = source[startup_start:startup_end]
    assert "if persisted_wsl_bootstrap_is_freshly_active()" in startup_body
    assert startup_body.index("persisted_wsl_bootstrap_is_freshly_active") < startup_body.index(
        'write_installer_state("wsl2", "blocked"'
    )


def test_duplicate_bootstrap_call_never_overwrites_the_active_run_state() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    action_start = source.index("fn run_local_installer_action_blocking")
    action_end = source.index("fn command_line_has_arg", action_start)
    action_body = source[action_start:action_end]
    result = action_body.index("let result = launch_wsl_ubuntu_install")
    duplicate = action_body.index('result.status == "already_running"', result)
    state_write = action_body.index("write_installer_state(", result)
    assert result < duplicate < state_write

    headless_start = source.index("fn run_headless_bootstrap()")
    headless_body = source[headless_start:]
    result = headless_body.index("Ok(result)")
    duplicate = headless_body.index('result.status == "already_running"', result)
    state_write = headless_body.index("write_installer_state(", result)
    assert result < duplicate < state_write


def test_windows_feature_servicing_is_sequential_safe_and_observable() -> None:
    """DISM must never be killed mid-CBS servicing or fall through to the next
    feature after failure. While Windows works, the saved state must heartbeat
    with a real phase, elapsed time, and step count for the visible UI."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]

    assert "function Write-ProgressState" in function_body
    assert "elapsed_seconds = $ElapsedSeconds" in function_body
    assert "activity_current = $ActivityCurrent" in function_body
    assert "activity_total = $ActivityTotal" in function_body
    assert "Windows is still working" in function_body
    assert "function Run-ServicingStep" in function_body
    servicing = function_body[
        function_body.index("function Run-ServicingStep") : function_body.index(
            "function Needs-Reboot", function_body.index("function Run-ServicingStep")
        )
    ]
    assert "taskkill.exe" not in servicing
    assert "$proc.Kill()" not in servicing

    enable_wsl = function_body.index('$enableWsl = Run-ServicingStep "enable-wsl-feature"')
    wsl_terminal_check = function_body.index("$enableWsl.ExitCode -ne 0", enable_wsl)
    enable_vm = function_body.index(
        '$enableVm = Run-ServicingStep "enable-virtual-machine-platform"'
    )
    vm_terminal_check = function_body.index("$enableVm.ExitCode -ne 0", enable_vm)
    update_core = function_body.index('$updateCore = Run-Step "update-wsl-core"')
    assert enable_wsl < wsl_terminal_check < enable_vm < vm_terminal_check < update_core
    assert "function Test-RebootPending" in function_body


@pytest.mark.skipif(os.name != "nt", reason="generated bootstrap runs in Windows PowerShell")
def test_generated_run_step_emits_live_progress_while_child_is_running(tmp_path: Path) -> None:
    """Execute the generated PowerShell invocation core, not a reimplementation.
    A slow child must produce durable heartbeat state before it exits."""
    rendered = _rendered_elevated_wsl_script(tmp_path)
    function_prefix = rendered[: rendered.index("function Needs-Reboot")]
    harness = (
        function_prefix
        + '\n$result = Run-Step "heartbeat-proof" "powershell.exe" '
        + '@("-NoProfile", "-Command", "Start-Sleep -Seconds 4; Write-Output done") '
        + '10 1 2 "Testing live Windows activity"\n'
        + "exit $result.ExitCode\n"
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
        ],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads((tmp_path / "installer-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["activity_phase"] == "Testing live Windows activity"
    assert state["activity_current"] == 1
    assert state["activity_total"] == 2
    assert state["elapsed_seconds"] >= 3
    assert "Windows is still working" in state["message"]
    assert "heartbeat-proof is still running" in (tmp_path / "bootstrap.log").read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(os.name != "nt", reason="generated bootstrap runs in Windows PowerShell")
def test_generated_feature_sequence_stops_after_first_failure_and_honors_reboot_pending(
    tmp_path: Path,
) -> None:
    rendered = _rendered_elevated_wsl_script(tmp_path)
    start = rendered.index("# Enable and verify one Windows feature")
    end = rendered.index("# 30min:", start)
    feature_sequence = rendered[start:end]
    evidence_path = tmp_path / "feature-sequence.json"
    evidence_ps = "'" + str(evidence_path).replace("'", "''") + "'"
    harness = f"""
$script:calls = @()
function Get-FeatureEnabled([string]$Name) {{ return $false }}
function Run-ServicingStep([string]$Name, [string]$Exe, [string[]]$ArgList, [int]$ActivityCurrent, [int]$ActivityTotal, [string]$ActivityPhase) {{
  $script:calls += $Name
  return [pscustomobject]@{{ ExitCode = 1; Output = 'simulated servicing failure' }}
}}
function Needs-Reboot([string]$Text) {{ return $false }}
function Test-RebootPending() {{ return $true }}
function Finish([string]$Status, [bool]$RebootRequired, [string]$Message) {{
  [ordered]@{{ status = $Status; reboot_required = $RebootRequired; calls = $script:calls }} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath {evidence_ps} -Encoding UTF8
}}
$logPath = 'simulated.log'
{feature_sequence}
throw 'feature sequence fell through after the first servicing failure'
"""

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
        ],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    assert evidence["calls"] == ["enable-wsl-feature"]
    assert evidence["status"] == "wsl_install_started"
    assert evidence["reboot_required"] is True


def test_windows_wsl_bootstrap_failed_elevation_writes_error_state() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]
    failure_start = function_body.index("let stderr = String::from_utf8_lossy")
    failure_body = function_body[failure_start:]

    assert 'write_installer_state(lane_id, "error", &message, false)?;' in failure_body
    assert failure_body.index(
        'write_installer_state(lane_id, "error", &message, false)?;'
    ) < failure_body.index("Err(message)")


def test_tauri_wsl_action_errors_are_not_silently_replaced_by_backend_fallback() -> None:
    source = INSTALLER_API.read_text(encoding="utf-8")

    function_start = source.index("async function runTauriInstallerAction")
    function_body = source[function_start:]
    invoke = function_body.index('"run_local_installer_action"')
    browser_fallback = function_body.index("saveBrowserInstallerProgress")
    wsl_error = function_body.index("CivicCast could not hand this step to the local setup helper")

    assert invoke < browser_fallback
    assert invoke < wsl_error
    assert 'if (!("__TAURI_INTERNALS__" in window))' not in function_body
    assert "nativeError" in function_body
    assert 'saveBrowserInstallerProgress(laneId, "error", message);' in function_body


def test_tauri_progress_null_result_is_authoritative_and_clears_browser_cache() -> None:
    """G-9b/UX-3 regression guard: a successful native read — INCLUDING a
    "null" answer (no state file yet) — is authoritative and must NOT resurrect
    a stale browser-cached error. loadInstallerProgress clears the cached entry
    and returns null on "null"; the browserProgress() fallback is reachable ONLY
    when the native bridge itself throws (the catch branch).
    """
    source = INSTALLER_API.read_text(encoding="utf-8")

    function_start = source.index("export async function loadInstallerProgress")
    function_end = source.index("\n}\n\nasync function runTauriInstallerAction", function_start)
    function_body = source[function_start:function_end]

    # A native read clears the browser cache so a stale error can't outlive it.
    assert 'window.localStorage.removeItem("civiccast.installerProgress")' in function_body
    # "null" from the native bridge returns null, not the browser cache.
    assert 'return raw === "null" ? null :' in function_body
    # The old resurrection path is gone: browserProgress() is only in the catch.
    assert "? browserProgress()" not in function_body
    catch_index = function_body.index("} catch")
    assert function_body.index("return browserProgress();") > catch_index


def test_packaged_startup_resumes_authorized_wsl_setup_after_the_servicing_reboot() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_startup_wsl_bootstrap_if_missing")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]

    ready_probe = function_body.index("let ubuntu_ready = wsl_ubuntu_ready()")
    core_probe = function_body.index("wsl_core_available_for_current_user(path)")
    resume_decision = function_body.index("should_resume_post_reboot_wsl_bootstrap(")
    running_state = function_body.index(
        '"Windows restarted successfully. CivicCast is resuming Windows helper setup for this user. '
        'Approve the Windows security prompt again if it appears."'
    )
    resume_launch = function_body.index('launch_wsl_ubuntu_install("wsl2")')
    ready_state = function_body.index(
        "The Windows helper CivicCast needs is already ready", ready_probe
    )
    post_reboot_reprobe = function_body.index("needs_post_reboot_reprobe")
    blocked_state = function_body.index('write_installer_state("wsl2", "blocked", message, false)')

    assert "The Windows helper CivicCast needs is already ready" in function_body
    assert "installer_state_needs_post_reboot_wsl_reprobe" in function_body
    assert "if !should_start {" not in function_body
    assert post_reboot_reprobe < ready_probe
    assert ready_probe < core_probe < resume_decision < running_state < resume_launch
    assert resume_launch < ready_state
    assert ready_state < blocked_state


def test_windows_state_paths_live_outside_package_redirected_appdata() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    headless = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")

    assert 'std::env::var_os("USERPROFILE")' in source
    assert '.join(".civiccast")' in source
    assert "windows_local_app_data" not in source
    assert "$StateRoot = Join-Path $env:USERPROFILE '.civiccast'" in headless
    assert 'Join-Path $env:LOCALAPPDATA "CivicCast"' not in headless
    assert "$PROFILE\\.civiccast" in hooks
    postuninstall = hooks[hooks.index("!macro NSIS_HOOK_POSTUNINSTALL") :]
    assert "$PROFILE\\AppData\\Local\\CivicCast" in postuninstall
    assert (
        "$PROFILE\\AppData\\Local\\CivicCast"
        not in hooks[: hooks.index("!macro NSIS_HOOK_POSTUNINSTALL")]
    )


def test_packaged_startup_reprobes_pending_reboot_state_instead_of_suppressing() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn installer_state_needs_post_reboot_wsl_reprobe")
    function_end = source.index("\n}\n\nfn write_installer_state", function_start)
    function_body = source[function_start:function_end]

    assert '\\"current_lane_id\\":\\"wsl2\\"' in function_body
    assert '\\"current_lane_id\\":\\"platform\\"' in function_body
    assert '\\"reboot_required\\":true' in function_body
    assert "if !should_start {" not in source
    assert "startup_post_reboot_wsl_missing_message()" in source
    assert '"status":"error"' not in function_body
    assert '"status":"blocked"' not in function_body
    assert '"status":"wsl_install_requested"' not in function_body


def test_explicit_windows_helper_action_cannot_get_stuck_on_saved_reboot_state() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    function_start = source.index("fn launch_wsl_ubuntu_install")
    function_end = source.index('\n#[cfg(not(target_os = "windows"))]', function_start)
    function_body = source[function_start:function_end]

    assert "reboot_still_pending" not in function_body
    assert "explicit operator action" in function_body
    assert "Start-Process -FilePath powershell.exe" in function_body


def test_nsis_postinstall_runs_headless_bootstrap_without_blocking_the_wizard() -> None:
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")

    assert "!macro NSIS_HOOK_POSTINSTALL" in hooks
    assert "Starting CivicCast headless setup in the background" in hooks
    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass" in hooks
    # PE-ENG-3: NSIS Exec is asynchronous. Launch powershell directly so paths
    # with spaces stay quoted instead of being flattened by a nested
    # Start-Process -ArgumentList array.
    postinstall = hooks.split("!macro NSIS_HOOK_POSTINSTALL", 1)[1].split("!macroend", 1)[0]
    assert "Exec '" in postinstall
    assert "Start-Process" not in postinstall
    assert '-File "$INSTDIR\\resources\\headless-bootstrap.ps1"' in postinstall
    assert '-InstallDir "$INSTDIR"' in postinstall


def test_nsis_preinstall_stops_existing_gui_and_runtime_host_before_file_check() -> None:
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")

    assert "!macro NSIS_HOOK_PREINSTALL" in hooks
    preinstall = hooks.split("!macro NSIS_HOOK_PREINSTALL", 1)[1].split("!macroend", 1)[0]
    assert 'taskkill.exe /IM "civiccast-installer.exe" /T /F' in preinstall
    assert "Sleep" in preinstall
    assert "-WindowStyle Hidden" in hooks


def test_nsis_postuninstall_removes_autostart_task() -> None:
    """The autostart entry Ensure-AutostartTask registers must be cleaned up
    on uninstall, not left behind pointing at a deleted install directory.
    Current mechanism is the HKCU Run value; the schtasks delete stays as
    legacy cleanup for earlier builds."""
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")

    assert "!macro NSIS_HOOK_POSTUNINSTALL" in hooks
    assert (
        'DeleteRegValue HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Run" '
        '"CivicCast Autostart"' in hooks
    )
    assert 'schtasks.exe /Delete /TN "CivicCast Autostart" /F' in hooks


def test_nsis_postuninstall_removes_product_install_directory_marker() -> None:
    """A completed uninstall must not leave NSIS's InstallDirRegKey behind.

    rc13 left this exact HKCU key on a clean Windows host, causing the next
    installer to show a false ``Already Installed`` page even though the app,
    uninstall entry, WSL distro, and application directories were gone.
    """
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")
    post = hooks[hooks.index("!macro NSIS_HOOK_POSTUNINSTALL") :]

    assert 'DeleteRegKey HKCU "Software\\civiccast\\CivicCast Installer"' in post
    assert 'DeleteRegKey /ifempty HKCU "Software\\civiccast"' in post


def test_nsis_gui_init_discards_only_orphaned_uninstall_registration() -> None:
    """A missing uninstaller makes an uninstall registration stale, not valid.

    rc13 left ``UninstallString`` behind even though its referenced executable
    no longer existed. Tauri's reinstall page trusts that value before any
    install hook runs, so the GUI-init callback must remove this exact orphan
    before page selection while preserving every live installation.
    """
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")
    callback = "CivicCastRepairOrphanedUninstall"
    assert f"!define MUI_CUSTOMFUNCTION_GUIINIT {callback}" in hooks
    gui_init = hooks[
        hooks.index(f"Function {callback}") : hooks.index(
            "FunctionEnd", hooks.index(f"Function {callback}")
        )
    ]

    uninstall_key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CivicCast Installer"
    assert f'ReadRegStr $R0 HKCU "{uninstall_key}" "UninstallString"' in gui_init
    assert 'StrCpy $R1 $R0 "" 1' in gui_init
    assert "StrCpy $R1 $R1 -1" in gui_init
    assert '${FileExists} "$R0"' in gui_init
    assert '${FileExists} "$R1"' in gui_init
    assert f'DeleteRegKey HKCU "{uninstall_key}"' in gui_init
    assert 'DeleteRegKey HKCU "Software\\civiccast\\CivicCast Installer"' in gui_init

    read_at = gui_init.index("ReadRegStr")
    live_file_guard_at = gui_init.index("${FileExists}")
    delete_at = gui_init.index("DeleteRegKey")
    assert read_at < live_file_guard_at < delete_at


def test_nsis_postuninstall_stops_and_can_remove_the_wsl_station() -> None:
    """F-RC3-8 regression guard (v1.0.0-rc3 clean-VM gauntlet): the rc3
    uninstaller reported "completed successfully" while the WSL station kept
    RUNNING and serving /health 200, and the distro + CivicCast data survived
    even with "Delete the application data" checked. The uninstall hook must
    (a) ALWAYS terminate the distro so no service outlives its uninstaller,
    (b) unregister the distro and remove the CivicCast data dirs ONLY under
    the delete-app-data checkbox, (c) prefer Sysnative wsl.exe so a 32-bit
    uninstaller survives System32 redirection, and (d) say honestly what is
    kept when the box is unchecked."""
    hooks = NSIS_HOOKS.read_text(encoding="utf-8")
    post = hooks[hooks.index("!macro NSIS_HOOK_POSTUNINSTALL") :]

    terminate_at = post.index("--terminate CivicCast-Ubuntu-24.04")
    checkbox_at = post.index("${If} $DeleteAppDataCheckboxState = 1")
    unregister_at = post.index("--unregister CivicCast-Ubuntu-24.04")

    # Terminate is unconditional (before the checkbox branch); unregister and
    # data removal live inside it.
    assert terminate_at < checkbox_at < unregister_at
    assert 'RMDir /r /REBOOTOK "$PROFILE\\.civiccast"' in post
    assert 'RMDir /r /REBOOTOK "$PROFILE\\AppData\\Local\\CivicCast"' in post
    assert 'RMDir /r /REBOOTOK "$INSTDIR"' in post
    assert "%WINDIR%\\Sysnative\\wsl.exe" in post
    # F-RC4-1: the kept-data (unchecked) message must give a followable removal
    # path, NOT tell the operator to rerun the uninstaller that just self-deleted.
    assert "Application data kept" in post
    assert "wsl --unregister CivicCast-Ubuntu-24.04" in post
    assert "Rerun the uninstaller" not in post


def test_nsis_headless_bootstrap_provisions_wsl_and_runtime_without_tauri() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert "function Get-WslExe" in source
    assert 'Join-Path $windowsRoot "Sysnative\\wsl.exe"' in source
    assert 'Join-Path $windowsRoot "System32\\wsl.exe"' in source
    assert 'Get-Command -Name "wsl.exe"' in source
    assert 'Write-Log "Resolved wsl.exe to $candidate"' in source
    assert "wsl-status-preflight" in source
    assert 'Invoke-Logged "wsl-status-preflight" (Get-WslExe)' in source
    assert "install-ubuntu-2404-user-web-download" in source
    assert "Ubuntu-24.04" in source
    assert "headless-root-bootstrap" in source
    assert "headless-runtime-bootstrap" in source
    assert "civiccast.app:create_app --factory --host 127.0.0.1 --port 8000" in source
    assert "FfmpegScheduledCapturePipeline" in source
    assert "ScheduledRecordingAssetFinalizer" in source
    assert "RecordingAlertSink" in source
    assert "BOOTSTRAP_INSTANCE_ID=" in source
    assert "CIVICCAST_EXPECTED_VERSION=" in source
    assert "CIVICCAST_RUNTIME_IDENTITY" in source
    assert "unset PYTHONPATH" in source
    assert "PYTHONNOUSERSITE=1" in source
    assert 'exec "${release_root}/venv/bin/python" -I -m uvicorn' in source
    assert 'Write-State "runtime" "ready"' in source


def test_nsis_headless_bootstrap_redacts_secret_material_before_logging() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    write_log = source[
        source.index("function Write-Log") : source.index("function Repair-ExistingLogSecrets")
    ]
    repair_log = source[
        source.index("function Repair-ExistingLogSecrets") : source.index("function Write-State")
    ]
    try_block = source[source.index("try {") :]

    assert "function Redact-LogMessage" in source
    assert "Redact-LogMessage $Message" in write_log
    assert "Redact-LogMessage $_" in repair_log
    assert "Repair-ExistingLogSecrets" in try_block
    assert try_block.index("Repair-ExistingLogSecrets") < try_block.index(
        'Write-Log "CivicCast headless bootstrap starting.'
    )
    for secret_marker in (
        "SETUP_NONCE",
        "BOOTSTRAP_INSTANCE_ID",
        "RECOVERY",
        "Bearer",
        "PASSWORD",
        "SECRET",
        "API[_-]?KEY",
        "nonce=",
    ):
        assert secret_marker in source


def test_release_builder_preserves_headless_bootstrap_resource() -> None:
    source = BUILD_RELEASE.read_text(encoding="utf-8")
    assert '"headless-bootstrap.ps1"' in source
    assert '{".gitkeep", "headless-bootstrap.ps1"}' in source


def test_tauri_progress_read_is_attempted_before_browser_storage_fallback() -> None:
    source = INSTALLER_API.read_text(encoding="utf-8")

    function_start = source.index("export async function loadInstallerProgress")
    function_end = source.index("\n}\n\nasync function runTauriInstallerAction", function_start)
    function_body = source[function_start:function_end]

    assert '"read_local_installer_state"' in function_body
    assert '"readLocalInstallerState"' in function_body
    # The native read is attempted before the browser-cache fallback: the
    # invoke call precedes the only remaining browserProgress() use, which now
    # lives in the catch branch (reached only when the native bridge throws).
    assert function_body.index('"read_local_installer_state"') < function_body.index(
        "return browserProgress();"
    )
    assert function_body.index("} catch") < function_body.index("return browserProgress();")
    assert 'if (!("__TAURI_INTERNALS__" in window))' not in function_body


def test_tauri_progress_reader_stays_in_current_windows_user_profile() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert "fn installer_state_candidate_paths" in source
    assert 'std::env::var_os("USERPROFILE")' in source
    assert '.join(".civiccast")' in source
    assert 'std::env::var_os("SystemDrive")' not in source
    assert '.join("Users")' not in source
    assert "current_user_installer_state_candidate_paths" in source
    assert "newest_existing_installer_state_path" in source
    assert "existing.sort_by" in source

    reader_start = source.index("fn read_local_installer_state")
    reader_end = source.index("\n}\n\n#[tauri::command", reader_start)
    reader = source[reader_start:reader_end]

    assert "newest_existing_installer_state_path" in reader
    assert "let path = installer_state_path()?" not in reader


def test_packaged_installer_has_error_state_instead_of_infinite_loading() -> None:
    api_source = INSTALLER_API.read_text(encoding="utf-8")
    app_source = (ROOT / "civiccast" / "apps" / "installer" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    assert "knownProgress?: InstallerProgress | null" in api_source
    assert "const progress = knownProgress === undefined" in api_source
    assert "const fallbackProgress = knownProgress === undefined" in api_source
    assert "const loadState = async () =>" in app_source
    assert "try {" in app_source
    assert "catch (error)" in app_source
    assert 'label: "Installer state"' in app_source
    assert "Close and reopen the installer, then retry the proof." in app_source


def test_runtime_bootstrap_runs_in_background_and_surfaces_progress() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    app_source = (ROOT / "civiccast" / "apps" / "installer" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    assert "fn launch_civiccast_runtime_bootstrap" in source
    assert 'write_installer_state(\n        &lane_id,\n        "running"' in source
    assert "std::thread::spawn(move || {" in source
    assert 'write_installer_state(\n                &lane_id,\n                "error"' in source
    assert "launch_civiccast_runtime_bootstrap(app, lane_id)" in source
    assert 'launch_civiccast_runtime_bootstrap(app, "runtime".to_string())' in source
    assert "window.setInterval" in app_source
    assert "refreshRuntimeProgress" in app_source
    assert 'progress?.current_lane_id !== "runtime" || progress.status !== "running"' in app_source


def test_runtime_bootstrap_stages_venv_before_installing_packaged_wheel() -> None:
    # Bootstrap dedupe (rc.5): the venv/wheel/service pipeline is single-sourced
    # in headless-bootstrap.ps1; main.rs shells out to it (see
    # test_tauri_runtime_bootstrap_shells_out_to_headless_bootstrap_script)
    # instead of maintaining a second copy of this logic.
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]

    install_dirs = script.index('install -d -o "${service_user}" -g "${service_group}"')
    stage_release = script.index('staging_root="$(mktemp -d')
    create_venv = script.index('python3 -m venv "${venv}"')
    pip_install = script.index('"${venv}/bin/python" -m pip install')

    assert install_dirs < stage_release < create_venv < pip_install
    assert 'rm -rf "${venv}"' not in script


def test_installed_console_script_survives_atomic_relocation(tmp_path: Path) -> None:
    """D1/R1: relocate a staged venv with the SAME mechanism the installer uses
    (atomic `mv` of the whole staging dir into its release path), then EXECUTE
    the installed console script for real. rc16 leaves every pip-generated
    shebang pointing at the deleted staging path (invalid interpreter, CLI
    dead); the fix must rehome those shebangs in place during cutover.
    """
    script = _runtime_bash()
    mv_marker = script.index('mv -- "${staging_root}" "${release_path}"')
    # Cutover captures the pre-relocation venv path in `staged_venv` just
    # before the `mv` itself (needed by any post-relocation repair step, so
    # the extracted segment must include that capture to be runnable
    # standalone). Fall back to the `mv` line itself if no such capture
    # exists yet.
    staged_venv_marker = 'staged_venv="${venv}"'
    segment_start = (
        script.index(staged_venv_marker) if staged_venv_marker in script[:mv_marker] else mv_marker
    )
    segment_end = script.index('chown -R root:root "${release_path}"')
    relocation_segment = script[segment_start:segment_end]

    staging_root = tmp_path / "releases" / ".staging.abc123"
    release_path = tmp_path / "releases" / "1.0.0-rc17-instance"
    staged_venv_bin = staging_root / "venv" / "bin"
    staged_venv_bin.mkdir(parents=True)

    # Git Bash auto-converts a POSIX-form (`/c/...`) env var value to a native
    # Windows form when it crosses into a real (non-MSYS) executable like
    # python.exe -- so the shebang text baked into the console script (which
    # a spawned python later reads back as a plain string, not a shell var)
    # must be written in that SAME native form the embedded repair script will
    # actually compare against. Bash itself accepts native-form paths fine for
    # mv/exec (proven directly against this exact Git Bash before writing this
    # test), so use `.as_posix()` (`C:/Users/...`) uniformly here instead of
    # `_bash_path()`'s POSIX-drive form.
    def _native(path: Path) -> str:
        return path.as_posix()

    # The venv's own "python": a real interpreter (this worktree's venv),
    # reached through a bash shim so it can itself be shebang-executed like a
    # real `venv/bin/python` symlink would be.
    python_shim = staged_venv_bin / "python"
    python_shim.write_text(
        f'#!/usr/bin/env bash\nexec "{_native(Path(sys.executable))}" "$@"\n',
        encoding="utf-8",
    )
    python_shim.chmod(0o755)

    # A pip-generated console script: shebang baked to the STAGING path, the
    # exact artifact `pip install` would leave behind before cutover.
    console_script = staged_venv_bin / "civiccast"
    console_script.write_text(
        f"#!{_native(staged_venv_bin)}/python\nprint('CIVICCAST_CONSOLE_SCRIPT_OK')\n",
        encoding="utf-8",
    )
    console_script.chmod(0o755)

    harness = f"""set -euo pipefail
staging_root='{_native(staging_root)}'
release_path='{_native(release_path)}'
venv='{_native(staging_root / "venv")}'
{relocation_segment}
"${{venv}}/bin/civiccast"
"""
    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, (
        "installed console script did not survive atomic release relocation "
        f"(shebang left pointing at the deleted staging path):\n{completed.stderr}"
    )
    assert "CIVICCAST_CONSOLE_SCRIPT_OK" in completed.stdout


def test_cli_launcher_forwards_arguments_with_spaces_and_quotes_verbatim(
    tmp_path: Path,
) -> None:
    """D1/R2: EXECUTE the installed `civiccast` launcher with arguments that
    contain spaces and embedded quotes and assert they arrive at the CLI
    verbatim (no re-splitting, no mangling).
    """
    script = _runtime_bash()
    marker = script.index('cli_script="${venv}/bin/civiccast"')
    heredoc_start = script.index("<<'EOF'\n", marker) + len("<<'EOF'\n")
    heredoc_end = script.index("\nEOF\n", heredoc_start)
    launcher_body = script[heredoc_start:heredoc_end]

    release_root = tmp_path / "current"
    (release_root / "venv" / "bin").mkdir(parents=True)
    (release_root / "civiccast.env").write_text("CIVICCAST_TEST_ENV_MARKER=1\n", encoding="utf-8")
    capture_path = tmp_path / "captured-args.txt"
    fake_python = release_root / "venv" / "bin" / "python"
    fake_python.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > '{_bash_path(capture_path)}'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    rendered_launcher = launcher_body.replace(
        'release_root="/opt/civiccast/current"',
        f'release_root="{_bash_path(release_root)}"',
    )
    assert rendered_launcher != launcher_body, "launcher template did not match; nothing rendered"
    launcher_path = tmp_path / "civiccast"
    launcher_path.write_text(rendered_launcher, encoding="utf-8")
    launcher_path.chmod(0o755)

    operator_args = [
        "--channel-id",
        "public meetings room",
        'value with "embedded" quotes',
        "path/with a space/and'quote",
    ]
    completed = subprocess.run(
        [_bash(), _bash_path(launcher_path), *operator_args],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    captured = capture_path.read_text(encoding="utf-8").splitlines()
    assert captured[-len(operator_args) :] == operator_args


def test_installed_database_url_env_is_wired_and_sourceable(tmp_path: Path) -> None:
    """D1/R3: prove the installed environment carries the production
    DATABASE_URL (the installed SQLite path) by actually sourcing the
    installed env file in a fresh process and reading it back — not a string
    assertion against the script source.
    """
    script = _runtime_bash()
    fragment_start = script.index("printf '%s\\n' \"DATABASE_URL='sqlite:///${storage_db}'\"")
    export_line = script.index("export DATABASE_URL=", fragment_start)
    fragment_end = script.index("\n", export_line) + 1
    fragment = script[fragment_start:fragment_end]

    storage_db = tmp_path / "storage" / "data" / "civiccast.sqlite3"
    storage_db.parent.mkdir(parents=True)
    storage_db.touch()
    env_file = tmp_path / "civiccast.env"
    env_file.write_text("CIVICCAST_EXISTING_VAR=1\n", encoding="utf-8")

    harness = f"""set -euo pipefail
storage_db='{_bash_path(storage_db)}'
env_file='{_bash_path(env_file)}'
service_group='civiccast'
chown() {{ :; }}
{fragment}
bash -c 'set -a; . "$1"; set +a; printf "OBSERVED_DATABASE_URL=%s\\n" "$DATABASE_URL"' _ "${{env_file}}"
"""
    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    expected_url = f"sqlite:///{_bash_path(storage_db)}"
    assert f"OBSERVED_DATABASE_URL={expected_url}" in completed.stdout
    assert "DATABASE_URL=" in env_file.read_text(encoding="utf-8")
    assert "CIVICCAST_EXISTING_VAR=1" in env_file.read_text(encoding="utf-8")


def test_runtime_bootstrap_writes_start_script_before_deeper_self_checks() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]

    install_dirs = script.index('install -d -o "${service_user}" -g "${service_group}"')
    bootstrap_log = script.index('tee -a "${shared_logs}/bootstrap.log"')
    trap = script.index("BOOTSTRAP_FAILED line=${LINENO}")
    env_chmod = script.index('chmod 640 "${env_file}"')
    start_script = script.index('start_script="${staging_root}/start-civiccast.sh"')
    start_script_body = script.index(
        'install_root="/opt/civiccast"',
        start_script,
    )
    start_script_cd = script.index('cd "${release_root}"', start_script_body)
    start_script_unset = script.index("unset PYTHONPATH", start_script_body)
    start_script_identity = script.index("CIVICCAST_RUNTIME_IDENTITY", start_script_body)
    start_script_python = script.index('exec "${release_root}/venv/bin/python" -I -m uvicorn')
    storage_phase = script.index('echo "BOOTSTRAP_PHASE=storage"')
    storage_check = script.index("from civiccast.installer.storage import ensure_managed_storage")
    wiring_phase = script.index('echo "BOOTSTRAP_PHASE=preflight"')
    wiring_check = script.index("from civiccast.recording.runtime import (", wiring_phase)
    start_phase = script.index('echo "BOOTSTRAP_PHASE=start"')

    assert install_dirs < bootstrap_log < trap
    assert env_chmod < start_script < wiring_phase < wiring_check
    assert wiring_check < storage_phase < storage_check < start_phase
    assert start_script < start_script_body < start_script_cd < start_script_unset
    assert start_script_unset < start_script_identity < start_script_python
    assert script.count('start_script="${staging_root}/start-civiccast.sh"') == 1


def test_runtime_bootstrap_launches_isolated_from_stale_source_paths() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert "CIVICCAST_EXPECTED_VERSION" in source
    assert "CIVICCAST_RUNTIME_IDENTITY" in source
    assert "unset PYTHONPATH" in source
    assert "export PYTHONNOUSERSITE=1" in source
    assert " -I - <<'PY'" in source
    assert (
        " -I -m uvicorn civiccast.app:create_app --factory --host 127.0.0.1 --port 8000" in source
    )
    assert "CivicCast runtime imported version %s instead of %s" in source
    assert "from civiccast.recording.runtime import (" in source


def test_tauri_runtime_bootstrap_shells_out_to_headless_bootstrap_script() -> None:
    """Bootstrap dedupe (rc.5): main.rs must not carry its own copy of the
    WSL-provisioning/venv/service pipeline. It shells out to the single
    headless-bootstrap.ps1 the NSIS postinstall hook also invokes, so a
    typo or drift only has one place it can happen."""
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert "fn bootstrap_civiccast_runtime_via_script" in source
    assert "headless-bootstrap.ps1" in source
    assert "powershell.exe" in source
    assert "-InstallDir" in source
    # readiness comes from the service's own /health (ground truth); the old
    # serde_json state-file parse was replaced by a health-first gate (rc6).
    assert "wait_for_service_health_after_wsl_bootstrap(" in source
    assert "Some(&expected_runtime_build_id)" in source
    bootstrap_source = source.split("fn bootstrap_civiccast_runtime_via_script", 1)[1].split(
        "\nfn ", 1
    )[0]
    assert "serde_json::from_str" not in bootstrap_source
    # The old embedded reimplementation must be gone, not just unused.
    assert "let user_script = format!(" not in source
    assert "gst_runtime_archive=__GST_RUNTIME_ARCHIVE__" not in source
    assert "tsduck_version=" not in source
    assert "fn run_wsl_script" not in source


def test_runtime_bootstrap_installs_and_verifies_gstreamer_caption_runtime() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Bootstrap-RootRuntime")
    function_end = source.index("function Bootstrap-UserRuntime", function_start)
    function_body = source[function_start:function_end]

    install_start = function_body.index("apt-get install -y")
    archive_check_start = function_body.index('if [ ! -f "${gst_runtime_archive}" ]')
    hash_check_start = function_body.index('sha256sum "${gst_runtime_archive}"')
    remove_runtime_start = function_body.index('rm -rf "${gst_runtime}"')
    extract_start = function_body.index('tar -xzf "${gst_runtime_archive}"')
    verify_start = function_body.index(
        "for element in cccombiner ccconverter h264ccinserter tttocea608"
    )

    for package in (
        "python3-gi",
        "gir1.2-gstreamer-1.0",
        "gir1.2-gst-plugins-base-1.0",
        "libasound2t64",
        "libcairo-gobject2",
        "libpango-1.0-0",
        "libpangocairo-1.0-0",
        "libpulse0",
        "tar",
    ):
        assert package in function_body

    for element in ("cccombiner", "ccconverter", "h264ccinserter", "tttocea608"):
        assert '"${gst_runtime}/bin/gst-inspect-1.0" "${element}"' in function_body
        assert element in function_body

    assert install_start < verify_start
    assert "native caption-SEI runtime is still missing" in function_body
    assert "gstreamer-runtime-linux-x86_64.tar.gz" in source
    assert "1b89a2712d29bfd27cb1c5679d0ab4e423d7f5d86c3f08661aa650d359c579e3" in source
    assert "__GST_RUNTIME_SHA256__" in function_body
    assert "GStreamer runtime failed SHA-256 verification" in function_body
    assert 'gst_runtime_root="/opt/civiccast"' in function_body
    assert "GST_PLUGIN_SCANNER" in function_body
    assert "GI_TYPELIB_PATH" in function_body
    assert "exit 43" in function_body
    assert install_start < archive_check_start < hash_check_start < remove_runtime_start
    assert hash_check_start < extract_start < verify_start


def test_runtime_bootstrap_missing_resource_copy_uses_official_release_language() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert "official CivicCast GitHub release" in source
    assert "private GitHub release" not in source


def test_headless_bootstrap_stages_every_wsl_input_outside_virtualized_appdata() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert '$WslTransferRoot = Join-Path $env:USERPROFILE ".civiccast-bootstrap"' in source
    assert "function Stage-WslVisibleResources" in source
    for resource in ("gstreamer-runtime", "wheelhouse", "portal-operator", "portal-public"):
        assert f'"{resource}"' in source
    assert "$resources = $WslResourcesRoot" in source
    assert 'Join-Path $WslTransferRoot "headless-root-bootstrap.sh"' in source
    assert 'Join-Path $WslTransferRoot "headless-runtime-bootstrap.sh"' in source


def test_headless_installer_state_is_atomic_bom_free_utf8_for_javascript_polling() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    write_state = source.split("function Write-State", 1)[1].split(
        "function ConvertTo-NativeArgumentString", 1
    )[0]

    assert "UTF8Encoding($false)" in write_state
    assert "WriteAllText" in write_state
    assert "Move-Item" in write_state


def test_runtime_retry_reenters_idempotent_bootstrap_instead_of_only_starting_host() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    retry_branch = source.split('if action == "retry"', 1)[1].split(
        "if is_wsl_bootstrap_lane(&lane_id)", 1
    )[0]

    assert "launch_civiccast_runtime_bootstrap" in retry_branch
    assert "launch_runtime_host_process" not in retry_branch


def test_runtime_bootstrap_installs_and_verifies_tsduck_for_cable_probe() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Bootstrap-RootRuntime")
    function_end = source.index("function Bootstrap-UserRuntime", function_start)
    function_body = source[function_start:function_end]

    tsduck_start = function_body.index('tsduck_version="3.44-4676"')
    verify_start = function_body.index("tsp --version")

    assert 'tsduck_deb="tsduck_${tsduck_version}.ubuntu24_amd64.deb"' in function_body
    assert "03a983a5147c5f733ef89aafd23f2d83e19a9e987ae4a575a7ee62ab4b16986e" in function_body
    assert 'tsduck_deb="tsduck_${tsduck_version}.ubuntu24_arm64.deb"' in function_body
    assert "09e728567c9e1eac619a440dfd22393eaaf04c0ab09711498cd5f787a7c7cae2" in function_body
    assert "https://github.com/tsduck/tsduck/releases/download/" in function_body
    assert 'sha256sum "${tsduck_path}"' in function_body
    assert 'apt-get install -y "${tsduck_path}"' in function_body
    assert "exit 44" in function_body
    assert "exit 45" in function_body
    assert "exit 46" in function_body
    assert tsduck_start < verify_start


def test_runtime_bootstrap_verifies_tsduck_with_a_linux_only_path() -> None:
    """A protected Windows PATH entry must not make TSDuck abort in WSL."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Bootstrap-RootRuntime")
    function_end = source.index("function Bootstrap-UserRuntime", function_start)
    function_body = source[function_start:function_end]

    assert (
        "env -i HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "tsp --version"
    ) in function_body


def test_runtime_bootstrap_hands_setup_nonce_to_operator_console() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert "printf 'SETUP_NONCE=%s\\n' \"${nonce}\"" in source
    assert "printf 'BOOTSTRAP_INSTANCE_ID=%s\\n' \"${bootstrap_instance_id}\"" in source
    assert "CIVICCAST_BOOTSTRAP_INSTANCE_ID='${bootstrap_instance_id}'" in source
    assert 'operator_console_url":"${operator_url_with_nonce}' in source
    assert 'Write-State "runtime" "ready"' in source


def test_runtime_bootstrap_verifies_windows_can_reach_health_before_ready() -> None:
    """The headless bootstrap script self-verifies /health before declaring
    ready; main.rs additionally re-verifies it independently over a real TCP
    connection after the script exits (defense in depth, orthogonal to which
    process did the provisioning)."""
    headless_source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    tauri_source = TAURI_MAIN.read_text(encoding="utf-8")

    assert 'with urlopen("__SERVICE_URL__/health"' in headless_source
    assert "bootstrap_instance_id" in headless_source
    assert 'payload.get("version") == "__CIVICCAST_VERSION__"' in headless_source

    assert "fn wait_for_service_health_after_wsl_bootstrap(" in tauri_source
    assert "fn service_health_reachable_once(" in tauri_source
    assert "GET /health HTTP/1.1" in tauri_source
    assert "CivicCast reported ready inside the Windows helper" in tauri_source
    function_start = tauri_source.index("fn bootstrap_civiccast_runtime_via_script")
    function_end = tauri_source.index("\n#[cfg(target_os", function_start)
    function_body = tauri_source[function_start:function_end]
    assert "wait_for_service_health_after_wsl_bootstrap(" in function_body
    assert "Some(&expected_runtime_build_id)" in function_body


def test_runtime_bootstrap_records_scheduled_recording_runtime_identity() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]

    # A fresh station is intentionally in local setup mode until its managed
    # storage is prepared, so the bootstrap cannot require the durable
    # recording-service override yet. It still records the installed runtime
    # implementation in the identity evidence.
    assert "CivicCast scheduled recording runtime is not wired" not in script
    assert "CIVICCAST_RUNTIME_IDENTITY" in script
    assert "FfmpegScheduledCapturePipeline" in script
    assert "ScheduledRecordingAssetFinalizer" in script
    assert "RecordingAlertSink" in script


def test_runtime_bootstrap_keeps_station_state_in_managed_storage() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]

    assert "CIVICCAST_MANAGED_STORAGE_DIR='${shared_storage}'" in script
    assert "CIVICCAST_STATION_STATE_PATH='${shared_storage}/station-state.json'" in script
    assert script.index("CIVICCAST_MANAGED_STORAGE_DIR=") < script.index(
        "CIVICCAST_STATION_STATE_PATH="
    )


def test_runtime_bootstrap_systemd_service_is_unprivileged_hardened_and_observable() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]
    unit_start = script.index("[Unit]")
    unit_end = script.index("UNIT", unit_start)
    unit = script[unit_start:unit_end]

    assert "legacy_user=__LEGACY_USER__" in script
    assert 'service_user="civiccast"' in script
    assert 'service_home="/var/lib/civiccast/home"' in script
    assert 'install_root="/opt/civiccast"' in script
    assert "useradd --system" in script
    assert 'chown -R root:root "${release_path}"' in script
    assert 'account_shell}" != "/usr/sbin/nologin"' in script
    assert 'account_uid}" -ge 1000' in script
    assert '"$(id -Gn "${service_user}")" != "${service_group}"' in script
    assert 'cutover_backup_root="$(mktemp -d /run/civiccast-cutover.' in script
    assert 'chown root:root "${cutover_backup_root}"' in script
    assert "User=${service_user}" in unit
    assert "Group=${service_group}" in unit
    assert "EnvironmentFile=${current_link}/civiccast.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "PrivateTmp=true" in unit
    assert "ProtectSystem=full" in unit
    assert "ProtectHome=" not in unit
    assert "ReadWritePaths=" not in unit
    assert "TimeoutStopSec=20" in unit
    assert "StandardOutput=append:${shared_logs}/civiccast.log" in unit
    assert "StandardError=append:${shared_logs}/civiccast.log" in unit
    assert "systemctl is-enabled --quiet civiccast" in script
    assert "systemctl is-active --quiet civiccast" in script
    assert "systemctl status civiccast --no-pager" in script
    assert "journalctl -u civiccast --no-pager -n 100" in script
    assert "restoring the pre-cutover state" in script
    assert "exit 48" in script
    assert "refusing an unsupervised fallback" in script
    assert 'return Invoke-WslBashScript "headless-runtime-bootstrap" $path $true' in source
    assert 'ln -s "${release_path}" "${current_link}.next"' in script
    assert 'mv -Tf "${current_link}.next" "${current_link}"' in script
    assert "rollback_cutover" in script
    assert "BOOTSTRAP_PHASE=external-storage-access" in script
    assert ".civiccast-service-access-" in script
    assert 'for name in ("CIVICCAST_NAS_ARCHIVE_PATH", "CIVICCAST_BACKUP_DIR")' in script


def test_runtime_bootstrap_restores_service_group_execute_after_release_cutover() -> None:
    """The systemd unit runs as the unprivileged CivicCast account.

    Finalizing a release deliberately makes the tree root-owned, but the
    service launcher and its environment file must then regain the service
    group modes. Otherwise systemd exits with 203/EXEC on a clean station.
    """
    script = _runtime_bash()
    cutover = script[
        script.index('mv -- "${staging_root}" "${release_path}"') : script.index(
            'cutover_backup_root="$(mktemp -d /run/civiccast-cutover.'
        )
    ]

    root_ownership = cutover.index('chown -R root:root "${release_path}"')
    launcher_path = cutover.index('start_script="${release_path}/start-civiccast.sh"')
    launcher_group = cutover.index('chown root:"${service_group}" "${start_script}" "${env_file}"')
    launcher_mode = cutover.index('chmod 750 "${start_script}"')

    assert root_ownership < launcher_path < launcher_group < launcher_mode


def test_runtime_bootstrap_accepts_the_locked_service_account_contract() -> None:
    runtime = _runtime_bash()
    start = runtime.index('service_passwd="$(getent passwd "${service_user}")"')
    end = runtime.index("install -d -o root -g root -m 0755", start)
    validation = runtime[start:end]
    harness = f"""set -euo pipefail
service_user='civiccast'
service_group='civiccast'
service_home='/var/lib/civiccast/home'
getent() {{
  if [ "$1" = 'passwd' ]; then
    printf '%s\n' 'civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin'
  else
    printf '%s\n' 'civiccast:x:991:'
  fi
}}
id() {{
  if [ "${{1:-}}" = '-Gn' ]; then
    printf '%s\n' 'civiccast'
  fi
}}
{validation}
printf '%s\n' VALID_ACCOUNT
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "VALID_ACCOUNT\n"


@pytest.mark.parametrize(
    ("service_entry", "uid_entries", "passwd_entries", "group_entry", "gid_entries"),
    [
        (
            "civiccast:x:0:0::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:0:0::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:0:0::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:0:",
            "civiccast:x:0:",
        ),
        (
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin\n"
            "intruder:x:992:991::/home/intruder:/bin/bash",
            "civiccast:x:991:",
            "civiccast:x:991:",
        ),
        (
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin",
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin\n"
            "uid-alias:x:991:992::/home/uid-alias:/bin/bash",
            "civiccast:x:991:991::/var/lib/civiccast/home:/usr/sbin/nologin\n"
            "uid-alias:x:991:992::/home/uid-alias:/bin/bash",
            "civiccast:x:991:",
            "civiccast:x:991:\ngid-alias:x:991:",
        ),
    ],
)
def test_runtime_bootstrap_rejects_privileged_or_shared_service_identities(
    service_entry: str,
    uid_entries: str,
    passwd_entries: str,
    group_entry: str,
    gid_entries: str,
) -> None:
    runtime = _runtime_bash()
    start = runtime.index('service_passwd="$(getent passwd "${service_user}")"')
    end = runtime.index("install -d -o root -g root -m 0755", start)
    validation = runtime[start:end]
    uid = service_entry.split(":")[2]
    gid = service_entry.split(":")[3]
    harness = f"""set -euo pipefail
service_user='civiccast'
service_group='civiccast'
service_home='/var/lib/civiccast/home'
getent() {{
  case "$1:${{2:-}}" in
    passwd:civiccast) printf '%s\n' '{service_entry}' ;;
    passwd:{uid}) printf '%s\n' '{uid_entries}' ;;
    passwd:) printf '%s\n' '{passwd_entries}' ;;
    group:civiccast) printf '%s\n' '{group_entry}' ;;
    group:{gid}) printf '%s\n' '{gid_entries}' ;;
    group:) printf '%s\n' '{gid_entries}' ;;
  esac
}}
id() {{ printf '%s\n' 'civiccast'; }}
{validation}
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 47
    assert "locked system-account contract" in completed.stderr


def test_runtime_bootstrap_rejects_hostile_legacy_nonce_without_execution(tmp_path: Path) -> None:
    runtime = _runtime_bash()
    start = runtime.index('nonce_file="${shared_root}/setup-nonce"')
    end = runtime.index("bootstrap_instance_id=", start)
    nonce_selection = runtime[start:end]
    shared_root = tmp_path / "shared"
    legacy_root = tmp_path / "legacy"
    sentinel = tmp_path / "nonce-executed"
    shared_root.mkdir()
    legacy_root.mkdir()
    (legacy_root / "setup-nonce").write_text(
        f"x'; touch '{_bash_path(sentinel)}'; #'\n", encoding="utf-8"
    )
    harness = f"""set -euo pipefail
shared_root='{_bash_path(shared_root)}'
legacy_root='{_bash_path(legacy_root)}'
venv='{_bash_path(tmp_path / "unused-venv")}'
{nonce_selection}
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 46
    assert "invalid token format" in completed.stderr
    assert not sentinel.exists()


def test_runtime_bootstrap_embedded_bash_parses() -> None:
    completed = subprocess.run(
        [_bash(), "-n"], input=_runtime_bash(), text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr


def test_rendered_systemd_unit_passes_systemd_analyze(tmp_path: Path) -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze is available on the Linux cleanroom runner")
    script = _runtime_bash()
    unit = script[script.index("[Unit]") : script.index("\nUNIT", script.index("[Unit]"))]
    unit = (
        unit.replace("User=${service_user}", "User=nobody")
        .replace("Group=${service_group}", "Group=nogroup")
        .replace("WorkingDirectory=${current_link}", "WorkingDirectory=/tmp")
        .replace("EnvironmentFile=${current_link}/civiccast.env", "EnvironmentFile=-/dev/null")
        .replace("ExecStart=${current_link}/start-civiccast.sh", "ExecStart=/bin/true")
        .replace("StandardOutput=append:${shared_logs}/civiccast.log", "StandardOutput=null")
        .replace("StandardError=append:${shared_logs}/civiccast.log", "StandardError=null")
    )
    unit_path = tmp_path / "civiccast.service"
    unit_path.write_text(f"{unit}\n", encoding="utf-8")

    completed = subprocess.run(
        [analyzer, "verify", str(unit_path)], text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr


def test_runtime_bootstrap_resolves_legacy_wsl_identity_before_root_cutover() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    context_start = source.index("function Get-WslDefaultUserContext")
    context_end = source.index("function Bootstrap-RootRuntime", context_start)
    context = source[context_start:context_end]

    assert "CIVICCAST_USER_CONTEXT=%s|%s|%s" in context
    assert '"$(id -un)" "$(id -gn)" "$HOME"' in context
    assert '$match.Groups[1].Value -eq "root"' not in context
    assert "existing data owner" in context
    assert '.Replace(\n        "__LEGACY_USER__"' in source
    assert 'return Invoke-WslBashScript "headless-runtime-bootstrap" $path $true' in source


def test_legacy_pid_cleanup_refuses_an_unrelated_reused_pid(tmp_path: Path) -> None:
    script = _runtime_bash()
    function = _bash_function(script, "stop_legacy_nohup")
    proc_root = tmp_path / "proc"
    run_root = tmp_path / "run"
    (proc_root / "4242").mkdir(parents=True)
    run_root.mkdir()
    (proc_root / "4242" / "cmdline").write_bytes(b"python\x00unrelated.py\x00")
    (run_root / "civiccast.pid").write_text("4242\n", encoding="utf-8")
    function = function.replace("/proc/${pid}", f"{_bash_path(proc_root)}/${{pid}}")
    harness = f"""set -euo pipefail
legacy_root='{_bash_path(tmp_path)}'
legacy_user='station'
shared_logs='{_bash_path(tmp_path / "logs")}'
legacy_was_running=0
kill() {{ printf 'KILL %s\\n' "$*"; return 99; }}
id() {{ printf '1000\\n'; }}
stat() {{ printf '1000\\n'; }}
{function}
stop_legacy_nohup
printf 'LEGACY=%s\\n' "$legacy_was_running"
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 50, completed.stderr
    assert "Refusing to stop PID 4242" in completed.stderr
    assert "KILL" not in completed.stdout
    assert (run_root / "civiccast.pid").exists()


def test_legacy_pid_cleanup_stops_only_the_exact_civiccast_runtime(tmp_path: Path) -> None:
    script = _runtime_bash()
    function = _bash_function(script, "stop_legacy_nohup")
    proc_root = tmp_path / "proc"
    run_root = tmp_path / "run"
    (proc_root / "4242").mkdir(parents=True)
    run_root.mkdir()
    legacy_root = _bash_path(tmp_path)
    cmdline = (
        f"{legacy_root}/venv/bin/python\x00-I\x00-m\x00uvicorn\x00"
        "civiccast.app:create_app\x00--factory\x00--host\x00127.0.0.1\x00--port\x008000\x00"
    )
    (proc_root / "4242" / "cmdline").write_bytes(cmdline.encode())
    (run_root / "civiccast.pid").write_text("4242\n", encoding="utf-8")
    function = function.replace("/proc/${pid}", f"{_bash_path(proc_root)}/${{pid}}")
    harness = f"""set -euo pipefail
legacy_root='{legacy_root}'
legacy_user='station'
shared_logs='{_bash_path(tmp_path / "logs")}'
legacy_was_running=0
id() {{ printf '1000\\n'; }}
stat() {{ printf '1000\\n'; }}
kill() {{
  printf 'KILL %s\\n' "$*"
  [ "${{1:-}}" != '-0' ]
}}
{function}
stop_legacy_nohup
printf 'LEGACY=%s\\n' "$legacy_was_running"
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert "KILL 4242" in completed.stdout
    assert "KILL -0 4242" in completed.stdout
    assert "LEGACY=1" in completed.stdout
    assert not (run_root / "civiccast.pid").exists()


def test_legacy_state_migration_copies_and_verifies_root_owned_layout(tmp_path: Path) -> None:
    function = _migration_function()
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage" / "data").mkdir(parents=True)
    shared_root.mkdir()
    (legacy_root / "storage" / "data" / "civiccast.sqlite3").write_bytes(b"legacy-db")
    (legacy_root / "storage" / "station-state.json").write_text(
        '{"station":"kept"}\n', encoding="utf-8"
    )
    (legacy_root / "setup-nonce").write_text("legacy-nonce\n", encoding="utf-8")
    harness = f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
    nonce_file='{_bash_path(shared_root / "setup-nonce")}'
    migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
    migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
    nonce='legacy-nonce'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
    service_group='civiccast'
    migration_performed=0
    nonce_created=0
chown() {{ return 0; }}
chmod() {{ return 0; }}
{function}
migrate_legacy_state
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert (shared_root / "storage" / "data" / "civiccast.sqlite3").read_bytes() == b"legacy-db"
    assert (shared_root / "storage" / "station-state.json").read_text(encoding="utf-8") == (
        '{"station":"kept"}\n'
    )
    assert (shared_root / "setup-nonce").read_text(encoding="utf-8") == "legacy-nonce\n"
    marker = shared_root / "legacy-migration-complete"
    pending = shared_root / "legacy-migration-pending"
    assert marker.read_text(encoding="utf-8") == f"legacy_root={_bash_path(legacy_root)}\n"
    assert pending.exists(), "pending receipt remains until candidate health commits migration"

    # Candidate health atomically commits the managed copy by removing the
    # pending receipt; the managed copy may then diverge from legacy rollback data.
    pending.unlink()
    managed_state = shared_root / "storage" / "station-state.json"
    managed_state.write_text('{"station":"updated"}\n', encoding="utf-8")
    repeated = subprocess.run([_bash()], input=harness, text=True, capture_output=True, check=False)
    assert repeated.returncode == 0, repeated.stderr
    assert managed_state.read_text(encoding="utf-8") == '{"station":"updated"}\n'


def test_legacy_state_migration_fails_closed_on_conflicting_target(tmp_path: Path) -> None:
    function = _migration_function()
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage").mkdir(parents=True)
    (shared_root / "storage").mkdir(parents=True)
    (legacy_root / "storage" / "station-state.json").write_text("legacy\n", encoding="utf-8")
    target = shared_root / "storage" / "station-state.json"
    target.write_text("managed\n", encoding="utf-8")
    harness = f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
    nonce_file='{_bash_path(shared_root / "setup-nonce")}'
    migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
    migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce='legacy-nonce'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
    service_group='civiccast'
    migration_performed=0
    nonce_created=0
{function}
migrate_legacy_state
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 51
    assert "conflicting legacy and managed storage" in completed.stderr
    assert target.read_text(encoding="utf-8") == "managed\n"


def test_failed_first_migration_is_removed_before_legacy_retry(tmp_path: Path) -> None:
    runtime = _runtime_bash()
    migrate = _migration_function()
    rollback = _bash_function(runtime, "rollback_cutover")
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage").mkdir(parents=True)
    shared_root.mkdir()
    legacy_state = legacy_root / "storage" / "station-state.json"
    legacy_state.write_text("v1\n", encoding="utf-8")
    migration_harness = f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
nonce_file='{_bash_path(shared_root / "setup-nonce")}'
migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce='nonce-v1'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
service_group='civiccast'
migration_performed=0
nonce_created=0
chown() {{ return 0; }}
chmod() {{ return 0; }}
{migrate}
migrate_legacy_state
"""
    first = subprocess.run(
        [_bash()], input=migration_harness, text=True, capture_output=True, check=False
    )
    assert first.returncode == 0, first.stderr
    assert (shared_root / "storage" / "station-state.json").read_text(encoding="utf-8") == "v1\n"

    rollback_harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "unit")}'
unit_backup='{_bash_path(tmp_path / "unit-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(tmp_path / "rollback-evidence")}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=0
legacy_was_running=0
storage_snapshot_ready=0
migration_performed=1
migration_owned_by_this_attempt=1
migration_marker_preexisting=0
nonce_created=1
shared_storage='{_bash_path(shared_root / "storage")}'
migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce_file='{_bash_path(shared_root / "setup-nonce")}'
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(shared_root / "logs")}'
systemctl() {{ return 0; }}
{rollback}
rollback_cutover
"""
    failed = subprocess.run(
        [_bash()], input=rollback_harness, text=True, capture_output=True, check=False
    )
    assert failed.returncode == 0, failed.stderr
    assert not (shared_root / "storage").exists()
    assert not (shared_root / "legacy-migration-complete").exists()

    legacy_state.write_text("v2-after-rollback\n", encoding="utf-8")
    retried = subprocess.run(
        [_bash()], input=migration_harness, text=True, capture_output=True, check=False
    )
    assert retried.returncode == 0, retried.stderr
    assert (shared_root / "storage" / "station-state.json").read_text(encoding="utf-8") == (
        "v2-after-rollback\n"
    )


def test_interrupted_migration_receipt_discards_candidate_state_before_retry(
    tmp_path: Path,
) -> None:
    migrate = _migration_function()
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage").mkdir(parents=True)
    shared_root.mkdir()
    legacy_state = legacy_root / "storage" / "station-state.json"
    legacy_state.write_text("legacy-v1\n", encoding="utf-8")
    harness = f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
nonce_file='{_bash_path(shared_root / "setup-nonce")}'
migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce='nonce-v1'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
service_group='civiccast'
migration_performed=0
nonce_created=0
chown() {{ return 0; }}
chmod() {{ return 0; }}
{migrate}
migrate_legacy_state
"""
    first = subprocess.run([_bash()], input=harness, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    assert (shared_root / "legacy-migration-pending").exists()
    managed_state = shared_root / "storage" / "station-state.json"
    managed_state.write_text("uncommitted-candidate-write\n", encoding="utf-8")
    legacy_state.write_text("legacy-v2-after-power-loss\n", encoding="utf-8")

    retried = subprocess.run([_bash()], input=harness, text=True, capture_output=True, check=False)

    assert retried.returncode == 0, retried.stderr
    assert "recovering an interrupted legacy migration" in retried.stdout
    assert managed_state.read_text(encoding="utf-8") == "legacy-v2-after-power-loss\n"
    assert (shared_root / "legacy-migration-pending").exists()


def test_interrupted_migration_commits_exact_healthy_candidate_without_data_loss(
    tmp_path: Path,
) -> None:
    migrate = _migration_function()
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage").mkdir(parents=True)
    shared_root.mkdir()
    (legacy_root / "storage" / "station-state.json").write_text(
        "legacy-before-cutover\n", encoding="utf-8"
    )
    candidate_release = shared_root / "candidate-candidate-1"

    def harness(previous_current: str = "", previous_identity: str = "") -> str:
        return f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
nonce_file='{_bash_path(shared_root / "setup-nonce")}'
migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce='nonce-v1'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
service_group='civiccast'
migration_performed=0
migration_owned_by_this_attempt=0
migration_marker_preexisting=0
nonce_created=0
previous_current='{previous_current}'
previous_health_identity='{previous_identity}'
chown() {{ return 0; }}
chmod() {{ return 0; }}
{migrate}
migrate_legacy_state
"""

    first = subprocess.run([_bash()], input=harness(), text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    managed_state = shared_root / "storage" / "station-state.json"
    managed_state.write_text("live-post-cutover-data\n", encoding="utf-8")
    pending = shared_root / "legacy-migration-pending"
    pending.write_text(
        pending.read_text(encoding="utf-8").replace(
            "version=__CIVICCAST_VERSION__", "version=1.0.0rc11"
        ),
        encoding="utf-8",
    )

    unhealthy = subprocess.run(
        [_bash()],
        input=harness(_bash_path(candidate_release), ""),
        text=True,
        capture_output=True,
        check=False,
    )
    assert unhealthy.returncode == 51
    assert "activated interrupted migration" in unhealthy.stderr
    assert managed_state.read_text(encoding="utf-8") == "live-post-cutover-data\n"
    assert pending.exists()

    exact_identity = '{"version":"1.0.0rc11","bootstrap_instance_id":"candidate-1"}'

    recovered = subprocess.run(
        [_bash()],
        input=harness(_bash_path(candidate_release), exact_identity),
        text=True,
        capture_output=True,
        check=False,
    )

    assert recovered.returncode == 0, recovered.stderr
    assert "verifying the exact healthy runtime" in recovered.stdout
    assert managed_state.read_text(encoding="utf-8") == "live-post-cutover-data\n"
    assert not pending.exists()


def test_interrupted_migration_preserves_managed_data_when_legacy_source_is_missing(
    tmp_path: Path,
) -> None:
    migrate = _migration_function()
    legacy_root = tmp_path / "legacy"
    shared_root = tmp_path / "managed"
    (legacy_root / "storage").mkdir(parents=True)
    shared_root.mkdir()
    legacy_state = legacy_root / "storage" / "station-state.json"
    legacy_state.write_text("legacy-v1\n", encoding="utf-8")
    harness = f"""set -euo pipefail
legacy_root='{_bash_path(legacy_root)}'
shared_root='{_bash_path(shared_root)}'
shared_storage='{_bash_path(shared_root / "storage")}'
nonce_file='{_bash_path(shared_root / "setup-nonce")}'
migration_marker='{_bash_path(shared_root / "legacy-migration-complete")}'
migration_pending='{_bash_path(shared_root / "legacy-migration-pending")}'
nonce='nonce-v1'
bootstrap_instance_id='candidate-1'
service_user='civiccast'
service_group='civiccast'
migration_performed=0
migration_owned_by_this_attempt=0
migration_marker_preexisting=0
nonce_created=0
previous_current=''
previous_health_identity=''
chown() {{ return 0; }}
chmod() {{ return 0; }}
{migrate}
migrate_legacy_state
"""
    first = subprocess.run([_bash()], input=harness, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    managed_state = shared_root / "storage" / "station-state.json"
    managed_state.write_text("only-surviving-managed-data\n", encoding="utf-8")
    copy_failure_harness = harness.replace(
        "chown() { return 0; }", "cp() { return 1; }\nchown() { return 0; }"
    )
    copy_failed = subprocess.run(
        [_bash()], input=copy_failure_harness, text=True, capture_output=True, check=False
    )
    assert copy_failed.returncode == 51
    assert "managed data was left untouched" in copy_failed.stderr
    assert managed_state.read_text(encoding="utf-8") == "only-surviving-managed-data\n"
    shutil.rmtree(legacy_root / "storage")

    recovered = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert recovered.returncode == 51
    assert "legacy storage is unavailable" in recovered.stderr
    assert managed_state.read_text(encoding="utf-8") == "only-surviving-managed-data\n"
    assert (shared_root / "legacy-migration-pending").exists()


def test_real_wal_sqlite_snapshot_is_restored_after_failed_cutover(tmp_path: Path) -> None:
    runtime = _runtime_bash()
    snapshot_code = _embedded_python_after(runtime, 'STORAGE_SOURCE="${storage_db}"')
    database = tmp_path / "storage" / "data" / "civiccast.sqlite3"
    backup_root = tmp_path / "root-only-cutover"
    backup = backup_root / "civiccast.sqlite3.pre-cutover"
    database.parent.mkdir(parents=True)
    backup_root.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE proof(value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof VALUES ('before-cutover')")
        connection.commit()
    env = os.environ.copy()
    env.update({"STORAGE_SOURCE": str(database), "STORAGE_BACKUP": str(backup)})
    snapped = subprocess.run(
        [sys.executable, "-I", "-c", snapshot_code],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert snapped.returncode == 0, snapped.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE proof SET value='migrated-candidate'")
        connection.commit()

    rollback = _bash_function(runtime, "rollback_cutover")
    backup_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "unit")}'
unit_backup='{_bash_path(tmp_path / "unit-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(backup_root)}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=0
legacy_was_running=0
storage_snapshot_ready=1
storage_db_existed=1
storage_config_existed=0
storage_db='{_bash_path(database)}'
storage_config='{_bash_path(tmp_path / "storage" / "managed-storage.json")}'
storage_db_backup='{_bash_path(backup)}'
storage_config_backup='{_bash_path(backup_root / "missing-config")}'
storage_db_backup_sha256='{backup_sha}'
storage_config_backup_sha256=''
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{ return 0; }}
install() {{ cp "${{@: -2:1}}" "${{@: -1}}"; }}
{rollback}
rollback_cutover
"""
    restored = subprocess.run([_bash()], input=harness, text=True, capture_output=True, check=False)
    assert restored.returncode == 0, restored.stderr
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM proof").fetchone()[0] == "before-cutover"


def test_failed_cutover_restores_previous_unit_and_release(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    old_release = tmp_path / "releases" / "old"
    new_release = tmp_path / "releases" / "new"
    old_release.mkdir(parents=True)
    new_release.mkdir()
    current_link = tmp_path / "current"
    unit_path = tmp_path / "civiccast.service"
    unit_backup = tmp_path / "civiccast.service.previous"
    systemctl_log = tmp_path / "systemctl.log"
    unit_path.write_text("new unit\n", encoding="utf-8")
    unit_backup.write_text("old unit\n", encoding="utf-8")
    storage_db = tmp_path / "storage" / "data" / "civiccast.sqlite3"
    storage_config = tmp_path / "storage" / "managed-storage.json"
    storage_db_backup = tmp_path / "run" / "civiccast.sqlite3.pre-cutover"
    storage_config_backup = tmp_path / "run" / "managed-storage.json.pre-cutover"
    storage_db.parent.mkdir(parents=True)
    storage_db_backup.parent.mkdir(parents=True)
    storage_db.write_text("migrated database\n", encoding="utf-8")
    storage_config.write_text("new config\n", encoding="utf-8")
    storage_db_backup.write_text("old database\n", encoding="utf-8")
    storage_config_backup.write_text("old config\n", encoding="utf-8")
    unit_sha = hashlib.sha256(unit_backup.read_bytes()).hexdigest()
    db_sha = hashlib.sha256(storage_db_backup.read_bytes()).hexdigest()
    config_sha = hashlib.sha256(storage_config_backup.read_bytes()).hexdigest()
    probe_python = tmp_path / "candidate" / "bin" / "python"
    probe_python.parent.mkdir(parents=True)
    probe_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    probe_python.chmod(0o755)
    harness = f"""set -euo pipefail
current_link='{_bash_path(current_link)}'
previous_current='{_bash_path(old_release)}'
unit_path='{_bash_path(unit_path)}'
unit_backup='{_bash_path(unit_backup)}'
unit_backup_sha256='{unit_sha}'
cutover_backup_root='{_bash_path(storage_db_backup.parent)}'
had_unit=1
previous_unit_active=1
previous_unit_enabled=1
legacy_was_running=0
storage_snapshot_ready=1
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
storage_db_existed=1
storage_config_existed=1
storage_db='{_bash_path(storage_db)}'
storage_config='{_bash_path(storage_config)}'
storage_db_backup='{_bash_path(storage_db_backup)}'
storage_config_backup='{_bash_path(storage_config_backup)}'
storage_db_backup_sha256='{db_sha}'
storage_config_backup_sha256='{config_sha}'
venv='{_bash_path(probe_python.parent.parent)}'
previous_health_identity='{{"version":"1.0.0-rc9","bootstrap_instance_id":"old-instance"}}'
install_root='{_bash_path(tmp_path / "install")}'
shared_logs='{_bash_path(tmp_path / "logs")}'
shared_run='{_bash_path(tmp_path / "run")}'
service_user='station'
service_group='station'
systemctl() {{ printf 'SYSTEMCTL %s\\n' "$*" >>'{_bash_path(systemctl_log)}'; return 0; }}
runuser() {{ printf 'RUNUSER %s\\n' "$*"; return 0; }}
install() {{ cp "${{@: -2:1}}" "${{@: -1}}"; }}
ln() {{ printf 'LN %s\\n' "$*"; return 0; }}
mv() {{ printf 'MV %s\\n' "$*"; return 0; }}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert (
        f"LN -s {_bash_path(old_release)} {_bash_path(current_link)}.rollback" in completed.stdout
    )
    assert (
        f"MV -Tf {_bash_path(current_link)}.rollback {_bash_path(current_link)}" in completed.stdout
    )
    assert "SYSTEMCTL restart civiccast" in systemctl_log.read_text(encoding="utf-8")
    assert "SYSTEMCTL enable civiccast" in systemctl_log.read_text(encoding="utf-8")
    assert unit_path.read_text(encoding="utf-8") == "old unit\n"
    assert storage_db.read_text(encoding="utf-8") == "old database\n"
    assert storage_config.read_text(encoding="utf-8") == "old config\n"
    assert "ROLLBACK_COMPLETE pre_cutover_state_restored=1" in completed.stderr
    assert "previous_runtime_identity_verified=1" in completed.stderr
    rollback_source = _bash_function(_runtime_bash(), "rollback_cutover")
    assert 'payload.get("version") == expected["version"]' in rollback_source
    assert (
        'payload.get("bootstrap_instance_id") == expected["bootstrap_instance_id"]'
        in rollback_source
    )


def test_unexpected_error_inside_cutover_always_invokes_rollback() -> None:
    function = _bash_function(_runtime_bash(), "on_cutover_error")
    harness = f"""set -Euo pipefail
cutover_active=1
rollback_cutover() {{ cutover_active=0; printf 'ROLLBACK\\n'; }}
{function}
trap on_cutover_error ERR
false
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 1
    assert completed.stdout == "ROLLBACK\n"
    assert "BOOTSTRAP_FAILED" in completed.stderr


def test_rollback_reports_failed_restart_instead_of_claiming_recovery(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    systemctl_log = tmp_path / "systemctl.log"
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "missing-unit")}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(tmp_path / "evidence")}'
had_unit=0
previous_unit_active=1
previous_unit_enabled=0
legacy_was_running=0
storage_snapshot_ready=0
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{
  printf 'SYSTEMCTL %s\\n' "$*" >>'{_bash_path(systemctl_log)}'
  [ "${{1:-}}" != 'restart' ]
}}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert "ROLLBACK_FAILED step=restart-previous-service" in completed.stderr
    assert "operator_action=" in completed.stderr
    assert "ROLLBACK_COMPLETE" not in completed.stderr


def test_rollback_does_not_restart_after_database_backup_integrity_failure(
    tmp_path: Path,
) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    database = tmp_path / "storage" / "civiccast.sqlite3"
    backup = tmp_path / "evidence" / "civiccast.sqlite3.pre-cutover"
    database.parent.mkdir()
    backup.parent.mkdir()
    database.write_bytes(b"candidate-database")
    wal = Path(f"{database}-wal")
    wal.write_bytes(b"committed-wal-recovery-evidence")
    backup.write_bytes(b"old-database")
    systemctl_log = tmp_path / "systemctl.log"
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "missing-unit")}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(backup.parent)}'
had_unit=0
previous_unit_active=1
previous_unit_enabled=1
legacy_was_running=0
storage_snapshot_ready=1
storage_db_existed=1
storage_config_existed=0
storage_db='{_bash_path(database)}'
storage_config='{_bash_path(tmp_path / "storage" / "managed-storage.json")}'
storage_db_backup='{_bash_path(backup)}'
storage_config_backup='{_bash_path(tmp_path / "missing-config")}'
storage_db_backup_sha256='definitely-not-the-backup-hash'
storage_config_backup_sha256=''
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{
  printf 'SYSTEMCTL %s\n' "$*" >>'{_bash_path(systemctl_log)}'
  [ "${{1:-}}" != 'is-active' ]
}}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert "ROLLBACK_FAILED step=verify-database-backup" in completed.stderr
    systemctl_calls = systemctl_log.read_text(encoding="utf-8")
    assert "daemon-reload" not in systemctl_calls
    assert "enable" not in systemctl_calls
    assert "restart" not in systemctl_calls
    assert wal.read_bytes() == b"committed-wal-recovery-evidence"
    assert database.read_bytes() == b"candidate-database"
    assert "ROLLBACK_COMPLETE" not in completed.stderr


def test_rollback_restores_previous_bootstrap_state(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    bootstrap_state = tmp_path / "bootstrap-state.json"
    bootstrap_backup = evidence / "bootstrap-state.json.pre-cutover"
    bootstrap_state.write_text('{"status":"candidate"}\n', encoding="utf-8")
    bootstrap_backup.write_text('{"status":"previous"}\n', encoding="utf-8")
    backup_sha = hashlib.sha256(bootstrap_backup.read_bytes()).hexdigest()
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "missing-unit")}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(evidence)}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=0
legacy_was_running=0
storage_snapshot_ready=0
bootstrap_state_snapshot_ready=1
bootstrap_state_existed=1
bootstrap_state='{_bash_path(bootstrap_state)}'
bootstrap_state_backup='{_bash_path(bootstrap_backup)}'
bootstrap_state_backup_sha256='{backup_sha}'
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{ [ "${{1:-}}" != 'is-active' ]; }}
install() {{ cp "${{@: -2:1}}" "${{@: -1}}"; }}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert bootstrap_state.read_text(encoding="utf-8") == '{"status":"previous"}\n'
    assert "removing the failed candidate and restoring the pre-cutover state" in completed.stderr
    assert "restoring the previous runtime" not in completed.stderr
    assert "ROLLBACK_COMPLETE" in completed.stderr


def test_rollback_restarts_legacy_runtime_with_apostrophe_path_safely(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    legacy_root = tmp_path / "legacy's home"
    (legacy_root / "logs").mkdir(parents=True)
    (legacy_root / "run").mkdir()
    start_script = legacy_root / "start-civiccast.sh"
    start_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    start_script.chmod(0o755)
    fake_python = tmp_path / "venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "missing-unit")}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(tmp_path / "evidence")}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=0
legacy_was_running=1
legacy_root="{_bash_path(legacy_root)}"
legacy_user='legacy-user'
legacy_home="{_bash_path(legacy_root)}"
venv='{_bash_path(fake_python.parent.parent)}'
previous_health_identity='{{"version":"0.1.0"}}'
storage_snapshot_ready=0
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{ [ "${{1:-}}" != 'is-active' ]; }}
runuser() {{
  shift 2
  [ "${{1:-}}" = '--' ] && shift
  "$@"
}}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert (legacy_root / "run" / "civiccast.pid").exists()
    assert "ROLLBACK_COMPLETE pre_cutover_state_restored=1" in completed.stderr
    assert "previous_runtime_identity_verified=1" in completed.stderr


def test_rollback_reports_failed_enable_state_restoration(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(tmp_path / "missing-unit")}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(tmp_path / "evidence")}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=1
legacy_was_running=0
storage_snapshot_ready=0
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{
  if [ "${{1:-}}" = 'enable' ]; then
    echo 'simulated enable diagnostic' >&2
    return 1
  fi
  return 0
}}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert "simulated enable diagnostic" in completed.stderr
    assert "ROLLBACK_FAILED step=restore-enable-state desired=enabled" in completed.stderr
    assert "ROLLBACK_COMPLETE" not in completed.stderr


def test_rollback_stop_failure_forces_unit_then_reports_if_still_active(tmp_path: Path) -> None:
    function = _bash_function(_runtime_bash(), "rollback_cutover")
    unit_path = tmp_path / "candidate.service"
    unit_path.write_text("candidate\n", encoding="utf-8")
    systemctl_log = tmp_path / "systemctl.log"
    harness = f"""set -euo pipefail
cutover_active=1
current_link='{_bash_path(tmp_path / "current")}'
previous_current=''
unit_path='{_bash_path(unit_path)}'
unit_backup='{_bash_path(tmp_path / "missing-backup")}'
unit_backup_sha256=''
cutover_backup_root='{_bash_path(tmp_path / "evidence")}'
had_unit=0
previous_unit_active=0
previous_unit_enabled=0
legacy_was_running=0
storage_snapshot_ready=0
migration_performed=0
migration_marker_preexisting=1
nonce_created=0
service_user='civiccast'
service_group='civiccast'
shared_logs='{_bash_path(tmp_path / "logs")}'
systemctl() {{
  printf 'SYSTEMCTL %s\\n' "$*" >>'{_bash_path(systemctl_log)}'
  case "${{1:-}}" in
    stop) return 1 ;;
    is-active) return 0 ;;
    *) return 0 ;;
  esac
}}
sleep() {{ return 0; }}
{function}
rollback_cutover
"""

    completed = subprocess.run(
        [_bash()], input=harness, text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    log = systemctl_log.read_text(encoding="utf-8")
    assert "SYSTEMCTL kill --kill-whom=all --signal=TERM civiccast" in log
    assert "SYSTEMCTL kill --kill-whom=all --signal=KILL civiccast" in log
    assert "ROLLBACK_FAILED step=stop-current-service" in completed.stderr
    assert "contact IT before changing storage" in completed.stderr
    assert "ROLLBACK_COMPLETE" not in completed.stderr


def test_runtime_bootstrap_env_file_does_not_source_windows_path_entries() -> None:
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    script_start = source.index("$runtimeScript = @'")
    script_end = source.index("'@", script_start)
    script = source[script_start:script_end]
    env_start = script.index('cat > "${env_file}" <<EOF')
    env_end = script.index("\nEOF", env_start)
    env_body = script[env_start:env_end]

    assert "PATH=/opt/civiccast/gstreamer/bin:${PATH}" not in env_body
    assert (
        "PATH='/opt/civiccast/gstreamer/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin'"
    ) in env_body
    assert (
        "LD_LIBRARY_PATH='/opt/civiccast/gstreamer/lib/x86_64-linux-gnu:/opt/civiccast/gstreamer/lib'"
        in env_body
    )


def test_packaged_installer_starts_runtime_from_native_startup_state() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert "fn installer_state_requests_runtime_bootstrap(raw: &str) -> bool" in source
    assert '\\"current_lane_id\\":\\"platform\\"' in source
    assert '\\"current_lane_id\\":\\"wsl2\\"' in source
    assert '\\"status\\":\\"ready\\"' in source
    assert '\\"reboot_required\\":true' in source
    assert "fn launch_startup_runtime_bootstrap_if_ready(app: tauri::AppHandle)" in source
    assert "newest_existing_installer_state_path()" in source
    assert "installer_state_requests_runtime_bootstrap(&raw)" in source
    assert 'launch_civiccast_runtime_bootstrap(app, "runtime".to_string())' in source
    assert ".setup(|app| {" in source
    assert "launch_startup_runtime_bootstrap_if_ready(app.handle().clone());" in source


def test_installer_enables_and_uses_explicit_native_bridge_paths() -> None:
    api_source = INSTALLER_API.read_text(encoding="utf-8")
    config_source = TAURI_CONFIG.read_text(encoding="utf-8")

    helper_start = api_source.index("async function invokeNativeInstaller")
    helper_end = api_source.index("\n}\n\nfunction mapStatus", helper_start)
    helper_body = api_source[helper_start:helper_end]

    assert '"withGlobalTauri": true' in config_source
    assert "__TAURI__" in helper_body
    assert "bridge.__TAURI__?.invoke" in helper_body
    assert "__TAURI_INTERNALS__" in helper_body
    assert "@tauri-apps/api/core" in helper_body
    assert helper_body.index("__TAURI__") < helper_body.index("@tauri-apps/api/core")


def test_installer_window_has_ipc_capability() -> None:
    capability = TAURI_CAPABILITY.read_text(encoding="utf-8")
    permission = TAURI_INSTALLER_ACTIONS_PERMISSION.read_text(encoding="utf-8")

    assert '"identifier": "installer-main"' in capability
    assert '"windows": ["*"]' in capability
    assert '"core:default"' in capability
    assert '"allow-installer-actions"' in capability
    assert 'identifier = "allow-installer-actions"' in permission
    assert "commands.allow" in permission
    assert '"open_operator_console"' in permission
    assert '"read_local_installer_state"' in permission
    assert '"reset_local_installer_state"' in permission
    assert '"run_local_installer_action"' in permission


def test_installer_can_open_local_operator_console_from_tauri() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    api_source = INSTALLER_API.read_text(encoding="utf-8")

    assert "fn open_operator_console" in source
    assert 'url.starts_with("http://127.0.0.1:8000/")' in source
    assert "open_operator_console," in source
    assert "invokeNativeInstallerAny<string>([" in api_source
    assert '"open_operator_console"' in api_source
    assert '"openOperatorConsole"' in api_source


def test_headless_bootstrap_updates_wsl_launcher_before_distro_install() -> None:
    """rc.5 fast-follow: an outdated wsl.exe launcher triggers a raw,
    unattended interactive prompt ("must be updated... press any key...
    times out in 60 seconds") on --install calls. Update the launcher first,
    non-interactively, before the per-distro install attempt."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Ensure-Ubuntu2404")
    function_end = source.index("function Invoke-WslBashScript", function_start)
    function_body = source[function_start:function_end]

    status_preflight = function_body.index('"wsl-status-preflight"')
    ready_check = function_body.index("Test-CivicCastUbuntuReady")
    update_preflight = function_body.index('"wsl-update-preflight"')
    install_call = function_body.index('"install-ubuntu-2404-user-web-download"')

    assert '@("--update")' in function_body
    assert status_preflight < ready_check < update_preflight < install_call


def test_headless_bootstrap_registers_persistent_runtime_host_at_logon() -> None:
    """rc12 regression: a one-shot bootstrap exits after health succeeds and
    leaves no Windows process owning the WSL lifetime.  WSL then idles the
    CivicCast distro down.  Logon must launch the persistent runtime host,
    never the destructive/full provisioning bootstrap."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert "function Ensure-RuntimeHostAutostart" in source
    assert "CivicCast Autostart" in source
    assert "--civiccast-runtime-host" in source
    autostart = source[
        source.index("function Ensure-RuntimeHostAutostart") : source.index(
            "function Test-ServiceAlreadyHealthy"
        )
    ]
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in autostart
    assert "--civiccast-bootstrap-unattended" not in autostart
    # The admin-only scheduled-task invocation must not come back (the
    # explanatory comment may still name schtasks).
    assert '"/SC", "ONLOGON"' not in autostart
    assert "schtasks.exe" not in autostart
    outer_try = source.index("\ntry {\n")
    assert source.index("function Ensure-RuntimeHostAutostart") < outer_try
    assert "Ensure-RuntimeHostAutostart" in source[outer_try:]
    assert "Start-RuntimeHost" in source[outer_try:]


def test_installer_binary_has_a_persistent_wsl_runtime_host_mode() -> None:
    """The Windows owner must remain alive after bootstrap and recover when
    the dedicated distro is terminated; a post-install health probe alone is
    not a lifecycle owner."""
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert '"--civiccast-runtime-host"' in source
    assert "fn run_civiccast_runtime_host()" in source
    assert "fn spawn_civiccast_wsl_keepalive()" in source
    host_start = source.index("fn run_civiccast_runtime_host()")
    host_end = source.index("\nfn ", host_start + 1)
    host_body = source[host_start:host_end]
    assert "spawn_civiccast_wsl_keepalive" in host_body
    assert "service_health_reachable_once(None, None)" in host_body
    assert "try_wait()" in host_body


def test_headless_bootstrap_fails_loud_when_wsl_core_is_missing() -> None:
    """PR #187 review, blocking 1: on a machine whose WSL Windows features
    were never enabled, a NON-elevated `wsl --install` (this script runs
    non-elevated -- currentUser install) can trigger wsl.exe's own secondary
    UAC consent in a different session and hang forever with no visible
    prompt (microsoft/WSL#9032, #11652). The preflight must fail loud
    (nonzero exit, clear state routing to the app's real elevated
    Set up Windows helper flow) BEFORE any --install attempt -- never hang,
    never silently exit 0."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Ensure-Ubuntu2404")
    function_end = source.index("function Invoke-WslBashScript", function_start)
    function_body = source[function_start:function_end]

    preflight = function_body.index('"wsl-status-preflight"')
    fail_exit = function_body.index("exit 1", preflight)
    install_call = function_body.index('"install-ubuntu-2404-user-web-download"')

    # fail-loud exit sits between the preflight and the first --install
    assert preflight < fail_exit < install_call
    assert "Set up Windows helper" in function_body
    assert "function Test-IsElevated" in source
    # the old silent-success behavior must be gone from the preflight block
    preflight_block = function_body[preflight:install_call]
    assert "exit 0" not in preflight_block


def test_headless_bootstrap_wsl_invocations_cannot_hang_on_interactive_prompts() -> None:
    """rc6 hang-guard: every wsl.exe call routes through Invoke-Logged, which
    invokes via Start-Process with stdin INHERITED (a stdin-closing
    ProcessStartInfo broke `wsl --status`/`--install` -- do NOT reintroduce it)
    and enforces a hard timeout plus a taskkill /T tree-kill on timeout so
    nothing can hang the unattended bootstrap forever (microsoft/WSL#13589
    class)."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    function_start = source.index("function Invoke-Logged")
    function_end = source.index("function ConvertTo-WslPath", function_start)
    function_body = source[function_start:function_end]

    assert "[int]$TimeoutSeconds" in function_body
    assert "$proc = Start-Process @spParams" in function_body
    assert "$proc.WaitForExit($TimeoutSeconds * 1000)" in function_body
    assert "taskkill.exe /T /F /PID $proc.Id" in function_body
    assert "$proc.Kill()" in function_body
    assert "timed out after $TimeoutSeconds seconds" in function_body
    assert "ConvertTo-NativeArgumentString" in function_body
    # the stdin-closing ProcessStartInfo (broke wsl flag parsing) must not return,
    # and neither may the legacy no-timeout direct-splat form
    assert "$psi.RedirectStandardInput = $true" not in function_body
    assert "& $FilePath @Arguments" not in function_body


def test_headless_bootstrap_noops_when_service_is_already_healthy() -> None:
    """PR #187 review, blocking 2: the autostart task fires at EVERY logon
    (sign-out/sign-in, second Windows account). Without a guard, the runtime
    layer unconditionally rm -rf'd the venv and killed the running service --
    killing a live broadcast. The bootstrap must check /health (+ version
    match against the expected version) FIRST and no-op when healthy."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")

    assert "function Test-ServiceAlreadyHealthy" in source
    health_fn = source[
        source.index("function Test-ServiceAlreadyHealthy") : source.index("\ntry {\n")
    ]
    assert '"$ServiceUrl/health"' in health_fn
    assert "$payload.version -eq $CivicCastVersion" in health_fn

    outer_try = source.index("\ntry {\n")
    try_body = source[outer_try:]
    guard = try_body.index("Test-ServiceAlreadyHealthy")
    noop_exit = try_body.index("exit 0", guard)
    root_runtime = try_body.index("Bootstrap-RootRuntime")
    ubuntu = try_body.index("Ensure-Ubuntu2404")
    # the guard and its no-op exit both come before any provisioning step
    assert guard < noop_exit < ubuntu < root_runtime


def test_bootstrap_normalizes_extended_length_install_dir() -> None:
    """release: 1.0.0-rc1 clean-install blocker. Tauri's resource_dir() hands
    the resume lane an extended-length (verbatim) prefixed InstallDir; PS 5.1
    provider cmdlets cannot map a PSDrive for it and the whole bootstrap died
    with 'Cannot process argument because the value of argument "drive" is
    null' on a clean Windows 11 25H2 machine (observed 2026-07-08). Both
    layers must normalize: Rust before spawning, PS at param ingest."""
    ps_source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    rust_source = TAURI_MAIN.read_text(encoding="utf-8")

    # PS side: strip happens before anything touches $InstallDir.
    strip = ps_source.index(r"$InstallDir.StartsWith('\\?\')")
    first_use = ps_source.index("Join-Path $InstallDir")
    assert strip < first_use
    assert r"$InstallDir.StartsWith('\\?\UNC\')" in ps_source

    # Rust side: the bootstrap lane simplifies the path before deriving
    # the script location and InstallDir argument. G-14/T-1: this composition
    # (normalize, THEN derive both outputs from the normalized value) was
    # promoted into its own pure function, resolved_bootstrap_paths, so it is
    # unit-tested directly on its return values (see the
    # resolved_bootstrap_paths_* tests in main.rs) rather than only by text
    # order here -- a refactor that discarded the fix (e.g.
    # `let _ = simplify_verbatim_path(...)`) would still pass a text-order
    # check like this one, but would fail those behavior tests.
    assert "fn simplify_verbatim_path" in rust_source
    assert "fn resolved_bootstrap_paths(resources_root: &Path)" in rust_source
    lane = rust_source.index("fn bootstrap_civiccast_runtime_via_script")
    assert "resolved_bootstrap_paths(&resources_root)" in rust_source[lane:]
    fn_start = rust_source.index("fn resolved_bootstrap_paths(resources_root: &Path)")
    fn_body = rust_source[fn_start : rust_source.index("\n}\n", fn_start)]
    script_derive = fn_body.index("headless_bootstrap_script_path(&resources_root)")
    simplify_use = fn_body.index("simplify_verbatim_path(resources_root)")
    assert simplify_use < script_derive


def test_autostart_task_targets_the_binary_that_actually_ships() -> None:
    """release: 1.0.0-rc1. The autostart registration probed for
    'CivicCast Installer.exe' but the built binary is civiccast-installer.exe
    (Cargo package name), so the reboot-survival task never registered on any
    install -- the station stayed off-air after every reboot. The probe must
    include the real binary name."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    autostart = source[
        source.index("function Get-CivicCastInstallerExe") : source.index(
            "function Test-ServiceAlreadyHealthy"
        )
    ]
    assert '"civiccast-installer.exe"' in autostart


def test_bootstrap_is_single_instance() -> None:
    """release: 1.0.0-rc1. The GUI lane, the unattended relaunch, and the
    logon autostart task can all run this script concurrently; two instances
    race over installer-state.json and a failing instance overwrites the
    working one's progress (observed: a stale 'exit 43' error shown while the
    service was healthy). A mutex must make later instances no-op."""
    source = HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")
    mutex = source.index("System.Threading.Mutex")
    outer_try = source.index("\ntry {\n")
    assert mutex < outer_try
    assert "CivicCastHeadlessBootstrap" in source


def test_installer_state_rewrites_preserve_the_setup_nonce_url() -> None:
    """release: 1.0.0-rc1. Every plain write_installer_state() reset
    operator_console_url to the nonce-less constant, so any state write after
    bootstrap success (e.g. an app restart) permanently lost the one-time
    setup handoff -- First Setup dead-ended with 'Could not read setup state'
    and the UI's own advice looped back to the same broken handoff."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    assert "fn preserved_operator_console_url" in source
    assert "fn nonce_operator_url_from_state" in source
    plain_writer = source[
        source.index("fn write_installer_state(") : source.index(
            "fn write_installer_state_with_operator_url("
        )
    ]
    assert "preserved_operator_console_url()" in plain_writer


def test_runtime_preflight_allows_fresh_station_local_setup_mode() -> None:
    """A fresh install has no durable storage yet, so recording wiring is absent.

    The preflight still proves the installed package identity, but it must not
    reject that expected setup-mode state before the operator can prepare
    managed storage.
    """
    preflight = _embedded_python_after(_runtime_bash(), 'echo "BOOTSTRAP_PHASE=preflight"')

    assert "from civiccast.recording.router import get_recording_service" not in preflight
    assert "app.dependency_overrides[get_recording_service]" not in preflight
    assert "CIVICCAST_RUNTIME_IDENTITY" in preflight
