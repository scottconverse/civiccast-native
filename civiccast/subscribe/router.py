# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for v0.8 resident subscriptions."""

from __future__ import annotations

import os
from typing import cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from civiccast.auth.roles import require_any_role
from civiccast.platform.stores import resolve_app_store
from civiccast.subscribe.models import (
    NotificationDispatchResponse,
    NotificationPayload,
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


# Hosts trusted as "this station, running locally" -- matches
# civiccast.activitypub.config._normalize_base_url's own loopback allowlist,
# which faced the same problem (a public link built from an env value or a
# request Host header must never be allowed to point somewhere the operator
# didn't configure).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def _resolve_public_base_url(request: Request) -> str:
    """Resolve the station's real public base URL for public feed links.

    Never invents a host. In priority order:

    1. ``CIVICCAST_PUBLIC_BASE_URL`` (the same env var
       ``civiccast.activitypub.config.load_activitypub_config`` falls back to
       for its own ``base_url``) -- the operator's configured real public
       address, when it parses as a valid absolute http(s) URL.
    2. The incoming request's own scheme+host, but ONLY when that host is
       loopback/testserver (local dev/test) or matches the configured
       station host above -- an arbitrary proxied ``Host`` header must never
       be trusted to build a link a public RSS reader will follow.

    Returns ``""`` when neither is available, so the caller renders a
    relative link instead of fabricating one.
    """
    configured = os.environ.get("CIVICCAST_PUBLIC_BASE_URL", "").strip().rstrip("/")
    configured_host: str | None = None
    if configured:
        parsed_configured = urlparse(configured)
        if parsed_configured.scheme in {"http", "https"} and parsed_configured.netloc:
            configured_host = parsed_configured.hostname
        else:
            configured = ""

    if configured:
        return configured

    request_base = str(request.base_url).rstrip("/")
    request_host = urlparse(request_base).hostname
    if request_host and (request_host in _LOOPBACK_HOSTS or request_host == configured_host):
        return request_base

    return ""


@public_router.get(
    "/rss/{target_type}/{target_id}.xml",
    summary="Read a public no-PII subscription RSS feed",
)
def rss_feed(target_type: str, target_id: str, request: Request) -> Response:
    if target_type not in {"channel", "meeting_body"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RSS feed not found. Use channel or meeting_body feed paths.",
        )
    # There is no published-recording resolver wired to this route yet (that
    # would mean joining subscribe targets against civiccast.publish's real
    # per-asset records, out of scope for this fix) -- serving a single
    # invented "Example CivicCast recording" item with a fake
    # https://portal.example link on every request looked like a real
    # published item to any reader/aggregator, which it never was. Until a
    # real resolver exists, this is an honest, valid, empty feed rather than
    # a fabricated one.
    xml = subscription_rss(target_type, target_id, [], base_url=_resolve_public_base_url(request))
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
