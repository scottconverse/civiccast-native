# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""One-shot proof preparation; actual executing capture still occurs naturally."""

import json
import logging
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from civiccast.captions import diagnostic_identity as identity


class Owner:
    def transcribe(self):
        return 1

    def _transcribe_source(self):
        return 2

    def _measured_segments(self):
        return 3


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(identity, "_SEEN", set())
    monkeypatch.setattr(identity, "_THREADS", {})
    monkeypatch.setattr(identity, "_FAILED", set())
    monkeypatch.setattr(identity, "_SLOTS", {}, raising=False)
    monkeypatch.setattr(identity, "_CLOSED", False, raising=False)
    monkeypatch.setattr(identity, "_PROOF_ENABLED", True)
    yield
    getattr(identity, "close_executable_proof", lambda: None)()
    for worker in identity._THREADS.values():
        if worker.ident is not None:
            worker.join(2)
            assert not worker.is_alive()


def prepare():
    # Missing preparation is replayed as existing lazy behavior for sensitive RED.
    getattr(identity, "prepare_executable_proof", lambda: None)()


def receipts(caplog):
    return [
        json.loads(r.getMessage().split(" ", 4)[4])
        for r in caplog.records
        if r.getMessage().startswith("Caption diagnostic executable receipt ")
    ]


