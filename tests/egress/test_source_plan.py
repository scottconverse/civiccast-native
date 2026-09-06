# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from civiccast.egress import resolver
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    MAX_PLAYLIST_SUBCHAINS,
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
)
from civiccast.egress.source_plan import (
    PLAN_MIN_SECONDS,
    ScheduleSourcePlanProvider,
    SlateSourceGenerator,
    _escape_drawtext,
    build_slate_source_args,
    build_source_plan_from_schedule,
)
from civiccast.schedule.models import ScheduleItemResponse, StaffAssetRow
from civiccast.stream._ffmpeg import FfmpegResult


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel: please stand by.",
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _schedule_item(
    *,
    asset_id: str = "council-meeting",
    channel_id: str = "gov",
    scheduled_at: datetime,
    duration_seconds: int = 1800,
    state: str = "published",
) -> ScheduleItemResponse:
    return ScheduleItemResponse(
        id=uuid4(),
        asset_id=asset_id,
        asset_title="Council Meeting",
        channel_id=channel_id,
        mode="premiere",
        state=state,
        scheduled_at=scheduled_at,
        duration_seconds=duration_seconds,
        notes=None,
        created_at=scheduled_at - timedelta(days=1),
    )


def _asset(path: Path, *, asset_id: str = "council-meeting") -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title="Council Meeting",
        state="validated",
        file_path=str(path),
        duration_seconds=1800,
        trim_in_seconds=10,
        trim_out_seconds=120,
    )


def test_build_slate_source_args_uses_canonical_profile_and_escapes_message(
    tmp_path: Path,
) -> None:
    config = _config().model_copy(update={"slate_message": "Mayor's update: standby"})

    args = build_slate_source_args(
        output_path=tmp_path / "slate.ts",
        config=config,
        duration_seconds=30,
    )

    assert "color=c=0x1a2744:size=640x360:rate=30:duration=30" in args
    assert "1200k" in args
    assert "Mayor\\'s update\\: standby" in " ".join(args)
    assert args[-3:] == ["-f", "mpegts", str(tmp_path / "slate.ts")]


def test_build_slate_source_args_can_skip_drawtext(tmp_path: Path) -> None:
    args = build_slate_source_args(
        output_path=tmp_path / "slate.ts",
        config=_config(),
        duration_seconds=30,
        include_text=False,
    )

    assert "-vf" not in args
    assert "drawtext" not in " ".join(args)


class TestEscapeDrawtext:
    """Gate finding F-3: this is the ONE shared drawtext-escaping implementation.

    ``board_compositor.py`` and ``bulletin_filler.py`` both import this rather
    than keeping their own copy (previously two independent copies existed and
    had already drifted once in call order). These tests pin the exact
    metacharacter set both prior versions handled -- backslash, single quote,
    and colon -- plus the backslash-first ordering that keeps a
    later-introduced backslash from being re-escaped.
    """

    def test_backslash_is_doubled(self) -> None:
        assert _escape_drawtext("a\\b") == "a\\\\b"

    def test_single_quote_is_escaped(self) -> None:
        assert _escape_drawtext("Mayor's update") == "Mayor\\'s update"

    def test_colon_is_escaped(self) -> None:
        assert _escape_drawtext("18:30 meeting") == "18\\:30 meeting"

    def test_all_three_metacharacters_together_backslash_first(self) -> None:
        # If colon/quote escaping ran before backslash escaping, the
        # backslashes those steps introduce would get doubled again. Backslash
        # must run first so `\:` and `\'` survive as single backslashes.
        assert _escape_drawtext(r"Mayor's \ update: 5pm") == r"Mayor\'s \\ update\: 5pm"

    def test_plain_text_is_unchanged(self) -> None:
        assert _escape_drawtext("Community programming") == "Community programming"


def test_slate_source_generator_returns_source_plan(tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}
    generator = SlateSourceGenerator(
        work_dir=tmp_path,
        ffmpeg_runner=lambda args: (
            captured.setdefault("args", args) and FfmpegResult(returncode=0, stdout="", stderr="")
        ),
    )

    plan = generator(_config())

    assert plan.channel_id == "gov"
    assert plan.segments[0].label == "CivicCast slate"
    assert plan.segments[0].path.endswith("slate.ts")
    assert captured["args"][-1].endswith("slate.ts")


