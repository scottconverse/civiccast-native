# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Round-2 review (Opus, PR #183), requirement 2: ``worker.py``'s ``main()`` must
return ``civiccast.egress.gst.exit_codes.GST_PREROLL_TIMEOUT_EXIT_CODE`` -- not the
generic crash code (1) -- when the engine raises ``PrerollTimeoutError`` (item 82).

``worker.py`` is import-safe with only stdlib + the sibling gi-free modules (its own
module docstring), so this drives ``main()`` directly against a FAKE
``civiccast.egress.gst.engine`` module stubbed into ``sys.modules`` -- mirrors
``tests/egress/test_gst_worker_module_identity.py``'s ``imported_worker`` fixture and
``tests/egress/test_gst_worker_reload_ack.py``'s ``worker_module`` fixture exactly, no
real ``gi``/GStreamer install needed.

Also covers requirement 5: the ``WORKER_RESULT`` receipt is still emitted on the
preroll-timeout exit path (before this fix, that exit returned with NO receipt at all,
so ``civiccast.native.installed_gstreamer_smoke.require_clean_worker_result`` would
report only "product worker emitted no WORKER_RESULT receipt" -- a generic message
that names nothing -- instead of naming the actual reason).
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from civiccast.egress.gst.graph import demo_test_graph, graph_to_json

_WORKER = "civiccast.egress.gst.worker"
_ALIASES = tuple(
    f"civiccast.egress.gst.{name}"
    for name in ("control", "audio_tap", "engine", "decode_policy", "reload_policy", "exit_codes")
)


class _FakePrerollTimeoutError(RuntimeError):
    """Stand-in for ``engine.PrerollTimeoutError`` -- worker.py's ``except``
    clause matches on ``enginemod.PrerollTimeoutError``, so the stub module
    must carry a real exception class under that attribute name."""


@pytest.fixture
def worker_module() -> Iterator[types.ModuleType]:
    """Import ``worker.py`` fresh with ``civiccast.egress.gst.engine`` stubbed
    (it needs real ``gi``, which this test environment does not have) --
    mirrors ``test_gst_worker_module_identity.py``'s ``imported_worker``
    fixture and ``test_gst_worker_reload_ack.py``'s ``worker_module`` fixture."""
    engine_stub = types.ModuleType("civiccast.egress.gst.engine")
    engine_stub.GstPlayoutEngine = object  # type: ignore[attr-defined]
    engine_stub.PrerollTimeoutError = _FakePrerollTimeoutError  # type: ignore[attr-defined]
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


class _FakeEngineInstanceRaisesPrerollTimeout:
    """Duck-typed stand-in for ``GstPlayoutEngine`` whose ``run_forever`` raises
    the (stubbed) ``PrerollTimeoutError`` exactly like the real engine does once
    ``_await_playing`` exceeds its bound."""

    def __init__(self, *_a: object, **_kw: object) -> None:
        pass

    def run_forever(self, *, control_fifo: str | None = None) -> dict[str, object]:
        raise _FakePrerollTimeoutError(
            "pipeline did not reach PLAYING within 30.0s (get_state=async)"
        )


def _write_graph_file(tmp_path: Path) -> Path:
    graph_path = tmp_path / "playout-graph.json"
    graph_path.write_text(graph_to_json(demo_test_graph()), encoding="utf-8")
    return graph_path


def test_main_returns_the_preroll_timeout_exit_code_when_the_engine_raises(
    worker_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker.py", str(graph_path)])
    monkeypatch.setattr(
        worker_module.enginemod, "GstPlayoutEngine", _FakeEngineInstanceRaisesPrerollTimeout
    )
    # SWAPS unset/0 and no control_fifo argv[2] -> main() takes the plain
    # run_forever() branch (never the Windows-pipe or fixed-swap-schedule
    # branches), which is what actually raises in production too.
    monkeypatch.delenv("SWAPS", raising=False)

    exit_code = worker_module.main()

    assert exit_code == worker_module.exit_codes_mod.GST_PREROLL_TIMEOUT_EXIT_CODE
    assert exit_code != 0
    assert exit_code != 1  # the generic crash code every OTHER engine failure uses

    err = capsys.readouterr().err
    assert "CTRL preroll: worker exiting" in err


def test_main_emits_a_worker_result_receipt_on_the_preroll_timeout_exit(
    worker_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requirement 5: ``civiccast.native.installed_gstreamer_smoke.
    require_clean_worker_result`` requires a ``WORKER_RESULT`` line in stdout
    or it reports an unhelpful "product worker emitted no WORKER_RESULT
    receipt" -- with this line present, its failure message instead NAMES the
    actual reason via this dict's ``error`` tuple."""
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker.py", str(graph_path)])
    monkeypatch.setattr(
        worker_module.enginemod, "GstPlayoutEngine", _FakeEngineInstanceRaisesPrerollTimeout
    )
    monkeypatch.delenv("SWAPS", raising=False)

    worker_module.main()

    out = capsys.readouterr().out
    line = next((line for line in out.splitlines() if line.startswith("WORKER_RESULT ")), None)
    assert line is not None, "must emit a WORKER_RESULT receipt even on this exit path"
    import ast

    result = ast.literal_eval(line.removeprefix("WORKER_RESULT "))
    assert isinstance(result, dict)
    assert result.get("error") is not None
    error = result["error"]
    assert error[0] == "preroll-timeout"
    assert "PLAYING" in error[1]
    assert result.get("teardown_clean") is False
