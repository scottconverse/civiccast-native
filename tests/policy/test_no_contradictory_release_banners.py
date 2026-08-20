# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the no-contradictory-release-banners policy check.

TW-B regression guard. SUPPORT.md, ARCHITECTURE.md,
docs/install/windows-release-trust.md, docs/adoption/early-adopter-quickstart.md,
docs/tester/known-limitations.md, docs/tester/SMARTSCREEN-WALKTHROUGH.md,
docs/tester/technical-walkthrough.md, README.md, and FAQ.md each independently
carried both "vX is an owner-held unpublished candidate; no approved public
installer" AND "vX is the current public beta" about the exact same version.
"""

from __future__ import annotations

from pathlib import Path

from scripts.policy.check_no_contradictory_release_banners import (
    SCANNED_SURFACES,
    evaluate_no_contradictory_release_banners,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_no_findings_on_a_clean_surface(tmp_path: Path) -> None:
    _write(
        tmp_path / "README.md",
        "\n".join(
            [
                "> **`v1.0.0-rc18` is an owner-held unpublished candidate.** There is no",
                "> approved public Windows installer while it is held.",
                "",
                "`v1.0.0-rc17` is the current public beta.",
                "",
            ]
        ),
    )

    assert evaluate_no_contradictory_release_banners(tmp_path) == []


def test_flags_the_same_version_asserted_both_ways(tmp_path: Path) -> None:
    """Reconstructs the exact round-shape: SUPPORT.md named v1.0.0-rc18 as
    both an owner-held unpublished candidate AND the current public Windows
    beta, in two separate paragraphs of the same file."""
    _write(
        tmp_path / "SUPPORT.md",
        "\n".join(
            [
                "> **Release state: `v1.0.0-rc18` is an owner-held unpublished repair candidate.**",
                "> There is no approved public Windows installer while it is held.",
                "",
                "> **Release state:** `v1.0.0-rc18` is the current public Windows beta. Use",
                "> only its signed GitHub release assets and complete manifest.",
                "",
            ]
        ),
    )

    findings = evaluate_no_contradictory_release_banners(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "SUPPORT.md"
    assert findings[0].version == "v1.0.0-rc18"


def test_does_not_flag_two_different_versions_discussed_together(tmp_path: Path) -> None:
    """A file that accurately narrates rc17 as current and rc18 as the
    denied candidate fixing rc17's bugs -- in the same paragraph -- must not
    be flagged just because both phrases and both tokens appear nearby."""
    _write(
        tmp_path / "README.md",
        "\n".join(
            [
                "`v1.0.0-rc17` is the current public beta line, carrying rc16's repairs.",
                "`v1.0.0-rc18` fixes rc17's stage-gate defects but remains an owner-held",
                "unpublished repair candidate until it clears its own gate re-run.",
                "",
            ]
        ),
    )

    assert evaluate_no_contradictory_release_banners(tmp_path) == []


def test_markers_outside_the_curated_surface_list_are_not_scanned(tmp_path: Path) -> None:
    """A doc naming a contradiction that isn't a curated live release-identity
    surface (e.g. a historical evidence log quoting the round-1 defect
    verbatim) is out of this control's scope by design."""
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "round1-quote.md",
        "\n".join(
            [
                "`v1.0.0-rc18` is an owner-held unpublished candidate.",
                "",
                "`v1.0.0-rc18` is the current public Windows beta.",
                "",
            ]
        ),
    )

    assert evaluate_no_contradictory_release_banners(tmp_path) == []


def test_real_docs_pass_after_the_tw_b_fix() -> None:
    """Integration proof: the actual repo docs, post-fix, clear the control."""
    assert evaluate_no_contradictory_release_banners() == []


def test_top_level_windows_install_guide_is_scanned() -> None:
    """INSTALL-WINDOWS.md must stay in the scan list.

    The first pass of this gate hardcoded a curated list that omitted
    INSTALL-WINDOWS.md -- the top-level Windows install guide, which was itself
    carrying the exact contradiction the gate exists to catch, undetected. A
    contradiction on the primary install doc that the gate cannot see is the
    worst-case blind spot, so pin that this file is covered.
    """
    assert Path("INSTALL-WINDOWS.md") in SCANNED_SURFACES
