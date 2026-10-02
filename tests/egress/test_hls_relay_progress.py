# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BETA.10 live finding: process-alive-but-no-HLS-progress relay monitoring.

The 2026-09-23 live evidence on the installed station showed a government
channel whose ``playlist.m3u8`` froze at ``seg000001130.ts`` while BOTH the
supervised HLS relay ffmpeg child was a live pid AND the GStreamer encoder
worker kept advancing its ``CTRL output`` counters. ``HlsRelaySupervisor.
is_alive`` only answers "is the relay PROCESS alive", so the frozen-but-alive
relay stayed invisible and the ``hls`` sink stayed ``connected`` off the MAIN
encoder's UDP progress. That is the monitor gap this file pins.

Audit-repaired semantics under test:
  * PROGRESS is the last segment NAME only. Manifest size/tag churn with the
    same final ``.ts`` is NOT progress (finding 1).
  * ANY stalled live relay for a channel is reported, never masked by an
    advancing sibling sink (finding 2).
  * A live relay that never writes a window past its startup grace is reported
    unhealthy/recoverable once the daemon has confirmed production -- distinct
    from legitimate STARTING/no-source (finding 3).
  * The one-shot heal latch survives the frozen on-disk playlist left behind by
    the replaced child, so a heal cannot re-arm every bound into a restart
    storm (finding 4).

``tests/egress/test_hls_relay.py`` still owns the wiring/idempotency contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.hls_relay import HlsRelaySupervisor
from civiccast.egress.models import EgressCommand, EgressConfig, EgressSinkSpec
from civiccast.egress.source_plan import EgressSourcePlan, EgressSourceSegment
from civiccast.egress.store import InMemoryEgressStore


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str = "C:/CivicCast/live/gov", label: str = "Web") -> EgressSinkSpec:
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
    """Controllable monotonic stand-in so synthetic ``now`` values line up with
    the relay's own spawn-time grace arithmetic."""

    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _supervisor(*, clock: _FakeClock, stall_bound_s: float = 0.0):
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        calls.append(args)
        procs.append(_FakeProcess(pid=500 + len(procs)))
        return procs[-1]

    sup = HlsRelaySupervisor(starter=starter, stall_bound_s=stall_bound_s)
    sup._clock = clock
    return sup, calls, procs


def _write_playlist(
    directory: Path,
    *,
    last_segment: str,
    media_sequence: int = 0,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    playlist = directory / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n"
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}\n"
        f"#EXTINF:2.000,\n{last_segment}\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    return playlist


# --- finding 1: segment-only progress -------------------------------------------


def test_manifest_size_change_with_same_last_segment_is_not_progress(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 1): metadata churn with the SAME last ``.ts`` must
    NOT reset freshness. Only the segment name counts."""
    hls_dir = tmp_path / "gov-live"
    playlist = _write_playlist(hls_dir, last_segment="seg000000010.ts", media_sequence=0)
    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))

    sup.note_progress("gov", now=1000.0)
    # Same final segment, but the manifest body/size changed (tag churn).
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n"
        "#EXT-X-MEDIA-SEQUENCE:9999\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-09-23T21:50:08-06:00\n"
        "#EXTINF:2.000,\nseg000000010.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    clock.value = 1000.0 + 600.0
    sup.note_progress("gov", now=clock.value)  # must NOT treat this as progress

    assert sup.progress_stale("gov", now=clock.value) is True


def test_last_segment_change_is_progress(tmp_path: Path) -> None:
    """POSITIVE counterpart: a genuinely new final segment is progress."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")
    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))

    sup.note_progress("gov", now=1000.0)
    _write_playlist(hls_dir, last_segment="seg000000011.ts")
    clock.value = 1000.0 + 600.0
    sup.note_progress("gov", now=clock.value)

    assert sup.progress_stale("gov", now=clock.value) is False


# --- finding 2: any-sink stall is reported --------------------------------------