def test_slate_source_generator_falls_back_to_plain_color(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        return FfmpegResult(returncode=1 if len(calls) == 1 else 0, stdout="", stderr="")

    generator = SlateSourceGenerator(work_dir=tmp_path, ffmpeg_runner=runner)

    plan = generator(_config())

    assert plan.segments[0].label == "CivicCast slate"
    assert "-vf" in calls[0]
    assert "-vf" not in calls[1]


def test_slate_source_generator_raises_on_ffmpeg_failure(tmp_path: Path) -> None:
    generator = SlateSourceGenerator(
        work_dir=tmp_path,
        ffmpeg_runner=lambda _args: FfmpegResult(returncode=1, stdout="", stderr="boom"),
    )

    with pytest.raises(SourcePrepareError, match="Could not generate"):
        generator(_config())


def test_build_source_plan_from_schedule_uses_current_local_media_with_trim(
    tmp_path: Path,
) -> None:
    media = tmp_path / "council.ts"
    media.write_text("fake", encoding="utf-8")
    now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

    plan = build_source_plan_from_schedule(
        channel_id="gov",
        schedule_items=[
            _schedule_item(scheduled_at=now),
            _schedule_item(
                asset_id="next-meeting",
                scheduled_at=now + timedelta(minutes=30),
                duration_seconds=1200,
            ),
        ],
        asset_resolver=lambda asset_id: _asset(media, asset_id=asset_id),
        now=now,
    )

    assert plan is not None
    assert plan.channel_id == "gov"
    assert plan.segments[0].path == str(media)
    assert plan.segments[0].duration_seconds == 110
    assert plan.segments[0].inpoint_seconds == 10
    assert plan.segments[0].outpoint_seconds == 120
    # D42: the trim window is 110s but the slot is 30 minutes, so this item
    # UNDER-FILLS its slot. The plan stops here -- the rest of the slot belongs
    # to the channel's fill policy (bulletins/slate), reached through the
    # daemon's FALLBACK_SLATE gap-replan. Before this fix the next item was
    # appended anyway and therefore started 110s in instead of 30 minutes in.
    assert [segment.label for segment in plan.segments] == ["Council Meeting"]


def test_scheduled_uncommitted_item_is_excluded_from_the_plan(tmp_path: Path) -> None:
    """Commit-to-Air gate (spec test a): a premiere still in ``scheduled``
    state (not yet approved via commit, and not auto-approved by
    autoschedule) must not air — the resolver only plays ``published``
    items."""
    media = tmp_path / "council.ts"
    media.write_text("fake", encoding="utf-8")
    now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

    plan = build_source_plan_from_schedule(
        channel_id="gov",
        schedule_items=[_schedule_item(scheduled_at=now, state="scheduled")],
        asset_resolver=lambda asset_id: _asset(media, asset_id=asset_id),
        now=now,
    )

    assert plan is None


class TestJoinInProgress:
    """CA-2: a (re)start mid-program rejoins the current item at the
    wall-clock offset instead of replaying it from the top and drifting
    the channel off its published log."""

    def _long_asset(self, path: Path, *, asset_id: str = "council-meeting") -> StaffAssetRow:
        return StaffAssetRow(
            asset_id=asset_id,
            title="Council Meeting",
            state="validated",
            file_path=str(path),
            duration_seconds=1800,
            trim_in_seconds=None,
            trim_out_seconds=None,
        )

    def test_restart_mid_program_offsets_into_the_current_item(self, tmp_path: Path) -> None:
        media = tmp_path / "council.ts"
        media.write_text("fake", encoding="utf-8")
        now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now - timedelta(minutes=10))],
            asset_resolver=lambda asset_id: self._long_asset(media, asset_id=asset_id),
            now=now,
        )

        assert plan is not None
        segment = plan.segments[0]
        assert segment.inpoint_seconds == 600
        assert segment.duration_seconds == 1200

    def test_offset_respects_an_existing_trim_window(self, tmp_path: Path) -> None:
        media = tmp_path / "council.ts"
        media.write_text("fake", encoding="utf-8")
        now = datetime(2026, 6, 5, 18, 1, tzinfo=UTC)
        trimmed = StaffAssetRow(
            asset_id="council-meeting",
            title="Council Meeting",
            state="validated",
            file_path=str(media),
            duration_seconds=1800,
            trim_in_seconds=10,
            trim_out_seconds=1200,
        )

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now - timedelta(minutes=1))],
            asset_resolver=lambda _asset_id: trimmed,
            now=now,
        )

        assert plan is not None
        segment = plan.segments[0]
        # 60s elapsed: playback resumes 60s into the TRIMMED window.
        assert segment.inpoint_seconds == 70
        assert segment.outpoint_seconds == 1200
        assert segment.duration_seconds == 1130

    def test_exhausted_media_falls_back_to_slate_for_the_slot_remainder(
        self, tmp_path: Path
    ) -> None:
        media = tmp_path / "council.ts"
        media.write_text("fake", encoding="utf-8")
        now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)
        # Media (trim window) is only 110s long; the slot is 30 minutes.
        # 10 minutes in, the program has fully aired: honest behavior is
        # slate (None) until the next item is due — never replaying the
        # program and never starting the next item early.
        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[
                _schedule_item(scheduled_at=now - timedelta(minutes=10)),
                _schedule_item(
                    asset_id="next-meeting",
                    scheduled_at=now + timedelta(minutes=20),
                    duration_seconds=1200,
                ),
            ],
            asset_resolver=lambda asset_id: _asset(media, asset_id=asset_id),
            now=now,
        )

        assert plan is None

    def test_on_time_start_is_unchanged(self, tmp_path: Path) -> None:
        media = tmp_path / "council.ts"
        media.write_text("fake", encoding="utf-8")
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now)],
            asset_resolver=lambda asset_id: self._long_asset(media, asset_id=asset_id),
            now=now,
        )

        assert plan is not None
        assert plan.segments[0].inpoint_seconds is None
        assert plan.segments[0].duration_seconds == 1800

    def test_following_items_are_not_offset(self, tmp_path: Path) -> None:
        media = tmp_path / "council.ts"
        media.write_text("fake", encoding="utf-8")
        now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[
                _schedule_item(scheduled_at=now - timedelta(minutes=10)),
                _schedule_item(
                    asset_id="next-meeting",
                    scheduled_at=now + timedelta(minutes=20),
                    duration_seconds=1200,
                ),
            ],
            asset_resolver=lambda asset_id: self._long_asset(media, asset_id=asset_id),
            now=now,
        )

        assert plan is not None
        assert len(plan.segments) == 2
        assert plan.segments[0].inpoint_seconds == 600
        assert plan.segments[1].inpoint_seconds is None
        # D42: the second item's SLOT is 1200s even though its media runs 1800s.
        # The slot is the contract -- the media is clipped to it, not the other
        # way round (this asserted 1800 before the fix, i.e. the item overran
        # its published slot by ten minutes).
        assert plan.segments[1].duration_seconds == 1200


