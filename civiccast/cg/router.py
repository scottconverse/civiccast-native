# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for v0.10 resident CG surfaces."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from civiccast.auth.roles import require_any_role
from civiccast.cg.models import (
    CgBulletinQueue,
    CgBulletinSubmission,
    CgFeedCatalog,
    CgHlsRenderPlan,
    CgOverlayContract,
    CgPortalDisplay,
    CgTemplateLibrary,
    CgZone,
    EmergencyOverlay,
    IdlePage,
    MultiZoneCgSnapshot,
)
from civiccast.cg.service import (
    build_bulletin_queue,
    build_emergency_overlay,
    build_feed_catalog,
    build_hls_manifest,
    build_hls_render_plan,
    build_idle_page,
    build_multi_zone_snapshot,
    build_overlay_contract,
    build_portal_display,
    build_template_library,
)

public_router = APIRouter(prefix="/api/public/cg", tags=["public", "cg"])
staff_router = APIRouter(prefix="/api/staff/cg", tags=["staff", "cg"])


def get_cg_bulletin_store() -> Any:
    """DI seam: the app factory overrides this with the durable bulletin store.

    None (ephemeral/no-DB mode) keeps the deterministic mock queue so demo
    runs and contract tests behave exactly as before CA-3.
    """


def get_cg_board_service() -> Any:
    """DI seam: the app factory overrides this with the durable CgBoardService.

    WP-06: the public feed catalog / portal display read station-configured
    feeds through this seam instead of the legacy deterministic
    ``build_feed_catalog()``. None (ephemeral/no-DB mode, or a fresh app
    factory that hasn't wired durable storage) means no durable board
    configuration exists yet -- callers fall back to an empty catalog (or, if
    explicitly demo-gated, the sample catalog) rather than inventing content.

    Typed ``Any`` (not ``CgBoardService``) to avoid importing
    ``civiccast.cg.board_service`` -- and its egress/ffmpeg-adjacent import
    chain via ``board_router`` -- into this lighter public-router module.
    """


def _cg_demo_feeds_enabled() -> bool:
    """True only when CIVICCAST_CG_DEMO_FEEDS=1 is explicitly set.

    Never on by default in a shipping profile (WP-06 item 4). Set this in a
    demo/dev environment to keep the four sample RSS/iCal/weather/social
    adapters (with example.invalid URLs) available for screenshots and manual
    walkthroughs when no station has configured real feeds yet.
    """

    return os.environ.get("CIVICCAST_CG_DEMO_FEEDS") == "1"


def _empty_feed_catalog(channel_id: str) -> CgFeedCatalog:
    return CgFeedCatalog(
        generated_at=datetime.now(UTC).replace(microsecond=0),
        channel_id=channel_id,
        adapters=[],
        proof_boundary="configured-feed-adapters-to-approved-cg-zone-items",
    )


def _empty_bulletin_queue(channel_id: str) -> CgBulletinQueue:
    return CgBulletinQueue(
        generated_at=datetime.now(UTC).replace(microsecond=0),
        channel_id=channel_id,
        submissions=[],
        approved_zone_items=[],
        proof_boundary="approved-community-bulletins-to-public-cg-zone-items",
    )


def _durable_ticker_zone(zone: CgZone, feeds: CgFeedCatalog, bulletins: CgBulletinQueue) -> CgZone:
    """Build the ticker zone's content from the already-resolved durable feed
    catalog and approved bulletin queue instead of hard-coded sample strings
    (WP-06 follow-up). ``feeds``/``bulletins`` are resolved once per request
    by the caller (durable store, or -- only under CIVICCAST_CG_DEMO_FEEDS=1
    -- the sample catalog/queue), so this never invents content on its own:
    zero durable/demo sources bound to "ticker" simply yields an empty,
    actionable ``{"items": [], "empty": True}`` rather than static filler.
    """

    items = [
        submission.title
        for submission in bulletins.submissions
        if submission.target_zone_kind == "ticker"
    ]
    for adapter in feeds.adapters:
        if "ticker" in adapter.target_zone_kinds:
            items.extend(item.title for item in adapter.items)
    content: dict[str, object] = {"items": items}
    if not items:
        content["empty"] = True
    return zone.model_copy(update={"source": "durable-station-config", "content": content})


