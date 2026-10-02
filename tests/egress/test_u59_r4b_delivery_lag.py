# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U59 round 4b -- the delivery-LAG judge, RED/GREEN.

Round 4 judges the on-air leg's INSTANTANEOUS delivery rate against a 0.9x
nominal floor. Live 2026-09-28 06:24 (public, reload_id=16) is the case that
floor cannot see: video drained at ~0.967x nominal for ~60s -- above any floor
that is also quiet on healthy legs -- and the accumulated shortfall became a
2.000s picture hole at the changeover. Round 4's own rate judge was live for that
occurrence and printed nothing. What that shortfall moves without bound is the
ACCUMULATED difference between the seconds of audio and the seconds of video the
leg has delivered, which is what ``_u59_judge_leg_lag`` measures.

The judge is reached from the same CTRL output poll as the rate judge
(``_maybe_print_output_progress``) and reads the same ``sel`` rung, and it is
judged before that poll's snapshot so the deltas it accumulates are this
interval's. Its bound is a GROWTH over a rolling window, chosen from the real
excerpts: a healthy leg's 60s-window growth never exceeded 0.32s across ~6000s
of C9 polling and 418s of C11, while the two occurrences measured +2.36s (C11)
and +4.57s (C9) -- the bound sits between with ~3x margin on both sides.

Every test asserts the POSITIVE -- a WARN line the round-4b engine prints and the
installed round-4 bytes do not -- so this file is RED against the round-4 engine
``fe5a530663243e71`` and GREEN after the round-4b hunks. Tests that assert a
silence carry their own positive control, for the reason the round-4 file gives:
an absence-only test passes against an engine that prints nothing at all. The
controls that must not inherit an earlier test's accumulator run on a FRESH
engine, because the accumulator is per-leg state on a long-lived object.

One test is deliberately green on BOTH engines:
``test_the_rate_line_is_unchanged_by_the_suffix_refactor`` pins the round-4 line
byte-for-byte, because round 4b moved its tail into a shared helper.

Every pinned time and value below is derived from the arithmetic, not read off a
run: at a uniform 5s cadence the growth across a fully covered 60s window is
exactly 12 polls of the per-poll increment, and the first line lands on the
second poll after the window is first covered. Each test's docstring carries its
own arithmetic so a reader can check it against the model -- and if a pinned
value is right in the model and wrong in the run, the model is what gets
re-derived, never the test fitted to the output.

