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


@pytest.mark.parametrize("installed", [False, True])
def test_backup_cli_preflight_only_requires_elevation_for_installed_service(monkeypatch, installed):
    from civiccast.native import admin_recovery

    monkeypatch.setattr(
        station_backup_runtime, "_installed_station_service_present", lambda: installed
    )
    checks = []
    monkeypatch.setattr(admin_recovery, "_require_elevation", lambda: checks.append("token"))
    station_backup_runtime.preflight_station_backup_cli()
    assert checks == (["token"] if installed else [])


def test_installed_backup_cli_preflight_denies_before_loading_state(monkeypatch):
    from civiccast.native import admin_recovery

    monkeypatch.setattr(station_backup_runtime, "_installed_station_service_present", lambda: True)

    def denied():
        raise admin_recovery.RecoveryError("private diagnostic")

    monkeypatch.setattr(admin_recovery, "_require_elevation", denied)
    with pytest.raises(PermissionError, match="Run as administrator") as raised:
        station_backup_runtime.preflight_station_backup_cli()
    assert "private diagnostic" not in str(raised.value)


@pytest.mark.parametrize("override", ["default", "uploads", "documents"])
def test_managed_agenda_root_uses_replacement_service_paths(tmp_path, monkeypatch, override):
    from civiccast.native.supervisor import install_layout

    root = tmp_path / "replacement"
    environment = {"CIVICCAST_STATION_STATE_PATH": str(root / "profile" / "station-state.json")}
    expected = root / "data" / "uploads" / "agenda-import"
    if override in {"uploads", "documents"}:
        environment["CIVICCAST_UPLOAD_DIR"] = str(root / "custom-uploads")
        expected = root / "custom-uploads" / "agenda-import"
    if override == "documents":
        environment["CIVICCAST_AGENDA_DOCUMENT_DIR"] = str(root / "custom-agendas")
        expected = root / "custom-agendas"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unused.db")
    monkeypatch.setenv("CIVICCAST_AGENDA_DOCUMENT_DIR", str(tmp_path / "unrelated-admin-agendas"))
    monkeypatch.setattr(
        station_backup_runtime, "_read_installed_service_environment", lambda: environment
    )
    monkeypatch.setattr(
        install_layout,
        "resolve_install_layout",
        lambda: SimpleNamespace(civiccast_data_root=root, pg_ctl_path=root / "pg_ctl.exe"),
    )
    service = build_station_backup_service()
    assert service.managed_roots == {"agenda-import": expected}
    assert service.media_roots == ()


def test_portable_service_environment_is_allowlisted_and_excludes_database_url():
    captured = station_backup_runtime._portable_service_environment(
        {
            "DATABASE_URL": "postgresql://old-user:old-password@old-host/old-db",
            "CIVICCAST_CONFIG_DIR": r"C:\old\profile\.civiccast",
            "CIVICCAST_STATION_STATE_PATH": r"C:\old\profile\station-state.json",
            "CIVICCAST_SMTP_HOST": "smtp.example.test",
            "CIVICCAST_SMTP_PASSWORD": "smtp-private",
            "CIVICCAST_AGENDA_SOURCE": "primegov",
            "CIVICCAST_AGENDA_SOURCE_CLIENT": "example",
            "CIVICCAST_AGENDA_SOURCE_TIMEOUT_S": "15",
            "CIVICCAST_AGENDA_DOCUMENT_DIR": r"C:\old\agenda-import",
            "UNRELATED_SECRET": "do-not-backup",
        }
    )
    assert captured == {
        "CIVICCAST_SMTP_HOST": "smtp.example.test",
        "CIVICCAST_SMTP_PASSWORD": "smtp-private",
        "CIVICCAST_AGENDA_SOURCE": "primegov",
        "CIVICCAST_AGENDA_SOURCE_CLIENT": "example",
        "CIVICCAST_AGENDA_SOURCE_TIMEOUT_S": "15",
    }


@pytest.mark.parametrize("override", [False, True])
def test_effective_application_config_included_with_unrelated_state_override(
    tmp_path, monkeypatch, override
):
    from civiccast.native.supervisor import install_layout

    root = tmp_path / "replacement"
    effective = root / "profile" / "CivicCast" / "app-platform-config.json"
    environment = {
        "LOCALAPPDATA": str(root / "profile"),
        "CIVICCAST_STATION_STATE_PATH": str(root / "other" / "station-state.json"),
    }
    if override:
        effective = root / "custom-config" / "branding.json"
        environment["CIVICCAST_APP_PLATFORM_CONFIG_PATH"] = str(effective)
    effective.parent.mkdir(parents=True)
    effective.write_text('{"station_name":"Preserved station"}')
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unused.db")
    monkeypatch.setattr(
        runtime := station_backup_runtime,
        "_read_installed_service_environment",
        lambda: environment,
    )
    monkeypatch.setattr(
        install_layout,
        "resolve_install_layout",
        lambda: SimpleNamespace(civiccast_data_root=root, pg_ctl_path=root / "pg_ctl.exe"),
    )
    service = runtime.build_station_backup_service()
    assert effective in service.config_paths
    assert effective in service.config_paths_provider()
    assert service.credential_destination is not None


