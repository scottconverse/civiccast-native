# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BETA.10 U04: the stuck-pass watchdog names where a stalled pass is stuck.

U01 (2026-09-24) established that the single automation thread spent ~446s
inside public's pass (13:30:44,903 -> 13:38:10,887) and that nothing said which
call it was in, because a pass logs nothing until it returns. These tests drive
the REAL loop -- ``run_forever`` on a thread -- against a fake daemon whose
``process_once`` blocks on a real ``threading.Event``, which is the shape of the
station stall (a synchronous ``SourcePreparer.prepare`` inside the pass). Real,
short thresholds are used rather than a stubbed clock, so what is exercised is
the production code path: a pass that outlives its threshold while a daemon
watcher thread dumps the automation thread's live stack.

The env names and the watcher's thread name are pinned here as literals: they
are the operator-facing and thread-dump-facing surface of this feature, so a
rename has to be a deliberate edit in two places rather than silently following
a constant.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from civiccast.egress.automation import (
    WATCHDOG_REPEAT_ENV,
    WATCHDOG_THRESHOLD_ENV,
    ChannelAutomationService,
    ChannelAutomationSettings,
    _PassWatchdog,
    pass_watchdog_repeat_seconds_from_env,
    pass_watchdog_threshold_seconds_from_env,
)
from civiccast.egress.models import CanonicalProfile, EgressConfig, EgressSinkSpec
from civiccast.egress.store import InMemoryEgressStore

# Two C's, like every other variable in the station's registry -- the one-C form
# is one character shorter and visually identical (see
# ``test_the_registry_spelling_is_the_two_c_one_and_has_no_legacy_alias``).
_THRESHOLD_ENV = "CIVICCAST_AUTOMATION_PASS_WATCHDOG_SECONDS"
_REPEAT_ENV = "CIVICCAST_AUTOMATION_PASS_WATCHDOG_REPEAT_SECONDS"
_WATCHDOG_THREAD = "civiccast-channel-automation-pass-watchdog"
_AUTOMATION_LOGGER = "civiccast.egress.automation"
_POLL_SECONDS = 0.01


def _config(channel_id: str) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        auto_start=False,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _service(store: InMemoryEgressStore, daemon: object) -> ChannelAutomationService:
    """The service under test with the daemon double wired in as the daemon."""

    return ChannelAutomationService(
        store,
        daemon,  # type: ignore[arg-type]
        lambda channel_id: None,
        settings=ChannelAutomationSettings(poll_seconds=_POLL_SECONDS),
    )


def _watchdog_threads() -> list[threading.Thread]:
    """By NAME, so a stray thread cannot hide behind ``enumerate()`` noise."""

    return [thread for thread in threading.enumerate() if thread.name == _WATCHDOG_THREAD]


