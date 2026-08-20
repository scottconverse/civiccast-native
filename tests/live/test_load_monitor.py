# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the concurrent live-viewer load monitor."""

from __future__ import annotations

from civiccast.live.load_monitor import LiveLoadMonitor


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_empty_channel_reports_zero() -> None:
    assert LiveLoadMonitor().concurrent("gov-ch12") == 0


def test_counts_distinct_clients_in_the_window() -> None:
    clock = _Clock()
    m = LiveLoadMonitor(window_seconds=6.0, clock=clock)
    m.record("gov-ch12", "a")
    m.record("gov-ch12", "b")
    m.record("gov-ch12", "a")  # same client re-polling does not double-count
    assert m.concurrent("gov-ch12") == 2


def test_clients_outside_the_window_expire() -> None:
    clock = _Clock()
    m = LiveLoadMonitor(window_seconds=6.0, clock=clock)
    m.record("gov-ch12", "a")
    clock.t = 3.0
    m.record("gov-ch12", "b")  # b polls 3s in
    clock.t = 7.0  # a last seen 7s ago (> window), b 4s ago (<= window)
    assert m.concurrent("gov-ch12") == 1


def test_channels_are_isolated() -> None:
    clock = _Clock()
    m = LiveLoadMonitor(clock=clock)
    m.record("gov-ch12", "a")
    m.record("gov-ch12", "b")
    m.record("edu-ch13", "a")
    assert m.concurrent("gov-ch12") == 2
    assert m.concurrent("edu-ch13") == 1


def test_a_returning_client_refreshes_its_window() -> None:
    clock = _Clock()
    m = LiveLoadMonitor(window_seconds=6.0, clock=clock)
    m.record("gov-ch12", "a")
    clock.t = 5.0
    m.record("gov-ch12", "a")  # re-poll keeps it alive
    clock.t = 9.0  # 4s since last poll -> still active
    assert m.concurrent("gov-ch12") == 1
