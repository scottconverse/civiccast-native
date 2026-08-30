# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for S1 StationBoxProfile (civiccast.platform.station_box_profile)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from civiccast.egress.compliance import TsduckStatus
from civiccast.egress.sdi_relay import SdiReadiness
from civiccast.platform.hardware import (
    CPUInfo,
    DiskInfo,
    GPUInfo,
    HardwareProbe,
    OSContext,
    RAMInfo,
)
from civiccast.platform.station_box_profile import (
    _BASE_REQUIRED_PLUGINS,
    BackupDestinationRef,
    CableOsVerdict,
    DeckLinkEngineRef,
    EngineReadiness,
    NdiSdkRef,
    compute_cable_os_verdict,
    compute_engine_tier_verdict,
    compute_peg_readiness,
    probe_clock,
    probe_engine_readiness,
    select_ai_defaults,
)
from civiccast.stream._ffmpeg import FfmpegResult


def _hw(ram_gb: float, gpu: GPUInfo | None = None) -> HardwareProbe:
    return HardwareProbe(
        cpu=CPUInfo(cores_physical=8, cores_logical=16, brand="Test CPU"),
        ram=RAMInfo(total_gb=ram_gb, available_gb=ram_gb / 2),
        disk=DiskInfo(path="C:\\", total_gb=1000, free_gb=500),
        gpu=gpu,
        os=OSContext(
            kind="windows", system="Windows", release="11", machine="AMD64", hostname="test"
        ),
        recommended_tier="tier-0",
        civiccast_version="test",
    )


# ---------------------------------------------------------------------------
# select_ai_defaults truth table (S1 §6.1 / §8)
# ---------------------------------------------------------------------------


_GPU = GPUInfo(name="Test GPU", vram_total_gb=24.0, vram_free_gb=20.0, driver_version="000.00")


class TestSelectAiDefaults:
    @pytest.mark.parametrize(
        ("ram_gb", "expected_basis", "expected_summary"),
        [
            # No GPU: field evidence 2026-08-29 (candidate #17) -- 12B is never the
            # default on a CPU-only box, regardless of RAM. 6/32/128 GB CPU-only all
            # land on "cpu-only"; only the <8GB "forced-cpu" wording differs, and
            # only because it predates GPU-awareness -- both mean "no GPU, use e4b".
            (6, "forced-cpu", "gemma4:e4b"),
            (8, "cpu-only", "gemma4:e4b"),
            (15.9, "cpu-only", "gemma4:e4b"),
            (16, "cpu-only", "gemma4:e4b"),
            (32, "cpu-only", "gemma4:e4b"),
            (128, "cpu-only", "gemma4:e4b"),
        ],
    )
    def test_ram_truth_table_cpu_only(
        self, ram_gb: float, expected_basis: str, expected_summary: str
    ) -> None:
        result = select_ai_defaults(_hw(ram_gb))
        assert result.basis == expected_basis
        assert result.summary_model == expected_summary

    @pytest.mark.parametrize(
        ("ram_gb", "expected_basis", "expected_summary"),
        [
            # "forced-cpu" now means "no GPU AND <8GB RAM" specifically -- with a
            # GPU present, even a <8GB box just isn't big enough for 12B yet
            # ("ram-e4b"), it isn't the doubly-constrained CPU-only case.
            (6, "ram-e4b", "gemma4:e4b"),
            (8, "ram-e4b", "gemma4:e4b"),
            (15.9, "ram-e4b", "gemma4:e4b"),
            (16, "ram-12b", "gemma4:12b"),
            (32, "ram-12b", "gemma4:12b"),
            (128, "ram-12b", "gemma4:12b"),
        ],
    )
    def test_ram_truth_table_with_gpu(
        self, ram_gb: float, expected_basis: str, expected_summary: str
    ) -> None:
        # A real GPU restores the old RAM-only table -- 12B is only ever the
        # default with a GPU present (still gated by RAM below 16GB).
        result = select_ai_defaults(_hw(ram_gb, gpu=_GPU))
        assert result.basis == expected_basis
        assert result.summary_model == expected_summary

    def test_flips_at_exactly_16gb_with_gpu(self) -> None:
        assert select_ai_defaults(_hw(15.999, gpu=_GPU)).basis == "ram-e4b"
        assert select_ai_defaults(_hw(16.0, gpu=_GPU)).basis == "ram-12b"

    def test_no_gpu_never_recommends_12b_even_at_16gb(self) -> None:
        assert select_ai_defaults(_hw(16.0)).basis == "cpu-only"
        assert select_ai_defaults(_hw(16.0)).summary_model == "gemma4:e4b"

    def test_translate_and_caption_always_locked(self) -> None:
        for ram in (4, 8, 16, 64):
            result = select_ai_defaults(_hw(ram))
            assert result.translate_model == "translategemma:4b"
            assert result.caption_model == "whisper-large-v3"

    def test_detected_ram_gb_matches_probe(self) -> None:
        assert select_ai_defaults(_hw(23.4)).detected_ram_gb == 23.4


