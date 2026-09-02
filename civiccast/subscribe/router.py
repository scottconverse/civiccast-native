# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for v0.8 resident subscriptions."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from civiccast.auth.roles import require_any_role
from civiccast.installer.station_state import resolve_station_display_name
from civiccast.platform.stores import resolve_app_store
from civiccast.publish.notifications import watch_url_for_asset
from civiccast.publish.targets import (
    ChannelAssociationLookup,
    resolve_public_base_url,
    resolve_publication_targets,
    resolve_station_default_channel_id,
)
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.models import (
    NotificationDispatchResponse,
    NotificationPayload,
    RssItem,
    SubscriptionConfirmResponse,
    SubscriptionPublicResponse,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.outcome_store import NotificationDeliveryStore
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


def get_notification_delivery_store(request: Request) -> NotificationDeliveryStore | None:
    """Resolve the durable subscriber-notification receipt store, or ``None``.

    ``None`` (an app instance without durable storage) does not disable
    delivery: ``deliver_publication_notifications`` falls back to a
    process-local guard. It does mean receipts do not outlive the process,
    which is why the durable store is wired wherever storage exists.

    Defined here rather than in ``civiccast.publish.router`` because the public
    RSS feed needs the sibling target lookup and ``publish.router`` already
    imports this module -- one definition, and the import direction stays
    publish -> subscribe.
    """

    return cast(
        "NotificationDeliveryStore | None",
        resolve_app_store(
            request, "notification_delivery_store", surface="Notification delivery store"
        ),
    )


def get_publication_target_lookup(request: Request) -> ChannelAssociationLookup | None:
    """Resolve the schedule/live channel association for the target resolver."""

    return cast(
        "ChannelAssociationLookup | None",
        resolve_app_store(
            request, "publication_target_lookup", surface="Publication target lookup"
        ),
    )


def get_rss_asset_store(request: Request) -> Any:
    """Resolve the asset store the public RSS feed reads published records from."""

    return resolve_app_store(request, "asset_store", surface="Asset store")


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


#: Most-recent published recordings one feed carries. A civic station's
#: recording history is unbounded; a reader wants the recent record, and an
#: unbounded feed would grow with every meeting ever held.
RSS_FEED_MAX_ITEMS = 50
#: Published rows scanned before target filtering. Bounds the resolver's work
#: for a station whose recent publications are mostly on other channels.
_RSS_SCAN_LIMIT = 400


def _published_rows(asset_store: Any) -> list[StaffAssetRow]:
    """Published, packaged recordings, newest first -- or none, never examples."""

    lister = getattr(asset_store, "list_all", None)
    if lister is None:
        # An app instance whose asset store has no operator-side projection
        # (the ephemeral in-memory VOD store). There is nothing published to
        # report, so the feed is empty -- not seeded with a sample item.
        return []
    rows = cast(list[StaffAssetRow], lister())
    published = [row for row in rows if row.published_at is not None and row.manifest_url]
    return published[:_RSS_SCAN_LIMIT]


@public_router.get(
    "/rss/{target_type}/{target_id}.xml",
    summary="Read a public no-PII subscription RSS feed",
)
def rss_feed(
    target_type: str,
    target_id: str,
    request: Request,
    asset_store: Any = Depends(get_rss_asset_store),
    target_lookup: ChannelAssociationLookup | None = Depends(get_publication_target_lookup),
) -> Response:
    # WP-05 plan item 12. NOTE for future editors: this function's docstring
    # becomes the public OpenAPI description, and
    # `tests/policy/test_lan_only_station_external_dependencies.py` fails the
    # build if /openapi.json names an external host -- so the history of the
    # placeholder link this route used to emit lives here in a comment and in
    # the CHANGELOG, never in the docstring.
    #
    # What was removed: one fabricated item ("Example CivicCast recording")
    # pointing at a placeholder hostname, served for every target on every
    # station in production. What replaced it: real published records,
    # filtered by the same canonical resolver publish delivery uses
    # (civiccast.publish.targets.resolve_publication_targets), so the feed and
    # the notices agree about which recordings belong to a target.
    """Render this target's real published recordings as RSS.

    Items are the station's actual published, packaged recordings for this
    channel or meeting body, newest first, capped at
    :data:`RSS_FEED_MAX_ITEMS`. Links are built from the station's configured
    public base URL (falling back to this request's own origin) and the
    portal's ``#/watch/{asset_id}`` route. A station with nothing published
    yet gets a valid, configured, empty feed.
    """

    if target_type not in {"channel", "meeting_body"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RSS feed not found. Use channel or meeting_body feed paths.",
        )
    # Configured base first; this request's own origin is the fallback, so the
    # feed is always self-consistent and always points at a host that exists.
    base_url = resolve_public_base_url() or str(request.base_url).rstrip("/")
    rows = _published_rows(asset_store)
    channel_ids: dict[str, str] = {}
    if rows and target_lookup is not None:
        channel_ids = target_lookup.channel_ids_for_assets(rows)
    default_channel_id = resolve_station_default_channel_id()

    items: list[RssItem] = []
    for row in rows:
        targets = resolve_publication_targets(
            row,
            channel_id=channel_ids.get(row.asset_id),
            default_channel_id=default_channel_id,
        )
        if not any(
            target.target_type == target_type and target.target_id == target_id
            for target in targets
        ):
            continue
        link = watch_url_for_asset(row.asset_id, public_base_url=base_url)
        if link is None:  # pragma: no cover - base_url is non-empty by construction
            continue
        items.append(
            RssItem(
                title=row.title,
                link=link,
                guid=f"civiccast:asset:{row.asset_id}",
                published_at=cast(datetime, row.published_at),
                description=(row.description or "").strip()
                or f"Public recording published by {resolve_station_display_name()}.",
            )
        )
        if len(items) >= RSS_FEED_MAX_ITEMS:
            break

    xml = subscription_rss(
        target_type,
        target_id,
        items,
        public_base_url=base_url,
        station_name=resolve_station_display_name(),
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
