# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish approval contracts for the v1.2 BrokerClient seam."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.publish.router import get_publish_store
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.schedule.router import get_postgres_store


class FakeAssetStore:
    def __init__(self, assets: list[StaffAssetRow]) -> None:
        self._assets = assets

    def list_all(self) -> list[StaffAssetRow]:
        return self._assets

    def get_staff_row(self, asset_id: str) -> StaffAssetRow | None:
        return next((asset for asset in self._assets if asset.asset_id == asset_id), None)

    def mark_published(self, asset_id: str, *, published_at: datetime) -> StaffAssetRow:
        asset = self.get_staff_row(asset_id)
        assert asset is not None
        updated = asset.model_copy(update={"published_at": published_at})
        self._assets[self._assets.index(asset)] = updated
        return updated


@pytest.fixture
def store() -> FakeAssetStore:
    return FakeAssetStore(
        [
            StaffAssetRow(
                asset_id="council-2026-05-08",
                title="Council - May 8, 2026",
                state="validated",
                manifest_url="https://cdn.example/council-2026-05-08/playlist.m3u8",
                published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
                retention_policy="meeting",
                version=1,
            ),
            StaffAssetRow(
                asset_id="training-clip",
                title="Training clip",
                state="validated",
                manifest_url=None,
                retention_policy="short",
                version=1,
            ),
        ]
    )


@pytest.fixture
def app_with_store(store: FakeAssetStore):
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: store
    app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
    return app


@pytest.fixture
def client(app_with_store) -> Iterator[tuple[TestClient, object]]:
    with TestClient(
        app_with_store, headers={"Authorization": "Bearer operator-token-a"}
    ) as test_client:
        yield test_client, app_with_store


class TestPublishBrokerSeam:
    def test_approval_emits_documented_broker_event_when_publish_succeeds(
        self,
        client: tuple[TestClient, object],
    ) -> None:
        test_client, app = client
        broker_module = import_module("civiccast.platform.broker")
        broker_client = broker_module.InProcessBrokerClient()
        app.dependency_overrides[broker_module.get_broker_client] = lambda: broker_client

        response = test_client.post(
            "/api/staff/publish/assets/council-2026-05-08/approve",
            json={
                "operator_id": "staff-1",
                "operator_display_name": "Avery Operator",
            },
        )

        assert response.status_code == 200
        events = broker_client.replay("publish.asset.approved")
        assert len(events) == 1
        assert events[0].payload["asset_id"] == "council-2026-05-08"
        assert events[0].payload["status"] == "archive_verified"
        assert events[0].payload["surfaces"]

    def test_preflight_failure_does_not_emit_success_event(
        self,
        client: tuple[TestClient, object],
    ) -> None:
        test_client, app = client
        broker_module = import_module("civiccast.platform.broker")
        broker_client = broker_module.InProcessBrokerClient()
        app.dependency_overrides[broker_module.get_broker_client] = lambda: broker_client

        response = test_client.post(
            "/api/staff/publish/assets/training-clip/approve",
            json={
                "operator_id": "staff-1",
                "operator_display_name": "Avery Operator",
            },
        )

        assert response.status_code == 409
        assert broker_client.replay("publish.asset.approved") == []
