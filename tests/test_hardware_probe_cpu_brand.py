# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CPU brand resolution tests — covers the WMIC Windows fallback.

The Sprint 0.1 ``_cpu_brand`` resolved Windows brand strings via
``platform.processor()``, which returns the unhelpful raw form
``"AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD"``. Cleanup batch B
added a WMIC-based fallback (``wmic cpu get name /value``) that returns
the friendly model name (``AMD Ryzen 7 7800X3D 8-Core Processor``).

These tests cover both the WMIC-success and WMIC-failure paths via mocks
so the coverage is platform-independent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from civiccast.platform import hardware


class TestWmicCpuBrand:
    """Locks: ``_wmic_cpu_brand()`` returns the friendly name on success,
    ``None`` on every failure mode (binary missing, non-zero exit, no Name
    line in output, subprocess error, timeout)."""

    def test_returns_friendly_name_when_wmic_succeeds(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "\r\r\nName=AMD Ryzen 7 7800X3D 8-Core Processor             \r\r\n\r\r\n"
        )
        with (
            patch("civiccast.platform.hardware.shutil.which", return_value="C:/wmic"),
            patch(
                "civiccast.platform.hardware.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert hardware._wmic_cpu_brand() == "AMD Ryzen 7 7800X3D 8-Core Processor"

    def test_returns_none_when_wmic_not_on_path(self) -> None:
        with patch("civiccast.platform.hardware.shutil.which", return_value=None):
            assert hardware._wmic_cpu_brand() is None

    def test_returns_none_when_wmic_exits_nonzero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with (
            patch("civiccast.platform.hardware.shutil.which", return_value="C:/wmic"),
            patch(
                "civiccast.platform.hardware.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert hardware._wmic_cpu_brand() is None

    def test_returns_none_when_output_lacks_name_line(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Caption=AMD64\r\nDeviceID=CPU0\r\n"
        with (
            patch("civiccast.platform.hardware.shutil.which", return_value="C:/wmic"),
            patch(
                "civiccast.platform.hardware.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert hardware._wmic_cpu_brand() is None

    def test_returns_none_when_subprocess_raises(self) -> None:
        import subprocess

        with (
            patch("civiccast.platform.hardware.shutil.which", return_value="C:/wmic"),
            patch(
                "civiccast.platform.hardware.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="wmic", timeout=5),
            ),
        ):
            assert hardware._wmic_cpu_brand() is None


class TestCpuBrandWindowsPath:
    """Locks: on Windows, ``_cpu_brand()`` prefers the WMIC friendly name
    over ``platform.processor()`` output. Falls back to processor() when
    WMIC returns None."""

    def test_prefers_wmic_friendly_name_on_windows(self) -> None:
        with (
            patch("civiccast.platform.hardware._platform.system", return_value="Windows"),
            patch(
                "civiccast.platform.hardware._wmic_cpu_brand",
                return_value="AMD Ryzen 7 7800X3D 8-Core Processor",
            ),
            patch("civiccast.platform.hardware.Path") as mock_path,
        ):
            # Force /proc/cpuinfo Path read to fail so we exit Linux branch
            mock_path.return_value.read_text.side_effect = OSError("not on Windows")
            assert hardware._cpu_brand() == "AMD Ryzen 7 7800X3D 8-Core Processor"

    def test_falls_back_to_processor_when_wmic_unavailable(self) -> None:
        with (
            patch("civiccast.platform.hardware._platform.system", return_value="Windows"),
            patch("civiccast.platform.hardware._wmic_cpu_brand", return_value=None),
            patch(
                "civiccast.platform.hardware._platform.processor",
                return_value="AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD",
            ),
            patch("civiccast.platform.hardware._platform.machine", return_value="AMD64"),
            patch("civiccast.platform.hardware.Path") as mock_path,
        ):
            mock_path.return_value.read_text.side_effect = OSError("not on Windows")
            brand = hardware._cpu_brand()
            assert brand == "AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD (AMD64)"
