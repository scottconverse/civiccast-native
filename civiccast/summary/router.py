# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff API for v0.6 sourced summary review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from civiccast.ai_runtime.ollama_client import OllamaRuntimeUnavailableError
from civiccast.auth.roles import require_any_role
from civiccast.captions import CaptionCue
from civiccast.platform.stores import resolve_app_store
from civiccast.summary.csv_export import render_transcript_csv
from civiccast.summary.generate import SummaryGenerationPipeline, SummaryModel
from civiccast.summary.job import (
    SUMMARY_JOB_STATE_FAILED,
    SUMMARY_JOB_STATE_PENDING,
    SummaryGenerationJobConflictError,
    SummaryGenerationJobRecord,
    SummaryGenerationJobState,
    SummaryGenerationJobStore,
    enqueue_summary_job,
)
from civiccast.summary.models import OperatorApproval, SummaryDraft
from civiccast.summary.ollama import OllamaSummaryModel
from civiccast.summary.store import (
    SummaryStore,
    SummaryStoreConflictError,
    SummaryStoreNotFoundError,
)

staff_router = APIRouter(prefix="/api/staff/summaries", tags=["staff", "summaries"])

_SUMMARY_JOB_STORE_NOT_READY_DETAIL = (
    "Summary generation job store is not configured for this app instance. "
    "Restart CivicCast through create_app() or configure the store bundle."
)

OLLAMA_NOT_CONFIGURED_MESSAGE = (
    "Local Ollama AI runtime is not reachable. Start Ollama and retry, or configure a "
    "different summary model in AI model settings."
)


def get_summary_store(request: Request) -> SummaryStore:
    """FastAPI dependency for the active summary review store."""

    return cast(
        SummaryStore, resolve_app_store(request, "summary_store", surface="Summary review store")
    )


def get_summary_job_store(request: Request) -> SummaryGenerationJobStore | None:
    """FastAPI dependency for the async summary generation job queue, when configured.

    Optional like ``get_offline_caption_job_store`` in ``captions.router``: a station
    running without durable storage has nowhere to keep a job that can legitimately
    span minutes of CPU-only generation (field evidence 2026-08-29 -- see
    civiccast/summary/job.py), so these endpoints report 503 rather than pretending.
    """

    return cast(
        "SummaryGenerationJobStore | None",
        resolve_app_store(request, "summary_job_store", surface="Summary generation job store"),
    )


def get_summary_model() -> SummaryModel:
    """FastAPI dependency for the active summary model (default: no durable storage).

    ``for_release()`` calls out to the local Ollama daemon to capture live model
    provenance; when Ollama isn't running/installed this raises
    ``OllamaRuntimeUnavailableError`` (unified in ``ai_runtime.ollama_client``
    for daemon-down, model-missing, and generate-call-failed alike). Report it
    the same clean "not configured" way the AI-models availability surface
    already does, rather than letting it bubble into a raw 500.

    When durable storage is wired, ``civiccast.app``'s app factory overrides
    this dependency with ``_resolve_summary_model`` (a separate path through
    ``ai_models.dispatch.build_summary_model`` to the same local-Ollama build)
    -- that override needs and has the identical try/except, since FastAPI
    calls whichever resolver is registered, not this one.
    """

    try:
        return OllamaSummaryModel.for_release()
    except OllamaRuntimeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=OLLAMA_NOT_CONFIGURED_MESSAGE
        ) from exc


class SummaryReviewQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SummaryDraft]
    next_cursor: str | None = None


class SummaryGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    cues: list[CaptionCue] = Field(default_factory=list)


class SummaryApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_note: str | None = None


@staff_router.get(
    "/review-items",
    response_model=SummaryReviewQueueResponse,
    summary="List sourced summaries awaiting operator review",
)
def list_review_items(
    store: SummaryStore = Depends(get_summary_store),
) -> SummaryReviewQueueResponse:
    return SummaryReviewQueueResponse(items=store.list_review_items(), next_cursor=None)


@staff_router.post(
    "/generate",
    response_model=SummaryDraft,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a sourced summary draft from committed transcript cues",
    dependencies=[Depends(require_any_role("records_clerk", "support_admin"))],
    responses={503: {"description": OLLAMA_NOT_CONFIGURED_MESSAGE}},
)
def generate_summary(
    payload: SummaryGenerateRequest,
    model: SummaryModel = Depends(get_summary_model),
    store: SummaryStore = Depends(get_summary_store),
) -> SummaryDraft:
    try:
        draft = SummaryGenerationPipeline(model=model).generate(
            meeting_id=payload.meeting_id,
            cues=payload.cues,
        )
    except OllamaRuntimeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=OLLAMA_NOT_CONFIGURED_MESSAGE
        ) from exc
    try:
        return store.create_summary(draft)
    except SummaryStoreConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Summary already exists: {draft.summary_id}",
        ) from exc


@staff_router.post(
    "/{summary_id}/approve",
    response_model=SummaryDraft,
    summary="Approve a sourced summary for signed-record export",
    dependencies=[Depends(require_any_role("records_clerk"))],
    responses={404: {"description": "Summary not found"}},
)
def approve_summary(
    request: Request,
    summary_id: str,
    payload: SummaryApprovalRequest,
    store: SummaryStore = Depends(get_summary_store),
) -> SummaryDraft:
    operator_identity = request.state.operator_identity
    approval = OperatorApproval(
        summary_id=summary_id,
        operator_id=operator_identity.operator_id,
        operator_display_name=operator_identity.operator_display_name,
        approved_at=datetime.now(UTC),
        approval_note=payload.approval_note,
    )
    try:
        return store.approve_summary(approval)
    except SummaryStoreNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary not found: {summary_id}. Generate or select an existing summary first.",
        ) from exc


