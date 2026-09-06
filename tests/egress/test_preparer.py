# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for egress source preparation."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
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


def test_schedule_warm_discards_key_when_scheduler_itself_fails(tmp_path: Path) -> None:
    """Item 66 round-6 (Opus review, point 7): if handing the warm job to
    ``self._warm_scheduler`` itself raises (the job never gets a chance to
    run, let alone clean up after itself), ``key`` must not be left stuck
    in ``self._warming`` forever -- that would silently suppress every
    GENUINE future warm for this asset for the life of this
    ``SourcePreparer`` instance."""

    def failing_scheduler(_job: Callable[[], None]) -> None:
        raise RuntimeError("scheduler is down")

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=failing_scheduler,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None

    preparer._schedule_warm(key, source, config, _loudness(), False)  # must not raise

    assert key not in preparer._warming  # not left stuck -- a genuine warm can still be scheduled


def test_schedule_cache_copy_promotion_discards_key_when_scheduler_itself_fails(
    tmp_path: Path,
) -> None:
    """Companion for ``_schedule_cache_copy_promotion`` -- the exact same
    ``self._warming`` set, the exact same failure mode."""

    def failing_scheduler(_job: Callable[[], None]) -> None:
        raise RuntimeError("scheduler is down")

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=failing_scheduler,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes", encoding="utf-8")

    preparer._schedule_cache_copy_promotion(
        key, finished, source, _loudness(), False
    )  # must not raise

    assert key not in preparer._warming


def test_schedule_warm_job_reconforms_a_flagless_legacy_cache_entry(tmp_path: Path) -> None:
    """Item 66 round-9 (tests-only follow-up to the round-8 MEDIUM fix).
    ``_schedule_warm``'s queued ``_job`` must treat a flagless legacy meta
    (a pre-round-7 entry, or a probe-only write that never got a conform)
    as a MISS, not an already-populated hit -- see the round-8 comment right
    above the skip check in ``preparer.py`` for the self-heal failure this
    guards against. Plant exactly that shape (a short ``.ts`` alongside a
    meta with no ``full_asset_conform`` key at all) and prove the job
    actually re-conforms instead of returning early: reverting the skip
    predicate back to ``cached_meta is not None`` makes this fail, because
    that predicate alone is satisfied by the flagless meta and the job would
    return before ever calling the ffmpeg runner."""
    calls: list[list[str]] = []
    warm_jobs: list[Callable[[], None]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None

    preparer._schedule_warm(key, source, config, _loudness(), False)
    assert len(warm_jobs) == 1

    # Plant a flagless legacy entry -- exactly the pre-round-7 on-disk shape --
    # as if some earlier, now-stale run had left it there.
    cache_dir = tmp_path / "work" / "conform-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.ts").write_text("stale short fragment", encoding="utf-8")
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "loudness_status": "ok",
                "measured_lufs": -24.1,
                "normalized": False,
                "media_duration_seconds": None,
                # no "full_asset_conform" key at all -- the pre-round-7 shape
            }
        ),
        encoding="utf-8",
    )

    warm_jobs[0]()  # run the queued job now

    assert len(calls) == 1  # re-conformed -- the flagless entry was never trusted as a HIT
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["full_asset_conform"] is True  # the fresh conform's own promotion set it


def test_schedule_cache_copy_promotion_job_reconforms_a_flagless_legacy_cache_entry(
    tmp_path: Path,
) -> None:
    """Companion to the test above for ``_schedule_cache_copy_promotion``'s
    own queued ``_job`` -- the exact same round-8 MEDIUM fix, the exact same
    self-heal failure mode, a different job body (a byte-for-byte copy of an
    already-finished per-plan file rather than a fresh ffmpeg conform)."""
    warm_jobs: list[Callable[[], None]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("the real, complete finished asset", encoding="utf-8")

    preparer._schedule_cache_copy_promotion(key, finished, source, _loudness(), False)
    assert len(warm_jobs) == 1

    # Plant a flagless legacy entry with SHORT, stale content -- if the job
    # wrongly treats this as already-populated, the copy never happens and
    # the stale bytes below survive unchanged.
    cache_dir = tmp_path / "work" / "conform-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.ts").write_text("stale short fragment", encoding="utf-8")
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "loudness_status": "ok",
                "measured_lufs": -24.1,
                "normalized": False,
                "media_duration_seconds": None,
                # no "full_asset_conform" key at all -- the pre-round-7 shape
            }
        ),
        encoding="utf-8",
    )

    warm_jobs[0]()  # run the queued job now

    cached_ts = cache_dir / f"{key}.ts"
    assert cached_ts.read_text(encoding="utf-8") == "the real, complete finished asset"
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["full_asset_conform"] is True


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


def test_conform_full_asset_into_cache_skips_instead_of_blocking_on_contention(
    tmp_path: Path,
) -> None:
    """automation.py shares one SourcePreparer across channels: a background
    warm and a foreground untrimmed-miss conform for the SAME asset (same
    cache key) can both reach _conform_full_asset_into_cache at once with no
    lock guarding it, both writing the identical {key}.ts.tmp -- concurrent
    calls for the same key must never collide.

    Item 66 round-4 (Opus review, point 1) changed HOW that's guaranteed:
    the per-key lock used to be acquired BLOCKING, so a contended second
    call would wait for the first to finish (serialized, but the FIRST
    version of this test's docstring called that the fix -- it was itself
    the bug: a synchronous caller blocking behind a background warm's
    entire single-threaded conform, tens of minutes for a long asset).
    The lock is now acquired NON-BLOCKING: a contended call returns
    ``None`` immediately instead of waiting, and never touches the ffmpeg
    runner at all."""
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")

    active = 0
    max_active = 0
    guard = threading.Lock()
    holder_started = threading.Event()
    proceed = threading.Event()

    def runner(args: list[str]) -> FfmpegResult:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        holder_started.set()
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

    results: dict[int, Path | None] = {}

    def conform(index: int) -> None:
        results[index] = preparer._conform_full_asset_into_cache(
            key, source, config, loudness, False
        )

    t1 = threading.Thread(target=conform, args=(0,))
    t1.start()
    assert holder_started.wait(timeout=5)  # t1 genuinely holds the lock and is running

    # t2's call, made while t1 still holds the lock, must return None
    # immediately -- not wait, not run the ffmpeg runner.
    contended_result = preparer._conform_full_asset_into_cache(key, source, config, loudness, False)
    assert contended_result is None
    assert max_active == 1  # t2 never entered the runner -- never ran concurrently with t1

    proceed.set()
    t1.join(timeout=5)
    assert results[0] is not None  # t1 completed normally and populated the cache


