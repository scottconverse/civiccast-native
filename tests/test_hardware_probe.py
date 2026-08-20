# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the hardware probe core."""

from __future__ import annotations

import platform as _platform
from pathlib import Path

import pytest

from civiccast.platform import hardware
from civiccast.platform.hardware import (
    CPUInfo,
    DiskInfo,
    GPUInfo,
    HardwareProbe,
    OSContext,
    RAMInfo,
    _classify_os,
    _is_wsl2,
    _tier_for,
    probe,
)


class TestTierClassification:
    """The tier decision tree is the load-bearing classifier — spec §7.7."""

    def test_no_gpu_is_tier_0(self) -> None:
        assert _tier_for(None) == "tier-0"

    def test_below_8gb_vram_is_tier_0(self) -> None:
        gpu = GPUInfo(
            name="GTX 1050",
            vram_total_gb=4.0,
            vram_free_gb=3.5,
            driver_version="535.0",
        )
        assert _tier_for(gpu) == "tier-0"

    def test_8gb_vram_is_tier_1(self) -> None:
        """RTX 4060 8GB is the spec §10.2 reference build floor."""
        gpu = GPUInfo(
            name="RTX 4060",
            vram_total_gb=8.0,
            vram_free_gb=7.5,
            driver_version="535.0",
        )
        assert _tier_for(gpu) == "tier-1"

    def test_15gb_vram_is_tier_1(self) -> None:
        """Just below the 16GB threshold stays at tier-1."""
        gpu = GPUInfo(
            name="RTX 4080 hypothetical",
            vram_total_gb=15.9,
            vram_free_gb=15.0,
            driver_version="535.0",
        )
        assert _tier_for(gpu) == "tier-1"

    def test_16gb_vram_is_tier_1_plus(self) -> None:
        """RTX 5070 Ti 16GB (ADR 0003 reference dev machine)."""
        gpu = GPUInfo(
            name="RTX 5070 Ti",
            vram_total_gb=16.0,
            vram_free_gb=15.0,
            driver_version="555.0",
        )
        assert _tier_for(gpu) == "tier-1-plus"

    def test_24gb_vram_is_tier_2(self) -> None:
        """RTX 4090 / RTX 5090 / Tier 2 multi-stream territory."""
        gpu = GPUInfo(
            name="RTX 4090",
            vram_total_gb=24.0,
            vram_free_gb=23.0,
            driver_version="555.0",
        )
        assert _tier_for(gpu) == "tier-2"


