# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-media reproduction of the U36 program->program rollover sliver.

``tests/egress/test_source_plan.py`` pins the planner contract with an INJECTED
probe, so it can prove the planner's arithmetic but not that a real asset is
actually the length the planner believes. This module is the same shape against
real media: two short programs built by the same ffmpeg the station uses, whose
DATABASE ROWS claim more media than the files hold (the live shape -- see
``reports/U36.md`` section 1.2), measured with the product's own ffprobe
wrapper ``civiccast.stream._ffmpeg.probe_media_duration_seconds``.

Two things are pinned here:

1. **The plan contract, against real measurements** (tests 1, 2 and 4): a
   rollover plan never airs a segment past the real measured end of its own
   media, and a boundary that lands past that end resolves the NEXT program
   rather than a sliver of the one that just finished. At the pre-fix revision
   the same code produces a single weather segment with ``inpoint=12.0``,
   ``duration=2.0`` against an 8.0s file -- the sliver -- so tests 1 and 2 fail
   there on the plan itself, not on a missing symbol (they never name the
   resolver: they drive the production ``ScheduleSourcePlanProvider`` seam and
   let the default do the work).

2. **What the engine was actually handed** (tests 3 and 4): the prepared artifact,
   produced by ``SourcePreparer`` with the production
   ``playout_trim_supported=False`` (``cli.py:1226`` / ``automation.py:2657``:
   ``not gstreamer_engine_selected()``) for a window that runs past the media
   end. The copy-out cannot manufacture media that does not exist, so the
   artifact is SHORTER than the plan promises -- while the emitted segment keeps
   the plan's promised ``duration_seconds``. That is the exact lie the single-leg
   pipeline was handed: a plan promising 5.0s over a 3.0s artifact.

   An in-point past the media's end used to hand the worker something worse than
   short: a ZERO-BYTE file, still reported as a 2.0s segment. U36 item 7's
   emission-time rejection now refuses to emit it at all -- and this module's
   real media is where that guard has to bite, because the 0-byte artifact it
   rejects is the one this host's ffmpeg actually produces for that window, not
   a fixture. Both halves are pinned below.

Skipped when ffmpeg/ffprobe are not on PATH, matching
``test_preparer_conform_cache_real_ffmpeg.py``. The GStreamer half of the
reproduction (a real worker reaching EOS and exiting) needs the packaged
GStreamer runtime and a ``gi`` build, neither of which exists in this
environment -- see ``reports/U36.md`` section 2 for that environmental gap.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparer
from civiccast.egress.source_plan import (
    SCHEDULE_GAP_ABSORB_SECONDS,
    ScheduleSourcePlanProvider,
)
from civiccast.schedule.models import ScheduleItemResponse, StaffAssetRow
from civiccast.stream._ffmpeg import (
    probe_media_duration_seconds,
    resolve_h264_encoder,
    run_ffmpeg,
)
from civiccast.stream.loudness import check_streaming_loudness

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH — skipping real-ffmpeg integration test.",
)

# The live shape, scaled to something ffmpeg builds in a couple of seconds: the
# rows claim 6.0s more media than the file holds (the 13:57:02 rollover's plan
# end lay ~6.5s past the real end and the 14:06:50 one 3.65s), and the schedule
# slot is longer than BOTH, so the slot is not the cap -- the row is.
_REAL_MEDIA_S = 8.0
_RECORDED_S = 14.0
_SLOT_S = 30
# The boundary instant, in seconds after the first program's start. It is
# inside the RECORDED slot (which runs to 30s) and past the media's real end
# (8.0s) -- exactly where the 14:17:52 relaunch landed.
_BOUNDARY_S = 12.0
# The next program's start offset. Inside SCHEDULE_GAP_ABSORB_SECONDS (30s) of
# the boundary, so the U26 absorb hands the boundary to it.
_SECOND_START_S = 30.0
_SECOND_REAL_MEDIA_S = 12.0
_START = datetime(2026, 9, 25, 14, 6, 41, tzinfo=UTC)
_FIRST = "weather"
_SECOND = "council"


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


def _real_asset(tmp_path: Path, *, name: str, seconds: float) -> Path:
    """A real MP4 with audio, of a length ffprobe reports honestly."""

    sample = tmp_path / name
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=15:duration={seconds:g}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds:g}",
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
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return sample


def _row(path: Path, *, asset_id: str, title: str, recorded_seconds: float) -> StaffAssetRow:
    """The asset row a station would hold for this media.

    No trim window: the planner's cap is then the row's ``duration_seconds``
    alone, which is the lie under test. ``recorded_seconds``
    (``_RECORDED_S``) is deliberately longer than the file.
    """

    return StaffAssetRow(
        asset_id=asset_id,
        title=title,
        state="validated",
        file_path=str(path),
        duration_seconds=recorded_seconds,
        trim_in_seconds=None,
        trim_out_seconds=None,
    )


