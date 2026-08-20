# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows ACL protection contract for local private keys and secret-hash
state files.

Regression home for blocker N-01: ``POST /api/staff/installer/first-admin``
returned HTTP 500 on a pristine WORKGROUP (non-domain) station because the
private-key/state ACL step granted ``%USERNAME%`` -- which under the
LocalSystem supervisor service is the MACHINE ACCOUNT ``COMPUTERNAME$``. That
principal has no local SID mapping on a non-domain machine, so ``icacls`` exits
1332 (ERROR_NONE_MAPPED) and the unhandled ``CalledProcessError`` propagated
out of first-admin setup as a 500. The fix grants three well-known/textual SIDs
(the caller's own token SID + SYSTEM + Administrators), never a name.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from civiccast.certs import authority

_SAMPLE_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"

windows_only = pytest.mark.skipif(os.name != "nt", reason="Real icacls behavior is Windows-only.")


# --------------------------------------------------------------------------- #
# Pure command-builder contract (cross-platform)                              #
# --------------------------------------------------------------------------- #
def test_command_grants_three_sids_by_star_prefix() -> None:
    path = Path(r"C:\CivicCast\certs\ca\civiccast-local-ca.key")

    command = authority._windows_private_key_acl_command(path, principal_sid=_SAMPLE_SID)

    assert command == [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"*{_SAMPLE_SID}:F",
        "*S-1-5-18:F",
        "*S-1-5-32-544:F",
    ]


def test_command_never_emits_a_bare_name_or_machine_account() -> None:
    """The N-01 regression guard: every grantee must be a raw SID (``*S-1-...``),
    never an account NAME and never the machine account ``COMPUTERNAME$``."""

    command = authority._windows_private_key_acl_command(
        Path(r"C:\CivicCast\key.pem"), principal_sid=_SAMPLE_SID
    )
    grants = command[command.index("/grant:r") + 1 :]
    assert grants, "expected at least one grant token"
    for token in grants:
        assert token.startswith("*S-1-"), f"grant {token!r} is not a raw SID"
        assert not token.endswith("$:F"), f"grant {token!r} is a machine account"


@pytest.mark.parametrize("bad", ["operator", "NVIDEABLACKWELL$", "", "S-1", "*S-1-5-18"])
def test_command_rejects_non_sid_principal(bad: str) -> None:
    with pytest.raises(ValueError, match="not a textual SID"):
        authority._windows_private_key_acl_command(Path(r"C:\k.pem"), principal_sid=bad)


# --------------------------------------------------------------------------- #
# _restrict wrapper: seam injection, argv, and fail-loud (cross-platform)      #
# --------------------------------------------------------------------------- #
def test_restrict_reads_token_sid_and_runs_icacls_without_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Identity comes from the injected SID reader (the token in production),
    NOT from %USERNAME% -- even a hostile machine-account USERNAME is ignored."""

    monkeypatch.setenv("USERNAME", "NVIDEABLACKWELL$")  # the LocalSystem trap
    key_path = tmp_path / "key.pem"
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": command, **kwargs})

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(authority.subprocess, "run", fake_run)

    authority._restrict_windows_private_key_acl(key_path, sid_reader=lambda: _SAMPLE_SID)

    assert calls == [
        {
            "command": authority._windows_private_key_acl_command(
                key_path, principal_sid=_SAMPLE_SID
            ),
            "check": False,
            "capture_output": True,
            "text": True,
            "creationflags": getattr(authority.subprocess, "CREATE_NO_WINDOW", 0),
        }
    ]
    # And the argv carries no machine-account / name grantee.
    for token in calls[0]["command"]:  # type: ignore[union-attr]
        assert not str(token).endswith("$:F")


def test_restrict_fails_loud_on_nonzero_icacls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        class Result:
            returncode = 1332
            stdout = ""
            stderr = "user$: No mapping between account names and security IDs was done."

        return Result()

    monkeypatch.setattr(authority.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        authority._restrict_windows_private_key_acl(
            tmp_path / "key.pem", sid_reader=lambda: _SAMPLE_SID
        )
    message = str(excinfo.value)
    assert "1332" in message
    assert "No mapping" in message  # stderr surfaced, not swallowed


def test_restrict_fails_loud_when_sid_unreadable(tmp_path: Path) -> None:
    def broken_reader() -> str:
        raise OSError("token query failed")

    with pytest.raises(RuntimeError, match="own user SID could not be read"):
        authority._restrict_windows_private_key_acl(tmp_path / "key.pem", sid_reader=broken_reader)


# --------------------------------------------------------------------------- #
# Real-icacls RED/GREEN on THIS (non-domain) box                              #
# --------------------------------------------------------------------------- #
@windows_only
def test_machine_account_name_grant_reproduces_1332_red(tmp_path: Path) -> None:
    """RED / root cause: the pre-fix principal -- the machine account
    ``COMPUTERNAME$`` -- does NOT resolve on a workgroup station, so real
    icacls fails the whole file with exit 1332. This is exactly what the
    LocalSystem service ran during first-admin setup."""

    key = tmp_path / "key.pem"
    key.write_text("secret")
    machine_account = f"{os.environ['COMPUTERNAME']}$"
    result = subprocess.run(
        [
            "icacls",
            str(key),
            "/inheritance:r",
            "/grant:r",
            f"{machine_account}:F",
            "SYSTEM:F",
            "Administrators:F",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "machine account unexpectedly resolved on this box"
    combined = (result.stdout + result.stderr).lower()
    assert "no mapping" in combined  # ERROR_NONE_MAPPED / 1332


@windows_only
def test_restrict_real_icacls_succeeds_and_grants_expected_principals(tmp_path: Path) -> None:
    """GREEN: the fixed helper runs real icacls against a real file on this
    non-domain box and leaves SYSTEM + Administrators (well-known SIDs)
    holding the file, with inheritance stripped."""

    key = tmp_path / "key.pem"
    key.write_text("secret")

    authority._restrict_windows_private_key_acl(key)  # real token SID reader

    readback = subprocess.run(["icacls", str(key)], capture_output=True, text=True)
    assert readback.returncode == 0
    text = readback.stdout
    assert "NT AUTHORITY\\SYSTEM:(F)" in text
    assert "BUILTIN\\Administrators:(F)" in text


# --------------------------------------------------------------------------- #
# Full first-admin path under the exact LocalSystem condition (N-01)          #
# --------------------------------------------------------------------------- #
@windows_only
def test_first_admin_completes_under_localsystem_username(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end N-01 proof: drive the exact service function the
    ``/api/staff/installer/first-admin`` endpoint calls, with ``%USERNAME%``
    set to the machine account (what LocalSystem presents), on this workgroup
    box with REAL icacls. Pre-fix this raised ``CalledProcessError`` (exit
    1332) -> HTTP 500; post-fix it completes and the persisted state file is
    hardened to SYSTEM + Administrators + caller."""

    from civiccast.installer.models import FirstAdminSetupRequest
    from civiccast.installer.service import complete_first_admin_setup

    state_path = tmp_path / "station-state.json"
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state_path))
    monkeypatch.setenv("USERNAME", f"{os.environ['COMPUTERNAME']}$")

    request = FirstAdminSetupRequest(
        station_name="Test PEG Station",
        admin_display_name="Ada Admin",
        admin_username="ada",
        admin_password="Correct-Horse-Battery-9",
        recovery_kit_destination=str(tmp_path / "kit.pdf"),
    )

    response = complete_first_admin_setup(request)  # must NOT raise

    assert response is not None
    assert state_path.exists()
    readback = subprocess.run(["icacls", str(state_path)], capture_output=True, text=True)
    assert readback.returncode == 0
    assert "NT AUTHORITY\\SYSTEM:(F)" in readback.stdout
    assert "BUILTIN\\Administrators:(F)" in readback.stdout
