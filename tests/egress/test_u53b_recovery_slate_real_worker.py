# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U53b, real worker: a RESTART-RECOVERY start airs the slate before it conforms.

U53's Addendum added the restart-recovery hand-off: the startup sweep clears a
stale ``ON_AIR`` claim, and the ``start`` it queues carries the cleared state in
its command id, so a channel that WAS on air relaunches "slate first" instead of
going dark for a cold conform (C1: government dark 6 m 55 s).

Installed as C2 on 2026-09-26 that path was **state-only**. The daemon wrote
``FALLBACK_SLATE`` with ``pid=-`` and no encoder behind it, and the three
channels that were airing before the restart stayed dark until their program
conform finished -- on the real station 3 m 02 s, because the slate the
hand-off declares is itself put through ``_PreparationRequest`` (the whole
``_prepare_segment`` conform, loudness probe included) before any worker is
launched. The slate that exists to cover the conform was waiting on it.

This module is that claim against real processes, the real ``worker.py``, and
real ffmpeg media -- the shape the live defect was observed in. The daemon is
driven through its OWN recovery route (``reconcile_stale_state`` ->
``process_once``), not by calling ``_start`` directly, so the sweep and the
command id's ``restart_recovery_previous_state`` marker are under test too.

The timeline, in one test:

1. A persisted ``ON_AIR`` claim whose encoder is gone (the sweep's input; the
   daemon is built with ``pid_is_dead`` forced True so the recovery is
   deterministic -- ``_pid_is_dead`` is consulted only by ``_encoder_is_gone``,
   never by ``_poll_process``, so live worker polling is unaffected).
2. ``reconcile_stale_state()`` clears it and queues the marked start.
3. **THE CLAIM**: slate output exists within 15 s of that recovery instant,
   while the program is still being prepared. The program preparation is held
   open on a ``threading.Event`` for at least 30 s for exactly this reason --
   so the number cannot be earned by the conform merely being fast. On the
   installed bytes this is where the channel is black: the held preparation is
   the SLATE's own (``preparer.kinds == ["slate"]``), no worker is ever spawned,
   and the tick below times out.
4. The hold is released and the channel ends ON AIR on its program -- the slate
   airing was a bridge, not a destination.

Runtime root: this runs the installed GStreamer closure, so it needs
``CIVICAST_GSTREAMER_RUNTIME_ROOT`` pointed at the install's ``runtime``
directory. Two C's after ``CIVI``: the one-C spelling is a different, never-set
variable and makes this skip silently rather than fail.

The channel id is deliberately NOT a production channel id: ``worker_pipe_name``
creates its pipe with ``FILE_FLAG_FIRST_PIPE_INSTANCE``, so sharing a live
station channel's name would fail this run with a squat-detection error, or race
the station's own pipe.
"""

from __future__ import annotations

import shutil
import threading
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
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressStateRow,
)
from civiccast.egress.source_plan import (
    SCHEDULE_GAP_ABSORB_SECONDS,
    ScheduleSourcePlanProvider,
    SlateSourceGenerator,
)
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.models import ScheduleItemResponse, StaffAssetRow
from civiccast.stream._ffmpeg import run_ffmpeg

# The U47 module is this test's harness: the real worker launcher with the spawn
# recorder, the D2 named-pipe control channel, the pacing filesink graph builder,
# and the teardown contract. Reusing it is what keeps this test on the shapes U47
# already pins (and what keeps the two spawn discriminators in one place). Its
# ``_tick_until`` is deliberately NOT imported -- see this module's own below.
from tests.egress import test_gst_engine_wsl as native
from tests.egress import test_u36_rollover_sliver_real_ffmpeg as u36
from tests.egress.test_u47_slate_first_real_worker import (
    _Harness,
    _size,
)

_LIVE_WORKER_AVAILABLE = native._wsl_gi_available()


def _tick_until(
    daemon: EgressDaemon,
    predicate: Any,
    *,
    timeout: float,
    label: str,
) -> float:
    """Tick the real daemon until ``predicate`` holds; return the elapsed seconds.

    This is the U47 module's helper with ONE difference: it ticks THIS module's
    channel. The U47 original hard-codes ``_CHANNEL`` (its own id), so importing it
    here would drive a channel no daemon in this test knows -- the daemon would
    never process the recovery start, every tick would be a no-op, and the module
    would fail for a reason that has nothing to do with the defect under test (this
    seat lost a run to exactly that before catching it).

    Semantics are unchanged otherwise: the predicate is checked BEFORE the first
    tick and after every tick, so a condition already satisfied costs no tick and
    the elapsed figure is a measurement of the daemon rather than of this cadence.
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

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH — skipping real-worker integration test.",
)

