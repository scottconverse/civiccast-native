# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from civiccast.egress.errors import SecretUnresolvedError
from civiccast.egress.models import (
    CanonicalProfile,
    EgressCommand,
    EgressConfig,
    EgressHealthSample,
    EgressProofEvent,
    EgressSinkSpec,
    EgressStateRow,
)
from civiccast.egress.sinks import (
    FileSink,
    HlsSink,
    LocalTsSink,
    RtmpSink,
    SdiSink,
    SrtSink,
    UdpTsSink,
    build_sink,
)
from civiccast.egress.store import InMemoryEgressStore


def test_egress_config_rejects_secret_bearing_sink_uris() -> None:
    with pytest.raises(ValidationError, match="must not include credentials or secrets"):
        EgressSinkSpec(
            kind="srt",
            label="Headend",
            uri="srt://headend.example:9000?passphrase=secret",
        )

    with pytest.raises(ValidationError, match="must not include credentials or secrets"):
        EgressSinkSpec(
            kind="rtmp",
            label="Platform",
            uri="rtmp://user:secret@example/live",
        )

    with pytest.raises(ValidationError, match="must not include credentials or secrets"):
        EgressSinkSpec(
            kind="srt",
            label="Headend",
            uri="srt://headend.example:9000?streamid=token-abc",
        )


def test_egress_config_enforces_unique_sink_labels_and_safe_extra_args() -> None:
    with pytest.raises(ValidationError, match="unsupported FFmpeg output flag"):
        EgressSinkSpec(
            kind="file",
            label="CI",
            uri="build/out.ts",
            extra_output_args=["-filter_complex"],
        )

    with pytest.raises(ValidationError, match="sink labels must be unique"):
        EgressConfig(
            channel_id="government",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[
                EgressSinkSpec(kind="file", label="Proof", uri="build/a.ts"),
                EgressSinkSpec(kind="file", label="Proof", uri="build/b.ts"),
            ],
        )


def test_srt_sink_builds_secret_resolved_output_args_and_redacted_description() -> None:
    spec = EgressSinkSpec(
        kind="srt",
        label="Headend",
        uri="srt://headend.example:9000",
        secret_ref="EGRESS_SRT_PASSPHRASE",
        latency_ms=1500,
    )
    sink = SrtSink(spec, resolve_secret=lambda ref: "station-passphrase" if ref else None)

    args = sink.output_args()

    assert args == [
        "-f",
        "mpegts",
        "srt://headend.example:9000?mode=caller&latency=1500000&linger=5&passphrase=station-passphrase",
    ]
    assert "station-passphrase" not in sink.describe()
    assert "passphrase=%3Credacted%3E" in sink.describe()


def test_srt_sink_blocks_missing_secret() -> None:
    spec = EgressSinkSpec(
        kind="srt",
        label="Headend",
        uri="srt://headend.example:9000",
        secret_ref="EGRESS_SRT_PASSPHRASE",
    )
    sink = SrtSink(spec, resolve_secret=lambda _ref: None)

    assert "passphrase=%3Credacted%3E" in sink.describe()
    with pytest.raises(SecretUnresolvedError):
        sink.output_args()


def test_rtmp_sink_resolves_stream_key_without_logging_secret() -> None:
    spec = EgressSinkSpec(
        kind="rtmp",
        label="Platform",
        uri="rtmps://stream.example/live",
        secret_ref="EGRESS_RTMP_STREAM_KEY",
    )
    sink = RtmpSink(spec, resolve_secret=lambda ref: "station-stream-key" if ref else None)

    assert sink.output_args() == [
        "-f",
        "flv",
        "rtmps://stream.example/live/station-stream-key",
    ]
    assert "station-stream-key" not in sink.describe()
    assert sink.describe() == "rtmp sink Platform -> rtmps://stream.example/live/<secret>"


def test_rtmp_sink_blocks_missing_secret() -> None:
    spec = EgressSinkSpec(
        kind="rtmp",
        label="Platform",
        uri="rtmp://stream.example/live",
        secret_ref="EGRESS_RTMP_STREAM_KEY",
    )
    sink = RtmpSink(spec, resolve_secret=lambda _ref: None)

    with pytest.raises(SecretUnresolvedError):
        sink.output_args()


