# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for withdrawing an asset from Portal visibility.

Codex review (PR #419, A-1): the first-run seeded sample's own description
tells the operator to "Delete it like any other asset once real content is
ready," but no removal or unpublish endpoint existed anywhere in the
product before this. Coverage:

  TestStoreMarkUnpublished  — PostgresAssetStore.mark_unpublished round-trip
  TestRouterUnpublish       — POST /api/staff/assets/{id}/unpublish HTTP
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.models import Asset, StaffAssetRow
from civiccast.schedule.router import get_postgres_store
from civiccast.schedule.store import AssetNotFoundError, PostgresAssetStore

# ---------------------------------------------------------------------------
# TestStoreMarkUnpublished
# ---------------------------------------------------------------------------


def _seed_published_asset(session_factory, asset_id: str = "sample-welcome-1") -> None:
    with session_factory() as sess:
        sess.add(
            Asset(
                asset_id=asset_id,
                title="Sample: Welcome to CivicCast",
                description="A short bundled sample video.",
                manifest_url="https://cdn.example/sample/playlist.m3u8",
                state="validated",
                published_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
            )
        )
        sess.commit()


class TestStoreMarkUnpublished:
    """Locks: PostgresAssetStore.mark_unpublished clears published_at
    (the exact column the public GET /assets endpoints filter on)."""

    def test_clears_published_at(self, session_factory) -> None:
        _seed_published_asset(session_factory, "asset-1")
        store = PostgresAssetStore(session_factory)

        result = store.mark_unpublished("asset-1")

        assert isinstance(result, StaffAssetRow)
        assert result.published_at is None

    def test_persists_across_a_new_session(self, session_factory) -> None:
        _seed_published_asset(session_factory, "asset-2")
        store = PostgresAssetStore(session_factory)
        store.mark_unpublished("asset-2")

        refetched = store.get_staff_row("asset-2")

        assert refetched is not None
        assert refetched.published_at is None

    def test_idempotent_on_already_unpublished_asset(self, session_factory) -> None:
        _seed_published_asset(session_factory, "asset-3")
        store = PostgresAssetStore(session_factory)
        store.mark_unpublished("asset-3")

        # Second call must not raise -- mirrors cancel_schedule_item's
        # "cancelling an already-cancelled item is a no-op" idiom.
        result = store.mark_unpublished("asset-3")

        assert result.published_at is None

    def test_missing_asset_raises(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        with pytest.raises(AssetNotFoundError):
            store.mark_unpublished("does-not-exist")

    def test_other_fields_are_untouched(self, session_factory) -> None:
        _seed_published_asset(session_factory, "asset-4")
        store = PostgresAssetStore(session_factory)

        result = store.mark_unpublished("asset-4")

        assert result.title == "Sample: Welcome to CivicCast"
        assert result.manifest_url == "https://cdn.example/sample/playlist.m3u8"


# ---------------------------------------------------------------------------
# TestRouterUnpublish
# ---------------------------------------------------------------------------


class TestRouterUnpublish:
    """Locks: POST /api/staff/assets/{asset_id}/unpublish HTTP contract."""

    def test_503_when_no_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
        app = create_app()
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.post("/api/staff/assets/abc-123/unpublish")
        assert response.status_code == 503

    def test_404_when_asset_missing(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.mark_unpublished.side_effect = AssetNotFoundError("ghost")
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.post("/api/staff/assets/ghost/unpublish")
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_200_returns_row_with_published_at_cleared(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.mark_unpublished.return_value = StaffAssetRow(
            asset_id="sample-welcome-1",
            title="Sample: Welcome to CivicCast",
            state="validated",
            published_at=None,
            version=2,
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.post("/api/staff/assets/sample-welcome-1/unpublish")
        assert response.status_code == 200
        body = response.json()
        assert body["asset_id"] == "sample-welcome-1"
        assert body["published_at"] is None
        mock_store.mark_unpublished.assert_called_once_with("sample-welcome-1")

    def test_requires_write_role(self) -> None:
        # No Authorization header at all -- auth dependency should refuse
        # before the store is ever touched.
        app = create_app()
        mock_store = MagicMock()
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app) as c:
            response = c.post("/api/staff/assets/abc-123/unpublish")
        assert response.status_code in (401, 403)
        mock_store.mark_unpublished.assert_not_called()
