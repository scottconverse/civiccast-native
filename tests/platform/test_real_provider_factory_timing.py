# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression guard: real provider factories stay side-effect-free at construction.

Companion to ``tests/platform/test_real_providers.py``. That module proves each
real adapter behaves correctly once it talks to a transport; this module
proves the *factory* functions in ``civiccast.platform.providers`` -- the ones
``ProviderRegistry.resolve()`` calls for ``CIVICCAST_PROVIDER_<KIND>=real`` --
never perform network I/O while building the client. That is the property a
pre-broadcast readiness check (``describe_provider``) leans on to call
``resolve()`` from a read-only evaluator: see the docstring on
``describe_provider`` in ``civiccast/platform/providers.py``.

Every real socket connect attempt is monkeypatched to sleep past the budget
and then raise ``OSError``, simulating a dead network with a realistic
connect-timeout delay rather than an instant failure. If any factory tried to
open a connection during construction, this test would observe an elapsed
time past the 250ms budget (from the simulated delay) instead of the
near-instant local construction the current factories perform.
"""

from __future__ import annotations

import contextlib
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Warm the import cache for every module a ``_real_*`` factory lazily imports
# internally, *before* any timing starts. First-time module import (parsing,
# building dependent stdlib/httpx module graphs) is a one-off Python interpreter
# cost that has nothing to do with whether a factory blocks on network I/O --
# without this, the first test to touch a given adapter would pay that import
# tax inside its timing window and could spuriously trip the budget.
import civiccast.archive.internet_archive
import civiccast.archive.local_nas
import civiccast.subscribe.smtp
import civiccast.subscribe.webhook
import civiccast.syndicate.youtube  # noqa: F401
from civiccast.platform.providers import (
    _real_internet_archive,
    _real_local_nas,
    _real_mail,
    _real_webhook,
    _real_youtube,
)

_BUDGET_SECONDS = 0.25
_SIMULATED_DEAD_NETWORK_DELAY = 0.4


@pytest.fixture(autouse=True)
def _dead_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real TCP connect attempt sleeps past the budget, then fails.

    This never fires for the current five factories (proved by the timing
    assertions below) because none of them open a socket during construction.
    It exists so a future factory that *did* connect during ``__init__``
    would be caught by the elapsed-time assertion below rather than silently
    succeeding (or hanging indefinitely) against a real network during a test
    run.
    """

    def _fake_connect(_self: socket.socket, _address: object) -> None:
        time.sleep(_SIMULATED_DEAD_NETWORK_DELAY)
        raise OSError("simulated dead network: connection refused")

    monkeypatch.setattr(socket.socket, "connect", _fake_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _fake_connect)


def _time_factory(factory: Callable[[], Any]) -> float:
    started = time.perf_counter()
    factory()
    return time.perf_counter() - started


def _time_factory_allow_oserror(factory: Callable[[], Any]) -> float:
    started = time.perf_counter()
    with contextlib.suppress(OSError):
        factory()
    return time.perf_counter() - started


class TestRealProviderFactoryConstructionIsSideEffectFree:
    """Each ``_real_*`` factory must build its client in well under 250ms.

    ``describe_provider`` calls ``registry.resolve(kind)`` from a read-only
    pre-broadcast evaluator on the strength of exactly this property. A
    future adapter that opened a connection, made an eager HTTP request, or
    otherwise blocked inside ``__init__``/``from_env()`` would silently turn
    that evaluator into a network call -- this test fails first.
    """

    def test_internet_archive_factory_is_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_IA_ACCESS_KEY", "test-access")
        monkeypatch.setenv("CIVICCAST_IA_SECRET_KEY", "test-secret")
        elapsed = _time_factory(_real_internet_archive)
        assert elapsed < _BUDGET_SECONDS, (
            f"_real_internet_archive() took {elapsed:.3f}s; a real provider "
            "factory must never block on network I/O during construction."
        )

    def test_youtube_factory_is_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_REFRESH_TOKEN", "test-refresh-token")
        elapsed = _time_factory(_real_youtube)
        assert elapsed < _BUDGET_SECONDS, (
            f"_real_youtube() took {elapsed:.3f}s; a real provider factory "
            "must never block on network I/O during construction."
        )

    def test_mail_factory_is_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_SMTP_HOST", "relay.example")
        monkeypatch.setenv("CIVICCAST_SMTP_FROM", "alerts@station.example")
        elapsed = _time_factory(_real_mail)
        assert elapsed < _BUDGET_SECONDS, (
            f"_real_mail() took {elapsed:.3f}s; a real provider factory must "
            "never block on network I/O during construction."
        )

    def test_webhook_factory_is_fast(self) -> None:
        # WebhookSettings.from_env() needs no credentials -- per-subscription
        # secrets are supplied by the caller, not read from the environment.
        elapsed = _time_factory(_real_webhook)
        assert elapsed < _BUDGET_SECONDS, (
            f"_real_webhook() took {elapsed:.3f}s; a real provider factory "
            "must never block on network I/O during construction."
        )

    def test_local_nas_factory_is_fast(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path))
        elapsed = _time_factory(_real_local_nas)
        assert elapsed < _BUDGET_SECONDS, (
            f"_real_local_nas() took {elapsed:.3f}s; a real provider factory "
            "must never block on network I/O during construction."
        )


class TestGuardCatchesARegressedFactory:
    """Proves the guard above is not vacuous: it fails on a real violation.

    Stands in for a hypothetical future ``_real_x()`` that opens a connection
    eagerly inside its constructor, instead of deferring I/O the way every
    shipped factory above does. Without the ``_dead_network`` fixture's
    simulated delay this would just fail instantly with ``OSError`` (a
    real dead network refuses fast on loopback-style test hosts); the sleep
    stands in for the connect-timeout latency a real dead/unreachable host
    would impose, so the elapsed-time assertion has something real to catch.
    """

    def test_a_factory_that_connects_during_construction_blows_the_budget(self) -> None:
        def _regressed_factory() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(("198.51.100.1", 80))  # TEST-NET-2, always unreachable

        elapsed = _time_factory_allow_oserror(_regressed_factory)
        assert elapsed >= _SIMULATED_DEAD_NETWORK_DELAY, (
            f"expected the simulated dead-network delay ({_SIMULATED_DEAD_NETWORK_DELAY}s) "
            f"to dominate the regressed factory's construction time, got {elapsed:.3f}s -- "
            "the dead-network fixture did not intercept the connect() call."
        )
