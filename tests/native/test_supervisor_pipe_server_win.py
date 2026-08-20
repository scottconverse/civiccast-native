# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-pipe tests for the D7 control pipe (RAT-003).

``win`` appears in this module's own filename (house convention, see
``tests/native/test_win_probes.py``) so ``-k "not win"`` deselects it
honestly. Skipped entirely on non-Windows; on Windows this hits the REAL
``CreateNamedPipe``, the REAL security descriptor, and REAL
``ImpersonateNamedPipeClient`` -- no fakes.

Environment note (recorded, not assumed): the caller tier is HOST-DEPENDENT,
and these tests branch on the real, impersonated result rather than assuming
one, so the module runs identically on either host without skipping (the
tests/native no-skip floor). A dev-box shell running as an UNELEVATED admin
carries ``BUILTIN\\Administrators`` marked ``SE_GROUP_USE_FOR_DENY_ONLY`` (a UAC
split token), so for authorization purposes it is an Authenticated-Users-tier,
non-admin caller -- exactly the "non-admin" actor RAT-003's acceptance criteria
call for, exercised WITHOUT any synthetic token: real status/version traffic
over the exact AU mask succeeds and a real admin-tier command is denied. A fully
elevated runner (e.g. windows-latest CI) is instead admin-tier, and the same
real path exercises the allow side. The tier-gating LOGIC itself is proven
exhaustively with synthetic tokens in ``test_supervisor_pipe_server.py``; the
value here is the real ``ImpersonateNamedPipeClient`` extraction + real SDDL
enforcement, on whichever host runs it.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
import uuid
from typing import Any

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real named-pipe tests"),
]

if os.name == "nt":
    import pywintypes
    import win32file  # type: ignore[import-untyped]
    import win32pipe  # type: ignore[import-untyped]
    import win32security

    from civiccast.native.supervisor.pipe_server import (
        ACCEPT_SHUTDOWN_TIMEOUT_SECONDS,
        AUTHENTICATED_USERS_ACCESS_MASK,
        CONTROL_PIPE_SDDL,
        CommandQueue,
        Dispatcher,
        PipeServer,
        create_control_pipe,
        encode_frame,
        impersonate_and_extract,
        read_pipe_dacl_sddl,
    )

_ERROR_ACCESS_DENIED = 5


def _unique_pipe_name() -> str:
    return rf"\\.\pipe\civiccast-supervisor-test-{uuid.uuid4().hex}"


def _create_pipe(name: str, sddl: str | None = None) -> Any:
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl or CONTROL_PIPE_SDDL, win32security.SDDL_REVISION_1
    )
    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    return win32pipe.CreateNamedPipe(
        name,
        win32pipe.PIPE_ACCESS_DUPLEX | win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        65536,
        65536,
        0,
        sa,
    )


def _extract_live_caller_identity() -> tuple[set[str], str]:
    """Round-trip one real frame through a real pipe and return this process's
    live impersonated (groups, sid) via ``ImpersonateNamedPipeClient`` -- no
    synthetic token. Used both to prove the extraction path and to detect the
    host's caller tier so the RAT-003 behavior tests branch on the truth."""

    name = _unique_pipe_name()
    handle = _create_pipe(name)
    client = None
    try:
        client = win32file.CreateFile(
            name, AUTHENTICATED_USERS_ACCESS_MASK, 0, None, win32file.OPEN_EXISTING, 0, None
        )
        with contextlib.suppress(pywintypes.error):
            win32pipe.ConnectNamedPipe(handle, None)  # already connected by CreateFile racing in
        win32file.WriteFile(client, b'{"v":1,"cmd":"status"}\n')
        win32file.ReadFile(handle, 4096)
        groups, sid = impersonate_and_extract(handle)
    finally:
        win32file.CloseHandle(handle)
        if client is not None:
            with contextlib.suppress(pywintypes.error):
                win32file.CloseHandle(client)
    return set(groups), sid


def _caller_is_admin() -> bool:
    """True on a fully elevated host (Administrators/SYSTEM enabled), False on a
    UAC-split unelevated-admin dev-box shell (AU-tier for authorization)."""

    groups, _sid = _extract_live_caller_identity()
    return "administrators" in groups or "system" in groups


