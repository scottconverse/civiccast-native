# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The pg_ctl executor must survive a child that spawns a lingering
grandchild inheriting its output handles -- the Windows pipe-inheritance
hang that burned Sandbox runs 14 and 15 (see pg_ctl_exec's module
docstring). The repro here is exact: a short-lived parent process spawns a
long-lived detached child, writes a line, and exits. With pipe capture the
old code blocked until the GRANDCHILD died; with file capture the call
returns as soon as the PARENT exits."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from civiccast.native.pg_ctl_exec import (
    CapturedProcess,
    PgCtlResult,
    kill_process_tree,
    run_captured_argv,
    run_pg_ctl_argv,
)

# Parent: print, spawn a detached 30s-sleeping grandchild that inherits our
# std handles, exit 0 immediately. (close_fds=False on Windows is what makes
# handle inheritance possible -- same as pg_ctl launching postgres.)
_PARENT_SCRIPT = (
    "import subprocess, sys; "
    "print('parent-output-line'); sys.stdout.flush(); "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
    "close_fds=False); "
    "sys.exit(0)"
)


def _lingering_child_argv() -> list[str]:
    return [sys.executable, "-c", _PARENT_SCRIPT]


def test_returns_promptly_despite_a_lingering_handle_inheriting_grandchild() -> None:
    """THE regression test for runs 14/15: must complete in seconds, not
    when the 30s grandchild dies. Bound generously at 15s -- the old
    pipe-capture implementation cannot pass this (it blocks ~30s+)."""

    started = time.monotonic()
    result = run_pg_ctl_argv(_lingering_child_argv(), timeout_seconds=20.0)
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert elapsed < 15.0, (
        f"executor took {elapsed:.1f}s -- it waited on the grandchild's "
        "inherited handles, the exact run-14/15 hang"
    )


def test_captures_the_parents_output_via_files() -> None:
    result = run_pg_ctl_argv(_lingering_child_argv(), timeout_seconds=20.0)
    assert "parent-output-line" in result.output_tail


def test_nonzero_exit_and_stderr_tail_are_reported() -> None:
    argv = [
        sys.executable,
        "-c",
        "import sys; print('boom-detail', file=sys.stderr); sys.exit(7)",
    ]
    result = run_pg_ctl_argv(argv, timeout_seconds=20.0)
    assert result.returncode == 7
    assert "boom-detail" in result.output_tail


def test_output_tail_retains_stdout_diagnosis_alongside_stderr_lines() -> None:
    """Forensically-proven Windows shape: `pg_ctl start` without `-l` merges
    the postmaster's real FATAL diagnosis into pg_ctl's STDOUT, while
    pg_ctl's own STDERR carries only its two generic lines. At HEAD, `tail =
    (err_text or out_text)[-_TAIL_CHARS:]` picked the useless stderr lines
    and silently discarded the real diagnosis. The tail must contain BOTH."""
    argv = [
        sys.executable,
        "-c",
        "import sys; "
        "print('DIAGNOSIS: FATAL: could not bind IPv4 address'); "
        "print('pg_ctl: could not start server', file=sys.stderr); "
        "print('Examine the log output.', file=sys.stderr); "
        "sys.exit(1)",
    ]
    result = run_pg_ctl_argv(argv, timeout_seconds=20.0)
    assert result.returncode == 1
    assert "DIAGNOSIS: FATAL: could not bind IPv4 address" in result.output_tail
    assert "pg_ctl: could not start server" in result.output_tail


def test_timeout_still_raises_for_a_parent_that_itself_hangs() -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    started = time.monotonic()
    try:
        run_pg_ctl_argv(argv, timeout_seconds=2.0)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        assert elapsed < 10.0
    else:  # pragma: no cover - the assertion documents intent
        raise AssertionError("a genuinely hung parent must raise TimeoutExpired")


def test_result_shape() -> None:
    assert PgCtlResult(returncode=0, output_tail="x").returncode == 0


# ---------------------------------------------------------------------------
# run_captured_argv (C2/C3, 2026-07-31): the generalized file-backed capture
# for the OTHER install-time/probe children (initdb, psql, wsl.exe, sc.exe)
# -- separate byte streams, hard deadline, kill-tree on expiry.
# ---------------------------------------------------------------------------


def test_run_captured_argv_survives_a_lingering_handle_inheriting_grandchild() -> None:
    """The exact run-14/15 repro, against the REAL production path (Popen +
    file-backed capture): must return when the parent exits, not when the
    30s grandchild dies."""

    started = time.monotonic()
    result = run_captured_argv(_lingering_child_argv(), timeout_seconds=20.0)
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert b"parent-output-line" in result.stdout
    assert elapsed < 15.0, (
        f"executor took {elapsed:.1f}s -- it waited on the grandchild's inherited handles"
    )


