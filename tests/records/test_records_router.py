# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI contract tests for v0.6 signed-record routes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.auth.models import OperatorIdentity
from civiccast.records.exporter import SignedRecordExporter
from civiccast.records.models import RecordExportResponse
from civiccast.records.router import get_record_store
from civiccast.records.store import InMemoryRecordStore
from civiccast.records.timestamp import DeterministicTimestampAuthority
from civiccast.summary.store import InMemorySummaryStore
from tests.summary.test_summary_persistence import _summary

_TEST_OPERATOR = OperatorIdentity(
    operator_id="staff-1", operator_display_name="Staff One", token_id="token-staff-1"
)


def _exported_record(summary_id: str = "summary-1") -> RecordExportResponse:
    """A real, fully-rendered signed record (not a hand-built fixture)."""

    summary = _summary().model_copy(update={"summary_id": summary_id, "status": "approved"})
    summary_store = InMemorySummaryStore()
    summary_store.create_summary(summary)
    exporter = SignedRecordExporter(
        summary_store=summary_store,
        timestamp_authority=DeterministicTimestampAuthority(),
    )
    return exporter.export(summary_id=summary_id, operator_identity=_TEST_OPERATOR)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = InMemoryRecordStore()
    app.dependency_overrides[get_record_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


@pytest.fixture
def client_and_store() -> Iterator[tuple[TestClient, InMemoryRecordStore]]:
    app = create_app()
    store = InMemoryRecordStore()
    app.dependency_overrides[get_record_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client, store


class TestRecordsRouter:
    def test_export_rejects_unapproved_summary_actionably(self, client: TestClient) -> None:
        response = client.post(
            "/api/staff/records",
            json={"summary_id": "summary-1", "summary_status": "pending_review"},
        )

        assert response.status_code == 409
        assert "approve" in response.json()["detail"].lower()

    def test_download_missing_record_returns_actionable_404(self, client: TestClient) -> None:
        response = client.get("/api/staff/records/missing/download")

        assert response.status_code == 404
        assert "record" in response.json()["detail"].lower()

    def test_verify_route_returns_fingerprint_and_timestamp_metadata(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/staff/records/record-1/verify")

        assert response.status_code == 200
        body = response.json()
        assert body["audit_fingerprint"].startswith("sha256:")
        assert body["timestamp_proof"]["algorithm"] == "sha256"

    def test_verify_reports_verified_for_an_untouched_export(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        client, store = client_and_store
        record = _exported_record()
        store.create_record(record, artifact_bytes=record.pdf_bytes)

        response = client.get(f"/api/staff/records/{record.record_id}/verify")

        assert response.status_code == 200
        assert response.json()["status"] == "verified"

    def test_verify_detects_artifact_corruption_after_export(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        """Bit-rot / a bad migration / direct DB edit / a store bug can
        change the persisted artifact bytes after export. /verify must
        recompute the digest from the CURRENT artifact and catch that,
        instead of echoing back the status recorded at export time."""
        client, store = client_and_store
        record = _exported_record()
        store.create_record(record, artifact_bytes=record.pdf_bytes)
        # Simulate post-export corruption of the stored artifact.
        store._artifacts[record.record_id] = record.pdf_bytes + b"\x00corrupted"

        response = client.get(f"/api/staff/records/{record.record_id}/verify")

        assert response.status_code == 200
        assert response.json()["status"] == "failed"

    def test_verify_detects_tampered_timestamp_proof_token(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        """A corrupted or swapped-in-garbage timestamp_proof.token_der_b64
        (e.g. a bad migration touching the proof column) must also be
        caught, even when the artifact bytes themselves are untouched."""
        client, store = client_and_store
        record = _exported_record()
        store.create_record(record, artifact_bytes=record.pdf_bytes)
        tampered = record.model_copy(
            update={
                "timestamp_proof": record.timestamp_proof.model_copy(
                    update={"token_der_b64": "Z2FyYmFnZQ=="}
                )
            }
        )
        store._records[record.record_id] = tampered

        response = client.get(f"/api/staff/records/{record.record_id}/verify")

        assert response.status_code == 200
        assert response.json()["status"] == "failed"
