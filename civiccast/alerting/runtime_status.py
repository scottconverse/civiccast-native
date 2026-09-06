# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 runtime safe-to-air computation (spec §3.6/§3.7/§6.5).

The install-time ``SafeToBroadcastContract`` answers "can I start a meeting?";
this answers "is the box on-air and healthy *right now*?" every few seconds.

Per ``auto_start`` channel we build a ``ChannelRuntimeStatus`` from its
``EgressStateRow`` + the post-QA-004 sink health carried on the latest
``EgressHealthSample`` (the corrected write path already stored state-aware
``sink_connected`` values). Overall color = worst channel color, escalated to
**red** if any ``critical`` alert is firing. This reuses the existing
``SafeToAirColor`` vocabulary so the runtime banner shares the install-time
color semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from civiccast.alerting.models import (
    ChannelRuntimeStatus,
    RuntimeSafeToAirStatus,
    SafeToAirColor,
)

if TYPE_CHECKING:
    from civiccast.alerting.models import AlertEvent
    from civiccast.egress.models import EgressConfig, EgressHealthSample, EgressStateRow
    from civiccast.egress.store import EgressStore

# Loudness target (ATSC A/85): -24 LUFS, ±2 LU healthy band.
_LOUDNESS_TARGET_LUFS = -24.0
_LOUDNESS_TOLERANCE_LU = 2.0

# States in which an auto_start channel is genuinely off-air (dark) — the
# operator promised 24/7 and the channel is not delivering it.
_DARK_STATES = {"STOPPED", "ERROR", "DRAINING", "STOPPING"}
# Transient states: on the way up / switching — not steady-green, not dark.
_TRANSIENT_STATES = {"STARTING", "TRANSITIONING"}
# BLOCKER A fix (2026-09-05 tester finding): a channel's TRANSITIONING latch
# could previously get stuck open indefinitely (daemon.py's pending-reload
# latch, now self-healed after ``_PENDING_RELOAD_STUCK_BOUND_S``). Escalate
# the runtime color past that self-heal bound so an operator is alerted even
# if the daemon-side recovery itself has a bug, rather than staying yellow
# ("coming up / switching") forever.
_TRANSITIONING_ESCALATION_SECONDS = 60

_COLOR_RANK: dict[SafeToAirColor, int] = {"green": 0, "yellow": 1, "red": 2}


def _worst(colors: list[SafeToAirColor]) -> SafeToAirColor:
    worst: SafeToAirColor = "green"
    for c in colors:
        if _COLOR_RANK[c] > _COLOR_RANK[worst]:
            worst = c
    return worst


def _seconds_in_state(state_row: EgressStateRow | None, now: datetime) -> int:
    if state_row is None:
        return 0
    updated = state_row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return max(0, int((now - updated).total_seconds()))


def _loudness_out_of_tolerance(lufs: float | None) -> bool:
    if lufs is None:
        return False
    return abs(lufs - _LOUDNESS_TARGET_LUFS) > _LOUDNESS_TOLERANCE_LU


