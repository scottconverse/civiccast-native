#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Bounded, read-only continuous emitted-HLS audio proof.

Why this exists (scope of the claim)
------------------------------------
``verify_beta10_live_hls_media.py`` measures a handful of newest 2 s HLS
segments -- about 8 s of audio per channel.  EBU R128 / ITU-R BS.1770
*integrated* loudness is not meaningful over 8 s of variable speech, so that
window can neither PASS nor FAIL a channel's loudness compliance.  This tool
captures a *continuous* >=3-minute emitted-HLS window per channel into an
immutable snapshot, then measures that window once with the installed ffmpeg.

It deliberately does NOT relax the configured target.  The policy band stays
-16 LUFS +/-1 LU.  The only thing this tool fixes is the *duration* of the
measurement: a short (or structurally broken) window is reported UNVERIFIED or
FAIL, never PASS.

Sibling, not replacement
------------------------
This is a separate script from ``verify_beta10_live_hls_media.py``.  That
short-window verifier keeps its job (decodability, continuity, caption
decode-back, freshness).  This tool owns exactly one extra question: "over a
long enough *continuous* emitted window, is the audio within the configured
loudness band?"  Neither script edits the other.

Read-only guarantee
-------------------
Nothing here writes to, restarts, or controls the live station.  It reads
files under ``--hls-root`` and shells out to read-only ffmpeg/ffprobe
analyzers.  The only files it creates are copies placed under its own
``--scratch-dir`` (for the immutable snapshot) and its own evidence JSON under
``--out``.  It never writes in the HLS root or the caption work dir.

Privacy
-------
No speech, cue, or caption text is ever read or persisted.  The tool opens
only ``.ts`` container bytes; it does not touch ``active.vtt`` or any timed
text.  Evidence records only numeric measurements and content hashes.

Immutability and the rotation race
----------------------------------
A live HLS writer rotates its playlist and deletes old segments continuously.
Reading the playlist, then reading each listed file in place, is a race: by
the time ffmpeg opens segment N, the writer may have already overwritten or
deleted it.  This tool therefore (1) snapshots the playlist, (2) copies each
referenced segment into the scratch directory *at capture time*, verifying the
copy's size and hash, and (3) measures the immutable copies afterward.  A
segment that has already vanished at copy time is a hard FAIL, not a silently
shortened window.

Fail-closed matrix (all produce FAIL or UNVERIFIED)
---------------------------------------------------
* playlist missing / unparseable
* a playlist-referenced segment missing or deleted mid-capture
* partial / truncated segment (copy size changed between stat and read)
* sequence gap in the captured window
* timestamp discontinuity between consecutive segments
* capture shorter than ``--min-duration-seconds``
* ffmpeg/ffprobe unavailable or erroring
* unparseable loudness summary
* measured integrated loudness outside the configured band

Usage
-----

    python scripts/capture_emitted_hls_audio_proof.py \
        --hls-root "C:\ProgramData\CivicCast\data\egress\live-hls" \
        --channels public government education \
        --duration-seconds 200 \
        --min-duration-seconds 180 \
        --out proof.json

Exit codes:

    0  -- every required channel PASSed a duration-qualified in-band window
    1  -- at least one channel FAILed
    2  -- at least one channel could not be verified (UNVERIFIED / NOT_PROVEN)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

#: Configured OTT streaming loudness target and tolerance (policy, not a knob
#: this tool may widen).  Unified spec Section 16.2a.
OTT_LOUDNESS_TARGET_LUFS: Final[float] = -16.0
OTT_LOUDNESS_TOLERANCE_LUFS: Final[float] = 1.0

#: A measurement at or below this integrated LUFS is indistinguishable from
#: silence -- imported policy constant (civiccast.egress.preparer).
SILENCE_FLOOR_LUFS: Final[float] = -60.0

#: Minimum continuous capture required before an integrated-loudness verdict
#: may be issued at all.  Below this the result is UNVERIFIED, never PASS and
#: never a loudness FAIL: an 8 s sample does not measure integrated loudness.
DEFAULT_MIN_DURATION_SECONDS: Final[float] = 180.0

#: Default capture length.  Long enough to cover the minimum with margin for
#: one rotation cycle.
DEFAULT_DURATION_SECONDS: Final[float] = 200.0

DEFAULT_CHANNELS: Final[tuple[str, ...]] = ("public", "government", "education")

#: Bounded per-analyzer wall-clock ceiling.
ANALYZER_TIMEOUT_SECONDS: Final[float] = 300.0

#: Poll spacing between playlist snapshots while capturing.
DEFAULT_POLL_SECONDS: Final[float] = 2.0

#: Hard ceiling on accumulated segments so scratch cannot grow without bound.
#: 300 segments * ~2 s = ~10 min of window at a 2 s cadence.
DEFAULT_MAX_SEGMENTS: Final[int] = 300

#: Hard ceiling on total capture wall-clock (seconds) before the accumulation
#: loop gives up and reports UNVERIFIED.  Well above the >=3 min target.
DEFAULT_MAX_WAIT_SECONDS: Final[float] = 420.0

#: The relay replaces ``playlist.m3u8`` atomically and writes each segment out
#: of band, so a read that lands inside that window on Windows gets EACCES (or
#: ENOENT for the instant the name is gone).  A transient race is not a station
#: fault: every live read is retried this many times, this far apart, before it
#: fails exactly as it did before the retry existed (U48).
RACE_RETRY_ATTEMPTS: Final[int] = 20
RACE_RETRY_DELAY_SECONDS: Final[float] = 0.1

#: The two errnos an atomic replace produces, and only those two: a retry here
#: must never absorb a real permission failure or a real absence past the
#: budget.
_RACE_ERRORS: Final[tuple[type[OSError], ...]] = (PermissionError, FileNotFoundError)

#: A segment whose observed size is 0, or which reports a duration wildly
#: different from its playlist EXTINF, is treated as partial rather than
#: trusted.  0.5 s of drift on a 2 s segment is the tolerated ceiling.
_SEGMENT_DURATION_TOLERANCE_SECONDS: Final[float] = 0.75

