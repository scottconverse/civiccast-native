# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI contract tests for v0.6 signed-record routes."""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

from civiccast.app import create_app
from civiccast.auth.models import OperatorIdentity
from civiccast.records.exporter import SignedRecordExporter
from civiccast.records.models import RecordExportResponse
from civiccast.records.pdfa import PDFA_FONT_NAME
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
    def test_long_summary_narrative_is_paginated_and_verifies(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        client, store = client_and_store
        narrative = " ".join(
            f"The council reviewed agenda item {index} and recorded its decision."
            for index in range(400)
        )
        summary = _summary().model_copy(
            update={
                "summary_id": "summary-long-narrative",
                "meeting_id": "meeting-long-narrative",
                "status": "approved",
                "narrative": narrative,
            }
        )
        summary_store = InMemorySummaryStore()
        summary_store.create_summary(summary)
        exporter = SignedRecordExporter(
            summary_store=summary_store,
            timestamp_authority=DeterministicTimestampAuthority(),
        )
        record = exporter.export(
            summary_id=summary.summary_id,
            operator_identity=_TEST_OPERATOR,
        )
        store.create_record(record, artifact_bytes=record.pdf_bytes)

        pages = PdfReader(BytesIO(record.pdf_bytes)).pages
        rendered_text = " ".join(
            " ".join((page.extract_text() or "").split()) for page in pages
        ).replace("CivicCast PDF/A-3B signed-record export (continued)", "")
        narrative_start = rendered_text.find(narrative.split()[0])
        rendered_narrative = rendered_text[narrative_start:].split()

        assert len(pages) > 1
        assert rendered_narrative == narrative.split()
        assert summary.audit_fingerprint in rendered_text
        out_of_bounds: list[str] = []
        for page_number, page in enumerate(pages, start=1):

            def check_text_bounds(
                text: str,
                _cm: object,
                text_matrix: tuple[float, ...],
                _font: object,
                font_size: float,
                current_page: int = page_number,
            ) -> None:
                if not text.strip():
                    return
                x, y = text_matrix[4], text_matrix[5]
                right = x + pdfmetrics.stringWidth(text, PDFA_FONT_NAME, font_size)
                if x < 71.5 or right > 540.5 or y < 81.5 or y > 740.5:
                    out_of_bounds.append(
                        f"page {current_page}: text at ({x:.1f}, {y:.1f}) reaches x={right:.1f}"
                    )

            page.extract_text(visitor_text=check_text_bounds)
        assert not out_of_bounds, "; ".join(out_of_bounds)
        verified = client.get(f"/api/staff/records/{record.record_id}/verify")
        assert verified.status_code == 200
        assert verified.json()["status"] == "verified"

    def test_list_returns_previously_exported_records(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        client, store = client_and_store
        record = _exported_record()
        store.create_record(record, artifact_bytes=record.pdf_bytes)

        response = client.get("/api/staff/records")

        assert response.status_code == 200
        assert [item["record_id"] for item in response.json()] == [record.record_id]

    def test_list_is_filtered_by_summary_and_limited(
        self, client_and_store: tuple[TestClient, InMemoryRecordStore]
    ) -> None:
        client, store = client_and_store
        first = _exported_record("summary-1")
        second = _exported_record("summary-2")
        store.create_record(first, artifact_bytes=first.pdf_bytes)
        store.create_record(second, artifact_bytes=second.pdf_bytes)

        response = client.get("/api/staff/records", params={"summary_id": "summary-2", "limit": 1})

        assert response.status_code == 200
        assert [item["record_id"] for item in response.json()] == [second.record_id]
        assert "pdf_bytes" not in response.json()[0]

    def test_list_download_and_verify_require_records_clerk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS",
            "meeting-token:meeting-user:Meeting User:meeting_operator",
        )
        app = create_app()
        with TestClient(app, headers={"Authorization": "Bearer meeting-token"}) as client:
            paths = (
                "/api/staff/records",
                "/api/staff/records/record-1/download",
                "/api/staff/records/record-1/verify",
            )
            for path in paths:
                assert client.get(path).status_code == 403

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
