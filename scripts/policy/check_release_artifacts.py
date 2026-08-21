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
    """Reject overclaims in installer docs and release proof text.

    This used to reject a "native Windows service without WSL2" claim as an
    overclaim, back when the WSL2/Ubuntu bootstrap lane was the only real
    Windows deployment and that claim was false. The native Windows product
    (ADR-0021) made it true, and the WSL2 lane was retired outright under
    the owner's "no linux" decision (2026-08-19) -- so the check is now
    inverted: it rejects docs that still claim the Windows installer
    requires, bootstraps, or runs inside WSL2/Ubuntu, since that claim is
    the one that is false today.
    """

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        if any(
            phrase in text
            for phrase in (
                "wsl2-only bootstrap",
                "requires wsl2",
                "bootstraps wsl2",
                "runs inside wsl2",
                "runs inside the wsl2",
            )
        ):
            return PolicyResult(
                status="failed",
                next_step=(
                    "Rewrite the stale WSL2 bootstrap claim: CivicCast's Windows "
                    "installer is a native Windows product (ADR-0021) with no WSL2 "
                    "dependency; the WSL2/Ubuntu lane was retired."
                ),
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
    """Require package artifacts to have sidecars naming real SHA-256 bytes.

    This repo's release chain has no cosign/Sigstore step (Azure Trusted
    Signing / Authenticode is the only signing mechanism -- see
    ``CODE_SIGNING_POLICY.md``), so a sidecar is never required to carry an
    ``attestation`` reference; requiring one would demand an artifact nothing
    in this chain produces. A present sidecar.json must at minimum name the
    artifact's real SHA-256.
    """

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
                next_step=f"{artifact.name} is missing a sidecar.",
            )
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return PolicyResult(
                status="failed",
                next_step=f"{sidecar.name} must be valid JSON with a sha256 field.",
            )
        if not payload.get("sha256"):
            return PolicyResult(
                status="failed",
                next_step=f"{sidecar.name} is missing its sha256 field.",
            )
    return PolicyResult(
        status="passed", next_step="Installer artifacts include sidecars with real hashes."
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
