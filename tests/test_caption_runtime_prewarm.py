# SPDX-License-Identifier: Apache-2.0
"""Native-service startup ordering for the live caption runtime."""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from types import SimpleNamespace

import pytest

from civiccast.app import _maybe_start_background_supervisors
from civiccast.captions import runtime as runtime_module


@pytest.fixture
def prepared_runtime_seams(monkeypatch):
    """No dependency import, native session creation or inference in these tests."""
    events = []

    class Model:
        def __init__(self, *args, **kwargs):
            events.append("model")

        def transcribe(self, *args, **kwargs):
            pytest.fail("preparation must not run dummy transcription")

    @lru_cache
    def get_vad_model():
        events.append("vad-session")
        return object()

    monkeypatch.setattr(runtime_module, "_load_whisper_model_class", lambda: Model)
    monkeypatch.setitem(
        sys.modules, "faster_whisper.vad", SimpleNamespace(get_vad_model=get_vad_model)
    )
    return events, get_vad_model


def test_live_prepare_initializes_cached_vad_before_admission(prepared_runtime_seams):
    events, getter = prepared_runtime_seams
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)
    runtime.prepare()
    runtime.prepare()
    assert events == ["model", "vad-session"], "live preparation left VAD cold"
    assert getter.cache_info().misses == 1
    assert runtime.language is None and runtime.vad_filter is True


@pytest.mark.parametrize("live,vad", [(False, True), (True, False)])
def test_prepare_does_not_eagerly_load_unused_vad(prepared_runtime_seams, live, vad):
    events, getter = prepared_runtime_seams
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=live, vad_filter=vad)
    runtime.prepare()
    assert events == ["model"]
    assert getter.cache_info().misses == 0


def test_concurrent_live_prepare_uses_one_shared_vad_session(monkeypatch, prepared_runtime_seams):
    events, _ = prepared_runtime_seams
    entered, release = threading.Event(), threading.Event()
    all_preparing = threading.Event()

    class TrackedLock:
        """Observe all real callers before releasing the held cold getter."""

        def __init__(self):
            self.lock = threading.Lock()
            self.count_lock = threading.Lock()
            self.requests = 0

        def __enter__(self):
            with self.count_lock:
                self.requests += 1
                if self.requests == 3:
                    all_preparing.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    monkeypatch.setattr(runtime_module, "_LIVE_VAD_PREPARE_LOCK", TrackedLock(), raising=False)

    @lru_cache
    def held_getter():
        events.append("vad-session")
        entered.set()
        assert release.wait(3)
        return object()

    monkeypatch.setitem(
        sys.modules, "faster_whisper.vad", SimpleNamespace(get_vad_model=held_getter)
    )
    runtimes = [runtime_module.FasterWhisperRuntime(device="cpu", live=True) for _ in range(3)]
    for runtime in runtimes:
        runtime._model_instance()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(runtime.prepare) for runtime in runtimes]
            assert entered.wait(1), "live prepare never initialized VAD"
            assert all_preparing.wait(1), "not all concurrent prepare calls reached VAD"
            release.set()
            for future in futures:
                future.result(timeout=2)
    finally:
        release.set()
    assert events.count("vad-session") == 1


def test_vad_preparation_failure_keeps_native_startup_best_effort(
    monkeypatch, caplog, prepared_runtime_seams
):
    events, getter = prepared_runtime_seams
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)

    def broken_getter():
        events.append("vad-error")
        raise RuntimeError("VAD session unavailable")

    monkeypatch.setitem(
        sys.modules, "faster_whisper.vad", SimpleNamespace(get_vad_model=broken_getter)
    )
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            durable_storage_active=True,
            health_schema_owner=_Owner(),
            supervisor_mode="normal",
            caption_tap_worker=SimpleNamespace(_runtime=runtime),
            background_supervisors=[_Supervisor("civiccast-channel-automation", events)],
            startup_condition_hooks=[],
        )
    )
    _maybe_start_background_supervisors(app)
    assert events == ["model", "vad-error", "start:civiccast-channel-automation"]
    assert not getattr(app.state, "caption_runtime_prewarmed", False)
    assert runtime.vad_filter is True and runtime.language is None
    assert "prewarm failed" in caplog.text.lower()
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", SimpleNamespace(get_vad_model=getter))
    _maybe_start_background_supervisors(app)
    assert app.state.caption_runtime_prewarmed is True
    assert events[-2:] == ["vad-session", "start:civiccast-channel-automation"]


class _Owner:
    """Synchronous seam for the current serialized startup/admission contract."""

    def __init__(self) -> None:
        self._depth = 0

    @contextmanager
    def operation(self):
        self._depth += 1
        try:
            yield True
        finally:
            self._depth -= 1

    @contextmanager
    def admission(self):
        assert self._depth == 1, "startup must hold its owner operation"
        yield True


class _Supervisor:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def start(self, *, admission) -> None:
        with admission() as allowed:
            assert allowed
            self._events.append(f"start:{self._name}")


class _Runtime:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.device = "cuda"
        self.compute_type = "float16"
        self.num_workers = 3
        self._model = SimpleNamespace(model=SimpleNamespace(device="cuda", compute_type="float16"))

    def prepare(self) -> None:
        self._events.append("prepare")

    def on_cuda(self) -> bool:
        return True


def test_live_caption_runtime_is_prepared_before_channel_automation_starts(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    events: list[str] = []
    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            durable_storage_active=True,
            health_schema_owner=_Owner(),
            supervisor_mode="normal",
            caption_tap_worker=SimpleNamespace(_runtime=_Runtime(events)),
            background_supervisors=[
                _Supervisor("civiccast-channel-automation", events),
                _Supervisor("civiccast-caption-tap-worker", events),
            ],
            startup_condition_hooks=[],
        )
    )

    _maybe_start_background_supervisors(app)

    assert events == [
        "prepare",
        "start:civiccast-channel-automation",
        "start:civiccast-caption-tap-worker",
    ]


def test_live_caption_runtime_preparation_failure_does_not_block_startup(
    caplog, monkeypatch
) -> None:
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    events: list[str] = []

    class _BrokenRuntime(_Runtime):
        def prepare(self) -> None:
            events.append("prepare")
            raise RuntimeError("model load failed")

    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            durable_storage_active=True,
            health_schema_owner=_Owner(),
            supervisor_mode="normal",
            caption_tap_worker=SimpleNamespace(_runtime=_BrokenRuntime(events)),
            background_supervisors=[_Supervisor("civiccast-channel-automation", events)],
            startup_condition_hooks=[],
        )
    )

    _maybe_start_background_supervisors(app)

    assert events == ["prepare", "start:civiccast-channel-automation"]
    assert "prewarm failed" in caplog.text.lower()
