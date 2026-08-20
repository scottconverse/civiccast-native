# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 RuntimeSafeToAirStatus computation tests (spec §3.6/§3.7/§6.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from civiccast.alerting.models import AlertEvent
from civiccast.alerting.runtime_status import (
    compute_channel_runtime_status,
    compute_runtime_safe_to_air,
)
from civiccast.egress.models import (
    EgressConfig,
    EgressHealthSample,
    EgressSinkSpec,
    EgressStateRow,
)

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _config(
    channel_id: str = "public", *, auto_start: bool = True, enabled: bool = True
) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=enabled,
        auto_start=auto_start,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="udp-ts", label="Cable headend", uri="udp://239.255.0.1:5000")],
    )


def _state(
    channel_id: str, state: str, *, age_s: int = 30, proof: str | None = "pf-1"
) -> EgressStateRow:
    return EgressStateRow(
        channel_id=channel_id,
        state=state,  # type: ignore[arg-type]
        current_proof_event_id=proof,
        updated_at=_NOW - timedelta(seconds=age_s),
    )


def _sample(
    channel_id: str,
    state: str,
    *,
    sinks: dict[str, bool] | None = None,
    fps: float | None = 29.97,
    bitrate: float | None = 8000.0,
    loudness: float | None = -24.0,
    caption_status: str = "on",
) -> EgressHealthSample:
    return EgressHealthSample(
        channel_id=channel_id,
        sampled_at=_NOW,
        state=state,  # type: ignore[arg-type]
        sink_connected=sinks if sinks is not None else {"Cable headend": True},
        encoder_fps=fps,
        encoder_bitrate_kbps=bitrate,
        last_loudness_lufs=loudness,
        caption_status=caption_status,  # type: ignore[arg-type]
    )


def _alert(severity: str, condition: str = "off-air") -> AlertEvent:
    return AlertEvent(
        event_id=f"a-{condition}-{severity}",
        rule_id=f"default:{condition}",
        condition=condition,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        state="firing",
        resource_ref="public",
        summary="x",
        source_section="S8",
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )


class _FakeStore:
    def __init__(self, configs, states, samples):
        self._configs = configs
        self._states = states
        self._samples = samples

    def list_configs(self):
        return self._configs

    def read_state(self, channel_id):
        return self._states.get(channel_id)

    def recent_health(self, channel_id, limit):
        s = self._samples.get(channel_id)
        return [s] if s is not None else []


# ---------------------------------------------------------------------------
# Per-channel status
# ---------------------------------------------------------------------------


class TestChannelRuntimeStatus:
    def test_on_air_all_sinks_healthy_is_green(self) -> None:
        c = compute_channel_runtime_status(
            _config(), _state("public", "ON_AIR"), _sample("public", "ON_AIR"), now=_NOW
        )
        assert c.color == "green"
        assert c.on_air is True
        assert c.on_healthy_slate is False
        assert c.seconds_in_state == 30
        assert c.last_proof_event_id == "pf-1"

    def test_on_air_with_sink_down_is_yellow(self) -> None:
        c = compute_channel_runtime_status(
            _config(),
            _state("public", "ON_AIR"),
            _sample("public", "ON_AIR", sinks={"Cable headend": False}),
            now=_NOW,
        )
        assert c.color == "yellow"
        assert c.on_air is True

    def test_on_air_loudness_out_of_tolerance_is_yellow(self) -> None:
        c = compute_channel_runtime_status(
            _config(),
            _state("public", "ON_AIR"),
            _sample("public", "ON_AIR", loudness=-18.0),  # +6 LU over target
            now=_NOW,
        )
        assert c.color == "yellow"

    def test_stopped_is_red(self) -> None:
        c = compute_channel_runtime_status(_config(), _state("public", "STOPPED"), None, now=_NOW)
        assert c.color == "red"
        assert c.on_air is False

    def test_error_is_red(self) -> None:
        c = compute_channel_runtime_status(_config(), _state("public", "ERROR"), None, now=_NOW)
        assert c.color == "red"

    def test_healthy_slate_is_green_and_flagged(self) -> None:
        c = compute_channel_runtime_status(
            _config(),
            _state("public", "FALLBACK_SLATE"),
            _sample("public", "FALLBACK_SLATE", fps=0.0, bitrate=0.0),
            now=_NOW,
        )
        assert c.color == "green"
        assert c.on_healthy_slate is True
        assert c.on_air is False

    def test_slate_with_sink_down_is_yellow_not_healthy_slate(self) -> None:
        c = compute_channel_runtime_status(
            _config(),
            _state("public", "FALLBACK_SLATE"),
            _sample("public", "FALLBACK_SLATE", sinks={"Cable headend": False}),
            now=_NOW,
        )
        assert c.color == "yellow"
        assert c.on_healthy_slate is False

    def test_transient_states_are_yellow(self) -> None:
        for state in ("STARTING", "TRANSITIONING"):
            c = compute_channel_runtime_status(
                _config(), _state("public", state), _sample("public", state), now=_NOW
            )
            assert c.color == "yellow", state

    def test_missing_state_treated_as_dark_red(self) -> None:
        c = compute_channel_runtime_status(_config(), None, None, now=_NOW)
        assert c.color == "red"
        assert c.egress_state == "STOPPED"
        assert c.seconds_in_state == 0

    @pytest.mark.parametrize(
        "caption_status",
        ["not-verified", "failed", "expired", "overloaded"],
    )
    def test_on_air_without_verified_captions_is_red(
        self,
        caption_status: str,
    ) -> None:
        sample = _sample("public", "ON_AIR").model_copy(
            update={"caption_status": caption_status}
        )

        c = compute_channel_runtime_status(
            _config(),
            _state("public", "ON_AIR"),
            sample,
            now=_NOW,
        )

        assert c.color == "red"

    def test_on_air_without_a_health_sample_is_red(self) -> None:
        c = compute_channel_runtime_status(
            _config(),
            _state("public", "ON_AIR"),
            None,
            now=_NOW,
        )

        assert c.color == "red"


