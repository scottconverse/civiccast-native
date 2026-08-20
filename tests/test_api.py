# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI endpoint tests via TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civiccast._version import __version__
from civiccast.app import create_app


def test_health_returns_200() -> None:
    """Liveness only: the process answers 200 and names its build.

    Readiness (the ``status`` field) is a separate contract and is pinned in
    tests/test_health_readiness.py -- this client never enters the lifespan, so
    the schema check has not run and there is no readiness verdict to assert.
    """
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == __version__
    assert body["status"] in ("healthy", "degraded")


def test_health_reports_exact_bundled_runtime_build(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    build_id = "a" * 64
    monkeypatch.setenv("CIVICCAST_RUNTIME_BUILD_ID", build_id)
    body = TestClient(create_app()).get("/health").json()
    assert body["runtime_build_id"] == build_id


def test_health_and_version_report_the_native_override_when_set(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Chain J (2026-08-02): a native station's control plane sets
    CIVICCAST_NATIVE_REPORTED_VERSION (civiccast.native.station_runtime.
    native_reported_version_environment, from civiccast._native_version) so
    /health and /api/version report the native line's own version -- kept
    separate from the WSL line's civiccast._version.__version__, which every
    other hosting context (this default one included) still reports."""
    monkeypatch.setenv("CIVICCAST_NATIVE_REPORTED_VERSION", "1.0.0-beta.7")
    client = TestClient(create_app())

    assert client.get("/health").json()["version"] == "1.0.0-beta.7"
    assert client.get("/api/version").json() == {"version": "1.0.0-beta.7"}


def test_health_and_version_fall_back_to_the_wsl_version_when_the_native_override_is_unset() -> (
    None
):
    """The exact pre-chain-J behavior, preserved for every hosting context
    that never sets CIVICCAST_NATIVE_REPORTED_VERSION -- including the WSL
    product line."""
    client = TestClient(create_app())

    assert client.get("/health").json()["version"] == __version__
    assert client.get("/api/version").json() == {"version": __version__}


def test_api_health_alias_returns_200() -> None:
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == __version__


def test_version_endpoint() -> None:
    client = TestClient(create_app())
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}


def test_hardware_endpoint_shape() -> None:
    """The endpoint is the JSON serialization of the hardware probe — same shape, different transport."""
    client = TestClient(create_app())
    r = client.get("/api/hardware")
    assert r.status_code == 200
    body = r.json()
    assert "cpu" in body
    assert "ram" in body
    assert "disk" in body
    assert "os" in body
    assert "recommended_tier" in body
    assert body["civiccast_version"] == __version__


def test_hardware_endpoint_tier_is_known_value() -> None:
    client = TestClient(create_app())
    r = client.get("/api/hardware")
    assert r.json()["recommended_tier"] in ("tier-0", "tier-1", "tier-1-plus", "tier-2")


def test_openapi_schema_includes_hardware() -> None:
    """The OpenAPI doc surfaces /api/hardware so integrators can codegen against it."""
    client = TestClient(create_app())
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "/api/hardware" in schema["paths"]
    assert "/health" in schema["paths"]
    assert "/api/health" not in schema["paths"]
    assert "/api/version" in schema["paths"]


def test_openapi_schema_declares_staff_bearer_auth() -> None:
    client = TestClient(create_app())

    schema = client.get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["CivicCastStaffBearer"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "CivicCast staff token",
        "description": (
            "CivicCast staff bearer token issued with `civiccast token issue` "
            "or configured through the legacy environment-token path."
        ),
    }
    staff_operations = [
        operation
        for path, path_item in schema["paths"].items()
        if path.startswith("/api/staff/")
        for method, operation in path_item.items()
        if method in {"delete", "get", "patch", "post", "put"}
    ]
    assert staff_operations
    assert all(
        operation["security"] == [{"CivicCastStaffBearer": []}] for operation in staff_operations
    )
    assert all("401" in operation["responses"] for operation in staff_operations)
