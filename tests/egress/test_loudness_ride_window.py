# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 answer 12: the acceptance gate, ported, and the leveling run that feeds it.

Answer 12 section 3 wires the guard into ``preparer.py``, and the guard's whole
input is a *measured artifact*: the ride has to measure the audio it just
emitted, on the acceptance harness's own arithmetic, and judge it.  Two things
therefore live in the module that did not before:

* the acceptance gate itself -- the 240 s window tiling in both families, the
  worst window deviation, the whole-program error -- a port of the harness the
  coordinator's U25 panel is scored by (``%TEMP%\\u25\\validate.py`` and
  ``%TEMP%\\u25\\r9\\model.py``), read over the same 100 ms M series
  :func:`civiccast.egress.loudness_ride.parse_ebur128_series` already returns;
* the leveling run: source series, :func:`converge`, the emitted pass with the
  guard's PCM tee, one re-encode round, and ``select_leveled_attempt``.

The ported arithmetic is deliberately *unrounded*.  The harness rounds every
number to 3 dp for its table; a gate the product ships on compares the value it
measured, not a display of it.  The tests below therefore pin the arithmetic to
hand-computed values and to the harness's own geometry (window starts, the
``duration - 1`` tail rule, ``start <= t < end``), so a drift in either shows up
as a wrong number rather than as a table that merely looks different.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.egress import loudness_ride as lr
from civiccast.egress.models import CanonicalProfile, EgressSourceSegment

# ---------------------------------------------------------------------------
# Canned ebur128 output.  The block line is the shape FFmpeg writes (and the
# module's own ``_RE_SERIES`` reads); the summary lines are the two the artifact
# attempt is built from.
# ---------------------------------------------------------------------------


def _stderr(
    values: list[float],
    *,
    step_s: float = 0.1,
    peak_dbtp: float | None = None,
    integrated_lufs: float | None = None,
) -> str:
    """One measurement pass's stderr: a block line per value, then the summary."""
    lines = [
        f"[Parsed_ebur128_0 @ 0x1] t: {0.1 + k * step_s:.1f} M: {v:.3f} S: -inf"
        for k, v in enumerate(values)
    ]
    if integrated_lufs is not None:
        lines.append(f"    I:         {integrated_lufs:.2f} LUFS")
    if peak_dbtp is not None:
        # FFmpeg prints a positive peak with no leading '+': "Peak:       11.9
        # dBFS" (measured, station ffmpeg 2026-09-26), and the module's parser
        # reads FFmpeg's format, not a signed one.  A fixture that wrote "+2.60"
        # here would be a stderr no FFmpeg ever produces.
        lines.append(f"    Peak:       {peak_dbtp:.2f} dBFS")
    return "\n".join(lines) + "\n"


def _flat(value: float, *, seconds: float = 240.0, step_s: float = 0.1) -> list[float]:
    return [value] * round(seconds / step_s)


def _pairs(values: list[float], *, step_s: float = 0.1) -> list[tuple[float, float]]:
    """The ``(t, M)`` pairs those block lines parse to."""
    return [(round(0.1 + k * step_s, 4), v) for k, v in enumerate(values)]


# ---------------------------------------------------------------------------
# The gate's constants and its geometry
# ---------------------------------------------------------------------------


def test_the_window_constants_are_the_measured_ones() -> None:
    assert lr.LOUDNESS_WINDOW_S == 240.0
    assert lr.LOUDNESS_WINDOW_OFFSET_S == 120.0
    assert lr.LOUDNESS_WINDOW_TOL_LU == 0.9
    assert lr.LOUDNESS_WHOLE_TOL_LU == 0.5


def test_series_duration_is_the_last_block_plus_one_step() -> None:
    assert lr.series_duration_s(_pairs(_flat(-16.0, seconds=240.0))) == pytest.approx(240.1)
    assert lr.series_duration_s([]) == 0.0


def test_window_tiling_matches_the_harness_geometry() -> None:
    """Ten minutes, both families: starts 0/240/480 and 120/360.

    The harness tiles while ``start < duration - 1`` and clamps each window's end
    to the duration, so a 600 s artifact yields three windows from the zero
    family (the last one clamped, 480 -> 600) and two from the 120 s family.
    """
    series = _pairs(_flat(-16.0, seconds=600.0))
    zero = lr.window_levels(series, 600.0, offset_s=0.0)
    offset = lr.window_levels(series, 600.0, offset_s=lr.LOUDNESS_WINDOW_OFFSET_S)
    assert [round(start, 3) for start, _ in zero] == [0.0, 240.0, 480.0]
    assert [round(start, 3) for start, _ in offset] == [120.0, 360.0]
    assert all(level == pytest.approx(-16.0) for _, level in zero + offset)


def test_a_window_boundary_belongs_to_the_later_window() -> None:
    """``start <= t < end``: the block at exactly 240.0 s is the 240 s window's.

    One block 15 LU above the rest, sitting on the boundary.  The first window
    must not see it at all (its level stays exactly -16.0), and the second must
    (its level rises above -16.0).
    """
    values = _flat(-16.0, seconds=600.0)
    values[round(240.0 / 0.1) - 1] = -1.0
    assert _pairs(values)[2399][0] == pytest.approx(240.0)
    first, second = lr.window_levels(_pairs(values), 600.0, offset_s=0.0)[:2]
    assert first[1] == pytest.approx(-16.0)
    assert second[1] is not None and second[1] > -16.0


def test_the_tail_shorter_than_a_second_is_not_a_window() -> None:
    """``start < duration - 1``: a 240.5 s artifact has one window, 241.5 s has two."""
    series = _pairs(_flat(-16.0, seconds=241.5))
    assert len(lr.window_levels(series, 240.5, offset_s=0.0)) == 1
    assert len(lr.window_levels(series, 241.5, offset_s=0.0)) == 2


def test_a_window_of_pure_digital_silence_has_no_level() -> None:
    assert lr.window_levels(_pairs(_flat(lr.DIGITAL_SILENCE)), 240.0, offset_s=0.0)[0][1] is None


