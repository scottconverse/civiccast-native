"""Local emergency recovery uses only isolated station state."""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from civiccast.cli import app
from civiccast.installer import station_state
from civiccast.native import admin_recovery as recovery


@pytest.fixture
def station(monkeypatch, tmp_path):
    path = tmp_path / "station-state.json"
    raw = {
        "setup_complete": True,
        "station": {
            "station_name": "Keep this station",
            "channel_count": 3,
            "admin_username": "owner",
            "admin_display_name": "Owner",
            "recovery_kit_id": "old-kit",
            "recovery_kit_generated_at": "2026-10-09T00:00:00+00:00",
        },
        "admin": {"username": "owner", "display_name": "Owner"},
        "operator_console": {
            "tokens": [{"token_hash": "old", "token_salt": "salt"}],
            "token_hash": "legacy",
            "token_salt": "legacy",
        },
        "recovery": {"code_hashes": ["old-code"], "acknowledged": True},
        "other_settings": {"provider_secret": "preserved", "media": ["meeting.mp4"]},
    }
    token, entry = station_state._new_operator_token_entry(source="test")
    raw["operator_console"]["tokens"] = [entry]
    monkeypatch.setattr(recovery, "_test_old_token", token, raising=False)
    station_state._replace_admin_password(raw, "old-password-value")
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(path))

    @contextmanager
    def offline():
        yield path

    monkeypatch.setattr(recovery, "_offline_station", offline)
    return path, raw


@pytest.mark.parametrize("legacy", [False, True])
def test_reset_preserves_data_and_revokes_credentials(station, legacy):
    path, original = station
    if legacy:
        original["operator_console"] = original["operator_console"]["tokens"][0]
        path.write_text(json.dumps(original), encoding="utf-8")
    assert station_state.verify_station_operator_token(recovery._test_old_token) is not None
    backup = recovery.reset_password(path, "new-password-value")
    if sys.platform == "win32":
        import win32security

        from civiccast.certs.authority import _current_process_sid

        allowed = {_current_process_sid(), "S-1-5-18", "S-1-5-32-544"}
        for protected in (path, backup):
            descriptor = win32security.GetNamedSecurityInfo(
                str(protected),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            assert descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
            acl = descriptor.GetSecurityDescriptorDacl()
            actual = {
                win32security.ConvertSidToStringSid(acl.GetAce(i)[2])
                for i in range(acl.GetAceCount())
            }
            assert actual == allowed
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    assert updated["station"] == original["station"]
    assert updated["other_settings"] == original["other_settings"]
    assert updated["admin"]["username"] == "owner"
    assert station_state._verify_admin_password(
        updated, username="owner", password="new-password-value"
    )
    assert not station_state._verify_admin_password(
        updated, username="owner", password="old-password-value"
    )
    assert station_state._operator_token_entries(updated["operator_console"]) == []
    assert station_state.verify_station_operator_token(recovery._test_old_token) is None
    assert updated["recovery"]["code_hashes"] == []
    assert updated["recovery"]["acknowledged"] is True
    assert "new-password-value" not in path.read_text(encoding="utf-8")
    from civiccast.installer.models import StationLoginRequest

    logged_in = station_state.login_station_admin(
        StationLoginRequest(admin_username="owner", admin_password="new-password-value"),
        operator_console_url="http://127.0.0.1:8000/operator",
    )
    assert station_state.verify_station_operator_token(logged_in.operator_console_token) is not None


def test_cli_uses_hidden_prompt_without_password_argument(monkeypatch, station):
    path, _ = station
    monkeypatch.setattr(recovery, "_prompt_password", lambda: "new-password-value")
    result = CliRunner().invoke(app, ["admin", "reset-password"])
    assert result.exit_code == 0, result.output
    assert "new-password-value" not in result.output
    assert "owner" in result.output
    assert json.loads(path.read_text())["operator_console"]["tokens"] == []
    rejected = CliRunner().invoke(app, ["admin", "reset-password", "plaintext"])
    assert rejected.exit_code != 0


@pytest.mark.parametrize("password", ["short", "x" * 257])
def test_invalid_password_preserves_original(station, password):
    path, _ = station
    before = path.read_bytes()
    with pytest.raises(recovery.RecoveryError):
        recovery.reset_password(path, password)
    assert path.read_bytes() == before


def test_failed_replace_preserves_original(monkeypatch, station):
    path, _ = station
    before = path.read_bytes()
    monkeypatch.setattr(
        type(path), "replace", lambda *args: (_ for _ in ()).throw(OSError("denied"))
    )
    with pytest.raises(OSError):
        recovery.reset_password(path, "new-password-value")
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_cli_denies_before_prompt_or_file_access(monkeypatch):
    @contextmanager
    def denied():
        raise recovery.RecoveryError("Run elevated with supervisor stopped.")
        yield

    monkeypatch.setattr(recovery, "_offline_station", denied)
    monkeypatch.setattr(recovery, "_prompt_password", lambda: pytest.fail("must not prompt"))
    result = CliRunner().invoke(app, ["admin", "reset-password"])
    assert result.exit_code == 1
    assert "Run elevated" in result.output


@pytest.mark.parametrize("elevated,member", [(False, True), (True, False), (True, True)])
def test_actual_elevation_and_enabled_admin_membership_required(monkeypatch, elevated, member):
    closed = []
    token = SimpleNamespace(Close=lambda: closed.append(True))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(GetCurrentProcess=lambda: 1))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(TOKEN_QUERY=8))
    monkeypatch.setitem(
        sys.modules,
        "win32security",
        SimpleNamespace(
            OpenProcessToken=lambda *args: token,
            TokenElevation=20,
            GetTokenInformation=lambda *args: elevated,
            WinBuiltinAdministratorsSid=26,
            CreateWellKnownSid=lambda *args: "admin-sid",
            CheckTokenMembership=lambda *args: member,
        ),
    )
    if elevated and member:
        recovery._require_elevation()
    else:
        with pytest.raises(recovery.RecoveryError, match="Run as administrator"):
            recovery._require_elevation()
    assert closed == [True]


