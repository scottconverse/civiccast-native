# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-worker proof of the U41 plan-EOS slate hold.

``tests/egress/test_gst_engine_reload_commit_ordering.py`` pins the hold with a
bare ``object.__new__`` engine and fake pads: it can prove which event is
dropped, which leg is selected and that the flag reaches ``reload_program`` --
but not that a real GStreamer pipeline actually keeps writing TS while the
selector sits on the slate. This module is the same behaviour against a REAL
worker: the production ``bridge.graph_from_config`` graph (program leg at
selector pad 0, the always-hot live/infinite slate at pad 1), the production
``worker.py``, a real filesink.

The shape is the live 2026-09-25 education-channel incident, scaled down: the
programme's own plan ends and the replacement is not ready yet (the daemon
prepares it for ~80 s in the field; here the preparation is simply withheld
until the end has been observed). Before U41 the leg's EOS crossed the active
selector pad, reached ``mpegtsmux`` and the bus, and ``_on_bus`` answered the
pipeline EOS by quitting the loop -- the worker exited 0 while the channel's own
state row still said ON_AIR, and the daemon relaunched it ~3 minutes later.
After U41 the EOS is declined at the pad, the slate goes on air, and the worker
is still running and still writing when the reload lands.

The reload is sent in the DEFERRED mode (the production
``switch_at_end_of_current`` path, ``reload_policy.DEFERRED_SWITCH_SUFFIX``) on
purpose: with the hold set, ``reload_program``'s ``old_leg_eos`` starts True, so
the commit must happen as soon as the replacement's first buffer lands instead
of arming a 900 s deferral for a boundary that has already passed. A hold that
did not feed that flag would leave this test waiting at
``CTRL reload committed``.