def test_the_worst_window_deviation_searches_both_families() -> None:
    """A 240 s stretch that is only inside one family's window still counts.

    Blocks from 120 s to 360 s sit 10 LU low.  The zero family sees half of them
    in each of two windows (2.599 LU of error -- the harness's own number, not a
    hand-computed one); the 120 s family sees all of them in one window -- 10.0 LU
    -- and that is the number the gate must report, at the window's own start.
    """
    series = [
        (t, -26.0 if 120.0 <= t <= 360.0 else v) for t, v in _pairs(_flat(-16.0, seconds=600.0))
    ]
    worst, start = lr.worst_window_deviation_lu(series, 600.0, target_lufs=-16.0)
    assert worst == pytest.approx(10.0)
    assert start == pytest.approx(120.0)
    zero_only = lr.worst_window_deviation_lu(series, 600.0, target_lufs=-16.0, offset_s=0.0)
    assert zero_only[0] == pytest.approx(2.599, abs=0.001)


def test_the_worst_window_deviation_is_none_when_nothing_was_measured() -> None:
    assert lr.worst_window_deviation_lu([], 240.0, target_lufs=-16.0) == (None, None)
    assert lr.worst_window_deviation_lu(
        _pairs(_flat(lr.DIGITAL_SILENCE)), 240.0, target_lufs=-16.0
    ) == (None, None)


def test_the_whole_program_error_is_the_gated_mean_of_the_series() -> None:
    """Whole-program ``I`` is the two-stage gated mean of the same M series.

    All blocks at -10 LUFS relative to a -16 target is exactly +6.0 LU of error,
    and it is signed: a program 4 LU quiet reads -4.0.
    """
    assert lr.whole_program_err_lu(_pairs(_flat(-10.0)), target_lufs=-16.0) == pytest.approx(6.0)
    assert lr.whole_program_err_lu(_pairs(_flat(-20.0)), target_lufs=-16.0) == pytest.approx(-4.0)
    assert lr.whole_program_err_lu([], target_lufs=-16.0) is None
    assert lr.whole_program_err_lu(_pairs(_flat(lr.DIGITAL_SILENCE)), target_lufs=-16.0) is None


# ---------------------------------------------------------------------------
# The two parsers the gate is scored with
# ---------------------------------------------------------------------------


def test_parse_true_peak_reads_the_summary_line() -> None:
    assert lr.parse_true_peak_dbtp("  True peak:\n    Peak:       -1.53 dBFS\n") == -1.53
    assert lr.parse_true_peak_dbtp("    Peak:       0.00 dBFS\n") == 0.0
    assert lr.parse_true_peak_dbtp("") is None
    assert lr.parse_true_peak_dbtp("    I:  -16.00 LUFS\n") is None


def test_parse_true_peak_takes_the_first_peak_line() -> None:
    """Harness parity: ``RE_TP.search`` -- the first match, not the last."""
    text = "    Peak:       -1.30 dBFS\n    Peak:       -2.90 dBFS\n"
    assert lr.parse_true_peak_dbtp(text) == -1.30


def test_parse_true_peak_ignores_the_per_frame_tpk_columns() -> None:
    """The per-block lines carry ``TPK:``, which is not a ``Peak:`` summary."""
    text = (
        "[Parsed_ebur128_0 @ 0x1] t: 0.1 M: -20.000 S: -inf"
        " I: -20.0 LUFS LRA: 0.0 LU FTPK: -3.0 -3.0 dBFS TPK: -2.9 -2.9 dBFS\n"
    )
    assert lr.parse_true_peak_dbtp(text) is None


# ---------------------------------------------------------------------------
# One attempt, out of one measurement
# ---------------------------------------------------------------------------


def test_attempt_from_measurement_keeps_the_printed_I_out_of_the_gate() -> None:
    """``emitted_lufs`` is the summary line; the gate is the series' own mean.

    They are different quantities on purpose: the summary ``I`` is what FFmpeg
    printed, the gate is what the acceptance harness computes off the same
    blocks.  Here they disagree (printed -16.0, series' gated mean -20.0) and the
    gate follows the series -- the panel's arithmetic, which puts the single
    240 s window 4.0 LU low and the whole program 4.0 LU low, not at target.
    """
    attempt = lr.attempt_from_measurement(
        _stderr(_flat(-20.0), peak_dbtp=-1.42, integrated_lufs=-16.0),
        round_index=1,
        limit_dbtp=-1.8,
        target_lufs=-16.0,
        duration_s=240.0,
        decoded_peak_dbfs=0.0036,
        wall_s=12.5,
    )
    assert attempt.round_index == 1
    assert attempt.limit_dbtp == pytest.approx(-1.8)
    assert attempt.emitted_lufs == pytest.approx(-16.0)
    assert attempt.emitted_dbtp == pytest.approx(-1.42)
    assert attempt.whole_err_lu == pytest.approx(-4.0)
    assert attempt.worst_window_err_lu == pytest.approx(4.0)
    assert attempt.decoded_peak_dbfs == pytest.approx(0.0036)
    assert attempt.wall_s == pytest.approx(12.5)
    assert attempt.loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5) is False
    assert attempt.hard_tp_ok() is True


def test_attempt_from_measurement_without_a_measurement_still_builds() -> None:
    """No series, no summary: every measured field is ``None``, nothing raises."""
    attempt = lr.attempt_from_measurement(
        "",
        round_index=0,
        limit_dbtp=-1.5,
        target_lufs=-16.0,
        duration_s=240.0,
    )
    assert attempt.emitted_lufs is None
    assert attempt.emitted_dbtp is None
    assert attempt.worst_window_err_lu is None
    assert attempt.whole_err_lu is None
    assert attempt.wall_s == 0.0
    assert attempt.decoded_peak_dbfs is None
    assert attempt.loudness_ok(window_tol_lu=0.9, whole_tol_lu=0.5) is False
    assert attempt.hard_tp_ok() is False


