# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-worker proof of U53 item 1: a filler rollover chains the next programme.

``tests/egress/test_daemon.py::test_filler_rollover_chains_the_next_program_into_the_same_plan``
pins the PLAN SHAPE hermetically (its provider is a stub, its preparer is a
recorder). That test can prove the daemon hands the strategy one plan whose
segments are ``[filler, programme]``; it cannot prove that the filler's trimmed
duration is what a real worker actually AIRS, nor that the chained programme
reaches the mux at the scheduled instant with nothing in between. This module is
the same claim against the real GStreamer worker, real media, and the production
preparer -- the U53 item 6 reproduction the brief asks for:

    a filler rollover followed by the next programme, where the programme airs
    at its due time and the filler never airs whole.

The claim is read off the emitted transport stream itself, not off the daemon's
bookkeeping:

* exactly ONE silent run, of the gap's own length, and it starts where the
  outgoing programme's slot ends -- the slate airs for the gap, not for its own
  declared fill;
* audio at 4 kHz after that run where the first programme sat at 200 Hz -- the
  chained programme really is the NEXT programme, not a re-air of the first;
* a total duration equal to ``first slot + gap + second slot`` -- one plan's
  worth of media, so there is no second slate and no second rollover behind it;
* exactly ONE worker spawn -- the deferred reload reused the running worker, so
  the hand-off is the seamless in-worker leg swap and not a restart.

Skipped when ffmpeg/ffprobe are not on PATH, and skipped again when no packaged
GStreamer runtime is reachable from THIS interpreter (point
``CIVICAST_GSTREAMER_RUNTIME_ROOT`` at the install's ``runtime`` directory; the
probe is ``test_gst_engine_wsl._wsl_gi_available``). The daemon/real-worker
harness itself is IMPORTED from ``test_u47_slate_first_real_worker`` rather than
copied here -- that module owns the pipe channel, the paced filesink and the
launcher, and a second copy of it would drift.

Timing note (recorded, not asserted): the daemon's deferred switch commits at
the OUTGOING leg's own media EOS, so the wall-clock instant a plan takes air is
the worker's real start, not the nominal schedule anchor. The gap the filler is
trimmed to is measured from the recorded rollover horizon, which this test sets
from the wall clock at arm time, so the two agree to within the tick latency
(printed below). That is why the shape assertions read the emitted media's own
timeline and never the wall clock.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.gst import strategy as strategy_mod
from civiccast.egress.gst.strategy import GstPlayoutStrategy
from civiccast.egress.models import (
    CanonicalProfile,
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
)
from civiccast.egress.source_plan import ScheduleSourcePlanProvider, SlateSourceGenerator
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.models import ScheduleItemResponse, StaffAssetRow
from civiccast.stream._ffmpeg import (
    probe_media_duration_seconds,
    resolve_h264_encoder,
    run_ffmpeg,
)

# The native line's own live suite supplies the worker harness; u36's supplies the
# real-media and production-preparer helpers; u47 owns the daemon+real-worker
# harness (worker launcher, D2 pipe channel, paced filesink) this module borrows
# rather than re-implements.
from tests.egress import test_gst_engine_wsl as native
from tests.egress import test_u36_rollover_sliver_real_ffmpeg as u36
from tests.egress.test_u47_slate_first_real_worker import _Harness, _PreparerObserver

_LIVE_WORKER_AVAILABLE = native._wsl_gi_available()

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH — skipping real-worker integration test.",
)

# A channel id no station profile can collide with: the pipe name is derived from
# it (``strategy.py``'s per-spawn ``WindowsWorkerPipeServer``), and
# ``FILE_FLAG_FIRST_PIPE_INSTANCE`` makes a collision a hard failure, not a
# shared channel.
_CHANNEL = "u53chainrollover"

