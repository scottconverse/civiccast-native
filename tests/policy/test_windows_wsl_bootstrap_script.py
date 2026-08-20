# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

import json
import os
import shutil
import subprocess
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


def test_runtime_bootstrap_missing_resource_copy_uses_official_release_language() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert "official CivicCast GitHub release" in source
    assert "private GitHub release" not in source


def test_runtime_retry_reenters_idempotent_bootstrap_instead_of_only_starting_host() -> None:
    source = TAURI_MAIN.read_text(encoding="utf-8")
    retry_branch = source.split('if action == "retry"', 1)[1].split(
        "if is_wsl_bootstrap_lane(&lane_id)", 1
    )[0]

    assert "launch_civiccast_runtime_bootstrap" in retry_branch
    assert "launch_runtime_host_process" not in retry_branch


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
