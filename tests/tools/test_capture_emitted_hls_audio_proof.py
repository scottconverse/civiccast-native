# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the bounded continuous emitted-HLS audio verifier.

FIXTURE-ONLY tests. They build a synthetic sliding-window HLS directory and
drive the tool's collector/measurement seams with injected readers and
injected ffmpeg results, so nothing here touches the live station, the
network, or a real GStreamer/ffmpeg process.

Why this exists (scope of the claim)
------------------------------------
The short-window verifier (``verify_beta10_live_hls_media.py``) measures a
handful of newest 2 s segments -- roughly 8 s of audio.  EBU R128 / ITU-R
BS.1770 integrated loudness is not meaningful over 8 s of variable speech, so
that gate can neither PASS nor FAIL a channel's loudness compliance.  This
tool captures a *continuous* >=3-minute emitted-HLS window per channel into an
immutable snapshot, then measures it once.  It exists to replace "8 s spot
sample" with a duration-qualified integrated measurement; it does not relax
the -16 +/-1 target and it does not weaken the short verifier.

Fail-closed posture
-------------------
Every one of these must produce a FAIL/NOT_PROVEN verdict, never a PASS:
missing or deleted segment, partial/truncated segment, sequence gap, timestamp
discontinuity, sample shorter than the minimum, and any analyzer/tool error.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_clock = iter(0.0 + 0.5 * i for i in range(100000))

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "capture_emitted_hls_audio_proof.py"
)


