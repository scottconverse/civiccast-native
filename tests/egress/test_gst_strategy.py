# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for graph JSON round-trip + GstPlayoutStrategy seam (Windows; no gi)."""

from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from civiccast.egress.encoder_strategy import EncoderStartRequest
from civiccast.egress.errors import EncoderUnavailableError
from civiccast.egress.gst import strategy as strategy_module
from civiccast.egress.gst.control import (
    align_live_caption_pts_ms,
    caption_gap_window_ms,
    install_unix_signal_handlers,
    parse_control_line,
)
from civiccast.egress.gst.graph import (
    AudioTapLeg,
    ElementSpec,
    PlaylistLeg,
    PlayoutGraph,
    SourceLeg,
    coerce_serialized_property,
    demo_test_graph,
    graph_from_json,
    graph_to_json,
)
from civiccast.egress.gst.strategy import GstPlayoutStrategy, _WindowsPipeChannel
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)

# The D2 seam gave GstPlayoutStrategy.start() a real os.name=='nt' branch that
# opens a Win32 named pipe. Two disjoint groups of tests below react to that:
#
#  * Graph-content tests assert only the serialized playout graph -- platform-
#    agnostic. They inject _fake_pipe_channel_factory so start()'s nt-branch
#    never touches a real pipe; the graph assertions are unchanged.
#  * FIFO control-path tests assert the POSIX/WSL FIFO contract (a control line
#    lands in the channel FIFO; the worker is told its FIFO path). On native
#    Windows the code correctly takes the pipe branch instead, so those FIFO
#    assertions don't apply -- they carry @_POSIX_FIFO_ONLY and run on ubuntu
#    CI (os.name=='posix'); the Windows pipe path is covered end-to-end by
#    tests/egress/test_worker_pipe_seam.py.

_POSIX_FIFO_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "POSIX/WSL FIFO control-path contract; the native-Windows worker-pipe path is "
        "covered by tests/egress/test_worker_pipe_seam.py and this contract runs on "
        "ubuntu CI where os.name=='posix'."
    ),
)


