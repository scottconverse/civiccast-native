#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 4 Virtual Media Studio proof envelope."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state

ROOT = Path(__file__).resolve().parents[1]
VSTUDIO_ROOT = ROOT / "tools" / "virtual-media-studio"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VSTUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(VSTUDIO_ROOT))

from vstudio.bundle import write_bundle  # noqa: E402

from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab  # noqa: E402


def build_stage4_virtual_lab_proof(
    *,
    artifact_root: Path,
    source_state: dict[str, Any] | None = None,
    probe_real_software: bool = True,
) -> dict[str, Any]:
    """Build Stage 4 proof by running the Stage 4-5 lab and bundle writer."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=ROOT)
    lab_root = artifact_root / "lpm-contract-lab"
    lab_result = run_lpm_contract_lab(
        profile_ids=["all"],
        artifact_root=lab_root,
        force_clean=bool(lab_root.exists()),
        execution_stage="stage45",
        probe_real_software=probe_real_software,
    )
    bundle_root = artifact_root / "virtual-media-studio-bundle"
    bundle_manifest = write_bundle(bundle_root, force_clean=bool(bundle_root.exists()))
    bundle_files = [path for path in bundle_root.rglob("*") if path.is_file()]
    summary = {
        "profiles": len(lab_result.profiles),
        "events": len(lab_result.events),
        "api_fixture_events": sum(
            1 for event in lab_result.events if event.proof_source == "api-fixture"
        ),
        "stateful_simulator_events": sum(
            1 for event in lab_result.events if event.proof_source == "stateful-simulator"
        ),
        "software_probe_events": sum(
            1 for event in lab_result.events if event.proof_source == "software-lab"
        ),
        "bundle_files": len(bundle_files),
        "bundle_profiles": len(bundle_manifest.profiles),
        "bundle_plugins": len(bundle_manifest.plugins),
        "bundle_scenarios": len(bundle_manifest.scenarios),
    }
    checks = [
        _check(
            "stage4-current-source",
            not resolved_source.get("dirty"),
            "Current source state is dirty.",
        ),
        _check(
            "stage4-lpm-stage45-lab",
            lab_result.status == "passed" and lab_result.execution_stage == "stage45",
            "Stage 4-5 LPM lab did not pass.",
        ),
        _check(
            "stage4-virtual-media-studio-bundle",
            (bundle_root / "vstudio-bundle-manifest.json").is_file()
            and summary["bundle_files"] >= 3,
            "Virtual Media Studio bundle manifest was not written.",
        ),
        _check(
            "stage4-proof-boundary",
            any("station-device" in claim.lower() for claim in bundle_manifest.not_claimed),
            "Virtual Media Studio bundle is missing station-device proof boundary.",
        ),
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "blocked"
    proof = {
        "stage_id": "3.5-stage4",
        "stage_name": "Virtual Media Studio And Reusable Local Lab",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "lab": {
            "artifact_root": str(lab_root),
            "status": lab_result.status,
            "execution_stage": lab_result.execution_stage,
            "profiles": lab_result.profiles,
            "issues": lab_result.issues,
        },
        "virtual_media_studio_bundle": {
            "artifact_root": str(bundle_root),
            "schema_id": bundle_manifest.schema_id,
            "contract_version": bundle_manifest.contract_version,
        },
        "summary": summary,
        "checks": checks,
        "not_claimed": [
            "Stage 4 local proof does not claim station-device evidence.",
            "Stage 4 local proof does not claim elapsed wall-clock soak.",
            "Stage 4 local proof does not claim clean Windows install proof.",
        ],
    }
    _write_json(artifact_root / "stage4-virtual-lab-proof.json", proof)
    _write_markdown(artifact_root / "stage4-virtual-lab-proof.md", proof)
    return proof


def _check(check_id: str, passed: bool, blocked_note: str) -> dict[str, str]:
    if passed:
        return {"id": check_id, "status": "passed"}
    return {"id": check_id, "status": "blocked", "notes": blocked_note}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, proof: dict[str, Any]) -> None:
    lines = [
        "# Stage 4 Virtual Lab Proof",
        "",
        f"Status: {proof['status']}",
        f"Source HEAD: {proof['source_state'].get('head')}",
        f"LPM lab: {proof['lab']['artifact_root']}",
        f"Virtual Media Studio bundle: {proof['virtual_media_studio_bundle']['artifact_root']}",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(proof["summary"]):
        lines.append(f"- {key}: {proof['summary'][key]}")
    lines.extend(["", "## Checks", ""])
    for check in proof["checks"]:
        note = f" - {check['notes']}" if check.get("notes") else ""
        lines.append(f"- {check['status']}: {check['id']}{note}")
    lines.extend(["", "## Not Claimed", ""])
    lines.extend(f"- {claim}" for claim in proof["not_claimed"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/stage4-virtual-lab/3.5-stage4-final"),
    )
    parser.add_argument(
        "--skip-real-software-probes",
        action="store_true",
        help="Do not attempt local OBS/vMix software probes.",
    )
    args = parser.parse_args(argv)
    proof = build_stage4_virtual_lab_proof(
        artifact_root=args.artifact_root,
        probe_real_software=not args.skip_real_software_probes,
    )
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
