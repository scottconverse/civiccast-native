# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publishing a recording queues its offline captions (keystone K3).

The gap K3 names is that nothing connected a published asset to the caption
engine. These are the contract tests for that connection: approving publish
must leave a queued caption job pointing at the recording's real source file
and its real package directory -- and must not pretend to have queued one
when it cannot.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.captions.vod_job import (
    OFFLINE_CAPTION_JOB_STATE_COMPLETE,
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    InMemoryOfflineCaptionJobStore,
)
from civiccast.publish.router import (
    _resolve_caption_package_dir,
    get_caption_job_store,
    get_publish_store,
)
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.schedule.router import get_postgres_store

_ASSET_ID = "council-2026-08-16"
_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}
_APPROVAL = {"operator_id": "staff-1", "operator_display_name": "Avery Operator"}


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
def upload_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(root))
    return root


@pytest.fixture
def source_file(upload_root: Path) -> Path:
    path = upload_root / f"{_ASSET_ID}.mp4"
    path.write_bytes(b"not really video")
    return path


@pytest.fixture
def job_store() -> InMemoryOfflineCaptionJobStore:
    return InMemoryOfflineCaptionJobStore()


def _asset(source_file: Path | None) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=_ASSET_ID,
        title="Council - August 16, 2026",
        state="validated",
        manifest_url=f"/media/vod/{_ASSET_ID}/playlist.m3u8",
        file_path=str(source_file) if source_file is not None else None,
        retention_policy="meeting",
        version=1,
    )


@pytest.fixture
def publish_store() -> InMemoryPublishStore:
    """Shared so a test can assert nothing was published, not just the code."""

    return InMemoryPublishStore()


