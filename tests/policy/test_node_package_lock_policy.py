# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Node package roots must be lockfile-backed for release auditability."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_node_package_roots_have_lockfiles() -> None:
    package_roots = sorted(
        path.parent
        for path in ROOT.glob("civiccast/**/package.json")
        if "node_modules" not in path.parts
    )

    missing = []
    for package_root in package_roots:
        package_json = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
        if package_json.get("private") is not True:
            continue
        if not (package_root / "package-lock.json").is_file():
            missing.append(package_root.relative_to(ROOT).as_posix())

    assert missing == []
