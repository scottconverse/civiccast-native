# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the v0.7 publish dashboard and approval workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

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
        if asset is None:
            raise ValueError(f"Asset not found: {asset_id}")
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
            StaffAssetRow(
                asset_id="concert-archive",
                title="Concert archive",
                state="validated",
                manifest_url="https://cdn.example/concert/playlist.m3u8",
                retention_policy="short",
                version=1,
            ),
        ]
    )


@pytest.fixture
def publish_store() -> InMemoryPublishStore:
    return InMemoryPublishStore()


@pytest.fixture
def client(
    store: FakeAssetStore,
    publish_store: InMemoryPublishStore,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: store
    app.dependency_overrides[get_publish_store] = lambda: publish_store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def test_list_publish_assets_returns_v07_dashboard_summary(client: TestClient) -> None:
    response = client.get("/api/staff/publish/assets")
    assert response.status_code == 200

    body = response.json()
    assert body["summary"] == {
        "total_assets": 3,
        "draft": 2,
        "portal_live": 0,
        "archive_verified": 0,
        "degraded": 0,
        "needs_operator_action": 1,
    }


def test_public_record_initial_state_keeps_archive_and_reach_separate(
    client: TestClient,
) -> None:
    response = client.get("/api/staff/publish/assets/council-2026-05-08")
    assert response.status_code == 200

    body = response.json()
    assert body["dashboard_state"] == "draft"
    assert body["canonical_public"] is False
    assert body["archive_verified"] is False
    surfaces = {surface["id"]: surface for surface in body["surfaces"]}
    assert surfaces["portal"]["state"] == "pending"
    assert surfaces["internet-archive"]["required"] is True
    assert surfaces["local-nas-rsync"]["required"] is True
    assert surfaces["local-nas-zfs"]["required"] is True
    assert surfaces["youtube-live"]["required"] is False
    assert surfaces["youtube-vod"]["required"] is False
    assert surfaces["podcast"]["required"] is False
    assert surfaces["subscriber-notifications"]["required"] is False


def test_preflight_reports_portal_archive_nas_and_youtube_readiness(
    client: TestClient,
) -> None:
    """WP-03: preflight reads through the real provider registry.

    The shipped default for every kind is the mock provider, so every
    surface is `ready` (usable) even though it is also simulated -- the
    `credential_reference` is now a safe, non-secret env-var descriptor
    (never an os-keyring path; the deterministic mock credential store this
    used to pin is gone -- see civiccast.publish.readiness).
    """
    response = client.get("/api/staff/publish/assets/council-2026-05-08/preflight")
    assert response.status_code == 200

    body = response.json()
    assert body["ready"] is True
    checks = {check["id"]: check for check in body["checks"]}
    assert checks["portal"]["health"] == "ok"
    assert checks["internet-archive"]["health"] == "ok"
    assert checks["internet-archive"]["credential_reference"] == (
        "CIVICCAST_PROVIDER_INTERNET_ARCHIVE=mock"
    )
    assert "simulated" in checks["internet-archive"]["message"]
    assert checks["local-nas-rsync"]["credential_reference"] == (
        "CIVICCAST_PROVIDER_LOCAL_NAS=mock"
    )
    assert checks["local-nas-zfs"]["credential_reference"] == "CIVICCAST_PROVIDER_LOCAL_NAS=mock"
    assert checks["youtube-live"]["credential_reference"] == "CIVICCAST_PROVIDER_YOUTUBE=mock"
    assert checks["youtube-vod"]["credential_reference"] == "CIVICCAST_PROVIDER_YOUTUBE=mock"
    # Podcast has no provider yet (WP-04 owns the real path); it must never
    # read as broken (not "error") and must never gate `ready` (not required).
    assert checks["podcast"]["health"] == "unknown"
    assert checks["podcast"]["required"] is False
    # Subscriber notifications: real sends are deferred to a future release
    # (owner decision 2026-09-02) -- always "unknown", never gates `ready`.
    assert checks["subscriber-notifications"]["health"] == "unknown"
    assert checks["subscriber-notifications"]["required"] is False
    assert "coming in a future release" in checks["subscriber-notifications"]["message"].lower()


def test_preflight_and_approve_agree_when_a_selected_real_provider_is_misconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-03 end-to-end (router layer): preflight says ready=false and
    approval refuses with a controlled 409 -- never a 500 -- for the exact
    same missing real-provider configuration."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")

    preflight = client.get("/api/staff/publish/assets/council-2026-05-08/preflight")
    assert preflight.status_code == 200
    body = preflight.json()
    assert body["ready"] is False
    check = next(c for c in body["checks"] if c["id"] == "internet-archive")
    assert check["health"] == "error"
    assert "CIVICCAST_IA_ACCESS_KEY" in check["message"]

    approve = client.post(
        "/api/staff/publish/assets/council-2026-05-08/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["internet-archive"],
        },
    )
    assert approve.status_code == 409
    assert "internet-archive" in approve.json()["detail"]
    assert "CIVICCAST_IA_ACCESS_KEY" in approve.json()["detail"]

    # Unrelated, unselected surfaces are never touched by the broken config
    # (plan item 9): a portal-only approval still succeeds.
    portal_only = client.post(
        "/api/staff/publish/assets/concert-archive/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["portal"],
        },
    )
    assert portal_only.status_code == 200
    assert portal_only.json()["canonical_public"] is True


