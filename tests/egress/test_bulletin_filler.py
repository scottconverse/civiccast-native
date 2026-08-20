# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bulletin filler renderer tests (cable automation CA-3).

Approved community bulletins render to a rotation of ffmpeg slide segments
(one MPEG-TS per bulletin) used as the channel's gap filler. No bulletins →
honest delegation to the plain slate. Content-hash caching avoids
re-rendering an unchanged board on every gap.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from civiccast.cable.channel import ChannelBranding
from civiccast.cg.models import CgBulletinSubmission
from civiccast.egress.bulletin_filler import (
    BulletinFillerSourceGenerator,
    FillerSourceProvider,
    build_bulletin_slide_args,
)
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import CanonicalProfile, EgressConfig, EgressSinkSpec
from civiccast.egress.source_plan import SlateSourceGenerator
from civiccast.stream._ffmpeg import FfmpegNotFoundError, FfmpegResult


def _config(*, fill_policy: str = "bulletins") -> EgressConfig:
    return EgressConfig(
        channel_id="public",
        enabled=True,
        fill_policy=fill_policy,  # type: ignore[arg-type]
        slate_message="CivicCast is preparing the channel.",
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _bulletin(submission_id: str, *, title: str = "Spring plant sale") -> CgBulletinSubmission:
    return CgBulletinSubmission(
        submission_id=submission_id,
        organization="Pinegrove Garden Club",
        submitter_label="Garden Club coordinator",
        title=title,
        message="Saturday 9am at the community center. Proceeds support the seed library.",
        target_zone_kind="primary",
        state="accepted",
        approved_by_operator="op-hash-1",
    )


_BRANDING = ChannelBranding(
    display_name="Public Access",
    short_name="PUB12",
    color="#2458A6",
    logo_text="PA",
)


def _ok_runner(calls: list[list[str]]):  # type: ignore[no-untyped-def]
    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        # Touch the output file so cache checks see it.
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"ts")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return runner


class TestSlideArgs:
    def test_args_use_branding_color_station_bug_and_wrapped_text(self, tmp_path: Path) -> None:
        args = build_bulletin_slide_args(
            output_path=tmp_path / "slide.ts",
            config=_config(),
            bulletin=_bulletin("cgb-1"),
            branding=_BRANDING,
            duration_seconds=10,
        )

        joined = " ".join(args)
        assert "color=c=0x2458A6:size=640x360" in joined
        assert "Spring plant sale" in joined
        assert "Pinegrove Garden Club" in joined
        assert "PUB12" in joined
        assert args[-3:] == ["-f", "mpegts", str(tmp_path / "slide.ts")]

    def test_args_without_branding_fall_back_to_default_background(self, tmp_path: Path) -> None:
        args = build_bulletin_slide_args(
            output_path=tmp_path / "slide.ts",
            config=_config(),
            bulletin=_bulletin("cgb-1"),
            branding=None,
            duration_seconds=10,
        )
        assert "color=c=0x1a2744" in " ".join(args)


