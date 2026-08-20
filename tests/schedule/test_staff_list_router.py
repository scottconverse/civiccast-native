# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for GET /api/staff/assets — operator asset library endpoint.

Sprint 0.3 task 3: the operator console needs to see every asset (including
``pending_ingest`` / ``ingesting`` / ``validated``-not-yet-packaged / ``rejected``)
that the public list endpoint deliberately filters out. These tests pin the
behaviour at three layers:

  TestStaffListEndpointNoDB        — 503 when get_postgres_store returns None
  TestStaffListStoreMethod         — list_all() returns every state
  TestStaffListEndpointHappyPath   — 200 + StaffAssetRow[] including non-packaged
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import (
    ASSET_STATE_PENDING,
    ASSET_STATE_REJECTED,
    ASSET_STATE_VALIDATED,
    Asset,
    StaffAssetRow,
)
from civiccast.schedule.router import get_postgres_store
from civiccast.schedule.store import PostgresAssetStore

# ---------------------------------------------------------------------------
# TestStaffListEndpointNoDB
# ---------------------------------------------------------------------------


@pytest.fixture
def no_db_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Client with no Postgres store override — endpoint must return 503."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


class TestStaffListEndpointNoDB:
    """503 when no Postgres store is wired."""

    def test_returns_503_without_database(self, no_db_client: TestClient) -> None:
        response = no_db_client.get("/api/staff/assets")
        assert response.status_code == 503
        assert "Durable storage is not ready" in response.json()["detail"]


# ---------------------------------------------------------------------------
# TestStaffListStoreMethod
# ---------------------------------------------------------------------------


_VALID_FFPROBE = FfprobeResult(
    duration_seconds=60,
    codec_video="h264",
    codec_audio="aac",
    width_px=1920,
    height_px=1080,
    bitrate_bps=5_000_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


class TestStaffListStoreMethod:
    """PostgresAssetStore.list_all() returns every asset across every state."""

    def test_empty_store_returns_empty_list(self, session_factory) -> None:
        store = PostgresAssetStore(session_factory)
        assert store.list_all() == []

    def test_returns_uploaded_but_not_packaged_assets(self, session_factory) -> None:
        """Assets uploaded via ingest_upload have manifest_url=None — public
        list() hides them; list_all() must return them."""
        store = PostgresAssetStore(session_factory)
        store.ingest_upload(
            asset_id="upload-1",
            title="Uploaded but not packaged",
            description=None,
            file_path="/data/uploads/upload-1/x.mp4",
            file_size_bytes=1024,
            ffprobe_result=_VALID_FFPROBE,
        )

        rows = store.list_all()
        assert len(rows) == 1
        assert isinstance(rows[0], StaffAssetRow)
        assert rows[0].asset_id == "upload-1"
        assert rows[0].state == ASSET_STATE_VALIDATED
        assert rows[0].manifest_url is None
        # Public list() hides this row:
        assert store.list() == []

    def test_returns_packaged_and_unpackaged_alike(self, session_factory) -> None:
        """Both packaged (manifest_url set) and unpackaged assets appear."""
        # Insert a packaged row directly via SA so we can set manifest_url
        with session_factory() as sess:
            sess.add(
                Asset(
                    asset_id="packaged-1",
                    title="Packaged",
                    manifest_url="https://cdn.example/packaged-1/playlist.m3u8",
                    state=ASSET_STATE_VALIDATED,
                    published_at=datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC),
                )
            )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        store.ingest_upload(
            asset_id="upload-1",
            title="Uploaded",
            description=None,
            file_path="/data/uploads/upload-1/x.mp4",
            file_size_bytes=1024,
            ffprobe_result=_VALID_FFPROBE,
        )

        ids = {row.asset_id for row in store.list_all()}
        assert ids == {"packaged-1", "upload-1"}

    def test_returns_rejected_assets(self, session_factory) -> None:
        """Rejected assets must still appear so the operator can see why."""
        with session_factory() as sess:
            sess.add(
                Asset(
                    asset_id="rejected-1",
                    title="Rejected codec",
                    manifest_url=None,
                    state=ASSET_STATE_REJECTED,
                )
            )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        rows = store.list_all()
        assert len(rows) == 1
        assert rows[0].state == ASSET_STATE_REJECTED

    def test_orders_published_at_desc_nulls_last(self, session_factory) -> None:
        """Same ordering as public list(): published DESC NULLS LAST, asset_id ASC."""
        with session_factory() as sess:
            sess.add_all(
                [
                    Asset(
                        asset_id="zzz-pending",
                        title="No publish date",
                        manifest_url=None,
                        state=ASSET_STATE_PENDING,
                    ),
                    Asset(
                        asset_id="aaa-newest",
                        title="Newest",
                        manifest_url="https://cdn.example/aaa/playlist.m3u8",
                        state=ASSET_STATE_VALIDATED,
                        published_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
                    ),
                    Asset(
                        asset_id="bbb-older",
                        title="Older",
                        manifest_url="https://cdn.example/bbb/playlist.m3u8",
                        state=ASSET_STATE_VALIDATED,
                        published_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                    ),
                ]
            )
            sess.commit()

        store = PostgresAssetStore(session_factory)
        ordered_ids = [row.asset_id for row in store.list_all()]
        # Newest published first, oldest published next, NULL published last.
        assert ordered_ids == ["aaa-newest", "bbb-older", "zzz-pending"]


# ---------------------------------------------------------------------------
# TestStaffListEndpointHappyPath
# ---------------------------------------------------------------------------


class TestStaffListEndpointHappyPath:
    """200 + JSON array of StaffAssetRow when the store is wired."""

    def test_returns_200_with_full_payload(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        rows = [
            StaffAssetRow(
                asset_id="upload-1",
                title="Uploaded",
                description=None,
                state=ASSET_STATE_VALIDATED,
                manifest_url=None,
                published_at=None,
                file_path="/data/uploads/upload-1/x.mp4",
                file_size_bytes=1024,
                duration_seconds=60,
                codec_video="h264",
                codec_audio="aac",
                width_px=1920,
                height_px=1080,
                bitrate_bps=5_000_000,
                format_name="mov,mp4,m4a,3gp,3g2,mj2",
            ),
            StaffAssetRow(
                asset_id="packaged-1",
                title="Packaged",
                description="A packaged asset",
                state=ASSET_STATE_VALIDATED,
                manifest_url="https://cdn.example/packaged-1/playlist.m3u8",
                published_at=datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC),
            ),
        ]
        # 4.0 media-library-hardening: the router calls the paginated
        # list_all_page(limit=, offset=) -> (rows, total_count) method, not
        # the unbounded list_all() (still used unchanged by other callers,
        # e.g. civiccast.publish.router).
        mock_store.list_all_page.return_value = (rows, len(rows))
        app.dependency_overrides[get_postgres_store] = lambda: mock_store

        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
            response = client.get("/api/staff/assets")

        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "2"
        body = response.json()
        assert len(body) == 2
        ids = [row["asset_id"] for row in body]
        assert ids == ["upload-1", "packaged-1"]
        # Uploaded asset surfaces no manifest_url
        assert body[0]["manifest_url"] is None
        # Packaged asset surfaces both manifest_url and published_at
        assert body[1]["manifest_url"] == "https://cdn.example/packaged-1/playlist.m3u8"
        assert body[1]["published_at"] is not None
        mock_store.list_all_page.assert_called_once_with(limit=50, offset=0)
