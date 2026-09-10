# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Software channel operations contracts for v1.6."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from civiccast.egress.models import EgressCaptionProofSample, EgressProofEvent, EgressStateRow
from civiccast.schedule.models import ScheduleItemResponse

ChannelKind = Literal["public", "education", "government", "community"]
OutputKind = Literal["hls", "rtmp", "srt", "ndi-plan"]
PlayoutKind = Literal["live", "file", "slate", "bulletin", "rerun", "fallback"]
PlayoutStatus = Literal["scheduled", "playing", "completed", "failed", "fallback"]


class ChannelOutput(BaseModel):
    """One software output target for a linear channel."""

    model_config = ConfigDict(extra="forbid")

    kind: OutputKind
    label: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=500)
    proof_boundary: str = Field(min_length=1, max_length=120)
    next_step: str = Field(min_length=1)


class ChannelBranding(BaseModel):
    """Resident and CTV-visible channel identity."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    short_name: str = Field(min_length=1, max_length=40)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_text: str = Field(min_length=1, max_length=40)


class ChannelProfile(BaseModel):
    """Industry-standard software channel profile."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=80)
    kind: ChannelKind
    branding: ChannelBranding
    programming_rules: list[str] = Field(default_factory=list)
    fallback_behavior: str = Field(min_length=1)
    default_slate_asset_id: str | None = Field(default=None, max_length=120)
    outputs: list[ChannelOutput] = Field(default_factory=list)


class PlayoutBlock(BaseModel):
    """One scheduled or actual linear-channel playout block."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1, max_length=120)
    channel_id: str = Field(min_length=1, max_length=80)
    kind: PlayoutKind
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    duration_seconds: int = Field(gt=0)
    source_ref: str = Field(min_length=1, max_length=500)
    status: PlayoutStatus = "scheduled"
    caption_refs: list[str] = Field(default_factory=list)
    failover_from: str | None = Field(default=None, max_length=120)
    failover_reason: str | None = Field(default=None, max_length=500)


class ChannelNowNext(BaseModel):
    """Resident and operator now/next projection for one channel."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    channel: ChannelProfile
    # ``None`` when nothing is on air: the outgoing feed is stopped or has no
    # daemon state row yet. The console renders "No program on air" for it
    # rather than a fabricated block (beta.5 walkthrough F-27).
    current: PlayoutBlock | None
    next: PlayoutBlock | None
    fallback_active: bool
    proof_boundary: str
    # Set when a scheduled block covers "now" but the egress daemon reports a
    # different source on air (live takeover, manual start, bulletin fill).
    # The daemon is the authority on what is airing; this names the
    # disagreement instead of rendering the scheduled title as "Playing".
    schedule_note: str | None = Field(default=None, max_length=500)


class ChannelProofEvent(BaseModel):
    """Operator-readable and machine-readable playout proof event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=120)
    observed_at: datetime
    channel_id: str = Field(min_length=1, max_length=80)
    # ``None`` when the daemon put something on air that no schedule block
    # claimed (operator start, takeover, fallback slate).
    scheduled_block_id: str | None = Field(default=None, min_length=1, max_length=120)
    actual_kind: PlayoutKind
    actual_status: PlayoutStatus
    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(min_length=1, max_length=500)
    failover_from: str | None = Field(default=None, max_length=120)
    failover_reason: str | None = Field(default=None, max_length=500)
    # Joined from the daemon's CEA-608/708 caption decode-back proof samples:
    # ``True`` when the nearest sample within CAPTION_PROOF_JOIN_WINDOW_SECONDS
    # of the event is a PASS, ``False`` on a FAIL, ``None`` ("not verified")
    # when no sample covers the event. The console must not print "Attached"
    # for captions nobody proved (F-27).
    captions_attached: bool | None
    machine_summary: str = Field(min_length=1)


class ChannelProofLog(BaseModel):
    """Playout proof log for one channel."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    channel: ChannelProfile
    events: list[ChannelProofEvent]
    export_formats: list[str]
    not_claimed: list[str]


