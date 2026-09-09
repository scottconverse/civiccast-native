# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 84 (measured in sandbox run 15, soak-fcfcb81-20260906-183448Z, and in
three seamless-OFF runs): every fresh worker printed
``CTRL preroll: reached PLAYING after 0.3s`` (a real, fast PLAYING transition)
immediately followed by ``CTRL stall: no output for 10s - quitting for daemon
restart`` -- ``GstPlayoutEngine._await_playing`` accepts NO_PREROLL as
success, so PLAYING is not evidence a single buffer crossed the mux, and
``_arm_stall_watchdog`` armed the 10s post-first-buffer stall bound
(``stall_timeout_s``) the instant PLAYING was reached. Under start-up load (a
concurrent ffmpeg conform, a ~10s synchronous content-reload source
preparation on the automation thread, live caption-tap overload) the first
output buffer can legitimately take longer than 10s, killing a perfectly
healthy worker.

This file covers the engine-side fix: ``_check_stall`` now measures two
DISTINCT budgets -- ``first_output_timeout_s`` (45s default) while no output
has been observed yet, and the original ``stall_timeout_s`` (10s default,
unchanged behavior) once the first buffer IS observed -- plus
``_resolve_first_output_timeout_s``'s default/env/clamp/NaN-guard resolution,
mirroring ``tests/egress/test_gst_engine_preroll_timeout.py`` exactly (same
fake-``gi``/``Gst`` fixture, no real GStreamer install needed).
"""

from __future__ import annotations

import importlib
import math
import sys
import types
from typing import Any

import pytest

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"


@pytest.fixture
def engine_module():
    """Load ``civiccast.egress.gst.engine`` fresh against a fake ``gi``/``Gst``
    that needs no real GStreamer install -- mirrors the fixture in
    ``test_gst_engine_preroll_timeout.py`` and
    ``test_gst_engine_reload_concat_naming.py``."""
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_repository = types.ModuleType("gi.repository")
    fake_glib = types.ModuleType("gi.repository.GLib")
    fake_glib.timeout_add_seconds = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_repository.GLib = fake_glib  # type: ignore[attr-defined]
    fake_repository.Gst = fake_gst  # type: ignore[attr-defined]
    fake_gi.repository = fake_repository  # type: ignore[attr-defined]

    patched_names = ("gi", "gi.repository", "gi.repository.GLib", "gi.repository.Gst")
    saved = {name: sys.modules.get(name) for name in (*patched_names, _ENGINE_MODULE_NAME)}
    for name in patched_names:
        sys.modules[name] = {
            "gi": fake_gi,
            "gi.repository": fake_repository,
            "gi.repository.GLib": fake_glib,
            "gi.repository.Gst": fake_gst,
        }[name]
    sys.modules.pop(_ENGINE_MODULE_NAME, None)
    try:
        module = importlib.import_module(_ENGINE_MODULE_NAME)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _bare_engine(
    module: types.ModuleType,
    *,
    first_output_timeout_s: float,
    stall_timeout_s: float,
) -> Any:
    """A ``GstPlayoutEngine`` with none of ``__init__``'s heavy pipeline-building
    run -- just the attributes ``_check_stall`` actually touches."""
    engine = object.__new__(module.GstPlayoutEngine)
    engine.first_output_timeout_s = first_output_timeout_s
    engine.stall_timeout_s = stall_timeout_s
    engine._first_output_seen = False
    engine._output_buffers = 0
    engine._stall_last_count = 0
    engine._stall_last_advance_t = 0.0
    engine._error = None
    engine._loop = None
    # Item 84 Round-2 review BLOCKER additions -- ``_check_stall`` /
    # ``_arm_stall_watchdog`` now also touch these.
    engine._playing_reached_at = None
    engine._first_output_marker_printed = False
    # Item 84c additions -- the arm-time snapshot the "real first output"
    # check is measured against, and the progress-line throttle state.
    engine._output_buffers_at_arm = 0
    engine._last_output_progress_print_t = 0.0
    return engine


class _FakeLoop:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


# --- _check_stall: the two-budget split ---------------------------------------------


def test_check_stall_never_trips_while_output_is_advancing(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()

    for i in range(1, 6):
        engine._output_buffers = i
        clock["t"] += 1.0
        assert engine._check_stall() is True
    assert engine._error is None
    assert engine._loop.quit_calls == 0
    assert engine._first_output_seen is True


def test_check_stall_fires_the_first_output_timeout_before_any_buffer_is_seen(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The item 84 fix's own core case: PLAYING was reached (armed at t=0) but
    NO buffer has ever crossed the mux -- once ``first_output_timeout_s``
    elapses, the engine quits with the distinct ``first-output-timeout``
    reason, never the ordinary ``stall_timeout_s`` (10s) bound, which would
    have tripped this scenario immediately under the OLD code."""
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()

    # Ticks well past the OLD 10s stall bound, but still under the NEW 45s
    # first-output bound -- must NOT trip yet (the exact scenario the old
    # code got wrong).
    for _ in range(20):
        clock["t"] += 1.0
        assert engine._check_stall() is True
    assert engine._error is None

    # Past the 45s first-output bound: now it trips.
    clock["t"] = 46.0
    result = engine._check_stall()

    assert result is False
    assert engine._error == ("first-output-timeout", "no output buffers observed within bound")
    assert engine._loop.quit_calls == 1
    err = capsys.readouterr().err
    assert "CTRL first-output: no output within 45s of PLAYING" in err


