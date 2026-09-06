# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for egress source preparation."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

import pytest

import civiccast.egress.preparer as preparer_module
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparer, build_conform_source_args
from civiccast.stream._ffmpeg import FfmpegResult
from civiccast.stream.loudness import LoudnessGateResult


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        loudness_tolerance_lufs=1.0,
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=12.5,
                inpoint_seconds=2,
                outpoint_seconds=14.5,
            )
        ],
    )


def _loudness(status: str = "ok", measured_lufs: float | None = -24.1) -> LoudnessGateResult:
    return LoudnessGateResult(
        status=status,
        standard="ITU-R BS.1770 / EBU R128",
        target_lufs=-24.0,
        used_ffmpeg_wrapper=True,
        measured_lufs=measured_lufs,
        operator_action="test action",
    )


def test_build_conform_source_args_uses_canonical_profile_and_trim(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "prepared.ts"
    segment = EgressSourceSegment(
        label="Council meeting",
        path=str(source),
        duration_seconds=10,
        inpoint_seconds=5,
        outpoint_seconds=15,
    )

    args = build_conform_source_args(
        source_path=source,
        output_path=output,
        segment=segment,
        profile=_config().canonical_profile,
    )

    assert args[:7] == ["-hide_banner", "-loglevel", "warning", "-ss", "5", "-i", str(source)]
    assert args[7:9] == ["-t", "10"]
    assert "scale=640:360" in " ".join(args)
    assert "1200k" in args
    assert "-af" not in args
    assert args[-3:] == ["-f", "mpegts", str(output)]


def _write_fake_output(args: list[str]) -> None:
    """H5 fix: prepared-segment writes are now atomic (tmp + rename), so a fake
    ffmpeg runner must actually create the file ``args[-1]`` names (its
    ``.tmp`` sibling of the final prepared path) for the rename to succeed --
    mirrors what a real ffmpeg process does."""
    Path(args[-1]).write_text("prepared", encoding="utf-8")


def test_source_preparer_conforms_inside_loudness_tolerance(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=lambda args: (
            (captured.setdefault("args", args) and _write_fake_output(args))
            or FfmpegResult(returncode=0, stdout="", stderr="")
        ),
        loudness_checker=lambda **kwargs: captured.setdefault("loudness", kwargs) and _loudness(),
        warm_scheduler=lambda job: None,  # keep the at-air behavior deterministic
    )

    report = preparer.prepare(_source_plan(tmp_path), _config())

    assert report.source_plan.channel_id == "gov"
    prepared = report.source_plan.segments[0]
    # H5 fix: every prepare() call now writes into its own uniquely-named
    # subdirectory under <channel>/prepared/ (a 12-hex-char uuid segment)
    # instead of a fixed, collision-prone path -- match that shape rather
    # than a single hardcoded path.
    assert re.search(r"gov[\\/]prepared[\\/][0-9a-f]{12}[\\/]segment-0001\.ts$", prepared.path), (
        prepared.path
    )
    assert prepared.inpoint_seconds is None
    assert prepared.outpoint_seconds is None
    assert report.records[0].normalized is False
    assert "-af" not in captured["args"]
    assert captured["loudness"]["target_lufs"] == -24.0


def test_source_preparer_passes_live_segments_through_without_local_file_check(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=lambda args: captured.setdefault("args", args),  # type: ignore[return-value]
        loudness_checker=lambda **kwargs: captured.setdefault("loudness", kwargs),  # type: ignore[return-value]
    )
    source_plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Live: Council chamber",
                path="srt://127.0.0.1:19002",
                duration_seconds=60,
                kind="live",
                source_ref="gov:relay",
            )
        ],
    )

    report = preparer.prepare(source_plan, _config())

    assert report.source_plan.segments == source_plan.segments
    assert report.records[0].loudness_status == "not_checked_live_passthrough"
    assert report.records[0].prepared_path == "srt://127.0.0.1:19002"
    assert captured == {}


def test_source_preparer_normalizes_when_loudness_is_out_of_tolerance(tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=lambda args: (
            (captured.setdefault("args", args) and _write_fake_output(args))
            or FfmpegResult(returncode=0, stdout="", stderr="")
        ),
        loudness_checker=lambda **_kwargs: _loudness(status="failed", measured_lufs=-18.0),
        warm_scheduler=lambda job: None,  # keep the at-air behavior deterministic
    )

    report = preparer.prepare(_source_plan(tmp_path), _config())

    assert report.records[0].normalized is True
    assert "-af" in captured["args"]
    assert "loudnorm=I=-24" in " ".join(captured["args"])


