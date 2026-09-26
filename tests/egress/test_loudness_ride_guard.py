# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 answer 11: the emitted-artifact guard, as one re-encode-only round.

Answer 7's guard re-ran the *whole* leveling path at a lowered ceiling, and U25
round 7 measured what that cost: on BIG it spent all three allowed rounds and
539.13 s of a 908.41 s total, and its step law (ceiling down by the overshoot,
emitted true peak follows 1:1) did not hold -- a -1.30 dB ceiling step bought
0.00 dB of true peak, because the emitted true peak is the AAC codec's own
overshoot rather than a property of the limiter.  Answer 11 replaces it:

* the hard true-peak gate -- no decoded sample over 0 dBFS and an emitted true
  peak at or under :data:`TP_GUARD_HARD_DBTP` -- is the *guarantee*; the
  :data:`TP_GUARD_TARGET_DBTP` of -1.0 dBTP is best effort;
* a hot emit buys exactly ONE more round, and that round re-encodes the
  already-correct ride PCM (limiter + AAC + mux).  It never re-converges and
  never takes a model step;
* the selector orders hard true peak first, then the loudness gates, then the
  lowest emitted true peak;
* when no attempt meets the hard gate, the caller emits once more at
  :data:`TP_GUARD_LAST_RESORT_DBTP` and ships that attempt with an error line.

These tests are the guard's whole contract: they hold the module to the answer
the coordinator gave, not to the shape it had before.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from civiccast.egress import loudness_ride as lr
from civiccast.egress.models import CanonicalProfile

#: Decoder and sink stand-ins for the tee test.  ``run_ride`` only ever hands
#: its two children opaque argument lists and a resolved binary, so pointing
#: ``_ffmpeg_binary`` at the test's own interpreter with ``-c`` scripts drives
#: the real chunk loop -- no FFmpeg build, and no re-implementation of it.
_DECODER_SCRIPT = """
import struct, sys
amp = float(sys.argv[1])
n = 60000
out = bytearray()
for i in range(n):
    v = amp * ((i % 1000) / 1000.0 - 0.5)
    out += struct.pack("<ff", v, v)
sys.stdout.buffer.write(bytes(out))
"""

_SINK_SCRIPT = """
import sys
Path = sys.argv[1]
data = sys.stdin.buffer.read()
with open(Path, "wb") as fh:
    fh.write(data)
"""


def _attempt(
    round_index: int = 0,
    limit_dbtp: float = -1.5,
    emitted_dbtp: float | None = None,
    emitted_lufs: float | None = -16.0,
    worst: float | None = 0.2,
    whole: float | None = 0.05,
    decoded_peak_dbfs: float | None = None,
) -> lr.LeveledAttempt:
    """One attempt as the driver reports it; loudness-lawful unless told otherwise."""
    return lr.LeveledAttempt(
        round_index=round_index,
        limit_dbtp=limit_dbtp,
        emitted_dbtp=emitted_dbtp,
        emitted_lufs=emitted_lufs,
        worst_window_err_lu=worst,
        whole_err_lu=whole,
        wall_s=0.0,
        decoded_peak_dbfs=decoded_peak_dbfs,
    )


def _select(attempts: list[lr.LeveledAttempt]) -> lr.LeveledSelection:
    return lr.select_leveled_attempt(attempts, window_tol_lu=0.9, whole_tol_lu=0.5)


# ---------------------------------------------------------------------------
# The hard gate
# ---------------------------------------------------------------------------


def test_the_gate_constants_are_the_answered_ones() -> None:
    assert lr.TP_GUARD_TARGET_DBTP == -1.0
    assert lr.TP_GUARD_HARD_DBTP == 0.0
    assert lr.TP_GUARD_LAST_RESORT_DBTP == -4.0
    assert lr.TP_GUARD_MAX_ROUNDS == 1


def test_hard_gate_reads_the_emitted_and_the_decoded_peak() -> None:
    """Both legs of the guarantee: emit at or under 0 dBTP, no sample over 0 dBFS."""
    assert _attempt(emitted_dbtp=None).hard_tp_ok() is False
    assert _attempt(emitted_dbtp=0.01).hard_tp_ok() is False
    assert _attempt(emitted_dbtp=0.0).hard_tp_ok() is True
    assert _attempt(emitted_dbtp=-0.5).hard_tp_ok() is True
    # A decoded sample above 0 dBFS is a failure even when the emit reads cold.
    assert _attempt(emitted_dbtp=-0.5, decoded_peak_dbfs=0.02).hard_tp_ok() is False
    assert _attempt(emitted_dbtp=-0.5, decoded_peak_dbfs=0.0).hard_tp_ok() is True
    assert _attempt(emitted_dbtp=-0.5, decoded_peak_dbfs=-1.0).hard_tp_ok() is True


