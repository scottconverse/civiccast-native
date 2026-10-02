# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U59 round 4 -- the changeover leg-rate diagnostic, RED/GREEN.

The defect this instruments (live 2026-09-27 19:15, one occurrence in ~60
C9/C10 changeovers): during a bounded changeover the retiring leg's video
DELIVERY collapses to ~0.79x nominal for ~21s and then steps to ~23fps while
its audio keeps flowing. Round 3 proved the media is clean -- the source and
every conform decode clean at every offset -- so the collapse is in delivery,
not in the asset, and round 4 fires on the delivery rate itself.

The judge is ``GstPlayoutEngine._u59_judge_leg_rate``, reached from the CTRL
output poll (``_maybe_print_output_progress``) and reading the U30 flow ladder's
``sel`` rung: the selector's src pad, i.e. the stream the channel is actually
AIRING. ``sel`` leads the rung preference because during a deferral rung ``in``
names the INCOMING leg (held and therefore silent, which the audio guard would
read as "not this defect") while the collapse sits on the RETIRING leg -- the
leg ``in`` stops naming once the switch commits.

Every test asserts the POSITIVE -- a WARN line the round-4 engine prints and the
pre-round-4 LIVE bytes do not -- so this file is RED against
``8a3722c9cb2025c5`` and GREEN after the round-4 hunks. Tests that assert a
silence carry their own positive control on the same engine for the same reason:
an absence-only test passes against an engine that prints nothing at all.

No station is touched and no real GStreamer is required: the engine is a bare
``object.__new__`` shape and the "leg" is a synthetic element list, exactly the
shapes the fake-``Gst`` harness in
``test_gst_engine_reload_commit_ordering`` already builds.
"""

from __future__ import annotations

import inspect
import types
from typing import Any

import pytest

from tests.egress.test_gst_engine_reload_commit_ordering import (  # noqa: F401
    _FakeDiagnosticPad,
    _FakeProbeBuffer,
    _FakeProbeInfo,
    _Recorder,
    engine_module,
)

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"

# Nominal rates the live engine measures: 30 video buffers/s (a 30fps station
# segment) and 46.875 audio buffers/s (AAC: 1024 samples at 48kHz).
_VIDEO_NOMINAL = 30.0
_AUDIO_NOMINAL = 48000.0 / 1024.0
_POLL_S = 5.0
_RUNG = "sel"

# Per-poll buffer counts that ride just under/over the two floors.
_VIDEO_STARVED = 105  # 21.0/s = 0.70x nominal -- below the 0.9 floor
_VIDEO_HEALTHY = 150  # 30.0/s = 1.00x nominal
_AUDIO_HEALTHY = 235  # 47.0/s = 1.00x nominal -- above the 0.97 floor
_AUDIO_DOWN = 210  # 42.0/s = 0.90x nominal -- below the 0.97 floor


class _RecorderlessPad(_FakeDiagnosticPad):
    """A ladder pad: the harness's diagnostic pad is all this needs to be."""

    def __init__(self, name: str) -> None:
        super().__init__(name, _Recorder())


class _Caps:
    def __init__(self, text: str) -> None:
        self._text = text

    def to_string(self) -> str:
        return self._text


class _Factory:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class _Element:
    """A GStreamer element as ``_u59_leg_record`` reads one.

    The record walks ``pending['new_elements']`` in build order and asks each
    element only for its factory name, its name, and (for a ``filesrc``) its
    ``location``; the capsfilters additionally report their negotiated caps
    through their src pad, which is where the nominal rates come from."""

    def __init__(
        self,
        factory: str,
        name: str,
        props: dict[str, Any] | None = None,
        *,
        src_caps: str | None = None,
    ) -> None:
        self._factory = _Factory(factory)
        self._name = name
        self._props = dict(props or {})
        self._src_caps = _Caps(src_caps) if src_caps is not None else None

    def get_factory(self) -> _Factory:
        return self._factory

    def get_name(self) -> str:
        return self._name

    def get_property(self, key: str) -> Any:
        return self._props.get(key)

    def get_static_pad(self, name: str) -> Any:
        if name != "src" or self._src_caps is None:
            return None
        return types.SimpleNamespace(get_current_caps=lambda: self._src_caps)


