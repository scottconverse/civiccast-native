#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: source files under ``civiccast/`` must not contain TODO/FIXME/HACK markers.

CLAUDE.md treats unfinished work-in-progress markers as a Blocker for
release tagging — they accumulate across rungs and the "later" usually
doesn't happen. Audit findings get queued in ``next-cleanup.md`` instead.

This check enforces the rule for ``civiccast/`` source only. ``tests/``
and ``docs/`` are explicitly excluded — tests legitimately mark expected
TODO regression cases (xfail rationale strings) and docs reference the
markers descriptively.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO_ROOT / "civiccast"
PATTERN = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)


def main() -> int:
    if not SCAN_ROOT.exists():
        print(f"check_no_todos: scan root {SCAN_ROOT} does not exist. PASS (vacuous).")
        return 0

    violations: list[tuple[Path, int, str]] = []
    for py_file in SCAN_ROOT.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_num, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                violations.append((py_file.relative_to(REPO_ROOT), line_num, line.rstrip()))

    if violations:
        print("check_no_todos: FAIL")
        print(
            "  TODO/FIXME/HACK markers in civiccast/ source are blockers per CLAUDE.md "
            "(unfinished work goes in next-cleanup.md, not the source tree)."
        )
        print("  Violations:")
        for path, line_num, line_text in violations:
            print(f"    {path.as_posix()}:{line_num}  {line_text}")
        return 1

    print("check_no_todos: PASS — no TODO/FIXME/HACK markers in civiccast/ source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
