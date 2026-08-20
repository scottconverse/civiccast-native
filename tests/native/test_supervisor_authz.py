# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the pure D7 two-tier control-pipe authorization decision.

Pins AC-N1 (the exact hole SDR-002 named: an unprivileged INTERACTIVE token can
read status but is denied stop) plus the full tier matrix and the fail-closed
paths. No token, no pipe, no impersonation -- the decision is pure.
"""

from __future__ import annotations

import pytest

from civiccast.native.supervisor.authz import _all_commands, authorize

ALL_COMMANDS = _all_commands()
READ_COMMANDS = ("status", "version")
ADMIN_COMMANDS = ("start", "stop", "restart", "drain", "runtime_set")

# Representative caller token group sets.
INTERACTIVE_NONADMIN = frozenset({"authenticated_users", "interactive"})
ADMIN = frozenset({"authenticated_users", "administrators"})
SYSTEM = frozenset({"authenticated_users", "system"})
NO_GROUPS: frozenset[str] = frozenset()


# --------------------------------------------------------------------------
# AC-N1 -- the named hole
# --------------------------------------------------------------------------


def test_ac_n1_unprivileged_interactive_reads_status_but_is_denied_stop() -> None:
    status = authorize("status", INTERACTIVE_NONADMIN)
    assert status.allowed is True
    assert status.is_mutating is False

    stop = authorize("stop", INTERACTIVE_NONADMIN)
    assert stop.allowed is False
    assert stop.is_mutating is True
    assert stop.required_tier == "admin"
    assert stop.caller_tier == "status"


# --------------------------------------------------------------------------
# Tier matrix
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_admin_commands_need_admin_or_system(command: str) -> None:
    assert authorize(command, ADMIN).allowed is True
    assert authorize(command, SYSTEM).allowed is True
    assert authorize(command, INTERACTIVE_NONADMIN).allowed is False
    assert authorize(command, NO_GROUPS).allowed is False


@pytest.mark.parametrize("command", READ_COMMANDS)
def test_read_commands_allowed_for_any_authenticated_caller(command: str) -> None:
    assert authorize(command, INTERACTIVE_NONADMIN).allowed is True
    assert authorize(command, ADMIN).allowed is True  # admin dominates status
    assert authorize(command, SYSTEM).allowed is True
    # A caller carrying none of the known groups is denied even the read tier.
    assert authorize(command, NO_GROUPS).allowed is False


def test_admin_caller_is_admin_tier_and_can_read() -> None:
    d = authorize("status", ADMIN)
    assert d.caller_tier == "admin"
    assert d.allowed is True


# --------------------------------------------------------------------------
# Classification + fail-closed
# --------------------------------------------------------------------------


def test_is_mutating_matches_the_admin_command_set() -> None:
    for command in ALL_COMMANDS:
        expected = command in ADMIN_COMMANDS
        assert authorize(command, ADMIN).is_mutating is expected, command


def test_unknown_command_is_denied_fail_closed() -> None:
    d = authorize("shutdown_everything", ADMIN)  # not a real command
    assert d.allowed is False
    assert d.required_tier == "none"
    assert d.is_mutating is False


def test_every_known_command_is_decidable() -> None:
    for command in ALL_COMMANDS:
        d = authorize(command, ADMIN)
        assert isinstance(d.allowed, bool)
        assert d.command == command
