# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Source-plan providers for channel egress."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import EgressConfig, EgressSourcePlan, EgressSourceSegment
from civiccast.egress.runtime import FfmpegRunner
from civiccast.schedule.models import (
    ASSET_STATE_RECORDED,
    ASSET_STATE_VALIDATED,
    SCHEDULE_MODE_PREMIERE,
    SCHEDULE_STATE_PUBLISHED,
    ScheduleItemResponse,
    StaffAssetRow,
)
from civiccast.stream._ffmpeg import run_ffmpeg

AssetResolver = Callable[[str], StaffAssetRow | None]
ScheduleItemsProvider = Callable[[str], Sequence[ScheduleItemResponse]]
_PLAYABLE_ASSET_STATES = {ASSET_STATE_VALIDATED, ASSET_STATE_RECORDED}


class SlateSourceGenerator:
    """Generate a pre-conformed MPEG-TS slate source for an egress channel."""

    def __init__(
        self,
        *,
        work_dir: Path,
        duration_seconds: int = 30,
        ffmpeg_runner: FfmpegRunner = run_ffmpeg,
        target_fill_seconds: int = 3600,
    ) -> None:
        self._work_dir = work_dir
        self._duration_seconds = duration_seconds
        self._ffmpeg_runner = ffmpeg_runner
        # CA-8 finding: a single-segment plan relaunched the encoder (and
        # reset the TS session) every `duration_seconds` during slate
        # periods — a headend monitor logs CC errors at every reset. The
        # plan repeats the one rendered file to span this target; the
        # automation reload still interrupts it the moment a program is due.
        self._target_fill_seconds = target_fill_seconds

    def __call__(self, config: EgressConfig) -> EgressSourcePlan:
        output_path = self._work_dir / config.channel_id / "slate.ts"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = build_slate_source_args(
            output_path=output_path,
            config=config,
            duration_seconds=self._duration_seconds,
        )
        result = self._ffmpeg_runner(args)
        if result.returncode != 0:
            args = build_slate_source_args(
                output_path=output_path,
                config=config,
                duration_seconds=self._duration_seconds,
                include_text=False,
            )
            result = self._ffmpeg_runner(args)
        if result.returncode != 0:
            raise SourcePrepareError(
                "Could not generate the egress slate source; inspect FFmpeg output before retrying."
            )
        repeats = max(1, -(-self._target_fill_seconds // self._duration_seconds))
        segment = EgressSourceSegment(
            label="CivicCast slate",
            path=str(output_path),
            duration_seconds=self._duration_seconds,
            kind="slate",
            source_ref="civiccast-slate",
        )
        return EgressSourcePlan(
            channel_id=config.channel_id,
            segments=[segment] * repeats,
        )


class ScheduleSourcePlanProvider:
    """Build concrete egress source plans from scheduled local media."""

    def __init__(
        self,
        *,
        schedule_items_provider: ScheduleItemsProvider,
        asset_resolver: AssetResolver,
        now_provider: Callable[[], datetime] | None = None,
        max_segments: int = 8,
        gap_tolerance_seconds: float = 1.0,
    ) -> None:
        if max_segments <= 0:
            raise ValueError("max_segments must be greater than zero.")
        if gap_tolerance_seconds < 0:
            raise ValueError("gap_tolerance_seconds must be zero or greater.")
        self._schedule_items_provider = schedule_items_provider
        self._asset_resolver = asset_resolver
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._max_segments = max_segments
        self._gap_tolerance = timedelta(seconds=gap_tolerance_seconds)

    def __call__(self, channel_id: str) -> EgressSourcePlan | None:
        return build_source_plan_from_schedule(
            channel_id=channel_id,
            schedule_items=self._schedule_items_provider(channel_id),
            asset_resolver=self._asset_resolver,
            now=self._now_provider(),
            max_segments=self._max_segments,
            gap_tolerance=self._gap_tolerance,
        )


def build_source_plan_from_schedule(
    *,
    channel_id: str,
    schedule_items: Sequence[ScheduleItemResponse],
    asset_resolver: AssetResolver,
    now: datetime | None = None,
    max_segments: int = 8,
    gap_tolerance: timedelta = timedelta(seconds=1),
) -> EgressSourcePlan | None:
    """Return the currently playable egress source plan, or None for slate fallback."""

    if max_segments <= 0:
        raise ValueError("max_segments must be greater than zero.")
    if gap_tolerance < timedelta(0):
        raise ValueError("gap_tolerance must be zero or greater.")
    current_time = _as_utc(now or datetime.now(UTC))
    playable_items = [
        item
        for item in schedule_items
        if item.channel_id == channel_id
        # Commit-to-Air gate: only ``published`` items are airable — a
        # ``scheduled`` premiere has not been approved to air yet (via
        # commit, or auto-approval by autoschedule).
        and item.state == SCHEDULE_STATE_PUBLISHED
        and item.mode == SCHEDULE_MODE_PREMIERE
        and item.duration_seconds is not None
    ]
    playable_items.sort(key=lambda item: (item.scheduled_at, str(item.id)))
    current_index = _current_item_index(playable_items, current_time)
    if current_index is None:
        return None

    current_item = playable_items[current_index]
    # CA-2 join-in-progress: a (re)start mid-program resumes the CURRENT
    # item at the wall-clock offset so the channel stays on its published
    # log instead of replaying the program from the top.
    elapsed_seconds = max(0.0, (current_time - _as_utc(current_item.scheduled_at)).total_seconds())

    segments: list[EgressSourceSegment] = []
    cursor_end = _as_utc(current_item.scheduled_at) + timedelta(
        seconds=current_item.duration_seconds or 0
    )
    for item in playable_items[current_index:]:
        starts_at = _as_utc(item.scheduled_at)
        if segments and starts_at > cursor_end + gap_tolerance:
            break
        is_current = item is current_item
        segment = _segment_from_item(
            item, asset_resolver, elapsed_seconds=elapsed_seconds if is_current else 0.0
        )
        if segment is None:
            # The current item's media has fully aired (media shorter than
            # its slot, or a late rejoin past the end). Honest behavior is
            # slate until the next item is due — never an early start.
            return None
        segments.append(segment)
        cursor_end = max(
            cursor_end,
            starts_at + timedelta(seconds=item.duration_seconds or segment.duration_seconds),
        )
        if len(segments) >= max_segments:
            break

    if not segments:
        return None
    return EgressSourcePlan(channel_id=channel_id, segments=segments)


def build_slate_source_args(
    *,
    output_path: Path,
    config: EgressConfig,
    duration_seconds: int,
    include_text: bool = True,
) -> list[str]:
    """Build FFmpeg args for a canonical MPEG-TS slate source."""

    profile = config.canonical_profile
    video_input = (
        f"color=c=0x1a2744:size={profile.width}x{profile.height}"
        f":rate={profile.fps}:duration={duration_seconds}"
    )
    args = [
        "-f",
        "lavfi",
        "-i",
        video_input,
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={profile.audio_sample_rate}:cl=stereo",
    ]
    if include_text:
        args.extend(
            [
                "-vf",
                (
                    f"drawtext=expansion=none:text='{_escape_drawtext(config.slate_message)}':"
                    "fontsize=28:fontcolor=white:box=1:boxcolor=black@0.4:boxborderw=8:"
                    "x=(w-text_w)/2:y=(h-text_h)/2"
                ),
            ]
        )
    args.extend(
        [
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-g",
            str(profile.gop_size),
            "-c:a",
            profile.audio_codec,
            "-b:a",
            f"{profile.audio_bitrate_kbps}k",
            "-ar",
            str(profile.audio_sample_rate),
            "-ac",
            str(profile.audio_channels),
            "-shortest",
            "-f",
            "mpegts",
            str(output_path),
        ]
    )
    return args


def _escape_drawtext(value: str) -> str:
    """Escape a string for safe use inside a single-quoted ffmpeg drawtext value.

    This is the ONE shared escaping implementation for every ``drawtext=`` call
    site in the egress package (source_plan.py, bulletin_filler.py, and
    board_compositor.py all import this rather than keeping their own copy).
    Two independent copies previously existed and had already drifted once in
    call order (gate finding F-3) -- do not add a third; import this instead.

    The backslash MUST be escaped first, before the quote and colon, or a
    literal backslash introduced by a later replacement would itself get
    re-escaped. Every ``drawtext`` build site also passes ``expansion=none``,
    which is a separate, load-bearing control that disables ffmpeg's own
    ``%{...}``-style value expansion inside drawtext text (gate finding F-1 --
    without it, community-submitted text could reach ffmpeg's expansion
    syntax). Escaping here and ``expansion=none`` at the call site are both
    required; neither substitutes for the other.
    """
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _current_item_index(
    items: Sequence[ScheduleItemResponse],
    current_time: datetime,
) -> int | None:
    for index, item in enumerate(items):
        starts_at = _as_utc(item.scheduled_at)
        assert item.duration_seconds is not None
        ends_at = starts_at + timedelta(seconds=item.duration_seconds)
        if starts_at <= current_time < ends_at:
            return index
    return None


def _segment_from_item(
    item: ScheduleItemResponse,
    asset_resolver: AssetResolver,
    *,
    elapsed_seconds: float = 0.0,
) -> EgressSourceSegment | None:
    """Build the segment for one scheduled item.

    ``elapsed_seconds`` > 0 means a join-in-progress rejoin of the current
    item: playback resumes that far into the (trimmed) media. Returns None
    when the elapsed time exceeds the playable media — the item has fully
    aired and contributes nothing (the caller falls back to slate).
    """

    asset = asset_resolver(item.asset_id)
    if asset is None:
        raise SourcePrepareError(
            f"Scheduled asset {item.asset_id!r} is not in the local asset library."
        )
    if asset.state not in _PLAYABLE_ASSET_STATES:
        raise SourcePrepareError(
            f"Scheduled asset {item.asset_id!r} is {asset.state!r}, not ready for egress."
        )
    if not asset.file_path:
        raise SourcePrepareError(
            f"Scheduled asset {item.asset_id!r} has no local media file path for egress."
        )
    media_path = Path(asset.file_path).expanduser()
    if not media_path.exists() or not media_path.is_file():
        raise SourcePrepareError(
            f"Scheduled asset {item.asset_id!r} local media file is missing: {media_path}."
        )
    inpoint = asset.trim_in_seconds
    outpoint = asset.trim_out_seconds
    duration = _segment_duration(item, asset, inpoint=inpoint, outpoint=outpoint)
    if duration <= 0:
        raise SourcePrepareError(
            f"Scheduled asset {item.asset_id!r} has an invalid trim window for egress."
        )
    if elapsed_seconds > 0:
        if elapsed_seconds >= duration:
            return None
        inpoint = (inpoint or 0.0) + elapsed_seconds
        duration = duration - elapsed_seconds
    return EgressSourceSegment(
        label=asset.title or item.asset_title or item.asset_id,
        path=str(media_path),
        duration_seconds=duration,
        kind="program",
        source_ref=item.asset_id,
        inpoint_seconds=inpoint,
        outpoint_seconds=outpoint,
    )


def _segment_duration(
    item: ScheduleItemResponse,
    asset: StaffAssetRow,
    *,
    inpoint: float | None,
    outpoint: float | None,
) -> float:
    if inpoint is not None and outpoint is not None:
        if inpoint >= outpoint:
            return 0
        return outpoint - inpoint
    if asset.duration_seconds is not None:
        duration = float(asset.duration_seconds)
        if inpoint is not None:
            return duration - inpoint
        return duration
    assert item.duration_seconds is not None
    return float(item.duration_seconds)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