class _FakePipeChannel:
    """Structural stand-in for the real D2 :class:`_WindowsPipeChannel` so the
    platform-agnostic graph-building assertions can exercise
    ``GstPlayoutStrategy.start()``'s ``os.name=='nt'`` branch on the Windows dev
    box without opening a real Win32 named pipe."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.sent: list[tuple[str, str, str | None]] = []

    def start(self) -> None:
        pass

    def send_and_wait(
        self,
        verb: str,
        line: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        self.sent.append((verb, line, command_id))
        return True

    def close(self) -> None:
        pass


def _fake_pipe_channel_factory(channel_id: str) -> _WindowsPipeChannel:
    return cast(_WindowsPipeChannel, _FakePipeChannel(channel_id))


def test_graph_json_round_trip_sourceleg() -> None:
    graph = demo_test_graph(out="/tmp/x.ts", nsrc=3)
    restored = graph_from_json(graph_to_json(graph))
    assert len(restored.sources) == 3
    assert all(isinstance(s, SourceLeg) for s in restored.sources)
    assert restored.mux.factory == "mpegtsmux"
    assert restored.sinks[0][-1].factory == "filesink"
    assert restored.encoder[-1].factory == graph.encoder[-1].factory


def test_serialized_caps_property_is_coerced_for_live_appsrc() -> None:
    converted: list[str] = []

    value = coerce_serialized_property(
        key="caps",
        value="text/x-raw,format=(string)utf8",
        caps_from_string=lambda text: converted.append(text) or "GST_CAPS",
    )

    assert value == "GST_CAPS"
    assert converted == ["text/x-raw,format=(string)utf8"]


def test_graph_json_round_trip_playlist() -> None:
    graph = PlayoutGraph(
        sources=(
            PlaylistLeg(
                "program",
                (
                    (
                        ElementSpec("filesrc", props={"location": "/m/a.ts"}),
                        ElementSpec("decodebin"),
                    ),
                ),
            ),
            SourceLeg("slate", (ElementSpec("videotestsrc", props={"pattern": 2}),)),
        ),
        encoder=(ElementSpec("x264enc", props={"bitrate": 4000}),),
        mux=ElementSpec("mpegtsmux", name="mux"),
        sinks=((ElementSpec("queue"), ElementSpec("filesink", props={"location": "/tmp/o.ts"})),),
    )
    restored = graph_from_json(graph_to_json(graph))
    assert isinstance(restored.sources[0], PlaylistLeg)
    assert restored.sources[0].subchains[0][0].props["location"] == "/m/a.ts"
    assert isinstance(restored.sources[1], SourceLeg)
    assert restored.sources[1].elements[0].props["pattern"] == 2
    assert restored.encoder[0].props["bitrate"] == 4000


def test_graph_json_round_trip_with_audio() -> None:
    from civiccast.egress.gst.graph import audio_encode_specs

    graph = PlayoutGraph(
        sources=(
            SourceLeg(
                "a",
                (ElementSpec("videotestsrc"),),
                audio=(ElementSpec("audiotestsrc"),),
            ),
        ),
        encoder=(ElementSpec("x264enc"),),
        audio_encoder=audio_encode_specs(),
        audio_tap=AudioTapLeg(tap_dir="/var/lib/civiccast/tap/ch1", segment_seconds=5.0),
        mux=ElementSpec("mpegtsmux", name="mux"),
        sinks=((ElementSpec("filesink", props={"location": "/tmp/o.ts"}),),),
    )
    restored = graph_from_json(graph_to_json(graph))
    assert restored.sources[0].audio[0].factory == "audiotestsrc"
    assert restored.audio_encoder[-1].factory == "aacparse"
    assert restored.audio_tap == AudioTapLeg(
        tap_dir="/var/lib/civiccast/tap/ch1",
        segment_seconds=5.0,
    )


@_POSIX_FIFO_ONLY
def test_strategy_start_builds_graph_and_launches_worker(tmp_path) -> None:
    launched: dict = {}

    def fake_launcher(argv, stdout_path, stderr_path):
        launched["argv"] = argv
        launched["stdout"] = stdout_path
        return SimpleNamespace(pid=4321, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(worker_launcher=fake_launcher, python_executable="python3")
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="ch1",
        segments=[EgressSourceSegment(label="c1", path="/m/c1.ts", duration_seconds=10)],
    )
    request = EncoderStartRequest(
        channel_id="ch1", source_plan=plan, config=config, work_dir=tmp_path
    )
    result = strategy.start(request)

    # the serialized graph was written and contains the program + sink elements
    assert result.concat_plan_path.exists()
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "mpegtsmux" in graph_text
    assert "filesrc" in graph_text
    assert "udpsink" in graph_text
    # the worker was launched by file path with the graph path then control FIFO
    assert "worker.py" in launched["argv"][1]
    assert launched["argv"][2] == str(result.concat_plan_path)
    assert launched["argv"][0] == "python3"
    # the returned process is poll/pid-compatible for the daemon's reaper
    assert result.process.poll() is None
    assert result.process.pid == 4321
    # the worker is told its control FIFO (last argv) for reload→swap
    assert launched["argv"][-1] == str(strategy.control_fifo_path(request.work_dir, "ch1"))


def test_parse_control_line() -> None:
    assert parse_control_line("swap 2") == ("swap", 2)
    assert parse_control_line("  swap 0 ") == ("swap", 0)
    assert parse_control_line("stop") == ("stop",)
    assert parse_control_line("") is None
    assert parse_control_line("garbage") is None
    assert parse_control_line("swap x") is None
    assert parse_control_line("swap 1 2") is None


def test_parse_control_line_caption() -> None:
    # "caption <pts_ms> <dur_ms> <b64text>" → ("caption", pts_ms, dur_ms, b64text)
    assert parse_control_line("caption 1200 800 SEVMTE8=") == ("caption", 1200, 800, "SEVMTE8=")
    assert parse_control_line("caption 0 500 QQ==") == ("caption", 0, 500, "QQ==")
    assert parse_control_line("caption 1200 800") is None  # missing the b64 field
    assert parse_control_line("caption x 800 SEVMTE8=") is None  # non-numeric pts
    assert parse_control_line("caption 1200 y SEVMTE8=") is None  # non-numeric dur
    assert parse_control_line("caption") is None


def test_live_caption_pts_rebases_a_late_asr_cue_to_the_live_edge() -> None:
    assert (
        align_live_caption_pts_ms(
            requested_pts_ms=1_000,
            running_time_ms=100_000,
        )
        == 100_250
    )


def test_live_caption_pts_preserves_a_future_cue() -> None:
    assert (
        align_live_caption_pts_ms(
            requested_pts_ms=110_000,
            running_time_ms=100_000,
        )
        == 110_000
    )


def test_live_caption_pts_never_overlaps_the_prior_caption_buffer() -> None:
    assert (
        align_live_caption_pts_ms(
            requested_pts_ms=1_000,
            running_time_ms=100_000,
            stream_position_ms=102_500,
        )
        == 102_500
    )


def test_caption_gap_window_advances_only_forward_to_the_live_edge() -> None:
    assert caption_gap_window_ms(stream_position_ms=250, running_time_ms=600) == (
        250,
        350,
    )
    assert caption_gap_window_ms(stream_position_ms=600, running_time_ms=600) is None
    assert caption_gap_window_ms(stream_position_ms=700, running_time_ms=600) is None


def test_windows_glib_without_unix_signal_api_skips_signal_registration() -> None:
    class _WindowsGLib:
        PRIORITY_DEFAULT = 0

    quit_calls: list[bool] = []

    assert (
        install_unix_signal_handlers(
            _WindowsGLib(),
            signal_numbers=(2, 15),
            quit_loop=lambda: quit_calls.append(True),
        )
        is False
    )
    assert quit_calls == []


def test_posix_glib_registers_each_worker_shutdown_signal() -> None:
    class _PosixGLib:
        PRIORITY_DEFAULT = 7

        def __init__(self) -> None:
            self.registrations: list[tuple[int, int, object]] = []

        def unix_signal_add(self, priority: int, signal_number: int, callback: object) -> None:
            self.registrations.append((priority, signal_number, callback))

    glib = _PosixGLib()

    assert (
        install_unix_signal_handlers(
            glib,
            signal_numbers=(2, 15),
            quit_loop=lambda: None,
        )
        is True
    )
    assert [(priority, number) for priority, number, _ in glib.registrations] == [
        (7, 2),
        (7, 15),
    ]


def test_parse_control_line_reload() -> None:
    assert parse_control_line("reload /tmp/ch1/playout-graph.reload.json") == (
        "reload",
        "/tmp/ch1/playout-graph.reload.json",
    )
    # a path with spaces is preserved (the remainder of the line, not split-truncated)
    assert parse_control_line("reload /tmp/my work/g.json") == (
        "reload",
        "/tmp/my work/g.json",
    )
    assert parse_control_line("reload") is None  # missing path
    assert parse_control_line("reload   ") is None


@_POSIX_FIFO_ONLY
def test_send_command_writes_control_line(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    path = strategy.control_fifo_path(tmp_path, "ch1")
    path.touch()  # send_command writes to an existing FIFO (the worker creates it)
    assert strategy.send_command(tmp_path, "ch1", "swap 1") is True
    assert path.read_text(encoding="utf-8").strip() == "swap 1"


def test_send_command_drops_when_fifo_missing(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    # no FIFO yet (worker not started) → drop, do not raise (audit M2)
    assert strategy.send_command(tmp_path, "ch1", "swap 1") is False


@_POSIX_FIFO_ONLY
def test_swap_role_maps_to_fifo_command(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    assert strategy.supports_live_swap is True
    (tmp_path / "ch1").mkdir()
    path = strategy.control_fifo_path(tmp_path, "ch1")
    path.touch()
    strategy.swap_role("ch1", tmp_path, "slate")
    assert path.read_text(encoding="utf-8").strip() == "swap 1"
    strategy.swap_role("ch1", tmp_path, "program")
    assert path.read_text(encoding="utf-8").strip().splitlines()[-1] == "swap 0"


def test_swap_role_rejects_unknown_role(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    with pytest.raises(ValueError, match="unknown source role"):
        strategy.swap_role("ch1", tmp_path, "bogus")


def test_swap_role_has_no_live_pad(tmp_path) -> None:
    # S16/step-9: CivicCast airs a single pre-switched live feed, so there is no
    # always-hot 'live' selector pad — a live takeover is a seamless content-reload
    # of the program leg, driven by the supervisor. 'live' is therefore an unknown
    # pad role here (not a NotImplementedError stub), and never reaches swap_role.
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    with pytest.raises(ValueError, match="unknown source role"):
        strategy.swap_role("ch1", tmp_path, "live")


def _reload_request(tmp_path, *, path: str = "/m/c2.ts", label: str = "c2"):
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="ch1",
        segments=[EgressSourceSegment(label=label, path=path, duration_seconds=10)],
    )
    return EncoderStartRequest(channel_id="ch1", source_plan=plan, config=config, work_dir=tmp_path)


def test_supports_content_reload_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 3 (beta.5 gate): owner decision 2026-09-06 -- the seamless in-place
    content-reload defaults ON so a plan rollover is an in-place reload with no
    worker restart. A channel that sets ``CIVICCAST_EGRESS_SEAMLESS_RELOAD=0``
    opts out and falls back to the daemon's terminate+restart reload path."""
    monkeypatch.delenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", raising=False)
    assert GstPlayoutStrategy(worker_launcher=lambda *a: None).supports_content_reload is True


