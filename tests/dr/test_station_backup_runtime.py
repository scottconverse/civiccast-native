# SPDX-License-Identifier: Apache-2.0
"""Installed-path backup integration using a disposable real database."""

import os
import sqlite3
import sys
from contextlib import closing, contextmanager
from types import SimpleNamespace

import pytest

from civiccast.dr import station_backup_runtime
from civiccast.dr.station_backup_runtime import build_station_backup_service
from civiccast.native.station_secrets import StationSecretVault


def test_portable_service_environment_is_allowlisted_and_excludes_database_url():
    captured = station_backup_runtime._portable_service_environment(
        {
            "DATABASE_URL": "postgresql://old-user:old-password@old-host/old-db",
            "CIVICCAST_CONFIG_DIR": r"C:\old\profile\.civiccast",
            "CIVICCAST_STATION_STATE_PATH": r"C:\old\profile\station-state.json",
            "CIVICCAST_SMTP_HOST": "smtp.example.test",
            "CIVICCAST_SMTP_PASSWORD": "smtp-private",
            "UNRELATED_SECRET": "do-not-backup",
        }
    )
    assert captured == {
        "CIVICCAST_SMTP_HOST": "smtp.example.test",
        "CIVICCAST_SMTP_PASSWORD": "smtp-private",
    }


def test_portable_service_environment_restore_preserves_new_database_and_runtime_paths(
    monkeypatch,
):
    written = {}
    stored = [
        "DATABASE_URL=postgresql://replacement-user:new-password@new-host/new-db",
        r"LOCALAPPDATA=C:\ProgramData\CivicCast\profile",
        r"CIVICCAST_CONFIG_DIR=C:\ProgramData\CivicCast\profile\.civiccast",
        "CIVICCAST_SMTP_HOST=new-install.example.test",
        "OTHER_SETTING=preserved",
    ]

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        KEY_READ=1,
        KEY_SET_VALUE=2,
        KEY_WOW64_64KEY=4,
        REG_MULTI_SZ=7,
        OpenKey=lambda *_args: FakeKey(),
        QueryValueEx=lambda *_args: (stored, 7),
        SetValueEx=lambda _key, name, _reserved, _kind, value: written.update({name: value}),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    with monkeypatch.context() as scoped:
        scoped.setattr(station_backup_runtime.os, "name", "nt")
        station_backup_runtime._restore_portable_service_environment(
            {
                "CIVICCAST_SMTP_HOST": "restored.example.test",
                "CIVICCAST_SMTP_PASSWORD": "restored-private",
            }
        )

    assert written["Environment"] == [
        "DATABASE_URL=postgresql://replacement-user:new-password@new-host/new-db",
        r"LOCALAPPDATA=C:\ProgramData\CivicCast\profile",
        r"CIVICCAST_CONFIG_DIR=C:\ProgramData\CivicCast\profile\.civiccast",
        "OTHER_SETTING=preserved",
        "CIVICCAST_SMTP_HOST=restored.example.test",
        "CIVICCAST_SMTP_PASSWORD=restored-private",
    ]


def test_offline_restore_uses_service_paths_and_restores_admin_environment(monkeypatch, tmp_path):
    from civiccast.native import admin_recovery

    state = tmp_path / "service-profile" / "station-state.json"
    service_config = tmp_path / "service-profile" / ".civiccast"
    admin_config = tmp_path / "admin-profile" / ".civiccast"
    service_config.mkdir(parents=True)
    admin_config.mkdir(parents=True)

    @contextmanager
    def offline_guard():
        yield state

    monkeypatch.setattr(admin_recovery, "_offline_station", offline_guard)
    monkeypatch.setattr(
        station_backup_runtime,
        "_read_installed_service_environment",
        lambda: {"CIVICCAST_CONFIG_DIR": str(service_config)},
    )
    monkeypatch.setenv("CIVICCAST_CONFIG_DIR", str(admin_config))
    with station_backup_runtime.offline_station_restore():
        assert os.environ["CIVICCAST_CONFIG_DIR"] == str(service_config)
        assert os.environ["CIVICCAST_STATION_STATE_PATH"] == str(state)
    assert os.environ["CIVICCAST_CONFIG_DIR"] == str(admin_config)
    assert "CIVICCAST_STATION_STATE_PATH" not in os.environ


def test_offline_restore_owns_managed_postgres_only_for_restore(monkeypatch, tmp_path):
    from civiccast.native import admin_recovery
    from civiccast.native.supervisor import install_layout

    events = []
    state = tmp_path / "station-state.json"
    layout = SimpleNamespace(
        pg_ctl_path=tmp_path / "bin" / "pg_ctl.exe",
        postgres_data_dir=tmp_path / "data" / "pgdata",
    )

    @contextmanager
    def offline_guard():
        events.append("mutex-enter")
        yield state
        events.append("mutex-exit")

    monkeypatch.setattr(admin_recovery, "_offline_station", offline_guard)
    monkeypatch.setattr(station_backup_runtime, "_read_installed_service_environment", lambda: {})
    monkeypatch.setattr(install_layout, "resolve_install_layout", lambda: layout)
    monkeypatch.setattr(
        station_backup_runtime,
        "_managed_postgres_is_running",
        lambda _paths: events.append("status") or False,
    )
    monkeypatch.setattr(
        "civiccast.native.upgrade.pg_lifecycle.real_start_postgres",
        lambda _paths: events.append("start-postgres"),
    )
    monkeypatch.setattr(
        "civiccast.native.upgrade.pg_lifecycle.real_stop_postgres",
        lambda _paths: events.append("stop-postgres"),
    )

    with station_backup_runtime.offline_station_restore(
        installed_database_url="postgresql://station@127.0.0.1:5544/civiccast",
        target_database_url="postgresql://restore@localhost:5544/civiccast",
    ):
        events.append("restore")

    assert events == [
        "mutex-enter",
        "status",
        "start-postgres",
        "restore",
        "stop-postgres",
        "mutex-exit",
    ]