class ChannelPlayoutPlan(BaseModel):
    """Operator playout plan derived from the schedule lane."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    channel: ChannelProfile
    source: Literal["schedule-store", "sample-contract"]
    # Empty when nothing is scheduled. The operator plan never falls back to
    # sample-contract blocks; that source is reserved for test fixtures.
    blocks: list[PlayoutBlock]
    gap_blocks: list[PlayoutBlock]
    export_formats: list[str]
    proof_boundary: str
    not_claimed: list[str]


class CtvFeedItem(BaseModel):
    """Roku/reference CTV feed item."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    type: Literal["live", "vod"]
    title: str = Field(min_length=1, max_length=200)
    channel_id: str | None = Field(default=None, max_length=80)
    stream_url: str = Field(min_length=1, max_length=500)
    captions_url: str | None = Field(default=None, max_length=500)
    content_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)


class CtvFeed(BaseModel):
    """Stable public feed for reference connected-TV clients."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    station_name: str = Field(min_length=1, max_length=160)
    items: list[CtvFeedItem]
    browse_facets: list[str]
    proof_boundary: str


def default_channel_profiles() -> list[ChannelProfile]:
    """Return the default PEG-style software channel lineup."""

    return [
        _profile(
            channel_id="public",
            slug="public",
            kind="public",
            display_name="Public Channel",
            short_name="Public",
            color="#2458A6",
            logo_text="PUBLIC",
            default_slate_asset_id="slate-public",
            programming_rules=[
                "Live meetings take priority over file playback.",
                "Meeting reruns may fill gaps between live events.",
                "Fallback to station slate when no approved program is available.",
            ],
        ),
        _profile(
            channel_id="education",
            slug="education",
            kind="education",
            display_name="Education Channel",
            short_name="Education",
            color="#1B7F5F",
            logo_text="EDU",
            default_slate_asset_id="slate-education",
            programming_rules=[
                "School-board meetings and education programs are preferred.",
                "Bulletin boards may fill short gaps.",
                "Fallback to education slate when playback underruns.",
            ],
        ),
        _profile(
            channel_id="government",
            slug="government",
            kind="government",
            display_name="Government Channel",
            short_name="Gov",
            color="#7A4E9D",
            logo_text="GOV",
            default_slate_asset_id="slate-government",
            programming_rules=[
                "Council, board, and commission meetings take priority.",
                "Emergency bulletin blocks may interrupt scheduled playback.",
                "Fallback to government slate when a live source fails.",
            ],
        ),
    ]


def get_channel_profile(channel_id: str) -> ChannelProfile | None:
    """Return one default channel profile by id or slug."""

    normalized = channel_id.strip().lower()
    for profile in default_channel_profiles():
        if normalized in {profile.channel_id, profile.slug}:
            return profile
    return None


_ON_AIR_EGRESS_STATES: frozenset[str] = frozenset(
    {"ON_AIR", "TRANSITIONING", "FALLBACK_SLATE", "DRAINING"}
)

NOW_NEXT_PROOF_BOUNDARY = "egress-state-and-schedule-store"
PLAYOUT_PLAN_PROOF_BOUNDARY = "software-schedule-to-playout-plan"
SAMPLE_PROOF_BOUNDARY = "sample-contract"

# Free text from the egress daemon (``last_error`` is up to 1000 chars and
# carries ``str(exc)`` / a child-stderr tail) is cut to the contract field's
# ``max_length`` at this boundary. Without it the now/next endpoints raised a
# pydantic ValidationError -- a 500 -- exactly during a fallback incident.
OPERATOR_REASON_MAX_CHARS = 500
_ELLIPSIS = "\u2026"

# A caption decode-back proof sample counts for a proof event only when it was
# taken within this many seconds of the event; matches the daemon's own
# caption freshness window (``civiccast.egress.caption_proof``).
CAPTION_PROOF_JOIN_WINDOW_SECONDS = 120

_PROOF_LOG_NOT_CLAIMED = [
    "SDI or DeckLink output",
    "Comcast/headend delivery proof",
    "Roku Channel Store publication",
    (
        "caption verdicts more than "
        f"{CAPTION_PROOF_JOIN_WINDOW_SECONDS}s from the event (reported as not verified)"
    ),
]


def operator_reason(text: str | None, limit: int = OPERATOR_REASON_MAX_CHARS) -> str | None:
    """Cut daemon free text to ``limit`` characters with a trailing ellipsis."""

    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + _ELLIPSIS


_PLAYOUT_PLAN_NOT_CLAIMED = [
    "hardware playout device control",
    "SDI or DeckLink output",
    "Comcast/headend delivery proof",
]


def build_channel_now_next(
    channel_id: str,
    *,
    now: datetime | None = None,
    schedule_items: list[ScheduleItemResponse] | None = None,
    egress_state: EgressStateRow | None = None,
    include_operator_detail: bool = True,
) -> ChannelNowNext:
    """Build now/next from what the egress daemon and schedule store really report.

    ``current`` is only populated while the daemon reports the feed on air
    (``ON_AIR``/``TRANSITIONING``/``FALLBACK_SLATE``/``DRAINING``). A stopped
    feed, a missing state row, or a channel with no daemon at all yields
    ``current=None`` -- the console says "No program on air". ``next`` is the
    first scheduled premiere that has not finished yet, or ``None``.

    ``include_operator_detail=False`` is the unauthenticated public
    projection: the daemon's ``last_error`` (raw ``str(exc)`` / stderr with
    file paths and headend host:port) and its free-text source label never
    leave the station. The public block carries the channel's display name
    (or "Fallback slate") and no ``failover_reason``; ``schedule_note`` is
    also withheld because it repeats the daemon label.
    """

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    scheduled = _blocks_from_schedule(profile, schedule_items or [])
    upcoming = [
        block
        for block in scheduled
        if block.starts_at + timedelta(seconds=block.duration_seconds) > current_time
    ]
    current: PlayoutBlock | None = None
    schedule_note: str | None = None
    if egress_state is not None and egress_state.state in _ON_AIR_EGRESS_STATES:
        current, schedule_note = _block_from_egress_state(
            profile, egress_state, upcoming, current_time
        )
        if not include_operator_detail:
            current = _public_projection(profile, current)
            schedule_note = None
    next_block: PlayoutBlock | None = None
    for block in upcoming:
        if current is not None and block.block_id == current.block_id:
            continue
        next_block = block
        break
    return ChannelNowNext(
        generated_at=current_time,
        channel=profile,
        current=current,
        next=next_block,
        fallback_active=egress_state is not None and egress_state.state == "FALLBACK_SLATE",
        proof_boundary=NOW_NEXT_PROOF_BOUNDARY,
        schedule_note=schedule_note,
    )


def build_channel_proof_log(
    channel_id: str,
    *,
    now: datetime | None = None,
    proof_events: list[EgressProofEvent] | None = None,
    caption_proof_samples: list[EgressCaptionProofSample] | None = None,
) -> ChannelProofLog:
    """Build the operator proof log from persisted egress daemon proof events.

    No daemon events means an empty log -- the console says "No proof events
    yet". Nothing here is synthesised from the plan. ``captions_attached`` is
    joined from ``caption_proof_samples`` (the daemon's decode-back verdicts):
    the nearest sample within :data:`CAPTION_PROOF_JOIN_WINDOW_SECONDS` of the
    event decides PASS -> ``True`` / FAIL -> ``False``; no sample in the window
    leaves ``None`` ("Not verified").
    """

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    samples = [
        sample
        for sample in (caption_proof_samples or [])
        if sample.channel_id == profile.channel_id
    ]
    events = [
        _proof_event_from_egress(profile, event, samples)
        for event in sorted(proof_events or [], key=lambda row: row.observed_at, reverse=True)
        if event.channel_id == profile.channel_id
    ]
    return ChannelProofLog(
        generated_at=current_time,
        channel=profile,
        events=events,
        export_formats=["json", "csv-ready"],
        not_claimed=_PROOF_LOG_NOT_CLAIMED,
    )


def build_channel_playout_plan(
    channel_id: str,
    *,
    schedule_items: list[ScheduleItemResponse] | None = None,
    now: datetime | None = None,
) -> ChannelPlayoutPlan:
    """Build a software playout plan from scheduled rows only.

    An empty schedule yields an empty plan (``blocks == []``); the operator
    view never receives sample-contract blocks.
    """

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    blocks = _blocks_from_schedule(profile, schedule_items or [])
    return ChannelPlayoutPlan(
        generated_at=current_time,
        channel=profile,
        source="schedule-store",
        blocks=blocks,
        gap_blocks=_gap_blocks(profile, blocks),
        export_formats=["json", "csv-ready"],
        proof_boundary=PLAYOUT_PLAN_PROOF_BOUNDARY,
        not_claimed=_PLAYOUT_PLAN_NOT_CLAIMED,
    )


def build_sample_channel_now_next(
    channel_id: str, *, now: datetime | None = None
) -> ChannelNowNext:
    """Deterministic sample now/next for fixtures and the seeded app-platform feed.

    Never wire this into the operator console: it invents a playing block.
    """

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    blocks = _sample_playout_blocks(profile, current_time)
    current = blocks[0]
    return ChannelNowNext(
        generated_at=current_time,
        channel=profile,
        current=current,
        next=blocks[1] if len(blocks) > 1 else None,
        fallback_active=current.status == "fallback",
        proof_boundary=SAMPLE_PROOF_BOUNDARY,
    )


def build_sample_channel_proof_log(
    channel_id: str, *, now: datetime | None = None
) -> ChannelProofLog:
    """Deterministic sample proof log for fixtures. Not for the operator console."""

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    blocks = _sample_playout_blocks(profile, current_time)
    events = [
        ChannelProofEvent(
            event_id=f"proof-{block.block_id}",
            observed_at=max(block.starts_at, current_time),
            channel_id=profile.channel_id,
            scheduled_block_id=block.block_id,
            actual_kind=block.kind,
            actual_status=block.status,
            title=block.title,
            source_ref=block.source_ref,
            failover_from=block.failover_from,
            failover_reason=block.failover_reason,
            captions_attached=bool(block.caption_refs),
            machine_summary=(
                f"{profile.channel_id}:{block.block_id}:{block.kind}:{block.status}:"
                f"{'captions' if block.caption_refs else 'no-captions'}"
            ),
        )
        for block in blocks
    ]
    return ChannelProofLog(
        generated_at=current_time,
        channel=profile,
        events=events,
        export_formats=["json", "csv-ready"],
        not_claimed=_PROOF_LOG_NOT_CLAIMED,
    )


def build_sample_channel_playout_plan(
    channel_id: str, *, now: datetime | None = None
) -> ChannelPlayoutPlan:
    """Deterministic sample plan (``source="sample-contract"``) for fixtures only."""

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    blocks = _sample_playout_blocks(profile, current_time)
    return ChannelPlayoutPlan(
        generated_at=current_time,
        channel=profile,
        source="sample-contract",
        blocks=blocks,
        gap_blocks=_gap_blocks(profile, blocks),
        export_formats=["json", "csv-ready"],
        proof_boundary=SAMPLE_PROOF_BOUNDARY,
        not_claimed=_PLAYOUT_PLAN_NOT_CLAIMED,
    )


def _block_from_egress_state(
    profile: ChannelProfile,
    state: EgressStateRow,
    upcoming: list[PlayoutBlock],
    now: datetime,
) -> tuple[PlayoutBlock, str | None]:
    """Project the daemon's on-air state onto a playout block.

    The daemon is the authority on what is on air. Its ``current_source_label``
    is the title; a scheduled block covering ``now`` lends its timing and
    caption refs only when it is the same program (its asset id or title
    appears in the daemon's label). When the schedule says one thing and the
    daemon another (live takeover, manual start, bulletin fill), the block is
    built from the daemon row alone and the second return value names the
    disagreement. A daemon row without a label never adopts the scheduled
    title as "Playing" -- that was the F-27 fabrication in a new coat.
    """

    fallback = state.state == "FALLBACK_SLATE"
    label = state.current_source_label
    reason = operator_reason(state.last_error) if fallback else None
    covering = next((block for block in upcoming if block.starts_at <= now), None)
    if covering is not None and label is not None and _block_matches_label(covering, label):
        return (
            covering.model_copy(
                update={
                    "title": label,
                    "status": "fallback" if fallback else "playing",
                    "kind": "fallback" if fallback else covering.kind,
                    "failover_from": covering.source_ref if fallback else None,
                    "failover_reason": reason,
                }
            ),
            None,
        )
    started = state.updated_at.astimezone(UTC)
    elapsed = max(1, int((now - started).total_seconds()))
    title = label or f"{profile.branding.short_name} outgoing feed"
    block = PlayoutBlock(
        block_id=f"{profile.channel_id}-egress-{state.state.lower()}",
        channel_id=profile.channel_id,
        kind="fallback" if fallback else "live",
        title=title,
        starts_at=started,
        duration_seconds=elapsed,
        source_ref=label or f"egress-{profile.channel_id}",
        status="fallback" if fallback else "playing",
        failover_reason=reason,
    )
    note: str | None = None
    if covering is not None:
        airing = f"'{label}'" if label else "an unlabelled source"
        note = operator_reason(
            f"Schedule lists '{covering.title}' from "
            f"{covering.starts_at.strftime('%H:%M')} UTC, but the outgoing feed "
            f"reports {airing} on air. The schedule is not what is airing."
        )
    return block, note


def _block_matches_label(block: PlayoutBlock, label: str) -> bool:
    """True when the daemon's source label names the scheduled block's program."""

    folded = label.strip().casefold()
    if not folded:
        return False
    if folded == block.title.strip().casefold():
        return True
    asset_id = block.source_ref.removeprefix("asset-").strip().casefold()
    return bool(asset_id) and asset_id in folded


def _public_projection(profile: ChannelProfile, block: PlayoutBlock) -> PlayoutBlock:
    """Resident-safe copy of an on-air block: no daemon free text."""

    fallback = block.status == "fallback"
    title = "Fallback slate" if fallback else profile.branding.display_name
    return block.model_copy(
        update={
            "title": title,
            "source_ref": f"egress-{profile.channel_id}",
            "failover_from": None,
            "failover_reason": None,
        }
    )


def _captions_verdict(
    event: EgressProofEvent, samples: list[EgressCaptionProofSample]
) -> bool | None:
    window = timedelta(seconds=CAPTION_PROOF_JOIN_WINDOW_SECONDS)
    observed = event.observed_at.astimezone(UTC)
    nearest: EgressCaptionProofSample | None = None
    nearest_delta: timedelta | None = None
    for sample in samples:
        delta = abs(sample.sampled_at.astimezone(UTC) - observed)
        if delta > window:
            continue
        if nearest_delta is None or delta < nearest_delta:
            nearest, nearest_delta = sample, delta
    if nearest is None:
        return None
    return nearest.status == "PASS"


def _proof_event_from_egress(
    profile: ChannelProfile,
    event: EgressProofEvent,
    caption_samples: list[EgressCaptionProofSample] | None = None,
) -> ChannelProofEvent:
    fallback = event.state == "FALLBACK_SLATE"
    on_air = event.state in _ON_AIR_EGRESS_STATES
    status: PlayoutStatus = "fallback" if fallback else ("playing" if on_air else "completed")
    if event.state == "ERROR":
        status = "failed"
    return ChannelProofEvent(
        event_id=event.event_id,
        observed_at=event.observed_at,
        channel_id=profile.channel_id,
        scheduled_block_id=None,
        actual_kind="fallback" if fallback else "live",
        actual_status=status,
        title=event.source_label,
        source_ref=event.source_ref or event.source_label,
        captions_attached=_captions_verdict(event, caption_samples or []),
        machine_summary=event.machine_summary,
    )


def build_ctv_feed(*, station_name: str = "CivicCast Test Station") -> CtvFeed:
    """Build the stable public feed for Roku/reference CTV clients."""

    generated_at = datetime.now(UTC)
    items = [
        CtvFeedItem(
            id=f"live-{profile.channel_id}",
            type="live",
            title=profile.branding.display_name,
            channel_id=profile.channel_id,
            stream_url=f"/api/public/channels/{profile.channel_id}/live.m3u8",
            captions_url=f"/api/public/channels/{profile.channel_id}/captions.vtt",
            content_id=f"civiccast-live-{profile.channel_id}",
            description=f"Live and scheduled programming for {profile.branding.display_name}.",
        )
        for profile in default_channel_profiles()
    ]
    items.append(
        CtvFeedItem(
            id="vod-recent-meetings",
            type="vod",
            title="Recent meetings",
            stream_url="/api/public/assets",
            content_id="civiccast-vod-recent-meetings",
            description="Reference VOD collection for meetings published through CivicCast.",
        )
    )
    return CtvFeed(
        generated_at=generated_at,
        station_name=station_name,
        items=items,
        browse_facets=["channel", "meeting-body", "series", "date", "topic"],
        proof_boundary="reference-feed-api-not-channel-store-publication",
    )


def _profile(
    *,
    channel_id: str,
    slug: str,
    kind: ChannelKind,
    display_name: str,
    short_name: str,
    color: str,
    logo_text: str,
    default_slate_asset_id: str,
    programming_rules: list[str],
) -> ChannelProfile:
    return ChannelProfile(
        channel_id=channel_id,
        slug=slug,
        kind=kind,
        branding=ChannelBranding(
            display_name=display_name,
            short_name=short_name,
            color=color,
            logo_text=logo_text,
        ),
        programming_rules=programming_rules,
        fallback_behavior=(
            "Use the channel slate immediately when a live source, file playback, "
            "or bulletin block is unavailable."
        ),
        default_slate_asset_id=default_slate_asset_id,
        outputs=[
            ChannelOutput(
                kind="hls",
                label="Resident and CTV HLS",
                target=f"/api/public/channels/{channel_id}/live.m3u8",
                proof_boundary="software-output-url",
                next_step="Connect this URL to the channel playout worker before partner proof.",
            ),
            ChannelOutput(
                kind="ndi-plan",
                label="NDI command plan",
                target=f"CivicCast {display_name}",
                proof_boundary="command-plan-only",
                next_step="Run receiver-side NDI proof before claiming NDI delivery.",
            ),
        ],
    )


def _require_profile(channel_id: str) -> ChannelProfile:
    profile = get_channel_profile(channel_id)
    if profile is None:
        raise ValueError(f"Unknown channel profile: {channel_id}")
    return profile


def _sample_playout_blocks(profile: ChannelProfile, now: datetime) -> list[PlayoutBlock]:
    started = now.replace(second=0, microsecond=0)
    failed_source = f"live-source-{profile.channel_id}"
    current_kind: PlayoutKind = "live" if profile.kind != "education" else "file"
    current_status: PlayoutStatus = "playing"
    failover_from = None
    failover_reason = None
    source_ref = failed_source
    if profile.kind == "government":
        current_kind = "fallback"
        current_status = "fallback"
        failover_from = failed_source
        failover_reason = "live source missing heartbeat"
        source_ref = profile.default_slate_asset_id or f"slate-{profile.channel_id}"
    return [
        PlayoutBlock(
            block_id=f"{profile.channel_id}-now",
            channel_id=profile.channel_id,
            kind=current_kind,
            title=f"{profile.branding.short_name} live programming",
            starts_at=started,
            duration_seconds=1800,
            source_ref=source_ref,
            status=current_status,
            caption_refs=[f"{profile.channel_id}-live.vtt"] if current_kind != "fallback" else [],
            failover_from=failover_from,
            failover_reason=failover_reason,
        ),
        PlayoutBlock(
            block_id=f"{profile.channel_id}-next",
            channel_id=profile.channel_id,
            kind="rerun",
            title=f"{profile.branding.short_name} meeting replay",
            starts_at=started + timedelta(minutes=30),
            duration_seconds=3600,
            source_ref=f"asset-{profile.channel_id}-recent-meeting",
            status="scheduled",
            caption_refs=[f"{profile.channel_id}-replay.vtt"],
        ),
    ]


def _blocks_from_schedule(
    profile: ChannelProfile,
    schedule_items: list[ScheduleItemResponse],
) -> list[PlayoutBlock]:
    blocks: list[PlayoutBlock] = []
    for item in sorted(schedule_items, key=lambda row: row.scheduled_at):
        if item.mode != "premiere" or item.state != "scheduled":
            continue
        title = item.asset_title or item.asset_id
        blocks.append(
            PlayoutBlock(
                block_id=f"schedule-{item.id}",
                channel_id=profile.channel_id,
                kind="file",
                title=title,
                starts_at=item.scheduled_at.astimezone(UTC),
                duration_seconds=item.duration_seconds or 1,
                source_ref=f"asset-{item.asset_id}",
                status="scheduled",
                caption_refs=[f"{item.asset_id}.vtt"],
            )
        )
    # An empty schedule is an empty plan. The old "channel slate" placeholder
    # block made a bare channel look programmed (beta.5 walkthrough F-27).
    return blocks


def _gap_blocks(profile: ChannelProfile, blocks: list[PlayoutBlock]) -> list[PlayoutBlock]:
    gaps: list[PlayoutBlock] = []
    ordered = sorted(blocks, key=lambda block: block.starts_at)
    for index, left in enumerate(ordered[:-1]):
        right = ordered[index + 1]
        left_end = left.starts_at + timedelta(seconds=left.duration_seconds)
        gap_seconds = int((right.starts_at - left_end).total_seconds())
        if gap_seconds <= 0:
            continue
        gaps.append(
            PlayoutBlock(
                block_id=f"gap-{left.block_id}-to-{right.block_id}",
                channel_id=profile.channel_id,
                kind="slate",
                title=f"{profile.branding.short_name} slate gap",
                starts_at=left_end,
                duration_seconds=gap_seconds,
                source_ref=profile.default_slate_asset_id or f"slate-{profile.channel_id}",
                status="scheduled",
            )
        )
    return gaps