def test_local_ts_sink_supports_udp_and_file_handoffs() -> None:
    udp_sink = build_sink(EgressSinkSpec(kind="local-ts", label="LAN", uri="udp://239.0.0.1:5000"))
    file_sink = build_sink(
        EgressSinkSpec(kind="local-ts", label="Pipe", uri="file:///tmp/civiccast.ts")
    )
    file_target = str(Path("/tmp/civiccast.ts"))

    assert isinstance(udp_sink, LocalTsSink)
    assert udp_sink.output_args() == ["-f", "mpegts", "udp://239.0.0.1:5000"]
    assert isinstance(file_sink, LocalTsSink)
    assert file_sink.output_args() == ["-f", "mpegts", file_target]
    assert file_sink.describe() == f"local-ts sink Pipe -> {file_target}"


def test_udp_ts_sink_builds_cbr_spts_output_with_packet_sizing() -> None:
    # CA-6: headend-grade SPTS — pkt_size=1316 (7x188 TS packets per datagram)
    # is appended when the operator did not set one; -muxrate rides the
    # allowlisted extra args so the mpegts muxer null-pads to a constant rate.
    sink = build_sink(
        EgressSinkSpec(
            kind="udp-ts",
            label="Headend",
            uri="udp://239.255.0.1:5000",
            extra_output_args=["-muxrate", "3750k"],
        )
    )
    assert isinstance(sink, UdpTsSink)
    args = sink.output_args()
    assert args[:2] == ["-muxrate", "3750k"]
    assert args[-3:-1] == ["-f", "mpegts"]
    assert args[-1] == "udp://239.255.0.1:5000?pkt_size=1316"
    assert "multicast" in sink.describe()

    unicast = build_sink(
        EgressSinkSpec(
            kind="udp-ts",
            label="Headend",
            uri="udp://10.0.0.9:5000?pkt_size=188",
        )
    )
    # Operator-set pkt_size wins; unicast is valid (TelVue accepts both).
    assert unicast.output_args()[-1] == "udp://10.0.0.9:5000?pkt_size=188"
    assert "unicast" in unicast.describe()


def test_udp_ts_sink_requires_udp_uri_with_port() -> None:
    with pytest.raises(ValidationError, match="udp"):
        EgressSinkSpec(kind="udp-ts", label="Headend", uri="srt://239.255.0.1:5000")
    with pytest.raises(ValidationError, match="port"):
        EgressSinkSpec(kind="udp-ts", label="Headend", uri="udp://239.255.0.1")


def test_hls_sink_builds_rolling_live_manifest_output_args(tmp_path: Path) -> None:
    out_dir = tmp_path / "live-hls"
    sink = build_sink(EgressSinkSpec(kind="hls", label="Web", uri=str(out_dir)))

    assert isinstance(sink, HlsSink)
    args = sink.output_args()

    assert "-f" in args and args[args.index("-f") + 1] == "hls"
    assert "-hls_time" in args and args[args.index("-hls_time") + 1] == "2"
    assert "-hls_list_size" in args and args[args.index("-hls_list_size") + 1] == "6"
    flags = args[args.index("-hls_flags") + 1]
    assert "delete_segments" in flags
    assert "append_list" in flags
    assert args[-1] == str(out_dir / "playlist.m3u8")

    # BLOCKING fix: the hls muxer only cuts a segment on a keyframe it
    # receives, so -hls_time is meaningless unless this sink also forces
    # keyframe cadence itself (it cannot rely on upstream GOP -- most sinks
    # reach this via -c:v copy, see egress.runtime). Assert the muxer-driven
    # cadence is actually configured, not just requested.
    assert "-force_key_frames" in args
    force_kf_expr = args[args.index("-force_key_frames") + 1]
    assert "n_forced*2" in force_kf_expr
    assert "-c:v" in args and args[args.index("-c:v") + 1] != "copy"
    # Writing output_args() must create the directory so ffmpeg's hls muxer
    # (which does not mkdir -p) can write the manifest + segments into it.
    assert out_dir.is_dir()


def test_hls_sink_accepts_file_uri_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "live-hls"
    sink = build_sink(EgressSinkSpec(kind="hls", label="Web", uri=out_dir.as_uri()))

    assert sink.connect_target() == str(out_dir / "playlist.m3u8")


def test_hls_sink_requires_local_directory_uri() -> None:
    with pytest.raises(ValidationError, match="hls egress sinks require a local directory"):
        EgressSinkSpec(kind="hls", label="Web", uri="rtmp://example.com/live")