def test_supports_content_reload_env_var_opts_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", "0")
    assert GstPlayoutStrategy(worker_launcher=lambda *a: None).supports_content_reload is False


@pytest.mark.parametrize("falsy_value", ["0", "false", "False", "no", "off", "OFF"])
def test_supports_content_reload_env_var_opt_out_values(
    monkeypatch: pytest.MonkeyPatch, falsy_value: str
) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", falsy_value)
    assert GstPlayoutStrategy(worker_launcher=lambda *a: None).supports_content_reload is False


def test_supports_content_reload_env_var_truthy_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", "1")
    assert GstPlayoutStrategy(worker_launcher=lambda *a: None).supports_content_reload is True


def test_supports_content_reload_explicit_constructor_arg_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", "0")
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None, supports_content_reload=True)
    assert strategy.supports_content_reload is True


def test_supports_content_reload_explicit_constructor_false_wins_over_truthy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_SEAMLESS_RELOAD", "1")
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None, supports_content_reload=False)
    assert strategy.supports_content_reload is False


def test_reload_ack_timeout_is_the_same_small_default_as_every_other_verb() -> None:
    """F1 redesign (F9): item 4's original widened bound (the worker's own
    reload_timeout_s plus a margin) was itself a bug -- a reload's ack now
    means only "armed" (fast, like any other verb), with the eventual settle
    outcome reported out-of-band (reload-status.json), so this bound must be
    back to the plain default and must NOT vary with
    CIVICCAST_RELOAD_TIMEOUT_S (the env var item 4 used to read here)."""
    assert strategy_module._reload_ack_timeout_s() == strategy_module._WORKER_PIPE_ACK_TIMEOUT_S


def test_reload_ack_timeout_ignores_the_old_reload_timeout_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_RELOAD_TIMEOUT_S", "900")
    assert strategy_module._reload_ack_timeout_s() == strategy_module._WORKER_PIPE_ACK_TIMEOUT_S


