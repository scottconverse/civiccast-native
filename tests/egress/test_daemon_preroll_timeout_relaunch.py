# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 82 (sandbox run 13 evidence): a fresh GStreamer worker under CPU load can
legitimately take longer than a few seconds to reach PLAYING. The engine now bounds
that wait at 30s (default) and exits with the distinct
``civiccast.egress.gst.exit_codes.GST_PREROLL_TIMEOUT_EXIT_CODE`` instead of a
generic non-zero code when it's exceeded (see
``tests/egress/test_gst_engine_preroll_timeout.py`` for the engine side).

This file covers the DAEMON side of the contract: ``EgressDaemon._relaunch_after_crash``
still relaunches a preroll-timeout exit through the exact same back-off path as any
other crash (never excluded from retry), but must not advance the crash-loop streak
(``_restart_streak`` — the counter that eventually forces fallback slate past
``_LIVE_SOURCE_FAILURE_FALLBACK_STREAK``) more than once per 60s. An ORDINARY
non-zero exit is unaffected and still increments on every single crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.gst.exit_codes import GST_PREROLL_TIMEOUT_EXIT_CODE
from civiccast.egress.models import (
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.store import InMemoryEgressStore


class _FakeProcess:
    def __init__(self, *, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0


class _WorkerStrategy:
    """A GStreamer-named strategy that hands out fake processes in order,
    mirroring ``tests/egress/test_gst_worker_exit_diagnosis.py``'s fixture."""

    name = "gstreamer-playout-worker"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess], stderr_text: str) -> None:
        self._processes = list(processes)
        self._stderr_text = stderr_text

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        log_dir = request.work_dir / request.channel_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "gst-worker.stderr.log"
        stderr_path.write_text(self._stderr_text, encoding="utf-8")
        return EncoderStartResult(
            process=process,
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=log_dir / "gst-worker.stdout.log",
            stderr_path=stderr_path,
            args=("worker",),
        )

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def reload_content(  # pragma: no cover
        self, channel_id: str, work_dir: Path, request: EncoderStartRequest, **_kwargs
    ) -> bool:
        return False


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


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
        issued_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id="cmd-start",
    )


def _daemon_with_fake_clock(
    tmp_path: Path, *, processes: list[_FakeProcess], clock: dict[str, float]
) -> EgressDaemon:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_start_command())
    strategy = _WorkerStrategy(
        processes,
        stderr_text=(
            "CTRL preroll: worker exiting -- pipeline did not reach PLAYING "
            "within 30.0s (get_state=async)\n"
        ),
    )
    return EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
        monotonic=lambda: clock["t"],
        # Isolate the preroll-timeout rate limit from the general restart
        # cooldown latch -- 0s means every relaunch attempt is immediately
        # permitted, so only _restart_streak's own logic is under test.
        restart_cooldown_seconds=0.0,
    )


def test_preroll_timeout_exit_is_rate_limited_to_once_per_minute(tmp_path: Path) -> None:
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=100 + i) for i in range(8)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")
    assert state.state == "ON_AIR"

    # First preroll-timeout crash: the streak starts at 1 like any first crash.
    # _poll_process always pops the just-exited process BEFORE calling
    # _relaunch_after_crash (daemon.py's real caller) -- simulate that here so
    # _start's "is a process already tracked as running?" guard doesn't treat
    # the previous (already-dead) fake process as still alive and skip the
    # actual relaunch.
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    # A second, and a third, preroll-timeout crash inside the 60s window: the
    # worker still gets relaunched (the retry itself is never skipped) but the
    # streak must NOT advance again.
    clock["t"] += 10.0
    # _poll_process always pops the just-exited process BEFORE calling
    # _relaunch_after_crash (daemon.py's real caller) -- simulate that here so
    # _start's "is a process already tracked as running?" guard doesn't treat
    # the previous (already-dead) fake process as still alive and skip the
    # actual relaunch.
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 45.0  # 55s since the first increment -- still inside the 60s window
    # _poll_process always pops the just-exited process BEFORE calling
    # _relaunch_after_crash (daemon.py's real caller) -- simulate that here so
    # _start's "is a process already tracked as running?" guard doesn't treat
    # the previous (already-dead) fake process as still alive and skip the
    # actual relaunch.
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    # Past the 60s window since the first (and only, so far) increment: the
    # streak is allowed to advance again.
    clock["t"] += 10.0  # 65s since the first increment
    # _poll_process always pops the just-exited process BEFORE calling
    # _relaunch_after_crash (daemon.py's real caller) -- simulate that here so
    # _start's "is a process already tracked as running?" guard doesn't treat
    # the previous (already-dead) fake process as still alive and skip the
    # actual relaunch.
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 2


