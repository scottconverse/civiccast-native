# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure control-logic tests for ``civiccast.platform.child_containment`` (U31)
and for the app-level guard that engages it.

No Win32 here: ``FakeContainmentApi`` never imports ``win32job``/``win32api``,
so this file runs on any OS. It proves the CONTROL LOGIC -- what status a
success/failure produces, whether the handle is retained on success and closed
on failure, that the result is latched, and that the guard never engages in an
unsupervised process -- independently of the real Win32 calls, which
``test_child_containment_win.py`` exercises with real processes and a real
``TerminateProcess``.

The failure cases matter as much as the success one. ``active=False`` is the
state that leaves relay ffmpegs orphaned holding their UDP ports (the 2026-09-25
station incident), and the caller only logs it at ERROR because the status
carries the reason -- so a regression that reported ``active=True`` without
``IsProcessInJob`` confirming membership would silently disarm the whole
mechanism.
"""

from __future__ import annotations

import logging

import pytest

import civiccast.app as app_module
import civiccast.platform.child_containment as cc
from civiccast.app import _CONTROL_PLANE_SUPERVISED_ENV_VAR
from civiccast.native.supervisor.children import CIVICCAST_SUPERVISED_ENV_VAR
from civiccast.platform.child_containment import (
    ContainmentStatus,
    contain_own_descendants,
)


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The latch and the retained-handle list are process globals; give every
    test a fresh pair so neither order nor a real job handle leaks across."""

    monkeypatch.setattr(cc, "_STATUS", None)
    monkeypatch.setattr(cc, "_RETAINED_HANDLES", [])


class FakeContainmentApi:
    """Records every call instead of touching Win32. ``create_error`` and
    ``assign_error`` inject the two fault paths; ``in_job`` seeds what
    ``IsProcessInJob`` answers."""

    def __init__(
        self,
        *,
        is_windows: bool = True,
        create_error: Exception | None = None,
        assign_error: Exception | None = None,
        in_job: bool = True,
    ) -> None:
        self._is_windows = is_windows
        self._create_error = create_error
        self._assign_error = assign_error
        self._in_job = in_job
        self.created = 0
        self.assigned: list[object] = []
        self.membership_queries: list[object] = []
        self.closed: list[object] = []

    def is_windows(self) -> bool:
        return self._is_windows

    def create_kill_on_job_close_job(self) -> object:
        self.created += 1
        if self._create_error is not None:
            raise self._create_error
        return f"fake-job-handle-{self.created}"

    def assign_current_process(self, job: object) -> None:
        self.assigned.append(job)
        if self._assign_error is not None:
            raise self._assign_error

    def current_process_in_job(self, job: object) -> bool:
        self.membership_queries.append(job)
        return self._in_job

    def close_handle(self, handle: object) -> None:
        self.closed.append(handle)


# ---------------------------------------------------------------------------
# The two constants that must agree, forever
# ---------------------------------------------------------------------------


def test_supervised_env_var_constants_agree() -> None:
    """``civiccast.app`` duplicates the supervisor's env-var constant instead
    of importing it. If they drift, the containment guard silently never fires
    -- the exact failure that masked this unit's first red-green attempt (the
    helper set ``CIVICAST_SUPERVISED``, the product read
    ``CIVICCAST_SUPERVISED``, and containment was never established)."""

    assert _CONTROL_PLANE_SUPERVISED_ENV_VAR == CIVICCAST_SUPERVISED_ENV_VAR
    assert _CONTROL_PLANE_SUPERVISED_ENV_VAR == "CIVICCAST_SUPERVISED"


# ---------------------------------------------------------------------------
# contain_own_descendants -- the control logic (fake api seam)
# ---------------------------------------------------------------------------


def test_non_windows_is_inactive_and_creates_no_job() -> None:
    api = FakeContainmentApi(is_windows=False)
    status = contain_own_descendants(api=api)

    assert status.active is False
    assert "not Windows" in status.detail
    assert api.created == 0, "a non-Windows host must not even attempt a job"


def test_create_failure_is_inactive_and_reports_the_fault() -> None:
    api = FakeContainmentApi(create_error=RuntimeError("boom"))
    status = contain_own_descendants(api=api)

    assert status.active is False
    assert "CreateJobObject/SetInformationJobObject failed" in status.detail
    assert "boom" in status.detail
    assert api.assigned == [], "nothing to assign to when the job never existed"


def test_assign_failure_is_inactive_and_closes_the_handle() -> None:
    api = FakeContainmentApi(assign_error=RuntimeError("winerror=5"))
    status = contain_own_descendants(api=api)

    assert status.active is False
    assert "AssignProcessToJobObject failed" in status.detail
    assert "winerror=5" in status.detail
    assert api.closed == ["fake-job-handle-1"], (
        "a job handle left open on the failure path would keep a kill-on-close "
        "job alive for a containment that was never established"
    )
    assert cc._RETAINED_HANDLES == []


