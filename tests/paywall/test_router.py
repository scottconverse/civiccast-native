# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S26 paywall API: role gating, 503 unwired, config CRUD, grants,
public access decision, magic-link end-to-end, Stripe webhook (signed),
no-PAN data egress.

Mirrors the agenda router harness: a minimal FastAPI app mounts the real
staff + public + webhook routers, installs an operator-identity middleware
(so ``require_any_role`` runs), and overrides the DI seams with a
SQLite-backed ``PaywallStore`` + ``PaywallService``. A mock Stripe
verifier is injected so tests never touch network and never need the
``stripe`` PyPI package.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.paywall.router import (
    _RATE_LIMITS,
    get_magic_link_email_sender,
    get_paywall_service,
    get_paywall_store,
    public_router,
    staff_router,
    webhook_router,
)
from civiccast.paywall.service import PaywallService
from civiccast.paywall.store import PaywallStore

_TEST_ENGINES: list[Engine] = []


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Reset the in-process per-IP rate limiter between tests so the
    Q-5 bucket from one test doesn't bleed into the next."""
    for limit, window, buckets in _RATE_LIMITS.values():  # noqa: B007
        buckets.clear()
    yield
    for limit, window, buckets in _RATE_LIMITS.values():  # noqa: B007
        buckets.clear()
    while _TEST_ENGINES:
        _TEST_ENGINES.pop().dispose()


_STATION = "civiccast-station"
_SECRET = "test-secret-do-not-rotate-this-okay-32+"
_CONFIG_SCOPES = ("setup_admin",)
_FROZEN_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


def _frozen_clock(at: datetime = _FROZEN_NOW):
    def _now() -> datetime:
        return at

    return _now


def _build(
    *,
    scopes: tuple[str, ...] | None = _CONFIG_SCOPES,
    wire_store: bool = True,
    wire_service: bool = True,
    stripe_verifier=None,
    email_sender=None,
    clock=None,
) -> tuple[FastAPI, PaywallStore, PaywallService, list[dict]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _TEST_ENGINES.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    store = PaywallStore(factory)
    service = PaywallService(
        store,
        mock_stripe_event_verifier=stripe_verifier,
        clock=clock or _frozen_clock(),
    )

    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana",
                operator_display_name="Dana",
                scopes=scopes,
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.include_router(public_router)
    app.include_router(webhook_router)
    if wire_store:
        app.dependency_overrides[get_paywall_store] = lambda: store
    if wire_service:
        app.dependency_overrides[get_paywall_service] = lambda: service

    # Recording email sender for magic-link tests.
    captured: list[dict] = []

    def _sender(
        *,
        email: str,
        token: str,
        station_id: str,
        scope_kind: str,
        scope_id: str,
    ) -> None:
        captured.append(
            {
                "email": email,
                "token": token,
                "station_id": station_id,
                "scope_kind": scope_kind,
                "scope_id": scope_id,
            }
        )

    app.dependency_overrides[get_magic_link_email_sender] = lambda: email_sender or _sender
    return app, store, service, captured


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _config_payload(
    *,
    config_id: str = "pw-cfg",
    enabled: bool = True,
    signing_secret: str | None = _SECRET,
    tiers: list[dict] | None = None,
) -> dict:
    return {
        "config_id": config_id,
        "station_id": _STATION,
        "enabled": enabled,
        "provider": "stripe",
        "tiers": tiers
        if tiers is not None
        else [{"tier_id": "basic", "name": "Basic", "price_id": "price_basic"}],
        "signing_secret": signing_secret,
    }


def _grant_payload(grant_id: str = "g1", **overrides) -> dict:
    body = {
        "grant_id": grant_id,
        "station_id": _STATION,
        "email": "viewer@example.com",
        "scope_kind": "asset",
        "scope_id": "vid-1",
        "granted_via": "comp",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# 503 when DI unwired
# ---------------------------------------------------------------------------


def test_503_when_store_unwired_on_get_config() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).get("/api/staff/paywall/config")
    assert r.status_code == 503


def test_503_when_store_unwired_on_put_config() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).put("/api/staff/paywall/config", json=_config_payload())
    assert r.status_code == 503


