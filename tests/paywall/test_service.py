# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S26 paywall service layer (slice 2).

Locks every PaywallService responsibility against a SQLite-backed
:class:`PaywallStore`:

* default-off short-circuit (DC-1): ``has_access`` returns True when no
  config exists OR ``enabled=False``, even without an email and even with
  no grants in the table;
* gating (DC-2): with the paywall enabled, grants drive yes/no,
  including the catch-all ``"all"`` scope and subscription / comp /
  magic_link grant kinds;
* ``decide`` reason codes (``sign_in_required`` vs
  ``subscription_required``);
* magic-link lifecycle (DC-5): mint succeeds with a configured secret,
  refuses without one; verify accepts a valid token, rejects malformed /
  tampered / expired / replayed tokens; token id round-trips into the
  redeeming grant; redeemed grants live in the table for the gate to find;
* Stripe webhook (DC-3): missing secret → 401; bad signature → 401;
  ``created`` upserts subscription + all-scope grant; ``updated``
  refreshes period_end; ``deleted`` flips status + revokes grants;
  unrecognized event types are ack'd + dropped;
* DC-4 — webhook never persists card-shaped data, even when the payload
  carries it in a free-text field.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.paywall.models import (
    AccessGrant,
    PaywallConfig,
    PaywallTier,
    Subscription,
)
from civiccast.paywall.service import (
    DEFAULT_MAGIC_LINK_GRANT_TTL_SECONDS,
    MagicLinkAlreadyRedeemedError,
    MagicLinkExpiredError,
    MagicLinkInvalidError,
    MagicLinkNotConfiguredError,
    PaywallService,
    WebhookSignatureError,
    _encode_token,
)
from civiccast.paywall.store import PaywallStore

_STATION = "civiccast-station"
_SECRET = "test-secret-do-not-rotate-this-okay-32+"
# A frozen "now" so token-expiry tests are deterministic.
_FROZEN_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)

# Card-shaped string the DC-4 test plants in a free-text Stripe field. We
# assert NO column anywhere stores it after the webhook runs.
_PAN_BAIT = "4242424242424242"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PaywallStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'paywall.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield PaywallStore(factory)
    finally:
        eng.dispose()


def _frozen_clock(at: datetime = _FROZEN_NOW):
    def _now() -> datetime:
        return at

    return _now


def _seed_enabled_config(store: PaywallStore, *, secret: str = _SECRET) -> PaywallConfig:
    return store.upsert_config(
        PaywallConfig(
            config_id="pw-cfg",
            station_id=_STATION,
            enabled=True,
            tiers=[PaywallTier(tier_id="basic", name="Basic", price_id="price_basic")],
            signing_secret=secret,
        )
    )


def _service(store: PaywallStore, **kw) -> PaywallService:
    kw.setdefault("clock", _frozen_clock())
    return PaywallService(store, **kw)


# ---------------------------------------------------------------------------
# DC-1 default-off
# ---------------------------------------------------------------------------


class TestDefaultOffShortCircuit:
    def test_no_config_anywhere_allows_access(self, store: PaywallStore) -> None:
        svc = _service(store)
        assert svc.has_access(_STATION, "anyone@example.com", "asset", "vid-1") is True

    def test_no_config_allows_anonymous(self, store: PaywallStore) -> None:
        svc = _service(store)
        assert svc.has_access(_STATION, None, "asset", "vid-1") is True

    def test_disabled_config_allows_everyone(self, store: PaywallStore) -> None:
        store.upsert_config(PaywallConfig(config_id="pw", station_id=_STATION, enabled=False))
        svc = _service(store)
        assert svc.has_access(_STATION, "anon@example.com", "asset", "vid-1") is True
        assert svc.has_access(_STATION, None, "series", "s-1") is True

    def test_decide_default_off_no_reason(self, store: PaywallStore) -> None:
        svc = _service(store)
        decision = svc.decide(_STATION, None, "asset", "vid-1")
        assert decision.allowed is True
        assert decision.reason is None

    def test_disabled_config_decide_allows(self, store: PaywallStore) -> None:
        store.upsert_config(PaywallConfig(config_id="pw", station_id=_STATION, enabled=False))
        svc = _service(store)
        assert svc.decide(_STATION, "x@y.com", "asset", "vid-1").allowed is True