def test_prepare_does_not_block_behind_a_warm_holding_the_cache_lock(tmp_path: Path) -> None:
    """Item 66 round-4 BLOCKER acceptance test (Opus review, point 1):
    reproduces the exact measured regression -- a synchronous prepare()
    took 3.01s behind a 3-second fake warm holding this asset's per-key
    lock -- and proves it is fixed. GStreamer engine (the constructor
    default): the untrimmed-miss path's cache promotion
    (_promote_finished_conform_into_cache) must not wait for the warm at
    all; the segment still airs from its own per-plan file regardless."""
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    key = preparer._cache_key(source, _config())
    assert key is not None
    lock = preparer._conform_lock(key)

    def fake_three_second_warm() -> None:
        with lock:
            time.sleep(3.0)

    warm_thread = threading.Thread(target=fake_three_second_warm, daemon=True)
    warm_thread.start()
    time.sleep(0.1)  # give the fake warm time to actually acquire the lock first

    started = time.monotonic()
    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())
    elapsed = time.monotonic() - started

    assert elapsed < 0.5  # measured regression: 3.01s; must not block behind the 3s warm
    seg = report.source_plan.segments[0]
    assert Path(seg.path).is_file()  # the segment still airs from its own per-plan file


def test_prepare_does_not_block_behind_a_warm_when_engine_can_trim(tmp_path: Path) -> None:
    """Companion (item 66 round-4, point 1's "Same at :995-998"): the
    playout_trim_supported=True call site (_conform_full_asset_into_cache
    invoked directly from _prepare_segment, not via the promotion helper)
    gets the same non-blocking treatment. Contention there falls through
    to the bounded per-segment conform instead of blocking on the lock
    too."""
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
        playout_trim_supported=True,
    )
    key = preparer._cache_key(source, _config())
    assert key is not None
    lock = preparer._conform_lock(key)

    def fake_three_second_warm() -> None:
        with lock:
            time.sleep(3.0)

    warm_thread = threading.Thread(target=fake_three_second_warm, daemon=True)
    warm_thread.start()
    time.sleep(0.1)

    started = time.monotonic()
    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    seg = report.source_plan.segments[0]
    # Fallback shape: a plain per-plan file, NOT a pointer into the (contended)
    # cache object -- this one airing gets its own bounded conform instead.
    assert "conform-cache" not in seg.path
    assert Path(seg.path).is_file()


def test_schedule_warm_job_skips_when_cache_already_populated_before_it_runs(
    tmp_path: Path,
) -> None:
    """Item 66 round-4 (Opus review, point 1): a queued warm job may sit in
    the single-worker warm queue for a while (round-3, point 4) -- by the
    time it is about to run, the identical asset may already be cached
    (e.g. a foreground untrimmed-miss conform promoted its own
    already-finished file straight in). The job must re-check {key}.ts
    existence (and a fresh meta) right before doing any work and skip the
    redundant re-conform if it's already there.

    Item 66 round-8 (MEDIUM fix): "already cached" now requires the
    simulated meta to genuinely carry ``full_asset_conform=True`` -- a
    flagless meta (what this test used to simulate) is no longer treated
    as a real cache hit by the job's own skip check (see
    ``_write_cache_meta``'s and the cache-HIT check's docstrings for why),
    so the simulated write below must match what a genuine promotion
    (``_promote_conform_into_cache``) actually persists."""
    calls: list[list[str]] = []
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    loudness = _loudness()

    preparer._schedule_warm(key, source, config, loudness, False)
    assert len(warm_jobs) == 1

    # Simulate the cache being populated by a concurrent caller WHILE this
    # job was still sitting in the queue.
    preparer._write_cache_meta(key, loudness, False, full_asset_conform=True)
    cache_dir = tmp_path / "work" / "conform-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.ts").write_text("already cached", encoding="utf-8")

    warm_jobs[0]()  # run the queued job now

    assert calls == []  # skipped the redundant re-conform


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


