# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Store CRUD and record_alert_condition hub tests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from civiccast.alerting.models import (
    AlertChannel,
    AlertEventDelivery,
    AlertRule,
    SystemResourceSample,
    SystemSelfTest,
)
from civiccast.alerting.store import (
    acknowledge_alert_event,
    append_resource_sample,
    delete_alert_channel,
    get_alert_channel,
    get_alert_channels,
    get_alert_event,
    get_alert_events,
    get_event_deliveries,
    get_self_tests,
    recent_resource_samples,
    record_alert_condition,
    upsert_alert_channel,
    upsert_alert_rule,
    upsert_event_delivery,
    upsert_self_test,
)

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 15, 12, 5, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    db_session: Session,
    condition: str = "off-air",
    severity: str = "critical",
    rule_id: str | None = None,
) -> AlertRule:
    rule = AlertRule(
        rule_id=rule_id or f"default:{condition}",
        condition=condition,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        channel_ids=[],
        updated_at=_NOW,
        updated_by="test",
    )
    return upsert_alert_rule(db_session, rule)


def _make_channel(
    db_session: Session, channel_id: str = "ch-1", kind: str = "email"
) -> AlertChannel:
    ch = AlertChannel(
        channel_id=channel_id,
        kind=kind,  # type: ignore[arg-type]
        label=f"Test {kind}",
        target_redacted="test@***",
        created_at=_NOW,
    )
    return upsert_alert_channel(db_session, ch)


# ---------------------------------------------------------------------------
# AlertRule CRUD
# ---------------------------------------------------------------------------


class TestAlertRuleCrud:
    def test_upsert_and_get_rule(self, db_session: Session) -> None:
        rule = _make_rule(db_session)
        fetched = get_alert_channel(db_session, rule.rule_id)
        # get_alert_channel targets channels; use the store directly.
        from civiccast.alerting.store import get_alert_rule

        fetched = get_alert_rule(db_session, "default:off-air")
        assert fetched is not None
        assert fetched.condition == "off-air"
        assert fetched.severity == "critical"

    def test_upsert_updates_existing_rule(self, db_session: Session) -> None:
        _make_rule(db_session, severity="critical")
        updated = AlertRule(
            rule_id="default:off-air",
            condition="off-air",
            severity="warning",  # changed
            channel_ids=["ch-1"],
            updated_at=_LATER,
            updated_by="operator",
        )
        upsert_alert_rule(db_session, updated)
        from civiccast.alerting.store import get_alert_rule

        fetched = get_alert_rule(db_session, "default:off-air")
        assert fetched is not None
        assert fetched.severity == "warning"
        assert fetched.channel_ids == ["ch-1"]


# ---------------------------------------------------------------------------
# AlertChannel CRUD
# ---------------------------------------------------------------------------


class TestAlertChannelCrud:
    def test_upsert_and_get_channel(self, db_session: Session) -> None:
        _make_channel(db_session)
        fetched = get_alert_channel(db_session, "ch-1")
        assert fetched is not None
        assert fetched.kind == "email"

    def test_list_channels(self, db_session: Session) -> None:
        _make_channel(db_session, "ch-1", "email")
        _make_channel(db_session, "ch-2", "sms")
        channels = get_alert_channels(db_session)
        assert len(channels) == 2
        kinds = {c.kind for c in channels}
        assert kinds == {"email", "sms"}

    def test_delete_channel(self, db_session: Session) -> None:
        _make_channel(db_session)
        result = delete_alert_channel(db_session, "ch-1")
        assert result is True
        assert get_alert_channel(db_session, "ch-1") is None

    def test_delete_nonexistent_channel_returns_false(self, db_session: Session) -> None:
        result = delete_alert_channel(db_session, "does-not-exist")
        assert result is False

    def test_upsert_updates_existing_channel(self, db_session: Session) -> None:
        _make_channel(db_session, "ch-1", "email")
        updated = AlertChannel(
            channel_id="ch-1",
            kind="email",
            label="Updated label",
            target_redacted="new@***",
            enabled=False,
            created_at=_NOW,
        )
        upsert_alert_channel(db_session, updated)
        fetched = get_alert_channel(db_session, "ch-1")
        assert fetched is not None
        assert fetched.label == "Updated label"
        assert fetched.enabled is False


# ---------------------------------------------------------------------------
# record_alert_condition — the hub
# ---------------------------------------------------------------------------


