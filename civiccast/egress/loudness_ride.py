# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 -- the speech-leveling ride that runs INSTEAD OF loudnorm before playout.

Why the conform stopped using ``loudnorm``
------------------------------------------
``loudnorm`` normalizes a program to its target *on average*.  A public meeting
is not stationary: a chair at the dais, a speaker who steps back from the
lectern, and an un-mic'd speaker at the public-comment mic can sit 15-20 LU
apart inside one recording, so a single whole-program gain necessarily lands
every four-minute stretch somewhere else.  The acceptance bar for a prepared
egress asset is therefore per-stretch, not per-program: **every 240 s window of
the emitted program, in both window families, must land inside
-16 +/- 1.0 LUFS**, with the whole program inside +/- 0.5 LU.  No built-in
FFmpeg leveler reaches that band (U25 rounds 1-2 measured ``dynaudnorm``,
``speechnorm``, ``compand``, ``loudnorm`` one-pass and two-pass, and chains of
them); a slow, speech-following gain ride does.

Shape of the ride
-----------------
::

    source decode (f32le, conformed rate)   ->  per-sample gain curve (pure)
                                            ->  numpy multiply, one chunk at a time
                                            ->  volume=<trim>dB, 4x upsample,
                                                alimiter=<true-peak ceiling>,
                                                4x downsample
                                            ->  AAC / MPEG-TS  (the audio the
                                                video pass then stream-copies)
                                            ->  emitted-true-peak guard: measure
                                                the artifact, re-emit once lower
                                                if it is hotter than -1.0 dBTP

Everything above the process boundary is a pure function of numbers, so the
rules that decide the gain -- the two-stage gate, the window curve, the silence
hold, the clamp, the gap cap, the slew limit, the correction, the sum, the
converge loop -- are all unit-testable without touching FFmpeg.  The three
process entry points (:func:`build_source_series_args`,
:func:`build_measure_sink_args`, :func:`build_encode_sink_args`,
:func:`build_video_from_source_args`) are pure argument builders too, so the
exact FFmpeg grammar is asserted in tests rather than described in prose.

Two-stage gate
--------------
The ride's own loudness arithmetic (:func:`gated_loudness`) is the EBU R128
two-stage gate that the *acceptance* measurement uses, so the ride and the gate
agree by construction rather than by calibration.

The converge loop
-----------------
The gain curve alone gets the program close but not to the bar: the limiter that
protects the emitted true peak is not an identity function, so a ride that
targets -16.0 LUFS emits somewhere near -16.5.  The loop therefore measures the
rendered result and corrects it, three passes per iteration:

``A``  the ride alone, with no trim and no limiter -> ``I_A``, which sets
       ``trim0 = TARGET - I_A`` (the trim that *would* be right if the limiter
       were transparent);
``B``  the ride with ``trim0`` -> ``I_B``, whose residual ``TARGET - I_B`` is
       the limiter's shortfall;
``C``  the ride with ``trim1 = trim0 + (TARGET - I_B) / max(slope, 0.4)``, where
       ``slope`` is the limiter's *measured* dB-per-dB from the previous
       iteration (``(I_C - I_B) / (trim1 - trim0)``).  The floor of 0.4 keeps a
       nearly-flat measured slope from launching the trim to infinity.

The loop stops when the emitted whole-program error is within
:data:`RideParams.stop_lu`, or when an iteration fails to improve on the
previous one, or at :data:`RideParams.max_iters`.  Then the correction curve --
``target - L_W(t)`` of what iteration ``C`` actually measured -- is summed into
the applied curve for the next iteration, and the gap cap is re-applied.

Measured effect (U25 Q12, 4D36 and BIG, the two cells round 5 failed): the
slope-corrected loop moved 4D36 from -0.700 to -0.1 LU and BIG from -0.600 to
+0.1 LU of whole-program error, while the worst 240 s window *improved* on both
(0.899 -> 0.513 and -> 0.289).  Round 5's plain ``trim1 = trim0 + err`` step is
what pinned them 0.6 LU low.

The output stage bounds the true peak, and the emit proves it
------------------------------------------------------------
``alimiter`` is a *sample*-peak limiter: it acts on the samples it is handed, so
on its own it cannot bound the inter-sample peaks an encoder will later create.
U25 Q14 measured the cost of that gap directly -- with a -3.0 dBFS sample-peak
ceiling, BIG's ride output sat at exactly -3.000 dBFS (true peak -0.8 dBTP) and
the emitted AAC still carried four frames above 0 dBFS (peak +2.754 dBFS,
emitted true peak +2.8 dBTP), i.e. essentially all of the reported true-peak
growth was the encoder's, and no sample-peak ceiling can prevent it.  So the
limiter is handed a 4x-oversampled copy of the signal (48 kHz -> 192 kHz, soxr,
precision 28), limits at ``-1.5 dBTP`` -- the value the incumbent
``loudnorm ... TP=-1.5`` conform promised -- and the result is decimated back to
the conformed rate before the AAC encode.

Oversampling makes the *pre*-AAC true peak bounded; it does not by itself make
the *artifact* compliant, because the codec's overshoot is its own -- U25 round 7
measured the limiter holding to +0.0034 dB over its own ceiling while the AAC
round trip added up to +3.27 dB, which is why a lowered ceiling does not buy a
proportionally lower emitted peak.  The artifact therefore gets the last word,
through the pair of pure decision functions that are this module's whole guard
API: after an attempt's emit, the emitted true peak and loudness are measured
seek-free, :func:`guard_next_ceiling` returns the ceiling the one re-encode round
owes (the overshoot plus :data:`TP_GUARD_MARGIN_DB` below the ceiling that
produced it, for at most :data:`TP_GUARD_MAX_ROUNDS` round), and
:func:`select_leveled_attempt` picks which attempt ships -- hard true peak first
(:meth:`LeveledAttempt.hard_tp_ok`), then the loudness gates, then the lowest
emitted true peak, the nominal attempt when nothing clears them.

That round is a *re-encode*, not a re-convergence.  The ride PCM is already
correct, so the guard re-runs only the limiter, the codec and the mux, over the
bytes the nominal emit consumed -- ``run_ride``'s ``pcm_path`` tee retains them
(:func:`build_reencode_args`, :func:`run_reencode`) -- and the bound is therefore
one round whose cost is seconds, not a second full ride.  The emitted true peak is
best effort at :data:`TP_GUARD_TARGET_DBTP`; the *hard* gate
(:data:`TP_GUARD_HARD_DBTP` on the emit, plus no decoded sample over 0 dBFS) is
the guarantee, and when no attempt clears it the caller emits once more at
:data:`TP_GUARD_LAST_RESORT_DBTP` (:func:`needs_last_resort`) and ships that with
an error line.  The caller owns the ride, the encode and the measurement; this
module never spawns a process for the guard and never logs.  The trigger rate and
the time it costs are counted in the unit report.

The gap cap is not a leveler for room tone
------------------------------------------
:func:`gap_cap` exists so the ride cannot lift a quiet room to target -- that is
how a meeting recording ends up sounding like a compressor pumping between
speakers.  It is kept, and it is known not to be sufficient: U25 measured a
``+13.698 dB`` lift on 4D36's quietest gap.  Recorded as a known beta.10
limitation rather than hidden; see the unit's report.

