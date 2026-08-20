# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

"""Every ``drawtext=`` filter CivicCast builds must disable ffmpeg expansion.

Gate finding F-1 (Critical) was that community-submitted bulletin text reached
ffmpeg's ``%{...}`` expansion layer inside ``drawtext``.  The fix was to pass
``expansion=none`` at every ``drawtext`` build site.  Escaping the value (see
``civiccast.egress.source_plan._escape_drawtext``) is a *separate* control and
does not substitute for this one: escaping protects the surrounding
single-quoted syntax, while ``expansion=none`` disables ffmpeg's own
metacharacter layer inside the value.

That fix was originally audited only across ``civiccast/egress/``.  A seventh
site in ``civiccast/stream/slate.py`` was missed and carried no
``expansion=none`` (not exploitable -- its text is the module constant
``SLATE_TEXT`` -- but the same class of gap).  Grepping by hand is how it was
missed, so the invariant is asserted here instead.

Scope: ``civiccast/`` **and** ``tests/``.  A first revision of this guard
scanned only ``civiccast/`` and consequently could not see a fixture site that
interpolated a caller-supplied marker without ``expansion=none``
(audit-lite AL-002) -- the same blind-spot-shaped mistake one level down.

Exactly one exemption exists, for a fixture that burns ``%{pts}``/``%{n}``
timecode into synthetic media, where the expansion *is* the feature.  It is
honoured only under ``tests/`` and only with the documented marker; using it in
shipping code is itself a test failure.

If a new ``drawtext`` site is added, add ``expansion=none`` to it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "civiccast"
TESTS_ROOT = REPO_ROOT / "tests"

# Matches the start of a drawtext filter as it appears in built filter strings,
# e.g. "drawtext=expansion=none:text='...'" or "[in]drawtext=text='...'".
_DRAWTEXT = re.compile(r"drawtext=")

# A narrow, auditable escape hatch for the ONE legitimate case: a filter whose
# whole purpose is ffmpeg's own expansion (burning %{pts}/%{n} timecode into a
# synthetic fixture).  It is honoured ONLY under tests/ -- see
# test_no_expansion_exemption_is_permitted_in_production_code, which makes
# using it anywhere in civiccast/ a hard failure.  Grep this marker to audit
# every exemption in the repo.
_EXEMPTION_MARKER = "drawtext-expansion-required:"
_EXEMPTION_LOOKBACK = 8


def _python_sources() -> list[Path]:
    """Production code and tests both. The invariant is not test-optional.

    An earlier revision scanned only ``civiccast/`` and therefore could not see
    a fixture site that interpolated a caller-supplied value without
    ``expansion=none`` (audit-lite AL-002).
    """

    roots = (PACKAGE_ROOT, TESTS_ROOT)
    # This module is excluded from its own scan: it is the scanner, and it
    # deliberately contains an unguarded drawtext literal as the fail-closed
    # proof in test_the_guard_actually_catches_an_unguarded_site.  Those
    # literals are strings under test, not filters handed to ffmpeg.
    this_file = Path(__file__).resolve()
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.py")
        if "migrations" not in path.parts
        and "__pycache__" not in path.parts
        and path.resolve() != this_file
    )


def _is_exempt(lines: list[str], index: int, path: Path) -> bool:
    """True when a tests/ line carries a documented expansion-required marker."""

    if TESTS_ROOT not in path.parents:
        return False
    start = max(0, index - _EXEMPTION_LOOKBACK)
    return any(_EXEMPTION_MARKER in lines[i] for i in range(start, index + 1))


def test_every_drawtext_build_site_disables_ffmpeg_expansion() -> None:
    offenders: list[str] = []

    for path in _python_sources():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not _DRAWTEXT.search(line):
                continue
            # Prose in docstrings/comments legitimately mentions "drawtext=";
            # only flag lines that actually build a filter fragment.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "expansion=none" in line:
                continue
            # A line that merely names the token inside prose has no quoted
            # filter fragment being constructed.
            if "drawtext=" in line and not re.search(r"['\"].*drawtext=", line):
                continue
            if _is_exempt(lines, index, path):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{index + 1}: {stripped}")

    assert not offenders, (
        "drawtext filter(s) built without expansion=none -- ffmpeg's %{...} "
        "expansion would be live inside the text value:\n  " + "\n  ".join(offenders)
    )


def test_no_expansion_exemption_is_permitted_in_production_code() -> None:
    """The tests/-only escape hatch must never appear under civiccast/.

    Without this, the exemption marker added for one legitimate fixture (a
    timecode burn-in that needs %{pts}) could be pasted into shipping code to
    silence the guard above.
    """

    leaked = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _EXEMPTION_MARKER in line
    ]

    assert not leaked, (
        f"the {_EXEMPTION_MARKER!r} escape hatch is for test fixtures only and "
        "must never appear in shipping code:\n  " + "\n  ".join(leaked)
    )


def test_the_guard_actually_catches_an_unguarded_site(tmp_path: Path) -> None:
    """Fail-closed proof: the matcher must flag a site missing expansion=none.

    Without this, a regex that silently matched nothing would let the test
    above pass vacuously forever.
    """
    unguarded = "    filter = f\"drawtext=text='{value}':fontsize=14\""
    guarded = "    filter = f\"drawtext=expansion=none:text='{value}':fontsize=14\""

    def flags(line: str) -> bool:
        if not _DRAWTEXT.search(line):
            return False
        if "expansion=none" in line:
            return False
        return bool(re.search(r"['\"].*drawtext=", line))

    assert flags(unguarded), "the guard failed to flag an unguarded drawtext site"
    assert not flags(guarded), "the guard falsely flagged a guarded drawtext site"
