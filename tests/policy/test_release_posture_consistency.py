# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: no active release surface may keep an operative directive for a
prior release once the release identity advances.

CC-RC17-005 regression guard. When the current version moved to rc17, six
active surfaces (README, ARCHITECTURE, FAQ, SUPPORT, the SmartScreen
walkthrough, and known-limitations) still told readers that rc15 was the
current/validated/only-use release or that rc16 was unpublished, while other
sections of the same files declared rc17 current. The existing doc-truth
suite passed that contradictory state because it only required the current
tag's presence; it never rejected a stale operative directive for a prior
tag. This control closes that false negative.

Matching is block/reflow-aware (the round-5 review proved a physical-line
scan is bypassed by ordinary Markdown prose reflow): lines are grouped into
blocks the same way scripts/policy/check_release_candidate_boundary.py does,
each line is stripped of blockquote markers, and the block is joined with
single spaces before phrase matching, so a directive wrapped across source
lines still trips.

Historical statements remain legal: past-tense evidence ("the exact public
rc15 installer passed ..."), possessives ("rc15's repairs"), withdrawal
records ("rc13 is withdrawn"), and era labels ("rc15-era") do not match the
forbidden operative phrases below.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CURRENT_VERSION = (
    (REPO_ROOT / "civiccast" / "_version.py")
    .read_text(encoding="utf-8")
    .split('__version__ = "', 1)[1]
    .split('"', 1)[0]
)
_RC_MATCH = re.search(r"-rc(\d+)$", CURRENT_VERSION)
CURRENT_RC = int(_RC_MATCH.group(1)) if _RC_MATCH else None

# 2026-08-31: the owner retired the WSL/mainline rc-numbered release line's
# version machinery. civiccast/_version.py now carries the single native
# version ("1.0.0-beta.1"), which is not rc-numbered, so CURRENT_RC is None
# and evaluate_release_posture_consistency's own `if CURRENT_RC is None:
# return violations` early-return applies -- there is no rc line left to
# carry a stale prior-rc directive, so the guard is correctly a no-op. The
# mechanism tests below prove the guard's phrase-matching logic against a
# synthetic prior-rc CURRENT_RC; they cannot exercise that logic while the
# live repo's CURRENT_RC is None, since the function short-circuits before
# ever reading their fixtures. Skip them for that reason rather than letting
# them fail on a premise (an rc-numbered current version) that no longer
# holds; test_active_surfaces_have_no_stale_prior_release_directives and
# test_prior_rc_number_does_not_match_inside_a_longer_number still run and
# still pass (trivially, via the same early return, which is the correct
# outcome now).
_RC_LINE_RETIRED_REASON = (
    "the WSL rc-numbered release line is retired (CURRENT_VERSION "
    f"{CURRENT_VERSION!r} is not rc-numbered); evaluate_release_posture_"
    "consistency's own CURRENT_RC-is-None early return makes this guard "
    "a no-op by design, so its phrase-matching mechanism cannot be "
    "exercised against synthetic fixtures until an rc-numbered line "
    "exists again"
)
skip_if_rc_line_retired = pytest.mark.skipif(
    CURRENT_RC is None, reason=_RC_LINE_RETIRED_REASON
)

# Curated active release surfaces â€” the union of the front doors, the
# tester path, and the adoption/public copy this repo already treats as
# release-identity surfaces in its sibling policy suites.
ACTIVE_SURFACES = (
    "README.md",
    "INSTALL-WINDOWS.md",
    "ARCHITECTURE.md",
    "CAPABILITIES.md",
    "FAQ.md",
    "SUPPORT.md",
    "docs/index.html",
    "docs/install-windows.html",
    "docs/adoption/early-adopter-quickstart.md",
    "docs/adoption/release-policy.md",
    "docs/tester/START-HERE.md",
    "docs/tester/lpm-beta-test-handoff.md",
    "docs/tester/technical-walkthrough.md",
    "docs/tester/known-limitations.md",
    "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
    "docs/install/windows-release-trust.md",
    "docs/public/civiccast-org-holding-page.md",
    # The persona guides the user manual links readers to. Omitting these is
    # how "Windows beta testing is open with rc15" survived in
    # technical-ops-reference.md after the release identity moved to rc17: the
    # guard only watched the front doors, not the documents the front doors
    # send people to.
    "docs/USER-MANUAL.md",
    "docs/admin-guide.md",
    "docs/meeting-operator-guide.md",
    "docs/records-clerk-guide.md",
    "docs/operator-language-guide.md",
    "docs/technical-ops-reference.md",
    "docs/tester/nontechnical-walkthrough.md",
    "docs/tester/station-implementation-walkthrough.md",
    "docs/tester/first-broadcast-checklist.md",
    "docs/tester/support-bundle-instructions.md",
    "docs/tester/recovery-kit-help.md",
    "docs/installer/beta-tester-handoff.md",
)

# A new list-item marker starts a new block even without a blank line before
# it, mirroring check_release_candidate_boundary.py.
_LIST_ITEM_RE = re.compile(r"^\s*([-*]|\d+\.)\s")
_QUOTE_PREFIX_RE = re.compile(r"^\s*(>\s?)+")


def _forbidden_phrases_for_prior(n: int) -> tuple[str, ...]:
    tag = f"v1.0.0-rc{n}"
    short = f"rc{n}"
    return (
        f"`{tag}` is the current",
        f"{short} is the current",
        f"`{tag}` is the validated",
        f"{short} is the validated",
        f"`{tag}` is the public",
        f"{short} is the public",
        f"the public beta `{tag}`",
        f"use only the public `{tag}`",
        f"use only `{tag}`",
        f"begin a new installer rehearsal only with `{tag}`",
        f"use the approved {short} replacement",
        f"`{tag}` is unpublished",
        f"{short} is unpublished",
        f"{short} remains unpublished",
        f"`{tag}` is the unpublished",
        f"{short} is the unpublished",
        f"the repair release is `{tag}`",
        f"the current public repair beta is `{tag}`",
        f"{short} remains the current",
        # "Windows beta testing is open with rc15." â€” the shape that hid in
        # technical-ops-reference.md because it never used the word "current".
        f"testing is open with {short}",
        f"testing is open with `{tag}`",
        f"use the approved `{tag}`",
        f"use the approved {short} public beta",
        f"the approved `{tag}` public beta",
    )


@functools.cache
def _phrase_re(phrase: str, n: int) -> re.Pattern[str]:
    """Compile a phrase so "rc1" cannot match inside "rc17".

    Without the lookahead, the rc1 phrase set matches the rc17 sentence
    "testing is open with rc17" and reports a false violation.
    """
    pattern = re.escape(phrase).replace(f"rc{n}", f"rc{n}(?!\\d)")
    return re.compile(pattern)


def _blocks(lines: list[str]) -> list[list[int]]:
    """Return blocks as lists of 0-based line indices into ``lines``."""
    blocks: list[list[int]] = []
    current: list[int] = []
    for index, raw in enumerate(lines):
        if not raw.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        if _LIST_ITEM_RE.match(raw) and current:
            blocks.append(current)
            current = [index]
        else:
            current.append(index)
    if current:
        blocks.append(current)
    return blocks


def _clean(line: str) -> str:
    """Strip blockquote markers and surrounding whitespace from one line."""
    return _QUOTE_PREFIX_RE.sub("", line).strip()


def _block_text(lines: list[str], block: list[int]) -> str:
    # Joined with a single space, each line stripped of quote markers, so a
    # phrase that wraps across source lines (ordinary prose reflow) still
    # matches as one logical sentence.
    return " ".join(_clean(lines[i]) for i in block)


def evaluate_release_posture_consistency(root: Path = REPO_ROOT) -> list[str]:
    violations: list[str] = []
    if CURRENT_RC is None:
        return violations
    phrase_sets = {n: _forbidden_phrases_for_prior(n) for n in range(1, CURRENT_RC)}
    for relative in ACTIVE_SURFACES:
        path = root / relative
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for block in _blocks(lines):
            block_text = _block_text(lines, block).lower()
            for n, phrases in phrase_sets.items():
                for phrase in phrases:
                    if not _phrase_re(phrase, n).search(block_text):
                        continue
                    # Report the single source line carrying the phrase when
                    # one exists; a wrapped phrase is reported against the
                    # block's first line.
                    line_index = next(
                        (i for i in block if phrase in _clean(lines[i]).lower()),
                        block[0],
                    )
                    violations.append(
                        f"{relative}:{line_index + 1}: operative prior-release "
                        f"directive (rc{n}) after the current version moved to "
                        f"{CURRENT_VERSION}: {lines[line_index].strip()!r}"
                    )
    return violations


def test_active_surfaces_have_no_stale_prior_release_directives() -> None:
    violations = evaluate_release_posture_consistency()
    assert violations == [], (
        "Stale operative prior-release directives on active surfaces:\n" + "\n".join(violations)
    )


@skip_if_rc_line_retired
def test_guard_goes_red_on_the_exact_cc_rc17_005_shapes(tmp_path: Path) -> None:
    # Red-proof: every contradiction class the round-4 review cited must trip.
    samples = {
        "README.md": (
            "> **Use only the public `v1.0.0-rc15` release.**\n"
            "Begin a new installer rehearsal only with `v1.0.0-rc15`:\n"
        ),
        "ARCHITECTURE.md": (
            "**Current release posture:** `v1.0.0-rc15` is the public clean-Windows repair\nbeta.\n"
        ),
        "FAQ.md": ("`v1.0.0-rc15` is the current public Windows\nrepair beta.\n"),
        "SUPPORT.md": ("`v1.0.0-rc15` is the current public Windows beta;\n"),
        "docs/tester/SMARTSCREEN-WALKTHROUGH.md": (
            "> `v1.0.0-rc16` is unpublished and not approved for SmartScreen walkthroughs\n"
        ),
        "docs/tester/known-limitations.md": (
            "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.\n"
            "Use the approved rc15 replacement and verify that exact release's SHA-256\n"
            "The repair release is `v1.0.0-rc15`; its exact public packaged installer\n"
        ),
    }
    for relative, text in samples.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    violations = evaluate_release_posture_consistency(tmp_path)

    tripped_files = {v.split(":", 1)[0] for v in violations}
    assert tripped_files == set(samples), f"guard missed files: {set(samples) - tripped_files}"


@skip_if_rc_line_retired
def test_guard_goes_red_on_reflow_wrapped_directives(tmp_path: Path) -> None:
    # Round-5 falsification shapes: a normal line break inside the phrase
    # must not launder it. One wrapped sample per core directive family,
    # including a wrapped blockquote.
    samples = {
        "README.md": ("`v1.0.0-rc15` is the\ncurrent public Windows repair beta.\n"),
        "FAQ.md": ("Use only\n`v1.0.0-rc15` and its matching proof assets.\n"),
        "SUPPORT.md": (
            "> `v1.0.0-rc16` is\n> unpublished and not approved for support requests.\n"
        ),
    }
    for relative, text in samples.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    violations = evaluate_release_posture_consistency(tmp_path)

    tripped_files = {v.split(":", 1)[0] for v in violations}
    assert tripped_files == set(samples), (
        f"reflow bypass: guard missed wrapped directives in {set(samples) - tripped_files}"
    )


def test_prior_rc_number_does_not_match_inside_a_longer_number(tmp_path: Path) -> None:
    """rc1 must not match inside rc18.

    Regression: the first cut of the "testing is open with rcN" phrase family
    used plain substring matching, so the rc1 phrase matched the perfectly
    correct sentence "Windows beta testing is open with rc17." and reported a
    violation against the current release.

    The fixture names the CURRENT release deliberately -- that is the whole
    point of the case -- so it moves with each release bump.
    """
    target = tmp_path / "docs" / "technical-ops-reference.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "> **Windows beta testing is open with rc18.** `v1.0.0-rc13` is withdrawn.\n"
        "Use the approved `v1.0.0-rc18` public beta.\n",
        encoding="utf-8",
    )

    assert evaluate_release_posture_consistency(tmp_path) == []


