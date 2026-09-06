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
    tmp_path: Path,
    *,
    processes: list[_FakeProcess],
    clock: dict[str, float],
    with_fallback: bool = False,
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
        # A real fallback provider (not None) is required for
        # _begin_relaunch's force_fallback_slate branch to actually take --
        # the escalation tests below need this wired to prove the channel
        # really lands on FALLBACK_SLATE, not just that the streak counted up.
        fallback_source_provider=(lambda _config: _source_plan(tmp_path))
        if with_fallback
        else None,
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


# --- Round-2 review (Opus, PR #183) -------------------------------------------------


def test_poll_process_plumbs_a_real_returncode_3_into_the_rate_limited_streak(
    tmp_path: Path,
) -> None:
    """Requirement 2: exercise the actual wiring (``_poll_process`` reading
    ``process.poll()`` and threading that returncode into
    ``_relaunch_after_crash``), not a direct call to ``_relaunch_after_crash``
    with a hand-picked ``returncode`` argument like the tests above. Every
    assertion here goes through ``daemon.process_once`` only."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=700 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    assert daemon._store.read_state("gov").state == "ON_AIR"

    # The REAL worker process object the daemon is tracking exits with the
    # REAL preroll-timeout exit code -- nothing hand-constructs the
    # returncode argument from here on; _poll_process reads process.poll()
    # itself and passes it through.
    daemon._processes["gov"].returncode = GST_PREROLL_TIMEOUT_EXIT_CODE
    daemon.process_once("gov")
    assert daemon._restart_streak["gov"] == 1
    assert "gov" in daemon._preroll_timeout_streak_incr_at

    # A second real returncode=3 poll, still inside the 60s rate-limit
    # window: the daemon must still relaunch (a fresh process is tracked)
    # but the streak must NOT advance a second time.
    clock["t"] += 5.0
    daemon._processes["gov"].returncode = GST_PREROLL_TIMEOUT_EXIT_CODE
    daemon.process_once("gov")
    assert daemon._restart_streak["gov"] == 1
    assert daemon._processes["gov"] is not None  # a fresh worker IS running


def _run_sustained_preroll_timeout_cycles(
    daemon: EgressDaemon, clock: dict[str, float], *, spacing_s: float, max_cycles: int
) -> float:
    """Drives 'gov' through repeated real preroll-timeout exits, spaced
    ``spacing_s`` apart on the fake clock (simulating the engine's own
    preroll bound elapsing every single time, worst case), going through
    ``daemon.process_once`` only -- never ``_relaunch_after_crash`` directly.
    Returns the clock time at which the channel first reads FALLBACK_SLATE.
    Raises ``AssertionError`` if it never does within ``max_cycles``."""
    assert daemon.process_once("gov") == 1
    for _ in range(max_cycles):
        clock["t"] += spacing_s
        process = daemon._processes.get("gov")
        assert process is not None, "expected a freshly relaunched worker process"
        process.returncode = GST_PREROLL_TIMEOUT_EXIT_CODE
        daemon.process_once("gov")
        if daemon._store.read_state("gov").state == "FALLBACK_SLATE":
            return clock["t"]
    raise AssertionError(f"channel never reached FALLBACK_SLATE within {max_cycles} cycles")


def test_sustained_preroll_timeouts_at_45s_still_reach_fallback_slate(tmp_path: Path) -> None:
    """Requirement 1's own test: at the new 45s clamp ceiling (the maximum an
    operator can configure via CIVICCAST_GST_PREROLL_TIMEOUT_S), a source that
    NEVER comes up must still eventually escalate to fallback slate -- the
    exact case the BLOCKER fixed (before it, an unclamped >=60s bound made
    every such exit look like a "healthy uptime" and reset the streak on
    every single crash, so escalation NEVER happened: measured 40 relaunches,
    streak stuck at 0)."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=800 + i) for i in range(12)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock, with_fallback=True)

    reached_at = _run_sustained_preroll_timeout_cycles(daemon, clock, spacing_s=45.0, max_cycles=10)

    assert daemon._store.read_state("gov").state == "FALLBACK_SLATE"
    assert daemon._restart_streak["gov"] >= 5
    assert reached_at <= 500.0  # generous -- no tight bound asserted at this spacing


def test_sustained_preroll_timeouts_at_30s_reach_fallback_slate_by_t_le_300s(
    tmp_path: Path,
) -> None:
    """Requirement 4: the whole risk surface, at the engine's DEFAULT 30s
    preroll bound. Consecutive crashes land every 30s, but the streak only
    advances once per 60s rate-limit window, so escalation (streak reaching
    ``_LIVE_SOURCE_FAILURE_FALLBACK_STREAK`` = 5) lands on the 9th crash --
    measured t=270s -- well inside the 300s bound this test asserts."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=900 + i) for i in range(12)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock, with_fallback=True)

    reached_at = _run_sustained_preroll_timeout_cycles(daemon, clock, spacing_s=30.0, max_cycles=10)

    assert daemon._store.read_state("gov").state == "FALLBACK_SLATE"
    assert reached_at <= 300.0


def test_preroll_timeout_streak_is_not_reset_even_at_uptime_above_60s(tmp_path: Path) -> None:
    """Defense-in-depth for the BLOCKER's daemon-side half: even if a caller
    somehow passes ``uptime >= _RESTART_STREAK_RESET_UPTIME_S`` (60s) for a
    preroll-timeout exit -- e.g. a future engine bug, or a value that bypassed
    engine.py's own 45s clamp -- the daemon must NOT treat that as a "healthy
    run" and reset the streak. Only the exit's OWN reason is what disqualifies
    a preroll-timeout exit from the healthy-uptime reset, independent of
    whatever the (informational only) uptime number happens to be."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=1000 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=70.0, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 65.0  # past the 60s rate-limit window -- must advance again
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=70.0, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    # If the healthy-uptime reset wrongly applied here, this would read back
    # to 1 (reset to 0, then incremented) instead of accumulating to 2.
    assert daemon._restart_streak["gov"] == 2
