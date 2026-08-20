# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure (any-OS) tests for the CC-WS5-007 identity-verifying control client
(``civiccast.native.supervisor.control_client``).

The pipe SERVER already verifies the CLIENT (``ImpersonateNamedPipeClient`` +
authz). This is the REVERSE, anti-squat direction: before it sends an admin
command, the CLIENT must verify the SERVER's pipe owner is SYSTEM or
BUILTIN\\Administrators -- so an unprivileged process that squatted the pipe
name can never receive an admin command (or trick an operator into "stopping"
the real supervisor through a fake). The owner read and the wire transport are
injected seams, so the accept-trusted / refuse-squatted decision is a
falsifiable property here with no Win32, no real pipe; the real named-pipe
round trip + a real server owner SID is VM-bound (disclosed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from civiccast.native.supervisor.config import CONTROL_PIPE_NAME
from civiccast.native.supervisor.control_client import (
    ControlClient,
    ControlServerUntrustedError,
    build_control_client,
    is_trusted_owner,
)

# Well-known owner SIDs.
_SYSTEM = "S-1-5-18"
_ADMINISTRATORS = "S-1-5-32-544"
_UNPRIVILEGED_USER = "S-1-5-21-1111111111-2222222222-3333333333-1001"


@dataclass
class FakeTransport:
    """Records every request frame it is asked to send and returns a canned
    response. A squatted-server test asserts it is NEVER called."""

    response: dict[str, Any]
    sent: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(request)
        return self.response


def _client(owner_sid: str | None, *, transport: FakeTransport | None = None) -> ControlClient:
    transport = transport or FakeTransport(response={"v": 1, "result": "ok"})
    return ControlClient(
        owner_sid_reader=lambda: owner_sid,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# is_trusted_owner: SYSTEM / Administrators only
# ---------------------------------------------------------------------------


def test_is_trusted_owner_accepts_system_and_administrators() -> None:
    assert is_trusted_owner(_SYSTEM) is True
    assert is_trusted_owner(_ADMINISTRATORS) is True


def test_is_trusted_owner_rejects_an_unprivileged_owner() -> None:
    assert is_trusted_owner(_UNPRIVILEGED_USER) is False


def test_is_trusted_owner_rejects_a_missing_owner() -> None:
    """A pipe whose owner could not be read (no server, or query denied) is NOT
    trusted -- fail-closed, so an unreadable owner is never treated as SYSTEM."""

    assert is_trusted_owner(None) is False


# ---------------------------------------------------------------------------
# verify_server_identity
# ---------------------------------------------------------------------------


def test_verify_server_identity_trusts_a_system_owned_pipe() -> None:
    verdict = _client(_SYSTEM).verify_server_identity()

    assert verdict.trusted is True
    assert verdict.owner_sid == _SYSTEM


def test_verify_server_identity_distrusts_a_squatted_pipe() -> None:
    verdict = _client(_UNPRIVILEGED_USER).verify_server_identity()

    assert verdict.trusted is False
    assert verdict.owner_sid == _UNPRIVILEGED_USER


# ---------------------------------------------------------------------------
# Anti-squat: an admin command NEVER reaches an untrusted server
# ---------------------------------------------------------------------------


def test_admin_command_is_sent_to_a_trusted_server() -> None:
    transport = FakeTransport(response={"v": 1, "cmd": "stop", "result": "ok"})
    client = _client(_SYSTEM, transport=transport)

    response = client.stop()

    assert response == {"v": 1, "cmd": "stop", "result": "ok"}
    assert len(transport.sent) == 1
    assert transport.sent[0]["cmd"] == "stop"
    assert transport.sent[0]["v"] == 1


def test_admin_command_is_refused_against_a_squatted_server_and_never_sent() -> None:
    """FALSIFICATION of the anti-squat guarantee: a ``stop`` aimed at a pipe
    owned by an unprivileged (squatting) process must RAISE and the command must
    NEVER be written to the transport -- the squatter learns nothing and receives
    no admin verb."""

    transport = FakeTransport(response={"v": 1, "result": "ok"})
    client = _client(_UNPRIVILEGED_USER, transport=transport)

    with pytest.raises(ControlServerUntrustedError):
        client.stop()

    assert transport.sent == []  # the command never left the client


def test_admin_command_is_refused_when_the_owner_is_unreadable() -> None:
    """No server / an unreadable owner is fail-closed: the admin command is
    refused and never sent (an absent owner is not a trusted owner)."""

    transport = FakeTransport(response={"v": 1, "result": "ok"})
    client = _client(None, transport=transport)

    with pytest.raises(ControlServerUntrustedError):
        client.runtime_set("wsl")

    assert transport.sent == []


# ---------------------------------------------------------------------------
# Typed verbs build the right envelopes (all verified before send)
# ---------------------------------------------------------------------------


def test_typed_verbs_build_the_expected_frames() -> None:
    transport = FakeTransport(response={"v": 1, "result": "ok"})
    client = _client(_ADMINISTRATORS, transport=transport)

    client.status()
    client.version()
    client.start()
    client.stop()
    client.restart()
    client.drain()
    client.runtime_set("native")

    cmds = [frame["cmd"] for frame in transport.sent]
    assert cmds == ["status", "version", "start", "stop", "restart", "drain", "runtime_set"]
    # runtime_set carries the target runtime the admin router validates.
    assert transport.sent[-1]["runtime"] == "native"
    # Every frame is the v1 envelope.
    assert all(frame["v"] == 1 for frame in transport.sent)


def test_read_verbs_are_also_identity_gated() -> None:
    """Even a read verb (status) is refused against a squatted server -- an
    operator must never read state from, or be phished by, a fake supervisor."""

    transport = FakeTransport(response={"v": 1, "result": "ok"})
    client = _client(_UNPRIVILEGED_USER, transport=transport)

    with pytest.raises(ControlServerUntrustedError):
        client.status()

    assert transport.sent == []


# ---------------------------------------------------------------------------
# CC-WS5-007-TOCTOU: verify the owner + send on the SAME live handle
# ---------------------------------------------------------------------------


@dataclass
class FakeConnection:
    """A single opened control-pipe connection. Records every call tagged with
    the ``opened_id`` of the connection it ran on, so a test can prove the owner
    check and the send both ran on ONE connection (the TOCTOU-safe property)."""

    owner: str | None
    opened_id: int
    calls: list[tuple[Any, ...]]

    def owner_sid(self) -> str | None:
        self.calls.append(("owner_sid", self.opened_id))
        return self.owner

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("send", self.opened_id, request))
        return {"v": 1, "result": "ok"}

    def close(self) -> None:
        self.calls.append(("close", self.opened_id))


@dataclass
class FakeConnectionFactory:
    """Opens a fresh :class:`FakeConnection` per call and counts the opens, so a
    test can assert a command opens the pipe EXACTLY ONCE (verify + send share
    that one live handle -- no verify-on-one/send-on-another TOCTOU window)."""

    owner: str | None
    opens: int = 0
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def __call__(self) -> FakeConnection:
        self.opens += 1
        return FakeConnection(owner=self.owner, opened_id=self.opens, calls=self.calls)


def test_single_handle_client_verifies_and_sends_on_one_connection() -> None:
    """CC-WS5-007-TOCTOU: the production single-handle path opens the pipe ONCE,
    reads the owner from THAT live handle, and -- only if trusted -- sends on the
    SAME handle. Proven by a fake connection that tags every call with its open
    id: exactly one open, and the owner read + the send both ran on it."""

    factory = FakeConnectionFactory(owner=_SYSTEM)
    client = ControlClient(connection_factory=factory)

    response = client.stop()

    assert response == {"v": 1, "result": "ok"}
    assert factory.opens == 1  # the whole command used ONE open handle
    assert factory.calls == [
        ("owner_sid", 1),
        ("send", 1, {"v": 1, "cmd": "stop"}),
        ("close", 1),
    ]


def test_single_handle_client_refuses_a_squat_on_the_same_handle_without_sending() -> None:
    """FALSIFICATION of the TOCTOU fix: a squatted server (untrusted owner read on
    the live handle) is refused and NOTHING is sent -- and there is no second open
    for a squatter to slip into between the check and the send (one handle only)."""

    factory = FakeConnectionFactory(owner=_UNPRIVILEGED_USER)
    client = ControlClient(connection_factory=factory)

    with pytest.raises(ControlServerUntrustedError):
        client.stop()

    assert factory.opens == 1  # opened once, checked on it, never re-opened
    assert ("owner_sid", 1) in factory.calls
    assert not any(call[0] == "send" for call in factory.calls)  # never sent
    assert ("close", 1) in factory.calls  # the one handle was still closed


def test_single_handle_client_fail_closes_when_the_pipe_cannot_be_opened() -> None:
    """A pipe that cannot be opened at all (no server) is fail-closed: the command
    is refused and never sent (an unopenable/unreadable owner is not trusted)."""

    def factory() -> FakeConnection:
        return FakeConnection(owner=None, opened_id=1, calls=[])

    client = ControlClient(connection_factory=factory)

    with pytest.raises(ControlServerUntrustedError):
        client.runtime_set("wsl")


# ---------------------------------------------------------------------------
# build_control_client: production wiring touches no Win32 at construction
# ---------------------------------------------------------------------------


def test_build_control_client_targets_the_d7_pipe_without_touching_win32() -> None:
    client = build_control_client()

    assert isinstance(client, ControlClient)
    assert client._name == CONTROL_PIPE_NAME
