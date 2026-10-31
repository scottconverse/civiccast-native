# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""R9: rejected credential requests must never echo their submitted secrets."""

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from civiccast.app import create_app

CANARY = "public-test-secret-never-echo"
ORIGINAL_USERNAME_CANARY = "NONACCOUNT_CANARY"
ORIGINAL_PASSWORD_CANARY = "PUBLIC_TEST_SENTINEL_PASSWORD_A"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param(
            "/api/setup/login",
            {"username": ORIGINAL_USERNAME_CANARY, "password": ORIGINAL_PASSWORD_CANARY},
            id="original-setup-wrong-fields",
        ),
        ("/api/setup/login", {"admin_username": "operator", "admin_password": {"nested": CANARY}}),
        ("/api/staff/auth/login", {"username": "operator", "password": [CANARY]}),
        ("/api/setup/recover", {"recovery_code": CANARY, "new_admin_password": CANARY}),
        ("/api/setup/login", {CANARY: {"nested": CANARY}}),
    ],
)
def test_credential_validation_does_not_echo_input(path, payload, caplog) -> None:
    caplog.set_level("DEBUG")
    client = TestClient(create_app())

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert CANARY not in response.text
    assert CANARY not in caplog.text
    for sentinel in (ORIGINAL_USERNAME_CANARY, ORIGINAL_PASSWORD_CANARY):
        assert sentinel not in response.text
        assert sentinel not in caplog.text
    errors = response.json()["detail"]
    assert errors
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert all(error["loc"][0] == "body" for error in errors)


@pytest.mark.parametrize(
    "kind",
    [
        "value_error",
        "union_tag_invalid",
        "json_invalid",
        "control_characters",
        "recording_location",
        "empty_publish_selection",
    ],
)
def test_validation_message_and_context_cannot_echo_secret(kind) -> None:
    app = create_app()

    @app.post("/api/setup/redaction-regression")
    def rejected(request: Request):
        raise RequestValidationError(
            [
                {
                    "type": kind,
                    "loc": ("body", "admin_password"),
                    "msg": CANARY,
                    "input": {"secret": CANARY},
                    "ctx": {"error": ValueError(CANARY), "tag": CANARY},
                }
            ]
        )

    response = TestClient(app).post("/api/setup/redaction-regression")
    assert response.status_code == 422
    assert CANARY not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "admin_password"]


@pytest.mark.parametrize("value", ["ordinary string", {"nested": CANARY}])
def test_provider_invalid_field_name_is_also_redacted(monkeypatch, tmp_path, value, caplog) -> None:
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})
    response = client.post(
        "/api/staff/installer/provider-credentials",
        json={
            "provider_id": "subscriber-notifications",
            "values": {CANARY: value},
        },
    )
    assert response.status_code == 422
    assert CANARY not in response.text
    assert CANARY not in caplog.text
    assert not (tmp_path / "credentials.json").exists()


def test_raw_malformed_credential_json_does_not_echo_input(caplog) -> None:
    """Additional negative case; original Beta20 request was valid JSON with wrong keys."""
    caplog.set_level("DEBUG")
    client = TestClient(create_app())
    response = client.post(
        "/api/setup/login",
        content='{"admin_username":"operator","admin_password":"' + CANARY + '",}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert CANARY not in response.text
    assert CANARY not in caplog.text
    errors = response.json()["detail"]
    assert errors
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert errors[0]["loc"][0] == "body"