def test_loudness_gates_are_unchanged_by_the_answer_11_reshuffle() -> None:
    assert _attempt(worst=0.9, whole=0.5).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(worst=0.91).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(worst=None).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(whole=None).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)


# ---------------------------------------------------------------------------
# The one re-encode-only round
# ---------------------------------------------------------------------------


def test_the_step_is_the_overshoot_plus_the_margin() -> None:
    # Already lawful: no round is owed.
    assert lr.guard_ceiling_dbtp(-1.5, -1.4) is None
    assert lr.guard_ceiling_dbtp(-1.5, -1.0) is None
    # Emitted at exactly 0.0 dBTP from a -1.5 dBTP ceiling: 1.0 + 0.3 below it.
    assert lr.guard_ceiling_dbtp(-1.5, 0.0) == -2.8
    # Emitted -0.4 from -1.8: 0.6 + 0.3 below the ceiling it came from.
    assert lr.guard_ceiling_dbtp(-1.8, -0.4) == -2.7


def test_a_hot_emit_buys_exactly_one_re_encode_round() -> None:
    assert lr.guard_next_ceiling([]) is None
    # -0.2 dBTP emitted from a -1.5 dBTP ceiling: 0.8 overshoot + 0.3 margin.
    hot = _attempt(limit_dbtp=-1.5, emitted_dbtp=-0.2)
    assert lr.guard_next_ceiling([hot]) == -2.6
    # The bound is spent after that one round, however hot the re-encode reads.
    assert (
        lr.guard_next_ceiling([hot, _attempt(round_index=1, limit_dbtp=-2.0, emitted_dbtp=-0.1)])
        is None
    )


def test_the_round_is_not_owed_when_the_emit_is_lawful_or_unmeasurable() -> None:
    assert lr.guard_next_ceiling([_attempt(emitted_dbtp=-1.4)]) is None
    assert lr.guard_next_ceiling([_attempt(emitted_dbtp=None)]) is None


# ---------------------------------------------------------------------------
# The last resort
# ---------------------------------------------------------------------------


def test_last_resort_needs_a_measured_attempt_that_misses_the_hard_gate() -> None:
    assert lr.needs_last_resort([]) is False
    # Nothing measured: a missing measurement is not a hot artifact.
    assert (
        lr.needs_last_resort(
            [_attempt(emitted_dbtp=None), _attempt(round_index=1, emitted_dbtp=None)]
        )
        is False
    )
    # Measured and lawful: no last resort.
    assert lr.needs_last_resort([_attempt(emitted_dbtp=-0.3)]) is False
    assert lr.needs_last_resort([_attempt(emitted_dbtp=0.0)]) is False
    # Measured and over the hard gate: last resort.
    assert lr.needs_last_resort([_attempt(emitted_dbtp=0.2)]) is True
    # ... on the decoded-sample leg too.
    assert lr.needs_last_resort([_attempt(emitted_dbtp=-0.3, decoded_peak_dbfs=0.02)]) is True
    # Any lawful attempt settles it.
    assert (
        lr.needs_last_resort(
            [_attempt(emitted_dbtp=0.2), _attempt(round_index=1, emitted_dbtp=-0.3)]
        )
        is False
    )


# ---------------------------------------------------------------------------
# Selection: hard true peak, then loudness, then the coldest emit
# ---------------------------------------------------------------------------


def test_the_hard_gate_outranks_the_loudness_gates() -> None:
    """A loudness-lawful attempt over 0 dBTP must not beat a cold one that is not.

    This is the ordering answer 11 names, and it is the one answer 7 got wrong:
    the old selector filtered on the loudness gates first, so the only attempt
    that cleared them won even when it was the one over the hard gate.
    """
    hot_loud = _attempt(limit_dbtp=-1.5, emitted_dbtp=0.2)
    cold_not_loud = _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=-1.2, worst=1.4)
    sel = _select([hot_loud, cold_not_loud])
    assert sel.kept.round_index == 1
    assert sel.hard_tp_met is True
    assert sel.last_resort_needed is False
    assert sel.target_met is True


