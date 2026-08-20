# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP tests for the caption review queue."""

from __future__ import annotations

import hashlib
import wave
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.captions.models import CaptionCue
from civiccast.captions.review import (
    CaptionReviewItemCreate,
    InMemoryCaptionReviewStore,
)
from civiccast.captions.router import (
    get_caption_review_asset_store,
    get_caption_review_clip_builder,
    get_caption_review_store,
)
from civiccast.schedule.models import StaffAssetRow


def _cue(text: str = "motion carries", *, low_confidence: bool = False) -> dict[str, object]:
    return {
        "cue_id": "cue-000001",
        "start_seconds": 0.0,
        "end_seconds": 3.8,
        "text": text,
        "confidence": 0.62 if low_confidence else 0.94,
        "low_confidence": low_confidence,
    }


def _payload(
    review_item_id: str = "review-1",
    *,
    asset_id: str = "asset-1",
    low_confidence: bool = True,
):
    return {
        "review_item_id": review_item_id,
        "asset_id": asset_id,
        "cue": _cue(low_confidence=low_confidence),
    }


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = InMemoryCaptionReviewStore()
    app.dependency_overrides[get_caption_review_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def _seed(
    client: TestClient,
    review_item_id: str = "review-1",
    *,
    asset_id: str = "asset-1",
    low_confidence: bool = True,
):
    response = client.post(
        "/api/staff/captions/review-items",
        json=_payload(
            review_item_id,
            asset_id=asset_id,
            low_confidence=low_confidence,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateReviewItem:
    def test_201_creates_pending_item(self, client: TestClient) -> None:
        body = _seed(client)

        assert body["review_item_id"] == "review-1"
        assert body["status"] == "pending"
        assert body["original_text"] == "motion carries"
        assert body["reviewed_text"] is None
        assert body["low_confidence"] is True

    def test_409_on_duplicate_id(self, client: TestClient) -> None:
        _seed(client)
        response = client.post("/api/staff/captions/review-items", json=_payload())

        assert response.status_code == 409
        assert "review-1" in response.json()["detail"]

    def test_422_on_invalid_cue_time(self, client: TestClient) -> None:
        payload = _payload()
        payload["cue"]["end_seconds"] = 0.0  # type: ignore[index]
        response = client.post("/api/staff/captions/review-items", json=payload)

        assert response.status_code == 422

    def test_http_create_cannot_inject_private_audio_evidence(
        self,
        client: TestClient,
        tmp_path,
    ) -> None:
        payload = _payload()
        payload["audio_evidence"] = {
            "source_path": str(tmp_path / "attacker-selected.wav"),
            "source_start_seconds": 0,
            "source_sha256": "0" * 64,
            "source_bytes": 1,
        }

        response = client.post("/api/staff/captions/review-items", json=payload)

        assert response.status_code == 422


class TestListAndGetReviewItems:
    def test_list_filters_by_asset_and_status(self, client: TestClient) -> None:
        _seed(client, "review-1", asset_id="asset-a")
        _seed(client, "review-2", asset_id="asset-b")
        client.post("/api/staff/captions/review-items/review-2/reject", json={})

        response = client.get(
            "/api/staff/captions/review-items",
            params={"asset_id": "asset-b", "status_filter": "rejected"},
        )

        assert response.status_code == 200
        assert [item["review_item_id"] for item in response.json()] == ["review-2"]

    def test_get_returns_item_or_404(self, client: TestClient) -> None:
        _seed(client)

        found = client.get("/api/staff/captions/review-items/review-1")
        missing = client.get("/api/staff/captions/review-items/missing")

        assert found.status_code == 200
        assert found.json()["review_item_id"] == "review-1"
        assert missing.status_code == 404


class TestReviewAudioClip:
    def test_returns_authenticated_bounded_wav_and_removes_temp_file(
        self,
        client: TestClient,
        tmp_path,
    ) -> None:
        source = tmp_path / "meeting.mp4"
        source.write_bytes(b"source")
        clip = tmp_path / "review.wav"

        class AssetStore:
            def get_staff_row(self, asset_id: str) -> StaffAssetRow | None:
                if asset_id != "asset-1":
                    return None
                return StaffAssetRow(
                    asset_id=asset_id,
                    title="Council meeting",
                    state="recorded",
                    file_path=str(source),
                )

        def build_clip(_source, _cue):
            clip.write_bytes(b"RIFF-bounded-review-audio")
            return clip

        app = client.app
        app.dependency_overrides[get_caption_review_asset_store] = AssetStore
        app.dependency_overrides[get_caption_review_clip_builder] = lambda: build_clip
        _seed(client)

        response = client.get("/api/staff/captions/review-items/review-1/clip")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.content == b"RIFF-bounded-review-audio"
        assert not clip.exists()

    def test_clip_reports_missing_review_item_asset_and_media(
        self,
        client: TestClient,
        tmp_path,
    ) -> None:
        class AssetStore:
            row: StaffAssetRow | None = None

            def get_staff_row(self, _asset_id: str) -> StaffAssetRow | None:
                return self.row

        assets = AssetStore()
        client.app.dependency_overrides[get_caption_review_asset_store] = lambda: assets
        client.app.dependency_overrides[get_caption_review_clip_builder] = lambda: (
            lambda _source, _cue: tmp_path / "unused.wav"
        )

        missing_review = client.get("/api/staff/captions/review-items/missing/clip")
        _seed(client)
        missing_asset = client.get("/api/staff/captions/review-items/review-1/clip")
        assets.row = StaffAssetRow(
            asset_id="asset-1",
            title="Council meeting",
            state="recorded",
            file_path=None,
        )
        missing_media = client.get("/api/staff/captions/review-items/review-1/clip")

        assert missing_review.status_code == 404
        assert missing_asset.status_code == 404
        assert missing_media.status_code == 409

    def test_live_caption_audio_uses_durable_evidence_without_an_asset_row(
        self,
        client: TestClient,
        tmp_path,
    ) -> None:
        source = tmp_path / "caption-evidence.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\0\0" * 16_000 * 5)
        evidence = {
            "source_path": str(source),
            "source_start_seconds": 10.0,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_bytes": source.stat().st_size,
        }
        store = InMemoryCaptionReviewStore()
        created = store.create(
            CaptionReviewItemCreate.model_validate(
                {
                    "review_item_id": "live-review-1",
                    "asset_id": "gov-ch12",
                    "cue": CaptionCue(
                        cue_id="cue-live-1",
                        start_seconds=12.0,
                        end_seconds=14.5,
                        text="the motion carries",
                        confidence=0.9,
                    ),
                    "audio_evidence": evidence,
                }
            )
        )
        assert created.audio_evidence_available is True

        class EmptyAssetStore:
            def get_staff_row(self, _asset_id: str) -> None:
                return None

        captured: dict[str, object] = {}
        clip = tmp_path / "bounded.wav"

        def build_clip(actual_source, relative_cue):
            captured["source"] = actual_source
            captured["cue"] = relative_cue
            clip.write_bytes(b"RIFF-bounded")
            return clip

        client.app.dependency_overrides[get_caption_review_store] = lambda: store
        client.app.dependency_overrides[get_caption_review_asset_store] = EmptyAssetStore
        client.app.dependency_overrides[get_caption_review_clip_builder] = lambda: build_clip

        response = client.get("/api/staff/captions/review-items/live-review-1/clip")

        assert response.status_code == 200, response.text
        assert captured["source"] == source.resolve()
        relative_cue = captured["cue"]
        assert relative_cue.start_seconds == 2.0
        assert relative_cue.end_seconds == 4.5


class TestReviewDecisions:
    def test_approve_uses_existing_text_without_rewriting_original_cue(
        self, client: TestClient
    ) -> None:
        _seed(client, low_confidence=False)

        response = client.post(
            "/api/staff/captions/review-items/review-1/approve",
            json={
                "reviewer_note": "Looks good.",
                "low_confidence_acknowledged": True,
            },
        )

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "approved"
        assert body["original_text"] == "motion carries"
        assert body["reviewed_text"] == "motion carries"
        assert body["cue"]["text"] == "motion carries"
        assert body["reviewer_note"] == "Looks good."

    def test_low_confidence_approve_requires_explicit_acknowledgement(
        self,
        client: TestClient,
    ) -> None:
        _seed(client)

        rejected = client.post(
            "/api/staff/captions/review-items/review-1/approve",
            json={"reviewer_note": "Unreviewed."},
        )

        assert rejected.status_code == 409
        assert "low-confidence" in rejected.json()["detail"].lower()
        assert client.get("/api/staff/captions/review-items/review-1").json()["status"] == "pending"

        blocked_without_evidence = client.post(
            "/api/staff/captions/review-items/review-1/approve",
            json={
                "reviewer_note": "Compared with the audio.",
                "low_confidence_acknowledged": True,
            },
        )
        assert blocked_without_evidence.status_code == 409
        assert "audio evidence" in blocked_without_evidence.json()["detail"].lower()
        assert client.get("/api/staff/captions/review-items/review-1").json()["status"] == "pending"

    def test_low_confidence_approval_succeeds_with_verified_covering_evidence(
        self,
        client: TestClient,
        tmp_path,
    ) -> None:
        source = tmp_path / "review-evidence.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\0\0" * 16_000 * 4)
        evidence = {
            "source_path": str(source.resolve()),
            "source_start_seconds": 0.0,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_bytes": source.stat().st_size,
        }
        store = InMemoryCaptionReviewStore()
        store.create(
            CaptionReviewItemCreate.model_validate(
                {
                    "review_item_id": "verified-review",
                    "asset_id": "asset-1",
                    "cue": _cue(low_confidence=True),
                    "audio_evidence": evidence,
                }
            )
        )
        client.app.dependency_overrides[get_caption_review_store] = lambda: store

        approved = client.post(
            "/api/staff/captions/review-items/verified-review/approve",
            json={
                "reviewer_note": "Compared with retained audio.",
                "low_confidence_acknowledged": True,
            },
        )

        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

    def test_edit_sets_reviewed_text_but_preserves_original_cue(self, client: TestClient) -> None:
        _seed(client)

        response = client.post(
            "/api/staff/captions/review-items/review-1/edit",
            json={"text": "motion carries unanimously", "reviewer_note": "Added vote result."},
        )

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "edited"
        assert body["original_text"] == "motion carries"
        assert body["reviewed_text"] == "motion carries unanimously"
        assert body["cue"]["text"] == "motion carries"

    def test_reject_clears_reviewed_text(self, client: TestClient) -> None:
        _seed(client)
        client.post(
            "/api/staff/captions/review-items/review-1/edit",
            json={"text": "motion carries unanimously"},
        )

        response = client.post("/api/staff/captions/review-items/review-1/reject", json={})

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert response.json()["reviewed_text"] is None

    @pytest.mark.parametrize("action", ["approve", "edit", "reject"])
    def test_missing_item_returns_404(self, client: TestClient, action: str) -> None:
        payload = {"text": "fixed"} if action == "edit" else {}
        response = client.post(f"/api/staff/captions/review-items/missing/{action}", json=payload)

        assert response.status_code == 404