def test_preroll_timeout_still_relaunches_every_time_despite_the_rate_limit(
    tmp_path: Path,
) -> None:
    """The rate limit caps the COUNTER, never the retry itself -- a preroll-timeout
    exit always gets a fresh worker started with the existing backoff, exactly like
    any other crash."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=200 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1  # consumes process 0 (the initial start)
    state = daemon._store.read_state("gov")

    for _ in range(3):
        clock["t"] += 1.0
        daemon._processes.pop("gov", None)  # mirrors _poll_process's own pop
        daemon._relaunch_after_crash(
            "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
        )

    # Every call reached _begin_relaunch -> _start, so every fake process was
    # actually consumed (the strategy pops one per start; an empty list would
    # have raised IndexError from the strategy, which it did not) -- 1 initial
    # start + 3 relaunches == all 4 fake processes.
    assert daemon._encoder_strategy._processes == []  # type: ignore[attr-defined]
    # _start() completes synchronously against this fake strategy/process (no
    # separate poll step needed to confirm it), so the channel lands straight
    # back on ON_AIR -- the relaunch genuinely happened each time, which is
    # the point of this test, not any particular transitional state label.
    assert daemon._store.read_state("gov").state == "ON_AIR"


def test_ordinary_crash_exit_code_is_not_rate_limited(tmp_path: Path) -> None:
    """Contrast case: an exit code OTHER than GST_PREROLL_TIMEOUT_EXIT_CODE (an
    ordinary crash) must keep incrementing the streak on every single relaunch --
    the rate limit is specific to the preroll-timeout exit reason."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=300 + i) for i in range(6)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    for expected_streak in (1, 2, 3, 4):
        clock["t"] += 1.0  # well inside any cooldown window -- must not matter here
        daemon._processes.pop("gov", None)  # mirrors _poll_process's own pop
        daemon._relaunch_after_crash("gov", state, uptime=None, returncode=1)
        assert daemon._restart_streak["gov"] == expected_streak


def test_preroll_timeout_rate_limit_does_not_apply_across_different_channels(
    tmp_path: Path,
) -> None:
    """The rate-limit clock is per-channel (keyed in a dict), never global --
    two channels hitting preroll timeouts at the same instant must each get
    their own first free increment."""
    clock = {"t": 0.0}
    store = InMemoryEgressStore()
    for channel_id in ("gov", "parks"):
        store.upsert_config(
            EgressConfig(
                channel_id=channel_id,
                enabled=True,
                slate_message="CivicCast is preparing the channel.",
                sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
            )
        )
        store.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action="start",
                issued_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
                issued_by="operator",
                command_id=f"cmd-start-{channel_id}",
            )
        )
    processes = [_FakeProcess(pid=400 + i) for i in range(4)]
    strategy = _WorkerStrategy(
        processes, stderr_text="CTRL preroll: worker exiting -- pipeline did not reach PLAYING\n"
    )
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
        monotonic=lambda: clock["t"],
        restart_cooldown_seconds=0.0,
    )
    assert daemon.process_once("gov") == 1
    assert daemon.process_once("parks") == 1
    gov_state = daemon._store.read_state("gov")
    parks_state = daemon._store.read_state("parks")

    daemon._processes.pop("gov", None)  # mirrors _poll_process's own pop
    daemon._relaunch_after_crash(
        "gov", gov_state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    daemon._processes.pop("parks", None)  # mirrors _poll_process's own pop
    daemon._relaunch_after_crash(
        "parks", parks_state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )

    assert daemon._restart_streak["gov"] == 1
    assert daemon._restart_streak["parks"] == 1


def test_reset_restart_tracking_clears_the_preroll_timeout_rate_limit_state(
    tmp_path: Path,
) -> None:
    """A channel that reaches a good terminal state (operator stop, clean exit,
    healthy uptime) must not carry stale preroll-timeout rate-limit bookkeeping
    into its next, unrelated crash streak."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=500 + i) for i in range(3)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")
    # _poll_process always pops the just-exited process BEFORE calling
    # _relaunch_after_crash (daemon.py's real caller) -- simulate that here so
    # _start's "is a process already tracked as running?" guard doesn't treat
    # the previous (already-dead) fake process as still alive and skip the
    # actual relaunch.
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert "gov" in daemon._preroll_timeout_streak_incr_at

    daemon._reset_restart_tracking("gov")

    assert "gov" not in daemon._preroll_timeout_streak_incr_at
    assert "gov" not in daemon._restart_streak