def test_one_stalled_sink_among_two_is_reported(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 2): a stalled sink must not be masked by an
    advancing sibling. Two HLS sinks -> two relays."""
    stalled_dir = tmp_path / "gov-stalled"
    live_dir = tmp_path / "gov-live"
    _write_playlist(stalled_dir, last_segment="seg000000010.ts")
    _write_playlist(live_dir, last_segment="seg000000020.ts")

    clock = _FakeClock(1000.0)
    sup, _calls, procs = _supervisor(clock=clock)
    sup.apply(
        _config(
            _hls_sink(str(stalled_dir), label="Stalled"),
            _hls_sink(str(live_dir), label="Live"),
        )
    )
    assert len(procs) == 2  # one child per sink, keyed channel|label

    sup.note_progress("gov", now=1000.0)
    # Only the LIVE sink advances; the stalled one keeps its segment.
    _write_playlist(live_dir, last_segment="seg000000021.ts")
    clock.value = 1000.0 + 600.0
    sup.note_progress("gov", now=clock.value)

    assert sup.progress_stale("gov", now=clock.value) is True


def test_both_sinks_advancing_is_not_stale(tmp_path: Path) -> None:
    """Positive counterpart for the any-sink semantics."""
    a_dir = tmp_path / "gov-a"
    b_dir = tmp_path / "gov-b"
    _write_playlist(a_dir, last_segment="seg000000010.ts")
    _write_playlist(b_dir, last_segment="seg000000020.ts")

    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(a_dir), label="A"), _hls_sink(str(b_dir), label="B")))
    sup.note_progress("gov", now=1000.0)
    _write_playlist(a_dir, last_segment="seg000000011.ts")
    _write_playlist(b_dir, last_segment="seg000000021.ts")
    clock.value = 1000.0 + 600.0
    sup.note_progress("gov", now=clock.value)

    assert sup.progress_stale("gov", now=clock.value) is False


# --- finding 3: never-emitted while producing -----------------------------------


def test_never_emitted_is_unknown_inside_startup_grace(tmp_path: Path) -> None:
    """STARTING/no-source: no window yet, still inside grace -> not a fault."""
    hls_dir = tmp_path / "gov-empty"  # never created
    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))

    assert sup.progress_stale("gov", now=1000.0 + 5.0) is None
    assert sup.never_emitted("gov", now=1000.0 + 5.0, startup_grace_s=20.0) is None


def test_never_emitted_past_grace_is_reported(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 3): a live relay that never wrote a window past
    its grace is a fault, not a permanent ``None``."""
    hls_dir = tmp_path / "gov-empty"
    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))

    assert sup.never_emitted("gov", now=1000.0 + 600.0, startup_grace_s=20.0) is True


def test_never_emitted_is_none_without_a_tracked_relay() -> None:
    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    assert sup.never_emitted("gov", now=1000.0, startup_grace_s=20.0) is None


# --- finding 4: heal latch survives the frozen on-disk playlist -----------------


def test_heal_latch_survives_the_frozen_on_disk_playlist(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 4): after a heal, the OLD playlist is still on
    disk. Its unchanged segment must NOT clear the latch, or the heal would
    re-arm every bound and become a restart storm."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")  # frozen window

    clock = _FakeClock(1000.0)
    sup, calls, procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    sup.note_progress("gov", now=1000.0)

    clock.value = 1000.0 + 600.0
    assert (
        sup.maybe_self_heal_stalled("gov", now=clock.value, producing=True, startup_grace_s=20.0)
        is True
    )
    assert len(calls) == 2

    # The replacement child has NOT written anything; the OLD playlist (same
    # last segment) is still on disk. Several ticks later, no second restart.
    for step in (1.0, 2.0, 3.0, 4.0):
        clock.value = 1000.0 + 600.0 + step * 100.0
        sup.note_progress("gov", now=clock.value)
        assert (
            sup.maybe_self_heal_stalled(
                "gov", now=clock.value, producing=True, startup_grace_s=20.0
            )
            is False
        )
    assert len(calls) == 2
    assert not procs[1].terminated


