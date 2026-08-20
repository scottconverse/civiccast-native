#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: a release-facing surface must not both deny and assert that the
same release version is installable.

TW-B: SUPPORT.md, ARCHITECTURE.md, docs/install/windows-release-trust.md,
docs/adoption/early-adopter-quickstart.md, docs/tester/known-limitations.md,
docs/tester/SMARTSCREEN-WALKTHROUGH.md, docs/tester/technical-walkthrough.md,
docs/tester/lpm-beta-test-handoff.md, README.md, and FAQ.md each carried an
accurate "v1.0.0-rc18 is an owner-held unpublished candidate; no approved
public installer" banner in one paragraph, and a stale "v1.0.0-rc18 is the
current public beta" claim -- naming the exact same version -- in another
paragraph of the same file. A reader who only sees one of the two paragraphs
gets a confident, wrong answer to "can I install this right now."

This check flags any scanned surface where the SAME version token is named
by both an "installer denied" paragraph and an "installer is current" paragraph
anywhere in the file. Paragraph-scoped (not whole-file substring matching) so
a file that correctly narrates rc17 as current and rc18 as denied in the same
breath is not flagged just because both phrases appear somewhere in the doc.
"""

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

# Curated release-facing surfaces a reader actually lands on to decide
# whether a build is installable -- matches this repo's existing
# RELEASE_IDENTITY_SURFACES / ACTIVE_RELEASE_SURFACES curation pattern rather
# than crawling the whole docs tree, which would risk flagging historical
# evidence logs that legitimately quote old contradictory claims verbatim.
SCANNED_SURFACES = (
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("ARCHITECTURE.md"),
    Path("SUPPORT.md"),
    Path("CAPABILITIES.md"),
    Path("FAQ.md"),
    Path("docs/install/windows-release-trust.md"),
    Path("docs/adoption/early-adopter-quickstart.md"),
    Path("docs/tester/known-limitations.md"),
    Path("docs/tester/SMARTSCREEN-WALKTHROUGH.md"),
    Path("docs/tester/technical-walkthrough.md"),
    Path("docs/tester/lpm-beta-test-handoff.md"),
    Path("INSTALL-WINDOWS.md"),
)

_VERSION_RE = re.compile(r"v\d+\.\d+\.\d+(?:-rc\d+)?")
_NO_INSTALLER_RE = re.compile(
    r"(owner-held unpublished( repair)? candidate|no approved public( Windows)? installer)",
    re.I,
)
_CURRENT_BETA_RE = re.compile(
    r"is the current public( Windows)?( repair)? beta",
    re.I,
)


@dataclass(frozen=True)
class BannerContradiction:
    path: str
    version: str


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


# How close a version token must sit to a phrase match to be read as THAT
# phrase's subject (as opposed to some other version merely mentioned
# elsewhere in the same paragraph -- e.g. "v1.0.0-rc18 fixes the defects
# found against rc17" legitimately names two versions in one sentence
# without either being the OTHER version's current-beta/denial subject).
_MAX_SUBJECT_DISTANCE = 60


def _nearest_version(flat: str, match: re.Match[str]) -> str | None:
    best: str | None = None
    best_distance: int | None = None
    for version_match in _VERSION_RE.finditer(flat):
        distance = min(
            abs(version_match.start() - match.end()),
            abs(match.start() - version_match.end()),
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = version_match.group(0)
    if best is not None and best_distance is not None and best_distance <= _MAX_SUBJECT_DISTANCE:
        return best
    return None


def evaluate_no_contradictory_release_banners(
    root: Path = REPO_ROOT,
) -> list[BannerContradiction]:
    findings: list[BannerContradiction] = []
    for relative in SCANNED_SURFACES:
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig")
        denied_versions: set[str] = set()
        current_versions: set[str] = set()
        for paragraph in _paragraphs(text):
            # Reflow so an ordinary line wrap (e.g. "current public Windows\n
            # repair beta.") still matches as one logical phrase -- same
            # technique as check_release_candidate_boundary.py's _block_text.
            flat = " ".join(paragraph.split())
            for match in _NO_INSTALLER_RE.finditer(flat):
                version = _nearest_version(flat, match)
                if version:
                    denied_versions.add(version)
            for match in _CURRENT_BETA_RE.finditer(flat):
                version = _nearest_version(flat, match)
                if version:
                    current_versions.add(version)
        for version in sorted(denied_versions & current_versions):
            findings.append(BannerContradiction(path=relative.as_posix(), version=version))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    findings = evaluate_no_contradictory_release_banners()
    if findings:
        print("check_no_contradictory_release_banners: FAIL")
        for finding in findings:
            print(
                f"  - {finding.path}: names {finding.version} as both an owner-held/no-approved-"
                "installer candidate and the current public beta -- pick one."
            )
        return 1
    print(
        "check_no_contradictory_release_banners: PASS - no scanned surface contradicts "
        "itself about whether the same release version is installable."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
