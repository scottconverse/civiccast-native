# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Public and staff ActivityPub routes for a CivicCast station actor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from civiccast.activitypub.config import ActivityPubConfig
from civiccast.activitypub.models import (
    DeliveryRecord,
    DeliveryRetryRecord,
    FollowerRecord,
    FollowerStatus,
    OutboxRecord,
)
from civiccast.activitypub.rate_limit import InboxRateLimiter
from civiccast.activitypub.remote import (
    ActivityPubDeliveryClient,
    ActivityPubRemoteError,
    RemoteActorFetcher,
)
from civiccast.activitypub.service import (
    ActivityPubBlockedError,
    ActivityPubDisabledError,
    ActivityPubError,
    ActivityPubPolicyError,
    ActivityPubRateLimitError,
    ActivityPubSignatureError,
    actor_document,
    approve_pending_follower,
    block_follower,
    followers_collection,
    handle_inbox_activity,
    nodeinfo_document,
    outbox_collection,
    reject_pending_follower,
    require_authorized_fetch,
    webfinger_document,
)
from civiccast.activitypub.store import ActivityPubStore
from civiccast.auth.roles import require_any_role
from civiccast.platform.stores import resolve_app_store

router = APIRouter(tags=["public", "activitypub"])

_MODERATION_ROLES = ("publish_operator", "support_admin")


def _base_url(request: Request) -> str:
    config = get_activitypub_config(request)
    return config.base_url or str(request.base_url).rstrip("/")


def _path_and_query(request: Request) -> str:
    path = request.url.path or "/"
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path


def get_activitypub_config(request: Request) -> ActivityPubConfig:
    return cast(ActivityPubConfig, request.app.state.activitypub_config)


def _require_activitypub_enabled(config: ActivityPubConfig) -> None:
    if config.federation_mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "ActivityPub federation is disabled for this CivicCast deployment. "
                "Set CIVICCAST_ACTIVITYPUB_MODE and key material before exposing federation."
            ),
        )


def get_activitypub_store(request: Request) -> ActivityPubStore:
    return cast(
        ActivityPubStore,
        resolve_app_store(request, "activitypub_store", surface="ActivityPub store"),
    )


def get_activitypub_rate_limiter(request: Request) -> InboxRateLimiter:
    return cast(InboxRateLimiter, request.app.state.activitypub_rate_limiter)


def get_activitypub_actor_fetcher(request: Request) -> RemoteActorFetcher:
    return cast(RemoteActorFetcher, request.app.state.activitypub_actor_fetcher)


def get_activitypub_delivery_client(request: Request) -> ActivityPubDeliveryClient:
    return cast(ActivityPubDeliveryClient, request.app.state.activitypub_delivery_client)


def _headers(request: Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.headers.items()}


def _authorized_fetch_if_needed(request: Request) -> None:
    config = get_activitypub_config(request)
    try:
        require_authorized_fetch(
            method=request.method,
            path_and_query=_path_and_query(request),
            headers=_headers(request),
            base_url=_base_url(request),
            config=config,
            actor_fetcher=get_activitypub_actor_fetcher(request),
        )
    except ActivityPubSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ActivityPubBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActivityPubPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _activity_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        media_type="application/activity+json",
    )


@router.get("/.well-known/webfinger", summary="Discover the CivicCast ActivityPub actor")
def webfinger(
    request: Request,
    resource: str = Query(..., min_length=1),
) -> JSONResponse:
    config = get_activitypub_config(request)
    _require_activitypub_enabled(config)
    host = cast(str, urlparse(_base_url(request)).hostname)
    expected = f"acct:{config.handle}@{host}"
    if resource != expected:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "ActivityPub account not found. Use the station account shown in "
                "the CivicCast federation settings."
            ),
        )
    return _activity_json(
        webfinger_document(base_url=_base_url(request), host=host, config=config),
        status_code=200,
    )


@router.get("/.well-known/nodeinfo", summary="Discover CivicCast NodeInfo")
def nodeinfo_links(request: Request) -> dict[str, Any]:
    _require_activitypub_enabled(get_activitypub_config(request))
    return {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": f"{_base_url(request)}/nodeinfo/2.0",
            }
        ]
    }


@router.get("/nodeinfo/2.0", summary="Read CivicCast local federation metadata")
def nodeinfo(request: Request) -> dict[str, Any]:
    _require_activitypub_enabled(get_activitypub_config(request))
    return nodeinfo_document(base_url=_base_url(request))


@router.get("/ap/actor", summary="Read the CivicCast station ActivityPub actor")
def activitypub_actor(request: Request) -> JSONResponse:
    _require_activitypub_enabled(get_activitypub_config(request))
    _authorized_fetch_if_needed(request)
    return _activity_json(
        actor_document(base_url=_base_url(request), config=get_activitypub_config(request))
    )


