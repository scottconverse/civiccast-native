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
    CAPTION_PROOF_JOIN_WINDOW_SECONDS,
    OPERATOR_REASON_MAX_CHARS,
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
from civiccast.egress.models import EgressCaptionProofSample, EgressProofEvent, EgressStateRow
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.models import ScheduleItemResponse
from civiccast.schedule.router import get_schedule_store

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


def test_channel_now_next_borrows_the_scheduled_block_only_when_the_daemon_airs_it() -> None:
    """The daemon's proof event names the scheduled asset: same program, so
    the block lends its id, timing and caption refs and the title is the daemon's."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Council Meeting",
        updated_at=_NOW - timedelta(minutes=10),
    )
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        current_source_ref="council",
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800),
            _schedule_item("board", "Board Replay", _NOW + timedelta(hours=1), 1200),
        ],
    )

    assert now_next.current is not None
    assert now_next.current.title == "Council Meeting"
    assert now_next.current.status == "playing"
    assert now_next.current.block_id.startswith("schedule-")
    assert now_next.current.caption_refs == ["council.vtt"]
    assert now_next.schedule_note is None
    assert now_next.next is not None
    assert now_next.next.title == "Board Replay"
    assert now_next.next.starts_at > _NOW


def test_channel_now_next_matches_the_scheduled_block_by_proof_event_source_ref_not_label() -> None:
    """Hostile review M5: identity is the daemon's proof-event ``source_ref``.
    The same conformed-file label with no proof event is NOT the scheduled
    block -- no borrowed slot, no borrowed caption refs, and the note fires."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="council (conformed)",
        updated_at=_NOW,
    )
    schedule = [_schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800)]

    proven = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=schedule,
        current_source_ref="council",
    )
    assert proven.current is not None
    assert proven.current.block_id.startswith("schedule-")
    assert proven.current.title == "council (conformed)"
    assert proven.current.caption_refs == ["council.vtt"]
    assert proven.schedule_note is None

    unproven = build_channel_now_next(
        "public", now=_NOW, egress_state=on_air, schedule_items=schedule
    )
    assert unproven.current is not None
    assert unproven.current.block_id == "public-egress-on_air"
    assert unproven.current.title == "council (conformed)"
    assert unproven.current.caption_refs == []
    assert unproven.schedule_note is not None
    assert "Council Meeting" in unproven.schedule_note

    other_asset = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=schedule,
        current_source_ref="bulletin",
    )
    assert other_asset.current is not None
    assert other_asset.current.block_id == "public-egress-on_air"
    assert other_asset.current.caption_refs == []
    assert other_asset.schedule_note is not None


def test_channel_now_next_never_matches_a_short_asset_id_inside_the_label() -> None:
    """Hostile review M5 (wrong match): asset id ``live`` must not own
    "Live takeover from Studio B" -- the takeover keeps its own timing, the
    meeting's caption refs are never grafted on, and the note fires."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Live takeover from Studio B",
        updated_at=_NOW - timedelta(minutes=2),
    )
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=[_schedule_item("live", "Live", _NOW - timedelta(minutes=10), 1800)],
    )

    assert now_next.current is not None
    assert now_next.current.block_id == "public-egress-on_air"
    assert now_next.current.starts_at == _NOW - timedelta(minutes=2)
    assert now_next.current.caption_refs == []
    assert now_next.schedule_note is not None
    assert "not what is airing" in now_next.schedule_note
    assert now_next.next is None


def test_channel_now_next_exact_title_match_without_proof_lends_the_slot_but_not_captions() -> None:
    """Hostile review M5 (wrong miss): the ordinary case where the daemon's
    label is the asset title and no proof event is available borrows the slot,
    but a caption claim never rests on a title heuristic."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Council Meeting",
        updated_at=_NOW - timedelta(minutes=10),
    )
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800)
        ],
    )

    assert now_next.current is not None
    assert now_next.current.block_id.startswith("schedule-")
    assert now_next.current.caption_refs == []
    assert now_next.schedule_note is None