def test_503_when_store_unwired_on_post_grant() -> None:
    app, *_ = _build(wire_store=False)
    r = TestClient(app).post("/api/staff/paywall/grants", json=_grant_payload())
    assert r.status_code == 503


def test_503_when_service_unwired_on_public_access() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).get("/api/public/paywall/access", params={"asset_id": "vid-1"})
    assert r.status_code == 503


def test_503_when_service_unwired_on_magic_link() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).post(
        "/api/public/paywall/magic-link",
        json={"email": "x@y.com", "scope_kind": "asset", "scope_id": "v"},
    )
    assert r.status_code == 503


def test_503_when_service_unwired_on_verify() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).get(
        "/api/public/paywall/verify", params={"token": "longer-than-eight.deadbeef"}
    )
    assert r.status_code == 503


def test_503_when_service_unwired_on_webhook() -> None:
    app, *_ = _build(wire_service=False)
    r = TestClient(app).post(
        "/api/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "sig"},
    )
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Role gating: staff routes require setup_admin
# ---------------------------------------------------------------------------


class TestRoleGates:
    def test_get_config_requires_setup_admin(self) -> None:
        assert _client(scopes=None).get("/api/staff/paywall/config").status_code == 401
        assert (
            _client(scopes=("publish_operator",)).get("/api/staff/paywall/config").status_code
            == 403
        )
        assert (
            _client(scopes=("records_clerk",)).get("/api/staff/paywall/config").status_code == 403
        )
        # setup_admin -> safe default response (no config yet), but NOT 401/403.
        assert _client(scopes=("setup_admin",)).get("/api/staff/paywall/config").status_code == 200

    def test_put_config_requires_setup_admin(self) -> None:
        r = _client(scopes=("publish_operator",)).put(
            "/api/staff/paywall/config", json=_config_payload()
        )
        assert r.status_code == 403

    def test_patch_config_requires_setup_admin(self) -> None:
        r = _client(scopes=("publish_operator",)).patch(
            "/api/staff/paywall/config/pw-cfg", json={"enabled": True}
        )
        assert r.status_code == 403

    def test_delete_config_requires_setup_admin(self) -> None:
        r = _client(scopes=("publish_operator",)).delete("/api/staff/paywall/config/pw-cfg")
        assert r.status_code == 403

    def test_create_grant_requires_setup_admin(self) -> None:
        r = _client(scopes=("publish_operator",)).post(
            "/api/staff/paywall/grants", json=_grant_payload()
        )
        assert r.status_code == 403

    def test_delete_grant_requires_setup_admin(self) -> None:
        r = _client(scopes=("publish_operator",)).delete("/api/staff/paywall/grants/g1")
        assert r.status_code == 403

    def test_public_access_has_no_role_gate(self) -> None:
        # No identity — public endpoint must not gate on it. Default-off
        # config -> allowed=True.
        r = _client(scopes=None).get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True

    def test_webhook_has_no_role_gate(self) -> None:
        # No identity — webhook is signature-authenticated by the service.
        # With no config yet, the service raises -> 401 (not 403/401-no-id).
        r = _client(scopes=None).post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        # 401 due to "no paywall configured", NOT 403 from a role gate.
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------