def test_foreground_thread_cap_is_pinned_to_cpu_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 66 round-3 (Opus review, point 2): pin the exact cap formula --
    half the box's cores, floored at 1 -- with a monkeypatched
    ``os.cpu_count()``, mirroring the shape of
    ``tests/captions/test_caption_tap_worker.py``'s
    ``test_default_concurrency_is_one_channel_per_eight_cpus``, including
    the ``cpu_count() -> None`` case (documented as possible by the stdlib)."""
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 8)
    assert preparer_module._foreground_thread_cap() == 4
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 4)
    assert preparer_module._foreground_thread_cap() == 2
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 2)
    assert preparer_module._foreground_thread_cap() == 1
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 1)
    assert preparer_module._foreground_thread_cap() == 1
    # `os.cpu_count()` is documented as possibly None.
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: None)
    assert preparer_module._foreground_thread_cap() == 1


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


def test_untrimmed_miss_runs_one_bounded_conform_and_links_into_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-3 BLOCKER fix (Opus review, point 1): with the
    GStreamer engine (``playout_trim_supported=False``, the constructor
    default) an untrimmed cache MISS falls through to a bounded
    per-segment conform (``-t <duration>``, thread-capped). The round-2
    version of this fix moved that conform's output INTO the cache and
    then copied it back OUT for the per-plan file -- an extra full-length
    copy on the blocking path. The per-plan file must now be the DIRECT
    result of the one ffmpeg call (finished before the cache is touched at
    all), and the cache must be populated from a link/copy of that same
    file, not a second ffmpeg invocation.

    Item 66 round-8 (HIGH fix): the direct-promotion path this test targets
    now requires a KNOWN ``media_duration`` that demonstrably covers the
    segment (see ``is_full_asset_conform`` in ``preparer.py`` -- an unknown
    duration always routes to ``_schedule_warm`` instead, since it can no
    longer be trusted that an untrimmed segment reaching here is genuinely
    the whole asset). ``probe_media_duration_seconds`` is patched to return
    exactly the plan's own ``duration_seconds`` (3600s) so this test keeps
    exercising the direct-link path it was written for, rather than the
    fake ``.mp4`` (plain text, no real media) failing a real ffprobe call
    and silently falling into the round-8 fail-closed branch instead."""
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda *_a, **_k: 3600.0)
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

    assert len(calls) == 1  # exactly one ffmpeg call -- no copy-out round trip
    conform_args = calls[0]
    assert conform_args[conform_args.index("-t") : conform_args.index("-t") + 2] == [
        "-t",
        "3600",
    ]
    assert conform_args[conform_args.index("-threads") : conform_args.index("-threads") + 2] == [
        "-threads",
        "4",  # max(1, 8 // 2)
    ]
    assert "conform-cache" not in conform_args[-1]  # conforms to a private per-plan tmp
    seg = report.source_plan.segments[0]
    assert "conform-cache" not in seg.path  # the re-encoded per-plan file itself airs
    assert Path(seg.path).is_file()  # what airs must actually exist
    assert len(warm_jobs) == 0  # no redundant warm -- this conform already populated the cache

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    cache_ts = tmp_path / "work" / "conform-cache" / f"{key}.ts"
    assert cache_ts.is_file()
    assert (tmp_path / "work" / "conform-cache" / f"{key}.json").is_file()
    assert not cache_ts.with_suffix(".ts.tmp").exists()  # no leftover tmp sibling
    # Linked (or copied), never MOVED: the per-plan file must still exist too.
    assert Path(seg.path).exists()

    # A second prepare() of the same asset is now a genuine cache HIT: the
    # engine still can't trim at playout, so it costs one fast `-c copy`
    # copy-out (never a re-encode) and zero warms.
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


def test_promote_finished_conform_links_without_moving_the_per_plan_file(
    tmp_path: Path,
) -> None:
    """Unit-level companion: ``_promote_finished_conform_into_cache`` must
    populate the cache from ``finished_output_path`` without ever making
    that path disappear (a link or a copy, never a move)."""
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes", encoding="utf-8")

    preparer._promote_finished_conform_into_cache(key, finished, source, _loudness(), False)

    cache_ts = tmp_path / "work" / "conform-cache" / f"{key}.ts"
    assert cache_ts.is_file()
    assert cache_ts.read_text(encoding="utf-8") == "prepared bytes"
    assert finished.is_file()  # never moved
    assert finished.read_text(encoding="utf-8") == "prepared bytes"


def test_promote_finished_conform_queues_a_copy_job_when_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-4 (Opus review, point 3): ``os.link`` can fail (e.g.
    the cache lives on a different volume than the per-plan directory) --
    the fallback is no longer an inline ``shutil.copy2`` on the
    synchronous start path (a full byte-for-byte copy of a long asset is
    exactly the kind of blocking work item 66 exists to close). It must
    instead be QUEUED onto the warm scheduler and return immediately
    without having copied anything yet."""
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes", encoding="utf-8")

    def _raising_link(_src: object, _dst: object) -> None:
        raise OSError("simulated cross-volume link failure")

    monkeypatch.setattr(preparer_module.os, "link", _raising_link)

    preparer._promote_finished_conform_into_cache(key, finished, source, _loudness(), False)

    cache_ts = tmp_path / "work" / "conform-cache" / f"{key}.ts"
    assert not cache_ts.exists()  # not populated yet -- the copy is only queued
    assert len(warm_jobs) == 1

    warm_jobs[0]()  # run the queued copy job

    assert cache_ts.is_file()  # now populated via the background shutil.copy2
    assert cache_ts.read_text(encoding="utf-8") == "prepared bytes"
    assert finished.is_file()


def test_cache_copy_promotion_job_cleans_up_tmp_on_a_post_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-6 (Opus review, point 5): the copy job's INNER
    try/except already cleaned up a partial ``.ts.tmp`` when ``shutil.
    copy2`` itself failed -- but a failure AFTER a successful copy (e.g.
    ``_promote_conform_into_cache``'s own over-budget raise, which runs
    after the copy2 succeeded but before the tmp is renamed away) hit only
    the OUTER except, which did not clean up. It must now unlink the tmp
    there too."""
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0.000000001")  # ~1 byte -- guarantees
    # _promote_conform_into_cache's own over-budget SourcePrepareError, raised AFTER copy2
    # succeeds and BEFORE the tmp is renamed away.
    warm_jobs: list = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes long enough to exceed a 1-byte budget", encoding="utf-8")

    def _raising_link(_src: object, _dst: object) -> None:
        raise OSError("simulated cross-volume link failure")

    monkeypatch.setattr(preparer_module.os, "link", _raising_link)

    preparer._promote_finished_conform_into_cache(key, finished, source, _loudness(), False)
    assert len(warm_jobs) == 1
    warm_jobs[0]()  # must not raise -- the job's own outer except must swallow it

    tmp = tmp_path / "work" / "conform-cache" / f"{key}.ts.tmp"
    assert not tmp.exists()  # cleaned up by the outer except, not left for the orphan reap
    assert finished.is_file()  # the segment's own file is never touched by any of this