def test_channel_now_next_reports_the_daemon_source_over_a_covering_schedule_block() -> None:
    """Hostile review M1: a live takeover / manual start / bulletin fill while a
    premiere covers the wall clock must render what the daemon has on air, not
    the scheduled title as "Playing", and must say the two disagree."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Emergency bulletin",
        updated_at=_NOW - timedelta(minutes=2),
    )
    now_next = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800)
        ],
    )

    assert now_next.current is not None
    assert now_next.current.title == "Emergency bulletin"
    assert now_next.current.status == "playing"
    assert now_next.current.kind == "live"
    assert now_next.current.block_id == "public-egress-on_air"
    assert now_next.current.duration_seconds == 120
    assert now_next.schedule_note is not None
    assert "Council Meeting" in now_next.schedule_note
    assert "Emergency bulletin" in now_next.schedule_note
    assert "not what is airing" in now_next.schedule_note
    # B4: the covering premiere started ten minutes ago and is not airing;
    # it is named in the note, never re-advertised as "Next".
    assert now_next.next is None


def test_channel_now_next_unlabelled_daemon_row_never_adopts_the_scheduled_title() -> None:
    """A daemon row with no source label says nothing about which program is
    airing; the scheduled title is not promoted to "Playing" on its behalf."""
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
    assert now_next.current.title == "Public outgoing feed"
    assert now_next.current.block_id == "public-egress-on_air"
    assert now_next.schedule_note is not None
    assert "Council Meeting" in now_next.schedule_note
    # B4: Next is the premiere that has not started, not the one already
    # ten minutes into its slot.
    assert now_next.next is not None
    assert now_next.next.title == "Board Replay"
    assert now_next.next.starts_at > _NOW


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


_LONG_LAST_ERROR = (
    "egress encoder unavailable; aired fallback slate: SourcePrepareError: "
    "C:\\station\\media\\council-2026-05-31.ts: ffmpeg exited 1 -- "
) + "stderr tail line with codec detail; " * 20
assert len(_LONG_LAST_ERROR) > OPERATOR_REASON_MAX_CHARS
assert len(_LONG_LAST_ERROR) <= 1000


def test_channel_now_next_truncates_a_long_daemon_error_at_the_contract_boundary() -> None:
    """Hostile review B1: ``EgressStateRow.last_error`` is up to 1000 chars,
    ``PlayoutBlock.failover_reason`` is 500; the builder used to raise a
    ValidationError (a 500 on both now/next routes) during an incident."""
    fallback = EgressStateRow(
        channel_id="government",
        state="FALLBACK_SLATE",
        last_error=_LONG_LAST_ERROR,
        updated_at=_NOW,
    )
    now_next = build_channel_now_next("government", now=_NOW, egress_state=fallback)

    assert now_next.current is not None
    reason = now_next.current.failover_reason
    assert reason is not None
    assert len(reason) == OPERATOR_REASON_MAX_CHARS
    assert reason.endswith("\u2026")
    assert reason.startswith("egress encoder unavailable; aired fallback slate")


def test_public_now_next_carries_no_daemon_error_or_source_label() -> None:
    """Hostile review B2: the public now/next is unauthenticated. The daemon's
    ``last_error`` (raw str(exc) with file paths / headend host:port) and its
    free-text source label stay on the staff projection."""
    fallback = EgressStateRow(
        channel_id="government",
        state="FALLBACK_SLATE",
        current_source_label="Council chamber camera (NAS-2)",
        last_error="SourcePrepareError: \\\\nas-2\\media\\council.ts -> srt://headend.lan:9000",
        updated_at=_NOW,
    )
    staff = build_channel_now_next("government", now=_NOW, egress_state=fallback)
    public = build_channel_now_next(
        "government", now=_NOW, egress_state=fallback, include_operator_detail=False
    )

    assert staff.current is not None
    assert staff.current.failover_reason is not None
    assert staff.current.failover_reason.startswith("SourcePrepareError")
    assert public.current is not None
    assert public.fallback_active is True
    assert public.current.status == "fallback"
    assert public.current.failover_reason is None
    assert public.current.title == "Fallback slate"
    body = public.model_dump_json()
    assert "nas-2" not in body
    assert "headend.lan" not in body
    assert "Council chamber camera" not in body


def test_public_now_next_names_the_scheduled_program_when_the_daemon_airs_it() -> None:
    """Hostile review M6: the scheduled title is already public via the
    schedule routes, so the resident surface says it instead of blanking the
    program to the channel name; the daemon's own label still never leaks."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Council Meeting (NAS-2 conform)",
        updated_at=_NOW - timedelta(minutes=10),
    )
    schedule = [
        _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800),
        _schedule_item("board", "Board Replay", _NOW + timedelta(hours=1), 1200),
    ]
    staff = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=schedule,
        current_source_ref="council",
    )
    public = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=schedule,
        current_source_ref="council",
        include_operator_detail=False,
    )

    assert staff.current is not None
    assert staff.current.title == "Council Meeting (NAS-2 conform)"
    assert public.current is not None
    assert public.current.title == "Council Meeting"
    assert public.current.source_ref == "egress-public"
    assert public.current.failover_reason is None
    assert public.next is not None
    assert public.next.title == "Board Replay"
    assert public.schedule_note is None
    assert "NAS-2" not in public.model_dump_json()


