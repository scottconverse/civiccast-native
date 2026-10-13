# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.dr import backup as backup_module
from civiccast.dr import station_backup as station_backup_module
from civiccast.dr.station_backup import BackupSchedule, StationBackupService, _restore_postgres


def test_encrypted_backup_contains_database_config_credentials_and_media(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY, message TEXT)")
        connection.execute("INSERT INTO notices(message) VALUES ('public meeting')")
        connection.commit()
    config = tmp_path / "station.json"
    config.write_text('{"station":"demo"}', encoding="utf-8")
    media = tmp_path / "media"
    media.mkdir()
    (media / "meeting.mp4").write_bytes(b"recording payload")

    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
        config_paths=[config],
        media_roots=[media],
        credential_exporter=lambda: {"smtp-password": b"private-secret"},
    )
    artifact = service.create_backup("correct horse battery staple")

    encrypted = artifact.path.read_bytes()
    assert b"private-secret" not in encrypted
    assert b"public meeting" not in encrypted
    assert service.verify_backup(artifact.path, "correct horse battery staple").valid
    with pytest.raises(ValueError, match=r"passphrase|decrypt|authentication"):
        service.verify_backup(artifact.path, "wrong passphrase")


def test_restore_applies_database_and_remaps_configuration_and_media(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY, message TEXT)")
        connection.execute("INSERT INTO notices(message) VALUES ('restore-me')")
        connection.commit()
    config = tmp_path / "old" / "station.json"
    config.parent.mkdir()
    config.write_text('{"station":"restored"}', encoding="utf-8")
    media = tmp_path / "old" / "media"
    media.mkdir()
    (media / "meeting.mp4").write_bytes(b"recording payload")

    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
        config_paths=[config],
        media_roots=[media],
        credential_exporter=lambda: {"smtp": b"portable-secret"},
    )
    artifact = service.create_backup("recovery passphrase")
    target_db = tmp_path / "replacement" / "civiccast.sqlite3"
    target_db.parent.mkdir()
    target_config = tmp_path / "replacement" / "config" / "station.json"
    target_media = tmp_path / "replacement" / "media"
    imported: dict[str, bytes] = {}
    service.credential_importer = imported.update
    result = service.restore_backup(
        artifact.path,
        "recovery passphrase",
        target_database_url=f"sqlite:///{target_db.as_posix()}",
        target_paths={str(config): target_config, str(media): target_media},
        writers_stopped=True,
    )

    assert result.database_restored
    with closing(sqlite3.connect(target_db)) as connection:
        assert connection.execute("SELECT message FROM notices").fetchone() == ("restore-me",)
    assert target_config.read_text(encoding="utf-8") == '{"station":"restored"}'
    assert (target_media / "meeting.mp4").read_bytes() == b"recording payload"
    assert imported == {"smtp": b"portable-secret"}


