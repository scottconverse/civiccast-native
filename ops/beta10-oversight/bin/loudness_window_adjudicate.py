#!/usr/bin/env python
"""Adjudicate a failing rung loudness window: station failure, or quiet source?

READ-ONLY on the station.  One ffmpeg at a time, below-normal priority, and never
a live-HLS path handed to ffmpeg: the aired audio that drives the optional
correlation comes from a file the caller names (`--air-audio`), so the live-station
read rule (PROJECT-BRIEF.md, "Live-station read rule") holds by construction.

The rung's loudness gate (`capture_emitted_hls_audio_proof.py` -> a 240 s window,
-16 +/- 1 LUFS) fails on windows the station cannot fix: a quiet passage the ride
may not lift past its own ceiling.  The owner's decision (2026-09-26) makes that
explicit -- such a window is NOT a failure, and every such window must be listed
with its numbers.  This tool produces those numbers.

For each channel whose window is not PASS:

  1. ASSET      the last `egress state -> ON_AIR (source=..., ...)` transition for
                that channel at or before the window's `captured_at_utc`.
  2. POSITION   T1: the U45 alignment method -- high-pass the aired 1 s momentary
                loudness series and slide it against the source's own series to
                find the lag, reported with its Pearson r and runner-up margin.
                T2: log-derived -- `captured_at_utc` minus the asset's ON_AIR
                timestamp (the log carries no live position; see the U45 report).
  3. MEASURE    the SOURCE over that span, with the ride's own invocation and the
                ride's own arithmetic (`ebur128=peak=true` -> the 0.1 s momentary
                blocks -> `loudness_ride.gated_loudness`), imported from the
                INSTALLED runtime, not from any checkout.
  4. CLASSIFY   second by second: a second of the span is UNREACHABLE iff its own
                centred ride window cannot be brought to the target's lower edge
                even at the ride's ceiling:
                    source_window_lufs + RideParams.g_max_db < target - tolerance
                `EXCLUDED_QUIET_SOURCE` iff the UNREACHABLE seconds reach a quarter
                of the window (`MIN_UNREACHABLE_FRACTION`: 60 s of a 240 s window),
                and that count is printed on the line.  Otherwise FAIL stands -- a
                single quiet 45 s moment inside a window whose other 195 s the
                station COULD have corrected is not the station's excuse.  (The
                retired reading -- the quietest window alone -- excused exactly
                that, which is why it was replaced; `lift_limited_lufs` is still
                emitted so the retired reading stays on the record.)
                The span-wide figure (gated loudness of the whole 240 s) is ALSO
                emitted as `literal_formula` so the two readings are both on the
                record; the span figure cannot be the intended one, because a
                span-wide gated loudness already discards quiet material at its
                relative gate -- it is loudest where the window fails hardest.
  5. ROBUST     the verdict is the unreachable count at the MEASURED position
                only (U45 answer 3): position uncertainty never makes the window
                UNRESOLVED.  Both sweeps (the position method's own uncertainty, and
                a wider +/-30 s) are reported as a RANGE on the line --
                    unreach=<n>/<scorable>s (range <lo>-<hi>, need 60) window=<w>s
                -- and a range that straddles the need is flagged BORDERLINE, which
                means a human reads that window by hand.  The need is a quarter of
                the FULL window and is NOT rescaled by how many of its seconds are
                scorable; the scorable count and the window are both on the line so
                that gap is visible.

A channel whose capture holds no loudness measurement at all is not a FAIL to
adjudicate.  The capture never scored a window, so there is nothing a source
measurement could excuse and nothing here to measure: such a channel is reported
INSTRUMENT_ERROR with the capture's own reason (U48), and `rung_check.py` prints
the same word on the line.  It still fails the rung -- no evidence is not a pass.

Any channel this tool cannot resolve is reported UNRESOLVED, and UNRESOLVED is a
failure in `rung_check.py` -- the tool may excuse a window, never a silence.  (A
criterion verdict is never UNRESOLVED: the count is read at the measured position.
That path is only for a measurement the tool could not take at all -- no asset, no
audio, no window -- where no count exists to read.)

Usage:
  loudness_window_adjudicate.py EVIDENCE.json [--out PATH] [--log PATH]
      [--media-root PATH] [--ffmpeg PATH] [--air-audio [CH=]PATH]
      [--position [CH=]SEC] [--cache-dir PATH] [--scratch-dir PATH]
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Constants: station paths, the ride's own numbers, and the method's knobs.
# --------------------------------------------------------------------------

STATION = Path(r"C:\Program Files\CivicCast (Native)")
STATION_SITE_PACKAGES = STATION / "runtime" / "Lib" / "site-packages"
DEFAULT_LOG = Path(r"C:\ProgramData\CivicCast\logs\control_plane-app.log")
DEFAULT_MEDIA_ROOT = Path(r"C:\ProgramData\CivicCast\data\uploads")
DEFAULT_FFMPEG = STATION / "dependencies" / "ffmpeg" / "bin" / "ffmpeg.exe"
DEFAULT_CACHE_DIR = Path(tempfile.gettempdir()) / "cc-loud-adj"
DEFAULT_SCRATCH_DIR = Path(tempfile.gettempdir()) / "cc-loud-adj-scratch"

#: Windows process-creation flags: the ride's children are dropped below normal
#: priority so a measurement can never outrank an on-air encoder.
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
#: The whole-asset retry (U66, item 2) decodes everything the asset has -- 15,949 s
#: of it for the C15 source -- while the rung may be on air.  That one child runs
#: at IDLE, the class the station's own `bin\monitors\lowloud.ps1` uses for ad-hoc
#: measurement; a rung window can afford the wall clock and the encoder cannot
#: afford the cycle.  Every other ffmpeg here stays below-normal.
IDLE_PRIORITY_CLASS = 0x00000040
CREATE_NO_WINDOW = 0x08000000

#: ebur128's own summary lines, exactly as `loudness_ride` reads them.  Copied
#: rather than imported (module-private); the module's path, size and sha256 are
#: recorded in the output so drift is visible.
RE_SERIES = re.compile(
    r"\]\s*t:\s*([\d.]+)\s+.*?M:\s*(-?[\d.]+|nan|-inf)\s+S:\s*(-?[\d.]+|nan|-inf)"
)
RE_I = re.compile(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", re.M)
RE_TP = re.compile(r"^\s*(?:True )?[Pp]eak:\s*(-?[\d.]+)\s*dBFS", re.M)

#: The ON_AIR transition line, as written by civiccast.egress.daemon:
#:   "channel %s: egress state -> %s (source=%s, pid=%s, last_error=%s)"
#: `source` is the asset's DISPLAY name, and a display name carries commas of
#: its own ("... August 11, 2026.mp4").  The boundary is therefore the following
#: field, not a bare comma: `source` is greedy up to the LAST `, pid=` on the
#: line (U54 -- the old `source=([^,]*), ` cut `City Council Regular Session -
#: August 11, 2026.mp4` down to `... August 11`, a key that matches nothing on
#: disk, so the window read "not found under the media root" and never even
#: reached the ambiguity branch its two real copies would have triggered).
#: The log stamps LOCAL wall clock (no offset), which is the same clock the
#: rung's own rung.log uses; `_local_naive` does the conversion explicitly.
RE_ON_AIR = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*?channel (\w+): egress state -> ON_AIR "
    r"\(source=(.*), pid=([^,]*), last_error=(.*)\)\s*$",
    re.M,
)

#: A `source=` value that is already a path rather than a display name, in the
#: Windows or POSIX spellings the station could emit.
RE_PATHISH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _pathish(name: str) -> Path | None:
    return Path(name) if RE_PATHISH.match(name) else None


#: Video containers a station upload can be.
MEDIA_SUFFIXES = (".mp4", ".mkv", ".mov", ".m4v", ".ts", ".mts", ".avi", ".webm")

#: Correlation knobs.  CALIBRATED on this station's own pair: the U45 alignment
#: put the aired window against the source at r=+0.9953 (10 s high-pass) with the
#: nearest rival at r<+0.03, so 0.6 / 0.15 sit far outside the noise and far
#: below the real signal.
AIR_HP_WIN_S = 10.0
AIR_MIN_R = 0.6
AIR_MIN_MARGIN = 0.15
AIR_NMS_S = 60.0
#: The reference slice is taken from the log-derived position, so T1 never needs
#: the whole asset profiled -- only this much either side of the guess.
REF_WINDOW_S = 900.0
#: The span is profiled with this much padding, so every shifted span is measured
#: from one pass of the decoder.
SPAN_PAD_S = 60.0

#: How far each position method can be wrong, in seconds.  `log` is calibrated
#: from the one measured pair (T2 4025.4 s vs T1 4046.7 s = 21.3 s) plus the
#: ON_AIR announce cadence; `supplied` from the caller's own assertion;
#: `correlation` is only a FALLBACK -- its uncertainty is the measured width of
#: the correlation peak (`curve_half_width_s`), which this value replaces.
POSITION_UNCERTAINTY_S = {"correlation": 2.0, "log": 30.0, "supplied": 0.0}
#: A T1 position that disagrees with the log by more than this is not trusted:
#: either the asset or the correlation is wrong, and neither may excuse a window.
T1_T2_MAX_DISAGREEMENT_S = 60.0
#: Reported (not gating) sweep half-width.
ROBUST_SWEEP_S = 30.0

#: U66.  A quiet head correlates badly (U64): the loudness curve of near-silence
#: is a shape of its own, and a whole-slice correlation can lock onto whatever
#: noise resembles it.  The loud part of the window carries the asset's identity,
#: so when the whole slice fails to lock, the loudest contiguous half is tried --
#: never a slice shorter than this, both because a short slice has fewer lags a
#: peak can be sharp against and because half of the rung's own 240 s window is
#: the natural floor.
LOUD_PART_MIN_S = 60.0
#: Two disjoint halves of the loud region must land within this of each other
#: before the region's lag is believed: a real lock repeats under the split, a
#: coincidence does not.  Well inside AIR_NMS_S, so it is the agreement test and
#: not a second naming of the peak separation.
LOUD_PART_AGREE_S = 15.0

#: U66 item 3.  The log can only place the window inside the ONE airing run it
#: found, and `on_air_transitions` collapses repeats of one name into one run.  An
#: asset the station replayed across a plan rollover therefore reports a position
#: that is short by every earlier part -- C15: the true 7121 s was logged as
#: 3226.3 s, because the August 11 source had been on air in ~1800 s parts.  Past
#: this much airtime the log is no longer trustworthy on its own.
MULTI_PART_T2_S = 1800.0
#: The word a human reads when T1 could not place the window and T2 may not be
#: believed.  Deliberately not FAIL (no loudness verdict exists) and deliberately
#: not EXCLUDED_QUIET_SOURCE (nothing was measured at a position anyone trusts).
POSITION_UNRESOLVED_MULTI_PART = "position unresolved: multi-part asset, log position unreliable"

TARGET_FALLBACK = -16.0
TOLERANCE_FALLBACK = 1.0

#: The tightened criterion (owner, 2026-09-26, U45 answer 2).  The quietest-window
#: reading it replaces excused a whole 240 s window on a single quiet 45 s moment
#: whose other 195 s the station could have corrected.  The owner's rule is "not a
#: fail only when the station could not have fixed it", so a window is excused only
#: when a QUARTER of it could not be fixed by the ride's own maximum lift.
MIN_UNREACHABLE_FRACTION = 0.25

#: U48.  A channel the capture could not measure at all: the playlist read raced
#: the relay's atomic replace, the capture stopped short, an ffmpeg died.  The rung
#: prints this word instead of a loudness FAIL, because no loudness verdict exists
#: to print -- see `instrument_reason` below.
INSTRUMENT_ERROR = "INSTRUMENT_ERROR"


def min_unreachable_seconds(window_s: float) -> int:
    """The count a window must reach to be excused: a quarter of it, at least one."""
    return max(1, math.ceil(MIN_UNREACHABLE_FRACTION * float(window_s)))


# --------------------------------------------------------------------------
# The installed ride: its numbers, its gate, its window.
# --------------------------------------------------------------------------


def load_ride(site_packages: Path) -> dict[str, Any]:
    """Import `civiccast.egress.loudness_ride` from the INSTALLED runtime.

    The installed module is what is on air, so it -- not any checkout -- is what
    this tool's criterion is read from.  Failure to import is fatal and loud: a
    tool that guesses `g_max_db` would excuse windows the ride cannot actually
    reach, which is the one thing this tool exists not to do.
    """
    text = str(site_packages)
    if text not in sys.path:
        sys.path.insert(0, text)
    from civiccast.egress.loudness_ride import (
        RideParams,
        gated_loudness,
        sliding_levels,
    )

    path = Path(sys.modules["civiccast.egress.loudness_ride"].__file__ or "")
    raw = path.read_bytes() if path.is_file() else b""
    st = path.stat() if path.is_file() else None
    return {
        "module_path": str(path),
        "module_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
        "module_mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat() if st else None,
        "site_packages": str(site_packages),
        "params": RideParams,
        "gated_loudness": gated_loudness,
        "sliding_levels": sliding_levels,
        "window_s": RideParams.window_s,
        "step_s": RideParams.step_s,
        "g_max_db": RideParams.g_max_db,
        "g_min_db": RideParams.g_min_db,
    }


# --------------------------------------------------------------------------
# Time: the log is local wall clock, the evidence JSON is UTC.
# --------------------------------------------------------------------------


def parse_log_time(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f")


def local_naive(when: dt.datetime) -> dt.datetime:
    """UTC -> the machine's local wall clock, naive, as the log writes it."""
    return when.astimezone().replace(tzinfo=None)


