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

    # test_release_artifacts_workflow_uses_hosted_runners_only,
    # test_windows_installer_is_blob_signed_verified_and_uploaded, and
    # test_sigstore_verification_binds_the_exact_trigger_ref were removed with
    # .github/workflows/release-artifacts.yml (the legacy WSL-era release
    # pipeline; chore/retire-wsl-lane). The current release path is the native
    # chain: .github/workflows/native-beta-candidate-artifacts.yml (build) and
    # .github/workflows/sign-native-installer.yml (Authenticode sign via Azure
    # Trusted Signing). That chain carries no cosign/sigstore step today, so
    # those three functions' assertions have no native-path equivalent to pin.


class TestWindowsAttestationDocumentation:
    def test_trust_guide_requires_exe_and_sidecar_together_with_no_sigstore_bundle(self) -> None:
        text = Path("docs/install/windows-release-trust.md").read_text(encoding="utf-8")

        assert "windows-setup.exe`" in text
        assert "windows-setup.exe.sidecar.json`" in text
        assert "keep them together in one folder" in text
        # ADR 0022: Sigstore/cosign was evaluated and denied for this release
        # chain. No release asset carries a `.sigstore.json` bundle, so the
        # trust guide must not tell testers to fetch one -- the only
        # permitted "sigstore" mention is the explicit denial statement.
        assert "windows-setup.exe.sigstore.json`" not in text
        assert "carries no Sigstore/cosign step" in text

    def test_code_signing_policy_documents_authenticode_only_chain(self) -> None:
        text = Path("CODE_SIGNING_POLICY.md").read_text(encoding="utf-8")

        assert "Authenticode code-signed" in text
        assert "Azure Trusted Signing" in text
        assert "evaluated and denied" in text
        assert "docs/adr/0022-sigstore-attestation-denied.md" in text
        assert "no cosign/sigstore step anywhere on the" in text
        assert "no code in this repository generates a `.sigstore.json` bundle" in text


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
