# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 84 (measured in sandbox run 15, soak-fcfcb81-20260906-183448Z, and in three
seamless-OFF runs): a fresh GStreamer worker can reach PLAYING quickly but still take
longer than the post-first-buffer stall bound to produce its FIRST output buffer under
start-up load. The engine now bounds that separately (``first_output_timeout_s``, 45s
default) and exits with the distinct
``civiccast.egress.gst.exit_codes.GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE`` instead of the
generic post-first-buffer stall reason (see
``tests/egress/test_gst_engine_first_output_timeout.py`` for the engine side).

This file covers the DAEMON side of the contract: ``EgressDaemon._relaunch_after_crash``
treats a ``GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE`` exit exactly like a
``GST_PREROLL_TIMEOUT_EXIT_CODE`` exit (see ``civiccast.egress.daemon._SLOW_START_EXIT_CODES``)
-- it still relaunches through the exact same back-off path as any other crash, but must
not advance the crash-loop streak (``_restart_streak``) more than once per 60s, SHARING
that rate-limit window with any preroll-timeout exits the same channel also hits. An
ORDINARY non-zero exit is unaffected and still increments the streak on every single
crash. Mirrors ``tests/egress/test_daemon_preroll_timeout_relaunch.py``'s core scenarios
(not its full round-2/3/4 regression matrix, which is preroll-timeout-specific
plumbing already covered there)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.gst.exit_codes import (
    GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE,
    GST_PREROLL_TIMEOUT_EXIT_CODE,
)
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
    """A GStreamer-named strategy that hands out fake processes in order.
    Mirrors ``tests/egress/test_daemon_preroll_timeout_relaunch.py``'s own
    fixture (append-mode stderr log, matching the real launcher)."""

    name = "gstreamer-playout-worker"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess], stderr_text: str = "") -> None:
        self._processes = list(processes)
        self._stderr_text = stderr_text

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        log_dir = request.work_dir / request.channel_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "gst-worker.stderr.log"
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write(self._stderr_text)
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
        issued_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
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
            "CTRL first-output: no output within 45s of PLAYING - quitting for daemon restart\n"
        ),
    )
    return EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=(lambda _config: _source_plan(tmp_path))
        if with_fallback
        else None,
        encoder_strategy=strategy,
        monotonic=lambda: clock["t"],
        # Isolate the slow-start rate limit from the general restart cooldown
        # latch -- 0s means every relaunch attempt is immediately permitted,
        # so only _restart_streak's own logic is under test.
        restart_cooldown_seconds=0.0,
    )


def test_first_output_timeout_exit_is_rate_limited_to_once_per_minute(tmp_path: Path) -> None:
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2100 + i) for i in range(8)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")
    assert state.state == "ON_AIR"

    daemon._processes.pop("gov", None)  # mirrors _poll_process's own pop
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 10.0
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1  # still inside the 60s window

    clock["t"] += 55.0  # 65s since the first increment
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 2


def test_first_output_timeout_still_relaunches_every_time_despite_the_rate_limit(
    tmp_path: Path,
) -> None:
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2200 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    for _ in range(3):
        clock["t"] += 1.0
        daemon._processes.pop("gov", None)
        daemon._relaunch_after_crash(
            "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
        )

    assert daemon._encoder_strategy._processes == []  # type: ignore[attr-defined]
    assert daemon._store.read_state("gov").state == "ON_AIR"


def test_ordinary_crash_exit_code_is_not_rate_limited_alongside_first_output_timeouts(
    tmp_path: Path,
) -> None:
    """Contrast case: an exit code OTHER than either slow-start reason (an
    ordinary crash) must keep incrementing the streak on every single
    relaunch."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2300 + i) for i in range(6)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    for expected_streak in (1, 2, 3, 4):
        clock["t"] += 1.0
        daemon._processes.pop("gov", None)
        daemon._relaunch_after_crash("gov", state, uptime=None, returncode=1)
        assert daemon._restart_streak["gov"] == expected_streak


def test_preroll_timeout_and_first_output_timeout_share_one_rate_limit_window(
    tmp_path: Path,
) -> None:
    """The two slow-start reasons are the SAME "was there a recent slow-start
    streak increment" clock (``_SLOW_START_EXIT_CODES``) -- a channel
    alternating between them must not get twice the retry budget."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2400 + i) for i in range(6)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_PREROLL_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 5.0
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    # Still inside the 60s window opened by the PREROLL-timeout increment --
    # the FIRST-OUTPUT-timeout exit must not get its own separate increment.
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 60.0
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 2


