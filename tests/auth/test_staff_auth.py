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
    StaffAuthMissingCredentialError,
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
        ("POST", "/api/staff/auth/sign-out", None),
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


def test_missing_bearer_token_raises_the_missing_credential_subclass() -> None:
    """Day-one-lockout audit finding #1: a missing Authorization header is a
    distinct condition from a present-but-wrong token. verify_bearer_token(None)
    must raise the StaffAuthMissingCredentialError subclass specifically (not
    just any StaffAuthError) so civiccast.auth.middleware.staff_auth_middleware
    -- and any future caller -- can tell "no credential offered" apart from
    "a credential was offered and it was wrong" without re-parsing the
    exception message."""

    with pytest.raises(StaffAuthMissingCredentialError):
        verify_bearer_token(None)
    with pytest.raises(StaffAuthMissingCredentialError):
        verify_bearer_token("")


def test_present_but_malformed_token_raises_the_base_class_not_the_subclass() -> None:
    """A header that IS present, just malformed (wrong scheme, empty token
    after 'Bearer '), is a failed credential guess like any other -- it must
    NOT be classified as "missing" or it would silently escape the
    brute-force budget too."""

    with pytest.raises(StaffAuthError) as excinfo:
        verify_bearer_token("Bearer")
    assert not isinstance(excinfo.value, StaffAuthMissingCredentialError)

    with pytest.raises(StaffAuthError) as excinfo:
        verify_bearer_token("Basic dXNlcjpwYXNz")
    assert not isinstance(excinfo.value, StaffAuthMissingCredentialError)


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


_FIRST_ADMIN_SETUP = {
    "station_name": "Pinegrove School Board",
    "admin_display_name": "Avery Admin",
    "admin_username": "avery",
    "admin_password": "correct horse battery staple",
    "recovery_kit_destination": "printed and stored in the clerk safe",
}
_FIRST_ADMIN_LOGIN = {"admin_username": "avery", "admin_password": "correct horse battery staple"}


def test_sign_out_revokes_only_the_calling_station_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """2026-09-09 walkthrough: the console had no sign-out. POST /api/staff/auth/
    sign-out must end exactly the caller's operator-console session and leave
    every other signed-in browser valid (the mirror of sessions/revoke-others)."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    setup = client.post("/api/setup/first-admin", json=_FIRST_ADMIN_SETUP)
    assert setup.status_code == 200
    other_browser_token = setup.json()["operator_console_token"]
    caller_token = client.post("/api/setup/login", json=_FIRST_ADMIN_LOGIN).json()[
        "operator_console_token"
    ]

    caller = TestClient(create_app(), headers={"Authorization": f"Bearer {caller_token}"})
    other = TestClient(create_app(), headers={"Authorization": f"Bearer {other_browser_token}"})
    assert caller.get("/api/staff/auth/me").status_code == 200

    response = caller.post("/api/staff/auth/sign-out")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_out"
    assert body["session_revoked"] is True
    # The caller's token is dead...
    assert caller.get("/api/staff/auth/me").status_code == 401
    # ...and the other browser is untouched.
    assert other.get("/api/staff/auth/me").status_code == 200
    # Signing out twice with the dead token is an ordinary 401, not a 500.
    assert caller.post("/api/staff/auth/sign-out").status_code == 401


def test_sign_out_revokes_a_lifecycle_store_token_through_the_store() -> None:
    from civiccast.auth.store import InMemoryStaffTokenStore

    store = InMemoryStaffTokenStore()
    issued = store.issue_token(operator_id="operator-a", operator_display_name="Operator A")
    app = create_app()
    app.state.staff_token_store = store
    client = TestClient(app, headers={"Authorization": f"Bearer {issued.secret}"})
    assert client.get("/api/staff/auth/me").status_code == 200

    response = client.post("/api/staff/auth/sign-out")

    assert response.status_code == 200
    assert response.json()["session_revoked"] is True
    revoked = client.get("/api/staff/auth/me")
    assert revoked.status_code == 401
    assert "revoked" in revoked.json()["detail"]
    assert any(
        event.token_id == issued.metadata.token_id and event.event_type == "revoked"
        for event in store.audit_events()
    )


def test_sign_out_with_an_env_configured_token_reports_it_cannot_be_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_PUBLISH_TOKEN}:publish-1:Publish Operator:publish_operator,records_clerk",
    )
    client = TestClient(create_app(), headers={"Authorization": f"Bearer {_PUBLISH_TOKEN}"})

    response = client.post("/api/staff/auth/sign-out")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_out"
    assert body["session_revoked"] is False
    assert "CIVICCAST_STAFF_TOKENS" in body["message"]
    # An env token has no server-side record to revoke: it still authenticates.
    assert client.get("/api/staff/auth/me").status_code == 200
