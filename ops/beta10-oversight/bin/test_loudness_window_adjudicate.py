# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U54 lookup tests for the loudness-window adjudicator.

SYNTHETIC-FIXTURE tests: they build their own media roots under `tmp_path` and
never read the live station's uploads tree, so they are safe to run while a
rung is up.  Every negative assertion is paired with a positive control so a
test that stops being able to fail is visible.

The U54 bug: `RE_ON_AIR` captured the source name with `([^,]*), `, which stops
at the first comma *inside the asset's own display name*.  The station's log
line for the public channel reads

    ... egress state -> ON_AIR (source=City Council Regular Session - August 11, 2026.mp4, pid=2044, last_error=-)

so the name was truncated to `City Council Regular Session - August 11`, whose
key matches nothing on disk -- "not found under the media root", never reaching
the ambiguity branch that the two real copies would otherwise trigger.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_ADJ = Path(__file__).resolve().with_name("loudness_window_adjudicate.py")
_SPEC = importlib.util.spec_from_file_location("loudness_window_adjudicate", _ADJ)
assert _SPEC is not None and _SPEC.loader is not None
adj = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = adj
_SPEC.loader.exec_module(adj)

#: The exact line the station wrote at 2026-09-26 18:06:42,447 local (verified
#: against control_plane-app.log:2288), comma and all.
_REAL_LINE = (
    "2026-09-26 18:06:42,447 INFO civiccast.egress.daemon: channel public: "
    "egress state -> ON_AIR (source=City Council Regular Session - August 11, 2026.mp4, "
    "pid=2044, last_error=-)\n"
)
_REAL_NAME = "City Council Regular Session - August 11, 2026.mp4"

#: The station's own on-disk spelling of the same asset.
_DISK_STEM = "City_Council_Regular_Session_-_August_11__2026"

_BODY_A = b"a" * 4096
_BODY_B = b"b" * 4096


