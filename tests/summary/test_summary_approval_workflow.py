# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Approval and post-approval discovery through the actual authenticated API."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.app import create_app
from civiccast.records.router import get_record_store
from civiccast.records.store import InMemoryRecordStore
from civiccast.summary.models import OperatorApproval
from civiccast.summary.router import get_summary_store
from civiccast.summary.store import InMemorySummaryStore, PostgresSummaryStore
from tests.summary.test_summary_persistence import _summary


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path, monkeypatch):
    if request.param == "memory":
        yield InMemorySummaryStore()
        return
    # Python 3.12 deprecated its implicit datetime adapter. Provide the test
    # SQLite driver's explicit ISO adapter, restored by monkeypatch at teardown.
    monkeypatch.setitem(
        sqlite3.adapters, (datetime, sqlite3.PrepareProtocol), lambda value: value.isoformat()
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'summaries.sqlite3'}")
    migration = import_module("civiccast.summary.migrations.versions.0011_summary_v06")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    try:
        yield PostgresSummaryStore(sessions)
    finally:
        engine.dispose()


@pytest.fixture
def client(store):
    app = create_app()
    app.dependency_overrides[get_summary_store] = lambda: store
    record_store = InMemoryRecordStore()
    app.dependency_overrides[get_record_store] = lambda: record_store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
        yield client


def test_approved_item_survives_explicit_refetch_without_changing_default_queue(client, store):
    store.create_summary(_summary())
    response = client.post(
        "/api/staff/summaries/summary-1/approve", json={"approval_note": "Checked cues."}
    )
    assert response.status_code == 200
    assert client.get("/api/staff/summaries/review-items").json()["items"] == []
    # A fresh request uses persisted state, not an optimistic client-only cache.
    items = client.get("/api/staff/summaries/review-items?include_approved=true").json()["items"]
    assert [(item["summary_id"], item["status"]) for item in items] == [("summary-1", "approved")]
    assert store.get_approval("summary-1").operator_id == "operator-token-a"
    assert store.get_approval("summary-1").operator_display_name == "Token Identity A"


def test_default_queue_preserves_nested_draft_defaults(client, store):
    draft = _summary()
    store.create_summary(draft)
    assert client.get("/api/staff/summaries/review-items").json() == {
        "items": [draft.model_dump(mode="json")],
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"status": "refused"},
        {"status": "rejected"},
        {"sourced_claims": []},
        {
            "sourced_claims": [
                _summary()
                .sourced_claims[0]
                .model_copy(update={"claim_type": "narrative", "transcript_ranges": []})
            ]
        },
    ],
)
def test_invalid_draft_cannot_be_persisted_as_approved(client, store, change):
    draft = _summary().model_copy(update=change)
    store.create_summary(draft)
    response = client.post("/api/staff/summaries/summary-1/approve", json={})
    assert response.status_code == 409
    assert store.get_summary("summary-1").status == draft.status
    assert store.get_approval("summary-1") is None


def test_client_cannot_supply_approval_identity(client, store):
    store.create_summary(_summary())
    response = client.post(
        "/api/staff/summaries/summary-1/approve",
        json={
            "operator_id": "forged",
            "operator_display_name": "Forged Clerk",
            "approval_note": "Checked cues.",
        },
    )
    assert response.status_code == 422
    assert store.get_approval("summary-1") is None


def test_unknown_token_cannot_approve(client, store):
    store.create_summary(_summary())
    response = client.post(
        "/api/staff/summaries/summary-1/approve",
        json={},
        headers={"Authorization": "Bearer unknown-test-token"},
    )
    assert response.status_code == 401
    assert store.get_approval("summary-1") is None


def test_non_clerk_cannot_approve(client, store, monkeypatch):
    store.create_summary(_summary())
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "workflow-test-token:meeting-op:Meeting Operator:meeting_operator"
    )
    response = client.post(
        "/api/staff/summaries/summary-1/approve",
        json={},
        headers={"Authorization": "Bearer workflow-test-token"},
    )
    assert response.status_code == 403
    assert store.get_approval("summary-1") is None


@pytest.mark.parametrize(
    "claims",
    [
        [],
        [
            _summary()
            .sourced_claims[0]
            .model_copy(update={"claim_type": "narrative", "transcript_ranges": []})
        ],
    ],
)
def test_existing_approved_invalid_data_cannot_bypass_evidence_gate(client, store, claims):
    store.create_summary(
        _summary().model_copy(update={"status": "approved", "sourced_claims": claims})
    )
    response = client.post("/api/staff/records", json={"summary_id": "summary-1"})
    assert response.status_code == 409
    assert "source" in response.json()["detail"].lower()


@pytest.mark.parametrize("mismatched", [False, True])
def test_fresh_export_requires_matching_persisted_approval_and_authenticated_recovery(
    client, store, monkeypatch, mismatched
):
    store.create_summary(_summary().model_copy(update={"status": "approved"}))
    original_get_approval = store.get_approval
    if mismatched:
        other = _summary().model_copy(update={"summary_id": "other"})
        other.sourced_claims = [
            other.sourced_claims[0].model_copy(update={"claim_id": "other-claim"})
        ]
        store.create_summary(other)
        store.approve_summary(
            OperatorApproval(
                summary_id="other",
                operator_id="real-other-clerk",
                operator_display_name="Other Clerk",
                approved_at=datetime.fromisoformat("2026-10-03T00:00:00+00:00"),
            )
        )
        # Simulate an adapter misbinding a real persisted approval to the wrong summary.
        monkeypatch.setattr(store, "get_approval", lambda _: original_get_approval("other"))
    response = client.post("/api/staff/records", json={"summary_id": "summary-1"})
    assert response.status_code == 409
    assert "reapprove" in response.json()["detail"].lower()
    queue = client.get("/api/staff/summaries/review-items?include_approved=true").json()
    assert "summary-1" in queue["approval_required_summary_ids"]
    monkeypatch.setattr(store, "get_approval", original_get_approval)
    assert original_get_approval("summary-1") is None
    recovery = client.post(
        "/api/staff/summaries/summary-1/approve",
        json={"approval_note": "Explicit recovery after cue review."},
    )
    assert recovery.status_code == 200
    approval = original_get_approval("summary-1")
    assert approval.summary_id == "summary-1"
    assert approval.operator_id == "operator-token-a"
    assert (
        client.get("/api/staff/summaries/review-items?include_approved=true").json()[
            "approval_required_summary_ids"
        ]
        == []
    )
    assert client.post("/api/staff/records", json={"summary_id": "summary-1"}).status_code == 201


def test_review_approval_lookup_failure_does_not_invent_reapproval_state(
    client, store, monkeypatch
):
    store.create_summary(_summary().model_copy(update={"status": "approved"}))

    def failed_lookup(_):
        raise RuntimeError("Approval lookup unavailable")

    monkeypatch.setattr(store, "get_approval", failed_lookup)
    with pytest.raises(RuntimeError, match="Approval lookup unavailable"):
        client.get("/api/staff/summaries/review-items?include_approved=true")
