# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-3 AlertEvaluator — condition derivation, dedupe, quiet-hours, resolve."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from civiccast.alerting.evaluator import (
    AlertEvaluator,
    _in_quiet_window,
    _window_end_dt,
    derive_channel_conditions,
)
from civiccast.alerting.models import AlertChannel, AlertRule
from civiccast.alerting.store import (
    get_alert_events,
    get_event_deliveries,
    upsert_alert_channel,
    upsert_alert_rule,
)

_NOW = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)  # 10:00 UTC, outside quiet hours
_IN_QUIET = datetime(2026, 6, 15, 23, 30, 0, tzinfo=UTC)  # 23:30 - inside 22:00-07:00


# ---------------------------------------------------------------------------
# Session factory for the evaluator (uses same db_session fixture)
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(db_session: Session):
    """Return a session factory that reuses the test session (no separate TX)."""

    @contextmanager
    def factory() -> Iterator[Session]:
        yield db_session
        # Don't commit — the test fixture owns the session lifecycle.
        # We manually call session.flush() inside the evaluator already.

    return factory


@pytest.fixture()
def dispatched() -> list[tuple[str, str, str, str, str]]:
    return []


@pytest.fixture()
def evaluator(session_factory, dispatched):
    calls = dispatched

    def dispatch_hook(event_id, delivery_id, channel_id, kind, label):
        calls.append((event_id, delivery_id, channel_id, kind, label))

    return AlertEvaluator(session_factory, dispatch=dispatch_hook)


def _make_rule(session: Session, condition: str, severity: str = "critical", **kwargs) -> AlertRule:
    rule = AlertRule(
        rule_id=f"default:{condition}",
        condition=condition,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        channel_ids=[],
        updated_at=_NOW,
        updated_by="test",
        **kwargs,
    )
    return upsert_alert_rule(session, rule)


def _make_channel(session: Session, channel_id: str = "ch-1") -> AlertChannel:
    ch = AlertChannel(
        channel_id=channel_id,
        kind="email",
        label="Test email",
        target_redacted="test@***",
        created_at=_NOW,
    )
    return upsert_alert_channel(session, ch)


# ---------------------------------------------------------------------------
# derive_channel_conditions — pure function tests
# ---------------------------------------------------------------------------


class TestDeriveChannelConditions:
    def test_stopped_triggers_off_air(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "STOPPED", encoder_fps=None, encoder_bitrate_kbps=None
        )
        kinds = [k for k, _ in conds]
        assert "off-air" in kinds

    def test_error_triggers_off_air(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "ERROR", encoder_fps=None, encoder_bitrate_kbps=None
        )
        kinds = [k for k, _ in conds]
        assert "off-air" in kinds

    def test_on_air_healthy_no_conditions(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "ON_AIR", encoder_fps=29.97, encoder_bitrate_kbps=8000.0
        )
        assert conds == []

    def test_on_air_fps_zero_triggers_encoder_death(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "ON_AIR", encoder_fps=0.0, encoder_bitrate_kbps=0.0
        )
        kinds = [k for k, _ in conds]
        assert "encoder-death" in kinds

    def test_qa_004_fallback_slate_fps_zero_no_encoder_death(self) -> None:
        """QA-004 regression: FALLBACK_SLATE + fps=0 must NOT fire encoder-death."""
        conds = derive_channel_conditions(
            "ch1", "FALLBACK_SLATE", encoder_fps=0.0, encoder_bitrate_kbps=0.0
        )
        kinds = [k for k, _ in conds]
        assert "encoder-death" not in kinds
        assert "off-air" not in kinds

    def test_starting_state_no_conditions(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "STARTING", encoder_fps=None, encoder_bitrate_kbps=None
        )
        assert conds == []

    def test_transitioning_state_no_conditions(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "TRANSITIONING", encoder_fps=None, encoder_bitrate_kbps=None
        )
        assert conds == []

    def test_on_air_fps_zero_only_triggers_encoder_death_not_off_air(self) -> None:
        conds = derive_channel_conditions(
            "ch1", "ON_AIR", encoder_fps=0.0, encoder_bitrate_kbps=None
        )
        kinds = [k for k, _ in conds]
        assert "encoder-death" in kinds
        assert "off-air" not in kinds

    def test_stopped_no_encoder_death(self) -> None:
        # STOPPED + fps=None — only off-air, not encoder-death.
        conds = derive_channel_conditions(
            "ch1", "STOPPED", encoder_fps=None, encoder_bitrate_kbps=None
        )
        kinds = [k for k, _ in conds]
        assert "encoder-death" not in kinds


