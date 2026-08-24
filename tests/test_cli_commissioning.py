# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI tests for the S3 commissioning surface: `cable doctor/commission/
support-bundle`, `output sdi-readiness`, `egress output test-pattern`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civiccast.cli import app
from civiccast.egress.compliance import ComplianceCheck, ComplianceProbeResult
from civiccast.egress.models import EgressConfig, EgressSinkSpec


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))


def test_cable_doctor_json_shape() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["cable", "doctor", "--json"])
    payload = json.loads(result.stdout)
    assert len(payload["checks"]) == 11
    assert "ready" in payload
    # exit code mirrors the honest readiness verdict; on a real dev box this
    # is very likely NOT READY (no durable storage prepared), so only assert
    # the exit code agrees with the reported `ready` flag rather than
    # hard-coding a value.
    assert result.exit_code == (0 if payload["ready"] else 1)


def test_cable_doctor_human_output_lists_all_checks() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["cable", "doctor"])
    assert "First-run cable checks:" in result.stdout
    assert "Operating system" in result.stdout
    assert "GStreamer playout engine" in result.stdout


def test_output_sdi_readiness_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["output", "sdi-readiness", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] in (
        "ok",
        "bmd_sdk_unavailable",
        "decklinkvideosink_missing",
        "decklink_card_absent",
    )


def test_cable_commission_fails_closed_when_checks_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a box with no durable storage, commissioning must exit 1 before
    ever touching the channel/egress store -- fail-closed at Screen 8."""

    import civiccast.installer.commissioning as commissioning_module

    monkeypatch.setattr(
        commissioning_module,
        "run_first_run_cable_checks",
        lambda **kwargs: commissioning_module.CommissioningCheckReport(
            generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            checks=[],
            ready=False,
            blockers=["Database: not configured"],
        ),
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "cable",
            "commission",
            "--channel-id",
            "government",
            "--headend-profile",
            "generic-udp-spts",
            "--destination",
            "192.168.1.100:5000",
        ],
    )
    assert result.exit_code == 1
    assert "cannot continue" in result.stdout.lower()


def test_cable_commission_end_to_end_with_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    import civiccast.installer.commissioning as commissioning_module

    monkeypatch.setattr(
        commissioning_module,
        "run_first_run_cable_checks",
        lambda **kwargs: commissioning_module.CommissioningCheckReport(
            generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            checks=[],
            ready=True,
        ),
    )

    config = EgressConfig(
        channel_id="government",
        enabled=True,
        slate_message="x",
        sinks=[
            EgressSinkSpec(
                kind="udp-ts",
                label="Cable headend",
                uri="udp://192.168.1.100:5000",
                extra_output_args=["-muxrate", "4000k"],
            )
        ],
    )

    class _FakeStore:
        def __init__(self, _factory: object) -> None:
            pass

        def get_config(self, channel_id: str) -> EgressConfig | None:
            return config if channel_id == "government" else None

    def fake_prober(cfg: EgressConfig, seconds: int) -> ComplianceProbeResult:
        return ComplianceProbeResult(
            channel_id=cfg.channel_id,
            destination="udp://192.168.1.100:5000",
            verdict="pass",
            checks=[ComplianceCheck(check="ts-sync", status="pass", detail="ok")],
        )

    monkeypatch.setattr("civiccast.egress.store.PostgresEgressStore", _FakeStore)
    monkeypatch.setattr(commissioning_module, "_default_compliance_prober", fake_prober)
    monkeypatch.setattr(commissioning_module, "_default_test_pattern_runner", lambda *a: None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "cable",
            "commission",
            "--channel-id",
            "government",
            "--headend-profile",
            "generic-udp-spts",
            "--destination",
            "192.168.1.100:5000",
            "--duration-seconds",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ready_for_broadcast"] is True
    assert payload["proof_run"]["verdict"] == "pass"

    # Resumability: the persisted state now has all 4 steps.
    from civiccast.installer.station_state import read_commissioning_state

    state = read_commissioning_state()
    assert state.first_run_checks is not None
    assert state.channel_setup is not None
    assert state.proof_run is not None
    assert state.report is not None


def test_cable_support_bundle_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from civiccast.installer.models import DiagnosticBundleResponse

    def fake_create_bundle(payload: object) -> DiagnosticBundleResponse:
        return DiagnosticBundleResponse(
            bundle_id="support-20260101T000000Z-abcd1234",
            generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            path="/tmp/support-bundle.json",
            sha256="0" * 64,
            redacted=True,
            contains=["station_setup", "system_health"],
            excludes=["secrets"],
            next_step="Attach to the support ticket.",
        )

    monkeypatch.setattr("civiccast.installer.service.create_diagnostic_bundle", fake_create_bundle)
    runner = CliRunner()
    result = runner.invoke(app, ["cable", "support-bundle", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["bundle_id"] == "support-20260101T000000Z-abcd1234"
    assert payload["redacted"] is True


def test_egress_output_test_pattern_rejects_an_invalid_pattern() -> None:
    """Regression test for the mypy fix: --pattern is validated against the
    TestPattern Literal (bars|live|slate) instead of passed through as a bare
    str, and an invalid value is a clean BadParameter, not a runtime crash."""

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["egress", "output", "test-pattern", "--channel-id", "government", "--pattern", "bogus"],
    )
    assert result.exit_code != 0
    # BadParameter's rich-rendered error panel goes through typer's own
    # console, not the click.echo stream CliRunner.stdout captures --
    # .output mixes both, matching the pattern real terminal users see.
    assert "must be one of bars, live, slate" in result.output


def test_egress_output_test_pattern_accepts_valid_patterns_before_store_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid --pattern passes validation and proceeds to the (here-absent)
    channel lookup, proving the Literal-narrowed value is accepted, not just
    that invalid values are rejected."""

    class _EmptyStore:
        def __init__(self, _factory: object) -> None:
            pass

        def get_config(self, channel_id: str) -> None:
            return None

    monkeypatch.setattr("civiccast.egress.store.PostgresEgressStore", _EmptyStore)
    runner = CliRunner()
    for pattern in ("bars", "live", "slate"):
        result = runner.invoke(
            app,
            [
                "egress",
                "output",
                "test-pattern",
                "--channel-id",
                "government",
                "--pattern",
                pattern,
            ],
        )
        # The pattern-validation error never fires; the command proceeds
        # past it to the (mocked, empty) store lookup, which fails for its
        # own unrelated reason -- proof the Literal-narrowed value flowed
        # through, not that the command fully succeeded.
        assert "must be one of" not in result.output
        assert "No egress config for channel" in result.output
