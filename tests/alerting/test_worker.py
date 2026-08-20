# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 alerting maintenance worker tests (scheduler core)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from civiccast.alerting.resource_sampler import ResourceProbes
from civiccast.alerting.self_test import SelfTestDeps
from civiccast.alerting.store import get_alert_events, get_self_tests, recent_resource_samples
from civiccast.alerting.worker import AlertingMaintenanceSettings, AlertingMaintenanceWorker

# A Monday 02:00 (local-naive is fine for the schedule comparison; tz-aware here).
_MON_0200 = datetime(2026, 6, 15, 2, 0, 0, tzinfo=UTC)  # 2026-06-15 is a Monday
_SUN_0300 = datetime(2026, 6, 21, 3, 0, 0, tzinfo=UTC)  # the following Sunday


def _ok_probes() -> ResourceProbes:
    return ResourceProbes(
        cpu_percent=lambda: 20.0,
        ram=lambda: (4.0, 16.0),
        gpu=lambda: (None, None),
        media_free_gb=lambda: 500.0,
        backup_free_gb=lambda: 500.0,
        backup_writable=lambda: True,
        db_reachable=lambda: True,
        service_running=lambda: True,
        clock_skew_seconds=lambda: 0.0,
    )


def _ok_deps() -> SelfTestDeps:
    return SelfTestDeps(
        **{
            name: (lambda: True)
            for name in (
                "readiness",
                "filesink_continuity",
                "backup_probe",
                "model_ping",
                "restore_rehearsal",
                "srt_continuity",
                "tsduck_probe",
                "channel_test_send",
            )
        }
    )


class _CountingRetry:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self, now=None) -> int:
        self.ticks += 1
        return 0


@pytest.fixture
def factory(db_session: Session):
    @contextmanager
    def _f() -> Iterator[Session]:
        yield db_session

    return _f


def test_resource_sampling_respects_interval(factory) -> None:
    worker = AlertingMaintenanceWorker(
        factory,
        resource_probes=_ok_probes(),
        settings=AlertingMaintenanceSettings(resource_interval_seconds=60),
    )
    worker.tick(_MON_0200, monotonic=1000.0)  # first ever -> sample
    worker.tick(_MON_0200, monotonic=1030.0)  # +30s -> not due
    worker.tick(_MON_0200, monotonic=1061.0)  # +61s -> sample
    with factory() as session:  # read back
        samples = recent_resource_samples(session, window_minutes=1440, now=_MON_0200)
    assert len(samples) == 2


def test_no_probes_no_sampling(factory) -> None:
    worker = AlertingMaintenanceWorker(factory)
    worker.tick(_MON_0200, monotonic=1.0)  # no probes -> no-op, no crash


def test_daily_self_test_runs_once_per_day(factory, db_session: Session) -> None:
    worker = AlertingMaintenanceWorker(factory, self_test_deps=_ok_deps())
    worker.tick(_MON_0200, monotonic=1.0)
    worker.tick(_MON_0200 + timedelta(hours=6), monotonic=2.0)  # later same day -> no 2nd run
    daily = get_self_tests(db_session, kind="daily")
    assert len(daily) == 1
    # Next day after 02:00 -> runs again.
    worker.tick(_MON_0200 + timedelta(days=1), monotonic=3.0)
    assert len(get_self_tests(db_session, kind="daily")) == 2


def test_daily_not_run_before_scheduled_time(factory, db_session: Session) -> None:
    worker = AlertingMaintenanceWorker(factory, self_test_deps=_ok_deps())
    worker.tick(_MON_0200 - timedelta(minutes=1), monotonic=1.0)  # 01:59 -> too early
    assert get_self_tests(db_session, kind="daily") == []


def test_weekly_self_test_runs_on_sunday(factory, db_session: Session) -> None:
    worker = AlertingMaintenanceWorker(factory, self_test_deps=_ok_deps())
    worker.tick(_MON_0200, monotonic=1.0)  # Monday -> daily only, no weekly
    assert get_self_tests(db_session, kind="weekly") == []
    worker.tick(_SUN_0300, monotonic=2.0)  # Sunday 03:00 -> weekly
    assert len(get_self_tests(db_session, kind="weekly")) == 1
    worker.tick(_SUN_0300 + timedelta(hours=2), monotonic=3.0)  # same Sunday -> no 2nd
    assert len(get_self_tests(db_session, kind="weekly")) == 1


def test_no_self_test_deps_skips_self_tests(factory, db_session: Session) -> None:
    worker = AlertingMaintenanceWorker(factory)  # no deps
    worker.tick(_MON_0200, monotonic=1.0)
    assert get_self_tests(db_session) == []


def test_retry_worker_ticked_each_tick(factory) -> None:
    retry = _CountingRetry()
    worker = AlertingMaintenanceWorker(factory, retry_worker=retry)
    worker.tick(_MON_0200, monotonic=1.0)
    worker.tick(_MON_0200, monotonic=2.0)
    assert retry.ticks == 2


def test_failing_self_test_fires_alert(factory, db_session: Session) -> None:
    deps = _ok_deps()
    deps.readiness = lambda: False  # required check fails
    worker = AlertingMaintenanceWorker(factory, self_test_deps=deps)
    worker.tick(_MON_0200, monotonic=1.0)
    assert get_self_tests(db_session, kind="daily")[0].status == "fail"
    assert any(
        e.condition == "self-test-fail" for e in get_alert_events(db_session, state="firing")
    )


def test_availability_excludes_heavy_checks_from_scheduled_run(
    factory, db_session: Session
) -> None:
    # A daily run with a "filesink off" availability map records only the checks
    # that actually ran — the excluded heavy proof must not appear at all. (An
    # explicit availability dict is honored as a test override.)
    deps = _ok_deps()
    availability = {
        "readiness": True,
        "backup_probe": True,
        "model_ping": True,
        "filesink_continuity": False,
    }
    worker = AlertingMaintenanceWorker(
        factory, self_test_deps=deps, self_test_availability=availability
    )
    worker.tick(_MON_0200, monotonic=1.0)
    recorded = get_self_tests(db_session, kind="daily")[0].checks
    assert "filesink_continuity" not in recorded  # honest not-run, not a fake pass/fail
    assert recorded.get("readiness") is True


def test_scheduled_run_recomputes_availability_each_run(
    factory, db_session: Session, monkeypatch
) -> None:
    # M1: with NO availability override, the worker recomputes availability per
    # scheduled run — a check enabled mid-session (e.g. after the operator adds a
    # channel / installs TSDuck) must start appearing WITHOUT a restart.
    import civiccast.alerting.worker as wk

    calls = {"n": 0}

    def fake_avail(*, session_factory=None):
        calls["n"] += 1
        return {
            "readiness": True,
            "backup_probe": True,
            "model_ping": True,
            "filesink_continuity": calls["n"] >= 2,  # unavailable run 1, available run 2
            "restore_rehearsal": False,
            "srt_continuity": False,
            "tsduck_probe": False,
            "channel_test_send": False,
        }

    monkeypatch.setattr(wk, "default_self_test_availability", fake_avail)
    worker = AlertingMaintenanceWorker(factory, self_test_deps=_ok_deps())  # no frozen dict
    worker.tick(_MON_0200, monotonic=1.0)  # daily run 1
    assert "filesink_continuity" not in get_self_tests(db_session, kind="daily")[0].checks
    worker.tick(_MON_0200 + timedelta(days=1), monotonic=2.0)  # daily run 2, next day
    assert "filesink_continuity" in get_self_tests(db_session, kind="daily")[0].checks
    assert calls["n"] >= 2  # recomputed per run, not snapshotted at construction