No station is touched and no real GStreamer is required -- the engine is a bare
``object.__new__`` shape, exactly the shapes the fake-``Gst`` harness in
``test_gst_engine_reload_commit_ordering`` already builds.
"""

from __future__ import annotations

import inspect
import types
from typing import Any

import pytest

from tests.egress.test_gst_engine_reload_commit_ordering import (  # noqa: F401
    _FakeDiagnosticPad,
    _Recorder,
    engine_module,
)

# Nominal rates the live engine measures: 30 video buffers/s (a 30fps station
# segment) and 46.875 audio buffers/s (AAC: 1024 samples at 48kHz).
_VIDEO_NOMINAL = 30.0
_AUDIO_NOMINAL = 48000.0 / 1024.0
_POLL_S = 5.0
_RUNG = "sel"
_START_T = 1000.0

# Per-poll buffer counts. The per-poll lag increment in seconds is
# audio/46.875 - video/30.
_MILD_VIDEO = 145  # 29.0/s = 0.967x nominal -- the live C11 shape; +0.180s/poll
_MILD_AUDIO = 235  # 47.0/s = 1.003x nominal
_HEALTHY_VIDEO = 150  # 30.0/s = 1.000x -- +0.013s/poll, 0.160s per 60s window
_HEALTHY_AUDIO = 235
_DIP_VIDEO = 138  # 27.6/s = 0.920x -- the box-wide contention shape
_DIP_AUDIO = 216  # 43.2/s = 0.922x -- down WITH the video: +0.008s/poll
_STARVED_VIDEO = 0  # a total video collapse: +5.013s/poll
_BURST_VIDEO = 195  # 39.0/s = 1.300x -- catching up: -1.487s/poll

_LAG_PREFIX = "WARN: leg delivery lag"
_RATE_PREFIX = "WARN: leg chain-in video below floor"
_WARN_PREFIXES = (_LAG_PREFIX, _RATE_PREFIX)


class _RecorderlessPad(_FakeDiagnosticPad):
    """A ladder pad. ``_u59_rates`` keys off pad PRESENCE, never identity, so the
    pad's own behaviour is irrelevant -- but reusing the harness's pad class keeps
    this file one shape with the round-4 file."""

    def __init__(self, name: str) -> None:
        super().__init__(name, _Recorder())


class _Named:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class _QueueElement(_Named):
    """A queue as ``_u59_queue_field`` reads one."""

    def __init__(self, name: str, buffers: int, time_ns: int) -> None:
        super().__init__(name)
        self._buffers = buffers
        self._time_ns = time_ns

    def get_property(self, key: str) -> Any:
        return {
            "current-level-buffers": self._buffers,
            "current-level-time": self._time_ns,
        }.get(key)


def _leg(**overrides: Any) -> dict[str, Any]:
    """One program leg as the record leaves it: two pieces whose concat probes
    reported spans, a queue, two decoders.

    Hand-built rather than recorded through ``_u59_leg_record``, because the
    helper under test reads exactly this dict: building it here makes the line's
    fields a test of the rendering, not of the recorder (which the round-4 file
    already exercises through the real build path)."""
    leg: dict[str, Any] = {
        "txn_id": 42,
        "label": "program",
        "video_pad": None,
        # piece spans: 100.000s then 30.000s -> leg_rt=130.000s on piece 2/2
        "pieces": [
            {
                "path": "C:/egress/seg-0001.ts",
                "first_pts": 0,
                "last_pts": 100_000_000_000,
                "last_t": 900.0,
            },
            {
                "path": "C:/egress/seg-0002.ts",
                "first_pts": 0,
                "last_pts": 30_000_000_000,
                "last_t": 1000.0,
            },
        ],
        "queues": [_QueueElement("program_video_queue", 3, 41_000_000)],
        "decoders": [_Named("decodebin0"), _Named("decodebin1")],
    }
    leg.update(overrides)
    return leg


def _diagnostic_engine(module: types.ModuleType, *, start_t: float = _START_T) -> Any:
    """A bare engine with the ladder, the leg list and the diagnostic state both
    U59 judges read.

    Nothing here is round-4b-specific except the lag state, so the same shape
    drives the installed round-4 engine too -- where the lag attributes are seeded
    but never read, because the judge does not exist there."""
    engine = object.__new__(module.GstPlayoutEngine)
    init = getattr(engine, "_u59_init_diagnostics", None)
    if callable(init):
        init()
    assert hasattr(engine, "_CHAIN_INPUT_RUNGS")
    engine._chain_input_pads = {
        (_RUNG, "video"): _RecorderlessPad("program_video_sel_src"),
        (_RUNG, "audio"): _RecorderlessPad("program_audio_sel_src"),
    }
    engine._chain_input_buffers = {(_RUNG, "video"): 0, (_RUNG, "audio"): 0}
    engine._chain_input_snapshot = dict(engine._chain_input_buffers)
    engine._mux_input_pads = {}
    engine._mux_input_buffers = {}
    engine._mux_input_snapshot = {}
    engine._mux_input_snapshot_t = start_t
    engine._output_buffers = 0
    engine._output_buffers_at_arm = 0
    engine._last_output_progress_print_t = start_t
    engine.selector = None
    engine._u59_legs = ()
    engine._u59_qos = ()
    engine._u59_rate_streak = 0
    engine._u59_rate_in_episode = False
    engine._u59_fired_t = None
    engine._u59_rate_interval_t = start_t
    # The round-4b state, seeded on both engines so the harness is one shape.
    engine._u59_lag_samples = ()
    engine._u59_lag_total = 0.0
    engine._u59_lag_txn = None
    engine._u59_lag_streak = 0
    engine._u59_lag_in_episode = False
    engine._u59_lag_fired_t = None
    engine._u59_lag_interval_t = start_t
    return engine


def _require_round_four_b(engine: Any) -> Any:
    """The judge, or a failure that says exactly what is missing -- which is what
    RED against the installed round-4 bytes looks like."""
    method = getattr(engine, "_u59_judge_leg_lag", None)
    if not callable(method):
        pytest.fail("round 4b method _u59_judge_leg_lag is absent from the engine")
    return method


def _advance(engine: Any, *, video: int, audio: int) -> None:
    engine._chain_input_buffers[(_RUNG, "video")] += video
    engine._chain_input_buffers[(_RUNG, "audio")] += audio
    engine._output_buffers += video + audio


def _poll_and_read(
    engine: Any, capsys: Any, *, now: float, video: int, audio: int
) -> tuple[list[str], list[str]]:
    """One CTRL output poll, returning (lag lines, rate lines) for THAT poll.

    Both kinds are returned, never just one: a helper that filtered to the line
    under test would make every "the other judge stayed quiet" assertion vacuous
    (``readouterr`` drains the buffer, so a discarded rate line is gone). The
    ladder advances by ``video``/``audio`` buffers over the interval and the REAL
    progress method then runs, so both judges see this interval's deltas and the
    baselines advance exactly as they do live."""
    capsys.readouterr()  # drop anything earlier
    _advance(engine, video=video, audio=audio)
    engine._maybe_print_output_progress(now)
    captured = capsys.readouterr()
    lag: list[str] = []
    rate: list[str] = []
    for line in captured.err.splitlines():
        if line.startswith(_LAG_PREFIX):
            lag.append(line)
        elif line.startswith(_RATE_PREFIX):
            rate.append(line)
    return lag, rate


def _drive(
    engine: Any,
    capsys: Any,
    *,
    polls: int,
    video: int,
    audio: int,
    first_index: int = 0,
) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    """Drive ``polls`` polls at the 5s cadence from ``first_index``; return the
    lag lines and the rate lines, each tagged with the moment it printed."""
    lag: list[tuple[float, str]] = []
    rate: list[tuple[float, str]] = []
    for index in range(first_index, first_index + polls):
        now = _START_T + (index + 1) * _POLL_S
        poll_lag, poll_rate = _poll_and_read(
            engine, capsys, now=now, video=video, audio=audio
        )
        lag.extend((now, line) for line in poll_lag)
        rate.extend((now, line) for line in poll_rate)
    return lag, rate


def _drive_mild(
    engine: Any, capsys: Any, *, polls: int, first_index: int = 0
) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    return _drive(
        engine,
        capsys,
        polls=polls,
        video=_MILD_VIDEO,
        audio=_MILD_AUDIO,
        first_index=first_index,
    )


def _judge_and_read(
    engine: Any, capsys: Any, *, now: float, video: int, audio: int
) -> list[str]:
    """One poll driven at a cadence the 5s progress gate would suppress.

    The rate-limit floor has to hold independently of the poll cadence, so this
    calls the judge directly -- and moves the ladder snapshot itself, which is the
    one thing ``_maybe_print_output_progress`` does after the judges."""
    judge = _require_round_four_b(engine)
    capsys.readouterr()
    _advance(engine, video=video, audio=audio)
    judge(now)
    engine._chain_input_snapshot = dict(engine._chain_input_buffers)
    captured = capsys.readouterr()
    return [line for line in captured.err.splitlines() if line.startswith(_LAG_PREFIX)]


# --- item 1: the mild sustained shortfall, which round 4 cannot see ----------


def test_mild_shortfall_fires_though_the_rate_floor_stays_quiet(
    engine_module: Any, capsys: Any, monkeypatch: Any
) -> None:
    """The whole reason for round 4b: 0.967x nominal is above every rate floor
    that is also quiet on a healthy leg, so the round-4 judge prints nothing --
    and the lag judge prints the shortfall as the seconds it is.

    Arithmetic: +0.180s of lag per poll; 12 polls in a covered 60s window ->
    growth 2.160s at the first poll that has a baseline (t=1065, streak 1) and
    again at t=1070 (streak 2) -> one line, lag=+2.160s, then latched."""
    monkeypatch.delenv("CIVICAST_GST_LEG_RATE_DIAG", raising=False)
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    lag, rate = _drive_mild(engine, capsys, polls=14)

    assert rate == [], "29.0/s is above the 0.9x floor -- the rate judge must stay quiet"
    assert [now for now, _ in lag] == [1070.0], f"expected one line at t=1070, got {lag!r}"

    line = lag[0][1]
    assert "reload_id=none" in line  # no leg recorded yet
    assert "rung=sel" in line
    assert "lag=+2.160s over 60.0s" in line
    assert "(bound 1.0s, polls=2)" in line
    assert "video=29.0/s" in line
    assert "audio=47.0/s" in line
    assert "window=5.0s" in line
    assert "leg=none piece=none pos=none leg_rt=none" in line
    assert "path=none" in line
    assert "queues=none" in line
    assert "decoders=none" in line
    assert "qos=0 in 30s" in line

    # latched for the episode: the next short poll prints nothing more
    assert _poll_and_read(engine, capsys, now=1075.0, video=_MILD_VIDEO, audio=_MILD_AUDIO) == (
        [],
        [],
    )


def test_no_line_until_the_window_is_fully_covered(engine_module: Any, capsys: Any) -> None:
    """The disclosed arming delay, pinned.

    A judge that grew over a partly covered window would compare a growth against
    a span it did not cover. The latency is a function of the WINDOW, not of the
    severity: a total video collapse (+5.013s of lag per poll, 60.16s per window)
    fires on exactly the same poll as the mild 0.967x shortfall above. The rate
    judge, on the same engine and the same polls, does fire on the collapse --
    the positive control that this test is not reading a silent engine."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    fired: list[float] = []
    rate_seen = 0
    for index in range(14):
        now = _START_T + (index + 1) * _POLL_S
        poll_lag, poll_rate = _poll_and_read(
            engine, capsys, now=now, video=_STARVED_VIDEO, audio=_MILD_AUDIO
        )
        fired.extend([now] * len(poll_lag))
        rate_seen += len(poll_rate)
        assert (poll_lag == []) or now == 1070.0, (
            f"the first lag line must wait for the window; it printed at t={now}"
        )

    assert fired == [1070.0], f"the first lag line must wait for the window, got {fired!r}"
    assert rate_seen >= 1, "the rate judge must have fired -- otherwise nothing was ever live"


