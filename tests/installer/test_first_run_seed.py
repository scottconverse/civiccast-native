# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for audit finding A-1 -- first-run sample content + starter schedule seeding.

Covers: seed-on (content + schedule seeded through the real ingest -> package
-> publish(portal) pipeline and a starter schedule item created), seed-off
(nothing seeded, toggle respected), a failure at each step being persisted
and surfaced (never a silent best-effort per audit K3-1), the dismiss
action, and a successful retry after a fixed failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer import service as installer_service
from civiccast.installer.router import get_postgres_store, get_publish_store, get_schedule_store
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import ASSET_STATE_VALIDATED, StaffAssetRow, UploadedAssetResponse
from civiccast.schedule.store import AssetNotFoundError
from civiccast.stream.packager import VodPackageResult


_FFPROBE_SAMPLE = FfprobeResult(
    duration_seconds=20,
    codec_video="h264",
    codec_audio="aac",
    width_px=640,
    height_px=360,
    bitrate_bps=300_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


class FakeFirstRunAssetStore:
    """Minimal in-memory stand-in for the Postgres asset store."""

    def __init__(self) -> None:
        self.ingested: dict[str, dict[str, object]] = {}
        self.packaged: dict[str, str] = {}
        self.published: dict[str, datetime] = {}
        self.fail_mark_packaged = False
        self.fail_mark_published = False

    def get_staff_row(self, asset_id: str) -> StaffAssetRow | None:
        if asset_id not in self.ingested:
            return None
        return self._row(asset_id)

    def ingest_upload(
        self,
        *,
        asset_id: str,
        title: str,
        description: str | None,
        file_path: str,
        file_size_bytes: int,
        ffprobe_result: FfprobeResult,
    ) -> UploadedAssetResponse:
        self.ingested[asset_id] = {
            "title": title,
            "description": description,
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
        }
        return UploadedAssetResponse(
            asset_id=asset_id,
            title=title,
            description=description,
            state=ASSET_STATE_VALIDATED,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            duration_seconds=ffprobe_result.duration_seconds,
            codec_video=ffprobe_result.codec_video,
            codec_audio=ffprobe_result.codec_audio,
            width_px=ffprobe_result.width_px,
            height_px=ffprobe_result.height_px,
            bitrate_bps=ffprobe_result.bitrate_bps,
            format_name=ffprobe_result.format_name,
        )

    def mark_packaged(self, asset_id: str, manifest_url: str) -> StaffAssetRow:
        if self.fail_mark_packaged:
            raise RuntimeError("simulated mark_packaged failure")
        self.packaged[asset_id] = manifest_url
        return self._row(asset_id)

    def mark_published(self, asset_id: str, *, published_at: datetime) -> StaffAssetRow:
        if self.fail_mark_published:
            raise RuntimeError("simulated mark_published failure")
        self.published[asset_id] = published_at
        return self._row(asset_id)

    def _row(self, asset_id: str) -> StaffAssetRow:
        record = self.ingested[asset_id]
        return StaffAssetRow(
            asset_id=asset_id,
            title=str(record["title"]),
            description=record["description"],  # type: ignore[arg-type]
            state=ASSET_STATE_VALIDATED,
            manifest_url=self.packaged.get(asset_id),
            published_at=self.published.get(asset_id),
            file_path=str(record["file_path"]),
            file_size_bytes=int(record["file_size_bytes"]),  # type: ignore[arg-type]
        )


class FakeScheduleStore:
    def __init__(self) -> None:
        self.created: list[object] = []
        self.fail: Exception | None = None

    def create(self, payload: object) -> SimpleNamespace:
        if self.fail is not None:
            raise self.fail
        self.created.append(payload)
        return SimpleNamespace(id=uuid4())


def _write_sample(path: Path, **_kwargs: object) -> None:
    path.write_bytes(b"sample-video")


def _fake_pack_vod_asset(input_path: Path, output_dir: Path, **_kwargs: object) -> VodPackageResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "playlist.m3u8"
    manifest_path.write_text("#EXTM3U\n", encoding="utf-8")
    return VodPackageResult(manifest_path=manifest_path, renditions=[], output_dir=output_dir)


def _client(
    asset_store: FakeFirstRunAssetStore,
    schedule_store: FakeScheduleStore,
    publish_store: InMemoryPublishStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_postgres_store] = lambda: asset_store
    app.dependency_overrides[get_schedule_store] = lambda: schedule_store
    app.dependency_overrides[get_publish_store] = lambda: publish_store
    return TestClient(app)


def _setup_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "station_name": "Pinegrove School Board",
        "admin_display_name": "Avery Admin",
        "admin_username": "avery",
        "admin_password": "correct horse battery staple",
        "recovery_kit_destination": "printed and stored in the clerk safe",
        "default_channel_id": "government",
    }
    payload.update(overrides)
    return payload


