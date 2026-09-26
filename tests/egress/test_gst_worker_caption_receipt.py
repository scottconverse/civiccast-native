# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-channel caption-leg receipt in the GStreamer playout worker (U46).

The caption control leg had no positive evidence anywhere: a worker whose engine
was taking caption cues and injecting them logged exactly what a worker that
received nothing logged -- nothing. On 2026-09-26 the public channel's emitted
stream carried no captions for hours and every caption-path log line stayed
quiet, because silence is what a healthy caption leg looks like from the other
side of the pipe.

``_CaptionReceiptCounter`` gives the worker one line per interval per channel:
captions received on the control pipe, injected into the live caption appsrc,
acked as a replay, and refused by the engine (no live caption source). The
window logic is driven here with a fake clock, so no thread and no wall-clock
wait is involved.

``worker.py`` is import-safe with only stdlib + the sibling gi-free modules (see
its own docstring), so it is imported here with ``civiccast.egress.gst.engine``
stubbed under its package name -- the same fixture pattern
``test_gst_worker_reload_ack.py`` and ``test_gst_worker_module_identity.py`` use.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator

import pytest

_WORKER = "civiccast.egress.gst.worker"
_ALIASES = tuple(f"civiccast.egress.gst.{name}" for name in ("control", "audio_tap", "engine"))

# The parsed shape ``control.parse_control_line`` returns for a caption line: the
# only element the receipt reads is the verb, but the tuple is passed whole so
# the counter sees exactly what the reader loop sees.
_CAPTION_PARSED = ("caption", 1000, 500, "aGVsbG8=")


@pytest.fixture
def worker_module() -> Iterator[types.ModuleType]:
    """Import ``worker.py`` with ``civiccast.egress.gst.engine`` stubbed (it needs
    real ``gi``, which this test environment does not have)."""
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


class _Clock:
    """Monotonic stand-in: the counter reads it, the test advances it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _counter(worker_module: types.ModuleType, **kwargs: object) -> types.SimpleNamespace:
    clock = _Clock()
    emitted: list[str] = []
    counter = worker_module._CaptionReceiptCounter(
        "public", clock=clock, emit=emitted.append, **kwargs
    )
    return types.SimpleNamespace(counter=counter, clock=clock, emitted=emitted)


def test_receipt_counts_received_injected_replayed_and_rejected(worker_module) -> None:
    rig = _counter(worker_module)
    counter = rig.counter

    for _ in range(3):
        counter.record_from_dispatch(_CAPTION_PARSED, "applied")
    counter.record_from_dispatch(_CAPTION_PARSED, "error")  # engine: no live caption source
    counter.record_from_dispatch(_CAPTION_PARSED, "applied", replayed=True)  # lost ack, re-acked
    counter.record_from_dispatch(("swap", 1), "applied")  # not the caption leg
    counter.record_from_dispatch(None, "error")  # unparseable line

    rig.clock.advance(60.0)
    line = counter.receipt_line()

    assert line is not None
    assert "public" in line
    assert "received=4" in line
    assert "injected=3" in line
    assert "replayed=1" in line
    assert "rejected=1" in line


def test_receipt_stays_quiet_before_the_interval_and_on_an_empty_window(worker_module) -> None:
    rig = _counter(worker_module)
    counter = rig.counter

    counter.record_from_dispatch(_CAPTION_PARSED, "applied")
    rig.clock.advance(59.0)
    assert counter.receipt_line() is None

    rig.clock.advance(1.0)
    line = counter.receipt_line()  # the window that closes the minute
    assert line is not None and "received=1" in line

    rig.clock.advance(60.0)
    assert counter.receipt_line() is None  # empty window: nothing to report yet


def test_receipt_warns_only_after_receipts_that_had_been_flowing_stop(worker_module) -> None:
    rig = _counter(worker_module, silent_windows=3)
    counter = rig.counter

    counter.record_from_dispatch(_CAPTION_PARSED, "applied")
    rig.clock.advance(60.0)
    assert counter.receipt_line() is not None

    for _ in range(2):  # two empty windows: not yet
        rig.clock.advance(60.0)
        assert counter.receipt_line() is None

    rig.clock.advance(60.0)
    warning = counter.receipt_line()
    assert warning is not None
    assert "WARNING" in warning
    assert "public" in warning
    assert "no caption command received" in warning

    rig.clock.advance(60.0)
    assert counter.receipt_line() is None  # announced once, not every window

    counter.record_from_dispatch(_CAPTION_PARSED, "applied")  # captions resume
    rig.clock.advance(60.0)
    assert counter.receipt_line() is not None


def test_receipt_never_reports_a_channel_that_never_received_a_caption(worker_module) -> None:
    """Live captions switched off for the station (or a channel that has not
    started them yet): the worker must stay silent, not warn once a minute."""
    rig = _counter(worker_module, silent_windows=2)
    counter = rig.counter

    for _ in range(10):
        rig.clock.advance(60.0)
        assert counter.receipt_line() is None


def test_receipt_label_is_the_channel_from_the_worker_pipe_name(worker_module) -> None:
    assert worker_module._caption_receipt_label(r"\\.\pipe\civiccast-worker-public") == "public"
    assert worker_module._caption_receipt_label(r"\\.\pipe\civiccast-worker-education") == (
        "education"
    )