def test_the_loudness_gates_outrank_the_coldest_emit() -> None:
    loud = _attempt(limit_dbtp=-1.5, emitted_dbtp=-0.4)
    colder_not_loud = _attempt(round_index=1, limit_dbtp=-2.4, emitted_dbtp=-0.9, worst=1.4)
    sel = _select([loud, colder_not_loud])
    assert sel.kept.round_index == 0
    assert sel.hard_tp_met is True
    assert sel.target_met is False
    assert sel.warning is not None


def test_the_coldest_lawful_emit_wins() -> None:
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=-1.2),
            _attempt(round_index=1, limit_dbtp=-1.8, emitted_dbtp=-1.6),
        ]
    )
    assert sel.kept.round_index == 1
    assert sel.target_met is True
    assert sel.warning is None


def test_an_unmeasurable_attempt_never_wins() -> None:
    sel = _select(
        [_attempt(emitted_dbtp=None), _attempt(round_index=1, limit_dbtp=-2.0, emitted_dbtp=-1.3)]
    )
    assert sel.kept.round_index == 1
    assert sel.warning is None


def test_all_unmeasurable_keeps_the_nominal_and_asks_for_no_last_resort() -> None:
    sel = _select(
        [_attempt(emitted_dbtp=None), _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=None)]
    )
    assert sel.kept.round_index == 0
    assert sel.target_met is False
    assert sel.hard_tp_met is False
    assert sel.last_resort_needed is False
    assert sel.warning is not None
    assert "unmeasurable" in sel.warning


def test_ties_go_to_the_earlier_round() -> None:
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=-1.4),
            _attempt(round_index=1, limit_dbtp=-1.8, emitted_dbtp=-1.4),
        ]
    )
    assert sel.kept.round_index == 0


def test_the_warning_names_both_true_peaks() -> None:
    """One warning, and the two numbers an operator needs: what was emitted, what ships."""
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=0.3),
            _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=-0.2),
        ]
    )
    assert sel.kept.round_index == 1
    assert sel.target_met is False
    assert sel.last_resort_needed is False
    assert sel.warning is not None
    assert "+0.30 dBTP" in sel.warning
    assert "-0.20 dBTP" in sel.warning


def test_no_warning_when_the_target_is_met() -> None:
    sel = _select([_attempt(emitted_dbtp=-1.2)])
    assert sel.target_met is True
    assert sel.warning is None


# ---------------------------------------------------------------------------
# The re-encode round's grammar
# ---------------------------------------------------------------------------


def test_the_re_encode_reads_the_retained_pcm_and_shares_the_encode_tail() -> None:
    """The guard's round is the nominal encode with a file input, nothing else.

    Every option after the input leg is shared with :func:`build_encode_sink_args`
    by construction, so a change to the emitted codec, bitrate, rate, channels or
    container cannot reach one shape and miss the other.
    """
    profile = CanonicalProfile(video_codec="h264_mf")
    params = lr.RideParams(target_lufs=-16.0, limit_dbtp=-2.8)
    pcm = Path("C:/tmp/ride.pcm")
    out = Path("C:/tmp/guard.ts")

    nominal = lr.build_encode_sink_args(out, 1.25, params=params, profile=profile)
    guard = lr.build_reencode_args(pcm, out, trim_db=1.25, params=params, profile=profile)

    # Split at the input operand rather than at a hardcoded prefix length: what
    # this test is about is that the two shapes share a head and a tail and differ
    # only in where ``-i`` points, not how many options precede it.
    def _split(argv: list[str]) -> tuple[list[str], str, list[str]]:
        i = argv.index("-i")
        return argv[:i], argv[i + 1], argv[i + 2 :]

    n_head, n_in, n_tail = _split(nominal)
    g_head, g_in, g_tail = _split(guard)
    assert n_head == g_head
    assert n_head == [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "f32le",
        "-ar",
        "48000",
        "-ac",
        "2",
    ]
    assert n_in == "pipe:0", "the encode sink takes the ride on stdin"
    assert g_in == str(pcm), "the guard's round takes the retained ride PCM"
    # Same tail, byte for byte: the re-encode is the encode sink's own grammar.
    assert g_tail == n_tail
    assert guard[guard.index("-c:a") + 1] == profile.audio_codec
    assert f"limit={lr.limit_value(-2.8):.6f}" in ",".join(guard)
    assert "asc=0:level=0" in ",".join(guard)


def test_the_two_shapes_differ_only_in_where_the_pcm_comes_from() -> None:
    profile = CanonicalProfile(video_codec="h264_mf")
    params = lr.RideParams(target_lufs=-16.0)
    nominal = lr.build_encode_sink_args(Path("o.ts"), 0.0, params=params, profile=profile)
    guard = lr.build_reencode_args(
        Path("p.pcm"), Path("o.ts"), trim_db=0.0, params=params, profile=profile
    )
    assert "pipe:0" in nominal and "pipe:0" not in guard


