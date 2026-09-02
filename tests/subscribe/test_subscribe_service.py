# SPDX-License-Identifier: Apache-2.0
"""Subscription service tests for v0.8."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.subscribe.crypto import DeterministicSecretBox, sign_payload, signed_token
from civiccast.subscribe.delivery import LocalMailbox, LocalWebhookClient
from civiccast.subscribe.models import (
    NotificationPayload,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.rss import validate_rss
from civiccast.subscribe.secrets import load_subscription_secrets, verify_subscription_token
from civiccast.subscribe.service import (
    confirm_subscription,
    create_email_subscription,
    create_webhook_subscription,
    dispatch_notifications,
    subscription_rss,
    unsubscribe,
)
from civiccast.subscribe.store import InMemorySubscribeStore


def _token_from_mail(mailbox) -> str:  # type: ignore[no-untyped-def]
    """Read the confirmation token the way a real subscriber does: from the mail.

    GauntletGate rc18 QA-1: these tests used to take the token out of the API's
    own signup RESPONSE, which is exactly the leak that let anyone confirm a
    stranger's address. Reading it from the delivered message keeps the flow
    under test while asserting the token travels only to the inbox.
    """
    body = mailbox.messages[-1]["body"]
    return body.split("token=", 1)[1].strip()


TEST_BOX_KEY = "civiccast-v08-" + "local-proof-key"


def test_email_double_opt_in_confirm_and_unsubscribe_flow() -> None:
    store = InMemorySubscribeStore()
    mailbox = LocalMailbox()

    created = create_email_subscription(
        SubscriptionSignupRequest(
            email="Resident@Example.org",
            target_type="channel",
            target_id="government",
        ),
        store=store,
        mailbox=mailbox,
    )

    assert created.status == "pending_confirmation"
    assert created.confirmation_token is None, (
        "The public response must not echo the confirmation token (QA-1)."
    )
    assert mailbox.messages[0]["to"] == "resident@example.org"
    assert "Confirm your CivicCast subscription" in mailbox.messages[0]["subject"]

    mailed_token = _token_from_mail(mailbox)
    confirmed = confirm_subscription(mailed_token, store=store)
    assert confirmed.status == "confirmed"

    again = confirm_subscription(mailed_token, store=store)
    assert again.message == "This subscription was already confirmed."

    unsubscribed = unsubscribe(created.unsubscribe_token or "", store=store)
    assert unsubscribed.status == "unsubscribed"


def test_invalid_confirmation_token_is_actionable() -> None:
    with pytest.raises(ValueError, match="malformed"):
        confirm_subscription("not-a-token", store=InMemorySubscribeStore())


def test_encrypted_handle_is_not_plaintext() -> None:
    store = InMemorySubscribeStore()
    created = create_email_subscription(
        SubscriptionSignupRequest(
            email="resident@example.org",
            target_type="meeting_body",
            target_id="planning-board",
        ),
        store=store,
    )
    record = store.get(created.subscription_id)

    assert record is not None
    assert "resident@example.org" not in record.encrypted_subscriber_handle
    assert (
        DeterministicSecretBox(TEST_BOX_KEY).open(
            record.encrypted_subscriber_handle,
            aad=record.subscription_id,
        )
        == "resident@example.org"
    )


def test_webhook_notification_signs_payload_and_tamper_fails() -> None:
    store = InMemorySubscribeStore()
    webhooks = LocalWebhookClient()
    created = create_webhook_subscription(
        SubscriptionWebhookRequest(
            webhook_url="https://example.org/civiccast-hook",
            target_type="channel",
            target_id="government",
        ),
        store=store,
    )
    confirm_subscription(created.confirmation_token or "", store=store)
    payload = NotificationPayload(
        asset_id="council-2026-05-14",
        title="Council",
        portal_url="https://portal.example/watch/council",
        podcast_url="https://portal.example/podcast/government.xml",
        summary="Council meeting published.",
        published_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
    )

    response = dispatch_notifications(payload, store=store, webhook_client=webhooks)

    assert response.sent == 1
    signature = response.deliveries[0].signature
    assert signature is not None
    record = store.get(created.subscription_id)
    assert record is not None
    secret = DeterministicSecretBox(TEST_BOX_KEY).open(
        record.encrypted_webhook_secret or "",
        aad=f"{record.subscription_id}:secret",
    )
    assert signature == sign_payload(payload.model_dump(mode="json"), secret)
    tampered = payload.model_copy(update={"title": "Changed"})
    assert signature != sign_payload(tampered.model_dump(mode="json"), secret)


def test_subscription_rss_is_valid_no_pii_feed() -> None:
    xml = subscription_rss(
        "channel",
        "government",
        [],
        public_base_url="https://records.example-city.gov",
    )

    assert validate_rss(xml) == []
    assert "subscriber" not in xml.lower()
    assert "email" not in xml.lower()


def test_subscription_rss_uses_the_configured_base_and_never_portal_example() -> None:
    """WP-05: the feed's own link comes from the station's configured base URL.

    The removed placeholder (``https://portal.example/{target_type}/{id}``) was
    a production-looking link to a host nobody owns; it shipped on every
    station's public feed.
    """

    xml = subscription_rss(
        "meeting_body",
        "planning-commission",
        [],
        public_base_url="https://records.example-city.gov/",
        station_name="Example City",
    )

    assert "portal.example" not in xml
    assert "<link>https://records.example-city.gov/</link>" in xml
    assert "Example City — Meeting body planning-commission" in xml
    # An empty feed is a real, valid state -- not a reason to invent an item.
    assert "<item>" not in xml
    assert validate_rss(xml) == []


def test_subscription_secrets_generate_durable_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / "subscribe-secrets.json"
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS", raising=False)
    monkeypatch.setenv("CIVICCAST_SUBSCRIBE_SECRETS_FILE", str(secret_file))

    generated = load_subscription_secrets()
    loaded = load_subscription_secrets()

    assert secret_file.exists()
    assert generated.token_secret == loaded.token_secret
    assert generated.source == str(secret_file)
    assert "civiccast-v08" not in secret_file.read_text(encoding="utf-8")


def test_legacy_subscription_token_verifies_only_when_rotation_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_secret = "civiccast-v08-" + "subscription-token-secret"
    token = signed_token({"subscription_id": "sub-existing", "action": "confirm"}, legacy_secret)
    env = {
        "CIVICCAST_SUBSCRIBE_TOKEN_SECRET": "new-token-secret-" + ("x" * 32),
        "CIVICCAST_SUBSCRIBE_ENCRYPTION_KEY": "new-encryption-secret-" + ("y" * 32),
    }

    without_legacy = load_subscription_secrets(env)
    with pytest.raises(ValueError):
        verify_subscription_token(token, without_legacy)

    with_legacy = load_subscription_secrets(
        {**env, "CIVICCAST_SUBSCRIBE_ACCEPT_V08_LEGACY_SECRETS": "1"}
    )
    assert verify_subscription_token(token, with_legacy)["subscription_id"] == "sub-existing"