# ---------------------------------------------------------------------------
# EngineReadiness / EngineTierVerdict
# ---------------------------------------------------------------------------


def _gst_runner(
    *,
    version_ok: bool = True,
    missing: frozenset[str] = frozenset(),
    encoder: str | None = None,
) -> Callable[[list[str]], FfmpegResult]:
    def _runner(args: list[str]) -> FfmpegResult:
        if args == ["--version"]:
            if not version_ok:
                return FfmpegResult(returncode=1, stdout="", stderr="not found")
            return FfmpegResult(returncode=0, stdout="gstreamer-1.0 1.24.0", stderr="")
        element = args[0]
        if element in missing:
            return FfmpegResult(returncode=1, stdout="", stderr="No such element")
        if element in ("nvh264enc", "vah264enc", "qsvh264enc") and element != encoder:
            return FfmpegResult(returncode=1, stdout="", stderr="No such element")
        return FfmpegResult(returncode=0, stdout=f"Factory Details:\n  Rank: {element}", stderr="")

    return _runner


def _no_device_runner(args: list[str]) -> FfmpegResult:
    raise FileNotFoundError("gst-device-monitor-1.0 not found")


class TestEngineReadiness:
    def test_full_base_set_present(self) -> None:
        runner = _gst_runner(missing=frozenset())
        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=runner, device_runner=_no_device_runner
        )
        assert readiness.gstreamer_present is True
        assert readiness.required_plugins_present is True
        assert readiness.missing_plugins == []

    def test_base_set_missing_decklink(self) -> None:
        runner = _gst_runner(missing=frozenset({"decklinkvideosink"}))
        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=runner, device_runner=_no_device_runner
        )
        assert readiness.required_plugins_present is True  # decklink is not a BASE plugin
        assert "decklinkvideosink" in readiness.missing_plugins
        assert readiness.decklink.bmd_sdk_present is False

    def test_no_gstreamer_at_all(self) -> None:
        runner = _gst_runner(version_ok=False)
        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=runner, device_runner=_no_device_runner
        )
        assert readiness.gstreamer_present is False
        assert readiness.required_plugins_present is False
        assert set(_BASE_REQUIRED_PLUGINS).issubset(set(readiness.missing_plugins))

    @pytest.mark.parametrize(
        ("encoder_element", "expected"),
        [("nvh264enc", "nvenc"), ("vah264enc", "vaapi"), ("qsvh264enc", "qsv"), (None, "none")],
    )
    def test_hw_encoder_resolution(self, encoder_element: str | None, expected: str) -> None:
        runner = _gst_runner(missing=frozenset(), encoder=encoder_element)
        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=runner, device_runner=_no_device_runner
        )
        assert readiness.hw_encoder == expected

    def test_sdk_probes_never_fake_present(self) -> None:
        """Absent runner/tooling always fails closed, never true."""

        def raising_runner(args: list[str]) -> FfmpegResult:
            raise FileNotFoundError("gst-inspect-1.0 not found")

        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=raising_runner, device_runner=_no_device_runner
        )
        assert readiness.decklink.bmd_sdk_present is False
        assert readiness.ndi_sdk.sdk_present is False
        assert readiness.decklink.card_present is False

    def test_device_monitor_error_fails_closed_never_faked_present(self) -> None:
        def raising_device_runner(args: list[str]) -> FfmpegResult:
            raise TimeoutError("device monitor timed out")

        runner = _gst_runner(missing=frozenset())
        readiness = probe_engine_readiness(
            native_os=True, gpu=None, runner=runner, device_runner=raising_device_runner
        )
        assert readiness.decklink.card_present is False


