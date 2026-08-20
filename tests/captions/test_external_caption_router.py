# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP tests for external caption appliance ingest."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.router import get_caption_review_store


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = InMemoryCaptionReviewStore()
    app.dependency_overrides[get_caption_review_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def test_external_caption_ingest_creates_pending_review_items(client: TestClient) -> None:
    response = client.post(
        "/api/staff/captions/external-ingest",
        json={
            "request_id": "caption-hw-101",
            "asset_id": "meeting-101",
            "appliance_id": "caption-appliance-a",
            "source_label": "Caption appliance A",
            "protocol": "webvtt",
            "payload": "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nGood evening.\n",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["cue_count"] == 1
    assert (
        body["proof_boundary"] == "external-caption-appliance-to-review-queue-no-hardware-control"
    )
    assert body["review_items"][0]["status"] == "pending"
    assert body["review_items"][0]["original_text"] == "Good evening."

    queue = client.get(
        "/api/staff/captions/review-items",
        params={"asset_id": "meeting-101", "status_filter": "pending"},
    )
    assert queue.status_code == 200
    assert queue.json()[0]["review_item_id"] == "external-caption-hw-101-000001-review"


def test_external_caption_ingest_rejects_payload_without_timed_cues(client: TestClient) -> None:
    response = client.post(
        "/api/staff/captions/external-ingest",
        json={
            "request_id": "caption-hw-102",
            "asset_id": "meeting-102",
            "appliance_id": "caption-appliance-a",
            "source_label": "Caption appliance A",
            "protocol": "webvtt",
            "payload": "WEBVTT\n\nNo timestamp here.\n",
        },
    )

    assert response.status_code == 400
    assert "timed cues" in response.json()["detail"]
