#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Reject current-facing beta handoff docs that still contain placeholder proof."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)

CURRENT_FACING_DOCS = (
    Path("USER-MANUAL.md"),
    Path("index.html"),
    Path("installer/beta-tester-handoff.md"),
    Path("installer/cross-platform-installer.md"),
    Path("ops/credential-matrix.md"),
    Path("ops/backup-restore.md"),
    Path("ops/troubleshooting.md"),
    Path("architecture.md"),
)

HISTORICAL_PARTS = {"releases", "evidence"}
BANNED_EXACT = ("TODO", "FIXME", "fake-success", "mock-proof")
BANNED_PLACEHOLDER_PHRASES = (
    "replace this placeholder",
    "placeholder with the real",
    "placeholder proof",
    "placeholder credentials until",
    "use fake",
    "stubbed after",
)
PLACEHOLDER_ALLOWANCE = (
    "not a placeholder",
    "no placeholder",
    "do not use placeholder",
    "do not synthesize placeholder",
    "placeholder credentials are rejected",
    "placeholder credentials were rejected",
    "placeholder hashes are not valid",
    "placeholder bytes",
    "historical",
    "retraction",
)


@dataclass(frozen=True)
class BetaHandoffDocsFinding:
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class BetaHandoffDocsResult:
    status: str
    findings: list[BetaHandoffDocsFinding]


def check_beta_handoff_docs(docs_root: Path = REPO_ROOT / "docs") -> BetaHandoffDocsResult:
    """Check current-facing beta handoff docs for placeholder/fake proof copy."""

    findings: list[BetaHandoffDocsFinding] = []
    for path in _candidate_paths(docs_root):
        if _historical_path(path, docs_root):
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for term in BANNED_EXACT:
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                    line,
                    re.IGNORECASE,
                ):
                    findings.append(
                        BetaHandoffDocsFinding(
                            path=_display_path(path, docs_root),
                            line=line_number,
                            message=f"current-facing docs contain `{term}`",
                        )
                    )
            if (
                "placeholder" in lowered
                and not any(allowed in lowered for allowed in PLACEHOLDER_ALLOWANCE)
                and any(phrase in lowered for phrase in BANNED_PLACEHOLDER_PHRASES)
            ):
                findings.append(
                    BetaHandoffDocsFinding(
                        path=_display_path(path, docs_root),
                        line=line_number,
                        message="current-facing docs contain placeholder proof language",
                    )
                )
    return BetaHandoffDocsResult(
        status="failed" if findings else "passed",
        findings=findings,
    )


def _candidate_paths(docs_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel in CURRENT_FACING_DOCS:
        path = docs_root / rel
        if path.exists():
            paths.append(path)
    beta_dir = docs_root / "installer"
    if beta_dir.exists():
        for path in sorted(beta_dir.glob("*handoff*.md")):
            if path not in paths:
                paths.append(path)
    return paths


def _historical_path(path: Path, docs_root: Path) -> bool:
    try:
        parts = set(path.relative_to(docs_root).parts)
    except ValueError:
        return False
    return parts >= HISTORICAL_PARTS


def _display_path(path: Path, docs_root: Path) -> str:
    try:
        return path.relative_to(docs_root).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", type=Path, default=REPO_ROOT / "docs")
    args = parser.parse_args(argv)
    result = check_beta_handoff_docs(args.docs_root)
    if result.findings:
        print("check_beta_handoff_docs: FAIL")
        for finding in result.findings:
            print(f"  - {finding.path}:{finding.line}: {finding.message}")
        return 1
    print("check_beta_handoff_docs: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