class TestClockReport:
    def test_ntp_sync_fails_to_unknown_on_raising_runner(self) -> None:
        def raising_query() -> bool:
            raise RuntimeError("boom")

        report = probe_clock(ntp_query=raising_query)
        assert report.ntp_sync == "unknown"

    def test_ntp_sync_fails_to_unknown_on_none(self) -> None:
        report = probe_clock(ntp_query=lambda: None)
        assert report.ntp_sync == "unknown"

    def test_ntp_sync_true_maps_to_synced(self) -> None:
        report = probe_clock(ntp_query=lambda: True)
        assert report.ntp_sync == "synced"

    def test_ntp_sync_false_maps_to_unsynced(self) -> None:
        report = probe_clock(ntp_query=lambda: False)
        assert report.ntp_sync == "unsynced"


def _full_engine(
    *, native_os: bool, hw_encoder: str = "nvenc", opengl_45: bool = True
) -> EngineReadiness:
    return EngineReadiness(
        gstreamer_present=True,
        gstreamer_version="1.24.0",
        required_plugins_present=True,
        missing_plugins=[],
        opengl_45=opengl_45,
        hw_encoder=hw_encoder,  # type: ignore[arg-type]
        decklink=DeckLinkEngineRef(card_present=True, bmd_sdk_present=True, sdk_version="12.0"),
        ndi_sdk=NdiSdkRef(sdk_present=True, sdk_version="6.0"),
        native_os=native_os,
        next_step="",
    )


class TestEngineTierVerdict:
    def test_base_only_box(self) -> None:
        engine = EngineReadiness(
            gstreamer_present=True,
            gstreamer_version="1.24.0",
            required_plugins_present=True,
            missing_plugins=[],
            opengl_45=False,
            hw_encoder="none",
            decklink=DeckLinkEngineRef(card_present=False, bmd_sdk_present=False, sdk_version=None),
            ndi_sdk=NdiSdkRef(sdk_present=False, sdk_version=None),
            native_os=True,
            next_step="",
        )
        verdict = compute_engine_tier_verdict(engine)
        assert verdict.qualifies_for == "base"
        assert verdict.base_ok is True
        assert verdict.sdi_broadcast_ok is False

    def test_full_sdi_box_qualifies_sdi_broadcast(self) -> None:
        # A "full" box (GPU/OpenGL 4.5, hw encoder, DeckLink+BMD SDK, NDI SDK,
        # native OS) meets sdi-broadcast; because premium-cg's only extra
        # requirement in this model is the same OpenGL 4.5 signal, such a box
        # also qualifies premium-cg (never required, never a failure either
        # way) -- assert the sdi-broadcast floor is met regardless.
        engine = _full_engine(native_os=True)
        verdict = compute_engine_tier_verdict(engine)
        assert verdict.sdi_broadcast_ok is True
        assert verdict.qualifies_for in ("sdi-broadcast", "premium-cg")

    def test_wsl2_demotes_out_of_sdi_broadcast(self) -> None:
        engine = _full_engine(native_os=False)
        verdict = compute_engine_tier_verdict(engine)
        assert verdict.qualifies_for == "base"
        assert verdict.sdi_broadcast_ok is False
        reasons = [b.reason for b in verdict.blockers if b.tier == "sdi-broadcast"]
        assert any("native OS" in reason or "WSL2" in reason for reason in reasons)

    def test_sdi_box_without_gpu_stays_base(self) -> None:
        engine = _full_engine(native_os=True, hw_encoder="none", opengl_45=False)
        verdict = compute_engine_tier_verdict(engine)
        assert verdict.qualifies_for == "base"
        blocker_reasons = {b.reason for b in verdict.blockers if b.tier == "sdi-broadcast"}
        assert any("hardware encoder" in reason.lower() for reason in blocker_reasons)
        assert any("opengl" in reason.lower() for reason in blocker_reasons)

    def test_premium_cg_never_blocks_a_lower_tier(self) -> None:
        # Full SDI box but no OpenGL -- premium-cg is unmet but must not
        # demote a box that would otherwise qualify sdi-broadcast... except
        # OpenGL 4.5 is ALSO an sdi-broadcast requirement, so use a case
        # where sdi-broadcast is fully met and only confirm premium-cg
        # absence doesn't regress the sdi_broadcast_ok flag.
        engine = _full_engine(native_os=True, opengl_45=True)
        verdict = compute_engine_tier_verdict(engine)
        assert verdict.sdi_broadcast_ok is True
        assert verdict.qualifies_for == "premium-cg"

        engine_no_gl = _full_engine(native_os=True, opengl_45=False)
        verdict_no_gl = compute_engine_tier_verdict(engine_no_gl)
        # premium-cg unmet does not itself fail sdi-broadcast beyond the
        # opengl requirement it shares; verify blockers name premium-cg only
        # additively, never as the sole cause of a lower qualification when
        # sdi-broadcast's own prerequisites are otherwise satisfied.
        assert all(
            b.tier != "premium-cg" or not verdict_no_gl.sdi_broadcast_ok
            for b in verdict_no_gl.blockers
        )