def test_attempt_duration_falls_back_to_the_series_coverage() -> None:
    """Without a stated duration the tiling uses the artifact's own coverage."""
    with_duration = lr.attempt_from_measurement(
        _stderr(_flat(-16.0)),
        round_index=0,
        limit_dbtp=-1.5,
        target_lufs=-16.0,
        duration_s=240.0,
    )
    without = lr.attempt_from_measurement(
        _stderr(_flat(-16.0)),
        round_index=0,
        limit_dbtp=-1.5,
        target_lufs=-16.0,
    )
    assert with_duration.worst_window_err_lu == pytest.approx(0.0)
    assert without.worst_window_err_lu == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# The two argument builders
# ---------------------------------------------------------------------------


def test_the_artifact_measure_args_measure_the_whole_file() -> None:
    """Seek-free, exactly like the harness's ``measure_whole``: no ``-ss``/``-t``."""
    args = lr.build_artifact_measure_args(artifact_path=Path("C:/cache/x.ts"))
    assert "-ss" not in args and "-t" not in args
    assert args[args.index("-i") + 1] == "C:/cache/x.ts" or args[args.index("-i") + 1] == str(
        Path("C:/cache/x.ts")
    )
    assert "-vn" in args
    assert "ebur128=peak=true" in args
    assert args[-2:] == ["-f", "null"] or args[-1] == "-"


def test_the_peak_scan_args_decode_to_raw_float32() -> None:
    params = lr.RideParams(target_lufs=-16.0)
    args = lr.build_peak_scan_args(artifact_path=Path("C:/cache/x.ts"), params=params)
    assert "-f" in args and args[args.index("-f") + 1] == "f32le"
    assert "-ar" in args and args[args.index("-ar") + 1] == "48000"
    assert "-ac" in args and args[args.index("-ac") + 1] == "2"
    assert "-vn" in args
    assert args[-1] == "-"


def test_the_program_mux_bounds_the_window_after_both_inputs() -> None:
    """``-t`` is an OUTPUT option, so it has to follow the LAST ``-i``.

    FFmpeg binds a ``-t`` sitting between two ``-i`` operands to the input that
    follows it -- here the ride's own audio, which is already exactly the
    window's length, so the bound became a no-op on the source.  Measured on a
    real 4 s window of an 8 s asset: the built program carried 7 s of video
    (the whole source tail past the in-point) against 3.97 s of audio, where
    ``build_conform_source_args``'s single-input ``-t`` produced 4 s.  The
    ``-ss`` stays before the FIRST ``-i``: that one is an input option on
    purpose.
    """
    segment = EgressSourceSegment(
        label="trimmed",
        path="C:/in/asset.mp4",
        duration_seconds=4.0,
        inpoint_seconds=1.0,
        outpoint_seconds=5.0,
    )
    args = lr.build_video_from_source_args(
        source_path=Path("C:/in/asset.mp4"),
        audio_path=Path("C:/in/program.ts.ride-audio.ts"),
        output_path=Path("C:/out/program.ts"),
        segment=segment,
        profile=CanonicalProfile(),
    )
    inputs = [i for i, arg in enumerate(args) if arg == "-i"]
    assert len(inputs) == 2, "the program mux reads the source and the ride's audio"
    assert args.index("-ss") < inputs[0], "the seek belongs to the source input"
    assert args.index("-t") > inputs[-1], "the window bound must be an output option"
    assert args[args.index("-t") + 1] == "4"


# ---------------------------------------------------------------------------
# The leveling run.  The two renderers are substituted (no encoder, no ride);
# the measurement is substituted too, so the run's own decisions -- which round
# ships, in which file -- are what the assertions read.
# ---------------------------------------------------------------------------

_NOMINAL = b"nominal-artifact"
_ROUND = b"round-artifact"
#: 240 s of blocks, so both window families exist (starts 0 and 120).
_WINDOW_S = 240.0
_FLAT = _flat(-16.0, seconds=_WINDOW_S)
#: A round that came back 4 LU quiet: lawful on the hard bound, and over the
#: window gate, which is how the pre-U43 ceiling round failed live (U42 log line
#: 18797).  U43's pad round hands the level back as drive, so this is the shape
#: the round *used* to have -- kept here because the selector still has to judge
#: a quiet round when a recorder hands it one.
_QUIET = _flat(-20.0, seconds=_WINDOW_S)


@dataclass(frozen=True)
class _Limiter:
    """The limiter's (drive, ceiling) -> level coupling, in the shape U43 measured.

    ``level = nominal_level + drive - ceiling_cost``.  The drive is returned 1:1
    -- what the pad and its correction both move is a constant gain *before* the
    limiter -- and a ceiling lowered by ``d`` costs ``ceiling_cost_lu_per_db * d``
    LU of whole-program loudness.

    ``ceiling_cost_lu_per_db=1.0`` is a limiter that takes back exactly what the
    pad hands it: the pad round then lands on the target with nothing to correct,
    which is the whole of the pad round's behaviour as U43 part II left it, and is
    why it is the default.  A recorder with no limiter measures the target on
    every pass -- the canned behaviour every other test in this file runs on.

    Cell A is *below* 1.0, and that is the shape answer 2 exists for: after a
    3.25 dB pad the attempt came back 0.53 LU loud, so the lowered ceiling cost
    the limiter 2.72 LU of the 3.25 it was handed -- harder limiting removes less
    loudness than the pad returns, by 0.53 LU more than the pad assumed.
    """

    ceiling_cost_lu_per_db: float = 1.0
    nominal_ceiling_dbtp: float = -1.5
    nominal_level_lufs: float = -16.0

    def level(self, trim_db: float, ceiling_dbtp: float) -> float:
        """The whole-program loudness of ``trim_db`` of drive at ``ceiling_dbtp``."""
        drop = max(self.nominal_ceiling_dbtp - ceiling_dbtp, 0.0)
        return self.nominal_level_lufs + trim_db - self.ceiling_cost_lu_per_db * drop


