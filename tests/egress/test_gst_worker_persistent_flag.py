# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U41 work item 1: which worker runs are PERSISTENT live channels, and which are
finite runs that end when their plan ends.

The U41 plan-EOS slate hold (``GstPlayoutEngine._on_program_pad_plan_eos``) is
correct for a live channel -- the 2026-09-25 education incident's worker exited 0
at 23:54:41 with the channel's own state row still ON_AIR and stayed dark for
~2m43s -- and WRONG for a finite run, whose only termination mechanism is the plan
ending: ``tests/egress/test_gst_engine_caption_flow_native.py`` (the beta.5
baseline pin) launches three workers that are expected to exit at plan EOS.

The worker cannot see that difference for itself (preparation runs in the daemon;
the control vocabulary is a closed ``swap``/``reload``/``caption``/``stop``), so
the daemon has to STATE it. It does: ``strategy._default_worker_launcher`` -- the
one place the worker's environment is built (``GstPlayoutStrategy.start()`` ->
``self._launch``), i.e. the ACTIVE-channel launch path -- sets
``reload_policy.WORKER_PERSISTENT_ENV`` to ``"1"``. ``worker.main()`` reads it and
arms the hold only for ``"1"``; anything that spawns ``worker.py`` without it
keeps exit-at-plan-EOS, which is what the pin and every unit harness rely on.

``worker.py`` is import-safe with only stdlib + the sibling gi-free modules, so
these drive ``main()`` (and the Windows-pipe entry point) against a FAKE
``civiccast.egress.gst.engine`` stubbed into ``sys.modules`` -- mirrors
``tests/egress/test_gst_worker_preroll_timeout_exit.py``'s ``worker_module``
fixture exactly, no real ``gi``/GStreamer install needed.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from civiccast.egress.gst import reload_policy as reload_policy_module
from civiccast.egress.gst.graph import demo_test_graph, graph_to_json

_WORKER = "civiccast.egress.gst.worker"
_ALIASES = tuple(
    f"civiccast.egress.gst.{name}"
    for name in ("control", "audio_tap", "engine", "decode_policy", "reload_policy", "exit_codes")
)

# The worker-persistent flag name, read from the product where the product defines it.
# The fallback literal covers only the pre-change (RED) run -- the constant lands with
# the behaviour. It cannot mask a name mismatch: once ``reload_policy`` defines it the
# module attribute wins, so this file (the reader's test) and the strategy test (the
# setter's test) are both held to the product's one name.
_FLAG_NAME = getattr(reload_policy_module, "WORKER_PERSISTENT_ENV", "CIVICAST_WORKER_PERSISTENT")

_WINDOWS_PIPE_ONLY = pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "main()'s worker-pipe branch only runs on native Windows (os.name=='nt'); the "
        "flag threading itself is platform-agnostic and covered by the plain-branch tests."
    ),
)


@pytest.fixture
def worker_module() -> Iterator[types.ModuleType]:
    """Import ``worker.py`` fresh with ``civiccast.egress.gst.engine`` stubbed (it
    needs real ``gi``, which this test environment does not have) -- mirrors
    ``test_gst_worker_preroll_timeout_exit.py``'s ``worker_module`` fixture."""
    engine_stub = types.ModuleType("civiccast.egress.gst.engine")
    engine_stub.GstPlayoutEngine = object  # type: ignore[attr-defined]
    saved_engine = sys.modules.get("civiccast.egress.gst.engine")
    sys.modules["civiccast.egress.gst.engine"] = engine_stub
    for cached in (
        _WORKER,
        "graph",
        "engine",
        "control",
        "audio_tap",
        "decode_policy",
        "reload_policy",
        "exit_codes",
    ):
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


