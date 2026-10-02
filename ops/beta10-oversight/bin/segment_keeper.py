# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U50 caption segment keeper: hold enough FINISHED segments for a real 60 s window.

The live-HLS directory the relay writes keeps only ~7 segments (about 14 s at
2 s each) -- the relay deletes each segment as it rotates it out *within* a run,
but the 7 that were still in the playlist when it stopped are left behind
forever.  So the directory holds a handful of live segments and a growing pile
of fossils from earlier runs, and the verifier's `caption_window()` -- 60 s
ordered, newest two excluded -- sees 7 fresh candidates and yields a
`span_seconds` of 10.0.  The 60 s caption window exists on paper only.

This is a measurement tool, not part of the product.  It copies finished
segments into a keep directory so the window can be filled from copies:

  * **plain copies only.**  One read-only `os.open` per attempt, closed before
    anything else happens, never a handle held across a retry -- on Windows an
    open handle blocks the relay's atomic playlist replace.  Nothing here ever
    opens `playlist.m3u8`; the directory listing is the only thing read.
  * **the segment is identified by mtime, never by sequence number.**  Fossils
    carry HIGHER sequence numbers than the live segments (U50 premise
    correction), so `seg<digits>.ts` order says nothing about which run a file
    belongs to.  A segment is this run's if it was written within
    `--fresh-seconds`.
  * **the newest two are not copied.**  The tail of the directory is the live
    edge and a copy of one would be torn.
  * **the copy carries the source's mtime** (`os.utime`): the verifier orders
    its window by the copy's own mtime, so a copy that landed with "now" would
    read as the newest segment and be excluded.
  * **writes are atomic** (`.part` + `os.replace`) so a verifier reading the
    keep directory never sees a half-written segment.
  * **a heartbeat each loop** (`heartbeat.json` under the keep root) so the
    verifier can tell a live keeper from an abandoned directory, and so a loop
    that failed says so instead of looking like a quiet one.

Run it for a bounded window:

    python segment_keeper.py --hls <live-hls root> --out %TEMP%\\cc-caption-keep \\
        --until 2026-09-26T21:37:00
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

#: The channels the relay writes.  Matches rung_check.py's CHANNELS and the
#: verifier's; a channel added there and not here would silently keep nothing.
CHANNELS = ("public", "government", "education")

#: Loop cadence.  4 s against 2 s segments means every segment is seen at least
#: once before it ages out of the keep window.
KEEP_INTERVAL_SECONDS = 4.0
#: How old a source segment may be and still count as this run's.  The relay
#: writes one every 2 s, so 120 s of slack tolerates a stalled loop without ever
#: reaching a fossil (the youngest fossil observed was hours old).
KEEP_FRESH_SECONDS = 120.0
#: How long a copy is held.  Must exceed the verifier's 60 s window plus the
#: two excluded newest and the 4 s cadence: 180 s holds ~90 s of segments.
KEEP_SECONDS = 180.0
#: The live edge.  Two segments, not one: the relay may have renamed a segment
#: into place but not yet finished flushing it.
KEEP_EXCLUDE_NEWEST = 2
HEARTBEAT_NAME = "heartbeat.json"
PART_SUFFIX = ".part"
#: A finished segment, and nothing else: not the playlist, not a `.tmp`, not a
#: dotfile.  Deliberately not `seg*.ts`, which would take `seg0001.ts.tmp`.
SEGMENT_NAME = re.compile(r"^seg\d+\.ts$")

#: Mirrors the verifier's U48 race discipline.  The relay replaces segments
#: atomically, so a reader can lose a race with it; the retry budget is the
#: verifier's, so the two tools agree on what "could not read" means.
RACE_ERRORS = (PermissionError, FileNotFoundError)
RACE_ATTEMPTS = 20
RACE_DELAY_SECONDS = 0.1

#: The `--until` forms accepted: an epoch second, or a local ISO-8601 time.
UNTIL_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