def _probe_trim(sink_args: list[str]) -> float:
    """The drive a probe pass ran with, read off its own filter chain.

    A pass with no ``volume`` filter (the ride-only pass) ran at 0.0 dB; anything
    else carries the drive the module formatted into its argv, which is what
    actually ran -- not the arithmetic that asked for it.
    """
    chain = str(sink_args[sink_args.index("-af") + 1])
    for part in chain.split(","):
        if part.startswith("volume="):
            return float(part[len("volume=") : -2])
    return 0.0


class _Recorder:
    """A stand-in for the ride, the round, the capture and the scan.

    One object because the round's artifact path is only known once the round
    runs, and the measurement fakes have to key on it.

    ``round_stderr``/``round_peak`` are the *pad* round's (``variant=None``,
    the one answer 12's ceiling and U43's drive are spent in).  ``variant_results``
    are the U42 variant rounds'
    -- ``(stderr, decoded peak)`` per variant call, in call order, so a test can
    give the 256 kbps round a different artifact from the fast-coder one.  A
    variant call with no entry left falls back to the pad round's, which is
    what a test that does not care about the variants wants.

    ``limiter`` is the one knob that overrides the canned numbers: with a model
    in play, every pass -- the probes and the re-encodes alike -- measures the
    loudness its own (drive, ceiling) emits, which is what makes the pad round's
    probe informative to the module and what a canned stderr cannot express.  The
    decoded peaks stay canned in every case.
    """

    def __init__(
        self,
        *,
        nominal_stderr: str,
        nominal_peak: float | None,
        round_stderr: str = "",
        round_peak: float | None = None,
        variant_results: list[tuple[str, float | None]] | None = None,
        round_error: Exception | None = None,
        capture_error: Exception | None = None,
        source_stderr: str = "",
        limiter: _Limiter | None = None,
    ) -> None:
        self.nominal_stderr = nominal_stderr
        self.nominal_peak = nominal_peak
        self.round_stderr = round_stderr
        self.round_peak = round_peak
        self.limiter = limiter
        self.variant_results = list(variant_results or [])
        self.round_error = round_error
        self.capture_error = capture_error
        self.source_stderr = source_stderr or _stderr(_flat(-25.0, seconds=60.0), step_s=0.1)
        self.emitted_path: Path | None = None
        self.round_path: Path | None = None
        self.ride_calls: list[SimpleNamespace] = []
        self.round_calls: list[SimpleNamespace] = []
        self.measured: list[Path] = []
        self.scanned: list[Path] = []
        #: Per-artifact measurement, keyed by the path the round wrote, so more
        #: than one round can be measured in the same run.
        self.artifact_text: dict[Path, str] = {}
        self.artifact_peak: dict[Path, float | None] = {}

    # -- the renderers ----------------------------------------------------
    def ride(
        self,
        *,
        decoder_args,
        sink_args,
        curve,
        params,
        pcm_path=None,
        cancel_event=None,
        timeout_s=None,
    ):
        self.ride_calls.append(
            SimpleNamespace(
                decoder_args=list(decoder_args),
                sink_args=list(sink_args),
                curve=list(curve),
                params=params,
                pcm_path=pcm_path,
                timeout_s=timeout_s,
            )
        )
        target = Path(sink_args[-1])
        if str(sink_args[-1]) == "-":
            # A probe pass: the measure sink discards, so it has no artifact.  With
            # a limiter model, the pass measures its own drive at its own ceiling --
            # which is exactly the question the pad round's probe is asking.
            level = -16.0
            if self.limiter is not None:
                level = self.limiter.level(_probe_trim(sink_args), params.limit_dbtp)
            return lr.RideRender(
                frames=0,
                audio_seconds=0.0,
                wall_s=0.5,
                stderr=_stderr(_flat(level), integrated_lufs=level),
            )
        if pcm_path is not None:
            Path(pcm_path).write_bytes(b"tee")
        target.write_bytes(_NOMINAL)
        self.emitted_path = target
        return lr.RideRender(frames=0, audio_seconds=0.0, wall_s=1.5, stderr="")

    def reencode(
        self, *, pcm_path, output_path, trim_db, params, profile, timeout_s=None, variant=None
    ):
        self.round_calls.append(
            SimpleNamespace(
                pcm_path=pcm_path,
                output_path=output_path,
                trim_db=trim_db,
                params=params,
                variant=variant,
                timeout_s=timeout_s,
            )
        )
        if self.round_error is not None:
            raise self.round_error
        if variant is None:
            text, peak = self.round_stderr, self.round_peak
        elif self.variant_results:
            text, peak = self.variant_results.pop(0)
        else:
            text, peak = self.round_stderr, self.round_peak
        if self.limiter is not None:
            # The model has the last word on what a re-encode measures: the level
            # a given (drive, ceiling) emits is the whole point of the A-shaped
            # test, and a canned stderr cannot express it.
            level = self.limiter.level(trim_db, params.limit_dbtp)
            text = _stderr(_flat(level), peak_dbtp=self.round_peak, integrated_lufs=level)
            peak = self.round_peak
        path = Path(output_path)
        path.write_bytes(_ROUND)
        self.artifact_text[path] = text
        self.artifact_peak[path] = peak
        self.round_path = path
        return lr.RideRender(frames=0, audio_seconds=0.0, wall_s=0.5, stderr="")

    # -- the probes -------------------------------------------------------
    def capture(self, args, *, timeout_s=None, cancel_event=None):
        path = Path(args[args.index("-i") + 1])
        self.measured.append(path)
        if self.capture_error is not None:
            raise self.capture_error
        if len(self.measured) == 1:
            # The run's first measurement is the source series -- the only pass
            # that is allowed to read the source file.
            return self.source_stderr
        if path.name == "x.capture":
            raise AssertionError(f"the run measured an unexpected path: {path}")
        if path in self.artifact_text:
            return self.artifact_text[path]
        if self.emitted_path is not None and path == self.emitted_path:
            if self.round_path is not None and self.round_path.exists() is False:
                raise AssertionError("the nominal artifact was overwritten before it was judged")
            return self.nominal_stderr
        return self.source_stderr

    def scan(self, artifact_path, *, params, timeout_s=None, cancel_event=None):
        path = Path(artifact_path)
        self.scanned.append(path)
        if path in self.artifact_peak:
            return self.artifact_peak[path]
        return self.nominal_peak


