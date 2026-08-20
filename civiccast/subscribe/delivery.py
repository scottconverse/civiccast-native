# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Deterministic v0.8 notification delivery adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from civiccast.subscribe.crypto import sign_payload
from civiccast.subscribe.models import NotificationDelivery, NotificationPayload, SubscriptionRecord


class MailboxProvider(Protocol):
    def send_confirmation(self, *, email: str, confirmation_url: str) -> str: ...
    def send_notification(self, *, email: str, payload: NotificationPayload) -> str: ...


class WebhookProvider(Protocol):
    def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str: ...


class LocalMailbox:
    """In-memory mailbox for CI and local proof."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send_confirmation(self, *, email: str, confirmation_url: str) -> str:
        message_id = f"mail:{len(self.messages) + 1}"
        self.messages.append(
            {
                "id": message_id,
                "to": email,
                "subject": "Confirm your CivicCast subscription",
                "body": f"Confirm your subscription: {confirmation_url}",
            }
        )
        return message_id

    def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
        message_id = f"mail:{len(self.messages) + 1}"
        self.messages.append(
            {
                "id": message_id,
                "to": email,
                "subject": f"New CivicCast recording: {payload.title}",
                "body": (
                    f"{payload.title}\nWatch: {payload.portal_url}\n"
                    f"Podcast: {payload.podcast_url or 'Not posted'}"
                ),
            }
        )
        return message_id


class LocalWebhookClient:
    """In-memory webhook client that records signed payload attempts."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
        signature = sign_payload(payload.model_dump(mode="json"), secret)
        self.requests.append(
            {
                "url": url,
                "signature": signature,
                "asset_id": payload.asset_id,
            }
        )
        return signature


def delivery_proof(
    *,
    subscription: SubscriptionRecord,
    payload: NotificationPayload,
    message: str,
    signature: str | None = None,
    status: Literal["sent", "failed"] = "sent",
) -> NotificationDelivery:
    return NotificationDelivery(
        delivery_id=f"{subscription.subscription_id}:{payload.asset_id}:{len(message)}",
        subscription_id=subscription.subscription_id,
        channel=subscription.channel,
        status=status,
        target_type=subscription.target_type,
        target_id=subscription.target_id,
        dispatched_at=datetime.now(UTC),
        message=message,
        signature=signature,
    )
