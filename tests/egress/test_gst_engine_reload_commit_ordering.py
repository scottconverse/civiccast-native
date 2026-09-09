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
import time
import types
from typing import Any

import pytest

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

    def set_locked_state(self, locked: bool) -> bool:
        self.recorder.calls.append(f"set_locked_state:{self.name}:{locked}")
        return True

    def set_state(self, state: Any) -> str:
        self.recorder.calls.append(f"set_state:{self.name}:{state}")
        return _FakeStateChangeReturn.SUCCESS

    def get_state(self, timeout: Any) -> tuple[str, str, str]:
        """A bin that answered ASYNC settles to NULL within the bounded wait."""
        self.recorder.calls.append(f"get_state:{self.name}:{timeout}")
        return (_FakeStateChangeReturn.SUCCESS, _FakeState.NULL, _FakeState.NULL)


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.State = _FakeState  # type: ignore[attr-defined]
    fake_gst.StateChangeReturn = _FakeStateChangeReturn  # type: ignore[attr-defined]
    fake_gst.MessageType = _FakeMessageType  # type: ignore[attr-defined]
    fake_gst.IteratorResult = _FakeIteratorResult  # type: ignore[attr-defined]
    fake_gst.SECOND = 1  # type: ignore[attr-defined]
    fake_gst.PadProbeType = _FakePadProbeType  # type: ignore[attr-defined]
    fake_gst.PadProbeReturn = _FakePadProbeReturn  # type: ignore[attr-defined]
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
    engine._commit_retire_threads = []
    engine._reload_commit_thread = None
    engine._stopping = False
    engine._error = None
    engine._loop = None
    engine._pending_overlay_swaps = {}
    engine._selector_pads_quiet = threading.Condition()
    engine._selector_pad_retirements = 0
    engine._retiring_legs = []
    engine._orphaned_leg_elements = []
    engine.stall_timeout_s = 10.0
    engine.commit_timeout_s = 15.0
    engine._stall_last_advance_t = 0.0
    return engine


def _complete_commit_for_test(engine: Any, pending: dict[str, Any]) -> bool:
    """Run the production commit phases serially, in their exact production order.

    Round-3 finding 1: the on-air half (selector switch, then hold release and the
    committed marker) runs FIRST and synchronously; old-leg retirement runs after
    it, and here inline instead of on its worker thread so the recorder's call
    order is deterministic.
    """
    pending.setdefault("commit_in_progress", True)
    pending.setdefault("commit_watchdog", None)
    pending.setdefault("commit_completed", None)
    engine._pending_reload = pending
    engine._begin_reload_commit(pending)
    result = engine._finish_reload_commit(pending)
    engine._dispose_source_leg(
        pending["old_video_pad"], pending["old_audio_pad"], pending["old_elements"]
    )
    return result


def _index_of(calls: list[str], prefix: str) -> int:
    for i, call in enumerate(calls):
        if call.startswith(prefix):
            return i
    raise AssertionError(f"{prefix!r} never called; calls={calls}")


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


def test_commit_releases_the_replacement_before_retiring_the_old_leg(engine_module) -> None:
    """Round-3 finding 1: the successor goes live BEFORE the old leg is retired.

    Round 2 switched the selector, retired the old leg, and only then lifted the
    replacement's hold probes -- so the mux was fed by nothing at all for the whole
    length of a teardown. Under a box pinned at 100% CPU that teardown outran the
    15s commit watchdog in 4 of 24 measured runs and force-exited a worker that had
    a perfectly good replacement standing by. The hold release must therefore land
    between the selector switch and the first ``set_state(NULL)`` of the outgoing
    leg, so that every millisecond of retirement is spent with output already
    flowing."""
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

    assert switch_video < remove_video < old_null < release_video, calls
    assert switch_audio < remove_audio < old_null < release_audio, calls


