# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U12 — an HLS relay (re)start must never lock a channel to a half program.

LIVE EVIDENCE (2026-09-24, coordinator): the government relay was restarted
mid-stream by the bounded stall self-heal (18:46:32, after the channel cut to
its fallback slate for a schedule gap). From then on its newest segments
probed as AUDIO ONLY while the public/education relays stayed H264+AAC, and it
stayed that way for hours until the channel itself was restarted. The same
shape happened earlier the same day (education 13:39:35, government 15:49:21).

THE OTHER DIRECTION (U13 measurement, coordinator audit): the same relay's
post-self-heal segments at 18:47:44-18:47:56 carried TS PID 256 (video) and no
PID 257 (audio) at all -- video-only, the mirror image of the same lock. A
municipal channel with picture and no sound fails acceptance exactly like one
with sound and no picture, so the rule below is symmetric over the stream
kinds a sink is configured to carry.

MECHANISM (reproduced with real ffmpeg against a live UDP input, see this
file's real-ffmpeg tests): ffmpeg fixes its OUTPUT stream set at probe time. A
relay child that starts while its input is missing a required kind inside the
probe window builds a half-program HLS output and never adds the missing kind
when it arrives later -- the widened 6M ``-analyzeduration``/``-probesize``
only narrows the window in which that can happen; it cannot remove it.

GOAL THIS FILE PINS: for a sink that carries video+audio, a relay either
produces video+audio or is restarted again promptly (bounded, logged) until it
does. Two halves:

* the relay's argv REQUIRES every kind the sink carries (``-map 0:v:0 -map
  0:a:0`` for a video+audio sink), so a probe missing one fails the child fast
  instead of silently serving a half-program window;
* the supervisor notices a child that cannot satisfy that requirement --
  exited, or alive with a newest segment missing a required kind -- and
  restarts it on a bounded, backed-off cadence: a few prompt attempts, then a
  low rate that logs an ERROR per attempt.

``tests/egress/test_hls_relay.py`` still owns the wiring/idempotency contract
and ``test_hls_relay_progress.py`` the served-window progress contract.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest

from civiccast.egress import hls_relay as hls_relay_mod
from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.hls_relay import (
    HlsRelaySupervisor,
    _Relay,
    _relay_map_args,
    _segment_stream_kinds,
    _sink_required_kinds,
    hls_relay_uri_for,
)
from civiccast.egress.models import EgressCommand, EgressConfig, EgressSinkSpec
from civiccast.egress.sinks import HlsSink
from civiccast.egress.source_plan import EgressSourcePlan, EgressSourceSegment
from civiccast.egress.store import InMemoryEgressStore
from civiccast.stream._ffmpeg import FfmpegProcessHandle

# --- unit layer: fake starter, controllable clock ---------------------------------


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str, label: str = "Web") -> EgressSinkSpec:
    return EgressSinkSpec(kind="hls", label=label, uri=uri)


