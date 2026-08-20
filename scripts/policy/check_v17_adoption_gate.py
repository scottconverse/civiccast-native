#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: adoption docs stay complete and non-overclaiming."""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)
CURRENT_RELEASE_TAG = (
    "v"
    + (
        (REPO_ROOT / "civiccast" / "_version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "', 1)[1]
        .split('"', 1)[0]
    )
)

REQUIRED_DOCS: dict[Path, tuple[str, ...]] = {
    Path("docs/spec/release-plan-v1.7.md"): (
        "early adoption candidate",
        "not a Roku release",
        "policy check",
    ),
    Path("docs/adoption/early-adopter-quickstart.md"): (
        CURRENT_RELEASE_TAG,
        "Windows setup executable",
        "SmartScreen",
        "WSL2",
        "verified publisher",
        "source ZIP",
    ),
    Path("docs/adoption/support-intake.md"): (
        "support bundle",
        "Security reports",
        "Do not post passwords",
        "Response Expectations",
    ),
    Path("docs/adoption/procurement-legal-brief.md"): (
        "not legal advice",
        "Apache-2.0",
        "CC BY 4.0",
        "Data Ownership",
        "Public Records And Retention",
        "Accessibility Posture",
        "AI Captions",
        "incumbent platform",
    ),
    Path("docs/adoption/release-policy.md"): (
        "Source/runtime release",
        "Packaged Windows release",
        "exact Windows setup executable",
        "SHA-256 checksum",
        "Hardware Or Platform Claim",
        "Do not hide unfinished work",
    ),
    Path("docs/releases/v1.7-proof-bundle.md"): (
        "v1.3.1",
        "v1.4.0",
        "v1.5.0",
        "v1.6.0",
        "Known Boundaries",
        "Early-Adopter Decision Rule",
    ),
}

PLACEHOLDER_PATTERN = re.compile(r"\b(?:TODO|TBD|fill in|placeholder)\b", re.IGNORECASE)
OVERCLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bRoku Channel Store (?:ready|certified|published|approved)\b", re.IGNORECASE),
    re.compile(r"\b(?:SDI|DeckLink|Comcast|headend) (?:proven|certified|ready)\b", re.IGNORECASE),
    re.compile(r"\blegal(?:ly)? certified\b", re.IGNORECASE),
    re.compile(r"\baccessibility certified\b", re.IGNORECASE),
    re.compile(r"\bone-for-one incumbent platform (?:replacement|parity)\b", re.IGNORECASE),
)


def evaluate_v17_adoption_gate(root: Path) -> list[str]:
    """Return v1.7 adoption-readiness violations."""

    root = root.resolve()
    violations: list[str] = []
    release_url = f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_RELEASE_TAG}"
    readme_path = root / "README.md"
    public_release = readme_path.exists() and release_url in readme_path.read_text(
        encoding="utf-8", errors="ignore"
    )
    for relative, required_phrases in REQUIRED_DOCS.items():
        path = root / relative
        if not path.exists():
            violations.append(f"{relative.as_posix()}: missing required v1.7 readiness doc.")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            violations.append(f"{relative.as_posix()}: required v1.7 readiness doc is empty.")
            continue
        if PLACEHOLDER_PATTERN.search(text):
            violations.append(f"{relative.as_posix()}: contains placeholder language.")
        lower_text = text.lower()
        for phrase in required_phrases:
            if phrase.lower() not in lower_text:
                violations.append(f"{relative.as_posix()}: missing required phrase {phrase!r}.")
        for pattern in OVERCLAIM_PATTERNS:
            if pattern.search(text):
                violations.append(
                    f"{relative.as_posix()}: contains overclaim pattern {pattern.pattern!r}."
                )

        if relative == Path("docs/adoption/early-adopter-quickstart.md"):
            required_posture = (
                "current controlled beta" if public_release else "unpublished repair candidate"
            )
            if required_posture not in lower_text:
                violations.append(
                    f"{relative.as_posix()}: missing coherent release posture {required_posture!r}."
                )

    index_path = root / "docs/index.html"
    if index_path.exists():
        index_text = index_path.read_text(encoding="utf-8", errors="ignore")
        for relative in REQUIRED_DOCS:
            if relative.as_posix().removeprefix("docs/") not in index_text:
                violations.append(f"docs/index.html: missing link to {relative.as_posix()}.")
    else:
        violations.append("docs/index.html: missing docs index.")

    return violations


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else REPO_ROOT
    violations = evaluate_v17_adoption_gate(root)
    if violations:
        print("V1.7 ADOPTION GATE: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("V1.7 ADOPTION GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
