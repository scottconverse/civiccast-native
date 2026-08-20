# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure-logic tests for the D7 control pipe: JSON-lines framing, the 16 KiB
frame cap, per-command authorization routing, audit-log wiring, and the
single serialized command queue (AC-N5). No Windows APIs, no real pipe --
those live in ``tests/native/test_supervisor_pipe_server_win.py`` (real
``CreateNamedPipe`` + SDDL + impersonation). This module runs on every OS in
CI, including the ``ubuntu`` job (per the design's "CI-pure (ubuntu +
windows)" proof tier).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from civiccast.native.supervisor.authz import _all_commands
from civiccast.native.supervisor.pipe_server import (
    FRAME_CAP_BYTES,
    CommandQueue,
    Dispatcher,
    build_response,
    encode_frame,
    parse_frame,
)

ALL_COMMANDS = _all_commands()
READ_COMMANDS = ("status", "version")
ADMIN_COMMANDS = ("start", "stop", "restart", "drain", "runtime_set")

AUTHENTICATED_USERS_ONLY = frozenset({"authenticated_users"})
ADMIN_GROUPS = frozenset({"authenticated_users", "administrators"})
SYSTEM_GROUPS = frozenset({"authenticated_users", "system"})
NO_GROUPS: frozenset[str] = frozenset()


def _frame(obj: dict[str, Any]) -> bytes:
    return encode_frame(obj)


# ---------------------------------------------------------------------------
# parse_frame -- JSON-lines, {"v":1}, 16 KiB cap
# ---------------------------------------------------------------------------


def test_parse_frame_valid_status_request() -> None:
    frame = parse_frame(_frame({"v": 1, "cmd": "status"}))
    assert frame.ok is True
    assert frame.payload == {"v": 1, "cmd": "status"}
    assert frame.close_reason is None


def test_parse_frame_oversized_frame_closes() -> None:
    """FALSIFICATION: a frame one byte over the cap must be rejected, not
    silently accepted because "it's close enough" or because the JSON
    itself is well-formed -- the cap is a hard byte-length boundary (D7:
    16 KiB frame cap; oversized -> close connection), independent of
    whether the payload would otherwise parse.
    """

    huge_cmd = "x" * FRAME_CAP_BYTES
    raw = _frame({"v": 1, "cmd": "status", "pad": huge_cmd})
    assert len(raw) > FRAME_CAP_BYTES

    frame = parse_frame(raw)

    assert frame.ok is False
    assert frame.payload is None
    assert frame.close_reason is not None
    assert "oversized" in frame.close_reason


def test_parse_frame_exactly_at_cap_is_accepted() -> None:
    """The cap is an upper bound, not an off-by-one trap: a frame whose byte
    length equals the cap exactly must still parse."""

    pad = ""
    raw_padded = _frame({"v": 1, "cmd": "status", "pad": pad})
    # Grow the pad field one byte of slack at a time until the encoded frame
    # is exactly at the cap -- avoids assuming JSON-escaping/quoting
    # overhead ahead of time.
    while len(raw_padded) < FRAME_CAP_BYTES:
        pad += "x"
        raw_padded = _frame({"v": 1, "cmd": "status", "pad": pad})
    assert len(raw_padded) == FRAME_CAP_BYTES

    frame = parse_frame(raw_padded)
    assert frame.ok is True


def test_parse_frame_malformed_json_closes() -> None:
    """FALSIFICATION: invalid JSON must close the connection, not be
    swallowed into a default/empty command."""

    frame = parse_frame(b"{not json at all")
    assert frame.ok is False
    assert frame.close_reason is not None
    assert "malformed" in frame.close_reason


def test_parse_frame_top_level_not_an_object_closes() -> None:
    """FALSIFICATION: a syntactically valid JSON value that is not an object
    (e.g. a bare JSON array) must not be accepted just because ``json.loads``
    succeeded."""

    frame = parse_frame(b"[1, 2, 3]")
    assert frame.ok is False
    assert frame.close_reason is not None


def test_parse_frame_missing_v_closes() -> None:
    frame = parse_frame(b'{"cmd": "status"}')
    assert frame.ok is False
    assert frame.close_reason is not None
    assert "v=" in frame.close_reason or "v" in frame.close_reason


def test_parse_frame_wrong_v_closes() -> None:
    """FALSIFICATION: envelope version 2 (or any non-1 value) is not silently
    coerced into version 1 -- D7 fixes the envelope at ``{"v":1}``."""

    frame = parse_frame(_frame({"v": 2, "cmd": "status"}))
    assert frame.ok is False
    assert frame.close_reason is not None


def test_parse_frame_missing_cmd_closes() -> None:
    frame = parse_frame(_frame({"v": 1}))
    assert frame.ok is False
    assert frame.close_reason is not None


