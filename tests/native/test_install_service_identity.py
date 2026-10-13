# SPDX-License-Identifier: Apache-2.0
"""Exercise installer decisions without changing this machine's SCM or registry."""

import os
from contextlib import nullcontext

import pytest

from civiccast.native import install_service_identity as migration
from civiccast.native.install_service_identity import _grant_tree as grant_windows_tree
from civiccast.native.service_identity import SERVICE_ACCOUNT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows installer APIs")


@pytest.fixture
def installed(tmp_path, monkeypatch):
    import winreg

    import win32service

    from civiccast.native import admin_recovery

    root = tmp_path / "app"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "python.exe").touch()
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(profile / "station-state.json"))
    state = {"environment": ["CUSTOM=preserved"], "account": "LocalSystem", "starts": 0}
    monkeypatch.setattr(admin_recovery, "_require_elevation", lambda: None)
    monkeypatch.setattr(migration, "station_profile_root", lambda: profile)
    monkeypatch.setattr(migration, "_grant_tree", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration, "restrict_data_directory", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration, "_grant_database_key_read", lambda: None)
    monkeypatch.setattr(migration, "_grant_service_environment_read", lambda: None)
    monkeypatch.setattr(winreg, "OpenKey", lambda *args: nullcontext("key"))
    monkeypatch.setattr(
        winreg, "QueryValueEx", lambda *args: (state["environment"], winreg.REG_MULTI_SZ)
    )
    monkeypatch.setattr(winreg, "SetValueEx", lambda *args: state.update(environment=args[-1]))
    monkeypatch.setattr(win32service, "OpenSCManager", lambda *args: "scm")
    monkeypatch.setattr(win32service, "OpenService", lambda *args: "service")
    monkeypatch.setattr(win32service, "CloseServiceHandle", lambda *args: None)
    monkeypatch.setattr(
        win32service, "QueryServiceConfig", lambda *args: [None] * 7 + [state["account"]]
    )
    monkeypatch.setattr(
        win32service, "QueryServiceStatus", lambda *args: [0, win32service.SERVICE_STOPPED]
    )

    def start(*args):
        assert migration.MIGRATION_ENV + "=1" in state["environment"]
        state["starts"] += 1
        (profile / "identity-migration.complete").write_text("preserved")

    monkeypatch.setattr(win32service, "StartService", start)
    monkeypatch.setattr(
        win32service, "ChangeServiceConfig", lambda *args: state.update(account=args[8])
    )
    return root, state


def test_migration_preserves_environment_and_changes_account_after_export(installed):
    root, state = installed
    migration.configure_service_identity(root)
    assert state["account"] == SERVICE_ACCOUNT
    assert state["starts"] == 1
    assert "CUSTOM=preserved" in state["environment"]
    assert not any(item.startswith(migration.MIGRATION_ENV + "=") for item in state["environment"])
    assert any(item.startswith("LOCALAPPDATA=") for item in state["environment"])


def test_failed_export_keeps_original_identity_and_environment(installed, monkeypatch):
    import win32service

    root, state = installed
    monkeypatch.setattr(win32service, "StartService", lambda *args: None)
    with pytest.raises(RuntimeError, match="could not preserve"):
        migration.configure_service_identity(root)
    assert state["account"] == "LocalSystem"
    assert state["environment"] == ["CUSTOM=preserved"]


def test_existing_virtual_account_skips_old_account_export(installed):
    root, state = installed
    state["account"] = SERVICE_ACCOUNT
    migration.configure_service_identity(root)
    assert state["starts"] == 0


def test_virtual_account_configuration_uses_null_password(installed, monkeypatch):
    import win32service

    root, _ = installed
    calls = []
    monkeypatch.setattr(win32service, "ChangeServiceConfig", lambda *args: calls.append(args))
    migration.configure_service_identity(root)
    assert calls[0][8] == SERVICE_ACCOUNT
    assert calls[0][9] is None


def test_data_root_grant_does_not_override_protected_installer_subtrees(installed, monkeypatch):
    import win32security

    from civiccast.native.service_identity import SERVICE_SID
    from civiccast.native.upgrade.journal import _harden_state_root_acl

    root, state = installed
    state["account"] = SERVICE_ACCOUNT
    data_root = root.parent / "CivicCast"
    protected = data_root / "upgrade"
    protected.mkdir(parents=True)
    _harden_state_root_acl(protected)

    def grant(path, rights, **kwargs):
        if path == data_root:
            grant_windows_tree(path, rights, **kwargs)

    monkeypatch.setattr(migration, "_grant_tree", grant)
    migration.configure_service_identity(root)
    acl = win32security.GetFileSecurity(
        str(protected), win32security.DACL_SECURITY_INFORMATION
    ).GetSecurityDescriptorDacl()
    trustees = {
        win32security.ConvertSidToStringSid(acl.GetAce(index)[2])
        for index in range(acl.GetAceCount())
    }
    assert SERVICE_SID not in trustees


