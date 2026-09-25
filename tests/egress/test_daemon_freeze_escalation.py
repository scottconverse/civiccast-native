# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BETA.10 U30: escalating when the relay self-heal does NOT restore the window.

The U30 finding (2026-09-25, observed live twice: education 06:27, government
01:03) is a two-step failure with only one step of recovery. A deferred
program->program reload commits at a segment boundary; the HLS live window stops
advancing; the relay supervisor correctly detects the frozen window, correctly
replaces its ffmpeg child ONCE -- and that child writes nothing either. The
one-shot ``heal_attempted`` latch (hls_relay audit finding 4) deliberately
forbids a second heal in the same episode, so the relay path has run out of
moves and the channel sits frozen until a human restarts it. Both live incidents
ended exactly that way (``STALE 36s -> 144s -> full channel restart``).

This guard is the missing second step, and it is modeled line for line on the
U16 output A/V guard: same shape (judge a settled channel, act through the
ordinary bounded worker termination, bounded restarts per rolling hour, then a
throttled CRITICAL). Four disciplines, each with a test below:

* The signal is the HLS live window, and only that. It is what residents see,
  the daemon already reads it every tick, and the relay stamps an exact clock
  for it (``heal_frozen_seconds``, measured from the heal itself). The worker's
  own ``CTRL output: N buffers`` line is deliberately NOT used: the daemon has
  no cheap, reliable seam to a child's stderr text, and the live incident's
  stderr shows that counter ADVANCING all the way through the freeze, so it
  would not even have answered the question.
* One escalation per worker incarnation, and one ERROR line per escalation.
  A killed worker is still the live entry until its exit is reaped, so without
  the pid latch a frozen window would spend the whole budget in a few ticks.
* A channel that is not settled (STARTING/TRANSITIONING/DRAINING) is never
  judged. TRANSITIONING is what ``_poll_process`` publishes while a content
  reload is in flight -- exactly when this freeze has been seen -- and a
  legitimately-young window must not be mistaken for a failed heal.
* The budget survives the restart. It is the whole reason this cannot become a
  restart loop, and a restart obviously changes the pid, so it must not be
  cleared with the episode.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import pytest

from civiccast.egress.daemon import (
    _FREEZE_ESCALATION_AFTER_HEAL_S,
    _FREEZE_ESCALATION_BUDGET_WINDOW_S,
    _FREEZE_ESCALATION_EXHAUSTED_LOG_INTERVAL_S,
    _FREEZE_ESCALATION_RESTART_BUDGET,
    EgressDaemon,
)
from civiccast.egress.hls_relay import HlsRelaySupervisor
from civiccast.egress.models import (
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressStateRow,
)
from civiccast.egress.source_plan import EgressSourcePlan, EgressSourceSegment
from civiccast.egress.store import InMemoryEgressStore

#: The daemon module's own logger -- the escalation's lines must reach an
#: operator through it, not through a print or a proof event alone.
_DAEMON_LOGGER = "civiccast.egress.daemon"

#: Far enough in the past that no ``updated_at`` assertion can depend on "now".
_NOW = datetime(2026, 9, 25, 6, 27, tzinfo=UTC)


# --- fixtures and doubles --------------------------------------------------------