def _write_log(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "control_plane-app.log"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# The regex: the display name must survive its own commas.
# ---------------------------------------------------------------------------


def test_on_air_source_name_with_a_comma_is_not_truncated(tmp_path: Path) -> None:
    """RED before the fix: the name was cut at `August 11, 2026`'s comma."""
    log = _write_log(tmp_path, _REAL_LINE)
    transitions = adj.on_air_transitions(log)
    assert [(ch, src) for _ts, ch, src in transitions] == [("public", _REAL_NAME)]
    # The truncation this pins down, stated as the failing value it used to be.
    assert transitions[0][2] != "City Council Regular Session - August 11"


def test_on_air_source_name_is_the_last_pid_field(tmp_path: Path) -> None:
    """A comma in `last_error` must not be mistaken for the source boundary."""
    line = _REAL_LINE.replace("last_error=-)", "last_error=reader, gone)")
    log = _write_log(tmp_path, line)
    assert adj.on_air_transitions(log)[0][2] == _REAL_NAME


def test_on_air_runs_still_collapse_to_one_transition(tmp_path: Path) -> None:
    """Positive control: the per-second repeat is still one transition."""
    log = _write_log(tmp_path, _REAL_LINE * 3)
    assert len(adj.on_air_transitions(log)) == 1


# ---------------------------------------------------------------------------
# find_asset: identical copies are one asset; different copies stay ambiguous.
# ---------------------------------------------------------------------------


def _two_copies(tmp_path: Path, body_a: bytes, body_b: bytes) -> Path:
    root = tmp_path / "uploads"
    for sub, body in (("fmt-h264", body_a), ("lpmrot-01-city", body_b)):
        d = root / sub
        d.mkdir(parents=True)
        (d / f"{_DISK_STEM}.mp4").write_bytes(body)
    return root


def test_find_asset_treats_byte_identical_copies_as_one(tmp_path: Path) -> None:
    """RED before the fix: two hits returned "ambiguous" and resolved nothing."""
    root = _two_copies(tmp_path, _BODY_A, _BODY_A)
    idx = adj.index_media(root)
    path, why = adj.find_asset(idx, _REAL_NAME)
    assert path is not None, why
    assert path.name == f"{_DISK_STEM}.mp4"
    assert path.parent.name == "fmt-h264"  # sorted-first is the deterministic pick
    assert why.startswith("unique")


def test_find_asset_keeps_ambiguity_for_different_copies(tmp_path: Path) -> None:
    """Positive control: genuinely different copies must still be reported."""
    root = _two_copies(tmp_path, _BODY_A, _BODY_B)
    idx = adj.index_media(root)
    path, why = adj.find_asset(idx, _REAL_NAME)
    assert path is None
    assert why.startswith("ambiguous (copies differ): ")


def test_find_asset_resolves_the_log_display_name_end_to_end(tmp_path: Path) -> None:
    """The whole path the rung walks: log line -> transitions -> find_asset."""
    root = _two_copies(tmp_path, _BODY_A, _BODY_A)
    log = _write_log(tmp_path, _REAL_LINE)
    display_name = adj.on_air_transitions(log)[0][2]
    path, why = adj.find_asset(adj.index_media(root), display_name)
    assert path is not None, why
    assert why.startswith("unique")


def test_find_asset_still_reports_not_found(tmp_path: Path) -> None:
    """Negative control: a name that is genuinely absent is still not found."""
    root = _two_copies(tmp_path, _BODY_A, _BODY_A)
    path, why = adj.find_asset(adj.index_media(root), "No Such Meeting - January 1, 1999.mp4")
    assert path is None
    assert why == "not found under the media root"


def test_find_asset_resolves_a_source_that_is_already_a_path(tmp_path: Path) -> None:
    """If the log ever names a path outright, resolve it without the index."""
    root = _two_copies(tmp_path, _BODY_A, _BODY_A)
    wanted = root / "lpmrot-01-city" / f"{_DISK_STEM}.mp4"
    path, why = adj.find_asset(adj.index_media(root), str(wanted))
    assert path == wanted
    assert why.startswith("unique")


# ---------------------------------------------------------------------------
# _emit: the rung reads this file every 30 minutes; it must never see a partial.
# ---------------------------------------------------------------------------


def _emit_args(out: Path) -> argparse.Namespace:
    return argparse.Namespace(out=out, evidence=None, scratch_dir=None, quiet=True)


def test_emit_replaces_the_report_and_leaves_no_partial(tmp_path: Path) -> None:
    out = tmp_path / "loudness-03.adjudicated.json"
    out.write_text('{"stale": true}', encoding="utf-8")
    report = {
        "tool": "loudness_window_adjudicate",
        "channels": {"public": {"classification": "PASS"}},
    }
    adj._emit(report, _emit_args(out))
    assert json.loads(out.read_text(encoding="utf-8")) == report
    assert report["_written"] == str(out)
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_emit_keeps_the_previous_report_when_the_write_fails(tmp_path: Path) -> None:
    """The atomic replace must not destroy a good report on a failed write."""
    out = tmp_path / "loudness-03.adjudicated.json"
    out.write_text('{"stale": true}', encoding="utf-8")
    args = _emit_args(out)
    args.out = tmp_path / "no-such-dir" / "x.json"  # parent missing -> OSError
    report = {"tool": "loudness_window_adjudicate"}
    adj._emit(report, args)
    assert "_write_error" in report
    assert json.loads(out.read_text(encoding="utf-8")) == {"stale": True}


# ---------------------------------------------------------------------------
# U66 — the window's position must not come from a multi-part log guess.
#
# C15 (2026-09-29 07:18): the log-derived position said 3226.3 s; the window was
# really at 7121-7206 s.  No `--air-audio` had been supplied, so the only signal
# that could have contradicted the log never ran.  Three things are tested here:
# the loud-part correlation that can place a quiet-headed window at all, the
# multi-part classification that refuses to rule on a log position it cannot
# trust, and the fact that an ordinary single-part window is untouched by it.
# ---------------------------------------------------------------------------

import datetime as _dt  # noqa: E402  (kept beside the U66 tests they serve)
import hashlib as _hashlib  # noqa: E402

_EDUCATION = "education"


def _args(tmp_path: Path, **kw: object) -> argparse.Namespace:
    """A namespace shaped like `build_parser()`'s, with the ffmpeg seam stubbed."""
    ns = argparse.Namespace(
        evidence=None,
        out=tmp_path / "loudness-09.adjudicated.json",
        scratch_dir=None,
        quiet=True,
        log=tmp_path / "control_plane-app.log",
        media_root=tmp_path / "uploads",
        cache_dir=tmp_path / "cache",
        ffmpeg=tmp_path / "ffmpeg.exe",
        site_packages=tmp_path,
        timeout_s=60.0,
        no_cache=False,
        air_audio={},
        position={},
    )
    for key, value in kw.items():
        setattr(ns, key, value)
    return ns


def _ride() -> dict[str, object]:
    """The ride the criterion is measured against, at the shipped settings.

    The two callables are plain mean-level stand-ins: the real ride is imported
    from the installed station runtime, which these tests must not require.  On a
    flat source they answer exactly what the ride answers -- the flat level.
    """

    def gated_loudness(levels: list[float]) -> float | None:
        got = [lv for lv in levels if lv == lv]
        return sum(got) / len(got) if got else None

    def sliding_levels(
        inside: list[tuple[float, float]], *, window_s: float, step_s: float
    ) -> list[tuple[float, float | None]]:
        if not inside:
            return []
        half = window_s / 2.0
        out: list[tuple[float, float | None]] = []
        t = inside[0][0]
        while t <= inside[-1][0] + 1e-9:
            vals = [m for tt, m in inside if abs(tt - t) <= half]
            out.append((round(t, 3), sum(vals) / len(vals) if vals else None))
            t += step_s
        return out

    return {
        "window_s": 45.0,
        "step_s": 1.0,
        "g_max_db": 18.0,
        "module_sha256": "stub",
        "gated_loudness": gated_loudness,
        "sliding_levels": sliding_levels,
    }


def _blocks(levels: list[float], t0: float = 0.0) -> list[tuple[float, float]]:
    return [(round(t0 + i * 0.1, 4), m) for i, m in enumerate(levels)]


def _stub_series(blocks: list[tuple[float, float]]):
    """Replace `cached_series` with a slice of an in-memory series (no ffmpeg).

    The times come back relative to the requested start, because that is what a
    real `-ss` pass produces -- its timeline begins at zero -- and
    `adjudicate_channel` shifts the profile back by the start it asked for.
    """

    def fake(cache_dir, ffmpeg, path, start, dur, timeout_s, **kw):
        t0 = float(start) if start is not None else 0.0
        t1 = t0 + float(dur) if dur is not None else float("inf")
        return {
            "blocks": [(round(t - t0, 4), m) for t, m in blocks if t0 <= t < t1],
            "returncode": 0,
            "seconds": 0.0,
            "ebur128_integrated_lufs": None,
            "ebur128_true_peak_dbfs": None,
            "cache": False,
        }

    return fake


def _one_asset(tmp_path: Path) -> Path:
    """One copy of the August 11 asset -- unique, so `find_asset` resolves it."""
    d = tmp_path / "uploads" / "fmt-h264"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_DISK_STEM}.mp4"
    p.write_bytes(_BODY_A)
    return p