def test_build_source_plan_from_schedule_returns_none_without_current_item(
    tmp_path: Path,
) -> None:
    media = tmp_path / "future.ts"
    media.write_text("fake", encoding="utf-8")
    now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

    plan = build_source_plan_from_schedule(
        channel_id="gov",
        schedule_items=[_schedule_item(scheduled_at=now + timedelta(minutes=15))],
        asset_resolver=lambda _asset_id: _asset(media),
        now=now,
    )

    assert plan is None


def test_build_source_plan_from_schedule_raises_for_missing_local_media(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)
    missing_media = tmp_path / "missing.ts"

    with pytest.raises(SourcePrepareError, match="local media file is missing"):
        build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now - timedelta(minutes=10))],
            asset_resolver=lambda _asset_id: _asset(missing_media),
            now=now,
        )


def test_build_source_plan_from_schedule_raises_for_invalid_trim_window(
    tmp_path: Path,
) -> None:
    media = tmp_path / "council.ts"
    media.write_text("fake", encoding="utf-8")
    now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)
    asset = _asset(media).model_copy(update={"trim_in_seconds": 120, "trim_out_seconds": 10})

    with pytest.raises(SourcePrepareError, match="invalid trim window"):
        build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now - timedelta(minutes=10))],
            asset_resolver=lambda _asset_id: asset,
            now=now,
        )