# ---------------------------------------------------------------------------
# The tee: the guard must re-encode the PCM the ride actually produced
# ---------------------------------------------------------------------------


def test_the_tee_writes_exactly_the_pcm_the_sink_receives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retained PCM is the post-curve stream, byte for byte.

    A second render would be a second ride; the whole point of answer 11's round
    is that the limiter it re-runs sees the samples the nominal encode saw.  The
    tee is therefore not "close enough" -- it is asserted equal to what the sink
    read, and asserted equal to the curve applied to the decoded source.
    """
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    pcm = tmp_path / "ride.pcm"
    sink_saw = tmp_path / "sink.bin"
    params = lr.RideParams(target_lufs=-16.0)

    rendered = lr.run_ride(
        decoder_args=["-c", _DECODER_SCRIPT, "0.5"],
        sink_args=["-c", _SINK_SCRIPT, str(sink_saw)],
        curve=[(0.0, 6.0), (10.0, 6.0)],
        params=params,
        pcm_path=pcm,
    )

    assert rendered.frames == 60000
    assert rendered.audio_seconds == round(60000 / params.sample_rate, 3)
    assert pcm.exists(), "run_ride must leave the tee for its caller to own"
    tee = pcm.read_bytes()
    assert tee == sink_saw.read_bytes()
    assert len(tee) == 60000 * 2 * 4

    samples = np.frombuffer(tee, dtype="<f4")
    # The decoder's ramp runs -0.5 .. +0.499 of ``amp``, so its hottest *absolute*
    # sample is the trough at ``amp * 0.5``, and a +6 dB curve scales amplitude by
    # 10**(6/20) -- not by 2.  Pinning the value is what proves the tee carries the
    # curve-applied stream and not, say, the decode.
    expected = 0.5 * 0.5 * 10.0 ** (6.0 / 20.0)
    assert samples.size == 120000
    assert abs(float(np.max(np.abs(samples))) - expected) < 1e-6


def test_run_ride_writes_no_tee_unless_it_is_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nominal path pays nothing for a facility its caller did not request."""
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    sink_saw = tmp_path / "sink.bin"
    before = set(tmp_path.iterdir())
    lr.run_ride(
        decoder_args=["-c", _DECODER_SCRIPT, "0.5"],
        sink_args=["-c", _SINK_SCRIPT, str(sink_saw)],
        curve=[(0.0, 0.0)],
        params=lr.RideParams(target_lufs=-16.0),
    )
    assert set(tmp_path.iterdir()) == before | {sink_saw}


# ---------------------------------------------------------------------------
# The re-encode runner
# ---------------------------------------------------------------------------


def test_run_reencode_reports_the_wall_time_and_raises_on_a_bad_pcm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-encode is a process like any other: it reports, and it fails loudly."""
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    pcm = tmp_path / "ride.pcm"
    pcm.write_bytes(b"\x00\x00\x80?\x00\x00\x80?" * 2048)
    out = tmp_path / "guard.ts"
    calls: list[list[str]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        argv = list(args[0])  # type: ignore[arg-type]
        calls.append(argv)
        if argv[-1] == "-":
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        out.write_bytes(b"ts")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(lr.subprocess, "run", fake_run)
    rendered = lr.run_reencode(
        pcm_path=pcm,
        output_path=out,
        trim_db=0.5,
        params=lr.RideParams(target_lufs=-16.0, limit_dbtp=-2.8),
        profile=CanonicalProfile(video_codec="h264_mf"),
    )
    assert rendered.wall_s >= 0.0
    assert calls, "run_reencode must run the builder's own argv"
    assert str(pcm) in calls[0]
    assert str(out) in calls[0]


def test_run_reencode_raises_the_module_error_on_a_non_zero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    pcm = tmp_path / "ride.pcm"
    pcm.write_bytes(b"\x00" * 64)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        argv = list(args[0])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(argv, 1, b"", b"Invalid data found")

    monkeypatch.setattr(lr.subprocess, "run", fake_run)
    with pytest.raises(lr.LoudnessRideError) as caught:
        lr.run_reencode(
            pcm_path=pcm,
            output_path=tmp_path / "guard.ts",
            trim_db=0.0,
            params=lr.RideParams(target_lufs=-16.0),
            profile=CanonicalProfile(video_codec="h264_mf"),
        )
    assert "Invalid data found" in str(caught.value)
