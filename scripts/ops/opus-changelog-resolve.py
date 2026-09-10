# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Resolve a ``CHANGELOG.md`` merge conflict: main's entries first, then the branch's.

Every PR on this repository adds entries under the same ``## [Unreleased]`` heading, so every
merge of ``origin/main`` into a branch conflicts there, and each merge to main invalidates the
next PR. The house resolution is always the same: main's entries first in main's order, then the
branch's, no duplicate headings, zero conflict markers.

Run it from the worktree root while a merge is in progress::

    python scripts/ops/opus-changelog-resolve.py

It touches nothing but ``CHANGELOG.md``, and it prints every bullet it keeps from each side so the
result is auditable rather than trusted. Exits non-zero if any conflict marker survives, or if
there was no conflict to resolve.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHANGELOG = Path("CHANGELOG.md")
BULLET = "- **"


def _trim_trailing_blanks(block: list[str]) -> list[str]:
    """Return ``block`` without its trailing blank lines."""
    trimmed = list(block)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _report(label: str, block: list[str]) -> None:
    for line in block:
        if line.startswith(BULLET):
            print(f"   {label}: {line[:80]}")


def resolve(lines: list[str]) -> tuple[list[str], int]:
    """Merge every conflict region in ``lines``, main's side first.

    Returns the resolved lines and the number of regions merged.
    """
    regions = 0
    while True:
        start = next(
            (i for i, line in enumerate(lines) if line.startswith("<<<<<<< HEAD")),
            None,
        )
        if start is None:
            break
        middle = next(i for i, line in enumerate(lines) if line.startswith("=======") and i > start)
        end = next(i for i, line in enumerate(lines) if line.startswith(">>>>>>>") and i > middle)

        ours = _trim_trailing_blanks(lines[start + 1 : middle])
        theirs = _trim_trailing_blanks(lines[middle + 1 : end])

        print(
            f"region {regions}: "
            f"main={sum(1 for line in theirs if line.startswith(BULLET))} bullets, "
            f"branch={sum(1 for line in ours if line.startswith(BULLET))} bullets"
        )
        _report("main  ", theirs)
        _report("branch", ours)

        merged = theirs + ([""] if theirs and ours else []) + ours
        lines = lines[:start] + merged + lines[end + 1 :]
        regions += 1
    return lines, regions


def main() -> int:
    lines = CHANGELOG.read_text(encoding="utf-8").split("\n")
    lines, regions = resolve(lines)
    if regions == 0:
        print(f"no conflict regions in {CHANGELOG}")
        return 1

    CHANGELOG.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    leftover = sum(1 for line in lines if line.startswith(("<<<<<<<", "=======", ">>>>>>>")))
    print(f"resolved {regions} region(s); markers left: {leftover}")
    return 1 if leftover else 0


if __name__ == "__main__":
    sys.exit(main())
