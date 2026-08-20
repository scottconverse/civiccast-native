# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Central staff-route bearer authentication tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.auth.models import OperatorIdentity
from civiccast.auth.roles import roles_for_identity
from civiccast.auth.store import StaffTokenInvalidError, StaffTokenRevokedError
from civiccast.auth.tokens import (
    StaffAuthError,
    generate_configured_staff_token,
    verify_bearer_token,
)

_BREAKGLASS_TOKEN = "breakglass-token-00000000000000000000"
_MEETING_TOKEN = "meeting-token-0000000000000000000000"
_PUBLISH_TOKEN = "publish-token-0000000000000000000000"
_RECORDS_TOKEN = "records-token-0000000000000000000000"
_SETUP_TOKEN = "setup-token-000000000000000000000000"


class _InvalidStore:
    def verify_token(self, secret: str) -> OperatorIdentity:
        raise StaffTokenInvalidError("invalid")


class _RevokedStore:
    def verify_token(self, secret: str) -> OperatorIdentity:
        raise StaffTokenRevokedError("revoked")


def _assert_staff_routes_registered() -> None:
    app = create_app()
    # Included routers are grouped under nested sub-routers, so a flat
    # ``app.routes`` scan misses the staff paths. The OpenAPI schema is the
    # authoritative, routing-structure-independent view of registered paths.
    registered_paths = set(app.openapi().get("paths", {}))
    staff_paths = {p for p in registered_paths if p.startswith("/api/staff/")}
    assert staff_paths, "Expected CivicCast to register /api/staff/* routes."

    required_paths = {"/api/staff/records", "/api/staff/installer/first-run-plan"}
    assert required_paths <= registered_paths


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/staff/records", {"summary_id": "summary-1", "summary_status": "approved"}),
        ("GET", "/api/staff/installer/first-run-plan", None),
    ],
)
def test_missing_bearer_token_returns_401_for_registered_staff_routes(
    method: str,
    path: str,
    payload: object | None,
) -> None:
    _assert_staff_routes_registered()
    client = TestClient(create_app())

    response = client.request(method, path, json=payload)

    assert response.status_code == 401, (
        f"{method} {path} must be blocked by central /api/staff/* bearer auth "
        "before route validation or handler execution."
    )


def test_default_deterministic_token_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/first-run-plan")

    assert response.status_code == 401
    assert "CIVICCAST_STAFF_TOKENS is not configured" in response.json()["detail"]


def test_postgres_token_store_env_fallback_requires_explicit_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_BREAKGLASS_TOKEN}:operator-1:Operator One:operator",
    )
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", raising=False)

    with pytest.raises(StaffAuthError, match="Invalid staff bearer token"):
        verify_bearer_token(f"Bearer {_BREAKGLASS_TOKEN}", token_store=_InvalidStore())

    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    identity = verify_bearer_token(f"Bearer {_BREAKGLASS_TOKEN}", token_store=_InvalidStore())

    assert identity.operator_id == "operator-1"


def test_configured_staff_token_can_carry_v14_product_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_RECORDS_TOKEN}:records-1:Records Clerk:records_clerk",
    )

    identity = verify_bearer_token(f"Bearer {_RECORDS_TOKEN}")

    assert identity.scopes == ("records_clerk",)
    assert roles_for_identity(identity) == {"records_clerk"}


def test_staff_identity_endpoint_returns_v14_product_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_PUBLISH_TOKEN}:publish-1:Publish Operator:publish_operator,records_clerk",
    )
    client = TestClient(create_app(), headers={"Authorization": f"Bearer {_PUBLISH_TOKEN}"})

    response = client.get("/api/staff/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "operator_id": "publish-1",
        "operator_display_name": "Publish Operator",
        "token_id": response.json()["token_id"],
        "scopes": ["publish_operator", "records_clerk"],
        "roles": ["publish_operator", "records_clerk"],
    }
    assert response.json()["token_id"].startswith("env-")


