# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Source-plan providers for channel egress."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    MAX_PLAYLIST_SUBCHAINS,
    EgressConfig,
    EgressSourcePlan,
    EgressSourceSegment,
)
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

_LOG = logging.getLogger(__name__)

AssetResolver = Callable[[str], StaffAssetRow | None]
ScheduleItemsProvider = Callable[[str], Sequence[ScheduleItemResponse]]
_PLAYABLE_ASSET_STATES = {ASSET_STATE_VALIDATED, ASSET_STATE_RECORDED}

#: D45 fix (2026-09-05): D43 (#170) set this to 1800.0 to lengthen a
#: schedule-derived plan for the sake of the ROLLOVER cadence (see
#: ``automation._check_plan_rollover``'s D43 comments). Real-hardware soak
#: evidence (3 GStreamer channels, a schedule of 30-second items
#: back-to-back) then measured the actual cost of that: chasing 1800s of
#: planned duration out of 30-second slots builds ~60 segments per plan, and
#: ``bridge.graph_from_config`` builds ONE filesrc->decodebin->videoconvert->
#: videoscale->videorate sub-chain PER segment in a SINGLE pipeline that is
#: set to PLAYING all at once (``engine._build_playlist``) -- avdec_h264 at
#: its default max-threads=0 spins up ~20 threads per sub-chain, so 60
#: sub-chains produced ~1200 threads and ~3.5 GB on one worker, with no TS
#: buffer landing inside the 10s stall watchdog
#: (``engine.py``'s ``CTRL stall: no output for 10s``). Every worker
#: relaunched roughly every 30s. The pipeline SHAPE (segment count) has to
#: be bounded on its own terms -- CPU-only stations building 1200 decoder
#: threads is unsafe regardless of how "correct" the resulting wall-clock
#: window is -- so this is back to 0.0 (no duration floor at all;
#: ``max_segments`` alone decides how many sub-chains a plan gets). The
#: rollover-cadence problem D43 was actually solving is fixed at its own
#: layer instead: ``ChannelAutomationService._rollover_min_interval_seconds``
#: (automation.py) now derives its per-channel dispatch floor from the
#: ON-AIR plan's own duration rather than a fixed 300s, so a short plan still
#: gets rolled over comfortably inside its own lifetime.
PLAN_MIN_SECONDS = 0.0


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
        min_plan_seconds: float = PLAN_MIN_SECONDS,
        segment_cap: int = MAX_PLAYLIST_SUBCHAINS,
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
        self._min_plan_seconds = min_plan_seconds
        self._segment_cap = segment_cap
        self._gap_tolerance = timedelta(seconds=gap_tolerance_seconds)

    def __call__(self, channel_id: str) -> EgressSourcePlan | None:
        return build_source_plan_from_schedule(
            channel_id=channel_id,
            schedule_items=self._schedule_items_provider(channel_id),
            asset_resolver=self._asset_resolver,
            now=self._now_provider(),
            max_segments=self._max_segments,
            min_plan_seconds=self._min_plan_seconds,
            segment_cap=self._segment_cap,
            gap_tolerance=self._gap_tolerance,
        )