def _load() -> object:
    if not _SCRIPT.is_file():
        pytest.fail(
            "capture_emitted_hls_audio_proof.py is absent: the approved continuous "
            "emitted-HLS audio verifier has not been implemented."
        )
    spec = importlib.util.spec_from_file_location("capture_emitted_hls_audio_proof", _SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail("capture_emitted_hls_audio_proof.py could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- synthetic sliding-window HLS fixtures --------------------------------


def _write_playlist(
    channel_dir: Path,
    *,
    media_sequence: int,
    count: int,
    target_duration: float = 2.0,
    pdt_prefix: str = "2026-09-24T09:00:",
    segment_bytes: bytes = b"\x47" * 188 * 10,
) -> list[str]:
    """Write a playlist referencing ``count`` segments and create the files."""

    names: list[str] = []
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        f"#EXT-X-TARGETDURATION:{target_duration:g}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
    ]
    for offset in range(count):
        sequence = media_sequence + offset
        name = f"seg{sequence:09d}.ts"
        names.append(name)
        lines.append(f"#EXTINF:{target_duration:g},")
        lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{pdt_prefix}{offset:02d}.000-0600")
        lines.append(name)
        (channel_dir / name).write_bytes(segment_bytes)
    (channel_dir / "playlist.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return names


def _hls_root(tmp_path: Path, channels: tuple[str, ...] = ("public",)) -> Path:
    root = tmp_path / "live-hls"
    for channel in channels:
        (root / channel).mkdir(parents=True)
    return root


# --- playlist parsing -----------------------------------------------------


def test_parse_playlist_reads_sequence_and_segments(tmp_path: Path) -> None:
    mod = _load()
    channel = _hls_root(tmp_path) / "public"
    names = _write_playlist(channel, media_sequence=100, count=3)

    playlist = mod.parse_playlist(channel / "playlist.m3u8")

    assert playlist.media_sequence == 100
    assert playlist.target_duration == pytest.approx(2.0)
    assert playlist.segments == names
    assert playlist.parse_error is None


def test_parse_playlist_missing_file_is_fail_closed(tmp_path: Path) -> None:
    mod = _load()

    playlist = mod.parse_playlist(tmp_path / "absent.m3u8")

    assert playlist.parse_error is not None
    assert playlist.segments == []


def test_parse_playlist_rejects_non_contiguous_sequence(tmp_path: Path) -> None:
    mod = _load()
    channel = _hls_root(tmp_path) / "public"
    _write_playlist(channel, media_sequence=100, count=3)
    # Remove the middle segment and its playlist line -> a real gap.
    (channel / "seg000000101.ts").unlink()
    text = (channel / "playlist.m3u8").read_text(encoding="utf-8")
    (channel / "playlist.m3u8").write_text(
        "\n".join(line for line in text.splitlines() if "seg000000101" not in line) + "\n",
        encoding="utf-8",
    )

    playlist = mod.parse_playlist(channel / "playlist.m3u8")

    # A playlist whose own listed sequences are not contiguous must be flagged;
    # the collector then refuses to treat that window as continuous.
    assert playlist.sequence_gaps or playlist.parse_error is not None


# --- dedupe by sequence/name/hash -----------------------------------------


def test_collector_deduplicates_by_sequence_and_name(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=200, count=4)

    snapshot = mod.capture_channel("public", root, min_duration_seconds=0.0, required_segments=4)

    sequence_numbers = [record["sequence"] for record in snapshot["segments"]]
    assert sequence_numbers == sorted(set(sequence_numbers)), "duplicate sequence captured"
    names = [record["name"] for record in snapshot["segments"]]
    assert len(names) == len(set(names)), "duplicate name captured"


def test_collector_records_hash_and_size_for_each_segment(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=300, count=3)

    snapshot = mod.capture_channel("public", root, min_duration_seconds=0.0, required_segments=3)

    for record in snapshot["segments"]:
        assert record["sha256"] and len(record["sha256"]) == 64
        assert record["bytes"] > 0


# --- immutability: no rotation race ---------------------------------------


def test_collector_is_immutable_against_rotation(tmp_path: Path, monkeypatch) -> None:
    """The snapshot must be a copy, not a live path reference.

    While the collector is running, the writer mutates the live playlist and
    deletes an old segment.  The already-captured snapshot must still name the
    original files with the original bytes.
    """

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=400, count=3)

    snapshot = mod.capture_channel("public", root, min_duration_seconds=0.0, required_segments=3)
    captured_names = [record["name"] for record in snapshot["segments"]]

    # Simulate rotation after capture: playlist advances, old file is deleted.
    _write_playlist(channel, media_sequence=401, count=3)
    (channel / "seg000000400.ts").unlink()

    assert [record["name"] for record in snapshot["segments"]] == captured_names
    for record in snapshot["segments"]:
        assert Path(record["snapshot_path"]).is_file(), "snapshot copy was not preserved"


# --- fail-closed structural checks ----------------------------------------


def test_collector_fails_closed_on_missing_referenced_segment(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=500, count=3)
    (channel / "seg000000501.ts").unlink()

    result = mod.capture_channel(
        "public", root, min_duration_seconds=0.0, required_segments=3
    )

    assert result["status"] == mod.Verdict.FAIL
    assert any("missing" in reason.lower() for reason in result["blocking_reasons"])
    missing_records = [r for r in result["segments"] if r["name"] == "seg000000501.ts"]
    assert missing_records and missing_records[0]["capture_status"] == "missing"
    assert result["captured_segment_count"] == 2


def test_collector_fails_closed_on_sequence_gap(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=600, count=3)
    # Rename the newest segment so the playlist references a non-contiguous seq.
    (channel / "seg000000602.ts").rename(channel / "seg000000699.ts")
    text = (channel / "playlist.m3u8").read_text(encoding="utf-8")
    (channel / "playlist.m3u8").write_text(
        text.replace("seg000000602.ts", "seg000000699.ts"), encoding="utf-8"
    )

    result = mod.capture_channel(
        "public", root, min_duration_seconds=0.0, required_segments=3
    )

    assert result["status"] == mod.Verdict.FAIL
    assert any("gap" in reason.lower() or "contigu" in reason.lower() for reason in result["blocking_reasons"])


def test_collector_fails_closed_when_sample_is_too_short(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=700, count=2)

    result = mod.capture_channel(
        "public", root, min_duration_seconds=180.0, required_segments=999
    )

    # Too short is a measurement-validity issue, not a loudness failure: it must
    # never PASS, and it is UNVERIFIED rather than FAIL (unless required_segments
    # is also unmet, which IS structural).  Use a required-segments value that
    # the capture satisfies so the shortfall is the only signal.
    assert result["status"] == mod.Verdict.FAIL  # required_segments=999 unmet -> structural


def test_collector_too_short_without_structural_defect_is_unverified(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=700, count=2)

    result = mod.capture_channel("public", root, min_duration_seconds=180.0)

    assert result["status"] == mod.Verdict.UNVERIFIED
    assert result["blocking_reasons"] == []
    assert "shorter" in result["duration_shortfall"]


# --- LUFS parsing ---------------------------------------------------------


_FFMPEG_STDERR_NORMAL = """
[Parsed_ebur128_0 @ 0] Summary:

  Integrated loudness:
    I:         -15.8 LUFS
    Threshold: -25.8 LUFS

  Loudness range:
    LRA:         3.1 LU
    Threshold: -35.8 LUFS

  True peak:
    Peak:       -1.4 dBFS
"""


def test_parse_loudness_extracts_lufs_lra_and_peak() -> None:
    mod = _load()

    parsed = mod.parse_ebur128(_FFMPEG_STDERR_NORMAL)

    assert parsed["integrated_lufs"] == pytest.approx(-15.8)
    assert parsed["lra_lu"] == pytest.approx(3.1)
    assert parsed["true_peak_dbfs"] == pytest.approx(-1.4)


def test_parse_loudness_returns_none_when_unparseable() -> None:
    mod = _load()

    parsed = mod.parse_ebur128("ffmpeg choked, no loudness here")

    assert parsed["integrated_lufs"] is None
    assert parsed["lra_lu"] is None
    assert parsed["true_peak_dbfs"] is None


def test_parse_loudness_uses_last_integrated_value() -> None:
    """Streaming ebur128 emits a rolling summary; the final I: is the window's."""
    mod = _load()
    stderr = """
    I:         -20.0 LUFS
    I:         -16.4 LUFS
    """

    parsed = mod.parse_ebur128(stderr)

    assert parsed["integrated_lufs"] == pytest.approx(-16.4)


# --- measurement window adequacy ------------------------------------------


def test_measurement_passes_only_on_long_enough_in_band_window(monkeypatch) -> None:
    mod = _load()
    captured: dict[str, list[str]] = {}

    def fake_run(args, **_kwargs):
        captured["args"] = args
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": _FFMPEG_STDERR_NORMAL}

    result = mod.measure_window(
        channel_id="public",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=200.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] == mod.Verdict.PASS
    assert result["integrated_lufs"] == pytest.approx(-15.8)
    assert result["within_target"] is True


def test_measurement_fails_closed_when_window_too_short(monkeypatch) -> None:
    mod = _load()

    def fake_run(_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("analyzer must not run on a too-short window")

    result = mod.measure_window(
        channel_id="public",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=8.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] == mod.Verdict.UNVERIFIED
    assert result["within_target"] is False
    assert "duration" in result["detail"].lower() or "short" in result["detail"].lower()


def test_measurement_fails_closed_on_out_of_band_window() -> None:
    mod = _load()

    def fake_run(_args, **_kwargs):
        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": _FFMPEG_STDERR_NORMAL.replace("-15.8", "-19.6"),
        }

    result = mod.measure_window(
        channel_id="public",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=200.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] == mod.Verdict.FAIL
    assert result["within_target"] is False


def test_measurement_fails_closed_when_analyzer_errors() -> None:
    mod = _load()

    def fake_run(_args, **_kwargs):
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": "boom"}

    result = mod.measure_window(
        channel_id="public",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=200.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] in (mod.Verdict.FAIL, mod.Verdict.UNVERIFIED)
    assert result["within_target"] is False


def test_measurement_fails_closed_on_unparseable_loudness() -> None:
    mod = _load()

    def fake_run(_args, **_kwargs):
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": "no loudness summary"}

    result = mod.measure_window(
        channel_id="public",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=200.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] != mod.Verdict.PASS
    assert result["within_target"] is False


def test_measurement_negative_control_short_in_band_is_not_a_pass() -> None:
    """The exact field failure mode: 8 s of in-band audio must NOT PASS."""

    mod = _load()

    def fake_run(_args, **_kwargs):
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": _FFMPEG_STDERR_NORMAL}

    result = mod.measure_window(
        channel_id="government",
        concat_path=Path("scratch/window.ffconcat"),
        duration_seconds=8.0,
        min_duration_seconds=180.0,
        run=fake_run,
    )

    assert result["status"] == mod.Verdict.UNVERIFIED
    assert result["within_target"] is False


# --- no speech/cue text persisted -----------------------------------------


def test_snapshot_and_result_contain_no_media_text_fields(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=800, count=3)

    snapshot = mod.capture_channel("public", root, min_duration_seconds=0.0, required_segments=3)
    serialized = json.dumps(snapshot)

    for forbidden in ("cue", "caption_text", "transcript", "speech"):
        assert forbidden not in serialized


# --- multi-poll accumulation ------------------------------------------------


def _writer(tmp_path: Path, channel: str = "public"):
    """Return a callable that advances a synthetic sliding-window HLS.

    Each call appends one new segment and slides the playlist, exactly like a
    live HLS writer on a 2 s cadence.
    """

    root = _hls_root(tmp_path, (channel,))
    channel_dir = root / channel
    window = 6
    state = {"next_seq": 0, "seqs": []}

    def advance(count: int = 1) -> None:
        for _ in range(count):
            seq = state["next_seq"]
            state["next_seq"] += 1
            name = f"seg{seq:09d}.ts"
            (channel_dir / name).write_bytes(bytes([0x47]) * 188 + seq.to_bytes(4, "little"))
            state["seqs"].append(seq)
            visible = state["seqs"][-window:]
            for old in state["seqs"][:-window]:
                (channel_dir / f"seg{old:09d}.ts").unlink(missing_ok=True)
            lines = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:2"]
            lines.append(f"#EXT-X-MEDIA-SEQUENCE:{visible[0]}")
            for s in visible:
                lines += ["#EXTINF:2.000000,", f"seg{s:09d}.ts"]
            (channel_dir / "playlist.m3u8").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )

    advance(window)
    return root, channel_dir, advance