def test_promote_finished_conform_does_not_deadlock_with_synchronous_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-5 BLOCKER fix (Opus review, point 1): round-4 scheduled
    the cross-volume copy job from INSIDE the still-held per-key lock, and
    the job itself blocking-acquired that SAME lock -- with a SYNCHRONOUS
    warm_scheduler (``lambda job: job()``, the exact shape
    ``test_aired_before_asset_prepares_with_zero_ffmpeg_work`` at line 622
    uses), the job runs inline, before this frame's own ``finally:
    lock.release()`` could ever execute -- a guaranteed self-deadlock. This
    call must simply RETURN."""
    warm_jobs: list = []

    def synchronous_scheduler(job: Callable[[], None]) -> None:
        warm_jobs.append(job)
        job()  # run it inline, immediately -- the exact shape that self-deadlocked in round 4

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=synchronous_scheduler,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes", encoding="utf-8")

    def _raising_link(_src: object, _dst: object) -> None:
        raise OSError("simulated cross-volume link failure")

    monkeypatch.setattr(preparer_module.os, "link", _raising_link)

    # Must return promptly -- pytest's own timeout is the real backstop,
    # but the point of this test is that this call does not hang at all.
    preparer._promote_finished_conform_into_cache(key, finished, source, _loudness(), False)

    assert len(warm_jobs) == 1  # the copy job ran synchronously, inline, without deadlocking
    cache_ts = tmp_path / "work" / "conform-cache" / f"{key}.ts"
    assert cache_ts.is_file()  # and it actually completed the copy + promotion
    assert cache_ts.read_text(encoding="utf-8") == "prepared bytes"


def test_promote_finished_conform_swallows_over_budget_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BLOCKER regression guard: a promotion failure (here, this single
    entry alone exceeding ``CIVICCAST_CONFORM_CACHE_GB``) must never
    propagate -- the per-plan file already airs and must keep existing."""
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0.000000001")  # ~1 byte
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    source = tmp_path / "long-recording.mp4"
    source.write_text("fake long media", encoding="utf-8")
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None  # a positive (if tiny) budget still enables caching
    finished = tmp_path / "already-airing.ts"
    finished.write_text("prepared bytes long enough to exceed a 1-byte budget", encoding="utf-8")

    preparer._promote_finished_conform_into_cache(
        key, finished, source, _loudness(), False
    )  # must not raise

    assert finished.is_file()  # the per-plan file survives regardless
    assert not (tmp_path / "work" / "conform-cache" / f"{key}.ts").exists()  # evicted over budget


def test_untrimmed_miss_still_airs_when_cache_promotion_fails_over_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end companion: the exact BLOCKER scenario through ``prepare()``
    itself -- a promotion that fails over budget must not turn into a
    failed ``prepare()`` call. Before this fix, ``_promote_conform_into_
    cache``'s ``SourcePrepareError`` propagated straight out of
    ``_prepare_segment`` because the per-plan file had already been moved
    into the (now-evicted) cache location."""
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0.000000001")  # ~1 byte
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )

    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())  # must not raise

    assert len(calls) == 1
    seg = report.source_plan.segments[0]
    assert Path(seg.path).is_file()  # the segment airs regardless of the cache-promotion failure


def test_untrimmed_miss_still_conforms_full_asset_when_engine_can_trim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion to the test above: with ``playout_trim_supported=True`` (the
    legacy ffmpeg-concat engine) the SHAPE of an untrimmed miss is unchanged
    by item 66 -- it still conforms the whole asset synchronously straight
    into the cache (no ``-t``/``-ss``), matching the pre-existing
    ``test_aired_before_asset_prepares_with_zero_ffmpeg_work`` contract.
    What DOES change (point 2, Opus review): this synchronous conform is now
    thread-capped rather than fully unthrottled, since it is reachable
    outside first-ON_AIR too (``EgressDaemon._try_content_reload``'s
    synchronous prepare while another channel may be on air) -- pin the
    exact cap value, not just its presence."""
    monkeypatch.setattr(preparer_module.os, "cpu_count", lambda: 4)
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
    assert args[args.index("-threads") : args.index("-threads") + 2] == [
        "-threads",
        "2",  # max(1, 4 // 2) -- point 2: exact cap, no longer fully unthrottled
    ]
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path  # emitted straight from the cache object


def test_loudness_probe_is_bounded_to_the_segment_window_when_trimmed(tmp_path: Path) -> None:
    """Item 66 round-3, point 7: a trimmed segment's loudness probe must be
    bounded to its own window (``-ss <inpoint>``, ``-t <duration>``), not
    the whole file."""
    probes: list[dict] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: None,
    )

    # _source_plan: inpoint=2, outpoint=14.5, duration=12.5 -- trimmed.
    preparer.prepare(_source_plan(tmp_path), _config())

    assert len(probes) == 1
    assert probes[0]["probe_start_seconds"] == 2
    assert probes[0]["probe_duration_seconds"] == 12.5


def test_untrimmed_probe_samples_mid_file_not_the_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-4 (Opus review, point 2): an untrimmed probe samples
    40% into the asset's REAL MEDIA DURATION for 120s, NOT the head. A
    round-3 HEAD sample can land on cold-open silence/room tone and
    measure the silence floor instead of the program's real loudness -- a
    real field failure (-70 LUFS at the head of a 39-minute meeting
    recording) that would then drive loudnorm's normalization target
    completely wrong. Round-5 (Opus review, point 2) corrected WHICH
    duration is sampled from: ``segment.duration_seconds`` is the
    schedule-slot-capped duration (source_plan.py's ``_segment_duration``),
    not the asset's own media duration, so this test monkeypatches
    ``probe_media_duration_seconds`` to a known value rather than relying
    on the segment's duration field."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 3600.0)
    probes: list[dict] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())  # 3600s asset

    assert len(probes) == 1
    assert probes[0]["probe_start_seconds"] == 1440.0  # 40% of the 3600s media duration
    assert probes[0]["probe_duration_seconds"] == 120.0

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["media_duration_seconds"] == 3600.0  # cached for a later prepare() call


