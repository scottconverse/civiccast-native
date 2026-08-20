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
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civiccast.egress.daemon import AlertEvaluatorHook, EgressDaemon
from civiccast.egress.engine_select import build_encoder_strategy, gstreamer_engine_selected
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import ChannelAutomationRollup, EgressCommand, EgressProofEvent
from civiccast.egress.store import EgressStore
from civiccast.native.station_runtime import EGRESS_DEGRADED_REASON_ENV

if TYPE_CHECKING:
    from civiccast.alerting.models import AlertConditionKind

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

        session = session_factory()
        try:
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
        finally:
            session.close()
    except Exception:
        _LOG.exception(
            "raising the GStreamer egress-degraded alert failed; continuing -- "
            "alerting must never block control-plane startup."
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
    ) -> None:
        self._store = store
        self._daemon = daemon
        self._source_plan_provider = source_plan_provider
        self._settings = settings
        self._monotonic = monotonic or time.monotonic
        # Pacing prevents command storms WITHOUT the one-shot deadlock that
        # left a dark channel unstarted for an hour (issue #152, found live
        # in the CA-8 run): a dark auto_start channel is retried every
        # cooldown until it comes up. Reload keeps the per-period latch.
        self._start_retry_at: dict[str, float] = {}
        self._reload_issued: set[str] = set()
        # Audit ENG-002: reload re-issue pacing (see _check_slate_replan).
        self._replan_retry_at: dict[str, float] = {}
        # Issue #116: one supervised BYO-NDI relay per named channel.
        self._ndi_supervisor_factory = ndi_supervisor_factory or _default_ndi_factory
        self._ndi_relays: dict[str, Any] = {}
        # Issue #117: one supervised BYO-SDI relay per configured channel.
        self._sdi_supervisor_factory = sdi_supervisor_factory or _default_sdi_factory
        self._sdi_relays: dict[str, Any] = {}

    _START_RETRY_COOLDOWN_SECONDS = 30.0
    _RELOAD_RETRY_COOLDOWN_SECONDS = 30.0

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
        seen: list[str] = []
        for config in self._store.list_configs():
            if not config.enabled:
                continue
            channel_id = config.channel_id
            seen.append(channel_id)
            # Audit Critical (TEST-001): one channel's failure - a poisoned
            # relay config, a supervisor crash - must never starve the other
            # channels' supervision. Isolate per channel; the loop's outer
            # handler in run_forever still covers scan-level failures.
            try:
                self._run_channel_pass(config, channel_id, resolved_now)
            except Exception:
                _LOG.exception(
                    "Channel automation pass failed for %s; other channels "
                    "continue. Fix this channel's configuration or inspect "
                    "the error above.",
                    channel_id,
                )
        return seen

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
    from civiccast.egress.preparer import SourcePreparer
    from civiccast.egress.source_plan import ScheduleSourcePlanProvider
    from civiccast.egress.store import PostgresEgressStore
    from civiccast.egress.supervisor import PlayoutSupervisor
    from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
    from civiccast.egress.ts_relay import TsRelaySupervisor
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
    asset_store = PostgresAssetStore(session_factory)
    schedule_store = PostgresScheduleStore(session_factory)
    source_plan_provider = ScheduleSourcePlanProvider(
        schedule_items_provider=lambda channel_id: schedule_store.list(
            channel_id=channel_id,
            states=(SCHEDULE_STATE_PUBLISHED,),
        ),
        asset_resolver=asset_store.get_staff_row,
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
        # #156: the persistent conform cache emits playout-time trims when the
        # engine honors them — the default ffmpeg-concat engine does (ffconcat
        # inpoint/outpoint); the gst engine reads only segment.path, so it gets
        # the fast stream-copy fallback instead.
        source_preparer=SourcePreparer(
            work_dir=resolved_work_dir,
            playout_trim_supported=not gstreamer_engine_selected(),
        ).prepare,
        resolve_secret=lambda ref: os.environ.get(ref),
        # S15: ffmpeg-concat (default) or the GStreamer engine, per CIVICCAST_EGRESS_ENGINE.
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
        # guarded). Distinct from the trimmed proof-event ring buffer.
        as_run_recorder=StoreAsRunRecorder(ReportingStore(session_factory)),
    )
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
    )
