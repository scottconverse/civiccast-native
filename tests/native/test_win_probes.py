# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-probe tests for civiccast.native.win_probes.

``win`` appears in this module's own filename (per the D3/CI naming
convention the brief requires) so `-k "not win"` deselects it honestly.
Skipped entirely on non-Windows (``pytest.mark.skipif``); runs for real on
windows-latest CI and this dev box -- SDR-001's point that fixture-only
proof is insufficient applies here: these hit the real registry, the real
process table, and the real ``wsl.exe``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import cast

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real probes"),
]

if os.name == "nt":
    import winreg

    from civiccast.native.models import A3Result
    from civiccast.native.runtime_guard import (
        RUN_KEY_PATH,
        RUN_VALUE_NAME,
        RUNTIME_HOST_FLAG,
        WSL_DISTRO_NAME,
    )
    from civiccast.native.win_probes import (
        WSL_EXE,
        WSL_LXSS_KEY_PATH,
        RuntimeOwnerMutex,
        detect_wsl_install,
        probe_indistro_services,
        probe_keeper,
        read_interlock,
        read_selector,
        scan_registered_distros,
        scan_run_entries,
        write_selector,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]


def _unique_test_key_path() -> str:
    return rf"Software\CivicCastWS4Test\{uuid.uuid4().hex}"


@pytest.fixture
def hkcu_test_key():
    key_path = _unique_test_key_path()
    yield key_path
    with subprocess_suppress():
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)


class subprocess_suppress:
    """Tiny local suppress-OSError context manager (avoids importing
    contextlib.suppress just for teardown cleanup noise)."""

    def __enter__(self) -> subprocess_suppress:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _default_distro_scan_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    """CC-WS4-002: pins the new registry-backed distro scan
    (``scan_registered_distros``) to an ambiguous default (``None``) for
    every test in this module, unless a test explicitly overrides it.

    Without this, any test that exercises ``_confirm_absence_via_service``'s
    SCM discriminator (by pinning ``wsl_service_present``) but says nothing
    about the distro scan would otherwise fall through to the REAL
    module-level default and hit THIS machine's actual Windows registry --
    making the test's outcome depend on whatever WSL distros happen to be
    registered on the box running the suite, rather than the scenario it is
    deliberately pinning. Tests that specifically exercise CC-WS4-002's new
    discriminator (or ``scan_registered_distros`` itself) override this
    default with their own later ``monkeypatch.setattr(win_probes,
    "scan_registered_distros", ...)`` call, which simply wins.
    """

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: None)


# --------------------------------------------------------------------------
# Selector round-trip (HKCU test key, root injected)
# --------------------------------------------------------------------------


def test_selector_absent_when_key_missing(hkcu_test_key: str) -> None:
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "absent"


def test_selector_absent_when_key_exists_but_value_missing(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE):
        pass
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "absent"


