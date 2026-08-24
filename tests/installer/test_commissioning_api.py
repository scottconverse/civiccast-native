# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the S3 commissioning router (/api/staff/cable/commissioning/*)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.egress.compliance import ComplianceCheck, ComplianceProbeResult
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.store import InMemoryEgressStore
from civiccast.installer.commissioning_router import get_commissioning_egress_store

_OPERATOR_HEADERS = {"Authorization": "Bearer operator-token-a"}


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))


def _records_clerk_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "records-token-c:records-c:Records C:records_clerk"
    )
    return {"Authorization": "Bearer records-token-c"}


class TestCommissioningChecksApi:
    def test_post_checks_200_and_persists(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/checks",
            json={"deployment_profile": "public-meetings", "station_name": "Test Station"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["checks"]) == 11

        state = client.get("/api/staff/cable/commissioning/state")
        assert state.status_code == 200
        assert state.json()["first_run_checks"] is not None

    def test_checks_403_for_role_without_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        headers = _records_clerk_headers(monkeypatch)
        client = TestClient(create_app(), headers=headers)
        response = client.post("/api/staff/cable/commissioning/checks", json={})
        assert response.status_code == 403

    def test_state_empty_before_any_step(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/cable/commissioning/state")
        assert response.status_code == 200
        payload = response.json()
        assert payload["first_run_checks"] is None
        assert payload["channel_setup"] is None
        assert payload["proof_run"] is None
        assert payload["report"] is None


class TestChannelSetupApi:
    def _payload(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "channel_id": "government",
            "channel_name": "Gov 12",
            "output_format": "1080p30",
            "headend_profile_id": "generic-udp-spts",
            "destination": "192.168.1.100:5000",
        }
        base.update(overrides)
        return base

    def test_valid_setup_200(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.post("/api/staff/cable/commissioning/channel-setup", json=self._payload())
        assert response.status_code == 200
        assert response.json()["channel_id"] == "government"

    def test_unknown_headend_profile_422(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/channel-setup",
            json=self._payload(headend_profile_id="not-real"),
        )
        assert response.status_code == 422

    def test_403_for_non_setup_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        headers = _records_clerk_headers(monkeypatch)
        client = TestClient(create_app(), headers=headers)
        response = client.post("/api/staff/cable/commissioning/channel-setup", json=self._payload())
        assert response.status_code == 403


class TestOutputProofApi:
    def test_503_when_egress_store_unavailable(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/output-proof",
            json={"channel_id": "government", "duration_seconds": 5},
        )
        assert response.status_code == 503

    def test_404_when_channel_has_no_config(self) -> None:
        app = create_app()
        app.dependency_overrides[get_commissioning_egress_store] = lambda: InMemoryEgressStore()
        client = TestClient(app, headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/output-proof",
            json={"channel_id": "government", "duration_seconds": 5},
        )
        assert response.status_code == 404

    def test_pass_verdict_with_real_store_and_fakes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(
            EgressConfig(
                channel_id="government",
                enabled=True,
                slate_message="x",
                sinks=[
                    EgressSinkSpec(
                        kind="udp-ts",
                        label="Headend",
                        uri="udp://192.168.1.100:5000",
                        extra_output_args=["-muxrate", "4000k"],
                    )
                ],
            )
        )

        import civiccast.installer.commissioning as commissioning_module

        def fake_prober(cfg: EgressConfig, seconds: int) -> ComplianceProbeResult:
            return ComplianceProbeResult(
                channel_id=cfg.channel_id,
                verdict="pass",
                checks=[ComplianceCheck(check="ts-sync", status="pass", detail="ok")],
            )

        monkeypatch.setattr(commissioning_module, "_default_compliance_prober", fake_prober)
        monkeypatch.setattr(commissioning_module, "_default_test_pattern_runner", lambda *a: None)

        app = create_app()
        app.dependency_overrides[get_commissioning_egress_store] = lambda: store
        client = TestClient(app, headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/output-proof",
            json={"channel_id": "government", "duration_seconds": 5},
        )
        assert response.status_code == 200
        assert response.json()["verdict"] == "pass"


class TestCommissioningReportApi:
    def test_409_when_earlier_steps_missing(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.post(
            "/api/staff/cable/commissioning/report", params={"station_name": "Test"}
        )
        assert response.status_code == 409

    def test_200_after_all_earlier_steps_complete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(
            EgressConfig(
                channel_id="government",
                enabled=True,
                slate_message="x",
                sinks=[
                    EgressSinkSpec(
                        kind="udp-ts",
                        label="Headend",
                        uri="udp://192.168.1.100:5000",
                        extra_output_args=["-muxrate", "4000k"],
                    )
                ],
            )
        )
        import civiccast.installer.commissioning as commissioning_module

        def fake_prober(cfg: EgressConfig, seconds: int) -> ComplianceProbeResult:
            return ComplianceProbeResult(channel_id=cfg.channel_id, verdict="pass", checks=[])

        monkeypatch.setattr(commissioning_module, "_default_compliance_prober", fake_prober)
        monkeypatch.setattr(commissioning_module, "_default_test_pattern_runner", lambda *a: None)

        app = create_app()
        app.dependency_overrides[get_commissioning_egress_store] = lambda: store
        client = TestClient(app, headers=_OPERATOR_HEADERS)

        client.post(
            "/api/staff/cable/commissioning/checks",
            json={"deployment_profile": "public-meetings", "station_name": "Test Station"},
        )
        client.post(
            "/api/staff/cable/commissioning/channel-setup",
            json={
                "channel_id": "government",
                "channel_name": "Gov 12",
                "output_format": "1080p30",
                "headend_profile_id": "generic-udp-spts",
                "destination": "192.168.1.100:5000",
            },
        )
        client.post(
            "/api/staff/cable/commissioning/output-proof",
            json={"channel_id": "government", "duration_seconds": 5},
        )
        response = client.post(
            "/api/staff/cable/commissioning/report", params={"station_name": "Test Station"}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["channel_name"] == "Gov 12"
        assert "ready_for_broadcast" in payload
