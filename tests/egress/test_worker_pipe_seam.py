# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the D2 worker-pipe seam (spec-supervisor D2, design.md sec4).

Two things are proved here, both without a real named pipe and without ``gi``:

1. The STRATEGY-side envelope + per-verb replay policy
   (``civiccast.egress.gst.strategy.WorkerPipeSession``), against a FAKE in-memory
   duplex transport and a small in-test "simulated worker" that mirrors the real
   worker's dedup contract using ``civiccast.native.supervisor.replay.AppliedIdCache``
   (the same LRU semantics ``worker.py``'s own local copy replicates -- see the
   module docstring on ``worker.py`` for why it keeps its own copy instead of
   importing ``replay.py`` directly: ``worker.py`` must stay import-safe with only
   ``gi`` + stdlib + sibling gst modules, never the pydantic-carrying civiccast
   package).

   Falsifications required by spec-supervisor D2 / design.md sec4, PARAMETERIZED
   ACROSS ALL FOUR ``parse_control_line`` verbs (reload, swap, caption, stop):
   - lost ack
   - duplicate delivery
   - worker restart between write and apply
   - reconnect under multi-channel load

2. That the Linux FIFO path in ``worker.py`` (``os.mkfifo``, the
   ``hasattr(os, "mkfifo")`` Windows-unavailable guard) is textually UNTOUCHED.
   This dev box has no ``gi`` installed (confirmed: ``import engine`` inside
   ``worker.py`` fails at module import with ``ModuleNotFoundError: gi`` -- see
   ``civiccast/egress/gst/engine.py`` line 55), so ``worker.py`` cannot actually be
   imported here; the check below is therefore a SOURCE-TEXT assertion, not a live
   import, and says so plainly rather than faking an import that cannot happen on
   this box. A companion test attempts a real import and is skipped (not xfailed)
   wherever ``gi`` is unavailable, so it becomes a real proof automatically on a
   box that has GStreamer bindings (e.g. the WSL/Linux CI lane).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path

import pytest

from civiccast.egress.gst.strategy import (
    WORKER_PIPE_FRAME_CAP,
    WorkerPipeSession,
    _WindowsPipeChannel,
    decode_envelope_ack,
    worker_pipe_name,
)
from civiccast.native.supervisor.replay import AppliedIdCache, Verb, delivery_semantics

_VERBS: list[Verb] = ["reload", "swap", "caption", "stop"]
_SAMPLE_LINE: dict[Verb, str] = {
    "reload": "reload /work/c1/playout-graph.reload.abc.json",
    "swap": "swap 1",
    "caption": "caption 1000 2000 aGVsbG8=",
    "stop": "stop",
}


# ---------------------------------------------------------------------------
# Fake in-memory duplex transport + a minimal simulated worker
# ---------------------------------------------------------------------------


