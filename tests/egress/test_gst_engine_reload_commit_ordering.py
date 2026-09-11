# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""GI-free reload-commit ordering, stale-callback, logging, and watchdog tests.

Physical beta.5 and native production-shaped traces localized the reload
wedge to synchronous old-leg disposal after the selector switch and new-leg
hold release. GStreamer 1.28.5 holds input-selector's active-pad reader lock
across a downstream push while request-pad release needs its writer lock.
Holding the replacement through synchronous main-loop retirement was also
disproven: the old audio concat then blocks because the main loop cannot
advance downstream caption flow. Native diagnostics verified a combination
that inserts bounded post-selector queues, keeps the GLib loop available while
a retirement thread cleans the old leg, and releases replacement holds only
after cleanup. The tests cover that production phase order, transaction
ownership, and diagnostics.
Releasing before selecting would lose the replacement's first buffers at a
non-caching selector; unlinking before NULL risks ``GST_FLOW_NOT_LINKED``.

These tests load ``civiccast.egress.gst.engine`` fresh against a small fake
``gi``/``Gst`` (the same technique as the concat-naming tests). They exercise
the commit/dispose/EOS helpers without a real pipeline or main loop, covering
the lock-safe ordering, superseded/stale EOS containment, staged diagnostics,
and the independent commit-watchdog thread."""

from __future__ import annotations

import importlib
import sys
import threading
import types
from typing import Any

import pytest

from scripts.ops.check_reload_preroll import check_log

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"


class _Recorder:
    """One shared, ORDER-preserving call log every fake below appends to --
    the whole point of these tests is relative ordering, not call counts."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class _FakeState:
    NULL = "NULL"


class _FakeStateChangeReturn:
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ASYNC = "ASYNC"
    NO_PREROLL = "NO_PREROLL"


class _FakePadProbeType:
    BUFFER = 1
    BUFFER_LIST = 2
    EVENT_DOWNSTREAM = 4


class _FakePadProbeReturn:
    OK = "OK"
    DROP = "DROP"


class _FakeMessageType:
    ERROR = "ERROR"
    EOS = "EOS"


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

    def add_probe(self, mask: Any, callback: Any) -> str:
        """Round-2 finding 1: the abort path installs a DROP probe here BEFORE it
        lifts the hold, so the aborted leg never pushes into the selector."""
        self.recorder.calls.append(f"add_probe:{self.name}:{mask}:{callback.__name__}")
        return f"{self.name}-drop-probe"


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

    def push_event(self, event: Any) -> bool:
        self.recorder.calls.append(f"peer.push_event:{self.name}:{event}")
        return True


class _FakeOldPad:
    """The RETIRING leg's own selector-side request pad -- what
    ``_dispose_source_leg`` unlinks and releases. NOT expected to see any
    ``send_event`` call in the current design -- see
    ``test_dispose_source_leg_never_sends_flush_events``."""

    def __init__(self, name: str, recorder: _Recorder, peer: _FakePeer | None) -> None:
        self.name = name
        self.recorder = recorder
        self._peer = peer

    def get_peer(self) -> _FakePeer | None:
        return self._peer

    def send_event(self, event: Any) -> bool:  # pragma: no cover - must not be called
        self.recorder.calls.append(f"send_event:{self.name}:{event}")
        return True


