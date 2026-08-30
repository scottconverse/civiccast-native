# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5: build_channel_automation threads the alert evaluator hook to the daemon."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.alerting.models
import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.alerting.store import get_alert_events
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.automation import _raise_egress_degraded_alert, build_channel_automation
from civiccast.egress.hls_relay import HlsRelaySupervisor


@pytest.fixture
def session_factory() -> Iterator[object]:
    eng: Engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(eng)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield factory
    finally:
        reset_engine()
        eng.dispose()


def test_hook_is_threaded_to_the_daemon(session_factory, tmp_path) -> None:
    calls: list[tuple] = []

    def hook(channel_id, state, fps, bitrate) -> None:
        calls.append((channel_id, state, fps, bitrate))

    svc = build_channel_automation(session_factory, work_dir=tmp_path, alert_evaluator_hook=hook)
    assert svc._daemon._alert_evaluator_hook is hook


def test_default_hook_is_none(session_factory, tmp_path) -> None:
    svc = build_channel_automation(session_factory, work_dir=tmp_path)
    assert svc._daemon._alert_evaluator_hook is None


def test_hls_relay_supervisor_is_wired_to_the_daemon(session_factory, tmp_path) -> None:
    """DEFECT A: build_channel_automation is the ONE production wiring site
    for the daemon (mirrors ts_relay_supervisor's own single wiring site) —
    without this, hls sinks would keep crashing in the real app even though
    the bridge/relay code itself is correct."""
    svc = build_channel_automation(session_factory, work_dir=tmp_path)
    assert isinstance(svc._daemon._hls_relay, HlsRelaySupervisor)


def test_command_failure_hook_and_automation_alerts_are_wired(session_factory, tmp_path) -> None:
    """DEFECT C/D: the daemon's per-command failure hook and the service's
    whole-pass alerting must be the SAME shared instance (see
    _ChannelAutomationAlerts's docstring) — not two independently-firing
    trackers that could disagree about whether a channel recovered."""
    svc = build_channel_automation(session_factory, work_dir=tmp_path)
    assert svc._alerts is not None
    assert svc._daemon._command_failure_hook == svc._alerts.on_command_failure


def test_egress_degraded_alert_is_actually_recorded(session_factory) -> None:
    """Regression: session_factory is a @contextmanager callable in
    production (civiccast.app._wire_stage_f_workers's _session_factory) —
    this alert used to reach for session.commit()/.close() directly on the
    _GeneratorContextManager that returns, raising AttributeError every
    single time, silently swallowed by the surrounding except Exception.
    The alert has therefore never actually been recorded in production
    until this fix. Exercised directly (not through build_channel_automation,
    whose degraded-alert call site is gated on an env var this test does not
    need to set) so a regression here fails loudly instead of silently again."""
    _raise_egress_degraded_alert(session_factory, reason="closure verify failed: missing bytes")

    with session_factory() as session:
        firing = get_alert_events(session, state="firing")
    assert len(firing) == 1
    assert firing[0].condition == "encoder-death"
    assert firing[0].resource_ref == "station:egress-engine"
    assert "closure verify failed" in firing[0].detail
