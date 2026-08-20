# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for POST /api/staff/installer/cdn-concierge/r2 (the R2 concierge endpoint)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer.models import ProviderConnectionTestResponse
from civiccast.installer.r2_concierge import ConciergeResult

_TOKEN = "cf-token-super-secret-value"
_SUCCESS_RESULT = ConciergeResult(
    status="success",
    message="R2 storage is ready: bucket created and its public domain enabled.",
    account_id="acct-1",
    bucket="civiccast-media",
    public_base_url="https://pub-abc123.r2.dev",
    credential_fields={
        "account_id": "acct-1",
        "access_key_id": "token-id-1",
        "secret_access_key": "derived-secret-should-never-leak",
        "bucket": "civiccast-media",
        "public_base_url": "https://pub-abc123.r2.dev",
    },
)


@pytest.fixture
def creds_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "provider-credentials.json"
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(path))
    return path


def _client() -> TestClient:
    return TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})


def test_happy_path_stores_credentials_and_scrubs_secrets(creds_env: Path) -> None:
    with (
        patch("civiccast.installer.router.provision_r2", return_value=_SUCCESS_RESULT) as provision,
        patch(
            "civiccast.installer.router.check_provider_connection",
            return_value=ProviderConnectionTestResponse(
                provider_id="cloudflare-r2", status="ok", message="Connected to the CDN."
            ),
        ),
    ):
        response = _client().post(
            "/api/staff/installer/cdn-concierge/r2",
            json={"token": _TOKEN, "bucket_name": "civiccast-media"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["bucket"] == "civiccast-media"
    assert body["public_base_url"] == "https://pub-abc123.r2.dev"
    serialized = json.dumps(body)
    assert _TOKEN not in serialized
    assert "derived-secret-should-never-leak" not in serialized

    # provision_r2 was called with the token (in-memory only) and never with
    # a leftover default other than what was posted.
    assert provision.call_args.args[0] == _TOKEN

    # the derived credentials were actually persisted via the existing store.
    from civiccast.installer.service import stored_provider_field_values

    stored = stored_provider_field_values("cloudflare-r2")
    assert stored["access_key_id"] == "token-id-1"
    assert stored["bucket"] == "civiccast-media"
    # the raw pasted token itself is not among the stored provider fields.
    assert _TOKEN not in json.dumps(stored)


def test_r2_not_enabled_error_propagates_with_deep_link_and_does_not_store(creds_env: Path) -> None:
    error_result = ConciergeResult(
        status="error",
        error_code="r2_not_enabled",
        message="R2 is not enabled on this Cloudflare account yet.",
        deep_link="https://dash.cloudflare.com/?to=/:account/r2",
    )
    with (
        patch("civiccast.installer.router.provision_r2", return_value=error_result),
        patch("civiccast.installer.router.save_provider_credentials") as save,
    ):
        response = _client().post(
            "/api/staff/installer/cdn-concierge/r2",
            json={"token": _TOKEN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "r2_not_enabled"
    assert body["deep_link"] == "https://dash.cloudflare.com/?to=/:account/r2"
    save.assert_not_called()


def test_health_check_failure_after_successful_provisioning_is_reported_failed(
    creds_env: Path,
) -> None:
    with (
        patch("civiccast.installer.router.provision_r2", return_value=_SUCCESS_RESULT),
        patch(
            "civiccast.installer.router.check_provider_connection",
            return_value=ProviderConnectionTestResponse(
                provider_id="cloudflare-r2", status="failed", message="Could not reach the CDN."
            ),
        ),
    ):
        response = _client().post(
            "/api/staff/installer/cdn-concierge/r2",
            json={"token": _TOKEN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "Could not reach the CDN." in body["message"]


def test_endpoint_requires_setup_admin_role(
    monkeypatch: pytest.MonkeyPatch, creds_env: Path
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "limited-token:limited:Limited Operator:meeting_operator"
    )
    with patch("civiccast.installer.router.provision_r2") as provision:
        response = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"}).post(
            "/api/staff/installer/cdn-concierge/r2", json={"token": _TOKEN}
        )

    assert response.status_code == 403
    provision.assert_not_called()


def test_bucket_name_is_validated_by_the_request_schema(creds_env: Path) -> None:
    with patch("civiccast.installer.router.provision_r2") as provision:
        response = _client().post(
            "/api/staff/installer/cdn-concierge/r2",
            json={"token": _TOKEN, "bucket_name": "Not Valid!"},
        )

    assert response.status_code == 422
    provision.assert_not_called()