@router.post("/ap/inbox", summary="Receive ActivityPub Follow and Undo requests")
async def activitypub_inbox(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        activity = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ActivityPub inbox body must be valid JSON.",
        ) from exc
    if not isinstance(activity, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ActivityPub inbox body must be a JSON object.",
        )
    try:
        status_code, payload = handle_inbox_activity(
            activity=activity,
            raw_body=raw_body,
            method=request.method,
            path_and_query=_path_and_query(request),
            headers=_headers(request),
            base_url=_base_url(request),
            config=get_activitypub_config(request),
            store=get_activitypub_store(request),
            rate_limiter=get_activitypub_rate_limiter(request),
            actor_fetcher=get_activitypub_actor_fetcher(request),
            delivery_client=get_activitypub_delivery_client(request),
        )
    except ActivityPubDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActivityPubBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActivityPubRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ActivityPubSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ActivityPubPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActivityPubRemoteError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ActivityPubError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _activity_json(payload, status_code=status_code)


@router.get("/ap/followers", summary="Read accepted ActivityPub followers")
def activitypub_followers(request: Request) -> JSONResponse:
    _require_activitypub_enabled(get_activitypub_config(request))
    _authorized_fetch_if_needed(request)
    return _activity_json(
        followers_collection(base_url=_base_url(request), store=get_activitypub_store(request))
    )


@router.get("/ap/outbox", summary="Read local CivicCast ActivityPub outbox")
def activitypub_outbox(request: Request) -> JSONResponse:
    _require_activitypub_enabled(get_activitypub_config(request))
    _authorized_fetch_if_needed(request)
    return _activity_json(
        outbox_collection(base_url=_base_url(request), store=get_activitypub_store(request))
    )


class FollowerModerationRequest(BaseModel):
    """Staff request to approve or block a remote ActivityPub follower."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(..., min_length=1, max_length=500)


class ActivityPubFollowerCounts(BaseModel):
    """Follower moderation counts grouped by durable status."""

    model_config = ConfigDict(extra="forbid")

    pending: int
    accepted: int
    blocked: int
    rejected: int
    removed: int


class ActivityPubStatusResponse(BaseModel):
    """Staff-visible ActivityPub status without secret key material."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    mode: str
    handle: str
    base_url: str
    actor_url: str | None
    authorized_fetch: bool
    blocked_instances: list[str]
    allowed_instances: list[str]
    followers: ActivityPubFollowerCounts
    outbox_items: int
    delivery_attempts: int


class ActivityPubFollowersResponse(BaseModel):
    """Staff list of ActivityPub followers for moderation."""

    model_config = ConfigDict(extra="forbid")

    followers: list[FollowerRecord]


class ActivityPubModerationResponse(BaseModel):
    """Staff moderation result for one ActivityPub follower."""

    model_config = ConfigDict(extra="forbid")

    follower: FollowerRecord


class ActivityPubOutboxResponse(BaseModel):
    """Staff list of local ActivityPub outbox activities."""

    model_config = ConfigDict(extra="forbid")

    outbox: list[OutboxRecord]


class ActivityPubDeliveriesResponse(BaseModel):
    """Staff list of signed ActivityPub delivery attempts."""

    model_config = ConfigDict(extra="forbid")

    deliveries: list[DeliveryRecord]


@router.get(
    "/api/staff/activitypub/status",
    response_model=ActivityPubStatusResponse,
    summary="Read ActivityPub federation status and policy",
)
def staff_activitypub_status(request: Request) -> ActivityPubStatusResponse:
    config = get_activitypub_config(request)
    store = get_activitypub_store(request)
    enabled = config.federation_mode != "disabled"
    return ActivityPubStatusResponse(
        enabled=enabled,
        mode=config.federation_mode,
        handle=config.handle,
        base_url=config.base_url,
        actor_url=f"{config.base_url}/ap/actor" if enabled and config.base_url else None,
        authorized_fetch=config.authorized_fetch,
        blocked_instances=sorted(config.blocked_instances),
        allowed_instances=sorted(config.allowed_instances),
        followers=ActivityPubFollowerCounts(
            accepted=len(store.list_followers(status="accepted")),
            pending=len(store.list_followers(status="pending")),
            blocked=len(store.list_followers(status="blocked")),
            rejected=len(store.list_followers(status="rejected")),
            removed=len(store.list_followers(status="removed")),
        ),
        outbox_items=len(store.list_outbox()),
        delivery_attempts=len(store.list_deliveries()),
    )


@router.get(
    "/api/staff/activitypub/followers",
    response_model=ActivityPubFollowersResponse,
    summary="List ActivityPub followers for operator moderation",
)
def staff_activitypub_followers(
    request: Request,
    follower_status: FollowerStatus = Query("pending", alias="status"),
) -> ActivityPubFollowersResponse:
    followers = get_activitypub_store(request).list_followers(status=follower_status)
    return ActivityPubFollowersResponse(followers=followers)