def test_check_stall_still_applies_the_ordinary_stall_bound_after_first_output(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Once the first buffer IS observed, the original S9-5 behavior applies
    completely unchanged: a 10s gap with no further advance trips the
    ordinary ``("stall", ...)`` reason, never the first-output-TIMEOUT one.
    The positive-evidence ``CTRL first-output: first buffer after ...``
    marker (item 84 Round-2) DOES print once, at the moment the first
    buffer is observed -- that is expected and desired (it is the daemon's
    on-air evidence for this exact scenario), distinct from the
    first-output-timeout FAILURE line this test proves never fires here."""
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()

    # Item 84c: real first output requires the count to exceed the arm-time
    # snapshot (0 here) by at least ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM``
    # (2) -- one buffer alone could still be a table-refresh coincidence.
    engine._output_buffers = 2  # two real buffers observed post-arm at t=0
    assert engine._check_stall() is True
    assert engine._first_output_seen is True

    clock["t"] += 9.0
    assert engine._check_stall() is True  # still inside the 10s stall bound
    assert engine._error is None

    clock["t"] += 2.0  # 11s since the last advance
    result = engine._check_stall()

    assert result is False
    assert engine._error == ("stall", "output stalled")
    assert engine._loop.quit_calls == 1
    err = capsys.readouterr().err
    assert "CTRL stall: no output for 10s" in err
    assert "CTRL first-output: no output within" not in err  # the TIMEOUT line, never printed
    assert "CTRL first-output: first buffer after" in err  # the SUCCESS marker, printed once


def test_check_stall_ordinary_stall_disabled_at_zero_after_first_output(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The post-first-buffer stall check keeps its pre-item-84 opt-out
    semantics (``stall_timeout_s <= 0`` disables just that check) even though
    ``_arm_stall_watchdog`` now arms unconditionally whenever EITHER budget is
    active."""
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=0.0)
    engine._loop = _FakeLoop()

    # Item 84c: two buffers past the arm-time snapshot (0), not one -- see
    # ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM``.
    engine._output_buffers = 2
    assert engine._check_stall() is True
    assert engine._first_output_seen is True

    clock["t"] = 10_000.0
    assert engine._check_stall() is True
    assert engine._error is None
    assert engine._loop.quit_calls == 0


# --- _maybe_print_first_output_marker: the positive on-air evidence marker ----------
#
# Item 84 Round-2 review BLOCKER: ``EgressDaemon._observed_on_air_evidence``
# crediting the ``CTRL preroll: reached PLAYING`` marker alone as GStreamer
# on-air evidence let a worker that reaches PLAYING on every relaunch, but
# never actually produces output, get its crash-loop streak reset every
# alive-poll cycle -- measured: streak pinned at 1, never escalating to
# fallback slate, at EVERY tested ``first_output_timeout_s`` from 65s through
# the 120s clamp ceiling. The fix is this NEW, separate, positive-evidence
# marker, printed exactly once the moment a real buffer crosses the mux --
# these tests prove the marker itself (the daemon-side escalation tests in
# ``test_daemon_first_output_timeout_relaunch.py`` prove the consuming half).


