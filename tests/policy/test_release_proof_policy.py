# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 release-proof policy checks."""

from __future__ import annotations

import ast
from pathlib import Path

REAL_LOOKING_MODEL_TAGS = {
    "gemma3:latest",
    "gemma4:e4b",
    "translategemma:4b",
    "whisper-large-v3",
}


def _deterministic_fallback_model_tags(source: str) -> set[str]:
    """Return real model tags embedded in deterministic/fallback implementations."""

    tree = ast.parse(source)
    offenders: set[str] = set()
    scoped_nodes = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, scoped_nodes):
            continue
        docstring = ast.get_docstring(node) or ""
        scope_markers = f"{node.name} {docstring}".lower()
        if "deterministic" not in scope_markers:
            continue
        strings = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        offenders.update(
            tag for tag in REAL_LOOKING_MODEL_TAGS if any(tag in text for text in strings)
        )
    return offenders


class TestWorkflowRunnerPolicy:
    def test_hardware_bound_proof_workflows_stay_self_hosted(self) -> None:
        """Hosted-runners directive (2026-06-12): hosted everywhere EXCEPT
        lanes that physically cannot run hosted. Only the hardware/duration
        lanes keep self-hosted labels; everything else must be hosted."""

        hardware_bound = [
            Path(".github/workflows/ai-release-proof.yml"),  # RTX GPU
            Path(".github/workflows/vm-cleanroom-release.yml"),  # local Hyper-V
            Path(".github/workflows/six-hour-soak.yml"),  # >6h hosted ceiling
        ]
        for path in hardware_bound:
            text = path.read_text(encoding="utf-8")
            assert "self-hosted" in text, path

        hosted_proofs = [
            Path(".github/workflows/external-provider-proof.yml"),
            Path(".github/workflows/loudness-compliance.yml"),
        ]
        for path in hosted_proofs:
            text = path.read_text(encoding="utf-8")
            assert "self-hosted" not in text, path
            assert "ubuntu-latest" in text, path

    def test_release_artifacts_workflow_uses_hosted_runners_only(self) -> None:
        text = Path(".github/workflows/release-artifacts.yml").read_text(encoding="utf-8")

        assert "self-hosted" not in text
        assert "ubuntu-latest" in text or "windows-latest" in text

    def test_windows_installer_is_blob_signed_verified_and_uploaded(self) -> None:
        text = Path(".github/workflows/release-artifacts.yml").read_text(encoding="utf-8")
        windows_job = text[text.index("  windows-installer:") : text.index("  publish-manifest:")]

        install = windows_job.index("cosign-installer")
        sign = windows_job.index("cosign sign-blob")
        verify = windows_job.index("cosign verify-blob")
        refresh = windows_job.index("Regenerate integrity artifacts with the Sigstore bundle")
        upload = windows_job.index("Upload workflow artifact bundle")

        assert install < sign < verify < refresh < upload
        assert "cosign attest-blob" not in windows_job
        assert "cosign verify-blob-attestation" not in windows_job
        assert "civiccast-*-windows-setup.exe.sigstore.json" in windows_job
        assert "civiccast-*-windows-setup.exe.sidecar.json" in windows_job

    def test_sigstore_verification_binds_the_exact_trigger_ref(self) -> None:
        text = Path(".github/workflows/release-artifacts.yml").read_text(encoding="utf-8")

        # The owner/name half is DERIVED, not written down. It used to be
        # hard-coded as scottconverse/civiccast, which meant that after the
        # migration cosign signed as civiccast-native and verified against
        # civiccast -- verification rejecting its own signatures. Pinning the
        # derived form keeps a regression back to a literal repo name failing.
        assert "github.com/scottconverse/civiccast/" not in text
        identity_tail = "/.github/workflows/release-artifacts.yml@"

        assert (
            f'identity="https://github.com/${{GITHUB_REPOSITORY}}{identity_tail}${{GITHUB_REF}}"'
            in text
        )
        assert (
            f'$identity = "https://github.com/${{env:GITHUB_REPOSITORY}}{identity_tail}'
            f'${{env:GITHUB_REF}}"' in text
        )
        # 1, not 2: the bash form appears only in publish-manifest now. The
        # linux-artifacts job that carried the second one was removed with the
        # .deb/.rpm lane. The pwsh form in windows-installer is asserted
        # separately below.
        assert text.count('--certificate-identity "$identity"') == 1
        assert "--certificate-identity $identity" in text
        assert "certificate-identity-regexp" not in text