def _run(tmp_path: Path, monkeypatch, rec: _Recorder, **kwargs):
    monkeypatch.setattr(lr, "run_capture", rec.capture)
    monkeypatch.setattr(lr, "scan_peak_dbfs", rec.scan)
    source = tmp_path / "x.capture"
    source.write_bytes(b"source")
    audio = tmp_path / "audio.ts"
    return lr.level_window(
        source_path=source,
        audio_path=audio,
        params=lr.RideParams(target_lufs=-16.0),
        profile=CanonicalProfile(video_codec="h264_mf"),
        duration_s=_WINDOW_S,
        ride_runner=rec.ride,
        reencode_runner=rec.reencode,
        **kwargs,
    )


def test_level_window_keeps_the_round_that_clears_the_gates_with_the_lower_peak(
    tmp_path: Path, monkeypatch
) -> None:
    """Answer 12's keep-best, end to end: the nominal is hot, the round is lawful.

    The nominal emitted at -0.60 dBTP with a decoded peak of +0.40 dBFS -- over
    the hard bound -- while its loudness gates hold; the single round at a lower
    ceiling emits -1.60 dBTP with a peak of -0.20 dBFS and holds loudness too.
    Both clear the loudness gates, so the peek at the lowest decoded peak
    decides, and the round wins.  The artifact that airs must then *be* the
    round's: same bytes, in the caller's path.

    The round's two settings are U43's measured pad on the nominal attempt: the
    decoded peak is 0.40 over the +0.1 dBFS bound, so the pad is 0.40 - 0.1 + 0.5
    = 0.80 dB -- the ceiling drops to -2.30 dBTP and the drive rises by the same
    0.80 dB.  That drive is only the round's *guess*: the pad round probes its own
    settings first and corrects the drive by the loudness it measured (answer 2).
    This recorder measures the target on every pass, so the correction here is a
    no-op and the guess is what is spent.  The case where it is not a no-op is
    ``test_level_window_corrects_the_pad_rounds_drive_onto_the_target``.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.60, integrated_lufs=-16.0),
        round_peak=-0.20,
    )
    result = _run(tmp_path, monkeypatch, rec)

    selection = result.selection
    assert [a.round_index for a in selection.attempts] == [0, 1]
    assert selection.kept.round_index == 1
    assert selection.kept.limit_dbtp == pytest.approx(-2.3)
    assert selection.hard_tp_met is True
    assert selection.target_met is True
    assert selection.warning is None
    assert result.audio_path.read_bytes() == _ROUND
    # The round re-encodes the PCM the nominal emit consumed -- the tee the run
    # was handed -- at the padded ceiling and drive, and it is spent once.
    assert len(rec.round_calls) == 1, "the round met the bound, so no variant is spent"
    assert rec.round_calls[0].variant is None
    assert rec.round_calls[0].pcm_path is not None
    assert rec.round_calls[0].params.limit_dbtp == pytest.approx(-2.3)
    assert rec.round_calls[0].trim_db == pytest.approx(result.curve.trim_db + 0.80)


def test_level_window_corrects_the_pad_rounds_drive_onto_the_target(
    tmp_path: Path, monkeypatch
) -> None:
    """Answer 2: the pad's drive guesses, the round's own measurement corrects it.

    Cell A, on a limiter model built from the live measurement.  The nominal is
    over the bound at +2.85 dBFS, so the pad is 3.25 dB and the round is set to
    emit at a -4.75 dBTP ceiling and a +3.25 dB drive.  A limiter that handed back
    exactly what the pad spends would land on -16.0 LUFS untouched -- but harder
    limiting removes *less* loudness than the pad returns, and the live sweep
    measured this round 0.53 LU loud: of the 3.25 dB of ceiling it was given, the
    limiter cost it 2.72 LU.  0.53 LU is over the 0.5 LU whole-program tolerance
    by 0.03, so the uncorrected round is *not* lawful, and the loudness-first
    keep-best below would pass over the round that fixed the bound.

    So the round measures the settings it is about to spend: one probe pass at
    (-4.75, +3.25) comes back at -15.47 LUFS, and the drive is corrected by that
    error -- 3.25 - 0.53 = 2.72 dB -- before the encode.  The corrected round is
    lawful on both gates and under the bound (-1.938 dBFS), so it is what ships
    and no variant is owed.  Run against the module before this correction
    existed, the same recorder never sees the probe (three ride passes, not four)
    and the uncorrected round is scored unlawful.
    """
    limiter = _Limiter(ceiling_cost_lu_per_db=2.72 / 3.25)
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=+4.60, integrated_lufs=-16.0),
        nominal_peak=2.85,
        round_stderr="",  # the model measures the round, so no canned numbers
        round_peak=-1.938,
        limiter=limiter,
    )
    result = _run(tmp_path, monkeypatch, rec)

    pad = 2.85 - lr.TP_GUARD_MAX_PEAK_DBFS + lr.TP_GUARD_PAD_MARGIN_DB
    pad_ceiling = -1.5 - pad
    assert pad == pytest.approx(3.25)
    # Three convergence passes, then the pad round's own probe -- and the probe
    # ran at the pad's guess, at the ceiling the round will emit at.
    probes = [c for c in rec.ride_calls if str(c.sink_args[-1]) == "-"]
    assert len(probes) == 4
    assert probes[-1].params.limit_dbtp == pytest.approx(pad_ceiling)
    assert _probe_trim(probes[-1].sink_args) == pytest.approx(result.curve.trim_db + pad)
    # ...and that guess is exactly the one that misses: +0.53 LU, 0.03 LU over the
    # whole-program tolerance.  This is the product's own gate judging the same
    # measurement the round corrects from, so the test cannot drift from it.
    guess_level = limiter.level(result.curve.trim_db + pad, pad_ceiling)
    guess = lr.attempt_from_measurement(
        _stderr(_flat(guess_level), peak_dbtp=-1.938, integrated_lufs=guess_level),
        round_index=1,
        limit_dbtp=pad_ceiling,
        target_lufs=-16.0,
        duration_s=_WINDOW_S,
        decoded_peak_dbfs=-1.938,
    )
    assert guess.whole_err_lu == pytest.approx(0.53)
    assert guess.hard_tp_ok() is True
    assert (
        guess.loudness_ok(
            window_tol_lu=lr.LOUDNESS_WINDOW_TOL_LU,
            whole_tol_lu=lr.LOUDNESS_WHOLE_TOL_LU,
        )
        is False
    )

    # The round that was actually spent carries the corrected drive, and it holds
    # both gates -- which is why it is kept and why no variant is owed.
    assert len(rec.round_calls) == 1, "the corrected round met the bound"
    assert rec.round_calls[0].variant is None
    assert rec.round_calls[0].params.limit_dbtp == pytest.approx(pad_ceiling)
    assert rec.round_calls[0].trim_db == pytest.approx(result.curve.trim_db + pad - 0.53)
    selection = result.selection
    assert [a.round_index for a in selection.attempts] == [0, 1]
    assert selection.kept.round_index == 1
    assert selection.kept.whole_err_lu == pytest.approx(0.0, abs=1e-9)
    assert selection.hard_tp_met is True
    assert selection.target_met is True
    assert selection.warning is None
    assert result.audio_path.read_bytes() == _ROUND


def test_level_window_spends_no_round_when_the_nominal_emitted_at_target(
    tmp_path: Path, monkeypatch
) -> None:
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-1.40, integrated_lufs=-16.0),
        nominal_peak=-0.30,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.90, integrated_lufs=-16.0),
        round_peak=-0.50,
    )
    result = _run(tmp_path, monkeypatch, rec)
    assert rec.round_calls == []
    assert result.selection.kept.round_index == 0
    assert result.selection.hard_tp_met is True
    assert result.selection.target_met is True
    assert result.selection.warning is None
    assert result.audio_path.read_bytes() == _NOMINAL


def test_level_window_ships_the_artifact_when_its_peak_cannot_be_measured(
    tmp_path: Path, monkeypatch
) -> None:
    """An unscanned artifact cannot clear the hard gate, and still airs.

    The emitted true peak is at target, so no round is warranted; the missing
    peak is not a round's job to fix.  The caller's cue for its error line is
    ``hard_tp_met`` being false, with ``decoded_peak_dbfs`` ``None`` to say why.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-1.40, integrated_lufs=-16.0),
        nominal_peak=None,
    )
    result = _run(tmp_path, monkeypatch, rec)
    assert rec.round_calls == []
    assert result.selection.hard_tp_met is False
    assert result.selection.kept.decoded_peak_dbfs is None
    assert result.selection.warning is None
    assert result.audio_path.read_bytes() == _NOMINAL