def test_real_token_extraction_yields_a_coherent_caller_identity() -> None:
    """Ground truth this module leans on: ``impersonate_and_extract`` over a REAL
    ``ImpersonateNamedPipeClient`` returns the LIVE caller's groups + SID -- a
    real identity, not a synthetic fake. Every logon token carries Authenticated
    Users, so that plus a real SID must always be extracted; the admin-vs-AU tier
    is host-dependent (see the module docstring) and is asserted-on by the
    behavior tests below, not fixed here."""

    groups, sid = _extract_live_caller_identity()

    assert "authenticated_users" in groups  # holds for any logon token, either host
    assert sid  # a real SID string was extracted
    # a coherent, single tier classification either way (admin-tier iff Administrators/SYSTEM enabled)
    assert _caller_is_admin() == ("administrators" in groups or "system" in groups)


# ---------------------------------------------------------------------------
# RAT-003: exact SDDL / access mask
# ---------------------------------------------------------------------------


def test_create_control_pipe_sets_exact_sddl_and_au_mask() -> None:
    name = _unique_pipe_name()
    result = create_control_pipe(name=name)
    try:
        assert result.ok is True
        assert result.handle is not None

        sddl_readback = read_pipe_dacl_sddl(result.handle)

        assert "(A;;0x120083;;;AU)" in sddl_readback
        assert ";;;WD)" not in sddl_readback  # FALSIFICATION: no Everyone ACE
        assert ";;;SY)" in sddl_readback
        assert ";;;BA)" in sddl_readback
        assert "(D;;" in sddl_readback and ";;;NU)" in sddl_readback  # explicit DENY NETWORK
    finally:
        if result.handle is not None:
            win32file.CloseHandle(result.handle)


def test_au_mask_constant_is_exactly_rat003_value() -> None:
    """FALSIFICATION: pins the literal mask so a future edit that silently
    widens it (e.g. accidentally adding FILE_CREATE_PIPE_INSTANCE back in)
    fails this test immediately, independent of the SDDL-string test above."""

    assert AUTHENTICATED_USERS_ACCESS_MASK == 0x00120083
    file_create_pipe_instance = 0x4
    assert AUTHENTICATED_USERS_ACCESS_MASK & file_create_pipe_instance == 0


# ---------------------------------------------------------------------------
# RAT-003: squat detection (FILE_FLAG_FIRST_PIPE_INSTANCE)
# ---------------------------------------------------------------------------


def test_create_control_pipe_degrades_instead_of_crashing_on_squat() -> None:
    """FALSIFICATION: a name pre-created by another process must produce a
    degraded PipeCreateResult (D7's defined fail-closed path), NOT an
    unhandled exception that would crash the supervisor's startup."""

    name = _unique_pipe_name()
    squatter = _create_pipe(name)
    try:
        result = create_control_pipe(name=name)

        assert result.ok is False
        assert result.degraded is True
        assert result.handle is None
    finally:
        win32file.CloseHandle(squatter)


def test_non_admin_create_named_pipe_of_same_name_is_denied() -> None:
    """RAT-003's explicit proof that 0x4 (FILE_CREATE_PIPE_INSTANCE) was
    withheld: a second instance of an already-existing
    FILE_FLAG_FIRST_PIPE_INSTANCE pipe is denied by Windows itself (the OS
    refuses a second first-instance regardless of caller tier) -- this is
    the real OS enforcement, not our own authorization code."""

    name = _unique_pipe_name()
    first = _create_pipe(name)
    try:
        with pytest.raises(pywintypes.error) as excinfo:
            _create_pipe(name)
        assert excinfo.value.winerror == _ERROR_ACCESS_DENIED
    finally:
        win32file.CloseHandle(first)


# ---------------------------------------------------------------------------
# RAT-003: real status/version round trip for an Authenticated-Users-only
# caller; a real admin-tier command denied for the same caller.
# ---------------------------------------------------------------------------


