# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-process proof of the U31 orphan fix: a killed control plane must take
its relay ffmpegs with it.

The live incident (2026-09-25, station, ``supervisor.log`` 07:20:32-07:32:15):
the supervisor killed an unready control plane; the three HLS relay ffmpegs
that control plane had spawned survived as orphans holding the relays' UDP
ports, so every supervised relay that followed failed with ``bind failed:
Error number -10048`` until the orphans were killed by hand.

``win`` in this module's filename follows the D3/CI naming convention, so
``-k "not win"`` deselects it honestly. Every test here spawns REAL processes
(``python`` parent, real ``ffmpeg`` relay-shaped child) and terminates the
parent with a real ``TerminateProcess``. Nothing here touches the live
station's data root: ``PROGRAMDATA`` is redirected into the test's tmp dir
before the child imports ``civiccast``.

Two cases, deliberately:

* ``contain=no`` -- the parent starts the child the way the product did
  before this unit's change (no job of its own). The child MUST survive the
  parent's death. This is the OS mechanism the incident ran into, pinned as a
  regression-proof fact rather than asserted in prose.
* ``contain=yes`` -- the parent goes through the production entry point
  (``civiccast.app._maybe_contain_own_descendants``, the guarded call site in
  the uvicorn ``--factory`` target). The child MUST be gone within 2 s.

The helper tolerates a missing entry point (``getattr``/``ImportError``) on
purpose: before the fix, ``contain=yes`` must fail as a BEHAVIOURAL assertion
("the child outlived its parent"), not as an ``ImportError``. That is the
red half of this file's red-then-green record.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real Job Object + TerminateProcess"),
]

if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateProcess.restype = wintypes.BOOL
    _KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _KERNEL32.WaitForSingleObject.restype = wintypes.DWORD
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL

    _SYNCHRONIZE = 0x00100000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_TIMEOUT = 0x00000102

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FFMPEG = shutil.which("ffmpeg")


def _pid_alive(pid: int) -> bool:
    """True while ``pid`` is still running (a real handle wait, not a guess)."""
    handle = _KERNEL32.OpenProcess(
        _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    try:
        return _KERNEL32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        _KERNEL32.CloseHandle(handle)


def _terminate(pid: int) -> None:
    """The kill the supervisor uses: ``TerminateProcess``, no graceful path."""
    handle = _KERNEL32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    assert handle, f"OpenProcess({pid}) for TerminateProcess failed err={ctypes.get_last_error()}"
    try:
        assert _KERNEL32.TerminateProcess(handle, 1), (
            f"TerminateProcess({pid}) failed err={ctypes.get_last_error()}"
        )
    finally:
        _KERNEL32.CloseHandle(handle)


def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float, interval_seconds: float = 0.05
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_seconds)
    return predicate()


def _force_kill(pid: int) -> None:
    """Best-effort cleanup kill, for the ``finally`` blocks only."""
    handle = _KERNEL32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if not handle:
        return
    try:
        _KERNEL32.TerminateProcess(handle, 1)
    finally:
        _KERNEL32.CloseHandle(handle)


_HELPER_SRC = '''\
"""Stand-in control plane: contain self, then spawn a relay-shaped ffmpeg.

Mirrors the production shape as closely as is safe off-station -- the real
``civiccast.stream._ffmpeg.start_ffmpeg`` starter and a real relay-shaped
argv (UDP mpegts input, decoderless ``-f null`` output) -- while redirecting
every data-root derivation into the caller's scratch directory.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--contain", choices=["yes", "no"], default="yes")
parser.add_argument("--handshake", required=True)
parser.add_argument("--scratch", required=True)
args = parser.parse_args()

scratch = Path(args.scratch)
contained = False
detail = "skipped"
if args.contain == "yes":
    try:
        import civiccast.app
    except ImportError as exc:  # pragma: no cover - helper-side diagnostic
        detail = f"import civiccast.app failed: {exc}"
    else:
        entry = getattr(civiccast.app, "_maybe_contain_own_descendants", None)
        if entry is None:
            detail = "civiccast.app has no _maybe_contain_own_descendants"
        else:
            entry()
            # Report the REAL latched status, not "the entry point existed".
            # An earlier revision of this helper set contained=True on the mere
            # presence of the entry point, which let a silently-inactive
            # containment (guard saw no env var) pass the flag assertion while
            # the child still survived -- the exact mask this test exists to
            # prevent.
            from civiccast.platform.child_containment import containment_status

            status = containment_status()
            contained = bool(status is not None and status.active)
            detail = "entry point called; " + (
                status.detail if status is not None else "no latched status"
            )

from civiccast.stream._ffmpeg import start_ffmpeg

# Relay-shaped: a long-lived ffmpeg reading a UDP mpegts input nobody writes
# to, exactly like an HLS relay between segments. It binds nothing itself.
handle = start_ffmpeg(
    [
        "-f", "mpegts",
        "-i", "udp://127.0.0.1:59997?overrun_nonfatal=1&fifo_size=50000000",
        "-f", "null",
        "-",
    ],
    stdout_path=scratch / "relay-shaped.out.log",
    stderr_path=scratch / "relay-shaped.err.log",
)

Path(args.handshake).write_text(
    json.dumps(
        {
            "parent_pid": os.getpid(),
            "child_pid": handle.process.pid,
            "contained": contained,
            "detail": detail,
        }
    ),
    encoding="utf-8",
)

while True:
    time.sleep(0.25)
'''


