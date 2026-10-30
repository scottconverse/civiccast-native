# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""R9: rejected credential requests must never echo their submitted secrets."""

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from civiccast.app import create_app

CANARY = "public-test-secret-never-echo"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/setup/login", {"username": "operator", "password": CANARY}),
        ("/api/setup/login", {"admin_username": "operator", "admin_password": {"nested": CANARY}}),
        ("/api/staff/auth/login", {"username": "operator", "password": [CANARY]}),
        ("/api/setup/recover", {"recovery_code": CANARY, "new_admin_password": CANARY}),
        ("/api/setup/login", {CANARY: {"nested": CANARY}}),
    ],
)
def test_credential_validation_does_not_echo_input(path, payload, caplog) -> None:
    client = TestClient(create_app())

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert CANARY not in response.text
    assert CANARY not in caplog.text
    errors = response.json()["detail"]
    assert errors
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert all(error["loc"][0] == "body" for error in errors)


@pytest.mark.parametrize("kind", ["value_error", "union_tag_invalid", "json_invalid"])
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