def test_public_now_next_falls_back_to_the_display_name_and_never_readvertises_the_airing_slot() -> (
    None
):
    """B4 on the resident surface: during a takeover the public body must not
    say "Coming up: Council Meeting" for a slot that started in the past."""
    on_air = EgressStateRow(
        channel_id="public",
        state="ON_AIR",
        current_source_label="Emergency bulletin",
        updated_at=_NOW - timedelta(minutes=2),
    )
    public = build_channel_now_next(
        "public",
        now=_NOW,
        egress_state=on_air,
        schedule_items=[
            _schedule_item("council", "Council Meeting", _NOW - timedelta(minutes=10), 1800)
        ],
        include_operator_detail=False,
    )

    assert public.current is not None
    assert public.current.title == public.channel.branding.display_name
    assert public.next is None
    assert public.schedule_note is None
    assert "Emergency bulletin" not in public.model_dump_json()


class _ScheduleStoreStub:
    """The only schedule-store call the now/next routes make is ``list``."""

    def __init__(self, items: list[ScheduleItemResponse]) -> None:
        self._items = items

    def list(self, *, channel_id=None, states=None):  # type: ignore[no-untyped-def]
        return [
            item
            for item in self._items
            if (channel_id is None or item.channel_id == channel_id)
            and (states is None or item.state in states)
        ]


def _client_with_egress_store(
    monkeypatch,
    store: InMemoryEgressStore,
    schedule_items: list[ScheduleItemResponse] | None = None,
) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "operator-token-a:operator-a:Operator A:operator")
    app = create_app()
    app.dependency_overrides[get_egress_store] = lambda: store
    if schedule_items is not None:
        app.dependency_overrides[get_schedule_store] = lambda: _ScheduleStoreStub(schedule_items)
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def _daemon_proof_event(
    channel_id: str, source_label: str, source_ref: str | None, observed_at: datetime
) -> EgressProofEvent:
    return EgressProofEvent(
        event_id=f"egress-proof-{source_label.lower().replace(' ', '-')}",
        observed_at=observed_at,
        channel_id=channel_id,
        state="ON_AIR",
        source_label=source_label,
        source_path="C:/CivicCast/media/source.ts",
        source_ref=source_ref,
        proof_boundary="civiccast-egress-handoff-boundary",
        machine_summary=f"{channel_id}: ON_AIR {source_label}",
    )


def test_now_next_routes_join_identity_from_the_daemon_proof_event(monkeypatch) -> None:
    """M5 + M6 + B4 through the real routes: the router joins the state row to
    the daemon's proof event for the asset id, the staff body borrows the
    scheduled slot and caption refs on that proof, the public body names the
    scheduled program, and Next is the premiere that has not started."""
    now = datetime.now(UTC)
    store = InMemoryEgressStore()
    store.append_proof_event(
        _daemon_proof_event("public", "Council Meeting", "council", now - timedelta(minutes=10))
    )
    store.write_state(
        EgressStateRow(
            channel_id="public",
            state="ON_AIR",
            current_source_label="Council Meeting",
            updated_at=now - timedelta(minutes=10),
        )
    )
    client = _client_with_egress_store(
        monkeypatch,
        store,
        schedule_items=[
            _schedule_item("council", "Council Meeting", now - timedelta(minutes=10), 1800),
            _schedule_item("board", "Board Replay", now + timedelta(hours=1), 1200),
        ],
    )

    staff = client.get("/api/staff/cable/channels/public/now-next")
    assert staff.status_code == 200, staff.text
    staff_body = staff.json()
    assert staff_body["current"]["block_id"].startswith("schedule-")
    assert staff_body["current"]["caption_refs"] == ["council.vtt"]
    assert staff_body["schedule_note"] is None
    assert staff_body["next"]["title"] == "Board Replay"

    public = client.get("/api/public/channels/public/now-next", headers={})
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["current"]["title"] == "Council Meeting"
    assert body["current"]["source_ref"] == "egress-public"
    assert body["next"]["title"] == "Board Replay"
    assert body["next"]["starts_at"] > body["generated_at"]


