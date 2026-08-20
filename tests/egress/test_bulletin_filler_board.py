# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Board-oriented bulletin filler tests (CG-1 integration)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.cable.channel import ChannelBranding
from civiccast.cg.board_resolver import ResolvedBoard
from civiccast.cg.models import (
    CgBulletinSubmission,
    CgTemplate,
    CgTemplateZone,
    CgZone,
    MultiZoneCgSnapshot,
)
from civiccast.egress.bulletin_filler import BulletinFillerSourceGenerator
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import CanonicalProfile, EgressConfig, EgressSinkSpec
from civiccast.stream._ffmpeg import FfmpegNotFoundError, FfmpegResult

NOW = datetime(2026, 8, 5, 19, 30, tzinfo=UTC)

_BRANDING = ChannelBranding(
    display_name="Public Access",
    short_name="PUB12",
    color="#2458A6",
    logo_text="PA",
)


def _config(*, fill_policy: str = "bulletins") -> EgressConfig:
    return EgressConfig(
        channel_id="public",
        enabled=True,
        fill_policy=fill_policy,  # type: ignore[arg-type]
        slate_message="CivicCast is preparing the channel.",
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _board(
    *,
    board_id: str = "board-1",
    zones: list[CgZone] | None = None,
    channel_id: str = "public",
) -> ResolvedBoard:
    tpl = CgTemplate(
        template_id="tpl-board-v1",
        label="Test board",
        regions=[
            CgTemplateZone(region="main", zone_kind="primary", order=0),
            CgTemplateZone(region="lower", zone_kind="ticker", order=1),
            CgTemplateZone(region="side", zone_kind="schedule", order=2),
            CgTemplateZone(region="bug", zone_kind="logo", order=3),
        ],
    )
    snapshot = MultiZoneCgSnapshot(
        snapshot_id="snap-1",
        generated_at=NOW,
        channel_id=channel_id,
        template=tpl,
        zones=zones
        or [
            CgZone(
                zone_id="z-primary",
                kind="primary",
                source="manual",
                content={},
                refresh_seconds=None,
                approved=True,
            ),
            CgZone(
                zone_id="z-ticker",
                kind="ticker",
                source="manual",
                content={"items": [{"title": "Road closure on Main St"}, {"title": "Permit day"}]},
                refresh_seconds=None,
                approved=True,
            ),
            CgZone(
                zone_id="z-schedule",
                kind="schedule",
                source="schedule",
                content={"mode": "clock"},
                refresh_seconds=None,
                approved=True,
            ),
            CgZone(
                zone_id="z-logo",
                kind="logo",
                source="image",
                content={"image_asset_ref": "asset://logo-lpm"},
                refresh_seconds=None,
                approved=True,
            ),
        ],
        hls_render_path="/cg/public/board.m3u8",
        portal_render_path="/cg/public/board.json",
        proof_boundary="test",
    )
    return ResolvedBoard(
        board_id=board_id,
        snapshot=snapshot,
        backfilled_kinds=[],
        degraded_zone_ids=[],
    )


def _bulletin(
    submission_id: str,
    *,
    title: str,
    state: str = "accepted",
) -> CgBulletinSubmission:
    return CgBulletinSubmission(
        submission_id=submission_id,
        organization="Pinegrove Garden Club",
        submitter_label="Garden Club coordinator",
        title=title,
        message="A short announcement for this bulletin.",
        target_zone_kind="primary",
        state=state,  # type: ignore[arg-type]
        approved_by_operator="op-1",
    )


def _windowed(
    *,
    submission_id: str,
    state: str = "accepted",
    start: datetime | None = None,
    end: datetime | None = None,
) -> CgBulletinSubmission:
    return CgBulletinSubmission(
        submission_id=submission_id,
        organization="Org",
        submitter_label="Volunteer",
        title=f"Notice {submission_id}",
        message="Body of the community notice.",
        target_zone_kind="primary",
        state=state,  # type: ignore[arg-type]
        requested_start=start,
        requested_end=end,
        approved_by_operator="op-2",
    )


def _runner(calls: list[list[str]], *, out_path: Path | None = None):  # type: ignore[no-untyped-def]
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        path_arg = out_path or Path(args[-1])
        path_arg.parent.mkdir(parents=True, exist_ok=True)
        path_arg.write_bytes(b"ts")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return run_ffmpeg


class TestBoardFillerIntegration:
    def test_active_board_renders_board_segment_per_airable_bulletin(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [
                _bulletin("cgb-1", title="Plant sale"),
                _bulletin("cgb-2", title="Food drive"),
            ],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_runner(calls),
            target_fill_seconds=25,
            branding_provider=lambda _cid: _BRANDING,
        )

        plan = generator(_config())

        assert len(plan.segments) == 4
        assert len(calls) == 2
        assert "board" in Path(plan.segments[0].path).parts
        assert [s.source_ref for s in plan.segments[:4]] == [
            "bulletin-cgb-1",
            "bulletin-cgb-2",
            "bulletin-cgb-1",
            "bulletin-cgb-2",
        ]
        joined = " ".join(calls[0])
        assert "x2" in joined or "x3" in joined

    def test_active_board_without_airable_bulletins_renders_one_empty_primary_segment(
        self, tmp_path: Path
    ) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [
                _windowed(
                    submission_id="expired",
                    state="accepted",
                    end=NOW.replace(hour=10),
                )
            ],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_runner(calls),
            target_fill_seconds=25,
            branding_provider=lambda _cid: _BRANDING,
        )

        plan = generator(_config())

        assert all(segment.source_ref == "board-empty" for segment in plan.segments)
        assert len(plan.segments) == 3
        assert len(calls) == 1
        assert all(segment.kind == "cg" for segment in plan.segments)

    def test_board_image_asset_ref_is_resolved_for_logo_overlay(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"PNG")

        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1", title="Plant sale")],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_runner(calls),
            target_fill_seconds=10,
            branding_provider=lambda _cid: _BRANDING,
            board_image_resolver=lambda _ref: logo,
        )

        plan = generator(_config())

        assert len(plan.segments) == 1
        assert str(logo) in " ".join(calls[0])