@staff_router.post(
    "/transcript.csv",
    summary="Export committed transcript cues as CSV",
    dependencies=[Depends(require_any_role("records_clerk", "support_admin"))],
    responses={200: {"content": {"text/csv": {}}}},
)
def export_transcript_csv(payload: SummaryGenerateRequest) -> Response:
    return Response(content=render_transcript_csv(payload.cues), media_type="text/csv")


# --- async summary generation job (field evidence 2026-08-29) ---------------
#
# POST /generate above blocks the request for as long as the model takes -- fine
# for a fast cloud tier, but a legitimate CPU-only local generation (measured
# 94-366s+ on the 32GB reference station) either sits behind an operator's open
# browser tab for minutes or, pre-fix, got discarded when the control plane's own
# timeout fired before Ollama finished. These endpoints are the async path: queue
# the same generation as a durable job (civiccast/summary/job.py, the same pattern
# civiccast.captions.vod_job established for offline captioning) and let the
# operator console poll visible progress instead of holding the connection open.
# POST /generate is unchanged and still works for a fast tier or a script.


@staff_router.post(
    "/jobs",
    response_model=SummaryGenerationJobRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Queue async summary generation from committed transcript cues",
    dependencies=[Depends(require_any_role("records_clerk", "support_admin"))],
    responses={503: {"description": _SUMMARY_JOB_STORE_NOT_READY_DETAIL}},
)
def create_summary_job(
    payload: SummaryGenerateRequest,
    store: SummaryGenerationJobStore | None = Depends(get_summary_job_store),
) -> SummaryGenerationJobRecord:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_SUMMARY_JOB_STORE_NOT_READY_DETAIL,
        )
    return enqueue_summary_job(store, meeting_id=payload.meeting_id, cues=payload.cues)


@staff_router.get(
    "/jobs",
    response_model=list[SummaryGenerationJobRecord],
    summary="List summary generation jobs for operator visibility",
    responses={503: {"description": _SUMMARY_JOB_STORE_NOT_READY_DETAIL}},
)
def list_summary_jobs(
    meeting_id: str | None = None,
    state: SummaryGenerationJobState | None = None,
    store: SummaryGenerationJobStore | None = Depends(get_summary_job_store),
) -> list[SummaryGenerationJobRecord]:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_SUMMARY_JOB_STORE_NOT_READY_DETAIL,
        )
    return store.list(meeting_id=meeting_id, state=state)


@staff_router.get(
    "/jobs/{job_id}",
    response_model=SummaryGenerationJobRecord,
    summary="Get one summary generation job's status/progress",
    responses={
        404: {"description": "Summary generation job not found"},
        503: {"description": _SUMMARY_JOB_STORE_NOT_READY_DETAIL},
    },
)
def get_summary_job(
    job_id: str,
    store: SummaryGenerationJobStore | None = Depends(get_summary_job_store),
) -> SummaryGenerationJobRecord:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_SUMMARY_JOB_STORE_NOT_READY_DETAIL,
        )
    job = store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary generation job not found: {job_id}",
        )
    return job


@staff_router.post(
    "/jobs/{job_id}/retry",
    response_model=SummaryGenerationJobRecord,
    summary="Manually retry a failed summary generation job",
    dependencies=[Depends(require_any_role("records_clerk"))],
    responses={
        404: {"description": "Summary generation job not found"},
        409: {"description": "Only a failed job can be manually retried"},
        503: {"description": _SUMMARY_JOB_STORE_NOT_READY_DETAIL},
    },
)
def retry_summary_job(
    job_id: str,
    store: SummaryGenerationJobStore | None = Depends(get_summary_job_store),
) -> SummaryGenerationJobRecord:
    """Reset a failed job to pending with a fresh attempt budget.

    Mirrors ``captions.router.retry_offline_caption_job``: pre-checks
    ``active_for_meeting`` so a retry never creates a second active job for a
    meeting that picked up a new job in the meantime (a second operator's retry,
    or a fresh generate), and catches the same conflict error the durable store's
    ``save`` raises if that check loses a TOCTOU race, so a race never surfaces as
    a raw 500.
    """
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_SUMMARY_JOB_STORE_NOT_READY_DETAIL,
        )
    job = store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary generation job not found: {job_id}",
        )
    if job.state != SUMMARY_JOB_STATE_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Summary generation job {job_id} is {job.state!r}; only a failed "
                "job can be manually retried."
            ),
        )
    conflict = store.active_for_meeting(job.meeting_id)
    if conflict is not None and conflict.job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Summary generation job {conflict.job_id!r} is already active for "
                f"meeting {job.meeting_id!r}; retry {job_id} once it finishes."
            ),
        )
    now = datetime.now(UTC)
    try:
        return store.save(
            job.model_copy(
                update={
                    "state": SUMMARY_JOB_STATE_PENDING,
                    "attempts": 0,
                    "next_attempt_at": now,
                    "last_error": "",
                    "updated_at": now,
                }
            )
        )
    except SummaryGenerationJobConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Summary generation job {job_id} could not be retried: another job "
                f"is now active for meeting {job.meeting_id!r}."
            ),
        ) from exc
