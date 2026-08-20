# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""approve_publish behavior with real-style providers (Beta sprint B5).

Two contracts on top of the adapter contract tests:
- full-media publishing: when the caller resolved the asset's local recording
  and the provider supports paths (``upload_path`` / ``upload_vod_path``), the
  real file is what gets published — not the verification payload;
- failure isolation: a provider exception marks that one surface ``failed``
  (still retryable) instead of failing the whole approval with a 500.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from civiccast.archive.local_nas import LocalNasArchiveClient, LocalNasSettings
from civiccast.archive.models import MockInternetArchiveClient, MockLocalNasArchiveClient
from civiccast.platform.providers import ProviderRegistry
from civiccast.publish.models import PublishApprovalRequest
from civiccast.publish.service import approve_publish
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.syndicate.models import MockYouTubeClient


def _asset() -> StaffAssetRow:
    return StaffAssetRow(
        asset_id="council-2026-06-10",
        title="Council - June 10, 2026",
        state="validated",
        manifest_url="https://cdn.example/council-2026-06-10/playlist.m3u8",
        published_at=datetime(2026, 6, 10, 20, 0, tzinfo=UTC),
        retention_policy="meeting",
        version=1,
    )


def _request(*surface_ids: str) -> PublishApprovalRequest:
    return PublishApprovalRequest(
        operator_id="staff-1",
        operator_display_name="Avery Operator",
        approved_surface_ids=list(surface_ids),
    )


class _PathAwareArchive(MockInternetArchiveClient):
    def __init__(self) -> None:
        self.uploaded_paths: list[Path] = []

    def upload_path(self, *, asset_id: str, path: Path):  # type: ignore[no-untyped-def]
        self.uploaded_paths.append(path)
        return super().upload(asset_id=asset_id, payload=path.read_bytes())


class _PathAwareYouTube(MockYouTubeClient):
    def __init__(self) -> None:
        self.uploaded_paths: list[Path] = []

    def upload_vod_path(self, *, asset_id: str, path: Path):  # type: ignore[no-untyped-def]
        self.uploaded_paths.append(path)
        return super().upload_vod(asset_id=asset_id)


class _ExplodingArchive:
    def upload(self, *, asset_id: str, payload: bytes):  # type: ignore[no-untyped-def]
        raise RuntimeError("archive.org unreachable")


def _registry(ia=None, youtube=None, nas=None) -> ProviderRegistry:  # type: ignore[no-untyped-def]
    registry = ProviderRegistry()
    registry.register("internet_archive", "mock", lambda: ia or MockInternetArchiveClient())
    registry.register("local_nas", "mock", lambda: nas or MockLocalNasArchiveClient())
    registry.register("youtube", "mock", lambda: youtube or MockYouTubeClient())
    return registry


class TestFullMediaPublishing:
    def test_media_path_reaches_path_aware_providers(self, tmp_path: Path) -> None:
        media = tmp_path / "council-2026-06-10.mp4"
        media.write_bytes(b"recording-bytes")
        ia = _PathAwareArchive()
        youtube = _PathAwareYouTube()

        record = approve_publish(
            asset=_asset(),
            request=_request("internet-archive", "youtube-vod"),
            store=InMemoryPublishStore(),
            registry=_registry(ia=ia, youtube=youtube),
            media_path=media,
        )

        assert ia.uploaded_paths == [media]
        assert youtube.uploaded_paths == [media]
        states = {surface.id: surface.state for surface in record.surfaces}
        assert states["internet-archive"] == "succeeded"
        assert states["youtube-vod"] == "succeeded"

    def test_payload_fallback_without_media_or_path_support(self) -> None:
        record = approve_publish(
            asset=_asset(),
            request=_request("internet-archive"),
            store=InMemoryPublishStore(),
            registry=_registry(),
            media_path=None,
        )

        surface = next(s for s in record.surfaces if s.id == "internet-archive")
        assert surface.state == "succeeded"


