# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 85: gi-free ordering tests for ``GstPlayoutEngine._commit_reload`` /
``_dispose_source_leg``.

Root cause (sandbox runs 12/14/15, seven soaks): the pre-fix ``_commit_reload``
switched the input-selector's ``active-pad`` onto the new leg BEFORE releasing
that leg's hold probes, and ``_dispose_source_leg`` NULLed a retiring leg's
elements BEFORE unlinking/releasing its selector request pad. Either ordering
can wedge a streaming thread inside GStreamer forever, blocking the GLib
main-loop thread's synchronous ``set_state``/``get_state`` call and hanging the
worker permanently -- the last line either wedged worker ever printed was "CTRL
reload: boundary switch rebased...", never "CTRL reload committed".

These tests load ``civiccast.egress.gst.engine`` fresh against a small FAKE
``gi``/``Gst`` (same technique as
``test_gst_engine_reload_concat_naming.py``) so the fix's ORDERING can be
proven without a real GStreamer/gi install, a real pipeline, or a main loop --
only ``GstPlayoutEngine._commit_reload_body``/``_dispose_source_leg`` are
exercised, against pad/selector/element doubles that record every call into one
shared, ordered list."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"


class _Recorder:
    """One shared, ORDER-preserving call log every fake below appends to --
    the whole point of these tests is relative ordering, not call counts."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class _FakeEvent:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return f"<FakeEvent {self.kind}>"


class _FakeEventFactory:
    @staticmethod
    def new_flush_start() -> _FakeEvent:
        return _FakeEvent("flush-start")

    @staticmethod
    def new_flush_stop(_reset_time: bool) -> _FakeEvent:
        return _FakeEvent("flush-stop")


class _FakeState:
    NULL = "NULL"


class _FakeIteratorResult:
    OK = "OK"


class _FakeElementIterator:
    """Empty iterator: ``_element_count`` just needs SOMETHING that returns a
    non-OK result on the first ``.next()`` call so the count loop ends at 0 --
    the exact count is irrelevant to these ordering tests."""

    def next(self) -> tuple[str, None]:
        return "DONE", None


class _FakePipeline:
    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    def remove(self, element: _FakeOldElement) -> None:
        self.recorder.calls.append(f"pipeline.remove:{element.name}")

    def iterate_elements(self) -> _FakeElementIterator:
        return _FakeElementIterator()


class _FakeHoldPad:
    """A new leg's tail pad, held by a blocking probe -- ``remove_probe`` is
    what ``_release_hold_probes`` calls to let its streaming thread go."""

    def __init__(self, name: str, recorder: _Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def remove_probe(self, probe_id: Any) -> None:
        self.recorder.calls.append(f"remove_probe:{self.name}:{probe_id}")


class _FakeSelector:
    """The input-selector (or audio-selector) ``_commit_reload``/
    ``_dispose_source_leg`` operate on."""

    def __init__(self, name: str, recorder: _Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def set_property(self, key: str, value: Any) -> None:
        value_name = getattr(value, "name", value)
        self.recorder.calls.append(f"{self.name}.set_property:{key}={value_name}")

    def release_request_pad(self, pad: _FakeOldPad) -> None:
        self.recorder.calls.append(f"{self.name}.release_request_pad:{pad.name}")


class _FakePeer:
    def __init__(self, name: str, recorder: _Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def unlink(self, pad: _FakeOldPad) -> None:
        self.recorder.calls.append(f"peer.unlink:{self.name}->{pad.name}")


class _FakeOldPad:
    """The RETIRING leg's own selector-side request pad -- what
    ``_dispose_source_leg`` flushes, unlinks, and releases."""

    def __init__(self, name: str, recorder: _Recorder, peer: _FakePeer | None) -> None:
        self.name = name
        self.recorder = recorder
        self._peer = peer

    def get_peer(self) -> _FakePeer | None:
        return self._peer

    def send_event(self, event: _FakeEvent) -> bool:
        self.recorder.calls.append(f"send_event:{self.name}:{event.kind}")
        return True


class _FakeOldElement:
    """One of the retiring leg's elements -- ``set_state(NULL)`` is the call
    that, on a real wedged leg, blocked the GLib main-loop thread forever."""

    def __init__(self, name: str, recorder: _Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def set_state(self, state: Any) -> None:
        self.recorder.calls.append(f"set_state:{self.name}:{state}")


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.Event = _FakeEventFactory  # type: ignore[attr-defined]
    fake_gst.State = _FakeState  # type: ignore[attr-defined]
    fake_gst.IteratorResult = _FakeIteratorResult  # type: ignore[attr-defined]
    return fake_gst


@pytest.fixture
def engine_module():
    """Load ``civiccast.egress.gst.engine`` fresh against a fake ``gi``/``Gst``
    -- no real GStreamer install required. Mirrors
    ``test_gst_engine_reload_concat_naming.py``'s fixture of the same name and
    the same sys.modules save/restore discipline."""
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_repository = types.ModuleType("gi.repository")
    fake_glib = types.ModuleType("gi.repository.GLib")
    fake_glib.source_remove = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_gst = _install_fake_gst()
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


def _bare_engine_for_commit(module: types.ModuleType, recorder: _Recorder) -> Any:
    engine = object.__new__(module.GstPlayoutEngine)
    engine.selector = _FakeSelector("video_sel", recorder)
    engine.audio_selector = _FakeSelector("audio_sel", recorder)
    engine.selector_sink_pads = [None]
    engine.audio_sink_pads = [None]
    engine._source_leg_elements = [None]
    engine.pipeline = _FakePipeline(recorder)
    engine._pending_reload = None
    engine._error = None
    return engine


def test_commit_releases_hold_probes_before_switching_active_pad(engine_module) -> None:
    """Item 85 root-cause assertion (a): every hold pad's ``remove_probe`` fires
    BEFORE the selector's ``active-pad`` is ever touched. The pre-fix code did
    this backwards (switch, THEN release) -- exactly the ordering the seven
    measured sandbox soaks wedged on."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    new_video_pad = object()
    new_audio_pad = object()
    hold_video = _FakeHoldPad("hold-video", recorder)
    hold_audio = _FakeHoldPad("hold-audio", recorder)
    old_video_pad = _FakeOldPad("old-video", recorder, peer=None)
    old_audio_pad = _FakeOldPad("old-audio", recorder, peer=None)

    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": new_video_pad,
        "new_audio_pad": new_audio_pad,
        "rebase_new_leg": False,
        "hold_probes": [(hold_video, "probe-1"), (hold_audio, "probe-2")],
        "boundary_probes": [],
        "old_video_pad": old_video_pad,
        "old_audio_pad": old_audio_pad,
        "old_elements": [],
        "new_elements": [],
        "on_settled": None,
    }

    result = engine._commit_reload_body(pending)

    assert result is False  # one-shot GLib-source contract
    calls = recorder.calls

    def index_of(prefix: str) -> int:
        for i, call in enumerate(calls):
            if call.startswith(prefix):
                return i
        raise AssertionError(f"{prefix!r} never called; calls={calls}")

    remove_video = index_of("remove_probe:hold-video")
    remove_audio = index_of("remove_probe:hold-audio")
    switch_video = index_of("video_sel.set_property:active-pad")
    switch_audio = index_of("audio_sel.set_property:active-pad")

    assert remove_video < switch_video, (
        f"video hold probe released AFTER active-pad switch; calls={calls}"
    )
    assert remove_audio < switch_audio, (
        f"audio hold probe released AFTER active-pad switch; calls={calls}"
    )


