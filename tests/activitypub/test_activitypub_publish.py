# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""ActivityPub outbox integration with the local publish workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.activitypub.keys import generate_activitypub_private_key
from civiccast.activitypub.remote import DeliveryResult
from civiccast.activitypub.store import InMemoryActivityPubStore
from civiccast.app import create_app
from civiccast.publish.router import get_publish_store
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.schedule.router import get_postgres_store


class FakeAssetStore:
    def __init__(self) -> None:
        self._asset = StaffAssetRow(
            asset_id="council-2026-05-08",
            title="Council - May 8, 2026",
            state="validated",
            manifest_url="https://portal.example/council-2026-05-08/playlist.m3u8",
            published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
            retention_policy="meeting",
            version=1,
        )

    def list_all(self) -> list[StaffAssetRow]:
        return [self._asset]

    def get_staff_row(self, asset_id: str) -> StaffAssetRow | None:
        return self._asset if asset_id == self._asset.asset_id else None

    def mark_published(self, asset_id: str, *, published_at: datetime) -> StaffAssetRow:
        assert asset_id == self._asset.asset_id
        self._asset = self._asset.model_copy(update={"published_at": published_at})
        return self._asset


@pytest.fixture(autouse=True)
def activitypub_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_path = tmp_path / "station-activitypub.pem"
    generate_activitypub_private_key(key_path)
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_HANDLE", "station")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_DISPLAY_NAME", "CivicCast Station")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "open")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_BASE_URL", "http://testserver")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH", str(key_path))


class RecordingDeliveryClient:
    def __init__(self) -> None:
        self.deliveries: list[tuple[str, dict[str, object]]] = []

    def deliver(self, *, inbox_url: str, activity: dict[str, object]) -> DeliveryResult:
        self.deliveries.append((inbox_url, activity))
        return DeliveryResult(
            inbox_url=inbox_url,
            status_code=202,
            response_body="accepted",
            delivered_at=datetime.now(UTC),
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: FakeAssetStore()
    app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
    activitypub_store = InMemoryActivityPubStore()
    app.state.store_bundle = app.state.store_bundle.__class__(
        asset_store=app.state.store_bundle.asset_store,
        caption_review_store=app.state.store_bundle.caption_review_store,
        summary_store=app.state.store_bundle.summary_store,
        record_store=app.state.store_bundle.record_store,
        publish_store=app.state.store_bundle.publish_store,
        subscribe_store=app.state.store_bundle.subscribe_store,
        podcast_store=app.state.store_bundle.podcast_store,
        activitypub_store=lambda: activitypub_store,
    )
    app.state.activitypub_delivery_client = RecordingDeliveryClient()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def test_publish_approval_adds_activitypub_outbox_create_note(client: TestClient) -> None:
    approval = client.post(
        "/api/staff/publish/assets/council-2026-05-08/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
        },
    )

    assert approval.status_code == 200
    outbox = client.get("/ap/outbox")
    assert outbox.status_code == 200
    body = outbox.json()
    assert body["totalItems"] == 1
    activity = body["orderedItems"][0]
    assert activity["type"] == "Create"
    assert activity["actor"] == "http://testserver/ap/actor"
    assert activity["object"]["type"] == "Note"
    assert "Council - May 8, 2026" in activity["object"]["content"]
    assert activity["object"]["url"] == "https://portal.example/council-2026-05-08/playlist.m3u8"