def _on_air_line(channel: str, when_local: _dt.datetime, name: str = _REAL_NAME) -> str:
    """One ON_AIR line, timestamped the way the log writes local wall clock.

    The log writes milliseconds (`%H:%M:%S,%3f`), not microseconds -- `RE_ON_AIR`
    anchors on exactly three digits, so a six-digit stamp is a line the parser
    would silently skip and every window would read as "no ON_AIR transition".
    """
    stamp = when_local.strftime("%Y-%m-%d %H:%M:%S,") + f"{when_local.microsecond // 1000:03d}"
    return (
        f"{stamp} INFO civiccast.egress.daemon: "
        f"channel {channel}: egress state -> ON_AIR (source={name}, pid=2044, last_error=-)\n"
    )


def _window_at(log_start_local: _dt.datetime, leg_seconds: float) -> str:
    """A `captured_at_utc` that `local_naive` turns back into `leg_seconds` later."""
    when_local = log_start_local + _dt.timedelta(seconds=leg_seconds)
    return when_local.astimezone(_dt.UTC).isoformat()


# --- the loud part, and the halves that must agree -------------------------


def _pattern(n: int, seed: int = 11, lo: float = -38.0, hi: float = -20.0) -> list[float]:
    scale = hi - lo
    return [
        round(
            lo
            + int.from_bytes(_hashlib.sha256(f"{seed}:{index}".encode()).digest()[:8], "big")
            / 2**64
            * scale,
            3,
        )
        for index in range(n)
    ]