def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` for up to ``timeout`` seconds.

    The loop runs on its own thread, so every claim about what it logged (or
    about a thread it started) has to wait for that thread to get there rather
    than assume it already has.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _records(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if needle in record.getMessage()]


def _runner(service: ChannelAutomationService, stop_event: threading.Event) -> threading.Thread:
    """The loop's thread, as ``ThreadSupervisor`` starts it in production: a
    daemon. A test that fails mid-way can then never leave a live loop thread
    holding the interpreter open."""

    return threading.Thread(
        target=service.run_forever,
        kwargs={"poll_seconds": _POLL_SECONDS, "stop_event": stop_event},
        name="u04-pass-watchdog-runner",
        daemon=True,
    )


class _IdleDaemon:
    """The minimum a channel pass needs: no live process, no operator override."""

    def __init__(self) -> None:
        self.processed: list[str] = []
        self.passes = 0

    def has_live_process(self, channel_id: str) -> bool:
        return False

    def has_manual_override(self, channel_id: str) -> bool:
        return False

    def process_once(self, channel_id: str) -> int:
        self.processed.append(channel_id)
        self.passes += 1
        return 0


class _StallingDaemon(_IdleDaemon):
    """A pass that blocks where the real one blocks: inside ``process_once``.

    ``hold_seconds=None`` blocks until ``release`` is set (the stall that has
    to be reported); a number blocks for exactly that long (a pass that stays
    under a longer threshold and must therefore be silent).
    """

    def __init__(self, *, hold_seconds: float | None = None) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self._hold_seconds = hold_seconds

    def process_once(self, channel_id: str) -> int:
        self.processed.append(channel_id)
        self.passes += 1
        self.entered.set()
        return self._block_until_released(channel_id)

    def _block_until_released(self, channel_id: str) -> int:
        """The blocked call a stack dump has to be able to name."""

        if self._hold_seconds is None:
            self.release.wait(2.0)
        else:
            time.sleep(self._hold_seconds)
        return 0


def test_stalled_pass_reports_the_stack_repeatedly_then_its_total_duration(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The U01 shape: one pass runs for minutes on the automation thread.

    Threshold 0.2s / repeat 0.2s: the stack is dumped once the pass passes the
    threshold, dumped AGAIN while it stays stalled, and the pass's own total
    duration is reported the moment it ends.
    """

    monkeypatch.setenv(_THRESHOLD_ENV, "0.2")
    monkeypatch.setenv(_REPEAT_ENV, "0.2")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon()
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        runner.start()
        try:
            assert daemon.entered.wait(1.0), "the blocked pass never started"
            assert _wait_for(lambda: len(_records(caplog, "still running")) >= 2, 2.0), (
                "the watchdog did not re-report a pass that stayed stalled past the threshold"
            )
            first = _records(caplog, "still running")[0].getMessage()
            assert "Channel automation pass for public has run" in first
            assert "automation thread stack:" in first
            assert "_block_until_released" in first, (
                "the dumped stack does not name the call the pass is stuck in"
            )
        finally:
            # Always, however the assertions above went: release the pass and
            # stop the loop, so a red run cannot leave a loop thread behind.
            daemon.release.set()
            stop_event.set()
            runner.join(2.0)

    assert not runner.is_alive(), "run_forever did not stop on its stop_event"
    assert _wait_for(lambda: not _watchdog_threads(), 1.0), (
        "the watchdog thread outlived the loop it watches"
    )
    assert _wait_for(lambda: bool(_records(caplog, "exceeded watchdog")), 1.0), (
        "the finished pass's total duration was never reported"
    )
    finished = _records(caplog, "exceeded watchdog")[0].getMessage()
    assert finished.startswith("Channel automation pass for public finished after ")
    assert len(_records(caplog, "exceeded watchdog")) == 1, (
        "the pass end must be reported exactly once, not per stalled poll"
    )


def test_pass_under_the_threshold_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A pass that stays under the threshold is nobody's business.

    Threshold 0.5s against passes of ~0.15s: the watchdog's ticks land at 0.5s
    and 0.6s, i.e. while a pass is genuinely RUNNING, and every one of those
    passes is still under the threshold -- so the silence asserted here is the
    comparison working, not the watchdog failing to run.
    """

    monkeypatch.setenv(_THRESHOLD_ENV, "0.5")
    monkeypatch.setenv(_REPEAT_ENV, "0.1")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon(hold_seconds=0.15)
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        runner.start()
        try:
            # Five ~0.15s passes put the clock past the 0.5s and 0.6s ticks.
            assert _wait_for(lambda: daemon.passes >= 5, 2.0), "the loop did not run passes"
            # U04 review: without this the silences below are equally true of a
            # watchdog that never started. With it, the watcher is provably
            # alive while the passes run.
            assert _wait_for(lambda: len(_watchdog_threads()) == 1, 1.0), (
                "no watcher was running, so the silences below prove nothing"
            )
        finally:
            stop_event.set()
            runner.join(1.0)

    assert _records(caplog, "still running") == []
    assert _records(caplog, "exceeded watchdog") == []


def test_run_once_without_run_forever_has_no_watchdog_thread_and_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Requirement: the testable unit keeps working, watchless.

    ``run_once`` is called directly by most of this suite. Its pass here runs
    0.3s against a 0.1s threshold, so a watchdog thread would certainly have
    reported it -- the silence is the absence of the thread, which is asserted
    by name as well.
    """

    monkeypatch.setenv(_THRESHOLD_ENV, "0.1")
    monkeypatch.setenv(_REPEAT_ENV, "0.1")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon(hold_seconds=0.3)
    service = _service(store, daemon)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        seen = service.run_once(now=datetime.now(UTC))

    assert seen == ["public"]
    assert daemon.processed == ["public"]
    assert _watchdog_threads() == []
    assert _records(caplog, "still running") == []
    assert _records(caplog, "exceeded watchdog") == []


def test_threshold_zero_disables_the_watchdog(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """0 is the documented off switch: no thread, no dump, however long the stall."""

    monkeypatch.setenv(_THRESHOLD_ENV, "0")
    monkeypatch.setenv(_REPEAT_ENV, "0.1")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon()
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        runner.start()
        try:
            assert daemon.entered.wait(1.0), "the blocked pass never started"
            # Well past the 0.1s repeat a still-running pass would have been
            # re-reported at, had the threshold been anything but 0.
            time.sleep(0.3)
            assert _watchdog_threads() == [], "a disabled watchdog still spawned a thread"
            assert _records(caplog, "still running") == []
        finally:
            daemon.release.set()
            stop_event.set()
            runner.join(1.0)

    assert _records(caplog, "exceeded watchdog") == []
    assert not runner.is_alive()


def test_watchdog_is_one_named_daemon_thread_that_stops_with_run_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserted by name: exactly one watcher, a daemon, gone when the loop ends."""

    monkeypatch.setenv(_THRESHOLD_ENV, "0.5")
    monkeypatch.setenv(_REPEAT_ENV, "0.5")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon()
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    runner.start()
    try:
        assert daemon.entered.wait(1.0), "the blocked pass never started"
        assert _wait_for(lambda: len(_watchdog_threads()) == 1, 1.0), (
            "run_forever did not start exactly one watchdog thread"
        )
        assert _watchdog_threads()[0].daemon is True, "the watchdog thread is not a daemon"
    finally:
        daemon.release.set()
        stop_event.set()
        runner.join(1.0)

    assert not runner.is_alive()
    assert _wait_for(lambda: not _watchdog_threads(), 1.0), (
        "the watchdog thread survived the loop's stop_event"
    )


@pytest.mark.parametrize("bad_value", ["not-a-number", "-5", "nan", "inf", "0.0.0"])
def test_invalid_threshold_env_warns_and_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, bad_value: str
) -> None:
    """A typo must never silently disable a stall detector.

    Same contract as this module's other env readers (see
    ``rollover_lead_seconds_from_env``): the offending value is named at
    WARNING and the safe default -- 30s -- is what ends up in force.
    """

    monkeypatch.setenv(_THRESHOLD_ENV, bad_value)
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        service = _service(InMemoryEgressStore(), _IdleDaemon())

    warnings = _records(caplog, _THRESHOLD_ENV)
    assert len(warnings) == 1, f"expected exactly one warning naming the variable: {warnings}"
    assert bad_value in warnings[0].getMessage()
    assert "using 30.0s" in warnings[0].getMessage()
    assert service is not None


def test_invalid_repeat_env_warns_and_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """0 is INVALID here, unlike the threshold: a 0s repeat would spin the
    watcher thread re-checking a pass it has just reported."""

    monkeypatch.setenv(_REPEAT_ENV, "0")
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        _service(InMemoryEgressStore(), _IdleDaemon())

    warnings = _records(caplog, _REPEAT_ENV)
    assert len(warnings) == 1, f"expected exactly one warning naming the variable: {warnings}"
    assert "using 60.0s" in warnings[0].getMessage()


def test_readers_default_to_30s_and_60s_and_pass_real_values_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert pass_watchdog_threshold_seconds_from_env() == 30.0
    assert pass_watchdog_repeat_seconds_from_env() == 60.0

    monkeypatch.setenv(_THRESHOLD_ENV, "12.5")
    monkeypatch.setenv(_REPEAT_ENV, "5")
    assert pass_watchdog_threshold_seconds_from_env() == 12.5
    assert pass_watchdog_repeat_seconds_from_env() == 5.0


def test_the_registry_spelling_is_the_two_c_one_and_has_no_legacy_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U04 coordinator fix 1: the brief says ``CIVICCAST_`` (two C's) -- the
    spelling the station's registry sets -- and this unit first shipped
    ``CIVICAST_`` (one C), one character short.

    That is the same defect class U03 fixed one unit earlier, and it survived a
    byte-level spelling check during planning because the check was run against
    the BRIEF: the brief's name was measured, then the constants were typed
    from eye-memory. ``CIVICAST`` and ``CIVICCAST`` render identically in most
    fonts, so no amount of re-reading catches this -- only measurement does.
    Hence the prefix-length assertion below: it is machine-checkable where the
    glyphs are not, and it fails if anyone ever types 8 characters again.

    These variables are brand new, so there is no legacy spelling to keep: a
    one-C alias must NOT be honoured, or an operator who sets the wrong name
    would silently get a 30s detector while believing they changed it.
    """

    # 1. The literal, spelled out -- the operator-facing surface.
    assert WATCHDOG_THRESHOLD_ENV == "CIVICCAST_AUTOMATION_PASS_WATCHDOG_SECONDS"
    assert WATCHDOG_REPEAT_ENV == "CIVICCAST_AUTOMATION_PASS_WATCHDOG_REPEAT_SECONDS"
    # 2. "CIVICCAST" is 9 characters; "CIVICAST" is 8 and looks the same.
    assert {
        len(name.split("_", 1)[0]) for name in (WATCHDOG_THRESHOLD_ENV, WATCHDOG_REPEAT_ENV)
    } == {9}

    # 3. The two-C name is the one that is read...
    monkeypatch.setenv("CIVICCAST_AUTOMATION_PASS_WATCHDOG_SECONDS", "12.5")
    assert pass_watchdog_threshold_seconds_from_env() == 12.5
    monkeypatch.delenv(WATCHDOG_THRESHOLD_ENV)
    # ...and the one-C name is inert, because it was never this variable's name.
    monkeypatch.setenv("CIVICAST_AUTOMATION_PASS_WATCHDOG_SECONDS", "99")
    assert pass_watchdog_threshold_seconds_from_env() == 30.0


def test_zero_threshold_is_the_off_switch_and_is_not_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """0 is a deliberate setting, not a typo: returned as-is, in silence.
    Nagging an operator for turning a diagnostic off is its own bug."""

    monkeypatch.setenv(_THRESHOLD_ENV, "0")
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        assert pass_watchdog_threshold_seconds_from_env() == 0.0

    assert caplog.records == []


def test_first_dump_lands_at_the_threshold_not_a_whole_repeat_later(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Threshold 0.2s, repeat 2.0s: the stall is reported well inside 2s.

    A watcher that slept the repeat interval from the start would miss every
    stall longer than the threshold but shorter than the repeat -- the band a
    real stall is most likely to land in -- so the first check is pinned to
    the threshold here, where the repeat is far longer than this test.
    """

    monkeypatch.setenv(_THRESHOLD_ENV, "0.2")
    monkeypatch.setenv(_REPEAT_ENV, "2.0")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon()
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        runner.start()
        try:
            assert daemon.entered.wait(1.0), "the blocked pass never started"
            assert _wait_for(lambda: bool(_records(caplog, "still running")), 1.5), (
                "the first dump waited for the repeat interval instead of the threshold"
            )
        finally:
            daemon.release.set()
            stop_event.set()
            runner.join(2.0)

    assert not runner.is_alive()


class _RaisingFrames:
    """A ``sys._current_frames`` stand-in that fails, as the real private API
    could; the watcher must survive a dump it cannot take."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> dict[int, Any]:
        self.calls += 1
        raise RuntimeError("frames unavailable")


class _RaisingClock:
    """A monotonic clock stand-in that fails, so the pass-side guard is
    exercised rather than argued."""

    def __call__(self) -> float:
        raise RuntimeError("clock unavailable")


def test_a_failing_stack_dump_costs_one_tick_not_the_watcher(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``sys._current_frames`` is private CPython API; a dump that raises must
    cost one tick, never the watcher thread and never the pass-end report."""

    frames = _RaisingFrames()
    watchdog = _PassWatchdog(threshold_seconds=0.1, repeat_seconds=0.1, current_frames=frames)
    watchdog.start()
    try:
        with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
            watchdog.pass_started("public")
            assert _wait_for(lambda: frames.calls >= 2, 1.5), (
                "the watcher thread died on the first failed dump"
            )
            watchdog.pass_finished("public")
    finally:
        watchdog.stop()

    assert _wait_for(lambda: not _watchdog_threads(), 1.0)
    assert _records(caplog, "still running") == []
    assert len(_records(caplog, "exceeded watchdog")) == 1, (
        "a pass whose dump could not be taken still has to report its overrun"
    )


def test_a_pass_whose_thread_is_gone_still_reports_its_overrun(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The dump needs a live frame; the finished line does not. An empty frames
    map is exactly the ident-already-gone case: the watcher trips over the
    overrun, finds no stack to print, and the pass still reports its duration.

    The pass is held past several 0.05s ticks and then finished, so the only
    thing missing from the log is the dump itself."""

    watchdog = _PassWatchdog(threshold_seconds=0.05, repeat_seconds=0.05, current_frames=dict)
    watchdog.start()
    try:
        with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
            watchdog.pass_started("public")
            time.sleep(0.2)
            watchdog.pass_finished("public")
    finally:
        watchdog.stop()

    assert _wait_for(lambda: not _watchdog_threads(), 1.0)
    assert _records(caplog, "still running") == []
    # Guarded, like it is in the failing-dump test above: the 0.05s tick has to
    # land inside the 0.2s hold, so on a loaded box this is the assertion in
    # this file most likely to need a moment more.
    assert _wait_for(lambda: len(_records(caplog, "exceeded watchdog")) == 1, 1.0)


def test_a_failing_clock_never_raises_into_the_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``pass_started``/``pass_finished`` run on the automation thread and in a
    ``finally``: a watchdog bookkeeping failure must never fail, and never
    relabel, a channel pass."""

    watchdog = _PassWatchdog(threshold_seconds=1.0, repeat_seconds=1.0, monotonic=_RaisingClock())
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        watchdog.pass_started("public")
        watchdog.pass_finished("public")

    assert caplog.records == []


class _RaisingLogHandler(logging.Handler):
    """A handler that fails with ``RecursionError`` -- the one exception
    ``logging`` deliberately re-raises out of ``emit`` instead of swallowing,
    so it escapes the ``except Exception`` around the reporting path."""

    def emit(self, record: logging.LogRecord) -> None:
        raise RecursionError("maximum recursion depth exceeded")


def test_a_failing_log_handler_never_replaces_a_pass_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """U04 review (R3): the guard's own fallback is a log call, and a handler
    can raise -- ``logging`` re-raises ``RecursionError`` out of ``emit`` by
    design rather than swallowing it.

    The precondition is measured, not assumed: the escape needs the fallback
    ``DEBUG`` record to actually be EMITTED, so this pins the logger at DEBUG,
    the level an operator troubleshooting a stalled station would switch on. At
    the shipped WARNING level the fallback is filtered before any handler sees
    it. Reproduced before the fix, at DEBUG: ``pass_finished`` raised
    ``RecursionError`` out of the pass's ``finally`` and REPLACED the pass's own
    exception -- exactly the blame-the-watchdog outcome the docstring promises
    cannot happen."""

    logger = logging.getLogger(_AUTOMATION_LOGGER)
    handler = _RaisingLogHandler()
    logger.addHandler(handler)
    watchdog = _PassWatchdog(threshold_seconds=60.0, repeat_seconds=60.0)
    try:
        with caplog.at_level(logging.DEBUG, logger=_AUTOMATION_LOGGER):
            watchdog.pass_started("public")
            # Make the pass look reported, so ``pass_finished`` takes the
            # logging branch rather than returning early.
            watchdog._reported = True  # the branch under test
            with pytest.raises(_PassBoom, match="the pass's own exception"):
                try:
                    raise _PassBoom("the pass's own exception")
                finally:
                    watchdog.pass_finished("public")
    finally:
        logger.removeHandler(handler)


class _PassBoom(RuntimeError):
    """The exception a channel pass raised; it must reach the caller intact."""


def test_run_forever_survives_a_watcher_thread_that_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U04 review (R4): ``start()`` sat outside ``run_forever``'s ``try``, so a
    failed ``Thread.start`` (``RuntimeError: can't start new thread``) turned a
    non-essential diagnostic into a dead automation loop -- ``ThreadSupervisor``
    does not restart a worker that exits. Reproduced before the fix."""

    real_start = threading.Thread.start
    attempted: list[str] = []

    def _start(self: threading.Thread) -> None:
        if self.name == _WATCHDOG_THREAD:
            attempted.append(self.name)
            raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _start)
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    service = _service(store, _IdleDaemon())
    stop_event = threading.Event()
    stop_event.set()

    service.run_forever(poll_seconds=_POLL_SECONDS, stop_event=stop_event)

    assert attempted, "the spawn was never attempted, so nothing was proven"
    assert service._pass_watchdog._thread is None, (  # the state under test
        "a watcher that could not start left a thread object behind, so a later "
        "run_forever would refuse to start one"
    )
    assert _watchdog_threads() == []


def test_repeat_beyond_the_event_wait_ceiling_warns_and_uses_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """U04 review (R1): 100000000 is finite, positive and unparsable to nothing
    -- and ``Event.wait`` cannot wait it. Reproduced before the fix: the reader
    accepted it in silence and the watcher died with ``OverflowError`` inside
    its own loop condition, which is the silent-disable failure this reader
    exists to prevent."""

    monkeypatch.setenv(_REPEAT_ENV, "100000000")
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        value = pass_watchdog_repeat_seconds_from_env()

    assert value == 60.0
    warnings = _records(caplog, _REPEAT_ENV)
    assert len(warnings) == 1, f"expected exactly one warning naming the variable: {warnings}"
    assert "100000000" in warnings[0].getMessage()
    assert "using 60.0s" in warnings[0].getMessage()


def test_a_directly_built_watcher_survives_an_interval_the_event_cannot_wait() -> None:
    """U04 review (R1), second half: the reader is not the only way in -- a
    directly constructed ``_PassWatchdog`` (as this suite builds one) must not
    die either. Before the fix the thread was gone within one tick; after it,
    the watcher is alive, ticked once, and still stops on command."""

    watchdog = _PassWatchdog(threshold_seconds=0.2, repeat_seconds=1e8)
    watchdog.start()
    try:
        assert _wait_for(lambda: len(_watchdog_threads()) == 1, 1.0), "the watcher never started"
        watchdog.pass_started("public")
        time.sleep(0.4)
        assert _watchdog_threads(), (
            "the watcher died on an interval Event.wait cannot take (OverflowError)"
        )
    finally:
        watchdog.pass_finished("public")
        watchdog.stop()

    assert _wait_for(lambda: not _watchdog_threads(), 6.0), (
        "stop() could not interrupt a wait near the platform ceiling"
    )


def test_negative_zero_is_zero_not_a_negative_threshold(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """U04 review (R2): ``-0.0 < 0`` is False, so ``-0`` slipped past the
    validity check and came back as ``-0.0``. The watchdog still ends up off --
    which is the documented off switch -- but the returned value was not the
    documented ``0.0``."""

    monkeypatch.setenv(_THRESHOLD_ENV, "-0")
    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        value = pass_watchdog_threshold_seconds_from_env()

    assert value == 0.0
    assert math.copysign(1.0, value) == 1.0, "the threshold came back as negative zero"
    assert caplog.records == []
    assert not _PassWatchdog(threshold_seconds=value, repeat_seconds=60.0).enabled


def test_under_threshold_silence_is_the_comparison_not_a_dead_watcher(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """U04 review, test-confidence gap: the under-threshold test above asserts
    only that no lines were logged, which is equally true of a watcher that
    never ran at all.

    This one counts ticks and, for each, whether a pass record was LIVE when it
    fired -- so the silence is attributable to the comparison rather than to
    the watcher's absence. It has to run against a SEQUENCE of short passes:
    with the first tick landing one threshold after the watcher starts, a
    single under-threshold pass ends before any tick can land, which is why the
    single-pass version of this experiment measures zero ticks either way."""

    live_ticks: list[bool] = []
    real_check = _PassWatchdog._check  # the tick under test

    def _counting_check(self: _PassWatchdog) -> None:
        live_ticks.append(self._channel_id is not None)  # the record under test
        real_check(self)

    monkeypatch.setattr(_PassWatchdog, "_check", _counting_check)
    monkeypatch.setenv(_THRESHOLD_ENV, "0.5")
    monkeypatch.setenv(_REPEAT_ENV, "0.1")
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    daemon = _StallingDaemon(hold_seconds=0.15)
    service = _service(store, daemon)
    stop_event = threading.Event()
    runner = _runner(service, stop_event)

    with caplog.at_level(logging.WARNING, logger=_AUTOMATION_LOGGER):
        runner.start()
        try:
            assert _wait_for(lambda: daemon.passes >= 5, 2.0), "the loop did not run passes"
        finally:
            stop_event.set()
            runner.join(1.0)

    observed = [tick for tick in live_ticks if tick]
    assert len(observed) >= 2, (
        f"{len(live_ticks)} ticks fired, {len(observed)} of them with a live pass record "
        "-- without at least one the silences below prove nothing"
    )
    assert _records(caplog, "still running") == []
    assert _records(caplog, "exceeded watchdog") == []
