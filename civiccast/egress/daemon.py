# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Egress daemon loop foundation."""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol, cast

from civiccast.captions.tap import build_audio_tap_plan
from civiccast.egress._text import db_safe_text, db_safe_text_or_none
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
from civiccast.egress.gst.exit_codes import GST_PREROLL_TIMEOUT_EXIT_CODE
from civiccast.egress.gst.reload_policy import should_defer_switch
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
    redact_uris_in_text,
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

# BLOCKER B1 (hostile audit): a live SRT/UDP/RTSP source that is unreachable or
# drops makes the GStreamer worker crash immediately after each relaunch — the
# encoder process itself starts fine (so _start's own EncoderUnavailableError /
# FfmpegNotFoundError fallback-to-slate seam never fires), then dies inside the
# pipeline once it can't connect to / keep reading the source. Left alone that
# is an infinite crash-loop against the SAME dead source: _relaunch_after_crash
# paces the *rate* of relaunch (the cooldown above) but never changes *what* it
# relaunches, so the channel never reaches a stable on-air state — "dead air is
# NEVER acceptable" (see the encoder-unavailable comment below) was violated for
# exactly this case. At this many consecutive crash-relaunches that never once
# reached a healthy uptime (the streak only advances on a crash before the
# reset-uptime threshold; see _RESTART_STREAK_RESET_UPTIME_S), the daemon stops
# trusting the configured source and forces the same fallback-slate path used
# for EncoderUnavailableError/FfmpegNotFoundError in _start, instead of
# relaunching against the same source again. This IS the terminal state that
# replaces dead air: the channel lands on FALLBACK_SLATE, healthy uptime there
# resets the streak (see _poll_process), and civiccast.egress.automation's
# existing _check_slate_replan already retries the real source on its own
# 30s-paced cooldown — so a source that recovers is picked back up automatically,
# and a source that stays dead keeps the station on slate instead of crash-looping
# silently forever.
_LIVE_SOURCE_FAILURE_FALLBACK_STREAK = _RESTART_ESCALATION_STREAK
# Bound on the child-stderr tail folded into ``last_error`` -- the state row is an
# operator-facing string, not a log sink.
_STDERR_TAIL_MAX_CHARS = 600

# Item 82: a GST_PREROLL_TIMEOUT_EXIT_CODE exit (a slow-but-progressing preroll
# under CPU load) still relaunches through _relaunch_after_crash's normal
# back-off path, but must not advance _restart_streak (the crash-loop counter
# that eventually forces fallback slate, _LIVE_SOURCE_FAILURE_FALLBACK_STREAK
# above) more than once per this window -- see _relaunch_after_crash's own
# docstring for why an uncapped counter would misfire on a healthy source.
_PREROLL_TIMEOUT_STREAK_COOLDOWN_S = 60.0

# F1 redesign (coordinator hostile review, 2026-09-06): absolute backstop for a
# pending reload settlement that never arrives at all (e.g. the worker crashed
# between arming the reload and writing reload-status.json, or the status file
# itself never made it to disk). Longer than the engine's own
# ``defer_switch_timeout_s`` (900s default, GstPlayoutEngine.__init__) plus a
# generous margin for the pipe round trip and a couple of missed poll ticks --
# a legitimate deferred switch always settles well within this window; past it,
# treat the reload as lost and fall back to restart rather than wait forever.
_PENDING_RELOAD_SETTLE_DEADLINE_S = 960.0


class _PendingReloadSettlement(NamedTuple):
    """F1 redesign: everything ``_poll_reload_settlement`` needs to either
    finish the ON_AIR bookkeeping (on "applied") or fall back to restart (on
    "aborted:<reason>" or a deadline lapse) for one armed-but-not-yet-settled
    content-reload. Constructed by ``_try_content_reload``, consumed and
    cleared by ``_poll_reload_settlement``."""

    reload_id: str
    since: float  # daemon._monotonic() at arm time -- the deadline clock
    process: object
    config: EgressConfig
    source_plan: EgressSourcePlan
    switch_at_end_of_current: bool
    previous_state: str | None
    previous_source_label: str | None
    plan_dir: Path | None