Failure is a degrade, never a channel outage
--------------------------------------------
Every failure inside the ride -- numpy absent, an FFmpeg that will not start, a
pass that exits non-zero or times out, an ebur128 series that cannot be parsed
-- raises :class:`LoudnessRideError`, which the preparer catches and turns into
ONE warning plus the pre-U25 single-pass ``loudnorm`` conform.  The channel
airs; only the leveling is missing.  This mirrors ``_measure_loudnorm_metadata``'s
existing degrade contract (U20), and a degraded artifact is never promoted into
the whole-asset conform cache.  Cancellation is not a failure: it raises
:class:`LoudnessRideCancelledError` and is re-raised as a shutdown signal.
"""

from __future__ import annotations

import contextlib
import importlib
import math
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from civiccast.egress.models import CanonicalProfile, EgressSourceSegment

__all__ = [
    "DIGITAL_SILENCE",
    "TP_GUARD_HARD_DBTP",
    "TP_GUARD_LAST_RESORT_DBTP",
    "TP_GUARD_MARGIN_DB",
    "TP_GUARD_MAX_ROUNDS",
    "TP_GUARD_TARGET_DBTP",
    "LeveledAttempt",
    "LeveledSelection",
    "LoudnessRideCancelledError",
    "LoudnessRideError",
    "LoudnessRideUnavailableError",
    "RideCurve",
    "RideParams",
    "RideRender",
    "RideRunner",
    "build_encode_sink_args",
    "build_measure_sink_args",
    "build_reencode_args",
    "build_source_series_args",
    "build_video_from_source_args",
    "canonical_video_filter",
    "combine",
    "converge",
    "correction_curve",
    "curve_stats",
    "gain_curve",
    "gap_cap",
    "gated_loudness",
    "guard_ceiling_dbtp",
    "guard_next_ceiling",
    "limit_value",
    "limiter_filter",
    "needs_last_resort",
    "parse_ebur128_series",
    "parse_integrated_lufs",
    "resample_filter",
    "run_reencode",
    "run_ride",
    "select_leveled_attempt",
    "slew_limit",
    "sliding_levels",
    "to_arrays",
]

#: ebur128 emits one momentary block per 100 ms.
BLOCK_STEP_S = 0.1

#: ebur128's absolute gate (EBU R128 / ITU-R BS.1770-4).
SILENCE_FLOOR_LUFS = -70.0

#: The relative gate, measured from the window's own ungated loudness.
RELATIVE_GATE_LU = -10.0

#: What a block that ebur128 reports as ``nan``/``-inf`` (digital silence)
#: becomes here: far below any gate, and finite so the arithmetic stays real.
DIGITAL_SILENCE = -1e9

#: 65536 frames of float32 stereo = 1.365 s = 512 KiB, the largest allocation
#: the ride makes for audio.  Peak memory is therefore a function of this
#: constant and the curve's length, never of how long the asset is -- that is
#: the bounded-memory requirement, and it is why a 2.5 h asset and an 8 s asset
#: ride at the same resident cost.
CHUNK_FRAMES = 65536

#: The children are dropped below normal priority so a ride (foreground,
#: background warm, or a second channel's) can never outrank an on-air encoder.
_BELOW_NORMAL_PRIORITY_CLASS = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_RE_I = re.compile(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", re.M)
_RE_SERIES = re.compile(
    r"\]\s*t:\s*([\d.]+)\s+.*?M:\s*(-?[\d.]+|nan|-inf)\s+S:\s*(-?[\d.]+|nan|-inf)"
)


class LoudnessRideError(RuntimeError):
    """The ride could not produce a leveled program.  Callers degrade."""


class LoudnessRideCancelledError(LoudnessRideError):
    """The ride was cancelled -- a shutdown/pause signal, not a failure."""


class LoudnessRideUnavailableError(LoudnessRideError):
    """The ride cannot run in this installation (numpy is not importable)."""


@dataclass(frozen=True)
class RideParams:
    """Every number the ride obeys, in one reviewable place.

    The defaults are the U25 round-5/Q12 chain exactly; a caller that wants a
    different ride changes this object, not the code.
    """

    target_lufs: float
    sample_rate: int = 48_000
    channels: int = 2

    #: The ride's own follow window.  Short enough to track a speaker change,
    #: long enough that it does not chase syllables.
    window_s: float = 45.0
    #: The curve's grid: one gain point per second.
    step_s: float = 1.0
    #: How far the ride may pull a passage down, and how far up.  The ceiling is
    #: deliberately high (a distant public-comment mic can be 20 LU down); the
    #: gap cap is what keeps it from lifting room tone to that ceiling.
    g_min_db: float = -6.0
    g_max_db: float = 18.0
    #: The causal rate limit on the applied gain.
    slew_db_per_s: float = 0.5

    #: Gap cap: in a passage whose emitted momentary loudness is below the
    #: absolute gate, or more than ``gap_rel_lu`` under its own window's gated
    #: loudness, the gain is capped here.
    gap_cap_db: float = 8.0
    gap_rel_lu: float = 20.0
    gap_abs_lufs: float = SILENCE_FLOOR_LUFS

    #: How far one iteration's correction curve may move the gain.
    correction_bound_db: float = 30.0
    #: Loop bounds.  ``stop_lu`` is the whole-program error that ends the loop;
    #: ``slope_floor`` floors the measured limiter slope (round 5/6 measured
    #: 0.521-0.615 on the cells that needed correcting).
    max_iters: int = 4
    stop_lu: float = 0.1
    slope_floor: float = 0.4
    #: An iteration that improves the whole-program error by less than this is
    #: treated as converged-but-not-there and stops the loop.
    min_improvement_lu: float = 0.01

    #: The emitted TRUE-peak ceiling (dBTP) the output stage enforces, and the
    #: limiter's own parameters.  -1.5 dBTP is what the incumbent
    #: ``loudnorm ... TP=-1.5`` conform promised; this ride keeps that promise
    #: rather than the -3.0 dBFS *sample*-peak ceiling it shipped with before
    #: Q14.  ``level=0`` is load-bearing: without it ``alimiter`` normalizes the
    #: limited signal back up and undoes the trim.
    limit_dbtp: float = -1.5
    limiter_attack_ms: float = 5.0
    limiter_release_ms: float = 50.0

    #: The limiter sees a 4x-oversampled copy of the signal so that the ceiling
    #: above is a real true-peak ceiling rather than a sample-peak one -- see the
    #: module docstring.  ``resampler=None`` builds a plain ``aresample``, for a
    #: host whose FFmpeg has no soxr (the ride then fails and the caller degrades
    #: to the pre-U25 conform, which is the documented failure path).
    oversample_factor: int = 4
    resampler: str | None = "soxr"
    resampler_precision: int = 28

    #: Q10: re-apply the slew limit to the SUMMED (base + correction) curve.
    #: Both inputs already carry the limit, so without this the sum can move at
    #: up to twice the specified slew wherever base and correction move the same
    #: way.  ON by the coordinator's Q10 order.  The measured window effect is in
    #: the unit report: round 4 saw a second causal pass cost 2.6 dB of lag on
    #: EF4, and round-5's passing numbers were measured with this OFF, so the two
    #: settings are NOT interchangeable evidence.  One-line revert if the
    #: coordinator prefers the measured-behaviour default.
    slew_summed_curve: bool = True

    chunk_frames: int = CHUNK_FRAMES


# ---------------------------------------------------------------------------
# Pure functions: the gate, the curve, the cap, the slew, the sum.
# ---------------------------------------------------------------------------


def gated_loudness(levels: list[float]) -> float | None:
    """Integrated loudness of gating blocks, EBU R128 two-stage gate.

    Identical arithmetic to the acceptance measurement, so the ride and the gate
    agree by construction.  ``None`` means nothing survived the absolute gate.
    """
    kept_abs = [v for v in levels if v > SILENCE_FLOOR_LUFS]
    if not kept_abs:
        return None
    ungated = 10.0 * math.log10(sum(10.0 ** (v / 10.0) for v in kept_abs) / len(kept_abs))
    kept = [v for v in kept_abs if v > ungated + RELATIVE_GATE_LU]
    if not kept:
        return None
    return 10.0 * math.log10(sum(10.0 ** (v / 10.0) for v in kept) / len(kept))


def sliding_levels(
    blocks: list[tuple[float, float]],
    window_s: float,
    step_s: float,
) -> list[tuple[float, float | None]]:
    """Gated loudness of a ``window_s`` window centred on every ``step_s``."""
    if not blocks:
        return []
    n = len(blocks)
    half = max(1, round(window_s / 2.0 / BLOCK_STEP_S))
    span = max(1, round(step_s / BLOCK_STEP_S))
    out: list[tuple[float, float | None]] = []
    for k in range(0, n, span):
        i = min(k, n - 1)
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append((blocks[i][0], gated_loudness([v for _, v in blocks[lo:hi]])))
    return out


def slew_limit(
    curve: list[tuple[float, float]],
    slew_db_per_s: float,
    step_s: float,
) -> list[tuple[float, float]]:
    """Causal forward rate limit: the gain may move at most ``slew * step``.

    Causal on purpose: an anti-causal pass anticipates a step by dragging the new
    target backwards through the quiet run-up, attenuating material that has not
    changed yet.  A causal pass can only ever be late, never wrong in the run-up.
    """
    if not curve:
        return []
    limit = slew_db_per_s * step_s
    out = [list(p) for p in curve]
    for i in range(1, len(out)):
        d = out[i][1] - out[i - 1][1]
        if d > limit:
            out[i][1] = out[i - 1][1] + limit
        elif d < -limit:
            out[i][1] = out[i - 1][1] - limit
    return [(t, v) for t, v in out]


def gain_curve(
    levels: list[tuple[float, float | None]],
    *,
    target_lufs: float,
    g_min_db: float,
    g_max_db: float,
    slew_db_per_s: float,
    step_s: float,
) -> list[tuple[float, float]]:
    """``clamp(target - level)`` with the silence hold, then the slew limit.

    The silence hold matters: a window with nothing above the absolute gate has
    no measurable level, and dropping the gain to 0 dB there would punch a hole
    in the program at every pause.  The previous gain is carried instead.
    """
    raw: list[float] = []
    held: float | None = None
    for _, level in levels:
        if level is None:
            raw.append(0.0 if held is None else held)
            continue
        held = min(max(target_lufs - level, g_min_db), g_max_db)
        raw.append(held)
    return slew_limit(
        [(t, v) for (t, _level), v in zip(levels, raw, strict=True)], slew_db_per_s, step_s
    )


def _momentary_at(blocks: list[tuple[float, float]], t: float) -> float:
    """Momentary loudness of the block nearest ``t`` (blocks are 100 ms apart)."""
    if not blocks:
        return DIGITAL_SILENCE
    lo, hi = 0, len(blocks) - 1
    if t <= blocks[0][0]:
        return blocks[0][1]
    if t >= blocks[-1][0]:
        return blocks[-1][1]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if blocks[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    return blocks[lo][1] if (t - blocks[lo][0]) <= (blocks[hi][0] - t) else blocks[hi][1]


def gap_cap(
    curve: list[tuple[float, float]],
    blocks: list[tuple[float, float]],
    levels: list[tuple[float, float | None]],
    *,
    cap_db: float,
    rel_lu: float,
    abs_lufs: float,
    slew_db_per_s: float,
    step_s: float,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    """Cap the applied gain in the quiet gaps, then rate-limit the capping.

    A block is a *gap* when its emitted momentary -- the source's own momentary
    loudness plus the gain about to be applied -- is below the EBU R128 absolute
    gate, or more than ``rel_lu`` under the gated loudness of its own 45 s
    neighbourhood.  That is the between-speakers case: room tone, a page turn,
    the pause before the chair recognises the next speaker.  In a gap the gain is
    capped at ``cap_db`` regardless of how far below target the passage measures,
    because lifting room tone to target is how a room gets loud.

    The cap is then passed through the same causal slew limit as everything else,
    so leaving a gap is a 0.5 dB/s ramp rather than a step.  It is deliberately
    *not* applied to non-gap points: a quiet passage that is genuinely being
    spoken is exactly what the ride is for.
    """
    if not curve:
        return [], {"n_points": 0}
    capped: list[float] = []
    n_gap = n_by_abs = n_by_rel = n_capped = 0
    depth = 0.0
    for (t, g), (_, lw) in zip(curve, levels, strict=False):
        m = _momentary_at(blocks, t)
        emitted = m + g
        is_abs = m <= abs_lufs or emitted <= abs_lufs
        is_rel = lw is not None and emitted < lw - rel_lu
        if is_abs or is_rel or lw is None:
            n_gap += 1
            n_by_abs += int(is_abs)
            n_by_rel += int(is_rel and not is_abs)
            if g > cap_db:
                n_capped += 1
                depth = max(depth, g - cap_db)
                capped.append(cap_db)
                continue
        capped.append(g)
    out = slew_limit(
        [(t, v) for (t, _g), v in zip(curve, capped, strict=True)], slew_db_per_s, step_s
    )
    steps = [abs(out[i][1] - out[i - 1][1]) for i in range(1, len(out))]
    return out, {
        "n_points": len(out),
        "n_gap_points": n_gap,
        "n_gap_by_abs_gate": n_by_abs,
        "n_gap_by_relative": n_by_rel,
        "n_gap_windows_silent": sum(1 for _, lw in levels if lw is None),
        "n_gap_points_capped": n_capped,
        "cap_depth_max_db": round(depth, 3),
        "cap_db": cap_db,
        "curve_min_db": round(min(v for _, v in out), 3),
        "curve_max_db": round(max(v for _, v in out), 3),
        "post_cap_max_step_db": round(max(steps, default=0.0), 4),
        "post_cap_max_rate_db_per_s": round(max(steps, default=0.0) / step_s, 4),
    }


def correction_curve(
    blocks: list[tuple[float, float]],
    *,
    target_lufs: float,
    bound_db: float,
    window_s: float,
    slew_db_per_s: float,
    step_s: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float | None]]]:
    """``c(t) = target - L_W(t)`` of a rendered output, same window/slew/hold."""
    levels = sliding_levels(blocks, window_s=window_s, step_s=step_s)
    return gain_curve(
        levels,
        target_lufs=target_lufs,
        g_min_db=-bound_db,
        g_max_db=bound_db,
        slew_db_per_s=slew_db_per_s,
        step_s=step_s,
    ), levels


def combine(
    base: list[tuple[float, float]],
    corr: list[tuple[float, float]],
    *,
    g_min_db: float,
    g_max_db: float,
    slew_db_per_s: float | None = None,
    step_s: float = 1.0,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    """Sum two curves on the base grid, clamp the sum, optionally re-slew it.

    Both inputs already carry the slew limit, so the default recipe is
    add -> clamp.  ``slew_db_per_s`` re-applies the limit to the sum as well
    (U25 Q10); it is off by default because the shipped numbers were measured
    without it -- see :attr:`RideParams.slew_summed_curve`.
    """
    if not corr:
        return base, {"n_points": len(base), "n_corr_points": 0}
    corr_vals = [interp(corr, t) for t, _ in base]
    summed = [(t, g + c) for (t, g), c in zip(base, corr_vals, strict=True)]
    out = [(t, min(max(v, g_min_db), g_max_db)) for t, v in summed]
    if slew_db_per_s is not None:
        out = slew_limit(out, slew_db_per_s, step_s)
    steps = [abs(out[i][1] - out[i - 1][1]) for i in range(1, len(out))]
    return out, {
        "n_points": len(out),
        "n_corr_points": len(corr),
        "sum_min_db": round(min((v for _, v in summed), default=0.0), 3),
        "sum_max_db": round(max((v for _, v in summed), default=0.0), 3),
        "clamped_below_g_min": sum(1 for _, v in summed if v < g_min_db - 1e-9),
        "clamped_above_g_max": sum(1 for _, v in summed if v > g_max_db + 1e-9),
        "sum_max_step_db": round(max(steps, default=0.0), 4),
        "sum_max_rate_db_per_s": round(max(steps, default=0.0) / step_s, 4),
        "re_slewed": slew_db_per_s is not None,
        "corr_min_db": round(min((v for _, v in corr), default=0.0), 3),
        "corr_max_db": round(max((v for _, v in corr), default=0.0), 3),
    }


def interp(curve: list[tuple[float, float]], t: float) -> float:
    """Linear interpolation, flat outside the ends."""
    if not curve:
        return 0.0
    if t <= curve[0][0]:
        return curve[0][1]
    if t >= curve[-1][0]:
        return curve[-1][1]
    lo, hi = 0, len(curve) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if curve[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, v0 = curve[lo]
    t1, v1 = curve[hi]
    return v0 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def curve_stats(
    curve: list[tuple[float, float]], tag: str, g_min_db: float, g_max_db: float
) -> dict[str, Any]:
    """Range/rate summary of one applied curve, for the diagnostics log."""
    gains = [g for _, g in curve]
    if not gains:
        return {"tag": tag, "n_points": 0}
    steps = [abs(gains[i] - gains[i - 1]) for i in range(1, len(gains))]
    return {
        "tag": tag,
        "n_points": len(gains),
        "curve_min_db": round(min(gains), 3),
        "curve_max_db": round(max(gains), 3),
        "curve_mean_db": round(sum(gains) / len(gains), 3),
        "hits_g_max": sum(1 for g in gains if g >= g_max_db - 1e-9),
        "hits_g_min": sum(1 for g in gains if g <= g_min_db + 1e-9),
        "max_step_db": round(max(steps, default=0.0), 4),
        "max_rate_db_per_s": round(max(steps, default=0.0), 4),
    }


def to_arrays(curve: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Split a curve into its time and gain sequences (the numpy multiply's input)."""
    return [t for t, _ in curve], [g for _, g in curve]


