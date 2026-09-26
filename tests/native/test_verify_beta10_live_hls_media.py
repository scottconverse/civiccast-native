# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract + sensitivity tests for the beta.10 live-HLS media verifier.

These are SYNTHETIC-FIXTURE tests. They never read the live station and never
depend on a running supervisor, so they are safe to run during a controlled
restart and are not acceptance evidence. Each negative test is paired with a
positive control so the assertion can actually fail (test sensitivity).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_beta10_live_hls_media.py"
_SPEC = importlib.util.spec_from_file_location("verify_beta10_live_hls_media", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
verify = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = verify
_SPEC.loader.exec_module(verify)


def _write_playlist(path: Path, *, media_sequence: int = 927, count: int = 3) -> list[str]:
    names = [f"seg{media_sequence + i:09d}.ts" for i in range(count)]
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        "#EXT-X-TARGETDURATION:2",
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
    ]
    for name in names:
        lines.append("#EXTINF:2.000000,")
        lines.append("#EXT-X-PROGRAM-DATE-TIME:2026-09-23T20:38:23.167-0600")
        lines.append(name)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return names


def _touch_segments(channel_dir: Path, names: list[str], *, size: int = 1024) -> None:
    for name in names:
        (channel_dir / name).write_bytes(b"\x47" * size)



def _stub_probe_ok(_ffprobe, _segment):  # pragma: no cover - test stub
    return {
        "status": verify.Verdict.PASS,
        "duration": 2.0,
        "video_start_pts": 90_000,
        "video_codec": "h264",
        "audio_codec": "aac",
    }


def _stub_ffmpeg_ok(_ffmpeg, _segment):  # pragma: no cover - test stub
    return {"status": verify.Verdict.PASS}


def _stub_tsp_ok(_tsp, _segment):  # pragma: no cover - test stub
    return {"status": verify.Verdict.PASS}

# --- Playlist parsing ------------------------------------------------------


def test_parse_playlist_reads_sequence_and_segments(tmp_path: Path) -> None:
    pl = tmp_path / "playlist.m3u8"
    names = _write_playlist(pl, media_sequence=927, count=3)

    parsed = verify.parse_playlist(pl)

    assert parsed.media_sequence == 927
    assert parsed.target_duration == 2.0
    assert parsed.segments == names
    assert parsed.parse_error is None


def test_parse_playlist_missing_file_is_an_error_not_empty_success(tmp_path: Path) -> None:
    parsed = verify.parse_playlist(tmp_path / "absent.m3u8")

    assert parsed.parse_error == "playlist missing"
    assert parsed.segments == []


def test_parse_playlist_without_extm3u_is_rejected(tmp_path: Path) -> None:
    pl = tmp_path / "playlist.m3u8"
    pl.write_text("#EXTINF:2.0,\nseg000000001.ts\n", encoding="utf-8")

    parsed = verify.parse_playlist(pl)

    assert parsed.parse_error == "missing #EXTM3U"


def test_sequence_number_parses_generated_segment_names() -> None:
    assert verify._sequence_number("seg000001234.ts") == 1234
    assert verify._sequence_number("not-a-segment.ts") is None


# --- Continuity (sensitive: positive control + negatives) ------------------


def _segment_record(pts: int, pcr: int, duration: float = 2.0) -> dict:
    return {
        "video_start_pts": pts,
        "pcr_first": pcr,
        "duration": duration,
        "probe": {"status": verify.Verdict.PASS},
        "decode": {"status": verify.Verdict.PASS},
        "ts": {"status": verify.Verdict.PASS},
    }