def test_now_next_routes_never_readvertise_the_covering_slot_during_a_takeover(
    monkeypatch,
) -> None:
    """B4 through the real routes: the daemon airs a bulletin over the
    scheduled meeting. Neither body lists the ten-minutes-old meeting as Next,
    and the public body names neither the bulletin nor the meeting."""
    now = datetime.now(UTC)
    store = InMemoryEgressStore()
    store.append_proof_event(
        _daemon_proof_event("public", "Emergency bulletin", None, now - timedelta(minutes=2))
    )
    store.write_state(
        EgressStateRow(
            channel_id="public",
            state="ON_AIR",
            current_source_label="Emergency bulletin",
            updated_at=now - timedelta(minutes=2),
        )
    )
    client = _client_with_egress_store(
        monkeypatch,
        store,
        schedule_items=[
            _schedule_item("council", "Council Meeting", now - timedelta(minutes=10), 1800)
        ],
    )

    staff = client.get("/api/staff/cable/channels/public/now-next")
    assert staff.status_code == 200, staff.text
    assert staff.json()["current"]["title"] == "Emergency bulletin"
    assert staff.json()["current"]["caption_refs"] == []
    assert staff.json()["next"] is None
    assert "not what is airing" in staff.json()["schedule_note"]

    public = client.get("/api/public/channels/public/now-next", headers={})
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["current"]["title"] == body["channel"]["branding"]["display_name"]
    assert body["next"] is None
    assert body["schedule_note"] is None
    assert "Emergency bulletin" not in public.text


def test_now_next_routes_survive_a_long_daemon_error_and_public_route_redacts_it(
    monkeypatch,
) -> None:
    """m5 + B1 + B2 through the real routes with a populated state row."""
    store = InMemoryEgressStore()
    store.write_state(
        EgressStateRow(
            channel_id="government",
            state="FALLBACK_SLATE",
            current_source_label="Council chamber camera (NAS-2)",
            last_error=_LONG_LAST_ERROR,
            updated_at=_NOW,
        )
    )
    client = _client_with_egress_store(monkeypatch, store)

    staff = client.get("/api/staff/cable/channels/government/now-next")
    assert staff.status_code == 200, staff.text
    staff_reason = staff.json()["current"]["failover_reason"]
    assert len(staff_reason) == OPERATOR_REASON_MAX_CHARS
    assert staff_reason.endswith("\u2026")
    assert staff.json()["current"]["title"] == "Council chamber camera (NAS-2)"

    public = client.get("/api/public/channels/government/now-next", headers={})
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["fallback_active"] is True
    assert body["current"]["status"] == "fallback"
    assert body["current"]["failover_reason"] is None
    assert body["current"]["title"] == "Fallback slate"
    assert body["schedule_note"] is None
    text = public.text
    assert "SourcePrepareError" not in text
    assert "council-2026-05-31.ts" not in text
    assert "Council chamber camera" not in text
    assert "NAS-2" not in text


def test_channel_proof_log_is_empty_without_daemon_events() -> None:
    proof = build_channel_proof_log("public", now=_NOW)

    assert proof.events == []
    assert "SDI or DeckLink output" in proof.not_claimed


def _proof_event(event_id: str = "proof-1", observed_at: datetime = _NOW) -> EgressProofEvent:
    return EgressProofEvent(
        event_id=event_id,
        observed_at=observed_at,
        channel_id="public",
        state="ON_AIR",
        source_label="Council chamber camera",
        source_path="C:/station/sources/chamber.sdp",
        proof_boundary="egress-daemon",
        machine_summary="public:ON_AIR:chamber",
    )