def test_commit_disposes_old_leg_by_unlinking_before_nulling(engine_module) -> None:
    """Item 85 root-cause assertion (a), second half: the retiring leg's selector
    pad is flushed/unlinked/released BEFORE any of its elements are told to NULL.
    The pre-fix ``_dispose_source_leg`` NULLed first -- if that leg's streaming
    thread was parked inside the selector's own wait (not this leg's element at
    all), NULLing never returns and the calling (GLib main-loop) thread hangs
    forever."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    old_video_peer = _FakePeer("old-video-peer", recorder)
    old_audio_peer = _FakePeer("old-audio-peer", recorder)
    old_video_pad = _FakeOldPad("old-video", recorder, peer=old_video_peer)
    old_audio_pad = _FakeOldPad("old-audio", recorder, peer=old_audio_peer)
    old_element_1 = _FakeOldElement("old-elem-1", recorder)
    old_element_2 = _FakeOldElement("old-elem-2", recorder)

    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": object(),
        "rebase_new_leg": False,
        "hold_probes": [],
        "boundary_probes": [],
        "old_video_pad": old_video_pad,
        "old_audio_pad": old_audio_pad,
        "old_elements": [old_element_1, old_element_2],
        "new_elements": [],
        "on_settled": None,
    }

    engine._commit_reload_body(pending)
    calls = recorder.calls

    def index_of(prefix: str) -> int:
        for i, call in enumerate(calls):
            if call.startswith(prefix):
                return i
        raise AssertionError(f"{prefix!r} never called; calls={calls}")

    unlink_video = index_of("peer.unlink:old-video-peer")
    release_video = index_of("video_sel.release_request_pad:old-video")
    unlink_audio = index_of("peer.unlink:old-audio-peer")
    release_audio = index_of("audio_sel.release_request_pad:old-audio")
    null_1 = index_of("set_state:old-elem-1")
    null_2 = index_of("set_state:old-elem-2")

    assert unlink_video < null_1, f"video pad unlinked AFTER set_state(NULL); calls={calls}"
    assert release_video < null_1, (
        f"video request pad released AFTER set_state(NULL); calls={calls}"
    )
    assert unlink_audio < null_1, f"audio pad unlinked AFTER set_state(NULL); calls={calls}"
    assert release_audio < null_1, (
        f"audio request pad released AFTER set_state(NULL); calls={calls}"
    )
    assert null_2 >= 0  # both elements were NULLed; their relative order is not asserted

    # Flush brackets the unlink -- start before, stop after -- on both pads, so a
    # thread parked in the selector's own wait on either pad wakes before the
    # pad is torn out from under it.
    flush_start_video = index_of("send_event:old-video:flush-start")
    flush_stop_video = index_of("send_event:old-video:flush-stop")
    assert flush_start_video < unlink_video < flush_stop_video, (
        f"video flush did not bracket the unlink; calls={calls}"
    )


def test_dispose_source_leg_is_best_effort_on_a_disposal_hiccup(engine_module) -> None:
    """A disposal failure must be swallowed (logged), never raised -- a reload
    disposal hiccup must not be able to kill a live channel (pre-existing
    contract, unchanged by the item 85 reordering)."""

    class _RaisingElement:
        def set_state(self, _state: Any) -> None:
            raise RuntimeError("boom")

    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.selector = None
    engine.audio_selector = None

    # Must not raise.
    engine._dispose_source_leg(None, None, [_RaisingElement()])


# --- item 85 (c): the commit watchdog THREAD escapes a commit that never returns ---


def test_commit_watchdog_force_exits_when_the_commit_never_returns(
    engine_module, monkeypatch
) -> None:
    """Item 85's second escape hatch: if ``_commit_reload`` (simulated here by
    simply never calling ``watchdog.cancel()``, i.e. a commit that hangs forever
    and never returns control) does not finish within ``commit_timeout_s``, the
    watchdog THREAD -- not a GLib timeout source, which could never fire if the
    SAME thread that would run it is the one wedged -- must fire on its own,
    independent OS thread, print the diagnosis, attempt a bounded/non-blocking
    pipeline teardown, and force-exit with the distinct
    ``GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE``. ``os._exit`` itself is monkeypatched
    (calling the real one would kill the test process) -- it is recorded instead,
    proving it was reached with the right argument, without actually exiting."""
    from civiccast.egress.gst.exit_codes import GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE

    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 0.05
    engine.pipeline.set_state = lambda state: recorder.calls.append(  # type: ignore[attr-defined]
        f"pipeline.set_state:{state}"
    )
    exit_calls: list[int] = []
    monkeypatch.setattr(engine_module.os, "_exit", exit_calls.append)

    watchdog = engine._arm_commit_watchdog()
    # A commit that never returns never calls watchdog.cancel() -- exactly the
    # condition this thread exists to escape. Join (bounded) rather than sleep:
    # the thread fires as soon as its own timer elapses, not on this test's clock.
    watchdog.join(timeout=5.0)

    assert not watchdog.is_alive(), "commit watchdog thread never fired"
    assert exit_calls == [int(GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE)]
    assert engine._error == ("reload-commit-timeout", "commit did not complete in time")
    assert any(call.startswith("pipeline.set_state:") for call in recorder.calls), (
        "watchdog did not attempt a bounded teardown before force-exiting"
    )


def test_commit_watchdog_is_a_no_op_when_the_commit_finishes_in_time(
    engine_module, monkeypatch
) -> None:
    """The normal case: a commit that finishes well within ``commit_timeout_s``
    cancels the watchdog and the process is never touched."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 5.0
    engine._pending_reload = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": None,
        "rebase_new_leg": False,
        "hold_probes": [],
        "boundary_probes": [],
        "old_video_pad": _FakeOldPad("old-video", recorder, peer=None),
        "old_audio_pad": None,
        "old_elements": [],
        "new_elements": [],
        "on_settled": None,
    }
    exit_calls: list[int] = []
    monkeypatch.setattr(engine_module.os, "_exit", exit_calls.append)

    result = engine._commit_reload()

    assert result is False
    assert exit_calls == [], "a commit that finished in time must never force-exit"
    assert engine._error is None
