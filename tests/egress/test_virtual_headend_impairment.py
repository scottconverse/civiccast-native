# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import pytest

from tests.egress.virtual_headend_impairment import (
    CommandResult,
    NetemProfile,
    apply_netem_profile,
    build_netem_commands,
    remove_netem_profile,
    required_netem_profiles,
)


def test_required_netem_profiles_match_e2_matrix() -> None:
    profiles = required_netem_profiles()

    assert [profile.name for profile in profiles] == [
        "clean",
        "delay-jitter",
        "loss",
        "loss-reorder",
        "bad-link",
    ]
    assert profiles[1].delay_ms == 80
    assert profiles[1].jitter_ms == 20
    assert profiles[2].loss_percent == 2.0
    assert profiles[3].reorder_percent == 2.0
    assert profiles[4].delay_ms > 0
    assert profiles[4].loss_percent > profiles[2].loss_percent


def test_clean_profile_only_removes_existing_qdisc() -> None:
    commands = build_netem_commands(interface="veth-egress", profile=NetemProfile(name="clean"))

    assert commands == (
        (
            type(commands[0])(
                args=("tc", "qdisc", "delete", "dev", "veth-egress", "root"),
                ignore_failure=True,
            )
        ),
    )


def test_delay_jitter_profile_builds_tc_netem_command() -> None:
    commands = build_netem_commands(
        interface="veth-egress",
        profile=NetemProfile(name="delay-jitter", delay_ms=80, jitter_ms=20),
    )

    assert commands[0].ignore_failure is True
    assert commands[1].args == (
        "tc",
        "qdisc",
        "add",
        "dev",
        "veth-egress",
        "root",
        "netem",
        "delay",
        "80ms",
        "20ms",
    )


def test_loss_reorder_profile_builds_tc_netem_command() -> None:
    commands = build_netem_commands(
        interface="veth-egress",
        profile=NetemProfile(name="loss-reorder", loss_percent=2.0, reorder_percent=2.0),
    )

    assert commands[1].args[-4:] == ("loss", "2%", "reorder", "2%")


def test_build_netem_commands_uses_custom_tc_command() -> None:
    commands = build_netem_commands(
        interface="veth-egress",
        profile=NetemProfile(name="loss", loss_percent=2.0),
        tc="/usr/sbin/tc",
    )

    assert commands[0].args[0] == "/usr/sbin/tc"
    assert commands[1].args[0] == "/usr/sbin/tc"


def test_apply_netem_profile_ignores_cleanup_failure_but_fails_apply_failure() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> CommandResult:
        calls.append(args)
        return CommandResult(returncode=1, stderr="cannot add qdisc")

    with pytest.raises(RuntimeError, match="tc netem command failed"):
        apply_netem_profile(
            interface="veth-egress",
            profile=NetemProfile(name="loss", loss_percent=2.0),
            runner=runner,
        )

    assert len(calls) == 2
    assert calls[0][:3] == ("tc", "qdisc", "delete")
    assert calls[1][:3] == ("tc", "qdisc", "add")


def test_apply_netem_profile_returns_command_results() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> CommandResult:
        calls.append(args)
        return CommandResult(returncode=0)

    results = apply_netem_profile(
        interface="veth-egress",
        profile=NetemProfile(name="loss", loss_percent=2.0),
        runner=runner,
    )

    assert len(results) == 2
    assert len(calls) == 2
    assert calls[0][0] == "tc"


def test_apply_netem_profile_uses_custom_tc_command() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> CommandResult:
        calls.append(args)
        return CommandResult(returncode=0)

    apply_netem_profile(
        interface="veth-egress",
        profile=NetemProfile(name="loss", loss_percent=2.0),
        tc="/usr/sbin/tc",
        runner=runner,
    )

    assert calls[0][0] == "/usr/sbin/tc"
    assert calls[1][0] == "/usr/sbin/tc"


def test_remove_netem_profile_requires_interface() -> None:
    with pytest.raises(ValueError, match="interface is required"):
        remove_netem_profile(interface="", runner=lambda _args: CommandResult(returncode=0))


def test_remove_netem_profile_uses_custom_tc_command() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> CommandResult:
        calls.append(args)
        return CommandResult(returncode=0)

    remove_netem_profile(interface="veth-egress", tc="/usr/sbin/tc", runner=runner)

    assert calls == [("/usr/sbin/tc", "qdisc", "delete", "dev", "veth-egress", "root")]