class _FakeProcess:
    def __init__(self, *, pid: int = 500, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.terminated = True
        self.returncode = 0
        return 0


class _FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _write_playlist(directory: Path, *, last_segment: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    playlist = directory / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-MEDIA-SEQUENCE:0\n"
        f"#EXTINF:2.000,\n{last_segment}\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    return playlist


def _supervisor(
    *,
    clock: _FakeClock,
    probe: Callable[[Path], frozenset[str] | None] | None = None,
    retry_delay_s: float = 1.0,
    slow_delay_s: float = 10.0,
    stall_bound_s: float = 30.0,
) -> tuple[HlsRelaySupervisor, list[list[str]], list[_FakeProcess]]:
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        calls.append(args)
        procs.append(_FakeProcess(pid=500 + len(procs)))
        return procs[-1]

    sup = HlsRelaySupervisor(
        starter=starter,
        stall_bound_s=stall_bound_s,
        segment_probe=probe,
        stream_retry_delay_s=retry_delay_s,
        stream_retry_slow_delay_s=slow_delay_s,
    )
    sup._clock = clock
    return sup, calls, procs


def _only_relay(sup: HlsRelaySupervisor) -> _Relay:
    return next(iter(sup._relays.values()))


def _expire_startup_grace(sup: HlsRelaySupervisor) -> None:
    """Age the relay child past its own startup grace, so the U12 alive-shape
    probe is allowed to judge it."""
    relay = _only_relay(sup)
    assert relay.started_at is not None
    relay.started_at -= 100.0


# --- the relay's argv must REQUIRE every kind the sink carries --------------------


def test_relay_argv_requires_video_and_audio_for_a_video_sink(tmp_path: Path) -> None:
    """A sink that carries video AND audio must have BOTH required in the relay
    argv, so a probe missing either fails the child fast instead of locking the
    HLS output to a half program -- audio-only (the 18:46:32 symptom) or
    video-only (U13's 18:47:44 measurement)."""
    sup, calls, _procs = _supervisor(clock=_FakeClock())
    sink = _hls_sink(str(tmp_path / "gov"))
    sup.apply(_config(sink))

    args = calls[0]
    maps = [args[index + 1] for index, item in enumerate(args) if item == "-map"]
    assert "0:v:0" in maps, f"relay argv must require video; maps={maps}"
    assert "0:a:0" in maps, f"relay argv must require audio; maps={maps}"
    assert "0:a:0?" not in maps, f"audio must not be optional for a video+audio sink; maps={maps}"
    # -map is an OUTPUT option: after -i, before the muxer args HlsSink owns.
    assert args.index("-map") > args.index("-i")
    output_args = HlsSink(sink).output_args()
    assert args[-len(output_args) :] == output_args


def test_relay_argv_leaves_an_audio_only_sink_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sink that does not carry video keeps today's argv byte-for-byte: no
    -map at all, so ffmpeg's default selection still applies."""
    monkeypatch.setattr(HlsSink, "carries_video", False)
    sup, calls, _procs = _supervisor(clock=_FakeClock())
    sup.apply(_config(_hls_sink(str(tmp_path / "gov"))))

    assert "-map" not in calls[0]


def test_relay_argv_leaves_audio_optional_for_a_video_only_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The video-without-audio case, kept optional rather than fatal: video is
    still required, audio is mapped with ``?`` so an audio-less input stays
    relay-able. No sink shipped today declares this (see ``EgressSink``), so
    this pins the behaviour of a variant that one day sets
    ``carries_audio = False``."""
    monkeypatch.setattr(HlsSink, "carries_audio", False)
    sup, calls, _procs = _supervisor(clock=_FakeClock())
    sup.apply(_config(_hls_sink(str(tmp_path / "gov"))))

    args = calls[0]
    maps = [args[index + 1] for index, item in enumerate(args) if item == "-map"]
    assert maps == ["0:v:0", "0:a:0?"], maps


def test_shipped_stream_retry_cadence_and_mapping_are_the_documented_ones() -> None:
    """The SHIPPED cadence, not a test-tuned one: three prompt attempts at 5s,
    then one attempt per 60s, plus the exact required-kind mapping. The other
    tests tighten the delays to fit a test-scale wall clock, so this is the only
    place the values an operator actually gets are pinned."""
    assert _relay_map_args(carries_video=True, carries_audio=True) == (
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
    )
    assert _relay_map_args(carries_video=True, carries_audio=False) == (
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    )
    assert _relay_map_args(carries_video=False, carries_audio=True) == ()
    assert hls_relay_mod._DEFAULT_STREAM_RETRY_DELAY_S == 5.0
    assert hls_relay_mod._DEFAULT_STREAM_RETRY_SLOW_DELAY_S == 60.0
    assert hls_relay_mod._STREAM_FAST_ATTEMPTS == 3

    default = HlsRelaySupervisor()
    assert default._stream_retry_delay_s == 5.0
    assert default._stream_retry_slow_delay_s == 60.0
    assert default._segment_probe is _segment_stream_kinds


def test_required_kinds_follow_the_sink_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the supervisor judges a sink's window against: both kinds for a
    video+audio sink, video only for a video-only sink, and NOTHING for an
    audio-only sink (never judged -- it keeps its audio-only output)."""
    uri = str(tmp_path / "gov")
    assert _sink_required_kinds(uri) == frozenset({"video", "audio"})

    monkeypatch.setattr(HlsSink, "carries_audio", False)
    assert _sink_required_kinds(uri) == frozenset({"video"})

    monkeypatch.setattr(HlsSink, "carries_video", False)
    assert _sink_required_kinds(uri) == frozenset()


# --- bounded, backed-off restart of a child that cannot carry video --------------


def test_exited_relay_is_restarted(tmp_path: Path) -> None:
    """NEGATIVE (the live fault, supervisor layer): a relay child that EXITED
    (ffmpeg fails fast on a video-less probe) must be restarted, not left dead
    until the channel's next encoder start/reload."""
    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(tmp_path / "gov"))))
    procs[0].returncode = 1  # ffmpeg exited: probed input had no video stream

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is True
    )
    assert len(calls) == 2
    assert procs[0].terminated
    assert not procs[1].terminated


