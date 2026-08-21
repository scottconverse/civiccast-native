# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit + resumability tests for S3 commissioning (civiccast.installer.commissioning)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.egress.compliance import ComplianceCheck, ComplianceProbeResult, TsduckStatus
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.sdi_relay import SdiReadiness
from civiccast.installer.commissioning import (
    ChannelCommissioningSetup,
    ChannelSetupValidationError,
    CommissioningCheckReport,
    CommissioningProofRun,
    OutputProofSettings,
    build_commissioning_report,
    run_first_run_cable_checks,
    run_output_proof,
    validate_channel_commissioning_setup,
)
from civiccast.installer.station_state import (
    read_commissioning_state,
    save_channel_commissioning_setup,
    save_commissioning_checks,
    save_commissioning_proof_run,
    save_commissioning_report,
)
from civiccast.platform.hardware import (
    CPUInfo,
    DiskInfo,
    HardwareProbe,
    OSContext,
    RAMInfo,
)
from civiccast.platform.station_box_profile import (
    AiDefaultSelection,
    BackupDestinationRef,
    CableOsVerdict,
    ClockReport,
    DeckLinkEngineRef,
    EngineReadiness,
    FfmpegFeatureReport,
    NdiSdkRef,
    NetworkReport,
    ReleaseIdentityRef,
    StationBoxProfile,
    compute_engine_tier_verdict,
    compute_peg_readiness,
)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))


def _box_profile(*, engine_ok: bool, sdi_ok: bool, tsduck_ok: bool) -> StationBoxProfile:
    hw = HardwareProbe(
        cpu=CPUInfo(cores_physical=8, cores_logical=16, brand="Fixture CPU"),
        ram=RAMInfo(total_gb=32.0, available_gb=16.0),
        disk=DiskInfo(path="C:\\", total_gb=1000, free_gb=500),
        gpu=None,
        os=OSContext(kind="windows", system="Windows", release="11", machine="AMD64", hostname="fixture"),
        recommended_tier="tier-0",
        civiccast_version="test",
    )
    engine = EngineReadiness(
        gstreamer_present=engine_ok,
        gstreamer_version="1.24.0" if engine_ok else None,
        required_plugins_present=engine_ok,
        missing_plugins=[] if engine_ok else ["compositor"],
        opengl_45=sdi_ok,
        hw_encoder="nvenc" if sdi_ok else "none",
        decklink=DeckLinkEngineRef(card_present=sdi_ok, bmd_sdk_present=sdi_ok, sdk_version=None),
        ndi_sdk=NdiSdkRef(sdk_present=sdi_ok, sdk_version=None),
        native_os=True,
        next_step="" if engine_ok else "install gstreamer",
    )
    qualified_tier = compute_engine_tier_verdict(engine)
    clock = ClockReport(
        timezone="America/Denver", utc_offset_minutes=-360, system_time=datetime.now(UTC), ntp_sync="synced"
    )
    tsduck = TsduckStatus(
        installed=tsduck_ok, path="/usr/bin/tsp" if tsduck_ok else None,
        version="3.40" if tsduck_ok else None, install_hint="install tsduck",
    )
    sdi = SdiReadiness(status="ok" if sdi_ok else "ffmpeg_unavailable", ffmpeg_detected=sdi_ok, muxer_present=sdi_ok)
    backup = BackupDestinationRef(configured=True, reachable=True, destination="nas://backup")
    cable_os = CableOsVerdict(verdict="native-linux-recommended", os_kind="linux", rationale="ok")
    peg_readiness = compute_peg_readiness(
        deployment_profile="peg-cable",
        engine=engine,
        qualified_tier=qualified_tier,
        sdi=sdi,
        tsduck=tsduck,
        clock=clock,
        backup_destination=backup,
        ram_total_gb=32.0,
        cable_os_verdict=cable_os,
    )
    return StationBoxProfile(
        generated_at=datetime.now(UTC),
        civiccast_version="test",
        hardware=hw,
        system_ram_total_gb=32.0,
        engine=engine,
        ffmpeg=FfmpegFeatureReport(
            detected=True, version="6.0", supported=True, has_decklink=False, has_ndi=False,
            has_libx264=True, has_loudnorm=True, byo_sdi_binary=None,
        ),
        clock=clock,
        network=NetworkReport(hostname="fixture", primary_interface_up=True, headend_interface_hint=None),
        backup_destination=backup,
        release_identity=ReleaseIdentityRef(version="test", package_verified=None, proof_state=None),
        sdi=sdi,
        tsduck=tsduck,
        ndi_sdk=engine.ndi_sdk,
        qualified_engine_tier=qualified_tier,
        ai_default=AiDefaultSelection(
            summary_model="gemma4:12b", translate_model="translategemma:4b",
            caption_model="whisper-large-v3", basis="ram-12b", detected_ram_gb=32.0, rationale="r",
        ),
        peg_readiness=peg_readiness,
        cable_os_verdict=cable_os,
    )


