#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run an elapsed wall-clock CivicCast 3.2 LPM contract-lab soak.

This runner is intentionally separate from the fast local CI gate. It repeats the
Stage 8 contract-lab path for the requested elapsed duration, records every cycle,
and writes a machine-readable endurance artifact.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from civiccast.control_room.lpm_lab_harness import LabRunResult, run_lpm_contract_lab  # noqa: E402
from scripts.collect_source_state import collect_source_state  # noqa: E402

MARKER = ".civiccast-lpm-wall-clock-soak-artifacts"
DEFAULT_DURATION_SECONDS = 4 * 60 * 60
DEFAULT_INTERVAL_SECONDS = 5 * 60


Clock = Callable[[], float]
Sleeper = Callable[[float], None]
WallClock = Callable[[], datetime]
LabRunner = Callable[..., LabRunResult]


@dataclass(frozen=True)
class SoakConfig:
    """Configuration for one elapsed soak run."""

    artifact_root: Path
    duration_seconds: int = DEFAULT_DURATION_SECONDS
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    profiles: list[str] | None = None
    probe_real_software: bool = False
    require_software_lab: bool = False
    force_clean: bool = False


def run_wall_clock_soak(
    config: SoakConfig,
    *,
    lab_runner: LabRunner = run_lpm_contract_lab,
    clock: Clock = time.monotonic,
    sleeper: Sleeper = time.sleep,
    wall_clock: WallClock = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Run the elapsed soak and return the final summary payload."""

    if config.duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")
    if config.interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    artifact_root = config.artifact_root
    _prepare_artifact_root(artifact_root, force_clean=config.force_clean)
    cycles_root = artifact_root / "cycles"
    cycles_root.mkdir(exist_ok=True)

    source_state = collect_source_state(artifact_root=artifact_root)
    started_at = wall_clock()
    started_monotonic = clock()
    deadline = started_monotonic + config.duration_seconds
    cycle_summaries: list[dict[str, Any]] = []
    issues: list[str] = []
    cycle_index = 0

    running_summary = _summary_payload(
        config=config,
        status="running",
        started_at=started_at,
        completed_at=None,
        elapsed_seconds=0.0,
        cycles=cycle_summaries,
        issues=issues,
        source_state=source_state,
    )
    _write_json(artifact_root / "summary.json", running_summary)

    while clock() < deadline or not cycle_summaries:
        cycle_index += 1
        cycle_start = clock()
        cycle_started_at = wall_clock()
        cycle_root = cycles_root / f"{cycle_index:04d}"

        try:
            result = lab_runner(
                profile_ids=config.profiles,
                artifact_root=cycle_root,
                force_clean=True,
                execution_stage="stage8",
                probe_real_software=config.probe_real_software,
                require_software_lab=config.require_software_lab,
            )
        except Exception as exc:  # pragma: no cover - exercised through CLI failures
            cycle_completed_at = wall_clock()
            cycle_elapsed = clock() - cycle_start
            issue = f"cycle {cycle_index} raised {type(exc).__name__}: {exc}"
            issues.append(issue)
            cycle_summary = {
                "index": cycle_index,
                "artifact_root": str(cycle_root),
                "started_at": _iso(cycle_started_at),
                "completed_at": _iso(cycle_completed_at),
                "elapsed_seconds": round(cycle_elapsed, 3),
                "status": "failed",
                "event_count": 0,
                "issue_count": 1,
                "issues": [issue],
            }
        else:
            cycle_completed_at = wall_clock()
            cycle_elapsed = clock() - cycle_start
            if result.status != "passed":
                issues.append(f"cycle {cycle_index} status was {result.status}")
            if result.issues:
                issues.extend(f"cycle {cycle_index}: {issue}" for issue in result.issues)
            cycle_summary = {
                "index": cycle_index,
                "artifact_root": str(cycle_root),
                "started_at": _iso(cycle_started_at),
                "completed_at": _iso(cycle_completed_at),
                "elapsed_seconds": round(cycle_elapsed, 3),
                "status": result.status,
                "execution_stage": result.execution_stage,
                "profiles": list(result.profiles),
                "event_count": len(result.events),
                "issue_count": len(result.issues),
                "issues": list(result.issues),
            }

        cycle_summaries.append(cycle_summary)
        elapsed = clock() - started_monotonic
        status = "running" if not issues else "failed"
        _write_json(
            artifact_root / "summary.json",
            _summary_payload(
                config=config,
                status=status,
                started_at=started_at,
                completed_at=None,
                elapsed_seconds=elapsed,
                cycles=cycle_summaries,
                issues=issues,
                source_state=source_state,
            ),
        )

        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(config.interval_seconds, remaining))

    completed_at = wall_clock()
    elapsed = clock() - started_monotonic
    if elapsed < config.duration_seconds:
        issues.append(
            f"elapsed duration {elapsed:.3f}s was shorter than requested {config.duration_seconds}s"
        )
    if not cycle_summaries:
        issues.append("no soak cycles ran")

    final_status = "passed" if not issues else "failed"
    final_summary = _summary_payload(
        config=config,
        status=final_status,
        started_at=started_at,
        completed_at=completed_at,
        elapsed_seconds=elapsed,
        cycles=cycle_summaries,
        issues=issues,
        source_state=source_state,
    )
    _write_json(artifact_root / "summary.json", final_summary)
    _write_readme(artifact_root / "README.md", final_summary)
    return final_summary


def _summary_payload(
    *,
    config: SoakConfig,
    status: str,
    started_at: datetime,
    completed_at: datetime | None,
    elapsed_seconds: float,
    cycles: list[dict[str, Any]],
    issues: list[str],
    source_state: dict[str, Any],
) -> dict[str, Any]:
    passed_cycles = sum(1 for cycle in cycles if cycle.get("status") == "passed")
    failed_cycles = sum(1 for cycle in cycles if cycle.get("status") == "failed")
    return {
        "schema": "civiccast.lpm.wall-clock-soak.v1",
        "status": status,
        "artifact_root": str(config.artifact_root),
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at) if completed_at else None,
        "requested_duration_seconds": config.duration_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "interval_seconds": config.interval_seconds,
        "cycle_count": len(cycles),
        "passed_cycle_count": passed_cycles,
        "failed_cycle_count": failed_cycles,
        "probe_real_software": config.probe_real_software,
        "require_software_lab": config.require_software_lab,
        "profiles": config.profiles or ["all"],
        "source_state": source_state,
        "cycles": cycles,
        "issues": issues,
        "not_claimed": [
            "This is local elapsed endurance evidence for the contract lab.",
            "It does not push, merge, tag, publish, or certify a public release.",
        ],
    }


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# LPM Contract Lab Wall-Clock Soak",
        "",
        f"- Status: `{summary['status']}`",
        f"- Requested duration seconds: `{summary['requested_duration_seconds']}`",
        f"- Elapsed seconds: `{summary['elapsed_seconds']}`",
        f"- Cycles: `{summary['cycle_count']}`",
        f"- Passed cycles: `{summary['passed_cycle_count']}`",
        f"- Failed cycles: `{summary['failed_cycle_count']}`",
        f"- Source diff SHA256: `{summary['source_state']['diff_sha256']}`",
        "",
        "This artifact records elapsed local endurance for the contract lab. It does not",
        "push, merge, tag, publish, or certify a public release.",
        "",
        "## Cycle Artifacts",
        "",
    ]
    for cycle in summary["cycles"]:
        lines.append(f"- Cycle {cycle['index']}: `{cycle['status']}` - `{cycle['artifact_root']}`")
    if summary["issues"]:
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- {issue}" for issue in summary["issues"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_artifact_root(artifact_root: Path, *, force_clean: bool) -> None:
    if artifact_root.exists() and not artifact_root.is_dir():
        raise NotADirectoryError(f"Artifact root exists and is not a directory: {artifact_root}")
    if artifact_root.exists() and any(artifact_root.iterdir()):
        if not force_clean:
            raise FileExistsError(
                f"Artifact root already contains files: {artifact_root}. Use --force-clean."
            )
        _assert_safe_force_clean_root(artifact_root)
        for child in artifact_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / MARKER).write_text(
        "CivicCast LPM wall-clock soak artifact root. Safe for soak cleanup only.\n",
        encoding="utf-8",
    )


def _assert_safe_force_clean_root(artifact_root: Path) -> None:
    resolved = artifact_root.resolve(strict=False)
    repo_artifacts = ROOT / "artifacts"
    safe_roots = [repo_artifacts.resolve(strict=False), Path(tempfile.gettempdir()).resolve()]
    if any(resolved == safe_root for safe_root in safe_roots) or not any(
        _is_relative_to(resolved, safe_root) for safe_root in safe_roots
    ):
        raise ValueError(
            "Refusing force_clean outside a safe child artifact root. Choose a dedicated "
            "directory under repo artifacts/ or system temp."
        )
    if not (artifact_root / MARKER).is_file():
        raise ValueError(
            "Refusing force_clean because the artifact root is not marked as a "
            "CivicCast LPM wall-clock soak artifact directory."
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT / "artifacts" / "wall-clock-soak" / time.strftime("%Y%m%d-%H%M%S"),
        help="Artifact directory for summary.json, README.md, source-state, and per-cycle artifacts.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
        help="Elapsed soak duration. Default: 14400 seconds (4 hours).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Delay between Stage 8 cycles. Default: 300 seconds.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Profile to run. Use multiple times or 'all'. Default: all.",
    )
    parser.add_argument(
        "--probe-real-software",
        action="store_true",
        help="Probe local OBS/vMix endpoints during each cycle.",
    )
    parser.add_argument(
        "--require-software-lab",
        action="store_true",
        help="Fail a cycle unless every selected OBS/vMix software class has a passed probe.",
    )
    parser.add_argument(
        "--force-clean",
        action="store_true",
        help="Replace only a marked soak artifact root under repo artifacts/ or system temp.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = run_wall_clock_soak(
            SoakConfig(
                artifact_root=args.artifact_root,
                duration_seconds=args.duration_seconds,
                interval_seconds=args.interval_seconds,
                profiles=args.profiles,
                probe_real_software=args.probe_real_software,
                require_software_lab=args.require_software_lab,
                force_clean=args.force_clean,
            )
        )
    except (ValueError, FileExistsError, NotADirectoryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"LPM wall-clock soak status: {summary['status']}")
    print(f"Elapsed seconds: {summary['elapsed_seconds']}")
    print(f"Cycles: {summary['cycle_count']}")
    print(f"Artifacts: {summary['artifact_root']}")
    if summary["issues"]:
        print("Issues:")
        for issue in summary["issues"]:
            print(f"- {issue}")
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