class FakeDuplexTransport:
    """In-memory duplex transport standing in for a real named pipe -- proves the
    envelope + replay policy without any Win32 I/O (design.md sec5: 'Pure-logic
    versions run in CI with fake transport')."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._inbox: deque[str] = deque()
        self.closed = False

    def write_line(self, text: str) -> bool:
        if self.closed:
            return False
        self.sent.append(text)
        return True

    def read_line(self) -> str | None:
        if not self._inbox:
            return None
        return self._inbox.popleft()

    def deliver(self, raw: str) -> None:
        self._inbox.append(raw)

    def close(self) -> None:
        self.closed = True


class SimulatedWorker:
    """A minimal stand-in for the real worker's Windows pipe-reader loop: dedups
    incoming envelope commands by id (LRU, same semantics ``worker.py`` keeps its
    own copy of) and, when told to, writes back an ack. Deliberately does NOT
    import ``worker.py`` (gi is unavailable on this box) or exercise real
    GStreamer -- it only proves the wire contract + dedup contract that the real
    worker must uphold."""

    def __init__(self, transport: FakeDuplexTransport, *, capacity: int = 1024) -> None:
        self._transport = transport
        self._applied = AppliedIdCache(capacity=capacity)
        self.dispatched: list[str] = []  # ids actually "applied" (not deduped)

    def receive_all(self, *, apply_result: str = "applied", detail: str | None = None) -> None:
        """Drain every command currently sitting in ``transport.sent`` and ack it,
        deduping by id exactly like the real worker must."""
        for raw in list(self._transport.sent):
            envelope = json.loads(raw)
            command_id = envelope["id"]
            if self._applied.should_apply(command_id):
                self.dispatched.append(command_id)
                if apply_result == "applied":
                    self._applied.mark_applied(command_id)
                self._transport.deliver(
                    json.dumps({"v": 1, "id": command_id, "result": apply_result, "detail": detail})
                )
            else:
                # redelivered id: acked again, NOT re-enacted (D2 dedup contract).
                self._transport.deliver(
                    json.dumps({"v": 1, "id": command_id, "result": "applied", "detail": None})
                )
        self._transport.sent.clear()


def _drain_acks(
    session: WorkerPipeSession, transport: FakeDuplexTransport
) -> list[tuple[str, str, str | None]]:
    results: list[tuple[str, str, str | None]] = []
    while True:
        raw = transport.read_line()
        if raw is None:
            break
        outcome = session.handle_ack_line(raw)
        if outcome is not None:
            results.append(outcome)
    return results


# ---------------------------------------------------------------------------
# Envelope wire format
# ---------------------------------------------------------------------------


def test_encode_envelope_command_matches_spec_shape() -> None:
    session = WorkerPipeSession("c1", FakeDuplexTransport())
    cmd_id = session.send("swap", "swap 1")
    raw = session._transport.sent[-1]  # type: ignore[attr-defined]
    obj = json.loads(raw)
    assert obj == {"v": 1, "id": cmd_id, "cmd": "swap 1"}


def test_decode_envelope_ack_rejects_wrong_version() -> None:
    with pytest.raises(ValueError):
        decode_envelope_ack(json.dumps({"v": 2, "id": "x", "result": "applied"}))


def test_worker_pipe_name_is_per_channel_and_matches_design() -> None:
    assert worker_pipe_name("chan-7") == r"\\.\pipe\civiccast-worker-chan-7"


def test_frame_cap_is_16kib_and_send_rejects_oversized_payload() -> None:
    assert WORKER_PIPE_FRAME_CAP == 16 * 1024
    session = WorkerPipeSession("c1", FakeDuplexTransport())
    huge = "x" * WORKER_PIPE_FRAME_CAP
    with pytest.raises(ValueError):
        session.send("reload", huge)


# ---------------------------------------------------------------------------
# Baseline: normal round trip applies exactly once per verb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", _VERBS)
def test_normal_round_trip_applies(verb: Verb) -> None:
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    worker = SimulatedWorker(transport)

    cmd_id = session.send(verb, _SAMPLE_LINE[verb])
    worker.receive_all()
    outcomes = _drain_acks(session, transport)

    assert outcomes == [(cmd_id, "applied", None)]
    assert worker.dispatched == [cmd_id]
    assert cmd_id not in session._pending


# ---------------------------------------------------------------------------
# Falsification 1 -- lost ack: reload/swap converge, caption drops, stop pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", _VERBS)
def test_falsification_lost_ack(verb: Verb) -> None:
    """FALSIFICATION: a command whose ack never arrives (the worker crashed, the
    pipe dropped it, whatever) must NOT be silently forgotten with the wrong
    outcome. reload/swap must reissue current desired state on reconnect; caption
    must be reported dropped and NEVER reissued; stop must pin the channel
    'stopping' and suppress all further reissue. If any verb's lost-ack handling
    fell through to a no-op (or to the wrong outcome for a different verb), this
    test fails."""
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    cmd_id = session.send(verb, _SAMPLE_LINE[verb])

    # No ack ever arrives -- caller (the strategy) detects the timeout itself.
    assert transport.read_line() is None
    outcome = session.expire(cmd_id)
    expected = delivery_semantics(verb).on_lost_ack
    assert outcome == expected

    reissued = session.reconnect(FakeDuplexTransport())
    if verb in ("reload", "swap"):
        assert len(reissued) == 1
        assert reissued[0] != cmd_id  # a fresh reissue, not a replay of the lost id
    elif verb == "caption":
        assert reissued == []
        assert cmd_id in session.dropped_captions
    else:  # stop
        assert reissued == []
        assert session.stopping is True


# ---------------------------------------------------------------------------
# Falsification 2 -- duplicate delivery: applied once, acked (idempotently) twice
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", _VERBS)
def test_falsification_duplicate_delivery(verb: Verb) -> None:
    """FALSIFICATION: a duplicated envelope frame (retransmit, at-least-once
    transport hiccup) must be applied at most once. If the worker re-enacted a
    duplicate ``swap``/``reload``/``stop``, that would double-apply a
    non-idempotent-looking op; a duplicate ``caption`` must not push the cue
    twice. Both must still be acknowledged (the FIRST send's ack was what got
    lost, not the application)."""
    transport = FakeDuplexTransport()
    worker = SimulatedWorker(transport)
    cmd_id = "fixed-id-for-dup-test"
    line = _SAMPLE_LINE[verb]

    # Same id delivered twice (simulating an at-least-once retransmit): the worker
    # sees two frames with an identical id, as it would over a real retried write.
    envelope = json.dumps({"v": 1, "id": cmd_id, "cmd": line})
    transport.sent.append(envelope)
    transport.sent.append(envelope)

    worker.receive_all()

    assert worker.dispatched == [cmd_id]  # applied exactly once
    raw_acks = [transport.read_line(), transport.read_line()]
    assert all(raw is not None for raw in raw_acks)
    acks = [json.loads(raw) for raw in raw_acks if raw is not None]
    assert [a["id"] for a in acks] == [cmd_id, cmd_id]  # acked twice
    assert all(a["result"] == "applied" for a in acks)


# ---------------------------------------------------------------------------
# Falsification 3 -- worker restart between write and apply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", _VERBS)
def test_falsification_worker_restart_between_write_and_apply(verb: Verb) -> None:
    """FALSIFICATION: the strategy writes a command; the worker process dies
    before applying it (never acks); a fresh worker with an EMPTY dedup cache
    comes up on reconnect. reload/swap must converge (the fresh worker applies
    the reissued desired state); caption must be dropped, never resurrected on
    the new worker; stop must keep the channel pinned stopping, never restarted."""
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    cmd_id = session.send(verb, _SAMPLE_LINE[verb])
    # Worker dies: nothing ever reads transport.sent, no ack comes back.
    outcome = session.expire(cmd_id)
    assert outcome == delivery_semantics(verb).on_lost_ack

    fresh_transport = FakeDuplexTransport()
    fresh_worker = SimulatedWorker(fresh_transport)  # brand-new, empty AppliedIdCache
    reissued_ids = session.reconnect(fresh_transport)

    if verb in ("reload", "swap"):
        assert len(reissued_ids) == 1
        fresh_worker.receive_all()
        assert fresh_worker.dispatched == reissued_ids  # fresh worker applies it
        outcomes = _drain_acks(session, fresh_transport)
        assert outcomes == [(reissued_ids[0], "applied", None)]
    else:
        assert reissued_ids == []
        fresh_worker.receive_all()
        assert fresh_worker.dispatched == []  # nothing to apply -- never resurrected


# ---------------------------------------------------------------------------
# Falsification 4 -- reconnect under multi-channel load
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["reload", "swap"])
def test_falsification_reconnect_multi_channel_load(verb: Verb) -> None:
    """FALSIFICATION: a mass reconnect event (e.g. the control-plane process
    restarted) across many channels must reissue EACH channel's OWN current
    desired state -- never another channel's, never a stale one overwritten by a
    later command on the same channel."""
    sessions = {}
    for i in range(8):
        cid = f"chan-{i}"
        transport = FakeDuplexTransport()
        session = WorkerPipeSession(cid, transport)
        session.send(verb, f"{verb} {i}-v1")
        session.send(verb, f"{verb} {i}-v2")  # overwritten desired state
        sessions[cid] = session

    for cid, session in sessions.items():
        fresh_transport = FakeDuplexTransport()
        reissued_ids = session.reconnect(fresh_transport)
        assert len(reissued_ids) == 1
        sent_line = json.loads(fresh_transport.sent[0])["cmd"]
        assert sent_line.endswith("v2")  # this channel's CURRENT desired state
        assert cid.split("-")[1] in sent_line  # never cross-contaminated with another channel


# ---------------------------------------------------------------------------
# Safety invariant: caption never replayed even across many lost acks
# ---------------------------------------------------------------------------


def test_caption_lost_acks_never_accumulate_a_replay() -> None:
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    for i in range(5):
        cmd_id = session.send("caption", f"caption {i * 1000} 500 aGVsbG8=")
        session.expire(cmd_id)
    assert session.reconnect(FakeDuplexTransport()) == []
    assert len(session.dropped_captions) == 5


def test_stop_dominates_a_pending_reload_on_the_same_channel() -> None:
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    reload_id = session.send("reload", "reload /work/c1/graph.json")
    session.expire(reload_id)  # lost -> desired state recorded, reload pending reissue
    stop_id = session.send("stop", "stop")
    session.expire(stop_id)
    assert session.stopping is True
    assert session.reconnect(FakeDuplexTransport()) == []


# ---------------------------------------------------------------------------
# The Linux FIFO path in worker.py: untouched
# ---------------------------------------------------------------------------

_WORKER_PY = Path(__file__).resolve().parents[2] / "civiccast" / "egress" / "gst" / "worker.py"


def test_posix_fifo_branch_source_is_unchanged() -> None:
    """SOURCE-TEXT check, not a live import: this dev box has no ``gi`` installed,
    so ``import engine`` inside ``worker.py`` raises ``ModuleNotFoundError`` before
    any of worker.py's own code (Windows or POSIX) can even run -- confirmed
    directly:

        >>> import subprocess
        >>> subprocess.run([py, "-c", "import sys; sys.path.insert(0, 'civiccast/egress/gst'); import worker"])

    fails with ``ModuleNotFoundError: No module named 'gi'``. A companion test
    below attempts the real import and SKIPS (not xfails) here for that reason,
    becoming a live proof automatically wherever gi is present. This test instead
    greps the actual current file text for the exact POSIX FIFO branch (recon
    r1-seam.md sec1, worker.py:34-39 pre-change) to prove it was not deleted,
    replaced, or mutated by the Windows addition."""
    text = _WORKER_PY.read_text(encoding="utf-8")
    assert "os.mkfifo(control_fifo)" in text
    assert 'raise RuntimeError("control FIFO support requires a POSIX host (Linux/macOS)")' in text
    assert 'not hasattr(os, "mkfifo")' in text
    assert "Path(control_fifo).parent.mkdir(parents=True, exist_ok=True)" in text


def test_worker_module_imports_and_exposes_windows_branch_when_gi_available() -> None:
    """Real import, skipped (not run) wherever ``gi`` is unavailable -- see the
    docstring above for why that is expected on this box. Wherever gi IS present
    (the WSL/Linux gst CI lane), this becomes a real, executed proof that the
    module imports cleanly and both branches exist as callables."""
    pytest.importorskip("gi")
    import sys as _sys

    _sys.path.insert(0, str(_WORKER_PY.parent))
    import worker as workermod  # type: ignore[import-not-found]

    assert hasattr(workermod, "main")
    assert hasattr(workermod, "_run_forever_windows_pipe")
    assert hasattr(workermod, "_windows_pipe_reader_loop")


# ---------------------------------------------------------------------------
# CC-WS5-006: _WindowsPipeChannel ack-ordering + explicit expire outcome
#
# These exercise the REAL production channel (serialized request/ack round trip
# plus the WorkerPipeSession policy engine) against an INJECTED fake duplex server --
# no Win32, no gi -- so the ack-ordering repro (Codex CC-WS5-006 defect 1) and
# the explicit lost-ack log (defect 2) are CI-testable on any OS.
# ---------------------------------------------------------------------------


class _ImmediateAckServer:
    """Fake ``WorkerPipeServer`` that acks every written command immediately, and
    records -- at the instant of the transport write -- whether the CHANNEL waiter
    for that command id was ALREADY registered. That boolean is the CC-WS5-006
    ack-ordering invariant: the fix registers the waiter BEFORE the write, so an
    immediate ack can never beat the waiter into place."""

    def __init__(self) -> None:
        self._inbox: deque[str] = deque()
        self.written_cmds: list[str] = []
        self.closed = False
        self.created = False
        self.accepted = False
        # Set by the test after the channel exists so write_line can inspect it.
        self.channel: _WindowsPipeChannel | None = None
        self.waiter_registered_at_write: list[bool] = []

    def create(self) -> None:
        self.created = True

    def accept(self) -> None:
        self.accepted = True

    def write_line(self, text: str) -> bool:
        obj = json.loads(text)
        command_id = str(obj["id"])
        self.written_cmds.append(str(obj["cmd"]))
        if self.channel is not None:
            with self.channel._lock:  # type: ignore[attr-defined]
                self.waiter_registered_at_write.append(
                    command_id in self.channel._pending  # type: ignore[attr-defined]
                )
        self._inbox.append(
            json.dumps({"v": 1, "id": command_id, "result": "applied", "detail": None})
        )
        return True

    def read_line(self) -> str | None:
        if not self._inbox:
            return None
        return self._inbox.popleft()

    def close(self) -> None:
        self.closed = True


class _SilentServer:
    """Fake ``WorkerPipeServer`` that never acks -- models a disconnect observed
    before any response arrives, so ``send_and_wait`` must time out."""

    def __init__(self) -> None:
        self.written_cmds: list[str] = []
        self.closed = False

    def create(self) -> None:
        pass

    def accept(self) -> None:
        pass

    def write_line(self, text: str) -> bool:
        self.written_cmds.append(json.loads(text)["cmd"])
        return True

    def read_line(self) -> str | None:
        return None

    def close(self) -> None:
        self.closed = True


class _NeverConnectServer(_SilentServer):
    """Fake server whose worker never reaches the named-pipe accept point."""

    def __init__(self) -> None:
        super().__init__()
        self._release_accept = threading.Event()

    def accept(self) -> None:
        self._release_accept.wait()

    def close(self) -> None:
        self._release_accept.set()
        super().close()


class _ReadOrderingServer(_ImmediateAckServer):
    """Records an invalid read started before the channel has written a command."""

    def __init__(self) -> None:
        super().__init__()
        self.read_before_write = threading.Event()

    def read_line(self) -> str | None:
        if not self.written_cmds:
            self.read_before_write.set()
        return super().read_line()


def test_channel_does_not_start_a_blocking_read_before_its_first_write() -> None:
    server = _ReadOrderingServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=2.0)
    server.channel = channel
    channel.start()
    try:
        assert server.read_before_write.wait(0.05) is False
        assert channel.send_and_wait("swap", "swap 1") is True
    finally:
        channel.close()


def test_channel_times_out_without_writing_before_worker_connects() -> None:
    server = _NeverConnectServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=0.05)
    channel.start()
    try:
        assert channel.send_and_wait("caption", "caption 0 500 aGk=") is False
        assert server.written_cmds == []
    finally:
        channel.close()


def test_channel_send_and_wait_true_on_immediate_ack_registers_waiter_before_write() -> None:
    """CC-WS5-006 defect 1 (ack-ordering): with an immediate-ack transport,
    ``send_and_wait`` must return True -- and the channel waiter must be registered
    BEFORE the transport write so the ack cannot be dropped by racing ahead of the
    waiter. Pre-fix (write via ``session.send`` happened before registering the
    waiter) this invariant is False."""
    server = _ImmediateAckServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=2.0)
    server.channel = channel
    channel.start()
    try:
        assert channel.send_and_wait("swap", "swap 1") is True
        assert server.waiter_registered_at_write == [True]
    finally:
        channel.close()


def test_channel_send_and_wait_false_and_logs_expire_outcome_on_lost_ack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CC-WS5-006 defect 2 (ignored expire outcome): a command whose ack never
    arrives must return False AND the per-verb lost-ack outcome must be logged
    explicitly (not silently discarded)."""
    server = _SilentServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=0.05)
    channel.start()
    try:
        with caplog.at_level(logging.WARNING, logger="civiccast.egress.gst.strategy"):
            assert channel.send_and_wait("reload", "reload /w/g.json") is False
    finally:
        channel.close()
    assert "lost-ack" in caplog.text
    # reload's explicit expire outcome (replay.delivery_semantics) is surfaced.
    assert "reissue_desired_state" in caplog.text


