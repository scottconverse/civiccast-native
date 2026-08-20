# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the adaptive local<->CDN surge switch state machine."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from civiccast.live.surge_switch import LivePublisher, SurgeSwitch


class _Load:
    def __init__(self) -> None:
        self._n: dict[str, int] = {}

    def set(self, channel_id: str, n: int) -> None:
        self._n[channel_id] = n

    def concurrent(self, channel_id: str) -> int:
        return self._n.get(channel_id, 0)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Publisher:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.syncs = 0
        self.evicted = 0
        self.fail = False

    def sync(self) -> str | None:
        self.syncs += 1
        if self.fail:
            raise RuntimeError("edge unreachable")
        return self.manifest_url()

    def manifest_url(self) -> str:
        return f"https://cdn/live/{self.channel_id}/playlist.m3u8"

    def evict_all(self) -> None:
        self.evicted += 1


def _switch(
    load: _Load,
    *,
    threshold: int = 10,
    buffer_seconds: float = 15.0,
    factory: Callable[[str], LivePublisher | None] | None = None,
) -> tuple[SurgeSwitch, _Clock]:
    clk = _Clock()
    fac: Callable[[str], LivePublisher | None] = factory or (lambda ch: _Publisher(ch))
    switch = SurgeSwitch(load, fac, threshold=threshold, buffer_seconds=buffer_seconds, clock=clk)
    return switch, clk


def test_below_threshold_stays_local() -> None:
    load = _Load()
    load.set("c", 5)
    switch, _ = _switch(load, threshold=10)
    switch.tick("c")
    assert switch.state("c") == "local"
    assert switch.manifest_url("c") is None


def test_crossing_threshold_warms_and_publishes_but_serves_local_during_buffer() -> None:
    load = _Load()
    load.set("c", 10)
    made: dict[str, _Publisher] = {}

    def factory(channel_id: str) -> LivePublisher:
        made[channel_id] = _Publisher(channel_id)
        return made[channel_id]

    switch, _ = _switch(load, threshold=10, factory=factory)
    switch.tick("c")
    assert switch.state("c") == "warming"
    assert made["c"].syncs == 1  # cold-start: publishing began
    assert switch.manifest_url("c") is None  # buffer covers the transition


def test_after_buffer_switches_viewers_to_cdn() -> None:
    load = _Load()
    load.set("c", 10)
    switch, clk = _switch(load, threshold=10, buffer_seconds=15.0)
    switch.tick("c")  # warm at t=0
    clk.t = 15.0
    switch.tick("c")  # buffer elapsed -> switch
    assert switch.state("c") == "cdn"
    assert switch.manifest_url("c") == "https://cdn/live/c/playlist.m3u8"


def test_load_dropping_below_release_returns_to_local() -> None:
    load = _Load()
    load.set("c", 10)
    switch, clk = _switch(load, threshold=10, buffer_seconds=15.0)
    switch.tick("c")
    clk.t = 15.0
    switch.tick("c")
    assert switch.state("c") == "cdn"

    load.set("c", 2)  # below release (threshold // 2 == 5)
    switch.tick("c")
    assert switch.state("c") == "local"
    assert switch.manifest_url("c") is None


def test_no_cdn_configured_stays_local_even_under_load() -> None:
    load = _Load()
    load.set("c", 100)
    switch, _ = _switch(load, threshold=10, factory=lambda ch: None)
    switch.tick("c")
    assert switch.state("c") == "local"
    assert switch.manifest_url("c") is None


def test_publish_failure_falls_back_to_local() -> None:
    load = _Load()
    load.set("c", 10)

    def factory(channel_id: str) -> LivePublisher:
        p = _Publisher(channel_id)
        p.fail = True
        return p

    switch, _ = _switch(load, threshold=10, factory=factory)
    switch.tick("c")  # warm -> sync raises -> clean fallback
    assert switch.state("c") == "local"
    assert switch.manifest_url("c") is None


def test_release_evicts_the_cdn_objects() -> None:
    load = _Load()
    load.set("c", 10)
    made: dict[str, _Publisher] = {}

    def factory(channel_id: str) -> LivePublisher:
        made[channel_id] = _Publisher(channel_id)
        return made[channel_id]

    switch, clk = _switch(load, threshold=10, buffer_seconds=15.0, factory=factory)
    switch.tick("c")
    clk.t = 15.0
    switch.tick("c")  # -> CDN
    assert switch.state("c") == "cdn"

    load.set("c", 0)  # drop below release
    switch.tick("c")  # -> local, must clean up the CDN
    assert switch.state("c") == "local"
    assert made["c"].evicted == 1


def test_publish_failure_evicts_before_falling_back() -> None:
    load = _Load()
    load.set("c", 10)
    made: dict[str, _Publisher] = {}

    def factory(channel_id: str) -> LivePublisher:
        p = _Publisher(channel_id)
        p.fail = True
        made[channel_id] = p
        return p

    switch, _ = _switch(load, threshold=10, factory=factory)
    switch.tick("c")  # warm -> sync raises -> fallback (evict is best-effort)
    assert switch.state("c") == "local"
    assert made["c"].evicted == 1


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        SurgeSwitch(_Load(), lambda ch: None, threshold=0)
