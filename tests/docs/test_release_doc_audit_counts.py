# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""TW-F: a release verification doc's self-reported doc-audit evidence should
track scripts/audit_docs.py's live output, not a remembered/pasted number.

docs/releases/v1.0.0-rc18-verification.md line ~193 claimed "355 documents /
408 links / 0 problems" while a fresh run of scripts/audit_docs.py reports 357
documents (the doc count drifted after the line was written and before the
doc was re-checked). This originally turned that prose number into a checked,
release-blocking assertion.

OWNER RULING (Scott Converse, 2026-08-12, recorded in
.agent-runs/native-windows/HANDOFF-2026-08-12-beta-completion.md): doc-count
drift in a dated, historical verification doc is prose staleness, not a
functional regression, and must not gate the release. Demoted from
release-blocking to a warning: this test records drift between the doc's
claimed count and the live scan instead of failing the suite over it. Do not
re-promote this to a hard assert without a fresh owner ruling, and do not
edit the historical rc18 doc's claimed count just to chase a moving live
scan -- the doc is a point-in-time record, not a live view.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RC18_VERIFICATION = REPO_ROOT / "docs" / "releases" / "v1.0.0-rc18-verification.md"
AUDIT_DOCS_SCRIPT = REPO_ROOT / "scripts" / "audit_docs.py"

_COUNT_LINE_RE = re.compile(r"(\d+)\s+documents\s*/\s*(\d+)\s+links\s*/\s*(\d+)\s+problems")
_LIVE_COUNT_RE = re.compile(r"documents scanned\s*:\s*(\d+)")


def _live_audit_docs_count() -> int:
    proc = subprocess.run(
        [sys.executable, str(AUDIT_DOCS_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    match = _LIVE_COUNT_RE.search(proc.stdout)
    assert match, f"Could not parse a document count from audit_docs.py output:\n{proc.stdout}"
    return int(match.group(1))


def test_rc18_verification_doc_audit_count_matches_live_scan() -> None:
    text = RC18_VERIFICATION.read_text(encoding="utf-8")
    match = _COUNT_LINE_RE.search(text)
    assert match, f"{RC18_VERIFICATION} has no 'N documents / M links / P problems' line to check"
    doc_claimed_count = int(match.group(1))
    live_count = _live_audit_docs_count()
    if doc_claimed_count != live_count:
        # Per the 2026-08-12 owner ruling (see module docstring): record the
        # drift instead of failing the release gate over prose in a dated
        # historical doc. Intentionally not `warnings.warn` -- this repo's
        # pytest config runs with filterwarnings = ["error", ...], which
        # would turn a warning right back into the hard failure we're
        # demoting away from.
        print(
            f"WARNING (non-blocking, 2026-08-12 owner ruling): "
            f"{RC18_VERIFICATION} claims {doc_claimed_count} documents but "
            f"scripts/audit_docs.py currently scans {live_count}. Drift is "
            "expected as the doc corpus grows after a dated verification doc "
            "was written; this is recorded, not enforced."
        )