def _item(asset_id: str, *, title: str, start_offset_s: float) -> ScheduleItemResponse:
    return ScheduleItemResponse(
        id=uuid4(),
        asset_id=asset_id,
        asset_title=title,
        channel_id="gov",
        mode="premiere",
        state="published",
        scheduled_at=_START + timedelta(seconds=start_offset_s),
        duration_seconds=int(_SLOT_S),
        notes=None,
        created_at=_START - timedelta(days=1),
    )


def _two_programs(tmp_path: Path) -> tuple[list[ScheduleItemResponse], dict[str, StaffAssetRow]]:
    first_media = _real_asset(tmp_path, name=f"{_FIRST}.mp4", seconds=_REAL_MEDIA_S)
    second_media = _real_asset(tmp_path, name=f"{_SECOND}.mp4", seconds=_SECOND_REAL_MEDIA_S)
    items = [
        _item(_FIRST, title="Weather Report", start_offset_s=0.0),
        _item(_SECOND, title="City Council", start_offset_s=_SECOND_START_S),
    ]
    assets = {
        _FIRST: _row(
            first_media, asset_id=_FIRST, title="Weather Report", recorded_seconds=_RECORDED_S
        ),
        _SECOND: _row(
            second_media,
            asset_id=_SECOND,
            title="City Council",
            recorded_seconds=_SECOND_REAL_MEDIA_S,
        ),
    }
    return items, assets


def _provider(
    items: list[ScheduleItemResponse], assets: dict[str, StaffAssetRow]
) -> ScheduleSourcePlanProvider:
    """The PRODUCTION shape, with no probe injected.

    ``max_segments=1`` is what ``automation.py:2628`` / ``cli.py:1150`` build
    when the GStreamer engine is selected -- one leg per plan, so the leg's own
    EOS is the pipeline's EOS. Nothing is passed for the media probe: whether
    the planner measures the media at all is precisely what is under test.
    """

    return ScheduleSourcePlanProvider(
        schedule_items_provider=lambda _channel_id: list(items),
        asset_resolver=assets.get,
        max_segments=1,
        gap_absorb_seconds=SCHEDULE_GAP_ABSORB_SECONDS,
    )


def test_u36_a_real_asset_is_never_planned_past_its_own_measured_end(tmp_path: Path) -> None:
    """A plan built at a program's own start must not air more than the file.

    Pre-fix this fails: the segment's ``duration_seconds`` is the ROW's 14.0
    against an 8.0s file. Post-fix the planner measures the file, so the
    segment is the media's real length.
    """

    items, assets = _two_programs(tmp_path)
    measured = probe_media_duration_seconds(Path(assets[_FIRST].file_path))
    assert measured is not None
    assert measured == pytest.approx(_REAL_MEDIA_S, abs=0.2)

    plan = _provider(items, assets).plan_at("gov", _START)

    assert [segment.source_ref for segment in plan.segments] == [_FIRST]
    segment = plan.segments[0]
    inpoint = segment.inpoint_seconds or 0.0
    assert inpoint + segment.duration_seconds <= measured + 0.05, (
        f"segment {segment.label!r} airs to {inpoint + segment.duration_seconds}s "
        f"of a {measured}s file"
    )
    assert segment.duration_seconds == pytest.approx(_REAL_MEDIA_S, abs=0.2)


def test_u36_a_real_rollover_past_the_end_resolves_the_next_program(tmp_path: Path) -> None:
    """The defect's own instant: the boundary lands past the media's real end.

    Pre-fix this is the sliver -- one segment of the SAME program, starting
    12.0s into an 8.0s file for a promised 2.0s. Post-fix the first program is
    recognised as exhausted and the U26 gap-absorb hands the boundary to the
    next contiguous program, which starts from its own beginning.
    """

    items, assets = _two_programs(tmp_path)
    plan = _provider(items, assets).plan_at("gov", _START + timedelta(seconds=_BOUNDARY_S))

    assert [segment.source_ref for segment in plan.segments] == [_SECOND]
    segment = plan.segments[0]
    measured = probe_media_duration_seconds(Path(assets[_SECOND].file_path))
    assert measured is not None
    assert segment.inpoint_seconds in (None, 0.0)
    assert segment.duration_seconds == pytest.approx(measured, abs=0.2)


def _sliver_plan(media: Path, *, inpoint_s: float, promised_s: float) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="sliver",
                path=str(media),
                duration_seconds=promised_s,
                inpoint_seconds=inpoint_s,
                outpoint_seconds=None,
            )
        ],
    )


