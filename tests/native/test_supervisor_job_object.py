# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure control-logic tests for ``civiccast.native.supervisor.job_object``.

No Win32 here -- ``FakeJobObjectApi`` never imports ``win32job``/``win32api``,
so this file runs on any OS. It exercises ``JobObjectController`` (assign)
and :func:`sweep_stragglers` against the fake, proving the CONTROL LOGIC (when
is the job created, is assignment idempotent, does the sweep call terminate
only when a straggler job is actually found) independently of the real Win32
calls, which ``test_supervisor_job_object_win.py`` exercises for real.
"""

from __future__ import annotations

import logging

import pytest

from civiccast.native.supervisor.job_object import (
    JOB_OBJECT_NAME,
    JobObjectController,
    SweepOutcome,
    sweep_stragglers,
)


class FakeJobObjectApi:
    """A fake ``JobObjectApi`` that records every call instead of touching
    Win32. ``existing_job`` seeds what :meth:`open_existing_job` returns (the
    "a prior instance's job survived" scenario); ``existing_job_pids`` seeds
    what :meth:`list_job_process_ids` reports for it."""

    def __init__(
        self,
        *,
        existing_job: object | None = None,
        existing_job_pids: list[int] | None = None,
    ) -> None:
        self.existing_job = existing_job
        self.existing_job_pids = existing_job_pids or []
        self.created_names: list[str] = []
        self.configured_handles: list[object] = []
        self.assigned: list[tuple[object, int]] = []
        self.closed_handles: list[object] = []
        self.terminated: list[tuple[object, int]] = []
        self.opened_names: list[str] = []
        self._next_handle_id = 0

    def create_job(self, name: str) -> object:
        self.created_names.append(name)
        self._next_handle_id += 1
        return f"fake-job-handle-{self._next_handle_id}"

    def configure_kill_on_close_no_breakaway(self, handle: object) -> None:
        self.configured_handles.append(handle)

    def assign_process(self, handle: object, pid: int) -> None:
        self.assigned.append((handle, pid))

    def is_process_in_job(self, handle: object, pid: int) -> bool:
        return (handle, pid) in self.assigned

    def is_process_in_any_job(self, pid: int) -> bool:
        return False

    def close_job(self, handle: object) -> None:
        self.closed_handles.append(handle)

    def open_existing_job(self, name: str) -> object | None:
        self.opened_names.append(name)
        return self.existing_job

    def list_job_process_ids(self, handle: object) -> list[int]:
        assert handle == self.existing_job
        return list(self.existing_job_pids)

    def terminate_job(self, handle: object, exit_code: int) -> None:
        self.terminated.append((handle, exit_code))


# ---------------------------------------------------------------------------
# JobObjectController.assign_child -- creation + assignment control logic
# ---------------------------------------------------------------------------


def test_assign_child_creates_job_lazily_on_first_call() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)
    # mypy note: compared with `==` rather than `is` -- mypy's property
    # narrowing for `controller.is_created` is not invalidated by the
    # intervening `assign_child` call (a real mypy limitation for computed
    # properties, verified in this unit's evidence), which would otherwise
    # make the post-mutation assertion below a false "unreachable" error.
    assert controller.is_created == False  # noqa: E712

    controller.assign_child(pid=111)

    assert controller.is_created == True  # noqa: E712
    assert api.created_names == [JOB_OBJECT_NAME]
    assert api.assigned == [("fake-job-handle-1", 111)]
    assert controller.assigned_pids == (111,)


def test_assign_child_configures_kill_on_close_before_first_assignment() -> None:
    """Ordering matters: the D3 limits must be set on the handle BEFORE any
    process is assigned, so no window exists where an assigned child is not
    yet covered by kill-on-close."""

    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)

    controller.assign_child(pid=222)

    assert api.configured_handles == ["fake-job-handle-1"]
    assert api.assigned == [("fake-job-handle-1", 222)]


def test_assign_multiple_children_reuses_one_job() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)

    controller.assign_child(pid=1)
    controller.assign_child(pid=2)
    controller.assign_child(pid=3)

    assert api.created_names == [JOB_OBJECT_NAME]  # created exactly once
    assert api.assigned == [
        ("fake-job-handle-1", 1),
        ("fake-job-handle-1", 2),
        ("fake-job-handle-1", 3),
    ]
    assert controller.assigned_pids == (1, 2, 3)


def test_assign_child_same_pid_twice_is_idempotent() -> None:
    """FALSIFICATION: a caller that retries assign_child for a pid it already
    captured (e.g. after a transient readiness-probe failure elsewhere in the
    supervisor) must NOT re-issue AssignProcessToJobObject for that pid --
    proving the second call did nothing beyond the first, not merely that it
    didn't raise."""

    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)

    controller.assign_child(pid=42)
    controller.assign_child(pid=42)

    assert api.assigned == [("fake-job-handle-1", 42)]  # exactly one call
    assert controller.assigned_pids == (42,)