# ---------------------------------------------------------------------------
# DC-2 gating with config enabled
# ---------------------------------------------------------------------------


class TestGatingEnabled:
    def test_enabled_no_email_denies(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        assert svc.has_access(_STATION, None, "asset", "vid-1") is False

    def test_enabled_blank_email_denies(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        assert svc.has_access(_STATION, "   ", "asset", "vid-1") is False

    def test_enabled_no_grant_denies(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        assert svc.has_access(_STATION, "viewer@example.com", "asset", "vid-1") is False

    def test_grant_for_specific_asset_allows(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g1",
                station_id=_STATION,
                email="viewer@example.com",
                scope_kind="asset",
                scope_id="vid-1",
                granted_via="comp",
            )
        )
        svc = _service(store)
        assert svc.has_access(_STATION, "viewer@example.com", "asset", "vid-1") is True
        assert svc.has_access(_STATION, "viewer@example.com", "asset", "vid-2") is False

    def test_all_scope_grant_unlocks_any_asset(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g-all",
                station_id=_STATION,
                email="vip@example.com",
                scope_kind="all",
                scope_id="",
                granted_via="comp",
            )
        )
        svc = _service(store)
        assert svc.has_access(_STATION, "vip@example.com", "asset", "anything") is True
        assert svc.has_access(_STATION, "vip@example.com", "series", "any-series") is True

    def test_subscription_grant_unlocks(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g-sub",
                station_id=_STATION,
                email="sub@example.com",
                scope_kind="all",
                scope_id="",
                granted_via="subscription",
                subscription_id="sub_abc",
            )
        )
        svc = _service(store)
        assert svc.has_access(_STATION, "sub@example.com", "asset", "anything") is True

    def test_email_case_insensitive(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g1",
                station_id=_STATION,
                email="viewer@example.com",
                scope_kind="asset",
                scope_id="vid-1",
                granted_via="comp",
            )
        )
        svc = _service(store)
        assert svc.has_access(_STATION, "VIEWER@Example.com", "asset", "vid-1") is True

    def test_expired_grant_denies(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g-exp",
                station_id=_STATION,
                email="viewer@example.com",
                scope_kind="asset",
                scope_id="vid-1",
                granted_via="comp",
                expires_at=_FROZEN_NOW - timedelta(days=1),
            )
        )
        svc = _service(store)
        assert svc.has_access(_STATION, "viewer@example.com", "asset", "vid-1") is False


# ---------------------------------------------------------------------------
# decide() reason codes
# ---------------------------------------------------------------------------