_LOUDNESS_I_RE = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS\b")
_LOUDNESS_LRA_RE = re.compile(r"\bLRA:\s*(-?\d+(?:\.\d+)?)\s+LU\b")
_LOUDNESS_PEAK_RE = re.compile(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s+dBFS\b")


class Verdict:
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    NOT_PROVEN = "NOT_PROVEN"


#: Release-grade runs must sample at least this much continuous audio before a
#: loudness PASS is credible.  A caller may run a shorter window for diagnosis,
#: but must not label it release-grade.
RELEASE_MIN_DURATION_SECONDS: Final[float] = 180.0

#: The exact station channel set a release-grade PASS must cover.  A subset (or
#: an empty set) may run for diagnosis but is never release-grade.
REQUIRED_CHANNELS: Final[tuple[str, ...]] = ("public", "government", "education")

#: Hard upper bounds so the "bounded" claim is real, not nominal.
MAX_SEGMENTS_CAP: Final[int] = 600          # ~20 min at a 2 s cadence
MAX_WAIT_SECONDS_CAP: Final[float] = 1800.0  # 30 min wall clock

#: Segment names in a playlists we will snapshot: a bare file name ending
#: ``.ts`` with no directory component.  Anything else (``../``, absolute,
#: nested, drive-relative) is refused rather than written.
_SAFE_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]+\.ts$")

#: A channel id we will accept as a single directory name.
_SAFE_CHANNEL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_finite(value: float) -> bool:
    """True when ``value`` is a finite, real number (rejects NaN/inf)."""

    import math

    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _resolve(p: Path) -> Path:
    """Absolute, symlink-resolved path for containment comparisons."""

    return p.expanduser().resolve()


