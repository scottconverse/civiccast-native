# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S21 scheduled-recording service layer (slice 2).

Sits above :mod:`civiccast.recording.store` and provides the operations
the router (slice 3) consumes — recurrence expansion, the
state-machine progression (``scheduled → arming → recording →
finalizing → done``), the ad-hoc "record now" entrypoint, and the
startup orphan-job reconciliation hook.

The capture pipeline, the asset finalizer, and the alert sink are all
injected as :class:`typing.Protocol` seams so the service has zero
runtime dependency on S15 (GStreamer), S7 (asset/readiness), or S8
(alert hub). Production wiring plugs the real implementations in; unit
tests inject in-memory stubs that record method calls.

Failure handling is built around the "never a silent miss" invariant
(DC-3):

* A capture-pipeline error at arm / start / finalize / stop transitions
  the job to ``failed`` AND fires an S8 alert through the injected
  sink — the operator console sees the failure within seconds.
* Overlap is re-checked at arm time (DC-5) even though the materializer
  already filtered at expansion time. A schedule edit, a manual
  ``record_now``, or a window-stretching transcoder estimate could
  have introduced a conflict between expand-time and arm-time; we
  prefer ``skipped`` (with a logged reason) over a torn capture.
* Loudness regime (S11) is passed verbatim through to the finalizer —
  the gate itself lives in the engine, but the service refuses to
  drop the regime on the floor at any handoff (DC-6).

When a Protocol seam is ``None``, the service treats the feature as
"disabled": ``record_now`` / ``arm_job`` raise
:class:`RecordingPipelineUnwiredError`, and a missing alert sink degrades
to a log line (the gate still trips — the operator just sees it in
``journalctl`` rather than the alert hub).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from civiccast.recording.models import (
    JOB_STATE_ACTIVE,
    RecordingJob,
    RecordingSource,
    RecurrenceSpec,
)
from civiccast.recording.store import (
    RecordingJobIdConflictError,
    RecordingJobNotFoundError,
    RecordingJobOverlapError,
    RecordingJobStateError,
    RecordingScheduleNotFoundError,
    RecordingStore,
)

logger = logging.getLogger(__name__)

#: How far ahead of ``planned_start`` :meth:`RecordingService.tick` arms
#: a job. 30 seconds is enough for a GStreamer arm + first-frame on a
#: warm encoder profile; a SDI input on a cold receiver may take longer
#: (S15 follow-up — once we have a measured arm budget per profile, the
#: lead becomes per-profile rather than constant). The default is a
#: deliberate over-allocation: arming early and waiting is fine; arming
#: late and missing the first frame is not.
DEFAULT_ARM_LEAD = timedelta(seconds=30)

#: Default horizon for :meth:`RecordingService.tick` — match the spec's
#: §6 "scheduler runs on the S19 cadence" guidance. Ten minutes is the
#: same window the program-log materializer uses for its "what's coming
#: up next" projection.
DEFAULT_TICK_HORIZON = timedelta(minutes=10)

#: Default ceiling on jobs returned per ``expand_jobs_for_horizon`` /
#: ``tick`` materialization pass. E-5 fix: pre-fix the service used a
#: magic-number ``limit=10_000`` on the underlying ``list_jobs`` calls
#: with no warning / alert when the cap was hit. A station with 10k+
#: historical jobs would silently lose materializer idempotency (the
#: ``taken`` set went stale) and the next tick would PK-collide. The cap
#: is now explicit on the service constructor; exceeding it emits a
#: warning log AND an S8 alert so the operator sees the truncation.
DEFAULT_MAX_JOBS_PER_TICK = 1_000


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _pipeline_failure_reason(phase: str) -> str:
    """Operator-facing failure text for capture engine exceptions."""

    return (
        f"Recording could not complete the {phase} step. "
        "The source, encoder, or storage backend returned an error; "
        "see the server log for technical details."
    )


# ---------------------------------------------------------------------------
# Protocol seams (capture pipeline, asset finalizer, alert sink)
# ---------------------------------------------------------------------------


class TickCounters(BaseModel):
    """Typed return value from :meth:`RecordingService.tick` (E-14 fix).

    Pre-fix the tick returned a raw ``dict`` and the caller had no
    contract; metrics + UI consumers had to feel the shape out. The
    typed model lets the OpenAPI generator emit the schema directly and
    lets downstream code use attribute access.
    """

    model_config = ConfigDict(extra="forbid")

    expanded: int = Field(ge=0)
    armed: int = Field(ge=0)
    started: int = Field(ge=0)
    finalized: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)
    dropouts_detected: int = Field(default=0, ge=0)


class CaptureResult(BaseModel):
    """Typed return value from the capture pipeline.

    ``sha256`` is optional — a cheap-to-compute capture pipeline
    streams it during the write; an SDI pipeline that bails on a torn
    capture may leave it ``None`` and let the finalizer recompute over
    the file. Either way, the value is forwarded to the asset
    finalizer so the produced asset has a content hash (DC-1).
    """

    model_config = ConfigDict(extra="forbid")

    bytes_written: int = Field(ge=0)
    capture_path: str = Field(min_length=1, max_length=2000)
    sha256: str | None = Field(default=None, max_length=64)


class DropoutCheckResult(BaseModel):
    """Outcome of one :meth:`CapturePipelineProtocol.check_dropout` poll
    (item 6: recording/ingest hardening — mid-recording source dropout).

    ``dropout_detected`` is True the poll that first notices the source is
    gone (process died, or the source stalled with no new bytes). When a
    dropout is detected the pipeline attempts its own reconnect inline
    (same call) and reports whether that reconnect succeeded via
    ``reconnected``; ``recording`` stays the job state either way — only a
    reconnect attempt that itself raises fails the job, via the normal
    pipeline-exception path the caller already handles.
    """

    model_config = ConfigDict(extra="forbid")

    dropout_detected: bool
    reconnected: bool = False
    detail: str = ""