class _FakeClock:
    def __init__(self, value: float = 50_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _FakeWorker:
    """A worker double whose exit is faithful to a REAL deliberate kill.

    Windows' ``Popen.terminate`` is ``TerminateProcess(handle, 1)`` and POSIX
    ``SIGTERM``/``SIGKILL`` both report a negative code, so a terminated worker
    exits NON-ZERO in production. That matters: a non-zero exit with no pending
    reload is exactly what routes the daemon into ``_relaunch_after_crash`` --
    the dead-encoder path this escalation reuses.
    """

    def __init__(self, *, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode: int | None = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1


class _ScriptedRelay:
    """The relay supervisor seam, scripted.

    The daemon's relay poll reaches for these by name (``is_alive``,
    ``note_progress``, ``progress_stale``, ``maybe_self_heal_stalled``,
    ``apply``). This double answers every one of them explicitly rather than
    through a ``MagicMock``, so a rename in the daemon surfaces as an
    ``AttributeError`` in a test instead of a silently-permissive mock.

    ``frozen`` is the value ``heal_frozen_seconds`` reports: ``None`` for "no
    live relay is mid-failed-heal" and a number for "this many seconds since
    the heal replaced the child".
    """

    def __init__(self, *, frozen: float | None = None, alive: bool = True) -> None:
        self.frozen = frozen
        self.alive = alive
        self.stopped: list[str] = []
        self.frozen_queries: list[tuple[str, float]] = []
        self.heal_calls: list[str] = []
        self.apply_calls: list[tuple[bool, Path | str | None]] = []

    def apply(
        self,
        config: EgressConfig,
        *,
        new_session: bool = False,
        log_root: Path | str | None = None,
    ) -> EgressConfig:
        # U21 (0d8b410a) added the ``new_session``/``log_root`` keywords to
        # ``HlsRelaySupervisor.apply``; this double mirrors the real signature so
        # a rename in the daemon still surfaces as an AttributeError here.
        self.apply_calls.append((new_session, log_root))
        return config

    def is_alive(self, channel_id: str) -> bool:
        return self.alive

    def note_progress(self, channel_id: str, *, now: float) -> None:
        return None

    def progress_stale(self, channel_id: str, *, now: float) -> bool:
        return False

    def never_emitted(self, channel_id: str, *, now: float, startup_grace_s: float) -> bool:
        return False

    def maybe_self_heal_stalled(
        self, channel_id: str, *, now: float, producing: bool, startup_grace_s: float
    ) -> bool:
        self.heal_calls.append(channel_id)
        return False

    def heal_frozen_seconds(self, channel_id: str, *, now: float) -> float | None:
        self.frozen_queries.append((channel_id, now))
        return self.frozen

    def stop_channel(self, channel_id: str) -> None:
        self.stopped.append(channel_id)


class _FreezeFixture(NamedTuple):
    daemon: EgressDaemon
    store: InMemoryEgressStore
    workers: list[_FakeWorker]
    clock: _FakeClock
    relay: _ScriptedRelay


def _write_playlist(directory: Path, *, segments: tuple[str, ...]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    playlist = directory / "playlist.m3u8"
    body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
    body += "".join(f"#EXTINF:2.000,\n{name}\n" for name in segments)
    playlist.write_text(body, encoding="utf-8")
    return playlist


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "source-a.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=1,
                source_ref="asset-council",
            )
        ],
    )


def _start_command() -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action="start",
        issued_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id="cmd-start",
    )


def _freeze_fixture(
    tmp_path: Path, *, frozen: float | None = None, alive: bool = True
) -> _FreezeFixture:
    """A daemon with one started ON_AIR channel and a scripted relay supervisor.

    ``frozen`` starts ``None`` in the normal case so the SETUP tick cannot
    escalate; tests that want an escalation set ``relay.frozen`` and then call
    ``_poll_freeze_escalation`` directly, which is what the real tick does.
    """
    live_dir = tmp_path / "gov-live"
    _write_playlist(live_dir, segments=("seg000000001.ts", "seg000000002.ts"))

    workers: list[_FakeWorker] = []

    def starter(_args: list[str]) -> _FakeWorker:
        worker = _FakeWorker(pid=4242 + len(workers))
        workers.append(worker)
        return worker

    clock = _FakeClock()
    relay = _ScriptedRelay(frozen=frozen, alive=alive)
    store = InMemoryEgressStore()
    store.upsert_config(
        EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="slate",
            sinks=[EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir))],
        )
    )
    store.enqueue_command(_start_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=starter,
        hls_relay_supervisor=relay,
    )
    daemon._monotonic = clock  # type: ignore[method-assign]
    return _FreezeFixture(daemon=daemon, store=store, workers=workers, clock=clock, relay=relay)


