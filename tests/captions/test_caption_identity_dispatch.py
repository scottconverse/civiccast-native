# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Sensitive proof-only receipt dispatch contracts; all blocking is test-owned."""

import importlib.util
import json
import logging
import sys
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
    monkeypatch.setattr(identity, "_THREADS", {}, raising=False)
    monkeypatch.setattr(identity, "_PROOF_ENABLED", True, raising=False)
    monkeypatch.setattr(identity, "_FAILED", set(), raising=False)
    yield
    for worker in identity._THREADS.values():
        if worker.ident is not None:
            worker.join(2)
            assert not worker.is_alive(), "test-owned receipt worker not released"


def receipts(caplog):
    return [
        json.loads(r.getMessage().split(" ", 4)[4])
        for r in caplog.records
        if r.getMessage().startswith("Caption diagnostic executable receipt ")
    ]


@pytest.mark.parametrize("boundary", ["fingerprint", "logger", "clock"])
def test_receipt_callback_block_does_not_wait_in_caller(boundary, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    entered, release, returned = (threading.Event() for _ in range(3))
    original_hash = identity.fingerprint_code
    original_log = identity._LOG.info

    def block():
        entered.set()
        assert release.wait(3), "controlled callback release deadline"

    if boundary == "fingerprint":

        def hash_code(code):
            block()
            return original_hash(code)

        monkeypatch.setattr(identity, "fingerprint_code", hash_code)
    elif boundary == "logger":

        def log(*args, **kwargs):
            block()
            return original_log(*args, **kwargs)

        monkeypatch.setattr(identity._LOG, "info", log)
    else:
        monkeypatch.setattr(
            identity, "time", SimpleNamespace(perf_counter=lambda: (block(), 1.0)[1])
        )
    owner = Owner()
    caller = threading.Thread(
        target=lambda: (
            identity.note_executing("runtime", Owner.transcribe.__code__, owner),
            returned.set(),
        ),
        daemon=True,
    )
    caller.start()
    try:
        assert entered.wait(1), "receipt callback never entered"
        assert returned.wait(0.25), "caption caller waited for receipt callback"
    finally:
        release.set()
        caller.join(2)
        assert not caller.is_alive()


def test_default_off_does_not_clock_hash_log_or_reserve(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(identity, "_PROOF_ENABLED", False, raising=False)
    calls = []
    monkeypatch.setattr(identity, "fingerprint_code", lambda code: (calls.append(code), "hash")[1])
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    assert calls == [], "default-off proof still fingerprinted caller code"
    assert set() == identity._SEEN
    assert receipts(caplog) == []


def test_capture_then_patch_keeps_actual_and_selected_snapshot(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    entered, release, returned = (threading.Event() for _ in range(3))
    original_hash = identity.fingerprint_code

    def blocked_hash(code):
        entered.set()
        assert release.wait(3)
        return original_hash(code)

    monkeypatch.setattr(identity, "fingerprint_code", blocked_hash)
    owner = Owner()
    actual = Owner.transcribe.__code__
    expected = original_hash(actual)
    caller = threading.Thread(
        target=lambda: (identity.note_executing("runtime", actual, owner), returned.set()),
        daemon=True,
    )
    caller.start()
    try:
        assert entered.wait(1)
        assert returned.wait(0.25), "capture callback did not return before fingerprint"
        owner.transcribe = lambda: "later patch"
    finally:
        release.set()
        caller.join(2)
        for worker in identity._THREADS.values():
            worker.join(2)
    result = receipts(caplog)[0]
    assert result["executing"]["sha256"] == expected
    assert result["selected"][0]["sha256"] == expected, "worker looked up owner after capture"
    assert result["status"] == "ok"


def test_once_keys_no_owner_retention_and_dispatch_timing(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    owner = Owner()
    ref = weakref.ref(owner)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda args: identity.note_executing(*args),
                [("runtime", Owner.transcribe.__code__, owner)] * 32,
            )
        )
    for worker in identity._THREADS.values():
        worker.join(2)
    result = receipts(caplog)
    assert len(result) == 1
    assert {"runtime"} == identity._SEEN
    assert len(identity._THREADS) == 1
    assert result[0]["caller_capture_dispatch_elapsed_s"] >= 0
    assert result[0]["background_fingerprint_elapsed_s"] >= 0
    del owner
    assert ref() is None, "receipt worker retained owner"


@pytest.mark.parametrize(
    "value,enabled",
    [
        (None, False),
        ("", False),
        (" ", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("unknown", False),
        ("1", True),
        ("TRUE", True),
        (" yes ", True),
        ("on", True),
    ],
)
def test_proof_flag_process_start_canonical_only(value, enabled, monkeypatch):
    monkeypatch.delenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", raising=False)
    monkeypatch.setenv("CIVICAST_CAPTION_EXECUTABLE_PROOF", "1")
    if value is not None:
        monkeypatch.setenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", value)
    spec = importlib.util.spec_from_file_location("test_proof_helper", identity.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    product_modules = {name for name in sys.modules if name.startswith("civiccast.")}
    spec.loader.exec_module(module)
    assert module._PROOF_ENABLED is enabled
    assert {name for name in sys.modules if name.startswith("civiccast.")} == product_modules
    monkeypatch.setenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", "0" if enabled else "1")
    assert module._PROOF_ENABLED is enabled, "hook reread process environment after startup"


@pytest.mark.parametrize("fault", ["constructor", "start"])
def test_failed_dispatch_never_retries(fault, monkeypatch):
    calls = []

    class FakeThread:
        ident = None

        def __init__(self, **kwargs):
            calls.append(kwargs)
            if fault == "constructor":
                raise RuntimeError("constructor")

        def start(self):
            raise RuntimeError("start")

    monkeypatch.setattr(
        identity, "threading", SimpleNamespace(Thread=FakeThread, Event=threading.Event)
    )
    for _ in range(16):
        identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    assert len(calls) == 1
    assert {"runtime"} == identity._SEEN
    assert {"runtime"} == identity._FAILED
    assert all(not hasattr(arg, "transcribe") for arg in calls[0]["args"])


@pytest.mark.parametrize(
    "clock",
    [
        lambda: float("nan"),
        lambda: float("inf"),
        lambda: -1,
        lambda: (_ for _ in ()).throw(RuntimeError("clock")),
    ],
)
def test_bad_builtin_caller_clock_fails_open_truthful_null(clock, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(identity, "_caller_clock", clock)
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity._THREADS["runtime"].join(2)
    assert receipts(caplog)[0]["caller_capture_dispatch_elapsed_s"] is None


def test_three_keys_bounded_and_stuck_worker_does_not_retain_owner(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    release, entered = threading.Event(), threading.Event()
    original_hash = identity.fingerprint_code

    def hash_code(code):
        entered.set()
        assert release.wait(3)
        return original_hash(code)

    monkeypatch.setattr(identity, "fingerprint_code", hash_code)
    monkeypatch.setattr(
        identity, "_ANCHORS", dict.fromkeys(("tap", "runtime", "collector"), ("transcribe",))
    )
    owner = Owner()
    ref = weakref.ref(owner)
    try:
        for name in ("tap", "runtime", "collector"):
            identity.note_executing(name, Owner.transcribe.__code__, owner)
        assert entered.wait(1)
        for _ in range(16):
            for name in ("tap", "runtime", "collector", "other"):
                identity.note_executing(name, Owner.transcribe.__code__, owner)
        assert len(identity._THREADS) == 3
        assert len(identity._SEEN) == 3
        del owner
        assert ref() is None, "hung receipt retained owner"
    finally:
        release.set()


def test_dispatch_stopwatch_is_published_after_start_completion(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    actual_thread = threading.Thread
    now = [1.0]

    class StartsThenFinishes(actual_thread):
        def start(self):
            super().start()
            now[0] = 1.125

    monkeypatch.setattr(
        identity, "threading", SimpleNamespace(Thread=StartsThenFinishes, Event=threading.Event)
    )
    monkeypatch.setattr(identity, "_caller_clock", lambda: now[0])
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity._THREADS["runtime"].join(2)
    result = receipts(caplog)[0]
    assert result["caller_capture_dispatch_elapsed_s"] == 0.125, (
        "worker published timing before start completed"
    )
    assert result["background_fingerprint_elapsed_s"] != 0.125


def test_capture_property_getter_never_executes(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []

    class PropertyOwner(Owner):
        @property
        def transcribe(self):
            calls.append(1)
            raise RuntimeError("descriptor executed")

    identity.note_executing("runtime", Owner.transcribe.__code__, PropertyOwner())
    identity._THREADS["runtime"].join(2)
    assert calls == []
    assert receipts(caplog)[0]["status"] == "unavailable"


def test_dispatch_completion_timeout_stays_unconfirmed(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    waits = []

    class MissingCompletion:
        def wait(self, timeout):
            waits.append(timeout)
            return False

        def set(self):
            pass

    monkeypatch.setattr(
        identity, "threading", SimpleNamespace(Thread=threading.Thread, Event=MissingCompletion)
    )
    identity.note_executing("runtime", Owner.transcribe.__code__, Owner())
    identity._THREADS["runtime"].join(2)
    assert waits == [2]
    assert receipts(caplog) == []