def test_unconfirmed_membership_is_inactive_and_closes_the_handle() -> None:
    """Assignment reported no error but ``IsProcessInJob`` says otherwise: the
    status must NOT claim a guarantee the membership check just contradicted."""

    api = FakeContainmentApi(in_job=False)
    status = contain_own_descendants(api=api)

    assert status.active is False
    assert "IsProcessInJob reports the control plane is not in the new job" in status.detail
    assert api.membership_queries == ["fake-job-handle-1"]
    assert api.closed == ["fake-job-handle-1"]
    assert cc._RETAINED_HANDLES == []


def test_success_is_active_and_retains_the_handle() -> None:
    api = FakeContainmentApi()
    status = contain_own_descendants(api=api)

    assert status.active is True
    assert "anonymous kill-on-close job" in status.detail
    assert api.assigned == ["fake-job-handle-1"]
    assert api.closed == [], (
        "the job handle must stay open for this process's lifetime -- closing "
        "the last handle to a kill-on-close job containing this process would "
        "kill this process"
    )
    assert cc._RETAINED_HANDLES == ["fake-job-handle-1"], (
        "the handle must be referenced or pywin32 will garbage-collect (and "
        "close) it, which is the same bug in a different disguise"
    )


def test_the_result_is_latched_so_a_second_call_does_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call per process: the second call must not create a second job --
    and must not consult the api at all."""

    api = FakeContainmentApi()
    calls: list[int] = []

    def _api_factory() -> FakeContainmentApi:
        calls.append(1)
        return api

    monkeypatch.setattr(cc, "_default_api", _api_factory)
    first = contain_own_descendants()
    second = contain_own_descendants()

    assert first == second
    assert first.active is True
    assert calls == [1], "the api was consulted twice -- the latch did not hold"
    assert api.created == 1


def test_a_latched_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure latches too: a station that could not be contained must not
    re-attempt on every call."""

    api = FakeContainmentApi(create_error=RuntimeError("boom"))
    monkeypatch.setattr(cc, "_default_api", lambda: api)

    first = contain_own_descendants()
    second = contain_own_descendants()

    assert first == second
    assert first.active is False
    assert api.created == 1


def test_the_api_seam_does_not_latch_the_process_global_status() -> None:
    """``api=`` is a test-only seam. It must not leave a status behind that a
    production caller would read as this process's real containment."""

    assert cc.containment_status() is None
    contain_own_descendants(api=FakeContainmentApi())
    assert cc.containment_status() is None


# ---------------------------------------------------------------------------
# civiccast.app._maybe_contain_own_descendants -- the guard
# ---------------------------------------------------------------------------


def test_guard_does_not_engage_when_unsupervised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``uvicorn`` dev run, a unit test, or any other unsupervised
    ``create_app()`` caller must NOT put itself in a kill-on-close job."""

    monkeypatch.delenv(_CONTROL_PLANE_SUPERVISED_ENV_VAR, raising=False)
    monkeypatch.setattr(app_module, "_descendants_contained", False)
    called: list[int] = []

    def _spy() -> ContainmentStatus:
        called.append(1)
        return ContainmentStatus(active=True, detail="spy")

    monkeypatch.setattr(cc, "contain_own_descendants", _spy)
    app_module._maybe_contain_own_descendants()

    assert called == []
    assert app_module._descendants_contained is False


def test_guard_engages_and_logs_active_at_info(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_CONTROL_PLANE_SUPERVISED_ENV_VAR, "1")
    monkeypatch.setattr(app_module, "_descendants_contained", False)
    monkeypatch.setattr(
        cc,
        "contain_own_descendants",
        lambda: ContainmentStatus(active=True, detail="latched: fake"),
    )

    with caplog.at_level(logging.INFO, logger="civiccast.app"):
        app_module._maybe_contain_own_descendants()
        # Second call: the latch means the api is not consulted again.
        app_module._maybe_contain_own_descendants()

    assert app_module._descendants_contained is True
    assert "control-plane containment active: latched: fake" in caplog.text
    assert [r.levelno for r in caplog.records] == [logging.INFO]


def test_guard_logs_an_inactive_containment_at_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The degradation must be findable in the log: an operator whose station
    is running uncontained has to be able to see why."""

    monkeypatch.setenv(_CONTROL_PLANE_SUPERVISED_ENV_VAR, "1")
    monkeypatch.setattr(app_module, "_descendants_contained", False)
    monkeypatch.setattr(
        cc,
        "contain_own_descendants",
        lambda: ContainmentStatus(active=False, detail="not Windows"),
    )

    with caplog.at_level(logging.INFO, logger="civiccast.app"):
        app_module._maybe_contain_own_descendants()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "control-plane containment INACTIVE (not Windows)" in caplog.text
    assert "U31 orphan defect" in caplog.text
    assert app_module._descendants_contained is False, (
        "an inactive containment must not latch as contained -- the next call "
        "would then be a silent no-op and the ERROR would never be re-logged"
    )
