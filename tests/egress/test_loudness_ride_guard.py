# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 answer 12: the emitted-artifact guard, keep-best, with a measured bound.

Answer 7's guard re-ran the *whole* leveling path at a lowered ceiling, and U25
round 7 measured what that cost: on BIG it spent all three allowed rounds and
539.13 s of a 908.41 s total, and its step law (ceiling down by the overshoot,
emitted true peak follows 1:1) did not hold -- a -1.30 dB ceiling step bought
0.00 dB of true peak, because the emitted true peak is the AAC codec's own
overshoot rather than a property of the limiter.  Answer 11 replaced it with one
re-encode-only round plus a *last resort* -- and U25's own panel then showed that
clause harming exactly the case it fired on: on BIG the last-resort artifact was
worse than the attempt the selector already held on **every** gated axis
(loudness 1.588 vs 0.285 LU of window error, whole-program -1.1 vs 0.0 LU,
decoded peak +0.4018 vs +0.0036 dBFS), because it gave up a loudness gate it had
passed in order to keep failing the one it was chasing.  Answer 12 deletes it:

* the selector is keep-best, always: the attempts that pass the loudness gates
  first, then the lowest decoded sample peak, then the lowest emitted true peak;
* the hard true-peak gate is a bound the product can honestly guarantee -- no
  decoded sample above :data:`TP_GUARD_MAX_PEAK_DBFS`.  BIG's nominal emit, the
  hottest artifact the panel produced, sits at +0.0036 dBFS from one sample in
  9000 s: a codec overshoot under the audibility floor;
* an artifact over that bound on *every* attempt still ships, with an error line
  rather than a stop -- the selector has nothing better to keep, and a channel
  that airs a slightly hot artifact beats one that airs nothing;
* the one re-encode round stays, and so does the :data:`TP_GUARD_TARGET_DBTP` of
  -1.0 dBTP as best effort, with one warning when the selector's keep misses it.

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
    encoder: str = "",
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
        encoder=encoder,
    )


def _select(attempts: list[lr.LeveledAttempt]) -> lr.LeveledSelection:
    return lr.select_leveled_attempt(attempts, window_tol_lu=0.9, whole_tol_lu=0.5)


# ---------------------------------------------------------------------------
# The hard gate
# ---------------------------------------------------------------------------


def test_the_gate_constants_are_the_answered_ones() -> None:
    assert lr.TP_GUARD_TARGET_DBTP == -1.0
    assert lr.TP_GUARD_MAX_PEAK_DBFS == 0.1
    assert lr.TP_GUARD_PAD_MARGIN_DB == 0.5
    assert lr.TP_GUARD_MAX_PAD_DB == 6.0
    # Answer 12 deleted the last-resort branch, constant and all.
    assert not hasattr(lr, "TP_GUARD_LAST_RESORT_DBTP")
    assert not hasattr(lr, "TP_GUARD_HARD_DBTP")
    assert not hasattr(lr, "needs_last_resort")
    # U43 replaced the emitted-TP ceiling step with the measured pad: the step's
    # helpers, its round budget and its margin are gone, not merely unused.
    assert not hasattr(lr, "guard_ceiling_dbtp")
    assert not hasattr(lr, "guard_next_ceiling")
    assert not hasattr(lr, "TP_GUARD_MAX_ROUNDS")
    assert not hasattr(lr, "TP_GUARD_MARGIN_DB")