class TestConfigCrud:
    def test_get_returns_disabled_default_when_no_config(self) -> None:
        r = _client().get("/api/staff/paywall/config")
        assert r.status_code == 200
        body = r.json()
        assert body["config_id"] == "paywall-default"
        assert body["station_id"] == "civiccast-station"
        assert body["enabled"] is False
        assert body["tiers"] == []
        assert body["signing_secret_present"] is False
        assert "signing_secret" not in body

    def test_put_creates_then_get_returns_it(self) -> None:
        client = _client()
        r = client.put("/api/staff/paywall/config", json=_config_payload())
        assert r.status_code == 200
        assert r.json()["config_id"] == "pw-cfg"
        assert r.json()["enabled"] is True
        # Q-2 fix: the PUT response is the public projection. signing_secret
        # never appears; signing_secret_present surfaces presence as bool.
        assert "signing_secret" not in r.json()
        assert r.json()["signing_secret_present"] is True
        # Round-trip via GET. Same public projection.
        r2 = client.get("/api/staff/paywall/config")
        assert r2.status_code == 200
        assert "signing_secret" not in r2.json()
        assert r2.json()["signing_secret_present"] is True

    def test_put_idempotent_same_config_id(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload())
        r = client.put("/api/staff/paywall/config", json=_config_payload(enabled=False))
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_put_different_config_id_same_station_is_409(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(config_id="pw-1"))
        r = client.put("/api/staff/paywall/config", json=_config_payload(config_id="pw-2"))
        assert r.status_code == 409

    def test_patch_404_when_missing(self) -> None:
        r = _client().patch("/api/staff/paywall/config/no-such", json={"enabled": True})
        assert r.status_code == 404

    def test_patch_updates_enabled(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=False))
        r = client.patch("/api/staff/paywall/config/pw-cfg", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_patch_can_rotate_signing_secret(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload())
        # Q-11 fix: 32-char minimum on a new secret.
        r = client.patch(
            "/api/staff/paywall/config/pw-cfg",
            json={"signing_secret": "new-secret-with-32-or-more-chars-ok"},
        )
        assert r.status_code == 200
        # Q-2 fix: the response is the public projection. signing_secret
        # never appears in the body; signing_secret_present is True.
        assert "signing_secret" not in r.json()
        assert r.json()["signing_secret_present"] is True

    def test_delete_404_when_missing(self) -> None:
        r = _client().delete("/api/staff/paywall/config/no-such")
        assert r.status_code == 404

    def test_delete_204_when_present(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload())
        r = client.delete("/api/staff/paywall/config/pw-cfg")
        assert r.status_code == 204
        # gone from durable storage; GET returns a fresh disabled default.
        r2 = client.get("/api/staff/paywall/config")
        assert r2.status_code == 200
        assert r2.json()["config_id"] == "paywall-default"
        assert r2.json()["enabled"] is False

    def test_put_rejects_extra_keys(self) -> None:
        body = _config_payload()
        body["surprise"] = "x"
        r = _client().put("/api/staff/paywall/config", json=body)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Grant CRUD
# ---------------------------------------------------------------------------


class TestGrantCrud:
    def test_create_grant_201(self) -> None:
        r = _client().post("/api/staff/paywall/grants", json=_grant_payload())
        assert r.status_code == 201
        assert r.json()["grant_id"] == "g1"

    def test_create_duplicate_grant_409(self) -> None:
        client = _client()
        client.post("/api/staff/paywall/grants", json=_grant_payload())
        r = client.post("/api/staff/paywall/grants", json=_grant_payload())
        assert r.status_code == 409

    def test_create_grant_422_on_bad_email(self) -> None:
        r = _client().post("/api/staff/paywall/grants", json=_grant_payload(email="not-an-email"))
        assert r.status_code == 422

    def test_delete_grant_204(self) -> None:
        client = _client()
        client.post("/api/staff/paywall/grants", json=_grant_payload())
        r = client.delete("/api/staff/paywall/grants/g1")
        assert r.status_code == 204

    def test_delete_grant_404(self) -> None:
        r = _client().delete("/api/staff/paywall/grants/no-such")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Public access (DC-1, DC-2)
# ---------------------------------------------------------------------------


class TestPublicAccess:
    def test_default_off_allows(self) -> None:
        # No config at all
        r = _client(scopes=None).get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert r.status_code == 200
        assert r.json() == {"allowed": True, "reason": None}

    def test_default_off_allows_anonymous(self) -> None:
        r = _client(scopes=None).get("/api/public/paywall/access", params={"asset_id": "vid-1"})
        assert r.status_code == 200
        assert r.json() == {"allowed": True, "reason": None}

    def test_enabled_no_email_returns_sign_in_required(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get("/api/public/paywall/access", params={"asset_id": "vid-1"})
        assert r.status_code == 200
        assert r.json()["allowed"] is False
        assert r.json()["reason"] == "sign_in_required"

    def test_enabled_no_grant_returns_subscription_required(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
        assert r.json()["reason"] == "subscription_required"

    def test_enabled_with_grant_allows(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post("/api/staff/paywall/grants", json=_grant_payload())
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True

    def test_series_scope_works(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/staff/paywall/grants",
            json=_grant_payload(scope_kind="series", scope_id="cityhall"),
        )
        r = client.get(
            "/api/public/paywall/access",
            params={"series_id": "cityhall", "email": "viewer@example.com"},
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True

    def test_both_asset_and_series_is_422(self) -> None:
        r = _client(scopes=None).get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "series_id": "cityhall"},
        )
        assert r.status_code == 422

    def test_neither_asset_nor_series_is_422(self) -> None:
        r = _client(scopes=None).get("/api/public/paywall/access", params={"email": "v@e.com"})
        assert r.status_code == 422

    def test_response_has_no_email_field(self) -> None:
        # The decision shape MUST NOT echo the viewer's email back.
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert "email" not in r.json()


# ---------------------------------------------------------------------------
# Magic-link end-to-end
# ---------------------------------------------------------------------------


class TestMagicLinkRouter:
    def test_mint_with_no_config_silently_drops(self) -> None:
        # Q-9 fix: identical response shape whether configured or not.
        # An anonymous caller can't probe "is the paywall on?" via the
        # status code. The mint is silently dropped if there's no config.
        r = _client().post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        assert r.status_code == 200
        assert r.json() == {"sent": True}

    def test_mint_does_not_echo_token(self) -> None:
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        assert r.status_code == 200
        assert r.json() == {"sent": True}
        # Token went to the email sender, NOT the response body.
        assert "token" not in r.text
        assert len(captured) == 1
        assert captured[0]["email"] == "viewer@example.com"

    def test_mint_calls_email_sender_with_token(self) -> None:
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        assert captured[0]["token"]
        assert "." in captured[0]["token"]

    def test_mint_then_verify_creates_grant_and_unlocks(self) -> None:
        app, _store, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        assert r.status_code == 200
        token = captured[0]["token"]
        # Now verify the link.
        r = client.get("/api/public/paywall/verify", params={"token": token})
        assert r.status_code == 200
        assert r.json() == {"allowed": True, "reason": None}
        # And the access decision now allows.
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert r.json()["allowed"] is True

    def test_verify_replay_is_401(self) -> None:
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        token = captured[0]["token"]
        client.get("/api/public/paywall/verify", params={"token": token})
        r = client.get("/api/public/paywall/verify", params={"token": token})
        assert r.status_code == 401
        # E-3 / Q-7 fix: identical generic detail across all failure modes.
        assert r.json() == {"detail": "Magic link could not be verified."}

    def test_verify_bad_token_is_401(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get("/api/public/paywall/verify", params={"token": "garbage.deadbeef"})
        assert r.status_code == 401

    def test_mint_with_loose_email_does_not_send_email(self) -> None:
        # T-6 fix: the public mint endpoint deliberately does not RFC5322-
        # validate. But it must NOT trigger an outbound email send for a
        # syntactically invalid address. The service-layer email validator
        # raises during mint -> service maps to 422 (the request didn't
        # conform to the public contract) -> the recording sender is
        # never invoked.
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "not-an-email", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        # 422 or 200 are both acceptable — the load-bearing assertion is
        # that no outbound email was triggered.
        assert r.status_code in (200, 422)
        assert captured == []


# ---------------------------------------------------------------------------
# Stripe webhook (DC-3, DC-4)
# ---------------------------------------------------------------------------


def _stripe_event(
    *,
    event_type: str = "customer.subscription.created",
    sub_id: str = "sub_router_test",
    email: str = "buyer@example.com",
    status_value: str = "active",
) -> dict:
    return {
        "type": event_type,
        "data": {
            "object": {
                "id": sub_id,
                "status": status_value,
                "current_period_end": int((_FROZEN_NOW + timedelta(days=30)).timestamp()),
                "customer_email": email,
                "items": {"data": [{"price": {"id": "price_basic"}}]},
            }
        },
    }


class TestStripeWebhookRouter:
    def test_webhook_missing_signature_header_is_401(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post("/api/webhooks/stripe", content=b"{}")
        assert r.status_code == 401

    def test_webhook_no_config_is_401(self) -> None:
        r = _client().post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 401

    def test_webhook_bad_signature_is_401(self) -> None:
        def _bad(*_a):
            raise ValueError("bad sig")

        app, _, _, _ = _build(stripe_verifier=_bad)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 401

    def test_webhook_created_returns_200_and_grants_access(self) -> None:
        event = _stripe_event()
        app, _store, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/webhooks/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 200
        assert r.json()["received"] is True
        assert r.json()["action"] == "created"
        # Buyer now has access.
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "buyer@example.com"},
        )
        assert r.json()["allowed"] is True

    def test_webhook_deleted_revokes(self) -> None:
        # Two passes against the same store.
        created_event = _stripe_event(event_type="customer.subscription.created")
        deleted_event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_router_test"}},
        }
        verifier_state = {"event": created_event}

        def _verifier(*_a):
            return verifier_state["event"]

        app, _, _, _ = _build(stripe_verifier=_verifier)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert (
            client.get(
                "/api/public/paywall/access",
                params={"asset_id": "vid-1", "email": "buyer@example.com"},
            ).json()["allowed"]
            is True
        )
        # Switch the verifier output + send delete.
        verifier_state["event"] = deleted_event
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 200
        assert r.json()["action"] == "deleted"
        # Buyer is locked out again.
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "buyer@example.com"},
        )
        assert r.json()["allowed"] is False

    def test_webhook_missing_email_is_400(self) -> None:
        event = _stripe_event()
        event["data"]["object"].pop("customer_email", None)
        app, *_ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# DC-4 — no PAN-shaped data lands in responses or DB