def _caption_sample(
    sampled_at: datetime, status: str = "PASS", channel_id: str = "public"
) -> EgressCaptionProofSample:
    return EgressCaptionProofSample(
        channel_id=channel_id,
        sampled_at=sampled_at,
        status=status,  # type: ignore[arg-type]
        caption_status="on" if status == "PASS" else "not-verified",
        mode="cea-708",
        decoder_name="ccextractor",
        expected_cue_count=4,
        decoded_cue_count=4 if status == "PASS" else 0,
        matched_cue_count=4 if status == "PASS" else 0,
        proof_boundary="egress-caption-decode-back",
    )


def test_channel_proof_log_maps_daemon_events_and_never_claims_captions() -> None:
    event = _proof_event()
    other = event.model_copy(update={"event_id": "proof-2", "channel_id": "education"})
    proof = build_channel_proof_log("public", now=_NOW, proof_events=[event, other])

    assert [row.event_id for row in proof.events] == ["proof-1"]
    assert proof.events[0].actual_status == "playing"
    assert proof.events[0].scheduled_block_id is None
    assert proof.events[0].captions_attached is None
    assert proof.events[0].source_ref == "Council chamber camera"
    assert any(f"{CAPTION_PROOF_JOIN_WINDOW_SECONDS}s" in claim for claim in proof.not_claimed)


def test_channel_proof_log_joins_the_nearest_caption_decode_back_verdict() -> None:
    """Hostile review M2: the daemon's caption proof samples carry a real
    PASS/FAIL; the nearest sample within the join window decides the column."""
    event = _proof_event()
    proof = build_channel_proof_log(
        "public",
        now=_NOW,
        proof_events=[event],
        caption_proof_samples=[
            _caption_sample(_NOW + timedelta(seconds=90), status="FAIL"),
            _caption_sample(_NOW + timedelta(seconds=30), status="PASS"),
        ],
    )
    assert proof.events[0].captions_attached is True

    failed = build_channel_proof_log(
        "public",
        now=_NOW,
        proof_events=[event],
        caption_proof_samples=[_caption_sample(_NOW + timedelta(seconds=45), status="FAIL")],
    )
    assert failed.events[0].captions_attached is False


def test_channel_proof_log_leaves_captions_unverified_outside_the_join_window() -> None:
    event = _proof_event()
    proof = build_channel_proof_log(
        "public",
        now=_NOW,
        proof_events=[event],
        caption_proof_samples=[
            _caption_sample(_NOW + timedelta(seconds=CAPTION_PROOF_JOIN_WINDOW_SECONDS + 1)),
            _caption_sample(_NOW - timedelta(minutes=10)),
            # Another channel's PASS inside the window must not count.
            _caption_sample(_NOW + timedelta(seconds=5), channel_id="education"),
        ],
    )
    assert proof.events[0].captions_attached is None


def test_staff_proof_log_route_joins_caption_samples_from_the_store(monkeypatch) -> None:
    store = InMemoryEgressStore()
    store.append_proof_event(_proof_event("proof-1", _NOW))
    store.append_proof_event(_proof_event("proof-2", _NOW + timedelta(hours=1)))
    store.append_caption_proof_sample(_caption_sample(_NOW + timedelta(seconds=20), "PASS"))
    store.append_caption_proof_sample(
        _caption_sample(_NOW + timedelta(hours=1, seconds=20), "FAIL")
    )
    client = _client_with_egress_store(monkeypatch, store)

    response = client.get("/api/staff/cable/channels/public/proof-log")

    assert response.status_code == 200, response.text
    by_id = {row["event_id"]: row["captions_attached"] for row in response.json()["events"]}
    assert by_id == {"proof-1": True, "proof-2": False}


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


# ---------------------------------------------------------------------------
# The advertised HLS URL must be true (beta.5 walkthrough: Channels printed
# /api/public/channels/public/live.m3u8 and it answered 404 while on air).
# ---------------------------------------------------------------------------


def test_static_profile_hls_output_is_marked_not_enabled() -> None:
    # With no egress store there is no hls sink; the output says so instead of
    # pretending the URL is wired.
    profile = next(p for p in default_channel_profiles() if p.channel_id == "public")
    hls = next(output for output in profile.outputs if output.kind == "hls")
    assert hls.enabled is False
    assert hls.target == "/api/public/channels/public/live.m3u8"
    assert hls.next_step.startswith("HLS web output is not enabled for this channel.")
    assert "Local rehearsal (web preview, HLS)" in hls.next_step