def test_custom_job_name_is_used() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api, name=r"Local\SomeOtherName")

    controller.assign_child(pid=9)

    assert api.created_names == [r"Local\SomeOtherName"]
    assert controller.name == r"Local\SomeOtherName"


# ---------------------------------------------------------------------------
# JobObjectController.close -- kill-on-close handle ownership
# ---------------------------------------------------------------------------


def test_close_closes_the_job_handle_and_clears_state() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)
    controller.assign_child(pid=7)

    controller.close()

    assert api.closed_handles == ["fake-job-handle-1"]
    assert controller.is_created is False
    assert controller.assigned_pids == ()


def test_close_without_ever_creating_is_a_clean_noop() -> None:
    """FALSIFICATION: closing a controller that never assigned anything must
    not call close_job at all -- there is no handle to close, and calling the
    fake would prove a phantom Win32 call the real wrapper must not make
    either."""

    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)

    controller.close()

    assert api.closed_handles == []


def test_close_is_idempotent() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)
    controller.assign_child(pid=1)

    controller.close()
    controller.close()

    assert api.closed_handles == ["fake-job-handle-1"]  # exactly one close


# ---------------------------------------------------------------------------
# sweep_stragglers -- defense-in-depth control logic
# ---------------------------------------------------------------------------


def test_sweep_with_no_existing_job_is_a_clean_noop() -> None:
    """FALSIFICATION: the common case (kill-on-close already reaped
    everything from a prior run) must NOT call terminate_job or close_job --
    there is nothing to terminate or close. A sweep that calls either here
    would be inventing work against a job that was never opened."""

    api = FakeJobObjectApi(existing_job=None)

    outcome = sweep_stragglers(api)

    assert outcome == SweepOutcome(
        found_existing_job=False,
        terminated_pids=[],
        detail=f"no existing job named {JOB_OBJECT_NAME!r}; nothing to sweep",
    )
    assert api.terminated == []
    assert api.closed_handles == []
    assert api.opened_names == [JOB_OBJECT_NAME]


def test_sweep_finds_existing_job_terminates_and_closes() -> None:
    api = FakeJobObjectApi(existing_job="stale-job-handle", existing_job_pids=[101, 202])

    outcome = sweep_stragglers(api, exit_code=9)

    assert outcome.found_existing_job is True
    assert outcome.terminated_pids == [101, 202]
    assert api.terminated == [("stale-job-handle", 9)]
    assert api.closed_handles == ["stale-job-handle"]


def test_sweep_uses_the_default_job_name_unless_overridden() -> None:
    api = FakeJobObjectApi(existing_job=None)

    sweep_stragglers(api)

    assert api.opened_names == [JOB_OBJECT_NAME]


def test_sweep_honors_a_custom_job_name() -> None:
    api = FakeJobObjectApi(existing_job=None)

    sweep_stragglers(api, name=r"Local\CustomSweepName")

    assert api.opened_names == [r"Local\CustomSweepName"]


def test_sweep_default_exit_code_is_one() -> None:
    api = FakeJobObjectApi(existing_job="h", existing_job_pids=[5])

    sweep_stragglers(api)

    assert api.terminated == [("h", 1)]