class TestFirstRunCableChecks:
    def test_all_pass_reports_ready(self) -> None:
        box = _box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True)
        report = run_first_run_cable_checks(
            deployment_profile="peg-cable",
            box_profile=box,
            storage_status=type("S", (), {"status": "ready", "operator_message": "ok"})(),
            nats_ready=True,
        )
        by_id = {c.id: c for c in report.checks}
        assert by_id["gstreamer_engine"].status == "pass"
        assert by_id["decklink_sdi"].status == "pass"
        assert by_id["tsduck"].status == "pass"
        assert by_id["db"].status == "pass"
        assert report.ready is True
        assert report.blockers == []

    def test_engine_failure_blocks_ready(self) -> None:
        box = _box_profile(engine_ok=False, sdi_ok=False, tsduck_ok=False)
        report = run_first_run_cable_checks(
            deployment_profile="public-meetings",
            box_profile=box,
            storage_status=type("S", (), {"status": "ready", "operator_message": "ok"})(),
            nats_ready=True,
        )
        by_id = {c.id: c for c in report.checks}
        assert by_id["gstreamer_engine"].status == "fail"
        assert report.ready is False
        assert any("gstreamer" in b.lower() or "playout" in b.lower() for b in report.blockers)

    def test_decklink_and_casparcg_skipped_outside_cable_profile(self) -> None:
        # decklink_sdi is skipped because the profile isn't peg-cable; caspar_cg
        # is skipped because this box (sdi_ok=False -> no OpenGL) doesn't
        # qualify the optional premium-cg engine tier either.
        box = _box_profile(engine_ok=True, sdi_ok=False, tsduck_ok=True)
        report = run_first_run_cable_checks(
            deployment_profile="public-meetings",
            box_profile=box,
            storage_status=type("S", (), {"status": "ready", "operator_message": "ok"})(),
            nats_ready=True,
        )
        by_id = {c.id: c for c in report.checks}
        assert by_id["decklink_sdi"].status == "skipped"
        assert by_id["caspar_cg"].status == "skipped"

    def test_db_not_ready_fails_and_blocks(self) -> None:
        box = _box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True)
        report = run_first_run_cable_checks(
            deployment_profile="peg-cable",
            box_profile=box,
            storage_status=type("S", (), {"status": "not_set_up", "operator_message": "no db"})(),
            nats_ready=True,
        )
        by_id = {c.id: c for c in report.checks}
        assert by_id["db"].status == "fail"
        assert report.ready is False

    def test_release_integrity_is_honestly_skipped_never_faked(self) -> None:
        box = _box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True)
        report = run_first_run_cable_checks(
            box_profile=box,
            storage_status=type("S", (), {"status": "ready", "operator_message": "ok"})(),
            nats_ready=True,
        )
        by_id = {c.id: c for c in report.checks}
        assert by_id["release_integrity"].status == "skipped"

    def test_exactly_eleven_checks(self) -> None:
        box = _box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True)
        report = run_first_run_cable_checks(
            box_profile=box,
            storage_status=type("S", (), {"status": "ready", "operator_message": "ok"})(),
            nats_ready=True,
        )
        assert len(report.checks) == 11