# ---------------------------------------------------------------------------
# FFmpeg grammar.  Pure builders -- no process, no filesystem.
# ---------------------------------------------------------------------------


def limit_value(limit_dbtp: float) -> float:
    """``alimiter``'s ``limit`` is linear amplitude, not dB."""
    return float(10.0 ** (limit_dbtp / 20.0))


def resample_filter(target_hz: int, params: RideParams) -> str:
    """One ``aresample`` leg of the oversampled output stage.

    soxr at ``precision=28`` is what the shipped build carries (the station's
    bundled FFmpeg is resolved by ``civiccast.stream._ffmpeg``); ``precision`` is
    a soxr option, so it is only emitted when a resampler is named.
    """
    if not params.resampler:
        return f"aresample={target_hz}"
    return (
        f"aresample={target_hz}:resampler={params.resampler}:precision={params.resampler_precision}"
    )


def limiter_filter(params: RideParams) -> str:
    """The true-peak-aware output stage: 4x up, limit, 4x down.

    ``alimiter`` is a sample-peak limiter -- it cannot see the inter-sample peaks
    a codec will later produce, which is why a sample-peak ceiling let BIG emit
    +2.754 dBFS samples (U25 Q14).  Oversampling puts those peaks *between* the
    samples the limiter sees, so the ceiling it enforces is a true-peak ceiling.

    ``asc=0`` keeps the lookahead off and ``level=0`` is what stops it
    normalizing the trimmed signal back up; both are load-bearing.
    """
    return ",".join(
        [
            resample_filter(params.sample_rate * params.oversample_factor, params),
            (
                f"alimiter=limit={limit_value(params.limit_dbtp):.6f}"
                f":attack={params.limiter_attack_ms:g}"
                f":release={params.limiter_release_ms:g}:asc=0:level=0"
            ),
            resample_filter(params.sample_rate, params),
        ]
    )