def test_selector_round_trips_native_and_wsl(hkcu_test_key: str) -> None:
    write_selector("native", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "native"

    write_selector("wsl", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "wsl"


def test_selector_garbage_value_is_unreadable(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "ActiveRuntime", 0, winreg.REG_SZ, "bogus-value")
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is False
    assert result.value is None


def test_selector_wrong_registry_type_is_unreadable(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "ActiveRuntime", 0, winreg.REG_DWORD, 1)
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is False


def test_selector_permission_error_opening_key_is_unreadable_not_absent(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6 FALSIFICATION: a PermissionError (or any other non-FileNotFoundError
    OSError) opening the selector key must classify as UNREADABLE (fail-closed,
    ok=False) -- it must NEVER be conflated with the readable-absent case
    (which is FileNotFoundError only, per D1)."""

    def raising_open_key(root: object, path: str, *args: object, **kwargs: object) -> object:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "OpenKey", raising_open_key)
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is False
    assert result.value is None
    assert "5" in result.detail or "denied" in result.detail.lower()


def test_selector_permission_error_reading_value_is_unreadable(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: same fail-closed classification when OpenKey succeeds but
    QueryValueEx itself raises a non-FileNotFoundError OSError."""

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE):
        pass

    def raising_query_value_ex(key: object, name: str) -> object:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "QueryValueEx", raising_query_value_ex)
    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is False
    assert result.value is None


def test_selector_still_absent_on_filenotfounderror_not_broken_by_f6(hkcu_test_key: str) -> None:
    """F6 must not change the D1 semantic: a genuinely missing key/value is
    still readable-absence (ok=True, value="absent"), not unreadable."""

    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "absent"


# --------------------------------------------------------------------------
# F5: every SOFTWARE\CivicCast registry access (selector + interlock) must
# force the 64-bit view (KEY_WOW64_64KEY) so a 32-bit process cannot split
# ActiveRuntime/Maintenance into the WOW6432Node shadow. Run-entry scan
# (HKEY_USERS) is exempt per the brief.
# --------------------------------------------------------------------------


def test_civiccast_key_access_helper_ors_in_wow64_64key() -> None:
    from civiccast.native.win_probes import _civiccast_key_access

    result = _civiccast_key_access(winreg.KEY_READ)
    assert result & winreg.KEY_WOW64_64KEY
    assert result & winreg.KEY_READ


def test_selector_and_interlock_registry_calls_pass_wow64_64key_access(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5 FALSIFICATION: spy on the real winreg.OpenKey/CreateKeyEx boundary
    -- every SOFTWARE\\CivicCast (selector + interlock) call must pass an
    explicit access mask with KEY_WOW64_64KEY set. Before the fix, these
    calls pass no explicit access argument at all (OpenKey) or an access
    mask without the WOW64 bit (CreateKeyEx), so `captured_accesses` stays
    empty / missing the bit."""

    from civiccast.native.win_probes import read_interlock, release_interlock, take_interlock

    real_open_key = winreg.OpenKey
    real_create_key_ex = winreg.CreateKeyEx
    captured_accesses: list[int] = []

    def spy_open_key(key: object, sub_key: str, *rest: object) -> object:
        if len(rest) >= 2:
            captured_accesses.append(cast(int, rest[-1]))
        return real_open_key(key, sub_key, *rest)  # type: ignore[arg-type]

    def spy_create_key_ex(key: object, sub_key: str, *rest: object) -> object:
        if len(rest) >= 2:
            captured_accesses.append(cast(int, rest[-1]))
        return real_create_key_ex(key, sub_key, *rest)  # type: ignore[arg-type]

    monkeypatch.setattr(winreg, "OpenKey", spy_open_key)
    monkeypatch.setattr(winreg, "CreateKeyEx", spy_create_key_ex)

    write_selector("native", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    take_interlock("run-1", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    release_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)

    assert len(captured_accesses) >= 5, captured_accesses
    for access in captured_accesses:
        assert access & winreg.KEY_WOW64_64KEY, (
            f"access mask {access:#x} is missing KEY_WOW64_64KEY"
        )


# --------------------------------------------------------------------------
# Interlock (Maintenance record) round-trip
# --------------------------------------------------------------------------


def test_interlock_free_when_key_missing(hkcu_test_key: str) -> None:
    result = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.status == "free"
    assert result.record is None


def test_interlock_permission_error_opening_key_is_unreadable_not_free(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6 FALSIFICATION: a PermissionError opening the Maintenance key must
    classify as UNREADABLE, never silently treated as the readable-free
    case (D4 fail-closed: a transmitter that can't check permission doesn't
    transmit)."""

    def raising_open_key(root: object, path: str, *args: object, **kwargs: object) -> object:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "OpenKey", raising_open_key)
    result = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.status == "unreadable"
    assert result.record is None


def test_interlock_round_trips_held_and_released(hkcu_test_key: str) -> None:
    from civiccast.native.win_probes import release_interlock, take_interlock

    record = take_interlock("run-abc", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert record.state == "held"
    assert record.generation == 1

    read_back = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert read_back.status == "held"
    assert read_back.record is not None
    assert read_back.record.generation == 1

    released = release_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert released.state == "released"
    assert released.generation == 1  # generation unchanged on release

    read_back2 = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert read_back2.status == "free"


def test_interlock_generation_increments_across_successive_takes(hkcu_test_key: str) -> None:
    from civiccast.native.win_probes import release_interlock, take_interlock

    first = take_interlock("run-1", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    release_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    second = take_interlock("run-2", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert second.generation == first.generation + 1


def test_interlock_double_take_raises(hkcu_test_key: str) -> None:
    from civiccast.native.win_probes import take_interlock

    take_interlock("run-1", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    with pytest.raises(RuntimeError):
        take_interlock("run-2", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)


def test_interlock_malformed_json_is_unreadable(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "Maintenance", 0, winreg.REG_SZ, "{not valid json")
    result = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.status == "unreadable"
    assert result.record is None


def test_interlock_schema_drift_extra_field_is_unreadable(hkcu_test_key: str) -> None:
    """FALSIFICATION: an otherwise well-formed Maintenance JSON blob with an
    extra unknown field must be rejected (extra="forbid"), not silently
    accepted as a valid record -- schema drift fails closed."""

    payload = (
        '{"v":1,"state":"held","generation":1,"owner_run_id":"run-x",'
        '"taken_utc":"2026-07-17T12:00:00Z","released_utc":null,"sneaky":"field"}'
    )
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "Maintenance", 0, winreg.REG_SZ, payload)
    result = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.status == "unreadable"


def test_interlock_wrong_registry_type_is_unreadable(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "Maintenance", 0, winreg.REG_DWORD, 1)
    result = read_interlock(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.status == "unreadable"


# --------------------------------------------------------------------------
# Run-entry scan (HKCU test path standing in for one loaded hive)
# --------------------------------------------------------------------------


def test_scan_run_entries_positive_when_marker_present(hkcu_test_key: str) -> None:
    # Scan the real default root first -- sanity that it's callable and
    # returns a legitimate status on THIS machine's actual loaded hives.
    default_status, _default_detail = scan_run_entries()
    assert default_status in ("positive", "negative", "error")

    fake_hive = f"{hkcu_test_key}\\FakeHive"
    run_path = f"{fake_hive}\\{RUN_KEY_PATH}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(
            key,
            RUN_VALUE_NAME,
            0,
            winreg.REG_SZ,
            f'"C:\\CivicCast\\civiccast.exe" {RUNTIME_HOST_FLAG}',
        )
    # winreg.OpenKey returns a PyHKEY that is itself usable as a root for
    # further OpenKey/EnumKey calls -- its direct children ("FakeHive" here)
    # stand in for loaded per-user hives under a real HKEY_USERS.
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        status, detail = scan_run_entries(users_root=fake_users_root_handle)
    assert status == "positive"
    assert RUNTIME_HOST_FLAG in detail


def test_scan_run_entries_negative_when_no_marker(hkcu_test_key: str) -> None:
    fake_hive = f"{hkcu_test_key}\\FakeHive"
    run_path = f"{fake_hive}\\{RUN_KEY_PATH}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(
            key, RUN_VALUE_NAME, 0, winreg.REG_SZ, '"C:\\SomethingElse\\other.exe" --unrelated'
        )
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        status, _detail = scan_run_entries(users_root=fake_users_root_handle)
    assert status == "negative"


def test_scan_run_entries_skips_classes_suffixed_hives(hkcu_test_key: str) -> None:
    """FALSIFICATION: a marker planted under a "<hive>_Classes" subkey must
    NEVER be found -- those are skipped per the brief's scan rule."""

    fake_hive_classes = f"{hkcu_test_key}\\FakeHive_Classes"
    run_path = f"{fake_hive_classes}\\{RUN_KEY_PATH}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(
            key,
            RUN_VALUE_NAME,
            0,
            winreg.REG_SZ,
            f'"C:\\CivicCast\\civiccast.exe" {RUNTIME_HOST_FLAG}',
        )
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        status, _detail = scan_run_entries(users_root=fake_users_root_handle)
    assert status == "negative"


def test_scan_run_entries_mid_scan_oserror_is_error_not_negative(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3 FALSIFICATION: a non-259 OSError raised by EnumKey mid-scan (e.g.
    winerror=1018, ERROR_KEY_DELETED) must classify as scan-level "error",
    never be conflated with the real end-of-enumeration sentinel
    (winerror=259, ERROR_NO_MORE_ITEMS)."""

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{hkcu_test_key}\\SomeHive", 0, winreg.KEY_SET_VALUE
    ):
        pass

    real_enum_key = winreg.EnumKey
    calls = {"n": 0}

    def flaky_enum_key(key: object, index: int) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(22, "key deleted mid-scan", None, 1018)
        return real_enum_key(key, index)  # type: ignore[arg-type]

    monkeypatch.setattr(winreg, "EnumKey", flaky_enum_key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        status, detail = scan_run_entries(users_root=fake_users_root_handle)
    assert status == "error"
    assert "1018" in detail


def test_scan_run_entries_real_end_of_list_winerror_259_is_clean_negative(
    hkcu_test_key: str,
) -> None:
    """F3: the REAL end-of-enumeration sentinel (winerror=259) must still be
    treated as a clean, ordinary end of scan -- "negative", not "error"."""

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{hkcu_test_key}\\SomeHive", 0, winreg.KEY_SET_VALUE
    ):
        pass
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        status, _detail = scan_run_entries(users_root=fake_users_root_handle)
    assert status == "negative"


# --------------------------------------------------------------------------
# A1: real process scan
# --------------------------------------------------------------------------


def test_probe_keeper_positive_for_real_spawned_flag_process_then_negative_after_kill() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", RUNTIME_HOST_FLAG],
    )
    try:
        deadline = time.monotonic() + 10
        result = None
        while time.monotonic() < deadline:
            result = probe_keeper()
            if result.live_process == "positive":
                break
            time.sleep(0.2)
        assert result is not None
        assert result.live_process == "positive"
        assert RUNTIME_HOST_FLAG in result.detail
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    deadline = time.monotonic() + 10
    result2 = None
    while time.monotonic() < deadline:
        result2 = probe_keeper()
        if result2.live_process == "negative":
            break
        time.sleep(0.2)
    assert result2 is not None
    assert result2.live_process == "negative"


# --------------------------------------------------------------------------
# A2: real-fire on this distro-less dev box + a FALSIFICATION with a stub
# runner simulating a REGISTERED distro that times out.
# --------------------------------------------------------------------------


def test_detect_wsl_install_false_on_this_distro_less_box() -> None:
    assert detect_wsl_install() is False


# --------------------------------------------------------------------------
# F4: wsl.exe is pinned to the absolute System32 path (CWD attack surface) --
# both real call sites must pass the pinned path to the injected runner, not
# a bare "wsl.exe" resolved via CreateProcess search order.
# --------------------------------------------------------------------------


def test_detect_wsl_install_invokes_pinned_system32_wsl_exe() -> None:
    seen_argv: list[list[str]] = []

    def spy_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen_argv.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    detect_wsl_install(runner=spy_runner)
    assert len(seen_argv) == 1
    assert seen_argv[0][0] == str(WSL_EXE)
    assert seen_argv[0][0].lower().endswith(r"\system32\wsl.exe")


def test_probe_indistro_services_invokes_pinned_system32_wsl_exe() -> None:
    seen_argv: list[list[str]] = []

    def spy_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen_argv.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"active\n", stderr=b"")

    probe_indistro_services(runner=spy_runner)
    assert len(seen_argv) == 1
    assert seen_argv[0][0] == str(WSL_EXE)
    assert seen_argv[0][0].lower().endswith(r"\system32\wsl.exe")


def test_probe_indistro_services_real_fire_negative_no_distro_registered() -> None:
    result = probe_indistro_services()
    assert result.status == "negative"
    assert "no CivicCast distro registered" in result.detail


# --------------------------------------------------------------------------
# CC-CLEANROOM-001 (found by the Windows-Sandbox clean-machine run
# 2026-07-22): on a PRISTINE box (no WSL feature at all) wsl.exe is the
# App-Execution-Alias stub -- EVERY invocation, including A2's systemctl
# probe call, exits nonzero with "The Windows Subsystem for Linux is not
# installed...". That output matched none of A2's recognized shapes and fell
# through to a BARE `unreadable`, which the guard fails closed on
# (blocked_probe_unavailable): the native product would not boot on its own
# target machine. Same AC1 class the WS4 wsl-detect fix closed for
# detect_wsl_install -- one probe over. Fix: the unrecognized-output
# fallthrough routes through _classify_absence_via_detect (locale-proof: it
# keys on the confirmatory SCM-backed tri-state, never on message text), so
# a DEFINITE no-WSL machine reads negative and every ambiguous state stays
# fail-closed unreadable.
# --------------------------------------------------------------------------

_WSL_NOT_INSTALLED_STUB = (
    "The Windows Subsystem for Linux is not installed. "
    "You can install by running 'wsl.exe --install'."
)


def _pristine_stub_runner(stderr_text: str) -> object:
    """Runner mimicking the pristine-box wsl.exe alias stub: every call
    (systemctl probe AND detect's `-l -q` inventory) exits 1 with the given
    diagnostic on stderr, UTF-16LE like the real wsl.exe."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 1, stdout=b"", stderr=stderr_text.encode("utf-16-le")
        )

    return stub_runner


def test_probe_indistro_services_not_installed_stub_with_no_wsl_services_is_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanroom failure, reproduced: stub output + SCM DEFINITIVELY
    showing no WSL services must be a readable negative, not unreadable."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: False)
    result = probe_indistro_services(runner=_pristine_stub_runner(_WSL_NOT_INSTALLED_STUB))
    assert result.status == "negative"
    assert "no CivicCast distro registered" in result.detail


def test_probe_indistro_services_localized_stub_with_no_wsl_services_is_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FALSIFICATION (locale): a non-English stub diagnostic must reach the
    same negative -- the fix may not key on the English message text."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: False)
    localized = "Das Windows-Subsystem für Linux ist nicht installiert."
    result = probe_indistro_services(runner=_pristine_stub_runner(localized))
    assert result.status == "negative"


def test_probe_indistro_services_unrecognized_output_with_wsl_present_stays_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FALSIFICATION (fail-closed): the same unrecognized output on a box
    where the SCM says WSL IS installed must stay unreadable -- the
    route-through may only flip to negative on a DEFINITE no-WSL read."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: True)
    result = probe_indistro_services(runner=_pristine_stub_runner(_WSL_NOT_INSTALLED_STUB))
    assert result.status == "unreadable"


def test_probe_indistro_services_unrecognized_output_with_unknown_scm_stays_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FALSIFICATION (fail-closed): SCM ambiguous (None) + unrecognized
    output must also stay unreadable."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: None)
    result = probe_indistro_services(runner=_pristine_stub_runner(_WSL_NOT_INSTALLED_STUB))
    assert result.status == "unreadable"


# --------------------------------------------------------------------------
# F1: detect_wsl_install tri-state (bool | None) -- a fail-open bug where
# TimeoutExpired/OSError silently became a definite False (an "unknown"
# state that authorized treating the machine as having no WSL install at
# all) is fixed here: those become None (UNKNOWN), distinct from a
# CONFIRMED False.
# --------------------------------------------------------------------------


def test_detect_wsl_install_returns_none_on_timeout_not_false() -> None:
    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    # Pin WSL-service PRESENT so this stays a deterministic "timeout with WSL
    # installed --> None" unit (CC-WS4-001 round-3): without pinning, the
    # timeout path now consults the real SCM and the outcome would depend on
    # the host having WSL installed.
    assert detect_wsl_install(runner=stub_runner, wsl_service_present=lambda: True) is None


def test_detect_wsl_install_returns_none_on_oserror_not_false() -> None:
    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("wsl.exe not found")

    # WSL-service present pinned: OSError with WSL installed --> None (ambiguous).
    assert detect_wsl_install(runner=stub_runner, wsl_service_present=lambda: True) is None


def test_detect_wsl_install_returns_definite_false_when_list_succeeds_without_distro() -> None:
    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    assert detect_wsl_install(runner=stub_runner) is False


# --------------------------------------------------------------------------
# CC-WS4-001 (round-2 panel, Critical): the round-1 F1 fix only caught the
# *exception* path (TimeoutExpired/OSError). It still ignored
# CompletedProcess.returncode entirely -- a `wsl.exe -l -q` invocation that
# RAN but exited nonzero (e.g. "Access is denied") returned an empty/garbage
# stdout, and `WSL_DISTRO_NAME in output` on that empty string is trivially
# False -- silently promoted to a CONFIRMED "no install" instead of the
# UNKNOWN it actually is. Fixed: `False` is returned ONLY after
# returncode==0 AND a decode that produced no U+FFFD replacement character
# (the positive "this was a clean, trustworthy decode" signal) -- every
# nonzero exit, undecodable/garbled output, exception, or timeout is None.
# --------------------------------------------------------------------------


def test_detect_wsl_install_returns_none_on_nonzero_exit_with_empty_stdout() -> None:
    """CC-WS4-001 FALSIFICATION: the auditor's literal repro -- `wsl.exe -l
    -q` runs (no exception) but exits nonzero with empty stdout (e.g.
    "Access is denied" on stderr). The round-1 code ignored returncode
    entirely and returned a confirmed False here; must be None (unknown)."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Access is denied")

    # WSL-service present pinned: a nonzero "Access is denied" WITH WSL
    # installed is an ambiguous failure --> None (CC-WS4-001 preserved).
    assert detect_wsl_install(runner=stub_runner, wsl_service_present=lambda: True) is None


def test_detect_wsl_install_returns_none_on_nonzero_exit_even_with_distro_name_in_stdout() -> None:
    """CC-WS4-001: a nonzero exit is untrustworthy regardless of what its
    stdout happens to contain -- even if the distro name literally appears
    in a failed invocation's stdout (e.g. an error echoing back part of the
    command line), the exit status alone means the answer is unknown, never
    a positive detection either way. This test specifically pins the "False"
    direction stays impossible; detect_wsl_install must not return True here
    either -- it returns None."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"CivicCast-Ubuntu-24.04\r\n", stderr=b"")

    # WSL-service present pinned: even a nonzero exit whose stdout echoes the
    # distro name is untrusted --> None, never True and never False.
    assert detect_wsl_install(runner=stub_runner, wsl_service_present=lambda: True) is None


def test_detect_wsl_install_returns_none_on_undecodable_garbage_bytes() -> None:
    """CC-WS4-001: a returncode==0 response whose bytes do not decode
    cleanly under either UTF-16LE or UTF-8 (garbled/binary noise) is not a
    trustworthy inventory -- it must not be silently treated as "positively
    lists zero or more distros, none matching." A clean decode under
    errors="replace" that still contains U+FFFD is the positive signal that
    the bytes were untrustworthy garbage."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 0, stdout=b"\xff\xfe\x00\x01\x02garbage\xfe", stderr=b""
        )

    # WSL-service present pinned: undecodable bytes are an untrustworthy
    # inventory --> None with WSL installed (never a spurious False).
    assert detect_wsl_install(runner=stub_runner, wsl_service_present=lambda: True) is None


def test_ws4_001_nonzero_wsl_inventory_with_timed_out_service_query_blocks_never_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS4-001 end-to-end FALSIFICATION -- the auditor's literal executed
    repro: the A2 in-distro service query times out AND the confirmatory
    `wsl.exe -l -q` returns exit 1 with "Access is denied". Before this fix,
    detect_wsl_install silently became a confirmed False, A2's
    _classify_absence_via_detect promoted that into a readable "negative",
    and decide() authorized a native start for selector-absent + otherwise
    clear probes. After the fix: detect_wsl_install is None, A2 stays
    unreadable, and decide() must return blocked_probe_unavailable -- never
    start."""

    from civiccast.native import win_probes
    from civiccast.native.models import A1Result, A3Result, GuardInputs, InterlockRead, SelectorRead
    from civiccast.native.runtime_guard import decide

    # The scenario is "wsl.exe -l -q DENIED while WSL IS installed": pin the
    # SCM signal to PRESENT so both the direct detect_wsl_install call and the
    # transitive one inside probe_indistro_services stay CC-WS4-001 None
    # (blocked), deterministically on any box (not host-WSL-dependent).
    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: True)

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "-l" in cmd and "-q" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Access is denied")
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    wsl_install_detected = detect_wsl_install(runner=stub_runner)
    assert wsl_install_detected is None

    a2 = probe_indistro_services(runner=stub_runner)
    assert a2.status == "unreadable"

    inputs = GuardInputs(
        selector=SelectorRead(ok=True, value="absent", detail="HKLM ActiveRuntime value missing"),
        wsl_install_detected=wsl_install_detected,
        a1=A1Result(live_process="negative", run_entry="negative", detail="clear"),
        a2=a2,
        a3=A3Result(status="acquired", detail="owned"),
        interlock=InterlockRead(status="free", record=None, detail="absent"),
    )
    decision = decide(inputs)
    assert decision.action != "start"
    assert decision.action == "blocked_probe_unavailable"


def test_probe_indistro_services_outer_timeout_with_confirmed_absent_distro_is_negative() -> None:
    """F1: the systemctl call itself times out/errors, but a confirmatory
    `wsl.exe -l -q` DEFINITIVELY shows no CivicCast distro registered --
    that combination is a readable negative ("no CivicCast distro
    registered"), not an unreadable probe."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "-l" in cmd and "-q" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    result = probe_indistro_services(runner=stub_runner)
    assert result.status == "negative"
    assert "no CivicCast distro registered" in result.detail


def test_probe_indistro_services_outer_timeout_with_unknown_install_state_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: the systemctl call times out AND the confirmatory detect ALSO
    cannot determine install state (None) -- must be unreadable, never
    negative (the fail-open bug this finding closes)."""

    from civiccast.native import win_probes

    # The confirmatory install state is genuinely UNKNOWN here: pin the SCM
    # signal to ambiguous (None) so detect_wsl_install stays None regardless
    # of whether the host actually has WSL (CC-WS4-001 round-3).
    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: None)

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    result = probe_indistro_services(runner=stub_runner)
    assert result.status == "unreadable"


