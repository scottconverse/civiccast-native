# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence contracts for v0.6 signed records."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civiccast.records.models import RecordExportResponse

SessionFactory = Callable[[], AbstractContextManager[Session]]


class RecordStoreConflictError(RuntimeError):
    """Raised when a record id already exists."""


class RecordStore(Protocol):
    def create_record(
        self,
        record: RecordExportResponse,
        *,
        artifact_bytes: bytes,
    ) -> RecordExportResponse: ...
    def get_record(self, record_id: str) -> RecordExportResponse | None: ...
    def get_artifact(self, record_id: str) -> bytes | None: ...


class InMemoryRecordStore:
    """In-memory signed-record store for tests and no-DB local runs."""

    def __init__(self) -> None:
        self._records: dict[str, RecordExportResponse] = {}
        self._artifacts: dict[str, bytes] = {}

    def create_record(
        self,
        record: RecordExportResponse,
        *,
        artifact_bytes: bytes,
    ) -> RecordExportResponse:
        if record.record_id in self._records:
            raise RecordStoreConflictError(f"Record already exists: {record.record_id}")
        self._records[record.record_id] = record
        self._artifacts[record.record_id] = artifact_bytes
        return record

    def get_record(self, record_id: str) -> RecordExportResponse | None:
        return self._records.get(record_id)

    def get_artifact(self, record_id: str) -> bytes | None:
        return self._artifacts.get(record_id)


class PostgresRecordStore:
    """SQLAlchemy-backed signed-record store for release persistence."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create_record(
        self,
        record: RecordExportResponse,
        *,
        artifact_bytes: bytes,
    ) -> RecordExportResponse:
        with self._session_factory() as session:
            table = self._table_prefix(session)
            try:
                session.execute(
                    text(
                        f"INSERT INTO {table}record_exports "  # nosec B608
                        "(record_id, summary_id, status, audit_fingerprint, artifact_digest, "
                        "pdfa_metadata_json, timestamp_proof_json, artifact_bytes, created_at) "
                        "VALUES (:record_id, :summary_id, :status, :audit_fingerprint, "
                        ":artifact_digest, :pdfa_metadata_json, :timestamp_proof_json, "
                        ":artifact_bytes, :created_at)"
                    ),
                    {
                        "record_id": record.record_id,
                        "summary_id": record.summary_id,
                        "status": record.status,
                        "audit_fingerprint": record.audit_fingerprint,
                        "artifact_digest": record.artifact_digest,
                        "pdfa_metadata_json": record.pdfa.model_dump_json(),
                        "timestamp_proof_json": record.timestamp_proof.model_dump_json(),
                        "artifact_bytes": artifact_bytes,
                        "created_at": datetime.now(UTC),
                    },
                )
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise RecordStoreConflictError(
                    f"Record already exists: {record.record_id}"
                ) from exc
            return record

    def get_record(self, record_id: str) -> RecordExportResponse | None:
        with self._session_factory() as session:
            table = self._table_prefix(session)
            row = session.execute(
                text(
                    f"SELECT record_id, summary_id, status, audit_fingerprint, "  # nosec B608
                    f"artifact_digest, pdfa_metadata_json, timestamp_proof_json "
                    f"FROM {table}record_exports WHERE record_id = :record_id"
                ),
                {"record_id": record_id},
            ).first()
            if row is None:
                return None
            return RecordExportResponse.model_validate(
                {
                    "record_id": row.record_id,
                    "summary_id": row.summary_id,
                    "status": row.status,
                    "audit_fingerprint": row.audit_fingerprint,
                    "pdfa": json.loads(row.pdfa_metadata_json),
                    "timestamp_proof": json.loads(row.timestamp_proof_json),
                    "artifact_digest": row.artifact_digest,
                }
            )

    def get_artifact(self, record_id: str) -> bytes | None:
        with self._session_factory() as session:
            table = self._table_prefix(session)
            row = session.execute(
                text(
                    f"SELECT artifact_bytes FROM {table}record_exports WHERE record_id = :record_id"  # nosec B608
                ),
                {"record_id": record_id},
            ).first()
            return None if row is None else bytes(row.artifact_bytes)

    @staticmethod
    def _table_prefix(session: Session) -> str:
        bind = session.get_bind()
        return "" if bind.dialect.name == "sqlite" else "civiccast."
