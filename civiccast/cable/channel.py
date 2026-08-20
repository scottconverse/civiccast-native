# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Software channel operations contracts for v1.6."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    current: PlayoutBlock
    next: PlayoutBlock | None
    fallback_active: bool
    proof_boundary: str


class ChannelProofEvent(BaseModel):
    """Operator-readable and machine-readable playout proof event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=120)
    observed_at: datetime
    channel_id: str = Field(min_length=1, max_length=80)
    scheduled_block_id: str = Field(min_length=1, max_length=120)
    actual_kind: PlayoutKind
    actual_status: PlayoutStatus
    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(min_length=1, max_length=500)
    failover_from: str | None = Field(default=None, max_length=120)
    failover_reason: str | None = Field(default=None, max_length=500)
    captions_attached: bool
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


def build_channel_now_next(channel_id: str, *, now: datetime | None = None) -> ChannelNowNext:
    """Build deterministic now/next state for a channel profile."""

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    blocks = _sample_playout_blocks(profile, current_time)
    current = blocks[0]
    next_block = blocks[1] if len(blocks) > 1 else None
    return ChannelNowNext(
        generated_at=current_time,
        channel=profile,
        current=current,
        next=next_block,
        fallback_active=current.status == "fallback",
        proof_boundary="software-schedule-and-playout-contract",
    )


def build_channel_proof_log(channel_id: str, *, now: datetime | None = None) -> ChannelProofLog:
    """Build an operator-readable proof log from the current software plan."""

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
        not_claimed=[
            "SDI or DeckLink output",
            "Comcast/headend delivery proof",
            "Roku Channel Store publication",
        ],
    )


def build_channel_playout_plan(
    channel_id: str,
    *,
    schedule_items: list[ScheduleItemResponse] | None = None,
    now: datetime | None = None,
) -> ChannelPlayoutPlan:
    """Build a software playout plan from scheduled rows or sample contract blocks."""

    profile = _require_profile(channel_id)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if schedule_items:
        blocks = _blocks_from_schedule(profile, schedule_items)
        source: Literal["schedule-store", "sample-contract"] = "schedule-store"
    else:
        blocks = _sample_playout_blocks(profile, current_time)
        source = "sample-contract"
    gap_blocks = _gap_blocks(profile, blocks)
    return ChannelPlayoutPlan(
        generated_at=current_time,
        channel=profile,
        source=source,
        blocks=blocks,
        gap_blocks=gap_blocks,
        export_formats=["json", "csv-ready"],
        proof_boundary="software-schedule-to-playout-plan",
        not_claimed=[
            "hardware playout device control",
            "SDI or DeckLink output",
            "Comcast/headend delivery proof",
        ],
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
    if blocks:
        return blocks
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    return [
        PlayoutBlock(
            block_id=f"{profile.channel_id}-empty-slate",
            channel_id=profile.channel_id,
            kind="slate",
            title=f"{profile.branding.short_name} channel slate",
            starts_at=now,
            duration_seconds=1800,
            source_ref=profile.default_slate_asset_id or f"slate-{profile.channel_id}",
            status="scheduled",
        )
    ]


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
