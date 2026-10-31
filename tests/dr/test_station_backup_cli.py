# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Destructive restore must resolve and confirm destinations before any side effect."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from civiccast.dr import station_backup_cli as cli
from civiccast.dr import station_backup_runtime as runtime


def test_create_failure_prints_safe_action_without_exception_traceback(monkeypatch):
    from civiccast.dr.station_backup import BackupCreationError

    def fail(_phrase):
        raise BackupCreationError("Backup example failed during database. Check database access.")

    monkeypatch.setattr(cli, "_service", lambda: SimpleNamespace(create_backup=fail))
    result = CliRunner().invoke(
        cli.backup_app, ["create"], input="test-recovery-passphrase\ntest-recovery-passphrase\n"
    )
    assert result.exit_code != 0
    assert "failed during database" in result.output
    assert "test-recovery-passphrase" not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "command", [["create"], ["verify", "backup.ccbackup"], ["inventory", "backup.ccbackup"]]
)
def test_privilege_preflight_precedes_runtime_loading_and_passphrase(monkeypatch, command):
    events = []

    def denied():
        events.append("preflight")
        raise PermissionError("Use Run as administrator; no backup work has started.")

    monkeypatch.setattr(runtime, "preflight_station_backup_cli", denied)
    monkeypatch.setattr(runtime, "build_station_backup_service", lambda: events.append("runtime"))
    result = CliRunner().invoke(cli.backup_app, command)
    assert result.exit_code != 0
    assert "Run as administrator" in result.output
    assert "Recovery passphrase" not in result.output
    assert events == ["preflight"]


@pytest.fixture
def restore_cli(tmp_path, monkeypatch):
    events = []
    mapping = tmp_path / "paths.json"
    mapping.write_text(json.dumps({str(tmp_path / "old"): str(tmp_path / "replacement")}))
    monkeypatch.delenv("CIVICCAST_TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICAST_TARGET_DATABASE_URL", raising=False)

    def restore(*_args, **kwargs):
        events.append(kwargs)
        return SimpleNamespace(backup_id="example", database_engine="postgres", files_restored=1)

    service = SimpleNamespace(
        database_url="postgresql://installed/installed",
        credential_destination="this machine's station vault and settings",
        restore_backup=restore,
    )
    monkeypatch.setattr(cli, "_service", lambda: service)

    @contextmanager
    def offline(**kwargs):
        events.append("offline")
        yield

    monkeypatch.setattr(runtime, "offline_station_restore", offline)
    args = [
        "restore",
        "archive.ccbackup",
        "--target-paths-json",
        str(mapping),
        "--confirmation",
        "RESTORE",
    ]
    return args, events


def test_missing_target_never_defaults_to_installed_database(restore_cli):
    args, events = restore_cli
    result = CliRunner().invoke(cli.backup_app, args)
    assert result.exit_code != 0
    assert "never defaults" in result.output
    assert events == []


@pytest.mark.parametrize("name", ["CIVICCAST_TARGET_DATABASE_URL", "CIVICAST_TARGET_DATABASE_URL"])
def test_restore_accepts_documented_and_legacy_environment(restore_cli, monkeypatch, name):
    args, events = restore_cli
    monkeypatch.setenv(
        name, "postgresql://operator:private-password@replacement/station?token=private-query"
    )
    result = CliRunner().invoke(
        cli.backup_app,
        [*args, "--restore-local-station-settings"],
        input="y\nrecovery-test-passphrase\n",
    )
    assert result.exit_code == 0, result.output
    assert events[0] == "offline"
    assert events[1]["target_database_url"].startswith("postgresql://operator:")
    assert events[1]["restore_local_station_settings"] is True
    assert "host=replacement" in result.output
    assert "private-password" not in result.output
    assert "private-query" not in result.output


def test_conflicting_environment_refuses_before_mutation(restore_cli, monkeypatch):
    args, events = restore_cli
    monkeypatch.setenv("CIVICCAST_TARGET_DATABASE_URL", "postgresql://a/station")
    monkeypatch.setenv("CIVICAST_TARGET_DATABASE_URL", "postgresql://b/station")
    result = CliRunner().invoke(cli.backup_app, args)
    assert result.exit_code != 0
    assert "Conflicting" in result.output
    assert events == []


def test_database_mapping_does_not_imply_isolated_settings_restore(restore_cli):
    args, events = restore_cli
    result = CliRunner().invoke(
        cli.backup_app, [*args, "--target-database-url", "postgresql://clone/station"]
    )
    assert result.exit_code != 0
    assert "isolated" in result.output and "clone" in result.output
    assert "this machine's station vault" in result.output
    assert events == []


def test_declining_resolved_destination_does_not_enter_offline_mode(restore_cli):
    args, events = restore_cli
    result = CliRunner().invoke(
        cli.backup_app,
        [
            *args,
            "--target-database-url",
            "postgresql://replacement/station",
            "--restore-local-station-settings",
        ],
        input="n\n",
    )
    assert result.exit_code != 0
    assert "host=replacement" in result.output
    assert events == []
