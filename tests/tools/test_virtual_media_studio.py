# SPDX-License-Identifier: Apache-2.0
"""Virtual Media Studio package tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2] / "tools" / "virtual-media-studio"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from vstudio import cli as vstudio_cli  # noqa: E402
from vstudio import probes  # noqa: E402
from vstudio.bundle import BUNDLE_ARTIFACT_MARKER, build_bundle_manifest, write_bundle  # noqa: E402
from vstudio.models import (  # noqa: E402
    DevicePluginManifest,
    DeviceRef,
    ScenarioDefinition,
    StudioProfile,
    VirtualStudioRun,
)
from vstudio.probes import PROBE_ARTIFACT_MARKER, probe  # noqa: E402
from vstudio.profile_packs import lpm  # noqa: E402
from vstudio.registry import VirtualStudioRegistry  # noqa: E402
from vstudio.runner import VirtualStudioRunner  # noqa: E402


def test_lpm_profile_pack_exposes_virtual_studio_profiles() -> None:
    profiles = {profile.profile_id: profile for profile in lpm.list_profiles()}

    assert set(profiles) == {
        "lpm-fixed-studio",
        "lpm-portable-field-kit",
        "lpm-digitization-obs",
    }
    assert profiles["lpm-fixed-studio"].source_profile_id == "fixed-studio-livestreaming"
    assert any(device.plugin_id == "vmix" for device in profiles["lpm-fixed-studio"].devices)
    assert "DeckLink card" in profiles["lpm-portable-field-kit"].required_absences


def test_virtual_studio_registry_exposes_profile_pack_manifest() -> None:
    registry = VirtualStudioRegistry()
    packs = registry.list_profile_packs()

    assert len(packs) == 1
    assert packs[0].pack_id == "lpm"
    assert packs[0].contract_version == "vstudio-contract-v1"
    assert packs[0].profile_count == 3
    assert packs[0].source == "civiccast.control_room.lpm_lab"


def test_lpm_profile_pack_declares_first_party_plugins() -> None:
    plugins = {plugin.plugin_id: plugin for plugin in lpm.list_plugins()}

    assert {"vmix", "obs", "atem", "ptz-visca-ndi", "decklink", "usb-capture"}.issubset(plugins)
    assert plugins["vmix"].supports_real_probe is True
    assert plugins["vmix"].supports_simulator is True
    assert "schema-drift" in plugins["vmix"].fault_modes
    assert plugins["atem"].supports_simulator is True


def test_virtual_studio_bundle_manifest_is_standalone_shaped() -> None:
    manifest = build_bundle_manifest()

    assert manifest.schema_id == "civiccast.virtual-media-studio.bundle.v1"
    assert manifest.contract_version == "vstudio-contract-v1"
    assert {pack.pack_id for pack in manifest.profile_packs} == {"lpm"}
    assert {profile.profile_pack for profile in manifest.profiles} == {"lpm"}
    assert "extension-contract.md" in manifest.artifact_files
    assert any("ProfilePackModule" in item for item in manifest.extension_points)
    assert any("does not run an elapsed wall-clock soak" in item for item in manifest.not_claimed)


def test_virtual_studio_bundle_extension_contract_names_claim_boundaries(tmp_path: Path) -> None:
    write_bundle(tmp_path)

    contract = (tmp_path / "extension-contract.md").read_text(encoding="utf-8")

    assert "Evidence and Claim Boundary" in contract
    assert (
        "`supports_real_probe` declares capability only; it is not evidence by itself." in contract
    )
    assert "Non-confined media-control listeners" in contract
    assert "must not be described as secure listener" in contract
    assert (
        "`run_scenario(profile_ids, scenario_id, artifact_root, force_clean, probe_real_software)`"
        in contract
    )
    assert "returns a `VirtualStudioRun`" in contract


def test_virtual_studio_runner_delegates_to_pack_owned_execution(tmp_path: Path) -> None:
    class FakePack:
        PACK_ID = "fake"
        LABEL = "Fake Lab"
        VERSION = "0.1"
        CONTRACT_VERSION = "vstudio-contract-v1"
        SOURCE = "tests.fake_pack"

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def list_profiles(self) -> list[StudioProfile]:
            return [
                StudioProfile(
                    profile_id="fake-main",
                    label="Fake Main",
                    profile_pack="fake",
                    source_profile_id="fake-source",
                    purpose="Exercise generic profile-pack dispatch.",
                    devices=[
                        DeviceRef(
                            device_id="fake-device",
                            label="Fake Device",
                            plugin_id="fake-plugin",
                            device_class="fake",
                        )
                    ],
                )
            ]

        def list_plugins(self) -> list[DevicePluginManifest]:
            return [
                DevicePluginManifest(
                    plugin_id="fake-plugin",
                    label="Fake Plugin",
                    device_class="fake",
                    kind="software",
                    supports_real_probe=False,
                    supports_simulator=True,
                )
            ]

        def list_scenarios(self) -> list[ScenarioDefinition]:
            return [
                ScenarioDefinition(scenario_id="fake-smoke", label="Fake Smoke", stage="catalog")
            ]

        def resolve_profile_ids(self, profile_ids: object) -> list[str] | None:
            return ["fake-source"] if profile_ids else None

        def resolve_scenario(self, scenario_id: str) -> ScenarioDefinition:
            if scenario_id != "fake-smoke":
                raise ValueError("unknown")
            return self.list_scenarios()[0]

        def run_scenario(
            self,
            *,
            profile_ids: list[str] | None,
            scenario_id: str,
            artifact_root: Path | None,
            force_clean: bool,
            probe_real_software: bool,
        ) -> VirtualStudioRun:
            self.calls.append(
                {
                    "profile_ids": profile_ids,
                    "scenario_id": scenario_id,
                    "force_clean": force_clean,
                    "probe_real_software": probe_real_software,
                }
            )
            if artifact_root is not None:
                artifact_root.mkdir(parents=True, exist_ok=True)
                (artifact_root / "fake-run.txt").write_text("ok\n", encoding="utf-8")
            return VirtualStudioRun(
                run_id="fake-run",
                status="passed",
                scenario_id=scenario_id,
                profiles=profile_ids or ["fake-main"],
                event_count=1,
                artifact_root=str(artifact_root) if artifact_root is not None else None,
                delegated_runner="tests.fake_pack",
            )

    fake_pack = FakePack()
    runner = VirtualStudioRunner(VirtualStudioRegistry([fake_pack]))

    result = runner.run(
        profile_ids=["fake-main"],
        scenario_id="fake-smoke",
        artifact_root=tmp_path,
        force_clean=True,
        probe_real_software=True,
    )

    runner_source = (TOOLS_ROOT / "vstudio" / "runner.py").read_text(encoding="utf-8")
    assert result.delegated_runner == "tests.fake_pack"
    assert fake_pack.calls == [
        {
            "profile_ids": ["fake-main"],
            "scenario_id": "fake-smoke",
            "force_clean": True,
            "probe_real_software": True,
        }
    ]
    assert (tmp_path / "fake-run.txt").is_file()
    assert "lpm_lab_harness" not in runner_source


def test_virtual_studio_runner_delegates_lpm_smoke_scenario(tmp_path: Path) -> None:
    runner = VirtualStudioRunner()

    result = runner.run(
        profile_ids=["lpm-fixed-studio"],
        scenario_id="smoke",
        artifact_root=tmp_path,
    )

    assert result.status == "passed"
    assert result.profiles == ["lpm-fixed-studio"]
    assert result.delegated_runner == "civiccast.control_room.lpm_lab_harness"
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "vstudio-summary.json").is_file()
    assert (tmp_path / "vstudio-plugins.json").is_file()
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# CivicCast Virtual Media Studio Run")
    assert "vstudio-summary.json" in readme
    assert "delegated-lpm-contract-lab-README.md" in readme
    assert (tmp_path / "delegated-lpm-contract-lab-README.md").is_file()


def test_virtual_studio_runner_maps_release_to_stage8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_lpm_contract_lab(**kwargs: object) -> object:
        artifact_root = kwargs["artifact_root"]
        assert isinstance(artifact_root, Path)
        (artifact_root / "summary.json").write_text(
            json.dumps({"execution_stage": kwargs["execution_stage"]}),
            encoding="utf-8",
        )
        (artifact_root / "stage8-release-manifest.json").write_text("{}\n", encoding="utf-8")
        bundle = artifact_root / "virtual-media-studio-bundle"
        bundle.mkdir()
        (bundle / "vstudio-bundle-manifest.json").write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            status="passed",
            profiles=["digitization-obs"],
            events=[SimpleNamespace()],
            issues=[],
        )

    monkeypatch.setattr(lpm, "run_lpm_contract_lab", fake_run_lpm_contract_lab)

    result = VirtualStudioRunner().run(
        profile_ids=["lpm-digitization-obs"],
        scenario_id="release",
        artifact_root=tmp_path,
    )
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert result.status == "passed"
    assert result.scenario_id == "release"
    assert summary["execution_stage"] == "stage8"
    assert (tmp_path / "stage8-release-manifest.json").is_file()
    assert (tmp_path / "virtual-media-studio-bundle" / "vstudio-bundle-manifest.json").is_file()


def test_virtual_studio_runner_maps_soak_to_stage67(tmp_path: Path) -> None:
    result = VirtualStudioRunner().run(
        profile_ids=["lpm-digitization-obs"],
        scenario_id="soak",
        artifact_root=tmp_path,
    )
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    # Overall status is honestly "failed" — the digitization-obs profile has
    # required checks (e.g. local-recording-evidence) with no Stage 4-5
    # fixture yet, and the harness now fails loudly on that instead of
    # silently dropping it (see test_lpm_lab_stage45.py).
    assert result.status == "failed"
    assert result.scenario_id == "soak"
    assert summary["execution_stage"] == "stage67"
    assert (tmp_path / "stage67-soak-plan.json").is_file()


def test_virtual_studio_cli_lists_profiles_and_runs_smoke(tmp_path: Path) -> None:
    script = TOOLS_ROOT / "civiccast-vstudio.py"

    listed = subprocess.run(
        [sys.executable, str(script), "profiles", "list"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert listed.returncode == 0
    assert "lpm-fixed-studio" in listed.stdout

    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "run",
            "--profile",
            "lpm-portable-field-kit",
            "--scenario",
            "smoke",
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0
    assert "lpm-portable-field-kit" in run.stdout
    assert (tmp_path / "vstudio-summary.json").is_file()


def test_virtual_studio_cli_lists_packs_and_writes_bundle(tmp_path: Path) -> None:
    script = TOOLS_ROOT / "civiccast-vstudio.py"

    packs = subprocess.run(
        [sys.executable, str(script), "packs", "list"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert packs.returncode == 0
    assert '"pack_id": "lpm"' in packs.stdout

    bundle_root = tmp_path / "bundle"
    bundle = subprocess.run(
        [
            sys.executable,
            str(script),
            "bundle",
            "write",
            "--artifact-root",
            str(bundle_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert bundle.returncode == 0
    assert "civiccast.virtual-media-studio.bundle.v1" in bundle.stdout
    assert (bundle_root / BUNDLE_ARTIFACT_MARKER).is_file()
    assert (bundle_root / "extension-contract.md").is_file()
    assert (bundle_root / "vstudio-bundle-manifest.json").is_file()


def test_virtual_studio_bundle_force_clean_requires_marker(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "unrelated.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="not marked"):
        write_bundle(bundle_root, force_clean=True)

    (bundle_root / BUNDLE_ARTIFACT_MARKER).write_text("owned\n", encoding="utf-8")
    write_bundle(bundle_root, force_clean=True)

    assert not (bundle_root / "unrelated.txt").exists()
    assert (bundle_root / "vstudio-bundle-manifest.json").is_file()


def test_virtual_studio_probe_ndi_writes_structured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ndi_runtime = tmp_path / "Processing.NDI.Lib.dll"
    ndi_runtime.write_text("ndi", encoding="utf-8")
    monkeypatch.setattr(probes, "_NDI_CANDIDATES", [ndi_runtime])

    result = probe("ndi", tmp_path)

    payload = result.model_dump(mode="json")
    assert payload["target"] == "ndi"
    assert payload["status"] == "passed"
    assert payload["checks"][0]["check_id"] == "software-probe-ndi-runtime"
    assert payload["checks"][0]["evidence_key"] == "ndi:runtime:software-probe-ndi-runtime"
    assert (tmp_path / PROBE_ARTIFACT_MARKER).is_file()
    assert (tmp_path / "vstudio-probe-ndi.json").is_file()
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# CivicCast Virtual Media Studio Probe")
    assert "runtime/tool artifact check" in readme
    assert "does not discover" in readme


def test_virtual_studio_probe_ndi_absence_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probes, "_NDI_CANDIDATES", [tmp_path / "missing.dll"])

    result = probe("ndi", tmp_path)

    assert result.status == "failed"
    assert result.checks[0].status == "failed"
    assert "required but not found" in result.issues[0]
    assert vstudio_cli._exit_code_for_payload(result.model_dump(mode="json")) == 1


def test_virtual_studio_probe_all_evidence_keys_are_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ndi_runtime = tmp_path / "Processing.NDI.Lib.dll"
    ndi_runtime.write_text("ndi", encoding="utf-8")
    monkeypatch.setattr(probes, "_NDI_CANDIDATES", [ndi_runtime])

    fake_events = [
        SimpleNamespace(
            profile_id="fixed-studio-livestreaming",
            device_id="fixed-vmix-streaming-pc",
            check_id="software-probe-vmix-http",
            status="passed",
            observed="fixed vMix",
            details={"device_label": "vMix Streaming PC"},
        ),
        SimpleNamespace(
            profile_id="portable-field-kit",
            device_id="portable-vmix-laptop",
            check_id="software-probe-vmix-http",
            status="passed",
            observed="portable vMix",
            details={"device_label": "vMix Laptop"},
        ),
    ]
    monkeypatch.setattr(
        probes,
        "_probe_lpm_software",
        lambda *args, **kwargs: SimpleNamespace(events=fake_events, issues=[]),
    )

    result = probe("all", tmp_path)

    evidence_keys = [check.evidence_key for check in result.checks]
    assert len(evidence_keys) == len(set(evidence_keys))
    assert result.checks[0].profile_id == "fixed-studio-livestreaming"
    assert result.checks[1].device_id == "portable-vmix-laptop"


def test_virtual_studio_probe_force_clean_requires_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probes, "_NDI_CANDIDATES", [tmp_path / "missing.dll"])
    (tmp_path / "unrelated.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="not marked"):
        probe("ndi", tmp_path, force_clean=True)

    (tmp_path / PROBE_ARTIFACT_MARKER).write_text("owned\n", encoding="utf-8")
    result = probe("ndi", tmp_path, force_clean=True)

    assert result.status == "failed"
    assert not (tmp_path / "unrelated.txt").exists()
    assert (tmp_path / PROBE_ARTIFACT_MARKER).is_file()


def test_virtual_studio_cli_reports_missing_dependency_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_missing_dependency(_args: object, _runner: object) -> object:
        raise ModuleNotFoundError("No module named 'defusedxml'", name="defusedxml")

    monkeypatch.setattr(vstudio_cli, "_dispatch", raise_missing_dependency)

    assert vstudio_cli.main(["profiles", "list"]) == 2
    captured = capsys.readouterr()
    assert "Missing Python dependency 'defusedxml'" in captured.err
    assert "Traceback" not in captured.err


def test_virtual_studio_wrapper_reports_import_time_dependency_without_traceback() -> None:
    script = TOOLS_ROOT / "civiccast-vstudio.py"

    result = subprocess.run(
        [sys.executable, "-S", "-B", str(script), "profiles", "list"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Missing Python dependency" in result.stderr
    assert "Traceback" not in result.stderr


def test_virtual_studio_cli_failed_payload_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(vstudio_cli, "_dispatch", lambda _args, _runner: {"status": "failed"})

    assert vstudio_cli.main(["profiles", "list"]) == 1
    captured = capsys.readouterr()
    assert '"status": "failed"' in captured.out


def test_virtual_studio_runner_rejects_unknown_profile_with_virtual_aliases() -> None:
    with pytest.raises(ValueError, match="lpm-fixed-studio"):
        VirtualStudioRunner().run(profile_ids=["fixed-studio-livestreaming"], scenario_id="smoke")
