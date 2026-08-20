#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scan operator TSX copy for API jargon.

The sweep checks `/api/`, `DATABASE_URL`, `console.log`, and `localhost`.
Exceptions live in docs/releases/evidence/v1.1-known-minor-risks.md.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)
OPERATOR_SRC = REPO_ROOT / "civiccast" / "apps" / "portal-operator" / "src"
ALLOWLIST = REPO_ROOT / "docs" / "releases" / "evidence" / "v1.1-known-minor-risks.md"
JARGON_TERMS = ("/api/", "DATABASE_URL", "console.log", "localhost")
STRING_RE = re.compile(r"(['\"])(?P<value>(?:\\.|(?!\1).)*?)\1")


def _allowlist_text() -> str:
    return ALLOWLIST.read_text(encoding="utf-8") if ALLOWLIST.exists() else ""


def _line_offsets(text: str) -> list[tuple[int, int, str]]:
    offsets: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        offsets.append((offset, offset + len(line), line))
        offset += len(line)
    return offsets


def _import_line_numbers(text: str) -> set[int]:
    lines = text.splitlines()
    skipped: set[int] = set()
    in_import = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_import and (
            stripped.startswith("import ")
            or stripped.startswith("export ")
            or stripped.startswith("export type ")
        ):
            in_import = True
        if in_import:
            skipped.add(index)
            if " from " in line or stripped.endswith(";") or STRING_RE.search(line):
                in_import = False
    return skipped


def _line_number_for_offset(offsets: list[tuple[int, int, str]], offset: int) -> int:
    for index, (start, end, _line) in enumerate(offsets, start=1):
        if start <= offset < end:
            return index
    return len(offsets)


def _string_literals(text: str) -> list[str]:
    values: list[str] = []
    offsets = _line_offsets(text)
    import_lines = _import_line_numbers(text)
    for match in STRING_RE.finditer(text):
        if _line_number_for_offset(offsets, match.start()) in import_lines:
            continue
        raw = match.group(0)
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            parsed = match.group("value")
        if isinstance(parsed, str):
            values.append(parsed)
    return values


def check_operator_copy(root: Path = REPO_ROOT) -> list[str]:
    src = root / OPERATOR_SRC.relative_to(REPO_ROOT)
    allowlist = _allowlist_text()
    violations: list[str] = []
    if not src.exists():
        return violations
    for path in sorted(src.rglob("*.tsx")):
        if path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8")
        for literal in _string_literals(text):
            for jargon in JARGON_TERMS:
                if jargon not in literal:
                    continue
                rel = path.relative_to(root).as_posix()
                if rel in allowlist and jargon in allowlist:
                    continue
                violations.append(f"{rel}: operator string contains `{jargon}`")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    violations = check_operator_copy()
    if violations:
        print("check_operator_copy: FAIL")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("check_operator_copy: PASS - operator copy avoids API jargon or documents risks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
