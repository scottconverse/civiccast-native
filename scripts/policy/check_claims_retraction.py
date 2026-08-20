#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Block current-facing signed-record capability overclaims."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "valid/signed PDF/A-3B record",
        re.compile(
            r"\b(?:valid\s+pdf/a-3b\s+signed\s+record|signed\s+pdf/a-3b\s+record|pdf/a-3b\s+signed\s+record)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "valid PDF/A-3B document",
        re.compile(r"\bvalid\s+pdf/a-3b\s+document\b", re.IGNORECASE),
    ),
    (
        "legal signed record",
        re.compile(
            r"\b(?:legally\s+defensible\s+signed\s+record|legally\s+defensible\s+pdf/a|legal\s+signed\s+record)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "RFC 3161-style timestamp proof",
        re.compile(r"\brfc\s*3161-style\s+timestamp\s+proof\b", re.IGNORECASE),
    ),
    (
        "PDF/A-3B conformance",
        re.compile(r"\bpdf/a-3b\s+conformance\b", re.IGNORECASE),
    ),
    (
        "fixture artifact conformance",
        re.compile(
            r"\b(?:fixture|artifact|pdf/a|pdf|export|record)[^.:\n]{0,80}\bconformance\b|\bconformance\b[^.:\n]{0,80}\b(?:fixture|artifact|pdf/a|pdf|export|record)\b",
            re.IGNORECASE,
        ),
    ),
)

QUALIFIERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdeterministic\s+contract\s+fixture\b", re.IGNORECASE),
    re.compile(r"\bnot\s+a\s+valid\s+pdf/a-3b\s+document\s+in\s+v1\.0\.0\b", re.IGNORECASE),
    re.compile(
        r"\bnot\s+a\s+real\s+timestamped\s+pdf/a-3b\s+artifact\s+in\s+v1\.0\.0\b", re.IGNORECASE
    ),
    re.compile(
        r"\bnot\s+a\s+legally\s+defensible\s+signed\s+record\s+in\s+v1\.0\.0\b", re.IGNORECASE
    ),
)

CURRENT_FACING_EXACT = {
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("docs/USER-MANUAL.md"),
    Path("docs/API-REFERENCE.md"),
    Path("docs/index.html"),
    Path("civiccast/app.py"),
    Path("civiccast/records/README.md"),
    Path("civiccast/records/CHANGELOG.md"),
    Path("civiccast/apps/portal-operator/README.md"),
}

CURRENT_FACING_DIRS = (
    Path("docs/ops"),
    Path("docs/releases"),
    Path("docs/process"),
    Path("civiccast/apps/portal-operator/src"),
)

TEXT_SUFFIXES = {".md", ".html", ".py", ".tsx", ".ts", ".txt"}


def _relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _is_scanned_path(path: Path, root: Path) -> bool:
    rel = _relative(path, root)
    if path.suffix not in TEXT_SUFFIXES:
        return False
    if any(part in {".git", ".venv", "node_modules", "dist", "test-results"} for part in rel.parts):
        return False
    if rel.parts and rel.parts[0] == "tests":
        return False
    if rel in CURRENT_FACING_EXACT:
        return True
    return any(rel == directory or directory in rel.parents for directory in CURRENT_FACING_DIRS)


def _context_for(text: str, start: int, end: int) -> str:
    paragraph_start = text.rfind("\n\n", 0, start)
    paragraph_end = text.find("\n\n", end)
    if paragraph_start == -1:
        paragraph_start = max(0, start - 240)
    if paragraph_end == -1:
        paragraph_end = min(len(text), end + 240)
    window_start = max(0, start - 600)
    window_end = min(len(text), end + 600)
    return text[paragraph_start:paragraph_end] + "\n" + text[window_start:window_end]


def _is_qualified(context: str) -> bool:
    return any(pattern.search(context) for pattern in QUALIFIERS)


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _scan_claims(path: Path, root: Path) -> list[str]:
    rel = _relative(path, root).as_posix()
    text = path.read_text(encoding="utf-8", errors="ignore")
    violations: list[str] = []

    for label, pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            context = _context_for(text, match.start(), match.end())
            if _is_qualified(context):
                continue
            line = _line_number(text, match.start())
            excerpt = " ".join(match.group(0).split())
            violations.append(f"{rel}:{line}: unqualified {label}: {excerpt}")

    rel_path = Path(rel)
    stale_auth_scope = rel_path in {
        Path("README.md"),
        Path("civiccast/app.py"),
        Path("docs/ops/staff-route-protection.md"),
    }
    if stale_auth_scope and "through v0.10" in text.lower():
        for match in re.finditer(r"through\s+v0\.10", text, re.IGNORECASE):
            line = _line_number(text, match.start())
            violations.append(f"{rel}:{line}: stale runtime/auth wording: {match.group(0)}")

    return violations


def evaluate_claims_retraction(root: Path) -> list[str]:
    """Return policy violations for unqualified current-facing claims."""
    root = root.resolve()
    violations: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _is_scanned_path(path, root):
            violations.extend(_scan_claims(path, root))
    return violations


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else Path.cwd()
    violations = evaluate_claims_retraction(root)
    if violations:
        print("CLAIMS RETRACTION: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("CLAIMS RETRACTION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