def test_sweep_existing_job_with_zero_pids_still_terminates_and_closes() -> None:
    """A job can exist (some handle kept it alive) with no member processes
    left (they already exited on their own) -- the sweep still terminates
    (a no-op against zero members) and closes the handle rather than leaking
    it, since it opened it."""

    api = FakeJobObjectApi(existing_job="empty-job", existing_job_pids=[])

    outcome = sweep_stragglers(api)

    assert outcome.found_existing_job is True
    assert outcome.terminated_pids == []
    assert api.terminated == [("empty-job", 1)]
    assert api.closed_handles == ["empty-job"]


class FakePywintypesError(Exception):
    """Production-SHAPED stand-in for ``pywintypes.error``.

    Deliberately derives from ``Exception`` and NOT from ``OSError``, because
    the real thing does not either -- verified: ``pywintypes.error`` MRO is
    ``error -> Exception -> BaseException -> object`` and
    ``issubclass(pywintypes.error, OSError)`` is ``False``. ``core.py``'s
    CC-WS5-015 comment records the same fact.

    This matters: an earlier revision of this test raised a plain ``OSError``,
    which made an ``except OSError`` handler look correct while being INERT on
    the real Win32 path. A fake that is easier to catch than the real
    exception does not test the fix, it hides it. Carries ``.winerror`` and
    the same 3-tuple ``args`` pywin32 produces."""

    def __init__(self, winerror: int, funcname: str, strerror: str) -> None:
        super().__init__(winerror, funcname, strerror)
        self.winerror = winerror
        self.funcname = funcname
        self.strerror = strerror


class InheritedMembershipApi(FakeJobObjectApi):
    """A fake whose ``assign_process`` raises the way Win32 actually does when
    the pid is ALREADY in the target job:
    ``pywintypes.error(5, 'AssignProcessToJobObject', 'Access is denied.')``.

    ``already_in_job`` seeds what ``IsProcessInJob`` reports, so a test can
    distinguish "denied because already contained" (safe) from "denied for
    some other reason and containment is NOT satisfied" (must fail closed)."""

    def __init__(
        self, *, winerror: int = 5, already_in_job: bool = True, in_any_job: bool = False
    ) -> None:
        super().__init__()
        self._winerror = winerror
        self._already_in_job = already_in_job
        self._in_any_job = in_any_job
        self.membership_checks: list[tuple[object, int]] = []
        self.any_job_checks: list[int] = []

    def assign_process(self, handle: object, pid: int) -> None:
        raise FakePywintypesError(self._winerror, "AssignProcessToJobObject", "Access is denied.")

    def is_process_in_job(self, handle: object, pid: int) -> bool:
        self.membership_checks.append((handle, pid))
        return self._already_in_job

    def is_process_in_any_job(self, pid: int) -> bool:
        self.any_job_checks.append(pid)
        return self._in_any_job


def test_assign_child_accepts_access_denied_when_pid_is_already_in_this_job() -> None:
    """The postgres RESTART path. ``pg_ctl`` runs inside the job, so the
    postmaster it spawns inherits membership before the supervisor sees its
    pid; the ``_assigned_pids`` guard misses (new pid) and
    ``AssignProcessToJobObject`` answers ERROR_ACCESS_DENIED (5).

    Measured 2026-08-08 in Sandbox against candidate 923fad14: this put the
    supervisor into a PERMANENT restart loop -- PostgreSQL started cleanly 13
    times in 5 minutes and was torn down each time for a containment
    "fault", service still reporting RUNNING with nothing listening. Evidence:
    adversarial/evidence/adv-recovery.json + logs-after-kill/supervisor.log.

    Containment is confirmed, not assumed: acceptance requires a positive
    ``IsProcessInJob``."""

    api = InheritedMembershipApi(winerror=5, already_in_job=True)
    controller = JobObjectController(api=api)

    controller.assign_child(4321)

    assert controller.assigned_pids == (4321,)
    assert api.membership_checks == [("fake-job-handle-1", 4321)], (
        "membership must be positively verified via IsProcessInJob, never assumed"
    )


