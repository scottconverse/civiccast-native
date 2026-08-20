# SPDX-License-Identifier: Apache-2.0
"""Stable data contracts for the Virtual Media Studio runner."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DeviceKind = Literal["software", "hardware", "network", "destination", "context"]
ScenarioStage = Literal["catalog", "stage45", "stage67", "stage8"]
RunStatus = Literal["passed", "failed", "not-applicable"]
ProbeTarget = Literal["obs", "vmix", "ndi", "all"]


class DevicePluginManifest(BaseModel):
    """Capabilities declared by one virtual studio device plugin."""

    model_config = ConfigDict(extra="forbid")

    plugin_id: Annotated[str, Field(min_length=1, max_length=120)]
    label: Annotated[str, Field(min_length=1, max_length=180)]
    device_class: Annotated[str, Field(min_length=1, max_length=80)]
    kind: DeviceKind
    supports_real_probe: bool
    supports_simulator: bool
    actions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list)
    state_fields: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list
    )
    fault_modes: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list
    )
    evidence_fields: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list
    )


class DeviceRef(BaseModel):
    """A profile's reference to a plugin-backed device."""

    model_config = ConfigDict(extra="forbid")

    device_id: Annotated[str, Field(min_length=1, max_length=120)]
    label: Annotated[str, Field(min_length=1, max_length=180)]
    plugin_id: Annotated[str, Field(min_length=1, max_length=120)]
    device_class: Annotated[str, Field(min_length=1, max_length=80)]
    required: bool = True
    checks: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list)


class StudioProfile(BaseModel):
    """One runnable virtual studio profile."""

    model_config = ConfigDict(extra="forbid")

    profile_id: Annotated[str, Field(min_length=1, max_length=120)]
    label: Annotated[str, Field(min_length=1, max_length=180)]
    profile_pack: Annotated[str, Field(min_length=1, max_length=80)]
    source_profile_id: Annotated[str, Field(min_length=1, max_length=120)]
    purpose: Annotated[str, Field(min_length=1, max_length=600)]
    devices: list[DeviceRef]
    required_absences: list[Annotated[str, Field(min_length=1, max_length=180)]] = Field(
        default_factory=list
    )
    outputs: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(default_factory=list)


class ScenarioDefinition(BaseModel):
    """One runner scenario and the CivicCast harness stage it maps to."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=160)]
    stage: ScenarioStage
    requires_real_software: bool = False


class ProfilePackSummary(BaseModel):
    """Stable manifest row for a virtual studio profile pack."""

    model_config = ConfigDict(extra="forbid")

    pack_id: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=180)]
    version: Annotated[str, Field(min_length=1, max_length=40)]
    contract_version: Annotated[str, Field(min_length=1, max_length=40)]
    profile_count: Annotated[int, Field(ge=1)]
    plugin_count: Annotated[int, Field(ge=1)]
    scenario_count: Annotated[int, Field(ge=1)]
    source: Annotated[str, Field(min_length=1, max_length=240)]


class VirtualStudioBundleManifest(BaseModel):
    """Portable manifest for exporting the virtual media studio lab."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["civiccast.virtual-media-studio.bundle.v1"]
    generated_at_unix: Annotated[int, Field(ge=0)]
    contract_version: Annotated[str, Field(min_length=1, max_length=40)]
    profile_packs: list[ProfilePackSummary]
    plugins: list[DevicePluginManifest]
    profiles: list[StudioProfile]
    scenarios: list[ScenarioDefinition]
    extension_points: list[Annotated[str, Field(min_length=1, max_length=160)]]
    artifact_files: list[Annotated[str, Field(min_length=1, max_length=180)]]
    not_claimed: list[Annotated[str, Field(min_length=1, max_length=240)]]


class VirtualStudioRun(BaseModel):
    """Top-level run result emitted by the virtual studio."""

    model_config = ConfigDict(extra="forbid")

    run_id: Annotated[str, Field(min_length=1, max_length=120)]
    status: RunStatus
    scenario_id: Annotated[str, Field(min_length=1, max_length=80)]
    profiles: list[Annotated[str, Field(min_length=1, max_length=120)]]
    event_count: Annotated[int, Field(ge=0)]
    issues: list[str] = Field(default_factory=list)
    artifact_root: Annotated[str | None, Field(max_length=500)] = None
    delegated_runner: Annotated[str, Field(min_length=1, max_length=160)]


class ProbeCheck(BaseModel):
    """One local software/runtime probe observation."""

    model_config = ConfigDict(extra="forbid")

    evidence_key: Annotated[str, Field(min_length=1, max_length=320)]
    check_id: Annotated[str, Field(min_length=1, max_length=120)]
    profile_id: Annotated[str | None, Field(max_length=120)] = None
    device_id: Annotated[str | None, Field(max_length=120)] = None
    device_label: Annotated[str | None, Field(max_length=180)] = None
    status: RunStatus
    observed: Annotated[str, Field(min_length=1, max_length=600)]
    details: dict[str, Any] = Field(default_factory=dict)


class SoftwareProbeRun(BaseModel):
    """Top-level result emitted by `vstudio probe`."""

    model_config = ConfigDict(extra="forbid")

    target: ProbeTarget
    status: RunStatus
    checks: list[ProbeCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    artifact_root: Annotated[str | None, Field(max_length=500)] = None