@pytest.fixture
def installed_windows(monkeypatch, tmp_path):
    values = {"status": 1, "account": "LocalSystem", "service_env": [], "machine": None}
    closed = []
    monkeypatch.setitem(
        sys.modules,
        "win32service",
        SimpleNamespace(
            SC_MANAGER_CONNECT=1,
            SERVICE_QUERY_STATUS=4,
            SERVICE_QUERY_CONFIG=1,
            SERVICE_STOPPED=1,
            OpenSCManager=lambda *args: "scm",
            OpenService=lambda *args: "service",
            QueryServiceStatus=lambda *args: (0, values["status"]),
            QueryServiceConfig=lambda *args: (None,) * 7 + (values["account"],),
            CloseServiceHandle=lambda handle: closed.append(handle),
        ),
    )
    monkeypatch.setitem(
        sys.modules, "win32api", SimpleNamespace(GetWindowsDirectory=lambda: str(tmp_path))
    )

    @contextmanager
    def open_key(root, name):
        yield name

    def query(key, name):
        if name == "Environment":
            return values["service_env"], 7
        if values["machine"] is None:
            raise FileNotFoundError
        return values["machine"], 1

    monkeypatch.setitem(
        sys.modules,
        "winreg",
        SimpleNamespace(
            HKEY_LOCAL_MACHINE=1,
            REG_SZ=1,
            REG_MULTI_SZ=7,
            OpenKey=open_key,
            QueryValueEx=query,
        ),
    )
    return values, closed


