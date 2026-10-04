# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U55: the no-speech classifier in rung_check.py's caption gate.

The rung's caption decode-back can only report what reached the EMITTED video.
When the source carries no speech -- public airs a title card between two
meetings -- the ASR produces no cue, the worker's receipt goes stale (it prints
its CTRL caption line only when something arrives), and a full 60 s window of
30 segments legitimately decodes to 0 cues.  That evidence is indistinguishable,
by the emitted segments alone, from a station whose caption chain is broken.

These tests drive the real tool as a SUBPROCESS (the tool is a script whose
dispatch is module-level code, and the printed line is the contract the rung
reads).  Every fixture is synthetic, built under tmp_path, and the tool is
pointed at it with CIVICAST_CAPTION_TAP_DIR -- nothing here reads the live
station.

The three cases, in the order the U55 brief names them:

* a real ASR gap that SPANS the window            -> excused, listed, still OK
* the ASR emitted cues INSIDE the window, none
  reached the video                               -> a real FAIL, stays BAD
* the verify-06 shape (2 s window, fresh receipt) -> byte-identical to today

Every excusal test is paired with a fail-closed control, so a classifier that
stops being able to refuse is visible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

#: The tool under test.  `RUNG_CHECK_UNDER_TEST` exists so a run can point at a
#: copy of `rung_check.py` doctored back to an earlier lookup -- that is how the
#: tap-race test below is shown RED against the single-shot version it replaced.
#: Left unset, the sibling tool is what runs.
_TOOL = Path(
    os.environ.get("RUNG_CHECK_UNDER_TEST") or Path(__file__).resolve().with_name("rung_check.py")
)
_CHANNEL = "public"

#: A frozen clock.  The tap anchor is `chunk mtime - (index + 1) * duration`, so
#: a fixed anchor plus the REAL counter values from the 2026-09-26 gap makes
#: these fixtures a faithful replay without depending on the station's clock.
_ANCHOR = 1_800_000_000.0
_INDEX = 100
_DURATION = 5.0

#: Cut from the real C:\ProgramData\CivicCast\data\egress\public\captions\active.vtt
#: (2026-09-26): the adjournment cue ends, the next meeting's first cue starts.
#: Their counter values are 455899.800 and 456193.850 -- a 294.05 s gap.
_CUE_ADJOURNED = "126:38:15.180 --> 126:38:19.800"
_CUE_ADJOURNED_TEXT = "to adjourn is a seconded. All those in favor? Okay, we are adjourned."
_CUE_RESUMED = "126:43:13.850 --> 126:43:14.960"
_CUE_RESUMED_TEXT = "Good evening, I'd"
_GAP_START, _GAP_END = 455899.800, 456193.850

#: The real verify-07 window in counter space (60 s span, 58 s of wall clock).
_WIN_LO, _WIN_HI = 456027.700, 456085.700


def _clock(counter: float) -> str:
    """The local wall clock a tap counter maps to under the frozen anchor."""

    return f"{datetime.fromtimestamp(_ANCHOR + counter):%H:%M:%S}"


def _iso(counter: float) -> str:
    return datetime.fromtimestamp(_ANCHOR + counter, tz=UTC).isoformat()


def _write_chunk(tap_dir: Path, *, index: int = _INDEX, duration: float = _DURATION) -> Path:
    """One tap chunk shaped like the station's: mono 16 kHz s16le, 160044 bytes."""

    tap_dir.mkdir(parents=True, exist_ok=True)
    path = tap_dir / f"chunk-{index:06d}.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\x00\x00" * int(16_000 * duration))
    stamp = _ANCHOR + (index + 1) * duration
    os.utime(path, (stamp, stamp))
    return path


def _write_vtt(captions_dir: Path, cues: list[tuple[str, str]]) -> Path:
    captions_dir.mkdir(parents=True, exist_ok=True)
    path = captions_dir / "active.vtt"
    body = ["WEBVTT", ""]
    for stamp, text in cues:
        body += [f"cue-{len(body):06d}", stamp, text, ""]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _zero_cue_block(status: str = "FAIL", span: float = 60.0) -> dict:
    return {"status": status, "cue_count": 0, "span_seconds": span}


def _channels(public_caption: dict, receipt: dict, window: dict) -> dict:
    """A verify shaped like the rung's: three channels, every gate answered."""

    def block(**over: object) -> dict:
        got = {
            "caption_decode_back": {"status": "PASS", "cue_count": 8, "span_seconds": 60.0},
            "caption_receipt": receipt,
            "caption_window": window,
            "timestamp_continuity": {"status": "PASS"},
            "freshness": {"status": "PASS"},
        }
        got.update(over)
        return got

    return {
        _CHANNEL: block(caption_decode_back=public_caption),
        "government": block(),
        "education": block(),
    }


