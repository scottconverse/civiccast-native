# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence contract tests for v0.6 sourced summaries."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.summary.models import (
    ModelProvenance,
    OperatorApproval,
    SourcedClaim,
    SummaryDraft,
    TranscriptRange,
)
from civiccast.summary.store import InMemorySummaryStore, SummaryStoreConflictError


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

        approved = store.approve_summary(approval)

        assert approved.status == "approved"
        assert store.get_approval("summary-1") == approval
        assert approved.sourced_claims[0].text == "The motion passed 2-1."

    def test_duplicate_summary_id_is_conflict(self) -> None:
        store = InMemorySummaryStore()
        store.create_summary(_summary())

        with pytest.raises(SummaryStoreConflictError, match="summary-1"):
            store.create_summary(_summary())
