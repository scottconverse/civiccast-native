# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the async summary generation job (field evidence 2026-08-29).

Candidate #17 (32GB CPU-only reference station): the synchronous
``POST /api/staff/summaries/generate`` 503'd at ~120s even on a warm model, because
Ollama's own completion (measured 94-366s+ on the same hardware class) cannot survive
one HTTP request/response cycle. This module proves the async job survives a slow
generation instead of discarding a completion the model actually produced -- the SAME
durable-queue-plus-worker shape the offline caption job (K3) already established.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from civiccast.ai_runtime.ollama_client import OllamaRuntimeUnavailableError
from civiccast.captions import CaptionCue
from civiccast.summary.generate import DeterministicSummaryModel
from civiccast.summary.job import (
    SUMMARY_JOB_STATE_COMPLETE,
    SUMMARY_JOB_STATE_FAILED,
    SUMMARY_JOB_STATE_PENDING,
    SUMMARY_JOB_STATE_RUNNING,
    InMemorySummaryGenerationJobStore,
    SummaryGenerationJobSettings,
    SummaryGenerationJobWorker,
    enqueue_summary_job,
)
from civiccast.summary.store import InMemorySummaryStore

_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _cue(cue_id: str = "cue-1", text: str = "The council approved the budget.") -> CaptionCue:
    return CaptionCue(cue_id=cue_id, start_seconds=0.0, end_seconds=6.0, text=text, confidence=0.95)


class _SlowModel:
    """A model whose ``generate`` takes as long as it needs -- the point is that the
    JOB never times it out the way the old synchronous HTTP request did. Real time
    is never actually slept in these tests; this fake just proves the pipeline runs
    to completion and the job records it, with no request/response clock involved."""

    def __init__(self, output: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self._output = output

    def generate(
        self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
    ) -> dict[str, Any]:
        self.calls += 1
        if self._output is not None:
            return self._output
        return {
            "narrative": cues[0].text if cues else "",
            "sourced_claims": [
                {
                    "claim_id": "claim-1",
                    "text": cues[0].text,
                    "claim_type": "narrative",
                    "transcript_ranges": [
                        {
                            "cue_id": cues[0].cue_id,
                            "start_seconds": cues[0].start_seconds,
                            "end_seconds": cues[0].end_seconds,
                        }
                    ],
                }
            ]
            if cues
            else [],
        }


class _UnavailableModel:
    def generate(
        self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
    ) -> dict[str, Any]:
        raise OllamaRuntimeUnavailableError("Local Ollama AI runtime is not reachable.")


class _CrashingModel:
    def generate(
        self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
    ) -> dict[str, Any]:
        raise RuntimeError("llama-server process has terminated: exit status 1")


def _worker(
    store: InMemorySummaryGenerationJobStore,
    summary_store: InMemorySummaryStore,
    model: Any,
    *,
    settings: SummaryGenerationJobSettings | None = None,
) -> SummaryGenerationJobWorker:
    return SummaryGenerationJobWorker(
        store,
        summary_store,
        model_factory=lambda: model,
        settings=settings or SummaryGenerationJobSettings(),
    )


class TestEnqueue:
    def test_enqueue_creates_a_pending_job(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        job = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)

        assert job.state == SUMMARY_JOB_STATE_PENDING
        assert job.meeting_id == "meeting-1"
        assert job.attempts == 0
        assert job.cues[0].cue_id == "cue-1"

    def test_enqueue_is_idempotent_per_meeting(self) -> None:
        # Field evidence context: an operator should never be able to start a
        # second multi-minute CPU generation for a meeting that already has one
        # in flight (e.g. a double-click on "Generate summary").
        store = InMemorySummaryGenerationJobStore()
        first = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        second = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)

        assert first.job_id == second.job_id
        assert len(store.list(meeting_id="meeting-1")) == 1

    def test_enqueue_allows_a_new_job_after_the_prior_one_completed(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        first = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        store.save(first.model_copy(update={"state": SUMMARY_JOB_STATE_COMPLETE}))

        second = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)

        assert second.job_id != first.job_id