def test_a_healthy_leg_never_fires(engine_module: Any, capsys: Any) -> None:
    """Nominal delivery is silent: +0.013s per poll is 0.160s per window, 6x under
    the bound. The control is a FRESH engine on the mild shape -- the accumulator
    is per-leg state on a long-lived object, so a control driven after a healthy
    prefix would measure the prefix's leftover as much as the shortfall."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    lag, rate = _drive(engine, capsys, polls=24, video=_HEALTHY_VIDEO, audio=_HEALTHY_AUDIO)
    assert (lag, rate) == ([], [])

    control = _diagnostic_engine(engine_module)
    assert [now for now, _ in _drive_mild(control, capsys, polls=14)[0]] == [1070.0]


def test_a_catch_up_burst_never_fires(engine_module: Any, capsys: Any) -> None:
    """One-sided by construction.

    A leg delivering video FASTER than nominal is catching up -- the post-switch
    burst measured -2.7s of growth over 30s on the real excerpts -- which is the
    opposite defect and must not be logged as this one. The accumulator goes
    negative and stays there."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    lag, rate = _drive(engine, capsys, polls=24, video=_BURST_VIDEO, audio=_HEALTHY_AUDIO)
    assert (lag, rate) == ([], [])
    assert engine._u59_lag_total < -1.0, "the burst must have driven the lag negative"

    control = _diagnostic_engine(engine_module)
    assert [now for now, _ in _drive_mild(control, capsys, polls=14)[0]] == [1070.0]


