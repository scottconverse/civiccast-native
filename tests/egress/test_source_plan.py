# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from civiccast.egress import resolver
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import CanonicalProfile, EgressConfig, EgressSinkSpec
from civiccast.egress.source_plan import (
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
    assert [segment.label for segment in plan.segments] == ["Council Meeting", "Council Meeting"]
    assert plan.segments[0].path == str(media)
    assert plan.segments[0].duration_seconds == 110
    assert plan.segments[0].inpoint_seconds == 10
    assert plan.segments[0].outpoint_seconds == 120


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
        assert plan.segments[1].duration_seconds == 1800


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
    calls: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        return FfmpegResult(returncode=0, stdout="", stderr="")

    generator = SlateSourceGenerator(
        work_dir=tmp_path, ffmpeg_runner=runner, target_fill_seconds=3600
    )

    plan = generator(_config())

    assert len(calls) == 1  # one render, many repeats
    assert len(plan.segments) == 120  # 3600 / 30
    assert len({segment.path for segment in plan.segments}) == 1
    total = sum(segment.duration_seconds for segment in plan.segments)
    assert total >= 3600
