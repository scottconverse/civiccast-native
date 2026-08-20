# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S9-1 reliability primitives: UniformPacingLatch + the shared TOCTOU-safe
process-kill primitive (Windows; psutil mocked)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import psutil

from civiccast.egress import process_identity, schema_currency
from civiccast.egress import store as store_module
from civiccast.egress.models import EgressProofEvent
from civiccast.egress.pacing import UniformPacingLatch
from civiccast.egress.store import InMemoryEgressStore

# --- UniformPacingLatch -------------------------------------------------------------


def test_latch_first_run_allowed_then_cools_down() -> None:
    clock = {"t": 100.0}
    latch = UniformPacingLatch(30.0, clock=lambda: clock["t"])
    assert latch.should_run_now("a") is True  # first run allowed
    assert latch.should_run_now("a") is False  # within cooldown
    clock["t"] = 129.9
    assert latch.should_run_now("a") is False
    clock["t"] = 130.0
    assert latch.should_run_now("a") is True  # cooldown elapsed


def test_latch_keys_are_independent() -> None:
    clock = {"t": 0.0}
    latch = UniformPacingLatch(10.0, clock=lambda: clock["t"])
    assert latch.should_run_now("a") is True
    assert latch.should_run_now("b") is True  # a different key is not blocked by a's latch


def test_latch_force_reset_allows_immediate_rerun() -> None:
    clock = {"t": 0.0}
    latch = UniformPacingLatch(10.0, clock=lambda: clock["t"])
    assert latch.should_run_now("a") is True
    assert latch.should_run_now("a") is False
    latch.force_reset("a")
    assert latch.should_run_now("a") is True


def test_latch_per_call_cooldown_override() -> None:
    clock = {"t": 0.0}
    latch = UniformPacingLatch(10.0, clock=lambda: clock["t"])
    assert latch.should_run_now("a", cooldown=5.0) is True
    clock["t"] = 6.0
    assert latch.should_run_now("a") is True  # the 5s override (not 10s) has elapsed


def test_latch_next_allowed_at_introspection() -> None:
    latch = UniformPacingLatch(10.0, clock=lambda: 100.0)
    assert latch.next_allowed_at("a") == 0.0
    latch.should_run_now("a")
    assert latch.next_allowed_at("a") == 110.0


# --- fake psutil process (fixture for the TOCTOU-kill tests below) ------------------


class _FakeProc:
    def __init__(
        self, *, create_time=1000.0, name="casparcg", terminate_raises=None, wait_raises=None
    ):
        self._ct = create_time
        self._name = name
        self._terminate_raises = terminate_raises
        self._wait_raises = wait_raises
        self.terminated = False
        self.killed = False

    def create_time(self):
        return self._ct

    def name(self):
        return self._name

    def terminate(self):
        if self._terminate_raises:
            raise self._terminate_raises
        self.terminated = True

    def wait(self, timeout=None):
        if self._wait_raises:
            raise self._wait_raises

    def kill(self):
        self.killed = True


# --- verify_and_kill_process (the shared TOCTOU primitive) --------------------------


def test_kill_when_create_time_matches(monkeypatch) -> None:
    proc = _FakeProc(create_time=1000.0)
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    assert process_identity.verify_and_kill_process(111, 1000.0) is True
    assert proc.terminated is True


def test_skip_recycled_pid(monkeypatch) -> None:
    proc = _FakeProc(create_time=2000.0)  # differs from recorded 1000.0 by > 1s
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    assert process_identity.verify_and_kill_process(111, 1000.0) is False
    assert proc.terminated is False


def test_kill_missing_process_returns_false(monkeypatch) -> None:
    def _raise(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", _raise)
    assert process_identity.verify_and_kill_process(111, 1000.0) is False


def test_kill_timeout_escalates_to_force_kill(monkeypatch) -> None:
    proc = _FakeProc(create_time=1000.0, wait_raises=psutil.TimeoutExpired(10))
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    assert process_identity.verify_and_kill_process(111, 1000.0) is True
    assert proc.killed is True


def test_kill_access_denied_returns_false_and_warns(monkeypatch, caplog) -> None:
    proc = _FakeProc(create_time=1000.0, terminate_raises=psutil.AccessDenied(111))
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    with caplog.at_level(logging.WARNING):
        assert process_identity.verify_and_kill_process(111, 1000.0) is False
    assert "Access denied" in caplog.text


# --- schema currency ----------------------------------------------------------------


def test_schema_currency() -> None:
    assert schema_currency.current_schema_version() == schema_currency.EGRESS_SCHEMA_VERSION

    class _Current:
        schema_version = schema_currency.EGRESS_SCHEMA_VERSION

    class _Stale:
        schema_version = schema_currency.EGRESS_SCHEMA_VERSION - 1

    assert schema_currency.is_schema_current(_Current()) is True
    assert schema_currency.is_schema_current(_Stale()) is False


# --- proof-event churn cap (S9 §6.5) ------------------------------------------------

_BASE = datetime(2026, 6, 14, tzinfo=UTC)


def _proof(channel: str, n: int) -> EgressProofEvent:
    return EgressProofEvent(
        event_id=f"{channel}-{n:06d}",
        observed_at=_BASE + timedelta(seconds=n),  # increasing → deterministic oldest
        channel_id=channel,
        state="ON_AIR",
        source_label="src",
        source_path="/m/x.ts",
        proof_boundary="boundary",
        machine_summary="summary",
    )


def test_proof_event_trim_per_channel(monkeypatch) -> None:
    # small thresholds keep the test fast while exercising the real trim logic
    monkeypatch.setattr(store_module, "MAX_PROOF_EVENTS_PER_CHANNEL", 50)
    monkeypatch.setattr(store_module, "TRIM_BATCH_SIZE", 10)
    store = InMemoryEgressStore()
    for n in range(60):
        store.append_proof_event(_proof("A", n))
    for n in range(5):
        store.append_proof_event(_proof("B", n))

    a = store.recent_proof_events("A", 1000)
    b = store.recent_proof_events("B", 1000)
    assert len(a) == 50  # 60 appended → over 50 → oldest 10 trimmed
    assert len(b) == 5  # a different channel is untouched
    a_ids = {e.event_id for e in a}
    assert "A-000000" not in a_ids and "A-000009" not in a_ids  # the 10 oldest dropped
    assert "A-000010" in a_ids and "A-000059" in a_ids  # the rest kept


def test_proof_event_trim_no_op_under_cap() -> None:
    store = InMemoryEgressStore()
    for n in range(20):
        store.append_proof_event(_proof("A", n))
    assert len(store.recent_proof_events("A", 1000)) == 20  # well under 10k cap, no trim