def test_restart_cadence_is_backed_off_not_a_tight_loop(tmp_path: Path) -> None:
    """NEGATIVE (bounded): once a restart has been attempted, the next tick
    (inside the retry delay) must NOT spawn another child, however many ticks
    arrive. A dead relay is otherwise re-seen on EVERY daemon tick."""
    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock, retry_delay_s=5.0, slow_delay_s=60.0)
    sup.apply(_config(_hls_sink(str(tmp_path / "gov"))))
    procs[0].returncode = 1

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is True
    )
    assert len(calls) == 2
    procs[1].returncode = 1  # the replacement failed too (input still has no video)

    for step in range(1, 20):  # 19 ticks inside the 5s retry delay
        clock.value = 1000.0 + step * 0.25
        assert (
            sup.maybe_restore_missing_streams(
                "gov", now=clock.value, producing=True, startup_grace_s=20.0
            )
            is False
        )
    assert len(calls) == 2  # no restart storm

    clock.value = 1000.0 + 5.0  # the retry delay has elapsed
    assert (
        sup.maybe_restore_missing_streams(
            "gov", now=clock.value, producing=True, startup_grace_s=20.0
        )
        is True
    )
    assert len(calls) == 3


def test_restarts_slow_to_a_low_rate_after_the_fast_attempts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The brief's bound: a few prompt attempts, then further attempts only at
    a LOW rate, each logging an ERROR. An explicit tick schedule proves both
    the spacing and the log-level transition: the child keeps failing on a
    video-less input, so every attempt is a genuine new one."""
    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock, retry_delay_s=1.0, slow_delay_s=30.0)
    sup.apply(_config(_hls_sink(str(tmp_path / "gov"))))

    # (tick time, does this tick attempt a restart)
    schedule = [
        (1000.0, True),  # attempt 1
        (1000.5, False),  # inside the 1s retry delay -> no child
        (1001.0, True),  # attempt 2
        (1002.0, True),  # attempt 3
        (1003.0, True),  # attempt 4: first ERROR, cadence drops to the slow delay
        (1010.0, False),  # inside the 30s slow delay -> no child
        (1032.9, False),  # still inside it
        (1033.0, True),  # attempt 5, at the low rate
    ]
    restarts: list[float] = []
    with caplog.at_level("WARNING", logger="civiccast.egress.hls_relay"):
        for at, expected in schedule:
            procs[-1].returncode = 1  # the input still has no video: it keeps failing
            clock.value = at
            before = len(calls)
            result = sup.maybe_restore_missing_streams(
                "gov", now=at, producing=True, startup_grace_s=20.0
            )
            assert result is expected, f"tick at {at} restarted={result}, want {expected}"
            if len(calls) > before:
                restarts.append(at)

    assert restarts == [1000.0, 1001.0, 1002.0, 1003.0, 1033.0], restarts
    assert len(calls) == 6  # the spawn at apply() + 5 attempts, and no more
    # The RATE is the bound: three prompt attempts, then one per 30s.
    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 2, [record.getMessage() for record in caplog.records]
    # An ERROR an operator cannot act on is noise: it must name the fault.
    assert all("exited without a live window" in record.getMessage() for record in errors)


def test_alive_relay_serving_audio_only_segments_is_restarted(tmp_path: Path) -> None:
    """NEGATIVE (post-(re)start verification): an ALIVE relay whose newest
    served segment carries no video is the live symptom -- it must be
    restarted, not merely reported."""
    hls_dir = tmp_path / "gov"
    playlist = _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")

    probed: list[Path] = []

    def probe(path: Path) -> frozenset[str] | None:
        probed.append(path)
        return frozenset({"audio"})  # audio only -- the 18:46:32 probe result

    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)  # well past its startup grace

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is True
    )
    assert probed == [playlist.parent / "seg000000002.ts"]
    assert len(calls) == 2
    assert procs[0].terminated


def test_alive_relay_serving_video_only_segments_is_restarted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """NEGATIVE, the MIRROR image (coordinator audit / U13): an ALIVE relay
    whose newest served segment carries video but NO audio -- the government
    relay's 18:47:44-18:47:56 shape, PID 256 and no PID 257 -- must be
    restarted too, and the operator must be told which stream is missing."""
    hls_dir = tmp_path / "gov"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")

    def probe(_path: Path) -> frozenset[str] | None:
        return frozenset({"video"})  # video only -- U13's measurement

    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)

    with caplog.at_level("WARNING", logger="civiccast.egress.hls_relay"):
        assert (
            sup.maybe_restore_missing_streams(
                "gov", now=1000.0, producing=True, startup_grace_s=20.0
            )
            is True
        )
    assert len(calls) == 2
    assert procs[0].terminated
    restarts = [
        record for record in caplog.records if "restarting the relay child" in record.getMessage()
    ]
    assert len(restarts) == 1, [record.getMessage() for record in caplog.records]
    message = restarts[0].getMessage()
    # The operator must be told WHICH stream is missing, not just that the
    # window is bad -- the two directions need different fixes upstream.
    assert "missing its audio stream" in message, message
    assert "carries only video" in message, message


def test_a_video_audio_segment_is_verified_once_and_not_reprobed(tmp_path: Path) -> None:
    """Positive counterpart: a probe that FINDS every required kind ends the
    fault episode -- no restart, no further probes for that child (one ffprobe
    per child, not one per tick)."""
    hls_dir = tmp_path / "gov"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")

    probed: list[Path] = []

    def probe(path: Path) -> frozenset[str] | None:
        probed.append(path)
        return frozenset({"video", "audio"})

    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)

    for step in range(4):
        clock.value = 1000.0 + step * 5.0
        assert (
            sup.maybe_restore_missing_streams(
                "gov", now=clock.value, producing=True, startup_grace_s=20.0
            )
            is False
        )
    assert len(calls) == 1
    assert len(probed) == 1  # verified once, then latched off


def test_video_only_sink_is_never_restored_for_missing_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sink that carries video but NOT audio is judged on video only: a
    video-only window is exactly its correct output, so it must not be
    restarted for the audio it was never configured to carry."""
    hls_dir = tmp_path / "gov-video"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")
    monkeypatch.setattr(HlsSink, "carries_audio", False)

    def probe(_path: Path) -> frozenset[str] | None:
        return frozenset({"video"})

    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is False
    )
    assert len(calls) == 1


