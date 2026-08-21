# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy contracts for cross-platform installer release claims."""

from __future__ import annotations

import importlib
from pathlib import Path


class TestCrossPlatformInstallerPolicy:
    def test_policy_accepts_native_windows_service_claims(self, tmp_path: Path) -> None:
        """The native Windows product (ADR-0021) genuinely has no WSL2
        dependency -- this claim is true and must pass, not fail."""

        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        docs = tmp_path / "installer.md"
        docs.write_text(
            "CivicCast installs a native Windows service without WSL2.",
            encoding="utf-8",
        )

        result = policy.check_cross_platform_installer_policy([docs])

        assert result.status == "passed"

    def test_policy_rejects_stale_wsl2_bootstrap_claims(self, tmp_path: Path) -> None:
        """The retired WSL2/Ubuntu bootstrap lane must never be claimed as a
        current requirement -- that decision (2026-08-19) is the one this
        check now guards."""

        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        docs = tmp_path / "installer.md"
        docs.write_text(
            "The Windows installer requires WSL2 and bootstraps an Ubuntu distro.",
            encoding="utf-8",
        )

        result = policy.check_cross_platform_installer_policy([docs])

        assert result.status == "failed"
        assert "native Windows product" in result.next_step

    def test_policy_rejects_full_model_proof_when_models_are_skipped(self, tmp_path: Path) -> None:
        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        proof = tmp_path / "proof.md"
        proof.write_text(
            "All model proof is complete. Model status: skipped because provider unavailable.",
            encoding="utf-8",
        )

        result = policy.check_cross_platform_installer_policy([proof])

        assert result.status == "failed"
        assert "proof_unavailable" in result.next_step

    def test_policy_rejects_package_artifacts_without_sidecars(self, tmp_path: Path) -> None:
        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"package bytes")

        result = policy.check_installer_artifact_directory(tmp_path)

        assert result.status == "failed"
        assert "sidecar" in result.next_step.lower()

    def test_policy_rejects_sidecar_with_no_sha256_field(self, tmp_path: Path) -> None:
        import json

        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"package bytes")
        sidecar = artifact.with_name(artifact.name + ".sidecar.json")
        sidecar.write_text(json.dumps({"install_manifest": {"signed": False}}), encoding="utf-8")

        result = policy.check_installer_artifact_directory(tmp_path)

        assert result.status == "failed"
        assert "sha256" in result.next_step.lower()

    def test_policy_accepts_package_artifact_with_a_real_sidecar_hash(self, tmp_path: Path) -> None:
        # This release chain has no cosign/Sigstore step (ADR 0022); a sidecar
        # needs a real sha256, not an attestation reference.
        import json

        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"package bytes")
        sidecar = artifact.with_name(artifact.name + ".sidecar.json")
        sidecar.write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")

        result = policy.check_installer_artifact_directory(tmp_path)

        assert result.status == "passed"

    def test_evaluate_flags_current_release_manifest_missing_beta_handoff(
        self, tmp_path: Path
    ) -> None:
        import json

        policy = importlib.import_module("scripts.policy.check_release_artifacts")
        release = tmp_path / "artifacts" / "release"
        release.mkdir(parents=True)
        # A current-version manifest with no beta_handoff_acquisition must be
        # flagged. The old hardcoded pre-reset path would never have matched this.
        (release / "civiccast-1.0.0-release-artifacts-manifest.json").write_text(
            json.dumps({"version": "1.0.0", "artifacts": []}),
            encoding="utf-8",
        )

        violations = policy.evaluate_release_artifacts(tmp_path)

        assert any("beta_handoff_acquisition" in v for v in violations), violations

    def test_run_all_invokes_release_artifacts_policy_check(self) -> None:
        run_all = importlib.import_module("scripts.policy.run_all")

        checks = {name: args[0] for name, args in run_all.CHECKS}

        assert checks.get("check_release_artifacts") == "check_release_artifacts.py"
