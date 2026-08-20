#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Release-asset gate for an owner-held candidate or a published release.

Catches the class of release-engineering defect that shipped in v1.0.0-rc8
(gate-civiccast C1/C2): the unified release-artifacts manifest silently missing,
and a ``*.sigstore.json`` attestation left orphaned next to no base file.

Usage:
    python scripts/policy/check_published_release_assets.py <tag> --candidate
    python scripts/policy/check_published_release_assets.py <tag> --public-beta
    python scripts/policy/check_published_release_assets.py <tag> --require-published

Reads the live release via ``gh release view <tag>`` and exits
non-zero (printing every problem) if the asset set is incomplete or inconsistent.
The phase flag is mandatory. Candidate mode requires an owner-held draft;
public-beta mode requires a published prerelease; published mode accepts any
non-draft release. The rule logic is pure and unit-tested; only ``main`` touches
the network.
"""

from __future__ import annotations

import json
import subprocess
import sys


def find_asset_problems(asset_names: list[str]) -> list[str]:
    """Return a list of human-readable problems with the asset name set.

    Empty list == the release is complete and self-consistent.
    """
    names = set(asset_names)
    problems: list[str] = []

    # 1. Exactly one unified release-artifacts manifest must be published.
    manifests = [n for n in names if n.endswith("-release-artifacts-manifest.json")]
    if not manifests:
        problems.append(
            "missing the unified '*-release-artifacts-manifest.json' "
            "(the merged ledger publish-manifest is supposed to produce)"
        )
    elif len(manifests) > 1:
        problems.append(f"more than one release-artifacts manifest published: {sorted(manifests)}")

    # 2. No orphaned attestation: every '<x>.sigstore.json' needs '<x>' present.
    for n in sorted(names):
        if n.endswith(".sigstore.json"):
            base = n[: -len(".sigstore.json")]
            if base not in names:
                problems.append(
                    f"orphaned attestation '{n}' has no base artifact '{base}' "
                    "(stale/dangling predicate — a verifier would fail)"
                )

    # 3. The Windows installer + its sidecar (the reason the merge job exists)
    #    must be present.
    if not any(n.endswith("-windows-setup.exe") for n in names):
        problems.append("missing the Windows installer '*-windows-setup.exe'")
    if not any(n.endswith("-windows-setup.exe.sidecar.json") for n in names):
        problems.append("missing the installer sidecar '*-windows-setup.exe.sidecar.json'")

    return problems


def find_release_problems(payload: dict[str, object], expected_tag: str) -> list[str]:
    """Return publication-posture problems for a GitHub Release payload."""
    problems: list[str] = []
    actual_tag = payload.get("tagName")
    if actual_tag != expected_tag:
        problems.append(f"release tag mismatch: expected {expected_tag!r}, got {actual_tag!r}")
    if payload.get("isDraft") is not False:
        problems.append("release is still a draft and is not publicly published")
    return problems


def find_candidate_problems(payload: dict[str, object], expected_tag: str) -> list[str]:
    """Return owner-held candidate posture problems for a GitHub Release payload."""
    problems: list[str] = []
    actual_tag = payload.get("tagName")
    if actual_tag != expected_tag:
        problems.append(f"release tag mismatch: expected {expected_tag!r}, got {actual_tag!r}")
    if payload.get("isDraft") is not True:
        problems.append("candidate release is not a draft; owner-held posture was lost")
    return problems


def find_public_beta_problems(payload: dict[str, object], expected_tag: str) -> list[str]:
    """Return authorized public-prerelease posture problems."""
    problems = find_release_problems(payload, expected_tag)
    if payload.get("isPrerelease") is not True:
        problems.append("public beta is not marked as a prerelease")
    return problems


def main(argv: list[str]) -> int:
    phases = {"--candidate", "--public-beta", "--require-published"}
    if len(argv) != 3 or argv[2] not in phases:
        print(
            "usage: check_published_release_assets.py <tag> "
            "(--candidate | --public-beta | --require-published)",
            file=sys.stderr,
        )
        return 2
    tag = argv[1]
    requested_phase = argv[2]
    out = subprocess.run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--json",
            "assets,isDraft,isPrerelease,tagName,url",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(out.stdout)
    assets = payload.get("assets", [])
    names = [a["name"] for a in assets]
    if requested_phase == "--candidate":
        phase = "candidate"
        posture_problems = find_candidate_problems(payload, tag)
    elif requested_phase == "--public-beta":
        phase = "public-beta"
        posture_problems = find_public_beta_problems(payload, tag)
    else:
        phase = "published"
        posture_problems = find_release_problems(payload, tag)
    problems = [*posture_problems, *find_asset_problems(names)]
    if problems:
        print(f"check_published_release_assets: FAIL ({phase}) for {tag} ({len(names)} assets):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        f"check_published_release_assets: PASS ({phase}) for {tag} "
        f"({len(names)} assets, self-consistent)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
