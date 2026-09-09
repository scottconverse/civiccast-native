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
import queue
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
from civiccast.stream._ffmpeg import probe_media_duration_seconds, run_ffmpeg
from civiccast.stream.loudness import (
    DEFAULT_LOUDNESS_STANDARD,
    LoudnessGateResult,
    check_streaming_loudness,
)

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

#: Item 66 round-3 (Opus review): _evict_cache_over_budget's orphan reap.
#: A ``.ts.tmp`` this old was abandoned mid-write (a crash, a killed
#: process) -- any legitimate in-flight conform or promotion finishes in
#: seconds to low minutes even for an hour-long asset. A ``.json`` with no
#: sibling ``.ts`` this old is a loudness-only probe (see
#: ``_write_cache_meta``) whose conform never landed (every attempt failed,
#: or the process was killed between the two writes).
_ORPHAN_CACHE_TMP_MAX_AGE_S = 3600.0
_ORPHAN_CACHE_META_MAX_AGE_S = 24.0 * 3600.0

#: Item 66 round-3 (Opus review, point 7): an untrimmed loudness probe no
#: longer decodes the whole asset -- it samples a window instead. This is
#: the one place that sampling-window assumption is encoded; see
#: ``_prepare_segment``'s loudness-probe comment.
_UNTRIMMED_LOUDNESS_PROBE_CAP_S = 120.0

#: Item 66 round-4 (Opus review, point 2): a HEAD sample (the round-3
#: shape) can land on cold open silence/room tone and measure the silence
#: floor instead of the program's real loudness -- a real field failure
#: (-70 LUFS at the head of a 39-minute meeting recording), which would
#: then drive loudnorm's normalization target completely wrong and get
#: memoized for every other segment/airing of that asset. The sample
#: window now starts partway into the asset instead of at the very head.
_UNTRIMMED_LOUDNESS_PROBE_FRACTION = 0.4

#: Item 66 round-5 (Opus review, point 3): the offset for the SECOND
#: bounded sample, taken only when the first (40%-in) sample measures at
#: the silence floor. A different offset than the first sample so the two
#: are genuinely independent evidence (both landing on, say, the same
#: extended silence would otherwise look like agreement).
_UNTRIMMED_LOUDNESS_PROBE_FRACTION_2 = 0.7

#: A measurement at or below this integrated LUFS is indistinguishable from
#: silence/room tone for any of CivicCast's target loudness standards (the
#: least aggressive, ATSC A/85, still targets -24 LKFS +/- tolerance) --
#: treat it as an unusable sample rather than a real reading of the asset's
#: program loudness.
_LOUDNESS_SILENCE_FLOOR_LUFS = -60.0

#: Item 66 round-7 (Opus review, point 2, MEDIUM fix): a single HEAD sample
#: is only genuinely conclusive proof of silence when its own window
#: (``min(duration, _UNTRIMMED_LOUDNESS_PROBE_CAP_S)`` from the very start)
#: covers the WHOLE asset -- i.e. ``duration <= _UNTRIMMED_LOUDNESS_PROBE_CAP_S``
#: itself. Round-6 set this to ``_UNTRIMMED_LOUDNESS_PROBE_CAP_S * 2`` (240s)
#: instead, reasoning only about when a genuinely independent SECOND sample
#: could fit -- but that let a 120-240s asset's single 120s HEAD sample (at
#: most half the file) get trusted as "the whole (or nearly the whole)
#: asset" when it was really only up to half of it: a real field failure
#: (a 200s clip with audio starting at 130s, entirely past the sampled
#: window, memoized as -70 LUFS silence). Below/at this duration the one
#: sample truly is (nearly) the whole file, so it needs no corroboration;
#: above it, the "long asset" branch below is used instead -- its first
#: sample already sits at 40% in (never the head) and, on a floor reading,
#: corroborates with a second bounded sample before trusting silence, which
#: is what protects the 120-240s range now.
_SHORT_ASSET_SINGLE_SAMPLE_MAX_S = _UNTRIMMED_LOUDNESS_PROBE_CAP_S

#: Item 66 round-7 (point 1, HIGH): D42 (source_plan.py's ``_segment_duration``,
#: ``min(slot, playable)``) means an "untrimmed" segment (no inpoint/outpoint)
#: can carry a ``duration_seconds`` SHORTER than the asset's real media length
#: whenever the schedule slot is shorter than the asset -- a 30s slot on a
#: 67s asset produces a 30s bounded conform that is NOT the whole asset,
#: even though ``trimmed`` (inpoint/outpoint both None) is False. The same
#: tolerance ``source_plan.py``'s own ``_covers_slot`` uses for its slot/media
#: fuzz (1s) is reused here so a 29.97s asset in a 30s slot still counts as
#: "the whole asset" and gets promoted into the shared cache.
_FULL_ASSET_DURATION_TOLERANCE_S = 1.0


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


_warm_queue: queue.Queue[Callable[[], None]] = queue.Queue()
_warm_worker_lock = threading.Lock()
_warm_worker_started = False


def _warm_worker() -> None:
    """Single background worker draining ``_warm_queue`` FIFO, one job at a
    time, forever -- see ``_default_warm_scheduler``. A job's own exception
    handling (``_schedule_warm``'s ``_job`` already catches and logs) should
    make this outer catch unreachable in practice; it exists purely so a
    bug in that handling can never permanently kill warming for the rest of
    the process (the worker is started exactly once -- see
    ``_warm_worker_started`` -- so a thread that dies uncaught would never
    be replaced)."""
    while True:
        job = _warm_queue.get()
        try:
            job()
        except Exception:
            _LOG.exception("Conform-cache warm job raised past its own error handling.")
        finally:
            _warm_queue.task_done()


def _default_warm_scheduler(job: Callable[[], None]) -> None:
    """Queue a cache warm onto a single background worker (production
    default).

    Item 66 (point 4, Opus review): this used to spawn one daemon thread
    PER job -- unbounded, so every distinct asset aired while a previous
    warm was still running got its own thread, all contending for CPU with
    the synchronous foreground conforms this whole feature exists to keep
    fast. Now FIFO through one long-lived worker: at most one background
    warm conform runs at a time, queued jobs simply wait. ``_schedule_warm``'s
    own per-key dedupe (``self._warming``) still prevents the same asset
    from being queued twice while its warm is pending or running.
    """
    global _warm_worker_started
    with _warm_worker_lock:
        if not _warm_worker_started:
            threading.Thread(target=_warm_worker, name="conform-cache-warm", daemon=True).start()
            _warm_worker_started = True
    _warm_queue.put(job)


def _cache_budget_bytes() -> float:
    raw = os.environ.get("CIVICCAST_CONFORM_CACHE_GB", "").strip()
    try:
        gb = float(raw) if raw else _DEFAULT_CACHE_GB
    except ValueError:
        gb = _DEFAULT_CACHE_GB
    return gb * 1e9