def test_preflight_blocks_unpackaged_public_record_with_actionable_next_step(
    client: TestClient,
) -> None:
    response = client.get("/api/staff/publish/assets/training-clip/preflight")
    assert response.status_code == 200

    body = response.json()
    assert body["ready"] is False
    portal = next(check for check in body["checks"] if check["id"] == "portal")
    assert portal["health"] == "error"
    assert "Run the packager" in portal["next_step"]


def test_approve_and_publish_runs_all_mock_surfaces(client: TestClient) -> None:
    response = client.post(
        "/api/staff/publish/assets/council-2026-05-08/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["dashboard_state"] == "archive_verified"
    assert body["canonical_public"] is True
    assert body["archive_verified"] is True
    surfaces = {surface["id"]: surface for surface in body["surfaces"]}
    assert surfaces["portal"]["state"] == "succeeded"
    # GauntletGate TW-1: the default providers are mocks. Their surfaces must be
    # machine-readable as simulated and must NOT carry a real-looking archive.org
    # permalink -- this assertion previously pinned the fabricated URL as correct.
    assert surfaces["internet-archive"]["simulated"] is True
    assert "archive.org" not in surfaces["internet-archive"]["url"]
    assert "SIMULATED" in surfaces["internet-archive"]["message"]
    assert surfaces["local-nas-rsync"]["simulated"] is True
    assert surfaces["local-nas-rsync"]["path"].endswith("council-2026-05-08.mp4")
    assert surfaces["local-nas-zfs"]["path"] == "zfs://civiccast/archive@council-2026-05-08"
    assert surfaces["youtube-live"]["url"].startswith("rtmps://youtube.example/live/")
    assert surfaces["youtube-vod"]["url"].startswith("https://youtube.example/watch")
    assert surfaces["podcast"]["url"] == "https://portal.example/podcast/government.xml"
    # Owner decision 2026-09-02: real subscriber notification sends are
    # deferred to a future release. This surface must never claim "succeeded"
    # -- civiccast.publish.service no longer builds or dispatches any
    # notification payload for it.
    assert surfaces["subscriber-notifications"]["state"] == "coming_soon"
    assert surfaces["subscriber-notifications"]["health"] == "unknown"
    assert "coming in a future release" in surfaces["subscriber-notifications"]["message"].lower()
    assert surfaces["internet-archive"]["verification_hash"].startswith("sha256:")


def test_portal_approval_marks_packaged_draft_as_published(
    client: TestClient, store: FakeAssetStore
) -> None:
    draft = store.get_staff_row("concert-archive")
    assert draft is not None and draft.published_at is None

    response = client.post(
        "/api/staff/publish/assets/concert-archive/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["portal"],
        },
    )

    assert response.status_code == 200
    published = store.get_staff_row("concert-archive")
    assert published is not None and published.published_at is not None


