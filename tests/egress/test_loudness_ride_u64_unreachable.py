# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U64: the ride's window gate on a program with a stretch beyond its reach.

The incident these tests pin: C15's loudness #9 FAIL (2026-09-29 07:18) reported
an aired four-minute stretch 10.02 LU under target.  The source's own level over
that stretch is -44.66 LUFS -- 28.66 LU below the -16 LUFS target -- and the
ride's clamp is +18 dB, so *no* ride this module can run puts that stretch inside
the +/-0.9 LU window gate.  The window was therefore not evidence about the ride;
it was a reading of the source, and the module scored it as a miss.

The signal below is synthetic, and deliberately so: the tests must run without
the station's 4.4 h source asset (which lives under ``C:\\ProgramData`` and is not
fixture material).  It is faithful because every number in it is a measurement of
the real thing rather than a convenience:

* the body sits at -16.0 LUFS, the program's own level, so the whole-program leg
  is already at target and the trim stays near zero -- as it did on air (+0.97 dB);
* the quiet stretch's *gated* level is -44.66 LUFS and its block level jitters
  between -42.40 and -50.70, which are the real capture's measured values.  The
  gate is therefore not being made to say "silence": every block is 20+ LU above
  the absolute gate and ``gated_loudness`` returns a finite number in there;
* the stretch is 300 s of core inside 90 s ramps -- 480 s end to end, longer
  than the gate's 240 s window, so both window families have a window wholly
  inside the core, which is what the aired capture showed.  The ramps are the
  real program's shape (a meeting does not step 28 LU in one block) and they are
  load-bearing for the test: the ride's slew is 0.5 dB/s, so on a step edge the
  *reachable* window after the stretch would air genuinely hot and the test would
  be measuring its own discontinuity instead of the clamp;