def test_continuity_passes_for_forward_two_second_cadence() -> None:
    records = [
        _segment_record(90_000, 5_000_000_000),
        _segment_record(270_000, 5_000_180_000),
        _segment_record(450_000, 5_000_360_000),
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.PASS


def test_continuity_fails_when_pts_goes_backwards() -> None:
    records = [
        _segment_record(90_000, 5_000_000_000),
        _segment_record(90_000, 5_000_180_000),  # backwards/zero delta
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.FAIL
    assert "did not advance" in result["detail"]


def test_continuity_fails_when_pts_gap_is_not_one_segment() -> None:
    records = [
        _segment_record(90_000, 5_000_000_000),
        _segment_record(90_000 + 180_000 * 4, 5_000_180_000),  # 4x gap
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.FAIL


def test_continuity_fails_when_pcr_stalls() -> None:
    records = [
        _segment_record(90_000, 5_000_000_000),
        _segment_record(270_000, 5_000_000_000),  # PCR did not advance
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.FAIL
    assert "PCR did not advance" in result["detail"]


def test_continuity_uses_previous_segment_duration_for_unequal_lengths() -> None:
    """Delta from seg N-1 to N must equal N-1's duration, not N's.

    Segment 0 is 2.0s and segment 1 is 6.0s. The true gap is 2.0s, so a correct
    check (previous duration) passes; a buggy check against the CURRENT (6.0s)
    duration would wrongly expect 6.0s and fail.
    """

    records = [
        _segment_record(90_000, 5_000_000_000, duration=2.0),
        _segment_record(90_000 + 180_000, 5_000_180_000, duration=6.0),
        _segment_record(90_000 + 180_000 + 540_000, 5_000_720_000, duration=2.0),
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.PASS


def test_continuity_flags_gap_when_measured_against_previous_duration() -> None:
    """Positive control for the previous-duration rule: a real gap still fails."""

    records = [
        _segment_record(90_000, 5_000_000_000, duration=2.0),
        _segment_record(90_000 + 180_000 * 3, 5_000_180_000, duration=2.0),  # 3x gap
    ]

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.FAIL


def test_continuity_is_unverified_when_pcr_is_missing() -> None:
    records = [
        _segment_record(90_000, 5_000_000_000),
        _segment_record(270_000, None),  # type: ignore[arg-type]
    ]
    records[1]["pcr_first"] = None

    result = verify.evaluate_timestamp_continuity(records)

    assert result["status"] == verify.Verdict.UNVERIFIED


# --- Loudness / silence ----------------------------------------------------


_LOUDNESS_STDERR_CLEAN = """
[Parsed_ebur128_0 @ 000] Integrated loudness:
  I:         -15.7 LUFS
  LRA:         1.2 LU
[Parsed_ebur128_0 @ 000] True peak:
  Peak:       -1.2 dBFS
"""

_LOUDNESS_STDERR_SILENT = """
[Parsed_ebur128_0 @ 000] Integrated loudness:
  I:         -70.0 LUFS
  LRA:         0.0 LU
[Parsed_ebur128_0 @ 000] True peak:
  Peak:      -91.0 dBFS
"""


def test_parse_last_float_extracts_latest_lufs() -> None:
    assert verify._parse_last_float(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS\b", _LOUDNESS_STDERR_CLEAN) == -15.7


def test_loudness_window_within_target_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)

    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": _LOUDNESS_STDERR_CLEAN},
    )

    result = verify.measure_window_audio(Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[180.0])

    assert result["status"] == verify.Verdict.PASS
    assert result["integrated_lufs"] == pytest.approx(-15.7)


def test_loudness_window_flags_silent_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)

    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": _LOUDNESS_STDERR_SILENT},
    )

    result = verify.measure_window_audio(Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[180.0])

    assert result["status"] == verify.Verdict.FAIL
    assert result["silent"] is True
    assert result["within_target"] is False
    assert result["status"] == verify.Verdict.FAIL


def test_loudness_window_flags_out_of_target_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    stderr = _LOUDNESS_STDERR_CLEAN.replace("-15.7", "-22.0")

    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": stderr},
    )

    result = verify.measure_window_audio(Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[180.0])

    assert result["status"] == verify.Verdict.FAIL
    assert result["within_target"] is False


def test_loudness_window_without_segments_fails_closed(tmp_path: Path) -> None:
    result = verify.measure_window_audio(Path("ffmpeg"), [], tmp_path / "list.txt")

    assert result["status"] == verify.Verdict.FAIL


# --- Caption decode-back (ffmpeg subcc -- proven sensitive) ----------------

_REAL_FIXTURES = Path(__file__).resolve().parents[1] / "egress" / "fixtures"
_POSITIVE_FIXTURE = _REAL_FIXTURES / "cea708_test_caption.mpegts"
_NEGATIVE_FIXTURE = _REAL_FIXTURES / "cea708_no_captions.mpegts"


def _subcc_runner(srt_text: str, *, returncode: int = 0, stderr: str = ""):
    """A fake ffmpeg runner returning fixed subcc SRT output."""

    def _run(_args, **_kwargs):
        return type(
            "C",
            (),
            {"returncode": returncode, "stdout": srt_text, "stderr": stderr},
        )()

    return _run


_SRT_ONE_CUE = (
    "1\n"
    "00:00:00,000 --> 00:00:01,600\n"
    "CIVICCAST CEA708 TEST.\n"
    "\n"
)


def test_subcc_real_positive_fixture_decodes_a_cue() -> None:
    """REAL positive fixture: the proven subcc route must find >= 1 cue."""

    assert _POSITIVE_FIXTURE.is_file(), f"missing fixture: {_POSITIVE_FIXTURE}"

    result = verify._decode_captions(_POSITIVE_FIXTURE)

    assert result["status"] == verify.Verdict.PASS
    assert result["decoded_text_present"] is True
    assert result["decoded_cue_count"] >= 1


def test_subcc_real_negative_fixture_finds_no_cues() -> None:
    """REAL negative fixture: the proven subcc route must find 0 cues -> FAIL."""

    assert _NEGATIVE_FIXTURE.is_file(), f"missing fixture: {_NEGATIVE_FIXTURE}"

    result = verify._decode_captions(_NEGATIVE_FIXTURE)

    assert result["status"] == verify.Verdict.FAIL
    assert result["decoded_text_present"] is False
    assert result["decoded_cue_count"] == 0


def test_subcc_real_positive_differs_from_negative() -> None:
    """Sensitivity guard: the SAME path must separate positive from negative.

    This is the exact property the old GStreamer chain failed (0 cues on both).
    """

    pos = verify._decode_captions(_POSITIVE_FIXTURE)
    neg = verify._decode_captions(_NEGATIVE_FIXTURE)

    assert pos["status"] == verify.Verdict.PASS
    assert neg["status"] == verify.Verdict.FAIL
    assert pos["decoded_cue_count"] > neg["decoded_cue_count"]


def test_subcc_no_raw_cue_text_in_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A future PASS must never persist or broadcast decoded speech content."""

    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(verify.subprocess, "run", _subcc_runner(_SRT_ONE_CUE))

    result = verify._decode_captions(seg)
    serialized = json.dumps(result)

    assert result["status"] == verify.Verdict.PASS
    assert "CIVICCAST" not in serialized
    assert result["decoded_text_present"] is True
    assert result["decoded_cue_count"] == 1
    assert "decoded_text" not in result


def test_subcc_stderr_never_leaks_cue_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(
        verify.subprocess,
        "run",
        _subcc_runner("", returncode=2, stderr="boom SECRET_SPEECH_IN_STDERR"),
    )

    result = verify._decode_captions(seg)

    assert result["status"] == verify.Verdict.UNVERIFIED
    assert "SECRET_SPEECH" not in json.dumps(result)


def test_subcc_no_ffmpeg_is_not_proven(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(verify, "_ffmpeg_path", lambda: None)

    result = verify._decode_captions(seg)

    assert result["status"] == verify.Verdict.NOT_PROVEN


def test_caption_decoder_available_uses_subcc_readeia608(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "_ffmpeg_path", lambda: Path("ffmpeg"))
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": " ... readeia608 ... ", "stderr": ""},
    )

    probe = verify.caption_decoder_available()

    assert probe["available"] is True
    assert probe["decoder"] == "ffmpeg-subcc"
    assert probe["readeia608"] is True


def test_caption_decoder_unavailable_without_readeia608(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "_ffmpeg_path", lambda: Path("ffmpeg"))
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "no such filter", "stderr": ""},
    )

    probe = verify.caption_decoder_available()

    assert probe["available"] is False


def test_caption_decode_error_is_unverified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(verify.subprocess, "run", _subcc_runner("", returncode=1, stderr="nope"))

    result = verify._decode_captions(seg)

    assert result["status"] == verify.Verdict.UNVERIFIED


# --- Window-level caption fail-closed + decoder-absent ---------------------


def _channel_with_segments(tmp_path: Path, count: int = 3) -> tuple[Path, list[str]]:
    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=100, count=count)
    _touch_segments(channel, names)
    return root, names


#: The instant this file's fixtures are pinned to: segments, logs and the
#: stubbed module clock all read `1_700_000_000.0`, so an age is exactly the
#: difference the test wrote and never a function of the wall clock.
_FIXTURE_EPOCH = 1_700_000_000.0


#: A segment left in the live channel dir by a PREVIOUS run carries a HIGHER
#: sequence number than the current run's newest -- observed live 2026-09-26:
#: public `seg000018677.ts` (Sep 19) sits beside the running `seg000001284.ts`.
#: Anything that chooses a window by name or sequence chooses those fossils.
_FOSSIL_AGE_SECONDS = 3 * 86400.0


def _emitted_channel(
    tmp_path: Path, *, count: int = 40, seconds: float = 2.0, playlist_count: int = 6
) -> tuple[Path, list[str]]:
    """A channel whose segments carry explicit EMISSION times, oldest first.

    Segment names ascend with emission time and the playlist lists only the
    newest `playlist_count`, the way the relay's own does.
    """
    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)
    first = 1000
    names = [f"seg{first + index:09d}.ts" for index in range(count)]
    _write_playlist(
        channel / "playlist.m3u8",
        media_sequence=first + count - playlist_count,
        count=playlist_count,
    )
    _touch_segments(channel, names)
    base = _FIXTURE_EPOCH
    for index, name in enumerate(names):
        stamp = base - (count - 1 - index) * seconds
        os.utime(channel / name, (stamp, stamp))
    return root, names


#: The keeper's own folder, named exactly as `bin\\segment_keeper.py` names it.
_KEEP_DIR_NAME = "cc-caption-keep"


def _rotated_channel(
    tmp_path: Path,
    *,
    emitted: int = 40,
    live_segments: int = 7,
    seconds: float = 2.0,
    first: int = 1000,
) -> tuple[Path, Path, list[str]]:
    """A channel whose ROTATED-AWAY segments survive only as keeper copies.

    Observed live 2026-09-26 (U50): `live-hls\\public\\` held 50 `seg*.ts` but only
    7 were live (~14 s at 2 s each) -- the relay DELETES each segment as it rotates
    it out, so all the ~60 s window needs (everything older than the playlist tail)
    was already gone when the verifier looked.  This fixture is that shape: the
    newest `live_segments` live in the channel dir, every older segment exists only
    as a copy under `<keep_root>/public/`, and both sets carry their true emission
    times, so the two are contiguous across the rotation boundary and the union
    spans the real history.  Returns ``(hls_root, keep_root, names_oldest_first)``.
    """

    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)
    names = [f"seg{first + index:09d}.ts" for index in range(emitted)]
    _write_playlist(channel / "playlist.m3u8", media_sequence=first + emitted - 6, count=6)
    live = set(names[-live_segments:])
    keep_root = tmp_path / _KEEP_DIR_NAME
    keep_channel = keep_root / "public"
    keep_channel.mkdir(parents=True)
    _touch_segments(channel, [name for name in names if name in live])
    _touch_segments(keep_channel, [name for name in names if name not in live])
    for index, name in enumerate(names):
        stamp = _FIXTURE_EPOCH - (emitted - 1 - index) * seconds
        target = channel / name if name in live else keep_channel / name
        os.utime(target, (stamp, stamp))
    return root, keep_root, names


def _write_keep_heartbeat(keep_root: Path, *, age: float, now: float = _FIXTURE_EPOCH) -> Path:
    """The keeper's liveness file, aged by `age` seconds.

    The keeper rewrites it every loop (4 s), so `age` is the whole liveness
    argument: a fresh line means a keeper was copying segments into this folder
    seconds ago and its copies are the recent past, not a stopped run's leftovers.
    """

    path = keep_root / "heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = now - age
    path.write_text(
        json.dumps({"updated_epoch": stamp, "loops": 12, "pid": 4321}), encoding="utf-8"
    )
    os.utime(path, (stamp, stamp))
    return path


def _write_worker_log(
    root: Path, channel: str, lines: list[str], *, age: float = 0.0, now: float = _FIXTURE_EPOCH
) -> Path:
    """The playout worker's stdout log for one channel, aged by `age` seconds.

    The log lives beside the live-hls root, not inside it: on the station the
    root is `...\\egress\\live-hls` and the log is `...\\egress\\<ch>\\logs\\`.
    """
    path = Path(root).parent / channel / "logs" / "gst-worker.stdout.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stamp = now - age
    os.utime(path, (stamp, stamp))
    return path


def _stub_all_av(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "probe_segment", _stub_probe_ok)
    monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
    monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
    monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)


def test_window_decodes_every_finished_segment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The window must decode EVERY finished segment it covers, not just the newest."""

    root, names = _emitted_channel(tmp_path)
    calls: list[str] = []

    def recording_decode(path):
        calls.append(Path(path).name)
        return {
            "status": verify.Verdict.PASS,
            "detail": "ok",
            "decoded_text_present": True,
            "decoded_text_bytes": 5,
            "decoded_text_sha256": "deadbeef",
            "decoded_cue_count": 1,
        }

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "_decode_captions", recording_decode)
    _stub_all_av(monkeypatch)

    verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    # 40 emitted segments 2 s apart -> the newest 60 s is 30 of them; the newest
    # two are never read (they may still be open), so indices 8..37.
    assert calls == names[8:38]
    assert len(calls) == 30


def test_window_sparse_captions_still_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sparse captions (some segments cue, some clean-but-empty) -> PASS.

    Stable-TS diagnostics (2026-09-24) decoded cues in only 4 of 9 sampled
    segments across three HEALTHY channels: captions are naturally sparse in 2s
    segments. Requiring text in EVERY segment would fail a healthy stream.
    """
    root, names = _emitted_channel(tmp_path)

    def fake_decode(path):
        if Path(path).name == names[20]:
            return {
                "status": verify.Verdict.PASS,
                "detail": "ok",
                "decoded_text_present": True,
                "decoded_text_bytes": 5,
                "decoded_text_sha256": "deadbeef",
                "decoded_cue_count": 1,
            }
        # clean decode, no cues in this segment
        return {
            "status": verify.Verdict.FAIL,
            "detail": "no cues",
            "decoded_text_present": False,
            "decoded_text_bytes": 0,
            "decoded_text_sha256": "",
            "decoded_cue_count": 0,
        }

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "_decode_captions", fake_decode)
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    assert len(result["caption_decode_back"]["per_segment"]) == 30
    assert result["caption_decode_back"]["status"] == verify.Verdict.PASS


def test_window_all_segments_captionless_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No cues anywhere in a CLEAN window -> caption FAIL (no weakening)."""
    root, _names = _emitted_channel(tmp_path)

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(
        verify,
        "_decode_captions",
        lambda *a, **k: {
            "status": verify.Verdict.FAIL,
            "detail": "no cues",
            "decoded_text_present": False,
            "decoded_text_bytes": 0,
            "decoded_text_sha256": "",
            "decoded_cue_count": 0,
        },
    )
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    assert result["caption_decode_back"]["status"] == verify.Verdict.FAIL
    assert result["status"] == verify.Verdict.FAIL
    assert result["caption_decode_back"]["cue_count"] == 0


def test_window_any_unverified_segment_forces_unverified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A vanished/undecodable segment keeps the window UNVERIFIED, not PASS/FAIL."""
    root, names = _emitted_channel(tmp_path)

    def fake_decode(path):
        if Path(path).name == names[20]:
            return {"status": verify.Verdict.UNVERIFIED, "detail": "decode error"}
        return {
            "status": verify.Verdict.PASS,
            "detail": "ok",
            "decoded_text_present": True,
            "decoded_text_bytes": 5,
            "decoded_text_sha256": "deadbeef",
            "decoded_cue_count": 1,
        }

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "_decode_captions", fake_decode)
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    assert result["caption_decode_back"]["status"] == verify.Verdict.UNVERIFIED

def test_decoder_absent_fails_closed_through_verify_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Decoder absence must NOT_PROVEN/fail-closed at the channel level."""

    root, _names = _channel_with_segments(tmp_path)
    monkeypatch.setattr(
        verify,
        "caption_decoder_available",
        lambda: {"available": False, "decoder": "ffmpeg-subcc", "detail": "no ffmpeg"},
    )
    monkeypatch.setattr(
        verify, "_decode_captions", lambda *a, **k: {"status": verify.Verdict.PASS}
    )
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    assert result["caption_decode_back"]["status"] == verify.Verdict.NOT_PROVEN
    assert result["status"] in (verify.Verdict.UNVERIFIED, verify.Verdict.FAIL)