@pytest.mark.parametrize(
    ("duration", "expected_start", "expected_duration", "second_sample_possible"),
    [
        # Item 66 round-7 (Opus review, point 2, MEDIUM fix): round-6 used
        # 240s (_UNTRIMMED_LOUDNESS_PROBE_CAP_S * 2) as the single-sample
        # cutoff, which let a 120-240s asset's HEAD-only 120s sample stand
        # in for the whole file when it covered at most HALF of it -- a real
        # field failure (a 200s clip whose only audio starts at 130s, past
        # the sampled [0, 120) window, got memoized as silent). The cutoff
        # is now the probe window's own size (120s): at or below it, one
        # sample spanning the whole file is taken from the very start; above
        # it, the "long asset" branch is used instead -- its first sample
        # sits at 40% in (never the head), and a genuinely non-overlapping
        # second sample (start >= first start + 120s, verified below) is
        # only attempted when there is room for one.
        (67.0, 0.0, 67.0, False),  # the exact duration from the PROVEN field failure
        (120.0, 0.0, 120.0, False),  # exactly the new single/dual boundary
        # 150s and 240s: now in the "long asset" branch (>120s), but neither
        # has room for a genuinely non-overlapping second 120s window (that
        # needs >= 240s) -- no resample is attempted, so the ONE (40%-in,
        # never head) sample is what's used. This is exactly what fixes the
        # 200s field failure above: 150s's window [30, 150) and 240s's
        # window [96, 216) both reach well past the old HEAD-only [0, 120)
        # sample and would have caught audio starting at 130s.
        (150.0, 30.0, 120.0, False),
        (240.0, 96.0, 120.0, False),
        (400.0, 160.0, 120.0, True),  # smallest duration where two 120s windows just fit
        (3600.0, 1440.0, 120.0, True),
    ],
)
def test_untrimmed_probe_window_by_media_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
    expected_start: float,
    expected_duration: float,
    second_sample_possible: bool,
) -> None:
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: duration)
    probes: list[dict] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        # A floor reading throughout: proves whether a resample is even
        # ATTEMPTED, regardless of whether it would end up trusted.
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(measured_lufs=-70.0),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    assert probes[0]["probe_start_seconds"] == expected_start
    assert probes[0]["probe_duration_seconds"] == expected_duration
    if second_sample_possible:
        assert len(probes) == 2  # the floor reading triggers exactly one resample
        # The two windows must never overlap: second start >= first start + 120s.
        assert probes[1]["probe_start_seconds"] >= expected_start + 120.0
        assert probes[1]["probe_start_seconds"] + probes[1]["probe_duration_seconds"] <= duration
    else:
        assert len(probes) == 1  # no second window exists to sample -- none attempted


def test_untrimmed_probe_trusts_a_single_conclusive_sample_as_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion to the parametrized test above: for a short, KNOWN-duration
    asset (<=120s -- item 66 round-7 lowered this from 240s, see
    ``_SHORT_ASSET_SINGLE_SAMPLE_MAX_S``'s docstring) whose one sample
    already covers the whole file, a floor reading is trusted directly as
    genuine silence -- there is no second window to corroborate against,
    and none is needed."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 90.0)
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(measured_lufs=-70.0),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -70.0
    assert meta["normalized"] is False  # trusted as silent from the one sample alone


def test_untrimmed_probe_at_120_to_240s_never_trusts_an_unusable_resample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-7 (point 2, MEDIUM fix): a 150s asset (in the "long
    asset" branch now that the single-sample cutoff is 120s, not 240s) has
    no room for a genuinely non-overlapping second 120s window -- two full
    120s windows need >= 240s. The floor reading on the one available
    (40%-in) sample is used directly as the measurement: it is NEITHER
    trusted as conclusive silence (only the <=120s branch does that) NOR
    corroborated by a resample (none was attempted, since none would be
    genuinely independent) -- exactly the round-6 "never trust an
    overlapping/identical resample as evidence" invariant, now also
    enforced in the range round-6 itself couldn't reach (120-240s)."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 150.0)
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        # status="failed": a real loudness checker reports this for a -70.0
        # reading against a -24.0 target -- the test double for the
        # conclusive-silence test above defaults to "ok" only because
        # ``silent_asset`` there forces ``normalized`` to False regardless.
        loudness_checker=lambda **_kwargs: _loudness(status="failed", measured_lufs=-70.0),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -70.0
    # NOT marked "normalized is False" (never trusted as conclusive silence,
    # unlike the <=120s case) -- the floor reading is used as a real
    # measurement, so normalization proceeds toward the target exactly as it
    # would for any other out-of-tolerance reading.
    assert meta["normalized"] is True


def test_untrimmed_probe_falls_back_to_a_second_bounded_sample_on_silence_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-5 (Opus review, point 3): when the mid-file sample
    measures at/below the silence floor (-60 LUFS), resample at a
    DIFFERENT bounded offset (70% into the media, still 120s -- never a
    whole-file decode, which measured 46.7s on a 39-minute clip) and use
    that reading -- the floor sample itself is never used or cached."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 3600.0)
    probes: list[dict] = []

    def loudness_checker(**kwargs: object) -> LoudnessGateResult:
        probes.append(kwargs)
        if kwargs.get("probe_start_seconds") == 1440.0:
            return _loudness(measured_lufs=-70.0)  # the 40%-in sample: silence
        # the 70%-in resample: a real reading, outside tolerance -- needs normalizing
        return _loudness(status="failed", measured_lufs=-16.0)

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=loudness_checker,
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    assert len(probes) == 2  # the first bounded sample, then exactly one resample -- never a loop
    assert probes[0]["probe_start_seconds"] == 1440.0  # 40% of 3600s
    assert probes[0]["probe_duration_seconds"] == 120.0
    assert probes[1]["probe_start_seconds"] == 2520.0  # 70% of 3600s -- a DIFFERENT offset
    assert probes[1]["probe_duration_seconds"] == 120.0  # still bounded, never None (whole file)

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -16.0  # the resample's reading, never the floor sample
    assert (
        meta["normalized"] is True
    )  # -16.0 is outside -24.0 +/- 1.0 tolerance -- still normalizes


def test_untrimmed_probe_keeps_first_reading_when_resample_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-6 (Opus review, point 4): if the resample itself fails
    to produce a measurement (e.g. an ffmpeg error), the first (floor)
    reading is kept -- never raise from a failed resample, and never
    silently overwrite a usable reading with an unmeasured one."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 3600.0)

    def loudness_checker(**kwargs: object) -> LoudnessGateResult:
        if kwargs.get("probe_start_seconds") == 1440.0:
            # the 40%-in sample: silence, well outside tolerance of the -24 target.
            return _loudness(status="failed", measured_lufs=-70.0)
        # the 70%-in resample fails outright -- no measurement at all.
        return _loudness(status="failed", measured_lufs=None)

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=loudness_checker,
        warm_scheduler=lambda job: None,
    )

    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())  # must not raise

    seg = report.source_plan.segments[0]
    assert Path(seg.path).is_file()
    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -70.0  # the first (floor) reading, kept
    assert meta["normalized"] is True  # never marked silent -- the resample couldn't confirm it