def test_source_preparer_fails_when_loudness_cannot_be_measured(tmp_path: Path) -> None:
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        loudness_checker=lambda **_kwargs: _loudness(status="failed", measured_lufs=None),
    )

    with pytest.raises(SourcePrepareError, match="could not be measured"):
        preparer.prepare(_source_plan(tmp_path), _config())


def test_source_preparer_fails_when_conform_ffmpeg_fails(tmp_path: Path) -> None:
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=lambda _args: FfmpegResult(returncode=1, stdout="", stderr="boom"),
        loudness_checker=lambda **_kwargs: _loudness(),
    )

    with pytest.raises(SourcePrepareError, match="could not be conformed"):
        preparer.prepare(_source_plan(tmp_path), _config())


def test_source_preparer_rejects_missing_source(tmp_path: Path) -> None:
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Missing",
                path=str(tmp_path / "missing.mp4"),
                duration_seconds=10,
            )
        ],
    )

    with pytest.raises(SourcePrepareError, match="missing before preparation"):
        preparer.prepare(plan, _config())


def test_same_path_with_different_trims_prepares_separately(tmp_path: Path) -> None:
    """Audit TEST-005: the memo key is (path, inpoint, outpoint); collapsing
    it to path alone would air the FIRST trim for every slot - exactly what
    join-in-progress plans (same asset, different offsets) would produce."""

    source = tmp_path / "council.ts"
    source.write_text("fake media", encoding="utf-8")

    def segment(inpoint: float, outpoint: float) -> EgressSourceSegment:
        return EgressSourceSegment(
            label=f"Council {inpoint:g}",
            path=str(source),
            duration_seconds=outpoint - inpoint,
            inpoint_seconds=inpoint,
            outpoint_seconds=outpoint,
        )

    plan = EgressSourcePlan(channel_id="gov", segments=[segment(0, 10), segment(10, 20)])
    ffmpeg_calls: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        ffmpeg_calls.append(args)
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path,
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,  # at-air conforms only; warms tested separately
    )

    report = preparer.prepare(plan, _config())

    assert len(ffmpeg_calls) == 2  # two distinct conforms
    assert len({seg.path for seg in report.source_plan.segments}) == 2


def test_reloading_a_plan_never_touches_the_previous_plans_prepared_files(
    tmp_path: Path,
) -> None:
    """H5 (measured on tester hardware): for the GStreamer engine
    (``playout_trim_supported=False``, the default), a content-reload's
    ``prepare()`` call used to write its trimmed-miss conform output to the SAME
    fixed path (``<channel>/prepared/segment-0001.ts``, keyed only by segment
    index within its own call) that the FIRST prepare() call had already written
    -- while the worker airing the first plan's segment could still be reading
    that exact file. Every ``prepare()`` call now gets its own uniquely-named
    subdirectory, so a second call for a DIFFERENT plan (even one whose segment
    lands at the same index, 1, as the first) can never share an output path
    with -- let alone overwrite -- the first call's still-possibly-live file."""

    def _segment(path: Path, label: str) -> EgressSourceSegment:
        path.write_text("fake media", encoding="utf-8")
        return EgressSourceSegment(
            label=label,
            path=str(path),
            duration_seconds=10,
            inpoint_seconds=1,  # forces the trimmed-miss (non-cached) write path
            outpoint_seconds=11,
        )

    def runner(args: list[str]) -> FfmpegResult:
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path,
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )

    plan_a = EgressSourcePlan(
        channel_id="gov", segments=[_segment(tmp_path / "a.ts", "Plan A segment 1")]
    )
    report_a = preparer.prepare(plan_a, _config())
    prepared_a = Path(report_a.source_plan.segments[0].path)
    assert prepared_a.is_file()
    bytes_before = prepared_a.read_bytes()
    mtime_before = prepared_a.stat().st_mtime_ns

    # A second, DIFFERENT plan -- e.g. a content-reload's newly-due program --
    # for the SAME channel. Its one segment also lands at index 1.
    plan_b = EgressSourcePlan(
        channel_id="gov", segments=[_segment(tmp_path / "b.ts", "Plan B segment 1")]
    )
    report_b = preparer.prepare(plan_b, _config())
    prepared_b = Path(report_b.source_plan.segments[0].path)

    assert prepared_b != prepared_a  # never the same path
    assert prepared_b.parent != prepared_a.parent  # never even the same plan directory
    # Plan A's already-prepared file is completely untouched by preparing plan B.
    assert prepared_a.is_file()
    assert prepared_a.read_bytes() == bytes_before
    assert prepared_a.stat().st_mtime_ns == mtime_before