@router.post(
    "/api/staff/activitypub/followers/approve",
    response_model=ActivityPubModerationResponse,
    summary="Approve a pending ActivityPub follower and deliver signed Accept",
    dependencies=[Depends(require_any_role(*_MODERATION_ROLES))],
)
def staff_activitypub_approve_follower(
    request: Request,
    payload: FollowerModerationRequest,
) -> ActivityPubModerationResponse:
    try:
        follower = approve_pending_follower(
            actor=payload.actor,
            base_url=_base_url(request),
            config=get_activitypub_config(request),
            store=get_activitypub_store(request),
            delivery_client=get_activitypub_delivery_client(request),
        )
    except ActivityPubError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ActivityPubRemoteError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ActivityPubModerationResponse(follower=follower)


@router.post(
    "/api/staff/activitypub/followers/reject",
    response_model=ActivityPubModerationResponse,
    summary="Reject a pending ActivityPub follower and deliver signed Reject",
    dependencies=[Depends(require_any_role(*_MODERATION_ROLES))],
)
def staff_activitypub_reject_follower(
    request: Request,
    payload: FollowerModerationRequest,
) -> ActivityPubModerationResponse:
    try:
        follower = reject_pending_follower(
            actor=payload.actor,
            base_url=_base_url(request),
            store=get_activitypub_store(request),
            delivery_client=get_activitypub_delivery_client(request),
        )
    except ActivityPubError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ActivityPubRemoteError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ActivityPubModerationResponse(follower=follower)


@router.post(
    "/api/staff/activitypub/followers/block",
    response_model=ActivityPubModerationResponse,
    summary="Block an ActivityPub follower",
    dependencies=[Depends(require_any_role(*_MODERATION_ROLES))],
)
def staff_activitypub_block_follower(
    request: Request,
    payload: FollowerModerationRequest,
) -> ActivityPubModerationResponse:
    try:
        follower = block_follower(actor=payload.actor, store=get_activitypub_store(request))
    except ActivityPubError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ActivityPubModerationResponse(follower=follower)


@router.get(
    "/api/staff/activitypub/outbox",
    response_model=ActivityPubOutboxResponse,
    summary="List local ActivityPub outbox activities for staff evidence",
)
def staff_activitypub_outbox(request: Request) -> ActivityPubOutboxResponse:
    return ActivityPubOutboxResponse(outbox=get_activitypub_store(request).list_outbox())


@router.get(
    "/api/staff/activitypub/deliveries",
    response_model=ActivityPubDeliveriesResponse,
    summary="List ActivityPub signed delivery attempts for staff evidence",
)
def staff_activitypub_deliveries(
    request: Request,
    activity_id: str | None = Query(None),
) -> ActivityPubDeliveriesResponse:
    return ActivityPubDeliveriesResponse(
        deliveries=get_activitypub_store(request).list_deliveries(activity_id=activity_id)
    )


class ActivityPubDeliveryRetriesResponse(BaseModel):
    """Staff view of the delivery retry queue, including dead letters."""

    model_config = ConfigDict(extra="forbid")

    delivery_retries: list[DeliveryRetryRecord]


@router.get(
    "/api/staff/activitypub/delivery-retries",
    response_model=ActivityPubDeliveryRetriesResponse,
    summary="List the ActivityPub delivery retry queue (including dead letters)",
)
def staff_activitypub_delivery_retries(request: Request) -> ActivityPubDeliveryRetriesResponse:
    return ActivityPubDeliveryRetriesResponse(
        delivery_retries=get_activitypub_store(request).list_delivery_retries()
    )


@router.post(
    "/api/staff/activitypub/delivery-retries/{retry_id}/replay",
    response_model=DeliveryRetryRecord,
    summary="Replay a dead-lettered ActivityPub delivery",
    dependencies=[Depends(require_any_role(*_MODERATION_ROLES))],
    responses={
        404: {"description": "Unknown delivery retry id"},
        409: {"description": "The retry is not dead-lettered"},
    },
)
def staff_replay_delivery_retry(retry_id: str, request: Request) -> DeliveryRetryRecord:
    """Operator repair surface (Beta B2): grant a dead-lettered delivery a
    fresh attempt budget. The retry worker re-delivers it on its next scan;
    confirm the follower's instance is reachable again first (see
    ``last_error``)."""

    store = get_activitypub_store(request)
    record = store.get_delivery_retry(retry_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown delivery retry: {retry_id}",
        )
    if record.state != "dead_letter":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Delivery retry {retry_id} is {record.state!r}; replay applies "
                "only to dead-lettered deliveries."
            ),
        )
    now = datetime.now(UTC)
    replayed = record.model_copy(
        update={
            "state": "pending",
            "attempts": 0,
            "next_attempt_at": now,
            "updated_at": now,
        }
    )
    return store.save_delivery_retry(replayed)
