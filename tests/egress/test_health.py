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
    worker_reached_playing,
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


class TestTailOnlyLogRead:
    """D44 (real-hardware soak, 2026-09-05): the daemon reads a worker stderr
    log on every ~2s health tick and the log grows for the life of the
    channel; reading it whole re-scanned an ever-growing file forever. Only
    the tail is read now."""

    def test_only_the_tail_is_read_and_older_values_are_not_seen(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        # An old, distinctive value first, then filler that pushes it beyond
        # the tail window, then the current value.
        lines = ["frame= 1 fps=11.0 bitrate=1111.0kbits/s drop=99"]
        lines += ["frame= 100 fps=28.0 bitrate=5000.0kbits/s drop=0"] * 200
        lines += ["frame= 900 fps=30.0 bitrate=6100.0kbits/s drop=1"]
        log_path.write_text("\n".join(lines), encoding="utf-8")

        metrics = read_latest_ffmpeg_encoder_metrics(log_path, tail_bytes=2048)

        assert metrics.encoder_fps == 30.0
        assert metrics.encoder_bitrate_kbps == 6100.0
        assert metrics.dropped_frames == 1
        # The 99-drop line at the very top is outside the tail window; the
        # newest values are all this function reports, so it is not needed.
        assert log_path.stat().st_size > 2048

    def test_a_log_smaller_than_the_tail_window_is_read_whole(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text("frame= 5 fps=24.0 bitrate=4000.0kbits/s drop=3", encoding="utf-8")

        metrics = read_latest_ffmpeg_encoder_metrics(log_path, tail_bytes=1024 * 1024)

        assert metrics.encoder_fps == 24.0
        assert metrics.dropped_frames == 3

    def test_a_missing_log_still_returns_empty_metrics(self, tmp_path: Path) -> None:
        assert read_latest_ffmpeg_encoder_metrics(tmp_path / "nope.log") == EgressEncoderMetrics()

    def test_a_partial_first_line_from_the_cut_is_harmless(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text(
            "frame= 1 fps=11.0 bitrate=1111.0kbits/s drop=99\n"
            "frame= 2 fps=30.0 bitrate=6100.0kbits/s drop=1\n",
            encoding="utf-8",
        )

        # A window that lands mid-way through the first line.
        metrics = read_latest_ffmpeg_encoder_metrics(log_path, tail_bytes=70)

        assert metrics.encoder_fps == 30.0
        assert metrics.encoder_bitrate_kbps == 6100.0


def test_encoder_has_progress_requires_fps_and_bitrate() -> None:
    assert encoder_has_progress(EgressEncoderMetrics(encoder_fps=30.0, encoder_bitrate_kbps=6100))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_fps=30.0))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_bitrate_kbps=6100))
    assert not encoder_has_progress(EgressEncoderMetrics(encoder_fps=0.0, encoder_bitrate_kbps=0.0))


class TestWorkerReachedPlaying:
    """Round-3 fix (PR #183 review, BLOCKER item 1): the daemon's ONLY real
    evidence a GStreamer worker's pipeline reached PLAYING, as opposed to
    merely not having exited yet. Emitted exactly once, on the success path
    of ``GstPlayoutEngine._await_playing`` (see
    ``tests/egress/test_gst_engine_preroll_timeout.py``)."""

    def test_true_when_the_marker_is_present(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text(
            "CTRL decode: demoted hardware decoders to CPU decode: vaapih264dec\n"
            "CTRL preroll: reached PLAYING after 6.2s\n",
            encoding="utf-8",
        )

        assert worker_reached_playing(log_path) is True

    def test_false_while_still_waiting(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text(
            "CTRL preroll: still waiting for PLAYING after 5.0s of 30.0s "
            "(get_state=async, current=null, pending=playing)\n",
            encoding="utf-8",
        )

        assert worker_reached_playing(log_path) is False

    def test_false_on_a_missing_log(self, tmp_path: Path) -> None:
        assert worker_reached_playing(tmp_path / "nope.log") is False

    def test_false_on_an_empty_log(self, tmp_path: Path) -> None:
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text("", encoding="utf-8")

        assert worker_reached_playing(log_path) is False

    def test_true_even_when_the_marker_is_outside_the_default_tail_window(
        self, tmp_path: Path
    ) -> None:
        """The marker prints exactly once near the start of the worker's
        lifetime; it must still be found via a SMALL tail window explicitly
        sized to cover it, proving the function honors ``tail_bytes`` the
        same way ``read_latest_ffmpeg_encoder_metrics`` does."""
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text(
            "CTRL preroll: reached PLAYING after 6.2s\n" + ("CTRL reload: filler tick\n" * 500),
            encoding="utf-8",
        )

        assert worker_reached_playing(log_path, tail_bytes=1024 * 1024) is True


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