def test_heal_latch_clears_once_the_window_really_advances(tmp_path: Path) -> None:
    """Positive counterpart: a genuinely NEW segment past the pre-heal baseline
    ends the episode, so a later, separate stall may heal again."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")
    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    sup.note_progress("gov", now=1000.0)

    clock.value = 1000.0 + 600.0
    assert (
        sup.maybe_self_heal_stalled("gov", now=clock.value, producing=True, startup_grace_s=20.0)
        is True
    )
    # New child really advances the window.
    _write_playlist(hls_dir, last_segment="seg000000011.ts")
    clock.value += 1.0
    sup.note_progress("gov", now=clock.value)

    # A later, separate stall is healable again (bounded, not permanently off).
    clock.value += 600.0
    assert (
        sup.maybe_self_heal_stalled("gov", now=clock.value, producing=True, startup_grace_s=20.0)
        is True
    )
    assert len(calls) == 3


# --- baseline gating ------------------------------------------------------------


def test_self_heal_does_not_fire_without_actual_output(tmp_path: Path) -> None:
    """Not 'producing' (STARTING / no source yet) must never self-heal."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")
    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    sup.note_progress("gov", now=1000.0)

    clock.value = 1000.0 + 600.0
    assert (
        sup.maybe_self_heal_stalled("gov", now=clock.value, producing=False, startup_grace_s=20.0)
        is False
    )
    assert len(calls) == 1


def test_self_heal_does_not_fire_inside_the_startup_grace(tmp_path: Path) -> None:
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")
    clock = _FakeClock(1000.0)
    sup, calls, _procs = _supervisor(clock=clock)
    sup.apply(_config(_hls_sink(str(hls_dir))))
    sup.note_progress("gov", now=1000.0)

    clock.value = 1000.0 + 5.0
    assert (
        sup.maybe_self_heal_stalled("gov", now=clock.value, producing=True, startup_grace_s=20.0)
        is False
    )
    assert len(calls) == 1


# --- daemon-level: truthful health + gated, bounded self-heal --------------------
#
# These pin the daemon seam that consumes the supervisor. The FIRST one is the
# required BEHAVIORAL RED (audit finding 5): it drives a fake ALIVE relay that
# advertises stale progress through a real in-memory store and asserts the
# served health flips to False. On the OLD (pre-monitor) implementation the
# daemon had no progress check at all, so the sink stayed True and this fails by
# ASSERTION, not by AttributeError.


def _daemon_command(action: str = "start") -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action=action,  # type: ignore[arg-type]
        issued_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id=f"cmd-{action}",
    )


def _daemon_source_plan(tmp_path: Path) -> EgressSourcePlan:
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


def _stalled_daemon(tmp_path: Path, *, sink_label: str = "Web"):
    """A daemon whose alive hls relay serves a frozen (or absent) window."""
    hls_dir = tmp_path / f"gov-live-{sink_label}"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")

    relay_procs: list[_FakeProcess] = []

    def relay_starter(_args: list[str]) -> _FakeProcess:
        relay_procs.append(_FakeProcess(pid=900 + len(relay_procs)))
        return relay_procs[-1]

    clock = _FakeClock(50_000.0)
    relay = HlsRelaySupervisor(starter=relay_starter, stall_bound_s=0.0)
    relay._clock = clock
    store = InMemoryEgressStore()
    sink = EgressSinkSpec(kind="hls", label=sink_label, uri=str(hls_dir))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[sink])
    )
    store.enqueue_command(_daemon_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _daemon_source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=relay,
        # Always claims "connected" -- only the daemon's own progress check can
        # produce the False the tests assert.
        sink_health_provider=lambda _channel_id, _config, _metrics: {sink_label: True},
    )
    daemon._monotonic = clock  # type: ignore[method-assign]
    return daemon, store, relay, hls_dir, relay_procs, clock, sink_label


def test_daemon_reports_stalled_but_alive_relay_unhealthy_behavioral(tmp_path: Path) -> None:
    """BEHAVIORAL RED (audit finding 5): frozen-but-alive relay -> health False.

    Fails on the OLD implementation by assertion (``{'Web': True}`` != False),
    because no progress check existed to flip it. The relay process stays alive
    throughout.
    """
    daemon, store, _relay, _hls_dir, procs, clock, label = _stalled_daemon(tmp_path)

    assert daemon.process_once("gov") == 1
    daemon._on_air_confirmed_at["gov"] = clock()
    daemon.process_once("gov")  # anchors the segment baseline
    clock.value += 1.0
    daemon.process_once("gov")  # unchanged past the (zero) bound -> stale

    assert procs[0].poll() is None  # relay never died
    assert store.recent_health("gov", 1)[0].sink_connected == {label: False}


