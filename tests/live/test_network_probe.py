# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the real network-reachability probe (bug B3).

``civiccast.live.network_probe.probe_network_reachable`` is the
``NetworkProbe`` implementation wired into every real station's
``PreflightEvaluator`` (``civiccast/app.py``'s
``_resolve_preflight_evaluator``). Before this module existed, the
"Network reachable" pre-flight check depended entirely on a caller
supplying ``network_reachable`` -- no real caller ever did, so the check
reported ``network.not_probed`` forever (field evidence, native beta
candidate #17).

These tests mock the socket boundary (no real network access required)
and assert:

* the first target that answers wins, and later targets are never tried.
* every target refusing the connection -> ``(False, message)`` naming
  what was tried, not a bare "unreachable."
* ``build_network_probe`` reads
  ``CIVICCAST_NETWORK_PROBE_TIMEOUT_SECONDS``, falls back to the
  documented default on an unset/invalid value, and an explicit
  ``timeout_seconds`` argument wins over the env var.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from civiccast.live.network_probe import (
    _PROBE_TARGETS,
    DEFAULT_NETWORK_PROBE_TIMEOUT_SECONDS,
    build_network_probe,
    probe_network_reachable,
)


class _FakeSocket:
    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None


def test_first_reachable_target_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted: list[tuple[str, int]] = []

    def _fake_create_connection(address: tuple[str, int], timeout: float) -> _FakeSocket:
        attempted.append(address)
        return _FakeSocket()

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    reachable, message = probe_network_reachable(timeout_seconds=1.0)
    assert reachable is True
    assert message is not None and _PROBE_TARGETS[0][0] in message
    # Only the first target was tried; a working target short-circuits the rest.
    assert attempted == [_PROBE_TARGETS[0]]


def test_second_target_tried_after_first_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted: list[tuple[str, int]] = []

    def _fake_create_connection(address: tuple[str, int], timeout: float) -> _FakeSocket:
        attempted.append(address)
        if address == _PROBE_TARGETS[0]:
            raise OSError("connection refused")
        return _FakeSocket()

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    reachable, _message = probe_network_reachable(timeout_seconds=1.0)
    assert reachable is True
    assert attempted == list(_PROBE_TARGETS[:2])


def test_all_targets_unreachable_fails_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _always_fails(address: tuple[str, int], timeout: float) -> _FakeSocket:
        raise OSError("network is unreachable")

    monkeypatch.setattr(socket, "create_connection", _always_fails)
    reachable, message = probe_network_reachable(timeout_seconds=1.0)
    assert reachable is False
    assert message is not None
    for host, port in _PROBE_TARGETS:
        assert f"{host}:{port}" in message
    assert "network" in message.lower()


def test_build_network_probe_uses_explicit_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICCAST_NETWORK_PROBE_TIMEOUT_SECONDS", raising=False)
    seen_timeouts: list[float] = []

    def _fake_create_connection(address: tuple[str, int], timeout: float) -> _FakeSocket:
        seen_timeouts.append(timeout)
        return _FakeSocket()

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    probe = build_network_probe(timeout_seconds=9.5)
    probe()
    assert seen_timeouts == [9.5]


def test_build_network_probe_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_NETWORK_PROBE_TIMEOUT_SECONDS", "2.5")
    seen_timeouts: list[float] = []

    def _fake_create_connection(address: tuple[str, int], timeout: float) -> _FakeSocket:
        seen_timeouts.append(timeout)
        return _FakeSocket()

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    probe = build_network_probe()
    probe()
    assert seen_timeouts == [2.5]


def test_build_network_probe_falls_back_on_invalid_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_NETWORK_PROBE_TIMEOUT_SECONDS", "not-a-number")
    seen_timeouts: list[float] = []

    def _fake_create_connection(address: tuple[str, int], timeout: float) -> _FakeSocket:
        seen_timeouts.append(timeout)
        return _FakeSocket()

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)
    probe = build_network_probe()
    probe()
    assert seen_timeouts == [DEFAULT_NETWORK_PROBE_TIMEOUT_SECONDS]