class TestRecordAlertCondition:
    def test_first_call_creates_firing_event(self, db_session: Session) -> None:
        _make_rule(db_session, "encoder-death", "critical")
        event = record_alert_condition(
            db_session,
            kind="encoder-death",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Encoder died",
            observed_at=_NOW,
        )
        assert event.state == "firing"
        assert event.condition == "encoder-death"
        assert event.resource_ref == "gov-ch12"
        assert event.occurrence_count == 1
        assert event.rule_id == "default:encoder-death"
        assert event.severity == "critical"

    def test_second_call_same_pair_bumps_count(self, db_session: Session) -> None:
        _make_rule(db_session, "encoder-death", "critical")
        first = record_alert_condition(
            db_session,
            kind="encoder-death",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Encoder died",
            observed_at=_NOW,
        )
        second = record_alert_condition(
            db_session,
            kind="encoder-death",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Still dead",
            observed_at=_LATER,
        )
        assert second.event_id == first.event_id  # same event
        assert second.occurrence_count == 2
        assert second.last_observed_at == _LATER

    def test_repeated_calls_keep_single_firing_event(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        for i in range(10):
            record_alert_condition(
                db_session,
                kind="off-air",
                resource_ref="gov-ch12",
                source_section="S8",
                summary=f"Off air tick {i}",
                observed_at=_NOW,
            )
        events = get_alert_events(db_session, state="firing")
        assert len(events) == 1
        assert events[0].occurrence_count == 10

    def test_resolve_clears_firing_event(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air",
            observed_at=_NOW,
        )
        resolved = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Back on air",
            observed_at=_LATER,
            resolved=True,
        )
        assert resolved.state == "resolved"
        assert resolved.resolved_at == _LATER
        # No more firing events
        assert get_alert_events(db_session, state="firing") == []

    def test_new_firing_event_after_resolve(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        first = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air",
            observed_at=_NOW,
        )
        record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Recovered",
            observed_at=_LATER,
            resolved=True,
        )
        second = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air again",
            observed_at=datetime(2026, 6, 15, 13, 0, 0, tzinfo=UTC),
        )
        assert second.event_id != first.event_id
        assert second.state == "firing"
        assert second.occurrence_count == 1

    def test_no_matching_rule_still_creates_event(self, db_session: Session) -> None:
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air (no rule)",
            observed_at=_NOW,
        )
        assert event.state == "firing"
        assert event.rule_id == ""  # no rule found

    def test_different_resource_refs_are_independent(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        e1 = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air ch12",
            observed_at=_NOW,
        )
        e2 = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="edu-ch5",
            source_section="S8",
            summary="Off air ch5",
            observed_at=_NOW,
        )
        assert e1.event_id != e2.event_id
        assert get_alert_events(db_session, state="firing") == [e1, e2] or {
            e.event_id for e in get_alert_events(db_session, state="firing")
        } == {e1.event_id, e2.event_id}

    def test_scoped_rule_preferred_over_wildcard(self, db_session: Session) -> None:
        # Wildcard rule for all channels
        _make_rule(db_session, "off-air", "warning", rule_id="default:off-air")
        # Scoped rule for gov-ch12 specifically
        scoped = AlertRule(
            rule_id="scoped:off-air:gov-ch12",
            condition="off-air",  # type: ignore[arg-type]
            severity="critical",
            scope_channel_id="gov-ch12",
            channel_ids=[],
            updated_at=_NOW,
            updated_by="test",
        )
        upsert_alert_rule(db_session, scoped)
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="gov-ch12",
            source_section="S8",
            summary="Off air",
            observed_at=_NOW,
        )
        # Should match scoped rule (critical) over wildcard (warning)
        assert event.rule_id == "scoped:off-air:gov-ch12"
        assert event.severity == "critical"


# ---------------------------------------------------------------------------
# AlertEvent queries
# ---------------------------------------------------------------------------


