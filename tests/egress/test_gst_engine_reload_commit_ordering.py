# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 85: gi-free tests for ``GstPlayoutEngine._commit_reload`` /
``_dispose_source_leg`` / the reload-commit watchdog thread.

Status (sandbox runs 12/14/15, hostile-review round 1): seven soaked workers
wedged permanently at reload commit -- ``CTRL reload committed`` never
appeared, the last line each ever printed was ``CTRL reload: boundary switch
rebased...``. Round 1 shipped a REORDERING of ``_commit_reload``/
``_dispose_source_leg`` as a hypothesized root-cause fix; hostile review
rejected that hypothesis (releasing a hold before the selector switch
deterministically DROPS the new leg's first buffer at the default
non-caching input-selector sink pad; unlinking/releasing a retiring leg's
selector pad before NULLing its own elements races that leg's still-live
streaming thread into ``GST_FLOW_NOT_LINKED``, a fatal error, not a benign
no-op) and reverted the reorder. The ordering these tests assert is
therefore main's ORIGINAL ordering, unchanged by this item -- these tests
exist to prove that reversion actually landed and stays landed, and to
cover the two things this item DOES add: the four staged diagnostic log
lines, and the commit-watchdog thread (the actual localization tool for
whichever future soak reproduces the wedge).

These tests load ``civiccast.egress.gst.engine`` fresh against a small FAKE
``gi``/``Gst`` (same technique as
``test_gst_engine_reload_concat_naming.py``) so the ordering can be proven
without a real GStreamer/gi install, a real pipeline, or a main loop -- only
``GstPlayoutEngine._commit_reload_body``/``_dispose_source_leg`` are
exercised, against pad/selector/element doubles that record every call into
one shared, ordered list."""

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
    ``_dispose_source_leg`` unlinks and releases. NOT expected to see any
    ``send_event`` call in the current (reverted-to-main) design -- see
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

    def set_state(self, state: Any) -> None:
        self.recorder.calls.append(f"set_state:{self.name}:{state}")


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
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
    return engine


def _index_of(calls: list[str], prefix: str) -> int:
    for i, call in enumerate(calls):
        if call.startswith(prefix):
            return i
    raise AssertionError(f"{prefix!r} never called; calls={calls}")


# --- (1) commit ordering, reverted to main: switch THEN release; NULL THEN unlink ---


def test_commit_switches_active_pad_before_releasing_hold_probes(engine_module) -> None:
    """Main's ordering (unchanged by this item -- round 1's reorder here was
    REVERTED, see module docstring): the selector's ``active-pad`` switch
    happens BEFORE the new leg's hold probes are released, not after. Releasing
    first would let the leg's streaming thread push its already-decoded first
    buffer into a sink pad the selector does not yet consider active, and the
    default (``cache-buffers=False``) input-selector drops a buffer that
    arrives on an inactive pad -- deterministically losing that buffer (and,
    with it, the running-time-rebase SEGMENT it carries) on every reload, not
    just a wedged one."""
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

    switch_video = _index_of(calls, "video_sel.set_property:active-pad")
    switch_audio = _index_of(calls, "audio_sel.set_property:active-pad")
    remove_video = _index_of(calls, "remove_probe:hold-video")
    remove_audio = _index_of(calls, "remove_probe:hold-audio")

    assert switch_video < remove_video, (
        f"active-pad switch happened AFTER releasing the video hold; calls={calls}"
    )
    assert switch_audio < remove_audio, (
        f"active-pad switch happened AFTER releasing the audio hold; calls={calls}"
    )


def test_commit_disposes_old_leg_by_nulling_before_unlinking(engine_module) -> None:
    """Main's ordering (unchanged by this item): the retiring leg's elements
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

    engine._commit_reload_body(pending)
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

    # Must not raise.
    engine._dispose_source_leg(None, None, [_RaisingElement()])


# --- (2) the four staged diagnostic log lines fire, in order --------------------


def test_commit_prints_the_four_staged_log_lines_in_order(
    engine_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 85's instrumentation: four staged stderr/stdout prints -- "CTRL
    reload: switching selector" / "holds released" / "old leg disposed" /
    "committed (elements=N)" -- so the NEXT soak that reproduces the wedge
    shows exactly which of these four steps it stalled inside."""
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

    engine._commit_reload_body(pending)
    out = capsys.readouterr().out

    markers = (
        "CTRL reload: switching selector",
        "CTRL reload: holds released",
        "CTRL reload: old leg disposed",
        "CTRL reload committed",
    )
    positions = [out.index(marker) for marker in markers]
    assert positions == sorted(positions), f"staged log lines out of order; output={out!r}"


# --- (3) the commit watchdog THREAD escapes a commit that never returns ---------


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

    watchdog = engine._arm_commit_watchdog()
    # A commit that never returns never calls watchdog.cancel() -- exactly the
    # condition this thread exists to escape. Join (bounded) rather than sleep:
    # the thread fires as soon as its own timer elapses, not on this test's clock.
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

    assert result is False
    assert exit_calls == [], "a commit that finished in time must never force-exit"
    assert dump_calls == [], "a commit that finished in time must never dump a stack trace"


# --- (4) commit_timeout_s validation/clamping -----------------------------------


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