# ---------------------------------------------------------------------------


_PAN_RE = re.compile(r"\b\d{13,19}\b")
_PAN_BAIT = "4242424242424242"


def _scan_db_for_pan(store: PaywallStore) -> list[str]:
    hits: list[str] = []
    with store._session_factory() as session:
        for table in ("paywall_configs", "access_grants", "paywall_subscriptions"):
            rows = session.execute(text(f"SELECT * FROM {table}")).mappings().all()
            for row in rows:
                for col, val in dict(row).items():
                    if val is None:
                        continue
                    if _PAN_RE.search(str(val)):
                        hits.append(f"{table}.{col}={val!r}")
    return hits


class TestNoPanDataLeaks:
    def test_webhook_with_pan_doesnt_persist_it(self) -> None:
        event = _stripe_event()
        event["data"]["object"]["description"] = f"Recurring charge {_PAN_BAIT}"
        event["data"]["object"]["billing_details"] = {"card_number": _PAN_BAIT}
        app, store, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 200
        # No card-shaped string anywhere in the DB.
        assert _scan_db_for_pan(store) == []
        # No card-shaped string in the response either.
        assert _PAN_RE.search(r.text) is None

    def test_public_access_response_has_no_pan_shaped_fields(self) -> None:
        # Sanity: the access endpoint never emits anything card-shaped.
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        assert _PAN_RE.search(r.text) is None