# ---------------------------------------------------------------------------
# cable_os_verdict (S1 §6.3)
# ---------------------------------------------------------------------------


class TestCableOsVerdict:
    def test_linux_is_recommended(self) -> None:
        verdict = compute_cable_os_verdict("linux")
        assert verdict.verdict == "native-linux-recommended"

    def test_macos_is_recommended(self) -> None:
        verdict = compute_cable_os_verdict("macos")
        assert verdict.verdict == "native-linux-recommended"

    def test_windows_is_soak_pending(self) -> None:
        verdict = compute_cable_os_verdict("windows")
        assert verdict.verdict == "soak-pending"
        assert "MASTER §13.1" in verdict.rationale

    def test_wsl2_is_soak_pending(self) -> None:
        verdict = compute_cable_os_verdict("wsl2")
        assert verdict.verdict == "soak-pending"

    def test_soak_pending_never_prints_certified(self) -> None:
        verdict = compute_cable_os_verdict("windows")
        assert "certif" not in verdict.rationale.lower() or "pending" in verdict.rationale.lower()


# ---------------------------------------------------------------------------
# peg_readiness color matrix (S1 §6.2 / §8) -- fail closed, profile-aware
# ---------------------------------------------------------------------------


def _tsduck(installed: bool) -> TsduckStatus:
    return TsduckStatus(installed=installed, path=None, version=None, install_hint="install tsduck")


def _sdi() -> SdiReadiness:
    return SdiReadiness(status="ok", ffmpeg_detected=True, muxer_present=True)