def _start_parent(tmp_path: Path, *, contain: str) -> tuple[subprocess.Popen[bytes], dict[str, object]]:
    """Launch the helper and wait for its handshake; return (proc, payload)."""

    helper = tmp_path / "cp_orphan_helper.py"
    helper.write_text(_HELPER_SRC, encoding="utf-8")
    handshake = tmp_path / "handshake.json"
    env = dict(os.environ)
    env["PROGRAMDATA"] = str(tmp_path / "programdata")
    env["CIVICAST_EGRESS_WORK_DIR"] = str(tmp_path / "egress")
    env["CIVICAST_UPLOAD_DIR"] = str(tmp_path / "uploads")
    env["CIVICCAST_SUPERVISED"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    # Files, not PIPE: this test kills the helper with TerminateProcess, so a
    # captured pipe would be left unclosed and pytest's warnings-as-errors
    # policy turns that ResourceWarning into a failure that masks the assertion.
    out_path = tmp_path / "helper.out.log"
    err_path = tmp_path / "helper.err.log"
    with out_path.open("wb") as out_file, err_path.open("wb") as err_file:
        parent = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(helper),
                "--contain",
                contain,
                "--handshake",
                str(handshake),
                "--scratch",
                str(tmp_path),
            ],
            cwd=str(_REPO_ROOT),
            env=env,
            stdout=out_file,
            stderr=err_file,
        )
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline and not handshake.exists():
        if parent.poll() is not None:
            break
        time.sleep(0.1)
    if not handshake.exists():
        if parent.poll() is None:
            parent.kill()
        pytest.fail(
            "helper never wrote its handshake "
            f"(rc={parent.returncode}); stdout="
            f"{out_path.read_bytes().decode('utf-8', 'replace')[-1500:]!r} stderr="
            f"{err_path.read_bytes().decode('utf-8', 'replace')[-3000:]!r}"
        )
    time.sleep(0.5)  # let ffmpeg finish exec'ing before we count it as alive
    return parent, json.loads(handshake.read_text(encoding="utf-8"))


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not on PATH")
def test_uncontained_parent_death_orphans_its_relay_child(tmp_path: Path) -> None:
    """``contain=no``: the pre-fix topology really does leak the child.

    This is the incident's mechanism, pinned. It passes before and after the
    fix -- it is the control that proves the ``contain=yes`` case below is
    testing containment and not something else about how the child died.
    """

    parent, payload = _start_parent(tmp_path, contain="no")
    child_pid = int(payload["child_pid"])
    try:
        assert payload["contained"] is False
        assert _pid_alive(child_pid), "helper's relay-shaped child should be running"
        _terminate(parent.pid)
        assert parent.wait(timeout=30) is not None
        survived = _wait_until(lambda: not _pid_alive(child_pid), timeout_seconds=2.0)
        assert not survived, (
            f"relay-shaped child pid {child_pid} was expected to SURVIVE the parent's "
            "TerminateProcess in the uncontained topology (that is the bug being fixed), "
            "but it died -- the control case is not measuring what it thinks it is"
        )
    finally:
        _force_kill(child_pid)
        if parent.poll() is None:
            parent.kill()


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not on PATH")
def test_contained_parent_death_reaps_its_relay_child_within_two_seconds(
    tmp_path: Path,
) -> None:
    """``contain=yes``: the fix. TerminateProcess the parent; child gone < 2 s."""

    parent, payload = _start_parent(tmp_path, contain="yes")
    child_pid = int(payload["child_pid"])
    try:
        assert _pid_alive(child_pid), "helper's relay-shaped child should be running"
        _terminate(parent.pid)
        assert parent.wait(timeout=30) is not None
        gone = _wait_until(lambda: not _pid_alive(child_pid), timeout_seconds=2.0)
        assert gone, (
            f"relay-shaped child pid {child_pid} outlived its control plane by more than "
            "2.0s after TerminateProcess -- this is the U31 orphan defect "
            f"(containment entry point: {payload['detail']!r})"
        )
        assert payload["contained"] is True, (
            "the child died, but the production entry point never ran -- the containment "
            f"being measured is not the product's: {payload['detail']!r}"
        )
    finally:
        _force_kill(child_pid)
        if parent.poll() is None:
            parent.kill()