class TestProviderFailureIsolation:
    def test_provider_exception_fails_only_that_surface(self) -> None:
        record = approve_publish(
            asset=_asset(),
            request=_request("internet-archive", "youtube-vod"),
            store=InMemoryPublishStore(),
            registry=_registry(ia=_ExplodingArchive()),
        )

        surfaces = {surface.id: surface for surface in record.surfaces}
        assert surfaces["internet-archive"].state == "failed"
        assert "archive.org unreachable" in (surfaces["internet-archive"].next_step or "")
        assert surfaces["youtube-vod"].state == "succeeded", (
            "one provider failure must not take down the other surfaces"
        )


class _ExplodingNas:
    def archive(self, *, asset_id: str, payload: bytes):  # type: ignore[no-untyped-def]
        raise RuntimeError("NAS mount unreachable")


class TestRealNasSurfaces:
    def test_real_nas_writes_verified_files_for_both_surfaces(self, tmp_path: Path) -> None:
        nas = LocalNasArchiveClient(LocalNasSettings(archive_root=tmp_path))

        record = approve_publish(
            asset=_asset(),
            request=_request("local-nas-rsync", "local-nas-zfs"),
            store=InMemoryPublishStore(),
            registry=_registry(nas=nas),
        )

        surfaces = {surface.id: surface for surface in record.surfaces}
        assert surfaces["local-nas-rsync"].state == "succeeded"
        assert surfaces["local-nas-zfs"].state == "succeeded"
        copy_path = Path(surfaces["local-nas-rsync"].path or "")
        snapshot_path = Path(surfaces["local-nas-zfs"].path or "")
        assert copy_path.exists() and copy_path.is_relative_to(tmp_path)
        assert snapshot_path.exists() and snapshot_path.is_relative_to(tmp_path)
        for surface, on_disk in (
            (surfaces["local-nas-rsync"], copy_path),
            (surfaces["local-nas-zfs"], snapshot_path),
        ):
            observed = f"sha256:{hashlib.sha256(on_disk.read_bytes()).hexdigest()}"
            assert surface.verification_hash == observed

    def test_real_nas_archives_the_actual_media_file(self, tmp_path: Path) -> None:
        media = tmp_path / "source" / "council-2026-06-10.mp4"
        media.parent.mkdir()
        media.write_bytes(b"recording-bytes" * 1024)
        nas_root = tmp_path / "nas"
        nas_root.mkdir()
        nas = LocalNasArchiveClient(LocalNasSettings(archive_root=nas_root))

        record = approve_publish(
            asset=_asset(),
            request=_request("local-nas-rsync"),
            store=InMemoryPublishStore(),
            registry=_registry(nas=nas),
            media_path=media,
        )

        surface = next(s for s in record.surfaces if s.id == "local-nas-rsync")
        assert surface.state == "succeeded"
        archived = Path(surface.path or "")
        assert archived.suffix == ".mp4"
        assert archived.read_bytes() == media.read_bytes()

    def test_nas_failure_marks_only_nas_surfaces_failed(self) -> None:
        record = approve_publish(
            asset=_asset(),
            request=_request("local-nas-rsync", "local-nas-zfs", "youtube-vod"),
            store=InMemoryPublishStore(),
            registry=_registry(nas=_ExplodingNas()),
        )

        surfaces = {surface.id: surface for surface in record.surfaces}
        assert surfaces["local-nas-rsync"].state == "failed"
        assert surfaces["local-nas-zfs"].state == "failed"
        assert "NAS mount unreachable" in (surfaces["local-nas-rsync"].next_step or "")
        assert surfaces["youtube-vod"].state == "succeeded"

    def test_one_publish_run_makes_exactly_one_snapshot(self, tmp_path: Path) -> None:
        nas = LocalNasArchiveClient(LocalNasSettings(archive_root=tmp_path))

        approve_publish(
            asset=_asset(),
            request=_request("local-nas-rsync", "local-nas-zfs"),
            store=InMemoryPublishStore(),
            registry=_registry(nas=nas),
        )

        snapshots = list((tmp_path / "snapshots" / "council-2026-06-10").iterdir())
        assert len(snapshots) == 1, (
            "approving both NAS surfaces in one run must archive once, not twice"
        )