def test_level_window_warns_when_the_kept_attempt_missed_the_tp_target(
    tmp_path: Path, monkeypatch
) -> None:
    """Every round spent and still hot: it ships, with the guard's warning.

    The pad round is hot (+0.35 dBFS) and so are both U42 encoder variants
    (this recorder hands every variant the pad round's own numbers, which is
    the honest stand-in for "the encoder did not help either"), so the selector
    has nothing better to keep than round 1 and the warning says so.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-0.55, integrated_lufs=-16.0),
        round_peak=0.35,
    )
    result = _run(tmp_path, monkeypatch, rec)
    selection = result.selection
    assert len(rec.round_calls) == 3, "the pad round and both encoder variants"
    assert [c.variant is None for c in rec.round_calls] == [True, False, False]
    assert selection.kept.round_index == 1
    assert selection.target_met is False
    assert selection.hard_tp_met is False
    assert selection.warning is not None
    assert "-1.0 dBTP" in selection.warning
    assert "NOT met" in selection.warning
    assert result.audio_path.read_bytes() == _ROUND


def test_level_window_ships_the_artifact_when_its_measurement_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed measurement pass is a report, not a discarded ride.

    The artifact exists and is lawful as far as anyone knows; only the evidence
    for it is missing.  ``LoudnessRideError`` is swallowed here (the emitted
    true peak is unknown, so the guard cannot ask for a round either) and the
    attempt carries ``None`` throughout.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, integrated_lufs=-16.0),
        nominal_peak=-0.30,
        capture_error=lr.LoudnessRideError("the measurement child exited 1"),
    )
    monkeypatch.setattr(lr, "run_capture", rec.capture)
    monkeypatch.setattr(lr, "scan_peak_dbfs", rec.scan)
    source = tmp_path / "x.capture"
    source.write_bytes(b"source")
    audio = tmp_path / "audio.ts"
    emitted = _stderr(_FLAT, integrated_lufs=-16.0)

    def capture(args, *, timeout_s=None, cancel_event=None):
        path = Path(args[args.index("-i") + 1])
        if path == source:
            return rec.source_stderr
        raise lr.LoudnessRideError("the measurement child exited 1")

    monkeypatch.setattr(lr, "run_capture", capture)
    result = lr.level_window(
        source_path=source,
        audio_path=audio,
        params=lr.RideParams(target_lufs=-16.0),
        profile=CanonicalProfile(video_codec="h264_mf"),
        duration_s=_WINDOW_S,
        ride_runner=rec.ride,
        reencode_runner=rec.reencode,
    )
    assert emitted is not None  # the canned text above is a measurement, not an error
    kept = result.selection.kept
    assert kept.round_index == 0
    assert kept.worst_window_err_lu is None and kept.whole_err_lu is None
    assert kept.decoded_peak_dbfs == pytest.approx(-0.30)
    assert result.selection.hard_tp_met is True
    assert audio.read_bytes() == _NOMINAL


def test_level_window_measures_the_artifact_it_wrote_not_the_source(
    tmp_path: Path, monkeypatch
) -> None:
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-1.40, integrated_lufs=-16.0),
        nominal_peak=-0.30,
    )
    result = _run(tmp_path, monkeypatch, rec)
    source = tmp_path / "x.capture"
    assert rec.measured[0] == source
    assert rec.measured[-1] == result.audio_path
    assert rec.scanned == [result.audio_path]


def test_level_window_propagates_cancellation_instead_of_shipping(
    tmp_path: Path, monkeypatch
) -> None:
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, integrated_lufs=-16.0),
        nominal_peak=-0.30,
    )
    source = tmp_path / "x.capture"
    source.write_bytes(b"source")

    def capture(args, *, timeout_s=None, cancel_event=None):
        path = Path(args[args.index("-i") + 1])
        if path == source:
            return rec.source_stderr
        raise lr.LoudnessRideCancelledError("cancelled")

    monkeypatch.setattr(lr, "run_capture", capture)
    monkeypatch.setattr(lr, "scan_peak_dbfs", rec.scan)
    with pytest.raises(lr.LoudnessRideCancelledError):
        lr.level_window(
            source_path=source,
            audio_path=tmp_path / "audio.ts",
            params=lr.RideParams(target_lufs=-16.0),
            profile=CanonicalProfile(video_codec="h264_mf"),
            duration_s=_WINDOW_S,
            ride_runner=rec.ride,
            reencode_runner=rec.reencode,
        )


def test_level_window_leaves_a_caller_supplied_tee_alone(tmp_path: Path, monkeypatch) -> None:
    """The tee outlives the call: it is the caller's file, and both passes read it."""
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.60, integrated_lufs=-16.0),
        round_peak=-0.20,
    )
    tee = tmp_path / "ride.pcm"
    result = _run(tmp_path, monkeypatch, rec, pcm_path=tee)
    assert result.audio_path.read_bytes() == _ROUND
    assert tee.exists()
    emit_calls = [c for c in rec.ride_calls if str(c.sink_args[-1]) != "-"]
    assert len(emit_calls) == 1 and emit_calls[0].pcm_path == tee
    assert rec.round_calls[0].pcm_path == tee