def test_a_box_wide_dip_never_fires(engine_module: Any, capsys: Any) -> None:
    """The contention shape round 4 needed an audio guard for, which round 4b is
    blind to by construction.

    Both streams counted in their OWN nominal seconds at the same fraction of it
    grow the lag by ~0 (+0.008s/poll here), whatever the absolute rates are. No
    audio guard is needed and none is applied -- the control below is the SAME
    depressed video with the audio that was down with it back to healthy, and at
    +0.413s/poll it fires."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    lag, rate = _drive(engine, capsys, polls=24, video=_DIP_VIDEO, audio=_DIP_AUDIO)
    assert (lag, rate) == ([], [])

    control = _diagnostic_engine(engine_module)
    control_lag, _ = _drive(control, capsys, polls=14, video=_DIP_VIDEO, audio=_HEALTHY_AUDIO)
    assert [now for now, _ in control_lag] == [1070.0], f"expected one line, got {control_lag!r}"
    assert "lag=+4.960s over 60.0s" in control_lag[0][1]


def test_the_accumulator_resets_when_the_leg_changes(engine_module: Any, capsys: Any) -> None:
    """A deficit belongs to the leg that ran it up.

    Inheriting one across a changeover would fire on the NEW leg for the OLD
    leg's hole. The new leg starts from zero, so its first line waits out a fresh
    window: the switch lands at t=1075 (after the 14th poll) and the line comes at
    t=1140 -- the 12-poll window plus the two-poll streak measured from the first
    second leg poll at 1080."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    engine._u59_legs = (_leg(txn_id=1),)
    assert [now for now, _ in _drive_mild(engine, capsys, polls=14)[0]] == [1070.0]

    engine._u59_legs = (_leg(txn_id=2),)
    lag, rate = _drive_mild(engine, capsys, polls=14, first_index=14)
    assert [now for now, _ in lag] == [1140.0], (
        f"the new leg must not inherit the old leg's deficit, got {lag!r} (rate={rate!r})"
    )
    # and the reset was of the ACCUMULATOR, not just the arming: a leg that
    # inherited +2.16s of deficit would have fired on its first covered poll
    assert engine._u59_lag_total < 3.0


