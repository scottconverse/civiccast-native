# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""F1 redesign (coordinator hostile-review follow-up, 2026-09-06, superseding
item 4's original "deferred ack" design): a ``reload`` command's pipe ack means
only "armed" now (the worker accepted the command and the new leg is building/
prerolling, or the build failed synchronously) -- written SYNCHRONOUSLY, same
as every other verb. Item 4's fix made the ack wait for the reload to fully
COMMIT or ABORT, which for a deferred/boundary-aligned switch (an
automation-driven ON_AIR extension) can take up to ``defer_switch_timeout_s``
(900s default) -- far longer than any pipe round-trip ack should ever block
for, and the strategy's bounded ack wait would time out on a correctly-armed
long-lead reload, causing the daemon to terminate a healthy worker (the F1
BLOCKER this redesign fixes).

The reload's EVENTUAL settle outcome (``"applied"``/``"aborted:<reason>"``) is
now reported OUT-OF-BAND via ``reload-status.json`` (``_write_reload_status``),
polled by ``EgressDaemon._poll_reload_settlement`` instead of riding the ack.

``worker.py`` is import-safe with only stdlib + the sibling gi-free ``control``/
``graph``/``reload_policy`` modules (its own module docstring), so
``_dispatch_control_with_ack`` is tested here directly against a FAKE
``engine_instance`` (a plain duck-typed double, not a real ``GstPlayoutEngine`` --
no ``gi``/GStreamer install needed) exactly like ``test_gst_worker_module_identity.
py`` imports ``worker.py`` by stubbing ``civiccast.egress.gst.engine`` in
``sys.modules`` under its package name."""

from __future__ import annotations

import importlib
import json
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
        self.reload_program_should_raise: Exception | None = None

    def reload_program(
        self, new_leg: Any, *, switch_at_end_of_current: bool, on_settled: Any
    ) -> None:
        if self.reload_program_should_raise is not None:
            raise self.reload_program_should_raise
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


# --- F1: the reload verb acks "armed" synchronously; settle is out-of-band --------


def _read_status(graph_path: Path) -> dict[str, Any]:
    status_path = graph_path.parent / "reload-status.json"
    return json.loads(status_path.read_text(encoding="utf-8"))


def test_reload_acks_armed_synchronously(worker_module, tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()

    result, detail = worker_module._dispatch_control_with_ack(
        engine, f"reload {graph_path}", command_id="cmd-1"
    )

    assert result == "armed"
    assert detail is None
    assert len(engine.reload_calls) == 1
    assert not graph_path.exists()  # one-shot graph file consumed after read
    # Not settled yet -- no status file until on_settled fires.
    assert not (graph_path.parent / "reload-status.json").exists()


def test_reload_settle_applied_is_written_out_of_band(worker_module, tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()

    worker_module._dispatch_control_with_ack(engine, f"reload {graph_path}", command_id="cmd-2")
    # Simulate the engine's own later main-loop commit (``_commit_reload``'s
    # ``on_settled(True, None)`` call) -- this does NOT touch the pipe ack at
    # all; it writes the status file instead.
    engine.reload_calls[0]["on_settled"](True, None)

    status = _read_status(graph_path)
    assert status["id"] == "cmd-2"
    assert status["result"] == "applied"


def test_reload_settle_aborted_carries_the_reason(worker_module, tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()

    worker_module._dispatch_control_with_ack(engine, f"reload {graph_path}", command_id="cmd-3")
    # Simulate the engine's own later main-loop abort (e.g. the H1 fix's
    # ``_make``-raises-on-refused-add path, or the reload_timeout_s watchdog) --
    # arriving long after any pipe ack bound would have expired is exactly the
    # point: this path no longer rides the ack at all.
    engine.reload_calls[0]["on_settled"](False, "timeout")

    status = _read_status(graph_path)
    assert status["id"] == "cmd-3"
    assert status["result"] == "aborted:timeout"


def test_reload_settle_without_a_command_id_falls_back_to_a_generated_one(
    worker_module, tmp_path: Path
) -> None:
    """A caller that doesn't supply ``command_id`` (the default) still gets a
    real, generated reload id in the status file -- never a crash, never a
    silently-dropped settlement."""
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()

    worker_module._dispatch_control_with_ack(engine, f"reload {graph_path}")
    engine.reload_calls[0]["on_settled"](True, None)

    status = _read_status(graph_path)
    assert status["id"]  # some non-empty generated id
    assert status["result"] == "applied"


def test_a_synchronous_build_failure_acks_error_and_settles_nothing(
    worker_module, tmp_path: Path
) -> None:
    """F2: if ``reload_program`` itself raises (nothing was armed), the ack is
    "error" immediately -- there is no pending settlement to report later, so
    no status file is written at all."""
    graph_path = _write_graph(tmp_path)
    engine = _FakeEngine()
    engine.reload_program_should_raise = RuntimeError("simulated fail-loud pipeline.add refusal")

    result, detail = worker_module._dispatch_control_with_ack(
        engine, f"reload {graph_path}", command_id="cmd-4"
    )

    assert result == "error"
    assert "simulated fail-loud pipeline.add refusal" in (detail or "")
    assert not (graph_path.parent / "reload-status.json").exists()


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

    result, _detail = worker_module._dispatch_control_with_ack(
        engine, f"reload {graph_path}", command_id="cmd-5"
    )

    assert result == "armed"  # program reload still armed fine
    assert len(engine.reload_calls) == 1
    assert "graphics-overlay re-apply failed" in capsys.readouterr().out

    engine.reload_calls[0]["on_settled"](True, None)
    status = _read_status(graph_path)
    assert status["result"] == "applied"  # program reload's own outcome, unaffected


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
