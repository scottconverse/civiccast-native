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
import threading
import time
import traceback
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
    assert lr.TP_GUARD_MAX_PEAK_DBFS == 0.1
    assert lr.TP_GUARD_MAX_ROUNDS == 1
    # Answer 12 deleted the last-resort branch, constant and all.
    assert not hasattr(lr, "TP_GUARD_LAST_RESORT_DBTP")
    assert not hasattr(lr, "TP_GUARD_HARD_DBTP")
    assert not hasattr(lr, "needs_last_resort")


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


@pytest.mark.parametrize("blocked_pipe", ["read", "write", "finalwait"])
@pytest.mark.parametrize("stop_reason", ["cancel", "deadline"])
def test_run_ride_interrupts_owned_blocked_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_pipe: str, stop_reason: str
) -> None:
    """Actual child pipes, not a fake read/write, must release on owned stop."""
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    popen = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(lr.subprocess, "Popen", spawn)
    cancel = threading.Event()
    finished = threading.Event()
    stop_threads_before = {
        thread.ident for thread in threading.enumerate() if thread.name == "civiccast-ride-stop"
    }
    outcomes = []
    decoder_ready = tmp_path / "decoder-ready"
    sink_ready = tmp_path / "sink-ready"
    prefix = "import sys,time; from pathlib import Path; Path(sys.argv[1]).touch(); "
    decoder = prefix + (
        "time.sleep(30)"
        if blocked_pipe == "read"
        else (
            "import os; os.close(1); time.sleep(30)"
            if blocked_pipe == "finalwait"
            else "sys.stdout.buffer.write(bytes(4*1024*1024)); sys.stdout.buffer.flush()"
        )
    )
    sink = prefix + ("time.sleep(30)" if blocked_pipe == "write" else "sys.stdin.buffer.read()")

    def ride():
        try:
            outcomes.append(
                lr.run_ride(
                    decoder_args=["-c", decoder, str(decoder_ready)],
                    sink_args=["-c", sink, str(sink_ready)],
                    curve=[(0.0, 0.0)],
                    params=lr.RideParams(target_lufs=-16.0),
                    cancel_event=cancel,
                    timeout_s=0.5 if stop_reason == "deadline" else 10,
                )
            )
        except Exception as exc:
            outcomes.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=ride, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while not (decoder_ready.exists() and sink_ready.exists()) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert decoder_ready.exists() and sink_ready.exists(), "both actual children started"
        if stop_reason == "cancel":
            cancel.set()
        assert finished.wait(2), f"{stop_reason} could not interrupt blocked {blocked_pipe}"
        thread.join(1)
        assert not thread.is_alive()
        assert all(child.poll() is not None for child in children), "owned child leaked"
        assert {
            thread.ident for thread in threading.enumerate() if thread.name == "civiccast-ride-stop"
        } == stop_threads_before, "owned stop thread leaked"
        assert len(outcomes) == 1
        if stop_reason == "cancel":
            assert isinstance(outcomes[0], lr.LoudnessRideCancelledError), (
                "".join(traceback.format_exception(outcomes[0]))
                if isinstance(outcomes[0], Exception)
                else outcomes[0]
            )
        else:
            assert isinstance(outcomes[0], lr.LoudnessRideError), (
                "".join(traceback.format_exception(outcomes[0]))
                if isinstance(outcomes[0], Exception)
                else outcomes[0]
            )
            assert "timed out" in str(outcomes[0])
    finally:
        cancel.set()
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
        thread.join(2)
        assert not thread.is_alive(), "test-owned ride thread did not settle after cleanup"


def test_run_ride_sink_spawn_failure_cleans_decoder_and_tee(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    popen = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        if children:
            raise OSError("synthetic sink spawn failure")
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(lr.subprocess, "Popen", spawn)
    before = {
        thread.ident for thread in threading.enumerate() if thread.name == "civiccast-ride-stop"
    }
    tee = tmp_path / "tee.pcm"
    with pytest.raises(OSError, match="synthetic sink spawn failure"):
        lr.run_ride(
            decoder_args=["-c", "import time; time.sleep(30)"],
            sink_args=["-c", "pass"],
            curve=[(0.0, 0.0)],
            params=lr.RideParams(target_lufs=-16.0),
            pcm_path=tee,
            cancel_event=threading.Event(),
            timeout_s=10,
        )
    assert children[0].poll() is not None
    assert {
        thread.ident for thread in threading.enumerate() if thread.name == "civiccast-ride-stop"
    } == before
    tee.unlink()  # Closed on Windows; caller still owns its retained tee.


def test_run_ride_completed_children_win_deadline_race(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    popen = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(lr.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        lr,
        "time",
        SimpleNamespace(
            perf_counter=lambda: (
                1000.0
                if len(children) == 2 and all(p.poll() is not None for p in children)
                else 0.0
            )
        ),
    )
    result = lr.run_ride(
        decoder_args=["-c", "pass"],
        sink_args=["-c", "import sys; sys.stdin.buffer.read()"],
        curve=[(0.0, 0.0)],
        params=lr.RideParams(target_lufs=-16.0),
        timeout_s=1,
    )
    assert result.frames == 0
    assert all(child.returncode == 0 for child in children)


def test_run_ride_zero_exit_sink_cannot_drop_buffered_pcm(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    marker = tmp_path / "sink-exited"
    decoder = (
        "import sys,time; from pathlib import Path; "
        "p=Path(sys.argv[1]); "
        "exec('while not p.exists(): time.sleep(0.01)'); "
        "time.sleep(0.1); sys.stdout.buffer.write(bytes(128)); sys.stdout.buffer.flush()"
    )
    with pytest.raises(lr.LoudnessRideError, match=r"sink|pipe"):
        lr.run_ride(
            decoder_args=["-c", decoder, str(marker)],
            sink_args=[
                "-c",
                "import sys; from pathlib import Path; Path(sys.argv[1]).touch()",
                str(marker),
            ],
            curve=[(0.0, 0.0)],
            params=lr.RideParams(target_lufs=-16.0),
            timeout_s=3,
        )


@pytest.mark.parametrize("owned_stop", [False, True])
def test_run_ride_pipe_oserror_preserves_owned_stop_only(monkeypatch, owned_stop):
    from types import SimpleNamespace

    monkeypatch.setattr(lr, "_ffmpeg_binary", lambda: sys.executable)
    cancel = threading.Event()
    popen = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        if len(children) == 1:
            pipe = child.stdout

            def read(size):
                if owned_stop:
                    cancel.set()
                    child.wait(timeout=2)  # Owner killed it, then Windows pipe raises EINVAL.
                raise OSError(22, "synthetic pipe error")

            child.stdout = SimpleNamespace(read=read, close=pipe.close)
        return child

    monkeypatch.setattr(lr.subprocess, "Popen", spawn)
    expected = lr.LoudnessRideCancelledError if owned_stop else OSError
    with pytest.raises(expected):
        lr.run_ride(
            decoder_args=["-c", "import time; time.sleep(30)"],
            sink_args=["-c", "import sys; sys.stdin.buffer.read()"],
            curve=[(0.0, 0.0)],
            params=lr.RideParams(target_lufs=-16.0),
            cancel_event=cancel,
            timeout_s=5,
        )
    assert all(child.poll() is not None for child in children)


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