class TestChannelSetupValidation:
    def _setup(self, **overrides: object) -> ChannelCommissioningSetup:
        base: dict[str, object] = {
            "channel_id": "government",
            "channel_name": "Gov Channel 12",
            "output_format": "1080p30",
            "headend_profile_id": "generic-udp-spts",
            "destination": "192.168.1.100:5000",
            "fill_policy": "slate",
        }
        base.update(overrides)
        return ChannelCommissioningSetup(**base)  # type: ignore[arg-type]

    def test_valid_setup_passes(self) -> None:
        result = validate_channel_commissioning_setup(
            self._setup(), box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True)
        )
        assert result.headend_profile_id == "generic-udp-spts"

    def test_unknown_headend_profile_raises(self) -> None:
        with pytest.raises(ChannelSetupValidationError, match="Unknown headend profile"):
            validate_channel_commissioning_setup(
                self._setup(headend_profile_id="not-a-real-profile"),
                box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True),
            )

    def test_sdi_device_without_sdk_raises(self) -> None:
        with pytest.raises(ChannelSetupValidationError, match="DeckLink"):
            validate_channel_commissioning_setup(
                self._setup(sdi_device="DeckLink Mini Monitor 4K"),
                box_profile=_box_profile(engine_ok=True, sdi_ok=False, tsduck_ok=True),
            )

    def test_sdi_device_with_sdk_ready_passes(self) -> None:
        result = validate_channel_commissioning_setup(
            self._setup(sdi_device="DeckLink Mini Monitor 4K"),
            box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True),
        )
        assert result.sdi_device == "DeckLink Mini Monitor 4K"

    def test_missing_watch_folder_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ChannelSetupValidationError, match="does not exist"):
            validate_channel_commissioning_setup(
                self._setup(watch_folder_path=str(tmp_path / "nonexistent")),
                box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True),
            )

    def test_existing_watch_folder_passes(self, tmp_path: Path) -> None:
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        result = validate_channel_commissioning_setup(
            self._setup(watch_folder_path=str(watch_dir)),
            box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True),
        )
        assert result.watch_folder_path == str(watch_dir)

    def test_port_reachable_check_is_non_fatal(self) -> None:
        def _always_false(destination: str) -> bool:
            return False

        result = validate_channel_commissioning_setup(
            self._setup(),
            box_profile=_box_profile(engine_ok=True, sdi_ok=True, tsduck_ok=True),
            port_reachable=_always_false,
        )
        assert result.channel_id == "government"


def _egress_config(*, with_udp_sink: bool = True) -> EgressConfig:
    sinks = (
        [
            EgressSinkSpec(
                kind="udp-ts",
                label="Headend",
                uri="udp://192.168.1.100:5000",
                extra_output_args=["-muxrate", "4000k"],
            )
        ]
        if with_udp_sink
        else [EgressSinkSpec(kind="file", label="Local", uri="file:///tmp/out.ts")]
    )
    return EgressConfig(
        channel_id="government",
        enabled=True,
        sinks=sinks,
        slate_message="Programming will resume shortly.",
    )


def _passing_probe_result() -> ComplianceProbeResult:
    return ComplianceProbeResult(
        channel_id="government",
        destination="192.168.1.100:5000",
        probed_at=datetime.now(UTC),
        seconds=10,
        expected_muxrate_kbps=4000,
        tsduck_version="3.40",
        checks=[ComplianceCheck(check="ts-sync", status="pass", detail="ok")],
        verdict="pass",
    )


class TestOutputProof:
    def test_pass_verdict_when_both_legs_succeed(self) -> None:
        calls: list[tuple[str, int, str, int]] = []

        def fake_runner(destination_uri: str, duration_seconds: int, pattern: str, muxrate_kbps: int) -> None:
            calls.append((destination_uri, duration_seconds, pattern, muxrate_kbps))

        def fake_prober(config: EgressConfig, seconds: int) -> ComplianceProbeResult:
            return _passing_probe_result()

        run = run_output_proof(
            OutputProofSettings(channel_id="government", test_pattern="bars", duration_seconds=5),
            config=_egress_config(),
            test_pattern_runner=fake_runner,
            compliance_prober=fake_prober,
        )
        assert run.verdict == "pass"
        assert run.blockers == []
        assert calls[0][0] == "udp://192.168.1.100:5000"
        assert calls[0][3] == 4000  # muxrate parsed from "4000k"

    def test_missing_udp_sink_is_a_blocker_and_fails(self) -> None:
        run = run_output_proof(
            OutputProofSettings(channel_id="government", duration_seconds=5),
            config=_egress_config(with_udp_sink=False),
            test_pattern_runner=lambda *a: None,
            compliance_prober=lambda *a: _passing_probe_result(),
        )
        assert run.verdict == "fail"
        assert run.blockers

    def test_pattern_generation_failure_is_captured_not_raised(self) -> None:
        def failing_runner(*args: object) -> None:
            raise RuntimeError("ffmpeg exploded")

        run = run_output_proof(
            OutputProofSettings(channel_id="government", duration_seconds=5),
            config=_egress_config(),
            test_pattern_runner=failing_runner,
            compliance_prober=lambda *a: _passing_probe_result(),
        )
        assert run.verdict != "pass"
        assert any("ffmpeg exploded" in b for b in run.blockers)

    def test_tsduck_fail_verdict_propagates_as_blocker(self) -> None:
        def failing_probe(config: EgressConfig, seconds: int) -> ComplianceProbeResult:
            return ComplianceProbeResult(
                channel_id="government", verdict="fail", detail="continuity errors"
            )

        run = run_output_proof(
            OutputProofSettings(channel_id="government", duration_seconds=5),
            config=_egress_config(),
            test_pattern_runner=lambda *a: None,
            compliance_prober=failing_probe,
        )
        assert run.verdict == "fail"
        assert any("continuity errors" in b for b in run.blockers)

    def test_cea708_requested_is_never_claimed_true_without_a_real_check(self) -> None:
        run = run_output_proof(
            OutputProofSettings(channel_id="government", duration_seconds=5),
            config=_egress_config(),
            test_pattern_runner=lambda *a: None,
            compliance_prober=lambda *a: _passing_probe_result(),
            cea708_expected=True,
        )
        assert run.cea708_verified is None
        assert any("CEA-708" in b for b in run.blockers)

    def test_not_claimed_boundary_is_always_present(self) -> None:
        run = run_output_proof(
            OutputProofSettings(channel_id="government", duration_seconds=5),
            config=_egress_config(),
            test_pattern_runner=lambda *a: None,
            compliance_prober=lambda *a: _passing_probe_result(),
        )
        assert run.not_claimed
        assert "SDI" in run.not_claimed[0]


