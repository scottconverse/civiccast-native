# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The offline caption job -- CivicCast One keystone K3.

Every piece of offline captioning already existed (runtime, review queue,
WebVTT renderer, HLS attach); nothing connected them for a published
recording. This module is that connection, built on the repo's established
background-job shape (durable queue row + ``run_once``/``run_forever``
worker under :class:`~civiccast.platform.worker_runtime.ThreadSupervisor`,
the shape the finalization and ActivityPub-retry workers set).

One job row per asset, two stages, because operator approval sits between
them (spec §4.1 -- no AI text reaches a public surface unreviewed):

``pending``
    Transcribe the recording's audio with the station's staged caption
    model and file every cue in the operator review queue. Publishes
    nothing. -> ``awaiting_review`` (or ``complete`` when the recording
    produced no speech at all).

``awaiting_review``
    Re-checked each poll. Once the operator has decided every queued cue,
    the approved/edited text is rendered and attached to the packaged VOD
    -- segmented WebVTT track in the manifest plus the flat
    ``captions.vtt`` records artifact. -> ``complete``.

``complete`` / ``failed``
    Terminal. ``failed`` means the attempt budget is spent; the reason is
    on the row, and the recording stays uncaptioned rather than shipping
    something unverified.

The stage-one work is the expensive half (a model pass over a whole
meeting), so it is retried with bounded exponential backoff exactly like
the other durable workers. Stage two is cheap and idempotent -- re-running
it just rewrites the same track from the same decisions.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from civiccast.captions.retention import CaptionEvidenceRetentionPolicy, CaptionRetentionResult
from civiccast.captions.review import CaptionReviewStore
from civiccast.captions.runtime import CaptionRuntime
from civiccast.captions.vod import (
    OFFLINE_CAPTION_CHUNK_SECONDS,
    attach_reviewed_captions,
    reviewed_caption_cues,
    transcribe_asset_captions,
)

_LOG = logging.getLogger(__name__)

OFFLINE_CAPTION_JOB_STATE_PENDING = "pending"
OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW = "awaiting_review"
OFFLINE_CAPTION_JOB_STATE_COMPLETE = "complete"
OFFLINE_CAPTION_JOB_STATE_FAILED = "failed"
OFFLINE_CAPTION_JOB_STATES = (
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
    OFFLINE_CAPTION_JOB_STATE_COMPLETE,
    OFFLINE_CAPTION_JOB_STATE_FAILED,
)
#: States the worker still has work to do in.
OFFLINE_CAPTION_JOB_ACTIVE_STATES = (
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
)

OfflineCaptionJobState = Literal["pending", "awaiting_review", "complete", "failed"]

OFFLINE_CAPTION_JOB_MODE_INLINE = "inline"
OFFLINE_CAPTION_JOB_MODE_OFF = "off"
_OFFLINE_CAPTION_JOB_MODES = (OFFLINE_CAPTION_JOB_MODE_INLINE, OFFLINE_CAPTION_JOB_MODE_OFF)

CaptionRuntimeFactory = Callable[[], CaptionRuntime]

__all__ = [
    "OFFLINE_CAPTION_JOB_ACTIVE_STATES",
    "OFFLINE_CAPTION_JOB_MODE_INLINE",
    "OFFLINE_CAPTION_JOB_MODE_OFF",
    "OFFLINE_CAPTION_JOB_STATES",
    "OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW",
    "OFFLINE_CAPTION_JOB_STATE_COMPLETE",
    "OFFLINE_CAPTION_JOB_STATE_FAILED",
    "OFFLINE_CAPTION_JOB_STATE_PENDING",
    "InMemoryOfflineCaptionJobStore",
    "OfflineCaptionJobConflictError",
    "OfflineCaptionJobRecord",
    "OfflineCaptionJobSettings",
    "OfflineCaptionJobState",
    "OfflineCaptionJobStore",
    "OfflineCaptionJobWorker",
    "enqueue_offline_caption_job",
    "new_offline_caption_job_id",
]


