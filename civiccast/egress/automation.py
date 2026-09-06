# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""24/7 channel automation driver (cable automation CA-2).

The egress daemon loop previously ran only under the ``civiccast egress run``
CLI — the app itself never drove channels. This module makes playout
self-driving:

* every poll, each enabled channel's command queue is processed
  (``daemon.process_once``), which also supervises the encoder process
  (crash auto-restart lives in the daemon already);
* channels flagged ``auto_start`` that have no live encoder get a ``start``
  command re-issued (``issued_by="channel-automation"``) — this is what
  brings a 24/7 channel back on air after an app or machine restart, since
  the operator's original start command was consumed long ago;
* a channel sitting on FALLBACK_SLATE gets a ``reload`` the moment the
  schedule yields a real source plan again, so a due program takes over the
  gap without operator action.

Combined with join-in-progress source plans (a rejoin resumes the current
program at the wall-clock offset), an app restart puts every automated
channel back where its published log says it should be.

Deployment shape mirrors the other lifespan workers: ``run_once`` is the
testable unit, ``run_forever`` survives and logs scan exceptions, and the
app lifespan runs the loop on a thread when ``CIVICCAST_CHANNEL_AUTOMATION``
is ``inline`` (the default — safe: with no auto_start channels and an empty
command queue each tick is a cheap poll; no encoder ever spawns uncommanded).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civiccast.egress.daemon import AlertEvaluatorHook, EgressDaemon
from civiccast.egress.engine_select import build_encoder_strategy, gstreamer_engine_selected
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.gst.reload_policy import rollover_trigger_at
from civiccast.egress.models import ChannelAutomationRollup, EgressCommand, EgressProofEvent
from civiccast.egress.store import EgressStore
from civiccast.native.station_runtime import EGRESS_DEGRADED_REASON_ENV

if TYPE_CHECKING:
    from civiccast.alerting.models import AlertConditionKind
    from civiccast.reporting.asrun_outbox import AsRunOutbox

_LOG = logging.getLogger(__name__)

#: The alerting condition raised when the GStreamer egress engine was found
#: corrupt and unrepairable at station-environment build time and egress was
#: switched to the FFmpeg concat engine to keep the channel airing
#: (``station_runtime._resolve_gstreamer_egress_environment`` sets
#: :data:`~civiccast.native.station_runtime.EGRESS_DEGRADED_REASON_ENV`). Seeded
#: CRITICAL (alerting migration 0039), so it forces the operator safe-to-air
#: surface OFF the green "healthy" state -- the channel is airing on FFmpeg and
#: is never dark, but the primary egress engine is down and the operator must
#: know loudly. The alert summary says the channel is still airing so a red
#: banner is not misread as dead air. Raised HERE, not in ``station_runtime``:
#: that module runs pre-DB under LocalSystem and holds no ``Session``; this
#: control-plane builder does, and is where the FFmpeg fallback engine is
#: actually selected (``build_encoder_strategy`` below).
_EGRESS_DEGRADED_ALERT_KIND: AlertConditionKind = "encoder-death"


def _raise_egress_degraded_alert(session_factory: Any, *, reason: str) -> None:
    """Raise the loud, critical GStreamer-egress-degraded operator alert.

    Never propagates (mirrors the supervisor's ``_AlertingOutbox`` posture): an
    alert INSERT against a degraded/absent DB must not block control-plane
    startup. The caller owns the transaction via ``session_factory``; a stable
    ``resource_ref`` lets the alerting store dedupe across restarts rather than
    spamming a fresh event every boot while the closure stays corrupt.
    """

    try:
        from civiccast.alerting.store import record_alert_condition

        # session_factory is a @contextmanager callable (see
        # civiccast.app._wire_stage_f_workers's _session_factory, the real
        # caller) -- calling it and reaching for .commit()/.close() directly
        # (the shape this used to have) raises AttributeError on the
        # _GeneratorContextManager it actually returns, so this alert has
        # never actually been recorded; caught here only because DEFECT C's
        # _ChannelAutomationAlerts._record copied the identical shape and a
        # new test for THAT code exercised the failure path for the first
        # time. Fixed alongside it, same file, same bug shape.
        with session_factory() as session:
            record_alert_condition(
                session,
                kind=_EGRESS_DEGRADED_ALERT_KIND,
                resource_ref="station:egress-engine",
                source_section="egress",
                summary=(
                    "GStreamer egress unavailable; channel airing on the FFmpeg "
                    "fallback engine (DEGRADED, not off air). Run the operator "
                    "'repair GStreamer runtime & restore full egress' action."
                ),
                detail=reason,
            )
            session.commit()
    except Exception:
        _LOG.exception(
            "raising the GStreamer egress-degraded alert failed; continuing -- "
            "alerting must never block control-plane startup."
        )


#: DEFECT C: a failed channel-automation pass (or one command inside it) used to
#: be visible ONLY as a log line -- "Channel automation pass failed for %s" --
#: which no operator would ever see. Wired to the same alerting hub every other
#: operational condition in this file already uses (no new UI surface).
_CHANNEL_AUTOMATION_FAILURE_KIND: AlertConditionKind = "channel-automation-failure"


class _ChannelAutomationAlerts:
    """Fires/clears the ``channel-automation-failure`` condition (DEFECT C).

    One instance is shared between the daemon's per-command failure hook
    (``EgressDaemon(command_failure_hook=...)``, fires mid-pass, inside
    ``process_once`` -- see the DEFECT D fix there) and
    ``ChannelAutomationService.run_once``'s per-channel exception handler
    (fires for failures OUTSIDE ``process_once``, e.g. a source-plan/relay/
    replan exception in ``_run_channel_pass``), so both routes land the same
    alert kind/resource_ref under one auto-clear contract: the alert for a
    channel stays firing until that channel completes one poll pass with NO
    failure recorded during it -- ``begin_tick``/``end_tick`` bracket every
    pass so a mid-pass command failure and a whole-pass failure both count,
    and a clean pass clears exactly once (not spammed every ~2s poll tick;
    ``record_alert_condition`` would happily create a fresh pre-resolved
    audit row on every call with nothing firing, so ``_firing`` gates that).
    Never propagates -- same posture as ``_raise_egress_degraded_alert``.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._firing: set[str] = set()
        self._failed_this_tick: set[str] = set()

    def begin_tick(self, channel_id: str) -> None:
        self._failed_this_tick.discard(channel_id)

    def on_command_failure(
        self, channel_id: str, command: EgressCommand, exc: BaseException
    ) -> None:
        self._failed_this_tick.add(channel_id)
        self._raise(
            channel_id,
            summary=f"Egress command {command.action!r} failed for channel {channel_id!r}.",
            detail=(
                f"command_id={command.command_id} issued_by={command.issued_by}: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )

    def on_pass_failure(self, channel_id: str, *, detail: str) -> None:
        self._failed_this_tick.add(channel_id)
        self._raise(
            channel_id,
            summary=f"Channel automation pass failed for channel {channel_id!r}.",
            detail=detail,
        )

    def end_tick(self, channel_id: str) -> None:
        """Call once a channel's pass has completed without raising."""
        if channel_id in self._failed_this_tick:
            return  # a command failed THIS tick even though the pass itself didn't raise
        if channel_id not in self._firing:
            return  # nothing to clear -- do not spam a resolved event every poll
        self._firing.discard(channel_id)
        self._record(
            channel_id,
            summary=f"Channel automation for {channel_id!r} recovered.",
            detail="The channel completed a poll pass with no failure.",
            resolved=True,
        )

    def _raise(self, channel_id: str, *, summary: str, detail: str) -> None:
        self._firing.add(channel_id)
        self._record(channel_id, summary=summary, detail=detail, resolved=False)

    def _record(self, channel_id: str, *, summary: str, detail: str, resolved: bool) -> None:
        try:
            from civiccast.alerting.store import record_alert_condition

            # session_factory is a @contextmanager callable -- see the note
            # in _raise_egress_degraded_alert above (same file) for why this
            # must be a ``with`` block, not a raw session.commit()/.close().
            with self._session_factory() as session:
                record_alert_condition(
                    session,
                    kind=_CHANNEL_AUTOMATION_FAILURE_KIND,
                    resource_ref=f"egress-channel:{channel_id}",
                    source_section="egress",
                    summary=summary[:300],
                    detail=detail[:2000],
                    resolved=resolved,
                )
                session.commit()
        except Exception:
            _LOG.exception(
                "recording the channel-automation-failure alert failed for %s; "
                "continuing -- alerting must never block channel automation.",
                channel_id,
            )


