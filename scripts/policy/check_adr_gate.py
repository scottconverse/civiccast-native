#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: ADR files under ``docs/adr/`` are append-only.

ADRs are immutable once Accepted (CLAUDE.md, ``docs/adr/0000-template.md``).
An autonomous run may ADD a new ADR file but must NOT modify any existing
one — those edits require a human approval gate per the layered audit
pattern's overflow rule.

This check inspects the working-tree diff against HEAD:
  * NEW files under ``docs/adr/`` are allowed.
  * MODIFIED or DELETED files under ``docs/adr/`` block the run.

The check is deliberately strict. If a typo or metadata correction is
genuinely needed, the operator runs the change manually outside the
pipeline; the policy gate does not silently approve it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_PREFIX = "docs/adr/"


def _diff_with_status() -> list[tuple[str, str]]:
    """Return [(status_letter, path), ...] for working-tree changes vs HEAD.

    Status letters from ``git diff --name-status``:
      A = added, C = copied, D = deleted, M = modified, R = renamed,
      T = type change, U = unmerged, X = unknown, B = pairing broken.
    """
    result = subprocess.run(
        ["git", "diff", "--name-status", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    pairs: list[tuple[str, str]] = []
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        # Renames look like `R100\told\tnew` — the new path is the relevant one.
        path = parts[-1].strip()
        pairs.append((status, path))
    return pairs


def main() -> int:
    pairs = _diff_with_status()
    blockers: list[tuple[str, str]] = []
    new_adrs: list[str] = []

    for status, path in pairs:
        if not path.startswith(ADR_PREFIX):
            continue
        # Pure additions (A) are fine. Anything else under docs/adr/ blocks.
        if status.startswith("A"):
            new_adrs.append(path)
        else:
            blockers.append((status, path))

    if blockers:
        print("check_adr_gate: FAIL")
        print("  ADR files are immutable once Accepted (CLAUDE.md, docs/adr/0000-template.md).")
        print(
            "  An autonomous run may add a new ADR but must not modify, rename, or delete an existing one."
        )
        print("  Modifications detected:")
        for status, path in blockers:
            print(f"    [{status}] {path}")
        return 1

    if new_adrs:
        print(f"check_adr_gate: PASS — {len(new_adrs)} new ADR(s), no modifications:")
        for path in new_adrs:
            print(f"    [+] {path}")
        return 0

    print("check_adr_gate: PASS — no ADR changes in working tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