def test_the_hard_gate_is_the_decoded_sample_bound() -> None:
    """One bound, measured on the artifact: no decoded sample above +0.1 dBFS.

    The emitted true peak is deliberately not part of it -- it is the codec's own
    overshoot, so an emitted-true-peak leg would only re-impose the ceiling
    arithmetic answer 12 abandoned.  ``+0.0036`` is BIG's nominal emit.
    """
    assert _attempt(decoded_peak_dbfs=0.0).hard_tp_ok() is True
    assert _attempt(decoded_peak_dbfs=0.1).hard_tp_ok() is True
    assert _attempt(decoded_peak_dbfs=0.0036).hard_tp_ok() is True
    assert _attempt(decoded_peak_dbfs=0.1001).hard_tp_ok() is False
    assert _attempt(decoded_peak_dbfs=0.4018).hard_tp_ok() is False
    assert _attempt(decoded_peak_dbfs=-1.3202).hard_tp_ok() is True
    # An unscanned artifact cannot clear a bound nobody measured.
    assert _attempt(decoded_peak_dbfs=None).hard_tp_ok() is False
    # ... and the emit's own true peak does not decide it.
    assert _attempt(emitted_dbtp=+2.8, decoded_peak_dbfs=-0.5).hard_tp_ok() is True
    assert _attempt(emitted_dbtp=-1.5, decoded_peak_dbfs=+0.5).hard_tp_ok() is False


def test_loudness_gates_are_unchanged_by_the_answer_11_reshuffle() -> None:
    assert _attempt(worst=0.9, whole=0.5).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(worst=0.91).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(worst=None).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)
    assert not _attempt(whole=None).loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5)


# ---------------------------------------------------------------------------
# The one re-encode-only round: U43's measured pad
# ---------------------------------------------------------------------------


def test_the_pad_is_the_measured_overshoot_plus_the_margin() -> None:
    """The pad is measured on the artifact, not derived from the emitted dBTP.

    U43 measured the emitted true peak's excursion past the ceiling to be the
    codec's own (a 192 kbps AAC round trip added +4.34 dB over a -1.5 dBFS-limited
    signal, and a lowpass at the encoder's own cutoff moved it +0.00 dB), so the
    emitted dBTP is the wrong place to derive a correction from.  The overshoot
    the guard corrects is the one it can see on the artifact it would air: the
    decoded peak's distance above :data:`TP_GUARD_MAX_PEAK_DBFS`.
    """
    # Already lawful: no round is owed.
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=-1.30)) is None
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=0.1)) is None
    # An unmeasured peak is not evidence that a round is owed either.
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=None)) is None
    # U42's live full-asset artifact: +0.783 dBFS is 0.683 over the bound, plus
    # the 0.5 dB margin.
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=0.783)) == 1.183
    # U43's Senior-window cell: +2.85 dBFS is 2.75 over, plus the margin.
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=2.85)) == 3.25
    # The emitted true peak decides nothing -- the decoded peak is the evidence.
    assert lr.guard_pad_db(_attempt(emitted_dbtp=+2.85, decoded_peak_dbfs=0.783)) == 1.183


def test_the_pad_is_capped_and_the_cap_is_not_a_second_round() -> None:
    """A measured need past the cap takes the cap; the miss is reported, not chased.

    One round is the whole budget: a second would move the ceiling and the drive
    again over the same retained PCM, and U43 measured that a ceiling drop alone
    buys loudness loss rather than peak.  So the cap is where the guard stops, and
    keep-best plus the caller's ERROR line are what tell the operator it did not
    reach the bound.
    """
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=5.5)) == 5.9, "under the cap, as measured"
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=5.6)) == 6.0, "6.0 is the cap exactly"
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=6.5)) == 6.0
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=12.0)) == 6.0
    # The cap is a parameter, so the arithmetic above is the cap's, not a
    # constant baked into the formula.
    assert lr.guard_pad_db(_attempt(decoded_peak_dbfs=12.0), max_pad_db=2.0) == 2.0