class SegmentRead(NamedTuple):
    """One stable read of a finished segment: its bytes and the mtime it had."""

    data: bytes
    mtime_ns: int


def _unlink(path: Path) -> bool:
    """Remove `path`, reporting whether it went away.  Never raises."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def _read_live_segment(src: Path) -> SegmentRead | None:
    """Read one finished segment, or None if it changed while being read.

    The U48 discipline, restated for a copier: one read-only `os.open` per
    call, `fstat` before and after the read, and the handle closed before this
    function returns -- no handle is ever held across a retry.  Only the source
    is read; nothing here opens the playlist or writes beside it.

    None means the file changed under the read (the relay was still touching
    it); the caller treats that as a miss rather than copying a torn segment.
    FileNotFoundError and PermissionError propagate: the caller's retry loop
    owns the budget for those.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(src, flags)
    try:
        before = os.fstat(fd)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None
    data = b"".join(chunks)
    if len(data) != after.st_size:
        return None
    return SegmentRead(data=data, mtime_ns=after.st_mtime_ns)


def finished_segments(
    channel_dir: Path,
    *,
    now: float,
    fresh_seconds: float = KEEP_FRESH_SECONDS,
    exclude_newest: int = KEEP_EXCLUDE_NEWEST,
) -> list[Path]:
    """The segments a reader may safely copy, newest first.

    Three filters, and each one is load-bearing:

    * the name must be a finished segment -- `playlist.m3u8`, its `.tmp`
      siblings and any dotfile are not segments;
    * the newest `exclude_newest` are still at the live edge, and a copy of one
      would be torn;
    * anything older than `fresh_seconds` belongs to an earlier run.  This is
      the filter that has to be mtime-based: the fossils left by a previous run
      carry *higher* sequence numbers than the live segments, so ordering by
      name would rank exactly the wrong files as new.

    A directory that is not there yet (the relay creates it on start) reads as
    "nothing to keep", never as an error.
    """
    try:
        entries = [
            item
            for item in channel_dir.iterdir()
            if item.is_file() and SEGMENT_NAME.match(item.name)
        ]
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return []
    stamped: list[tuple[float, str, Path]] = []
    for item in entries:
        try:
            mtime = item.stat().st_mtime
        except OSError:
            continue
        stamped.append((mtime, item.name, item))
    # Newest first, name as the tiebreak so two segments written in the same
    # clock tick still order deterministically.
    stamped.sort(key=lambda row: (row[0], row[1]), reverse=True)
    chosen = []
    for mtime, _name, item in stamped[exclude_newest:]:
        if now - mtime > fresh_seconds:
            continue
        chosen.append(item)
    return chosen


def _prune(dest_dir: Path, *, now: float, keep_seconds: float, entry: dict) -> None:
    """Drop copies (and abandoned `.part` files) older than the keep window."""
    try:
        items = sorted(dest_dir.iterdir())
    except OSError:
        return
    for item in items:
        name = item.name
        if not (SEGMENT_NAME.match(name) or name.endswith(PART_SUFFIX)):
            continue
        try:
            if not item.is_file():
                continue
            age = now - item.stat().st_mtime
        except OSError:
            continue
        if age <= keep_seconds:
            continue
        if _unlink(item):
            entry["pruned"].append(name)


