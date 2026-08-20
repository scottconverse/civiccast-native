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