def test_probe_indistro_services_outer_oserror_with_confirmed_registered_distro_is_unreadable() -> (
    None
):
    """F1: systemctl invocation itself fails (e.g. wsl.exe missing) but the
    distro IS confirmed registered -- ambiguous (can't tell if the service
    is actually inactive), so unreadable, never a readable negative."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "-l" in cmd and "-q" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"{WSL_DISTRO_NAME}\r\n".encode("utf-16-le"), stderr=b""
            )
        raise FileNotFoundError("wsl.exe not found")

    result = probe_indistro_services(runner=stub_runner)
    assert result.status == "unreadable"


def test_falsification_registered_distro_that_times_out_is_unreadable_fail_closed() -> None:
    """FALSIFICATION: a runner stub simulating a REGISTERED CivicCast distro
    (so detect_wsl_install must see it) whose systemctl call times out must
    classify as unreadable, not negative -- fail-closed proven in the
    "distro exists but is unresponsive" direction too."""

    def stub_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "-l" in cmd and "-q" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"{WSL_DISTRO_NAME}\r\n".encode("utf-16-le"), stderr=b""
            )
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    assert detect_wsl_install(runner=stub_runner) is True
    result = probe_indistro_services(runner=stub_runner)
    assert result.status == "unreadable"


# --------------------------------------------------------------------------
# CC-WS4-001 round-3 (clean-machine cleanroom, 2026-07-22): on a genuinely
# WSL-less Windows box, `wsl.exe` is an OS inbox stub that exits NONZERO
# ("The Windows Subsystem for Linux is not installed"). The CC-WS4-001
# round-2 fix correctly refuses to trust that nonzero exit as "no WSL" -->
# detect_wsl_install returned None --> A2 stayed "unreadable" --> the
# dual-runtime guard fail-closed and the NATIVE runtime (whose deployment
# target IS the clean box) never started. The fix adds a robust confirmatory
# signal on the nonzero/undecodable/exception paths: consult WSL-SERVICE
# presence via the Service Control Manager (`sc query WslService` /
# `LxssManager`; exit 0 = service exists, 1060 = does-not-exist). No WSL
# service registered => WSL genuinely absent => return False (native may
# start). A WSL service present, or the service check itself ambiguous =>
# stay None (CC-WS4-001 fail-closed preserved). The exit-0 clean-decode
# inventory path is authoritative and never consults the service seam.
#
# The two real-fire tests above each only exercise ONE environment-half
# (this dev box: wsl.exe exits 0). These inject BOTH seams (the wsl.exe
# `runner` and the `wsl_service_present` classifier) to pin every quadrant
# of the discriminator deterministically, on any box.
# --------------------------------------------------------------------------


def test_detect_wsl_install_nonzero_wsl_with_service_absent_is_definite_false() -> None:
    """CLEAN-MACHINE FIX: wsl.exe exits NONZERO (OS stub on a WSL-less box)
    AND the SCM reports NO WSL service registered --> WSL is genuinely not
    installed --> definite False, so the native runtime may start on its own
    target box. This is the exact clean-machine cleanroom failure being
    closed."""

    def nonzero_wsl(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout=b"",
            stderr="Windows Subsystem for Linux is not installed".encode("utf-16-le"),
        )

    assert detect_wsl_install(runner=nonzero_wsl, wsl_service_present=lambda: False) is False


def test_detect_wsl_install_nonzero_wsl_with_service_present_stays_none() -> None:
    """CC-WS4-001 PRESERVED: wsl.exe exits nonzero but a WSL service IS
    registered --> WSL is installed and the inventory query merely failed
    ambiguously (e.g. "Access is denied") --> must stay None, never a
    definite False (a failed wsl.exe invocation is never trusted as "no
    WSL")."""

    def nonzero_wsl(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Access is denied")

    assert detect_wsl_install(runner=nonzero_wsl, wsl_service_present=lambda: True) is None


def test_detect_wsl_install_nonzero_wsl_with_service_ambiguous_stays_none() -> None:
    """FAIL-CLOSED: wsl.exe exits nonzero and the SCM check itself is
    ambiguous (None -- e.g. sc.exe timed out or returned an unexpected exit)
    --> WSL absence cannot be PROVEN --> stays None, never False."""

    def nonzero_wsl(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"unexpected wsl failure")

    assert detect_wsl_install(runner=nonzero_wsl, wsl_service_present=lambda: None) is None


def test_detect_wsl_install_exit0_paths_never_consult_service_seam() -> None:
    """The clean exit-0 inventory path is authoritative and must NEVER
    consult the service seam: distro absent --> False, distro present -->
    True. A sentinel classifier that raises if called proves the seam is not
    touched on either exit-0 branch."""

    def _service_must_not_be_called() -> bool | None:
        raise AssertionError("wsl_service_present consulted on the authoritative exit-0 path")

    def exit0_no_distro(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    def exit0_with_distro(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"{WSL_DISTRO_NAME}\r\n".encode("utf-16-le"), stderr=b""
        )

    assert (
        detect_wsl_install(runner=exit0_no_distro, wsl_service_present=_service_must_not_be_called)
        is False
    )
    assert (
        detect_wsl_install(
            runner=exit0_with_distro, wsl_service_present=_service_must_not_be_called
        )
        is True
    )


def test_detect_wsl_install_exception_path_routes_through_service_discriminator() -> None:
    """The exception path (OSError/TimeoutExpired-raising runner) routes
    through the SAME SCM discriminator as the nonzero-exit path: service
    absent --> False; service present or ambiguous --> None."""

    def raising(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("wsl.exe not found")

    def timing_out(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    assert detect_wsl_install(runner=raising, wsl_service_present=lambda: False) is False
    assert detect_wsl_install(runner=raising, wsl_service_present=lambda: True) is None
    assert detect_wsl_install(runner=timing_out, wsl_service_present=lambda: None) is None
    assert detect_wsl_install(runner=timing_out, wsl_service_present=lambda: False) is False


def test_detect_wsl_install_undecodable_output_routes_through_service_discriminator() -> None:
    """The undecodable-output path (returncode 0 but garbled bytes producing
    U+FFFD) also routes through the SCM discriminator -- an untrustworthy
    inventory is not an authoritative exit-0 read: service absent --> False;
    service present --> None."""

    def garbled(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 0, stdout=b"\xff\xfe\x00\x01\x02garbage\xfe", stderr=b""
        )

    assert detect_wsl_install(runner=garbled, wsl_service_present=lambda: False) is False
    assert detect_wsl_install(runner=garbled, wsl_service_present=lambda: True) is None


# --------------------------------------------------------------------------
# The default SCM-backed classifier itself (`_default_wsl_service_present`):
# `sc query <name>` exit 0 for ANY WSL service name => True; exit 1060
# (ERROR_SERVICE_DOES_NOT_EXIST) for ALL candidate names => False; any other
# exit / timeout / OSError => None (ambiguous, fail-closed). Uses the SCM via
# sc.exe, NOT winreg (the raw Services registry path reads absent even when
# WslService is Running -- a Store-packaged service). The subprocess runner
# is injected so the classifier is exercised deterministically.
# --------------------------------------------------------------------------


def test_default_wsl_service_present_all_names_1060_is_false() -> None:
    from civiccast.native.win_probes import WSL_SERVICE_NAMES, _default_wsl_service_present

    seen: list[str] = []

    def sc_all_absent(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 1060, stdout=b"", stderr=b"does not exist")

    assert _default_wsl_service_present(runner=sc_all_absent) is False
    assert seen == list(WSL_SERVICE_NAMES)  # every candidate had to be a definite does-not-exist


def test_default_wsl_service_present_first_name_exit0_short_circuits_true() -> None:
    from civiccast.native.win_probes import WSL_SERVICE_NAMES, _default_wsl_service_present

    seen: list[str] = []

    def sc_first_present(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    assert _default_wsl_service_present(runner=sc_first_present) is True
    assert seen == [WSL_SERVICE_NAMES[0]]  # short-circuits on the first service that exists


def test_default_wsl_service_present_second_name_exit0_is_true() -> None:
    from civiccast.native.win_probes import WSL_SERVICE_NAMES, _default_wsl_service_present

    def sc_second_present(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        name = cmd[-1]
        rc = 0 if name == WSL_SERVICE_NAMES[1] else 1060
        return subprocess.CompletedProcess(cmd, rc, stdout=b"", stderr=b"")

    assert _default_wsl_service_present(runner=sc_second_present) is True


def test_default_wsl_service_present_other_exit_is_none() -> None:
    """A non-0, non-1060 exit (e.g. 5 Access Denied querying the SCM) is
    ambiguous -- we cannot conclude the service is absent -- so None."""

    from civiccast.native.win_probes import _default_wsl_service_present

    def sc_weird(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 5, stdout=b"", stderr=b"Access is denied")

    assert _default_wsl_service_present(runner=sc_weird) is None


def test_default_wsl_service_present_timeout_is_none() -> None:
    from civiccast.native.win_probes import _default_wsl_service_present

    def sc_timeout(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    assert _default_wsl_service_present(runner=sc_timeout) is None


def test_default_wsl_service_present_oserror_is_none() -> None:
    from civiccast.native.win_probes import _default_wsl_service_present

    def sc_oserror(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("sc.exe not found")

    assert _default_wsl_service_present(runner=sc_oserror) is None


def test_default_wsl_service_present_queries_pinned_system32_sc_exe() -> None:
    """F4-parallel: the SCM query must pin the absolute System32 sc.exe path,
    never a bare "sc" resolved via CreateProcess search order (the same CWD
    hijack surface F4 closed for wsl.exe)."""

    from civiccast.native.win_probes import SC_EXE, _default_wsl_service_present

    seen: list[list[str]] = []

    def spy(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1060, stdout=b"", stderr=b"")

    _default_wsl_service_present(runner=spy)
    assert seen
    for cmd in seen:
        assert cmd[0] == str(SC_EXE)
        assert cmd[0].lower().endswith(r"\system32\sc.exe")
        assert cmd[1] == "query"


# --------------------------------------------------------------------------
# A2 knock-on (the second failing real-fire test's intent, exercised
# hermetically): probe_indistro_services's in-distro systemctl call fails to
# run AND the confirmatory detect_wsl_install resolves to a definite False
# because the SCM reports no WSL service registered --> A2 status "negative"
# ("no CivicCast distro registered"), NOT "unreadable". The transitive
# detect_wsl_install call uses the module-default service seam, so the SCM
# classifier is monkeypatched to the clean-box "absent" signal (probe_
# indistro_services / _classify_absence_via_detect are unchanged -- the
# definite-False --> "negative" mapping already exists).
# --------------------------------------------------------------------------


def test_a2_knock_on_systemctl_fails_and_service_absent_is_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: False)

    def clean_box_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "-l" in cmd and "-q" in cmd:
            # clean-box `wsl.exe -l -q`: OS stub exits nonzero, "not installed"
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=b"",
                stderr="Windows Subsystem for Linux is not installed".encode("utf-16-le"),
            )
        # the in-distro systemctl call cannot even run
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    result = probe_indistro_services(runner=clean_box_runner)
    assert result.status == "negative"
    assert "no CivicCast distro registered" in result.detail


# --------------------------------------------------------------------------
# A3: RuntimeOwnerMutex -- real mutex, real SD, real cross-process behavior.
# --------------------------------------------------------------------------


def test_mutex_fresh_acquire_succeeds_and_dacl_has_no_everyone_ace() -> None:
    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)
    try:
        result = mutex.acquire()
        assert result.status == "acquired"
        sddl = mutex.read_dacl_sddl()
        assert ";;;SY)" in sddl
        assert ";;;BA)" in sddl
        assert ";;;WD)" not in sddl
    finally:
        mutex.release()


def test_mutex_second_process_is_denied_while_held() -> None:
    """Two-PROCESS test (not two threads): a second RuntimeOwnerMutex in a
    spawned subprocess is DENIED while the first holds it. On this
    unelevated dev box, the real Win32 mechanism is CreateMutex raising
    ERROR_ACCESS_DENIED on the second (any) open of an already-existing
    instance of this restrictive-SDDL mutex -- classified as "denied" here,
    which doubles as AC4's SD proof (an unprivileged token cannot acquire
    it either)."""

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)
    result = mutex.acquire()
    assert result.status == "acquired"
    try:
        script = (
            "from civiccast.native.win_probes import RuntimeOwnerMutex; "
            f"m = RuntimeOwnerMutex(name={name!r}); "
            "r = m.acquire(); "
            "print(r.status)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.stdout.strip() == "denied", (completed.stdout, completed.stderr)
    finally:
        mutex.release()


def test_mutex_abandoned_via_three_actor_witness_pattern() -> None:
    """Abandoned-mutex classification, proven for real: a witness process
    keeps the named kernel object alive (a mutex is destroyed the instant
    its last handle closes -- see module docstring), a holder acquires then
    dies (os._exit) without releasing, and this test process's reacquire
    observes WAIT_ABANDONED -> acquired_abandoned. A test-only PERMISSIVE
    SDDL is used (the production restrictive SDDL needs a privileged run to
    exercise this same code path against two equally-privileged holders --
    see evidence/PENDING.md)."""

    name = f"Global\\CivicCastWS4TestAbandon-{uuid.uuid4().hex}"
    permissive_sddl = "D:P(A;;GA;;;WD)"

    witness_script = (
        "import time, win32event, win32security\n"
        f"sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor({permissive_sddl!r}, win32security.SDDL_REVISION_1)\n"
        "sa = win32security.SECURITY_ATTRIBUTES()\n"
        "sa.SECURITY_DESCRIPTOR = sd\n"
        f"h = win32event.CreateMutex(sa, False, {name!r})\n"
        "time.sleep(8)\n"
    )
    holder_script = (
        "import os, time, win32event, win32security\n"
        f"sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor({permissive_sddl!r}, win32security.SDDL_REVISION_1)\n"
        "sa = win32security.SECURITY_ATTRIBUTES()\n"
        "sa.SECURITY_DESCRIPTOR = sd\n"
        "time.sleep(1)\n"
        f"h = win32event.CreateMutex(sa, False, {name!r})\n"
        "win32event.WaitForSingleObject(h, 0)\n"
        "os._exit(1)\n"
    )

    witness = subprocess.Popen([sys.executable, "-c", witness_script])
    holder = subprocess.Popen([sys.executable, "-c", holder_script])
    try:
        holder.wait(timeout=15)
        time.sleep(1.5)  # let the OS finalize abandonment bookkeeping

        mutex = RuntimeOwnerMutex(name=name, sddl=permissive_sddl)
        result = mutex.acquire()
        assert result.status == "acquired_abandoned"
        mutex.release()
    finally:
        witness.wait(timeout=15)


# --------------------------------------------------------------------------
# F7: RuntimeOwnerMutex.__enter__ context-manager honesty -- must not lie
# about ownership by silently returning a mutex object the caller does not
# actually own.
# --------------------------------------------------------------------------


def test_acquire_closes_handle_on_denied_via_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """FALSIFICATION (round-2 re-verify panel, Major): acquire() opens a real
    handle via CreateMutex before WaitForSingleObject classifies the outcome;
    on WAIT_TIMEOUT (denied) that handle must be closed inline, not parked on
    self._handle where a raising __enter__ (or a probe caller that never
    release()s) leaks one kernel handle per attempt."""

    import win32event

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    monkeypatch.setattr(
        win32event, "WaitForSingleObject", lambda handle, timeout: win32event.WAIT_TIMEOUT
    )
    mutex = RuntimeOwnerMutex(name=name)
    result = mutex.acquire()
    assert result.status == "denied"
    assert mutex._handle is None


def test_acquire_closes_handle_on_wait_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """FALSIFICATION: same leak, WaitForSingleObject raise path."""

    import pywintypes
    import win32event

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"

    def _boom(handle: object, timeout: object) -> int:
        raise pywintypes.error(6, "WaitForSingleObject", "The handle is invalid.")

    monkeypatch.setattr(win32event, "WaitForSingleObject", _boom)
    mutex = RuntimeOwnerMutex(name=name)
    result = mutex.acquire()
    assert result.status == "error"
    assert mutex._handle is None


def test_context_manager_raises_runtime_error_on_denied() -> None:
    """F7: __enter__ must not silently succeed when acquire() reports
    "denied" -- the caller would otherwise believe it owns the mutex."""

    mutex = RuntimeOwnerMutex(name=f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}")
    mutex.acquire = lambda timeout_ms=0: A3Result(  # type: ignore[method-assign]
        status="denied", detail="mutex held by pid 999"
    )
    with pytest.raises(RuntimeError, match="denied"), mutex:
        pass  # pragma: no cover - must not be reached


def test_context_manager_raises_runtime_error_on_error() -> None:
    """F7: __enter__ must not silently succeed when acquire() reports
    "error" -- an unarbitrated mutex is not a mutex the caller owns."""

    mutex = RuntimeOwnerMutex(name=f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}")
    mutex.acquire = lambda timeout_ms=0: A3Result(  # type: ignore[method-assign]
        status="error", detail="CreateMutex failed: boom"
    )
    with pytest.raises(RuntimeError, match="error"), mutex:
        pass  # pragma: no cover - must not be reached


def test_context_manager_passes_through_on_acquired() -> None:
    mutex = RuntimeOwnerMutex(name=f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}")
    try:
        with mutex as entered:
            assert entered is mutex
    finally:
        mutex.release()


def test_context_manager_passes_through_on_acquired_abandoned() -> None:
    """F7: acquired_abandoned passes __enter__ through (the caller still
    owes the A2 re-verify per D4 -- this context manager only guards against
    denied/error, it does not itself perform the mandatory re-verify)."""

    mutex = RuntimeOwnerMutex(name=f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}")
    mutex.acquire = lambda timeout_ms=0: A3Result(  # type: ignore[method-assign]
        status="acquired_abandoned", detail="prior owner crashed"
    )
    mutex.release = lambda: None  # type: ignore[method-assign] - no real handle to release
    with mutex as entered:
        assert entered is mutex


# --------------------------------------------------------------------------
# CC-WS4-004 (round 2, Major -- auditor panel): lifetime-safe ownership.
# GuardMonitor's real A3 callable must be `mutex.probe`, never `.acquire`
# directly -- every 30s re-evaluation calling `.acquire()` re-opens/re-waits
# the kernel object even when this process already owns it, and an
# unelevated holder cannot reopen the production-DACL object it already
# owns (CreateMutex's second-open DACL check -- see the module docstring's
# first empirical correction) -- the monitor controlled-stops itself within
# one interval of starting. `probe()` reports stable self-ownership WITHOUT
# reopening once owned; the exclusivity assertion against the other side
# still happens exactly once, on the first probe.
# --------------------------------------------------------------------------


def test_probe_first_call_attempts_one_real_acquire() -> None:
    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)
    try:
        result = mutex.probe()
        assert result.status == "acquired"
    finally:
        mutex.release()


def test_probe_does_not_reacquire_once_self_owned() -> None:
    """CC-WS4-004 FALSIFICATION: probe() must not call acquire() again once
    this instance already owns the mutex -- the round-1 bug (GuardMonitor
    wired directly with `.acquire`) re-acquired on every evaluation."""

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)
    acquire_calls = {"n": 0}
    real_acquire = mutex.acquire

    def counting_acquire(timeout_ms: int = 0) -> A3Result:
        acquire_calls["n"] += 1
        return real_acquire(timeout_ms)

    mutex.acquire = counting_acquire  # type: ignore[method-assign]
    try:
        first = mutex.probe()
        assert first.status == "acquired"
        assert acquire_calls["n"] == 1

        second = mutex.probe()
        assert second.status == "acquired"
        assert acquire_calls["n"] == 1  # NOT re-called -- the whole point.
        assert "self-owned" in second.detail

        third = mutex.probe()
        assert third.status == "acquired"
        assert acquire_calls["n"] == 1
    finally:
        mutex.release()


def test_probe_defensive_branch_calls_acquire_when_owns_true_but_handle_lost() -> None:
    """FALSIFICATION: the defensive branch (self._owns True but the handle
    was somehow lost -- should not happen; release() clears both together)
    must NOT silently report continued ownership by trusting `_owns` alone.
    It attempts a real re-acquire, and a real denial there is a real
    refusal, not papered over."""

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)
    mutex._owns = True
    mutex._handle = None
    acquire_calls = {"n": 0}

    def fake_acquire(timeout_ms: int = 0) -> A3Result:
        acquire_calls["n"] += 1
        return A3Result(status="denied", detail="real loss of ownership")

    mutex.acquire = fake_acquire  # type: ignore[method-assign]
    result = mutex.probe()
    assert acquire_calls["n"] == 1
    assert result.status == "denied"


def test_guard_monitor_wired_with_real_mutex_probe_survives_two_evaluations_and_pre_child_start() -> (
    None
):
    """CC-WS4-004 RED-FIRST control (real Windows, this box): wiring a real
    RuntimeOwnerMutex's `.probe` (NOT `.acquire`) into a GuardMonitor with
    otherwise-clear real-contract inputs must return `start` on EVERY
    evaluation -- the round-1 wiring (`.acquire` directly) denied itself on
    the second evaluation (this process cannot reopen the production-DACL
    object it already owns). A second process attempting real `.acquire()`
    on the SAME mutex must still be denied (exclusivity intact). One
    release frees the object with NO handle growth -- a fresh
    RuntimeOwnerMutex can then acquire it. The existing two-process denial
    (`test_mutex_second_process_is_denied_while_held`) and abandoned
    (`test_mutex_abandoned_via_three_actor_witness_pattern`) tests stay
    green, unmodified by this fix."""

    from datetime import UTC, datetime

    from civiccast.native.models import A1Result, A2Result, InterlockRead, SelectorRead
    from civiccast.native.runtime_guard import GuardMonitor

    name = f"Global\\CivicCastWS4Test-{uuid.uuid4().hex}"
    mutex = RuntimeOwnerMutex(name=name)

    monitor = GuardMonitor(
        selector_reader=lambda: SelectorRead(ok=True, value="native", detail="ok"),
        a1_probe=lambda: A1Result(live_process="negative", run_entry="negative", detail="clear"),
        a2_probe=lambda: A2Result(status="negative", detail="inactive"),
        mutex=mutex.probe,
        interlock_reader=lambda: InterlockRead(status="free", record=None, detail="absent"),
        wsl_install_detector=lambda: False,
        clock=lambda: datetime.now(UTC),
    )

    try:
        decision1 = monitor.evaluate_once()
        assert decision1.action == "start", decision1.message
        decision2 = monitor.evaluate_once()
        assert decision2.action == "start", decision2.message
        decision3 = monitor.pre_child_start()
        assert decision3.action == "start", decision3.message

        script = (
            "from civiccast.native.win_probes import RuntimeOwnerMutex; "
            f"m = RuntimeOwnerMutex(name={name!r}); "
            "r = m.acquire(); "
            "print(r.status)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.stdout.strip() == "denied", (completed.stdout, completed.stderr)
    finally:
        mutex.release()

    reacquire = RuntimeOwnerMutex(name=name)
    try:
        result = reacquire.acquire()
        assert result.status == "acquired"
    finally:
        reacquire.release()


# --------------------------------------------------------------------------
# CC-WS4-005 (round 2, Major -- auditor panel): runtime_cli.py's
# `_default_phase2_remove_run_entries` and `_enumerate_unloaded_profiles`
# had the SAME EnumKey/open/query/delete-OSError-as-end-of-list-or-continue
# conflation F3 already fixed in win_probes.scan_run_entries -- only
# winerror==259 (ERROR_NO_MORE_ITEMS) is the real end-of-enumeration
# sentinel; every other OSError must now FAIL the phase (raise) with
# hive/index context, never silently return a partial/empty result the
# journal or evidence would then trust as complete. These monkeypatch the
# real `winreg` module directly (mirroring
# `test_scan_run_entries_mid_scan_oserror_is_error_not_negative`'s
# pattern) since both functions use HKEY_USERS directly, not an injectable
# root.
# --------------------------------------------------------------------------


class _FakeRegKey:
    """No-op context manager standing in for a winreg key handle."""

    def __enter__(self) -> _FakeRegKey:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def test_default_phase2_remove_run_entries_enumkey_permission_error_fails_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS4-005 FALSIFICATION: a non-259 OSError from EnumKey while
    scanning HKEY_USERS for hives must FAIL the phase (raise) -- never be
    silently treated as end-of-list, and never let the phase record
    removed=[] as if that were a confirmed, trustworthy success."""

    from civiccast.native import runtime_cli

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        return _FakeRegKey()

    def fake_enum_key(key: object, index: int) -> str:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)

    with pytest.raises(RuntimeError, match="enumeration failed"):
        runtime_cli._default_phase2_remove_run_entries()


def test_default_phase2_remove_run_entries_per_hive_open_denied_fails_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS4-005 FALSIFICATION: per-hive open-denied variant -- EnumKey
    cleanly names one hive, but opening THAT hive's Run key raises a
    non-FileNotFoundError OSError (access denied). The round-1 code
    silently `continue`d past this; it must now fail the phase."""

    from civiccast.native import runtime_cli

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        if path == "":
            return _FakeRegKey()
        raise PermissionError(13, "Access is denied", None, 5)

    def fake_enum_key(key: object, index: int) -> str:
        if index == 0:
            return "S-1-5-21-fake-sid"
        raise OSError(0, "no more items", None, 259)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)

    with pytest.raises(RuntimeError, match="Run-entry access"):
        runtime_cli._default_phase2_remove_run_entries()


def test_default_phase2_remove_run_entries_delete_failed_fails_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS4-005 FALSIFICATION: delete-failed variant -- the marker is
    found (a real DeleteValue would remove it), but DeleteValue itself
    raises. The round-1 code had no failure path here at all (DeleteValue's
    own OSError would have propagated uncaught, but a wrapping fix must not
    accidentally swallow it into `continue` either); this pins that it
    surfaces as a phase failure."""

    from civiccast.native import runtime_cli
    from civiccast.native.runtime_guard import RUNTIME_HOST_FLAG

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        return _FakeRegKey()

    def fake_enum_key(key: object, index: int) -> str:
        if index == 0:
            return "S-1-5-21-fake-sid"
        raise OSError(0, "no more items", None, 259)

    def fake_query_value_ex(key: object, name: str) -> tuple[str, int]:
        return f'"C:\\CivicCast\\civiccast.exe" {RUNTIME_HOST_FLAG}', winreg.REG_SZ

    def fake_delete_value(key: object, name: str) -> None:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query_value_ex)
    monkeypatch.setattr(winreg, "DeleteValue", fake_delete_value)

    with pytest.raises(RuntimeError, match="Run-entry access"):
        runtime_cli._default_phase2_remove_run_entries()


def test_default_phase2_remove_run_entries_real_end_of_list_still_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The REAL end-of-enumeration sentinel (winerror=259) must still end
    the scan cleanly -- no false failures introduced by the fix. Every
    OpenKey (HKEY_USERS root, ProfileList, or a per-hive Run key) opens
    cleanly here; EnumKey immediately reports "no more items" everywhere,
    so both enumeration passes (this phase's hive scan and
    ``_enumerate_unloaded_profiles``'s two passes) are legitimately empty."""

    from civiccast.native import runtime_cli

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        return _FakeRegKey()

    def fake_enum_key(key: object, index: int) -> str:
        raise OSError(0, "no more items", None, 259)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)

    removed, unloaded, exe_path = runtime_cli._default_phase2_remove_run_entries()
    assert removed == []
    assert unloaded == []
    assert exe_path is None


def test_enumerate_unloaded_profiles_enumkey_failure_raises_not_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS4-005 FALSIFICATION: a ProfileList/HKEY_USERS enumeration
    failure must FAIL (raise) -- never silently return an empty/partial
    inventory that evidence would then falsely claim as a complete,
    trustworthy "no unloaded profiles" result."""

    from civiccast.native import runtime_cli

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        return _FakeRegKey()

    def fake_enum_key(key: object, index: int) -> str:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)

    with pytest.raises(RuntimeError, match="enumeration failed"):
        runtime_cli._enumerate_unloaded_profiles()


def test_enumerate_unloaded_profiles_real_end_of_list_still_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The REAL end-of-enumeration sentinel (winerror=259) must still end
    both enumeration passes cleanly."""

    from civiccast.native import runtime_cli

    def fake_open_key(root: object, path: str = "", *args: object, **kwargs: object) -> _FakeRegKey:
        return _FakeRegKey()

    def fake_enum_key(key: object, index: int) -> str:
        raise OSError(0, "no more items", None, 259)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)

    result = runtime_cli._enumerate_unloaded_profiles()
    assert result == []


# --------------------------------------------------------------------------
# CC-WS4-006 (round 2, Major -- auditor panel): rollback's Run-entry
# restoration must VERIFY the exact value data immediately (read it back)
# before the phase can be done. `_default_phase4_restore_run_entry` is now
# root/key_path-injectable (house pattern) specifically so this proof can
# target a scoped HKCU test subkey -- never the real production
# ``Software\Microsoft\Windows\CurrentVersion\Run`` key (this box has a
# REAL live CivicCast Autostart entry in the real key; a test must never
# touch it).
# --------------------------------------------------------------------------


def test_default_phase4_restore_run_entry_real_hkcu_round_trip_verifies_readback(
    hkcu_test_key: str,
) -> None:
    from civiccast.native import runtime_cli

    exe_path = r"C:\CivicCast\civiccast.exe"
    detail = runtime_cli._default_phase4_restore_run_entry(
        exe_path, root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key
    )
    assert "read-back verified" in detail

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as key:
        value, value_type = winreg.QueryValueEx(key, "CivicCast Autostart")
    assert value_type == winreg.REG_SZ
    assert value == f'"{exe_path}" {RUNTIME_HOST_FLAG}'


def test_default_phase4_restore_run_entry_none_exe_path_raises(hkcu_test_key: str) -> None:
    """CC-WS4-006 FALSIFICATION: a None exe path must RAISE (defensive
    backstop -- run_rollback's preflight is the real gate), never return
    the round-1 "Run entry NOT restored" normal-success detail."""

    from civiccast.native import runtime_cli

    with pytest.raises(RuntimeError, match="no exe path"):
        runtime_cli._default_phase4_restore_run_entry(
            None, root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key
        )


def test_default_phase4_restore_run_entry_readback_mismatch_raises(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-WS4-006 FALSIFICATION: if the read-back does not match what was
    written (simulated here -- a real Windows registry write would not
    normally do this, but the check must still bite if it ever does), the
    phase must FAIL, never be recorded done."""

    from civiccast.native import runtime_cli

    real_query_value_ex = winreg.QueryValueEx

    def mismatched_query_value_ex(key: object, name: str) -> tuple[str, int]:
        return "something-else-entirely", winreg.REG_SZ

    monkeypatch.setattr(winreg, "QueryValueEx", mismatched_query_value_ex)
    with pytest.raises(RuntimeError, match="did not read back correctly"):
        runtime_cli._default_phase4_restore_run_entry(
            r"C:\CivicCast\civiccast.exe", root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key
        )
    monkeypatch.setattr(winreg, "QueryValueEx", real_query_value_ex)


# --------------------------------------------------------------------------
# C3 (2026-07-31): probe children run file-backed with a hard deadline and a
# kill-tree on expiry -- the capture mechanism changed; every verdict above
# is asserted UNCHANGED by the existing tests in this file.
# --------------------------------------------------------------------------


def test_probe_children_receive_file_backed_capture_never_pipes() -> None:
    """All three probe execution sites (wsl -l -q, wsl -d ... systemctl,
    sc query) must hand the child real FILES for stdout/stderr with the
    5s hard deadline -- never capture_output pipes, which wslhost.exe-style
    helpers demonstrably hold open past any timeout."""

    from civiccast.native.runtime_guard import A2_TIMEOUT_SECONDS
    from civiccast.native.win_probes import _default_wsl_service_present

    seen_kwargs: list[dict[str, object]] = []

    def spy_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen_kwargs.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"active\n", stderr=b"")

    detect_wsl_install(runner=spy_runner)
    probe_indistro_services(runner=spy_runner)
    _default_wsl_service_present(runner=spy_runner)

    assert len(seen_kwargs) >= 3
    for kwargs in seen_kwargs:
        assert "capture_output" not in kwargs, "pipes are the proven hang -- files only"
        assert hasattr(kwargs["stdout"], "fileno"), "stdout must be a real file"
        assert hasattr(kwargs["stderr"], "fileno"), "stderr must be a real file"
        assert kwargs["timeout"] == A2_TIMEOUT_SECONDS


def test_default_runner_path_is_file_backed_and_feeds_the_same_verdict_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the DEFAULT (production) runner, execution routes through
    pg_ctl_exec's Popen + file-backed capture; the bytes written to the
    FILE (UTF-16LE, as real wsl.exe emits) must flow into the exact same
    decode/verdict logic."""

    import civiccast.native.pg_ctl_exec as pg_ctl_exec_module

    seen: dict[str, object] = {}

    class FakeProc:
        pid = 999_999_001

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProc:
        seen["argv"] = argv
        seen.update(kwargs)
        stdout_file = kwargs["stdout"]
        stdout_file.write(f"Some-Other-Distro\n{WSL_DISTRO_NAME}\n".encode("utf-16-le"))  # type: ignore[attr-defined]
        return FakeProc()

    monkeypatch.setattr(pg_ctl_exec_module.subprocess, "Popen", fake_popen)

    assert detect_wsl_install() is True

    assert seen["argv"] == [str(WSL_EXE), "-l", "-q"]
    assert "capture_output" not in seen
    assert hasattr(seen["stdout"], "fileno")
    assert hasattr(seen["stderr"], "fileno")
    assert seen["stdin"] is subprocess.DEVNULL


def test_default_runner_timeout_kills_the_probe_tree_and_keeps_the_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung wsl.exe on the production path: the deadline fires, the WHOLE
    process tree is force-killed (kill_process_tree), and the probe's
    existing timeout classification (route through the SCM discriminator;
    definite no-WSL -> False) is preserved exactly."""

    import civiccast.native.pg_ctl_exec as pg_ctl_exec_module

    killed: list[int] = []

    class HungProc:
        pid = 999_999_002

        def __init__(self) -> None:
            self.waits = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(cmd="wsl", timeout=timeout or 0.0)
            return -9

    monkeypatch.setattr(pg_ctl_exec_module.subprocess, "Popen", lambda argv, **kwargs: HungProc())
    monkeypatch.setattr(pg_ctl_exec_module, "kill_process_tree", killed.append)

    assert detect_wsl_install(wsl_service_present=lambda: False) is False
    assert detect_wsl_install(wsl_service_present=lambda: True) is None
    assert killed == [HungProc.pid, HungProc.pid]


# ---------------------------------------------------------------------------
# Chain G: the installer's selector claim, read back through the guard's own
# read path.
#
# `native_uninstall::write_selector_native` (Rust, elevated, install time)
# writes a REG_SZ named "ActiveRuntime" whose text is exactly "native" under
# SOFTWARE\CivicCast in the 64-bit view. These tests state the SAME write with
# raw winreg -- deliberately NOT through `write_selector`, so a change to the
# Python writer cannot make the contract look satisfied when the Rust writer
# is what actually runs on a station -- and prove the supervisor's guard
# accepts it.
# ---------------------------------------------------------------------------


def test_the_rust_installers_selector_write_is_read_back_as_native(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        # Byte-for-byte what native_uninstall.rs's `key.set_value(SELECTOR_VALUE, &"native")`
        # produces: value name "ActiveRuntime", type REG_SZ, text "native".
        winreg.SetValueEx(key, "ActiveRuntime", 0, winreg.REG_SZ, "native")

    result = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result.ok is True
    assert result.value == "native"


def test_a_claimed_native_selector_clears_the_r7_blocked_probe_unavailable_verdict(
    hkcu_test_key: str,
) -> None:
    """The R7 station halted at ``blocked_probe_unavailable`` with "selector
    absent and WSL install state is unknown". This proves the claim written by
    the installer removes THAT verdict: the same guard inputs, with the same
    unknown ``wsl_install_detected``, no longer reach ``decide``'s step-4
    selector-absent branch at all.

    It deliberately does NOT claim the station starts -- see
    ``test_a_claimed_native_selector_does_not_by_itself_survive_an_unreadable_a2``
    below for the gate that remains.
    """

    from civiccast.native.models import A1Result, A2Result, A3Result, GuardInputs, InterlockRead
    from civiccast.native.runtime_guard import decide

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "ActiveRuntime", 0, winreg.REG_SZ, "native")
    selector = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)

    inputs = GuardInputs(
        selector=selector,
        # The exact R7 value: the install-detection probe could not answer.
        wsl_install_detected=None,
        a1=A1Result(live_process="negative", run_entry="negative", detail="no keeper"),
        a2=A2Result(status="negative", detail="no CivicCast distro registered"),
        a3=A3Result(status="acquired", detail="mutex owned by this process"),
        interlock=InterlockRead(status="free", record=None, detail="Maintenance value not present"),
    )
    decision = decide(inputs)
    assert decision.action == "start", decision.message


def test_a_claimed_native_selector_starts_degraded_when_a2_is_unreadable(
    hkcu_test_key: str,
) -> None:
    """THE R7-shaped scenario, end to end -- and chain I's RED witness.

    Chain G disclosed this as a residual and pinned it ASSERTING THE BLOCK
    (``action == "blocked_probe_unavailable"``, ``named_probe == "A2"``),
    which passed against the pre-chain-I tree. Inverted here per the owner
    decision: an explicit, validly-written ``ActiveRuntime=native`` IS the
    authority basis for a native start, so an A2 the guard merely could not
    READ degrades the start and is logged, rather than withholding the
    station. Against the pre-chain-I tree this fails on the first assertion.

    On R7 this is exactly the state that will be reached: chain G's installer
    write lands the selector; ``probe_indistro_services`` routes its failure
    through ``_classify_absence_via_detect``, which calls the SAME
    ``detect_wsl_install`` that answered ``None`` there, producing the
    unreadable A2.
    """

    from civiccast.native.models import A1Result, A2Result, A3Result, GuardInputs, InterlockRead
    from civiccast.native.runtime_guard import decide

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "ActiveRuntime", 0, winreg.REG_SZ, "native")
    selector = read_selector(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)

    decision = decide(
        GuardInputs(
            selector=selector,
            wsl_install_detected=None,
            a1=A1Result(live_process="negative", run_entry="negative", detail="no keeper"),
            a2=A2Result(
                status="unreadable",
                detail="WSL install state unknown (confirmatory detect_wsl_install could not "
                "determine it) while wsl.exe reports distro not found",
            ),
            a3=A3Result(status="acquired", detail="mutex owned by this process"),
            interlock=InterlockRead(
                status="free", record=None, detail="Maintenance value not present"
            ),
        )
    )
    assert decision.action == "start_degraded"
    assert decision.named_probe == "A2"
    assert "probe-degraded" in decision.message
    assert "ActiveRuntime=native is the authority basis" in decision.message
    # Not a block: no bounded retry, no blocked state name.
    assert decision.retry_seconds is None
    assert decision.state_name is None


# ---------------------------------------------------------------------------
# CC-WS4-002: the supervisor runs as LocalSystem, and current WSL versions
# categorically refuse that identity (`wsl.exe -l -q` exits -1 with "Running
# WSL as local system is not supported."). detect_wsl_install then falls
# through to _confirm_absence_via_service, whose SCM signal could only prove
# WSL itself exists, never that the CivicCast distro specifically was
# absent -- on a machine with WSL installed but the CivicCast distro not
# registered, that stayed a fail-closed None forever and the control plane
# never started (confirmed live: the interactive user reads False, the
# LocalSystem service identity reads None for the exact same machine state).
# Fixed by consulting scan_registered_distros -- a registry-backed,
# LocalSystem-safe distro inventory -- as a further discriminator on every
# path that does not already resolve to a definite SCM-backed False.
# ---------------------------------------------------------------------------

_LOCAL_SYSTEM_WSL_STDOUT = (
    "Running WSL as local system is not supported.\r\n"
    "Error code: Wsl/WSL_E_LOCAL_SYSTEM_NOT_SUPPORTED\r\n"
)


def _local_system_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    """Reproduces the exact live-confirmed LocalSystem repro: wsl.exe exits
    -1 with the verbatim WSL_E_LOCAL_SYSTEM_NOT_SUPPORTED stdout."""

    return subprocess.CompletedProcess(
        cmd, -1, stdout=_LOCAL_SYSTEM_WSL_STDOUT.encode(), stderr=b""
    )


def test_ws4_002_local_system_repro_service_present_distro_scan_false_yields_definite_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug being fixed, reproduced end to end: wsl.exe refuses
    LocalSystem (verbatim stdout, exit -1), the SCM confirms WSL IS present
    (a WSL-installed-but-CivicCast-distro-missing machine), and the
    registry-backed distro scan proves the CivicCast distro is NOT
    registered. First pin down what the answer WAS before this fix -- with
    no distro-specific signal available, an SCM-present read alone could
    never resolve past None, regardless of what the (not-yet-existing)
    distro scan would have said. Then show the fix: a distro scan that
    definitely says False flips the same detect_wsl_install call to a
    genuine False."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: True)

    # Pre-fix behavior, pinned directly: before CC-WS4-002 there was no
    # distro-specific discriminator at all, so this path could only ever
    # produce None. A distro scan that itself cannot resolve (None) recreates
    # that exact pre-fix outcome.
    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: None)
    assert detect_wsl_install(runner=_local_system_runner) is None

    # Post-fix behavior: a distro scan that DEFINITELY proves the CivicCast
    # distro is absent now flips the same scenario to False.
    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: False)
    assert detect_wsl_install(runner=_local_system_runner) is False


def test_ws4_002_local_system_repro_distro_scan_true_preserves_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same LocalSystem repro, but the distro scan finds the CivicCast
    distro IS registered under some hive -- the failure is elsewhere (e.g. a
    genuinely broken WSL runtime), so the CC-WS4-001 fail-closed None must be
    preserved, never flipped to False or True."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: True)
    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: True)
    assert detect_wsl_install(runner=_local_system_runner) is None


def test_ws4_002_local_system_repro_distro_scan_none_preserves_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same LocalSystem repro, but the distro scan itself could not be
    trusted (e.g. HKEY_USERS enumeration failed under whatever identity ran
    it) -- an untrustworthy scan must not be promoted into a confident
    False; None is preserved."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: True)
    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: None)
    assert detect_wsl_install(runner=_local_system_runner) is None


def test_ws4_002_scm_definite_absence_short_circuits_before_distro_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the SCM signal ALONE already proves no WSL service is
    registered at all, that must return False exactly as it did before this
    change -- and the new distro scan must not even be consulted (there is
    no CivicCast distro question to ask on a machine with no WSL)."""

    from civiccast.native import win_probes

    def scanner_must_not_be_called(**kwargs: object) -> bool | None:
        raise AssertionError("distro scan consulted despite a definite SCM absence")

    monkeypatch.setattr(win_probes, "_default_wsl_service_present", lambda: False)
    monkeypatch.setattr(win_probes, "scan_registered_distros", scanner_must_not_be_called)

    assert detect_wsl_install(runner=_local_system_runner) is False


def test_ws4_002_exit0_paths_never_consult_distro_scanner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clean exit-0 authoritative path is unchanged by this fix and must
    never consult the new distro-scan fallback, exactly as it never consults
    the SCM fallback."""

    from civiccast.native import win_probes

    def scanner_must_not_be_called(**kwargs: object) -> bool | None:
        raise AssertionError("distro scan consulted on the authoritative exit-0 path")

    monkeypatch.setattr(win_probes, "scan_registered_distros", scanner_must_not_be_called)

    def exit0_no_distro(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    def exit0_with_distro(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"{WSL_DISTRO_NAME}\r\n".encode("utf-16-le"), stderr=b""
        )

    assert detect_wsl_install(runner=exit0_no_distro) is False
    assert detect_wsl_install(runner=exit0_with_distro) is True


# --------------------------------------------------------------------------
# _confirm_absence_via_service's new injectable `distro_scanner` keyword,
# exercised directly against injected callables (no module monkeypatching)
# to pin the discriminator's own truth table independent of detect_wsl_
# install's calling conventions.
# --------------------------------------------------------------------------


def test_confirm_absence_via_service_scm_false_short_circuits_distro_scanner_not_called() -> None:
    from civiccast.native.win_probes import _confirm_absence_via_service

    def scanner_must_not_be_called() -> bool | None:
        raise AssertionError("distro scanner consulted despite a definite SCM absence")

    assert (
        _confirm_absence_via_service(lambda: False, distro_scanner=scanner_must_not_be_called)
        is False
    )


def test_confirm_absence_via_service_scm_present_distro_scan_false_is_false() -> None:
    from civiccast.native.win_probes import _confirm_absence_via_service

    assert _confirm_absence_via_service(lambda: True, distro_scanner=lambda: False) is False


def test_confirm_absence_via_service_scm_present_distro_scan_true_stays_none() -> None:
    from civiccast.native.win_probes import _confirm_absence_via_service

    assert _confirm_absence_via_service(lambda: True, distro_scanner=lambda: True) is None


def test_confirm_absence_via_service_scm_present_distro_scan_none_stays_none() -> None:
    from civiccast.native.win_probes import _confirm_absence_via_service

    assert _confirm_absence_via_service(lambda: True, distro_scanner=lambda: None) is None


def test_confirm_absence_via_service_scm_ambiguous_distro_scan_false_is_false() -> None:
    """The SCM itself being ambiguous (None, e.g. sc.exe timed out) is
    treated the same as "present" for purposes of consulting the distro
    scan -- only a DEFINITE SCM False short-circuits."""

    from civiccast.native.win_probes import _confirm_absence_via_service

    assert _confirm_absence_via_service(lambda: None, distro_scanner=lambda: False) is False


def test_confirm_absence_via_service_scm_ambiguous_distro_scan_true_stays_none() -> None:
    from civiccast.native.win_probes import _confirm_absence_via_service

    assert _confirm_absence_via_service(lambda: None, distro_scanner=lambda: True) is None


def test_confirm_absence_via_service_default_distro_scanner_resolved_by_module_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors the existing `wsl_service_present` default-resolution
    contract: when `distro_scanner` is not supplied, the module-level
    `scan_registered_distros` is resolved BY NAME at call time (not bound as
    a default argument), so monkeypatching the module attribute takes
    effect."""

    from civiccast.native import win_probes

    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: False)
    assert win_probes._confirm_absence_via_service(lambda: True) is False

    monkeypatch.setattr(win_probes, "scan_registered_distros", lambda **kwargs: True)
    assert win_probes._confirm_absence_via_service(lambda: True) is None


# --------------------------------------------------------------------------
# scan_registered_distros itself: the registry-backed, LocalSystem-safe
# distro inventory. Same fixture style as scan_run_entries's tests -- a real
# HKCU test key stands in for HKEY_USERS, with one level of "FakeHive"
# child(ren) standing in for loaded per-user hives.
# --------------------------------------------------------------------------


def test_scan_registered_distros_true_when_matching_distribution_name_present(
    hkcu_test_key: str,
) -> None:
    fake_hive = f"{hkcu_test_key}\\FakeHive"
    guid_path = f"{fake_hive}\\{WSL_LXSS_KEY_PATH}\\{{fake-guid-1}}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, guid_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DistributionName", 0, winreg.REG_SZ, WSL_DISTRO_NAME)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is True