def parse_utc(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


# --------------------------------------------------------------------------
# The station log: which asset was airing, and since when.
# --------------------------------------------------------------------------


def on_air_transitions(log_path: Path) -> list[tuple[dt.datetime, str, str]]:
    """Every ON_AIR transition in the log: (local time, channel, source name).

    A transition is the first line of a run of identical sources for a channel.
    """
    try:
        raw = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[tuple[dt.datetime, str, str]] = []
    last: dict[str, str] = {}
    for ts, ch, src, _pid, _err in RE_ON_AIR.findall(raw):
        name = src.strip()
        if last.get(ch) != name:
            last[ch] = name
            out.append((parse_log_time(ts), ch, name))
    return out


def asset_and_leg_start(
    transitions: list[tuple[dt.datetime, str, str]], channel: str, when_local: dt.datetime
) -> tuple[str, dt.datetime] | None:
    """The asset airing at `when_local` and the time its ON_AIR run began."""
    seen: tuple[str, dt.datetime] | None = None
    for ts, ch, src in transitions:
        if ch != channel:
            continue
        if ts > when_local:
            break
        if seen is None or seen[0] != src:
            seen = (src, ts)
    return seen


def multi_part_airing(
    transitions: list[tuple[dt.datetime, str, str]],
    channel: str,
    display_name: str,
    when_local: dt.datetime,
    t2: float,
) -> dict[str, Any]:
    """Could the log's position be short by earlier parts of the same asset? (U66)

    `on_air_transitions` collapses a run of identical sources into ONE transition,
    so a station that plays a long meeting in ~1800 s parts -- each part a fresh
    ON_AIR of the SAME name, back to back -- reports a single run whose start is
    part ONE's.  The window's log position then counts every part before it, which
    is exactly the C15 defect: true 7121 s, logged 3226.3 s.

    Two observable facts, either of which is enough:
      * the window sits more than MULTI_PART_T2_S into the run -- no ordinary
        single-leg airing is that long, but a long single-leg airing IS possible
        (an unattended two-hour meeting), which is why this only ever produces a
        note for a human and never a FAIL; or
      * the same display name went on air more than once for this channel (it left
        and came back), which for one asset means it was played in parts.

    Deliberately conservative.  This is read by the caller ONLY when the
    correlation could not place the window, and its answer never excuses anything.
    """
    runs = [
        ts
        for ts, ch, src in transitions
        if ch == channel and src == display_name and ts <= when_local
    ]
    leg_seconds = float(t2)
    if len(runs) > 1:
        why = (
            f"{display_name!r} went on air {len(runs)} separate times for {channel} "
            f"before this window: the log's position likely counts only the last part"
        )
        multi = True
    elif leg_seconds > MULTI_PART_T2_S:
        why = (
            f"the log places the window {leg_seconds:g}s into one airing of "
            f"{display_name!r} (> {MULTI_PART_T2_S:g}s): either the asset was replayed "
            "in parts under one name or it was on air unattended this long"
        )
        multi = True
    else:
        why = f"the log places the window {leg_seconds:g}s into a single airing"
        multi = False
    return {
        "multi_part": multi,
        "why": why,
        "leg_seconds": round(leg_seconds, 1),
        "threshold_s": MULTI_PART_T2_S,
        "on_air_runs_of_this_name": len(runs),
    }


# --------------------------------------------------------------------------
# Media resolution: the log's display name -> the uploaded asset on disk.
# --------------------------------------------------------------------------


def name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def index_media(media_root: Path) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    if not media_root.is_dir():
        return idx
    for dirpath, _dirnames, filenames in os.walk(media_root):
        for fn in filenames:
            if not fn.lower().endswith(MEDIA_SUFFIXES):
                continue
            p = Path(dirpath) / fn
            # Key on the STEM: the log writes a display name, the disk writes a
            # filename, and the only predictable difference between them is the
            # extension (the log's name carries none).
            for key in {name_key(p.stem), name_key(p.stem).replace("and", "")}:
                idx.setdefault(key, []).append(p)
    for paths in idx.values():
        paths.sort()
    return idx


def find_asset(
    idx: dict[str, list[Path]],
    display_name: str,
    *,
    digests: DigestCache | None = None,
) -> tuple[Path | None, str]:
    """Resolve a display name to one file.  Ambiguity is reported, never guessed.

    More than one name-key hit is not automatically ambiguous: the station keeps
    the same upload in more than one place (`uploads/fmt-h264/` and the
    per-channel `uploads/<channel>/`), and two byte-identical copies are ONE
    asset, not a choice.  Copies whose bytes differ are still reported.
    """
    # The log may name the asset outright; if it does, honour it and skip the index.
    hinted = _pathish(display_name)
    if hinted is not None and hinted.is_file():
        return hinted, "unique (path from the log)"
    stem = display_name[:-4] if display_name.lower().endswith(MEDIA_SUFFIXES) else display_name
    for key in (name_key(stem), name_key(stem).replace("and", "")):
        hits = idx.get(key) or []
        if not hits:
            continue
        if len(hits) == 1:
            return hits[0], "unique"
        try:
            groups = _identical_groups(hits, digests)
        except OSError as exc:
            return None, "ambiguous: " + "; ".join(str(h) for h in hits) + f" (hash failed: {exc})"
        if len(groups) == 1:
            return groups[0][0], f"unique (identical copies: {len(groups[0])})"
        return None, "ambiguous (copies differ): " + "; ".join(str(h) for h in hits)
    return None, "not found under the media root"


def _identical_groups(paths: list[Path], digests: DigestCache | None) -> list[list[Path]]:
    """Group candidate files by content, cheaply: size first, then sha256."""
    by_size: dict[int, list[Path]] = {}
    for p in paths:
        by_size.setdefault(p.stat().st_size, []).append(p)
    groups: list[list[Path]] = []
    for same_size in by_size.values():
        if len(same_size) == 1:
            groups.append(same_size)
            continue
        by_digest: dict[str, list[Path]] = {}
        for p in same_size:
            by_digest.setdefault(file_digest(p, digests), []).append(p)
        groups.extend(by_digest.values())
    for group in groups:
        group.sort()
    if digests is not None:
        digests.prune({p for group in groups for p in group})
    groups.sort(key=lambda g: g[0])
    return groups


class DigestCache:
    """File digests keyed by (path, size, mtime), so a 4 GB asset is hashed once.

    The rung re-runs the adjudicator every 30 minutes against the same uploads;
    hashing each multi-copy candidate per run would spend minutes of I/O for an
    answer that cannot change while size and mtime hold.  A stale entry can only
    be reached if a file changes size-and-mtime-preservingly, which no writer
    here does; the size and mtime are re-checked on every lookup.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, dict[str, Any]] = {}
        self._used: set[str] = set()
        if path is not None and path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = {str(k): v for k, v in loaded.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                self.data = {}

    def get(self, path: Path) -> str | None:
        st = path.stat()
        entry = self.data.get(str(path))
        if entry and entry.get("size") == st.st_size and entry.get("mtime_ns") == st.st_mtime_ns:
            self._used.add(str(path))
            return str(entry.get("sha256"))
        return None

    def put(self, path: Path, digest: str) -> None:
        st = path.stat()
        self.data[str(path)] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
        self._used.add(str(path))

    def prune(self, keep: set[Path]) -> None:
        allowed = {str(p) for p in keep}
        for key in [k for k in self.data if k not in allowed]:
            del self.data[key]

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(self.data, indent=0, sort_keys=True)
            tmp = self.path.with_name(self.path.name + f".tmp{os.getpid()}")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


def file_digest(path: Path, digests: DigestCache | None = None) -> str:
    """The file's sha256, from the cache when (size, mtime) still match."""
    if digests is not None:
        cached = digests.get(path)
        if cached is not None:
            return cached
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if digests is not None:
        digests.put(path, digest)
    return digest


# --------------------------------------------------------------------------
# ffmpeg: the ride's own measurement invocation, below normal priority.
# --------------------------------------------------------------------------


def ebur128_series(
    ffmpeg: Path,
    path: Path,
    start: float | None,
    dur: float | None,
    timeout_s: float,
    *,
    priority: int = BELOW_NORMAL_PRIORITY_CLASS,
) -> dict[str, Any]:
    """One decode pass -> the 0.1 s momentary blocks plus ebur128's summaries.

    The argument list is `loudness_ride.build_source_series_args` verbatim:
    input-side `-ss`, `-t` after `-i`, `-vn -af ebur128=peak=true -f null -`.

    `priority` is the Windows creation class; only the whole-asset retry drops to
    IDLE (see IDLE_PRIORITY_CLASS), because only it decodes the whole asset.
    """
    args = [str(ffmpeg), "-hide_banner", "-loglevel", "info"]
    if start is not None:
        args += ["-ss", f"{float(start):g}"]
    args += ["-i", str(path)]
    if dur is not None:
        args += ["-t", f"{float(dur):g}"]
    args += ["-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]

    t0 = time.monotonic()
    # Operator-selected local ffmpeg (--ffmpeg/local receipt); media is an argv operand, no shell.
    proc = subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        creationflags=priority | CREATE_NO_WINDOW,
    )
    stderr = proc.stderr or ""
    blocks: list[tuple[float, float]] = []
    for t_s, m_s, _s_s in RE_SERIES.findall(stderr):
        try:
            blocks.append((float(t_s), float(m_s)))
        except ValueError:
            continue
    i_hits = RE_I.findall(stderr)
    tp_hits = RE_TP.findall(stderr)
    return {
        "args": args,
        "returncode": proc.returncode,
        "seconds": round(time.monotonic() - t0, 2),
        "blocks": blocks,
        "ebur128_integrated_lufs": float(i_hits[-1]) if i_hits else None,
        "ebur128_true_peak_dbfs": float(tp_hits[0]) if tp_hits else None,
    }


def series_cache_key(path: Path, start: float | None, dur: float | None, ffmpeg: Path) -> str:
    st = path.stat()
    raw = f"{path}|{st.st_size}|{st.st_mtime_ns}|{start}|{dur}|{ffmpeg}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cached_series(
    cache_dir: Path,
    ffmpeg: Path,
    path: Path,
    start: float | None,
    dur: float | None,
    timeout_s: float,
    *,
    use_cache: bool = True,
    priority: int = BELOW_NORMAL_PRIORITY_CLASS,
) -> dict[str, Any]:
    """`ebur128_series`, memoised on (file identity, window, ffmpeg).

    The cache key is content identity, so `priority` does not enter it: the same
    window decoded at IDLE and below-normal is the same series, and the whole
    asset's one IDLE pass must be reused by every later call.
    """
    key = series_cache_key(path, start, dur, ffmpeg)
    cache_file = cache_dir / f"{key}.json"
    if use_cache and cache_file.is_file():
        try:
            got = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = None
        if isinstance(got, dict) and got.get("blocks"):
            got["cache"] = "hit"
            got["cache_file"] = str(cache_file)
            return got
    got = ebur128_series(ffmpeg, path, start, dur, timeout_s, priority=priority)
    got["cache"] = "miss"
    got["cache_file"] = str(cache_file)
    if got.get("blocks") and got.get("returncode") == 0:
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in got.items() if k not in ("args", "cache", "cache_file")}
        with contextlib.suppress(OSError):
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
    return got


