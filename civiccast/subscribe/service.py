# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Subscription signup, confirmation, RSS, and notification orchestration."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from civiccast.platform.providers import (
    PROVIDER_KIND_MAIL,
    PROVIDER_KIND_WEBHOOK,
    default_registry,
)
from civiccast.subscribe.crypto import (
    SecretBox,
    signed_token,
)
from civiccast.subscribe.delivery import LocalMailbox, LocalWebhookClient, delivery_proof
from civiccast.subscribe.models import (
    NotificationDelivery,
    NotificationDispatchResponse,
    NotificationPayload,
    RssItem,
    SubscriptionConfirmResponse,
    SubscriptionPublicResponse,
    SubscriptionRecord,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.retry_worker import enqueue_failed_webhook_delivery
from civiccast.subscribe.rss import render_rss
from civiccast.subscribe.secrets import (
    SubscriptionSecrets,
    load_subscription_secrets,
    verify_subscription_token,
)
from civiccast.subscribe.store import SubscribeStore


def _subscription_id(channel: str, handle: str, target_type: str, target_id: str) -> str:
    digest = hashlib.sha256(f"{channel}:{handle}:{target_type}:{target_id}".encode()).hexdigest()
    return f"sub-{digest[:24]}"


def _public_response(record: SubscriptionRecord) -> SubscriptionPublicResponse:
    return SubscriptionPublicResponse(
        subscription_id=record.subscription_id,
        channel=record.channel,
        target_type=record.target_type,
        target_id=record.target_id,
        status=record.status,
        message=(
            "Subscription is waiting for confirmation."
            if record.status == "pending_confirmation"
            else "Subscription is active."
            if record.status == "confirmed"
            else "Subscription is unsubscribed."
        ),
        next_step=(
            "Open the confirmation link sent to this address."
            if record.status == "pending_confirmation"
            else "You will receive notifications when matching recordings publish."
            if record.status == "confirmed"
            else "Sign up again if you want to receive future notices."
        ),
        # EMAIL: never echoed (GauntletGate rc18 QA-1, Critical). This field
        # used to carry the live confirmation token whenever the subscription
        # was pending, so the requester could confirm an address they had no
        # access to -- two HTTP calls to subscribe a stranger to a government
        # notification list. Possession of the token IS the proof of inbox
        # access; handing it back to whoever asked destroys the only thing
        # double opt-in checks. The token still reaches the mail body, which is
        # the one place it belongs. The paywall module's magic-link route has
        # always done this correctly and says so in its docstring.
        #
        # WEBHOOK: still echoed, deliberately and narrowly. Unlike email,
        # `create_webhook_subscription` delivers NOTHING out of band -- there is
        # no callback to the registered URL -- so the response body is the only
        # place the token exists. Blanking it here would not harden the webhook
        # flow, it would break confirmation outright. That leaves webhook
        # "confirmation" proving nothing about URL ownership, which is a real
        # but SEPARATE gap: closing it needs a delivery mechanism, not a field
        # change, and inventing one inside a Critical fix would be scope creep.
        # Recorded in the rc18 verification record instead of silently half-done.
        confirmation_token=(
            record.confirmation_token
            if record.status == "pending_confirmation" and record.channel != "email"
            else None
        ),
        unsubscribe_token=record.unsubscribe_token,
    )


def create_email_subscription(
    request: SubscriptionSignupRequest,
    *,
    store: SubscribeStore,
    secrets: SubscriptionSecrets | None = None,
    secret_box: SecretBox | None = None,
    mailbox: LocalMailbox | None = None,
) -> SubscriptionPublicResponse:
    subscription_secrets = secrets or load_subscription_secrets()
    box = secret_box or subscription_secrets.secret_box
    # Default mail client resolves through the provider registry (Stage C);
    # the shipped default stays the in-memory LocalMailbox mock.
    mail = mailbox or default_registry().resolve(PROVIDER_KIND_MAIL)
    subscription_id = _subscription_id(
        "email", request.email, request.target_type, request.target_id
    )
    confirmation_token = signed_token(
        {"subscription_id": subscription_id, "action": "confirm"},
        subscription_secrets.token_secret,
    )
    unsubscribe_token = signed_token(
        {"subscription_id": subscription_id, "action": "unsubscribe"},
        subscription_secrets.token_secret,
    )
    record = SubscriptionRecord(
        subscription_id=subscription_id,
        channel="email",
        encrypted_subscriber_handle=box.seal(request.email, aad=subscription_id),
        target_type=request.target_type,
        target_id=request.target_id,
        status="pending_confirmation",
        confirmation_token=confirmation_token,
        unsubscribe_token=unsubscribe_token,
        created_at=datetime.now(UTC),
    )
    store.create(record)
    mail.send_confirmation(
        email=request.email,
        confirmation_url=f"/subscribe/confirm?token={confirmation_token}",
    )
    return _public_response(record)


def create_webhook_subscription(
    request: SubscriptionWebhookRequest,
    *,
    store: SubscribeStore,
    secrets: SubscriptionSecrets | None = None,
    secret_box: SecretBox | None = None,
) -> SubscriptionPublicResponse:
    subscription_secrets = secrets or load_subscription_secrets()
    box = secret_box or subscription_secrets.secret_box
    handle = str(request.webhook_url)
    subscription_id = _subscription_id("webhook", handle, request.target_type, request.target_id)
    webhook_secret = hashlib.sha256(f"{subscription_id}:webhook".encode()).hexdigest()
    confirmation_token = signed_token(
        {"subscription_id": subscription_id, "action": "confirm"},
        subscription_secrets.token_secret,
    )
    unsubscribe_token = signed_token(
        {"subscription_id": subscription_id, "action": "unsubscribe"},
        subscription_secrets.token_secret,
    )
    record = SubscriptionRecord(
        subscription_id=subscription_id,
        channel="webhook",
        encrypted_subscriber_handle=box.seal(handle, aad=subscription_id),
        encrypted_webhook_secret=box.seal(webhook_secret, aad=f"{subscription_id}:secret"),
        target_type=request.target_type,
        target_id=request.target_id,
        status="pending_confirmation",
        confirmation_token=confirmation_token,
        unsubscribe_token=unsubscribe_token,
        created_at=datetime.now(UTC),
    )
    store.create(record)
    return _public_response(record)


def confirm_subscription(
    token: str, *, store: SubscribeStore, secrets: SubscriptionSecrets | None = None
) -> SubscriptionConfirmResponse:
    payload = verify_subscription_token(token, secrets or load_subscription_secrets())
    subscription_id = payload.get("subscription_id")
    if payload.get("action") != "confirm" or not isinstance(subscription_id, str):
        raise ValueError("Confirmation link is invalid. Request a new signup link.")
    record = store.get(subscription_id)
    if record is None:
        raise KeyError(subscription_id)
    if record.status == "confirmed":
        return SubscriptionConfirmResponse(
            subscription_id=record.subscription_id,
            status=record.status,
            message="This subscription was already confirmed.",
            next_step="No action is needed. Future matching recordings will send a notice.",
        )
    updated = record.model_copy(update={"status": "confirmed", "confirmed_at": datetime.now(UTC)})
    store.update(updated)
    return SubscriptionConfirmResponse(
        subscription_id=updated.subscription_id,
        status=updated.status,
        message="Subscription confirmed.",
        next_step="You will receive a notice when a matching recording publishes.",
    )


def unsubscribe(
    token: str, *, store: SubscribeStore, secrets: SubscriptionSecrets | None = None
) -> SubscriptionConfirmResponse:
    payload = verify_subscription_token(token, secrets or load_subscription_secrets())
    subscription_id = payload.get("subscription_id")
    if payload.get("action") != "unsubscribe" or not isinstance(subscription_id, str):
        raise ValueError("Unsubscribe link is invalid. Request a new link from the station.")
    record = store.get(subscription_id)
    if record is None:
        raise KeyError(subscription_id)
    updated = record.model_copy(
        update={"status": "unsubscribed", "unsubscribed_at": datetime.now(UTC)}
    )
    store.update(updated)
    return SubscriptionConfirmResponse(
        subscription_id=updated.subscription_id,
        status=updated.status,
        message="Subscription unsubscribed.",
        next_step="You will not receive future notices for this subscription.",
    )


def dispatch_notifications(
    payload: NotificationPayload,
    *,
    store: SubscribeStore,
    target_type: str = "channel",
    target_id: str = "government",
    secrets: SubscriptionSecrets | None = None,
    secret_box: SecretBox | None = None,
    mailbox: LocalMailbox | None = None,
    webhook_client: LocalWebhookClient | None = None,
) -> NotificationDispatchResponse:
    subscription_secrets = secrets or load_subscription_secrets()
    box = secret_box or subscription_secrets.secret_box
    # Defaults resolve through the provider registry (Stage C); the shipped
    # defaults stay the in-memory LocalMailbox/LocalWebhookClient mocks.
    mail = mailbox or default_registry().resolve(PROVIDER_KIND_MAIL)
    webhooks = webhook_client or default_registry().resolve(PROVIDER_KIND_WEBHOOK)
    deliveries: list[NotificationDelivery] = []
    failed = 0
    for subscription in store.list_confirmed_for_target(
        target_type=target_type, target_id=target_id
    ):
        handle = box.open(
            subscription.encrypted_subscriber_handle, aad=subscription.subscription_id
        )
        if subscription.channel == "email":
            message_id = mail.send_notification(email=handle, payload=payload)
            deliveries.append(
                delivery_proof(subscription=subscription, payload=payload, message=message_id)
            )
        else:
            secret = box.open(
                subscription.encrypted_webhook_secret or "",
                aad=f"{subscription.subscription_id}:secret",
            )
            try:
                signature = webhooks.post(url=handle, payload=payload, secret=secret)
            except Exception as exc:
                # Issue #111: a failed real delivery is queued durably and the
                # retry worker re-delivers with backoff; never claim "sent".
                failed += 1
                status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                enqueue_failed_webhook_delivery(
                    store=store,
                    subscription_id=subscription.subscription_id,
                    payload=payload.model_dump(mode="json"),
                    status_code=status_code,
                    error=str(exc),
                )
                deliveries.append(
                    delivery_proof(
                        subscription=subscription,
                        payload=payload,
                        message="webhook delivery failed; queued for retry",
                        status="failed",
                    )
                )
                continue
            deliveries.append(
                delivery_proof(
                    subscription=subscription,
                    payload=payload,
                    message="webhook delivered with HMAC signature",
                    signature=signature,
                )
            )
    return NotificationDispatchResponse(
        asset_id=payload.asset_id,
        sent=len(deliveries) - failed,
        failed=failed,
        deliveries=deliveries,
    )


def subscription_rss(
    target_type: str, target_id: str, items: list[RssItem], *, base_url: str = ""
) -> str:
    """Render the public subscription RSS feed.

    ``base_url`` is the station's real public base URL (see
    ``civiccast.subscribe.router._resolve_public_base_url``) -- never an
    invented host. When it is empty (nothing configured and the request
    could not be trusted as the station's own host), the feed's channel
    link is relative (``/{target_type}/{target_id}``) rather than a
    fabricated absolute URL.
    """
    label = "Channel" if target_type == "channel" else "Meeting body"
    link = f"{base_url}/{target_type}/{target_id}" if base_url else f"/{target_type}/{target_id}"
    return render_rss(
        title=f"CivicCast {label} {target_id}",
        link=link,
        description="Public CivicCast recording notifications. RSS has no stored PII.",
        items=items,
    )
