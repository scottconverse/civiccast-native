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
from civiccast.cable.channel import get_channel_profile
from civiccast.cg.board_resolver import coming_up_next
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


# DI seam (overridden by the app factory): the EAS service's active-overlay resolver.
# When wired and a channel_id is given, the public overlay reflects a REAL ingested
# public-safety alert being displayed on that channel (S11c) — rendered as generic
# emergency information, never labeled "EAS". None = the deterministic placeholder.
EmergencyOverlayProvider = Callable[[str], EmergencyOverlay | None]


def get_eas_overlay_provider() -> EmergencyOverlayProvider | None:
    return None


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


def _durable_schedule_zone(
    zone: CgZone, upcoming: list[tuple[datetime, str]], *, now: datetime
) -> CgZone:
    """Build the "coming up next" schedule zone from the station's real
    program-log occurrences (``CgBoardService.upcoming()`` -- the same
    program-log data the operator Schedule and Program Guide screens read),
    instead of the hard-coded "18:00 City Council" / "20:00 Planning Board"
    sample. Empty, actionable when the station has nothing scheduled next."""

    items = coming_up_next(upcoming, now=now)
    content: dict[str, object] = {"items": items}
    if not items:
        content["empty"] = True
    return zone.model_copy(update={"source": "durable-station-config", "content": content})


def _honest_primary_zone(zone: CgZone) -> CgZone:
    """The primary zone is generic between-streams platform copy, not a
    per-station configuration value -- no CG board/feed/bulletin store owns
    "primary zone content" as a concept. Reuses the SAME already-approved
    copy the /idle endpoint returns (never a fabricated headline/body), and
    is never demo-gated: it isn't sample data standing in for real
    configuration, it's genuine product messaging."""

    idle = build_idle_page()
    return zone.model_copy(
        update={
            "source": "platform-copy",
            "content": {"headline": idle.title, "body": idle.message},
        }
    )


def _durable_logo_zone(zone: CgZone, channel_id: str) -> CgZone:
    """Source the logo zone from the channel's real branding profile --
    the SAME civiccast.cable.channel.get_channel_profile() lookup the
    audited board-preview render path (board_router._preview_branding)
    already uses as this codebase's one channel-identity source. This is
    not new invented content: it is the identity the real on-air preview
    already shows, not a separate fabricated "PUBLIC" label."""

    profile = get_channel_profile(channel_id)
    if profile is None:
        return zone.model_copy(
            update={
                "source": "channel-profile-not-found",
                "content": {"logo_text": "", "color": ""},
            }
        )
    return zone.model_copy(
        update={
            "source": "channel-branding-profile",
            "content": {
                "logo_text": profile.branding.logo_text,
                "color": profile.branding.color,
            },
        }
    )


def _honest_audio_zone(zone: CgZone) -> CgZone:
    """Board background audio remains a disabled future control (WP-06 plan
    item 5) -- this zone must never claim an active sample track is
    playing."""

    return zone.model_copy(
        update={
            "source": "future-release-disabled",
            "content": {"track": None, "duck_under_alerts": False, "disabled": True},
        }
    )


def _resolve_alert_zone(
    zone: CgZone, channel_id: str, provider: EmergencyOverlayProvider | None
) -> CgZone:
    """Mirror the real /emergency-overlay endpoint's provider contract: a
    real active public-safety alert when EAS is wired and one is showing on
    this channel, otherwise honestly inactive -- never a fabricated alert."""

    overlay = provider(channel_id) if provider is not None else None
    if overlay is not None:
        return zone.model_copy(
            update={
                "source": "eas-overlay",
                "content": {
                    "active": True,
                    "aria_live": "assertive",
                    "severity": overlay.severity,
                    "title": overlay.title,
                    "message": overlay.message,
                },
            }
        )
    return zone.model_copy(
        update={
            "source": "no-active-alert",
            "content": {"active": False, "aria_live": "assertive"},
        }
    )


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


# ---------------------------------------------------------------------------
# Shared resolvers (WP-06 non-negotiable: no shipping production path exposes
# invented content). Every public GET route that carries feed, bulletin, or
# ticker data goes through exactly one of these three functions, so a station
# with nothing configured gets an honest empty result everywhere, a
# durable-store-backed station sees the same data on every route that shows
# it, and the sample content is reachable ONLY behind
# CIVICCAST_CG_DEMO_FEEDS=1 -- never as an unconditional no-store fallback.
# ---------------------------------------------------------------------------


def _resolve_feed_catalog(service: Any, channel_id: str) -> CgFeedCatalog:
    if service is not None:
        return cast(CgFeedCatalog, service.feed_catalog(channel_id))
    if _cg_demo_feeds_enabled():
        return build_feed_catalog(channel_id=channel_id)
    return _empty_feed_catalog(channel_id)


def _resolve_public_approved_bulletins(store: Any, channel_id: str) -> CgBulletinQueue:
    if store is not None:
        return _durable_approved_bulletins(store, channel_id)
    if _cg_demo_feeds_enabled():
        sample = build_bulletin_queue(channel_id=channel_id)
        return CgBulletinQueue(
            generated_at=sample.generated_at,
            channel_id=sample.channel_id,
            submissions=_approved_submissions(sample.submissions),
            approved_zone_items=sample.approved_zone_items,
            proof_boundary="approved-community-bulletins-to-public-cg-zone-items",
        )
    return _empty_bulletin_queue(channel_id)


