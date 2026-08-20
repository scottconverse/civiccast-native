# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Alembic ini drift guard (audit ENG-010).

Two copies of alembic.ini exist - the repo root (source-tree runs) and the
packaged copy under civiccast/alembic/ (wheel fallback). The packaged copy
silently fell three module directories behind. Pin: (1) both inis declare
the same version_locations, (2) the list covers every on-disk
*/migrations/versions directory.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _version_locations(ini_path: Path) -> set[str]:
    text = ini_path.read_text(encoding="utf-8")
    match = re.search(r"version_locations\s*=\s*\n((?:\s+\S+\n)+)", text)
    assert match is not None, f"{ini_path} has no version_locations block"
    return {
        line.strip().replace("%(here)s/", "")
        for line in match.group(1).splitlines()
        if line.strip()
    }


def test_packaged_ini_matches_the_root_ini() -> None:
    root = _version_locations(REPO_ROOT / "alembic.ini")
    packaged = _version_locations(REPO_ROOT / "civiccast" / "alembic" / "alembic.ini")
    assert root == packaged, (
        f"alembic.ini copies drifted: only-root={sorted(root - packaged)}, "
        f"only-packaged={sorted(packaged - root)}. Sync the packaged copy "
        "from the root (audit ENG-010)."
    )


def test_ini_covers_every_module_migrations_directory() -> None:
    declared = _version_locations(REPO_ROOT / "alembic.ini")
    on_disk = {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in (REPO_ROOT / "civiccast").glob("*/migrations/versions")
        if path.is_dir()
    }
    missing = on_disk - declared
    assert not missing, (
        f"Module migration directories not registered in alembic.ini: "
        f"{sorted(missing)} - their migrations would be invisible to "
        "'alembic upgrade head'."
    )
