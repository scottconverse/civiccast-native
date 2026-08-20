# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI contract tests for v0.6 sourced summary routes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from civiccast.ai_runtime.ollama_client import OllamaRuntimeUnavailableError
from civiccast.app import create_app
from civiccast.captions import CaptionCue
from civiccast.summary.generate import DeterministicSummaryModel
from civiccast.summary.router import get_summary_model, get_summary_store
from civiccast.summary.store import InMemorySummaryStore


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = InMemorySummaryStore()
    app.dependency_overrides[get_summary_store] = lambda: store
    app.dependency_overrides[get_summary_model] = lambda: DeterministicSummaryModel()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


class TestSummaryRouter:
    def test_empty_review_queue_returns_stable_success_shape(self, client: TestClient) -> None:
        response = client.get("/api/staff/summaries/review-items")

        assert response.status_code == 200
        assert response.json() == {"items": [], "next_cursor": None}

    def test_generate_summary_returns_pending_review_with_sourced_claim_links(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/staff/summaries/generate",
            json={
                "meeting_id": "meeting-1",
                "cues": [
                    {
                        "cue_id": "cue-1",
                        "start_seconds": 18.0,
                        "end_seconds": 24.0,
                        "text": "Motion passes 2-1.",
                        "confidence": 0.96,
                        "low_confidence": False,
                    }
                ],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending_review"
        assert body["sourced_claims"][0]["transcript_ranges"][0]["cue_id"] == "cue-1"

    def test_generate_summary_returns_clean_503_when_ollama_unreachable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ollama daemon down at model-selection time is a clean 503, not a raw 500.

        Exercises the real ``get_summary_model`` dependency (not a test double)
        by making the underlying ``OllamaSummaryModel.for_release()`` call raise,
        the way it does when the local Ollama daemon isn't running.
        """

        def _raise_unavailable(**_: Any) -> DeterministicSummaryModel:
            raise OllamaRuntimeUnavailableError(
                "Local Ollama request failed. Start Ollama and retry."
            )

        del client.app.dependency_overrides[get_summary_model]
        monkeypatch.setattr(
            "civiccast.summary.router.OllamaSummaryModel.for_release", _raise_unavailable
        )
        try:
            response = client.post(
                "/api/staff/summaries/generate",
                json={"meeting_id": "meeting-1", "cues": []},
            )
        finally:
            client.app.dependency_overrides[get_summary_model] = lambda: DeterministicSummaryModel()

        assert response.status_code == 503
        assert "ollama" in response.json()["detail"].lower()

    def test_generate_summary_returns_clean_503_when_ollama_fails_mid_generation(
        self, client: TestClient
    ) -> None:
        """Ollama failing during the actual generate call is also a clean 503."""

        class _FlakyModel:
            def generate(
                self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
            ) -> dict[str, Any]:
                raise OllamaRuntimeUnavailableError(
                    "Local Ollama request failed for /api/generate. Start Ollama and retry."
                )

        client.app.dependency_overrides[get_summary_model] = lambda: _FlakyModel()
        try:
            response = client.post(
                "/api/staff/summaries/generate",
                json={"meeting_id": "meeting-1", "cues": []},
            )
        finally:
            client.app.dependency_overrides[get_summary_model] = lambda: DeterministicSummaryModel()

        assert response.status_code == 503
        assert "ollama" in response.json()["detail"].lower()

    def test_approve_rejects_missing_summary_actionably(self, client: TestClient) -> None:
        response = client.post(
            "/api/staff/summaries/missing/approve",
            json={},
        )

        assert response.status_code == 404
        assert "summary" in response.json()["detail"].lower()

    def test_csv_export_preserves_partial_low_confidence_state(self, client: TestClient) -> None:
        response = client.post(
            "/api/staff/summaries/transcript.csv",
            json={
                "meeting_id": "meeting-1",
                "cues": [
                    {
                        "cue_id": "cue-1",
                        "start_seconds": 0.0,
                        "end_seconds": 4.0,
                        "text": "unclear speaker",
                        "confidence": 0.51,
                        "low_confidence": True,
                    }
                ],
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "low_confidence" in response.text.splitlines()[0]
        assert "true" in response.text.lower()