def test_the_pad_rounds_drive_is_corrected_by_its_own_measurement() -> None:
    """Answer 2: the pad's drive is a guess; the round's measurement corrects it.

    Raising the drive by exactly the pad assumes the harder limiting hands back
    the loudness the pad spent.  U43's live sweep measured that it does not: the
    pad round came back +0.53 LU over the target on cell A and -0.28 LU under on
    cell B -- opposite signs, so the limiter is nonlinear in the ceiling and no
    fixed compensation holds loudness.  The round therefore measures the limited
    pass and corrects its own pre-limiter drive by the error it measured, the
    same correction :func:`converge` applies to the nominal's trim.
    """
    # Cell A's residue: 3.25 dB of pad came back 0.53 LU short of the target, so
    # the drive the round actually emits with is 3.25 - 0.53 = 2.72 dB.
    assert lr.guard_pad_trim_db(-15.47, trim_db=3.25, target_lufs=-16.0) == 2.72
    # Cell B's residue has the other sign: the round overshot the target, so the
    # correction adds rather than subtracts.
    assert lr.guard_pad_trim_db(-16.28, trim_db=3.25, target_lufs=-16.0) == 3.53
    # Already on target is a no-op, not a write of zero drive.
    assert lr.guard_pad_trim_db(-16.0, trim_db=0.80, target_lufs=-16.0) == 0.80
    # The correction is relative to the drive it was handed, not to 0 dB.
    assert lr.guard_pad_trim_db(-15.0, trim_db=0.15, target_lufs=-16.0) == -0.85
    # A pass that measured no loudness corrects nothing: the caller emits the
    # uncorrected pad rather than inventing a drive from an absent measurement.
    assert lr.guard_pad_trim_db(None, trim_db=3.25, target_lufs=-16.0) is None
    # The drive is emitted in the ``volume=`` element's own 3 dp form, so the
    # corrected value is rounded there and not left as a longer float.
    assert lr.guard_pad_trim_db(-16.12349, trim_db=0.0, target_lufs=-16.0) == 0.123


# ---------------------------------------------------------------------------
# Selection: the loudness gates, then the lowest decoded peak, then the emit
# ---------------------------------------------------------------------------


def test_the_loudness_gates_outrank_the_lowest_decoded_peak() -> None:
    """The adverse-BIG shape, in the panel's own numbers.

    BIG's nominal round passed both loudness gates at a decoded peak of
    +0.0036 dBFS.  The single re-encode round came back 0.6 LU quieter, blew the
    window gate at 0.92 LU, and decoded **hotter** at +0.7979 dBFS.  Ranking the
    peak first would ship the second; answer 12 ranks the gates first, and the
    hard bound that follows is then judged on what ships.
    """
    big_nominal = _attempt(
        round_index=0,
        limit_dbtp=-1.5,
        emitted_dbtp=0.0,
        emitted_lufs=-16.0,
        worst=0.285,
        whole=0.0,
        decoded_peak_dbfs=0.0036,
    )
    big_reencode = _attempt(
        round_index=1,
        limit_dbtp=-2.8,
        emitted_dbtp=0.9,
        emitted_lufs=-16.6,
        worst=0.92,
        whole=-0.6,
        decoded_peak_dbfs=0.7979,
    )
    sel = _select([big_nominal, big_reencode])
    assert sel.kept.round_index == 0
    assert sel.hard_tp_met is True, "+0.0036 dBFS is inside the +0.1 bound"
    assert sel.target_met is False, "+0.00 dBTP misses the -1.0 dBTP target"
    assert sel.warning is not None
    assert "+0.00 dBFS" in sel.warning


def test_the_loudness_gates_outrank_the_coldest_emit() -> None:
    loud = _attempt(limit_dbtp=-1.5, emitted_dbtp=-0.4, decoded_peak_dbfs=-0.487)
    colder_not_loud = _attempt(
        round_index=1, limit_dbtp=-2.4, emitted_dbtp=-0.9, worst=1.4, decoded_peak_dbfs=-1.2
    )
    sel = _select([loud, colder_not_loud])
    assert sel.kept.round_index == 0
    assert sel.hard_tp_met is True
    assert sel.target_met is False
    assert sel.warning is not None


def test_the_lowest_decoded_peak_wins_among_lawful_attempts() -> None:
    """The peak axis is live: a colder *emit* does not outrank a colder *decode*."""
    lower_peak_hotter_tp = _attempt(limit_dbtp=-1.5, emitted_dbtp=-0.9, decoded_peak_dbfs=-1.30)
    colder_tp_higher_peak = _attempt(
        round_index=1, limit_dbtp=-2.8, emitted_dbtp=-1.5, decoded_peak_dbfs=-0.80
    )
    sel = _select([lower_peak_hotter_tp, colder_tp_higher_peak])
    assert sel.kept.round_index == 0


