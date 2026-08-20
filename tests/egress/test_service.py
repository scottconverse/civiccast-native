# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the egress service loop."""

from __future__ import annotations

import pytest

from civiccast.egress.service import EgressService


class _FakeDaemon:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def process_once(self, channel_id: str) -> int:
        self.calls.append(channel_id)
        return 1 if channel_id == "council" else 0


def test_service_runs_bounded_iterations_without_sleep_after_last_pass() -> None:
    daemon = _FakeDaemon()
    sleeps: list[float] = []

    service = EgressService(
        daemon,  # type: ignore[arg-type]
        channel_ids=["council", "planning"],
        poll_seconds=0.5,
        sleep=sleeps.append,
    )

    report = service.run(max_iterations=2)

    assert report.channel_ids == ("council", "planning")
    assert report.iterations == 2
    assert report.commands_processed == 2
    assert report.stopped_by == "max_iterations"
    assert report.last_iteration_at is not None
    assert daemon.calls == ["council", "planning", "council", "planning"]
    assert sleeps == [0.5]


def test_service_honors_stop_predicate_before_polling() -> None:
    daemon = _FakeDaemon()
    service = EgressService(
        daemon,  # type: ignore[arg-type]
        channel_ids=["council"],
        should_stop=lambda: True,
    )

    report = service.run()

    assert report.iterations == 0
    assert report.commands_processed == 0
    assert report.stopped_by == "stop_predicate"
    assert report.last_iteration_at is None
    assert daemon.calls == []


@pytest.mark.parametrize(
    ("channel_ids", "poll_seconds", "message"),
    [
        ([], 2.0, "At least one channel id"),
        ([""], 2.0, "At least one channel id"),
        (["council"], -0.1, "poll_seconds"),
    ],
)
def test_service_rejects_invalid_loop_inputs(
    channel_ids: list[str],
    poll_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        EgressService(_FakeDaemon(), channel_ids=channel_ids, poll_seconds=poll_seconds)  # type: ignore[arg-type]