# ---------------------------------------------------------------------------
# Quiet-hours helpers
# ---------------------------------------------------------------------------


class TestQuietHours:
    def test_same_day_window_inside(self) -> None:
        # 22:00-23:00 -> 22:30 is inside
        assert _in_quiet_window((22, 30), "22:00", "23:00") is True

    def test_same_day_window_outside(self) -> None:
        assert _in_quiet_window((21, 59), "22:00", "23:00") is False

    def test_overnight_window_inside_after_start(self) -> None:
        # 22:00-07:00, now=23:00 -> inside
        assert _in_quiet_window((23, 0), "22:00", "07:00") is True

    def test_overnight_window_inside_before_end(self) -> None:
        # 22:00-07:00, now=06:00 -> inside
        assert _in_quiet_window((6, 0), "22:00", "07:00") is True

    def test_overnight_window_outside_middle_of_day(self) -> None:
        # 22:00-07:00, now=10:00 -> outside
        assert _in_quiet_window((10, 0), "22:00", "07:00") is False

    def test_window_end_same_day(self) -> None:
        now = datetime(2026, 6, 15, 8, 0, 0, tzinfo=UTC)  # 08:00
        end = _window_end_dt(now, "09:00")
        assert end == datetime(2026, 6, 15, 9, 0, 0, tzinfo=UTC)

    def test_window_end_next_day(self) -> None:
        now = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)  # after 09:00
        end = _window_end_dt(now, "09:00")
        assert end == datetime(2026, 6, 16, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# AlertEvaluator — evaluation lifecycle
# ---------------------------------------------------------------------------


class TestEvaluatorDedupeAndDispatch:
    def test_first_off_air_creates_event_no_dispatch_no_channels(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_rule(db_session, "off-air")
        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        events = get_alert_events(db_session, state="firing")
        assert len(events) == 1
        assert events[0].condition == "off-air"
        assert events[0].occurrence_count == 1
        # No channel_ids configured on the rule → no dispatch call
        assert dispatched == []

    def test_first_off_air_with_channel_dispatches(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        assert len(dispatched) == 1
        assert dispatched[0][3] == "off-air"

    def test_repeated_off_air_bumps_count_no_extra_dispatch(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            re_alert_after_seconds=3600,
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        # First call: fires and dispatches
        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        assert len(dispatched) == 1

        # Second call within re_alert window: no new dispatch
        second_time = _NOW + timedelta(seconds=60)
        evaluator.evaluate_channel("ch1", "STOPPED", now=second_time)
        assert len(dispatched) == 1  # still just one

        events = get_alert_events(db_session, state="firing")
        assert len(events) == 1
        assert events[0].occurrence_count == 2

    def test_re_alert_after_window_fires_again(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            re_alert_after_seconds=300,
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        assert len(dispatched) == 1

        # After re_alert_after_seconds elapses, re-alert fires
        after_window = _NOW + timedelta(seconds=301)
        evaluator.evaluate_channel("ch1", "STOPPED", now=after_window)
        assert len(dispatched) == 2

    def test_one_shot_no_re_alert(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:server-crash",
            condition="server-crash",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            re_alert_after_seconds=0,  # one-shot
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_server_crash("ch1", now=_NOW)
        assert len(dispatched) == 1

        # Calling again (e.g. reboot in quick succession) should not re-alert
        evaluator.evaluate_server_crash("ch1", now=_NOW + timedelta(minutes=5))
        assert len(dispatched) == 1  # still just one

    def test_resolve_clears_event_and_dispatches_resolve(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            notify_on_resolve=True,
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        assert len(dispatched) == 1

        # Channel comes back on air
        recovery_time = _NOW + timedelta(minutes=5)
        evaluator.evaluate_channel(
            "ch1", "ON_AIR", encoder_fps=29.97, encoder_bitrate_kbps=8000.0, now=recovery_time
        )
        assert len(dispatched) == 2  # resolve notification

        resolved_events = get_alert_events(db_session, state="resolved")
        assert len(resolved_events) == 1

    def test_resolve_no_notify_no_dispatch(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-1"],
            notify_on_resolve=False,
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)
        assert len(dispatched) == 1

        evaluator.evaluate_channel(
            "ch1", "ON_AIR", encoder_fps=29.97, now=_NOW + timedelta(minutes=5)
        )
        # No resolve dispatch because notify_on_resolve=False
        assert len(dispatched) == 1


class TestEvaluatorQuietHours:
    def test_critical_bypasses_quiet_hours(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        ch = AlertChannel(
            channel_id="ch-email",
            kind="email",
            label="Email",
            target_redacted="ops@***",
            quiet_hours_start_utc="22:00",
            quiet_hours_end_utc="07:00",
            created_at=_NOW,
        )
        upsert_alert_channel(db_session, ch)
        rule = AlertRule(
            rule_id="default:off-air",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            channel_ids=["ch-email"],
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        # Trigger during quiet hours (23:30 UTC, inside 22:00-07:00 window)
        evaluator.evaluate_channel("ch1", "STOPPED", now=_IN_QUIET)
        assert len(dispatched) == 1  # critical always fires

    def test_warning_suppressed_during_quiet_hours(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        ch = AlertChannel(
            channel_id="ch-email",
            kind="email",
            label="Email",
            target_redacted="ops@***",
            quiet_hours_start_utc="22:00",
            quiet_hours_end_utc="07:00",
            created_at=_NOW,
        )
        upsert_alert_channel(db_session, ch)
        rule = AlertRule(
            rule_id="default:encoder-death",
            condition="encoder-death",  # type: ignore[arg-type]
            severity="warning",
            channel_ids=["ch-email"],
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)

        evaluator.evaluate_channel("ch1", "ON_AIR", encoder_fps=0.0, now=_IN_QUIET)
        assert len(dispatched) == 0  # suppressed
        deliveries = get_event_deliveries(db_session, get_alert_events(db_session)[0].event_id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "suppressed"
        assert deliveries[0].next_attempt_at is not None


class TestEvaluatorQA004Regression:
    """QA-004: FALLBACK_SLATE + fps=0 must not trigger encoder-death."""

    def test_fallback_slate_no_encoder_death_alert(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_rule(db_session, "encoder-death")
        _make_rule(db_session, "off-air")
        evaluator.evaluate_channel(
            "ch1", "FALLBACK_SLATE", encoder_fps=0.0, encoder_bitrate_kbps=0.0, now=_NOW
        )
        events = get_alert_events(db_session)
        # No alerts should have been created at all
        assert events == []
        assert dispatched == []

    def test_on_air_stalled_triggers_encoder_death(
        self, db_session: Session, evaluator: AlertEvaluator, dispatched: list
    ) -> None:
        _make_channel(db_session)
        rule = AlertRule(
            rule_id="default:encoder-death",
            condition="encoder-death",  # type: ignore[arg-type]
            severity="warning",
            channel_ids=["ch-1"],
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, rule)
        evaluator.evaluate_channel(
            "ch1", "ON_AIR", encoder_fps=0.0, encoder_bitrate_kbps=0.0, now=_NOW
        )
        events = get_alert_events(db_session, state="firing")
        assert len(events) == 1
        assert events[0].condition == "encoder-death"
        assert len(dispatched) == 1
