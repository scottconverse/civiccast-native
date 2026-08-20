# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for v0.8 resident subscriptions."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from civiccast.auth.roles import require_any_role
from civiccast.platform.stores import resolve_app_store
from civiccast.subscribe.models import (
    NotificationDispatchResponse,
    NotificationPayload,
    RssItem,
    SubscriptionConfirmResponse,
    SubscriptionPublicResponse,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.rate_limit import SubscribeRateLimiter
from civiccast.subscribe.secrets import SubscriptionSecrets, load_subscription_secrets
from civiccast.subscribe.service import (
    confirm_subscription,
    create_email_subscription,
    create_webhook_subscription,
    dispatch_notifications,
    subscription_rss,
    unsubscribe,
)
from civiccast.subscribe.store import SubscribeStore

public_router = APIRouter(prefix="/api/public/subscribe", tags=["public", "subscribe"])
staff_router = APIRouter(prefix="/api/staff/subscribe", tags=["staff", "subscribe"])


def get_subscribe_store(request: Request) -> SubscribeStore:
    return cast(
        SubscribeStore, resolve_app_store(request, "subscribe_store", surface="Subscribe store")
    )


def get_subscribe_secrets(request: Request) -> SubscriptionSecrets:
    configured = getattr(request.app.state, "subscribe_secrets", None)
    return cast(SubscriptionSecrets, configured or load_subscription_secrets())


def get_subscribe_rate_limiter(request: Request) -> SubscribeRateLimiter:
    configured = getattr(request.app.state, "subscribe_rate_limiter", None)
    return cast(SubscribeRateLimiter, configured or SubscribeRateLimiter())


def _enforce_signup_rate_limit(
    request: Request, limiter: SubscribeRateLimiter, *, channel: str
) -> None:
    limit = int(os.environ.get("CIVICCAST_SUBSCRIBE_RATE_LIMIT", "5"))
    window_seconds = int(os.environ.get("CIVICCAST_SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS", "60"))
    client_host = request.client.host if request.client is not None else "unknown"
    if not limiter.allow(f"{channel}:{client_host}", limit=limit, window_seconds=window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many subscription attempts from this address. Wait a minute, then try again."
            ),
        )


@public_router.post(
    "/email",
    response_model=SubscriptionPublicResponse,
    summary="Start email double opt-in subscription",
)
def signup_email(
    payload: SubscriptionSignupRequest,
    request: Request,
    store: SubscribeStore = Depends(get_subscribe_store),
    secrets: SubscriptionSecrets = Depends(get_subscribe_secrets),
    limiter: SubscribeRateLimiter = Depends(get_subscribe_rate_limiter),
) -> SubscriptionPublicResponse:
    _enforce_signup_rate_limit(request, limiter, channel="email")
    return create_email_subscription(payload, store=store, secrets=secrets)


@public_router.post(
    "/webhook",
    response_model=SubscriptionPublicResponse,
    summary="Start webhook subscription opt-in",
)
def signup_webhook(
    payload: SubscriptionWebhookRequest,
    request: Request,
    store: SubscribeStore = Depends(get_subscribe_store),
    secrets: SubscriptionSecrets = Depends(get_subscribe_secrets),
    limiter: SubscribeRateLimiter = Depends(get_subscribe_rate_limiter),
) -> SubscriptionPublicResponse:
    _enforce_signup_rate_limit(request, limiter, channel="webhook")
    return create_webhook_subscription(payload, store=store, secrets=secrets)


@public_router.get(
    "/confirm",
    response_model=SubscriptionConfirmResponse,
    summary="Confirm a double opt-in subscription",
)
def confirm(
    token: str = Query(min_length=1),
    store: SubscribeStore = Depends(get_subscribe_store),
    secrets: SubscriptionSecrets = Depends(get_subscribe_secrets),
) -> SubscriptionConfirmResponse:
    try:
        return confirm_subscription(token, store=store, secrets=secrets)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found. Sign up again to receive a fresh confirmation link.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@public_router.get(
    "/unsubscribe",
    response_model=SubscriptionConfirmResponse,
    summary="Unsubscribe using a signed one-click link",
)
def unsubscribe_link(
    token: str = Query(min_length=1),
    store: SubscribeStore = Depends(get_subscribe_store),
    secrets: SubscriptionSecrets = Depends(get_subscribe_secrets),
) -> SubscriptionConfirmResponse:
    try:
        return unsubscribe(token, store=store, secrets=secrets)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found. Contact the station if notices continue.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@public_router.get(
    "/rss/{target_type}/{target_id}.xml",
    summary="Read a public no-PII subscription RSS feed",
)
def rss_feed(target_type: str, target_id: str) -> Response:
    if target_type not in {"channel", "meeting_body"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RSS feed not found. Use channel or meeting_body feed paths.",
        )
    xml = subscription_rss(
        target_type,
        target_id,
        [
            RssItem(
                title="Example CivicCast recording",
                link=f"https://portal.example/watch/{target_id}",
                guid=f"civiccast:{target_type}:{target_id}:example",
                published_at=datetime.now(UTC),
                description="Subscribe with this RSS feed to receive public recording notices.",
            )
        ],
    )
    return Response(content=xml, media_type="application/rss+xml")


@staff_router.post(
    "/dispatch-test",
    response_model=NotificationDispatchResponse,
    summary="Dispatch deterministic local v0.8 subscription notifications",
    dependencies=[Depends(require_any_role("publish_operator", "support_admin"))],
)
def dispatch_test(
    payload: NotificationPayload,
    target_type: str = "channel",
    target_id: str = "government",
    store: SubscribeStore = Depends(get_subscribe_store),
    secrets: SubscriptionSecrets = Depends(get_subscribe_secrets),
) -> NotificationDispatchResponse:
    return dispatch_notifications(
        payload,
        store=store,
        target_type=target_type,
        target_id=target_id,
        secrets=secrets,
    )
