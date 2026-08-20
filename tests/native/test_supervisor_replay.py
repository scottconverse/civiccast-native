# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the pure D2 per-verb delivery/replay policy.

Pins the four falsifications D2 owes (lost ack, duplicate delivery, worker
restart between write and apply, reconnect under multi-channel load) plus the
safety invariants: reload/swap converge to desired state, caption drops rather
than replays, a stopping channel never resurrects. Fake transport only.
"""

from __future__ import annotations

import pytest

from civiccast.native.supervisor.replay import (
    AppliedIdCache,
    ChannelReplay,
    Command,
    delivery_semantics,
)


def _cmd(cid: str, verb: str, line: str = "") -> Command:
    return Command(id=cid, verb=verb, line=line or f"{verb}-payload")


# --------------------------------------------------------------------------
# Per-verb semantics
# --------------------------------------------------------------------------


def test_semantics_per_verb() -> None:
    assert delivery_semantics("reload").on_lost_ack == "reissue_desired_state"
    assert delivery_semantics("swap").on_lost_ack == "reissue_desired_state"
    assert delivery_semantics("caption").on_lost_ack == "report_dropped"
    assert delivery_semantics("caption").at_most_once is True
    assert delivery_semantics("stop").on_lost_ack == "keep_stopping"
    assert delivery_semantics("stop").replayed is False


# --------------------------------------------------------------------------
# Falsification 1 -- lost ack converges (reload/swap) / drops (caption)
# --------------------------------------------------------------------------


def test_lost_ack_reload_reissues_desired_state() -> None:
    ch = ChannelReplay(channel_id="c1")
    cmd = _cmd("r1", "reload", "graph-v2")
    ch.record_sent(cmd)
    assert ch.on_lost_ack(cmd) == "reissue_desired_state"
    reissued = ch.reissue_on_reconnect()
    assert [c.verb for c in reissued] == ["reload"]
    assert reissued[0].line == "graph-v2"  # current desired state, not the lost id


def test_lost_ack_caption_is_dropped_never_replayed() -> None:
    ch = ChannelReplay(channel_id="c1")
    cap = _cmd("cap1", "caption", "cue-at-12:00")
    ch.record_sent(cap)
    assert ch.on_lost_ack(cap) == "report_dropped"
    assert "cap1" in ch.dropped_captions
    # A caption leaves no desired state, so a reconnect never re-sends it.
    assert ch.reissue_on_reconnect() == []


# --------------------------------------------------------------------------
# Falsification 2 -- duplicate delivery applied once (worker dedup)
# --------------------------------------------------------------------------


def test_duplicate_delivery_applied_once() -> None:
    cache = AppliedIdCache()
    assert cache.should_apply("r1") is True
    cache.mark_applied("r1")
    # Redelivered same id: acknowledged again by the caller, but not re-enacted.
    assert cache.should_apply("r1") is False


def test_errored_command_is_not_remembered_as_applied() -> None:
    cache = AppliedIdCache()
    assert cache.should_apply("r1") is True
    # Engine errored -> caller does NOT mark_applied -> a retry still applies.
    assert cache.should_apply("r1") is True


# --------------------------------------------------------------------------
# Falsification 3 -- worker restart between write and apply
# --------------------------------------------------------------------------


def test_worker_restart_then_reissue_converges() -> None:
    # Strategy set desired reload; worker restarted before applying (fresh cache).
    ch = ChannelReplay(channel_id="c1")
    ch.record_sent(_cmd("r1", "reload", "graph-v2"))
    fresh_worker = AppliedIdCache()
    reissued = ch.reissue_on_reconnect()
    assert reissued and reissued[0].line == "graph-v2"
    # Fresh worker has no record of r1's reissue id, so it applies the desired state.
    assert fresh_worker.should_apply(reissued[0].id) is True


# --------------------------------------------------------------------------
# Falsification 4 -- reconnect under multi-channel load
# --------------------------------------------------------------------------


def test_reconnect_reissues_each_channels_current_desired_state() -> None:
    a = ChannelReplay(channel_id="a")
    b = ChannelReplay(channel_id="b")
    a.record_sent(_cmd("a-r1", "reload", "graph-A"))
    a.record_sent(_cmd("a-s1", "swap", "role-A2"))
    b.record_sent(_cmd("b-r1", "reload", "graph-B"))
    # Later reload on A overwrites desired state -> reissue sends the CURRENT one.
    a.record_sent(_cmd("a-r2", "reload", "graph-A-final"))

    a_re = a.reissue_on_reconnect()
    b_re = b.reissue_on_reconnect()
    assert {c.verb: c.line for c in a_re} == {"reload": "graph-A-final", "swap": "role-A2"}
    assert {c.verb: c.line for c in b_re} == {"reload": "graph-B"}


# --------------------------------------------------------------------------
# Safety invariant -- a stopping channel never resurrects
# --------------------------------------------------------------------------


def test_stop_pins_channel_and_suppresses_all_reissue() -> None:
    ch = ChannelReplay(channel_id="c1")
    ch.record_sent(_cmd("r1", "reload", "graph-v2"))  # a live desired state exists
    ch.record_sent(_cmd("st1", "stop", "stop"))  # then stop
    assert ch.stopping is True
    # Even with a desired reload on record, a stopping channel reissues nothing.
    assert ch.reissue_on_reconnect() == []


def test_lost_ack_on_reload_while_stopping_does_not_reissue() -> None:
    ch = ChannelReplay(channel_id="c1")
    ch.record_sent(_cmd("st1", "stop", "stop"))
    reload_cmd = _cmd("r1", "reload", "graph-v2")
    ch.record_sent(reload_cmd)  # desired state set, but channel is stopping
    assert ch.on_lost_ack(reload_cmd) == "keep_stopping"
    assert ch.reissue_on_reconnect() == []


# --------------------------------------------------------------------------
# AppliedIdCache LRU
# --------------------------------------------------------------------------


def test_applied_id_cache_evicts_lru() -> None:
    cache = AppliedIdCache(capacity=2)
    cache.mark_applied("a")
    cache.mark_applied("b")
    cache.mark_applied("c")  # evicts "a"
    assert "a" not in cache
    assert "b" in cache and "c" in cache
    assert len(cache) == 2


def test_applied_id_cache_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AppliedIdCache(capacity=0)
