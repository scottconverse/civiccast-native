#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: v1.4 proof claims require committed evidence or a waiver."""

from __future__ import annotations

import re
import sys
from pathlib import Path

VERIFICATION_PATH = Path("docs/releases/v1.4-verification.md")
PROVIDER_EVIDENCE_PATH = Path("docs/releases/evidence/v1.4-controlled-provider-proof.md")
NONTECH_WALKTHROUGH_PATH = Path("docs/releases/evidence/v1.4-nontechnical-operator-walkthrough.md")
TECH_WALKTHROUGH_PATH = Path("docs/releases/evidence/v1.4-technical-admin-walkthrough.md")
WAIVER_PATH = Path("docs/releases/evidence/v1.4-release-owner-waiver.md")

PROMOTION_PATTERN = re.compile(
    r"\b(?:passed|promoted|ready|release-ready|tagged|complete|complete for release)\b",
    re.IGNORECASE,
)
BLOCKED_PATTERN = re.compile(r"\b(?:blocked|not promotable|not release-ready)\b", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\b(?:todo|tbd|template|fill in|pending)\b", re.IGNORECASE)


def _read(root: Path, relative: Path) -> str:
    return (root / relative).read_text(encoding="utf-8", errors="ignore")


def _looks_promoted(text: str) -> bool:
    status_lines = [
        line.strip()
        for line in text.splitlines()
        if "release status" in line.lower() or "status:" in line.lower()
    ]
    haystack = "\n".join(status_lines) if status_lines else text[:1200]
    return bool(PROMOTION_PATTERN.search(haystack)) and not bool(BLOCKED_PATTERN.search(haystack))


def _evidence_ready(root: Path, relative: Path) -> bool:
    path = root / relative
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return bool(text.strip()) and not bool(PLACEHOLDER_PATTERN.search(text))


def evaluate_v14_release_evidence(root: Path) -> list[str]:
    """Return violations for v1.4 release-proof overclaims."""
    root = root.resolve()
    verification = root / VERIFICATION_PATH
    if not verification.exists():
        return []

    text = _read(root, VERIFICATION_PATH)
    if not _looks_promoted(text):
        return []

    waiver_ready = _evidence_ready(root, WAIVER_PATH)
    required = [
        ("controlled live-provider proof", PROVIDER_EVIDENCE_PATH),
        ("non-technical observed walkthrough", NONTECH_WALKTHROUGH_PATH),
        ("technical-admin observed walkthrough", TECH_WALKTHROUGH_PATH),
    ]
    violations: list[str] = []
    for label, relative in required:
        if not _evidence_ready(root, relative) and not waiver_ready:
            violations.append(
                f"{VERIFICATION_PATH.as_posix()}: v1.4 is claimed as promoted, but "
                f"{label} evidence is missing or still a template at {relative.as_posix()}."
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else Path.cwd()
    violations = evaluate_v14_release_evidence(root)
    if violations:
        print("V1.4 RELEASE EVIDENCE: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("V1.4 RELEASE EVIDENCE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
