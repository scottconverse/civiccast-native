# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 4 (honest ack): ``worker.py``'s D2 windows-pipe dispatch must not ack a
``reload`` command "applied" before the engine's reload actually COMMITS -- and
must ack "aborted:<reason>" if it doesn't. Measured on real hardware (2026-09-06):
the pre-fix code acked "applied" the instant ``engine.reload_program(...)``
RETURNED, which only means the reload was ARMED (built + prerolled), not that it
had committed; combined with the H1 concat-naming collision (engine.py), the daemon
believed every rollover had landed while it silently timed out and was retried
forever.

``worker.py`` is import-safe with only stdlib + the sibling gi-free ``control``/
``graph``/``reload_policy`` modules (its own module docstring), so
``_dispatch_control_with_ack`` is tested here directly against a FAKE
``engine_instance`` (a plain duck-typed double, not a real ``GstPlayoutEngine`` --
no ``gi``/GStreamer install needed) exactly like ``test_gst_worker_module_identity.
py`` imports ``worker.py`` by stubbing ``civiccast.egress.gst.engine`` in
``sys.modules`` under its package name."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from civiccast.egress.gst.graph import demo_test_graph, graph_to_json

_WORKER = "civiccast.egress.gst.worker"
_ALIASES = tuple(f"civiccast.egress.gst.{name}" for name in ("control", "audio_tap", "engine"))


@pytest.fixture
def worker_module() -> Iterator[types.ModuleType]:
    """Import ``worker.py`` with ``civiccast.egress.gst.engine`` stubbed (it needs
    real ``gi``, which this test environment does not have) -- mirrors
    ``test_gst_worker_module_identity.py``'s ``imported_worker`` fixture exactly."""
    engine_stub = types.ModuleType("civiccast.egress.gst.engine")
    engine_stub.GstPlayoutEngine = object  # type: ignore[attr-defined]
    saved_engine = sys.modules.get("civiccast.egress.gst.engine")
    sys.modules["civiccast.egress.gst.engine"] = engine_stub
    for cached in (_WORKER, "graph", "engine", "control", "audio_tap", "reload_policy"):
        sys.modules.pop(cached, None)
    already_aliased = {name: sys.modules.get(name) for name in _ALIASES}
    module = importlib.import_module(_WORKER)
    try:
        yield module
    finally:
        sys.modules.pop(_WORKER, None)
        for name, previous in already_aliased.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if saved_engine is None:
            sys.modules.pop("civiccast.egress.gst.engine", None)
        else:
            sys.modules["civiccast.egress.gst.engine"] = saved_engine


class _FakeSwap:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def swap_to(self, index: int) -> None:
        self.calls.append(index)


class _FakeEngine:
    """Duck-typed stand-in for ``GstPlayoutEngine`` -- only the surface
    ``_dispatch_control_with_ack`` actually touches. ``reload_program`` records its
    ``on_settled`` callback instead of ever calling it (the test drives settlement
    explicitly, simulating the engine's own later main-loop commit/abort)."""

    def __init__(self) -> None:
        self.swap = _FakeSwap()
        self._loop = types.SimpleNamespace(quit=lambda: setattr(self, "quit_called", True))
        self.quit_called = False
        self.reload_calls: list[dict[str, Any]] = []
        self.graphics_overlay_calls: list[Any] = []
        self.graphics_overlay_should_raise = False
        self.caption_pushed: list[dict[str, Any]] = []
        self.push_caption_return = True

    def reload_program(
        self, new_leg: Any, *, switch_at_end_of_current: bool, on_settled: Any
    ) -> None:
        self.reload_calls.append(
            {
                "new_leg": new_leg,
                "switch_at_end_of_current": switch_at_end_of_current,
                "on_settled": on_settled,
            }
        )

    def reload_graphics_overlay(self, graphics_overlay: Any) -> None:
        self.graphics_overlay_calls.append(graphics_overlay)
        if self.graphics_overlay_should_raise:
            raise RuntimeError("simulated graphics-overlay re-apply failure")

    def push_caption_cue(self, *, text: str, pts_seconds: float, duration_seconds: float) -> bool:
        self.caption_pushed.append(
            {"text": text, "pts_seconds": pts_seconds, "duration_seconds": duration_seconds}
        )
        return self.push_caption_return


def _write_graph(tmp_path: Path) -> Path:
    path = tmp_path / "playout-graph.reload.json"
    path.write_text(graph_to_json(demo_test_graph()), encoding="utf-8")
    return path


# --- the reload verb defers its ack (item 4) --------------------------------------