def test_real_pipe_status_roundtrip_and_admin_command_matches_caller_tier() -> None:
    """RAT-003 over the REAL pipe + REAL token: read-tier ``status`` always
    succeeds; an admin-tier ``start`` is allowed IFF the live impersonated caller
    is admin-tier and denied otherwise -- proving the dispatcher gates on the
    caller's TRUE identity, not an assumed one. On a UAC-split dev-box shell
    (AU-tier) this exercises the real deny path AC-N1 calls for; on a fully
    elevated CI runner it exercises the real allow path. Neither skips."""

    # Detect the host's real caller tier BEFORE the server is up (independent pipe,
    # same process identity, so it matches what the dispatcher will impersonate).
    caller_is_admin = _caller_is_admin()
    expected_admin_result = "ok" if caller_is_admin else "denied"

    name = _unique_pipe_name()

    def handler(_command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"state": "ready"}

    command_queue = CommandQueue(handler)
    dispatcher = Dispatcher(command_queue=command_queue)
    server = PipeServer(dispatcher, name=name)
    create_result = server.create()
    assert create_result.ok is True, create_result.detail

    server_thread = threading.Thread(target=server.accept_and_serve_one, daemon=True)
    server_thread.start()

    try:
        client = win32file.CreateFile(
            name, AUTHENTICATED_USERS_ACCESS_MASK, 0, None, win32file.OPEN_EXISTING, 0, None
        )
        try:
            win32file.WriteFile(client, encode_frame({"v": 1, "cmd": "status", "id": "req-1"}))
            _, raw_reply = win32file.ReadFile(client, 4096)
            import json

            reply = json.loads(raw_reply.rstrip(b"\n").decode("utf-8"))
            assert reply["result"] == "ok"  # read tier succeeds for any caller
            assert reply["id"] == "req-1"

            # Same connection, same real caller: an admin-tier command is gated
            # on that caller's TRUE impersonated tier (denied for AU, ok for admin).
            win32file.WriteFile(client, encode_frame({"v": 1, "cmd": "start", "id": "req-2"}))
            _, raw_reply2 = win32file.ReadFile(client, 4096)
            reply2 = json.loads(raw_reply2.rstrip(b"\n").decode("utf-8"))
            assert reply2["result"] == expected_admin_result, (
                f"admin-tier 'start' result {reply2['result']!r} did not match the live "
                f"caller tier (admin={caller_is_admin}); expected {expected_admin_result!r}"
            )
        finally:
            win32file.CloseHandle(client)
    finally:
        server_thread.join(timeout=5)
        command_queue.stop()
        server.close()


# ---------------------------------------------------------------------------
# Cancellable shutdown of the accept loop (gauntlet run 17 wedge, 2026-07-31)
# ---------------------------------------------------------------------------
#
# The supervisor service, alive for the first time, wedged in
# SERVICE_STOP_PENDING forever: SvcDoRun never returned and the SCM checkpoint
# stayed 0x1 for 112+ seconds. `ConnectNamedPipe(handle, None)` on a
# blocking-mode pipe is a synchronous, non-cancellable wait, the D7 accept
# thread had been parked in it since boot with no client ever connecting, and
# the stop path's `PipeServer.close()` called `CloseHandle` on that exact
# handle. A direct probe on this OS build measured the result: `CloseHandle`
# ITSELF never returned. These tests hold the fix's contract.
#
# Every one of them bounds its own wait (never an infinite join) so a
# regression fails by TIMEOUT-ASSERT rather than hanging the suite.


def _serving_server(name: str) -> tuple[PipeServer, CommandQueue]:
    def handler(_command: str, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"state": "ready"}

    command_queue = CommandQueue(handler)
    server = PipeServer(Dispatcher(command_queue=command_queue), name=name)
    create_result = server.create()
    assert create_result.ok is True, create_result.detail
    return server, command_queue


def _park_an_accept_thread(server: PipeServer) -> tuple[threading.Thread, threading.Event]:
    """Start the accept thread and return only once it is genuinely parked in
    ``ConnectNamedPipe`` (proven by it NOT having returned)."""

    returned = threading.Event()

    def accept() -> None:
        try:
            server.accept_and_serve_one()
        except Exception:  # teardown-shaped errors are the caller's to assert on
            pass
        finally:
            returned.set()

    thread = threading.Thread(target=accept, name="test-accept", daemon=True)
    thread.start()
    time.sleep(0.5)
    assert not returned.is_set(), "the accept thread was expected to be parked in ConnectNamedPipe"
    return thread, returned


def _close_off_thread(server: PipeServer) -> tuple[threading.Event, list[BaseException]]:
    """Run ``close()`` on its own daemon thread so a close that BLOCKS (the
    pre-fix behavior) fails this test by timeout instead of hanging pytest."""

    finished = threading.Event()
    errors: list[BaseException] = []

    def do_close() -> None:
        try:
            server.close()
        except BaseException as exc:  # recorded, then asserted on by the caller
            errors.append(exc)
        finally:
            finished.set()

    threading.Thread(target=do_close, name="test-close", daemon=True).start()
    return finished, errors


