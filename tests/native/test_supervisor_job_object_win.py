# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-Win32 tests for ``civiccast.native.supervisor.job_object``.

``win`` appears in this module's own filename (per the D3/CI naming
convention the brief requires) so ``-k "not win"`` deselects it honestly.
Skipped entirely on non-Windows (``pytest.mark.skipif``); on Windows these
create REAL Job Objects, spawn REAL child processes, and assert real direct-child
kill-on-close/assignment/no-breakaway behavior -- the pure-logic suite in
``test_supervisor_job_object.py`` proves the CONTROL LOGIC against a fake;
this file proves the underlying Win32 calls actually do what D3/AC4 require.

Every real Win32 call in this file goes through
``civiccast.native.supervisor.job_object``'s own wrapper (``JobObjectController``
/ ``Win32JobObjectApi`` / ``sweep_stragglers``) -- no raw ``win32job`` call is
made directly here, so these tests exercise exactly the production seam.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real Job Object"),
]

if os.name == "nt":
    import psutil

    from civiccast.native.supervisor.job_object import (
        JobObjectController,
        Win32JobObjectApi,
        sweep_stragglers,
    )


def _unique_job_name() -> str:
    return f"Global\\CivicCastWS5JobTest-{uuid.uuid4().hex}"


def _spawn_sleeper() -> subprocess.Popen[bytes]:
    """A real, long-lived child process: this interpreter sleeping, so no
    external binary dependency is required beyond Python itself."""

    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 5.0, interval_seconds: float = 0.1
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_seconds)
    return bool(predicate())


# ---------------------------------------------------------------------------
# Job creation + limits (kill-on-close set, breakaway NOT set)
# ---------------------------------------------------------------------------


def test_ensure_job_sets_kill_on_close_and_leaves_breakaway_disabled() -> None:
    import win32job  # only to READ BACK the flags for assertion; the SET is via the wrapper

    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    try:
        handle = controller.ensure_job()

        info = win32job.QueryInformationJobObject(
            handle, win32job.JobObjectExtendedLimitInformation
        )
        flags = info["BasicLimitInformation"]["LimitFlags"]

        assert flags & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, "kill-on-close must be set"
        assert not (flags & win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK), "breakaway must be disabled"
        assert not (flags & win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK), (
            "silent breakaway must be disabled"
        )
    finally:
        controller.close()


def test_ensure_job_is_idempotent_against_the_real_handle() -> None:
    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    try:
        first = controller.ensure_job()
        second = controller.ensure_job()
        assert first == second
    finally:
        controller.close()


def test_job_object_carries_explicit_sddl_system_and_admins_only() -> None:
    """F-JOB-1 (coordinator review): the GLOBAL named job must carry an
    EXPLICIT security descriptor, never the default DACL, so an unprivileged
    token cannot open+TerminateJobObject the station's process tree. Read the
    DACL back and assert the SYSTEM + BUILTIN\\Administrators ACEs and the
    ABSENCE of an Everyone (``;;;WD``) ACE. GENERIC_ALL normalizes to the
    object-specific mask on readback, so this asserts on the SID markers, not
    the literal "GA" (win_probes empirical caution)."""

    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    try:
        handle = controller.ensure_job()
        sddl = api.read_dacl_sddl(handle)
        assert ";;;SY)" in sddl, f"SYSTEM ACE missing from job DACL: {sddl}"
        assert ";;;BA)" in sddl, f"Administrators ACE missing from job DACL: {sddl}"
        assert ";;;WD)" not in sddl, f"Everyone (WD) ACE must be absent from job DACL: {sddl}"
    finally:
        controller.close()


# ---------------------------------------------------------------------------
# assign_child -- real assignment, verified via IsProcessInJob
# ---------------------------------------------------------------------------


def test_assign_child_real_process_is_reported_in_job() -> None:
    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    child = _spawn_sleeper()
    try:
        controller.assign_child(child.pid)

        handle = controller.ensure_job()
        assert api.is_process_in_job(handle, child.pid) is True
        assert controller.assigned_pids == (child.pid,)
    finally:
        controller.close()  # kills the child too (proven separately below)
        child.wait(timeout=5)


