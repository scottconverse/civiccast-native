# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for cross-platform installer bootstrap plans."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


class TestPlatformBootstrapPlans:
    def test_linux_plan_names_service_metadata_when_systemd_available(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="linux",
            detected_tools={"systemd": True, "package_manager": "apt"},
        )

        assert plan.status == "ready"
        assert plan.service_metadata.service_name == "civiccast"
        assert plan.bootstrap_metadata.package_manager == "apt"
        assert "systemctl enable civiccast" in plan.next_step

    def test_macos_plan_names_launchd_bootstrap_metadata(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="macos",
            detected_tools={"launchd": True, "pkgbuild": True},
        )

        assert plan.status == "ready"
        assert plan.service_metadata.manager == "launchd"
        assert plan.bootstrap_metadata.package_kind == "pkg"
        assert "launchctl" in plan.next_step

    def test_windows_plan_targets_wsl2_ubuntu_when_windows_host_detected(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="windows",
            detected_tools={"wsl": True, "ubuntu": True, "ubuntu_wsl2": True},
        )

        assert plan.status == "ready"
        assert plan.runtime == "wsl2-ubuntu"
        assert plan.service_metadata.manager == "systemd"
        assert plan.service_metadata.host_service is False
        assert "wsl --install -d Ubuntu" not in plan.blockers

    def test_windows_plan_blocks_wsl1_ubuntu(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="windows",
            detected_tools={"wsl": True, "ubuntu": True, "ubuntu_wsl2": False},
        )

        assert plan.status == "blocked"
        assert any("older mode" in blocker for blocker in plan.blockers)
        assert "Choose Set up Windows helper" in plan.next_step

    def test_native_windows_service_metadata_rejected_when_supplied(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        with pytest.raises(ValidationError):
            platform.PlatformBootstrapPlan.model_validate(
                {
                    "os_family": "windows",
                    "runtime": "native-windows-service",
                    "status": "ready",
                    "service_metadata": {
                        "manager": "windows-service-control-manager",
                        "host_service": True,
                    },
                    "bootstrap_metadata": {"package_kind": "msi"},
                    "blockers": [],
                    "next_step": "Install the Windows service.",
                }
            )

    def test_blocked_plan_names_in_installer_wsl2_install_action(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="windows",
            detected_tools={"wsl": False, "ubuntu": False},
        )

        assert plan.status == "blocked"
        assert "Choose Set up Windows helper" in plan.next_step
        assert "Approve the Windows security prompt" in plan.next_step
        assert any("Windows helper" in blocker for blocker in plan.blockers)
