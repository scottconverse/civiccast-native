# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from civiccast.installer.models import BackupSetupRequest
from civiccast.installer.service import (
    build_restore_status,
    configure_backup,
    run_restore_rehearsal,
)


def test_backup_manifest_round_trip_does_not_claim_station_data_was_restored(
    monkeypatch,
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))

    configured = configure_backup(BackupSetupRequest(destination=str(backup_dir)))
    assert configured.status == "ready"

    report = run_restore_rehearsal()

    assert report.status == "needs_attention"
    assert report.proof_summary is not None
    assert "did not restore" in report.proof_summary.lower()
    assert {item.state for item in report.proof_items} == {"pending"}
    assert build_restore_status().status == "not_tested"
    assert not list(backup_dir.glob(".civiccast-restore-*"))
