#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Bounded, read-only real-output verifier for beta.10 three-channel live HLS.

Why this exists (scope of the claim)
------------------------------------
``C:\CivicCastTester\soak-beta9-2h-20260921\rung_30m.py`` PASSes a rung when,
for every channel, the public API reports ``ON_AIR`` and the caption sidecar
``active.vtt`` is >7 bytes and grows.  That is an API + sidecar-shape gate: it
never opens an emitted HLS segment, never proves a viewer could decode the
bytes, never proves the muxed timestamps are continuous, never proves audio is
audible, and never proves a single caption bit reached the transport stream.

This verifier *supplements* that gate; it does not replace it.  It reads the
real on-disk live-HLS output (``playlist.m3u8`` + ``seg*.ts``) for the three
station channels and produces a per-channel machine-readable evidence object
with tool versions, segment identity/hashes, and measured evidence for:

* playlist presence and advancement over a bounded window,
* that every playlist-referenced segment exists (fresh, not stale),
* H.264 video + AAC audio decodability (decode a bounded set of segments),
* per-segment PTS and PCR monotonicity plus MPEG-TS continuity-counter
  evidence via TSDuck ``analyze``,
* audio presence / integrated loudness / true-peak / silence measurement,
* caption decode-back from the emitted TS, using the product's proven-sensitive
  ffmpeg ``movie=...[out0+subcc]`` route (``civiccast.egress.caption_proof``).
  An earlier GStreamer ``h264ccextractor -> ccconverter -> cea608tott`` child
  was found INSENSITIVE by independent QA (0 bytes on a known-positive fixture)
  and has been removed.

Honesty posture
---------------
Missing data or a tool error is ``FAIL``/``UNVERIFIED``, never ``PASS``.
Caption decode-back is reported ``NOT_PROVEN`` when no real decoder path is
available and the overall release-grade verdict fails closed -- caption
presence is NEVER inferred from ``active.vtt``.  Thresholds are not invented
here: the loudness target/tolerance and the zero-tolerance continuity rule are
imported from the project's own policy modules (``civiccast.stream.loudness``
and ``civiccast.egress.compliance`` / ``civiccast.egress.preparer``); the HLS
window/segment cadence is imported from ``civiccast.egress.sinks.HlsSink``.

Read-only guarantee
-------------------
Nothing here writes to, restarts, or controls the live station.  The verifier
only reads files under ``--hls-root`` and shells out to read-only analyzers
(``ffprobe``/``ffmpeg``/``tsp`` and the packaged ``gst-inspect-1.0``).  The
only files it creates are its own evidence JSON under ``--out``.

Boundary of this component
--------------------------
This is ONE component.  It does NOT run the 30m -> 2h -> 4h -> 8h rungs and
does NOT assert that ladder passed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Thresholds sourced from project policy (never invented/weakened) -------

#: OTT-typical streaming loudness target and tolerance, from the unified spec
#: (Section 16.2a: "-16 LUFS, +/-1 LU") surfaced by civiccast.stream.loudness.
OTT_LOUDNESS_TARGET_LUFS: Final[float] = -16.0
OTT_LOUDNESS_TOLERANCE_LUFS: Final[float] = 1.0
#: Minimum measured window length for an INTEGRATED BS.1770 loudness value to be
#: release-grade. The live HLS window is only ~6x2s (== ~8s of usable audio when
#: the newest N segments are measured), far too short to establish an integrated
#: -16 +/- 1 LUFS program measurement. Below this floor the verifier reports the
#: measured LUFS but marks audio UNVERIFIED (not release-grade) rather than PASS
#: or FAIL. Target and tolerance are NOT changed; only the adequacy of the window
#: is gated. A separate continuous >=2-3 minute capture is required to prove the
#: integrated target.
MIN_RELEASE_GRADE_AUDIO_SECONDS: Final[float] = 120.0

#: A measurement at or below this integrated LUFS is indistinguishable from
#: silence -- imported policy constant (civiccast.egress.preparer).
SILENCE_FLOOR_LUFS: Final[float] = -60.0
if (ROOT / "civiccast" / "egress" / "preparer.py").is_file():
    try:  # pragma: no cover - import-time policy pin, exercised at runtime
        from civiccast.egress.preparer import _LOUDNESS_SILENCE_FLOOR_LUFS as _POLICY_FLOOR

        SILENCE_FLOOR_LUFS = float(_POLICY_FLOOR)
    except Exception:
        pass

#: MPEG-TS continuity is zero-tolerance by project policy
#: (civiccast.egress.compliance: "continuity stays zero-tolerance").
CONTINUITY_TOLERANCE: Final[int] = 0

#: HLS window/segment cadence from civiccast.egress.sinks.HlsSink.
HLS_TARGET_SEGMENT_SECONDS: Final[float] = 2.0
HLS_PLAYLIST_SIZE: Final[int] = 6

#: PTS/PCR are 90 kHz MPEG-TS clocks; allow at most one tick of jitter and
#: require strictly-forward motion between consecutive segments.
TS_CLOCK_HZ: Final[int] = 90_000

REQUIRED_CHANNELS: Final[tuple[str, ...]] = ("public", "government", "education")

def validate_max_segments(max_segments: int) -> int:
    """Return ``max_segments`` iff it is an int in the explicit safe range.

    ``list(seq)[-max_segments:]`` is ALL for 0 ([-0:]) and for any negative or
    absurdly large value, defeating the bounded-scratch guarantee. Enforce
    1..MAX_SEGMENTS_UPPER_BOUND and fail closed otherwise.
    """
    if isinstance(max_segments, bool) or not isinstance(max_segments, int):
        raise ValueError(f"max_segments must be an int, got {type(max_segments).__name__}")
    if not (1 <= max_segments <= MAX_SEGMENTS_UPPER_BOUND):
        raise ValueError(
            f"max_segments must be within 1..{MAX_SEGMENTS_UPPER_BOUND}, got {max_segments}"
        )
    return max_segments