def test_parse_frame_non_string_cmd_closes() -> None:
    frame = parse_frame(_frame({"v": 1, "cmd": 5}))
    assert frame.ok is False


def test_parse_frame_invalid_utf8_closes() -> None:
    """FALSIFICATION: bytes that are not valid UTF-8 must close the
    connection rather than raise an uncaught exception out of the framing
    layer."""

    frame = parse_frame(b"\xff\xfe\x00\x01")
    assert frame.ok is False
    assert frame.close_reason is not None


# ---------------------------------------------------------------------------
# build_response
# ---------------------------------------------------------------------------


def test_build_response_echoes_id_when_present() -> None:
    response = build_response({"v": 1, "cmd": "status", "id": "abc123"}, status="ok", detail="applied")
    assert response["v"] == 1
    assert response["cmd"] == "status"
    assert response["result"] == "ok"
    assert response["id"] == "abc123"


def test_build_response_omits_id_when_absent() -> None:
    response = build_response({"v": 1, "cmd": "status"}, status="ok", detail="applied")
    assert "id" not in response


# ---------------------------------------------------------------------------
# Dispatcher -- authz routing + audit logging + queue wiring
# ---------------------------------------------------------------------------


def _handler_ok(_command: str, _payload: dict[str, Any]) -> dict[str, Any]:
    return {"state": "ready"}


def _make_dispatcher(
    *, audit_calls: list[tuple[str, str]] | None = None, handler: Any = _handler_ok
) -> tuple[Dispatcher, CommandQueue]:
    command_queue = CommandQueue(handler)
    audit_log = None
    if audit_calls is not None:

        def _audit(sid: str, cmd: str) -> None:
            audit_calls.append((sid, cmd))

        audit_log = _audit
    return Dispatcher(command_queue=command_queue, audit_log=audit_log), command_queue


@pytest.mark.parametrize("command", READ_COMMANDS)
def test_dispatcher_read_tier_allowed_for_authenticated_users(command: str) -> None:
    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(
        _frame({"v": 1, "cmd": command}), groups=AUTHENTICATED_USERS_ONLY, caller_sid="S-1-5-21-test-1001"
    )
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "ok"
    queue.stop()


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_dispatcher_admin_tier_denied_for_authenticated_users_only(command: str) -> None:
    """FALSIFICATION: this is AC-N1's exact shape at the dispatcher layer --
    a caller carrying only Authenticated Users (no Administrators/SYSTEM)
    must be denied every mutating command, not just ``stop``."""

    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(
        _frame({"v": 1, "cmd": command}), groups=AUTHENTICATED_USERS_ONLY, caller_sid="S-1-5-21-test-1001"
    )
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "denied"
    queue.stop()


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_dispatcher_admin_tier_allowed_for_administrators(command: str) -> None:
    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(
        _frame({"v": 1, "cmd": command}), groups=ADMIN_GROUPS, caller_sid="S-1-5-32-544"
    )
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "ok"
    queue.stop()


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_dispatcher_admin_tier_allowed_for_system(command: str) -> None:
    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(_frame({"v": 1, "cmd": command}), groups=SYSTEM_GROUPS, caller_sid="S-1-5-18")
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "ok"
    queue.stop()


def test_dispatcher_no_groups_denied_even_status() -> None:
    """Fail-closed: a caller who carries none of the known groups (e.g. a
    token extraction failure upstream) is denied even the read tier."""

    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(_frame({"v": 1, "cmd": "status"}), groups=NO_GROUPS, caller_sid="S-1-0-0")
    assert outcome.response is not None
    assert outcome.response["result"] == "denied"
    queue.stop()


def test_dispatcher_unknown_command_denied() -> None:
    """FALSIFICATION: an unrecognized command string must be denied, not
    routed to the handler and not treated as an implicit no-op success."""

    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(
        _frame({"v": 1, "cmd": "reboot_the_datacenter"}), groups=ADMIN_GROUPS, caller_sid="S-1-5-32-544"
    )
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "denied"
    queue.stop()


