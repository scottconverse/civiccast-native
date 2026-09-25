# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A channel start consults a background retention verdict, never a live scan.

MEASURED LIVE 2026-09-24 17:19:23 MDT (installed station): one channel start ran
``enforce_discovered`` synchronously on the automation thread and held every
other channel for 60.5 s (the automation watchdog fires at 30 s), because
``_discover_candidates`` resolves, stats and SHA-256s a full read of every
processed chunk -- 15,045 of them for the public channel alone. The same scan
had already stalled the pass for 446 s at 13:30 under disk load.

These tests pin the contract that replaces it: the start path is bounded and
never touches discovery, a real verdict produced in the background is still
honored (including its refusal), and the background sweep cannot be fanned out
into one scan per start.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from civiccast.captions.retention import (
    RETENTION_SWEEP_SECONDS,
    RETENTION_VERDICT_FRESHNESS_SECONDS,
    CaptionEvidenceRetentionPolicy,
    CaptionRetentionResult,
    CaptionRetentionVerdictSource,
)
from civiccast.captions.review import InMemoryCaptionReviewStore

#: The brief's start-path budget. Measured discovery on the live archive is
#: 60.5 s, so anything above this cannot be the "consult a verdict" path.
_START_BUDGET_SECONDS = 0.5

#: The refresh thread's name, asserted by name so the test cannot pass on some
#: other thread happening to be alive.
_REFRESH_THREAD_NAME = "civiccast-caption-readiness-retention-timer"

#: Providers built by ``_build_source``, so every test leaves no thread behind.
_SOURCES: list[CaptionRetentionVerdictSource] = []


def _thread_names() -> set[str]:
    return {thread.name for thread in threading.enumerate()}


def _refresh_threads() -> set[threading.Thread]:
    """Live threads carrying the refresh name, by IDENTITY.

    By identity rather than by name-membership, because the claim under test is
    "the thread THIS provider armed has ended". The egress suite arms its own
    provider (``tests/egress/test_daemon.py``), so a name-membership assertion
    would be measuring whoever else is alive in the process.
    """
    return {thread for thread in threading.enumerate() if thread.name == _REFRESH_THREAD_NAME}


