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
from civiccast.summary.models import OperatorApproval, SummaryDraft
from civiccast.summary.ollama import OllamaSummaryModel
from civiccast.summary.store import (
    SummaryStore,
    SummaryStoreConflictError,
    SummaryStoreNotFoundError,
)

staff_router = APIRouter(prefix="/api/staff/summaries", tags=["staff", "summaries"])

OLLAMA_NOT_CONFIGURED_MESSAGE = (
    "Local Ollama AI runtime is not reachable. Start Ollama and retry, or configure a "
    "different summary model in AI model settings."
)


def get_summary_store(request: Request) -> SummaryStore:
    """FastAPI dependency for the active summary review store."""

    return cast(
        SummaryStore, resolve_app_store(request, "summary_store", surface="Summary review store")
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