def test_the_coldest_lawful_emit_breaks_a_peak_tie() -> None:
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=-1.2, decoded_peak_dbfs=-0.5),
            _attempt(round_index=1, limit_dbtp=-1.8, emitted_dbtp=-1.6, decoded_peak_dbfs=-0.5),
        ]
    )
    assert sel.kept.round_index == 1
    assert sel.target_met is True
    assert sel.warning is None


def test_an_unmeasurable_attempt_never_wins() -> None:
    sel = _select(
        [
            _attempt(emitted_dbtp=None, decoded_peak_dbfs=None),
            _attempt(round_index=1, limit_dbtp=-2.0, emitted_dbtp=-1.3, decoded_peak_dbfs=-0.9),
        ]
    )
    assert sel.kept.round_index == 1
    assert sel.warning is None


def test_an_unscanned_peak_cannot_win_the_peak_axis() -> None:
    """A peak nobody measured is not the lowest peak; it is no evidence at all."""
    unscanned = _attempt(limit_dbtp=-1.5, emitted_dbtp=-1.4, decoded_peak_dbfs=None)
    scanned = _attempt(round_index=1, limit_dbtp=-1.8, emitted_dbtp=-1.4, decoded_peak_dbfs=-0.05)
    sel = _select([unscanned, scanned])
    assert sel.kept.round_index == 1
    assert sel.hard_tp_met is True


def test_all_unmeasurable_keeps_the_nominal() -> None:
    sel = _select(
        [_attempt(emitted_dbtp=None), _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=None)]
    )
    assert sel.kept.round_index == 0
    assert sel.target_met is False
    assert sel.hard_tp_met is False
    assert sel.warning is not None
    assert "unmeasurable" in sel.warning


def test_ties_go_to_the_earlier_round() -> None:
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=-1.4, decoded_peak_dbfs=-0.6),
            _attempt(round_index=1, limit_dbtp=-1.8, emitted_dbtp=-1.4, decoded_peak_dbfs=-0.6),
        ]
    )
    assert sel.kept.round_index == 0


def test_the_warning_names_both_true_peaks_and_the_peak() -> None:
    """One warning, and the numbers an operator needs: what ships, what was emitted."""
    sel = _select(
        [
            _attempt(limit_dbtp=-1.5, emitted_dbtp=0.3, decoded_peak_dbfs=-0.31),
            _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=-0.2, decoded_peak_dbfs=-0.55),
        ]
    )
    assert sel.kept.round_index == 1
    assert sel.target_met is False
    assert sel.warning is not None
    assert "+0.30 dBTP" in sel.warning
    assert "-0.20 dBTP" in sel.warning
    assert "-0.55 dBFS" in sel.warning


def test_no_warning_when_the_target_is_met() -> None:
    sel = _select([_attempt(emitted_dbtp=-1.2, decoded_peak_dbfs=-1.0)])
    assert sel.target_met is True
    assert sel.warning is None


def test_every_attempt_over_the_bound_still_ships_the_best_one() -> None:
    """An ERROR line, not a stop, and not another emit.

    Answer 12: nothing better exists to keep, so the best attempt airs and the
    caller reports it.  The guard must not answer a hot artifact with a quieter
    emit -- that is the last-resort mistake the panel measured.
    """
    hot = _attempt(limit_dbtp=-1.5, emitted_dbtp=0.4, decoded_peak_dbfs=0.30)
    hotter = _attempt(round_index=1, limit_dbtp=-2.8, emitted_dbtp=1.1, decoded_peak_dbfs=0.40)
    sel = _select([hot, hotter])
    assert sel.kept.round_index == 0
    assert sel.hard_tp_met is False
    assert sel.target_met is False
    assert sel.warning is not None
    assert "+0.30 dBFS" in sel.warning
    assert "NOT met" in sel.warning


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


