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

from civiccast.captions.cdn_republish import CaptionPackageCdnRepublisher
from civiccast.captions.models import CaptionCue
from civiccast.captions.retention import CaptionEvidenceRetentionPolicy, CaptionRetentionResult
from civiccast.captions.review import CaptionReviewStore
from civiccast.captions.runtime import CaptionRuntime
from civiccast.captions.vod import (
    OFFLINE_CAPTION_CHUNK_SECONDS,
    OFFLINE_CAPTION_LANGUAGE,
    SPANISH_CAPTION_LANGUAGE,
    ReviewedCaptions,
    attach_reviewed_captions,
    queue_translated_captions,
    reviewed_caption_cues,
    transcribe_asset_captions,
)
from civiccast.translate.models import TranslationTarget
from civiccast.translate.service import TranslationProvider

_LOG = logging.getLogger(__name__)

OfflineCaptionJobState = Literal["pending", "awaiting_review", "complete", "failed"]

# Annotated with the Literal rather than left as bare str. Untyped, each of
# these infers as `str`, so passing one where OfflineCaptionJobState is
# expected -- as create_offline_caption_job does -- was an arg-type error, and
# a typo in any of these four strings would have type-checked clean.
OFFLINE_CAPTION_JOB_STATE_PENDING: OfflineCaptionJobState = "pending"
OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW: OfflineCaptionJobState = "awaiting_review"
OFFLINE_CAPTION_JOB_STATE_COMPLETE: OfflineCaptionJobState = "complete"
OFFLINE_CAPTION_JOB_STATE_FAILED: OfflineCaptionJobState = "failed"
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


OFFLINE_CAPTION_JOB_MODE_INLINE = "inline"
OFFLINE_CAPTION_JOB_MODE_OFF = "off"
_OFFLINE_CAPTION_JOB_MODES = (OFFLINE_CAPTION_JOB_MODE_INLINE, OFFLINE_CAPTION_JOB_MODE_OFF)

#: The switch that used to be able to turn the recorded-Spanish leg off.
#: It no longer can (see ``OfflineCaptionJobSettings.spanish_enabled``);
#: ``from_env`` still *reads* it, only to fail fast rather than silently
#: ignore a station that is asking for English-only output.
_SPANISH_ENV_VAR = "CIVICCAST_OFFLINE_CAPTION_SPANISH"
_TRUE_ENV_VALUES = ("1", "true", "on", "yes", "es")
_FALSE_ENV_VALUES = ("0", "false", "off", "no")

#: Put on the job row (and therefore in front of the operator) when the
#: station has no translation runtime wired but a recording is waiting on
#: its Spanish track. Names the thing to fix, not the internal symbol.
MISSING_TRANSLATOR_REMEDIATION = (
    "This recording's English captions are approved, but CivicCast has no translation "
    "model available to produce the required Spanish track, so the recording cannot "
    "finish publishing. Install or repair the station's translation model (Settings > "
    "AI Models > Translation) and run 'civiccast doctor'; the job retries on its own."
)

#: Put on the job row when the operator rejected every Spanish cue. English
#: alone is not a publishable outcome, so the job waits for a usable Spanish
#: track instead of completing.
ALL_SPANISH_REJECTED_REMEDIATION = (
    "Every Spanish caption cue for this recording was rejected. A published recording "
    "must carry a reviewed Spanish track alongside English, so it is being held here "
    "rather than published in English only. Open the caption review queue, filter to "
    "Spanish, and edit the cues with the correct wording (or approve the ones that are "
    "right); publication continues automatically once at least one Spanish cue is "
    "approved or edited."
)

CaptionRuntimeFactory = Callable[[], CaptionRuntime]
#: Lazy builder for the translation adapter -- same shape as the runtime
#: factory, so a station with the worker enabled but nothing to translate
#: never loads the translation model.
TranslationProviderFactory = Callable[[], TranslationProvider]