class OfflineCaptionJobConflictError(Exception):
    """Raised when a concurrent enqueue lost the race for an asset's active job.

    Two concurrent ``enqueue_offline_caption_job`` calls for the same asset
    (a publish approval racing a retry, for instance) can both pass the
    ``active_for_asset`` pre-check before either has inserted. The DB-level
    partial-unique index (``ix_offline_caption_jobs_one_active_per_asset``
    in ``0075_offline_caption_jobs``) is the real guard; a store raises this
    from ``enqueue`` when it loses that race, so the caller can recover the
    winning job instead of surfacing a raw integrity error.
    """

    def __init__(self, asset_id: str) -> None:
        self.asset_id = asset_id
        super().__init__(f"Offline caption job already active for asset {asset_id!r}")


def new_offline_caption_job_id() -> str:
    """Return a fresh opaque job id (same shape as the other queue ids)."""

    return "ocj_" + secrets.token_urlsafe(16).replace("-", "").replace("_", "")


class OfflineCaptionJobRecord(BaseModel):
    """One asset's offline captioning job."""

    model_config = ConfigDict(extra="forbid")

    job_id: Annotated[str, Field(min_length=1, max_length=120)]
    asset_id: Annotated[str, Field(min_length=1, max_length=160)]
    #: The recording ffmpeg reads caption audio from.
    source_path: Annotated[str, Field(min_length=1, max_length=1000)]
    #: The packaged HLS directory the reviewed track is attached to. Whoever
    #: enqueues the job resolves this (today, always
    #: civiccast.publish.router._queue_offline_captions via
    #: resolve_vod_package_dir, the UPLOAD-only convention -- see the
    #: KNOWN FOLLOW-UP comment there and "Known follow-ups" in
    #: docs/ops/background-workers.md for the LIVE-finalized-recording gap
    #: this leaves, out of CivicCast One v1 scope).
    package_dir: Annotated[str, Field(min_length=1, max_length=1000)]
    state: OfflineCaptionJobState
    attempts: int = 0
    next_attempt_at: datetime | None = None
    #: Cues the model produced (stage one).
    cue_count: int = 0
    #: Cues an operator approved/edited and that were published (stage two).
    published_cue_count: int = 0
    last_error: str = ""
    created_at: datetime
    updated_at: datetime