AUTOMATION_MODE_INLINE = "inline"
AUTOMATION_MODE_OFF = "off"
_AUTOMATION_MODES = (AUTOMATION_MODE_INLINE, AUTOMATION_MODE_OFF)

_ISSUED_BY = "channel-automation"

__all__ = [
    "ChannelAutomationService",
    "ChannelAutomationSettings",
    "build_channel_automation",
    "default_egress_work_dir",
]


def default_egress_work_dir() -> Path:
    """Default directory for egress plans, prepared segments, and slates."""

    configured = os.environ.get("CIVICCAST_EGRESS_WORK_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "CivicCast" / "egress"
    return Path.home() / ".local" / "share" / "civiccast" / "egress"


@dataclass(frozen=True)
class ChannelAutomationSettings:
    """Deployment configuration for the channel automation driver."""

    mode: str = AUTOMATION_MODE_INLINE
    poll_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> ChannelAutomationSettings:
        mode = (
            os.environ.get("CIVICCAST_CHANNEL_AUTOMATION", AUTOMATION_MODE_INLINE).strip().lower()
        )
        if mode not in _AUTOMATION_MODES:
            raise ValueError(
                f"CIVICCAST_CHANNEL_AUTOMATION must be one of {', '.join(_AUTOMATION_MODES)}; "
                f"got {mode!r}."
            )
        raw_poll = os.environ.get("CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS", "").strip()
        if not raw_poll:
            return cls(mode=mode)
        try:
            poll_seconds = float(raw_poll)
        except ValueError as exc:
            raise ValueError(
                f"CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS must be a number; got {raw_poll!r}."
            ) from exc
        if poll_seconds <= 0:
            raise ValueError(
                f"CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS must be positive; got {raw_poll!r}."
            )
        return cls(mode=mode, poll_seconds=poll_seconds)


class ChannelAutomationService:
    """Drive every enabled channel's daemon loop from the app lifespan."""

    def __init__(
        self,
        store: EgressStore,
        daemon: EgressDaemon,
        source_plan_provider: Any,
        *,
        settings: ChannelAutomationSettings,
        ndi_supervisor_factory: Any = None,
        sdi_supervisor_factory: Any = None,
        monotonic: Any = None,
        as_run_outbox: AsRunOutbox | None = None,
        automation_alerts: _ChannelAutomationAlerts | None = None,
    ) -> None:
        self._store = store
        self._daemon = daemon
        self._source_plan_provider = source_plan_provider
        self._settings = settings
        self._monotonic = monotonic or time.monotonic
        # DEFECT C: shared with the daemon's command_failure_hook (see
        # build_channel_automation) so a mid-pass command failure and a
        # whole-pass failure land the SAME alert, with ONE auto-clear
        # contract. None (tests / the bare CLI daemon loop) is a no-op --
        # a failed pass is still logged, just not alerted.
        self._alerts = automation_alerts
        # BUG C2 fix: periodic drain of the as-run durable outbox
        # (civiccast.reporting.asrun_outbox). The recorder already drains
        # opportunistically on every write; this tick is what retries a
        # backlog left behind by a DB outage once the DB comes back, without
        # needing a dedicated thread -- it rides the same poll cadence that
        # already drives every other channel-automation concern.
        self._as_run_outbox = as_run_outbox
        # Pacing prevents command storms WITHOUT the one-shot deadlock that
        # left a dark channel unstarted for an hour (issue #152, found live
        # in the CA-8 run): a dark auto_start channel is retried every
        # cooldown until it comes up. Reload keeps the per-period latch.
        self._start_retry_at: dict[str, float] = {}
        self._reload_issued: set[str] = set()
        # Audit ENG-002: reload re-issue pacing (see _check_slate_replan).
        self._replan_retry_at: dict[str, float] = {}
        # Soak evidence 2026-09-04 (kit 4b30c99): back-to-back scheduled
        # premieres EOS'd the engine at every source-plan boundary because
        # nothing ever extended a LIVE (ON_AIR) plan before it ran out --
        # only a FALLBACK_SLATE gap re-planned (_check_slate_replan above).
        # Each channel restarted 6-8x in a 2h soak, a worker-restart blip at
        # every 10-15 min boundary. _plan_horizon tracks, per channel, the
        # (current_proof_event_id, projected wall-clock end, projected start
        # of the plan's LAST segment) of the plan the daemon is actually
        # airing; _check_plan_rollover below extends it via the SAME
        # seamless content-reload path _check_slate_replan already uses,
        # before the engine ever reaches EOS.
        # D45 fix (2026-09-05): the tuple's 4th element is the tracked plan's
        # own planned duration (seconds), used by
        # _rollover_min_interval_seconds to size the per-channel dispatch
        # floor to the plan actually on air instead of a fixed constant --
        # see that method's docstring.
        self._plan_horizon: dict[str, tuple[str | None, datetime, datetime, float]] = {}
        self._rollover_issued: set[str] = set()
        # D43 hardening (2026-09-05): the monotonic timestamp of the last
        # rollover DISPATCH per channel, enforcing
        # _rollover_min_interval_seconds between them. Each dispatch runs
        # SourcePreparer.prepare synchronously on the automation thread
        # (daemon._try_content_reload), so the cadence has to be bounded
        # whatever the plan window turns out to be.
        self._rollover_dispatched_at: dict[str, float] = {}
        # Hostile-review B2 fix: when the reload lands (a fresh
        # current_proof_event_id shows up), _rollover_issued is discarded by the
        # "tracked is None or tracked[0] != proof_event_id" branch below. This
        # timestamp is how a reload that DIDN'T land within
        # _ROLLOVER_ISSUED_TIMEOUT_SECONDS is detected and retried once more
        # before the plan's projected end, instead of silently waiting forever
        # for a proof-event change that a dropped/failed reload will never
        # produce.
        self._rollover_issued_at: dict[str, float] = {}
        # Hostile-review B2 fix: mirrors _replan_retry_at (see
        # _check_slate_replan) -- backs off re-querying the schedule after a
        # SourcePrepareError or an empty/None plan, instead of hammering the
        # provider every ~2s poll tick until the next successful dispatch.
        self._rollover_retry_at: dict[str, float] = {}
        # Issue #116: one supervised BYO-NDI relay per named channel.
        self._ndi_supervisor_factory = ndi_supervisor_factory or _default_ndi_factory
        self._ndi_relays: dict[str, Any] = {}
        # Issue #117: one supervised BYO-SDI relay per configured channel.
        self._sdi_supervisor_factory = sdi_supervisor_factory or _default_sdi_factory
        self._sdi_relays: dict[str, Any] = {}

    _START_RETRY_COOLDOWN_SECONDS = 30.0
    _RELOAD_RETRY_COOLDOWN_SECONDS = 30.0
    # Hostile-review B3 fix: the floor of how far ahead of a live plan's
    # projected end the rollover trigger fires -- the actual trigger is
    # boundary-aligned (reload_policy.rollover_trigger_at: the moment the
    # plan's LAST segment begins, or this many seconds before the projected
    # end, whichever is EARLIER). 120s gives SourcePreparer's cold-conform
    # path (which can take minutes -- daemon.py's _try_content_reload calls it
    # synchronously) real runway before the engine reaches EOS; the previous
    # fixed 30s lookahead left conform racing EOS (soak evidence, kit
    # 4b30c99). Deliberately generous: even when conform finishes well before
    # the boundary, the new leg simply waits, prerolled, for the outgoing
    # leg's own EOS (the engine's switch_at_end_of_current -- see
    # reload_policy.should_defer_switch) rather than cutting in early and
    # truncating the still-airing item.
    #
    # Hostile-review fix (NEW-3, 2026-09-05): this fixed 120s value is no
    # longer used directly as the lead -- it is only the CEILING
    # _rollover_min_lead_seconds clamps to (mirrors
    # _ROLLOVER_MIN_INTERVAL_SECONDS's relationship to
    # _rollover_min_interval_seconds, above). A flat 120s lead pushed
    # ``plan_end_at - lead`` deep into the PAST for a plan shorter than
    # 120s (an 8x3s/24-second plan), which dominates ``rollover_trigger_at``'s
    # min() over the real last-segment-start candidate and lands the
    # dispatch at or after the plan's own end. See
    # _rollover_min_lead_seconds.
    _ROLLOVER_MIN_LEAD_SECONDS = 120.0
    # Hostile-review B2 fix: if a dispatched rollover reload has not landed
    # (no fresh current_proof_event_id) within this long, treat it as dropped
    # and retry once more before the plan's projected end, rather than waiting
    # on a proof-event change a failed/lost reload will never produce. Shorter
    # than _ROLLOVER_MIN_LEAD_SECONDS so a retry still has lead time to land.
    _ROLLOVER_ISSUED_TIMEOUT_SECONDS = 45.0
    # Hostile-review B2 fix: mirrors _RELOAD_RETRY_COOLDOWN_SECONDS -- how long
    # to back off re-querying the schedule after the provider raises
    # SourcePrepareError or returns no/empty plan for a rollover check.
    _ROLLOVER_RETRY_COOLDOWN_SECONDS = 30.0
    # D43 hardening, D45 fix (2026-09-05): a floor under the per-channel
    # rollover CADENCE. The boundary-aligned trigger point alone is not
    # enough -- it is derived from the plan, so a plan that comes back short
    # for any reason can still drive a fast cycle. Each dispatch costs a
    # synchronous SourcePreparer.prepare on the automation thread
    # (daemon._try_content_reload), so no channel may dispatch rollovers
    # closer together than this. The B2 "the reload never landed" retry is
    # deliberately exempt -- that is recovery, not cadence.
    #
    # D45: this fixed 300s value is no longer used directly as the floor --
    # it is only the CEILING _rollover_min_interval_seconds clamps to. A flat
    # 300s floor is longer than the lifetime of a short plan (D45's own
    # trigger: PLAN_MIN_SECONDS reverted to 0.0 in source_plan.py means an
    # 8-segment, 30-second-item plan is only 240s long). MEASURED: against
    # that 240s plan a flat 300s floor produces a dispatch every 300s with
    # the boundary-aligned lead shrinking each cycle (120s, then 60s, then
    # 0s, then negative), so by the third rollover the trigger arrives at or
    # after the plan's real end and the engine reaches EOS and restarts --
    # exactly the failure this cadence floor exists to prevent. See
    # _rollover_min_interval_seconds.
    _ROLLOVER_MIN_INTERVAL_SECONDS = 300.0
    #: Hostile-review fix (2026-09-05): a trivial epsilon floor ONLY -- large
    #: enough to avoid a literal zero/near-zero interval for a degenerate
    #: plan, small enough to never bind for any plan worth measuring. An
    #: earlier version of this fix used 30.0 here, which is a real floor for
    #: a longer plan but is LONGER than half the lifetime of an 8x3s (24s)
    #: plan -- measured (with ``_rollover_min_lead_seconds``, NEW-3, also
    #: scaled): dispatches still happen every 30s (the floor), but the
    #: boundary-aligned lead shrinks each cycle (12s, 6s, 0s, then negative
    #: from the fourth rollover on) exactly like the flat-300s bug this
    #: whole mechanism exists to fix, just faster. ``_rollover_min_interval_
    #: seconds`` must never return more than half the plan's own planned
    #: duration; this constant cannot violate that because it is far smaller
    #: than any real plan.
    _ROLLOVER_MIN_INTERVAL_FLOOR_SECONDS = 1.0

    @property
    def daemon(self) -> EgressDaemon:
        """RAT-004: the underlying daemon, exposed so the app lifespan's
        shutdown ``finally`` block can call ``stop_all_channels(...)`` as the
        graceful drain-all owner before halting this service's poll loop."""

        return self._daemon

    def run_forever(
        self,
        *,
        poll_seconds: float = 2.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Run the automation loop until stopped; survive scan errors."""

        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                _LOG.exception(
                    "Channel automation scan failed; retrying on the next poll interval."
                )
            if stop_event is not None:
                stop_event.wait(poll_seconds)
            else:
                time.sleep(poll_seconds)

    def run_once(self, *, now: datetime | None = None) -> list[str]:
        """One pass over every enabled channel; returns the channel ids seen."""

        resolved_now = now or datetime.now(UTC)
        self._drain_as_run_outbox()
        seen: list[str] = []
        for config in self._store.list_configs():
            if not config.enabled:
                continue
            channel_id = config.channel_id
            seen.append(channel_id)
            if self._alerts is not None:
                self._alerts.begin_tick(channel_id)
            # Audit Critical (TEST-001): one channel's failure - a poisoned
            # relay config, a supervisor crash - must never starve the other
            # channels' supervision. Isolate per channel; the loop's outer
            # handler in run_forever still covers scan-level failures.
            try:
                self._run_channel_pass(config, channel_id, resolved_now)
            except Exception as exc:
                _LOG.exception(
                    "Channel automation pass failed for %s; other channels "
                    "continue. Fix this channel's configuration or inspect "
                    "the error above.",
                    channel_id,
                )
                # DEFECT C: this used to be visible ONLY as the log line above.
                if self._alerts is not None:
                    self._alerts.on_pass_failure(
                        channel_id, detail=f"{exc.__class__.__name__}: {exc}"
                    )
                continue
            if self._alerts is not None:
                self._alerts.end_tick(channel_id)
        return seen

    def _drain_as_run_outbox(self) -> None:
        """BUG C2 fix: retry a backlog left by a prior DB outage.

        Routes through ``ensure_started()`` rather than ``drain_once()``
        directly: this is the first of the two call sites
        (``AsRunOutbox.ensure_started``'s docstring names the other --
        the recorder's first opportunistic write) that can perform the
        one-time startup replay, deferred out of ``build_channel_automation``
        so create_app() never touches the database. In steady state (no
        backlog, replay already done) this is a cheap no-op read. Neither
        ``ensure_started`` nor ``drain_once`` ever raises for a store
        failure (both log + alert internally); this try/except is
        defense-in-depth against a genuinely unexpected bug, matching every
        other per-tick guard in this loop.
        """
        if self._as_run_outbox is None:
            return
        try:
            self._as_run_outbox.ensure_started()
        except Exception:
            _LOG.exception("As-run outbox drain tick failed unexpectedly; retrying next poll.")

    def _run_channel_pass(self, config: Any, channel_id: str, resolved_now: datetime) -> None:
        if self._daemon.has_live_process(channel_id):
            self._start_retry_at.pop(channel_id, None)
        elif config.auto_start:
            retry_at = self._start_retry_at.get(channel_id)
            if retry_at is None or self._monotonic() >= retry_at:
                self._enqueue(channel_id, "start", now=resolved_now)
                self._start_retry_at[channel_id] = (
                    self._monotonic() + self._START_RETRY_COOLDOWN_SECONDS
                )
                _LOG.info(
                    "Channel automation issued start for dark auto_start "
                    "channel %s (retries every %.0fs until live).",
                    channel_id,
                    self._START_RETRY_COOLDOWN_SECONDS,
                )
        self._daemon.process_once(channel_id)
        self._check_slate_replan(channel_id, now=resolved_now)
        self._check_plan_rollover(channel_id, now=resolved_now)
        self._sync_ndi_relay(config)
        self._sync_sdi_relay(config)

    def _sync_ndi_relay(self, config: Any) -> None:
        from civiccast.egress.ndi_relay import (
            NdiRelayStatus,
            drop_relay_status,
            set_relay_status,
        )

        channel_id = config.channel_id
        if not config.ndi_relay_name:
            existing = self._ndi_relays.pop(channel_id, None)
            if existing is not None:
                existing.stop()
                drop_relay_status(channel_id)
            return
        source_uri = _udp_ts_source_uri(config)
        if source_uri is None:
            set_relay_status(
                NdiRelayStatus(
                    channel_id=channel_id,
                    ndi_name=config.ndi_relay_name,
                    state="blocked",
                    next_step=(
                        "NDI relay needs the channel's UDP transport-stream "
                        "output. Apply a headend delivery preset (or add a "
                        "udp-ts/local-ts udp:// sink) first."
                    ),
                )
            )
            return
        relay = self._ndi_relays.get(channel_id)
        if relay is not None and (
            relay.ndi_name != config.ndi_relay_name or relay.source_uri != source_uri
        ):
            relay.stop()
            relay = None
        if relay is None:
            relay = self._ndi_supervisor_factory(
                channel_id=channel_id,
                ndi_name=config.ndi_relay_name,
                source_uri=source_uri,
            )
            self._ndi_relays[channel_id] = relay
        set_relay_status(relay.ensure_running())

    def _sync_sdi_relay(self, config: Any) -> None:
        from civiccast.egress.sdi_relay import (
            SdiRelayStatus,
            drop_relay_status,
            set_relay_status,
        )

        channel_id = config.channel_id
        if not config.sdi_relay_device:
            existing = self._sdi_relays.pop(channel_id, None)
            if existing is not None:
                existing.stop()
                drop_relay_status(channel_id)
            return
        source_uri = _udp_ts_source_uri(config)
        if source_uri is None:
            set_relay_status(
                SdiRelayStatus(
                    channel_id=channel_id,
                    device=config.sdi_relay_device,
                    state="blocked",
                    next_step=(
                        "SDI relay needs the channel's UDP transport-stream "
                        "output. Apply a headend delivery preset (or add a "
                        "udp-ts/local-ts udp:// sink) first."
                    ),
                )
            )
            return
        relay = self._sdi_relays.get(channel_id)
        if relay is not None and (
            relay.device != config.sdi_relay_device or relay.source_uri != source_uri
        ):
            relay.stop()
            relay = None
        if relay is None:
            relay = self._sdi_supervisor_factory(
                channel_id=channel_id,
                device=config.sdi_relay_device,
                source_uri=source_uri,
            )
            self._sdi_relays[channel_id] = relay
        set_relay_status(relay.ensure_running())

    def _check_slate_replan(self, channel_id: str, *, now: datetime) -> None:
        state_row = self._store.read_state(channel_id)
        if state_row is None or state_row.state != "FALLBACK_SLATE":
            self._reload_issued.discard(channel_id)
            # A program actually made it on air: the last reload SUCCEEDED,
            # so the failure-pacing cooldown resets and the next gap reloads
            # immediately. The TRANSITIONING leg of a failing flap does NOT
            # clear it - that is the churn the cooldown exists to stop.
            if state_row is not None and state_row.state == "ON_AIR":
                self._replan_retry_at.pop(channel_id, None)
            return
        if channel_id in self._reload_issued:
            return
        # Audit ENG-002: when the due item persistently fails PREPARATION,
        # the channel flaps TRANSITIONING->FALLBACK_SLATE (clearing the
        # one-shot latch above) and a naive re-issue strobes kill/restart
        # every ~2 ticks for the item's whole duration. Reloads get the
        # same cooldown pacing as #152 gave starts: 30s of honest slate
        # between retries.
        retry_at = self._replan_retry_at.get(channel_id)
        if retry_at is not None and self._monotonic() < retry_at:
            return
        try:
            plan = self._source_plan_provider(channel_id)
        except SourcePrepareError:
            # The due item exists but is not playable yet; stay on slate and
            # try again next poll — the daemon would land back on slate anyway.
            return
        if plan is None:
            return
        self._enqueue(channel_id, "reload", now=now)
        self._reload_issued.add(channel_id)
        self._replan_retry_at[channel_id] = self._monotonic() + self._RELOAD_RETRY_COOLDOWN_SECONDS
        _LOG.info(
            "Channel automation issued reload for %s: a scheduled program is due.",
            channel_id,
        )

    def _rollover_min_lead_seconds(self, planned_seconds: float) -> float:
        """Hostile-review fix (NEW-3, 2026-09-05): the boundary-aligned
        rollover LEAD, sized to the plan actually on air instead of a fixed
        constant -- the same problem ``_rollover_min_interval_seconds``
        solves for the dispatch-cadence FLOOR, one layer up.

        ``_ROLLOVER_MIN_LEAD_SECONDS`` (120s) is fine as a floor for
        ``rollover_trigger_at``'s ``min_lead_seconds`` when the plan is long
        enough to have 120s to spare. For a very short plan it is not: a
        flat 120s lead against an 8x3s (24-second) plan pushes
        ``plan_end_at - 120`` deep into the plan's own past, so the
        boundary-aligned trigger -- ``min(last_segment_start_at,
        plan_end_at - lead)`` -- is dominated by that negative candidate
        rather than the plan's real last-segment start, and the resulting
        dispatch lands at or after the plan's actual end (a negative lead
        over its own life) even with ``_rollover_min_interval_seconds``
        already fixed. Scaling this the same way (half the plan's own
        duration, clamped at the historic 120s ceiling) keeps the trigger
        boundary-aligned to a REAL point within a short plan's life instead
        of one that has already passed -- measured, an 8x3s (24-second)
        plan's every rollover now lands with a lead of at least a quarter of
        the plan's own duration (see
        ``TestRolloverCadence.test_a_very_short_plan_still_rolls_over_before_its_own_end``).
        This ceiling (120s) is smaller than ``_rollover_min_interval_
        seconds``'s (300s), so for the schedule-derived plans this whole
        pass targets (``max_segments=8`` by default, well under a 600s
        life) the two formulas agree; a plan long enough to separate them
        (several minutes or more) has ample runway from either number."""

        return min(self._ROLLOVER_MIN_LEAD_SECONDS, 0.5 * planned_seconds)

    def _rollover_min_interval_seconds(self, planned_seconds: float) -> float:
        """D45 fix: the per-channel rollover-dispatch floor, sized to the plan
        actually on air instead of a fixed constant.

        D43 fixed this floor at a flat ``_ROLLOVER_MIN_INTERVAL_SECONDS``
        (300s). That is longer than the lifetime of a short plan -- with
        ``source_plan.PLAN_MIN_SECONDS`` back to 0.0 (D45; see its
        docstring), a schedule of 30-second items yields an 8-segment,
        240-second plan. MEASURED against that plan with the flat 300s
        floor: 6 dispatches in 30 minutes, the first at 120s, each 300s
        apart, with the boundary-aligned lead shrinking every cycle (120s,
        then 60s, then 0s, then negative) -- so by the third rollover the
        trigger arrives at or after the plan's real end and the engine
        reaches EOS and restarts before that rollover can land: exactly the
        failure this cadence floor exists to prevent (see
        ``tests/egress/test_automation.py``'s
        ``test_the_flat_floor_bug_the_scaled_floor_fixes`` for the exact
        numbers).

        Scaling the floor to HALF the plan's own planned duration (clamped
        at ``_ROLLOVER_MIN_INTERVAL_SECONDS``, 300s, for a long plan)
        guarantees this can never exceed the plan's own lifetime, so a
        rollover always has room to dispatch again well before the plan runs
        out, however short the schedule's slots are. Hostile-review fix: an
        earlier version additionally floored this at a flat 30s
        (``max(30.0, 0.5 * planned_seconds)``), which is itself LONGER than
        HALF an 8x3s (24-second) plan's own lifetime and reproduces the same
        shrinking-lead bug at a smaller scale -- MEASURED (with
        ``_rollover_min_lead_seconds``, NEW-3, also in place): dispatches
        still happen, ten of them in a 300s window (12s, 42s, 72s, ...), but
        the lead shrinks every cycle (12s, 6s, 0s, then negative from the
        fourth rollover on) exactly like the 300s-floor case above, not
        "one dispatch and then nothing." The floor is now only
        ``_ROLLOVER_MIN_INTERVAL_FLOOR_SECONDS`` (a trivial 1.0s epsilon
        against a literal zero/near-zero interval for a degenerate plan),
        so this never returns more than half of ``planned_seconds`` -- the
        ONLY invariant this method guarantees. A long-item schedule (a plan
        well over 600s) is unaffected -- the 300s ceiling still applies."""

        return min(
            self._ROLLOVER_MIN_INTERVAL_SECONDS,
            max(self._ROLLOVER_MIN_INTERVAL_FLOOR_SECONDS, 0.5 * planned_seconds),
        )

    def _check_plan_rollover(self, channel_id: str, *, now: datetime) -> None:
        """Extend a LIVE plan before it EOSes (the fix for the soak defect).

        ``_check_slate_replan`` above only reacts to a GAP (FALLBACK_SLATE):
        it has never looked at a plan that is actively airing (ON_AIR). A
        schedule of back-to-back published premieres builds a source plan
        capped at ``max_segments`` (``source_plan.py``); once the last
        segment finishes the GStreamer worker EOSes, the daemon writes
        STOPPED, and only THEN does auto_start bring the channel back --
        6-8 worker restarts (and on-air blips) in the 2h soak
        (evidence: Desktop/CIVICCAST-EVIDENCE/soak-120-4b30c99-20260904,
        T6-beat-*.json pid churn).

        This tracks the projected wall-clock end of the plan the daemon is
        currently airing, AND the projected start of its last segment (keyed
        off ``current_proof_event_id``, which changes at every fresh
        start/reload -- see ``daemon._write_state`` call sites) and, once the
        boundary-aligned trigger computed by
        ``reload_policy.rollover_trigger_at`` is reached, re-fetches the
        schedule. Building the plan again at (a later) ``now`` is itself the
        rollover: the provider always resumes at the currently-airing item
        with a join-in-progress offset and windows forward from there
        (``source_plan.build_source_plan_from_schedule``), so a later call
        naturally reaches further into the schedule than the original call
        did. If that fresh plan reaches further than the one already
        airing, the SAME ``reload`` command ``_check_slate_replan`` uses is
        enqueued -- the daemon's ``_request_reload`` dispatches it through
        ``_try_content_reload`` (the GStreamer seamless content-swap;
        ``gst/strategy.py``'s ``reload_content``), so the channel stays
        ON_AIR with no worker restart and no EOS.

        Hostile-review B1 fix: skipped entirely while an operator override
        (live takeover / forced fallback slate) is active for the channel --
        see ``EgressDaemon.has_manual_override`` / ``PlayoutSupervisor.
        has_manual_override``. Neither writes a state-row transition this
        method could otherwise key off, so without this check a live takeover
        gets fought with a mid-event reload back to the SCHEDULED plan (a
        forced SRT/NDI reconnect), and a forced slate's reload attempt lands
        in the daemon's ``_pending_reloads`` latch and silently drops the
        operator's slate once it resolves.

        Hostile-review B3 fix: the trigger point moved EARLIER and became
        boundary-aligned (``_ROLLOVER_MIN_LEAD_SECONDS`` / last-segment-start,
        see ``reload_policy.rollover_trigger_at``'s docstring) -- the previous
        fixed 30s lookahead left ``SourcePreparer``'s synchronous cold-conform
        (daemon.py's ``_try_content_reload``, which can take minutes) racing
        the pipeline's own EOS. Triggering early enough that the new leg is
        typically ready well before the boundary means an IMMEDIATE switch
        (the old default) would truncate the tail of the still-airing item --
        so the daemon requests ``switch_at_end_of_current=True`` for this
        reload whenever the channel is ON_AIR with no override active
        (``reload_policy.should_defer_switch``), and the engine defers the
        actual selector switch to the outgoing leg's own EOS
        (``GstPlayoutEngine.reload_program``). The airing item is never
        re-decoded or cut short.

        Hostile-review B2 fix: ``_rollover_retry_at`` backs off re-querying
        the schedule (mirrors ``_replan_retry_at``) after a
        ``SourcePrepareError`` or an empty/None plan, instead of hammering the
        provider every ~2s poll tick. ``_rollover_issued_at`` bounds how long
        a dispatched reload is trusted to be in flight: if
        ``current_proof_event_id`` hasn't changed within
        ``_ROLLOVER_ISSUED_TIMEOUT_SECONDS`` (the reload was dropped, failed,
        or the command was never consumed), the latch clears and one retry is
        issued before the plan's projected end, rather than silently waiting
        forever on a proof-event change that will never arrive.

        D43 hardening, D45 fix (2026-09-05): ``_rollover_min_interval_seconds``
        is a floor under the gap between two rollover dispatches for one
        channel, independent of the plan window, because each dispatch runs
        ``SourcePreparer.prepare`` synchronously on this thread via
        ``daemon._try_content_reload``. D43 originally fixed this floor at a
        flat 300s and grew the plan itself (``source_plan.PLAN_MIN_SECONDS``)
        so a short-slot schedule would not need frequent rollovers. Real-
        hardware soak evidence then measured what that plan growth cost: an
        1800-second-minimum plan built from 30-second schedule items is ~60
        segments, and the GStreamer bridge builds one decoder sub-chain PER
        segment in a single pipeline -- ~1200 threads and ~3.5 GB on one
        worker, tripping the 10s stall watchdog every ~30s. D45 reverts
        ``PLAN_MIN_SECONDS`` to 0.0 (the plan's segment COUNT alone bounds
        pipeline shape now) and instead derives this floor from the plan
        actually on air: short plan, short floor, so a rollover is always
        allowed to land comfortably inside the plan's own lifetime, instead
        of a flat constant that can be longer than that lifetime -- measured
        with a flat 300s floor against an 8x30s (240s) plan: the
        boundary-aligned lead shrinks every cycle (120s, then 60s, then 0s,
        then negative) until a rollover arrives at or after the plan's real
        end and the engine reaches EOS. See ``_rollover_min_interval_seconds``
        for the exact numbers and the smaller-scale version of this same bug
        (a flat 30s sub-floor against a 24-second plan) an earlier version
        of this fix still had.

        If the schedule has nothing beyond what is already loaded (the
        freshly-built plan does not reach any further), this deliberately
        does nothing: there is no more program content to roll onto, so the
        plan is left to reach its own natural end. That crash-restart-free
        path is unchanged by this fix (see the module docstring and #157);
        closing that residual gap (a seamless swap onto filler/slate BEFORE
        the true end of schedule) is a separate follow-on, not needed by
        the continuous-premiere soak scenario this fixes.
        """

        state_row = self._store.read_state(channel_id)
        if state_row is None or state_row.state != "ON_AIR":
            # Not airing a schedule-derived program right now (dark, slate,
            # starting, transitioning, draining) -- nothing to extend.
            self._plan_horizon.pop(channel_id, None)
            self._rollover_issued.discard(channel_id)
            self._rollover_issued_at.pop(channel_id, None)
            # The cadence floor governs EXTENSIONS of a live plan; a channel
            # that has left the air starts fresh (a restart or a slate replan
            # must never be throttled by an earlier rollover).
            self._rollover_dispatched_at.pop(channel_id, None)
            return
        if self._daemon_has_manual_override(channel_id):
            # B1 fix: an operator override is live -- never fight it. Leave any
            # tracked horizon as-is; it will be re-established (or correctly
            # found stale and discarded) once the override clears and this
            # channel's state/proof-event settle back to a normal rollover.
            return
        proof_event_id = state_row.current_proof_event_id
        tracked = self._plan_horizon.get(channel_id)
        if tracked is None or tracked[0] != proof_event_id:
            # A fresh plan just took air (initial start, a slate replan, or
            # this method's own rollover reload completing) -- (re)establish
            # its projected end + last-segment-start and wait; nothing to
            # roll over yet. Also means any in-flight rollover landed.
            self._rollover_issued.discard(channel_id)
            self._rollover_issued_at.pop(channel_id, None)
            previous_end_at = tracked[1] if tracked is not None else None
            if self._establish_horizon_from_dispatch(
                channel_id,
                now=now,
                proof_event_id=proof_event_id,
                previous_end_at=previous_end_at,
            ):
                return
            retry_at = self._rollover_retry_at.get(channel_id)
            if retry_at is not None and self._monotonic() < retry_at:
                self._plan_horizon.pop(channel_id, None)
                return
            try:
                plan = self._source_plan_provider(channel_id)
            except SourcePrepareError:
                self._rollover_retry_at[channel_id] = (
                    self._monotonic() + self._ROLLOVER_RETRY_COOLDOWN_SECONDS
                )
                return
            if plan is None or not plan.segments:
                self._plan_horizon.pop(channel_id, None)
                self._rollover_retry_at[channel_id] = (
                    self._monotonic() + self._ROLLOVER_RETRY_COOLDOWN_SECONDS
                )
                return
            self._rollover_retry_at.pop(channel_id, None)
            planned_seconds = sum(segment.duration_seconds for segment in plan.segments)
            plan_end_at = now + timedelta(seconds=planned_seconds)
            last_segment_start_at = plan_end_at - timedelta(
                seconds=plan.segments[-1].duration_seconds
            )
            self._plan_horizon[channel_id] = (
                proof_event_id,
                plan_end_at,
                last_segment_start_at,
                planned_seconds,
            )
            return
        _, plan_end_at, last_segment_start_at, planned_seconds = tracked

        retrying_undelivered = False
        if channel_id in self._rollover_issued:
            if self._daemon_has_pending_reload_settlement(channel_id):
                # F1 redesign follow-up: the daemon reports this specific
                # reload is armed and still settling (a deferred switch can
                # take ~120s-900s) -- never retry while that is true; the
                # daemon's own deadline resolves it one way or the other.
                return
            issued_at = self._rollover_issued_at.get(channel_id)
            if issued_at is not None and (
                self._monotonic() - issued_at >= self._ROLLOVER_ISSUED_TIMEOUT_SECONDS
            ):
                # B2 fix: the proof event never changed -- the dispatched
                # reload did not land. Clear the latch and fall through to
                # retry once more before the plan's projected end.
                _LOG.warning(
                    "Channel automation rollover reload for %s did not land within "
                    "%.0fs (current_proof_event_id unchanged); retrying.",
                    channel_id,
                    self._ROLLOVER_ISSUED_TIMEOUT_SECONDS,
                )
                self._rollover_issued.discard(channel_id)
                self._rollover_issued_at.pop(channel_id, None)
                retrying_undelivered = True
            else:
                return  # already dispatched for this plan boundary; wait for it to land

        trigger_at = rollover_trigger_at(
            plan_end_at=plan_end_at,
            last_segment_start_at=last_segment_start_at,
            min_lead_seconds=self._rollover_min_lead_seconds(planned_seconds),
        )
        if now < trigger_at:
            return  # not yet at the boundary-aligned trigger point

        if not retrying_undelivered:
            # D43 cadence floor, D45 fix: never dispatch rollovers for one
            # channel faster than _rollover_min_interval_seconds(planned_seconds)
            # apart -- sized to the plan actually on air, not a fixed
            # constant that can outlast a short plan (see that method's
            # docstring). Checked BEFORE the provider call so a throttled
            # tick costs nothing at all.
            last_dispatch = self._rollover_dispatched_at.get(channel_id)
            if (
                last_dispatch is not None
                and self._monotonic() - last_dispatch
                < self._rollover_min_interval_seconds(planned_seconds)
            ):
                return

        retry_at = self._rollover_retry_at.get(channel_id)
        if retry_at is not None and self._monotonic() < retry_at:
            return
        try:
            fresh_plan = self._source_plan_provider(channel_id)
        except SourcePrepareError:
            # Try again next poll (after the cooldown) -- the current plan
            # still plays out fine meanwhile.
            self._rollover_retry_at[channel_id] = (
                self._monotonic() + self._ROLLOVER_RETRY_COOLDOWN_SECONDS
            )
            return
        if fresh_plan is None or not fresh_plan.segments:
            # Schedule exhausted for now -- let the current plan reach its
            # own end.
            self._rollover_retry_at[channel_id] = (
                self._monotonic() + self._ROLLOVER_RETRY_COOLDOWN_SECONDS
            )
            return
        fresh_end = now + timedelta(
            seconds=sum(segment.duration_seconds for segment in fresh_plan.segments)
        )
        if fresh_end <= plan_end_at:
            # No more published schedule content beyond what is already
            # loaded (the window did not advance) -- nothing to roll onto.
            self._rollover_retry_at[channel_id] = (
                self._monotonic() + self._ROLLOVER_RETRY_COOLDOWN_SECONDS
            )
            return
        self._rollover_retry_at.pop(channel_id, None)
        self._enqueue(channel_id, "reload", now=now)
        self._rollover_issued.add(channel_id)
        self._rollover_issued_at[channel_id] = self._monotonic()
        self._rollover_dispatched_at[channel_id] = self._monotonic()
        _LOG.info(
            "Channel automation issued a seamless plan rollover for %s: the live plan "
            "ends in %.0fs and the schedule continues %.0fs further; extending in place "
            "before the engine reaches EOS.",
            channel_id,
            (plan_end_at - now).total_seconds(),
            (fresh_end - plan_end_at).total_seconds(),
        )

    def _establish_horizon_from_dispatch(
        self,
        channel_id: str,
        *,
        now: datetime,
        proof_event_id: str | None,
        previous_end_at: datetime | None,
    ) -> bool:
        """Set this channel's tracked plan horizon from the plan the daemon
        ACTUALLY dispatched. Returns False when the daemon cannot say (a bare test
        double, or no dispatch recorded for this proof event yet), leaving the
        caller on its legacy re-query path.

        Hostile-review (d) fix. The re-query path this replaces asked the source
        plan provider for a plan again and summed THAT. The provider re-windows
        from whatever schedule item is live at the moment of the call, capped at
        ``max_segments`` (``source_plan.build_source_plan_from_schedule``), so the
        answer is a different segment list than the one on air -- and the derived
        ``plan_end_at`` can overshoot far enough that
        ``rollover_trigger_at`` lands ON the real EOS, which is precisely the
        boundary this whole pass exists to get ahead of. The dispatched plan is
        the only list whose durations are the ones the engine is playing.

        The deferred-switch case is the second half of the fix: a boundary-aligned
        rollover plan (``switch_at_end_of_current``) does not start when it is
        dispatched -- the engine holds it, prerolled, until the OUTGOING leg's own
        end. Its projected end therefore runs from the previous plan's projected
        end, not from ``now`` (measuring from ``now`` would put the horizon a whole
        rollover lead time -- up to ``_ROLLOVER_MIN_LEAD_SECONDS`` -- early, and
        make every subsequent rollover fire before there was anything to roll)."""

        reader = getattr(self._daemon, "dispatched_plan_horizon", None)
        if not callable(reader):
            return False
        dispatched = reader(channel_id)
        if not dispatched:
            return False
        dispatched_proof_id, durations, switch_deferred = dispatched
        if dispatched_proof_id != proof_event_id or not durations:
            # A dispatch we have no matching proof event for is not evidence about
            # what is on air right now.
            return False
        starts_at = now
        if switch_deferred and previous_end_at is not None and previous_end_at > now:
            starts_at = previous_end_at
        planned_seconds = sum(durations)
        plan_end_at = starts_at + timedelta(seconds=planned_seconds)
        last_segment_start_at = plan_end_at - timedelta(seconds=durations[-1])
        self._plan_horizon[channel_id] = (
            proof_event_id,
            plan_end_at,
            last_segment_start_at,
            planned_seconds,
        )
        self._rollover_retry_at.pop(channel_id, None)
        return True

    def _daemon_has_manual_override(self, channel_id: str) -> bool:
        """B1 fix: consult ``EgressDaemon.has_manual_override`` /
        ``PlayoutSupervisor.has_manual_override`` if the wired daemon defines
        it (every real daemon does -- see daemon.py/supervisor.py); ``getattr``
        keeps a bare test double that predates this method working exactly as
        before (no override signal available -> treated as none active)."""

        has_override = getattr(self._daemon, "has_manual_override", None)
        if not callable(has_override):
            return False
        return bool(has_override(channel_id))

    def _daemon_has_pending_reload_settlement(self, channel_id: str) -> bool:
        """F1 redesign follow-up (coordinator hostile review, 2026-09-06): a
        DEFERRED/boundary-aligned reload's ``current_proof_event_id`` does not
        change until it actually SETTLES (``EgressDaemon._commit_reload_
        settlement``) -- for an automation-driven ON_AIR extension that can be
        ~120s+ after ``_check_plan_rollover`` dispatched it (the whole point of
        triggering early, ``reload_policy.rollover_trigger_at``), and up to the
        engine's own ``defer_switch_timeout_s`` (900s default) in the worst
        case. ``_ROLLOVER_ISSUED_TIMEOUT_SECONDS`` (45s) is far shorter than
        that, so without this check the "did the dispatched reload land"
        timeout below would clear its latch and retry -- re-preparing
        synchronously, superseding the still-armed leg in the engine, and
        creating another prepared-plan directory -- every ~45s while a
        perfectly healthy deferred reload is still legitimately settling.

        ``has_pending_reload_settlement`` is an OPTIONAL daemon capability
        (only ``EgressDaemon``/``PlayoutSupervisor`` implement it; a bare test
        double need not), resolved via ``getattr`` like
        ``has_manual_override``/``dispatched_plan_horizon`` above. While it
        reports True, this method treats the rollover as "landed, waiting" --
        never retrying -- and relies entirely on the DAEMON's own bounded
        deadline (``_PENDING_RELOAD_SETTLE_DEADLINE_S``) to eventually either
        commit (which changes ``current_proof_event_id``, handled by the
        existing "fresh plan just took air" branch above) or fall back to
        restart (which flips the state row away from ON_AIR, handled by this
        method's own top-of-function early return)."""

        reader = getattr(self._daemon, "has_pending_reload_settlement", None)
        if not callable(reader):
            return False
        return bool(reader(channel_id))

    def _enqueue(self, channel_id: str, action: str, *, now: datetime) -> None:
        self._store.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action=action,  # type: ignore[arg-type]
                issued_at=now,
                issued_by=_ISSUED_BY,
                command_id=f"auto-{action}-{uuid.uuid4().hex[:12]}",
            )
        )


_RELAY_CMDLINE_MARKERS = ("-f decklink", "-f libndi_newtek")


def reap_predecessor_relays(
    *,
    boot_epoch: float,
    scanner: Any = None,
    terminator: Any = None,
    store: Any = None,
) -> list[int]:
    """Terminate relay ffmpeg processes left by a previous server (ENG-003).

    Relay children survive a server kill exactly like encoder children
    (#161), but their pids are tracked only in memory - so they are found by
    their DISTINCTIVE command line instead: an ffmpeg whose argv contains an
    NDI relay muxer flag and whose create time predates this server. (3.0 is
    IP-only; the SDI/DeckLink relay is descoped, so the surviving case is the
    NDI relay holding an NDI name.) The kill is TOCTOU-safe (the terminator
    re-verifies create_time via ``process_identity.verify_and_kill_process``).

    S9-4: when ``store`` is given, each reap is recorded as a durable
    ``civiccast-egress-coprocess-lifecycle`` proof event so the boot cleanup is
    auditable, not just a log line.
    """

    scan = scanner or _default_relay_scanner
    kill = terminator or _default_relay_terminator
    reaped: list[int] = []
    for pid, name, cmdline, created_at in scan():
        if "ffmpeg" not in (name or "").lower():
            continue
        if created_at >= boot_epoch:
            continue
        if not any(marker in cmdline for marker in _RELAY_CMDLINE_MARKERS):
            continue
        kill(pid, created_at)
        reaped.append(pid)
        _LOG.warning(
            "Reaped predecessor relay ffmpeg pid %s (left by a previous "
            "server process; it was holding the relay output).",
            pid,
        )
        if store is not None:
            try:
                store.append_proof_event(
                    EgressProofEvent(
                        event_id=f"egress-coproc-reap-{pid}-{int(created_at)}",
                        observed_at=datetime.now(UTC),
                        channel_id="egress-system",
                        state="STARTING",
                        source_label="(predecessor relay reap)",
                        source_path=f"coproc-pid-{pid}",
                        proof_boundary="civiccast-egress-coprocess-lifecycle",
                        machine_summary=(
                            f"Reaped a predecessor relay co-process (pid {pid}) left by a "
                            "previous server before startup; its output/name is freed."
                        ),
                    )
                )
            except Exception:  # auditing must never block startup
                _LOG.exception("Failed to record co-process reap proof event for pid %s.", pid)
    return reaped


def _default_relay_scanner() -> list[tuple[int, str, str, float]]:
    import psutil

    rows: list[tuple[int, str, str, float]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            info = process.info
            cmdline = " ".join(info.get("cmdline") or [])
            rows.append(
                (info["pid"], info.get("name") or "", cmdline, info.get("create_time") or 0.0)
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


def _default_relay_terminator(pid: int, created_at: float) -> None:
    from civiccast.egress.daemon import _default_orphan_terminator

    _default_orphan_terminator(pid, created_at)


def _udp_ts_source_uri(config: Any) -> str | None:
    """The channel's UDP TS output a side-relay can eat, if any."""

    for sink in config.sinks:
        if sink.kind in ("udp-ts", "local-ts") and sink.uri.startswith("udp://"):
            return sink.uri  # type: ignore[no-any-return]
    return None


def _default_ndi_factory(*, channel_id: str, ndi_name: str, source_uri: str) -> Any:
    from civiccast.egress.ndi_relay import NdiRelaySettings, NdiRelaySupervisor

    return NdiRelaySupervisor(
        channel_id=channel_id,
        ndi_name=ndi_name,
        source_uri=source_uri,
        settings=NdiRelaySettings.from_env(),
    )


def _default_sdi_factory(*, channel_id: str, device: str, source_uri: str) -> Any:
    from civiccast.egress.sdi_relay import SdiRelaySettings, SdiRelaySupervisor

    return SdiRelaySupervisor(
        channel_id=channel_id,
        device=device,
        source_uri=source_uri,
        settings=SdiRelaySettings.from_env(),
    )


def summarize_automation(store: EgressStore) -> ChannelAutomationRollup:
    """Roll up the state of every auto_start channel for System Health.

    "Dark" means an automated channel whose last known state is missing,
    STOPPED, or ERROR — the operator promised 24/7 and the channel is not
    delivering it. FALLBACK_SLATE counts as on-air-with-filler (the channel
    IS broadcasting; the schedule just has a gap).
    """

    from civiccast.egress.models import ChannelAutomationRollup

    automated = 0
    on_air = 0
    on_slate = 0
    dark: list[str] = []
    for config in store.list_configs():
        if not (config.enabled and config.auto_start):
            continue
        automated += 1
        state_row = store.read_state(config.channel_id)
        state = state_row.state if state_row is not None else None
        if state in ("ON_AIR", "STARTING", "TRANSITIONING"):
            on_air += 1
        elif state == "FALLBACK_SLATE":
            on_slate += 1
        else:
            dark.append(config.channel_id)
    return ChannelAutomationRollup(automated=automated, on_air=on_air, on_slate=on_slate, dark=dark)


def build_channel_automation(
    session_factory: Any,
    *,
    work_dir: Path | None = None,
    alert_evaluator_hook: AlertEvaluatorHook | None = None,
) -> ChannelAutomationService:
    """Construct the wired automation service (same shape as the egress CLI).

    ``alert_evaluator_hook`` (S8-3/S8-5) is threaded to the EgressDaemon so each
    health sample feeds the operational alert evaluator.
    """

    from civiccast.captions.persistence import PostgresCaptionReviewStore
    from civiccast.captions.retention import build_caption_readiness_provider
    from civiccast.captions.tap_worker import CaptionTapWorkerSettings
    from civiccast.egress.audio_tracks import AudioTrackStore
    from civiccast.egress.bulletin_filler import build_filler_source_provider
    from civiccast.egress.caption_proof import build_caption_status_provider
    from civiccast.egress.hls_relay import HlsRelaySupervisor
    from civiccast.egress.preparer import SourcePreparer
    from civiccast.egress.source_plan import ScheduleSourcePlanProvider
    from civiccast.egress.store import PostgresEgressStore
    from civiccast.egress.supervisor import PlayoutSupervisor
    from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
    from civiccast.egress.ts_relay import TsRelaySupervisor
    from civiccast.reporting.asrun_outbox import AsRunOutbox, default_asrun_outbox_path
    from civiccast.reporting.asrun_recorder import StoreAsRunRecorder
    from civiccast.reporting.store import ReportingStore
    from civiccast.schedule.models import SCHEDULE_STATE_PUBLISHED
    from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore

    resolved_work_dir = (work_dir or default_egress_work_dir()).expanduser()
    resolved_work_dir.mkdir(parents=True, exist_ok=True)
    caption_tap_settings = CaptionTapWorkerSettings.from_env()
    store = PostgresEgressStore(session_factory)
    # ENG-003 / S9-4: clear any relay co-process a previous server left holding its
    # NDI name, recording each reap as a durable proof event. Never blocks startup.
    try:
        reap_predecessor_relays(boot_epoch=time.time(), store=store)
    except Exception:
        _LOG.exception("Predecessor relay reap failed; continuing startup.")
    # BUG C2 fix (S23 §6.1 durable outbox): one AsRunOutbox for the process,
    # rooted at the real station-data-dir journal, shared by the recorder
    # (opportunistic drain on every write) and this service's periodic
    # drain tick. Constructing it here only opens the LOCAL journal file
    # (plain sqlite3, not the app's SQLAlchemy engine) -- cheap and safe to
    # do synchronously. The startup replay itself is deliberately NOT run
    # here: build_channel_automation runs inside civiccast.app.create_app()
    # (via _wire_stage_f_workers / _wire_durable_stores /
    # _install_durable_store_wiring when DATABASE_URL is set at boot), a
    # path that must never touch the database (pinned by
    # tests/schedule/test_app_wiring.py::TestAppFactorySetEnv::
    # test_create_app_does_not_call_engine_connect). AsRunOutbox.
    # ensure_started() defers the replay to the first real drain attempt
    # instead (the recorder's first opportunistic write, or this service's
    # first run_once poll tick -- see its docstring), which only happens
    # once the app is actually serving, so the "a crash mid-drain loses
    # nothing" guarantee still holds without an eager DB touch here.
    as_run_outbox = AsRunOutbox(
        ReportingStore(session_factory),
        db_path=default_asrun_outbox_path(),
        alert_session_factory=session_factory,
    )
    # DEFECT C: one alert-firing/clearing instance shared between the daemon's
    # per-command failure hook (fires mid-pass) and the service's whole-pass
    # exception handler (fires for a raise outside process_once) -- see
    # _ChannelAutomationAlerts's docstring for why they must share state.
    automation_alerts = _ChannelAutomationAlerts(session_factory)
    asset_store = PostgresAssetStore(session_factory)
    schedule_store = PostgresScheduleStore(session_factory)
    source_plan_provider = ScheduleSourcePlanProvider(
        schedule_items_provider=lambda channel_id: schedule_store.list(
            channel_id=channel_id,
            states=(SCHEDULE_STATE_PUBLISHED,),
        ),
        asset_resolver=asset_store.get_staff_row,
    )
    # #156: the persistent conform cache emits playout-time trims when the
    # engine honors them — the legacy ffmpeg-concat engine does (ffconcat
    # inpoint/outpoint); the gst engine (default) reads only segment.path, so
    # it gets the fast stream-copy fallback instead.
    # F3 fix (hostile-review follow-up, 2026-09-06): kept as a named instance
    # so `.release` (immediate per-plan-directory reclaim once the daemon
    # independently knows a plan is retired) can be wired alongside `.prepare`
    # -- see cli.py's identical pattern.
    source_preparer_instance = SourcePreparer(
        work_dir=resolved_work_dir,
        playout_trim_supported=not gstreamer_engine_selected(),
    )
    # S5: the production engine is the PlayoutSupervisor (subclass of EgressDaemon)
    # so live takeover/handback work. lookahead_source_plan_provider=None keeps
    # source selection a single-plan passthrough of source_plan_provider —
    # behaviorally identical to the base daemon for scheduled playout (the
    # look-ahead-combine window is a deliberate follow-on, not enabled here, to
    # protect the 24h-proven automation path). takeover_audit_store lets the
    # supervisor read the open session a "takeover" command must put live.
    daemon = PlayoutSupervisor(
        store,
        work_dir=resolved_work_dir,
        source_plan_provider=source_plan_provider,
        lookahead_source_plan_provider=None,
        takeover_audit_store=PostgresTakeoverAuditStore(session_factory),
        # CA-3: gaps fill per the channel's fill_policy — rotating approved
        # community bulletins or the plain slate.
        fallback_source_provider=build_filler_source_provider(
            session_factory, work_dir=resolved_work_dir
        ),
        source_preparer=source_preparer_instance.prepare,
        prepared_plan_release=source_preparer_instance.release,
        resolve_secret=lambda ref: os.environ.get(ref),
        # S15: the GStreamer engine (default) or ffmpeg-concat (legacy), per
        # CIVICCAST_EGRESS_ENGINE.
        # S11 gap 9: the gst engine gets a per-channel secondary-audio (SAP/descriptive)
        # provider so it can mux extra audio PIDs; the ffmpeg path ignores it.
        encoder_strategy=build_encoder_strategy(
            audio_tracks_provider=lambda channel_id: AudioTrackStore(session_factory).list_tracks(
                scope="channel", target_id=channel_id, enabled_only=True
            )
        ),
        # S8: feed each health sample to the operational alert evaluator.
        alert_evaluator_hook=alert_evaluator_hook,
        # #151: channel-lifetime TS relay (TSDuck continuity --fix + pcradjust)
        # so encoder relaunches never reset the mux session at a udp-ts
        # headend. auto mode: active only when tsp is available.
        ts_relay_supervisor=TsRelaySupervisor(),
        # DEFECT A: the GStreamer engine's hls sinks are delivered by a
        # supervised ffmpeg relay (real segments + a real manifest) -- see
        # civiccast.egress.hls_relay's module docstring for why no native
        # GStreamer element can do this with the shipped runtime's plugins.
        hls_relay_supervisor=HlsRelaySupervisor(),
        # DEFECT D/C: a command that fails inside process_once no longer
        # aborts the rest of its batch (see EgressDaemon.process_once); this
        # hook is how that failure still reaches the operator alert surface.
        command_failure_hook=automation_alerts.on_command_failure,
        # S11a: caption_status reflects the latest caption decode-back proof
        # (fail-closed — not-verified until a fresh PASS is persisted by the
        # caption proof loop), instead of a hardcoded posture.
        caption_status_provider=build_caption_status_provider(store),
        # Retention is classified from durable review/evidence rows and real disk
        # capacity before the daemon selects a program source or starts an encoder.
        caption_readiness_provider=build_caption_readiness_provider(
            tap_root=caption_tap_settings.tap_root,
            review_store=PostgresCaptionReviewStore(session_factory),
            storage_root=resolved_work_dir,
            segment_seconds=caption_tap_settings.segment_seconds,
        ),
        # S23: at each ACTUAL source transition the engine appends an as-run
        # entry (proof-of-performance) to the durable franchise-compliance
        # ledger. Append-only side-write; never blocks playout (every call is
        # guarded). Distinct from the trimmed proof-event ring buffer. BUG C2
        # fix: routed through the shared as_run_outbox (journal-first, never
        # a bare direct store write) instead of a fresh unwired recorder.
        as_run_recorder=StoreAsRunRecorder(ReportingStore(session_factory), outbox=as_run_outbox),
    )
    # Item 5 fix: only the daemon knows which per-plan directories are
    # currently LIVE (active on-air + armed-not-yet-settled) -- wire it back
    # into the preparer's own GC pass now that both exist.
    source_preparer_instance.set_protected_plan_dirs_provider(daemon.live_prepared_plan_dirs)
    # GStreamer degraded-mode tier 3: if the station bootstrap found the
    # GStreamer closure corrupt/unrepairable and switched egress to FFmpeg
    # (build_encoder_strategy above therefore returned ConcatEncoderStrategy),
    # raise the loud operator alert now -- this is the first seam past the
    # pre-DB station bootstrap that holds a session_factory. Health goes off
    # "green healthy" via the critical alert (safe-to-air surface).
    _egress_degraded_reason = os.environ.get(EGRESS_DEGRADED_REASON_ENV, "").strip()
    if _egress_degraded_reason:
        _raise_egress_degraded_alert(session_factory, reason=_egress_degraded_reason)
    return ChannelAutomationService(
        store,
        daemon,
        source_plan_provider,
        settings=ChannelAutomationSettings.from_env(),
        # BUG C2 fix: the periodic poll retries any as-run drain backlog
        # left by a DB outage once the DB comes back (see run_once's
        # _drain_as_run_outbox).
        as_run_outbox=as_run_outbox,
        # DEFECT C: whole-pass failures raise/clear through the same
        # instance the daemon's command_failure_hook above uses.
        automation_alerts=automation_alerts,
    )