# The daemon writes ``source_plan.segments[0].label`` into the state row. The
# programme labels come from the asset row's title (``source_plan.py:1024``); the
# slate generator hard-codes its own (``source_plan.py``'s ``SlateSourceGenerator``).
_FIRST_TITLE = "City Council"
_SECOND_TITLE = "Education Board"
_SLATE_LABEL = "CivicCast slate"
_FIRST_ASSET_ID = "u53-first"
_SECOND_ASSET_ID = "u53-second"

# Media length == slot length for both programmes: the planner's cap is
# ``min(slot, media)`` (``_segment_duration``), so equal lengths make each plan
# segment's declared duration exactly its slot and remove the trim-window
# question from the shape under test. The equality is ASSERTED against the real
# probe below, so a short encode fails this test rather than silently changing
# what it measures.
_FIRST_SLOT_S = 60
_SECOND_SLOT_S = 20

# The gap the filler must fill: nothing is due at the rollover horizon, and the
# next programme is due 12s later. 12s is comfortably larger than the planner's
# 1s slot tolerance, so "the filler aired for the gap" cannot be confused with a
# rounding difference, and comfortably smaller than the slate's declared fill
# (below), so the trim has to actually happen.
_GAP_S = 12.0

# ``duration == target_fill`` keeps ``repeats == 1``, so the rendered slate is ONE
# file declared at 20s (the U27 shape) that the chain trims to the 12s gap. If the
# trim were skipped the slate would air 8s too long and the programme would land
# 8s late -- which is exactly what the emitted-media assertions catch.
_SLATE_RENDER_S = 20
_SLATE_FILL_S = 20

# The tones that tell the two programmes apart in the emitted stream. 200Hz and
# 4kHz are four octaves apart, and two cascaded 1kHz high-pass stages (24 dB/oct
# total) attenuate the low tone by ~56 dB while passing the high one unchanged --
# so a mean-volume difference of tens of dB is the signature of "a different
# programme is playing", where a single 6 dB/oct stage would be ambiguous.
_FIRST_TONE_HZ = 200.0
_SECOND_TONE_HZ = 4000.0
_TONE_HPF = "highpass=f=1000,highpass=f=1000"
# The asserted separation. The measured figure is tens of dB; this is the floor
# that still cannot be reached by the same tone at any sane gain.
_TONE_SEPARATION_DB = 20.0

# Ceilings for steps whose cost is a real process start (python + ``import gi`` +
# Gst.init + graph build + preroll + a conform) on a dev box.
_STEP_WAIT_S = 150.0
# Wall time to keep ticking after the reload settles, so the chained programme
# has fully aired before the emitted file is copied. gap + programme slot + tail.
_POST_SETTLE_S = _GAP_S + _SECOND_SLOT_S + 8.0

# ``silencedetect``'s threshold: the slate is ``anullsrc`` (true digital silence,
# ``source_plan.py``'s slate args) while both programmes carry a normalized sine,
# so -50 dB separates them by a wide margin. The 0.5s minimum run keeps the
# mux's own sub-second discontinuities at a handover out of the result.
_SILENCE_NOISE = "-50dB"
_SILENCE_MIN_S = 0.5