@_POSIX_FIFO_ONLY
def test_reload_content_writes_graph_and_sends_reload_command(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    fifo = strategy.control_fifo_path(tmp_path, "ch1")
    fifo.touch()  # worker present: send_command writes the line

    applied = strategy.reload_content("ch1", tmp_path, _reload_request(tmp_path))

    assert applied is True
    # ENG-005: the reload graph is written to a unique per-reload filename
    reload_graphs = list((tmp_path / "ch1").glob("playout-graph.reload.*.json"))
    assert len(reload_graphs) == 1
    reload_graph = reload_graphs[0]
    graph_text = reload_graph.read_text(encoding="utf-8")
    assert "/m/c2.ts" in graph_text and "mpegtsmux" in graph_text
    command = fifo.read_text(encoding="utf-8").strip()
    assert command == f"reload {reload_graph}"


def test_reload_content_drops_when_worker_not_ready(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *args: None)
    (tmp_path / "ch1").mkdir()
    # no FIFO (worker not started) → returns False so the daemon falls back to restart
    assert strategy.reload_content("ch1", tmp_path, _reload_request(tmp_path)) is False


# --- coordinator follow-up: daemon._try_content_reload's silent False (diagnosability) --


def test_last_send_command_failure_reason_none_before_any_call() -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None)
    assert strategy.last_send_command_failure_reason("ch1") is None


def test_last_send_command_failure_reason_reports_worker_not_started(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None)
    # No pipe channel ever registered for "ch1" (start() was never called).
    applied = strategy.send_command(tmp_path, "ch1", "swap 1")

    assert applied is False
    reason = strategy.last_send_command_failure_reason("ch1")
    assert reason is not None and "not started" in reason


def test_last_send_command_failure_reason_reports_the_workers_ack(tmp_path) -> None:
    """A channel whose worker connected but explicitly declined the command
    (e.g. a reload that aborted -- item 4's "aborted:<reason>" ack) surfaces
    THAT text, not just a bare False."""

    class _DecliningPipeChannel:
        def __init__(self, channel_id: str) -> None:
            self.channel_id = channel_id
            self.last_failure_reason: str | None = None

        def start(self) -> None:
            pass

        def send_and_wait(self, verb, line, *, command_id=None) -> bool:
            self.last_failure_reason = "worker acked 'aborted:timeout'"
            return False

        def close(self) -> None:
            pass

    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: None,
        pipe_channel_factory=lambda channel_id: cast(
            _WindowsPipeChannel, _DecliningPipeChannel(channel_id)
        ),
        # This test exercises the Windows D2 named-pipe control path
        # specifically (bug fix, coordinator hostile review 2026-09-06:
        # start()/send_command() used to branch on the real os.name instead
        # of this injectable seam, so this test silently exercised the FIFO
        # branch instead on a POSIX CI runner and failed there).
        is_windows=True,
    )
    strategy.start(_start_request(tmp_path))

    applied = strategy.send_command(tmp_path, "ch1", "reload /w/g.json")

    assert applied is False
    assert strategy.last_send_command_failure_reason("ch1") == "worker acked 'aborted:timeout'"


def test_last_send_command_failure_reason_clears_on_a_later_success(tmp_path) -> None:
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: None,
        pipe_channel_factory=_fake_pipe_channel_factory,  # always succeeds
        is_windows=True,  # exercises the Windows D2 pipe path -- see the test above
    )
    strategy.start(_start_request(tmp_path))
    strategy._last_send_command_failure["ch1"] = "stale reason from a prior failure"

    applied = strategy.send_command(tmp_path, "ch1", "swap 1")

    assert applied is True
    assert strategy.last_send_command_failure_reason("ch1") is None


# --- S11a: CEA-708 caption embed toggle + cue feed ------------------------------


def _start_request(tmp_path):
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="ch1",
        segments=[EgressSourceSegment(label="c1", path="/m/c1.ts", duration_seconds=10)],
    )
    return EncoderStartRequest(channel_id="ch1", source_plan=plan, config=config, work_dir=tmp_path)


def test_cg_overlay_inserts_gdkpixbufoverlay_when_element_registered(tmp_path) -> None:
    # S15 §5 CG-lite: an active board's raster composites over the output half.
    from dataclasses import replace as dc_replace

    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        embed_captions=False,
        pipe_channel_factory=_fake_pipe_channel_factory,
        element_probe=lambda name: True,
    )
    board_png = tmp_path / "board.png"
    request = dc_replace(_start_request(tmp_path), cg_overlay_image=board_png)
    result = strategy.start(request)
    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    first = graph.encoder[0]
    assert first.factory == "gdkpixbufoverlay"
    assert first.props["location"] == str(board_png)


def test_cg_overlay_degrades_honestly_when_element_missing(tmp_path, caplog) -> None:
    import logging
    from dataclasses import replace as dc_replace

    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        embed_captions=False,
        pipe_channel_factory=_fake_pipe_channel_factory,
        element_probe=lambda name: False,
    )
    request = dc_replace(_start_request(tmp_path), cg_overlay_image=tmp_path / "board.png")
    with caplog.at_level(logging.WARNING, logger="civiccast.egress.gst.strategy"):
        result = strategy.start(request)
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "gdkpixbufoverlay" not in graph_text
    assert any("board overlay" in record.message for record in caplog.records), (
        "a requested-but-unavailable overlay must be announced, never silent"
    )


def test_no_board_leaves_graph_without_overlay(tmp_path) -> None:
    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        embed_captions=False,
        pipe_channel_factory=_fake_pipe_channel_factory,
        element_probe=lambda name: True,
    )
    result = strategy.start(_start_request(tmp_path))
    assert "gdkpixbufoverlay" not in result.concat_plan_path.read_text(encoding="utf-8")