# --------------------------------------------------------------------------
# The span statistics: the ride's own gate, over the ride's own window.
# --------------------------------------------------------------------------


def span_stats(
    blocks: list[tuple[float, float]],
    start_s: float,
    dur_s: float,
    ride: dict[str, Any],
    unreachable_below_lufs: float | None = None,
) -> dict[str, Any]:
    """Source loudness over [start_s, start_s + dur_s] of the profiled audio.

    `blocks` are (t, M) in the profiled window's own timebase; the caller shifts
    `start_s` to move the span inside the profile.

    `lift_limited_lufs` is the quietest COMPLETE `RideParams.window_s` window the
    ride could score inside the span -- complete because a truncated edge window
    is not a 45 s window, and dropping those only ever makes this tool stricter.
    It is the RETIRED (pre-U45-answer-2) criterion operand and is kept for the
    record; the criterion now runs on `unreachable_seconds`.

    `unreachable_seconds`, when `unreachable_below_lufs` is given, counts the
    seconds of the span whose OWN centred ride window scores below that level --
    the seconds no amount of the ride's lift could bring to target.  Only complete
    windows are scored: a truncated edge window is not the ride's window, and
    counting it either way would be an invented number.  A window that scores no
    level at all scores nothing the arithmetic can be run on, so it counts as
    neither reachable nor unreachable and is reported separately as
    `unscorable_seconds` (the strict reading: what the order cannot measure, the
    order does not excuse).
    """
    win = float(ride["window_s"])
    step = float(ride["step_s"])
    lo = start_s
    hi = start_s + dur_s
    inside = [(t, m) for t, m in blocks if t >= lo and t < hi]
    span_lufs = ride["gated_loudness"]([m for _t, m in inside])

    half = win / 2.0
    best: tuple[float, float] | None = None
    n_unreachable = 0
    n_scored = 0
    n_unscorable = 0
    if inside:
        levels = ride["sliding_levels"](inside, window_s=win, step_s=step)
        for t, lv in levels:
            if t - half < lo - 1e-9 or t + half > hi + 1e-9:
                continue  # a truncated window is not a windows-worth of material
            if lv is None:
                n_unscorable += 1
                continue
            n_scored += 1
            if best is None or lv < best[1]:
                best = (t, lv)
            if unreachable_below_lufs is not None and lv < unreachable_below_lufs:
                n_unreachable += 1
    return {
        "span_lufs": None if span_lufs is None else round(span_lufs, 3),
        "lift_limited_lufs": None if best is None else round(best[1], 3),
        "lift_limited_at_s": None if best is None else round(best[0], 2),
        "blocks_in_span": len(inside),
        "window_seconds": round(dur_s, 3),
        "unreachable_seconds": (
            None if unreachable_below_lufs is None else round(n_unreachable * step, 3)
        ),
        # Every second of the span whose own centred ride window scored a level:
        # the reachable ones and the unreachable ones.  (Named `scorable`, not
        # "reachable": the count above says which of these are unreachable.)
        "scorable_seconds": (None if unreachable_below_lufs is None else round(n_scored * step, 3)),
        "unscorable_seconds": (
            None if unreachable_below_lufs is None else round(n_unscorable * step, 3)
        ),
        "unreachable_below_lufs": (
            None if unreachable_below_lufs is None else round(unreachable_below_lufs, 3)
        ),
        "ebur128_integrated_lufs": None,
    }