@pytest.mark.parametrize("stop_finishes", [True, False])
def test_timed_out_migration_waits_for_stopped_before_restoring_environment(
    installed, monkeypatch, stop_finishes
):
    import win32service

    root, state = installed
    statuses = iter(
        [
            win32service.SERVICE_STOPPED,
            win32service.SERVICE_RUNNING,
            win32service.SERVICE_STOP_PENDING,
            win32service.SERVICE_STOPPED,
        ]
    )
    observed = []

    def query(*args):
        status = next(statuses)
        observed.append(status)
        if len(observed) > 1:
            assert migration.MIGRATION_ENV + "=1" in state["environment"]
        return [0, status]

    times = iter([0, 91, 91, 92 if stop_finishes else 122])
    monkeypatch.setattr(migration.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(migration.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(win32service, "QueryServiceStatus", query)
    monkeypatch.setattr(win32service, "ControlService", lambda *args: None)
    message = "90 seconds" if stop_finishes else "migration-only mode retained"
    with pytest.raises(RuntimeError, match=message):
        migration.configure_service_identity(root)
    assert state["account"] == "LocalSystem"
    if stop_finishes:
        assert observed[-1] == win32service.SERVICE_STOPPED
        assert state["environment"] == ["CUSTOM=preserved"]
    else:
        assert observed[-1] == win32service.SERVICE_STOP_PENDING
        assert migration.MIGRATION_ENV + "=1" in state["environment"]


def test_custom_account_refused_before_modification(installed):
    root, state = installed
    state["account"] = "DOMAIN\\custom"
    with pytest.raises(RuntimeError, match="Custom service accounts"):
        migration.configure_service_identity(root)
    assert state == {"environment": ["CUSTOM=preserved"], "account": "DOMAIN\\custom", "starts": 0}


def test_configured_media_paths_honor_service_override(tmp_path, monkeypatch):
    import json

    state = tmp_path / "station-state.json"
    media = tmp_path / "old-media"
    recordings = tmp_path / "recordings"
    state.write_text(
        json.dumps(
            {
                "station": {
                    "storage_locations": {
                        "media_library": str(media),
                        "recordings": str(recordings),
                    }
                }
            }
        )
    )
    for variable in (
        "CIVICCAST_STATION_MEDIA_LIBRARY",
        "CIVICCAST_STATION_RECORDINGS",
        "CIVICCAST_STATION_BACKUPS",
    ):
        monkeypatch.delenv(variable, raising=False)
    override = tmp_path / "selected-media"
    assert migration._configured_storage_paths(
        [f"CIVICCAST_STATION_MEDIA_LIBRARY={override}"], state
    ) == [override, recordings]


@pytest.mark.parametrize("service_environment", [False, True])
def test_registry_secret_grants_service_read_only_on_disposable_key(
    monkeypatch, service_environment
):
    import uuid
    import winreg

    import win32con
    import win32security

    from civiccast.native.service_identity import SERVICE_SID

    name = rf"Software\CivicCastIdentityTest\{uuid.uuid4().hex}"
    real_open = winreg.OpenKey
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_ALL_ACCESS)
    child = winreg.CreateKeyEx(key, "PythonClass", 0, winreg.KEY_ALL_ACCESS)
    original_acl = win32security.GetSecurityInfo(
        int(key), win32security.SE_REGISTRY_KEY, win32security.DACL_SECURITY_INFORMATION
    ).GetSecurityDescriptorDacl()
    key.Close()
    try:

        def redirected_open(hive, path, reserved, access):
            assert hive == winreg.HKEY_LOCAL_MACHINE
            assert path == (
                migration.SERVICE_KEY if service_environment else r"SOFTWARE\CivicCast\Native"
            )
            return real_open(winreg.HKEY_CURRENT_USER, name, reserved, access)

        monkeypatch.setattr(winreg, "OpenKey", redirected_open)
        if service_environment:
            migration._grant_service_environment_read()
        else:
            migration._grant_database_key_read()
        with real_open(winreg.HKEY_CURRENT_USER, name, 0, win32con.READ_CONTROL) as readback:
            descriptor = win32security.GetSecurityInfo(
                int(readback),
                win32security.SE_REGISTRY_KEY,
                win32security.DACL_SECURITY_INFORMATION,
            )
            acl = descriptor.GetSecurityDescriptorDacl()
            grants = {
                win32security.ConvertSidToStringSid(acl.GetAce(i)[2]): acl.GetAce(i)[1]
                for i in range(acl.GetAceCount())
            }
            assert grants[SERVICE_SID] == winreg.KEY_READ
            assert set(grants) == {SERVICE_SID, "S-1-5-18", "S-1-5-32-544"}
        child_acl = win32security.GetSecurityInfo(
            int(child), win32security.SE_REGISTRY_KEY, win32security.DACL_SECURITY_INFORMATION
        ).GetSecurityDescriptorDacl()
        child_grants = {
            win32security.ConvertSidToStringSid(child_acl.GetAce(i)[2]): child_acl.GetAce(i)[1]
            for i in range(child_acl.GetAceCount())
        }
        assert child_grants[SERVICE_SID] == winreg.KEY_READ
        assert child_grants["S-1-5-18"] == winreg.KEY_ALL_ACCESS
        assert child_grants["S-1-5-32-544"] == winreg.KEY_ALL_ACCESS
    finally:
        child.Close()
        with real_open(winreg.HKEY_CURRENT_USER, name, 0, win32con.WRITE_DAC) as cleanup:
            win32security.SetSecurityInfo(
                int(cleanup),
                win32security.SE_REGISTRY_KEY,
                win32security.DACL_SECURITY_INFORMATION,
                None,
                None,
                original_acl,
                None,
            )
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name + r"\PythonClass")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
