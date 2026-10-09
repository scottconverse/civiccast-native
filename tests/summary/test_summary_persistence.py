# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence contract tests for v0.6 sourced summaries."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from civiccast.summary.models import (
    ModelProvenance,
    OperatorApproval,
    SourcedClaim,
    SummaryDraft,
    TranscriptRange,
)
from civiccast.summary.store import (
    InMemorySummaryStore,
    PostgresSummaryStore,
    SummaryStoreConflictError,
)


def _summary() -> SummaryDraft:
    return SummaryDraft(
        summary_id="summary-1",
        meeting_id="meeting-1",
        status="pending_review",
        narrative="The motion passed 2-1.",
        sourced_claims=[
            SourcedClaim(
                claim_id="claim-1",
                text="The motion passed 2-1.",
                claim_type="quantitative",
                transcript_ranges=[
                    TranscriptRange(cue_id="cue-1", start_seconds=18.0, end_seconds=24.0)
                ],
            )
        ],
        provenance=ModelProvenance(
            model_tag="gemma3:latest",
            model_digest="sha256:abc123",
            ollama_version="0.9.0",
            prompt_version="summary-v0.6",
            extraction_version="summary-extract-v0.6",
            runtime_parameters={"temperature": 0},
            generated_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        ),
        audit_fingerprint="sha256:" + ("b" * 64),
    )


