# SPDX-License-Identifier: Apache-2.0
"""LPM profile pack adapter for the reusable Virtual Media Studio."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

from civiccast.control_room.lpm_lab import TopologyId, build_lpm_lab_profiles
from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab
from vstudio.models import (
    DevicePluginManifest,
    DeviceRef,
    ScenarioDefinition,
    StudioProfile,
    VirtualStudioRun,
)

PACK_ID = "lpm"
LABEL = "Longmont Public Media Lab"
VERSION = "3.2-local"
CONTRACT_VERSION = "vstudio-contract-v1"
SOURCE = "civiccast.control_room.lpm_lab"

PROFILE_ALIASES: dict[str, TopologyId] = {
    "lpm-fixed-studio": "fixed-studio-livestreaming",
    "lpm-portable-field-kit": "portable-field-kit",
    "lpm-digitization-obs": "digitization-obs",
}

SCENARIOS = {
    "smoke": ScenarioDefinition(
        scenario_id="smoke",
        label="Profile catalog smoke",
        stage="catalog",
    ),
    "walkthrough": ScenarioDefinition(
        scenario_id="walkthrough",
        label="API fixture and simulator walkthrough",
        stage="stage45",
    ),
    "chaos": ScenarioDefinition(
        scenario_id="chaos",
        label="Fault and recovery rehearsal",
        stage="stage67",
    ),
    "soak": ScenarioDefinition(
        scenario_id="soak",
        label="Twelve-hour plan rehearsal",
        stage="stage67",
    ),
    "software": ScenarioDefinition(
        scenario_id="software",
        label="Real local software probe",
        stage="stage45",
        requires_real_software=True,
    ),
    "release": ScenarioDefinition(
        scenario_id="release",
        label="Local Stage 8 release-hardening package",
        stage="stage8",
        requires_real_software=True,
    ),
}


def list_profiles() -> list[StudioProfile]:
    """Return the LPM profiles through the virtual-studio schema."""

    return [_studio_profile(alias, source_id) for alias, source_id in PROFILE_ALIASES.items()]


def list_plugins() -> list[DevicePluginManifest]:
    """Return first-party plugin manifests required by the LPM pack."""

    plugin_by_class = {
        "vmix": DevicePluginManifest(
            plugin_id="vmix",
            label="vMix HTTP/API Plugin",
            device_class="vmix",
            kind="software",
            supports_real_probe=True,
            supports_simulator=True,
            actions=["input-select", "cut", "fade", "overlay-in", "overlay-out"],
            state_fields=["version", "active", "preview", "recording", "streaming", "inputs"],
            fault_modes=["api-disabled", "auth-failed", "schema-drift", "input-identity-drift"],
            evidence_fields=["status_xml", "version", "input_count", "probe_url"],
        ),
        "obs": DevicePluginManifest(
            plugin_id="obs",
            label="OBS WebSocket Plugin",
            device_class="obs",
            kind="software",
            supports_real_probe=True,
            supports_simulator=True,
            actions=["get-version", "start-recording", "stop-recording", "select-scene"],
            state_fields=["protocol_version", "scenes", "sources", "recording"],
            fault_modes=["websocket-disabled", "wrong-password", "protocol-mismatch"],
            evidence_fields=["obs_version", "obs_websocket_version", "request_id"],
        ),
        "atem": DevicePluginManifest(
            plugin_id="atem",
            label="ATEM Switcher Plugin",
            device_class="atem",
            kind="hardware",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["input-select", "cut", "auto-transition"],
            state_fields=["program", "preview", "in_transition"],
            fault_modes=["absent", "busy-transition", "protocol-mismatch"],
            evidence_fields=["program_input", "preview_input", "protocol_version"],
        ),
        "ptz-visca-ndi": DevicePluginManifest(
            plugin_id="ptz-visca-ndi",
            label="VISCA/PTZ NDI Plugin",
            device_class="ptz-visca-ndi",
            kind="hardware",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["preset-recall", "position-read"],
            state_fields=["ndi_source", "pan", "tilt", "zoom", "preset"],
            fault_modes=["offline", "timeout", "command-error", "ndi-disappears"],
            evidence_fields=["visca_command", "visca_ack", "visca_completion"],
        ),
        "decklink": DevicePluginManifest(
            plugin_id="decklink",
            label="DeckLink/SDI Readiness Plugin",
            device_class="decklink",
            kind="hardware",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["enumerate", "read-signal"],
            state_fields=["driver", "card", "channel", "mode", "signal"],
            fault_modes=["driver-missing", "card-absent", "mode-mismatch", "signal-unlocked"],
            evidence_fields=["driver_version", "device_name", "channel", "signal_state"],
        ),
        "usb-capture": DevicePluginManifest(
            plugin_id="usb-capture",
            label="Generic USB Capture Plugin",
            device_class="usb-capture",
            kind="hardware",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["enumerate", "read-identity"],
            state_fields=["stable_id", "friendly_name", "signal"],
            fault_modes=["absent", "identity-drift", "usb-reset", "no-signal"],
            evidence_fields=["stable_id", "friendly_name", "class"],
        ),
        "usb-audio": DevicePluginManifest(
            plugin_id="usb-audio",
            label="USB Audio Plugin",
            device_class="usb-audio",
            kind="hardware",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["enumerate", "read-format"],
            state_fields=["friendly_name", "sample_rate", "channels"],
            fault_modes=["absent", "sample-rate-mismatch", "sync-warning"],
            evidence_fields=["friendly_name", "sample_rate", "channels"],
        ),
        "network": DevicePluginManifest(
            plugin_id="network",
            label="Network Fault Plugin",
            device_class="network",
            kind="network",
            supports_real_probe=False,
            supports_simulator=True,
            actions=["apply-impairment", "clear-impairment"],
            state_fields=["latency_ms", "loss_percent", "dns_state"],
            fault_modes=["latency", "dropout", "dns-failure"],
            evidence_fields=["profile", "started_at", "cleared_at"],
        ),
        "audio-mixer": DevicePluginManifest(
            plugin_id="audio-mixer",
            label="Audio Mixer Topology Plugin",
            device_class="audio-mixer",
            kind="context",
            supports_real_probe=False,
            supports_simulator=False,
            actions=[],
            state_fields=["topology_present"],
            fault_modes=["not-configured"],
            evidence_fields=["topology_label"],
        ),
    }
    return sorted(plugin_by_class.values(), key=lambda plugin: plugin.plugin_id)


def list_scenarios() -> list[ScenarioDefinition]:
    return list(SCENARIOS.values())


def resolve_profile_ids(profile_ids: Iterable[str] | None) -> list[str] | None:
    """Map virtual-studio profile aliases to CivicCast LPM profile IDs."""

    if profile_ids is None:
        return None
    resolved: list[str] = []
    for profile_id in profile_ids:
        if profile_id == "all":
            resolved.append(profile_id)
            continue
        try:
            resolved.append(PROFILE_ALIASES[profile_id])
        except KeyError as exc:
            known = ", ".join(["all", *sorted(PROFILE_ALIASES)])
            raise ValueError(
                f"Unknown virtual studio profile {profile_id!r}. Known: {known}."
            ) from exc
    return resolved


def resolve_scenario(scenario_id: str) -> ScenarioDefinition:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        known = ", ".join(sorted(SCENARIOS))
        raise ValueError(
            f"Unknown virtual studio scenario {scenario_id!r}. Known: {known}."
        ) from exc


def run_scenario(
    *,
    profile_ids: list[str] | None,
    scenario_id: str,
    artifact_root: Path | None,
    force_clean: bool,
    probe_real_software: bool,
) -> VirtualStudioRun:
    """Execute an LPM scenario through the CivicCast LPM harness."""

    scenario = resolve_scenario(scenario_id)
    resolved_profile_ids = resolve_profile_ids(profile_ids)
    should_probe_real_software = probe_real_software or scenario.requires_real_software
    result = run_lpm_contract_lab(
        profile_ids=resolved_profile_ids,
        artifact_root=artifact_root,
        force_clean=force_clean,
        execution_stage=scenario.stage,
        probe_real_software=should_probe_real_software,
        require_software_lab=scenario.requires_real_software,
    )
    run = VirtualStudioRun(
        run_id=f"vstudio-{scenario.scenario_id}-{int(time.time())}",
        status=result.status,
        scenario_id=scenario.scenario_id,
        profiles=[_virtual_profile_id(profile_id) for profile_id in result.profiles],
        event_count=len(result.events),
        issues=result.issues,
        artifact_root=str(artifact_root) if artifact_root is not None else None,
        delegated_runner="civiccast.control_room.lpm_lab_harness",
    )
    if artifact_root is not None:
        delegated_readme = _preserve_delegated_readme(artifact_root)
        (artifact_root / "vstudio-summary.json").write_text(
            run.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (artifact_root / "vstudio-plugins.json").write_text(
            json.dumps(
                [plugin.model_dump(mode="json") for plugin in list_plugins()],
                indent=2,
            ),
            encoding="utf-8",
        )
        _write_vstudio_run_index(
            artifact_root,
            run=run,
            delegated_readme=delegated_readme,
        )
    return run


def _studio_profile(alias: str, source_id: TopologyId) -> StudioProfile:
    source = build_lpm_lab_profiles()[source_id]
    return StudioProfile(
        profile_id=alias,
        label=source.label,
        profile_pack="lpm",
        source_profile_id=source.profile_id,
        purpose=source.purpose,
        devices=[
            DeviceRef(
                device_id=device.contract_id,
                label=device.label,
                plugin_id=device.device_class,
                device_class=device.device_class,
                required=device.required_for_profile,
                checks=device.required_checks,
            )
            for device in source.devices
        ],
        required_absences=source.required_absences,
        outputs=source.egress_destinations,
    )


def _virtual_profile_id(source_profile_id: str) -> str:
    for alias, source in PROFILE_ALIASES.items():
        if source == source_profile_id:
            return alias
    return source_profile_id


def _preserve_delegated_readme(artifact_root: Path) -> str | None:
    readme = artifact_root / "README.md"
    if not readme.is_file():
        return None
    body = readme.read_text(encoding="utf-8")
    if body.startswith("# CivicCast Virtual Media Studio"):
        return None
    delegated = artifact_root / "delegated-lpm-contract-lab-README.md"
    delegated.write_text(body, encoding="utf-8")
    return delegated.name


def _write_vstudio_run_index(
    artifact_root: Path,
    *,
    run: VirtualStudioRun,
    delegated_readme: str | None,
) -> None:
    lines = [
        "# CivicCast Virtual Media Studio Run",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Status: `{run.status}`",
        f"- Scenario: `{run.scenario_id}`",
        f"- Profiles: {', '.join(run.profiles)}",
        f"- Events: {run.event_count}",
        f"- Issues: {len(run.issues)}",
        "",
        "## Virtual Studio Artifacts",
        "",
        "- `vstudio-summary.json` - wrapper run status.",
        "- `vstudio-plugins.json` - plugin manifest snapshot.",
    ]
    if delegated_readme is not None:
        lines.extend(
            [
                "- `delegated-lpm-contract-lab-README.md` - delegated CivicCast LPM harness evidence.",
                "- `summary.json`, `events.json`, and `profiles.json` - delegated harness machine data.",
            ]
        )
    lines.extend(
        [
            "",
            "This root is owned by the Virtual Media Studio wrapper. Delegated harness",
            "artifacts are supporting evidence, not the first thing a reviewer has to infer.",
            "",
        ]
    )
    (artifact_root / "README.md").write_text("\n".join(lines), encoding="utf-8")