def test_daemon_does_not_self_heal_before_the_channel_is_producing(tmp_path: Path) -> None:
    """STARTING / no on-air evidence must never trigger a relay restart."""
    daemon, _store, _relay, _hls_dir, procs, clock, _label = _stalled_daemon(tmp_path)

    assert daemon.process_once("gov") == 1
    for _ in range(2):
        clock.value += 1.0
        daemon.process_once("gov")  # no on-air latch -> not producing

    assert len(procs) == 1
    assert not procs[0].terminated


def test_daemon_tick_sequence_no_restart_storm_with_frozen_playlist(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 4, daemon-level): after one heal, the frozen
    on-disk playlist must NOT re-arm a restart on later daemon ticks."""
    daemon, _store, relay, _hls_dir, procs, clock, _label = _stalled_daemon(tmp_path)

    assert daemon.process_once("gov") == 1
    # Relay is already well past its startup grace.
    next(iter(relay._relays.values())).started_at -= 10_000.0
    daemon._on_air_confirmed_at["gov"] = clock() - 10_000.0

    daemon.process_once("gov")  # anchor baseline
    clock.value += 1.0
    daemon.process_once("gov")  # heal #1
    assert len(procs) == 2

    # The replacement wrote nothing; the OLD playlist is still on disk. Many
    # further ticks must NOT spawn more children.
    for _ in range(5):
        clock.value += 60.0
        daemon._on_air_confirmed_at["gov"] = clock() - 10_000.0
        daemon.process_once("gov")
    assert len(procs) == 2
    assert not procs[1].terminated


def test_daemon_reports_never_emitted_relay_unhealthy_when_producing(tmp_path: Path) -> None:
    """NEGATIVE (audit finding 3, daemon-level): producing + never-emitted past
    grace must surface as unhealthy, not a permanent unknown."""
    hls_dir = tmp_path / "gov-empty"  # never created
    relay_procs: list[_FakeProcess] = []

    def relay_starter(_args: list[str]) -> _FakeProcess:
        relay_procs.append(_FakeProcess(pid=901))
        return relay_procs[0]

    clock = _FakeClock(50_000.0)
    relay = HlsRelaySupervisor(starter=relay_starter, stall_bound_s=0.0)
    relay._clock = clock
    store = InMemoryEgressStore()
    sink = EgressSinkSpec(kind="hls", label="Web", uri=str(hls_dir))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[sink])
    )
    store.enqueue_command(_daemon_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _daemon_source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=relay,
        sink_health_provider=lambda _channel_id, _config, _metrics: {"Web": True},
    )
    daemon._monotonic = clock  # type: ignore[method-assign]

    assert daemon.process_once("gov") == 1
    # Past the relay's startup grace with still no window on disk.
    clock.value += 600.0
    daemon._on_air_confirmed_at["gov"] = clock() - 10_000.0
    daemon.process_once("gov")

    assert store.recent_health("gov", 1)[0].sink_connected == {"Web": False}


def test_one_good_one_missing_sink_reports_never_emitted(tmp_path: Path) -> None:
    """NEGATIVE (audit follow-up): with two sinks, one advancing and one never
    having written a window past its grace, the missing sink must be reported --
    it must NOT be masked by the healthy sibling."""
    good_dir = tmp_path / "gov-good"
    _write_playlist(good_dir, last_segment="seg000000020.ts")
    missing_dir = tmp_path / "gov-missing"  # never created

    clock = _FakeClock(1000.0)
    sup, _calls, procs = _supervisor(clock=clock)
    sup.apply(
        _config(
            _hls_sink(str(good_dir), label="Good"),
            _hls_sink(str(missing_dir), label="Missing"),
        )
    )
    assert len(procs) == 2

    clock.value = 1000.0 + 600.0
    sup.note_progress("gov", now=clock.value)

    assert sup.never_emitted("gov", now=clock.value, startup_grace_s=20.0) is True


def test_one_good_one_missing_stays_unknown_inside_grace(tmp_path: Path) -> None:
    """Positive counterpart: the young missing sink is inside its grace, so no
    fault is claimed yet."""
    good_dir = tmp_path / "gov-good"
    _write_playlist(good_dir, last_segment="seg000000020.ts")
    missing_dir = tmp_path / "gov-missing"

    clock = _FakeClock(1000.0)
    sup, _calls, _procs = _supervisor(clock=clock)
    sup.apply(
        _config(
            _hls_sink(str(good_dir), label="Good"),
            _hls_sink(str(missing_dir), label="Missing"),
        )
    )

    assert sup.never_emitted("gov", now=1000.0 + 5.0, startup_grace_s=20.0) is None


def test_daemon_never_emitted_path_actually_self_heals(tmp_path: Path) -> None:
    """NEGATIVE (audit Fix A): the never-emitted branch used to set
    ``_hls_relay_dead`` and RETURN without healing. This proves the daemon now
    spawns a replacement relay for a producing channel whose relay never wrote a
    window."""
    hls_dir = tmp_path / "gov-empty"  # never created
    relay_procs: list[_FakeProcess] = []

    def relay_starter(_args: list[str]) -> _FakeProcess:
        relay_procs.append(_FakeProcess(pid=900 + len(relay_procs)))
        return relay_procs[-1]

    clock = _FakeClock(50_000.0)
    relay = HlsRelaySupervisor(starter=relay_starter, stall_bound_s=0.0)
    relay._clock = clock
    store = InMemoryEgressStore()
    sink = EgressSinkSpec(kind="hls", label="Web", uri=str(hls_dir))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[sink])
    )
    store.enqueue_command(_daemon_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _c: _daemon_source_plan(tmp_path),
        ffmpeg_starter=lambda _a: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=relay,
        sink_health_provider=lambda _c, _cfg, _m: {"Web": True},
    )
    daemon._monotonic = clock  # type: ignore[method-assign]

    assert daemon.process_once("gov") == 1
    assert len(relay_procs) == 1
    clock.value += 600.0
    daemon._on_air_confirmed_at["gov"] = clock() - 10_000.0
    daemon.process_once("gov")

    assert store.recent_health("gov", 1)[0].sink_connected == {"Web": False}
    assert len(relay_procs) == 2
    assert relay_procs[0].terminated


def test_old_api_alive_relay_with_frozen_window_reads_unhealthy(tmp_path: Path) -> None:
    """BEHAVIORAL RED (audit finding 5), old-API-only construction."""
    hls_dir = tmp_path / "gov-live"
    _write_playlist(hls_dir, last_segment="seg000000010.ts")

    relay = HlsRelaySupervisor(starter=lambda _args: _FakeProcess(pid=900))
    # Keep construction old-API-only (so OLD code raises nothing here), but
    # shrink the stall bound via the attribute so three quick ticks exceed it
    # without sleeping. On OLD code this attribute is simply unused.
    relay._stall_bound_s = 0.0
    store = InMemoryEgressStore()
    sink = EgressSinkSpec(kind="hls", label="Web", uri=str(hls_dir))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[sink])
    )
    store.enqueue_command(_daemon_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _c: _daemon_source_plan(tmp_path),
        ffmpeg_starter=lambda _a: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=relay,
        sink_health_provider=lambda _c, _cfg, _m: {"Web": True},
    )

    assert daemon.process_once("gov") == 1
    daemon._on_air_confirmed_at["gov"] = daemon._monotonic()
    daemon.process_once("gov")  # anchor the segment baseline
    # Backdate the observed progress so the unchanged window is unambiguously
    # past the (zero) bound on the next tick; on OLD code this attribute is
    # unused and the sink simply stays True.
    if hasattr(next(iter(relay._relays.values())), "progress_at"):
        next(iter(relay._relays.values())).progress_at -= 1000.0
    daemon._on_air_confirmed_at["gov"] = daemon._monotonic()
    daemon.process_once("gov")

    assert store.recent_health("gov", 1)[0].sink_connected == {"Web": False}