def test_probe_waits_for_the_startup_grace(tmp_path: Path) -> None:
    """A just-(re)started child must not be judged before it can write: no
    probe, no restart, inside its startup grace."""
    hls_dir = tmp_path / "gov"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")

    def probe(_path: Path) -> frozenset[str] | None:
        raise AssertionError("must not probe inside the startup grace")

    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))

    assert (
        sup.maybe_restore_missing_streams(
            "gov", now=1000.0 + 5.0, producing=True, startup_grace_s=20.0
        )
        is False
    )
    assert len(calls) == 1


def test_audio_only_sink_is_never_restored_for_missing_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An audio-only sink keeps its audio-only output: the video requirement
    (and the audio-only fault) does not apply to it at all."""
    hls_dir = tmp_path / "gov-audio"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")
    monkeypatch.setattr(HlsSink, "carries_video", False)

    def probe(_path: Path) -> frozenset[str] | None:
        raise AssertionError("an audio-only sink must never be probed for a stream kind")

    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is False
    )
    assert len(calls) == 1


def test_restore_does_not_fire_without_a_tracked_relay() -> None:
    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock)

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=True, startup_grace_s=20.0)
        is False
    )
    assert calls == []


def test_alive_probe_does_not_fire_while_the_channel_is_not_producing(tmp_path: Path) -> None:
    """STARTING / no-source: a channel that is not producing has no business
    being restarted for a video-less window it has not yet had time to fill."""
    hls_dir = tmp_path / "gov"
    _write_playlist(hls_dir, last_segment="seg000000002.ts")
    (hls_dir / "seg000000002.ts").write_bytes(b"not-really-a-segment")

    def probe(_path: Path) -> frozenset[str] | None:
        raise AssertionError("must not probe a channel that is not producing")

    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock, probe=probe)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    _expire_startup_grace(sup)

    assert (
        sup.maybe_restore_missing_streams("gov", now=1000.0, producing=False, startup_grace_s=20.0)
        is False
    )
    assert len(calls) == 1


# --- daemon layer: the tick actually drives it ------------------------------------


def _daemon_command(action: str = "start") -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action=action,  # type: ignore[arg-type]
        issued_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id=f"cmd-{action}",
    )


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "source-a.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=1,
                source_ref="asset-council",
            )
        ],
    )


def _relay_daemon(
    tmp_path: Path,
    hls_dir: Path,
    *,
    supervisor: HlsRelaySupervisor | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[
    EgressDaemon, InMemoryEgressStore, HlsRelaySupervisor, list[_FakeProcess], Callable[[], float]
]:
    relay_procs: list[_FakeProcess] = []

    def relay_starter(_args: list[str], *, stderr_path: Path | None = None) -> _FakeProcess:
        relay_procs.append(_FakeProcess(pid=900 + len(relay_procs)))
        return relay_procs[-1]

    # A frozen fake clock is what the unit layer wants (deterministic
    # arithmetic on the attempt cadence); the real-ffmpeg test needs the REAL
    # monotonic clock, because the supervisor's backoff and startup grace are
    # wall-clock quantities -- with a frozen clock the first restart pins
    # ``stream_retry_not_before`` ahead of every later tick and the bounded
    # cadence can never advance (measured: the relay stayed dead and the
    # served window stayed empty).
    resolved_clock: Callable[[], float] = clock if clock is not None else _FakeClock(50_000.0)
    relay = supervisor or HlsRelaySupervisor(starter=relay_starter, stall_bound_s=30.0)
    relay._clock = resolved_clock
    store = InMemoryEgressStore()
    sink = EgressSinkSpec(kind="hls", label="Web", uri=str(hls_dir))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[sink])
    )
    store.enqueue_command(_daemon_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        # The daemon types this seam as the real handle class (not a Protocol),
        # so the double needs the cast the relay supervisor's starter does not.
        ffmpeg_starter=lambda _args: cast(
            FfmpegProcessHandle, _FakeProcess(pid=4242, returncode=None)
        ),
        hls_relay_supervisor=relay,
        sink_health_provider=lambda _channel_id, _config, _metrics: {"Web": True},
    )
    daemon._monotonic = resolved_clock
    return daemon, store, relay, relay_procs, resolved_clock


def test_daemon_tick_respawns_a_dead_relay(tmp_path: Path) -> None:
    """BEHAVIORAL RED: on the OLD implementation a dead relay child was only
    ever restarted by the channel's next encoder start/reload -- so this tick
    spawned nothing and the assertion failed. The daemon's own poll must
    restart it (the live fix for a relay that exited on a video-less probe)."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")
    clock = _FakeClock(50_000.0)
    daemon, _store, _relay, procs, _clock = _relay_daemon(tmp_path, hls_dir, clock=clock)

    assert daemon.process_once("gov") == 1
    assert len(procs) == 1
    procs[0].returncode = 1  # ffmpeg exited: probed input had no video stream

    daemon._on_air_confirmed_at["gov"] = clock()
    clock.value += 10.0
    daemon.process_once("gov")

    assert len(procs) == 2, "the daemon tick must restart a dead relay child"
    assert procs[0].terminated
    assert not procs[1].terminated


