# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 external provider proof orchestration and redaction."""

from __future__ import annotations

from importlib import import_module


class TestExternalProviderProofOrchestration:
    def test_all_provider_surfaces_emit_redacted_release_evidence(self) -> None:
        proof_module = import_module("civiccast.publish.proof")

        result = proof_module.run_external_provider_proof(
            mode="release",
            allow_mocks=False,
        )

        assert {record.provider for record in result.records} == {
            "internet_archive",
            "youtube_live",
            "youtube_vod",
            "nas_rsync",
            "nas_zfs",
            "email_double_opt_in",
            "webhook_hmac",
            "podcast_rss",
        }
        for record in result.records:
            assert record.proof_mode != "mock"
            assert record.redacted_evidence
            assert "token" not in record.redacted_evidence.lower()
            assert "secret" not in record.redacted_evidence.lower()


class TestProviderProofReadinessPlan:
    def test_credentials_alone_do_not_count_as_live_proof(self) -> None:
        proof_module = import_module("civiccast.publish.proof")

        plan = proof_module.build_provider_proof_plan(
            configured_credentials={
                "internet-archive",
                "youtube-live",
                "youtube-vod",
                "local-nas-rsync",
                "local-nas-zfs",
                "subscriber-notifications",
            },
        )

        required = [item for item in plan if item.required_for_public_records]
        assert required
        assert {item.status for item in required} == {"needs_live_proof"}
        assert not any(item.ready_for_public_release for item in required)
        assert all(item.credential_configured for item in required)

    def test_missing_credentials_are_called_out_before_live_proof(self) -> None:
        proof_module = import_module("civiccast.publish.proof")

        internet_archive = next(
            item
            for item in proof_module.build_provider_proof_plan()
            if item.provider == "internet_archive"
        )

        assert internet_archive.status == "not_configured"
        assert internet_archive.ready_for_public_release is False
        assert internet_archive.credential_configured is False
        assert "Configure" in internet_archive.next_step

    def test_redacted_evidence_is_required_for_passed_proof(self) -> None:
        proof_module = import_module("civiccast.publish.proof")

        unredacted = next(
            item
            for item in proof_module.build_provider_proof_plan(
                configured_credentials={"internet-archive"},
                passed_evidence={"internet_archive": "proofs/ia.txt"},
            )
            if item.provider == "internet_archive"
        )
        redacted = next(
            item
            for item in proof_module.build_provider_proof_plan(
                configured_credentials={"internet-archive"},
                passed_evidence={"internet_archive": "proofs/ia.txt"},
                redacted_evidence={"internet_archive"},
            )
            if item.provider == "internet_archive"
        )

        assert unredacted.status == "proof_failed_redaction"
        assert unredacted.ready_for_public_release is False
        assert redacted.status == "proof_passed"
        assert redacted.ready_for_public_release is True
        assert redacted.evidence_reference == "proofs/ia.txt"

    def test_optional_provider_can_be_explicitly_skipped_without_claiming_proof(self) -> None:
        proof_module = import_module("civiccast.publish.proof")

        webhook = next(
            item
            for item in proof_module.build_provider_proof_plan(
                skipped_optional_providers={"webhook_hmac"},
            )
            if item.provider == "webhook_hmac"
        )

        assert webhook.status == "skipped_optional"
        assert webhook.ready_for_public_release is True
        assert "Do not claim" in webhook.next_step