def _ascii_safe(text: str) -> str:
    """Fold arbitrary child output so it can reach the database, whatever its
    server encoding.

    T6 soak evidence (Desktop/CIVICCAST-EVIDENCE/soak-120-e502074-20260905, kit
    e502074): the GStreamer worker's stall message contained one non-ASCII
    character. ``_child_stderr_tail`` reads the child log with
    ``errors="replace"``, so it arrived as U+FFFD; ``_child_exit_error`` folded it
    into ``last_error``; ``_write_state`` wrote that to Postgres, and psycopg
    raised ``UnicodeEncodeError: 'charmap' codec can't encode character '\\ufffd'``
    while converting the statement for a non-UTF8 client encoding.

    That exception escaped ``_begin_relaunch`` -> ``_relaunch_after_crash`` ->
    ``_poll_process`` -> ``process_once``, i.e. out of
    ``ChannelAutomationService._run_channel_pass`` BEFORE it reaches
    ``_check_slate_replan`` / ``_check_plan_rollover`` (automation.py) -- so every
    crash-relaunch tick silently skipped the seamless-rollover machinery #162
    added. 23 aborted passes in that 2h soak, zero rollovers dispatched.

    Child stderr is untrusted, arbitrarily encoded text; nothing about an
    operator-facing error string needs to carry it verbatim. Fold it here, at the
    single boundary where child bytes become a persisted value -- delegates to
    :func:`civiccast.egress._text.db_safe_text`, the same helper every OTHER
    persisted free-text path in this module now goes through (current_source_label,
    proof-event label/machine_summary, last_error), so every one of those paths
    degrades identically instead of each choosing its own fold.
    """

    return db_safe_text(text)


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
        # DEFECT A: the GStreamer engine's hls sinks are delivered by a
        # supervised ffmpeg relay child (real segments + a real manifest),
        # not a native GStreamer element — see civiccast.egress.hls_relay.
        # None (the ffmpeg-concat engine's default) means hls sinks pass
        # through unchanged; that engine's own EgressSink/HlsSink already
        # writes real HLS directly.
        hls_relay_supervisor: Any | None = None,
        # DEFECT D: called (channel_id, command, exception) whenever one
        # queued command raises during process_once — see process_once's
        # per-command isolation. Wired to the operator alert surface in
        # civiccast.egress.automation.build_channel_automation; None is a
        # silent no-op (tests / the CLI daemon loop that don't wire alerting).
        command_failure_hook: Callable[[str, EgressCommand, BaseException], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        # F3 fix (hostile-review follow-up, 2026-09-06): optional hook to
        # immediately reclaim one specific SourcePreparer per-plan directory
        # (``SourcePreparer.release``) once THIS daemon independently knows a
        # plan is retired -- see ``_poll_reload_settlement`` (a just-settled
        # reload's predecessor) and ``_stop`` (the channel's active plan on an
        # operator stop). None (the default, and every caller that doesn't
        # construct a real ``SourcePreparer``) means GC alone reclaims stale
        # directories -- never a correctness issue, just slower cleanup.
        prepared_plan_release: Callable[[Path | None], None] | None = None,
    ) -> None:
        self._store = store
        # Single injectable monotonic clock for all crash-relaunch timing (the
        # restart latch + worker uptime), so tests drive the back-off deterministically
        # through the constructor instead of reaching into private state.
        self._monotonic = monotonic or time.monotonic
        # #151: persistent per-channel TS relay so encoder relaunches never
        # reset the mux session at a udp-ts headend. None = pass-through.
        self._ts_relay = ts_relay_supervisor
        self._hls_relay = hls_relay_supervisor
        self._command_failure_hook = command_failure_hook
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
        # Per channel: the horizon of the source plan actually DISPATCHED to the
        # encoder (see dispatched_plan_horizon / _record_dispatched_plan).
        self._dispatched_plan_horizon: dict[str, tuple[str | None, tuple[float, ...], bool]] = {}
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
        # Item 82: last _monotonic() the crash-loop streak was actually
        # incremented FOR a preroll-timeout exit -- rate-limits how often that
        # specific exit reason can advance the streak (see
        # _relaunch_after_crash). Ordinary crashes are unaffected and always
        # increment the streak on every exit.
        self._preroll_timeout_streak_incr_at: dict[str, float] = {}
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
        # MAJOR M1: last-observed liveness of each channel's supervised HLS
        # relay child (True = confirmed dead since last poll; absent = alive
        # or not applicable). Polled every process_once tick (see
        # _poll_hls_relay) so a relay death (disk full / ffmpeg missing / OOM)
        # is visible even while the main encoder keeps sending fine.
        self._hls_relay_dead: dict[str, bool] = {}
        self._last_loudness_lufs: dict[str, float] = {}
        self._active_cg_overlay_ids: dict[str, str] = {}
        self._last_cg_overlay_event_keys: dict[str, tuple[str, str, str | None]] = {}
        # F1 redesign (2026-09-06): a content-reload's ack now means only
        # "armed" -- the actual commit/abort is tracked here until
        # ``_poll_reload_settlement`` observes it (or its deadline lapses).
        # See ``_try_content_reload``'s docstring for the full design.
        self._pending_reload_settle: dict[str, _PendingReloadSettlement] = {}
        # F3 fix: the per-plan prepared/ directory (SourcePreparationReport.
        # plan_dir) backing the CURRENTLY on-air plan for each channel, if the
        # configured source_preparer reports one. Updated when a reload
        # settles applied; the PREVIOUS value is released at that point (see
        # ``_poll_reload_settlement``) rather than left for GC alone.
        self._active_prepared_plan_dir: dict[str, Path] = {}
        self._prepared_plan_release = prepared_plan_release
        # Hostile-review follow-up (2026-09-06), item 1: the reload_id a
        # discarded (worker-exited/superseded/restarted) pending settlement
        # last carried, kept ONLY so a late-arriving status write for that
        # dead attempt can be recognized and logged as ignored instead of
        # silently doing nothing -- see ``_discard_pending_reload_settlement``
        # and ``_poll_reload_settlement``. Keyed by channel_id, so this is
        # already bounded by the number of channels this daemon instance
        # tracks (at most one entry per channel, always overwritten by that
        # channel's next discard) -- NOT by time. (Hostile-review follow-up,
        # third pass, P2: a second-pass revision briefly added a bounded-age
        # expiry here on the theory that this dict could otherwise grow
        # unboundedly; it could not (the per-channel key already caps it),
        # and the added expiry could evict an id whose real settlement lands
        # legitimately right at the edge of the same
        # ``_PENDING_RELOAD_SETTLE_DEADLINE_S`` budget the pending entry
        # itself was allowed to take -- and it was never evicted for a
        # channel that gets stopped, so it did not even close the gap it was
        # written for. Reverted to a plain reload_id with no expiry.)
        self._discarded_reload_ids: dict[str, str] = {}

    def process_once(self, channel_id: str) -> int:
        """Process all currently queued commands for one channel.

        DEFECT D (found live: after a crash, later queued commands —
        "takeover", then a "stop" — sat unprocessed with zero log activity
        for minutes). Root cause: ``pop_pending_commands`` marks the ENTIRE
        currently-pending batch consumed in one durable update before any of
        it runs (see ``EgressStore.pop_pending_commands``); an unguarded
        ``for`` loop here meant one command raising (e.g. the DEFECT A hls
        crash, or a hls-config'd channel's ``_start`` re-raising on every
        subsequent takeover/reload attempt because the broken sink was still
        configured) aborted the loop, and every command AFTER it in that same
        batch was already marked consumed — durably lost, never retried,
        with no per-command trace of what happened. Isolating each command's
        processing means one bad command can no longer take the rest of the
        batch down with it; the crashed command itself is still consumed
        (at-most-once delivery is unchanged — reissue it), but everything
        queued alongside or after it still runs.

        Encoding-defect follow-up (reviewer finding on the state-write-encoding
        branch): ``_poll_process``/``_service_backoff_relaunch`` write
        persisted state on a crash-relaunch (``_write_state``,
        ``append_proof_event``), and ``_poll_hls_relay`` can too. Before this
        fix, an exception escaping ANY of the three (e.g. the exact
        ``UnicodeEncodeError`` the encoding fix closes, or any other write
        failure) propagated out of ``process_once`` and aborted the WHOLE
        pass for that channel — including ``pop_pending_commands`` below,
        so every queued command (takeover, stop, ...) sat unprocessed too,
        not just the poll that failed. Guarding each call the same way the
        command loop below already guards each command means one poll's
        write failure can never again take the rest of the pass down with
        it — the failing poll is simply retried next tick (each is
        idempotent against durable state), exactly like a failed command is
        simply reissued.
        """

        # Poll the HLS relay child BEFORE the main worker so a relay death is
        # already reflected in _hls_relay_dead by the time _poll_process's own
        # health append (below) calls _sink_connected this same tick (MAJOR M1).
        # Order is preserved across the guard: each call still runs only after
        # the previous one completed (successfully or not), never in parallel.
        # F1 redesign: _poll_reload_settlement checks reload-status.json for a
        # channel with an armed-but-not-yet-settled content-reload -- a no-op
        # for every other channel (it returns immediately when there is no
        # pending entry).
        for poll in (
            self._poll_hls_relay,
            self._poll_process,
            self._service_backoff_relaunch,
            self._poll_reload_settlement,
        ):
            try:
                poll(channel_id)
            except Exception:
                _LOG.exception(
                    "channel %s: %s failed this process_once tick; the pass continues "
                    "(command draining below still runs, and every other poll for this "
                    "channel still runs). Will be retried next tick.",
                    channel_id,
                    poll.__name__,
                )
        commands = self._store.pop_pending_commands(channel_id)
        for command in commands:
            try:
                self._process_command(command)
            except Exception as exc:
                _LOG.exception(
                    "Egress command %s (%s) failed for channel %s; it will NOT be "
                    "retried (already marked consumed by pop_pending_commands) but "
                    "every other queued command for this channel this pass still runs. "
                    "Reissue the failed command if it was still needed.",
                    command.command_id,
                    command.action,
                    channel_id,
                )
                if self._command_failure_hook is not None:
                    try:
                        self._command_failure_hook(channel_id, command, exc)
                    except Exception:  # the hook must never break command draining
                        _LOG.exception(
                            "command_failure_hook itself raised for channel %s; continuing.",
                            channel_id,
                        )
        return len(commands)

    def has_live_process(self, channel_id: str) -> bool:
        """True when THIS daemon instance tracks a live encoder process.

        CA-2 channel automation uses this for the auto-start pass: a flagged
        channel with no live process (fresh app start, or a stop the operator
        issued) is a candidate for a re-issued start command.
        """

        process = self._processes.get(channel_id)
        return process is not None and _process_poll(process) is None

    def has_manual_override(self, channel_id: str) -> bool:
        """True while an operator override (live takeover / forced fallback slate)
        is active for this channel. The base daemon has no notion of either — only
        ``PlayoutSupervisor`` (civiccast/egress/supervisor.py) does — so this
        default is always False, and ``PlayoutSupervisor`` overrides it. Consulted
        by channel-automation's plan-rollover pass (B1 fix: neither an operator
        force-slate nor a live takeover writes a state-row transition the rollover
        check could otherwise key off) and by ``_try_content_reload`` below (B3
        fix: whether a reload may defer its selector switch to the outgoing leg's
        EOS — never while an override is active, see ``reload_policy.
        should_defer_switch``)."""

        return False

    def dispatched_plan_horizon(
        self, channel_id: str
    ) -> tuple[str | None, tuple[float, ...], bool] | None:
        """``(proof_event_id, segment durations, switch_was_deferred)`` for the
        source plan this daemon most recently DISPATCHED to the encoder for
        ``channel_id`` -- or None if it has dispatched none.

        Exists because channel-automation's rollover pass has to know when the
        airing plan runs out, and the only honest source for that is the plan that
        was actually sent. It used to re-derive the horizon by calling the source
        plan provider AGAIN and summing whatever came back
        (``_check_plan_rollover``); that is a DIFFERENT plan -- the provider
        re-windows from the schedule item live at the moment of the call, capped at
        ``max_segments``, so the re-query's segment list is neither the one on air
        nor aligned to it, and the derived horizon can land the rollover trigger on
        (or past) the real end. Recorded at the two sites that actually dispatch:
        ``_start`` and ``_try_content_reload``.

        ``switch_was_deferred`` is what makes the horizon correct for a
        boundary-aligned rollover: that plan does NOT begin when it is dispatched:
        the engine holds it until the outgoing leg's own end
        (``reload_policy.should_defer_switch`` /
        ``GstPlayoutEngine.reload_program``), so its projected end runs from the
        OUTGOING plan's end, not from the dispatch instant."""

        return self._dispatched_plan_horizon.get(channel_id)

    def _record_dispatched_plan(
        self,
        channel_id: str,
        *,
        proof_event_id: str | None,
        source_plan: EgressSourcePlan,
        switch_deferred: bool,
    ) -> None:
        """Remember the plan just dispatched, keyed by the proof event written with
        it (so a consumer can tell "this is the plan now on air" from "this is a
        stale record"). See ``dispatched_plan_horizon``."""

        self._dispatched_plan_horizon[channel_id] = (
            proof_event_id,
            tuple(float(segment.duration_seconds) for segment in source_plan.segments),
            switch_deferred,
        )

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
            if self._hls_relay is not None:
                self._hls_relay.stop_channel(command.channel_id)
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
        force_fallback_slate: bool = False,
        force_fallback_reason: str | None = None,
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
            if self._hls_relay is not None:
                # DEFECT A: route hls sinks through the supervised ffmpeg relay
                # that actually writes segments + a manifest for this engine.
                config = self._hls_relay.apply(config)
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
            # Hostile-review follow-up, items 1 & 4: reaching here means either
            # no process was tracked at all, or the tracked one has ALREADY
            # exited (the guard above only returns early while it is still
            # alive) -- some callers reach _start directly on a dead process
            # without going through _poll_process (e.g. _request_reload's own
            # poll check), so this is the other place that exit must be
            # recognized. Any armed-but-unsettled reload for the OLD process
            # is moot, and the OLD active plan is no longer being read by
            # anything -- reclaim both before starting fresh.
            self._discard_pending_reload_settlement(channel_id, reason="channel restarting")
            self._discard_active_prepared_plan_dir(channel_id)
            self._reap_orphan(channel_id)
            using_fallback_slate = False
            fallback_reason: str | None = None
            if force_fallback_slate and self._fallback_source_provider is not None:
                # BLOCKER B1: the caller (a crash-relaunch that has never once
                # reached a healthy uptime — see _LIVE_SOURCE_FAILURE_FALLBACK_STREAK)
                # has already decided the configured source is unusable right now.
                # Go straight to the fallback-slate plan rather than re-resolving
                # (and re-trusting) the same source_plan_provider that keeps
                # producing a source the encoder can't stay attached to.
                fallback_reason = force_fallback_reason or (
                    "Live source failed repeatedly; aired fallback slate instead of "
                    "an infinite crash-loop."
                )
                self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                # Annotated because this is the FIRST binding of source_plan on this
                # branch path — see the matching note at the other first-binding
                # branch below for why the annotation matters to mypy.
                source_plan: EgressSourcePlan | None = self._fallback_source_provider(config)
                using_fallback_slate = True
                readiness = None
            elif (
                readiness := (
                    self._caption_readiness_provider(channel_id)
                    if self._caption_readiness_provider is not None
                    else None
                )
            ) is not None and not getattr(readiness, "ready", True):
                reason = getattr(readiness, "refusal_reason", None) or "caption-readiness-refused"
                fallback_reason = f"caption storage refused: {reason}"
                if not getattr(readiness, "requires_fallback_slate", False):
                    raise ConfigInvalidError(fallback_reason)
                if self._fallback_source_provider is None:
                    self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                    self._append_health(channel_id, "FALLBACK_SLATE", sink_connected={})
                    return
                self._write_state(channel_id, "FALLBACK_SLATE", last_error=fallback_reason)
                source_plan = self._fallback_source_provider(config)
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
            # Hostile-review follow-up, item 4: None unless the preparer
            # actually reports a discrete per-plan directory for the plan
            # this worker ends up airing -- tracked into
            # _active_prepared_plan_dir below once the encoder actually
            # starts, so the flag-OFF (shipped default) path releases it too
            # instead of relying solely on _try_content_reload's tracking
            # (which never runs at all while supports_content_reload is False).
            prepared_plan_dir: Path | None = None
            if self._source_preparer is not None:
                try:
                    preparation_report = self._source_preparer(source_plan, config)
                    source_plan = preparation_report.source_plan
                    prepared_plan_dir = preparation_report.plan_dir
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

            # Hostile-review follow-up (third pass), P0: captured right here,
            # BEFORE the encoder-unavailable retry below gets a chance to flip
            # using_fallback_slate again -- this records whether the preparer
            # (just above) ran against a plan that was ALREADY the fallback
            # slate (an early flip: force_fallback_slate, caption-readiness
            # refusal, or source_plan is None, all above) versus the program
            # plan. The distinction matters because the tracking decision at
            # the end of this method used to release prepared_plan_dir on
            # ANY using_fallback_slate=True, including this early-flip case --
            # but there, prepared_plan_dir is the SLATE's own directory (the
            # preparer ran on source_plan after it was already reassigned to
            # the fallback plan), which the encoder is actively airing from.
            # Releasing it (rmtree) out from under a live airing was reviewer-
            # proven with a probe: prepared_for=['Fallback slate'], state
            # FALLBACK_SLATE pid=111, released=['plan-1'].
            prepared_for_fallback = using_fallback_slate

            # Hostile-review follow-up (second pass), items 1 & 2: everything
            # from here down to the tracking decision at the end of this
            # block can either raise (a provider hook, EncoderStartRequest
            # construction, the encoder itself) or can legitimately decide
            # NOT to use the prepared plan after all (the encoder-unavailable
            # retry falling back to slate, using_fallback_slate flips True
            # AFTER prepare() already succeeded) -- in EITHER case, if the
            # preparer minted a real prepared_plan_dir above, it must be
            # released here: nothing else ever looks at this local variable
            # again, so silently dropping the reference (the previous code)
            # or letting an exception skip past it were both permanent leaks,
            # recoverable only by age/budget GC, not this daemon's own faster
            # release.
            try:
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
                # Hostile-review follow-up, item 4: track the plan actually being
                # aired so it gets released on the next exit/stop even when the
                # seamless-reload flag is OFF (supports_content_reload=False, the
                # shipped default) -- _try_content_reload/_commit_reload_
                # settlement never run at all on that path, so without this the
                # only cleanup for a _start()-launched plan was age/budget GC.
                if using_fallback_slate and not prepared_for_fallback:
                    # Item 1 fix, narrowed by the P0 fix above: only release
                    # when using_fallback_slate flipped True AFTER the
                    # preparer already ran (prepared_for_fallback is False) --
                    # the encoder-unavailable retry path just above, where
                    # prepared_plan_dir is the PROGRAM plan's directory, never
                    # actually dispatched to this encoder (a separately-built
                    # fallback slate plan aired instead). Release it.
                    self._release_prepared_plan_dir(prepared_plan_dir)
                elif prepared_plan_dir is not None:
                    # Covers both: a normal (non-fallback) start, AND an
                    # early-flip fallback slate (force_fallback_slate,
                    # caption-readiness refusal, or no source plan) where the
                    # preparer ran against the SLATE plan itself -- that
                    # directory is exactly what this encoder is airing from,
                    # so it must be tracked as active, not released.
                    self._active_prepared_plan_dir[channel_id] = prepared_plan_dir
            except Exception:
                # Item 2 fix: anything above that raises past this point --
                # a provider hook, EncoderStartRequest construction, an
                # encoder failure this method doesn't itself recover from --
                # must not leak prepared_plan_dir. Release, then propagate
                # unchanged (the existing outer except clauses below still
                # decide how the channel's STATE responds to this failure;
                # this inner handler only ever touches the plan directory).
                self._release_prepared_plan_dir(prepared_plan_dir)
                raise
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
            # A start puts its plan on air immediately (no deferred switch).
            self._record_dispatched_plan(
                channel_id,
                proof_event_id=proof_event.event_id,
                source_plan=source_plan,
                switch_deferred=False,
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
        # Gate A T4 diagnosability fix (2026-09): this is the ONE choke point
        # every pipeline state transition passes through -- every
        # FALLBACK_SLATE / ERROR entry above sets ``last_error`` here, never
        # anywhere else. Logging it at INFO (rather than leaving it as a
        # store-only field) is what actually reaches an operator or a Gate A
        # probe reading ``control_plane-app.log``: before this fix the
        # control-plane child process had no configured handler for the
        # ``civiccast`` logger at any level, so this record was silently
        # dropped even though the STATE it describes was durably persisted.
        # ``current_source_label`` is never secret-bearing -- it is a
        # human-facing label (e.g. "Council meeting", "Fallback slate"), not
        # the underlying URI; the URI itself is redacted via
        # ``redact_source_uri`` before it ever reaches proof-event storage
        # (see ``_build_proof_event`` below) and is never passed to this
        # method at all.
        #
        # Both fields below are free text this daemon does not control the
        # content of: ``current_source_label`` traces back to an
        # operator-entered asset title (source_plan.py's ``label = asset.title
        # or item.asset_title or item.asset_id``), and ``last_error`` often
        # carries a raw ``str(exc)`` or a folded child-stderr tail. This is the
        # ONE choke point every state transition passes through (see the
        # comment above), so it is the one place to fold BOTH before they
        # reach ``EgressStore.write_state`` -- see
        # ``civiccast/egress/_text.py`` for why a non-UTF8 character here
        # aborts the whole automation pass if left unfolded.
        current_source_label = db_safe_text_or_none(current_source_label)
        last_error = db_safe_text_or_none(last_error)
        _LOG.info(
            "channel %s: egress state -> %s (source=%s, pid=%s, last_error=%s)",
            channel_id,
            state,
            current_source_label or "-",
            pid if pid is not None else "-",
            last_error or "-",
        )
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

    def _engine_label(self) -> str:
        """Which encoder engine actually runs this channel's child process.

        Gate A T4 (2026-09): every non-zero child exit was reported as "FFmpeg child
        exited non-zero" even when the child was the GStreamer playout worker, which
        sent operators (and a Gate A triage) hunting an ffmpeg problem that did not
        exist. Name the engine from the strategy that launched it.
        """
        name = getattr(self._encoder_strategy, "name", "") or ""
        return "GStreamer playout worker" if "gstreamer" in name.lower() else "FFmpeg encoder"

    def _child_stderr_tail(self, channel_id: str, *, max_lines: int = 8) -> str | None:
        """Last few non-blank stderr lines of the channel's just-exited child.

        The worker's traceback / stall message is the only thing that says WHY a
        channel is bouncing, and it lives in a per-channel log file nothing outside
        the work dir reads. Fold a bounded, redacted tail into ``last_error`` so the
        operator's state row and the control-plane log carry the reason.
        Redacted with ``redact_uris_in_text`` per line -- an ingest URI in a GStreamer
        error message can carry an SRT passphrase / RTMP key (ENG-003). NOT
        ``redact_source_uri``: that leaves a URI EMBEDDED in a longer line untouched, and
        ``ERROR failed to open srt://host?passphrase=...`` is exactly what a child writes.
        """
        log_path = self._stderr_logs.get(channel_id)
        if log_path is None:
            return None
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        tail = " | ".join(redact_uris_in_text(line) for line in lines[-max_lines:])
        return _ascii_safe(tail)[:_STDERR_TAIL_MAX_CHARS]

    def _child_exit_error(self, channel_id: str, *, suffix: str) -> str:
        tail = self._child_stderr_tail(channel_id)
        message = f"{self._engine_label()} child exited non-zero; {suffix}"
        if tail:
            message = f"{message} Last child stderr: {tail}"
        return message

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
        # ``segment.label`` is operator-entered free text (source_plan.py:
        # ``label = asset.title or item.asset_title or item.asset_id``), and
        # ``_proof_event_summary`` interpolates it (and the PREVIOUS label) into
        # ``machine_summary`` -- both are persisted via
        # ``EgressStore.append_proof_event``, a separate write path from
        # ``_write_state``, so it needs its own fold at this, its own choke
        # point. See ``civiccast/egress/_text.py``.
        source_label = db_safe_text(segment.label)
        return EgressProofEvent(
            event_id=f"egress-proof-{uuid.uuid4()}",
            observed_at=datetime.now(UTC),
            channel_id=channel_id,
            state=state,  # type: ignore[arg-type]
            source_label=source_label,
            # ENG-003: a live segment's path is an ingest URI that can carry an SRT
            # passphrase / RTMP key / RTSP credentials — redact before it lands in the
            # durable, operator-readable proof chain.
            source_path=redact_source_uri(segment.path),
            source_ref=segment.source_ref,
            proof_boundary="civiccast-egress-handoff-boundary",
            machine_summary=db_safe_text(
                _proof_event_summary(
                    state=state,
                    previous_state=previous_state,
                    previous_source_label=db_safe_text_or_none(previous_source_label),
                    source_kind=segment.kind,
                    source_label=source_label,
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

    def _poll_hls_relay(self, channel_id: str) -> None:
        """MAJOR M1: poll this channel's supervised HLS relay child liveness.

        Mirrors ``_poll_process`` polling the main worker, for the SEPARATE
        ffmpeg co-process ``HlsRelaySupervisor`` owns (see DEFECT A / M1 in
        ``civiccast.egress.hls_relay``). Before this, a relay death was never
        observed until the channel's next full encoder start/reload happened
        to call ``apply()`` again. Result is cached in ``_hls_relay_dead`` and
        consulted by ``_sink_connected`` so the ``hls`` sink's reported health
        reflects the relay's OWN liveness, not just the main encoder's UDP
        send progress.
        """
        if self._hls_relay is None:
            return
        is_alive = getattr(self._hls_relay, "is_alive", None)
        if not callable(is_alive):
            return
        alive = is_alive(channel_id)
        if alive is None:
            # No relay currently tracked for this channel (no hls sink
            # configured, or none started yet) -- not a health signal.
            self._hls_relay_dead.pop(channel_id, None)
            return
        was_already_flagged_dead = self._hls_relay_dead.get(channel_id, False)
        self._hls_relay_dead[channel_id] = not alive
        if not alive and not was_already_flagged_dead:
            _LOG.error(
                "HLS relay child for channel %s is no longer running (disk full, "
                "ffmpeg missing, or OOM are the known causes); the main encoder is "
                "unaffected but residents on the hls sink are getting a stale or "
                "dead stream until this channel's next start/reload restarts it.",
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
        # Hostile-review follow-up, items 1 & 4: the worker that would have
        # settled any armed reload (and that was reading the currently-active
        # prepared plan) is now DEFINITELY gone -- reclaim both immediately
        # rather than let a spurious restart fire at the 960s deadline against
        # a channel that has already moved on (possibly restarted onto a
        # completely different plan by the branches below), or wait for GC to
        # notice the active plan is no longer referenced.
        self._discard_pending_reload_settlement(channel_id, reason="worker exited")
        self._discard_active_prepared_plan_dir(channel_id)
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
            if was_draining and self._hls_relay is not None:
                self._hls_relay.stop_channel(channel_id)
            self._write_state(channel_id, "STOPPED")
            self._append_health(channel_id, "STOPPED", sink_connected={})
            return
        self._pending_reloads.pop(channel_id, None)
        state = self._store.read_state(channel_id)
        if state is not None and state.state in {"ON_AIR", "FALLBACK_SLATE", "TRANSITIONING"}:
            self._relaunch_after_crash(channel_id, state, uptime, returncode)
            return
        self._reset_restart_tracking(channel_id)
        self._clear_cg_overlay_proof(channel_id, "ERROR")
        self._close_as_run(channel_id)  # terminal error — close the open row
        self._write_state(
            channel_id,
            "ERROR",
            last_error=self._child_exit_error(
                channel_id, suffix="inspect the channel's worker logs before retrying."
            ),
        )
        self._append_health(channel_id, "ERROR", sink_connected={}, dropped_frames=0)

    def _relaunch_after_crash(
        self,
        channel_id: str,
        state: EgressStateRow,
        uptime: float | None,
        returncode: int | None = None,
    ) -> None:
        """Crash-relaunch with back-off (S9-5). The first crash relaunches at once;
        a crash recurring within the cooldown is paced (a deferred relaunch the
        ``process_once`` tick services once the latch permits) so a worker that keeps
        dying at startup can't hot-loop. A worker that ran healthily resets the streak.

        Item 82: a GStreamer worker that exits with
        ``civiccast.egress.gst.exit_codes.GST_PREROLL_TIMEOUT_EXIT_CODE`` (a slow,
        CPU-load-bound preroll, not a crash) still relaunches through the exact
        same path below -- the existing back-off/cooldown pacing applies
        unchanged -- but does NOT advance the crash-loop streak more than once
        per ``_PREROLL_TIMEOUT_STREAK_COOLDOWN_S`` (60s). Left uncapped, a train
        of successive slow starts (each individually a legitimate retry) would
        trip ``_LIVE_SOURCE_FAILURE_FALLBACK_STREAK`` and force the channel onto
        fallback slate for a source that was never actually unreachable -- the
        exact failure this rate limit exists to prevent, without weakening the
        streak's real job of catching a genuinely dead/unreachable source
        (an ordinary non-zero exit still increments on every single crash).

        Round-2 review BLOCKER (Opus, PR #183): a preroll-timeout exit's
        ``uptime`` (how long the worker was alive before it gave up) is NOT
        evidence of a healthy run -- it is simply how long the doomed preroll
        attempt took, which can legitimately be close to (engine.py now clamps
        it below) the ``_RESTART_STREAK_RESET_UPTIME_S`` (60s) reset threshold
        below. Applying that reset to a preroll-timeout exit would silently
        defeat the crash-loop escalation to fallback slate for a source that
        NEVER comes up (measured: 40 consecutive relaunches, streak stuck at
        0, before this exemption existed) -- so this reset is skipped
        entirely for that exit reason; only a genuinely different exit
        (successful start reaching PLAYING, then crashing later, or an
        ordinary crash) can benefit from it."""
        streak = self._restart_streak.get(channel_id, 0)
        if (
            uptime is not None
            and uptime >= _RESTART_STREAK_RESET_UPTIME_S
            and returncode != GST_PREROLL_TIMEOUT_EXIT_CODE
        ):
            # Belt-and-suspenders with the healthy-poll reset in _poll_process: that
            # path clears the streak while the worker is RUNNING healthily; this one
            # covers a worker that ran healthily and then crashed in the SAME gap
            # between polls (so the poll-reset never saw it). Either way a fresh
            # failure after a healthy run is streak 1 → immediate relaunch.
            streak = 0
            # Round-2 review nit: a healthy run also makes any earlier
            # preroll-timeout rate-limit window stale -- clear it so a FUTURE
            # preroll-timeout exit (a fresh problem, unrelated to whatever
            # last incremented the streak before this healthy stretch) is
            # never rate-limited by a now-irrelevant past timestamp.
            self._preroll_timeout_streak_incr_at.pop(channel_id, None)
        if returncode == GST_PREROLL_TIMEOUT_EXIT_CODE:
            last_incr_at = self._preroll_timeout_streak_incr_at.get(channel_id)
            if (
                last_incr_at is not None
                and self._monotonic() - last_incr_at < _PREROLL_TIMEOUT_STREAK_COOLDOWN_S
            ):
                # Rate-limited: still persist any healthy-uptime reset above,
                # but don't advance the streak again inside this cooldown window.
                self._restart_streak[channel_id] = streak
            else:
                streak += 1
                self._restart_streak[channel_id] = streak
                self._preroll_timeout_streak_incr_at[channel_id] = self._monotonic()
        else:
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
        # BLOCKER B1: a crash-relaunch streak that has never once reached a
        # healthy uptime is the "unreachable/dropping live source" signature —
        # relaunching against the SAME source again would just repeat the
        # crash. Once the streak crosses the threshold, force the same
        # fallback-slate path _start already uses for
        # EncoderUnavailableError/FfmpegNotFoundError, instead of trusting the
        # source_plan_provider again — deliberately WITHOUT excluding a
        # ``previous_state == "FALLBACK_SLATE"`` crash: the streak (once
        # crossed) only clears on a healthy uptime (see _poll_process /
        # _reset_restart_tracking) or an explicit operator/automation command
        # (see _process_command popping _backoff_relaunch), so leaving this
        # unguarded keeps the channel LATCHED onto slate across a slate-encoder
        # crash too, instead of one relaunch attempt bouncing back to
        # re-resolving the still-dead live source via source_plan_provider
        # (which has no reason to behave differently) before the very next
        # crash forces fallback again — an avoidable ON_AIR/FALLBACK_SLATE
        # flap that is not the stable terminal slate state this fix exists to
        # provide. A crash-looping slate encoder itself is the deeper
        # zero-ffmpeg-floor case _start's own exception handler still covers,
        # unchanged, if the slate encoder can't even START.
        streak = self._restart_streak.get(channel_id, 0)
        force_fallback_slate = (
            streak >= _LIVE_SOURCE_FAILURE_FALLBACK_STREAK
            and self._fallback_source_provider is not None
        )
        force_fallback_reason = (
            f"Live source failed to stay on air after {streak} consecutive "
            "crash-relaunches; aired fallback slate instead of an infinite "
            "crash-loop against the dead source."
            if force_fallback_slate
            else None
        )
        self._write_state(
            channel_id,
            "STARTING",
            current_source_label=previous_source_label,
            current_proof_event_id=proof_event_id,
            last_error=(
                force_fallback_reason
                or self._child_exit_error(channel_id, suffix="relaunching encoder.")
            ),
        )
        self._append_health(channel_id, "STARTING", sink_connected={}, dropped_frames=0)
        self._start(
            channel_id,
            previous_state=previous_state,
            previous_source_label=previous_source_label,
            force_fallback_slate=force_fallback_slate,
            force_fallback_reason=force_fallback_reason,
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
        self._preroll_timeout_streak_incr_at.pop(channel_id, None)
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

    def _release_prepared_plan_dir(self, plan_dir: Path | None) -> None:
        """Best-effort call into the configured ``prepared_plan_release`` hook
        (F3) -- a no-op if no hook is configured or ``plan_dir`` is None. A
        release hiccup must never break the caller's own state transition."""
        if self._prepared_plan_release is None or plan_dir is None:
            return
        with contextlib.suppress(Exception):
            self._prepared_plan_release(plan_dir)

    def _discard_pending_reload_settlement(self, channel_id: str, *, reason: str) -> None:
        """Hostile-review follow-up (2026-09-06), items 1 & 3: drop any
        armed-but-unsettled reload tracking for ``channel_id`` and release its
        plan directory immediately (never leave it for GC/the 960s deadline).

        Called from every path where the pending attempt is definitely moot:
        the worker that would have settled it exited (``_poll_process``), the
        channel is restarting fresh (``_start``), a newer reload superseded it
        before it settled (``_try_content_reload``, item 3 -- the previous
        code silently overwrote ``_pending_reload_settle`` here, leaking the
        replaced entry's plan_dir), and the explicit restart fallback
        (``_fall_back_to_restart_reload``) as a defensive backstop.

        Records the discarded reload_id (``_discarded_reload_ids``) so a
        LATE-arriving status write for that dead attempt is recognized and
        logged as ignored by ``_poll_reload_settlement``, instead of the
        previous silent no-op (pending already gone, nothing left to compare
        against) that gave no evidence the late write was even seen.

        Deliberately does NOT clear ``_discarded_reload_ids`` when there is no
        pending entry to discard: this method is called defensively from
        several places in a row for the SAME exit (e.g. ``_poll_process``'s
        crash branch calling ``_start``, which calls this again) -- an
        unconditional clear here would wipe out the very tracking the FIRST
        call just recorded before ``_poll_reload_settlement`` ever gets a
        chance to observe a late arrival against it."""
        pending = self._pending_reload_settle.pop(channel_id, None)
        if pending is None:
            return
        _LOG.info(
            "Content-reload for %s (reload_id=%s) discarded: %s.",
            channel_id,
            pending.reload_id,
            reason,
        )
        self._discarded_reload_ids[channel_id] = pending.reload_id
        self._release_prepared_plan_dir(pending.plan_dir)

    def _discard_active_prepared_plan_dir(self, channel_id: str) -> None:
        """Hostile-review follow-up, item 4: release the plan directory
        backing whatever ``channel_id`` was ACTUALLY airing (tracked from both
        ``_start`` and ``_commit_reload_settlement``), once the worker reading
        it is confirmed gone -- a real process exit (``_poll_process``), a
        fresh ``_start`` past its already-alive guard (which only reaches
        here when the previously-tracked process has already exited), a
        direct (non-draining) operator stop (``_stop(channel_id,
        draining=False)``, whose immediate ``_process_terminate`` call above
        it makes exit synchronous), or ``stop_all_channels``'s own
        observed-exit loop for the DRAINING case (hostile-review follow-up,
        third pass, P2: ``_stop(channel_id, draining=True)`` only sends the
        worker its graceful TERMINAL command and returns -- the worker is
        still airing, possibly for the entire ``deadline_seconds`` window, so
        ``_stop`` itself must NOT call this for a draining stop; the previous
        docstring here claiming the worker is "confirmed gone" on every
        ``_stop`` call was wrong for exactly that path). Deliberately NOT
        called from ``_fall_back_to_restart_reload``: that path's worker may
        still be alive and draining/airing the very plan this would
        release."""
        self._release_prepared_plan_dir(self._active_prepared_plan_dir.pop(channel_id, None))

    def live_prepared_plan_dirs(self, channel_id: str) -> frozenset[Path]:
        """Hostile-review follow-up, item 5: every ``SourcePreparer`` per-plan
        directory this daemon currently considers LIVE for ``channel_id`` --
        the active on-air plan and any armed-but-not-yet-settled reload's
        plan. Wired into the configured ``SourcePreparer`` (via
        ``set_protected_plan_dirs_provider``, see cli.py/automation.py) as the
        ``keep=`` set its own GC pass must never evict, regardless of age,
        size, or keep-N recency -- closing the gap where nothing but this
        daemon actually knows which directories are still referenced."""
        pending = self._pending_reload_settle.get(channel_id)
        return frozenset(
            plan_dir
            for plan_dir in (
                self._active_prepared_plan_dir.get(channel_id),
                pending.plan_dir if pending is not None else None,
            )
            if plan_dir is not None
        )

    def has_pending_reload_settlement(self, channel_id: str) -> bool:
        """Public capability ``ChannelAutomationService`` probes (via
        ``getattr``, like ``has_manual_override``/``dispatched_plan_horizon``)
        so its rollover cadence latch can tell "armed, still settling" (never
        retry -- wait for this daemon's own deadline) apart from "genuinely
        dropped" (retry after ``_ROLLOVER_ISSUED_TIMEOUT_SECONDS``)."""
        return channel_id in self._pending_reload_settle

    def _try_content_reload(self, channel_id: str, state: EgressStateRow, process: object) -> bool:
        """Seamless program content-reload for a content-reload-capable strategy.

        Resolves the newly-due plan (same provider → preparer chain as ``_start``) and
        tells the running worker to rebuild its program leg in place. Returns False —
        so the caller falls back to terminate+restart — for any case the seamless path
        can't own: no/disabled config, no/foreign/invalid plan, a prepare failure, a
        strategy error, or a worker control channel that isn't ready yet.

        F1 redesign (coordinator hostile review, 2026-09-06): ``reload_content``
        returning True now means the reload was ARMED (accepted; the worker's new
        leg is building/prerolling), NOT that it has committed -- committing (or
        aborting) can take up to the worker's own ``defer_switch_timeout_s`` (900s
        default) for a deferred/boundary-aligned switch (the automation-driven
        ON_AIR-extension case this method exists for -- see
        ``reload_policy.should_defer_switch``). Doing the ON_AIR proof-event/state
        bookkeeping immediately, as the pre-redesign code did, would therefore
        claim the channel is airing the NEW source before the switch has actually
        happened -- for a deferred switch, the OLD content is often still
        genuinely on air for minutes after this method returns.

        This method now only ARMS the reload and records a
        ``_PendingReloadSettlement`` in ``self._pending_reload_settle``; the
        state/proof-event bookkeeping is deferred to ``_commit_reload_settlement``,
        invoked by ``_poll_reload_settlement`` once ``reload-status.json`` actually
        reports ``"applied"`` (or the daemon falls back to restart on
        ``"aborted:<reason>"``/a deadline lapse). Returns True as soon as the
        reload is armed -- this is what tells the CALLER (``_request_reload``) not
        to fall back to terminate+restart; it does not mean the switch landed."""
        config = self._store.get_config(channel_id)
        if config is None or not config.enabled:
            return False
        if self._ts_relay is not None:
            # #151: keep the reload request's sink URIs consistent with the
            # relay-routed URIs the running encoder was started with.
            config = self._ts_relay.apply(config)
        if self._hls_relay is not None:
            config = self._hls_relay.apply(config)
        try:
            source_plan = self._source_plan_provider(channel_id)
        except SourcePrepareError:
            return False  # let terminate+restart resolve the slate fallback
        if source_plan is None or source_plan.channel_id != channel_id:
            return False
        # F3: None unless the preparer actually reports a discrete per-plan
        # directory (see SourcePreparationReport.plan_dir) -- tracked into the
        # pending settlement below so _commit_reload_settlement can release the
        # PREVIOUS plan once this one lands.
        prepared_plan_dir: Path | None = None
        if self._source_preparer is not None:
            # D43 instrumentation (2026-09-05): this call is SYNCHRONOUS on the
            # automation thread -- ChannelAutomationService's poll loop
            # dispatches the reload that lands here, so every second spent
            # conforming is a second the whole automation pass is blocked. The
            # tester soak could measure the symptom (control plane at ~240% of
            # a core, worker restarts from the 10s CTRL stall watchdog) but not
            # this number, and the log recorded 5 reloads over 2 hours with no
            # timing on any of them. Log it per reload, at INFO with the
            # segment count, so the NEXT soak can read the actual prepare cost
            # straight out of the control-plane log instead of inferring it.
            # (Cache-warm prepares are already cheap: SourcePreparer._prepare_segment
            # short-circuits a conform-cache HIT to a stream copy or a
            # zero-ffmpeg trim -- see preparer.py. This measures what is left.)
            prepare_started = time.monotonic()
            try:
                preparation_report = self._source_preparer(source_plan, config)
                source_plan = preparation_report.source_plan
                prepared_plan_dir = preparation_report.plan_dir
                self._record_prepared_loudness(channel_id, preparation_report)
            except SourcePrepareError:
                _LOG.warning(
                    "Content-reload source preparation FAILED for %s after %.1fs; "
                    "falling back to restart.",
                    channel_id,
                    time.monotonic() - prepare_started,
                )
                return False
            _LOG.info(
                "Content-reload source preparation for %s took %.1fs for %d segment(s) "
                "(synchronous on the automation thread).",
                channel_id,
                time.monotonic() - prepare_started,
                len(source_plan.segments),
            )
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
            # B3 fix: only an automation-driven extension of an already-ON_AIR plan
            # (never a FALLBACK_SLATE gap-replan, never while an operator override
            # is active) may defer the selector switch to the outgoing leg's own
            # EOS -- see reload_policy.should_defer_switch's docstring.
            switch_at_end_of_current=should_defer_switch(
                previous_state=state.state if state else None,
                manual_override_active=self.has_manual_override(channel_id),
            ),
        )
        # F1 redesign: a daemon-generated id (not the strategy's own internal
        # uuid, which this layer never sees) so _poll_reload_settlement can
        # correlate reload-status.json's "id" field back to THIS specific
        # attempt -- load-bearing across a supersede (a second reload armed
        # before the first settles gets its OWN id and its OWN pending entry;
        # see that method's docstring).
        reload_id = str(uuid.uuid4())
        # F5 note (coordinator hostile review; NOT fixed here, deliberately):
        # this call still runs synchronously on the automation thread, same as
        # every call already made from here (source_plan_provider, the
        # preparer, the strategy dispatch below). With the F1 redesign the
        # worker's ack is "armed" -- fast, bounded by _reload_ack_timeout_s()
        # (the plain 5s default) -- so the WORST case this blocks the
        # automation thread for is that ~5s pipe round trip, not the up-to-
        # 900s settlement wait the pre-redesign code risked. That is still a
        # synchronous call on a thread automation's whole poll loop shares
        # across every channel; moving send_and_wait off the automation
        # thread entirely (e.g. a dedicated dispatch thread/executor per
        # channel) would remove even that bound but is a separate change --
        # left as a note, not attempted in this PR.
        try:
            armed = self._encoder_strategy.reload_content(
                channel_id, self._work_dir, request, command_id=reload_id
            )
        except Exception:
            _LOG.exception("Content-reload dispatch failed for %s; restarting encoder.", channel_id)
            return False
        if not armed:
            # Diagnosability fix (coordinator follow-up, 2026-09-06): this used to
            # return False with NO log line at all -- an operator/on-call reading
            # the control-plane log for "why did this channel restart instead of
            # reloading in place" found nothing. ``last_send_command_failure_reason``
            # is an OPTIONAL strategy capability (only GstPlayoutStrategy's D2
            # worker-pipe path tracks a reason; the ffmpeg concat strategy has none
            # to report), resolved via ``getattr`` -- mirroring the
            # ``supports_content_reload``/``send_command`` probes elsewhere in
            # this file.
            reason_fn = getattr(self._encoder_strategy, "last_send_command_failure_reason", None)
            reason = reason_fn(channel_id) if callable(reason_fn) else None
            _LOG.warning(
                "Seamless content-reload declined for %s (%s); falling back to restart.",
                channel_id,
                reason or "no reason reported by the encoder strategy",
            )
            return False
        # Item 3 fix: a still-pending PREVIOUS reload for this channel (this
        # attempt supersedes it -- e.g. automation issued another rollover
        # before the first settled) used to be silently overwritten below,
        # leaking its plan_dir forever. Discard it properly first.
        if channel_id in self._pending_reload_settle:
            self._discard_pending_reload_settlement(
                channel_id, reason="superseded by a newer reload attempt"
            )
        # Armed, not yet settled: record it and return. _poll_reload_settlement
        # finishes the ON_AIR bookkeeping once reload-status.json confirms
        # "applied" (or falls back to restart on "aborted:<reason>"/deadline).
        self._pending_reload_settle[channel_id] = _PendingReloadSettlement(
            reload_id=reload_id,
            since=self._monotonic(),
            process=process,
            config=config,
            source_plan=source_plan,
            switch_at_end_of_current=bool(request.switch_at_end_of_current),
            previous_state=state.state if state else None,
            previous_source_label=state.current_source_label if state else None,
            plan_dir=prepared_plan_dir,
        )
        _LOG.info(
            "Seamless content-reload armed for %s (reload_id=%s, switch_at_end_of_current=%s); "
            "awaiting settlement.",
            channel_id,
            reload_id,
            request.switch_at_end_of_current,
        )
        return True

    def _commit_reload_settlement(self, channel_id: str, pending: _PendingReloadSettlement) -> None:
        """F1 redesign: the ON_AIR proof-event/state bookkeeping ``_try_content_
        reload`` used to do immediately -- now run only once
        ``_poll_reload_settlement`` observes ``reload-status.json`` reporting
        ``"applied"`` for ``pending.reload_id``. Also releases the PREVIOUS
        active prepared-plan directory (F3) and records the new one."""
        config = pending.config
        source_plan = pending.source_plan
        previous_state = pending.previous_state
        previous_source_label = pending.previous_source_label
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
            pid=_process_pid(pending.process),
        )
        self._record_dispatched_plan(
            channel_id,
            proof_event_id=proof_event.event_id,
            source_plan=source_plan,
            switch_deferred=pending.switch_at_end_of_current,
        )
        self._append_health(
            channel_id,
            "ON_AIR",
            sink_connected=self._sink_connected(channel_id, config, state="ON_AIR"),
            seconds_on_air=self._seconds_on_air(channel_id),
        )
        # F3: the reload just settled -- the PREVIOUS plan is retired (the
        # engine has disposed its leg; see engine.reload_program's on_settled
        # contract). Release it immediately rather than waiting for GC, then
        # start tracking the new plan as active.
        self._release_prepared_plan_dir(self._active_prepared_plan_dir.pop(channel_id, None))
        if pending.plan_dir is not None:
            self._active_prepared_plan_dir[channel_id] = pending.plan_dir

    def _poll_reload_settlement(self, channel_id: str) -> None:
        """F1 redesign: poll ``reload-status.json`` for a channel with an
        armed-but-not-yet-settled content-reload (``_try_content_reload``).
        Runs once per ``process_once`` tick (added to its poll tuple), replacing
        the pre-redesign design's synchronous, potentially-900s-long block on
        the worker-pipe ack.

        * status ``"id"`` matches the pending reload and ``"result" ==
          "applied"`` -- the switch actually landed: finish the ON_AIR
          bookkeeping (``_commit_reload_settlement``) and clear the pending
          entry.
        * status matches and ``"result"`` starts with ``"aborted:"`` -- the
          reload did not land (build error, timeout, supersession downstream of
          this specific attempt): log the reason and fall back to restart
          (``_fall_back_to_restart_reload``), same path a synchronously-declined
          reload always took.
        * no status yet, or an id that does not match (a superseded attempt's
          own settlement arriving late) -- keep waiting, UNLESS
          ``_PENDING_RELOAD_SETTLE_DEADLINE_S`` has elapsed since this reload
          was armed, in which case treat it as lost and fall back to restart
          rather than wait forever for a status update that may never come
          (e.g. the worker crashed between arming and writing the file).
        * a status matching the pending id but carrying an UNRECOGNIZED
          result value (hostile-review follow-up: neither ``"applied"`` nor
          ``"aborted:..."`` -- a malformed write, a future/older worker
          version) is treated as aborted IMMEDIATELY, not silently waited out
          for the full deadline: whatever wrote it clearly ran, so waiting
          longer buys nothing, and a channel that is really fine should not
          sit unresolved for up to 960s over a status the daemon simply
          cannot interpret.

        If ``channel_id`` has no pending entry at all (already discarded --
        see ``_discard_pending_reload_settlement``), this also checks whether
        a LATE status write matches the most recently discarded reload_id and
        logs that it is being ignored, rather than the previous silent no-op
        that left no evidence the late write was ever observed."""
        pending = self._pending_reload_settle.get(channel_id)
        if pending is None:
            discarded_id = self._discarded_reload_ids.get(channel_id)
            if discarded_id is not None:
                status = self._read_reload_status(channel_id)
                if status is not None and status.get("id") == discarded_id:
                    _LOG.info(
                        "Content-reload settlement for %s (reload_id=%s) arrived after "
                        "that attempt was already discarded (worker exit/supersede/"
                        "restart); ignoring.",
                        channel_id,
                        discarded_id,
                    )
                    self._discarded_reload_ids.pop(channel_id, None)
            return
        status = self._read_reload_status(channel_id)
        if status is not None and status.get("id") == pending.reload_id:
            result = status.get("result")
            if result == "applied":
                # Follow-up (second hostile-review pass): liveness re-check --
                # the worker that armed this reload may have exited BETWEEN
                # _poll_process observing it (which would have discarded this
                # entry already) and this read, or in a process_once pass
                # where _poll_process ran before this worker's exit actually
                # happened. Stamping ON_AIR against a pid that is already dead
                # would be a lie the state row then carries until the next
                # tick catches it -- checked directly, not inferred.
                if _process_poll(pending.process) is not None:
                    _LOG.warning(
                        'Seamless content-reload for %s reported "applied" but its '
                        "worker had already exited (reload_id=%s); falling back to restart "
                        "instead of stamping ON_AIR against a dead process.",
                        channel_id,
                        pending.reload_id,
                    )
                    self._discard_pending_reload_settlement(
                        channel_id, reason="worker exited before settlement could be committed"
                    )
                    self._fall_back_to_restart_reload(channel_id)
                    return
                # NOTE: a plain pop here, not _discard_pending_reload_settlement --
                # this attempt is COMMITTING, not being discarded; its plan_dir
                # becomes the new active one inside _commit_reload_settlement,
                # never released.
                self._pending_reload_settle.pop(channel_id, None)
                self._commit_reload_settlement(channel_id, pending)
                return
            if isinstance(result, str) and result.startswith("aborted:"):
                _LOG.warning(
                    "Seamless content-reload for %s did not land (%s); falling back to restart.",
                    channel_id,
                    result,
                )
                self._discard_pending_reload_settlement(
                    channel_id, reason=f"worker reported {result}"
                )
                self._fall_back_to_restart_reload(channel_id)
                return
            # Unrecognized result value -- see the docstring note above.
            _LOG.warning(
                "Seamless content-reload for %s reported an unrecognized settlement "
                "result %r (reload_id=%s); treating as aborted and falling back to restart.",
                channel_id,
                result,
                pending.reload_id,
            )
            self._discard_pending_reload_settlement(
                channel_id, reason=f"unrecognized settlement result {result!r}"
            )
            self._fall_back_to_restart_reload(channel_id)
            return
        if self._monotonic() - pending.since >= _PENDING_RELOAD_SETTLE_DEADLINE_S:
            _LOG.warning(
                "Seamless content-reload for %s reported no settlement within %.0fs "
                "(reload_id=%s); falling back to restart.",
                channel_id,
                _PENDING_RELOAD_SETTLE_DEADLINE_S,
                pending.reload_id,
            )
            self._discard_pending_reload_settlement(
                channel_id, reason=f"no settlement within {_PENDING_RELOAD_SETTLE_DEADLINE_S:.0f}s"
            )
            self._fall_back_to_restart_reload(channel_id)

    def _read_reload_status(self, channel_id: str) -> dict[str, Any] | None:
        """Best-effort read of ``<work>/<channel_id>/reload-status.json``
        (``worker.py``'s ``_write_reload_status``). Never raises: a torn read
        (mid-rewrite, though the worker writes atomically via tmp+replace so
        this should be rare) or a malformed body is just "no status yet",
        retried next tick."""
        status_path = self._work_dir / channel_id / "reload-status.json"
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _fall_back_to_restart_reload(self, channel_id: str) -> None:
        """The terminate+restart reload path a declined/aborted/lost content-
        reload always falls through to -- factored out of ``_request_reload``
        so ``_poll_reload_settlement`` can take the exact same path for a
        reload that armed successfully but then failed to settle.

        Hostile-review follow-up, item 1: defensively discards any pending
        reload-settlement tracking for this channel too (a no-op if the
        caller already did -- every current call site does). Kept here as a
        backstop so a future call site reaching this method can never leave a
        stale pending entry (and its leaked plan_dir) behind."""
        self._discard_pending_reload_settlement(channel_id, reason="falling back to restart")
        state = self._store.read_state(channel_id)
        process = self._processes.get(channel_id)
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
        if state is not None and state.state == "FALLBACK_SLATE" and process is not None:
            # Issue #157 (CA-8 live finding): filler is interruptible by
            # design - a due program must not wait out the fill-target plan
            # (after #154 that wait is up to an hour of slate). Programs
            # keep the graceful drain above.
            self._reload_kills.add(channel_id)
            _process_terminate(process)

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
            # F1 redesign: True means ARMED, not settled -- _poll_reload_
            # settlement (in process_once's poll tuple) finishes the job (or
            # falls back to restart via _fall_back_to_restart_reload below)
            # once reload-status.json actually reports an outcome.
            return
        self._fall_back_to_restart_reload(channel_id)

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
        # F1/F3 fix: an armed-but-unsettled reload is moot once the channel is
        # stopped (nothing will ever read reload-status.json for it again) --
        # release it immediately instead of waiting for GC. Hostile-review
        # follow-up (second pass), item 3: this used to plain-pop
        # _pending_reload_settle (never releasing pending.plan_dir, never
        # logging, never recording the discarded reload_id for late-arrival
        # detection) -- routed through the shared helper now.
        self._discard_pending_reload_settlement(channel_id, reason="channel stopped")
        # Hostile-review follow-up (third pass), P2: the ACTIVE prepared-plan
        # directory is only safe to release here when this is a direct
        # (non-draining) stop -- the _process_terminate call further down
        # this method makes the worker's exit synchronous with this call, so
        # by the time we'd release it is already confirmed gone. A DRAINING
        # stop only sends the worker its graceful TERMINAL command below and
        # returns; the worker may still be airing from this very directory
        # for up to stop_all_channels' whole deadline_seconds window, so that
        # path defers this release to stop_all_channels' own observed-exit
        # loop instead (see _discard_active_prepared_plan_dir's docstring).
        if not draining:
            self._discard_active_prepared_plan_dir(channel_id)
        self._stderr_logs.pop(channel_id, None)
        self._hls_relay_dead.pop(channel_id, None)
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

        Hostile-review follow-up (third pass), P2: ``_stop(channel_id,
        draining=True)`` deliberately does NOT release the channel's active
        prepared-plan directory (see ``_discard_active_prepared_plan_dir``'s
        docstring) -- the worker is still airing from it until THIS method
        observes its exit. Every terminal branch below (``already_gone``,
        ``drained`` at either the polling loop or the deadline check, and
        ``killed_after_deadline``) therefore releases it here instead, once
        exit is actually confirmed.
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
                self._discard_active_prepared_plan_dir(channel_id)
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
                self._discard_active_prepared_plan_dir(channel_id)
                del pending[channel_id]
            if pending:
                self._sleep(_DRAIN_POLL_INTERVAL_SECONDS)

        for channel_id, process in pending.items():
            # Ground truth is re-checked one last time at the deadline boundary
            # before escalating, so a process that exits exactly on the last
            # tick is still reported ``drained`` rather than needlessly killed.
            if _process_poll(process) is not None:
                outcomes[channel_id] = "drained"
                self._discard_active_prepared_plan_dir(channel_id)
                continue
            _process_terminate(process)
            outcomes[channel_id] = "killed_after_deadline"
            self._discard_active_prepared_plan_dir(channel_id)

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
            health = self._sink_health_provider(channel_id, config, metrics)
        else:
            health = build_default_sink_health(config=config, metrics=metrics, state=state)
        # MAJOR M1: neither the injected provider nor the default health
        # builder above knows about the HLS relay CHILD PROCESS -- both only
        # see the main encoder's own send progress. A relay confirmed dead by
        # _poll_hls_relay overrides the hls sink(s) to unhealthy here, in one
        # place, regardless of which health path produced the dict, so
        # /api/staff/egress/channels/{id}/health stops reporting "connected"
        # for a dead relay.
        if self._hls_relay_dead.get(channel_id):
            hls_labels = [sink.label for sink in config.sinks if sink.kind == "hls"]
            if hls_labels:
                # Copy rather than mutate in place -- a provider (or the cached
                # default builder result) may hand back a dict it reuses.
                health = dict(health)
                for label in hls_labels:
                    health[label] = False
        return health


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
