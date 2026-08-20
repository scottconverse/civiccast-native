# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Network impairment shim for the E.2 virtual-headend gate.

This is test-only infrastructure. It builds and applies Linux ``tc netem``
profiles so loopback continuity tests do not hide transport discontinuities.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ImpairmentProfileName = Literal[
    "clean",
    "delay-jitter",
    "loss",
    "loss-reorder",
    "bad-link",
]


@dataclass(frozen=True)
class NetemProfile:
    """One required E.2 network impairment profile."""

    name: ImpairmentProfileName
    delay_ms: int = 0
    jitter_ms: int = 0
    loss_percent: float = 0.0
    reorder_percent: float = 0.0


@dataclass(frozen=True)
class NetemCommand:
    """One tc command plus whether cleanup failure is acceptable."""

    args: tuple[str, ...]
    ignore_failure: bool = False


@dataclass(frozen=True)
class CommandResult:
    """Small subprocess result contract for fakeable tc execution."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...]], CommandResult]


def required_netem_profiles() -> tuple[NetemProfile, ...]:
    """Return the minimum impairment matrix required by the E.2 spec."""

    return (
        NetemProfile(name="clean"),
        NetemProfile(name="delay-jitter", delay_ms=80, jitter_ms=20),
        NetemProfile(name="loss", loss_percent=2.0),
        NetemProfile(name="loss-reorder", loss_percent=2.0, reorder_percent=2.0),
        NetemProfile(
            name="bad-link",
            delay_ms=120,
            jitter_ms=35,
            loss_percent=3.0,
            reorder_percent=3.0,
        ),
    )


def build_netem_commands(
    *,
    interface: str,
    profile: NetemProfile,
    tc: str = "tc",
) -> tuple[NetemCommand, ...]:
    """Build cleanup + apply commands for one profile."""

    if not interface:
        raise ValueError("interface is required for tc netem")
    cleanup = NetemCommand(
        args=(tc, "qdisc", "delete", "dev", interface, "root"),
        ignore_failure=True,
    )
    if profile.name == "clean":
        return (cleanup,)
    args: list[str] = [tc, "qdisc", "add", "dev", interface, "root", "netem"]
    if profile.delay_ms > 0:
        args.extend(["delay", f"{profile.delay_ms}ms"])
        if profile.jitter_ms > 0:
            args.append(f"{profile.jitter_ms}ms")
    if profile.loss_percent > 0:
        args.extend(["loss", _percent(profile.loss_percent)])
    if profile.reorder_percent > 0:
        args.extend(["reorder", _percent(profile.reorder_percent)])
    return (cleanup, NetemCommand(args=tuple(args)))


def apply_netem_profile(
    *,
    interface: str,
    profile: NetemProfile,
    tc: str = "tc",
    runner: CommandRunner | None = None,
) -> tuple[CommandResult, ...]:
    """Apply one profile and fail closed if tc cannot install impairment."""

    results: list[CommandResult] = []
    active_runner = runner or _run_command
    for command in build_netem_commands(interface=interface, profile=profile, tc=tc):
        result = active_runner(command.args)
        results.append(result)
        if result.returncode != 0 and not command.ignore_failure:
            raise RuntimeError(
                f"tc netem command failed for profile {profile.name!r}: {result.stderr}"
            )
    return tuple(results)


def remove_netem_profile(
    *,
    interface: str,
    tc: str = "tc",
    runner: CommandRunner | None = None,
) -> CommandResult:
    """Remove netem from an interface; cleanup is idempotent for tests."""

    if not interface:
        raise ValueError("interface is required for tc netem cleanup")
    active_runner = runner or _run_command
    return active_runner((tc, "qdisc", "delete", "dev", interface, "root"))


def _run_command(args: tuple[str, ...]) -> CommandResult:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _percent(value: float) -> str:
    return f"{value:g}%"
