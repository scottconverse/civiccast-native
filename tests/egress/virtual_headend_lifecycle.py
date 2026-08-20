# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Lifecycle driver for the E.2 virtual-headend scenario.

This is test-only infrastructure. It drives the shipping ``PlayoutSupervisor``
through the scenario events while fake encoder processes make recovery paths
deterministic in unit tests and self-hosted runner orchestration.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from civiccast.egress.cg_bridge import EgressCgOverlayProof
from civiccast.egress.models import EgressCommand, EgressSourcePlan
from civiccast.egress.store import EgressStore
from civiccast.egress.supervisor import PlayoutSupervisor
from tests.egress.virtual_headend_media import GeneratedTestMediaSet
from tests.egress.virtual_headend_scenario import (
    ScenarioRecoveryEvidence,
    VirtualHeadendScenarioEvent,
)

RestartDaemon = Callable[[], float]
Clock = Callable[[], float]


@dataclass
class ControlledEncoderProcess:
    """Fakeable encoder child used by the lifecycle driver."""

    pid: int
    returncode: int | None = None
    terminated: bool = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0


class EncoderProcessController:
    """Create and manipulate deterministic fake encoder children."""

    def __init__(self, *, first_pid: int = 10_000) -> None:
        self._next_pid = first_pid
        self.started: list[ControlledEncoderProcess] = []

    def start(self, _args: list[str]) -> ControlledEncoderProcess:
        process = ControlledEncoderProcess(pid=self._next_pid)
        self._next_pid += 1
        self.started.append(process)
        return process

    def finish_current(self) -> None:
        self.current.returncode = 0

    def kill_current(self) -> None:
        self.current.returncode = 1

    @property
    def current(self) -> ControlledEncoderProcess:
        if not self.started:
            raise RuntimeError("no encoder child has been started")
        return self.started[-1]


@dataclass(frozen=True)
class ProcessRestartProbe:
    """Process-backed restart probe for E.2 daemon-restart evidence."""

    command: tuple[str, ...] = (
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
    )
    timeout_seconds: float = 5.0

    def __call__(self) -> float:
        started_at = time.monotonic()
        original = _start_probe_process(self.command)
        try:
            _stop_probe_process(original, timeout_seconds=self.timeout_seconds)
            replacement = _start_probe_process(self.command)
            try:
                if replacement.poll() is not None:
                    raise RuntimeError("replacement process exited before restart proof completed")
                return time.monotonic() - started_at
            finally:
                _stop_probe_process(replacement, timeout_seconds=self.timeout_seconds)
        finally:
            if original.poll() is None:
                _stop_probe_process(original, timeout_seconds=self.timeout_seconds)


@dataclass(frozen=True)
class PlayoutSupervisorLifecycleDriver:
    """Drive the real supervisor through the E.2 scenario event contract."""

    channel_id: str
    store: EgressStore
    supervisor: PlayoutSupervisor
    process_controller: EncoderProcessController
    fallback_reason: str
    cg_overlay_proof: EgressCgOverlayProof
    restart_daemon: RestartDaemon
    clock: Clock

    def __call__(
        self,
        *,
        events: tuple[VirtualHeadendScenarioEvent, ...],
        media_set: GeneratedTestMediaSet,
    ) -> ScenarioRecoveryEvidence:
        daemon_restart_seconds: float | None = None
        ffmpeg_restart_seconds: float | None = None
        for event in events:
            if event.name == "start-daemon":
                self._enqueue("start")
                self.supervisor.process_once(self.channel_id)
            elif event.name == "program-boundary":
                continue
            elif event.name == "remove-scheduled-asset":
                self.supervisor.request_fallback_slate(
                    channel_id=self.channel_id,
                    reason=self.fallback_reason,
                )
                self._finish_boundary()
            elif event.name == "restore-scheduled-asset":
                self.supervisor.request_slate_exit(channel_id=self.channel_id)
                self._finish_boundary()
            elif event.name == "live-takeover":
                self.supervisor.request_live_takeover(
                    channel_id=self.channel_id,
                    live_source_plan=_source_plan_for_kind(media_set, kind="live"),
                )
                self._finish_boundary()
            elif event.name == "live-handback":
                self.supervisor.request_live_handback(channel_id=self.channel_id)
                self._finish_boundary()
            elif event.name == "raise-cg-emergency":
                self.supervisor.raise_cg_emergency_overlay(proof=self.cg_overlay_proof)
            elif event.name == "clear-cg-emergency":
                self.supervisor.clear_cg_emergency_overlay(channel_id=self.channel_id)
            elif event.name == "kill-ffmpeg-child":
                started_at = self.clock()
                self.process_controller.kill_current()
                self.supervisor.process_once(self.channel_id)
                ffmpeg_restart_seconds = self.clock() - started_at
            elif event.name == "kill-daemon-process":
                daemon_restart_seconds = self.restart_daemon()
            elif event.name == "reload":
                self._enqueue("reload")
                self.supervisor.process_once(self.channel_id)
                self._finish_boundary()
            elif event.name == "drain-stop":
                self._enqueue("drain")
                self.supervisor.process_once(self.channel_id)
                self._finish_boundary()
            else:
                raise RuntimeError(f"unsupported E.2 lifecycle event: {event.name}")
        return ScenarioRecoveryEvidence(
            daemon_restart_recovery_seconds=daemon_restart_seconds,
            ffmpeg_child_restart_recovery_seconds=ffmpeg_restart_seconds,
        )

    def _finish_boundary(self) -> None:
        self.process_controller.finish_current()
        self.supervisor.process_once(self.channel_id)

    def _enqueue(self, action: str) -> None:
        self.store.enqueue_command(
            EgressCommand(
                channel_id=self.channel_id,
                action=action,  # type: ignore[arg-type]
                issued_at=datetime.now(UTC),
                issued_by="virtual-headend-lifecycle",
                command_id=f"virtual-headend-{action}-{self.clock():.6f}",
            )
        )


def _source_plan_for_kind(media_set: GeneratedTestMediaSet, *, kind: str) -> EgressSourcePlan:
    for segment in media_set.source_plan.segments:
        if segment.kind == kind:
            return EgressSourcePlan(channel_id=media_set.source_plan.channel_id, segments=[segment])
    raise RuntimeError(f"generated media set does not include a {kind!r} source")


def _start_probe_process(command: tuple[str, ...]) -> subprocess.Popen[bytes]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _stop_probe_process(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)