def test_commit_settles_the_caller_before_retirement_starts(engine_module) -> None:
    """Round-3 finding 1: the honest ack reports a reload that is ON AIR.

    The receipt no longer waits on -- and can no longer be failed by -- a teardown
    of the leg that has already been replaced."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    order: list[str] = []

    class _OrderingElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            order.append("retire")
            return super().set_state(state)

    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": None,
        "rebase_new_leg": False,
        "hold_probes": [],
        "boundary_probes": [],
        "old_video_pad": None,
        "old_audio_pad": None,
        "old_elements": [_OrderingElement("old-elem", recorder)],
        "new_elements": [],
        "on_settled": lambda committed, reason: order.append(f"settled:{committed}:{reason}"),
    }

    _complete_commit_for_test(engine, pending)

    assert order == ["settled:True:None", "retire"], order


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


def test_dispose_source_leg_never_sends_flush_events(engine_module) -> None:
    """Round 1 also added ``FLUSH_START``/``FLUSH_STOP`` events on the
    retiring leg's selector pad, bracketing the unlink. REVERTED along with
    the reorder: ``FLUSH_START`` sent directly to the selector's OWN sink pad
    does not reach (and cannot unblock) a thread blocked further upstream in
    the leg's own elements, and ``flush_stop(True)`` immediately after
    re-opens the exact race window the flush was meant to close. This test
    proves ``_FakeOldPad.send_event`` -- which would fail loudly via its own
    ``pragma: no cover`` marker if ever actually invoked as part of the normal
    call recording -- is never called at all during a normal dispose."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    old_video_pad = _FakeOldPad("old-video", recorder, peer=_FakePeer("old-video-peer", recorder))
    old_audio_pad = _FakeOldPad("old-audio", recorder, peer=_FakePeer("old-audio-peer", recorder))

    engine._dispose_source_leg(old_video_pad, old_audio_pad, [_FakeOldElement("elem", recorder)])

    assert not any(call.startswith("send_event:") for call in recorder.calls), (
        f"a FLUSH event was sent; calls={recorder.calls}"
    )


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
    # The retirement line is printed by the retirement worker; drive it here so
    # this test sees the complete, ordered sequence a real commit emits.
    engine._start_old_leg_retirement(pending)
    engine._reload_commit_thread.join(timeout=5.0)
    captured = capsys.readouterr()
    out = captured.out

    # Round-3 finding 1: "old leg disposed" moved to LAST, and carries the
    # element count, because retirement now runs behind an already-committed
    # replacement instead of in front of it.
    markers = (
        "CTRL reload: switching selector",
        "CTRL reload: holds released",
        "CTRL reload committed",
        "CTRL reload: old leg disposed (elements=0)",
    )
    positions = [out.index(marker) for marker in markers]
    assert positions == sorted(positions), f"staged log lines out of order; output={out!r}"
    diagnostic_markers = (
        "CTRL reload diagnostic: stage=switching-selector",
        "CTRL reload diagnostic: stage=holds-released",
        "CTRL reload diagnostic: stage=committed",
        "CTRL reload diagnostic: stage=old-leg-disposed elements=0",
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


def test_disposal_state_failure_is_an_orphan_that_is_never_removed(engine_module) -> None:
    """Round-3 finding 5: an element that will not reach NULL is not removed.

    Round 2 ran unlink/release/remove unconditionally after a NULL failure, so a
    possibly-still-running element was detached from the pipeline with nothing
    watching it. ``Gst.Bin.remove`` is only valid for an element at NULL. The
    element now stays in the pipeline, is counted as an orphan, and is named in an
    ERROR line an operator can act on."""
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
    assert "pipeline.remove:bad" not in recorder.calls, recorder.calls
    assert len(engine._orphaned_leg_elements) == 1
    # The selector pad is still released: that is bookkeeping on the SELECTOR, not
    # a state change on the orphan, and leaking a request pad forever is its own
    # unbounded leak.
    assert "video_sel.release_request_pad:old-video" in recorder.calls


def test_orphan_report_names_the_element_and_counts_it(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round-3 finding 5: 'one element did not reach NULL' is not actionable."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _FailedElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.FAILURE

    engine._dispose_source_leg(None, None, [_FailedElement("vdec_program_7", recorder)])
    err = capsys.readouterr().err

    assert "left 1 element(s) above NULL" in err, err
    assert "vdec_program_7" in err, err
    assert "NOT removed" in err, err


def test_leg_disposal_is_bounded_by_one_deadline_for_the_whole_leg(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-3 finding 3: ``_LEG_NULL_ASYNC_WAIT_S`` is a PER-ELEMENT cap, and it
    was being spent per element (twice, with the retry). A real program leg is 77
    elements, so the arithmetic worst case was 77 x 2 x 2.0s = ~308s. Every
    element of one leg now draws down a single ``_LEG_DISPOSAL_BUDGET_S``
    deadline, so the waits an element is granted shrink to zero as the leg's
    budget is consumed."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    waits: list[int] = []
    clock = {"t": 0.0}

    class _SlowAsyncElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.ASYNC

        def get_state(self, timeout: Any) -> tuple[str, str, str]:
            waits.append(timeout)
            # Every wait actually burns its whole budget, the pathological case.
            clock["t"] += timeout / 1_000_000_000
            return (_FakeStateChangeReturn.ASYNC, "PAUSED", _FakeState.NULL)

    elements = [_SlowAsyncElement(f"elem-{i}", recorder) for i in range(77)]
    # A virtual clock: every granted wait is spent in full, which is the
    # pathological leg this bound exists for.
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])
    ok, _reason = engine._dispose_source_leg(None, None, elements)

    assert ok is False
    total_wait_s = sum(waits) / 1_000_000_000
    budget = engine_module._LEG_DISPOSAL_BUDGET_S + engine_module._LEG_ORPHAN_RETRY_BUDGET_S
    assert total_wait_s <= budget + 0.001, (
        f"leg disposal waited {total_wait_s}s across 77 elements; the whole-leg "
        f"budget is {budget}s (round-2 behaviour would have waited ~308s)"
    )
    # And the orphans are all recorded, not silently dropped.
    assert len(engine._orphaned_leg_elements) == 77


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


def test_disposal_async_that_never_settles_is_bounded_then_reported(engine_module) -> None:
    """The bounded wait is bounded: one attempt, one retry, one orphan sweep, then
    the element is reported as an orphan rather than waited on forever."""
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
    # Bounded, not an unbounded loop: two attempts in the NULL pass plus one final
    # orphan sweep, each with its own bounded wait.
    assert sum(call.startswith("set_state:wedged:") for call in recorder.calls) == 3
    assert sum(call.startswith("get_state:wedged:") for call in recorder.calls) == 3
    assert len(engine._orphaned_leg_elements) == 1


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


def test_retirement_failure_keeps_the_channel_on_air_and_the_stall_bound_intact(
    engine_module,
) -> None:
    """Round-3 findings 1, 2 and 6: what actually protects the channel here.

    A retirement that cannot finish is reported, never fatal -- the replacement it
    was retiring BEHIND is already selected and feeding the mux, so killing the
    worker over a leftover element would take a producing channel off air. Round 2
    asserted only the "does not quit" half and dropped the compensating control,
    which is the half that matters: if the incomplete retirement really does stop
    output, something must still take the channel down. That something is the
    stall watchdog, on its OWN ``stall_timeout_s`` budget -- reset at the commit so
    the fresh leg gets a full one, and (finding 2) never suspended, so the dead air
    a viewer can see is bounded by ``stall_timeout_s``, not by the longer
    ``commit_timeout_s``."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    results: list[tuple[bool, str | None]] = []

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    class _FailedElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            super().set_state(state)
            return _FakeStateChangeReturn.FAILURE

    loop = _Loop()
    engine._loop = loop
    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": None,
        "rebase_new_leg": False,
        "commit_in_progress": True,
        "commit_completed": None,
        "commit_watchdog": None,
        "boundary_probes": [],
        "hold_probes": [],
        "old_video_pad": None,
        "old_audio_pad": None,
        "old_elements": [_FailedElement("stuck", recorder)],
        "new_elements": [],
        "on_settled": lambda committed, reason: results.append((committed, reason)),
    }
    engine._pending_reload = pending

    engine._finish_reload_commit(pending)
    stall_reference_at_commit = engine._stall_last_advance_t
    engine._start_old_leg_retirement(pending)
    engine._reload_commit_thread.join(timeout=5.0)

    # The reload LANDED -- the replacement is on air -- and the failed retirement
    # neither reversed that nor quit the loop.
    assert results == [(True, None)]
    assert engine._pending_reload is None
    assert loop.quit_called is False
    assert engine._error is None
    assert len(engine._orphaned_leg_elements) == 1
    # The commit reset the stall reference, so the new leg is measured from here.
    assert stall_reference_at_commit > 0.0

    # Compensating control: a channel that is NOT producing is killed within
    # stall_timeout_s -- no commit suspension, no stretch to commit_timeout_s.
    engine._output_buffers = 5
    engine._output_buffers_at_arm = 0
    engine._stall_last_count = 5
    engine._first_output_seen = True
    engine.first_output_timeout_s = 45.0
    engine._last_output_progress_print_t = time.monotonic()

    engine._stall_last_advance_t = time.monotonic() - (engine.stall_timeout_s - 0.5)
    assert engine._check_stall() is True, "killed BEFORE the stall bound elapsed"
    assert loop.quit_called is False

    engine._stall_last_advance_t = time.monotonic() - engine.stall_timeout_s
    assert engine._check_stall() is False, (
        "a non-producing channel survived past stall_timeout_s -- the watchdog "
        "stood down for the commit again"
    )
    assert loop.quit_called is True
    assert engine._error == ("stall", "output stalled")


def test_stall_watchdog_does_not_stand_down_for_a_commit(engine_module) -> None:
    """Round-3 finding 2: the round-2 suspension is gone.

    Suspending this check while ``commit_in_progress`` was set stretched worst-case
    dead air from ``stall_timeout_s`` (10s) to ``commit_timeout_s`` (15s) on every
    wedge. With finding 1's ordering there is nothing to suspend for: the only part
    of a commit that can darken output runs synchronously on this same GLib main
    loop, so this timeout source cannot even be entered while it executes."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    engine._loop = _Loop()
    engine._pending_reload = {"commit_in_progress": True}
    engine._output_buffers = 5
    engine._output_buffers_at_arm = 0
    engine._stall_last_count = 5
    engine._first_output_seen = True
    engine.first_output_timeout_s = 45.0
    engine._last_output_progress_print_t = time.monotonic()
    engine._stall_last_advance_t = time.monotonic() - engine.stall_timeout_s

    assert engine._check_stall() is False
    assert engine._loop.quit_called is True
    assert engine._error == ("stall", "output stalled")


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


def test_retirement_thread_start_failure_retires_inline_after_the_commit(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-3 finding 1: the retirement thread starts AFTER the replacement is on
    air, so a thread that will not start can no longer cancel a commit. The leg
    must still not leak: retirement falls back to running inline, which delays the
    loop but cannot darken output, because output is already flowing."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    old_element = _FakeOldElement("old-elem", recorder)
    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": None,
        "rebase_new_leg": False,
        "commit_in_progress": True,
        "commit_completed": None,
        "commit_watchdog": None,
        "boundary_probes": [],
        "hold_probes": [],
        "old_video_pad": None,
        "old_audio_pad": None,
        "old_elements": [old_element],
        "new_elements": [],
        "on_settled": None,
    }
    engine._pending_reload = pending
    engine._finish_reload_commit(pending)

    class _NoStartThread:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(engine_module.threading, "Thread", _NoStartThread)
    engine._start_old_leg_retirement(pending)

    assert engine._reload_commit_thread is None
    assert "set_state:old-elem:NULL" in recorder.calls, recorder.calls


def test_commit_watchdog_start_failure_cancels_retirement_and_aborts_before_switch(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 0.1
    results: list[tuple[bool, str | None]] = []
    new_pad = _FakeOldPad("new-video", recorder, peer=None)
    engine._pending_reload = {
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
    engine._commit_retire_threads = [engine._reload_commit_thread]
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


# --- (7) round-3 finding 4: selector request pads are serialised ----------------


def test_reload_waits_for_a_retiring_leg_to_release_its_selector_pads(engine_module) -> None:
    """Round-3 finding 4: ``request_pad_simple`` must not overlap
    ``release_request_pad`` on the same ``input-selector``.

    ``_abort_pending_reload("superseded")`` returns as soon as its retirement
    THREAD has started, so round 2's very next statements requested selector pads
    while that thread was still releasing them. The gate makes the successor wait
    for the release, bounded."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    released = threading.Event()
    disposing = threading.Event()

    class _SlowElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            disposing.set()
            released.wait(2.0)
            return super().set_state(state)

    retire = threading.Thread(
        target=lambda: engine._dispose_source_leg(None, None, [_SlowElement("old", recorder)]),
        daemon=True,
    )
    retire.start()
    assert disposing.wait(2.0), "retirement never started"

    waited: list[str] = []

    def _await() -> None:
        engine._await_selector_pads_quiet()
        waited.append("returned")

    waiter = threading.Thread(target=_await, daemon=True)
    waiter.start()
    waiter.join(0.2)
    assert waited == [], "a pad request was admitted while a retirement held the selector"

    released.set()
    waiter.join(2.0)
    retire.join(2.0)
    assert waited == ["returned"]


def test_reload_refuses_rather_than_racing_a_wedged_selector_release(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bounded, and the bound is a refusal -- not a shrug that races anyway.

    ``reload_program`` raises before it instantiates or links anything, so the
    contract that a pre-build failure has committed no state still holds. The
    worker reports the error and the daemon restarts from the newest graph."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    monkeypatch.setattr(engine_module, "_SELECTOR_PAD_QUIESCE_TIMEOUT_S", 0.05)
    engine.selector_sink_pads = [object()]
    engine.audio_sink_pads = []
    build_calls: list[object] = []
    engine._instantiate_source_leg = lambda leg: build_calls.append(leg)  # type: ignore[method-assign]
    with engine._selector_pads_quiet:
        engine._selector_pad_retirements = 1

    with pytest.raises(RuntimeError, match="still holds this pipeline's input-selector"):
        engine.reload_program(object())

    assert build_calls == []
    assert not any(call.startswith("video_sel.") for call in recorder.calls), recorder.calls


def test_retirement_is_announced_before_its_thread_runs(engine_module) -> None:
    """Round-3 finding 4, the gap a first round-3 cut left open.

    The selector-pad gate and the bus-error containment both read state that the
    first cut only wrote from INSIDE ``_dispose_source_leg`` -- i.e. once the
    worker thread had been scheduled and reached that call. ``thread.start()``
    returns as soon as the OS thread exists, so on a loaded box the main loop can
    run the next ``reload_program`` (and its ``request_pad_simple``) with the count
    still at zero. The starter must announce on the CALLING thread: by the time
    ``_start_old_leg_retirement`` returns the count is already 1 and the leg is
    already listed, regardless of whether the worker has run a single statement."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    started = threading.Event()
    release = threading.Event()

    class _GatedElement(_FakeOldElement):
        def set_state(self, state: Any) -> str:
            started.set()
            release.wait(2.0)
            return super().set_state(state)

    old_elements = [_GatedElement("old", recorder)]
    pending: dict[str, Any] = {
        "boundary_probes": [],
        "old_video_pad": None,
        "old_audio_pad": None,
        "old_elements": old_elements,
    }

    class _LazyThread(threading.Thread):
        """A thread whose body does not run until the test says so -- models the
        scheduler not getting to it before the main loop's next statement."""

        def start(self) -> None:  # pragma: no cover - trivial
            pass

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine_module.threading, "Thread", _LazyThread)
        engine._start_old_leg_retirement(pending)

    # The worker has not executed at all, yet the retirement is fully visible.
    assert engine._selector_pad_retirements == 1
    assert engine._belongs_to_retiring_leg(old_elements[0]) is True
    assert not started.is_set()

    # Now let it run to completion: it concludes exactly once, and the gate opens.
    release.set()
    engine._reload_commit_thread.run()
    assert engine._selector_pad_retirements == 0
    assert engine._belongs_to_retiring_leg(old_elements[0]) is False
    engine._await_selector_pads_quiet()  # returns immediately, nothing held


def test_abort_retirement_is_announced_before_its_thread_runs(engine_module) -> None:
    """Same guarantee on the abort path -- ``_abort_pending_reload("superseded")``
    is the exact call the finding named."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    elements = [_FakeOldElement("aborted", recorder)]

    class _LazyThread(threading.Thread):
        def start(self) -> None:  # pragma: no cover - trivial
            pass

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine_module.threading, "Thread", _LazyThread)
        engine._start_aborted_leg_retirement("superseded", None, None, elements)

    assert engine._selector_pad_retirements == 1
    assert engine._belongs_to_retiring_leg(elements[0]) is True
    engine._abort_retire_threads[0].run()
    assert engine._selector_pad_retirements == 0
    assert engine._retiring_legs == []


def test_stop_joins_every_in_flight_commit_retirement_not_only_the_newest(
    engine_module,
) -> None:
    """Round-3 finding 1 made retirement asynchronous, so under a fast rollover
    cadence two old legs can be retiring at once (each bounded at 8s + 4s). A
    ``stop()`` that joined only ``_reload_commit_thread`` would start the
    whole-pipeline NULL transition on top of the OLDER one -- the exact lock race
    the ``_RETIREMENT_STOP_JOIN_S`` join exists to prevent."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    engine.teardown_timeout_s = 1.0
    engine.audio_tap_writer = None
    release = threading.Event()
    joined: list[str] = []

    class _RetiringThread:
        def __init__(self, name: str) -> None:
            self.name = name
            self._alive = True

        def join(self, timeout: float) -> None:
            joined.append(self.name)
            release.wait(timeout)
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    class _StopPipeline(_FakePipeline):
        def set_state(self, state: Any) -> str:
            assert state == _FakeState.NULL
            # Both retirements must have been joined before the pipeline goes down.
            assert set(joined) == {"older", "newer"}, joined
            return _FakeStateChangeReturn.SUCCESS

        def get_state(self, _timeout: int) -> tuple[str, None, None]:
            return _FakeStateChangeReturn.SUCCESS, None, None

    engine.pipeline = _StopPipeline(recorder)
    older, newer = _RetiringThread("older"), _RetiringThread("newer")
    engine._commit_retire_threads = [older, newer]
    engine._reload_commit_thread = newer
    release.set()

    assert engine.stop(force_exit_on_hang=False) is True
    assert set(joined) == {"older", "newer"}, joined


def test_every_retiring_element_is_state_locked_before_it_is_nulled(engine_module) -> None:
    """Round 3, measured on the live runtime: a bin re-applies its state to every
    UNLOCKED child when a state change of its own completes -- and a live pipeline
    completes one whenever a concurrently-added chain (the graphics-overlay swap)
    finishes an ASYNC preroll. That cascade set the first two already-NULLed
    elements of a retiring program leg back to PLAYING between iterations of the
    retirement loop, and the loop then removed them in that state: a worker crash
    at stop (``rc=0xC0000005``) behind a GStreamer "dispose element ... in PLAYING"
    critical, in 2 of 3 ``-k reload`` batch runs. ``set_locked_state(True)`` before
    the NULL is what keeps a NULLed element NULL until it is removed."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    elements = [_FakeOldElement(f"elem-{i}", recorder) for i in range(3)]

    ok, _reason = engine._dispose_source_leg(None, None, elements)

    assert ok is True
    for element in elements:
        lock = _index_of(recorder.calls, f"set_locked_state:{element.name}:True")
        null = _index_of(recorder.calls, f"set_state:{element.name}:NULL")
        remove = _index_of(recorder.calls, f"pipeline.remove:{element.name}")
        assert lock < null < remove, recorder.calls


# --- (8) round-3 finding 1: a retiring leg's bus errors are contained -----------


def test_bus_error_from_a_retiring_leg_does_not_quit_the_channel(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round-3 finding 1: retirement now runs BEHIND an already-on-air
    replacement, so a leg being torn down on purpose can post errors (a decoder
    complaining as its pad goes away, a source reporting a read it will never
    finish) while the channel is perfectly healthy. Escalating those to the fatal
    path would take a producing channel off air over the corpse of the leg it just
    replaced -- the same failure this round exists to close, arriving by the bus
    instead of by the watchdog."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    retiring = _FakeOldElement("dying-decoder", recorder)

    class _Message:
        type = _FakeMessageType.ERROR
        src = retiring

        @staticmethod
        def parse_error() -> tuple[str, str]:
            return "internal data stream error", "debug"

    engine._loop = _Loop()
    engine._retiring_legs = [[retiring]]

    assert engine._on_bus(None, _Message()) is True
    assert engine._loop.quit_called is False
    assert engine._error is None
    err = capsys.readouterr().err
    assert "retiring reload leg errored during teardown" in err, err
    assert "dying-decoder" in err, err


def test_bus_error_is_still_fatal_once_the_leg_is_no_longer_retiring(engine_module) -> None:
    """The containment above is scoped to legs whose retirement is in flight. An
    error from the LIVE graph must still end the run so supervisor recovery is
    truthful."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)

    class _Loop:
        quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    live = _FakeOldElement("live-decoder", recorder)

    class _Message:
        type = _FakeMessageType.ERROR
        src = live

        @staticmethod
        def parse_error() -> tuple[str, str]:
            return "internal data stream error", "debug"

    engine._loop = _Loop()
    engine._retiring_legs = []

    assert engine._on_bus(None, _Message()) is True
    assert engine._loop.quit_called is True
    assert engine._error == ("internal data stream error", "debug")


# --- (9) round-3: the outgoing EOS-drop probes outlive the commit ---------------


def test_boundary_probes_survive_the_commit_and_are_dropped_after_retirement(
    engine_module,
) -> None:
    """Measured round-3 regression, not a hypothesis.

    A first cut of the finding-1 reordering removed the outgoing pads' EOS-drop
    probes in the on-air half, one statement before the hold release. Three-worker
    rollovers then failed with unclean worker teardowns and GStreamer
    "trying to dispose element ... instead of the NULL state" criticals: the
    retiring leg's audio EOS -- which lands a beat after video, while the leg is
    still being unlinked and NULLed -- reached the mux and ended the run. That is
    exactly the window ``_on_outgoing_pad_data``'s docstring says the probe exists
    to cover. The probes must therefore survive the commit and come off only once
    the leg they guard is actually disposed."""
    recorder = _Recorder()
    engine = _bare_engine_for_commit(engine_module, recorder)
    boundary_pad = _FakeHoldPad("outgoing-video", recorder)
    old_element = _FakeOldElement("old-elem", recorder)
    pending: dict[str, Any] = {
        "timeout_id": None,
        "defer_timeout_id": None,
        "new_video_pad": object(),
        "new_audio_pad": None,
        "rebase_new_leg": False,
        "commit_in_progress": True,
        "commit_completed": None,
        "commit_watchdog": None,
        "boundary_probes": [(boundary_pad, "boundary-1")],
        "hold_probes": [],
        "old_video_pad": None,
        "old_audio_pad": None,
        "old_elements": [old_element],
        "new_elements": [],
        "on_settled": None,
    }
    engine._pending_reload = pending

    engine._begin_reload_commit(pending)
    engine._finish_reload_commit(pending)

    assert not any(call.startswith("remove_probe:outgoing-video") for call in recorder.calls), (
        f"the outgoing EOS-drop probe was removed before retirement; calls={recorder.calls}"
    )

    engine._start_old_leg_retirement(pending)
    engine._reload_commit_thread.join(timeout=5.0)

    calls = recorder.calls
    null_index = _index_of(calls, "set_state:old-elem:NULL")
    drop_index = _index_of(calls, "remove_probe:outgoing-video")
    assert null_index < drop_index, (
        f"the EOS-drop probe came off before the leg reached NULL; calls={calls}"
    )
