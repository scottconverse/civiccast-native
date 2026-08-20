# SPDX-License-Identifier: Apache-2.0
"""Profile-pack registry for the reusable Virtual Media Studio."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from vstudio.models import (
    DevicePluginManifest,
    ProfilePackSummary,
    ScenarioDefinition,
    StudioProfile,
    VirtualStudioRun,
)
from vstudio.profile_packs import lpm


class ProfilePackModule(Protocol):
    """Protocol implemented by built-in and future external profile packs."""

    PACK_ID: str
    LABEL: str
    VERSION: str
    CONTRACT_VERSION: str
    SOURCE: str

    def list_profiles(self) -> list[StudioProfile]:
        """Return profile definitions owned by the pack."""

    def list_plugins(self) -> list[DevicePluginManifest]:
        """Return plugin manifests owned by the pack."""

    def list_scenarios(self) -> list[ScenarioDefinition]:
        """Return scenarios supported by the pack."""

    def resolve_profile_ids(self, profile_ids: Iterable[str] | None) -> list[str] | None:
        """Map public profile aliases to the delegated runner's profile IDs."""

    def resolve_scenario(self, scenario_id: str) -> ScenarioDefinition:
        """Resolve a scenario by ID or raise ``ValueError``."""

    def run_scenario(
        self,
        *,
        profile_ids: list[str] | None,
        scenario_id: str,
        artifact_root: Path | None,
        force_clean: bool,
        probe_real_software: bool,
    ) -> VirtualStudioRun:
        """Execute a scenario through the pack-owned runner."""


class VirtualStudioRegistry:
    """Registry for profile packs and plugin manifests.

    The current product ships only the LPM pack, but callers go through this
    registry so another pack can be added later without rewriting CLI commands,
    artifact packaging, or tests.
    """

    def __init__(self, packs: Iterable[ProfilePackModule] | None = None) -> None:
        self._packs = list(packs or [lpm])
        if not self._packs:
            raise ValueError("At least one Virtual Media Studio profile pack is required.")
        pack_ids = [pack.PACK_ID for pack in self._packs]
        duplicates = sorted({pack_id for pack_id in pack_ids if pack_ids.count(pack_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate Virtual Media Studio profile pack(s): {duplicates}.")

    def list_profile_packs(self) -> list[ProfilePackSummary]:
        """Return stable profile-pack manifest rows."""

        return [
            ProfilePackSummary(
                pack_id=pack.PACK_ID,
                label=pack.LABEL,
                version=pack.VERSION,
                contract_version=pack.CONTRACT_VERSION,
                profile_count=len(pack.list_profiles()),
                plugin_count=len(pack.list_plugins()),
                scenario_count=len(pack.list_scenarios()),
                source=pack.SOURCE,
            )
            for pack in self._packs
        ]

    def list_profiles(self) -> list[StudioProfile]:
        """Return all known profiles."""

        return [profile for pack in self._packs for profile in pack.list_profiles()]

    def list_plugins(self) -> list[DevicePluginManifest]:
        """Return all plugin manifests, rejecting ID drift."""

        plugins = [plugin for pack in self._packs for plugin in pack.list_plugins()]
        plugin_ids = [plugin.plugin_id for plugin in plugins]
        duplicates = sorted(
            {plugin_id for plugin_id in plugin_ids if plugin_ids.count(plugin_id) > 1}
        )
        if duplicates:
            raise ValueError(f"Duplicate Virtual Media Studio plugin(s): {duplicates}.")
        return sorted(plugins, key=lambda plugin: plugin.plugin_id)

    def list_scenarios(self) -> list[ScenarioDefinition]:
        """Return all known scenarios."""

        scenarios = [scenario for pack in self._packs for scenario in pack.list_scenarios()]
        scenario_ids = [scenario.scenario_id for scenario in scenarios]
        duplicates = sorted(
            {scenario_id for scenario_id in scenario_ids if scenario_ids.count(scenario_id) > 1}
        )
        if duplicates:
            raise ValueError(f"Duplicate Virtual Media Studio scenario(s): {duplicates}.")
        return sorted(scenarios, key=lambda scenario: scenario.scenario_id)

    def resolve_pack_for_profiles(self, profile_ids: Iterable[str] | None) -> ProfilePackModule:
        """Return the single pack that owns the selected profile aliases."""

        if profile_ids is None:
            return self._default_pack()
        profile_id_list = list(profile_ids)
        if not profile_id_list or "all" in profile_id_list:
            return self._default_pack()
        matches = [
            pack
            for pack in self._packs
            if set(profile_id_list).issubset(
                {profile.profile_id for profile in pack.list_profiles()}
            )
        ]
        if len(matches) == 1:
            return matches[0]
        known = ", ".join(["all", *sorted(profile.profile_id for profile in self.list_profiles())])
        raise ValueError(
            "Profile selection must belong to one Virtual Media Studio profile pack. "
            f"Requested: {', '.join(profile_id_list)}. Known: {known}."
        )

    def resolve_scenario(self, scenario_id: str) -> ScenarioDefinition:
        """Resolve a scenario from the registered packs."""

        matches = []
        for pack in self._packs:
            try:
                matches.append(pack.resolve_scenario(scenario_id))
            except ValueError:
                continue
        if len(matches) == 1:
            return matches[0]
        known = ", ".join(scenario.scenario_id for scenario in self.list_scenarios())
        raise ValueError(f"Unknown virtual studio scenario {scenario_id!r}. Known: {known}.")

    def as_manifest_payload(self) -> dict[str, Any]:
        """Return JSON-serializable registry state for support artifacts."""

        return {
            "profile_packs": [pack.model_dump(mode="json") for pack in self.list_profile_packs()],
            "plugins": [plugin.model_dump(mode="json") for plugin in self.list_plugins()],
            "profiles": [profile.model_dump(mode="json") for profile in self.list_profiles()],
            "scenarios": [scenario.model_dump(mode="json") for scenario in self.list_scenarios()],
        }

    def _default_pack(self) -> ProfilePackModule:
        return self._packs[0]


__all__ = ["ProfilePackModule", "VirtualStudioRegistry"]