# --- Caption decode-back window: the newest ~60 s of FINISHED segments -----
#
# U48 follow-on, from a real rung: verify #4 of rung-8h-post-u44 (2026-09-26
# 13:10:02) failed government and education caption_decode_back over 4 segments
# (~8 s) while both channels' workers had injected 14-17 captions/minute and
# government's sidecar read "take a five-minute break" (a recess). An 8 s window
# fails on any speech pause, so an 8 h rung fails on noise. The window is now
# ~60 s of finished segments and the judgement needs ONE cue in it.


def test_caption_window_is_the_newest_sixty_seconds_of_finished_segments(tmp_path: Path) -> None:
    root, names = _emitted_channel(tmp_path, count=40, seconds=2.0)

    window = verify.caption_window(root / "public", segment_seconds=2.0)

    assert [item["segment"] for item in window["segments"]] == names[8:38]
    assert window["span_seconds"] == 60.0


def test_caption_window_excludes_the_two_newest_segments(tmp_path: Path) -> None:
    """The newest two may still be open: they are never copied or decoded."""
    root, names = _emitted_channel(tmp_path, count=6, seconds=2.0)

    window = verify.caption_window(root / "public", segment_seconds=2.0)

    assert [item["segment"] for item in window["segments"]] == names[:-2]
    assert window["newest_excluded"] == names[-2:]
    assert window["span_seconds"] == 8.0


def test_caption_window_never_reaches_a_fossil_from_a_previous_run(tmp_path: Path) -> None:
    """Selection is by EMISSION TIME: fossils outrank the live run by name."""
    root, names = _emitted_channel(tmp_path, count=6, seconds=2.0)
    channel = root / "public"
    fossils = ["seg000018677.ts", "seg000018678.ts"]
    for name in fossils:
        (channel / name).write_bytes(b"\x47" * 1024)
        stamp = 1_700_000_000.0 - _FOSSIL_AGE_SECONDS
        os.utime(channel / name, (stamp, stamp))

    window = verify.caption_window(channel, segment_seconds=2.0)

    got = [item["segment"] for item in window["segments"]]
    assert got == names[:-2]
    assert not set(got) & set(fossils)
    assert window["older_excluded"] == 2


# --- U50: the 60 s window needs the keeper's copies ------------------------
#
# Measured live 2026-09-26: `live-hls\public\` held 7 live segments (~14 s at 2 s
# each) and the verifier reported `span_seconds` 10.0 on all three channels of
# rung 8h-post-u47 -- the 60 s window existed only on paper, because the relay
# had already deleted every segment it rotated out.  `bin\segment_keeper.py`
# copies finished segments aside before that happens; the window is the live dir
# UNION those copies.  The keeper's own liveness file is what makes them
# trustworthy: a stopped keeper's copies are a fossil group like any other.


def test_caption_window_fills_sixty_seconds_from_the_keeper_copies(tmp_path: Path) -> None:
    """7 live segments cannot make 60 s; the keeper's copies of the rotated-away ones can."""
    root, keep_root, names = _rotated_channel(tmp_path, emitted=40, live_segments=7)
    heartbeat = _write_keep_heartbeat(keep_root, age=3.0)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    assert heartbeat.is_file()
    assert keep.usable is True
    assert keep.heartbeat_age_seconds == 3.0
    assert [item["segment"] for item in window["segments"]] == names[8:38]
    assert window["span_seconds"] == 60.0
    # 30 segments end at names[37]; the live dir only holds names[33:] ...
    assert window["from_live"] == 5
    # ... so 25 of the 30 could come from nowhere but the keeper's copies.
    assert window["from_keep"] == 25
    assert window["source"] == "keep"


def test_caption_window_from_the_live_dir_alone_is_ten_seconds(tmp_path: Path) -> None:
    """The U50 defect, pinned: 7 live segments, 2 excluded, 5 x 2 s = 10 s.

    This is what every verify of rung 8h-post-u47 reported (`span_seconds` 10.0),
    and it is still the honest answer when no keeper is running -- the point is
    that the evidence must SAY which of the two it is.
    """
    root, _keep_root, _names = _rotated_channel(tmp_path, emitted=40, live_segments=7)

    window = verify.caption_window(root / "public", segment_seconds=2.0)

    assert window["span_seconds"] == 10.0
    assert window["source"] == "live"
    assert window["from_keep"] == 0
    assert window["from_live"] == 5


def test_caption_window_prefers_the_live_file_over_a_keeper_copy_of_the_same_segment(
    tmp_path: Path,
) -> None:
    """A segment in BOTH places is one segment, read from the live dir.

    This is the NORMAL case, not an edge: the keeper copies every finished
    segment, and a finished segment stays in the live dir for another rotation or
    two.  Counting it twice would inflate the span, and reading the copy when the
    live file is still on air would report dead bytes as the stream.
    """
    root, keep_root, names = _rotated_channel(tmp_path, emitted=40, live_segments=7)
    # The keeper's copy of a segment that is still live (its poll caught it while
    # the relay had not yet rotated it away).  The keeper preserves the SOURCE
    # mtime, so the two entries are identical in every field but their path -- the
    # only thing that can tell them apart is the name, which is the point.
    overlapped = names[35]
    copy = keep_root / "public" / overlapped
    copy.write_bytes(b"\x47" * 512)
    os.utime(copy, (_FIXTURE_EPOCH - 8.0, _FIXTURE_EPOCH - 8.0))
    assert copy.stat().st_mtime_ns == (root / "public" / overlapped).stat().st_mtime_ns
    _write_keep_heartbeat(keep_root, age=1.0)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    got = [item for item in window["segments"] if item["segment"] == overlapped]
    assert len(got) == 1
    assert got[0]["path"] == str(root / "public" / overlapped)
    # names[35] is the 6th-newest of 40, so its true emission time is 8 s back.
    assert got[0]["mtime_ns"] == int((_FIXTURE_EPOCH - 8.0) * 1_000_000_000)
    # The window is unchanged by the overlap: still names[8:38] and 60 s.
    assert [item["segment"] for item in window["segments"]] == names[8:38]
    assert window["span_seconds"] == 60.0
    assert window["from_live"] == 5


def test_caption_window_with_a_stale_keeper_heartbeat_is_the_live_dir_alone(tmp_path: Path) -> None:
    """A keeper that stopped 412 s ago is not evidence about the last 60 s."""
    root, keep_root, _names = _rotated_channel(tmp_path, emitted=40, live_segments=7)
    _write_keep_heartbeat(keep_root, age=verify.CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS + 382.0)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    assert keep.usable is False
    # Not merely unused: a stale keeper's copies are refused outright, so no
    # caller can be tempted to read them anyway.
    assert keep.channel_dir("public") is None
    assert "412" in keep.note and "30" in keep.note
    assert str(keep_root) in keep.note
    assert window["span_seconds"] == 10.0
    assert window["source"] == "live"
    assert window["keep_heartbeat_age_seconds"] == 412.0


def test_caption_window_with_no_keeper_heartbeat_at_all_falls_back(tmp_path: Path) -> None:
    """No heartbeat file: not a keeper folder, whatever is lying in it."""
    root, keep_root, _names = _rotated_channel(tmp_path, emitted=40, live_segments=7)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    assert keep.usable is False
    assert keep.heartbeat_age_seconds is None
    assert "heartbeat" in keep.note
    assert window["span_seconds"] == 10.0
    assert window["source"] == "live"


def test_caption_window_refuses_fossils_even_when_the_keeper_dir_is_the_only_source(
    tmp_path: Path,
) -> None:
    """Both live segments are excluded as newest, so the keeper dir is all there is.

    What lies there is a previous run's segment -- the fossil U50 was told to
    expect.  A window that reached it would be reporting dead media as the
    stream; the staleness rule must refuse it on the keep side too.
    """
    root, keep_root, _names = _rotated_channel(tmp_path, emitted=2, live_segments=2)
    fossil = keep_root / "public" / "seg000018677.ts"
    fossil.write_bytes(b"\x47" * 1024)
    stamp = _FIXTURE_EPOCH - _FOSSIL_AGE_SECONDS
    os.utime(fossil, (stamp, stamp))
    _write_keep_heartbeat(keep_root, age=1.0)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    assert keep.usable is True  # the keeper IS fresh; the fossil is refused anyway
    assert window["segments"] == []
    assert window["span_seconds"] == 0.0
    assert window["older_excluded"] == 1


def test_caption_window_stops_at_a_hole_in_the_kept_segments(tmp_path: Path) -> None:
    """A window is only honest while it is CONTIGUOUS.

    The keeper polls every 4 s and copies every finished segment it has not
    copied yet, so it does not normally miss one -- but if it does (started late,
    a poll lost), the copies are holed, and `count x segment_seconds` would then
    claim a span the media does not cover.  The walk stops at the hole and says
    where, instead of counting across it.
    """
    root, keep_root, names = _rotated_channel(tmp_path, emitted=40, live_segments=7)
    (keep_root / "public" / names[20]).unlink()  # the poll that missed one
    _write_keep_heartbeat(keep_root, age=1.0)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    window = verify.caption_window(
        root / "public",
        segment_seconds=2.0,
        keep_dir=keep.channel_dir("public"),
        keep_heartbeat_age_seconds=keep.heartbeat_age_seconds,
    )

    assert [item["segment"] for item in window["segments"]] == names[21:38]
    assert window["span_seconds"] == 34.0
    assert window["gap_stopped_at"] == names[19]
    assert window["gap_seconds"] == 4.0


