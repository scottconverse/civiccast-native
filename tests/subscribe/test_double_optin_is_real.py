# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Double opt-in must require access to the inbox being subscribed.

GauntletGate rc18 QA-1 (Critical). ``POST /api/public/subscribe/email``
returned the ``confirmation_token`` in its own response body whenever the
subscription was ``pending_confirmation``. The caller could therefore confirm
the address immediately, without ever seeing the mail:

    POST /api/public/subscribe/email {"email": "someone-else@example.gov"}
      -> {"status": "pending_confirmation", "confirmation_token": "eyJ..."}
    GET  /api/public/subscribe/confirm?token=<that token>
      -> {"status": "confirmed"}

Two requests, no access to the mailbox, and a stranger's address is subscribed
to a government notification list. The echo was unconditional on
``record.status`` -- not on which mail provider was configured -- so selecting
a real SMTP provider did not close it.

The sibling magic-link route in the paywall module gets this right and says so
in its own docstring: "Mint a token + invoke the email sender. The token is
never echoed." Same contract, two modules, opposite behaviour. These tests pin
the correct one.

Confirmation tokens are still returned to the SENDER (the mail body needs the
link) -- they are simply no longer handed back to whoever made the HTTP call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS", "1")
    return TestClient(create_app())


def _signup(client: TestClient, email: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/public/subscribe/email",
        json={"email": email, "target_type": "channel", "target_id": "government"},
    )


def test_signup_response_never_carries_the_confirmation_token() -> None:
    """The response to the CALLER must not contain the proof of inbox access."""

    import os

    os.environ["CIVICCAST_AUTH_ACK"] = "1"
    os.environ["CIVICCAST_ALLOW_EPHEMERAL_STORES"] = "1"
    os.environ["CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS"] = "1"
    c = TestClient(create_app())

    response = _signup(c, "stranger@example.gov")
    assert response.status_code in (200, 201), response.text
    body = response.json()

    assert body.get("confirmation_token") in (None, ""), (
        "The signup response handed the confirmation token back to whoever made "
        "the request. Anyone can then confirm an address they do not control, "
        "which is the entire thing double opt-in exists to prevent."
    )
    # The rest of the contract must survive: the caller still learns what state
    # the subscription is in and what to do next.
    assert body["status"] == "pending_confirmation"
    assert "confirmation" in (body.get("next_step") or "").lower()


def test_a_stranger_cannot_confirm_an_address_they_do_not_control() -> None:
    """The end-to-end abuse path, asserted on the OUTCOME not the payload."""

    import os

    os.environ["CIVICCAST_AUTH_ACK"] = "1"
    os.environ["CIVICCAST_ALLOW_EPHEMERAL_STORES"] = "1"
    os.environ["CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS"] = "1"
    c = TestClient(create_app())

    signup = _signup(c, "victim@example.gov").json()
    token = signup.get("confirmation_token")

    if token:  # pre-fix path: the token was handed over, so confirm succeeds
        confirmed = c.get("/api/public/subscribe/confirm", params={"token": token})
        assert confirmed.json().get("status") != "confirmed", (
            "A caller with no access to victim@example.gov confirmed the "
            "subscription using a token the API gave them."
        )
