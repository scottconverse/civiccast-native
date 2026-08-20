# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pydantic contract tests for S8 alerting models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from civiccast.alerting.models import (
    AlertChannel,
    AlertEvent,
    AlertEventDelivery,
    AlertRule,
    ChannelRuntimeStatus,
    RuntimeSafeToAirStatus,
    SystemResourceSample,
    SystemSelfTest,
)

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _rule(**kwargs) -> AlertRule:
    defaults = {
        "rule_id": "default:off-air",
        "condition": "off-air",
        "severity": "critical",
        "updated_at": _NOW,
        "updated_by": "seed",
    }
    defaults.update(kwargs)
    return AlertRule(**defaults)


def _channel(**kwargs) -> AlertChannel:
    defaults = {
        "channel_id": "ch-email-1",
        "kind": "email",
        "label": "On-call email",
        "target_redacted": "oncall@***",
        "created_at": _NOW,
    }
    defaults.update(kwargs)
    return AlertChannel(**defaults)


class TestAlertRule:
    def test_valid_rule(self) -> None:
        rule = _rule()
        assert rule.condition == "off-air"
        assert rule.severity == "critical"
        assert rule.enabled is True
        assert rule.channel_ids == []
        assert rule.notify_on_resolve is True

    def test_invalid_condition_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _rule(condition="not-a-real-condition")  # type: ignore[arg-type]

    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _rule(severity="emergency")  # type: ignore[arg-type]

    def test_dedupe_window_bounds(self) -> None:
        # Max allowed
        rule = _rule(dedupe_window_seconds=86_400)
        assert rule.dedupe_window_seconds == 86_400
        with pytest.raises(ValidationError):
            _rule(dedupe_window_seconds=86_401)

    def test_re_alert_after_zero_is_valid(self) -> None:
        # 0 = one-shot (server-crash, missing-media)
        rule = _rule(re_alert_after_seconds=0)
        assert rule.re_alert_after_seconds == 0

    def test_all_fourteen_condition_kinds_accepted(self) -> None:
        conditions = [
            "off-air",
            "encoder-death",
            "server-crash",
            "schema-drift",
            "relay-blocked",
            "compliance-probe-fail",
            "missing-media",
            "commit-failure",
            "takeover-stuck-2h",
            "ai-runtime-down",
            "disk-low",
            "clock-skew",
            "db-unreachable",
            "service-down",
        ]
        for cond in conditions:
            r = _rule(rule_id=f"default:{cond}", condition=cond)
            assert r.condition == cond


class TestAlertChannel:
    def test_valid_email_channel(self) -> None:
        ch = _channel()
        assert ch.kind == "email"
        assert ch.enabled is True

    def test_sms_and_webhook_kinds_accepted(self) -> None:
        for kind in ("sms", "webhook"):
            ch = _channel(channel_id=f"ch-{kind}", kind=kind)
            assert ch.kind == kind

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _channel(kind="pager")  # type: ignore[arg-type]

    def test_valid_quiet_hours(self) -> None:
        ch = _channel(quiet_hours_start_utc="22:00", quiet_hours_end_utc="07:00")
        assert ch.quiet_hours_start_utc == "22:00"
        assert ch.quiet_hours_end_utc == "07:00"

    def test_invalid_quiet_hours_format_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _channel(quiet_hours_start_utc="2200")

    def test_invalid_quiet_hours_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _channel(quiet_hours_start_utc="25:00")


class TestAlertEvent:
    def test_valid_firing_event(self) -> None:
        event = AlertEvent(
            event_id="alert-abc123",
            rule_id="default:off-air",
            condition="off-air",
            severity="critical",
            state="firing",
            resource_ref="gov-ch12",
            summary="gov-ch12 is off air",
            source_section="S8",
            first_observed_at=_NOW,
            last_observed_at=_NOW,
        )
        assert event.state == "firing"
        assert event.occurrence_count == 1
        assert event.resolved_at is None

    def test_resolved_event(self) -> None:
        event = AlertEvent(
            event_id="alert-xyz",
            rule_id="default:off-air",
            condition="off-air",
            severity="critical",
            state="resolved",
            resource_ref="gov-ch12",
            summary="gov-ch12 recovered",
            source_section="S8",
            first_observed_at=_NOW,
            last_observed_at=_NOW,
            resolved_at=_NOW,
        )
        assert event.state == "resolved"
        assert event.resolved_at is not None

    def test_invalid_state_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AlertEvent(
                event_id="x",
                rule_id="r",
                condition="off-air",
                severity="critical",
                state="unknown",  # type: ignore[arg-type]
                resource_ref="gov-ch12",
                summary="x",
                source_section="S8",
                first_observed_at=_NOW,
                last_observed_at=_NOW,
            )