class _Concat:
    """The leg's video concat: its ``sinkpads`` are the per-piece pads whose
    index is the piece index, and the record arms one observe-only probe on
    each."""

    def __init__(self, name: str, pads: list[Any]) -> None:
        self._factory = _Factory("concat")
        self._name = name
        self.sinkpads = pads

    def get_factory(self) -> _Factory:
        return self._factory

    def get_name(self) -> str:
        return self._name


class _Selector:
    """``active-pad`` is the identity ``_u59_airing_leg`` matches first."""

    def __init__(self, active: Any) -> None:
        self._active = active

    def get_property(self, key: str) -> Any:
        return self._active if key == "active-pad" else None


class _Structure:
    def __init__(self, fields: dict[str, Any]) -> None:
        self._fields = dict(fields)

    def has_field(self, key: str) -> bool:
        return key in self._fields

    def get_value(self, key: str) -> Any:
        return self._fields[key]


class _QosMessage:
    def __init__(self, src_name: str, fields: dict[str, Any]) -> None:
        self.src = types.SimpleNamespace(get_name=lambda: src_name)
        self._structure = _Structure(fields)

    def get_structure(self) -> _Structure:
        return self._structure


def _diagnostic_engine(module: types.ModuleType, *, start_t: float = 1000.0) -> Any:
    """A bare engine with the ladder, mux counters and diagnostic state the
    round-4 judge reads. Nothing here is round-4-specific except the state the
    diagnostic keeps, so the same shape drives the pre-round-4 engine too."""
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
    return engine


def _poll(engine: Any, *, now: float, video: int, audio: int) -> None:
    """One CTRL output poll: the ladder advances by ``video``/``audio`` buffers
    over the interval, then the REAL progress method runs. Everything below
    the judge -- the snapshot, the CTRL line -- is production code."""
    engine._chain_input_buffers[(_RUNG, "video")] += video
    engine._chain_input_buffers[(_RUNG, "audio")] += audio
    engine._output_buffers += video + audio
    engine._maybe_print_output_progress(now)


def _judge(engine: Any, *, now: float, video: int, audio: int) -> None:
    """One poll driven at a cadence the 5s progress gate would suppress.

    The rate-limit floor has to hold independently of the poll cadence, so this
    calls the judge directly (and moves the baseline itself, the one thing
    ``_maybe_print_output_progress`` does after the judge)."""
    engine._chain_input_buffers[(_RUNG, "video")] += video
    engine._chain_input_buffers[(_RUNG, "audio")] += audio
    judge = getattr(engine, "_u59_judge_leg_rate", None)
    if callable(judge):
        judge(now)
    engine._chain_input_snapshot = dict(engine._chain_input_buffers)


def _starvation_lines(captured: Any) -> list[str]:
    return [
        line
        for line in captured.err.splitlines()
        if line.startswith("WARN: leg chain-in video below floor")
    ]


def _require_round_four(engine: Any, name: str) -> Any:
    method = getattr(engine, name, None)
    if not callable(method):
        pytest.fail(f"round 4 method {name} is absent from the engine")
    return method


# --- item 1: the line fires on a video-only collapse ------------------------