def test_untrimmed_probe_treats_asset_as_silent_when_both_samples_hit_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion: TWO independent samples (different offsets) both at the
    silence floor means the asset really is silent -- normalize=False is
    cached rather than trusting either floor reading as a real loudnorm
    target."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 3600.0)
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(measured_lufs=-70.0),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -70.0
    assert meta["normalized"] is False  # never normalize toward a target that isn't there


def test_untrimmed_probe_does_not_fall_back_when_sample_is_above_the_floor(
    tmp_path: Path,
) -> None:
    """Companion: a normal (non-floor) mid-file sample is used as-is -- no
    fallback probe runs at all."""
    probes: list[dict] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(measured_lufs=-24.1),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    assert len(probes) == 1  # no fallback triggered


def test_untrimmed_probe_with_unknown_duration_samples_from_zero_never_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-6 BLOCKER-adjacent fix (Opus review, point 1): PROVEN
    on a real 67-second clip (real loudness -10.9 LUFS): when the real
    media duration is unknown (ffprobe unavailable/failed), round 5's
    fixed 120s/240s offsets landed entirely past the clip's actual end for
    ANY asset shorter than 120s, read as silence, and got misreported as a
    genuinely silent asset. With duration unknown, the probe must sample
    from 0s instead (never past EOF for any asset with real audio), and a
    floor reading there must NEVER be trusted as proof of silence (there
    is no independent second window, and no known length, to corroborate
    it against)."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: None)
    probes: list[dict] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        # Simulates the PROVEN failure mode: a blind offset lands past EOF
        # and reads as silence, even though the real asset is not silent.
        loudness_checker=lambda **kwargs: (
            probes.append(kwargs) or _loudness(status="failed", measured_lufs=-70.0)
        ),
        warm_scheduler=lambda job: None,
    )

    preparer.prepare(_untrimmed_plan(tmp_path), _config())

    assert len(probes) == 1  # sampled once, from the start -- never a second/corroborating sample
    assert probes[0]["probe_start_seconds"] == 0.0
    assert probes[0]["probe_duration_seconds"] == 120.0

    key = preparer._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["measured_lufs"] == -70.0
    assert meta["normalized"] is True  # NEVER trusted as silent when duration is unknown
    assert meta["media_duration_seconds"] is None


def test_cache_hit_utime_race_falls_through_to_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-3, point 4: ``os.utime(cached_ts)`` on a cache HIT can
    race a concurrent eviction pass that removed the entry between the
    ``.is_file()`` check and this call -- must fall through to a MISS
    (re-conform) instead of an unguarded ``FileNotFoundError`` crash."""
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
        playout_trim_supported=True,
    )
    preparer.prepare(_untrimmed_plan(tmp_path), _config())  # warm the cache: a real HIT exists
    assert len(calls) == 1
    calls.clear()

    def _raising_utime(_path: object, *_a: object, **_k: object) -> None:
        raise FileNotFoundError(_path)

    monkeypatch.setattr(preparer_module.os, "utime", _raising_utime)

    report = preparer.prepare(_untrimmed_plan(tmp_path), _config())  # must not raise

    assert len(calls) == 1  # treated as a miss -- re-conformed
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path


def test_evict_cache_over_budget_reaps_orphaned_tmp_and_meta(tmp_path: Path) -> None:
    """Item 66 round-3, point 3: an abandoned ``.ts.tmp`` older than 1h is
    reaped; a younger one is left alone. A ``.json`` with no sibling
    ``.ts`` older than 24h is reaped; one with a sibling ``.ts`` is kept
    regardless of age."""
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    cache_dir = tmp_path / "work" / "conform-cache"
    cache_dir.mkdir(parents=True)

    old_tmp = cache_dir / "orphan1.ts.tmp"
    old_tmp.write_text("stale", encoding="utf-8")
    young_tmp = cache_dir / "orphan2.ts.tmp"
    young_tmp.write_text("still writing", encoding="utf-8")
    orphan_meta = cache_dir / "orphan3.json"
    orphan_meta.write_text("{}", encoding="utf-8")
    paired_meta = cache_dir / "orphan4.json"
    paired_meta.write_text("{}", encoding="utf-8")
    paired_ts = cache_dir / "orphan4.ts"
    paired_ts.write_text("real cache entry", encoding="utf-8")

    old_tmp_time = time.time() - preparer_module._ORPHAN_CACHE_TMP_MAX_AGE_S - 60
    os.utime(old_tmp, (old_tmp_time, old_tmp_time))
    old_meta_time = time.time() - preparer_module._ORPHAN_CACHE_META_MAX_AGE_S - 60
    os.utime(orphan_meta, (old_meta_time, old_meta_time))

    preparer._evict_cache_over_budget()

    assert not old_tmp.exists()  # reaped: old orphaned .tmp
    assert young_tmp.exists()  # kept: still within the age floor
    assert not orphan_meta.exists()  # reaped: old .json with no sibling .ts
    assert paired_meta.exists()  # kept: has a sibling .ts
    assert paired_ts.exists()


def test_evict_cache_over_budget_counts_live_tmp_bytes_toward_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-3, point 3: a live (young) ``.ts.tmp`` counts toward
    the budget even though it is never itself evicted here -- so a real
    ``.ts`` entry is evicted earlier to make room for in-flight writes."""
    monkeypatch.setenv("CIVICCAST_CONFORM_CACHE_GB", "0.0000001")  # 100 bytes
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    cache_dir = tmp_path / "work" / "conform-cache"
    cache_dir.mkdir(parents=True)
    ts_entry = cache_dir / "aaaa.ts"
    ts_entry.write_text("x" * 60, encoding="utf-8")
    live_tmp = cache_dir / "bbbb.ts.tmp"
    live_tmp.write_text("y" * 60, encoding="utf-8")  # young -- not orphaned

    preparer._evict_cache_over_budget()

    # 60 (live .tmp, counted but never evicted here) + 60 (.ts) = 120 bytes,
    # over the ~100-byte budget -- the .ts entry is evicted to bring the
    # total back down; the live .tmp itself is left alone.
    assert not ts_entry.exists()
    assert live_tmp.exists()