def test_trimmed_miss_conform_write_is_atomic(tmp_path: Path) -> None:
    """H5 (atomic write): a failed conform must leave no ``.tmp`` sibling behind
    at the prepared segment's final path, and a successful one must leave ONLY
    the final path (never the ``.tmp`` alongside it)."""
    source = tmp_path / "council.ts"
    source.write_text("fake media", encoding="utf-8")
    segment = EgressSourceSegment(
        label="Council meeting",
        path=str(source),
        duration_seconds=10,
        inpoint_seconds=1,
        outpoint_seconds=11,
    )
    plan = EgressSourcePlan(channel_id="gov", segments=[segment])

    # Failure case: the runner never creates the .tmp output file at all (the
    # real ffmpeg failure mode this simulates), and returns nonzero.
    failing_preparer = SourcePreparer(
        work_dir=tmp_path / "fail-work",
        ffmpeg_runner=lambda _args: FfmpegResult(returncode=1, stdout="", stderr="boom"),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    with pytest.raises(SourcePrepareError, match="could not be conformed"):
        failing_preparer.prepare(plan, _config())
    fail_prepared_root = tmp_path / "fail-work" / "gov" / "prepared"
    leftover_files = (
        [p for p in fail_prepared_root.rglob("*") if p.is_file()]
        if fail_prepared_root.exists()
        else []
    )
    assert leftover_files == []  # no partial/.tmp file survives a failed conform

    # Success case: only the final path exists afterward, never a lingering .tmp.
    def runner(args: list[str]) -> FfmpegResult:
        assert args[-1].endswith(".ts.tmp")  # the atomic-write staging name
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    ok_preparer = SourcePreparer(
        work_dir=tmp_path / "ok-work",
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    report = ok_preparer.prepare(plan, _config())
    prepared_path = Path(report.source_plan.segments[0].path)
    plan_dir = prepared_path.parent
    assert sorted(p.name for p in plan_dir.iterdir()) == [prepared_path.name]


def test_stale_prepared_plan_directories_are_garbage_collected(tmp_path: Path) -> None:
    """H5 (GC backstop): a per-plan directory older than the generous age floor
    is reclaimed on the NEXT ``prepare()`` call for that channel; one younger
    than the floor is left alone (it might still be airing)."""
    source = tmp_path / "council.ts"
    source.write_text("fake media", encoding="utf-8")
    segment = EgressSourceSegment(
        label="Council meeting",
        path=str(source),
        duration_seconds=10,
        inpoint_seconds=1,
        outpoint_seconds=11,
    )
    plan = EgressSourcePlan(channel_id="gov", segments=[segment])

    def runner(args: list[str]) -> FfmpegResult:
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )

    # F3 fix: keep-N-most-recent (N=3) protects a directory from GC purely by
    # recency, however old it is -- so proving the AGE FLOOR actually fires
    # requires enough other directories to push the stale one out of that
    # protection first. One dir older than the floor, plus enough OTHER dirs
    # (all younger) to exceed keep-N, plus a fresh one this very prepare()
    # call creates.
    prepared_root = tmp_path / "work" / "gov" / "prepared"
    stale_dir = prepared_root / ("0" * 12)
    stale_dir.mkdir(parents=True)
    (stale_dir / "segment-0001.ts").write_text("old", encoding="utf-8")
    old_time = time.time() - (25 * 3600)  # older than the 24h floor
    os.utime(stale_dir, (old_time, old_time))

    for i in range(preparer_module._PREPARED_PLAN_DIR_KEEP_N):
        other_dir = prepared_root / f"other{i:03d}"
        other_dir.mkdir(parents=True)
        (other_dir / "segment-0001.ts").write_text("other", encoding="utf-8")

    fresh_dir = prepared_root / ("1" * 12)
    fresh_dir.mkdir(parents=True)
    (fresh_dir / "segment-0001.ts").write_text("fresh", encoding="utf-8")
    # left at the current mtime -- younger than the floor, must survive

    preparer.prepare(plan, _config())

    remaining = {p.name for p in prepared_root.iterdir() if p.is_dir()}
    assert stale_dir.name not in remaining  # reclaimed: older than the floor,
    # and pushed out of keep-N-most-recent by the other directories above
    assert fresh_dir.name in remaining  # untouched: younger than the floor


def test_a_plan_dir_still_referenced_by_a_live_worker_is_never_deleted(
    tmp_path: Path,
) -> None:
    """F4: a per-plan directory the CALLER (the daemon, tracking which plan a
    live worker is currently reading) explicitly marks as still in use is
    NEVER removed by GC -- however old it is, however large (the byte budget
    alone would otherwise evict it), and however far outside the
    keep-N-most-recent protection it falls."""
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    prepared_root = tmp_path / "work" / "gov" / "prepared"

    live_dir = prepared_root / "aaaaaaaaaaaa"
    live_dir.mkdir(parents=True)
    # large enough that the byte budget alone would otherwise evict it first
    (live_dir / "segment-0001.ts").write_bytes(b"x" * 1024)
    ancient_time = time.time() - (48 * 3600)  # older than the 24h floor
    os.utime(live_dir, (ancient_time, ancient_time))

    # enough OTHER (newer) directories to push live_dir out of keep-N's
    # recency protection too -- ``keep`` must be the thing saving it, not an
    # accident of recency.
    for i in range(preparer_module._PREPARED_PLAN_DIR_KEEP_N + 2):
        other_dir = prepared_root / f"other{i:03d}"
        other_dir.mkdir(parents=True)
        (other_dir / "segment-0001.ts").write_text("other", encoding="utf-8")

    preparer._gc_prepared_plan_dirs(prepared_root, keep=frozenset({live_dir}))

    assert live_dir.exists()
    assert (live_dir / "segment-0001.ts").exists()


def test_release_reclaims_one_specific_plan_dir_immediately(tmp_path: Path) -> None:
    """F3: the daemon calls release() for a plan it independently knows has
    settled (the OLD plan of a just-committed content-reload) -- reclaimed
    immediately, no GC pass needed."""
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    plan_dir = tmp_path / "work" / "gov" / "prepared" / "abc123"
    plan_dir.mkdir(parents=True)
    (plan_dir / "segment-0001.ts").write_text("retired", encoding="utf-8")

    preparer.release(plan_dir)

    assert not plan_dir.exists()


def test_release_of_none_is_a_no_op(tmp_path: Path) -> None:
    """A plan whose prepare() never created a discrete directory (F7: a
    live-only plan, or every segment a playout_trim_supported cache hit)
    reports plan_dir=None -- release(None) must not raise."""
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    preparer.release(None)  # must not raise


def test_flat_pre_upgrade_prepared_files_are_swept(tmp_path: Path) -> None:
    """F6: a pre-upgrade flat ``prepared/segment-NNNN.ts`` (the fixed-path
    layout H5 replaced) sitting directly under the channel's prepared/ root
    is removed by GC -- nothing written after this fix ever reads from there
    again."""
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    prepared_root = tmp_path / "work" / "gov" / "prepared"
    prepared_root.mkdir(parents=True)
    flat_file = prepared_root / "segment-0001.ts"
    flat_file.write_text("pre-upgrade leftover", encoding="utf-8")
    flat_tmp = prepared_root / "segment-0002.ts.tmp"
    flat_tmp.write_text("pre-upgrade partial", encoding="utf-8")

    preparer._gc_prepared_plan_dirs(prepared_root)

    assert not flat_file.exists()
    assert not flat_tmp.exists()


def test_a_plan_with_no_local_writes_leaves_no_directory(tmp_path: Path) -> None:
    """F7: a plan whose every segment is live (no local ffmpeg write ever
    happens) must not leave an empty per-plan directory under prepared/, and
    the report's plan_dir is None (nothing to release or track)."""
    preparer = SourcePreparer(work_dir=tmp_path / "work")
    plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Live feed",
                path="srt://127.0.0.1:19002",
                duration_seconds=60,
                kind="live",
                source_ref="gov:relay",
            )
        ],
    )

    report = preparer.prepare(plan, _config())

    assert report.plan_dir is None
    prepared_root = tmp_path / "work" / "gov" / "prepared"
    assert not prepared_root.exists() or list(prepared_root.iterdir()) == []


