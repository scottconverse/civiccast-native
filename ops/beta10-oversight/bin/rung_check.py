"""rung_check.py <verify|loudness> <evidence.json> -> prints 'OK' / 'PASS ...' or 'BAD ...' (read-only).

loudness mode re-scores a FAIL channel window with loudness_window_adjudicate.py
before it rules: the owner's decision (2026-09-26) is that a window is NOT a
failure when the station is already at its maximum lift on source it may not
legally correct -- and, since U45 answer 2, only when a QUARTER of the window
could not be reached even at that ceiling.  Such a window is printed as
EXCLUDED_QUIET_SOURCE with its asset, position, levels and the UNREACHABLE
count the verdict turned on -- it keeps the run's PASS, and it stays in the log
with its numbers so the exclusion is visible, never silent.  The count is read at
the measured position (U45 answer 3) and printed with the range the +/-30 s sweep
of that count covers; a range that straddles the need is marked BORDERLINE, which
means the coordinator reads that window by hand -- BORDERLINE never changes the
verdict here, it only says the margin is thin.

A channel whose capture holds NO loudness measurement is a different thing
altogether: the instrument failed, not the station.  Since U48 such a channel is
printed as INSTRUMENT_ERROR with the capture's own reason (a playlist read that
raced the relay's atomic replace, a window that could not be scored) instead of a
loudness FAIL the station never earned -- there is no measurement to be a verdict
about.  The run still fails: no evidence is not a pass, and this word changes
what the line claims, never whether the rung passes.

Verify mode carries the same second-opinion rule into the caption gate (U48
follow-on).  A caption decode-back FAIL used to fail the rung outright, and the
window it failed on was ~8 s: on 2026-09-26 verify #4 government's sidecar was
reading "take a five-minute break" -- a recess -- while both it and education had
injected 14-17 captions in the preceding minute.  A speech pause is not a caption
outage.  A caption FAIL (or UNVERIFIED) therefore stands as a rung failure only
on the two signs of a REAL outage: the channel's own worker reported
`CTRL caption <ch>: received=0` for the window (the verify records that receipt
per channel), or two consecutive verifies decoded 0 cues for that channel.
Anything else is printed as CAPTION_QUIET(<why>) beside the OK -- listed with its
numbers, never failed, because a quiet channel is not a broken one.  The
softening reaches only those two statuses: a missing caption block, a NOT_PROVEN
status (no decoder path at all) and every other gate keep the old hard rule.  No
evidence is not a pass.

Anything the adjudicator cannot resolve is NOT a pass: a missing adjudication
file, an error, or an UNRESOLVED window all leave the channel as BAD.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

REQUIRED_VERIFY = ("caption_decode_back", "timestamp_continuity", "freshness")
CHANNELS = ("public", "government", "education")

EXCUSED = "EXCLUDED_QUIET_SOURCE"
INSTRUMENT_ERROR = "INSTRUMENT_ERROR"

#: The caption gate, and the two verify statuses a quiet channel explains.  A
#: verified PASS is never touched, and NOT_PROVEN is deliberately not here: it
#: means the verify had no proven decoder path, which no worker receipt speaks
#: to and no amount of waiting cures.
CAPTION_KEY = "caption_decode_back"
CAPTION_QUIET = "CAPTION_QUIET"
CAPTION_SOFTENED = ("FAIL", "UNVERIFIED")
#: The verify files are written as verify-01.json, verify-02.json ... into one
#: run folder, so "consecutive" is the previous NUMBER in this folder -- not the
#: previous file mtime, which an ad-hoc re-run can reorder or overwrite.
VERIFY_NAME = re.compile(r"^verify-(\d+)\.json$")
ADJUDICATOR = Path(__file__).with_name("loudness_window_adjudicate.py")

#: U55: the third caption word.  A window that decoded 0 cues while the ASR's
#: own output shows it emitted none across that window is a quiet SOURCE, not a
#: broken station -- printed with the gap's numbers beside the OK, never as a
#: pass (the rung fails on no evidence, and there is no station fault to fail).
NO_SPEECH_SOURCE = "NO_SPEECH_SOURCE"
#: A worker receipt no older than this still speaks for the window.  The worker
#: prints its `CTRL caption <ch>` line once per 60 s window and prints NOTHING
#: when no cue arrives, so a silent source makes the receipt age grow without
#: bound.  The 2026-09-26 run filed both ends of this: verify-06's receipt was
#: 20.974 s old over live speech, verify-07's was 178.934 s old over the gap.
RECEIPT_FRESH_SECONDS = 150.0
#: How far the ASR's cue-free gap must extend past each end of the caption
#: window before it can explain it.  The anchor is derived from the newest tap
#: chunk's mtime; measured over 446 chunks / 37 minutes on 2026-09-26 the same
#: session's anchor held to 0.10 s, so this is ~300x the observed drift and it
#: also absorbs the tap's own write lag.
ANCHOR_SLACK_SECONDS = 30.0
#: The tap root is EMPTY between segments: the worker moves a consumed chunk on
#: to `<channel>/processed/` and the next one is published up to a full segment
#: later, so a single glob can legitimately find no `chunk-*.wav` at all.
#: OBSERVED on the live `public` tap 2026-09-26 22:54-22:55, sampled every 0.25 s
#: for 240 samples: 59 samples (24.6%) had no chunk at all, in empty runs of 5, 6,
#: 7, 8, 9, 12 and 12 samples -- a 3.00 s worst case.  Separately, a chunk the
#: glob DID list was moved away before the tool could stat it (FileNotFoundError
#: at 22:53).  Neither is evidence that the tap is gone -- that is the fail-closed
#: answer only when the dir is still empty a whole segment cycle later.  Against
#: the real verify-07 the single-shot lookup this replaced failed closed 5 times
#: in 10; the retry passed 20 of 20.
ANCHOR_POLL_SECONDS = 0.25
ANCHOR_POLL_TRIES = 24  # 6.0 s: 2x the worst observed empty window
#: `chunk-%06d.wav` under the tap root -- tap.py:21 TAP_SEGMENT_PATTERN.
TAP_CHUNK_RE = re.compile(r"^chunk-(\d+)\.wav$")
#: The station's egress root, used only when the evidence carries no receipt log
#: path to derive it from (the receipt's log lives at
#: <egress>\<channel>\logs\gst-worker.stdout.log).
DEFAULT_EGRESS_ROOT = Path(r"C:\ProgramData\CivicCast\data\egress")
#: A VTT cue timestamp.  `format_webvtt_timestamp` allows 2+ hour digits (this
#: channel's live file reaches `126:43:13.850`), so the hour field is `\d{2,}`.
VTT_CUE_RE = re.compile(
    r"^(\d{2,}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})\.(\d{3})"
)


def adjudicate(path, air_audio=None):
    """Run the adjudicator beside this script; return its report, or None.

    The report lands in the adjudicator's own cache directory rather than beside
    the rung's evidence: this script may only be handed an evidence path, and a
    rung evidence folder is the coordinator's, not ours.  The numbers the run is
    judged on are in the printed line below, which the rung writes to its log.

    `air_audio` maps a channel to the concatenated capture for its window (see
    `channel_air_audio`); each entry becomes the adjudicator's own `--air-audio
    CH=PATH`, which is what arms the correlation (T1).  Without it the
    adjudicator can only fall back on the log's position -- which is how the C15
    incident (U66) produced a ruling at 3226.3 s for a window that was really at
    7121 s.
    """
    if not ADJUDICATOR.is_file():
        return None
    out_dir = Path(tempfile.gettempdir()) / "cc-loud-adj"
    out = out_dir / (Path(path).stem + ".adjudicated.json")
    argv = [sys.executable, str(ADJUDICATOR), path, "--out", str(out), "--quiet"]
    for ch, air in sorted((air_audio or {}).items()):
        if air:
            argv += ["--air-audio", f"{ch}={air}"]
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Current Python + sibling adjudicator; operator evidence paths are argv, never shell code.
        subprocess.run(argv, capture_output=True, text=True, timeout=1800)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: U66 item 1.  Where the concatenated capture for a window is kept.  The rung
#: calls this every ~30 minutes against the SAME evidence, so the file is reused
#: while its snapshot set is unchanged, and the sibling from the previous window
#: is dropped -- a stale concat is not evidence for this window.  Overridable so
#: a test can concatenate into a tree of its own instead of the live one.
AIR_SCRATCH_DIR = Path(
    os.environ.get("CIVICAST_AIR_AUDIO_DIR")
    or (Path(tempfile.gettempdir()) / "cc-loud-adj-scratch" / "air")
)


def channel_air_audio(channel, chan, scratch_dir=None):
    """Concatenate a channel's captured snapshot segments into one audio file.

    Returns the path, or None when there is nothing to concatenate: the evidence
    names no segments, or every snapshot has already been swept out of the
    capture's scratch tree (the rung's own evidence folder keeps the record, not
    the media -- `loudness-09.json` still names all 121 of education's segments
    and not one of them is on disk any more).

    The segments ARE the window: `snapshot_path` names consecutive MPEG-TS chunks
    of one contiguous capture, in `sequence` order, so joining them byte for byte
    reproduces the audio the capture measured.  Nothing here decodes or
    re-encodes -- a container-level concatenation of TS chunks is one stream to
    the decoder, and re-encoding would put this script in the signal path.

    The key is the ordered segment digests, not the paths: the same window
    re-captured into a fresh scratch directory is the same audio and reuses the
    same concat.
    """
    segs = [s for s in ((chan or {}).get("segments") or []) if isinstance(s, dict)]
    segs.sort(key=lambda s: s.get("sequence") if isinstance(s.get("sequence"), int) else 0)
    paths, ids = [], []
    for seg in segs:
        raw = seg.get("snapshot_path")
        if not raw:
            continue
        p = Path(raw)
        try:
            if not p.is_file() or p.stat().st_size <= 0:
                continue
        except OSError:
            continue
        paths.append(p)
        ids.append(str(seg.get("sha256") or seg.get("name") or raw))
    if not paths:
        return None
    root = Path(scratch_dir) if scratch_dir is not None else AIR_SCRATCH_DIR
    key = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16]
    want = root / f"{channel}-{key}.aac.ts"
    try:
        total = sum(p.stat().st_size for p in paths)
        if want.is_file() and want.stat().st_size == total:
            return want
        root.mkdir(parents=True, exist_ok=True)
        part = want.with_name(want.name + f".{os.getpid()}.part")
        with part.open("wb") as fh:
            for p in paths:
                with p.open("rb") as src:
                    shutil.copyfileobj(src, fh, 1 << 20)
        part.replace(want)
        for old in root.glob(f"{channel}-*.aac.ts"):
            if old != want:
                with suppress(OSError):
                    old.unlink()
        return want
    except OSError:
        return None


#: The capture script's own floor (`SILENCE_FLOOR_LUFS`): at or below this the
#: window is indistinguishable from silence, and a silent window is a station
#: fault, never a quiet source.  Hard-coded rather than imported so this check
#: cannot be silently loosened by a change in the capture script.
SILENCE_FLOOR_LUFS = -60.0


def instrument_reason(chan):
    """Why this channel carries no loudness measurement, or "" if it carries one.

    The capture script sets a channel's status straight from its `audio_window`,
    but not every non-PASS status is a loudness verdict: a channel can also fail
    before any window is scored -- the playlist read raced the relay's atomic
    replace, the capture stopped short, an ffmpeg died.  Nothing about the
    station's loudness follows from such a channel, so it is an INSTRUMENT_ERROR,
    not a FAIL the station earned ("blocking_reasons or no integrated_lufs",
    U48).  The reason printed is the capture's own words, most specific first:
    the channel's `blocking_reasons`, then the window's `detail` (a short capture
    and a continuity break say which they are), then a plain statement that no
    measurement exists.  `loudness_window_adjudicate.py` keeps the same predicate
    and the same reason, duplicated like the count token below, so the two
    revisions tell one story.
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


def excusable(channel, chan, adj, top_blocking):
    """May this channel's FAIL be attributed to a quietly-sourced window?

    Only a *measured* window that missed target may be excused, and only when
    the capture itself was structurally sound: the capture script sets a
    channel's status straight from its `audio_window` status, so a FAIL can also
    mean a short capture, an unmeasurable window, or a continuity break -- none
    of which any source measurement may paper over.
    """
    if top_blocking:
        return False, "the capture recorded blocking reasons"
    if chan.get("blocking_reasons"):
        return False, "the channel recorded blocking reasons"
    if (chan.get("continuity") or {}).get("status") != "PASS":
        return False, "timestamp continuity was not proven for the window"
    aw = chan.get("audio_window") or {}
    if aw.get("status") != "FAIL" or aw.get("within_target") is not False:
        return False, "the window did not fail on target loudness"
    integrated = aw.get("integrated_lufs")
    # Unreachable from the loudness branch below since U48 -- a channel with no
    # measurement is INSTRUMENT_ERROR before it ever gets here.  Kept because
    # this predicate is the one place that says what an excusable window IS.
    if integrated is None:
        return False, "no integrated loudness was measured for the window"
    if integrated <= SILENCE_FLOOR_LUFS:
        return False, f"the window is at or below the silence floor ({SILENCE_FLOOR_LUFS:g} LUFS)"
    if not str(aw.get("detail") or "").startswith("window integrated "):
        return False, "the window carries no measured-window detail"
    got = ((adj or {}).get("channels") or {}).get(channel) or {}
    if got.get("classification") != EXCUSED:
        return False, "the adjudicator did not exclude this window"
    return True, ""


def unreach_token(got):
    """The count token, in the shape the adjudicator's own line prints it.

    `?` if the adjudication predates the count criterion or was not swept: an
    exclusion whose count cannot be shown is still an exclusion, but the log must
    not imply a number it never measured.
    """
    n = got.get("unreachable_seconds")
    scorable = (got.get("source") or {}).get("scorable_seconds")
    rng = got.get("unreachable_range_s")
    need = got.get("min_unreachable_seconds")
    window = got.get("window_seconds")
    if n is None or scorable is None:
        return "unreach=?"
    rng_s = "range ?" if not rng else f"range {rng[0]:g}-{rng[1]:g}"
    need_s = "?" if need is None else f"{need:g}"
    tok = f"unreach={n:g}/{scorable:g}s ({rng_s}, need {need_s})"
    if window is not None:
        tok += f" window={window:g}s"
    if got.get("borderline"):
        tok += " BORDERLINE"
    return tok


def excused(channel, adj):
    got = ((adj or {}).get("channels") or {}).get(channel) or {}
    asset = (got.get("asset") or {}).get("display_name") or "?"
    pos = (got.get("position") or {}).get("position_s")
    src = (got.get("source") or {}).get("lift_limited_lufs")
    span = (got.get("source") or {}).get("span_lufs")
    reach = got.get("max_reachable_lufs")
    air = (got.get("air") or {}).get("integrated_lufs")
    return (
        f'{EXCUSED}[asset="{asset}" pos={pos}s src45min={src}LUFS srcspan={span}LUFS '
        f"maxreach={reach}LUFS air={air}LUFS {unreach_token(got)}]"
    )


def label(channel, chan, adj):
    """The per-channel word in the printed line: its status, or why it stands."""
    status = (chan or {}).get("status")
    if status == "PASS":
        return "PASS"
    got = ((adj or {}).get("channels") or {}).get(channel) or {}
    kind, detail = got.get("classification"), got.get("detail")
    if kind and kind != "NOT_APPLICABLE":
        word = status if kind == status else f"{status}/{kind}"
        # A FAIL whose sweep range straddles the need is still a FAIL, but it is
        # the window the coordinator reads by hand, so the flag travels with it.
        note = unreach_token(got) if got.get("borderline") else ""
        bits = "; ".join(b for b in (detail, note) if b)
        return f"{word}({bits})" if bits else word
    return (
        f"{status}(no adjudication)" if adj is not None else f"{status}(adjudicator gave no answer)"
    )


def caption_cues(chan):
    """The cue count the verify recorded for this channel, or None if it recorded none.

    None and 0 are different claims: 0 is "a clean span carried no cue", which is
    the outage signal; None is "this evidence predates the count" (or the block is
    absent), which proves nothing about an outage and must never be read as 0.
    """
    n = ((chan or {}).get(CAPTION_KEY) or {}).get("cue_count")
    return n if isinstance(n, int) else None


def previous_verify(path):
    """The verify evidence filed immediately before `path`, or None.

    Read from the same folder, by number: the next-lower verify-NN.json.  A file
    that does not follow the rung's own naming -- an ad-hoc verify written beside
    the rung's -- has no predecessor here, and its caption FAIL is then judged on
    the receipt alone.
    """
    current = VERIFY_NAME.match(Path(path).name)
    if current is None:
        return None
    best_n, best_p = 0, None
    try:
        siblings = list(Path(path).parent.glob("verify-*.json"))
    except OSError:
        return None
    for cand in siblings:
        got = VERIFY_NAME.match(cand.name)
        if got is None:
            continue
        n = int(got.group(1))
        if 0 < n < int(current.group(1)) and n > best_n:
            best_n, best_p = n, cand
    return best_p


def caption_outage(path, channel, v):
    """Is this channel's caption status a REAL outage, or a quiet channel?

    (U48 follow-on.)  Two signs only, both the station's own: the channel's
    worker reported received=0 for the window (the verify's `caption_receipt`,
    status ZERO -- from an explicit zero receipt or from the worker's own
    ten-silent-window WARNING), or the previous verify decoded 0 cues for this
    channel as well.  Returns (is_outage, why); an empty `why` means quiet.
    """
    receipt = (v or {}).get("caption_receipt") or {}
    if receipt.get("status") == "ZERO":
        return True, str(receipt.get("detail") or "the worker reported received=0 for the window")
    # Coordinator tightening (13:40): quiet is excused only on POSITIVE evidence -- a fresh worker
    # receipt (status OK, received>0) AND a span that actually decoded to a cue count. Absent or
    # stale receipt, or a decode with no cue count, is a caption FAIL: missing evidence is not a pass.
    if receipt.get("status") != "OK":
        return (
            True,
            f"no positive worker receipt ({receipt.get('detail') or receipt.get('status') or 'absent'})",
        )
    if caption_cues(v) is None:
        return True, "the span did not decode to a cue count"
    prev = previous_verify(path)
    if prev is None:
        return False, ""
    try:
        earlier = json.loads(prev.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, ""
    if earlier is None:
        return False, ""
    other = ((earlier or {}).get("channels") or {}).get(channel) or {}
    if CAPTION_KEY in other and caption_cues(other) == 0:
        return True, f"this channel decoded 0 cues in {prev.name} as well"
    return False, ""


def utc_seconds(value):
    """An ISO-8601 stamp from a verify as epoch seconds, or None.

    The verify writes `...+00:00`; a stamp with no zone is read as UTC rather
    than as this box's local time, which would silently shift the window.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        got = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if got.tzinfo is None:
        got = got.replace(tzinfo=UTC)
    return got.timestamp()


def caption_window_counters(v, anchor):
    """The caption window as tap-chunk counters, or None.

    The window is recorded as the emitted segments' UTC stamps; the tap chunk
    counter is what the VTT's cue times count, so the two need this anchor.
    A degenerate window (one segment, first == last) is widened by the span the
    verify itself recorded, so a 2 s window stays a 2 s window here.
    """
    win = (v or {}).get("caption_window") or {}
    lo = utc_seconds(win.get("emitted_first_utc"))
    hi = utc_seconds(win.get("emitted_last_utc"))
    if lo is None or hi is None:
        return None
    span = win.get("span_seconds")
    if not isinstance(span, (int, float)) or span <= 0:
        span = 0.0
    if hi < lo + span:
        hi = lo + span
    return lo - anchor, hi - anchor


def newest_chunk(tap_dir):
    """(index, path) of a channel tap dir's newest `chunk-*.wav`, or None."""
    newest = None
    try:
        entries = list(tap_dir.glob("chunk-*.wav"))
    except OSError:
        return None
    for path in entries:
        got = TAP_CHUNK_RE.match(path.name)
        if got is None:
            continue
        index = int(got.group(1))
        if newest is None or index > newest[0]:
            newest = (index, path)
    return newest


def chunk_anchor(index, path):
    """The epoch tap counter 0 maps to, from ONE chunk, or None.

    A chunk is published when the segment BEFORE it is complete, so this file's
    mtime is the end of counter `(index + 1) * duration`.  The duration comes
    from the WAV header, not from CIVICAST_CAPTION_TAP_SEGMENT_SECONDS, so the
    mapping carries the file that is actually on disk.  A read that races the
    worker's move to `processed/` raises rather than guesses.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            duration = handle.getnframes() / handle.getframerate()
        stamp = path.stat().st_mtime
    except (OSError, wave.Error, EOFError, ZeroDivisionError):
        return None
    if duration <= 0:
        return None
    return stamp - (index + 1) * duration


def asr_anchor(tap_dir):
    """The epoch tap counter 0 maps to, from the NEWEST chunk, or None.

    A VTT cue time is a tap-chunk COUNTER, not media time: the worker builds
    each chunk as `start = index * self._segment_seconds` (tap_worker.py:2379),
    with `index` read from the file name (`^chunk-(\\d+)\\.wav$`,
    tap_worker.py:102).  A chunk is written when the segment BEFORE it is
    complete, so the newest `chunk-N.wav`'s mtime is the end of counter
    (N+1) * duration, and `epoch(counter) = mtime - (N+1) * duration + counter`.

    Only the NEWEST chunk may be used: the counter restarts at 0 in a new
    session, so an older chunk's index belongs to a different epoch.  (Every
    chunk still in the live dir IS this session's -- `_discard_settled_segments`
    unlinks a channel's leftovers at session start, and `_settled_segments`
    documents that GStreamer publishes `.wav.partial -> .wav` atomically, so
    every visible WAV is complete, tap_worker.py:1841/2350.)

    The lookup is retried over ANCHOR_POLL_TRIES * ANCHOR_POLL_SECONDS, because
    the live dir is legitimately empty between segments and because a chunk the
    glob just saw can be moved away before it is opened.  Neither is evidence
    that the tap is gone -- only a tap that is still empty after a full segment
    cycle is, and then this returns None and the caption outage stays a FAIL.
    """
    for attempt in range(ANCHOR_POLL_TRIES):
        newest = newest_chunk(tap_dir)
        if newest is not None:
            anchor = chunk_anchor(*newest)
            if anchor is not None:
                return anchor
        if attempt + 1 < ANCHOR_POLL_TRIES:
            time.sleep(ANCHOR_POLL_SECONDS)
    return None


def caption_paths(v, channel):
    """(active.vtt, this channel's tap dir) for a verify's channel.

    The egress root comes from the receipt's own `log` path -- the evidence
    names where the worker writes, so the tool follows it rather than assume a
    station layout.  The tap root is `data\\caption-tap` beside it
    (`CIVICAST_CAPTION_TAP_DIR`, which is the ROOT: `tap_root / channel_id`,
    tap_worker.py:1852) unless the environment names one.
    """
    root = DEFAULT_EGRESS_ROOT
    log = ((v or {}).get("caption_receipt") or {}).get("log")
    if isinstance(log, str) and log:
        parents = Path(log).parents
        if len(parents) >= 3:
            root = parents[2]
    tap = os.environ.get("CIVICAST_CAPTION_TAP_DIR", "").strip()
    tap_dir = Path(tap) / channel if tap else root.parent / "caption-tap" / channel
    return root / channel / "captions" / "active.vtt", tap_dir


def vtt_cues(path):
    """The (start, end) counter pairs in a channel's active.vtt, or None.

    Read whole -- the file is ~90 KB and this runs every ~11 minutes.  The
    station replaces it atomically, so a reader can land between the replace
    and see a transient error; retry a couple of times rather than call a
    transient miss an absent file.
    """
    text = None
    for attempt in range(3):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            break
        except OSError:
            if attempt == 2:
                return None
            time.sleep(0.2)
    if text is None:
        return None
    cues = []
    for line in text.splitlines():
        got = VTT_CUE_RE.match(line.strip())
        if got is None:
            continue
        parts = [int(g) for g in got.groups()]
        start = parts[0] * 3600 + parts[1] * 60 + parts[2] + parts[3] / 1000.0
        end = parts[4] * 3600 + parts[5] * 60 + parts[6] + parts[7] / 1000.0
        cues.append((start, end))
    return cues


def clock_of(epoch):
    """A local wall clock HH:MM:SS for an epoch, for the log line."""
    try:
        return f"{datetime.fromtimestamp(epoch):%H:%M:%S}"
    except (OSError, OverflowError, ValueError):
        return "?"


def no_speech_source(path, channel, v):
    """U55: is this caption outage a SOURCE that carried no speech?  Detail or None.

    Returns None -- "not excused, keep the FAIL" -- unless the ASR's own output
    proves all three of these:

    * the window decoded 0 cues.  A window with NO cue count is a missing
      measurement, and a quiet source says nothing about it;
    * the worker receipt is not a fresh positive one.  A receipt within
      RECEIPT_FRESH_SECONDS says the worker injected captions for the window,
      so the silence is the station's problem, not the source's.  A ZERO
      receipt is the station's own received=0 outage sign and is never excused;
    * the ASR emitted no cue across the window AND its cue-free gap is BOUNDED
      on both sides and reaches ANCHOR_SLACK_SECONDS past each end.  Bounded is
      the point: no cue before the window means the ASR was never talking and
      no cue after it means it never resumed, and both of those are just as
      consistent with a dead ASR as with a quiet room -- which must stay a FAIL.

    The mapping the window is checked on is asr_anchor's: the window's emitted
    UTC stamps are shifted by the newest tap chunk's implied epoch, and the
    VTT's own cue times are compared on that same counter.
    """
    receipt = (v or {}).get("caption_receipt") or {}
    if receipt.get("status") == "ZERO":
        return None
    age = receipt.get("age_seconds")
    if (
        receipt.get("status") == "OK"
        and isinstance(age, (int, float))
        and age <= RECEIPT_FRESH_SECONDS
    ):
        return None
    if caption_cues(v) != 0:
        return None
    vtt_path, tap_dir = caption_paths(v, channel)
    anchor = asr_anchor(tap_dir)
    if anchor is None:
        return None
    window = caption_window_counters(v, anchor)
    if window is None:
        return None
    cues = vtt_cues(vtt_path)
    if not cues:
        return None
    lo, hi = window
    if any(start < hi and end > lo for start, end in cues):
        return None  # the ASR DID speak inside the window: a real caption FAIL
    before = [end for _start, end in cues if end <= lo]
    after = [start for start, _end in cues if start >= hi]
    if not before or not after:
        return None
    gap_start, gap_end = max(before), min(after)
    if gap_start > lo - ANCHOR_SLACK_SECONDS or gap_end < hi + ANCHOR_SLACK_SECONDS:
        return None
    return (
        f"asr gap {clock_of(anchor + gap_start)}-{clock_of(anchor + gap_end)}, "
        f"{gap_end - gap_start:.0f}s; the ASR emitted no cue across the "
        f"{hi - lo:.0f}s window"
    )


def quiet_detail(v):
    """The parenthetical for CAPTION_QUIET: what the span showed, and what the worker said."""
    blk = (v or {}).get(CAPTION_KEY) or {}
    receipt = (v or {}).get("caption_receipt") or {}
    span = blk.get("span_seconds")
    span_s = f"{span:g}s" if isinstance(span, (int, float)) else "?s"
    cues = blk.get("cue_count")
    cues_s = "no cue count" if cues is None else f"{cues} cue(s)"
    said = receipt.get("detail") or f"the worker receipt is {receipt.get('status') or 'absent'}"
    return f"{blk.get('status')} over {span_s}, {cues_s}; {said}"


mode, path = sys.argv[1], sys.argv[2]
try:
    with Path(path).open(encoding="utf-8") as f:
        d = json.load(f)
except Exception as exc:  # missing or unreadable evidence is a failure, never a pass
    print(f"BAD unreadable evidence {path}: {exc}")
    sys.exit(0)
chans = d.get("channels", {})
missing = [c for c in CHANNELS if c not in chans]
if mode == "verify":
    bad = [f"{c}:missing" for c in missing]
    quiet = []
    for c, v in chans.items():
        v = v or {}
        for k in REQUIRED_VERIFY:
            st = (v.get(k) or {}).get("status")
            if st == "PASS":
                continue
            if k == CAPTION_KEY and st in CAPTION_SOFTENED:
                # A caption FAIL is a rung failure only on the two signs of a
                # real outage (the worker's own received=0, or two consecutive
                # 0-cue verifies).  Otherwise it is listed, with its numbers, and
                # the rung keeps its PASS -- the channel is quiet, not broken.
                outage, why = caption_outage(path, c, v)
                if not outage:
                    quiet.append(f"{c}:{CAPTION_QUIET}({quiet_detail(v)})")
                    continue
                # U55: an outage the ASR's OWN output explains is a quiet
                # source, not a broken station -- listed with the gap's numbers
                # beside the OK, exactly as CAPTION_QUIET is.  This can only
                # soften the line, never the rule: the two outage signs above
                # are decided first, and no_speech_source refuses on anything
                # but a bounded ASR gap that spans the window.
                excuse = no_speech_source(path, c, v)
                if excuse is not None:
                    quiet.append(f"{c}:{NO_SPEECH_SOURCE}({excuse})")
                    continue
                bad.append(f"{c}:{k}={st}({why})")
                continue
            bad.append(f"{c}:{k}={st}")
    # The quiet items ride on the same line so the rung log carries them, but the
    # word in front is OK: rung.ps1 decides on the prefix (it must match '^OK',
    # not equal 'OK' -- a CAPTION_QUIET note is an OK line with company).
    line = "OK" if not bad else "BAD " + " ".join(bad)
    print(line + (" " + " ".join(quiet) if quiet else ""))
elif mode == "loudness":
    adj = None
    # A channel that carries no measurement is not adjudicable -- there is no
    # window for the source measurement to excuse -- so it does not pull the
    # adjudicator (and its ffmpeg passes) into a rung that has nothing to excuse.
    if any((v or {}).get("status") != "PASS" and not instrument_reason(v) for v in chans.values()):
        # U66 item 1: hand the adjudicator the window the capture actually heard.
        # The adjudicator's correlation needs aired audio and the rung has never
        # passed any, which is how a loudness FAIL came back ruled at a position
        # 3900 s from the truth (C15, 2026-09-29 07:18).  Snapshots are swept out
        # of the capture tree on their own schedule, so this is best-effort: where
        # they are gone, the adjudicator falls back to the log position and, for a
        # multi-part airing, refuses to rule on it at all (item 3).
        air = {}
        for c, v in chans.items():
            if (v or {}).get("status") == "PASS" or instrument_reason(v):
                continue
            got = channel_air_audio(c, v)
            if got is not None:
                air[c] = str(got)
        adj = adjudicate(path, air)
    labels, ok = [], not missing and not d.get("blocking_reasons")
    for c, v in chans.items():
        v = v or {}
        if v.get("status") == "PASS":
            labels.append(f"{c}=PASS")
            continue
        why_instrument = instrument_reason(v)
        if why_instrument:
            # The instrument failed.  The run still fails (no evidence is not a
            # pass), but the line may not say the station's loudness did.
            labels.append(f"{c}={INSTRUMENT_ERROR}({why_instrument})")
            ok = False
            continue
        allowed, why = excusable(c, v, adj, d.get("blocking_reasons"))
        kind = ((adj or {}).get("channels") or {}).get(c, {}).get("classification")
        if allowed:
            labels.append(f"{c}={excused(c, adj)}")
        elif kind == EXCUSED:  # the adjudicator excused it; the capture refused it
            labels.append(f"{c}={label(c, v, adj)} [exclusion not applied: {why}]")
            ok = False
        elif kind or adj is None:
            labels.append(f"{c}={label(c, v, adj)}")
            ok = False
        else:
            labels.append(f"{c}={label(c, v, adj)} [{why}]")
            ok = False
    print(
        ("PASS " if ok else "BAD ") + " ".join(labels) + (f" missing={missing}" if missing else "")
    )
else:
    print(f"BAD unknown mode {mode}")