# A channel id no station profile can collide with -- see the module docstring.
_CHANNEL = "u53brecovery"
# The label the daemon writes into the state row is the source plan's first
# segment label (``source_plan.py:1024`` takes it from the asset row's TITLE);
# the slate generator hard-codes its own (``source_plan.py:248``).
_PROGRAM_LABEL = "City Council"
_SLATE_LABEL = "CivicCast slate"
_PROGRAM_ASSET_ID = "u53bprogram"

# 30 s of real program media in a 60 s slot: the media is shorter than the slot, so
# the plan is capped by the media's MEASURED length and ends at 30 s, not at the
# slot's end.
_PROGRAM_MEDIA_S = 30.0
_SLOT_S = 60
# ``duration == target_fill`` keeps ``repeats == 1``, so ONE rendered file covers the
# whole horizon and ``SlateSourceGenerator._render_fill``'s extra concat pass never
# runs. The horizon is long enough that the slate worker cannot reach plan EOS while
# the test holds the program open.
_SLATE_RENDER_S = 90
_SLATE_FILL_S = 90

# THE BRIEF'S BAR, asserted directly: "assert a playlist with slate segments appears
# within 15 s of the recovery start". 15 s has ~9 s of headroom over the ~6 s this
# seat measures for worker process bring-up (U47 measured 5.42-6.22 s end to end),
# so a breach here is a daemon that waited for the program, not a slow launch.
_SLATE_BUDGET_S = 15.0
# The program preparation is held at least this long -- the brief's "program that
# takes >= 30 s to prepare". A real cold conform costs 20-133 s in the field; the
# hold is what makes that deterministic instead of media-dependent.
_PROGRAM_PREP_HOLD_S = 30.0
# A general ceiling for steps whose cost is a real process start (python + ``import
# gi`` + Gst.init + graph build + preroll) on a dev box.
_STEP_WAIT_S = 120.0

# A fixed instant just after the scheduled item, so the plan is resolved by the
# schedule rather than by the wall clock.
_NOW = u36._START + timedelta(seconds=1.0)

# The filesink paths this module's graph builder writes to; the spawn discriminator
# maps them back to a plan kind in the U47 module's ``_SINK_PLAN_KIND``.
_PROGRAM_TS = "program.ts"
_SLATE_TS = "slate.ts"


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


def _item(title: str) -> ScheduleItemResponse:
    """The one due program."""

    return ScheduleItemResponse(
        id=uuid4(),
        asset_id=_PROGRAM_ASSET_ID,
        asset_title=title,
        channel_id=_CHANNEL,
        mode="premiere",
        state="published",
        scheduled_at=u36._START,
        duration_seconds=int(_SLOT_S),
        notes=None,
        created_at=u36._START - timedelta(days=1),
    )


def _provider(item: ScheduleItemResponse, assets: dict[str, StaffAssetRow]) -> Any:
    """The PRODUCTION provider shape, driven by a fixed clock (see U47's twin)."""

    return ScheduleSourcePlanProvider(
        schedule_items_provider=lambda _channel_id: [item],
        asset_resolver=assets.get,
        now_provider=lambda: _NOW,
        max_segments=1,
        gap_absorb_seconds=SCHEDULE_GAP_ABSORB_SECONDS,
    )


