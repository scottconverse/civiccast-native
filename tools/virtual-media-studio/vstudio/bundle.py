# SPDX-License-Identifier: Apache-2.0
"""Portable bundle writer for the Virtual Media Studio lab."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from vstudio.models import VirtualStudioBundleManifest
from vstudio.registry import VirtualStudioRegistry

BUNDLE_ARTIFACT_MARKER = ".civiccast-vstudio-bundle-artifacts"
CONTRACT_VERSION = "vstudio-contract-v1"


def build_bundle_manifest(
    registry: VirtualStudioRegistry | None = None,
) -> VirtualStudioBundleManifest:
    """Build the portable lab manifest without writing files."""

    registry = registry or VirtualStudioRegistry()
    return VirtualStudioBundleManifest(
        schema_id="civiccast.virtual-media-studio.bundle.v1",
        generated_at_unix=int(time.time()),
        contract_version=CONTRACT_VERSION,
        profile_packs=registry.list_profile_packs(),
        plugins=registry.list_plugins(),
        profiles=registry.list_profiles(),
        scenarios=registry.list_scenarios(),
        extension_points=[
            "Add profile packs by implementing the ProfilePackModule protocol.",
            "Add device plugins by declaring DevicePluginManifest rows.",
            "Add software probes by routing ProbeTarget values to probe modules.",
            "Add scenarios by mapping ScenarioDefinition.stage to a runner stage.",
        ],
        artifact_files=[
            "vstudio-bundle-manifest.json",
            "profile-packs.json",
            "plugins.json",
            "profiles.json",
            "scenarios.json",
            "extension-contract.md",
            "README.md",
        ],
        not_claimed=[
            "This bundle is a reusable local lab description, not a CivicCast release artifact.",
            "This bundle does not claim station-device evidence or production certification.",
            "This bundle does not run an elapsed wall-clock soak.",
        ],
    )


def write_bundle(
    artifact_root: Path,
    *,
    force_clean: bool = False,
    registry: VirtualStudioRegistry | None = None,
) -> VirtualStudioBundleManifest:
    """Write a portable Virtual Media Studio bundle."""

    registry = registry or VirtualStudioRegistry()
    manifest = build_bundle_manifest(registry)
    _prepare_bundle_root(artifact_root, force_clean=force_clean)
    (artifact_root / BUNDLE_ARTIFACT_MARKER).write_text(
        "CivicCast Virtual Media Studio bundle artifact root. Safe for bundle cleanup only.\n",
        encoding="utf-8",
    )
    (artifact_root / "vstudio-bundle-manifest.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (artifact_root / "profile-packs.json").write_text(
        json.dumps([pack.model_dump(mode="json") for pack in manifest.profile_packs], indent=2),
        encoding="utf-8",
    )
    (artifact_root / "plugins.json").write_text(
        json.dumps([plugin.model_dump(mode="json") for plugin in manifest.plugins], indent=2),
        encoding="utf-8",
    )
    (artifact_root / "profiles.json").write_text(
        json.dumps([profile.model_dump(mode="json") for profile in manifest.profiles], indent=2),
        encoding="utf-8",
    )
    (artifact_root / "scenarios.json").write_text(
        json.dumps([scenario.model_dump(mode="json") for scenario in manifest.scenarios], indent=2),
        encoding="utf-8",
    )
    (artifact_root / "extension-contract.md").write_text(
        _render_extension_contract(manifest),
        encoding="utf-8",
    )
    (artifact_root / "README.md").write_text(_render_bundle_readme(manifest), encoding="utf-8")
    return manifest


def _prepare_bundle_root(artifact_root: Path, *, force_clean: bool) -> None:
    if artifact_root.exists() and not artifact_root.is_dir():
        raise NotADirectoryError(f"Bundle root exists and is not a directory: {artifact_root}")
    if artifact_root.exists() and any(artifact_root.iterdir()):
        if not force_clean:
            raise FileExistsError(
                f"Bundle root already contains files: {artifact_root}. Use --force-clean "
                "only for a marked Virtual Media Studio bundle artifact root."
            )
        _assert_safe_bundle_root(artifact_root)
        for child in artifact_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    artifact_root.mkdir(parents=True, exist_ok=True)


def _assert_safe_bundle_root(artifact_root: Path) -> None:
    resolved = artifact_root.resolve(strict=False)
    repo_artifacts = Path(__file__).resolve().parents[3] / "artifacts"
    safe_roots = [repo_artifacts.resolve(strict=False), Path(tempfile.gettempdir()).resolve()]
    if any(resolved == safe_root for safe_root in safe_roots) or not any(
        _is_relative_to(resolved, safe_root) for safe_root in safe_roots
    ):
        raise ValueError(
            "Refusing force_clean outside a safe child artifact root. "
            "Choose a dedicated directory under repo artifacts or system temp."
        )
    if not (artifact_root / BUNDLE_ARTIFACT_MARKER).is_file():
        raise ValueError(
            "Refusing force_clean because the artifact root is not marked as a "
            "Virtual Media Studio bundle artifact directory."
        )


def _render_extension_contract(manifest: VirtualStudioBundleManifest) -> str:
    lines = [
        "# Virtual Media Studio Extension Contract",
        "",
        f"Contract version: `{manifest.contract_version}`",
        "",
        "A profile pack can be moved into a separate repository later if it keeps",
        "these public shapes stable:",
        "",
        "- `ProfilePackModule` metadata: `PACK_ID`, `LABEL`, `VERSION`, `CONTRACT_VERSION`, `SOURCE`.",
        "- `list_profiles()` returns `StudioProfile` records.",
        "- `list_plugins()` returns `DevicePluginManifest` records.",
        "- `list_scenarios()` returns `ScenarioDefinition` records.",
        "- `resolve_profile_ids()` maps user-facing profile IDs to runner profile IDs.",
        "- `resolve_scenario()` fails closed on unknown scenario names.",
        "- `run_scenario(profile_ids, scenario_id, artifact_root, force_clean, probe_real_software)` executes the selected scenario and returns a `VirtualStudioRun`.",
        "- `run_scenario()` owns scenario artifact writes for its profile pack and must fail closed on unsupported scenarios or unsafe cleanup roots.",
        "",
        "Supported extension points:",
        "",
        *[f"- {item}" for item in manifest.extension_points],
        "",
        "No plugin may store credentials in a profile, fixture, log, or bundle.",
        "Runtime credentials belong in CivicCast's credential store.",
        "",
        "## Evidence and Claim Boundary",
        "",
        "Every profile pack and plugin must preserve the same evidence vocabulary",
        "used by CivicCast:",
        "",
        "- `mocked` rows are useful for rehearsal only and are not release claims.",
        "- `simulated-proven` rows come from deterministic simulators or fault harnesses.",
        "- `api-contract-proven` rows are backed by strict vendor/API fixtures.",
        "- `software-lab-proven` rows require a real local application or runtime probe.",
        "- `station-device-proven` rows require separately captured station evidence.",
        "",
        "`supports_real_probe` declares capability only; it is not evidence by itself.",
        "Plugins must record the artifact path, status, proof level, and explicit",
        "`not_claimed` boundary for every run. Non-confined media-control listeners",
        "may prove API compatibility, but must not be described as secure listener",
        "posture.",
        "",
        "Bundles must not claim elapsed wall-clock soak, production certification,",
        "or station-device operation unless the corresponding artifact exists in",
        "the same package. Credentials, tokens, passwords, and secret-bearing URLs",
        "must be redacted from logs, fixtures, support bundles, and status text.",
        "",
    ]
    return "\n".join(lines)


def _render_bundle_readme(manifest: VirtualStudioBundleManifest) -> str:
    return "\n".join(
        [
            "# CivicCast Virtual Media Studio Bundle",
            "",
            f"- Schema: `{manifest.schema_id}`",
            f"- Contract: `{manifest.contract_version}`",
            f"- Profile packs: {len(manifest.profile_packs)}",
            f"- Profiles: {len(manifest.profiles)}",
            f"- Plugins: {len(manifest.plugins)}",
            f"- Scenarios: {len(manifest.scenarios)}",
            "",
            "This bundle is reusable local lab software for CivicCast 3.2 work.",
            "It is shaped so the lab can later become a standalone project without",
            "rewriting the profile/plugin/scenario contracts.",
            "",
            "## Files",
            "",
            *[f"- `{path}`" for path in manifest.artifact_files],
            "",
            "## Not Claimed",
            "",
            *[f"- {claim}" for claim in manifest.not_claimed],
            "",
        ]
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


__all__ = ["BUNDLE_ARTIFACT_MARKER", "CONTRACT_VERSION", "build_bundle_manifest", "write_bundle"]