def test_schedule_source_plan_provider_calls_schedule_and_asset_resolvers(
    tmp_path: Path,
) -> None:
    media = tmp_path / "council.ts"
    media.write_text("fake", encoding="utf-8")
    now = datetime(2026, 6, 5, 18, 10, tzinfo=UTC)
    seen: dict[str, str] = {}
    provider = ScheduleSourcePlanProvider(
        schedule_items_provider=lambda channel_id: (
            seen.setdefault("channel_id", channel_id) and [_schedule_item(scheduled_at=now)]
        ),
        asset_resolver=lambda asset_id: seen.setdefault("asset_id", asset_id) and _asset(media),
        now_provider=lambda: now,
    )

    plan = provider("gov")

    assert plan is not None
    assert seen == {"channel_id": "gov", "asset_id": "council-meeting"}


def test_resolver_module_exports_source_plan_contracts() -> None:
    assert resolver.ScheduleSourcePlanProvider is ScheduleSourcePlanProvider
    assert resolver.SlateSourceGenerator is SlateSourceGenerator
    assert resolver.build_source_plan_from_schedule is build_source_plan_from_schedule
    assert resolver.build_slate_source_args is build_slate_source_args


def test_slate_plan_spans_the_fill_target_with_one_rendered_file(tmp_path: Path) -> None:
    # CA-8 finding: a 30s single-segment plan made the encoder relaunch (and
    # reset the TS session) every 30s during slate periods. The plan now
    # repeats the one rendered slate file to span the fill target; the
    # automation reload still interrupts it the moment a program is due.
    #
    # BLOCKER B fix (2026-09-05 regression from #174): the fixed 30s
    # duration_seconds used to mean 120 repeats for a 3600s target --
    # gst/bridge.graph_from_config truncates a plan past MAX_PLAYLIST_
    # SUBCHAINS (12) segments, so the slate worker actually hit a real EOS
    # (and restarted) after only ~360s of a 3600s target. The generator now
    # holds the rendered card longer instead, so the plan never NEEDS more
    # than MAX_PLAYLIST_SUBCHAINS segments to cover the target.
    calls: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        return FfmpegResult(returncode=0, stdout="", stderr="")

    generator = SlateSourceGenerator(
        work_dir=tmp_path, ffmpeg_runner=runner, target_fill_seconds=3600
    )

    plan = generator(_config())

    assert len(calls) == 1  # one render, many repeats
    assert len(plan.segments) <= MAX_PLAYLIST_SUBCHAINS
    assert len(plan.segments) == 12  # 3600 / 300 (the per-segment hold this fix computes)
    assert len({segment.path for segment in plan.segments}) == 1
    total = sum(segment.duration_seconds for segment in plan.segments)
    assert total >= 3600


def test_slate_plan_still_repeats_short_segments_when_under_the_playlist_cap(
    tmp_path: Path,
) -> None:
    """A target the default 30s duration already covers within the cap is
    unaffected -- no need to lengthen the card just because the fix exists."""
    generator = SlateSourceGenerator(
        work_dir=tmp_path,
        ffmpeg_runner=lambda _args: FfmpegResult(returncode=0, stdout="", stderr=""),
        target_fill_seconds=200,
    )

    plan = generator(_config())

    assert len(plan.segments) == 7  # ceil(200 / 30), well under the cap
    assert all(segment.duration_seconds == 30 for segment in plan.segments)


def _asset_of(
    path: Path,
    *,
    duration_seconds: int,
    asset_id: str = "council-meeting",
    trim_in: float | None = None,
    trim_out: float | None = None,
) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title="Council Meeting",
        state="validated",
        file_path=str(path),
        duration_seconds=duration_seconds,
        trim_in_seconds=trim_in,
        trim_out_seconds=trim_out,
    )


def _media(tmp_path: Path) -> Path:
    media = tmp_path / "council.ts"
    media.write_text("fake", encoding="utf-8")
    return media


def _slot_schedule(
    now: datetime, *, count: int, slot_seconds: int = 30
) -> list[ScheduleItemResponse]:
    return [
        _schedule_item(
            asset_id=f"item-{index}",
            scheduled_at=now + timedelta(seconds=slot_seconds * index),
            duration_seconds=slot_seconds,
        )
        for index in range(count)
    ]