def test_dispatcher_malformed_frame_closes_without_reaching_handler() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(command: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((command, payload))
        return {}

    dispatcher, queue = _make_dispatcher(handler=handler)
    outcome = dispatcher.handle_frame(b"not json", groups=ADMIN_GROUPS, caller_sid="S-1-5-32-544")
    assert outcome.action == "close"
    assert not calls
    queue.stop()


def test_dispatcher_audit_logs_mutating_command_with_caller_sid() -> None:
    audit_calls: list[tuple[str, str]] = []
    dispatcher, queue = _make_dispatcher(audit_calls=audit_calls)
    dispatcher.handle_frame(
        _frame({"v": 1, "cmd": "stop"}), groups=ADMIN_GROUPS, caller_sid="S-1-5-21-test-9999"
    )
    assert audit_calls == [("S-1-5-21-test-9999", "stop")]
    queue.stop()


def test_dispatcher_does_not_audit_log_read_command() -> None:
    audit_calls: list[tuple[str, str]] = []
    dispatcher, queue = _make_dispatcher(audit_calls=audit_calls)
    dispatcher.handle_frame(
        _frame({"v": 1, "cmd": "status"}), groups=ADMIN_GROUPS, caller_sid="S-1-5-21-test-9999"
    )
    assert audit_calls == []
    queue.stop()


def test_dispatcher_does_not_audit_log_denied_mutating_command() -> None:
    """A denied ``stop`` is not the same as an executed one -- only commands
    that were actually authorized and run get an audit entry (D7: "every
    mutating command is audit-logged with the caller SID", read as "every
    mutating command *the server carried out*")."""

    audit_calls: list[tuple[str, str]] = []
    dispatcher, queue = _make_dispatcher(audit_calls=audit_calls)
    dispatcher.handle_frame(
        _frame({"v": 1, "cmd": "stop"}), groups=AUTHENTICATED_USERS_ONLY, caller_sid="S-1-5-21-test-1001"
    )
    assert audit_calls == []
    queue.stop()


def test_dispatcher_handler_exception_becomes_error_reply_not_a_crash() -> None:
    def boom(_command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("child process refused to start")

    dispatcher, queue = _make_dispatcher(handler=boom)
    outcome = dispatcher.handle_frame(_frame({"v": 1, "cmd": "start"}), groups=ADMIN_GROUPS, caller_sid="S-1-5-32-544")
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "error"
    queue.stop()


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_dispatcher_exhaustive_command_x_tier_matrix(command: str) -> None:
    """Every command in authz.Command is routed through the same
    authorize() the pure authz test suite pins -- this closes the gap
    between "authz.authorize is correct in isolation" and "the pipe server
    actually calls it for every known command"."""

    dispatcher, queue = _make_dispatcher()
    outcome = dispatcher.handle_frame(_frame({"v": 1, "cmd": command}), groups=ADMIN_GROUPS, caller_sid="S-1-5-32-544")
    assert outcome.action == "reply"
    assert outcome.response is not None
    assert outcome.response["result"] == "ok"
    queue.stop()


# ---------------------------------------------------------------------------
# CommandQueue -- AC-N5: concurrent conflicting commands are serialized
# ---------------------------------------------------------------------------


def test_command_queue_runs_commands_in_submission_order() -> None:
    order: list[str] = []

    def handler(command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        order.append(command)
        return {}

    queue = CommandQueue(handler)
    try:
        queue.submit("start", {}, timeout=5)
        queue.submit("stop", {}, timeout=5)
        queue.submit("restart", {}, timeout=5)
    finally:
        queue.stop()

    assert order == ["start", "stop", "restart"]


def test_command_queue_serializes_concurrent_submissions_no_torn_state() -> None:
    """FALSIFICATION (AC-N5): if the queue were NOT actually serializing --
    e.g. if it ran each submitted command on its own thread with no mutual
    exclusion -- this test would observe an interleaved (torn) sequence:
    thread A's "begin" immediately followed by thread B's "begin" before
    A's "end". A correctly serialized queue can NEVER produce that pattern
    even though the handler itself does no locking and sleeps mid-command
    to make a race maximally likely to show up.
    """

    events: list[str] = []
    events_lock = threading.Lock()

    def handler(command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        with events_lock:
            events.append(f"{command}:begin")
        time.sleep(0.02)  # widen the window a race would need to slip through
        with events_lock:
            events.append(f"{command}:end")
        return {}

    queue = CommandQueue(handler)
    threads = [
        threading.Thread(target=lambda i=i: queue.submit(f"cmd{i}", {}, timeout=5)) for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    queue.stop()

    assert len(events) == 16
    # Every "begin" must be immediately followed by its OWN "end" -- proves
    # no second command's "begin" was ever interleaved before the first
    # command's "end" (no torn state).
    for i in range(0, len(events), 2):
        begin = events[i]
        end = events[i + 1]
        assert begin.endswith(":begin")
        assert end.endswith(":end")
        assert begin.split(":")[0] == end.split(":")[0]


def test_command_queue_zero_commands_stop_is_a_clean_noop() -> None:
    queue = CommandQueue(_handler_ok)
    queue.start()
    queue.stop()  # must not hang, must not raise


def test_command_queue_timeout_raises_when_handler_never_returns() -> None:
    started = threading.Event()

    def hang(_command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        started.set()
        time.sleep(5)
        return {}

    queue = CommandQueue(hang)
    try:
        with pytest.raises(TimeoutError):
            queue.submit("start", {}, timeout=0.1)
        assert started.wait(timeout=2)
    finally:
        queue.stop(timeout=0.1)