def test_strategy_embed_captions_off_by_default(tmp_path) -> None:
    captured: dict = {}

    def fake_launcher(argv, *a):
        captured["argv"] = argv
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        embed_captions=False,
        pipe_channel_factory=_fake_pipe_channel_factory,
    )
    result = strategy.start(_start_request(tmp_path))
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "cccombiner" not in graph_text
    assert graph_from_json(graph_text).captions is None


def test_strategy_embed_captions_on_inserts_cc_elements(tmp_path) -> None:
    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        embed_captions=True,
        pipe_channel_factory=_fake_pipe_channel_factory,
    )
    result = strategy.start(_start_request(tmp_path))
    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert graph.captions is not None
    assert graph.captions.combiner.factory == "cccombiner"
    assert [s.factory for s in graph.captions.inserter_chain] == ["h264ccinserter", "h264parse"]
    assert graph.captions.caption_source[0].factory == "appsrc"


def test_strategy_builds_the_live_caption_audio_tap_into_the_gstreamer_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tap_root = tmp_path / "caption-tap"
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tap_root))
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_SEGMENT_SECONDS", "4.5")
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *_args: SimpleNamespace(
            pid=1, poll=lambda: None, terminate=lambda **_kwargs: 0
        ),
        pipe_channel_factory=_fake_pipe_channel_factory,
    )

    result = strategy.start(_start_request(tmp_path))

    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert graph.audio_tap == AudioTapLeg(
        tap_dir=str(tap_root / "ch1"),
        segment_seconds=4.5,
    )


def test_strategy_omits_the_audio_tap_when_live_captions_are_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 91 follow-up: the operator's ``StationProfile.live_captions_enabled``
    switch (and/or ``CIVICCAST_CAPTION_TAP=off``, which
    ``resolve_live_captions_enabled`` also folds in) must stop the egress
    audio-tap LEG at the next channel start, not just stop the tap worker
    from transcribing what it forked. Before this, a caption dir configured
    in the environment always produced a tap leg regardless of the
    operator's switch -- ``_with_audio_tap`` never consulted it."""

    tap_root = tmp_path / "caption-tap"
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tap_root))
    monkeypatch.setattr(
        "civiccast.installer.station_state.resolve_live_captions_enabled",
        lambda: False,
    )
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *_args: SimpleNamespace(
            pid=1, poll=lambda: None, terminate=lambda **_kwargs: 0
        ),
        pipe_channel_factory=_fake_pipe_channel_factory,
    )

    result = strategy.start(_start_request(tmp_path))

    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert graph.audio_tap is None


def test_strategy_start_survives_a_corrupt_station_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Item 91 review round 2 (BLOCKER): ``resolve_live_captions_enabled``
    reads ``station-state.json`` via ``_load_raw_state``, which only ever
    suppresses ``FileNotFoundError``/``json.JSONDecodeError`` -- a state file
    containing a byte that is not valid UTF-8 raises ``UnicodeDecodeError``
    straight through ``read_text(encoding="utf-8")``'s strict decode.
    MEASURED before this test's fix landed: that exception propagated out of
    ``GstPlayoutStrategy.start()`` and stopped the channel going to air over
    a corrupt status file for an entirely unrelated, best-effort,
    accessibility feature. ``_live_captions_enabled_or_default`` must catch
    this, log once, and default to the documented "on" instead."""

    strategy_module._live_captions_read_failure_announced = False
    state_path = tmp_path / "station-state.json"
    # A byte that is not valid UTF-8 anywhere (0xFF is invalid in every UTF-8
    # continuation/lead position) -- guarantees UnicodeDecodeError, not a
    # JSONDecodeError, which is already handled.
    state_path.write_bytes(b'{"station": {"live_captions_enabled": \xff}}')
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state_path))
    monkeypatch.delenv("CIVICCAST_CAPTION_TAP", raising=False)

    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *_args: SimpleNamespace(
            pid=1, poll=lambda: None, terminate=lambda **_kwargs: 0
        ),
        pipe_channel_factory=_fake_pipe_channel_factory,
    )

    with caplog.at_level("WARNING", logger="civiccast.egress.gst.strategy"):
        result = strategy.start(_start_request(tmp_path))  # must not raise

    assert "could not read the live-captions station-profile switch" in caplog.text
    # Defaults to the documented "on" -- unaffected by the read failure, the
    # graph still gets built normally (no CIVICCAST_CAPTION_TAP_DIR is set in
    # this test, so there is simply no tap plan; the point is start() did not
    # raise, not that a tap was built).
    graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))


def test_strategy_start_survives_a_locked_station_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Sibling of the corrupt-file case: a Windows sharing violation while
    another process holds ``station-state.json`` open surfaces as
    ``PermissionError`` (a subclass of ``OSError``), which
    ``_load_raw_state`` also does not suppress. Stubbed directly against
    ``resolve_live_captions_enabled`` (rather than a real file lock, which
    is awkward to arrange portably in a unit test) to prove the SAME guard
    catches an ``OSError`` family member, not just ``UnicodeDecodeError``."""

    strategy_module._live_captions_read_failure_announced = False

    def _raise_permission_error() -> bool:
        raise PermissionError(
            13, "The process cannot access the file because it is being used by another process"
        )

    monkeypatch.setattr(
        "civiccast.installer.station_state.resolve_live_captions_enabled",
        _raise_permission_error,
    )
    tap_root = tmp_path / "caption-tap"
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tap_root))

    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *_args: SimpleNamespace(
            pid=1, poll=lambda: None, terminate=lambda **_kwargs: 0
        ),
        pipe_channel_factory=_fake_pipe_channel_factory,
    )

    with caplog.at_level("WARNING", logger="civiccast.egress.gst.strategy"):
        result = strategy.start(_start_request(tmp_path))  # must not raise

    assert "could not read the live-captions station-profile switch" in caplog.text
    # Defaults to "on": the tap dir WAS configured, so the graph carries the
    # tap leg exactly as it would if the read had actually succeeded and
    # returned True.
    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert graph.audio_tap is not None