def test_startup_delay_is_not_repeated_in_natural_capture(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    clock = [1.0]
    starts = []

    class DelayedStart(threading.Thread):
        def start(self):
            starts.append(self.name)
            super().start()
            clock[0] += 0.125

    monkeypatch.setattr(identity, "_caller_clock", lambda: clock[0])
    monkeypatch.setattr(
        identity, "threading", SimpleNamespace(Thread=DelayedStart, Event=threading.Event)
    )
    prepare()
    before = len(starts)
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity._THREADS["runtime"].join(2)
    result = receipts(caplog)[0]
    assert result["caller_capture_dispatch_elapsed_s"] == 0.0, (
        "natural dispatch repeated delayed startup"
    )
    assert len(starts) == before == 3
    assert result["executing_matches_selected"] is True


def test_real_handoff_completion_is_still_measured(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    clock = [1.0]
    monkeypatch.setattr(identity, "_caller_clock", lambda: clock[0])
    prepare()
    slot = identity._SLOTS["runtime"]
    original = slot.ready.set

    def delayed_set():
        original()
        clock[0] += 0.125

    monkeypatch.setattr(slot.ready, "set", delayed_set)
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity._THREADS["runtime"].join(2)
    assert receipts(caplog)[0]["caller_capture_dispatch_elapsed_s"] == 0.125


def test_prepared_duplicates_are_one_actual_snapshot_and_no_owner_retention(caplog):
    caplog.set_level(logging.INFO)
    prepare()
    owner = Owner()
    ref = weakref.ref(owner)
    with ThreadPoolExecutor(max_workers=8) as callers:
        list(
            callers.map(
                lambda _, selected_owner=owner: identity.note_executing(
                    "runtime", Owner.transcribe.__code__, selected_owner
                ),
                range(32),
            )
        )
    identity._THREADS["runtime"].join(2)
    assert len(receipts(caplog)) == 1
    assert {"runtime"} == identity._SEEN
    assert len(identity._THREADS) == 3
    del owner
    assert ref() is None


def test_close_wakes_unused_workers_and_refuses_new_capture(caplog):
    caplog.set_level(logging.INFO)
    prepare()
    identity.close_executable_proof()
    for worker in identity._THREADS.values():
        worker.join(2)
        assert not worker.is_alive()
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    prepare()
    assert len(identity._THREADS) == 3
    assert not identity._SEEN
    assert receipts(caplog) == []


def test_expired_unused_slots_never_spawn_replacements(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(identity, "_UNUSED_WAIT_SECONDS", 0.01, raising=False)
    prepare()
    for worker in identity._THREADS.values():
        worker.join(2)
    original = tuple(identity._THREADS.values())
    for _ in range(8):
        identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    prepare()
    assert tuple(identity._THREADS.values()) == original
    assert "runtime" in identity._FAILED
    assert receipts(caplog) == []


def test_disabled_preparation_has_no_startup_work(monkeypatch):
    monkeypatch.setattr(identity, "_PROOF_ENABLED", False)
    prepare()
    assert not identity._THREADS and not identity._SLOTS and not identity._SEEN


def test_failed_thread_construction_is_not_retried(monkeypatch):
    attempts = []

    def broken(**kwargs):
        attempts.append(kwargs["name"])
        raise RuntimeError("startup seam")

    monkeypatch.setattr(
        identity, "threading", SimpleNamespace(Thread=broken, Event=threading.Event)
    )
    prepare()
    prepare()
    assert len(attempts) == 3
    assert set(identity._ANCHORS) == identity._FAILED


def test_native_startup_hook_prepares_proof_before_model(monkeypatch):
    from civiccast.app import _prewarm_native_live_caption_runtime

    events = []
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    monkeypatch.setattr(identity, "prepare_executable_proof", lambda: events.append("proof"))
    runtime = SimpleNamespace(prepare=lambda: events.append("model"))
    app = SimpleNamespace(
        state=SimpleNamespace(caption_tap_worker=SimpleNamespace(_runtime=runtime))
    )
    _prewarm_native_live_caption_runtime(app)
    assert events == ["proof", "model"]


def test_lifespan_closes_unused_proof_without_join(monkeypatch):
    import asyncio

    from civiccast.app import _app_lifespan

    events = []
    owner = SimpleNamespace(
        start=lambda: events.append("owner-start"), close=lambda: events.append("owner")
    )
    app = SimpleNamespace(state=SimpleNamespace(health_schema_owner=owner))
    monkeypatch.setattr(identity, "close_executable_proof", lambda: events.append("proof-close"))

    async def run():
        async with _app_lifespan(app):
            events.append("running")

    asyncio.run(run())
    assert events == ["owner-start", "running", "owner", "proof-close"]


def test_prepared_capture_cannot_be_relabelled_by_later_class_mutation(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    entered, release = threading.Event(), threading.Event()
    original = identity.fingerprint_code

    def held(code):
        entered.set()
        assert release.wait(2)
        return original(code)

    monkeypatch.setattr(identity, "fingerprint_code", held)
    prepare()
    actual = Owner.transcribe.__code__
    identity.note_executing("runtime", actual, Owner())
    assert entered.wait(2)
    monkeypatch.setattr(Owner, "transcribe", lambda self: "later replacement")
    release.set()
    identity._THREADS["runtime"].join(2)
    receipt = receipts(caplog)[0]
    assert receipt["executing"]["sha256"] == original(actual)
    assert receipt["selected"][0]["sha256"] == original(actual)
    assert receipt["executing_matches_selected"] is True


def test_stuck_callback_close_and_overload_never_create_more_than_three(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def stuck(*args):
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(identity, "_emit_captured", stuck)
    prepare()
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    assert entered.wait(2)
    workers = tuple(identity._THREADS.values())
    for _ in range(32):
        prepare()
        identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity.close_executable_proof()
    assert identity._THREADS["runtime"].is_alive(), "close must not join callback"
    assert tuple(identity._THREADS.values()) == workers
    assert len(workers) == 3
    release.set()


def test_natural_capture_lock_contention_does_not_reserve_or_wait():
    prepare()
    assert identity._LOCK.acquire(blocking=False)
    try:
        identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
        assert not identity._SEEN
    finally:
        identity._LOCK.release()


@pytest.mark.parametrize("wait_result", [True, False])
def test_unused_wait_signal_timeout_boundary_is_fail_closed(monkeypatch, wait_result):
    emitted, timeouts = [], []

    class BoundaryEvent:
        def wait(self, timeout):
            timeouts.append(timeout)
            return wait_result

    captured = identity._Captured(
        "runtime", Owner.transcribe.__code__, (), False, 1, "fixed", "cpython-test", (3, 12, 0), 0
    )
    slot = identity._ProofSlot(BoundaryEvent(), threading.Event(), [0.0], captured)
    monkeypatch.setattr(identity, "_emit_captured", lambda *args: emitted.append(args[0]))
    identity._wait_for_capture("runtime", slot)
    assert timeouts == [1800]
    assert identity._UNUSED_WAIT_SECONDS >= 600
    assert emitted == ([captured] if wait_result else [])
    assert ("runtime" in identity._FAILED) is (not wait_result)
    assert slot.snapshot is None