def _foreground_thread_cap() -> int:
    """Item 66 (point 2, Opus review, measured on HALO): conforming 300s of
    content at ``-threads 1`` took 233s vs 36.6s unthrottled -- the
    original item-66 fix's unconditional single-threaded background=False
    knob was dead on the shipped default (``playout_trim_supported=False``)
    and, once reached via ``EgressDaemon._try_content_reload``'s
    synchronous prepare on the ffmpeg-concat engine (``daemon.py`` around
    line 1839, which can run while another channel is genuinely on air),
    fully unthrottled foreground encodes would starve everything else on
    the box. Cap foreground (synchronous, blocks the caller) conforms at
    half the machine's cores instead of leaving them fully unbounded or
    fully serialized."""
    cpu_count = os.cpu_count() or 2
    return max(1, cpu_count // 2)


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

    def _write_cache_meta(
        self,
        key: str,
        loudness: LoudnessGateResult,
        normalized: bool,
        *,
        media_duration_seconds: float | None = None,
        full_asset_conform: bool = False,
    ) -> None:
        """Item 66 (point 1): now also called BEFORE any conform for this
        asset exists (a loudness-only probe result, persisted early so
        later segments of the same asset can skip re-probing) -- so this
        must create the cache directory itself rather than assume a conform
        call already did.

        Item 66 round-3 (Opus review): tmp+replace atomic write, same
        discipline as every ``.ts`` write in this module -- a reader
        (``_read_cache_meta``, or the cache-HIT check's ``.is_file()``) must
        never observe a partially-written ``{key}.json``.

        ``media_duration_seconds`` (item 66 round-5, point 2; simplified
        round-6, point 3): the asset's real media duration, probed once via
        ``probe_media_duration_seconds`` and cached here so later
        segments/airings of the same asset never re-probe it. Every call
        site that could plausibly know this value now threads it through
        explicitly (``_conform_full_asset_into_cache``,
        ``_promote_conform_into_cache``, ``_promote_finished_conform_into_
        cache``, ``_schedule_cache_copy_promotion``, ``_schedule_warm`` all
        gained the same keyword) -- a round-5 version of this method instead
        read the existing meta back and merged in whatever value it already
        held, purely to avoid a later write-without-the-value clobbering an
        earlier write-with-it. That extra read on every write is no longer
        needed now that the value travels with the call: this write is the
        single atomic write of everything this cache entry's meta holds.

        ``full_asset_conform`` (item 66 round-7, point 1, HIGH): True ONLY
        when this write accompanies (or follows) an actual ``{key}.ts`` that
        genuinely holds the whole asset -- set exclusively by
        ``_promote_conform_into_cache``, the single choke point every
        promotion path (``_conform_full_asset_into_cache``,
        ``_promote_finished_conform_into_cache``, ``_schedule_cache_copy_
        promotion``'s job) funnels through right after the ``.ts`` itself is
        finalized. The probe-only call in ``_prepare_segment`` (persisted
        before any conform exists) never sets it, so it defaults False there.
        The cache-HIT check in ``_prepare_segment`` requires this flag before
        trusting ``{key}.ts`` as the shared full-asset entry -- see that
        check's own comment for why a numeric ``duration_seconds`` comparison
        alone cannot detect an already-on-disk short/truncated ``.ts`` (D42,
        round-6 BLOCKER: a slot-capped "untrimmed" conform used to get
        promoted as if it were the whole asset). A meta file written by
        pre-round-7 code never carries this key, so ``.get(...)`` on it
        naturally reads False too -- a legacy short entry self-heals into a
        MISS (and gets correctly re-conformed) rather than staying silently
        wrong.
        """
        cache_dir = self._cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "loudness_status": loudness.status,
            "measured_lufs": loudness.measured_lufs,
            "normalized": normalized,
            "media_duration_seconds": media_duration_seconds,
            "full_asset_conform": full_asset_conform,
        }
        final = cache_dir / f"{key}.json"
        tmp = final.with_name(final.name + ".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(final)

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
        *,
        threads: int = 1,
        media_duration_seconds: float | None = None,
    ) -> Path | None:
        """Conform the WHOLE asset (no trim) into the cache, atomically.

        ``threads`` (item 66, revised): the warm-behind path
        (``_schedule_warm``) keeps the default ``1`` -- single-threaded, so a
        background warm can never starve the on-air encoder. The synchronous
        start-path call (the untrimmed-MISS branch in ``_prepare_segment``,
        reachable only when ``self._playout_trim_supported`` is True -- see
        the guard there) passes ``_foreground_thread_cap()`` instead: an
        Opus-review follow-up found the original fix's unconditional
        ``background=False`` (fully unthrottled) starved the ffmpeg-concat
        engine's synchronous content-reload prepare (``daemon.py``'s
        ``_try_content_reload``, which runs this call ON the automation
        thread while other channels may be on air) -- a bounded cap keeps
        the synchronous path fast without letting it claim every core.

        Returns ``None`` instead of conforming (item 66 round-4 BLOCKER fix,
        Opus review) when this key's per-key lock is already held --
        virtually always ``_schedule_warm``'s background job already
        conforming the identical asset. This lock used to be acquired with a
        BLOCKING ``with`` statement: a background warm holds it for its
        entire single-threaded conform (tens of minutes for a long asset),
        so a synchronous caller landing here while that warm is running
        would stall behind it for just as long -- exactly the kind of delay
        item 66 exists to close, just via lock contention instead of a
        direct synchronous conform. Callers on the synchronous path
        (``_prepare_segment``'s untrimmed/``playout_trim_supported`` branch)
        must treat ``None`` as "fall back to the bounded per-segment conform
        instead of waiting"; ``_schedule_warm``'s own background job ignores
        the return value entirely (a warm colliding with another warm for
        the same key can't happen -- see its own dedupe -- so ``None`` there
        would only mean an unrelated caller is already populating this exact
        entry, which is fine to leave to that caller).
        """
        lock = self._conform_lock(key)
        if not lock.acquire(blocking=False):
            _LOG.info(
                "Full-asset conform skipped for %r: another conform/warm already holds "
                "this asset's cache lock.",
                source_path.name,
            )
            return None
        try:
            cache_dir = self._cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cache_dir / f"{key}.ts.tmp"
            args = build_conform_source_args(
                source_path=source_path,
                output_path=tmp,
                segment=None,
                profile=config.canonical_profile,
                loudness_target_lufs=config.loudness_target_lufs if normalized else None,
                threads=threads,
            )
            result = self._ffmpeg_runner(args)
            if result.returncode != 0:
                tmp.unlink(missing_ok=True)
                raise SourcePrepareError(
                    f"Full-asset conform for cache failed for {source_path.name!r}."
                )
            return self._promote_conform_into_cache(
                key,
                tmp,
                source_path,
                loudness,
                normalized,
                media_duration_seconds=media_duration_seconds,
            )
        finally:
            lock.release()

    def _promote_conform_into_cache(
        self,
        key: str,
        tmp: Path,
        source_path: Path,
        loudness: LoudnessGateResult,
        normalized: bool,
        *,
        media_duration_seconds: float | None = None,
    ) -> Path:
        """Move an already-conformed ``tmp`` file (a full-asset conform, no
        trim) into the persistent conform cache atomically: rename into
        place, write the sidecar meta, run eviction, and fail cleanly if the
        just-written entry alone exceeds budget.

        Shared tail of every call site that already holds ``self._conform_
        lock(key)`` around the call (item 66 round-4: NON-BLOCKING
        acquisition at every one of them, so this method itself never
        blocks -- see ``_conform_full_asset_into_cache``,
        ``_promote_finished_conform_into_cache``, and
        ``_schedule_cache_copy_promotion``'s docstrings for what "already
        holds it" means at each -- round-5: the LATTER TWO must always
        release their own hold before returning, including on every
        failure path, since this method's own ``SourcePrepareError`` below
        is exactly the kind of failure a caller needs to still unwind
        cleanly from).

        Raises ``SourcePrepareError`` if the just-written entry alone
        exceeds the configured budget -- callers that must never let a
        cache-promotion failure interrupt something already safely airing
        (``_promote_finished_conform_into_cache``,
        ``_schedule_cache_copy_promotion``) catch this themselves.

        Item 66 round-7 (point 1, HIGH): this is the SOLE place a ``.ts`` is
        ever renamed into the persistent cache, so it is the one authoritative
        place to mark the sidecar meta ``full_asset_conform=True`` -- every
        caller (``_conform_full_asset_into_cache``'s own whole-file conform,
        and ``_promote_finished_conform_into_cache``/``_schedule_cache_copy_
        promotion``'s copy of an already-finished per-plan file) is now
        responsible for only ever reaching this method with a ``tmp`` that
        genuinely IS the whole asset -- ``_prepare_segment``'s cache-hit check
        depends on that invariant holding here unconditionally.
        """
        cache_dir = self._cache_dir()
        final = cache_dir / f"{key}.ts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp.replace(final)
        self._write_cache_meta(
            key,
            loudness,
            normalized,
            media_duration_seconds=media_duration_seconds,
            full_asset_conform=True,
        )
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

    def _promote_finished_conform_into_cache(
        self,
        key: str,
        finished_output_path: Path,
        source_path: Path,
        loudness: LoudnessGateResult,
        normalized: bool,
        *,
        media_duration_seconds: float | None = None,
    ) -> None:
        """Item 66 round-3 BLOCKER fix (Opus review): populate the
        persistent conform cache from an ALREADY-FINISHED, already-airing
        per-plan file via a hard link (``os.link``) -- never by moving
        ``finished_output_path`` itself. The segment is airing from that
        exact path; this method must never make it disappear.

        Round-4 (Opus review), point 1: the per-key lock is now acquired
        NON-BLOCKING. A background warm holds this SAME lock for its
        entire single-threaded conform (tens of minutes for a long asset);
        a blocking acquire here meant a synchronous caller could stall
        behind an in-progress warm for just as long. If the lock is
        already held, the promotion is skipped entirely (logged) -- the
        segment already airs from ``finished_output_path`` regardless, so
        skipping costs nothing except that this one airing's copy is (for
        now) absent from the persistent cache; the in-progress warm (or
        the next airing) populates it instead.

        Round-5 (Opus review) BLOCKER fix: linking is a metadata-only
        filesystem operation (fast) and still runs inline; but when it
        FAILS (e.g. the cache lives on a different volume than the
        per-plan directory), the full byte-for-byte copy is handed to the
        warm scheduler (``_schedule_cache_copy_promotion``) -- and that
        scheduling now happens ONLY AFTER this method's own lock is fully
        released (the ``lock.release()`` in ``finally`` below runs before
        the scheduling call, never after). Round 4 scheduled the copy job
        from INSIDE the still-held lock: the queued job itself
        blocking-acquired the SAME lock, so a synchronous
        ``warm_scheduler`` (the job runs inline, before this frame's
        ``finally`` could ever run) was a guaranteed self-deadlock, and
        even the real threaded scheduler head-of-line-blocked its single
        worker on a lock THIS caller was still holding.

        Any OTHER failure here (a failed link, or
        ``_promote_conform_into_cache``'s own over-budget
        ``SourcePrepareError``) is logged and swallowed, never raised: the
        segment is already safely on air from ``finished_output_path``
        regardless. The only cost of a promotion failure is that the NEXT
        airing of this asset misses the cache and re-conforms, exactly
        like a failed background warm already does (see
        ``_schedule_warm``).
        """
        lock = self._conform_lock(key)
        if not lock.acquire(blocking=False):
            _LOG.info(
                "Cache promotion skipped for %r: another conform/warm already holds "
                "this asset's cache lock; the segment already aired from its own file.",
                source_path.name,
            )
            return
        cache_dir = self._cache_dir()
        tmp = cache_dir / f"{key}.ts.tmp"
        needs_background_copy = False
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp.unlink(missing_ok=True)
            try:
                os.link(finished_output_path, tmp)
            except OSError:
                # Cross-volume (or otherwise unlinkable) -- the actual copy
                # is scheduled AFTER this method's own lock is released
                # (see the `finally` below and the call after this
                # try/except/finally) rather than here, while still held.
                needs_background_copy = True
            else:
                self._promote_conform_into_cache(
                    key,
                    tmp,
                    source_path,
                    loudness,
                    normalized,
                    media_duration_seconds=media_duration_seconds,
                )
        except Exception:
            _LOG.exception(
                "Promoting the finished conform for %r into the persistent conform cache "
                "failed; the segment already airs from its per-plan file unaffected. "
                "The next airing of this asset misses the cache and re-conforms.",
                source_path.name,
            )
            with contextlib.suppress(OSError):
                tmp.unlink()
        finally:
            lock.release()

        if needs_background_copy:
            self._schedule_cache_copy_promotion(
                key,
                finished_output_path,
                source_path,
                loudness,
                normalized,
                media_duration_seconds=media_duration_seconds,
            )

    def _schedule_cache_copy_promotion(
        self,
        key: str,
        finished_output_path: Path,
        source_path: Path,
        loudness: LoudnessGateResult,
        normalized: bool,
        *,
        media_duration_seconds: float | None = None,
    ) -> None:
        """Item 66 round-4 (Opus review, point 3): queue a full
        byte-for-byte copy of an already-finished, already-airing per-plan
        file into the persistent cache, for the case where
        ``_promote_finished_conform_into_cache`` could not hard-link it
        (typically a cross-volume cache/work-dir layout). MUST be called
        only after the caller has released its own hold on this key's
        per-key lock (round-5 BLOCKER fix -- see
        ``_promote_finished_conform_into_cache``'s docstring for why
        scheduling from inside a still-held lock was a self-deadlock with
        a synchronous scheduler and head-of-line blocking with the real
        one). Runs on the same single-worker warm queue as
        ``_schedule_warm`` (see ``_default_warm_scheduler``), so a slow
        cross-volume copy never contends with a foreground conform, and
        shares its dedupe (``self._warming``) so a burst of airings of the
        same asset never queues more than one populate job for it -- a
        warm and a copy-promotion for the same key are mutually exclusive
        the same way two warms for the same key already are.

        The queued job itself acquires the lock NON-BLOCKING too: on
        contention (a warm, or another copy-promotion job, already holds
        this key's lock) it skips outright rather than waiting or
        immediately re-queuing itself -- a naive re-queue with nothing
        else in the queue would busy-loop the single warm worker for as
        long as the contending operation runs, potentially tens of minutes
        for a warm's full-asset conform. Skipping costs nothing: whatever
        holds the lock is already populating this exact cache entry.

        Item 66 round-5 (point 5): this job's ``finished_output_path``
        lives under a per-plan ``prepared/<uuid>/`` directory, and this
        job can sit in the warm queue for a while before it runs -- see
        ``release``'s docstring for the accepted (not fixed) race against
        that directory being reclaimed (by ``release`` or
        ``_gc_prepared_plan_dirs``) before the copy runs.

        Item 66 round-6 (point 7): if handing ``_job`` to ``self.
        _warm_scheduler`` itself raises (the job is never queued at all --
        "discarded" before it ever got a chance to run its own cleanup),
        ``key`` is removed from ``self._warming`` right here instead of
        being left there forever -- otherwise ``_schedule_warm``'s own
        top-of-function dedupe check (which shares this same set) would
        silently refuse to ever schedule a GENUINE warm for this asset
        again for the life of this ``SourcePreparer`` instance.
        """
        with self._warming_guard:
            if key in self._warming:
                return
            self._warming.add(key)

        def _job() -> None:
            tmp: Path | None = None
            try:
                cached_ts = self._cache_dir() / f"{key}.ts"
                # Item 66 round-8 (MEDIUM fix): a flagless meta (a
                # pre-round-7 entry, or a probe-only write that never got a
                # conform) is not a genuine full-asset cache hit -- see
                # ``_write_cache_meta``'s and the cache-HIT check's own
                # docstrings for why ``full_asset_conform`` must be
                # explicitly True. Without this check, a legacy flagless
                # entry sitting here read as "already populated" and this
                # job returned without ever conforming, so the asset never
                # healed: every future airing kept paying the foreground
                # conform cost forever, and the stale short ``.ts`` stayed
                # in the eviction budget taking up space it was never
                # supposed to hold.
                cached_meta = self._read_cache_meta(key)
                if (
                    cached_ts.is_file()
                    and cached_meta is not None
                    and cached_meta.get("full_asset_conform") is True
                ):
                    return  # already populated by the time this job ran
                lock = self._conform_lock(key)
                if not lock.acquire(blocking=False):
                    _LOG.info(
                        "Background cache-copy promotion skipped for %r: another "
                        "conform/warm already holds this asset's cache lock.",
                        source_path.name,
                    )
                    return
                try:
                    cache_dir = self._cache_dir()
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    tmp = cache_dir / f"{key}.ts.tmp"
                    tmp.unlink(missing_ok=True)
                    try:
                        shutil.copy2(finished_output_path, tmp)
                    except Exception:
                        # Item 66 round-5 (point 5): a failed/partial copy
                        # must never leave a corrupt .ts.tmp behind for
                        # _evict_cache_over_budget's orphan reap to trip
                        # over later -- clean it up right away.
                        with contextlib.suppress(OSError):
                            tmp.unlink()
                        raise
                    self._promote_conform_into_cache(
                        key,
                        tmp,
                        source_path,
                        loudness,
                        normalized,
                        media_duration_seconds=media_duration_seconds,
                    )
                finally:
                    lock.release()
            except Exception:
                _LOG.exception(
                    "Background cache-copy promotion failed for %r; the next airing "
                    "re-populates the cache.",
                    source_path.name,
                )
                # Item 66 round-6 (point 5): the inner handler above already
                # covers a failed copy2; this covers every OTHER failure in
                # the block (cache_dir.mkdir, the initial tmp.unlink, or
                # _promote_conform_into_cache's own over-budget raise after
                # copy2 succeeded but before tmp was renamed away) so a
                # partial .ts.tmp is never left for the orphan reap to find.
                if tmp is not None:
                    with contextlib.suppress(OSError):
                        tmp.unlink()
            finally:
                with self._warming_guard:
                    self._warming.discard(key)

        try:
            self._warm_scheduler(_job)
        except Exception:
            with self._warming_guard:
                self._warming.discard(key)
            _LOG.exception(
                "Failed to queue background cache-copy promotion for %r; the next "
                "airing re-populates the cache.",
                source_path.name,
            )

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
            # ``_conform_full_asset_into_cache``'s tmp+replace pattern (every
            # write site under ``conform-cache/`` now follows it, including
            # ``_write_cache_meta``'s sidecar -- item 66 round-3 review).
            # ``output_path`` is now unique per ``prepare()`` call (see that
            # method's docstring), so this is defense-in-depth rather than the
            # primary H5 fix -- but a reader that opens the final path
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
        *,
        media_duration_seconds: float | None = None,
    ) -> None:
        """Warm-behind: populate the full-asset cache without blocking airtime.

        Item 66 round-6 (point 7): if handing ``_job`` to ``self.
        _warm_scheduler`` itself raises, ``key`` is removed from
        ``self._warming`` here too -- see
        ``_schedule_cache_copy_promotion``'s docstring, which shares this
        exact concern (and this exact ``self._warming`` set): a job
        "discarded" before it ever ran would otherwise leave the key
        stuck, silently suppressing every future GENUINE warm for this
        asset for the life of this ``SourcePreparer`` instance.
        """
        with self._warming_guard:
            if key in self._warming:
                return
            self._warming.add(key)

        def _job() -> None:
            try:
                # Item 66 round-4 (Opus review, point 1): this job may have
                # sat in the single-worker warm queue for a while (round-3,
                # point 4) -- by the time it is finally about to run, the
                # identical asset may already be cached (e.g. an untrimmed
                # airing of it promoted its own already-finished conform
                # straight in -- see _promote_finished_conform_into_cache).
                # Re-check right before doing any work and skip the
                # redundant re-conform if it's already there.
                cached_ts = self._cache_dir() / f"{key}.ts"
                # Item 66 round-8 (MEDIUM fix): same fix as
                # ``_schedule_cache_copy_promotion``'s ``_job`` -- a flagless
                # meta is not a genuine full-asset hit (see
                # ``_write_cache_meta``'s docstring); without this the exact
                # same permanent-miss self-heal failure applied here too.
                cached_meta = self._read_cache_meta(key)
                if (
                    cached_ts.is_file()
                    and cached_meta is not None
                    and cached_meta.get("full_asset_conform") is True
                ):
                    return
                self._conform_full_asset_into_cache(
                    key,
                    source_path,
                    config,
                    loudness,
                    normalized,
                    media_duration_seconds=media_duration_seconds,
                )
            except Exception:
                # A failed warm must never surface at air; the next airing
                # simply misses the cache and warms again.
                _LOG.exception("Conform-cache warm failed; next airing re-warms.")
            finally:
                with self._warming_guard:
                    self._warming.discard(key)

        try:
            self._warm_scheduler(_job)
        except Exception:
            with self._warming_guard:
                self._warming.discard(key)
            _LOG.exception("Failed to queue conform-cache warm; next airing re-warms.")

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
        directory falls through to the next GC pass instead of a hard failure.

        Item 66 round-5 (point 5): this can race a QUEUED
        ``_schedule_cache_copy_promotion`` job that still names a file
        under ``plan_dir`` as its ``finished_output_path`` -- the warm
        queue (round-3, point 4) can leave that job waiting behind other
        work for a while, and this method (or ``_gc_prepared_plan_dirs``
        below, on the very next ``prepare()`` call) has no way to know a
        copy job still needs that file. This is accepted, not fixed: the
        job's own ``shutil.copy2`` simply fails (the source is gone),
        caught and logged same as any other promotion failure -- the
        segment already aired from this file while it existed, and the
        next real airing of that asset re-populates the cache normally.
        """
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
        """Oldest-first eviction of ``.ts`` entries over
        ``CIVICCAST_CONFORM_CACHE_GB``.

        Item 66 round-3 (Opus review) also reaps two kinds of orphaned
        cache-dir detritus that no other code path here ever cleans up:

        * an abandoned ``{key}.ts.tmp`` (a conform or promotion interrupted
          mid-write, e.g. by a crash or a killed process) older than
          ``_ORPHAN_CACHE_TMP_MAX_AGE_S`` (1h) is deleted outright; a
          younger one is assumed still in-flight and its bytes are counted
          toward the budget below so a burst of concurrent warms/promotions
          can't blow past the configured budget before any of them finish
          and become real ``.ts`` entries;
        * a ``{key}.json`` with no sibling ``{key}.ts`` (a loudness-only
          probe meta -- see ``_write_cache_meta`` -- whose conform never
          followed) older than ``_ORPHAN_CACHE_META_MAX_AGE_S`` (24h) is
          deleted outright.
        """
        budget = _cache_budget_bytes()
        cache_dir = self._cache_dir()
        now = time.time()
        try:
            ts_entries = sorted(cache_dir.glob("*.ts"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return

        tmp_bytes = 0
        with contextlib.suppress(OSError):
            for tmp in cache_dir.glob("*.ts.tmp"):
                try:
                    age = now - tmp.stat().st_mtime
                except OSError:
                    continue
                if age > _ORPHAN_CACHE_TMP_MAX_AGE_S:
                    with contextlib.suppress(OSError):
                        tmp.unlink()
                    continue
                with contextlib.suppress(OSError):
                    tmp_bytes += tmp.stat().st_size

        with contextlib.suppress(OSError):
            for meta_path in cache_dir.glob("*.json"):
                if meta_path.with_suffix(".ts").exists():
                    continue
                try:
                    age = now - meta_path.stat().st_mtime
                except OSError:
                    continue
                if age > _ORPHAN_CACHE_META_MAX_AGE_S:
                    with contextlib.suppress(OSError):
                        meta_path.unlink()

        total = tmp_bytes
        for p in ts_entries:
            with contextlib.suppress(OSError):
                total += p.stat().st_size
        for oldest in ts_entries:
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
        meta = self._read_cache_meta(key) if key is not None else None
        if key is not None:
            cached_ts = self._cache_dir() / f"{key}.ts"
            # Item 66 round-7 (point 1, HIGH): ``full_asset_conform`` must be
            # explicitly True, not just present -- see ``_promote_conform_
            # into_cache``'s docstring for the invariant this depends on and
            # ``_write_cache_meta``'s for why a meta file from BEFORE this
            # flag existed (or the probe-only write, which never sets it)
            # reads as False here rather than raising. D42 (source_plan.py's
            # ``_segment_duration``) can make an "untrimmed" segment's own
            # ``duration_seconds`` SHORTER than the asset's real media length
            # (a schedule slot shorter than the asset) -- a round-6 BLOCKER:
            # such a segment's bounded conform used to get promoted as if it
            # were the whole asset (``trimmed`` is False either way, since
            # D42's truncation carries no inpoint/outpoint), so a LATER,
            # longer-slot airing of the same asset would hit this exact
            # cache entry and stream-copy ``-t`` past what it actually holds
            # -- dead air, sticky until the entry's size/mtime changed. A
            # plain ``segment.duration_seconds`` vs ``media_duration_seconds``
            # comparison HERE cannot catch this: ``media_duration_seconds``
            # records the asset's true length, not the short entry's actual
            # bytes, so it would look identical whether or not the ``.ts`` on
            # disk is genuinely the whole asset. The explicit marker (set only
            # at the one choke point that finalizes a ``.ts`` -- see that
            # method) is what actually distinguishes them.
            if cached_ts.is_file() and meta is not None and meta.get("full_asset_conform") is True:
                try:
                    os.utime(cached_ts)  # refresh the eviction clock on hit
                except FileNotFoundError:
                    # Item 66 round-3 (Opus review): a concurrent eviction
                    # pass (_evict_cache_over_budget, running under a
                    # DIFFERENT SourcePreparer/channel sharing this cache
                    # dir) removed the entry between the .is_file() check
                    # above and this utime call. Fall through and treat it
                    # as a MISS instead of returning a cache path that no
                    # longer exists.
                    pass
                else:
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

        # Item 66 round-6 (point 3): declared here, before the reuse/probe
        # split, so it is ALWAYS bound regardless of which branch runs --
        # both branches' tail calls (``_conform_full_asset_into_cache`` /
        # ``_promote_finished_conform_into_cache`` / ``_schedule_warm``)
        # thread it through to ``_write_cache_meta``.
        media_duration: float | None = None
        if meta is not None:
            # Item 66 (point 1, Opus review): the full conform isn't cached
            # yet, but a loudness probe for this SAME asset fingerprint
            # already ran and its meta was persisted -- by an earlier
            # segment of this asset in this very prepare() call, or an
            # earlier prepare() call whose warm never landed. Reuse it: an
            # 8-segment plan of one asset used to mean 8 full-file ebur128
            # passes (measured ~46.7s each on a 39-min clip) all on the
            # synchronous start path; now it's exactly one.
            loudness_status = str(meta.get("loudness_status", "ok"))
            loudness = LoudnessGateResult(
                status=loudness_status,
                standard=DEFAULT_LOUDNESS_STANDARD,
                target_lufs=config.loudness_target_lufs,
                used_ffmpeg_wrapper=True,
                measured_lufs=(
                    float(lufs)
                    if isinstance(lufs := meta.get("measured_lufs"), int | float)
                    else None
                ),
                operator_action=(
                    "Loudness is within tolerance."
                    if loudness_status == "ok"
                    else f"Normalize audio to {config.loudness_target_lufs:g} LUFS "
                    "and rerun the loudness gate."
                ),
            )
            normalized = bool(meta.get("normalized", False))
            # Item 66 round-6 (point 3): read the cached media duration back
            # from this SAME meta -- reused here so a downstream conform's
            # own ``_write_cache_meta`` call (which does not itself know the
            # duration) does not have to guess at it. Whichever segment
            # first probed this asset already persisted this value in the
            # exact same atomic write as the loudness fields above; a round-5
            # version of ``_write_cache_meta`` instead did a defensive
            # read-modify-write on every single write to avoid losing this
            # value -- reading it back once here, at the one place loudness
            # itself is also being reused from disk, replaces that.
            media_duration = (
                float(cached_duration)
                if isinstance(cached_duration := meta.get("media_duration_seconds"), int | float)
                else None
            )
        else:
            # Item 66 round-3 (Opus review): bound the probe to a WINDOW
            # instead of decoding/analyzing the whole file. A trimmed
            # segment probes exactly its own wanted window (``-ss
            # <inpoint>`` before ``-i`` for the seek, ``-t <duration>`` after
            # it -- the same convention ``build_conform_source_args`` uses).
            # An untrimmed segment (the full asset) samples
            # ``_UNTRIMMED_LOUDNESS_PROBE_CAP_S`` (120s) of the middle of the
            # asset instead -- round-4 (Opus review, point 2): a HEAD sample
            # (round-3's original shape) can land on cold-open silence/room
            # tone and measure the silence floor, a real field failure that
            # would drive loudnorm's target completely wrong and get
            # memoized for every other segment/airing of the asset.
            silent_asset = False
            # Item 66 round-6 (Opus review): two different ways a floor
            # reading on the FIRST sample can become a trusted silence
            # verdict. ``allow_second_sample`` -- corroborate with a
            # second, genuinely independent sample before trusting it (the
            # "long asset" branch below). ``single_sample_is_conclusive`` --
            # trust the FIRST sample alone, because its window already
            # covers the whole (or nearly the whole) known-length asset, so
            # there is nothing left to corroborate against (the "short,
            # known-duration asset" branch below). Neither applies to a
            # trimmed probe, nor when the real duration is unknown --
            # point 1(a): a single, uncorroborated sample against an asset
            # of UNKNOWN length is never trusted as proof of silence.
            allow_second_sample = False
            single_sample_is_conclusive = False
            if trimmed:
                probe_start_seconds = segment.inpoint_seconds
                probe_duration_seconds = segment.duration_seconds
            else:
                # Item 66 round-5 (Opus review, point 2): ``segment.
                # duration_seconds`` is NOT the asset's real media duration
                # here -- source_plan.py's ``_segment_duration`` returns
                # ``min(slot, playable)`` (or the bare SLOT for an
                # un-probed asset), so a schedule slot shorter than the
                # asset would place the 40%-in sample past the asset's
                # actual EOF (measured: a past-EOF ``-ss`` reads as silence
                # -> -70 LUFS -> an unnecessary floor fallback). Use the
                # REAL media duration instead, via a cheap ffprobe
                # ``-format`` query (not a decode). This branch is only
                # ever reached with ``meta is None`` (the sibling ``if meta
                # is not None:`` branch above already reused a cached
                # measurement and returned before probing at all) -- so
                # there is never an already-cached duration to reuse HERE;
                # ``_write_cache_meta`` below persists this probe's result
                # so a LATER ``prepare()`` call for this asset (once its
                # loudness eventually needs re-probing too, e.g. a
                # re-finalized recording gets a new cache key) still only
                # pays for one ffprobe, not a repeat one, alongside the
                # loudness memo it is written together with.
                media_duration = probe_media_duration_seconds(source_path)
                if media_duration is not None and media_duration > 0:
                    if media_duration <= _SHORT_ASSET_SINGLE_SAMPLE_MAX_S:
                        # Item 66 round-7 (point 2, MEDIUM fix): a single
                        # sample is only conclusive when its own window
                        # (min(duration, 120s) from the very start) IS the
                        # whole file -- i.e. duration itself is at most the
                        # probe cap. Round-6 used ``* 2`` (240s) here, which
                        # let a 120-240s asset's HEAD-only 120s sample stand
                        # in for the whole file when it was really covering
                        # at most half of it (see this constant's own
                        # docstring for the field failure that caught this).
                        probe_start_seconds = 0.0
                        probe_duration_seconds = min(
                            media_duration, _UNTRIMMED_LOUDNESS_PROBE_CAP_S
                        )
                        single_sample_is_conclusive = True
                    else:
                        # Long asset (now also anything just over 120s, not
                        # only >240s -- see the constant's docstring): 40% in,
                        # clamped so a LATER 70%-in resample can still fit
                        # non-overlapping when there IS room for one.
                        #
                        # Item 66 round-8 (LOW fix): the "room for one" cutoff
                        # is NOT 240s. Working the two clamped expressions
                        # through (``probe_start = max(0, min(0.4d, d-120))``,
                        # ``second = min(max(0.7d, probe_start+120), d-120)``,
                        # both below) shows the non-overlap requirement
                        # (``second >= probe_start + 120``) only holds once
                        # ``d >= 400`` -- verified by direct evaluation of both
                        # expressions across the whole range, not just algebra
                        # (see the round-8 review). Below 400s (which fully
                        # covers the 120-240s range this comment used to name,
                        # but also the 240-400s range it missed) the reserved
                        # gap can't fit a second non-overlapping window at
                        # all, and ``second_sample_is_usable``'s explicit
                        # non-overlap check (below) is what actually keeps a
                        # too-close/identical resample from being trusted as
                        # corroboration in that range, rather than this
                        # reservation alone.
                        probe_start_seconds = max(
                            0.0,
                            min(
                                media_duration * _UNTRIMMED_LOUDNESS_PROBE_FRACTION,
                                media_duration - _SHORT_ASSET_SINGLE_SAMPLE_MAX_S,
                            ),
                        )
                        probe_duration_seconds = _UNTRIMMED_LOUDNESS_PROBE_CAP_S
                        allow_second_sample = True
                else:
                    # Item 66 round-6 (Opus review, point 1): the real
                    # duration is genuinely unknown (ffprobe unavailable or
                    # failed) -- round 5's fixed 120s/240s offsets were
                    # PROVEN wrong here: for anything shorter than 120s,
                    # BOTH blind offsets land past the asset's actual end,
                    # read as silence, and get misreported as a genuinely
                    # silent asset (measured: a real 67s/-10.9 LUFS clip
                    # reported as silent). Sample from the very start
                    # instead -- never past EOF for any asset with any
                    # audio at all -- and never corroborate/trust this
                    # single, uncorroborated sample as proof of silence:
                    # there is no independent second window to cross-check
                    # it against when the asset's true length isn't known.
                    probe_start_seconds = 0.0
                    probe_duration_seconds = _UNTRIMMED_LOUDNESS_PROBE_CAP_S
            loudness = self._loudness_checker(
                media_path=source_path,
                target_lufs=config.loudness_target_lufs,
                tolerance_lufs=config.loudness_tolerance_lufs,
                probe_start_seconds=probe_start_seconds,
                probe_duration_seconds=probe_duration_seconds,
                threads=_foreground_thread_cap(),
            )
            if (
                single_sample_is_conclusive
                and loudness.measured_lufs is not None
                and loudness.measured_lufs <= _LOUDNESS_SILENCE_FLOOR_LUFS
            ):
                # Item 66 round-6 (point 2 companion): the short,
                # known-duration asset's ONE sample already covers the
                # whole (or nearly the whole) file -- no second window
                # exists to corroborate against, so this reading alone is
                # trusted directly.
                silent_asset = True
            elif (
                allow_second_sample
                and loudness.measured_lufs is not None
                and loudness.measured_lufs <= _LOUDNESS_SILENCE_FLOOR_LUFS
            ):
                # Item 66 round-5 (Opus review, point 3): the round-4 shape
                # fell back to a WHOLE-FILE probe here -- measured 46.7s on
                # a 39-minute clip, exactly the kind of synchronous,
                # start-path-blocking work item 66 exists to close. Take a
                # SECOND bounded sample at a different offset instead
                # (``_UNTRIMMED_LOUDNESS_PROBE_FRACTION_2``, 70% into the
                # media) rather than a full decode. ``allow_second_sample``
                # (only True for the "long asset" branch above) guarantees
                # ``media_duration`` is known and positive here, and that
                # there is room for a window starting at least
                # ``_UNTRIMMED_LOUDNESS_PROBE_CAP_S`` after the first one
                # without running past EOF (round-6, point 2's overlap
                # fix). Only if BOTH independent samples land at the
                # silence floor is the asset treated as genuinely silent.
                assert media_duration is not None
                assert probe_start_seconds is not None  # untrimmed: always a concrete float
                second_probe_start = min(
                    max(
                        media_duration * _UNTRIMMED_LOUDNESS_PROBE_FRACTION_2,
                        probe_start_seconds + _UNTRIMMED_LOUDNESS_PROBE_CAP_S,
                    ),
                    media_duration - _UNTRIMMED_LOUDNESS_PROBE_CAP_S,
                )
                # Item 66 round-6 (point 1b): defense in depth -- a window
                # that would start at or past EOF is unusable, not silence,
                # however it got computed. The clamping above should always
                # keep this comfortably non-negative and within bounds; this
                # guard only disables corroboration if that arithmetic is
                # ever wrong, rather than trusting a past-EOF read.
                #
                # Item 66 round-7 (point 2, MEDIUM): also require genuine
                # non-overlap with the first window. Lowering
                # ``_SHORT_ASSET_SINGLE_SAMPLE_MAX_S`` from 240s to 120s (see
                # that constant's docstring) means this "long asset" branch
                # now also runs for assets as short as just over 120s, where
                # two full non-overlapping 120s windows cannot both fit --
                # exactly the "identical/overlapping, never genuinely
                # independent evidence" failure round-6 already fixed, but
                # (round-8 LOW fix) that gap actually runs up to just under
                # 400s, not 240s -- see the sibling comment above this
                # branch for the worked-out boundary. Without this check the
                # arithmetic above can compute a second window that starts AT
                # OR BEFORE the first one ends (or is identical to it), which
                # would count as "corroboration" while providing none.
                second_sample_is_usable = (
                    second_probe_start >= 0.0
                    and second_probe_start + _UNTRIMMED_LOUDNESS_PROBE_CAP_S <= media_duration
                    and second_probe_start >= probe_start_seconds + _UNTRIMMED_LOUDNESS_PROBE_CAP_S
                )
                if second_sample_is_usable:
                    _LOG.info(
                        "Loudness sample for %r measured at the silence floor "
                        "(%.1f LUFS) at %.1fs in; resampling at %.1fs in before "
                        "treating the asset as silent.",
                        source_path.name,
                        loudness.measured_lufs,
                        probe_start_seconds,
                        second_probe_start,
                    )
                    second_loudness = self._loudness_checker(
                        media_path=source_path,
                        target_lufs=config.loudness_target_lufs,
                        tolerance_lufs=config.loudness_tolerance_lufs,
                        probe_start_seconds=second_probe_start,
                        probe_duration_seconds=_UNTRIMMED_LOUDNESS_PROBE_CAP_S,
                        threads=_foreground_thread_cap(),
                    )
                    if second_loudness.measured_lufs is not None:
                        # Item 66 round-6 (point 4): only replace the first
                        # (floor) reading if the resample actually produced
                        # a measurement -- if the resample itself failed
                        # (e.g. an ffmpeg error), keep the first reading
                        # rather than overwriting it with an unmeasured
                        # result and raising below.
                        if second_loudness.measured_lufs <= _LOUDNESS_SILENCE_FLOOR_LUFS:
                            # Two independent samples, two different
                            # offsets, both at the floor -- treat as a
                            # genuinely silent asset: never normalize
                            # toward a target that isn't there.
                            silent_asset = True
                        loudness = second_loudness
            if loudness.status != "ok" and loudness.measured_lufs is None:
                raise SourcePrepareError(
                    f"Egress source {segment.label!r} could not be measured for loudness: "
                    f"{loudness.operator_action}"
                )
            normalized = False if silent_asset else loudness.status != "ok"
            if key is not None:
                # Persist the probe result immediately -- BEFORE any conform
                # runs -- so every other segment of this asset (this
                # prepare() call or a later one) skips the probe too, even
                # though the full-asset conform itself may still be a MISS.
                self._write_cache_meta(
                    key, loudness, normalized, media_duration_seconds=media_duration
                )

        # Untrimmed MISS: the full-asset conform IS what airs — conform it once,
        # directly into the cache, then emit from the cache (duration truncation
        # applied at playout or via stream-copy per engine capability).
        #
        # Item 66: this branch's conform runs SYNCHRONOUSLY on the automation
        # thread and blocks first ON_AIR (measured 8.5-12+ min on a fresh
        # station) -- only take it when the engine can actually make use of
        # the resulting untrimmed cache object via a playout-side trim
        # (``self._playout_trim_supported``). When the engine cannot trim at
        # playout (the GStreamer engine), fall through to the trimmed-MISS
        # branch below instead: it conforms only the wanted window
        # (``-t segment.duration_seconds``) straight to the prepared file --
        # bounded, not a whole-clip re-encode -- and (point 3) promotes that
        # same conform straight into the cache instead of scheduling a
        # redundant warm.
        if key is not None and not trimmed and self._playout_trim_supported:
            full_asset_cached_ts = self._conform_full_asset_into_cache(
                key,
                source_path,
                config,
                loudness,
                normalized,
                threads=_foreground_thread_cap(),
                media_duration_seconds=media_duration,
            )
            if full_asset_cached_ts is not None:
                return self._emit_prepared_from_cache(
                    full_asset_cached_ts,
                    segment,
                    source_path=source_path,
                    output_path=output_path,
                    loudness_status=loudness.status,
                    measured_lufs=loudness.measured_lufs,
                    normalized=normalized,
                )
            # Item 66 round-4 BLOCKER fix (Opus review, point 1): ``None``
            # means a background warm already holds this exact asset's
            # cache lock -- rather than block behind it (potentially tens
            # of minutes, see _conform_full_asset_into_cache's docstring),
            # fall through to the SAME bounded per-segment conform path the
            # GStreamer engine always takes. That path's own tail (below)
            # attempts a best-effort, non-blocking promotion afterward too.

        # Trimmed MISS (first-ever join-in-progress start), an untrimmed
        # miss on an engine that cannot trim at playout
        # (self._playout_trim_supported is False, e.g. GStreamer), OR (round-4)
        # an untrimmed miss on an engine that CAN trim at playout but whose
        # full-asset conform lock was already held by a concurrent warm:
        # either way conform only the wanted window straight to air -- bounded by
        # ``-t segment.duration_seconds`` in build_conform_source_args below,
        # never a whole-clip re-encode. Foreground (synchronous) conforms are
        # thread-capped rather than single-threaded or unbounded (point 2,
        # Opus review, measured on HALO): this call is reachable both on
        # first ON_AIR and on ``EgressDaemon._try_content_reload``'s
        # synchronous prepare while another channel may be on air
        # (``daemon.py`` around line 1839) -- fully serializing it
        # (233s/300s measured) regressed latency there, and leaving it fully
        # unbounded (36.6s/300s) risked starving everything else on the box.
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
            threads=_foreground_thread_cap(),
        )
        result = self._ffmpeg_runner(args)
        if result.returncode != 0:
            tmp_output_path.unlink(missing_ok=True)
            raise SourcePrepareError(
                f"Egress source {segment.label!r} could not be conformed; inspect FFmpeg output."
            )
        # Item 66 round-3 BLOCKER fix (Opus review): the per-plan file is
        # finished FIRST, unconditionally, before anything else touches the
        # cache. The previous round moved this same tmp file INTO the cache
        # and then copied it back OUT again for the per-plan output -- an
        # extra full-length copy on the blocking path, and if the cache
        # promotion raised (e.g. this entry alone exceeds
        # CIVICCAST_CONFORM_CACHE_GB), the per-plan file no longer existed
        # and the segment failed to air where it used to air fine. Now the
        # segment's own file exists and is ready to air before the cache is
        # touched at all.
        tmp_output_path.replace(output_path)

        if key is not None:
            # Item 66 round-7 (point 1, HIGH fix): an UNTRIMMED segment
            # (inpoint/outpoint both None) is NOT, by definition, the whole
            # asset -- D42 (source_plan.py's ``_segment_duration``, ``min(slot,
            # playable)``) makes an untrimmed segment's own ``duration_seconds``
            # SHORTER than the asset's real media length whenever the
            # schedule slot is shorter than the asset (a 30s slot on a 67s
            # asset produces a 30s bounded conform here, no inpoint/outpoint
            # attached, so ``trimmed`` reads False even though this output is
            # only a fragment). A round-6 BLOCKER promoted that fragment into
            # the persistent cache as if it WERE the whole asset; a later,
            # longer-slot airing of the same asset then hit this exact entry
            # and stream-copied ``-t`` past what it actually held -- dead air,
            # sticky until the entry's size/mtime changed. Only promote this
            # bounded conform directly when it demonstrably covers the whole
            # known media duration (the same tolerance ``source_plan.py``'s
            # own ``_covers_slot`` uses).
            #
            # Item 66 round-8 (HIGH fix): round-7's ``media_duration is None``
            # branch here still promoted -- reasoning that D42 can only ever
            # cap ``segment.duration_seconds`` below the real media length
            # when ``source_plan.py`` itself already knows the asset's
            # duration, so an untrimmed segment reaching here with an UNKNOWN
            # duration was "never capped by D42 to begin with." That
            # reasoning compares the wrong two sources: D42's own cap in
            # ``source_plan.py`` (``_segment_duration``/``_playable_duration``,
            # source_plan.py:523-543) reads ``asset.duration_seconds`` off the
            # DATABASE row, while ``media_duration`` here comes from THIS
            # call's own live ffprobe -- the two can and do disagree. Two real
            # reproductions on an 8s test asset (3s slot, then a 6s slot):
            # (a) ffprobe genuinely unavailable/failing for this call while
            # the DB row still carries a real (shorter) duration -- D42 caps
            # the segment to 3s off the DB row, this call's own probe fails,
            # ``media_duration`` reads ``None`` here, and the round-7 code
            # promoted the 3s fragment as the full 8s asset; (b) a TRIMMED
            # airing runs first and takes the sibling ``if trimmed:`` branch
            # above, which probes nothing (it seeks/duration-limits off the
            # segment's own inpoint/outpoint) and persists
            # ``media_duration_seconds=None`` via ``_write_cache_meta`` --  no
            # failure anywhere -- and the NEXT airing (untrimmed, slot-capped)
            # takes the meta-reuse branch near the top of this method, reads
            # that ``None`` back, and promotes ITS fragment as the whole
            # asset. Both are the exact "DB-known, ffprobe-unknown" poisoning
            # quadrant the round-7 comment dismissed. Fail closed instead:
            # ``media_duration is None`` now NEVER promotes here, regardless
            # of ``trimmed`` -- it always falls through to ``_schedule_warm``,
            # which conforms the WHOLE asset (not this bounded fragment) on a
            # background thread. That job builds its conform with
            # ``build_conform_source_args(segment=None, ...)`` -- no
            # ``-ss``/``-t`` at all (see that function's docstring) -- so
            # unlike this bounded fragment, its output genuinely IS the whole
            # file regardless of what ``media_duration`` measured. Once it
            # finishes, ``_promote_conform_into_cache`` marks the cache entry
            # ``full_asset_conform=True`` -- unconditionally, from the mere
            # fact of having been called (it does not itself measure
            # anything; see its own docstring) -- which is safe here only
            # because the caller reaching it (the warm job) is the one that
            # already guaranteed a trim-free, whole-file conform, never from
            # this unverified fragment. Follow-up (not done this round, listed
            # rather than silently deferred): thread the plan's own known
            # asset duration
            # (the DB row `source_plan.py` already read) through to the
            # segment/``PreparedSegment`` spec so this method stops
            # re-deriving it via a second, independently-fallible ffprobe at
            # all -- see the round-7 review notes for the suggested shape.
            is_full_asset_conform = (
                not trimmed
                and media_duration is not None
                and segment.duration_seconds >= media_duration - _FULL_ASSET_DURATION_TOLERANCE_S
            )
            if is_full_asset_conform:
                # This bounded conform's output already IS the full-asset
                # conform the persistent cache wants. Populate the cache from
                # the ALREADY-FINISHED, already-airing ``output_path`` via a
                # hard link (queuing a background copy instead if linking
                # fails -- e.g. a cross-volume layout) instead of moving it --
                # see ``_promote_finished_conform_into_cache``'s docstring for
                # the full round-4 shape: non-blocking on lock contention
                # (skipped rather than waited on), and any failure here is
                # logged and swallowed rather than raised -- the segment is
                # already safely on air regardless of whether this succeeds.
                self._promote_finished_conform_into_cache(
                    key,
                    output_path,
                    source_path,
                    loudness,
                    normalized,
                    media_duration_seconds=media_duration,
                )
            else:
                # A genuinely trimmed miss, OR an untrimmed-but-slot-capped
                # (D42) conform that is only a fragment of the asset -- this
                # window is NOT the whole asset, so warm the full-asset cache
                # behind it for later airings, same as before item 66.
                self._schedule_warm(
                    key,
                    source_path,
                    config,
                    loudness,
                    normalized,
                    media_duration_seconds=media_duration,
                )
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
    threads: int | None = None,
) -> list[str]:
    """Build FFmpeg args that conform one media source to the canonical profile.

    ``segment=None`` conforms the WHOLE asset (no ``-ss``/``-t``) — the
    persistent conform-cache unit; trim happens at playout via the ffconcat
    plan.

    ``threads`` (item 66, revised after Opus review): when given, caps the
    encode at that many threads (``-threads <N>``); ``None`` leaves ffmpeg's
    own default untouched. Warm-behind conforms (``_schedule_warm`` /
    ``_conform_full_asset_into_cache``'s default) pass ``threads=1`` so a
    background warm can never starve the on-air encoder. Synchronous
    (foreground) conforms pass ``_foreground_thread_cap()`` instead of
    either extreme -- the original item-66 fix's unconditional single
    thread measured 233s for a 300s foreground conform on HALO vs 36.6s
    fully unthrottled, an unacceptable regression on the synchronous
    start/content-reload path (``daemon.py``'s ``_try_content_reload``,
    which can run this call while another channel is genuinely on air).
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