class TestSlotDuration:
    """D42 (real-hardware soak on the tester, 2026-09-05).

    ``_segment_duration`` returned the ASSET's playable length and ignored
    ``item.duration_seconds`` (the published schedule slot) entirely: a 30s
    slot holding an hour of media aired for the whole hour, so the schedule
    was not honoured at all; conversely a schedule of short assets built a
    plan far shorter than the slots it covered. The slot is the contract; the
    media can only ever cut it short.
    """

    def test_long_media_is_clipped_to_its_thirty_second_slot(self, tmp_path: Path) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=4),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
        )

        assert plan is not None
        # Before the fix every one of these was 3600s: an hour of media in a
        # 30-second slot, playing straight over the next three programs.
        assert [segment.duration_seconds for segment in plan.segments] == [30.0, 30.0, 30.0, 30.0]

    def test_join_in_progress_offsets_within_the_slot_not_the_asset(self, tmp_path: Path) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, 20, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[
                _schedule_item(scheduled_at=now - timedelta(seconds=20), duration_seconds=30)
            ],
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
        )

        assert plan is not None
        segment = plan.segments[0]
        assert segment.inpoint_seconds == 20  # 20s into the slot
        assert segment.duration_seconds == 10  # the 10s of slot that remain

    def test_a_trim_window_longer_than_the_slot_clips_and_moves_the_outpoint(
        self, tmp_path: Path
    ) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=[_schedule_item(scheduled_at=now, duration_seconds=30)],
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id, trim_in=100, trim_out=900
            ),
            now=now,
        )

        assert plan is not None
        segment = plan.segments[0]
        assert segment.duration_seconds == 30
        assert segment.inpoint_seconds == 100
        # A stale 900 out-point would let a trim-aware consumer
        # (preparer._emit_prepared_from_cache with playout_trim_supported)
        # emit 800s of media for a 30s slot.
        assert segment.outpoint_seconds == 130

    def test_media_shorter_than_its_slot_ends_the_plan_for_the_fill_policy(
        self, tmp_path: Path
    ) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        def resolver(asset_id: str) -> StaffAssetRow:
            # The FIRST item's media runs 400s inside a 600s slot; the rest
            # fill their slots exactly.
            duration = 400 if asset_id == "item-0" else 600
            return _asset_of(media, duration_seconds=duration, asset_id=asset_id)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=4, slot_seconds=600),
            asset_resolver=resolver,
            now=now,
        )

        assert plan is not None
        # The 200s the media cannot cover belong to the channel's fill policy
        # (bulletin_filler.FillerSourceProvider -> bulletins or slate), reached
        # through the daemon's FALLBACK_SLATE gap-replan -- the same honest
        # answer the already-aired current item gives. Nothing loops the media,
        # and item-1 is NOT started 200 seconds early.
        assert [segment.duration_seconds for segment in plan.segments] == [400.0]

    def test_media_within_the_gap_tolerance_of_its_slot_still_continues(
        self, tmp_path: Path
    ) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=3),
            # 29.97s of media in a 30s slot must not truncate the plan on
            # every single build.
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=30, asset_id=asset_id, trim_in=0.0, trim_out=29.97
            ),
            now=now,
        )

        assert plan is not None
        assert len(plan.segments) == 3


