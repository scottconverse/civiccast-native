# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared test bootstrap for deterministic staff-route authentication."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest


def pytest_configure() -> None:
    """Enable the documented deterministic staff token for local tests."""

    os.environ.setdefault("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    os.environ.setdefault("CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS", "1")
    os.environ.setdefault("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")


@pytest.fixture(autouse=True)
def _clear_external_database_probe_cache() -> None:
    """Keep the durable-storage probe memo from leaking across tests.

    ``civiccast.installer.storage`` memoizes its external-``DATABASE_URL``
    connectivity + schema-currency probe for a few seconds so a GUI polling
    ``/installer/summary`` cannot pile up abandoned connect threads. That memo
    is process-global and keyed only on the URL, so without this a test that
    injects one database outcome could be answered by a neighbouring test's
    cached result for the same URL.
    """

    from civiccast.installer.storage import reset_external_database_probe_cache

    reset_external_database_probe_cache()


@pytest.fixture(autouse=True)
def _restore_os_environ_after_every_test() -> Iterator[None]:
    """Restore the whole process environment after every test.

    Verified cross-suite pollution: ``civiccast.native.supervisor.
    service_env.ensure_database_url_env`` writes ``os.environ["DATABASE_URL"]``
    directly -- by design, so the production service can bridge the
    installer-persisted registry value into its process env (see
    ``service_env.py``'s module docstring). Tests that exercise it first call
    ``monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)`` to start from
    a clean slate, but pytest's own ``MonkeyPatch.delitem``/``delenv`` is a
    documented no-op -- it records NO undo entry -- when the key is already
    absent. The first time a whole pytest process runs one of those tests,
    ``DATABASE_URL`` is unset, so the guarding ``delenv`` registers nothing to
    undo, and the raw write that follows (bypassing monkeypatch entirely) is
    never reverted: the value survives every later test in the same process.

    ``tests/native`` and ``tests/installer`` running together is exactly the
    case that exposes this. ``tests/native/test_service_env.py`` leaves
    ``DATABASE_URL=postgresql://from-registry/db`` (its fixture value) set for
    the rest of the session; every later installer test that calls
    ``civiccast.app.create_app()`` then picks up that ambient URL and tries to
    actually connect, breaking dozens of unrelated installer tests (auth,
    durable storage, ...). Each suite run alone never notices, because
    ``tests/installer`` alone never runs after the leaking native test.

    Rather than special-case ``DATABASE_URL``, this is a general backstop: it
    snapshots ``os.environ`` before each test and restores it byte-for-byte
    after, so ANY direct environment write left unrestored by test code (or
    by production code under test) cannot outlive the test that caused it.
    ``PYTEST_CURRENT_TEST`` is left alone -- pytest's own runner maintains it
    across the very setup/call/teardown phases this fixture wraps, and
    touching it here would race pytest's own bookkeeping for no benefit.
    """

    before = dict(os.environ)
    try:
        yield
    finally:
        after = dict(os.environ)
        if after != before:
            for key in after.keys() - before.keys():
                if key != "PYTEST_CURRENT_TEST":
                    del os.environ[key]
            for key, value in before.items():
                if os.environ.get(key) != value:
                    os.environ[key] = value


def _installed_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the loop installed for this thread WITHOUT constructing one.

    ``asyncio.get_event_loop()`` creates a loop when none is set, which is the
    opposite of what this needs.
    """

    policy = asyncio.get_event_loop_policy()
    local = getattr(policy, "_local", None)
    loop = getattr(local, "_loop", None)
    return loop if isinstance(loop, asyncio.AbstractEventLoop) else None


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown() -> None:
    """Close the event loop pytest-asyncio abandons, so it cannot leak.

    pytest-asyncio 1.3.0 can leave a function-scoped loop installed in the
    thread's policy slot without closing it. Nothing then references that loop
    except the slot itself, so the next ``asyncio.run()`` -- which ends by
    calling ``set_event_loop(None)`` -- drops the last reference. The garbage
    collector finalizes the loop while it is still open, and Python reports
    "unclosed event loop" plus BOTH halves of the loop's socketpair self-pipe
    (on Windows a ProactorEventLoop self-pipe is a real AF_INET loopback pair)
    as *unraisable* ResourceWarnings. ``filterwarnings = ["error", ...]``
    escalates those onto whichever unrelated test the collection interrupted,
    which is why the randomized-order lane failed on a different innocent test
    every run.

    Every async test here is function-scoped (see ``asyncio_default_*_loop_scope``
    in pyproject.toml and the absence of any ``loop_scope`` marker), so a loop
    still installed at teardown is finished with. A running loop is never
    touched: several background workers (``civiccast.platform.worker_runtime``
    and its consumers) park one on a daemon thread deliberately.
    """

    loop = _installed_event_loop()
    if loop is None or loop.is_running() or loop.is_closed():
        return
    loop.close()
    asyncio.set_event_loop(None)
