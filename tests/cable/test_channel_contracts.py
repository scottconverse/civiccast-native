# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""v1.6 channel and CTV contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.cable.channel import (
    build_channel_now_next,
    build_channel_playout_plan,
    build_channel_proof_log,
    build_ctv_feed,
    default_channel_profiles,
)
from civiccast.cable.router import public_channel_captions_vtt
from civiccast.captions.live_sidecar import active_caption_sidecar
from civiccast.egress.automation import default_egress_work_dir
from civiccast.schedule.models import ScheduleItemResponse


def test_default_channel_profiles_cover_peg_lineup() -> None:
    profiles = default_channel_profiles()

    assert [profile.channel_id for profile in profiles] == ["public", "education", "government"]
    assert all(profile.outputs for profile in profiles)
    assert all(profile.default_slate_asset_id for profile in profiles)
    assert all("Fallback" not in profile.branding.display_name for profile in profiles)


def test_channel_now_next_reports_fallback_when_live_source_fails() -> None:
    now_next = build_channel_now_next(
        "government",
        now=datetime(2026, 5, 31, 18, 0, tzinfo=UTC),
    )

    assert now_next.channel.channel_id == "government"
    assert now_next.current.status == "fallback"
    assert now_next.current.kind == "fallback"
    assert now_next.current.failover_from == "live-source-government"
    assert now_next.next is not None
    assert now_next.next.kind == "rerun"


def test_channel_proof_log_is_machine_readable_and_names_non_claims() -> None:
    proof = build_channel_proof_log(
        "public",
        now=datetime(2026, 5, 31, 18, 0, tzinfo=UTC),
    )

    assert proof.channel.channel_id == "public"
    assert proof.export_formats == ["json", "csv-ready"]
    assert proof.events[0].machine_summary.startswith("public:public-now:live:playing")
    assert "SDI or DeckLink output" in proof.not_claimed
    assert "Roku Channel Store publication" in proof.not_claimed


def test_channel_playout_plan_derives_file_blocks_and_slate_gaps_from_schedule() -> None:
    start = datetime(2026, 5, 31, 18, 0, tzinfo=UTC)
    plan = build_channel_playout_plan(
        "public",
        schedule_items=[
            ScheduleItemResponse(
                id=uuid4(),
                asset_id="council-meeting",
                asset_title="Council Meeting",
                channel_id="public",
                mode="premiere",
                state="scheduled",
                scheduled_at=start,
                duration_seconds=1800,
                notes=None,
                created_at=start - timedelta(days=1),
            ),
            ScheduleItemResponse(
                id=uuid4(),
                asset_id="board-replay",
                asset_title="Board Replay",
                channel_id="public",
                mode="premiere",
                state="scheduled",
                scheduled_at=start + timedelta(hours=1),
                duration_seconds=1200,
                notes=None,
                created_at=start - timedelta(days=1),
            ),
        ],
        now=start,
    )

    assert plan.source == "schedule-store"
    assert [block.kind for block in plan.blocks] == ["file", "file"]
    assert plan.blocks[0].title == "Council Meeting"
    assert plan.gap_blocks[0].kind == "slate"
    assert plan.gap_blocks[0].duration_seconds == 1800
    assert "hardware playout device control" in plan.not_claimed


def test_ctv_feed_exposes_live_channels_and_vod_collection() -> None:
    feed = build_ctv_feed(station_name="Longmont Public Media Lab")

    assert feed.station_name == "Longmont Public Media Lab"
    assert {item.type for item in feed.items} == {"live", "vod"}
    assert "topic" in feed.browse_facets
    public_live = next(item for item in feed.items if item.id == "live-public")
    assert public_live.content_id == "civiccast-live-public"
    assert public_live.stream_url.endswith("/api/public/channels/public/live.m3u8")


def test_channel_api_routes_are_in_openapi_and_return_public_contracts(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "operator-token-a:operator-a:Operator A:operator")
    app = create_app()
    client = TestClient(app, headers={"Authorization": "Bearer operator-token-a"})

    channels = client.get("/api/public/channels")
    assert channels.status_code == 200
    assert channels.json()[0]["channel_id"] == "public"

    now_next = client.get("/api/public/channels/government/now-next")
    assert now_next.status_code == 200
    assert now_next.json()["fallback_active"] is True

    proof = client.get("/api/staff/cable/channels/public/proof-log")
    assert proof.status_code == 200
    assert proof.json()["events"]

    plan = client.get("/api/staff/cable/channels/public/playout-plan")
    assert plan.status_code == 200
    assert plan.json()["proof_boundary"] == "software-schedule-to-playout-plan"

    feed = client.get("/api/public/channels/ctv/feed?station_name=CTV%20Lab")
    assert feed.status_code == 200
    assert feed.json()["station_name"] == "CTV Lab"

    missing = client.get("/api/public/channels/missing/now-next")
    assert missing.status_code == 404


def test_public_caption_feed_serves_atomic_webvtt_without_caching(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    expected = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nCouncil is in session.\n"
    sidecar = active_caption_sidecar(tmp_path, "government")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(expected, encoding="utf-8", newline="\n")

    app = create_app()
    app.dependency_overrides[default_egress_work_dir] = lambda: tmp_path
    response = TestClient(app).get("/api/public/channels/government/captions.vtt")

    assert response.status_code == 200
    assert response.content == expected.encode("utf-8")
    assert response.headers["content-type"] == "text/vtt; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    operation = app.openapi()["paths"]["/api/public/channels/{channel_id}/captions.vtt"]["get"]
    assert set(operation["responses"]["200"]["content"]) == {"text/vtt"}


def test_public_caption_feed_returns_404_for_missing_or_unknown_channel(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    unknown = active_caption_sidecar(tmp_path, "unknown")
    unknown.parent.mkdir(parents=True)
    unknown.write_text("WEBVTT\n", encoding="utf-8")

    app = create_app()
    app.dependency_overrides[default_egress_work_dir] = lambda: tmp_path
    client = TestClient(app)

    assert client.get("/api/public/channels/government/captions.vtt").status_code == 404
    assert client.get("/api/public/channels/unknown/captions.vtt").status_code == 404


def test_public_caption_feed_rejects_channel_path_escape(monkeypatch, tmp_path: Path) -> None:
    outside = tmp_path.parent / "captions" / "active.vtt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("WEBVTT\n\nsecret\n", encoding="utf-8")
    monkeypatch.setattr(
        "civiccast.cable.router.active_caption_sidecar",
        lambda _root, _channel_id: outside,
    )

    with pytest.raises(HTTPException) as exc_info:
        public_channel_captions_vtt("government", work_dir=tmp_path)

    assert exc_info.value.status_code == 404