def test_assign_child_still_fails_closed_when_membership_cannot_be_confirmed() -> None:
    """ACCESS_DENIED with the pid NOT in the job is a real containment
    failure -- an uncontained child would escape kill-on-job-close (D3), so
    this must still raise rather than be swallowed."""

    api = InheritedMembershipApi(winerror=5, already_in_job=False)
    controller = JobObjectController(api=api)

    with pytest.raises(FakePywintypesError):
        controller.assign_child(4321)

    assert controller.assigned_pids == ()


def test_assign_child_does_not_swallow_other_win32_errors() -> None:
    """Only ERROR_ACCESS_DENIED means "already in this job". Any other error
    code is a genuine failure and must propagate untouched -- and must not
    even reach the membership check."""

    api = InheritedMembershipApi(winerror=87, already_in_job=True)
    controller = JobObjectController(api=api)

    with pytest.raises(FakePywintypesError):
        controller.assign_child(4321)

    assert controller.assigned_pids == ()
    assert api.membership_checks == []


def test_the_handler_is_not_typed_on_oserror() -> None:
    """Regression guard for the exact defect an auditor caught in the first
    revision of this fix: the handler was written ``except OSError``, which
    NEVER fires on the real Win32 path because ``pywintypes.error`` is not an
    ``OSError`` subclass -- so the fix was inert in production while a fake
    that raised ``OSError`` made it look correct.

    Assert the production-shaped exception really is outside ``OSError``, so
    that if anyone re-narrows the handler to ``except OSError`` this file
    fails instead of silently going inert again."""

    exc = FakePywintypesError(5, "AssignProcessToJobObject", "Access is denied.")
    assert not isinstance(exc, OSError), (
        "the stand-in must NOT be an OSError, or it cannot detect an "
        "OSError-narrowed handler going inert"
    )

    api = InheritedMembershipApi(winerror=5, already_in_job=True)
    controller = JobObjectController(api=api)
    controller.assign_child(99)
    assert controller.assigned_pids == (99,)


# ---------------------------------------------------------------------------
# JobObjectController.containment_diagnostics -- fault-site forensics for the
# postgres reinstall ACCESS_DENIED loop (orphan-leak FINDING). The membership
# facts separate foreign-job inheritance from our own surviving job.
# ---------------------------------------------------------------------------


def test_containment_diagnostics_without_a_live_handle_reports_unknown() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)

    text = controller.containment_diagnostics(4242)

    assert "in_this_job=unknown" in text
    assert "named_job=" in text


def test_containment_diagnostics_reports_membership_and_named_job_members() -> None:
    existing = "surviving-job-handle"
    api = FakeJobObjectApi(existing_job=existing, existing_job_pids=[111, 222])
    controller = JobObjectController(api=api)
    controller.assign_child(111)

    text = controller.containment_diagnostics(4242)

    # The queried pid is NOT in this controller's job...
    assert "in_this_job=False" in text
    # ...and the named job's full membership is enumerated for the log.
    assert "named_job_member_pids=[111, 222]" in text
    # The reopened named-job handle is closed again -- no handle leak, and no
    # second live handle silently keeping a dead job's kill-on-close armed.
    assert existing in api.closed_handles


def test_containment_diagnostics_reports_in_this_job_true_for_a_member() -> None:
    api = FakeJobObjectApi()
    controller = JobObjectController(api=api)
    controller.assign_child(4242)

    text = controller.containment_diagnostics(4242)

    assert "in_this_job=True" in text


class _EveryQueryFaultsApi(FakeJobObjectApi):
    """Every forensic query raises the production-shaped (non-OSError)
    exception -- diagnostics must degrade to 'unqueryable', never raise."""

    def is_process_in_job(self, handle: object, pid: int) -> bool:
        raise FakePywintypesError(6, "IsProcessInJob", "The handle is invalid.")

    def open_existing_job(self, name: str) -> object | None:
        raise FakePywintypesError(5, "OpenJobObject", "Access is denied.")