# --- real ffmpeg: the live fault, end to end --------------------------------------

_REAL_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

pytestmark_real = pytest.mark.skipif(
    not _REAL_FFMPEG, reason="real-ffmpeg relay proof needs ffmpeg + ffprobe on PATH"
)


def _audio_only_producer(port: int) -> subprocess.Popen[str]:
    """Streams an audio-only MPEG-TS to ``port`` in real time until terminated.

    One stream only, so ffmpeg's mpegts muxer puts it on PID 0x100 -- the same
    PID the video-joining producer below puts its AUDIO on (see
    ``_audio_video_producer``), which is what keeps the two consecutive
    producers' PID layout stable across the swap.
    """
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "mpegts",
            f"udp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _audio_video_producer(port: int) -> subprocess.Popen[str]:
    """Same port, now carrying H.264 as well -- the "video arrives late" half
    of the live transition.

    AUDIO IS MAPPED FIRST deliberately, so the mpegts muxer keeps AAC on PID
    0x100 and adds video on PID 0x101. With video first (PID 0x100 = H.264,
    audio 0x101) the swap reuses a PID for a different codec and ffmpeg's
    demuxer rejects the stream ("h264 bitstream malformed, no startcode
    found" -- measured), which would make this test measure a PID collision
    instead of the relay's stream selection.
    """
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-map",
            "0:a:0",
            "-map",
            "1:v:0",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mpegts",
            f"udp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _newest_segment(directory: Path) -> str | None:
    playlist = directory / "playlist.m3u8"
    if not playlist.exists():
        return None
    last: str | None = None
    for line in playlist.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().endswith(".ts"):
            last = line.strip()
    return last


