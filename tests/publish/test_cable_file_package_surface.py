# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish surface coverage for the optional cable file package."""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.publish.models import PublishApprovalRequest
from civiccast.publish.service import approve_publish, build_initial_surfaces
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow


def _asset(file_path: str | None) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id="council-2026-05-08",
        title="Council - May 8, 2026",
        state="validated",
        manifest_url="https://cdn.example/council-2026-05-08/playlist.m3u8",
        published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
        file_path=file_path,
        retention_policy="meeting",
        version=1,
    )


def test_initial_publish_surfaces_include_optional_cable_file_package() -> None:
    surfaces = {surface.id: surface for surface in build_initial_surfaces(_asset(None))}

    assert surfaces["cable-file-package"].label == "Cable file package"
    assert surfaces["cable-file-package"].kind == "record"
    assert surfaces["cable-file-package"].required is False
    assert "headend" in surfaces["cable-file-package"].next_step


def test_cable_file_package_surface_succeeds_when_media_and_caption_exist(
    tmp_path, monkeypatch
) -> None:
    media = tmp_path / "meeting.mp4"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "packages"
    captions_dir.mkdir()
    media.write_bytes(b"mp4 bytes")
    (captions_dir / "council-2026-05-08.vtt").write_text("WEBVTT\n", encoding="utf-8")
    monkeypatch.setenv("CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("CIVICCAST_CABLE_CAPTIONS_DIR", str(captions_dir))

    record = approve_publish(
        asset=_asset(str(media)),
        request=PublishApprovalRequest(
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_surface_ids=["cable-file-package"],
        ),
        store=InMemoryPublishStore(),
    )

    surface = next(surface for surface in record.surfaces if surface.id == "cable-file-package")
    assert surface.state == "succeeded"
    assert surface.health == "ok"
    assert surface.path is not None and surface.path.endswith(".zip")
    assert surface.verification_hash is not None
    assert surface.verification_hash.startswith("sha256:")


def test_cable_file_package_surface_reads_not_configured_not_failed_when_never_set_up() -> None:
    """Field evidence (candidate #17): an operator saw a red "failed: Cable
    file package was not created" on an otherwise-successful publish, for a
    PEG/headend handoff surface most stations never turn on. This surface
    was never attempted for real -- it must read "not set up (optional)",
    not "failed", and must never look red on the publish dashboard (see
    apps/portal-operator/src/screens/PublishDashboardScreen.tsx's
    SurfaceDot, which only turns red for "failed"/"blocked")."""

    record = approve_publish(
        asset=_asset(None),
        request=PublishApprovalRequest(
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_surface_ids=["cable-file-package"],
        ),
        store=InMemoryPublishStore(),
    )

    surface = next(surface for surface in record.surfaces if surface.id == "cable-file-package")
    assert surface.state == "not_configured"
    assert surface.state != "failed"
    assert surface.required is False
    assert surface.message is not None and "optional" in surface.message.lower()
    assert "CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR" in surface.next_step


def test_cable_file_package_surface_still_fails_for_a_real_configured_problem(
    tmp_path, monkeypatch
) -> None:
    """A station that DID configure cable packaging, but is missing the
    source media file, is a genuine failure -- distinct from "never set
    up" -- and must keep reading as "failed"."""

    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "packages"
    captions_dir.mkdir()
    monkeypatch.setenv("CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("CIVICCAST_CABLE_CAPTIONS_DIR", str(captions_dir))

    record = approve_publish(
        asset=_asset(None),
        request=PublishApprovalRequest(
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_surface_ids=["cable-file-package"],
        ),
        store=InMemoryPublishStore(),
    )

    surface = next(surface for surface in record.surfaces if surface.id == "cable-file-package")
    assert surface.state == "failed"
    assert surface.message == "Cable file package was not created."
    assert "local source media path" in surface.next_step