class TestBulletinFiller:
    def test_renders_one_slide_per_approved_bulletin_in_order(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [
                _bulletin("cgb-1", title="Plant sale"),
                _bulletin("cgb-2", title="Food drive"),
            ],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=_ok_runner(calls),
        )

        plan = generator(_config())

        assert plan.channel_id == "public"
        # The rotation repeats to span the fill target (CA-8); each cycle
        # preserves the approved order and each slide renders exactly once.
        assert [segment.label for segment in plan.segments[:2]] == ["Plant sale", "Food drive"]
        assert len(plan.segments) % 2 == 0
        assert all(segment.kind == "cg" for segment in plan.segments)
        assert [segment.source_ref for segment in plan.segments[:2]] == [
            "bulletin-cgb-1",
            "bulletin-cgb-2",
        ]
        assert len(calls) == 2

    def test_unchanged_board_is_cached_changed_board_rerenders(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        bulletins = [_bulletin("cgb-1")]
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: bulletins,
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=_ok_runner(calls),
        )

        generator(_config())
        generator(_config())
        assert len(calls) == 1, "an unchanged board must not re-render"

        bulletins.append(_bulletin("cgb-2", title="Food drive"))
        generator(_config())
        assert len(calls) == 2, "a changed board renders only its NEW slides (per-slide cache)"

    def test_no_approved_bulletins_delegates_to_slate(self, tmp_path: Path) -> None:
        slate_calls: list[list[str]] = []
        slate = SlateSourceGenerator(work_dir=tmp_path, ffmpeg_runner=_ok_runner(slate_calls))
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=_ok_runner([]),
            slate_generator=slate,
        )

        plan = generator(_config())

        assert plan.segments[0].kind == "slate"
        assert len(slate_calls) == 1

    def test_drawtext_failure_retries_then_raises(self, tmp_path: Path) -> None:
        attempts: list[list[str]] = []

        def failing_runner(args: list[str]) -> FfmpegResult:
            attempts.append(args)
            return FfmpegResult(returncode=1, stdout="", stderr="boom")

        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1")],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=failing_runner,
        )

        with pytest.raises(SourcePrepareError, match="bulletin"):
            generator(_config())
        assert len(attempts) == 2, "expected a no-text retry before failing"

    def test_ffmpeg_not_found_fails_open_as_source_prepare_error(self, tmp_path: Path) -> None:
        # Pins the gate's Blocker fix (QA-1): run_ffmpeg raises
        # FfmpegNotFoundError/FfmpegError BEFORE returning a result when the
        # binary is missing -- that must never escape the filler uncaught (it
        # used to crash the egress service). It must translate to
        # SourcePrepareError so the daemon's existing fallback-to-slate
        # contract can handle it, with the original exception chained.
        attempts: list[list[str]] = []

        def not_found_runner(args: list[str]) -> FfmpegResult:
            attempts.append(args)
            raise FfmpegNotFoundError("ffmpeg is not on PATH")

        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1")],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=not_found_runner,
        )

        with pytest.raises(SourcePrepareError) as exc_info:
            generator(_config())

        assert not isinstance(exc_info.value, FfmpegNotFoundError)
        assert isinstance(exc_info.value.__cause__, FfmpegNotFoundError)
        assert len(attempts) == 1, "a missing ffmpeg binary must not be retried"

    def test_text_render_failure_retry_logs_warning_naming_channel(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        attempts: list[list[str]] = []

        def flaky_runner(args: list[str]) -> FfmpegResult:
            attempts.append(args)
            if len(attempts) == 1:
                return FfmpegResult(returncode=1, stdout="", stderr="boom: missing font")
            Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(args[-1]).write_bytes(b"ts")
            return FfmpegResult(returncode=0, stdout="", stderr="")

        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1")],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=flaky_runner,
        )

        with caplog.at_level(logging.WARNING, logger="civiccast.egress.bulletin_filler"):
            generator(_config())

        assert len(attempts) == 2, "expected a no-text retry after the first failure"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("public" in r.getMessage() for r in warnings), (
            "the text-degradation warning must name the channel"
        )


_NOW = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def _windowed(
    submission_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    state: str = "scheduled",
) -> CgBulletinSubmission:
    return CgBulletinSubmission(
        submission_id=submission_id,
        organization="Org",
        submitter_label="Volunteer",
        title=f"Notice {submission_id}",
        message="Body of the community notice goes here for the slide.",
        target_zone_kind="ticker",
        state=state,  # type: ignore[arg-type]
        requested_start=start,
        requested_end=end,
        approved_by_operator="op",
    )


class TestBulletinTimeWindow:
    def test_only_airable_bulletins_render(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []
        bulletins = [
            _windowed("live", start=_NOW - timedelta(hours=1), end=_NOW + timedelta(hours=1)),
            _windowed("future", start=_NOW + timedelta(days=1)),
            _windowed("expired", end=_NOW - timedelta(hours=1)),
            _windowed("open", state="accepted"),  # no window -> always airable
        ]
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: bulletins,
            ffmpeg_runner=_ok_runner(calls),
            clock=lambda: _NOW,
        )
        plan = generator(_config())
        assert {s.source_ref for s in plan.segments} == {"bulletin-live", "bulletin-open"}
        assert len(calls) == 2  # future + expired never render

    def test_all_expired_falls_back_to_slate(self, tmp_path: Path) -> None:
        slate_calls: list[list[str]] = []
        slate = SlateSourceGenerator(work_dir=tmp_path, ffmpeg_runner=_ok_runner(slate_calls))
        generator = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_windowed("expired", end=_NOW - timedelta(hours=1))],
            ffmpeg_runner=_ok_runner([]),
            slate_generator=slate,
            clock=lambda: _NOW,
        )
        plan = generator(_config())
        assert plan.segments[0].kind == "slate"
        assert len(slate_calls) == 1


