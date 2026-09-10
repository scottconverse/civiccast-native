#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Render the GitHub release body from the release-artifacts manifest.

Root-cause fix for a hand-pasted-checksum release body going stale the moment
an asset is rebuilt or re-uploaded (see the rc.2 release-body audit finding):
the tag/commit and every SHA-256 in the release notes now come directly from
the same manifest the assets were built with, never typed by hand.

Usage::

    python scripts/render_release_notes.py \\
        --manifest artifacts/release/civiccast-0.1.0-rc6-release-artifacts-manifest.json \\
        --tag v0.1.0-rc6

Prints the release-body markdown to stdout. The "Verification run before
publishing" section is intentionally not generated here -- it depends on a
test run that happens after this script would be invoked -- so the caller
appends that section (and the "Known boundary" section, which is static
prose) before publishing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Filenames that belong in the release-body checksum list, in display order.
# Matches what a clean-machine tester is told to verify in
# docs/install/windows-release-trust.md.
_BODY_ASSET_SUFFIXES = (
    "-windows-setup.exe",
    "-windows-setup.exe.sidecar.json",
    "-clean-windows-proof-kit.zip",
    "-release-artifacts-manifest.json",
    "-windows-tester-package.zip",
)


def _select_body_assets(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_filename = {Path(a["filename"]).name: a for a in artifacts}
    selected = []
    for suffix in _BODY_ASSET_SUFFIXES:
        match = next((a for name, a in by_filename.items() if name.endswith(suffix)), None)
        if match is not None:
            selected.append(match)
    return selected


#: GitHub refuses a release body over 125,000 characters (HTTP 422 "body is
#: too long", measured live on the v1.0.0-beta.5 publish 2026-09-10 when the
#: [Unreleased] CHANGELOG section alone was ~130 KB). The "What changed"
#: section is bounded to this many characters at a line boundary; the full
#: text lives in CHANGELOG.md at the tagged commit and the body says so.
CHANGELOG_BODY_MAX_CHARS = 90_000


def bound_changelog_section(text: str, *, max_chars: int = CHANGELOG_BODY_MAX_CHARS) -> str:
    """Return ``text`` unchanged if it fits, else the longest prefix that ends
    at a line boundary within ``max_chars`` plus a pointer to the full text."""

    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    cut = stripped.rfind("\n", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    head = stripped[:cut].rstrip()
    return (
        head + "\n\n_The CHANGELOG entry for this release is longer than a GitHub release "
        "body allows; this is the first part. The complete entry is `CHANGELOG.md` "
        "at the tagged commit._"
    )


def render_release_notes(manifest: dict[str, Any], tag: str) -> str:
    commit = manifest.get("source_state", {}).get("head", "")
    if not commit:
        raise ValueError("manifest source_state.head is empty; cannot render Source identity.")

    assets = _select_body_assets(manifest.get("artifacts", []))
    if not assets:
        raise ValueError("no release-body assets found in manifest['artifacts'].")

    lines = [
        f"# CivicCast {tag.lstrip('v')} Test Release",
        "",
        "This is the RC clean-Windows test release for CivicCast 4.0.",
        "",
        "Source identity:",
        "",
        f"- Commit: {commit}",
        f"- Tag: {tag}",
        "",
        "Clean-machine tester rule:",
        "",
        "Start by reading the docs before launching the installer:",
        "",
        "1. docs/tester/START-HERE.md",
        "2. INSTALL-WINDOWS.md",
        "3. docs/install/windows-release-trust.md",
        f"4. docs/releases/{tag}-verification.md",
        "",
        "If docs, release assets, manifest, setup sidecar, proof kit, or installer "
        "UI disagree about version, filename, checksum, or next step, stop before "
        "installing and report the mismatch.",
        "",
        "SHA-256:",
        "",
    ]
    for artifact in assets:
        lines.append(f"- {Path(artifact['filename']).name}: {artifact['sha256']}")
    lines.append("")
    return "\n".join(lines)


def render_native_beta_candidate_notes(
    *,
    tag: str,
    source_sha: str,
    build_run_url: str,
    gate_a_run_url: str,
    lane_verdicts: dict[str, str],
    changelog_unreleased: str,
    assets: list[dict[str, Any]],
    smartscreen_note: str,
) -> str:
    """Render the GitHub release body for a native-Windows beta-candidate.

    Separate from :func:`render_release_notes` (the WSL2-line renderer) on
    purpose -- the native-beta-candidate publish path
    (``scripts/release/publish_beta_candidate.py``) ships a different asset
    set (an installer whose name does not carry the old
    ``-windows-setup.exe`` suffix convention, plus per-component ``.ccpack``
    runtime packs, never a proof kit or tester-package zip) and a Gate A
    three-lane verdict, neither of which the WSL2-line renderer's manifest
    shape can express. Reusing that function's asset-suffix matching would
    either silently drop every native asset or require faking filenames to
    match a naming convention this line does not use -- so this is an
    additive function in the same module (not a duplicate implementation)
    that the publish script imports and calls.

    ``lane_verdicts`` maps Gate A lane name (``clean``, ``dirty``,
    ``download-only``) to its verdict string (expected ``PASS`` -- the
    caller is responsible for having already refused to publish on anything
    else; this function only renders what it is given).

    ``assets`` is a list of ``{"filename": str, "bytes": int, "sha256":
    str}`` dicts, one per uploaded release asset, in upload order.
    """

    if not source_sha:
        raise ValueError("source_sha is empty; cannot render Source identity.")
    if not assets:
        raise ValueError("no release assets given; cannot render an asset table.")

    lines = [
        f"# CivicCast {tag.lstrip('v')} (Beta Candidate)",
        "",
        "> **This is a beta candidate, not a production release.** It has "
        "passed automated Gate A station-acceptance (clean install, "
        "cross-version upgrade, and download-only upgrade lanes) but has "
        "NOT had a human acceptance pass. Treat findings as expected; report "
        "them rather than assuming the release is broken.",
        "",
        "## Source identity",
        "",
        f"- Commit: {source_sha}",
        f"- Tag: {tag}",
        f"- Build run: {build_run_url}",
        f"- Gate A run: {gate_a_run_url}",
        "",
        "## Gate A verdict (all three lanes required PASS)",
        "",
        "| lane | verdict |",
        "| --- | --- |",
    ]
    for lane in ("clean", "dirty", "download-only"):
        if lane in lane_verdicts:
            lines.append(f"| {lane} | {lane_verdicts[lane]} |")
    lines += [
        "",
        "## What changed",
        "",
        bound_changelog_section(changelog_unreleased) or "(no [Unreleased] CHANGELOG entry found)",
        "",
        "## Install / upgrade",
        "",
        "Download `setup.exe`; if you already have CivicCast installed just "
        "run it -- your recordings, database and AI models are kept. "
        "First-time installs need the USB model bundle (the AI-model "
        "runtime is not a download asset on this release -- see "
        "INSTALL-WINDOWS.md).",
        "",
        "## SmartScreen note",
        "",
        smartscreen_note.strip(),
        "",
        "## Assets",
        "",
        "| asset | size | SHA-256 |",
        "| --- | --- | --- |",
    ]
    for asset in assets:
        size = asset.get("bytes")
        size_display = f"{int(size):,} bytes" if isinstance(size, int) else "?"
        lines.append(f"| {asset['filename']} | {size_display} | {asset['sha256']} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sys.stdout.write(render_release_notes(manifest, args.tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