def _copy_segment(
    src: Path,
    dest: Path,
    *,
    attempts: int = RACE_ATTEMPTS,
    delay: float = RACE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Copy one finished segment into place atomically.

    Returns None on success, or a one-line reason it did not happen.  The
    failure is returned rather than raised because a segment that could not be
    read is a gap in the keep window, not a reason to stop keeping the others.
    """
    part = dest.with_name(dest.name + PART_SUFFIX)
    for attempt in range(attempts):
        try:
            read = _read_live_segment(src)
        except RACE_ERRORS as exc:
            if attempt + 1 < attempts:
                sleep(delay)
                continue
            return f"{type(exc).__name__}: {exc}"
        if read is None:
            if attempt + 1 < attempts:
                sleep(delay)
                continue
            return "the segment changed while it was being read"
        try:
            with part.open("wb") as handle:
                handle.write(read.data)
            # The verifier positions the window by the copy's own mtime, so the
            # copy must carry the source's, to the nanosecond: a copy stamped
            # "now" would read as the newest segment in the directory.
            os.utime(part, ns=(read.mtime_ns, read.mtime_ns))
            part.replace(dest)
        except OSError as exc:
            _unlink(part)
            return f"{type(exc).__name__}: {exc}"
        return None
    return "the retry budget ran out"


def keep_once(
    hls_root: Path,
    out_root: Path,
    *,
    now: float | None = None,
    channels: Sequence[str] = CHANNELS,
    fresh_seconds: float = KEEP_FRESH_SECONDS,
    keep_seconds: float = KEEP_SECONDS,
    exclude_newest: int = KEEP_EXCLUDE_NEWEST,
    attempts: int = RACE_ATTEMPTS,
    delay: float = RACE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """One keeping pass over every channel.  Returns the per-channel report."""
    moment = time.time() if now is None else now
    hls_root, out_root = Path(hls_root), Path(out_root)
    report: dict = {"now": moment, "channels": {}}
    for channel in channels:
        dest_dir = out_root / channel
        entry: dict = {"copied": [], "already": [], "pruned": [], "errors": []}
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            entry["errors"].append(f"could not create the keep dir: {type(exc).__name__}: {exc}")
            report["channels"][channel] = entry
            continue
        _prune(dest_dir, now=moment, keep_seconds=keep_seconds, entry=entry)
        for src in finished_segments(
            hls_root / channel,
            now=moment,
            fresh_seconds=fresh_seconds,
            exclude_newest=exclude_newest,
        ):
            dest = dest_dir / src.name
            if dest.exists():
                entry["already"].append(src.name)
                continue
            reason = _copy_segment(src, dest, attempts=attempts, delay=delay, sleep=sleep)
            if reason is None:
                entry["copied"].append(src.name)
            else:
                entry["errors"].append(f"{src.name}: {reason}")
        report["channels"][channel] = entry
    return report


def write_heartbeat(
    out_root: Path,
    *,
    now: float,
    loops: int,
    report: dict | None = None,
    error: str | None = None,
) -> Path:
    """Write the keep directory's liveness stamp, atomically.

    The verifier refuses to trust the keep directory unless this file is fresh;
    a keeper that died silently must therefore stop refreshing it, which is why
    it is written on every loop including a failed one.  Counts, not name lists:
    the file is read by a tool deciding whether the directory is alive, and the
    names are already on disk for anything that needs them.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    channels: dict = {}
    errors: list[str] = []
    for name, entry in ((report or {}).get("channels") or {}).items():
        failures = [str(item) for item in (entry.get("errors") or [])]
        channels[name] = {
            "copied": len(entry.get("copied") or []),
            "already": len(entry.get("already") or []),
            "pruned": len(entry.get("pruned") or []),
            "errors": failures,
        }
        errors.extend(f"{name}: {item}" for item in failures)
    if error:
        errors.insert(0, error)
    body: dict = {
        "updated_epoch": now,
        "loops": loops,
        "pid": os.getpid(),
        "channels": channels,
    }
    if errors:
        body["errors"] = errors
    path = out_root / HEARTBEAT_NAME
    part = path.with_name(path.name + PART_SUFFIX)
    part.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.utime(part, ns=(int(now * 1e9), int(now * 1e9)))
    part.replace(path)
    return path


def parse_until(text: str) -> float:
    """Read `--until` as an epoch second or a local ISO-8601 time.

    Local, because both callers think in the station's clock: rung.ps1 computes
    its bound from a local `DateTime`, and a coordinator reading the rung folder
    reads local times too.
    """
    stripped = str(text).strip()
    try:
        return float(stripped)
    except ValueError:
        pass
    for fmt in UNTIL_FORMATS:
        try:
            return datetime.datetime.strptime(stripped, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(
        f"cannot read {text!r} as an epoch second or a local ISO-8601 time "
        f"(one of {', '.join(UNTIL_FORMATS)})"
    )


def _summary(channel: str, entry: dict) -> str:
    return (
        f"{channel}: +{len(entry['copied'])} held={len(entry['already'])} "
        f"-{len(entry['pruned'])} err={len(entry['errors'])}"
    )


def run(
    hls_root: Path,
    out_root: Path,
    *,
    until: float,
    interval: float = KEEP_INTERVAL_SECONDS,
    channels: Sequence[str] = CHANNELS,
    fresh_seconds: float = KEEP_FRESH_SECONDS,
    keep_seconds: float = KEEP_SECONDS,
    exclude_newest: int = KEEP_EXCLUDE_NEWEST,
    attempts: int = RACE_ATTEMPTS,
    delay: float = RACE_DELAY_SECONDS,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> int:
    """Keep until `until`, one pass per interval.  Returns the number of passes.

    A pass that raises is caught and recorded in the heartbeat rather than
    ending the run: a channel directory that vanishes mid-pass (the relay
    restarting) must not cost the other channels their window.  `clock` and
    `sleep` are injectable so the loop can be tested without waiting.
    """
    start = clock()
    if start >= until:
        write_heartbeat(out_root, now=start, loops=0)
        log(f"segment_keeper: --until {until:.0f} is already past; nothing to keep")
        return 0
    log(
        f"segment_keeper: keeping every {interval:g}s until {until:.0f} "
        f"({(until - start) / 60.0:.1f} min), channels {', '.join(channels)}"
    )
    loops = 0
    while clock() < until:
        moment = clock()
        report = None
        error = None
        try:
            report = keep_once(
                hls_root,
                out_root,
                now=moment,
                channels=channels,
                fresh_seconds=fresh_seconds,
                keep_seconds=keep_seconds,
                exclude_newest=exclude_newest,
                attempts=attempts,
                delay=delay,
                sleep=sleep,
            )
        except Exception as exc:  # a broken pass must not end the keeping
            error = f"{type(exc).__name__}: {exc}"
            log(f"segment_keeper: pass {loops + 1} failed: {error}")
        loops += 1
        write_heartbeat(out_root, now=moment, loops=loops, report=report, error=error)
        if report is not None:
            log("  " + "  ".join(_summary(name, item) for name, item in report["channels"].items()))
        sleep(interval)
    # No closing heartbeat: the last pass's own stamp is the truth, and a write
    # here would refresh the mtime and drop the errors that pass recorded.
    log(f"segment_keeper: {until:.0f} reached after {loops} passes")
    return loops


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Keep finished HLS segments for the caption window"
    )
    parser.add_argument(
        "--hls", required=True, type=Path, help="live-HLS root holding <channel>/ dirs"
    )
    parser.add_argument("--out", required=True, type=Path, help="keep root; one subdir per channel")
    parser.add_argument(
        "--until", required=True, help="stop at this epoch second or local ISO-8601 time"
    )
    parser.add_argument("--interval", type=float, default=KEEP_INTERVAL_SECONDS)
    parser.add_argument("--fresh-seconds", type=float, default=KEEP_FRESH_SECONDS)
    parser.add_argument("--keep-seconds", type=float, default=KEEP_SECONDS)
    parser.add_argument("--channels", default=",".join(CHANNELS))
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        until = parse_until(args.until)
    except ValueError as exc:
        print(f"segment_keeper: {exc}", file=sys.stderr)
        return 2
    channels = tuple(name.strip() for name in args.channels.split(",") if name.strip())
    run(
        args.hls,
        args.out,
        until=until,
        interval=args.interval,
        channels=channels,
        fresh_seconds=args.fresh_seconds,
        keep_seconds=args.keep_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
