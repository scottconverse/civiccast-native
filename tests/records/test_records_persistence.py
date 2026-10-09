# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence contract tests for v0.6 signed-record exports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from civiccast.records.models import PdfARecordMetadata, RecordExportResponse, Rfc3161TimestampProof
from civiccast.records.store import (
    InMemoryRecordStore,
    PostgresRecordStore,
    RecordStoreConflictError,
)


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

    def test_durable_record_list_filters_and_limits_without_loading_artifacts(self) -> None:
        engine = create_engine("sqlite://", future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE record_exports (record_id TEXT PRIMARY KEY, summary_id TEXT NOT NULL, "
                    "status TEXT NOT NULL, audit_fingerprint TEXT NOT NULL, artifact_digest TEXT NOT NULL, "
                    "pdfa_metadata_json TEXT NOT NULL, timestamp_proof_json TEXT NOT NULL, "
                    "artifact_bytes BLOB NOT NULL, created_at DATETIME NOT NULL)"
                )
            )

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresRecordStore(session_factory)
        first = _record()
        second = _record().model_copy(update={"record_id": "record-2", "summary_id": "summary-2"})
        with session_factory() as session:
            for record, artifact in ((first, b"%PDF first"), (second, b"%PDF second")):
                session.execute(
                    text(
                        "INSERT INTO record_exports (record_id, summary_id, status, audit_fingerprint, "
                        "artifact_digest, pdfa_metadata_json, timestamp_proof_json, artifact_bytes, created_at) "
                        "VALUES (:record_id, :summary_id, :status, :audit_fingerprint, :artifact_digest, "
                        ":pdfa_metadata_json, :timestamp_proof_json, :artifact_bytes, :created_at)"
                    ),
                    {
                        "record_id": record.record_id,
                        "summary_id": record.summary_id,
                        "status": record.status,
                        "audit_fingerprint": record.audit_fingerprint,
                        "artifact_digest": record.artifact_digest,
                        "pdfa_metadata_json": record.pdfa.model_dump_json(),
                        "timestamp_proof_json": record.timestamp_proof.model_dump_json(),
                        "artifact_bytes": artifact,
                        "created_at": "2026-05-14T12:00:00+00:00",
                    },
                )
            session.commit()

        records = store.list_records(summary_id="summary-2", limit=1)

        assert [record.record_id for record in records] == ["record-2"]
        assert records[0].pdf_bytes == b""
        assert store.get_artifact("record-2") == b"%PDF second"
        engine.dispose()