def test_scan_registered_distros_false_when_only_non_matching_distros_present(
    hkcu_test_key: str,
) -> None:
    fake_hive = f"{hkcu_test_key}\\FakeHive"
    guid_path = f"{fake_hive}\\{WSL_LXSS_KEY_PATH}\\{{fake-guid-1}}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, guid_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DistributionName", 0, winreg.REG_SZ, "Ubuntu-22.04")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is False


def test_scan_registered_distros_false_when_hive_has_no_lxss_key_at_all(
    hkcu_test_key: str,
) -> None:
    """A missing Lxss key under a loaded hive is a clean absence for that
    hive (continue), never a failure -- a hive that simply has no WSL
    distros at all must not downgrade the scan to None."""

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{hkcu_test_key}\\FakeHive", 0, winreg.KEY_SET_VALUE
    ):
        pass
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is False


def test_scan_registered_distros_hive_raising_non_filenotfound_oserror_is_none(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FALSIFICATION: a non-FileNotFoundError OSError while reading a
    DistributionName value (e.g. access denied) must NOT be silently treated
    as a clean skip -- FileNotFoundError is the ONLY OSError meaning
    readable absence in this file's convention; every other OSError makes
    the whole scan untrusted (None), never a confident False."""

    fake_hive = f"{hkcu_test_key}\\FakeHive"
    guid_path = f"{fake_hive}\\{WSL_LXSS_KEY_PATH}\\{{fake-guid-1}}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, guid_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DistributionName", 0, winreg.REG_SZ, "Ubuntu-22.04")

    real_query_value_ex = winreg.QueryValueEx

    def flaky_query_value_ex(key: object, name: str) -> tuple[str, int]:
        if name == "DistributionName":
            raise PermissionError(13, "Access is denied", None, 5)
        return real_query_value_ex(key, name)  # type: ignore[arg-type]

    monkeypatch.setattr(winreg, "QueryValueEx", flaky_query_value_ex)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is None


def test_scan_registered_distros_hkey_users_enumeration_failure_is_none(
    hkcu_test_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FALSIFICATION: a non-259 OSError raised by EnumKey while scanning the
    top-level users_root for hives must fail the whole scan closed (None),
    mirroring scan_run_entries's F3 discipline -- never conflated with the
    real end-of-enumeration sentinel (winerror=259)."""

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{hkcu_test_key}\\SomeHive", 0, winreg.KEY_SET_VALUE
    ):
        pass

    def flaky_enum_key(key: object, index: int) -> str:
        raise OSError(22, "key deleted mid-scan", None, 1018)

    monkeypatch.setattr(winreg, "EnumKey", flaky_enum_key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is None


def test_scan_registered_distros_real_end_of_list_winerror_259_is_clean_false(
    hkcu_test_key: str,
) -> None:
    """The REAL end-of-enumeration sentinel (winerror=259) must still be a
    clean, ordinary end of scan -- False, not None."""

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{hkcu_test_key}\\SomeHive", 0, winreg.KEY_SET_VALUE
    ):
        pass
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is False