def _write_verify(path: Path, channels: dict) -> Path:
    path.write_text(json.dumps({"channels": channels}), encoding="utf-8")
    return path


def _tree(
    tmp_path: Path,
    *,
    cues: list[tuple[str, str]],
    window: dict,
    receipt: dict,
    cues_in_block: object = 0,
) -> Path:
    """A synthetic station: one tap chunk, one active.vtt, one verify to judge."""

    egress = tmp_path / "data" / "egress"
    _write_chunk(tmp_path / "data" / "caption-tap" / _CHANNEL)
    _write_vtt(egress / _CHANNEL / "captions", cues)
    (egress / _CHANNEL / "logs").mkdir(parents=True, exist_ok=True)

    # The predecessor carries 0 cues, which is what makes the subject verify's
    # own 0-cue decode a REAL outage today (two consecutive zero-cue verifies).
    _write_verify(
        tmp_path / "verify-06.json",
        _channels(_zero_cue_block(), receipt, window),
    )
    return _write_verify(
        tmp_path / "verify-07.json",
        _channels(
            {"status": "FAIL", "cue_count": cues_in_block, "span_seconds": 60.0},
            receipt,
            window,
        ),
    )


def _receipt(**over: object) -> dict:
    got = {
        "status": "OK",
        "age_seconds": 178.934,
        "received": 18,
        "detail": "the worker reported received=18 in 60s, 178.934s ago",
        "line": "CTRL caption public: received=18 injected=18 replayed=0 rejected=0 in 60s",
    }
    got.update(over)
    # The egress root is derived from this path, so the fixture must own it.
    got.setdefault("log", "")
    return got


