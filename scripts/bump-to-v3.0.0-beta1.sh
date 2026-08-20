#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python - "$ROOT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])

replacements = {
    "civiccast/_version.py": ('__version__ = "2.1.0"', '__version__ = "3.0.0-beta1"'),
    "civiccast/apps/installer/package.json": ('"version": "2.1.0"', '"version": "3.0.0-beta1"'),
    "civiccast/apps/installer/src-tauri/tauri.conf.json": ('"version": "2.1.0"', '"version": "3.0.0-beta1"'),
    "civiccast/apps/installer/src-tauri/Cargo.toml": ('version = "2.1.0"', 'version = "3.0.0-beta.1"'),
}

for relpath, (old, new) in replacements.items():
    path = root / relpath
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{relpath}: expected {old!r} before beta bump")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Keep package.json formatting stable after the textual version bump.
package_path = root / "civiccast/apps/installer/package.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
PY

echo "CivicCast version files bumped to v3.0.0-beta1."