# ---------------------------------------------------------------------------
# Overall safe-to-air
# ---------------------------------------------------------------------------


class TestRuntimeSafeToAir:
    def _store(self, specs):
        # specs: list of (channel_id, state, sinks, auto_start)
        configs, states, samples = [], {}, {}
        for cid, state, sinks, auto in specs:
            configs.append(_config(cid, auto_start=auto))
            states[cid] = _state(cid, state)
            samples[cid] = _sample(cid, state, sinks=sinks)
        return _FakeStore(configs, states, samples)

    def test_all_green_no_alerts(self) -> None:
        store = self._store([("public", "ON_AIR", {"Cable headend": True}, True)])
        r = compute_runtime_safe_to_air(store, [], now=_NOW)
        assert r.color == "green"
        assert r.label == "On air"
        assert len(r.channels) == 1

    def test_off_air_channel_is_red_and_named(self) -> None:
        store = self._store([("gov-ch12", "STOPPED", None, True)])
        r = compute_runtime_safe_to_air(store, [], now=_NOW)
        assert r.color == "red"
        assert r.label == "OFF AIR"
        assert "gov-ch12" in r.operator_message

    def test_critical_alert_escalates_green_to_red(self) -> None:
        store = self._store([("public", "ON_AIR", {"Cable headend": True}, True)])
        r = compute_runtime_safe_to_air(store, [_alert("critical")], now=_NOW)
        assert r.color == "red"
        assert r.active_critical_alerts == 1

    def test_warning_alert_with_degraded_channel_is_yellow(self) -> None:
        store = self._store([("public", "ON_AIR", {"Cable headend": False}, True)])
        r = compute_runtime_safe_to_air(store, [_alert("warning", "encoder-death")], now=_NOW)
        assert r.color == "yellow"
        assert r.active_warning_alerts == 1
        assert "warning" in r.operator_message

    def test_non_auto_start_channels_excluded(self) -> None:
        store = self._store(
            [
                ("public", "ON_AIR", {"Cable headend": True}, True),
                ("adhoc", "STOPPED", None, False),  # not auto_start -> excluded
            ]
        )
        r = compute_runtime_safe_to_air(store, [], now=_NOW)
        assert [c.channel_id for c in r.channels] == ["public"]
        assert r.color == "green"

    def test_no_auto_start_channels_is_idle_green(self) -> None:
        store = self._store([("adhoc", "STOPPED", None, False)])
        r = compute_runtime_safe_to_air(store, [], now=_NOW)
        assert r.color == "green"
        assert r.label == "Idle"
        assert r.channels == []

    def test_worst_channel_color_wins(self) -> None:
        store = self._store(
            [
                ("public", "ON_AIR", {"Cable headend": True}, True),  # green
                ("edu", "ON_AIR", {"Cable headend": False}, True),  # yellow
            ]
        )
        r = compute_runtime_safe_to_air(store, [], now=_NOW)
        assert r.color == "yellow"