def test_write_cache_meta_is_atomic_tmp_replace(tmp_path: Path) -> None:
    """Item 66 round-3, point 4: ``_write_cache_meta``'s sidecar write must
    be tmp+replace, matching every ``.ts`` write in this module -- no
    leftover ``.tmp`` sibling once the write completes."""
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )

    preparer._write_cache_meta("somekey", _loudness(), False)

    cache_dir = tmp_path / "work" / "conform-cache"
    assert (cache_dir / "somekey.json").is_file()
    assert not (cache_dir / "somekey.json.tmp").exists()


def test_cli_source_preparer_wires_playout_trim_supported(tmp_path: Path) -> None:
    """Item 66 round-3, point 6: ``cli.py``'s ``SourcePreparer(work_dir=
    work_dir)`` construction was missing ``playout_trim_supported`` entirely
    (silently defaulting to ``False`` even on the legacy ffmpeg-concat
    engine) -- it must now mirror ``automation.py``'s
    ``not gstreamer_engine_selected()`` wiring via the same helper."""
    import inspect

    from civiccast import cli as cli_module

    source = inspect.getsource(cli_module._run_egress_service)
    assert "gstreamer_engine_selected" in source
    assert "playout_trim_supported=not gstreamer_engine_selected()" in source


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


def test_untrimmed_second_prepare_of_same_asset_runs_zero_ffprobes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-6 (Opus review, point 3): an untrimmed asset's real
    media duration (probed via ``probe_media_duration_seconds``) is cached
    in the same meta as its loudness result -- a SECOND ``prepare()`` of
    the same asset (a fresh ``SourcePreparer`` sharing ``work_dir``) must
    run ZERO ffprobes, same as it must run zero loudness probes. The
    duration read back from the reused meta (see ``_prepare_segment``'s
    ``if meta is not None:`` branch) must also survive the SECOND meta
    write that the untrimmed-miss tail makes (``_promote_finished_conform_
    into_cache`` -> ``_write_cache_meta`` again, without itself knowing the
    duration) -- proving the round-6 explicit-threading fix actually
    prevents the round-5 read-modify-write it replaced from being needed."""
    ffprobe_calls: list[Path] = []

    def counting_probe(path: Path) -> float | None:
        ffprobe_calls.append(path)
        return 3600.0

    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", counting_probe)

    preparer_1 = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    preparer_1.prepare(_untrimmed_plan(tmp_path), _config())
    assert len(ffprobe_calls) == 1

    key = preparer_1._cache_key(tmp_path / "long-recording.mp4", _config())
    assert key is not None
    meta_after_first = preparer_1._read_cache_meta(key)
    assert meta_after_first is not None
    assert meta_after_first["media_duration_seconds"] == 3600.0  # survives the conform-tail's
    # second _write_cache_meta call (the untrimmed-miss branch always writes meta twice: once
    # from the probe itself, again from _promote_finished_conform_into_cache's tail).

    ffprobe_calls.clear()
    preparer_2 = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    preparer_2.prepare(_untrimmed_plan(tmp_path), _config())

    assert ffprobe_calls == []  # zero ffprobes on the second prepare() of the same asset


def _slot_capped_untrimmed_plan(
    source: Path, *, duration_seconds: float, label: str = "segment"
) -> EgressSourcePlan:
    """An "untrimmed" (no inpoint/outpoint) segment whose own duration is
    SHORTER than the asset's real media length -- exactly D42's shape
    (`source_plan.py`'s `_segment_duration`, `min(slot, playable)`): a
    schedule slot shorter than the asset produces this without any
    inpoint/outpoint attached."""
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(label=label, path=str(source), duration_seconds=duration_seconds)
        ],
    )


def test_slot_capped_untrimmed_conform_is_not_promoted_as_full_asset_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-7 (point 1, HIGH BLOCKER fix). Reproduces the reviewer's
    scenario: D42 (`source_plan.py`'s `_segment_duration`, `min(slot,
    playable)`) makes a 30s schedule slot on a 67s untrimmed asset produce a
    30s bounded conform with NO inpoint/outpoint -- `trimmed` reads False
    even though this is only a fragment of the asset. Round-6 hard-linked
    that fragment into the persistent cache as if it were the whole asset
    (`_promote_finished_conform_into_cache`, unconditional on `not trimmed`
    alone); this must no longer happen -- the fragment must never become
    `{key}.ts`, and the real full-asset conform must be warmed behind it
    instead, exactly like a genuinely trimmed miss."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 67.0)
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    warm_jobs: list[Callable[[], None]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,  # never runs -- inspect state before any warm executes
    )

    report = preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=30.0), _config())

    # The segment still airs fine from its own per-plan file...
    seg = report.source_plan.segments[0]
    assert Path(seg.path).is_file()
    # ...but the 30s fragment must NOT have been hard-linked into the
    # persistent cache as if it were the whole 67s asset.
    key = preparer._cache_key(source, _config())
    assert key is not None
    cached_ts = preparer._cache_dir() / f"{key}.ts"
    assert not cached_ts.is_file()  # no fragment ever gets promoted as "the full asset"
    # A real full-asset warm was scheduled behind it instead (same fallback
    # a genuinely trimmed miss already used).
    assert len(warm_jobs) == 1


def test_slot_capped_untrimmed_conform_warms_the_true_full_asset(tmp_path: Path) -> None:
    """Companion to the test above, with a synchronous warm scheduler: once
    the warm-behind job actually runs, it conforms the WHOLE asset (no
    duration truncation -- ``_conform_full_asset_into_cache`` always builds
    with ``segment=None``) and marks the cache entry ``full_asset_conform``
    -- a later, longer-slot request for the same asset can then safely hit
    it (see the read-side test below)."""
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: job(),  # synchronous: runs inline
    )

    preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=30.0), _config())

    key = preparer._cache_key(source, _config())
    assert key is not None
    cached_ts = preparer._cache_dir() / f"{key}.ts"
    assert cached_ts.is_file()  # the warm populated the persistent cache
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta["full_asset_conform"] is True


def test_unknown_media_duration_on_untrimmed_slot_capped_segment_never_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-8 (HIGH fix), mock-level (no real ffmpeg needed):
    reproduces the round-7-vs-round-8 gap without depending on
    ffmpeg/ffprobe being on PATH (the real-ffmpeg suite in
    ``test_preparer_conform_cache_real_ffmpeg.py`` covers the same scenario
    end to end, but skips entirely when ffmpeg is missing, which is exactly
    why this fix had zero coverage on a runner without it).

    ``probe_media_duration_seconds`` is monkeypatched to return ``None`` --
    a genuinely unknown media duration, e.g. ffprobe unavailable/failing for
    this call -- for an untrimmed segment whose own ``duration_seconds`` is
    shorter than a real asset would be (D42's slot-cap shape). ``is_full_
    asset_conform`` must read False here: the bounded conform must fall
    through to ``_schedule_warm`` instead of being hard-linked into the
    cache as if it were the whole asset. Reverting the fix's ``media_
    duration is not None`` clause back to round-7's ``media_duration is
    None or ...`` shape makes this fail: with that clause removed, ``not
    trimmed`` alone is enough and the fragment gets promoted."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: None)
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    warm_jobs: list[Callable[[], None]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner([]),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=warm_jobs.append,  # never runs -- inspect state before any warm executes
    )

    report = preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=30.0), _config())

    # The segment still airs fine from its own per-plan file...
    seg = report.source_plan.segments[0]
    assert Path(seg.path).is_file()
    # ...but with the real duration unknown, nothing may be promoted as "the
    # full asset" from this unverified fragment.
    key = preparer._cache_key(source, _config())
    assert key is not None
    cached_ts = preparer._cache_dir() / f"{key}.ts"
    assert not cached_ts.is_file()  # no fragment ever gets promoted
    meta = preparer._read_cache_meta(key)
    assert meta is not None
    assert meta.get("full_asset_conform") is not True  # never marked as a genuine full conform
    # A real full-asset warm was scheduled behind it instead -- fail closed,
    # never trust the unverified fragment.
    assert len(warm_jobs) == 1


def test_full_asset_cache_hit_requires_the_explicit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-7 (point 1, HIGH BLOCKER fix), read side. A meta file
    whose ``full_asset_conform`` is missing or False -- a legacy entry from
    before this fix, or (defense in depth) any future write that forgets to
    set it -- must never be trusted as the shared full-asset cache: a
    `segment.duration_seconds` vs `media_duration_seconds` numeric
    comparison alone cannot tell a genuinely full conform apart from a short
    one, because `media_duration_seconds` records the ASSET's true length,
    unaffected by whatever the `.ts` on disk actually holds. Plant a SHORT
    `.ts` with a meta that omits the flag (simulating the exact stale-entry
    shape the round-6 bug produced) and prove a later request re-conforms
    instead of trusting it."""
    monkeypatch.setattr(preparer_module, "probe_media_duration_seconds", lambda _path: 67.0)
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: None,
    )
    key = preparer._cache_key(source, _config())
    assert key is not None
    cache_dir = preparer._cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.ts").write_text("only 30s of real content", encoding="utf-8")

    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "loudness_status": "ok",
                "measured_lufs": -24.1,
                "normalized": False,
                "media_duration_seconds": 67.0,
                # no "full_asset_conform" key at all -- the pre-round-7 shape
            }
        ),
        encoding="utf-8",
    )

    report = preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=60.0), _config())

    assert len(calls) == 1  # re-conformed -- the stale entry was never trusted as a HIT
    seg = report.source_plan.segments[0]
    assert "conform-cache" not in seg.path  # its own bounded conform, not the stale cache object


