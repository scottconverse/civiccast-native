# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for asset metadata edit + trim/chapter/retention persistence.

Sprint 0.3 task 5. Coverage:

  TestAssetMetadataUpdateModel    — Pydantic validation (trim ordering,
                                     retention enum, chapter shape)
  TestStoreUpdateMetadata         — store.update_metadata round-trip
  TestStoreGetStaffRow            — store.get_staff_row chapters JSON
                                     deserialization
  TestRouterMetadataEdit          — PATCH /api/staff/assets/{id} HTTP

Real-Postgres CHECK-constraint coverage lives in test_real_postgres.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from civiccast.app import create_app
from civiccast.schedule.models import (
    RETENTION_DEFAULT,
    RETENTION_MEETING,
    RETENTION_PERMANENT,
    Asset,
    AssetMetadataUpdate,
    Chapter,
    StaffAssetRow,
)
from civiccast.schedule.router import get_postgres_store
from civiccast.schedule.store import (
    AssetNotFoundError,
    PostgresAssetStore,
)

# ---------------------------------------------------------------------------
# TestAssetMetadataUpdateModel
# ---------------------------------------------------------------------------


class TestAssetMetadataUpdateModel:
    """Locks: Pydantic validation rules on AssetMetadataUpdate."""

    def test_empty_update_accepts(self) -> None:
        # No fields set → valid (no-op patch).
        AssetMetadataUpdate(expected_version=1)

    def test_trim_window_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="strictly less than"):
            AssetMetadataUpdate(expected_version=1, trim_in_seconds=3600, trim_out_seconds=600)

    def test_trim_in_equal_out_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strictly less than"):
            AssetMetadataUpdate(expected_version=1, trim_in_seconds=100, trim_out_seconds=100)

    def test_trim_in_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, trim_in_seconds=-1)

    def test_trim_out_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, trim_out_seconds=0)

    def test_only_trim_in_or_only_trim_out_accepts(self) -> None:
        # Either bound alone is fine — operator might be setting just one.
        AssetMetadataUpdate(expected_version=1, trim_in_seconds=10)
        AssetMetadataUpdate(expected_version=1, trim_out_seconds=20)

    def test_fractional_trim_values_accept(self) -> None:
        update = AssetMetadataUpdate(
            expected_version=1,
            trim_in_seconds=1.5,
            trim_out_seconds=2.333,
        )
        assert update.trim_in_seconds == 1.5
        assert update.trim_out_seconds == 2.333

    def test_unknown_retention_policy_rejected(self) -> None:
        with pytest.raises(ValidationError, match="retention_policy must be one of"):
            AssetMetadataUpdate(expected_version=1, retention_policy="forever")

    def test_known_retention_policies_accept(self) -> None:
        for v in (RETENTION_DEFAULT, RETENTION_PERMANENT, RETENTION_MEETING, "short"):
            AssetMetadataUpdate(expected_version=1, retention_policy=v)

    def test_chapters_validation(self) -> None:
        # Valid chapter list
        AssetMetadataUpdate(
            expected_version=1, chapters=[Chapter(t=0, name="Intro"), Chapter(t=120, name="Vote")]
        )
        # Negative t
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, chapters=[Chapter(t=-1, name="x")])
        # Empty name
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, chapters=[Chapter(t=0, name="")])

    def test_title_constraints(self) -> None:
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, title="")
        AssetMetadataUpdate(expected_version=1, title="x" * 200)
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, title="x" * 201)

    def test_meeting_body_constraints(self) -> None:
        # Option b (#107 remainder): a meeting-body category tag on assets.
        AssetMetadataUpdate(expected_version=1, meeting_body="City Council")
        AssetMetadataUpdate(expected_version=1, meeting_body="x" * 120)
        AssetMetadataUpdate(expected_version=1, meeting_body=None)  # explicit clear
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, meeting_body="")
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, meeting_body="x" * 121)

    def test_meeting_body_is_normalized_server_side(self) -> None:
        # Audit QA-002/UX-002: the portal facet derives by RAW equality, so
        # padded API writes (" City Council ") would fork the facet. The
        # server strips; whitespace-only and control chars are rejected.
        update = AssetMetadataUpdate(expected_version=1, meeting_body="  City Council  ")
        assert update.meeting_body == "City Council"
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, meeting_body="   ")
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, meeting_body="City\x01Council")


