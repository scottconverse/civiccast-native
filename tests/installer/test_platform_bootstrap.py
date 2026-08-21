# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Linux/macOS native installer bootstrap plans.

Windows is deliberately absent here: it used to be modeled as a third
``os_family`` (WSL2 Ubuntu only, with native Windows service metadata
rejected at validation time), retired along with the rest of the WSL2 lane
under the owner's "no linux" decision (2026-08-19). Windows deployment
readiness is decided entirely by civiccast.installer.service's own
native-station activation check now -- see
tests/installer/test_installer_api_contract.py and
tests/installer/test_existing_first_run_regression.py for that coverage.
"""

from __future__ import annotations

import importlib


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

    def test_linux_plan_blocks_without_systemd(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="linux",
            detected_tools={"systemd": False},
        )

        assert plan.status == "blocked"
        assert any("systemd" in blocker for blocker in plan.blockers)

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

    def test_macos_plan_blocks_without_tooling(self) -> None:
        platform = importlib.import_module("civiccast.installer.platform")

        plan = platform.build_bootstrap_plan(
            os_family="macos",
            detected_tools={},
        )

        assert plan.status == "blocked"
        assert any("launchd" in blocker for blocker in plan.blockers)