def test_full_station_restore_refuses_unacknowledged_local_settings_before_archive_access(tmp_path):
    from civiccast.dr.station_backup import StationBackupService

    service = StationBackupService(
        database_url="sqlite:///unused.db",
        destination=tmp_path / "backups",
        credential_destination="local vault and service settings",
    )
    with pytest.raises(RuntimeError, match="explicit acknowledgement"):
        service.restore_backup(
            tmp_path / "nonexistent.ccbackup",
            "recovery-test-passphrase",
            target_database_url="sqlite:///clone.db",
            writers_stopped=True,
        )
    assert not (tmp_path / "clone.db").exists()


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
    app_config = station_config / "app-platform-config.json"
    app_config.write_text('{"station_name":"Effective operator branding"}')
    caption_settings = station_config / "offline-caption-settings.json"
    caption_settings.write_text('{"enabled":false,"languages":["en"]}')
    agenda_settings = station_config / "agenda-import-settings.json"
    agenda_settings.write_text('{"source":"primegov","client_code":"example"}')
    (config_root / "existing.json").write_text('{"provider":"configured"}')
    database = tmp_path / "station.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE station (name TEXT)")
        connection.execute("INSERT INTO station VALUES ('preserved')")
        connection.commit()
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(profile))
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
    assert app_config in service.config_paths
    assert caption_settings in service.config_paths
    assert agenda_settings in service.config_paths
    assert service.managed_roots == {"agenda-import": root / "data" / "uploads" / "agenda-import"}
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
    assert any(record["source_path"] == str(app_config) for record in inventory["payload"])
    assert any(record["source_path"] == str(late_config) for record in inventory["payload"])
    assert any(record["source_path"] == str(caption_settings) for record in inventory["payload"])
    assert b"smtp-test-secret" not in artifact.path.read_bytes()
    assert b"camera-test-secret" not in artifact.path.read_bytes()

    # Restore into a different disposable station, exercising real machine-DPAPI
    # credential import. Service-registry writes are captured, never redirected
    # to the developer's installed service. Its merge policy has separate tests.
    source_vault_bytes = vault.path.read_bytes()
    replacement_root = tmp_path / "replacement" / "CivicCast"
    replacement_database = tmp_path / "replacement.db"
    with closing(sqlite3.connect(replacement_database)) as connection:
        connection.execute("CREATE TABLE station (name TEXT)")
        connection.execute("INSERT INTO station VALUES ('replacement sentinel')")
        connection.commit()
    monkeypatch.setenv("PROGRAMDATA", str(replacement_root.parent))
    monkeypatch.setenv("LOCALAPPDATA", str(replacement_root / "profile"))
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(replacement_root / "station-state.json"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{replacement_database.as_posix()}")
    monkeypatch.setattr(
        install_layout,
        "resolve_install_layout",
        lambda: SimpleNamespace(
            civiccast_data_root=replacement_root,
            pg_ctl_path=tmp_path / "bin" / "pg_ctl.exe",
        ),
    )
    environment_imports = []
    monkeypatch.setattr(
        station_backup_runtime,
        "_restore_portable_service_environment",
        environment_imports.append,
    )
    replacement_vault = StationSecretVault()
    replacement_vault.set("civiccast.live-source", "camera", "replacement-test-secret")
    replacement = build_station_backup_service()
    target_paths = {
        record["source_path"]: replacement_root / "restored-config" / str(index)
        for index, record in enumerate(inventory["payload"])
        if record["kind"] == "config"
    }
    restore_args = {
        "target_database_url": f"sqlite:///{replacement_database.as_posix()}",
        "target_paths": target_paths,
        "writers_stopped": True,
    }
    with pytest.raises(RuntimeError, match="acknowledgement"):
        replacement.restore_backup(artifact.path, "recovery-test-passphrase", **restore_args)
    assert replacement_vault.get("civiccast.live-source", "camera") == "replacement-test-secret"
    assert not environment_imports
    with closing(sqlite3.connect(replacement_database)) as connection:
        assert connection.execute("SELECT name FROM station").fetchall() == [
            ("replacement sentinel",)
        ]

    result = replacement.restore_backup(
        artifact.path,
        "recovery-test-passphrase",
        restore_local_station_settings=True,
        **restore_args,
    )
    assert result.database_restored
    assert replacement_vault.get("civiccast.live-source", "camera") == "camera-test-secret"
    assert b"camera-test-secret" not in replacement_vault.path.read_bytes()
    assert vault.path.read_bytes() == source_vault_bytes
    assert environment_imports == [{"CIVICCAST_SMTP_PASSWORD": "smtp-test-secret"}]
    assert target_paths[str(app_config)].read_text() == app_config.read_text()
    with closing(sqlite3.connect(replacement_database)) as connection:
        assert connection.execute("SELECT name FROM station").fetchall() == [("preserved",)]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT name FROM station").fetchall() == [("preserved",)]