def test_one_line_per_warn_interval_while_the_episode_continues(
    engine_module: Any, capsys: Any
) -> None:
    """The 10s floor, driven at a 1s cadence so it is exercised as a floor and not
    as a side effect of the 5s progress interval.

    At 1s the mild shape accumulates +0.036s per poll, so the same 2.16s window
    growth arrives at t=1062 -- the metric is cadence-independent. One second at
    10x video drives the accumulator negative and ends the episode; the collapse
    from t=1064 grows +1.28s per second, crossing the bound at t=1070 (streak 1)
    and t=1071 -- where the floor suppresses it, 9s after the last line, WITHOUT
    latching the episode -- so it prints at t=1072 with the growth by then."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)

    fired: list[tuple[float, str]] = []
    for now in range(1001, 1063):
        for line in _judge_and_read(engine, capsys, now=float(now), video=29, audio=47):
            fired.append((float(now), line))
    assert [t for t, _ in fired] == [1062.0], f"expected the first line at t=1062, got {fired!r}"
    assert "lag=+2.160s" in fired[0][1]

    # one 10x second: -1.437s, so the accumulator drops and the episode ends
    assert _judge_and_read(engine, capsys, now=1063.0, video=300, audio=47) == []
    for now in range(1064, 1071):
        assert _judge_and_read(engine, capsys, now=float(now), video=0, audio=60) == [], (
            f"the episode ended at t=1063 and the floor still holds (t={now})"
        )

    assert _judge_and_read(engine, capsys, now=1071.0, video=0, audio=60) == [], (
        "streak 2 but only 9s since the last line: the floor suppresses it"
    )
    lines = _judge_and_read(engine, capsys, now=1072.0, video=0, audio=60)
    assert len(lines) == 1, f"expected one line at t=1072, got {lines!r}"
    assert "lag=+4.323s over 60.0s" in lines[0]

    assert _judge_and_read(engine, capsys, now=1073.0, video=0, audio=60) == [], "latched again"


def test_the_kill_switch_silences_the_line(
    engine_module: Any, capsys: Any, monkeypatch: Any
) -> None:
    """The same switch as round 4's: an explicit 0/off/false/no. Nothing is
    accumulated while it is off, so the control's window starts when it is
    re-armed -- the line lands at t=1170, twelve polls after t=1105."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)
    monkeypatch.setenv("CIVICAST_GST_LEG_RATE_DIAG", "0")

    lag, rate = _drive_mild(engine, capsys, polls=20)
    assert (lag, rate) == ([], [])

    monkeypatch.delenv("CIVICAST_GST_LEG_RATE_DIAG")
    assert [now for now, _ in _drive_mild(engine, capsys, polls=14, first_index=20)[0]] == [1170.0]


# --- item 2: the line's fields, and the rate line's byte-identity -----------


def test_the_line_names_the_leg_piece_path_queues_decoders_and_qos(
    engine_module: Any, capsys: Any, monkeypatch: Any
) -> None:
    """The same per-leg suffix the rate line carries -- one description of the
    leg, two measurements of it."""
    monkeypatch.delenv("CIVICAST_GST_LEG_RATE_DIAG", raising=False)
    engine = _diagnostic_engine(engine_module)
    _require_round_four_b(engine)
    engine._u59_legs = (_leg(),)
    engine._u59_qos = (
        {"t": 1060.0, "src": "tsdemux0", "jitter": 0.05, "proportion": 1.0, "dropped": 12},
    )

    lag, _ = _drive_mild(engine, capsys, polls=14)
    assert len(lag) == 1, f"expected exactly one line, got {lag!r}"

    line = lag[0][1]
    assert "reload_id=42" in line
    assert "leg=program" in line
    assert "piece=2/2" in line
    assert "pos=30.000s" in line
    assert "leg_rt=130.000s" in line
    assert "path=C:/egress/seg-0002.ts" in line
    assert "queues=program_video_queue=3buf/0.041s" in line
    assert "decoders=decodebin0,decodebin1" in line
    assert "qos=1 in 30s [tsdemux0,jit=0.0500,prop=1.0000,drop=12]" in line