__all__ = [
    "ALL_SPANISH_REJECTED_REMEDIATION",
    "MISSING_TRANSLATOR_REMEDIATION",
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
    #: Recorded-Spanish translation leg. **Not configurable in a shipping
    #: profile, and never set from the environment** -- a published
    #: recording carrying a reviewed Spanish track alongside English is an
    #: owner requirement, not a station preference (Longmont is ~30%
    #: Latino). A published recording's operator-approved English captions
    #: are translated to Spanish and queued for their OWN review pass, and
    #: neither track attaches until both passes are complete.
    #:
    #: The field survives only so a *test fixture* can construct a worker
    #: with the leg off to exercise the English half in isolation. Nothing
    #: in ``from_env`` (or anywhere else in production wiring) can set it
    #: to ``False``; ``from_env`` raises when the retired
    #: ``CIVICCAST_OFFLINE_CAPTION_SPANISH`` switch asks for English-only,
    #: rather than starting a station that would quietly publish
    #: English-only recordings.
    spanish_enabled: bool = True
    #: Target language tag for that leg. ``es`` today; kept configurable so
    #: another station could translate to a different language without a code
    #: change, though only Spanish is a shipped requirement.
    spanish_target_language: str = SPANISH_CAPTION_LANGUAGE

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
        _reject_retired_spanish_switch()
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
            # spanish_enabled is deliberately NOT read from the environment
            # -- see the field's docstring. It keeps its ``True`` default in
            # every profile this classmethod can produce.
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


def _reject_retired_spanish_switch() -> None:
    """Fail startup rather than silently ignore an English-only request.

    ``CIVICCAST_OFFLINE_CAPTION_SPANISH`` used to be able to turn the
    recorded-Spanish leg off. It cannot any more: a caption-eligible
    published recording must carry a reviewed Spanish track, so there is no
    supported English-only configuration. A station that still carries the
    switch set to a false value is asking for behavior CivicCast will not
    do, and the worst possible answer is to start anyway and let the
    operator believe the setting took -- they would find out from a
    resident. So it raises here, at ``from_env``, which the app factory
    calls during startup (before any recording is queued), with the name of
    the variable to remove.

    A true value asks for what already happens unconditionally, so it is a
    no-op rather than a failure; it is logged so the operator learns the
    variable no longer does anything.
    """

    raw = os.environ.get(_SPANISH_ENV_VAR, "").strip().lower()
    if not raw:
        return
    if raw in _TRUE_ENV_VALUES:
        _LOG.info(
            "%s is set to %r, which is now the only supported behavior; the variable "
            "no longer does anything and can be removed.",
            _SPANISH_ENV_VAR,
            raw,
        )
        return
    if raw in _FALSE_ENV_VALUES:
        raise ValueError(
            f"{_SPANISH_ENV_VAR}={raw!r} would publish recordings with English captions "
            "only. A published recording must carry an operator-reviewed Spanish caption "
            "track alongside English, so this switch can no longer disable it. Remove "
            f"{_SPANISH_ENV_VAR} from the station environment and start CivicCast again."
        )
    raise ValueError(
        f"{_SPANISH_ENV_VAR} must be one of "
        f"{', '.join((*_TRUE_ENV_VALUES, *_FALSE_ENV_VALUES))}; got {raw!r}."
    )


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
        translation_provider_factory: TranslationProviderFactory | None = None,
        cdn_republisher: CaptionPackageCdnRepublisher | None = None,
        retention_policy: CaptionEvidenceRetentionPolicy | None = None,
    ) -> None:
        self._store = store
        self._review_store = review_store
        self._runtime_factory = runtime_factory
        self._settings = settings
        # Built lazily on first Spanish translation, same reason as
        # ``_runtime`` -- a station with nothing to translate never loads
        # the translation model. ``None`` means "no translation runtime
        # configured", which is a station MISCONFIGURATION, not an
        # English-only mode: a job that reaches the Spanish leg without a
        # translator fails with MISSING_TRANSLATOR_REMEDIATION on the row
        # rather than publishing English alone. app.py always supplies the
        # factory in production.
        self._translation_provider_factory = translation_provider_factory
        self._translation_provider: TranslationProvider | None = None
        # Optional: re-publishes the rewritten manifest and the new caption
        # files to the CDN this asset's package is actually served from
        # (see civiccast.captions.cdn_republish). ``None`` means no CDN is
        # configured, so the local rewrite IS the published state.
        self._cdn_republisher = cdn_republisher
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
        """Two-phase publish gate (spec §4.2, operator review before publish).

        Phase one gates on the ENGLISH review pass. Once English is fully
        decided and something was approved, the recorded-Spanish leg
        translates those approved English cues, queues the Spanish cues for
        their OWN review pass, and gates a second time on that pass. Only
        when BOTH passes are complete are both tracks attached in a single
        manifest rewrite. Nothing is published while either language still
        has pending rows -- an early attach would put unreviewed AI text on
        the public record.

        There is no English-only success path (owner requirement: Spanish
        captions on published recordings are required, not optional). The
        two ways the Spanish leg can fail to produce a track are both
        handled as *blocked*, never as completion:

        * no translation runtime wired -> ``_record_failure`` with
          :data:`MISSING_TRANSLATOR_REMEDIATION`;
        * every Spanish cue rejected -> ``_await_spanish_rework``, which
          holds the job open with :data:`ALL_SPANISH_REJECTED_REMEDIATION`.

        The one case that does complete without any track is an asset whose
        *English* pass approved nothing: there is no English to publish
        either, so nothing was captioned and there is nothing to hold for.
        """

        english = reviewed_caption_cues(
            self._review_store, row.asset_id, language=OFFLINE_CAPTION_LANGUAGE
        )
        if english.pending:
            # Still the operator's move on the English pass. Not an attempt,
            # not a failure -- just poll again without burning the budget.
            return self._poll_again(row, now=now)
        if not english.cues:
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

        # English is approved. Spanish is REQUIRED before anything attaches:
        # both tracks land together, or neither does. There is no
        # English-only success path for a caption-eligible recording.
        spanish_cues: list[CaptionCue] | None = None
        if self._settings.spanish_enabled:
            if self._translation_provider_factory is None:
                # Station misconfiguration, not a mode. Blocked with a
                # remediation on the row rather than a green English-only
                # publish. Consumes the attempt budget so the job lands in
                # ``failed`` (and out of the polling loop) if the operator
                # never repairs the runtime -- ``failed`` keeps the reason
                # on the row for the staff "what's stuck and why" view.
                return self._record_failure(
                    row,
                    now=now,
                    error=MISSING_TRANSLATOR_REMEDIATION,
                    stage="caption translation",
                )
            try:
                spanish = self._resolve_spanish_review(row.asset_id, english.cues)
            except Exception as exc:
                return self._record_failure(
                    row, now=now, error=str(exc), stage="caption translation"
                )
            if spanish is None:
                # Spanish cues are queued but still under review -- gate the
                # final attach without burning the retry budget, exactly like
                # a pending English pass.
                return self._poll_again(row, now=now)
            if not spanish.cues:
                # Every Spanish cue was rejected. Publishing English alone
                # here is precisely the fail-open this policy forbids, and
                # failing the job would take the operator's remaining move
                # away, so the job stays active and actionable: the operator
                # edits or approves Spanish rows in the review queue and the
                # next poll finishes the publish. Review decisions are not
                # terminal (see CaptionReviewStore.edit/approve), so that
                # move is really available.
                return self._await_spanish_rework(row, now=now)
            spanish_cues = spanish.cues

        try:
            attached = attach_reviewed_captions(
                Path(row.package_dir), english.cues, spanish_cues=spanish_cues
            )
        except Exception as exc:
            return self._record_failure(row, now=now, error=str(exc), stage="caption attach")
        if self._cdn_republisher is not None:
            # attach_reviewed_captions rewrote the LOCAL manifest and wrote
            # the LOCAL caption files. If this package is served to residents
            # through a CDN, that copy is still the pre-caption one, and
            # calling the job complete would claim a captioned recording the
            # public cannot get. Re-publish before completing; a failure
            # fails the job (with the provider's message on the row) instead.
            # Safe to retry: attach is idempotent, so a re-run rewrites the
            # same files from the same decisions and re-uploads them.
            try:
                self._cdn_republisher.republish(
                    asset_id=row.asset_id,
                    package_dir=Path(row.package_dir),
                    attached=attached,
                )
            except Exception as exc:
                return self._record_failure(
                    row, now=now, error=str(exc), stage="caption CDN republish"
                )
        _LOG.info(
            "Published %d English + %d Spanish reviewed caption cue(s) onto asset %s (%s).",
            attached.cue_count,
            attached.spanish_cue_count,
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

    def _poll_again(
        self, row: OfflineCaptionJobRecord, *, now: datetime
    ) -> OfflineCaptionJobRecord:
        """Re-check on the next poll without consuming the retry budget."""

        return self._store.save(row.model_copy(update={"next_attempt_at": now, "updated_at": now}))

    def _await_spanish_rework(
        self, row: OfflineCaptionJobRecord, *, now: datetime
    ) -> OfflineCaptionJobRecord:
        """Hold an all-Spanish-rejected job open, with the operator's next move on it.

        Stays in ``awaiting_review`` and does not consume the retry budget --
        the block is a decision waiting on a human, not a transient fault --
        but unlike :meth:`_poll_again` it puts a reason on the row, because
        an otherwise-silent job that never completes is the thing an
        operator cannot act on.
        """

        _LOG.warning(
            "Every Spanish caption cue for asset %s was rejected; holding the recording "
            "rather than publishing it in English only.",
            row.asset_id,
        )
        return self._store.save(
            row.model_copy(
                update={
                    "next_attempt_at": now,
                    "last_error": ALL_SPANISH_REJECTED_REMEDIATION,
                    "updated_at": now,
                }
            )
        )

    def _resolve_spanish_review(
        self,
        asset_id: str,
        english_cues: list[CaptionCue],
    ) -> ReviewedCaptions | None:
        """Ensure Spanish cues are queued, then gate on their review pass.

        Returns the reviewed Spanish cues once every Spanish row has an
        operator decision (an empty ``cues`` list means all were rejected),
        or ``None`` while any Spanish row is still pending. Translation runs
        exactly once per asset: the ``total == 0`` guard means a re-poll while
        Spanish is under review never re-invokes the model, and
        ``queue_translated_captions`` is itself idempotent as a second line of
        defense.
        """

        target_language = self._settings.spanish_target_language
        spanish = reviewed_caption_cues(self._review_store, asset_id, language=target_language)
        if spanish.total == 0:
            queued = queue_translated_captions(
                self._review_store,
                asset_id=asset_id,
                cues=english_cues,
                provider=self._translation_provider_instance(),
                target=TranslationTarget(target_language=target_language),
            )
            _LOG.info(
                "Queued %d Spanish caption cue(s) for review on asset %s (%d already queued).",
                len(queued.created_review_item_ids),
                asset_id,
                len(queued.duplicate_review_item_ids),
            )
            spanish = reviewed_caption_cues(self._review_store, asset_id, language=target_language)
        if spanish.pending:
            return None
        return spanish

    # -- shared ------------------------------------------------------------

    def _runtime_instance(self) -> CaptionRuntime:
        if self._runtime is None:
            self._runtime = self._runtime_factory()
        return self._runtime

    def _translation_provider_instance(self) -> TranslationProvider:
        if self._translation_provider is None:
            if self._translation_provider_factory is None:  # pragma: no cover - guarded by caller
                raise RuntimeError(
                    "No translation provider factory configured for the offline caption "
                    "worker; the recorded-Spanish leg cannot run."
                )
            self._translation_provider = self._translation_provider_factory()
        return self._translation_provider

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
