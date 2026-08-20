# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for installer-facing model setup state."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path


class TestModelInstallerState:
    def test_online_helper_reports_full_lifecycle_states(self) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")
        whisper_hash = hashlib.sha256(b"whisper-large-v3 bytes").hexdigest()
        gemma_hash = hashlib.sha256(b"gemma4:e4b bytes").hexdigest()

        states = model_state.plan_online_model_setup(
            models=["whisper-large-v3", "gemma4:e4b"],
            provider_available=True,
            verified_hashes={
                "whisper-large-v3": whisper_hash,
                "gemma4:e4b": gemma_hash,
            },
        )

        assert [state.status for state in states] == [
            "planned",
            "running",
            "progress",
            "complete",
        ]
        assert states[-1].proof_state == "hash_verified"
        assert states[-1].sha256 == whisper_hash

    def test_online_helper_does_not_invent_hash_proof_without_verified_hashes(self) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")

        states = model_state.plan_online_model_setup(
            models=["whisper-large-v3", "gemma4:e4b"],
            provider_available=True,
        )

        assert states[-1].status == "unavailable"
        assert states[-1].proof_state == "proof_unavailable"
        assert states[-1].sha256 is None

    def test_cancelled_model_setup_never_reports_complete_proof(self) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")

        state = model_state.cancel_model_setup("gemma4:e4b")

        assert state.status == "cancelled"
        assert state.proof_state == "proof_unavailable"
        assert "rerun model setup" in state.next_step.lower()

    def test_skipped_or_unavailable_models_never_produce_full_proof(self) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")

        skipped = model_state.mark_model_skipped("translategemma:4b", reason="operator skipped")
        unavailable = model_state.mark_model_unavailable(
            "gemma4:e4b", reason="provider unavailable"
        )

        assert skipped.status == "skipped"
        assert unavailable.status == "unavailable"
        assert skipped.proof_state == "proof_unavailable"
        assert unavailable.proof_state == "proof_unavailable"

    def test_offline_bundle_import_uses_real_hashes(self, tmp_path: Path) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")
        model_file = tmp_path / "whisper-large-v3.tar.zst"
        model_file.write_bytes(b"offline model bytes")
        digest = hashlib.sha256(model_file.read_bytes()).hexdigest()

        result = model_state.import_offline_model_bundle(
            bundle_dir=tmp_path,
            expected_hashes={"whisper-large-v3.tar.zst": digest},
        )

        assert result.status == "complete"
        assert result.items[0].sha256 == digest
        assert result.items[0].proof_state == "hash_verified"

    def test_missing_model_names_file_and_next_operator_action(self, tmp_path: Path) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")

        result = model_state.import_offline_model_bundle(
            bundle_dir=tmp_path,
            expected_hashes={"gemma4-e4b.tar.zst": "0" * 64},
        )

        assert result.status == "blocked"
        assert "gemma4-e4b.tar.zst" in result.next_step
        assert "copy" in result.next_step.lower()
