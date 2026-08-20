# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Security headers + CORS policy coverage (audit item #27)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.auth.cors import cors_allowed_origins


def test_health_response_carries_hardening_headers() -> None:
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_packaged_operator_console_html_carries_the_same_headers(monkeypatch, tmp_path) -> None:
    operator_dist = tmp_path / "operator-dist"
    operator_dist.mkdir()
    (operator_dist / "index.html").write_text("<h1>Operator console</h1>", encoding="utf-8")
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(operator_dist))
    client = TestClient(create_app())

    response = client.get("/operator/")

    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


def test_cors_allowed_origins_defaults_to_empty(monkeypatch) -> None:
    monkeypatch.delenv("CIVICCAST_CORS_ALLOWED_ORIGINS", raising=False)
    assert cors_allowed_origins() == []


def test_cors_allowed_origins_fails_loud_on_any_wildcard_entry(monkeypatch) -> None:
    """A wildcard is a startup error, not a silent no-op: `*` would open a
    LAN-exposed box, and a typo like `*.example.com` would never match and
    send the operator chasing phantom CORS failures."""

    for bad in ("*", "*.example.com", "https://*.example.org"):
        monkeypatch.setenv("CIVICCAST_CORS_ALLOWED_ORIGINS", bad)
        with pytest.raises(ValueError, match="wildcard"):
            cors_allowed_origins()


def test_cors_allowed_origins_parses_explicit_list(monkeypatch) -> None:
    monkeypatch.setenv(
        "CIVICCAST_CORS_ALLOWED_ORIGINS", "https://dash.example.org, https://ops.example.org"
    )
    assert cors_allowed_origins() == ["https://dash.example.org", "https://ops.example.org"]


def test_no_cors_headers_without_explicit_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("CIVICCAST_CORS_ALLOWED_ORIGINS", raising=False)
    client = TestClient(create_app())

    response = client.get("/health", headers={"Origin": "https://evil.example.org"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_reflects_only_the_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_CORS_ALLOWED_ORIGINS", "https://dash.example.org")
    client = TestClient(create_app())

    allowed = client.get("/health", headers={"Origin": "https://dash.example.org"})
    denied = client.get("/health", headers={"Origin": "https://evil.example.org"})

    assert allowed.headers.get("Access-Control-Allow-Origin") == "https://dash.example.org"
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_staff_route_preflight_gets_cors_headers_without_a_bearer_token(monkeypatch) -> None:
    """A browser's CORS preflight OPTIONS never carries an Authorization
    header. If staff_auth_middleware runs outside (before) CORSMiddleware,
    the preflight gets a bare 401 with no CORS headers and the browser
    never sends the real request -- the CORS opt-in is inoperative for
    every /api/staff/* route, exactly the surface it exists to protect."""

    monkeypatch.setenv("CIVICCAST_CORS_ALLOWED_ORIGINS", "https://dashboard.example.org")
    client = TestClient(create_app())

    response = client.options(
        "/api/staff/auth/me",
        headers={
            "Origin": "https://dashboard.example.org",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("Access-Control-Allow-Origin") == "https://dashboard.example.org"
    assert response.status_code != 401


def test_staff_route_real_request_still_requires_bearer_token_with_cors_enabled(
    monkeypatch,
) -> None:
    """The preflight fix must not weaken auth on the actual request."""

    monkeypatch.setenv("CIVICCAST_CORS_ALLOWED_ORIGINS", "https://dashboard.example.org")
    client = TestClient(create_app())

    response = client.get("/api/staff/auth/me", headers={"Origin": "https://dashboard.example.org"})

    assert response.status_code == 401