def test_a_plan_with_local_writes_reports_its_plan_dir(tmp_path: Path) -> None:
    """F7 counterpart: a plan that DOES write locally reports the real
    plan_dir, and the directory actually holds the written segment."""

    def runner(args: list[str]) -> FfmpegResult:
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )

    report = preparer.prepare(_source_plan(tmp_path), _config())

    assert report.plan_dir is not None
    assert report.plan_dir.is_dir()
    assert list(report.plan_dir.iterdir())


def test_repeated_identical_segments_prepare_once(tmp_path: Path) -> None:
    """CA-8: filler plans repeat one rendered segment hundreds of times to
    span the fill target; preparing (loudness probe + conform) per ENTRY
    multiplied channel startup ~120x. Identical (path, trim) segments must
    prepare exactly once and share the prepared output."""

    source = tmp_path / "slate.ts"
    source.write_text("fake media", encoding="utf-8")
    segment = EgressSourceSegment(
        label="CivicCast slate",
        path=str(source),
        duration_seconds=30,
        kind="slate",
        source_ref="civiccast-slate",
    )
    plan = EgressSourcePlan(channel_id="gov", segments=[segment] * 5)

    loudness_calls: list[dict] = []
    ffmpeg_calls: list[list[str]] = []

    def runner(args: list[str]) -> FfmpegResult:
        ffmpeg_calls.append(args)
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path,
        ffmpeg_runner=runner,
        loudness_checker=lambda **kwargs: loudness_calls.append(kwargs) or _loudness(),
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )

    report = preparer.prepare(plan, _config())

    assert len(loudness_calls) == 1
    assert len(ffmpeg_calls) == 1
    assert len(report.source_plan.segments) == 5
    assert len({seg.path for seg in report.source_plan.segments}) == 1


