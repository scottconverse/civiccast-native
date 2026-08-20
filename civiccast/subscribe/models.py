# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Closed data contracts for v0.8 subscriptions and notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from civiccast.db import Base

SubscriptionChannel = Literal["email", "webhook"]
SubscriptionTargetType = Literal["channel", "meeting_body"]
SubscriptionStatus = Literal["pending_confirmation", "confirmed", "unsubscribed"]


class SubscriptionSignupRequest(BaseModel):
    """Resident email double-opt-in signup request."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=3, max_length=320)]
    target_type: SubscriptionTargetType
    target_id: Annotated[str, Field(min_length=1, max_length=120)]

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must include a local part and domain")
        return value.lower()


class SubscriptionWebhookRequest(BaseModel):
    """Webhook subscription request with URL ownership represented by an opt-in link."""

    model_config = ConfigDict(extra="forbid")

    webhook_url: HttpUrl
    target_type: SubscriptionTargetType
    target_id: Annotated[str, Field(min_length=1, max_length=120)]


class SubscriptionRecord(BaseModel):
    """Persisted subscription row without plaintext subscriber PII."""

    model_config = ConfigDict(extra="forbid")

    subscription_id: Annotated[str, Field(min_length=1, max_length=160)]
    channel: SubscriptionChannel
    encrypted_subscriber_handle: Annotated[str, Field(min_length=1)]
    target_type: SubscriptionTargetType
    target_id: Annotated[str, Field(min_length=1, max_length=120)]
    status: SubscriptionStatus
    confirmation_token: Annotated[str, Field(min_length=1)]
    unsubscribe_token: Annotated[str, Field(min_length=1)]
    encrypted_webhook_secret: str | None = None
    created_at: datetime
    confirmed_at: datetime | None = None
    unsubscribed_at: datetime | None = None

    @model_validator(mode="after")
    def _webhook_secret_matches_channel(self) -> SubscriptionRecord:
        if self.channel == "webhook" and not self.encrypted_webhook_secret:
            raise ValueError("webhook subscriptions require encrypted_webhook_secret")
        return self


class SubscriptionPublicResponse(BaseModel):
    """Safe resident-facing subscription state."""

    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    channel: SubscriptionChannel
    target_type: SubscriptionTargetType
    target_id: str
    status: SubscriptionStatus
    message: str
    next_step: str
    confirmation_token: str | None = None
    unsubscribe_token: str | None = None


class SubscriptionConfirmResponse(BaseModel):
    """Result of confirm or unsubscribe link action."""

    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    status: SubscriptionStatus
    message: str
    next_step: str


class NotificationPayload(BaseModel):
    """Payload dispatched when a recording publishes."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    title: str
    portal_url: str
    podcast_url: str | None = None
    summary: str | None = None
    published_at: datetime


class NotificationDelivery(BaseModel):
    """Proof that a notification was attempted."""

    model_config = ConfigDict(extra="forbid")

    delivery_id: str
    subscription_id: str
    channel: SubscriptionChannel
    status: Literal["sent", "failed"]
    target_type: SubscriptionTargetType
    target_id: str
    dispatched_at: datetime
    message: str
    signature: str | None = None


class NotificationDispatchResponse(BaseModel):
    """Aggregate notification dispatch result for a published asset."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    sent: int
    failed: int
    deliveries: list[NotificationDelivery]


WebhookRetryState = Literal["pending", "delivered", "dead_letter"]


class WebhookRetryRecord(BaseModel):
    """A failed webhook delivery queued for retry (issue #111).

    Carries only the subscription id and the notification payload: the
    webhook URL and per-subscription secret stay sealed in the subscriptions
    table and are reopened at send time, so this queue adds no plaintext PII.
    """

    model_config = ConfigDict(extra="forbid")

    retry_id: Annotated[str, Field(min_length=1, max_length=120)]
    subscription_id: Annotated[str, Field(min_length=1, max_length=160)]
    payload: dict[str, object]
    state: WebhookRetryState
    attempts: int
    next_attempt_at: datetime | None = None
    last_status_code: int
    last_error: str = ""
    created_at: datetime
    updated_at: datetime


class SubscriptionWebhookRetry(Base):
    """Durable retry-queue row for a failed subscriber webhook delivery."""

    __tablename__ = "subscription_webhook_retries"

    retry_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class RssItem(BaseModel):
    """One public RSS feed item."""

    title: str
    link: str
    guid: str
    published_at: datetime
    description: str
