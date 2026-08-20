# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 generated API, TypeScript, and docs artifacts."""

from __future__ import annotations

import json
from pathlib import Path


class TestGeneratedApiContracts:
    def test_v11_endpoints_and_closed_status_literals_are_in_openapi(self) -> None:
        openapi_path = Path("docs/openapi.json")

        schema = json.loads(openapi_path.read_text(encoding="utf-8"))

        for path in [
            "/api/staff/first-run/wizard",
            "/api/staff/release/proof",
            "/api/staff/doctor/audit",
            "/api/staff/live/preflight-v1.1",
        ]:
            assert path in schema["paths"]

        status_schema = schema["components"]["schemas"]["V11GateStatus"]
        assert set(status_schema["enum"]) == {
            "ok",
            "credential_or_secret_required",
            "hardware_required",
            "deferred_by_scott",
            "failed",
        }