def test_loud_part_correlate_places_a_quiet_headed_window() -> None:
    """U64's case: a head too quiet to correlate must not stop the lock.

    The aired window is 30 s of near-silence followed by 150 s lifted from the
    reference at 300 s.  A whole-slice correlation is dominated by whatever the
    silence resembles; the loud part is the lifted audio, and it is the loud part
    that has to place the window.
    """
    ref = _blocks([round(v, 3) for v in _pattern(9000)])
    head = _blocks([-58.0] * 300, t0=0.0)
    body = _blocks([m for _t, m in ref[3000:4500]], t0=30.0)
    got = adj.loud_part_correlate(head + body, ref, 1000.0)
    assert got["ok"], got.get("why")
    assert got["trusted"], got
    # The body's own content starts 30 s into the window and is reference audio
    # from 300 s, so the window's start sits at 270 s: 1000 + 270 = 1270.  The
    # reported position is the WINDOW's start (what `correlate` answers), not the
    # loud region's -- the region simply begins 30 s later.
    assert abs(got["position_s"] - 1270.0) <= 2.0, got["position_s"]
    assert got["loud_part"]["halves_agree_s"] <= adj.LOUD_PART_AGREE_S
    assert got["loud_part"]["air_from_s"] >= 30.0  # the loud part is the body


def test_loud_part_correlate_refuses_halves_that_disagree(monkeypatch) -> None:
    """The acceptance test: two halves that do not repeat are a coincidence."""
    lags = iter([120.0, 480.0])

    def two_lags(*a, **kw):
        lag = next(lags)
        return {"ok": True, "lag_s": lag, "r": 0.9, "margin": 0.5, "curve_half_width_s": 1.0}

    monkeypatch.setattr(adj, "best_lag", two_lags)
    air = _blocks([-25.0] * 2000)
    ref = _blocks([-25.0] * 2000)
    got = adj.loud_part_correlate(air, ref, 0.0)
    assert not got["ok"]
    assert "disagree" in got["why"], got["why"]
    # The second half's raw lag is its own offset further along, so the two
    # halves are compared where they must agree: on where the REGION starts.
    halves = got["loud_part"]["halves"]
    assert [h["lag_s"] for h in halves] == [120.0, 480.0]
    assert halves[0]["offset_in_region_s"] == 0
    assert halves[1]["offset_in_region_s"] > 0
    assert halves[0]["region_lag_s"] == 120.0
    assert halves[1]["region_lag_s"] == 480.0 - halves[1]["offset_in_region_s"]


def test_loud_part_correlate_accepts_halves_that_agree(monkeypatch) -> None:
    """Positive control for the test above: the same shape with agreeing halves.

    A real lock looks like this: the second half is its own offset further into
    the reference, so its raw lag is larger by exactly that offset -- and both
    halves then put the REGION at the same second.  A stub returning one constant
    for both halves would be the disagreeing shape, not this one.
    """
    called = {"n": 0}

    def same_lag(air, *_a, **_kw):
        called["n"] += 1
        # Call 1 is the first half; call 2 the second, offset by its own length;
        # call 3 the whole region, back at the region's own start.
        lag = 300.0 + (len(air) if called["n"] == 2 else 0.0)
        return {"ok": True, "lag_s": lag, "r": 0.9, "margin": 0.5, "curve_half_width_s": 1.0}

    monkeypatch.setattr(adj, "best_lag", same_lag)
    air = _blocks([-25.0] * 2000)
    ref = _blocks([-25.0] * 2000)
    got = adj.loud_part_correlate(air, ref, 0.0)
    assert got["ok"], got.get("why")
    assert got["loud_part"]["halves_agree_s"] == 0.0
    assert got["position_s"] == 300.0  # the region, which starts at the window's own head
    assert called["n"] == 3  # two halves, then the whole region


