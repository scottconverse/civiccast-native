# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for cross-platform installer release claims."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PolicyResult:
    """Small policy result object used by tests and runbooks."""

    status: str
    next_step: str


def check_cross_platform_installer_policy(paths: list[Path]) -> PolicyResult:
    """Reject overclaims in installer docs and release proof text."""

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        if "native windows service" in text or "without wsl2" in text:
            return PolicyResult(
                status="failed",
                next_step="Rewrite Windows claims as Windows WSL2-only bootstrap support.",
            )
        if "model status: skipped" in text and "all model proof is complete" in text:
            return PolicyResult(
                status="failed",
                next_step="Use proof_unavailable for skipped or unavailable model lanes.",
            )
    return PolicyResult(
        status="passed", next_step="Cross-platform installer claims are policy clean."
    )


def check_installer_artifact_directory(path: Path) -> PolicyResult:
    """Require package artifacts to have sidecars and attestation references."""

    artifacts = [
        candidate
        for candidate in path.iterdir()
        if candidate.is_file() and not candidate.name.endswith(".sidecar.json")
    ]
    package_suffixes = (".deb", ".rpm", ".pkg", ".tar.gz", ".json")
    for artifact in artifacts:
        if not artifact.name.endswith(package_suffixes):
            continue
        sidecar = artifact.with_name(artifact.name + ".sidecar.json")
        if not sidecar.exists():
            return PolicyResult(
                status="failed",
                next_step=f"{artifact.name} is missing a sidecar and attestation reference.",
            )
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return PolicyResult(
                status="failed",
                next_step=f"{sidecar.name} must be valid JSON with an attestation reference.",
            )
        if not payload.get("attestation"):
            return PolicyResult(
                status="failed",
                next_step=f"{sidecar.name} is missing an attestation reference.",
            )
    return PolicyResult(
        status="passed", next_step="Installer artifacts include sidecars and attestations."
    )


def evaluate_release_artifacts(root: Path) -> list[str]:
    """Evaluate release-artifact claims that should run in aggregate policy."""

    docs_to_check = [
        root / "README.md",
        root / "INSTALL-WINDOWS.md",
        root / "ARCHITECTURE.md",
        root / "docs" / "USER-MANUAL.md",
        root / "docs" / "installer" / "cross-platform-installer.md",
        root / "docs" / "installer" / "beta-tester-handoff.md",
        root / "docs" / "releases" / "v3.0.0-beta1.md",
        root / "docs" / "releases" / "v3.0.0-beta1-verification.md",
    ]
    existing_docs = [path for path in docs_to_check if path.exists()]
    violations: list[str] = []
    docs_result = check_cross_platform_installer_policy(existing_docs)
    if docs_result.status != "passed":
        violations.append(docs_result.next_step)

    # Validate whatever release manifest(s) are actually present, version-agnostic.
    # (Previously this pointed at a hardcoded pre-reset v3.0.0-beta1 reroll path
    # that can never exist in the 1.0.0 line, so the check silently no-opped.)
    release_dir = root / "artifacts" / "release"
    manifests = (
        sorted(release_dir.rglob("civiccast-*-release-artifacts-manifest.json"))
        if release_dir.exists()
        else []
    )
    for manifest in manifests:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            violations.append(f"{manifest}: invalid JSON: {exc}")
            continue
        acquisition = payload.get("beta_handoff_acquisition")
        if not isinstance(acquisition, dict):
            violations.append(f"{manifest}: missing beta_handoff_acquisition.")
        elif "windows_installer" not in acquisition:
            violations.append(f"{manifest}: beta_handoff_acquisition missing windows_installer.")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    violations = evaluate_release_artifacts(args.root)
    if violations:
        print("check_release_artifacts: FAIL")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("check_release_artifacts: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