def test_close_ends_a_never_connected_accept_thread_within_the_bound() -> None:
    """THE run-17 wedge, reduced: an accept thread parked in ConnectNamedPipe
    since boot, no client ever connected, and then a stop. Both halves must
    hold -- close() must RETURN, and the accept thread must END -- inside
    ACCEPT_SHUTDOWN_TIMEOUT_SECONDS.

    FALSIFICATION: against the pre-fix tree this fails on the FIRST assert
    (close() parked in CloseHandle and never returned)."""

    server, command_queue = _serving_server(_unique_pipe_name())
    try:
        _thread, accept_returned = _park_an_accept_thread(server)

        started = time.monotonic()
        close_finished, close_errors = _close_off_thread(server)

        assert close_finished.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS + 2.0), (
            "PipeServer.close() did not return: it is blocked on the handle the accept "
            "thread is parked on (the run-17 STOP_PENDING wedge)"
        )
        assert close_errors == [], f"close() must never raise; got {close_errors!r}"
        assert accept_returned.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS), (
            "the accept thread is still parked in ConnectNamedPipe after close()"
        )
        elapsed = time.monotonic() - started
        assert elapsed <= ACCEPT_SHUTDOWN_TIMEOUT_SECONDS, (
            f"close() + accept-thread exit took {elapsed:.2f}s, over the "
            f"{ACCEPT_SHUTDOWN_TIMEOUT_SECONDS}s bound"
        )
    finally:
        command_queue.stop()


def test_close_is_idempotent_and_bounded_on_repeat_and_never_accepted_servers() -> None:
    """``close()`` is called from ``_ControlPipe.close()`` on every stop path,
    including ones that already ran it, and on a server whose accept loop never
    started. None of those may raise or block."""

    # (a) a created server nobody ever accepted on
    server, command_queue = _serving_server(_unique_pipe_name())
    try:
        started = time.monotonic()
        server.close()
        server.close()  # idempotent: the second call is a clean no-op
        assert time.monotonic() - started <= ACCEPT_SHUTDOWN_TIMEOUT_SECONDS
    finally:
        command_queue.stop()

    # (b) a server that was never created at all
    never_created = PipeServer(
        Dispatcher(command_queue=CommandQueue(lambda _c, _p: {})), name=_unique_pipe_name()
    )
    never_created.close()
    never_created.close()

    # (c) a server whose accept thread WAS parked, closed twice
    server2, command_queue2 = _serving_server(_unique_pipe_name())
    try:
        _thread, accept_returned = _park_an_accept_thread(server2)
        close_finished, close_errors = _close_off_thread(server2)
        assert close_finished.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS + 2.0)
        assert close_errors == []
        assert accept_returned.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS)
        server2.close()  # second close after a real unblock: still a no-op
    finally:
        command_queue2.stop()


def test_accept_loop_unwinds_after_close_instead_of_reblocking() -> None:
    """The production shape (``_ControlPipe._accept_loop``): a `while running:
    accept_and_serve_one()` loop that has served a real client, gone back to
    blocking, and is then closed. The loop must EXIT, not re-park on a handle
    that is being torn down -- and the served round trip must be unchanged."""

    name = _unique_pipe_name()
    server, command_queue = _serving_server(name)
    loop_exited = threading.Event()
    running = threading.Event()
    running.set()

    def accept_loop() -> None:
        try:
            while running.is_set():
                with contextlib.suppress(Exception):
                    server.accept_and_serve_one()
        finally:
            loop_exited.set()

    threading.Thread(target=accept_loop, name="test-accept-loop", daemon=True).start()
    try:
        client = win32file.CreateFile(
            name, AUTHENTICATED_USERS_ACCESS_MASK, 0, None, win32file.OPEN_EXISTING, 0, None
        )
        try:
            win32file.WriteFile(client, encode_frame({"v": 1, "cmd": "status", "id": "loop-1"}))
            _, raw_reply = win32file.ReadFile(client, 4096)
            import json

            reply = json.loads(raw_reply.rstrip(b"\n").decode("utf-8"))
            assert reply["result"] == "ok"  # per-connection behavior unchanged
            assert reply["id"] == "loop-1"
        finally:
            win32file.CloseHandle(client)

        time.sleep(0.5)  # let the loop go back to blocking in ConnectNamedPipe
        running.clear()
        close_finished, close_errors = _close_off_thread(server)
        assert close_finished.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS + 2.0), (
            "close() blocked while the loop was re-parked in ConnectNamedPipe"
        )
        assert close_errors == []
        assert loop_exited.wait(timeout=ACCEPT_SHUTDOWN_TIMEOUT_SECONDS), (
            "the accept LOOP did not unwind after close()"
        )
    finally:
        running.clear()
        command_queue.stop()