class RecordingDrainResult(BaseModel):
    """Outcome of :meth:`RecordingService.drain_in_flight` — the bounded,
    best-effort graceful stop of in-flight recording jobs on app shutdown.

    ``considered`` is every job found in an active state
    (``arming``/``recording``/``finalizing``) at drain time. ``finalized``
    reached a terminal ``done`` with a real asset; ``failed`` reached
    ``failed`` (a torn/zero-byte capture, an ``arming`` job that never
    recorded, or a per-job stop that raised); ``not_drained`` was left
    untouched because the deadline elapsed first — those jobs stay in their
    active state for the next boot's ``reconcile_orphans`` hook to fail
    cleanly, exactly the pre-drain behaviour (never worse).
    """

    model_config = ConfigDict(extra="forbid")

    considered: int = Field(ge=0)
    finalized: int = Field(ge=0)
    failed: int = Field(ge=0)
    not_drained: int = Field(ge=0)


class CapturePipelineProtocol(Protocol):
    """Engine-side capture seam.

    Production wires this to the S15 GStreamer pipeline. Tests inject a
    stub that records ``arm`` / ``start`` / ``finalize`` / ``stop`` so
    the contract is exercised without opening real sockets or file
    handles.

    Implementations MUST:

    * Raise on a source-unreachable / disk-full / pipeline-crash —
      the service translates the raise into ``failed`` + an S8 alert.
    * Be idempotent on repeat ``arm`` calls (the service guards
      transitions, but a transient retry shouldn't double-allocate).
    * Return a :class:`CaptureResult` from both ``finalize`` (window-
      end) and ``stop`` (operator stop). A ``stop``-result with
      ``bytes_written=0`` is treated as a torn capture and
      transitioned to ``failed``.

    Implementations MAY optionally expose ``stop_arming(job_id)`` — when
    present the service calls it when the operator stops a job from the
    ``arming`` state (pre-recording-phase abort). When absent the
    service short-circuits the ``arming``-state stop to ``failed``
    without invoking ``stop`` (which would have no live mux to halt).
    E-4 fix.

    Implementations MAY optionally expose
    ``check_dropout(job_id) -> DropoutCheckResult`` — when present the
    service's scheduler tick calls it once per poll for every
    ``recording``-state job (item 6). When absent, dropout detection is a
    no-op (the feature degrades to today's behavior: a dead source only
    surfaces at window-end finalize).
    """

    def arm(
        self,
        *,
        job_id: str,
        source: RecordingSource,
        encoder_profile: str,
        loudness_regime: str,
    ) -> None: ...

    def start(self, job_id: str) -> None: ...

    def finalize(self, job_id: str) -> CaptureResult: ...

    def stop(self, job_id: str) -> CaptureResult: ...


class AssetFinalizerProtocol(Protocol):
    """Asset+readiness seam (DC-4 — produces a normal :class:`Asset`).

    Production wires this to the S7 ingest pipeline; tests inject a
    stub that returns a deterministic asset id. Returning ``str`` is
    deliberate — the service has no use for the full asset model.
    """

    def finalize_to_asset(
        self,
        *,
        station_id: str,
        capture_path: str,
        target_series: str | None,
        custom_field_values: dict[str, Any],
        sha256: str | None,
    ) -> str: ...


class AlertSinkProtocol(Protocol):
    """Operational-alert seam (DC-3 — "never a silent miss").

    Production wires this to the S8 alert hub; tests inject a recording
    stub. An implementation that itself raises must NOT cause the
    enclosing job-transition to roll back — the alert is best-effort,
    the job state is durable.
    """

    def emit(
        self,
        *,
        severity: str,
        source: str,
        message: str,
        context: dict[str, Any],
    ) -> None: ...


# ---------------------------------------------------------------------------
# Typed exceptions (router maps to status codes; messages echo no secrets)
# ---------------------------------------------------------------------------


class RecordingServiceError(RuntimeError):
    """Base error raised by :class:`RecordingService` operations."""


class RecordingPipelineUnwiredError(RecordingServiceError):
    """Raised when an operation needs the capture pipeline but the
    service was constructed without one (DI seam is ``None``).

    The router maps this to 503 — same posture as a missing store: a
    silent 200 against an unwired engine would let the operator think
    a recording started when nothing did.
    """


class RecordingPipelineFailureError(RecordingServiceError):
    """Raised when the capture pipeline itself raises during a
    transition. The service has already transitioned the job to
    ``failed`` and emitted an S8 alert before re-raising; this exception
    surfaces the cause to the router so the response detail can name it
    (sanitized — no paths or tokens echo through)."""