# ---------------------------------------------------------------------------
# E-1 BLOCKER fix — public mint of scope_kind="all" rejected
# ---------------------------------------------------------------------------


class TestPublicMintRejectsCatchAllScope:
    """The public ``POST /api/public/paywall/magic-link`` endpoint MUST
    refuse ``scope_kind="all"``. Otherwise any anonymous caller could
    mint a 30-day catch-all grant via one email round-trip, bypassing
    Stripe entirely. The S26 audit's headline blocker (E-1).
    """

    def test_public_mint_all_scope_is_422(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "atk@example.com", "scope_kind": "all", "scope_id": ""},
        )
        # Pydantic rejects scope_kind="all" at the model layer (the
        # Literal no longer includes "all") so this is a 422 from the
        # request validator.
        assert r.status_code == 422

    def test_public_mint_default_scope_kind_is_asset(self) -> None:
        # Omitting scope_kind no longer defaults to "all" (the unsafe
        # default that made E-1 a one-roundtrip blocker). It now defaults
        # to "asset", and scope_id becomes required so an omitted body
        # cannot mint a catch-all grant.
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_id": "vid-1"},
        )
        assert r.status_code == 200
        assert captured[0]["scope_kind"] == "asset"

    def test_public_mint_with_empty_scope_id_is_422(self) -> None:
        # E-1: scope_id is now required. An empty string cannot collapse
        # into a catch-all by accident.
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": ""},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# E-3 / Q-7 fix — verify-endpoint generic 401 detail across all failure modes
# ---------------------------------------------------------------------------