# ---------------------------------------------------------------------------
# U42: the guard's second lever is the ENCODER, not only the ceiling
# ---------------------------------------------------------------------------

#: The measured lever table behind the variant list, all three rows from the
#: same ``stage.s5.pcm`` and the same -1.50 dBTP ceiling, with only the encoder
#: options changed (``evidence/u42-aac-overshoot/out-lever-table.txt``):
#: 192 kbps (the live setting) +0.783 dBFS peak / +2.6 dBTP; 256 kbps
#: -1.064 dBFS / -1.1 dBTP; 192 kbps ``-aac_coder fast`` -0.387 dBFS /
#: -0.4 dBTP.  All three at I = -16.0 LUFS: the codec is loudness-transparent,
#: so the variant round can be judged on the same gates as the attempt it is
#: trying to beat.


def _variant(bitrate_kbps: int, extra_args: tuple[str, ...] = ()) -> lr.EncoderVariant:
    return lr.EncoderVariant(bitrate_kbps=bitrate_kbps, extra_args=extra_args)


def test_the_encoder_variants_are_the_ordered_pair_the_guard_may_spend() -> None:
    """U42's order is the coordinator's: 256 kbps, then 256 kbps + fast coder.

    It is a tuple, so the order is the contract: the guard stops at the first
    variant that meets the bound, and the cheaper lever must be tried first.
    """
    expected = (
        _variant(256),
        _variant(256, ("-aac_coder", "fast")),
    )
    # ruff's SIM300 wants the expectation on the left of a module attribute.
    assert expected == lr.TP_GUARD_ENCODER_VARIANTS


def test_the_encoder_variants_are_offered_only_to_an_aac_profile() -> None:
    """``-aac_coder`` is the native AAC encoder's option, so the list is gated.

    The headend's profiles carry ``audio_codec="ac3"`` (``headend.py``); an
    ``-aac_coder`` beside ``-c:a ac3`` is an FFmpeg parse error, and a variant
    list that cannot be emitted is not a lever.
    """
    assert lr.encoder_variants_for(CanonicalProfile()) == (
        _variant(256),
        _variant(256, ("-aac_coder", "fast")),
    )
    assert lr.encoder_variants_for(CanonicalProfile(audio_codec="ac3")) == ()
    # A variant that would re-emit exactly what the nominal emit already wrote
    # is not a lever either: it buys a whole re-encode and can only change the
    # encoder's state, not its settings.  At 256 kbps the first variant is that
    # variant and drops out; the fast-coder one still differs and stays.
    assert lr.encoder_variants_for(CanonicalProfile(audio_bitrate_kbps=256)) == (
        _variant(256, ("-aac_coder", "fast")),
    )


def test_the_variant_re_encode_changes_only_the_encoder() -> None:
    """The round's grammar is unchanged: same input, same limiter, new encoder.

    U42 is explicit that the variant re-encodes ONLY the AAC and the mux from
    the same already-limited PCM -- no re-render, no re-convergence -- so the
    only options that may differ from the nominal round are the encoder's.
    """
    profile = CanonicalProfile(video_codec="h264_mf")
    params = lr.RideParams(target_lufs=-16.0, limit_dbtp=-1.5)
    pcm = Path("C:/tmp/ride.pcm")
    out = Path("C:/tmp/guard.ts")

    nominal = lr.build_reencode_args(pcm, out, trim_db=1.25, params=params, profile=profile)
    plain = lr.build_reencode_args(
        pcm, out, trim_db=1.25, params=params, profile=profile, variant=_variant(256)
    )
    fast = lr.build_reencode_args(
        pcm,
        out,
        trim_db=1.25,
        params=params,
        profile=profile,
        variant=_variant(256, ("-aac_coder", "fast")),
    )

    def _encoder_block(argv: list[str]) -> tuple[str, str, list[str]]:
        coder: list[str] = []
        if "-aac_coder" in argv:
            index = argv.index("-aac_coder")
            coder = argv[index : index + 2]
        return (argv[argv.index("-c:a") + 1], argv[argv.index("-b:a") + 1], coder)

    def _without_the_encoder_block(argv: list[str]) -> list[str]:
        rest = list(argv)
        del rest[rest.index("-b:a") : rest.index("-b:a") + 2]
        if "-aac_coder" in rest:
            index = rest.index("-aac_coder")
            del rest[index : index + 2]
        return rest

    assert _encoder_block(nominal) == ("aac", "192k", [])
    assert _encoder_block(plain) == ("aac", "256k", [])
    assert _encoder_block(fast) == ("aac", "256k", ["-aac_coder", "fast"])
    # Everything else -- the file input, the trim, the limiter, the rate, the
    # channels, the container -- is byte for byte the nominal round's.
    assert _without_the_encoder_block(nominal) == _without_the_encoder_block(plain)
    assert _without_the_encoder_block(nominal) == _without_the_encoder_block(fast)
    assert f"limit={lr.limit_value(-1.5):.6f}" in ",".join(fast)


