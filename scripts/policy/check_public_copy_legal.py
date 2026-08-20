#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: release copy contains third-party vendor comparison references."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root


REPO_ROOT = find_repo_root(__file__)

VENDOR_ALLOWLIST = frozenset(
    {
        "LEGAL-NOTICES.md",
        "docs/legal/patent-watchlist.md",
        "docs/spec/3.0/sections/S18-cablecast-parity-gap-closure.md",
        "docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md",
        "scripts/policy/check_public_copy_legal.py",
        "tests/policy/test_public_copy_legal.py",
        # Generated API contracts carry the migrate endpoint's source_system enum
        # ("cablecast"/"telvue") -- a factual field name, not positioning copy.
        "docs/API-REFERENCE.md",
        "docs/openapi.json",
        "civiccast/apps/portal-operator/src/types/api.generated.ts",
        # The capabilities matrix describes the migrate-from-incumbent feature
        # with honest limits ("Cablecast only ..."); factual, no framing.
        "CAPABILITIES.md",
        # Internal release-verification and forward-planning docs that reference
        # the migrate-from-incumbent feature by name. Plain mentions only.
        "docs/releases/1.0.0-field-proof-runbook.md",
        "docs/releases/v1.0.0-rc1-verification.md",
        "docs/releases/v1.0.0-rc18-verification.md",
        "docs/spec/3.3-to-4.0-sprint-list-and-implementation-plan.md",
    }
)

# Whole directories where naming the incumbent vendors is factual and
# unavoidable, not positioning: the migration adapters (code + tests) that
# import FROM Cablecast/TelVue, and the competitive-research corpus (the same
# "research" carve-out the patent watchlist above already gets). The HIGH_RISK
# framing patterns below are what guard against a "replaces/beats Cablecast"
# claim; a factual source_system="cablecast" is not that.
VENDOR_ALLOWLIST_PREFIXES = (
    "civiccast/migrate/",
    "tests/migrate/",
    "docs/research/",
)

SKIPPED_SUFFIXES = (
    ".docx",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lock",
    ".pdf",
    ".png",
    ".webp",
    ".zip",
)

HIGH_RISK_PATTERNS = (
    r"\bCablecast\s+replacement\b",
    r"\bCablecast\s+parity\b",
    r"\bCablecast\s+parity\s+target\b",
    "\\bTightrope['\\u2019]s\\s+Cablecast\\b",
    r"\bCablecast-by-Cablecast\b",
    r"\breplaces\s+Cablecast\b",
    r"\breplacing\s+Cablecast\b",
    r"\bdrop-in\s+replacement\b",
    r"\bfull\s+parity\b",
    r"\bmirrors\s+Cablecast\b",
    r"\bmatches\s+Cablecast\b",
    r"\bexceeds\s+Cablecast\b",
    r"\bbeats\s+Cablecast\b",
)

VENDOR_PATTERN = re.compile(r"\b(?:Cablecast|Tightrope)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PublicCopyViolation:
    path: str
    line: int
    phrase: str
    text: str
    kind: str = "high-risk phrase"

    def render(self) -> str:
        return f"{self.path}:{self.line}: `{self.phrase}` {self.kind}: {self.text}"


def _tracked_paths(root: Path) -> list[Path] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return [root / line for line in proc.stdout.splitlines() if line]


def _is_probably_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return False
    except OSError:
        return False
    return True


def _iter_scanned_paths(root: Path) -> list[Path]:
    paths = _tracked_paths(root)
    if paths is None:
        paths = [path for path in root.rglob("*") if path.is_file()]
    scanned: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        parts = set(Path(relative).parts)
        if parts & {"node_modules", "dist", "build", ".git", ".venv", "__pycache__"}:
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        if not _is_probably_text(path):
            continue
        scanned.append(path)
    return scanned


def evaluate_public_copy_legal(root: Path = REPO_ROOT) -> list[PublicCopyViolation]:
    compiled = [(pattern, re.compile(pattern, re.IGNORECASE)) for pattern in HIGH_RISK_PATTERNS]
    violations: list[PublicCopyViolation] = []
    for path in _iter_scanned_paths(root):
        relative = path.relative_to(root).as_posix()
        is_allowlisted = relative in VENDOR_ALLOWLIST or relative.startswith(
            VENDOR_ALLOWLIST_PREFIXES
        )
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if not is_allowlisted:
                vendor_match = VENDOR_PATTERN.search(line)
                if vendor_match is not None:
                    violations.append(
                        PublicCopyViolation(
                            path=relative,
                            line=line_number,
                            phrase=vendor_match.group(0),
                            kind="outside legal/research allowlist",
                            text=line.strip(),
                        )
                    )
            for _label, pattern in compiled:
                match = pattern.search(line)
                if match is None:
                    continue
                if is_allowlisted:
                    continue
                violations.append(
                    PublicCopyViolation(
                        path=relative,
                        line=line_number,
                        phrase=match.group(0),
                        text=line.strip(),
                    )
                )
    return violations


def main() -> int:
    violations = evaluate_public_copy_legal()
    if violations:
        print("check_public_copy_legal: FAIL")
        print("  non-allowlisted vendor references or high-risk phrases:")
        for item in violations:
            print(f"    - {item.render()}")
        return 1
    print(
        "check_public_copy_legal: PASS - vendor references are contained to the legal/research allowlist."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
