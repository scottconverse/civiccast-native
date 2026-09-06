# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 82 (sandbox run 13 evidence): a fresh GStreamer worker died with
``RuntimeError: pipeline did not reach PLAYING within 5.0s (get_state=async)``
under CPU load -- the old bound was ``teardown_timeout_s`` (5.0s), a constant
that was never meant to double as a preroll bound, and the daemon treated the
resulting exit as an ordinary crash (relaunch storm against a source that was
never actually broken).

Like ``tests/egress/test_gst_engine_reload_concat_naming.py``, these do NOT
require a real GStreamer/gi install: ``civiccast.egress.gst.engine`` is loaded
fresh against a small FAKE ``gi``/``Gst`` (installed into ``sys.modules`` only
for the duration of the import, then restored) -- just enough to drive
``GstPlayoutEngine._await_playing`` and ``_resolve_preroll_timeout_s`` without a
real pipeline or main loop.

The fake pipeline's ``get_state(timeout)`` simulates GStreamer's own blocking
contract (block for up to ``timeout``, then report where the pipeline is) by
advancing a FAKE clock that ``time.monotonic`` is monkeypatched to read from --
so these tests run instantly, never a real multi-second sleep.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"

# The fake Gst.SECOND is 1 (not GStreamer's real 1_000_000_000) so the fake
# pipeline's ``get_state(timeout)`` argument is directly comparable to whole
# simulated seconds -- purely a test-harness simplification, engine.py itself
# only ever does ``int(seconds * Gst.SECOND)`` and never assumes a specific value.
_FAKE_GST_SECOND = 1


class _FakeStateChangeReturn:
    def __init__(self, nick: str) -> None:
        self.value_nick = nick

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<StateChangeReturn {self.value_nick}>"


class _StateChangeReturn:
    SUCCESS = _FakeStateChangeReturn("success")
    NO_PREROLL = _FakeStateChangeReturn("no-preroll")
    FAILURE = _FakeStateChangeReturn("failure")
    ASYNC = _FakeStateChangeReturn("async")


class _FakeState:
    def __init__(self, nick: str) -> None:
        self.value_nick = nick

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<State {self.value_nick}>"


class _State:
    VOID_PENDING = _FakeState("void-pending")
    NULL = _FakeState("null")
    PLAYING = _FakeState("playing")


class _FakeClock:
    """Shared, monkeypatched stand-in for ``time.monotonic`` -- advanced by the
    fake pipeline's ``get_state`` to simulate GStreamer's blocking wait without
    a real sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _FakePipeline:
    """``get_state(timeout)`` advances the shared fake clock by ``timeout``
    (simulating a blocking wait of that many seconds), then reports SUCCESS
    once the clock has reached ``reach_playing_at_s`` -- or never, if it is
    ``None`` (models a wedged preroll that never completes)."""

    def __init__(self, clock: _FakeClock, *, reach_playing_at_s: float | None) -> None:
        self._clock = clock
        self._reach_playing_at_s = reach_playing_at_s
        self.get_state_calls: list[float] = []

    def get_state(self, timeout: float) -> tuple[Any, Any, Any]:
        self.get_state_calls.append(timeout)
        self._clock.now += timeout
        if self._reach_playing_at_s is not None and self._clock.now >= self._reach_playing_at_s:
            return (_StateChangeReturn.SUCCESS, _State.PLAYING, _State.VOID_PENDING)
        return (_StateChangeReturn.ASYNC, _State.NULL, _State.PLAYING)


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.StateChangeReturn = _StateChangeReturn  # type: ignore[attr-defined]
    fake_gst.State = _State  # type: ignore[attr-defined]
    fake_gst.SECOND = _FAKE_GST_SECOND  # type: ignore[attr-defined]
    return fake_gst


@pytest.fixture
def engine_module():
    """Load ``civiccast.egress.gst.engine`` fresh against a fake ``gi``/``Gst``
    that needs no real GStreamer install, without disturbing ``sys.modules``
    for any other test in the session (a real ``gi`` install, if present, is
    restored after this fixture tears down). Mirrors the fixture in
    ``test_gst_engine_reload_concat_naming.py``."""
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_repository = types.ModuleType("gi.repository")
    fake_glib = types.ModuleType("gi.repository.GLib")
    fake_gst = _install_fake_gst()
    fake_repository.GLib = fake_glib  # type: ignore[attr-defined]
    fake_repository.Gst = fake_gst  # type: ignore[attr-defined]
    fake_gi.repository = fake_repository  # type: ignore[attr-defined]

    patched_names = ("gi", "gi.repository", "gi.repository.GLib", "gi.repository.Gst")
    saved = {name: sys.modules.get(name) for name in (*patched_names, _ENGINE_MODULE_NAME)}
    for name in patched_names:
        sys.modules[name] = {
            "gi": fake_gi,
            "gi.repository": fake_repository,
            "gi.repository.GLib": fake_glib,
            "gi.repository.Gst": fake_gst,
        }[name]
    sys.modules.pop(_ENGINE_MODULE_NAME, None)
    try:
        module = importlib.import_module(_ENGINE_MODULE_NAME)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _bare_engine(
    module: types.ModuleType, pipeline: _FakePipeline, *, preroll_timeout_s: float
) -> Any:
    """A ``GstPlayoutEngine`` with none of ``__init__``'s heavy pipeline-building
    run -- just the attributes ``_await_playing`` actually touches."""
    engine = object.__new__(module.GstPlayoutEngine)
    engine.pipeline = pipeline
    engine.preroll_timeout_s = preroll_timeout_s
    return engine


# --- item 1/2: _await_playing itself -----------------------------------------------


def test_await_playing_passes_when_playing_arrives_before_the_default_bound(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake pipeline that reaches PLAYING at simulated t=12s passes cleanly
    under the 30s default bound -- and the wait is polled in slices (visible,
    multiple ``get_state`` calls), not one single 30s blocking call."""
    clock = _FakeClock()
    monkeypatch.setattr(engine_module.time, "monotonic", clock.monotonic)
    pipeline = _FakePipeline(clock, reach_playing_at_s=12.0)
    engine = _bare_engine(engine_module, pipeline, preroll_timeout_s=30.0)

    engine._await_playing()  # must not raise

    assert len(pipeline.get_state_calls) > 1, "must poll in slices, not one blocking call"
    assert clock.now >= 12.0