def test_level_window_deletes_the_tee_it_owns(tmp_path: Path, monkeypatch) -> None:
    """``pcm_path=None``: the module tees into its own temp file and cleans it up."""
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.60, integrated_lufs=-16.0),
        round_peak=-0.20,
    )
    result = _run(tmp_path, monkeypatch, rec)
    emit_calls = [c for c in rec.ride_calls if str(c.sink_args[-1]) != "-"]
    owned = emit_calls[0].pcm_path
    assert owned is not None
    assert not Path(owned).exists()
    assert result.audio_path.exists()


def test_level_window_spends_no_round_when_the_round_fails(tmp_path: Path, monkeypatch) -> None:
    """A failed round is not an error: the nominal is still the best attempt.

    The round's failure leaves the nominal artifact in place -- the bytes that
    air are the bytes the nominal emit wrote -- and the guard keeps round 0.

    The nominal is still hot (+0.40 dBFS), so U42's encoder variants *are*
    spent against that same hot attempt: a variant is the guard's response to a
    measured over-bound peak, and a round that never rendered does not change
    what the guard knows.  They fail too, so the nominal still airs.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_error=lr.LoudnessRideError("the guard's re-encode exited 1"),
    )
    result = _run(tmp_path, monkeypatch, rec)
    assert len(rec.round_calls) == 3, "the pad round and both encoder variants"
    assert result.selection.kept.round_index == 0
    assert result.audio_path.read_bytes() == _NOMINAL
    # The failure is reported, not swallowed: the caller logs it beside the
    # selection's own warning, and no partial round file survives the run.
    assert result.round_error is not None
    assert "exited 1" in result.round_error
    assert rec.round_path is None


def test_level_window_keeps_the_nominal_when_the_round_peaks_higher(
    tmp_path: Path, monkeypatch
) -> None:
    """The peak axis outranks the true-peak axis, and a losing render is deleted.

    Both attempts hold loudness, so answer 12's key moves to the lowest decoded
    peak -- and the nominal's +0.40 dBFS beats the round's +0.55, even though the
    round emitted the better true peak (-1.60 against -0.60).  The artifact that
    airs is the nominal's, and the round's file does not outlive the decision.

    That kept nominal is over the hard bound, so U42 spends both encoder
    variants too -- and this recorder hands them the pad round's own hot
    numbers, which is the honest stand-in for "the encoder did not help".  All
    three rounds lose to the nominal, and all three files are deleted.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.60, integrated_lufs=-16.0),
        round_peak=0.55,
    )
    result = _run(tmp_path, monkeypatch, rec)
    selection = result.selection
    assert len(rec.round_calls) == 3
    assert selection.kept.round_index == 0
    assert selection.kept.decoded_peak_dbfs == pytest.approx(0.40)
    assert selection.target_met is False
    assert selection.warning is not None
    assert result.audio_path.read_bytes() == _NOMINAL
    assert rec.round_path is not None
    assert rec.round_path != result.audio_path
    assert not rec.round_path.exists()