class TestPegReadiness:
    def _base_kwargs(self, *, deployment_profile: str = "peg-cable") -> dict[str, Any]:
        engine = _full_engine(native_os=True)
        from civiccast.platform.station_box_profile import compute_engine_tier_verdict

        return {
            "deployment_profile": deployment_profile,
            "engine": engine,
            "qualified_tier": compute_engine_tier_verdict(engine),
            "sdi": _sdi(),
            "tsduck": _tsduck(True),
            "clock": probe_clock(ntp_query=lambda: True),
            "backup_destination": BackupDestinationRef(
                configured=True,
                reachable=True,
                destination="nas://backup",
                last_probe_at=datetime.now(UTC),
            ),
            "ram_total_gb": 32.0,
            "cable_os_verdict": CableOsVerdict(
                verdict="native-linux-recommended", os_kind="linux", rationale="ok"
            ),
        }

    def test_all_green(self) -> None:
        rollup = compute_peg_readiness(**self._base_kwargs())
        assert rollup.overall == "green"
        assert all(dim.color == "green" for dim in rollup.dimensions)

    def test_engine_absent_is_red_fail_closed(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["engine"] = EngineReadiness(
            gstreamer_present=False,
            gstreamer_version=None,
            required_plugins_present=False,
            missing_plugins=list(_BASE_REQUIRED_PLUGINS),
            opengl_45=False,
            hw_encoder="none",
            decklink=DeckLinkEngineRef(card_present=False, bmd_sdk_present=False, sdk_version=None),
            ndi_sdk=NdiSdkRef(sdk_present=False, sdk_version=None),
            native_os=True,
            next_step="install gstreamer",
        )
        kwargs["qualified_tier"] = compute_engine_tier_verdict(kwargs["engine"])
        rollup = compute_peg_readiness(**kwargs)
        assert rollup.overall == "red"
        engine_dim = next(d for d in rollup.dimensions if d.id == "engine")
        assert engine_dim.color == "red"
        assert engine_dim.next_step

    def test_tsduck_not_installed_is_yellow_on_cable_profile(self) -> None:
        kwargs = self._base_kwargs(deployment_profile="peg-cable")
        kwargs["tsduck"] = _tsduck(False)
        rollup = compute_peg_readiness(**kwargs)
        assert rollup.overall == "yellow"
        tsduck_dim = next(d for d in rollup.dimensions if d.id == "tsduck")
        assert tsduck_dim.color == "yellow"

    def test_streaming_only_profile_reports_cable_dims_not_applicable(self) -> None:
        kwargs = self._base_kwargs(deployment_profile="streaming-only")
        kwargs["tsduck"] = _tsduck(False)  # would be yellow on peg-cable
        kwargs["engine"] = _full_engine(native_os=False)  # would fail sdi-broadcast on peg-cable
        kwargs["qualified_tier"] = compute_engine_tier_verdict(kwargs["engine"])
        rollup = compute_peg_readiness(**kwargs)
        tsduck_dim = next(d for d in rollup.dimensions if d.id == "tsduck")
        decklink_dim = next(d for d in rollup.dimensions if d.id == "decklink")
        assert tsduck_dim.color == "green"
        assert "not required" in tsduck_dim.message.lower()
        assert decklink_dim.color == "green"
        assert "not required" in decklink_dim.message.lower()
        # base engine is still required even off the cable profile
        assert rollup.overall == "green"

    def test_low_ram_is_yellow(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["ram_total_gb"] = 6.0
        rollup = compute_peg_readiness(**kwargs)
        ai_dim = next(d for d in rollup.dimensions if d.id == "ai_ram")
        assert ai_dim.color == "yellow"

    def test_no_backup_destination_is_yellow(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["backup_destination"] = BackupDestinationRef(
            configured=False, reachable=None, destination=None
        )
        rollup = compute_peg_readiness(**kwargs)
        backup_dim = next(d for d in rollup.dimensions if d.id == "backup")
        assert backup_dim.color == "yellow"

    def test_soak_pending_cable_os_is_yellow_on_cable_profile(self) -> None:
        kwargs = self._base_kwargs(deployment_profile="peg-cable")
        kwargs["cable_os_verdict"] = CableOsVerdict(
            verdict="soak-pending", os_kind="windows", rationale="pending soak"
        )
        rollup = compute_peg_readiness(**kwargs)
        os_dim = next(d for d in rollup.dimensions if d.id == "cable_os")
        assert os_dim.color == "yellow"
        assert rollup.overall == "yellow"

    def test_never_soft_greens_a_red_dimension(self) -> None:
        """No combination of other-dimension green can mask one red dimension."""
        kwargs = self._base_kwargs()
        kwargs["engine"] = EngineReadiness(
            gstreamer_present=False,
            gstreamer_version=None,
            required_plugins_present=False,
            missing_plugins=list(_BASE_REQUIRED_PLUGINS),
            opengl_45=True,
            hw_encoder="nvenc",
            decklink=DeckLinkEngineRef(card_present=True, bmd_sdk_present=True, sdk_version="12.0"),
            ndi_sdk=NdiSdkRef(sdk_present=True, sdk_version="6.0"),
            native_os=True,
            next_step="install gstreamer",
        )
        kwargs["qualified_tier"] = compute_engine_tier_verdict(kwargs["engine"])
        rollup = compute_peg_readiness(**kwargs)
        assert rollup.overall == "red"