@skip_if_rc_line_retired
def test_guard_goes_red_on_testing_is_open_with_a_prior_rc(tmp_path: Path) -> None:
    # The exact shape that hid in technical-ops-reference.md: it never used
    # the word "current", so the original phrase set walked straight past it.
    target = tmp_path / "docs" / "technical-ops-reference.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "> **Windows beta testing is open with rc15.** Use the approved\n"
        "> `v1.0.0-rc15` public beta and its matching verification artifacts.\n",
        encoding="utf-8",
    )

    violations = evaluate_release_posture_consistency(tmp_path)

    assert violations, "guard missed 'testing is open with rc15'"
    assert all("technical-ops-reference" in v for v in violations)


def test_guard_stays_green_on_historical_statements(tmp_path: Path) -> None:
    # Past-tense evidence, possessives, withdrawal records, and era labels
    # must not trip â€” they are the legal way to keep history on a surface.
    target = tmp_path / "README.md"
    target.write_text(
        "The exact public rc15 installer passed installation from a WSL-disabled\n"
        "baseline and cold-reboot recovery. It carries rc15's clean-Windows\n"
        "repairs and rc16's published UI/UX repairs. rc13 is withdrawn after a\n"
        "genuine clean-host bootstrap failure; a known rc15-era limitation is\n"
        "fixed in this line.\n",
        encoding="utf-8",
    )

    assert evaluate_release_posture_consistency(tmp_path) == []


def test_guard_does_not_join_across_blank_lines_or_list_items(tmp_path: Path) -> None:
    # Phrase fragments separated by a paragraph boundary or split across two
    # list items are different sentences; the block model must not fuse them
    # into a false positive.
    target = tmp_path / "README.md"
    target.write_text(
        "This paragraph mentions `v1.0.0-rc15` is the\n"
        "\n"
        "current section heading of an unrelated paragraph.\n"
        "\n"
        "- one list item ends with use only\n"
        "- `v1.0.0-rc15` appears in the next item as history\n",
        encoding="utf-8",
    )

    assert evaluate_release_posture_consistency(tmp_path) == []