def test_level_window_variants_the_encoder_when_the_kept_attempt_is_hot(
    tmp_path: Path, monkeypatch
) -> None:
    """U42's live shape: the ceiling is not the lever, the encoder is.

    This is log line 18797 reproduced as a decision.  The nominal emits +2.60
    dBTP / +0.783 dBFS at the -1.50 dBTP ceiling; U43's pad round (ceiling -2.683,
    drive +1.183) is lawful on peak but 4 LU quiet this time, so it fails the
    loudness gate and cannot be kept -- the attempt the selector would still ship
    is the nominal, and it is over the bound.  The guard's remaining lever is the
    encoder, so it re-encodes the same retained PCM at the *kept attempt's own*
    settings -- the nominal's, since the pad round lost -- with the profile's
    first variant (256 kbps), which comes back at -1.064 dBFS and is kept.  The
    second variant is never spent: the first one met the bound, and the order is a
    cost contract.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=+2.60, integrated_lufs=-16.0),
        nominal_peak=0.783,
        round_stderr=_stderr(_QUIET, peak_dbtp=-1.90, integrated_lufs=-20.0),
        round_peak=-1.89,
        variant_results=[(_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0), -1.064)],
    )
    result = _run(tmp_path, monkeypatch, rec)
    selection = result.selection

    assert [c.variant for c in rec.round_calls] == [None, lr.EncoderVariant(256)]
    # Round 0 is the pad round: +0.783 dBFS is 0.683 over the bound, plus the
    # 0.5 dB margin, so the ceiling drops to -2.683 and the drive rises by 1.183.
    pad = 0.783 - lr.TP_GUARD_MAX_PEAK_DBFS + lr.TP_GUARD_PAD_MARGIN_DB
    assert rec.round_calls[0].params.limit_dbtp == pytest.approx(-1.5 - pad)
    assert rec.round_calls[0].trim_db == pytest.approx(result.curve.trim_db + pad)
    # The variant re-encodes the SAME retained PCM, at the kept attempt's own
    # settings -- the nominal's, because the pad round lost the loudness gate: no
    # re-render, no re-convergence, and neither the ceiling nor the drive is a
    # second variable moving at the same time as the encoder.
    assert rec.round_calls[1].pcm_path == rec.round_calls[0].pcm_path
    assert rec.round_calls[1].params.limit_dbtp == pytest.approx(-1.5)
    assert rec.round_calls[1].trim_db == pytest.approx(result.curve.trim_db)

    assert [a.round_index for a in selection.attempts] == [0, 1, 2]
    assert [a.encoder for a in selection.attempts] == ["aac 192k", "aac 192k", "aac 256k"]
    assert selection.kept.round_index == 2
    assert selection.kept.decoded_peak_dbfs == pytest.approx(-1.064)
    assert selection.hard_tp_met is True
    assert result.audio_path.read_bytes() == _ROUND
    # One file airs: the loser is deleted rather than left beside it.
    assert not (tmp_path / "audio.ts.round1.ts").exists()
    assert not (tmp_path / "audio.ts.round2.ts").exists()


def test_level_window_spends_every_variant_until_one_meets_the_bound(
    tmp_path: Path, monkeypatch
) -> None:
    """The variants are an ordered list, and the guard walks it in order.

    The pad round fails its loudness gate and the 256 kbps variant comes
    back hot too (+0.35 dBFS), so the guard cannot stop there: it spends the
    second variant, the fast coder, which clears the bound at -0.387 dBFS.
    Round 3 is kept and its bytes are what airs.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=+2.60, integrated_lufs=-16.0),
        nominal_peak=0.783,
        round_stderr=_stderr(_QUIET, peak_dbtp=-1.90, integrated_lufs=-20.0),
        round_peak=-1.89,
        variant_results=[
            (_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0), 0.35),
            (_stderr(_FLAT, peak_dbtp=-0.40, integrated_lufs=-16.0), -0.387),
        ],
    )
    result = _run(tmp_path, monkeypatch, rec)
    selection = result.selection

    assert [c.variant for c in rec.round_calls] == [
        None,
        lr.EncoderVariant(256),
        lr.EncoderVariant(256, ("-aac_coder", "fast")),
    ]
    assert [a.encoder for a in selection.attempts] == [
        "aac 192k",
        "aac 192k",
        "aac 256k",
        "aac 256k (-aac_coder fast)",
    ]
    assert selection.kept.round_index == 3
    assert selection.kept.decoded_peak_dbfs == pytest.approx(-0.387)
    assert selection.hard_tp_met is True
    assert result.audio_path.read_bytes() == _ROUND
    for index in (1, 2, 3):
        assert not (tmp_path / f"audio.ts.round{index}.ts").exists()


def test_level_window_spends_the_variants_at_the_pad_rounds_ceiling_and_drive(
    tmp_path: Path, monkeypatch
) -> None:
    """The order is one pad round, then the variants at the *pad round's* settings.

    U43's round moves two settings at once -- the ceiling down by the pad and the
    drive up by exactly the same pad -- so after it the attempt the guard must
    beat is no longer the nominal.  Here the pad round holds both loudness gates
    and still comes back over the bound at +0.30 dBFS: lower than the nominal's
    +0.40, so it is what the selector would ship, and the encoder variant is then
    spent at *its* pair (-2.30 dBTP, drive +0.80) rather than the nominal's.  A
    variant that moved the ceiling or the drive back would be varying three axes
    at once, and its artifact would not be comparable with the one it beats.
    """
    rec = _Recorder(
        nominal_stderr=_stderr(_FLAT, peak_dbtp=-0.60, integrated_lufs=-16.0),
        nominal_peak=0.40,
        round_stderr=_stderr(_FLAT, peak_dbtp=-1.10, integrated_lufs=-16.0),
        round_peak=0.30,
        variant_results=[(_stderr(_FLAT, peak_dbtp=-1.60, integrated_lufs=-16.0), -0.15)],
    )
    result = _run(tmp_path, monkeypatch, rec)
    selection = result.selection
    pad = 0.40 - lr.TP_GUARD_MAX_PEAK_DBFS + lr.TP_GUARD_PAD_MARGIN_DB

    assert [c.variant for c in rec.round_calls] == [None, lr.EncoderVariant(256)]
    assert [a.round_index for a in selection.attempts] == [0, 1, 2]
    assert rec.round_calls[0].params.limit_dbtp == pytest.approx(-1.5 - pad)
    assert rec.round_calls[0].trim_db == pytest.approx(result.curve.trim_db + pad)
    assert rec.round_calls[1].params.limit_dbtp == pytest.approx(-1.5 - pad)
    assert rec.round_calls[1].trim_db == pytest.approx(result.curve.trim_db + pad)
    # The pad round is what the guard would ship when the variant is spent, and
    # it is over the bound -- which is exactly why the variant is owed.
    assert selection.kept.round_index == 2
    assert selection.kept.decoded_peak_dbfs == pytest.approx(-0.15)
    assert selection.hard_tp_met is True
    assert result.audio_path.read_bytes() == _ROUND
    assert not (tmp_path / "audio.ts.round1.ts").exists()
    assert not (tmp_path / "audio.ts.round2.ts").exists()
