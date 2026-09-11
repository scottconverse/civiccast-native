# Copyright (c) The CivicCast Authors
# SPDX-License-Identifier: Apache-2.0
"""F-2(c) regression for boundary-time source-plan selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.models import (
    CanonicalProfile,
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.store import InMemoryEgressStore


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0


class _BoundaryStrategy:
    name = "fake-content-reload"
    supports_live_swap = False
    supports_content_reload = True

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.process = _FakeProcess(4200)
        self.start_requests: list[EncoderStartRequest] = []
        self.reload_requests: list[EncoderStartRequest] = []
        self.reload_ids: list[str | None] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        self.start_requests.append(request)
        return EncoderStartResult(
            process=self.process,
            concat_plan_path=self.work_dir / "playout-graph.json",
            stdout_path=self.work_dir / "out.log",
            stderr_path=self.work_dir / "err.log",
            args=("fake-worker",),
        )

    def reload_content(
        self,
        channel_id: str,
        work_dir: Path,
        request: EncoderStartRequest,
        *,
        command_id: str | None = None,
    ) -> bool:
        self.reload_requests.append(request)
        self.reload_ids.append(command_id)
        return True


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="public",
        enabled=True,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/public.ts")],
    )


def _plan(tmp_path: Path, label: str) -> EgressSourcePlan:
    source = tmp_path / f"{label.lower().replace(' ', '-')}.ts"
    source.write_text(label, encoding="utf-8")
    return EgressSourcePlan(
        channel_id="public",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(source),
                duration_seconds=300,
                source_ref=f"ref-{label.lower().replace(' ', '-')}",
            )
        ],
    )


def _reload_command(command_id: str, issued_at: datetime) -> EgressCommand:
    return EgressCommand(
        channel_id="public",
        action="reload",
        issued_at=issued_at,
        issued_by="channel-automation",
        command_id=command_id,
    )


@pytest.mark.parametrize("minute", [25, 50, 55])
def test_boundary_reload_uses_future_item_and_commits_only_after_settlement(
    tmp_path: Path, minute: int
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    initial = _plan(tmp_path, "Program A")
    boundary_plan = _plan(tmp_path, "Program B")
    boundary_calls: list[tuple[str, datetime]] = []
    strategy = _BoundaryStrategy(tmp_path)

    def wallclock_provider(_channel_id: str) -> EgressSourcePlan:
        return initial

    def boundary_provider(channel_id: str, boundary_at: datetime) -> EgressSourcePlan:
        boundary_calls.append((channel_id, boundary_at))
        return boundary_plan

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path / "egress",
        source_plan_provider=wallclock_provider,
        boundary_source_plan_provider=boundary_provider,
        encoder_strategy=strategy,
    )
    start_id = "start-public"
    store.enqueue_command(
        EgressCommand(
            channel_id="public",
            action="start",
            issued_at=datetime.now(UTC),
            issued_by="operator",
            command_id=start_id,
        )
    )
    daemon.process_once("public")
    assert store.read_state("public").current_source_label == "Program A"

    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    boundary_at = now.replace(minute=minute) + timedelta(seconds=120)
    command_id = f"rollover-{minute}"
    daemon.record_rollover_plan_end("public", boundary_at, command_id=command_id)
    store.enqueue_command(_reload_command(command_id, now))

    daemon.process_once("public")
    assert boundary_calls == [("public", boundary_at)]
    assert strategy.reload_requests[0].source_plan.segments[0].label == "Program B"
    assert len(strategy.reload_ids) == 1 and strategy.reload_ids[0]
    assert strategy.reload_requests[0].switch_at_end_of_current is True
    # The deferred reload is armed, not yet landed; the old source remains the
    # durable operator-visible state until the worker reports settlement.
    assert store.read_state("public").current_source_label == "Program A"

    status_path = tmp_path / "egress" / "public" / "reload-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps({"id": strategy.reload_ids[0], "result": "applied"}), encoding="utf-8"
    )
    daemon.process_once("public")
    assert store.read_state("public").current_source_label == "Program B"
