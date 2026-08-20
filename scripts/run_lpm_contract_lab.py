#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the local CivicCast 3.2 LPM contract lab."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help=(
            "Profile to run. Use multiple times or 'all'. Default: all. "
            "Known IDs: fixed-studio-livestreaming, portable-field-kit, digitization-obs."
        ),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help=(
            "Directory for summary.json, profiles.json, events.json, README.md, "
            "and stage-specific artifacts such as Stage 6-7 soak plans, support "
            "bundle manifests, station-evidence templates, redacted logs, Stage 8 "
            "release-hardening manifests, and reusable virtual-lab bundle files. "
            "Stage 6-7 output is plan/rehearsal only; Stage 8 output is local "
            "hardening only. Neither is elapsed wall-clock soak proof."
        ),
    )
    parser.add_argument(
        "--force-clean",
        action="store_true",
        help=(
            "Replace only a marked CivicCast contract-lab artifact root under "
            "repo artifacts/ or system temp; refuses unmarked/shared directories."
        ),
    )
    parser.add_argument(
        "--execution-stage",
        choices=["catalog", "stage45", "stage67", "stage8"],
        default="catalog",
        help=(
            "catalog keeps Stage 0-1 check-catalog evidence only. stage45 adds "
            "opt-in Stage 4-5 API fixtures, stateful simulators, and software probes. "
            "stage67 also adds deterministic Stage 6-7 soak/chaos and station-readiness events. "
            "stage8 adds local release-hardening and reusable lab-bundle artifacts."
        ),
    )
    parser.add_argument(
        "--probe-real-software",
        action="store_true",
        help="In stage45/stage67 mode, probe local OBS/vMix endpoints and record the result.",
    )
    parser.add_argument(
        "--require-software-lab",
        action="store_true",
        help=(
            "Fail unless every selected profile software class, such as OBS or vMix, "
            "has a passed local software probe."
        ),
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List known LPM contract-lab profile IDs and exit.",
    )
    return parser.parse_args()


def _load_lab_modules() -> dict[str, Any]:
    try:
        from civiccast.control_room.lpm_lab import build_lpm_lab_profiles
        from civiccast.control_room.lpm_lab_harness import (
            run_lpm_contract_lab,
            summarize_software_lab,
        )
    except ModuleNotFoundError as exc:
        missing = exc.name or "required module"
        raise RuntimeError(
            f"Missing Python dependency {missing!r}. Run this command through "
            "`uv run python scripts/run_lpm_contract_lab.py ...` from the repo root."
        ) from exc
    return {
        "build_lpm_lab_profiles": build_lpm_lab_profiles,
        "run_lpm_contract_lab": run_lpm_contract_lab,
        "summarize_software_lab": summarize_software_lab,
    }


def main() -> int:
    args = parse_args()
    try:
        modules = _load_lab_modules()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.list_profiles:
        for profile_id in modules["build_lpm_lab_profiles"]():
            print(profile_id)
        return 0

    artifact_root = args.artifact_root
    if artifact_root is None:
        artifact_root = ROOT / "artifacts" / "lpm-contract-lab" / time.strftime("%Y%m%d-%H%M%S")
    try:
        result = modules["run_lpm_contract_lab"](
            profile_ids=args.profiles,
            artifact_root=artifact_root,
            force_clean=args.force_clean,
            execution_stage=args.execution_stage,
            probe_real_software=args.probe_real_software,
            require_software_lab=args.require_software_lab,
        )
    except (ValueError, FileExistsError, NotADirectoryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"LPM contract lab status: {result.status}")
    print(f"Execution stage: {result.execution_stage}")
    print(f"Profiles: {', '.join(result.profiles)}")
    print(f"Events: {len(result.events)}")
    if result.execution_stage in {"stage45", "stage67", "stage8"}:
        print("Software probe summary:")
        for line in modules["summarize_software_lab"](result):
            print(f"- {line}")
    if result.execution_stage == "stage67":
        from civiccast.control_room.lpm_lab_stage67 import summarize_stage67_events

        print("Stage 6-7 summary:")
        for line in summarize_stage67_events(result.events):
            print(f"- {line}")
    if result.execution_stage == "stage8":
        from civiccast.control_room.lpm_lab_stage8 import summarize_stage8_events

        print("Stage 8 summary:")
        for line in summarize_stage8_events(result.events):
            print(f"- {line}")
    print(f"Artifacts: {artifact_root}")
    if result.issues:
        print("Issues:")
        for issue in result.issues:
            print(f"- {issue}")
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