def test_verify_channel_evidence_names_the_keep_dir_and_its_heartbeat_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The channel evidence must carry the union's provenance, not just its span."""
    root, keep_root, _names = _rotated_channel(tmp_path, emitted=40, live_segments=7)
    _write_keep_heartbeat(keep_root, age=1.5)
    _write_worker_log(
        root,
        "public",
        ["CTRL caption public: received=9 injected=9 replayed=0 rejected=0 in 60s"],
        age=5.0,
    )

    def recording_decode(path):
        # 25 of the 30 window segments exist ONLY as keeper copies: a decode-back
        # that reached the live channel dir alone would come back UNVERIFIED.
        return {
            "status": verify.Verdict.PASS,
            "detail": "ok",
            "decoded_text_present": True,
            "decoded_text_bytes": 5,
            "decoded_text_sha256": "deadbeef",
            "decoded_cue_count": 1,
        }

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "_decode_captions", recording_decode)
    _stub_all_av(monkeypatch)

    keep = verify.resolve_caption_keep(keep_root, requested=True)
    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
        caption_keep=keep,
    )

    block = result["caption_window"]
    assert block["span_seconds"] == 60.0
    assert block["segment_count"] == 30
    assert block["source"] == "keep"
    assert block["from_keep"] == 25
    assert block["from_live"] == 5
    assert block["keep_dir"] == str(keep_root)
    assert block["keep_dir_used"] is True
    assert block["keep_heartbeat_age_seconds"] == 1.5
    assert block["emitted_first_utc"].startswith("2023")  # the fixture epoch's year
    # Every one of the 30 decoded cleanly -- proof the keeper's copies were the
    # bytes on the table, not a fallback the live dir happened to satisfy.
    assert result["caption_decode_back"]["status"] == verify.Verdict.PASS
    assert result["caption_decode_back"]["cue_count"] == 30
    assert result["caption_decode_back"]["span_seconds"] == 60.0


def test_verify_channel_without_a_keep_dir_says_so_in_the_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No keeper in play: the evidence states the window came from the live dir alone."""
    root, _keep_root, names = _rotated_channel(tmp_path, emitted=40, live_segments=7)

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(
        verify,
        "_decode_captions",
        lambda *a, **k: {"status": verify.Verdict.PASS, "decoded_cue_count": 1},
    )
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    block = result["caption_window"]
    assert block["source"] == "live"
    assert block["keep_dir_used"] is False
    assert block["keep_dir"] is None
    assert block["keep_heartbeat_age_seconds"] is None
    assert block["span_seconds"] == 10.0
    assert result["caption_decode_back"]["per_segment"] != []
    assert names[-2:] == block["newest_excluded"]


def test_verify_all_hands_the_keep_source_to_every_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI-resolved keeper must reach each channel's own verify_channel call."""
    root, names = _emitted_channel(tmp_path, count=8, seconds=2.0)
    monkeypatch.setattr(
        verify,
        "tool_versions",
        lambda: {"ffprobe": {"path": None}, "ffmpeg": {"path": None}, "tsp": {"path": None}},
    )
    monkeypatch.setattr(
        verify,
        "snapshot_channels",
        lambda *_a, **_k: {"channels": {"public": None}, "scratch": tmp_path / "scratch"},
    )
    seen: list[object] = []

    def spy(channel_id, hls_root, **kwargs):
        seen.append(kwargs.get("caption_keep"))
        return {"status": verify.Verdict.PASS, "channel": channel_id, "segments": names}

    monkeypatch.setattr(verify, "verify_channel", spy)
    keep = verify.CaptionKeepSource(
        root=tmp_path / _KEEP_DIR_NAME, usable=True, heartbeat_age_seconds=2.0, note="kept copies"
    )

    verify.verify_all(root, channel_ids=("public",), dwell_seconds=0.0, caption_keep=keep)

    assert seen == [keep]


def test_main_resolves_the_default_keep_dir_when_its_heartbeat_is_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The 8 h rung already running must benefit without a restart.

    rung.ps1 loaded its own copy of the script at start, so it passes no
    `--caption-keep-dir`: the CLI has to look in %TEMP%\\cc-caption-keep by
    default, and to fall back cleanly when nothing is there.
    """
    root, _names = _emitted_channel(tmp_path, count=8, seconds=2.0)
    keep_root = tmp_path / _KEEP_DIR_NAME
    _write_keep_heartbeat(keep_root, age=2.0)
    monkeypatch.setattr(verify, "default_caption_keep_dir", lambda: keep_root)
    captured: dict[str, object] = {}

    def spy(hls_root, **kwargs):
        captured.update(kwargs)
        return {"channels": {}, "verdict": verify.Verdict.FAIL}

    monkeypatch.setattr(verify, "verify_all", spy)
    out = tmp_path / "verify.json"

    verify.main(["--hls-root", str(root), "--out", str(out)])

    keep = captured["caption_keep"]
    assert keep.usable is True
    assert keep.heartbeat_age_seconds == 2.0
    assert keep.channel_dir("public") == keep_root / "public"
    # ... and the file the rung reads says so.
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["verdict"] == verify.Verdict.FAIL


def test_main_falls_back_to_the_live_dir_when_the_default_keep_dir_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No keeper running: one line of evidence, no error, today's window."""
    root, _names = _emitted_channel(tmp_path, count=8, seconds=2.0)
    monkeypatch.setattr(verify, "default_caption_keep_dir", lambda: tmp_path / "never-created")
    captured: dict[str, object] = {}

    def spy(hls_root, **kwargs):
        captured.update(kwargs)
        return {"channels": {}, "verdict": verify.Verdict.FAIL}

    monkeypatch.setattr(verify, "verify_all", spy)

    verify.main(["--hls-root", str(root), "--out", str(tmp_path / "verify.json")])

    keep = captured["caption_keep"]
    assert keep.usable is False
    assert keep.root == tmp_path / "never-created"
    assert "never-created" in keep.note


