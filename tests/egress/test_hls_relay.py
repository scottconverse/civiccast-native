# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""DEFECT A — the GStreamer engine's hls-sink relay.

Unit layer only (fake ffmpeg starter): supervisor lifecycle, config
rewriting, idempotency, graceful degradation when ffmpeg is unavailable.
See ``tests/egress/test_hls_sink_live_playability.py`` for the real-ffmpeg
proof that ``HlsSink.output_args()`` (reused here unchanged) writes a
genuinely playable manifest + segments; this file proves the relay wires
that proven muxer up correctly, not that the muxer itself works.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from civiccast.egress.hls_relay import HlsRelaySupervisor, hls_relay_uri_for
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.stream._ffmpeg import FfmpegNotFoundError


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str = "C:/CivicCast/live/gov", label: str = "Web") -> EgressSinkSpec:
    return EgressSinkSpec(kind="hls", label=label, uri=uri)


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.terminated = True
        self._returncode = 0
        return 0


def _supervisor():
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        calls.append(args)
        proc = _FakeProcess()
        procs.append(proc)
        return proc

    return HlsRelaySupervisor(starter=starter), calls, procs


def test_hls_relay_uri_for_is_pure_and_deterministic() -> None:
    uri_a = hls_relay_uri_for("C:/CivicCast/live/gov")
    uri_b = hls_relay_uri_for("C:/CivicCast/live/gov")
    assert uri_a == uri_b
    parsed = urlsplit(uri_a)
    assert parsed.scheme == "udp"
    assert parsed.hostname == "127.0.0.1"
    assert 18_000 <= parsed.port < 18_500


def test_hls_relay_uri_for_differs_per_directory() -> None:
    a = hls_relay_uri_for("C:/CivicCast/live/gov")
    b = hls_relay_uri_for("C:/CivicCast/live/school-board")
    assert a != b


def test_apply_rewrites_hls_sink_to_local_ts_and_starts_relay() -> None:
    sup, calls, procs = _supervisor()
    config = _config(_hls_sink())

    updated = sup.apply(config)

    assert len(calls) == 1
    assert len(procs) == 1
    rewritten = updated.sinks[0]
    assert rewritten.kind == "local-ts"
    assert rewritten.uri == hls_relay_uri_for("C:/CivicCast/live/gov")
    # The original config is untouched (in-memory rewrite only, mirrors
    # TsRelaySupervisor — never persisted back to the store).
    assert config.sinks[0].kind == "hls"


def test_apply_feeds_the_relay_the_real_hls_muxer_args() -> None:
    """The relay child's args must be exactly ``HlsSink(original_spec).output_args()``
    appended to a udp input — the same, already-proven ffmpeg HLS invocation the
    legacy engine uses, not a reinvented one."""
    from civiccast.egress.sinks import HlsSink

    sup, calls, _procs = _supervisor()
    sink = _hls_sink()
    sup.apply(_config(sink))

    args = calls[0]
    assert "-i" in args
    input_uri = args[args.index("-i") + 1]
    assert input_uri.startswith(hls_relay_uri_for(sink.uri))
    expected_output_args = HlsSink(sink).output_args()
    assert args[-len(expected_output_args) :] == expected_output_args


def test_apply_is_idempotent_for_an_unchanged_sink() -> None:
    sup, calls, procs = _supervisor()
    config = _config(_hls_sink())

    sup.apply(config)
    sup.apply(config)

    assert len(calls) == 1  # relay reused, not restarted
    assert not procs[0].terminated


def test_apply_restarts_the_relay_when_the_directory_changes() -> None:
    sup, calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/gov")))
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/gov-v2")))

    assert len(calls) == 2
    assert procs[0].terminated  # the stale relay was torn down
    assert not procs[1].terminated


