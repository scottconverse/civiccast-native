# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Cross-platform installer bootstrap contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from civiccast.installer.models import BootstrapMetadata, ServiceMetadata

OsFamily = Literal["linux", "macos", "windows"]
BootstrapStatus = Literal["ready", "blocked"]


class PlatformBootstrapPlan(BaseModel):
    """Fail-closed platform bootstrap plan.

    Windows is intentionally WSL2 Ubuntu only. Native Windows host services are
    rejected at validation time so docs, API routes, and release manifests all
    share the same contract.
    """

    model_config = ConfigDict(extra="forbid")

    os_family: OsFamily
    runtime: Annotated[str, Field(min_length=1)]
    status: BootstrapStatus
    service_metadata: ServiceMetadata
    bootstrap_metadata: BootstrapMetadata
    blockers: list[str]
    next_step: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _reject_native_windows_service(self) -> PlatformBootstrapPlan:
        if self.os_family == "windows":
            if self.runtime != "wsl2-ubuntu" or self.service_metadata.host_service:
                raise ValueError("Windows installer support is WSL2 Ubuntu 24.04 only.")
            if self.service_metadata.manager != "systemd":
                raise ValueError("Windows host plans must manage CivicCast inside WSL2 systemd.")
        return self


def build_bootstrap_plan(
    *, os_family: OsFamily, detected_tools: dict[str, object] | None = None
) -> PlatformBootstrapPlan:
    """Build an actionable bootstrap plan for one platform family."""

    tools = detected_tools or {}
    if os_family == "linux":
        if not tools.get("systemd"):
            return PlatformBootstrapPlan(
                os_family="linux",
                runtime="native-linux",
                status="blocked",
                service_metadata=ServiceMetadata(manager="systemd"),
                bootstrap_metadata=BootstrapMetadata(
                    package_kind="deb",
                    package_manager=str(tools.get("package_manager") or "apt"),
                ),
                blockers=["systemd service manager is unavailable."],
                next_step="Install on a Linux host with systemd, then run systemctl enable civiccast.",
            )
        package_manager = str(tools.get("package_manager") or "apt")
        return PlatformBootstrapPlan(
            os_family="linux",
            runtime="native-linux",
            status="ready",
            service_metadata=ServiceMetadata(manager="systemd"),
            bootstrap_metadata=BootstrapMetadata(
                package_kind="deb" if package_manager == "apt" else "rpm",
                package_manager=package_manager,
            ),
            blockers=[],
            next_step="Install the package, then run systemctl enable civiccast --now.",
        )

    if os_family == "macos":
        ready = bool(tools.get("launchd")) and bool(tools.get("pkgbuild"))
        return PlatformBootstrapPlan(
            os_family="macos",
            runtime="native-macos",
            status="ready" if ready else "blocked",
            service_metadata=ServiceMetadata(manager="launchd"),
            bootstrap_metadata=BootstrapMetadata(package_kind="pkg"),
            blockers=[] if ready else ["launchd and pkgbuild tooling are required."],
            next_step=(
                "Install the signed .pkg, then load org.civiccast.civiccast with launchctl."
                if ready
                else "Install Xcode command line packaging tools, then rebuild the .pkg."
            ),
        )

    has_wsl = bool(tools.get("wsl"))
    has_ubuntu = bool(tools.get("ubuntu"))
    has_ubuntu_wsl2 = bool(tools.get("ubuntu_wsl2"))
    wsl_ready = has_wsl and has_ubuntu and has_ubuntu_wsl2
    blockers = []
    if not has_wsl:
        blockers.append(
            "CivicCast needs a Windows helper before it can finish setup. "
            "The helper lets CivicCast run its local meeting tools on this computer."
        )
    if not has_ubuntu:
        blockers.append("The helper for this Windows user is missing.")
    elif not has_ubuntu_wsl2:
        blockers.append(
            "CivicCast found the helper, but Windows is running it in an older mode "
            "that CivicCast cannot use."
        )
    return PlatformBootstrapPlan(
        os_family="windows",
        runtime="wsl2-ubuntu",
        status="ready" if wsl_ready else "blocked",
        service_metadata=ServiceMetadata(manager="systemd", host_service=False),
        bootstrap_metadata=BootstrapMetadata(package_kind="windows-wsl2-bootstrap-manifest"),
        blockers=blockers,
        next_step=(
            "CivicCast's Windows helper is ready. It can run the local meeting tools on this computer. Continue setup and open the dashboard."
            if wsl_ready
            else (
                "Choose Set up Windows helper. Approve the Windows security prompt, "
                "restart if Windows asks, then reopen CivicCast Installer."
            )
        ),
    )
