# SPDX-License-Identifier: Apache-2.0
"""Generic runner for Virtual Media Studio profile packs."""

from __future__ import annotations

from pathlib import Path

from vstudio.models import VirtualStudioRun
from vstudio.registry import VirtualStudioRegistry


class VirtualStudioRunner:
    """Run reusable virtual-studio profiles through stable contracts."""

    def __init__(self, registry: VirtualStudioRegistry | None = None) -> None:
        self._registry = registry or VirtualStudioRegistry()

    def list_profile_packs(self) -> list[dict[str, object]]:
        return [pack.model_dump(mode="json") for pack in self._registry.list_profile_packs()]

    def list_profiles(self) -> list[dict[str, object]]:
        return [profile.model_dump(mode="json") for profile in self._registry.list_profiles()]

    def list_devices(self, profile_id: str | None = None) -> list[dict[str, object]]:
        profiles = self._registry.list_profiles()
        if profile_id and profile_id != "all":
            profiles = [profile for profile in profiles if profile.profile_id == profile_id]
            if not profiles:
                known = ", ".join(profile.profile_id for profile in self._registry.list_profiles())
                raise ValueError(f"Unknown virtual studio profile {profile_id!r}. Known: {known}.")

        devices: list[dict[str, object]] = []
        for profile in profiles:
            for device in profile.devices:
                record = device.model_dump(mode="json")
                record["profile_id"] = profile.profile_id
                devices.append(record)
        return devices

    def list_plugins(self) -> list[dict[str, object]]:
        return [plugin.model_dump(mode="json") for plugin in self._registry.list_plugins()]

    def list_scenarios(self) -> list[dict[str, object]]:
        return [scenario.model_dump(mode="json") for scenario in self._registry.list_scenarios()]

    def run(
        self,
        *,
        profile_ids: list[str] | None,
        scenario_id: str,
        artifact_root: Path | None = None,
        force_clean: bool = False,
        probe_real_software: bool = False,
    ) -> VirtualStudioRun:
        pack = self._registry.resolve_pack_for_profiles(profile_ids)
        return pack.run_scenario(
            profile_ids=profile_ids,
            scenario_id=scenario_id,
            artifact_root=artifact_root,
            force_clean=force_clean,
            probe_real_software=probe_real_software,
        )
