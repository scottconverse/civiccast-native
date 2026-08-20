# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Supervised BYO-NDI relay tests (issue #116, option c)."""

from __future__ import annotations

import pytest

from civiccast.cable.ndi import NdiReadinessResult
from civiccast.egress.ndi_relay import (
    NdiRelaySettings,
    NdiRelaySupervisor,
    build_ndi_relay_args,
)


def _ready() -> NdiReadinessResult:
    return NdiReadinessResult(
        status="ok",
        supported_muxer="libndi_newtek",
        ffmpeg_detected=True,
        ndi_runtime_detected=True,
        ndi_sdk_detected=True,
        ndi_sender_detected=False,
        ndi_sender_path=None,
        next_step="",
    )


def _blocked() -> NdiReadinessResult:
    return NdiReadinessResult(
        status="ndi_muxer_missing",
        supported_muxer=None,
        ffmpeg_detected=True,
        ndi_runtime_detected=False,
        ndi_sdk_detected=False,
        ndi_sender_detected=False,
        ndi_sender_path=None,
        next_step="Install or build an FFmpeg binary with NDI output support.",
    )


def test_readiness_probe_result_is_cached_per_binary() -> None:
    # S9-6 (parity with SDI audit ENG-008): an uncached NDI readiness probe re-ran
    # inside the automation tick on every spawn attempt, so a blocked relay churned
    # ffmpeg every ~2s. The default checker now caches per ffmpeg path with a TTL.
    from civiccast.egress.ndi_relay import cached_check_ndi_runtime, clear_readiness_cache

    clear_readiness_cache()
    clock = {"now": 1000.0}
    calls: list[str] = []

    def probe(ffmpeg_path: str) -> NdiReadinessResult:
        calls.append(ffmpeg_path)
        return _ready()

    first = cached_check_ndi_runtime("ffmpeg-ndi", probe=probe, monotonic=lambda: clock["now"])
    second = cached_check_ndi_runtime("ffmpeg-ndi", probe=probe, monotonic=lambda: clock["now"])
    assert first.status == "ok" and second.status == "ok"
    assert len(calls) == 1  # cached within the TTL

    clock["now"] += 600.0
    cached_check_ndi_runtime("ffmpeg-ndi", probe=probe, monotonic=lambda: clock["now"])
    assert len(calls) == 2  # TTL expired: re-probed
    clear_readiness_cache()


def test_readiness_cache_is_keyed_per_binary_path() -> None:
    # The cache must key on the ffmpeg path, not be a single global slot: two distinct
    # binaries within the same TTL window each get probed (swapping the BYO binary must
    # not return a stale verdict from the other one).
    from civiccast.egress.ndi_relay import cached_check_ndi_runtime, clear_readiness_cache

    clear_readiness_cache()
    clock = {"now": 1000.0}
    calls: list[str] = []

    def probe(ffmpeg_path: str) -> NdiReadinessResult:
        calls.append(ffmpeg_path)
        return _ready()

    cached_check_ndi_runtime("ffmpeg-ndi-a", probe=probe, monotonic=lambda: clock["now"])
    cached_check_ndi_runtime("ffmpeg-ndi-b", probe=probe, monotonic=lambda: clock["now"])
    # second call to A within the TTL is served from A's cache slot, not B's
    cached_check_ndi_runtime("ffmpeg-ndi-a", probe=probe, monotonic=lambda: clock["now"])
    assert calls == ["ffmpeg-ndi-a", "ffmpeg-ndi-b"]  # each path probed exactly once
    clear_readiness_cache()


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.alive = True
        self.killed = False

    def poll(self) -> int | None:
        return None if self.alive else 1

    def terminate(self) -> None:
        self.alive = False
        self.killed = True


