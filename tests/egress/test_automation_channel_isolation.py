# Copyright (c) The CivicCast Authors
# SPDX-License-Identifier: Apache-2.0
"""F-2 regression for async source preparation in the production loop."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.automation import ChannelAutomationService, ChannelAutomationSettings
from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.models import (
    CanonicalProfile,
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparationReport
from civiccast.egress.store import InMemoryEgressStore

_CHANNELS = ("aaa-slow", "bbb-fast", "ccc-fast")
_WAIT_SECONDS = 1.0


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0


class _RecordingEgressDaemon(EgressDaemon):
    """Real daemon with only pass observability added for this regression."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.processed: list[str] = []
        self.process_counts: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.fast_second_passes = threading.Event()
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def process_once(self, channel_id: str) -> int:
        with self._lock:
            active = self._active.get(channel_id, 0) + 1
            self._active[channel_id] = active
            self.max_active[channel_id] = max(self.max_active.get(channel_id, 0), active)
            self.processed.append(channel_id)
            self.process_counts[channel_id] = self.process_counts.get(channel_id, 0) + 1
        try:
            return super().process_once(channel_id)
        finally:
            with self._lock:
                self._active[channel_id] -= 1
                if all(
                    self.process_counts.get(channel, 0) >= 2 and self.has_live_process(channel)
                    for channel in _CHANNELS[1:]
                ):
                    self.fast_second_passes.set()


def _config(channel_id: str) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        auto_start=True,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _plan(channel_id: str, source_path: Path) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label=f"Program {channel_id}",
                path=str(source_path),
                duration_seconds=60,
                source_ref=f"source-{channel_id}",
            )
        ],
    )


def test_run_forever_keeps_fast_channels_passing_during_slow_prepare(tmp_path: Path) -> None:
    """A blocked A preparation cannot starve B/C's current or next poll pass."""
    store = InMemoryEgressStore()
    sources = {}
    for channel_id in _CHANNELS:
        store.upsert_config(_config(channel_id))
        source_path = tmp_path / f"{channel_id}.ts"
        source_path.write_text("fake", encoding="utf-8")
        sources[channel_id] = source_path

    slow_prepare_entered = threading.Event()
    release_slow_prepare = threading.Event()
    provider_called = {channel_id: threading.Event() for channel_id in _CHANNELS}

    def provider(channel_id: str) -> EgressSourcePlan:
        provider_called[channel_id].set()
        return _plan(channel_id, sources[channel_id])

    def prepare(plan: EgressSourcePlan, _config: EgressConfig) -> SourcePreparationReport:
        if plan.channel_id == _CHANNELS[0]:
            slow_prepare_entered.set()
            assert release_slow_prepare.wait(10.0), "slow preparation was not released"
        return SourcePreparationReport(source_plan=plan, records=())

    processes = iter(_FakeProcess(pid) for pid in range(4100, 4200))

    def ffmpeg_starter(_args: list[str]) -> _FakeProcess:
        return next(processes)

    daemon = _RecordingEgressDaemon(
        store,
        work_dir=tmp_path / "egress",
        source_plan_provider=provider,
        source_preparer=prepare,
        ffmpeg_starter=ffmpeg_starter,
    )
    service = ChannelAutomationService(
        store,
        daemon,
        provider,
        settings=ChannelAutomationSettings(poll_seconds=0.01),
    )
    stop_event = threading.Event()
    runner = threading.Thread(
        target=service.run_forever,
        kwargs={"poll_seconds": 0.01, "stop_event": stop_event},
        name="f2-channel-isolation-regression",
    )
    runner.start()
    try:
        assert slow_prepare_entered.wait(_WAIT_SECONDS), "slow preparation did not start"
        assert provider_called[_CHANNELS[1]].wait(_WAIT_SECONDS)
        assert provider_called[_CHANNELS[2]].wait(_WAIT_SECONDS)
        assert daemon.fast_second_passes.wait(_WAIT_SECONDS), (
            "fast channels did not complete a second process_once pass while A prepared"
        )
        assert not release_slow_prepare.is_set(), "A was released before fast passes completed"
    finally:
        release_slow_prepare.set()
        stop_event.set()
        runner.join(_WAIT_SECONDS)

    assert not runner.is_alive(), "run_forever did not shut down after stop_event"
    assert daemon.max_active == dict.fromkeys(_CHANNELS, 1)
    assert all(channel_id in daemon.processed for channel_id in _CHANNELS)


def test_stop_during_preparation_discards_late_result(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    channel_id = _CHANNELS[0]
    store.upsert_config(_config(channel_id))
    source = tmp_path / "source.ts"
    source.write_text("fake", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    launched: list[object] = []

    def prepare(plan: EgressSourcePlan, _config: EgressConfig) -> SourcePreparationReport:
        entered.set()
        assert release.wait(10.0)
        return SourcePreparationReport(source_plan=plan, records=())

    def start(_args: list[str]) -> _FakeProcess:
        process = _FakeProcess(4100)
        launched.append(process)
        return process

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path / "egress",
        source_plan_provider=lambda channel: _plan(channel, source),
        source_preparer=prepare,
        ffmpeg_starter=start,
    )
    daemon.enable_async_preparation()
    try:
        store.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action="start",
                issued_at=datetime.now(UTC),
                issued_by="test",
                command_id="start-slow",
            )
        )
        daemon.process_once(channel_id)
        assert entered.wait(_WAIT_SECONDS)
        store.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action="stop",
                issued_at=datetime.now(UTC),
                issued_by="test",
                command_id="stop-slow",
            )
        )
        daemon.process_once(channel_id)
        state = store.read_state(channel_id)
        assert state is not None and state.state == "STOPPED"
        assert not launched
    finally:
        release.set()
        daemon.shutdown_preparation()
    daemon.process_once(channel_id)
    assert not launched
    assert not daemon.has_live_process(channel_id)