# ---------------------------------------------------------------------------
# #156 — persistent conform cache (long-asset TRANSITIONING stall)
# ---------------------------------------------------------------------------


def _untrimmed_plan(tmp_path: Path, label: str = "Council meeting") -> EgressSourcePlan:
    source = tmp_path / "long-recording.mp4"
    if not source.exists():
        source.write_text("fake long media", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[EgressSourceSegment(label=label, path=str(source), duration_seconds=3600.0)],
    )


def _counting_runner(calls: list[list[str]]):
    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return runner


def test_aired_before_asset_prepares_with_zero_ffmpeg_work(tmp_path: Path) -> None:
    """#156 acceptance 1: a program whose asset has aired before starts within
    seconds — the SECOND airing (fresh preparer instance, like a fresh hourly
    plan) must run zero conforms and zero loudness probes."""

    calls_1: list[list[str]] = []
    probes: list[dict] = []
    SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls_1),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    ).prepare(_untrimmed_plan(tmp_path), _config())
    assert len(calls_1) == 1  # first airing conforms once (into the cache)

    calls_2: list[list[str]] = []
    report = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls_2),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    ).prepare(_untrimmed_plan(tmp_path), _config())

    assert calls_2 == []  # zero ffmpeg work on the second airing
    assert len(probes) == 1  # loudness probed once, cached thereafter
    assert "conform-cache" in report.source_plan.segments[0].path


def test_join_in_progress_hits_cache_with_playout_trim(tmp_path: Path) -> None:
    """#156 acceptance 3: join-in-progress offsets survive — a cached full
    conform is aired with the segment's own inpoint applied at playout, so two
    different join offsets share one cache object with different trims."""

    warm_jobs: list = []
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")

    def plan(inpoint: float) -> EgressSourcePlan:
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="Council joined late",
                    path=str(source),
                    duration_seconds=1800.0,
                    inpoint_seconds=inpoint,
                    outpoint_seconds=inpoint + 1800.0,
                )
            ],
        )

    # First-ever airing: trimmed conform straight to air + a warm scheduled.
    preparer.prepare(plan(120.0), _config())
    assert len(calls) == 1
    assert "-ss" in calls[0]  # air path still trims at the source (old latency)
    assert len(warm_jobs) == 1
    warm_jobs[0]()  # the background warm completes

    # Next hourly airing at a DIFFERENT join offset: cache hit, trim at playout.
    calls.clear()
    report = preparer.prepare(plan(300.0), _config())
    assert calls == []  # zero conforms
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path
    assert seg.inpoint_seconds == 300.0
    assert seg.outpoint_seconds == 300.0 + 1800.0


def test_full_asset_warm_conform_has_no_trim_and_is_single_threaded(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )
    preparer.prepare(_source_plan(tmp_path), _config())  # trimmed miss
    warm_jobs[0]()

    warm_args = calls[-1]
    assert "-ss" not in warm_args  # the cache unit is the FULL asset
    assert "-t" not in warm_args
    assert warm_args[warm_args.index("-threads") : warm_args.index("-threads") + 2] == [
        "-threads",
        "1",
    ]


def test_duplicate_warms_are_deduped(tmp_path: Path) -> None:
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )
    source = tmp_path / "raw-source.mp4"

    def plan(inpoint: float) -> EgressSourcePlan:
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="x",
                    path=str(source),
                    duration_seconds=10.0,
                    inpoint_seconds=inpoint,
                    outpoint_seconds=inpoint + 10.0,
                )
            ],
        )

    source.write_text("fake media", encoding="utf-8")
    preparer.prepare(plan(1.0), _config())
    preparer.prepare(plan(2.0), _config())  # same asset, warm already pending

    assert len(warm_jobs) == 1


def test_corrupt_cache_sidecar_is_treated_as_miss(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )
    preparer.prepare(_untrimmed_plan(tmp_path), _config())
    # Corrupt the sidecar: the entry must not be trusted.
    for sidecar in (tmp_path / "work" / "conform-cache").glob("*.json"):
        sidecar.write_text("{not json", encoding="utf-8")

    calls.clear()
    preparer.prepare(_untrimmed_plan(tmp_path), _config())
    assert len(calls) == 1  # re-conformed, not served from the corrupt entry


