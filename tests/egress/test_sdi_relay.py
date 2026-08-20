# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Supervised BYO-SDI relay tests (issue #117, option c)."""

from __future__ import annotations

import pytest

from civiccast.egress.sdi_relay import (
    SdiReadiness,
    SdiRelaySettings,
    SdiRelaySupervisor,
    build_sdi_relay_args,
    check_sdi_runtime,
)
from civiccast.stream._ffmpeg import FfmpegResult


def _ready() -> SdiReadiness:
    return SdiReadiness(status="ok", muxer_present=True, ffmpeg_detected=True, next_step="")


def _blocked() -> SdiReadiness:
    return SdiReadiness(
        status="decklink_muxer_missing",
        muxer_present=False,
        ffmpeg_detected=True,
        next_step=(
            "Install or build an FFmpeg binary with --enable-decklink "
            "(Blackmagic Desktop Video SDK), then retry."
        ),
    )


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
    monkeypatch.delenv("CIVICCAST_SDI_FFMPEG", raising=False)
    monkeypatch.delenv("CIVICCAST_SDI_RELAY", raising=False)
    settings = SdiRelaySettings.from_env()
    assert settings.mode == "inline"
    assert settings.ffmpeg_path is None

    monkeypatch.setenv("CIVICCAST_SDI_FFMPEG", r"C:\station\ffmpeg-decklink\ffmpeg.exe")
    monkeypatch.setenv("CIVICCAST_SDI_RELAY", "off")
    settings = SdiRelaySettings.from_env()
    assert settings.mode == "off"
    assert settings.ffmpeg_path == r"C:\station\ffmpeg-decklink\ffmpeg.exe"


def test_settings_reject_unknown_relay_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Audit ENG-012: a typo like CIVICCAST_SDI_RELAY=disabled used to
    # silently ENABLE supervision. Unknown modes must raise, naming the
    # valid values (matches the CIVICCAST_CHANNEL_AUTOMATION pattern).
    import pytest

    monkeypatch.setenv("CIVICCAST_SDI_RELAY", "disabled")
    with pytest.raises(ValueError, match="CIVICCAST_SDI_RELAY"):
        SdiRelaySettings.from_env()

    from civiccast.egress.ndi_relay import NdiRelaySettings

    monkeypatch.setenv("CIVICCAST_NDI_RELAY", "nope")
    with pytest.raises(ValueError, match="CIVICCAST_NDI_RELAY"):
        NdiRelaySettings.from_env()


def test_check_sdi_runtime_detects_decklink_muxer() -> None:
    def runner_with(output: str):  # type: ignore[no-untyped-def]
        return lambda args: FfmpegResult(returncode=0, stdout=output, stderr="")

    ok = check_sdi_runtime(
        "ffmpeg-decklink",
        ffmpeg_runner=runner_with(" E decklink        Blackmagic DeckLink output\n"),
    )
    assert ok.status == "ok"
    assert ok.muxer_present is True

    missing = check_sdi_runtime(
        "ffmpeg-plain",
        ffmpeg_runner=runner_with(" E mpegts          MPEG-TS\n"),
    )
    assert missing.status == "decklink_muxer_missing"
    assert "decklink" in missing.next_step.lower()


def test_relay_args_keep_embedded_audio_and_publish_uyvy() -> None:
    args = build_sdi_relay_args(
        source_uri="udp://127.0.0.1:23101?pkt_size=1316",
        device="DeckLink Mini Monitor 4K",
    )
    # SDI embeds audio (unlike the NDI relay's -an): PCM 48kHz stereo.
    assert args[:2] == ["-i", "udp://127.0.0.1:23101?pkt_size=1316"]
    assert "-pix_fmt" in args and args[args.index("-pix_fmt") + 1] == "uyvy422"
    assert "-c:a" in args and args[args.index("-c:a") + 1] == "pcm_s16le"
    assert args[-3:] == ["-f", "decklink", "DeckLink Mini Monitor 4K"]


def test_supervisor_blocked_without_byo_binary() -> None:
    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="DeckLink Mini Monitor 4K",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path=None),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda args: _FakeProcess(1),
    )

    status = supervisor.ensure_running()

    assert status.state == "blocked"
    assert "CIVICCAST_SDI_FFMPEG" in status.next_step


def test_supervisor_blocked_without_decklink_muxer_never_spawns() -> None:
    spawned: list[list[str]] = []
    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="DeckLink Mini Monitor 4K",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-plain"),
        readiness_checker=lambda _path: _blocked(),
        process_starter=lambda args: spawned.append(args) or _FakeProcess(1),
    )

    status = supervisor.ensure_running()

    assert status.state == "blocked"
    assert "decklink" in status.next_step.lower()
    assert spawned == []