class OfflineCaptionJobStore(Protocol):
    """Storage contract for the offline caption job queue."""

    def enqueue(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        """Persist a new job row.

        Raises :class:`OfflineCaptionJobConflictError` when ``record`` is in
        an active state and another active job already exists for its
        asset -- the DB-level partial-unique index losing a concurrent race.
        """

    def save(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        """Persist an updated job row."""

    def get(self, job_id: str) -> OfflineCaptionJobRecord | None:
        """Return one job row when present."""

    def active_for_asset(self, asset_id: str) -> OfflineCaptionJobRecord | None:
        """Return the asset's non-terminal job, when one exists."""

    def due(
        self,
        *,
        now: datetime,
        states: Sequence[str] = OFFLINE_CAPTION_JOB_ACTIVE_STATES,
    ) -> list[OfflineCaptionJobRecord]:
        """Return job rows in ``states`` whose next attempt is due."""

    def list(
        self,
        *,
        asset_id: str | None = None,
        state: str | None = None,
    ) -> list[OfflineCaptionJobRecord]:
        """Return job rows for operator visibility, optionally filtered.

        Unlike :meth:`due`, this is not restricted to active states or to
        rows whose backoff clock has elapsed -- it is the read path for the
        staff "what's stuck and why" view (finding 4), so a ``failed`` or
        ``complete`` row must come back too.
        """


class InMemoryOfflineCaptionJobStore:
    """In-memory job queue for tests and non-DB development."""

    def __init__(self) -> None:
        self._jobs: dict[str, OfflineCaptionJobRecord] = {}

    def enqueue(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        if record.state in OFFLINE_CAPTION_JOB_ACTIVE_STATES:
            conflict = next(
                (
                    row
                    for row in self._jobs.values()
                    if row.asset_id == record.asset_id
                    and row.state in OFFLINE_CAPTION_JOB_ACTIVE_STATES
                ),
                None,
            )
            if conflict is not None:
                # Mirrors the durable store's partial-unique index: at most
                # one active job per asset, enforced here too so the
                # in-memory store honors the same contract in tests.
                raise OfflineCaptionJobConflictError(record.asset_id)
        self._jobs[record.job_id] = record
        return record.model_copy(deep=True)

    def save(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        self._jobs[record.job_id] = record
        return record.model_copy(deep=True)

    def get(self, job_id: str) -> OfflineCaptionJobRecord | None:
        record = self._jobs.get(job_id)
        return record.model_copy(deep=True) if record is not None else None

    def active_for_asset(self, asset_id: str) -> OfflineCaptionJobRecord | None:
        for record in sorted(self._jobs.values(), key=lambda row: row.created_at):
            if record.asset_id == asset_id and record.state in OFFLINE_CAPTION_JOB_ACTIVE_STATES:
                return record.model_copy(deep=True)
        return None

    def due(
        self,
        *,
        now: datetime,
        states: Sequence[str] = OFFLINE_CAPTION_JOB_ACTIVE_STATES,
    ) -> list[OfflineCaptionJobRecord]:
        rows = [
            record
            for record in self._jobs.values()
            if record.state in states
            and (record.next_attempt_at is None or record.next_attempt_at <= now)
        ]
        return [
            record.model_copy(deep=True)
            for record in sorted(rows, key=lambda row: (row.created_at, row.job_id))
        ]

    def list(
        self,
        *,
        asset_id: str | None = None,
        state: str | None = None,
    ) -> list[OfflineCaptionJobRecord]:
        rows = list(self._jobs.values())
        if asset_id is not None:
            rows = [row for row in rows if row.asset_id == asset_id]
        if state is not None:
            rows = [row for row in rows if row.state == state]
        return [
            row.model_copy(deep=True)
            for row in sorted(rows, key=lambda row: (row.created_at, row.job_id))
        ]


@dataclass(frozen=True)
class OfflineCaptionJobSettings:
    """Deployment configuration for the offline caption job worker."""

    mode: str = OFFLINE_CAPTION_JOB_MODE_INLINE
    poll_seconds: float = 60.0
    backoff_seconds: float = 300.0
    max_attempts: int = 4
    chunk_seconds: float = OFFLINE_CAPTION_CHUNK_SECONDS

    @classmethod
    def from_env(cls) -> OfflineCaptionJobSettings:
        mode = (
            os.environ.get("CIVICCAST_OFFLINE_CAPTION_JOB", OFFLINE_CAPTION_JOB_MODE_INLINE)
            .strip()
            .lower()
        )
        if mode not in _OFFLINE_CAPTION_JOB_MODES:
            raise ValueError(
                f"CIVICCAST_OFFLINE_CAPTION_JOB must be one of "
                f"{', '.join(_OFFLINE_CAPTION_JOB_MODES)}; got {mode!r}."
            )
        defaults = cls()
        return cls(
            mode=mode,
            poll_seconds=_env_positive_float(
                "CIVICCAST_OFFLINE_CAPTION_POLL_SECONDS", defaults.poll_seconds
            ),
            backoff_seconds=_env_positive_float(
                "CIVICCAST_OFFLINE_CAPTION_BACKOFF_SECONDS", defaults.backoff_seconds
            ),
            max_attempts=_env_positive_int(
                "CIVICCAST_OFFLINE_CAPTION_MAX_ATTEMPTS", defaults.max_attempts
            ),
            chunk_seconds=_env_positive_float(
                "CIVICCAST_OFFLINE_CAPTION_CHUNK_SECONDS", defaults.chunk_seconds
            ),
        )


def _env_positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number; got {raw!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero; got {raw!r}.")
    return value


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer; got {raw!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero; got {raw!r}.")
    return value


def enqueue_offline_caption_job(
    store: OfflineCaptionJobStore,
    *,
    asset_id: str,
    source_path: Path,
    package_dir: Path,
    now: datetime | None = None,
) -> OfflineCaptionJobRecord:
    """Queue offline captioning for a published recording.

    Idempotent per asset: publishing (or re-publishing) an asset that is
    already queued or already awaiting review returns the existing job
    instead of re-transcribing the same meeting and re-queueing cues an
    operator may already be working through.

    The idempotency check is check-then-insert (a plain SELECT, no
    row lock), so two concurrent calls for the same asset -- a publish
    approval racing a retry, or two operators approving at once -- can both
    pass it before either has inserted. The DB-level partial-unique index
    (``ix_offline_caption_jobs_one_active_per_asset``) is the real guard:
    when this loses that race, the losing insert raises
    :class:`OfflineCaptionJobConflictError`, and that's caught here to
    return the winner instead of a raw DB error or a duplicate job.
    """

    existing = store.active_for_asset(asset_id)
    if existing is not None:
        return existing
    resolved_now = now or datetime.now(UTC)
    record = OfflineCaptionJobRecord(
        job_id=new_offline_caption_job_id(),
        asset_id=asset_id,
        source_path=str(source_path),
        package_dir=str(package_dir),
        state=OFFLINE_CAPTION_JOB_STATE_PENDING,
        attempts=0,
        next_attempt_at=resolved_now,
        created_at=resolved_now,
        updated_at=resolved_now,
    )
    try:
        enqueued = store.enqueue(record)
    except OfflineCaptionJobConflictError:
        # Lost the DB-level race against a concurrent enqueue for this asset
        # (the check above raced past another caller's insert). Re-fetch
        # and return the winner instead of queueing a second full
        # transcription pass -- or a raw integrity error -- for one asset.
        winner = store.active_for_asset(asset_id)
        if winner is None:
            # The winner must have already finished (or itself failed)
            # between the conflict and this re-fetch; nothing active is
            # left to return, so surface the conflict as-is.
            raise
        _LOG.info(
            "Offline caption enqueue for asset %s lost a concurrent race; reusing job %s.",
            asset_id,
            winner.job_id,
        )
        return winner
    _LOG.info("Queued offline captioning for published asset %s.", asset_id)
    return enqueued


class OfflineCaptionJobWorker:
    """Drive queued assets from published-but-uncaptioned to captioned.

    ``run_once`` is the testable unit; ``run_forever`` is the supervised
    loop that survives and logs scan exceptions -- the same split every
    other CivicCast background worker uses.

    The caption runtime is built lazily, through ``runtime_factory``, so a
    station with the worker enabled but nothing queued never loads a
    multi-gigabyte model into memory. The factory is the app's existing
    :func:`civiccast.ai_models.runtime.build_caption_runtime` seam, which
    resolves the operator-selected tier and inherits the hardware-adaptive
    device/compute-type the native station runtime published into the
    environment -- this worker never decides ``cpu`` versus ``cuda`` itself.

    Every tick also runs the retained-audio-evidence retention sweep
    (audit finding, MAJOR). ``CaptionEvidenceRetentionPolicy``
    (civiccast/captions/retention.py) is the owner-approved 90-day/
    free-space lifecycle for review-evidence WAVs, but its only caller used
    to be the live channel readiness tick in
    :meth:`civiccast.captions.tap_worker.CaptionTapWorker.run_once`. A
    station doing offline/VOD captioning with no airing live channel never
    ran that tick, so its evidence WAVs (written under each asset's package
    directory -- see ``_offline_audio_evidence_factory`` in
    :mod:`civiccast.captions.vod`) grew unbounded. ``run_once`` here now
    triggers the same policy class -- ``CaptionEvidenceRetentionPolicy``,
    same ``enforce_discovered`` call shape as ``CaptionTapWorker`` uses,
    just with ``tap_root`` absent, since this path has no live tap
    directory to also sweep. The *storage root* is not shared with
    ``CaptionTapWorker`` (audit finding, P1): that worker measures free
    space and the storage cap against the live egress work directory
    (``default_egress_work_dir()``), because that is where its tap evidence
    lives. This worker's evidence lives under the VOD package tree instead
    (``<package_dir>/captions/evidence/*.wav``), which can be a different
    filesystem entirely, so ``_retention_policy_instance`` builds its
    default policy against the VOD package root
    (:func:`civiccast.schedule.paths.resolve_vod_package_root`) instead --
    see that method for the resolution. Two more consequences of routing
    through the *same* policy class rather than a forked one: (1) the
    result is no longer discarded (audit finding, P1) -- ``run_once`` reads
    ``CaptionRetentionResult.ready`` and skips processing every due job
    this tick when the sweep refuses storage, exactly like
    ``CaptionTapWorker.run_once`` skips its channel scan; and (2) a sweep
    *exception* (as opposed to a clean not-ready result) still never blocks
    job processing -- see ``_sweep_retention``. Unlike ``CaptionTapWorker``
    (whose ``caption_work_dir`` is a required constructor argument, so its
    default policy is already hermetic per caller), this worker is built
    unconditionally in app.py regardless of
    ``OfflineCaptionJobSettings.mode``; the default policy is therefore
    built lazily on first use (see ``_retention_policy_instance``) rather
    than in ``__init__``, so constructing the worker itself never touches
    the filesystem.
    """

    def __init__(
        self,
        store: OfflineCaptionJobStore,
        review_store: CaptionReviewStore,
        *,
        runtime_factory: CaptionRuntimeFactory,
        settings: OfflineCaptionJobSettings,
        retention_policy: CaptionEvidenceRetentionPolicy | None = None,
    ) -> None:
        self._store = store
        self._review_store = review_store
        self._runtime_factory = runtime_factory
        self._settings = settings
        self._runtime: CaptionRuntime | None = None
        # Built lazily, same reason as ``_runtime_instance`` below: this
        # worker is constructed unconditionally in app.py regardless of
        # ``OfflineCaptionJobSettings.mode``, so touching the real
        # filesystem (``mkdir`` + ``shutil.disk_usage`` inside
        # ``CaptionEvidenceRetentionPolicy.from_system``) here in
        # ``__init__`` would run on every app startup -- including every
        # test that builds the app -- rather than only when a tick
        # actually runs.
        self._retention_policy = retention_policy

    def run_forever(
        self,
        *,
        poll_seconds: float = 60.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Run the caption-job loop until ``stop_event`` is set."""

        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                _LOG.exception("Offline caption scan failed; retrying on the next poll interval.")
            if stop_event is not None:
                stop_event.wait(poll_seconds)
            else:  # pragma: no cover - only reachable outside a supervisor
                time.sleep(poll_seconds)

    def run_once(self, *, now: datetime | None = None) -> list[OfflineCaptionJobRecord]:
        """Advance every due job once; return the rows that were touched.

        The retention sweep (see ``_sweep_retention``) always runs first.
        When it returns a clean *not-ready* result -- the free-space
        reserve would be breached, or retained evidence is over the
        storage cap, even after pruning everything eligible -- no due job
        is processed this tick, mirroring
        :meth:`civiccast.captions.tap_worker.CaptionTapWorker.run_once`'s
        own predicate (``if not retention.ready: ...`` before any channel
        work) exactly: this worker must not keep writing new evidence WAVs
        (stage one, ``_transcribe``) or new package artifacts (stage two,
        ``_publish_if_reviewed``) onto a volume the policy just refused
        (audit finding, P1 -- the result used to be discarded and every due
        job ran regardless). A sweep *exception* is different from a clean
        not-ready result and is never treated as a refusal here -- see
        ``_sweep_retention``.
        """

        retention = self._sweep_retention()
        if retention is not None and not retention.ready:
            _LOG.warning(
                "Offline caption evidence retention refused storage (%s); skipping "
                "job processing this tick.",
                retention.refusal_reason,
            )
            return []
        resolved_now = now or datetime.now(UTC)
        processed: list[OfflineCaptionJobRecord] = []
        for row in self._store.due(now=resolved_now):
            if row.state == OFFLINE_CAPTION_JOB_STATE_PENDING:
                processed.append(self._transcribe(row, now=resolved_now))
            elif row.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW:
                processed.append(self._publish_if_reviewed(row, now=resolved_now))
        return processed

    def _sweep_retention(self) -> CaptionRetentionResult | None:
        """Prune expired retained caption evidence once per tick.

        Runs every ``run_once`` regardless of whether any job is due, same
        cadence as :meth:`civiccast.captions.tap_worker.CaptionTapWorker
        .run_once`'s own unconditional call. ``tap_root=None`` because this
        worker has no live tap directory -- ``enforce_discovered`` already
        treats that as "skip the raw-chunk sweep, still prune resolved
        review-evidence WAVs" (see ``_discover_candidates`` in retention.py).

        Returns the sweep's :class:`~civiccast.captions.retention
        .CaptionRetentionResult` so ``run_once`` can honor a not-ready
        refusal the same way the live tap does, or ``None`` when the sweep
        raised. A retention *failure* -- including building the default
        policy the first time -- must never fail the caption job it happens
        to run alongside, so it is logged and treated as "no opinion this
        tick" (``run_once`` proceeds with job processing), not surfaced as
        a refusal.
        """

        try:
            return self._retention_policy_instance().enforce_discovered(
                tap_root=None,
                review_store=self._review_store,
                # Only consulted for raw-chunk (live tap) candidates, which
                # cannot exist when tap_root is None -- kept for structural
                # parity with the tap-worker call this mirrors.
                segment_seconds=self._settings.chunk_seconds,
            )
        except Exception:
            _LOG.exception(
                "Offline caption evidence retention sweep failed; continuing without "
                "pruning this tick."
            )
            return None

    def _retention_policy_instance(self) -> CaptionEvidenceRetentionPolicy:
        if self._retention_policy is None:
            # Offline evidence WAVs land under the VOD package tree, not
            # the live egress work directory CaptionTapWorker measures
            # (audit finding, P1) -- see the class docstring. Resolved the
            # same way every queued job's own ``package_dir`` was
            # (civiccast.publish.router._queue_offline_captions, via
            # resolve_vod_package_dir): CIVICCAST_UPLOAD_DIR is the
            # required base, optionally overridden by
            # CIVICCAST_VOD_PACKAGE_DIR. Lazy import mirrors
            # civiccast.captions.tap_worker.build_tap_worker's own default
            # resolution -- neither seam is needed eagerly at module load
            # time.
            from civiccast.schedule.paths import resolve_upload_root, resolve_vod_package_root

            upload_root = resolve_upload_root()
            if upload_root is None:
                # A job can only ever have been enqueued with a real
                # package_dir when CIVICCAST_UPLOAD_DIR was set (see
                # _queue_offline_captions, which skips enqueueing
                # otherwise) -- so in real deployments this only fires when
                # nothing is queued yet. Raising here (rather than
                # guessing a root) is caught by _sweep_retention's
                # try/except and logged, same as any other sweep failure.
                raise ValueError(
                    "CIVICCAST_UPLOAD_DIR must be set to resolve the offline "
                    "caption evidence volume for the retention sweep."
                )
            self._retention_policy = CaptionEvidenceRetentionPolicy.from_system(
                storage_root=resolve_vod_package_root(upload_root)
            )
        return self._retention_policy

    # -- stage one ---------------------------------------------------------

    def _transcribe(
        self,
        row: OfflineCaptionJobRecord,
        *,
        now: datetime,
    ) -> OfflineCaptionJobRecord:
        try:
            transcription = transcribe_asset_captions(
                self._runtime_instance(),
                self._review_store,
                asset_id=row.asset_id,
                source_path=Path(row.source_path),
                package_dir=Path(row.package_dir),
                chunk_seconds=self._settings.chunk_seconds,
            )
        except Exception as exc:
            return self._record_failure(row, now=now, error=str(exc), stage="transcription")

        cue_count = len(transcription.cues)
        if cue_count == 0:
            _LOG.info(
                "Offline captioning found no speech in asset %s; nothing to review.",
                row.asset_id,
            )
            return self._store.save(
                row.model_copy(
                    update={
                        "state": OFFLINE_CAPTION_JOB_STATE_COMPLETE,
                        "attempts": row.attempts + 1,
                        "next_attempt_at": None,
                        "cue_count": 0,
                        "last_error": "",
                        "updated_at": now,
                    }
                )
            )
        _LOG.info(
            "Offline captioning queued %d cue(s) for review on asset %s.",
            cue_count,
            row.asset_id,
        )
        return self._store.save(
            row.model_copy(
                update={
                    "state": OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                    # Each stage gets its own attempt budget: a transcription
                    # that needed two tries must not leave the attach stage
                    # with fewer retries than a first-try transcription did.
                    "attempts": 0,
                    # Re-checked on the normal poll cadence; the operator
                    # decides when, not the worker.
                    "next_attempt_at": now,
                    "cue_count": cue_count,
                    "last_error": "",
                    "updated_at": now,
                }
            )
        )

    # -- stage two ---------------------------------------------------------

    def _publish_if_reviewed(
        self,
        row: OfflineCaptionJobRecord,
        *,
        now: datetime,
    ) -> OfflineCaptionJobRecord:
        reviewed = reviewed_caption_cues(self._review_store, row.asset_id)
        if reviewed.pending:
            # Still the operator's move. Not an attempt, not a failure --
            # just poll again without burning the retry budget.
            return self._store.save(
                row.model_copy(update={"next_attempt_at": now, "updated_at": now})
            )
        if not reviewed.cues:
            _LOG.warning(
                "Offline captions for asset %s produced nothing an operator approved; "
                "the published recording stays uncaptioned.",
                row.asset_id,
            )
            return self._store.save(
                row.model_copy(
                    update={
                        "state": OFFLINE_CAPTION_JOB_STATE_COMPLETE,
                        "next_attempt_at": None,
                        "published_cue_count": 0,
                        "last_error": "",
                        "updated_at": now,
                    }
                )
            )
        try:
            # KNOWN FOLLOW-UP (out of CivicCast One v1 scope, owner-approved
            # to defer -- see "Known follow-ups" in
            # docs/ops/background-workers.md and the docstring on
            # attach_reviewed_captions in civiccast/captions/vod.py):
            # this only rewrites the LOCAL manifest and writes the LOCAL
            # WebVTT track/sidecar under row.package_dir. One v1 serves VOD
            # from the local portal origin, so that is complete here. A
            # CDN-backed deployment (CIVICCAST_CDN_PROVIDER) that already
            # pushed the package to its CDN before review finished would
            # not see the caption track or the rewritten manifest entry
            # that declares it -- only the local copy changes. Fix when
            # CDN-backed deployments are in scope: re-run (or extend) the
            # finalization worker's CDN upload
            # (LiveFinalizationWorker._upload_package) for the rewritten
            # manifest and the new caption-track files after this call
            # returns.
            attached = attach_reviewed_captions(Path(row.package_dir), reviewed.cues)
        except Exception as exc:
            return self._record_failure(row, now=now, error=str(exc), stage="caption attach")
        _LOG.info(
            "Published %d reviewed caption cue(s) onto asset %s (%s).",
            attached.cue_count,
            row.asset_id,
            attached.sidecar_path,
        )
        return self._store.save(
            row.model_copy(
                update={
                    "state": OFFLINE_CAPTION_JOB_STATE_COMPLETE,
                    "next_attempt_at": None,
                    "published_cue_count": attached.cue_count,
                    "last_error": "",
                    "updated_at": now,
                }
            )
        )

    # -- shared ------------------------------------------------------------

    def _runtime_instance(self) -> CaptionRuntime:
        if self._runtime is None:
            self._runtime = self._runtime_factory()
        return self._runtime

    def _record_failure(
        self,
        row: OfflineCaptionJobRecord,
        *,
        now: datetime,
        error: str,
        stage: str,
    ) -> OfflineCaptionJobRecord:
        attempts = row.attempts + 1
        if attempts >= self._settings.max_attempts:
            _LOG.error(
                "Offline caption %s for asset %s failed %d time(s); giving up: %s",
                stage,
                row.asset_id,
                attempts,
                error,
            )
            return self._store.save(
                row.model_copy(
                    update={
                        "state": OFFLINE_CAPTION_JOB_STATE_FAILED,
                        "attempts": attempts,
                        "next_attempt_at": None,
                        "last_error": error,
                        "updated_at": now,
                    }
                )
            )
        delay = self._settings.backoff_seconds * (2 ** max(attempts - 1, 0))
        _LOG.warning(
            "Offline caption %s for asset %s failed (attempt %d/%d); next try in %.0fs: %s",
            stage,
            row.asset_id,
            attempts,
            self._settings.max_attempts,
            delay,
            error,
        )
        return self._store.save(
            row.model_copy(
                update={
                    "attempts": attempts,
                    "next_attempt_at": now + timedelta(seconds=delay),
                    "last_error": error,
                    "updated_at": now,
                }
            )
        )