def test_cache_eviction_respects_budget(tmp_path: Path, monkeypatch) -> None:
    """A budget too small even for the just-written entry evicts it before
    prepare() returns. Silently succeeding would send a nonexistent cache
    path into the source plan (dead air at encode time) -- prepare() must
    raise a clean SourcePrepareError instead."""
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0.000000001")  # ~1 byte
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # the legacy ffmpeg-concat engine's trim-passthrough wiring
    )
    with pytest.raises(SourcePrepareError, match="budget"):
        preparer.prepare(_untrimmed_plan(tmp_path), _config())
    cache_dir = tmp_path / "work" / "conform-cache"
    assert list(cache_dir.glob("*.ts")) == []  # over budget -> evicted immediately


def test_foreground_conform_does_not_race_a_concurrent_conform_for_same_key(
    tmp_path: Path,
) -> None:
    """automation.py shares one SourcePreparer across channels: a background
    warm and a foreground untrimmed-miss conform for the SAME asset (same
    cache key) can both reach _conform_full_asset_into_cache at once with no
    lock guarding it, both writing the identical {key}.ts.tmp. Concurrent
    calls for the same key must be serialized."""
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")

    active = 0
    max_active = 0
    guard = threading.Lock()
    proceed = threading.Event()

    def runner(args: list[str]) -> FfmpegResult:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        proceed.wait(timeout=5)
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_text("prepared", encoding="utf-8")
        with guard:
            active -= 1
        return FfmpegResult(returncode=0, stdout="", stderr="")

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    loudness = _loudness()

    def conform() -> None:
        preparer._conform_full_asset_into_cache(key, source, config, loudness, False)

    t1 = threading.Thread(target=conform)
    t2 = threading.Thread(target=conform)
    t1.start()
    time.sleep(0.05)  # give t1 a head start so t2 has to contend for the key
    t2.start()
    proceed.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert max_active == 1  # the two conforms for the same key never overlap


def test_cache_disabled_by_nonpositive_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0")
    calls: list[list[str]] = []
    probes: list[dict] = []
    for _ in range(2):
        SourcePreparer(
            work_dir=tmp_path / "work",
            ffmpeg_runner=_counting_runner(calls),
            loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
            warm_scheduler=lambda job: job(),
            playout_trim_supported=True,
        ).prepare(_untrimmed_plan(tmp_path), _config())

    assert len(calls) == 2  # conforms every airing — the historic behavior
    assert not (tmp_path / "work" / "conform-cache").exists()


def test_cache_hit_stream_copies_when_engine_cannot_trim(tmp_path: Path) -> None:
    """The GStreamer engine reads only segment.path (no inpoint/outpoint), so
    under playout_trim_supported=False a cache hit must emit a TRIM-FREE
    per-plan output produced by a fast `-c copy` window — never a re-encode,
    and never a trimmed segment the engine would ignore."""

    calls: list[list[str]] = []
    common: dict = {
        "work_dir": tmp_path / "work",
        "loudness_checker": lambda **_kwargs: _loudness(),
        "warm_scheduler": lambda job: job(),
    }
    plan = _source_plan(tmp_path)  # built once: rewriting the source would change its mtime/key
    # Warm the cache via a first airing (flag value irrelevant for warming).
    SourcePreparer(
        ffmpeg_runner=_counting_runner([]), playout_trim_supported=False, **common
    ).prepare(plan, _config())

    report = SourcePreparer(
        ffmpeg_runner=_counting_runner(calls), playout_trim_supported=False, **common
    ).prepare(plan, _config())

    assert len(calls) == 1
    copy_args = calls[0]
    assert copy_args[copy_args.index("-c") : copy_args.index("-c") + 2] == ["-c", "copy"]
    assert "-b:v" not in copy_args  # no re-encode
    seg = report.source_plan.segments[0]
    assert seg.inpoint_seconds is None and seg.outpoint_seconds is None  # trim-free contract
    assert "conform-cache" not in seg.path  # per-plan output, not the cache object


# ---------------------------------------------------------------------------
# Item 66 — first ON_AIR no longer waits behind a whole-clip conform on the
# synchronous start path. Revised after Opus review of PR #180: the original
# single-threaded (`-threads 1`) foreground conform and unconditional
# untrimmed-MISS-into-cache promotion both measured badly on real hardware
# (HALO) and are replaced below by a thread cap, per-asset loudness
# memoization, foreground-conform-promotes-into-cache, and a single-worker
# warm queue.
# ---------------------------------------------------------------------------