def _started_on_air(fixture: _FreezeFixture) -> _FakeWorker:
    """Drive one real tick so the daemon owns a worker AND has published ON_AIR."""
    assert fixture.daemon.process_once("gov") == 1
    row = fixture.store.read_state("gov")
    assert row is not None and row.state == "ON_AIR"
    return fixture.workers[0]


def _force_state(fixture: _FreezeFixture, state: str) -> None:
    fixture.store.write_state(EgressStateRow(channel_id="gov", state=state, updated_at=_NOW))  # type: ignore[arg-type]


def _swap_worker(fixture: _FreezeFixture, *, pid: int) -> _FakeWorker:
    """Replace the tracked worker exactly the way a relaunch does."""
    replacement = _FakeWorker(pid=pid)
    fixture.workers.append(replacement)
    fixture.daemon._processes["gov"] = replacement
    fixture.daemon._started_at["gov"] = fixture.clock.value
    return replacement


def _error_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Exactly the ERROR lines: CRITICAL is a distinct verdict here (the
    budget-exhausted report), and a helper that counted both would let a test
    mistake "reported" for "restarted"."""
    return [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]


def _critical_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.CRITICAL]


# --- the shipped bounds ----------------------------------------------------------


def test_u30_escalation_bounds_match_the_authorized_values() -> None:
    """The numbers are the brief's spec, not taste: act 30s after the heal
    (the relay's own stall bound, one segment cadence of slack), 3 restarts per
    rolling hour, then a CRITICAL every 10 minutes and no restart."""
    assert _FREEZE_ESCALATION_AFTER_HEAL_S == 30.0
    assert _FREEZE_ESCALATION_RESTART_BUDGET == 3
    assert _FREEZE_ESCALATION_BUDGET_WINDOW_S == 3600.0
    assert _FREEZE_ESCALATION_EXHAUSTED_LOG_INTERVAL_S == 600.0


# --- the required verdicts -------------------------------------------------------


def test_u30_a_freeze_that_survives_the_self_heal_restarts_the_worker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The incident: heal ran, window still frozen -> ONE ERROR, and the worker is
    terminated so the ordinary relaunch owns it."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)

    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 118.3
    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        fixture.daemon._poll_freeze_escalation("gov")

    assert worker.terminated
    assert fixture.relay.stopped == []
    errors = _error_lines(caplog)
    assert len(errors) == 1
    message = errors[0]
    assert "gov" in message
    assert "148.3s" in message  # the MEASURED freeze, not the constant
    assert "restart 1 of at most 3" in message


def test_u30_the_escalation_does_not_stop_the_relay_child_itself(tmp_path: Path) -> None:
    """The escalation restarts the WORKER and touches no relay child ITSELF.

    The self-heal this escalation escalates has already replaced that child (the
    age of the replacement is what ``heal_frozen_seconds`` measures), and in both
    live incidents the fresh child wrote nothing either, so a child that stopped
    writing while its upstream stopped feeding it is not evidence about the
    child. Restarting the relay here would also spend the channel's one bounded
    move on the half of the two-step failure that has not been shown to be at
    fault. This asserts the call site directly rather than trusting that some
    older test continues to cover it.

    READ THE ASSERTION NARROWLY -- the relay is NOT left alone end to end. This
    test's ``fixture.relay`` is a double, so all it can show is what
    ``_restart_frozen_channel`` does on its own. On the merged beta10 line the
    escalation is followed, on the next tick, by the ordinary crashed-encoder
    relaunch, and that relaunch reaches ``_start`` with the worker dead ->
    ``apply(..., new_session=True)`` -> U21's ``_drop_channel_relays`` discards
    the channel's ``_Relay`` record and spawns a fresh child. The replacement
    therefore gets a fresh one-shot ``heal_attempted`` latch, and the frozen
    playlist re-arms one further heal per incarnation. What keeps that bounded
    is the rolling-hour restart budget below (3/hour), NOT the heal latch.
    ``tests/egress/test_hls_relay_progress.py::test_daemon_tick_sequence_with_escalation_is_bounded_not_a_storm``
    is the test that pins the merged-line sequence; its sibling
    ``..._no_restart_storm_with_frozen_playlist`` pins the latch in isolation,
    with ``_poll_freeze_escalation`` switched off.
    """
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0

    fixture.daemon._poll_freeze_escalation("gov")

    assert worker.terminated
    assert fixture.relay.stopped == []


def test_u30_a_freeze_the_self_heal_actually_cured_is_never_escalated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative case: the heal worked, so the signal reports no failed heal
    (``None``) and nothing is touched -- no ERROR, no relay teardown, no kill."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)

    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        fixture.daemon._poll_freeze_escalation("gov")

    assert not worker.terminated
    assert fixture.relay.stopped == []
    assert not _error_lines(caplog)
    assert fixture.relay.frozen_queries == [("gov", fixture.clock.value)]


def test_u30_with_no_relay_tracked_the_freezing_is_not_judged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No relay in play (no hls sink, or none started) means no heal can have
    failed, so a worker must never be restarted on this signal alone."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)

    fixture.relay.alive = False
    fixture.relay.frozen = None
    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        fixture.daemon._poll_freeze_escalation("gov")

    assert not worker.terminated
    assert not _error_lines(caplog)


def test_u30_a_settled_channel_is_judged_only_in_a_settled_state(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """STARTING, TRANSITIONING and DRAINING are never judged, however frozen the
    window looks -- TRANSITIONING is exactly when the U30 freeze happens, and it
    is also when a legitimate rebase makes the window momentarily stop moving."""
    for state in ("STARTING", "TRANSITIONING", "DRAINING", "STOPPING", "ERROR", "STOPPED"):
        fixture = _freeze_fixture(tmp_path / state.lower())
        worker = _started_on_air(fixture)
        _force_state(fixture, state)
        if state == "DRAINING":
            fixture.daemon._draining_channels.add("gov")

        with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
            fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S * 10.0
            fixture.daemon._poll_freeze_escalation("gov")

        assert not worker.terminated, state
        assert fixture.relay.stopped == [], state
        assert not _error_lines(caplog), state
        assert fixture.relay.frozen_queries == [], state


def test_u30_fallback_slate_is_judged(tmp_path: Path) -> None:
    """FALLBACK_SLATE IS judged: the channel is delivering a settled program (a
    slate), residents see it, and U16 gates on it for the same reason."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)
    _force_state(fixture, "FALLBACK_SLATE")
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S

    fixture.daemon._poll_freeze_escalation("gov")

    assert worker.terminated


def test_u30_just_under_the_bound_is_not_yet_an_escalation(tmp_path: Path) -> None:
    """The bound is a real wait, not a formality: 29.9s of freeze is not 30."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S - 0.1

    fixture.daemon._poll_freeze_escalation("gov")

    assert not worker.terminated


# --- one escalation per worker, and the budget -----------------------------------


def test_u30_one_restart_per_worker_incarnation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A killed worker is still the daemon's live entry until its exit is
    reaped. Without the pid latch, the frozen window would spend the entire
    hourly budget in a handful of 2s ticks."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 5.0

    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        for _ in range(5):
            fixture.clock.value += 2.0
            fixture.daemon._poll_freeze_escalation("gov")

    assert worker.terminated
    assert fixture.relay.stopped == []
    assert len(_error_lines(caplog)) == 1
    state = fixture.daemon._freeze_escalation["gov"]
    assert len(state.restarted_at) == 1


def test_u30_the_escalation_line_names_the_budget_left(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The single ERROR line IS the operator's notification, so it carries the
    three facts the brief names: the channel, how long the window has been
    frozen, and the budget LEFT. Naming only what has been spent ("restart 1 of
    at most 3") makes the reader do the subtraction at the exact moment they
    are deciding whether to intervene by hand."""
    fixture = _freeze_fixture(tmp_path)
    _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 4.0

    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        fixture.daemon._poll_freeze_escalation("gov")

    (line,) = _error_lines(caplog)
    assert "channel gov" in line
    assert "still frozen 34.0s after the relay self-heal" in line
    assert f"restart 1 of at most {_FREEZE_ESCALATION_RESTART_BUDGET} in the last hour" in line
    assert f"({_FREEZE_ESCALATION_RESTART_BUDGET - 1} left in this hour)" in line


def test_u30_a_new_worker_incarnation_may_be_escalated_again(tmp_path: Path) -> None:
    """After the restart the episode is over: if the replacement worker's window
    freezes after its own heal, it is judged on its own evidence."""
    fixture = _freeze_fixture(tmp_path)
    first = _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0
    fixture.daemon._poll_freeze_escalation("gov")
    assert first.terminated

    # The relaunch replaced the worker; the frozen window is now a NEW episode.
    second = _swap_worker(fixture, pid=5151)
    fixture.clock.value += 60.0
    fixture.daemon._poll_freeze_escalation("gov")

    assert second.terminated
    assert fixture.daemon._freeze_escalation["gov"].restarted_at != []


def test_u30_the_budget_is_exhausted_after_three_restarts_then_critical(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Three restarts in the rolling hour, then the channel is REPORTED and not
    restarted again. The fourth verdict must be a CRITICAL and must leave the
    worker alone -- a station otherwise on air is worse off in a restart loop
    than with one channel an operator has been told about."""
    fixture = _freeze_fixture(tmp_path)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0

    # The deltas are counted rather than ``caplog.clear()``-ed: the assertion
    # "the fourth verdict logged NO error line" is about what the fourth poll
    # emitted, and a running count states that directly.
    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        for index in range(_FREEZE_ESCALATION_RESTART_BUDGET):
            worker = _swap_worker(fixture, pid=6000 + index) if index else _started_on_air(fixture)
            fixture.clock.value += 1.0
            fixture.daemon._poll_freeze_escalation("gov")
            assert worker.terminated, index
        assert len(_error_lines(caplog)) == _FREEZE_ESCALATION_RESTART_BUDGET

        fourth = _swap_worker(fixture, pid=7000)
        errors_before = len(_error_lines(caplog))
        criticals_before = len(_critical_lines(caplog))
        fixture.clock.value += 1.0
        fixture.daemon._poll_freeze_escalation("gov")

        assert len(_error_lines(caplog)) == errors_before
        assert len(_critical_lines(caplog)) == criticals_before + 1
        critical = _critical_lines(caplog)[-1]

        # ...and it keeps being reported, throttled, not once per tick.
        reported = len(_critical_lines(caplog))
        fixture.clock.value += 2.0
        fixture.daemon._poll_freeze_escalation("gov")
        assert len(_critical_lines(caplog)) == reported, "must be throttled, not per-tick"
        fixture.clock.value += _FREEZE_ESCALATION_EXHAUSTED_LOG_INTERVAL_S
        fixture.daemon._poll_freeze_escalation("gov")
        assert len(_critical_lines(caplog)) == reported + 1

    assert not fourth.terminated
    assert fixture.relay.stopped == []
    assert "gov" in critical
    assert "budget exhausted" in critical
    assert "NOT restarting the worker again" in critical


def test_u30_the_budget_window_rolls_so_an_old_restart_does_not_linger(
    tmp_path: Path,
) -> None:
    """The budget is a ROLLING hour, not a lifetime cap: a channel that froze
    once an hour ago must still be recoverable now."""
    fixture = _freeze_fixture(tmp_path)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0

    for index in range(_FREEZE_ESCALATION_RESTART_BUDGET):
        worker = _swap_worker(fixture, pid=8000 + index) if index else _started_on_air(fixture)
        fixture.clock.value += 1.0
        fixture.daemon._poll_freeze_escalation("gov")
        assert worker.terminated, index

    fixture.clock.value += _FREEZE_ESCALATION_BUDGET_WINDOW_S + 1.0
    after_window = _swap_worker(fixture, pid=9000)
    fixture.daemon._poll_freeze_escalation("gov")

    assert after_window.terminated


def test_u30_a_stopped_channel_drops_its_budget_bookkeeping(tmp_path: Path) -> None:
    """A channel with no live worker entry has nothing to restart, and must not
    carry a stale budget into its next start."""
    fixture = _freeze_fixture(tmp_path)
    _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0
    fixture.daemon._poll_freeze_escalation("gov")
    assert fixture.daemon._freeze_escalation["gov"].restarted_at != []

    del fixture.daemon._processes["gov"]
    fixture.daemon._poll_freeze_escalation("gov")

    assert "gov" not in fixture.daemon._freeze_escalation


def test_u30_the_restart_goes_through_the_ordinary_crash_relaunch_path(
    tmp_path: Path,
) -> None:
    """The escalation must NOT invent a private restart route. Terminating the
    worker without recording it in ``_reload_kills`` is what makes its exit an
    ordinary non-zero exit that ``_poll_process`` hands to the crash-relaunch
    path (with its own back-off and accounting) instead of preserving a pending
    reload this guard never intended."""
    fixture = _freeze_fixture(tmp_path)
    _started_on_air(fixture)
    fixture.relay.frozen = _FREEZE_ESCALATION_AFTER_HEAL_S + 1.0

    fixture.daemon._poll_freeze_escalation("gov")

    assert "gov" not in fixture.daemon._reload_kills
    assert fixture.daemon._pending_reloads.get("gov") is None


def test_u30_a_supervisor_without_the_signal_is_not_applicable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Seam discipline, matching ``_poll_hls_relay``: a supervisor double (or an
    older wiring) that predates this signal must read as "not applicable",
    never as an exception on every tick of every channel."""
    fixture = _freeze_fixture(tmp_path)
    worker = _started_on_air(fixture)

    relay = _NoFreezeSignalRelay()
    fixture.daemon._hls_relay = relay
    with caplog.at_level(logging.ERROR, logger=_DAEMON_LOGGER):
        fixture.daemon._poll_freeze_escalation("gov")

    assert not worker.terminated
    assert not _error_lines(caplog)
    assert relay.stopped == []


class _NoFreezeSignalRelay(_ScriptedRelay):
    """A relay supervisor that cannot answer the freeze question at all."""

    heal_frozen_seconds = None  # type: ignore[assignment]


# --- the relay-side measurement --------------------------------------------------


class _FakeRelayProcess:
    """A relay ffmpeg child double: alive until terminated."""

    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.returncode = 1
        return 1


def _relay_supervisor(clock: _FakeClock, procs: list[_FakeRelayProcess]) -> HlsRelaySupervisor:
    def starter(_args: Sequence[str]) -> _FakeRelayProcess:
        process = _FakeRelayProcess(pid=900 + len(procs))
        procs.append(process)
        return process

    supervisor = HlsRelaySupervisor(
        starter=starter,
        stall_bound_s=0.0,
        segment_probe=lambda _path: frozenset({"video", "audio"}),
    )
    supervisor._clock = clock
    return supervisor


def _hls_config(live_dir: Path) -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="slate",
        sinks=[EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir))],
    )