class TestWorkerSuccess:
    def test_run_once_marks_running_then_complete_and_links_the_summary(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        job = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        worker = _worker(store, summary_store, _SlowModel())

        processed = worker.run_once(now=_NOW + timedelta(seconds=5))

        assert len(processed) == 1
        result = processed[0]
        assert result.job_id == job.job_id
        assert result.state == SUMMARY_JOB_STATE_COMPLETE
        assert result.summary_id is not None
        assert summary_store.get_summary(result.summary_id) is not None
        assert result.last_error == ""

    def test_a_refused_draft_still_counts_as_a_complete_job(self) -> None:
        # The pipeline's own evidence-citation gate (spec §4.2) can legitimately
        # produce status="refused" -- that is the pipeline working correctly, not
        # a job failure. See the SummaryGenerationJobRecord docstring.
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        # DeterministicSummaryModel with no scripted outputs and no quantitative
        # facts in the cues falls through to a narrative claim, so force a refusal
        # by returning sourced_claims that do not cite the supplied cue.
        bad_output = {
            "narrative": "made up text",
            "sourced_claims": [
                {
                    "claim_id": "claim-1",
                    "text": "made up text",
                    "claim_type": "narrative",
                    "transcript_ranges": [
                        {"cue_id": "not-a-real-cue", "start_seconds": 0.0, "end_seconds": 1.0}
                    ],
                }
            ],
        }
        worker = _worker(store, summary_store, _SlowModel(bad_output))

        [result] = worker.run_once(now=_NOW + timedelta(seconds=5))

        assert result.state == SUMMARY_JOB_STATE_COMPLETE
        assert result.summary_id is not None
        stored = summary_store.get_summary(result.summary_id)
        assert stored is not None
        assert stored.status == "refused"

    def test_model_factory_is_called_lazily_per_attempt(self) -> None:
        # Each attempt must pick up the operator's CURRENT model selection, not one
        # captured at worker-construction time.
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        built: list[int] = []

        def factory() -> Any:
            built.append(1)
            return _SlowModel()

        worker = SummaryGenerationJobWorker(
            store,
            summary_store,
            model_factory=factory,
            settings=SummaryGenerationJobSettings(),
        )
        worker.run_once(now=_NOW)

        assert built == [1]


class TestWorkerFailureAndRetry:
    def test_ollama_unavailable_is_retried_with_backoff(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        settings = SummaryGenerationJobSettings(backoff_seconds=60.0, max_attempts=3)
        worker = _worker(store, summary_store, _UnavailableModel(), settings=settings)

        [result] = worker.run_once(now=_NOW)

        assert result.state == SUMMARY_JOB_STATE_PENDING
        assert result.attempts == 1
        assert "not reachable" in result.last_error.lower()
        assert result.next_attempt_at == _NOW + timedelta(seconds=60)

    def test_a_crash_fails_after_the_attempt_budget_is_spent(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        settings = SummaryGenerationJobSettings(backoff_seconds=1.0, max_attempts=2)
        worker = _worker(store, summary_store, _CrashingModel(), settings=settings)

        # Attempt 1: fails, scheduled to retry.
        [after_first] = worker.run_once(now=_NOW)
        assert after_first.state == SUMMARY_JOB_STATE_PENDING
        assert after_first.attempts == 1

        # Attempt 2 (budget spent -> failed, terminal).
        [after_second] = worker.run_once(now=after_first.next_attempt_at)
        assert after_second.state == SUMMARY_JOB_STATE_FAILED
        assert after_second.attempts == 2
        assert after_second.next_attempt_at is None
        assert "llama-server" in after_second.last_error

    def test_run_once_only_touches_due_jobs(self) -> None:
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)
        settings = SummaryGenerationJobSettings(backoff_seconds=3600.0, max_attempts=5)
        worker = _worker(store, summary_store, _UnavailableModel(), settings=settings)

        worker.run_once(now=_NOW)  # schedules a retry ~1h later
        processed_too_soon = worker.run_once(now=_NOW + timedelta(minutes=1))

        assert processed_too_soon == []


class TestRunningStateIsVisibleDuringGeneration:
    def test_state_is_running_while_the_model_call_is_in_flight(self) -> None:
        # This is the actual product fix for the field evidence: an operator
        # polling job status during a multi-minute CPU generation must see
        # "running", not a static "pending" that looks stuck.
        store = InMemorySummaryGenerationJobStore()
        summary_store = InMemorySummaryStore()
        job = enqueue_summary_job(store, meeting_id="meeting-1", cues=[_cue()], now=_NOW)

        seen_state_during_call: list[str] = []

        class _ObservingModel:
            def generate(
                self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
            ) -> dict[str, Any]:
                current = store.get(job.job_id)
                assert current is not None
                seen_state_during_call.append(current.state)
                return DeterministicSummaryModel().generate(
                    meeting_id=meeting_id, cues=cues, prompt_version=prompt_version
                )

        worker = _worker(store, summary_store, _ObservingModel())
        worker.run_once(now=_NOW)

        assert seen_state_during_call == [SUMMARY_JOB_STATE_RUNNING]