def test_portal_visibility_failure_is_recorded_and_remains_private(
    client: TestClient,
    store: FakeAssetStore,
    publish_store: InMemoryPublishStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_visibility(asset_id: str, *, published_at: datetime) -> StaffAssetRow:
        del asset_id, published_at
        raise OSError("database write failed")

    monkeypatch.setattr(store, "mark_published", fail_visibility)

    response = client.post(
        "/api/staff/publish/assets/concert-archive/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["portal"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    portal = next(surface for surface in body["surfaces"] if surface["id"] == "portal")
    assert portal["state"] == "failed"
    assert body["canonical_public"] is False
    assert store.get_staff_row("concert-archive").published_at is None
    saved = publish_store.get_run("concert-archive")
    assert saved is not None
    assert next(surface for surface in saved.surfaces if surface.id == "portal").state == "failed"


def test_retrying_failed_portal_surface_makes_the_asset_public(
    client: TestClient,
    store: FakeAssetStore,
    publish_store: InMemoryPublishStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = store.mark_published
    monkeypatch.setattr(
        store,
        "mark_published",
        lambda asset_id, *, published_at: (_ for _ in ()).throw(OSError("temporary failure")),
    )
    first = client.post(
        "/api/staff/publish/assets/concert-archive/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["portal"],
        },
    )
    assert first.status_code == 200
    monkeypatch.setattr(store, "mark_published", original)

    retry = client.post(
        "/api/staff/publish/assets/concert-archive/surfaces/portal/retry",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
        },
    )

    assert retry.status_code == 200
    assert retry.json()["canonical_public"] is True
    assert store.get_staff_row("concert-archive").published_at is not None


def test_publish_mutations_require_publish_operator_role(
    monkeypatch: pytest.MonkeyPatch,
    store: FakeAssetStore,
    publish_store: InMemoryPublishStore,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        (
            "records-token:records-1:Records Clerk:records_clerk;"
            "publish-token:publish-1:Publish Operator:publish_operator"
        ),
    )
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: store
    app.dependency_overrides[get_publish_store] = lambda: publish_store

    payload = {
        "operator_id": "staff-1",
        "operator_display_name": "Avery Operator",
    }
    with TestClient(app, headers={"Authorization": "Bearer records-token"}) as records_client:
        rejected = records_client.post(
            "/api/staff/publish/assets/council-2026-05-08/approve",
            json=payload,
        )
    assert rejected.status_code == 403
    assert "publish_operator" in rejected.json()["detail"]

    with TestClient(app, headers={"Authorization": "Bearer publish-token"}) as publish_client:
        approved = publish_client.post(
            "/api/staff/publish/assets/council-2026-05-08/approve",
            json=payload,
        )
    assert approved.status_code == 200


def test_retry_one_surface_preserves_other_publish_results(client: TestClient) -> None:
    approved = client.post(
        "/api/staff/publish/assets/council-2026-05-08/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": ["portal", "internet-archive"],
        },
    )
    assert approved.status_code == 200

    retry = client.post(
        "/api/staff/publish/assets/council-2026-05-08/surfaces/internet-archive/retry",
        json={
            "operator_id": "staff-2",
            "operator_display_name": "Riley Retry",
        },
    )
    assert retry.status_code == 200

    surfaces = {surface["id"]: surface for surface in retry.json()["surfaces"]}
    assert surfaces["portal"]["state"] == "succeeded"
    assert surfaces["internet-archive"]["state"] == "succeeded"
    assert surfaces["internet-archive"]["retry_count"] == 1
    assert surfaces["local-nas-rsync"]["state"] == "pending"


def test_retry_unknown_surface_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/staff/publish/assets/council-2026-05-08/surfaces/not-real/retry",
        json={
            "operator_id": "staff-2",
            "operator_display_name": "Riley Retry",
        },
    )
    assert response.status_code == 404
    assert "Unknown publish surface" in response.json()["detail"]


def test_public_record_archive_override_requires_audit_justification(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/staff/publish/assets/council-2026-05-08/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "overrides": [
                {
                    "surface_id": "internet-archive",
                    "justification": "Withheld under state-law redaction review.",
                }
            ],
        },
    )
    assert response.status_code == 200

    surface = next(s for s in response.json()["surfaces"] if s["id"] == "internet-archive")
    assert surface["state"] == "overridden"
    assert "state-law redaction" in surface["override_justification"]


def test_explicit_empty_surface_selection_does_not_publish_every_surface(
    client: TestClient, store: FakeAssetStore
) -> None:
    response = client.post(
        "/api/staff/publish/assets/concert-archive/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
            "approved_surface_ids": [],
            "overrides": [
                {
                    "surface_id": "internet-archive",
                    "justification": "Withheld under a documented legal review.",
                }
            ],
        },
    )

    assert response.status_code == 200
    surfaces = {surface["id"]: surface for surface in response.json()["surfaces"]}
    assert surfaces["internet-archive"]["state"] == "overridden"
    assert surfaces["portal"]["state"] == "pending"
    draft = store.get_staff_row("concert-archive")
    assert draft is not None and draft.published_at is None


def test_unpackaged_asset_blocks_approval_with_actionable_409(client: TestClient) -> None:
    response = client.post(
        "/api/staff/publish/assets/training-clip/approve",
        json={
            "operator_id": "staff-1",
            "operator_display_name": "Avery Operator",
        },
    )
    assert response.status_code == 409
    assert "manifest_url" in response.json()["detail"]
    assert "Run the packager" in response.json()["detail"]


def test_publish_dashboard_503_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/publish/assets")

    assert response.status_code == 503
    assert "Durable storage is not ready" in response.json()["detail"]


def test_unknown_publish_asset_returns_404(client: TestClient) -> None:
    response = client.get("/api/staff/publish/assets/missing-asset")
    assert response.status_code == 404
    assert response.json()["detail"] == "Asset not found: missing-asset"