def test_run_captured_argv_separates_the_two_real_streams_as_bytes() -> None:
    argv = [
        sys.executable,
        "-c",
        "import sys; print('to-out'); print('to-err', file=sys.stderr); sys.exit(9)",
    ]
    result = run_captured_argv(argv, timeout_seconds=20.0)
    assert result.returncode == 9
    assert b"to-out" in result.stdout
    assert b"to-err" in result.stderr
    assert b"to-err" not in result.stdout


def test_run_captured_argv_gives_the_child_files_never_pipes() -> None:
    seen: dict[str, object] = {}

    class FakeProc:
        pid = 4242

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        kwargs["stdout"].write(b"out-bytes")
        kwargs["stderr"].write(b"err-bytes")
        return FakeProc()

    result = run_captured_argv(["whatever"], timeout_seconds=5.0, popen=fake_popen)

    assert hasattr(seen["stdout"], "fileno"), "stdout must be a real file, never a pipe"
    assert hasattr(seen["stderr"], "fileno"), "stderr must be a real file, never a pipe"
    assert seen["stdin"] is subprocess.DEVNULL
    assert result == CapturedProcess(returncode=0, stdout=b"out-bytes", stderr=b"err-bytes")


def test_run_captured_argv_timeout_kills_the_whole_tree_and_raises() -> None:
    """C3's hard requirement: on deadline expiry the WHOLE process tree is
    force-killed (wsl.exe leaves wslhost.exe helpers behind) and
    TimeoutExpired still propagates unchanged for the caller's existing
    classification."""

    killed: list[int] = []

    class HungProc:
        pid = 424242

        def __init__(self) -> None:
            self.waits = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(cmd="hung", timeout=timeout or 0.0)
            return -9  # the post-kill bounded reap

    proc = HungProc()
    with pytest.raises(subprocess.TimeoutExpired):
        run_captured_argv(
            ["hung"],
            timeout_seconds=0.1,
            popen=lambda argv, **kwargs: proc,
            kill_tree=killed.append,
        )

    assert killed == [HungProc.pid]
    assert proc.waits == 2  # deadline wait + post-kill reap


def test_run_captured_argv_injected_runner_gets_the_file_backed_shape() -> None:
    """The subprocess.run-shaped test seam every probe exposes: the fake is
    invoked with the file-backed keyword shape (never capture_output), and
    its legacy CompletedProcess-style .stdout/.stderr (bytes OR str) is
    honored when it wrote nothing to the files."""

    seen: dict[str, object] = {}

    def fake_runner(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 5, stdout=b"legacy-out", stderr="legacy-err")

    result = run_captured_argv(["x"], timeout_seconds=1.5, env={"K": "V"}, runner=fake_runner)

    assert "capture_output" not in seen
    assert hasattr(seen["stdout"], "fileno")
    assert hasattr(seen["stderr"], "fileno")
    assert seen["timeout"] == 1.5
    assert seen["env"] == {"K": "V"}
    assert result == CapturedProcess(returncode=5, stdout=b"legacy-out", stderr=b"legacy-err")


def test_run_captured_argv_injected_runner_exceptions_propagate_unchanged() -> None:
    def timing_out(argv, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    with pytest.raises(subprocess.TimeoutExpired):
        run_captured_argv(["x"], timeout_seconds=1.0, runner=timing_out)

    def missing(argv, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("no such exe")

    with pytest.raises(FileNotFoundError):
        run_captured_argv(["x"], timeout_seconds=1.0, runner=missing)


def test_kill_process_tree_reaps_a_real_detached_grandchild(tmp_path) -> None:
    """Real-fire proof: kill_process_tree takes down BOTH the parent and the
    detached grandchild it spawned (the lingering-helper shape wsl.exe
    produces)."""

    import psutil

    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time, pathlib; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "close_fds=False); "
        f"pathlib.Path(r'{pid_file}').write_text(str(p.pid)); "
        "time.sleep(60)"
    )
    parent = subprocess.Popen([sys.executable, "-c", script])
    try:
        deadline = time.monotonic() + 20.0
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "grandchild never started"
        grandchild_pid = int(pid_file.read_text())

        kill_process_tree(parent.pid)

        parent.wait(timeout=10.0)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                proc = psutil.Process(grandchild_pid)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the detached grandchild survived kill_process_tree")
    finally:
        if parent.poll() is None:
            parent.kill()


def test_kill_process_tree_tolerates_an_already_gone_pid() -> None:
    probe = subprocess.Popen([sys.executable, "-c", "pass"])
    probe.wait(timeout=20.0)
    kill_process_tree(probe.pid)  # must not raise
