# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for v0.6 signed-record data models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from civiccast.records.models import (
    PdfARecordMetadata,
    RecordExportRequest,
    RecordExportResponse,
    Rfc3161TimestampProof,
)


class TestRecordModels:
    def test_export_request_requires_approved_summary_status(self) -> None:
        with pytest.raises(ValidationError, match="approved"):
            RecordExportRequest(
                summary_id="summary-1",
                summary_status="pending_review",
                requested_by="staff-1",
            )

    def test_rfc3161_proof_binds_digest_nonce_and_timestamp(self) -> None:
        proof = Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + ("a" * 64),
            token_der_b64="MII=",
            tsa_policy_oid="1.2.3.4",
            nonce="123456",
            timestamped_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
            certificate_fingerprint="sha256:" + ("b" * 64),
        )

        assert proof.algorithm == "sha256"
        assert proof.artifact_digest.endswith("a" * 64)
        assert proof.nonce == "123456"

    def test_record_response_requires_pdfa_metadata_fingerprint_and_proof(self) -> None:
        response = RecordExportResponse(
            record_id="record-1",
            summary_id="summary-1",
            status="verified",
            audit_fingerprint="sha256:" + ("c" * 64),
            pdfa=PdfARecordMetadata(
                conformance="PDF/A-3B",
                file_name="meeting-1-record.pdf",
                media_type="application/pdf",
                byte_size=2048,
                embedded_metadata_names=["sourced-claims.json", "provenance.json"],
            ),
            timestamp_proof=Rfc3161TimestampProof(
                algorithm="sha256",
                artifact_digest="sha256:" + ("d" * 64),
                token_der_b64="MII=",
                timestamped_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
            ),
        )

        assert response.model_config["extra"] == "forbid"
        assert "sourced-claims.json" in response.pdfa.embedded_metadata_names