def test_strategy_builds_the_audio_tap_when_live_captions_stay_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling of the disabled case above: an explicit ``True`` (the default,
    an operator who never touched the switch) still builds the tap exactly
    as before -- the new check is a gate, not a behavior change for the
    common case."""

    tap_root = tmp_path / "caption-tap"
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tap_root))
    monkeypatch.setattr(
        "civiccast.installer.station_state.resolve_live_captions_enabled",
        lambda: True,
    )
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *_args: SimpleNamespace(
            pid=1, poll=lambda: None, terminate=lambda **_kwargs: 0
        ),
        pipe_channel_factory=_fake_pipe_channel_factory,
    )

    result = strategy.start(_start_request(tmp_path))

    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert graph.audio_tap is not None
    assert graph.audio_tap.tap_dir == str(tap_root / "ch1")


@_POSIX_FIFO_ONLY
def test_strategy_reload_carries_caption_leg_when_embedding(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None, embed_captions=True)
    (tmp_path / "ch1").mkdir()
    strategy.control_fifo_path(tmp_path, "ch1").touch()
    assert strategy.reload_content("ch1", tmp_path, _reload_request(tmp_path)) is True
    reload_graph = next((tmp_path / "ch1").glob("playout-graph.reload.*.json"))
    assert "cccombiner" in reload_graph.read_text(encoding="utf-8")


@_POSIX_FIFO_ONLY
def test_strategy_send_caption_cue_writes_base64_command(tmp_path) -> None:
    import base64

    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None)
    (tmp_path / "ch1").mkdir()
    fifo = strategy.control_fifo_path(tmp_path, "ch1")
    fifo.touch()
    sent = strategy.send_caption_cue(
        "ch1", tmp_path, text="HELLO CIVICCAST", pts_seconds=1.2, duration_seconds=0.8
    )
    assert sent is True
    verb, pts, dur, payload = fifo.read_text(encoding="utf-8").strip().split()
    assert verb == "caption"
    assert pts == "1200"
    assert dur == "800"
    # round-trips through base64 (so caption text with spaces survives the FIFO)
    assert base64.b64decode(payload).decode("utf-8") == "HELLO CIVICCAST"


def test_strategy_send_caption_cue_drops_when_worker_not_ready(tmp_path) -> None:
    strategy = GstPlayoutStrategy(worker_launcher=lambda *a: None)
    (tmp_path / "ch1").mkdir()
    assert (
        strategy.send_caption_cue("ch1", tmp_path, text="x", pts_seconds=0.0, duration_seconds=1.0)
        is False
    )


# --- S11 gap 9: secondary audio (SAP) wiring -----------------------------------


def test_strategy_audio_tracks_provider_adds_secondary_audio(tmp_path) -> None:
    from civiccast.egress.audio_tracks import AudioProgramTrack

    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    sap = AudioProgramTrack(
        track_id="t_sap",
        scope="channel",
        target_id="ch1",
        kind="sap",
        language="es",
        label="Spanish SAP",
        source_uri="file:///m/es.aac",
    )
    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        audio_tracks_provider=lambda channel_id: [sap] if channel_id == "ch1" else [],
        pipe_channel_factory=_fake_pipe_channel_factory,
    )
    result = strategy.start(_start_request(tmp_path))
    graph = graph_from_json(result.concat_plan_path.read_text(encoding="utf-8"))
    assert len(graph.secondary_audio) == 1
    assert graph.secondary_audio[0].language == "es"


def test_strategy_no_secondary_audio_by_default(tmp_path) -> None:
    def fake_launcher(argv, *a):
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)

    strategy = GstPlayoutStrategy(
        worker_launcher=fake_launcher,
        python_executable="python3",
        pipe_channel_factory=_fake_pipe_channel_factory,
    )
    result = strategy.start(_start_request(tmp_path))
    assert (
        graph_from_json(result.concat_plan_path.read_text(encoding="utf-8")).secondary_audio == ()
    )


# --- CC-WS5-006: reconnect + same-channel replacement through the strategy path ---
#
# These drive the REAL _WindowsPipeChannel (via a factory that injects a fake
# immediate-ack duplex server) through GstPlayoutStrategy's production Windows
# path. They are the os.name=='nt' counterpart of the FIFO-only tests above:
# start()'s pipe branch only runs on native Windows, so they are Windows-only and
# skip on the ubuntu FIFO CI lane (where the seam is covered by test_worker_pipe_seam).

_WINDOWS_PIPE_ONLY = pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "GstPlayoutStrategy.start()'s worker-pipe branch only runs on native Windows "
        "(os.name=='nt'); the platform-agnostic policy is covered by test_worker_pipe_seam."
    ),
)


class _ImmediateAckServer:
    """Fake WorkerPipeServer (immediate 'applied' ack) for driving a real
    _WindowsPipeChannel with no Win32 I/O."""

    def __init__(self) -> None:
        self._inbox: deque[str] = deque()
        self.written_cmds: list[str] = []
        self.written_ids: list[str] = []
        self.closed = False

    def create(self) -> None:
        pass

    def accept(self) -> None:
        pass

    def write_line(self, text: str) -> bool:
        obj = json.loads(text)
        self.written_cmds.append(str(obj["cmd"]))
        self.written_ids.append(str(obj["id"]))
        self._inbox.append(
            json.dumps({"v": 1, "id": str(obj["id"]), "result": "applied", "detail": None})
        )
        return True

    def read_line(self) -> str | None:
        if not self._inbox:
            return None
        return self._inbox.popleft()

    def close(self) -> None:
        self.closed = True


def _real_channel_factory(servers: list[_ImmediateAckServer]):
    from civiccast.egress.gst.strategy import _WindowsPipeChannel as _Chan

    def factory(channel_id: str) -> _WindowsPipeChannel:
        server = _ImmediateAckServer()
        servers.append(server)
        return _Chan(channel_id, server=cast("object", server), ack_timeout_s=2.0)  # type: ignore[arg-type]

    return factory


@_WINDOWS_PIPE_ONLY
def test_reconnect_channel_replays_desired_state_through_strategy(tmp_path) -> None:
    """CC-WS5-006 defect 3 wired end-to-end: after start()+send_command(reload/swap/
    caption) on the production strategy, reconnect_channel reissues ONLY reload/swap."""
    servers: list[_ImmediateAckServer] = []
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: SimpleNamespace(pid=1, poll=lambda: None),
        python_executable="python3",
        pipe_channel_factory=_real_channel_factory(servers),
    )
    strategy.start(_start_request(tmp_path))
    assert strategy.send_command(tmp_path, "ch1", "reload /w/g.json") is True
    assert strategy.send_command(tmp_path, "ch1", "swap 1") is True
    assert strategy.send_command(tmp_path, "ch1", "caption 0 500 aGk=") is True

    reissued = strategy.reconnect_channel("ch1")
    assert reissued == ["reissue-reload-ch1", "reissue-swap-ch1"]
    assert servers[0].written_cmds[-2:] == ["reload /w/g.json", "swap 1"]
    strategy.close_channel("ch1")


@_WINDOWS_PIPE_ONLY
def test_caption_delivery_id_reaches_the_worker_envelope(tmp_path) -> None:
    servers: list[_ImmediateAckServer] = []
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: SimpleNamespace(pid=1, poll=lambda: None),
        python_executable="python3",
        pipe_channel_factory=_real_channel_factory(servers),
    )
    strategy.start(_start_request(tmp_path))

    assert strategy.send_caption_cue(
        "ch1",
        tmp_path,
        text="Council meeting",
        pts_seconds=1.0,
        duration_seconds=2.0,
        delivery_id="caption-page-stable-id",
    )

    assert servers[0].written_ids[-1] == "caption-page-stable-id"
    strategy.close_channel("ch1")


@_WINDOWS_PIPE_ONLY
def test_reconnect_channel_is_noop_for_unknown_channel(tmp_path) -> None:
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: SimpleNamespace(pid=1, poll=lambda: None),
        pipe_channel_factory=_real_channel_factory([]),
    )
    assert strategy.reconnect_channel("never-started") == []


@_WINDOWS_PIPE_ONLY
def test_start_replacement_closes_old_pipe_server(tmp_path) -> None:
    """CC-WS5-006 defect 3 (leak): a second start() for the SAME channel must close
    the previous channel's pipe server rather than leaking it, and must carry the
    channel's desired state forward so a relaunch can replay it."""
    servers: list[_ImmediateAckServer] = []
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: SimpleNamespace(pid=1, poll=lambda: None),
        python_executable="python3",
        pipe_channel_factory=_real_channel_factory(servers),
    )
    strategy.start(_start_request(tmp_path))
    assert strategy.send_command(tmp_path, "ch1", "swap 1") is True  # desired state

    strategy.start(_start_request(tmp_path))  # replacement (e.g. crash-relaunch)
    assert servers[0].closed is True  # the OLD server was closed, not leaked
    assert servers[1].closed is False  # the new one is live

    # desired state carried across the replacement, so reconnect replays it.
    assert strategy.reconnect_channel("ch1") == ["reissue-swap-ch1"]
    assert servers[1].written_cmds[-1] == "swap 1"
    strategy.close_channel("ch1")