class TestVerifyEndpointGeneric401:
    """Every magic-link verify failure (malformed / bad-sig / expired /
    replayed / cross-station / unknown station) MUST return the same
    401 body. The docstring promise was already there; the
    implementation now matches.
    """

    def _mint_token(self):
        from datetime import timedelta

        app, _, svc, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        token = captured[0]["token"]
        return app, client, svc, token, timedelta

    def test_malformed_token_returns_generic_detail(self) -> None:
        _, client, _, _, _ = self._mint_token()
        r = client.get("/api/public/paywall/verify", params={"token": "garbage.deadbeef"})
        assert r.status_code == 401
        assert r.json() == {"detail": "Magic link could not be verified."}

    def test_replay_returns_generic_detail(self) -> None:
        _, client, _, token, _ = self._mint_token()
        client.get("/api/public/paywall/verify", params={"token": token})
        r = client.get("/api/public/paywall/verify", params={"token": token})
        assert r.status_code == 401
        assert r.json() == {"detail": "Magic link could not be verified."}

    def test_expired_token_returns_generic_detail(self) -> None:
        # Build a service with a clock-drift wrapper so we can age the
        # token past its TTL without rebuilding the world.
        from datetime import timedelta

        # Mint at frozen-now, then move the clock forward via a custom
        # clock factory.
        clock_state = {"now": _FROZEN_NOW}

        def _clock() -> datetime:
            return clock_state["now"]

        app, _, _, captured = _build(clock=_clock)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        token = captured[0]["token"]
        # Advance past the 15-min TTL.
        clock_state["now"] = _FROZEN_NOW + timedelta(hours=1)
        r = client.get("/api/public/paywall/verify", params={"token": token})
        assert r.status_code == 401
        assert r.json() == {"detail": "Magic link could not be verified."}

    def test_tampered_mac_returns_generic_detail(self) -> None:
        _, client, _, token, _ = self._mint_token()
        payload_b64, _mac = token.split(".", 1)
        tampered = f"{payload_b64}.deadbeefcafe"
        r = client.get("/api/public/paywall/verify", params={"token": tampered})
        assert r.status_code == 401
        assert r.json() == {"detail": "Magic link could not be verified."}


# ---------------------------------------------------------------------------
# Q-1 fix — Stripe webhook event-id idempotency (replay protection)
# ---------------------------------------------------------------------------


class TestStripeWebhookIdempotency:
    def test_replay_of_same_event_id_short_circuits(self) -> None:
        event = _stripe_event()
        event["id"] = "evt_idem_1"
        app, _store, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        # First delivery
        r1 = client.post(
            "/api/webhooks/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "sig"},
        )
        assert r1.status_code == 200
        assert r1.json()["action"] == "created"
        # Replay — same event id, same body
        r2 = client.post(
            "/api/webhooks/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "sig"},
        )
        assert r2.status_code == 200
        assert r2.json()["action"] == "duplicate"

    def test_distinct_event_ids_both_process(self) -> None:
        event_a = _stripe_event()
        event_a["id"] = "evt_idem_a"
        event_b = _stripe_event()
        event_b["id"] = "evt_idem_b"
        # Switch the verifier output between calls.
        events = [event_a, event_b]
        idx = {"i": 0}

        def _verifier(*_a):
            return events[idx["i"]]

        app, _, _, _ = _build(stripe_verifier=_verifier)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r1 = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        idx["i"] = 1
        r2 = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r1.json()["action"] == "created"
        assert r2.json()["action"] == "created"


