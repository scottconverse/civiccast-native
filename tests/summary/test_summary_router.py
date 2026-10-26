# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI contract tests for v0.6 sourced summary routes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from civiccast.ai_runtime.ollama_client import OllamaRuntimeUnavailableError
from civiccast.app import create_app
from civiccast.captions import CaptionCue
from civiccast.summary.generate import DeterministicSummaryModel
from civiccast.summary.ollama import SummaryResourceDeferredError
from civiccast.summary.router import (
    SummaryGenerateRequest,
    generate_summary,
    get_summary_model,
    get_summary_store,
)
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

    def test_generate_summary_explains_resource_deferral(self) -> None:
        class _DeferredModel:
            def generate(
                self, *, meeting_id: str, cues: list[CaptionCue], prompt_version: str
            ) -> dict[str, Any]:
                raise SummaryResourceDeferredError(
                    "Summary generation was deferred before loading gemma4:12b: "
                    "17.0 GiB is available; preserve broadcast headroom or select the smaller model."
                )

        with pytest.raises(HTTPException) as exc_info:
            generate_summary(
                SummaryGenerateRequest(meeting_id="meeting-1", cues=[]),
                _DeferredModel(),  # type: ignore[arg-type]
                InMemorySummaryStore(),
            )

        assert exc_info.value.status_code == 503
        assert "deferred before loading" in exc_info.value.detail
        assert "broadcast headroom" in exc_info.value.detail

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