def _flaky_runner(calls: list[list[str]], *, fail_times: int = 1):  # type: ignore[no-untyped-def]
    """Fail the first ``fail_times`` calls (returncode 1), then succeed."""

    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        if len(calls) <= fail_times:
            return FfmpegResult(returncode=1, stdout="", stderr="boom: missing font")
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"ts")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return run_ffmpeg


def _always_failing_runner(calls: list[list[str]]):  # type: ignore[no-untyped-def]
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        return FfmpegResult(returncode=1, stdout="", stderr="boom: missing font")

    return run_ffmpeg


def _not_found_runner(calls: list[list[str]]):  # type: ignore[no-untyped-def]
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        raise FfmpegNotFoundError("ffmpeg is not on PATH")

    return run_ffmpeg


class TestBoardFailOpenAndRetry:
    """Pins the gate's Blocker fix (QA-1): board-path ffmpeg errors must never
    escape the filler uncaught -- they translate to SourcePrepareError so the
    daemon's existing fallback-to-slate contract handles them, and a text-render
    failure degrades to an image-only retry (with a WARNING naming the channel)
    rather than crashing the segment outright."""

    def test_ffmpeg_not_found_fails_open_as_source_prepare_error(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1", title="Plant sale")],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_not_found_runner(calls),
            branding_provider=lambda _cid: _BRANDING,
        )

        with pytest.raises(SourcePrepareError) as exc_info:
            generator(_config())

        # Pin the translation, not just "raises something": the daemon's
        # fallback contract keys off SourcePrepareError specifically, and the
        # original FfmpegNotFoundError must be chained, not discarded.
        assert not isinstance(exc_info.value, FfmpegNotFoundError)
        assert isinstance(exc_info.value.__cause__, FfmpegNotFoundError)
        assert len(calls) == 1, "a missing ffmpeg binary must not be retried"

    def test_text_render_failure_retry_logs_warning_naming_channel(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1", title="Plant sale")],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_flaky_runner(calls, fail_times=1),
            branding_provider=lambda _cid: _BRANDING,
            target_fill_seconds=10,
        )

        with caplog.at_level(logging.WARNING, logger="civiccast.egress.bulletin_filler"):
            plan = generator(_config())

        assert len(plan.segments) == 1
        assert len(calls) == 2, "expected a no-text retry after the first failure"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("public" in r.getMessage() for r in warnings), (
            "the text-degradation warning must name the channel"
        )

    def test_retry_disables_text_in_the_second_call(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1", title="Plant sale")],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_flaky_runner(calls, fail_times=1),
            branding_provider=lambda _cid: _BRANDING,
        )

        generator(_config())

        assert len(calls) == 2
        assert "drawtext" in " ".join(calls[0]), "first attempt renders WITH text"
        assert "drawtext" not in " ".join(calls[1]), "retry must render image-only"

    def test_both_attempts_failing_raises_source_prepare_error(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1", title="Plant sale")],
            board_provider=lambda _cid, _now: _board(),
            ffmpeg_runner=_always_failing_runner(calls),
            branding_provider=lambda _cid: _BRANDING,
        )

        with pytest.raises(SourcePrepareError, match="board segment"):
            generator(_config())
        assert len(calls) == 2, "expected exactly one no-text retry before giving up"