Skipped without a packaged GStreamer runtime reachable from THIS interpreter --
point ``CIVICCAST_GSTREAMER_RUNTIME_ROOT`` at the install's ``runtime`` directory
(the recipe is ``tests/egress/test_gst_engine_wsl.py``'s module docstring, and
that module's own availability probe decides). The spelling is two C's after
``CIVI`` (``CIVICCAST_``, matching the package name); the one-C variant is a
different variable that nothing in the product reads, so exporting that one
skips this test's worker half by making the probe fail -- silent, not an error.
"""

from __future__ import annotations

import shutil
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from civiccast.schedule.models import ScheduleItemResponse, StaffAssetRow

# The live-worker half imports the native line's own live suite rather than
# copying its harness, exactly as ``test_u36_rollover_sliver_real_ffmpeg.py`` and
# ``test_gst_engine_caption_flow_native.py`` already do. U36's module is used for
# the real-media and production-preparer helpers, so the plan/artifact shapes
# below are the same ones that module already pins against real ffmpeg.
from tests.egress import test_gst_engine_wsl as native
from tests.egress import test_u36_rollover_sliver_real_ffmpeg as u36

_LIVE_WORKER_AVAILABLE = native._wsl_gi_available()

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH — skipping real-ffmpeg integration test.",
)

# Scaled to something ffmpeg builds and conforms in a couple of seconds: the
# programme is 6 s of real media and its rows tell the truth about it (this test
# is about the plan ENDING, not about a row that lies), so the leg's EOS lands
# ~6 s after the worker goes to PLAYING. The SLOT is 30 s -- longer than the
# media, so the row's measured length is the cap and the plan ends at 6 s, not
# at the slot's end (the same shape U36 pins).
_PROGRAM_S = 6.0
_SLOT_S = 30
# The replacement starts where the programme's slot ends, so it is the NEXT
# programme at every instant in between, and it is inside
# SCHEDULE_GAP_ABSORB_SECONDS (30 s) of the plan end -- U26's absorb therefore
# hands the boundary to it rather than to a gap.
_REPLACEMENT_START_S = 30.0
_REPLACEMENT_S = 8.0
# The instant the delayed reload is planned at: the first second after the
# programme's own media ends, which is where the field's rollover landed too.
_RELOAD_PLAN_AT_S = _PROGRAM_S + 1.0
# How long the slate is watched before the reload is sent. Long enough for TS to
# advance measurably and for the pre-U41 worker to have exited several times over.
_SLATE_WATCH_S = 3.0

# The hold's own operator-facing lines, verbatim from
# ``GstPlayoutEngine._on_program_pad_plan_eos`` / ``_hold_slate_for_plan_eos``.
_HOLD_LINE = "CTRL plan EOS: program leg ended with no reload in flight; holding the slate"
_SLATE_LINE = "CTRL plan EOS: slate on air; the channel stays up until the replacement is ready"

# A 20 s settle window: the deferred switch is armed early and must commit on the
# replacement's first buffer, so a wedged state fails fast instead of holding.
#
# U41: the hold is armed only for a run the DAEMON marked persistent (its launcher
# sets ``reload_policy.WORKER_PERSISTENT_ENV`` in the child's environment); this
# harness spawns ``worker.py`` itself, so it has to say the same thing. Read from
# the product -- the name comes from the module ``worker.main()`` itself reads, so
# a rename cannot leave this test arming a hold on a flag nothing consumes (which
# would fail here as a silent "worker exited at plan EOS", not as an error).
_RELOAD_SETTLE_ENV = {
    "CIVICAST_RELOAD_TIMEOUT_S": "20",
    native.reloadpolicy.WORKER_PERSISTENT_ENV: "1",
}


def _programs(tmp_path: Path) -> tuple[list[ScheduleItemResponse], dict[str, StaffAssetRow]]:
    """One programme of real media, its rows honest, plus the replacement.

    Both items are built by U36's helpers against ``u36._START``; the shapes are
    ordinary schedule rows with no trim window, so the planner's segment is the
    media's own length.
    """

    first_media = u36._real_asset(tmp_path, name="program.mp4", seconds=_PROGRAM_S)
    replacement_media = u36._real_asset(tmp_path, name="replacement.mp4", seconds=_REPLACEMENT_S)
    items = [
        ScheduleItemResponse(
            id=uuid4(),
            asset_id="program",
            asset_title="City Council",
            channel_id="gov",
            mode="premiere",
            state="published",
            scheduled_at=u36._START,
            duration_seconds=_SLOT_S,
            notes=None,
            created_at=u36._START - timedelta(days=1),
        ),
        ScheduleItemResponse(
            id=uuid4(),
            asset_id="replacement",
            asset_title="Planning Commission",
            channel_id="gov",
            mode="premiere",
            state="published",
            scheduled_at=u36._START + timedelta(seconds=_REPLACEMENT_START_S),
            duration_seconds=_SLOT_S,
            notes=None,
            created_at=u36._START - timedelta(days=1),
        ),
    ]
    assets = {
        "program": u36._row(
            first_media, asset_id="program", title="City Council", recorded_seconds=_PROGRAM_S
        ),
        "replacement": u36._row(
            replacement_media,
            asset_id="replacement",
            title="Planning Commission",
            recorded_seconds=_REPLACEMENT_S,
        ),
    }
    return items, assets


@pytest.mark.skipif(
    not _LIVE_WORKER_AVAILABLE,
    reason="no packaged GStreamer runtime reachable from this interpreter — the real "
    "worker cannot run here (set CIVICCAST_GSTREAMER_RUNTIME_ROOT).",
)
def test_u41_a_real_plan_end_holds_the_slate_until_the_reload_lands(tmp_path: Path) -> None:
    """The whole chain, on real media, with a real GStreamer worker.

    Asserted, in order: the plan end is declined at the pad and the slate goes on
    air; the worker is STILL RUNNING and still writing TS through the hold; the
    withheld reload then commits against the held slate; the worker stays up and
    tears down cleanly.

    What each revision does with that chain:

      * At ``e1189cae`` (and at every revision before U41) nothing declines the
        EOS, so it reaches the mux's downstream and the bus, ``_announce_pipeline_
        eos`` quits the loop, and the worker exits 0 -- ``holding the slate`` never
        appears and the TS stops growing. The daemon's relaunch is the only thing
        that put the channel back, ~3 minutes later.
      * At HEAD the EOS is dropped before it crosses, ``selector`` moves to pad 1,
        and the live slate keeps the mux's output advancing until the reload
        commits to ``selector_sink_pads[0]`` again.

    Not covered here: the daemon's decision of WHEN to arm the reload (this test
    plays that role), the station's own udp sinks, and a >900 s hold -- the
    deferred reload here lands within seconds of the hold.
    """

    # The production graph, built by the same bridge the station uses: program at
    # pad 0, the live/infinite slate at pad 1. The harness loads ``graph.py`` a
    # SECOND time (by path, under the bare name ``graph``) so its serializers are a
    # different module object than the product's; U36 documents the rebind below
    # (``graph_to_json``'s ``isinstance(source, PlaylistLeg)`` is class identity) and
    # this test reuses it verbatim, restoring the harness global afterwards.
    from civiccast.egress.gst import graph as product_graph
    from civiccast.egress.gst.bridge import graph_from_config

    items, assets = _programs(tmp_path)
    provider = u36._provider(items, assets)
    preparer = u36._sliver_preparer(tmp_path)
    config = u36._config()

    program_plan = provider.plan_at("gov", u36._START)
    assert [segment.source_ref for segment in program_plan.segments] == ["program"], (
        f"the outgoing plan must be the programme alone, got "
        f"{[segment.source_ref for segment in program_plan.segments]}"
    )
    outgoing = preparer.prepare(program_plan, config)

    out_ts = tmp_path / "out.ts"
    reload_path = tmp_path / f"rollover{native.reloadpolicy.DEFERRED_SWITCH_SUFFIX}"

    harness_graphmod = native.graphmod
    native.graphmod = product_graph
    try:
        graph = native._paced_filesink_graph(
            graph_from_config(config, outgoing.source_plan), out_ts
        )
        # The replacement's graph, written now but DELIVERED late: the reload is
        # withheld until the plan end has been observed, which is this test's stand-in
        # for the field's ~80 s preparation the channel had to wait through.
        replacement_plan = provider.plan_at(
            "gov", u36._START + timedelta(seconds=_RELOAD_PLAN_AT_S)
        )
        assert [segment.source_ref for segment in replacement_plan.segments] == ["replacement"], (
            f"the delayed reload must resolve the NEXT programme, got "
            f"{[segment.source_ref for segment in replacement_plan.segments]}"
        )
        replacement = preparer.prepare(replacement_plan, config)
        reload_path.write_text(
            native.graphmod.graph_to_json(
                native._filesink_graph(
                    graph_from_config(config, replacement.source_plan), tmp_path / "payload-out.ts"
                )
            ),
            encoding="utf-8",
        )
        assert native.reloadpolicy.reload_switch_is_deferred(str(reload_path)), (
            "the reload must request the DEFERRED switch mode: the whole point is that the "
            "hold's old_leg_eos=True commits it at once instead of arming a deferral"
        )
        proc, control, log = native._launch_worker(tmp_path, graph, out_ts, _RELOAD_SETTLE_ENV)
    finally:
        native.graphmod = harness_graphmod

    try:
        # The plan end. Waiting on the engine's own line rather than on a stopwatch:
        # 45 s covers a slow first frame plus the 6 s programme with wide margin.
        native._wait_for_log(log, _HOLD_LINE, timeout=45.0)
        held_at_size = out_ts.stat().st_size

        # THE DEFECT: the worker used to exit here, having played the plan out.
        assert proc.poll() is None, (
            "the worker exited at the plan end instead of holding the slate -- the channel "
            "went dark until the daemon relaunched it;\n"
            f"{log.read_text(encoding='utf-8', errors='replace')}"
        )
        native._wait_for_log(log, _SLATE_LINE, timeout=10.0)

        # The slate is live and infinite, so the mux's output keeps advancing while
        # it is on air. This is what a bare "the loop did not quit" cannot show.
        time.sleep(_SLATE_WATCH_S)
        assert proc.poll() is None, (
            f"the worker exited during the slate hold;\n"
            f"{log.read_text(encoding='utf-8', errors='replace')}"
        )
        slate_at_size = out_ts.stat().st_size
        assert slate_at_size > held_at_size, (
            f"no TS was written during the {_SLATE_WATCH_S}s slate hold "
            f"({held_at_size} -> {slate_at_size} bytes): the output stopped, so the channel "
            f"was effectively dark even though the worker was alive;\n"
            f"{log.read_text(encoding='utf-8', errors='replace')}"
        )

        # The delayed reload. Deferred mode, so the commit is the hold's own doing.
        native._send(control, f"reload {reload_path}")
        native._wait_for_log(log, "CTRL reload committed", timeout=60.0)
        committed_at_size = out_ts.stat().st_size
        time.sleep(1.0)
        assert proc.poll() is None, (
            f"the worker exited while the held slate was being replaced;\n"
            f"{log.read_text(encoding='utf-8', errors='replace')}"
        )
        assert out_ts.stat().st_size > committed_at_size, (
            "the transport stream did not advance after the reload committed;\n"
            f"{log.read_text(encoding='utf-8', errors='replace')}"
        )

        native._send(control, "stop")
        returncode = proc.wait(timeout=25)
    finally:
        native._reap(proc)

    text = log.read_text(encoding="utf-8", errors="replace")
    assert returncode == 0, (
        f"unclean teardown after the held-slate reload (rc={returncode});\n{text}"
    )
    native._assert_reload_committed(text)
    assert {"video", "audio"} <= native._ffprobe_codec_types(out_ts), (
        f"ffprobe did not report both a video and an audio stream across the hold;\n{text}"
    )
    # The transport clock across the whole file, plan end and hold included. Reported
    # as raw numbers too (U41 report section 5) because this is the first real-worker
    # run of a bare selector swap that was NOT inside a reload transaction.
    analysis = native._analyze_ts(out_ts)
    print(f"U41 TS ANALYSIS: {analysis}")
    assert analysis["packets"] > 0, f"no TS produced;\n{text}"
    elementary = [pid for pid in analysis["pids"] if pid >= 0x40]
    assert len(elementary) >= 2, f"expected video+audio PIDs, got {analysis['pids']};\n{text}"