def test_agenda_minutes_review_correction_history_approval_export_and_manual_recovery(tmp_path):
    import json
    from contextlib import contextmanager
    from io import BytesIO
    from pathlib import Path
    from types import SimpleNamespace

    import pikepdf
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session

    from civiccast.agenda.models import AgendaItem, MeetingAgenda
    from civiccast.agenda.router import get_agenda_service, get_agenda_store
    from civiccast.agenda.service import AgendaService
    from civiccast.agenda.store import AgendaStore
    from civiccast.auth.models import OperatorIdentity
    from civiccast.captions.review import (
        CaptionReviewDecision,
        CaptionReviewEdit,
        CaptionReviewItemCreate,
        InMemoryCaptionReviewStore,
    )
    from civiccast.captions.router import get_caption_review_store
    from civiccast.recording.router import get_recording_store
    from civiccast.records.exporter import SignedRecordExporter
    from civiccast.records.timestamp import DeterministicTimestampAuthority
    from civiccast.summary.generate import SummaryGenerationPipeline
    from civiccast.summary.store import PostgresSummaryStore

    database = f"sqlite:///{(tmp_path / 'minutes.db').as_posix()}"
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database)
    command.upgrade(config, "0096_agenda_recording_link")
    engine = create_engine(
        database,
        connect_args={"check_same_thread": False},
        execution_options={"schema_translate_map": {"civiccast": None}},
    )
    assert "agenda_minutes_json" not in {
        c["name"] for c in inspect(engine).get_columns("summaries")
    }
    command.upgrade(config, "0097_agenda_minutes")

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    agendas = AgendaStore(factory)
    agendas.upsert_agenda(
        MeetingAgenda(
            agenda_id="agenda-1",
            station_id="civiccast-station",
            meeting_asset_id="placeholder",
            source_recording_job_id="capture-1",
        )
    )
    agendas.upsert_item(
        AgendaItem(
            item_id="budget", agenda_id="agenda-1", order=0, title="Budget", video_timecode_s=5
        )
    )
    cues = [
        CaptionCue(
            cue_id="budget-discussion",
            start_seconds=5,
            end_seconds=12,
            text="The council discussed the proposed budget.",
            confidence=0.99,
        ),
        CaptionCue(
            cue_id="budget-vote",
            start_seconds=20,
            end_seconds=24,
            text="Avery moved to adopt the budget. Blake voted yes.",
            confidence=0.99,
        ),
    ]
    reviews = InMemoryCaptionReviewStore()
    for cue in cues:
        reviews.create(
            CaptionReviewItemCreate(review_item_id=cue.cue_id, asset_id="meeting-1", cue=cue)
        )
        reviews.approve(cue.cue_id, CaptionReviewDecision())
    model = DeterministicSummaryModel(
        outputs=[
            {
                "narrative": "Budget discussion draft.",
                "sourced_claims": [
                    {
                        "claim_id": "budget-draft",
                        "text": "The council discussed the budget.",
                        "claim_type": "narrative",
                        "transcript_ranges": [
                            {"cue_id": cues[0].cue_id, "start_seconds": 5, "end_seconds": 12}
                        ],
                    },
                    {
                        "claim_id": "budget-vote-draft",
                        "text": cues[1].text,
                        "claim_type": "quantitative",
                        "transcript_ranges": [
                            {"cue_id": cues[1].cue_id, "start_seconds": 20, "end_seconds": 24}
                        ],
                    },
                ],
            }
        ]
    )
    generated = SummaryGenerationPipeline(model=model).generate(meeting_id="meeting-1", cues=cues)
    store = PostgresSummaryStore(factory)
    store.create_summary(generated)
    app = create_app()
    app.dependency_overrides[get_summary_store] = lambda: store
    app.dependency_overrides[get_caption_review_store] = lambda: reviews
    app.dependency_overrides[get_agenda_store] = lambda: agendas
    app.dependency_overrides[get_agenda_service] = lambda: AgendaService(
        agendas, playback_window_provider=lambda _: (2, 100)
    )
    app.dependency_overrides[get_recording_store] = lambda: SimpleNamespace(
        get_job=lambda _: SimpleNamespace(asset_id="meeting-1")
    )
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
        made = client.post(
            "/api/staff/summaries/agendas/agenda-1/minutes",
            json={"source_summary_id": generated.summary_id},
        )
        assert made.status_code == 201, made.text
        draft = made.json()
        route = f"/api/staff/summaries/{draft['summary_id']}"
        assert "player 3s" in draft["narrative"]
        assert (
            client.post(
                route + "/approve", json={"expected_audit_fingerprint": draft["audit_fingerprint"]}
            ).status_code
            == 409
        )
        content = draft["agenda_minutes"]["content"]
        content["sections"][0]["discussion"] = "The council discussed revisions before adoption."
        content["sections"][0]["motions"] = [
            {
                "text": "Adopt the revised budget",
                "mover": "Avery",
                "seconder": "Blake",
                "outcome": "passed",
                "votes": [{"member": "Blake", "choice": "yes"}],
                "human_confirmed": False,
                "transcript_ranges": [
                    {"cue_id": "budget-vote", "start_seconds": 20, "end_seconds": 24}
                ],
            }
        ]
        edited = client.patch(
            route + "/minutes",
            json={"expected_audit_fingerprint": draft["audit_fingerprint"], "content": content},
        )
        assert edited.status_code == 200, edited.text
        current = edited.json()
        assert (
            client.post(
                route + "/approve",
                json={"expected_audit_fingerprint": current["audit_fingerprint"]},
            ).status_code
            == 409
        )
        content["sections"][0]["motions"][0]["human_confirmed"] = True
        content["decisions_reviewed"] = True
        confirmed = client.patch(
            route + "/minutes",
            json={"expected_audit_fingerprint": current["audit_fingerprint"], "content": content},
        ).json()
        assert (
            client.post(
                route + "/approve", json={"expected_audit_fingerprint": draft["audit_fingerprint"]}
            ).status_code
            == 409
        )
        restarted = PostgresSummaryStore(factory)
        saved = restarted.get_summary(draft["summary_id"])
        assert len(saved.agenda_minutes.revisions) == 2
        assert (
            saved.agenda_minutes.revisions[0]
            .content.sections[0]
            .discussion.startswith("The council discussed the budget.")
        )
        assert saved.agenda_minutes.revisions[1].operator_id
        approved = client.post(
            route + "/approve", json={"expected_audit_fingerprint": confirmed["audit_fingerprint"]}
        )
        assert approved.status_code == 200, approved.text
        assert (
            client.patch(
                route + "/minutes",
                json={
                    "expected_audit_fingerprint": confirmed["audit_fingerprint"],
                    "content": content,
                },
            ).status_code
            == 409
        )
        record = SignedRecordExporter(
            summary_store=restarted, timestamp_authority=DeterministicTimestampAuthority()
        ).export(
            summary_id=draft["summary_id"],
            operator_identity=OperatorIdentity(
                operator_id="clerk", operator_display_name="Records clerk", token_id="test"
            ),
        )
        with pikepdf.open(BytesIO(record.pdf_bytes)) as pdf:
            minutes_file = pdf.attachments["agenda-minutes.json"].get_file()
            assert (
                str(pdf.attachments["agenda-minutes.json"].obj["/EF"]["/F"]["/Subtype"])
                == "/application/json"
            )
            embedded = json.loads(minutes_file.read_bytes())
            assert embedded["content"]["sections"][0]["motions"][0]["votes"][0] == {
                "member": "Blake",
                "choice": "yes",
            }
            assert len(embedded["revisions"]) == 2
            assert (
                json.loads(pdf.attachments["approval.json"].get_file().read_bytes())["summary_id"]
                == draft["summary_id"]
            )
        assert "Adopt the revised budget" in saved.narrative

        # A failed/unavailable model is independent of the manual route.
        def unavailable():
            raise AssertionError("Manual minutes must not invoke a model")

        app.dependency_overrides[get_summary_model] = unavailable
        manual = client.post("/api/staff/summaries/agendas/agenda-1/minutes", json={})
        assert manual.status_code == 201, manual.text
        assert manual.json()["provenance"]["model_tag"] == "manual-no-model"
        manual_route = "/api/staff/summaries/" + manual.json()["summary_id"]
        reviews.edit("budget-discussion", CaptionReviewEdit(text="Corrected council discussion."))
        stale_source = client.post(
            "/api/staff/summaries/agendas/agenda-1/minutes",
            json={"source_summary_id": generated.summary_id},
        )
        assert stale_source.status_code == 409
        stale_minutes = client.post(
            manual_route + "/approve",
            json={"expected_audit_fingerprint": manual.json()["audit_fingerprint"]},
        )
        assert stale_minutes.status_code == 409
        assert "transcript changed" in stale_minutes.json()["detail"]
    engine.dispose()
