# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 85 (hostile review round 2): the DAEMON side of the reload-commit-
timeout exit code contract (``civiccast.egress.gst.exit_codes.
GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE`` -- see ``tests/egress/
test_gst_engine_reload_commit_ordering.py`` for the engine side, the commit
watchdog thread itself).

Unlike ``GST_PREROLL_TIMEOUT_EXIT_CODE`` (item 82) and item 84's first-output
watchdog exit code, a reload-commit-timeout exit is deliberately NOT treated as
a "slow start" here: the worker had already reached PLAYING and was airing a
channel when its commit wedged, so this is a genuine failure of an
already-running channel, not a slow-but-progressing start. It must count
toward the crash-loop streak on every single occurrence (no rate-limited
exemption, mirroring ``test_ordinary_crash_exit_code_is_not_rate_limited`` in
``test_daemon_preroll_timeout_relaunch.py``), and the relaunch log line should
name the specific reason so an operator/on-call does not have to infer it from
a bare exit code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.gst.exit_codes import GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE
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
    """Minimal GStreamer-named strategy handing out fake processes in order --
    mirrors ``test_daemon_preroll_timeout_relaunch.py``'s fixture of the same
    name (kept as a separate, deliberately smaller copy here: no stderr-log
    plumbing is needed for these tests, which drive ``_relaunch_after_crash``
    directly with a hand-picked ``returncode`` rather than a real worker
    exit)."""

    name = "gstreamer-playout-worker"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess]) -> None:
        self._processes = list(processes)

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        log_dir = request.work_dir / request.channel_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "gst-worker.stderr.log"
        stderr_path.write_text("", encoding="utf-8")
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


def _daemon(tmp_path: Path, *, processes: list[_FakeProcess]) -> EgressDaemon:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_start_command())
    return EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=_WorkerStrategy(processes),
        restart_cooldown_seconds=0.0,
    )


def test_reload_commit_timeout_exit_code_is_not_rate_limited(tmp_path: Path) -> None:
    """Contrast case (mirrors ``test_ordinary_crash_exit_code_is_not_rate_
    limited`` for ``GST_PREROLL_TIMEOUT_EXIT_CODE``): a reload-commit-timeout
    exit must keep incrementing the crash-loop streak on every single
    relaunch, never rate-limited the way a genuine slow-start exit is."""
    processes = [_FakeProcess(pid=500 + i) for i in range(6)]
    daemon = _daemon(tmp_path, processes=processes)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    for expected_streak in (1, 2, 3, 4):
        daemon._processes.pop("gov", None)  # mirrors _poll_process's own pop
        daemon._relaunch_after_crash(
            "gov", state, uptime=None, returncode=GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE
        )
        assert daemon._restart_streak["gov"] == expected_streak


def test_reload_commit_timeout_relaunch_log_line_is_classified(tmp_path: Path) -> None:
    """The relaunch's ``last_error`` names the specific reason
    ("reload-commit-timeout") for a ``GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE``
    exit, distinct from the generic "relaunching encoder." suffix any other
    exit code gets."""
    processes = [_FakeProcess(pid=600 + i) for i in range(3)]
    daemon = _daemon(tmp_path, processes=processes)

    assert daemon.process_once("gov") == 1
    state = daemon._store.read_state("gov")

    # ``_begin_relaunch`` writes a "STARTING" row carrying the classified
    # last_error, but immediately calls ``_start`` after, which -- on a
    # successful start -- writes a FRESH "ON_AIR" row with last_error cleared
    # (correct product behavior: last_error describes why THIS restart
    # happened, not a permanent scar on a channel that is airing fine again).
    # Reading the FINAL persisted state would therefore see last_error=None
    # regardless of what this relaunch actually logged -- spy on every
    # ``_write_state`` call instead so the transient "STARTING" write's
    # last_error is the one under test.
    written_last_errors: list[str | None] = []
    real_write_state = daemon._write_state

    def _spy_write_state(*args: object, **kwargs: object) -> object:
        written_last_errors.append(kwargs.get("last_error"))  # type: ignore[arg-type]
        return real_write_state(*args, **kwargs)

    daemon._write_state = _spy_write_state  # type: ignore[method-assign]

    daemon._processes.pop("gov", None)
    daemon._relaunch_after_crash(
        "gov", state, uptime=None, returncode=GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE
    )

    assert any(
        error is not None and "reload-commit-timeout" in error for error in written_last_errors
    ), written_last_errors


def test_reload_commit_timeout_is_not_in_slow_start_exit_codes() -> None:
    """PR #187 (item 84, first-output watchdog, merged to main as a6d7871)
    introduced ``civiccast.egress.daemon._SLOW_START_EXIT_CODES`` -- the set
    of exit codes daemon.py treats as "slow start, not a crash" (rate-limited
    streak exemption, currently ``{GST_PREROLL_TIMEOUT_EXIT_CODE,
    GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE}``). ``GST_RELOAD_COMMIT_TIMEOUT_
    EXIT_CODE`` must never be a member: a reload-commit wedge is a genuine
    failure of an already-running channel, not a slow start."""
    from civiccast.egress.daemon import _SLOW_START_EXIT_CODES

    assert GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE not in _SLOW_START_EXIT_CODES