def build_source_plan_from_schedule(
    *,
    channel_id: str,
    schedule_items: Sequence[ScheduleItemResponse],
    asset_resolver: AssetResolver,
    now: datetime | None = None,
    max_segments: int = 8,
    min_plan_seconds: float = PLAN_MIN_SECONDS,
    segment_cap: int = MAX_PLAYLIST_SUBCHAINS,
    gap_tolerance: timedelta = timedelta(seconds=1),
) -> EgressSourcePlan | None:
    """Return the currently playable egress source plan, or None for slate fallback.

    The window is bounded by COUNT first (``max_segments``, 8 by default) --
    each segment becomes its own decoder sub-chain in the egress pipeline
    (``bridge.graph_from_config``), so the segment count IS the pipeline's
    shape, not just a wall-clock convenience. ``min_plan_seconds`` (D45: 0.0
    by default) is an OPTIONAL additional duration floor for a caller that
    explicitly wants a longer window and can bear a bigger pipeline; segments
    are appended until there are at least ``max_segments`` of them AND the
    plan spans at least ``min_plan_seconds``, whichever condition is
    satisfied later. ``segment_cap`` is the hard upper bound on the segment
    count regardless of either.

    Each segment is clipped to its SCHEDULE SLOT (D42): the slot is the
    contract, so long media in a 30-second slot plays for 30 seconds, not
    for its full asset length. When the media is SHORTER than its slot the
    plan stops at that item: the remainder of the slot belongs to the
    channel's fill policy (``bulletin_filler.FillerSourceProvider`` --
    bulletins or slate), reached through the daemon's FALLBACK_SLATE
    gap-replan path, exactly as an already-aired current item does below.
    Nothing here loops or stretches media to cover a slot, and no following
    item is ever started early.
    """

    if max_segments <= 0:
        raise ValueError("max_segments must be greater than zero.")
    if min_plan_seconds < 0:
        raise ValueError("min_plan_seconds must be zero or greater.")
    if gap_tolerance < timedelta(0):
        raise ValueError("gap_tolerance must be zero or greater.")
    # Hostile-review fix (2026-09-05): validate the CALLER's raw pair first,
    # before either is touched by the pipeline-shape clamp below. A caller
    # that explicitly asks for an inconsistent pair (e.g. max_segments=20,
    # segment_cap=15) is asking for something that was never sensible on its
    # own terms -- that is a caller bug to surface loudly, not something the
    # clamp below should silently paper over by coincidentally shrinking
    # both values into agreement (20/15 clamped to 12/12 would look "fixed"
    # while hiding that the caller's own request was self-contradictory).
    if segment_cap < max_segments:
        raise ValueError("segment_cap must be at least max_segments.")
    # The cap that bounds the pipeline SHAPE has to live here, at the plan's
    # only producer, not in ``bridge.graph_from_config`` alone. A
    # caller-side ``max_segments``/``segment_cap`` above
    # ``MAX_PLAYLIST_SUBCHAINS`` used to build a plan every OTHER consumer
    # (``automation.py``'s rollover-horizon tracking, ``daemon.py``'s
    # dispatched-plan bookkeeping, ``continuity.py``, ``preparer.py``)
    # trusted at its full, uncapped size, while the bridge silently played
    # only the first ``MAX_PLAYLIST_SUBCHAINS`` of it -- the pipeline would
    # reach EOS long before automation's tracked horizon expected it to,
    # restarting the worker on a cadence the rest of the system had no idea
    # was coming. Clamping the inputs here instead means every consumer
    # reads the SAME plan the pipeline will actually play; a plan returned
    # by this function can never disagree with what ``graph_from_config``
    # builds from it. This runs AFTER the raw-pair validation above: a
    # caller whose own numbers already agree with each other (e.g. 20/20)
    # gets both quietly clamped down together, in step, rather than raising
    # over a cap the caller had no way to know about at the call site.
    if max_segments > MAX_PLAYLIST_SUBCHAINS:
        _LOG.warning(
            "build_source_plan_from_schedule(%s): max_segments=%d exceeds "
            "MAX_PLAYLIST_SUBCHAINS=%d (the hard per-pipeline decoder-chain cap); "
            "clamping to %d.",
            channel_id,
            max_segments,
            MAX_PLAYLIST_SUBCHAINS,
            MAX_PLAYLIST_SUBCHAINS,
        )
        max_segments = MAX_PLAYLIST_SUBCHAINS
    if segment_cap > MAX_PLAYLIST_SUBCHAINS:
        _LOG.warning(
            "build_source_plan_from_schedule(%s): segment_cap=%d exceeds "
            "MAX_PLAYLIST_SUBCHAINS=%d (the hard per-pipeline decoder-chain cap); "
            "clamping to %d.",
            channel_id,
            segment_cap,
            MAX_PLAYLIST_SUBCHAINS,
            MAX_PLAYLIST_SUBCHAINS,
        )
        segment_cap = MAX_PLAYLIST_SUBCHAINS
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
    planned_seconds = 0.0
    cursor_end = _as_utc(current_item.scheduled_at) + timedelta(
        seconds=current_item.duration_seconds or 0
    )
    for item in playable_items[current_index:]:
        starts_at = _as_utc(item.scheduled_at)
        if segments and starts_at > cursor_end + gap_tolerance:
            break
        is_current = item is current_item
        item_elapsed = elapsed_seconds if is_current else 0.0
        segment = _segment_from_item(item, asset_resolver, elapsed_seconds=item_elapsed)
        if segment is None:
            # The current item's media has fully aired (media shorter than
            # its slot, or a late rejoin past the end). Honest behavior is
            # slate until the next item is due — never an early start.
            return None
        segments.append(segment)
        planned_seconds += segment.duration_seconds
        cursor_end = max(
            cursor_end,
            starts_at + timedelta(seconds=item.duration_seconds or segment.duration_seconds),
        )
        if len(segments) >= segment_cap:
            break
        if not _covers_slot(
            item,
            segment,
            elapsed_seconds=item_elapsed,
            tolerance_seconds=gap_tolerance.total_seconds(),
        ):
            # D42: this item's media runs out before its slot does. The rest
            # of the slot is the fill policy's (bulletins/slate) — stop the
            # plan here rather than starting the NEXT item early, the same
            # honest answer the fully-aired branch above already gives.
            break
        if len(segments) >= max_segments and planned_seconds >= min_plan_seconds:
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
    if outpoint is not None:
        # D42: ``duration`` may now be the SLOT rather than the whole trim
        # window, so the out-point has to follow it — a stale outpoint would
        # let a trim-aware consumer (preparer._emit_prepared_from_cache with
        # ``playout_trim_supported``, build_conform_source_args) emit more
        # media than the slot actually bought.
        outpoint = min(outpoint, (inpoint or 0.0) + duration)
    return EgressSourceSegment(
        label=asset.title or item.asset_title or item.asset_id,
        path=str(media_path),
        duration_seconds=duration,
        kind="program",
        source_ref=item.asset_id,
        inpoint_seconds=inpoint,
        outpoint_seconds=outpoint,
    )