class TestAlertEventDelivery:
    def test_valid_delivery(self) -> None:
        d = AlertEventDelivery(
            delivery_id="del-1",
            event_id="alert-abc",
            alert_channel_id="ch-email-1",
            kind="email",
            status="sent",
            dispatched_at=_NOW,
        )
        assert d.status == "sent"
        assert d.attempts == 0
        assert d.last_error == ""

    def test_dead_letter_status_accepted(self) -> None:
        d = AlertEventDelivery(
            delivery_id="del-2",
            event_id="alert-abc",
            alert_channel_id="ch-sms-1",
            kind="sms",
            status="dead_letter",
            dispatched_at=_NOW,
        )
        assert d.status == "dead_letter"


class TestSystemResourceSample:
    def test_all_none_fields_valid(self) -> None:
        s = SystemResourceSample(sampled_at=_NOW)
        assert s.cpu_percent is None
        assert s.db_reachable is True
        assert s.service_running is True

    def test_out_of_range_cpu_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemResourceSample(sampled_at=_NOW, cpu_percent=101.0)

    def test_fully_populated_sample(self) -> None:
        s = SystemResourceSample(
            sampled_at=_NOW,
            cpu_percent=35.2,
            ram_used_gb=4.1,
            ram_total_gb=16.0,
            gpu_percent=12.0,
            media_volume_free_gb=200.0,
            db_reachable=True,
            service_running=True,
            clock_skew_seconds=0.012,
        )
        assert s.ram_total_gb == 16.0


class TestSystemSelfTest:
    def test_valid_daily_test(self) -> None:
        t = SystemSelfTest(
            self_test_id="st-daily-001",
            kind="daily",
            started_at=_NOW,
            finished_at=_NOW,
            status="pass",
            checks={"readiness": True, "filesink": True},
            summary="All 2 checks passed.",
        )
        assert t.status == "pass"
        assert t.checks["filesink"] is True

    def test_fail_status_accepted(self) -> None:
        t = SystemSelfTest(
            self_test_id="st-weekly-001",
            kind="weekly",
            started_at=_NOW,
            status="fail",
            checks={"restore_rehearsal": False},
            summary="Restore rehearsal failed.",
        )
        assert t.status == "fail"
        assert t.finished_at is None

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemSelfTest(
                self_test_id="st-x",
                kind="monthly",  # type: ignore[arg-type]
                started_at=_NOW,
                status="pass",
                checks={},
                summary="x",
            )


class TestRuntimeModels:
    def test_channel_runtime_status(self) -> None:
        crs = ChannelRuntimeStatus(
            channel_id="gov-ch12",
            egress_state="ON_AIR",
            on_air=True,
            on_healthy_slate=False,
            encoder_fps=29.97,
            encoder_bitrate_kbps=6000.0,
            color="green",
        )
        assert crs.on_air is True
        assert crs.color == "green"

    def test_runtime_safe_to_air_status(self) -> None:
        status = RuntimeSafeToAirStatus(
            generated_at=_NOW,
            color="green",
            label="On air",
            operator_message="All channels healthy.",
            active_critical_alerts=0,
            active_warning_alerts=0,
        )
        assert status.color == "green"
        assert status.channels == []

    def test_safe_to_air_red_with_alerts(self) -> None:
        status = RuntimeSafeToAirStatus(
            generated_at=_NOW,
            color="red",
            label="OFF AIR",
            operator_message="gov-ch12 has been off air for 4m 12s.",
            active_critical_alerts=1,
            active_warning_alerts=0,
        )
        assert status.active_critical_alerts == 1