# ---------------------------------------------------------------------------
# Q-4 fix — webhook body size cap (1 MiB)
# ---------------------------------------------------------------------------


class TestWebhookBodySizeCap:
    def test_oversized_body_is_413(self) -> None:
        # Content-Length advertised above the cap is rejected before
        # the body materializes in memory.
        app, *_ = _build(stripe_verifier=lambda *a: {})
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        big = b"x" * (1 * 1024 * 1024 + 1)
        r = client.post(
            "/api/webhooks/stripe",
            content=big,
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 413


# ---------------------------------------------------------------------------
# Q-2 fix — signing_secret never appears in any GET response
# ---------------------------------------------------------------------------


class TestSigningSecretNeverEchoed:
    def test_get_config_omits_signing_secret(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.get("/api/staff/paywall/config")
        assert _SECRET not in r.text

    def test_put_response_omits_signing_secret(self) -> None:
        client = _client()
        r = client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        assert r.status_code == 200
        assert _SECRET not in r.text

    def test_patch_response_omits_signing_secret(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        new_secret = "patched-secret-with-32-or-more-chars"
        r = client.patch(
            "/api/staff/paywall/config/pw-cfg",
            json={"signing_secret": new_secret},
        )
        assert r.status_code == 200
        assert new_secret not in r.text

    def test_public_endpoints_never_leak_signing_secret(self) -> None:
        # T-11 fix: scan every public surface for the configured secret.
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        # Public access
        r1 = client.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )
        # Public mint
        r2 = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        # Public verify (against a bad token)
        r3 = client.get("/api/public/paywall/verify", params={"token": "garbage.deadbeef"})
        for r in (r1, r2, r3):
            assert _SECRET not in r.text


# ---------------------------------------------------------------------------
# Q-2 fix — PATCH signing_secret set-only semantics
# ---------------------------------------------------------------------------


class TestPatchSigningSecretSetOnly:
    def test_absent_signing_secret_leaves_unchanged(self) -> None:
        # Round-trip: PUT a secret, PATCH something else with no
        # signing_secret key in the body, verify the secret is still set.
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.patch("/api/staff/paywall/config/pw-cfg", json={"enabled": False})
        assert r.status_code == 200
        # The public projection says the secret is still present.
        r2 = client.get("/api/staff/paywall/config")
        assert r2.json()["signing_secret_present"] is True

    def test_explicit_empty_string_clears_secret(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.patch("/api/staff/paywall/config/pw-cfg", json={"signing_secret": ""})
        assert r.status_code == 200
        r2 = client.get("/api/staff/paywall/config")
        assert r2.json()["signing_secret_present"] is False

    def test_explicit_null_does_not_clear_secret(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.patch("/api/staff/paywall/config/pw-cfg", json={"signing_secret": None})
        assert r.status_code == 200
        r2 = client.get("/api/staff/paywall/config")
        # Null was a no-op; the secret is still set.
        assert r2.json()["signing_secret_present"] is True

    def test_under_length_signing_secret_is_422(self) -> None:
        client = _client()
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.patch(
            "/api/staff/paywall/config/pw-cfg",
            json={"signing_secret": "too-short"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Q-6 fix — /access endpoint timing/shape parity for DC-1 default-off
# ---------------------------------------------------------------------------


class TestAccessEndpointShapeParity:
    def test_no_config_and_has_config_have_same_response_shape(self) -> None:
        # DC-1 default-off when there's no config returns allowed=True.
        # Both endpoints (no config / has config but no grant) MUST return
        # the same key set in their JSON body so a probing client can't
        # distinguish "no config" from "has config, no grant" via shape.
        client_no_config = _client()
        r_no_config = client_no_config.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )

        client_has_config = _client()
        client_has_config.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r_has_config = client_has_config.get(
            "/api/public/paywall/access",
            params={"asset_id": "vid-1", "email": "viewer@example.com"},
        )

        # Same shape: {"allowed": bool, "reason": str|None}.
        assert (
            set(r_no_config.json().keys())
            == set(r_has_config.json().keys())
            == {
                "allowed",
                "reason",
            }
        )


# ---------------------------------------------------------------------------
# Real DC-4 test (T-1 fix) — PAN cannot leak to logs OR response body
# even when planted in a field the parser DOES read.
# ---------------------------------------------------------------------------


_LUHN_VALID_CARDS = ("4242424242424242", "4111111111111111", "5555555555554444")


class TestNoPanInLogsOrResponse:
    def test_pan_in_customer_email_is_rejected_and_not_logged(self, caplog) -> None:
        # Plant a Luhn-valid card-shaped string in customer_email (a
        # field the parser DOES read). The email-shape validator
        # should reject it; if a future change starts accepting it, we
        # MUST still not log the raw value at any level.
        import logging as _logging

        event = _stripe_event()
        event["data"]["object"]["customer_email"] = _LUHN_VALID_CARDS[0]
        app, store, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        caplog.set_level(_logging.DEBUG)
        client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        # Scan DB AND caplog for the planted bait.
        for record in caplog.records:
            for value in (record.getMessage(), *(str(v) for v in (record.args or ()))):
                if _PAN_RE.search(value):
                    raise AssertionError(f"PAN-shaped string in log record: {value!r}")
        assert _scan_db_for_pan(store) == []

    def test_pan_in_metadata_does_not_reach_logs_or_db(self, caplog) -> None:
        import logging as _logging

        event = _stripe_event()
        event["data"]["object"]["description"] = f"Charge for card {_LUHN_VALID_CARDS[1]}"
        event["data"]["object"]["metadata"] = {"raw_pan": _LUHN_VALID_CARDS[2]}
        event["data"]["object"]["billing_details"] = {"card_number": _LUHN_VALID_CARDS[0]}
        app, store, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        caplog.set_level(_logging.DEBUG)
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        # The webhook accepts but persists nothing card-shaped.
        assert r.status_code == 200
        assert _scan_db_for_pan(store) == []
        # Logs don't leak it either.
        for record in caplog.records:
            for value in (record.getMessage(), *(str(v) for v in (record.args or ()))):
                if _PAN_RE.search(value):
                    raise AssertionError(f"PAN-shaped string in log record: {value!r}")
        # Response body doesn't either.
        assert _PAN_RE.search(r.text) is None


# ---------------------------------------------------------------------------
# E-8 / E-1 / E-6 / E-7 / Q-13 service-level behaviors exercised via router
# ---------------------------------------------------------------------------


class TestServiceLevelGuardsViaRouter:
    def test_mint_refused_when_paywall_disabled(self) -> None:
        # E-8 fix: a "configured but disabled" station must not mint.
        # Q-9 keeps the response shape constant — sent: true is returned
        # but no token is actually sent.
        app, _, _, captured = _build()
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=False))
        r = client.post(
            "/api/public/paywall/magic-link",
            json={"email": "viewer@example.com", "scope_kind": "asset", "scope_id": "vid-1"},
        )
        assert r.status_code == 200
        assert captured == []  # no email triggered

    def test_webhook_missing_period_end_on_active_is_400(self) -> None:
        # E-7 fix: an active subscription event without current_period_end
        # is rejected (400) rather than silently granting 30 days.
        event = _stripe_event()
        event["data"]["object"].pop("current_period_end", None)
        app, _, _, _ = _build(stripe_verifier=lambda *a: event)
        client = TestClient(app)
        client.put("/api/staff/paywall/config", json=_config_payload(enabled=True))
        r = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        assert r.status_code == 400