class BulletinCreate(BaseModel):
    """Operator-entered community bulletin submission."""

    model_config = ConfigDict(extra="forbid")

    organization: Annotated[str, Field(min_length=1, max_length=160)]
    submitter_label: Annotated[str, Field(min_length=1, max_length=160)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    message: Annotated[str, Field(min_length=1, max_length=500)]
    target_zone_kind: Annotated[str, Field(pattern=r"^(primary|ticker|schedule)$")] = "primary"
    requested_start: datetime | None = None
    requested_end: datetime | None = None


class BulletinUpdate(BaseModel):
    """Moderation/state update; the submission model enforces transition rules."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    message: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    state: (
        Annotated[str, Field(pattern=r"^(submitted|needs_changes|accepted|declined|scheduled)$")]
        | None
    ) = None
    moderation_notes: Annotated[str, Field(max_length=500)] | None = None
    approved_by_operator: Annotated[str, Field(max_length=120)] | None = None


def _queue_from_durable(store: Any, channel_id: str) -> CgBulletinQueue:
    submissions: list[CgBulletinSubmission] = store.list(channel_id=channel_id)
    return CgBulletinQueue(
        generated_at=datetime.now(UTC).replace(microsecond=0),
        channel_id=channel_id,
        submissions=submissions,
        approved_zone_items=_zone_items(submissions),
        proof_boundary="community-submission-queue-to-approved-cg-zone-items",
    )


def _approved_submissions(
    submissions: list[CgBulletinSubmission],
) -> list[CgBulletinSubmission]:
    return [
        submission for submission in submissions if submission.state in {"accepted", "scheduled"}
    ]


def _durable_approved_bulletins(store: Any, channel_id: str) -> CgBulletinQueue:
    """Same durable-store + approved-state filter the public /bulletins
    endpoint below uses -- shared so the portal-display contract's
    ``approved_bulletins`` field never disagrees with the standalone
    endpoint (WP-06 follow-up)."""

    queue = _queue_from_durable(store, channel_id)
    return CgBulletinQueue(
        generated_at=queue.generated_at,
        channel_id=queue.channel_id,
        submissions=_approved_submissions(queue.submissions),
        approved_zone_items=queue.approved_zone_items,
        proof_boundary="approved-community-bulletins-to-public-cg-zone-items",
    )


def _zone_items(submissions: list[CgBulletinSubmission]) -> list[CgZone]:
    return [
        CgZone(
            zone_id=f"bulletin-{submission.submission_id}",
            kind=submission.target_zone_kind,
            title=submission.title,
            source="community-submission",
            content={
                "submission_id": submission.submission_id,
                "organization": submission.organization,
                "message": submission.message,
            },
            refresh_seconds=900,
            approved=True,
        )
        for submission in submissions
        if submission.state in {"accepted", "scheduled"}
    ]


@public_router.get(
    "/idle",
    response_model=IdlePage,
    summary="Read the between-streams idle page state",
)
def idle_page(channel_id: str = "public") -> IdlePage:
    return build_idle_page(channel_id=channel_id)


# DI seam (overridden by the app factory): the EAS service's active-overlay resolver.
# When wired and a channel_id is given, the public overlay reflects a REAL ingested
# public-safety alert being displayed on that channel (S11c) — rendered as generic
# emergency information, never labeled "EAS". None = the deterministic placeholder.
EmergencyOverlayProvider = Callable[[str], EmergencyOverlay | None]


def get_eas_overlay_provider() -> EmergencyOverlayProvider | None:
    return None


@public_router.get(
    "/emergency-overlay",
    response_model=EmergencyOverlay,
    summary="Read the emergency-notification overlay state",
)
def emergency_overlay(
    channel_id: str | None = None,
    overlay_id: str = "test-emergency-overlay",
    severity: str = "warning",
    provider: EmergencyOverlayProvider | None = Depends(get_eas_overlay_provider),
) -> EmergencyOverlay:
    # When EAS is wired and a channel is given, render the real active alert overlay
    # for that channel (or 404 when nothing is being displayed — the player shows no
    # banner). Without a channel (or before EAS is wired) the deterministic placeholder
    # keeps the endpoint usable for demos/tests. Never labeled "EAS".
    if provider is not None and channel_id is not None:
        overlay = provider(channel_id)
        if overlay is not None:
            return overlay
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No emergency overlay is active for this channel."
        )
    return build_emergency_overlay(overlay_id=overlay_id, severity=severity)


@public_router.get(
    "/channels/{channel_id}/snapshot",
    response_model=MultiZoneCgSnapshot,
    summary="Read the multi-zone CG bulletin-board snapshot",
)
def multi_zone_snapshot(
    channel_id: str = "public",
    template_id: str | None = None,
) -> MultiZoneCgSnapshot:
    return build_multi_zone_snapshot(channel_id=channel_id, template_id=template_id)


@public_router.get(
    "/channels/{channel_id}/feeds",
    response_model=CgFeedCatalog,
    summary="Read configured CG dynamic feed adapters",
    responses={
        200: {
            "description": (
                "Adapters built from the station's durably configured, "
                "enabled CG feed sources. An empty adapters list is the "
                "normal state for a station that hasn't configured any feed "
                "yet -- add one in Board Designer -- never invented content."
            )
        },
    },
)
def feed_catalog(
    channel_id: str = "public",
    service: Any = Depends(get_cg_board_service),
) -> CgFeedCatalog:
    # WP-06: production reads durable station configuration through the board
    # service (see CgBoardService.feed_catalog). The deterministic
    # example.invalid sample catalog only appears when the app factory hasn't
    # wired durable storage (ephemeral/no-DB mode) AND an operator has
    # explicitly opted into CIVICCAST_CG_DEMO_FEEDS=1; otherwise a station
    # with nothing configured gets an honest empty catalog, not sample rows.
    if service is not None:
        return cast(CgFeedCatalog, service.feed_catalog(channel_id))
    if _cg_demo_feeds_enabled():
        return build_feed_catalog(channel_id=channel_id)
    return _empty_feed_catalog(channel_id)


@public_router.get(
    "/channels/{channel_id}/templates",
    response_model=CgTemplateLibrary,
    summary="Read the CG template library",
)
def template_library(channel_id: str = "public") -> CgTemplateLibrary:
    return build_template_library(channel_id=channel_id)


@public_router.get(
    "/channels/{channel_id}/bulletins",
    response_model=CgBulletinQueue,
    summary="Read approved community bulletin-board items",
)
def public_bulletins(
    channel_id: str = "public",
    store: Any = Depends(get_cg_bulletin_store),
) -> CgBulletinQueue:
    queue = (
        _queue_from_durable(store, channel_id)
        if store is not None
        else build_bulletin_queue(channel_id=channel_id)
    )
    return CgBulletinQueue(
        generated_at=queue.generated_at,
        channel_id=queue.channel_id,
        submissions=_approved_submissions(queue.submissions),
        approved_zone_items=queue.approved_zone_items,
        proof_boundary="approved-community-bulletins-to-public-cg-zone-items",
    )


@staff_router.get(
    "/channels/{channel_id}/bulletins",
    response_model=CgBulletinQueue,
    summary="Read operator community bulletin submission queue",
    dependencies=[Depends(require_any_role("setup_admin", "publish_operator"))],
)
def staff_bulletin_queue(
    channel_id: str = "public",
    store: Any = Depends(get_cg_bulletin_store),
) -> CgBulletinQueue:
    if store is not None:
        return _queue_from_durable(store, channel_id)
    return build_bulletin_queue(channel_id=channel_id)


@staff_router.post(
    "/channels/{channel_id}/bulletins",
    response_model=CgBulletinSubmission,
    summary="Add a community bulletin submission to the channel board",
    dependencies=[Depends(require_any_role("setup_admin", "publish_operator"))],
    responses={503: {"description": "Durable storage not ready"}},
)
def create_bulletin(
    channel_id: str,
    payload: BulletinCreate,
    store: Any = Depends(get_cg_bulletin_store),
) -> CgBulletinSubmission:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Durable storage is not ready. Open Setup and choose Prepare "
                "storage before managing community bulletins."
            ),
        )
    submission = CgBulletinSubmission(
        submission_id="cgb_" + secrets.token_urlsafe(9).replace("-", "").replace("_", ""),
        organization=payload.organization,
        submitter_label=payload.submitter_label,
        title=payload.title,
        message=payload.message,
        target_zone_kind=payload.target_zone_kind,  # type: ignore[arg-type]
        state="submitted",
        requested_start=payload.requested_start,
        requested_end=payload.requested_end,
    )
    return store.create(channel_id, submission)  # type: ignore[no-any-return]


@staff_router.patch(
    "/channels/{channel_id}/bulletins/{submission_id}",
    response_model=CgBulletinSubmission,
    summary="Moderate a community bulletin (approve, decline, request changes)",
    dependencies=[Depends(require_any_role("setup_admin", "publish_operator"))],
    responses={
        404: {"description": "Bulletin not found on this channel"},
        422: {"description": "Transition violates the approval rules"},
        503: {"description": "Durable storage not ready"},
    },
)
def update_bulletin(
    channel_id: str,
    submission_id: str,
    payload: BulletinUpdate,
    store: Any = Depends(get_cg_bulletin_store),
) -> CgBulletinSubmission:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Durable storage is not ready. Open Setup and choose Prepare "
                "storage before managing community bulletins."
            ),
        )
    existing = store.get(submission_id)
    if existing is None or existing[0] != channel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bulletin not found on channel {channel_id!r}: {submission_id}",
        )
    updates = payload.model_dump(exclude_unset=True)
    try:
        updated = existing[1].model_copy(update=updates)
        # Re-validate: model_copy(update=...) bypasses validators, and the
        # approval rules (operator id for accept, notes for decline) are the
        # whole point of this endpoint.
        updated = CgBulletinSubmission.model_validate(updated.model_dump())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return store.update(channel_id, updated)  # type: ignore[no-any-return]


@public_router.get(
    "/channels/{channel_id}/render-plan",
    response_model=CgHlsRenderPlan,
    summary="Read the CG HLS render plan",
)
def hls_render_plan(channel_id: str = "public") -> CgHlsRenderPlan:
    return build_hls_render_plan(channel_id=channel_id)


@public_router.get(
    "/channels/{channel_id}/stream.m3u8",
    response_class=Response,
    summary="Read the CG HLS manifest",
)
def hls_manifest(channel_id: str = "public") -> Response:
    return Response(
        content=build_hls_manifest(channel_id=channel_id),
        media_type="application/vnd.apple.mpegurl",
    )


@public_router.get(
    "/channels/{channel_id}/overlay-contract",
    response_model=CgOverlayContract,
    summary="Read the CG linear overlay contract",
)
def overlay_contract(channel_id: str = "public") -> CgOverlayContract:
    return build_overlay_contract(channel_id=channel_id)


@public_router.get(
    "/channels/{channel_id}/display",
    response_model=CgPortalDisplay,
    summary="Read the complete CG portal display contract",
)
def portal_display(
    channel_id: str = "public",
    template_id: str | None = None,
    service: Any = Depends(get_cg_board_service),
    bulletin_store: Any = Depends(get_cg_bulletin_store),
) -> CgPortalDisplay:
    # WP-06 + follow-up: feed_catalog, approved_bulletins, and the snapshot's
    # ticker zone are the parts of this contract this work touches -- each is
    # assembled the same way its standalone endpoint above is (/feeds,
    # /bulletins), so they never disagree. The template library, render plan,
    # and overlay contract are unchanged (out of scope; no example.invalid /
    # sample content lives there).
    display = build_portal_display(channel_id=channel_id, template_id=template_id)

    if service is not None:
        feeds = cast(CgFeedCatalog, service.feed_catalog(channel_id))
    elif _cg_demo_feeds_enabled():
        feeds = display.feed_catalog
    else:
        feeds = _empty_feed_catalog(channel_id)

    if bulletin_store is not None:
        bulletins = _durable_approved_bulletins(bulletin_store, channel_id)
    elif _cg_demo_feeds_enabled():
        bulletins = CgBulletinQueue(
            generated_at=display.approved_bulletins.generated_at,
            channel_id=display.approved_bulletins.channel_id,
            submissions=_approved_submissions(display.approved_bulletins.submissions),
            approved_zone_items=display.approved_bulletins.approved_zone_items,
            proof_boundary="approved-community-bulletins-to-public-cg-zone-items",
        )
    else:
        bulletins = _empty_bulletin_queue(channel_id)

    # The ticker zone is rebuilt from the SAME resolved feeds/bulletins above
    # (never the static sample zone), so it is empty by default, matches the
    # demo flag when set, and can never drift from the /feeds and /bulletins
    # contracts.
    zones = [
        _durable_ticker_zone(zone, feeds, bulletins) if zone.kind == "ticker" else zone
        for zone in display.snapshot.zones
    ]
    snapshot = display.snapshot.model_copy(update={"zones": zones})

    return display.model_copy(
        update={"feed_catalog": feeds, "approved_bulletins": bulletins, "snapshot": snapshot}
    )