def test_settings_require_byo_ffmpeg(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_NDI_FFMPEG", raising=False)
    monkeypatch.delenv("CIVICCAST_NDI_RELAY", raising=False)
    settings = NdiRelaySettings.from_env()
    assert settings.mode == "inline"
    assert settings.ffmpeg_path is None

    monkeypatch.setenv("CIVICCAST_NDI_FFMPEG", r"C:\station\ffmpeg-ndi\ffmpeg.exe")
    monkeypatch.setenv("CIVICCAST_NDI_RELAY", "off")
    settings = NdiRelaySettings.from_env()
    assert settings.mode == "off"
    assert settings.ffmpeg_path == r"C:\station\ffmpeg-ndi\ffmpeg.exe"


def test_relay_args_consume_channel_ts_and_publish_uyvy() -> None:
    args = build_ndi_relay_args(
        source_uri="udp://127.0.0.1:23101?pkt_size=1316",
        ndi_name="CivicCast  Public ",
    )
    # The relay eats the channel's existing TS output and publishes raw
    # uyvy422 (the NDI wire format) under a sanitized name.
    assert args[:2] == ["-i", "udp://127.0.0.1:23101?pkt_size=1316"]
    assert "-pix_fmt" in args and args[args.index("-pix_fmt") + 1] == "uyvy422"
    assert args[-3:] == ["-f", "libndi_newtek", "CivicCast Public"]


def test_supervisor_blocked_without_readiness_never_spawns() -> None:
    spawned: list[list[str]] = []
    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-ndi"),
        readiness_checker=lambda _path: _blocked(),
        process_starter=lambda args: spawned.append(args) or _FakeProcess(1),
    )

    status = supervisor.ensure_running()

    assert status.state == "blocked"
    assert "FFmpeg binary with NDI output" in status.next_step
    assert spawned == []


def test_supervisor_blocked_without_byo_binary() -> None:
    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="inline", ffmpeg_path=None),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda args: _FakeProcess(1),
    )

    status = supervisor.ensure_running()

    assert status.state == "blocked"
    assert "CIVICCAST_NDI_FFMPEG" in status.next_step


def test_supervisor_starts_and_reports_running() -> None:
    spawned: list[list[str]] = []

    def starter(args: list[str]) -> _FakeProcess:
        spawned.append(args)
        return _FakeProcess(4242)

    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-ndi"),
        readiness_checker=lambda _path: _ready(),
        process_starter=starter,
    )

    status = supervisor.ensure_running()
    assert status.state == "running"
    assert status.pid == 4242
    assert spawned[0][0] == "ffmpeg-ndi"
    # Steady state: a second pass does not respawn.
    assert supervisor.ensure_running().state == "running"
    assert len(spawned) == 1


def test_supervisor_restarts_dead_relay_with_backoff() -> None:
    clock = {"now": 1000.0}
    processes: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        proc = _FakeProcess(5000 + len(processes))
        processes.append(proc)
        return proc

    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-ndi"),
        readiness_checker=lambda _path: _ready(),
        process_starter=starter,
        monotonic=lambda: clock["now"],
    )

    assert supervisor.ensure_running().state == "running"
    processes[0].alive = False  # relay died

    # Immediately after death: restarting (backoff), not yet respawned.
    status = supervisor.ensure_running()
    assert status.state == "restarting"
    assert status.restarts == 0
    assert len(processes) == 1

    clock["now"] += 10.0  # past the first backoff window
    status = supervisor.ensure_running()
    assert status.state == "running"
    assert status.restarts == 1
    assert len(processes) == 2


def test_supervisor_stop_terminates_and_reports_stopped() -> None:
    proc_holder: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        proc = _FakeProcess(7777)
        proc_holder.append(proc)
        return proc

    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-ndi"),
        readiness_checker=lambda _path: _ready(),
        process_starter=starter,
    )
    assert supervisor.ensure_running().state == "running"

    supervisor.stop()

    assert proc_holder[0].killed is True
    assert supervisor.status().state == "stopped"


def test_supervisor_off_mode_reports_off_and_never_spawns() -> None:
    spawned: list[list[str]] = []
    supervisor = NdiRelaySupervisor(
        channel_id="public",
        ndi_name="CivicCast Public",
        source_uri="udp://127.0.0.1:23101",
        settings=NdiRelaySettings(mode="off", ffmpeg_path="ffmpeg-ndi"),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda args: spawned.append(args) or _FakeProcess(1),
    )

    assert supervisor.ensure_running().state == "off"
    assert spawned == []


def test_relay_name_validation_rejects_control_characters() -> None:
    with pytest.raises(ValueError):
        build_ndi_relay_args(
            source_uri="udp://127.0.0.1:23101",
            ndi_name="bad\r\nname",
        )
