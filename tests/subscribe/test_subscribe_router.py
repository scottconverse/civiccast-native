# SPDX-License-Identifier: Apache-2.0
"""Subscription router tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.subscribe.router import get_subscribe_store
from civiccast.subscribe.store import InMemorySubscribeStore


def _mailed_confirm_token(subscription_id: str) -> str:
    """Rebuild the token the confirmation MAIL carries.

    GauntletGate rc18 QA-1: the signup response no longer echoes the
    confirmation token, because handing it to the caller is what let anyone
    confirm a stranger's address. These API-level tests cannot reach the
    in-process mailbox the app resolves through the provider registry, so they
    mint the identical token the mail body would contain -- standing in for
    "the subscriber opened the link", not for "the API told me the answer".
    """
    from civiccast.subscribe.crypto import signed_token
    from civiccast.subscribe.secrets import load_subscription_secrets

    return signed_token(
        {"subscription_id": subscription_id, "action": "confirm"},
        load_subscription_secrets().token_secret,
    )


@pytest.fixture
def store() -> InMemorySubscribeStore:
    return InMemorySubscribeStore()


@pytest.fixture
def client(store: InMemorySubscribeStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_subscribe_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def test_signup_confirm_unsubscribe_api_flow(client: TestClient) -> None:
    signup = client.post(
        "/api/public/subscribe/email",
        json={"email": "resident@example.org", "target_type": "channel", "target_id": "government"},
    )
    assert signup.status_code == 200
    body = signup.json()
    assert body["status"] == "pending_confirmation"
    assert body["confirmation_token"] is None, (
        "The signup response must not echo the confirmation token (QA-1)."
    )

    confirm = client.get(
        "/api/public/subscribe/confirm",
        params={"token": _mailed_confirm_token(body["subscription_id"])},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"

    unsubscribe = client.get(
        "/api/public/subscribe/unsubscribe",
        params={"token": body["unsubscribe_token"]},
    )
    assert unsubscribe.status_code == 200
    assert unsubscribe.json()["status"] == "unsubscribed"


def test_bad_token_returns_actionable_400(client: TestClient) -> None:
    response = client.get("/api/public/subscribe/confirm", params={"token": "bad"})

    assert response.status_code == 400
    assert "Request a new signup link" in response.json()["detail"]


def test_rss_endpoint_returns_xml(client: TestClient) -> None:
    response = client.get("/api/public/subscribe/rss/channel/government.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    assert '<rss version="2.0">' in response.text


def test_staff_dispatch_sends_confirmed_subscriber(client: TestClient) -> None:
    signup = client.post(
        "/api/public/subscribe/email",
        json={"email": "resident@example.org", "target_type": "channel", "target_id": "government"},
    ).json()
    client.get(
        "/api/public/subscribe/confirm",
        params={"token": _mailed_confirm_token(signup["subscription_id"])},
    )

    response = client.post(
        "/api/staff/subscribe/dispatch-test",
        json={
            "asset_id": "council",
            "title": "Council",
            "portal_url": "https://portal.example/watch/council",
            "podcast_url": "https://portal.example/podcast/government.xml",
            "summary": "Council meeting published.",
            "published_at": "2026-05-14T12:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["sent"] == 1


def test_signup_email_rate_limit_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_SUBSCRIBE_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_SUBSCRIBE_RATE_LIMIT_WINDOW_SECONDS", "60")

    first = client.post(
        "/api/public/subscribe/email",
        json={"email": "one@example.org", "target_type": "channel", "target_id": "government"},
    )
    second = client.post(
        "/api/public/subscribe/email",
        json={"email": "two@example.org", "target_type": "channel", "target_id": "government"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