def test_installed_target_ignores_invoking_profile_and_override(
    monkeypatch, installed_windows, tmp_path
):
    values, closed = installed_windows
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "wrong-user"))
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "wrong-state"))
    assert (
        recovery._installed_state_path()
        == tmp_path / "System32/config/systemprofile/AppData/Local/CivicCast/station-state.json"
    )
    values["machine"] = str(tmp_path / "machine-state.json")
    values["service_env"] = [f"CIVICCAST_STATION_STATE_PATH={tmp_path / 'service-state.json'}"]
    assert recovery._installed_state_path() == tmp_path / "service-state.json"
    assert closed == ["service", "scm", "service", "scm"]
    values["machine"] = None
    values["service_env"] = [f"LOCALAPPDATA={tmp_path / 'service-profile'}"]
    assert (
        recovery._installed_state_path()
        == tmp_path / "service-profile/CivicCast/station-state.json"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": 4},
        {"account": r"DOMAIN\other"},
        {"service_env": ["CIVICCAST_STATION_STATE_PATH=relative.json"]},
    ],
)
def test_running_or_wrong_identity_or_ambiguous_target_denied(installed_windows, change):
    values, closed = installed_windows
    values.update(change)
    with pytest.raises(recovery.RecoveryError):
        recovery._installed_state_path()
    assert closed == ["service", "scm"]


@pytest.mark.parametrize("case", ["mismatch", "cancel", "fallback", "pipe"])
def test_hidden_prompt_failures_preserve_original(monkeypatch, station, case):
    path, _ = station
    before = path.read_bytes()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: case != "pipe")
    answers = iter(["new-password-value", "different-password"])

    def prompt(*args):
        if case == "cancel":
            raise KeyboardInterrupt
        if case == "fallback":
            import warnings

            warnings.warn("cannot hide", recovery.getpass.GetPassWarning, stacklevel=2)
        return next(answers)

    monkeypatch.setattr(recovery.getpass, "getpass", prompt)
    with pytest.raises((recovery.RecoveryError, KeyboardInterrupt)):
        recovery._prompt_password()
    assert path.read_bytes() == before


@pytest.mark.parametrize("contents", [b"broken", b"{}", b'{"setup_complete":false}'])
def test_missing_or_corrupt_state_never_reinitialized(tmp_path, contents):
    path = tmp_path / "station-state.json"
    path.write_bytes(contents)
    with pytest.raises(recovery.RecoveryError):
        recovery.reset_password(path, "new-password-value")
    assert path.read_bytes() == contents
    assert list(tmp_path.iterdir()) == [path]


def test_acl_failure_writes_no_credentials_and_preserves_original(monkeypatch, station):
    path, _ = station
    before = path.read_bytes()

    def deny(target):
        assert target.read_bytes() == b""
        raise RuntimeError("ACL denied")

    monkeypatch.setattr(recovery, "_restrict_state_file", deny)
    with pytest.raises(RuntimeError, match="ACL denied"):
        recovery.reset_password(path, "new-password-value")
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.skipif(sys.platform != "win32", reason="Real isolated Windows mutex")
def test_offline_guard_excludes_another_windows_process_owner(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4

    from civiccast.native.supervisor import service
    from civiccast.native.supervisor.config import SINGLETON_MUTEX_SDDL
    from civiccast.native.win_probes import RuntimeOwnerMutex

    # A unique object, never the installed supervisor's live mutex or SCM.
    name = "Local\\CivicCastRecoveryTest-" + uuid4().hex
    monkeypatch.setattr(recovery, "_require_elevation", lambda: None)
    monkeypatch.setattr(recovery, "_installed_state_path", lambda: tmp_path / "station-state.json")
    monkeypatch.setattr(
        service,
        "build_singleton_mutex",
        lambda: RuntimeOwnerMutex(name=name, sddl=SINGLETON_MUTEX_SDDL),
    )

    def attempt():
        with recovery._offline_station():
            return "acquired"

    with recovery._offline_station(), ThreadPoolExecutor(max_workers=1) as executor:  # noqa: SIM117
        with pytest.raises(recovery.RecoveryError, match="active"):
            executor.submit(attempt).result(timeout=5)
    assert attempt() == "acquired"