def _covers_slot(
    item: ScheduleItemResponse,
    segment: EgressSourceSegment,
    *,
    elapsed_seconds: float,
    tolerance_seconds: float,
) -> bool:
    """Whether this item's media fills its whole scheduled slot.

    ``elapsed_seconds`` is the join-in-progress offset already consumed from
    the slot, so the comparison is against the slot as a whole, not the
    remaining part of it. ``tolerance_seconds`` (the caller's gap tolerance,
    1s by default) keeps a 29.97s asset in a 30s slot from being treated as
    an under-fill on every single plan.
    """

    if item.duration_seconds is None:
        return True
    slot_seconds = float(item.duration_seconds)
    aired_seconds = elapsed_seconds + segment.duration_seconds
    return aired_seconds + tolerance_seconds >= slot_seconds


def _segment_duration(
    item: ScheduleItemResponse,
    asset: StaffAssetRow,
    *,
    inpoint: float | None,
    outpoint: float | None,
) -> float:
    """The airtime this item contributes: its SLOT, capped by playable media.

    D42 (real-hardware soak, 2026-09-05): this used to return the asset's own
    playable length and ignore ``item.duration_seconds`` entirely, so a
    30-second schedule slot holding an hour-long recording aired for the
    whole hour — the published schedule was not honoured at all — while a
    schedule of short assets built a plan far shorter than its own slots.
    The slot is the contract; the media can only ever cut it short.
    """

    playable = _playable_duration(asset, inpoint=inpoint, outpoint=outpoint)
    if item.duration_seconds is None:
        # No slot on record (should not happen: the caller filters these out)
        # — fall back to whatever the media offers.
        return playable if playable is not None else 0.0
    slot = float(item.duration_seconds)
    if playable is None:
        # Un-probed asset with no trim window: the slot is the only number
        # available, exactly as before this change.
        return slot
    return min(slot, playable)


def _playable_duration(
    asset: StaffAssetRow,
    *,
    inpoint: float | None,
    outpoint: float | None,
) -> float | None:
    """Seconds of media playable from ``inpoint``, or None when unknowable.

    A non-positive result (an inverted trim window) is returned as-is so the
    caller raises the existing ``invalid trim window`` SourcePrepareError.
    """

    if inpoint is not None and outpoint is not None:
        return outpoint - inpoint
    if asset.duration_seconds is not None:
        end = float(asset.duration_seconds)
        if outpoint is not None:
            end = min(end, outpoint)
        return end - (inpoint or 0.0)
    if outpoint is not None:
        return outpoint - (inpoint or 0.0)
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