class _FakeRecordingEngine:
    """Duck-typed ``GstPlayoutEngine`` stand-in whose ``run_forever`` records how
    ``main()`` called it and returns a clean result immediately (so ``main()``
    reaches ``return 0`` without a pipeline). ``run_forever``'s keywords carry
    defaults on purpose: a caller that does NOT pass the hold flag must land here
    as the finite default, not as a ``TypeError``."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *_a: object, **_kw: object) -> None:
        pass

    def run_forever(
        self, *, control_fifo: str | None = None, hold_slate_at_plan_eos: bool = False
    ) -> dict[str, Any]:
        type(self).calls.append(
            {"control_fifo": control_fifo, "hold_slate_at_plan_eos": hold_slate_at_plan_eos}
        )
        return {"error": None, "teardown_clean": True}


@pytest.fixture(autouse=True)
def _reset_fake_engine_state() -> Iterator[None]:
    """``main()`` constructs the engine itself, so the recording is class-level;
    reset around every test so nothing leaks between them."""
    _FakeRecordingEngine.calls = []
    yield
    _FakeRecordingEngine.calls = []


def _write_graph_file(tmp_path: Path) -> Path:
    graph_path = tmp_path / "playout-graph.json"
    graph_path.write_text(graph_to_json(demo_test_graph()), encoding="utf-8")
    return graph_path


def _install_fake_engine(worker_module: types.ModuleType) -> None:
    worker_module.enginemod.GstPlayoutEngine = _FakeRecordingEngine


def test_main_arms_the_plan_eos_hold_for_a_persistent_channel(
    worker_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The daemon's ACTIVE-channel launch marks the worker, and the marked worker
    holds the slate at plan EOS instead of quitting.

    The flag name is taken from the product (``reload_policy.WORKER_PERSISTENT_ENV``,
    the same constant ``strategy._default_worker_launcher`` sets), never typed --
    a divergence between the setter's name and the reader's would otherwise
    disable the hold silently, in the field.
    """
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker.py", str(graph_path)])
    monkeypatch.delenv("SWAPS", raising=False)
    monkeypatch.setenv(_FLAG_NAME, "1")
    _install_fake_engine(worker_module)

    assert worker_module.main() == 0

    assert _FakeRecordingEngine.calls == [{"control_fifo": None, "hold_slate_at_plan_eos": True}]


@pytest.mark.parametrize("value", [None, "", "0", "yes", "TRUE"])
def test_main_leaves_the_hold_off_unless_the_flag_is_exactly_one(
    worker_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str | None,
) -> None:
    """Anything but ``"1"`` is the finite run.

    ``None`` is the beta.5 baseline pin
    (``tests/egress/test_gst_engine_caption_flow_native.py``), whose ONLY
    shutdown is ``process.wait(timeout=40)`` after the plan plays out -- an
    unflagged worker must still exit at plan EOS, or that pin times out. The
    other values are a deployment that wrote something else into the variable;
    they must not silently turn a finite run into a channel that never ends.
    """
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker.py", str(graph_path)])
    monkeypatch.delenv("SWAPS", raising=False)
    if value is None:
        monkeypatch.delenv(_FLAG_NAME, raising=False)
    else:
        monkeypatch.setenv(_FLAG_NAME, value)
    _install_fake_engine(worker_module)

    assert worker_module.main() == 0

    assert _FakeRecordingEngine.calls == [{"control_fifo": None, "hold_slate_at_plan_eos": False}]


@_WINDOWS_PIPE_ONLY
def test_main_threads_the_flag_through_the_windows_pipe_entry_point(
    worker_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The production Windows path (argv[2] = the worker pipe name) arms the hold too.

    ``_run_forever_windows_pipe`` is the call site the station actually uses on
    native Windows -- the plain ``run_forever`` branch above is the POSIX one. A
    flag read in ``main()`` but not threaded here would leave the station's own
    channel exiting at plan EOS while every non-Windows test passed.

    The reader THREAD is stubbed (it imports ``gi``, which this environment does
    not have); what is under test is which ``run_forever`` call main() makes, not
    the pipe reader.
    """
    graph_path = _write_graph_file(tmp_path)
    pipe_name = r"\\.\pipe\civiccast-worker-ch1"
    monkeypatch.setattr(sys, "argv", ["worker.py", str(graph_path), pipe_name])
    monkeypatch.delenv("SWAPS", raising=False)
    monkeypatch.setenv(_FLAG_NAME, "1")
    monkeypatch.setattr(worker_module, "_windows_pipe_reader_loop", lambda *a, **k: None)
    _install_fake_engine(worker_module)

    assert worker_module.main() == 0

    assert _FakeRecordingEngine.calls == [{"control_fifo": None, "hold_slate_at_plan_eos": True}]
