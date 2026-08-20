# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for v0.6 sourced summary data models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from civiccast.summary.models import (
    ModelProvenance,
    OperatorApproval,
    SourcedClaim,
    SummaryDraft,
    TranscriptRange,
)


class TestSummaryModels:
    def test_transcript_range_requires_forward_time(self) -> None:
        with pytest.raises(ValidationError, match="end_seconds"):
            TranscriptRange(cue_id="cue-1", start_seconds=12.0, end_seconds=12.0)

    def test_sourced_claim_requires_timestamp_range_for_quantitative_claim(self) -> None:
        with pytest.raises(ValidationError, match=r"quantitative.*source"):
            SourcedClaim(
                claim_id="claim-1",
                text="The motion passed 4-1.",
                claim_type="quantitative",
                transcript_ranges=[],
            )

    def test_summary_draft_is_closed_contract_with_required_provenance(self) -> None:
        provenance = ModelProvenance(
            model_tag="gemma3:latest",
            model_digest="sha256:abc123",
            ollama_version="0.9.0",
            prompt_version="summary-v0.6",
            extraction_version="summary-extract-v0.6",
            runtime_parameters={"temperature": 0, "top_p": 0.1},
            generated_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        )
        claim = SourcedClaim(
            claim_id="claim-1",
            text="The motion passed 4-1.",
            claim_type="quantitative",
            transcript_ranges=[
                TranscriptRange(cue_id="cue-2", start_seconds=35.0, end_seconds=42.0)
            ],
        )

        draft = SummaryDraft(
            summary_id="summary-1",
            meeting_id="meeting-1",
            status="pending_review",
            narrative="The council approved the zoning motion.",
            sourced_claims=[claim],
            provenance=provenance,
            audit_fingerprint="sha256:" + ("a" * 64),
        )

        assert draft.model_config["extra"] == "forbid"
        assert draft.sourced_claims[0].transcript_ranges[0].cue_id == "cue-2"

    def test_operator_approval_requires_human_metadata(self) -> None:
        with pytest.raises(ValidationError, match="operator"):
            OperatorApproval(summary_id="summary-1", approved_at=datetime.now(UTC))