def test_first_output_marker_prints_once_when_output_first_advances(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = {"t": 5.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.os, "getpid", lambda: 4242)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()
    engine._playing_reached_at = 5.0  # PLAYING was reached at this same instant

    # Item 84c: two buffers past the arm-time snapshot (0, from _bare_engine)
    # -- one alone would not yet count as real first output.
    engine._output_buffers = 2
    clock["t"] = 8.5
    assert engine._check_stall() is True

    err = capsys.readouterr().err
    assert "CTRL first-output: first buffer after 3.5s pid=4242" in err
    assert engine._first_output_marker_printed is True


def test_first_output_marker_never_prints_twice(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()
    engine._playing_reached_at = 0.0

    for i in range(1, 4):
        engine._output_buffers = i
        clock["t"] += 1.0
        assert engine._check_stall() is True

    err = capsys.readouterr().err
    assert err.count("CTRL first-output: first buffer after") == 1


def test_arm_stall_watchdog_snapshots_preroll_buffers_instead_of_crediting_them(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 84c (sandbox run 17, soak-a6d7871-20260906-213332Z): the OLD
    round-2 behavior this test used to cover -- ``_output_buffers > 0`` at
    arm time alone counting as first-output evidence -- was a TAUTOLOGY. The
    persistent output half's async sink chain means the pipeline cannot even
    reach PLAYING before at least one buffer (PAT/PMT/SDT tables + preroll)
    has already crossed the mux, so that check was true for essentially
    every worker on every arm, real media flow or not. Arming must snapshot
    the count instead of crediting it: ``_first_output_seen`` stays False and
    no marker prints at arm time, even though buffers were already flowing
    before arm."""
    clock = {"t": 10.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    monkeypatch.setattr(engine_module.os, "getpid", lambda: 777)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._playing_reached_at = 7.0  # PLAYING reached 3s before this arm call
    engine._output_buffers = 5  # preroll already produced buffers before arm

    engine._arm_stall_watchdog()

    assert engine._first_output_seen is False  # item 84c's own fix
    assert engine._output_buffers_at_arm == 5  # snapshot, not credited as evidence
    err = capsys.readouterr().err
    assert "CTRL first-output: first buffer after" not in err  # no marker at arm time


def test_first_output_marker_prints_once_real_post_arm_output_is_observed(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Continuing the arm-time snapshot scenario above: once
    ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM`` (2) further buffers arrive AFTER
    arming, that IS real first-output evidence, and the marker prints
    measuring elapsed from PLAYING as before."""
    clock = {"t": 10.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    monkeypatch.setattr(engine_module.os, "getpid", lambda: 777)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._playing_reached_at = 7.0
    engine._output_buffers = 5
    engine._arm_stall_watchdog()  # snapshot at 5, no evidence yet
    engine._loop = _FakeLoop()

    clock["t"] = 13.0  # 3s after arm
    engine._output_buffers = 7  # +2 past the snapshot -- real output

    assert engine._check_stall() is True

    assert engine._first_output_seen is True
    err = capsys.readouterr().err
    assert "CTRL first-output: first buffer after 6.0s pid=777" in err


def test_first_output_marker_falls_back_to_zero_elapsed_when_playing_never_recorded(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defensive fallback: ``_playing_reached_at`` stays ``None`` if
    ``_maybe_print_first_output_marker`` is ever reached without
    ``_await_playing`` having run (should not happen in production, but must
    never raise) -- the elapsed text degrades to 0.0s rather than crashing."""
    clock = {"t": 42.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._loop = _FakeLoop()
    assert engine._playing_reached_at is None

    # Item 84c: two buffers past the arm-time snapshot (0, from _bare_engine).
    engine._output_buffers = 2
    engine._check_stall()

    err = capsys.readouterr().err
    assert "CTRL first-output: first buffer after 0.0s" in err


# --- _arm_stall_watchdog: arms unless BOTH budgets are disabled ----------------------
#
# Coordinator review round 2: ``first_output_timeout_s=0.0`` is an UNREACHABLE
# configuration through the real constructor -- ``_resolve_first_output_
# timeout_s`` always clamps to ``[10, 120]``, so no real ``GstPlayoutEngine``
# can ever have this attribute at 0. Two tests here used to construct a bare
# engine and set that attribute directly (bypassing the resolver entirely) to
# exercise the ``_arm_stall_watchdog``/``_check_stall`` "both budgets
# disabled" branch -- removed rather than kept, since a passing test against
# a state the product can never reach is misleading, not coverage.
# ``test_arm_stall_watchdog_still_arms_when_only_stall_timeout_is_disabled``
# below already covers the one REACHABLE disabled-budget state
# (``stall_timeout_s <= 0`` alone, which IS a real, unclamped, operator-
# settable value via ``CIVICCAST_STALL_TIMEOUT_S``).


def test_arm_stall_watchdog_still_arms_when_only_stall_timeout_is_disabled(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before item 84, ``stall_timeout_s <= 0`` disabled the watchdog
    entirely -- that silently also disabled the (independently useful)
    first-output check. Now it must still arm as long as the first-output
    budget is active."""
    calls: list[Any] = []
    monkeypatch.setattr(
        engine_module.GLib, "timeout_add_seconds", lambda *a, **k: calls.append((a, k))
    )
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=0.0)

    engine._arm_stall_watchdog()

    assert len(calls) == 1


def test_arm_stall_watchdog_resets_first_output_seen(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._first_output_seen = True

    engine._arm_stall_watchdog()

    assert engine._first_output_seen is False


# --- _resolve_first_output_timeout_s: default / env / clamp / NaN guard -------------


def test_resolve_first_output_timeout_defaults_to_45s(engine_module) -> None:
    assert engine_module._resolve_first_output_timeout_s(None) == 45.0


def test_resolve_first_output_timeout_reads_the_env_override(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "60")
    assert engine_module._resolve_first_output_timeout_s(None) == 60.0


def test_resolve_first_output_timeout_clamps_the_env_override_to_10s_minimum(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "1")
    assert engine_module._resolve_first_output_timeout_s(None) == 10.0


def test_resolve_first_output_timeout_clamps_the_env_override_to_120s_maximum(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "999")
    assert engine_module._resolve_first_output_timeout_s(None) == 120.0


def test_resolve_first_output_timeout_ignores_a_malformed_env_value(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "not-a-number")
    assert engine_module._resolve_first_output_timeout_s(None) == 45.0


def test_resolve_first_output_timeout_explicit_value_wins_over_env(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "60")
    assert engine_module._resolve_first_output_timeout_s(30.0) == 30.0


def test_resolve_first_output_timeout_clamps_an_explicit_value_too(engine_module) -> None:
    assert engine_module._resolve_first_output_timeout_s(1.0) == 10.0
    assert engine_module._resolve_first_output_timeout_s(999.0) == 120.0


def test_resolve_first_output_timeout_env_nan_falls_back_to_default(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors the preroll bound's own NaN-clamp-escape fix: Python's
    ``min``/``max`` do not clamp NaN (every comparison with NaN is False), so
    an unguarded NaN would reach the watchdog's elapsed-time comparisons and
    never trip either budget at all."""
    monkeypatch.setenv("CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S", "nan")
    resolved = engine_module._resolve_first_output_timeout_s(None)
    assert resolved == 45.0
    assert math.isfinite(resolved)


def test_resolve_first_output_timeout_explicit_nan_falls_back_to_default(
    engine_module,
) -> None:
    resolved = engine_module._resolve_first_output_timeout_s(float("nan"))
    assert resolved == 45.0
    assert math.isfinite(resolved)


def test_resolve_first_output_timeout_explicit_infinity_falls_back_to_default(
    engine_module,
) -> None:
    resolved = engine_module._resolve_first_output_timeout_s(float("inf"))
    assert resolved == 45.0
    assert math.isfinite(resolved)


def test_resolve_first_output_timeout_120s_is_still_the_allowed_maximum(
    engine_module,
) -> None:
    assert engine_module._resolve_first_output_timeout_s(120.0) == 120.0


def test_resolve_first_output_timeout_10s_is_still_the_allowed_minimum(
    engine_module,
) -> None:
    assert engine_module._resolve_first_output_timeout_s(10.0) == 10.0


# --- _maybe_print_output_progress: item 84c addendum, bounded 5s breadcrumb --------
#
# Sandbox run 17 (soak-a6d7871-20260906-213332Z) had no signal at all between
# "output was flowing" and the eventual watchdog kill -- the only evidence of
# the item 88 stall was TSDuck's after-the-fact silence. This line gives the
# NEXT soak exactly that signal, bounded to at most one line per 5s so it
# cannot become its own source of log spam under sustained healthy output.


def test_output_progress_line_prints_at_most_once_per_five_seconds(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._output_buffers = 100
    engine._arm_stall_watchdog()  # snapshots at 100, starts the progress clock
    engine._loop = _FakeLoop()

    for i in range(1, 5):  # t=1,2,3,4 -- under the 5s interval, must not print
        clock["t"] = float(i)
        engine._output_buffers = 100 + i
        assert engine._check_stall() is True
    assert "CTRL output:" not in capsys.readouterr().err

    clock["t"] = 5.0  # exactly at the interval -- prints now
    engine._output_buffers = 106
    assert engine._check_stall() is True
    err = capsys.readouterr().err
    assert "CTRL output: 106 buffers (+6) since PLAYING" in err


def test_output_progress_line_prints_even_while_stalled(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The breadcrumb is not gated on output advancing -- it must also print
    while the count is flat, so a soak shows the count stopped changing
    (rather than going silent) in the run-up to the eventual stall kill."""
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._output_buffers = 50
    engine._arm_stall_watchdog()
    engine._loop = _FakeLoop()

    clock["t"] = 5.0  # no advance at all since arm -- still due a progress line
    assert engine._check_stall() is True
    err = capsys.readouterr().err
    assert "CTRL output: 50 buffers (+0) since PLAYING" in err


def test_output_progress_line_delta_is_relative_to_the_arm_time_snapshot(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine_module.GLib, "timeout_add_seconds", lambda *a, **k: None)
    engine = _bare_engine(engine_module, first_output_timeout_s=45.0, stall_timeout_s=10.0)
    engine._output_buffers = 1_000  # a lot of preroll/table churn already counted
    engine._arm_stall_watchdog()
    engine._loop = _FakeLoop()

    clock["t"] = 5.0
    engine._output_buffers = 1_003
    assert engine._check_stall() is True
    err = capsys.readouterr().err
    assert "CTRL output: 1003 buffers (+3) since PLAYING" in err