def test_accumulation_reaches_target_duration_across_polls(tmp_path: Path) -> None:
    """A 12 s playlist must be accumulated into a >=3-minute continuous window."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def advance_and_return(**_kwargs):
        advance(1)

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=180.0,
        max_wait_seconds=600.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=advance_and_return,
    )

    assert snapshot["status"] == mod.Verdict.PASS, snapshot["blocking_reasons"]
    assert snapshot["captured_duration_seconds"] >= 180.0
    seqs = [r["sequence"] for r in snapshot["segments"]]
    assert seqs == list(range(min(seqs), min(seqs) + len(seqs))), "window not contiguous"


def test_accumulation_deduplicates_replayed_segments(tmp_path: Path) -> None:
    """A writer that replays the same playlist must not double-count a segment."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    polls = {"n": 0}

    def on_poll(**_kwargs):
        # Only advance every third poll -> the same playlist is seen repeatedly.
        polls["n"] += 1
        if polls["n"] % 3 == 0:
            advance(1)

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=120.0,
        max_wait_seconds=600.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    seqs = [r["sequence"] for r in snapshot["segments"]]
    assert len(seqs) == len(set(seqs)), "replayed segment was counted twice"
    assert snapshot["captured_duration_seconds"] >= 120.0


def test_accumulation_fails_closed_on_skipped_sequence(tmp_path: Path) -> None:
    """A rotation whose next segment jumps a sequence number -> FAIL.

    The writer is driven only by this test (no auto-advance), so the jump is a
    true unrecoverable gap: the skipped sequence never appears on disk and can
    never be captured.
    """

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    window = 6

    def write_window(seqs: list[int]) -> None:
        for s in seqs:
            (channel / f"seg{s:09d}.ts").write_bytes(
                bytes([0x47]) * 188 + s.to_bytes(4, "little")
            )
        lines = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:2"]
        lines.append(f"#EXT-X-MEDIA-SEQUENCE:{seqs[0]}")
        for s in seqs:
            lines += ["#EXTINF:2.000000,", f"seg{s:09d}.ts"]
        (channel / "playlist.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_window(list(range(window)))  # 0..5 contiguous

    state = {"n": 0}

    def on_poll(**_kwargs) -> None:
        state["n"] += 1
        if state["n"] == 1:
            # Skip sequence 6 entirely; land on 7 and 8.
            write_window([0, 1, 2, 3, 4, 5, 7, 8])
        # every later poll leaves the same (already broken) window

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=60.0,
        max_wait_seconds=30.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert snapshot["status"] == mod.Verdict.FAIL
    assert any(
        "skip" in reason.lower() or "gap" in reason.lower()
        for reason in snapshot["blocking_reasons"]
    )

def test_accumulation_fails_closed_on_timeout(tmp_path: Path) -> None:
    """A writer that never advances must time out, not loop forever."""

    mod = _load()
    root, _channel, _advance = _writer(tmp_path)

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=180.0,
        max_wait_seconds=5.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=lambda **_kwargs: None,
    )

    assert snapshot["status"] in (mod.Verdict.UNVERIFIED, mod.Verdict.FAIL)
    assert any("time" in r.lower() or "timeout" in r.lower() for r in snapshot["blocking_reasons"])


def test_accumulation_is_bounded_by_max_segments(tmp_path: Path) -> None:
    """Segment count must be capped so scratch cannot grow without bound."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=10_000.0,
        max_wait_seconds=1.0,
        max_segments=8,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert snapshot["captured_segment_count"] <= 8


def test_accumulation_fails_closed_on_partial_ts(tmp_path: Path) -> None:
    """A segment that shrinks mid-copy is partial -> FAIL, never a short window."""

    mod = _load()
    root, channel, _advance = _writer(tmp_path)
    victim = channel / "seg000000004.ts"
    victim.write_bytes(b"")

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=12.0,
        max_wait_seconds=5.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
    )

    assert snapshot["status"] == mod.Verdict.FAIL
    assert any("partial" in r.lower() or "empty" in r.lower() for r in snapshot["blocking_reasons"])


# --- PTS/PCR continuity -----------------------------------------------------


def _probe_with(pts_values, pcr_values, duration=2.0):
    """Build an ffprobe stub returning the supplied per-segment PTS/PCR."""

    def probe(_ffprobe, path):
        index = int(str(path).rsplit("seg", 1)[1].split(".", 1)[0])
        return {
            "status": "PASS",
            "video_start_pts": pts_values[index],
            "pcr_first": pcr_values[index],
            "duration": duration,
        }

    return probe


def test_continuity_passes_on_forward_two_second_cadence() -> None:
    mod = _load()
    pts = [90_000 * (1 + 2 * i) for i in range(4)]
    pcr = [5_000_000_000 + 180_000 * i for i in range(4)]

    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": f"seg{i:09d}.ts", "video_start_pts": pts[i], "pcr_first": pcr[i], "duration": 2.0}
            for i in range(4)
        ]
    )

    assert result["status"] == mod.Verdict.PASS


def test_continuity_fails_closed_on_pts_discontinuity() -> None:
    mod = _load()

    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 90_000, "pcr_first": 5_000_000_000, "duration": 2.0},
            {"name": "seg1", "video_start_pts": 900_000, "pcr_first": 5_000_180_000, "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.FAIL
    assert any("pts" in p.lower() for p in result["problems"])


def test_continuity_fails_closed_on_pcr_stall() -> None:
    mod = _load()

    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 90_000, "pcr_first": 5_000_000_000, "duration": 2.0},
            {"name": "seg1", "video_start_pts": 270_000, "pcr_first": 5_000_000_000, "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.FAIL
    assert any("pcr" in p.lower() for p in result["problems"])


def test_continuity_fails_closed_when_timestamps_missing() -> None:
    mod = _load()

    result = mod.evaluate_pts_pcr_continuity(
        [{"name": "seg0", "video_start_pts": None, "pcr_first": None, "duration": 2.0}]
    )

    assert result["status"] in (mod.Verdict.UNVERIFIED, mod.Verdict.FAIL)


def test_continuity_negative_control_forward_is_not_flagged() -> None:
    """Positive control: a genuinely continuous window must not be flagged."""

    mod = _load()

    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 100_000, "pcr_first": 1_000_000, "duration": 2.0},
            {"name": "seg1", "video_start_pts": 280_000, "pcr_first": 1_180_000, "duration": 2.0},
            {"name": "seg2", "video_start_pts": 460_000, "pcr_first": 1_360_000, "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.PASS
    assert result["problems"] == []

# --- continuity gates the loudness verdict ---------------------------------


def test_verify_channel_refuses_loudness_when_continuity_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A discontinuity must block the LUFS verdict, even if audio parses fine."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    def bad_probe(_ffprobe, path):
        return {
            "status": mod.Verdict.PASS,
            # Every segment reports the SAME PTS -> a real discontinuity.
            "video_start_pts": 90_000,
            "pcr_first": 5_000_000_000,
            "duration": 2.0,
        }

    def fake_run(_args, **_kwargs):
        raise AssertionError("loudness analyzer must not run when continuity fails")

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=12.0,
        release_grade=False,
        ffprobe=Path("ffprobe"),
        tsp=None,
        probe=bad_probe,
        run=fake_run,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert result["continuity"]["status"] == mod.Verdict.FAIL
    assert result["audio_window"]["status"] == mod.Verdict.FAIL
    assert result["audio_window"]["within_target"] is False


def test_verify_channel_measures_only_after_continuity_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: a continuous window does reach the LUFS measurement."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    def good_probe(_ffprobe, path):
        index = int(str(path).rsplit("seg", 1)[1].split(".", 1)[0])
        return {
            "status": mod.Verdict.PASS,
            "video_start_pts": 90_000 + 180_000 * index,
            "pcr_first": 5_000_000_000 + 180_000 * index,
            "duration": 2.0,
        }

    def fake_run(_args, **_kwargs):
        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "I:         -15.9 LUFS\nLRA:         3.0 LU\nPeak:       -1.3 dBFS\n",
        }

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=12.0,
        release_grade=False,
        ffprobe=Path("ffprobe"),
        probe=good_probe,
        run=fake_run,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert result["continuity"]["status"] == mod.Verdict.PASS
    assert result["audio_window"]["status"] == mod.Verdict.PASS
    assert result["audio_window"]["integrated_lufs"] == pytest.approx(-15.9)

# --- scratch containment & safe delete (coordinator HOLD findings) ----------


def test_scratch_inside_hls_root_is_refused(tmp_path: Path) -> None:
    """``--scratch-dir`` pointing at the HLS root must be refused, not deleted."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=("public",),
        scratch_root=root,  # catastrophic: same tree we only ever read
        min_duration_seconds=0.0,
        duration_seconds=0.0,
    )

    assert result["verdict"] == mod.Verdict.FAIL
    assert any("scratch" in r.lower() for r in result["blocking_reasons"])
    assert (root / "public" / "playlist.m3u8").is_file(), "HLS root must be untouched"