def test_apply_passes_through_configs_without_an_hls_sink() -> None:
    sup, calls, _procs = _supervisor()
    config = _config(EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000"))

    updated = sup.apply(config)

    assert updated is config  # untouched, same instance
    assert calls == []


def test_apply_degrades_gracefully_when_ffmpeg_is_unavailable() -> None:
    """No ffmpeg on PATH must not crash the channel: the sink is returned
    unchanged (still hls) so sink_element_spec's own fallback branch builds
    a real, if unreceived, udpsink — degraded (no live HLS), never a crash."""

    def starter(_args: list[str]) -> _FakeProcess:
        raise FfmpegNotFoundError("no ffmpeg on PATH")

    sup = HlsRelaySupervisor(starter=starter)
    config = _config(_hls_sink())

    updated = sup.apply(config)

    assert updated is config
    assert updated.sinks[0].kind == "hls"


def test_stop_channel_terminates_only_that_channels_relays() -> None:
    sup, _calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(), channel_id="gov"))
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/other"), channel_id="other"))

    sup.stop_channel("gov")

    assert procs[0].terminated
    assert not procs[1].terminated


def test_stop_all_terminates_every_relay() -> None:
    sup, _calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(), channel_id="gov"))
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/other"), channel_id="other"))

    sup.stop_all()

    assert all(proc.terminated for proc in procs)


def test_apply_creates_a_fresh_relay_after_stop_channel() -> None:
    sup, calls, procs = _supervisor()
    config = _config(_hls_sink())
    sup.apply(config)
    sup.stop_channel("gov")

    sup.apply(config)

    assert len(calls) == 2
    assert procs[0].terminated
    assert not procs[1].terminated


# --- U21: a new worker session must not inherit the old relay's timeline ---------------
#
# The relay child does its own per-stream PTS-discontinuity correction and keeps
# the resulting offset for as long as the child lives (U21 task A, proven on the
# station's bundled ffmpeg: a one-sided +20s forward jump on the RE-ENCODED audio
# leg left a permanent -10.0s output a-v offset that survived every later
# segment, and the relay logged a DIFFERENT "new offset" per stream). So reuse is
# only safe while the writer the relay serves is the same writer. Every genuine
# worker (re)start -- first start, crash relaunch, output-desync guard restart,
# slate->program restart -- must rebind the channel's relay to the new session.


def test_apply_with_new_session_rebinds_the_relay_to_the_new_worker_session() -> None:
    sup, calls, procs = _supervisor()
    config = _config(_hls_sink())

    first = sup.apply(config)
    second = sup.apply(config, new_session=True)

    assert len(calls) == 2, "the new worker session kept the previous session's relay child"
    assert procs[0].terminated, "the previous session's relay child was left running"
    assert not procs[1].terminated
    # Same argv, therefore the same deterministic udp port: the config already
    # handed to the engine graph stays valid across the rebind.
    assert calls[0] == calls[1]
    assert second.sinks[0].uri == first.sinks[0].uri == hls_relay_uri_for("C:/CivicCast/live/gov")


def test_apply_without_new_session_keeps_the_relay_for_an_in_place_reload() -> None:
    """The reload path (``new_session=False``) is not a worker restart: the
    relay must be left alone so an in-place reload keeps one continuous mux."""

    sup, calls, procs = _supervisor()
    config = _config(_hls_sink())

    sup.apply(config)
    sup.apply(config, new_session=False)

    assert len(calls) == 1
    assert not procs[0].terminated