def _heal_once(supervisor: HlsRelaySupervisor, clock: _FakeClock) -> float:
    """Drive a real self-heal through the real supervisor; return its instant."""
    clock.value += 5.0
    healed = supervisor.maybe_self_heal_stalled(
        "gov", now=clock.value, producing=True, startup_grace_s=0.0
    )
    assert healed is True
    return clock.value


def test_u30_heal_frozen_seconds_is_measured_from_the_heal(tmp_path: Path) -> None:
    """The signal's clock is exact, because the heal itself stamps it: none of
    the freeze is guessed from a poll cadence."""
    live_dir = tmp_path / "gov-live"
    _write_playlist(live_dir, segments=("seg000000010.ts",))
    clock = _FakeClock()
    supervisor = _relay_supervisor(clock, [])
    supervisor.apply(_hls_config(live_dir))
    supervisor.note_progress("gov", now=clock.value)

    assert supervisor.heal_frozen_seconds("gov", now=clock.value) is None

    healed_at = _heal_once(supervisor, clock)

    assert supervisor.heal_frozen_seconds("gov", now=healed_at) == 0.0
    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 12.5) == 12.5
    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 148.0) == 148.0


def test_u30_a_cured_window_ends_the_freeze_episode(tmp_path: Path) -> None:
    """The signal must agree with the heal latch: once the served window moves
    past the pre-heal baseline the episode is over and the daemon stops seeing a
    failed heal -- otherwise a long-lived channel would be restarted on a freeze
    that ended minutes ago."""
    live_dir = tmp_path / "gov-live"
    _write_playlist(live_dir, segments=("seg000000010.ts",))
    clock = _FakeClock()
    supervisor = _relay_supervisor(clock, [])
    supervisor.apply(_hls_config(live_dir))
    supervisor.note_progress("gov", now=clock.value)
    healed_at = _heal_once(supervisor, clock)
    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 40.0) == 40.0

    _write_playlist(live_dir, segments=("seg000000011.ts", "seg000000012.ts"))
    supervisor.note_progress("gov", now=healed_at + 41.0)

    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 60.0) is None