@_WINDOWS_PIPE_ONLY
def test_close_channel_closes_server_and_forgets_channel(tmp_path) -> None:
    servers: list[_ImmediateAckServer] = []
    strategy = GstPlayoutStrategy(
        worker_launcher=lambda *a: SimpleNamespace(pid=1, poll=lambda: None),
        pipe_channel_factory=_real_channel_factory(servers),
    )
    strategy.start(_start_request(tmp_path))
    strategy.close_channel("ch1")
    assert servers[0].closed is True
    # idempotent: closing an already-forgotten channel is a no-op.
    strategy.close_channel("ch1")


# --- Native-Windows encoder pre-flight (Story 4) -----------------------------------
# is_windows is injected so these prove the gate wiring on ANY platform (incl. ubuntu CI),
# not just a Windows runner. The pure decision matrix lives in test_encoder_decision.py.


def _preflight_launcher(argv, *a):
    return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda **k: 0)


def _hw_codec_request(tmp_path, *, codec: str, allow_software_fallback: bool):
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
        canonical_profile=CanonicalProfile(video_codec=codec),
        allow_software_fallback=allow_software_fallback,
    )
    plan = EgressSourcePlan(
        channel_id="ch1",
        segments=[EgressSourceSegment(label="c1", path="/m/c1.ts", duration_seconds=10)],
    )
    return EncoderStartRequest(channel_id="ch1", source_plan=plan, config=config, work_dir=tmp_path)