def test_build_conform_source_args_threads_param(tmp_path: Path) -> None:
    """``build_conform_source_args``'s ``threads`` argument (replacing the
    old boolean ``background`` flag) emits ``-threads <N>`` only when given,
    and omits the flag entirely (ffmpeg's own default) when ``None``."""
    source = tmp_path / "source.mp4"
    output = tmp_path / "prepared.ts"
    profile = _config().canonical_profile

    default_args = build_conform_source_args(
        source_path=source, output_path=output, segment=None, profile=profile
    )
    assert "-threads" not in default_args

    capped_args = build_conform_source_args(
        source_path=source, output_path=output, segment=None, profile=profile, threads=3
    )
    assert capped_args[capped_args.index("-threads") : capped_args.index("-threads") + 2] == [
        "-threads",
        "3",
    ]


def test_conform_full_asset_into_cache_thread_param(tmp_path: Path) -> None:
    """``_conform_full_asset_into_cache``'s ``threads`` parameter must reach
    ``build_conform_source_args``: the warm-behind path (default, ``threads=1``)
    still caps the encode at one thread so a background warm can never starve
    the on-air encoder, but an explicit foreground cap must be honored
    verbatim for the synchronous caller (point 2, Opus review: the prior
    unconditional ``background=False`` -- fully unthrottled -- measured
    233s/300s at `-threads 1` vs 36.6s/300s unthrottled on HALO, an
    unacceptable regression on the synchronous content-reload path)."""
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    loudness = _loudness()

    key_bg = preparer._cache_key(source, config)
    assert key_bg is not None
    preparer._conform_full_asset_into_cache(key_bg, source, config, loudness, False)
    warm_args = calls[-1]
    assert warm_args[warm_args.index("-threads") : warm_args.index("-threads") + 2] == [
        "-threads",
        "1",
    ]

    # A different source (different cache key) so the second call is not
    # short-circuited by the first call's cache entry -- exercise an
    # explicit foreground cap.
    source2 = tmp_path / "long-recording-2.mp4"
    source2.write_text("different fake long media", encoding="utf-8")
    key_fg = preparer._cache_key(source2, config)
    assert key_fg is not None
    calls.clear()
    preparer._conform_full_asset_into_cache(key_fg, source2, config, loudness, False, threads=4)
    fg_args = calls[-1]
    assert fg_args[fg_args.index("-threads") : fg_args.index("-threads") + 2] == [
        "-threads",
        "4",
    ]


def test_untrimmed_miss_runs_bounded_conform_and_promotes_into_cache(tmp_path: Path) -> None:
    """Item 66, points 2+3: with the GStreamer engine (``playout_trim_supported
    =False``, the constructor default) an untrimmed cache MISS must NOT take
    the whole-asset synchronous conform (measured 8.5-12+ min to first
    ON_AIR on a fresh station) -- it falls through to a bounded per-segment
    conform (``-t <duration>``, thread-capped, not single-threaded/unthrottled).
    Because an untrimmed segment IS the whole asset by definition, that
    bounded conform's output is promoted straight into the persistent
    conform cache instead of a redundant warm being scheduled."""
    calls: list[list[str]] = []
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
        # playout_trim_supported left at its default (False) -- the
        # GStreamer-engine wiring this fix targets.
    )

    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())

    # Two ffmpeg calls: (1) the bounded foreground conform into a private
    # per-plan tmp file, then (2) _emit_prepared_from_cache's normal `-c
    # copy` copy-out from the now-populated cache into the per-plan output
    # (the same shape a genuine cache HIT would take) -- never a second
    # re-encode of the asset.
    assert len(calls) == 2
    conform_args = calls[0]
    assert conform_args[conform_args.index("-t") : conform_args.index("-t") + 2] == [
        "-t",
        "3600",
    ]
    assert "-threads" in conform_args  # foreground-capped, not unthrottled/single-threaded
    assert "conform-cache" not in conform_args[-1]  # conforms to a private per-plan tmp, not the
    # cache path directly -- the promotion is a Python rename, not an ffmpeg output target.
    copy_out_args = calls[1]
    assert copy_out_args[copy_out_args.index("-c") : copy_out_args.index("-c") + 2] == [
        "-c",
        "copy",
    ]
    assert "-b:v" not in copy_out_args  # no re-encode on the copy-out
    seg = report.source_plan.segments[0]
    assert "conform-cache" not in seg.path  # per-plan output emitted via copy-out
    assert len(warm_jobs) == 0  # no redundant warm -- this conform already populated the cache

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    assert (tmp_path / "work" / "conform-cache" / f"{key}.ts").is_file()
    assert (tmp_path / "work" / "conform-cache" / f"{key}.json").is_file()

    # A second prepare() of the same asset is now a genuine cache HIT: the
    # engine still can't trim at playout, so it costs one fast `-c copy`
    # copy-out (never a re-encode) and zero warms -- never a second
    # full-asset conform.
    calls.clear()
    warm_jobs.clear()
    preparer.prepare(_untrimmed_plan(tmp_path), _config())
    assert len(calls) == 1
    hit_copy_args = calls[0]
    assert hit_copy_args[hit_copy_args.index("-c") : hit_copy_args.index("-c") + 2] == [
        "-c",
        "copy",
    ]
    assert "-b:v" not in hit_copy_args
    assert warm_jobs == []


