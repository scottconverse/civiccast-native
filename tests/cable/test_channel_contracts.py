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
    build_sample_channel_now_next,
    build_sample_channel_playout_plan,
    build_sample_channel_proof_log,
    default_channel_profiles,
)
from civiccast.cable.router import public_channel_captions_vtt
from civiccast.captions.live_sidecar import active_caption_sidecar
from civiccast.egress.automation import default_egress_work_dir
from civiccast.egress.models import EgressProofEvent, EgressStateRow
from civiccast.schedule.models import ScheduleItemResponse

_NOW = datetime(2026, 5, 31, 18, 0, tzinfo=UTC)


def _schedule_item(
    asset_id: str, title: str, scheduled_at: datetime, duration_seconds: int
) -> ScheduleItemResponse:
    return ScheduleItemResponse(
        id=uuid4(),
        asset_id=asset_id,
        asset_title=title,
        channel_id="public",
        mode="premiere",
        state="scheduled",
        scheduled_at=scheduled_at,
        duration_seconds=duration_seconds,
        notes=None,
        created_at=scheduled_at - timedelta(days=1),
    )


def test_default_channel_profiles_cover_peg_lineup() -> None:
    profiles = default_channel_profiles()

    assert [profile.channel_id for profile in profiles] == ["public", "education", "government"]
    assert all(profile.outputs for profile in profiles)
    assert all(profile.default_slate_asset_id for profile in profiles)
    assert all("Fallback" not in profile.branding.display_name for profile in profiles)


# beta.5 walkthrough F-27: the operator console must never receive the sample
# contract rows. The honest builders below report nothing until the egress
# daemon and the schedule store have something real to say.


def test_channel_now_next_is_empty_when_nothing_is_on_air_or_scheduled() -> None:
    now_next = build_channel_now_next("public", now=_NOW)

    assert now_next.current is None
    assert now_next.next is None
    assert now_next.fallback_active is False
    assert now_next.proof_boundary == "egress-state-and-schedule-store"


def test_channel_now_next_stopped_feed_has_no_current_but_keeps_next_premiere() -> None:
    stopped = EgressStateRow(channel_id="public", state="STOPPED", updated_at=_NOW)
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=stopped,
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW + timedelta(hours=1), 1800)
        ],
    )

    assert now_next.current is None
    assert now_next.next is not None
    assert now_next.next.title == "Council Meeting"
    assert now_next.next.status == "scheduled"


def test_channel_now_next_reports_the_daemon_source_while_on_air() -> None:
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Council chamber camera",
        updated_at=_NOW - timedelta(minutes=5),
    )
    now_next = build_channel_now_next("public", now=_NOW, egress_state=on_air)

    assert now_next.current is not None
    assert now_next.current.title == "Council chamber camera"
    assert now_next.current.status == "playing"
    assert now_next.current.kind == "live"
    assert now_next.current.duration_seconds == 300
    assert now_next.next is None
    assert now_next.fallback_active is False


def test_channel_now_next_on_air_uses_the_scheduled_block_covering_now() -> None:
    on_air = EgressStateRow(channel_id="public", state="ON_AIR", updated_at=_NOW)
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800),
            _schedule_item("board", "Board Replay", _NOW + timedelta(hours=1), 1200),
        ],
    )

    assert now_next.current is not None
    assert now_next.current.title == "Council Meeting"
    assert now_next.current.status == "playing"
    assert now_next.next is not None
    assert now_next.next.title == "Board Replay"


def test_channel_now_next_reports_fallback_slate_from_daemon_state() -> None:
    fallback = EgressStateRow(
        channel_id="government",
        state="FALLBACK_SLATE",
        last_error="live source missing heartbeat",
        updated_at=_NOW,
    )
    now_next = build_channel_now_next("government", now=_NOW, egress_state=fallback)

    assert now_next.fallback_active is True
    assert now_next.current is not None
    assert now_next.current.status == "fallback"
    assert now_next.current.failover_reason == "live source missing heartbeat"


def test_channel_proof_log_is_empty_without_daemon_events() -> None:
    proof = build_channel_proof_log("public", now=_NOW)

    assert proof.events == []
    assert "SDI or DeckLink output" in proof.not_claimed


def test_channel_proof_log_maps_daemon_events_and_never_claims_captions() -> None:
    event = EgressProofEvent(
        event_id="proof-1",
        observed_at=_NOW,
        channel_id="public",
        state="ON_AIR",
        source_label="Council chamber camera",
        source_path="C:/station/sources/chamber.sdp",
        proof_boundary="egress-daemon",
        machine_summary="public:ON_AIR:chamber",
    )
    other = event.model_copy(update={"event_id": "proof-2", "channel_id": "education"})
    proof = build_channel_proof_log("public", now=_NOW, proof_events=[event, other])

    assert [row.event_id for row in proof.events] == ["proof-1"]
    assert proof.events[0].actual_status == "playing"
    assert proof.events[0].scheduled_block_id is None
    assert proof.events[0].captions_attached is None
    assert proof.events[0].source_ref == "Council chamber camera"


def test_channel_playout_plan_is_empty_without_schedule_rows() -> None:
    plan = build_channel_playout_plan("public", now=_NOW)

    assert plan.source == "schedule-store"
    assert plan.blocks == []
    assert plan.gap_blocks == []
    assert plan.proof_boundary == "software-schedule-to-playout-plan"


def test_sample_channel_now_next_reports_fallback_when_live_source_fails() -> None:
    now_next = build_sample_channel_now_next(
        "government",
        now=datetime(2026, 5, 31, 18, 0, tzinfo=UTC),
    )

    assert now_next.channel.channel_id == "government"
    assert now_next.proof_boundary == "sample-contract"
    assert now_next.current is not None
    assert now_next.current.status == "fallback"
    assert now_next.current.kind == "fallback"
    assert now_next.current.failover_from == "live-source-government"
    assert now_next.next is not None
    assert now_next.next.kind == "rerun"


def test_sample_channel_proof_log_is_machine_readable_and_names_non_claims() -> None:
    proof = build_sample_channel_proof_log(
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


def test_sample_channel_playout_plan_is_labelled_as_a_sample() -> None:
    plan = build_sample_channel_playout_plan("public", now=_NOW)

    assert plan.source == "sample-contract"
    assert plan.proof_boundary == "sample-contract"
    assert plan.blocks


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

    # Ephemeral stores: no egress daemon state, no schedule rows. The API must
    # say so (F-27) instead of serving the sample contract.
    now_next = client.get("/api/public/channels/government/now-next")
    assert now_next.status_code == 200
    assert now_next.json()["current"] is None
    assert now_next.json()["next"] is None
    assert now_next.json()["fallback_active"] is False

    staff_now_next = client.get("/api/staff/cable/channels/government/now-next")
    assert staff_now_next.status_code == 200
    assert staff_now_next.json()["current"] is None

    proof = client.get("/api/staff/cable/channels/public/proof-log")
    assert proof.status_code == 200
    assert proof.json()["events"] == []

    plan = client.get("/api/staff/cable/channels/public/playout-plan")
    assert plan.status_code == 200
    assert plan.json()["source"] == "schedule-store"
    assert plan.json()["blocks"] == []
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