def validate_channel_ids(channel_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Reject channel ids that are not bare, safe path components.

    ``channel_id`` is joined onto the HLS root, so a value like ``..\\..\\x`` or
    an absolute path could read outside the root. Require a non-empty bare name
    (no separators, no traversal) for EVERY channel before any read. Known
    required channel names are ordinary bare names, so this does not forbid them.
    """
    if not channel_ids:
        raise ValueError("channel_ids must not be empty")
    for cid in channel_ids:
        if (
            not isinstance(cid, str)
            or not cid
            or cid != cid.strip()
            or "/" in cid
            or "\\" in cid
            or cid in (".", "..")
            or Path(cid).name != cid
        ):
            raise ValueError(f"unsafe channel id rejected: {cid!r}")
    return channel_ids

#: Bounded decode/measure budget: number of newest listed segments to analyze.
DEFAULT_MAX_SEGMENTS: Final[int] = 4
#: Hard upper bound for --max-segments. The live HLS window is ~6x2s, so a few
#: segments are all that can ever be present; anything larger is a
#: misconfiguration that would only widen scratch scope. 1..16 is the explicit
#: safe finite range (0 or negative would make ``[-max_segments:]`` == ALL, and a
#: huge value weakens the "bounded scratch" guarantee).
MAX_SEGMENTS_UPPER_BOUND: Final[int] = 16
#: Bounded total verifier wall-clock ceiling (per external analyzer call).
ANALYZER_TIMEOUT_SECONDS: Final[float] = 90.0

#: The relay replaces ``playlist.m3u8`` atomically and rotates segments while
#: this verifier reads them, so a read that lands inside that window on Windows
#: gets EACCES (or ENOENT for the instant the name is gone).  A transient race
#: is not a station fault: every live read is retried this many times, this far
#: apart, before it fails exactly as it did before the retry existed (U48).
RACE_RETRY_ATTEMPTS: Final[int] = 20
RACE_RETRY_DELAY_SECONDS: Final[float] = 0.1

#: Caption decode-back spans the newest ~60 s of FINISHED segments (U48
#: follow-on).  The old 4-segment (~8 s) window failed on any speech pause: on
#: 2026-09-26 verify #4 it failed government (its sidecar reading "take a
#: five-minute break" -- a recess) and education while BOTH workers had injected
#: 14-17 captions in the preceding minute.  One cue anywhere in the span is a
#: pass; a clean span with no cue at all is still a FAIL.
CAPTION_WINDOW_SECONDS: Final[float] = 60.0
#: The newest two segments are excluded: the relay may still be writing them.
CAPTION_WINDOW_EXCLUDE_NEWEST: Final[int] = 2
#: Hard cap on copied/decoded segments, so the window stays bounded even if the
#: segment duration is misreported.
CAPTION_WINDOW_MAX_SEGMENTS: Final[int] = 40
#: A candidate emitted this much longer ago than the newest candidate belongs to
#: a previous run, not this window.  The live channel dir keeps fossils from
#: earlier runs -- public `seg000018677.ts` (Sep 19) beside `seg000001284.ts` --
#: and a fossil's cues would be a false PASS, so the walk stops at this floor.
CAPTION_WINDOW_STALENESS_SECONDS: Final[float] = 900.0

# --- U50: the keeper's copies, without which the 60 s window is a fiction ---
#
# Measured live 2026-09-26: `live-hls\public\` held 7 live segments (14:36:04 -
# 14:36:16, 2 s each) and 43 fossils; a verify therefore saw 7 fresh candidates,
# excluded the newest 2 and reported `span_seconds` 10.0 on all three channels of
# rung 8h-post-u47.  The relay deletes each segment as it rotates it out, so the
# media a 60 s window needs is GONE by the time the verifier looks for it.
# `bin\segment_keeper.py` copies finished segments aside before that happens and
# rewrites a heartbeat file every loop; the window is the live dir UNION those
# copies, and only while that heartbeat is fresh.

#: The keeper's liveness file, inside the keep dir (one keep dir for all channels,
#: which is why the channels live in subdirectories of it).
CAPTION_KEEP_HEARTBEAT_NAME: Final[str] = "heartbeat.json"
#: `%TEMP%\cc-caption-keep`: the folder `bin\segment_keeper.py` writes by default
#: and the folder this verifier looks in by default, so the 8 h rung ALREADY
#: RUNNING (which loaded its own copy of rung.ps1 at start, without the new
#: option) benefits as soon as a keeper is started beside it.
CAPTION_KEEP_DIR_NAME: Final[str] = "cc-caption-keep"
#: The keeper rewrites its heartbeat every 4 s.  Older than this and the copies
#: are a stopped run's leftovers, which is exactly the fossil group the window
#: must never reach.
CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS: Final[float] = 30.0
#: A window is only honest while it is CONTIGUOUS, and `count x segment_seconds`
#: claims a span the media may not cover when the keeper missed a segment (it
#: polls every 4 s and copies everything not yet copied, so this is rare, but a
#: hole must shorten the window rather than hide inside it).  The walk stops when
#: the step between adjacent candidates exceeds this multiple of the segment
#: duration; every healthy fixture spaces segments at exactly 2.0 s.
CAPTION_KEEP_GAP_TOLERANCE: Final[float] = 1.5

#: The playout worker prints one ``CTRL caption <ch>: received=... in 60s`` line
#: per 60 s window that carried caption activity, and one WARNING after ten
#: silent windows.  The receipt is read from the tail of that log (bounded: the
#: log runs for the life of the station) and a log older than this floor no
#: longer speaks for the window under judgement -- a dead worker's last line is
#: not evidence about the last 60 s.
CAPTION_RECEIPT_TAIL_BYTES: Final[int] = 65536
CAPTION_RECEIPT_FRESH_SECONDS: Final[float] = 180.0
CAPTION_RECEIPT_RE: Final[re.Pattern[str]] = re.compile(
    r"CTRL caption (?P<channel>\S+): received=(?P<received>\d+) injected=(?P<injected>\d+) "
    r"replayed=(?P<replayed>\d+) rejected=(?P<rejected>\d+) in (?P<window>\d+(?:\.\d+)?)s"
)
CAPTION_SILENT_RE: Final[re.Pattern[str]] = re.compile(
    r"CTRL caption (?P<channel>\S+): WARNING no caption command received for "
    r"(?P<seconds>\d+(?:\.\d+)?)s"
)

#: The two errnos an atomic replace produces, and only those two: a retry here
#: must never absorb a real permission failure or a real absence past the
#: budget.
_RACE_ERRORS: Final[tuple[type[OSError], ...]] = (PermissionError, FileNotFoundError)


class Verdict:
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    NOT_PROVEN = "NOT_PROVEN"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    """SHA-256 of a text value, so evidence can identify output without
    exposing its content (caption cue bytes must never be persisted)."""

    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


#: Exact scratch dirs THIS process created, by resolved absolute path. Ownership
#: is proven by this set -- a directory name/prefix alone is NOT proof (an
#: unrelated ``civiccast-verify-*`` dir under temp must never be deleted).
_OWNED_SCRATCH: set[str] = set()


def _make_scratch_dir() -> Path:
    """Create (and register) a writable scratch dir; never in the live HLS root."""

    import tempfile as _tf

    for base in (os.environ.get("TEMP"), os.environ.get("TMP"), None):
        try:
            created = Path(_tf.mkdtemp(prefix="civiccast-verify-", dir=base))
        except OSError:
            continue
        # Registration is REQUIRED: an unregistered scratch dir would be refused
        # by _safe_rmtree and leak. If we cannot resolve/register it, back out of
        # the JUST-CREATED EMPTY dir using NON-RECURSIVE rmdir only -- never a
        # recursive delete on an unvalidated path (Windows safety rule). If it is
        # unexpectedly non-empty, rmdir fails and we fail closed, leaving it for a
        # human rather than recursing.
        try:
            resolved = created.resolve()
        except OSError:
            with contextlib.suppress(OSError):
                created.rmdir()
            continue
        _OWNED_SCRATCH.add(str(resolved))
        return created
    raise RuntimeError("no writable scratch directory available")

def _safe_rmtree(path: Path) -> None:
    """rmtree ONLY a scratch dir THIS process created (exact ownership).

    Ownership = the resolved absolute path is in ``_OWNED_SCRATCH``, i.e. it was
    returned by :func:`_make_scratch_dir` in this process. A directory that merely
    has the ``civiccast-verify-`` prefix, or merely lives under temp, is NOT ours
    and is refused. Additionally require the resolved target to be a STRICT
    descendant of a real temp root (never TEMP/TMP itself) before recursing.
    """
    import tempfile as _tf

    try:
        resolved = path.resolve()
    except OSError:
        return
    # EXACT ownership: must be a scratch dir we registered at creation time.
    if str(resolved) not in _OWNED_SCRATCH:
        return
    if not resolved.is_dir():
        return
    roots = []
    for base in (os.environ.get("TEMP"), os.environ.get("TMP"), _tf.gettempdir()):
        if base:
            try:
                roots.append(Path(base).resolve())
            except OSError:
                continue
    for root in roots:
        # STRICT descendant: resolved must be BELOW root, never root itself.
        if root in resolved.parents:
            shutil.rmtree(resolved, ignore_errors=True)
            _OWNED_SCRATCH.discard(str(resolved))
            return
    # Not a strict temp descendant: refuse.


def _read_live_text(path: Path) -> str:
    """Read a live file whole, retrying a racing atomic replace.

    One handle per attempt: opened, read to EOF, closed before any retry.  A
    handle held across a retry can block the relay's replace, which is the very
    fault this absorbs.  Raises the last race error once the budget is spent.
    """

    last: OSError | None = None
    for attempt in range(RACE_RETRY_ATTEMPTS):
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except _RACE_ERRORS as exc:
            last = exc
            if attempt + 1 < RACE_RETRY_ATTEMPTS:
                time.sleep(RACE_RETRY_DELAY_SECONDS)
    if last is None:  # pragma: no cover - the budget is at least one attempt
        raise RuntimeError(f"unreadable live file: {path}")
    raise last


def _open_live_fd(src: Path) -> int:
    """One read-only open of a live file.  A race error propagates unhandled."""

    return os.open(str(src), os.O_RDONLY | getattr(os, "O_BINARY", 0))


def _read_live_segment(src: Path) -> tuple[bytes, os.stat_result, os.stat_result] | None:
    """One read attempt of a live segment; ``None`` when the attempt is unstable.

    ``PermissionError`` / ``FileNotFoundError`` -- the relay's replace racing
    this read -- PROPAGATE, so ``_snapshot_segment`` can retry them rather than
    score a station fault.  Every other failure returns ``None``, exactly as the
    single-attempt copy did before the retry existed.
    """

    try:
        fd = _open_live_fd(src)
    except _RACE_ERRORS:
        raise
    except OSError:
        return None
    try:
        try:
            pre_stat = os.fstat(fd)
        except OSError:
            return None
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:
            return None
        data = b"".join(chunks)
        try:
            post_stat = os.fstat(fd)
        except OSError:
            # Handle closed under us; treat as unstable and fail closed.
            return None
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    if not data:
        # zero-byte/torn read: never accept as a snapshot
        return None
    if post_stat.st_size != pre_stat.st_size or post_stat.st_mtime_ns != pre_stat.st_mtime_ns:
        # source identity changed across the read -> unstable; fail closed.
        return None
    return data, pre_stat, post_stat


def _snapshot_segment(src: Path, scratch: Path) -> tuple[Path | None, str | None]:
    """Copy a live segment's bytes into private scratch EARLY, read-only-on-live.

    Returns ``(snapshot_path, sha256)`` or ``(None, None)`` on a copy race. The
    live HLS window (typically 6x2s) deletes segments underneath a slow
    analyzer, so analysis/decode-back must run on a private copy captured at
    identity time -- never on the live path, which can vanish mid-run. The
    source is opened read-only and never modified or deleted.

    The read is retried through a racing atomic replace (U48): an ``EACCES`` or
    ``ENOENT`` inside the relay's replace window is not a station fault, so the
    attempt is repeated rather than reported.  A read that is still unreadable
    once the budget is spent returns ``(None, None)`` -- exactly what it
    returned before the retry existed.

    Capture the source identity from the SAME open handle BEFORE and AFTER the
    read, via os.fstat on one fd. This is the strongest check available without
    taking an OS-level lock (which the read-only live path deliberately avoids):
      * pre = fstat(fd) before reading bytes,
      * data = read all bytes from that same fd,
      * post = fstat(fd) after reading.
    A same-size rewrite during the read that stabilizes before any stat is NOT
    fully detectable, so we make NO atomicity claim: we only fail closed when
    the pre/post identity differs (size OR mtime_ns), and the recorded evidence
    is the CAPTURED BYTES hash. Rotation (the fd no longer resolves on the live
    path) is handled explicitly and does not invalidate the captured bytes.
    """

    read: tuple[bytes, os.stat_result, os.stat_result] | None = None
    for attempt in range(RACE_RETRY_ATTEMPTS):
        try:
            read = _read_live_segment(src)
        except _RACE_ERRORS:
            if attempt + 1 < RACE_RETRY_ATTEMPTS:
                time.sleep(RACE_RETRY_DELAY_SECONDS)
                continue
            return None, None
        break
    if read is None:
        return None, None
    data = read[0]
    digest = hashlib.sha256(data).hexdigest()
    dst = scratch / src.name
    try:
        dst.write_bytes(data)
        # verify the SCRATCH COPY matches the captured bytes exactly
        if hashlib.sha256(dst.read_bytes()).hexdigest() != digest:
            return None, None
    except OSError:
        return None, None
    return dst, digest


def _run(cmd: list[str], *, timeout: float = ANALYZER_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run a read-only analyzer; never raise on nonzero exit."""
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": repr(exc), "returncode": None, "stdout": "", "stderr": ""}
    return {
        "ok": completed.returncode == 0,
        "error": None,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }

# --- Tool discovery (installed runtime first, then PATH) --------------------


def _civiccast_native_root() -> Path | None:
    candidates = [
        Path(os.environ["CIVICCAST_NATIVE_ROOT"]) if os.environ.get("CIVICCAST_NATIVE_ROOT") else None,
        Path(r"C:\Program Files\CivicCast (Native)"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def tool_versions() -> dict[str, Any]:
    """Record exact tool versions + resolved paths for the evidence object."""

    versions: dict[str, Any] = {}
    native = _civiccast_native_root()

    ffprobe: Path | None = None
    ffmpeg: Path | None = None
    if native is not None:
        bundled = native / "dependencies" / "ffmpeg" / "bin"
        if (bundled / "ffprobe.exe").is_file():
            ffprobe = bundled / "ffprobe.exe"
        if (bundled / "ffmpeg.exe").is_file():
            ffmpeg = bundled / "ffmpeg.exe"
    if ffprobe is None:
        found = shutil.which("ffprobe")
        ffprobe = Path(found) if found else None
    if ffmpeg is None:
        found = shutil.which("ffmpeg")
        ffmpeg = Path(found) if found else None

    if ffprobe is not None:
        result = _run([str(ffprobe), "-version"])
        versions["ffprobe"] = {
            "path": str(ffprobe),
            "version": result["stdout"].splitlines()[0] if result["stdout"] else None,
            "ok": result["ok"],
        }
    else:
        versions["ffprobe"] = {"path": None, "version": None, "ok": False}

    if ffmpeg is not None:
        result = _run([str(ffmpeg), "-version"])
        versions["ffmpeg"] = {
            "path": str(ffmpeg),
            "version": result["stdout"].splitlines()[0] if result["stdout"] else None,
            "ok": result["ok"],
        }
    else:
        versions["ffmpeg"] = {"path": None, "version": None, "ok": False}

    tsp: Path | None = None
    if native is not None:
        packs = native / "packs"
        if packs.is_dir():
            matches = sorted(packs.rglob("tsp.exe"))
            if matches:
                tsp = matches[0]
    if tsp is None:
        found = shutil.which("tsp")
        tsp = Path(found) if found else None
    if tsp is not None:
        result = _run([str(tsp), "--version"])
        text = (result["stdout"] + result["stderr"]).strip()
        versions["tsp"] = {
            "path": str(tsp),
            "version": text.splitlines()[0] if text else None,
            "ok": bool(text),
        }
    else:
        versions["tsp"] = {"path": None, "version": None, "ok": False}

    gst_root = None
    if native is not None:
        candidate = native / "runtime" / "dependencies" / "gstreamer"
        if candidate.is_dir():
            gst_root = candidate
    versions["gstreamer_runtime"] = {
        "path": str(gst_root) if gst_root else None,
        "present": gst_root is not None,
    }
    return versions


def _ffmpeg_path() -> Path | None:
    """Resolve the packaged ffmpeg binary (the proven subcc decode route)."""

    versions = tool_versions()
    resolved = versions.get("ffmpeg", {}).get("path")
    return Path(resolved) if resolved else None


def caption_decoder_available() -> dict[str, Any]:
    """Prove the proven-sensitive ffmpeg ``subcc`` decoder path is available.

    The earlier GStreamer ``h264ccextractor -> ccconverter -> cea608tott``
    child was found INSENSITIVE by independent QA: it returns EOS/0 bytes on a
    known-positive CEA-708 fixture while ffmpeg's ``movie=...[out0+subcc]``
    route returns a real cue. This verifier therefore uses the product's proven
    ``ffmpeg-subcc`` path (civiccast.egress.caption_proof) exclusively.
    ``available`` is True only when ffmpeg resolves AND advertises the
    ``readeia608`` capability the route depends on.
    """

    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        return {
            "available": False,
            "decoder": "ffmpeg-subcc",
            "detail": "ffmpeg not found; cannot run the proven subcc caption decoder",
            "readeia608": False,
        }
    filters = _run([str(ffmpeg), "-hide_banner", "-filters"])
    listing = (filters.get("stdout") or "") + (filters.get("stderr") or "")
    has_readeia608 = "readeia608" in listing
    return {
        "available": bool(filters.get("ok")) and has_readeia608,
        "decoder": "ffmpeg-subcc",
        "ffmpeg_path": str(ffmpeg),
        "readeia608": has_readeia608,
        "detail": (
            "ffmpeg subcc decode-back available (readeia608 present)"
            if has_readeia608
            else "ffmpeg present but readeia608 capability not advertised"
        ),
    }


def _decode_captions(segment: Path) -> dict[str, Any]:
    """Decode-back captions from one emitted TS via ffmpeg's proven ``subcc`` source.

    Uses the SAME route the product proves with in
    ``civiccast.egress.caption_proof.decode_embedded_captions``:
    ``ffmpeg -f lavfi -i movie=<path>[out0+subcc] -map 0:1 -f srt -``. That route
    is empirically sensitive (1 cue on the known-positive CEA-708 fixture, 0 on
    the negative), unlike the removed GStreamer chain.

    Privacy: the decoded cue text is NEVER returned. Only a boolean, a byte
    count, and a SHA-256 leave this function, so a PASS can never persist or
    broadcast speech content into evidence. Raw ffmpeg stderr is also withheld
    (hashed only) because it can echo cue bytes.
    """

    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        return {"status": Verdict.NOT_PROVEN, "detail": "ffmpeg unavailable for subcc decode"}

    # Build the movie filter path with the SAME escaping the product's proven
    # helper uses. We do NOT import that helper: its module chain pulls psutil
    # and can raise ImportError in a restricted/provisioning environment, and the
    # OLD local fallback was WRONG -- single-level ":" escaping reaches the movie
    # option parser as a bare ":" so ffmpeg splits a Windows "C:" drive and tries
    # to open "C" (exit -2/ENOENT). The lavfi movie path crosses TWO
    # escape-consuming parsers, so a literal ":" needs "\\:" in the graph string.
    # Verified natively 2026-09-24 on the known-positive CEA fixture: the
    # double-backslash form exits 0 and decodes a cue; the single form exits -2.
    movie = segment.as_posix().replace("\\", "\\\\\\\\").replace(":", "\\\\:")

    try:
        completed = subprocess.run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-nostats",
                "-f",
                "lavfi",
                "-i",
                f"movie={movie}[out0+subcc]",
                "-map",
                "0:1",
                "-f",
                "srt",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=ANALYZER_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": Verdict.UNVERIFIED, "detail": f"subcc decode process error: {type(exc).__name__}"}

    srt_text = completed.stdout or ""
    # Count SRT cues without retaining their text. A cue block is a payload line
    # following a "start --> end" timing line.
    lines = [ln.strip() for ln in srt_text.splitlines()]
    cue_count = 0
    for index, line in enumerate(lines):
        if "-->" in line and index + 1 < len(lines):
            payload = lines[index + 1]
            if payload and not payload.isdigit() and "-->" not in payload:
                cue_count += 1
    decoded_text_present = cue_count > 0
    decoded_text_bytes = len(srt_text.encode("utf-8"))
    decoded_text_sha256 = _sha256_text(srt_text)

    result: dict[str, Any] = {
        "decoder": "ffmpeg-subcc",
        "decoded_text_present": decoded_text_present,
        "decoded_text_bytes": decoded_text_bytes,
        "decoded_text_sha256": decoded_text_sha256,
        "decoded_cue_count": cue_count,
    }
    if completed.returncode != 0:
        result["status"] = Verdict.UNVERIFIED
        result["detail"] = (
            f"subcc decode exited {completed.returncode} "
            f"(stderr_sha256={_sha256_text(completed.stderr or '')}); raw output withheld"
        )
        return result
    if not decoded_text_present:
        result["status"] = Verdict.FAIL
        result["detail"] = "subcc decode returned no embedded caption cues for this segment"
        return result
    result["status"] = Verdict.PASS
    result["detail"] = (
        f"subcc decoded {cue_count} caption cue(s) "
        f"({decoded_text_bytes} bytes, sha256={decoded_text_sha256[:16]}...)"
    )
    return result


# --- Caption decode-back window --------------------------------------------


def _read_log_tail(path: Path, limit: int) -> tuple[str, int]:
    """The last ``limit`` bytes of a live log, and that file's mtime (ns).

    The worker log is appended to for the life of the station, so only the tail
    is ever read.  One short-lived handle, with the same atomic-replace retry as
    every other live read.
    """

    last: OSError | None = None
    for attempt in range(RACE_RETRY_ATTEMPTS):
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                data = handle.read()
            mtime_ns = path.stat().st_mtime_ns
            return data.decode("utf-8", errors="replace"), mtime_ns
        except _RACE_ERRORS as exc:
            last = exc
            if attempt + 1 < RACE_RETRY_ATTEMPTS:
                time.sleep(RACE_RETRY_DELAY_SECONDS)
    if last is None:  # pragma: no cover - the budget is at least one attempt
        raise RuntimeError(f"unreadable live log: {path}")
    raise last


def caption_keep_heartbeat_age(root: Path, *, now: float | None = None) -> float | None:
    """How long ago the keeper last wrote its heartbeat, or None if it never did.

    The heartbeat is rewritten every loop (4 s), so its MTIME is the whole
    liveness argument: a fresh one means segments were being copied into this
    folder seconds ago and the copies are the recent past.  `updated_epoch` inside
    the file says the same thing, but a file whose mtime is old is a stopped
    keeper's leftovers whatever its contents claim.
    """

    moment = time.time() if now is None else now
    try:
        stat = (root / CAPTION_KEEP_HEARTBEAT_NAME).stat()
    except OSError:
        return None
    return round(moment - stat.st_mtime, 3)


@dataclass(frozen=True)
class CaptionKeepSource:
    """Where the keeper's copies live, and whether they may be used at all.

    A folder of `seg*.ts` copies is not evidence by itself: a stopped keeper
    leaves exactly the fossil group the window must never reach.  The heartbeat
    age is what makes them usable, so when it is stale (or absent) this type is
    inert -- `channel_dir` returns None for every channel, refusing the copies
    outright rather than merely ignoring them, so no caller can read them anyway.
    """

    root: Path
    usable: bool
    heartbeat_age_seconds: float | None
    note: str

    def channel_dir(self, channel_id: str) -> Path | None:
        return self.root / channel_id if self.usable else None


#: The default when no keeper is in play.  Frozen and inert, and the default for
#: `verify_channel` / `verify_all`, so a unit test can never silently pick up
#: whatever a live keeper happens to have left in %TEMP%.
NO_CAPTION_KEEP: Final[CaptionKeepSource] = CaptionKeepSource(
    root=Path(), usable=False, heartbeat_age_seconds=None, note="no caption keep dir was requested"
)


def default_caption_keep_dir() -> Path:
    """`%TEMP%\\cc-caption-keep`: where `bin\\segment_keeper.py` writes by default.

    A rung that is ALREADY RUNNING loaded its own copy of `rung.ps1` at start and
    therefore passes no `--caption-keep-dir`; looking here by default is what lets
    a keeper started beside it take effect without restarting the rung.
    """

    return Path(tempfile.gettempdir()) / CAPTION_KEEP_DIR_NAME


def resolve_caption_keep(
    root: Path, *, requested: bool = False, now: float | None = None
) -> CaptionKeepSource:
    """Decide whether the keep dir may be used, and say why in the evidence.

    `requested` only colours the wording (an explicit `--caption-keep-dir` versus
    the CLI's default lookup); the rule is the same either way -- the copies are
    usable exactly while the keeper's heartbeat is `CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS`
    old or newer.  Every outcome states which it is, so the verify file never has
    to be read against the live station to learn whether the 60 s window was real.
    """

    origin = "the requested caption keep dir" if requested else "the default caption keep dir"
    age = caption_keep_heartbeat_age(root, now=now)
    if age is None:
        return CaptionKeepSource(
            root=root,
            usable=False,
            heartbeat_age_seconds=None,
            note=(
                f"{origin} {root} holds no {CAPTION_KEEP_HEARTBEAT_NAME}: no caption keeper is "
                "running there, so the caption window is the live dir alone"
            ),
        )
    if age > CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS:
        return CaptionKeepSource(
            root=root,
            usable=False,
            heartbeat_age_seconds=age,
            note=(
                f"{origin} {root} last heartbeat was {age:g}s ago, older than "
                f"{CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS:g}s: the keeper is not running, so its "
                "copies are a stopped run's leftovers and the caption window is the live dir alone"
            ),
        )
    return CaptionKeepSource(
        root=root,
        usable=True,
        heartbeat_age_seconds=age,
        note=(
            f"{origin} {root} heartbeat was {age:g}s ago: the keeper's copies of rotated-away "
            "segments are part of the caption window"
        ),
    )


def caption_window(
    channel_dir: Path,
    *,
    segment_seconds: float = HLS_TARGET_SEGMENT_SECONDS,
    keep_dir: Path | None = None,
    keep_heartbeat_age_seconds: float | None = None,
) -> dict[str, Any]:
    """The newest ~60 s of FINISHED segments, oldest first.

    Selection is by EMISSION TIME (mtime), never by name or sequence number: a
    live channel dir also holds segments left by PREVIOUS runs whose sequence
    numbers are far higher than the current run's newest -- observed live
    2026-09-26, public `seg000018677.ts` (Sep 19) beside the running
    `seg000001284.ts` -- and a name-ordered window would decode those fossils
    instead of the stream.  The newest `CAPTION_WINDOW_EXCLUDE_NEWEST` segments
    are never touched -- the relay may still be writing them -- and the walk stops
    at `CAPTION_WINDOW_STALENESS_SECONDS` behind the newest candidate so it can
    never walk back into a previous run.

    `keep_dir` (U50) adds the keeper's plain copies of segments the relay has
    already DELETED, without which this window is 10 s on the live station and not
    60 s: the relay keeps only ~7 segments and rotates the rest away before the
    verifier can look.  The copies are UNIONED with the live dir, deduped by name
    with the LIVE file winning (a kept copy is only ever a stand-in for a segment
    that is gone, never a substitute for one still on air), and they are subject to
    the same staleness rule as anything else.  A window is also only honest while
    it is CONTIGUOUS: `count x segment_seconds` would otherwise claim a span the
    media does not cover, so the walk stops at the first step wider than
    `CAPTION_KEEP_GAP_TOLERANCE` segment durations and reports where.

    The result says where the window came from (`source`, `from_keep`, `from_live`,
    the heartbeat age), and each segment carries the `path` it was actually read
    from, so a consumer decodes the copy rather than the live name.
    """

    stale_ns = int(CAPTION_WINDOW_STALENESS_SECONDS * 1_000_000_000)

    def _empty() -> dict[str, Any]:
        return {
            "segments": [],
            "span_seconds": 0.0,
            "newest_excluded": [],
            "older_excluded": 0,
            "source": "live",
            "from_keep": 0,
            "from_live": 0,
            "keep_heartbeat_age_seconds": keep_heartbeat_age_seconds,
            "gap_stopped_at": None,
            "gap_seconds": None,
        }

    # (mtime_ns, sequence, name, path, from_keep); the live dir is collected FIRST
    # so a name present in both resolves to the live file.
    candidates: list[tuple[int, int, str, Path, bool]] = []
    live_names: set[str] = set()
    try:
        entries = list(channel_dir.glob("seg*.ts"))
    except OSError:  # pragma: no cover - an unreadable dir is reported upstream
        return _empty()
    for path, from_keep in [(entry, False) for entry in entries] + [
        (entry, True) for entry in (list(keep_dir.glob("seg*.ts")) if keep_dir is not None else [])
    ]:
        sequence = _sequence_number(path.name)
        if sequence is None:
            continue
        if from_keep and path.name in live_names:
            continue  # the live file is the one on air; the copy is a stand-in
        try:
            stat = path.stat()
        except OSError:
            # A segment rotated away mid-enumeration is simply not part of the
            # window; it is not evidence of anything.
            continue
        if not from_keep:
            live_names.add(path.name)
        candidates.append((stat.st_mtime_ns, sequence, path.name, path, from_keep))
    if not candidates:
        return _empty()
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    if CAPTION_WINDOW_EXCLUDE_NEWEST > 0:
        finished = candidates[:-CAPTION_WINDOW_EXCLUDE_NEWEST]
        newest_excluded = [item[2] for item in candidates[-CAPTION_WINDOW_EXCLUDE_NEWEST :]]
    else:  # pragma: no cover - the shipped floor is 2, and 0 is not a window
        finished, newest_excluded = candidates, []
    newest_ns = candidates[-1][0]
    gap_ns = int(segment_seconds * CAPTION_KEEP_GAP_TOLERANCE * 1_000_000_000)

    chosen: list[tuple[int, int, str, Path, bool]] = []
    span = 0.0
    gap_stopped_at: str | None = None
    gap_seconds: float | None = None
    for item in reversed(finished):
        if newest_ns - item[0] > stale_ns:
            break  # this and everything older belongs to a previous run
        if chosen and chosen[-1][0] - item[0] > gap_ns:
            # The keeper missed this segment (or the relay outran it): counting
            # across the hole would claim a span the media does not cover.
            gap_stopped_at, gap_seconds = item[2], round((chosen[-1][0] - item[0]) / 1e9, 3)
            break
        if chosen and span + segment_seconds > CAPTION_WINDOW_SECONDS:
            break
        chosen.append(item)
        span += segment_seconds
        if len(chosen) >= CAPTION_WINDOW_MAX_SEGMENTS:
            break
    chosen.reverse()

    from_keep = sum(1 for item in chosen if item[4])
    return {
        "segments": [
            {
                "segment": name,
                "path": str(path),
                "mtime_ns": mtime_ns,
                "emitted_utc": datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC).isoformat(),
            }
            for mtime_ns, _sequence, name, path, _kept in chosen
        ],
        "span_seconds": round(span, 3),
        "newest_excluded": newest_excluded,
        "older_excluded": len(finished) - len(chosen),
        "source": "keep" if from_keep else "live",
        "from_keep": from_keep,
        "from_live": len(chosen) - from_keep,
        "keep_heartbeat_age_seconds": keep_heartbeat_age_seconds,
        "gap_stopped_at": gap_stopped_at,
        "gap_seconds": gap_seconds,
    }


def caption_receipt(channel_id: str, hls_root: Path, *, now: float | None = None) -> dict[str, Any]:
    """What the playout worker itself reported receiving, for this channel.

    Read from ``<egress>/<channel>/logs/gst-worker.stdout.log`` -- the worker's
    own stdout, which is where ``_CaptionReceiptCounter`` prints.  The verdict
    is about the LAST line that names this channel: a receipt with
    ``received>0`` means captions reached the worker; ``received=0`` means the
    window closed with nothing; and the worker's own WARNING (ten silent
    windows, ~600 s) is as strong as a zero receipt.  A log that has not been
    written for longer than ``CAPTION_RECEIPT_FRESH_SECONDS`` cannot speak for
    the window being judged, so it is UNAVAILABLE rather than ZERO -- a quiet
    channel is not an outage.  No caption TEXT is ever read or returned.
    """

    path = Path(hls_root).parent / channel_id / "logs" / "gst-worker.stdout.log"
    moment = time.time() if now is None else now
    receipt: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "channel": channel_id,
        "log": str(path),
        "age_seconds": None,
        "received": None,
        "window_s": None,
        "silent_seconds": None,
        "line": None,
        "detail": f"no worker caption log at {path}",
    }
    try:
        text, mtime_ns = _read_log_tail(path, CAPTION_RECEIPT_TAIL_BYTES)
    except OSError as exc:
        receipt["detail"] = f"the worker caption log could not be read ({exc.__class__.__name__})"
        return receipt
    receipt["age_seconds"] = round(moment - mtime_ns / 1e9, 3)

    last_receipt: re.Match[str] | None = None
    last_silence: re.Match[str] | None = None
    receipt_line_no = 0
    silence_line_no = 0
    for index, line in enumerate(text.splitlines(), start=1):
        got = CAPTION_RECEIPT_RE.search(line)
        if got is not None and got.group("channel") == channel_id:
            last_receipt, receipt_line_no = got, index
            continue
        silent = CAPTION_SILENT_RE.search(line)
        if silent is not None and silent.group("channel") == channel_id:
            last_silence, silence_line_no = silent, index
    if last_silence is not None and silence_line_no > receipt_line_no:
        # The warning is the last word this channel got: the worker has been
        # receiving nothing for ~600 s and says so itself.
        receipt["status"] = "ZERO"
        receipt["silent_seconds"] = float(last_silence.group("seconds"))
        receipt["detail"] = (
            f"the worker reported no caption command received for "
            f"{receipt['silent_seconds']:g}s; the last thing it sent for {channel_id}"
        )
        return receipt
    if last_receipt is None:
        receipt["detail"] = (
            f"no caption receipt for {channel_id} in the last "
            f"{CAPTION_RECEIPT_TAIL_BYTES // 1024} KiB of the worker log"
        )
        return receipt

    received = int(last_receipt.group("received"))
    receipt["line"] = last_receipt.group(0)
    receipt["received"] = received
    receipt["window_s"] = float(last_receipt.group("window"))
    fresh = bool(receipt["age_seconds"] is not None and receipt["age_seconds"] <= CAPTION_RECEIPT_FRESH_SECONDS)
    if received == 0:
        receipt["status"] = "ZERO" if fresh else "UNAVAILABLE"
        receipt["detail"] = (
            f"the worker's last receipt for {channel_id} reported received=0 in "
            f"{receipt['window_s']:g}s, {receipt['age_seconds']:g}s ago"
            + ("" if fresh else " -- too old to speak for the window under judgement")
        )
        return receipt
    receipt["status"] = "OK" if fresh else "UNAVAILABLE"
    receipt["detail"] = (
        f"the worker reported received={received} in {receipt['window_s']:g}s, "
        f"{receipt['age_seconds']:g}s ago"
        + ("" if fresh else " -- too old to speak for the window under judgement")
    )
    return receipt


# --- Playlist parsing ------------------------------------------------------


@dataclass
class Playlist:
    path: Path
    media_sequence: int | None
    target_duration: float | None
    segments: list[str] = field(default_factory=list)
    segment_infos: list[float] = field(default_factory=list)
    program_date_times: list[str] = field(default_factory=list)
    parse_error: str | None = None


def parse_playlist(path: Path) -> Playlist:
    """Parse a media playlist; a read that races the relay's replace is retried.

    The retry is built on the read itself rather than on a pre-check:
    ``Path.is_file()`` swallows ``OSError``, so an ``is_file()`` guard would
    report a raced playlist as "playlist missing" -- a station fault that never
    happened.  A playlist that is still unreadable once the budget is spent
    reports exactly what it reported before the retry existed.
    """

    try:
        text = _read_live_text(path)
    except FileNotFoundError:
        return Playlist(path=path, media_sequence=None, target_duration=None, parse_error="playlist missing")
    except OSError as exc:
        return Playlist(path=path, media_sequence=None, target_duration=None, parse_error=repr(exc))
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        return Playlist(path=path, media_sequence=None, target_duration=None, parse_error="missing #EXTM3U")
    media_sequence: int | None = None
    target_duration: float | None = None
    segments: list[str] = []
    infos: list[float] = []
    pdts: list[str] = []
    pending_info: float | None = None
    for raw in lines:
        line = raw.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            digits = line.split(":", 1)[1].strip()
            media_sequence = int(digits) if digits.lstrip("-").isdigit() else None
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = float(line.split(":", 1)[1].strip())
            except ValueError:
                target_duration = None
        elif line.startswith("#EXTINF:"):
            try:
                pending_info = float(line.split(":", 1)[1].split(",")[0].strip())
            except ValueError:
                pending_info = None
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdts.append(line.split(":", 1)[1].strip())
        elif line and not line.startswith("#"):
            segments.append(line)
            infos.append(pending_info if pending_info is not None else float("nan"))
            pending_info = None
    if not segments:
        return Playlist(
            path=path,
            media_sequence=media_sequence,
            target_duration=target_duration,
            parse_error="playlist lists no segments",
        )
    return Playlist(
        path=path,
        media_sequence=media_sequence,
        target_duration=target_duration,
        segments=segments,
        segment_infos=infos,
        program_date_times=pdts,
    )


def _sequence_number(segment_name: str) -> int | None:
    match = re.search(r"(\d+)\.ts$", segment_name)
    return int(match.group(1)) if match else None


# --- Per-segment media analysis -------------------------------------------


def probe_segment(ffprobe: Path, segment: Path) -> dict[str, Any]:
    result = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_programs",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(segment),
        ]
    )
    if not result["ok"]:
        return {"status": Verdict.FAIL, "detail": f"ffprobe failed: {result['error'] or result['stderr'][-300:]}"}
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        return {"status": Verdict.FAIL, "detail": f"ffprobe emitted invalid JSON: {exc!r}"}

    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    evidence: dict[str, Any] = {
        "container": (payload.get("format") or {}).get("format_name"),
        "duration": _as_float((payload.get("format") or {}).get("duration")),
        "video_codec": (video or {}).get("codec_name"),
        "video_profile": (video or {}).get("profile"),
        "video_width": (video or {}).get("width"),
        "video_height": (video or {}).get("height"),
        "video_start_pts": _as_int((video or {}).get("start_pts")),
        "video_start_time": _as_float((video or {}).get("start_time")),
        "audio_codec": (audio or {}).get("codec_name"),
        "audio_channels": (audio or {}).get("channels"),
        "audio_sample_rate": _as_int((audio or {}).get("sample_rate")),
        "audio_start_pts": _as_int((audio or {}).get("start_pts")),
        "audio_start_time": _as_float((audio or {}).get("start_time")),
    }
    problems: list[str] = []
    if (video or {}).get("codec_name") != "h264":
        problems.append(f"video codec is not H.264 ({(video or {}).get('codec_name')!r})")
    if (audio or {}).get("codec_name") != "aac":
        problems.append(f"audio codec is not AAC ({(audio or {}).get('codec_name')!r})")
    evidence["status"] = Verdict.FAIL if problems else Verdict.PASS
    evidence["detail"] = "; ".join(problems) if problems else "H.264 video + AAC audio present"
    return evidence


