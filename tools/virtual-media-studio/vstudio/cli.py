# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for the Virtual Media Studio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from vstudio.bundle import write_bundle
from vstudio.models import ProbeTarget
from vstudio.probes import probe
from vstudio.runner import VirtualStudioRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CivicCast Virtual Media Studio local lab runner.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    profiles = subcommands.add_parser(
        "profiles",
        description="Inspect reusable studio profiles.",
        help="Inspect reusable studio profiles.",
    )
    profile_subcommands = profiles.add_subparsers(dest="profiles_command", required=True)
    profile_subcommands.add_parser("list", help="List available profile aliases.")

    packs = subcommands.add_parser(
        "packs",
        description="Inspect reusable profile packs.",
        help="Inspect profile packs.",
    )
    pack_subcommands = packs.add_subparsers(dest="packs_command", required=True)
    pack_subcommands.add_parser("list", help="List available profile packs.")

    devices = subcommands.add_parser(
        "devices",
        description="Inspect devices declared by one or more profiles.",
        help="Inspect profile devices.",
    )
    device_subcommands = devices.add_subparsers(dest="devices_command", required=True)
    devices_list = device_subcommands.add_parser("list", help="List devices for a profile.")
    devices_list.add_argument(
        "--profile",
        default=None,
        help="Virtual profile alias, for example lpm-fixed-studio. Omit for all profiles.",
    )

    plugins = subcommands.add_parser(
        "plugins",
        description="Inspect first-party virtual-studio plugin manifests.",
        help="Inspect plugin manifests.",
    )
    plugin_subcommands = plugins.add_subparsers(dest="plugins_command", required=True)
    plugin_subcommands.add_parser("list", help="List plugin manifests.")

    scenarios = subcommands.add_parser(
        "scenarios",
        description="Inspect runnable scenario names.",
        help="Inspect scenarios.",
    )
    scenario_subcommands = scenarios.add_subparsers(dest="scenarios_command", required=True)
    scenario_subcommands.add_parser("list", help="List scenario names.")

    probe_parser = subcommands.add_parser(
        "probe",
        description=(
            "Probe installed local OBS, vMix, and NDI runtime/tool artifact targets. "
            "The NDI target checks install artifacts; it does not discover NDI sources."
        ),
        help="Probe installed local software.",
    )
    probe_parser.add_argument("target", choices=["obs", "vmix", "ndi", "all"], help="Probe target.")
    probe_parser.add_argument("--artifact-root", type=Path, default=None, help="Output directory.")
    probe_parser.add_argument(
        "--force-clean",
        action="store_true",
        help=(
            "Replace only a marked probe or contract-lab artifact directory under "
            "repo artifacts/ or system temp."
        ),
    )

    run = subcommands.add_parser(
        "run",
        description="Run a virtual studio scenario against one or more profiles.",
        help="Run a profile scenario.",
    )
    run.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        default=None,
        help="Virtual profile alias or all. Repeat for multiple profiles.",
    )
    run.add_argument("--scenario", default="smoke", help="Scenario name from `scenarios list`.")
    run.add_argument("--artifact-root", type=Path, default=None, help="Output directory.")
    run.add_argument(
        "--force-clean",
        action="store_true",
        help=(
            "Replace only a marked contract-lab artifact directory under repo "
            "artifacts/ or system temp."
        ),
    )
    run.add_argument(
        "--probe-real-software",
        action="store_true",
        help="Also probe reachable OBS/vMix software when the scenario supports it.",
    )

    bundle = subcommands.add_parser(
        "bundle",
        description="Write a portable Virtual Media Studio bundle manifest.",
        help="Write a reusable lab bundle.",
    )
    bundle_subcommands = bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_write = bundle_subcommands.add_parser("write", help="Write bundle artifacts.")
    bundle_write.add_argument("--artifact-root", type=Path, required=True, help="Output directory.")
    bundle_write.add_argument(
        "--force-clean",
        action="store_true",
        help="Replace only a marked Virtual Media Studio bundle artifact root.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = VirtualStudioRunner()
    try:
        payload = _dispatch(args, runner)
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        print(
            "ERROR: Missing Python dependency "
            f"{missing!r}. Run from the project environment, for example: "
            "`uv run python tools/virtual-media-studio/civiccast-vstudio.py ...`.",
            file=sys.stderr,
        )
        return 2
    except (FileExistsError, NotADirectoryError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2))
    return _exit_code_for_payload(payload)


def _dispatch(args: argparse.Namespace, runner: VirtualStudioRunner) -> object:
    if args.command == "profiles" and args.profiles_command == "list":
        return runner.list_profiles()
    if args.command == "packs" and args.packs_command == "list":
        return runner.list_profile_packs()
    if args.command == "devices" and args.devices_command == "list":
        return runner.list_devices(profile_id=args.profile)
    if args.command == "plugins" and args.plugins_command == "list":
        return runner.list_plugins()
    if args.command == "scenarios" and args.scenarios_command == "list":
        return runner.list_scenarios()
    if args.command == "probe":
        return probe(
            target=cast(ProbeTarget, args.target),
            artifact_root=args.artifact_root,
            force_clean=args.force_clean,
        ).model_dump(mode="json")
    if args.command == "run":
        return runner.run(
            profile_ids=args.profiles,
            scenario_id=args.scenario,
            artifact_root=args.artifact_root,
            force_clean=args.force_clean,
            probe_real_software=args.probe_real_software,
        ).model_dump(mode="json")
    if args.command == "bundle" and args.bundle_command == "write":
        return write_bundle(
            args.artifact_root,
            force_clean=args.force_clean,
        ).model_dump(mode="json")
    raise AssertionError(f"Unhandled command: {args.command}")


def _exit_code_for_payload(payload: object) -> int:
    if isinstance(payload, dict):
        status = payload.get("status")
        if status in {"failed", "not-applicable"}:
            return 1
    return 0
