# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Subscription signup, confirmation, RSS, and notification orchestration."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
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
from civiccast.subscribe.delivery import (
    DeliveryRecorder,
    LocalMailbox,
    LocalWebhookClient,
    delivery_error_code,
    delivery_proof,
    redact_delivery_detail,
)
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

_LOG = logging.getLogger(__name__)


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


def _intended_deliveries(
    store: SubscribeStore, targets: Sequence[tuple[str, str]]
) -> list[tuple[SubscriptionRecord, str, str]]:
    """Confirmed subscriptions across ``targets``, deduplicated by subscription.

    WP-05 plan item 1: a resident subscribed to both the channel and the
    meeting body is one recipient, not two. Targets are visited in the order
    given (the resolver's deterministic order), so the same subscription always
    binds to the same target -- which keeps its logical delivery key stable
    across runs, which is what makes re-approval idempotent.
    """

    seen: set[str] = set()
    intended: list[tuple[SubscriptionRecord, str, str]] = []
    for target_type, target_id in targets:
        for subscription in store.list_confirmed_for_target(
            target_type=target_type, target_id=target_id
        ):
            if subscription.subscription_id in seen:
                continue
            seen.add(subscription.subscription_id)
            intended.append((subscription, target_type, target_id))
    return intended


def dispatch_notifications(
    payload: NotificationPayload,
    *,
    store: SubscribeStore,
    target_type: str = "channel",
    target_id: str = "government",
    targets: Sequence[tuple[str, str]] | None = None,
    secrets: SubscriptionSecrets | None = None,
    secret_box: SecretBox | None = None,
    mailbox: LocalMailbox | None = None,
    webhook_client: LocalWebhookClient | None = None,
    recorder: DeliveryRecorder | None = None,
) -> NotificationDispatchResponse:
    """Send ``payload`` to every confirmed subscription of the given targets.

    ``targets`` (WP-05) generalises the single ``target_type``/``target_id``
    pair to the canonical publication targets an asset resolves to; the
    single-pair signature is unchanged for the staff dispatch-test route.

    ``recorder`` is the durable-outcome hook. When supplied, a recipient it
    reports as already delivered is skipped rather than sent again, and every
    attempt is persisted as it happens -- so an exception on recipient three
    cannot erase the receipts for recipients one and two.

    Every per-recipient step runs inside its own ``try``: a failure to open a
    sealed handle, an SMTP refusal, or a webhook error marks that recipient and
    moves on. One bad recipient never stops the rest (plan item 7). Failure
    text is redacted before it is persisted or logged.
    """
    subscription_secrets = secrets or load_subscription_secrets()
    box = secret_box or subscription_secrets.secret_box
    # Defaults resolve through the provider registry (Stage C); the shipped
    # defaults stay the in-memory LocalMailbox/LocalWebhookClient mocks.
    mail = mailbox or default_registry().resolve(PROVIDER_KIND_MAIL)
    webhooks = webhook_client or default_registry().resolve(PROVIDER_KIND_WEBHOOK)
    resolved_targets = list(targets) if targets else [(target_type, target_id)]
    deliveries: list[NotificationDelivery] = []
    sent = 0
    failed = 0
    skipped = 0

    for subscription, subscription_target_type, subscription_target_id in _intended_deliveries(
        store, resolved_targets
    ):
        if recorder is not None and not recorder.should_send(
            subscription=subscription,
            target_type=subscription_target_type,
            target_id=subscription_target_id,
        ):
            # Already observed delivered for this publication. Re-approval
            # returns the existing logical outcome instead of a second notice.
            skipped += 1
            continue
        try:
            handle = box.open(
                subscription.encrypted_subscriber_handle, aad=subscription.subscription_id
            )
        except Exception as exc:
            failed += 1
            detail = redact_delivery_detail(str(exc))
            _LOG.warning(
                "Subscription %s could not be opened for delivery: %s",
                subscription.subscription_id,
                detail,
            )
            if recorder is not None:
                recorder.record(
                    subscription=subscription,
                    target_type=subscription_target_type,
                    target_id=subscription_target_id,
                    outcome="failed",
                    error_code=delivery_error_code(exc),
                    detail=detail,
                )
            deliveries.append(
                delivery_proof(
                    subscription=subscription,
                    payload=payload,
                    message="subscriber record could not be opened for delivery",
                    status="failed",
                )
            )
            continue

        if subscription.channel == "email":
            try:
                message_id = mail.send_notification(email=handle, payload=payload)
            except Exception as exc:
                # Before WP-05 an SMTP refusal propagated out of this loop and
                # took every later recipient (and every earlier receipt) with
                # it. Mail failures are now per-recipient, same as webhooks.
                failed += 1
                detail = redact_delivery_detail(str(exc), handle=handle)
                _LOG.warning(
                    "Email notification for subscription %s failed: %s",
                    subscription.subscription_id,
                    detail,
                )
                if recorder is not None:
                    recorder.record(
                        subscription=subscription,
                        target_type=subscription_target_type,
                        target_id=subscription_target_id,
                        outcome="failed",
                        error_code=delivery_error_code(exc),
                        detail=detail,
                    )
                deliveries.append(
                    delivery_proof(
                        subscription=subscription,
                        payload=payload,
                        message="email delivery failed",
                        status="failed",
                    )
                )
                continue
            sent += 1
            if recorder is not None:
                recorder.record(
                    subscription=subscription,
                    target_type=subscription_target_type,
                    target_id=subscription_target_id,
                    outcome="sent",
                    detail="Email notice accepted by the mail provider.",
                )
            deliveries.append(
                delivery_proof(subscription=subscription, payload=payload, message=message_id)
            )
            continue

        try:
            secret = box.open(
                subscription.encrypted_webhook_secret or "",
                aad=f"{subscription.subscription_id}:secret",
            )
            signature = webhooks.post(url=handle, payload=payload, secret=secret)
        except Exception as exc:
            # Issue #111: a failed real delivery is queued durably and the
            # retry worker re-delivers with backoff; never claim "sent".
            failed += 1
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            detail = redact_delivery_detail(str(exc), handle=handle)
            retry = enqueue_failed_webhook_delivery(
                store=store,
                subscription_id=subscription.subscription_id,
                payload=payload.model_dump(mode="json"),
                status_code=status_code,
                error=detail,
            )
            if recorder is not None:
                recorder.record(
                    subscription=subscription,
                    target_type=subscription_target_type,
                    target_id=subscription_target_id,
                    # "queued", not "failed": the retry worker still owns this
                    # delivery, so the publish surface must read pending/partial
                    # rather than terminally failed.
                    outcome="queued",
                    error_code=delivery_error_code(exc),
                    detail=detail,
                    retry_id=retry.retry_id,
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
        sent += 1
        if recorder is not None:
            recorder.record(
                subscription=subscription,
                target_type=subscription_target_type,
                target_id=subscription_target_id,
                outcome="sent",
                detail="Webhook accepted the HMAC-signed notice.",
            )
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
        sent=sent,
        failed=failed,
        skipped=skipped,
        deliveries=deliveries,
    )


def subscription_rss(
    target_type: str,
    target_id: str,
    items: list[RssItem],
    *,
    public_base_url: str,
    station_name: str = "CivicCast",
) -> str:
    """Render one public subscription feed.

    ``public_base_url`` is required and has no default: the placeholder
    ``https://portal.example/...`` link this function used to hardcode shipped
    a production-looking URL for a host nobody owns. Callers resolve the real
    base from the station profile (or the request's own origin) --
    see :func:`civiccast.publish.targets.resolve_public_base_url`.

    An empty ``items`` list renders a valid, configured, EMPTY feed. A station
    with nothing published yet is a real state, not a reason to invent content.
    """

    label = "Channel" if target_type == "channel" else "Meeting body"
    base = public_base_url.rstrip("/")
    return render_rss(
        title=f"{station_name} — {label} {target_id}",
        link=f"{base}/",
        description=(
            "Public CivicCast recording notices for this "
            f"{'channel' if target_type == 'channel' else 'meeting body'}. "
            "RSS has no stored PII."
        ),
        items=items,
    )
