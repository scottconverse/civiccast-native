# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for egress source preparation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

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


def test_source_preparer_conforms_inside_loudness_tolerance(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=lambda args: (
            captured.setdefault("args", args) and FfmpegResult(returncode=0, stdout="", stderr="")
        ),
        loudness_checker=lambda **kwargs: captured.setdefault("loudness", kwargs) and _loudness(),
        warm_scheduler=lambda job: None,  # keep the at-air behavior deterministic
    )

    report = preparer.prepare(_source_plan(tmp_path), _config())

    assert report.source_plan.channel_id == "gov"
    prepared = report.source_plan.segments[0]
    assert prepared.path.endswith("gov\\prepared\\segment-0001.ts") or prepared.path.endswith(
        "gov/prepared/segment-0001.ts"
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
            captured.setdefault("args", args) and FfmpegResult(returncode=0, stdout="", stderr="")
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
    ).prepare(_untrimmed_plan(tmp_path), _config())
    assert len(calls_1) == 1  # first airing conforms once (into the cache)

    calls_2: list[list[str]] = []
    report = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=_counting_runner(calls_2),
        loudness_checker=lambda **kwargs: probes.append(kwargs) or _loudness(),
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
        playout_trim_supported=True,  # the production-default ffmpeg-concat wiring
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