def _is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` is ``parent`` or lives strictly beneath it."""

    child_r, parent_r = _resolve(child), _resolve(parent)
    return child_r == parent_r or parent_r in child_r.parents


def _is_under(child: Path, parent: Path) -> bool:
    """True only when ``child`` lives strictly beneath ``parent``."""

    child_r, parent_r = _resolve(child), _resolve(parent)
    return parent_r in child_r.parents


@dataclass(frozen=True)
class ScratchDir:
    """An owned scratch directory the tool created and may safely delete.

    ``parent`` is the user-supplied location (never deleted).  ``owned_dir`` is
    a freshly-created child of it, and only ever that child is removed.
    """

    parent: Path
    owned_dir: Path

    def remove(self) -> bool:
        """Delete ONLY ``owned_dir`` after re-proving it is safe to do so."""

        return safe_remove_owned_dir(obj=self, target=self.owned_dir)


def safe_remove_owned_dir(*, obj: ScratchDir, target: Path) -> bool:
    """Recursively delete ``target`` only when every safety check holds.

    Refuses -- returning False without deleting -- when: ``target`` is not
    exactly ``obj.owned_dir``; the owned dir is no longer strictly beneath its
    parent; the owned dir has become a symlink/junction; the owned dir is a
    drive root, the user's home, or any resolved location that is not our own
    freshly-created child.
    """

    try:
        target_r = _resolve(target)
        owned_r = _resolve(obj.owned_dir)
        parent_r = _resolve(obj.parent)
    except OSError:
        return False

    if target_r != owned_r:
        return False
    if not _is_under(owned_r, parent_r):
        return False
    if target.is_symlink() or obj.owned_dir.is_symlink():
        return False
    # Windows junctions / other reparse points resolve to an unrelated subtree
    # while still being a directory, so an rmtree would delete the target's
    # contents.  Refuse them explicitly (``is_junction`` exists on 3.12+).
    is_junction = getattr(Path, "is_junction", None)
    if callable(is_junction):
        try:
            if obj.owned_dir.is_junction():
                return False
        except OSError:
            return False
    try:
        if Path(owned_r).is_symlink():
            return False
    except OSError:
        return False
    if owned_r == parent_r or owned_r.parent == owned_r:  # drive root / self-parent
        return False
    if owned_r == Path.home().resolve():
        return False
    try:
        shutil.rmtree(owned_r)
    except OSError:
        return False
    return True


def scratch_parent_bounds_error(parent: Path, *, hls_root: Path) -> str | None:
    """Return a refusal reason when the requested scratch parent is unsafe."""

    try:
        parent_r = _resolve(parent)
        root_r = _resolve(hls_root)
    except OSError as exc:
        return f"scratch directory could not be resolved: {exc}"

    if parent_r == root_r or _is_within(root_r, parent_r):
        return (
            f"scratch directory {parent_r} is inside (or is) the read-only HLS root "
            f"{root_r}; refusing to use a scratch location the tool must never delete"
        )
    if _is_within(parent_r, root_r):
        return (
            f"scratch directory {parent_r} is inside the read-only HLS root "
            f"{root_r}; refusing"
        )
    return None


def prepare_scratch_dir(parent: Path) -> ScratchDir:
    """Create a UNIQUE owned scratch child under ``parent``.

    The parent is user-owned state and is never deleted.  The child name is
    unique (``mkdtemp``) so a second run cannot collide with -- or delete -- a
    first run's directory, unlike a fixed timestamp name.
    """

    import tempfile

    parent = _resolve(parent)
    parent.mkdir(parents=True, exist_ok=True)
    owned = Path(
        tempfile.mkdtemp(prefix="civiccast-hls-audio-proof-", dir=str(parent))
    ).resolve()
    return ScratchDir(parent=parent, owned_dir=owned)


def validate_channel_id(channel_id: str) -> str | None:
    """Return a refusal reason when the channel id is not a safe directory name."""

    if not channel_id or not _SAFE_CHANNEL_RE.fullmatch(channel_id):
        return f"unsafe channel id {channel_id!r}: expected a plain directory name"
    if channel_id in {".", ".."}:
        return f"unsafe channel id {channel_id!r}"
    return None


def validate_segment_name(name: str) -> str | None:
    """Return a refusal reason when a playlist segment name is unsafe."""

    if not name or "/" in name or "\\" in name:
        return f"unsafe segment name {name!r}: directory components are not allowed"
    if not _SAFE_SEGMENT_RE.fullmatch(name):
        return f"unsafe segment name {name!r}: expected a bare *.ts file name"
    return None

class CaptureError(RuntimeError):
    """A capture-time structural failure that must fail the window closed."""


@dataclass
class Playlist:
    """One parsed HLS media playlist snapshot."""

    path: Path
    media_sequence: int | None = None
    target_duration: float | None = None
    segments: list[str] = field(default_factory=list)
    segment_infos: list[float] = field(default_factory=list)
    parse_error: str | None = None
    sequence_gaps: list[int] = field(default_factory=list)
    sequence_numbers: list[int] = field(default_factory=list)
    discontinuity_indices: list[int] = field(default_factory=list)


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
        raise CaptureError(f"unreadable live file: {path}")
    raise last


def _read_live_bytes(path: Path) -> bytes:
    """Read a live file's bytes whole, retrying a racing atomic replace."""

    last: OSError | None = None
    for attempt in range(RACE_RETRY_ATTEMPTS):
        try:
            with path.open("rb") as handle:
                return handle.read()
        except _RACE_ERRORS as exc:
            last = exc
            if attempt + 1 < RACE_RETRY_ATTEMPTS:
                time.sleep(RACE_RETRY_DELAY_SECONDS)
    if last is None:  # pragma: no cover - the budget is at least one attempt
        raise CaptureError(f"unreadable live file: {path}")
    raise last


def _wait_for_file(path: Path) -> bool:
    """True once the path exists; False after the race-retry budget.

    ``Path.is_file()`` swallows ``OSError``, so a file that is momentarily gone
    during the relay's replace and one that is genuinely absent look identical
    here -- the retry is the only thing that separates them.
    """

    for attempt in range(RACE_RETRY_ATTEMPTS):
        if path.is_file():
            return True
        if attempt + 1 < RACE_RETRY_ATTEMPTS:
            time.sleep(RACE_RETRY_DELAY_SECONDS)
    return False


def parse_playlist(path: Path) -> Playlist:
    """Parse a media playlist, recording sequence gaps and parse failures.

    The read is retried through a racing atomic replace (``_read_live_text``),
    and the retry is built on the read itself rather than on a pre-check:
    ``Path.is_file()`` swallows ``OSError``, so an ``is_file()`` guard would
    report a raced playlist as "playlist missing" -- a station fault that never
    happened.  A playlist that is still unreadable once the budget is spent
    reports exactly what it reported before the retry existed.
    """

    try:
        text = _read_live_text(path)
    except FileNotFoundError:
        return Playlist(path=path, parse_error="playlist missing")
    except OSError as exc:
        return Playlist(path=path, parse_error=f"playlist unreadable: {exc}")

    lines = text.splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        return Playlist(path=path, parse_error="missing #EXTM3U")

    media_sequence: int | None = None
    target_duration: float | None = None
    names: list[str] = []
    infos: list[float] = []
    discontinuity_indices: list[int] = []
    pending: float | None = None
    pending_discontinuity = False
    for raw in lines:
        line = raw.strip()
        if line == "#EXT-X-DISCONTINUITY":
            pending_discontinuity = True
            continue
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
                pending = float(line.split(":", 1)[1].split(",")[0].strip())
            except ValueError:
                pending = None
        elif line and not line.startswith("#"):
            if pending_discontinuity:
                discontinuity_indices.append(len(names))
                pending_discontinuity = False
            names.append(line)
            infos.append(pending if pending is not None else float("nan"))
            pending = None

    if not names:
        return Playlist(
            path=path,
            media_sequence=media_sequence,
            target_duration=target_duration,
            parse_error="playlist lists no segments",
        )

    sequences: list[int] = []
    for name in names:
        match = re.search(r"(\d+)\.ts$", name)
        if match is None:
            sequences.append(-1)
        else:
            sequences.append(int(match.group(1)))

    gaps: list[int] = []
    for index in range(1, len(sequences)):
        previous, current = sequences[index - 1], sequences[index]
        if previous < 0 or current < 0:
            continue
        if current != previous + 1:
            gaps.append(index)

    return Playlist(
        path=path,
        media_sequence=media_sequence,
        target_duration=target_duration,
        segments=names,
        segment_infos=infos,
        sequence_numbers=sequences,
        sequence_gaps=gaps,
        discontinuity_indices=discontinuity_indices,
    )



def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def capture_channel(
    channel_id: str,
    hls_root: Path,
    *,
    scratch_dir: Path | None = None,
    min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS,
    required_segments: int | None = None,
    playlist_reader: Callable[[Path], Playlist] = parse_playlist,
) -> dict[str, Any]:
    """Copy one channel's current playlist-referenced segments into scratch.

    Returns a snapshot record.  The returned ``status`` reflects *structural*
    capture validity only -- loudness is measured later against the immutable
    snapshot.  A structurally invalid capture is FAIL and is never measured.
    """

    channel_error = validate_channel_id(channel_id)
    if channel_error is not None:
        return {
            "channel_id": channel_id,
            "captured_at_utc": _utc_now(),
            "blocking_reasons": [channel_error],
            "segments": [],
            "status": Verdict.FAIL,
        }
    channel_dir = hls_root / channel_id
    playlist = playlist_reader(channel_dir / "playlist.m3u8")
    scratch = scratch_dir or (hls_root / channel_id / ".capture-scratch")

    evidence: dict[str, Any] = {
        "channel_id": channel_id,
        "channel_dir": str(channel_dir),
        "captured_at_utc": _utc_now(),
        "media_sequence": playlist.media_sequence,
        "target_duration": playlist.target_duration,
        "playlist_parse_error": playlist.parse_error,
        "blocking_reasons": [],
        "segments": [],
    }

    if playlist.parse_error is not None:
        evidence["blocking_reasons"].append(f"playlist unusable: {playlist.parse_error}")
        evidence["status"] = Verdict.FAIL
        return evidence

    if playlist.sequence_gaps:
        evidence["blocking_reasons"].append(
            f"playlist sequence gap at index(es) {playlist.sequence_gaps}"
        )

    snapshot_root = scratch / channel_id
    snapshot_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    seen_names: set[str] = set()
    total_duration = 0.0

    for index, name in enumerate(playlist.segments):
        if name in seen_names:
            continue
        sequence = playlist.sequence_numbers[index] if index < len(playlist.sequence_numbers) else -1
        if sequence in seen_sequences:
            continue
        seen_names.add(name)
        if sequence >= 0:
            seen_sequences.add(sequence)

        source = channel_dir / name
        extinf = playlist.segment_infos[index] if index < len(playlist.segment_infos) else float("nan")
        record: dict[str, Any] = {
            "name": name,
            "sequence": sequence,
            "extinf_seconds": extinf,
            "present": source.is_file(),
        }
        if not source.is_file():
            record["capture_status"] = "missing"
            evidence["blocking_reasons"].append(f"referenced segment missing: {name}")
            records.append(record)
            continue

        snapshot_path = snapshot_root / name
        try:
            size_before = source.stat().st_size
            if size_before <= 0:
                raise CaptureError(f"segment is empty: {name}")
            digest = hashlib.sha256()
            with source.open("rb") as src, snapshot_path.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    dst.write(chunk)
            size_after = source.stat().st_size
            copied = snapshot_path.stat().st_size
            if copied != size_before or size_after != size_before:
                raise CaptureError(f"segment changed size during capture: {name}")
        except (OSError, CaptureError) as exc:
            record["capture_status"] = "partial"
            evidence["blocking_reasons"].append(f"incomplete capture for {name}: {exc}")
            snapshot_path.unlink(missing_ok=True)
            records.append(record)
            continue

        record.update(
            {
                "capture_status": "complete",
                "bytes": copied,
                "sha256": digest.hexdigest(),
                "snapshot_path": str(snapshot_path),
            }
        )
        if extinf == extinf:  # not NaN
            total_duration += float(extinf)
        records.append(record)

    evidence["segments"] = records
    evidence["captured_segment_count"] = sum(
        1 for record in records if record.get("capture_status") == "complete"
    )
    evidence["captured_duration_seconds"] = total_duration

    if playlist.sequence_gaps:
        evidence["blocking_reasons"].append("sequence gap in captured window")

    if required_segments is not None and evidence["captured_segment_count"] < required_segments:
        evidence["blocking_reasons"].append(
            f"captured {evidence['captured_segment_count']} segment(s), "
            f"required {required_segments}"
        )

    # A structurally valid window that is merely too SHORT is not a loudness
    # failure -- integrated loudness is unmeasurable at that length, so the
    # channel is UNVERIFIED rather than FAIL.  Structural defects keep FAIL.
    if min_duration_seconds > 0 and total_duration < min_duration_seconds:
        evidence["duration_shortfall"] = (
            f"captured duration {total_duration:.1f}s is shorter than the "
            f"required {min_duration_seconds:.1f}s"
        )

    if evidence["blocking_reasons"]:
        evidence["status"] = Verdict.FAIL
    elif evidence.get("duration_shortfall"):
        evidence["status"] = Verdict.UNVERIFIED
    else:
        evidence["status"] = Verdict.PASS
    return evidence


#: MPEG-TS PTS is a 33-bit, 90 kHz counter.  Deltas are taken modulo 2**33 so
#: a legal wrap is not misread as a backwards jump.
PTS_CLOCK_HZ: Final[int] = 90_000
PTS_MODULUS: Final[int] = 1 << 33

#: MPEG-TS PCR is a 42-bit counter.  The TSDuck ``pcrextract`` CSV ``Value``
#: column is the 27 MHz base (measured: 26,550,000 ticks per second on the
#: shipped runtime's segments).  We do NOT gate on a PCR cadence -- only on
#: monotonicity modulo 2**42 -- because the per-segment PCR base is re-based by
#: real muxers and the 27 MHz/base-90 kHz distinction makes a tick-for-tick
#: cadence check unsound without a pinned unit.
PCR_MODULUS: Final[int] = 1 << 42

#: One frame at 30 fps in 90 kHz PTS ticks; used as the PTS delta tolerance.
_PTS_FRAME_TOLERANCE_TICKS: Final[int] = 3000


def _modular_delta(previous: int, current: int, modulus: int) -> int:
    """Forward counter delta with wrap: ``(current - previous) % modulus``.

    Returns a value in ``[0, modulus)``.  A same-or-backwards step yields
    either 0 (identical) or a very large value near the modulus; callers treat
    both as failure via the expected-delta comparison below.
    """

    return (int(current) - int(previous)) % modulus


def evaluate_pts_pcr_continuity(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Require strictly-forward, gap-free PTS across the captured window.

    **PTS is the load-bearing gap proof.**  PTS is a 33-bit 90 kHz counter, so
    each adjacent delta is computed modulo 2**33 and must match the previous
    segment's duration (within one frame) -- a skip, a stall, a backwards jump,
    or an overlap fails.

    **PCR is a presence + monotonicity sanity signal only.**  The TSDuck value
    is the 27 MHz PCR base (measured) and real muxers re-base it per segment, so
    PCR cadence is deliberately NOT asserted and the tick unit is never assumed
    for a gap verdict.  A non-forward PCR (modulo 2**42) fails; a missing PCR
    is UNVERIFIED.  This intentionally narrows the "gap-free" claim to PTS.
    """

    problems: list[str] = []
    if not records:
        return {
            "status": Verdict.UNVERIFIED,
            "problems": ["no segments to check"],
            "detail": "no segments to check",
        }

    pts_values = [record.get("video_start_pts") for record in records]
    pcr_values = [record.get("pcr_first") for record in records]
    durations = [record.get("duration") for record in records]

    if any(value is None for value in pts_values):
        return {
            "status": Verdict.UNVERIFIED,
            "problems": ["one or more segments report no video PTS"],
            "detail": "one or more segments report no video PTS",
        }
    if any(value is None for value in pcr_values):
        return {
            "status": Verdict.UNVERIFIED,
            "problems": ["one or more segments report no PCR"],
            "detail": "one or more segments report no PCR",
        }

    for index in range(1, len(pts_values)):
        delta = _modular_delta(pts_values[index - 1], pts_values[index], PTS_MODULUS)
        previous_duration = durations[index - 1]
        if delta == 0:
            problems.append(f"segment {index} PTS did not advance (delta 0 ticks)")
            continue
        if previous_duration is not None:
            expected = round(float(previous_duration) * PTS_CLOCK_HZ)
            # A wrap produces a small positive delta; a real forward step is
            # ~expected.  Anything far from expected (including a wrap-induced
            # near-modulus value) is a gap or overlap.
            if abs(delta - expected) > _PTS_FRAME_TOLERANCE_TICKS:
                problems.append(
                    f"segment {index} PTS delta {delta} ticks != expected {expected}"
                )

    for index in range(1, len(pcr_values)):
        delta = _modular_delta(pcr_values[index - 1], pcr_values[index], PCR_MODULUS)
        if delta == 0:
            problems.append(f"segment {index} PCR did not advance (delta 0 ticks)")
            break

    return {
        "status": Verdict.FAIL if problems else Verdict.PASS,
        "problems": problems,
        "detail": "PTS advances gap-free; PCR monotonic (cadence not asserted)"
        if not problems
        else "; ".join(problems),
    }


def accumulate_channel(
    channel_id: str,
    hls_root: Path,
    *,
    scratch_dir: Path,
    target_duration_seconds: float,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    playlist_reader: Callable[[Path], Playlist] = parse_playlist,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_poll: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Accumulate successive playlist windows into one continuous snapshot.

    Each poll snapshots the *current* playlist and copies only segments whose
    sequence number has not already been captured.  The window is accepted only
    when its sequences are exactly contiguous -- a rotation that skips a
    sequence number, replays an out-of-order window, or hides a partial file
    fails the capture closed.

    Bounded three ways: ``max_wait_seconds`` wall-clock, ``max_segments`` count,
    and the caller's scratch dir (removed on completion by ``main``).
    """

    evidence: dict[str, Any] = {
        "channel_id": channel_id,
        "channel_dir": str(hls_root / channel_id),
        "captured_at_utc": _utc_now(),
        "blocking_reasons": [],
        "segments": [],
        "captured_duration_seconds": 0.0,
        "captured_segment_count": 0,
        "target_duration_seconds": target_duration_seconds,
        "polls": 0,
    }

    channel_error = validate_channel_id(channel_id)
    if channel_error is not None:
        evidence["blocking_reasons"].append(channel_error)
        evidence["status"] = Verdict.FAIL
        return evidence

    channel_dir = hls_root / channel_id
    snapshot_root = scratch_dir / channel_id
    snapshot_root.mkdir(parents=True, exist_ok=True)

    evidence["captured_at_utc"] = _utc_now()

    captured: dict[int, dict[str, Any]] = {}
    seen_hashes: set[str] = set()
    started_at = monotonic()

    while True:
        evidence["polls"] += 1
        playlist = playlist_reader(channel_dir / "playlist.m3u8")
        if playlist.parse_error is not None:
            evidence["blocking_reasons"].append(f"playlist unusable: {playlist.parse_error}")
            break
        if playlist.sequence_gaps:
            evidence["blocking_reasons"].append(
                f"playlist sequence gap at index(es) {playlist.sequence_gaps}"
            )
            break
        if playlist.discontinuity_indices:
            evidence["blocking_reasons"].append(
                "playlist declares #EXT-X-DISCONTINUITY at segment index(es) "
                f"{playlist.discontinuity_indices}; the window is not one "
                "continuous timeline"
            )
            break

        progressed = False
        for index, name in enumerate(playlist.segments):
            sequence = (
                playlist.sequence_numbers[index]
                if index < len(playlist.sequence_numbers)
                else -1
            )
            name_error = validate_segment_name(name)
            if name_error is not None:
                evidence["blocking_reasons"].append(name_error)
                break
            if sequence < 0 or sequence in captured:
                continue

            # Every sequence between the oldest captured and this one must
            # exist -- a jump means the rotation skipped a segment we can never
            # recover, so the window is not continuous.  A HIGHER sequence than
            # expected_next is a real skip; a LOWER one is an already-superseded
            # replay and is simply ignored (dedupe, not a failure).
            if captured:
                expected_next = max(captured) + 1
                if sequence > expected_next:
                    evidence["blocking_reasons"].append(
                        f"sequence rotation skipped from {expected_next} to {sequence}"
                    )
                    break
                if sequence < expected_next:
                    continue

            source = channel_dir / name
            extinf = (
                playlist.segment_infos[index]
                if index < len(playlist.segment_infos)
                else float("nan")
            )
            record = _copy_segment(source, snapshot_root / name, sequence, extinf, evidence)
            if record is None:
                # _copy_segment already recorded a structural blocker.
                break
            digest = record["sha256"]
            if digest in seen_hashes:
                # Same bytes already captured under another sequence: a replay.
                # Drop the duplicate copy and keep scanning this same playlist.
                (snapshot_root / name).unlink(missing_ok=True)
                continue
            seen_hashes.add(digest)
            captured[sequence] = record
            progressed = True

        if evidence["blocking_reasons"]:
            break
        if len(captured) > max_segments:
            evidence["blocking_reasons"].append(
                f"accumulated more than max_segments={max_segments} segments"
            )
            break

        evidence["segments"] = [captured[s] for s in sorted(captured)]
        evidence["captured_segment_count"] = len(captured)
        evidence["captured_duration_seconds"] = sum(
            float(r["extinf_seconds"])
            for r in captured.values()
            if isinstance(r.get("extinf_seconds"), float) and r["extinf_seconds"] == r["extinf_seconds"]
        )

        if evidence["captured_duration_seconds"] >= target_duration_seconds:
            break

        if monotonic() - started_at >= max_wait_seconds:
            evidence["blocking_reasons"].append(
                f"capture timed out after {max_wait_seconds:.0f}s with "
                f"{evidence['captured_duration_seconds']:.1f}s captured"
            )
            break

        if not progressed and on_poll is None:
            # Nothing new and no writer driver: wait then re-poll (bounded by
            # the timeout above), so a stalled writer ends as UNVERIFIED.
            sleep(poll_seconds)
        elif poll_seconds > 0:
            sleep(poll_seconds)

        if on_poll is not None:
            on_poll()

    evidence["segments"] = [captured[s] for s in sorted(captured)]
    evidence["captured_segment_count"] = len(captured)
    evidence["captured_duration_seconds"] = sum(
        float(r["extinf_seconds"])
        for r in captured.values()
        if isinstance(r.get("extinf_seconds"), float) and r["extinf_seconds"] == r["extinf_seconds"]
    )

    # Contiguity of what we actually captured (independent of any per-poll
    # playlist ordering): 1, 2, 3, ... must be unbroken end-to-end.
    if captured:
        sequences = sorted(captured)
        if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
            evidence["blocking_reasons"].append("captured window is not sequence-contiguous")

    if evidence["blocking_reasons"]:
        evidence["status"] = Verdict.FAIL
    elif evidence["captured_duration_seconds"] < target_duration_seconds:
        evidence["duration_shortfall"] = (
            f"accumulated {evidence['captured_duration_seconds']:.1f}s is shorter than "
            f"the requested {target_duration_seconds:.1f}s"
        )
        evidence["status"] = Verdict.UNVERIFIED
    else:
        evidence["status"] = Verdict.PASS
    return evidence


def _copy_segment(
    source: Path,
    snapshot_path: Path,
    sequence: int,
    extinf: float,
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """Copy one TS immutably; record a partial/missing segment as a blocker.

    Both live touches are race-aware (U48): the presence check and the byte
    read are each retried through the relay's replace before a segment is
    called missing or its capture called incomplete.
    """

    present = _wait_for_file(source)
    record: dict[str, Any] = {
        "name": source.name,
        "sequence": sequence,
        "extinf_seconds": extinf,
        "present": present,
    }
    if not present:
        record["capture_status"] = "missing"
        evidence["blocking_reasons"].append(f"referenced segment missing: {source.name}")
        return None

    try:
        size_before = source.stat().st_size
        if size_before <= 0:
            raise CaptureError(f"segment is empty: {source.name}")
        data = _read_live_bytes(source)
        if len(data) != size_before:
            raise CaptureError(f"segment changed size during capture: {source.name}")
        digest = hashlib.sha256(data)
        snapshot_path.write_bytes(data)
        size_after = source.stat().st_size
        copied = snapshot_path.stat().st_size
        if copied != size_before or size_after != size_before:
            raise CaptureError(f"segment changed size during capture: {source.name}")
    except (OSError, CaptureError) as exc:
        evidence["blocking_reasons"].append(f"incomplete capture for {source.name}: {exc}")
        snapshot_path.unlink(missing_ok=True)
        return None

    record.update(
        {
            "capture_status": "complete",
            "bytes": copied,
            "sha256": digest.hexdigest(),
            "snapshot_path": str(snapshot_path),
        }
    )
    return record

def parse_ebur128(stderr: str) -> dict[str, float | None]:
    """Extract integrated LUFS, LRA, and true peak from ffmpeg ebur128 output."""

    def last(pattern: re.Pattern[str]) -> float | None:
        matches = pattern.findall(stderr)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
            return None

    return {
        "integrated_lufs": last(_LOUDNESS_I_RE),
        "lra_lu": last(_LOUDNESS_LRA_RE),
        "true_peak_dbfs": last(_LOUDNESS_PEAK_RE),
    }


def _default_run(
    args: list[str], *, timeout: float = ANALYZER_TIMEOUT_SECONDS
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(exc)}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def measure_window(
    *,
    channel_id: str,
    concat_path: Path,
    duration_seconds: float,
    min_duration_seconds: float,
    ffmpeg: Path | None = None,
    run: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure one captured window; fail closed on short/unparseable/error.

    ``duration_seconds`` is the playlist-declared duration of the immutable
    snapshot.  If it is below ``min_duration_seconds`` the analyzer is not run
    at all -- an 8 s sample must not be reported as a loudness PASS or FAIL.
    """

    result: dict[str, Any] = {
        "channel_id": channel_id,
        "duration_seconds": duration_seconds,
        "min_duration_seconds": min_duration_seconds,
        "target_lufs": OTT_LOUDNESS_TARGET_LUFS,
        "tolerance_lufs": OTT_LOUDNESS_TOLERANCE_LUFS,
        "integrated_lufs": None,
        "lra_lu": None,
        "true_peak_dbfs": None,
        "within_target": False,
    }

    if duration_seconds < min_duration_seconds:
        result["status"] = Verdict.UNVERIFIED
        result["detail"] = (
            f"window duration {duration_seconds:.1f}s is shorter than the required "
            f"{min_duration_seconds:.1f}s; integrated loudness is not measurable at "
            "this length and no loudness verdict is issued"
        )
        return result

    runner = run or _default_run
    args = [
        str(ffmpeg) if ffmpeg is not None else "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-vn",
        "-filter_complex",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    analysis = runner(args)
    if not analysis.get("ok"):
        result["status"] = Verdict.FAIL
        result["detail"] = (
            f"ebur128 analysis failed (returncode={analysis.get('returncode')}); "
            "the window could not be measured"
        )
        return result

    parsed = parse_ebur128(analysis.get("stderr") or "")
    result.update(parsed)
    integrated = parsed["integrated_lufs"]
    if integrated is None:
        result["status"] = Verdict.FAIL
        result["detail"] = "ffmpeg reported no integrated loudness for the window"
        return result

    if integrated <= SILENCE_FLOOR_LUFS:
        result["status"] = Verdict.FAIL
        result["detail"] = f"window integrated {integrated:.1f} LUFS is at or below silence floor"
        return result

    within = abs(integrated - OTT_LOUDNESS_TARGET_LUFS) <= OTT_LOUDNESS_TOLERANCE_LUFS
    result["within_target"] = within
    result["status"] = Verdict.PASS if within else Verdict.FAIL
    result["detail"] = (
        f"window integrated {integrated:.1f} LUFS over {duration_seconds:.1f}s "
        f"(target {OTT_LOUDNESS_TARGET_LUFS:g} +/- {OTT_LOUDNESS_TOLERANCE_LUFS:g})"
    )
    return result


def _resolve_tsp() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\CivicCast (Native)\packs\native-server-binaries\payload\tsduck\bin\tsp.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("tsp")
    return Path(found) if found else None

def _resolve_ffprobe() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def _first_pcr_from_tsp(tsp: Path, segment: Path) -> int | None:
    """First PCR (90 kHz) in a segment via TSDuck ``pcrextract``.

    TSDuck has no ``--json`` for pcrextract; the CSV columns are
    PID, packet-in-TS, packet-in-PID, Type, Count-in-PID, Value, offset-in-PID,
    offset-from-PCR.  The first row with Type == PCR yields the PCR value.
    TSDuck writes this CSV on stderr in the shipped build.
    """

    result = _default_run([str(tsp), "-I", "file", str(segment), "-P", "pcrextract", "-O", "drop"])
    if not result.get("ok"):
        return None
    for raw in f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}".splitlines():
        line = raw.strip()
        if not line or line.startswith("PID,"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6 and parts[3].upper() == "PCR":
            try:
                return int(parts[5])
            except ValueError:
                return None
    return None


def _default_probe(
    ffprobe: Path,
    segment: Path,
    *,
    tsp: Path | None = None,
) -> dict[str, Any]:
    """Probe one segment for first video PTS, duration, and first PCR.

    PTS + duration come from ffprobe; PCR comes from TSDuck when available.
    A missing PTS or missing PCR is reported as ``None`` and the continuity
    check treats that as UNVERIFIED rather than PASS.
    """

    result = _default_run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=start_pts,duration",
            "-of",
            "json",
            str(segment),
        ]
    )
    if not result.get("ok"):
        return {"status": Verdict.UNVERIFIED, "detail": "ffprobe failed"}

    try:
        payload = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {"status": Verdict.UNVERIFIED, "detail": "ffprobe emitted invalid JSON"}

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    duration = None
    try:
        duration = float(stream.get("duration"))
    except (TypeError, ValueError):
        duration = None
    start_pts = stream.get("start_pts")
    pcr_first = _first_pcr_from_tsp(tsp, segment) if tsp is not None else None
    return {
        "status": Verdict.PASS,
        "video_start_pts": start_pts,
        "duration": duration,
        "pcr_first": pcr_first,
    }


def probe_window_continuity(
    *,
    records: list[dict[str, Any]],
    ffprobe: Path,
    tsp: Path | None = None,
    probe: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Probe each captured segment and evaluate PTS/PCR continuity."""

    probed: list[dict[str, Any]] = []
    for record in records:
        if record.get("capture_status") != "complete":
            continue
        entry = dict(record)
        if probe is not None:
            entry.update(probe(ffprobe, Path(record["snapshot_path"])))
        else:
            entry.update(_default_probe(ffprobe, Path(record["snapshot_path"]), tsp=tsp))
        probed.append(entry)
    return evaluate_pts_pcr_continuity(probed)

def _write_concat(records: list[dict[str, Any]], concat_path: Path) -> None:
    concat_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"file '{Path(record['snapshot_path']).as_posix()}'"
        for record in records
        if record.get("capture_status") == "complete"
    ]
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_channel(
    channel_id: str,
    hls_root: Path,
    *,
    scratch_dir: Path,
    min_duration_seconds: float,
    target_duration_seconds: float | None = None,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
    tsp: Path | None = None,
    run: Callable[..., dict[str, Any]] | None = None,
    probe: Callable[..., dict[str, Any]] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_poll: Callable[..., None] | None = None,
    release_grade: bool = True,
) -> dict[str, Any]:
    """Accumulate a continuous window, prove continuity, then measure loudness."""

    if target_duration_seconds is None:
        target_duration_seconds = min_duration_seconds

    if release_grade and (
        not _is_finite(min_duration_seconds) or min_duration_seconds < RELEASE_MIN_DURATION_SECONDS
    ):
        return {
            "channel_id": channel_id,
            "captured_at_utc": _utc_now(),
            "blocking_reasons": [
                f"release-grade runs require --min-duration-seconds >= "
                f"{RELEASE_MIN_DURATION_SECONDS:g}; got {min_duration_seconds!r}"
            ],
            "segments": [],
            "continuity": {"status": Verdict.FAIL, "detail": "release floor not met"},
            "audio_window": {
                "status": Verdict.FAIL,
                "detail": "release floor not met; no loudness verdict is issued",
                "within_target": False,
            },
            "status": Verdict.FAIL,
        }

    snapshot = accumulate_channel(
        channel_id,
        hls_root,
        scratch_dir=scratch_dir,
        target_duration_seconds=target_duration_seconds,
        max_wait_seconds=max_wait_seconds,
        max_segments=max_segments,
        poll_seconds=poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
        on_poll=on_poll,
    )
    if snapshot["status"] != Verdict.PASS:
        shortfall = snapshot.get("duration_shortfall")
        snapshot["audio_window"] = {
            "status": Verdict.UNVERIFIED if shortfall else Verdict.FAIL,
            "detail": (
                f"{shortfall}; integrated loudness is not measurable at this "
                "length and no loudness verdict is issued"
                if shortfall
                else "capture structurally invalid; no loudness verdict issued"
            ),
            "within_target": False,
        }
        snapshot["status"] = snapshot["audio_window"]["status"]
        return snapshot

    # Continuity MUST be proven before any loudness verdict: a window that
    # splices disjoint timestamps is not a continuous sample, so its
    # integrated loudness is not a valid measurement of the channel.
    if ffprobe is not None:
        continuity = probe_window_continuity(
            records=snapshot["segments"],
            ffprobe=ffprobe,
            tsp=tsp,
            probe=probe,
        )
        snapshot["continuity"] = continuity
        if continuity["status"] != Verdict.PASS:
            snapshot["audio_window"] = {
                "status": continuity["status"],
                "detail": f"timestamp continuity not proven: {continuity['detail']}",
                "within_target": False,
            }
            snapshot["status"] = continuity["status"]
            return snapshot
    else:
        snapshot["continuity"] = {
            "status": Verdict.UNVERIFIED,
            "detail": "ffprobe unavailable; timestamp continuity not proven",
        }
        snapshot["audio_window"] = {
            "status": Verdict.UNVERIFIED,
            "detail": "timestamp continuity not proven (ffprobe unavailable); "
            "no loudness verdict is issued",
            "within_target": False,
        }
        snapshot["status"] = Verdict.UNVERIFIED
        return snapshot

    concat_path = scratch_dir / channel_id / "window.ffconcat"
    _write_concat(snapshot["segments"], concat_path)
    snapshot["audio_window"] = measure_window(
        channel_id=channel_id,
        concat_path=concat_path,
        duration_seconds=snapshot["captured_duration_seconds"],
        min_duration_seconds=min_duration_seconds,
        ffmpeg=ffmpeg,
        run=run,
    )
    snapshot["status"] = snapshot["audio_window"]["status"]
    return snapshot


def _resolve_ffmpeg() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffmpeg.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def verify_all(
    hls_root: Path,
    *,
    channels: tuple[str, ...] = DEFAULT_CHANNELS,
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
    min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS,
    scratch_root: Path | None = None,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
    tsp: Path | None = None,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    keep_scratch: bool = False,
    release_grade: bool = True,
    run: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture + measure every requested channel; overall verdict is fail-closed."""

    blocking: list[str] = []

    # An empty channel set can never be a PASS, and only the exact required
    # station set can be release-grade.
    if not channels:
        blocking.append("no channels requested; an empty set cannot be a PASS")

    if not isinstance(max_segments, int) or max_segments < 1:
        blocking.append(f"max_segments={max_segments!r} must be a positive integer")
    elif max_segments > MAX_SEGMENTS_CAP:
        blocking.append(
            f"max_segments={max_segments} exceeds the hard cap {MAX_SEGMENTS_CAP}"
        )
    if _is_finite(max_wait_seconds) and max_wait_seconds > MAX_WAIT_SECONDS_CAP:
        blocking.append(
            f"max_wait_seconds={max_wait_seconds:g} exceeds the hard cap "
            f"{MAX_WAIT_SECONDS_CAP:g}"
        )

    # Bounds: reject NaN/inf/negative windows and non-positive waits outright.
    for label, value in (
        ("duration_seconds", duration_seconds),
        ("min_duration_seconds", min_duration_seconds),
        ("max_wait_seconds", max_wait_seconds),
    ):
        if not _is_finite(value) or value < 0:
            blocking.append(f"{label}={value!r} must be a finite, non-negative number")
    if _is_finite(max_wait_seconds) and max_wait_seconds <= 0:
        blocking.append("max_wait_seconds must be greater than zero")
    # The scratch PARENT must never be the HLS root or contain it: the tool
    # deletes only its own freshly-created child, but a parent inside the tree
    # still means the tool would create files there.
    parent = scratch_root or Path(
        os.environ.get("TEMP") or os.environ.get("TMP") or "."
    )
    parent_error = scratch_parent_bounds_error(parent, hls_root=hls_root)
    if parent_error is not None:
        blocking.append(parent_error)

    for channel_id in channels:
        channel_error = validate_channel_id(channel_id)
        if channel_error is not None:
            blocking.append(channel_error)

    if blocking:
        return {
            "tool": "capture_emitted_hls_audio_proof",
            "hls_root": str(hls_root),
            "channels_requested": list(channels),
            "started_utc": _utc_now(),
            "finished_utc": _utc_now(),
            "min_duration_seconds": min_duration_seconds,
            "blocking_reasons": blocking,
            "channels": {},
            "verdict": Verdict.FAIL,
        }

    scratch = prepare_scratch_dir(parent)

    started = _utc_now()
    results: dict[str, Any] = {}
    try:
        for channel_id in channels:
            results[channel_id] = verify_channel(
                channel_id,
                hls_root,
                scratch_dir=scratch.owned_dir,
                min_duration_seconds=min_duration_seconds,
                target_duration_seconds=duration_seconds,
                max_wait_seconds=max_wait_seconds,
                max_segments=max_segments,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                tsp=tsp,
                run=run,
            )
    finally:
        # Only the owned child is ever removed; the user's parent is untouched.
        if not keep_scratch:
            scratch.remove()

    statuses = [result["status"] for result in results.values()]
    if Verdict.FAIL in statuses:
        overall = Verdict.FAIL
    elif any(status in (Verdict.UNVERIFIED, Verdict.NOT_PROVEN) for status in statuses):
        overall = Verdict.UNVERIFIED
    else:
        overall = Verdict.PASS

    exact_required = tuple(channels) == REQUIRED_CHANNELS
    is_release_grade = bool(release_grade) and exact_required
    if overall == Verdict.PASS and not is_release_grade:
        # A subset/off-set diagnostic run may not assert a release PASS.
        overall = Verdict.UNVERIFIED

    return {
        "tool": "capture_emitted_hls_audio_proof",
        "scope": (
            "bounded read-only continuous emitted-HLS audio capture and "
            "duration-qualified integrated-loudness measurement"
        ),
        "hls_root": str(hls_root),
        "channels_requested": list(channels),
        "started_utc": started,
        "finished_utc": _utc_now(),
        "target_lufs": OTT_LOUDNESS_TARGET_LUFS,
        "tolerance_lufs": OTT_LOUDNESS_TOLERANCE_LUFS,
        "min_duration_seconds": min_duration_seconds,
        "ffmpeg": str(ffmpeg) if ffmpeg is not None else None,
        "blocking_reasons": [],
        "release_grade": is_release_grade,
        "channels": results,
        "verdict": overall,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded read-only continuous emitted-HLS audio proof"
    )
    parser.add_argument(
        "--hls-root",
        type=Path,
        default=Path(r"C:\ProgramData\CivicCast\data\egress\live-hls"),
    )
    parser.add_argument("--channels", nargs="+", default=list(DEFAULT_CHANNELS))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument(
        "--min-duration-seconds", type=float, default=DEFAULT_MIN_DURATION_SECONDS
    )
    parser.add_argument("--scratch-dir", type=Path, default=None)
    parser.add_argument("--keep-scratch", action="store_true")
    parser.add_argument("--max-wait-seconds", type=float, default=DEFAULT_MAX_WAIT_SECONDS)
    parser.add_argument("--max-segments", type=int, default=DEFAULT_MAX_SEGMENTS)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help=(
            "explicitly non-release run: subset channel sets and short windows "
            "are allowed and the verdict can never be release-grade PASS"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    # Read-only guarantee: the evidence file may NOT land inside the tree we
    # are only supposed to read.  Refuse before doing any work.
    if _is_within(args.out, args.hls_root):
        print(
            json.dumps(
                {
                    "tool": "capture_emitted_hls_audio_proof",
                    "verdict": Verdict.FAIL,
                    "blocking_reasons": [
                        f"--out {args.out} is inside the read-only HLS root "
                        f"{args.hls_root}; refusing to write into the tree under audit",
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    scratch_parent = args.scratch_dir or Path(
        os.environ.get("TEMP") or os.environ.get("TMP") or "."
    )
    report = verify_all(
        args.hls_root,
        channels=tuple(args.channels),
        duration_seconds=args.duration_seconds,
        min_duration_seconds=args.min_duration_seconds,
        scratch_root=scratch_parent,
        ffmpeg=_resolve_ffmpeg(),
        ffprobe=_resolve_ffprobe(),
        tsp=_resolve_tsp(),
        max_wait_seconds=args.max_wait_seconds,
        max_segments=args.max_segments,
        keep_scratch=args.keep_scratch,
        release_grade=not args.diagnostic,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["verdict"] == Verdict.PASS:
        return 0
    return 2 if report["verdict"] == Verdict.UNVERIFIED else 1


if __name__ == "__main__":
    raise SystemExit(main())