def test_loud_part_correlate_refuses_a_half_that_does_not_lock(monkeypatch) -> None:
    """A half below r/margin must not be averaged away by a good other half."""

    calls = iter(
        [
            {"ok": True, "lag_s": 300.0, "r": 0.9, "margin": 0.5, "curve_half_width_s": 1.0},
            {"ok": True, "lag_s": 300.0, "r": 0.2, "margin": 0.05, "curve_half_width_s": 1.0},
        ]
    )
    monkeypatch.setattr(adj, "best_lag", lambda *a, **kw: next(calls))
    got = adj.loud_part_correlate(_blocks([-25.0] * 2000), _blocks([-25.0] * 2000), 0.0)
    assert not got["ok"]
    assert "does not lock" in got["why"], got["why"]


def test_loud_region_of_a_short_window_is_the_whole_window() -> None:
    """Below LOUD_PART_MIN_S there is no loud half to pick, and it must say so."""
    start, span, note = adj._loud_region([-30.0] * 40)
    assert (start, span) == (0, 40)
    assert "whole slice is the loud part" in note


# --- the multi-part classification -----------------------------------------


def _transitions(*specs: tuple[str, str]) -> list[tuple[_dt.datetime, str, str]]:
    base = _dt.datetime(2026, 9, 29, 6, 0, 0)
    return [(base + _dt.timedelta(seconds=s), ch, name) for s, ch, name in specs]


def test_multi_part_fires_when_the_name_went_on_air_more_than_once() -> None:
    tr = _transitions(
        (0, _EDUCATION, _REAL_NAME),
        (1800, _EDUCATION, "Some Other Meeting.mp4"),
        (3600, _EDUCATION, _REAL_NAME),
    )
    got = adj.multi_part_airing(
        tr, _EDUCATION, _REAL_NAME, _dt.datetime(2026, 9, 29, 7, 18, 0), 3226.3
    )
    assert got["multi_part"] is True
    assert got["on_air_runs_of_this_name"] == 2
    assert "2 separate times" in got["why"]


def test_multi_part_fires_on_a_leg_longer_than_the_threshold() -> None:
    """C15's own shape: one collapsed run, a position 3226.3 s in."""
    tr = _transitions((0, _EDUCATION, _REAL_NAME))
    got = adj.multi_part_airing(
        tr, _EDUCATION, _REAL_NAME, _dt.datetime(2026, 9, 29, 7, 18, 0), 3226.3
    )
    assert got["multi_part"] is True
    assert got["on_air_runs_of_this_name"] == 1
    assert "3226.3s into one airing" in got["why"]


def test_multi_part_is_quiet_on_an_ordinary_single_leg() -> None:
    """Positive control: a 400 s window into one airing is not a multi-part case."""
    tr = _transitions((0, _EDUCATION, _REAL_NAME))
    got = adj.multi_part_airing(
        tr, _EDUCATION, _REAL_NAME, _dt.datetime(2026, 9, 29, 6, 6, 40), 400.0
    )
    assert got["multi_part"] is False
    assert got["leg_seconds"] == 400.0
    assert got["threshold_s"] == adj.MULTI_PART_T2_S


def test_multi_part_ignores_other_channels_runs() -> None:
    """Another channel airing the same asset says nothing about this window."""
    tr = _transitions(
        (0, _EDUCATION, _REAL_NAME),
        (0, "public", _REAL_NAME),
        (1800, "public", "Some Other Meeting.mp4"),
        (3600, "public", _REAL_NAME),
    )
    got = adj.multi_part_airing(
        tr, _EDUCATION, _REAL_NAME, _dt.datetime(2026, 9, 29, 6, 6, 40), 400.0
    )
    assert got["multi_part"] is False
    assert got["on_air_runs_of_this_name"] == 1


