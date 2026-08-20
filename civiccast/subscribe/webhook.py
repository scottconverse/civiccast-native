# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real outbound webhook client (issue #111).

POSTs the canonical signed JSON notification body with an HMAC signature
header. Selected with ``CIVICCAST_PROVIDER_WEBHOOK=real``; the in-memory
``LocalWebhookClient`` mock remains the default. Per-subscription secrets are
passed in by the caller (they live sealed in the subscriptions table), so this
module reads no credentials from the environment — only the request timeout.

The signed bytes are exactly the bytes on the wire: canonical JSON with sorted
keys and compact separators, the same body :func:`sign_payload` HMACs, so the
mock's recorded signature and a real delivery's signature agree for the same
payload and secret.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from civiccast.subscribe.crypto import sign_payload
from civiccast.subscribe.models import NotificationPayload

__all__ = ["HttpWebhookClient", "WebhookSettings"]


@dataclass(frozen=True)
class WebhookSettings:
    """Outbound webhook delivery configuration, read from the environment."""

    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> WebhookSettings:
        raw = os.environ.get("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return cls()
        try:
            timeout = float(raw)
        except ValueError as exc:
            raise ValueError(
                f"CIVICCAST_WEBHOOK_TIMEOUT_SECONDS must be a number; got {raw!r}."
            ) from exc
        if timeout <= 0:
            raise ValueError(f"CIVICCAST_WEBHOOK_TIMEOUT_SECONDS must be positive; got {raw!r}.")
        return cls(timeout_seconds=timeout)


class HttpWebhookClient:
    """Webhook provider satisfying the same protocol as ``LocalWebhookClient``."""

    def __init__(
        self,
        settings: WebhookSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or WebhookSettings()
        self._transport = transport

    def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
        data = payload.model_dump(mode="json")
        signature = sign_payload(data, secret)
        body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        with httpx.Client(
            transport=self._transport, timeout=self._settings.timeout_seconds
        ) as client:
            response = client.post(
                url,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-civiccast-signature": f"sha256={signature}",
                    "x-civiccast-asset-id": payload.asset_id,
                },
            )
            response.raise_for_status()
        return signature