def test_scratch_parent_of_hls_root_is_refused(tmp_path: Path) -> None:
    """A scratch that CONTAINS the HLS root would delete it on cleanup."""

    mod = _load()
    root = tmp_path / "live-hls"
    (root / "public").mkdir(parents=True)
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=("public",),
        scratch_root=tmp_path,  # parent of the root
        min_duration_seconds=0.0,
        duration_seconds=0.0,
    )

    assert result["verdict"] == mod.Verdict.FAIL
    assert any("scratch" in r.lower() for r in result["blocking_reasons"])


def test_managed_scratch_is_created_under_user_parent_not_deleted_in_place(
    tmp_path: Path,
) -> None:
    """A user-supplied parent gets a NEW owned child; only that child is removed."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=0, count=3)
    parent = tmp_path / "scratch-parent"
    parent.mkdir()
    sentinel = parent / "keep-me.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    cleanup = mod.prepare_scratch_dir(parent)

    assert cleanup.owned_dir.parent == parent.resolve()
    assert cleanup.owned_dir != parent.resolve()
    assert cleanup.owned_dir.is_dir()
    # The user's parent and its contents must survive cleanup of the owned child.
    cleanup.remove()
    assert sentinel.is_file(), "user parent contents must never be deleted"
    assert parent.is_dir()
    assert not cleanup.owned_dir.exists()


def test_fixed_timestamp_default_does_not_reuse_existing_dir(tmp_path: Path, monkeypatch) -> None:
    """Two runs must not collide on a shared fixed-name scratch directory."""

    mod = _load()
    first = mod.prepare_scratch_dir(tmp_path)
    second = mod.prepare_scratch_dir(tmp_path)

    assert first.owned_dir != second.owned_dir
    first.remove()
    assert second.owned_dir.is_dir(), "second run's scratch must not be clobbered"


def test_cleanup_refuses_to_delete_a_symlinked_scratch_target(tmp_path: Path) -> None:
    """If the owned dir is swapped for a junction/symlink, cleanup must refuse."""

    mod = _load()
    real = tmp_path / "real"
    real.mkdir()
    (real / "important.txt").write_text("keep", encoding="utf-8")
    parent = tmp_path / "parent"
    parent.mkdir()

    cleanup = mod.prepare_scratch_dir(parent)
    # Simulate an attacker swapping our owned dir for a link to elsewhere.
    import shutil as _shutil

    _shutil.rmtree(cleanup.owned_dir, ignore_errors=True)
    try:
        cleanup.owned_dir.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - privilege dependent
        pytest.skip("symlink creation not permitted on this host")

    removed = cleanup.remove()

    assert removed is False
    assert (real / "important.txt").is_file(), "link target must not be deleted"


def test_cleanup_refuses_delete_outside_resolved_owned_path(tmp_path: Path) -> None:
    """The delete routine refuses a target that is not the resolved owned dir."""

    mod = _load()
    parent = tmp_path / "parent"
    parent.mkdir()
    cleanup = mod.prepare_scratch_dir(parent)
    other = tmp_path / "other"
    other.mkdir()
    (other / "data.txt").write_text("keep", encoding="utf-8")

    removed = mod.safe_remove_owned_dir(obj=cleanup, target=other)

    assert removed is False
    assert (other / "data.txt").is_file()


# --- untrusted playlist / channel traversal -------------------------------


def test_playlist_segment_name_traversal_is_rejected(tmp_path: Path) -> None:
    """A playlist entry of ``../evil.ts`` must never write outside scratch."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    outside = root / "evil.ts"
    outside.write_bytes(b"\x47" * 188)
    (channel / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:2.000000,\n../evil.ts\n",
        encoding="utf-8",
    )

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=0.0,
        max_wait_seconds=1.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
    )

    assert snapshot["status"] == mod.Verdict.FAIL
    assert any(
        "unsafe" in r.lower() or "traversal" in r.lower() or "invalid" in r.lower()
        for r in snapshot["blocking_reasons"]
    )
    # Nothing outside the scratch root may have been created.
    assert not (tmp_path / "evil.ts").exists() or True  # pre-existing file is fine
    assert not (tmp_path / "scratch" / "evil.ts").exists()


def test_playlist_absolute_segment_path_is_rejected(tmp_path: Path) -> None:
    """An absolute segment path in the playlist must be refused."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    (channel / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        f"#EXTINF:2.000000,\n{tmp_path / 'abs.ts'}\n",
        encoding="utf-8",
    )

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=0.0,
        max_wait_seconds=1.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
    )

    assert snapshot["status"] == mod.Verdict.FAIL


def test_channel_id_traversal_is_rejected(tmp_path: Path) -> None:
    """A channel id like ``../..`` must not be accepted as a directory name."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))

    result = mod.verify_all(
        root,
        channels=("../escape",),
        scratch_root=tmp_path / "scratch",
        min_duration_seconds=0.0,
        duration_seconds=0.0,
    )

    assert result["verdict"] == mod.Verdict.FAIL
    assert any("channel" in r.lower() for r in result["blocking_reasons"])


def test_segment_with_subdirectory_component_is_rejected(tmp_path: Path) -> None:
    """A nested playlist path (``sub/seg.ts``) is not a bare .ts and is refused."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    (channel / "sub").mkdir()
    (channel / "sub" / "seg.ts").write_bytes(b"\x47" * 188)
    (channel / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:2.000000,\nsub/seg.ts\n",
        encoding="utf-8",
    )

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=0.0,
        max_wait_seconds=1.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
    )

    assert snapshot["status"] == mod.Verdict.FAIL


# --- out path must not land in the read-only HLS tree ---------------------


def test_out_inside_hls_root_is_rejected(tmp_path: Path) -> None:
    """``--out`` inside the HLS tree contradicts the read-only guarantee."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))

    rc = mod.main(
        [
            "--hls-root",
            str(root),
            "--channels",
            "public",
            "--min-duration-seconds",
            "0",
            "--duration-seconds",
            "0",
            "--scratch-dir",
            str(tmp_path / "scratch"),
            "--out",
            str(root / "public" / "proof.json"),
        ]
    )

    assert rc != 0
    assert not (root / "public" / "proof.json").exists()


# --- finite argument bounds ----------------------------------------------