def test_external_database_restore_does_not_start_or_stop_local_postgres(tmp_path):
    events = []
    layout = SimpleNamespace(
        pg_ctl_path=tmp_path / "bin" / "pg_ctl.exe",
        postgres_data_dir=tmp_path / "data" / "pgdata",
    )

    with station_backup_runtime._managed_postgres_for_restore(
        "postgresql://station@127.0.0.1:5544/civiccast",
        "postgresql://restore@db.example.test:5432/civiccast",
        layout,
        status_probe=lambda _paths: events.append("status"),
        start=lambda _paths: events.append("start"),
        stop=lambda _paths: events.append("stop"),
    ):
        events.append("restore")

    assert events == ["restore"]


def test_managed_postgres_stops_even_when_restore_fails(tmp_path):
    events = []
    layout = SimpleNamespace(
        pg_ctl_path=tmp_path / "bin" / "pg_ctl.exe",
        postgres_data_dir=tmp_path / "data" / "pgdata",
    )

    with (
        pytest.raises(RuntimeError, match="restore failed"),
        station_backup_runtime._managed_postgres_for_restore(
            "postgresql://station@127.0.0.1:5544/civiccast",
            "postgresql://restore@127.0.0.1:5544/civiccast",
            layout,
            status_probe=lambda _paths: False,
            start=lambda _paths: events.append("start"),
            stop=lambda _paths: events.append("stop"),
        ),
    ):
        events.append("restore")
        raise RuntimeError("restore failed")

    assert events == ["start", "restore", "stop"]


@pytest.mark.skipif(os.name != "nt", reason="Windows protected scheduler credentials")
def test_runtime_backup_includes_station_state_and_portable_credentials(tmp_path, monkeypatch):
    from civiccast.native.supervisor import install_layout

    root = tmp_path / "CivicCast"
    profile = root / "profile"
    config_root = profile / ".civiccast"
    station_config = profile / "CivicCast"
    config_root.mkdir(parents=True)
    state = station_config / "station-state.json"
    station_config.mkdir(parents=True)
    state.write_text('{"station_name":"Integration station"}')
    (config_root / "existing.json").write_text('{"provider":"configured"}')
    database = tmp_path / "station.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE station (name TEXT)")
        connection.execute("INSERT INTO station VALUES ('preserved')")
        connection.commit()
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state))
    monkeypatch.delenv("CIVICCAST_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_CERT_ROOT", raising=False)
    monkeypatch.setenv("CIVICCAST_NETWORK_SETTINGS_PATH", str(station_config / "network.json"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "admin-profile"))
    monkeypatch.setenv("CIVICCAST_SMTP_PASSWORD", "smtp-test-secret")
    monkeypatch.setattr(station_backup_runtime, "_read_installed_service_environment", lambda: {})
    monkeypatch.setattr(
        install_layout,
        "resolve_install_layout",
        lambda: SimpleNamespace(
            civiccast_data_root=root,
            pg_ctl_path=tmp_path / "bin" / "pg_ctl.exe",
        ),
    )
    vault = StationSecretVault()
    vault.set("civiccast.live-source", "camera", "camera-test-secret")
    service = build_station_backup_service()
    assert state in service.config_paths
    assert config_root / "existing.json" in service.config_paths
    assert not service.has_scheduled_passphrase()
    service.set_scheduled_passphrase("recovery-test-passphrase")
    assert service.has_scheduled_passphrase()
    assert (
        b"recovery-test-passphrase"
        not in (root / "credentials" / "backup-passphrase.dpapi").read_bytes()
    )
    late_config = config_root / "created-after-factory.json"
    late_config.write_text('{"late":true}', encoding="utf-8")
    portable_environment = service.credential_exporter()
    assert portable_environment is not None
    environment_record = portable_environment["station-service-environment.json"]
    assert isinstance(environment_record, bytes)
    assert b"SMTP_PASSWORD" in environment_record
    assert b"old-password" not in environment_record
    artifact = service.create_backup("recovery-test-passphrase")
    assert service.verify_backup(artifact.path, "recovery-test-passphrase").valid
    inventory = service.inspect_backup(artifact.path, "recovery-test-passphrase")
    assert any(record["source_path"] == str(late_config) for record in inventory["payload"])
    assert b"smtp-test-secret" not in artifact.path.read_bytes()
    assert b"camera-test-secret" not in artifact.path.read_bytes()
