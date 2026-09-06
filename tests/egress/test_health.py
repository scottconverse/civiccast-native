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
    read_ffmpeg_encoder_metrics_since,
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

    def test_true_when_the_marker_is_130kb_past_the_spawn_offset(self, tmp_path: Path) -> None:
        """Round-4 (PR #183 review, BLOCKER reproduced): this replaces the
        old ``test_true_even_when_the_marker_is_outside_the_default_tail_window``,
        which named a ``tail_bytes`` parameter that no longer exists -- the
        function no longer reads a tail window at all. The real behavior
        under test now: a worker's OWN marker, well past the 64 KiB the old
        tail window would have covered (130 KB of filler AFTER the marker,
        which a chatty worker crossing the old window before the first
        observing tick would have made this test fail under the design this
        replaces), is still found because the scan runs forward from the
        spawn offset with no window bound at all -- the marker is the OLDEST
        line a worker ever prints."""
        log_path = tmp_path / "gst-worker.stderr.log"
        filler_line = "CTRL reload: filler tick\n"
        filler_count = (130 * 1024 // len(filler_line)) + 1
        log_path.write_text(
            "CTRL preroll: reached PLAYING after 6.2s\n" + (filler_line * filler_count),
            encoding="utf-8",
        )
        assert log_path.stat().st_size - len("CTRL preroll: reached PLAYING after 6.2s\n") > (
            130 * 1024
        )

        assert worker_reached_playing(log_path, offset=0) is True

    def test_a_marker_before_the_spawn_offset_does_not_count(self, tmp_path: Path) -> None:
        """Round-4 (PR #183 review, BLOCKER reproduced): the exact bug --
        ``strategy.py`` opens this log in APPEND mode and never truncates it
        per spawn, so a PREVIOUS worker's marker sits earlier in the same
        file a NEW worker's evidence is read from. The offset anchor must
        make that earlier marker invisible, even though it is still
        physically present in the file."""
        log_path = tmp_path / "gst-worker.stderr.log"
        previous_worker_marker = "CTRL preroll: reached PLAYING after 4.0s pid=111\n"
        log_path.write_text(previous_worker_marker, encoding="utf-8")
        spawn_offset = log_path.stat().st_size
        log_path.write_text(
            previous_worker_marker + "CTRL preroll: still waiting for PLAYING after 1.0s of 30.0s "
            "(get_state=async, current=null, pending=playing)\n",
            encoding="utf-8",
        )

        # Anchored at the new worker's spawn offset: only the still-waiting
        # line (no marker) is visible, so no evidence is found yet.
        assert worker_reached_playing(log_path, offset=spawn_offset) is False
        # Unanchored (offset=0, the pre-round-4 behavior): the previous
        # worker's marker IS visible and would have wrongly returned True --
        # this is the exact regression the offset anchor closes.
        assert worker_reached_playing(log_path, offset=0) is True

    def test_pid_mismatch_refuses_a_marker_even_inside_the_scan_window(
        self, tmp_path: Path
    ) -> None:
        """Round-4 belt-and-braces layer: even a marker that DOES fall at or
        after the spawn offset must not be credited to the wrong worker if
        its printed pid disagrees with the pid the daemon is currently
        tracking."""
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text("CTRL preroll: reached PLAYING after 2.0s pid=4242\n", encoding="utf-8")

        assert worker_reached_playing(log_path, expected_pid=4242) is True
        assert worker_reached_playing(log_path, expected_pid=9999) is False
        # No expected_pid given -> pid in the marker is not checked at all.
        assert worker_reached_playing(log_path, expected_pid=None) is True

    def test_a_marker_with_no_pid_group_is_accepted_on_offset_evidence_alone(
        self, tmp_path: Path
    ) -> None:
        """An older worker binary (or a hand-written fixture) may print the
        marker with no ``pid=`` suffix at all -- ``expected_pid`` has
        nothing to compare against, so the marker is accepted on the offset
        anchor alone rather than being rejected for a missing field."""
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text("CTRL preroll: reached PLAYING after 2.0s\n", encoding="utf-8")

        assert worker_reached_playing(log_path, expected_pid=4242) is True

    def test_a_file_shrunk_below_the_offset_is_treated_as_rotated(self, tmp_path: Path) -> None:
        """If the log is ever found smaller than the recorded spawn offset
        (rotated or truncated out from under the daemon between spawn and
        this read), that offset can no longer mean anything -- read from
        byte 0 instead of silently returning no evidence forever."""
        log_path = tmp_path / "gst-worker.stderr.log"
        log_path.write_text("CTRL preroll: reached PLAYING after 1.0s\n", encoding="utf-8")

        assert worker_reached_playing(log_path, offset=10_000) is True


class TestReadFfmpegEncoderMetricsSince:
    """Round-4 (PR #183 review, BLOCKER reproduced): the FFmpeg-side
    counterpart to ``TestWorkerReachedPlaying``'s spawn-offset anchor --
    ``_ffmpeg.py`` also opens its stderr log in APPEND mode and never
    truncates it per spawn, so a previous worker's stale fps/bitrate
    progress must not confirm a brand-new, not-yet-encoding worker."""

    def test_stale_progress_before_the_offset_does_not_count(self, tmp_path: Path) -> None:
        """A real ffmpeg progress line can omit fields between ticks (e.g. a
        very first line before the encoder has measured anything at all) --
        the parser's own "keep the last seen value per field" folding
        (``_latest_metrics_from_text``) means an unanchored read can
        silently inherit a PREVIOUS worker's stale, real-looking fps/bitrate
        for a field the CURRENT worker hasn't printed yet at all. Anchoring
        to the current worker's own spawn offset must not let that happen:
        with nothing parseable at or after the offset, the current worker
        has produced no evidence, full stop."""
        log_path = tmp_path / "ffmpeg.stderr.log"
        previous_worker_progress = "frame= 900 fps=30.0 bitrate=6100.0kbits/s drop=1\n"
        log_path.write_text(previous_worker_progress, encoding="utf-8")
        spawn_offset = log_path.stat().st_size
        # The current worker's own line so far: a frame count only, no
        # fps=/bitrate= fields printed yet.
        log_path.write_text(previous_worker_progress + "frame=   1\n", encoding="utf-8")

        metrics = read_ffmpeg_encoder_metrics_since(log_path, offset=spawn_offset)

        assert metrics == EgressEncoderMetrics()
        assert not encoder_has_progress(metrics)
        # Unanchored, the previous worker's stale fps/bitrate would have
        # wrongly carried forward as "the latest value" for fields the
        # current worker's own line never mentions.
        unanchored = read_ffmpeg_encoder_metrics_since(log_path, offset=0)
        assert encoder_has_progress(unanchored)

    def test_progress_at_or_after_the_offset_is_found(self, tmp_path: Path) -> None:
        log_path = tmp_path / "ffmpeg.stderr.log"
        log_path.write_text("frame= 200 fps=30.0 bitrate=6100.0kbits/s drop=1\n", encoding="utf-8")

        metrics = read_ffmpeg_encoder_metrics_since(log_path, offset=0)

        assert encoder_has_progress(metrics)

    def test_a_missing_log_returns_empty_metrics(self, tmp_path: Path) -> None:
        assert read_ffmpeg_encoder_metrics_since(tmp_path / "nope.log") == EgressEncoderMetrics()


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
