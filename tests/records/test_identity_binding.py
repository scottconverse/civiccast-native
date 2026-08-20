# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff identity binding tests for signed-record audit fingerprints."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import civiccast.records.exporter as exporter_module
from civiccast.app import create_app
from civiccast.records.router import get_record_store
from civiccast.records.store import InMemoryRecordStore
from civiccast.summary.models import OperatorApproval
from civiccast.summary.router import get_summary_store
from civiccast.summary.store import InMemorySummaryStore
from tests.summary.test_summary_persistence import _summary


class _FixedUuid:
    hex = "0" * 32


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    summary_store = InMemorySummaryStore()
    summary = _summary().model_copy(update={"status": "approved"})
    summary_store.create_summary(summary)
    summary_store.approve_summary(
        OperatorApproval(
            summary_id=summary.summary_id,
            operator_id="operator-token-a",
            operator_display_name="Token Identity A",
            approved_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            approval_note="Approved by authenticated token identity.",
        )
    )
    monkeypatch.setattr(exporter_module, "uuid4", lambda: _FixedUuid())

    app = create_app()
    app.dependency_overrides[get_summary_store] = lambda: summary_store
    app.dependency_overrides[get_record_store] = lambda: InMemoryRecordStore()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def test_export_fingerprint_uses_bearer_identity_not_spoofed_payload(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/staff/records",
        headers={"Authorization": "Bearer operator-token-a"},
        json={
            "summary_id": "summary-1",
            "summary_status": "approved",
            "requested_by": "operator-spoof-b",
        },
    )

    if response.status_code in {400, 422}:
        detail = str(response.json()).lower()
        assert "requested_by" in detail or "identity" in detail or "operator" in detail
        return

    assert response.status_code == 201
    body = response.json()
    expected_material = (
        f"{_summary().audit_fingerprint}:record-{'0' * 32}:operator-token-a:"
        f"operator-token-a:{body['timestamp_proof']['artifact_digest'].removeprefix('sha256:')}"
    )
    expected_fingerprint = hashlib.sha256(expected_material.encode("utf-8")).hexdigest()

    assert body["audit_fingerprint"] == f"{_summary().audit_fingerprint}:{expected_fingerprint}"