def test_restore_remaps_database_media_references_and_station_storage_locations(
    tmp_path: Path,
) -> None:
    source_db = tmp_path / "source.sqlite3"
    old_media = tmp_path / "old" / "media"
    old_media.mkdir(parents=True)
    (old_media / "meeting.mp4").write_bytes(b"meeting")
    with closing(sqlite3.connect(source_db)) as connection:
        connection.executescript(
            """
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                file_path TEXT,
                thumbnail_path TEXT
            );
            CREATE TABLE watch_folder_configs (
                config_id TEXT PRIMARY KEY,
                monitor_path TEXT
            );
            CREATE TABLE watch_folder_file_state (
                state_id TEXT PRIMARY KEY,
                file_path TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?)",
            (
                "meeting-1",
                str(old_media / "meeting.mp4"),
                str(old_media / "thumbnails" / "meeting.jpg"),
            ),
        )
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?)",
            ("meeting-2", str(old_media / "other.mp4"), str(tmp_path / "external.jpg")),
        )
        connection.execute(
            "INSERT INTO watch_folder_configs VALUES (?, ?)",
            ("watch-1", str(old_media / "incoming")),
        )
        connection.execute(
            "INSERT INTO watch_folder_file_state VALUES (?, ?)",
            ("watch-state-1", str(old_media / "incoming" / "next.mp4")),
        )
        connection.commit()

    state = tmp_path / "old" / "station-state.json"
    state.write_text(
        json.dumps(
            {
                "station": {
                    "storage_locations": {
                        "media_library": str(old_media),
                        "recordings": str(old_media / "recordings"),
                        "backups": str(tmp_path / "old" / "backups"),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
        config_paths=[state],
        media_roots=[old_media],
    )
    artifact = service.create_backup("replacement passphrase")

    target_db = tmp_path / "replacement" / "civiccast.sqlite3"
    target_state = tmp_path / "replacement" / "config" / "station-state.json"
    target_media = tmp_path / "replacement" / "media"
    service.restore_backup(
        artifact.path,
        "replacement passphrase",
        target_database_url=f"sqlite:///{target_db.as_posix()}",
        target_paths={str(state): target_state, str(old_media): target_media},
        writers_stopped=True,
    )

    with closing(sqlite3.connect(target_db)) as connection:
        asset_paths = connection.execute(
            "SELECT file_path, thumbnail_path FROM assets WHERE asset_id = 'meeting-1'"
        ).fetchone()
        partial_asset_paths = connection.execute(
            "SELECT file_path, thumbnail_path FROM assets WHERE asset_id = 'meeting-2'"
        ).fetchone()
        watch_root = connection.execute(
            "SELECT monitor_path FROM watch_folder_configs WHERE config_id = 'watch-1'"
        ).fetchone()
        watch_file = connection.execute(
            "SELECT file_path FROM watch_folder_file_state WHERE state_id = 'watch-state-1'"
        ).fetchone()
    assert asset_paths == (
        str(target_media / "meeting.mp4"),
        str(target_media / "thumbnails" / "meeting.jpg"),
    )
    assert partial_asset_paths == (str(target_media / "other.mp4"), str(tmp_path / "external.jpg"))
    assert watch_root == (str(target_media / "incoming"),)
    assert watch_file == (str(target_media / "incoming" / "next.mp4"),)
    restored_state = json.loads(target_state.read_text(encoding="utf-8"))
    assert restored_state["station"]["storage_locations"] == {
        "media_library": str(target_media),
        "recordings": str(target_media / "recordings"),
        "backups": str(tmp_path / "old" / "backups"),
    }
    assert (target_media / "meeting.mp4").read_bytes() == b"meeting"


def test_restore_requires_explicit_offline_writers_gate(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY)")
        connection.commit()
    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
    )
    artifact = service.create_backup("recovery passphrase")
    with pytest.raises(RuntimeError, match=r"writers.*stopped|offline"):
        service.restore_backup(
            artifact.path,
            "recovery passphrase",
            target_database_url=f"sqlite:///{(tmp_path / 'target.sqlite3').as_posix()}",
            writers_stopped=False,
        )


@pytest.mark.parametrize(
    "relative_path",
    [r"..\..\outside.mp4", r"C:\outside.mp4", "C:outside.mp4", "nested\\clip.mp4"],
)
def test_restore_rejects_windows_media_path_syntax(tmp_path: Path, relative_path: str) -> None:
    source = tmp_path / "media"
    with pytest.raises(ValueError, match="unsafe relative path"):
        station_backup_module._validate_payload_targets(
            [{"kind": "media", "source_path": str(source), "relative_path": relative_path}],
            {str(source): tmp_path / "restored"},
        )


def test_restore_requires_absolute_targets_for_configuration_files(tmp_path: Path) -> None:
    config = tmp_path / "station.json"
    with pytest.raises(ValueError, match="target paths must be absolute"):
        station_backup_module._validate_payload_targets(
            [{"kind": "config", "source_path": str(config)}],
            {str(config): Path("relative-config.json")},
        )


def test_restore_validates_portable_credentials_before_database_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "decrypted-bundle"
    bundle.mkdir()
    credential_file = bundle / "portable-credentials.json"
    credential_file.write_text(
        json.dumps({"smtp-password": {"encoding": "base64", "value": "not@@@base64"}}),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "members": [
            {
                "member": credential_file.name,
                "sha256": hashlib.sha256(credential_file.read_bytes()).hexdigest(),
            }
        ],
        "payload": [],
        "credential_export_member": credential_file.name,
    }
    (bundle / "station-backup.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(station_backup_module, "_decrypt_and_extract", lambda *_args: bundle)
    restored_database = []
    imported_credentials = []
    monkeypatch.setattr(
        station_backup_module, "_restore_sqlite", lambda *args: restored_database.append(args)
    )
    service = StationBackupService(
        database_url=f"sqlite:///{(tmp_path / 'unused.sqlite3').as_posix()}",
        destination=tmp_path / "backups",
        credential_importer=imported_credentials.append,
    )

    with pytest.raises(ValueError, match="invalid base64"):
        service.restore_backup(
            tmp_path / "fixture.ccbackup",
            "recovery passphrase",
            target_database_url=f"sqlite:///{(tmp_path / 'target.sqlite3').as_posix()}",
            writers_stopped=True,
        )

    assert restored_database == []
    assert imported_credentials == []


def test_schedule_has_bounded_retention_and_prunes_only_after_success(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY)")
        connection.commit()
    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
        scheduled_passphrase_available=lambda: True,
    )
    with pytest.raises(ValueError, match="retention"):
        BackupSchedule(enabled=True, destination=str(tmp_path / "backups"), retention_count=101)
    service.set_schedule(
        BackupSchedule(
            enabled=True,
            destination=str(tmp_path / "backups"),
            hour_utc=3,
            minute_utc=15,
            retention_count=1,
        )
    )
    service.create_backup("recovery passphrase")
    service.create_backup("recovery passphrase")
    assert len(service.list_backups()) == 1


def test_failed_destination_setup_releases_backup_job_lock(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY)")
        connection.commit()
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("fixture", encoding="utf-8")
    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=blocked / "backups",
        state_path=tmp_path / "backup-state.json",
    )

    with pytest.raises(OSError):
        service.create_backup("recovery passphrase")

    service.destination = tmp_path / "backups"
    assert service.create_backup("recovery passphrase").path.is_file()


def test_unattended_passphrase_is_delegated_and_media_roots_persist(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_db)) as connection:
        connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY)")
        connection.commit()
    media = tmp_path / "selected-media"
    media.mkdir()
    secret_slot: dict[str, str] = {}
    state_path = tmp_path / "service-state.json"
    service = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "backups",
        state_path=state_path,
        scheduled_passphrase_setter=lambda value: secret_slot.__setitem__("value", value),
        scheduled_passphrase_provider=lambda: secret_slot["value"],
        scheduled_passphrase_available=lambda: "value" in secret_slot,
    )
    service.set_scheduled_passphrase("scheduled recovery passphrase")
    service.set_schedule(
        BackupSchedule(
            enabled=True,
            destination=str(tmp_path / "backups"),
            hour_utc=3,
            minute_utc=0,
            retention_count=14,
            selected_media_roots=[str(media)],
        )
    )
    assert service.status()["scheduled_passphrase_configured"] is True
    assert "scheduled recovery passphrase" not in state_path.read_text(encoding="utf-8")

    reloaded = StationBackupService(
        database_url=f"sqlite:///{source_db.as_posix()}",
        destination=tmp_path / "initial-destination",
        state_path=state_path,
    )
    assert reloaded.media_roots == (media,)
    assert reloaded.destination == tmp_path / "backups"


def test_postgres_restore_replaces_provisioned_objects_transactionally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "database.pgdump"
    artifact.write_bytes(b"custom dump fixture")
    captured: list[list[str]] = []

    def fake_spawn(argv: list[str], **kwargs: object) -> SimpleNamespace:
        captured.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(backup_module, "_spawn_pg_tool", fake_spawn)
    _restore_postgres(
        artifact,
        "postgresql://restore-user@localhost:5432/civiccast",
        ["pg_restore"],
    )
    assert "--clean" in captured[0]
    assert "--if-exists" in captured[0]
    assert "--single-transaction" in captured[0]
    assert "--no-owner" in captured[0]
