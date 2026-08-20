# SPDX-License-Identifier: Apache-2.0
"""Guard the published-release asset-consistency check (gate-civiccast C2/M7).

Proves the check flags the exact rc8 defects: a missing unified manifest and an
orphaned *.sigstore.json attestation. Pure logic, no network.
"""

from __future__ import annotations

import json

from scripts.policy.check_published_release_assets import (
    find_asset_problems,
    find_candidate_problems,
    find_public_beta_problems,
    find_release_problems,
    main,
)

COMPLETE = [
    "civiccast-1.0.0-rc9-windows-setup.exe",
    "civiccast-1.0.0-rc9-windows-setup.exe.sidecar.json",
    "civiccast-1.0.0-rc9-windows-setup.exe.sigstore.json",
    "civiccast-1.0.0-rc9-release-artifacts-manifest.json",
    "civiccast-1.0.0-rc9-release-artifacts-manifest.json.sigstore.json",
    "civiccast-1.0.0rc9-py3-none-any.whl",
    "civiccast-1.0.0rc9-py3-none-any.whl.sigstore.json",
]


def test_complete_self_consistent_set_passes():
    assert find_asset_problems(COMPLETE) == []


def test_missing_unified_manifest_is_flagged():
    assets = [a for a in COMPLETE if not a.endswith("-release-artifacts-manifest.json")]
    problems = find_asset_problems(assets)
    assert any("release-artifacts-manifest.json" in p for p in problems)


def test_orphan_sigstore_is_flagged():
    # The exact rc8 shape: the manifest's sigstore is present but the manifest is not.
    assets = [a for a in COMPLETE if a != "civiccast-1.0.0-rc9-release-artifacts-manifest.json"]
    problems = find_asset_problems(assets)
    assert any("orphaned attestation" in p and "manifest.json.sigstore.json" in p for p in problems)


def test_missing_installer_or_sidecar_is_flagged():
    no_exe = [a for a in COMPLETE if not a.endswith("-windows-setup.exe")]
    assert any("windows-setup.exe" in p for p in find_asset_problems(no_exe))
    no_sidecar = [a for a in COMPLETE if not a.endswith(".exe.sidecar.json")]
    assert any("sidecar" in p for p in find_asset_problems(no_sidecar))


def test_draft_release_is_not_accepted_as_published():
    payload = {"tagName": "v1.0.0-rc11", "isDraft": True, "assets": []}
    assert any("draft" in p for p in find_release_problems(payload, "v1.0.0-rc11"))


def test_release_tag_must_match_requested_tag():
    payload = {"tagName": "v1.0.0-rc9", "isDraft": False, "assets": []}
    assert any("tag" in p for p in find_release_problems(payload, "v1.0.0-rc11"))


def test_matching_nondraft_release_posture_passes():
    payload = {"tagName": "v1.0.0-rc11", "isDraft": False, "assets": []}
    assert find_release_problems(payload, "v1.0.0-rc11") == []


def test_candidate_posture_requires_matching_draft():
    matching_draft = {"tagName": "v1.0.0-rc11", "isDraft": True, "assets": []}
    public_release = {"tagName": "v1.0.0-rc11", "isDraft": False, "assets": []}
    assert find_candidate_problems(matching_draft, "v1.0.0-rc11") == []
    assert any("not a draft" in p for p in find_candidate_problems(public_release, "v1.0.0-rc11"))


def test_public_beta_is_an_explicit_cli_phase(monkeypatch):
    class Result:
        stdout = json.dumps(
            {
                "tagName": "v1.0.0-rc14",
                "isDraft": False,
                "isPrerelease": True,
                "assets": [{"name": name} for name in COMPLETE],
            }
        )

    monkeypatch.setattr(
        "scripts.policy.check_published_release_assets.subprocess.run", lambda *a, **k: Result()
    )
    assert main(["check", "v1.0.0-rc14", "--public-beta"]) == 0


def test_public_beta_posture_requires_published_prerelease():
    public_beta = {
        "tagName": "v1.0.0-rc14",
        "isDraft": False,
        "isPrerelease": True,
        "assets": [],
    }
    draft = {**public_beta, "isDraft": True}
    final_release = {**public_beta, "isPrerelease": False}
    assert find_public_beta_problems(public_beta, "v1.0.0-rc14") == []
    assert any("draft" in p for p in find_public_beta_problems(draft, "v1.0.0-rc14"))
    assert any("prerelease" in p for p in find_public_beta_problems(final_release, "v1.0.0-rc14"))


def test_require_published_is_an_explicit_cli_phase(monkeypatch):
    class Result:
        stdout = json.dumps(
            {
                "tagName": "v1.0.0-rc11",
                "isDraft": True,
                "assets": [{"name": name} for name in COMPLETE],
            }
        )

    monkeypatch.setattr(
        "scripts.policy.check_published_release_assets.subprocess.run", lambda *a, **k: Result()
    )
    assert main(["check", "v1.0.0-rc11"]) == 2  # phase selection is fail-closed
    assert main(["check", "v1.0.0-rc11", "--candidate"]) == 0
    assert main(["check", "v1.0.0-rc11", "--require-published"]) == 1
