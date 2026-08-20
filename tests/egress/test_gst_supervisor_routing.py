# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""PlayoutSupervisor routes a source-role change to an in-place swap when the
encoder strategy supports it (the GStreamer engine), and to the existing reload
otherwise (the ffmpeg path). Closes the audit's supervisor-routing coverage gap."""

from __future__ import annotations

from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.supervisor import PlayoutSupervisor


class _FakeStrategy:
    def __init__(self, *, supports_live_swap: bool) -> None:
        self.name = "fake"
        self.supports_live_swap = supports_live_swap
        self.swaps: list[tuple[str, str]] = []

    def start(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError

    def swap_role(self, channel_id: str, work_dir, role: str) -> None:
        self.swaps.append((channel_id, role))


def _supervisor(tmp_path, strategy: _FakeStrategy) -> PlayoutSupervisor:
    return PlayoutSupervisor(
        InMemoryEgressStore(),
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: None,
        encoder_strategy=strategy,
    )


def test_supervisor_swaps_when_strategy_supports_live_swap(tmp_path) -> None:
    strategy = _FakeStrategy(supports_live_swap=True)
    supervisor = _supervisor(tmp_path, strategy)
    supervisor.request_fallback_slate(channel_id="c", reason="off-air")
    supervisor.request_slate_exit(channel_id="c")
    assert ("c", "slate") in strategy.swaps
    assert ("c", "program") in strategy.swaps


def test_supervisor_does_not_swap_when_strategy_lacks_live_swap(tmp_path) -> None:
    strategy = _FakeStrategy(supports_live_swap=False)
    supervisor = _supervisor(tmp_path, strategy)
    supervisor.request_fallback_slate(channel_id="c", reason="off-air")
    assert strategy.swaps == []