class TestWindowsAttestationDocumentation:
    def test_trust_guide_requires_exe_sidecar_and_sigstore_bundle_together(self) -> None:
        text = Path("docs/install/windows-release-trust.md").read_text(encoding="utf-8")

        assert "windows-setup.exe`" in text
        assert "windows-setup.exe.sidecar.json`" in text
        assert "windows-setup.exe.sigstore.json`" in text
        assert "keep them together in one folder" in text

    def test_code_signing_policy_includes_windows_sigstore_provenance(self) -> None:
        text = Path("CODE_SIGNING_POLICY.md").read_text(encoding="utf-8")

        assert "Windows setup executable carries both" in text
        assert "keyless blob signature" in text
        assert "Every non-Windows-job release asset" not in text

    def test_rc11_verification_page_names_the_public_release_and_historical_record(self) -> None:
        text = Path("docs/releases/v1.0.0-rc11-verification.md").read_text(encoding="utf-8")

        assert "public prerelease for controlled beta testing" in text
        assert "https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc11" in text
        assert "Prepublication verification record" in text
        assert "There is no public rc11 release" not in text


class TestWorkflowCostDiscipline:
    def test_expensive_release_workflows_have_manual_dispatch_timeout_and_retention(
        self,
    ) -> None:
        workflow_paths = [
            Path(".github/workflows/ai-release-proof.yml"),
            Path(".github/workflows/external-provider-proof.yml"),
            Path(".github/workflows/vm-cleanroom-release.yml"),
            Path(".github/workflows/six-hour-soak.yml"),
            Path(".github/workflows/loudness-compliance.yml"),
        ]

        for path in workflow_paths:
            text = path.read_text(encoding="utf-8")
            assert "workflow_dispatch" in text
            assert "concurrency:" in text
            assert "timeout-minutes:" in text
            assert "retention-days:" in text
            assert "on:\n  push:" not in text


class TestReleaseProofSourcePolicy:
    def test_vm_cleanroom_script_consumes_candidate_artifacts_not_working_tree(
        self,
    ) -> None:
        script = Path("scripts/run_vm_cleanroom_release.py").read_text(encoding="utf-8")

        assert "release-candidate" in script
        assert "working tree" not in script.lower()


class TestNoDeterministicReleaseEvidence:
    def test_v11_release_evidence_contains_no_deterministic_or_mock_tags(self) -> None:
        evidence_paths = [
            Path("docs/releases/evidence/v1.1-real-ai-proof.json"),
            Path("docs/releases/evidence/v1.1-external-provider-proof.md"),
        ]

        for path in evidence_paths:
            text = path.read_text(encoding="utf-8")
            assert "deterministic-test" not in text
            assert "mock" not in text.lower()


class TestNoRealModelTagsInDeterministicFallbacks:
    def test_policy_detects_real_model_tag_inside_deterministic_fallback(self) -> None:
        source = """
class DeterministicCaptionFallback:
    def transcribe(self) -> dict[str, str]:
        return {"model": "whisper-large-v3"}
"""

        assert _deterministic_fallback_model_tags(source) == {"whisper-large-v3"}

    def test_deterministic_fallbacks_do_not_emit_real_looking_model_tags(self) -> None:
        offenders: list[str] = []
        for path in Path("civiccast").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for tag in _deterministic_fallback_model_tags(source):
                offenders.append(f"{path}:{tag}")

        assert offenders == []