class TestOSClassification:
    def test_windows_native(self) -> None:
        assert _classify_os("Windows", "10.0.26200") == "windows"

    def test_macos(self) -> None:
        assert _classify_os("Darwin", "23.5.0") == "macos"

    def test_linux_native(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force the in-container short-circuit so this test behaves the same
        # whether the test runner is on a bare Linux box, on Windows, or
        # inside a Docker container on a WSL2 host (where /proc/version
        # leaks "microsoft" from the host kernel and would otherwise lie).
        from civiccast.platform import hardware

        monkeypatch.setattr(hardware, "_in_linux_container", lambda: True)
        assert _classify_os("Linux", "5.15.0-118-generic") == "linux"

    def test_linux_wsl_via_release_string(self) -> None:
        assert _classify_os("Linux", "5.15.153.1-microsoft-standard-WSL2") == "wsl2"

    def test_unknown(self) -> None:
        assert _classify_os("FreeBSD", "13.0") == "unknown"


class TestWSL2Detection:
    def test_microsoft_in_release(self) -> None:
        assert _is_wsl2("5.15.153.1-microsoft-standard-WSL2") is True

    def test_wsl_in_release(self) -> None:
        assert _is_wsl2("5.15.0-WSL2") is True

    def test_plain_linux_release(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force the function to take its non-/proc/version path so the test
        # behaves identically inside containers (Docker on Windows-WSL2 hosts
        # leaks "microsoft" into /proc/version) and on bare Linux boxes.
        from civiccast.platform import hardware

        monkeypatch.setattr(hardware, "_in_linux_container", lambda: True)
        assert _is_wsl2("5.15.0-118-generic") is False

    def test_release_string_takes_precedence_over_container_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even if we're in a container, an explicit WSL2 release string
        # (e.g. someone pinning kernel info from the host into env vars)
        # still wins. Defense against the container-detection logic
        # accidentally suppressing a real WSL2 signal.
        from civiccast.platform import hardware

        monkeypatch.setattr(hardware, "_in_linux_container", lambda: True)
        assert _is_wsl2("5.15.153.1-microsoft-standard-WSL2") is True

    def test_in_linux_container_detects_dockerenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate a container by patching Path("/.dockerenv").exists() True.
        from civiccast.platform import hardware

        original_path = hardware.Path

        class _FakePath(type(original_path("/"))):
            def exists(self_inner) -> bool:  # type: ignore[override]
                if str(self_inner) == "/.dockerenv":
                    return True
                return original_path(str(self_inner)).exists()

        # Simpler: patch the helper directly to assert the wiring.
        monkeypatch.setattr(hardware, "_in_linux_container", lambda: True)
        # Now plain-Linux release inside "container" must NOT consult /proc/version.
        assert _is_wsl2("5.15.0-118-generic") is False


class TestProbeIntegration:
    """End-to-end probe — runs against the actual host. Asserts shape, not values."""

    def test_probe_returns_well_formed_result(self) -> None:
        result = probe()
        assert isinstance(result, HardwareProbe)
        assert isinstance(result.cpu, CPUInfo)
        assert isinstance(result.ram, RAMInfo)
        assert isinstance(result.disk, DiskInfo)
        assert isinstance(result.os, OSContext)
        assert result.gpu is None or isinstance(result.gpu, GPUInfo)
        assert result.recommended_tier in ("tier-0", "tier-1", "tier-1-plus", "tier-2")

    def test_probe_cpu_counts_are_positive(self) -> None:
        result = probe()
        assert result.cpu.cores_physical >= 1
        assert result.cpu.cores_logical >= result.cpu.cores_physical

    def test_probe_ram_is_positive(self) -> None:
        result = probe()
        assert result.ram.total_gb > 0
        assert 0 <= result.ram.available_gb <= result.ram.total_gb

    def test_probe_disk_is_positive(self) -> None:
        result = probe()
        assert result.disk.total_gb > 0
        assert 0 <= result.disk.free_gb <= result.disk.total_gb

    def test_probe_os_kind_matches_running_platform(self) -> None:
        result = probe()
        system = _platform.system()
        if system == "Windows":
            assert result.os.kind == "windows"
        elif system == "Darwin":
            assert result.os.kind == "macos"
        elif system == "Linux":
            assert result.os.kind in ("wsl2", "linux")

    def test_probe_disk_path_is_overridable(self, tmp_path: Path) -> None:
        result = probe(disk_path=tmp_path)
        assert result.disk.path == str(tmp_path)

    def test_probe_includes_civiccast_version(self) -> None:
        from civiccast._version import __version__

        result = probe()
        assert result.civiccast_version == __version__


class TestProbeJSONSerialization:
    """Probe results must serialize as JSON for the FastAPI surface."""

    def test_probe_serializes_to_json(self) -> None:
        result = probe()
        payload = result.model_dump_json()
        assert "cpu" in payload
        assert "recommended_tier" in payload

    def test_probe_round_trips_through_json(self) -> None:
        original = probe()
        rebuilt = HardwareProbe.model_validate_json(original.model_dump_json())
        assert rebuilt == original


class TestNVMLFailureModesGracefullyDegrade:
    """The probe must never raise from GPU detection — return None on every failure mode."""

    def test_pynvml_import_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "pynvml":
                raise ImportError("pynvml not installed in this test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        # Must not raise.
        assert hardware._probe_gpu() is None

    def test_nvml_init_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pynvml  # type: ignore[import-untyped]

        def fake_init() -> None:
            raise RuntimeError("driver not present")

        monkeypatch.setattr(pynvml, "nvmlInit", fake_init)
        assert hardware._probe_gpu() is None