# Re-exports so the router can catch the store's NotFound errors without
# importing two modules.
__all_reexports__ = (
    RecordingJobNotFoundError,
    RecordingScheduleNotFoundError,
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RecordingService:
    """Recurrence expansion + state-machine progression + ad-hoc capture."""

    def __init__(
        self,
        store: RecordingStore,
        *,
        capture_pipeline: CapturePipelineProtocol | None = None,
        asset_finalizer: AssetFinalizerProtocol | None = None,
        alert_sink: AlertSinkProtocol | None = None,
        clock: Callable[[], datetime] | None = None,
        arm_lead: timedelta = DEFAULT_ARM_LEAD,
        max_jobs_per_tick: int = DEFAULT_MAX_JOBS_PER_TICK,
    ) -> None:
        self._store = store
        self._pipeline = capture_pipeline
        self._finalizer = asset_finalizer
        self._alert_sink = alert_sink
        self._clock = clock or _utcnow
        self._arm_lead = arm_lead
        # E-5 fix: cap is explicit and configurable; exceeding it logs +
        # alerts rather than silently truncating.
        self._max_jobs_per_tick = max_jobs_per_tick

    # ------------------------------------------------------------------
    # Recurrence expansion (DC-2)
    # ------------------------------------------------------------------

    def expand_jobs_for_horizon(
        self,
        station_id: str,
        horizon: timedelta,
    ) -> list[RecordingJob]:
        """Materialize jobs for every enabled schedule at the station
        across ``[now, now + horizon]``.

        DC-2 deterministic round-trip: for the same store contents and
        the same ``now``, the function returns the same set of jobs.
        Idempotency is enforced by ``(schedule_id, planned_start)`` —
        an existing job at that exact start (in ANY state) means we've
        already materialized this occurrence; we skip it.

        Overlap (DC-5) is NOT decided here. The materializer cannot
        know what the operator will arm in the next minute — a
        ``record_now`` call between expand and arm could conflict. We
        re-run the overlap check inside :meth:`arm_job` so the
        ``skipped`` row lands at arm-time with the right reason.
        """
        now = self._clock()
        deadline = now + horizon
        schedules = self._store.list_schedules(station_id, enabled_only=True)
        # E-5 fix: pre-fix the existence probe was ``list_jobs(limit=10_000)``
        # which silently truncated at ~10k historical jobs and left the
        # ``taken`` set stale (materializer started re-creating jobs and
        # PK-colliding). We now bound the probe by the cap and warn +
        # alert when it's exhausted; production should re-evaluate the
        # cap rather than silently lose idempotency.
        existing_jobs = self._store.list_jobs(station_id, limit=self._max_jobs_per_tick)
        if len(existing_jobs) >= self._max_jobs_per_tick:
            logger.warning(
                "recording.expand_jobs_for_horizon truncated at cap "
                "(station_id=%s cap=%d); materializer idempotency may be lost.",
                station_id,
                self._max_jobs_per_tick,
            )
            self._emit_alert(
                severity="warning",
                source="recording.expand",
                message=("Job history exceeded materializer cap; idempotency may be lost."),
                context={
                    "station_id": station_id,
                    "cap": self._max_jobs_per_tick,
                },
            )
        # The materializer compares (schedule_id, planned_start) — a
        # one-shot's start is exact; a weekly's materialized start is
        # the UTC-midnight + time_hhmm of the target day. We compare
        # by epoch seconds (timezone-aware) to avoid tz-naive surprises
        # against SQLite's date storage.
        taken: set[tuple[str, float]] = {
            (job.schedule_id or "", job.planned_start.timestamp())
            for job in existing_jobs
            if job.schedule_id is not None
        }
        created: list[RecordingJob] = []
        for schedule in schedules:
            for planned_start in _materialize_starts(schedule.recurrence, now, deadline):
                key = (schedule.schedule_id, planned_start.timestamp())
                if key in taken:
                    continue
                planned_end = planned_start + timedelta(seconds=schedule.duration_seconds)
                job = RecordingJob(
                    job_id=_job_id_for(schedule.schedule_id, planned_start),
                    station_id=schedule.station_id,
                    schedule_id=schedule.schedule_id,
                    planned_start=planned_start,
                    planned_end=planned_end,
                    source_snapshot=schedule.source,
                    encoder_profile=schedule.encoder_profile,
                    loudness_regime=schedule.loudness_regime,
                    target_series=schedule.target_series,
                    custom_field_values=dict(schedule.custom_field_values),
                )
                try:
                    created.append(self._store.create_job(job))
                except RecordingJobIdConflictError:
                    # E-6 fix: a PK collision here means a sibling
                    # materializer (or a prior tick that the truncated
                    # ``existing_jobs`` probe missed) already created
                    # this exact (schedule_id, planned_start) job. The
                    # operation is idempotent by design — skip it.
                    logger.debug(
                        "recording.expand_jobs_for_horizon skipping pre-existing "
                        "job_id=%s schedule_id=%s",
                        job.job_id,
                        schedule.schedule_id,
                    )
                    pass
                taken.add(key)
        return created

    # ------------------------------------------------------------------
    # State-machine progression (DC-1, DC-3, DC-5, DC-6)
    # ------------------------------------------------------------------

    def arm_job(self, job_id: str) -> RecordingJob:
        """Transition a ``scheduled`` job to ``arming`` and call the
        capture pipeline's ``arm``.

        DC-5: overlap is re-checked here, NOT just at expansion time.
        A second job in an overlapping window on the same source
        transitions to ``skipped`` with a structured reason.

        DC-3: a capture-pipeline raise → ``failed`` + S8 alert + a
        :class:`RecordingPipelineFailureError` re-raise so the router
        emits 500. The job state is durable BEFORE the alert is
        emitted; a flaky alert sink cannot leave the job in ``arming``.
        """
        job = self._require_job(job_id)
        if job.state != "scheduled":
            raise RecordingJobStateError(
                f"Cannot arm job {job_id!r}: state is {job.state!r}, expected 'scheduled'."
            )
        pipeline = self._require_pipeline("arm")

        # E-3 fix: the overlap probe + the state transition into ``arming``
        # used to live in two different sessions; a concurrent
        # ``record_now`` / ``record_now`` could pass the probe in BOTH
        # callers before either wrote the transition, breaking DC-5
        # under concurrency. Now ``transition_to_arming_with_overlap_guard``
        # does both in one transaction; the loser raises a typed error
        # that we translate into the same ``skipped`` outcome as the
        # original soft-check path.
        try:
            self._store.transition_to_arming_with_overlap_guard(job_id)
        except RecordingJobOverlapError:
            # Look up the conflicting job for the failure_reason; if the
            # find-overlapping-jobs returns no rows (race between the
            # rollback and the lookup), fall back to a generic reason.
            overlaps = [
                other
                for other in self._store.find_overlapping_jobs(
                    job.station_id,
                    job.source_snapshot,
                    job.planned_start,
                    job.planned_end,
                    exclude_job_id=job.job_id,
                )
                if other.state in JOB_STATE_ACTIVE
            ]
            conflicting = overlaps[0].job_id if overlaps else "(unknown)"
            reason = (
                f"Skipped: an overlapping recording is already armed/active on "
                f"the same source (conflicting job_id={conflicting!r})."
            )
            updated = self._store.set_job_state(
                job_id,
                "skipped",
                ended_at=self._clock(),
                failure_reason=reason,
            )
            self._emit_alert(
                severity="warning",
                source="recording.overlap",
                message="Recording skipped: source overlap.",
                context={
                    "job_id": job_id,
                    "schedule_id": job.schedule_id,
                    "station_id": job.station_id,
                    "conflicting_job_id": conflicting,
                },
            )
            return updated

        try:
            pipeline.arm(
                job_id=job_id,
                source=job.source_snapshot,
                encoder_profile=job.encoder_profile,
                loudness_regime=job.loudness_regime,
            )
        except Exception as exc:
            return self._fail_job(
                job_id,
                phase="arm",
                exc=exc,
                schedule_id=job.schedule_id,
                station_id=job.station_id,
            )
        return self._require_job(job_id)

    def start_job(self, job_id: str) -> RecordingJob:
        """Transition ``arming → recording`` and call ``pipeline.start``."""
        job = self._require_job(job_id)
        if job.state != "arming":
            raise RecordingJobStateError(
                f"Cannot start job {job_id!r}: state is {job.state!r}, expected 'arming'."
            )
        pipeline = self._require_pipeline("start")
        now = self._clock()
        try:
            pipeline.start(job_id)
        except Exception as exc:
            return self._fail_job(
                job_id,
                phase="start",
                exc=exc,
                schedule_id=job.schedule_id,
                station_id=job.station_id,
            )
        return self._store.set_job_state(job_id, "recording", started_at=now)

    def finalize_job(self, job_id: str) -> RecordingJob:
        """Transition ``recording → finalizing → done`` (DC-4, DC-6).

        DC-4: a successful finalize produces a normal :class:`Asset`
        via the injected asset-finalizer (same shape as a watch-folder
        ingest); the asset id lands on the job.

        DC-6: ``loudness_regime`` and the custom-field stamps pass
        verbatim to the finalizer so a publish-time pipeline that
        validates loudness sees the regime the operator chose at
        schedule time.
        """
        job = self._require_job(job_id)
        if job.state != "recording":
            raise RecordingJobStateError(
                f"Cannot finalize job {job_id!r}: state is {job.state!r}, expected 'recording'."
            )
        pipeline = self._require_pipeline("finalize")
        finalizer = self._require_finalizer("finalize")
        # Move into finalizing first so a finalize-time crash can
        # transition forward (``finalizing → failed``) per the store's
        # allowed-transitions table.
        self._store.set_job_state(job_id, "finalizing")
        try:
            result = pipeline.finalize(job_id)
            asset_id = finalizer.finalize_to_asset(
                station_id=job.station_id,
                capture_path=result.capture_path,
                target_series=job.target_series,
                custom_field_values=job.custom_field_values,
                sha256=result.sha256,
            )
        except Exception as exc:
            return self._fail_job(
                job_id,
                phase="finalize",
                exc=exc,
                schedule_id=job.schedule_id,
                station_id=job.station_id,
            )
        return self._store.set_job_state(
            job_id,
            "done",
            ended_at=self._clock(),
            asset_id=asset_id,
            bytes_written=result.bytes_written,
        )

    def stop_job(self, job_id: str) -> RecordingJob:
        """Operator-initiated stop on a running job.

        Calls ``pipeline.stop`` (which returns the partial capture
        result), then routes the partial bytes through the finalizer
        so the operator gets a usable asset rather than an orphan file.
        Active states only (``arming`` / ``recording`` / ``finalizing``);
        a stop against a terminal job is a 409 (state error).

        The transition path mirrors the normal finalize: ``recording →
        finalizing → done`` (or → ``failed`` on torn capture / pipeline
        raise). An ``arming``-state stop walks through ``recording``
        first so the store's allowed-transitions table accepts the
        forward path; an operator stop during arm is rare but legal
        (e.g. the operator hits Stop while waiting on a slow SDI
        receiver).
        """
        job = self._require_job(job_id)
        if job.state not in JOB_STATE_ACTIVE:
            raise RecordingJobStateError(
                f"Cannot stop job {job_id!r}: state is {job.state!r}; "
                f"only {sorted(JOB_STATE_ACTIVE)!r} are stoppable."
            )
        pipeline = self._require_pipeline("stop")
        finalizer = self._require_finalizer("stop")

        # E-4 fix: pre-fix an ``arming``-state stop bridged
        # ``arming → recording → finalizing`` and then called
        # ``pipeline.stop`` — but ``pipeline.start`` had never been
        # called, so a real GStreamer pipeline (which doesn't yet have a
        # live mux to stop) would have raised. We now branch on the
        # current state and call the right pipeline method:
        #
        # * ``arming``    → no live capture; if the pipeline exposes a
        #                   ``stop_arming`` hook we call it, otherwise we
        #                   short-circuit straight to ``failed`` with a
        #                   "Stopped before recording started" reason.
        # * ``recording`` → the standard pipeline.stop() path (current
        #                   behavior).
        # * ``finalizing``→ finalize is already in flight; call
        #                   pipeline.stop() to short-circuit and finalize
        #                   whatever the pipeline produces. The
        #                   transition forward to ``done`` / ``failed``
        #                   is the same as ``recording``.
        if job.state == "arming":
            stop_arming = getattr(pipeline, "stop_arming", None)
            if callable(stop_arming):
                try:
                    stop_arming(job_id)
                except Exception as exc:
                    return self._fail_job(
                        job_id,
                        phase="stop",
                        exc=exc,
                        schedule_id=job.schedule_id,
                        station_id=job.station_id,
                    )
            # ``arming`` has no live capture — we bridge to ``failed``
            # via the legal transition table (``arming → failed``) with
            # a clear reason rather than calling ``pipeline.stop`` on a
            # pipeline that never started.
            return self._store.set_job_state(
                job_id,
                "failed",
                ended_at=self._clock(),
                bytes_written=0,
                failure_reason=(
                    "Stopped before recording started; capture pipeline "
                    "never reached the 'recording' phase."
                ),
            )

        # ``recording`` or ``finalizing`` — there IS a live (or in-flight)
        # capture to stop. Walk to ``finalizing`` from wherever we are
        # so the store's allowed-transitions table accepts the forward
        # path.
        if job.state == "recording":
            self._store.set_job_state(job_id, "finalizing")
        try:
            result = pipeline.stop(job_id)
            asset_id = finalizer.finalize_to_asset(
                station_id=job.station_id,
                capture_path=result.capture_path,
                target_series=job.target_series,
                custom_field_values=job.custom_field_values,
                sha256=result.sha256,
            )
        except Exception as exc:
            return self._record_job_failure(
                job_id,
                phase="stop",
                exc=exc,
                schedule_id=job.schedule_id,
                station_id=job.station_id,
            )
        # A stop with zero bytes is a torn capture — surface as failed
        # so the operator UI doesn't show a 0-byte "done" asset.
        if result.bytes_written <= 0:
            return self._store.set_job_state(
                job_id,
                "failed",
                ended_at=self._clock(),
                bytes_written=0,
                failure_reason="Operator stop landed a zero-byte capture; nothing to finalize.",
            )
        return self._store.set_job_state(
            job_id,
            "done",
            ended_at=self._clock(),
            asset_id=asset_id,
            bytes_written=result.bytes_written,
        )

    # ------------------------------------------------------------------
    # Ad-hoc / startup
    # ------------------------------------------------------------------

    def record_now(self, schedule_id: str) -> RecordingJob:
        """Create + arm + start an unplanned job NOW for ``schedule_id``.

        The operator clicks "Record now" on a schedule; we mint a job
        with ``planned_start=now`` + ``planned_end=now + duration``,
        then walk it through ``arm → start`` so the operator gets the
        same state-machine guarantees as a scheduled capture.
        Finalization is driven by the scheduler's ``tick`` (or an
        operator stop).
        """
        schedule = self._store.get_schedule(schedule_id)
        if schedule is None:
            raise RecordingScheduleNotFoundError(f"Recording schedule {schedule_id!r} not found.")
        self._require_pipeline("record_now")
        now = self._clock()
        # Two ``record_now`` clicks within the same second on the same
        # schedule would collide on the deterministic id; mix in a
        # short uuid suffix so the operator UI's double-click is safe.
        unique_suffix = uuid.uuid4().hex[:8]
        job = RecordingJob(
            job_id=_job_id_for(schedule.schedule_id, now, prefix=f"now-{unique_suffix}"),
            station_id=schedule.station_id,
            schedule_id=schedule.schedule_id,
            planned_start=now,
            planned_end=now + timedelta(seconds=schedule.duration_seconds),
            source_snapshot=schedule.source,
            encoder_profile=schedule.encoder_profile,
            loudness_regime=schedule.loudness_regime,
            target_series=schedule.target_series,
            custom_field_values=dict(schedule.custom_field_values),
        )
        stored = self._store.create_job(job)
        armed = self.arm_job(stored.job_id)
        if armed.state != "arming":
            return armed  # skipped / failed — short-circuit
        return self.start_job(stored.job_id)

    def record_now_from_source(
        self,
        *,
        station_id: str,
        source: RecordingSource,
        duration_seconds: int,
        encoder_profile: str,
        loudness_regime: str = "inherit",
        target_series: str | None = None,
        custom_field_values: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> RecordingJob:
        """Same as :meth:`record_now` but without a saved schedule —
        the operator dials in a source + profile ad-hoc."""
        self._require_pipeline("record_now_from_source")
        now = self._clock()
        unique_suffix = uuid.uuid4().hex[:8]
        resolved_id = job_id or _job_id_for(
            f"adhoc-{station_id}", now, prefix=f"adhoc-{unique_suffix}"
        )
        job = RecordingJob(
            job_id=resolved_id,
            station_id=station_id,
            schedule_id=None,
            planned_start=now,
            planned_end=now + timedelta(seconds=duration_seconds),
            source_snapshot=source,
            encoder_profile=encoder_profile,
            loudness_regime=loudness_regime,
            target_series=target_series,
            custom_field_values=custom_field_values or {},
        )
        stored = self._store.create_job(job)
        armed = self.arm_job(stored.job_id)
        if armed.state != "arming":
            return armed
        return self.start_job(stored.job_id)

    def cancel_scheduled_jobs_for_schedule(
        self,
        schedule_id: str,
        *,
        reason: str = "schedule disabled",
    ) -> int:
        """Cancel every ``state='scheduled'`` job for ``schedule_id``.

        E-11 fix: disabling a schedule mid-window used to be a no-op for
        already-materialized jobs — they would fire anyway against the
        operator's expectation that disabling stops future captures. The
        router's PATCH endpoint now calls this whenever ``enabled`` is
        flipped from ``True`` to ``False``; returns the number of jobs
        transitioned to ``skipped``.
        """
        cancelled = 0
        # Use the station's pending-scheduled list, then filter by
        # schedule_id. We don't have a direct "list_by_schedule" path —
        # the store's existing ``list_jobs`` accepts a schedule filter.
        # We cap at the configured per-tick limit; if a schedule has
        # more than that many pending jobs the next disable + tick will
        # finish the job.
        pending: list[RecordingJob] = []
        # We need station_id; we don't carry one — but list_jobs requires
        # one. Use the schedule lookup.
        sched = self._store.get_schedule(schedule_id)
        if sched is None:
            return 0
        pending = self._store.list_jobs(
            sched.station_id,
            state="scheduled",
            schedule_id=schedule_id,
            limit=self._max_jobs_per_tick,
        )
        for job in pending:
            try:
                self._store.set_job_state(
                    job.job_id,
                    "skipped",
                    ended_at=self._clock(),
                    failure_reason=reason,
                )
                cancelled += 1
            except RecordingJobStateError:
                # Race: the job advanced past 'scheduled' before we got
                # to it. Leave it alone — the operator's "disable cancels
                # FUTURE captures" intent is satisfied by the ones we did
                # cancel.
                pass
        return cancelled

    def reconcile_orphans(self) -> int:
        """Startup hook: fail any job stuck in an active state past its
        planned end. Wraps :meth:`RecordingStore.reconcile_orphaned_active_jobs`."""
        return self._store.reconcile_orphaned_active_jobs(now=self._clock())

    def drain_in_flight(
        self,
        station_id: str,
        *,
        deadline_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> RecordingDrainResult:
        """Shutdown hook: gracefully stop every in-flight recording job to a
        finalized asset, bounded by ``deadline_seconds`` (best-effort, never
        hangs shutdown).

        This is the recording-side peer of the egress daemon's
        ``stop_all_channels(deadline_seconds=...)`` drain. Without it, a
        shutdown mid-recording lets process exit tear the capture down: the
        ffmpeg child is killed (by the supervisor Job Object, or orphaned off
        the supervisor), the partial ``.ts`` segment is never concatenated or
        finalized, and the job sits ``recording`` until the next boot's
        ``reconcile_orphans`` marks it ``failed`` — the capture up to the stop
        moment is lost even though it is valid, flushed MPEG-TS on disk.

        Each job is stopped through :meth:`stop_job`, which drives
        ``pipeline.stop`` under the capture pipeline's per-instance
        ``_job_lock``. That lock is the seam that makes this safe to run
        alongside the scheduler poll thread's ``check_dropout``/``finalize``:
        the two serialize on it, and whichever reaches the job first pops it
        out of the pipeline's ``_active`` map — the loser then finds the job
        already gone and no-ops rather than double-finalizing. It cannot
        deadlock the poll thread: the lock is only ever held across bounded
        in-memory state transitions (the unbounded ffmpeg concat/merge runs
        outside it), and this method holds no lock of its own across the call.

        Bounded + fail-open: the deadline is checked before each job (a
        synchronous ``stop_job`` is not interruptible mid-flight, so the budget
        caps how MANY jobs we drain, not a single hung stop — ``pipeline.stop``
        carries its own 10s terminate grace and the concat runner its own
        timeout). Any per-job failure is caught and counted, never propagated,
        so one bad job never aborts the drain or blocks shutdown. Jobs not
        reached fall through to ``reconcile_orphans`` on the next boot.
        """
        deadline = monotonic() + max(0.0, deadline_seconds)
        considered = 0
        finalized = 0
        failed = 0
        not_drained = 0
        # Snapshot the in-flight set once. recording first (the captures worth
        # saving), then finalizing (a window-end finalize the poll thread may
        # have started), then arming (no live capture — stop_job resolves these
        # to a clean 'failed' so they don't linger as orphans).
        for state in ("recording", "finalizing", "arming"):
            for job in self._store.list_jobs(
                station_id, state=state, limit=self._max_jobs_per_tick
            ):
                considered += 1
                if monotonic() >= deadline:
                    not_drained += 1
                    continue
                try:
                    result = self.stop_job(job.job_id)
                except Exception:
                    # A concurrent poll-thread finalize may have already driven
                    # this job terminal (the _job_lock guarantees no corruption,
                    # only that the loser's state transition can raise). Best
                    # effort: log and count, never abort the drain.
                    logger.exception(
                        "recording.drain_in_flight stop_job raised for job_id=%s", job.job_id
                    )
                    failed += 1
                    continue
                if result.state == "done":
                    finalized += 1
                else:
                    failed += 1
        if considered:
            logger.info(
                "recording.drain_in_flight station_id=%s considered=%d finalized=%d "
                "failed=%d not_drained=%d",
                station_id,
                considered,
                finalized,
                failed,
                not_drained,
            )
        return RecordingDrainResult(
            considered=considered,
            finalized=finalized,
            failed=failed,
            not_drained=not_drained,
        )

    def poll_active_recordings(self, station_id: str) -> int:
        """Item 6: poll every ``recording``-state job for a source dropout.

        A no-op when the wired pipeline doesn't implement
        ``check_dropout`` (the optional Protocol member — mirrors the
        existing ``stop_arming`` optionality). Called once per scheduler
        tick, same cadence as ``finalize_job``'s window-end check, so a
        dropout is observed within one poll interval rather than only
        surfacing when the recording ends.

        Returns the number of jobs on which a dropout was newly recorded
        this poll. A dropout that reconnects keeps the job ``recording``;
        the record + alert happen regardless of reconnect outcome so the
        event is durable even if the reconnect itself later fails (that
        failure surfaces separately, through the normal pipeline-exception
        path on the next arm/finalize call).
        """
        if self._pipeline is None:
            return 0
        checker = getattr(self._pipeline, "check_dropout", None)
        if not callable(checker):
            return 0
        recorded = 0
        for job in self._store.list_jobs(
            station_id, state="recording", limit=self._max_jobs_per_tick
        ):
            try:
                result = checker(job.job_id)
            except Exception:
                logger.exception(
                    "recording.poll_active_recordings dropout check raised for job_id=%s",
                    job.job_id,
                )
                continue
            if not result.dropout_detected:
                continue
            observed_at = self._clock()
            self._store.record_dropout(job.job_id, observed_at=observed_at)
            recorded += 1
            reconnect_note = "reconnected" if result.reconnected else "reconnect failed"
            logger.warning(
                "recording.dropout job_id=%s station_id=%s %s: %s",
                job.job_id,
                job.station_id,
                reconnect_note,
                result.detail,
            )
            self._emit_alert(
                severity="warning" if result.reconnected else "critical",
                source="recording.dropout",
                message=(
                    f"Recording source dropout detected and {reconnect_note}."
                    if result.reconnected
                    else "Recording source dropout detected; reconnect failed."
                ),
                context={
                    "job_id": job.job_id,
                    "schedule_id": job.schedule_id,
                    "station_id": job.station_id,
                    "reconnected": result.reconnected,
                    "detail": result.detail,
                    "dropout_count": job.dropout_count + 1,
                },
            )
        return recorded

    def tick(
        self,
        station_id: str,
        *,
        horizon: timedelta = DEFAULT_TICK_HORIZON,
    ) -> TickCounters:
        """One scheduler tick: expand + arm + start any due jobs.

        The scheduler invokes this on the S19 cadence; it's idempotent
        on the expand side (already-materialized jobs are skipped) and
        bounded on the arm side (only jobs whose ``planned_start`` is
        within ``arm_lead`` of ``now`` are armed).

        Returns a typed :class:`TickCounters` (E-14 fix) so the operator
        UI / metrics endpoint sees a stable schema rather than a raw
        ``dict``.
        """
        expanded = len(self.expand_jobs_for_horizon(station_id, horizon))
        armed_count = 0
        started_count = 0
        finalized_count = 0
        skipped_count = 0
        failed_count = 0

        now = self._clock()
        arm_cutoff = now + self._arm_lead
        # We re-list AFTER expansion so newly-created jobs are visible.
        # E-5 fix: cap is configurable + warned-on, no more magic number.
        pending = self._store.list_jobs(
            station_id, state="scheduled", limit=self._max_jobs_per_tick
        )
        for pending_job in pending:
            if pending_job.planned_start > arm_cutoff:
                continue
            armed = self.arm_job(pending_job.job_id)
            if armed.state == "skipped":
                skipped_count += 1
                continue
            if armed.state == "failed":
                failed_count += 1
                continue
            armed_count += 1
            # E-8 fix: read the post-arm model's planned_start instead of
            # the stale pre-arm ``pending_job`` row. The two are equal
            # today (``planned_start`` is immutable) but the rename
            # forecloses the stale-shadow bug class on future refactors.
            if armed.planned_start <= now:
                started = self.start_job(pending_job.job_id)
                if started.state == "recording":
                    started_count += 1
                elif started.state == "failed":
                    failed_count += 1
        # Item 6: poll every still-recording job for a source dropout BEFORE
        # the window-end finalize sweep below, so a dropout is observed and
        # reconnected within this tick rather than only surfacing once the
        # window closes.
        dropouts_detected = self.poll_active_recordings(station_id)
        due_recordings = self._store.list_jobs(
            station_id, state="recording", limit=self._max_jobs_per_tick
        )
        for recording_job in due_recordings:
            if recording_job.planned_end > now:
                continue
            try:
                finalized = self.finalize_job(recording_job.job_id)
            except RecordingPipelineFailureError:
                failed_count += 1
                continue
            if finalized.state == "done":
                finalized_count += 1
            elif finalized.state == "failed":
                failed_count += 1
        return TickCounters(
            expanded=expanded,
            armed=armed_count,
            started=started_count,
            finalized=finalized_count,
            skipped=skipped_count,
            failed=failed_count,
            dropouts_detected=dropouts_detected,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_job(self, job_id: str) -> RecordingJob:
        job = self._store.get_job(job_id)
        if job is None:
            raise RecordingJobNotFoundError(f"Recording job {job_id!r} not found.")
        return job

    def _require_pipeline(self, op: str) -> CapturePipelineProtocol:
        if self._pipeline is None:
            raise RecordingPipelineUnwiredError(
                f"Cannot {op}: the capture pipeline is not wired into this service."
            )
        return self._pipeline

    def _require_finalizer(self, op: str) -> AssetFinalizerProtocol:
        if self._finalizer is None:
            raise RecordingPipelineUnwiredError(
                f"Cannot {op}: the asset finalizer is not wired into this service."
            )
        return self._finalizer

    def _emit_alert(
        self,
        *,
        severity: str,
        source: str,
        message: str,
        context: dict[str, Any],
    ) -> None:
        """Best-effort alert. A sink that itself raises is logged and
        swallowed — DC-3's "never a silent miss" applies to the JOB
        STATE, which is already durable by the time we get here."""
        if self._alert_sink is None:
            # E-9 fix: pre-fix every severity logged at INFO when there
            # was no sink, which silently lost critical fail alerts into
            # the noise floor on a station with default-INFO logging.
            # Map severity to the appropriate stdlib level so an operator
            # tailing journalctl still sees critical signals at ERROR.
            level = {
                "critical": logging.ERROR,
                "error": logging.ERROR,
                "warning": logging.WARNING,
                "info": logging.INFO,
            }.get(severity, logging.INFO)
            logger.log(
                level,
                "recording.alert (no sink) %s: %s %s",
                source,
                message,
                context,
            )
            return
        try:
            self._alert_sink.emit(
                severity=severity,
                source=source,
                message=message,
                context=context,
            )
        except Exception:
            logger.exception(
                "recording.alert sink raised for %s; job state already durable.", source
            )

    def _record_job_failure(
        self,
        job_id: str,
        *,
        phase: str,
        exc: BaseException,
        schedule_id: str | None,
        station_id: str,
    ) -> RecordingJob:
        """Transition to ``failed`` and emit an S8 alert without raising."""
        reason = _pipeline_failure_reason(phase)
        logger.exception(
            "recording.job.failed job_id=%s phase=%s station_id=%s",
            job_id,
            phase,
            station_id,
        )
        self._store.set_job_state(
            job_id,
            "failed",
            ended_at=self._clock(),
            failure_reason=reason,
        )
        self._emit_alert(
            severity="critical",
            source=f"recording.{phase}",
            message=f"Recording job failed during {phase}.",
            context={
                "job_id": job_id,
                "schedule_id": schedule_id,
                "station_id": station_id,
                "phase": phase,
                "exception_type": type(exc).__name__,
            },
        )
        failed = self._store.get_job(job_id)
        if failed is None:
            raise RecordingJobNotFoundError(f"Recording job {job_id!r} not found.")
        return failed

    def _fail_job(
        self,
        job_id: str,
        *,
        phase: str,
        exc: BaseException,
        schedule_id: str | None,
        station_id: str,
    ) -> RecordingJob:
        """Transition to ``failed`` + emit an S8 alert + re-raise as a
        typed service error.

        The exception's message is NOT echoed verbatim into the failure
        reason — capture pipeline messages can carry filesystem paths
        and stream URIs. We surface the phase in operator language; the
        exception type and full traceback live in the alert context and
        server log.
        """
        reason = _pipeline_failure_reason(phase)
        logger.exception(
            "recording.job.failed job_id=%s phase=%s station_id=%s",
            job_id,
            phase,
            station_id,
        )
        self._store.set_job_state(
            job_id,
            "failed",
            ended_at=self._clock(),
            failure_reason=reason,
        )
        self._emit_alert(
            severity="critical",
            source=f"recording.{phase}",
            message=f"Recording job failed during {phase}.",
            context={
                "job_id": job_id,
                "schedule_id": schedule_id,
                "station_id": station_id,
                "phase": phase,
                "exception_type": type(exc).__name__,
            },
        )
        raise RecordingPipelineFailureError(reason) from exc


# ---------------------------------------------------------------------------
# Recurrence materializer (module-level — pure function, easy to unit-test)
# ---------------------------------------------------------------------------


def _materialize_starts(
    recurrence: RecurrenceSpec,
    now: datetime,
    deadline: datetime,
) -> list[datetime]:
    """Return the start timestamps of ``recurrence`` that fall inside
    ``[now, deadline]``. UTC throughout.

    * ``one_shot`` produces at most one element (its ``start``), and
      only if it's in-window. Past one-shots are filtered out so a
      historical schedule doesn't re-materialize on every tick.
    * ``weekly`` walks day-by-day from ``now`` (UTC) to ``deadline``
      and yields the time-of-day (``time_hhmm`` parsed as UTC) on each
      matching weekday.
    """
    if recurrence.kind == "one_shot":
        start = recurrence.start
        if start is None:
            return []
        # Ensure tz-aware comparison.
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if now <= start <= deadline:
            return [start]
        return []

    # weekly
    weekdays = set(recurrence.weekdays)
    if not weekdays or not recurrence.time_hhmm:
        return []
    hour = int(recurrence.time_hhmm[:2])
    minute = int(recurrence.time_hhmm[3:])
    # Walk day-by-day from now's calendar date through deadline's; for
    # each matching weekday, the start is that day's hour/minute in UTC.
    starts: list[datetime] = []
    cursor = datetime(now.year, now.month, now.day, tzinfo=UTC)
    end_day = datetime(deadline.year, deadline.month, deadline.day, tzinfo=UTC)
    while cursor <= end_day:
        if cursor.weekday() in weekdays:
            candidate = cursor.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now <= candidate <= deadline:
                starts.append(candidate)
        cursor = cursor + timedelta(days=1)
    return starts


def _job_id_for(
    schedule_id: str,
    planned_start: datetime,
    *,
    prefix: str = "job",
) -> str:
    """Deterministic job id for a (schedule, planned_start) tuple.

    Same schedule + same start → same job id → the store's PK already
    enforces idempotency. The ``prefix`` differentiates scheduler-
    materialized (``job-...``) from operator-driven (``now-...`` /
    ``adhoc-...``) so the operator UI can colour them differently.

    The id is slug-shaped so :class:`~civiccast.recording.models.RecordingJob`
    accepts it (``Slug`` allows ``[a-z0-9_-]``).
    """
    # ISO 8601 second-precision, lowercased, with ``:`` + ``+`` swapped
    # out for slug-safe chars.
    safe_start = planned_start.astimezone(UTC).strftime("%Y%m%dt%H%M%Sz").lower()
    # E-1 fix: preserve schedule_id VERBATIM (lowercased only). Pre-fix
    # the validator did ``.replace("_", "-")`` which collapses ``sch_a``
    # and ``sch-a`` to the same job_id — a deterministic PK collision
    # between two perfectly valid Slug-shaped schedule_ids. The slug
    # pattern admits BOTH ``_`` and ``-``; the job_id has to be injective
    # over that input or the materializer's idempotency assumption
    # silently fails.
    safe_schedule = schedule_id.lower()
    return f"{prefix}-{safe_schedule}-{safe_start}"


__all__ = [
    "DEFAULT_ARM_LEAD",
    "DEFAULT_MAX_JOBS_PER_TICK",
    "DEFAULT_TICK_HORIZON",
    "AlertSinkProtocol",
    "AssetFinalizerProtocol",
    "CapturePipelineProtocol",
    "CaptureResult",
    "RecordingDrainResult",
    "RecordingJobNotFoundError",
    "RecordingPipelineFailureError",
    "RecordingPipelineUnwiredError",
    "RecordingScheduleNotFoundError",
    "RecordingService",
    "RecordingServiceError",
    "TickCounters",
]