def test_main_honours_an_explicit_caption_keep_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--caption-keep-dir` wins over the default, fresh or not."""
    root, _names = _emitted_channel(tmp_path, count=8, seconds=2.0)
    keep_root = tmp_path / "elsewhere"
    _write_keep_heartbeat(keep_root, age=1.0)
    monkeypatch.setattr(verify, "default_caption_keep_dir", lambda: tmp_path / _KEEP_DIR_NAME)
    captured: dict[str, object] = {}

    def spy(hls_root, **kwargs):
        captured.update(kwargs)
        return {"channels": {}, "verdict": verify.Verdict.FAIL}

    monkeypatch.setattr(verify, "verify_all", spy)

    verify.main(
        [
            "--hls-root",
            str(root),
            "--out",
            str(tmp_path / "verify.json"),
            "--caption-keep-dir",
            str(keep_root),
        ]
    )

    assert captured["caption_keep"].root == keep_root
    assert captured["caption_keep"].usable is True


def test_caption_window_records_span_cues_and_the_worker_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, names = _emitted_channel(tmp_path, count=40, seconds=2.0)
    _write_worker_log(
        root,
        "public",
        [
            "CTRL caption public: received=20 injected=20 replayed=0 rejected=0 in 60s",
            "CTRL caption public: received=18 injected=18 replayed=0 rejected=0 in 60s",
        ],
        age=30.0,
    )

    def fake_decode(path):
        if Path(path).name == names[20]:
            return {
                "status": verify.Verdict.PASS,
                "detail": "ok",
                "decoded_text_present": True,
                "decoded_text_bytes": 5,
                "decoded_text_sha256": "deadbeef",
                "decoded_cue_count": 2,
            }
        return {
            "status": verify.Verdict.FAIL,
            "detail": "no cues",
            "decoded_text_present": False,
            "decoded_text_bytes": 0,
            "decoded_text_sha256": "",
            "decoded_cue_count": 0,
        }

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "_decode_captions", fake_decode)
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    block = result["caption_decode_back"]
    assert block["status"] == verify.Verdict.PASS
    assert block["cue_count"] == 2
    assert block["span_seconds"] == 60.0
    assert "60.0 s" in block["detail"]
    assert "2 cue" in block["detail"]
    # The worker's own receipt rides along, so rung_check can tell a quiet
    # channel from a caption outage without reading the live station itself.
    assert result["caption_receipt"]["status"] == "OK"
    assert result["caption_receipt"]["received"] == 18


def test_caption_window_with_no_finished_segment_is_not_proven(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two segments or fewer: both newest are excluded, nothing is decodable."""
    root, _names = _emitted_channel(tmp_path, count=2, seconds=2.0)

    monkeypatch.setattr(
        verify, "caption_decoder_available", lambda: {"available": True, "detail": "ok"}
    )
    monkeypatch.setattr(
        verify,
        "_decode_captions",
        lambda *a, **k: {"status": verify.Verdict.PASS, "decoded_cue_count": 1},
    )
    _stub_all_av(monkeypatch)

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    assert result["caption_decode_back"]["status"] == verify.Verdict.NOT_PROVEN
    assert result["caption_decode_back"]["per_segment"] == []


# --- The playout worker's caption receipt ---------------------------------
#
# `civiccast/egress/gst/worker.py` prints one line per 60 s window that carried
# caption activity, and one WARNING after ten silent windows. Silence with no
# prior receipt is a channel with captions switched off, so it prints nothing.


def test_caption_receipt_reads_the_newest_line_for_this_channel(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        [
            "CTRL caption public: received=4 injected=4 replayed=0 rejected=0 in 60s",
            "CTRL caption public: received=18 injected=18 replayed=0 rejected=0 in 60s",
        ],
        age=12.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "OK"
    assert receipt["received"] == 18
    assert receipt["window_s"] == 60.0
    assert receipt["age_seconds"] == pytest.approx(12.0)


def test_caption_receipt_ignores_another_channels_lines(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        ["CTRL caption education: received=17 injected=17 replayed=0 rejected=0 in 60s"],
        age=12.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "UNAVAILABLE"


def test_caption_receipt_received_zero_is_zero(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        ["CTRL caption public: received=0 injected=0 replayed=3 rejected=0 in 60s"],
        age=12.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "ZERO"
    assert receipt["received"] == 0


def test_caption_receipt_warning_after_the_last_receipt_is_zero(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        [
            "CTRL caption public: received=18 injected=18 replayed=0 rejected=0 in 60s",
            "CTRL caption public: WARNING no caption command received for 601s since the last "
            "receipt; this channel's emitted stream is carrying no new captions",
        ],
        age=12.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "ZERO"
    assert receipt["silent_seconds"] == 601.0


def test_caption_receipt_warning_before_a_later_receipt_is_not_zero(tmp_path: Path) -> None:
    """The worker's own words: a later receipt retracts an earlier warning."""
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        [
            "CTRL caption public: WARNING no caption command received for 601s since the last "
            "receipt; this channel's emitted stream is carrying no new captions",
            "CTRL caption public: received=9 injected=9 replayed=0 rejected=0 in 60s",
        ],
        age=12.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "OK"
    assert receipt["received"] == 9


def test_caption_receipt_without_a_log_is_unavailable(tmp_path: Path) -> None:
    receipt = verify.caption_receipt("public", tmp_path / "live-hls", now=1_700_000_000.0)

    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["received"] is None


def test_caption_receipt_stale_log_is_unavailable_not_zero(tmp_path: Path) -> None:
    """A dead worker's last line says nothing about the window under judgement."""
    root = tmp_path / "live-hls"
    _write_worker_log(
        root,
        "public",
        [
            "CTRL caption public: received=4 injected=4 replayed=0 rejected=0 in 60s",
            "CTRL caption public: received=0 injected=0 replayed=0 rejected=0 in 60s",
        ],
        age=7200.0,
    )

    receipt = verify.caption_receipt("public", root, now=1_700_000_000.0)

    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["age_seconds"] == pytest.approx(7200.0)


# --- Channel-level fail-closed behavior -----------------------------------


def test_missing_segment_forces_channel_fail(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=927, count=3)
    _touch_segments(channel, names[:2])  # third segment listed but absent

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=_stub_probe_ok,
        ffmpeg=_stub_ffmpeg_ok,
        tsp=_stub_tsp_ok,
        max_segments=3,
        first_playlist=verify.parse_playlist(channel / "playlist.m3u8"),
    )

    assert result["status"] == verify.Verdict.FAIL
    assert names[2] in result["missing_segments"]
    assert result["statuses"].count(verify.Verdict.FAIL) >= 1


def test_absent_playlist_fails_closed(tmp_path: Path) -> None:
    result = verify.verify_channel(
        "public",
        tmp_path,
        ffprobe=None,
        ffmpeg=None,
        tsp=None,
        max_segments=2,
    )

    assert result["status"] == verify.Verdict.FAIL


def test_thresholds_come_from_project_policy() -> None:
    # -16 LUFS +/-1 LU is the spec's OTT-typical target; silence floor is the
    # preparer's policy constant; continuity is zero-tolerance.
    assert verify.OTT_LOUDNESS_TARGET_LUFS == -16.0
    assert verify.OTT_LOUDNESS_TOLERANCE_LUFS == 1.0
    assert verify.SILENCE_FLOOR_LUFS == -60.0
    assert verify.CONTINUITY_TOLERANCE == 0
    assert verify.HLS_TARGET_SEGMENT_SECONDS == 2.0
    assert verify.HLS_PLAYLIST_SIZE == 6


def test_required_channels_are_exactly_the_station_channels() -> None:
    assert verify.REQUIRED_CHANNELS == ("public", "government", "education")


def _fake_tool_versions() -> dict:
    return {
        "ffprobe": {"path": None, "version": None, "ok": False},
        "ffmpeg": {"path": None, "version": None, "ok": False},
        "tsp": {"path": None, "version": None, "ok": False},
        "gstreamer_runtime": {"path": None, "present": False},
    }


def test_subset_channels_cannot_return_release_grade_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-channel run must never be reported as a release-grade PASS."""

    monkeypatch.setattr(verify, "tool_versions", _fake_tool_versions)
    monkeypatch.setattr(
        verify,
        "verify_channel",
        lambda channel_id, *a, **k: {"channel_id": channel_id, "status": verify.Verdict.PASS},
    )

    report = verify.verify_all(tmp_path, channel_ids=("public",), dwell_seconds=0.0)

    assert report["release_grade"] is False
    assert report["verdict"] != verify.Verdict.PASS
    assert report["verdict"] == verify.Verdict.UNVERIFIED
    assert set(report["missing_required_channels"]) == {"government", "education"}
    assert "NON-RELEASE" in report["release_grade_note"]


def test_full_required_set_with_all_pass_is_release_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, "tool_versions", _fake_tool_versions)
    monkeypatch.setattr(
        verify,
        "verify_channel",
        lambda channel_id, *a, **k: {"channel_id": channel_id, "status": verify.Verdict.PASS},
    )

    report = verify.verify_all(tmp_path, dwell_seconds=0.0)

    assert report["release_grade"] is True
    assert report["verdict"] == verify.Verdict.PASS
    assert report["required_channels"] == list(verify.REQUIRED_CHANNELS)


def test_unexpected_channel_is_not_release_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, "tool_versions", _fake_tool_versions)
    monkeypatch.setattr(
        verify,
        "verify_channel",
        lambda channel_id, *a, **k: {"channel_id": channel_id, "status": verify.Verdict.PASS},
    )

    report = verify.verify_all(
        tmp_path, channel_ids=("public", "government", "education", "extra"), dwell_seconds=0.0
    )

    assert report["release_grade"] is False
    assert report["verdict"] != verify.Verdict.PASS
    assert report["unexpected_channels"] == ["extra"]


def test_cli_defaults_to_the_full_required_channel_set() -> None:
    args = verify._parser().parse_args(["--out", "x.json"])

    assert tuple(args.channels) == verify.REQUIRED_CHANNELS


def test_cli_help_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse formats every help string with `%`, so a bare `%TEMP%` in an
    # option's help raises "ValueError: unsupported format character" and --help
    # tracebacks instead of printing. The tool's own instructions name that
    # folder, so the help has to be able to say it.
    with pytest.raises(SystemExit) as excinfo:
        verify.main(["--help"])

    assert excinfo.value.code == 0
    printed = capsys.readouterr().out
    assert "--caption-keep-dir" in printed
    assert "%TEMP%" in printed


def test_cli_accepts_subset_but_marked_non_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify, "tool_versions", _fake_tool_versions)
    monkeypatch.setattr(
        verify,
        "verify_channel",
        lambda channel_id, *a, **k: {"channel_id": channel_id, "status": verify.Verdict.PASS},
    )

    out = tmp_path / "evidence.json"
    exit_code = verify.main(
        ["--hls-root", str(tmp_path), "--channels", "public", "--dwell-seconds", "0", "--out", str(out)]
    )
    report = json.loads(out.read_text(encoding="utf-8"))

    assert exit_code != 0
    assert report["release_grade"] is False
    assert report["verdict"] != verify.Verdict.PASS


def test_verify_all_does_not_claim_the_acceptance_ladder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify,
        "verify_channel",
        lambda channel_id, *a, **k: {"channel_id": channel_id, "status": verify.Verdict.FAIL},
    )
    monkeypatch.setattr(verify, "tool_versions", lambda: {
        "ffprobe": {"path": None, "version": None, "ok": False},
        "ffmpeg": {"path": None, "version": None, "ok": False},
        "tsp": {"path": None, "version": None, "ok": False},
        "gstreamer_runtime": {"path": None, "present": False},
    })

    report = verify.verify_all(tmp_path, dwell_seconds=0.0)

    assert report["ladder_claim"].startswith("NOT_RUN")
    assert report["verdict"] == verify.Verdict.FAIL


# --- Staleness (frozen HLS while API/sidecar would still say ON_AIR) --------


def _fresh_mtimes(channel_dir: Path, names: list[str], base: float) -> dict[str, float]:
    return {name: base + index for index, name in enumerate(names)}


def test_freshness_fails_when_playlist_frozen_and_mtimes_unchanged(tmp_path: Path) -> None:
    channel = tmp_path / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=900, count=3)
    _touch_segments(channel, names)
    first = verify.parse_playlist(channel / "playlist.m3u8")
    first_mtimes = dict.fromkeys(names, 1000.0)

    # Second sample: identical playlist (media-sequence unchanged) and identical mtimes.
    current = verify.parse_playlist(channel / "playlist.m3u8")
    current_mtimes = dict.fromkeys(names, 1000.0)

    freshness = verify.evaluate_freshness(
        first, current, first_mtimes=first_mtimes, current_mtimes=current_mtimes, channel_dir=channel
    )

    assert freshness["status"] == verify.Verdict.FAIL
    assert freshness["advanced"] is False
    assert "stale HLS" in freshness["detail"]


def test_freshness_passes_when_segment_mtime_advances(tmp_path: Path) -> None:
    channel = tmp_path / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=900, count=3)
    _touch_segments(channel, names)
    playlist = verify.parse_playlist(channel / "playlist.m3u8")

    first_mtimes = dict.fromkeys(names, 1000.0)
    current_mtimes = dict.fromkeys(names, 2000.0)

    freshness = verify.evaluate_freshness(
        playlist, playlist, first_mtimes=first_mtimes, current_mtimes=current_mtimes, channel_dir=channel
    )

    assert freshness["status"] == verify.Verdict.PASS
    assert freshness["advanced"] is True


def test_stale_channel_fails_even_with_valid_segments(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    channel = root / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=900, count=3)
    _touch_segments(channel, names)
    first = verify.parse_playlist(channel / "playlist.m3u8")
    # Freeze the on-disk mtimes so BOTH the first and current samples agree;
    # the channel must then fail closed as stale even though every segment
    # listed exists and is a valid-looking file.
    frozen = dict.fromkeys(names, 1000.0)
    for name in names:
        os.utime(channel / name, (1000.0, 1000.0))

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=None,
        ffmpeg=None,
        tsp=None,
        max_segments=3,
        first_playlist=first,
        first_mtimes=frozen,
    )

    assert result["status"] == verify.Verdict.FAIL
    assert result["freshness"]["status"] == verify.Verdict.FAIL

def test_silence_floor_is_the_deciding_signal_when_configured_target_is_loose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silence must fail on its own, independent of the loudness target band.

    A -70 LUFS window is numerically far from -16 LUFS, so a target-band check
    alone would already fail it. To prove the silence floor is load-bearing,
    this test lowers the configured target to -70 LUFS so the value is inside
    the band and ONLY the silence floor can reject it.
    """

    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    silent_stderr = "\nI:         -70.0 LUFS\n  LRA:         0.0 LU\n  Peak:      -91.0 dBFS\n"
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": silent_stderr},
    )
    monkeypatch.setattr(verify, "OTT_LOUDNESS_TARGET_LUFS", -70.0)
    monkeypatch.setattr(verify, "OTT_LOUDNESS_TOLERANCE_LUFS", 1.0)

    result = verify.measure_window_audio(Path("ffmpeg"), [seg], tmp_path / "list.txt")

    assert result["within_target"] is True
    assert result["silent"] is True
    assert result["status"] == verify.Verdict.FAIL


# --- Live-window sliding race: snapshot-before-analyze ---------------------
# Field evidence (2026-09-24 03:14 MDT): the verifier snapshots live segment
# NAMES from playlist.m3u8, then analyzes/decodes those paths SECONDS later --
# by which time ffmpeg's HLS muxer (6x2s window) has deleted them. ffmpeg's
# movie= source then fails ENOENT (exit 4294967294) and caption decode-back
# reads UNVERIFIED with the report's segment files already gone. These tests
# pin the fix: the verifier must COPY needed TS bytes to its own scratch EARLY
# (read-only on the live HLS) and analyze the private copies.


def test_segment_deleted_after_capture_does_not_false_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED: the live window slides DURING analysis (as in the field). The
    verifier must analyze its own early snapshot; if it reads the live path
    after deletion, ffmpeg/probe see ENOENT and the segment is unusable."""
    root, names = _channel_with_segments(tmp_path)
    channel = root / "public"

    calls: list[Path] = []

    def slide_window():
        # Emulate the HLS muxer deleting the live segments mid-run.
        for n in names:
            p = channel / n
            if p.exists():
                p.unlink()

    def probe(_ffprobe, segment):
        calls.append(Path(segment))
        return {
            "status": verify.Verdict.PASS,
            "duration": 2.0,
            "video_start_pts": 90_000,
            "video_codec": "h264",
            "audio_codec": "aac",
        }

    def decode(_ffmpeg, segment):
        calls.append(Path(segment))
        # The window slides the moment analysis begins.
        slide_window()
        return {"status": verify.Verdict.PASS, "detail": "ok"}

    def tsp_analyze(_tsp, segment):
        calls.append(Path(segment))
        return {"status": verify.Verdict.PASS, "detail": "ok"}

    monkeypatch.setattr(verify, "probe_segment", probe)
    monkeypatch.setattr(verify, "decode_segment", decode)
    monkeypatch.setattr(verify, "tsduck_analyze", tsp_analyze)
    monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)
    monkeypatch.setattr(
        verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "caption_decoder_available", lambda: {"available": False, "detail": "n/a"})

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )

    # Every analyzed path must be a PRIVATE verifier snapshot under a
    # civiccast-verify-* scratch dir -- never the live channel path. (The scratch
    # is intentionally cleaned up before verify_channel returns, so we assert the
    # path SHAPE, not post-return existence.)
    assert calls, "verifier did not analyze any segment"
    for p in calls:
        assert p.parent != channel, f"verifier analyzed the live path directly: {p}"
        assert any(part.startswith("civiccast-verify-") for part in p.parts), (
            f"analyzed path was not in a verifier-owned scratch: {p}"
        )
        assert p.name in names
    # With the fix, the window slid but analysis succeeded from snapshots.
    assert result["segments_analyzed"], "no segments analyzed"
    for entry in result["segments_analyzed"]:
        assert entry.get("snapshot") is True, f"segment analyzed without a snapshot: {entry}"


def test_snapshot_hash_matches_live_source_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Positive control: the snapshot preserves source identity (sha256)."""
    root, names = _channel_with_segments(tmp_path)
    channel = root / "public"
    live_hashes = {n: verify._sha256(channel / n) for n in names}

    monkeypatch.setattr(verify, "probe_segment", _stub_probe_ok)
    monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
    monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
    monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)
    monkeypatch.setattr(
        verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "caption_decoder_available", lambda: {"available": False, "detail": "n/a"})

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
    )
    for rec in result["segment_identity"]:
        assert rec.get("snapshot_sha256") == live_hashes[rec["segment"]]

def test_loudness_short_window_is_unverified_not_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An 8s window is NOT release-grade: measured LUFS reported, status
    UNVERIFIED -- never PASS -- while target/tolerance are unchanged."""
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": _LOUDNESS_STDERR_CLEAN},
    )

    result = verify.measure_window_audio(
        Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[8.0]
    )

    assert result["integrated_lufs"] == pytest.approx(-15.7)
    assert result["release_grade_adequate"] is False
    assert result["status"] == verify.Verdict.UNVERIFIED
    assert result["status"] != verify.Verdict.PASS


def test_loudness_long_window_within_target_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A 120s-or-longer window at target IS release-grade PASS (positive control)."""
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": _LOUDNESS_STDERR_CLEAN},
    )

    result = verify.measure_window_audio(
        Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[180.0]
    )

    assert result["release_grade_adequate"] is True
    assert result["status"] == verify.Verdict.PASS


def test_loudness_silent_short_window_still_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Silence is FAIL regardless of window length (never softened to UNVERIFIED)."""
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"\x47" * 100)
    monkeypatch.setattr(
        verify,
        "_run",
        lambda *a, **k: {"ok": True, "returncode": 0, "stdout": "", "stderr": _LOUDNESS_STDERR_SILENT},
    )

    result = verify.measure_window_audio(
        Path("ffmpeg"), [seg], tmp_path / "list.txt", segment_seconds=[8.0]
    )

    assert result["status"] == verify.Verdict.FAIL


def test_snapshot_channels_copies_all_before_analysis(tmp_path: Path) -> None:
    """All channels' selected TS are copied up front into one scratch, so a
    later channel cannot rotate out; identity/hash is preserved per channel."""
    import shutil as _sh

    root = tmp_path / "live-hls"
    names_by_channel: dict[str, list[str]] = {}
    for c in ("public", "government", "education"):
        ch = root / c
        ch.mkdir(parents=True)
        names = _write_playlist(ch / "playlist.m3u8", media_sequence=100, count=3)
        _touch_segments(ch, names)
        names_by_channel[c] = names

    shot = verify.snapshot_channels(root, ("public", "government", "education"), max_segments=3)
    try:
        for c, names in names_by_channel.items():
            recs = shot["channels"][c]["records"]
            assert [r["segment"] for r in recs] == names
            for r in recs:
                assert r.get("snapshot"), f"{c}/{r['segment']} not snapshotted"
                snap = Path(r["snapshot"])
                assert snap.is_file()
                assert verify._sha256(snap) == r["snapshot_sha256"]
                assert snap.name == r["segment"]
    finally:
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_analysis_uses_snapshot_when_live_path_rotates_after_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BLOCKER regression: live files deleted AFTER the upfront snapshot must
    still analyze the immutable copy and NOT be marked missing/fail."""
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=100, count=3)
    _touch_segments(ch, names)

    # Upfront capture (all present) ...
    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    try:
        # ... then the live window slides: delete every original live segment.
        for n in names:
            (ch / n).unlink()

        monkeypatch.setattr(verify, "probe_segment", _stub_probe_ok)
        monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
        monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
        monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)
        monkeypatch.setattr(
            verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
        )
        monkeypatch.setattr(verify, "caption_decoder_available", lambda: {"available": False, "detail": "n/a"})

        result = verify.verify_channel(
            "public",
            root,
            ffprobe=Path("ffprobe"),
            ffmpeg=Path("ffmpeg"),
            tsp=Path("tsp"),
            max_segments=3,
            presnapshot=shot["channels"]["public"],
        )

        # Original identity preserved, and no missing-segment FAIL from rotation.
        assert [r["segment"] for r in result["segment_identity"]] == names
        assert "missing_segments" not in result
        assert all(entry.get("snapshot") for entry in result["segments_analyzed"])
        # (Timestamp continuity is stubbed constant here and may legitimately
        # FAIL; the regression under test is that rotation must not be reported
        # as missing/unusable.)
        for entry in result["segments_analyzed"]:
            assert entry.get("probe", {}).get("detail") != "segment listed but missing on disk"
    finally:
        import shutil as _sh
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_old_rotated_references_outside_chosen_window_do_not_false_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BLOCKER regression (live run 2026-09-24): the playlist can still list 6
    references while we only snapshot/analyze the newest ``max_segments``. The
    oldest references may rotate out of the live window during analysis. Their
    absence must NOT be scored as a media failure; only a missing segment WITHIN
    the chosen newest N (or a missing/copy-raced chosen snapshot) fails closed."""
    import shutil as _sh

    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=2113, count=6)
    _touch_segments(ch, names)

    # Upfront cross-channel capture of only the newest 4 (the analyzed scope).
    shot = verify.snapshot_channels(root, ("public",), max_segments=4)
    try:
        # The two oldest references rotate out of the live window before the
        # per-channel analysis phase runs on this channel.
        for n in names[:2]:
            (ch / n).unlink()

        # Advancing PTS per chosen segment so the ONLY possible FAIL source is
        # the old-reference rotation being scored; continuity is not under test.
        _pts = {n: 90_000 + 180_000 * i for i, n in enumerate(names)}
        monkeypatch.setattr(
            verify,
            "probe_segment",
            lambda _fp, seg: dict(_stub_probe_ok(_fp, seg), video_start_pts=_pts[seg.name]),
        )
        monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
        monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
        monkeypatch.setattr(
            verify, "extract_first_pcr", lambda _tsp, seg: 5_000_000_000 + 200_000 * _pts[seg.name]
        )
        monkeypatch.setattr(
            verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
        )
        monkeypatch.setattr(
            verify,
            "caption_decoder_available",
            lambda: {"available": True, "detail": "stub"},
        )
        monkeypatch.setattr(
            verify,
            "_decode_captions",
            lambda _p: {
                "segment": _p.name,
                "status": verify.Verdict.PASS,
                "decoded_cue_count": 1,
                "decoded_text_present": True,
            },
        )

        result = verify.verify_channel(
            "public",
            root,
            ffprobe=Path("ffprobe"),
            ffmpeg=Path("ffmpeg"),
            tsp=Path("tsp"),
            max_segments=4,
            presnapshot=shot["channels"]["public"],
        )

        # The chosen newest 4 were snapshotted and analyzed.
        assert [e["segment"] for e in result["segments_analyzed"]] == names[-4:]
        assert all(e.get("snapshot") for e in result["segments_analyzed"])
        # Rotation of the two OLD references must not be reported as missing.
        assert "missing_segments" not in result
        # With all chosen segments passing AV/TS, the channel must not FAIL
        # solely because older playlist references rotated out.
        assert result["status"] != verify.Verdict.FAIL
    finally:
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_snapshot_channels_copies_only_newest_max_segments(tmp_path: Path) -> None:
    """BOUNDED SCOPE: only the newest N are copied, not the whole playlist."""
    import shutil as _sh

    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=1, count=10)
    _touch_segments(ch, names)

    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    try:
        recs = shot["channels"]["public"]["records"]
        assert [r["segment"] for r in recs] == names[-3:]
        snap_files = list(shot["scratch"].rglob("*.ts"))
        assert len(snap_files) == 3
    finally:
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_snapshot_channels_rejects_traversal_names(tmp_path: Path) -> None:
    """PATH SAFETY: a playlist entry escaping the channel dir must be rejected."""
    import shutil as _sh

    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    outside = tmp_path / "outside.ts"
    outside.write_bytes(b"\x47" * 64)
    (ch / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1\n"
        "#EXTINF:2.000000,\n../outside.ts\n",
        encoding="utf-8",
    )

    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    try:
        rec = shot["channels"]["public"]["records"][0]
        assert not rec.get("snapshot"), "traversal name must not be snapshotted"
        assert rec.get("snapshot_error") in (
            "unsafe_segment_name_rejected",
            "segment_path_outside_channel_rejected",
        )
    finally:
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_snapshot_channels_rejects_non_ts_name(tmp_path: Path) -> None:
    import shutil as _sh

    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    (ch / "evil.txt").write_bytes(b"x")
    (ch / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1\n"
        "#EXTINF:2.000000,\nevil.txt\n",
        encoding="utf-8",
    )
    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    try:
        rec = shot["channels"]["public"]["records"][0]
        assert rec.get("snapshot_error") == "unsafe_segment_name_rejected"
    finally:
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_snapshot_segment_fails_closed_on_torn_source(tmp_path: Path) -> None:
    """Copy-race BEFORE capture: an unreadable/short source yields no snapshot."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    missing = tmp_path / "nope.ts"
    snap, sha = verify._snapshot_segment(missing, scratch)
    assert snap is None and sha is None



def test_safe_rmtree_refuses_temp_root_and_foreign_prefixed_dir() -> None:
    """BLOCKER regression: ownership is proven, not guessed by name/prefix.

    An unrelated directory that merely has the ``civiccast-verify-`` prefix and
    sits under the OS temp root is NOT owned by this process and must never be
    deleted, even though its name and location look like a scratch dir.
    """
    import shutil as _sh
    import tempfile as _tf

    temp_root = Path(_tf.gettempdir())
    # (a) refusing the temp root itself: it must still exist afterward.
    verify._safe_rmtree(temp_root)
    assert temp_root.is_dir(), "temp root was deleted!"

    # (b) an unrelated, prefixed directory UNDER the OS temp root (not created by
    # _make_scratch_dir) must be refused -> proves prefix+temp is not ownership.
    foreign = Path(_tf.mkdtemp(prefix="civiccast-verify-outside-"))
    (foreign / "x").write_text("x", encoding="utf-8")
    try:
        verify._safe_rmtree(foreign)
        assert foreign.is_dir(), "foreign prefixed temp dir was deleted!"
    finally:
        _sh.rmtree(foreign, ignore_errors=True)

    # (c) a non-prefixed dir under temp is likewise refused.
    other = Path(_tf.mkdtemp(prefix="unrelated-"))
    (other / "x").write_text("x", encoding="utf-8")
    try:
        verify._safe_rmtree(other)
        assert other.is_dir(), "unrelated temp dir was deleted!"
    finally:
        _sh.rmtree(other, ignore_errors=True)


def test_safe_rmtree_deletes_only_registered_owned_scratch() -> None:
    """Positive control: a dir RETURNED by _make_scratch_dir IS deleted."""
    owned = verify._make_scratch_dir()
    (owned / "f").write_text("x", encoding="utf-8")
    assert str(owned.resolve()) in verify._OWNED_SCRATCH
    verify._safe_rmtree(owned)
    assert not owned.exists(), "owned scratch was not deleted"


def test_safe_rmtree_deletes_verifier_owned_temp_dir(tmp_path: Path) -> None:
    owned = verify._make_scratch_dir()
    (owned / "f").write_text("x", encoding="utf-8")
    verify._safe_rmtree(owned)
    assert not owned.exists()


def test_verify_channel_cleans_its_own_scratch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """verify_channel must not leak its scratch, even with a presnapshot given."""

    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=100, count=3)
    _touch_segments(ch, names)
    shot = verify.snapshot_channels(root, ("public",), max_segments=3)

    monkeypatch.setattr(verify, "probe_segment", _stub_probe_ok)
    monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
    monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
    monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)
    monkeypatch.setattr(
        verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "caption_decoder_available", lambda: {"available": False, "detail": "n/a"})

    # Count verifier scratch dirs before/after verify_channel.
    import tempfile as _tf
    base = Path(_tf.gettempdir())
    before = {p.name for p in base.glob("civiccast-verify-*") if p.is_dir()}
    try:
        verify.verify_channel(
            "public",
            root,
            ffprobe=Path("ffprobe"),
            ffmpeg=Path("ffmpeg"),
            tsp=Path("tsp"),
            max_segments=3,
            presnapshot=shot["channels"]["public"],
        )
    finally:
        import shutil as _sh
        _sh.rmtree(shot["scratch"], ignore_errors=True)
    after = {p.name for p in base.glob("civiccast-verify-*") if p.is_dir()}
    leaked = after - before
    assert not leaked, f"verify_channel leaked scratch dir(s): {leaked}"


def test_snapshot_channels_no_records_does_not_orphan_owned_scratch(tmp_path: Path) -> None:
    """An empty/malformed playlist yields no records; the shared scratch is
    still returned for the caller to own+clean (no orphan), and presnapshot-mode
    verify_channel still owns its OWN scratch."""
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    (ch / "playlist.m3u8").write_text("#EXTM3U\n#EXT-X-VERSION:6\n", encoding="utf-8")
    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    try:
        assert shot["channels"]["public"]["records"] == []
        assert shot["scratch"].is_dir()
    finally:
        import shutil as _sh
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_captured_identity_is_authoritative_not_overwritten_by_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A live re-stat (rotated/torn) must NOT overwrite the captured snapshot
    identity; the snapshot sha256 stays the authoritative record."""
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=100, count=3)
    _touch_segments(ch, names)
    shot = verify.snapshot_channels(root, ("public",), max_segments=3)
    captured = {
        r["segment"]: r["snapshot_sha256"]
        for r in shot["channels"]["public"]["records"]
    }
    # Rotate/overwrite the live files with DIFFERENT bytes.
    for n in names:
        (ch / n).write_bytes(b"\x47" * 8)

    monkeypatch.setattr(verify, "probe_segment", _stub_probe_ok)
    monkeypatch.setattr(verify, "decode_segment", _stub_ffmpeg_ok)
    monkeypatch.setattr(verify, "tsduck_analyze", _stub_tsp_ok)
    monkeypatch.setattr(verify, "extract_first_pcr", lambda *a, **k: 5_000_000_000)
    monkeypatch.setattr(
        verify, "measure_window_audio", lambda *a, **k: {"status": verify.Verdict.PASS, "detail": "ok"}
    )
    monkeypatch.setattr(verify, "caption_decoder_available", lambda: {"available": False, "detail": "n/a"})

    result = verify.verify_channel(
        "public",
        root,
        ffprobe=Path("ffprobe"),
        ffmpeg=Path("ffmpeg"),
        tsp=Path("tsp"),
        max_segments=3,
        presnapshot=shot["channels"]["public"],
    )
    try:
        for rec in result["segment_identity"]:
            assert rec["snapshot_sha256"] == captured[rec["segment"]]
            # live bytes were overwritten but must not appear as the identity
            assert rec.get("sha256") in (None, captured[rec["segment"]])
    finally:
        import shutil as _sh
        _sh.rmtree(shot["scratch"], ignore_errors=True)


def test_snapshot_segment_rejects_zero_byte(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    empty = tmp_path / "seg000000001.ts"
    empty.write_bytes(b"")
    snap, sha = verify._snapshot_segment(empty, scratch)
    assert snap is None and sha is None


def test_validate_max_segments_rejects_unbounded_values() -> None:
    """RED/GREEN: 0/negative/huge must raise (never slice to ALL), 1..16 ok."""
    for bad in (0, -1, 17, 10_000, 2**31):
        with pytest.raises(ValueError):
            verify.validate_max_segments(bad)
    for good in (1, 4, verify.MAX_SEGMENTS_UPPER_BOUND):
        assert verify.validate_max_segments(good) == good
    assert verify.MAX_SEGMENTS_UPPER_BOUND == 16


def test_snapshot_channels_rejects_max_segments_zero(tmp_path: Path) -> None:
    """max_segments=0 would be [-0:] == ALL; must fail closed, not copy all."""
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=1, count=10)
    _touch_segments(ch, names)
    with pytest.raises(ValueError):
        verify.snapshot_channels(root, ("public",), max_segments=0)


def test_snapshot_channels_rejects_negative_and_huge(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=1, count=4)
    _touch_segments(ch, names)
    for bad in (-1, 9999):
        with pytest.raises(ValueError):
            verify.snapshot_channels(root, ("public",), max_segments=bad)


def test_verify_channel_rejects_bad_max_segments(tmp_path: Path) -> None:
    root = tmp_path / "live-hls"
    ch = root / "public"
    ch.mkdir(parents=True)
    names = _write_playlist(ch / "playlist.m3u8", media_sequence=1, count=3)
    _touch_segments(ch, names)
    with pytest.raises(ValueError):
        verify.verify_channel(
            "public", root, ffprobe=None, ffmpeg=None, tsp=None, max_segments=0
        )


def test_validate_channel_ids_rejects_traversal() -> None:
    for bad in ("../evil", "..\\evil", "/abs", "a/b", "a\\b", "..", ".", "", " x"):
        with pytest.raises(ValueError):
            verify.validate_channel_ids((bad,))
    # known required names are plain bare names and must be allowed
    assert verify.validate_channel_ids(verify.REQUIRED_CHANNELS) == verify.REQUIRED_CHANNELS


def test_snapshot_channels_rejects_traversal_channel_id(tmp_path: Path) -> None:
    """A traversal channel id must be rejected before any read outside root."""
    root = tmp_path / "live-hls"
    (root / "public").mkdir(parents=True)
    with pytest.raises(ValueError):
        verify.snapshot_channels(root, ("../outside",), max_segments=3)
    with pytest.raises(ValueError):
        verify.snapshot_channels(root, ("public", "../outside"), max_segments=3)


def test_verify_all_rejects_bad_max_segments_and_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "live-hls"
    (root / "public").mkdir(parents=True)
    with pytest.raises(ValueError):
        verify.verify_all(root, channel_ids=("public",), max_segments=0)
    with pytest.raises(ValueError):
        verify.verify_all(root, channel_ids=("../escape",), max_segments=3)


def test_snapshot_segment_fails_closed_on_mid_read_rewrite(tmp_path: Path) -> None:
    """RED: a same-size rewrite DURING the read must be detected (pre/post
    identity differ) and fail closed -- never accepted as a stable snapshot."""
    import os as _os

    src = tmp_path / "seg000000001.ts"
    src.write_bytes(b"\x47" * 4096)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    real_read = _os.read
    state = {"touched": False}

    def rewriting_read(fd, n):
        if not state["touched"]:
            state["touched"] = True
            # Same SIZE, different bytes, and a later mtime -> identity changes.
            with src.open("wb") as fh:
                fh.write(b"\x00" * 4096)
            _os.utime(src, None)
        return real_read(fd, n)

    monkeypatched = False
    try:
        _os.read = rewriting_read  # type: ignore[assignment]
        monkeypatched = True
        snap, sha = verify._snapshot_segment(src, scratch)
    finally:
        if monkeypatched:
            _os.read = real_read  # type: ignore[assignment]

    assert state["touched"], "test setup did not rewrite mid-read"
    assert snap is None and sha is None, "mid-read rewrite was accepted as a snapshot"


def test_make_scratch_dir_never_returns_unregistered_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registration is required: if resolve() fails, no unowned dir is returned."""
    import pathlib as _pl

    real_resolve = _pl.Path.resolve

    def bad_resolve(self, *a, **k):
        raise OSError("simulated resolve failure")

    # Assert NO recursive delete is ever used on the unvalidated just-created dir.
    rmtree_calls: list[str] = []

    def spy_rmtree(path, *a, **k):  # pragma: no cover - must never be called
        rmtree_calls.append(str(path))
        return

    monkeypatch.setattr(verify.shutil, "rmtree", spy_rmtree)
    monkeypatch.setattr(_pl.Path, "resolve", bad_resolve)
    with pytest.raises(RuntimeError):
        verify._make_scratch_dir()
    monkeypatch.setattr(_pl.Path, "resolve", real_resolve)
    assert rmtree_calls == [], f"recursive delete used on unvalidated path: {rmtree_calls}"


def test_make_scratch_dir_resolve_failure_leaves_nonempty_dir_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the just-created dir is UNEXPECTEDLY non-empty, rmdir fails closed and
    the dir (and its contents) are left intact -- no recursive delete."""
    import pathlib as _pl
    import tempfile as _tf

    # A fake mkdtemp returns a NON-EMPTY dir to prove rmdir (not rmtree) is used.
    foreign = tmp_path / "civiccast-verify-nonempty"
    foreign.mkdir()
    (foreign / "keep").write_text("x", encoding="utf-8")
    monkeypatch.setattr(_tf, "mkdtemp", lambda *a, **k: str(foreign))

    real_resolve = _pl.Path.resolve

    def bad_resolve(self, *a, **k):
        raise OSError("simulated resolve failure")

    rmtree_calls: list[str] = []
    monkeypatch.setattr(verify.shutil, "rmtree", lambda p, *a, **k: rmtree_calls.append(str(p)))
    monkeypatch.setattr(_pl.Path, "resolve", bad_resolve)
    with pytest.raises(RuntimeError):
        verify._make_scratch_dir()
    monkeypatch.setattr(_pl.Path, "resolve", real_resolve)

    assert rmtree_calls == [], "recursive delete used"
    assert (foreign / "keep").is_file(), "unexpectedly non-empty dir was not preserved"


# --- U48: a live read that races the relay's atomic replace ----------------


@pytest.fixture(autouse=True)
def _never_pay_the_race_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the shipped retry budget out of this file's wall clock.

    Several fixtures in this file intentionally reference a playlist or segment
    that does not exist, and the shipped budget (20 x 100 ms) would charge each
    of them about two seconds.  The budget itself is pinned by
    ``test_parse_playlist_gives_up_after_the_retry_budget`` -- exact constants
    and recorded delays -- so no contract is left unproven by not sleeping
    here.  A test that needs the recorded delays re-stubs ``verify.time``
    through ``_no_sleeps``.

    The module clock is frozen at ``_FIXTURE_EPOCH`` too: the fixtures write
    their ages against that instant, so a reader that asks the module what time
    it is must get the same answer the fixture did.
    """

    monkeypatch.setattr(
        verify, "time", SimpleNamespace(sleep=lambda _seconds: None, time=lambda: _FIXTURE_EPOCH)
    )


def _no_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Stub the module's ``time`` so a retry budget costs no wall clock.

    Returns the recorded delays so a test can assert the spacing as well as the
    attempt count.  Only this module's ``time`` attribute is replaced, and its
    clock is frozen at ``_FIXTURE_EPOCH`` for the same reason as above.
    """

    slept: list[float] = []
    monkeypatch.setattr(
        verify, "time", SimpleNamespace(sleep=slept.append, time=lambda: _FIXTURE_EPOCH)
    )
    return slept


def _racing_open(monkeypatch: pytest.MonkeyPatch, target: Path, failures: int) -> dict[str, int]:
    """Make the first ``failures`` opens of ``target`` raise EACCES, then work."""

    real_open = Path.open
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        if self == target and calls["n"] < failures:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky)
    return calls


def test_parse_playlist_read_survives_a_racing_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three EACCES reads in a row are a race, not a verdict: the read wins."""

    slept = _no_sleeps(monkeypatch)
    pl = tmp_path / "playlist.m3u8"
    names = _write_playlist(pl, media_sequence=927, count=3)
    calls = _racing_open(monkeypatch, pl, 3)

    parsed = verify.parse_playlist(pl)

    assert calls["n"] == 3, "the raced read was not retried"
    assert parsed.parse_error is None
    assert parsed.segments == names
    assert parsed.media_sequence == 927
    assert slept == [verify.RACE_RETRY_DELAY_SECONDS] * 3


def test_parse_playlist_gives_up_after_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that never succeeds still fails closed, as before, after the budget."""

    slept = _no_sleeps(monkeypatch)
    pl = tmp_path / "playlist.m3u8"
    _write_playlist(pl, media_sequence=927, count=3)
    calls = _racing_open(monkeypatch, pl, 25)

    parsed = verify.parse_playlist(pl)

    assert verify.RACE_RETRY_ATTEMPTS == 20
    assert verify.RACE_RETRY_DELAY_SECONDS == 0.1
    assert calls["n"] == verify.RACE_RETRY_ATTEMPTS
    assert len(slept) == verify.RACE_RETRY_ATTEMPTS - 1
    assert set(slept) == {0.1}
    assert parsed.parse_error is not None
    assert "Permission denied" in parsed.parse_error
    assert parsed.segments == []


def test_absent_playlist_still_reports_missing_after_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely absent playlist keeps today's word -- and pays the budget once."""

    slept = _no_sleeps(monkeypatch)

    parsed = verify.parse_playlist(tmp_path / "absent.m3u8")

    assert parsed.parse_error == "playlist missing"
    assert parsed.segments == []
    assert len(slept) == verify.RACE_RETRY_ATTEMPTS - 1


def _racing_fd_open(failures: int, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Make the first ``failures`` read-only opens raise EACCES, then work."""

    real = verify._open_live_fd
    calls = {"n": 0}

    def flaky(src):
        if calls["n"] < failures:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied", str(src))
        return real(src)

    monkeypatch.setattr(verify, "_open_live_fd", flaky)
    return calls


def test_snapshot_segment_read_survives_a_racing_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EACCES on the open is the relay's replace racing us, not a station fault."""

    slept = _no_sleeps(monkeypatch)
    channel = tmp_path / "live" / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=927, count=3)
    _touch_segments(channel, names)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    calls = _racing_fd_open(3, monkeypatch)

    path, digest = verify._snapshot_segment(channel / names[0], scratch)

    assert calls["n"] == 3, "the raced segment read was not retried"
    assert path is not None
    assert path.read_bytes() == b"\x47" * 1024
    assert digest == hashlib.sha256(b"\x47" * 1024).hexdigest()
    assert slept == [verify.RACE_RETRY_DELAY_SECONDS] * 3


def test_snapshot_segment_gives_up_after_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A segment read that never succeeds is still fail-closed, as before."""

    _no_sleeps(monkeypatch)
    channel = tmp_path / "live" / "public"
    channel.mkdir(parents=True)
    names = _write_playlist(channel / "playlist.m3u8", media_sequence=927, count=3)
    _touch_segments(channel, names)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    calls = _racing_fd_open(25, monkeypatch)

    path, digest = verify._snapshot_segment(channel / names[0], scratch)

    assert calls["n"] == verify.RACE_RETRY_ATTEMPTS
    assert path is None
    assert digest is None
    assert not (scratch / names[0]).exists()