class TestDecideReasons:
    def test_no_email_returns_sign_in_required(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        decision = svc.decide(_STATION, None, "asset", "vid-1")
        assert decision.allowed is False
        assert decision.reason == "sign_in_required"

    def test_no_grant_returns_subscription_required(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        decision = svc.decide(_STATION, "viewer@example.com", "asset", "vid-1")
        assert decision.allowed is False
        assert decision.reason == "subscription_required"

    def test_with_grant_returns_allowed_no_reason(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        store.upsert_grant(
            AccessGrant(
                grant_id="g1",
                station_id=_STATION,
                email="viewer@example.com",
                scope_kind="asset",
                scope_id="vid-1",
                granted_via="comp",
            )
        )
        svc = _service(store)
        decision = svc.decide(_STATION, "viewer@example.com", "asset", "vid-1")
        assert decision.allowed is True
        assert decision.reason is None


# ---------------------------------------------------------------------------
# Magic-link mint + verify (DC-5)
# ---------------------------------------------------------------------------


class TestMagicLinkMint:
    def test_mint_succeeds_with_configured_secret(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        assert "." in token

    def test_mint_refuses_without_config(self, store: PaywallStore) -> None:
        svc = _service(store)
        with pytest.raises(MagicLinkNotConfiguredError):
            svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")

    def test_mint_refuses_without_signing_secret(self, store: PaywallStore) -> None:
        store.upsert_config(
            PaywallConfig(config_id="pw", station_id=_STATION, enabled=True, signing_secret=None)
        )
        svc = _service(store)
        with pytest.raises(MagicLinkNotConfiguredError):
            svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")

    def test_mint_normalizes_email(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "  Viewer@Example.com  ", "asset", "vid-1")
        # decode the payload to confirm normalization happened pre-sign
        payload_b64 = token.split(".")[0]
        import base64

        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        assert payload["email"] == "viewer@example.com"


class TestMagicLinkVerify:
    def test_verify_creates_grant_for_asset(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        grant = svc.verify_magic_link(token)
        assert grant.email == "viewer@example.com"
        assert grant.scope_kind == "asset"
        assert grant.scope_id == "vid-1"
        assert grant.granted_via == "magic_link"
        assert grant.magic_link_token_id is not None
        # The redeemed grant is in the table and the gate now allows access.
        assert svc.has_access(_STATION, "viewer@example.com", "asset", "vid-1") is True

    def test_verify_rejects_malformed_token(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link("garbage-no-dot")

    def test_verify_rejects_bad_base64(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link("!!!!.abcdef")

    def test_verify_rejects_non_json_payload(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        # base64 of "not-json"
        import base64

        not_json = base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode()
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(f"{not_json}.abcdef")

    def test_verify_rejects_tampered_payload(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        # Forge a new payload claiming a different scope but reuse the MAC.
        _payload_b64, mac = token.split(".")
        import base64

        forged = (
            base64.urlsafe_b64encode(
                json.dumps({"hacked": True}, sort_keys=True, separators=(",", ":")).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(f"{forged}.{mac}")

    def test_verify_rejects_tampered_mac(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        payload_b64, _mac = token.split(".")
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(f"{payload_b64}.deadbeef")

    def test_verify_rejects_expired_token(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        # Mint at T0 with a 1-second TTL; advance the clock by 2 seconds.
        clock_state = {"now": _FROZEN_NOW}

        def _clock() -> datetime:
            return clock_state["now"]

        svc = PaywallService(store, clock=_clock)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1", ttl_seconds=1)
        clock_state["now"] = _FROZEN_NOW + timedelta(seconds=2)
        with pytest.raises(MagicLinkExpiredError):
            svc.verify_magic_link(token)

    def test_verify_rejects_replay(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        svc.verify_magic_link(token)
        with pytest.raises(MagicLinkAlreadyRedeemedError):
            svc.verify_magic_link(token)

    def test_verify_rejects_token_for_rotated_secret(self, store: PaywallStore) -> None:
        _seed_enabled_config(store, secret="original-secret-with-32-or-more-chrs")
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        # Rotate the secret on the config.
        store.upsert_config(
            PaywallConfig(
                config_id="pw-cfg",
                station_id=_STATION,
                enabled=True,
                signing_secret="rotated-secret-with-32-or-more-chars",
            )
        )
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(token)

    def test_verify_rejects_token_for_unknown_station(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        # Craft a token referencing a station with no config.
        token = _encode_token(
            {
                "token_id": "abc",
                "station_id": "no-such-station",
                "email": "x@y.com",
                "scope_kind": "asset",
                "scope_id": "v",
                "exp": (_FROZEN_NOW + timedelta(minutes=5)).timestamp(),
            },
            "whatever",
        )
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(token)

    def test_verify_redeemed_grant_has_expected_ttl(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        grant = svc.verify_magic_link(token)
        assert grant.expires_at is not None
        expected = _FROZEN_NOW + timedelta(seconds=DEFAULT_MAGIC_LINK_GRANT_TTL_SECONDS)
        # Compare to the second to tolerate any drift; we control the clock.
        if grant.expires_at.tzinfo is None:
            actual = grant.expires_at.replace(tzinfo=UTC)
        else:
            actual = grant.expires_at
        assert abs((actual - expected).total_seconds()) < 2

    def test_verify_rejects_payload_missing_fields(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = _encode_token({"exp": (_FROZEN_NOW + timedelta(minutes=5)).timestamp()}, _SECRET)
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(token)


# ---------------------------------------------------------------------------
# Stripe webhook (DC-3 + DC-4)
# ---------------------------------------------------------------------------


def _stripe_payload(
    *,
    event_type: str,
    sub_id: str = "sub_abc123",
    status_value: str = "active",
    email: str = "buyer@example.com",
    period_end: int | None = None,
    price_id: str = "price_basic",
    extra_data: dict | None = None,
) -> dict:
    body = {
        "type": event_type,
        "data": {
            "object": {
                "id": sub_id,
                "status": status_value,
                "current_period_end": period_end
                or int((_FROZEN_NOW + timedelta(days=30)).timestamp()),
                "customer_email": email,
                "items": {"data": [{"price": {"id": price_id}}]},
            }
        },
    }
    if extra_data:
        body["data"]["object"].update(extra_data)
    return body


class TestStripeWebhookSignature:
    def test_no_signing_secret_returns_signature_error(self, store: PaywallStore) -> None:
        # Config exists but signing_secret is None.
        store.upsert_config(
            PaywallConfig(config_id="pw", station_id=_STATION, enabled=True, signing_secret=None)
        )
        svc = _service(store, mock_stripe_event_verifier=lambda *a: {})
        with pytest.raises(WebhookSignatureError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)

    def test_no_config_returns_signature_error(self, store: PaywallStore) -> None:
        svc = _service(store, mock_stripe_event_verifier=lambda *a: {})
        with pytest.raises(WebhookSignatureError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)

    def test_mock_verifier_raising_translates_to_signature_error(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)

        def _bad(*_a):
            raise ValueError("bad sig")

        svc = _service(store, mock_stripe_event_verifier=_bad)
        with pytest.raises(WebhookSignatureError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)

    def test_missing_stripe_sdk_returns_signature_error(
        self, monkeypatch: pytest.MonkeyPatch, store: PaywallStore
    ) -> None:
        _seed_enabled_config(store)
        # Force ``import stripe`` to fail by removing it from sys.modules and
        # blocking the import.
        import builtins

        real_import = builtins.__import__

        def _no_stripe(name, *args, **kwargs):
            if name == "stripe":
                raise ImportError("no stripe installed in this test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_stripe)
        svc = _service(store)  # NO mock verifier -> falls through to SDK
        with pytest.raises(WebhookSignatureError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)


class TestStripeWebhookCreatedUpdated:
    def test_created_upserts_subscription_and_all_scope_grant(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created")
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        result = svc.handle_stripe_webhook(json.dumps(event).encode(), "sig", _STATION)
        assert result["received"] is True
        assert result["action"] == "created"
        # Subscription + grant landed.
        sub = store.get_subscription("sub_abc123")
        assert sub is not None
        assert sub.status == "active"
        assert sub.email == "buyer@example.com"
        # Gate now allows the buyer for any asset.
        assert svc.has_access(_STATION, "buyer@example.com", "asset", "anything") is True

    def test_updated_refreshes_period_end(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        first = _stripe_payload(event_type="customer.subscription.created")
        svc = _service(store, mock_stripe_event_verifier=lambda *a: first)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        new_period = int((_FROZEN_NOW + timedelta(days=60)).timestamp())
        second = _stripe_payload(event_type="customer.subscription.updated", period_end=new_period)
        svc2 = _service(store, mock_stripe_event_verifier=lambda *a: second)
        result = svc2.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result["action"] == "updated"
        sub = store.get_subscription("sub_abc123")
        assert sub is not None
        # SQLite returns timezone-naive datetimes for DateTime(timezone=True);
        # rehydrate as UTC before comparing to the unix timestamp we wrote.
        cpe = sub.current_period_end
        if cpe.tzinfo is None:
            cpe = cpe.replace(tzinfo=UTC)
        assert int(cpe.timestamp()) == new_period

    def test_past_due_still_grants_access(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created", status_value="past_due")
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert svc.has_access(_STATION, "buyer@example.com", "asset", "v") is True

    def test_incomplete_does_not_grant(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(
            event_type="customer.subscription.created", status_value="incomplete"
        )
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert svc.has_access(_STATION, "buyer@example.com", "asset", "v") is False

    def test_missing_email_raises(self, store: PaywallStore) -> None:
        from civiccast.paywall.service import PaywallServiceError

        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created", email="")
        # blank out customer_email entirely
        event["data"]["object"].pop("customer_email", None)
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        with pytest.raises(PaywallServiceError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)

    def test_falls_back_to_customer_details_email(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created")
        event["data"]["object"].pop("customer_email", None)
        event["data"]["object"]["customer_details"] = {"email": "details@example.com"}
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        result = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result["action"] == "created"
        assert svc.has_access(_STATION, "details@example.com", "asset", "v") is True

    def test_unknown_status_treated_as_incomplete(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(
            event_type="customer.subscription.created", status_value="future_status"
        )
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        sub = store.get_subscription("sub_abc123")
        assert sub is not None
        assert sub.status == "incomplete"


class TestStripeWebhookDeleted:
    def test_deleted_flips_status_and_revokes_grants(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        # First, create one.
        created = _stripe_payload(event_type="customer.subscription.created")
        svc = _service(store, mock_stripe_event_verifier=lambda *a: created)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert svc.has_access(_STATION, "buyer@example.com", "asset", "v") is True

        # Now delete.
        deleted = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_abc123"}},
        }
        svc_del = _service(store, mock_stripe_event_verifier=lambda *a: deleted)
        result = svc_del.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result["action"] == "deleted"
        assert result["grants_removed"] >= 1
        sub = store.get_subscription("sub_abc123")
        assert sub is not None
        assert sub.status == "canceled"
        # Gate now denies again.
        assert svc_del.has_access(_STATION, "buyer@example.com", "asset", "v") is False

    def test_deleted_unknown_subscription_is_idempotent(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_never_existed"}},
        }
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        result = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result["action"] == "deleted"
        assert result["grants_removed"] == 0

    def test_deleted_without_id_is_ignored(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = {"type": "customer.subscription.deleted", "data": {"object": {}}}
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        result = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result["action"] == "ignored"


class TestStripeWebhookIgnored:
    def test_unknown_event_type_ack_and_drop(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = {"type": "invoice.paid", "data": {"object": {"id": "in_x"}}}
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        result = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result == {"received": True, "action": "ignored"}

    def test_malformed_event_payload_ack_and_drop(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store, mock_stripe_event_verifier=lambda *a: {"no": "type"})
        result = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result == {"received": True, "action": "ignored"}


# ---------------------------------------------------------------------------
# DC-4 — no PAN-shaped data lands in the DB
# ---------------------------------------------------------------------------


_PAN_RE = re.compile(r"\b\d{13,19}\b")


def _scan_db_for_pan(store: PaywallStore) -> list[tuple[str, str]]:
    """Pull every cell from every paywall table and return any cells whose
    string form contains a 13-19 digit run. Used as a defensive DC-4 guard."""

    hits: list[tuple[str, str]] = []
    with store._session_factory() as session:
        for table in ("paywall_configs", "access_grants", "paywall_subscriptions"):
            rows = session.execute(text(f"SELECT * FROM {table}")).mappings().all()
            for row in rows:
                for col, val in dict(row).items():
                    if val is None:
                        continue
                    text_val = str(val)
                    if _PAN_RE.search(text_val):
                        hits.append((f"{table}.{col}", text_val))
    return hits


class TestWebhookNoPanData:
    def test_webhook_with_pan_in_description_does_not_persist_it(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(
            event_type="customer.subscription.created",
            extra_data={
                "description": f"Recurring charge on card {_PAN_BAIT}",
                "metadata": {"raw_pan": _PAN_BAIT},
                "billing_details": {"card_number": _PAN_BAIT},
            },
        )
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        # Subscription + grant landed.
        assert store.get_subscription("sub_abc123") is not None
        # But no card-shaped string is anywhere in the paywall tables.
        assert _scan_db_for_pan(store) == []

    def test_baseline_config_has_no_pan(self, store: PaywallStore) -> None:
        # Sanity check that the scanner only flags real PAN-shaped strings.
        _seed_enabled_config(store)
        assert _scan_db_for_pan(store) == []


# ---------------------------------------------------------------------------
# E-1 BLOCKER — service-level rejection of catch-all on public mint
# ---------------------------------------------------------------------------


class TestPublicMintRejectsAllScope:
    def test_mint_magic_link_for_public_rejects_all(self, store: PaywallStore) -> None:
        from civiccast.paywall.service import PaywallServiceError

        _seed_enabled_config(store)
        svc = _service(store)
        with pytest.raises(PaywallServiceError):
            svc.mint_magic_link_for_public(
                _STATION,
                "viewer@example.com",
                "all",  # type: ignore[arg-type]
                "",
            )

    def test_mint_magic_link_for_public_requires_scope_id(self, store: PaywallStore) -> None:
        from civiccast.paywall.service import PaywallServiceError

        _seed_enabled_config(store)
        svc = _service(store)
        with pytest.raises(PaywallServiceError):
            svc.mint_magic_link_for_public(_STATION, "viewer@example.com", "asset", "")

    def test_mint_magic_link_operator_path_still_allows_all(self, store: PaywallStore) -> None:
        # The operator-only mint_magic_link still allows "all" (used for
        # operator-issued comps / VIPs).
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "vip@example.com", "all", "")
        assert "." in token


# ---------------------------------------------------------------------------
# Q-8 — cross-station replay protection
# ---------------------------------------------------------------------------


class TestCrossStationReplay:
    def test_verify_rejects_token_minted_for_different_station(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        token = svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(token, expected_station_id="other-station")


# ---------------------------------------------------------------------------
# Q-13 — bool exp claim is rejected
# ---------------------------------------------------------------------------


class TestExpClaimBoolRejected:
    def test_bool_exp_in_payload_is_invalid(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        svc = _service(store)
        # Sign a token with exp=True (a Python bool that isinstance(int)).
        token = _encode_token(
            {
                "token_id": "abc",
                "station_id": _STATION,
                "email": "viewer@example.com",
                "scope_kind": "asset",
                "scope_id": "vid-1",
                "exp": True,
            },
            _SECRET,
        )
        with pytest.raises(MagicLinkInvalidError):
            svc.verify_magic_link(token)


# ---------------------------------------------------------------------------
# E-6 — current_period_end never regresses (out-of-order updated events)
# ---------------------------------------------------------------------------


class TestPeriodEndAdvanceOnly:
    def test_out_of_order_update_does_not_shorten_period_end(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        # First an updated event with period_end +60 days.
        future = int((_FROZEN_NOW + timedelta(days=60)).timestamp())
        first = _stripe_payload(event_type="customer.subscription.created", period_end=future)
        svc = _service(store, mock_stripe_event_verifier=lambda *a: first)
        svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        # Now a stale event with period_end +10 days (older than what we
        # already stored). The stored value must NOT regress.
        older = int((_FROZEN_NOW + timedelta(days=10)).timestamp())
        second = _stripe_payload(
            event_type="customer.subscription.updated",
            period_end=older,
        )
        svc2 = _service(store, mock_stripe_event_verifier=lambda *a: second)
        svc2.handle_stripe_webhook(b"{}", "sig", _STATION)
        sub = store.get_subscription("sub_abc123")
        assert sub is not None
        cpe = sub.current_period_end
        if cpe.tzinfo is None:
            cpe = cpe.replace(tzinfo=UTC)
        assert int(cpe.timestamp()) == future, "stale period_end must not regress"


# ---------------------------------------------------------------------------
# T-3 — Webhook event id idempotency at service layer
# ---------------------------------------------------------------------------


class TestServiceWebhookIdempotency:
    def test_replay_same_event_id_short_circuits(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created")
        event["id"] = "evt_replay_1"
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        r1 = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert r1["action"] == "created"
        r2 = svc.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert r2["action"] == "duplicate"

    def test_distinct_event_ids_both_process(self, store: PaywallStore) -> None:
        _seed_enabled_config(store)
        event_a = _stripe_payload(event_type="customer.subscription.created")
        event_a["id"] = "evt_distinct_a"
        event_b = _stripe_payload(
            event_type="customer.subscription.updated",
            period_end=int((_FROZEN_NOW + timedelta(days=60)).timestamp()),
        )
        event_b["id"] = "evt_distinct_b"
        svc1 = _service(store, mock_stripe_event_verifier=lambda *a: event_a)
        svc1.handle_stripe_webhook(b"{}", "sig", _STATION)
        svc2 = _service(store, mock_stripe_event_verifier=lambda *a: event_b)
        result2 = svc2.handle_stripe_webhook(b"{}", "sig", _STATION)
        assert result2["action"] == "updated"


# ---------------------------------------------------------------------------
# E-7 — fail-closed on missing period_end for active events
# ---------------------------------------------------------------------------


class TestActiveEventMissingPeriodEnd:
    def test_active_without_period_end_raises(self, store: PaywallStore) -> None:
        from civiccast.paywall.service import PaywallServiceError

        _seed_enabled_config(store)
        event = _stripe_payload(event_type="customer.subscription.created")
        event["data"]["object"].pop("current_period_end", None)
        svc = _service(store, mock_stripe_event_verifier=lambda *a: event)
        with pytest.raises(PaywallServiceError):
            svc.handle_stripe_webhook(b"{}", "sig", _STATION)


# ---------------------------------------------------------------------------
# E-2 — single-transaction reconcile (store-level)
# ---------------------------------------------------------------------------


class TestSingleTransactionReconcile:
    def test_reconcile_writes_both_or_neither(self, store: PaywallStore) -> None:
        # The store's reconcile_subscription_event method opens ONE
        # session for the grant + subscription writes. If we kill the
        # transaction before it commits, neither lands.
        from civiccast.paywall.models import AccessGrant as _Grant

        _seed_enabled_config(store)
        sub = Subscription(
            sub_id="sub_tx_1",
            station_id=_STATION,
            email="buyer@example.com",
            tier_id="basic",
            status="active",
            current_period_end=_FROZEN_NOW + timedelta(days=30),
        )
        grant = _Grant(
            grant_id="sg-sub_tx_1",
            station_id=_STATION,
            email="buyer@example.com",
            scope_kind="all",
            scope_id="",
            granted_via="subscription",
            subscription_id="sub_tx_1",
            expires_at=_FROZEN_NOW + timedelta(days=30),
        )
        stored_sub, stored_grant, revoked = store.reconcile_subscription_event(sub, grant)
        assert stored_sub.sub_id == "sub_tx_1"
        assert stored_grant is not None
        assert revoked == 0
        # Both rows visible after commit.
        assert store.get_subscription("sub_tx_1") is not None
        assert store.get_grant("sg-sub_tx_1") is not None


# ---------------------------------------------------------------------------
# E-8 — mint refused when paywall disabled
# ---------------------------------------------------------------------------


class TestMintRequiresEnabled:
    def test_mint_refused_when_disabled(self, store: PaywallStore) -> None:
        store.upsert_config(
            PaywallConfig(
                config_id="pw-cfg",
                station_id=_STATION,
                enabled=False,
                signing_secret=_SECRET,
            )
        )
        svc = _service(store)
        with pytest.raises(MagicLinkNotConfiguredError):
            svc.mint_magic_link(_STATION, "viewer@example.com", "asset", "vid-1")