@pytest.fixture(autouse=True)
def _stop_every_provider_after_its_test() -> Iterator[None]:
    yield
    while _SOURCES:
        _SOURCES.pop().stop(10.0)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _Clock:
    """A monotonic clock the test drives, so freshness needs no wall-clock wait."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Discovery:
    """Stand-in for ``_discover_candidates``: counts calls, optionally blocks."""

    def __init__(self, *, block: bool = True) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.calls = 0
        #: Bounded so a test that forgets to release still finishes (and any
        #: failure is reported as a timeout, never as a hung suite).
        self.wait_seconds = 30.0

    def __call__(
        self,
        *,
        tap_root: Path | None,
        review_store: Any,
        segment_seconds: float,
    ) -> list[dict[str, object]]:
        self.calls += 1
        self.entered.set()
        self.release.wait(self.wait_seconds)
        return []


def _divergence_refusal() -> CaptionRetentionResult:
    return CaptionRetentionResult(
        ready=False,
        refusal_reason="caption-storage-volumes-diverge",
        requires_fallback_slate=True,
    )


def _build_source(
    tmp_path: Path,
    *,
    monotonic: Callable[[], float] | None = None,
    sweep_interval_seconds: float = RETENTION_SWEEP_SECONDS,
) -> tuple[CaptionRetentionVerdictSource, Path]:
    storage_root = tmp_path / "egress"
    storage_root.mkdir(parents=True, exist_ok=True)
    source = CaptionRetentionVerdictSource(
        policy=CaptionEvidenceRetentionPolicy.from_system(storage_root=storage_root),
        tap_root=None,
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=5.0,
        storage_root=storage_root,
        monotonic=monotonic or time.monotonic,
        sweep_interval_seconds=sweep_interval_seconds,
    )
    _SOURCES.append(source)
    return source, storage_root


def _status(storage_root: Path, channel_id: str) -> dict[str, object]:
    path = storage_root / channel_id / "captions" / "runtime-status.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


class TestAStartNeverWaitsForRetentionDiscovery:
    def test_a_blocked_discovery_never_holds_the_start_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, _storage_root = _build_source(tmp_path)
        discovery = _Discovery()
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)
        try:
            began = time.monotonic()
            result = source("public")
            elapsed = time.monotonic() - began
            assert elapsed < _START_BUDGET_SECONDS, (
                f"the start path waited {elapsed:.2f}s on retention discovery"
            )
            # "No verdict yet" must never become a refusal: the program starts,
            # and WAV retention stays off through the tap's own pending rule.
            assert result.ready is True
            assert result.refusal_reason is None
            assert result.requires_fallback_slate is False
            assert discovery.entered.wait(5.0), "no background sweep was dispatched"
        finally:
            discovery.release.set()
            assert source.wait_for_sweep(10.0)
        assert discovery.calls == 1

    def test_a_failed_sweep_never_refuses_a_start_and_retries_on_the_cadence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _Clock()
        source, _storage_root = _build_source(tmp_path, monotonic=clock)
        calls: list[int] = []

        def failing(**_kwargs: object) -> list[dict[str, object]]:
            calls.append(1)
            raise RuntimeError("review store unavailable")

        monkeypatch.setattr(source.policy, "_discover_candidates", failing)

        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert len(calls) == 1
        # Inside the sweep cadence: a start does not stack another scan.
        assert source("public").ready is True
        assert len(calls) == 1
        # Past it: the failed sweep is retried, and still never refuses.
        clock.advance(RETENTION_SWEEP_SECONDS + 1.0)
        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert len(calls) == 2

    def test_the_divergence_refusal_is_still_synchronous(self, tmp_path: Path) -> None:
        # The one refusal this policy still makes is a real routing hazard and
        # costs three syscalls -- it must NOT be deferred behind a live scan.
        tap_root = tmp_path / "caption-tap"
        (tap_root / "public").mkdir(parents=True)
        storage_root = tmp_path / "egress"
        storage_root.mkdir(parents=True, exist_ok=True)
        policy = CaptionEvidenceRetentionPolicy.from_system(storage_root=storage_root)
        real_device = tap_root.stat().st_dev
        policy._storage_root = _OtherVolume(real_device + 1)

        result = policy.check_storage_divergence(tap_root=tap_root)

        assert result is not None
        assert result.ready is False
        assert result.refusal_reason == "caption-storage-volumes-diverge"
        assert result.requires_fallback_slate is True

    def test_a_divergent_station_refuses_without_running_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, storage_root = _build_source(tmp_path)
        monkeypatch.setattr(
            source.policy, "check_storage_divergence", lambda **_kwargs: _divergence_refusal()
        )
        discovery = _Discovery()
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)
        try:
            began = time.monotonic()
            result = source("public")
            elapsed = time.monotonic() - began
        finally:
            discovery.release.set()
            assert source.wait_for_sweep(10.0)

        assert elapsed < _START_BUDGET_SECONDS, f"the refusal waited {elapsed:.2f}s"
        assert result.ready is False
        assert result.refusal_reason == "caption-storage-volumes-diverge"
        assert discovery.calls == 0, "the cheap check must refuse before any scan"
        status = _status(storage_root, "public")
        assert status["state"] == "storage-refused"
        assert status["refusal_reason"] == "caption-storage-volumes-diverge"


class TestTheSharedVerdict:
    def test_a_fresh_refused_verdict_still_refuses_and_publishes_the_sidecar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, storage_root = _build_source(tmp_path)
        refusal = _divergence_refusal()
        monkeypatch.setattr(source.policy, "enforce_discovered", lambda **_kwargs: refusal)

        # Start 1: no verdict yet -- the program starts and NOTHING is refused.
        assert source("public").ready is True
        assert not (storage_root / "public" / "captions" / "runtime-status.json").exists()
        assert source.wait_for_sweep(10.0)

        # Start 2: the verdict is fresh, so today's refusal behavior applies.
        result = source("public")
        assert result.ready is False
        assert result.refusal_reason == "caption-storage-volumes-diverge"
        assert result.requires_fallback_slate is True
        status = _status(storage_root, "public")
        assert status["state"] == "storage-refused"
        assert status["refusal_reason"] == "caption-storage-volumes-diverge"

    def test_a_missing_verdict_dispatches_one_sweep_not_one_per_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, _storage_root = _build_source(tmp_path)
        discovery = _Discovery()
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)
        try:
            for _ in range(3):
                assert source("public").ready is True
            # The dispatch is asynchronous by design (that IS the fix), so wait
            # for the sweep to be inside discovery rather than racing its start.
            assert discovery.entered.wait(5.0)
            assert discovery.calls == 1
            assert source._sweeps_started == 1
        finally:
            discovery.release.set()
            assert source.wait_for_sweep(10.0)

    def test_a_fresh_verdict_is_reused_and_a_stale_one_is_refreshed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _Clock()
        source, _storage_root = _build_source(tmp_path, monotonic=clock)
        discovery = _Discovery(block=False)
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)

        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert discovery.calls == 1

        # Fresh (well inside the bound): the sweep is NOT repeated.
        assert source("public").ready is True
        assert discovery.calls == 1

        # Stale: exactly one refresh, then reuse again.
        clock.advance(RETENTION_VERDICT_FRESHNESS_SECONDS + 1.0)
        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert discovery.calls == 2
        assert source("public").ready is True
        assert discovery.calls == 2


class TestTheVerdictStaysFreshWithoutAStart:
    """The provider keeps its own verdict fresh, so a start is not what re-arms it.

    As first built the provider swept only when a start found no fresh verdict.
    Channel starts are usually more than one sweep interval apart, so almost
    every start saw a stale verdict, returned "pending", and dispatched one
    scan -- which means a background REFUSAL could essentially never gate a
    start. The refresh thread arms on the first ``__call__`` and then dispatches
    on its own cadence forever.
    """

    def test_building_the_provider_starts_no_thread(self, tmp_path: Path) -> None:
        before = _thread_names()
        armed_before = _refresh_threads()

        source, _storage_root = _build_source(tmp_path)

        assert _thread_names() <= before, "building the provider must start nothing"
        source("public")
        assert len(_refresh_threads() - armed_before) == 1, "the first start arms the refresh"

    def test_a_sweep_re_runs_without_another_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, _storage_root = _build_source(tmp_path, sweep_interval_seconds=0.05)
        discovery = _Discovery(block=False)
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)

        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert discovery.calls == 1

        # No second start, no other caller: the refresh alone must dispatch it.
        assert _wait_until(lambda: discovery.calls >= 2), (
            f"the verdict was not refreshed in the background (calls={discovery.calls})"
        )

    def test_a_background_refusal_gates_the_next_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, storage_root = _build_source(tmp_path, sweep_interval_seconds=0.05)
        sweeps: list[int] = []

        def sweep(**_kwargs: object) -> CaptionRetentionResult:
            sweeps.append(1)
            if len(sweeps) == 1:
                return CaptionRetentionResult(
                    ready=True, refusal_reason=None, requires_fallback_slate=False
                )
            return _divergence_refusal()

        monkeypatch.setattr(source.policy, "enforce_discovered", sweep)

        # Start 1: nothing is known yet, so the program starts.
        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)

        # The refusal is published by the BACKGROUND sweep, with no start to
        # carry it -- this is the case the first build could not reach.
        assert _wait_until(lambda: len(sweeps) >= 2)
        assert _wait_until(lambda: source._fresh_verdict() is not None)

        result = source("public")

        assert result.ready is False
        assert result.refusal_reason == "caption-storage-volumes-diverge"
        assert result.requires_fallback_slate is True
        status = _status(storage_root, "public")
        assert status["state"] == "storage-refused"

    def test_the_refresh_never_stacks_sweeps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source, _storage_root = _build_source(tmp_path, sweep_interval_seconds=0.05)
        discovery = _Discovery()
        monkeypatch.setattr(source.policy, "_discover_candidates", discovery)
        try:
            assert source("public").ready is True
            assert discovery.entered.wait(5.0)
            # Several refresh cadences pass with a sweep still in flight.
            time.sleep(0.3)
            assert discovery.calls == 1, "a slow sweep must not be fanned out"
        finally:
            discovery.release.set()
            assert source.wait_for_sweep(10.0)

    def test_stop_ends_the_refresh_thread(self, tmp_path: Path) -> None:
        source, _storage_root = _build_source(tmp_path, sweep_interval_seconds=0.05)
        armed_before = _refresh_threads()
        assert source("public").ready is True
        assert source.wait_for_sweep(10.0)
        assert len(_refresh_threads() - armed_before) == 1, "the start armed exactly one refresh"

        assert source.stop(10.0) is True

        assert _refresh_threads() == armed_before, (
            "the refresh thread this provider armed is still alive"
        )

    def test_a_stopped_provider_does_not_re_arm(self, tmp_path: Path) -> None:
        source, _storage_root = _build_source(tmp_path, sweep_interval_seconds=0.05)
        armed_before = _refresh_threads()
        assert source("public").ready is True
        assert source.stop(10.0) is True
        assert _refresh_threads() == armed_before

        assert source("public").ready is True

        assert _refresh_threads() == armed_before, "a stopped provider must not re-arm"


class _OtherVolume:
    """A storage root on a different device, without a second real volume."""

    def __init__(self, st_dev: int) -> None:
        self._st_dev = st_dev

    def is_dir(self) -> bool:
        return True

    def stat(self) -> os.stat_result:
        # st_dev is index 2 of the POSIX stat tuple.
        return os.stat_result((0, 0, self._st_dev, 0, 0, 0, 0, 0, 0, 0))
