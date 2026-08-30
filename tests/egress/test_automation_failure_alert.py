# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""DEFECT C: a failed channel-automation pass must be visible to an operator.

Found live alongside DEFECT A: the hls-sink crash inside a channel's
automation pass was recorded ONLY as a log line ("Channel automation pass
failed for %s") — no operator would ever see it. These tests prove the
fix lands a real, readable alert through the existing alerting hub (no new
UI surface, per the task) and that it clears again once the channel is
healthy — not that a mock got called.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

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
from civiccast.egress.automation import (
    ChannelAutomationService,
    ChannelAutomationSettings,
    _ChannelAutomationAlerts,
)
from civiccast.egress.models import CanonicalProfile, EgressCommand, EgressConfig, EgressSinkSpec
from civiccast.egress.store import InMemoryEgressStore

_NOW = datetime(2026, 6, 12, 6, 0, tzinfo=UTC)


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


def _config(channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _firing_events(session_factory: object) -> list:
    with session_factory() as session:  # type: ignore[operator]
        return get_alert_events(session, state="firing")


class _FakeDaemon:
    """process_once raises for one poll, then succeeds, driven by ``should_fail``."""

    def __init__(self) -> None:
        self.should_fail = True

    def has_live_process(self, channel_id: str) -> bool:
        return True  # skip the auto_start branch; only process_once matters here

    def process_once(self, channel_id: str) -> int:
        if self.should_fail:
            raise RuntimeError("simulated channel automation crash")
        return 0


class TestChannelAutomationAlertsUnit:
    """Direct unit coverage of the alert-firing/clearing state machine."""

    def test_pass_failure_creates_a_firing_alert_naming_the_channel(
        self, session_factory: object
    ) -> None:
        alerts = _ChannelAutomationAlerts(session_factory)
        alerts.begin_tick("gov")
        alerts.on_pass_failure("gov", detail="RuntimeError: boom")

        firing = _firing_events(session_factory)
        assert len(firing) == 1
        assert firing[0].condition == "channel-automation-failure"
        assert firing[0].resource_ref == "egress-channel:gov"
        assert "gov" in firing[0].summary
        assert "boom" in firing[0].detail

    def test_command_failure_creates_a_firing_alert_naming_the_command(
        self, session_factory: object
    ) -> None:
        alerts = _ChannelAutomationAlerts(session_factory)
        command = EgressCommand(
            channel_id="gov",
            action="start",
            issued_at=_NOW,
            issued_by="operator",
            command_id="egress-abc123",
        )
        alerts.begin_tick("gov")
        alerts.on_command_failure("gov", command, ValueError("unknown sink kind: hls"))

        firing = _firing_events(session_factory)
        assert len(firing) == 1
        assert "start" in firing[0].summary
        assert "egress-abc123" in firing[0].detail
        assert "unknown sink kind" in firing[0].detail

    def test_end_tick_clears_the_alert_after_a_clean_pass(self, session_factory: object) -> None:
        alerts = _ChannelAutomationAlerts(session_factory)
        alerts.begin_tick("gov")
        alerts.on_pass_failure("gov", detail="boom")
        assert len(_firing_events(session_factory)) == 1

        alerts.begin_tick("gov")  # next poll tick: no failure recorded this time
        alerts.end_tick("gov")

        assert _firing_events(session_factory) == []

    def test_end_tick_is_a_no_op_when_nothing_was_firing(self, session_factory: object) -> None:
        """Guards against a resolved-event-per-tick churn: calling end_tick on
        a channel with no firing alert must write nothing (S9's proof-event
        churn discipline applies to alert events too)."""
        alerts = _ChannelAutomationAlerts(session_factory)
        alerts.begin_tick("gov")
        alerts.end_tick("gov")
        alerts.begin_tick("gov")
        alerts.end_tick("gov")

        with session_factory() as session:  # type: ignore[operator]
            all_events = get_alert_events(session)
        assert all_events == []

    def test_a_command_failure_in_the_same_tick_blocks_the_pass_level_clear(
        self, session_factory: object
    ) -> None:
        """If a command failed THIS tick, the pass itself finishing without
        raising must not clear the alert -- the channel is not actually
        healthy just because process_once's outer call didn't propagate."""
        alerts = _ChannelAutomationAlerts(session_factory)
        command = EgressCommand(
            channel_id="gov",
            action="stop",
            issued_at=_NOW,
            issued_by="operator",
            command_id="egress-def456",
        )
        alerts.begin_tick("gov")
        alerts.on_command_failure("gov", command, RuntimeError("boom"))
        alerts.end_tick("gov")  # same tick as the command failure

        assert len(_firing_events(session_factory)) == 1


class TestRunOnceIntegration:
    """ChannelAutomationService.run_once wired to a real alerts instance."""

    def test_a_failed_pass_is_visible_and_clears_on_recovery(
        self, session_factory: object
    ) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        daemon = _FakeDaemon()
        alerts = _ChannelAutomationAlerts(session_factory)
        service = ChannelAutomationService(
            store,
            daemon,
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            automation_alerts=alerts,
        )

        service.run_once(now=_NOW)
        firing = _firing_events(session_factory)
        assert len(firing) == 1
        assert firing[0].resource_ref == "egress-channel:gov"

        daemon.should_fail = False
        service.run_once(now=_NOW)
        assert _firing_events(session_factory) == []

    def test_automation_alerts_is_optional(self, session_factory: object) -> None:
        """A service built without automation_alerts (as most existing tests
        already construct it) must not raise just because a pass failed."""
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        daemon = _FakeDaemon()
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )

        seen = service.run_once(now=_NOW)  # must not raise
        assert seen == ["gov"]
