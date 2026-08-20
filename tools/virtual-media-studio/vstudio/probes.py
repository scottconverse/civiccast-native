# SPDX-License-Identifier: Apache-2.0
"""Local software probes for the reusable Virtual Media Studio."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from civiccast.control_room.lpm_lab_harness import LabRunResult, run_lpm_contract_lab
from vstudio.models import ProbeCheck, ProbeTarget, RunStatus, SoftwareProbeRun

PROBE_ARTIFACT_MARKER = ".civiccast-vstudio-probe-artifacts"

_TARGET_PROFILES: dict[ProbeTarget, list[str]] = {
    "obs": ["digitization-obs"],
    "vmix": ["fixed-studio-livestreaming", "portable-field-kit"],
    "all": ["all"],
}

_NDI_CANDIDATES = [
    Path(
        "C:/Program Files/NDI/NDI 6 Tools/Studio Monitor/Application.Network.StudioMonitor.x64.exe"
    ),
    Path(
        "C:/Program Files/NDI/NDI 5 Tools/Studio Monitor/Application.Network.StudioMonitor.x64.exe"
    ),
    Path("C:/Program Files (x86)/vMix/ndi/x64/Processing.NDI.Lib.dll"),
    Path("C:/Program Files (x86)/vMix/NDIInterop.dll"),
    Path("C:/Program Files (x86)/vMix/NDINode.exe"),
]


def probe(
    target: ProbeTarget,
    artifact_root: Path | None = None,
    *,
    force_clean: bool = False,
) -> SoftwareProbeRun:
    """Probe installed local media software/runtime dependencies."""

    if target == "ndi":
        return _probe_ndi(artifact_root, force_clean=force_clean)

    lpm_result = _probe_lpm_software(target, artifact_root, force_clean=force_clean)
    checks = [
        ProbeCheck(
            evidence_key=f"{event.profile_id}:{event.device_id}:{event.check_id}",
            check_id=event.check_id,
            profile_id=event.profile_id,
            device_id=event.device_id,
            device_label=str(event.details.get("device_label") or "") or None,
            status=event.status,
            observed=event.observed,
            details=event.details,
        )
        for event in lpm_result.events
        if event.check_id.startswith("software-probe-")
    ]
    issues = list(lpm_result.issues)

    if target == "all":
        ndi = _probe_ndi(artifact_root, force_clean=False)
        checks.extend(ndi.checks)
        issues.extend(ndi.issues)

    status: RunStatus = (
        "failed" if issues or any(check.status == "failed" for check in checks) else "passed"
    )
    if not checks:
        status = "not-applicable"
    result = SoftwareProbeRun(
        target=target,
        status=status,
        checks=checks,
        issues=issues,
        artifact_root=str(artifact_root) if artifact_root is not None else None,
    )
    _write_probe_result(result, artifact_root, f"vstudio-probe-{target}.json")
    return result


def _probe_lpm_software(
    target: ProbeTarget,
    artifact_root: Path | None,
    *,
    force_clean: bool,
) -> LabRunResult:
    return run_lpm_contract_lab(
        profile_ids=_TARGET_PROFILES[target],
        artifact_root=artifact_root,
        force_clean=force_clean,
        execution_stage="stage45",
        probe_real_software=True,
        require_software_lab=True,
    )


def _probe_ndi(artifact_root: Path | None, *, force_clean: bool) -> SoftwareProbeRun:
    if force_clean and artifact_root is not None:
        _clean_standalone_probe_root(artifact_root)
    present = [str(path) for path in _NDI_CANDIDATES if path.exists()]
    status: RunStatus = "passed" if present else "failed"
    issues = [] if present else ["NDI runtime/tool artifacts were required but not found."]
    observed = (
        f"Found {len(present)} local NDI runtime/tool artifact(s)."
        if present
        else "No local NDI runtime/tool artifacts found in known install paths."
    )
    result = SoftwareProbeRun(
        target="ndi",
        status=status,
        checks=[
            ProbeCheck(
                evidence_key="ndi:runtime:software-probe-ndi-runtime",
                check_id="software-probe-ndi-runtime",
                status=status,
                observed=observed,
                details={
                    "known_paths": [str(path) for path in _NDI_CANDIDATES],
                    "present_paths": present,
                },
            )
        ],
        issues=issues,
        artifact_root=str(artifact_root) if artifact_root is not None else None,
    )
    _write_probe_result(result, artifact_root, "vstudio-probe-ndi.json")
    return result


def _write_probe_result(result: SoftwareProbeRun, artifact_root: Path | None, name: str) -> None:
    if artifact_root is None:
        return
    artifact_root.mkdir(parents=True, exist_ok=True)
    delegated_readme = _preserve_delegated_readme(artifact_root)
    (artifact_root / PROBE_ARTIFACT_MARKER).write_text(
        "CivicCast Virtual Media Studio probe artifact root. Safe for probe cleanup only.\n",
        encoding="utf-8",
    )
    (artifact_root / name).write_text(
        json.dumps(result.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    _write_probe_index(
        artifact_root,
        result=result,
        result_file=name,
        delegated_readme=delegated_readme,
    )


def _clean_standalone_probe_root(artifact_root: Path) -> None:
    if not artifact_root.exists():
        return
    if not artifact_root.is_dir():
        raise NotADirectoryError(f"Artifact root exists and is not a directory: {artifact_root}")
    _assert_safe_probe_root(artifact_root)
    if any(artifact_root.iterdir()) and not (artifact_root / PROBE_ARTIFACT_MARKER).is_file():
        raise ValueError(
            "Refusing force_clean because the artifact root is not marked as a "
            "CivicCast Virtual Media Studio probe artifact directory."
        )
    for child in artifact_root.iterdir():
        if child.is_dir():
            raise ValueError(
                "Refusing to force-clean standalone probe root containing directories: "
                f"{artifact_root}"
            )
        child.unlink()


def _assert_safe_probe_root(artifact_root: Path) -> None:
    resolved = artifact_root.resolve(strict=False)
    repo_artifacts = Path(__file__).resolve().parents[3] / "artifacts"
    safe_roots = [repo_artifacts.resolve(strict=False), Path(tempfile.gettempdir()).resolve()]

    if any(resolved == safe_root for safe_root in safe_roots) or not any(
        _is_relative_to(resolved, safe_root) for safe_root in safe_roots
    ):
        raise ValueError(
            "Refusing force_clean outside a safe child artifact root. "
            "Choose a dedicated directory under the repo artifacts folder or system temp."
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _preserve_delegated_readme(artifact_root: Path) -> str | None:
    readme = artifact_root / "README.md"
    if not readme.is_file():
        return None
    body = readme.read_text(encoding="utf-8")
    if body.startswith("# CivicCast Virtual Media Studio"):
        delegated = artifact_root / "delegated-lpm-contract-lab-README.md"
        return delegated.name if delegated.is_file() else None
    delegated = artifact_root / "delegated-lpm-contract-lab-README.md"
    delegated.write_text(body, encoding="utf-8")
    return delegated.name


def _write_probe_index(
    artifact_root: Path,
    *,
    result: SoftwareProbeRun,
    result_file: str,
    delegated_readme: str | None,
) -> None:
    lines = [
        "# CivicCast Virtual Media Studio Probe",
        "",
        f"- Target: `{result.target}`",
        f"- Status: `{result.status}`",
        f"- Checks: {len(result.checks)}",
        f"- Issues: {len(result.issues)}",
        "",
        "## Virtual Studio Artifacts",
        "",
        f"- `{result_file}` - wrapper probe status.",
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
            "The NDI probe is a local runtime/tool artifact check. It does not discover",
            "NDI sources or touch station devices.",
            "",
        ]
    )
    (artifact_root / "README.md").write_text("\n".join(lines), encoding="utf-8")