class TestCommissioningReport:
    def test_ready_for_broadcast_true_when_all_steps_clean(self) -> None:
        checks = CommissioningCheckReport(generated_at=datetime.now(UTC), checks=[], ready=True)
        setup = ChannelCommissioningSetup(
            channel_id="government",
            channel_name="Gov 12",
            output_format="1080p30",
            headend_profile_id="generic-udp-spts",
            destination="192.168.1.100:5000",
        )
        proof = CommissioningProofRun(
            channel_id="government",
            proof_id="p1",
            started_at=datetime.now(UTC),
            test_pattern="bars",
            verdict="pass",
        )
        report = build_commissioning_report(
            station_name="Test Station", first_run_checks=checks, channel_setup=setup, proof_run=proof
        )
        assert report.ready_for_broadcast is True

    def test_ready_for_broadcast_false_when_checks_not_ready(self) -> None:
        checks = CommissioningCheckReport(
            generated_at=datetime.now(UTC), checks=[], ready=False, blockers=["engine down"]
        )
        setup = ChannelCommissioningSetup(
            channel_id="government",
            channel_name="Gov 12",
            output_format="1080p30",
            headend_profile_id="generic-udp-spts",
            destination="192.168.1.100:5000",
        )
        proof = CommissioningProofRun(
            channel_id="government", proof_id="p1", started_at=datetime.now(UTC), test_pattern="bars", verdict="pass"
        )
        report = build_commissioning_report(
            station_name="Test Station", first_run_checks=checks, channel_setup=setup, proof_run=proof
        )
        assert report.ready_for_broadcast is False


class TestResumability:
    def test_state_round_trips_through_each_step(self) -> None:
        assert read_commissioning_state().first_run_checks is None

        checks = CommissioningCheckReport(generated_at=datetime.now(UTC), checks=[], ready=True)
        save_commissioning_checks(checks)
        resumed = read_commissioning_state()
        assert resumed.first_run_checks is not None
        assert resumed.first_run_checks.ready is True
        assert resumed.channel_setup is None

        setup = ChannelCommissioningSetup(
            channel_id="government",
            channel_name="Gov 12",
            output_format="1080p30",
            headend_profile_id="generic-udp-spts",
            destination="192.168.1.100:5000",
        )
        save_channel_commissioning_setup(setup)
        resumed = read_commissioning_state()
        assert resumed.channel_setup is not None
        assert resumed.channel_setup.channel_name == "Gov 12"
        # earlier step is still there -- steps don't clobber each other
        assert resumed.first_run_checks is not None

        proof = CommissioningProofRun(
            channel_id="government", proof_id="p1", started_at=datetime.now(UTC), test_pattern="bars", verdict="pass"
        )
        save_commissioning_proof_run(proof)
        report = build_commissioning_report(
            station_name="Test Station",
            first_run_checks=checks,
            channel_setup=setup,
            proof_run=proof,
        )
        save_commissioning_report(report)

        final_state = read_commissioning_state()
        assert final_state.first_run_checks is not None
        assert final_state.channel_setup is not None
        assert final_state.proof_run is not None
        assert final_state.report is not None
        assert final_state.report.ready_for_broadcast is True

    def test_fresh_state_is_empty(self) -> None:
        state = read_commissioning_state()
        assert state.first_run_checks is None
        assert state.channel_setup is None
        assert state.proof_run is None
        assert state.report is None
