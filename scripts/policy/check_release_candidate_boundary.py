#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: candidate-only installer capabilities must not read as current-release fact.

A live surface (an install page, FAQ, or tester handoff) that names the
current public release artifact must not, on the same surface, describe an
installer capability that artifact does not actually have -- unless that
description is explicitly labeled as forthcoming candidate behavior.

This closed CC-RC17-002: `INSTALL-WINDOWS.md`, `FAQ.md`,
`docs/tester/START-HERE.md`, `docs/tester/lpm-beta-test-handoff.md`, and
`docs/tester/known-limitations.md` all named the public rc15 artifact while
describing rc17-only Ollama auto-provisioning and UAC-resume re-elevation as
if rc15 already does it.

Advancing the release identity (e.g. rc17 gets approved and becomes the
named public release) is ONE deliberate change: bump
``CURRENT_PUBLIC_RELEASE_TAG`` below to match
``CANDIDATE_CAPABILITY_INTRODUCED_IN``. Once they're equal, the capability
described by ``CANDIDATE_ONLY_CAPABILITY_MARKERS`` is current-release fact,
not a candidate claim, and this check stops requiring the forthcoming label
for it. No per-surface edits to this script are needed at that point --
only the docs themselves get rewritten to describe the now-current release,
which is a separate, ordinary documentation task.
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

# The ONE line to change at rc17 approval time. See module docstring.
CURRENT_PUBLIC_RELEASE_TAG = "v1.0.0-rc18"
CANDIDATE_CAPABILITY_INTRODUCED_IN = "v1.0.0-rc18"

# Surfaces that name CURRENT_PUBLIC_RELEASE_TAG as the current/active public
# release. Curated, not inferred, matching this repo's existing
# ACTIVE_RELEASE_SURFACES pattern (test_current_release_candidate_docs.py) --
# inferring "does this file claim to be current" from free text is exactly
# the kind of fuzzy detection that lets drift back in unnoticed.
RELEASE_IDENTITY_SURFACES = (
    Path("INSTALL-WINDOWS.md"),
    Path("FAQ.md"),
    Path("docs/tester/START-HERE.md"),
    Path("docs/tester/lpm-beta-test-handoff.md"),
    Path("docs/tester/known-limitations.md"),
    Path("docs/USER-MANUAL.md"),
)

# Substrings that only appear when a surface is describing the rc17-only
# Ollama auto-provisioning or UAC-resume re-elevation behavior. Chosen to be
# stable across wording edits (they're the technical nouns, not the
# surrounding prose) so this check keeps matching real content rather than
# a single frozen sentence.
CANDIDATE_ONLY_CAPABILITY_MARKERS = (
    "local Ollama AI runtime",
    "local Ollama runtime",
    "sets up the local Ollama",
    "provisions Ollama",
    "provision Ollama",
    "Ollama summary and translation models",
    "re-elevates as a fresh",
    "does not expect exactly one prompt",
)

# A candidate-only marker is compliant only if one of these qualifiers
# appears in the same block. Both parts of the acceptance criterion's own
# phrase -- "FORTHCOMING" and "rc17-candidate" -- must be present, so a
# generic "coming soon" note elsewhere can't accidentally satisfy this.
QUALIFIER_PATTERNS = (re.compile(r"forthcoming", re.I), re.compile(r"rc17", re.I))

# A block is a maximal run of non-blank lines, except that a new list-item
# marker ("- " / "1. ") starts a new block even without a blank line before
# it (list items in this repo's docs are rarely blank-line-separated).
_LIST_ITEM_RE = re.compile(r"^\s*([-*]|\d+\.)\s")


@dataclass(frozen=True)
class BoundaryFinding:
    path: str
    line: int
    marker: str


def _blocks(lines: list[str]) -> list[list[int]]:
    """Return blocks as lists of 0-based line indices into ``lines``."""
    blocks: list[list[int]] = []
    current: list[int] = []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            if current:
                blocks.append(current)
                current = []
            continue
        starts_item = bool(_LIST_ITEM_RE.match(raw))
        if starts_item and current:
            blocks.append(current)
            current = [index]
        else:
            current.append(index)
    if current:
        blocks.append(current)
    return blocks


def _block_text(lines: list[str], block: list[int]) -> str:
    # Joined with a single space (not "\n") and each line stripped, so a
    # marker or qualifier phrase that happens to wrap across two source
    # lines (ordinary prose reflow) still matches as one logical line.
    return " ".join(lines[i].strip() for i in block)


def evaluate_release_candidate_boundary(root: Path = REPO_ROOT) -> list[BoundaryFinding]:
    findings: list[BoundaryFinding] = []
    if CURRENT_PUBLIC_RELEASE_TAG == CANDIDATE_CAPABILITY_INTRODUCED_IN:
        # The release identity has been advanced past the candidate line
        # that introduced this capability; it's current-release fact now,
        # not a candidate-only claim, so nothing to enforce here.
        return findings

    for relative in RELEASE_IDENTITY_SURFACES:
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        blocks = _blocks(lines)
        for block in blocks:
            block_text = _block_text(lines, block)
            matched_markers = [m for m in CANDIDATE_ONLY_CAPABILITY_MARKERS if m in block_text]
            if not matched_markers:
                continue
            qualified = all(pattern.search(block_text) for pattern in QUALIFIER_PATTERNS)
            if qualified:
                continue
            for marker in matched_markers:
                # Report the single source line containing the marker when
                # one exists; a marker that only appears once the block is
                # reflowed (it wraps across two source lines) is reported
                # against the block's first line instead.
                line_index = next(
                    (i for i in block if marker in lines[i]),
                    block[0],
                )
                findings.append(
                    BoundaryFinding(
                        path=relative.as_posix(),
                        line=line_index + 1,
                        marker=marker,
                    )
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    findings = evaluate_release_candidate_boundary()
    if findings:
        print("check_release_candidate_boundary: FAIL")
        for finding in findings:
            print(
                f"  - {finding.path}:{finding.line}: names {CURRENT_PUBLIC_RELEASE_TAG} as the "
                f"current public release and describes candidate-only capability "
                f"({finding.marker!r}) without a 'Forthcoming ... rc17-candidate' label in "
                "the same block."
            )
        return 1
    print(
        "check_release_candidate_boundary: PASS - no surface combines current-release "
        "identity with an unlabeled candidate-only capability."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