def classify(stat: dict[str, Any], target: float, tol: float, g_max_db: float) -> dict[str, Any]:
    """The owner's criterion, on the ride's own per-second windows.

    `EXCLUDED_QUIET_SOURCE` iff the UNREACHABLE seconds -- those whose own centred
    ride window misses the target's lower edge even at the ride's ceiling -- reach
    a quarter of the window.  The retired quietest-window reading is still
    reported (`max_reachable_lufs`) so both readings stay on the record.
    """
    floor = target - tol
    lift_limited = stat["lift_limited_lufs"]
    span = stat["span_lufs"]
    window_s = float(stat.get("window_seconds") or 0.0)
    unreachable = stat.get("unreachable_seconds")
    below = stat.get("unreachable_below_lufs")
    need = min_unreachable_seconds(window_s) if window_s > 0.0 else None
    max_reachable = None if lift_limited is None else round(lift_limited + g_max_db, 3)
    literal = None if span is None else round(span + g_max_db, 3)
    if unreachable is None or need is None or below is None:
        verdict = "UNRESOLVED"
        why = "the span was not swept second by second, so its reachability is unknown"
    elif unreachable >= need:
        verdict = "EXCLUDED_QUIET_SOURCE"
        why = (
            f"{unreachable:g}s of {window_s:g}s missed {floor:.2f} LUFS even at "
            f"g_max {g_max_db:.2f} dB (source under {below:.2f} LUFS) >= {need}s, "
            "a quarter of the window"
        )
    else:
        verdict = "FAIL"
        why = (
            f"only {unreachable:g}s of {window_s:g}s missed {floor:.2f} LUFS at "
            f"g_max {g_max_db:.2f} dB (< {need}s, a quarter of the window): the "
            f"remaining {max(0.0, window_s - unreachable):g}s was reachable and the "
            "station did not correct it"
        )
    return {
        "classification": verdict,
        "criterion": (
            "unreachable_seconds >= ceil(0.25 * window_seconds) -> EXCLUDED_QUIET_SOURCE, "
            "a second being UNREACHABLE iff its own centred ride window scores below "
            "target_lufs - tolerance_lufs - RideParams.g_max_db"
        ),
        "criterion_floor_lufs": round(floor, 3),
        "window_seconds": window_s,
        "unreachable_seconds": unreachable,
        "min_unreachable_seconds": need,
        "unreachable_below_lufs": below,
        "max_reachable_lufs": max_reachable,
        "retired_reading_note": (
            "lift_limited_lufs + g_max_db, the quietest-single-window reading this "
            "criterion replaces; reported, not used"
        ),
        "detail": why,
        "literal_formula": {
            "note": (
                "the same formula on the span-wide gated loudness; reported for the "
                "record, not used, because the span gate discards quiet material so "
                "this reading goes LOUDER exactly where a window fails hardest"
            ),
            "source_span_lufs": span,
            "plus_g_max_db": literal,
            "would_exclude": None if literal is None else bool(literal < floor),
        },
    }


# --------------------------------------------------------------------------
# Position: T1 (correlation) and T2 (log).
# --------------------------------------------------------------------------