# ---------------------------------------------------------------------------
# close() -- real kill-on-close for an assigned child
# ---------------------------------------------------------------------------


def test_close_kills_a_single_assigned_child() -> None:
    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    child = _spawn_sleeper()
    controller.assign_child(child.pid)
    assert child.poll() is None, "child must still be alive before close()"

    controller.close()

    assert _wait_until(lambda: child.poll() is not None), "child must be reaped by kill-on-close"
    assert not psutil.pid_exists(child.pid)


def test_close_without_ever_creating_is_a_real_noop() -> None:
    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())

    controller.close()  # must not raise -- nothing was ever created


# ---------------------------------------------------------------------------
# open_existing_job -- real ERROR_FILE_NOT_FOUND mapping
# ---------------------------------------------------------------------------


def test_open_existing_job_returns_none_for_an_unknown_name() -> None:
    """FALSIFICATION: a job name nothing ever created must map to ``None``,
    not raise -- proving ERROR_FILE_NOT_FOUND is the expected, handled path,
    not an unhandled exception that would crash a fresh supervisor's sweep on
    every normal boot (the common case has no straggler job)."""

    api = Win32JobObjectApi()

    result = api.open_existing_job(_unique_job_name())

    assert result is None


# ---------------------------------------------------------------------------
# sweep_stragglers -- real defense-in-depth: a job that survived its owner
# ---------------------------------------------------------------------------


def test_sweep_stragglers_finds_and_terminates_a_surviving_job() -> None:
    """Simulate a prior supervisor instance that assigned a child to a
    named job and never called close() (the handle this test holds open
    stands in for whatever kept the job alive past its creator). A fresh
    sweep -- a NEW Win32JobObjectApi, exactly as a newly-started supervisor
    process would use -- must find it by name, list the straggler pid,
    terminate it, and close the reopened handle.
    """

    job_name = _unique_job_name()
    # F-JOB-1: the production job SDDL is SYSTEM + Administrators only, which an
    # UNELEVATED test runner cannot OpenJobObject by name (that denial IS the
    # hardening, proven by test_job_object_carries_explicit_sddl_*). To exercise
    # the sweep's find+terminate LOGIC on an unelevated box, the leaked job is
    # created with a permissive test SD; the real SYSTEM->SYSTEM sweep against
    # the restrictive SDDL is a dev-box/elevated item (see PENDING.md).
    leaked_api = Win32JobObjectApi(sddl="D:(A;;GA;;;WD)")
    leaked_controller = JobObjectController(api=leaked_api, name=job_name)
    straggler = _spawn_sleeper()
    leaked_controller.assign_child(straggler.pid)
    # Deliberately do NOT call leaked_controller.close() -- this is the
    # "still held" scenario the sweep exists to catch.

    try:
        fresh_api = Win32JobObjectApi()
        outcome = sweep_stragglers(fresh_api, name=job_name)

        assert outcome.found_existing_job is True
        assert straggler.pid in outcome.terminated_pids
        assert _wait_until(lambda: straggler.poll() is not None), (
            "the straggler must actually be terminated by the sweep"
        )
    finally:
        # Best-effort cleanup of the leaked handle this test intentionally
        # held open; harmless if the sweep already tore the object down.
        leaked_controller.close()
        if straggler.poll() is None:
            straggler.terminate()
        straggler.wait(timeout=5)


def test_sweep_stragglers_is_clean_when_nothing_survived() -> None:
    api = Win32JobObjectApi()
    controller = JobObjectController(api=api, name=_unique_job_name())
    child = _spawn_sleeper()
    controller.assign_child(child.pid)
    controller.close()  # kill-on-close reaps the child normally, as expected
    child.wait(timeout=5)

    fresh_api = Win32JobObjectApi()
    outcome = sweep_stragglers(fresh_api, name=controller.name)

    assert outcome.found_existing_job is False
    assert outcome.terminated_pids == []
