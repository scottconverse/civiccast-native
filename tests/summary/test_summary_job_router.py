# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP contract tests for the async summary generation job endpoints.

Field evidence (candidate #17): the synchronous POST /generate blocks the request
for as long as CPU-only generation takes (measured 94-366s+) and, pre-fix, 503'd at
~120s even when Ollama itself succeeded. These endpoints are the async path an
operator's console polls instead -- queue, list, get, and retry.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.captions import CaptionCue
from civiccast.summary.job import (
    SUMMARY_JOB_STATE_FAILED,
    SUMMARY_JOB_STATE_PENDING,
    InMemorySummaryGenerationJobStore,
    enqueue_summary_job,
)
from civiccast.summary.router import get_summary_job_store

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}
_CUE = {
    "cue_id": "cue-1",
    "start_seconds": 18.0,
    "end_seconds": 24.0,
    "text": "Motion passes 2-1.",
    "confidence": 0.96,
    "low_confidence": False,
}


@pytest.fixture
def job_store() -> InMemorySummaryGenerationJobStore:
    return InMemorySummaryGenerationJobStore()


@pytest.fixture
def client(job_store: InMemorySummaryGenerationJobStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_summary_job_store] = lambda: job_store
    with TestClient(app, headers=_STAFF_HEADERS) as test_client:
        yield test_client


class TestCreateSummaryJob:
    def test_queues_a_pending_job(self, client: TestClient) -> None:
        response = client.post(
            "/api/staff/summaries/jobs",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["state"] == SUMMARY_JOB_STATE_PENDING
        assert body["meeting_id"] == "meeting-1"
        assert body["cues"][0]["cue_id"] == "cue-1"

    def test_queuing_twice_for_the_same_meeting_returns_the_same_job(
        self, client: TestClient
    ) -> None:
        first = client.post(
            "/api/staff/summaries/jobs",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        ).json()
        second = client.post(
            "/api/staff/summaries/jobs",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        ).json()

        assert first["job_id"] == second["job_id"]

    def test_requires_records_clerk_or_support_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # meeting_operator is a real product role but neither of the two allowed
        # for this route -- same shape as tests/auth/test_sec1_staff_mutation_
        # role_403.py's existing "AI summaries" /generate case, extended to /jobs.
        token = "sec1-jobs-meeting-token-0000000000000"
        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS", f"{token}:meeting-op-1:Meeting Op:meeting_operator"
        )
        app = create_app()
        app.dependency_overrides[get_summary_job_store] = lambda: (
            InMemorySummaryGenerationJobStore()
        )
        with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
            response = client.post(
                "/api/staff/summaries/jobs",
                json={"meeting_id": "meeting-1", "cues": [_CUE]},
            )
        assert response.status_code == 403

    def test_returns_503_when_store_not_configured(self) -> None:
        app = create_app()
        app.dependency_overrides[get_summary_job_store] = lambda: None
        with TestClient(app, headers=_STAFF_HEADERS) as client:
            response = client.post(
                "/api/staff/summaries/jobs",
                json={"meeting_id": "meeting-1", "cues": [_CUE]},
            )
        assert response.status_code == 503


class TestListAndGetSummaryJobs:
    def test_list_filters_by_meeting_id(
        self, client: TestClient, job_store: InMemorySummaryGenerationJobStore
    ) -> None:
        enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )
        enqueue_summary_job(
            job_store, meeting_id="meeting-2", cues=[CaptionCue.model_validate(_CUE)]
        )

        response = client.get("/api/staff/summaries/jobs", params={"meeting_id": "meeting-1"})

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["meeting_id"] == "meeting-1"

    def test_get_one_job_by_id(
        self, client: TestClient, job_store: InMemorySummaryGenerationJobStore
    ) -> None:
        job = enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )

        response = client.get(f"/api/staff/summaries/jobs/{job.job_id}")

        assert response.status_code == 200
        assert response.json()["job_id"] == job.job_id

    def test_get_missing_job_is_404(self, client: TestClient) -> None:
        response = client.get("/api/staff/summaries/jobs/sgj_doesnotexist")
        assert response.status_code == 404


class TestRetrySummaryJob:
    def test_retry_resets_a_failed_job_to_pending(
        self, client: TestClient, job_store: InMemorySummaryGenerationJobStore
    ) -> None:
        job = enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )
        job_store.save(
            job.model_copy(
                update={"state": SUMMARY_JOB_STATE_FAILED, "attempts": 3, "last_error": "boom"}
            )
        )

        response = client.post(f"/api/staff/summaries/jobs/{job.job_id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == SUMMARY_JOB_STATE_PENDING
        assert body["attempts"] == 0
        assert body["last_error"] == ""

    def test_retry_a_non_failed_job_is_409(
        self, client: TestClient, job_store: InMemorySummaryGenerationJobStore
    ) -> None:
        job = enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )

        response = client.post(f"/api/staff/summaries/jobs/{job.job_id}/retry")

        assert response.status_code == 409

    def test_retry_missing_job_is_404(self, client: TestClient) -> None:
        response = client.post("/api/staff/summaries/jobs/sgj_doesnotexist/retry")
        assert response.status_code == 404

    def test_retry_conflicts_when_another_job_is_active_for_the_meeting(
        self, client: TestClient, job_store: InMemorySummaryGenerationJobStore
    ) -> None:
        failed = enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )
        job_store.save(failed.model_copy(update={"state": SUMMARY_JOB_STATE_FAILED, "attempts": 3}))
        # A fresh job took the active slot for this meeting in the meantime.
        enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )

        response = client.post(f"/api/staff/summaries/jobs/{failed.job_id}/retry")

        assert response.status_code == 409

    def test_retry_requires_records_clerk(
        self, job_store: InMemorySummaryGenerationJobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # support_admin can queue a job (POST /jobs allows it) but retry is
        # records_clerk-only, same as captions.router.retry_offline_caption_job.
        job = enqueue_summary_job(
            job_store, meeting_id="meeting-1", cues=[CaptionCue.model_validate(_CUE)]
        )
        job_store.save(job.model_copy(update={"state": SUMMARY_JOB_STATE_FAILED}))

        token = "sec1-jobs-support-token-0000000000000"
        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS", f"{token}:support-1:Support Admin:support_admin"
        )
        app = create_app()
        app.dependency_overrides[get_summary_job_store] = lambda: job_store
        with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
            response = client.post(f"/api/staff/summaries/jobs/{job.job_id}/retry")
        assert response.status_code == 403