class TestFillerSourceProvider:
    def test_policy_branches_between_bulletins_and_slate(self, tmp_path: Path) -> None:
        slate = SlateSourceGenerator(work_dir=tmp_path, ffmpeg_runner=_ok_runner([]))
        bulletins = BulletinFillerSourceGenerator(
            work_dir=tmp_path,
            bulletins_provider=lambda _cid: [_bulletin("cgb-1")],
            branding_provider=lambda _cid: _BRANDING,
            ffmpeg_runner=_ok_runner([]),
            slate_generator=slate,
        )
        provider = FillerSourceProvider(bulletin_generator=bulletins, slate_generator=slate)

        bulletin_plan = provider(_config(fill_policy="bulletins"))
        slate_plan = provider(_config(fill_policy="slate"))

        assert bulletin_plan.segments[0].kind == "cg"
        assert slate_plan.segments[0].kind == "slate"


def test_bulletin_plan_cycles_slides_to_span_the_fill_target(tmp_path: Path) -> None:
    # CA-8 finding: one ~30s bulletin cycle per plan reset the TS session
    # every cycle. The rotation now repeats to span the fill target with
    # each slide still rendered exactly once.
    rendered: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        rendered.append(args)
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"ts")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    generator = BulletinFillerSourceGenerator(
        work_dir=tmp_path,
        bulletins_provider=lambda _cid: [
            _bulletin("cgb_1", title="Food drive Saturday"),
            _bulletin("cgb_2", title="Library book sale"),
        ],
        ffmpeg_runner=runner,
        target_fill_seconds=600,
    )

    plan = generator(_config())

    assert len(rendered) == 2  # each slide rendered once
    # 2 slides x 10s = 20s cycle; 600s target -> 30 cycles -> 60 segments.
    assert len(plan.segments) == 60
    total = sum(segment.duration_seconds for segment in plan.segments)
    assert total >= 600
    # Rotation order is preserved within every cycle.
    assert [s.source_ref for s in plan.segments[:4]] == [
        "bulletin-cgb_1",
        "bulletin-cgb_2",
        "bulletin-cgb_1",
        "bulletin-cgb_2",
    ]


class TestDefaultImageResolver:
    """Gate finding F-4: ``_default_image_resolver`` must not resolve a staff
    asset's ``file_path`` to a filesystem path outside CivicCast's configured
    upload root. Defense-in-depth -- ``file_path`` is a staff-set DB column,
    not community-controlled, so this isn't exploitable today, but the
    resolver should fail closed (render without the image, same as an
    unresolvable ref) and log rather than silently serve an out-of-root path.
    """

    def _resolver_for(self, monkeypatch: pytest.MonkeyPatch, file_path: str | None):  # type: ignore[no-untyped-def]
        import civiccast.egress.bulletin_filler as bf

        class _FakeRow:
            def __init__(self, path: str | None) -> None:
                self.file_path = path

        class _FakeStore:
            def __init__(self, _session_factory: object) -> None:
                pass

            def get_staff_row(self, _ref: str) -> _FakeRow | None:
                return _FakeRow(file_path) if file_path is not None else None

        monkeypatch.setattr(bf, "PostgresAssetStore", _FakeStore)
        return bf._default_image_resolver(lambda: None)

    def test_path_inside_upload_root_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        upload_root = tmp_path / "uploads"
        upload_root.mkdir()
        image = upload_root / "logo.png"
        image.write_bytes(b"png")
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(upload_root))

        resolve = self._resolver_for(monkeypatch, str(image))

        assert resolve("asset-1") == image.resolve()

    def test_path_outside_upload_root_is_refused_and_logged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        upload_root = tmp_path / "uploads"
        upload_root.mkdir()
        outside = tmp_path / "outside" / "secret.png"
        outside.parent.mkdir()
        outside.write_bytes(b"png")
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(upload_root))

        resolve = self._resolver_for(monkeypatch, str(outside))

        with caplog.at_level(logging.WARNING, logger="civiccast.egress.bulletin_filler"):
            result = resolve("asset-2")

        assert result is None
        assert any(
            "outside the configured CivicCast upload root" in record.message
            for record in caplog.records
        )

    def test_unconfigured_upload_root_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
        image = tmp_path / "logo.png"
        image.write_bytes(b"png")

        resolve = self._resolver_for(monkeypatch, str(image))

        assert resolve("asset-3") is None

    def test_missing_row_or_no_file_path_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))

        resolve = self._resolver_for(monkeypatch, None)

        assert resolve("missing-asset") is None