def _video_only_producer(port: int) -> subprocess.Popen[str]:
    """Streams a VIDEO-ONLY MPEG-TS to ``port`` in real time until terminated.

    One stream only, so the mpegts muxer puts H.264 on PID 0x100 -- the same
    PID the video-then-audio producer below keeps its VIDEO on (see
    ``_video_then_audio_producer``), which is what keeps the two consecutive
    producers' PID layout stable across the swap.
    """
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mpegts",
            f"udp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _video_then_audio_producer(port: int) -> subprocess.Popen[str]:
    """Same port, now carrying AAC as well -- the "audio arrives late" half.

    VIDEO IS MAPPED FIRST deliberately, so the mpegts muxer keeps H.264 on PID
    0x100 and adds AAC on PID 0x101. The predecessor
    (``_video_only_producer``) already has H.264 on 0x100, so the swap never
    re-uses a PID for a different codec -- with audio first it would, and
    ffmpeg's demuxer rejects the stream ("h264 bitstream malformed, no
    startcode found" -- measured), which would make this test measure a PID
    collision instead of the relay's stream selection.
    """
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "mpegts",
            f"udp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _probe_stream_kinds(path: Path) -> set[str]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return set()
    try:
        streams = json.loads(completed.stdout).get("streams", [])
    except json.JSONDecodeError:
        return set()
    kinds: set[str] = set()
    for stream in streams:
        if isinstance(stream, dict):
            kind = stream.get("codec_type")
            if isinstance(kind, str):
                kinds.add(kind)
    return kinds


@pytestmark_real
def test_segment_probe_verdicts_are_tri_state(tmp_path: Path) -> None:
    """The probe the alive-shape recovery judges on, against real files.

    The set of kinds the segment actually carries -- ``{"video"}``,
    ``{"audio"}``, or both -- and ``None`` -- claim nothing, never restart --
    for anything ffprobe cannot read (a missing file, or bytes that are not a
    transport stream). The ``None`` arm is the safety property: a restart must
    never be triggered by the supervisor failing to tell rather than by it
    seeing a kind genuinely missing from the window.
    """
    encoded = tmp_path / "with-video.ts"
    audio_only = tmp_path / "audio-only.ts"
    for path, inputs in (
        (
            encoded,
            (
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=15",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-g",
                "15",
                "-pix_fmt",
                "yuv420p",
            ),
        ),
        (audio_only, ("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-c:a", "aac")),
    ):
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *inputs,
                "-t",
                "1",
                "-f",
                "mpegts",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr

    garbage = tmp_path / "garbage.ts"
    garbage.write_bytes(b"this is not a transport stream")

    assert _segment_stream_kinds(encoded) == frozenset({"video"})
    assert _segment_stream_kinds(audio_only) == frozenset({"audio"})
    assert _segment_stream_kinds(tmp_path / "missing.ts") is None
    assert _segment_stream_kinds(garbage) is None