# --- T1 without aired audio is not a position ------------------------------


def test_air_lock_without_air_audio_says_so_and_touches_no_ffmpeg(tmp_path: Path) -> None:
    got = adj.air_lock(_args(tmp_path), tmp_path / "x.mp4", None, 3226.3)
    assert got["ok"] is False
    assert got["why"] == "no aired audio supplied"


# --- the two ends of adjudicate_channel ------------------------------------


def _channel(leg_seconds: float, *, duration: float = 241.666667) -> dict:
    return {
        "status": "FAIL",
        "captured_at_utc": _window_at(_dt.datetime(2026, 9, 29, 6, 0, 0), leg_seconds),
        "captured_duration_seconds": duration,
        "audio_window": {
            "status": "FAIL",
            "integrated_lufs": -21.9,
            "duration_seconds": duration,
            "target_lufs": -16.0,
            "tolerance_lufs": 1.0,
            "detail": "window integrated -21.9 LUFS over 241.7s (target -16 +/- 1)",
        },
    }


def _adjudicate(tmp_path: Path, monkeypatch, leg_seconds: float) -> dict:
    """Run one channel end to end with the media and ffmpeg seams stubbed.

    The log is deliberately C15's own shape: the station played one asset in parts
    under one name, so `on_air_transitions` collapsed the whole airing into a
    single ON_AIR at its first part.  `leg_seconds` -- how far `captured_at_utc`
    sits past that ON_AIR -- is the only thing that differs between the two cases
    below; 3226.3 s is the position C15's log reported.
    """
    _one_asset(tmp_path)
    log = tmp_path / "control_plane-app.log"
    start = _dt.datetime(2026, 9, 29, 6, 0, 0)
    log.write_text(_on_air_line(_EDUCATION, start), encoding="utf-8")
    monkeypatch.setattr(adj, "air_lock", lambda *a, **kw: {"ok": False, "why": "stubbed"})
    flat = _blocks([-18.0] * 6000)
    monkeypatch.setattr(adj, "cached_series", _stub_series(flat))
    args = _args(tmp_path, log=log)
    return adj.adjudicate_channel(
        _EDUCATION,
        _channel(leg_seconds),
        args,
        _ride(),
        adj.on_air_transitions(log),
        adj.index_media(tmp_path / "uploads"),
        {"target_lufs": -16.0, "tolerance_lufs": 1.0},
    )


def test_multi_part_window_with_no_correlation_is_borderline(tmp_path, monkeypatch) -> None:
    """Item 3: never FAIL or EXCLUDE on a log position that may count one part."""
    out = _adjudicate(tmp_path, monkeypatch, 3226.3)
    assert out["classification"] == "BORDERLINE"
    assert out["detail"] == adj.POSITION_UNRESOLVED_MULTI_PART
    assert out["position"]["source"] == "log"
    assert out["multi_part"]["multi_part"] is True
    # It stops BEFORE measuring: the C15 wrong ruling was a measurement, at a
    # position nobody had established.
    assert "source" not in out
    assert out["summary_line"].startswith(f"{_EDUCATION}=BORDERLINE ")


def test_single_part_window_still_uses_the_log_position_unchanged(tmp_path, monkeypatch) -> None:
    """Positive control: an ordinary window is measured exactly as before."""
    out = _adjudicate(tmp_path, monkeypatch, 400.0)
    assert out["position"]["source"] == "log"
    assert out["position"]["position_s"] == 400.0
    assert out["position"]["agrees_with_log_within_s"] == 0.0
    assert out["multi_part"]["multi_part"] is False
    assert out["classification"] != "BORDERLINE"
    assert out["source"]["span_lufs"] == -18.0
    assert out["summary_line"].startswith(f"{_EDUCATION}={out['classification']} ")