def test_readiness_probe_result_is_cached_per_binary() -> None:
    # Audit ENG-008: the readiness subprocess probe used to run inside the
    # automation tick on every spawn attempt (30s worst case, stalling every
    # channel). The default checker caches per ffmpeg path with a TTL.
    from civiccast.egress.sdi_relay import cached_check_sdi_runtime, clear_readiness_cache

    clear_readiness_cache()
    clock = {"now": 1000.0}
    calls: list[list[str]] = []

    def runner(args: list[str]):  # type: ignore[no-untyped-def]
        calls.append(args)
        from civiccast.stream._ffmpeg import FfmpegResult

        return FfmpegResult(returncode=0, stdout=" E decklink\n", stderr="")

    first = cached_check_sdi_runtime(
        "ffmpeg-decklink", ffmpeg_runner=runner, monotonic=lambda: clock["now"]
    )
    second = cached_check_sdi_runtime(
        "ffmpeg-decklink", ffmpeg_runner=runner, monotonic=lambda: clock["now"]
    )
    assert first.status == "ok" and second.status == "ok"
    assert len(calls) == 1  # cached within the TTL

    clock["now"] += 600.0
    cached_check_sdi_runtime(
        "ffmpeg-decklink", ffmpeg_runner=runner, monotonic=lambda: clock["now"]
    )
    assert len(calls) == 2  # TTL expired: re-probed
    clear_readiness_cache()


def test_invalid_device_yields_honest_blocked_not_a_restart_loop() -> None:
    # Audit DOC-002: the docs promise an honest `blocked` for a bad device;
    # the code used to raise out of ensure_running into a restart loop.
    spawned: list[list[str]] = []
    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="Deck\nLink",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-decklink"),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda args: spawned.append(args) or _FakeProcess(1),
    )

    status = supervisor.ensure_running()
    again = supervisor.ensure_running()

    assert status.state == "blocked"
    assert "control characters" in status.next_step
    assert again.state == "blocked"
    assert spawned == []


def test_exited_relay_status_carries_the_stderr_tail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Audit ENG-013: "relay exited; restart pending" must say WHY - the
    # supervisor reads the child's captured stderr tail into last_error.
    stderr_file = tmp_path / "relay-stderr.log"
    stderr_file.write_text(
        "decklink @ 000001: Could not find device 'DeckLink Mini Monitor 4K'\n",
        encoding="utf-8",
    )
    proc = _FakeProcess(6001)
    proc.civiccast_stderr_path = str(stderr_file)  # type: ignore[attr-defined]

    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="DeckLink Mini Monitor 4K",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-decklink"),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda _args: proc,
    )

    assert supervisor.ensure_running().state == "running"
    proc.alive = False  # the relay dies
    status = supervisor.ensure_running()

    assert status.state == "restarting"
    assert status.last_error is not None
    assert "Could not find device" in status.last_error


def test_supervisor_starts_runs_and_restarts_with_backoff() -> None:
    clock = {"now": 1000.0}
    processes: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        proc = _FakeProcess(6000 + len(processes))
        processes.append(proc)
        return proc

    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="DeckLink Mini Monitor 4K",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-decklink"),
        readiness_checker=lambda _path: _ready(),
        process_starter=starter,
        monotonic=lambda: clock["now"],
    )

    status = supervisor.ensure_running()
    assert status.state == "running"
    assert processes[0].pid == 6000
    assert supervisor.ensure_running().state == "running"
    assert len(processes) == 1  # steady state, no respawn

    processes[0].alive = False
    assert supervisor.ensure_running().state == "restarting"
    clock["now"] += 10.0
    status = supervisor.ensure_running()
    assert status.state == "running"
    assert status.restarts == 1
    assert len(processes) == 2


def test_supervisor_stop_terminates() -> None:
    proc = _FakeProcess(7000)
    supervisor = SdiRelaySupervisor(
        channel_id="public",
        device="DeckLink Mini Monitor 4K",
        source_uri="udp://127.0.0.1:23101",
        settings=SdiRelaySettings(mode="inline", ffmpeg_path="ffmpeg-decklink"),
        readiness_checker=lambda _path: _ready(),
        process_starter=lambda args: proc,
    )
    assert supervisor.ensure_running().state == "running"

    supervisor.stop()

    assert proc.killed is True
    assert supervisor.status().state == "stopped"


def test_device_name_validation_rejects_control_characters() -> None:
    with pytest.raises(ValueError):
        build_sdi_relay_args(
            source_uri="udp://127.0.0.1:23101",
            device="bad\r\ndevice",
        )