@pytestmark_real
def test_relay_restarted_mid_stream_ends_up_with_video(tmp_path: Path) -> None:
    """THE UNIT'S GOAL, end to end with real ffmpeg (RED on the old code).

    A relay child starts while its UDP input carries audio only; video joins
    ~8s later -- LATER than the child's own probe window, so the child has
    already committed to its output stream set when video arrives (the live
    slate-transition shape). With no required video map the child locks to an
    audio-only HLS output and NEVER recovers -- the live symptom, and the
    assertion this test makes fails on that code. With the required map the
    child fails fast, the daemon's bounded restore restarts it, and the
    replacement's output carries H.264 again.

    Real pieces throughout: the real ``EgressDaemon._poll_hls_relay`` tick on
    the REAL monotonic clock (the cadence is a wall-clock quantity), the real
    ``HlsRelaySupervisor``, real ffmpeg children, a real UDP socket, and an
    ffprobe of the served segment (not of the stream it came from).
    """
    hls_dir = tmp_path / "gov-live"
    hls_dir.mkdir(parents=True, exist_ok=True)
    relay_port = int(urlsplit(hls_relay_uri_for(str(hls_dir))).port or 0)
    assert relay_port > 0

    dead_air = None
    late_video = None
    # A prompt retry so the proof fits a test-scale wall clock; the SHIPPED
    # defaults (5s / 60s) are asserted separately at the unit layer.
    supervisor = HlsRelaySupervisor(stream_retry_delay_s=2.0, stream_retry_slow_delay_s=4.0)
    daemon, _store, relay, _procs, _clock = _relay_daemon(
        tmp_path, hls_dir, supervisor=supervisor, clock=time.monotonic
    )
    try:
        # The loopback input is ALREADY streaming audio-only when the child
        # starts: the live shape is a relay restarting INTO a running feed
        # (the station's fallback slate), not a feed starting under a relay.
        dead_air = _audio_only_producer(relay_port)
        time.sleep(0.5)
        assert daemon.process_once("gov") == 1
        daemon._on_air_confirmed_at["gov"] = time.monotonic()

        started = time.monotonic()
        swapped_to_video = False
        newest: str | None = None
        kinds: set[str] = set()
        while time.monotonic() - started < 30.0:
            time.sleep(0.25)
            daemon.process_once("gov")
            if not swapped_to_video and time.monotonic() - started >= 8.0:
                swapped_to_video = True
                # One producer per port: the audio-only feed is stopped and
                # waited for BEFORE video joins, so the relay never reads an
                # interleaving of two independent transport streams.
                dead_air.terminate()
                dead_air.wait(timeout=5)
                late_video = _audio_video_producer(relay_port)
            newest = _newest_segment(hls_dir)
            if newest is not None and (hls_dir / newest).exists():
                kinds = _probe_stream_kinds(hls_dir / newest)
                if {"video", "audio"} <= kinds:
                    break

        assert newest is not None and (hls_dir / newest).exists(), (
            "the relay served no readable HLS window at all within 30s"
        )
        if "video" not in kinds:
            # The newest segment may still be mid-write (ffmpeg appends the
            # playlist entry before it closes the segment). Re-probe once it
            # has settled rather than judging a partial file.
            time.sleep(1.5)
            newest = _newest_segment(hls_dir) or newest
            kinds = _probe_stream_kinds(hls_dir / newest)
        size = (hls_dir / newest).stat().st_size
        assert "video" in kinds, (
            f"relay output stayed audio-only after the restore: newest={newest} "
            f"({size} bytes) streams={sorted(kinds)} (the live government symptom)"
        )
        assert "audio" in kinds, (
            f"relay output lost audio: newest={newest} ({size} bytes) kinds={kinds}"
        )
    finally:
        for process in (dead_air, late_video):
            if process is not None and process.poll() is None:
                process.terminate()
        for process in (dead_air, late_video):
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover - teardown
                    process.kill()
        relay.stop_channel("gov")