class TestPlanWindow:
    """D43 (superseded by D45): the plan window used to be bounded by
    DURATION as well as by count -- ``PLAN_MIN_SECONDS`` defaulted to 1800.0
    so a schedule of 30-second slots chased a 60-segment, 1800-second plan
    instead of the count-only 8-segment, 240-second one.

    Real-hardware soak evidence (3 GStreamer channels, 30-second items
    back-to-back) measured what that duration target actually cost:
    ``bridge.graph_from_config`` builds ONE decoder sub-chain PER segment in
    a single pipeline set to PLAYING all at once, so 60 segments produced
    ~1200 avdec_h264 threads and ~3.5 GB on one worker -- no TS output landed
    inside the engine's 10s stall watchdog, and every worker relaunched
    roughly every 30s. D45 reverts ``PLAN_MIN_SECONDS`` to 0.0: a normal
    plan's segment count is bounded by ``max_segments`` (pipeline shape)
    alone by default now. A caller that explicitly wants a longer
    duration-bounded window (and can bear the bigger pipeline) can still opt
    in via ``min_plan_seconds`` -- exercised below too.
    """

    def test_thirty_second_slots_build_only_max_segments_by_default(self, tmp_path: Path) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=200),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
        )

        assert plan is not None
        # D45: PLAN_MIN_SECONDS defaults to 0.0 -- max_segments (8 by
        # default) is what bounds a normal plan's segment count, not a
        # duration target that used to build 60 segments (and ~1200 decoder
        # threads) out of 30-second slots.
        assert PLAN_MIN_SECONDS == 0.0
        assert len(plan.segments) == 8
        total = sum(segment.duration_seconds for segment in plan.segments)
        assert total == 240.0

    def test_min_plan_seconds_widens_the_window_only_up_to_the_pipeline_cap(
        self, tmp_path: Path
    ) -> None:
        """Hostile-review fix (2026-09-05): a caller cannot opt its way past
        ``MAX_PLAYLIST_SUBCHAINS`` -- the pipeline-shape ceiling always wins,
        because ``build_source_plan_from_schedule`` is the plan's only
        producer and every OTHER consumer (``automation.py``'s rollover-
        horizon tracking, ``daemon.py``, ``continuity.py``, ``preparer.py``)
        trusts whatever segment count it returns as the plan the pipeline
        will actually play. 1800s of planned duration out of 30-second slots
        would need 60 segments; the default ``segment_cap``
        (``MAX_PLAYLIST_SUBCHAINS``, 12) stops it at 360s instead."""
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=200),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
            # A caller that explicitly wants a longer duration-bounded plan
            # can still ask for it -- but not past the pipeline cap.
            min_plan_seconds=1800.0,
        )

        assert plan is not None
        assert len(plan.segments) == MAX_PLAYLIST_SUBCHAINS
        total = sum(segment.duration_seconds for segment in plan.segments)
        assert total == MAX_PLAYLIST_SUBCHAINS * 30.0
        assert total < 1800.0

    def test_an_explicit_segment_cap_above_the_pipeline_ceiling_is_clamped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Hostile-review fix: a caller cannot ask its way past
        ``MAX_PLAYLIST_SUBCHAINS`` by passing an explicit larger
        ``segment_cap``/``max_segments`` either -- both are clamped down
        (with a WARNING naming the channel), because a plan larger than one
        pipeline can safely decode is exactly the regression this module
        exists to prevent. 1-second slots: 1800 of them would be needed to
        reach ``min_plan_seconds``, and an oversized ``segment_cap`` (120,
        the module's pre-D45 historical ceiling) would let the segment
        count get there if it were still honoured."""
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        with caplog.at_level("WARNING"):
            plan = build_source_plan_from_schedule(
                channel_id="gov",
                schedule_items=_slot_schedule(now, count=400, slot_seconds=1),
                asset_resolver=lambda asset_id: _asset_of(
                    media, duration_seconds=3600, asset_id=asset_id
                ),
                now=now,
                min_plan_seconds=1800.0,
                segment_cap=120,
            )

        assert plan is not None
        assert len(plan.segments) == MAX_PLAYLIST_SUBCHAINS
        assert any(
            "gov" in record.message and "MAX_PLAYLIST_SUBCHAINS" in record.message
            for record in caplog.records
        )

    def test_long_items_still_stop_at_max_segments(self, tmp_path: Path) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            # 30-minute slots: the count bound (max_segments) is what
            # applies regardless of min_plan_seconds. A long-item schedule
            # is unaffected by D45.
            schedule_items=_slot_schedule(now, count=40, slot_seconds=1800),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=1800, asset_id=asset_id
            ),
            now=now,
        )

        assert plan is not None
        assert len(plan.segments) == 8

    def test_end_to_end_a_thirty_second_schedule_never_exceeds_eight_subchains(
        self, tmp_path: Path
    ) -> None:
        """Hostile-review fix (2026-09-05), BLOCKER 1: the clamp has to live
        at the plan's producer, not just in ``bridge.graph_from_config`` --
        otherwise a consumer that trusts the plan's own segment count
        (``automation.py``'s rollover-horizon tracking, ``daemon.py``'s
        dispatched-plan bookkeeping) disagrees with what the pipeline
        actually plays. Proven end-to-end here: build a real plan from a
        30-second-item schedule with ``build_source_plan_from_schedule``,
        feed that SAME plan into ``graph_from_config``, and check the two
        never disagree about the segment/sub-chain count -- not just that
        each is separately capped."""
        from civiccast.egress.gst.bridge import graph_from_config
        from civiccast.egress.gst.graph import PlaylistLeg

        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=200),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
        )
        assert plan is not None
        assert len(plan.segments) <= 8

        graph = graph_from_config(_config(), plan)
        program, _slate = graph.sources
        assert isinstance(program, PlaylistLeg)
        assert len(program.subchains) <= 8
        # The invariant BLOCKER 1 asked for: the plan built by the producer
        # and the graph built by the consumer agree on the segment count --
        # nothing was silently truncated on the bridge side because the
        # producer had already handed it a plan the pipeline can play in
        # full.
        assert len(program.subchains) == len(plan.segments)

    def test_end_to_end_agreement_holds_exactly_AT_the_cap(self, tmp_path: Path) -> None:
        """Item 6: the test above proves agreement well UNDER the cap
        (``max_segments=8``); prove it also holds exactly AT the cap, where
        a prior version of ``graph_from_config`` would have hit its own
        (now removed) truncation branch instead of building the full plan.
        A caller that explicitly asks for ``max_segments=MAX_PLAYLIST_
        SUBCHAINS`` gets a plan of exactly that many segments, and
        ``graph_from_config`` builds exactly that many sub-chains from it --
        not one fewer."""
        from civiccast.egress.gst.bridge import graph_from_config
        from civiccast.egress.gst.graph import PlaylistLeg

        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)

        plan = build_source_plan_from_schedule(
            channel_id="gov",
            schedule_items=_slot_schedule(now, count=200),
            asset_resolver=lambda asset_id: _asset_of(
                media, duration_seconds=3600, asset_id=asset_id
            ),
            now=now,
            max_segments=MAX_PLAYLIST_SUBCHAINS,
        )
        assert plan is not None
        assert len(plan.segments) == MAX_PLAYLIST_SUBCHAINS

        graph = graph_from_config(_config(), plan)
        program, _slate = graph.sources
        assert isinstance(program, PlaylistLeg)
        assert len(program.subchains) == MAX_PLAYLIST_SUBCHAINS
        assert len(program.subchains) == len(plan.segments)

    def test_min_plan_seconds_and_segment_cap_are_validated(self, tmp_path: Path) -> None:
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)
        resolver = lambda asset_id: _asset_of(  # noqa: E731
            media, duration_seconds=3600, asset_id=asset_id
        )

        with pytest.raises(ValueError, match="segment_cap"):
            build_source_plan_from_schedule(
                channel_id="gov",
                schedule_items=_slot_schedule(now, count=2),
                asset_resolver=resolver,
                now=now,
                max_segments=8,
                segment_cap=4,
            )
        with pytest.raises(ValueError, match="min_plan_seconds"):
            build_source_plan_from_schedule(
                channel_id="gov",
                schedule_items=_slot_schedule(now, count=2),
                asset_resolver=resolver,
                now=now,
                min_plan_seconds=-1.0,
            )

    def test_an_inconsistent_pair_above_the_cap_raises_rather_than_clamping_silently(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Hostile-review fix (2026-09-05): the raw-pair validation
        (``segment_cap`` must be at least ``max_segments``) has to run
        BEFORE the ``MAX_PLAYLIST_SUBCHAINS`` clamp, not after -- otherwise
        an inconsistent caller-supplied pair that both happen to exceed the
        pipeline cap (``max_segments=20``, ``segment_cap=15``) would get
        silently clamped down to an agreeing pair (12/12) instead of
        surfacing that the caller's own request never made sense on its own
        terms. A CONSISTENT pair above the cap (20/20) is a different
        case -- both values agree with each other, so they are clamped down
        together (with a WARNING), not rejected."""
        media = _media(tmp_path)
        now = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)
        resolver = lambda asset_id: _asset_of(  # noqa: E731
            media, duration_seconds=3600, asset_id=asset_id
        )

        with pytest.raises(ValueError, match="segment_cap"):
            build_source_plan_from_schedule(
                channel_id="gov",
                schedule_items=_slot_schedule(now, count=2),
                asset_resolver=resolver,
                now=now,
                max_segments=20,
                segment_cap=15,
            )

        with caplog.at_level("WARNING"):
            plan = build_source_plan_from_schedule(
                channel_id="gov",
                schedule_items=_slot_schedule(now, count=200),
                asset_resolver=resolver,
                now=now,
                max_segments=20,
                segment_cap=20,
            )
        assert plan is not None
        assert len(plan.segments) == MAX_PLAYLIST_SUBCHAINS
        assert any(
            "gov" in record.message and "MAX_PLAYLIST_SUBCHAINS" in record.message
            for record in caplog.records
        )