class _RecordingStrategy(GstPlayoutStrategy):
    """The production strategy, with each reload request kept for the assertions.

    The request is the daemon's own hand-off to the engine: its
    ``switch_at_end_of_current`` is what makes the switch DEFERRED (the reload is
    armed while the outgoing leg still airs), and its segments are the chained
    plan. Reading them here is how this test knows the daemon chose the chained
    shape rather than falling back to a restart with a filler-only plan.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.reloads: list[dict[str, Any]] = []

    def reload_content(
        self,
        channel_id: str,
        work_dir: Path,
        request: Any,
        *,
        command_id: str | None = None,
    ) -> bool:
        plan = request.source_plan
        self.reloads.append(
            {
                "switch_at_end_of_current": bool(request.switch_at_end_of_current),
                "segments": [
                    (segment.kind, float(segment.duration_seconds)) for segment in plan.segments
                ],
                "labels": [segment.label for segment in plan.segments],
            }
        )
        return super().reload_content(channel_id, work_dir, request, command_id=command_id)


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id=_CHANNEL,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        loudness_tolerance_lufs=1.0,
        canonical_profile=CanonicalProfile(width=320, height=240, video_bitrate_kbps=600),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _asset(tmp_path: Path, *, name: str, seconds: float, frequency: float) -> Path:
    """A real MP4 of a known length whose audio is a single, known tone.

    ``u36._real_asset`` hard-codes ``sine=frequency=440``, and this test's whole
    discrimination between the two programmes is the tone's frequency, so the
    asset builder is its own here rather than u36's.
    """

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
            f"sine=frequency={frequency:g}:duration={seconds:g}",
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
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return sample


def _item(
    title: str,
    *,
    asset_id: str,
    scheduled_at: datetime,
    slot_seconds: int,
) -> ScheduleItemResponse:
    """One due programme.

    Built here rather than reused from u36 because u36's ``_item`` hard-codes
    ``channel_id="gov"``, and this test must not touch a production channel id.
    """

    return ScheduleItemResponse(
        id=uuid4(),
        asset_id=asset_id,
        asset_title=title,
        channel_id=_CHANNEL,
        mode="premiere",
        state="published",
        scheduled_at=scheduled_at,
        duration_seconds=slot_seconds,
        notes=None,
        created_at=scheduled_at - timedelta(days=1),
    )


def _tick_until(
    daemon: EgressDaemon,
    predicate: Any,
    *,
    timeout: float,
    label: str,
) -> float:
    """Tick the real daemon until ``predicate`` holds; return the elapsed seconds.

    Same shape as u47's helper, with THIS module's channel id (that one is
    module-private and hard-codes its own).
    """

    started = time.monotonic()
    deadline = started + timeout
    while True:
        if predicate():
            return time.monotonic() - started
        if time.monotonic() >= deadline:
            raise AssertionError(f"{label}: not satisfied within {timeout:.1f}s")
        daemon.process_once(_CHANNEL)
        time.sleep(0.05)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _on_air(store: InMemoryEgressStore, ts: Path) -> Any:
    def ready() -> bool:
        row = store.read_state(_CHANNEL)
        return row is not None and row.state == "ON_AIR" and _size(ts) > 0

    return ready


def _reload_result(work_dir: Path) -> str | None:
    """The worker's own terminal receipt for the armed reload.

    ``worker.py``'s ``_write_reload_status`` writes ``<work>/<channel>/reload-status.json``
    when the engine settles the switch; ``daemon._poll_reload_settlement`` reads
    the same file. ``"applied"`` therefore means the engine COMMITTED the new leg
    -- not merely that the command was accepted.
    """

    try:
        payload = json.loads((work_dir / _CHANNEL / "reload-status.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    result = payload.get("result")
    return result if isinstance(result, str) else None


# ---- emitted-media analysis -------------------------------------------------------


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return float(result.stdout.strip())


def _silence_runs(path: Path) -> list[tuple[float, float]]:
    """Every closed silent run, as (start, end) media seconds."""

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={_SILENCE_NOISE}:d={_SILENCE_MIN_S}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    starts = [float(value) for value in re.findall(r"silence_start: (-?[\d.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: (-?[\d.]+)", result.stderr)]
    # A run still open at EOF reports a start with no end; this test expects none,
    # and silently dropping it would hide exactly that.
    assert len(starts) == len(ends), (starts, ends)
    return list(zip(starts, ends, strict=True))


def _mean_volume_db(path: Path, *, start: float, length: float) -> float:
    """Mean volume of one window after ``_TONE_HPF``, in dBFS (``-inf`` if silent).

    Seek and duration are placed AFTER ``-i``: an input seek would snap to a
    video keyframe and could land the window in the wrong programme.
    """

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-ss",
            f"{start:g}",
            "-t",
            f"{length:g}",
            "-af",
            f"{_TONE_HPF},volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", result.stderr)
    assert match is not None, result.stderr[-2000:]
    raw = match.group(1)
    return float("-inf") if raw == "-inf" else float(raw)


def test_u53_a_filler_rollover_airs_the_next_programme_with_no_second_slate(
    tmp_path: Path,
) -> None:
    """The whole rule, end to end, on real workers."""

    if not _LIVE_WORKER_AVAILABLE:
        pytest.skip("no packaged GStreamer runtime reachable from this interpreter")

    harness = _Harness(tmp_path)
    # A caption tap would add an appsink to the audio path; deleting the knob makes
    # the strategy's ``_with_audio_tap`` a deterministic no-op.
    monkey = pytest.MonkeyPatch()
    monkey.delenv("CIVICAST_CAPTION_TAP_DIR", raising=False)
    monkey.setattr(strategy_mod, "graph_from_config", harness.build_graph)
    monkey.setattr(strategy_mod, "subprocess", harness.recorder)

    first_media = _asset(
        tmp_path, name="first.mp4", seconds=_FIRST_SLOT_S, frequency=_FIRST_TONE_HZ
    )
    second_media = _asset(
        tmp_path, name="second.mp4", seconds=_SECOND_SLOT_S, frequency=_SECOND_TONE_HZ
    )
    # The premise the whole shape rests on: the planner caps a segment by BOTH the
    # slot and the media, so media shorter than its slot would silently shorten the
    # plan and move the boundary this test arms against.
    for media, slot in ((first_media, _FIRST_SLOT_S), (second_media, _SECOND_SLOT_S)):
        measured = probe_media_duration_seconds(media)
        assert measured is not None and measured >= slot - 0.5, (media, measured, slot)

    # The schedule, driven by a fixed anchor so the initial plan is resolved by the
    # schedule rather than by the wall clock. ``items`` is deliberately MUTABLE and
    # the provider reads it through a closure: the second programme is appended at
    # arm time, when its due instant is known relative to the real airing.
    anchor = datetime.now(UTC)
    items: list[ScheduleItemResponse] = [
        _item(
            _FIRST_TITLE,
            asset_id=_FIRST_ASSET_ID,
            scheduled_at=anchor,
            slot_seconds=_FIRST_SLOT_S,
        )
    ]
    assets: dict[str, StaffAssetRow] = {
        _FIRST_ASSET_ID: u36._row(
            first_media,
            asset_id=_FIRST_ASSET_ID,
            title=_FIRST_TITLE,
            recorded_seconds=_FIRST_SLOT_S,
        ),
        _SECOND_ASSET_ID: u36._row(
            second_media,
            asset_id=_SECOND_ASSET_ID,
            title=_SECOND_TITLE,
            recorded_seconds=_SECOND_SLOT_S,
        ),
    }
    provider = ScheduleSourcePlanProvider(
        schedule_items_provider=lambda _channel_id: items,
        asset_resolver=assets.get,
        now_provider=lambda: anchor,
        # The GStreamer engine's production shape: one leg per plan.
        max_segments=1,
        # Deliberately NOT ``SCHEDULE_GAP_ABSORB_SECONDS`` (30s): the gap under test
        # is 12s, and the absorb window would hand the boundary straight to the next
        # programme, which is the OTHER design (U26) rather than the one under test.
    )

    store = InMemoryEgressStore()
    config = _config()
    store.upsert_config(config)

    harness_preparer = u36._sliver_preparer(tmp_path)
    # The daemon calls ``source_preparer`` as a FUNCTION, not as a ``SourcePreparer``
    # method (``_drive_preparation``'s sync branch: ``preparer(request.plan,
    # request.config)``), so the production preparer needs a callable around it. u47's
    # observer is that callable and is used UNARMED here, where it simply delegates --
    # no hold, because this test runs the reload inline (no executor).
    preparer = _PreparerObserver(harness_preparer)
    slate = SlateSourceGenerator(
        work_dir=tmp_path / "slate",
        duration_seconds=_SLATE_RENDER_S,
        target_fill_seconds=_SLATE_FILL_S,
        ffmpeg_runner=run_ffmpeg,
    )
    strategy = _RecordingStrategy(
        worker_launcher=harness.worker_launcher,
        pipe_channel_factory=harness.pipe_channel,
        is_windows=True,
        embed_captions=False,
        # Explicit rather than env-derived: without the seamless path the hand-off
        # has no route to hand the chained plan in at all.
        supports_content_reload=True,
    )
    work_dir = tmp_path / "daemon-work"
    daemon = EgressDaemon(
        store,
        # NOT ``tmp_path/"work"``: that is the path u36's ``_sliver_preparer``
        # already hands the preparer.
        work_dir=work_dir,
        source_plan_provider=provider,
        # Both providers are the SAME object: the chain needs ``plan_at`` for the
        # programme due at the gap and ``next_item_start_at`` to measure the gap.
        boundary_source_plan_provider=provider.plan_at,
        next_program_start_provider=provider.next_item_start_at,
        fallback_source_provider=lambda _config: slate(_config),
        source_preparer=preparer,
        async_source_preparer=preparer,
        encoder_strategy=strategy,
    )
    harness.daemon = daemon
    harness.observer = preparer
    # Deliberately NOT ``enable_async_preparation()``: with no executor the daemon
    # runs the whole reload preparation inline on this thread, so one tick both
    # arms the reload and returns -- no hold to synchronize, no observer needed.

    # The harness's ``build_graph`` names the sink by the plan's first segment kind,
    # so the initial (programme) graph writes here. The reload graph's own sink name
    # does not matter: the engine swaps only the PROGRAM LEG (``reload_program``) and
    # leaves its live sink running, so every emitted byte of this run lands in this
    # one file.
    program_ts = tmp_path / "program.ts"

    applied_s = 0.0
    switch_wait_s = 0.0
    try:
        # ---- 1. the channel goes ON AIR on the first programme -----------------------
        store.enqueue_command(
            EgressCommand(
                channel_id=_CHANNEL,
                action="start",
                issued_at=datetime.now(UTC),
                issued_by="u53-test",
                command_id=f"u53-{uuid4().hex}",
            )
        )
        _tick_until(
            daemon,
            _on_air(store, program_ts),
            timeout=_STEP_WAIT_S,
            label="the first programme airing (cold start)",
        )
        row = store.read_state(_CHANNEL)
        assert row is not None and row.state == "ON_AIR", row
        assert row.current_source_label == _FIRST_TITLE, row

        # ---- 2. the boundary this rollover fills -------------------------------------
        # The deferred switch fires at the OUTGOING LEG's own EOS, which is
        # ``_FIRST_SLOT_S`` of media after the worker reached PLAYING -- i.e. from
        # here. The horizon recorded below is the same instant, so the filler's
        # trimmed length and the leg's real end agree to within the tick latency.
        boundary_at = datetime.now(UTC) + timedelta(seconds=_FIRST_SLOT_S)
        items.append(
            _item(
                _SECOND_TITLE,
                asset_id=_SECOND_ASSET_ID,
                scheduled_at=boundary_at + timedelta(seconds=_GAP_S),
                slot_seconds=_SECOND_SLOT_S,
            )
        )
        command_id = f"u53-rollover-{uuid4().hex}"
        daemon.record_rollover_plan_end(
            _CHANNEL,
            boundary_at,
            command_id=command_id,
            # The live trigger: automation sets this when its boundary resolves to
            # filler, and it is what routes the reload through the chain.
            force_fallback=True,
        )
        store.enqueue_command(
            EgressCommand(
                channel_id=_CHANNEL,
                action="reload",
                issued_at=datetime.now(UTC),
                issued_by="u53-test",
                command_id=command_id,
            )
        )
        armed_at = time.monotonic()

        # Two separate receipts, and the tick waits for BOTH: the worker writes its
        # status the moment the engine settles the switch, while the daemon commits
        # its own state row on the NEXT tick after reading it. Waiting only on the
        # file would race the commit.
        def _settled() -> bool:
            row = store.read_state(_CHANNEL)
            return (
                _reload_result(work_dir) == "applied"
                and row is not None
                and row.state == "FALLBACK_SLATE"
            )

        # ---- 3. the reload is armed, then COMMITS at the outgoing leg's EOS ---------
        _tick_until(
            daemon,
            _settled,
            timeout=_STEP_WAIT_S,
            label="the content reload settling",
        )
        applied_s = time.monotonic() - armed_at
        assert _reload_result(work_dir) == "applied", _reload_result(work_dir)
        switch_wait_s = boundary_at.timestamp() - datetime.now(UTC).timestamp()

        row = store.read_state(_CHANNEL)
        assert row is not None and row.state == "FALLBACK_SLATE", row
        assert row.current_source_label == _SLATE_LABEL, row

        # ---- 4. let the chained programme air out ----------------------------------
        settled_at = time.monotonic()
        _tick_until(
            daemon,
            lambda: time.monotonic() - settled_at >= _POST_SETTLE_S,
            timeout=_STEP_WAIT_S,
            label="the chained programme airing out",
        )
    finally:
        # Teardown FIRST: the copy below must not race a live filesink, and on
        # Windows a plain ``copyfile`` of a file another process holds open for
        # writing is a sharing violation, not a read.
        harness.shutdown()
        monkey.undo()

    # ---- 5. what the emitted stream actually airs -------------------------------------
    emitted = tmp_path / "emitted-copy.ts"
    shutil.copyfile(program_ts, emitted)
    duration = _probe_duration(emitted)
    # Runs under a second are the mux's own handover gaps, not a slate: the filler
    # is 12s, so filtering at 1s cannot hide a second slate -- it only keeps a
    # sub-second encoder gap at a leg boundary from reading as one.
    silences = [run for run in _silence_runs(emitted) if run[1] - run[0] >= 1.0]

    # The chained plan's media ends at first slot + gap + second slot. Anything past
    # that is the worker's post-EOS hold -- U41: the worker stays up on the last plan
    # rather than exiting, so the mux keeps writing silence while the harness has
    # nothing to hand off to. That hold is a silent run reaching EOF, so its START is
    # where the chained programme's audio ends, and the file's own duration is NOT
    # that instant (it is the moment this test stopped ticking).
    holds = [run for run in silences if abs(run[1] - duration) <= 0.5]
    assert len(holds) <= 1, holds
    content_end = holds[0][0] if holds else duration
    within = [run for run in silences if run[0] < content_end - 0.5]
    assert len(within) == 1, (
        f"expected exactly one silent run INSIDE the plan's own media (the filler); saw "
        f"{within} (all runs {silences}, content ends at {content_end:.2f}s). A second "
        f"run is a second filler -- the pre-U53 shape, where the filler airs whole and "
        f"the programme needs its own rollover to follow it."
    )
    filler_start, filler_end = within[0]
    filler_seconds = filler_end - filler_start

    # Windows well inside each region, so the tone probes cannot be moved by the
    # mux's own sub-second boundary behaviour: the first programme's tail, the
    # filler itself, the chained programme's body, and its own last seconds.
    first_tone = _mean_volume_db(emitted, start=max(1.0, filler_start - 10.0), length=4.0)
    filler_tone = _mean_volume_db(emitted, start=filler_start + 2.0, length=4.0)
    second_tone = _mean_volume_db(emitted, start=filler_end + 8.0, length=4.0)
    end_tone = _mean_volume_db(emitted, start=content_end - 6.0, length=4.0)

    # The reload request the daemon actually made.
    assert len(strategy.reloads) == 1, strategy.reloads
    reload_request = strategy.reloads[0]
    spawns = [spawn.plan_kind for spawn in harness.recorder.spawns]

    print(
        f"[u53] emitted: duration={duration:.2f}s (content ends {content_end:.2f}s, "
        f"{len(holds)} post-EOS hold run(s)), filler={filler_start:.2f}->"
        f"{filler_end:.2f}s ({filler_seconds:.2f}s); tone dBFS first={first_tone:.1f} "
        f"filler={filler_tone} second={second_tone:.1f} end={end_tone:.1f}; "
        f"reload segments={reload_request['segments']} "
        f"labels={reload_request['labels']} "
        f"deferred={reload_request['switch_at_end_of_current']}; "
        f"armed->applied={applied_s:.2f}s (horizon was {_FIRST_SLOT_S:g}s out: "
        f"{switch_wait_s:+.2f}s at settle); spawns={spawns}; "
        f"preparations={preparer.kinds}",
        flush=True,
    )

    # -- the plan the daemon handed the engine
    assert reload_request["switch_at_end_of_current"] is True, (
        "the reload was NOT deferred: it was armed too late for the outgoing leg, so "
        "this run did not exercise the deferred hand-off at all"
    )
    assert reload_request["segments"] == [("slate", _GAP_S), ("program", _SECOND_SLOT_S)], (
        f"expected the filler trimmed to the {_GAP_S:g}s gap and chained with the "
        f"{_SECOND_SLOT_S}s programme in ONE plan; saw {reload_request['segments']}"
    )
    assert reload_request["labels"] == [_SLATE_LABEL, _SECOND_TITLE], reload_request["labels"]

    # -- the shape of what aired
    assert abs(filler_seconds - _GAP_S) <= 1.0, (
        f"the filler aired for {filler_seconds:.2f}s, not the {_GAP_S:g}s gap -- the "
        f"programme is early or late by {filler_seconds - _GAP_S:+.2f}s"
    )
    assert abs(filler_start - _FIRST_SLOT_S) <= 2.0, (
        f"the filler started at {filler_start:.2f}s, not at the first slot's end "
        f"({_FIRST_SLOT_S}s): the outgoing leg did not hand over at its own EOS"
    )
    expected_total = _FIRST_SLOT_S + _GAP_S + _SECOND_SLOT_S
    assert abs(content_end - expected_total) <= 1.5, (
        f"the plan's media ended at {content_end:.2f}s, not {expected_total:g}s "
        f"(first slot + gap + second slot): a segment aired short or long"
    )
    assert filler_tone == float("-inf") or filler_tone < -50.0, (
        f"the filler window is not silent ({filler_tone} dBFS): the gap is not the slate"
    )
    assert second_tone - first_tone >= _TONE_SEPARATION_DB, (
        f"the post-filler window is only {second_tone - first_tone:.1f} dB louder than "
        f"the first programme after a {_TONE_HPF!r} filter (first={first_tone:.1f}, "
        f"second={second_tone:.1f} dBFS): the chained programme is not the 4kHz one"
    )
    assert end_tone - first_tone >= _TONE_SEPARATION_DB, (
        f"the last seconds before the plan's own end are only "
        f"{end_tone - first_tone:.1f} dB above the first programme (end={end_tone:.1f}, "
        f"first={first_tone:.1f} dBFS): the chained programme did not play to its end"
    )

    # -- and the daemon did it without restarting the worker
    assert spawns == ["program"], (
        f"expected exactly one worker spawn (the cold start; the deferred reload "
        f"reuses it); saw {spawns}"
    )
    for spawn in harness.recorder.spawns:
        assert spawn.persistent == "1", (
            f"worker spawned without {native.reloadpolicy.WORKER_PERSISTENT_ENV}=1"
        )
