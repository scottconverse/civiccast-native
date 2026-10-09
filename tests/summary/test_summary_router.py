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

_CUE = {
    "cue_id": "cue-1",
    "start_seconds": 18.0,
    "end_seconds": 24.0,
    "text": "Motion passes 2-1.",
    "confidence": 0.96,
    "low_confidence": False,
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = InMemorySummaryStore()
    app.dependency_overrides[get_summary_store] = lambda: store
    app.dependency_overrides[get_summary_model] = lambda: DeterministicSummaryModel()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


class TestSummaryRouter:
    def test_approval_requires_displayed_fingerprint_and_rejects_unseen_edit(
        self, client: TestClient
    ) -> None:
        draft = client.post(
            "/api/staff/summaries/generate",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        ).json()
        route = f"/api/staff/summaries/{draft['summary_id']}"
        assert client.post(f"{route}/approve", json={}).status_code == 422
        edited = client.patch(
            route,
            json={
                "narrative": "Another clerk corrected this narrative.",
                "expected_audit_fingerprint": draft["audit_fingerprint"],
            },
        )
        assert edited.status_code == 200
        stale = client.post(
            f"{route}/approve",
            json={"expected_audit_fingerprint": draft["audit_fingerprint"]},
        )
        assert stale.status_code == 409
        assert "reload" in stale.json()["detail"].lower()
        store = client.app.dependency_overrides[get_summary_store]()
        assert store.get_approval(draft["summary_id"]) is None
        assert store.get_summary(draft["summary_id"]).status == "pending_review"
        current = client.post(
            f"{route}/approve",
            json={"expected_audit_fingerprint": edited.json()["audit_fingerprint"]},
        )
        assert current.status_code == 200
        assert current.json()["narrative"] == edited.json()["narrative"]
        assert (
            client.post(
                f"{route}/approve",
                json={"expected_audit_fingerprint": edited.json()["audit_fingerprint"]},
            ).status_code
            == 409
        )

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
            json={"expected_audit_fingerprint": "sha256:" + "0" * 64},
        )

        assert response.status_code == 404
        assert "summary" in response.json()["detail"].lower()

    def test_approved_summary_remains_available_and_uses_authenticated_identity(
        self, client: TestClient
    ) -> None:
        generated = client.post(
            "/api/staff/summaries/generate",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        )
        assert generated.status_code == 201
        summary_id = generated.json()["summary_id"]

        rejected = client.post(
            f"/api/staff/summaries/{summary_id}/approve",
            json={
                "operator_id": "spoofed",
                "operator_display_name": "Spoofed",
                "expected_audit_fingerprint": generated.json()["audit_fingerprint"],
            },
        )
        assert rejected.status_code == 422

        approved = client.post(
            f"/api/staff/summaries/{summary_id}/approve",
            json={"expected_audit_fingerprint": generated.json()["audit_fingerprint"]},
        )
        identity = client.get("/api/staff/auth/me").json()
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        stored = client.app.dependency_overrides[get_summary_store]()
        approval = stored.get_approval(summary_id)
        assert approval is not None
        assert approval.operator_id == identity["operator_id"]
        assert approval.operator_display_name == identity["operator_display_name"]

        listed = client.get("/api/staff/summaries/review-items")
        assert listed.status_code == 200
        assert any(
            item["summary_id"] == summary_id and item["status"] == "approved"
            for item in listed.json()["items"]
        )

    def test_edit_updates_narrative_and_fingerprint_only_while_pending(
        self, client: TestClient
    ) -> None:
        generated = client.post(
            "/api/staff/summaries/generate",
            json={"meeting_id": "meeting-1", "cues": [_CUE]},
        )
        assert generated.status_code == 201
        draft = generated.json()

        edited = client.patch(
            f"/api/staff/summaries/{draft['summary_id']}",
            json={
                "narrative": "The council approved the motion 2-1.",
                "expected_audit_fingerprint": draft["audit_fingerprint"],
            },
        )

        assert edited.status_code == 200
        assert edited.json()["narrative"] == "The council approved the motion 2-1."
        assert edited.json()["audit_fingerprint"] != draft["audit_fingerprint"]
        assert edited.json()["sourced_claims"] == draft["sourced_claims"]

        stale_edit = client.patch(
            f"/api/staff/summaries/{draft['summary_id']}",
            json={
                "narrative": "A stale edit must not overwrite the saved draft.",
                "expected_audit_fingerprint": draft["audit_fingerprint"],
            },
        )
        assert stale_edit.status_code == 409

        approved = client.post(
            f"/api/staff/summaries/{draft['summary_id']}/approve",
            json={"expected_audit_fingerprint": edited.json()["audit_fingerprint"]},
        )
        assert approved.status_code == 200
        after_approval = client.patch(
            f"/api/staff/summaries/{draft['summary_id']}",
            json={
                "narrative": "An edit after approval must fail.",
                "expected_audit_fingerprint": edited.json()["audit_fingerprint"],
            },
        )
        assert after_approval.status_code == 409

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