class TestSummaryStoreContract:
    def test_summary_claims_provenance_and_fingerprint_round_trip_in_memory(self) -> None:
        store = InMemorySummaryStore()

        stored = store.create_summary(_summary())
        found = store.get_summary("summary-1")

        assert found == stored
        assert found.sourced_claims[0].transcript_ranges[0].cue_id == "cue-1"
        assert found.provenance.prompt_version == "summary-v0.6"
        assert found.audit_fingerprint.startswith("sha256:")

    def test_approval_metadata_round_trips_without_rewriting_summary_claims(self) -> None:
        store = InMemorySummaryStore()
        store.create_summary(_summary())
        approval = OperatorApproval(
            summary_id="summary-1",
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_at=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
            approval_note="Checked against transcript.",
        )

        approved = store.approve_summary(
            approval, expected_audit_fingerprint=_summary().audit_fingerprint
        )

        assert approved.status == "approved"
        assert store.get_approval("summary-1") == approval
        assert approved.sourced_claims[0].text == "The motion passed 2-1."

    def test_duplicate_summary_id_is_conflict(self) -> None:
        store = InMemorySummaryStore()
        store.create_summary(_summary())

        with pytest.raises(SummaryStoreConflictError, match="summary-1"):
            store.create_summary(_summary())

    def test_edit_changes_fingerprint_and_refuses_stale_or_approved_drafts(self) -> None:
        store = InMemorySummaryStore()
        original = store.create_summary(_summary())

        edited = store.edit_summary(
            original.summary_id,
            narrative="The council approved the motion 2-1.",
            expected_audit_fingerprint=original.audit_fingerprint,
        )

        assert edited.narrative == "The council approved the motion 2-1."
        assert edited.audit_fingerprint != original.audit_fingerprint
        assert edited.sourced_claims == original.sourced_claims
        with pytest.raises(SummaryStoreConflictError, match="changed or is no longer pending"):
            store.edit_summary(
                original.summary_id,
                narrative="Stale version.",
                expected_audit_fingerprint=original.audit_fingerprint,
            )

        approval = OperatorApproval(
            summary_id=original.summary_id,
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_at=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
        )
        store.approve_summary(approval, expected_audit_fingerprint=edited.audit_fingerprint)
        with pytest.raises(SummaryStoreConflictError, match="changed or is no longer pending"):
            store.edit_summary(
                original.summary_id,
                narrative="Approved drafts are immutable.",
                expected_audit_fingerprint=edited.audit_fingerprint,
            )

    def test_durable_edit_persists_and_approval_rejects_concurrent_change(
        self, tmp_path: Path
    ) -> None:
        engine = create_engine(f"sqlite:///{(tmp_path / 'summaries.db').as_posix()}", future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE summaries (summary_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, "
                    "status TEXT NOT NULL, narrative TEXT NOT NULL, provenance_json TEXT NOT NULL, "
                    "audit_fingerprint TEXT NOT NULL, operator_message TEXT, created_at DATETIME NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE sourced_claims (claim_id TEXT PRIMARY KEY, summary_id TEXT NOT NULL, "
                    "claim_type TEXT NOT NULL, text TEXT NOT NULL, transcript_ranges_json TEXT NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE summary_approvals (summary_id TEXT PRIMARY KEY, "
                    "operator_id TEXT NOT NULL, operator_display_name TEXT NOT NULL, "
                    "approved_at DATETIME NOT NULL, approval_note TEXT)"
                )
            )

        @contextmanager
        def session_factory() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        store = PostgresSummaryStore(session_factory)
        original = _summary()
        approved = _summary().model_copy(
            update={"summary_id": "summary-approved", "status": "approved"}
        )
        with session_factory() as session:
            for summary in (original, approved):
                session.execute(
                    text(
                        "INSERT INTO summaries (summary_id, meeting_id, status, narrative, "
                        "provenance_json, audit_fingerprint, operator_message, created_at) "
                        "VALUES (:summary_id, :meeting_id, :status, :narrative, :provenance_json, "
                        ":audit_fingerprint, :operator_message, :created_at)"
                    ),
                    {
                        "summary_id": summary.summary_id,
                        "meeting_id": summary.meeting_id,
                        "status": summary.status,
                        "narrative": summary.narrative,
                        "provenance_json": summary.provenance.model_dump_json(),
                        "audit_fingerprint": summary.audit_fingerprint,
                        "operator_message": summary.operator_message,
                        "created_at": "2026-05-14T12:00:00+00:00",
                    },
                )
                for claim in summary.sourced_claims:
                    session.execute(
                        text(
                            "INSERT INTO sourced_claims (claim_id, summary_id, claim_type, text, "
                            "transcript_ranges_json) VALUES (:claim_id, :summary_id, :claim_type, "
                            ":claim_text, :ranges)"
                        ),
                        {
                            "claim_id": claim.claim_id
                            + ("-approved" if summary.status == "approved" else ""),
                            "summary_id": summary.summary_id,
                            "claim_type": claim.claim_type,
                            "claim_text": claim.text,
                            "ranges": json.dumps(
                                [
                                    cue_range.model_dump(mode="json")
                                    for cue_range in claim.transcript_ranges
                                ],
                                sort_keys=True,
                            ),
                        },
                    )
            session.commit()

        edited = store.edit_summary(
            original.summary_id,
            narrative="The council approved the motion 2-1.",
            expected_audit_fingerprint=original.audit_fingerprint,
        )

        assert store.get_summary(original.summary_id) == edited
        listed = store.list_review_items()
        assert {summary.summary_id for summary in listed} == {"summary-1", "summary-approved"}
        assert (
            next(summary for summary in listed if summary.summary_id == "summary-approved").status
            == "approved"
        )
        approval = OperatorApproval(
            summary_id=original.summary_id,
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_at=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
        )
        with pytest.raises(SummaryStoreConflictError, match="Reload"):
            store.approve_summary(approval, expected_audit_fingerprint=original.audit_fingerprint)
        assert store.get_approval(original.summary_id) is None

        # Commit a competing edit on a separate connection immediately before
        # the approval UPDATE reaches SQLite. A pre-read guard alone loses here.
        interleaved = False

        @event.listens_for(engine, "before_cursor_execute")
        def edit_before_approval(conn, cursor, statement, parameters, context, executemany):
            nonlocal interleaved
            if not interleaved and "SET status = 'approved'" in statement:
                interleaved = True
                store.edit_summary(
                    original.summary_id,
                    narrative="A competing clerk saved this before approval committed.",
                    expected_audit_fingerprint=edited.audit_fingerprint,
                )

        with pytest.raises(SummaryStoreConflictError, match="Reload"):
            store.approve_summary(approval, expected_audit_fingerprint=edited.audit_fingerprint)
        assert interleaved
        assert store.get_approval(original.summary_id) is None
        current = store.get_summary(original.summary_id)
        assert current.status == "pending_review"
        assert current.narrative == "A competing clerk saved this before approval committed."

        approved_current = store.approve_summary(
            approval, expected_audit_fingerprint=current.audit_fingerprint
        )
        assert approved_current.status == "approved"
        assert approved_current.audit_fingerprint == current.audit_fingerprint
        assert store.get_approval(original.summary_id) == approval
        with pytest.raises(SummaryStoreConflictError, match="Reload"):
            store.approve_summary(
                approval.model_copy(update={"operator_id": "different-clerk"}),
                expected_audit_fingerprint=current.audit_fingerprint,
            )
        assert store.get_approval(original.summary_id) == approval
        with pytest.raises(SummaryStoreConflictError):
            store.edit_summary(
                original.summary_id,
                narrative="Cannot overwrite approved content.",
                expected_audit_fingerprint=current.audit_fingerprint,
            )
        engine.dispose()