def test_u30_a_frozen_window_at_the_same_baseline_is_still_frozen(tmp_path: Path) -> None:
    """The inverse of the case above, and the one the live incident was: the
    window on disk is UNCHANGED, so nothing about it counts as progress and the
    freeze keeps being reported."""
    live_dir = tmp_path / "gov-live"
    _write_playlist(live_dir, segments=("seg000000010.ts",))
    clock = _FakeClock()
    supervisor = _relay_supervisor(clock, [])
    supervisor.apply(_hls_config(live_dir))
    supervisor.note_progress("gov", now=clock.value)
    healed_at = _heal_once(supervisor, clock)

    for step in (1.0, 5.0, 30.0):
        supervisor.note_progress("gov", now=healed_at + step)
    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 40.0) == 40.0


def test_u30_heal_frozen_seconds_is_none_without_a_tracked_relay(tmp_path: Path) -> None:
    """No relay tracked: not applicable. Never a freeze, never an escalation."""
    clock = _FakeClock()
    supervisor = _relay_supervisor(clock, [])

    assert supervisor.heal_frozen_seconds("gov", now=clock.value) is None


def test_u30_a_relay_that_exited_after_its_heal_cannot_hold_a_freeze_open(
    tmp_path: Path,
) -> None:
    """Dead children contribute nothing here (that is ``is_alive``'s signal):
    a child that exited is recovered by the relay path, not escalated as a
    freeze of a window nobody is serving."""
    live_dir = tmp_path / "gov-live"
    _write_playlist(live_dir, segments=("seg000000010.ts",))
    clock = _FakeClock()
    procs: list[_FakeRelayProcess] = []
    supervisor = _relay_supervisor(clock, procs)
    supervisor.apply(_hls_config(live_dir))
    supervisor.note_progress("gov", now=clock.value)
    healed_at = _heal_once(supervisor, clock)
    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 60.0) == 60.0

    procs[-1].returncode = 1

    assert supervisor.heal_frozen_seconds("gov", now=healed_at + 61.0) is None
