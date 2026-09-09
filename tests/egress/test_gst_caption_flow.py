# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""GI-free contracts for bounded live-caption heartbeat GAP admission."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from civiccast.egress.gst.caption_flow import CaptionGapGate


def test_allows_only_one_outstanding_heartbeat_gap() -> None:
    gate = CaptionGapGate()

    assert gate.reserve(101) is True
    assert gate.pending == 101
    assert gate.reserve(102) is False
    assert gate.pending == 101

    assert gate.entered_downstream(101) is True
    assert gate.pending is None
    assert gate.reserve(102) is True


def test_wrong_sequence_cannot_release_pending_gap() -> None:
    gate = CaptionGapGate()

    assert gate.reserve(101) is True
    assert gate.entered_downstream(102) is False
    assert gate.cancel(102) is False
    assert gate.pending == 101


def test_probe_before_failed_send_return_cannot_clear_newer_gap() -> None:
    gate = CaptionGapGate()

    # The queue source probe can run before send_event() returns to its caller.
    assert gate.reserve(101) is True
    assert gate.entered_downstream(101) is True
    assert gate.reserve(102) is True

    # The earlier sender learns of its failure late; it must not clear 102.
    assert gate.cancel(101) is False
    assert gate.pending == 102


def test_concurrent_reservations_have_one_winner() -> None:
    gate = CaptionGapGate()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(gate.reserve, range(100, 108)))

    assert results.count(True) == 1
    assert gate.pending in range(100, 108)


def test_close_is_idempotent_and_prevents_new_reservations() -> None:
    gate = CaptionGapGate()
    assert gate.reserve(101) is True

    gate.close()
    gate.close()

    assert gate.pending is None
    assert gate.reserve(102) is False
    assert gate.entered_downstream(101) is False
    assert gate.cancel(101) is False


def test_prime_and_heartbeat_follow_the_same_reserve_protocol() -> None:
    """A caller reserves an auto-assigned Gst event seqnum before send_event()."""
    gate = CaptionGapGate()

    # Prime's GAP reaches the queue source before the heartbeat attempts another.
    assert gate.reserve(5001) is True
    assert gate.entered_downstream(5001) is True
    assert gate.reserve(5002) is True
