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
from civiccast.egress.models import (
    MAX_PLAYLIST_SUBCHAINS,
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
)
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
        # The approved order is preserved inside the ONE rotation file (see
        # the concat-list assertion below); the egress plan itself just
        # repeats that one file up to the playlist-subchain cap.
        assert len(plan.segments) <= MAX_PLAYLIST_SUBCHAINS
        assert all(segment.kind == "cg" for segment in plan.segments)
        assert all(segment.source_ref == "bulletin-rotation" for segment in plan.segments)
        assert len({segment.path for segment in plan.segments}) == 1
        # 2 individual slide renders + 1 concat render of the rotation.
        assert len(calls) == 3
        concat_args = calls[2]
        concat_list_path = Path(concat_args[concat_args.index("-i") + 1])
        concat_text = concat_list_path.read_text(encoding="utf-8")
        assert concat_text.index(calls[0][-1]) < concat_text.index(calls[1][-1])

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
        assert len(calls) == 2  # 1 slide render + 1 rotation concat
        generator(_config())
        assert len(calls) == 2, "an unchanged rotation must not re-render OR re-concat"

        bulletins.append(_bulletin("cgb-2", title="Food drive"))
        generator(_config())
        # The new slide renders once (per-slide cache); the rotation's
        # content changed (a different slide set), so it re-concats too.
        assert len(calls) == 4, "a changed rotation renders its NEW slide and re-concats"

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

        # attempt1: text render fails; attempt2: no-text retry succeeds;
        # attempt3: the rotation concat (a single bulletin's rotation is
        # just that one slide, but it still goes through the concat step).
        assert len(attempts) == 3, "expected a no-text retry after the first failure"
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
        assert {s.source_ref for s in plan.segments} == {"bulletin-rotation"}
        # 2 airable slides rendered + 1 rotation concat; future + expired
        # never render at all.
        assert len(calls) == 3

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


def test_bulletin_plan_builds_one_rotation_file_and_repeats_it_up_to_the_cap(
    tmp_path: Path,
) -> None:
    # CA-8 finding: one ~30s bulletin cycle per plan reset the TS session
    # every cycle.
    #
    # Hostile-review redo (2026-09-05, regression from #174, then a
    # follow-up review of the first fix): a 2-slide, 10s-each rotation
    # cycled to reach 600s used to build 30 cycles = 60 total segments --
    # gst/bridge.graph_from_config truncates a "cg"-kind plan past
    # MAX_PLAYLIST_SUBCHAINS (12) segments, so the board/bulletin worker
    # actually hit a real EOS (and restarted) after only ~120s of a 600s
    # target. A first fix lengthened each slide's OWN hold duration instead
    # of cycling -- but that changes what airs (a 10s slide became a 50s
    # slide). The shipped fix instead concatenates the individual slides
    # into ONE rotation file (each slide still exactly its configured 10s)
    # and repeats THAT ONE file up to MAX_PLAYLIST_SUBCHAINS times -- 2
    # slides x 10s = a 20s rotation, capped at 12 repeats = 240s of
    # coverage (short of the 600s target; the rollover mechanism -- the
    # same one that extends a schedule-derived program plan -- covers the
    # rest for as long as the channel stays on this fill).
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

    # 2 individual slide renders + 1 concat render of the rotation file.
    assert len(rendered) == 3
    assert len(plan.segments) == 12
    assert len(plan.segments) <= MAX_PLAYLIST_SUBCHAINS
    # Each slide keeps its configured ~10s hold; the rotation (all repeats
    # of the SAME concatenated file) is 20s -- nothing was stretched.
    assert all(segment.duration_seconds == 20 for segment in plan.segments)
    assert len({segment.path for segment in plan.segments}) == 1  # one file, repeated
    assert all(segment.source_ref == "bulletin-rotation" for segment in plan.segments)
    total = sum(segment.duration_seconds for segment in plan.segments)
    assert total == 240  # short of the 600s target -- rollover covers the rest

    # The concat list (the third ffmpeg call) preserves rotation order.
    slide_paths = [rendered[0][-1], rendered[1][-1]]
    concat_args = rendered[2]
    concat_list_path = Path(concat_args[concat_args.index("-i") + 1])
    concat_text = concat_list_path.read_text(encoding="utf-8")
    assert concat_text.index(slide_paths[0]) < concat_text.index(slide_paths[1])


def test_bulletin_rotation_is_cached_and_not_rebuilt_on_a_second_prepare(
    tmp_path: Path,
) -> None:
    """A second prepare with the same rotation must not re-concatenate --
    only the individual per-slide cache mattered before this fix; the
    rotation file itself needs the same posture."""
    rendered: list[list[str]] = []
    generator = BulletinFillerSourceGenerator(
        work_dir=tmp_path,
        bulletins_provider=lambda _cid: [_bulletin("cgb_1", title="Food drive Saturday")],
        ffmpeg_runner=_ok_runner(rendered),
        target_fill_seconds=60,
    )

    first = generator(_config())
    calls_after_first = len(rendered)
    second = generator(_config())

    assert len(rendered) == calls_after_first  # no new ffmpeg calls at all
    assert first.segments[0].path == second.segments[0].path


@pytest.mark.parametrize("bulletin_count", [13, 40])
def test_bulletin_rotation_caps_distinct_slides_at_the_playlist_subchain_limit(
    tmp_path: Path, bulletin_count: int
) -> None:
    """Hostile-review "invariant" fix: the first pass's cap check
    (``cycles * segment_count > MAX_PLAYLIST_SUBCHAINS``) never actually
    bounded ``segment_count`` itself -- a rotation with MORE distinct slides
    than the cap (13, 40, ...) still built that many segments regardless.
    The rotation must never exceed MAX_PLAYLIST_SUBCHAINS distinct slides,
    however many are airable."""
    bulletins = [_bulletin(f"cgb_{i}", title=f"Bulletin {i}") for i in range(bulletin_count)]
    generator = BulletinFillerSourceGenerator(
        work_dir=tmp_path,
        bulletins_provider=lambda _cid: bulletins,
        ffmpeg_runner=_ok_runner([]),
        target_fill_seconds=60,
    )

    plan = generator(_config())

    assert len(plan.segments) <= MAX_PLAYLIST_SUBCHAINS
    assert len({segment.path for segment in plan.segments}) == 1
    # The rotation itself holds at most the capped number of slides (10s
    # each) -- never bulletin_count's full, uncapped length.
    assert plan.segments[0].duration_seconds <= MAX_PLAYLIST_SUBCHAINS * 10


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
