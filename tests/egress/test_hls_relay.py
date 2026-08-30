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

from urllib.parse import urlsplit

from civiccast.egress.hls_relay import HlsRelaySupervisor, hls_relay_uri_for
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.stream._ffmpeg import FfmpegNotFoundError


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks))


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
