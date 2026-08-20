# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Egress daemon loop foundation."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol, cast

from civiccast.captions.tap import build_audio_tap_plan
from civiccast.egress.asrun import (
    AsRunCaptureSchemaError,
    AsRunRecorder,
    asset_id_for_segment,
    map_source_kind,
)
from civiccast.egress.branding import EgressBrandingPlan
from civiccast.egress.caption_embed import EgressCaptionEmbeddingPlan
from civiccast.egress.cg_bridge import (
    CG_EGRESS_PROOF_BOUNDARY,
    EgressCgOverlayClearProof,
    EgressCgOverlayProof,
    build_cg_overlay_clear_egress_proof,
)
from civiccast.egress.encoder_strategy import (
    ConcatEncoderStrategy,
    EncoderStartRequest,
    EncoderStrategy,
)
from civiccast.egress.errors import (
    ConfigInvalidError,
    EgressError,
    EncoderUnavailableError,
    SecretUnresolvedError,
    SourcePrepareError,
)
from civiccast.egress.health import (
    EgressEncoderMetrics,
    build_default_sink_health,
    read_latest_ffmpeg_encoder_metrics,
)
from civiccast.egress.models import (
    CaptionStatus,
    EgressCommand,
    EgressConfig,
    EgressHealthSample,
    EgressProofEvent,
    EgressSourcePlan,
    EgressState,
    EgressStateRow,
    redact_source_uri,
)
from civiccast.egress.pacing import UniformPacingLatch
from civiccast.egress.preparer import SourcePreparationReport
from civiccast.egress.process_identity import verify_and_kill_process
from civiccast.egress.runtime import (
    FfmpegStarter,
)
from civiccast.egress.schema_currency import current_schema_version
from civiccast.egress.sinks import SecretResolver
from civiccast.egress.store import EgressStore
from civiccast.stream._ffmpeg import FfmpegNotFoundError

SourcePlanProvider = Callable[[str], EgressSourcePlan | None]
FallbackSourceProvider = Callable[[EgressConfig], EgressSourcePlan]
SourcePreparerFunc = Callable[[EgressSourcePlan, EgressConfig], SourcePreparationReport]
BrandingPlanProvider = Callable[[str], EgressBrandingPlan | None]
CaptionPlanProvider = Callable[[str], EgressCaptionEmbeddingPlan | None]
CaptionStatusProvider = Callable[[str], CaptionStatus]
CaptionReadinessProvider = Callable[[str], Any]
CgOverlayProofProvider = Callable[[str], EgressCgOverlayProof | None]
#: S15 §5 CG-lite: (channel_id, config) → board raster for the engine overlay.
#: Takes the config because the raster must match ``canonical_profile`` geometry.
BoardOverlayProvider = Callable[[str, EgressConfig], Path | None]
SinkHealthProvider = Callable[[str, EgressConfig, EgressEncoderMetrics], dict[str, bool]]
AlertEvaluatorHook = Callable[[str, EgressState, "float | None", "float | None"], None]
"""(channel_id, state, encoder_fps, encoder_bitrate_kbps) → None. S8 alert hook."""
IndependentSlateStrategyFactory = Callable[[], "EncoderStrategy | None"]
"""() → an encoder strategy that does not depend on the `ffmpeg` binary being on
PATH, or None if no such strategy is available in this deployment. See
``_default_independent_slate_strategy`` (K2-1 follow-up, P1)."""

_LOG = logging.getLogger(__name__)


def _default_independent_slate_strategy() -> EncoderStrategy | None:
    """Best-effort construction of an ffmpeg-PATH-independent encoder, used only
    as the last-resort slate retry after a ``FfmpegNotFoundError`` (K2-1 follow-up,
    P1 audit finding).

    ``civiccast.stream._ffmpeg._ffmpeg_path()`` is a pure ``shutil.which("ffmpeg")``
    PATH lookup: it is completely content-independent, so it returns the identical
    result on every call within one process regardless of which source plan (the
    program, or the fallback slate) is being encoded. Retrying the SAME
    ``ConcatEncoderStrategy`` instance against the slate plan is therefore
    guaranteed to raise the identical ``FfmpegNotFoundError`` again -- the
    "advance the ladder to slate" claim for this specific exception was never
    reachable through the real strategy, only through a fake test double that
    could not exist in production (audit finding: the regression test asserted a
    state the real strategy cannot enter).

    ``GstPlayoutStrategy`` is a genuinely separate encoder: it launches a
    per-channel GStreamer worker subprocess and never calls ``_ffmpeg_path()`` or
    shells out to the ``ffmpeg`` binary at all, so it is a real independent
    fallback rather than a second attempt at the one already known to be
    unusable. Returns None (falls through to the existing zero-ffmpeg-floor ERROR
    handling, unchanged from before this fix) when the GStreamer engine's package
    is not importable in this deployment, or its construction fails for any
    reason -- this must never raise past the caller.
    """
    try:
        from civiccast.egress.gst.strategy import GstPlayoutStrategy
    except ImportError:
        return None
    try:
        return GstPlayoutStrategy()
    except Exception:
        return None


# S9-5 crash-relaunch back-off. The first crash relaunches immediately (fast
# recovery for a one-off); a crash that recurs within the cooldown is a churn
# signal (typically a worker that dies at startup — a bad graph, a missing
# element) and is paced instead of hot-looped. A worker that stays up at least
# _RESTART_STREAK_RESET_UPTIME_S resets the streak (the failure was transient,
# not a loop). NOTE: the restart cooldown (15s) and the engine's stall timeout
# (CIVICCAST_STALL_TIMEOUT_S, default 10s) are independent constants. A worker
# that keeps stalling restarts on roughly the cooldown cadence — its ~stall-
# timeout-long no-output cycle is under the 15s cooldown, so every relaunch after
# the first is paced rather than passed straight through. That pacing IS the
# intended anti-churn behavior (a persistently-dead source must not hot-loop).
_RESTART_COOLDOWN_SECONDS = 15.0
_RESTART_STREAK_RESET_UPTIME_S = 60.0
# Emit an escalation proof event at this restart streak and every multiple after
# (the S8 alerting hook — the actual alert dispatch is wired when S8 lands, build
# step 4; until then the escalation is durably recorded as a proof event).
_RESTART_ESCALATION_STREAK = 5


# RAT-004: poll cadence for stop_all_channels' observed-exit wait loop.
_DRAIN_POLL_INTERVAL_SECONDS = 0.05


class ChannelDrainOutcome(NamedTuple):
    """One channel's result from :meth:`EgressDaemon.stop_all_channels`."""

    channel_id: str
    outcome: str  # "drained" | "killed_after_deadline" | "already_gone"


class DrainResult(NamedTuple):
    """Per-channel outcomes of a :meth:`EgressDaemon.stop_all_channels` call."""

    outcomes: tuple[ChannelDrainOutcome, ...]


class OrphanInfo(NamedTuple):
    """Identity of a running process a reaper is considering (audit ENG-001).

    ``created_at`` is the process start time (epoch seconds); reapers only
    touch processes created BEFORE this server booted, and terminators
    re-verify it so a recycled pid is never killed (pid-reuse TOCTOU).
    """

    name: str
    created_at: float


