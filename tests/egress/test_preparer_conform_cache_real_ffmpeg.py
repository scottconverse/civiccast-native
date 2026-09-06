# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-ffmpeg reproduction of the item 66 round-7 (point 1, HIGH) bug.

The mock-based unit tests in test_preparer.py cover the promotion/cache-hit
GATE logic in isolation, but cannot detect whether a genuinely conformed
downstream segment is actually the length it claims to be. This module runs
``SourcePreparer`` against a real, short lavfi-generated asset and asserts the
prepared output's OWN measured duration -- not just which code path fired.

Skipped when ffmpeg/ffprobe are not on PATH so CI without them stays green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

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

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH — skipping real-ffmpeg integration test.",
)

# Scaled-down analogue of the reviewer's reported field values (30s slot /
# 67s asset / 60s slot): short enough to encode in a couple of seconds,
# while preserving the exact shape that triggers the bug (first slot <
# asset < second slot... no -- second slot must ALSO be <= the real asset
# length, per D42's own min(slot, playable) contract; the bug is that the
# SECOND, LONGER request gets served from the FIRST, SHORTER request's
# wrongly-promoted cache entry).
_ASSET_DURATION_S = 8.0
_FIRST_SLOT_S = 3.0
_SECOND_SLOT_S = 6.0


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        loudness_tolerance_lufs=1.0,
        canonical_profile=CanonicalProfile(width=320, height=240, video_bitrate_kbps=600),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


@pytest.fixture
def real_asset(tmp_path: Path) -> Path:
    """A real, short MP4 with audio -- long enough to distinguish a 3s vs a
    6s conform by actually measuring the output's duration."""
    sample = tmp_path / "asset.mp4"
    result = subprocess.run(
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


def _plan(source: Path, *, duration_seconds: float, label: str) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(label=label, path=str(source), duration_seconds=duration_seconds)
        ],
    )


def test_slot_capped_untrimmed_segment_then_longer_slot_no_dead_air(
    tmp_path: Path, real_asset: Path
) -> None:
    """Item 66 round-7 (point 1, HIGH BLOCKER fix) -- reproduces the
    reviewer's exact scenario end to end with real ffmpeg/ffprobe: a
    schedule slot shorter than its asset (D42) followed by a LONGER slot on
    the SAME asset must never serve the second request's extra seconds from
    the first request's short, wrongly-promoted "full-asset" cache entry.

    Before the round-7 fix: the first (3s) request's bounded conform got
    hard-linked into ``conform-cache/{key}.ts`` as if it WERE the whole
    asset (``not trimmed`` was the only gate). The second (6s) request then
    hit that cache and stream-copied ``-t 6`` from a file that only had ~3s
    of real content -- the actual measured duration of its prepared output
    would be ~3s, not ~6s (dead air/underrun downstream).
    """
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),  # synchronous: any warm completes inline
        playout_trim_supported=False,  # forces the stream-copy-from-cache emit path
    )
    config = _config()

    first = preparer.prepare(
        _plan(real_asset, duration_seconds=_FIRST_SLOT_S, label="first-airing"), config
    )
    first_seg = first.source_plan.segments[0]
    first_measured = probe_media_duration_seconds(Path(first_seg.path))
    assert first_measured is not None
    assert first_measured == pytest.approx(_FIRST_SLOT_S, abs=1.0)

    second = preparer.prepare(
        _plan(real_asset, duration_seconds=_SECOND_SLOT_S, label="second-airing"), config
    )
    second_seg = second.source_plan.segments[0]
    second_measured = probe_media_duration_seconds(Path(second_seg.path))
    assert second_measured is not None
    # The bug: this would measure ~_FIRST_SLOT_S (~3s) instead, because the
    # second request's -c copy -t 6 ran against a cache entry that only ever
    # held ~3s of real content.
    assert second_measured == pytest.approx(_SECOND_SLOT_S, abs=1.0)
    assert second_measured > first_measured + 1.0  # unambiguously longer, not truncated to match


def test_repeated_shorter_slot_still_hits_the_real_full_asset_cache(
    tmp_path: Path, real_asset: Path
) -> None:
    """Positive companion, same real asset: once the true full-asset conform
    is genuinely cached (a longer/full request populates it), a LATER
    shorter-slot request for the same asset still gets served correctly from
    it -- the fix does not disable the cache for the ordinary, correct
    case."""
    calls: list[list[str]] = []

    def counting_runner(args: list[str]):
        calls.append(args)
        return run_ffmpeg(args)

    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=counting_runner,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),
        playout_trim_supported=True,  # simplest path to a genuine, unbounded full-asset conform
    )
    config = _config()

    preparer.prepare(
        _plan(real_asset, duration_seconds=_ASSET_DURATION_S, label="full-airing"), config
    )
    calls.clear()

    report = preparer.prepare(
        _plan(real_asset, duration_seconds=_FIRST_SLOT_S, label="short-airing"), config
    )

    assert calls == []  # zero ffmpeg work -- a genuine cache HIT
    seg = report.source_plan.segments[0]
    assert "conform-cache" in seg.path