def test_channel_reconnect_replays_reload_and_swap_not_caption_or_stop() -> None:
    """CC-WS5-006 defect 3 (reconnect): through the production channel, after a
    reload+swap+caption have been sent, a reconnect reissues ONLY the current
    reload/swap desired state -- never the caption. A stop pins the channel and
    suppresses all reissue."""
    server = _ImmediateAckServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=2.0)
    server.channel = channel
    channel.start()
    try:
        assert channel.send_and_wait("reload", "reload /w/g.json") is True
        assert channel.send_and_wait("swap", "swap 1") is True
        assert channel.send_and_wait("caption", "caption 0 500 aGk=") is True
    finally:
        channel.close()

    reissued = channel.session.reconnect()
    assert reissued == ["reissue-reload-c1", "reissue-swap-c1"]
    assert server.written_cmds[-2:] == ["reload /w/g.json", "swap 1"]
    # the caption (index 2 of the original sends) is never among the reissues.
    assert not any(cmd.startswith("caption") for cmd in server.written_cmds[3:])


def test_channel_reconnect_after_stop_reissues_nothing() -> None:
    """CC-WS5-006 defect 3 (stop): once a stop is recorded, a reconnect reissues
    nothing -- a stopping channel is never resurrected."""
    server = _ImmediateAckServer()
    channel = _WindowsPipeChannel("c1", server=server, ack_timeout_s=2.0)
    server.channel = channel
    channel.start()
    try:
        assert channel.send_and_wait("reload", "reload /w/g.json") is True
        assert channel.send_and_wait("stop", "stop") is True
    finally:
        channel.close()
    assert channel.session.stopping is True
    assert channel.session.reconnect() == []


def test_channel_new_command_registers_before_dispatch_writes() -> None:
    """CC-WS5-006 defect 1 at the session seam: ``new_command`` records the intent
    (id known, replay + pending set) WITHOUT writing; ``dispatch`` performs the
    write. This split is what lets the channel register its waiter between the two."""
    transport = FakeDuplexTransport()
    session = WorkerPipeSession("c1", transport)
    command = session.new_command("swap", "swap 1")
    assert transport.sent == []  # new_command did NOT write
    assert command.id in session._pending  # ...but the intent is recorded
    returned_id = session.dispatch(command)
    assert returned_id == command.id
    assert json.loads(transport.sent[-1]) == {"v": 1, "id": command.id, "cmd": "swap 1"}