def test_scan_registered_distros_skips_classes_suffixed_hives(hkcu_test_key: str) -> None:
    """FALSIFICATION: a matching DistributionName planted under a
    "<hive>_Classes" subkey must NEVER be found -- those are skipped per the
    same rule scan_run_entries follows."""

    fake_hive_classes = f"{hkcu_test_key}\\FakeHive_Classes"
    guid_path = f"{fake_hive_classes}\\{WSL_LXSS_KEY_PATH}\\{{fake-guid-1}}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, guid_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DistributionName", 0, winreg.REG_SZ, WSL_DISTRO_NAME)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hkcu_test_key) as fake_users_root_handle:
        result = scan_registered_distros(users_root=fake_users_root_handle)
    assert result is False


def test_scan_registered_distros_without_a_registry_is_unknown_not_absent(monkeypatch) -> None:
    """No registry at all (any non-Windows host) must be UNKNOWN, not False.

    This is the exact failure that broke CI's platform-independent lane:
    ``scan_registered_distros`` imported ``winreg`` unguarded, so on Linux it
    raised ``ModuleNotFoundError`` straight out of a tri-state probe whose
    whole contract is to downgrade to UNKNOWN rather than fail loudly --
    taking ``detect_wsl_install`` and
    ``test_phase5_verify_rejects_truncated_evidence_on_resume`` with it.

    A confident ``False`` here would be actively dangerous, not merely wrong:
    "no CivicCast WSL distro is registered" is an input to the selector's
    "absent + no WSL install => continue as native" decision. Answering False
    because we could not look is how a machine that DOES have the WSL lane
    gets treated as a clean native box.

    winreg exists on the Windows hosts where this file runs, so the guard is
    unreachable without forcing it -- hence the import hook.
    """

    import builtins

    real_import = builtins.__import__

    def _no_winreg(name, *args, **kwargs):
        if name == "winreg":
            raise ModuleNotFoundError("No module named 'winreg'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "winreg", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_winreg)

    assert scan_registered_distros() is None