def test_new_session_preserves_a_live_window_but_clears_fresh_or_dead_windows(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "live"
    directory.mkdir()
    config = _config(_hls_sink(uri=str(directory)))
    playlist = directory / "playlist.m3u8"
    segment = directory / "seg000000001.ts"
    sup, _calls, procs = _supervisor()

    # A fresh relay must remove a previous broadcast's window.
    playlist.write_text("#EXTM3U\n#stale\n", encoding="utf-8")
    segment.write_bytes(b"stale segment")
    sup.apply(config)
    assert not playlist.exists()
    assert not segment.exists()

    # A live relay's window belongs to the same broadcast during a worker
    # crash-relaunch and stays visible while its relay child is rebound.
    playlist.write_text("#EXTM3U\n#live\n", encoding="utf-8")
    segment.write_bytes(b"live segment")
    sup.apply(config, new_session=True)
    assert procs[0].terminated
    assert playlist.is_file()
    assert segment.is_file()

    # A same-label sink redirected to another directory is not the same
    # output window. Stale files at the new destination must still be cleared.
    directory = tmp_path / "redirected"
    directory.mkdir()
    config = _config(_hls_sink(uri=str(directory)))
    playlist = directory / "playlist.m3u8"
    segment = directory / "seg000000001.ts"
    playlist.write_text("#EXTM3U\n#stale\n", encoding="utf-8")
    segment.write_bytes(b"stale segment")
    sup.apply(config, new_session=True)
    assert procs[1].terminated
    assert not playlist.exists()
    assert not segment.exists()

    # A dead relay cannot prove that the old window is still live. Clear it
    # before starting the replacement so it cannot advertise stale media.
    playlist.write_text("#EXTM3U\n#stale\n", encoding="utf-8")
    segment.write_bytes(b"stale segment")
    procs[2]._returncode = 1
    sup.apply(config, new_session=True)
    assert not playlist.exists()
    assert not segment.exists()


def test_apply_with_new_session_drops_a_previous_sessions_relay_with_no_hls_sink() -> None:
    """A channel restarted onto a config with no hls sink at all must not leave
    the previous session's relay child (and its udp port) running."""

    sup, calls, procs = _supervisor()
    sup.apply(_config(_hls_sink()))
    config = _config(EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts"))

    updated = sup.apply(config, new_session=True)

    assert updated is config
    assert procs[0].terminated
    assert calls == [calls[0]]  # nothing respawned
    assert sup.is_alive("gov") is None


# --- MAJOR M1: relay-child liveness ----------------------------------------------------
#
# Before ``is_alive`` existed, nothing polled the relay subprocess after ``apply()``
# started it: a relay that died later (disk full, ffmpeg missing/removed mid-run, OOM)
# stayed invisible until the channel's next full encoder start/reload happened to call
# ``apply()`` again. These tests pin the liveness contract ``civiccast.egress.daemon``
# polls every tick; see ``tests/egress/test_daemon.py`` for the daemon-level integration
# (health surfacing) proof.


def test_is_alive_is_none_when_no_relay_is_tracked_for_the_channel() -> None:
    sup, _calls, _procs = _supervisor()

    assert sup.is_alive("gov") is None


def test_is_alive_is_true_while_the_relay_process_is_running() -> None:
    sup, _calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(), channel_id="gov"))

    assert sup.is_alive("gov") is True
    assert not procs[0].terminated  # is_alive is read-only — it must not touch the process


def test_is_alive_is_false_once_the_relay_process_has_exited() -> None:
    sup, _calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(), channel_id="gov"))

    procs[0]._returncode = 1  # simulate the relay child dying on its own (disk full / OOM)

    assert sup.is_alive("gov") is False


def test_is_alive_only_reports_on_the_named_channels_relays() -> None:
    sup, _calls, procs = _supervisor()
    sup.apply(_config(_hls_sink(), channel_id="gov"))
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/other"), channel_id="other"))

    procs[0]._returncode = 1  # only "gov"'s relay died

    assert sup.is_alive("gov") is False
    assert sup.is_alive("other") is True


def test_udp_input_args_use_widened_analyze_and_probe_for_delayed_video() -> None:
    """REGRESSION: a delayed-video UDP TS can lock the relay to audio-only when the
    ffmpeg start-time probe window is too small. The isolated synthetic proof shows
    2,000,000 locks to AAC-only while 6,000,000 retains H264/AAC. Pin BOTH options
    to the widened value so the two never drift apart."""
    from civiccast.egress.hls_relay import _UDP_INPUT_ARGS

    args = tuple(_UDP_INPUT_ARGS)
    # both flags must be present and identical
    assert args.count("-analyzeduration") == 1
    assert args.count("-probesize") == 1
    ad = args[args.index("-analyzeduration") + 1]
    ps = args[args.index("-probesize") + 1]
    assert ad == ps, f"analyze/probe must move together: {ad} vs {ps}"
    # widened value (2_000_000 is the known audio-only-lock baseline)
    assert ad == "6000000", (
        f"UDP input probe window must be widened to 6000000 for delayed video; got {ad}"
    )