def test_the_settings_label_names_the_codec_the_bitrate_and_the_coder() -> None:
    """One label per attempt, so the operator's error line says what ran."""
    profile = CanonicalProfile()
    assert lr.encoder_settings_label(profile) == "aac 192k"
    assert lr.encoder_settings_label(profile, _variant(256)) == "aac 256k"
    assert (
        lr.encoder_settings_label(profile, _variant(256, ("-aac_coder", "fast")))
        == "aac 256k (-aac_coder fast)"
    )


def test_an_attempt_over_the_bound_is_not_an_unscanned_one() -> None:
    """U42 keys the variant round on a *measured* peak that is over the bound.

    ``hard_tp_ok`` is false for both, and for the same reason -- the gate is a
    guarantee and neither attempt can evidence it.  They are not the same input
    to the guard's decision to spend a re-encode: a hot artifact is what the
    encoder is a lever on, and an unscanned one is a measurement failure another
    encode of the same samples will not fix.
    """
    assert _attempt(decoded_peak_dbfs=0.4018).over_hard_bound() is True
    assert _attempt(decoded_peak_dbfs=0.1001).over_hard_bound() is True
    assert _attempt(decoded_peak_dbfs=0.1).over_hard_bound() is False
    assert _attempt(decoded_peak_dbfs=-1.064).over_hard_bound() is False
    assert _attempt(decoded_peak_dbfs=None).over_hard_bound() is False
    assert _attempt(decoded_peak_dbfs=None).hard_tp_ok() is False


def test_the_warning_names_every_attempts_encoder_settings() -> None:
    """U42: each attempt's encoder settings are named, and so is the kept one.

    The shape is the live one -- the nominal at 192 kbps hot, the pad round
    lawful on peak but over the bound, the 256 kbps variant clearing it -- with
    the variant's emitted true peak still short of the best-effort target, which
    is the only case that produces a warning at all.
    """
    hot_nominal = _attempt(
        round_index=0,
        limit_dbtp=-1.5,
        emitted_dbtp=+2.60,
        decoded_peak_dbfs=0.783,
        encoder="aac 192k",
    )
    pad_round = _attempt(
        round_index=1,
        limit_dbtp=-5.4,
        emitted_dbtp=-1.90,
        worst=1.4,
        decoded_peak_dbfs=-1.89,
        encoder="aac 192k",
    )
    variant = _attempt(
        round_index=2,
        limit_dbtp=-1.5,
        emitted_dbtp=-0.85,
        decoded_peak_dbfs=-1.064,
        encoder="aac 256k",
    )
    sel = _select([hot_nominal, pad_round, variant])
    assert sel.kept.round_index == 2, "the variant is loudness-lawful and coldest"
    assert sel.hard_tp_met is True
    assert sel.target_met is False
    assert sel.warning is not None
    assert "aac 192k" in sel.warning
    assert "aac 256k" in sel.warning
    assert "round 2" in sel.warning
    # The label is the kept attempt's own, not the nominal's relabelled.
    assert "keeping round 2" in sel.warning
    assert "-1.06 dBFS" in sel.warning
