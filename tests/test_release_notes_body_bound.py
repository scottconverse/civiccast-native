# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The GitHub release body must stay under GitHub's 125,000-character limit
even when the [Unreleased] CHANGELOG section is huge (measured live on the
v1.0.0-beta.5 publish, 2026-09-10: HTTP 422 "body is too long")."""

from __future__ import annotations

from scripts.render_release_notes import (
    CHANGELOG_BODY_MAX_CHARS,
    bound_changelog_section,
    render_native_beta_candidate_notes,
)


def test_short_changelog_is_unchanged() -> None:
    assert bound_changelog_section("  - one line  ") == "- one line"


def test_long_changelog_is_cut_at_a_line_boundary_with_a_pointer() -> None:
    big = "\n".join(f"- entry {i} " + "x" * 80 for i in range(3000))
    out = bound_changelog_section(big)
    assert len(out) <= CHANGELOG_BODY_MAX_CHARS + 300
    head, _, tail = out.rpartition("\n\n")
    assert head.endswith("x" * 80)  # cut on a whole line, never mid-line
    assert "complete entry is `CHANGELOG.md`" in tail


def test_rendered_body_stays_under_github_limit() -> None:
    big = "\n".join(f"- entry {i} " + "x" * 80 for i in range(3000))
    body = render_native_beta_candidate_notes(
        tag="v1.0.0-beta.5",
        source_sha="148c8d2172dd6b63cbbb856b429b68aa020dc421",
        build_run_url="https://example.invalid/build",
        gate_a_run_url="https://example.invalid/gate-a",
        lane_verdicts={"clean": "PASS", "dirty": "PASS", "download-only": "PASS"},
        changelog_unreleased=big,
        assets=[{"filename": "setup.exe", "bytes": 1, "sha256": "0" * 64}],
        smartscreen_note="note",
    )
    assert len(body) < 125_000