def _sliver_preparer(tmp_path: Path) -> SourcePreparer:
    return SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),  # synchronous: any warm completes inline
        playout_trim_supported=False,  # the GStreamer engine's value
    )


def test_u36_the_prepared_sliver_is_shorter_than_the_window_it_promises(tmp_path: Path) -> None:
    """A window reaching past the media end emits a SHORT but real artifact.

    Inside the media but asking for more than remains: the copy-out yields the
    tail that exists -- the 3.0s left of an 8.0s file -- not the promised 5.0s.
    The exact figure lands within a keyframe interval of 3.0s (this host measured
    3.097122s and 3.203789s on two builds), so the assertion brackets it rather
    than pinning one frame layout.

    This is also the guard's lower bound on real media: a segment that is merely
    SHORT is real media and must still be prepared. U36 item 7 rejects only a
    positively stream-less artifact, and a regression that widened it to
    "shorter than promised" would fail here.
    """

    media = _real_asset(tmp_path, name="asset.mp4", seconds=_REAL_MEDIA_S)
    preparer = _sliver_preparer(tmp_path)
    report = preparer.prepare(_sliver_plan(media, inpoint_s=5.0, promised_s=5.0), _config())

    segment = report.source_plan.segments[0]
    artifact = Path(segment.path)
    measured = probe_media_duration_seconds(artifact)

    # The emitted segment still claims the planner's promise, whatever the file
    # turned out to be -- the engine is told the plan's duration, not the
    # artifact's.
    assert segment.duration_seconds == 5.0
    assert measured is not None
    assert measured == pytest.approx(3.0, abs=0.5)
    # The artifact cannot fill the window the plan promised.
    assert measured + 0.5 < 5.0, f"artifact measured {measured}s against a promised 5.0s"


def test_u36_a_window_past_the_media_end_never_reaches_the_worker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The past-EOF window is refused at preparation, naming source and in-point.

    Past the real end the copy-out produces NOTHING at all. Measured on this
    host's ffmpeg 8.1.1 through the preparer's own args: a 0-byte .ts, ffprobe
    answering None. Before U36 item 7's guard that empty file was handed on as a
    2.0s segment -- exactly the artifact the GStreamer worker EOS'd on when the
    boundary reload's single leg delivered 1.6s (``reports/U36.md`` 1.4). Now
    ``prepare`` raises instead, so the caller's own failure handling runs
    instead of the worker's stall exit, and the operator gets a WARNING naming
    the source and the in-point rather than a channel that went dark.
    """

    media = _real_asset(tmp_path, name="asset.mp4", seconds=_REAL_MEDIA_S)
    preparer = _sliver_preparer(tmp_path)

    with (
        caplog.at_level(logging.WARNING, logger="civiccast.egress.preparer"),
        pytest.raises(SourcePrepareError) as raised,
    ):
        preparer.prepare(_sliver_plan(media, inpoint_s=12.0, promised_s=2.0), _config())

    message = str(raised.value)
    assert "0 bytes" in message, message
    assert "12.000s" in message, message  # the in-point is named
    assert str(media) in message, message  # and so is the source

    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert any(
        str(media) in line and "12.000s" in line and "0 bytes" in line for line in warnings
    ), f"no warning named the source, the in-point and the 0-byte artifact: {warnings}"


def test_u36_the_fixed_plan_and_the_artifact_it_produces_agree(tmp_path: Path) -> None:
    """The other half of the loop: post-fix, promise and artifact match.

    The boundary resolves the next program (test 2); preparing THAT segment
    yields an artifact whose own measured length is the length the plan
    promised, for both a fresh start and a join in progress.
    """

    items, assets = _two_programs(tmp_path)
    provider = _provider(items, assets)
    preparer = SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),
        playout_trim_supported=False,
    )

    for when, expected_source in (
        (_START + timedelta(seconds=_BOUNDARY_S), _SECOND),  # the defect's instant
        (_START + timedelta(seconds=_SECOND_START_S + 4.0), _SECOND),  # join in progress
    ):
        plan = provider.plan_at("gov", when)
        assert [segment.source_ref for segment in plan.segments] == [expected_source]

        report = preparer.prepare(plan, _config())
        for segment in report.source_plan.segments:
            measured = probe_media_duration_seconds(Path(segment.path))
            assert measured is not None
            # The artifact fills the promise: it is not short by more than a
            # keyframe interval, and never empty.
            assert segment.duration_seconds - measured <= 0.5, (
                f"{segment.label!r} promised {segment.duration_seconds}s "
                f"but the artifact measures {measured}s"
            )
            assert measured > 0.5
