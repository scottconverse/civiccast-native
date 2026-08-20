# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Egress health metric parsing tests."""

from __future__ import annotations

from pathlib import Path

from civiccast.egress.health import (
    EgressEncoderMetrics,
    build_default_sink_health,
    encoder_has_progress,
    parse_ffmpeg_encoder_metrics_line,
    read_latest_ffmpeg_encoder_metrics,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec


def test_parse_ffmpeg_encoder_metrics_line_extracts_status_values() -> None:
    metrics = parse_ffmpeg_encoder_metrics_line(
        "frame=  300 fps=29.97 q=-1.0 size= 2048kB time=00:00:10.0 "
        "bitrate=6200.5kbits/s dup=0 drop=2 speed=1x"
    )

    assert metrics.encoder_fps == 29.97
    assert metrics.encoder_bitrate_kbps == 6200.5
    assert metrics.dropped_frames == 2


def test_parse_ffmpeg_encoder_metrics_line_supports_progress_drop_frames() -> None:
    metrics = parse_ffmpeg_encoder_metrics_line(
        "fps=30.0 bitrate=6.4Mbits/s total_size=123 drop_frames=4"
    )

    assert metrics.encoder_fps == 30.0
    assert metrics.encoder_bitrate_kbps == 6400.0
    assert metrics.dropped_frames == 4


def test_read_latest_ffmpeg_encoder_metrics_keeps_newest_values(tmp_path: Path) -> None:
    log_path = tmp_path / "ffmpeg.stderr.log"
    log_path.write_text(
        "\n".join(
            [
                "frame= 100 fps=28.0 bitrate=5000.0kbits/s drop=0",
                "frame= 200 fps=30.0 bitrate=6100.0kbits/s drop=1",
            ]
        ),
        encoding="utf-8",
    )

    metrics = read_latest_ffmpeg_encoder_metrics(log_path)

    assert metrics.encoder_fps == 30.0
    assert metrics.encoder_bitrate_kbps == 6100.0
    assert metrics.dropped_frames == 1


def test_encoder_has_progress_requires_fps_and_bitrate() -> None:
    assert encoder_has_progress(EgressEncoderMetrics(encoder_fps=30.0, encoder_bitrate_kbps=6100))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_fps=30.0))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_bitrate_kbps=6100))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_fps=0.0, encoder_bitrate_kbps=0.0))


def test_default_sink_health_keeps_file_sinks_local_only_true() -> None:
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(kind="file", label="Proof file", uri="build/out.ts"),
            EgressSinkSpec(kind="local-ts", label="Local capture", uri="file:///tmp/out.ts"),
        ],
    )

    # File-like sinks are locally healthy regardless of on-air state.
    assert build_default_sink_health(
        config=config, metrics=EgressEncoderMetrics(), state="FALLBACK_SLATE"
    ) == {
        "Proof file": True,
        "Local capture": True,
    }


def test_default_sink_health_does_not_assume_external_sinks_connected() -> None:
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(kind="srt", label="SRT headend", uri="srt://headend.example:9000"),
            EgressSinkSpec(kind="rtmp", label="RTMP relay", uri="rtmp://relay.example/live"),
            EgressSinkSpec(kind="local-ts", label="UDP monitor", uri="udp://127.0.0.1:19000"),
        ],
    )
    metrics = EgressEncoderMetrics(encoder_fps=30.0, encoder_bitrate_kbps=6000.0)

    assert build_default_sink_health(config=config, metrics=metrics, state="ON_AIR") == {
        "SRT headend": False,
        "RTMP relay": False,
        "UDP monitor": True,
    }


def test_udp_sink_health_is_not_false_when_metrics_are_unavailable() -> None:
    """Audit QA-004: the slate encoder emits no parseable fps/bitrate lines,
    so udp-ts health read `false` for hours on a sink TSDuck verified 6/6
    clean - training operators to ignore the flag. When metrics are simply
    ABSENT (encoder alive, nothing measured), fire-and-forget UDP sinks
    must not claim a failure they cannot observe; only metrics that show an
    actual stall (fps/bitrate of zero) report false."""

    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(kind="udp-ts", label="Cable headend", uri="udp://127.0.0.1:23101"),
            EgressSinkSpec(kind="local-ts", label="UDP monitor", uri="udp://127.0.0.1:19000"),
        ],
    )

    # Idling on slate, no metrics: healthy (no far-end to disprove).
    absent = build_default_sink_health(
        config=config, metrics=EgressEncoderMetrics(), state="FALLBACK_SLATE"
    )
    assert absent == {"Cable headend": True, "UDP monitor": True}

    # THE QA-004 BUG: a stale fps=0/bitrate=0 line while idling on slate must NOT
    # flip a TSDuck-clean UDP sink to false — it is not on air, so progress isn't required.
    slate_stale = build_default_sink_health(
        config=config,
        metrics=EgressEncoderMetrics(encoder_fps=0.0, encoder_bitrate_kbps=0.0),
        state="FALLBACK_SLATE",
    )
    assert slate_stale == {"Cable headend": True, "UDP monitor": True}

    # On air with a measured stall (fps/bitrate zero): honestly false.
    on_air_stalled = build_default_sink_health(
        config=config,
        metrics=EgressEncoderMetrics(encoder_fps=0.0, encoder_bitrate_kbps=0.0),
        state="ON_AIR",
    )
    assert on_air_stalled == {"Cable headend": False, "UDP monitor": False}

    # On air but NO measurable progress at all: we expect media to move and don't see
    # it → a real, observable problem, surfaced as false (not hidden as "unknown").
    on_air_absent = build_default_sink_health(
        config=config, metrics=EgressEncoderMetrics(), state="ON_AIR"
    )
    assert on_air_absent == {"Cable headend": False, "UDP monitor": False}