def test_await_playing_raises_preroll_timeout_error_past_the_bound(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pipeline that never reaches PLAYING raises the DISTINCT
    ``PrerollTimeoutError`` once the configured bound (31s here) is exceeded --
    not a bare ``RuntimeError`` (worker.py tells them apart to choose the exit
    code; a bare ``RuntimeError`` IS a ``PrerollTimeoutError`` since it
    subclasses it, but the reverse must not hold for other RuntimeErrors)."""
    clock = _FakeClock()
    monkeypatch.setattr(engine_module.time, "monotonic", clock.monotonic)
    pipeline = _FakePipeline(clock, reach_playing_at_s=None)  # wedged forever
    engine = _bare_engine(engine_module, pipeline, preroll_timeout_s=31.0)

    with pytest.raises(engine_module.PrerollTimeoutError, match=r"31\.0s"):
        engine._await_playing()

    assert issubclass(engine_module.PrerollTimeoutError, RuntimeError)
    assert clock.now >= 31.0


def test_await_playing_logs_pipeline_state_every_poll_interval(
    engine_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every 5s slice while still waiting logs the ``get_state`` result and the
    pending state to stderr -- so a slow (not wedged) preroll under load is
    VISIBLE, the whole point of item 82's fix (the old code blocked silently
    for the entire bound)."""
    clock = _FakeClock()
    monkeypatch.setattr(engine_module.time, "monotonic", clock.monotonic)
    pipeline = _FakePipeline(clock, reach_playing_at_s=17.0)
    engine = _bare_engine(engine_module, pipeline, preroll_timeout_s=30.0)

    engine._await_playing()

    err = capsys.readouterr().err
    assert err.count("CTRL preroll: still waiting for PLAYING") >= 2
    assert "get_state=async" in err
    assert "pending=playing" in err


def test_await_playing_raises_plain_runtime_error_on_immediate_failure(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``get_state`` FAILURE (a genuine pipeline construction/link problem,
    not a slow preroll) still raises a plain ``RuntimeError`` -- NOT the
    distinct ``PrerollTimeoutError`` -- so the daemon/worker never mistake a
    real pipeline failure for a retryable slow start."""
    clock = _FakeClock()
    monkeypatch.setattr(engine_module.time, "monotonic", clock.monotonic)

    class _FailingPipeline(_FakePipeline):
        def get_state(self, timeout: float) -> tuple[Any, Any, Any]:
            self.get_state_calls.append(timeout)
            self._clock.now += timeout
            return (_StateChangeReturn.FAILURE, _State.NULL, _State.VOID_PENDING)

    pipeline = _FailingPipeline(clock, reach_playing_at_s=None)
    engine = _bare_engine(engine_module, pipeline, preroll_timeout_s=30.0)

    with pytest.raises(RuntimeError) as exc_info:
        engine._await_playing()
    assert not isinstance(exc_info.value, engine_module.PrerollTimeoutError)


# --- item 3: env override / clamp / default resolution -----------------------------


def test_resolve_preroll_timeout_defaults_to_30s(engine_module) -> None:
    assert engine_module._resolve_preroll_timeout_s(None) == 30.0


def test_resolve_preroll_timeout_reads_the_env_override(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_PREROLL_TIMEOUT_S", "45")
    assert engine_module._resolve_preroll_timeout_s(None) == 45.0


def test_resolve_preroll_timeout_clamps_the_env_override_to_5s_minimum(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_PREROLL_TIMEOUT_S", "2")
    assert engine_module._resolve_preroll_timeout_s(None) == 5.0


def test_resolve_preroll_timeout_ignores_a_malformed_env_value(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_PREROLL_TIMEOUT_S", "not-a-number")
    assert engine_module._resolve_preroll_timeout_s(None) == 30.0


def test_resolve_preroll_timeout_explicit_constructor_value_wins_over_env(
    engine_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_GST_PREROLL_TIMEOUT_S", "45")
    assert engine_module._resolve_preroll_timeout_s(12.0) == 12.0


def test_resolve_preroll_timeout_clamps_an_explicit_constructor_value_too(
    engine_module,
) -> None:
    assert engine_module._resolve_preroll_timeout_s(1.0) == 5.0