def test_containment_diagnostics_never_raises_when_every_query_faults() -> None:
    """Forensics on a failure path must never make the failure worse. Every
    individually-faulting query degrades to an 'unqueryable' report."""

    api = _EveryQueryFaultsApi()
    controller = JobObjectController(api=api)
    controller.ensure_job()

    text = controller.containment_diagnostics(4242)  # must NOT raise

    assert "in_this_job=unqueryable" in text
    assert "unqueryable" in text


# ---------------------------------------------------------------------------
# CC-PG-JOB -- provenance-gated FOREIGN-job acceptance (2026-08-14). Field
# forensics (TESTER4, evidence tester4-kit-recovery-0132/10- and 11-): the
# postmaster lives in pg_ctl's OWN restricted-process job, so on a fast start
# the cross-job assign answers ACCESS_DENIED even on a clean SYSTEM/SCM start.
# Acceptance requires ALL of: the caller opted in (only the postmaster call
# site does), winerror==5, NOT in our job, and POSITIVELY in some job.
# ---------------------------------------------------------------------------


def test_assign_child_accepts_foreign_membership_only_with_opt_in_and_proof(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fix: ACCESS_DENIED + not-in-our-job + in-SOME-job + explicit opt-in
    -> accepted, tracked, and logged loudly with the forensics string.

    FALSIFICATION: against the pre-fix tree the call raises (the keyword does
    not exist), so this test cannot pass accidentally."""

    api = InheritedMembershipApi(winerror=5, already_in_job=False, in_any_job=True)
    controller = JobObjectController(api=api)

    with caplog.at_level(logging.WARNING, logger="civiccast.native.supervisor.job_object"):
        controller.assign_child(4242, accept_foreign_job_membership=True)

    assert controller.assigned_pids == (4242,)
    assert api.any_job_checks == [4242]
    messages = [r.getMessage() for r in caplog.records]
    assert any("accepting foreign-job membership for pid 4242" in m for m in messages)


def test_assign_child_without_opt_in_still_fails_closed_on_foreign_membership() -> None:
    """Negative control: the SAME foreign-membership condition without the
    opt-in keyword must still raise -- nats/control_plane/ollama keep the
    strict D3 assign."""

    api = InheritedMembershipApi(winerror=5, already_in_job=False, in_any_job=True)
    controller = JobObjectController(api=api)

    with pytest.raises(FakePywintypesError):
        controller.assign_child(4242)
    assert controller.assigned_pids == ()


def test_assign_child_opt_in_still_fails_closed_when_pid_is_in_no_job() -> None:
    """Negative control: ACCESS_DENIED with the pid in NO job is a genuine
    permission failure, not a membership collision -- the opt-in must NOT
    swallow it."""

    api = InheritedMembershipApi(winerror=5, already_in_job=False, in_any_job=False)
    controller = JobObjectController(api=api)

    with pytest.raises(FakePywintypesError):
        controller.assign_child(4242, accept_foreign_job_membership=True)
    assert controller.assigned_pids == ()


def test_assign_child_opt_in_still_fails_closed_on_other_winerrors() -> None:
    """Negative control: a non-ACCESS_DENIED fault (e.g. invalid handle, 6)
    must raise regardless of the opt-in."""

    api = InheritedMembershipApi(winerror=6, already_in_job=False, in_any_job=True)
    controller = JobObjectController(api=api)

    with pytest.raises(FakePywintypesError):
        controller.assign_child(4242, accept_foreign_job_membership=True)
    assert controller.assigned_pids == ()


def test_assign_child_opt_in_prefers_same_job_acceptance_over_foreign() -> None:
    """When the pid is already in THIS job, the original Aug-8 acceptance
    applies and the any-job probe is never consulted."""

    api = InheritedMembershipApi(winerror=5, already_in_job=True, in_any_job=True)
    controller = JobObjectController(api=api)

    controller.assign_child(4242, accept_foreign_job_membership=True)

    assert controller.assigned_pids == (4242,)
    assert api.any_job_checks == []