class TestAlertEventQueries:
    def test_get_alert_events_filter_by_state(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        _make_rule(db_session, "encoder-death", rule_id="default:encoder-death")
        record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="x",
            observed_at=_NOW,
        )
        record_alert_condition(
            db_session,
            kind="encoder-death",
            resource_ref="ch1",
            source_section="S8",
            summary="y",
            observed_at=_NOW,
        )
        record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="z",
            resolved=True,
            observed_at=_LATER,
        )
        firing = get_alert_events(db_session, state="firing")
        resolved = get_alert_events(db_session, state="resolved")
        assert len(firing) == 1  # encoder-death still firing
        assert len(resolved) == 1  # off-air resolved

    def test_get_alert_event_by_id(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="x",
            observed_at=_NOW,
        )
        fetched = get_alert_event(db_session, event.event_id)
        assert fetched is not None
        assert fetched.event_id == event.event_id

    def test_acknowledge_event(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="x",
            observed_at=_NOW,
        )
        acked = acknowledge_alert_event(
            db_session, event.event_id, by="operator@example.com", at=_LATER
        )
        assert acked is not None
        assert acked.acknowledged_at == _LATER
        assert acked.acknowledged_by == "operator@example.com"


# ---------------------------------------------------------------------------
# AlertEventDelivery
# ---------------------------------------------------------------------------


class TestAlertEventDelivery:
    def test_upsert_and_get_delivery(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="x",
            observed_at=_NOW,
        )
        delivery = AlertEventDelivery(
            delivery_id="del-001",
            event_id=event.event_id,
            alert_channel_id="ch-email-1",
            kind="email",
            status="sent",
            attempts=1,
            dispatched_at=_NOW,
        )
        upsert_event_delivery(db_session, delivery)
        results = get_event_deliveries(db_session, event.event_id)
        assert len(results) == 1
        assert results[0].status == "sent"
        assert results[0].delivery_id == "del-001"

    def test_upsert_updates_delivery_status(self, db_session: Session) -> None:
        _make_rule(db_session, "off-air")
        event = record_alert_condition(
            db_session,
            kind="off-air",
            resource_ref="ch1",
            source_section="S8",
            summary="x",
            observed_at=_NOW,
        )
        d = AlertEventDelivery(
            delivery_id="del-002",
            event_id=event.event_id,
            alert_channel_id="ch-1",
            kind="webhook",
            status="failed",
            attempts=1,
            dispatched_at=_NOW,
        )
        upsert_event_delivery(db_session, d)
        d2 = AlertEventDelivery(
            delivery_id="del-002",
            event_id=event.event_id,
            alert_channel_id="ch-1",
            kind="webhook",
            status="dead_letter",
            attempts=5,
            last_error="Connection refused",
            dispatched_at=_NOW,
        )
        upsert_event_delivery(db_session, d2)
        results = get_event_deliveries(db_session, event.event_id)
        assert len(results) == 1
        assert results[0].status == "dead_letter"
        assert results[0].attempts == 5


# ---------------------------------------------------------------------------
# SystemResourceSample
# ---------------------------------------------------------------------------


class TestSystemResourceSample:
    def test_append_and_recent_samples(self, db_session: Session) -> None:
        s = SystemResourceSample(sampled_at=_NOW, cpu_percent=42.0, ram_total_gb=16.0)
        appended = append_resource_sample(db_session, s)
        assert appended.sample_id is not None
        results = recent_resource_samples(db_session, window_minutes=60, now=_NOW)
        assert len(results) == 1
        assert results[0].cpu_percent == 42.0


# ---------------------------------------------------------------------------
# SystemSelfTest
# ---------------------------------------------------------------------------


class TestSystemSelfTest:
    def test_upsert_and_get_self_test(self, db_session: Session) -> None:
        t = SystemSelfTest(
            self_test_id="st-daily-001",
            kind="daily",
            started_at=_NOW,
            finished_at=_NOW,
            status="pass",
            checks={"readiness": True},
            summary="All good.",
        )
        upsert_self_test(db_session, t)
        results = get_self_tests(db_session, kind="daily")
        assert len(results) == 1
        assert results[0].status == "pass"
        assert results[0].checks == {"readiness": True}

    def test_upsert_updates_self_test(self, db_session: Session) -> None:
        t = SystemSelfTest(
            self_test_id="st-daily-001",
            kind="daily",
            started_at=_NOW,
            status="pass",
            checks={},
            summary="Pending",
        )
        upsert_self_test(db_session, t)
        t2 = SystemSelfTest(
            self_test_id="st-daily-001",
            kind="daily",
            started_at=_NOW,
            finished_at=_LATER,
            status="warn",
            checks={"readiness": True, "filesink": False},
            summary="FileSink probe failed.",
        )
        upsert_self_test(db_session, t2)
        results = get_self_tests(db_session)
        assert len(results) == 1
        assert results[0].status == "warn"
        assert results[0].checks["filesink"] is False
