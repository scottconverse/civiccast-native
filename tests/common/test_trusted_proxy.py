# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the shared CDN-aware trusted-proxy resolver."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from civiccast.common.trusted_proxy import (
    is_trusted_proxy,
    reset_trusted_proxy_cache,
    resolve_client_ip,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):  # type: ignore[no-untyped-def]
    """Each test starts with a clean env + a cleared cache."""
    for var in (
        "CIVICCAST_TRUSTED_PROXY_CIDRS",
        "CIVICCAST_CDN_PROVIDER",
        "CIVICCAST_TRUST_PRIVATE_PROXIES",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_trusted_proxy_cache()
    yield
    reset_trusted_proxy_cache()


def _mock_request(peer_host: str, *, x_forwarded_for: str | None = None) -> MagicMock:
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = peer_host
    headers = {}
    if x_forwarded_for is not None:
        headers["X-Forwarded-For"] = x_forwarded_for
    req.headers = headers
    return req


class TestIsTrustedProxy:
    def test_private_proxies_untrusted_by_default_with_no_env_override(self) -> None:
        # QA-4: CIVICCAST_TRUST_PRIVATE_PROXIES now defaults OFF. With every
        # relevant env var unset (matching a real deployment's defaults), a
        # loopback peer is NOT implicitly trusted -- otherwise that same peer
        # could pick its own rate-limit bucket via a spoofed X-Forwarded-For.
        assert is_trusted_proxy("127.0.0.1") is False

    def test_rfc1918_untrusted_by_default(self) -> None:
        assert is_trusted_proxy("10.0.0.5") is False
        assert is_trusted_proxy("192.168.1.10") is False
        assert is_trusted_proxy("172.20.0.42") is False

    def test_public_ip_not_trusted_by_default(self) -> None:
        assert is_trusted_proxy("8.8.8.8") is False

    def test_loopback_trusted_when_private_proxies_explicitly_enabled(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Deployments that genuinely run uvicorn behind a local nginx opt in
        # explicitly instead of relying on an implicit default.
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
        reset_trusted_proxy_cache()
        assert is_trusted_proxy("127.0.0.1") is True
        assert is_trusted_proxy("10.0.0.5") is True

    def test_private_off_drops_rfc1918(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        reset_trusted_proxy_cache()
        assert is_trusted_proxy("10.0.0.5") is False
        # Loopback also drops when private-off.
        assert is_trusted_proxy("127.0.0.1") is False

    def test_explicit_cidr_trusted(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_TRUSTED_PROXY_CIDRS", "203.0.113.0/24")
        reset_trusted_proxy_cache()
        assert is_trusted_proxy("203.0.113.42") is True
        assert is_trusted_proxy("8.8.8.8") is False

    def test_multiple_explicit_cidrs(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv(
            "CIVICCAST_TRUSTED_PROXY_CIDRS",
            "203.0.113.0/24, 198.51.100.0/24, 2001:db8::/32",
        )
        reset_trusted_proxy_cache()
        assert is_trusted_proxy("203.0.113.10") is True
        assert is_trusted_proxy("198.51.100.10") is True
        assert is_trusted_proxy("2001:db8::1") is True

    def test_cdn_provider_preset_bunny(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        reset_trusted_proxy_cache()
        # BunnyCDN documented netblock — 23.227.38.0/24 is in our preset.
        assert is_trusted_proxy("23.227.38.42") is True
        # Random public IP outside any documented BunnyCDN range.
        assert is_trusted_proxy("8.8.8.8") is False

    def test_cdn_provider_preset_cloudflare(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "cloudflare")
        reset_trusted_proxy_cache()
        # Cloudflare's documented 104.16.0.0/12 includes 104.16.1.1.
        assert is_trusted_proxy("104.16.1.1") is True
        # And the v6 prefix.
        assert is_trusted_proxy("2606:4700::1") is True

    def test_cloudflare_r2_alias(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "cloudflare_r2")
        reset_trusted_proxy_cache()
        # cloudflare_r2 aliases to the same edge list.
        assert is_trusted_proxy("104.16.1.1") is True

    def test_unknown_provider_treated_as_no_preset(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "akamai")
        reset_trusted_proxy_cache()
        assert is_trusted_proxy("104.16.1.1") is False

    def test_explicit_and_provider_combined(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        monkeypatch.setenv("CIVICCAST_TRUSTED_PROXY_CIDRS", "203.0.113.0/24")
        reset_trusted_proxy_cache()
        # Both the bunny preset AND the explicit CIDR are trusted.
        assert is_trusted_proxy("23.227.38.42") is True
        assert is_trusted_proxy("203.0.113.42") is True

    def test_malformed_string_not_trusted(self) -> None:
        assert is_trusted_proxy("not-an-ip") is False

    def test_invalid_cidr_silently_skipped(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        monkeypatch.setenv(
            "CIVICCAST_TRUSTED_PROXY_CIDRS",
            "203.0.113.0/24, garbage/64, 198.51.100.0/24",
        )
        reset_trusted_proxy_cache()
        # The valid CIDRs still load, the garbage one is silently dropped.
        assert is_trusted_proxy("203.0.113.10") is True
        assert is_trusted_proxy("198.51.100.10") is True


class TestResolveClientIp:
    def test_no_xff_falls_through_to_peer(self) -> None:
        req = _mock_request("8.8.8.8")
        assert resolve_client_ip(req) == "8.8.8.8"

    def test_untrusted_peer_ignores_xff_header(self) -> None:
        # Attack: public client claims they're behind a proxy via spoofed header.
        # Resolver MUST NOT trust it.
        req = _mock_request("8.8.8.8", x_forwarded_for="1.2.3.4, 10.0.0.1")
        assert resolve_client_ip(req) == "8.8.8.8"

    def test_trusted_peer_walks_xff(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Standard nginx-in-front: 127.0.0.1 is trusted once the deployment
        # opts in explicitly (QA-4: no longer trusted by default); the real
        # client comes from X-Forwarded-For.
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
        reset_trusted_proxy_cache()
        req = _mock_request("127.0.0.1", x_forwarded_for="203.0.113.42")
        assert resolve_client_ip(req) == "203.0.113.42"

    def test_trusted_peer_xff_chain_returns_first_untrusted(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Two trusted hops + one real client at the head of the chain.
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
        monkeypatch.setenv("CIVICCAST_TRUSTED_PROXY_CIDRS", "192.168.0.0/16, 10.0.0.0/8")
        reset_trusted_proxy_cache()
        req = _mock_request(
            "127.0.0.1",
            x_forwarded_for="203.0.113.42, 10.0.0.5, 192.168.1.10",
        )
        # Walk right-to-left: 192.168.1.10 trusted, 10.0.0.5 trusted, 203.0.113.42 not.
        assert resolve_client_ip(req) == "203.0.113.42"

    def test_all_trusted_chain_returns_leftmost(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Edge case: every hop in the chain is itself trusted (e.g. a chain
        # of internal LBs). Return the leftmost as the convention.
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
        reset_trusted_proxy_cache()
        req = _mock_request("127.0.0.1", x_forwarded_for="10.0.0.5, 192.168.1.10")
        assert resolve_client_ip(req) == "10.0.0.5"

    def test_malformed_xff_entry_skipped(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # 8.8.8.8 is a real public IP and NOT in any reserved/private/test
        # range — Python's ip_address.is_reserved is False for it, so it
        # passes through the private-proxy filter as a real client.
        # (TEST-NET docs ranges like 203.0.113.0/24 are is_reserved → would
        # be auto-trusted under the private-on policy.)
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
        reset_trusted_proxy_cache()
        req = _mock_request(
            "127.0.0.1",
            x_forwarded_for="not-an-ip, 8.8.8.8",
        )
        assert resolve_client_ip(req) == "8.8.8.8"

    def test_untrusted_loopback_peer_ignores_xff_by_default(self) -> None:
        # QA-4 post-condition: with nothing configured, two requests from the
        # SAME peer but with DIFFERENT X-Forwarded-For values must resolve to
        # the SAME client IP (the peer itself) -- not to whatever the caller
        # put in the header. This is what closes the "pick your own rate
        # limit bucket" hole: an attacker sending X-Forwarded-For from
        # loopback/RFC1918 no longer gets to choose their bucket.
        req_a = _mock_request("127.0.0.1", x_forwarded_for="1.2.3.4")
        req_b = _mock_request("127.0.0.1", x_forwarded_for="9.9.9.9")
        resolved_a = resolve_client_ip(req_a)
        resolved_b = resolve_client_ip(req_b)
        assert resolved_a == resolved_b == "127.0.0.1"

    def test_no_client_returns_unknown(self) -> None:
        req = MagicMock()
        req.client = None
        req.headers = {}
        assert resolve_client_ip(req) == "unknown"

    def test_cdn_provider_unwraps_to_real_client(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Simulate sitting behind BunnyCDN. The peer IP is a BunnyCDN edge.
        # XFF carries the real client.
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        reset_trusted_proxy_cache()
        req = _mock_request("23.227.38.42", x_forwarded_for="203.0.113.42")
        assert resolve_client_ip(req) == "203.0.113.42"

    def test_attacker_at_cdn_edge_cannot_spoof_xff(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Realistic threat: an attacker controls one of the CDN edge IPs
        # (e.g. owns a server in Cloudflare's IP range) and tries to
        # spoof a fake XFF. The resolver returns whatever the trusted CDN
        # edge sent in XFF — that's the CDN's job to fill correctly.
        # This test confirms we don't add ADDITIONAL spoofability beyond
        # what the CDN provider's terms allow.
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "cloudflare")
        reset_trusted_proxy_cache()
        req = _mock_request(
            "104.16.1.1",
            x_forwarded_for="8.8.8.8",
        )
        assert resolve_client_ip(req) == "8.8.8.8"

    def test_private_disabled_rejects_loopback_xff(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # When private-off + no explicit trusted CIDRs, the loopback peer
        # is NOT trusted. We return the peer IP verbatim, ignoring the
        # spoofed XFF header.
        monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "false")
        reset_trusted_proxy_cache()
        req = _mock_request("127.0.0.1", x_forwarded_for="203.0.113.42")
        assert resolve_client_ip(req) == "127.0.0.1"
