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
# BLOCKER A redo (2026-09-05 hostile review): a stuck-looking TRANSITIONING
# row is not necessarily wrong -- for an ON_AIR program whose seamless
# reload failed, daemon.py's terminate+restart fallback is DESIGNED to wait
# for that program's own natural EOS (see daemon.py's _request_reload
# "Programs keep the graceful drain" comment), which can legitimately take
# as long as the program itself runs. Escalating on a flat wall-clock bound
# would false-alarm on every long program. The real hang is a pending reload
# that has outlived the plan it is waiting on: escalate once
# ``pending_reload_deadline`` (the dispatched plan's own duration + a
# margin, set by daemon.py's ``_request_reload``) has passed. When that
# deadline is unknown (no dispatched-plan record to estimate from) -- and
# for STARTING, which has no such per-plan concept at all -- fall back to a
# generous, symmetric flat bound so a GENUINELY stuck transition (the
# daemon-side estimate itself having a bug, or a worker wedged before ever
# reaching ON_AIR) still surfaces eventually.
_TRANSIENT_STATE_FALLBACK_ESCALATION_SECONDS = 600

_COLOR_RANK: dict[SafeToAirColor, int] = {"green": 0, "yellow": 1, "red": 2}


def _worst(colors: list[SafeToAirColor]) -> SafeToAirColor:
    worst: SafeToAirColor = "green"
    for c in colors:
        if _COLOR_RANK[c] > _COLOR_RANK[worst]:
            worst = c
    return worst


def _seconds_in_state(state_row: EgressStateRow | None, now: datetime) -> int:
    """How long ``state_row.state`` itself has been unchanged.

    Deliberately reads ``state_entered_at``, NOT ``updated_at`` -- the latter
    is the row's public "last write" timestamp and advances on every write
    (including a poll tick that rewrites an unchanged state), so it cannot
    answer "how long has this channel been stuck" (BLOCKER A hostile-review
    redo, 2026-09-05: an earlier pass conflated the two)."""
    if state_row is None:
        return 0
    entered = state_row.state_entered_at
    if entered.tzinfo is None:
        entered = entered.replace(tzinfo=UTC)
    return max(0, int((now - entered).total_seconds()))


def _pending_reload_overdue(state_row: EgressStateRow | None, now: datetime) -> bool:
    """True once a pending content-reload has outlived the plan it was
    estimated to hand off at (``pending_reload_deadline``, set by
    daemon.py's ``_request_reload``/``_poll_process``). Never true when the
    deadline is unknown -- an unknown deadline must not manufacture a false
    escalation; the flat fallback bound covers that case instead."""
    if state_row is None or state_row.pending_reload_deadline is None:
        return False
    deadline = state_row.pending_reload_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return now >= deadline


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
        # Coming up / switching — not steady, not off-air. BLOCKER A
        # hostile-review redo: escalate a TRANSITIONING row once its pending
        # reload has genuinely outlived the plan it is waiting on (the real
        # hang), not after a flat guess that would false-alarm on every
        # long-running program's graceful drain. STARTING (and a
        # TRANSITIONING row with no computable deadline) escalates
        # symmetrically, but only past a generous flat fallback bound.
        transitioning_overdue = state == "TRANSITIONING" and _pending_reload_overdue(state_row, now)
        if (
            transitioning_overdue
            or seconds_in_state >= _TRANSIENT_STATE_FALLBACK_ESCALATION_SECONDS
        ):
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