def test_video_starvation_fires_one_warn_line(engine_module: Any, capsys: Any) -> None:
    engine = _diagnostic_engine(engine_module)

    _poll(engine, now=1005.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert _starvation_lines(capsys.readouterr()) == [], "one poll is not an episode"

    _poll(engine, now=1010.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    lines = _starvation_lines(capsys.readouterr())
    assert len(lines) == 1, f"expected exactly one line, got {lines!r}"

    line = lines[0]
    assert "reload_id=none" in line  # no leg recorded yet
    assert "rung=sel" in line
    assert "video=21.0/s (0.70x nominal 30.0)" in line
    assert "audio=47.0/s (1.00x nominal 46.9)" in line
    assert "window=5.0s polls=2" in line
    assert "leg=none piece=none pos=none leg_rt=none" in line
    assert "path=none" in line
    assert "queues=none" in line
    assert "decoders=none" in line
    assert "qos=0 in 30s" in line

    # latched for the episode: the next starved poll prints nothing more
    _poll(engine, now=1015.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert _starvation_lines(capsys.readouterr()) == []


def test_a_single_low_poll_does_not_fire(engine_module: Any, capsys: Any) -> None:
    engine = _diagnostic_engine(engine_module)

    for index in range(6):
        video = _VIDEO_STARVED if index % 2 == 0 else _VIDEO_HEALTHY
        _poll(engine, now=1005.0 + index * _POLL_S, video=video, audio=_AUDIO_HEALTHY)
    assert _starvation_lines(capsys.readouterr()) == [], "the streak must reset"

    # positive control on the same engine: two consecutive starved polls fire
    _poll(engine, now=1035.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    _poll(engine, now=1040.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert len(_starvation_lines(capsys.readouterr())) == 1


def test_both_streams_down_together_is_not_this_defect(engine_module: Any, capsys: Any) -> None:
    """The box-wide contention shape: video down and audio down with it. The
    audio guard is what keeps this out of the log -- it is a different defect
    and must not be reported as this one."""
    engine = _diagnostic_engine(engine_module)

    for index in range(6):
        _poll(
            engine,
            now=1005.0 + index * _POLL_S,
            video=_VIDEO_STARVED,
            audio=_AUDIO_DOWN,
        )
    assert _starvation_lines(capsys.readouterr()) == []

    # positive control: audio recovers, video stays down -> now it fires
    _poll(engine, now=1035.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    _poll(engine, now=1040.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert len(_starvation_lines(capsys.readouterr())) == 1


def test_no_rung_no_judgement(engine_module: Any, capsys: Any) -> None:
    """Both streams must be readable from the SAME rung: a video reading
    compared against an absent audio one is not a comparison."""
    engine = _diagnostic_engine(engine_module)
    del engine._chain_input_pads[(_RUNG, "audio")]

    for index in range(4):
        _poll(engine, now=1005.0 + index * _POLL_S, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert _starvation_lines(capsys.readouterr()) == []

    # positive control: complete the ladder and the same traffic fires
    engine._chain_input_pads[(_RUNG, "audio")] = _RecorderlessPad("program_audio_sel_src")
    _poll(engine, now=1025.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    _poll(engine, now=1030.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert len(_starvation_lines(capsys.readouterr())) == 1


def test_the_rate_limit_floor_holds_at_a_denser_poll_cadence(
    engine_module: Any, capsys: Any
) -> None:
    """One line per episode, and at most one per 10s. Driven at a 1s cadence so
    the floor is exercised as a floor and not as a side effect of the 5s
    progress interval; an episode suppressed by the floor is not latched, so it
    prints as soon as the floor allows while it is still running."""
    engine = _diagnostic_engine(engine_module)
    _require_round_four(engine, "_u59_judge_leg_rate")

    _judge(engine, now=1001.0, video=21, audio=47)
    _judge(engine, now=1002.0, video=21, audio=47)  # fires: t=1002
    assert len(_starvation_lines(capsys.readouterr())) == 1

    _judge(engine, now=1003.0, video=30, audio=47)  # healthy: episode ends
    # 1s cadence all the way through, so the measured rates stay 0.70x video /
    # 1.00x audio and the 10s floor is what suppresses the print. A coarser step
    # would divide the audio count by a longer interval, drop it under its own
    # floor, and end the episode for a reason that has nothing to do with the
    # rate limit being tested.
    for now in (1004.0, 1005.0, 1006.0, 1007.0, 1008.0, 1009.0, 1010.0, 1011.0):
        _judge(engine, now=now, video=21, audio=47)  # streak 2 by 1005, inside the floor
    assert _starvation_lines(capsys.readouterr()) == []

    _judge(engine, now=1012.0, video=21, audio=47)  # 10s since the fire
    assert len(_starvation_lines(capsys.readouterr())) == 1


def test_the_kill_switch_silences_the_line(engine_module: Any, capsys: Any, monkeypatch: Any) -> None:
    engine = _diagnostic_engine(engine_module)
    monkeypatch.setenv("CIVICAST_GST_LEG_RATE_DIAG", "0")

    for index in range(4):
        _poll(engine, now=1005.0 + index * _POLL_S, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert _starvation_lines(capsys.readouterr()) == []

    # positive control: the same engine, unset -> armed again
    monkeypatch.delenv("CIVICAST_GST_LEG_RATE_DIAG")
    _poll(engine, now=1025.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    _poll(engine, now=1030.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    assert len(_starvation_lines(capsys.readouterr())) == 1


# --- item 1: the line's per-leg fields --------------------------------------


def _leg_pending(video_pad: Any, recorder: _Recorder) -> dict[str, Any]:
    """One program leg as the build returns it: two pieces, a decoder in each,
    a queue, both capsfilters, and the video concat the pieces feed."""
    return {
        "txn_id": 42,
        "new_video_pad": video_pad,
        "new_elements": [
            _Element("filesrc", "filesrc0", {"location": "C:/egress/seg-0001.ts"}),
            _Element("decodebin", "decodebin0"),
            _Element(
                "queue",
                "program_video_queue",
                {"current-level-buffers": 3, "current-level-time": 41_000_000},
            ),
            _Element(
                "capsfilter",
                "video_caps0",
                src_caps="video/x-raw,width=1920,height=1080,framerate=(fraction)30/1",
            ),
            _Element(
                "capsfilter",
                "audio_caps0",
                src_caps="audio/mpeg,mpegversion=(int)4,rate=(int)48000,channels=(int)2",
            ),
            _Element("filesrc", "filesrc1", {"location": "C:/egress/seg-0002.ts"}),
            _Element("decodebin", "decodebin1"),
            _Concat(
                "vconcat_program_7",
                [
                    _FakeDiagnosticPad("sink_0", recorder),
                    _FakeDiagnosticPad("sink_1", recorder),
                ],
            ),
        ],
    }


def test_the_line_names_the_leg_piece_path_queues_decoders_and_qos(
    engine_module: Any, capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.delenv("CIVICAST_GST_LEG_RATE_DIAG", raising=False)
    engine = _diagnostic_engine(engine_module)
    _require_round_four(engine, "_u59_record_leg")
    recorder = _Recorder()
    video_pad = _RecorderlessPad("program_video_sel_sink_1")
    pending = _leg_pending(video_pad, recorder)
    engine.selector = _Selector(video_pad)

    engine._u59_record_leg(pending)
    assert len(engine._u59_legs) == 1

    concat = pending["new_elements"][-1]
    # The pieces stream: piece 1 runs 0..100s, then piece 2 runs 0..30s, so piece
    # 2 is the piece the line reports. Both pieces are fired here inside the same
    # ``time.monotonic()`` tick (the clock is far coarser than this loop), which
    # also pins the tie-break: on equal activity the LATER piece wins, because
    # pieces stream in playlist order. Firing the recorded probes is what a
    # streaming thread does.
    for pad, first, last in (
        (concat.sinkpads[0], 0, 100_000_000_000),
        (concat.sinkpads[1], 0, 30_000_000_000),
    ):
        assert pad.probes, "the record must arm one observe-only probe per piece"
        _mask, callback = pad.probes[0]
        callback(pad, _FakeProbeInfo(_FakeProbeBuffer(first)))
        callback(pad, _FakeProbeInfo(_FakeProbeBuffer(last)))

    engine._u59_record_qos(
        _QosMessage("tsdemux0", {"jitter": 0.05, "proportion": 1.0, "dropped": 12})
    )

    start = engine._u59_rate_interval_t
    _poll(engine, now=start + 5.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    _poll(engine, now=start + 10.0, video=_VIDEO_STARVED, audio=_AUDIO_HEALTHY)
    lines = _starvation_lines(capsys.readouterr())
    assert len(lines) == 1, f"expected exactly one line, got {lines!r}"

    line = lines[0]
    assert "reload_id=42" in line
    assert "leg=program" in line
    assert "piece=2/2" in line
    assert "pos=30.000s" in line
    assert "leg_rt=130.000s" in line
    assert "path=C:/egress/seg-0002.ts" in line
    assert "queues=program_video_queue=3buf/0.041s" in line
    assert "decoders=decodebin0,decodebin1" in line
    assert "qos=1 in 30s [tsdemux0,jit=0.0500,prop=1.0000,drop=12]" in line
    # the leg's OWN nominal rates, read from its capsfilters
    assert "(0.70x nominal 30.0)" in line
    assert "nominal 46.9" in line


# --- item 2: the bound-exceeded line states what was measured ---------------


def test_bound_exceeded_line_names_the_measured_ends(engine_module: Any) -> None:
    engine = object.__new__(engine_module.GstPlayoutEngine)
    line = _require_round_four(engine, "_bound_exceeded_warn_line")(
        {"txn_id": 42},
        [("video", 8_998_836_000_000), ("audio", 9_002_936_000_000)],
        4_100_000_000,
        now=1000.0,
    )
    assert line.startswith("WARN: reload switch-at-shorter-leg bound exceeded")
    assert "reload_id=42" in line
    assert "spread=4.100s" in line
    assert "> 2.000s;" in line
    assert "keeping the longer-leg end (no trim)" in line
    assert "video_end=8998.836" in line
    assert "audio_end=9002.936" in line
    # the round-3 refuted claim is gone: the line no longer asserts a cause
    assert "a truly broken asset" not in line
    assert "video delivery fell short" not in line


def test_bound_exceeded_line_says_short_delivery_after_a_recent_fire(
    engine_module: Any,
) -> None:
    engine = object.__new__(engine_module.GstPlayoutEngine)
    build = _require_round_four(engine, "_bound_exceeded_warn_line")
    ends = [("video", 8_998_836_000_000), ("audio", 9_002_936_000_000)]

    engine._u59_fired_t = 988.0
    recent = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert "video delivery fell short at the end of the leg" in recent
    assert "(leg chain-in video below floor 12.0s ago)" in recent

    engine._u59_fired_t = 800.0
    stale = build({"txn_id": 7}, ends, 4_100_000_000, now=1000.0)
    assert "video delivery fell short" not in stale


# --- item 1: the hunks are wired into the live paths ------------------------


def test_round_four_is_wired_into_the_live_paths(engine_module: Any) -> None:
    engine_type = engine_module.GstPlayoutEngine

    progress = inspect.getsource(engine_type._maybe_print_output_progress)
    assert "self._u59_judge_leg_rate(now)" in progress
    # the judge must read the baseline the LAST print left behind, so it runs
    # before this poll's snapshot
    assert progress.index("self._u59_judge_leg_rate(now)") < progress.index(
        "self._snapshot_chain_input()"
    )

    on_bus = inspect.getsource(engine_type._on_bus)
    assert "self._u59_record_qos(message)" in on_bus
    # the harness's fake MessageType has no QOS, and neither does an older
    # GStreamer: an unguarded attribute read here would raise on every message
    assert 'getattr(Gst.MessageType, "QOS", None)' in on_bus

    assert "self._u59_record_leg(pending)" in inspect.getsource(
        engine_type._arm_new_leg_selector_diagnostics
    )
    assert "self._u59_init_diagnostics()" in inspect.getsource(engine_type.__init__)

    commit = inspect.getsource(engine_type._begin_reload_commit)
    assert "self._bound_exceeded_warn_line(pending, measured_ends, switch_spread_ns)" in commit
    assert "a truly broken asset must stay visible" not in commit
