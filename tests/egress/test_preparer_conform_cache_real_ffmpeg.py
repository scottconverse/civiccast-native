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

import json
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


def test_ffprobe_unavailable_never_promotes_a_fragment_as_full_asset(
    tmp_path: Path, real_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 66 round-8 (HIGH fix), repro (a): ffprobe genuinely unavailable
    for a slot-capped untrimmed segment must never let that fragment stand
    in for the whole asset -- round 7's fallback ("media_duration is None
    keeps the pre-round-7 trust-untrimmed-as-full assumption") reasoned that
    D42 can only shorten a segment below the real media length when the
    asset's duration is already KNOWN in the database, so an untrimmed
    segment reaching here with an unknown ``media_duration`` was "never
    capped by D42 to begin with." That is wrong: D42's cap
    (``source_plan.py:523-543``) reads the DB row's duration; the preparer's
    ``media_duration`` here comes from THIS call's own, independently
    fallible, ffprobe -- the two are different sources and can disagree.

    Patches ``probe_media_duration_seconds`` to always return ``None``
    (simulating ffprobe being unavailable for every call in this preparer),
    then requests a short (3s) slot first and a full-length (8s) slot
    second on the same real asset. Before the round-8 fix the first
    request's 3s fragment was promoted directly (``is_full_asset_conform``
    True because ``media_duration is None``); the second request would then
    stream-copy ``-t 8`` from a cache entry that only ever held ~3s of real
    content. After the fix, an unknown duration always routes to
    ``_schedule_warm`` instead (here synchronous, so it completes inline and
    genuinely conforms the whole file) -- the second request must measure
    the full asset duration, not the truncated first-request length.
    """
    monkeypatch.setattr(
        "civiccast.egress.preparer.probe_media_duration_seconds", lambda *_a, **_k: None
    )
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
        _plan(real_asset, duration_seconds=_ASSET_DURATION_S, label="second-airing"), config
    )
    second_seg = second.source_plan.segments[0]
    second_measured = probe_media_duration_seconds(Path(second_seg.path))
    assert second_measured is not None
    # The bug: this would measure ~_FIRST_SLOT_S (~3s), truncated to the
    # wrongly-promoted first fragment, instead of the real ~8s asset.
    assert second_measured == pytest.approx(_ASSET_DURATION_S, abs=1.0)
    assert second_measured > first_measured + 1.0


def test_trimmed_airing_then_slot_capped_untrimmed_does_not_poison_cache(
    tmp_path: Path, real_asset: Path
) -> None:
    """Item 66 round-8 (HIGH fix), repro (b): NO probe failure anywhere.

    A TRIMMED (join-in-progress) airing runs first -- its probe branch
    (``if trimmed:``) never calls ``probe_media_duration_seconds`` at all
    (it seeks/bounds off the segment's own inpoint/outpoint instead), so it
    persists ``media_duration_seconds: null`` via ``_write_cache_meta`` the
    first time this asset's cache key is ever written. A slot-capped
    UNTRIMMED airing of the SAME asset runs second: it takes the
    meta-reuse branch (this asset's loudness was already probed by the
    first airing), reads that cached ``null`` back, and -- before the
    round-8 fix -- promoted ITS OWN bounded fragment as the whole asset
    purely because ``media_duration`` read as ``None``.

    The warm scheduler here QUEUES jobs without draining them (a plain
    list, never invoked) so any fallback warm this round-8 fix schedules
    instead of promoting is deliberately left un-run -- proving the fix
    itself (never promoting on ``media_duration is None``) is what prevents
    the corruption, not an incidental warm racing in to fix it up. A THIRD,
    full-length untrimmed airing of the same asset must then still measure
    the real full duration from its own genuine conform (there is nothing
    valid in the cache to wrongly serve it from), not the second airing's
    shorter slot.
    """
    queued_jobs: list[object] = []
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=queued_jobs.append,  # queued, never drained
        playout_trim_supported=False,  # forces the stream-copy-from-cache emit path
    )
    config = _config()

    trimmed_duration = 4.0
    preparer.prepare(
        _plan(
            real_asset,
            duration_seconds=trimmed_duration,
            label="trimmed-airing",
            inpoint_seconds=0.0,
            outpoint_seconds=trimmed_duration,
        ),
        config,
    )

    second_slot = 6.0
    second = preparer.prepare(
        _plan(real_asset, duration_seconds=second_slot, label="slot-capped-untrimmed-airing"),
        config,
    )
    second_seg = second.source_plan.segments[0]
    second_measured = probe_media_duration_seconds(Path(second_seg.path))
    assert second_measured is not None
    assert second_measured == pytest.approx(second_slot, abs=1.0)

    # A cache entry may or may not exist yet (a queued-but-undrained warm
    # never writes one), but if one somehow does, it must never be trusted
    # as the full asset while it only holds the second airing's short
    # fragment.
    cache_dir = tmp_path / "work" / "conform-cache"
    for meta_path in cache_dir.glob("*.json") if cache_dir.is_dir() else []:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("full_asset_conform") is True:
            ts_path = meta_path.with_suffix(".ts")
            assert probe_media_duration_seconds(ts_path) == pytest.approx(
                _ASSET_DURATION_S, abs=1.0
            ), "a full_asset_conform=True cache entry must genuinely hold the whole asset"

    third = preparer.prepare(
        _plan(real_asset, duration_seconds=_ASSET_DURATION_S, label="full-length-airing"), config
    )
    third_seg = third.source_plan.segments[0]
    third_measured = probe_media_duration_seconds(Path(third_seg.path))
    assert third_measured is not None
    # The bug (pre-round-8): this would measure ~second_slot (~6s), served
    # from the wrongly-promoted second airing's fragment, instead of the
    # real ~8s asset.
    assert third_measured == pytest.approx(_ASSET_DURATION_S, abs=1.0)
    assert third_measured > second_measured + 1.0