@contextmanager
def _seed_patches() -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(
            patch("civiccast.installer.service._write_sample_video", side_effect=_write_sample)
        )
        stack.enter_context(
            patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE)
        )
        stack.enter_context(patch("civiccast.installer.service.validate_ingest"))
        stack.enter_context(
            patch("civiccast.installer.service.pack_vod_asset", side_effect=_fake_pack_vod_asset)
        )
        yield


def test_first_admin_setup_seeds_sample_content_and_starter_schedule(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        assert setup_response.status_code == 200
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        status_response = client.get("/api/staff/installer/sample-seed-status", headers=auth)

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "succeeded"
    assert body["sample_content_enabled"] is True
    assert body["initial_schedule_enabled"] is True
    assert body["asset_id"] is not None
    assert body["schedule_item_id"] is not None
    assert body["dismissed"] is False

    assert len(asset_store.ingested) == 1
    (asset_id, record) = next(iter(asset_store.ingested.items()))
    assert record["title"] == "Sample: Welcome to CivicCast"
    assert asset_store.packaged[asset_id].startswith("/media/vod/")
    assert asset_id in asset_store.published

    assert len(schedule_store.created) == 1
    scheduled = schedule_store.created[0]
    assert scheduled.asset_id == asset_id
    assert scheduled.channel_id == "government"
    assert scheduled.mode == "premiere"

    run = publish_store.get_run(asset_id)
    assert run is not None
    portal_surface = next(s for s in run.surfaces if s.id == "portal")
    assert portal_surface.state == "succeeded"
    # Only the portal surface should have been touched -- no IA/YouTube/etc
    # network calls during unattended first-run setup.
    other_surfaces = [s for s in run.surfaces if s.id != "portal"]
    assert all(s.state == "pending" for s in other_surfaces)


def test_first_admin_setup_skips_seeding_when_sample_content_disabled(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin",
            json=_setup_payload(sample_content_enabled=False),
        )
        token = setup_response.json()["operator_console_token"]
        status_response = client.get(
            "/api/staff/installer/sample-seed-status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert setup_response.status_code == 200
    assert status_response.json()["status"] == "not_applicable"
    assert status_response.json()["sample_content_enabled"] is False
    assert asset_store.ingested == {}
    assert schedule_store.created == []


def test_first_admin_setup_seeds_content_without_schedule_when_toggle_off(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin",
            json=_setup_payload(initial_schedule_enabled=False),
        )
        token = setup_response.json()["operator_console_token"]
        status_response = client.get(
            "/api/staff/installer/sample-seed-status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert len(asset_store.ingested) == 1
    assert schedule_store.created == []
    body = status_response.json()
    assert body["status"] == "succeeded"
    assert body["asset_id"] is not None
    assert body["schedule_item_id"] is None


def test_first_run_seed_failure_is_persisted_visible_and_retryable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    asset_store.fail_mark_packaged = True
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        assert setup_response.status_code == 200  # first-admin never blocks on seeding
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        failed_status = client.get("/api/staff/installer/sample-seed-status", headers=auth)
        assert failed_status.status_code == 200
        failed_body = failed_status.json()
        assert failed_body["status"] == "failed"
        assert failed_body["failed_step"] == "package"
        assert "simulated mark_packaged failure" in failed_body["error_message"]
        assert failed_body["dismissed"] is False

        dismissed = client.post("/api/staff/installer/sample-seed-status/dismiss", headers=auth)
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "failed"
        assert dismissed.json()["dismissed"] is True

        # Fix the underlying problem, then retry.
        asset_store.fail_mark_packaged = False
        retried = client.post("/api/staff/installer/sample-seed-status/retry", headers=auth)

    assert retried.status_code == 200
    retried_body = retried.json()
    assert retried_body["status"] == "succeeded"
    assert retried_body["asset_id"] is not None
    assert retried_body["dismissed"] is False
    # A new attempt allocates a fresh asset id rather than reusing the failed one.
    assert len(asset_store.ingested) == 2


def test_first_run_seed_fails_loudly_without_upload_storage(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        token = setup_response.json()["operator_console_token"]
        status_response = client.get(
            "/api/staff/installer/sample-seed-status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert setup_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["failed_step"] == "ingest"
    assert "Upload storage" in body["error_message"]


def test_first_run_seed_schedule_step_failure_keeps_the_seeded_asset_id(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    schedule_store.fail = AssetNotFoundError("asset_id 'sample-welcome-x' does not exist.")
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        token = setup_response.json()["operator_console_token"]
        status_response = client.get(
            "/api/staff/installer/sample-seed-status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert setup_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["failed_step"] == "schedule"
    # The asset was already published to the portal -- that half of the
    # seed is real and should not be hidden just because the schedule step
    # failed afterward.
    assert body["asset_id"] is not None
    assert len(asset_store.ingested) == 1


def test_retry_after_schedule_step_failure_resumes_instead_of_reseeding(
    monkeypatch, tmp_path
) -> None:
    """Codex review, PR #419 P2: retrying a schedule-only failure must not
    publish a second sample asset while the first stays public."""
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    schedule_store.fail = AssetNotFoundError("asset_id 'sample-welcome-x' does not exist.")
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        failed = client.get("/api/staff/installer/sample-seed-status", headers=auth).json()
        assert failed["status"] == "failed"
        assert failed["failed_step"] == "schedule"
        original_asset_id = failed["asset_id"]
        assert original_asset_id is not None
        assert len(asset_store.ingested) == 1

        # Fix the underlying problem, then retry.
        schedule_store.fail = None
        retried = client.post("/api/staff/installer/sample-seed-status/retry", headers=auth)

    assert retried.status_code == 200
    retried_body = retried.json()
    assert retried_body["status"] == "succeeded"
    # Same asset id as before -- resumed, not reseeded.
    assert retried_body["asset_id"] == original_asset_id
    assert retried_body["schedule_item_id"] is not None
    # No second sample was ingested or published.
    assert len(asset_store.ingested) == 1
    assert list(asset_store.published) == [original_asset_id]
    assert len(schedule_store.created) == 1


def test_retry_after_ingest_failure_still_reseeds_from_scratch(monkeypatch, tmp_path) -> None:
    """Only a schedule-step failure (asset already published) resumes.
    A failure with no published asset yet has nothing to resume from."""
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    asset_store.fail_mark_packaged = True
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        failed = client.get("/api/staff/installer/sample-seed-status", headers=auth).json()
        assert failed["status"] == "failed"
        assert failed["failed_step"] == "package"
        assert failed["asset_id"] is None

        asset_store.fail_mark_packaged = False
        retried = client.post("/api/staff/installer/sample-seed-status/retry", headers=auth)

    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"
    # A fresh attempt allocates a new asset id -- there was nothing to resume
    # (the first attempt never made it past packaging, so it never
    # published anything to leave behind).
    assert len(asset_store.ingested) == 2


def test_abandoned_pending_seed_is_reconciled_to_failed_on_read(monkeypatch, tmp_path) -> None:
    """Codex review, PR #419 P2: a "pending" record from a background task
    that never got to run (process killed/restarted between
    mark_first_run_seed_pending() and the task actually starting) must not
    stay invisibly "pending" forever -- SampleSeedNoticeView renders
    nothing for "pending", so an un-reconciled record is a silent failure,
    which audit K3-1 requires this feature never produce."""
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        assert setup_response.status_code == 200
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # The real setup flow already ran seeding to completion (TestClient
        # executes background tasks synchronously) -- simulate a later
        # *retry* attempt whose background task never got to run at all:
        # mark pending, then never call run_first_run_seed(), and backdate
        # started_at past the staleness threshold.
        installer_service.mark_first_run_seed_pending()
        stale_started_at = (
            datetime.now(UTC) - installer_service._FIRST_RUN_SEED_STALE_AFTER - timedelta(minutes=1)
        )
        installer_service._save_first_run_seed_state(started_at=stale_started_at.isoformat())

        status_response = client.get("/api/staff/installer/sample-seed-status", headers=auth)

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["failed_step"] is None
    assert "interrupted" in body["error_message"].lower()
    assert body["dismissed"] is False

    # Reconciliation persisted -- a second read sees the same failed record,
    # not a re-derived "still pending" guess.
    second_read = installer_service.read_first_run_seed_status()
    assert second_read.status == "failed"
    assert second_read.completed_at is not None


def test_pending_seed_within_the_staleness_window_is_left_alone(monkeypatch, tmp_path) -> None:
    """A pending record that is merely a few seconds old (the normal,
    still-in-flight case) must not be reconciled away."""
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    asset_store = FakeFirstRunAssetStore()
    schedule_store = FakeScheduleStore()
    publish_store = InMemoryPublishStore()

    with _client(asset_store, schedule_store, publish_store) as client, _seed_patches():
        setup_response = client.post(
            "/api/setup/first-admin", json=_setup_payload()
        )
        token = setup_response.json()["operator_console_token"]
        auth = {"Authorization": f"Bearer {token}"}

        installer_service.mark_first_run_seed_pending()

        status_response = client.get("/api/staff/installer/sample-seed-status", headers=auth)

    assert setup_response.status_code == 200
    assert status_response.json()["status"] == "pending"