def to_grid_1s(blocks: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """0.1 s momentary blocks -> one 1 s mean per second, gaps interpolated."""
    if not blocks:
        return [], []
    t0, t1 = blocks[0][0], blocks[-1][0]
    n = int(t1 - t0) + 1
    buckets: list[list[float]] = [[] for _ in range(n)]
    for t, m in blocks:
        i = int(t - t0)
        if 0 <= i < n and m == m and m > -200.0:
            buckets[i].append(m)
    times = [t0 + i for i in range(n)]
    values = [sum(b) / len(b) if b else float("nan") for b in buckets]
    known = [i for i, v in enumerate(values) if v == v]
    if len(known) < 2:
        return [], []
    first, last = known[0], known[-1]
    for i in range(first, last + 1):
        if values[i] != values[i]:
            j = i
            while j <= last and values[j] != values[j]:
                j += 1
            k = i - 1
            frac = (i - k) / (j - k)
            values[i] = values[k] + frac * (values[j] - values[k])
    return times[first : last + 1], values[first : last + 1]


def highpass(values: list[float], win_s: float) -> list[float]:
    """Subtract a centred moving average: the ride's slow gain falls out."""
    n = len(values)
    if n == 0:
        return []
    half = max(1, round(win_s / 2.0))
    out: list[float] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        out.append(values[i] - sum(values[lo:hi]) / (hi - lo))
    return out


def pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 8:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0.0 or vb <= 0.0:
        return None
    # best_lag passes a complete equal-length reference slice for every candidate.
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    return cov / math.sqrt(va * vb)


def best_lag(
    air: list[float], ref: list[float], *, nms_s: float, min_overlap: int
) -> dict[str, Any]:
    """Slide `air` along `ref`; return the best offset, r, and the rival's r.

    A lag of `d` seconds means air[0] sits at ref[d].  Rivals are separated by
    `nms_s` so a broad hump cannot masquerade as a second hypothesis.
    """
    n_air, n_ref = len(air), len(ref)
    if n_air < min_overlap or n_ref <= n_air:
        return {"ok": False, "why": f"too short: air={n_air} ref={n_ref} (need air>={min_overlap})"}
    scored: list[tuple[int, float]] = []
    for d in range(0, n_ref - n_air + 1):
        r = pearson(air, ref[d : d + n_air])
        if r is not None:
            scored.append((d, r))
    if not scored:
        return {"ok": False, "why": "no lag produced a defined correlation"}
    scored.sort(key=lambda p: -p[1])
    best_d, best_r = scored[0]
    rival = next((p for p in scored if abs(p[0] - best_d) > nms_s), None)
    # How sharp is the peak?  The half-width of the lag band that still scores
    # >= 90% of the best r is the honest scale of this method's precision, and is
    # used as its uncertainty -- a guessed +/-N s constant would either excuse
    # windows a broad hump cannot support or refuse ones a sharp peak settles.
    band = [
        abs(d - best_d)
        for d, r in scored
        if abs(d - best_d) <= ROBUST_SWEEP_S and r >= 0.9 * best_r
    ]
    return {
        "ok": True,
        "lag_s": best_d,
        "r": round(best_r, 6),
        "rival_lag_s": None if rival is None else rival[0],
        "rival_r": None if rival is None else round(rival[1], 6),
        "margin": None if rival is None else round(best_r - rival[1], 6),
        "curve_half_width_s": round(max(band) if band else 0.0, 1),
        "air_points": n_air,
        "ref_points": n_ref,
        "note": (
            "10 s high-pass, 1 s grid, Pearson r at every whole-second lag; "
            "curve_half_width_s = half-width of the lag band scoring >= 90% of the peak r"
        ),
    }


def correlate(
    air_blocks: list[tuple[float, float]],
    ref_blocks: list[tuple[float, float]],
    ref_start_s: float,
) -> dict[str, Any]:
    """T1: where in the source does this aired audio sit?"""
    _, a_v = to_grid_1s(air_blocks)
    _, r_v = to_grid_1s(ref_blocks)
    if len(a_v) < 20 or len(r_v) < 60:
        return {"ok": False, "why": f"series too short: air={len(a_v)}s ref={len(r_v)}s"}
    lag = best_lag(
        highpass(a_v, AIR_HP_WIN_S), highpass(r_v, AIR_HP_WIN_S), nms_s=AIR_NMS_S, min_overlap=20
    )
    if not lag.get("ok"):
        return lag
    lag["position_s"] = round(ref_start_s + lag["lag_s"], 1)
    lag["ref_start_s"] = ref_start_s
    lag["trusted"] = bool(
        lag["r"] >= AIR_MIN_R and (lag["margin"] is None or lag["margin"] >= AIR_MIN_MARGIN)
    )
    return lag


def _moving_mean(values: list[float], win: int) -> list[float]:
    """Centred moving mean, NaNs skipped; used only to RANK slices, never to score."""
    n = len(values)
    if n == 0:
        return []
    half = max(0, win // 2)
    out: list[float] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        got = [v for v in values[lo:hi] if v == v]
        out.append(sum(got) / len(got) if got else float("nan"))
    return out


def _loud_region(a_v: list[float]) -> tuple[int, int, str]:
    """The loudest contiguous half of the aired window, as (start, length, note).

    Half the window is the largest slice that is still a contiguous loud region
    for any window the rung takes; shorter than LOUD_PART_MIN_S the whole slice is
    used, because a short slice both leaves too few lags for a peak to be sharp
    against and is already the loud part of a short window.
    """
    n = len(a_v)
    span = max(1, n // 2)
    if span < LOUD_PART_MIN_S:
        return 0, n, f"window shorter than {LOUD_PART_MIN_S:g}s: the whole slice is the loud part"
    # Rank on a smoothed curve so a single transient (a gavel, a door) cannot pick
    # the slice; the smoothing window is a twentieth of the slice, at least 1 s.
    smooth = _moving_mean(a_v, max(1, span // 20))
    step = max(1, span // 20)
    best_i, best_level = 0, None
    for i in range(0, n - span + 1, step):
        chunk = [v for v in smooth[i : i + span] if v == v]
        if not chunk:
            continue
        level = sum(chunk) / len(chunk)
        if best_level is None or level > best_level:
            best_i, best_level = i, level
    return best_i, span, f"the loudest {span}s of {n}s (from {best_i}s into the window)"


def loud_part_correlate(
    air_blocks: list[tuple[float, float]],
    ref_blocks: list[tuple[float, float]],
    ref_start_s: float,
) -> dict[str, Any]:
    """Correlate on the LOUD part of the window, and make the two halves agree.

    U64: a quiet head correlates badly -- near-silence has a loudness curve of its
    own, and a whole-slice correlation can lock onto whatever noise resembles it.
    The loud part carries the asset's identity, so:

      1. take the loudest contiguous half of the aired window, never shorter than
         LOUD_PART_MIN_S;
      2. split that region down the middle and correlate each half against the
         reference INDEPENDENTLY, under the same r / margin test as T1;
      3. accept only when both halves lock AND their lags agree within
         LOUD_PART_AGREE_S -- a real lock repeats under the split, a coincidence
         does not.

    The answer reported is the whole loud region's own correlation, so its `r`,
    `margin` and `curve_half_width_s` describe the slice actually used.  Its
    `position_s` is the WINDOW's start, not the region's (the region's lag less its
    offset in the window), so it is directly comparable with `correlate` and with
    the log's t2.  Each half's own lag is reported too, as `region_lag_s`.
    """
    a_t, a_v = to_grid_1s(air_blocks)
    _, r_v = to_grid_1s(ref_blocks)
    if len(a_v) < 20 or len(r_v) < 60:
        return {"ok": False, "why": f"series too short: air={len(a_v)}s ref={len(r_v)}s"}
    start, span, note = _loud_region(a_v)
    region = a_v[start : start + span]
    mid = len(region) // 2
    halves = [region[:mid], region[mid:]]
    if min(len(h) for h in halves) < 20:
        return {
            "ok": False,
            "why": f"the loud region is too short to split ({len(region)}s -> {mid}s a half)",
            "loud_part": {"note": note, "seconds": span, "start_in_window_s": start},
        }
    r_hp = highpass(r_v, AIR_HP_WIN_S)
    halves_out: list[dict[str, Any]] = []
    for i, half in enumerate(halves):
        # Each half is correlated on its own, so its lag is where THAT half
        # begins in the reference.  The two halves sit `offset` seconds apart
        # inside the region, so subtracting the offset turns both into the same
        # unknown -- where the region begins -- and that is what must agree.
        offset = i * mid
        lag = best_lag(highpass(half, AIR_HP_WIN_S), r_hp, nms_s=AIR_NMS_S, min_overlap=20)
        if not lag.get("ok"):
            return {
                "ok": False,
                "why": f"a loud half did not correlate: {lag.get('why')}",
                "loud_part": {"note": note, "seconds": span, "start_in_window_s": start},
            }
        trusted = bool(
            lag["r"] >= AIR_MIN_R and (lag["margin"] is None or lag["margin"] >= AIR_MIN_MARGIN)
        )
        halves_out.append(
            {
                "offset_in_region_s": offset,
                "lag_s": lag["lag_s"],
                "region_lag_s": lag["lag_s"] - offset,
                "r": lag["r"],
                "margin": lag["margin"],
            }
        )
        if not trusted:
            return {
                "ok": False,
                "why": (
                    f"a loud half scored r={lag['r']} margin={lag['margin']} "
                    f"(below {AIR_MIN_R}/{AIR_MIN_MARGIN}): the loud part does not lock either"
                ),
                "loud_part": {
                    "note": note,
                    "seconds": span,
                    "start_in_window_s": start,
                    "halves": halves_out,
                },
            }
    gap = abs(halves_out[0]["region_lag_s"] - halves_out[1]["region_lag_s"])
    if gap > LOUD_PART_AGREE_S:
        return {
            "ok": False,
            "why": (
                f"the two loud halves disagree by {gap}s (> {LOUD_PART_AGREE_S:g}s): they "
                f"put the region {halves_out[0]['region_lag_s']}s and "
                f"{halves_out[1]['region_lag_s']}s into the reference -- a coincidence, "
                "not a lock"
            ),
            "loud_part": {
                "note": note,
                "seconds": span,
                "start_in_window_s": start,
                "halves": halves_out,
            },
        }
    lag = best_lag(highpass(region, AIR_HP_WIN_S), r_hp, nms_s=AIR_NMS_S, min_overlap=20)
    if not lag.get("ok"):
        return lag
    # `lag_s` is where the REGION begins; the region begins `start` seconds into
    # the window, so the window's own start is `lag_s - start`.  T1 has to answer
    # the same question `correlate` answers -- where does the window sit? -- or the
    # +-T1_T2_MAX_DISAGREEMENT_S rule would compare two different things.
    lag["position_s"] = round(ref_start_s + lag["lag_s"] - start, 1)
    lag["ref_start_s"] = ref_start_s
    lag["trusted"] = bool(
        lag["r"] >= AIR_MIN_R and (lag["margin"] is None or lag["margin"] >= AIR_MIN_MARGIN)
    )
    lag["loud_part"] = {
        "note": note,
        "seconds": span,
        "start_in_window_s": start,
        "air_from_s": round(a_t[start], 1) if a_t else None,
        "halves": halves_out,
        "halves_agree_s": round(gap, 1),
    }
    return lag


def air_lock(
    args: argparse.Namespace,
    asset_path: Path,
    air_file: Path | None,
    t2: float,
) -> dict[str, Any]:
    """T1, in four attempts, cheapest and most-anchored first.

      1. the log's own neighbourhood (`t2 +/- REF_WINDOW_S`), whole slice;
      2. that neighbourhood, on its loud part only;
      3. the WHOLE asset, whole slice;
      4. the whole asset, on its loud part only.

    Attempts 1 and 2 are anchored on t2, so the pre-existing rule still holds: a
    lock further than T1_T2_MAX_DISAGREEMENT_S from t2 means one of the two is
    wrong and neither is believed.  Attempts 3 and 4 exist BECAUSE t2 can be wrong
    (U66/C15: a multi-part airing put the log 3,894 s out), so they stand on their
    own r/margin and only REPORT the disagreement -- applying the >60 s rule to
    them would disqualify exactly the evidence they were added to gather.

    Attempts 3 and 4 decode the whole asset, once per asset: the series is cached,
    and the pass runs at IDLE priority because the rung may be on air.
    """
    t1: dict[str, Any] = {"ok": False, "why": "no aired audio supplied"}
    if air_file is None or not Path(air_file).is_file():
        return t1

    air = cached_series(
        args.cache_dir,
        args.ffmpeg,
        Path(air_file),
        None,
        None,
        args.timeout_s,
        use_cache=not args.no_cache,
    )
    air_file = Path(air_file)
    if not air.get("blocks"):
        t1 = {"ok": False, "why": f"aired-audio profile failed (rc={air.get('returncode')})"}
        t1["air_audio"] = str(air_file)
        return t1

    attempts: list[dict[str, Any]] = []

    def run(name: str, ref: dict[str, Any], ref_start: float, whole: bool, loud: bool) -> None:
        if loud:
            got = dict(loud_part_correlate(air["blocks"], ref["blocks"], ref_start))
        else:
            got = dict(correlate(air["blocks"], ref["blocks"], ref_start))
        got["ref_profile"] = {
            "source": str(asset_path),
            "start_s": ref_start,
            "seconds": None if whole else REF_WINDOW_S * 2.0,
            "cache": ref.get("cache"),
            "decode_seconds": ref.get("seconds"),
            "priority": "idle" if whole else "below_normal",
        }
        if whole:
            # Log-independent: it is allowed to disagree, and the disagreement is
            # the finding, not a reason to discard it.
            got["log_independent"] = True
            got["agrees_with_log_within_s"] = (
                round(got["position_s"] - t2, 1) if got.get("ok") else None
            )
        elif got.get("ok") and abs(got["position_s"] - t2) > T1_T2_MAX_DISAGREEMENT_S:
            got["trusted"] = False
            got["why"] = (
                f"correlation says {got['position_s']}s but the log says {t2}s "
                f"(> {T1_T2_MAX_DISAGREEMENT_S:g}s apart): neither is trusted"
            )
        row = {"attempt": name, "anchored_on_log": not whole}
        row.update({k: v for k, v in got.items() if k != "note"})
        attempts.append(row)

    def locked() -> bool:
        return bool(attempts and attempts[-1].get("ok") and attempts[-1].get("trusted"))

    near_start = max(0.0, t2 - REF_WINDOW_S)
    near = cached_series(
        args.cache_dir,
        args.ffmpeg,
        asset_path,
        near_start,
        REF_WINDOW_S * 2.0,
        args.timeout_s,
        use_cache=not args.no_cache,
    )
    if not near.get("blocks"):
        row = {
            "attempt": "log window",
            "anchored_on_log": True,
            "ok": False,
            "why": f"reference profile failed (rc={near.get('returncode')})",
        }
        attempts.append(row)
    else:
        run("log window, whole slice", near, near_start, False, False)
        if not locked():
            run("log window, loud part", near, near_start, False, True)

    if not locked():
        whole = cached_series(
            args.cache_dir,
            args.ffmpeg,
            asset_path,
            None,
            None,
            args.timeout_s,
            use_cache=not args.no_cache,
            priority=IDLE_PRIORITY_CLASS,
        )
        if not whole.get("blocks"):
            attempts.append(
                {
                    "attempt": "whole asset",
                    "anchored_on_log": False,
                    "ok": False,
                    "why": f"whole-asset profile failed (rc={whole.get('returncode')})",
                }
            )
        else:
            run("whole asset, whole slice", whole, 0.0, True, False)
            if not locked():
                run("whole asset, loud part", whole, 0.0, True, True)

    chosen = next((row for row in attempts if row.get("ok") and row.get("trusted")), None)
    if chosen is None:
        # Nothing is trustworthy.  Hand back the last attempt that produced a lag
        # so the reader sees the nearest thing to an answer, else the last row.
        chosen = next(
            (row for row in reversed(attempts) if row.get("ok")),
            attempts[-1] if attempts else {"ok": False, "why": "no position attempt ran"},
        )
    t1 = dict(chosen)
    t1["air_audio"] = str(air_file)
    t1["air_audio_points_0p1s"] = len(air["blocks"])
    t1["attempts"] = attempts
    return t1


# --------------------------------------------------------------------------
# One channel's adjudication.
# --------------------------------------------------------------------------


def instrument_reason(chan: dict[str, Any]) -> str:
    """Why this channel holds no loudness measurement, or "" if it holds one.

    The capture script sets a channel's status straight from its `audio_window`,
    but a non-PASS status is not always a loudness verdict: the capture can also
    fail before any window is scored.  No measurement, no loudness claim -- this
    channel is the instrument's failure, and the predicate is duplicated in
    `rung_check.py` (as the count token already is) so the two agree by
    construction.  The reason is the capture's own words, most specific first:
    the channel's `blocking_reasons`, then the window's `detail`.
    """
    aw = (chan or {}).get("audio_window") or {}
    if aw.get("integrated_lufs") is not None:
        return ""
    blocking = [str(r) for r in ((chan or {}).get("blocking_reasons") or [])]
    if blocking:
        return "; ".join(blocking)
    detail = str(aw.get("detail") or "").strip()
    if detail:
        return detail
    if aw:
        return "the capture recorded an audio window with no integrated loudness"
    return "the capture recorded no audio window"


def adjudicate_channel(
    channel: str,
    chan: dict[str, Any],
    args: argparse.Namespace,
    ride: dict[str, Any],
    transitions: list[tuple[dt.datetime, str, str]],
    media_idx: dict[str, list[Path]],
    report: dict[str, Any],
    digests: DigestCache | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"channel_id": channel, "rung_status": (chan.get("status") or "?")}
    aw = chan.get("audio_window") or {}
    out["air"] = {
        "integrated_lufs": aw.get("integrated_lufs"),
        "target_lufs": aw.get("target_lufs"),
        "tolerance_lufs": aw.get("tolerance_lufs"),
        "captured_at_utc": chan.get("captured_at_utc"),
        "captured_duration_seconds": chan.get("captured_duration_seconds"),
        "detail": aw.get("detail"),
    }
    # No measurement, no loudness verdict (U48): there is no window here for a
    # source measurement to excuse, and a FAIL word would be a claim about the
    # station that nothing in this report supports.  Ahead of the duration check
    # because a missing measurement is the more specific truth.
    reason = instrument_reason(chan)
    if reason:
        out["classification"] = INSTRUMENT_ERROR
        out["detail"] = reason
        return out

    target = float(aw.get("target_lufs", report["target_lufs"]))
    tol = float(aw.get("tolerance_lufs", report["tolerance_lufs"]))
    dur = float(chan.get("captured_duration_seconds") or 0.0)
    if dur <= 0.0:
        out["classification"] = "UNRESOLVED"
        out["detail"] = "the evidence JSON carries no captured window duration"
        return out

    # --- the asset and the leg, from the log ------------------------------
    if not chan.get("captured_at_utc"):
        out["classification"] = "UNRESOLVED"
        out["detail"] = "the evidence JSON carries no captured_at_utc"
        return out
    when_local = local_naive(parse_utc(chan["captured_at_utc"]))
    found = asset_and_leg_start(transitions, channel, when_local)
    if found is None:
        out["classification"] = "UNRESOLVED"
        out["detail"] = f"no ON_AIR transition for {channel} at or before {when_local.isoformat()}"
        return out
    display_name, leg_start = found
    t2 = round((when_local - leg_start).total_seconds(), 1)
    out["asset"] = {"display_name": display_name, "on_air_since_local": leg_start.isoformat()}
    out["log_position"] = {
        "position_s": t2,
        "method": "captured_at_utc - the asset's ON_AIR transition (local clocks)",
        "uncertainty_s": POSITION_UNCERTAINTY_S["log"],
    }

    asset_path, why = find_asset(media_idx, display_name, digests=digests)
    out["asset"]["resolution"] = why
    if asset_path is None:
        out["classification"] = "UNRESOLVED"
        out["detail"] = f"asset not resolved: {why}"
        return out
    out["asset"]["path"] = str(asset_path)
    out["asset"]["bytes"] = asset_path.stat().st_size

    # --- position ---------------------------------------------------------
    supplied = args.position.get(channel, args.position.get("*"))
    air_file = args.air_audio.get(channel, args.air_audio.get("*"))
    # U66 item 2: four attempts, the log's own neighbourhood first and the whole
    # asset last, so a log position that is short by earlier parts of the same
    # asset (C15) no longer decides the measurement's position by default.
    t1 = air_lock(args, asset_path, air_file, t2)
    out["correlation"] = t1

    if supplied is not None:
        position, source, unc = float(supplied), "supplied", POSITION_UNCERTAINTY_S["supplied"]
        if t1.get("ok") and abs(t1["position_s"] - position) > T1_T2_MAX_DISAGREEMENT_S:
            out["classification"] = "UNRESOLVED"
            out["detail"] = (
                f"supplied position {position:g}s disagrees with the correlation "
                f"({t1['position_s']}s) by more than {T1_T2_MAX_DISAGREEMENT_S:g}s"
            )
            return out
    elif t1.get("ok") and t1.get("trusted"):
        position, source = float(t1["position_s"]), "correlation"
        half_width = t1.get("curve_half_width_s")
        if half_width is None:  # a zero half-width is a real, sharp answer
            half_width = POSITION_UNCERTAINTY_S["correlation"]
        unc = max(1.0, min(ROBUST_SWEEP_S, float(half_width)))
    else:
        position, source, unc = float(t2), "log", POSITION_UNCERTAINTY_S["log"]
    out["position"] = {
        "position_s": round(position, 2),
        "source": source,
        "uncertainty_s": unc,
        "uncertainty_basis": (
            "caller's assertion"
            if source == "supplied"
            else "half-width of the lag band scoring >= 90% of the peak r"
            if source == "correlation"
            else "calibrated from the one measured T1-T2 pair plus the ON_AIR announce cadence"
        ),
        "agrees_with_log_within_s": round(position - t2, 1),
    }

    # --- U66 item 3: is the log's position even usable? -------------------
    # Only when nothing else placed the window: a `supplied` position is the
    # caller's assertion and a correlation lock is measured audio, but the log is
    # an inference, and for an asset the station replayed in parts it is an
    # inference from a truncated run.  Measuring at such a position produced the
    # C15 wrong ruling, so the tool stops BEFORE the measurement rather than
    # reporting a loudness verdict about audio nobody has placed.
    if source == "log":
        mp = multi_part_airing(transitions, channel, display_name, when_local, t2)
        out["multi_part"] = mp
        if mp["multi_part"]:
            out["classification"] = "BORDERLINE"
            out["detail"] = POSITION_UNRESOLVED_MULTI_PART
            out["criterion"] = (
                "position unresolved: the correlation could not place the window and "
                "the log's position may count only the last part of a multi-part "
                "airing (U66 item 3) -- a human reads this, it is neither a FAIL nor "
                "an EXCLUDED_QUIET_SOURCE"
            )
            out["summary_line"] = summary_line(out)
            return out

    # --- measure the source over the span ---------------------------------
    #: The level under which a second's own ride window cannot be brought to the
    #: target's lower edge even at the ride's ceiling.  Computed ONCE so the
    #: criterion and every sweep row are measured against the same number.
    unreachable_below = target - tol - float(ride["g_max_db"])
    prof_start = max(0.0, position - SPAN_PAD_S)
    prof = cached_series(
        args.cache_dir,
        args.ffmpeg,
        asset_path,
        prof_start,
        dur + 2.0 * SPAN_PAD_S,
        args.timeout_s,
        use_cache=not args.no_cache,
    )
    if not prof.get("blocks"):
        out["classification"] = "UNRESOLVED"
        out["detail"] = (
            f"no source audio over {prof_start:.1f}s..{prof_start + dur + 2.0 * SPAN_PAD_S:.1f}s "
            f"of {asset_path.name} (ffmpeg rc={prof.get('returncode')}) -- check whether the "
            "resolved position lies past the end of the asset"
        )
        return out
    blocks = [(t + prof_start, m) for t, m in prof["blocks"]]
    out["source_profile"] = {
        "start_s": prof_start,
        "seconds": dur + 2.0 * SPAN_PAD_S,
        "blocks": len(prof["blocks"]),
        "decode_seconds": prof.get("seconds"),
        "cache": prof.get("cache"),
        "ffmpeg": str(args.ffmpeg),
    }
    stat = span_stats(blocks, position, dur, ride, unreachable_below)
    stat["ride_window_s"] = float(ride["window_s"])
    out["source"] = stat

    # --- the sweep: does the verdict survive the position's own error? ----
    gate_shifts = sorted({round(s, 2) for s in _sweep(unc)})
    wide_shifts = sorted({round(s, 2) for s in _sweep(ROBUST_SWEEP_S)})
    gate, wide = [], []
    for shift in gate_shifts:
        s = span_stats(blocks, position + shift, dur, ride, unreachable_below)
        s["ride_window_s"] = float(ride["window_s"])
        c = classify(s, target, tol, float(ride["g_max_db"]))
        gate.append(
            {
                "shift_s": shift,
                "lift_limited_lufs": s["lift_limited_lufs"],
                "unreachable_seconds": s["unreachable_seconds"],
                "classification": c["classification"],
            }
        )
    for shift in wide_shifts:
        s = span_stats(blocks, position + shift, dur, ride, unreachable_below)
        s["ride_window_s"] = float(ride["window_s"])
        c = classify(s, target, tol, float(ride["g_max_db"]))
        wide.append(
            {
                "shift_s": shift,
                "lift_limited_lufs": s["lift_limited_lufs"],
                "unreachable_seconds": s["unreachable_seconds"],
                "classification": c["classification"],
            }
        )
    out["sweep"] = {
        "gating": gate if unc > 0.0 else [],
        "gating_uncertainty_s": unc,
        "reported": wide,
        "reported_half_width_s": ROBUST_SWEEP_S,
    }

    # --- classify: the count at the MEASURED position decides (U45 answer 3)
    # The count is a duration measured at the position the caller or the
    # correlation chose, so a sweep over position must not be allowed to rule on
    # it: the sweeps below are reported, and a thin margin is flagged for a human
    # rather than turning the window into an unresolvable one.
    verdict = classify(stat, target, tol, float(ride["g_max_db"]))
    out["classification"] = verdict["classification"]
    out["detail"] = verdict["detail"]
    need = verdict["min_unreachable_seconds"]
    counts = [row["unreachable_seconds"] for row in wide if row["unreachable_seconds"] is not None]
    #: The reported range is the WIDER +/-30 s sweep, which always brackets the
    #: measured position (`wide` has shift 0 in it), so the line can always show a
    #: range even when the position comes from the caller with zero uncertainty.
    out["unreachable_range_s"] = [min(counts), max(counts)] if counts else None
    #: The range straddles the need when the sweep holds positions both under it
    #: and at/over it: the verdict would flip with position there, so that window
    #: is read by hand (the coordinator's own review rule).
    out["borderline"] = bool(need is not None and counts and min(counts) < need <= max(counts))
    out["sweep_note"] = (
        "reported only: the verdict is the unreachable count at the measured position "
        "(U45 answer 3), so a sweep over position cannot make this window UNRESOLVED"
    )
    out.update(
        {
            k: verdict[k]
            for k in (
                "criterion",
                "criterion_floor_lufs",
                "window_seconds",
                "unreachable_seconds",
                "min_unreachable_seconds",
                "unreachable_below_lufs",
                "max_reachable_lufs",
                "retired_reading_note",
                "literal_formula",
            )
        }
    )
    out["summary_line"] = summary_line(out)
    return out


def _sweep(half_width_s: float) -> list[float]:
    if half_width_s <= 0.0:
        return [0.0]
    step = max(1.0, half_width_s / 5.0)
    out: list[float] = []
    s = -half_width_s
    while s <= half_width_s + 1e-9:
        out.append(s)
        s += step
    return out


def summary_line(chan: dict[str, Any]) -> str:
    """One line naming the window, its asset, its position, its levels, the count."""
    asset = (chan.get("asset") or {}).get("display_name") or "?"
    pos = (chan.get("position") or {}).get("position_s")
    src = (chan.get("source") or {}).get("lift_limited_lufs")
    span = (chan.get("source") or {}).get("span_lufs")
    air = (chan.get("air") or {}).get("integrated_lufs")
    reach = chan.get("max_reachable_lufs")
    unreach = chan.get("unreachable_seconds")
    scorable = (chan.get("source") or {}).get("scorable_seconds")
    window = chan.get("window_seconds")
    need = chan.get("min_unreachable_seconds")
    rng = chan.get("unreachable_range_s")
    pos_s = "?" if pos is None else f"{pos:g}s"
    src_s = "?" if src is None else f"{src:g}"
    span_s = "?" if span is None else f"{span:g}"
    air_s = "?" if air is None else f"{air:g}"
    reach_s = "?" if reach is None else f"{reach:g}"
    # The count the verdict turns on, over the seconds the ride's own centred
    # window could score.  `?` if the span was not swept, or if the report predates
    # the count criterion, so an old report read by this revision degrades visibly
    # rather than implying a number it never measured.  The need is a quarter of
    # the FULL window (240 s -> 60 s) and is not rescaled by the scorable count;
    # the window is printed beside it so the gap between the two is legible.
    if unreach is None or scorable is None:
        unreach_s = "unreach=?"
    else:
        rng_s = "range ?" if not rng else f"range {rng[0]:g}-{rng[1]:g}"
        need_s = "?" if need is None else f"{need:g}"
        unreach_s = f"unreach={unreach:g}/{scorable:g}s ({rng_s}, need {need_s})"
        if window is not None:
            unreach_s += f" window={window:g}s"
        if chan.get("borderline"):
            unreach_s += " BORDERLINE"
    return (
        f"{chan['channel_id']}={chan['classification']} "
        f'asset="{asset}" pos={pos_s}({chan.get("position", {}).get("source", "?")}) '
        f"src45min={src_s}LUFS srcspan={span_s}LUFS maxreach={reach_s}LUFS air={air_s}LUFS "
        f"{unreach_s}"
    )


# --------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("evidence", type=Path, help="a rung loudness-NN.json")
    p.add_argument("--out", type=Path, default=None, help="default <evidence>.adjudicated.json")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    p.add_argument("--ffmpeg", type=Path, default=None, help="default: the JSON's own ffmpeg")
    p.add_argument("--site-packages", type=Path, default=STATION_SITE_PACKAGES)
    p.add_argument(
        "--air-audio",
        action="append",
        default=[],
        metavar="[CH=]PATH",
        help="aired audio for the correlation (T1); CH=all applies to every channel",
    )
    p.add_argument(
        "--position",
        action="append",
        default=[],
        metavar="[CH=]SEC",
        help="assert the span's position in the asset instead of resolving it",
    )
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    p.add_argument("--scratch-dir", type=Path, default=DEFAULT_SCRATCH_DIR)
    p.add_argument("--timeout-s", type=float, default=3600.0)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p


def parse_assignments(items: list[str], cast: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items:
        if "=" in item:
            ch, _, val = item.partition("=")
            out[ch.strip()] = cast(val)
        else:
            out["*"] = cast(item)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.position = parse_assignments(args.position, float)
    args.air_audio = parse_assignments(args.air_audio, str)

    report: dict[str, Any] = {
        "tool": "loudness_window_adjudicate",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        # Which interpreter judged: the rung may spawn this under a different
        # venv than the one it was written against, and the report is the only
        # place a later reader can see that.  This tool itself is stdlib-only.
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "evidence": str(args.evidence),
        "log": str(args.log),
        "media_root": str(args.media_root),
        "channels": {},
    }
    try:
        ev = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report["error"] = f"unreadable evidence {args.evidence}: {exc}"
        _emit(report, args)
        return 2
    report["target_lufs"] = float(ev.get("target_lufs", TARGET_FALLBACK))
    report["tolerance_lufs"] = float(ev.get("tolerance_lufs", TOLERANCE_FALLBACK))
    report["rung_verdict"] = ev.get("verdict")

    ffmpeg = args.ffmpeg or Path(ev.get("ffmpeg") or DEFAULT_FFMPEG)
    if not ffmpeg.is_file():
        report["error"] = f"ffmpeg not found: {ffmpeg}"
        _emit(report, args)
        return 2
    args.ffmpeg = ffmpeg
    report["ffmpeg"] = str(ffmpeg)

    try:
        ride = load_ride(args.site_packages)
    except Exception as exc:
        report["error"] = f"installed loudness_ride could not be read: {exc!r}"
        _emit(report, args)
        return 2
    report["ride"] = {
        k: v
        for k, v in ride.items()
        if k
        in (
            "module_path",
            "module_sha256",
            "module_mtime",
            "window_s",
            "step_s",
            "g_max_db",
            "g_min_db",
        )
    }
    report["method"] = {
        "measurement": "ebur128=peak=true, input-side -ss, ride's own regexes (build_source_series_args)",
        "gating": "loudness_ride.gated_loudness over the 0.1 s momentary blocks",
        "window": "loudness_ride.sliding_levels, complete windows only, step 1 s",
        "air_highpass_s": AIR_HP_WIN_S,
        "air_min_r": AIR_MIN_R,
        "air_min_margin": AIR_MIN_MARGIN,
        "position_uncertainty_defaults_s": POSITION_UNCERTAINTY_S,
        "position_uncertainty_note": (
            "the correlation method uses the measured curve half-width when it has one "
            "(clamped to >= 1 s); the value listed here is its fallback when it does not. "
            "Each channel reports the uncertainty it actually used, with its basis."
        ),
    }

    transitions = on_air_transitions(args.log)
    report["on_air_transitions"] = len(transitions)
    media_idx = index_media(args.media_root)
    report["media_files_indexed"] = sum(len(v) for v in media_idx.values())
    #: Copy identity survives a run: the rung calls this every 30 minutes and a
    #: 4 GB multi-copy asset must not be re-hashed each time.
    digests = DigestCache(args.cache_dir / "digests.json" if args.cache_dir else None)
    report["digest_cache"] = {
        "path": None if digests.path is None else str(digests.path),
        "entries": len(digests.data),
    }
    hashed_before = set(digests.data)

    chans = ev.get("channels") or {}
    report["channels"] = {}
    for channel in ("public", "government", "education"):
        chan = chans.get(channel)
        if not isinstance(chan, dict):
            report["channels"][channel] = {
                "channel_id": channel,
                "classification": "UNRESOLVED",
                "detail": "channel absent from the evidence JSON",
            }
            continue
        if (chan.get("status") or "").upper() == "PASS":
            report["channels"][channel] = {
                "channel_id": channel,
                "rung_status": chan.get("status"),
                "classification": "NOT_APPLICABLE",
                "detail": "the rung already scored this window PASS",
            }
            continue
        try:
            report["channels"][channel] = adjudicate_channel(
                channel, chan, args, ride, transitions, media_idx, report, digests
            )
        except Exception as exc:
            report["channels"][channel] = {
                "channel_id": channel,
                "classification": "UNRESOLVED",
                "detail": f"adjudication error: {exc!r}",
            }
    report["summary"] = [
        c.get("summary_line") or f"{c['channel_id']}={c['classification']} {c.get('detail', '')}"
        for c in report["channels"].values()
    ]
    digests.save()
    report["digest_cache"]["new_entries"] = sorted(set(digests.data) - hashed_before)
    _emit(report, args)
    return 0


def _emit(report: dict[str, Any], args: argparse.Namespace) -> None:
    """Write the report by atomic replace.

    `rung_check.py` reads this file every 30 minutes while the rung runs, so it
    must never observe a half-written document: the text goes to a sibling temp
    file and moves into place in one operation.  A failed write leaves the
    previous report intact and records the error in the in-memory report.
    """
    out = args.out or args.evidence.with_suffix(".adjudicated.json")
    try:
        if args.scratch_dir:
            args.scratch_dir.mkdir(parents=True, exist_ok=True)
        report["_written"] = str(out)
        tmp = out.with_name(f"{out.name}.tmp{os.getpid()}")
        try:
            tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
            tmp.replace(out)
        except OSError:
            tmp.unlink(missing_ok=True)
            del report["_written"]
            raise
    except OSError as exc:
        report["_write_error"] = str(exc)
    if not args.quiet:
        print(json.dumps(report, indent=1), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
