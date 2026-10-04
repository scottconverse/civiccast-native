# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regeneration against unchanged, actual migration tables; no HTTP/auth bypass."""

import importlib
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.captions import CaptionCue
from civiccast.summary.fingerprint import sha256_fingerprint
from civiccast.summary.generate import DeterministicSummaryModel, SummaryGenerationPipeline
from civiccast.summary.job import (
    InMemorySummaryGenerationJobStore,
    SummaryGenerationJobSettings,
    SummaryGenerationJobWorker,
    enqueue_summary_job,
)
from civiccast.summary.models import OperatorApproval
from civiccast.summary.persistence import PostgresSummaryGenerationJobStore
from civiccast.summary.store import (
    InMemorySummaryStore,
    PostgresSummaryStore,
    SummaryStoreConflictError,
)

NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.fixture(params=["memory", "migrated-sqlite"])
def stores(request, monkeypatch):
    if request.param == "memory":
        yield InMemorySummaryGenerationJobStore(), InMemorySummaryStore()
        return
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setitem(
        sqlite3.adapters, (datetime, sqlite3.PrepareProtocol), lambda value: value.isoformat()
    )
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        for name in ("0011_summary_v06", "0081_summary_generation_jobs"):
            importlib.import_module("civiccast.summary.migrations.versions." + name).upgrade()

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    try:
        yield PostgresSummaryGenerationJobStore(sessions), PostgresSummaryStore(sessions)
    finally:
        engine.dispose()


def cue(text):
    return CaptionCue(cue_id="cue-1", start_seconds=0, end_seconds=6, text=text, confidence=0.95)


def worker(jobs, summaries):
    return SummaryGenerationJobWorker(
        jobs,
        summaries,
        model_factory=DeterministicSummaryModel,
        settings=SummaryGenerationJobSettings(max_attempts=1),
    )


def test_successive_corrected_regeneration_preserves_old_approval(stores):
    jobs, summaries = stores
    old_ids = set()
    first = enqueue_summary_job(
        jobs, meeting_id="asset-1", cues=[cue("The council approved the budget.")], now=NOW
    )
    [completed] = worker(jobs, summaries).run_once(now=NOW)
    assert completed.state == "complete"
    old = summaries.get_summary(completed.summary_id)
    assert old is not None
    summaries.approve_summary(
        OperatorApproval(
            summary_id=old.summary_id,
            operator_id="synthetic-clerk",
            operator_display_name="Synthetic Clerk",
            approved_at=NOW,
            approval_note="Synthetic prior approval",
        )
    )
    before = summaries.get_summary(old.summary_id).model_dump(mode="json")
    approval_before = summaries.get_approval(old.summary_id).model_dump(mode="json")
    old_ids.update(c.claim_id for c in old.sourced_claims)
    for text in ("The council deferred the budget.", "The council rejected the budget."):
        fresh = enqueue_summary_job(jobs, meeting_id="asset-1", cues=[cue(text)], now=NOW)
        assert fresh.job_id != first.job_id
        duplicate = enqueue_summary_job(
            jobs, meeting_id="asset-1", cues=[cue("Ignored duplicate.")], now=NOW
        )
        assert duplicate.job_id == fresh.job_id
        [result] = worker(jobs, summaries).run_once(now=NOW)
        draft = summaries.get_summary(result.summary_id) if result.summary_id else None
        assert draft is not None, "completed job must link a persisted replacement draft"
        assert result.state == "complete" and result.last_error == ""
        assert draft.status == "pending_review" and draft.narrative == text
        assert summaries.get_approval(draft.summary_id) is None
        ids = {c.claim_id for c in draft.sourced_claims}
        assert ids.isdisjoint(old_ids)
        old_ids.update(ids)
        assert summaries.get_summary(old.summary_id).model_dump(mode="json") == before
        assert summaries.get_approval(old.summary_id).model_dump(mode="json") == approval_before
    assert len(summaries.list_review_items()) == 2
    assert len(summaries.list_review_items(include_approved=True)) == 3