class _FakeOldElement:
    """One of the retiring leg's elements -- ``set_state(NULL)``."""

    def __init__(self, name: str, recorder: _Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def get_name(self) -> str:
        return self.name

    def get_factory(self) -> Any:
        return types.SimpleNamespace(get_name=lambda: "fake-element")

    def set_state(self, state: Any) -> str:
        self.recorder.calls.append(f"set_state:{self.name}:{state}")
        return _FakeStateChangeReturn.SUCCESS

    def get_state(self, timeout: Any) -> tuple[str, str, str]:
        """A bin that answered ASYNC settles to NULL within the bounded wait."""
        self.recorder.calls.append(f"get_state:{self.name}:{timeout}")
        return (_FakeStateChangeReturn.SUCCESS, _FakeState.NULL, _FakeState.NULL)


class _FakeEvent:
    @staticmethod
    def new_flush_start() -> str:
        return "FLUSH_START"


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.State = _FakeState  # type: ignore[attr-defined]
    fake_gst.StateChangeReturn = _FakeStateChangeReturn  # type: ignore[attr-defined]
    fake_gst.MessageType = _FakeMessageType  # type: ignore[attr-defined]
    fake_gst.IteratorResult = _FakeIteratorResult  # type: ignore[attr-defined]
    fake_gst.SECOND = 1  # type: ignore[attr-defined]
    fake_gst.PadProbeType = _FakePadProbeType  # type: ignore[attr-defined]
    fake_gst.PadProbeReturn = _FakePadProbeReturn  # type: ignore[attr-defined]
    fake_gst.Event = _FakeEvent  # type: ignore[attr-defined]
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
    fake_glib.idle_add = lambda function, *args: function(*args)  # type: ignore[attr-defined]
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
    engine._abort_retire_threads = []
    engine._reload_commit_thread = None
    engine._stopping = False
    engine._error = None
    engine._loop = None
    engine._pending_overlay_swaps = {}
    return engine


def _complete_commit_for_test(engine: Any, pending: dict[str, Any]) -> bool:
    """Run the three production phases serially while retaining their exact order."""
    pending.setdefault("commit_in_progress", True)
    pending.setdefault("commit_watchdog", None)
    pending.setdefault("commit_completed", None)
    pending.setdefault("retirement_result", None)
    engine._pending_reload = pending
    engine._begin_reload_commit(pending)
    pending["retirement_result"] = engine._dispose_source_leg(
        pending["old_video_pad"], pending["old_audio_pad"], pending["old_elements"]
    )
    return engine._finish_reload_commit(pending)


def _index_of(calls: list[str], prefix: str) -> int:
    for i, call in enumerate(calls):
        if call.startswith(prefix):
            return i
    raise AssertionError(f"{prefix!r} never called; calls={calls}")


def _unready_reload(recorder: _Recorder, txn_id: int = 1) -> dict[str, Any]:
    video = _FakeHoldPad("new-video", recorder)
    audio = _FakeHoldPad("new-audio", recorder)
    return {
        "txn_id": txn_id,
        "new_leg_ready": False,
        "holds_awaited": 2,
        "held_pads": set(),
        "ready_pads": set(),
        "readiness_probes": [],
        "new_src_pads": [video, audio],
        "hold_probes": [(video, 1), (audio, 2)],
        "new_video_pad": video,
        "new_audio_pad": audio,
        "new_elements": [],
        "old_video_pad": _FakeOldPad("old-video", recorder, None),
        "old_audio_pad": None,
        "old_elements": [_FakeOldElement("old-program", recorder)],
        "switch_at_end_of_current": True,
        "old_leg_eos": True,
        "rebase_new_leg": False,
        "boundary_probes": [],
        "timeout_id": None,
        "defer_timeout_id": None,
        "on_settled": None,
    }


def test_f1_never_prerolled_reload_cannot_dispose_or_commit(engine_module, capsys) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 5.0
    pending = _unready_reload(recorder)
    engine._pending_reload = pending
    assert engine._commit_reload() is False
    thread = engine._reload_commit_thread
    if thread is not None:
        thread.join(timeout=1.0)
    assert recorder.calls == [], "an unready replacement must not switch or retire the old leg"
    assert engine._pending_reload is pending
    assert "committed (elements=" not in capsys.readouterr().out


@pytest.mark.parametrize("held", [False, True])
def test_f1_queued_readiness_cannot_ready_a_superseding_reload(
    engine_module, monkeypatch, held
) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    old = _unready_reload(recorder)
    current = _unready_reload(recorder, txn_id=2)
    if not held:
        for pending in (old, current):
            pending["hold_probes"] = []
            pending["holds_awaited"] = 0
            pending["readiness_probes"] = [
                (pad, i) for i, pad in enumerate(pending["new_src_pads"])
            ]
    engine._pending_reload = old
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setattr(engine_module.GLib, "idle_add", lambda fn, *args: queued.append((fn, args)))
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")
    if held:
        engine._on_new_leg_hold(old["new_src_pads"][0], None, old["txn_id"])
    else:
        # The non-held path also queues a callback from a streaming thread.
        engine_module.Gst.PadProbeReturn.REMOVE = "REMOVE"
        engine._on_reload_first_buffer(old["new_video_pad"], None, old["txn_id"])
    engine._pending_reload = current
    for callback, args in queued:
        callback(*args)
    assert current["new_leg_ready"] is False
    assert current["holds_awaited"] == (2 if held else 0)
    assert commits == []


@pytest.mark.parametrize("deferred", [False, True])
def test_f1_unheld_video_cannot_commit_before_audio_prerolls(engine_module, deferred) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    pending = _unready_reload(recorder)
    pending["hold_probes"] = []
    pending["holds_awaited"] = 0
    pending["switch_at_end_of_current"] = deferred
    pending["readiness_probes"] = [(pad, i) for i, pad in enumerate(pending["new_src_pads"])]
    engine._pending_reload = pending
    engine_module.Gst.PadProbeReturn.REMOVE = "REMOVE"
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")
    video, audio = pending["new_src_pads"]
    engine._on_reload_first_buffer(video, None, pending["txn_id"])
    engine._on_reload_first_buffer(video, None, pending["txn_id"])
    assert pending["new_leg_ready"] is False
    assert commits == []
    engine._on_reload_first_buffer(audio, None, pending["txn_id"])
    assert pending["new_leg_ready"] is True
    assert commits == ["commit"]


def test_f1_duplicate_hold_cannot_substitute_for_unprerolled_audio(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    pending = _unready_reload(recorder)
    engine._pending_reload = pending
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")
    video, audio = pending["new_src_pads"]
    engine._on_new_leg_hold(video, None, pending["txn_id"])
    engine._on_new_leg_hold(video, None, pending["txn_id"])
    assert pending["new_leg_ready"] is False
    assert pending["holds_awaited"] == 1
    assert commits == []
    engine._on_new_leg_hold(audio, None, pending["txn_id"])
    assert pending["new_leg_ready"] is True
    assert commits == ["commit"]


@pytest.mark.parametrize("timer", ["_on_reload_timeout", "_on_defer_switch_timeout"])
def test_f1_stale_timer_cannot_abort_or_commit_new_transaction(engine_module, timer) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    pending = _unready_reload(recorder, txn_id=2)
    pending["old_leg_eos"] = False
    engine._pending_reload = pending
    actions: list[str] = []
    engine._commit_reload = lambda: actions.append("commit")
    engine._abort_pending_reload = actions.append
    assert getattr(engine, timer)(1) is False
    assert actions == []
    assert engine._pending_reload is pending
    assert pending["old_leg_eos"] is False


@pytest.mark.parametrize("missing", ["audio", "boundary"])
def test_f1_commit_requires_all_streams_and_due_boundary(engine_module, missing) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    pending = _unready_reload(recorder)
    pending["new_leg_ready"] = True
    if missing == "boundary":
        pending["holds_awaited"] = 0
        pending["old_leg_eos"] = False
    engine._pending_reload = pending
    engine._begin_reload_commit = lambda _pending: pytest.fail("premature selector switch")
    assert engine._commit_reload() is False
    assert engine._reload_commit_thread is None
    assert recorder.calls == []


def test_f1_commit_log_requires_current_preroll_holds(engine_module, capsys) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 5.0
    pending = _unready_reload(recorder)
    engine._pending_reload = pending
    video, audio = pending["new_src_pads"]
    engine._on_new_leg_hold(video, None, pending["txn_id"])
    assert engine._reload_commit_thread is None
    engine._on_new_leg_hold(audio, None, pending["txn_id"])
    thread = engine._reload_commit_thread
    if thread is not None:
        thread.join(timeout=1.0)
    lines = capsys.readouterr().out.splitlines()
    hold = next(i for i, line in enumerate(lines) if "(0 stream(s) still to preroll)" in line)
    proof = next(i for i, line in enumerate(lines) if "preroll verified (reload_id=1)" in line)
    fire = next(i for i, line in enumerate(lines) if "firing (reload_id=1)" in line)
    disposed = next(i for i, line in enumerate(lines) if "old leg disposed" in line)
    commit = next(i for i, line in enumerate(lines) if "committed (elements=" in line)
    assert hold < proof < fire < disposed < commit
    assert check_log("\n".join(lines)) == (1, [])
    assert engine._pending_reload is None


# --- (1) settle only the current reload's first A/V boundary --------------------


def test_deferred_commit_uses_first_current_outgoing_stream_eos(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first A/V EOS is the boundary; waiting for both can stop the mux."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    video_pad = _FakeOldPad("old-video", recorder, peer=None)
    audio_pad = _FakeOldPad("old-audio", recorder, peer=None)
    commits: list[str] = []

    def _commit() -> None:
        commits.append("commit")
        engine._pending_reload = None

    engine._commit_reload = _commit  # type: ignore[method-assign]
    engine._pending_reload = {
        "boundary_probes": [(video_pad, "video-probe"), (audio_pad, "audio-probe")],
        "outgoing_eos_pads": set(),
        "txn_id": 1,
        "old_video_pad": video_pad,
        "old_audio_pad": audio_pad,
        "old_leg_eos": False,
        "new_leg_ready": True,
    }

    assert engine._on_old_leg_eos(video_pad, 1) is False
    assert commits == ["commit"]
    # Queued sibling/duplicate callbacks arrive after the real commit cleared the
    # transaction and cannot settle anything a second time.
    assert engine._on_old_leg_eos(video_pad, 1) is False
    assert engine._on_old_leg_eos(audio_pad, 1) is False
    assert commits == ["commit"]
    stderr = capsys.readouterr().err
    assert "CTRL reload: outgoing EOS observed stream=video (1/2 stream(s))" in stderr
    assert "stream=audio" not in stderr


def test_deferred_video_only_commit_still_settles_on_its_only_eos(engine_module) -> None:
    """The first-boundary trigger also supports legitimate video-only legs."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    video_pad = _FakeOldPad("old-video", recorder, peer=None)
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")  # type: ignore[method-assign]
    engine._pending_reload = {
        "boundary_probes": [(video_pad, "video-probe")],
        "outgoing_eos_pads": set(),
        "txn_id": 1,
        "old_video_pad": video_pad,
        "old_audio_pad": None,
        "old_leg_eos": False,
        "new_leg_ready": True,
    }

    assert engine._on_old_leg_eos(video_pad, 1) is False
    assert commits == ["commit"]
    assert engine._pending_reload["old_leg_eos"] is True


def test_stale_outgoing_eos_cannot_settle_a_superseding_reload(engine_module) -> None:
    """An idle callback queued by an older leg is ignored after supersession."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    stale_pad = _FakeOldPad("superseded-video", recorder, peer=None)
    current_pad = _FakeOldPad("current-video", recorder, peer=None)
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")  # type: ignore[method-assign]
    engine._pending_reload = {
        "boundary_probes": [(current_pad, "current-probe")],
        "outgoing_eos_pads": set(),
        "txn_id": 1,
        "old_leg_eos": False,
        "new_leg_ready": True,
    }

    assert engine._on_old_leg_eos(stale_pad, 1) is False
    assert commits == []
    assert engine._pending_reload["outgoing_eos_pads"] == set()
    assert engine._pending_reload["old_leg_eos"] is False


def test_stale_outgoing_eos_cannot_settle_an_immediate_reload(engine_module) -> None:
    """An immediate reload has no boundary pads and rejects an older EOS callback."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    stale_pad = _FakeOldPad("superseded-video", recorder, peer=None)
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")  # type: ignore[method-assign]
    engine._pending_reload = {
        "boundary_probes": [],
        "outgoing_eos_pads": set(),
        "txn_id": 1,
        "old_leg_eos": True,
        "new_leg_ready": True,
    }

    assert engine._on_old_leg_eos(stale_pad, 1) is False
    assert commits == []
    assert engine._pending_reload["outgoing_eos_pads"] == set()


def test_stale_outgoing_eos_on_the_same_pad_cannot_settle_a_superseding_reload(
    engine_module,
) -> None:
    """Round-2 finding 5: pad identity alone was not enough to reject a stale EOS.

    The boundary probes live on the OUTGOING selector sink pads, and a superseded
    transaction and the one that replaced it watch the SAME pad object. The old
    ``pad in expected`` guard therefore admitted a stale ``idle_add`` EOS queued by
    the superseded transaction and let it settle -- and commit -- its successor.
    The transaction id the probe captured at install time is what distinguishes
    them."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    shared_pad = _FakeOldPad("outgoing-video", recorder, peer=None)
    commits: list[str] = []
    engine._commit_reload = lambda: commits.append("commit")  # type: ignore[method-assign]
    engine._pending_reload = {
        "boundary_probes": [(shared_pad, "current-probe")],
        "outgoing_eos_pads": set(),
        "txn_id": 7,
        "old_video_pad": shared_pad,
        "old_audio_pad": None,
        "old_leg_eos": False,
        "new_leg_ready": True,
    }

    # Queued by transaction 6, delivered after 7 replaced it, on the same pad.
    assert engine._on_old_leg_eos(shared_pad, 6) is False
    assert commits == []
    assert engine._pending_reload["outgoing_eos_pads"] == set()
    assert engine._pending_reload["old_leg_eos"] is False

    # The current transaction's own EOS on that very same pad still settles it.
    assert engine._on_old_leg_eos(shared_pad, 7) is False
    assert commits == ["commit"]


# --- (2) select, retire old leg with replacement held, then release --------------


def test_commit_retires_old_leg_before_releasing_replacement(engine_module) -> None:
    """Queues let old retirement finish while new selector pushes remain held."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    new_video_pad = object()
    new_audio_pad = object()
    hold_video = _FakeHoldPad("hold-video", recorder)
    hold_audio = _FakeHoldPad("hold-audio", recorder)
    old_video_pad = _FakeOldPad("old-video", recorder, peer=_FakePeer("old-video-peer", recorder))
    old_audio_pad = _FakeOldPad("old-audio", recorder, peer=_FakePeer("old-audio-peer", recorder))
    old_element = _FakeOldElement("old-elem", recorder)

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
        "old_elements": [old_element],
        "new_elements": [],
        "on_settled": None,
    }

    result = _complete_commit_for_test(engine, pending)

    assert result is False  # one-shot GLib-source contract
    calls = recorder.calls

    switch_video = _index_of(calls, "video_sel.set_property:active-pad")
    switch_audio = _index_of(calls, "audio_sel.set_property:active-pad")
    old_null = _index_of(calls, "set_state:old-elem:NULL")
    release_video = _index_of(calls, "video_sel.release_request_pad:old-video")
    release_audio = _index_of(calls, "audio_sel.release_request_pad:old-audio")
    remove_video = _index_of(calls, "remove_probe:hold-video")
    remove_audio = _index_of(calls, "remove_probe:hold-audio")

    assert switch_video < old_null < release_video < remove_video, calls
    assert switch_audio < old_null < release_audio < remove_audio, calls


def test_commit_disposes_old_leg_by_nulling_before_unlinking(engine_module) -> None:
    """The retiring leg's elements
    are told ``set_state(NULL)`` BEFORE the selector unlinks/releases that
    leg's request pad, not after. Unlinking/releasing FIRST (round 1's
    reverted hypothesis) races the leg's still-live streaming thread into
    pushing a buffer through a pad with no peer -- ``GST_FLOW_NOT_LINKED``, a
    FATAL flow error on that leg's own source pad -- while the leg is still
    being told to shut down."""
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

    _complete_commit_for_test(engine, pending)
    calls = recorder.calls

    null_1 = _index_of(calls, "set_state:old-elem-1")
    null_2 = _index_of(calls, "set_state:old-elem-2")
    unlink_video = _index_of(calls, "peer.unlink:old-video-peer")
    release_video = _index_of(calls, "video_sel.release_request_pad:old-video")
    unlink_audio = _index_of(calls, "peer.unlink:old-audio-peer")
    release_audio = _index_of(calls, "audio_sel.release_request_pad:old-audio")

    assert null_1 < unlink_video, f"video pad unlinked BEFORE set_state(NULL); calls={calls}"
    assert null_1 < release_video, (
        f"video request pad released BEFORE set_state(NULL); calls={calls}"
    )
    assert null_1 < unlink_audio, f"audio pad unlinked BEFORE set_state(NULL); calls={calls}"
    assert null_1 < release_audio, (
        f"audio request pad released BEFORE set_state(NULL); calls={calls}"
    )
    assert null_2 >= 0  # both elements were NULLed; their relative order is not asserted


def test_dispose_flushes_the_retiring_leg_peer_before_null_without_reopening_it(
    engine_module,
) -> None:
    """The flush starts at each retiring leg tail, never at a selector request pad.

    It must precede ``set_state(NULL)`` so blocked concat tasks can return
    FLUSHING before teardown waits for their STREAM_LOCK. There is deliberately no
    matching FLUSH_STOP: the leg is about to be removed and must never resume."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    old_video_pad = _FakeOldPad("old-video", recorder, peer=_FakePeer("old-video-peer", recorder))
    old_audio_pad = _FakeOldPad("old-audio", recorder, peer=_FakePeer("old-audio-peer", recorder))

    engine._dispose_source_leg(old_video_pad, old_audio_pad, [_FakeOldElement("elem", recorder)])

    video_flush = _index_of(recorder.calls, "peer.push_event:old-video-peer:FLUSH_START")
    audio_flush = _index_of(recorder.calls, "peer.push_event:old-audio-peer:FLUSH_START")
    null = _index_of(recorder.calls, "set_state:elem:NULL")
    assert video_flush < null
    assert audio_flush < null
    assert not any(call.startswith("send_event:") for call in recorder.calls), recorder.calls
    assert not any("FLUSH_STOP" in call for call in recorder.calls), recorder.calls


def test_dispose_source_leg_is_best_effort_on_a_disposal_hiccup(engine_module) -> None:
    """A disposal failure must be swallowed (logged), never raised -- a reload
    disposal hiccup must not be able to kill a live channel (pre-existing
    contract)."""

    class _RaisingElement:
        def set_state(self, _state: Any) -> None:
            raise RuntimeError("boom")

    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.selector = None
    engine.audio_selector = None

    # Must not raise, but must also not misreport the partial cleanup as success.
    ok, reason = engine._dispose_source_leg(None, None, [_RaisingElement()])
    assert ok is False
    assert reason is not None and "element-null-error:1" in reason


# --- (3) the four staged diagnostic log lines fire, in order --------------------


def test_commit_prints_the_four_staged_log_lines_in_order(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep stdout's settlement contract and mirror distinct stages to stderr.

    Sandbox verdict parsing consumes ``CTRL reload committed`` from stdout.  The
    daemon captures stderr independently, so distinct diagnostic stages go there
    without moving or duplicating the settlement marker that existing evidence
    consumers count.
    """
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    pending: dict[str, Any] = {
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

    _complete_commit_for_test(engine, pending)
    captured = capsys.readouterr()
    out = captured.out

    markers = (
        "CTRL reload: switching selector",
        "CTRL reload: old leg disposed",
        "CTRL reload: holds released",
        "CTRL reload committed",
    )
    positions = [out.index(marker) for marker in markers]
    assert positions == sorted(positions), f"staged log lines out of order; output={out!r}"
    diagnostic_markers = (
        "CTRL reload diagnostic: stage=switching-selector",
        "CTRL reload diagnostic: stage=old-leg-disposed",
        "CTRL reload diagnostic: stage=holds-released",
        "CTRL reload diagnostic: stage=committed elements=0",
    )
    diagnostic_positions = [captured.err.index(marker) for marker in diagnostic_markers]
    assert diagnostic_positions == sorted(diagnostic_positions), captured.err
    assert "CTRL reload committed" not in captured.err


# --- (4) asynchronous transaction ownership and failure settlement --------------


def test_selector_isolation_queue_uses_explicit_bounded_nonleaky_defaults(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _Queue:
        def set_property(self, key: str, value: object) -> None:
            recorder.calls.append(f"{key}={value}")

    queue = _Queue()
    engine._make = lambda _spec: queue  # type: ignore[method-assign]

    assert engine._make_selector_isolation_queue("isolation") is queue
    assert recorder.calls == [
        "max-size-buffers=200",
        "max-size-bytes=10485760",
        "max-size-time=1000000000",
        "leaky=0",
    ]


def test_finalizer_ignores_a_stale_transaction_identity(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    callbacks: list[tuple[bool, str | None]] = []
    stale = {
        "commit_in_progress": True,
        "retirement_result": (True, None),
        "on_settled": lambda committed, reason: callbacks.append((committed, reason)),
    }
    current = {"commit_in_progress": False}
    engine._pending_reload = current

    assert engine._finish_reload_commit(stale) is False
    assert engine._pending_reload is current
    assert callbacks == []
    assert recorder.calls == []


def test_reload_during_commit_is_rejected_before_any_graph_mutation(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    current = {"commit_in_progress": True}
    engine._pending_reload = current
    observed: list[tuple[bool, str | None]] = []
    build_calls: list[object] = []
    engine._instantiate_source_leg = lambda leg: build_calls.append(leg)  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="reload commit already in progress"):
        engine.reload_program(
            object(), on_settled=lambda committed, reason: observed.append((committed, reason))
        )

    assert engine._pending_reload is current
    assert build_calls == []
    assert observed == []
    assert recorder.calls == []


def test_success_callback_reentry_can_start_a_new_reload(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    current_results: list[tuple[bool, str | None]] = []

    def _current_settled(committed: bool, reason: str | None) -> None:
        current_results.append((committed, reason))
        engine._pending_reload = {"newer": True}

    pending = {
        "commit_in_progress": True,
        "retirement_result": (True, None),
        "boundary_probes": [],
        "hold_probes": [],
        "on_settled": _current_settled,
        "commit_completed": None,
        "commit_watchdog": None,
    }
    engine._pending_reload = pending
    assert engine._finish_reload_commit(pending) is False
    assert current_results == [(True, None)]
    assert engine._pending_reload == {"newer": True}


def test_disposal_state_failure_is_not_a_successful_cleanup(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _FailedElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.FAILURE

    ok, reason = engine._dispose_source_leg(
        _FakeOldPad("old-video", recorder, peer=None), None, [_FailedElement("bad", recorder)]
    )

    assert ok is False
    assert reason is not None and "element-null-incomplete:1:FAILURE" in reason
    assert "pipeline.remove:bad" in recorder.calls


def test_disposal_async_that_settles_to_null_is_a_successful_retirement(engine_module) -> None:
    """Round-2 finding 3: ASYNC on a downward transition is legitimate, not a failure.

    Source legs are bins, and a bin winding its children down answers ASYNC by
    GStreamer contract. Reporting that as "incomplete cleanup" is what made an
    ordinary retirement look fatal to the commit path. The bounded ``get_state``
    wait is the correct reading; only a leg that never reaches NULL fails."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _AsyncElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.ASYNC

    ok, reason = engine._dispose_source_leg(None, None, [_AsyncElement("async", recorder)])

    assert ok is True
    assert reason is None
    assert any(call.startswith("get_state:async:") for call in recorder.calls), recorder.calls


def test_disposal_async_that_never_settles_is_retried_once_then_reported(engine_module) -> None:
    """The bounded wait is bounded: a leg still not at NULL after a retry fails."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _WedgedElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.ASYNC

        def get_state(self, timeout: Any) -> tuple[str, str, str]:
            self.recorder.calls.append(f"get_state:{self.name}:{timeout}")
            return (_FakeStateChangeReturn.ASYNC, "PAUSED", _FakeState.NULL)

    ok, reason = engine._dispose_source_leg(None, None, [_WedgedElement("wedged", recorder)])

    assert ok is False
    assert reason is not None and "element-null-incomplete:1:async-unsettled:ASYNC" in reason
    # One retry, not an unbounded loop: two set_state attempts, two bounded waits.
    assert sum(call.startswith("set_state:wedged:") for call in recorder.calls) == 2
    assert sum(call.startswith("get_state:wedged:") for call in recorder.calls) == 2


def test_disposal_unlink_and_remove_problems_are_warnings_not_failures(engine_module) -> None:
    """Round-2 finding 3: by the time unlink/remove runs the leg is already at NULL
    and off air, so a hiccup there costs bookkeeping, not airtime. It must not be
    escalated into a retirement failure that takes a producing channel down."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _RefusingPipeline(_FakePipeline):
        def remove(self, element: Any) -> bool:
            super().remove(element)
            return False

    engine.pipeline = _RefusingPipeline(recorder)

    ok, reason = engine._dispose_source_leg(None, None, [_FakeOldElement("leg", recorder)])

    assert ok is True
    assert reason is None


def test_cleanup_failure_settles_false_but_keeps_a_producing_channel_on_air(
    engine_module,
) -> None:
    """Round-2 finding 3: an incomplete retirement is reported honestly on the
    receipt, but it no longer quits the loop. The replacement leg is already
    selected and feeding the mux; killing the channel over a leftover element took
    a PRODUCING channel off air. A retirement problem that genuinely stops output
    is the stall watchdog's to escalate, with far better evidence."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    results: list[tuple[bool, str | None]] = []

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    loop = _Loop()
    engine._loop = loop
    pending = {
        "commit_in_progress": True,
        "retirement_result": (False, "element-null-failed:2"),
        "boundary_probes": [],
        "hold_probes": [],
        "on_settled": lambda committed, reason: results.append((committed, reason)),
        "commit_completed": None,
        "commit_watchdog": None,
    }
    engine._pending_reload = pending

    assert engine._finish_reload_commit(pending) is False
    assert results == [(False, "cleanup-failed")]
    assert engine._pending_reload is None
    assert engine._stopping is False
    assert engine._error is None
    assert loop.quit_called is False


def test_new_active_leg_bus_error_during_retirement_is_fatal(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    source = object()
    engine._pending_reload = {
        "commit_in_progress": True,
        "new_elements": [source],
    }

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    class _Message:
        type = _FakeMessageType.ERROR
        src = source

        @staticmethod
        def parse_error() -> tuple[str, str]:
            return "active failure", "debug"

    engine._loop = _Loop()
    engine._abort_pending_reload = lambda _reason: pytest.fail(  # type: ignore[method-assign]
        "already-selected replacement must not be aborted as uncommitted"
    )

    assert engine._on_bus(None, _Message()) is True
    assert engine._error == ("active failure", "debug")
    assert engine._loop.quit_called is True


def test_retirement_thread_start_failure_aborts_before_selector_switch(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 0.1
    results: list[tuple[bool, str | None]] = []
    new_pad = _FakeOldPad("new-video", recorder, peer=None)
    engine._pending_reload = {
        "txn_id": 1,
        "new_leg_ready": True,
        "holds_awaited": 0,
        "switch_at_end_of_current": False,
        "old_leg_eos": True,
        "timeout_id": None,
        "defer_timeout_id": None,
        "probe_id": None,
        "new_video_pad": new_pad,
        "new_audio_pad": None,
        "new_elements": [],
        "hold_probes": [],
        "boundary_probes": [],
        "on_settled": lambda committed, reason: results.append((committed, reason)),
        "commit_in_progress": False,
    }

    class _NoStartThread:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(engine_module.threading, "Thread", _NoStartThread)

    assert engine._commit_reload() is False
    assert results == [(False, "commit-thread-start")]
    assert engine._pending_reload is None
    assert not any(call.startswith("video_sel.set_property") for call in recorder.calls)


def test_commit_watchdog_start_failure_cancels_retirement_and_aborts_before_switch(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 0.1
    results: list[tuple[bool, str | None]] = []
    new_pad = _FakeOldPad("new-video", recorder, peer=None)
    engine._pending_reload = {
        "txn_id": 1,
        "new_leg_ready": True,
        "holds_awaited": 0,
        "switch_at_end_of_current": False,
        "old_leg_eos": True,
        "timeout_id": None,
        "defer_timeout_id": None,
        "probe_id": None,
        "new_video_pad": new_pad,
        "new_audio_pad": None,
        "new_elements": [],
        "hold_probes": [],
        "boundary_probes": [],
        "on_settled": lambda committed, reason: results.append((committed, reason)),
        "commit_in_progress": False,
    }
    monkeypatch.setattr(
        engine,
        "_arm_commit_watchdog",
        lambda: (_ for _ in ()).throw(RuntimeError("timer unavailable")),
    )

    assert engine._commit_reload() is False
    assert results == [(False, "commit-watchdog-start")]
    assert engine._pending_reload is None
    assert engine._reload_commit_thread is None
    assert not any(call.startswith("video_sel.set_property") for call in recorder.calls)


def test_stop_settles_current_callback_once(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 0.1
    engine.audio_tap_writer = None
    current: list[tuple[bool, str | None]] = []

    class _StoppedThread:
        def join(self, timeout: float) -> None:
            assert 0 <= timeout <= 0.1

        @staticmethod
        def is_alive() -> bool:
            return False

    class _StopPipeline(_FakePipeline):
        def set_state(self, state: Any) -> str:
            assert state == _FakeState.NULL
            return _FakeStateChangeReturn.SUCCESS

        def get_state(self, _timeout: int) -> tuple[str, None, None]:
            return _FakeStateChangeReturn.SUCCESS, None, None

    engine.pipeline = _StopPipeline(recorder)
    engine._reload_commit_thread = _StoppedThread()
    engine._pending_reload = {
        "commit_in_progress": True,
        "retirement_result": (True, None),
        "boundary_probes": [],
        "hold_probes": [],
        "on_settled": lambda committed, reason: current.append((committed, reason)),
        "commit_completed": None,
        "commit_watchdog": None,
    }
    assert engine.stop(force_exit_on_hang=False) is True
    assert current == [(False, "stopped")]
    assert engine._pending_reload is None


def test_stop_bounds_a_pipeline_set_state_null_call_that_blocks(engine_module) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 0.02
    engine.audio_tap_writer = None
    entered = threading.Event()
    release = threading.Event()
    returned: list[bool] = []

    class _BlockingStopPipeline(_FakePipeline):
        def set_state(self, state: Any) -> str:
            assert state == _FakeState.NULL
            entered.set()
            release.wait(1.0)
            return _FakeStateChangeReturn.SUCCESS

        def get_state(self, _timeout: int) -> tuple[str, None, None]:
            return _FakeStateChangeReturn.SUCCESS, None, None

    engine.pipeline = _BlockingStopPipeline(recorder)
    caller = threading.Thread(
        target=lambda: returned.append(engine.stop(force_exit_on_hang=False)), daemon=True
    )
    caller.start()
    try:
        assert entered.wait(0.2)
        caller.join(0.2)
        assert not caller.is_alive(), "stop() exceeded its bound inside set_state(NULL)"
        assert returned == [False]
    finally:
        release.set()
        caller.join(0.2)


# --- (5) the commit watchdog THREAD escapes a commit that never returns ---------


def test_commit_watchdog_force_exits_when_the_commit_never_returns(
    engine_module, monkeypatch
) -> None:
    """Item 85's escape hatch: if ``_commit_reload`` (simulated here by simply
    never calling ``watchdog.cancel()``, i.e. a commit that hangs forever and
    never returns control) does not finish within ``commit_timeout_s``, the
    watchdog THREAD -- not a GLib timeout source, which could never fire if
    the SAME thread that would run it is the one wedged -- must fire on its
    own, independent OS thread: dump every live thread's Python stack FIRST
    (the actual diagnostic this item ships), print the diagnosis, and
    force-exit IMMEDIATELY with the distinct
    ``GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE`` -- with NO pipeline teardown
    attempt in between (a downward state transition takes the same
    STREAM_LOCK a wedged thread already holds; attempting it here would
    either do nothing or wedge this watchdog thread too). ``os._exit`` and
    ``faulthandler.dump_traceback`` are both monkeypatched (calling the real
    ``os._exit`` would kill the test process) -- both are recorded instead,
    proving they were reached, in the right order, without actually
    exiting."""
    from civiccast.egress.gst.exit_codes import GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE

    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 0.05
    # Must NOT be called: proves the watchdog attempts no pipeline teardown.
    engine.pipeline.set_state = lambda state: recorder.calls.append(  # type: ignore[attr-defined]
        f"pipeline.set_state:{state}"
    )
    dump_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        engine_module.faulthandler,
        "dump_traceback",
        lambda **kwargs: dump_calls.append(kwargs),
    )
    exit_calls: list[int] = []
    monkeypatch.setattr(engine_module.os, "_exit", exit_calls.append)

    watchdog, completed = engine._arm_commit_watchdog()
    # A commit that never returns never sets `completed` and never calls
    # watchdog.cancel() -- exactly the condition this thread exists to escape.
    # Join (bounded) rather than sleep: the thread fires as soon as its own
    # timer elapses, not on this test's clock.
    assert not completed.is_set()
    watchdog.join(timeout=5.0)

    assert not watchdog.is_alive(), "commit watchdog thread never fired"
    assert len(dump_calls) == 1
    assert dump_calls[0].get("all_threads") is True
    assert exit_calls == [int(GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE)]
    assert not any(call.startswith("pipeline.set_state:") for call in recorder.calls), (
        "watchdog must not attempt any pipeline teardown before force-exiting"
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
        "txn_id": 1,
        "new_leg_ready": True,
        "holds_awaited": 0,
        "switch_at_end_of_current": False,
        "old_leg_eos": True,
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
    dump_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        engine_module.faulthandler,
        "dump_traceback",
        lambda **kwargs: dump_calls.append(kwargs),
    )

    result = engine._commit_reload()
    retirement = engine._reload_commit_thread
    if retirement is not None:
        retirement.join(timeout=1.0)

    assert result is False
    assert retirement is None or not retirement.is_alive()
    assert engine._pending_reload is None
    assert exit_calls == [], "a commit that finished in time must never force-exit"
    assert dump_calls == [], "a commit that finished in time must never dump a stack trace"


def test_commit_watchdog_completion_flag_wins_a_cancel_race(engine_module, monkeypatch) -> None:
    """Hostile-review follow-up: ``Timer.cancel()`` alone cannot close the race
    where the watchdog thread has ALREADY started running
    ``_on_commit_wedged`` (past ``Timer.cancel()``'s own internal check) at the
    exact moment the commit finishes -- cancelling at that point is a no-op.
    Simulates that exact race directly: fire ``_on_commit_wedged`` (obtained
    via the real ``threading.Timer.function`` the production code built) AFTER
    ``completed`` is set but BEFORE/without ever calling ``cancel()`` at all --
    proving the function itself, not the ``Timer`` API, is what refuses to
    exit once the commit is known to have finished."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.commit_timeout_s = 5.0  # never actually waited for the timer to fire
    exit_calls: list[int] = []
    monkeypatch.setattr(engine_module.os, "_exit", exit_calls.append)
    dump_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        engine_module.faulthandler,
        "dump_traceback",
        lambda **kwargs: dump_calls.append(kwargs),
    )

    watchdog, completed = engine._arm_commit_watchdog()
    try:
        # Simulates the commit finishing and _commit_reload's finally block
        # setting `completed` BEFORE cancel() -- exactly the documented order.
        completed.set()
        watchdog.cancel()
        # Even if the timer thread had ALREADY passed cancel()'s own check
        # (the race this flag exists for), invoking the underlying function
        # directly -- exactly what that thread would do next -- must still be
        # a no-op now that `completed` is set.
        watchdog.function()
    finally:
        watchdog.join(timeout=5.0)  # bounded: never actually fires (5s interval)

    assert exit_calls == [], "a completed commit must never force-exit, even racing cancel()"
    assert dump_calls == [], (
        "a completed commit must never dump a stack trace, even racing cancel()"
    )


# --- (6) commit_timeout_s validation/clamping -----------------------------------


def test_resolve_commit_timeout_s_clamps_and_warns_on_an_out_of_range_value(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unlike an earlier draft's inline ``max(1.0, self.commit_timeout_s)``
    (a SILENT floor), an out-of-bounds ``commit_timeout_s`` is clamped WITH a
    stderr warning naming the value and the bound it was clamped to."""
    resolved = engine_module._resolve_commit_timeout_s(0.001)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert resolved == engine_module._MIN_COMMIT_TIMEOUT_S
    assert "0.001" in out
    assert "clamped" in out


def test_resolve_commit_timeout_s_accepts_an_in_range_value_silently(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = engine_module._resolve_commit_timeout_s(20.0)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert resolved == 20.0
    assert out == ""


def test_resolve_commit_timeout_s_falls_back_to_default_on_nan(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = engine_module._resolve_commit_timeout_s(float("nan"))
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert resolved == engine_module._DEFAULT_COMMIT_TIMEOUT_S
    assert "non-finite" in out


# --- (5) round-2 finding 1: the abort path's contract ---------------------------


def _abort_pending(recorder: _Recorder, pads: list[Any], elements: list[Any]) -> dict[str, Any]:
    return {
        "txn_id": 1,
        "probe_id": None,
        "timeout_id": None,
        "defer_timeout_id": None,
        "boundary_probes": [],
        "hold_probes": [(pad, f"{pad.name}-hold") for pad in pads],
        "new_src_pads": list(pads),
        "new_video_pad": None,
        "new_audio_pad": None,
        "new_elements": elements,
        "commit_in_progress": False,
        "on_settled": None,
    }


def test_abort_drops_the_leg_at_its_own_pads_before_lifting_the_hold(engine_module) -> None:
    """Round-2 finding 1: DETACH BEFORE RELEASE.

    Lifting a held leg's blocking probes frees its streaming threads. Until this
    fix those threads ran straight into the input-selector on a pad that was still
    INACTIVE -- a state ``_SELECTOR_PROPS`` explicitly documents the deferred
    switch as never producing ("pushes nothing at all while inactive"). The DROP
    probe must therefore be installed on the leg's own src pads FIRST, so the
    ordering is structural and not a race."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    pads = [_FakeHoldPad("new-video", recorder), _FakeHoldPad("new-audio", recorder)]
    pending = _abort_pending(recorder, pads, [_FakeOldElement("aborted", recorder)])
    engine._pending_reload = pending

    engine._abort_pending_reload("error")
    for thread in engine._abort_retire_threads:
        thread.join(timeout=5.0)

    drops = [i for i, call in enumerate(recorder.calls) if call.startswith("add_probe:")]
    releases = [i for i, call in enumerate(recorder.calls) if call.startswith("remove_probe:")]
    assert len(drops) == 2, recorder.calls
    assert len(releases) == 2, recorder.calls
    assert max(drops) < min(releases), recorder.calls
    # The probe installed is the drop-everything one, not some other callback.
    assert all("_drop_everything_probe" in recorder.calls[i] for i in drops), recorder.calls
    assert engine._pending_reload is None


def test_abort_retires_the_leg_off_the_main_loop(engine_module) -> None:
    """Round-2 finding 1: ``set_state(NULL)`` blocks until the leg's streaming
    threads join. ``_abort_pending_reload`` runs ON the GLib main loop, so an
    errored leg that will not go down would take the loop -- and with it both
    watchdogs and the control-plane reader -- off a channel that is still on air.
    Retirement therefore happens on a worker thread, and its result is reported
    rather than discarded."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    main_thread = threading.current_thread()
    disposing_threads: list[Any] = []

    class _ThreadRecordingElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            disposing_threads.append(threading.current_thread())
            return super().set_state(state)

    pending = _abort_pending(
        recorder,
        [_FakeHoldPad("new-video", recorder)],
        [_ThreadRecordingElement("aborted", recorder)],
    )
    engine._pending_reload = pending

    engine._abort_pending_reload("error")
    assert len(engine._abort_retire_threads) == 1
    for thread in engine._abort_retire_threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "abort retirement thread did not finish"

    assert disposing_threads, "the leg was never disposed"
    assert all(thread is not main_thread for thread in disposing_threads), (
        "abort disposal ran on the main loop"
    )


def test_abort_settles_the_caller_without_waiting_for_retirement(engine_module) -> None:
    """The honest ack (item 4) reports the reload's OUTCOME, which is already
    decided; it is not held behind cleanup."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    results: list[tuple[bool, str | None]] = []
    pending = _abort_pending(
        recorder, [_FakeHoldPad("new-video", recorder)], [_FakeOldElement("aborted", recorder)]
    )
    pending["on_settled"] = lambda committed, reason: results.append((committed, reason))
    engine._pending_reload = pending

    engine._abort_pending_reload("timeout")
    for thread in engine._abort_retire_threads:
        thread.join(timeout=5.0)

    assert results == [(False, "timeout")]
