# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Source preparation for canonical egress playout assets.

#156 (long-asset TRANSITIONING stall): preparation used to re-conform the
same asset from scratch at every airing, synchronously, at airtime — a long
recording could hold the channel in TRANSITIONING for minutes at top-of-hour.
Preparation now keeps a **persistent conform cache** under
``work_dir/conform-cache``:

* the cacheable unit is the **full-asset conform** (keyed by source file
  fingerprint + canonical profile + loudness config). Trim/join-in-progress
  offsets are applied at *playout* instead — the emitted segment carries
  ``inpoint``/``outpoint`` and the encoder's ffconcat plan already honors them
  (:func:`civiccast.egress.runtime.write_concat_plan`);
* a cache **hit** costs zero ffmpeg work and zero loudness probing: a program
  whose asset has aired before starts within seconds (the #156 acceptance bar);
* a trimmed cache **miss** (typically a first-ever join-in-progress start)
  conforms only the remaining portion straight to air — identical latency to
  the old behavior — and *warm-behind* conforms the full asset into the cache
  on a background thread so the next airing hits. First-ever airing latency is
  therefore unchanged and documented in the runbook rather than hidden;
* the cache is bounded (``CIVICCAST_CONFORM_CACHE_GB``, default 20; ``<= 0``
  disables caching entirely) with oldest-first eviction, hits refreshing the
  entry's clock.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.runtime import FfmpegRunner
from civiccast.stream._ffmpeg import run_ffmpeg
from civiccast.stream.loudness import LoudnessGateResult, check_streaming_loudness

LoudnessChecker = Callable[..., LoudnessGateResult]
_LOG = logging.getLogger(__name__)
WarmScheduler = Callable[[Callable[[], None]], None]

_CACHE_DIR_NAME = "conform-cache"
_DEFAULT_CACHE_GB = 20.0
#: F3 fix (hostile-review follow-up, 2026-09-06): the age-only GC this replaced
#: had no size/count budget at all, so a channel doing frequent rollovers (the
#: exact scenario H5 was fixed for) could accumulate an unbounded number of
#: per-plan directories over a 6-hour window. GC is now keep-N-most-recent
#: FIRST (a directory this recent could plausibly still be the one a live
#: worker is reading, or one the daemon hasn't yet released -- see
#: ``release``), THEN a byte budget across whatever is left, and only falls
#: back to a bare age floor as an absolute last resort for anything neither
#: of those already caught. The floor is deliberately longer than H5's
#: original 6h now that keep-N is the primary defense.
_PREPARED_PLAN_DIR_KEEP_N = 3
_PREPARED_PLAN_DIR_BUDGET_GB = 5.0
_PREPARED_PLAN_DIR_MAX_AGE_S = 24.0 * 3600.0


def _prepared_plan_dir_budget_bytes() -> float:
    raw = os.environ.get("CIVICCAST_PREPARED_PLAN_DIR_BUDGET_GB", "").strip()
    try:
        gb = float(raw) if raw else _PREPARED_PLAN_DIR_BUDGET_GB
    except ValueError:
        gb = _PREPARED_PLAN_DIR_BUDGET_GB
    return gb * 1e9


def _dir_size_bytes(directory: Path) -> int:
    total = 0
    with contextlib.suppress(OSError):
        for entry in directory.rglob("*"):
            with contextlib.suppress(OSError):
                if entry.is_file():
                    total += entry.stat().st_size
    return total


def _default_warm_scheduler(job: Callable[[], None]) -> None:
    """Run a cache warm on a daemon thread (production default)."""
    threading.Thread(target=job, name="conform-cache-warm", daemon=True).start()


def _cache_budget_bytes() -> float:
    raw = os.environ.get("CIVICCAST_CONFORM_CACHE_GB", "").strip()
    try:
        gb = float(raw) if raw else _DEFAULT_CACHE_GB
    except ValueError:
        gb = _DEFAULT_CACHE_GB
    return gb * 1e9


@dataclass(frozen=True)
class PreparedSegmentRecord:
    """Trace of one source segment preparation decision."""

    label: str
    source_path: str
    prepared_path: str
    loudness_status: str
    measured_lufs: float | None
    normalized: bool


@dataclass(frozen=True)
class SourcePreparationReport:
    """Prepared source plan plus per-segment decisions for proof/debug output."""

    source_plan: EgressSourcePlan
    records: tuple[PreparedSegmentRecord, ...]
    #: F3 fix: this call's unique ``<channel>/prepared/<uuid>`` directory (see
    #: ``prepare``'s docstring), so a caller that independently knows a plan is
    #: retired (e.g. the daemon, once a content-reload reports its predecessor
    #: settled) can hand it straight back to ``SourcePreparer.release`` instead
    #: of waiting for GC. ``None`` for a caller/test double that never
    #: constructs a real per-plan directory (e.g. a live-only plan whose
    #: ``prepare()`` call wrote nothing at all -- see F7 -- or a fake
    #: preparer in a test).
    plan_dir: Path | None = None


class SourcePreparer:
    """Conform one source plan to the channel's canonical egress profile."""

    def __init__(
        self,
        *,
        work_dir: Path,
        ffmpeg_runner: FfmpegRunner = run_ffmpeg,
        loudness_checker: LoudnessChecker = check_streaming_loudness,
        warm_scheduler: WarmScheduler = _default_warm_scheduler,
        playout_trim_supported: bool = False,
    ) -> None:
        """``playout_trim_supported``: the consuming encoder honors per-segment
        ``inpoint``/``outpoint`` on prepared segments (true for the legacy
        ffmpeg-concat engine via its ffconcat plan; the GStreamer engine reads
        only ``segment.path``). When False — the safe default — cache hits are
        emitted as a fast ``-c copy`` trim into the per-plan output instead, so
        the historic "prepared segments are trim-free" contract holds for any
        consumer. Either way a hit costs seconds, not a re-encode."""
        self._work_dir = work_dir
        self._ffmpeg_runner = ffmpeg_runner
        self._loudness_checker = loudness_checker
        self._warm_scheduler = warm_scheduler
        self._playout_trim_supported = playout_trim_supported
        self._warming_guard = threading.Lock()
        self._warming: set[str] = set()
        # ponytail: one Lock per cache key ever seen, never pruned -- bounded
        # by the number of distinct assets aired over the process lifetime.
        self._conform_locks: dict[str, threading.Lock] = {}
        # Hostile-review follow-up, item 5: this module has no visibility of
        # its own into which per-plan directories a caller still considers
        # LIVE (an active on-air plan, an armed-but-not-yet-settled reload) --
        # only the daemon knows that. None means GC falls back to keep-N/
        # budget/age alone (still safe, just less precise); see
        # ``set_protected_plan_dirs_provider``.
        self._protected_plan_dirs_provider: Callable[[str], frozenset[Path]] | None = None

    def set_protected_plan_dirs_provider(
        self, provider: Callable[[str], frozenset[Path]] | None
    ) -> None:
        """Wire a callback ``prepare()`` consults before every GC pass to learn
        which of THIS channel's per-plan directories must never be evicted,
        however old, large, or far outside keep-N recency they are.

        A setter rather than a constructor arg because of construction order:
        production wiring builds the ``SourcePreparer`` instance FIRST (so its
        ``.prepare``/``.release`` bound methods can be passed into
        ``EgressDaemon.__init__``), and only the resulting daemon can answer
        "which directories are live" (``EgressDaemon.live_prepared_plan_dirs``)
        -- see cli.py's/automation.py's wiring, both of which call this right
        after constructing the daemon."""
        self._protected_plan_dirs_provider = provider

    # -- persistent conform cache -------------------------------------------

    def _cache_dir(self) -> Path:
        return self._work_dir / _CACHE_DIR_NAME

    def _cache_key(self, source_path: Path, config: EgressConfig) -> str | None:
        """Fingerprint (source file, canonical profile, loudness config) or None.

        Stat-based (path, size, mtime_ns): a re-finalized recording at the same
        path gets a new key. Returns None when caching is disabled or the file
        cannot be statted (callers fall back to uncached behavior).
        """
        if _cache_budget_bytes() <= 0:
            return None
        try:
            st = source_path.stat()
        except OSError:
            return None
        raw = "|".join(
            [
                str(source_path.resolve()),
                str(st.st_size),
                str(st.st_mtime_ns),
                config.canonical_profile.model_dump_json(),
                f"{config.loudness_target_lufs:g}",
                f"{config.loudness_tolerance_lufs:g}",
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _read_cache_meta(self, key: str) -> dict[str, object] | None:
        meta_path = self._cache_dir() / f"{key}.json"
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_cache_meta(self, key: str, loudness: LoudnessGateResult, normalized: bool) -> None:
        meta = {
            "loudness_status": loudness.status,
            "measured_lufs": loudness.measured_lufs,
            "normalized": normalized,
        }
        (self._cache_dir() / f"{key}.json").write_text(json.dumps(meta), encoding="utf-8")

    def _conform_lock(self, key: str) -> threading.Lock:
        """A per-cache-key lock: a background warm and a foreground
        untrimmed-miss conform for the same asset must never write the
        identical {key}.ts.tmp concurrently."""
        with self._warming_guard:
            return self._conform_locks.setdefault(key, threading.Lock())

    def _conform_full_asset_into_cache(
        self,
        key: str,
        source_path: Path,
        config: EgressConfig,
        loudness: LoudnessGateResult,
        normalized: bool,
    ) -> Path:
        """Conform the WHOLE asset (no trim) into the cache, atomically."""
        cache_dir = self._cache_dir()
        final = cache_dir / f"{key}.ts"
        with self._conform_lock(key):
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cache_dir / f"{key}.ts.tmp"
            args = build_conform_source_args(
                source_path=source_path,
                output_path=tmp,
                segment=None,
                profile=config.canonical_profile,
                loudness_target_lufs=config.loudness_target_lufs if normalized else None,
                # ponytail: single-threaded background encode so a warm can't
                # starve the on-air encoder; add priority-class control if
                # field data shows starvation anyway.
                background=True,
            )
            result = self._ffmpeg_runner(args)
            if result.returncode != 0:
                tmp.unlink(missing_ok=True)
                raise SourcePrepareError(
                    f"Full-asset conform for cache failed for {source_path.name!r}."
                )
            tmp.replace(final)
            self._write_cache_meta(key, loudness, normalized)
            self._evict_cache_over_budget()
            if not final.exists():
                # The just-written entry alone exceeded the budget and was
                # evicted by the call above -- fail cleanly instead of
                # returning a path the encoder will find missing at air time.
                (cache_dir / f"{key}.json").unlink(missing_ok=True)
                raise SourcePrepareError(
                    f"Conform-cache budget too small to retain {source_path.name!r}; "
                    "increase CIVICCAST_CONFORM_CACHE_GB or exclude this asset."
                )
            return final

    def _emit_prepared_from_cache(
        self,
        cached_ts: Path,
        segment: EgressSourceSegment,
        *,
        source_path: Path,
        output_path: Path,
        loudness_status: str,
        measured_lufs: float | None,
        normalized: bool,
    ) -> tuple[EgressSourceSegment, PreparedSegmentRecord]:
        """Emit a prepared segment backed by the cached full-asset conform.

        Engine honors playout trims -> point straight at the cache with
        ``inpoint``/``outpoint`` (zero ffmpeg work). Otherwise -> stream-copy
        the wanted window into the per-plan output: no re-encode, seconds even
        for hour-long assets, and the historic trim-free contract holds.
        ``-ss`` before ``-i`` under ``-c copy`` floors to the previous keyframe
        (<= one GOP early at the canonical profile) — the honest trade for
        engine-agnostic prepared segments; documented in the playout runbook.
        """
        inpoint = segment.inpoint_seconds
        if self._playout_trim_supported:
            emitted = str(cached_ts)
            emit_inpoint = inpoint
            emit_outpoint = (inpoint or 0.0) + segment.duration_seconds
        else:
            # H5 fix (atomic write, second half): write to a ``.tmp`` sibling and
            # ``rename`` into place only on success -- mirrors
            # ``_conform_full_asset_into_cache``'s existing tmp+replace pattern
            # (this was the one write site in this module that did NOT already
            # follow it). ``output_path`` is now unique per ``prepare()`` call
            # (see that method's docstring), so this is defense-in-depth rather
            # than the primary H5 fix -- but a reader that opens the final path
            # mid-write (this module has no control over when a consumer looks)
            # must never observe a partial file either.
            # F7 fix: prepare() no longer pre-creates the per-plan directory
            # (it may end up removed again if nothing is ever written into it),
            # so the first actual write site must create it lazily.
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_output_path = output_path.with_name(output_path.name + ".tmp")
            args = ["-hide_banner", "-loglevel", "warning"]
            if inpoint is not None:
                args.extend(["-ss", f"{inpoint:g}"])
            args.extend(
                [
                    "-i",
                    str(cached_ts),
                    "-t",
                    f"{segment.duration_seconds:g}",
                    "-c",
                    "copy",
                    "-f",
                    "mpegts",
                    str(tmp_output_path),
                ]
            )
            result = self._ffmpeg_runner(args)
            if result.returncode != 0:
                tmp_output_path.unlink(missing_ok=True)
                raise SourcePrepareError(
                    f"Cached conform copy-out failed for {segment.label!r}; inspect FFmpeg output."
                )
            tmp_output_path.replace(output_path)
            emitted = str(output_path)
            emit_inpoint = None
            emit_outpoint = None
        return (
            EgressSourceSegment(
                label=segment.label,
                path=emitted,
                duration_seconds=segment.duration_seconds,
                inpoint_seconds=emit_inpoint,
                outpoint_seconds=emit_outpoint,
                kind=segment.kind,
                source_ref=segment.source_ref,
            ),
            PreparedSegmentRecord(
                label=segment.label,
                source_path=str(source_path),
                prepared_path=emitted,
                loudness_status=loudness_status,
                measured_lufs=measured_lufs,
                normalized=normalized,
            ),
        )

    def _schedule_warm(
        self,
        key: str,
        source_path: Path,
        config: EgressConfig,
        loudness: LoudnessGateResult,
        normalized: bool,
    ) -> None:
        """Warm-behind: populate the full-asset cache without blocking airtime."""
        with self._warming_guard:
            if key in self._warming:
                return
            self._warming.add(key)

        def _job() -> None:
            try:
                self._conform_full_asset_into_cache(key, source_path, config, loudness, normalized)
            except Exception:
                # A failed warm must never surface at air; the next airing
                # simply misses the cache and warms again.
                _LOG.exception("Conform-cache warm failed; next airing re-warms.")
            finally:
                with self._warming_guard:
                    self._warming.discard(key)

        self._warm_scheduler(_job)

    def release(self, plan_dir: Path | None) -> None:
        """F3 fix: immediately reclaim ONE specific per-plan directory the caller
        independently knows is safe to remove -- e.g. the daemon calls this for
        the PREVIOUS plan's directory once a content-reload's replacement has
        actually SETTLED (``engine.reload_program``'s ``on_settled`` landing
        "applied" means the old leg is disposed engine-side and its file is no
        longer open for read). ``None`` (no discrete directory was ever tracked
        for that plan -- see ``SourcePreparationReport.plan_dir``) is a no-op.
        Best-effort and silent, same as GC: a locked file (still-open handle on
        Windows, worker slower to let go than expected) just means this
        directory falls through to the next GC pass instead of a hard failure."""
        if plan_dir is None:
            return
        with contextlib.suppress(OSError):
            shutil.rmtree(plan_dir)

    def _gc_prepared_plan_dirs(
        self, channel_prepared_root: Path, *, keep: frozenset[Path] = frozenset()
    ) -> None:
        """Reclaim old per-plan ``prepared/<uuid>`` directories (H5 fix; budget +
        keep-N added by the F3 follow-up). Best-effort and silent throughout: a
        GC hiccup (a locked file, a permissions error) must never fail the
        ``prepare()`` call it runs inside of -- the worst case is one stale
        directory surviving to the next prepare's GC pass.

        Three layers, in order:

        1. **Keep-N-most-recent** (``_PREPARED_PLAN_DIR_KEEP_N``, by directory
           mtime) is NEVER eligible for removal here, regardless of size or age
           -- one of these could plausibly still be the plan a live worker is
           reading, or one the daemon has armed but not yet confirmed settled.
           ``keep`` (the caller's own actively-tracked directories, e.g. the
           daemon's current on-air plan) is unioned into this protected set,
           so an explicitly-tracked directory is never swept even if it is
           somehow older than the N most recent by mtime.
        2. **Byte budget** (``_prepared_plan_dir_budget_bytes``) across
           whatever is left after (1): oldest-first eviction until the
           channel's ``prepared/`` tree (excluding the protected set) is back
           under budget.
        3. **Age floor** (``_PREPARED_PLAN_DIR_MAX_AGE_S``, 24h) as an absolute
           last resort for anything (1) and (2) did not already catch -- a
           directory this old was very likely already reclaimed by (2) on a
           channel with any reload cadence at all; this floor exists for the
           degenerate case of a channel that barely reloads, where the byte
           budget alone might never trigger.

        F6 (same follow-up): also removes any PRE-UPGRADE flat
        ``prepared/segment-NNNN.ts``/``.tmp`` file sitting directly under
        ``channel_prepared_root`` itself (never inside a plan subdirectory) --
        the layout this fix replaced. Safe unconditionally: no code path
        written after this fix ever reads from that flat location again, and a
        file a pre-upgrade worker still has open simply fails to delete (a
        locked file raises ``OSError``, suppressed) and is retried next pass."""
        try:
            entries = list(channel_prepared_root.iterdir())
        except OSError:
            return
        # F6: pre-upgrade flat files directly under the channel's prepared/ root.
        for entry in entries:
            if entry.is_file() and entry.suffix in (".ts", ".tmp"):
                with contextlib.suppress(OSError):
                    entry.unlink()
        plan_dirs = [entry for entry in entries if entry.is_dir()]

        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        plan_dirs.sort(key=_mtime, reverse=True)  # newest first
        protected = set(plan_dirs[:_PREPARED_PLAN_DIR_KEEP_N]) | (keep & set(plan_dirs))
        candidates = [entry for entry in plan_dirs if entry not in protected]
        # oldest-first for eviction (both the budget and age passes below want
        # to give up the least-recently-used directory first).
        candidates.sort(key=_mtime)

        budget = _prepared_plan_dir_budget_bytes()
        sizes = {entry: _dir_size_bytes(entry) for entry in candidates}
        total = sum(sizes.values())
        remaining: list[Path] = []
        for entry in candidates:
            if total <= budget:
                remaining.append(entry)
                continue
            with contextlib.suppress(OSError):
                shutil.rmtree(entry)
            total -= sizes[entry]

        now = time.time()
        for entry in remaining:
            if now - _mtime(entry) <= _PREPARED_PLAN_DIR_MAX_AGE_S:
                continue
            with contextlib.suppress(OSError):
                shutil.rmtree(entry)

    def _evict_cache_over_budget(self) -> None:
        budget = _cache_budget_bytes()
        cache_dir = self._cache_dir()
        try:
            entries = sorted(cache_dir.glob("*.ts"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        total = sum(p.stat().st_size for p in entries if p.exists())
        for oldest in entries:
            if total <= budget:
                break
            try:
                size = oldest.stat().st_size
                oldest.unlink()
                oldest.with_suffix(".json").unlink(missing_ok=True)
                total -= size
            except OSError:
                continue

    def prepare(
        self, source_plan: EgressSourcePlan, config: EgressConfig
    ) -> SourcePreparationReport:
        """Return a canonical, trim-free source plan ready for the persistent encoder.

        H5 fix (measured on real hardware, tester soak): before this fix every
        ``prepare()`` call for a channel wrote its non-cached/trim-copy output to
        the SAME fixed path (``<channel>/prepared/segment-NNNN.ts``, keyed only by
        segment INDEX within its own call, never by which plan the call was
        preparing). For the GStreamer engine (``playout_trim_supported=False``),
        a content-reload's ``prepare()`` call for the NEWLY-due plan therefore
        wrote directly over the exact file the CURRENTLY LIVE worker's ``filesrc``
        was still reading for the plan already on air -- no GStreamer warning, no
        error, just a truncated/rewritten file underneath a live read, surfacing
        only as a downstream ``CTRL stall: no output for 10s`` on the worker with
        nothing in its own log pointing at the cause. Every call now gets its own
        uniquely-named subdirectory (``<channel>/prepared/<uuid>/segment-NNNN.ts``)
        so two ``prepare()`` calls -- however close together, however they
        overlap in wall-clock time -- can never share an output path. See
        ``_gc_prepared_plan_dirs`` for how the resulting directories are
        eventually reclaimed (keep-N-most-recent + a byte budget + an age
        floor as a last resort -- F3 fix), ``release`` for how a caller that
        independently knows a plan is retired can reclaim it immediately, and
        each write site's own comments for the accompanying atomic-write fix
        (H5's second half: a partial write must never be observable at the
        final path either). F7 fix: the directory itself is created lazily (by
        the write sites below, not here) and removed again at the end of this
        call if nothing was ever written into it -- a plan whose every segment
        is ``kind == "live"``, or whose every segment is a cache HIT under
        ``playout_trim_supported=True`` (which points straight at the shared
        conform-cache entry, never writing a per-plan file at all), leaves no
        trace under ``prepared/`` rather than an empty directory nothing will
        ever clean up."""

        channel_prepared_root = self._work_dir / config.channel_id / "prepared"
        channel_prepared_root.mkdir(parents=True, exist_ok=True)
        # Item 5 fix: ask the wired provider (the daemon, if one is
        # configured -- set_protected_plan_dirs_provider) which of this
        # channel's directories are LIVE right now, so GC can never evict one
        # regardless of age, size, or keep-N recency -- not just the
        # keep-N-most-recent heuristic on its own.
        protected = (
            self._protected_plan_dirs_provider(config.channel_id)
            if self._protected_plan_dirs_provider is not None
            else frozenset()
        )
        self._gc_prepared_plan_dirs(channel_prepared_root, keep=protected)
        prepared_dir = channel_prepared_root / uuid.uuid4().hex[:12]
        prepared_segments: list[EgressSourceSegment] = []
        records: list[PreparedSegmentRecord] = []
        # CA-8: filler plans repeat one rendered segment hundreds of times to
        # span the fill target. Preparing (loudness probe + conform) per
        # ENTRY multiplied channel startup ~120x — identical (path, trim)
        # segments prepare exactly once and share the prepared output.
        # Cache assumption (audit ENG-015): repeats of one (path, trim) are
        # intentionally IDENTICAL entries, so the first segment's label and
        # record stand in for later repeats. A plan that repeats one file
        # under different labels would surface the first label only.
        seen: dict[
            tuple[str, float | None, float | None],
            tuple[EgressSourceSegment, PreparedSegmentRecord],
        ] = {}
        for index, segment in enumerate(source_plan.segments, start=1):
            if segment.kind == "live":
                prepared_segments.append(segment)
                records.append(
                    PreparedSegmentRecord(
                        label=segment.label,
                        source_path=segment.path,
                        prepared_path=segment.path,
                        loudness_status="not_checked_live_passthrough",
                        measured_lufs=None,
                        normalized=False,
                    )
                )
                continue
            key = (segment.path, segment.inpoint_seconds, segment.outpoint_seconds)
            cached = seen.get(key)
            if cached is not None:
                prepared_segments.append(cached[0])
                records.append(cached[1])
                continue
            prepared_path = prepared_dir / f"segment-{index:04d}.ts"
            prepared_segment, record = self._prepare_segment(
                segment,
                config=config,
                output_path=prepared_path,
            )
            seen[key] = (prepared_segment, record)
            prepared_segments.append(prepared_segment)
            records.append(record)
        # F7 fix: nothing was ever written into prepared_dir (every segment was
        # live-passthrough and/or a playout_trim_supported=True cache hit, which
        # points straight at the shared conform-cache entry) -- remove the
        # directory rather than leave an empty one nothing will ever clean up,
        # and report no plan_dir at all (there is nothing to release or GC).
        reported_plan_dir: Path | None = prepared_dir
        if prepared_dir.exists() and not any(prepared_dir.iterdir()):
            with contextlib.suppress(OSError):
                prepared_dir.rmdir()
                reported_plan_dir = None
        elif not prepared_dir.exists():
            reported_plan_dir = None
        return SourcePreparationReport(
            source_plan=EgressSourcePlan(
                channel_id=source_plan.channel_id,
                segments=prepared_segments,
            ),
            records=tuple(records),
            plan_dir=reported_plan_dir,
        )

    def _prepare_segment(
        self,
        segment: EgressSourceSegment,
        *,
        config: EgressConfig,
        output_path: Path,
    ) -> tuple[EgressSourceSegment, PreparedSegmentRecord]:
        source_path = Path(segment.path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise SourcePrepareError(
                f"Egress source {segment.label!r} is missing before preparation: {source_path}."
            )
        key = self._cache_key(source_path, config)
        trimmed = segment.inpoint_seconds is not None or segment.outpoint_seconds is not None

        # Cache HIT: the full-asset conform already exists — no re-encode, no
        # probing (#156: an aired-before program starts within seconds). Trim is
        # applied at playout when the engine supports it, else as a fast
        # stream-copy into the per-plan output.
        if key is not None:
            cached_ts = self._cache_dir() / f"{key}.ts"
            meta = self._read_cache_meta(key)
            if cached_ts.is_file() and meta is not None:
                os.utime(cached_ts)  # refresh the eviction clock on hit
                return self._emit_prepared_from_cache(
                    cached_ts,
                    segment,
                    source_path=source_path,
                    output_path=output_path,
                    loudness_status=str(meta.get("loudness_status", "ok")),
                    measured_lufs=(
                        float(lufs)
                        if isinstance(lufs := meta.get("measured_lufs"), int | float)
                        else None
                    ),
                    normalized=bool(meta.get("normalized", False)),
                )

        loudness = self._loudness_checker(
            media_path=source_path,
            target_lufs=config.loudness_target_lufs,
            tolerance_lufs=config.loudness_tolerance_lufs,
        )
        if loudness.status != "ok" and loudness.measured_lufs is None:
            raise SourcePrepareError(
                f"Egress source {segment.label!r} could not be measured for loudness: "
                f"{loudness.operator_action}"
            )
        normalized = loudness.status != "ok"

        # Untrimmed MISS: the full-asset conform IS what airs — conform it once,
        # directly into the cache, then emit from the cache (duration truncation
        # applied at playout or via stream-copy per engine capability).
        if key is not None and not trimmed:
            cached_ts = self._conform_full_asset_into_cache(
                key, source_path, config, loudness, normalized
            )
            return self._emit_prepared_from_cache(
                cached_ts,
                segment,
                source_path=source_path,
                output_path=output_path,
                loudness_status=loudness.status,
                measured_lufs=loudness.measured_lufs,
                normalized=normalized,
            )

        # Trimmed MISS (first-ever join-in-progress start): conform only the
        # remaining portion straight to air — identical latency to the historic
        # behavior — and warm the full-asset cache behind it for next time.
        # H5 fix (atomic write, second half): same tmp+rename pattern as the
        # cache-hit stream-copy branch above -- see that branch's comment.
        # F7 fix: create the per-plan directory lazily -- see the sibling
        # comment in _emit_prepared_from_cache.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_output_path = output_path.with_name(output_path.name + ".tmp")
        args = build_conform_source_args(
            source_path=source_path,
            output_path=tmp_output_path,
            segment=segment,
            profile=config.canonical_profile,
            loudness_target_lufs=config.loudness_target_lufs if normalized else None,
        )
        result = self._ffmpeg_runner(args)
        if result.returncode != 0:
            tmp_output_path.unlink(missing_ok=True)
            raise SourcePrepareError(
                f"Egress source {segment.label!r} could not be conformed; inspect FFmpeg output."
            )
        tmp_output_path.replace(output_path)
        if key is not None:
            self._schedule_warm(key, source_path, config, loudness, normalized)
        return (
            EgressSourceSegment(
                label=segment.label,
                path=str(output_path),
                duration_seconds=segment.duration_seconds,
                kind=segment.kind,
                source_ref=segment.source_ref,
            ),
            PreparedSegmentRecord(
                label=segment.label,
                source_path=str(source_path),
                prepared_path=str(output_path),
                loudness_status=loudness.status,
                measured_lufs=loudness.measured_lufs,
                normalized=normalized,
            ),
        )


def build_conform_source_args(
    *,
    source_path: Path,
    output_path: Path,
    segment: EgressSourceSegment | None,
    profile: CanonicalProfile,
    loudness_target_lufs: float | None = None,
    background: bool = False,
) -> list[str]:
    """Build FFmpeg args that conform one media source to the canonical profile.

    ``segment=None`` conforms the WHOLE asset (no ``-ss``/``-t``) — the
    persistent conform-cache unit; trim happens at playout via the ffconcat
    plan. ``background=True`` caps the encode at one thread so a warm-behind
    conform cannot starve the on-air encoder.
    """

    args = ["-hide_banner", "-loglevel", "warning"]
    if segment is not None and segment.inpoint_seconds is not None:
        args.extend(["-ss", f"{segment.inpoint_seconds:g}"])
    args.extend(["-i", str(source_path)])
    if segment is not None:
        args.extend(["-t", f"{segment.duration_seconds:g}"])
    filters = [
        (
            f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
            f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={profile.fps},format=yuv420p"
        )
    ]
    args.extend(["-vf", ",".join(filters)])
    if loudness_target_lufs is not None:
        args.extend(["-af", f"loudnorm=I={loudness_target_lufs:g}:LRA=11:TP=-1.5"])
    if background:
        args.extend(["-threads", "1"])
    args.extend(
        [
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-g",
            str(profile.gop_size),
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
    )
    return args