class EgressDaemon:
    """Consume egress commands and run the configured output encoder."""

    def __init__(
        self,
        store: EgressStore,
        *,
        work_dir: Path,
        source_plan_provider: SourcePlanProvider,
        fallback_source_provider: FallbackSourceProvider | None = None,
        source_preparer: SourcePreparerFunc | None = None,
        branding_plan_provider: BrandingPlanProvider | None = None,
        cg_overlay_provider: BoardOverlayProvider | None = None,
        caption_plan_provider: CaptionPlanProvider | None = None,
        caption_status_provider: CaptionStatusProvider | None = None,
        caption_readiness_provider: CaptionReadinessProvider | None = None,
        cg_overlay_proof_provider: CgOverlayProofProvider | None = None,
        sink_health_provider: SinkHealthProvider | None = None,
        alert_evaluator_hook: AlertEvaluatorHook | None = None,
        encoder_strategy: EncoderStrategy | None = None,
        independent_slate_strategy_factory: IndependentSlateStrategyFactory | None = None,
        resolve_secret: SecretResolver | None = None,
        ffmpeg_starter: FfmpegStarter | None = None,
        orphan_probe: Callable[[int], OrphanInfo | None] | None = None,
        orphan_terminator: Callable[[int, float], None] | None = None,
        as_run_recorder: AsRunRecorder | None = None,
        restart_cooldown_seconds: float = _RESTART_COOLDOWN_SECONDS,
        monotonic: Callable[[], float] | None = None,
        ts_relay_supervisor: Any | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._store = store
        # Single injectable monotonic clock for all crash-relaunch timing (the
        # restart latch + worker uptime), so tests drive the back-off deterministically
        # through the constructor instead of reaching into private state.
        self._monotonic = monotonic or time.monotonic
        # #151: persistent per-channel TS relay so encoder relaunches never
        # reset the mux session at a udp-ts headend. None = pass-through.
        self._ts_relay = ts_relay_supervisor
        self._work_dir = work_dir
        self._source_plan_provider = source_plan_provider
        self._fallback_source_provider = fallback_source_provider
        self._source_preparer = source_preparer
        self._branding_plan_provider = branding_plan_provider
        # S15 §5 CG-lite: per-channel board raster for the engine overlay leg.
        self._cg_overlay_provider = cg_overlay_provider
        self._caption_plan_provider = caption_plan_provider
        self._caption_status_provider = caption_status_provider
        self._caption_readiness_provider = caption_readiness_provider
        self._cg_overlay_proof_provider = cg_overlay_proof_provider
        self._sink_health_provider = sink_health_provider
        self._alert_evaluator_hook = alert_evaluator_hook
        self._encoder_strategy = encoder_strategy or ConcatEncoderStrategy()
        # K2-1 follow-up (P1): factory, not an instance, so a real GStreamer worker
        # is never constructed unless a FfmpegNotFoundError actually needs it. Tests
        # inject a fake factory instead of a fake encoder_strategy so the injected
        # double represents a genuinely SEPARATE encoder, matching production.
        self._independent_slate_strategy_factory = (
            independent_slate_strategy_factory or _default_independent_slate_strategy
        )
        self._resolve_secret = resolve_secret
        self._ffmpeg_starter = ffmpeg_starter
        self._processes: dict[str, object] = {}
        self._started_at: dict[str, float] = {}
        # S9-5 crash-relaunch back-off: a latch paces rapid repeat relaunches, a
        # per-channel streak counts consecutive rapid crashes (for escalation +
        # reset on healthy uptime), and _backoff_relaunch holds a deferred relaunch
        # (committed (prev_state, prev_source_label)) until the latch permits it.
        # RAT-004: injectable sleep for the drain-all deadline-wait loop (mirrors
        # the ``monotonic`` seam above) so tests drive it deterministically
        # without a real wall-clock wait.
        self._sleep = sleep or time.sleep
        self._restart_latch = UniformPacingLatch(
            default_cooldown_seconds=restart_cooldown_seconds, clock=self._monotonic
        )
        self._restart_streak: dict[str, int] = {}
        self._backoff_relaunch: dict[str, tuple[str, str | None]] = {}
        self._draining_channels: set[str] = set()
        self._pending_reloads: dict[str, tuple[str | None, str | None]] = {}
        # Issue #157: channels whose encoder WE terminated for a filler
        # reload - their non-zero exit still honors the pending reload.
        self._reload_kills: set[str] = set()
        # Issue #161: a server restart leaves the previous server's encoder
        # children streaming to the sink ports; before starting fresh, the
        # daemon reaps any still-running ffmpeg pid from the durable state
        # row. Seams default to psutil implementations.
        self._orphan_probe = orphan_probe or _default_orphan_probe
        self._orphan_terminator = orphan_terminator or _default_orphan_terminator
        # S23 as-run capture: optional append-only side-write at each ACTUAL
        # source transition (None on the test/CLI in-memory path). Capture is
        # fail-safe — _record_as_run_transition guards every call so a recorder
        # error never breaks the playout path.
        self._as_run_recorder = as_run_recorder
        # S23 §6.1 schema-drift flag (E-1): set when the recorder raises
        # AsRunCaptureSchemaError so the daemon can mark a degraded-mode marker
        # without crashing the playout path. Toggling this is loud (an ERROR
        # log + a distinct message) so silent loss of the as-aired ledger is
        # impossible — the very failure mode S23 §6.1 exists to prevent.
        self._as_run_schema_drift = False
        # Reap guard (audit ENG-001): only processes created before this
        # daemon existed can be a predecessor's orphans.
        self._boot_epoch = time.time()
        self._stderr_logs: dict[str, Path] = {}
        self._last_loudness_lufs: dict[str, float] = {}
        self._active_cg_overlay_ids: dict[str, str] = {}
        self._last_cg_overlay_event_keys: dict[str, tuple[str, str, str | None]] = {}

    def process_once(self, channel_id: str) -> int:
        """Process all currently queued commands for one channel."""

        self._poll_process(channel_id)
        self._service_backoff_relaunch(channel_id)
        commands = self._store.pop_pending_commands(channel_id)
        for command in commands:
            self._process_command(command)
        return len(commands)

    def has_live_process(self, channel_id: str) -> bool:
        """True when THIS daemon instance tracks a live encoder process.

        CA-2 channel automation uses this for the auto-start pass: a flagged
        channel with no live process (fresh app start, or a stop the operator
        issued) is a candidate for a re-issued start command.
        """

        process = self._processes.get(channel_id)
        return process is not None and _process_poll(process) is None

    def send_caption_cue(
        self,
        channel_id: str,
        work_dir: Path,
        *,
        text: str,
        pts_seconds: float,
        duration_seconds: float,
        delivery_id: str,
    ) -> bool:
        """Send a cue through the encoder strategy that owns the live worker.

        Native Windows keeps each worker's duplex named-pipe server on the
        strategy instance that started that worker.  A newly constructed
        strategy cannot reach those pipes, so the caption feed must delegate
        through this daemon's existing strategy instance.
        """

        sender = getattr(self._encoder_strategy, "send_caption_cue", None)
        if not callable(sender):
            return False
        return bool(
            sender(
                channel_id,
                work_dir,
                text=text,
                pts_seconds=pts_seconds,
                duration_seconds=duration_seconds,
                delivery_id=delivery_id,
            )
        )

    def _process_command(self, command: EgressCommand) -> None:
        # An explicit operator/automation command supersedes any deferred crash
        # back-off relaunch still waiting on the latch: clear it so a start that
        # then ERRORs (e.g. an unresolved secret) can't be silently resurrected
        # later by the automatic relaunch the operator was trying to replace.
        self._backoff_relaunch.pop(command.channel_id, None)
        if command.action == "start":
            self._start(command.channel_id)
            return
        if command.action == "stop":
            self._stop(command.channel_id, draining=False)
            if self._ts_relay is not None:
                # Operator stop = the channel is leaving air; the relay's
                # session ends WITH the channel (relaunches never come here).
                self._ts_relay.stop_channel(command.channel_id)
            self._write_state(command.channel_id, "STOPPED")
            return
        if command.action == "drain":
            self._drain(command.channel_id)
            return
        if command.action == "reload":
            self._request_reload(command.channel_id)
            return
        raise ConfigInvalidError(f"unsupported egress command action: {command.action}")

    def _start(
        self,
        channel_id: str,
        *,
        previous_state: str | None = None,
        previous_source_label: str | None = None,
    ) -> None:
        try:
            config = self._store.get_config(channel_id)
            if config is None:
                raise ConfigInvalidError("No egress configuration exists for this channel.")
            if not config.enabled:
                raise ConfigInvalidError("Egress is disabled for this channel.")
            if self._ts_relay is not None:
                # #151: route udp-ts sinks through the channel-lifetime relay so
                # this (re)launch splices into ONE continuous mux session.
                config = self._ts_relay.apply(config)
            existing_process = self._processes.get(channel_id)
            if existing_process is not None and _process_poll(existing_process) is None:
                state = self._store.read_state(channel_id)
                current_state: EgressState = (
                    "DRAINING" if channel_id in self._draining_channels else "ON_AIR"
                )
                self._write_state(
                    channel_id,
                    current_state,
                    current_source_label=state.current_source_label if state else None,
                    pid=_process_pid(existing_process),
                )
                self._append_health(
                    channel_id,
                    current_state,
                    sink_connected=self._sink_connected(
                        channel_id,
                        config,
                        state=current_state,
                    ),
                    seconds_on_air=self._seconds_on_air(channel_id),
                )
                return
            self._reap_orphan(channel_id)
            using_fallback_slate = False
            fallback_reason: str | None = None
            readiness = (
                self._caption_readiness_provider(channel_id)
                if self._caption_readiness_provider is not None
                else None
            )
            if readiness is not None and not getattr(readiness, "ready", True):
                reason = getattr(readiness, "refusal_reason", None) or "caption-readiness-refused"
                fallback_reason = f"caption storage refused: {reason}"
                if not getattr(readiness, "requires_fallback_slate", False):
                    raise ConfigInvalidError(fallback_reason)
                if self._fallback_source_provider is None:
                    self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                    self._append_health(channel_id, "FALLBACK_SLATE", sink_connected={})
                    return
                self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                # Annotated because this is the FIRST binding of source_plan and
                # the fallback provider returns a plain EgressSourcePlan, while
                # _source_plan_provider below returns EgressSourcePlan | None.
                # Without it mypy fixed the narrower type here, rejected the
                # assignment at the `else` branch, and then treated the
                # `if source_plan is None` slate guard below as unreachable --
                # leaving the daemon's whole no-plan fallback path unchecked.
                source_plan: EgressSourcePlan | None = self._fallback_source_provider(config)
                using_fallback_slate = True
            else:
                try:
                    source_plan = self._source_plan_provider(channel_id)
                except SourcePrepareError as exc:
                    if self._fallback_source_provider is None:
                        raise
                    fallback_reason = str(exc)
                    self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                    source_plan = self._fallback_source_provider(config)
                    using_fallback_slate = True
            if source_plan is None:
                if self._fallback_source_provider is None:
                    self._write_state(
                        channel_id,
                        "FALLBACK_SLATE",
                        last_error=(
                            "No valid source plan is available. Slate generation is required "
                            "before this channel can go on air."
                        ),
                    )
                    self._append_health(channel_id, "FALLBACK_SLATE", sink_connected={})
                    return
                fallback_reason = "No valid source plan is available; generated fallback slate."
                self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                source_plan = self._fallback_source_provider(config)
                using_fallback_slate = True
            if source_plan.channel_id != channel_id:
                raise ConfigInvalidError(
                    f"Source plan channel {source_plan.channel_id!r} does not match "
                    f"requested channel {channel_id!r}."
                )
            if self._source_preparer is not None:
                try:
                    preparation_report = self._source_preparer(source_plan, config)
                    source_plan = preparation_report.source_plan
                    self._record_prepared_loudness(channel_id, preparation_report)
                except SourcePrepareError as exc:
                    if self._fallback_source_provider is None:
                        raise
                    fallback_reason = str(exc)
                    self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                    source_plan = self._fallback_source_provider(config)
                    using_fallback_slate = True
                    self._last_loudness_lufs.pop(channel_id, None)
            else:
                self._last_loudness_lufs.pop(channel_id, None)

            self._write_state(channel_id, "STARTING")
            branding_plan = (
                self._branding_plan_provider(channel_id)
                if self._branding_plan_provider is not None
                else None
            )
            caption_plan = (
                self._caption_plan_provider(channel_id)
                if self._caption_plan_provider is not None
                else None
            )
            running_state: EgressState = "FALLBACK_SLATE" if using_fallback_slate else "ON_AIR"
            if previous_state in {"ON_AIR", "FALLBACK_SLATE"}:
                transition_event = self._build_proof_event(
                    channel_id=channel_id,
                    state="TRANSITIONING",
                    source_plan=source_plan,
                    previous_state=previous_state,
                    previous_source_label=previous_source_label,
                )
                self._store.append_proof_event(transition_event)
                self._write_state(
                    channel_id,
                    "TRANSITIONING",
                    current_source_label=source_plan.segments[0].label,
                    current_proof_event_id=transition_event.event_id,
                    pid=None,
                )
            self._write_state(
                channel_id,
                running_state,
                current_source_label=source_plan.segments[0].label,
                pid=None,
                last_error=fallback_reason if using_fallback_slate else None,
            )

            def _encoder_request(plan: EgressSourcePlan) -> EncoderStartRequest:
                return EncoderStartRequest(
                    channel_id=channel_id,
                    source_plan=plan,
                    config=config,
                    work_dir=self._work_dir,
                    resolve_secret=self._resolve_secret,
                    branding_plan=branding_plan,
                    caption_plan=caption_plan,
                    # Live caption tap (Beta B6, option A): env-configured
                    # audio fork rides the same encoder process.
                    audio_tap_plan=build_audio_tap_plan(channel_id),
                    ffmpeg_starter=self._ffmpeg_starter,
                    cg_overlay_image=(
                        self._cg_overlay_provider(channel_id, config)
                        if self._cg_overlay_provider is not None
                        else None
                    ),
                )

            try:
                encoder_result = self._encoder_strategy.start(_encoder_request(source_plan))
            except (EncoderUnavailableError, FfmpegNotFoundError) as exc:
                # Degraded-mode tier 4 (owner ruling: dead air is the cardinal
                # sin, NEVER acceptable). The encoder itself could not start --
                # e.g. GStreamer already fell back to FFmpeg and FFmpeg egress
                # ALSO failed (EncoderUnavailableError), OR the FFmpeg tier
                # itself has no ffmpeg binary on PATH (FfmpegNotFoundError --
                # audit K2-1: this used to escape straight past this seam to
                # the outer ERROR handler below, skipping the slate tier
                # entirely). Both are tier failures of the SAME ladder, so
                # both land here. Rather than dropping the channel to
                # ERROR/black, put up the existing fallback SLATE ("technical
                # difficulties") as the absolute last resort: rebuild the
                # request against the slate source plan and try the encoder
                # once more. Only ERROR (dead air) if there is no fallback
                # provider, we were ALREADY airing the slate (so the slate
                # itself is what failed), or the slate encode also fails --
                # e.g. ffmpeg is genuinely absent from the machine, so no
                # tier (program OR slate) can be encoded. That is the true
                # zero-ffmpeg floor: the outer handler below still catches
                # FfmpegNotFoundError and lands the channel on ERROR with
                # last_error set and health appended -- a no-crash state with
                # operator alerting, never a crash and never a silent hang.
                if self._fallback_source_provider is None or using_fallback_slate:
                    raise
                _LOG.error(
                    "channel %s: egress encoder unavailable (%s); falling back to the "
                    "technical-difficulties slate rather than dead air.",
                    channel_id,
                    exc,
                )
                fallback_reason = f"egress encoder unavailable; aired fallback slate: {exc}"
                source_plan = self._fallback_source_provider(config)
                using_fallback_slate = True
                running_state = "FALLBACK_SLATE"
                self._write_state(channel_id, running_state, last_error=fallback_reason)
                # K2-1 follow-up (P1): FfmpegNotFoundError is a pure PATH lookup with
                # no dependence on the source plan being encoded, so retrying THIS
                # SAME strategy is guaranteed to fail identically again -- see
                # _default_independent_slate_strategy's docstring. Route the slate
                # retry through a genuinely separate, ffmpeg-independent encoder in
                # that specific case. EncoderUnavailableError has no such guarantee
                # (e.g. a hardware-encoder probe outcome can legitimately differ
                # between the program and slate content), so it keeps retrying the
                # original strategy unchanged.
                retry_strategy = self._encoder_strategy
                if isinstance(exc, FfmpegNotFoundError):
                    independent_strategy = self._independent_slate_strategy_factory()
                    if independent_strategy is not None:
                        retry_strategy = independent_strategy
                encoder_result = retry_strategy.start(_encoder_request(source_plan))
            self._stderr_logs[channel_id] = encoder_result.stderr_path
            process = encoder_result.process
            self._processes[channel_id] = process
            self._started_at[channel_id] = self._monotonic()
            proof_event = self._build_proof_event(
                channel_id=channel_id,
                state=running_state,
                source_plan=source_plan,
                previous_state=previous_state,
                previous_source_label=previous_source_label,
            )
            self._store.append_proof_event(proof_event)
            self._record_as_run_transition(
                channel_id=channel_id,
                running_state=running_state,
                source_plan=source_plan,
                proof_event=proof_event,
            )
            self._sync_cg_overlay_proof(channel_id, running_state)
            self._write_state(
                channel_id,
                running_state,
                current_source_label=source_plan.segments[0].label,
                current_proof_event_id=proof_event.event_id,
                pid=_process_pid(process),
                last_error=fallback_reason if using_fallback_slate else None,
            )
            self._append_health(
                channel_id,
                running_state,
                sink_connected=self._sink_connected(channel_id, config, state=running_state),
                seconds_on_air=0,
            )
        except (ConfigInvalidError, SecretUnresolvedError, FfmpegNotFoundError) as exc:
            # FfmpegNotFoundError only reaches here when the ladder's own
            # tier-failure seam above already tried (or could not try) the
            # slate tier -- see the comment there. This is the documented
            # zero-ffmpeg floor: no crash, ERROR state with last_error set,
            # health appended, so the operator is alerted instead of the
            # channel silently hanging or the supervisor crashing.
            self._write_state(channel_id, "ERROR", last_error=str(exc))
            self._append_health(channel_id, "ERROR", sink_connected={})
        except EgressError as exc:
            self._write_state(channel_id, "ERROR", last_error=str(exc))
            self._append_health(channel_id, "ERROR", sink_connected={})

    def _write_state(
        self,
        channel_id: str,
        state: EgressState,
        *,
        current_source_label: str | None = None,
        current_proof_event_id: str | None = None,
        last_error: str | None = None,
        pid: int | None = None,
    ) -> None:
        self._store.write_state(
            EgressStateRow(
                channel_id=channel_id,
                state=state,
                current_source_label=current_source_label,
                current_proof_event_id=current_proof_event_id,
                updated_at=datetime.now(UTC),
                pid=pid,
                last_error=last_error,
            )
        )

    def _append_health(
        self,
        channel_id: str,
        state: EgressState,
        *,
        sink_connected: dict[str, bool],
        dropped_frames: int = 0,
        seconds_on_air: int = 0,
    ) -> None:
        metrics = self._health_metrics(channel_id, state=state)
        # S9: stamp the running schema version + the proof-event churn since the last
        # sample (operator skew + churn-loop visibility).
        last_health = self._store.recent_health(channel_id, 1)
        since = last_health[0].sampled_at if last_health else None
        self._store.append_health(
            EgressHealthSample(
                channel_id=channel_id,
                sampled_at=datetime.now(UTC),
                state=state,
                sink_connected=sink_connected,
                encoder_fps=metrics.encoder_fps,
                encoder_bitrate_kbps=metrics.encoder_bitrate_kbps,
                dropped_frames=(
                    metrics.dropped_frames if metrics.dropped_frames is not None else dropped_frames
                ),
                seconds_on_air=seconds_on_air,
                last_loudness_lufs=self._last_loudness_lufs.get(channel_id),
                caption_status=(
                    self._caption_status_provider(channel_id)
                    if self._caption_status_provider is not None
                    else "not-verified"
                ),
                schema_version=current_schema_version(),
                proof_events_appended_since_last_sample=self._store.count_proof_events_since(
                    channel_id, since
                ),
            )
        )
        # S8-3: alert evaluator hook — derive conditions from the just-written sample.
        if self._alert_evaluator_hook is not None:
            self._alert_evaluator_hook(
                channel_id, state, metrics.encoder_fps, metrics.encoder_bitrate_kbps
            )

    def _record_prepared_loudness(
        self,
        channel_id: str,
        preparation_report: SourcePreparationReport,
    ) -> None:
        for record in reversed(preparation_report.records):
            if record.measured_lufs is not None:
                self._last_loudness_lufs[channel_id] = record.measured_lufs
                return
        self._last_loudness_lufs.pop(channel_id, None)

    def _health_metrics(self, channel_id: str, *, state: str) -> EgressEncoderMetrics:
        if state not in {"ON_AIR", "TRANSITIONING", "FALLBACK_SLATE", "DRAINING"}:
            return EgressEncoderMetrics()
        log_path = self._stderr_logs.get(channel_id)
        if log_path is None:
            return EgressEncoderMetrics()
        return read_latest_ffmpeg_encoder_metrics(log_path)

    def _build_proof_event(
        self,
        *,
        channel_id: str,
        state: str,
        source_plan: EgressSourcePlan,
        previous_state: str | None = None,
        previous_source_label: str | None = None,
    ) -> EgressProofEvent:
        segment = source_plan.segments[0]
        return EgressProofEvent(
            event_id=f"egress-proof-{uuid.uuid4()}",
            observed_at=datetime.now(UTC),
            channel_id=channel_id,
            state=state,  # type: ignore[arg-type]
            source_label=segment.label,
            # ENG-003: a live segment's path is an ingest URI that can carry an SRT
            # passphrase / RTMP key / RTSP credentials — redact before it lands in the
            # durable, operator-readable proof chain.
            source_path=redact_source_uri(segment.path),
            source_ref=segment.source_ref,
            proof_boundary="civiccast-egress-handoff-boundary",
            machine_summary=(
                _proof_event_summary(
                    state=state,
                    previous_state=previous_state,
                    previous_source_label=previous_source_label,
                    source_kind=segment.kind,
                    source_label=segment.label,
                    channel_id=channel_id,
                )
            ),
        )

    def _record_as_run_transition(
        self,
        *,
        channel_id: str,
        running_state: str,
        source_plan: EgressSourcePlan,
        proof_event: EgressProofEvent,
    ) -> None:
        """Append an as-run entry for an ACTUAL source transition (S23 §6.1).

        Called immediately after the engine emits an ON_AIR/FALLBACK_SLATE
        proof event (the on-air instant). Append-only side-effect — never raises
        into the playout path (the recorder also guards internally; this is the
        engine-side belt-and-suspenders, parallel to the proof-event auditing).
        """
        if self._as_run_recorder is None:
            return
        try:
            segment = source_plan.segments[0]
            source_kind = map_source_kind(segment_kind=segment.kind, running_state=running_state)
            self._as_run_recorder.record_transition(
                channel_id=channel_id,
                source_kind=source_kind,
                asset_id=asset_id_for_segment(source_plan=source_plan, source_kind=source_kind),
                source_label=segment.label,
                actual_start=proof_event.observed_at,
                proof_event_id=proof_event.event_id,
            )
        except AsRunCaptureSchemaError:
            # Schema drift on the engine→ledger seam (E-1). Loud, not silent:
            # mark degraded mode + log at ERROR so an operator sees the as-run
            # ledger is paused while playout continues.
            self._as_run_schema_drift = True
            _LOG.error(
                "as-run capture schema drift; playout safe; ledger paused (channel %s)",
                channel_id,
            )
        except Exception:  # auditing must never block the playout path
            _LOG.exception(
                "As-run capture failed for channel %s; playout is unaffected.",
                channel_id,
            )

    def _close_as_run(self, channel_id: str) -> None:
        """Close the channel's open as-run row at a terminal state (clean stop,
        error, drain) — the channel left air with no new source taking over.
        Fail-safe; a no-op when no recorder is wired or no row is open."""
        if self._as_run_recorder is None:
            return
        try:
            self._as_run_recorder.close_open(channel_id=channel_id, actual_end=datetime.now(UTC))
        except AsRunCaptureSchemaError:
            # Schema drift on close (E-1). Same loud-not-silent contract as the
            # record path.
            self._as_run_schema_drift = True
            _LOG.error(
                "as-run capture schema drift; playout safe; ledger paused (channel %s)",
                channel_id,
            )
        except Exception:  # auditing must never block the playout path
            _LOG.exception(
                "As-run close failed for channel %s; playout is unaffected.",
                channel_id,
            )

    def _poll_process(self, channel_id: str) -> None:
        process = self._processes.get(channel_id)
        if process is None:
            return
        returncode = _process_poll(process)
        if returncode is None:
            state = self._store.read_state(channel_id)
            config = self._store.get_config(channel_id)
            if channel_id in self._draining_channels:
                current_state: EgressState = "DRAINING"
            elif channel_id in self._pending_reloads:
                current_state = "TRANSITIONING"
            elif state and state.state == "FALLBACK_SLATE":
                current_state = "FALLBACK_SLATE"
            else:
                current_state = "ON_AIR"
            self._append_health(
                channel_id,
                current_state,
                sink_connected=(
                    self._sink_connected(channel_id, config, state=current_state) if config else {}
                ),
                seconds_on_air=self._seconds_on_air(channel_id),
            )
            self._write_state(
                channel_id,
                current_state,
                current_source_label=state.current_source_label if state else None,
                current_proof_event_id=state.current_proof_event_id if state else None,
                pid=_process_pid(process),
            )
            self._sync_cg_overlay_proof(channel_id, current_state)
            if self._seconds_on_air(channel_id) >= _RESTART_STREAK_RESET_UPTIME_S and (
                channel_id in self._restart_streak
                or channel_id in self._backoff_relaunch
                or self._restart_latch.next_allowed_at(channel_id) != 0.0
            ):
                # The worker has stayed up healthily — any earlier crash streak was
                # transient, not a loop; clear it so the next crash relaunches at once.
                # Guarded so it fires once per healthy stretch (when there is state to
                # clear) rather than force-resetting the latch on every ~2s poll.
                self._reset_restart_tracking(channel_id)
            return
        started_at = self._started_at.get(channel_id)
        uptime = None if started_at is None else max(0.0, self._monotonic() - started_at)
        self._processes.pop(channel_id, None)
        self._started_at.pop(channel_id, None)
        was_draining = channel_id in self._draining_channels
        self._draining_channels.discard(channel_id)
        # A deliberate filler kill (issue #157) exits non-zero on real
        # ffmpeg; it still flows into the pending reload, not crash relaunch.
        deliberate_kill = channel_id in self._reload_kills
        self._reload_kills.discard(channel_id)
        pending_reload = (
            self._pending_reloads.pop(channel_id, None)
            if returncode == 0 or deliberate_kill
            else None
        )
        _process_close(process)
        if pending_reload is not None:
            previous_state, previous_source_label = pending_reload
            # Audit ENG-001: the state row still carries the just-exited
            # encoder's pid; clear it BEFORE the fresh start so the orphan
            # reap never probes a freed pid on this hot path.
            self._write_state(
                channel_id,
                "STARTING",
                current_source_label=previous_source_label,
                pid=None,
            )
            self._start(
                channel_id,
                previous_state=previous_state,
                previous_source_label=previous_source_label,
            )
            return
        if returncode == 0:
            self._reset_restart_tracking(channel_id)  # clean exit — fresh slate
            self._clear_cg_overlay_proof(channel_id, "STOPPED")
            self._close_as_run(channel_id)  # the channel left air — close the open row
            if was_draining and self._ts_relay is not None:
                # Drain completed = the channel intentionally left air; a
                # natural plan-end (automation restarts next tick) keeps the
                # relay so the relaunch splices into the same mux session.
                self._ts_relay.stop_channel(channel_id)
            self._write_state(channel_id, "STOPPED")
            self._append_health(channel_id, "STOPPED", sink_connected={})
            return
        self._pending_reloads.pop(channel_id, None)
        state = self._store.read_state(channel_id)
        if state is not None and state.state in {"ON_AIR", "FALLBACK_SLATE", "TRANSITIONING"}:
            self._relaunch_after_crash(channel_id, state, uptime)
            return
        self._reset_restart_tracking(channel_id)
        self._clear_cg_overlay_proof(channel_id, "ERROR")
        self._close_as_run(channel_id)  # terminal error — close the open row
        self._write_state(
            channel_id,
            "ERROR",
            last_error="FFmpeg exited non-zero; inspect daemon logs before retrying.",
        )
        self._append_health(channel_id, "ERROR", sink_connected={}, dropped_frames=0)

    def _relaunch_after_crash(
        self, channel_id: str, state: EgressStateRow, uptime: float | None
    ) -> None:
        """Crash-relaunch with back-off (S9-5). The first crash relaunches at once;
        a crash recurring within the cooldown is paced (a deferred relaunch the
        ``process_once`` tick services once the latch permits) so a worker that keeps
        dying at startup can't hot-loop. A worker that ran healthily resets the streak."""
        streak = self._restart_streak.get(channel_id, 0)
        if uptime is not None and uptime >= _RESTART_STREAK_RESET_UPTIME_S:
            # Belt-and-suspenders with the healthy-poll reset in _poll_process: that
            # path clears the streak while the worker is RUNNING healthily; this one
            # covers a worker that ran healthily and then crashed in the SAME gap
            # between polls (so the poll-reset never saw it). Either way a fresh
            # failure after a healthy run is streak 1 → immediate relaunch.
            streak = 0
        streak += 1
        self._restart_streak[channel_id] = streak
        failure_event = self._append_encoder_child_failure_event(channel_id, state)
        proof_event_id = failure_event.event_id
        if streak >= _RESTART_ESCALATION_STREAK and streak % _RESTART_ESCALATION_STREAK == 0:
            # S8 hook: durably record the escalation now; alert dispatch lands in S8.
            escalation = self._append_restart_escalation_event(channel_id, state, streak)
            proof_event_id = escalation.event_id
        if self._restart_latch.should_run_now(channel_id):
            self._begin_relaunch(
                channel_id, state.state, state.current_source_label, proof_event_id
            )
        else:
            # Within the cooldown after a recent relaunch — defer instead of hot-looping.
            self._backoff_relaunch[channel_id] = (state.state, state.current_source_label)
            self._write_state(
                channel_id,
                "STARTING",
                current_source_label=state.current_source_label,
                current_proof_event_id=proof_event_id,
                last_error=(
                    f"Encoder exited non-zero repeatedly (restart #{streak}); backing off "
                    "before relaunch to avoid a crash loop."
                ),
            )
            self._append_health(channel_id, "STARTING", sink_connected={}, dropped_frames=0)

    def _service_backoff_relaunch(self, channel_id: str) -> None:
        """Fire a deferred crash-relaunch once the back-off latch permits. Driven by
        every ``process_once`` tick (automation polls each enabled channel), so a paced
        relaunch lands without any dedicated timer."""
        pending = self._backoff_relaunch.get(channel_id)
        if pending is None:
            return
        if channel_id in self._processes:  # something already brought it back
            self._backoff_relaunch.pop(channel_id, None)
            return
        if not self._restart_latch.should_run_now(channel_id):
            return  # still cooling down
        self._backoff_relaunch.pop(channel_id, None)
        previous_state, previous_source_label = pending
        state = self._store.read_state(channel_id)
        proof_event_id = state.current_proof_event_id if state else None
        self._begin_relaunch(channel_id, previous_state, previous_source_label, proof_event_id)

    def _begin_relaunch(
        self,
        channel_id: str,
        previous_state: str,
        previous_source_label: str | None,
        proof_event_id: str | None,
    ) -> None:
        self._write_state(
            channel_id,
            "STARTING",
            current_source_label=previous_source_label,
            current_proof_event_id=proof_event_id,
            last_error="FFmpeg child exited non-zero; relaunching encoder.",
        )
        self._append_health(channel_id, "STARTING", sink_connected={}, dropped_frames=0)
        self._start(
            channel_id,
            previous_state=previous_state,
            previous_source_label=previous_source_label,
        )
        # CC-WS5-006: a crash-relaunch brings up a FRESH worker on a fresh control
        # pipe. Replay the channel's desired state (reload/swap) over it so a swap
        # or content-reload that was live before the crash is restored rather than
        # silently lost. Optional strategy capability (only the GStreamer worker-pipe
        # strategy carries a control channel) — resolved via getattr like
        # send_command; a no-op on POSIX / for a strategy without the seam.
        self._reconnect_worker_channel(channel_id)

    def _reconnect_worker_channel(self, channel_id: str) -> None:
        reconnect = getattr(self._encoder_strategy, "reconnect_channel", None)
        if callable(reconnect):
            reconnect(channel_id)

    def _close_worker_channel(self, channel_id: str) -> None:
        """Release a channel's worker control pipe (CC-WS5-006). Optional strategy
        capability resolved via getattr; a no-op on POSIX / for a strategy without
        a worker-pipe seam / for an unknown channel."""
        close_channel = getattr(self._encoder_strategy, "close_channel", None)
        if callable(close_channel):
            close_channel(channel_id)

    def _reset_restart_tracking(self, channel_id: str) -> None:
        """Clear crash-relaunch back-off state — the channel reached a good state
        (clean stop, error terminal, or a healthy run)."""
        self._restart_streak.pop(channel_id, None)
        self._backoff_relaunch.pop(channel_id, None)
        self._restart_latch.force_reset(channel_id)

    def _append_encoder_child_failure_event(
        self,
        channel_id: str,
        state: EgressStateRow,
    ) -> EgressProofEvent:
        event = EgressProofEvent(
            event_id=f"egress-encoder-child-relaunch-{uuid.uuid4()}",
            observed_at=datetime.now(UTC),
            channel_id=channel_id,
            state="STARTING",
            source_label=state.current_source_label or "Unknown egress source",
            source_path="ffmpeg-child:nonzero-exit",
            source_ref=state.current_proof_event_id,
            proof_boundary="civiccast-egress-handoff-boundary",
            machine_summary=(
                "CivicCast detected a non-zero FFmpeg child exit while the channel was "
                "expected to stay on air; the daemon kept running and started encoder relaunch."
            ),
        )
        self._store.append_proof_event(event)
        return event

    def _append_restart_escalation_event(
        self,
        channel_id: str,
        state: EgressStateRow,
        streak: int,
    ) -> EgressProofEvent:
        """Durably record that a channel has crash-relaunched repeatedly in a short
        window. This is the S8 alerting hook seam: the proof event lands now; the
        operator-facing alert dispatch is wired when S8 alerting lands (build step 4)."""
        event = EgressProofEvent(
            event_id=f"egress-encoder-restart-escalation-{uuid.uuid4()}",
            observed_at=datetime.now(UTC),
            channel_id=channel_id,
            state="STARTING",
            source_label=state.current_source_label or "Unknown egress source",
            source_path="ffmpeg-child:restart-escalation",
            source_ref=state.current_proof_event_id,
            proof_boundary="civiccast-egress-handoff-boundary",
            machine_summary=(
                f"CivicCast encoder for this channel has crash-relaunched {streak} times in "
                "a short window; output is unstable. The daemon keeps retrying with back-off. "
                "Investigate the source/sink before air; an operator alert is dispatched here "
                "once S8 alerting is in service."
            ),
        )
        self._store.append_proof_event(event)
        return event

    def _reap_orphan(self, channel_id: str) -> None:
        """Terminate a predecessor server's still-running encoder (issue #161).

        Called on every fresh start (this daemon tracks no live process for
        the channel). The durable state row carries the last known encoder
        pid; if that pid is alive AND its process image is ffmpeg, it is an
        orphan from a previous server process still streaming to the sink
        port - two writers on one UDP destination corrupt the feed. A pid
        reused by an unrelated program is never touched.
        """

        state = self._store.read_state(channel_id)
        if state is None or state.pid is None:
            return
        # Audit ENG-001: a pid this daemon tracks belongs to it - never a
        # predecessor's orphan.
        tracked = {_process_pid(p) for p in self._processes.values()}
        if state.pid in tracked:
            return
        info = self._orphan_probe(state.pid)
        if info is None or "ffmpeg" not in info.name.lower():
            return
        if info.created_at >= self._boot_epoch:
            # Created after this server booted: a recycled pid on a FRESH
            # ffmpeg (another channel, a conform job, a relay). Not ours to
            # kill.
            return
        self._orphan_terminator(state.pid, info.created_at)
        _LOG.warning(
            "Reaped orphaned encoder pid %s for channel %s (left by a "
            "previous server process; it was still streaming to the sink).",
            state.pid,
            channel_id,
        )
        self._store.append_proof_event(
            EgressProofEvent(
                event_id=f"egress-orphan-reap-{uuid.uuid4()}",
                observed_at=datetime.now(UTC),
                channel_id=channel_id,
                state="STARTING",
                source_label=state.current_source_label or "unknown",
                source_path=f"orphan-pid-{state.pid}",
                source_ref=None,
                proof_boundary="civiccast-egress-handoff-boundary",
                machine_summary=(
                    f"CivicCast reaped an orphaned encoder (pid {state.pid}) for "
                    f"channel {channel_id!r} left by a previous server process "
                    "before starting a fresh encoder."
                ),
            )
        )

    def _try_content_reload(self, channel_id: str, state: EgressStateRow, process: object) -> bool:
        """Seamless program content-reload for a content-reload-capable strategy.

        Resolves the newly-due plan (same provider → preparer chain as ``_start``) and
        tells the running worker to rebuild its program leg in place. Returns False —
        so the caller falls back to terminate+restart — for any case the seamless path
        can't own: no/disabled config, no/foreign/invalid plan, a prepare failure, a
        strategy error, or a worker control channel that isn't ready yet.
        """
        config = self._store.get_config(channel_id)
        if config is None or not config.enabled:
            return False
        if self._ts_relay is not None:
            # #151: keep the reload request's sink URIs consistent with the
            # relay-routed URIs the running encoder was started with.
            config = self._ts_relay.apply(config)
        try:
            source_plan = self._source_plan_provider(channel_id)
        except SourcePrepareError:
            return False  # let terminate+restart resolve the slate fallback
        if source_plan is None or source_plan.channel_id != channel_id:
            return False
        if self._source_preparer is not None:
            try:
                preparation_report = self._source_preparer(source_plan, config)
                source_plan = preparation_report.source_plan
                self._record_prepared_loudness(channel_id, preparation_report)
            except SourcePrepareError:
                return False
        request = EncoderStartRequest(
            channel_id=channel_id,
            source_plan=source_plan,
            config=config,
            work_dir=self._work_dir,
            resolve_secret=self._resolve_secret,
            branding_plan=(
                self._branding_plan_provider(channel_id)
                if self._branding_plan_provider is not None
                else None
            ),
            caption_plan=(
                self._caption_plan_provider(channel_id)
                if self._caption_plan_provider is not None
                else None
            ),
            cg_overlay_image=(
                self._cg_overlay_provider(channel_id, config)
                if self._cg_overlay_provider is not None
                else None
            ),
            audio_tap_plan=build_audio_tap_plan(channel_id),
            ffmpeg_starter=self._ffmpeg_starter,
        )
        try:
            applied = self._encoder_strategy.reload_content(channel_id, self._work_dir, request)
        except Exception:
            _LOG.exception("Content-reload dispatch failed for %s; restarting encoder.", channel_id)
            return False
        if not applied:
            return False
        previous_state = state.state if state else None
        previous_source_label = state.current_source_label if state else None
        # Record the source-to-source transition in the proof chain for parity with
        # the restart path — but DO NOT write a TRANSITIONING *state*: the seamless
        # swap never takes output down, so the channel stays ON_AIR throughout.
        if previous_state in {"ON_AIR", "FALLBACK_SLATE"}:
            transition_event = self._build_proof_event(
                channel_id=channel_id,
                state="TRANSITIONING",
                source_plan=source_plan,
                previous_state=previous_state,
                previous_source_label=previous_source_label,
            )
            self._store.append_proof_event(transition_event)
        proof_event = self._build_proof_event(
            channel_id=channel_id,
            state="ON_AIR",
            source_plan=source_plan,
            previous_state=previous_state,
            previous_source_label=previous_source_label,
        )
        self._store.append_proof_event(proof_event)
        # The GStreamer seamless-swap twin of the _start ON_AIR site: the channel
        # stays ON_AIR but the source actually changed, so it IS an as-run boundary.
        self._record_as_run_transition(
            channel_id=channel_id,
            running_state="ON_AIR",
            source_plan=source_plan,
            proof_event=proof_event,
        )
        self._write_state(
            channel_id,
            "ON_AIR",
            current_source_label=source_plan.segments[0].label,
            current_proof_event_id=proof_event.event_id,
            pid=_process_pid(process),
        )
        self._append_health(
            channel_id,
            "ON_AIR",
            sink_connected=self._sink_connected(channel_id, config, state="ON_AIR"),
            seconds_on_air=self._seconds_on_air(channel_id),
        )
        return True

    def _request_reload(self, channel_id: str) -> None:
        state = self._store.read_state(channel_id)
        process = self._processes.get(channel_id)
        if process is None or _process_poll(process) is not None:
            self._start(
                channel_id,
                previous_state=state.state if state else None,
                previous_source_label=state.current_source_label if state else None,
            )
            return
        # S15 (D-S1-6): if the strategy can rebuild program content in place (the
        # GStreamer engine), apply the newly-due program seamlessly — no encoder
        # restart, so MPEG-TS continuity is unbroken at the program boundary (the
        # #151 fix applied to every reload). Any condition the seamless path can't
        # handle falls through to the terminate+restart reload below (which already
        # handles slate fallback, interruptible filler, and the graceful drain).
        if (
            state is not None
            and getattr(self._encoder_strategy, "supports_content_reload", False)
            and self._try_content_reload(channel_id, state, process)
        ):
            return
        self._pending_reloads[channel_id] = (
            state.state if state else None,
            state.current_source_label if state else None,
        )
        self._write_state(
            channel_id,
            "TRANSITIONING",
            current_source_label=state.current_source_label if state else None,
            current_proof_event_id=state.current_proof_event_id if state else None,
            pid=_process_pid(process),
        )
        if state is not None and state.state == "FALLBACK_SLATE":
            # Issue #157 (CA-8 live finding): filler is interruptible by
            # design - a due program must not wait out the fill-target plan
            # (after #154 that wait is up to an hour of slate). Programs
            # keep the graceful drain above.
            self._reload_kills.add(channel_id)
            _process_terminate(process)

    def _drain(self, channel_id: str) -> None:
        process = self._processes.get(channel_id)
        if process is None:
            self._close_as_run(channel_id)  # nothing on air to drain — close any open row
            self._write_state(channel_id, "STOPPED")
            self._append_health(channel_id, "STOPPED", sink_connected={})
            return
        state = self._store.read_state(channel_id)
        config = self._store.get_config(channel_id)
        self._draining_channels.add(channel_id)
        self._pending_reloads.pop(channel_id, None)
        self._reload_kills.discard(channel_id)  # drain cancels a pending kill
        self._write_state(
            channel_id,
            "DRAINING",
            current_source_label=state.current_source_label if state else None,
            current_proof_event_id=state.current_proof_event_id if state else None,
            pid=_process_pid(process),
        )
        self._append_health(
            channel_id,
            "DRAINING",
            sink_connected=(
                self._sink_connected(channel_id, config, state="DRAINING") if config else {}
            ),
            seconds_on_air=self._seconds_on_air(channel_id),
        )

    def _stop(self, channel_id: str, *, draining: bool) -> None:
        process = self._processes.pop(channel_id, None)
        self._started_at.pop(channel_id, None)
        self._reset_restart_tracking(channel_id)  # operator stop — clear crash back-off
        self._draining_channels.discard(channel_id)
        self._pending_reloads.pop(channel_id, None)
        # Audit ENG-005: a leaked reload-kill flag would later misclassify a
        # genuine crash as a clean reload handoff.
        self._reload_kills.discard(channel_id)
        self._stderr_logs.pop(channel_id, None)
        self._clear_cg_overlay_proof(channel_id, "DRAINING" if draining else "STOPPING")
        # Operator stop — the channel comes off air now; close the open as-run
        # row. The encoder is popped from _processes here, so _poll_process will
        # never see its exit; this is the terminal close for the stop path.
        self._close_as_run(channel_id)
        if process is None:
            return
        self._write_state(channel_id, "DRAINING" if draining else "STOPPING")
        if draining:
            # RAT-004 graceful drain (CC-WS5-004): send the worker its TERMINAL
            # protocol command through the D2 control channel and DO NOT
            # force-terminate here. ``stop_all_channels`` owns the deadline loop:
            # it observes the worker's OS process exit as ground truth and
            # escalates to ``_process_terminate`` ONLY after the deadline. Killing
            # the worker here (as the pre-fix code did) force-terminated it before
            # it ever received its graceful terminal action. ``send_command`` is an
            # OPTIONAL strategy capability (only the GStreamer engine carries a
            # worker control channel; the concat strategy has none), so it is
            # resolved via ``getattr`` — mirroring the ``supports_content_reload``
            # capability probe above. If it is absent or returns False (no live
            # control channel / lost ack), the deadline escalation still reaps a
            # worker that has not exited.
            send_command = getattr(self._encoder_strategy, "send_command", None)
            if callable(send_command):
                send_command(self._work_dir, channel_id, "stop")
            return
        # Direct operator stop (NOT the drain): no deadline/escalation loop exists
        # to reap a hung worker, so keep the immediate force-terminate rather than
        # risk hanging on a dead control channel.
        _process_terminate(process)
        # CC-WS5-006: the worker is gone — release its control pipe so the
        # named-pipe server is not leaked until Job Object teardown. The drain
        # path defers this to stop_all_channels, which closes once exit is observed.
        self._close_worker_channel(channel_id)

    def stop_all_channels(self, *, deadline_seconds: float) -> DrainResult:
        """RAT-004: the missing graceful drain-all owner for supervised shutdown.

        Snapshots every channel this daemon instance currently tracks a live
        process for, issues the terminal ``_stop(channel_id, draining=True)``
        to each (the existing graceful-stop path), then waits on OBSERVED
        process exit — ``poll()``, not any acknowledgement — as ground truth,
        up to ``deadline_seconds``. A channel still alive at the deadline is
        escalated with a second call to the existing ``_process_terminate``
        kill and reported ``killed_after_deadline``; the drain still returns
        rather than hanging. Idempotent: a channel with no live process at
        snapshot time (already stopped/crashed) is reported ``already_gone``
        without issuing a redundant stop. Zero tracked channels is a clean
        no-op.
        """

        snapshot = list(self._processes.items())
        if not snapshot:
            return DrainResult(outcomes=())

        outcomes: dict[str, str] = {}
        pending: dict[str, object] = {}
        for channel_id, process in snapshot:
            if _process_poll(process) is not None:
                # No live process to drain — pop it so a stale handle can't
                # linger, and report the terminal state without a redundant
                # stop (RAT-004 idempotency).
                self._processes.pop(channel_id, None)
                outcomes[channel_id] = "already_gone"
                continue
            self._stop(channel_id, draining=True)
            pending[channel_id] = process

        deadline_at = self._monotonic() + max(deadline_seconds, 0.0)
        while pending and self._monotonic() < deadline_at:
            exited = [
                channel_id
                for channel_id, process in pending.items()
                if _process_poll(process) is not None
            ]
            for channel_id in exited:
                outcomes[channel_id] = "drained"
                del pending[channel_id]
            if pending:
                self._sleep(_DRAIN_POLL_INTERVAL_SECONDS)

        for channel_id, process in pending.items():
            # Ground truth is re-checked one last time at the deadline boundary
            # before escalating, so a process that exits exactly on the last
            # tick is still reported ``drained`` rather than needlessly killed.
            if _process_poll(process) is not None:
                outcomes[channel_id] = "drained"
                continue
            _process_terminate(process)
            outcomes[channel_id] = "killed_after_deadline"

        # CC-WS5-006: shutdown/drain-all is a terminal off-air for each channel —
        # release its worker control pipe now that its process exit is resolved, so
        # no named-pipe server leaks past supervised shutdown.
        for channel_id, _ in snapshot:
            self._close_worker_channel(channel_id)

        return DrainResult(
            outcomes=tuple(
                ChannelDrainOutcome(channel_id, outcomes[channel_id]) for channel_id, _ in snapshot
            )
        )

    def _sync_cg_overlay_proof(self, channel_id: str, state: EgressState) -> None:
        if self._cg_overlay_proof_provider is None:
            return
        proof = self._cg_overlay_proof_provider(channel_id)
        if proof is None:
            self._last_cg_overlay_event_keys.pop(channel_id, None)
            self._clear_cg_overlay_proof(channel_id, state)
            return
        proof_key = (proof.status, proof.overlay_id, proof.blocker)
        if proof.status != "READY":
            if self._last_cg_overlay_event_keys.get(channel_id) == proof_key:
                return
            self._append_cg_overlay_event(proof, state=state)
            self._last_cg_overlay_event_keys[channel_id] = proof_key
            return
        if self._active_cg_overlay_ids.get(channel_id) == proof.overlay_id:
            return
        previous_overlay_id = self._active_cg_overlay_ids.get(channel_id)
        if previous_overlay_id is not None:
            clear_proof = build_cg_overlay_clear_egress_proof(
                channel_id=channel_id,
                overlay_id=previous_overlay_id,
            )
            self._append_cg_overlay_clear_event(clear_proof, state=state)
        self._append_cg_overlay_event(proof, state=state)
        self._active_cg_overlay_ids[channel_id] = proof.overlay_id
        self._last_cg_overlay_event_keys[channel_id] = proof_key

    def _clear_cg_overlay_proof(self, channel_id: str, state: EgressState) -> None:
        overlay_id = self._active_cg_overlay_ids.pop(channel_id, None)
        self._last_cg_overlay_event_keys.pop(channel_id, None)
        if overlay_id is None:
            return
        clear_proof = build_cg_overlay_clear_egress_proof(
            channel_id=channel_id,
            overlay_id=overlay_id,
        )
        self._append_cg_overlay_clear_event(clear_proof, state=state)

    def _append_cg_overlay_event(self, proof: EgressCgOverlayProof, *, state: EgressState) -> None:
        self._store.append_proof_event(
            EgressProofEvent(
                event_id=f"egress-cg-overlay-{uuid.uuid4()}",
                observed_at=datetime.now(UTC),
                channel_id=proof.channel_id,
                state=state,
                source_label=proof.operator_label,
                source_path=f"cg-overlay:{proof.overlay_id}",
                source_ref=proof.overlay_id,
                proof_boundary=CG_EGRESS_PROOF_BOUNDARY,
                machine_summary=_cg_overlay_event_summary(proof),
            )
        )

    def _append_cg_overlay_clear_event(
        self,
        proof: EgressCgOverlayClearProof,
        *,
        state: EgressState,
    ) -> None:
        self._store.append_proof_event(
            EgressProofEvent(
                event_id=f"egress-cg-overlay-clear-{uuid.uuid4()}",
                observed_at=datetime.now(UTC),
                channel_id=proof.channel_id,
                state=state,
                source_label=proof.operator_label,
                source_path=f"cg-overlay-clear:{proof.overlay_id}",
                source_ref=proof.overlay_id,
                proof_boundary=CG_EGRESS_PROOF_BOUNDARY,
                machine_summary=_cg_overlay_clear_event_summary(proof),
            )
        )

    def _seconds_on_air(self, channel_id: str) -> int:
        started_at = self._started_at.get(channel_id)
        if started_at is None:
            return 0
        return max(0, int(self._monotonic() - started_at))

    def _sink_connected(
        self,
        channel_id: str,
        config: EgressConfig,
        *,
        state: EgressState,
    ) -> dict[str, bool]:
        metrics = self._health_metrics(channel_id, state=state)
        if self._sink_health_provider is not None:
            return self._sink_health_provider(channel_id, config, metrics)
        return build_default_sink_health(config=config, metrics=metrics, state=state)


def _default_orphan_probe(pid: int) -> OrphanInfo | None:
    """Return the running process identity for ``pid``, or None."""

    import psutil

    try:
        process = psutil.Process(pid)
        return OrphanInfo(name=process.name(), created_at=process.create_time())
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied:
        # Audit ENG-009: an unreapable orphan must at least be visible.
        _LOG.warning(
            "Orphan probe denied access to pid %s; if it is a predecessor's "
            "encoder it cannot be reaped from this process.",
            pid,
        )
        return None


def _default_orphan_terminator(pid: int, created_at: float) -> None:
    # S9 §6.3: the encoder-orphan terminator and the optional-co-process terminator
    # share one TOCTOU-safe kill primitive (re-verify create_time; never kill a
    # recycled pid; AccessDenied is logged, never raised into _start — audit ENG-001/009).
    verify_and_kill_process(pid, created_at)


def _process_pid(process: object) -> int | None:
    return getattr(process, "pid", None)


class _PollableProcess(Protocol):
    def poll(self) -> int | None: ...


def _process_poll(process: object) -> int | None:
    return cast(_PollableProcess, process).poll()


def _process_terminate(process: object) -> None:
    process.terminate()  # type: ignore[attr-defined]


def _process_close(process: object) -> None:
    close = getattr(process, "close", None)
    if close is not None:
        close()


def _proof_event_summary(
    *,
    state: str,
    previous_state: str | None,
    previous_source_label: str | None,
    source_kind: str,
    source_label: str,
    channel_id: str,
) -> str:
    if state == "TRANSITIONING":
        prior = previous_source_label or previous_state or "previous source"
        if source_kind == "live":
            return (
                f"CivicCast began live takeover from {prior!r} to {source_label!r} "
                f"for channel {channel_id!r} at the configured handoff boundary."
            )
        return (
            f"CivicCast began an egress handoff from {prior!r} to {source_label!r} "
            f"for channel {channel_id!r} at the configured handoff boundary."
        )
    if state == "FALLBACK_SLATE":
        return (
            f"CivicCast entered fallback slate {source_label!r} for channel "
            f"{channel_id!r} at the configured handoff boundary."
        )
    if previous_state == "FALLBACK_SLATE":
        return (
            f"CivicCast exited fallback slate and started egress source {source_label!r} "
            f"for channel {channel_id!r} at the configured handoff boundary."
        )
    if source_kind == "live":
        return (
            f"CivicCast put live source {source_label!r} on air for channel "
            f"{channel_id!r} at the configured handoff boundary."
        )
    if previous_source_label and previous_source_label.lower().startswith("live:"):
        return (
            f"CivicCast released live source {previous_source_label!r} and returned to "
            f"scheduled source {source_label!r} for channel {channel_id!r} at the "
            "configured handoff boundary."
        )
    return (
        f"CivicCast started egress source {source_label!r} for channel "
        f"{channel_id!r} at the configured handoff boundary."
    )


def _cg_overlay_event_summary(proof: EgressCgOverlayProof) -> str:
    if proof.status == "BLOCKED":
        return (
            f"CivicCast blocked emergency banner {proof.overlay_id!r} for channel "
            f"{proof.channel_id!r}: {proof.blocker}. This is not an EAS claim."
        )
    return (
        f"CivicCast raised emergency banner {proof.overlay_id!r} "
        f"({proof.overlay_title!r}, severity {proof.severity!r}) for channel "
        f"{proof.channel_id!r}. This is not an EAS claim."
    )


def _cg_overlay_clear_event_summary(proof: EgressCgOverlayClearProof) -> str:
    return (
        f"CivicCast cleared emergency banner {proof.overlay_id!r} for channel "
        f"{proof.channel_id!r}. This is not an EAS claim."
    )
