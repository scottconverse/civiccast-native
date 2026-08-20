# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.cg.models import (
    CgBulletinSubmission,
    CgFeedAdapter,
    CgFeedCatalog,
    CgTemplate,
    CgTemplateZone,
    CgZone,
    MultiZoneCgSnapshot,
)
from civiccast.cg.service import (
    build_bulletin_queue,
    build_emergency_overlay,
    build_feed_catalog,
    build_hls_manifest,
    build_hls_render_plan,
    build_idle_page,
    build_multi_zone_snapshot,
    build_overlay_contract,
    build_portal_display,
    build_template_library,
)


def test_idle_page_is_actionable_between_streams() -> None:
    page = build_idle_page(channel_id="gov-ch12")

    assert page.channel_id == "gov-ch12"
    assert "No meeting is live" in page.message
    assert page.action_label == "View published recordings"
    assert page.action_url == "/"


def test_emergency_overlay_is_assertive_and_cellular_ready() -> None:
    overlay = build_emergency_overlay(overlay_id="storm-warning", severity="emergency")

    assert overlay.overlay_id == "storm-warning"
    assert overlay.severity == "emergency"
    assert overlay.aria_live == "assertive"
    assert overlay.cellular_fallback_enabled is True
    assert "Follow local emergency guidance" in overlay.instructions


def test_multi_zone_snapshot_has_required_24_7_bulletin_zones() -> None:
    snapshot = build_multi_zone_snapshot(channel_id="public")

    assert snapshot.channel_id == "public"
    assert snapshot.template.template_id == "standard-community-board"
    assert snapshot.hls_render_path == "/api/public/cg/channels/public/stream.m3u8"
    assert snapshot.portal_render_path == "/api/public/cg/channels/public/snapshot"
    assert {zone.kind for zone in snapshot.zones} >= {
        "primary",
        "ticker",
        "schedule",
        "logo",
        "audio",
        "alert",
    }
    ticker = next(zone for zone in snapshot.zones if zone.kind == "ticker")
    assert ticker.source == "rss"
    assert ticker.refresh_seconds == 600
    schedule = next(zone for zone in snapshot.zones if zone.kind == "schedule")
    assert schedule.content["items"][0]["title"] == "City Council"


def test_template_library_exposes_visual_layout_choices() -> None:
    library = build_template_library(channel_id="public")

    assert library.active_template_id == "standard-community-board"
    assert {template.template_id for template in library.templates} == {
        "standard-community-board",
        "live-lower-banner",
        "schedule-forward-board",
    }
    assert all(template.regions for template in library.templates)

    alternate = build_multi_zone_snapshot(
        channel_id="public",
        template_id="schedule-forward-board",
    )
    assert alternate.template.template_id == "schedule-forward-board"


def test_multi_zone_snapshot_rejects_missing_required_zones() -> None:
    template = CgTemplate(
        template_id="bad-template",
        label="Bad template",
        regions=[CgTemplateZone(region="main", zone_kind="primary", order=0)],
    )

    with pytest.raises(ValidationError, match="missing required zones"):
        MultiZoneCgSnapshot(
            snapshot_id="bad-snapshot",
            generated_at=build_multi_zone_snapshot().generated_at,
            channel_id="public",
            template=template,
            zones=[
                CgZone(
                    zone_id="primary-only",
                    kind="primary",
                    source="operator",
                    content={"headline": "Only primary"},
                )
            ],
            hls_render_path="/api/public/cg/channels/public/stream.m3u8",
            portal_render_path="/api/public/cg/channels/public/snapshot",
            proof_boundary="test",
        )


def test_feed_catalog_covers_dynamic_cg_adapter_types() -> None:
    catalog = build_feed_catalog(channel_id="public")

    assert catalog.channel_id == "public"
    assert {adapter.kind for adapter in catalog.adapters} == {
        "rss",
        "ical",
        "weather",
        "social",
    }
    assert all(adapter.items for adapter in catalog.adapters)
    weather = next(adapter for adapter in catalog.adapters if adapter.kind == "weather")
    assert weather.trust_tier == "operator_curated"
    assert weather.target_zone_kinds == ["alert", "ticker"]


def test_feed_catalog_rejects_duplicate_adapters_and_unsafe_weather() -> None:
    adapter = CgFeedAdapter(
        adapter_id="weather",
        kind="weather",
        label="Weather",
        source_url="https://example.invalid/weather.json",
        trust_tier="operator_curated",
        refresh_seconds=300,
        target_zone_kinds=["alert"],
    )

    with pytest.raises(ValidationError, match="adapter_id"):
        CgFeedCatalog(
            generated_at=build_feed_catalog().generated_at,
            channel_id="public",
            adapters=[adapter, adapter],
            proof_boundary="test",
        )

    with pytest.raises(ValidationError, match="weather feeds"):
        CgFeedAdapter(
            adapter_id="unsafe-weather",
            kind="weather",
            label="Weather",
            source_url="https://example.invalid/weather.json",
            trust_tier="public_permitted",
            refresh_seconds=300,
            target_zone_kinds=["alert"],
        )


def test_bulletin_queue_exposes_only_approved_zone_items() -> None:
    queue = build_bulletin_queue(channel_id="public")

    assert queue.channel_id == "public"
    assert {submission.state for submission in queue.submissions} == {
        "scheduled",
        "needs_changes",
    }
    assert queue.approved_zone_items[0].content["submission_id"] == "arts-fair"
    assert queue.approved_zone_items[0].kind == "ticker"


def test_bulletin_submission_requires_moderation_and_approval_metadata() -> None:
    accepted = build_bulletin_queue().submissions[0]
    needs_changes = build_bulletin_queue().submissions[1]

    with pytest.raises(ValidationError, match="approved_by_operator"):
        CgBulletinSubmission.model_validate({**accepted.model_dump(), "approved_by_operator": None})

    with pytest.raises(ValidationError, match="moderation_notes"):
        CgBulletinSubmission.model_validate(
            {**needs_changes.model_dump(), "moderation_notes": None}
        )


def test_hls_render_plan_and_manifest_are_channel_specific() -> None:
    plan = build_hls_render_plan(channel_id="public")
    manifest = build_hls_manifest(channel_id="public")

    assert plan.snapshot_url == "/api/public/cg/channels/public/snapshot"
    assert plan.manifest_url == "/api/public/cg/channels/public/stream.m3u8"
    assert plan.linear_overlay_contract_url == "/api/public/cg/channels/public/overlay-contract"
    assert "#EXTM3U" in manifest
    assert "/api/public/cg/channels/public/segments/cg-00000.ts" in manifest

    overlay_contract = build_overlay_contract(channel_id="public")
    assert overlay_contract.snapshot_url == "/api/public/cg/channels/public/snapshot"
    assert overlay_contract.zone_count == 6
    assert overlay_contract.safe_area_percent == 5


def test_portal_display_packages_board_inputs_for_between_streams_display() -> None:
    display = build_portal_display(channel_id="public")

    assert display.snapshot.channel_id == "public"
    assert display.template_library.active_template_id == display.snapshot.template.template_id
    assert display.feed_catalog.adapters
    assert display.approved_bulletins.approved_zone_items
    assert display.render_plan.manifest_url.endswith("/stream.m3u8")
    assert display.overlay_contract.zone_count == len(display.snapshot.zones)

    alternate_display = build_portal_display(
        channel_id="public",
        template_id="live-lower-banner",
    )
    assert alternate_display.snapshot.template.template_id == "live-lower-banner"