@pytestmark_real
def test_relay_restarted_mid_stream_ends_up_with_audio(tmp_path: Path) -> None:
    """THE MIRROR GOAL, end to end with real ffmpeg (RED on the video-only code).

    A relay child starts while its UDP input carries VIDEO only; audio joins
    ~8s later -- LATER than the child's own probe window, so the child has
    already committed to its output stream set when audio arrives. With audio
    mapped merely OPTIONALLY (``-map 0:a:0?``, this repository before the
    coordinator's audit) the child locks to a video-only HLS output and NEVER
    recovers -- the government relay's 18:47:44-18:47:56 shape, and the
    assertion below fails on that code. With audio required the child fails
    fast, the daemon's bounded restore restarts it, and the replacement's
    output carries AAC again.
    """
    hls_dir = tmp_path / "gov-live-audio"
    hls_dir.mkdir(parents=True, exist_ok=True)
    relay_port = int(urlsplit(hls_relay_uri_for(str(hls_dir))).port or 0)
    assert relay_port > 0

    silent_motion = None
    late_audio = None
    supervisor = HlsRelaySupervisor(stream_retry_delay_s=2.0, stream_retry_slow_delay_s=4.0)
    daemon, _store, relay, _procs, _clock = _relay_daemon(
        tmp_path, hls_dir, supervisor=supervisor, clock=time.monotonic
    )
    try:
        silent_motion = _video_only_producer(relay_port)
        time.sleep(0.5)
        assert daemon.process_once("gov") == 1
        daemon._on_air_confirmed_at["gov"] = time.monotonic()

        started = time.monotonic()
        swapped_to_audio = False
        newest: str | None = None
        kinds: set[str] = set()
        while time.monotonic() - started < 30.0:
            time.sleep(0.25)
            daemon.process_once("gov")
            if not swapped_to_audio and time.monotonic() - started >= 8.0:
                swapped_to_audio = True
                # One producer per port, exactly as in the video case: the
                # video-only feed stops and is waited for BEFORE audio joins.
                silent_motion.terminate()
                silent_motion.wait(timeout=5)
                late_audio = _video_then_audio_producer(relay_port)
            newest = _newest_segment(hls_dir)
            if newest is not None and (hls_dir / newest).exists():
                kinds = _probe_stream_kinds(hls_dir / newest)
                if {"video", "audio"} <= kinds:
                    break

        assert newest is not None and (hls_dir / newest).exists(), (
            "the relay served no readable HLS window at all within 30s"
        )
        if "audio" not in kinds:
            # The newest segment may still be mid-write; re-probe once it has
            # settled rather than judging a partial file.
            time.sleep(1.5)
            newest = _newest_segment(hls_dir) or newest
            kinds = _probe_stream_kinds(hls_dir / newest)
        size = (hls_dir / newest).stat().st_size
        assert "audio" in kinds, (
            f"relay output stayed video-only after the restore: newest={newest} "
            f"({size} bytes) streams={sorted(kinds)} (U13's 18:47:44 symptom)"
        )
        assert "video" in kinds, (
            f"relay output lost video: newest={newest} ({size} bytes) kinds={kinds}"
        )
    finally:
        for process in (silent_motion, late_audio):
            if process is not None and process.poll() is None:
                process.terminate()
        for process in (silent_motion, late_audio):
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover - teardown
                    process.kill()
        relay.stop_channel("gov")


@pytestmark_real
def test_relay_argv_produces_video_and_audio_for_a_plain_video_input(tmp_path: Path) -> None:
    """Guard for the required-video map itself: an ordinary video+audio UDP
    input still produces a rotating HLS window carrying BOTH streams. Without
    this, a broken ``-map`` would look like a fix for the audio-only lock."""
    hls_dir = tmp_path / "gov-happy"
    hls_dir.mkdir(parents=True, exist_ok=True)
    relay_port = int(urlsplit(hls_relay_uri_for(str(hls_dir))).port or 0)

    supervisor = HlsRelaySupervisor()
    config = _config(_hls_sink(str(hls_dir)))
    supervisor.apply(config)
    producer = _audio_video_producer(relay_port)
    try:
        started = time.monotonic()
        kinds: set[str] = set()
        while time.monotonic() - started < 16.0:
            time.sleep(0.5)
            newest = _newest_segment(hls_dir)
            if newest is not None and (hls_dir / newest).exists():
                kinds = _probe_stream_kinds(hls_dir / newest)
                if kinds == {"video", "audio"}:
                    break
        assert kinds == {"video", "audio"}, (
            f"a plain video+audio input must relay video AND audio; got {sorted(kinds)}"
        )
    finally:
        if producer.poll() is None:
            producer.terminate()
        try:
            producer.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - teardown
            producer.kill()
        supervisor.stop_channel("gov")
