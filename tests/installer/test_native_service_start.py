"""Contract for D4: the installer must START the supervisor service, not just
register it.

`native_service_registration.rs` registers `CivicCastSupervisor` with
`--startup auto`, which only decides what the SCM does at the NEXT BOOT.
Nothing in `src-tauri/src/` ever issued a start, so a freshly installed
station had a registered, correctly configured, entirely STOPPED service --
no control plane on 127.0.0.1:8000 until the operator rebooted. A service
that registers but cannot start is an install FAILURE, not a warning, so the
D4 CLI must also fail loud on it (`nsis-hooks-bootstrap.nsh` already aborts
the install on any nonzero exit from this subcommand).

Source-shape contract, following `test_tauri_windows_manifest.py`'s existing
convention in this directory: the real `sc.exe`-driven start cannot be unit
tested (this module's own HARD RULE forbids unit-testing live SCM execution),
so the pure command construction, the exit-code classifier, and the wiring
into the D4 CLI are what get pinned here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_TAURI = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src"
SERVICE_REGISTRATION_RS = SRC_TAURI / "native_service_registration.rs"
MAIN_RS = SRC_TAURI / "main.rs"


def _registration_source() -> str:
    return SERVICE_REGISTRATION_RS.read_text(encoding="utf-8")


def test_a_start_command_is_constructed_for_the_supervisor_service() -> None:
    source = _registration_source()

    assert "pub fn service_start_command()" in source, (
        "native_service_registration.rs constructs no sc.exe start command; "
        "--startup auto only decides what the SCM does at the NEXT boot"
    )
    assert "pub fn start_native_service()" in source


def test_the_start_is_awaited_to_a_real_running_state_with_a_bounded_timeout() -> None:
    source = _registration_source()

    assert "fn wait_for_service_running()" in source, (
        "nothing polls the service to a real RUNNING state; sc.exe start returning 0 "
        "only means the start request was accepted"
    )
    assert "SERVICE_START_POLL_TIMEOUT_SECS" in source, "the RUNNING wait is unbounded"
    assert "fn service_query_reports_running(" in source


def test_an_already_running_service_is_an_idempotent_success() -> None:
    source = _registration_source()

    assert "ERROR_SERVICE_ALREADY_RUNNING" in source, (
        "re-running D4 over an already-started station must be success, not a failure; "
        "sc.exe start returns 1056 for it"
    )
    assert "fn classify_service_start_exit_code(" in source


def test_the_d4_registration_cli_issues_the_start_and_fails_loud_on_it() -> None:
    source = MAIN_RS.read_text(encoding="utf-8")
    marker = "fn run_native_service_registration_cli"
    start = source.find(marker)
    assert start != -1, f"{marker} not found in {MAIN_RS}"
    # The next `\nfn ` / `\n/// ` at column 0 ends this function's body.
    end = source.find("\n/// ", start)
    body = source[start : end if end != -1 else len(source)]

    assert "start_native_service()" in body, (
        "the D4 registration CLI registers the service and never starts it, so a fresh "
        "install leaves the station's control plane down until a reboot"
    )
    assert "SERVICE_START_FAILED_EXIT_CODE" in body, (
        "a service that registers but cannot start must fail the install with its own "
        "exit code, not collapse into the registration failure code"
    )