def test_untrimmed_miss_still_conforms_full_asset_when_engine_can_trim(tmp_path: Path) -> None:
    """Companion to the test above: with ``playout_trim_supported=True`` (the
    legacy ffmpeg-concat engine) the SHAPE of an untrimmed miss is unchanged
    by item 66 -- it still conforms the whole asset synchronously straight
    into the cache (no ``-t``/``-ss``), matching the pre-existing
    ``test_aired_before_asset_prepares_with_zero_ffmpeg_work`` contract.
    What DOES change (point 2, Opus review): this synchronous conform is now
    thread-capped rather than fully unthrottled, since it is reachable
    outside first-ON_AIR too (``EgressDaemon._try_content_reload``'s
    synchronous prepare while another channel may be on air)."""
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
        playout_trim_supported=True,
    )

    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())

    assert len(calls) == 1
    args = calls[0]
    assert "-t" not in args  # whole-asset conform, not bounded to the segment
    assert "-ss" not in args
    assert "-threads" in args  # point 2: thread-capped, no longer fully unthrottled
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path  # emitted straight from the cache object


def test_loudness_probed_once_for_all_segments_of_one_asset_in_one_prepare(
    tmp_path: Path,
) -> None:
    """Item 66, point 1: 8 differently-trimmed segments of the SAME asset
    (same cache key, distinct (path, inpoint, outpoint) so prepare()'s own
    ``seen`` dedupe does not short-circuit them) used to mean 8 full-file
    loudness probes on the synchronous start path (~6.3 minutes measured).
    The first segment probes and persists the meta immediately -- before any
    conform for the asset exists -- so the other 7 reuse it."""
    probes: list[dict] = []
    calls: list[list[str]] = []
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: None,
    )

    def plan() -> EgressSourcePlan:
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label=f"segment-{i}",
                    path=str(source),
                    duration_seconds=30.0,
                    inpoint_seconds=float(i * 30),
                    outpoint_seconds=float(i * 30 + 30),
                )
                for i in range(8)
            ],
        )

    preparer.prepare(plan(), _config())

    assert len(probes) == 1  # exactly one loudness probe for all 8 segments
    assert len(calls) == 8  # each distinct trim still gets its own bounded conform


def test_loudness_probe_reused_across_prepares_of_the_same_asset(tmp_path: Path) -> None:
    """Companion: a SECOND prepare() of the same asset (a fresh
    ``SourcePreparer`` sharing ``work_dir``, no warm ever run) must run ZERO
    loudness probes -- the meta persisted by the first prepare() survives on
    disk and is read back before any probe is attempted."""
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")

    def plan() -> EgressSourcePlan:
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="joined-late",
                    path=str(source),
                    duration_seconds=30.0,
                    inpoint_seconds=5.0,
                    outpoint_seconds=35.0,
                )
            ],
        )

    probes_1: list[dict] = []
    SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **kwargs: probes_1.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: None,  # the warm never runs -- no full conform is cached
    ).prepare(plan(), _config())
    assert len(probes_1) == 1

    probes_2: list[dict] = []
    SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **kwargs: probes_2.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: None,
    ).prepare(plan(), _config())
    assert probes_2 == []  # reused from the meta the first prepare() persisted


def test_default_warm_scheduler_runs_one_job_at_a_time_fifo(tmp_path: Path) -> None:
    """Item 66, point 4: the production ``_default_warm_scheduler`` used to
    spawn one daemon thread PER job -- unbounded. It must instead queue jobs
    onto a single worker: 3 distinct assets queue 3 jobs, but at most 1 ever
    runs concurrently."""
    active = 0
    max_active = 0
    guard = threading.Lock()
    started = threading.Event()
    release = threading.Event()
    completed: list[int] = []

    def make_job(n: int):
        def _job() -> None:
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            if n == 0:
                started.set()
                release.wait(timeout=5)
            with guard:
                active -= 1
            completed.append(n)

        return _job

    for n in range(3):
        preparer_module._default_warm_scheduler(make_job(n))

    assert started.wait(timeout=5)  # the first job is running
    assert max_active == 1  # never more than one warm job active at once
    release.set()
    # Give the single worker time to drain the remaining queued jobs.
    deadline = time.monotonic() + 5
    while len(completed) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sorted(completed) == [0, 1, 2]
    assert max_active == 1