def _client_with_egress_store(monkeypatch, egress_store):  # type: ignore[no-untyped-def]
    from civiccast.egress.router import get_egress_store

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "operator-token-a:operator-a:Operator A:operator")
    app = create_app()
    app.dependency_overrides[get_egress_store] = lambda: egress_store
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def test_live_m3u8_redirects_to_media_router_when_hls_sink_configured(monkeypatch) -> None:
    from civiccast.egress.models import EgressConfig, EgressSinkSpec
    from civiccast.egress.store import InMemoryEgressStore

    store = InMemoryEgressStore()
    store.upsert_config(
        EgressConfig(
            channel_id="public",
            enabled=True,
            slate_message="x",
            sinks=[EgressSinkSpec(kind="hls", label="Web preview (HLS)", uri="/srv/live/public")],
        )
    )
    client = _client_with_egress_store(monkeypatch, store)

    r = client.get("/api/public/channels/public/live.m3u8", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/media/live/public/playlist.m3u8"

    # Both channel lists now print the REAL manifest and mark the output wired.
    for path in ("/api/public/channels", "/api/staff/cable/channels"):
        profiles = client.get(path).json()
        public = next(p for p in profiles if p["channel_id"] == "public")
        hls = next(o for o in public["outputs"] if o["kind"] == "hls")
        assert hls["enabled"] is True, path
        assert hls["target"] == "/media/live/public/playlist.m3u8", path
        assert hls["proof_boundary"] == "hls-sink-configured", path
        # Other channels have no sink: still honest.
        government = next(p for p in profiles if p["channel_id"] == "government")
        gov_hls = next(o for o in government["outputs"] if o["kind"] == "hls")
        assert gov_hls["enabled"] is False, path
        assert gov_hls["target"] == "/api/public/channels/government/live.m3u8", path


def test_live_m3u8_404_names_the_fix_when_hls_output_not_enabled(monkeypatch) -> None:
    from civiccast.egress.models import EgressConfig, EgressSinkSpec
    from civiccast.egress.store import InMemoryEgressStore

    store = InMemoryEgressStore()
    store.upsert_config(
        EgressConfig(
            channel_id="public",
            enabled=True,
            slate_message="x",
            sinks=[EgressSinkSpec(kind="udp-ts", label="Cable headend", uri="udp://10.0.0.9:5000")],
        )
    )
    client = _client_with_egress_store(monkeypatch, store)

    r = client.get("/api/public/channels/public/live.m3u8", follow_redirects=False)
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail.startswith("HLS web output is not enabled for this channel.")
    assert "Local rehearsal (web preview, HLS)" in detail
    assert "(channel: public)" in detail

    # Unknown channel is a plain 404 too, never a redirect into /media/live.
    r = client.get("/api/public/channels/nope/live.m3u8", follow_redirects=False)
    assert r.status_code == 404
    assert "Channel profile not found" in r.json()["detail"]


def test_live_m3u8_404_without_any_egress_store(monkeypatch) -> None:
    client = _client_with_egress_store(monkeypatch, None)
    r = client.get("/api/public/channels/public/live.m3u8", follow_redirects=False)
    assert r.status_code == 404
    assert "HLS web output is not enabled" in r.json()["detail"]


# Round-2 delta review, MINOR 2: ``local_live_manifest_path`` ignored
# ``CIVICCAST_LOCAL_MEDIA_BASE_URL`` and never quoted the channel id, so the
# Channels screen and ``/api/public/live/current`` disagreed whenever an
# operator base was configured. One helper owns the URL now.


def test_local_live_manifest_path_is_site_relative_and_quoted_by_default(monkeypatch) -> None:
    from civiccast.cable.channel import local_live_manifest_path

    monkeypatch.delenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", raising=False)
    assert local_live_manifest_path("public") == "/media/live/public/playlist.m3u8"
    assert local_live_manifest_path("gov ch/12") == "/media/live/gov%20ch%2F12/playlist.m3u8"


def test_local_live_manifest_path_honours_an_operator_base_like_the_live_api(monkeypatch) -> None:
    from civiccast.cable.channel import local_live_manifest_path

    for base in ("https://media.town.example", "https://media.town.example/"):
        monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", base)
        assert local_live_manifest_path("public") == (
            "https://media.town.example/media/live/public/playlist.m3u8"
        ), base
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", "   ")
    assert local_live_manifest_path("public") == "/media/live/public/playlist.m3u8"