@pytest.fixture
def client(
    source_file: Path,
    job_store: InMemoryOfflineCaptionJobStore,
    publish_store: InMemoryPublishStore,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: FakeAssetStore([_asset(source_file)])
    app.dependency_overrides[get_publish_store] = lambda: publish_store
    app.dependency_overrides[get_caption_job_store] = lambda: job_store
    with TestClient(app, headers=_STAFF_HEADERS) as test_client:
        yield test_client


class TestPublishEnqueuesOfflineCaptions:
    def test_approval_queues_a_job_for_the_recording(
        self,
        client: TestClient,
        job_store: InMemoryOfflineCaptionJobStore,
        source_file: Path,
        upload_root: Path,
    ) -> None:
        response = client.post(f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL)

        assert response.status_code == 200
        job = job_store.active_for_asset(_ASSET_ID)
        assert job is not None
        assert job.state == OFFLINE_CAPTION_JOB_STATE_PENDING
        assert Path(job.source_path) == source_file
        # The package directory the job will caption must be the same one
        # the packager wrote and /media/vod serves.
        assert Path(job.package_dir) == (upload_root / ".civiccast-packages" / _ASSET_ID).resolve()

    def test_reapproving_does_not_requeue_work_an_operator_is_reviewing(
        self,
        client: TestClient,
        job_store: InMemoryOfflineCaptionJobStore,
    ) -> None:
        client.post(f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL)
        first = job_store.active_for_asset(_ASSET_ID)
        client.post(f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL)
        second = job_store.active_for_asset(_ASSET_ID)

        assert first is not None and second is not None
        assert first.job_id == second.job_id

    def test_a_portal_retry_also_queues_captions(
        self,
        client: TestClient,
        job_store: InMemoryOfflineCaptionJobStore,
    ) -> None:
        """A portal retry that actually publishes an uncaptioned asset enqueues."""
        response = client.post(
            f"/api/staff/publish/assets/{_ASSET_ID}/surfaces/portal/retry",
            json=_APPROVAL,
        )

        assert response.status_code == 200
        assert response.json()["canonical_public"] is True
        assert job_store.active_for_asset(_ASSET_ID) is not None

    def test_a_portal_retry_that_fails_to_publish_does_not_queue_captions(
        self,
        source_file: Path,
        job_store: InMemoryOfflineCaptionJobStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Refines audit finding 5: ``surface_id == "portal"`` alone is not enough.

        Checking only ``staff_asset.published_at`` (set by an *earlier*
        successful publish) is also not enough -- an asset can already be
        public from a prior approval, and *this* retry's own
        ``asset_store.mark_published`` write can still fail (mirrors
        ``test_portal_visibility_failure_is_recorded_and_remains_private``
        in tests/publish/test_router.py, the first-approval version of this
        failure). ``published_at`` stays set to its old value in that case
        -- ``_apply_portal_visibility`` returns the unchanged ``staff_asset``
        on a ``mark_published`` failure -- so only the *record's* portal
        surface state (``"succeeded"`` only when this call's write actually
        landed) can tell a real re-publish apart from a no-op failed retry.
        Queueing captions on the no-op would start a transcription pass
        that isn't owed by anything this retry actually did.
        """
        asset_store = FakeAssetStore([_asset(source_file)])
        app = create_app()
        app.dependency_overrides[get_postgres_store] = lambda: asset_store
        app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
        app.dependency_overrides[get_caption_job_store] = lambda: job_store

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            # First, a real successful publish -- the asset is genuinely
            # public and its (first) caption job is queued and completed.
            approved = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL
            )
            assert approved.status_code == 200
            first_job = job_store.active_for_asset(_ASSET_ID)
            assert first_job is not None
            job_store.save(
                first_job.model_copy(
                    update={"state": OFFLINE_CAPTION_JOB_STATE_COMPLETE, "next_attempt_at": None}
                )
            )
            assert asset_store.get_staff_row(_ASSET_ID).published_at is not None  # type: ignore[union-attr]

            # Now a portal retry whose own visibility write fails -- the
            # asset stays public from the earlier approval, but this retry
            # made nothing newly public.
            def _fail_visibility(asset_id: str, *, published_at: datetime) -> StaffAssetRow:
                del asset_id, published_at
                raise OSError("database write failed")

            monkeypatch.setattr(asset_store, "mark_published", _fail_visibility)

            retry = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/surfaces/portal/retry",
                json=_APPROVAL,
            )

        assert retry.status_code == 200
        body = retry.json()
        portal = next(surface for surface in body["surfaces"] if surface["id"] == "portal")
        assert portal["state"] == "failed"
        # published_at is still non-None -- it survives from the earlier
        # successful approval -- which is exactly why a naive
        # ``published_at is not None`` check is not sufficient here.
        assert asset_store.get_staff_row(_ASSET_ID).published_at is not None  # type: ignore[union-attr]
        assert job_store.active_for_asset(_ASSET_ID) is None

    def test_retrying_a_non_portal_surface_does_not_requeue_an_already_captioned_asset(
        self,
        source_file: Path,
        job_store: InMemoryOfflineCaptionJobStore,
    ) -> None:
        """Audit finding 5: an unrelated surface retry (e.g. YouTube) on an
        asset whose captions already completed must not start a brand-new
        transcription pass. Portal success is what starts the caption
        obligation; ``active_for_asset`` only matches pending/
        awaiting_review, so a naive unconditional queue call on any retry
        would re-transcribe a `complete` asset every time an operator
        retries an unrelated surface.

        Uses its own app/asset-store (rather than the module ``client``
        fixture) because the scenario needs ``published_at`` to survive
        from the approval request into the later retry request -- the
        shared fixture's asset store is rebuilt fresh per request, which
        would mask this finding behind an unrelated ``published_at is
        None`` no-op instead of exercising the surface-id gate.
        """

        asset_store = FakeAssetStore([_asset(source_file)])
        app = create_app()
        app.dependency_overrides[get_postgres_store] = lambda: asset_store
        app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
        app.dependency_overrides[get_caption_job_store] = lambda: job_store

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            approved = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL
            )
            assert approved.status_code == 200
            queued = job_store.active_for_asset(_ASSET_ID)
            assert queued is not None
            # Simulate the worker having already finished captioning this asset.
            job_store.save(
                queued.model_copy(
                    update={"state": OFFLINE_CAPTION_JOB_STATE_COMPLETE, "next_attempt_at": None}
                )
            )
            assert asset_store.get_staff_row(_ASSET_ID).published_at is not None  # type: ignore[union-attr]

            retry = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/surfaces/youtube-vod/retry",
                json=_APPROVAL,
            )

        assert retry.status_code == 200
        assert job_store.active_for_asset(_ASSET_ID) is None

    def test_a_queueing_failure_blocks_approval_with_a_409(
        self,
        client: TestClient,
        publish_store: InMemoryPublishStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A caption job that cannot be queued must stop the publish.

        This used to assert the opposite -- queueing was best-effort, so a
        failure was logged and the publish returned 200. That produced the
        state the whole caption policy exists to prevent: a recording on the
        public record with no caption job, no captions coming, and nothing
        but a log line to say so. Publish-first still stands (the recording
        does not wait for review), but a station that cannot even record the
        obligation does not publish.
        """

        import civiccast.publish.router as publish_router

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("caption queue unavailable")

        monkeypatch.setattr(publish_router, "enqueue_offline_caption_job", _boom)

        response = client.post(f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Nothing was published." in detail
        assert "caption queue unavailable" in detail
        # And it really did not publish: no surface record was written.
        assert publish_store.get_run(_ASSET_ID) is None


class TestPublishWithoutCaptionableSource:
    def test_an_asset_with_no_local_file_is_skipped_not_queued(
        self,
        source_file: Path,
        job_store: InMemoryOfflineCaptionJobStore,
    ) -> None:
        app = create_app()
        app.dependency_overrides[get_postgres_store] = lambda: FakeAssetStore([_asset(None)])
        app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
        app.dependency_overrides[get_caption_job_store] = lambda: job_store

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            response = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL
            )

        assert response.status_code == 200
        assert job_store.active_for_asset(_ASSET_ID) is None

    def test_no_caption_job_store_configured_blocks_a_captionable_asset(
        self,
        source_file: Path,
    ) -> None:
        """No caption job store + a real recording = no publish.

        Previously "survivable" (200). A station with no caption job store has
        lost durable storage; publishing a recording it can never caption is
        not survival, it is a public record with a permanent accessibility
        gap and no record that one is owed.
        """

        app = create_app()
        app.dependency_overrides[get_postgres_store] = lambda: FakeAssetStore([_asset(source_file)])
        app.dependency_overrides[get_publish_store] = lambda: InMemoryPublishStore()
        app.dependency_overrides[get_caption_job_store] = lambda: None

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            response = test_client.post(
                f"/api/staff/publish/assets/{_ASSET_ID}/approve", json=_APPROVAL
            )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Nothing was published." in detail
        # Names what the operator should go and look at.
        assert "System health" in detail


class TestLiveFinalizedRecordingPackageDir:
    """A live-finalized recording's package is NOT under the upload root.

    Regression: making an unqueueable caption job block approval turned a
    deferred stage-two gap into a publish-blocking 409. A station that
    broadcasts live may have no CIVICCAST_UPLOAD_DIR at all, and
    resolve_vod_package_dir only knows the upload convention, so approving a
    live recording was refused with "this station has no upload storage
    configured" -- about an asset whose package was sitting on disk exactly
    where the finalization job said it was. Caught by the randomized-order
    CI suite, which surfaced it through
    tests/live/test_finalization_worker_app_wiring.py.

    The resolver now mirrors media_router._package_dir_for_asset: the
    finalization job's local_package_manifest_path wins, and the upload
    convention is the fallback.
    """

    def test_the_live_finalization_manifest_wins_over_the_upload_convention(
        self, tmp_path: Path
    ) -> None:
        package_dir = tmp_path / "recordings" / "ls_abc-hls"
        package_dir.mkdir(parents=True)
        manifest = package_dir / "playlist.m3u8"
        manifest.write_text("#EXTM3U\n", encoding="utf-8")

        class _Worker:
            def get_status(self, asset_id: str) -> object:
                return SimpleNamespace(local_package_manifest_path=str(manifest))

        resolved = _resolve_caption_package_dir(_ASSET_ID, _Worker())

        assert resolved == package_dir.resolve()

    def test_no_finalization_job_falls_back_to_the_upload_convention(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class _Worker:
            def get_status(self, asset_id: str) -> object:
                return SimpleNamespace(local_package_manifest_path=None)

        import civiccast.publish.router as publish_router

        monkeypatch.setattr(
            publish_router, "resolve_vod_package_dir", lambda asset_id: tmp_path / asset_id
        )

        assert _resolve_caption_package_dir(_ASSET_ID, _Worker()) == tmp_path / _ASSET_ID

    def test_an_unwired_worker_falls_back_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ephemeral mode has no finalization worker at all."""

        import civiccast.publish.router as publish_router

        monkeypatch.setattr(
            publish_router, "resolve_vod_package_dir", lambda asset_id: tmp_path / asset_id
        )

        assert _resolve_caption_package_dir(_ASSET_ID, None) == tmp_path / _ASSET_ID

    def test_neither_convention_resolves_is_still_a_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The gate stays closed when the package really cannot be located."""

        import civiccast.publish.router as publish_router

        monkeypatch.setattr(publish_router, "resolve_vod_package_dir", lambda asset_id: None)

        assert _resolve_caption_package_dir(_ASSET_ID, None) is None
