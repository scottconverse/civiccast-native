# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""RAT-004: EgressDaemon.stop_all_channels is the missing graceful drain-all owner.

Ground truth for "drained" is the observed process exit (poll()), never an
acknowledgement — these tests exercise that contract directly with fake
processes that separate "asked to stop" (terminate() called) from "actually
exited" (poll() returns non-None), and a fake clock/sleep pair so the
deadline-wait loop is deterministic and fast (no real wall-clock waiting).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import ChannelDrainOutcome, DrainResult, EgressDaemon
from civiccast.egress.encoder_strategy import ConcatEncoderStrategy
from civiccast.egress.models import (
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.store import InMemoryEgressStore


class _FakeClock:
    """An injectable monotonic clock + sleep pair for a deterministic, fast
    deadline-wait loop — no real time.sleep() is ever invoked."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start
        self.sleep_calls = 0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1
        self.t += seconds


class _DrainProcess:
    """A fake subprocess whose exit is independent of terminate()/any ack.

    ``exit_after_polls`` controls how many poll() calls occur before the
    process reports exited — this stands in for "the worker actually died",
    which is the only thing stop_all_channels is allowed to trust.
    """

    def __init__(self, *, pid: int, exit_after_polls: int | None = None) -> None:
        self.pid = pid
        self.exit_after_polls = exit_after_polls
        self.poll_calls = 0
        self.terminate_calls = 0
        self.returncode: int | None = None

    def poll(self) -> int | None:
        self.poll_calls += 1
        if self.exit_after_polls is not None and self.poll_calls >= self.exit_after_polls:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1


class _RecordingStrategy(ConcatEncoderStrategy):
    """The default concat strategy plus a recording ``send_command`` seam.

    RAT-004's graceful drain must send the terminal ``"stop"`` control command
    to the worker BEFORE any force-terminate; this fake records every such
    command (channel_id, text) so a test can assert the terminal verb was sent
    per channel, and ``send_returns`` models a live control channel (True) vs a
    lost/dropped ack (False) — the drain must still trust the OBSERVED process
    exit, never this return value, so a False-returning send still drains a
    worker that exits.
    """

    def __init__(self, *, send_returns: bool = True) -> None:
        self.send_returns = send_returns
        self.commands: list[tuple[str, str]] = []

    def send_command(self, work_dir: Path, channel_id: str, text: str) -> bool:
        self.commands.append((channel_id, text))
        return self.send_returns


def _config(channel_id: str) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _command(channel_id: str) -> EgressCommand:
    return EgressCommand(
        channel_id=channel_id,
        action="start",
        issued_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id=f"cmd-start-{channel_id}",
    )


def _source_plan(tmp_path: Path, channel_id: str) -> EgressSourcePlan:
    source = tmp_path / f"{channel_id}.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=1,
                source_ref="asset-council",
            )
        ],
    )


def _daemon_with_live_channels(
    tmp_path: Path,
    channel_ids: list[str],
    processes: dict[str, _DrainProcess],
    *,
    clock: _FakeClock | None = None,
    strategy: ConcatEncoderStrategy | None = None,
) -> tuple[EgressDaemon, InMemoryEgressStore]:
    """A daemon with a real live process tracked per channel_id (via the
    normal start path — process_once — not by poking private state)."""

    store = InMemoryEgressStore()
    for channel_id in channel_ids:
        store.upsert_config(_config(channel_id))
        store.enqueue_command(_command(channel_id))

    clock = clock or _FakeClock()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: _source_plan(tmp_path, channel_id),
        ffmpeg_starter=lambda args: processes[_channel_id_from_out_path(args)],
        monotonic=clock.now,
        sleep=clock.sleep,
        encoder_strategy=strategy,
    )
    for channel_id in channel_ids:
        daemon.process_once(channel_id)
    return daemon, store


def _channel_id_from_out_path(args: list[str]) -> str:
    # The last arg is the sink URI "build/<channel_id>.ts" per _config() above.
    out_path = args[-1]
    return Path(out_path).stem


def test_stop_all_channels_zero_channels_is_clean_noop(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path, "gov"),
    )

    result = daemon.stop_all_channels(deadline_seconds=5.0)

    assert result == DrainResult(outcomes=())


def test_stop_all_channels_drains_multiple_channels_via_observed_exit(tmp_path: Path) -> None:
    """RAT-004: every active channel gets the terminal graceful ``"stop"``
    control command, and each is reported drained once its process is OBSERVED
    to exit (poll()) — WITHOUT a force-terminate, because it drained cleanly
    inside the deadline.

    REGRESSION (CC-WS5-004): the pre-fix drain force-terminated the worker
    immediately in ``_stop`` (before it ever received its terminal protocol
    action), so ``terminate_calls`` was 1 and no ``"stop"`` command was sent.
    """

    processes = {
        # exit_after_polls=2: the first poll() is stop_all_channels' initial
        # liveness check (still alive -> issues the stop); the process exits
        # only on the SECOND poll, inside the deadline-wait loop -- proving
        # the outcome is driven by the observed exit, not the initial check.
        "gov": _DrainProcess(pid=1, exit_after_polls=2),
        "edu": _DrainProcess(pid=2, exit_after_polls=2),
        "pub": _DrainProcess(pid=3, exit_after_polls=2),
    }
    strategy = _RecordingStrategy()
    daemon, store = _daemon_with_live_channels(
        tmp_path, ["gov", "edu", "pub"], processes, strategy=strategy
    )

    result = daemon.stop_all_channels(deadline_seconds=5.0)

    assert set(result.outcomes) == {
        ChannelDrainOutcome("gov", "drained"),
        ChannelDrainOutcome("edu", "drained"),
        ChannelDrainOutcome("pub", "drained"),
    }
    # The terminal graceful command reached EVERY live worker exactly once...
    assert sorted(strategy.commands) == [("edu", "stop"), ("gov", "stop"), ("pub", "stop")]
    for channel_id, process in processes.items():
        # ...and NOT ONE cleanly-draining worker was force-terminated.
        assert process.terminate_calls == 0, channel_id
        state = store.read_state(channel_id)
        assert state is not None
        assert state.state == "DRAINING", channel_id


def test_stop_all_channels_lost_ack_but_process_exits_is_drained(tmp_path: Path) -> None:
    """A worker that never acknowledges the stop but DOES exit is 'drained' —
    exit is ground truth, not the (absent) acknowledgement.

    FALSIFICATION: if stop_all_channels required an ack to report 'drained',
    this process (which never sends one — there is no ack concept below the
    daemon at all, only observed poll()) would incorrectly report as hung.
    """

    process = _DrainProcess(pid=1, exit_after_polls=3)
    strategy = _RecordingStrategy(send_returns=False)  # control-channel ack lost/dropped
    daemon, _store = _daemon_with_live_channels(
        tmp_path, ["gov"], {"gov": process}, strategy=strategy
    )

    result = daemon.stop_all_channels(deadline_seconds=5.0)

    assert result == DrainResult(outcomes=(ChannelDrainOutcome("gov", "drained"),))
    assert strategy.commands == [("gov", "stop")]  # the terminal command was still sent
    assert process.terminate_calls == 0  # never escalated — it exited in time on its own


def test_stop_all_channels_hung_worker_is_killed_after_deadline(tmp_path: Path) -> None:
    """A worker that neither acks nor exits within the deadline is escalated
    to the existing _process_terminate kill and reported killed_after_deadline
    — and the call returns instead of hanging.

    FALSIFICATION: if stop_all_channels only issued the one graceful stop and
    trusted it (no deadline wait, no escalation), this process — whose poll()
    always returns None — would report 'drained' forever and the call would
    never return within the test's timeout; the fake clock/sleep pair makes
    the deadline expire deterministically without a real wall-clock wait.
    """

    process = _DrainProcess(pid=1, exit_after_polls=None)  # never exits
    strategy = _RecordingStrategy()
    daemon, _store = _daemon_with_live_channels(
        tmp_path, ["gov"], {"gov": process}, strategy=strategy
    )

    result = daemon.stop_all_channels(deadline_seconds=1.0)

    assert result == DrainResult(outcomes=(ChannelDrainOutcome("gov", "killed_after_deadline"),))
    assert strategy.commands == [("gov", "stop")]  # graceful command issued first...
    # ...and the ONLY force-terminate is the post-deadline escalation (the drain
    # itself no longer kills up front — CC-WS5-004).
    assert process.terminate_calls == 1


def test_stop_all_channels_already_gone_channel_reported_without_double_stop(
    tmp_path: Path,
) -> None:
    """A channel whose process already exited before the drain even asked is
    reported already_gone — no redundant _stop is issued (idempotency)."""

    process = _DrainProcess(pid=1, exit_after_polls=None)
    process.returncode = 0  # already exited by the time the drain runs
    strategy = _RecordingStrategy()
    daemon, store = _daemon_with_live_channels(
        tmp_path, ["gov"], {"gov": process}, strategy=strategy
    )

    result = daemon.stop_all_channels(deadline_seconds=5.0)

    assert result == DrainResult(outcomes=(ChannelDrainOutcome("gov", "already_gone"),))
    assert process.terminate_calls == 0
    assert strategy.commands == []  # no redundant terminal command for an already-gone worker
    # DRAINING was never written for an already-gone channel — no redundant stop.
    state = store.read_state("gov")
    assert state is not None
    assert state.state != "DRAINING"


def test_direct_operator_stop_force_terminates_without_graceful_command(tmp_path: Path) -> None:
    """A DIRECT operator stop (``_stop(draining=False)``) is NOT the RAT-004
    drain — it has no deadline/escalation loop to reap a hung worker, so it
    keeps its immediate force-terminate and does NOT send a graceful ``"stop"``
    control command (which could hang on a dead control channel). This pins the
    behavior the CC-WS5-004 fix must leave UNCHANGED.
    """

    process = _DrainProcess(pid=1, exit_after_polls=None)
    strategy = _RecordingStrategy()
    daemon, store = _daemon_with_live_channels(
        tmp_path, ["gov"], {"gov": process}, strategy=strategy
    )

    daemon._stop("gov", draining=False)

    assert process.terminate_calls == 1  # force-terminated immediately, as before
    assert strategy.commands == []  # no graceful terminal command on the direct-stop path
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "STOPPING"


def test_stop_all_channels_is_idempotent_on_repeated_call(tmp_path: Path) -> None:
    process = _DrainProcess(pid=1, exit_after_polls=2)
    daemon, _store = _daemon_with_live_channels(tmp_path, ["gov"], {"gov": process})

    first = daemon.stop_all_channels(deadline_seconds=5.0)
    second = daemon.stop_all_channels(deadline_seconds=5.0)

    assert first == DrainResult(outcomes=(ChannelDrainOutcome("gov", "drained"),))
    assert second == DrainResult(outcomes=())  # nothing left tracked — clean no-op