def decode_segment(ffmpeg: Path, segment: Path) -> dict[str, Any]:
    """Full decode of video+audio to null; proves decodability, not just headers."""

    result = _run(
        [str(ffmpeg), "-v", "error", "-xerror", "-i", str(segment), "-f", "null", "-"],
        timeout=ANALYZER_TIMEOUT_SECONDS,
    )
    stderr = (result["stderr"] or "").strip()
    ok = result["ok"] and not stderr
    return {
        "status": Verdict.PASS if ok else Verdict.FAIL,
        "returncode": result["returncode"],
        "stderr_tail": stderr[-400:] or None,
        "detail": "full H.264/AAC decode to null succeeded" if ok else "decode reported errors",
    }


def measure_audio(ffmpeg: Path, segment: Path) -> dict[str, Any]:
    """Integrated loudness + true peak + silence floor for one segment's audio."""

    result = _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-i",
            str(segment),
            "-vn",
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]
    )
    if result["returncode"] != 0:
        return {"status": Verdict.FAIL, "detail": f"ebur128 analysis failed: {result['stderr'][-300:]}"}
    integrated = _parse_last_float(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS\b", result["stderr"])
    lra = _parse_last_float(r"\bLRA:\s*(-?\d+(?:\.\d+)?)\s+LU\b", result["stderr"])
    true_peak = _parse_last_float(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s+dBFS\b", result["stderr"])
    # Single-segment measurement: no EXTINF window length is known here, so this
    # is a local audio sanity probe, not a release-grade integrated measurement.
    silent = integrated is None or integrated <= SILENCE_FLOOR_LUFS
    within_target = (
        integrated is not None
        and abs(integrated - OTT_LOUDNESS_TARGET_LUFS) <= OTT_LOUDNESS_TOLERANCE_LUFS
    )
    status = Verdict.FAIL if (silent or not within_target) else Verdict.PASS
    detail = (
        f"integrated {integrated} LUFS (target {OTT_LOUDNESS_TARGET_LUFS:g} +/- "
        f"{OTT_LOUDNESS_TOLERANCE_LUFS:g}), true peak {true_peak} dBFS"
        if integrated is not None
        else "no integrated LUFS reported (silent or no audio)"
    )
    return {
        "status": status,
        "integrated_lufs": integrated,
        "lra_lu": lra,
        "true_peak_dbfs": true_peak,
        "silence_floor_lufs": SILENCE_FLOOR_LUFS,
        "silent": silent,
        "within_target": within_target,
        "target_lufs": OTT_LOUDNESS_TARGET_LUFS,
        "tolerance_lufs": OTT_LOUDNESS_TOLERANCE_LUFS,
        "detail": detail,
    }

def measure_window_audio(
    ffmpeg: Path,
    segments: list[Path],
    concat_list: Path,
    *,
    segment_seconds: list[float] | None = None,
) -> dict[str, Any]:
    """Integrated loudness + true peak over the whole present HLS window.

    The project's loudness gate (civiccast.stream.loudness.check_loudness) is an
    integrated BS.1770 measurement; a single 2s segment is too short to measure
    the configured target meaningfully, so this measures the real emitted window
    (the newest N present segments) via ffmpeg concat. The window duration is
    reported so a caller can judge its adequacy.
    """

    if not segments:
        return {"status": Verdict.FAIL, "detail": "no present segments to measure"}
    lines = "".join(f"file '{seg.as_posix()}'\n" for seg in segments)
    try:
        concat_list.write_text(lines, encoding="utf-8")
    except OSError as exc:
        return {"status": Verdict.UNVERIFIED, "detail": f"cannot write concat list: {exc!r}"}
    result = _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-vn",
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]
    )
    if result["returncode"] != 0:
        return {"status": Verdict.FAIL, "detail": f"ebur128 window analysis failed: {result['stderr'][-300:]}"}
    integrated = _parse_last_float(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS\b", result["stderr"])
    lra = _parse_last_float(r"\bLRA:\s*(-?\d+(?:\.\d+)?)\s+LU\b", result["stderr"])
    true_peak = _parse_last_float(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s+dBFS\b", result["stderr"])
    # Duration gate: the caller may pass segment durations (EXTINF) so we know how
    # much audio was actually measured. Absent durations we cannot certify length.
    measured_seconds: float | None = None
    if segment_seconds is not None and len(segment_seconds) == len(segments):
        measured_seconds = float(sum(segment_seconds))
    release_grade = (
        measured_seconds is not None and measured_seconds >= MIN_RELEASE_GRADE_AUDIO_SECONDS
    )
    silent = integrated is None or integrated <= SILENCE_FLOOR_LUFS
    within_target = (
        integrated is not None
        and abs(integrated - OTT_LOUDNESS_TARGET_LUFS) <= OTT_LOUDNESS_TOLERANCE_LUFS
    )
    # A measured value is only a release-grade PASS/FAIL when the window is long
    # enough to be an integrated measurement. Silence still FAILs at any length.
    if silent:
        status = Verdict.FAIL
    elif not release_grade:
        status = Verdict.UNVERIFIED
    elif within_target:
        status = Verdict.PASS
    else:
        status = Verdict.FAIL
    detail = (
        f"window integrated {integrated} LUFS (target {OTT_LOUDNESS_TARGET_LUFS:g} +/- "
        f"{OTT_LOUDNESS_TOLERANCE_LUFS:g}), true peak {true_peak} dBFS, {len(segments)} segments"
        if integrated is not None
        else "no integrated LUFS reported for the window (silent or no audio)"
    )
    if integrated is not None and not release_grade:
        detail += (
            f"; {measured_seconds if measured_seconds is not None else 'unknown'}s measured < "
            f"{MIN_RELEASE_GRADE_AUDIO_SECONDS:g}s minimum -> NOT release-grade (integrated "
            "loudness requires a longer continuous capture)"
        )
    return {
        "status": status,
        "integrated_lufs": integrated,
        "lra_lu": lra,
        "true_peak_dbfs": true_peak,
        "silence_floor_lufs": SILENCE_FLOOR_LUFS,
        "silent": silent,
        "within_target": within_target,
        "target_lufs": OTT_LOUDNESS_TARGET_LUFS,
        "tolerance_lufs": OTT_LOUDNESS_TOLERANCE_LUFS,
        "segments_measured": [seg.name for seg in segments],
        "measured_seconds": measured_seconds,
        "release_grade_min_seconds": MIN_RELEASE_GRADE_AUDIO_SECONDS,
        "release_grade_adequate": release_grade,
        "detail": detail,
    }

def tsduck_analyze(tsp: Path, segment: Path) -> dict[str, Any]:
    """MPEG-TS sync/continuity/PAT-PMT/PCR evidence for one segment via TSDuck."""

    result = _run([str(tsp), "-I", "file", str(segment), "-P", "analyze", "--json", "-O", "drop"])
    raw = result["stdout"] or ""
    if not result["ok"]:
        return {"status": Verdict.UNVERIFIED, "detail": f"tsp analyze exited {result['returncode']}: {result['stderr'][-300:]}"}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        return {"status": Verdict.UNVERIFIED, "detail": "tsp analyze emitted no JSON"}
    try:
        report = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        return {"status": Verdict.UNVERIFIED, "detail": f"tsp analyze JSON error: {exc!r}"}

    ts = report.get("ts") or {}
    packets = ts.get("packets") or {}
    pid_rows = report.get("pids") or []
    discontinuities = sum(int((row.get("packets") or {}).get("discontinuities", 0)) for row in pid_rows)
    invalid_syncs = int(packets.get("invalid-syncs", 0))
    transport_errors = int(packets.get("transport-errors", 0))
    pat_seen = any(int(row.get("id", -1)) == 0 for row in pid_rows)
    pmt_seen = any(str(row.get("description", "")).upper().startswith("PMT") for row in pid_rows)
    pcr_pids = int((ts.get("pids") or {}).get("pcr", 0))

    problems: list[str] = []
    if invalid_syncs != 0 or transport_errors != 0:
        problems.append(f"invalid-syncs={invalid_syncs}, transport-errors={transport_errors}")
    if discontinuities > CONTINUITY_TOLERANCE:
        problems.append(f"{discontinuities} continuity discontinuities (tolerance {CONTINUITY_TOLERANCE})")
    if not pat_seen or not pmt_seen:
        problems.append(f"PAT {'seen' if pat_seen else 'missing'}, PMT {'seen' if pmt_seen else 'missing'}")
    if pcr_pids <= 0:
        problems.append("no PID carries PCR")
    return {
        "status": Verdict.FAIL if problems else Verdict.PASS,
        "invalid_syncs": invalid_syncs,
        "transport_errors": transport_errors,
        "discontinuities": discontinuities,
        "continuity_tolerance": CONTINUITY_TOLERANCE,
        "pat_seen": pat_seen,
        "pmt_seen": pmt_seen,
        "pcr_pids": pcr_pids,
        "detail": "; ".join(problems) if problems else "sync OK, zero discontinuities, PAT/PMT/PCR present",
    }


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text)
    return float(matches[-1]) if matches else None


# --- Continuity across segments -------------------------------------------


def evaluate_timestamp_continuity(per_segment: list[dict[str, Any]]) -> dict[str, Any]:
    """Require strictly-forward, gap-free video PTS and PCR across the window.

    Uses each segment's first-video-PTS and first-PCR (both 90 kHz). Segment
    duration comes from ffprobe. Adjacent segments must advance by
    approximately one segment duration; a backwards jump, a gap, or an overlap
    beyond a single frame fails. Missing timestamps are UNVERIFIED, never PASS.
    """

    pts_values = [entry.get("video_start_pts") for entry in per_segment]
    pcr_values = [entry.get("pcr_first") for entry in per_segment]
    durations = [entry.get("duration") for entry in per_segment]
    if not per_segment:
        return {"status": Verdict.UNVERIFIED, "detail": "no segments analyzed"}
    if any(v is None for v in pts_values):
        return {"status": Verdict.UNVERIFIED, "detail": "one or more segments report no video PTS"}
    if any(v is None for v in pcr_values):
        return {"status": Verdict.UNVERIFIED, "detail": "one or more segments report no PCR"}

    frame_tolerance_ticks = 3000  # one 30 fps frame at 90 kHz
    problems: list[str] = []
    deltas: list[int] = []
    for index in range(1, len(pts_values)):
        delta = int(pts_values[index]) - int(pts_values[index - 1])
        deltas.append(delta)
        if delta <= 0:
            problems.append(f"segment {index} video PTS did not advance (delta {delta} ticks)")
            continue
        # The gap between segment N-1's start and segment N's start is N-1's
        # played duration, not N's -- for variable-length windows and rollover
        # the two differ, so compare against the PREVIOUS segment's duration.
        previous_duration = durations[index - 1]
        if previous_duration is not None:
            expected = round(float(previous_duration) * TS_CLOCK_HZ)
            if abs(delta - expected) > frame_tolerance_ticks:
                problems.append(
                    f"segment {index} PTS delta {delta} ticks != expected {expected} "
                    "(previous segment ffprobe duration)"
                )
    for index in range(1, len(pcr_values)):
        delta = int(pcr_values[index]) - int(pcr_values[index - 1])
        if delta <= 0:
            problems.append(f"segment {index} PCR did not advance (delta {delta} ticks)")
            break
    return {
        "status": Verdict.FAIL if problems else Verdict.PASS,
        "pts_deltas_ticks": deltas,
        "pts_first": pts_values[0],
        "pts_last": pts_values[-1],
        "pcr_first": pcr_values[0],
        "pcr_last": pcr_values[-1],
        "detail": "; ".join(problems)
        if problems
        else "video PTS and PCR advance monotonically at the expected segment cadence",
    }




def extract_first_pcr(tsp: Path, segment: Path) -> int | None:
    """First PCR (90 kHz) in a segment via TSDuck pcrextract CSV output.

    TSDuck's pcrextract has no --json option; its default is CSV whose columns
    are: PID,Packet index in TS,Packet index in PID,Type,Count in PID,Value,
    Value offset in PID,Offset from PCR. We take the 'Value' (column 6) of the
    first row whose Type is PCR.
    """

    result = _run([str(tsp), "-I", "file", str(segment), "-P", "pcrextract", "-O", "drop"])
    if not result["ok"]:
        return None
    # TSDuck emits this CSV on stderr in the shipped 3.44 build (verified).
    output = result["stdout"] + "\n" + result["stderr"]
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("PID,"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6 and parts[3].upper() == "PCR":
            return _as_int(parts[5])
    return None

# --- Channel verification --------------------------------------------------


def evaluate_freshness(
    first: Playlist | None,
    current: Playlist,
    *,
    first_mtimes: dict[str, float] | None = None,
    current_mtimes: dict[str, float] | None = None,
    channel_dir: Path | None = None,
) -> dict[str, Any]:
    """Fail closed on stale HLS using two-sample index/mtime evidence.

    A frozen live HLS output can still serve a syntactically valid playlist and
    a still-``ON_AIR`` API while emitting nothing new (observed live: playlists
    and TS files stopped changing while ``/now`` said ON_AIR). This compares two
    bounded snapshots of the playlist media-sequence AND the newest listed
    segment's mtime, and reports stale/UNVERIFIED rather than trusting the
    playlist alone.
    """

    evidence: dict[str, Any] = {
        "first_media_sequence": first.media_sequence if first else None,
        "current_media_sequence": current.media_sequence,
        "sequence_advanced": None,
        "newest_segment": None,
        "newest_segment_mtime_utc": None,
        "mtime_advanced": None,
        "advanced": False,
        "status": Verdict.UNVERIFIED,
        "detail": "insufficient samples to judge freshness",
    }
    if channel_dir is not None and current.segments:
        newest = channel_dir / current.segments[-1]
        if newest.is_file():
            evidence["newest_segment"] = newest.name
            evidence["newest_segment_mtime_utc"] = datetime.fromtimestamp(
                newest.stat().st_mtime, UTC
            ).isoformat()
    if first is None:
        return evidence

    first_seq = first.media_sequence
    now_seq = current.media_sequence
    seq_advanced = (
        first_seq is not None and now_seq is not None and now_seq > first_seq
    )
    evidence["sequence_advanced"] = seq_advanced

    mtime_advanced = None
    if first_mtimes and current_mtimes:
        common = [s for s in current.segments if s in first_mtimes]
        if common:
            newest = common[-1]
            mtime_advanced = current_mtimes.get(newest, 0.0) > first_mtimes.get(newest, 0.0)
            evidence["mtime_advanced"] = mtime_advanced

    advanced = bool(seq_advanced) or bool(mtime_advanced)
    evidence["advanced"] = advanced
    if advanced:
        evidence["status"] = Verdict.PASS
        evidence["detail"] = "playlist media-sequence and/or segment mtime advanced between samples"
    else:
        evidence["status"] = Verdict.FAIL
        evidence["detail"] = (
            "stale HLS: media-sequence did not advance and no listed segment mtime "
            "changed between the two bounded samples (sidecar/API ON_AIR is not evidence)"
        )
    return evidence


def _segment_mtimes(channel_dir: Path, playlist: Playlist) -> dict[str, float]:
    mtimes: dict[str, float] = {}
    for name in playlist.segments:
        path = channel_dir / name
        if path.is_file():
            try:
                mtimes[name] = path.stat().st_mtime
            except OSError:
                continue
    return mtimes

def snapshot_channels(
    hls_root: Path,
    channel_ids: tuple[str, ...],
    *,
    max_segments: int,
) -> dict[str, dict[str, Any]]:
    """Capture EVERY channel's newest playlist-referenced TS bytes up front.

    Design (audit 2026-09-24): the live HLS window retains only ~6x2s (12s),
    while full analysis takes ~23s. If we snapshot inside per-channel analysis,
    later channels rotate out before we reach them. So we read each playlist and
    copy its newest N referenced, still-present segments into ONE shared scratch
    as fast as possible, BEFORE any ffprobe/ffmpeg/tsp work. Read-only on live.
    Fail-closed on a copy race (that record is marked unsnapshotted). Scrubs the
    whole shared scratch if any unexpected exception escapes.
    """
    max_segments = validate_max_segments(max_segments)
    channel_ids = validate_channel_ids(tuple(channel_ids))
    scratch = _make_scratch_dir()
    per_channel: dict[str, dict[str, Any]] = {}
    try:
        for channel_id in channel_ids:
            per_channel[channel_id] = _snapshot_one_channel(
                hls_root, channel_id, scratch, max_segments=max_segments
            )
    except BaseException:
        # Never leak a partially-populated scratch on an unexpected failure.
        _safe_rmtree(scratch)
        raise
    return {"scratch": scratch, "channels": per_channel}


def _snapshot_one_channel(
    hls_root: Path,
    channel_id: str,
    scratch: Path,
    *,
    max_segments: int,
) -> dict[str, Any]:
    """Capture the newest N referenced TS for ONE channel into ``scratch``."""
    max_segments = validate_max_segments(max_segments)
    validate_channel_ids((channel_id,))
    channel_dir = hls_root / channel_id
    playlist = parse_playlist(channel_dir / "playlist.m3u8")
    snap_dir = scratch / channel_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    # BOUNDED SCOPE: capture only the newest N segments we will actually
    # analyze, so a malformed/huge playlist cannot explode the scratch dir.
    chosen = list(playlist.segments)[-max_segments:]
    channel_root = channel_dir.resolve()
    for name in chosen:
        record: dict[str, Any] = {"segment": name}
        # PATH SAFETY (fail closed): the playlist entry must be a bare basename
        # with a .ts suffix, and its resolved path must stay within the channel
        # directory. Reject traversal / absolute / odd names.
        safe_name = name.strip()
        invalid = (
            not safe_name
            or safe_name != Path(safe_name).name
            or "/" in safe_name
            or "\\" in safe_name
            or not safe_name.lower().endswith(".ts")
        )
        if invalid:
            record["present"] = False
            record["snapshot_error"] = "unsafe_segment_name_rejected"
            records.append(record)
            continue
        src = channel_dir / safe_name
        try:
            resolved = src.resolve()
            contained = resolved == channel_root or channel_root in resolved.parents
        except OSError:
            contained = False
        if not contained:
            record["present"] = False
            record["snapshot_error"] = "segment_path_outside_channel_rejected"
            records.append(record)
            continue
        if not src.is_file():
            record["present"] = False
            records.append(record)
            continue
        record["present"] = True
        snap, sha = _snapshot_segment(src, snap_dir)
        if snap is not None and sha is not None:
            record["snapshot"] = str(snap)
            record["snapshot_sha256"] = sha
        else:
            record["snapshot_error"] = "copy_race_or_unreadable"
        records.append(record)
    return {"playlist": playlist, "records": records}

def verify_channel(
    channel_id: str,
    hls_root: Path,
    *,
    ffprobe: Path | None,
    ffmpeg: Path | None,
    tsp: Path | None,
    max_segments: int,
    first_playlist: Playlist | None = None,
    first_mtimes: dict[str, float] | None = None,
    presnapshot: dict[str, Any] | None = None,
    caption_keep: CaptionKeepSource = NO_CAPTION_KEEP,
) -> dict[str, Any]:
    max_segments = validate_max_segments(max_segments)
    validate_channel_ids((channel_id,))
    channel_dir = hls_root / channel_id
    # Prefer a cross-channel pre-captured snapshot set (all channels copied up
    # front, before any expensive analysis) so a later channel cannot rotate out
    # of the live window. Fall back to a local snapshot for direct callers/tests.
    playlist = (
        presnapshot["playlist"] if presnapshot is not None else parse_playlist(channel_dir / "playlist.m3u8")
    )
    evidence: dict[str, Any] = {
        "channel_id": channel_id,
        "channel_dir": str(channel_dir),
        "playlist": {
            "path": str(playlist.path),
            "media_sequence": playlist.media_sequence,
            "target_duration": playlist.target_duration,
            "segment_count": len(playlist.segments),
            "segments": playlist.segments,
            "program_date_times": playlist.program_date_times,
            "parse_error": playlist.parse_error,
        },
    }
    if playlist.parse_error:
        evidence["status"] = Verdict.FAIL
        evidence["verdict_detail"] = f"playlist unusable: {playlist.parse_error}"
        return evidence

    evidence["freshness"] = evaluate_freshness(
        first_playlist,
        playlist,
        first_mtimes=first_mtimes,
        current_mtimes=_segment_mtimes(channel_dir, playlist),
        channel_dir=channel_dir,
    )
    evidence["playlist_advance"] = {
        "first_media_sequence": evidence["freshness"]["first_media_sequence"],
        "current_media_sequence": evidence["freshness"]["current_media_sequence"],
        "advanced": evidence["freshness"]["advanced"],
    }
    # --- EARLY SNAPSHOT -------------------------------------------------------
    # The live HLS window deletes old segments as the muxer slides (6x2s). If we
    # only record NAMES here and read the live paths during analysis seconds
    # later, the files can be gone (ffmpeg movie= -> ENOENT / exit -2), which is
    # exactly the observed caption UNVERIFIED. So we capture every chosen
    # segment's BYTES into private scratch NOW (read-only on the live HLS) and
    # analyze the copies. Live paths are never modified or deleted.
    # DETERMINISTIC scratch ownership: verify_channel ALWAYS owns a scratch dir
    # that it creates here, and cleans up in `finally`. A caller-supplied
    # presnapshot is a READ-ONLY input whose paths we reuse (never delete). If
    # the presnapshot exists but carries no usable records, we still fall back to
    # a local capture into OUR scratch -- never an orphaned caller scratch.
    scratch = _make_scratch_dir()
    try:
        return _verify_channel_body(
            channel_id,
            hls_root,
            channel_dir=channel_dir,
            playlist=playlist,
            scratch=scratch,
            evidence=evidence,
            presnapshot=presnapshot,
            ffprobe=ffprobe,
            ffmpeg=ffmpeg,
            tsp=tsp,
            max_segments=max_segments,
            caption_keep=caption_keep,
        )
    finally:
        _safe_rmtree(scratch)


def _verify_channel_body(
    channel_id: str,
    hls_root: Path,
    *,
    channel_dir: Path,
    playlist: Playlist,
    scratch: Path,
    evidence: dict[str, Any],
    presnapshot: dict[str, Any] | None,
    ffprobe: Path | None,
    ffmpeg: Path | None,
    tsp: Path | None,
    max_segments: int,
    caption_keep: CaptionKeepSource = NO_CAPTION_KEEP,
) -> dict[str, Any]:
    snapshot_dir = scratch / "segments"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    pre_by_name = None
    if presnapshot is not None and presnapshot.get("records"):
        pre_by_name = {r["segment"]: r for r in presnapshot["records"]}

    # BOUNDED SCOPE (audit 2026-09-24): only the newest N playlist references
    # are inside our snapshot/analysis scope. Older references legitimately
    # rotate out of the live window while we analyze, so an absent OLD
    # reference is not a media failure. Fail-closed is preserved for a missing
    # segment WITHIN the chosen newest N (or when no snapshot set exists).
    chosen_names = set(list(playlist.segments)[-max_segments:])
    missing: list[str] = []
    segment_records: list[dict[str, Any]] = []
    for name in playlist.segments:
        path = channel_dir / name
        record: dict[str, Any] = {"segment": name}
        # A pre-captured, hash-validated snapshot is AUTHORITATIVE evidence even
        # if the live file has since rotated out of the window (the 6x2s window
        # slides during analysis). We therefore attach the snapshot FIRST and do
        # NOT gate it on the live path still existing.
        pre = pre_by_name.get(name) if pre_by_name is not None else None
        if pre is not None:
            record["present"] = bool(pre.get("present"))
            if pre.get("snapshot"):
                record["snapshot"] = pre["snapshot"]
                record["snapshot_sha256"] = pre.get("snapshot_sha256")
            elif pre.get("snapshot_error"):
                record["snapshot_error"] = pre["snapshot_error"]
        # CAPTURED IDENTITY IS AUTHORITATIVE: never re-stat/re-hash the live path
        # here (it may have rotated, and a torn live read must not overwrite the
        # validated snapshot identity). We only RECORD late live presence, and
        # only when we have no snapshot is absence a failure.
        live_present_late = path.is_file()
        record["live_present_after_snapshot"] = live_present_late
        record.setdefault("sequence", _sequence_number(name))
        if "snapshot" in record:
            record["present"] = True
        else:
            record["present"] = live_present_late
            if not live_present_late and name in chosen_names:
                missing.append(name)
        if pre is None and live_present_late:
            snap, snap_sha = _snapshot_segment(path, snapshot_dir)
            if snap is not None and snap_sha is not None:
                record["snapshot"] = str(snap)
                record["snapshot_sha256"] = snap_sha
            else:
                record["snapshot_error"] = "copy_race_or_unreadable"
        segment_records.append(record)
    if missing:
        evidence["missing_segments"] = missing
    evidence["segment_identity"] = segment_records

    # Keep the newest N segments, in chronological (older -> newer) order so
    # PTS/PCR continuity advances forward, matching real playback order.
    chosen_records = list(segment_records)[-max_segments:]

    def _analysis_path(record: dict[str, Any]) -> Path | None:
        """Prefer the private snapshot; NEVER the race-prone live path once a
        snapshot exists. A record with no snapshot is not analyzable."""
        snap = record.get("snapshot")
        return Path(snap) if snap else None

    analyzed: list[dict[str, Any]] = []
    for record in chosen_records:
        name = record["segment"]
        # Analyze the EARLY private snapshot, never the live path (race-prone).
        path = _analysis_path(record)
        entry: dict[str, Any] = {"segment": name, "present": record["present"], "snapshot": bool(path)}
        if path is None or not path.is_file():
            entry["probe"] = {
                "status": Verdict.FAIL,
                "detail": "segment could not be snapshotted before the live window slid (copy race)",
            }
            analyzed.append(entry)
            continue
        entry["probe"] = (
            probe_segment(ffprobe, path) if ffprobe else {"status": Verdict.UNVERIFIED, "detail": "ffprobe unavailable"}
        )
        entry["decode"] = (
            decode_segment(ffmpeg, path) if ffmpeg else {"status": Verdict.UNVERIFIED, "detail": "ffmpeg unavailable"}
        )
        entry["ts"] = (
            tsduck_analyze(tsp, path) if tsp else {"status": Verdict.UNVERIFIED, "detail": "tsp unavailable"}
        )
        entry["pcr_first"] = extract_first_pcr(tsp, path) if tsp else None
        entry["duration"] = (entry["probe"] or {}).get("duration")
        entry["video_start_pts"] = (entry["probe"] or {}).get("video_start_pts")
        analyzed.append(entry)
    evidence["segments_analyzed"] = analyzed

    present_paths = [p for p in (_analysis_path(r) for r in chosen_records) if p is not None and p.is_file()]
    # Scratch OWNERSHIP: when verify_all supplies a shared pre-snapshot scratch,
    # the caller owns (and cleans up) it; we must not delete it here, or a later
    # channel's already-captured copies would vanish. Only a locally-created
    # scratch is ours to remove.
    # Pair each present path with its EXTINF duration so the loudness measurement
    # knows the real window length (and can refuse to be release-grade on a
    # too-short ~8s window). Scratch cleanup is owned by the outer finally.
    if ffmpeg:
        name_to_seconds = dict(zip(playlist.segments, playlist.segment_infos, strict=False))
        durations = [float(name_to_seconds.get(p.name, 0.0) or 0.0) for p in present_paths]
        evidence["audio_window"] = measure_window_audio(
            ffmpeg, present_paths, scratch / "window.ffconcat", segment_seconds=durations
        )
    else:
        evidence["audio_window"] = {"status": Verdict.UNVERIFIED, "detail": "ffmpeg unavailable"}

    evidence["timestamp_continuity"] = evaluate_timestamp_continuity(analyzed)

    decoder = caption_decoder_available()
    evidence["caption_decoder"] = decoder
    # What the playout worker ITSELF reported receiving on this channel's caption
    # pipe.  Captions are sparse and a healthy channel pauses (a recess), so a
    # decode-back FAIL alone cannot tell a quiet channel from an outage; the
    # worker's own receipt is the second opinion rung_check needs (U48 follow-on).
    evidence["caption_receipt"] = caption_receipt(channel_id, hls_root)

    # The caption window is the newest ~60 s of FINISHED segments, chosen by
    # emission time (U48 follow-on: 4 segments / ~8 s failed on any speech pause).
    # U50: the relay keeps only ~7 live segments and DELETES each one as it rotates
    # it out, so the live dir alone yields 10 s, never 60.  The keeper's copies of
    # the rotated-away segments (used only while its heartbeat is fresh) are what
    # make the 60 s window real; the evidence says which of the two this is.
    durations = [d for d in playlist.segment_infos if d and d > 0]
    caption_seconds = sorted(durations)[len(durations) // 2] if durations else HLS_TARGET_SEGMENT_SECONDS
    keep_channel_dir = caption_keep.channel_dir(channel_id)
    window = caption_window(
        channel_dir,
        segment_seconds=caption_seconds,
        keep_dir=keep_channel_dir,
        keep_heartbeat_age_seconds=caption_keep.heartbeat_age_seconds,
    )
    window_names = [item["segment"] for item in window["segments"]]
    evidence["caption_window"] = {
        "span_seconds": window["span_seconds"],
        "segment_count": len(window_names),
        "emitted_first_utc": window["segments"][0]["emitted_utc"] if window["segments"] else None,
        "emitted_last_utc": window["segments"][-1]["emitted_utc"] if window["segments"] else None,
        "newest_excluded": window["newest_excluded"],
        "older_excluded": window["older_excluded"],
        # U50 provenance: a 60 s span means something different when 25 of its
        # segments are keeper copies rather than bytes still on air, and a 10 s
        # span means something different when no keeper was running at all.
        "source": window["source"],
        "from_keep": window["from_keep"],
        "from_live": window["from_live"],
        "keep_dir": str(caption_keep.root) if caption_keep is not NO_CAPTION_KEEP else None,
        "keep_dir_used": keep_channel_dir is not None,
        "keep_heartbeat_age_seconds": window["keep_heartbeat_age_seconds"],
        "keep_note": caption_keep.note,
        "gap_stopped_at": window["gap_stopped_at"],
        "gap_seconds": window["gap_seconds"],
    }
    per_segment_captions: list[dict[str, Any]] = []
    if not decoder["available"]:
        evidence["caption_decode_back"] = {
            "status": Verdict.NOT_PROVEN,
            "detail": "no proven local caption decoder path -- caption decode-back is NOT_PROVEN",
            "cue_count": None,
            "span_seconds": window["span_seconds"],
            "per_segment": [],
        }
    elif not window_names:
        evidence["caption_decode_back"] = {
            "status": Verdict.NOT_PROVEN,
            "detail": (
                "no finished segment in the caption window (every emitted segment is "
                f"newer than the newest {CAPTION_WINDOW_EXCLUDE_NEWEST} or older than "
                f"{CAPTION_WINDOW_STALENESS_SECONDS:g}s)"
            ),
            "cue_count": None,
            "span_seconds": window["span_seconds"],
            "per_segment": [],
        }
    else:
        # Copy each finished segment into private scratch FIRST (the live path is
        # read-once and may be rotated away), then decode the copy.  Every segment
        # in the span is decoded: one cue anywhere is a pass, and a segment that
        # could not be captured keeps the span UNVERIFIED rather than silently
        # dropping out of it.
        caption_dir = scratch / "caption"
        caption_dir.mkdir(parents=True, exist_ok=True)
        for item in window["segments"]:
            # The path the window actually chose: a live segment, or the keeper's
            # copy of one the relay has already deleted (U50).
            snapshot, _digest = _snapshot_segment(Path(item["path"]), caption_dir)
            if snapshot is None:
                per_segment_captions.append(
                    {
                        "segment": item["segment"],
                        "status": Verdict.UNVERIFIED,
                        "detail": "segment could not be copied out of the live window (copy race)",
                        "decoded_cue_count": None,
                    }
                )
                continue
            decoded = _decode_captions(snapshot)
            per_segment_captions.append({"segment": item["segment"], **decoded})
        cue_count = sum(int(item.get("decoded_cue_count") or 0) for item in per_segment_captions)
        unverified_count = sum(
            1 for item in per_segment_captions if item["status"] == Verdict.UNVERIFIED
        )
        # Window-level semantics (corrected 2026-09-24, span widened 2026-09-26):
        # embedded CEA-708/608 captions are SPARSE, and a station legitimately
        # stops speaking (a recess, a pause between agenda items).  A ~60 s span
        # may therefore hold cues in only a few segments -- or, rarely, none.  The
        # rules:
        #   * UNVERIFIED if ANY segment in the span could not be decoded cleanly
        #     (decode error / copy race): partial evidence proves nothing.
        #   * PASS when every segment decoded cleanly AND at least one cue is in
        #     the span.
        #   * FAIL only when the span decoded cleanly AND carried no cue at all.
        # This still refuses to call a captionless span a pass; the widening is in
        # the SPAN, not in the verdict.
        if unverified_count > 0:
            aggregate_status = Verdict.UNVERIFIED
        elif cue_count > 0:
            aggregate_status = Verdict.PASS
        else:
            aggregate_status = Verdict.FAIL
        evidence["caption_decode_back"] = {
            "status": aggregate_status,
            "detail": (
                f"caption decode-back over the newest {window['span_seconds']:.1f} s of "
                f"finished segments: {len(per_segment_captions)} segment(s) decoded, "
                f"{unverified_count} unverified, {cue_count} cue(s) total; "
                "PASS needs at least one cue in the span with NO unverified segment; "
                "a clean span with no cue is FAIL"
            ),
            "cue_count": cue_count,
            "span_seconds": window["span_seconds"],
            "per_segment": per_segment_captions,
        }

    statuses: list[str] = []
    if missing:
        statuses.append(Verdict.FAIL)
    for entry in analyzed:
        for key in ("probe", "decode", "ts"):
            statuses.append((entry.get(key) or {}).get("status", Verdict.UNVERIFIED))
    statuses.append(evidence["audio_window"]["status"])
    statuses.append(evidence["timestamp_continuity"]["status"])
    statuses.append(evidence["caption_decode_back"]["status"])
    statuses.append(evidence["freshness"]["status"])

    if Verdict.FAIL in statuses:
        evidence["status"] = Verdict.FAIL
    elif any(s in (Verdict.UNVERIFIED, Verdict.NOT_PROVEN) for s in statuses):
        evidence["status"] = Verdict.UNVERIFIED
    else:
        evidence["status"] = Verdict.PASS
    evidence["statuses"] = statuses
    return evidence


def verify_all(
    hls_root: Path,
    *,
    channel_ids: tuple[str, ...] = REQUIRED_CHANNELS,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    dwell_seconds: float = 5.0,
    caption_keep: CaptionKeepSource = NO_CAPTION_KEEP,
) -> dict[str, Any]:
    """Verify all channels; bounded dwell measures real playlist advancement."""

    # Fail closed BEFORE any allocation or read: bound the snapshot scope and
    # ensure channel ids cannot escape the HLS root.
    max_segments = validate_max_segments(max_segments)
    channel_ids = validate_channel_ids(tuple(channel_ids))

    versions = tool_versions()
    ffprobe_path = Path(versions["ffprobe"]["path"]) if versions["ffprobe"]["path"] else None
    ffmpeg_path = Path(versions["ffmpeg"]["path"]) if versions["ffmpeg"]["path"] else None
    tsp_path = Path(versions["tsp"]["path"]) if versions["tsp"]["path"] else None

    first_snapshots = {c: parse_playlist(hls_root / c / "playlist.m3u8") for c in channel_ids}
    first_mtime_snapshots = {
        c: _segment_mtimes(hls_root / c, first_snapshots[c]) for c in channel_ids
    }
    started = _utc_now()
    if dwell_seconds > 0:
        time.sleep(dwell_seconds)

    # Capture ALL channels' selected TS into ONE shared scratch BEFORE any
    # expensive analysis (the live window is ~12s; full analysis is ~23s). This
    # keeps a later channel from rotating out while an earlier one is analyzed.
    shot = snapshot_channels(hls_root, channel_ids, max_segments=max_segments)
    pre_channels = shot["channels"]

    channels: dict[str, Any] = {}
    try:
        for channel_id in channel_ids:
            channels[channel_id] = verify_channel(
                channel_id,
                hls_root,
                ffprobe=ffprobe_path,
                ffmpeg=ffmpeg_path,
                tsp=tsp_path,
                max_segments=max_segments,
                first_playlist=first_snapshots[channel_id],
                first_mtimes=first_mtime_snapshots[channel_id],
                presnapshot=pre_channels.get(channel_id),
                caption_keep=caption_keep,
            )
    finally:
        _safe_rmtree(shot["scratch"])

    # Release-grade mode requires EXACTLY the three station channels. A subset
    # run is permitted for development but can never return a release-grade
    # PASS: it is reported as non-release and its verdict is demoted to
    # UNVERIFIED at best.
    exact_required_set = tuple(channel_ids) == REQUIRED_CHANNELS
    missing_required = [c for c in REQUIRED_CHANNELS if c not in channel_ids]
    unexpected_channels = [c for c in channel_ids if c not in REQUIRED_CHANNELS]

    overall_fail = any(c["status"] == Verdict.FAIL for c in channels.values())
    overall_unverified = any(c["status"] == Verdict.UNVERIFIED for c in channels.values())
    overall = Verdict.FAIL if overall_fail else (Verdict.UNVERIFIED if overall_unverified else Verdict.PASS)
    if not exact_required_set and overall == Verdict.PASS:
        # A subset (or an off-station channel) cannot assert a three-channel
        # release-grade pass; demote rather than overclaim.
        overall = Verdict.UNVERIFIED
    return {
        "verifier": "verify_beta10_live_hls_media",
        "component_scope": "bounded read-only live-HLS media verifier (one component of the 30m/2h/4h/8h ladder)",
        "ladder_claim": "NOT_RUN -- this verifier does not assert the 30m->2h->4h->8h ladder passed",
        "release_grade": exact_required_set,
        "channels_requested": list(channel_ids),
        "missing_required_channels": missing_required,
        "unexpected_channels": unexpected_channels,
        "release_grade_note": (
            "exact three-channel set verified"
            if exact_required_set
            else (
                "NON-RELEASE subset/dev run: verdict cannot be PASS for release; "
                "release-grade requires exactly "
                + ", ".join(REQUIRED_CHANNELS)
            )
        ),
        "started_utc": started,
        "finished_utc": _utc_now(),
        "hls_root": str(hls_root),
        "required_channels": list(REQUIRED_CHANNELS),
        "dwell_seconds": dwell_seconds,
        "max_segments": max_segments,
        "tool_versions": versions,
        "thresholds": {
            "ott_loudness_target_lufs": OTT_LOUDNESS_TARGET_LUFS,
            "ott_loudness_tolerance_lufs": OTT_LOUDNESS_TOLERANCE_LUFS,
            "silence_floor_lufs": SILENCE_FLOOR_LUFS,
            "continuity_tolerance": CONTINUITY_TOLERANCE,
            "hls_target_segment_seconds": HLS_TARGET_SEGMENT_SECONDS,
            "hls_playlist_size": HLS_PLAYLIST_SIZE,
            "caption_window_seconds": CAPTION_WINDOW_SECONDS,
            "caption_window_exclude_newest": CAPTION_WINDOW_EXCLUDE_NEWEST,
            "caption_receipt_fresh_seconds": CAPTION_RECEIPT_FRESH_SECONDS,
            "caption_keep_heartbeat_fresh_seconds": CAPTION_KEEP_HEARTBEAT_FRESH_SECONDS,
            "caption_keep_gap_tolerance": CAPTION_KEEP_GAP_TOLERANCE,
            "source": (
                "civiccast.stream.loudness / civiccast.egress.compliance / "
                "civiccast.egress.preparer / civiccast.egress.sinks.HlsSink"
            ),
        },
        "channels": channels,
        "caption_keep": {
            "root": str(caption_keep.root) if caption_keep is not NO_CAPTION_KEEP else None,
            "usable": caption_keep.usable,
            "heartbeat_age_seconds": caption_keep.heartbeat_age_seconds,
            "note": caption_keep.note,
        },
        "verdict": overall,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Beta.10 bounded read-only live-HLS media verifier")
    parser.add_argument(
        "--hls-root",
        type=Path,
        default=Path(r"C:\ProgramData\CivicCast\data\egress\live-hls"),
    )
    parser.add_argument("--out", type=Path, required=True, help="evidence JSON output path")
    parser.add_argument("--channels", nargs="+", default=list(REQUIRED_CHANNELS))
    parser.add_argument("--max-segments", type=int, default=DEFAULT_MAX_SEGMENTS)
    parser.add_argument("--dwell-seconds", type=float, default=5.0)
    parser.add_argument(
        "--caption-keep-dir",
        type=Path,
        default=None,
        help=(
            "folder of plain copies of finished segments kept by "
            # `%%`, not `%`: argparse runs every help string through `%`
            # formatting, so a bare `%TEMP%` here makes --help raise
            # "ValueError: unsupported format character 'T'".
            r"bin\segment_keeper.py (default: %%TEMP%%\cc-caption-keep when its heartbeat is fresh)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # An explicit `--caption-keep-dir` is used as given; otherwise look in the
    # keeper's default folder, so a rung ALREADY RUNNING (which passes no option)
    # benefits from a keeper started beside it without a restart.  Either way the
    # heartbeat decides whether the copies may be used, and the evidence says
    # which of the two it was -- a stale or absent keeper is today's behaviour.
    requested = args.caption_keep_dir is not None
    caption_keep = resolve_caption_keep(
        args.caption_keep_dir if requested else default_caption_keep_dir(), requested=requested
    )
    report = verify_all(
        args.hls_root,
        channel_ids=tuple(args.channels),
        max_segments=args.max_segments,
        dwell_seconds=args.dwell_seconds,
        caption_keep=caption_keep,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == Verdict.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