class _EveryPreparationObserver:
    """The production preparer, with the FIRST post-arm preparation held open.

    U47's observer holds only the first NON-slate preparation, because its
    timeline has a program airing before the relaunch and that program's own
    conform must be allowed to finish. This unit's timeline has no such
    preparation: the recovery start is the first thing that happens, so the
    hold must land on whatever that start asks for FIRST. That difference is
    the whole diagnosis -- on the installed bytes it is the SLATE (nothing then
    airs), on the fixed bytes it is the PROGRAM (the slate is already airing).

    Both halves of the daemon's seam get this same object: the sync path calls it
    ``(plan, config)`` and the async path calls it ``(plan, config, cancel,
    protected)`` positionally, so one signature with keyword-only extras serves
    both. The ``kinds``/``entered``/``release``/``timeline`` attributes are the
    harness's teardown contract.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self._armed = False
        self._held_once = False
        self.kinds: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.held_at: float | None = None
        self.timeline: list[tuple[str, str, float]] = []

    def arm(self) -> None:
        with self._lock:
            self._armed = True

    def __call__(
        self,
        plan: EgressSourcePlan,
        config: EgressConfig,
        cancel_event: threading.Event | None = None,
        protected_plan_dirs: frozenset[Path] | None = None,
    ) -> Any:
        kind = plan.segments[0].kind if plan.segments else "<empty>"
        with self._lock:
            self.kinds.append(kind)
            self.timeline.append((kind, "enter", time.monotonic()))
            hold = self._armed and not self._held_once
            if hold:
                self._held_once = True
                self.held_at = time.monotonic()
        if hold:
            self.entered.set()
            self.release.wait(timeout=_STEP_WAIT_S)
        report = self._inner.prepare(
            plan, config, cancel_event=cancel_event, protected_plan_dirs=protected_plan_dirs
        )
        with self._lock:
            self.timeline.append((kind, "exit", time.monotonic()))
        return report


def _recovered_state(*, pid: int, age_seconds: float) -> EgressStateRow:
    """The stale claim the sweep is built to clear (the exact shape it reads)."""

    return EgressStateRow(
        channel_id=_CHANNEL,
        state="ON_AIR",
        updated_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        pid=pid,
    )


def test_u53b_a_recovery_start_airs_the_slate_before_the_program_is_prepared(
    tmp_path: Path,
) -> None:
    """The whole rule, end to end, on real workers, through the recovery route."""

    if not _LIVE_WORKER_AVAILABLE:
        pytest.skip("no packaged GStreamer runtime reachable from this interpreter")

    harness = _Harness(tmp_path)
    monkey = pytest.MonkeyPatch()
    # A caption tap would add an appsink to the audio path; deleting the knob makes
    # the strategy's ``_with_audio_tap`` a deterministic no-op.
    monkey.delenv("CIVICAST_CAPTION_TAP_DIR", raising=False)
    monkey.setattr(strategy_mod, "graph_from_config", harness.build_graph)
    monkey.setattr(strategy_mod, "subprocess", harness.recorder)

    media = u36._real_asset(tmp_path, name="program.mp4", seconds=_PROGRAM_MEDIA_S)
    item = _item(_PROGRAM_LABEL)
    assets = {
        _PROGRAM_ASSET_ID: u36._row(
            media,
            asset_id=_PROGRAM_ASSET_ID,
            title=_PROGRAM_LABEL,
            recorded_seconds=_PROGRAM_MEDIA_S,
        )
    }
    provider = _provider(item, assets)

    store = InMemoryEgressStore()
    config = _config()
    store.upsert_config(config)
    # The claim the channel was airing under when the previous process died. Its
    # ``pid`` is a pid no live encoder holds; ``pid_is_dead`` below answers for it
    # so the recovery is a fact of this test rather than of this machine's process
    # table. ``_pid_is_dead`` is consulted ONLY by ``_encoder_is_gone``
    # (``daemon.py:1604-1641``), never by ``_poll_process``, so the daemon's own
    # worker polling stays real.
    store.write_state(_recovered_state(pid=424242, age_seconds=3600))

    preparer = _EveryPreparationObserver(u36._sliver_preparer(tmp_path))
    harness.observer = preparer
    slate = SlateSourceGenerator(
        work_dir=tmp_path / "slate",
        duration_seconds=_SLATE_RENDER_S,
        target_fill_seconds=_SLATE_FILL_S,
        ffmpeg_runner=run_ffmpeg,
    )
    strategy = GstPlayoutStrategy(
        worker_launcher=harness.worker_launcher,
        pipe_channel_factory=harness.pipe_channel,
        is_windows=True,
        embed_captions=False,
        # Explicit rather than env-derived: without the seamless path the hand-off
        # has no route to hand the program in at all, and step 4 would hang rather
        # than fail.
        supports_content_reload=True,
    )
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path / "daemon-work",
        source_plan_provider=provider,
        fallback_source_provider=slate,
        source_preparer=preparer,
        async_source_preparer=preparer,
        encoder_strategy=strategy,
        pid_is_dead=lambda _pid: True,
    )
    harness.daemon = daemon
    daemon.enable_async_preparation()

    slate_ts = tmp_path / _SLATE_TS
    program_ts = tmp_path / _PROGRAM_TS
    try:
        # The slate is a CACHED asset on a real station (rendered once, reused by
        # cache key). Warming it before the stopwatch is what makes the figure a
        # measure of the LAUNCH rather than of a one-off render; the warm render's
        # own cost is reported at the end rather than hidden.
        warm_started = time.monotonic()
        slate_plan = slate(config)
        warm_render_s = time.monotonic() - warm_started
        assert slate_plan.segments[0].kind == "slate", slate_plan
        assert Path(slate_plan.segments[0].path).exists(), slate_plan

        # ---- 1. the recovery ------------------------------------------------
        # The stopwatch starts at the RECOVERY instant, not at the first command
        # drain: the sweep that clears the claim and queues the start is part of
        # the window the brief bounds.
        preparer.arm()
        recovery_started = time.monotonic()
        recovered = daemon.reconcile_stale_state()
        assert recovered == [_CHANNEL], (
            f"the stale ON_AIR claim was not recovered: reconcile_stale_state() -> {recovered}"
        )
        row = store.read_state(_CHANNEL)
        assert row is not None and row.state == "STOPPED", (
            f"the sweep did not clear the claim in the command transaction: {row}"
        )

        # ---- 2. THE CLAIM: slate on air, and writing, while the program conforms
        try:
            slate_elapsed = _tick_until(
                daemon,
                lambda: _size(slate_ts) > 0,
                timeout=_SLATE_BUDGET_S,
                label="slate output after the restart-recovery start",
            )
        except AssertionError as exc:
            row = store.read_state(_CHANNEL)
            raise AssertionError(
                f"{exc} -- the restart-recovery start produced no slate output within "
                f"{_SLATE_BUDGET_S:g}s. Preparations the start asked for: {preparer.kinds}; "
                f"preparation entered: {preparer.entered.is_set()}; channel state: "
                f"{row.state if row is not None else None} (pid="
                f"{row.pid if row is not None else None}); worker spawns: "
                f"{[spawn.plan_kind for spawn in harness.recorder.spawns]}. A state-only "
                f"slate (no encoder behind FALLBACK_SLATE) is the C2 defect this unit fixes."
            ) from exc

        assert preparer.entered.is_set(), (
            "no preparation was entered at all -- the elapsed figure below would not be "
            "measuring the dark window it is meant to measure"
        )
        assert not preparer.release.is_set(), "the hold was already released"
        # The program is what must be conforming while the slate airs. On the
        # installed bytes this reads ["slate"]: the start put the SLATE through the
        # conform path it exists to cover.
        assert preparer.kinds[0] == "program", (
            f"the first preparation of the recovery start was {preparer.kinds[0]!r}, not "
            f"'program' -- the slate (or something else) was put on the start path "
            f"instead of airing. All preparations: {preparer.kinds}"
        )
        slate_spawn_s = harness.recorder.spawns[0].at - recovery_started
        assert slate_spawn_s <= _SLATE_BUDGET_S, slate_spawn_s
        row = store.read_state(_CHANNEL)
        assert row is not None and row.state == "FALLBACK_SLATE", row
        assert row.current_source_label == _SLATE_LABEL, row
        assert row.pid is not None, (
            f"FALLBACK_SLATE with no encoder pid -- exactly the state-only slate the C2 "
            f"restart shipped: {row}"
        )

        slate_size_at_hold = _size(slate_ts)
        hold_started_at = preparer.held_at or recovery_started
        assert not preparer.release.is_set(), "the program hold was released before it began"

        # ---- 3. the program preparation really does take >= 30 s -------------
        # Not a sleep: the hold is a real preparation that has not returned, and this
        # tick drives the daemon the whole time. The predicate is the HOLD's age, not
        # the slate's growth -- the slate is writing every few hundred ms, so a
        # growth-driven tick would return immediately and then fail the very
        # assertion it exists to support. Measuring the hold first and the slate's
        # growth across it second is the order that makes both statements true.
        held_s = _tick_until(
            daemon,
            lambda: time.monotonic() - hold_started_at >= _PROGRAM_PREP_HOLD_S,
            timeout=_STEP_WAIT_S,
            label=f"the program preparation held for >= {_PROGRAM_PREP_HOLD_S:g}s",
        )
        assert held_s >= _PROGRAM_PREP_HOLD_S, (
            f"the program preparation was released after {held_s:.2f}s, under the brief's "
            f"{_PROGRAM_PREP_HOLD_S:g}s 'takes >= 30 s to prepare' shape"
        )
        assert not preparer.release.is_set(), "the hold released itself; it is not a real hold"
        # ... and the slate aired for the whole of it: it is strictly larger now than
        # when the hold began, and the channel is still reporting the slate.
        assert _size(slate_ts) > slate_size_at_hold, (
            f"the slate stopped growing while the program was held: {slate_size_at_hold} B "
            f"-> {_size(slate_ts)} B over {held_s:.2f}s"
        )
        still = store.read_state(_CHANNEL)
        assert still is not None and still.state == "FALLBACK_SLATE", (
            f"the channel left the slate while its program was still being prepared: {still}"
        )

        # ---- 4. release: the program is handed in and airs -------------------
        program_ts.unlink(missing_ok=True)
        preparer.release.set()

        def on_program() -> bool:
            current = store.read_state(_CHANNEL)
            return (
                current is not None
                and current.state == "ON_AIR"
                and current.current_source_label == _PROGRAM_LABEL
            )

        _tick_until(
            daemon,
            on_program,
            timeout=_STEP_WAIT_S,
            label="the program handed in and airing after the release",
        )

        # ---- 5. what the real spawn log says ---------------------------------
        labels = [spawn.plan_kind for spawn in harness.recorder.spawns]
        assert labels[0] == "slate", (
            f"the recovery start's FIRST worker was {labels[0]!r}, not the slate -- a "
            f"recovery start must never air the program before the slate. Spawns: {labels}"
        )
        assert labels.count("slate") == 1, (
            f"expected exactly one slate worker (a second would mean it crashed and was "
            f"relaunched); saw {labels}"
        )
        for spawn in harness.recorder.spawns:
            assert spawn.persistent == "1", (
                f"worker spawned without {native.reloadpolicy.WORKER_PERSISTENT_ENV}=1 "
                f"({spawn.plan_kind})"
            )

        print(
            f"[u53b] slate render (warm, one-off): {warm_render_s:.2f}s; "
            f"recovery -> slate output: {slate_elapsed:.2f}s "
            f"(budget {_SLATE_BUDGET_S:g}s; {slate_spawn_s:.2f}s to spawn + "
            f"{slate_elapsed - slate_spawn_s:.2f}s worker startup); "
            f"program prepared for {held_s:.2f}s while the slate aired "
            f"({slate_size_at_hold} B -> {_size(slate_ts)} B); "
            f"preparations={preparer.kinds}; spawns={labels}"
        )
    finally:
        harness.shutdown()
        monkey.undo()