def test_role_restricted_provider_mutation_rejects_records_clerk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_RECORDS_TOKEN}:records-1:Records Clerk:records_clerk;"
        f"{_SETUP_TOKEN}:setup-1:Setup Admin:setup_admin",
    )
    monkeypatch.setenv(
        "CIVICCAST_PROVIDER_CREDENTIALS_FILE",
        str(tmp_path / "provider-credentials.json"),
    )
    app = create_app()
    records_client = TestClient(app, headers={"Authorization": f"Bearer {_RECORDS_TOKEN}"})
    setup_client = TestClient(app, headers={"Authorization": f"Bearer {_SETUP_TOKEN}"})

    forbidden = records_client.post(
        "/api/staff/installer/provider-credentials",
        json={
            "provider_id": "youtube",
            "values": {"client_id": "client-id", "client_secret": "client-secret"},
        },
    )
    allowed = setup_client.post(
        "/api/staff/installer/provider-credentials",
        json={
            "provider_id": "youtube",
            "values": {"client_id": "client-id", "client_secret": "client-secret"},
        },
    )

    assert forbidden.status_code == 403
    assert "setup_admin" in forbidden.json()["detail"]
    assert allowed.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected_role"),
    [
        (
            "POST",
            "/api/staff/live/sessions",
            {
                "live_session_id": "council-live-room",
                "channel_id": "gov-ch12",
                "title": "Council live room",
            },
            "meeting_operator",
        ),
        (
            "POST",
            "/api/staff/installer/rehearsal",
            None,
            "meeting_operator",
        ),
        (
            "POST",
            "/api/staff/installer/support-bundle",
            {"operator_note": "Need help with rehearsal."},
            "support_admin",
        ),
        (
            "POST",
            "/api/staff/installer/restore/rehearsal",
            None,
            "setup_admin",
        ),
    ],
)
def test_v14_role_restricted_workflows_reject_unrelated_role(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: object | None,
    expected_role: str,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_RECORDS_TOKEN}:records-1:Records Clerk:records_clerk",
    )
    client = TestClient(create_app(), headers={"Authorization": f"Bearer {_RECORDS_TOKEN}"})

    response = client.request(method, path, json=payload)

    assert response.status_code == 403
    assert expected_role in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/staff/captions/review-items/review-1/approve", {"reviewer_note": "ok"}),
        ("/api/staff/captions/review-items/review-1/edit", {"text": "corrected"}),
        ("/api/staff/captions/review-items/review-1/reject", {"reviewer_note": "bad cue"}),
        ("/api/staff/summaries/summary-1/approve", {"approval_note": "checked"}),
        ("/api/staff/records", {"summary_id": "summary-1", "summary_status": "approved"}),
    ],
)
def test_v14_records_workflows_reject_meeting_operator(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: object,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_MEETING_TOKEN}:meeting-1:Meeting Operator:meeting_operator",
    )
    client = TestClient(create_app(), headers={"Authorization": f"Bearer {_MEETING_TOKEN}"})

    response = client.post(path, json=payload)

    assert response.status_code == 403
    assert "records_clerk" in response.json()["detail"]


def test_revoked_postgres_token_never_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_BREAKGLASS_TOKEN}:operator-1:Operator One:operator",
    )
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")

    with pytest.raises(StaffAuthError, match="revoked"):
        verify_bearer_token(f"Bearer {_BREAKGLASS_TOKEN}", token_store=_RevokedStore())


# ---------------------------------------------------------------------------
# QA-002 (Stage B+D audit): a staff token configured without roles must never
# silently receive full admin. Scott's decision: reject role-less env tokens at
# config load (the app refuses to start), and the role expansion itself is
# fail-closed so no future identity source can reintroduce the hole.
# ---------------------------------------------------------------------------


def test_empty_scope_env_token_is_rejected_at_config_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "noroles:op-1:No Roles Operator")

    with pytest.raises(StaffAuthError, match="no roles"):
        verify_bearer_token("Bearer noroles")


def test_unknown_scope_env_token_is_rejected_at_config_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "weird:op-1:Weird Operator:not_a_real_role")

    with pytest.raises(StaffAuthError, match="unknown role scope"):
        verify_bearer_token("Bearer weird")


def test_empty_scope_env_token_fails_app_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator gets a clear startup error, not a silently-admin token."""

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "noroles:op-1:No Roles Operator")

    with pytest.raises(StaffAuthError, match="no roles"):
        create_app()


def test_handwritten_env_token_fails_app_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A length-only lookalike must not satisfy the versioned-secret contract."""

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{'a' * 32}:op-1:Weak Token Operator:operator",
    )

    with pytest.raises(StaffAuthError, match="civiccast token generate-env"):
        create_app()


def test_low_complexity_versioned_env_token_fails_app_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"ccenv1_{'a' * 43}:op-1:Predictable Token Operator:operator",
    )

    with pytest.raises(StaffAuthError, match="civiccast token generate-env"):
        create_app()


def test_generated_env_token_passes_startup_and_authenticates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    token = generate_configured_staff_token()
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{token}:op-1:Generated Token Operator:operator",
    )

    client = TestClient(create_app())
    response = client.get(
        "/api/staff/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["operator_id"] == "op-1"


def test_roles_for_identity_is_fail_closed_for_empty_scopes() -> None:
    identity = OperatorIdentity(
        operator_id="op-1",
        operator_display_name="No Roles Operator",
        token_id="test-token-id",
        scopes=(),
    )

    assert roles_for_identity(identity) == set()


def test_station_operator_token_always_carries_admin_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The station-state first-admin path names a role explicitly (QA-002 check
    of `verify_station_operator_token` for the same empty-scope hole)."""

    import civiccast.installer.station_state as station_state

    salt = "test-salt"
    token = "station-token"
    monkeypatch.setattr(
        station_state,
        "_load_raw_state",
        lambda: {
            "admin": {"username": "first-admin", "display_name": "First Admin"},
            "operator_console": {
                "token_salt": salt,
                "token_hash": station_state._hash_token(token, salt=salt),
            },
        },
    )

    identity = station_state.verify_station_operator_token(token)

    assert identity is not None
    assert identity.scopes == ("admin",)
    assert roles_for_identity(identity) == {
        "setup_admin",
        "meeting_operator",
        "records_clerk",
        "publish_operator",
        "support_admin",
    }