def test_file_sink_and_sdi_stub_have_honest_boundaries() -> None:
    file_sink = build_sink(EgressSinkSpec(kind="file", label="CI", uri="build/out.ts"))
    sdi_sink = build_sink(EgressSinkSpec(kind="sdi", label="DeckLink", uri="sdi"))

    assert isinstance(file_sink, FileSink)
    assert file_sink.output_args() == ["-f", "mpegts", "build/out.ts"]
    assert isinstance(sdi_sink, SdiSink)
    # Issue #117: the stub now routes the operator to the supervised relay.
    with pytest.raises(NotImplementedError, match="SDI output device"):
        sdi_sink.output_args()


def test_file_sink_supports_rotating_as_run_recording_patterns() -> None:
    sink = FileSink(
        EgressSinkSpec(
            kind="file",
            label="As-run",
            uri="build/as-run/gov-%Y%m%d-%H.ts",
        )
    )

    assert sink.output_args() == [
        "-f",
        "segment",
        "-segment_time",
        "3600",
        "-strftime",
        "1",
        "-reset_timestamps",
        "1",
        "build/as-run/gov-%Y%m%d-%H.ts",
    ]


def test_in_memory_egress_store_orders_and_consumes_commands() -> None:
    store = InMemoryEgressStore()
    base = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    later = EgressCommand(
        channel_id="government",
        action="stop",
        issued_at=base + timedelta(seconds=5),
        issued_by="operator",
        command_id="cmd-2",
    )
    earlier = EgressCommand(
        channel_id="government",
        action="start",
        issued_at=base,
        issued_by="operator",
        command_id="cmd-1",
    )

    store.enqueue_command(later)
    store.enqueue_command(earlier)
    store.enqueue_command(earlier)

    popped = store.pop_pending_commands("government")

    assert [cmd.command_id for cmd in popped] == ["cmd-1", "cmd-2"]
    assert store.pop_pending_commands("government") == []


def test_in_memory_egress_store_keeps_config_state_and_recent_health() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    config = EgressConfig(
        channel_id="government",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
        canonical_profile=CanonicalProfile(video_bitrate_kbps=3000),
    )
    state = EgressStateRow(
        channel_id="government",
        state="ON_AIR",
        current_source_label="Council meeting",
        current_proof_event_id="proof-1",
        updated_at=now,
        pid=1234,
    )

    store.upsert_config(config)
    store.write_state(state)
    store.append_health(
        EgressHealthSample(
            channel_id="government",
            sampled_at=now,
            state="ON_AIR",
            sink_connected={"Proof": True},
            encoder_fps=30.0,
            seconds_on_air=1,
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="government",
            sampled_at=now + timedelta(seconds=1),
            state="ON_AIR",
            sink_connected={"Proof": True},
            encoder_fps=30.0,
            seconds_on_air=2,
        )
    )

    assert store.get_config("government") == config
    assert store.read_state("government") == state
    assert [sample.seconds_on_air for sample in store.recent_health("government", 2)] == [2, 1]
    assert [sample.caption_status for sample in store.recent_health("government", 2)] == [
        "not-verified",
        "not-verified",
    ]

    assert store.trim_health_before(now + timedelta(milliseconds=500)) == 1
    assert [sample.seconds_on_air for sample in store.recent_health("government", 2)] == [2]


def test_in_memory_egress_store_uses_append_order_for_equal_health_timestamps() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    for seconds_on_air in [1, 2, 3]:
        store.append_health(
            EgressHealthSample(
                channel_id="government",
                sampled_at=now,
                state="ON_AIR",
                sink_connected={"Proof": True},
                seconds_on_air=seconds_on_air,
            )
        )

    assert [sample.seconds_on_air for sample in store.recent_health("government", 3)] == [3, 2, 1]


def test_in_memory_egress_store_uses_append_order_for_equal_proof_timestamps() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    for event_id in ["proof-1", "proof-2", "proof-3"]:
        store.append_proof_event(
            EgressProofEvent(
                event_id=event_id,
                observed_at=now,
                channel_id="government",
                state="ON_AIR",
                source_label=event_id,
                source_path=f"prepared/{event_id}.ts",
                source_ref=event_id,
                proof_boundary="civiccast-egress-handoff-boundary",
                machine_summary=f"{event_id} went to air.",
            )
        )

    assert [event.event_id for event in store.recent_proof_events("government", 3)] == [
        "proof-3",
        "proof-2",
        "proof-1",
    ]