# ---------------------------------------------------------------------------
# Store-level fixtures (reuse the existing schedule conftest's session_factory)
# ---------------------------------------------------------------------------


def _seed_asset(session_factory, asset_id: str = "council-2026-05-08") -> None:
    """Insert a minimal Asset row directly via the SA model so the
    metadata-edit tests have a target."""
    with session_factory() as sess:
        sess.add(
            Asset(
                asset_id=asset_id,
                title="Original title",
                description="Original description",
                manifest_url="https://cdn.example/x/playlist.m3u8",
                state="validated",
            )
        )
        sess.commit()


# ---------------------------------------------------------------------------
# TestStoreUpdateMetadata
# ---------------------------------------------------------------------------


class TestStoreUpdateMetadata:
    """Locks: PostgresAssetStore.update_metadata applies partial patches
    and persists each field correctly."""

    def test_update_title_only(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-1")
        store = PostgresAssetStore(session_factory)
        # Audit TEST-003: tag first, so the title-only PATCH proves the tag
        # SURVIVES unrelated edits (an always-assign mutation cleared it).
        store.update_metadata(
            "asset-1", AssetMetadataUpdate(expected_version=1, meeting_body="City Council")
        )
        result = store.update_metadata(
            "asset-1", AssetMetadataUpdate(expected_version=2, title="Updated title")
        )
        assert isinstance(result, StaffAssetRow)
        assert result.title == "Updated title"
        # Description AND the meeting-body tag preserved.
        assert result.description == "Original description"
        assert result.meeting_body == "City Council"

    def test_update_trim_window(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-2")
        store = PostgresAssetStore(session_factory)
        result = store.update_metadata(
            "asset-2",
            AssetMetadataUpdate(expected_version=1, trim_in_seconds=1.5, trim_out_seconds=600.333),
        )
        assert result.trim_in_seconds == 1.5
        assert result.trim_out_seconds == 600.333

    def test_update_chapters_replaces_all(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-3")
        store = PostgresAssetStore(session_factory)
        # First write — initial version is 1.
        first = store.update_metadata(
            "asset-3",
            AssetMetadataUpdate(
                expected_version=1,
                chapters=[
                    Chapter(t=0, name="Open"),
                    Chapter(t=120, name="Vote", sub="2-1 in favor"),
                ],
            ),
        )
        # QA-008: each successful update increments version.
        assert first.version == 2
        result = store.update_metadata(
            "asset-3",
            AssetMetadataUpdate(
                expected_version=2,
                chapters=[Chapter(t=300, name="Adjourn")],
            ),
        )
        assert len(result.chapters) == 1
        assert result.chapters[0].name == "Adjourn"
        assert result.version == 3

    def test_update_chapters_empty_list_clears(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-4")
        store = PostgresAssetStore(session_factory)
        store.update_metadata(
            "asset-4",
            AssetMetadataUpdate(
                expected_version=1,
                chapters=[Chapter(t=0, name="Open")],
            ),
        )
        result = store.update_metadata(
            "asset-4",
            AssetMetadataUpdate(expected_version=2, chapters=[]),
        )
        assert result.chapters == []

    def test_update_retention_policy(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-5")
        store = PostgresAssetStore(session_factory)
        result = store.update_metadata(
            "asset-5",
            AssetMetadataUpdate(expected_version=1, retention_policy=RETENTION_PERMANENT),
        )
        assert result.retention_policy == RETENTION_PERMANENT

    def test_update_retention_until_tz_aware(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-6")
        store = PostgresAssetStore(session_factory)
        until = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = store.update_metadata(
            "asset-6",
            AssetMetadataUpdate(expected_version=1, retention_until=until),
        )
        assert result.retention_until is not None
        assert result.retention_until.tzinfo is not None

    def test_update_meeting_body_round_trips_and_clears(self, session_factory) -> None:
        # Option b (#107 remainder): the meeting-body tag persists and an
        # explicit null clears it (untagged recordings stay browsable).
        _seed_asset(session_factory, "asset-mb")
        store = PostgresAssetStore(session_factory)
        tagged = store.update_metadata(
            "asset-mb",
            AssetMetadataUpdate(expected_version=1, meeting_body="School Board"),
        )
        assert tagged.meeting_body == "School Board"
        assert tagged.title == "Original title"

        cleared = store.update_metadata(
            "asset-mb",
            AssetMetadataUpdate(expected_version=2, meeting_body=None),
        )
        assert cleared.meeting_body is None

    def test_update_missing_asset_raises(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        with pytest.raises(AssetNotFoundError) as exc_info:
            store.update_metadata(
                "ghost-asset", AssetMetadataUpdate(expected_version=1, title="Doesn't matter")
            )
        assert exc_info.value.asset_id == "ghost-asset"

    def test_no_change_when_payload_empty(self, session_factory) -> None:
        _seed_asset(session_factory, "asset-7")
        store = PostgresAssetStore(session_factory)
        result = store.update_metadata("asset-7", AssetMetadataUpdate(expected_version=1))
        assert result.title == "Original title"
        assert result.description == "Original description"

    # -------------------------------------------------------------------
    # QA-007 (audit-team v0.3.0): published-schedule-item guard
    # -------------------------------------------------------------------

    def test_qa007_refused_when_asset_has_published_schedule_item(self, session_factory) -> None:
        """Locks: update_metadata raises AssetAlreadyPublishedError when
        at least one linked schedule_items row is in state 'published'."""
        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_PUBLISHED,
            ScheduleItem,
        )
        from civiccast.schedule.store import AssetAlreadyPublishedError

        _seed_asset(session_factory, "published-asset")
        # Insert a published schedule item linked to the asset.
        with session_factory() as sess:
            sess.add(
                ScheduleItem(
                    asset_id="published-asset",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_PREMIERE,
                    state=SCHEDULE_STATE_PUBLISHED,
                    scheduled_at=datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC),
                    duration_seconds=3600,
                    scheduled_at_end=datetime(2026, 5, 15, 19, 0, 0, tzinfo=UTC),
                )
            )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        with pytest.raises(AssetAlreadyPublishedError) as exc_info:
            store.update_metadata(
                "published-asset",
                AssetMetadataUpdate(expected_version=1, title="Would-be edit"),
            )
        assert exc_info.value.asset_id == "published-asset"
        assert len(exc_info.value.published_schedule_item_ids) == 1

    def test_qa007_allowed_when_only_cancelled_or_scheduled(self, session_factory) -> None:
        """Locks: an asset with only 'cancelled' or 'scheduled' linked
        schedule items is editable; only 'published' items trip the guard."""
        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_CANCELLED,
            SCHEDULE_STATE_SCHEDULED,
            ScheduleItem,
        )

        _seed_asset(session_factory, "editable-asset")
        # Insert a cancelled item + a scheduled item; neither blocks edit.
        with session_factory() as sess:
            sess.add(
                ScheduleItem(
                    asset_id="editable-asset",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_PREMIERE,
                    state=SCHEDULE_STATE_CANCELLED,
                    scheduled_at=datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC),
                    duration_seconds=3600,
                    scheduled_at_end=datetime(2026, 5, 15, 19, 0, 0, tzinfo=UTC),
                )
            )
            sess.add(
                ScheduleItem(
                    asset_id="editable-asset",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_PREMIERE,
                    state=SCHEDULE_STATE_SCHEDULED,
                    scheduled_at=datetime(2026, 5, 16, 18, 0, 0, tzinfo=UTC),
                    duration_seconds=3600,
                    scheduled_at_end=datetime(2026, 5, 16, 19, 0, 0, tzinfo=UTC),
                )
            )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        result = store.update_metadata(
            "editable-asset",
            AssetMetadataUpdate(expected_version=1, title="Edit allowed"),
        )
        assert result.title == "Edit allowed"
        assert result.version == 2

    def test_qa007_lists_all_published_item_ids(self, session_factory) -> None:
        """Locks: when multiple published schedule items reference the
        asset, the error's id list includes all of them so the router
        409 detail can name every blocker."""
        from civiccast.schedule.models import (
            SCHEDULE_MODE_PREMIERE,
            SCHEDULE_STATE_PUBLISHED,
            ScheduleItem,
        )
        from civiccast.schedule.store import AssetAlreadyPublishedError

        _seed_asset(session_factory, "multi-pub-asset")
        with session_factory() as sess:
            for hour_offset in range(3):
                sess.add(
                    ScheduleItem(
                        asset_id="multi-pub-asset",
                        channel_id=f"gov-ch{hour_offset}",
                        mode=SCHEDULE_MODE_PREMIERE,
                        state=SCHEDULE_STATE_PUBLISHED,
                        scheduled_at=datetime(2026, 5, 15, 18 + hour_offset, 0, 0, tzinfo=UTC),
                        duration_seconds=3600,
                        scheduled_at_end=datetime(2026, 5, 15, 19 + hour_offset, 0, 0, tzinfo=UTC),
                    )
                )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        with pytest.raises(AssetAlreadyPublishedError) as exc_info:
            store.update_metadata(
                "multi-pub-asset",
                AssetMetadataUpdate(expected_version=1, title="Blocked edit"),
            )
        assert len(exc_info.value.published_schedule_item_ids) == 3


# ---------------------------------------------------------------------------
# TestStoreGetStaffRow
# ---------------------------------------------------------------------------


class TestStoreGetStaffRow:
    """Locks: store.get_staff_row deserializes chapters_json correctly."""

    def test_returns_none_for_unknown(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        assert store.get_staff_row("ghost") is None

    def test_returns_row_with_empty_chapters_when_unset(self, session_factory) -> None:
        _seed_asset(session_factory, "no-chapters")
        store = PostgresAssetStore(session_factory)
        row = store.get_staff_row("no-chapters")
        assert row is not None
        assert row.chapters == []

    def test_returns_row_with_chapters_after_update(self, session_factory) -> None:
        _seed_asset(session_factory, "with-chapters")
        store = PostgresAssetStore(session_factory)
        store.update_metadata(
            "with-chapters",
            AssetMetadataUpdate(
                expected_version=1,
                chapters=[
                    Chapter(t=0, name="Open"),
                    Chapter(t=600, name="Public comment"),
                ],
            ),
        )
        row = store.get_staff_row("with-chapters")
        assert row is not None
        assert len(row.chapters) == 2
        assert row.chapters[0].name == "Open"
        assert row.chapters[1].t == 600


# ---------------------------------------------------------------------------
# TestRouterMetadataEdit  (mocked store — full HTTP-shape coverage)
# ---------------------------------------------------------------------------


class TestRouterMetadataEdit:
    """Locks: PATCH /api/staff/assets/{asset_id} HTTP contract."""

    def test_503_when_no_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
        app = create_app()
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={"expected_version": 1, "title": "New"},
            )
        assert response.status_code == 503

    def test_404_when_asset_missing(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.side_effect = AssetNotFoundError(asset_id="ghost")
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/ghost",
                json={"expected_version": 1, "title": "New"},
            )
        assert response.status_code == 404

    def test_200_returns_updated_row(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.return_value = StaffAssetRow(
            asset_id="abc-123",
            title="Updated",
            state="validated",
            trim_in_seconds=1.5,
            trim_out_seconds=600.333,
            chapters=[Chapter(t=0, name="Open")],
            retention_policy=RETENTION_PERMANENT,
            version=2,
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={
                    "expected_version": 1,
                    "title": "Updated",
                    "trim_in_seconds": 1.5,
                    "trim_out_seconds": 600.333,
                    "chapters": [{"t": 0, "name": "Open"}],
                    "retention_policy": RETENTION_PERMANENT,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Updated"
        assert body["trim_in_seconds"] == 1.5
        assert body["trim_out_seconds"] == 600.333
        assert body["chapters"] == [{"t": 0.0, "name": "Open", "sub": None}]
        assert body["retention_policy"] == RETENTION_PERMANENT
        assert body["version"] == 2

    def test_422_on_invalid_trim_window(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={
                    "expected_version": 1,
                    "trim_in_seconds": 3600,
                    "trim_out_seconds": 600,
                },
            )
        assert response.status_code == 422

    def test_422_on_unknown_retention_policy(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={"expected_version": 1, "retention_policy": "forever"},
            )
        assert response.status_code == 422

    def test_422_when_expected_version_missing(self) -> None:
        # QA-008 (audit-team v0.3.0): expected_version is required.
        app = create_app()
        mock_store = MagicMock()
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={"title": "New"},
            )
        assert response.status_code == 422
        # Pydantic surfaces the missing field by name.
        body = response.json()
        assert any("expected_version" in str(item) for item in body.get("detail", []))

    def test_409_on_version_conflict(self) -> None:
        # QA-008: stale expected_version → 409 with structured payload.
        from civiccast.schedule.store import AssetVersionConflictError

        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.side_effect = AssetVersionConflictError(
            asset_id="abc-123",
            current_version=4,
            expected_version=2,
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={"expected_version": 2, "title": "New"},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["expected_version"] == 2
        assert detail["current_version"] == 4
        assert "abc-123" in detail["message"]

    def test_qa007_409_on_already_published(self) -> None:
        """Locks: PATCH returns 409 when the asset has linked published
        schedule items. Detail body carries the conflicting item ids per
        the audit's "fix and retry" UX flow."""
        from civiccast.schedule.store import AssetAlreadyPublishedError

        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.side_effect = AssetAlreadyPublishedError(
            asset_id="abc-123",
            published_schedule_item_ids=[
                "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "550e8400-e29b-41d4-a716-446655440000",
            ],
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.patch(
                "/api/staff/assets/abc-123",
                json={"expected_version": 1, "title": "Blocked edit"},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "abc-123" in detail["message"]
        assert "Unpublish or cancel" in detail["message"]
        assert detail["published_schedule_item_ids"] == [
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "550e8400-e29b-41d4-a716-446655440000",
        ]


# ---------------------------------------------------------------------------
# TestRouterGetStaffAsset  (mocked store — basic HTTP contract)
# ---------------------------------------------------------------------------


class TestRouterGetStaffAsset:
    def test_503_when_no_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
        app = create_app()
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.get("/api/staff/assets/abc-123")
        assert response.status_code == 503

    def test_404_when_absent(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.get_staff_row.return_value = None
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.get("/api/staff/assets/ghost")
        assert response.status_code == 404

    def test_200_returns_staff_row(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.get_staff_row.return_value = StaffAssetRow(
            asset_id="abc-123",
            title="Test",
            state="validated",
            duration_seconds=11820,
            chapters=[Chapter(t=0, name="Open")],
            retention_policy=RETENTION_DEFAULT,
            version=1,
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.get("/api/staff/assets/abc-123")
        assert response.status_code == 200
        body = response.json()
        assert body["asset_id"] == "abc-123"
        assert body["chapters"][0]["name"] == "Open"
