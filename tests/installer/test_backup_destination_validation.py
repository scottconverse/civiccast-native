# SPDX-License-Identifier: Apache-2.0
"""A WSL-style backup destination must never show as verified.

Field evidence (candidate #17): a station's Backup destination showed READY
for C:\\mnt\\c\\CivicCastBackups -- a WSL/Linux mounted-drive path that does
not exist on this native-Windows product. Nothing in this codebase sets that
as a default (see the comment on _WSL_STYLE_PATH_RE in
civiccast/installer/service.py); this test proves the rejection, not the
origin of that particular test box's leftover value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.installer.models import BackupSetupRequest
from civiccast.installer.service import configure_backup


@pytest.mark.parametrize(
    "wsl_path",
    [
        r"C:\mnt\c\CivicCastBackups",
        r"\mnt\c\CivicCastBackups",
        "/mnt/c/CivicCastBackups",
        "c:/mnt/c/CivicCastBackups",
    ],
)
def test_wsl_style_backup_destination_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wsl_path: str
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))

    status = configure_backup(BackupSetupRequest(destination=wsl_path))

    assert status.status == "needs_attention"
    assert "WSL" in status.message
    assert "C:\\CivicCastBackups" in status.message


def test_real_windows_backup_destination_is_still_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    backup_dir = tmp_path / "CivicCastBackups"

    status = configure_backup(BackupSetupRequest(destination=str(backup_dir)))

    assert status.status == "ready"