def compute_channel_runtime_status(
    config: EgressConfig,
    state_row: EgressStateRow | None,
    latest_sample: EgressHealthSample | None,
    *,
    now: datetime,
) -> ChannelRuntimeStatus:
    """Build the runtime status for one channel from its state + latest sample."""
    state = state_row.state if state_row is not None else "STOPPED"
    sink_health = dict(latest_sample.sink_connected) if latest_sample is not None else {}
    all_sinks_ok = bool(sink_health) and all(sink_health.values())
    a_sink_down = any(not ok for ok in sink_health.values())
    captions_verified = (
        latest_sample is not None
        and getattr(latest_sample, "caption_status", "not-verified") == "on"
    )

    on_air = state == "ON_AIR"
    on_healthy_slate = state == "FALLBACK_SLATE" and all_sinks_ok and captions_verified

    fps = latest_sample.encoder_fps if latest_sample is not None else None
    bitrate = latest_sample.encoder_bitrate_kbps if latest_sample is not None else None
    loudness = latest_sample.last_loudness_lufs if latest_sample is not None else None

    degraded = a_sink_down or _loudness_out_of_tolerance(loudness)
    seconds_in_state = _seconds_in_state(state_row, now)

    color: SafeToAirColor
    if state in _DARK_STATES:
        color = "red"
    elif state in _TRANSIENT_STATES:
        # Coming up / switching — not steady, not off-air. BLOCKER A fix: a
        # TRANSITIONING channel that has sat that way past the escalation
        # bound is stuck, not merely mid-switch — escalate to red.
        if state == "TRANSITIONING" and seconds_in_state >= _TRANSITIONING_ESCALATION_SECONDS:
            color = "red"
        else:
            color = "yellow"
    elif state == "ON_AIR":
        color = "yellow" if degraded else "green"
    elif state == "FALLBACK_SLATE":
        # Idling on slate is healthy *iff* the sinks are up; otherwise degraded.
        color = "green" if all_sinks_ok and not _loudness_out_of_tolerance(loudness) else "yellow"
    else:  # pragma: no cover - exhaustive guard for future states
        color = "yellow"

    # Captions are a legal readiness requirement, not an optional health
    # decoration. Any missing, stale, failed, or otherwise unverified proof
    # fails closed even when transport and audio are otherwise healthy.
    if not captions_verified:
        color = "red"

    return ChannelRuntimeStatus(
        channel_id=config.channel_id,
        egress_state=state,
        sink_health=sink_health,
        on_air=on_air,
        on_healthy_slate=on_healthy_slate,
        encoder_fps=fps,
        encoder_bitrate_kbps=bitrate,
        last_loudness_lufs=loudness,
        seconds_in_state=seconds_in_state,
        last_proof_event_id=(state_row.current_proof_event_id if state_row is not None else None),
        color=color,
    )


def compute_runtime_safe_to_air(
    store: EgressStore,
    firing_alerts: list[AlertEvent],
    *,
    now: datetime | None = None,
) -> RuntimeSafeToAirStatus:
    """Compute the continuous runtime safe-to-air signal over auto_start channels.

    ``firing_alerts`` is the current set of ``state="firing"`` alert events
    (the caller reads them once from the alert store). Overall color = worst
    channel color, escalated to red if any critical alert is firing.
    """
    now = now or datetime.now(tz=UTC)

    channels: list[ChannelRuntimeStatus] = []
    for config in store.list_configs():
        if not (config.enabled and config.auto_start):
            continue
        state_row = store.read_state(config.channel_id)
        recent = store.recent_health(config.channel_id, 1)
        latest_sample = recent[0] if recent else None
        channels.append(compute_channel_runtime_status(config, state_row, latest_sample, now=now))

    active_critical = sum(1 for a in firing_alerts if a.severity == "critical")
    active_warning = sum(1 for a in firing_alerts if a.severity == "warning")

    channel_worst = _worst([c.color for c in channels]) if channels else "green"
    color: SafeToAirColor = "red" if active_critical > 0 else channel_worst

    label, message = _summarize(color, channels, active_critical, active_warning)

    return RuntimeSafeToAirStatus(
        generated_at=now,
        color=color,
        label=label,
        operator_message=message,
        channels=channels,
        active_critical_alerts=active_critical,
        active_warning_alerts=active_warning,
    )


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _summarize(
    color: SafeToAirColor,
    channels: list[ChannelRuntimeStatus],
    active_critical: int,
    active_warning: int,
) -> tuple[str, str]:
    if not channels:
        return ("Idle", "No channels are configured for 24/7 automation.")
    if color == "green":
        return ("On air", f"On air — all {len(channels)} channel(s) healthy.")
    if color == "red":
        red = [c for c in channels if c.color == "red"]
        if red:
            worst = red[0]
            return (
                "OFF AIR",
                f"OFF AIR — {worst.channel_id} {worst.egress_state} "
                f"for {_fmt_duration(worst.seconds_in_state)}.",
            )
        # Red only because a critical alert is firing (channels themselves not red).
        return ("OFF AIR", f"{active_critical} critical alert(s) firing.")
    # yellow
    degraded = [c.channel_id for c in channels if c.color == "yellow"]
    suffix = f" ({active_warning} warning alert(s))" if active_warning else ""
    return ("Degraded", f"Degraded — {', '.join(degraded)} not fully healthy.{suffix}")