def _preflight_strategy(*, probe_result: bool):
    return GstPlayoutStrategy(
        worker_launcher=_preflight_launcher,
        python_executable="python3",
        pipe_channel_factory=_fake_pipe_channel_factory,
        encoder_probe=lambda name: probe_result,
        is_windows=True,
    )


def test_preflight_refuses_when_hardware_absent_no_fallback(tmp_path) -> None:
    strategy = _preflight_strategy(probe_result=False)
    with pytest.raises(EncoderUnavailableError):
        strategy.start(
            _hw_codec_request(tmp_path, codec="h264_vaapi", allow_software_fallback=False)
        )


def test_preflight_software_fallback_swaps_to_openh264(tmp_path) -> None:
    strategy = _preflight_strategy(probe_result=False)
    result = strategy.start(
        _hw_codec_request(tmp_path, codec="h264_vaapi", allow_software_fallback=True)
    )
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "openh264enc" in graph_text
    assert "mfh264enc" not in graph_text


def test_preflight_proceeds_with_hardware_encoder_when_present(tmp_path) -> None:
    strategy = _preflight_strategy(probe_result=True)
    result = strategy.start(
        _hw_codec_request(tmp_path, codec="h264_vaapi", allow_software_fallback=False)
    )
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "mfh264enc" in graph_text


def test_preflight_hevc_absent_refuses_even_with_fallback(tmp_path) -> None:
    strategy = _preflight_strategy(probe_result=False)
    with pytest.raises(EncoderUnavailableError):
        strategy.start(
            _hw_codec_request(tmp_path, codec="hevc_vaapi", allow_software_fallback=True)
        )


def test_preflight_hevc_present_uses_mf_h265_with_nv12(tmp_path) -> None:
    # HEVC now proceeds on native Windows when the hardware encoder is present; the built
    # graph must use mfh265enc with the NV12 input the MF HEVC encoder requires.
    strategy = _preflight_strategy(probe_result=True)
    result = strategy.start(
        _hw_codec_request(tmp_path, codec="hevc_vaapi", allow_software_fallback=False)
    )
    graph_text = result.concat_plan_path.read_text(encoding="utf-8")
    assert "mfh265enc" in graph_text
    assert "format=NV12" in graph_text


def test_preflight_hevc_with_captions_refused(tmp_path) -> None:
    # HEVC + embedded captions is unsupported (h264ccinserter is H.264-only): even with the
    # HEVC hardware encoder present, an embed-captions channel must be refused, not built.
    strategy = GstPlayoutStrategy(
        worker_launcher=_preflight_launcher,
        python_executable="python3",
        pipe_channel_factory=_fake_pipe_channel_factory,
        encoder_probe=lambda name: True,  # HEVC hardware present
        is_windows=True,
        embed_captions=True,  # captions ON -> incompatible with HEVC
    )
    with pytest.raises(EncoderUnavailableError) as exc:
        strategy.start(
            _hw_codec_request(tmp_path, codec="hevc_vaapi", allow_software_fallback=False)
        )
    assert "caption" in str(exc.value).lower()


def test_preflight_reload_content_preserves_software_fallback(tmp_path) -> None:
    # BLOCKER regression (adversarial review): a channel that fell back to software must
    # NOT rebuild its live pipeline on the absent hardware encoder during a content
    # reload -- reload_content must apply the same encoder decision as start().
    strategy = _preflight_strategy(probe_result=False)  # hardware absent
    request = _hw_codec_request(tmp_path, codec="h264_vaapi", allow_software_fallback=True)
    strategy.start(request)  # engages software fallback (openh264enc), creates the channel
    strategy.reload_content("ch1", tmp_path, request)
    reload_graph = next((tmp_path / "ch1").glob("playout-graph.reload.*.json"))
    text = reload_graph.read_text(encoding="utf-8")
    assert "openh264enc" in text
    assert "mfh264enc" not in text


def test_playout_worker_is_spawned_above_the_control_planes_priority() -> None:
    """Playout outranks the control plane on Windows.

    MEASURED field failure (tester DESKTOP-VBMA6O5, 1.0.0-beta.5 candidate
    kit, three channels ON_AIR): the control-plane python ran live-caption ASR
    at ~247% of a core at the SAME priority class as the playout workers,
    which sat at 26-64% each and repeatedly tripped their own
    ``CTRL stall: no output for 10s`` watchdog into a daemon restart. Captions
    are best effort; the air signal is not. Raising the worker one class is
    the cheap half of enforcing that (the caption ASR threads are lowered from
    the other side, in ``civiccast.captions.tap_worker``).

    The console-suppression flag (ENG-006) must survive the addition.
    """

    flags = strategy_module._worker_creationflags()

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    above_normal = getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)
    assert flags == no_window | above_normal
    if os.name == "nt":  # both constants only exist on Windows
        assert no_window and above_normal
        assert flags & no_window
        assert flags & above_normal
    else:
        # A no-op on the WSL/Linux line, where neither constant exists.
        assert flags == 0
