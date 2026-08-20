# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Positive-path NVML probe test.

The existing :mod:`tests.test_hardware_probe` suite exercises every NVML
*failure* mode (pynvml ImportError, nvmlInit raising, no devices) but never
the success path. This module fills that gap.

We exercise the success path by monkeypatching :mod:`pynvml` so the parse
pipeline runs against synthetic-but-realistically-shaped values (bytes for
``nvmlDeviceGetName`` / ``nvmlSystemGetDriverVersion`` to mirror real NVML
return types, integer VRAM counts in bytes, integer CUDA version in the
``major*1000 + minor*10`` packed format the driver actually returns).

The previous incarnation of this file gated the test on real hardware via
``pytest.skipif`` so the suite stayed green on no-GPU developer machines
and CI runners. That left the parse path untested on every CI run — the
exact "skip is a lie" anti-pattern called out in the project's testing
posture. The mocked variant exercises the same success-path code in
:func:`civiccast.platform.hardware._probe_gpu` (the bytes-decode branches,
the VRAM-rounding arithmetic, the packed-CUDA-version split) on every
host, no skips. A real-hardware variant lives behind the
``requires_gpu`` mark for self-hosted GPU runners.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from civiccast.platform import hardware
from civiccast.platform.hardware import GPUInfo


def _install_fake_pynvml(
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: bytes | str = b"NVIDIA GeForce RTX 4090",
    vram_total: int = 24 * 1024**3,
    vram_free: int = 20 * 1024**3,
    driver: bytes | str = b"550.54.14",
    cuda_packed: int | None = 12040,  # 12.4
    device_count: int = 1,
) -> None:
    """Install a synthetic ``pynvml`` module on the import path.

    Mirrors the shape of real NVML return values: name and driver come back
    as ``bytes`` from native NVML calls (the production code decodes), VRAM
    figures arrive in raw bytes, and the CUDA version is the packed integer
    (major * 1000 + minor * 10) the driver actually returns.
    """
    fake = SimpleNamespace()

    def nvmlInit() -> None:
        return None

    def nvmlShutdown() -> None:
        return None

    def nvmlDeviceGetCount() -> int:
        return device_count

    def nvmlDeviceGetHandleByIndex(_idx: int) -> object:
        return object()

    def nvmlDeviceGetName(_handle: object) -> bytes | str:
        return name

    def nvmlDeviceGetMemoryInfo(_handle: object) -> Any:
        return SimpleNamespace(total=vram_total, free=vram_free, used=vram_total - vram_free)

    def nvmlSystemGetDriverVersion() -> bytes | str:
        return driver

    def nvmlSystemGetCudaDriverVersion() -> int:
        if cuda_packed is None:
            raise RuntimeError("CUDA driver version unavailable")
        return cuda_packed

    fake.nvmlInit = nvmlInit
    fake.nvmlShutdown = nvmlShutdown
    fake.nvmlDeviceGetCount = nvmlDeviceGetCount
    fake.nvmlDeviceGetHandleByIndex = nvmlDeviceGetHandleByIndex
    fake.nvmlDeviceGetName = nvmlDeviceGetName
    fake.nvmlDeviceGetMemoryInfo = nvmlDeviceGetMemoryInfo
    fake.nvmlSystemGetDriverVersion = nvmlSystemGetDriverVersion
    fake.nvmlSystemGetCudaDriverVersion = nvmlSystemGetCudaDriverVersion

    import sys

    monkeypatch.setitem(sys.modules, "pynvml", fake)


class TestProbeGpuPositivePathMocked:
    """Locks: ``_probe_gpu()`` parses NVML's success-path return values
    correctly. Runs on every host (no real GPU required)."""

    def test_returns_populated_gpu_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_pynvml(monkeypatch)
        info = hardware._probe_gpu()
        assert info is not None
        assert isinstance(info, GPUInfo)
        assert info.name == "NVIDIA GeForce RTX 4090"
        assert info.vram_total_gb == pytest.approx(24.0, abs=0.05)
        assert 0 <= info.vram_free_gb <= info.vram_total_gb
        assert info.driver_version == "550.54.14"
        assert info.cuda_version == "12.4"

    def test_full_probe_includes_gpu_and_classifies_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_pynvml(monkeypatch)
        result = hardware.probe()
        assert result.gpu is not None
        assert result.recommended_tier in {"tier-0", "tier-1", "tier-1-plus", "tier-2"}

    def test_str_name_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Newer pynvml releases sometimes return ``str`` instead of ``bytes``."""
        _install_fake_pynvml(
            monkeypatch,
            name="NVIDIA RTX A6000",
            driver="535.154.05",
        )
        info = hardware._probe_gpu()
        assert info is not None
        assert info.name == "NVIDIA RTX A6000"
        assert info.driver_version == "535.154.05"

    def test_cuda_unavailable_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ``nvmlSystemGetCudaDriverVersion`` raises, ``cuda_version`` is None."""
        _install_fake_pynvml(monkeypatch, cuda_packed=None)
        info = hardware._probe_gpu()
        assert info is not None
        assert info.cuda_version is None


# Real-hardware integration coverage is intentionally NOT shipped here:
# the mocked tests above exercise the full success-path parse pipeline on
# every host without skips. A real-driver "does the actual NVML library
# respond correctly" check is an integration concern that will live in
# tests/integration/ once self-hosted GPU runners are wired up — that
# directory is not collected by the default pytest run, so it never
# manifests as a skip.
