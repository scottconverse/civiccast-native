# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence contract tests for v0.6 signed-record exports."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.records.models import PdfARecordMetadata, RecordExportResponse, Rfc3161TimestampProof
from civiccast.records.store import InMemoryRecordStore, RecordStoreConflictError


def _record() -> RecordExportResponse:
    return RecordExportResponse(
        record_id="record-1",
        summary_id="summary-1",
        status="verified",
        audit_fingerprint="sha256:" + ("e" * 64),
        pdfa=PdfARecordMetadata(
            conformance="PDF/A-3B",
            file_name="meeting-1-record.pdf",
            media_type="application/pdf",
            byte_size=2048,
            embedded_metadata_names=["sourced-claims.json", "provenance.json"],
        ),
        timestamp_proof=Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + ("f" * 64),
            token_der_b64="MII=",
            timestamped_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        ),
    )


class TestRecordsStoreContract:
    def test_record_export_and_timestamp_artifact_round_trip_in_memory(self) -> None:
        store = InMemoryRecordStore()

        stored = store.create_record(_record(), artifact_bytes=b"%PDF-1.7")
        found = store.get_record("record-1")

        assert found == stored
        assert store.get_artifact("record-1") == b"%PDF-1.7"
        assert found.timestamp_proof.artifact_digest.startswith("sha256:")

    def test_duplicate_record_id_is_conflict(self) -> None:
        store = InMemoryRecordStore()
        store.create_record(_record(), artifact_bytes=b"%PDF-1.7")

        with pytest.raises(RecordStoreConflictError, match="record-1"):
            store.create_record(_record(), artifact_bytes=b"%PDF-1.7")
