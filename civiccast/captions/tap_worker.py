# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Caption tap worker: live broadcast audio -> durable caption review queue.

Beta sprint B6 (decision #1 option A). The egress encoder forks live audio to
rolling WAV segments (:mod:`civiccast.captions.tap`); this worker bridges
those segments into the existing live caption seam
(:class:`~civiccast.captions.worker.LiveCaptionWorker`: pipeline →
two-window stabilization → durable review queue).

House worker shape (same as the finalization/Stage F workers):

- env settings with fail-fast ``from_env``
  (``CIVICCAST_CAPTION_TAP=off|inline|external``, default ``off`` — live
  captioning needs a transcription model, so a station opts in);
- ``run_once`` scans ``<tap_root>/<channel>/chunk-NNNNNN.wav``; a segment is
  consumed only when a newer-numbered segment exists (ffmpeg has moved on),
  so a half-written file is never read;
- consumed segments move to ``<channel>/processed/``, unreadable ones to
  ``<channel>/quarantine/`` — a scan never double-feeds and one bad file is
  never fatal;
- ``run_forever(poll_seconds, stop_event)`` survives and logs scan errors;
- inline mode runs under the app lifespan's ``ThreadSupervisor``; external
  mode is ``python -m civiccast.captions.tap_worker`` against the same env.

Chunk timing derives from the segment index times the configured segment
length, so cue timestamps line up with broadcast time even after restarts.

CAPTIONS ARE BEST EFFORT; PLAYOUT WINS. Three mechanisms enforce that here,
because on a real CPU-only station they did not:

- overload backs OFF (:mod:`civiccast.captions.tap_backoff`) -- a channel that
  cannot keep up is paused for an exponentially growing window instead of
  retrying, and re-logging, every scan;
- ASR concurrency is BOUNDED (:func:`default_max_channel_workers`) -- one
  transcribing channel per 8 CPUs, so three ON_AIR channels on an 8-core box
  do not each claim the machine;
- the playout workers are spawned at ``ABOVE_NORMAL`` priority class, and the
  Python ASR threads here drop to ``BELOW_NORMAL``. The first of those is the
  load-bearing one; see :func:`_lower_current_thread_priority` for what the
  second does and does NOT cover.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import hashlib
import logging
import os
import re
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from civiccast.captions.live_sidecar import (
    CaptionRuntimeState,
    LiveWebVttPublisher,
    active_caption_sidecar,
    publish_caption_runtime_status,
    reset_existing_live_sidecars,
)
from civiccast.captions.models import AudioChunk, CaptionCue
from civiccast.captions.retention import CaptionEvidenceRetentionPolicy
from civiccast.captions.review import CaptionReviewAudioEvidence, CaptionReviewStore
from civiccast.captions.review_media import write_caption_review_audio_evidence
from civiccast.captions.runtime import CaptionRuntime
from civiccast.captions.tap_backoff import (
    DEFAULT_BASE_BACKOFF_SECONDS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    CaptionBackoffPolicy,
)
from civiccast.captions.worker import AudioEvidenceFactory, LiveCaptionWorker

if TYPE_CHECKING:
    from civiccast.translate.service import TranslationProvider

_LOG = logging.getLogger(__name__)

_SEGMENT_RE = re.compile(r"^chunk-(\d+)\.wav$")

TAP_MODE_OFF = "off"
TAP_MODE_INLINE = "inline"
TAP_MODE_EXTERNAL = "external"
_TAP_MODES = (TAP_MODE_OFF, TAP_MODE_INLINE, TAP_MODE_EXTERNAL)

__all__ = [
    "CaptionTapScanResult",
    "CaptionTapWorker",
    "CaptionTapWorkerSettings",
    "default_max_channel_workers",
]

#: How many CPUs one concurrently-transcribing channel is allowed to assume.
#: See :func:`default_max_channel_workers`.
_CPUS_PER_CAPTION_CHANNEL = 8

#: Windows ``THREAD_PRIORITY_BELOW_NORMAL``, applied to the per-channel ASR
#: threads. PARTIAL COVERAGE BY CONSTRUCTION -- read
#: :func:`_lower_current_thread_priority` before relying on it.
_THREAD_PRIORITY_BELOW_NORMAL = -1

#: How long a channel's runtime-status file may go unrewritten while its state
#: is unchanged. A heartbeat, not a poll interval: it keeps ``updated_at`` and
#: a paused channel's ``resume_in_seconds`` countdown moving for an operator
#: who is watching, without paying a durable write every ~2-second scan for a
#: state that has not changed. See ``CaptionTapWorker._publish_status``.
_STATUS_REFRESH_SECONDS = 30.0

#: How often the retention sweep may run, independent of the scan interval.
#: ``enforce_discovered`` lists review rows from the database and SHA-256s
#: every chunk it considers; at the 2-second scan cadence that is a database
#: query and a pass over the recorded audio 30 times a minute, forever, to
#: enforce a schedule measured in days. Retention correctness does not depend
#: on the interval -- only on running often enough that the schedule is
#: honoured -- so it gets its own, much slower clock. The first scan after
#: startup always sweeps.
_RETENTION_SWEEP_SECONDS = 60.0


def default_max_channel_workers() -> int:
    """How many channels may be transcribed CONCURRENTLY by default.

    MEASURED defect this replaces (tester DESKTOP-VBMA6O5, three channels
    ON_AIR): the previous flat default of 3 let all three channels run ASR at
    once, and each faster-whisper model was itself built with
    ``cpu_threads=0`` -- CTranslate2's "use every core". Three channels times
    every core is how the control plane came to burn ~247% of a core while the
    playout workers were starved into their own 10-second stall watchdog.

    One concurrent channel per 8 CPUs, never more than 3. On the 8-core field
    station that is ONE, and paired with the runtime's new ``cpu_threads``
    floor of 1 (:class:`civiccast.captions.runtime.FasterWhisperRuntime`) the
    whole caption feature's steady-state budget is about one core. Channels
    beyond the bound are not dropped -- they queue on the executor and are
    transcribed in the same scan, just not simultaneously.

    Overridable end-to-end via ``CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS``.
    """

    return max(1, min(3, (os.cpu_count() or 1) // _CPUS_PER_CAPTION_CHANNEL))


def _lower_current_thread_priority() -> None:
    """Best-effort ``BELOW_NORMAL`` for the calling ASR thread (Windows).

    WHAT THIS DOES NOT DO, stated plainly because an earlier version of this
    comment claimed a symmetry it does not have: it lowers the PYTHON thread
    that calls ``transcribe`` and nothing else. CTranslate2 runs the actual
    inference on its own intra-op thread pool, created inside the native
    library at whatever priority the process had when the model was
    constructed -- i.e. ``NORMAL``. Those threads are where the CPU is
    genuinely spent, and this call does not reach them. On a saturated box the
    Python thread yields; the CT2 pool does not.

    The real, load-bearing protections for playout are the two that do not
    depend on thread priorities at all: the ASR concurrency bound plus
    ``cpu_threads=1`` (which limits how many CT2 threads exist in the first
    place), and the overload backoff (which stops the work entirely). This
    call is a cheap extra nudge on top of those, not a mechanism to rely on.
    Lowering the CT2 pool itself would mean running the live ASR in its own
    process at ``BELOW_NORMAL_PRIORITY_CLASS``; that is a larger change than
    this fix and is not attempted here.

    A no-op everywhere but Windows and on any failure: the hint is a
    protection for playout, never a precondition for captions. Cheap enough
    (one syscall) to re-apply per scan, which is required because the caption
    scan builds a fresh :class:`~concurrent.futures.ThreadPoolExecutor` each
    time and therefore does not keep its worker threads.
    """

    if os.name != "nt":
        return
    windll = getattr(ctypes, "windll", None)
    if windll is None:  # pragma: no cover - non-Windows interpreters
        return
    try:
        kernel32 = windll.kernel32
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), _THREAD_PRIORITY_BELOW_NORMAL)
    except Exception:  # pragma: no cover - defensive; never fatal to captions
        _LOG.debug("Could not lower caption ASR thread priority.", exc_info=True)


@dataclass(frozen=True)
class CaptionTapWorkerSettings:
    """Deployment configuration for the caption tap worker."""

    mode: str = TAP_MODE_OFF
    tap_root: Path | None = None
    segment_seconds: float = 5.0
    atomic_segments: bool = False
    overlap_seconds: float = 4.0
    poll_seconds: float = 2.0
    max_channel_workers: int = field(default_factory=default_max_channel_workers)
    max_backlog_segments: int = 2
    overload_backoff_seconds: float = DEFAULT_BASE_BACKOFF_SECONDS
    max_overload_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS

    @classmethod
    def from_env(cls) -> CaptionTapWorkerSettings:
        mode = os.environ.get("CIVICCAST_CAPTION_TAP", TAP_MODE_OFF).strip().lower()
        if mode not in _TAP_MODES:
            raise ValueError(
                f"CIVICCAST_CAPTION_TAP must be one of {', '.join(_TAP_MODES)}; got {mode!r}."
            )
        root_raw = os.environ.get("CIVICCAST_CAPTION_TAP_DIR", "").strip()
        if mode != TAP_MODE_OFF and not root_raw:
            raise ValueError(
                "CIVICCAST_CAPTION_TAP_DIR must be set when CIVICCAST_CAPTION_TAP "
                f"is {mode!r} (the directory the egress audio fork writes into)."
            )
        defaults = cls()
        return cls(
            mode=mode,
            tap_root=Path(root_raw) if root_raw else None,
            segment_seconds=_env_float(
                "CIVICCAST_CAPTION_TAP_SEGMENT_SECONDS", defaults.segment_seconds
            ),
            atomic_segments=_env_bool("CIVICCAST_CAPTION_TAP_ATOMIC", defaults.atomic_segments),
            overlap_seconds=_env_float(
                "CIVICCAST_CAPTION_TAP_OVERLAP_SECONDS", defaults.overlap_seconds
            ),
            poll_seconds=_env_float("CIVICCAST_CAPTION_TAP_POLL_SECONDS", defaults.poll_seconds),
            max_channel_workers=_env_int(
                "CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS",
                defaults.max_channel_workers,
            ),
            max_backlog_segments=_env_int(
                "CIVICCAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS",
                defaults.max_backlog_segments,
            ),
            **_backoff_settings_from_env(
                base_default=defaults.overload_backoff_seconds,
                max_default=defaults.max_overload_backoff_seconds,
            ),
        )


def _backoff_settings_from_env(*, base_default: float, max_default: float) -> dict[str, float]:
    """Backoff windows from the environment, CLAMPED rather than fatal.

    Every other setting on this class fails fast, and should: a bad tap
    directory or an unparseable mode means the operator asked for something
    CivicCast cannot do, and starting anyway would silently caption nothing.

    These two are different in kind. They tune how long an already-degraded
    OPTIONAL feature waits before retrying. ``from_env`` runs inside the app
    lifespan, so raising here does not degrade captions -- it aborts control-
    plane startup and takes the station OFF AIR over a mistyped duration for a
    feature that is explicitly best effort. Refusing to broadcast because
    someone wrote ``60s`` instead of ``60`` is a worse failure than any
    misconfiguration it could be protecting against.

    So: unparseable or non-positive values fall back to the shipped default,
    and a maximum below the base is raised to the base. Each correction is
    logged at WARNING naming the variable, the rejected value and what is
    being used instead, so it is visible rather than silent.
    """

    base = _clamped_env_seconds(
        "CIVICCAST_CAPTION_TAP_OVERLOAD_BACKOFF_SECONDS", base_default, minimum=1.0
    )
    ceiling = _clamped_env_seconds(
        "CIVICCAST_CAPTION_TAP_MAX_OVERLOAD_BACKOFF_SECONDS", max_default, minimum=1.0
    )
    if ceiling < base:
        _LOG.warning(
            "CIVICCAST_CAPTION_TAP_MAX_OVERLOAD_BACKOFF_SECONDS (%s) is below the base "
            "backoff (%s); using the base as the ceiling so the caption tap still "
            "backs off instead of refusing to start.",
            ceiling,
            base,
        )
        ceiling = base
    return {"overload_backoff_seconds": base, "max_overload_backoff_seconds": ceiling}


def _clamped_env_seconds(name: str, default: float, *, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        _LOG.warning(
            "%s must be a number; got %r. Using the default of %ss so the station "
            "still starts -- live captions are best effort and must never hold the "
            "control plane down.",
            name,
            raw,
            default,
        )
        return default
    if value < minimum:
        _LOG.warning(
            "%s must be at least %ss; got %s. Using the default of %ss.",
            name,
            minimum,
            value,
            default,
        )
        return default
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number; got {raw!r}.") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer; got {raw!r}.") from exc
    if value < 1:
        raise ValueError(f"{name} must be at least 1; got {value}.")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean; got {raw!r}.")


@dataclass(frozen=True)
class CaptionTapScanResult:
    """Outcome of one ``run_once`` scan (or one explicit :meth:`CaptionTapWorker.flush_channel`)."""

    consumed_segments: int = 0
    quarantined_segments: int = 0
    committed_review_items: int = 0
    dropped_overload_segments: int = 0
    # Pending hypotheses the stabilizer expired without re-confirmation: never
    # committed/never on-air, but counted here so the drop is never silent
    # (civiccast/captions/stabilize.py CaptionStabilizer.expired_unconfirmed).
    expired_unconfirmed_cues: int = 0
    channels: tuple[str, ...] = field(default_factory=tuple)
    overloaded_channels: tuple[str, ...] = field(default_factory=tuple)
    # Channels whose ASR is suspended by the overload backoff for this scan --
    # both the ones that overloaded in THIS scan (they are in
    # ``overloaded_channels`` too) and the ones still inside an earlier pause
    # window, whose settled audio is drained without transcription.
    paused_channels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _ChannelScanResult:
    consumed_segments: int = 0
    quarantined_segments: int = 0
    committed_review_items: int = 0
    expired_unconfirmed_cues: int = 0


class CaptionTapWorker:
    """Consume forked audio segments into the durable caption review queue."""

    def __init__(
        self,
        *,
        tap_root: Path,
        caption_work_dir: Path,
        runtime: CaptionRuntime,
        review_store: CaptionReviewStore,
        segment_seconds: float = 5.0,
        atomic_segments: bool = False,
        overlap_seconds: float = 4.0,
        max_channel_workers: int | None = None,
        max_backlog_segments: int = 2,
        reviewer_note: str = "Auto-generated from the live broadcast audio tap.",
        translation_provider: TranslationProvider | None = None,
        retention_policy: CaptionEvidenceRetentionPolicy | None = None,
        backoff_policy: CaptionBackoffPolicy | None = None,
        is_enabled: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._tap_root = tap_root
        self._caption_work_dir = caption_work_dir.expanduser().resolve()
        self._runtime = runtime
        self._review_store = review_store
        self._segment_seconds = segment_seconds
        self._atomic_segments = atomic_segments
        if overlap_seconds <= 0:
            raise ValueError("Caption tap overlap_seconds must be greater than zero.")
        self._overlap_seconds = overlap_seconds
        if max_channel_workers is None:
            max_channel_workers = default_max_channel_workers()
        if max_channel_workers < 1:
            raise ValueError("Caption tap max_channel_workers must be at least 1.")
        if max_backlog_segments < 1:
            raise ValueError("Caption tap max_backlog_segments must be at least 1.")
        self._max_channel_workers = max_channel_workers
        self._backoff = backoff_policy or CaptionBackoffPolicy()
        # One clock for the whole worker, and the SAME clock the backoff policy
        # runs on, so a test that drives the backoff forward also drives the
        # status heartbeat forward. Monotonic, never wall-clock: a station
        # clock step must not un-pause a channel or fake a heartbeat.
        self._monotonic = monotonic or time.monotonic
        #: channel -> (semantic status key, monotonic time it was published)
        self._published_status: dict[str, tuple[tuple[object, ...], float]] = {}
        #: monotonic time of the last retention sweep, and its last verdict.
        #: ``None`` means "never swept", so the first scan always sweeps.
        self._last_retention_sweep: float | None = None
        self._retention_ready = True
        self._retention_refusal: str | None = None
        # Consulted on EVERY scan, not once at construction: the operator's
        # switch (``StationProfile.live_captions_enabled``) has to take effect
        # on a station that is on air, and restarting the control plane to
        # apply it is exactly the kind of interruption this whole change
        # exists to avoid. Default: always enabled, so an injected worker in a
        # test or an external-mode process behaves as before.
        self._is_enabled = is_enabled or (lambda: True)
        self._disabled_announced = False
        self._max_backlog_segments = max_backlog_segments
        self._reviewer_note = reviewer_note
        # S13 (T3/M4): the operator-selected translation model, injected at the same
        # DI seam summary/captions use. Threaded into each per-channel LiveCaptionWorker
        # so the running translator consults the operator's selection.
        self._translation_provider = translation_provider
        self._retention_policy = retention_policy or CaptionEvidenceRetentionPolicy.from_system(
            storage_root=self._caption_work_dir
        )
        # One persistent LiveCaptionWorker per channel so the two-window
        # stabilization contract survives across scans.
        self._channel_workers: dict[str, LiveCaptionWorker] = {}
        self._channel_publishers: dict[str, LiveWebVttPublisher] = {}
        self._previous_segments: dict[str, tuple[int, AudioChunk]] = {}
        reset_existing_live_sidecars(self._caption_work_dir)

    def run_forever(
        self,
        *,
        poll_seconds: float = 2.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Run the scan loop until ``stop_event`` is set; scan errors are logged."""

        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                _LOG.exception("Caption tap scan failed; continuing.")
            if stop_event is None:
                threading.Event().wait(poll_seconds)  # pragma: no cover - loop shape
            else:
                stop_event.wait(poll_seconds)

    def flush_channel(self, channel_id: str) -> CaptionTapScanResult:
        """Commit every cue still pending for one channel at stream end.

        Call this when the caller knows a channel's audio has ended (channel
        stop, station shutdown) so the stabilizer's last unconfirmed
        hypotheses are not lost silently -- ``run_once``/``run_forever`` only
        ever look forward and there is no second transcription pass after
        audio ends. Flushed cues persist through the exact same review-store
        and active-VTT publication path as a normal scan. Safe to call on a
        channel with no worker yet (returns zero counts) and safe to call
        twice (the second call flushes nothing new).
        """

        # The channel's audio has ended, so its overload history is spent: a
        # channel that comes back on air starts from the base delay, not from
        # whatever escalation its previous broadcast left behind.
        self._backoff.forget(channel_id)
        worker = self._channel_workers.get(channel_id)
        if worker is None:
            return CaptionTapScanResult(channels=(channel_id,))
        result = worker.flush()
        self._publisher_for(channel_id).publish(worker.committed_cues())
        return CaptionTapScanResult(
            committed_review_items=len(result.committed_review_items),
            expired_unconfirmed_cues=len(result.expired_unconfirmed_cues),
            channels=(channel_id,),
        )

    def run_once(self) -> CaptionTapScanResult:
        """Scan every channel directory once and consume settled segments."""

        consumed = 0
        quarantined = 0
        committed = 0
        dropped = 0
        expired = 0
        channels: list[str] = []
        overloaded_channels: list[str] = []
        paused_channels: list[str] = []
        if not self._tap_root.is_dir():
            return CaptionTapScanResult()
        # Retention runs BEFORE the enabled check, deliberately and in this
        # order. It prunes audio this station has ALREADY recorded --
        # `<channel>/processed/` and the review evidence -- under the station's
        # retention schedule (spec 4.3). Switching live captions off is a
        # decision about future transcription, never a licence to stop
        # deleting what is already on disk: gating pruning behind the switch
        # would freeze every retention clock for as long as the switch is off,
        # which is the exact opposite of what an operator turning captions off
        # is asking for.
        self._sweep_retention()
        if not self._is_enabled():
            return self._run_disabled()
        self._disabled_announced = False
        if not self._retention_ready:
            channels = sorted(path.name for path in self._tap_root.iterdir() if path.is_dir())
            for channel_id in channels:
                self._publish_status(
                    channel_id,
                    state="storage-refused",
                    backlog_segments=0,
                    refusal_reason=self._retention_refusal,
                )
            return CaptionTapScanResult(channels=tuple(channels))
        pending: list[tuple[str, Path, list[tuple[int, Path]]]] = []
        for channel_dir in sorted(p for p in self._tap_root.iterdir() if p.is_dir()):
            channel_id = channel_dir.name
            segments = self._settled_segments(channel_dir)
            if not segments:
                continue
            channels.append(channel_id)
            if self._backoff.is_paused(channel_id):
                # Inside an earlier pause window: spend NOTHING on ASR, but
                # still drain the settled audio so a paused channel cannot
                # grow an unbounded tap directory while it waits.
                dropped += self._drain_paused_channel(channel_id, channel_dir, segments)
                paused_channels.append(channel_id)
                continue
            if len(segments) > self._max_backlog_segments:
                dropped += self._fail_closed_overload(channel_id, channel_dir, segments)
                overloaded_channels.append(channel_id)
                paused_channels.append(channel_id)
                continue
            pending.append((channel_id, channel_dir, segments))

        if pending:
            # The executor bound is the ASR concurrency bound: channels beyond
            # it are queued inside this same scan, never transcribed
            # simultaneously. See ``default_max_channel_workers``.
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self._max_channel_workers, len(pending)),
                thread_name_prefix="civiccast-caption-channel",
            ) as pool:
                results = list(pool.map(lambda args: self._process_channel(*args), pending))
            consumed += sum(result.consumed_segments for result in results)
            quarantined += sum(result.quarantined_segments for result in results)
            committed += sum(result.committed_review_items for result in results)
            expired += sum(result.expired_unconfirmed_cues for result in results)
        return CaptionTapScanResult(
            consumed_segments=consumed,
            quarantined_segments=quarantined,
            committed_review_items=committed,
            dropped_overload_segments=dropped,
            expired_unconfirmed_cues=expired,
            channels=tuple(channels),
            overloaded_channels=tuple(overloaded_channels),
            paused_channels=tuple(paused_channels),
        )

    def _process_channel(
        self,
        channel_id: str,
        channel_dir: Path,
        segments: list[tuple[int, Path]],
    ) -> _ChannelScanResult:
        # This thread is about to run ASR. Hint the scheduler that it must
        # yield to the playout workers when the box is saturated.
        _lower_current_thread_priority()
        consumed = 0
        quarantined = 0
        committed = 0
        expired = 0
        for index, segment in segments:
            processed = channel_dir / "processed" / segment.name
            if processed.exists():
                collision_path = self._move_collision(segment, channel_dir / "collision")
                self._retention_policy.record_event(
                    outcome="quarantined",
                    reason="restarted-chunk-index-collision",
                    path=collision_path,
                    sha256=_sha256(collision_path),
                )
                quarantined += 1
                continue
            raw_chunk = self._read_chunk(channel_id, index, segment)
            if raw_chunk is None:
                self._previous_segments.pop(channel_id, None)
                self._move(segment, channel_dir / "quarantine")
                quarantined += 1
                continue
            chunk = self._with_overlap(channel_id, index, raw_chunk)
            worker = self._worker_for(channel_id)
            result = worker.process_batch(
                [chunk],
                audio_evidence_factory=self._audio_evidence_factory(channel_id, chunk),
            )
            self._publisher_for(channel_id).publish(worker.committed_cues())
            committed += len(result.committed_review_items)
            expired += len(result.expired_unconfirmed_cues)
            self._move(segment, channel_dir / "processed")
            self._previous_segments[channel_id] = (index, raw_chunk)
            consumed += 1
        # One healthy scan. The policy forgives the channel's escalation only
        # after several of these in a row, so a channel that flaps does not
        # reset itself to the base delay every other scan.
        self._backoff.record_within_capacity(channel_id)
        self._publish_status(
            channel_id,
            state="within-capacity",
            backlog_segments=len(segments),
        )
        return _ChannelScanResult(
            consumed_segments=consumed,
            quarantined_segments=quarantined,
            committed_review_items=committed,
            expired_unconfirmed_cues=expired,
        )

    def _fail_closed_overload(
        self,
        channel_id: str,
        channel_dir: Path,
        segments: list[tuple[int, Path]],
    ) -> int:
        self._clear_channel_captions(channel_id)
        state = self._backoff.record_overload(channel_id)
        self._publish_status(
            channel_id,
            state="paused",
            backlog_segments=len(segments),
            resume_in_seconds=state.pause_seconds,
            consecutive_overloads=state.consecutive_overloads,
        )
        # WARNING, once per pause window -- not CRITICAL every scan. The field
        # log this replaces carried 663 caption lines, the same CRITICAL
        # repeating every ~30s for all three channels, while the real casualty
        # was the playout worker being restarted by its stall watchdog. An
        # overloaded caption tap is a degraded optional feature, not a station
        # emergency, and it must not drown the log the operator needs.
        _LOG.warning(
            "Caption tap overload for channel %s: %d settled segments exceeds "
            "the maximum %d. Live captions are PAUSED for %.0fs (overload #%d) so "
            "playout keeps the CPU; active captions were cleared and the stale "
            "audio was discarded.",
            channel_id,
            len(segments),
            self._max_backlog_segments,
            state.pause_seconds,
            state.consecutive_overloads,
        )
        # DISCARDED, not filed under `<channel>/overload/`. That directory was
        # never swept by anything -- the retention policy's tap sweep reads
        # `processed/` only (civiccast/captions/retention.py) -- and no review
        # row ever referenced it, so on a chronically overloaded station it
        # grew without bound across every pause cycle: one directory of raw
        # broadcast audio per channel, accumulating for as long as the station
        # could not keep up, with no retention clock on it at all. Audio that
        # was never transcribed and can never be reviewed is not evidence; it
        # is a disk leak wearing the word.
        for _index, segment in segments:
            segment.unlink(missing_ok=True)
        return len(segments)

    def _sweep_retention(self) -> None:
        """Enforce the retention schedule, on its own slower cadence.

        Called before the enabled check, deliberately: this prunes audio the
        station has ALREADY recorded, and switching live captions off is a
        decision about future transcription, not a licence to stop deleting
        what is on disk. Its verdict is cached so a scan that skips the sweep
        still fails closed on a storage refusal seen earlier, rather than
        quietly reverting to "ready" between sweeps.
        """

        now = self._monotonic()
        if (
            self._last_retention_sweep is not None
            and now - self._last_retention_sweep < _RETENTION_SWEEP_SECONDS
        ):
            return
        retention = self._retention_policy.enforce_discovered(
            tap_root=self._tap_root,
            review_store=self._review_store,
            segment_seconds=self._segment_seconds,
        )
        self._last_retention_sweep = now
        self._retention_ready = bool(retention.ready)
        self._retention_refusal = retention.refusal_reason

    def _run_disabled(self) -> CaptionTapScanResult:
        """The operator turned live captions OFF: transcribe nothing, keep nothing.

        The egress audio fork is part of the playout graph and keeps writing a
        segment every few seconds regardless of this switch, so "off" cannot
        just mean "stop reading". Every channel's live VTT is blanked, the
        status reads ``disabled``, and settled audio is DELETED rather than
        filed as evidence -- a station that switched live captioning off has
        not asked CivicCast to keep a rolling recording of its broadcast audio.
        """

        if not self._disabled_announced:
            # Clear by the CHANNEL SET, not by tap-directory presence. A
            # channel whose tap directory was never created (or was already
            # swept) has no directory to iterate, yet it can still be serving a
            # stale ``active.vtt`` from before the switch was thrown -- captions
            # on air that nothing is producing any more. ``reset_existing_live_
            # sidecars`` blanks every channel that HAS a live sidecar, which is
            # exactly that set; the loop below then handles the per-channel ASR
            # state for the channels this worker knows about.
            reset_existing_live_sidecars(self._caption_work_dir)
            for channel_id in sorted(
                {*self._channel_workers, *self._channel_publishers, *self._previous_segments}
            ):
                self._clear_channel_captions(channel_id)
                self._backoff.forget(channel_id)

        channels: list[str] = []
        discarded = 0
        for channel_dir in sorted(p for p in self._tap_root.iterdir() if p.is_dir()):
            channel_id = channel_dir.name
            channels.append(channel_id)
            if not self._disabled_announced:
                self._clear_channel_captions(channel_id)
                self._backoff.forget(channel_id)
            # Throttled: "disabled" is a steady state that can hold for weeks.
            # Rewriting it every 2 seconds is a durable write per channel per
            # scan carrying no new information.
            self._publish_status(channel_id, state="disabled", backlog_segments=0)
            for _index, segment in self._settled_segments(channel_dir):
                segment.unlink(missing_ok=True)
                discarded += 1
        if not self._disabled_announced:
            _LOG.info(
                "Live captions are switched off for this station "
                "(StationProfile.live_captions_enabled); the caption tap is "
                "discarding forked audio without transcribing it."
            )
            self._disabled_announced = True
        return CaptionTapScanResult(
            dropped_overload_segments=discarded,
            channels=tuple(channels),
        )

    def _drain_paused_channel(
        self,
        channel_id: str,
        channel_dir: Path,
        segments: list[tuple[int, Path]],
    ) -> int:
        """Discard settled audio for a paused channel without transcribing it.

        The pause is the whole point: not one sample is handed to the ASR
        runtime while it holds. Draining is still required -- the egress audio
        tap keeps publishing a segment every few seconds whether anyone reads
        them or not, so a paused channel that kept its segments would fill the
        station's disk instead of its CPU.
        """

        self._publish_status(
            channel_id,
            state="paused",
            backlog_segments=len(segments),
            resume_in_seconds=self._backoff.remaining_seconds(channel_id),
            consecutive_overloads=self._backoff.state(channel_id).consecutive_overloads,
        )
        # DELETED, not filed as evidence. `<channel>/overload/` is swept by
        # nothing -- the retention policy's tap sweep reads `processed/` only
        # -- so a station stuck in a long backoff would accumulate its own
        # broadcast audio there forever, unpruned and unreferenced by any
        # review row. The one-off `_fail_closed_overload` move that opens a
        # pause still files its segments as overload evidence, which is what
        # the capacity proof's negative control inspects; the unbounded
        # per-scan drain that follows it must not.
        for _index, segment in segments:
            segment.unlink(missing_ok=True)
        return len(segments)

    def _publish_status(
        self,
        channel_id: str,
        *,
        state: CaptionRuntimeState,
        backlog_segments: int,
        refusal_reason: str | None = None,
        resume_in_seconds: float | None = None,
        consecutive_overloads: int | None = None,
    ) -> bool:
        """Publish channel status only when it CHANGED, or when it went stale.

        The scan loop runs every ~2 seconds per channel forever. Rewriting an
        unchanged status file on every one of those scans is a durable write
        (the publisher fsyncs and renames) for no new information: a
        three-channel station idles at ~90 pointless fsync+rename pairs a
        minute, against the same disk the recordings are written to.

        Two things are excluded from the comparison on purpose. ``updated_at``
        always differs, so comparing whole payloads would never suppress
        anything. ``resume_in_seconds`` ticks down continuously while a channel
        is paused, so it would do the same -- it is therefore not part of the
        change key, and freshness is preserved instead by the
        :data:`_STATUS_REFRESH_SECONDS` heartbeat below, which still republishes
        a steady state periodically so an operator's countdown advances and
        ``updated_at`` never looks abandoned.
        """

        key = (state, backlog_segments, consecutive_overloads, refusal_reason)
        now = self._monotonic()
        previous = self._published_status.get(channel_id)
        if previous is not None:
            previous_key, published_at = previous
            if previous_key == key and now - published_at < _STATUS_REFRESH_SECONDS:
                return False
        publish_caption_runtime_status(
            self._caption_work_dir,
            channel_id,
            state=state,
            backlog_segments=backlog_segments,
            max_backlog_segments=self._max_backlog_segments,
            refusal_reason=refusal_reason,
            resume_in_seconds=resume_in_seconds,
            consecutive_overloads=consecutive_overloads,
        )
        self._published_status[channel_id] = (key, now)
        return True

    def _clear_channel_captions(self, channel_id: str) -> None:
        """Fail closed: drop the channel's ASR state and blank its live VTT."""

        self._channel_workers.pop(channel_id, None)
        publisher = self._channel_publishers.pop(channel_id, None)
        if publisher is None:
            publisher = LiveWebVttPublisher(
                active_caption_sidecar(self._caption_work_dir, channel_id)
            )
        publisher.reset()
        self._previous_segments.pop(channel_id, None)

    def _settled_segments(self, channel_dir: Path) -> list[tuple[int, Path]]:
        """Numbered segments with a newer sibling (ffmpeg moved past them)."""

        numbered: list[tuple[int, Path]] = []
        for path in channel_dir.iterdir():
            match = _SEGMENT_RE.match(path.name)
            if match is not None and path.is_file():
                numbered.append((int(match.group(1)), path))
        numbered.sort()
        # GStreamer publishes through ``.wav.partial -> .wav`` atomically, so
        # every visible WAV is complete. Legacy FFmpeg segment output writes the
        # highest WAV in place; preserve its one-file settling guard.
        return numbered if self._atomic_segments else numbered[:-1]

    def _read_chunk(self, channel_id: str, index: int, path: Path) -> AudioChunk | None:
        try:
            with wave.open(str(path), "rb") as handle:
                rate = handle.getframerate()
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                frames = handle.readframes(handle.getnframes())
            if channels != 1 or width != 2:
                raise ValueError(f"expected mono s16le tap audio, got {channels}ch/{width * 8}-bit")
            if not frames:
                raise ValueError("segment contains no audio frames")
        except Exception:
            _LOG.exception("Unreadable caption tap segment for channel %s: %s", channel_id, path)
            return None
        duration = len(frames) / 2 / rate
        start = index * self._segment_seconds
        return AudioChunk(
            chunk_id=f"{channel_id}-tap-{index:06d}",
            start_seconds=start,
            end_seconds=start + duration,
            sample_rate_hz=rate,
            pcm_s16le=frames,
        )

    def _worker_for(self, channel_id: str) -> LiveCaptionWorker:
        worker = self._channel_workers.get(channel_id)
        if worker is None:
            worker = LiveCaptionWorker(
                self._runtime,
                self._review_store,
                asset_id=channel_id,
                reviewer_note=self._reviewer_note,
                translation_provider=self._translation_provider,
            )
            self._channel_workers[channel_id] = worker
        return worker

    def _audio_evidence_factory(
        self,
        channel_id: str,
        chunk: AudioChunk,
    ) -> AudioEvidenceFactory:
        """Return one lazy evidence writer bound to this channel and ASR window."""

        evidence: CaptionReviewAudioEvidence | None = None

        def write_once(_cue: CaptionCue) -> CaptionReviewAudioEvidence:
            nonlocal evidence
            if evidence is None:
                digest = hashlib.sha256(chunk.chunk_id.encode("utf-8")).hexdigest()[:24]
                evidence = write_caption_review_audio_evidence(
                    chunk,
                    self._caption_work_dir / channel_id / "captions" / "evidence" / f"{digest}.wav",
                )
            return evidence

        return write_once

    def _with_overlap(
        self,
        channel_id: str,
        index: int,
        current: AudioChunk,
    ) -> AudioChunk:
        """Prepend the prior segment tail so consecutive ASR windows overlap."""

        previous_entry = self._previous_segments.get(channel_id)
        if previous_entry is None:
            return current
        previous_index, previous = previous_entry
        if previous_index + 1 != index or previous.sample_rate_hz != current.sample_rate_hz:
            return current
        sample_tolerance = 1.0 / current.sample_rate_hz
        if abs(previous.end_seconds - current.start_seconds) > sample_tolerance:
            return current

        available_frames = len(previous.pcm_s16le) // 2
        requested_frames = round(self._overlap_seconds * current.sample_rate_hz)
        overlap_frames = min(available_frames, requested_frames)
        if overlap_frames <= 0:
            return current
        overlap_bytes = overlap_frames * 2
        actual_overlap = overlap_frames / current.sample_rate_hz
        return AudioChunk(
            chunk_id=f"{current.chunk_id}-overlap",
            start_seconds=current.start_seconds - actual_overlap,
            end_seconds=current.end_seconds,
            sample_rate_hz=current.sample_rate_hz,
            pcm_s16le=previous.pcm_s16le[-overlap_bytes:] + current.pcm_s16le,
        )

    def _publisher_for(self, channel_id: str) -> LiveWebVttPublisher:
        publisher = self._channel_publishers.get(channel_id)
        if publisher is None:
            publisher = LiveWebVttPublisher(
                active_caption_sidecar(self._caption_work_dir, channel_id)
            )
            publisher.reset()
            self._channel_publishers[channel_id] = publisher
        return publisher

    @staticmethod
    def _move(path: Path, into: Path) -> None:
        into.mkdir(parents=True, exist_ok=True)
        path.replace(into / path.name)

    @staticmethod
    def _move_collision(path: Path, into: Path) -> Path:
        into.mkdir(parents=True, exist_ok=True)
        destination = into / path.name
        if destination.exists():
            destination = into / f"{path.stem}-{_sha256(path)[:12]}{path.suffix}"
        path.replace(destination)
        return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_tap_worker(
    settings: CaptionTapWorkerSettings,
    review_store: CaptionReviewStore,
    *,
    runtime: CaptionRuntime | None = None,
    translation_provider: TranslationProvider | None = None,
    caption_work_dir: Path | None = None,
    is_enabled: Callable[[], bool] | None = None,
) -> CaptionTapWorker:
    """Construct a tap worker from deployment settings.

    Without an injected runtime, ``CIVICCAST_CAPTION_RUNTIME`` selects the
    runtime. Activated native stations are locked to the accepted
    faster-whisper large-v3 contract. Runtime failures surface immediately
    (fail fast, never a silent no-op).
    ``translation_provider`` (S13) is the operator-selected translation model; when
    omitted no translation track is produced.
    """

    if settings.tap_root is None:
        raise ValueError("Caption tap worker requires a tap_root (CIVICCAST_CAPTION_TAP_DIR).")
    if runtime is None:
        backend = (
            os.environ.get(
                "CIVICCAST_CAPTION_RUNTIME",
                "faster-whisper",
            )
            .strip()
            .lower()
        )
        if (
            os.environ.get("CIVICCAST_NATIVE_STATION", "").strip() == "1"
            and backend != "faster-whisper"
        ):
            raise ValueError(
                "Activated native stations require the accepted faster-whisper "
                "large-v3 caption runtime."
            )
        if backend == "faster-whisper":
            # NOT num_workers=max_channel_workers. Those are unrelated
            # quantities: max_channel_workers is how many CHANNELS this worker
            # may caption at once and is already spent on the
            # ThreadPoolExecutor in _scan_once, while faster-whisper's
            # num_workers is CTranslate2's inter_threads. Passing one as the
            # other is a category error regardless of what it costs.
            #
            # MEASURED, and it does NOT cost what I claimed. I originally
            # changed this believing inter_threads replicated the model and
            # therefore explained the 16 GB field failure. TESTER2 A/B'd it on
            # a real station (request 0192): same audio, same 12 segments,
            # override verified live, real faster-whisper inference confirmed
            # from the VAD/language rows. Going from 3 to 1 moved the private-
            # byte plateau by 3.93% -- 5.41 GB to 5.20 GB -- not to a third.
            # The replication hypothesis is REFUTED. Do not repeat it.
            #
            # What this change is actually worth: ~2.9% peak private, ~18% peak
            # RSS, and a 3.6% speedup at no measured cost. A tidy-up, not a fix.
            #
            # The real defect is still open and is NOT a leak: both runs held a
            # FLAT shelf from segment 1 and completed 12/12. It is a fixed
            # ~5.4 GB commit against only ~1.1 GB resident -- i.e. commit
            # charge, which is what actually exhausts a 16 GB box. Next
            # suspects are compute_type and cpu_threads sizing CTranslate2's
            # arenas, not the worker count.
            #
            # Deliberately overridable: CIVICCAST_WHISPER_NUM_WORKERS.
            #
            # ``live=True``: this is the live captioner, sharing a box with
            # playout, so the runtime sizes ITSELF conservatively -- one
            # CTranslate2 intra-thread and greedy decoding once it resolves to
            # CPU (civiccast.captions.runtime.LIVE_TAP_CPU_THREADS records the
            # measured field failure the batch sizing produced here).
            #
            # NOTE this branch runs only for the EXTERNAL entrypoint and for
            # callers that inject no runtime. The native service pre-builds the
            # runtime through civiccast.ai_models.runtime.build_caption_runtime
            # and injects it, which is exactly why ``live`` is a property of
            # the RUNTIME and not a bundle of kwargs applied here: kwargs here
            # were dead code in the product, and the live tap went on using
            # every core at beam 5.
            from civiccast.captions.runtime import FasterWhisperRuntime

            runtime = FasterWhisperRuntime(live=True)
        elif backend == "whispercpp-vulkan":
            from civiccast.captions.runtime import WhisperCppRuntime

            executable = os.environ.get("CIVICCAST_WHISPER_CPP_EXE", "").strip()
            model = os.environ.get("CIVICCAST_WHISPER_CPP_MODEL_PATH", "").strip()
            if not executable or not model:
                raise ValueError(
                    "CIVICCAST_WHISPER_CPP_EXE and "
                    "CIVICCAST_WHISPER_CPP_MODEL_PATH must be set when "
                    "CIVICCAST_CAPTION_RUNTIME='whispercpp-vulkan'."
                )
            runtime = WhisperCppRuntime(
                executable=Path(executable),
                model=Path(model),
            )
        else:
            raise ValueError(
                "CIVICCAST_CAPTION_RUNTIME must be 'faster-whisper' or "
                f"'whispercpp-vulkan'; got {backend!r}."
            )
    if caption_work_dir is None:
        from civiccast.egress.automation import default_egress_work_dir

        caption_work_dir = default_egress_work_dir()
    return CaptionTapWorker(
        tap_root=settings.tap_root,
        caption_work_dir=caption_work_dir,
        runtime=runtime,
        review_store=review_store,
        segment_seconds=settings.segment_seconds,
        atomic_segments=settings.atomic_segments,
        overlap_seconds=settings.overlap_seconds,
        max_channel_workers=settings.max_channel_workers,
        max_backlog_segments=settings.max_backlog_segments,
        translation_provider=translation_provider,
        backoff_policy=CaptionBackoffPolicy(
            base_seconds=settings.overload_backoff_seconds,
            max_seconds=settings.max_overload_backoff_seconds,
        ),
        is_enabled=is_enabled,
    )


def main(argv: list[str] | None = None) -> int:
    """External entrypoint: ``python -m civiccast.captions.tap_worker``.

    Requires ``DATABASE_URL`` (durable review queue) and the same
    ``CIVICCAST_CAPTION_TAP*`` settings as the in-app thread; the mode value
    is not consulted — running this entrypoint IS the external mode.
    """

    parser = argparse.ArgumentParser(
        prog="python -m civiccast.captions.tap_worker",
        description="CivicCast live caption tap worker (external process mode).",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run a single scan and exit (smoke checks)."
    )
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        parser.error("DATABASE_URL must be set to run the caption tap worker.")

    logging.basicConfig(level=logging.INFO)

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from civiccast.captions.persistence import PostgresCaptionReviewStore
    from civiccast.db import connect_options
    from civiccast.db.url import normalize_database_url

    database_url = normalize_database_url(database_url)
    engine = create_engine(
        database_url, future=True, pool_pre_ping=True, **connect_options(database_url)
    )
    if database_url.startswith("sqlite"):
        engine = engine.execution_options(schema_translate_map={"civiccast": None})

    @contextmanager
    def _session_factory():  # type: ignore[no-untyped-def]
        with Session(bind=engine) as session:
            yield session

    settings = CaptionTapWorkerSettings.from_env()
    worker = build_tap_worker(settings, PostgresCaptionReviewStore(_session_factory))
    if args.once:
        worker.run_once()
        return 0
    stop_event = threading.Event()
    try:
        worker.run_forever(poll_seconds=settings.poll_seconds, stop_event=stop_event)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown path
        stop_event.set()
        _LOG.info("Caption tap worker interrupted; exiting.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via external mode
    raise SystemExit(main())