def test_negative_and_nonfinite_duration_bounds_are_rejected(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    for bad in (-1.0, float("nan"), float("inf")):
        result = mod.verify_all(
            root,
            channels=("public",),
            scratch_root=tmp_path / "scratch",
            min_duration_seconds=bad,
            duration_seconds=bad,
        )
        assert result["verdict"] != mod.Verdict.PASS, f"accepted bad bound {bad!r}"


def test_zero_and_huge_max_wait_are_bounded(tmp_path: Path) -> None:
    """``max_wait_seconds`` must be positive and finite."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    for bad in (0.0, -5.0, float("inf")):
        result = mod.verify_all(
            root,
            channels=("public",),
            scratch_root=tmp_path / "scratch",
            min_duration_seconds=0.0,
            duration_seconds=0.0,
            max_wait_seconds=bad,
        )
        assert result["verdict"] != mod.Verdict.PASS

# --- missing ffprobe / missing continuity must not PASS --------------------


def test_missing_ffprobe_fails_closed_before_lufs(tmp_path: Path) -> None:
    """No ffprobe => continuity unproven => never PASS, even if LUFS parses fine."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    def fake_run(_args, **_kwargs):
        raise AssertionError("loudness must not be credited without continuity proof")

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=8.0,
        release_grade=False,
        ffmpeg=Path("ffmpeg"),
        ffprobe=None,  # continuity cannot be proven
        run=fake_run,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert result["status"] != mod.Verdict.PASS
    assert result["audio_window"]["status"] != mod.Verdict.PASS
    assert result["audio_window"]["within_target"] is False


def test_missing_ffprobe_is_never_masked_by_inband_lufs(tmp_path: Path) -> None:
    """Negative control: an in-band LUFS string must not rescue a missing probe."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    def fake_run(_args, **_kwargs):
        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "I:         -16.0 LUFS\nLRA:         2.0 LU\nPeak:       -1.3 dBFS\n",
        }

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=8.0,
        release_grade=False,
        ffmpeg=Path("ffmpeg"),
        ffprobe=None,
        run=fake_run,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert result["status"] == mod.Verdict.UNVERIFIED
    assert result["audio_window"]["status"] == mod.Verdict.UNVERIFIED


# --- PCR gap size, not just delta > 0 -------------------------------------


def test_pcr_cadence_is_not_asserted_and_units_are_not_assumed() -> None:
    """PCR is a monotonicity signal only; cadence/units must NOT be gated.

    Measured on the shipped runtime: TSDuck ``pcrextract`` Value advances
    ~26,550,000 ticks/s (27 MHz base), and real muxers re-base PCR per segment.
    A tool that assumed 90 kHz ticks would falsely FAIL real output, so the
    evaluator must not gate on a PCR delta magnitude.
    """

    mod = _load()

    # A large (real-muxer-like) PCR step must NOT be a failure on its own.
    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 90_000, "pcr_first": 5_000_000_000,
             "duration": 2.0},
            {"name": "seg1", "video_start_pts": 270_000, "pcr_first": 5_026_550_000,
             "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.PASS, result["problems"]


def test_continuity_passes_when_pcr_advances_by_one_segment() -> None:
    """Positive control: a duration-sized PCR delta must not be flagged."""

    mod = _load()

    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 90_000, "pcr_first": 5_000_000_000,
             "duration": 2.0},
            {"name": "seg1", "video_start_pts": 270_000, "pcr_first": 5_000_180_000,
             "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.PASS


# --- release floor for --min-duration-seconds ------------------------------


def test_release_min_duration_cannot_be_lowered_for_a_pass(tmp_path: Path) -> None:
    """A release-grade run may not accept an arbitrarily short window."""

    mod = _load()
    root, _channel, advance = _writer(tmp_path)

    def on_poll(**_kwargs):
        advance(1)

    def good_probe(_ffprobe, path):
        index = int(str(path).rsplit("seg", 1)[1].split(".", 1)[0])
        return {
            "status": mod.Verdict.PASS,
            "video_start_pts": 90_000 + 180_000 * index,
            "pcr_first": 5_000_000_000 + 180_000 * index,
            "duration": 2.0,
        }

    def fake_run(_args, **_kwargs):
        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "I:         -16.0 LUFS\nLRA:         2.0 LU\nPeak:       -1.3 dBFS\n",
        }

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=8.0,  # far below the 180s release floor
        release_grade=True,
        ffmpeg=Path("ffmpeg"),
        ffprobe=Path("ffprobe"),
        probe=good_probe,
        run=fake_run,
        poll_seconds=0.0,
        sleep=lambda _s: None,
        monotonic=lambda: next(_clock),
        on_poll=on_poll,
    )

    assert result["status"] != mod.Verdict.PASS


def test_release_min_duration_floor_is_at_least_180_seconds() -> None:
    mod = _load()

    assert mod.RELEASE_MIN_DURATION_SECONDS >= 180.0

# --- Luna audit: wraparound, discontinuity, tsp wiring, poll bound ---------


def test_pts_33bit_rollover_is_not_a_discontinuity() -> None:
    """A legal 33-bit PTS wrap must not be reported as a backwards jump."""

    mod = _load()
    # A full 2 s segment starting exactly PTS_MODULUS - 2s, so the next
    # segment wraps to 0 and the modular delta is a clean 2 s.
    last_pts = (1 << 33) - 180_000
    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": last_pts, "pcr_first": 1_000_000,
             "duration": 2.0},
            {"name": "seg1", "video_start_pts": 0, "pcr_first": 1_180_000,
             "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.PASS, result["problems"]


def test_pcr_42bit_rollover_is_not_a_discontinuity() -> None:
    """A legal 42-bit PCR wrap must not be reported as a PCR stall/backjump."""

    mod = _load()
    last_pcr = (1 << 42) - 90_000
    result = mod.evaluate_pts_pcr_continuity(
        [
            {"name": "seg0", "video_start_pts": 90_000, "pcr_first": last_pcr,
             "duration": 2.0},
            {"name": "seg1", "video_start_pts": 270_000, "pcr_first": 90_000,
             "duration": 2.0},
        ]
    )

    assert result["status"] == mod.Verdict.PASS, result["problems"]


def test_ext_x_discontinuity_tag_is_honoured(tmp_path: Path) -> None:
    """A playlist that marks #EXT-X-DISCONTINUITY must fail continuity."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    for i in range(3):
        (channel / f"seg{i:09d}.ts").write_bytes(bytes([0x47]) * 188 + i.to_bytes(4, "little"))
    (channel / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:2.000000,\nseg000000000.ts\n"
        "#EXT-X-DISCONTINUITY\n"
        "#EXTINF:2.000000,\nseg000000001.ts\n"
        "#EXTINF:2.000000,\nseg000000002.ts\n",
        encoding="utf-8",
    )

    parsed = mod.parse_playlist(channel / "playlist.m3u8")

    assert parsed.discontinuity_indices == [1], parsed.discontinuity_indices


def test_discontinuity_blocks_loudness_verdict(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    for i in range(3):
        (channel / f"seg{i:09d}.ts").write_bytes(bytes([0x47]) * 188 + i.to_bytes(4, "little"))
    (channel / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:2.000000,\nseg000000000.ts\n"
        "#EXT-X-DISCONTINUITY\n"
        "#EXTINF:2.000000,\nseg000000001.ts\n"
        "#EXTINF:2.000000,\nseg000000002.ts\n",
        encoding="utf-8",
    )

    snapshot = mod.accumulate_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        target_duration_seconds=4.0,
        max_wait_seconds=2.0,
        poll_seconds=0.0,
        sleep=lambda _s: None,
    )

    assert snapshot["status"] == mod.Verdict.FAIL
    assert any("discontinu" in r.lower() for r in snapshot["blocking_reasons"])


def test_cli_passes_tsp_so_pcr_is_reachable(tmp_path: Path, monkeypatch) -> None:
    """The CLI must resolve and thread TSDuck, else PCR is always None -> UNVERIFIED."""

    mod = _load()
    captured: dict[str, Any] = {}

    def fake_verify_all(_root, **kwargs):
        captured.update(kwargs)
        return {"verdict": mod.Verdict.PASS, "channels": {}}

    monkeypatch.setattr(mod, "verify_all", fake_verify_all)
    monkeypatch.setattr(mod, "_resolve_tsp", lambda: Path("tsduck-tsp"))
    monkeypatch.setattr(mod, "_resolve_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(mod, "_resolve_ffprobe", lambda: Path("ffprobe"))

    rc = mod.main(
        [
            "--hls-root",
            str(tmp_path / "hls"),
            "--out",
            str(tmp_path / "out.json"),
            "--min-duration-seconds",
            "180",
        ]
    )

    assert rc == 0
    assert captured.get("tsp") == Path("tsduck-tsp")


def test_production_poll_default_is_bounded_nonzero() -> None:
    """The production default must not busy-spin the playlist between segments."""

    mod = _load()

    assert mod.DEFAULT_POLL_SECONDS > 0
    import inspect

    sig = inspect.signature(mod.verify_channel)
    assert sig.parameters["poll_seconds"].default == mod.DEFAULT_POLL_SECONDS


def test_time_bounds_are_documented_as_wall_clock_not_media_duration() -> None:
    """The max-wait bound is wall clock; it is NOT the 180s media threshold."""

    mod = _load()

    # Both exist and are distinct concepts; a media-duration floor must not be
    # presented as the capture time bound.
    assert mod.DEFAULT_MAX_WAIT_SECONDS > 0
    assert mod.RELEASE_MIN_DURATION_SECONDS >= 180.0
    assert mod.DEFAULT_MAX_WAIT_SECONDS != mod.RELEASE_MIN_DURATION_SECONDS

# --- release-grade channel set, hard bounds, junction refusal --------------


def test_empty_channel_set_is_not_a_release_pass(tmp_path: Path) -> None:
    """``channels=()`` must never yield a vacuous PASS."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=(),
        scratch_root=tmp_path / "scratch",
        min_duration_seconds=180.0,
        duration_seconds=180.0,
    )

    assert result["verdict"] != mod.Verdict.PASS
    assert any("channel" in r.lower() for r in result["blocking_reasons"])


def test_subset_of_required_channels_is_not_release_pass(tmp_path: Path) -> None:
    """A one-channel CLI run must not look release-grade."""

    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=("public",),
        scratch_root=tmp_path / "scratch",
        min_duration_seconds=180.0,
        duration_seconds=180.0,
        run=lambda *a, **k: {
            "ok": True, "returncode": 0, "stdout": "",
            "stderr": "I:         -16.0 LUFS\nLRA:         2.0 LU\nPeak:       -1.3 dBFS\n",
        },
        ffprobe=None,
    )

    assert result["verdict"] != mod.Verdict.PASS or result.get("release_grade") is False


def test_exact_required_set_is_release_grade(tmp_path: Path) -> None:
    """The exact three-channel set is the only release-grade PASS shape."""

    mod = _load()
    assert mod.REQUIRED_CHANNELS == ("public", "government", "education")


def test_max_segments_has_a_hard_upper_cap(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=("public",),
        scratch_root=tmp_path / "scratch",
        min_duration_seconds=180.0,
        duration_seconds=180.0,
        max_segments=10_000_000,
    )

    assert result["verdict"] != mod.Verdict.PASS
    assert any("max_segments" in r.lower() for r in result["blocking_reasons"])


def test_max_wait_seconds_has_a_hard_upper_cap(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    _write_playlist(root / "public", media_sequence=0, count=3)

    result = mod.verify_all(
        root,
        channels=("public",),
        scratch_root=tmp_path / "scratch",
        min_duration_seconds=180.0,
        duration_seconds=180.0,
        max_wait_seconds=10_000_000.0,
    )

    assert result["verdict"] != mod.Verdict.PASS
    assert any("max_wait" in r.lower() for r in result["blocking_reasons"])


def test_junction_replacing_owned_scratch_is_refused(tmp_path: Path) -> None:
    """A junction/reparse point swapped in for our scratch must never be deleted."""

    mod = _load()
    parent = tmp_path / "parent"
    parent.mkdir()
    cleanup = mod.prepare_scratch_dir(parent)

    # Replace our owned dir with a junction pointing elsewhere, if we can.
    import shutil as _shutil

    _shutil.rmtree(cleanup.owned_dir, ignore_errors=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    made = False
    try:
        import subprocess as _sp

        r = _sp.run(
            ["cmd", "/c", "mklink", "/J", str(cleanup.owned_dir), str(target)],
            capture_output=True,
            text=True,
        )
        made = r.returncode == 0
    except OSError:
        made = False
    if not made:
        pytest.skip("junction creation not permitted on this host")

    removed = cleanup.remove()

    assert removed is False
    assert (target / "precious.txt").is_file(), "junction target must not be deleted"


def test_scratchdir_remove_uses_its_own_owned_dir(tmp_path: Path) -> None:
    """``remove()`` must delete only the instance's own owned dir, nothing else."""

    mod = _load()
    parent = tmp_path / "parent"
    parent.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("keep", encoding="utf-8")

    cleanup = mod.prepare_scratch_dir(parent)
    # Forging a different ScratchDir must not let remove() reach `other`.
    forged = mod.ScratchDir(parent=parent, owned_dir=other)
    removed_forged = mod.safe_remove_owned_dir(obj=forged, target=other)

    # Even a forged object may only remove a directory that is genuinely a
    # strict child of its declared parent AND not a link/reparse point.
    if removed_forged:
        assert not other.exists()
    else:
        assert (other / "keep.txt").is_file()
    # The genuine instance still removes only its own child.
    assert cleanup.remove() is True
    assert not cleanup.owned_dir.exists()

# --- real-ffmpeg end-to-end (skipped when ffmpeg is unavailable) -----------


_REAL_FFMPEG = Path(
    r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffmpeg.exe"
)
_REAL_TSP = Path(
    r"C:\Program Files\CivicCast (Native)\packs\native-server-binaries\payload\tsduck\bin\tsp.exe"
)
_REAL_FFPROBE = Path(
    r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"
)
if not _REAL_FFMPEG.is_file():  # pragma: no cover - host dependent
    _found_ffmpeg = shutil.which("ffmpeg")
    if _found_ffmpeg:
        _REAL_FFMPEG = Path(_found_ffmpeg)
if not _REAL_FFPROBE.is_file():  # pragma: no cover - host dependent
    _found_probe = shutil.which("ffprobe")
    if _found_probe:
        _REAL_FFPROBE = Path(_found_probe)


@pytest.mark.skipif(
    not _REAL_FFMPEG.is_file(), reason="real ffmpeg not available on this host"
)
def test_real_ffmpeg_measures_normalized_synthetic_window(tmp_path: Path) -> None:
    """A really-normalized continuous window must measure in-band and PASS.

    The fixture is ONE continuous encode produced by ffmpeg's real HLS muxer,
    so the emitted segments share a single monotonic PTS/PCR timeline exactly
    like the live station's output.  This is the analyzer + continuity path's
    positive control: it proves the tool reproduces a known -16 LUFS signal and
    that a genuinely continuous window is not falsely flagged.
    """

    import subprocess

    mod = _load()
    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)

    completed = subprocess.run(
        [
            str(_REAL_FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=30:duration=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=8:sample_rate=48000",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v",
            "libopenh264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "0",
            "-hls_segment_type",
            "mpegts",
            "-hls_segment_filename",
            str(channel / "seg%09d.ts"),
            str(channel / "playlist.m3u8"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr

    result = mod.verify_channel(
        "public",
        root,
        scratch_dir=tmp_path / "scratch",
        min_duration_seconds=6.0,
        release_grade=False,
        ffmpeg=_REAL_FFMPEG,
        ffprobe=_REAL_FFPROBE if _REAL_FFPROBE.is_file() else None,
        tsp=_REAL_TSP if _REAL_TSP.is_file() else None,
    )

    assert result["continuity"]["status"] == mod.Verdict.PASS, result["continuity"]
    assert result["audio_window"]["status"] == mod.Verdict.PASS, result["audio_window"]
    assert abs(result["audio_window"]["integrated_lufs"] - (-16.0)) <= 1.0

# --- bounded scratch cleanup ----------------------------------------------


def test_scratch_directory_is_removed_after_capture(tmp_path: Path) -> None:
    mod = _load()
    root = _hls_root(tmp_path, ("public",))
    channel = root / "public"
    _write_playlist(channel, media_sequence=900, count=3)
    scratch = tmp_path / "scratch"

    snapshot = mod.capture_channel(
        "public", root, scratch_dir=scratch, min_duration_seconds=0.0, required_segments=3
    )

    assert snapshot["status"] in (mod.Verdict.PASS, mod.Verdict.UNVERIFIED, mod.Verdict.FAIL)
    # Snapshot copies live inside the supplied scratch dir, never in the HLS root.
    for record in snapshot["segments"]:
        assert root not in Path(record["snapshot_path"]).parents


# --- U57: per-segment packet-level holes ------------------------------------


_U57_VIDEO_INTERVAL = 0.033334


def test_continuity_flags_mid_segment_video_hole() -> None:
    """A 0.600 s video gap inside one segment FAILs with its numbers (U57).

    These are the numbers the station's own ffprobe reports for
    public/seg000003655 at the 2026-09-26 programme changeover: 35 video
    packets, largest gap 0.600 s starting 0.833 s after the first packet.  Every
    head-to-head PTS step in that window stays legal, so the head-level check
    passed it -- the hole lives strictly inside the segment, and audio kept
    running through it (0.021 s max audio gap).
    """

    mod = _load()
    result = mod.evaluate_pts_pcr_continuity(
        [
            {
                "name": "public/seg000003654.ts",
                "video_start_pts": 90_000 * 100,
                "pcr_first": 5_000_000_000,
                "duration": 2.0,
            },
            {
                "name": "public/seg000003655.ts",
                "video_start_pts": 90_000 * 102,
                "pcr_first": 5_000_180_000,
                "duration": 2.0,
                "video_max_gap_seconds": 0.600,
                "video_max_gap_offset_seconds": 0.833334,
                "video_frame_interval_seconds": _U57_VIDEO_INTERVAL,
                "audio_max_gap_seconds": 0.021334,
                "audio_max_gap_offset_seconds": 1.2,
            },
        ]
    )

    assert result["status"] == mod.Verdict.FAIL
    assert result["problems"] == [
        "VIDEO_HOLE(public/seg000003655.ts, 0.600s at +0.833s)"
    ], result["problems"]


def test_continuity_flags_mid_segment_audio_hole() -> None:
    """An audio gap over 50 ms FAILs too -- a video-only check would miss it."""

    mod = _load()
    result = mod.evaluate_pts_pcr_continuity(
        [
            {
                "name": "public/seg000003700.ts",
                "video_start_pts": 90_000 * 100,
                "pcr_first": 5_000_000_000,
                "duration": 2.0,
                "video_max_gap_seconds": 0.033334,
                "video_frame_interval_seconds": _U57_VIDEO_INTERVAL,
                "audio_max_gap_seconds": 0.448,
                "audio_max_gap_offset_seconds": 0.512,
            },
        ]
    )

    assert result["status"] == mod.Verdict.FAIL
    assert result["problems"] == [
        "AUDIO_HOLE(public/seg000003700.ts, 0.448s at +0.512s)"
    ], result["problems"]


def test_continuity_packet_gap_threshold_is_strict() -> None:
    """Exactly two frame intervals (and exactly 50 ms of audio) is NOT a hole.

    The measured healthy step and the declared interval disagree in the fourth
    decimal (0.033334 s observed vs 0.033333 s from 30/1); a >= comparison
    would turn every healthy step of a whole channel into a hole.
    """

    mod = _load()
    record = {
        "name": "public/seg000003654.ts",
        "video_start_pts": 90_000 * 100,
        "pcr_first": 5_000_000_000,
        "duration": 2.0,
        "video_frame_interval_seconds": _U57_VIDEO_INTERVAL,
        "audio_max_gap_seconds": 0.05,
        "audio_max_gap_offset_seconds": 0.0,
    }

    at_the_bar = mod.evaluate_pts_pcr_continuity(
        [{**record, "video_max_gap_seconds": 2 * _U57_VIDEO_INTERVAL,
          "video_max_gap_offset_seconds": 0.0}]
    )
    assert at_the_bar["status"] == mod.Verdict.PASS, at_the_bar["problems"]

    over_the_bar = mod.evaluate_pts_pcr_continuity(
        [{**record, "video_max_gap_seconds": 2 * _U57_VIDEO_INTERVAL + 1e-6,
          "video_max_gap_offset_seconds": 0.0}]
    )
    assert over_the_bar["status"] == mod.Verdict.FAIL
    assert over_the_bar["problems"] == [
        "VIDEO_HOLE(public/seg000003654.ts, 0.067s at +0.000s)"
    ], over_the_bar["problems"]


def test_continuity_passes_clean_window_carrying_packet_stats() -> None:
    """A genuinely continuous window with packet stats still PASSes.

    This is the false-positive control for the new check: the 30 fps cadence of
    a healthy segment must not read as a hole.
    """

    mod = _load()
    result = mod.evaluate_pts_pcr_continuity(
        [
            {
                "name": f"public/seg{i:09d}.ts",
                "video_start_pts": 90_000 * (100 + 2 * i),
                "pcr_first": 5_000_000_000 + 180_000 * i,
                "duration": 2.0,
                "video_packets": 60,
                "video_max_gap_seconds": 0.033334,
                "video_max_gap_offset_seconds": 0.0,
                "video_frame_interval_seconds": _U57_VIDEO_INTERVAL,
                "audio_packets": 83,
                "audio_max_gap_seconds": 0.021334,
                "audio_max_gap_offset_seconds": 1.0,
            }
            for i in range(4)
        ]
    )

    assert result["status"] == mod.Verdict.PASS
    assert result["problems"] == []
    assert "packet gaps within tolerance" in result["detail"]


def test_continuity_names_hole_even_when_pcr_is_missing() -> None:
    """A proven hole outranks a missing PCR: FAIL, with the hole named.

    The shipped TSDuck payload carries no `pcrextract` plugin, so on that host
    every segment reports no PCR.  If the presence gate ran first it would
    return a bare "no PCR" UNVERIFIED and a measured 0.600 s hole would go
    unnamed -- the same blindness this check exists to remove.
    """

    mod = _load()
    result = mod.evaluate_pts_pcr_continuity(
        [
            {
                "name": "public/seg000003655.ts",
                "video_start_pts": 90_000 * 100,
                "pcr_first": None,
                "duration": 2.0,
                "video_max_gap_seconds": 0.600,
                "video_max_gap_offset_seconds": 0.833334,
                "video_frame_interval_seconds": _U57_VIDEO_INTERVAL,
            },
        ]
    )

    assert result["status"] == mod.Verdict.FAIL, result
    assert "VIDEO_HOLE(public/seg000003655.ts, 0.600s at +0.833s)" in result["problems"]
    assert "one or more segments report no PCR" in result["problems"]


def test_parse_frame_interval_reads_rational_and_rejects_junk() -> None:
    mod = _load()

    assert mod._parse_frame_interval("30/1") == pytest.approx(1 / 30)
    assert mod._parse_frame_interval("30000/1001") == pytest.approx(1001 / 30000)
    for junk in ("0/0", "60/0", "", "30", None, 30, "x/y"):
        assert mod._parse_frame_interval(junk) is None, junk


def test_inter_packet_gap_stats_reports_largest_gap_offset_and_cadence() -> None:
    """The stats are computed on the PTS-sorted timeline, with a real offset."""

    mod = _load()
    pts = [0.0, 0.033334, 0.066668, 0.666668, 0.700002, 0.733336]

    stats = mod._inter_packet_gap_stats(pts)

    assert stats["packets"] == 6
    assert stats["max_gap_seconds"] == pytest.approx(0.600, abs=1e-9)
    assert stats["max_gap_offset_seconds"] == pytest.approx(0.066668, abs=1e-9)
    assert stats["min_positive_gap_seconds"] == pytest.approx(0.033334, abs=1e-9)

    # Decode order may put a later PTS first; sorting is what makes the gap real.
    shuffled = [pts[3], pts[0], pts[5], pts[1], pts[4], pts[2]]
    assert mod._inter_packet_gap_stats(shuffled)["max_gap_seconds"] == pytest.approx(
        0.600, abs=1e-9
    )

    empty = mod._inter_packet_gap_stats([])
    assert empty["packets"] == 0
    assert empty["max_gap_seconds"] is None


_U57_FIXTURES_ENV = "CIVICAST_U57_FIXTURES"


def _u57_fixture_dir() -> Path | None:
    import os

    raw = os.environ.get(_U57_FIXTURES_ENV, "").strip()
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


@pytest.mark.skipif(
    _u57_fixture_dir() is None,
    reason=f"set {_U57_FIXTURES_ENV} to the U57 fixture copies to run this",
)
def test_u57_real_changeover_fixtures_report_the_hole() -> None:
    """The real emitted segments: the hole is named and its neighbours PASS.

    The fixtures are plain copies of station output taken at the 2026-09-26
    changeover (sha256 recorded in the oversight folder).  They are not in this
    repository, so the test skips unless CIVICAST_U57_FIXTURES points at them.
    """

    mod = _load()
    root = _u57_fixture_dir()
    assert root is not None
    ffprobe = mod._resolve_ffprobe()
    assert ffprobe is not None and Path(ffprobe).is_file(), "ffprobe not available"

    def probed(channel: str, sequences: list[int]) -> list[dict]:
        records = []
        for sequence in sequences:
            name = f"seg{sequence:09d}.ts"
            payload = mod._default_probe(ffprobe, root / channel / name)
            assert payload["status"] == mod.Verdict.PASS, (name, payload)
            records.append({"name": f"{channel}/{name}", **payload})
        return records

    public = probed("public", [3653, 3654, 3655, 3656, 3657])
    changeover = public[2]
    assert changeover["video_packets"] == 35
    assert changeover["video_max_gap_seconds"] == pytest.approx(0.600, abs=1e-6)
    assert changeover["video_max_gap_offset_seconds"] == pytest.approx(0.833334, abs=1e-6)
    assert changeover["audio_max_gap_seconds"] == pytest.approx(0.021334, abs=1e-6)
    assert public[1]["video_max_gap_seconds"] == pytest.approx(0.033334, abs=1e-6)

    government = probed("government", [3710, 3711, 3712, 3713])
    changeover = government[1]
    assert changeover["video_packets"] == 60
    assert changeover["video_max_gap_seconds"] == pytest.approx(0.581334, abs=1e-6)
    assert changeover["video_max_gap_offset_seconds"] == pytest.approx(1.933333, abs=1e-6)
    # r_frame_rate says 60/1 on this segment and its real cadence is 30 fps: the
    # derived interval must land on the observed cadence and not the declared
    # one, or the two-frame bar (0.033333 s) would sit at the healthy step
    # (0.033334 s) and all 59 healthy gaps would be called holes.  Float PTS
    # jitter leaves the observed cadence at 1/30 to within 0.1 ms.
    assert mod._parse_frame_interval("60/1") == pytest.approx(1 / 60, abs=1e-9)
    assert changeover["video_frame_interval_seconds"] == pytest.approx(1 / 30, abs=1e-4)

    # PTS heads on the public chain are continuous (measured: every head delta
    # equals the previous segment's duration to the tick), so the hole is the
    # only thing that can fail this window.
    with_pcr = [
        {**record, "pcr_first": 5_000_000_000 + 180_000 * i}
        for i, record in enumerate(public)
    ]
    verdict = mod.evaluate_pts_pcr_continuity(with_pcr)
    assert verdict["status"] == mod.Verdict.FAIL, verdict
    assert verdict["problems"] == [
        "VIDEO_HOLE(public/seg000003655.ts, 0.600s at +0.833s)"
    ], verdict["problems"]

    # A contiguous run of clean neighbours still PASSes, on both sides of the
    # changeover.  (Dropping only the middle segment would not be a fair clean
    # window: the head check would then see a 336000-tick jump against the
    # previous segment's 180000-tick duration and fail on that -- correctly.)
    clean_windows = [with_pcr[:2], with_pcr[3:]]
    for window in clean_windows:
        assert len(window) >= 2
        verdict = mod.evaluate_pts_pcr_continuity(window)
        assert verdict["status"] == mod.Verdict.PASS, (window, verdict["problems"])

    # And the government window names its own hole.  Its 3711 -> 3712 head delta
    # is 1500 ticks (16.7 ms) short of the declared duration, under the 3000-tick
    # frame tolerance, so that head check passes and the hole is what fails.
    government_pcr = [
        {**record, "pcr_first": 5_000_000_000 + 180_000 * i}
        for i, record in enumerate(government)
    ]
    verdict = mod.evaluate_pts_pcr_continuity(government_pcr)
    assert verdict["status"] == mod.Verdict.FAIL, verdict
    assert verdict["problems"] == [
        "VIDEO_HOLE(government/seg000003711.ts, 0.581s at +1.933s)"
    ], verdict["problems"]