* the render pass is arithmetic (the ride's own curve plus its trim, and the
  ride's own gating) rather than ffmpeg.  The limiter is a no-op on a signal
  40 LU below its ceiling, and the curve moves at most 0.5 dB/s, so applying a
  gain per 100 ms block is faithful well inside 0.1 LU.

Everything the module does on this program -- the clamp reaching its ceiling,
the emitted quiet window landing ~10.7 LU off target, the whole program holding
-- is asserted, so a change that stops reproducing the mechanism fails here
rather than passing on an API detail.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from civiccast.egress import loudness_ride as lr
from civiccast.egress.models import CanonicalProfile

_TARGET_LUFS = -16.0
#: The program's own level, and the ride's target: a conform needing no lift.
_BODY_LUFS = -16.0
#: The aired stretch's measured gated level, and the span of its block levels.
_QUIET_LUFS = -44.66
_QUIET_JITTER = (2.26, 0.0, -2.26, 1.70, -3.40, -6.04, 1.13, -2.83, 0.57, -1.98)
#: 40 minutes of program around the stretch.  Length matters to this test: the
#: ride's global trim is what it must add after the whole program is re-gated, and
#: the lift it gives the unreachable stretch re-enters that gate; on a 20 min
#: program that feedback alone eats the window tolerance, which is a different
#: (real) effect and not the one under test here.
_DURATION_S = 2400.0
#: The quiet stretch: a 90 s ramp down, a 300 s core, a 90 s ramp back up.  The
#: ramps are not decoration -- the ride's gain slews at 0.5 dB/s, so a 28.66 dB
#: step in one block would leave the program after the stretch genuinely hot and
#: the test would be measuring its own discontinuity instead of the clamp.
_QUIET_RAMP_S = 90.0
_QUIET_START_S = 600.0
_QUIET_CORE_START_S = _QUIET_START_S + _QUIET_RAMP_S
_QUIET_CORE_END_S = _QUIET_CORE_START_S + 300.0
_QUIET_END_S = _QUIET_CORE_END_S + _QUIET_RAMP_S
_BLOCK_S = lr.BLOCK_STEP_S
_PEAK_DBFS = -3.0  # well under the true-peak ceiling, so the guard spends no round


def _stderr(values: list[float], *, integrated_lufs: float | None = None) -> str:
    """One measurement pass's stderr: a block line per value, then the summary."""
    lines = [
        f"[Parsed_ebur128_0 @ 0x1] t: {0.1 + k * _BLOCK_S:.1f} M: {v:.3f} S: -inf"
        for k, v in enumerate(values)
    ]
    if integrated_lufs is not None:
        lines.append(f"    I:         {integrated_lufs:.2f} LUFS")
    return "\n".join(lines) + "\n"


def _value_at(t: float, k: int) -> float:
    """The program's block level at ``t``: body, ramp, or the stretch's own core."""
    if t < _QUIET_START_S or t >= _QUIET_END_S:
        return _BODY_LUFS
    if t < _QUIET_CORE_START_S:
        frac = (t - _QUIET_START_S) / _QUIET_RAMP_S
        return _BODY_LUFS + frac * (_QUIET_LUFS - _BODY_LUFS)
    if t >= _QUIET_CORE_END_S:
        frac = (t - _QUIET_CORE_END_S) / _QUIET_RAMP_S
        return _QUIET_LUFS + frac * (_BODY_LUFS - _QUIET_LUFS)
    return _QUIET_LUFS + _QUIET_JITTER[k % len(_QUIET_JITTER)]


def _source_blocks() -> list[tuple[float, float]]:
    """The synthetic program: a loud body, and the real quiet stretch inside it."""
    return [
        (round(0.1 + k * _BLOCK_S, 4), _value_at(round(0.1 + k * _BLOCK_S, 4), k))
        for k in range(round(_DURATION_S / _BLOCK_S))
    ]


def _ridden(curve, trim_db: float | None, blocks) -> list[tuple[float, float]]:
    """The ride's own arithmetic: one gain per block, the trim added on top."""
    return [
        (
            t,
            lr.DIGITAL_SILENCE
            if v <= lr.DIGITAL_SILENCE / 2
            else v + lr.interp(curve, t) + (trim_db or 0.0),
        )
        for t, v in blocks
    ]


def _trim_of(sink_args) -> float | None:
    """The trim the sink's filter chain carries, read back out of its own args."""
    match = re.search(r"volume=(-?\d+\.\d+)dB", " ".join(str(a) for a in sink_args))
    return None if match is None else float(match.group(1))


class _Harness:
    """The ride, the capture and the peak scan, over the synthetic program.

    One object because the emitted pass's stderr is only known once the emit has
    run, and the measurement fakes have to key on the artifact it wrote.
    """

    def __init__(self, blocks: list[tuple[float, float]]) -> None:
        self.blocks = blocks
        self.source_stderr = _stderr(
            [v for _, v in blocks],
            integrated_lufs=lr.gated_loudness([v for _, v in blocks]),
        )
        self.emitted_stderr = ""
        self.emitted_path: Path | None = None
        self.measured: list[Path] = []
        self.ride_calls: list[SimpleNamespace] = []

    # -- the ride ---------------------------------------------------------
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
        trim_db = _trim_of(sink_args)
        self.ride_calls.append(
            SimpleNamespace(
                sink_args=list(sink_args),
                curve=list(curve),
                params=params,
                trim_db=trim_db,
                is_probe=str(sink_args[-1]) == "-",
            )
        )
        emitted = _ridden(curve, trim_db, self.blocks)
        text = _stderr(
            [v for _, v in emitted],
            integrated_lufs=lr.gated_loudness([v for _, v in emitted]),
        )
        if str(sink_args[-1]) == "-":
            return lr.RideRender(frames=0, audio_seconds=0.0, wall_s=0.5, stderr=text)
        if pcm_path is not None:
            Path(pcm_path).write_bytes(b"tee")
        target = Path(sink_args[-1])
        target.write_bytes(b"emitted")
        self.emitted_path = target
        self.emitted_stderr = text
        return lr.RideRender(
            frames=int(_DURATION_S * params.sample_rate),
            audio_seconds=_DURATION_S,
            wall_s=1.0,
            stderr=text,
        )

    def reencode(
        self, *, pcm_path, output_path, trim_db, params, profile, timeout_s=None, variant=None
    ):
        raise AssertionError("this program is not hot: the guard owes no round")

    # -- the probes -------------------------------------------------------
    def capture(self, args, *, timeout_s=None, cancel_event=None):
        path = Path(args[args.index("-i") + 1])
        self.measured.append(path)
        if len(self.measured) == 1:
            return self.source_stderr
        if self.emitted_path is not None and path == self.emitted_path:
            return self.emitted_stderr
        raise AssertionError(f"the run measured an unexpected path: {path}")

    def scan(self, artifact_path, *, params, timeout_s=None, cancel_event=None):
        return _PEAK_DBFS

    # -- readback ---------------------------------------------------------
    def emitted_series(self) -> list[tuple[float, float]]:
        """The emitted program, re-derived from the emit pass's own curve + trim."""
        emit = next(call for call in self.ride_calls if not call.is_probe)
        return _ridden(emit.curve, emit.trim_db, self.blocks)

    def applied_curve(self):
        emit = next(call for call in self.ride_calls if not call.is_probe)
        return emit.curve


def _run(tmp_path: Path, monkeypatch) -> tuple[_Harness, lr.LeveledWindow]:
    harness = _Harness(_source_blocks())
    monkeypatch.setattr(lr, "run_capture", harness.capture)
    monkeypatch.setattr(lr, "scan_peak_dbfs", harness.scan)
    source = tmp_path / "x.capture"
    source.write_bytes(b"source")
    window = lr.level_window(
        source_path=source,
        audio_path=tmp_path / "audio.ts",
        params=lr.RideParams(target_lufs=_TARGET_LUFS),
        profile=CanonicalProfile(video_codec="h264_mf"),
        duration_s=_DURATION_S,
        ride_runner=harness.ride,
        reencode_runner=harness.reencode,
    )
    return harness, window


def test_the_ride_reports_a_stretch_it_cannot_reach_instead_of_failing_it(
    tmp_path: Path, monkeypatch
) -> None:
    """GREEN on the U64 candidate; RED on the installed (LIVE) bytes.

    The assertions are ordered so the RED lands on the defect rather than on a
    missing symbol: everything down to the window-leg assertion uses only API the
    installed bytes already have, and on LIVE that assertion is the failure --
    the kept attempt's own window leg *is* the 10.7 LU miss, because the gate
    scored a window the +18 dB clamp cannot reach.
    """
    harness, window = _run(tmp_path, monkeypatch)
    selection = window.selection
    emitted = harness.emitted_series()

    # -- the incident, on the artifact that would air ----------------------
    worst, where = lr.worst_window_deviation_lu(emitted, _DURATION_S, target_lufs=_TARGET_LUFS)
    assert worst is not None and worst > 9.0, (
        f"the reproduction: the emitted quiet window is {worst} LU off, not the "
        f"~10.7 LU the C15 capture showed"
    )
    assert where is not None and _QUIET_START_S <= where < _QUIET_END_S, (
        f"the miss should name a window inside the quiet stretch, got {where}"
    )
    gains = [g for _, g in harness.applied_curve()]
    assert max(gains) >= 18.0 - 0.001, "the clamp should be engaged on this program"
    assert sum(1 for g in gains if g >= 18.0 - 0.001) > 200, (
        "the stretch should pin the curve at its ceiling for minutes, not moments"
    )

    # -- the defect (this is the assertion that fails on LIVE) --------------
    attempt = selection.attempts[0]
    assert attempt.worst_window_err_lu is not None
    assert attempt.worst_window_err_lu <= lr.LOUDNESS_WINDOW_TOL_LU, (
        f"the kept attempt still reports a {attempt.worst_window_err_lu} LU window "
        f"miss: the gate scored a window the ride cannot reach"
    )

    # -- the source is quiet, not silent: the rule is not a silence detector -
    quiet = [v for t, v in harness.blocks if _QUIET_CORE_START_S <= t < _QUIET_CORE_END_S]
    assert max(quiet) < lr.unreachable_floor_lufs(target_lufs=_TARGET_LUFS, g_max_db=18.0), (
        "every second in the stretch is below the ride's reach, and that is the point"
    )
    assert min(quiet) > lr.SILENCE_FLOOR_LUFS, (
        "the rule must not be a silence test: real speech is here, 20+ LU above the gate"
    )
    assert lr.gated_loudness(quiet) is not None

    # -- the fix, named and legible ----------------------------------------
    assert attempt.unreachable_windows, "the exclusions must be named, not silent"
    excused = set(attempt.unreachable_windows)
    for offset in (0.0, lr.LOUDNESS_WINDOW_OFFSET_S):
        family = {s for s, _ in lr.window_levels(harness.blocks, _DURATION_S, offset_s=offset)}
        assert family & excused, (
            f"the {offset} s tiling has a window over the stretch and the gate "
            f"scored it: the exclusion missed a whole family"
        )
    assert attempt.loudness_excused(
        window_tol_lu=lr.LOUDNESS_WINDOW_TOL_LU, whole_tol_lu=lr.LOUDNESS_WHOLE_TOL_LU
    )
    assert abs(attempt.whole_err_lu) <= lr.LOUDNESS_WHOLE_TOL_LU, (
        "the whole-program leg is unchanged: this is the same audio, judged on "
        "the windows the ride can do something about"
    )
    assert selection.kept is attempt


def test_no_window_is_excused_on_a_program_the_ride_can_level() -> None:
    """The exclusion has to be empty when nothing is beyond reach.

    Without this, a bug that excused everything would pass the test above.
    """
    blocks = [
        (round(0.1 + k * _BLOCK_S, 4), _BODY_LUFS) for k in range(round(_DURATION_S / _BLOCK_S))
    ]
    levels = lr.sliding_levels(blocks, lr.RideParams(target_lufs=_TARGET_LUFS).window_s, 1.0)
    assert (
        lr.unreachable_window_starts(
            levels,
            lr.series_duration_s(blocks),
            target_lufs=_TARGET_LUFS,
            g_max_db=18.0,
        )
        == ()
    )


def test_the_exclusions_name_windows_the_gate_actually_scores() -> None:
    """Both tilings, and only starts the gate walks -- the same geometry, not a copy."""
    blocks = _source_blocks()
    params = lr.RideParams(target_lufs=_TARGET_LUFS)
    levels = lr.sliding_levels(blocks, params.window_s, params.step_s)
    duration = lr.series_duration_s(blocks)
    excused = lr.unreachable_window_starts(
        levels, duration, target_lufs=_TARGET_LUFS, g_max_db=params.g_max_db
    )
    scored = set()
    for offset in (0.0, lr.LOUDNESS_WINDOW_OFFSET_S):
        scored |= {start for start, _ in lr.window_levels(blocks, duration, offset_s=offset)}
    assert set(excused) <= scored
    assert excused, "a window wholly inside the stretch must be excluded"
    # The loud windows -- the ones wholly in the body, either family -- are never
    # excused: an exclusion that swallows the program would fail the fix's point.
    assert {0.0, 120.0, 1920.0, 2040.0} & set(excused) == set()


def test_a_reachable_miss_is_still_a_miss() -> None:
    """The exclusion is about the source's floor, not about the gate's verdict."""
    miss = lr.LeveledAttempt(
        round_index=0,
        limit_dbtp=-1.5,
        emitted_dbtp=-3.0,
        emitted_lufs=-16.0,
        worst_window_err_lu=2.0,
        whole_err_lu=0.0,
        wall_s=1.0,
        unreachable_windows=(480.0,),
    )
    assert not miss.loudness_ok(
        window_tol_lu=lr.LOUDNESS_WINDOW_TOL_LU, whole_tol_lu=lr.LOUDNESS_WHOLE_TOL_LU
    )
    assert not miss.loudness_excused(
        window_tol_lu=lr.LOUDNESS_WINDOW_TOL_LU, whole_tol_lu=lr.LOUDNESS_WHOLE_TOL_LU
    )
    # And a whole-program miss is never excused by a window exclusion either.
    whole_miss = lr.LeveledAttempt(
        round_index=0,
        limit_dbtp=-1.5,
        emitted_dbtp=-3.0,
        emitted_lufs=-14.5,
        worst_window_err_lu=0.2,
        whole_err_lu=1.5,
        wall_s=1.0,
        unreachable_windows=(480.0,),
    )
    assert not whole_miss.loudness_excused(
        window_tol_lu=lr.LOUDNESS_WINDOW_TOL_LU, whole_tol_lu=lr.LOUDNESS_WHOLE_TOL_LU
    )