def test_the_rate_line_is_unchanged_by_the_suffix_refactor(engine_module: Any) -> None:
    """Round 4b factors the rate line's per-leg tail into ``_u59_leg_suffix`` so
    both instruments name the leg identically. The rate line must be
    BYTE-identical to round 4's -- it is the line the live station is already
    grepping for, and this test is therefore green on both engines by design."""
    engine = _diagnostic_engine(engine_module)
    line = engine._u59_warn_line(
        now=1060.0,
        leg=None,
        rung=_RUNG,
        video_rate=21.0,
        audio_rate=47.0,
        video_nominal=_VIDEO_NOMINAL,
        audio_nominal=_AUDIO_NOMINAL,
        interval=5.0,
    )
    assert line == (
        "WARN: leg chain-in video below floor reload_id=none rung=sel "
        "video=21.0/s (0.70x nominal 30.0) audio=47.0/s (1.00x nominal 46.9) "
        "window=5.0s polls=2 "
        "leg=none piece=none pos=none leg_rt=none path=none "
        "queues=none decoders=none qos=0 in 30s"
    )


# --- item 3: the bound-exceeded line names the witness ----------------------


def test_bound_exceeded_line_prefers_the_lag_witness(engine_module: Any) -> None:
    """The clause is chosen by measurement quality: the lag witness reports the
    deficit in SECONDS -- the same quantity as the spread -- so it wins over the
    rate witness, which only says the instantaneous rate was low at some point.
    With neither fired the line is byte-identical to round 4's."""
    _require_round_four_b(object.__new__(engine_module.GstPlayoutEngine))
    engine = object.__new__(engine_module.GstPlayoutEngine)
    build = engine._bound_exceeded_warn_line
    ends = [("video", 8_998_836_000_000), ("audio", 9_002_936_000_000)]

    engine._u59_lag_fired_t = 988.0
    engine._u59_fired_t = None
    lag_only = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert "video delivery fell short at the end of the leg" in lag_only
    assert "(leg delivery lag fired 12.0s ago)" in lag_only

    engine._u59_lag_fired_t = 995.0
    engine._u59_fired_t = 990.0
    both = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert "(leg delivery lag fired 5.0s ago)" in both

    engine._u59_lag_fired_t = None
    engine._u59_fired_t = 988.0
    rate_only = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert "(leg chain-in video below floor 12.0s ago)" in rate_only

    engine._u59_lag_fired_t = 800.0
    engine._u59_fired_t = 800.0
    stale = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert stale == (
        "WARN: reload switch-at-shorter-leg bound exceeded reload_id=7 "
        "spread=4.100s > 2.000s; keeping the longer-leg end (no trim) "
        "video_end=8998.836 audio_end=9002.936"
    )


# --- item 1: the hunks are wired into the live paths ------------------------


def test_round_four_b_is_wired_into_the_live_paths(engine_module: Any) -> None:
    engine_type = engine_module.GstPlayoutEngine

    progress = inspect.getsource(engine_type._maybe_print_output_progress)
    assert "self._u59_judge_leg_lag(now)" in progress
    # it accumulates THIS interval's deltas, so it must run before the snapshot
    assert progress.index("self._u59_judge_leg_lag(now)") < progress.index(
        "self._snapshot_chain_input()"
    )

    assert "_u59_lag_interval_t = 0.0" in inspect.getsource(engine_type._u59_init_diagnostics)
    assert "self._u59_leg_suffix(now, leg)" in inspect.getsource(engine_type._u59_warn_line)
    assert "self._u59_leg_suffix(now, leg)" in inspect.getsource(engine_type._u59_lag_line)
    assert "self._u59_leg_delivery_clause(moment)" in inspect.getsource(
        engine_type._bound_exceeded_warn_line
    )
