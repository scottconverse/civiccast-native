# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Caption proof child supervision contract."""

from __future__ import annotations

import threading
import time

from civiccast.egress.caption_proof_process import CaptionProofProcessSupervisor


class _Child:
    pid = 4242

    def __init__(self) -> None:
        self.alive = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        self.alive = False

    def wait(self, *, timeout: float) -> int:
        return 0


def test_supervisor_starts_and_stops_an_independent_child() -> None:
    child = _Child()
    seen: dict[str, object] = {}

    def popen(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return child

    supervisor = CaptionProofProcessSupervisor(
        poll_seconds=0.01,
        capture_seconds=6.0,
        timeout_seconds=15.0,
        python_executable="python-test",
        popen=popen,
    )
    stop = threading.Event()
    thread = threading.Thread(
        target=supervisor.run_forever,
        kwargs={"poll_seconds": 0.01, "stop_event": stop},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 1.0
    while "command" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=1.0)

    assert seen["command"][:4] == [
        "python-test",
        "-m",
        "civiccast.egress.caption_proof_process",
        "--worker-poll-seconds",
    ]
    assert "--timeout-seconds" in seen["command"]
    assert child.terminated is True
