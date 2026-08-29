# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Native installer runtime infrastructure: IPC capability, the local
installer-state read/write path, the background runtime host watchdog, and
the frontend's native-bridge dispatch.

Re-homed from ``test_windows_wsl_bootstrap_script.py`` (deleted): this repo
shipped a WSL2/Ubuntu installer lane alongside the native product until the
owner's "no linux" decision (2026-08-19) retired it. That file's ~45 tests
were a mix of WSL-lane-specific tests (the WSL2 feature-enable/Ubuntu
provisioning pipeline, the retired ``nsis-hooks.nsh`` hook file, the
deleted ``headless-bootstrap.ps1`` resource script) and tests of shared
installer infrastructure the native product also depends on. The WSL-lane
tests were deleted along with the code they tested; the ~13 tests below
cover infrastructure that is still real, live, and native -- carried over
(and, where the WSL purge changed the code they cover, updated to match).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI_MAIN = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs"
INSTALLER_API = ROOT / "civiccast" / "apps" / "installer" / "src" / "api.ts"
APP_TSX = ROOT / "civiccast" / "apps" / "installer" / "src" / "App.tsx"
TAURI_CONFIG = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
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


def test_runtime_retry_reenters_idempotent_bootstrap_instead_of_only_starting_host() -> None:
    """Retry on a runtime-family lane must re-enter the full idempotent
    bootstrap (launch_civiccast_runtime_bootstrap), not just start the host
    process directly -- a runtime error can mean provisioning never
    completed, and starting the host alone cannot repair that state."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    retry_branch = source.split('if action == "retry"', 1)[1].split('if action == "continue"', 1)[0]

    assert "launch_civiccast_runtime_bootstrap" in retry_branch
    assert "is_runtime_bootstrap_lane(&lane_id)" in retry_branch


def test_runtime_bootstrap_starts_the_host_process_and_reverifies_health() -> None:
    """launch_civiccast_runtime_bootstrap is the "repair"/"retry"/"continue"
    recovery for the runtime-family lanes. It replaced a pipeline that
    shelled out to the now-deleted headless-bootstrap.ps1 (the retired WSL
    lane's runtime-provisioning script): it must instead start the native
    runtime host process and re-verify /health before reporting the lane's
    outcome, running the health-affecting work off the UI thread."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "fn launch_civiccast_runtime_bootstrap" in source
    bootstrap_start = source.index("fn launch_civiccast_runtime_bootstrap")
    bootstrap_end = source.index("\nfn ", bootstrap_start + 1)
    bootstrap_body = source[bootstrap_start:bootstrap_end]

    assert 'write_installer_state(\n        &lane_id,\n        "running"' in bootstrap_body
    assert "std::thread::spawn(move || {" in bootstrap_body
    assert "launch_runtime_host_process(&app)" in bootstrap_body
    assert "wait_for_service_health_after_runtime_start(" in bootstrap_body
    assert (
        'write_installer_state(\n                &lane_id,\n                "error"'
        in bootstrap_body
    )
    # The old pipeline this replaced (shelling out to the deleted
    # headless-bootstrap.ps1) is gone as CODE, not just unused -- the
    # filename may still appear in a historical doc comment explaining the
    # replacement, so scope this to the actual function body.
    assert "headless-bootstrap.ps1" not in bootstrap_body
    assert "bootstrap_civiccast_runtime_via_script" not in source

    assert "launch_civiccast_runtime_bootstrap(app, lane_id)" in source
    assert "window.setInterval" in app_source
    assert "refreshRuntimeProgress" in app_source
    assert 'progress?.current_lane_id !== "runtime" || progress.status !== "running"' in app_source


def test_runtime_host_watchdog_only_observes_service_health_no_companion_process() -> None:
    """run_civiccast_runtime_host (spawned via --civiccast-runtime-host) used
    to spawn and monitor a companion wsl.exe process, and shell into the WSL
    distro to restart civiccast.service on repeated health failures -- both
    deleted with the WSL lane. CivicCastSupervisor is a real Windows service
    with its own SCM restart-on-failure actions
    (native_service_registration::service_failure_actions_command), so the
    watchdog's job for native is honest health observation only."""
    source = TAURI_MAIN.read_text(encoding="utf-8")

    assert '"--civiccast-runtime-host"' in source
    assert "fn run_civiccast_runtime_host()" in source
    host_start = source.index("fn run_civiccast_runtime_host()")
    host_end = source.index("\nfn ", host_start + 1)
    host_body = source[host_start:host_end]

    assert "service_health_reachable_once(None, None)" in host_body
    assert "acquire_runtime_host_lifetime_guard(RUNTIME_HOST_MUTEX_ADDR)" in host_body
    assert "installer_shutdown_marker_paths()" in host_body

    # The deleted WSL keepalive/recovery machinery must not be present as CODE
    # anywhere (definitions gone repo-wide) or referenced from the watchdog's
    # own body (a historical comment elsewhere in the file may still name
    # wsl.exe, e.g. explaining why run_bounded_command decodes UTF-16LE).
    assert "fn spawn_civiccast_wsl_keepalive" not in source
    assert "fn recover_civiccast_service" not in source
    assert "wsl.exe" not in host_body
    assert "spawn_civiccast_wsl_keepalive" not in host_body


def test_tauri_action_errors_are_not_silently_replaced_by_backend_fallback() -> None:
    source = INSTALLER_API.read_text(encoding="utf-8")

    function_start = source.index("async function runTauriInstallerAction")
    function_body = source[function_start:]
    invoke = function_body.index('"run_local_installer_action"')
    browser_fallback = function_body.index("saveBrowserInstallerProgress")
    action_error = function_body.index(
        "CivicCast could not hand this step to the local setup helper"
    )

    assert invoke < browser_fallback
    assert invoke < action_error
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
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "knownProgress?: InstallerProgress | null" in api_source
    assert "const progress = knownProgress === undefined" in api_source
    assert "const fallbackProgress = knownProgress === undefined" in api_source
    assert "const loadState = async () =>" in app_source
    assert "try {" in app_source
    assert "catch (error)" in app_source


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


def test_installer_state_rewrites_always_use_the_plain_operator_console_url() -> None:
    """The one-time setup-nonce handoff was retired: first setup is now
    admitted purely by the control plane checking the request's peer IP is
    loopback (civiccast/installer/router.py's _require_local_setup_request),
    so there is no longer a nonce-bearing URL for write_installer_state() to
    preserve or reconcile. Every write always uses the plain, fixed
    OPERATOR_CONSOLE_URL constant."""
    source = TAURI_MAIN.read_text(encoding="utf-8")
    assert "fn preserved_operator_console_url" not in source
    assert "fn nonce_operator_url_from_state" not in source
    plain_writer = source[
        source.index("fn write_installer_state(") : source.index(
            "fn write_installer_state_with_operator_url("
        )
    ]
    assert "OPERATOR_CONSOLE_URL" in plain_writer
    assert "write_installer_state_with_operator_url(" in plain_writer