def test_first_output_timeout_is_exempt_from_the_healthy_uptime_reset(tmp_path: Path) -> None:
    """Mirrors the preroll-timeout BLOCKER fix: a first-output-timeout exit's
    ``uptime`` is not evidence of a healthy run (it is simply how long the
    doomed wait for a first buffer took) -- applying the healthy-uptime reset
    to it would silently defeat crash-loop escalation for a source that
    never comes up."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2500 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=70.0, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert daemon._restart_streak["gov"] == 1

    clock["t"] += 65.0  # past the 60s rate-limit window -- must advance again
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=70.0, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    # If the healthy-uptime reset wrongly applied, this would read back to 1
    # (reset to 0, then incremented) instead of accumulating to 2.
    assert daemon._restart_streak["gov"] == 2


def test_reset_restart_tracking_clears_the_shared_slow_start_rate_limit_state(
    tmp_path: Path,
) -> None:
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2600 + i) for i in range(3)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")
    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    )
    assert "gov" in daemon._preroll_timeout_streak_incr_at

    daemon._reset_restart_tracking("gov")

    assert "gov" not in daemon._preroll_timeout_streak_incr_at
    assert "gov" not in daemon._restart_streak


def test_poll_process_plumbs_a_real_first_output_timeout_returncode(tmp_path: Path) -> None:
    """Requirement mirrors the preroll-timeout equivalent: exercise the
    actual wiring (``_poll_process`` reading ``process.poll()`` and threading
    that returncode into ``_relaunch_after_crash``), not a direct call with a
    hand-picked ``returncode`` argument."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2700 + i) for i in range(4)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock)

    assert daemon.process_once("gov") == 1
    assert daemon._store.read_state("gov").state == "ON_AIR"

    daemon._processes["gov"].returncode = GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    daemon.process_once("gov")
    assert daemon._restart_streak["gov"] == 1
    assert "gov" in daemon._preroll_timeout_streak_incr_at

    clock["t"] += 5.0
    daemon._processes["gov"].returncode = GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
    daemon.process_once("gov")
    assert daemon._restart_streak["gov"] == 1
    assert daemon._processes["gov"] is not None  # a fresh worker IS running


def _run_sustained_first_output_timeout_cycles(
    daemon: EgressDaemon, clock: dict[str, float], *, spacing_s: float, max_cycles: int
) -> float:
    assert daemon.process_once("gov") == 1
    for _ in range(max_cycles):
        clock["t"] += spacing_s
        process = daemon._processes.get("gov")
        assert process is not None, "expected a freshly relaunched worker process"
        process.returncode = GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE
        daemon.process_once("gov")
        if daemon._store.read_state("gov").state == "FALLBACK_SLATE":
            return clock["t"]
    raise AssertionError(f"channel never reached FALLBACK_SLATE within {max_cycles} cycles")


def test_sustained_first_output_timeouts_at_45s_still_reach_fallback_slate(
    tmp_path: Path,
) -> None:
    """A source that NEVER produces output must still eventually escalate to
    fallback slate -- the rate limit caps the STREAK, never the retry."""
    clock = {"t": 0.0}
    processes = [_FakeProcess(pid=2800 + i) for i in range(12)]
    daemon = _daemon_with_fake_clock(tmp_path, processes=processes, clock=clock, with_fallback=True)

    reached_at = _run_sustained_first_output_timeout_cycles(
        daemon, clock, spacing_s=45.0, max_cycles=10
    )

    assert daemon._store.read_state("gov").state == "FALLBACK_SLATE"
    assert daemon._restart_streak["gov"] >= 5
    assert reached_at == 405.0