def _run(verify_path: Path, tmp_path: Path, *, log_path: Path) -> str:
    env = dict(os.environ)
    env["CIVICAST_CAPTION_TAP_DIR"] = str(tmp_path / "data" / "caption-tap")
    # Current Python + operator-selected test tool; all evidence/tap paths are owned fixtures.
    got = subprocess.run(  # noqa: S603
        [sys.executable, str(_TOOL), "verify", str(verify_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert got.returncode == 0, got.stderr
    return got.stdout.strip()


def _gap_window() -> dict:
    return {
        "emitted_first_utc": _iso(_WIN_LO),
        "emitted_last_utc": _iso(_WIN_HI),
        "span_seconds": 60.0,
    }


def _fixture(tmp_path: Path, **over: object) -> tuple[Path, Path]:
    log = tmp_path / "data" / "egress" / _CHANNEL / "logs" / "gst-worker.stdout.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    receipt = _receipt(log=str(log))
    receipt.update(over.pop("receipt", {}))
    path = _tree(tmp_path, receipt=receipt, **over)  # type: ignore[arg-type]
    return path, log


def test_real_asr_gap_is_excused_not_passed(tmp_path: Path) -> None:
    """No ASR cue across the window and a bounded gap that spans it: excused."""

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
        window=_gap_window(),
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("OK "), line
    assert "NO_SPEECH_SOURCE" in line, line
    assert f"asr gap {_clock(_GAP_START)}-{_clock(_GAP_END)}, 294s" in line, line
    assert _CHANNEL + ":caption_decode_back" not in line, line


def test_asr_cues_inside_the_window_stay_a_real_fail(tmp_path: Path) -> None:
    """The ASR spoke inside the window and none of it reached the video: BAD."""

    inside = "126:40:40.000 --> 126:40:42.000"
    path, log = _fixture(
        tmp_path,
        cues=[
            (_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT),
            (inside, "and that concludes the public hearing."),
            (_CUE_RESUMED, _CUE_RESUMED_TEXT),
        ],
        window=_gap_window(),
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert f"{_CHANNEL}:caption_decode_back=FAIL" in line, line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_verify06_shape_is_unchanged(tmp_path: Path) -> None:
    """A 2 s window on a fresh receipt keeps today's CAPTION_QUIET line, exactly."""

    egress = tmp_path / "data" / "egress"
    # A predecessor WITH cues, as verify-05 had 8: that is what makes the 2 s
    # zero-cue window quietly excusable under the existing rule.
    _write_chunk(tmp_path / "data" / "caption-tap" / _CHANNEL)
    _write_vtt(
        egress / _CHANNEL / "captions",
        [(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
    )
    (egress / _CHANNEL / "logs").mkdir(parents=True, exist_ok=True)
    log = egress / _CHANNEL / "logs" / "gst-worker.stdout.log"
    log.write_text("", encoding="utf-8")
    span = {
        "emitted_first_utc": _iso(455446.1),
        "emitted_last_utc": _iso(455446.1),
        "span_seconds": 2.0,
    }
    receipt = _receipt(
        age_seconds=20.974,
        received=12,
        log=str(log),
        detail="the worker reported received=12 in 60s, 20.974s ago",
    )
    # A predecessor WITH 8 cues, as verify-05 had: that is what makes the 2 s
    # zero-cue window quietly excusable under the existing rule.
    _write_verify(
        tmp_path / "verify-05.json",
        _channels({"status": "PASS", "cue_count": 8, "span_seconds": 2.0}, receipt, span),
    )
    _write_verify(
        tmp_path / "verify-06.json",
        _channels(_zero_cue_block(span=2.0), receipt, span),
    )
    line = _run(tmp_path / "verify-06.json", tmp_path, log_path=log)
    assert line == (
        "OK public:CAPTION_QUIET(FAIL over 2s, 0 cue(s); "
        "the worker reported received=12 in 60s, 20.974s ago)"
    ), line


def test_worker_zero_receipt_is_never_excused(tmp_path: Path) -> None:
    """The station's own received=0 is a positive outage sign; no silence excuses it."""

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
        window=_gap_window(),
        receipt={
            "status": "ZERO",
            "age_seconds": None,
            "received": 0,
            "detail": "the worker reported received=0 for the window",
        },
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_fresh_positive_receipt_is_never_excused(tmp_path: Path) -> None:
    """A fresh receipt says captions WERE injected: silence is not the source's."""

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
        window=_gap_window(),
        receipt={"age_seconds": 20.974, "received": 12},
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_a_gap_that_does_not_cover_the_window_stays_a_fail(tmp_path: Path) -> None:
    """A gap whose margins are thinner than the anchor's slack: fail closed."""

    # ASR silent only from counter 456030 to 456060 -- 9 s either side of the
    # window, well inside ANCHOR_SLACK_SECONDS.
    path, log = _fixture(
        tmp_path,
        cues=[
            ("126:40:25.000 --> 126:40:30.000", "we are adjourned."),
            ("126:41:00.000 --> 126:41:05.000", "Good evening."),
        ],
        window=_gap_window(),
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_missing_tap_evidence_is_never_excused(tmp_path: Path) -> None:
    """No anchor means no mapping, which is not evidence of a quiet source."""

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
        window=_gap_window(),
    )
    for chunk in (tmp_path / "data" / "caption-tap" / _CHANNEL).glob("chunk-*.wav"):
        chunk.unlink()
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_an_asr_that_never_resumed_stays_a_fail(tmp_path: Path) -> None:
    """A cue-free window with no cue AFTER it is a dead ASR, not a quiet room.

    The two are indistinguishable from the ASR's output alone -- which is
    exactly why the gap has to be BOUNDED on both sides before a silence can be
    blamed on the source.  No cue after the window means the ASR never resumed.
    """

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT)],
        window=_gap_window(),
    )
    line = _run(path, tmp_path, log_path=log)
    assert line.startswith("BAD "), line
    assert "NO_SPEECH_SOURCE" not in line, line


def test_a_tap_dir_that_is_empty_at_first_read_is_still_excused(tmp_path: Path) -> None:
    """A live dir caught between segments must not be read as a missing tap.

    OBSERVED on the stations's own tap on 2026-09-26: the channel directory holds
    no `chunk-*.wav` at all for stretches of its 5 s cycle (22:51:12-13, between
    chunk-091403 being moved to `processed/` and chunk-091404 being published),
    and a chunk the glob just listed can be gone by the time it is opened
    (FileNotFoundError at 22:53).  A single-shot lookup fails closed on both -- a
    false caption FAIL on a genuinely quiet source, which is what U55 exists to
    remove.  So this fixture publishes its chunk AFTER the tool has started.
    """

    path, log = _fixture(
        tmp_path,
        cues=[(_CUE_ADJOURNED, _CUE_ADJOURNED_TEXT), (_CUE_RESUMED, _CUE_RESUMED_TEXT)],
        window=_gap_window(),
    )
    tap_dir = tmp_path / "data" / "caption-tap" / _CHANNEL
    for chunk in tap_dir.glob("chunk-*.wav"):
        chunk.unlink()
    latecomer = threading.Timer(1.0, _write_chunk, (tap_dir,))
    latecomer.start()
    try:
        line = _run(path, tmp_path, log_path=log)
    finally:
        latecomer.join()
    assert line.startswith("OK "), line
    assert "NO_SPEECH_SOURCE" in line, line


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
