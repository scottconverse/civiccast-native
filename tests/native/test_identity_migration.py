# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from civiccast.native.identity_migration import preserve_profile


def test_profile_copy_preserves_original_and_supports_identical_retry(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    (source / "station-state.json").write_text('{"admin":"preserved"}')
    destination = tmp_path / "new" / "CivicCast"
    preserve_profile(source, destination)
    preserve_profile(source, destination)
    assert (destination / "station-state.json").read_bytes() == (
        source / "station-state.json"
    ).read_bytes()


def test_existing_changed_destination_is_never_overwritten(tmp_path):
    source, destination = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    destination.mkdir()
    (source / "state").write_text("old")
    (destination / "state").write_text("new")
    with pytest.raises(RuntimeError, match="differ"):
        preserve_profile(source, destination)
    assert (destination / "state").read_text() == "new"


def test_redirected_destination_parent_is_refused_before_copy(tmp_path, monkeypatch):
    source = tmp_path / "old"
    source.mkdir()
    (source / "state").write_text("preserve")
    redirected = tmp_path / "redirected"
    destination = redirected / "CivicCast"
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == redirected or original(path))
    with pytest.raises(RuntimeError, match="redirected destination"):
        preserve_profile(source, destination)
    assert not redirected.exists()


def test_copy_failure_does_not_promote_or_remove_source(tmp_path, monkeypatch):
    source = tmp_path / "old"
    source.mkdir()
    (source / "state").write_text("preserve")
    destination = tmp_path / "new"
    original = Path.open

    def fail_copy(path, *args, **kwargs):
        if ".profile-migration-" in str(path) and args and args[0] == "rb":
            raise OSError("simulated verification read failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_copy)
    with pytest.raises(OSError):
        preserve_profile(source, destination)
    assert not destination.exists()
    assert (source / "state").read_text() == "preserve"


@pytest.mark.windows_only
def test_migration_only_start_never_launches_station(monkeypatch):
    import os

    if os.name != "nt":
        pytest.skip("Windows service entrypoint")
    from civiccast.native import identity_migration
    from civiccast.native.supervisor import service_host

    calls = []
    monkeypatch.setenv(identity_migration.MIGRATION_ENV, "1")
    monkeypatch.setattr(identity_migration, "migrate_old_account", lambda: calls.append("migrate"))
    monkeypatch.setattr(
        service_host, "ensure_database_url_env", lambda: pytest.fail("station startup")
    )
    service = object.__new__(service_host.CivicCastSupervisorService)
    service._stop_watchdog = None
    service.SvcDoRun()
    assert calls == ["migrate"]