def test_reload_returns_deferred_and_does_not_ack_immediately(
    worker_module, tmp_path: Path
) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()
    settled: list[tuple[str, str | None]] = []

    result, detail = worker_module._dispatch_control_with_ack(
        engine,
        f"reload {graph_path}",
        on_reload_settled=lambda result, detail: settled.append((result, detail)),
    )

    assert result == worker_module._DEFERRED_RESULT
    assert detail is None
    assert settled == []  # not acked yet -- the engine hasn't settled
    assert len(engine.reload_calls) == 1
    assert not graph_path.exists()  # one-shot graph file consumed after read


def test_reload_acks_applied_only_once_the_engine_commits(worker_module, tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()
    settled: list[tuple[str, str | None]] = []

    result, _detail = worker_module._dispatch_control_with_ack(
        engine,
        f"reload {graph_path}",
        on_reload_settled=lambda result, detail: settled.append((result, detail)),
    )
    assert result == worker_module._DEFERRED_RESULT
    assert settled == []

    # Simulate the engine's own later main-loop commit (``_commit_reload``'s
    # ``on_settled(True, None)`` call).
    engine.reload_calls[0]["on_settled"](True, None)

    assert settled == [("applied", None)]


def test_reload_acks_aborted_with_reason_when_the_engine_aborts(
    worker_module, tmp_path: Path
) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()
    settled: list[tuple[str, str | None]] = []

    worker_module._dispatch_control_with_ack(
        engine,
        f"reload {graph_path}",
        on_reload_settled=lambda result, detail: settled.append((result, detail)),
    )
    # Simulate the engine's own later main-loop abort (e.g. the H1 fix's
    # ``_make``-raises-on-refused-add path, or the reload_timeout_s watchdog).
    engine.reload_calls[0]["on_settled"](False, "timeout")

    assert settled == [("aborted:timeout", None)]


def test_reload_with_no_on_reload_settled_callback_is_still_deferred(
    worker_module, tmp_path: Path
) -> None:
    """A caller that does not ask for a deferred ack (``on_reload_settled=None``,
    the parameter's default) still gets the honest "deferred" result -- it simply
    has no way to observe the eventual settlement. This proves the fix does not
    silently fall back to the old "applied instantly" behavior for any caller."""
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()

    result, detail = worker_module._dispatch_control_with_ack(engine, f"reload {graph_path}")

    assert result == worker_module._DEFERRED_RESULT
    assert detail is None


def test_a_graphics_overlay_reapply_failure_does_not_affect_the_program_reload_ack(
    worker_module, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The program reload and the graphics-overlay re-apply are independent --
    engine.reload_graphics_overlay's own docstring says a build/preroll failure
    there must never disturb the already-on-air overlay, and it must equally never
    be conflated with the program reload's own commit/abort outcome."""
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()
    engine.graphics_overlay_should_raise = True
    settled: list[tuple[str, str | None]] = []

    result, _detail = worker_module._dispatch_control_with_ack(
        engine,
        f"reload {graph_path}",
        on_reload_settled=lambda result, detail: settled.append((result, detail)),
    )

    assert result == worker_module._DEFERRED_RESULT  # program reload still armed fine
    assert len(engine.reload_calls) == 1
    assert "graphics-overlay re-apply failed" in capsys.readouterr().out

    engine.reload_calls[0]["on_settled"](True, None)
    assert settled == [("applied", None)]  # program reload's own outcome, unaffected


# --- every other verb is unchanged: synchronous dispatch + immediate ack ----------


def test_swap_acks_applied_immediately(worker_module) -> None:
    engine = _FakeEngine()
    result, detail = worker_module._dispatch_control_with_ack(engine, "swap 1")
    assert (result, detail) == ("applied", None)
    assert engine.swap.calls == [1]


def test_caption_acks_applied_immediately(worker_module) -> None:
    engine = _FakeEngine()
    result, detail = worker_module._dispatch_control_with_ack(engine, "caption 1000 2000 aGVsbG8=")
    assert (result, detail) == ("applied", None)
    assert engine.caption_pushed == [{"text": "hello", "pts_seconds": 1.0, "duration_seconds": 2.0}]


def test_caption_acks_error_when_no_live_caption_source(worker_module) -> None:
    engine = _FakeEngine()
    engine.push_caption_return = False
    result, detail = worker_module._dispatch_control_with_ack(engine, "caption 1000 2000 aGVsbG8=")
    assert result == "error"
    assert detail == "no live caption source"


def test_stop_acks_applied_immediately(worker_module) -> None:
    engine = _FakeEngine()
    result, detail = worker_module._dispatch_control_with_ack(engine, "stop")
    assert (result, detail) == ("applied", None)
    assert engine.quit_called is True


def test_unparseable_line_acks_error(worker_module) -> None:
    engine = _FakeEngine()
    result, detail = worker_module._dispatch_control_with_ack(engine, "not-a-verb")
    assert result == "error"
    assert "unparseable" in (detail or "")
    assert engine.reload_calls == []