@pytest.mark.parametrize("existing", ["absent", "different", "identical", "read-error"])
def test_conflict_only_recovers_actual_matching_draft(existing, stores):
    jobs, backing = stores

    class ConflictingStore:
        def create_summary(self, draft):
            if existing != "absent":
                backing.create_summary(
                    draft
                    if existing == "identical"
                    else draft.model_copy(update={"narrative": "Different persisted output"})
                )
            raise SummaryStoreConflictError("Synthetic insert conflict")

        def get_summary(self, summary_id):
            if existing == "read-error":
                raise RuntimeError("Synthetic persistence verification failure")
            return backing.get_summary(summary_id)

    summaries = ConflictingStore()
    enqueue_summary_job(
        jobs, meeting_id="asset-1", cues=[cue("The council deferred the budget.")], now=NOW
    )
    [result] = worker(jobs, summaries).run_once(now=NOW)
    if existing == "identical":
        assert result.state == "complete"
        assert summaries.get_summary(result.summary_id) is not None
    else:
        assert result.state == "failed"
        assert result.summary_id is None
        assert result.last_error


def test_generated_claim_identity_is_bounded_even_for_maximum_model_id():
    output = DeterministicSummaryModel().generate(
        meeting_id="asset-1",
        cues=[cue("The council deferred the budget.")],
        prompt_version="fixture",
    )
    output["sourced_claims"][0]["claim_id"] = "x" * 160
    first = SummaryGenerationPipeline(DeterministicSummaryModel([output])).generate(
        meeting_id="asset-1", cues=[cue("The council deferred the budget.")]
    )
    second = SummaryGenerationPipeline(DeterministicSummaryModel([output])).generate(
        meeting_id="asset-1", cues=[cue("The council deferred the budget.")]
    )
    assert first.sourced_claims[0].claim_id.startswith(first.summary_id + ":")
    assert len(first.sourced_claims[0].claim_id) <= 160
    assert first.sourced_claims[0].claim_id != second.sourced_claims[0].claim_id


def test_duplicate_model_local_ids_remain_distinct_persisted_claims(stores):
    _, summaries = stores
    output = DeterministicSummaryModel().generate(
        meeting_id="asset-1",
        cues=[cue("The council deferred the budget.")],
        prompt_version="fixture",
    )
    output["sourced_claims"] *= 2
    draft = SummaryGenerationPipeline(DeterministicSummaryModel([output])).generate(
        meeting_id="asset-1", cues=[cue("The council deferred the budget.")]
    )
    assert len({c.claim_id for c in draft.sourced_claims}) == 2
    summaries.create_summary(draft)
    assert summaries.get_summary(draft.summary_id) == draft


def test_existing_unscoped_record_and_export_metadata_are_unchanged(stores):
    from io import BytesIO

    import pikepdf

    from civiccast.records.pdfa import render_pdfa_record

    def attachments(pdf):
        with pikepdf.open(BytesIO(pdf)) as document:
            return {
                name: item.get_file().read_bytes() for name, item in document.attachments.items()
            }

    jobs, summaries = stores
    old = SummaryGenerationPipeline(DeterministicSummaryModel()).generate(
        meeting_id="asset-1", cues=[cue("The council approved the budget.")]
    )
    # Reproduce pre-repair durable data; never rewrite its IDs or audit fingerprint.
    old = old.model_copy(
        update={
            "sourced_claims": [old.sourced_claims[0].model_copy(update={"claim_id": "claim-1"})]
        }
    )
    old = old.model_copy(
        update={
            "audit_fingerprint": sha256_fingerprint(
                {
                    "meeting_id": old.meeting_id,
                    "status": old.status,
                    "narrative": old.narrative,
                    "sourced_claims": [
                        claim.model_dump(mode="json") for claim in old.sourced_claims
                    ],
                    "provenance": old.provenance.model_dump(mode="json"),
                    "errors": [],
                }
            )
        }
    )
    summaries.create_summary(old)
    approval = OperatorApproval(
        summary_id=old.summary_id,
        operator_id="synthetic-clerk",
        operator_display_name="Synthetic Clerk",
        approved_at=NOW,
    )
    summaries.approve_summary(approval)
    before = summaries.get_summary(old.summary_id)
    stored_approval = summaries.get_approval(old.summary_id)
    export_before = render_pdfa_record(before, approval=stored_approval)
    enqueue_summary_job(
        jobs, meeting_id="asset-1", cues=[cue("The council deferred the budget.")], now=NOW
    )
    [result] = worker(jobs, summaries).run_once(now=NOW)
    assert result.state == "complete"
    assert summaries.get_summary(result.summary_id) is not None
    assert summaries.get_summary(old.summary_id) == before
    assert summaries.get_approval(old.summary_id) == stored_approval
    export_after = render_pdfa_record(
        summaries.get_summary(old.summary_id), approval=summaries.get_approval(old.summary_id)
    )
    assert attachments(export_after) == attachments(export_before)