def test_full_asset_cache_hit_trusted_once_flag_is_set(tmp_path: Path) -> None:
    """Positive companion: once a cache entry genuinely IS the whole asset
    (``full_asset_conform`` True), a later, shorter-slot request for the
    SAME asset correctly hits it -- the fix does not disable caching for the
    ordinary (correct) case, only for entries that were never proven full."""
    source = tmp_path / "raw-source.mp4"
    source.write_text("fake media", encoding="utf-8")
    calls: list[list[str]] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls),
        loudness_checker=lambda **_kwargs: _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # simplest path to a genuine full-asset conform
    )
    # First airing: untrimmed MISS on an engine that trims at playout ->
    # _conform_full_asset_into_cache runs directly, always the whole file.
    preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=3600.0), _config())
    assert len(calls) == 1
    calls.clear()

    # A later, shorter-slot request for the same asset.
    report = preparer.prepare(_slot_capped_untrimmed_plan(source, duration_seconds=30.0), _config())

    assert calls == []  # zero ffmpeg work -- a genuine cache HIT
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path


def test_default_warm_scheduler_runs_jobs_in_fifo_order_one_at_a_time(tmp_path: Path) -> None:
    """Item 66, point 4 (round-3 review tightened the assertions): the
    production ``_default_warm_scheduler`` used to spawn one daemon thread
    PER job -- unbounded. It must instead queue jobs onto a single worker:
    3 distinct assets queue 3 jobs, at most 1 ever runs concurrently, AND
    they complete in the order they were queued (``completed == [0, 1, 2]``,
    not merely ``sorted(completed) == [0, 1, 2]`` -- a worker that ran them
    out of order would still pass the weaker assertion). ``max_active`` is
    read under ``guard`` too, matching how it is written."""
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
    with guard:
        assert max_active == 1  # never more than one warm job active at once
    release.set()
    # Give the single worker time to drain the remaining queued jobs.
    deadline = time.monotonic() + 5
    while len(completed) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert completed == [0, 1, 2]  # FIFO order, not just membership
    with guard:
        assert max_active == 1


def test_default_warm_scheduler_survives_a_job_that_raises(tmp_path: Path) -> None:
    """Item 66 round-3, point 5: a job that raises must not stop the
    single worker from draining the rest of the queue -- ``_warm_worker``'s
    own try/except is meant to catch exactly this, but it was never
    exercised by a test."""
    completed: list[int] = []

    def failing_job() -> None:
        completed.append(-1)
        raise RuntimeError("boom")

    def make_ok_job(n: int):
        def _job() -> None:
            completed.append(n)

        return _job

    preparer_module._default_warm_scheduler(failing_job)
    preparer_module._default_warm_scheduler(make_ok_job(1))

    deadline = time.monotonic() + 5
    while len(completed) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert completed == [-1, 1]  # job 2 still ran despite job 1's exception