def build_source_series_args(
    *,
    source_path: Path,
    segment: EgressSourceSegment | None,
    params: RideParams,
    threads: int | None = None,
) -> list[str]:
    """One pass over the SOURCE window: per-100 ms momentary loudness, nothing else.

    This is where the base curve's levels and the gap cap's blocks come from.
    ``-ss``/``-t`` mirror ``build_conform_source_args``: a trimmed segment
    analyzes exactly its own window, ``segment=None`` analyzes the whole asset.
    """
    args = ["-hide_banner", "-loglevel", "info"]
    if threads is not None:
        args.extend(["-threads", str(threads)])
    if segment is not None and segment.inpoint_seconds is not None:
        args.extend(["-ss", f"{segment.inpoint_seconds:g}"])
    args.extend(["-i", str(source_path)])
    if segment is not None:
        args.extend(["-t", f"{segment.duration_seconds:g}"])
    args.extend(["-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    return args


def build_decoder_args(
    *,
    source_path: Path,
    segment: EgressSourceSegment | None,
    params: RideParams,
    threads: int | None = None,
) -> list[str]:
    """Decode the segment's audio at the conformed rate, as raw float32.

    Output goes to this process's stdout; the ride feeds it, one chunk at a
    time, into the sink's stdin.  ``-vn`` is what keeps the pipe PCM-only -- the
    video is decoded once, later, by the video pass.
    """
    args = ["-hide_banner", "-loglevel", "error"]
    if threads is not None:
        args.extend(["-threads", str(threads)])
    if segment is not None and segment.inpoint_seconds is not None:
        args.extend(["-ss", f"{segment.inpoint_seconds:g}"])
    args.extend(["-i", str(source_path)])
    if segment is not None:
        args.extend(["-t", f"{segment.duration_seconds:g}"])
    args.extend(
        [
            "-vn",
            "-ar",
            str(params.sample_rate),
            "-ac",
            str(params.channels),
            "-f",
            "f32le",
            "-",
        ]
    )
    return args


def _pcm_input_args(*, params: RideParams, from_file: Path | None = None) -> list[str]:
    """The raw-float32 input leg, from ``-f f32le`` through the ``-i`` operand.

    ``from_file=None`` is the pipe a ride feeds (both live sinks); a path is bytes
    a previous pass already wrote -- the guard's re-encode, which must see the
    very samples the nominal emit consumed.  Every f32le reader in this module
    builds its leg here, so the three cannot drift in rate or channel count; a
    drift there would silently reshape the PCM rather than fail.
    """
    return [
        "-f",
        "f32le",
        "-ar",
        str(params.sample_rate),
        "-ac",
        str(params.channels),
        "-i",
        "pipe:0" if from_file is None else str(from_file),
    ]


def _encode_sink_tail(
    output_path: Path,
    trim_db: float,
    *,
    params: RideParams,
    profile: CanonicalProfile,
) -> list[str]:
    """Everything the emitted-audio sink does after its input, in one place.

    Factored so the guard's re-encode round IS this encode, option for option: a
    change to the codec, bitrate, rate, channel count or container reaches both
    shapes or neither.
    """
    parts = [f"volume={trim_db:.3f}dB", limiter_filter(params)]
    return [
        "-af",
        ",".join(parts),
        "-c:a",
        profile.audio_codec,
        "-b:a",
        f"{profile.audio_bitrate_kbps}k",
        "-ar",
        str(profile.audio_sample_rate),
        "-ac",
        str(profile.audio_channels),
        "-f",
        "mpegts",
        str(output_path),
    ]


def build_measure_sink_args(trim_db: float | None, *, params: RideParams) -> list[str]:
    """Sink that measures the ridden PCM: trim, limiter, ebur128, discard.

    ``trim_db=None`` is the ride-only pass: no trim and no limiter, which is how
    the level the ride alone produced is measured before a trim is chosen.
    """
    if trim_db is None:
        parts = ["ebur128=peak=true"]
    else:
        parts = [f"volume={trim_db:.3f}dB", limiter_filter(params), "ebur128=peak=true"]
    return [
        "-hide_banner",
        "-loglevel",
        "info",
        *_pcm_input_args(params=params),
        "-af",
        ",".join(parts),
        "-f",
        "null",
        "-",
    ]


def build_encode_sink_args(
    output_path: Path,
    trim_db: float,
    *,
    params: RideParams,
    profile: CanonicalProfile,
) -> list[str]:
    """Sink that writes the real emitted audio: the profile's codec, in MPEG-TS.

    The audio parameters come from the canonical profile, because the video pass
    later stream-copies this stream into the final program: whatever bitrate,
    rate or channel count is written here IS what the program carries, and
    re-encoding it there would be a second lossy generation.
    """
    return [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        *_pcm_input_args(params=params),
        *_encode_sink_tail(output_path, trim_db, params=params, profile=profile),
    ]


def build_reencode_args(
    pcm_path: Path,
    output_path: Path,
    *,
    trim_db: float,
    params: RideParams,
    profile: CanonicalProfile,
) -> list[str]:
    """The guard's re-encode round: the emitted-audio sink, fed from a PCM file.

    Answer 11's guard round is not a re-convergence -- the ride PCM is already
    correct -- so it is the nominal encode with a file for an input and nothing
    else different.  ``params.limit_dbtp`` is the ceiling this round pulls the
    only available lever to: the limiter's ``limit`` (:func:`limiter_filter`).
    """
    return [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        *_pcm_input_args(params=params, from_file=pcm_path),
        *_encode_sink_tail(output_path, trim_db, params=params, profile=profile),
    ]


def canonical_video_filter(profile: CanonicalProfile) -> str:
    """The canonical scale/pad/rate/format chain, in one place.

    Shared with ``preparer.build_conform_source_args`` so the two conform shapes
    cannot drift apart: the video pass below must produce exactly the frames the
    single-pass conform produced.
    """
    return (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
        f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={profile.fps},format=yuv420p"
    )


def build_video_from_source_args(
    *,
    source_path: Path,
    audio_path: Path,
    output_path: Path,
    segment: EgressSourceSegment | None,
    profile: CanonicalProfile,
    threads: int | None = None,
) -> list[str]:
    """Final pass: video re-encoded from the SOURCE, audio stream-copied.

    The video is taken from the original file (input 0) and the ride's audio
    from the ride's own MPEG-TS (input 1), so the emitted program has exactly one
    encode of each stream.  ``-c:a copy`` is what makes the ride's work survive
    into the program untouched -- any audio filter here would fight the ride.

    No ``-b:a``/``-ar``/``-ac`` may be emitted alongside ``-c:a copy``: they are
    input-format options for an encoder that is not running, and FFmpeg treats
    them as a contradiction.  The stream's parameters were fixed by the ride's
    encode sink from the same profile.
    """
    args = ["-hide_banner", "-loglevel", "warning"]
    if segment is not None and segment.inpoint_seconds is not None:
        args.extend(["-ss", f"{segment.inpoint_seconds:g}"])
    args.extend(["-i", str(source_path)])
    if segment is not None:
        args.extend(["-t", f"{segment.duration_seconds:g}"])
    args.extend(["-i", str(audio_path)])
    args.extend(["-map", "0:v:0", "-map", "1:a:0", "-vf", canonical_video_filter(profile)])
    if threads is not None:
        args.extend(["-threads", str(threads)])
    args.extend(
        [
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-g",
            str(profile.gop_size),
            "-c:a",
            "copy",
            "-f",
            profile.container,
            str(output_path),
        ]
    )
    return args


def ride_audio_path(final_path: Path) -> Path:
    """Where the ride's intermediate audio lives: beside its final artifact.

    Same directory as the output on purpose -- a temp on another volume turns
    the promotion's ``rename`` into a copy, and the cache directory is the one
    place the conform is allowed to write.
    """
    return final_path.with_name(final_path.name + ".ride-audio.ts")


# ---------------------------------------------------------------------------
# Parsers for ebur128's own output.
# ---------------------------------------------------------------------------


def parse_integrated_lufs(stderr: str) -> float | None:
    """The summary ``I:`` line ebur128 prints at the end of a pass.

    ``-loglevel info`` prints one ``I:`` per 100 ms *inside* a per-frame line and
    the summary on a line of its own; the anchored pattern picks up only the
    latter.  ``None`` means the pass produced no summary -- the caller treats
    that as a failed measurement.
    """
    matches = _RE_I.findall(stderr)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def parse_ebur128_series(stderr: str) -> list[tuple[float, float]]:
    """Per-100 ms ``(t, momentary)`` pairs; digital silence becomes a sentinel."""
    out: list[tuple[float, float]] = []
    for t, m, _s in _RE_SERIES.findall(stderr):
        out.append((float(t), DIGITAL_SILENCE if m in ("nan", "-inf") else float(m)))
    return out


# ---------------------------------------------------------------------------
# The chunked multiply, between two FFmpeg processes.
# ---------------------------------------------------------------------------


def _load_numpy() -> Any:
    """Import numpy lazily and name the failure in the operator's terms.

    numpy is not a declared dependency of this package (it arrives with the
    native app closure, via ctranslate2/onnxruntime), and this module must not
    make it one: a station without it should keep conforming sources the way it
    did before U25, not fail to import ``civiccast.egress``.
    """
    try:
        return importlib.import_module("numpy")
    except Exception as exc:  # ImportError, or a broken install's anything
        raise LoudnessRideUnavailableError(
            "the U25 speech-leveling ride needs numpy, which is not importable in "
            f"this installation ({type(exc).__name__}: {exc})"
        ) from exc


def _ffmpeg_binary() -> str:
    """Resolve FFmpeg through ``civiccast.stream._ffmpeg``.

    Imported inside the function so this module stays importable (and its pure
    functions testable) on a host with no FFmpeg at all, and so tests that
    monkeypatch ``_ffmpeg._ffmpeg_path`` control the ride's binary too.
    """
    from civiccast.stream import _ffmpeg

    return _ffmpeg._ffmpeg_path()


@dataclass(frozen=True)
class RideRender:
    """What one ride pass produced.  The measurement lives in ``stderr``."""

    frames: int
    audio_seconds: float
    wall_s: float
    stderr: str


def run_ride(
    *,
    decoder_args: list[str],
    sink_args: list[str],
    curve: list[tuple[float, float]],
    params: RideParams,
    pcm_path: Path | None = None,
    cancel_event: threading.Event | None = None,
    timeout_s: float | None = None,
) -> RideRender:
    """Feed decoded PCM through the gain curve into the sink, one chunk at a time.

    The decoder writes float32 PCM to a pipe; each chunk is multiplied by the
    curve interpolated per sample and written to the sink's stdin.  Nothing
    larger than one chunk is ever held, so peak memory does not grow with asset
    length.

    ``pcm_path`` tees those post-curve bytes to a file as they pass -- the same
    chunk object the sink receives, so the copy is bit-identical by construction
    rather than by a second render that would have to reproduce it.  It is
    ``None`` on the nominal path, which then pays nothing; when it is given the
    caller owns the file (this function never deletes it), because its whole
    purpose is to outlive the call and feed :func:`build_reencode_args` if the
    emitted artifact turns out hot.

    The sink's stderr is where the measurement lives, and ebur128 writes a block
    line every 100 ms -- ~10 MB over a 2.5 h asset.  A pipe nobody drains while
    the ride is running would fill and deadlock both processes, so it goes to a
    file and is read back at the end.

    Raises :class:`LoudnessRideCancelledError` on cancellation, and
    :class:`LoudnessRideError` on a timeout or a non-zero exit from either child.
    """
    np = _load_numpy()
    gt, gv = to_arrays(curve)
    ffmpeg = _ffmpeg_binary()
    bytes_per_frame = params.channels * 4
    bytes_per_chunk = params.chunk_frames * bytes_per_frame

    # Opened before either child starts: an unwritable tee is this call's own
    # failure and must not leave a decoder running behind it.
    pcm_file: BinaryIO | None = pcm_path.open("wb") if pcm_path is not None else None

    t_start = time.perf_counter()
    decoder = subprocess.Popen(  # noqa: S603 - explicit list, resolved binary, shell=False
        [ffmpeg, *decoder_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=_CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS,
    )
    err_file = tempfile.NamedTemporaryFile(  # noqa: SIM115 - held open for the child
        prefix="civiccast-ride-", suffix=".log", delete=False
    )
    err_path = Path(err_file.name)
    sink: subprocess.Popen[bytes] | None = None
    frames_done = 0
    cancelled = False
    timed_out = False
    try:
        sink = subprocess.Popen(  # noqa: S603 - explicit list, resolved binary, shell=False
            [ffmpeg, *sink_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=err_file,
            creationflags=_CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS,
        )
        assert decoder.stdout is not None
        assert sink.stdin is not None
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if timeout_s is not None and time.perf_counter() - t_start > timeout_s:
                timed_out = True
                break
            raw = decoder.stdout.read(bytes_per_chunk)
            if not raw:
                break
            if len(raw) % bytes_per_frame:
                raw = raw[: len(raw) - len(raw) % bytes_per_frame]
            block = np.frombuffer(raw, dtype="<f4").reshape(-1, params.channels).copy()
            n = block.shape[0]
            t = (frames_done + np.arange(n, dtype=np.float64)) / params.sample_rate
            gain = np.interp(t, gt, gv)
            block *= (10.0 ** (gain / 20.0)).astype(np.float32)[:, None]
            payload = block.astype("<f4").tobytes()
            if pcm_file is not None:
                pcm_file.write(payload)
            sink.stdin.write(payload)
            frames_done += n
    except BrokenPipeError:
        # The sink died first (a bad filter, a bad codec, a full disk).  Its
        # exit code below is the real error; the broken pipe is a symptom.
        pass
    finally:
        for stream in (decoder.stdout, sink.stdin if sink is not None else None):
            if stream is not None:
                with contextlib.suppress(BrokenPipeError, OSError):
                    stream.close()
        if pcm_file is not None:
            with contextlib.suppress(OSError):
                pcm_file.close()
        if cancelled or timed_out:
            for proc in (sink, decoder):
                if proc is not None and proc.poll() is None:
                    proc.kill()
        # Drain the decoder's stderr into its own void so a chatty failure
        # cannot leave the pipe full and the wait below hanging.
        if decoder.stderr is not None:
            decoder.stderr.close()
        err_file.close()

    decoder.wait()
    sink_rc = sink.wait() if sink is not None else -1
    try:
        err = err_path.read_text(encoding="utf-8", errors="replace")
    finally:
        err_path.unlink(missing_ok=True)

    if cancelled:
        raise LoudnessRideCancelledError("the speech-leveling ride was cancelled")
    if timed_out:
        raise LoudnessRideError(f"the speech-leveling ride timed out after {timeout_s:g}s")
    if decoder.returncode != 0:
        raise LoudnessRideError(
            f"the ride's source decode exited {decoder.returncode}; "
            f"last output: {err.strip()[-400:]!r}"
        )
    if sink_rc != 0:
        raise LoudnessRideError(
            f"the ride's audio sink exited {sink_rc}; last output: {err.strip()[-400:]!r}"
        )
    return RideRender(
        frames=frames_done,
        audio_seconds=round(frames_done / params.sample_rate, 3),
        wall_s=round(time.perf_counter() - t_start, 2),
        stderr=err,
    )


def run_reencode(
    *,
    pcm_path: Path,
    output_path: Path,
    trim_db: float,
    params: RideParams,
    profile: CanonicalProfile,
    timeout_s: float | None = None,
) -> RideRender:
    """Re-encode retained ride PCM once: limiter, codec, mux -- no ride, no curve.

    This is the guard's whole round, as a process.  The samples are the ones the
    nominal emit already consumed, so this pass cannot move the loudness the
    convergence settled on; the only thing it changes is what the limiter and the
    codec do to a hot signal, which is exactly the lever answer 11 asks it to
    pull.  One input, one output, no pipe and no chunk loop -- FFmpeg reads the
    file itself.

    ``frames`` and ``audio_seconds`` are zero: the caller measures the artifact it
    just wrote (that measurement is the guard's input), and this function reports
    only the wall time and the child's stderr, so the decision stays with the pure
    functions.

    Raises :class:`LoudnessRideError` on a timeout or a non-zero exit.
    """
    ffmpeg = _ffmpeg_binary()
    argv = [
        ffmpeg,
        *build_reencode_args(
            pcm_path, output_path, trim_db=trim_db, params=params, profile=profile
        ),
    ]
    t_start = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 - explicit list, resolved binary, shell=False
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
            creationflags=_CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS,
        )
    except subprocess.TimeoutExpired as exc:
        raise LoudnessRideError(f"the guard's re-encode timed out after {timeout_s:g}s") from exc
    wall_s = round(time.perf_counter() - t_start, 2)
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise LoudnessRideError(
            f"the guard's re-encode exited {proc.returncode}; "
            f"last output: {stderr.strip()[-400:]!r}"
        )
    return RideRender(frames=0, audio_seconds=0.0, wall_s=wall_s, stderr=stderr)


# ---------------------------------------------------------------------------
# The converge loop.  Takes a render callable, so the loop itself is pure.
# ---------------------------------------------------------------------------

#: ``render(curve, trim_db)`` -> one ride pass.  ``trim_db=None`` is the
#: ride-only pass (no trim, no limiter).
RenderFn = Callable[[list[tuple[float, float]], "float | None"], RideRender]


class RideRunner(Protocol):
    """How the preparer runs one ride pass.

    Declared so the preparer can take a substitute runner (tests substitute a
    canned stderr; the installed station takes :func:`run_ride`) without losing
    the signature -- the same shape ``FfmpegRunner`` gives ``run_ffmpeg``.
    """

    def __call__(
        self,
        *,
        decoder_args: list[str],
        sink_args: list[str],
        curve: list[tuple[float, float]],
        params: RideParams,
        pcm_path: Path | None = None,
        cancel_event: threading.Event | None = None,
        timeout_s: float | None = None,
    ) -> RideRender: ...


@dataclass(frozen=True)
class RideCurve:
    """The converged ride: what to apply, and the evidence for why."""

    curve: list[tuple[float, float]]
    trim_db: float
    iterations: int
    converged: bool
    stop_reason: str
    diagnostics: list[dict[str, Any]]


def converge(
    params: RideParams,
    *,
    source_blocks: list[tuple[float, float]],
    source_levels: list[tuple[float, float | None]],
    render: RenderFn,
) -> RideCurve:
    """Iterate the ride until the emitted whole-program level is at target.

    ``source_blocks``/``source_levels`` are this window's own ebur128 series and
    window levels (see :func:`build_source_series_args`); ``render`` runs one
    ride pass.  Returns the applied curve and the trim to emit with, plus one
    diagnostics record per iteration.

    Raises :class:`LoudnessRideError` when the ride-only pass measures no
    integrated loudness at all -- a window the ride cannot level, whose caller
    must fall back rather than emit whatever the curve happened to be.
    """
    base = gain_curve(
        source_levels,
        target_lufs=params.target_lufs,
        g_min_db=params.g_min_db,
        g_max_db=params.g_max_db,
        slew_db_per_s=params.slew_db_per_s,
        step_s=params.step_s,
    )
    applied, cap_diag = gap_cap(
        base,
        source_blocks,
        source_levels,
        cap_db=params.gap_cap_db,
        rel_lu=params.gap_rel_lu,
        abs_lufs=params.gap_abs_lufs,
        slew_db_per_s=params.slew_db_per_s,
        step_s=params.step_s,
    )
    diagnostics: list[dict[str, Any]] = [
        {"stage": "base", **curve_stats(base, "base", params.g_min_db, params.g_max_db)},
        {"stage": "base+cap", **cap_diag},
    ]

    trim0 = 0.0
    trim1 = 0.0
    slope: float | None = None
    prev_err: float | None = None
    converged = False
    stop_reason = f"stopped at max_iters={params.max_iters}"

    for iteration in range(1, params.max_iters + 1):
        ride_only = render(applied, None)
        level_a = parse_integrated_lufs(ride_only.stderr)
        if level_a is None:
            raise LoudnessRideError(
                f"iteration {iteration}: the ride-only pass measured no integrated loudness"
            )
        trim0 = params.target_lufs - level_a

        with_trim0 = render(applied, trim0)
        level_b = parse_integrated_lufs(with_trim0.stderr)
        err_b = (params.target_lufs - level_b) if level_b is not None else 0.0
        slope_used = 1.0 if slope is None else max(slope, params.slope_floor)
        trim1 = trim0 + err_b / slope_used

        with_trim1 = render(applied, trim1)
        level_c = parse_integrated_lufs(with_trim1.stderr)
        err_c = None if level_c is None else level_c - params.target_lufs
        measured_slope: float | None = None
        if level_b is not None and level_c is not None and abs(trim1 - trim0) > 1e-6:
            measured_slope = (level_c - level_b) / (trim1 - trim0)
            slope = measured_slope

        diagnostics.append(
            {
                "stage": f"iter{iteration}",
                "iteration": iteration,
                "level_ride_only": level_a,
                "trim0_db": round(trim0, 4),
                "level_trim0": level_b,
                "slope_used": round(slope_used, 4),
                "slope_measured": None if measured_slope is None else round(measured_slope, 4),
                "trim1_db": round(trim1, 4),
                "level_trim1": level_c,
                "error_db": None if err_c is None else round(err_c, 4),
                "ride_wall_s": [ride_only.wall_s, with_trim0.wall_s, with_trim1.wall_s],
                "curve": curve_stats(applied, f"iter{iteration}", params.g_min_db, params.g_max_db),
            }
        )

        if err_c is not None and abs(err_c) <= params.stop_lu:
            converged = True
            stop_reason = f"whole-program error <= {params.stop_lu:g} LU"
            break
        if (
            prev_err is not None
            and err_c is not None
            and abs(err_c) >= abs(prev_err) - params.min_improvement_lu
        ):
            stop_reason = "no improvement between iterations"
            break
        prev_err = err_c
        if iteration >= params.max_iters:
            break

        correction, _ = correction_curve(
            parse_ebur128_series(with_trim1.stderr),
            target_lufs=params.target_lufs,
            bound_db=params.correction_bound_db,
            window_s=params.window_s,
            slew_db_per_s=params.slew_db_per_s,
            step_s=params.step_s,
        )
        applied, combine_diag = combine(
            applied,
            correction,
            g_min_db=params.g_min_db,
            g_max_db=params.g_max_db,
            slew_db_per_s=params.slew_db_per_s if params.slew_summed_curve else None,
            step_s=params.step_s,
        )
        applied, _ = gap_cap(
            applied,
            source_blocks,
            source_levels,
            cap_db=params.gap_cap_db,
            rel_lu=params.gap_rel_lu,
            abs_lufs=params.gap_abs_lufs,
            slew_db_per_s=params.slew_db_per_s,
            step_s=params.step_s,
        )
        diagnostics[-1]["combine"] = combine_diag

    diagnostics.append(
        {
            "stage": "done",
            "iterations": len([d for d in diagnostics if d.get("stage", "").startswith("iter")]),
            "converged": converged,
            "stop_reason": stop_reason,
            "final_trim_db": round(trim1, 4),
            "curve": curve_stats(applied, "final", params.g_min_db, params.g_max_db),
        }
    )
    return RideCurve(
        curve=applied,
        trim_db=trim1,
        iterations=len([d for d in diagnostics if str(d.get("stage", "")).startswith("iter")]),
        converged=converged,
        stop_reason=stop_reason,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# The emitted-artifact guard: the artifact gets the last word on its own TP.
# ---------------------------------------------------------------------------

#: The emitted true peak the artifact must not exceed (dBTP).
TP_GUARD_TARGET_DBTP = -1.0

#: Headroom the guard leaves under that target when it lowers the ceiling.  Not
#: slack in the contract -- the artifact still has to measure at or below the
#: target -- it is room for the *next* decode, whose resampler is not the one the
#: guard measured with.
TP_GUARD_MARGIN_DB = 0.3


def guard_ceiling_dbtp(current_dbtp: float, emitted_dbtp: float) -> float | None:
    """The ceiling to re-emit with, or ``None`` when the emit is already lawful.

    The correction is the overshoot plus the margin: the ceiling moves down by
    however far the emit missed the target, plus :data:`TP_GUARD_MARGIN_DB`.
    """
    if emitted_dbtp <= TP_GUARD_TARGET_DBTP:
        return None
    overshoot = emitted_dbtp - TP_GUARD_TARGET_DBTP
    return round(current_dbtp - (overshoot + TP_GUARD_MARGIN_DB), 3)


# ---------------------------------------------------------------------------
# The guard (answer 11: one re-encode round, then a last resort)
# ---------------------------------------------------------------------------

#: The hard true-peak gate the artifact must clear: no decoded sample above
#: 0 dBFS, and an emitted true peak at or below this.  This is the guarantee;
#: :data:`TP_GUARD_TARGET_DBTP` below is best effort, because the emitted true
#: peak is the codec's own overshoot rather than the limiter's ceiling, so a hot
#: asset can miss the target through no fault of the limiter's.
TP_GUARD_HARD_DBTP = 0.0

#: The limiter ceiling of the last resort, used only when no attempt cleared the
#: hard gate.  Four dB under the target leaves the codec room it has been measured
#: to need; an artifact emitted here airs quieter than target to stay lawful, so
#: the caller reports it with an error line rather than a warning.
TP_GUARD_LAST_RESORT_DBTP = -4.0

#: Re-encode rounds a hot artifact may spend.  One.  The round re-runs only the
#: limiter, the codec and the mux over the ride PCM the nominal emit already
#: consumed (:func:`build_reencode_args`), so it costs seconds instead of a second
#: full ride -- and U25 round 7 measured a lowered ceiling buying 0.00 dB of
#: emitted true peak on BIG, so a second round would buy cost, not compliance.
TP_GUARD_MAX_ROUNDS = 1


@dataclass(frozen=True)
class LeveledAttempt:
    """One emitted attempt: the ceiling it ran at, and what it emitted.

    ``emitted_dbtp``/``emitted_lufs`` are ``None`` when the emitted artifact could
    not be measured.  ``worst_window_err_lu`` is the largest absolute deviation of
    any gated window from the target and ``whole_err_lu`` the signed whole-program
    error; both are ``None`` when the loudness measurement failed.  The loudness
    errors are the attempt's *own* artifact's, not the loop's pre-encode probe --
    the gates are judged on what airs.

    ``decoded_peak_dbfs`` is the hottest sample a decode of the artifact found.
    It is the second leg of the hard gate and is ``None`` when the artifact was
    not scanned, which -- like a missing loudness measurement -- cannot clear the
    gate it cannot evidence.
    """

    round_index: int
    limit_dbtp: float
    emitted_dbtp: float | None
    emitted_lufs: float | None
    worst_window_err_lu: float | None
    whole_err_lu: float | None
    wall_s: float
    decoded_peak_dbfs: float | None = None

    def loudness_ok(self, *, window_tol_lu: float, whole_tol_lu: float) -> bool:
        """Whether both loudness gates hold for this attempt's own artifact."""
        return (
            self.worst_window_err_lu is not None
            and self.whole_err_lu is not None
            and abs(self.worst_window_err_lu) <= window_tol_lu
            and abs(self.whole_err_lu) <= whole_tol_lu
        )

    def hard_tp_ok(self) -> bool:
        """Whether this attempt clears the hard true-peak gate on both legs.

        An unmeasurable attempt fails: the gate is a guarantee, and a missing
        measurement is not evidence that the guarantee held.
        """
        return (
            self.emitted_dbtp is not None
            and self.emitted_dbtp <= TP_GUARD_HARD_DBTP
            and (self.decoded_peak_dbfs is None or self.decoded_peak_dbfs <= 0.0)
        )


@dataclass(frozen=True)
class LeveledSelection:
    """Which attempt ships, and the one warning that explains it.

    ``warning`` is the caller's to log -- this module never logs.  ``hard_tp_met``
    is the guarantee and ``target_met`` the best effort; ``last_resort_needed`` is
    the caller's instruction to emit once more at
    :data:`TP_GUARD_LAST_RESORT_DBTP`.
    """

    kept: LeveledAttempt
    attempts: list[LeveledAttempt]
    target_met: bool
    hard_tp_met: bool
    last_resort_needed: bool
    warning: str | None


def guard_next_ceiling(
    attempts: Sequence[LeveledAttempt],
    *,
    max_rounds: int = TP_GUARD_MAX_ROUNDS,
) -> float | None:
    """The ceiling for the next re-encode round, or ``None`` to stop here.

    The correction is measured against the *latest* attempt, never against the
    best one so far: the ceiling's effect on the emitted peak is not monotone, so
    a correction derived from a ceiling that is no longer in force chases a fixed
    point that does not exist.  A round is spent only while the latest artifact is
    still above :data:`TP_GUARD_TARGET_DBTP` and rounds remain; an unmeasurable
    latest attempt cannot be corrected, so it ends the search rather than guessing.

    The round this returns the ceiling for is a re-encode of the retained ride PCM
    (see :func:`build_reencode_args`), not a re-convergence -- one round, seconds.
    """
    if not attempts:
        return None
    if len(attempts) - 1 >= max(0, max_rounds):
        return None
    latest = attempts[-1]
    if latest.emitted_dbtp is None:
        return None
    return guard_ceiling_dbtp(latest.limit_dbtp, latest.emitted_dbtp)


def needs_last_resort(attempts: Sequence[LeveledAttempt]) -> bool:
    """Whether every *measured* attempt missed the hard gate, so none may ship.

    Only measured attempts count.  An artifact nobody could measure is a
    measurement failure, not a hot one, and answering it with a quieter emit would
    trade a known loudness for an unknown peak.  A panel with nothing measured
    therefore asks for no last resort: there is no evidence of an over-peak
    artifact to correct.
    """
    measured = [a for a in attempts if a.emitted_dbtp is not None]
    return bool(measured) and not any(a.hard_tp_ok() for a in measured)


def select_leveled_attempt(
    attempts: Sequence[LeveledAttempt],
    *,
    window_tol_lu: float,
    whole_tol_lu: float,
    target_dbtp: float = TP_GUARD_TARGET_DBTP,
) -> LeveledSelection:
    """Which attempt ships, and whether it reached the target.

    The order is answer 11's, and it is a hierarchy rather than a filter:

    1. **hard true peak** (:meth:`LeveledAttempt.hard_tp_ok`) -- the guarantee;
    2. **the loudness gates** -- the level the audience was promised;
    3. **the lowest emitted true peak** -- the guard's actual purpose.

    Each level only breaks ties within the one above it, so a lawful-but-hot
    attempt can never outrank a cold one that misses the loudness gates.  Ranking
    the loudness gates first -- filtering on them and then taking the coldest --
    is the ordering that let a loud attempt over the hard gate win in U25 round 7.

    An unmeasurable attempt can never win: it cannot be shown to be the coldest,
    and the guard does not trade a measured artifact for an unmeasured one.  When
    *nothing* is measured the *nominal* attempt is kept, because a program that
    cannot be measured still airs; the caller warns and the last-resort decision is
    :func:`needs_last_resort`'s, not this function's.  Ties go to the earlier
    round, so the nominal ceiling keeps its claim whenever a lowered one is no
    better.
    """
    nominal = attempts[0]
    kept = min(
        attempts,
        key=lambda a: (
            0 if a.hard_tp_ok() else 1,
            0 if a.loudness_ok(window_tol_lu=window_tol_lu, whole_tol_lu=whole_tol_lu) else 1,
            math.inf if a.emitted_dbtp is None else a.emitted_dbtp,
            a.round_index,
        ),
    )
    target_met = kept.emitted_dbtp is not None and kept.emitted_dbtp <= target_dbtp

    warning: str | None = None
    if not target_met:
        kept_tp = "unmeasurable" if kept.emitted_dbtp is None else f"{kept.emitted_dbtp:+.2f} dBTP"
        nominal_tp = (
            "unmeasurable" if nominal.emitted_dbtp is None else f"{nominal.emitted_dbtp:+.2f} dBTP"
        )
        tried = "; ".join(
            f"round {a.round_index} at a {a.limit_dbtp:+.2f} dBTP ceiling -> "
            + ("unmeasurable" if a.emitted_dbtp is None else f"{a.emitted_dbtp:+.2f} dBTP emitted")
            + ", "
            + (
                "loudness ok"
                if a.loudness_ok(window_tol_lu=window_tol_lu, whole_tol_lu=whole_tol_lu)
                else "loudness gate failed"
            )
            + ("" if a.hard_tp_ok() else ", over the hard true-peak gate")
            for a in attempts
        )
        warning = (
            f"the emitted true peak is {kept_tp}, above the {target_dbtp:+.1f} dBTP "
            f"target and this is best effort only -- the hard true-peak gate is "
            f"what must hold; the nominal attempt emitted {nominal_tp}; attempts: "
            f"{tried}; keeping round {kept.round_index} at a {kept.limit_dbtp:+.2f} "
            f"dBTP ceiling (hard gate {'met' if kept.hard_tp_ok() else 'NOT met'})"
        )
    return LeveledSelection(
        kept=kept,
        attempts=list(attempts),
        target_met=target_met,
        hard_tp_met=kept.hard_tp_ok(),
        last_resort_needed=needs_last_resort(attempts),
        warning=warning,
    )
