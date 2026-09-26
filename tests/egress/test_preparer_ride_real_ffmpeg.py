# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 answer 12 section 3: the real ride, end to end, through the preparer.

Every other U25 preparer test substitutes ``window_leveler`` with a double: they
prove the *decisions* (which method label is recorded, what is written where,
what happens when the ride refuses) but not that a real ``level_window`` and a
real program mux produce a real program at the level the target asks for.  This
module runs the whole thing -- lavfi asset in, ridden canonical program out --
and asserts on the artifact the station would put on air: its method label, its
length, and its own measured loudness.

**The ride needs an FFmpeg with soxr.**  Its true-peak ceiling is 4x oversampled
through ``aresample=192000:resampler=soxr:precision=28``
(:func:`civiccast.egress.loudness_ride.resample_filter`).  A build without soxr
fails that filter with ``Requested resampling engine is unavailable`` and
``-22 (Invalid argument)`` as soon as the trim stage starts, ``level_window``
raises, and the preparer correctly degrades to loudnorm -- so on such a host this
module would be asserting against the fallback path and proving nothing about
the ride.  It skips instead, on a probe built from the module's own filter
builder so the guard cannot drift from the filter the ride really runs.  The
station's shipped FFmpeg does carry soxr; a stock Windows PATH build may not.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from civiccast.egress import loudness_ride as lr
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparer
from civiccast.stream._ffmpeg import probe_media_duration_seconds, resolve_h264_encoder, run_ffmpeg
from civiccast.stream.loudness import check_streaming_loudness

_TARGET_LUFS = -24.0
_TOLERANCE_LUFS = 1.0
_ASSET_DURATION_S = 8.0
_WINDOW_INPOINT_S = 1.0
_WINDOW_DURATION_S = 4.0
#: A window shorter than the ride's 240 s acceptance window still gates as a
#: whole program: the same measurement the product's own loudness gate makes.
_OVERSAMPLE_HZ = 192_000


def _soxr_available() -> bool:
    """Does the FFmpeg the ride will resolve actually build its oversampler?

    Cheap (0.1 s of lavfi) and run once, at import, because every test here is
    meaningless without it.  The filter string is the module's own.
    """
    probe = subprocess.run(  # fixed argv; the binary is the ride's own resolver
        [
            lr._ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.1",
            "-af",
            lr.resample_filter(_OVERSAMPLE_HZ, lr.RideParams(target_lufs=_TARGET_LUFS)),
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None
    or importlib.util.find_spec("numpy") is None
    or not _soxr_available(),
    reason=(
        "needs ffmpeg+ffprobe+numpy and an FFmpeg built with soxr (the ride's limiter "
        "oversampler); without soxr the ride degrades to loudnorm and this module would "
        "prove nothing about it."
    ),
)


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=_TARGET_LUFS,
        loudness_tolerance_lufs=_TOLERANCE_LUFS,
        canonical_profile=CanonicalProfile(width=320, height=240, video_bitrate_kbps=600),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


@pytest.fixture
def real_asset(tmp_path: Path) -> Path:
    """A short MP4 with real audio, loud enough that the ride has to move it."""
    sample = tmp_path / "asset.mp4"
    result = subprocess.run(  # fixed argv on a lavfi source, into tmp_path
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=15:duration={_ASSET_DURATION_S:g}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={_ASSET_DURATION_S:g}",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(sample),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return sample


def _preparer(work_dir: Path, *, playout_trim_supported: bool) -> SourcePreparer:
    return SourcePreparer(
        work_dir=work_dir,
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),  # synchronous: any warm completes inline
        playout_trim_supported=playout_trim_supported,
    )


def _plan(
    source: Path,
    *,
    duration_seconds: float,
    label: str,
    inpoint_seconds: float | None = None,
    outpoint_seconds: float | None = None,
) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(source),
                duration_seconds=duration_seconds,
                inpoint_seconds=inpoint_seconds,
                outpoint_seconds=outpoint_seconds,
            )
        ],
    )


def _measured_loudness(path: Path) -> float:
    gate = check_streaming_loudness(
        media_path=path, target_lufs=_TARGET_LUFS, tolerance_lufs=_TOLERANCE_LUFS
    )
    assert gate.measured_lufs is not None, gate
    return gate.measured_lufs


def test_a_full_asset_conform_is_ridden_and_lands_on_the_target(
    tmp_path: Path, real_asset: Path
) -> None:
    """The whole-asset path (the conform-cache unit), end to end.

    Before answer 12's wiring this conform was loudnorm's, and the prepared
    program was the source level with a loudnorm offset applied to the average
    -- the case the "every 4-minute stretch" target exists because it gets
    wrong.  What is asserted here is the shipped artifact: the ride recorded on
    the segment AND in the promoted cache entry the next airing will read, the
    asset's real length, and a loudness the product's own gate accepts.
    """
    work = tmp_path / "work"
    report = _preparer(work, playout_trim_supported=True).prepare(
        _plan(real_asset, duration_seconds=_ASSET_DURATION_S, label="full-airing"), _config()
    )

    record = report.records[0]
    assert record.loudness_method == "ride", record
    prepared = Path(report.source_plan.segments[0].path)
    assert prepared.exists()
    measured_duration = probe_media_duration_seconds(prepared)
    assert measured_duration is not None
    assert measured_duration == pytest.approx(_ASSET_DURATION_S, abs=1.0)

    metas = list((work / "conform-cache").glob("*.json"))
    assert metas, "a full-asset conform promotes into the cache"
    promoted = [json.loads(path.read_text(encoding="utf-8")) for path in metas]
    assert [meta["loudness_method"] for meta in promoted if meta.get("full_asset_conform")] == [
        "ride"
    ]

    measured_lufs = _measured_loudness(prepared)
    assert abs(measured_lufs - _TARGET_LUFS) <= _TOLERANCE_LUFS, measured_lufs


def test_a_windowed_conform_is_ridden_and_keeps_the_window_length(
    tmp_path: Path, real_asset: Path
) -> None:
    """The bounded per-segment path, end to end -- and the length it must keep.

    The window here is a join-in-progress airing: 4 s out of the middle of an
    8 s asset.  Its length assertion is a regression guard with a specific
    history: the program mux used to place ``-t`` between its two ``-i``
    operands, where FFmpeg binds it to the SECOND input (the ride's own audio,
    already the window's length) instead of bounding the output.  The source
    video then ran unbounded past the in-point and this 4 s window shipped as a
    7 s program -- 3 s of video with no audio on it -- against 3.97 s of audio.
    ``build_video_from_source_args`` now emits the bound after both inputs.
    """
    work = tmp_path / "work"
    report = _preparer(work, playout_trim_supported=False).prepare(
        _plan(
            real_asset,
            duration_seconds=_WINDOW_DURATION_S,
            label="trimmed-airing",
            inpoint_seconds=_WINDOW_INPOINT_S,
            outpoint_seconds=_WINDOW_INPOINT_S + _WINDOW_DURATION_S,
        ),
        _config(),
    )

    record = report.records[0]
    assert record.loudness_method == "ride", record
    prepared = Path(report.source_plan.segments[0].path)
    assert prepared.exists()
    measured_duration = probe_media_duration_seconds(prepared)
    assert measured_duration is not None
    assert measured_duration == pytest.approx(_WINDOW_DURATION_S, abs=0.5), measured_duration

    measured_lufs = _measured_loudness(prepared)
    assert abs(measured_lufs - _TARGET_LUFS) <= _TOLERANCE_LUFS, measured_lufs