def _resolve_staff_bulletin_queue(store: Any, channel_id: str) -> CgBulletinQueue:
    # Unfiltered (unlike the public/approved resolver above): this backs the
    # operator moderation queue, which must show submitted/needs_changes rows
    # too, not just accepted/scheduled ones.
    if store is not None:
        return _queue_from_durable(store, channel_id)
    if _cg_demo_feeds_enabled():
        return build_bulletin_queue(channel_id=channel_id)
    return _empty_bulletin_queue(channel_id)


def _resolve_durable_snapshot(
    channel_id: str,
    template_id: str | None,
    feeds: CgFeedCatalog,
    bulletins: CgBulletinQueue,
    *,
    service: Any,
    eas_provider: EmergencyOverlayProvider | None,
) -> MultiZoneCgSnapshot:
    """Build the multi-zone snapshot with EVERY zone sourced from durable
    station data or honestly marked otherwise (WP-06 non-negotiable: no
    shipping production path exposes invented content) --
    ``build_multi_zone_snapshot()`` only supplies the template's zone
    *layout* (kinds/regions/order, which are configuration choices, not
    invented facts); this function replaces every zone's content:

    * ``ticker`` / ``schedule``: the already-resolved durable feed catalog +
      approved bulletin queue, and the station's real program-log
      occurrences (``CgBoardService.upcoming()``) -- empty when nothing is
      configured, or (only under CIVICCAST_CG_DEMO_FEEDS=1, and only when no
      durable service is wired) the historical sample.
    * ``primary``: genuine platform copy (the same text ``/idle`` returns),
      never demo-gated -- it isn't a stand-in for real configuration.
    * ``logo``: the channel's real branding profile.
    * ``audio``: an honest disabled-future-control state (WP-06 plan item 5).
    * ``alert``: the real EAS overlay when wired and active, else honestly
      inactive.

    So /snapshot and the display.snapshot field never disagree and neither
    ever shows invented content by default.
    """

    base = build_multi_zone_snapshot(channel_id=channel_id, template_id=template_id)
    now = datetime.now(UTC)

    upcoming: list[tuple[datetime, str]] | None
    if service is not None:
        upcoming = cast("list[tuple[datetime, str]]", service.upcoming(channel_id))
    elif _cg_demo_feeds_enabled():
        upcoming = None  # sentinel: keep the template's static demo sample below
    else:
        upcoming = []

    zones: list[CgZone] = []
    for zone in base.zones:
        if zone.kind == "ticker":
            zones.append(_durable_ticker_zone(zone, feeds, bulletins))
        elif zone.kind == "schedule":
            zones.append(
                zone if upcoming is None else _durable_schedule_zone(zone, upcoming, now=now)
            )
        elif zone.kind == "primary":
            zones.append(_honest_primary_zone(zone))
        elif zone.kind == "logo":
            zones.append(_durable_logo_zone(zone, channel_id))
        elif zone.kind == "audio":
            zones.append(_honest_audio_zone(zone))
        elif zone.kind == "alert":
            zones.append(_resolve_alert_zone(zone, channel_id, eas_provider))
        else:
            zones.append(zone)
    return base.model_copy(update={"zones": zones})


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
    service: Any = Depends(get_cg_board_service),
    bulletin_store: Any = Depends(get_cg_bulletin_store),
    eas_provider: EmergencyOverlayProvider | None = Depends(get_eas_overlay_provider),
) -> MultiZoneCgSnapshot:
    # WP-06 non-negotiable follow-up: this standalone endpoint used to call
    # build_multi_zone_snapshot() directly, which always carried the static
    # sample ticker/schedule/logo/audio content regardless of station
    # configuration. Every zone is now resolved the same way the /display
    # endpoint's embedded snapshot is, so the two never disagree.
    feeds = _resolve_feed_catalog(service, channel_id)
    bulletins = _resolve_public_approved_bulletins(bulletin_store, channel_id)
    return _resolve_durable_snapshot(
        channel_id, template_id, feeds, bulletins, service=service, eas_provider=eas_provider
    )


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
    return _resolve_feed_catalog(service, channel_id)


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
    # WP-06 non-negotiable follow-up: the no-store fallback used to return
    # the CA-3 sample queue unconditionally. It now falls to an honest empty
    # queue unless CIVICCAST_CG_DEMO_FEEDS=1 is explicitly set.
    return _resolve_public_approved_bulletins(store, channel_id)


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
    # WP-06 non-negotiable follow-up: the no-store fallback used to return
    # the CA-3 sample queue unconditionally, even to an authenticated staff
    # session on a station that hasn't wired durable storage. It now falls to
    # an honest empty queue unless CIVICCAST_CG_DEMO_FEEDS=1 is set.
    return _resolve_staff_bulletin_queue(store, channel_id)


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
    eas_provider: EmergencyOverlayProvider | None = Depends(get_eas_overlay_provider),
) -> CgPortalDisplay:
    # WP-06 + follow-ups: feed_catalog, approved_bulletins, and every zone of
    # the snapshot are resolved the same way their standalone endpoints above
    # are (/feeds, /bulletins, /snapshot), so they never disagree. The
    # template library, render plan, and overlay contract are unchanged (out
    # of scope; no example.invalid / sample content lives there).
    display = build_portal_display(channel_id=channel_id, template_id=template_id)

    # Every field this work touches is resolved through the SAME shared
    # helpers the standalone /feeds, /bulletins, and /snapshot endpoints use
    # above, so this contract can never drift from them.
    feeds = _resolve_feed_catalog(service, channel_id)
    bulletins = _resolve_public_approved_bulletins(bulletin_store, channel_id)
    snapshot = _resolve_durable_snapshot(
        channel_id, template_id, feeds, bulletins, service=service, eas_provider=eas_provider
    )

    return display.model_copy(
        update={"feed_catalog": feeds, "approved_bulletins": bulletins, "snapshot": snapshot}
    )
