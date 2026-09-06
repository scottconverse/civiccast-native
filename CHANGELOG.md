# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This repository begins on 2026-08-20 with the native-Windows product extracted
from [`scottconverse/civiccast`](https://github.com/scottconverse/civiccast) at
**fresh history**. Entries before that date live in that repository's own
CHANGELOG; nothing was deleted there. See [`BRANCHES.md`](BRANCHES.md) for what
came across and what deliberately did not.

## [Unreleased]

`v1.0.0-beta.5` is the next candidate and the current owner-held unpublished
candidate; it does not change the `v1.0.0-beta.4` install story documented
below.

### Added

- **An operator switch for live captions: `Show live captions on air` on
  Setup > Station Profile** (`StationProfile.live_captions_enabled`, default
  on, `GET`/`PUT /api/staff/station/profile`, `setup_admin` to change). An
  activated native station sets `CIVICCAST_CAPTION_TAP=inline`
  unconditionally, so until now there was no way for an operator to stop live
  captioning on a box where it could not keep up. The switch is read on every
  caption scan, so it takes effect within one poll interval **without
  restarting a control plane that is on air**. While off, the tap transcribes
  nothing, blanks every channel's live caption file, reports
  `"state": "disabled"`, and deletes the forked audio instead of filing it as
  evidence. Captions on published recordings (the offline caption job, the
  legal requirement) are unaffected. `CIVICCAST_CAPTION_TAP=off` also forces
  live captions off and wins over the persisted value; the reverse is
  deliberately not true, so no environment value can re-enable captions
  against the operator's switch.

### Fixed

- **Live caption tap knob hardening: one channel at a time, bounded live ASR
  threads, a longer first pause after an overload (item 79).** MEASURED in
  the sandbox on candidate 3b: 10 "Caption tap overload" events, with
  GStreamer playout worker stalls clustered inside them -- the same root
  cause class as the tester's beta.4 soak, and PR #172's backoff alone was
  not enough. Three changes, all in `civiccast/captions/tap_worker.py` and
  `civiccast/captions/runtime.py`: (1) the live caption tap's per-scan
  concurrency bound is now a flat **one channel's ASR call in flight at a
  time, station-wide**, always -- tightened from "one channel per 8 CPUs,
  never more than 3" (override: `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`,
  unchanged). Read this as hardening, not as the mechanism that fixed the
  original field failure by itself: every channel already shares ONE speech
  recognition model instance built with CTranslate2's `inter_threads=1`, so
  the previous default of 3 never actually ran 3 concurrent inferences --
  that model-level queue was already serializing them. A station with more
  channels ON_AIR than this bound will spend most of a scan transcribing one
  channel while the others' backlog grows; once a channel's backlog exceeds
  `CIVICCAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS` its stale audio is
  **discarded**, not queued, and it is paused under the same exponential
  backoff as any other overload -- a 3-channel station will have live
  captions paused most of the time. (2) the speech recognition model used by
  the live tap now caps how many CPU threads it uses per channel (1 on a
  small station, up to 2 on a bigger one, never more, logged once when the
  tap starts alongside `cpu_count` and the channel concurrency bound;
  override: `CIVICCAST_CAPTION_TAP_CPU_THREADS`, clamped rather than fatal on
  a bad value, and capped at 2 with a warning if it asks for more, so a typo
  or an over-aggressive value cannot take an activated station off air or
  hand the live tap "every core" worth of threads. The existing, more
  general `CIVICCAST_WHISPER_CPU_THREADS` keeps its original fail-fast
  (raise) behaviour for recorded-meeting transcription, unchanged -- but for
  the **live tap specifically** it is now clamped the same way as the
  tap-only variable (a bad value warns and falls back instead of raising),
  its `0` ("every core") is refused regardless of which of the two variables
  asked for it, and a value above 2 is capped the same way. Recorded meeting
  transcription itself is untouched either way -- it still uses as many
  threads as the box allows. (3) the first pause after an overload is now
  twice as long (120 seconds instead of 60) so a station that just proved it cannot
  keep up gets real recovery time before speech recognition is attempted
  again. Does not add any new cross-module wiring to the stall watchdog --
  that stays a separate, medium-risk item. `scripts/prove_native_caption_capacity.py`'s
  `--cpu-threads`/`--beam-size` flags now default to the same live sizing
  production ships, and the proof constructs its runtime with `live=True`, so
  an unoverridden capacity-proof run measures the actual deployed
  configuration instead of a station nobody ships.
- **First ON_AIR no longer waits for a whole-clip re-encode (item 66).**
  MEASURED: a fresh station took 8.5-12+ minutes to first ON_AIR because
  `civiccast/egress/preparer.py`'s `_prepare_segment` conformed the WHOLE
  first asset synchronously on the automation thread before the channel
  could start, and every channel queued behind that one conform. An initial
  pass at this fix also tried making the synchronous conform single-threaded
  (`-threads 1`) or fully unthrottled, and probing loudness once per
  segment; an Opus review measured both of those choices on real hardware
  (HALO) and found real regressions, so the shipped fix is different from
  that first pass. What actually ships, all measured on HALO:
  - **A foreground thread cap, not `-threads 1` and not unthrottled.**
    Conforming 300s of content took 233s at `-threads 1` vs 36.6s fully
    unthrottled — serializing every synchronous conform to one thread (the
    first pass's fix) was itself the kind of regression item 66 exists to
    close, and it's reachable outside first-ON_AIR too:
    `EgressDaemon._try_content_reload` (`daemon.py` around line 1839) runs
    this same synchronous conform on the automation thread on the legacy
    ffmpeg-concat engine while ANOTHER channel may genuinely be on air, so
    fully unthrottled isn't safe there either. `build_conform_source_args`
    now takes a `threads: int | None` argument instead of a `background:
    bool` flag: warm-behind conforms (`_schedule_warm`) still pass
    `threads=1` (a background warm must never starve the on-air encoder),
    but every SYNCHRONOUS conform — first-ON_AIR and the content-reload path
    above — now passes a cap of `max(1, os.cpu_count() // 2)` instead. This
    is a real behavior change for `playout_trim_supported=True` (the legacy
    ffmpeg-concat engine): its synchronous untrimmed-MISS conform used to run
    fully unthrottled and is now thread-capped too.
  - **Loudness probing is memoized per asset, not per segment.** A
    `ebur128` loudness pass on a 39-minute clip took 46.7s (it decodes video
    too — `check_loudness` in `civiccast/stream/loudness.py` now passes
    `-vn`, audio-only decode, cutting that cost). An 8-segment plan of one
    asset (8 distinct trims of the same recording) used to mean 8 full-file
    probes — ~6.3 minutes, still on the synchronous start path. `_prepare_segment`
    now consults the persisted cache meta (`_read_cache_meta`, keyed by the
    same source fingerprint `_cache_key` uses) BEFORE probing; a miss probes
    once and writes the meta immediately — even before any conform for that
    asset exists — so every other segment of the same asset, in this
    `prepare()` call or a later one, reuses it instead of re-probing.
  - **An untrimmed foreground conform now populates the cache by LINKING
    the already-finished per-plan file into it, never by moving it.**
    Untrimmed segments are the full asset by definition (`source_plan.py`'s
    untrimmed-segment contract) — on the GStreamer engine an untrimmed
    MISS's bounded conform (`-t <duration>`) IS already a full-asset
    conform. A round-2 version of this fix finished that conform into the
    persistent cache FIRST and then copied it back OUT for the per-plan
    file — an extra full-length copy on the blocking path, and if the cache
    promotion raised (the entry alone exceeds `CIVICCAST_CONFORM_CACHE_GB`),
    the per-plan file no longer existed and the segment failed to air where
    it used to air fine. An Opus review caught both problems. The per-plan
    file is now finished FIRST, unconditionally (`tmp_output_path.replace
    (output_path)`), and airs from itself; the cache is populated
    afterward via `_promote_finished_conform_into_cache` — a hard link
    (`os.link`) of that SAME already-airing file into
    `conform-cache/{key}.ts.tmp`, then the existing atomic rename.
  - **The link/lock design in the paragraph above went through FOUR more
    measured rounds of Opus review after it first shipped:**
    - **Round 4, BLOCKER:** the lock guarding that promotion (and the
      matching lock in `_conform_full_asset_into_cache`, used on the
      `playout_trim_supported=True` engine) was still acquired BLOCKING. A
      background warm holds the identical lock for its ENTIRE
      single-threaded conform — tens of minutes for a long asset — so a
      synchronous `prepare()` landing behind an in-progress warm for the
      SAME asset stalled for just as long (measured: 3.01s against a
      3-second fake warm in the regression test). Both lock sites now
      acquire NON-BLOCKING: on contention, the promotion is skipped
      (logged) and the untrimmed-miss path falls through to the bounded
      per-segment conform instead of waiting — the segment already airs
      from its own file either way. `_schedule_warm`'s queued job also
      re-checks `{key}.ts` (and a fresh meta) right before doing any work,
      so a job that sat in the single-worker warm queue while a foreground
      promotion already populated the same entry skips its now-redundant
      re-conform instead of racing it.
    - **Round 4, point 3:** the `shutil.copy2` fallback (when `os.link`
      fails, e.g. the cache and per-plan directories live on different
      volumes) was still a full synchronous byte-for-byte copy on the
      start path — the same class of blocking work item 66 exists to
      close. It was handed to the warm scheduler
      (`_schedule_cache_copy_promotion`) as a queued background job.
    - **Round 5, BLOCKER:** round 4's fix for the point above scheduled
      that background job from INSIDE the still-held per-key lock, and the
      queued job itself blocking-acquired the SAME lock — with a
      SYNCHRONOUS `warm_scheduler` (a test double, or any future
      non-threaded integration) the job ran inline, before the caller's
      own `finally: lock.release()` could ever execute: a reproducible
      self-deadlock. With the real threaded scheduler it was head-of-line
      blocking of the single warm worker on a lock its own caller still
      held. Fixed: `_promote_finished_conform_into_cache` now releases its
      lock FIRST (in `finally`) and only schedules the copy job
      AFTERWARD; the queued job's own lock acquisition is now also
      non-blocking (skip on contention rather than wait or busy-loop
      re-queuing itself).
    - **Round 6, point 7:** if handing the job to `self._warm_scheduler`
      itself raised (the job "discarded" before it ever ran, e.g. a broken
      or test-double scheduler), `key` was left stuck in `self._warming`
      forever — silently suppressing every future GENUINE warm for that
      asset. Both `_schedule_warm` and `_schedule_cache_copy_promotion` now
      catch that failure, discard the key, and log instead of leaving it
      stuck. Point 5: the copy job's OUTER exception handler (covering
      every failure other than a failed `shutil.copy2` itself, e.g.
      `_promote_conform_into_cache`'s own over-budget raise after the copy
      already succeeded) now also unlinks its partial `.ts.tmp` — only the
      inner handler did before.
    Any failure in cache promotion (including the over-budget case) is
    still logged and swallowed, never raised: the segment is already
    safely on air regardless, and only the NEXT airing of that asset
    misses the cache and re-conforms. TRIMMED misses are unchanged: bounded
    conform straight to air, full-asset warm scheduled behind it.
  - **The warm scheduler is a single-worker FIFO queue, not one thread per
    job.** `_default_warm_scheduler` used to spawn an unbounded daemon
    thread per warm job; it now queues onto one long-lived background
    worker, so at most one warm conform (or cache-copy promotion, above)
    runs at a time regardless of how many distinct assets are warming. The
    existing per-key dedupe (`self._warming`) is unchanged, and now shared
    between the two job kinds.
  - **The loudness probe is now bounded to a window, not the whole file --
    and, since round 4 (corrected round 5), not the HEAD of an untrimmed
    asset either.** A trimmed segment probes exactly its own wanted window
    (`-ss <inpoint>` before `-i`, `-t <duration>` after it — the same
    convention `build_conform_source_args` uses). An untrimmed segment (the
    full asset) samples 120 seconds starting 40% into the asset's REAL
    MEDIA DURATION instead of its whole duration -- the initial round-3
    shape sampled the HEAD instead, and an Opus review found a real failure
    mode: a cold-open with silence or room tone measures the silence floor
    instead of the program's real loudness, which then drives `loudnorm`'s
    normalization target completely wrong and gets memoized for every
    other segment/airing of that asset. A round-4 version of the 40%
    offset used `segment.duration_seconds` for "the asset's duration" --
    wrong: `source_plan.py`'s `_segment_duration` returns
    `min(slot, playable)` (or the bare schedule SLOT for an un-probed
    asset), so a slot shorter than the asset placed the sample past the
    asset's actual EOF (measured: a past-EOF `-ss` reads as silence -> -70
    LUFS -> an unnecessary floor fallback). Round 5 uses the asset's REAL
    media duration instead -- a cheap ffprobe `-format` query (never a
    decode), cached in the same meta as the loudness result -- and clamps
    the 40% offset so it can never land past EOF even for a short asset.
    If the mid-file sample itself measures at or below -60 LUFS integrated
    (still silence -- e.g. a pause that happens to land in the sampled
    window), a round-4 version fell back to a synchronous WHOLE-FILE probe
    (measured 46.7s on a 39-minute clip) -- exactly the kind of
    start-path-blocking work item 66 exists to close. Round 5 replaced that
    with a SECOND bounded sample at a different offset (70% into the real
    media duration, still 120 seconds).
    **Round 6 found two more real bugs in that round-5 shape, both PROVEN
    on real clips:** (1) when the real duration is genuinely UNKNOWN
    (ffprobe unavailable or failed), round 5 still sampled at fixed 120s
    and 240s offsets — for a real 67-second clip (true loudness -10.9
    LUFS) BOTH offsets land past the clip's actual end, read as silence,
    and the asset was misreported as genuinely silent. Round 6 samples
    from 0s instead when duration is unknown (never past EOF for any
    asset with real audio), and never trusts that single,
    uncorroborated sample as proof of silence. (2) round 5's "second,
    different offset" sample was actually IDENTICAL to the first for any
    asset <=200s and OVERLAPPED it for up to 400s — never genuinely
    independent evidence. Round 6 takes exactly ONE sample (0s, spanning
    `min(duration, 120s)`) for any asset <=240s instead (trusted directly
    as silence if it hits the floor — that one sample already covers the
    whole, or nearly the whole, file); above 240s, the two samples are
    placed and clamped so the second always starts at least 120s after
    the first, guaranteeing no overlap. If the resample itself fails to
    produce a measurement at all, the first (floor) reading is kept
    rather than raising or silently discarding it.
    `check_loudness`/`check_streaming_loudness` gained optional
    `probe_start_seconds`/`probe_duration_seconds`/`threads` parameters for
    this (`None` for every OTHER caller, still measuring the whole file,
    unthrottled, unchanged); `_prepare_segment` now passes `threads=` on
    every probe (round 6, point 6 — a production caller now exercises the
    arg-order fix below, not just its own unit tests). This remains a
    documented sample, not a full-file measurement, for material whose
    loudness varies significantly across its length — the persisted-meta
    memo above still means one asset gets one measured value shared
    across every segment/airing of it, which was already this codebase's
    model before item 66 (the cache key never depended on trim). The
    asset's real media duration is threaded explicitly through every
    conform/promotion call site that writes cache meta (round 6, point 3)
    instead of `_write_cache_meta` doing a defensive read-modify-write on
    every single write to avoid losing it.
  - **`-threads`'s position in `check_loudness` was an OUTPUT option, not
    an input one (round 5).** Round 4 placed `-threads <N>` after `-i`/
    `-t`, which ffmpeg parses as applying to the `-f null` output --
    capping nothing about the actual decode or filter graph. It now comes
    BEFORE `-i` (an input/decoder option), paired with
    `-filter_complex_threads <N>` to also cap the `ebur128` filter graph's
    own threading, which `-threads` alone never bounded.
  - **`_evict_cache_over_budget` now reaps orphaned cache-dir files** that
    no other path here ever cleaned up: an abandoned `{key}.ts.tmp` (a
    conform or promotion interrupted mid-write) older than 1 hour is
    deleted outright, and a live one still counts toward the budget so a
    burst of concurrent warms/promotions can't blow past
    `CIVICCAST_CONFORM_CACHE_GB` before finishing; a `{key}.json` with no
    sibling `{key}.ts` (a loudness-only probe whose conform never followed)
    older than 24 hours is deleted outright. `_write_cache_meta`'s sidecar
    write is now tmp+replace atomic, matching every `.ts` write in this
    module. `os.utime(cached_ts)` on a cache HIT is now guarded against
    `FileNotFoundError` (a concurrent eviction pass removing the entry
    between the existence check and the utime call) and falls through to a
    MISS instead of crashing. A failed/partial background copy (in the
    cross-volume job above) now unlinks its own partial `.ts.tmp` instead
    of leaving it for the orphan reap to find later.
  - **`cli.py`'s CLI-driven worker now passes `playout_trim_supported`
    too.** Its `SourcePreparer(work_dir=work_dir)` construction was missing
    the argument entirely (silently defaulting to `False`, the
    GStreamer-engine shape, even when running the legacy ffmpeg-concat
    engine) — `automation.py`'s in-app driver already wired this correctly;
    the CLI path now imports the same `gstreamer_engine_selected` helper
    and mirrors it.
  See `docs/ops/channel-egress-runbook.md`'s corrected "Cache HIT accuracy vs
  MISS accuracy" note (an untrimmed asset's cache entry is a link -- or, on
  a cross-volume layout, a background copy -- of the exact file that
  already aired, so it is byte-identical, not a separately-produced copy),
  its new "Cache promotion never waits behind an in-progress warm" note,
  and its corrected "loudness probe" note describing the sampling window
  (40%/70% of the asset's REAL media duration, not its schedule-slot
  duration, with a single-sample shape for assets at or below 240s and a
  never-trust-a-single-blind-sample rule when duration is unknown).
  **Round 7 found two more real bugs, both PROVEN with a reproduction, in
  the round-6 shape above:**
  - **HIGH: an "untrimmed" segment is NOT, by definition, the whole asset.**
    Round 6's own line above ("untrimmed segments are the full asset by
    definition") was wrong once D42 (`source_plan.py`'s `_segment_duration`,
    `min(slot, playable)`) shipped: a schedule slot shorter than its asset
    makes an untrimmed segment's `duration_seconds` shorter than the
    asset's real media length too, with no inpoint/outpoint attached to
    show it. `_promote_finished_conform_into_cache` still hard-linked that
    SHORT bounded conform into the persistent cache as if it were the whole
    asset; a later, longer-slot airing of the same asset then hit that
    entry and stream-copied `-t <longer duration>` from a file that didn't
    have that much content — dead air, sticky in the cache until its
    size/mtime happened to change. Reproduced: a 30-second schedule slot on
    a 67-second asset, followed by a 60-second slot on the same asset.
    Fixed at both ends: the promotion is now gated on the bounded conform's
    own `duration_seconds` actually covering the asset's real media
    duration (the same 1-second tolerance `_covers_slot` uses) — if it
    doesn't, the full-asset cache is warmed behind it instead, exactly like
    a genuinely trimmed miss already was. (A genuinely UNKNOWN real duration
    — the preparer's own ffprobe unavailable or failing for this call —
    keeps the pre-round-7 "trust untrimmed as full" assumption rather than
    force every such segment through an extra, unverifiable warm: D42 itself
    can only shorten a segment's duration below the real media length when
    the asset's duration is KNOWN, so an untrimmed segment reaching this
    gate with a genuinely unknown duration was never capped by D42 to begin
    with.) The cache **read** side no longer
    trusts `{key}.ts` on `duration_seconds` arithmetic either (a short
    entry's meta still reports the asset's correct real length, so a
    numeric comparison alone can't tell a genuine full conform apart from a
    stale short one) — `_write_cache_meta` gained an explicit
    `full_asset_conform` flag, set ONLY by `_promote_conform_into_cache`
    (the one place a `.ts` is ever finalized into the cache), and a cache
    HIT now requires that flag to be `True`. A `{key}.json` written by
    pre-round-7 code never carries it, so an already-corrupted on-disk
    entry from before this fix self-heals into a MISS (and gets correctly
    re-conformed) instead of staying silently wrong.
  - **MEDIUM: a single HEAD sample was trusted as conclusive silence for
    assets up to 240 seconds, even though the sampled window only covers
    120 of them — reintroducing the exact round-4 head-silence failure for
    that range.** Reproduced: a 200-second clip whose only audio starts at
    130 seconds (well past the sampled `[0, 120)` window) got memoized as
    silent, and normalization was skipped. The single-sample-conclusive
    cutoff (`_SHORT_ASSET_SINGLE_SAMPLE_MAX_S`) is now the probe window's
    own size (120s, not 240s) — a "duration known" asset over 120 seconds
    always falls into the sampled-window branch instead (40% in, not the
    head), which happens to cover the 130-200s range in the reproduction
    above. That branch's corroborating resample also gained an explicit
    non-overlap check (`second_probe_start >= first + 120s`): lowering the
    cutoff means the 120-240s range can now reach that branch too, where
    two full non-overlapping 120-second windows don't always fit — without
    the check, an overlapping/identical resample could count as
    "corroboration" while providing none, exactly the failure round-6
    already fixed for durations above 240s.
  - Doc-only: `civiccast/stream/loudness.py`'s `check_streaming_loudness`
    docstring claimed its `probe_start_seconds`/`probe_duration_seconds`/
    `threads` parameters were "not currently exercised by any caller" —
    false since round 6 shipped: `_prepare_segment` passes `threads=` on
    every probe (see above) and `probe_start_seconds`/`probe_duration_seconds`
    on every untrimmed/trimmed probe alike. Corrected.
  See `docs/ops/channel-egress-runbook.md`'s corrected loudness-probe note
  (the single-sample cutoff is 120s, not 240s, and the 120-240s range's
  resample is skipped rather than trusted when no non-overlapping window
  fits).
  **Round 8 found the round-7 HIGH fix was still not fixed, reproduced
  twice with real ffmpeg on an 8-second test asset (a 3-second slot, then a
  6-second slot):**
  - **HIGH: `media_duration is None` still promoted a slot-capped fragment
    as the full asset.** Round 7's fallback reasoned that D42's own cap in
    `source_plan.py` can only shorten a segment's `duration_seconds` below
    the real media length when that file's `_playable_duration` already
    knows the asset's duration — so an untrimmed segment reaching the
    promotion gate with an UNKNOWN `media_duration` was "never capped by
    D42 to begin with," and kept promoting it. That compares the wrong two
    sources: D42's cap reads the asset's duration off the **database row**
    (`source_plan.py:523-543`); `media_duration` in the preparer comes from
    **this call's own live ffprobe**. The two can disagree, and disagree in
    exactly the poisoning direction (DB knows the duration, ffprobe
    doesn't): (a) ffprobe genuinely fails for one call while the DB row
    still caps the segment to 3 of the asset's 8 seconds — the 3-second
    fragment got promoted as the whole asset; (b) with no failure at all —
    a TRIMMED airing runs first, takes the sibling probe branch that never
    calls `probe_media_duration_seconds` at all, and persists
    `media_duration_seconds: null`; the very next airing (untrimmed,
    slot-capped to 6 of 8 seconds) reads that cached `null` back and
    promotes its own fragment as the whole asset. `media_duration is None`
    now **never** promotes — it always falls through to `_schedule_warm`,
    whose background job conforms with `build_conform_source_args(segment=
    None, ...)` — no `-ss`/`-t` at all — so its output genuinely is the
    whole file regardless of what `media_duration` measured, unlike this
    unverified fragment. `_promote_conform_into_cache` then marks the entry
    `full_asset_conform=True` unconditionally (it measures nothing itself);
    that is safe here only because the caller reaching it already
    guaranteed a trim-free, whole-file conform. Threading the plan's
    already-known (DB) asset duration through to the segment spec so the
    preparer stops re-deriving it via a second, independently fallible
    ffprobe is a listed follow-up, not done this round.
  - **MEDIUM: the warm/copy-job skip checks didn't require the
    `full_asset_conform` flag.** `_schedule_warm`'s and
    `_schedule_cache_copy_promotion`'s own re-check-before-running guards
    (added round-4/round-6 to skip redundant work if another caller already
    populated the entry) accepted ANY meta file as "already populated," so
    a flagless legacy entry (anything written before round 7) read as a
    hit and the job returned without ever conforming — the asset never
    healed: every future airing kept paying the foreground conform, and the
    stale short `.ts` stayed in the eviction budget forever. Both guards
    now require `meta.get("full_asset_conform") is True`, matching the
    cache-HIT check round 7 already applied on the read side.
  - **LOW: the "no room for a corroborating resample" comment named the
    wrong cutoff.** With `probe_start = max(0, min(0.4·d, d−120))` and the
    non-overlap requirement `second_probe_start >= probe_start + 120`,
    working both clamped expressions through (not just describing them)
    shows corroboration is actually unavailable for every asset under 400
    seconds, not 240 — the fail-safe *behavior* was already correct
    (skip the resample, keep the single reading), only the documented
    boundary was wrong. Corrected in this file, the runbook, and the
    in-code comments; no behavior change.
  **Round 9 was tests/wording only — both round-8 functional fixes (the
  warm/copy skip-predicate MEDIUM and the fail-closed HIGH gate) were
  already correct, just uncovered:**
  - **MEDIUM: added a mock-level test per job** (`_schedule_warm`'s and
    `_schedule_cache_copy_promotion`'s own queued `_job`) that plants a
    flagless legacy meta plus a short `.ts`, runs the job, and asserts it
    re-conforms (does not return early) with the resulting cache entry
    carrying `full_asset_conform=True` — reverting either skip predicate
    back to `cached_meta is not None` now fails the suite instead of
    passing silently.
  - **MEDIUM: added a mock-level (no-ffmpeg) test of the HIGH fail-closed
    gate** — an untrimmed, slot-capped segment with an unknown media
    duration now asserts `_schedule_warm` is called and nothing is
    promoted, catching a revert of `is_full_asset_conform`'s
    `media_duration is not None` clause without needing real ffmpeg on the
    runner. Also wired `tests/egress/test_preparer_conform_cache_real_ffmpeg.py`'s
    four tests into `ci-test.yml`'s junit-floor guard pattern (matching the
    existing `tests/live/test_finalization_worker` and live-HLS guards), so
    CI fails if they were skipped (no ffmpeg/ffprobe on the runner) rather
    than silently passing.
  - **LOW: corrected a false invariant in a code comment and this file.**
    Both claimed the warm job "sets `full_asset_conform=True` from its own
    measured length via `_promote_conform_into_cache`" — that method sets
    the flag unconditionally and measures nothing. The real invariant is
    that the warm job's conform always builds with
    `build_conform_source_args(segment=None, ...)`, emitting no `-ss`/`-t`,
    so its output is genuinely the whole file regardless of what
    `media_duration` measured; `_promote_conform_into_cache`'s unconditional
    flag write is safe only because of that guarantee, not because it
    verified anything itself.
  - **LOW: `docs/ops/channel-egress-runbook.md`'s "for a 120-400 second
    asset that room may not exist" line now says plainly that below 400s a
    second sample never fits at all**, plus two new operational notes: a
    broken ffprobe queues a single-threaded background whole-asset conform
    for every slot-capped untrimmed airing until it heals (bounded by the
    warm dedupe; can mean a long first-run queue on a GStreamer station with
    many assets), and upgrading past this fix invalidates every
    pre-existing conform-cache entry (flagless reads as a miss), so each
    asset pays one re-conform after upgrade — synchronous on the start path
    when `playout_trim_supported=True`.
- **A seamless plan rollover collided its own concat aggregators, silently
  failed to join the pipeline, and was acked "applied" anyway -- so
  automation kept re-triggering it forever while the channel bounced.**
  MEASURED on real hardware (2026-09-06, clean install of `609273d`, three
  GStreamer channels): the first seamless plan rollover
  (`daemon._try_content_reload` -> `strategy.reload_content` -> the D2
  worker-pipe seam -> `engine.reload_program`) was followed by
  `CTRL stall: no output for 10s` worker relaunches every ~30s on every
  channel. Root cause (H1): `bridge.graph_from_config`/`reload_content`
  always build the program leg as a `PlaylistLeg` labeled `"program"`, and
  `engine._build_playlist` named its `concat` aggregators with the bare
  label (`vconcat_program`/`aconcat_program`) on every build -- a reload's
  rebuilt aggregators therefore collided with the still-live outgoing leg's
  same-named aggregators while both were in the pipeline. GStreamer's
  `Gst.Bin.add()` silently REFUSED the duplicate name
  (`"Name 'vconcat_program' is not unique in bin ... not adding"`) and the
  discarded return value let the new leg's elements dangle unlinked: its
  readiness probes never fired, `_on_reload_timeout` aborted the reload
  every time (`reload_timeout_s=10.0`), and `worker.py`'s D2 pipe dispatch
  acked the `reload` command `"applied"` the instant `reload_program`
  *returned* -- before the reload had committed or even had a chance to --
  so the daemon believed every rollover had landed and automation
  re-issued it every cadence tick, forever. A second measured root cause
  (H5) also contributed on the tester: `preparer.prepare()` wrote every
  content-reload's non-cache-hit prepared segment to a FIXED path keyed
  only by the segment's index within its own call
  (`<channel>/prepared/segment-NNNN.ts`), never by which plan the call was
  preparing -- for the GStreamer engine (`playout_trim_supported=False`) a
  reload's prepare wrote directly over the exact file the CURRENTLY LIVE
  worker's `filesrc` was still reading, with no GStreamer warning, only a
  downstream stall. Four independent fixes, all in this change:
  - `engine.py`'s `_make` now checks `pipeline.add()`'s return value and
    raises `RuntimeError` naming the refused element instead of silently
    proceeding; `reload_program`'s existing build-error handling aborts the
    in-flight reload cleanly on that raise (the current program keeps
    playing).
  - `_build_playlist` now names each build's aggregators with a monotonic
    `self._source_leg_seq` (`vconcat_<label>_<seq>`/`aconcat_<label>_<seq>`,
    mirroring the existing `_overlay_layer_seq` pattern) so a reload's
    rebuilt aggregators never collide with the leg they are replacing.
  - `reload_program` gained an optional `on_settled` callback, invoked
    exactly once when the reload actually commits or aborts.
    `worker.py`'s D2 pipe dispatch acks a `reload` command `"armed"`
    SYNCHRONOUSLY the instant `reload_program` returns without raising (the
    command was accepted; the new leg is building/prerolling) -- a first
    attempt at this fix made the ack wait for `on_settled` to fire instead,
    which just moved the dishonesty: a DEFERRED/boundary-aligned switch (an
    automation-driven ON_AIR extension, `reload_policy.should_defer_switch`)
    can take up to `defer_switch_timeout_s` (900s default) to settle, so that
    ack would have blocked far longer than any pipe round trip should, and
    the strategy's bounded ack wait would time out on a correctly-armed
    long-lead reload and the daemon would terminate a perfectly healthy
    worker. The reload's eventual settle outcome
    (`"applied"`/`"aborted:<reason>"`) is instead reported OUT-OF-BAND via
    `reload-status.json` (`worker.py`'s `_write_reload_status`), polled once
    per automation tick by the new `EgressDaemon._poll_reload_settlement`
    (added to `process_once`'s poll set) -- `_try_content_reload` now only
    ARMS a reload and records a `_PendingReloadSettlement`; the ON_AIR
    proof-event/state bookkeeping (`_commit_reload_settlement`) runs only
    once settlement is actually observed, and a settlement that never
    arrives within a generous backstop deadline (`
    _PENDING_RELOAD_SETTLE_DEADLINE_S`, 960s) falls back to the daemon's
    terminate+restart path, same as an immediately-declined reload always
    did. The strategy's ack wait for `reload` is therefore back to the SAME
    small default every other verb uses. The daemon also now logs a WARNING
    naming the channel and the reason whenever a seamless reload is declined
    or fails to settle
    (`GstPlayoutStrategy.last_send_command_failure_reason`), where before
    `if not applied: return False` had no log line at all. **Known
    consequence, not a bug**: while a reload is armed but genuinely still
    settling, the channel's state row stays at whatever it was before the
    reload (honest -- the physical output has not switched yet either); with
    the seamless path OFF (the beta.5 default below), a plan rollover instead
    shows `TRANSITIONING` from the moment automation triggers the rollover
    check (well before the current item's natural end, by design -- see
    `reload_policy.rollover_trigger_at`) until the item actually ends and the
    restart lands, even though the channel is airing normally the whole time.
  - `preparer.py`'s `prepare()` now writes every call's prepared segments
    into their own uniquely-named subdirectory
    (`<channel>/prepared/<uuid>/segment-NNNN.ts`) so two `prepare()` calls
    can never share an output path; the two direct-ffmpeg write sites
    (cache-hit stream-copy, trimmed-miss conform) now write to a `.tmp`
    sibling and rename into place atomically, matching the existing
    full-asset-cache write's pattern. GC is now keep-3-most-recent-plans
    first (never swept regardless of age or size), then a byte budget, then
    a 24h age floor as a last resort -- plus an explicit `release()` the
    daemon calls the moment it independently knows a plan is retired (a
    just-settled reload's predecessor, or a channel's active plan on
    operator stop), and a plan whose every segment never triggers a local
    write (all-live, or every segment a `playout_trim_supported` cache hit)
    leaves no directory behind at all.
  - **Known issue: the seamless in-place rollover is disabled by default in
    beta.5, pending a fresh hardware soak.** All fixes above are
    unit-tested, but the seamless path itself has not yet been RE-PROVEN on
    real hardware since they landed. `GstPlayoutStrategy.supports_content_reload`
    now defaults to `False` (env `CIVICCAST_EGRESS_SEAMLESS_RELOAD=1` to opt
    back in); a channel with it off falls back to the daemon's existing
    terminate+restart reload path at every plan rollover instead of the
    in-place swap. Cost of the fallback: one encoder restart per plan
    rollover -- a rounding error for a normal 10-40 minute program item, but
    roughly one restart every ~30 seconds for a rapid 30-second-item
    test/demo schedule -- and, per the TRANSITIONING note above, the state
    row reads `TRANSITIONING` for that whole rollover-trigger-to-natural-end
    window even though playout itself never glitches.
  - **Second-round hostile-review fixes (same branch):** an armed-but-not-
    yet-settled reload's tracking (and its prepared-plan directory) is now
    released on every worker-exit path (a crash mid-settle no longer fires a
    spurious restart 960s later against a channel that already moved on, and
    a late-arriving settlement for a dead attempt is logged as ignored
    instead of silently doing nothing), on a fresh restart, and when a newer
    reload supersedes a still-pending one (the previous code silently leaked
    the superseded attempt's directory). `ChannelAutomationService`'s
    45-second "did the reload land" retry now checks the daemon's own
    "armed, still settling" signal first, so a legitimately-settling deferred
    reload (~120s+ before its `current_proof_event_id` changes) is never
    retried out from under itself (previously: a re-prep, a superseded leg,
    and another prepared-plan directory every ~45s while it was still
    healthy). `SourcePreparer`'s GC now also protects every directory the
    daemon reports as live (not just the keep-N-most-recent heuristic), and
    the `_start` path -- not just the seamless-reload path -- tracks and
    releases its own prepared-plan directory, so the fallback-flag-off
    (shipped) default gets the same cleanup. The POSIX FIFO control channel
    now reports reload settlement too (it previously never did, so a FIFO-
    dispatched reload always waited out the full 960s deadline and fell back
    to restart regardless of whether it actually landed). Automation's own
    reload dispatch remains synchronous on its shared poll thread, now
    bounded by the ~5-second "armed" ack instead of up to 900 seconds (F5 --
    documented, not eliminated; a dedicated dispatch thread per channel would
    remove even that bound but is a separate change).
- **A channel-automation pass that blocked for a long time (e.g. a cold
  content prepare inside a channel's own start) could freeze a channel's
  plan-rollover horizon in the past and make it roll over forever, and a
  worker that kept crashing right after a rollover could get hit with an
  unthrottled re-arm every second (item 78).** Four related fixes in
  `ChannelAutomationService`/`reload_policy`/the daemon:
  - Wall-clock "now" is now read fresh for EACH channel's pass, AFTER that
    channel's own poll work runs (not before it) -- reading it any earlier
    left the channel that actually blocks still computing its own
    rollover math against a timestamp captured before the block, which is
    the exact scenario that was freezing the horizon in the past.
  - If a channel's tracked plan horizon has already ended by wall clock
    (`plan_end_at` at or before "now") by the time it is checked, it is now
    discarded and re-established from the channel's current plan instead of
    being used to justify another dispatch. This stops the runaway
    rollover-forever failure, but it is not free: re-anchoring to "now"
    also pushes the NEXT trigger point later than it would otherwise have
    been, since the new plan is windowed from a later starting point --
    safe, but a real behavior change worth knowing about, not a free
    correction. (`tests/egress/test_automation.py`'s
    `TestRolloverCadence.test_the_flat_floor_bug_the_scaled_floor_fixes`
    measures this concretely: it deliberately reproduces an OLDER, already-
    fixed cadence-floor bug from D43 to compare against the shipped,
    scaled floor, and this PR's stale-horizon re-anchor changes the
    reproduced bug's own worst-case lead from -180s to -360s. The negative
    lead itself is that older bug, not this PR's doing -- the shipped floor
    the test compares against is unaffected -- but the re-anchor measurably
    changes how that unrelated, deliberately-reintroduced bug plays out.)
  - The 45-second "did the last rollover reload actually land" retry path
    used to be completely unthrottled; it now refuses to dispatch to a
    worker whose process has been alive less than 60 seconds (giving a
    freshly relaunched worker room to settle before another synchronous
    prepare is thrown at it), and separately enforces its own 60-second
    minimum gap between CONSECUTIVE retries (measured from the last retry
    dispatch, not the original one, which is what makes this floor
    actually bind instead of always being satisfied already by the 45-
    second timeout that gates entry to the retry path in the first place).
    Degrade mode, unchanged by this fix: a worker that keeps relaunching
    faster than a rollover's own boundary-aligned trigger delay never keeps
    a horizon tracked long enough to fire one at all (every relaunch resets
    it -- see the "not ON_AIR"/"fresh plan took air" clearing above); one
    that relaunches slower than that but still faster than the 60-second
    worker-age floor gets no rollover RETRY (the floor applies only to the
    retry branch, never to a plan's first, original dispatch) for as long
    as that keeps happening. Neither is a hang -- just a reversion to the
    pre-item-78 shape, where the channel reaches its own end-of-schedule/
    crash cycle and the daemon's own crash back-off (this fix does not
    touch it) owns the restart.
  - The daemon also now refuses to defer a seamless reload's on-air switch
    to the outgoing program's own end if that boundary has already passed
    by the time the reload actually runs -- it cuts over immediately
    instead, since waiting for an end-of-program event that is already
    behind the clock would otherwise mean waiting for something that will
    never arrive. The plan_end_at a rollover reload was computed against is
    consumed exactly once per "reload" command: `EgressDaemon._request_reload`
    pops it at the very top of its own body, before any of ITS OWN branches
    run (the worker is missing/dead, there is no state row, or the strategy
    doesn't support content-reload all used to skip straight past the point
    that consumed it and leave it sitting there), and passes the value down
    explicitly to `_try_content_reload`. Plainly: the recorded value binds
    to whatever "reload" command for that channel `_request_reload`
    processes NEXT, not necessarily the one automation dispatched it for --
    MEASURED, an operator reload queued before automation's own rollover
    reload drains consumes it instead, and cuts immediately when it should
    have deferred normally. Automation's own 45-second retry-timeout/
    settlement bookkeeping still recovers from that (the never-landed
    reload it was actually tracking gets retried on schedule), but the
    mixup itself is real and this fix does not close it -- only the
    indefinite leak, and only once every route off-air actually clears the
    entry (see the next paragraph; an earlier round of this same fix
    believed, incorrectly, that `_stop` alone was enough).
  - **Round 5 (coordinator review): three more off-air routes left the
    same entry uncleared, and one of them was MEASURED to actually revert
    a later, unrelated reload's defer decision.** `_stop` clearing the
    entry (added above) only covers an operator stop or a drain -- a
    worker that exits on its own (a clean rc=0 exit with no pending
    reload, or a terminal crash that lands the channel in `ERROR` rather
    than a relaunch) never reaches `_stop`, and neither does `_drain`'s
    own "nothing to drain" branch nor `stop_all_channels`' "already gone"
    branch (both handle a channel with no live process at all). Any of
    the four now leaves a rollover-plan `plan_end_at` sitting in memory
    forever once recorded, exactly as before `_stop`'s own fix, just via a
    different door. MEASURED: record a rollover plan_end already in the
    past for a channel, let its worker exit cleanly (`STOPPED`), restart
    the channel (`ON_AIR`), then issue a plain operator reload with no
    rollover behind it at all -- the reload wrongly saw the stale,
    already-past `plan_end_at` and cut immediately instead of deferring
    normally. All four routes (`_poll_process`'s clean-exit and
    terminal-`ERROR` worker-exit branches, `_drain`'s process-is-None
    branch, and `stop_all_channels`' already-gone branch) now clear the
    entry themselves, the same as `_stop` does; the pending-reload restart
    and crash-relaunch routes inside `_poll_process` deliberately do not,
    since those keep the channel effectively on air and rely on
    `_request_reload`'s own pop instead (the same round-4 rule that keeps
    `_start` from popping this dict). Note: `_poll_process`'s clean-exit
    branch is shared by two cases -- a worker that simply exited on its
    own, and a drain that has finished (`was_draining`). An operator-issued
    "drain" command (`_process_command` -> `EgressDaemon._drain`) never
    calls `_stop` at all -- it only writes the `DRAINING` state and waits
    for the worker to actually exit -- so `_stop(draining=True)`'s own pop
    plays no part in that path; only `stop_all_channels` calls `_stop(...,
    draining=True)`. The clean-exit pop this round adds is therefore what
    actually covers an operator drain finishing: it is the only pop either
    case (a plain clean exit or a completed drain) reaches, not a
    redundant backstop behind an earlier one.
  - **Round 6 (coordinator review): the round-5 fix's "nothing recorded
    before a channel goes fully dark can ever survive" claim was still
    false -- two more routes leaked, both MEASURED.** First, a worker
    that crashes twice within the back-off cooldown takes
    `_relaunch_after_crash`'s DEFERRED branch: the channel sits in
    `STARTING` with no process running for the entire cooldown, and that
    branch never popped the entry. MEASURED: crash once (immediate
    relaunch), crash again inside the cooldown (deferred), let
    `_service_backoff_relaunch` fire the deferred relaunch once the latch
    permits, then issue a plain operator reload -- `switch_at_end_of_
    current` came back `False` (cut) instead of the deferred `True` a
    rollover plan_end sitting in the dict should have produced, and the
    dict was confirmed empty during the back-off window itself. The same
    leak also reached the operator via a second path: an explicit operator
    start command superseding a still-deferred relaunch (`_process_command`
    already pops `_backoff_relaunch` there, but was not popping this
    dict). Fixed by a single pop, not two: `_relaunch_after_crash`'s
    DEFERRED branch itself now clears the entry the moment the channel
    enters the back-off (`_backoff_relaunch[channel_id] = ...`), before
    either later resolution runs -- so both the latch eventually firing the
    deferred relaunch on its own AND an operator start command superseding
    it first find the entry already gone; `_process_command` itself gained
    no new pop of this dict. Second, `_start`'s own two terminal-`ERROR`
    `except` clauses (`ConfigInvalidError`/`SecretUnresolvedError`/
    `FfmpegNotFoundError`, and the general `EgressError` fallback) never
    popped -- `ERROR` is off-air by the same definition every other route
    in this list uses, so a value recorded going into a `_start` call that
    lands in `ERROR` survived across it. That branch now pops directly,
    closing the second gap.
    Exactly two routes deliberately still do not pop, unchanged from
    round 4: the pending-reload restart inside `_poll_process`, and the
    IMMEDIATE crash-relaunch path (`_relaunch_after_crash` ->
    `_begin_relaunch` -> `_start`, taken when the back-off latch permits
    running right away instead of deferring) -- both keep the channel
    effectively on air through the transition and rely on
    `_request_reload`'s own pop instead. The daemon's in-code docstring
    for `_rollover_plan_end_at` names both of these still-standing
    exceptions explicitly rather than repeating the "nothing can ever
    survive" claim this round disproved twice.
  - **Round 7 (coordinator review): the IMMEDIATE crash-relaunch path
    round 6 left standing (deliberately -- it keeps the channel effectively
    on air through the transition, per round 4) still leaked, MEASURED.**
    `record_rollover_plan_end` for a rollover reload about to be enqueued,
    then a crash lands and the channel relaunches immediately
    (`_relaunch_after_crash` -> `_begin_relaunch` -> `_start`, which per
    round 4 must not pop this dict) BEFORE that reload command ever
    drains -- and a wholly unrelated operator reload landing afterward
    inherited the stale, already-past `plan_end_at` and was wrongly cut
    immediately (`switch_at_end_of_current=False`) instead of deferring
    normally (`True`). This closes the mixup round 4's own fix explicitly
    left open (see that round's entry above, and
    `test_the_recorded_plan_end_binds_to_whichever_reload_drains_first_
    not_automations_own`, which now documents the WILDCARD/unscoped shape
    only, not the caller ChannelAutomationService actually uses): every
    pop above still fires unconditionally exactly as before (this round
    changes none of the "does the channel go off-air" routes), but the
    entry is now `(command_id, plan_end_at)` rather than a bare
    `plan_end_at`, and `EgressDaemon._request_reload` only hands the
    value down to `_try_content_reload` when the command actually
    draining matches the `command_id` the value was recorded for (or the
    recorded id is the `None` wildcard -- kept as the default so a direct
    call that bypasses the command queue entirely, e.g. every
    `PlayoutSupervisor` live-takeover/handback/slate route, and any
    pre-round-7 test double, keeps its exact prior behavior). A mismatch
    discards the value outright -- the reload that finds it gone falls
    back to `should_defer_switch`'s ordinary ON_AIR/no-override behavior
    (defer), the same as if nothing had ever been recorded, never a wrong
    cut and never a wrong defer off a horizon it wasn't actually computed
    against. `ChannelAutomationService._check_plan_rollover` now
    generates its rollover reload's `command_id` up front and passes the
    SAME id to both `record_rollover_plan_end` and the `_enqueue` call
    that dispatches it (`_enqueue` gained an optional `command_id`
    parameter for exactly this); every other `_enqueue` call site is
    unaffected (defaults to generating its own id, as before). Two new
    tests exercise the fix directly:
    `test_command_id_scoping_closes_the_immediate_crash_relaunch_leak`
    (the scenario above: the crash-relaunch leaves the entry untouched,
    and the scoped id keeps the later unrelated reload from consuming it)
    and `test_command_id_scoping_discards_value_when_an_unrelated_reload_
    drains_first` (an unrelated reload draining BEFORE the rollover's own
    scoped reload discards the value outright; the rollover's own reload,
    draining second, finds nothing left and also defers normally --
    neither wrongly cuts). No prior claim in this file or the daemon's own
    `_rollover_plan_end_at`/`_request_reload`/`_try_content_reload`
    docstrings asserted this specific mixup was closed; the claims about
    `_request_reload`'s pop "passing the value down" (never discarding it)
    were and remain accurate -- what changes this round is that the value
    passed down is now gated on the command_id matching before it is used
    at all.
  - **Round 8 (coordinator review): round 7's claim above -- "never a wrong
    cut and never a wrong defer off a horizon it wasn't actually computed
    against" -- was FALSE, MEASURED.** Round 7's `_request_reload` popped
    `_rollover_plan_end_at` UNCONDITIONALLY on every drain and only gated
    *use* of the popped value on the command_id match; a mismatch still
    discarded whatever was recorded. The common trigger is
    `ChannelAutomationService`'s own 45s issued-timeout retry
    (`_check_plan_rollover`'s `retrying_undelivered` branch): dispatch A
    records `command_id=A` and enqueues reload A; the daemon stalls past
    the retry timeout; the retry re-records (OVERWRITING the dict entry)
    `command_id=B` and enqueues reload B. Both A and B are real, live
    commands sitting in the queue when the daemon catches up. If A drains
    first, round 7's unconditional pop threw away B's freshly-recorded
    entry right there, on A's mismatch -- so when B itself drained moments
    later there was nothing left at all, and the daemon deferred against no
    recorded horizon even though B's own horizon (the one just discarded)
    had already passed. Round 6 measured the pre-scoping shape as
    `[False, True]` (A wrongly cut on a value recorded for a different
    command); round 7's scoping flipped it to `[True, True]` (both wrongly
    defer -- dead air on a horizon already past, never cut at all). Neither
    shape is correct; the right one is `[True, False]` (A: mismatch, value
    left in place, ordinary defer; B: match, cut on the past horizon it was
    actually recorded against).

    Fixed by popping `_rollover_plan_end_at` ONLY on an actual command_id
    match -- a mismatch now leaves the entry untouched for whichever
    command it was really recorded for to consume when that one drains,
    instead of discarding it on the first unrelated command that happens to
    drain first. This stays safe against every off-air/relaunch leak the
    prior rounds closed: none of those routes go through `_request_reload`
    at all, so a mismatched entry left here still cannot outlive the
    channel going off-air (every off-air route pops the dict itself,
    unconditionally, unchanged by this round).

    `record_rollover_plan_end`'s `command_id` is now a REQUIRED
    keyword-only parameter -- the round-7 `None` default doubled as a
    "wildcard, matches whatever drains next" behavior that zero production
    callers relied on (`ChannelAutomationService` is the only recorder and
    always supplies a real generated id); a caller that genuinely wants an
    unscoped recording must now say so explicitly (`command_id=None`), and
    an explicit `None` matches only a drain whose own `command_id` is also
    `None` (`supervisor.py`'s direct-call routes) by ordinary equality, not
    a special-cased wildcard -- since a real `EgressCommand` drawn from the
    durable queue always carries a real string id, an unscoped record can
    no longer be wrongly consumed by whichever queued reload happens to
    drain first at all (see
    `test_unscoped_record_never_matches_a_real_queued_reload_and_needs_an_
    off_air_pop`). `_enqueue`'s previously-unused `str` return value is
    removed (nothing read it; every call site that needs to correlate an id
    already pre-generates its own, per round 7).

    `test_command_id_scoping_closes_the_immediate_crash_relaunch_leak` and
    `test_command_id_scoping_discards_value_when_an_unrelated_reload_drains_
    first` are rewritten (the latter renamed
    `test_command_id_scoping_defers_and_retains_value_when_an_unrelated_
    reload_drains_first`) to the corrected pop-only-on-match shape,
    `test_the_recorded_plan_end_binds_to_whichever_reload_drains_first_not_
    automations_own` is rewritten as
    `test_unscoped_record_never_matches_a_real_queued_reload_and_needs_an_
    off_air_pop` (the old wildcard-binds-to-whichever-drains-first shape is
    no longer reachable at all), and a new
    `test_retry_collision_a_stalled_retry_that_overwrites_the_recorded_
    value_still_cuts` reproduces the exact production trigger above end to
    end through the real command queue. `tests/egress/test_automation.py`
    gained
    `test_check_plan_rollover_records_the_plan_end_scoped_to_the_enqueued_
    commands_own_id`, pinning that `_check_plan_rollover` actually passes
    the SAME id to both `record_rollover_plan_end` and `_enqueue` --
    nothing had asserted the two agree before this round.
- **Install-over could leave the PREVIOUS kit's application payload silently
  running.** MEASURED on a real tester (2026-09-05): installing kit B `/S`
  (install-over) on a station kit A had already installed, where both kits
  declared the same `product_version` (e.g. `1.0.0-beta.5`) but carried
  different content, left kit A's `native-app-payload.ccpack` -- and its
  extracted `runtime\` tree -- staged and running: the installer exited `0`,
  `/health` reported healthy, but the code actually executing was still kit
  A's. Root cause: `native_pack_staging.rs`'s staged-pack check
  (`classify_dest_pack_state`) verified the pack already at
  `$INSTDIR\packs\<component>.ccpack` against only the `--new-version`/
  `--compatible-core` STRINGS, so an identically-versioned but
  content-different incoming pack was classified `AlreadySatisfied` and the
  new pack at `$EXEDIR\packs` was never copied in. The staging decision now
  also compares each pack's content digest (`VerifiedPack::sha256`, the raw
  `.ccpack` file's own SHA-256) and replaces the staged pack whenever the
  incoming one differs, for both required and optional components. Every
  staging decision -- for every component and every outcome, not only a
  replace/unchanged subset -- now records which outcome fired plus both
  packs' digests as structured `payload_identity` entries
  (`PackPayloadIdentity`) on the `--civiccast-stage-packs` manifest report.
  That full manifest is written whole to its own file under
  `%ProgramData%\CivicCast\` (`install-manifest-report-<pid>-<unix
  time>.json`) rather than piped through stdout: a manifest carrying
  `payload_identity` for even a handful of components already exceeds the
  1024-byte NSIS_MAX_STRLEN cap `nsis-hooks-bootstrap.nsh`'s `ExecToStack`
  capture truncates at (measured against real Gate A evidence), and because
  `serde_json`'s `Map` renders keys alphabetically, truncation would have
  silently dropped the entire `required` object. `install-progress.log`
  instead gets a short, budget-tested summary line naming that file's path
  plus one `component=outcome staged=<8hex> incoming=<8hex>` token per
  component; `native_pack_staging.rs` itself still emits zero
  `print`/`println`/`eprintln` calls, which `nsis-hooks-bootstrap.nsh`'s
  capture strategy depends on.
  Gate A's cross-version upgrade lane (`sandbox-lab/scripts/
  In-Sandbox-Report.ps1`, `scripts/gate_a_verdict.py`'s
  `check_dirty_survival`) now additionally hashes the installed app-payload
  pack against the kit's own pack post-upgrade
  (`POST_UPGRADE_APP_PAYLOAD_DIGEST` / `KIT_APP_PAYLOAD_DIGEST`) and fails
  the run on any mismatch -- a real, additional post-upgrade assertion this
  lane did not make before. **It does not, on its own, cover the specific
  regression above**: that lane's baseline kit is always a genuinely older
  `product_version` (currently `1.0.0-beta.4`) than the candidate under
  test, so the incoming pack is always copied and the two digests always
  match by construction; the lane would not (yet) fail if the identity
  check above were removed. Reproducing this exact same-`product_version`,
  different-content scenario end to end is covered by a new Rust unit/e2e
  test (`native_pack_staging.rs`'s
  `install_over_a_different_content_kit_declaring_the_same_version_replaces_the_staged_payload`
  and its `native-app-payload`/`$INSTDIR\runtime` counterpart), not yet by
  a Gate A sandbox lane; a same-`product_version` install-over lane is
  logged as a follow-up.
- **The live caption tap could starve playout, and did.** MEASURED on tester
  DESKTOP-VBMA6O5 (1.0.0-beta.5 candidate kit `e502074`, three channels
  ON_AIR on the GStreamer engine): the control plane burned ~247% of a core
  (19,000+ CPU-seconds, 1.9 GB RSS, 61 threads) running live-caption ASR while
  the three playout workers sat at 26-64% each and repeatedly hit
  `CTRL stall: no output for 10s - quitting for daemon restart`; two channels
  restarted within the first hour. `control_plane-app.log` carried 663
  `caption` lines -- the same CRITICAL overload message every ~30 seconds for
  all three channels -- and the station had never been asked to caption
  anything. Four causes, all fixed:
  - **Overload did not back off.** The worker cleared the channel's captions,
    dropped the audio, logged CRITICAL, and retried on the very next scan,
    forever, at full CPU, transcribing audio it then discarded. New
    `civiccast/captions/tap_backoff.py` pauses an overloaded channel for an
    exponentially growing window (60s, 120s, 240s ... capped at 900s), logged
    once at WARNING per pause. A channel is forgiven only after three
    consecutive within-capacity scans, so a flapping channel keeps escalating.
    The stale audio is discarded rather than filed under `<channel>/overload/`:
    nothing ever swept that directory (the retention policy's tap sweep reads
    `processed/` only) and no review row referenced it, so on a chronically
    overloaded station it grew without bound across every pause cycle.
  - **ASR concurrency was unbounded in practice.** `max_channel_workers`
    defaulted to a flat 3 while each faster-whisper model was built with
    `cpu_threads=0` -- CTranslate2's "every core". The default is now one
    transcribing channel per 8 CPUs (never more than 3), and the LIVE runtime
    is built with `cpu_threads=1` and greedy decoding on CPU: about a one-core
    steady-state budget for the whole caption feature on the 8-core field
    station. Channels beyond the bound are queued in the same scan, never
    dropped. Batch/VOD sizing is deliberately unchanged.
  - **Playout and captions ran at the same scheduler priority.** The
    GStreamer playout workers are now spawned with
    `ABOVE_NORMAL_PRIORITY_CLASS`. (The caption side lowers only its Python
    ASR threads, not CTranslate2's own thread pool -- see
    `civiccast/captions/tap_worker.py`; the bound and the backoff are the
    load-bearing protections, and neither priority change is measured on a
    station yet.)
  - **There was no operator switch.** See *Added* above.
  Also: `<channel>/runtime-status.json` gains the `paused` and `disabled`
  states plus `resume_in_seconds`/`consecutive_overloads`, and is now written
  only on a state change or a 30-second heartbeat instead of on every ~2-second
  scan; and the retention sweep now runs on its own 60-second cadence instead
  of once per ~2-second scan (it lists review rows and SHA-256s every chunk it
  considers, to enforce a schedule measured in days). New env vars:
  `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`,
  `CIVICCAST_CAPTION_TAP_OVERLOAD_BACKOFF_SECONDS`,
  `CIVICCAST_CAPTION_TAP_MAX_OVERLOAD_BACKOFF_SECONDS` (both clamped with a
  WARNING rather than raising, so a mistyped duration can never hold the
  control plane down over a best-effort feature), and
  `CIVICCAST_WHISPER_BEAM_SIZE` (live tap only). Operator guidance:
  `docs/ops/background-workers.md`.
- **`scripts/prove_native_caption_capacity.py` pinned the single string
  `"overloaded"` for its fail-closed negative control**, so the capacity proof
  would have failed on every station the moment the backoff above started
  publishing `"paused"` -- while the property the control exists to prove was
  still satisfied. It now accepts either refusal state, and the test consumes
  the REAL producer's output instead of a hand-typed report dict, which is why
  nothing caught the mismatch.
- **`civiccast/egress/gst/graph.py`'s `source_leg_is_clock_timed` docstring
  claimed the fail-safe answer for an unknown source factory is `True`; the
  code has always returned `False`** (`_chain_is_clock_timed` only matches a
  listed factory or an explicit `is-live=True`). Fixed the docstring, added
  the Windows live-capture device factories (`ksvideosrc`, `mfvideosrc`,
  `dshowvideosrc`, `wasapi2src`, `wasapisrc`) plus Linux's `v4l2src` to
  `CLOCK_TIMED_SOURCE_FACTORIES`, and deliberately did not add
  `interpipesrc`/`interpipesink` -- the RidgeRun interpipe plugin was
  demoted from the shipped GStreamer closure by an owner-confirmed spec
  decision and is not wired into any ingest/playout graph this repository
  builds. New tests in `tests/egress/test_gst_graph.py` pin both the new
  factories (clock-timed) and the corrected unknown-factory default
  (segment-timed), including `interpipesrc` as a documented example of an
  unrecognized factory. Since `graph.py` is a D2 blob-drift-bound
  code/fixtures input across two `external_evidence` claims in
  `docs/claims/claims.yaml` (`native-decision-gate`,
  `session0-service-broadcast`), re-hashed its three bound blob entries and
  added re-provisioning comments following this registry's established
  pattern, with current-source proof pointed at the new gi-free unit tests
  above.
- **A schedule of back-to-back short items (30-second slots) blew up the
  GStreamer worker's decoder threads.** MEASURED on a real tester (clean
  install of `91caebc`, three GStreamer channels, a schedule of 30-second
  items back-to-back): every worker exited with
  `CTRL stall: no output for 10s` and relaunched roughly every 30 seconds; a
  live worker had 1238 threads and 3.5 GB RSS. Root cause: #170's
  `source_plan.PLAN_MIN_SECONDS = 1800.0` chased 30 minutes of planned
  DURATION out of 30-second slots, building ~60 segments per plan --
  `bridge.graph_from_config` builds one
  `filesrc -> decodebin -> videoconvert -> videoscale -> videorate` sub-chain
  PER segment in a single pipeline set to `PLAYING` all at once
  (`engine._build_playlist`), and `avdec_h264`'s default `max-threads=0`
  spins up ~20 threads per sub-chain -- ~1200 threads, no TS output landing
  inside the engine's 10-second stall watchdog. D45, four independent fixes
  (the first pass at this fix missed the second and third below; caught in
  hostile review before merge):
  - `PLAN_MIN_SECONDS` reverted to `0.0` -- a plan's segment count is bounded
    by `max_segments` (8 by default, pipeline shape) alone again; a caller
    that explicitly wants a longer duration-bounded window can still opt in
    via `min_plan_seconds`.
  - The pipeline-shape cap (`MAX_PLAYLIST_SUBCHAINS`, 12; moved into
    `civiccast/egress/models.py` so every producer and consumer import the
    same value) is now enforced at the plan's only PRODUCER --
    `source_plan.build_source_plan_from_schedule` clamps `max_segments` and
    `segment_cap` down to it (logging a WARNING when it does) -- not only in
    `bridge.graph_from_config`. Hostile review caught that the first pass
    capped the pipeline but left every OTHER consumer of the same plan
    (`automation.py`'s rollover-horizon tracking, `daemon.py`'s
    dispatched-plan bookkeeping, `continuity.py`, `preparer.py`) trusting an
    uncapped plan, so a plan above the cap would still have made the
    pipeline reach EOS long before automation's tracked horizon expected it
    to -- a worker restart roughly every 6 minutes, silently, for any
    schedule that could build more than 12 segments. Because the producer
    now guarantees the cap, `graph_from_config` treats a "program"-kind plan
    still reaching it above the cap as proof that clamp was BYPASSED and
    FAILS CLOSED (`errors.PlaylistCapBypassedError`) rather than silently
    truncating it -- a second delta review caught that truncating-and-
    logging-ERROR (the first pass's answer) would still have let
    automation/daemon go on trusting the plan's full, uncapped duration
    while the pipeline quietly played a shorter one, exactly the desync the
    producer-side clamp exists to prevent. A "slate"/"cg" fill plan
    (`SlateSourceGenerator`, `bulletin_filler._plan_with_cycle`) is EXPECTED
    to repeat past this cap by design (CA-8) and is unaffected -- truncated
    with a WARNING, not failed.
  - `ChannelAutomationService._rollover_min_interval_seconds` (`automation.py`)
    now derives the per-channel rollover-dispatch floor from the plan
    actually on air (half its planned duration, clamped at the historic 300s
    ceiling) instead of a flat 300s. MEASURED with the flat 300s floor
    against an 8x30s (240s) plan: 6 dispatches in 30 minutes, the first at
    120s, each 300s apart, with the boundary lead shrinking every cycle --
    120s, then 60s, then 0s, then negative -- so by the third rollover the
    trigger arrives AT OR AFTER the plan's actual end and the engine reaches
    EOS and restarts before that rollover can land. The scaled floor keeps
    the lead at a steady ~120s indefinitely instead. A second delta review
    caught two more instances of the same shape of bug: an earlier version
    of the scaled floor itself still floored at a flat 30s
    (`max(30.0, 0.5 * planned)`, longer than an 8x3s/24-second plan's own
    life -- MEASURED: still dispatches, ten times in 300s, but with the same
    shrinking-to-negative lead), and `_ROLLOVER_MIN_LEAD_SECONDS` (the
    boundary-aligned trigger's lead, previously a flat 120s) had the
    identical problem on its own -- a lead longer than the plan pushes
    `rollover_trigger_at`'s `plan_end_at - lead` candidate into the plan's
    own past, landing dispatches at or after EOS even with the floor fixed.
    Both are now scaled the same way
    (`_ROLLOVER_MIN_INTERVAL_FLOOR_SECONDS` = 1.0, a trivial epsilon; a new
    `_rollover_min_lead_seconds` = `min(120, 0.5 * planned)`), so neither
    ever returns more than half of the plan's own planned duration --
    MEASURED for the 24-second plan: a rollover every 24s with a steady 12s
    (half the plan) of lead, indefinitely.
  New/rewritten tests in `tests/egress/test_source_plan.py` (an end-to-end
  test proving the plan `build_source_plan_from_schedule` returns and the
  graph `bridge.graph_from_config` builds from it agree on the segment
  count) and `test_automation.py` (production-shape cadence tests against
  the real `ChannelAutomationService`, an 8x30s and an 8x67s plan, and the
  8x3s starvation regression), plus `test_gst_bridge.py`. None of the
  changed files (`source_plan.py`, `automation.py`, `bridge.py`) are D2
  blob-drift-bound in `docs/claims/claims.yaml`; `models.py` is not bound
  either.
- **A fresh GStreamer worker under CPU load could die with `pipeline did not
  reach PLAYING within 5.0s`, which the daemon treated as an ordinary crash
  and relaunched into a storm** (item 82, sandbox run 13 evidence). The old
  bound reused `teardown_timeout_s` (5.0s), a constant never meant to double
  as a preroll bound. `engine.py`'s `_await_playing` now waits up to a
  dedicated, configurable `preroll_timeout_s` (30s default,
  `CIVICCAST_GST_PREROLL_TIMEOUT_S` env override, clamped to `[5, 45]`s),
  polling in 5s slices and logging the `get_state` result, the CURRENT
  pipeline state, and the pending state on every slice instead of blocking
  silently for the whole bound. Once the bound is actually exceeded it raises
  the distinct `PrerollTimeoutError` (a `RuntimeError` subclass) rather than a
  bare `RuntimeError`; `worker.py` catches that, emits its `WORKER_RESULT`
  receipt (`{"error": ("preroll-timeout", ...), "teardown_clean": False}`, so
  `civiccast.native.installed_gstreamer_smoke.require_clean_worker_result`
  can name the reason instead of reporting a missing receipt), and exits with
  a new, distinct `civiccast.egress.gst.exit_codes.GST_PREROLL_TIMEOUT_EXIT_CODE`
  instead of the generic crash code. `EgressDaemon._relaunch_after_crash`
  still relaunches that exit through the exact same back-off path as any
  other crash, but no longer counts it toward the crash-loop streak that
  eventually forces fallback slate (`_LIVE_SOURCE_FAILURE_FALLBACK_STREAK`)
  more than once per 60s -- a train of legitimate slow starts under load can
  no longer force a healthy source onto fallback slate.
  - **Round-2 review BLOCKER (Opus, PR #183), fixed same day:** the 45s
    upper clamp is load-bearing, not cosmetic. An unclamped
    `CIVICCAST_GST_PREROLL_TIMEOUT_S >= 60` made a worker that ALWAYS
    preroll-times-out still measure >= 60s of "uptime" on every single exit
    (it dies right at its own configured bound) -- which is exactly the
    daemon's healthy-uptime streak-reset threshold
    (`_RESTART_STREAK_RESET_UPTIME_S`), so the crash-loop streak reset on
    every single crash and NEVER escalated to fallback slate (measured: 40
    consecutive relaunches, streak stuck at 0 -- a genuinely dead source
    would have relaunched forever). Fixed on both sides: the 45s clamp keeps
    the configured bound safely under that threshold, and
    `_relaunch_after_crash` now ALSO exempts a
    `GST_PREROLL_TIMEOUT_EXIT_CODE` exit from the healthy-uptime reset
    outright (a preroll that never reached PLAYING is not "healthy uptime"
    regardless of how long it took). The healthy-uptime reset (for every
    OTHER exit reason) now also clears the preroll-timeout rate-limit
    bookkeeping, so a genuinely healthy run doesn't leave a stale rate-limit
    window behind for a later, unrelated preroll timeout.
  - **Round-3 review BLOCKER (Opus, PR #183), fixed same day: round-2's fix
    was NOT sufficient on its own.** Correcting the round-2 entry directly
    above: the 45s clamp and the crash-path exemption did **not**, either
    alone or together, close the hole -- `EgressDaemon._poll_process` has a
    SEPARATE healthy-uptime reset on the **alive-poll** path (no returncode
    there to exempt, since the worker hasn't exited) that reset the crash
    streak on wall-clock seconds since the worker was **spawned** -- which
    also counts interpreter start, `import gi`/`Gst.init`, graph build, and
    the preroll wait itself, none of which is air, and none of which is
    bounded by the worker's own `preroll_timeout_s`. Measured against the
    real `process_once` poll loop (2s ticks while alive, then a real
    preroll-timeout exit): a worker "alive" for 45/58/59s still escalated to
    fallback slate by cycle 9 as expected, but one "alive" for 60 or 62s got
    its streak reset on every single alive poll past the 60s mark --
    **before it even exited** -- so the streak stayed stuck at 1 forever
    (never escalated in 40 cycles), reproducing the exact 40-relaunch
    symptom this whole fix chain exists to close. Fixed: `_await_playing`
    now prints a stable `CTRL preroll: reached PLAYING` marker on stderr
    ONLY on the actual PLAYING success path (never on timeout or failure);
    the daemon greps for it via a new
    `civiccast.egress.health.worker_reached_playing`, and the alive-poll
    reset now starts its 60s healthy-uptime clock from the moment that
    evidence is first observed (`EgressDaemon._on_air_confirmed_at`), never
    from spawn time. An FFmpeg-strategy channel has no PLAYING marker of its
    own, so the same evidence check also accepts real fps/bitrate progress
    (`civiccast.egress.health.encoder_has_progress`, already used for sink
    health) as an equally valid on-air signal --
    `EgressDaemon._observed_on_air_evidence` covers both encoder families.
    Also fixed the same round, both false claims this document and the code
    itself were carrying: the "either fix alone would have closed the hole"
    line directly above was not true (see this correction), and
    `engine.py`'s own module comment claiming the healthy-uptime exemption
    holds "regardless of how this bound is configured" was equally false
    for the identical reason -- both now read the corrected story. And a
    separate BLOCKER: `CIVICCAST_GST_PREROLL_TIMEOUT_S=nan` escaped the
    `[5, 45]` clamp entirely (`min(max(nan, 5), 45)` evaluates to `nan`, not
    `5.0` -- Python's `min`/`max` keep their first argument across any
    comparison against NaN, and `float("nan")` parses without raising, so
    the pre-existing malformed-value guard never caught it either), which
    reached `_await_playing`'s deadline arithmetic as `nan` and fell through
    to the generic pipeline-construction `ValueError` path instead of ever
    raising the distinct `PrerollTimeoutError` -- `_resolve_preroll_timeout_s`
    now guards both the explicit-arg and env-var paths with `math.isfinite`
    before clamping, falling back to the 30s default (with a stderr warning)
    on any non-finite value.
  - **Carry-over follow-up (item 5), fixed the same round:** `worker.py`'s
    `PrerollTimeoutError` handler used to let the exception propagate out of
    `run_forever` without ever calling `engine_instance.stop()` -- the only
    teardown was the unconditional, non-graceful `os._exit()` at the very
    bottom of the file. `main()` now attempts `stop(force_exit_on_hang=False)`
    in that handler (already time-bounded via `teardown_timeout_s`;
    deliberately never `force_exit_on_hang=True`, which would call
    `os._exit(70)` on a stuck teardown and silently swap out the distinct
    `GST_PREROLL_TIMEOUT_EXIT_CODE` this whole path exists to preserve), and
    the `WORKER_RESULT` receipt's `teardown_clean` field now reports that
    real outcome instead of a hardcoded `False`. A teardown that itself
    raises is caught and logged, never allowed to mask the distinct exit
    code.
  - **Round-4 review BLOCKER (Opus, PR #183), reproduced -- round-3's fix
    was NOT sufficient on its own.** Correcting the round-3 entry directly
    above: `EgressDaemon._poll_process` did start greping for the
    `CTRL preroll: reached PLAYING` marker via
    `civiccast.egress.health.worker_reached_playing`, but that function read
    a fixed tail window of the channel's per-worker stderr log with no
    anchor to the CURRENT worker's own spawn point. Both encoder strategies
    open that fixed per-channel log (`gst-worker.stderr.log` /
    `ffmpeg.stderr.log`) in **APPEND mode and never truncate it per spawn**
    (`_default_worker_launcher` in `strategy.py`, `start_ffmpeg` in
    `_ffmpeg.py`) -- so once ANY worker on a channel ever reached PLAYING (or
    ever showed FFmpeg fps/bitrate progress), that evidence sat in the log
    forever, and every LATER worker spawned on the same channel read as
    "confirmed on air" on its very first poll tick, whether or not it ever
    produced any output of its own. The 60s healthy-uptime clock had become
    a spawn clock again -- the exact round-3 symptom, reproduced (measured:
    40 relaunches, streak pinned at 1). Fixed with two independent anchors,
    belt and braces: `EgressDaemon._stderr_spawn_offset` now records the
    stderr log's byte SIZE at the moment the CURRENT worker was spawned
    (`_start`, popped alongside `_started_at` on every exit/spawn/stop route
    so a fresh worker never inherits a stale offset), and
    `civiccast.egress.health.worker_reached_playing` /
    the new `read_ffmpeg_encoder_metrics_since` scan ONLY bytes at or after
    that offset -- a previous worker's evidence, which always sits before
    it, is never read at all, not merely filtered out afterward. If the log
    is ever found smaller than the recorded offset (rotated/truncated
    out from under the daemon), the read falls back to byte 0 rather than
    erroring. Second, independent layer: `_await_playing`'s marker now also
    prints the worker's own pid (`... pid=1234`, `os.getpid()`), and the
    daemon requires that pid to match its currently-tracked process
    (`_observed_on_air_evidence`) before crediting the marker -- a defense
    that holds even on the (believed-impossible) case where the byte offset
    itself were somehow wrong. The old fixed 64 KiB tail window is gone from
    this check entirely, replaced by a 4 MiB bounded scan measured FROM the
    spawn offset (not a hard requirement of the fix, but a deliberate choice
    not to reintroduce an unbounded read from the other end of the file --
    see `civiccast.egress.health._SPAWN_SCAN_LIMIT_BYTES`); per-tick cost of
    the new scan measured directly (2,000 calls, wall-clock average) against
    a representative unconfirmed-worker log: `worker_reached_playing`
    (~55 KB, marker present, early-exit on match) averaged ~0.1ms/call;
    `read_ffmpeg_encoder_metrics_since` (~110 KB / 2,000 progress lines, the
    worst case of a channel that has been unconfirmed since spawn for a
    while and keeps accumulating progress lines with no early exit) averaged
    ~5.8ms/call. Both comfortably inside the existing ~2s poll cadence, and
    the 4 MiB bound caps the worst case regardless of how long a channel
    stays unconfirmed. `read_latest_ffmpeg_encoder_metrics`
    (the sink-health tail-window reader used by `_health_metrics` /
    `build_default_sink_health`) is unchanged -- that reader only ever wants
    "is the encoder moving media right now," which a previous worker's
    long-stale progress line cannot masquerade as once the current worker
    has printed anything of its own; only the ON-AIR-EVIDENCE readers needed
    the spawn anchor.
  - New tests: `tests/egress/test_gst_engine_preroll_timeout.py` (the
    engine's bounded wait, env-var resolution/clamp including the new 45s
    ceiling, the distinct exception, the current+pending log line, the new
    `reached PLAYING` success marker -- present only on success, never on
    timeout -- and the NaN-clamp-escape regression),
    `tests/egress/test_gst_worker_preroll_timeout_exit.py` (`worker.main()`
    returns the distinct exit code, still emits a `WORKER_RESULT` receipt,
    and now attempts a bounded teardown -- covering a clean teardown, an
    unclean one, and one that itself raises), `tests/egress/test_health.py`
    (`worker_reached_playing`, spawn-offset anchoring and the pid check --
    round-4 rewrote
    `test_true_even_when_the_marker_is_outside_the_default_tail_window` into
    `test_true_when_the_marker_is_130kb_past_the_spawn_offset` (the OLD test
    named a tail-window parameter that no longer exists; the real behavior
    now under test is that a marker well past the 64 KiB the old window
    would have covered is still found because it's scanned from the spawn
    offset forward with no window at all) plus a new
    `test_a_marker_before_the_spawn_offset_does_not_count`, and
    `read_ffmpeg_encoder_metrics_since`'s equivalent stale-progress-before-
    offset case), and `tests/egress/test_daemon_preroll_timeout_relaunch.py`
    (the rate-limited streak wired through a REAL `_poll_process` returncode
    rather than a direct call, per-channel isolation, the healthy-uptime
    exemption even at uptime >= 60s, reset behavior, sustained-crash
    escalation to fallback slate at both the 30s default and the 45s clamp
    ceiling with the previously-loose cadence bound replaced by the actual
    measured value, AND the round-3 alive-poll-path regression: sustained
    preroll timeouts at worker lifetimes of 45/59/60/62/90s under both
    bounds -- reproduced against the pre-fix gating logic to confirm each
    new test actually fails without the fix before being restored). Round-4
    additionally: changed the fixture's `_WorkerStrategy.start` from
    `write_text` (truncates per spawn -- the reason the round-3 test matrix
    passed while the real append-mode log did not) to append mode, matching
    `strategy.py`'s real behavior, and re-ran the full 45/59/60/62/90s x
    30/45s matrix under it; added
    `test_a_stale_marker_from_a_previous_worker_does_not_confirm_a_new_one`,
    the reviewer's own reproduction: worker 1 emits the real marker, airs
    10s, exits cleanly; workers 2 through 41 append ONLY the never-reaches-
    PLAYING timeout line to the SAME log, each staying alive 62s before its
    own preroll-timeout exit -- and the channel must still escalate to
    FALLBACK_SLATE (asserted at cycle 5, the same cadence the non-stale-
    marker 62s case already reaches) rather than latching "confirmed on air"
    off worker 1's long-stale marker forever. Also updated
    `tests/egress/test_daemon.py::test_healthy_uptime_resets_the_crash_streak`,
    which used to force the reset by back-dating `_started_at` directly with
    no encoder evidence at all -- exactly the bug this round closes -- to
    instead write real evidence and assert the reset only fires once that
    evidence has been held for the healthy-uptime window.
- **A fresh GStreamer worker could reach PLAYING quickly and still get killed
  before its first output buffer, distinct from item 82's slow-preroll case**
  (item 84, measured in sandbox run 15, soak-fcfcb81-20260906-183448Z, and in
  three seamless-OFF runs). Every affected worker printed
  `CTRL preroll: reached PLAYING after 0.3s` -- a real, fast PLAYING
  transition -- immediately followed by
  `CTRL stall: no output for 10s - quitting for daemon restart`.
  `_await_playing` accepts `NO_PREROLL` as success (unchanged, and correctly
  so -- some pipelines legitimately never preroll), so PLAYING is not
  evidence a single buffer crossed the mux, but `_arm_stall_watchdog` armed
  the 10s post-first-buffer `stall_timeout_s` the instant PLAYING was
  reached. Under start-up load (a concurrent `ffmpeg -threads 1 h264_mf +
  loudnorm` conform, a ~10s synchronous content-reload source preparation on
  the automation thread, live caption-tap overload) the first output buffer
  can legitimately take longer than 10s, killing a perfectly healthy worker.
  `engine.py`'s `_check_stall` now measures two DISTINCT budgets: while no
  output buffer has been observed yet, a new, separate, configurable
  `first_output_timeout_s` (45s default, `CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S`
  env override, clamped to `[10, 120]`s, `math.isfinite`-guarded exactly like
  `preroll_timeout_s`); only once the first buffer IS observed does the
  original 10s `stall_timeout_s` apply, completely unchanged. A distinct
  stderr marker (`CTRL first-output: no output within Ns of PLAYING -
  quitting for daemon restart`) and a distinct `("first-output-timeout", ...)`
  `WORKER_RESULT` error reason let `worker.py` exit with a new, distinct
  `civiccast.egress.gst.exit_codes.GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE`
  instead of the generic crash code every other engine failure uses.
  `EgressDaemon._relaunch_after_crash` treats this new exit code exactly like
  `GST_PREROLL_TIMEOUT_EXIT_CODE` (`_SLOW_START_EXIT_CODES`, sharing the same
  per-channel rate-limit bookkeeping) -- still relaunches through the normal
  back-off path, but never advances the crash-loop streak more than once per
  60s and is exempt from the healthy-uptime streak reset, so a train of
  legitimate slow-first-output starts under load can no longer force a
  healthy source onto fallback slate. `_arm_stall_watchdog` now arms
  whenever EITHER budget is active (before this fix, an operator setting
  `stall_timeout_s <= 0` to disable the post-first-buffer check also
  silently disabled the independently useful first-output check).
  - **Related automation.py fix (same item, same soak evidence):** the
    channel-rollover "reload for `<ch>` did not land within 45s; retrying"
    WARNING used to log on EVERY ~2s poll tick for as long as the actual
    retry stayed gated behind either the retry-cadence floor or the
    worker-pid-age floor (measured 1:1 with "deferred: worker pid has only
    been alive Ns" -- a worker that keeps crashing/relaunching right after
    every reload never gets a chance to settle) because the WARNING fires
    before either gate and `_rollover_issued_at` is never cleared by a gated
    tick. Now logs once when the 45s threshold is first crossed, at most
    once more per 60s while still gated (DEBUG for every other gated tick),
    and a separate WARNING when the retry actually dispatches. The gating
    logic itself is unchanged.
  - New tests: `tests/egress/test_gst_engine_first_output_timeout.py` (the
    `_check_stall`/`_arm_stall_watchdog` two-budget split, and
    `_resolve_first_output_timeout_s`'s default/env/clamp/NaN-guard coverage
    mirroring the preroll resolver's own),
    `tests/egress/test_gst_worker_first_output_timeout_exit.py` (the
    worker's distinct exit code and `WORKER_RESULT` receipt on this reason,
    contrasted against the unchanged generic-crash-code path for an ordinary
    stall), `tests/egress/test_daemon_first_output_timeout_relaunch.py` (the
    daemon's shared rate-limited streak across both slow-start exit reasons,
    the healthy-uptime exemption, and sustained-failure escalation to
    fallback slate), and
    `tests/egress/test_automation_rollover_retry_log_cadence.py` (the log
    cadence fix: one WARNING on first crossing, DEBUG while still gated, a
    repeat WARNING at the 60s mark while STILL gated -- simulating a worker
    that keeps relaunching with a fresh, still-too-young pid -- and a
    distinct WARNING once the retry actually dispatches).
  - **Runbook note:** a worker's stderr distinguishes "never produced
    output" (`CTRL first-output: ...`, item 84) from "stopped producing
    output after airing" (`CTRL stall: ...`, S9-5/unchanged) -- read the
    exact marker before assuming a channel bounce is the same failure mode
    as any other stall.
  - **Round-2 review BLOCKER (2026-09-06), fixed same day: an escalation
    cliff in the fix directly above.** `_MAX_FIRST_OUTPUT_TIMEOUT_S` (120)
    exceeds the daemon's ALIVE-poll healthy-uptime reset threshold
    (`_RESTART_STREAK_RESET_UPTIME_S`, 60s), and item 84's own failure mode
    prints `CTRL preroll: reached PLAYING after 0.3s pid=N` on every single
    relaunch -- which `EgressDaemon._observed_on_air_evidence` accepted as
    sufficient GStreamer on-air evidence (unchanged from before item 84,
    predating this fix). Measured with that marker present and the worker
    never actually producing output: at `first_output_timeout_s`
    65s/90s/120s the crash-loop streak reset on every alive-poll cycle and
    NEVER escalated to fallback slate (streak pinned at 1); at 45s-60s
    escalation still worked, purely because the worker's alive window never
    crossed the 60s reset threshold before it exited. PLAYING is not
    evidence output ever flowed -- fixed properly rather than by re-tuning
    the clamp: `GstPlayoutEngine` now prints a SEPARATE, new, pid-tagged
    marker exactly once, the moment the first real mux buffer is observed
    (`CTRL first-output: first buffer after Ns pid=N`,
    `_maybe_print_first_output_marker`); `civiccast.egress.health` gained
    `worker_produced_output`, the parsing counterpart to
    `worker_reached_playing` for this new marker (same spawn-offset/pid
    anchoring contract); and `EgressDaemon._observed_on_air_evidence` now
    requires `worker_produced_output` instead of `worker_reached_playing`
    for the GStreamer strategy -- the PLAYING marker is kept (still
    printed, still a genuine "reached PLAYING" log signal) but is no longer
    sufficient on-air evidence on its own. No configured budget value can
    defeat escalation now. Also this round: `_arm_stall_watchdog` used to
    hardcode `_first_output_seen = False` on every arm, which could wrongly
    re-open the first-output budget for a buffer that already crossed the
    mux DURING preroll, before arming -- now
    `self._first_output_seen = self._output_buffers > 0`.
  - **Round-2 also fixed automation.py's own sibling defect the round-1
    entry missed:** the "worker pid has only been alive Ns" deferred-WARNING
    (gated on the worker-pid-age floor, a different condition than the "did
    not land" WARNING above) still fired on every single gated tick after
    round 1's fix landed (measured: 150 WARNINGs per 300s) -- now
    rate-limited the same way, with its own bookkeeping
    (`_rollover_pid_age_warned_at`) since the two WARNINGs gate on
    different, independently-timed conditions.
  - **Round-2 also corrected `docs/claims/claims.yaml`'s engine.py blob**,
    which the round-1 entry recorded WRONG (a post-hash comment typo-fix
    edit was never re-hashed before that entry was written; the recorded
    value did not correspond to any object this repository had ever
    produced) -- re-hashed via `git hash-object --path
    civiccast/egress/gst/engine.py civiccast/egress/gst/engine.py` against
    the file as it stands after every round-1 AND round-2 edit.
  - **Round-2 additional tests:** `tests/egress/test_gst_engine_first_output_timeout.py`
    gained `_maybe_print_first_output_marker` coverage (prints once, prints
    at arm-time when output already flowed before arm -- round-2 item 4's
    own scenario -- and the zero-elapsed fallback);
    `tests/egress/test_health.py` gained `TestWorkerProducedOutput`
    (mirrors `TestWorkerReachedPlaying`, including the
    PLAYING-marker-alone-is-insufficient contrast case);
    `tests/egress/test_daemon_first_output_timeout_relaunch.py` gained the
    escalation-cliff reproduction itself (sustained cycles at the 45s
    default AND the 120s clamp ceiling with the PLAYING marker present but
    the output marker absent -- both must reach `FALLBACK_SLATE` -- and the
    positive case: a worker printing the real output marker and holding it
    60s DOES reset the streak); and
    `tests/egress/test_automation_rollover_retry_log_cadence.py` gained a
    dedicated test isolating the pid-age WARNING's own cadence. Two
    engine-side tests that assigned `first_output_timeout_s = 0.0` directly
    (an unreachable configuration -- the constructor always clamps to
    `[10, 120]`) were removed rather than converted, since a passing test
    against a state the product can never reach is misleading, not
    coverage.

### Changed

- **Release prep: bump product version to `v1.0.0-beta.5`.** Every surface
  `scripts/policy/check_release_identity.py` binds together
  (`civiccast/_version.py`, `civiccast/_native_version.py`, the installer's
  Cargo/Tauri/package.json identities, `main.rs`'s `CIVICCAST_VERSION`, the
  OpenAPI-derived docs, the operator-console on-screen-version e2e
  expectation) plus the extra surfaces the beta.3/beta.4 release-preps
  touched (`ARCHITECTURE.md`, `SUPPORT.md`, `docs/USER-MANUAL.md`,
  `scripts/download_windows_release_artifacts.ps1`,
  `docs/technical-ops-reference.md`, `INSTALL-WINDOWS.md`, both lockfiles)
  now read `1.0.0-beta.5`. `v1.0.0-beta.4` remains the current published
  release; this bump only advances the next development candidate's
  identity.
- **`sandbox-lab/upgrade-baseline.json` repinned to the beta.4 kit.** Now
  pins source SHA `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`, build run
  33854799455 (`native-beta-candidate-artifacts`, conclusion success),
  Gate A run 33901203343 (the successful three-lane Gate A run for this
  candidate -- clean station-acceptance PASS including
  `PASS_PRODUCT_ENGINE`, cross-version-upgrade PASS, download-only-upgrade
  PASS), and `product_version: 1.0.0-beta.4` -- so Gate A's cross-version
  and download-only lanes have a real, current prior build to upgrade
  `v1.0.0-beta.5` from. `installer_sha256` verified against the GitHub
  Release `v1.0.0-beta.4` asset digest for `setup.exe` (also matching that
  release's `SHA256SUMS.txt`); `station_index_sha256` computed against
  `station-index.json` from the `native-station-embed-c27c6e70...` build
  artifact of run 33854799455 (`manifest.product_version` confirms
  `1.0.0-beta.4`).
- `docs/releases/release-truth.yaml`: new `v1.0.0-beta.5` entry, `status:
  staging`, mirroring how beta.4 was originally recorded (PR #150).
  `v1.0.0-beta.4`'s own entry is untouched and stays `status: current`
  (flipped by PR #157); this bump only stages the next candidate behind
  it.

## [1.0.0-beta.4] - 2026-09-04

Published as [`v1.0.0-beta.4`](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.4),
a download-only upgrade for stations already on `v1.0.0-beta.3`: `setup.exe`
and the runtime `.ccpack` packs are attached to the GitHub Release, verified
by `SHA256SUMS.txt` and a signed sidecar. See
[`docs/releases/2026-09-03-beta4-release-notes.md`](docs/releases/2026-09-03-beta4-release-notes.md)
for the publish record and
[`docs/releases/v1.0.0-beta.4-verification.md`](docs/releases/v1.0.0-beta.4-verification.md)
for the verification record. `v1.0.0-beta.3` is now superseded.

### Fixed

- **Root cause of the GStreamer playout worker dying on every machine
  without a system-wide GStreamer install: the control-plane child process
  never actually got the bundled GStreamer `bin` directory on its `PATH`.**
  `station_environment_for_python` builds a `PATH` that prepends
  `<runtime>\dependencies\gstreamer\bin`, but `build_control_plane_media_env`
  composed its own `PATH` value over `os.environ` (the supervisor's stock
  LocalSystem `PATH`) instead of over the caller's already-built one, and
  that dict is merged last into the control-plane child's environment — so
  the GStreamer prepend was discarded outright on every station. Without it,
  girepository resolves `gstreamer-1.0-0.dll` with a bare-name Win32
  `LoadLibrary` call, which searches `PATH` and not the per-process
  directory list `os.add_dll_directory` feeds; the lookup failed silently,
  `Gst.URIHandler`'s GType came back `G_TYPE_NONE`, and the `gi.overrides.Gst`
  import raised `TypeError: must be an interface` — the worker died at
  import, before it could do anything else. This has been true since the
  initial commit, on every machine without a system-wide GStreamer already
  on `PATH` (every customer box, every sandbox run); a dev box with
  GStreamer installed system-wide masked it completely. Fixed by having
  `build_production_service` pass the control-plane env builder the PATH the
  caller already assembled (so the ffmpeg prepend extends the
  GStreamer-aware PATH instead of replacing it) and by having
  `bootstrap_installed_gstreamer_runtime` publish its whole computed
  environment (PATH prepend, plus `GI_TYPELIB_PATH`/`GST_PLUGIN_PATH` via
  `setdefault`) into `os.environ`, so any process holding
  `CIVICCAST_GSTREAMER_RUNTIME_ROOT` can import the staged `gi` on its own.
  Gate A evidence `20260903-225553Z` on kit `9479c56` shows the worker
  start and stay alive after the fix, against the import-time crash
  recorded in evidence `20260903-195625Z` on the same kit line before it.
  The two fixes below are real, but secondary: neither one can matter until
  the worker can import `gi` at all.
- **Secondary fix (only reachable once the worker can import `gi` at all,
  see the control-plane `PATH` root cause above): the GStreamer egress
  engine now actually puts MPEG-TS on the wire.**
  `civiccast/egress/gst/worker.py` imported its sibling modules by path
  (`import graph`) while `engine.py` prefers the package form
  (`from civiccast.egress.gst.graph import ...`). On the native Windows line the
  bundled GStreamer closure makes the engine's package import succeed, so the
  two halves bound two distinct `PlaylistLeg` classes compiled from the same
  file. `engine._instantiate_source_leg`'s `isinstance(leg, PlaylistLeg)`
  dispatch therefore missed on every program leg (`bridge.graph_from_config`
  always builds one), fell through to the `SourceLeg` branch, and raised
  `AttributeError: 'PlaylistLeg' object has no attribute 'elements'` inside
  `GstPlayoutEngine.__init__` — the worker died before the pipeline reached
  PLAYING, so the configured `udp-ts` sink never emitted a packet. Gate A's T4
  probe saw exactly that: `engine_state=FALLBACK_SLATE` and a TSDuck capture
  that timed out with zero packets, while the ffmpeg fallback on the same box
  passed. The worker now publishes each by-path sibling module under its
  `civiccast.egress.gst.<name>` key in `sys.modules`, so the engine's
  package-form imports resolve to the same objects — without importing the
  `civiccast` package (which would drag `civiccast/egress/__init__.py`, 771
  modules with sqlalchemy and pydantic, into the worker). Verified against the
  shipped runtime closure: 2651 TS packets, 0 invalid syncs, 0 transport
  errors, 1 service.

### Changed

- **Release prep: bump product version to `v1.0.0-beta.4`.** Every surface
  `scripts/policy/check_release_identity.py` binds together
  (`civiccast/_version.py`, `civiccast/_native_version.py`, the installer's
  Cargo/Tauri/package.json identities, `main.rs`'s `CIVICCAST_VERSION`, the
  OpenAPI-derived docs, the operator-console on-screen-version e2e
  expectation) plus the extra surfaces the beta.3 release-prep touched
  (`ARCHITECTURE.md`, `SUPPORT.md`, `docs/USER-MANUAL.md`,
  `scripts/download_windows_release_artifacts.ps1`,
  `docs/technical-ops-reference.md`, both lockfiles that mirror the bumped
  `package.json` versions) now read `1.0.0-beta.4`. `v1.0.0-beta.3` remains
  the current published release; this bump only advances the next
  development candidate's identity.
- **`sandbox-lab/upgrade-baseline.json` repinned to the beta.3 kit.** Now
  pins source SHA `9573d4a82e1e1d9993589f633bad6dacba792afb`, build run
  33711079441, Gate A run 33713004718, and `product_version:
  1.0.0-beta.3` -- the published beta.3 kit at
  `C:\CivicCastTester\kit-staging\9573d4a82e1e1d9993589f633bad6dacba792afb\`
  -- with recomputed installer and station-index hashes, so Gate A's
  cross-version and download-only lanes have a real, current prior build to
  upgrade `v1.0.0-beta.4` from.
- `docs/releases/release-truth.yaml`: new `v1.0.0-beta.4` entry, `status:
  staging`, mirroring how beta.3 was originally recorded before it
  published. `v1.0.0-beta.3` remains `current`.

### Fixed

- **Control-plane child process had no INFO-level logging at all, hiding
  the real cause of Gate A T4's `FALLBACK_SLATE` finding.** The supervisor
  host process configures a rotating `civiccast` package logger
  (`service.configure_logging`), but that call was never reached inside the
  separate `python -m uvicorn civiccast.app:create_app` child process the
  supervisor spawns -- so every INFO record the egress daemon and app emit
  (pipeline state transitions, fallback reasons, `last_error`, the
  GStreamer worker's launch command line) was silently dropped; only
  WARNING+ reached `control_plane.log`, via Python's handlerless-root
  `lastResort` writer. Gate A's T4 probe found
  `engine_state=FALLBACK_SLATE` on both the beta.3 and beta.4 kits with no
  diagnostic trail explaining why. Fixed with a new
  `service.configure_control_plane_logging`, called from
  `civiccast.app.create_app` when (and only when) the supervisor's
  `children.control_plane_child_spec` marks the child as supervised
  (`CIVICCAST_SUPERVISED=1`, set unconditionally, same shape as
  `CIVICCAST_EGRESS_WORK_DIR`/`CIVICCAST_UPLOAD_DIR`) -- writes to
  `%ProgramData%\CivicCast\logs\control_plane-app.log`, a file distinct
  from the child runner's raw stdout/stderr capture (`control_plane.log`)
  so the two never race a rotation rename on Windows. `EgressDaemon._write_state`
  (the one choke point every pipeline state transition and every
  `last_error` write already passes through) and `GstPlayoutStrategy.start`
  (the worker subprocess launch, argv-safe to log verbatim -- sink
  credentials are resolved into the graph JSON file, never the command
  line) now log at INFO.
- **`sandbox-lab/scripts/In-Sandbox-Report.ps1`'s T4 probe raced a cold
  start with a fixed 20s sleep and recorded only a bare `engine_state`
  string.** Replaced with a bounded poll (5s interval, 60s budget) of both
  `/state` (`engine_state` + `last_error`) and `/health` (the
  `sink_connected` map): the TSDuck capture window now opens as soon as the
  engine reports a connected sink instead of racing an arbitrary head
  start, and every poll tick plus the full final state/health bodies are
  written to `T4-ENGINE-NOTES.txt` (and `T4-ENGINE-STATE-BODY.json` /
  `T4-ENGINE-HEALTH-BODY.json`). `Test-TsProof`'s own verdict logic is
  unchanged.
- **Docs honesty: retracted the beta.3 claim that Gate A proved GStreamer
  engine egress.** The beta.3 `t4_engine` PASS was graded from a
  PowerShell null-pipeline bug in `Test-TsProof` (fixed in #145) that read
  a 0-byte, timed-out TSDuck capture on `udp/19003` as passing.
  `docs/releases/v1.0.0-beta.3-verification.md` and `docs/ops/gate-a.md`
  now say plainly that GStreamer engine egress is NOT yet proven in Gate A
  for beta.3 (re-run under the fixed grader, the engine's own state was
  `FALLBACK_SLATE`); the ffmpeg fallback path
  (`T4_RESULT=PASS_FFMPEG_FALLBACK`) is proven and remains what CivicCast
  falls back to. README's "Honestly scoped" section carries the same
  Known-limitation entry.
- **Docs honesty: "beta.1 to beta.3 is a fresh install" read as "wipe the
  station," which is not what Gate A's cross-version lane proved.** Run
  33713004718 confirmed running `setup.exe` from the **full** beta.3 kit
  (`setup.exe` plus the `station\` folder beside it) **over** an existing
  beta.1 install keeps recordings, settings, the database, and AI models,
  and migrates the schema -- the one unsupported path is running
  `setup.exe` **alone**, without the `station\` folder, from a beta.1
  install (its pack cache predates the pack-identity change and can't
  satisfy beta.3's signed index). `README.md`, `INSTALL-WINDOWS.md`,
  `docs/tester/lpm-beta-test-handoff.md`, `docs/tester/START-HERE.md`,
  `docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`, and the
  `[1.0.0-beta.3]` entry above now say this plainly instead of "fresh
  install."
- **Secondary fix (only reachable once the worker can import `gi` at all,
  see the control-plane `PATH` root cause above): a hardware video decoder
  that cannot actually decode on this machine stalled the GStreamer playout
  worker ~10s after it started, with no error on the bus.** `engine.py`'s
  `_CPU_DECODE_FEATURE_RANK` policy is a
  hand-maintained name list meant to keep `decodebin` output in system
  memory unless an operator opts into GPU decode; it covered the
  `nv*`/`cuda*`/`vaapi*`/`va*`/`d3d11*` families but not `d3d12*`, and the
  shipped runtime's `gstd3d12.dll` registers `d3d12h264dec`/`d3d12h265dec`
  above both `d3d11` and every software decoder. On a machine with no
  working GPU video-decode path (a VM, Windows Sandbox, a WARP/Basic
  Render Driver adapter), `decodebin` autoplugged the GPU decoder anyway,
  which prerolled and then delivered no buffers: the pipeline reached
  PLAYING, nothing left the mux, no bus `ERROR` was posted, and the
  worker's own stall watchdog (`_check_stall`, 10s timeout) quit and
  exited non-zero, so the daemon relaunched it in a loop -- Gate A's T4
  probe saw `FALLBACK_SLATE` with the watchdog's own explanation printed
  to stdout, into a file `station-diag` does not collect. New
  `civiccast/egress/gst/decode_policy.py` names the `d3d11`/`d3d12`
  families the runtime actually bundles and adds
  `demote_hardware_decoders()`, a post-`Gst.init` sweep that sets rank 0 on
  every registered `Codec/Decoder/*/Hardware` factory found on the running
  machine's own registry, so it cannot go stale the next time the bundled
  runtime gains a plugin (`CIVICCAST_GST_ALLOW_HARDWARE_DECODE=1` disables
  the sweep for an operator who wants GPU decode). The worker's `last_error`
  now names the actual dead engine (never says `FFmpeg` for a GStreamer
  worker) and its stderr tail is redacted and length-bounded. **Honest
  boundary carried over from the PR:** the rank defect itself is measured
  on the shipped runtime's registry; that it is *the* cause of the sandbox
  stall specifically is a well-supported inference (not reproduced inside
  Windows Sandbox in that session) -- tonight's Gate A run is what turns
  that inference into a measurement either way.
- **`In-Sandbox-Report.ps1`'s T4 probe raced a cold engine start with a
  fixed 20s sleep and recorded only a bare `engine_state` string.**
  Replaced with a bounded poll (5s interval, 60s budget) of both `/state`
  (`engine_state` + `last_error`) and `/health` (the `sink_connected` map):
  the TSDuck capture window now opens as soon as the engine reports a
  connected sink, and every poll tick plus the full final state/health
  bodies are written to `T4-ENGINE-NOTES.txt`,
  `T4-ENGINE-STATE-BODY.json`, and `T4-ENGINE-HEALTH-BODY.json` so a
  FALLBACK_SLATE result carries its own diagnostic trail instead of a bare
  string. `Test-TsProof`'s own verdict logic is unchanged.
- **Gate A verdict artifact names must use the build run id, not the Gate A
  run id.** `gate-a-station-acceptance.yml` uploads its `gate-a*-verdict-*`
  artifacts suffixed with the *build* run id (its own `run_id` step output
  is `github.event.inputs.run_id`, the build being validated), never the
  Gate A workflow's own run id -- but `download_gate_a_verdicts` formatted
  `GATE_A_ARTIFACT_NAMES[lane]` with `gate_a_run_id` (correct elsewhere, as
  the `gh run download` argument selecting which run to fetch from), so it
  looked for an artifact name that can never exist whenever the two run
  ids differ. This is the same class of bug the beta.3 publish record
  already reported for `publish_beta_candidate.py`'s own
  `download_gate_a_verdicts` call and fixed there; this PR applies the
  identical fix to the Gate A verdict-aggregation path itself and adds a
  regression test asserting both ids are used for their correct, distinct
  purposes.
- **The schema-status health check had no TTL checkpoint until the first
  request asked for one.** `/health`'s schema-status caching set its TTL
  checkpoint lazily, on first read, so a probe landing in the window right
  after a cold start (uvicorn worker boot, before any request had primed
  the cache) could read a stale or absent schema-status value. The
  checkpoint is now set once at `lifespan` startup, so every `/health`
  call after boot sees a consistently-aged cache instead of one whose age
  depends on request ordering.
- **The D3 pre-upgrade drill could report a false negative, and a rollback
  restore was not actually reachable in the flat installer layout.** Fixed
  the pre-upgrade drill's false-negative path and made the rollback
  restore's containment work against the installer's real flat directory
  layout (not an assumed nested one), so an upgrade drill failure and an
  actual rollback both do what their own status text claims.
- **The D3 rollback restore's own CLI tools were pointed at the wrong
  server and an unresolved `psql`.** The restore path invoked `psql`
  without resolving it against the installer's bundled Postgres tooling
  and without the CLI tools' own view of which server to talk to, so a
  rollback restore could fail (or silently target the wrong instance)
  exactly when it is needed most, during a failed upgrade's unwind. Fixed
  to reuse the same resolved-server, resolved-`psql` path the rest of the
  upgrade/rollback machinery already uses.
- **Installer-path audit batch: every BLOCKER and release-path MAJOR found
  in a dedicated audit of the upgrade/install/uninstall paths.** Closed a
  fail-open in the upgrade drill's BL-03/BL-04 checks (they could report
  success without actually verifying what they claimed to), corrected
  three status messages that claimed more coverage than the code checked,
  stopped an unrecognized installer flag from hanging `setup.exe` forever,
  gave uninstall refusals exit codes that mean something instead of a bare
  nonzero, gave the mandatory caption-floor model pack a content contract
  so a corrupt/partial pack is caught before it is trusted, and stopped
  the installer verifying components it never actually stages. This is
  the batch `Test-TsProof`'s null-pipeline bug (the one retracting the
  beta.3 `PASS_PRODUCT_ENGINE` grade above) was fixed inside.
- **UI walkthrough batch 6-10: publish retest, search fallback, setup
  gating, dev proxy.** A round of UI-only fixes found during a full
  operator-console click-through: publish retest after a fixed
  configuration issue now actually retests instead of leaving the last
  (stale) failure showing, search gained a fallback path for a state that
  previously rendered a blank result with no explanation, first-setup
  gating closed a path where an unconfigured station could look further
  along than it was, and the dev proxy configuration issue that made some
  of the above invisible outside a production-style build was fixed.
  Playwright was not run for this batch's UI changes in the session that
  produced it -- said so rather than claiming a run that didn't happen.

### Landed since the draft above: Gate A T4 measured a real passing engine

The three shipped-product bugs above (`engine_state=FALLBACK_SLATE` on a
worker that could not even reach PLAYING) are what made Gate A's T4
product-engine check unmeasurable for beta.3. Both PRs the draft above
tracked as open have merged, and Gate A's T4 lane now measures a real
passing engine for the first time:

- **#155 -- Gate A: real product-engine soak (T6, `SOAK_MINUTES>20`).** Adds
  a soak phase that schedules real sample clips onto all three PEG
  channels on the station's own GStreamer engine and polls TSDuck/state
  every 300s for the soak window, failing the verdict on any channel that
  is not `ON_AIR` or shows zero packets. Below `SOAK_MINUTES=20` (Gate A's
  normal CI lanes) the harness is unchanged.
- **#156 -- ship TSDuck config data files and find the shipped `tsp.exe`.**
  The packaged `tsp.exe` had its plugin DLLs but none of the `.names`/
  `.xml` data files TSDuck resolves relative to its own directory on
  Windows, so a fresh install's `tsp` failed with errors like `file not
  found: tsduck.hfbands.xml` -- this is *why* the T4 TSDuck capture itself
  could not measure the product engine even after the worker fixes above
  landed. Adds the ~1 MB of missing data files to the server pack and a
  lookup fix so the product's own `TS relay auto mode` no longer logs
  "TSDuck (tsp) not found" on an install that genuinely shipped it.

**Gate A T4 proof, as the gate wrote it.** Run
[`33837269907`](https://github.com/scottconverse/civiccast-native/actions/runs/33837269907)
against kit `4b30c99`, clean lane:

```
T4_RESULT=PASS_PRODUCT_ENGINE; tsp exited 0 over 1233 analysed packets
with 0 invalid syncs / transport errors / discontinuities
```

`v1.0.0-beta.4` is therefore the first CivicCast release whose Gate A run
measured real MPEG-TS packets from the GStreamer default engine, not the
ffmpeg fallback -- superseding beta.3's `PASS_PRODUCT_ENGINE` grade, which
was a grader false pass (see #145 above). The "first release whose Gate A
measured real engine packets" framing in the release notes and README's
engine bullet is accurate as of this run and stands.

**The 120-minute engine soak (2026-09-04, sandbox, lane PR #155 T6, kit
`4b30c99`) did NOT pass, and no wording anywhere may say it did.** Three
channels (`public`, `education`, `government`) played three real LPM
sample clips each, scheduled as premieres, for 120 continuous minutes: 22
scheduling beats x 3 channels = 66 samples, every one measured `ON_AIR`
with a passing TSDuck capture (minimum 1357 packets per 8s capture window),
worker RSS flat around 445-566 MB for the whole run. Lane verdict as the
harness wrote it:

```
T6_RESULT=FAIL reason=soak-public relaunches=8 (>3); soak-education
relaunches=6 (>3); soak-government relaunches=7 (>3) beats=22
failed_beats=0
```

The correct framing, used consistently across this file, the release
notes, the verification doc, and README: **the engine stayed live and
on-air for the full 2 hours (`failed_beats=0`); the T6 lane failed on a
relaunch-count rule, not on liveness or packet quality.** Each channel
restarted 6-8 times over 120 minutes, past T6's `>3` budget. Each restart
is a short on-air blip, not an outage. Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`.

**Correction (2026-09-05): this entry previously misdiagnosed the
restarts and is retracted.** It said the playout worker exits cleanly at
the end of every source plan (`civiccast/egress/source_plan.py`'s
`max_segments=8`), roughly every 10-15 minutes under continuous
premieres, and credited beta.5's #162 (seamless plan rollover) with the
fix. That was inferred from worker pid changes across scheduling beats,
never verified against the worker's own logs, and it is wrong: this
soak's `gst-worker.stderr.log` for all three channels contains only
`CTRL stall: no output for 10s — quitting for daemon restart` lines
(7/9/10 occurrences across education/government/public), and no EOS or
plan-end exit anywhere. A beta.5 retest soak (kit `e502074`, 2026-09-05)
shows the same pattern (8/8/7 stall lines, again no plan-end exit); plans
actually ran 28-38 minutes while restarts came 1-25 minutes apart, ruling
out a plan-boundary cause.

Two contributing issues were found in the sandbox soaks, both dated
2026-09-05: **(a)** periodic output stalls specific to the
software-encoded channels in the GPU-less Windows Sandbox test
environment, while the source preparer conforms clips synchronously on
the same box -- not established to reproduce on real station hardware
(an R7 with an iGPU, where operators have reported no such issue); and
**(b)** a real product bug -- every restart's channel-automation pass then
raised `UnicodeEncodeError: 'charmap' codec can't encode character
'\ufffd' in position 118` (the worker's stall message folds a `\ufffd`
replacement character into `last_error`, and writing it out under the
process's `cp1252` client encoding failed), skipping channel supervision
for that channel until the next tick. (b) is fixed in beta.5 by #169
(merged); #167, an earlier attempt at the same fix (ASCII-fold only, not
the underlying state-write encoding), is closed, superseded by #169.
**#162's seamless plan rollover is a real improvement for genuine
plan-boundary transitions, but it was never exercised by either soak and
is not what fixes the restarts measured here.** Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`
(beta.4) and
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-e502074-20260905`
(beta.5 retest).

**Update (2026-09-05, real tester hardware): (a) and (b) above are not
what operators actually experience.** Measured on real station hardware,
the restarts operators see -- a brief on-air blip every 10-25 minutes on a
multi-channel, CPU-only station running with live captions on -- are
driven by the live caption tap, not by a sandbox artifact or the encoding
bug above. `civiccast/captions/tap_worker.py` transcribes every `ON_AIR`
channel in-process on CPU; with three channels captioning at once it
exceeds its own settled-segment backlog limit roughly every 30 seconds
(`CRITICAL civiccast.captions.tap_worker: Caption tap overload for
channel <id>: N settled segments exceeds the maximum 2 ...`) and never
backs off, driving the control-plane process to ~2.5 CPU cores and
starving the GStreamer playout workers -- each worker's own 10-second
stall watchdog then fires and exits, which the daemon relaunches. Fixed
in beta.5: #169 (the state-write `UnicodeEncodeError` above, a real bug
but not this driver). The caption-tap overload fix itself has no merged
PR yet (PR pending). **Workaround for beta.4 operators: none in the
product.** `CIVICCAST_CAPTION_TAP` is the only switch for the live
caption tap, and a native station's control-plane process hardcodes it
to `inline` unconditionally (`civiccast/native/station_runtime.py:1361`)
-- there is no per-channel or operator-console setting to turn live
captioning off on a beta.4 station.

**Known issues in beta.4:**

1. Each channel's playout worker restarts periodically under continuous
   premiere scheduling (a short on-air blip each time). Previously
   misattributed to plan-end exits and credited to beta.5's #162 --
   retracted 2026-09-05; see the correction above. Contributing issues
   found in the sandbox soaks: (a) sandbox-specific output stalls, not
   established on real hardware; (b) an automation `UnicodeEncodeError`
   on every restart, a real product bug fixed in beta.5 by #169 (#167,
   an earlier attempt, is closed/superseded). #162 is a genuine
   plan-boundary-transition improvement but does not address either
   issue.
   **What operators actually see, measured on real tester hardware
   (2026-09-05): a brief on-air blip every 10-25 minutes on a
   multi-channel, CPU-only station with live captions on**, driven by the
   live caption tap (`civiccast/captions/tap_worker.py`) transcribing
   every `ON_AIR` channel in-process on CPU. On three simultaneous
   channels it exceeds its own backlog limit every ~30 seconds (`CRITICAL
   civiccast.captions.tap_worker: Caption tap overload for channel <id>:
   N settled segments exceeds the maximum 2 ...`), never backs off, and
   drives the control-plane process to ~2.5 CPU cores, starving the
   GStreamer playout workers -- their 10-second stall watchdog then
   exits, which the daemon relaunches. Fixed in beta.5: #169 (the
   encoding crash above). The caption-tap overload fix itself has no
   merged PR yet (PR pending). **Workaround for beta.4: none in the
   product** -- `CIVICCAST_CAPTION_TAP` is hardcoded to `inline` on every
   native station (`civiccast/native/station_runtime.py:1361`), with no
   per-channel or operator-console setting to disable it.
2. TSDuck data files now shipped beside `tsp.exe` (#156, above).
3. **Upgrade over a running beta.3 station fixed (#159).** Before the fix,
   the upgrade's provision step unconditionally start/stopped a PostgreSQL
   cluster the freshly started station service already owned and had
   running -- that collision with the live service's own instance of the
   same cluster failed the install and forced a crash recovery of the
   database on the next successful start. The fix has the provision step
   recognize a cluster the running station already owns and migrate it in
   place instead of restarting it out from under the live service.

The final beta.4 kit, `c27c6e7`, adds only the #159 fix above on top of
`4b30c99` -- it does not touch the GStreamer engine, TSDuck packaging, or
the Gate A T4/T6 harness, so the T4/T6 results above stand for it
unchanged. Its own three-lane Gate A run
([`33901203343`](https://github.com/scottconverse/civiccast-native/actions/runs/33901203343))
passed all three lanes -- clean install, cross-version upgrade (over the
pinned beta.3 baseline, including the independent `psql` schema proof), and
download-only -- see
`docs/releases/v1.0.0-beta.4-verification.md` for the per-lane evidence.

### Changed

- **Release prep: bump product version to `v1.0.0-beta.5`.** Every surface
  `scripts/policy/check_release_identity.py` binds together
  (`civiccast/_version.py`, `civiccast/_native_version.py`, the installer's
  Cargo/Tauri/package.json identities, `main.rs`'s `CIVICCAST_VERSION`, the
  OpenAPI-derived docs, the operator-console on-screen-version e2e
  expectation) plus the extra surfaces the beta.3/beta.4 release-preps
  touched (`ARCHITECTURE.md`, `SUPPORT.md`, `docs/USER-MANUAL.md`,
  `scripts/download_windows_release_artifacts.ps1`,
  `docs/technical-ops-reference.md`, both lockfiles that mirror the bumped
  `package.json` versions) now read `1.0.0-beta.5`. `v1.0.0-beta.3` remains
  the current published release; this bump only advances the next
  development candidate's identity.
- **`sandbox-lab/upgrade-baseline.json` repinned to the published beta.4
  kit.** Now pins source SHA `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`,
  build run `33854799455` (`native-beta-candidate-artifacts`, conclusion
  `success`), Gate A run `33857982657`, and `product_version:
  1.0.0-beta.4` -- installer hash verified against the GitHub Release
  `v1.0.0-beta.4` asset digest for `setup.exe`
  (`9fae1211c8cb1f7d51c59d3088e0dd1d311be32493652b61917efebc0274628f`, also
  matching `SHA256SUMS.txt` on that release) and station-index hash computed
  against `station-index.json` from the `native-station-embed-c27c6e70...`
  build artifact of run `33854799455` (its `manifest.product_version` reads
  `1.0.0-beta.4`, confirming it is the right file). `gate_a_run_id`
  (`33901203343`) is the successful three-lane Gate A run for this candidate
  -- clean station-acceptance PASS (including `PASS_PRODUCT_ENGINE`),
  cross-version-upgrade PASS, and download-only-upgrade PASS. That run was
  dispatched via `workflow_dispatch` against `main` with `run_id` /
  `source_sha` supplied as parameters (`Run-GateA.ps1 -SourceSha
  c27c6e70200406b51558ee1ef6b3a95ee4dc4426 -RunId 33854799455`), so its own
  GitHub Actions `head_sha` shows the dispatching commit on `main`, not the
  candidate's -- its logs and `gate-a-verdict.json` confirm it built and
  judged the `c27c6e70...` kit, not `main`.
- `docs/releases/release-truth.yaml`: new `v1.0.0-beta.5` entry, `status:
  staging`, mirroring how beta.4 was originally recorded. `v1.0.0-beta.4`'s
  entry is untouched and stays `status: staging` (it has not yet been
  flipped to `current` on `main`; that flip is tracked separately in PR
  #157 and is out of scope for this identity bump).

### Fixed

- **`civiccast/egress/gst/graph.py`'s `source_leg_is_clock_timed` docstring
  claimed the fail-safe answer for an unknown source factory is `True`; the
  code has always returned `False`.** `_chain_is_clock_timed` only returns
  `True` when a chain's factory is listed in `CLOCK_TIMED_SOURCE_FACTORIES`
  or an element carries `is-live=True`; an unrecognized factory with no
  `is-live` property matches neither, so `any(...)` over the chains returns
  `False` -- segment-timed, the same "no hold, no rebase" default the
  module's own property-level comment already (correctly) documented two
  paragraphs above the docstring that contradicted it. Fixed the docstring
  to say `False` and explain why that is the safe default (a
  boundary-aligned rollover neither holds nor rebases an unrecognized leg,
  rather than risking staling a leg that turns out to be live). Also added
  the Windows live-capture device factories -- `ksvideosrc`, `mfvideosrc`,
  `dshowvideosrc`, `wasapi2src`, `wasapisrc` -- plus Linux's `v4l2src`, to
  `CLOCK_TIMED_SOURCE_FACTORIES`: a physical/OS capture device is
  always-live, the same class of source as the `decklink*src` entries
  already listed, even though no ingest graph builder in this repository
  instantiates one of these yet. **Deliberately did NOT add
  `interpipesrc`/`interpipesink`**: the RidgeRun interpipe plugin was
  demoted from the shipped GStreamer closure by an owner-confirmed spec
  decision (alongside `compositor`/`hlssink3`/`pango`) and is not wired
  into any ingest or playout graph this repository builds --
  `civiccast/native/runtime_closure.py` already documents it as
  "deliberately NOT here." New `TestSourceLegIsClockTimed` cases in
  `tests/egress/test_gst_graph.py` pin both: the new Windows/Linux capture
  factories answer `True`, and an unrecognized factory (including
  `interpipesrc`, to document it is treated as any other unknown factory)
  answers `False`.

## [1.0.0-beta.3] - 2026-09-03

Published as [`v1.0.0-beta.3`](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.3),
the first downloadable CivicCast release: `setup.exe` and the runtime
`.ccpack` packs are attached to the GitHub Release, verified by
`SHA256SUMS.txt` and a signed sidecar. See
[`docs/releases/2026-09-03-beta3-first-downloadable-release.md`](docs/releases/2026-09-03-beta3-first-downloadable-release.md)
for the publish record. `v1.0.0-beta.1` (USB-delivered, no downloadable
assets) is now superseded. `v1.0.0-beta.2` was never published -- it exists
only as an internal Gate A upgrade-baseline kit (see the "Changed" entry
below).

### Added

- **WP-11 item 1 — Recording form accessibility.** Every field-validation
  message on the operator Scheduled Recording form
  (`apps/portal-operator/src/screens/RecordingScreen.tsx`) now has a stable
  id, and the offending control (or, for the weekday checkboxes, the
  `role="group"` wrapper) carries `aria-invalid` and `aria-describedby`
  pointing at it. A failed submit moves keyboard/screen-reader focus to the
  first invalid control in field order (slug -> name -> source -> recurrence
  -> duration -> encoder profile) instead of leaving focus on the "Create
  schedule" button or the form heading. Covered by new unit assertions in
  `RecordingScreen.test.tsx` that read the real `aria-invalid` /
  `aria-describedby` DOM attributes and `document.activeElement` (not just
  the visible copy), and by two new `e2e/a11y.spec.ts` cases that exercise
  the same flow with axe-core against a real browser render. That axe scan
  also caught a pre-existing `color-contrast` defect (serious) on `main`:
  every plain-surface validation/notice span in this form used
  `var(--cc-warn)` text on the section's `var(--cc-surface)` background
  (~3.8:1 in light theme, under the 4.5:1 AA floor for normal text) — never
  axe-scanned before this PR added the first Recording-screen a11y
  coverage. Switched to `var(--cc-err)` (~6.2:1) for every such span in the
  file, not just the four the CI run happened to render simultaneously.

- **WP-11 item 2 — Lower-third help copy.** Channel Ops' lower-third-banner
  control (`GraphicsOverlayPanel` in
  `apps/portal-operator/src/screens/ChannelOpsScreen.tsx`) no longer calls
  itself a "station bug graphics overlay" — that's a different broadcast
  graphic (the corner logo) from the lower-third text banner this control
  actually edits. The copy now says plainly that the change lands on the
  selected channel's lower-third banner on the next pipeline build or a
  scheduled swap, and does not hot-change an already-live pipeline. Pinned
  by a new focused test in `ChannelOpsScreen.test.tsx`.

- **WP-11 item 3 — CivicSuite/CivicClerk bridge truth card.** `AgendasScreen`
  now shows a disabled "CivicSuite event bridge — coming in a future
  release" card beside the existing agenda-import configuration
  (`ExternalImportSection`), with no executable configuration fields. The
  card states the real distinction: CivicCast's manual/public CivicClerk
  agenda importer (also Legistar, PrimeGov, and a generic portal crawler)
  already works today and is unchanged; the CivicSuite event bridge is a
  separate, not-yet-built authenticated integration that would receive a
  jurisdiction's meeting lifecycle events automatically and send published
  recording links back to CivicClerk. A new regression suite in
  `AgendasScreen.test.tsx` asserts the working importer and the future
  bridge are never conflated.

- **WP-11 item 4 — Podcast "coming soon" card (owner decision 2026-09-02).**
  The operator Publish dashboard's podcast surface row
  (`apps/portal-operator/src/screens/PublishDashboardScreen.tsx`) is now
  always a neutral "Coming in a future release" card, regardless of the
  state/health this asset's row happens to carry: no red error framing, no
  "Approve this surface" checkbox, no retry button, and it is excluded from
  the pre-checked/submittable surface set an "Approve and Publish selected"
  click sends. The message text is aligned with the preflight API's
  `health="unknown"` copy ("Podcast is not available yet; it is coming in a
  future release."). Backend behavior is unchanged (WP-03/#129 already
  reports podcast preflight as not-available) — this closes the gap where
  the dashboard's own asset-listing surface still defaulted podcast to a
  selectable `state="pending"` row that could be checked and submitted.
  Four new tests in `PublishDashboardScreen.test.tsx` cover the neutral
  card, the missing checkbox, the never-red-even-if-backend-reports-failed
  case, and that approval excludes podcast from `approved_surface_ids`.

- **WP-11 item 5 — Publish preflight in the UI (gap found in review of
  #129).** The operator Publish screen never called `GET
  .../assets/{id}/preflight`, so an operator could select a surface with
  missing/invalid real-provider configuration and only find out from the
  approval 409 after clicking. `PublishDashboardScreen.tsx` now shows a
  per-surface readiness panel (`getPublishPreflight`, new hand-curated
  `PublishPreflightResponse`/`PublishPreflightCheck` types in
  `types/publish.ts` mirroring PR #129's backend models) for every asset,
  before the approve action: loading state, ready/not-ready per surface
  with the API's own safe next-step text, the podcast future-release
  surface (never rendered "not ready"), and a load error with a retry
  action. "Approve and Publish selected" now also stays disabled while any
  SELECTED real (non-future) surface's readiness check reports
  `health="error"`; a still-loading or failed readiness fetch adds no new
  block of its own (approval's existing 409 refusal remains the real
  backstop). Six new tests in `PublishDashboardScreen.test.tsx` cover
  ready/not-ready/future/load-error-with-retry and the approve-disabled
  gate; `e2e/publish-dashboard.spec.ts` gained a default preflight route
  mock plus a dedicated not-ready-blocks-approve case (Playwright was not
  run in this session — say so rather than claiming a run that didn't
  happen).

### Changed

- **A configured live source is no longer treated as ready just because it
  exists.** Readiness is now an observation with an age (audit finding
  ENG-003, ADR 0025). `civiccast/live/relay.py::_source_path` used to stamp
  `health_state='ready'` on every configured `live_sources` row, and that
  health value is the only gate
  `civiccast/egress/live_takeover.py::build_live_takeover_source_plan` applies
  before a manual takeover writes a takeover audit row and queues a
  route-change command -- so a camera that had been unplugged for a week looked
  exactly like a live encoder. Migration `0086_live_source_probe_state` adds
  `probe_state` / `probe_observed_at` / `probe_detail` / `probe_error_code` /
  `probe_last_success_at` / `row_version` to `live_sources`; existing rows
  backfill to `never_probed`, not to ready. Four operator-facing states
  (`never_probed`, `ready`, `stale`, `failed`) are derived against a readiness
  TTL -- 30s by default, `CIVICCAST_LIVE_SOURCE_READINESS_TTL_SECONDS`, clamped
  to the accepted 5-300s range. `stale` is deliberately never persisted: it is
  a function of the clock, and a stored "stale" would outlive the successful
  probe that should have cleared it.
- **A configured live source is visible to production takeover.**
  `civiccast/app.py::_resolve_takeover_service` built its ingest-plan provider
  from relay configuration only, while `/api/staff/live/ingest-plan` had
  already been fixed to include the channel's `LiveSourceStore` rows -- so a
  source could appear in the API plan and be invisible to the takeover service
  that actually changes air, and a station with no relay row (the default) had
  nothing takeover could select. `civiccast/cli.py::_build_takeover_service`
  carried the identical omission. Both now read the same channel-scoped rows.
- **A manual takeover re-checks the source before anything durable happens.**
  `TakeoverService.take` calls an injected readiness verifier after the source
  plan is built and *before* the audit row is written or the command is
  queued: a within-TTL success is reused, anything else gets one bounded fresh
  probe, and a source edited between the operator's ingest plan and the Take
  fails closed. Stale, failed, and never-probed sources create no takeover
  audit row, queue no command, and cannot change air.
- **The `credentials_handle` column is no longer a dead surface for reading.**
  `civiccast/live/secrets.py` resolves it through the station's OS credential
  store at execution time -- per probe, so rotating a passphrase takes effect on
  the next check without a restart -- and, for playout, carries the *handle*
  (never the secret) through the durable takeover audit row and the engine's
  on-disk graph file in a new `ElementSpec.secret_props`, resolved by the
  worker at element-construction time. Only SRT can hold one: its passphrase is
  a first-class option on both runtimes (`ffprobe -passphrase`, `srtsrc
  passphrase=`), so it never enters a URL, a row, a log line, or proof output.
  Authenticated RTSP and RTMP shapes are rejected with explicit operator copy
  and a disabled UI control, because neither FFmpeg protocol accepts a
  password anywhere except inside the address. Missing or unreadable secrets
  fail the probe closed; every probe detail is secret-redacted. **Readable
  handle contract only; no write path yet:** `save_live_source_secret` has no
  caller anywhere in the product (no route, CLI, or UI writes an SRT
  passphrase into the OS credential store), so a live source's stored secret
  can only be set today by a caller reaching into `civiccast.live.secrets`
  directly. There is also an open per-user-vault-vs-LocalSystem gap: `keyring`
  on Windows is the signed-in user's own per-user vault, while the CivicCast
  supervisor service is registered and runs as `LocalSystem`
  (`civiccast/apps/installer/src-tauri/src/native_service_registration.rs`),
  so a secret saved from an interactive operator session would not
  necessarily be visible to the service process that actually needs it at
  probe/playout time. See ADR 0025's "Known gaps" section for the two
  resolution options under consideration (write from the service process, or
  a machine-scoped credential store).
- **Subscriber notifications now honestly report "coming in a future
  release" instead of a fabricated green "succeeded" (owner decision
  2026-09-02).** Real subscriber notification sends (mail/webhook fan-out on
  publish) are deferred to a future release — the implementation is parked
  on `feat/publish-real-subscriber-delivery`, not merged. Until now,
  `civiccast/publish/service.py`'s `approve_publish` built a
  `NotificationPayload` for the "subscriber-notifications" surface,
  never dispatched it, and still marked the surface `state="succeeded"` —
  an operator approving publish saw a green "sent" state for a notification
  that was never delivered. It could also block an otherwise-ready publish
  with a 409 if a real mail/webhook provider was misconfigured, even though
  nothing was ever going to send. The surface now always reports a new
  `state="coming_soon"` (`health="unknown"`) with the plain-language message
  "Subscriber notifications are coming in a future release. No emails or
  webhooks are sent yet.", is excluded from approval's provider-readiness
  precheck so it can never block publish, and sends nothing. The operator
  Publish dashboard (`apps/portal-operator/src/screens/PublishDashboardScreen.tsx`)
  shows it as the same neutral "Coming in a future release" card already
  used for the podcast surface (WP-11 item 4) — no checkbox, no red error,
  never selectable or approvable. `civiccast.publish.readiness`'s real
  per-provider subscriber-channel check is unchanged and still directly unit
  tested (`tests/publish/test_provider_readiness.py`); service.py simply no
  longer routes through it for this surface while the send is parked.
  New/updated coverage: `tests/publish/test_provider_readiness.py`,
  `tests/publish/test_router.py`, `tests/publish/test_soak.py`,
  `civiccast/apps/portal-operator/src/screens/PublishDashboardScreen.test.tsx`.

- **The public subscription RSS feed no longer invents a fake recording.**
  `civiccast/subscribe/router.py`'s `GET /api/public/subscribe/rss/{target_type}/{target_id}.xml`
  used to serve a single hardcoded `<item>` — title "Example CivicCast
  recording", link `https://portal.example/watch/{target_id}` — on every
  request, indistinguishable from a real published recording to any reader
  or aggregator. There is no published-recording resolver wired to this
  route yet, so it now returns an honest, valid, empty RSS 2.0 feed (zero
  `<item>` elements) instead of a fabricated one. New coverage:
  `tests/subscribe/test_subscribe_router.py`.

- **Ordinary tests can no longer touch the operator's real CivicCast state.** A
  central autouse fixture (`tests/conftest.py`, helpers in
  `tests/support/hermetic_state.py`) now points every state, lock, upload,
  managed-storage, egress, TSDuck, certificate and secrets default beneath the
  test's own temporary root, and a teardown guard fails any test that creates,
  rewrites or deletes a file under the real `%LOCALAPPDATA%\CivicCast` or
  `~/.civiccast`. The few tests that verify the installed-path contract itself
  opt out with `@pytest.mark.installed_paths` (they still get the guard).
  Proven by running the app-factory suites with the real `%LOCALAPPDATA%`
  pointed at an unwritable location. Seventeen test env-var names misspelled
  `CIVICAST_` (so their "worker off" and state-path settings never applied)
  are corrected.

### Fixed

- **The D3 rollback restore handed its CLI tools the wrong server address and
  an unresolved `psql` (installer-path audit BL-01, follow-up).** Two wiring
  defects on one line of `build_default_seams`, both surfaced by BL-01's own
  Postgres proof failing in CI's real-Postgres lane:
  - `default_restore_backup` never accepted `command_database_url`, so it
    passed `context.database_url` — the HOST-reachable URL every direct
    SQLAlchemy read needs — to `psql` and `pg_restore`, which parse it for
    their own `--host`/`--port`. Where those commands carry a prefix that
    relocates them (the `docker exec` pattern the DR suite and the engine's
    own Postgres proof both use), the restore aimed at a host port from
    inside the container: `connection to server at "localhost", port 32803
    failed: Connection refused`. `run_postgres_restore` raised, `_rollback`
    went to `_halt`, and the run reported `HALTED_RESTORE_FAILED` — BL-01's
    own symptom, reproduced by BL-01's own fix, and the reason its proof
    could not execute. `default_backup` has always honoured this split; the
    restore path never did, even though the engine's own
    `_PG_CLIENT_EXECUTABLES` doc already named "`pg_restore` again on the
    rollback path" as one of the four commands that has to be resolved.
  - `psql_command` was not threaded to the restore seam either. The BL-01
    rollback newly calls `create_fresh_postgres_database`, which shells to
    `psql`; without the resolved path it fell back to
    `civiccast/dr/backup.py`'s bare-name default and resolved `psql` through
    `PATH`. The installer writes no `PATH` entry and these binaries ship only
    inside the staged `native-server-binaries` pack, so on a real Windows
    station that is a filename-less `WinError 2` — the Sandbox run 22 defect
    class `_resolve_pg_client_commands` exists to prevent, reintroduced on
    the one path that runs when an upgrade is already going wrong. This one
    never showed in CI, whose container has `psql` on `PATH`; it would have
    shown on stations.

  Production behaviour is unchanged wherever `command_database_url` is `None`
  (one reachable Postgres, no container indirection) — which is every real
  install. Three new tests pin the wiring at the seam boundary and are RED
  without the fix.

- **`/health` readiness ignored its own TTL cache and could report a stale
  schema verdict as live-refreshed.** `civiccast/app.py`'s lifespan startup
  set `app.state.schema_status` but never set the paired
  `app.state.schema_status_checked_monotonic` checkpoint that
  `_maybe_refresh_schema_status` uses to honor `SCHEMA_STATUS_TTL_SECONDS`.
  With that checkpoint left `None`, every single `/health` request treated
  the cache as unconditionally expired and recomputed
  `check_schema_currency` from scratch — opening a database connection on
  every poll instead of the intended 5-second TTL window, and silently
  discarding any schema status a caller had set directly in between (e.g. a
  test simulating the `unknown` schema state). The checkpoint is now set
  alongside the status at lifespan startup, matching what
  `_refresh_schema_status` already does for the mid-flight "Prepare storage"
  path. Caught by `tests/test_health_readiness.py::
  test_unknown_schema_state_is_degraded_not_healthy`, which failed
  deterministically (not just under randomized ordering) before this fix.
  Also updated `test_schema_behind_the_code_is_degraded`'s fixture: it used
  a synthetic revision id (`0001_ancient_revision`) that was never a real
  entry in this repo's migration graph, so under the ahead/behind
  distinction added by installer-path-audit finding MA-06
  (`evaluate_schema_currency` — a revision the graph doesn't recognize is
  `ahead`, not `behind`) it always classified as `ahead`. Swapped in a real,
  superseded revision id (`0001_create_assets_table`) so the test still
  exercises the `behind` path it names.

- **Installer-path audit (2026-09-03) — the whole install / upgrade /
  activation / health path, in one batch.** A read-only audit of the NSIS
  bootstrap, the installer Rust CLIs, the D3 upgrade engine, the DR
  backup/restore drill, schema currency + `/health`, the pack/station-index/
  cache path, the Gate A harness and the test suites returned 84 findings
  against `main` @ `9573d4a`. Its central observation is one defect class:
  *a verdict is read from a proxy — a status code, an exit code, a label, a
  file's existence, a non-empty list — instead of from the substantive value,
  and the test that should have caught it constructs both sides of the
  comparison from the same source at the same head.* Every BLOCKER and every
  release-path MAJOR is fixed here, one entry per finding id.

  Gate A's instruments first, because everything else is graded by them:

  - **BL-10** — `POST_UPGRADE_DB_REVISION_MATCHES_HEAD`, added by PR #143 to
    stop trusting a label, *was itself the label and could not fail*:
    `$healthRes.ok` requires `body_schema == "current"`, `civiccast/app.py`
    sources both revisions from one `SchemaStatus`, and
    `evaluate_schema_currency` returns `"current"` **iff** they are equal.
    The check now compares the live database's own `alembic_version` row
    (read in the sandbox with `psql`) against the migration head the CI job
    derives at build time from the candidate's own migration files
    (`scripts/gate_a_expected_head.py`), and the judge re-derives the match
    instead of reading the flag.
  - **BL-09** — `In-Sandbox-Report.ps1`'s `finally` set
    `harness_completed = $true` unconditionally, including after the `catch`
    that swallows any throw from its 1500-line `try`, and it deleted
    `WATCHDOG-TIMEOUT.txt` on the way past. Completion is now promoted by the
    last statement of the `try`; the judge's own self-comparison
    (`summary.json.last_completed_step` vs `DONE.json.last_completed_step`,
    written microseconds apart from one variable) is replaced by assertions a
    crashed run cannot satisfy.
  - **MA-23 / MA-24 / MA-25** — `install-progress.log` is append-only across
    both install phases and the capture kept the last match in the whole
    file, so a phase-2 installer that died early inherited phase 1's
    `route=FRESH_INSTALL engine_exit=11`; the download-only check claimed to
    prove D4 activation while reading D3's exit code; and the clean lane
    graded that log not at all. Now phase-scoped, with D4's own exit and the
    postinstall outcome judged in every lane.
  - **MA-26 / MA-27 / MN-20** — T3's `health-200` and every T5 soak beat read
    `.StatusCode` alone (one run recorded `T5_RESULT=PASS beats=2
    unhealthy=0` over a `degraded`/`schema:behind` station); a 0-byte TSDuck
    report produced `verdict=pass` because `Get-Content -Raw` returns `$null`
    and PowerShell's pipeline drops it, so `ConvertFrom-Json` never ran; and
    `beats=0` passed the soak. All three now fail closed.
  - **MA-38 / MA-39 / MA-40 / MA-41 / MN-19** — the DR test floor was one
    below the real count (so PR #143's only DR proof could vanish silently)
    and is now derived from the source; the release-branch job's silent skip
    of the one cross-version D3 proof is named; an `or` clause that subsumed
    its own ordering assertion is deleted; a `pytest.skip` that erased the R7
    regression case on any machine that has ever installed CivicCast is
    replaced; and the Gate A hoststore reset now states its post-condition.

  The product side of the same class:

  - **BL-11** — nothing in the entire elevated install chain ever contacted
    `/health`; SCM `RUNNING` was the only success signal the installer had,
    which is why Gate A run 33681670855 wrote `InstalledVersion`, exited 0
    and showed a success page over a station serving 500s. D4 service
    registration now polls `/health` and requires `status: healthy` with a
    current schema, failing with its own exit code and a truthful message.
  - **BL-02** — every failed POSTINSTALL left `CivicCastSupervisor`
    registered `--startup auto` over the NEW payload, so the operator's next
    reboot restored the exact state PR #143 was written to prevent. Failures
    now stop the service and set it to manual start before aborting.
  - **BL-12** — a reinstall over a preserved cluster could route
    FRESH_INSTALL, take provisioning's reuse path (the one route that never
    migrated), stamp the new `InstalledVersion` anyway, and report
    SAME_VERSION_NO_OP forever afterwards. The reuse path now migrates, and
    BL-11's gate runs before the marker is written.
  - **BL-13 / MA-32** — an unprovable `ActiveRuntime` selector printed a
    sentence saying the runtime would not start and returned `Ok`; and
    "already provisioned" was the mere presence of a registry string. Both
    are now real, fail-loud checks with their own exit codes.
  - **MA-07 / MA-08 / MA-28 / MA-29** — the installer's own health probe was
    200-only; five distinct activation exit codes collapsed into one message
    naming the wrong cause; exit code 74 meant three different things while
    the comment beside it said "74 is free"; and the `.nsh`'s CLI-contract
    comment listed a set that was wrong in both directions.

  The D3 engine:

  - **BL-01** — the rollback's `pg_restore` had no `--clean`/`--if-exists`/
    `--create` and restored into the live database, so it always hit
    `relation already exists`: **the clean-rollback outcome (exit 10) was
    unreachable for every post-migration failure**, while three shipped
    comments and one operator dialog asserted the opposite. The restore now
    drops and recreates the target under the held interlock and replays in
    one transaction, after re-hashing the artifact against its manifest.
  - **BL-03 / BL-04** — `post_schema_revision` was written and never read, so
    a no-op `alembic upgrade head` committed COMPLETE; and the maintenance
    health gate names no version or revision, so the OLD supervisor could
    certify the upgrade by attesting to itself. Both now check.
  - **BL-05 / BL-06 / BL-07** — a second concurrent installer released the
    first one's interlock mid-migration; a preserved terminal journal
    returned the previous run's outcome forever (which PR #143 made a fatal
    abort, bricking the upgrade path); and a raise from `stop_service` or the
    recovery-document write escaped as "unexpected fault", leaving no journal
    and no `UPGRADE-RECOVERY.md` — the one artifact designed for exactly that
    case.
  - **MA-01 / MA-02 / MA-05 / MA-06** — under the only layout production runs
    the journal claimed a payload revert that cannot happen and the recovery
    document named a junction that does not exist; the previous junction
    target was persisted after the flip rather than before; there was no
    ordering comparison anywhere, so an older setup.exe drove `alembic
    upgrade head` toward an older head; and there was no `ahead` schema
    state, so a newer database was reported as "behind" with advice that
    cannot work.
  - **MA-09 / MA-10 / MA-11 / MA-12 / MA-13 / MN-08 / MN-09** — `verified`
    was a non-emptiness check; the SQLite manifest was snapshotted from the
    artifact the drill then compares to a copy of itself; the drill's verdict
    was true over zero compared tables; the quiescence proof compared two
    copies of sha256-over-nothing; `/health`'s schema verdict was a boot-time
    snapshot never refreshed; a drill database inherited `template1`'s
    encoding; and `DROP DATABASE ... WITH (FORCE)` had no same-name guard.

  Packs, activation and repair:

  - **BL-08** — the owner-designated **mandatory** caption FLOOR model
    reached no branch of `validate_component_contract` at all, so the
    complete set of machine checks on it was the signature, the component id,
    and two values the publisher chose and signed in one operation. Pointing
    `--captions-floor-root` at a different model shipped an unreviewed ASR
    model to every station on the legally non-negotiable captions path with
    every gate green. It now has the same pinned content contract large-v3
    has always had.
  - **MA-04 / MA-15** — `validate_staged_runtime_layout` never ran on the
    path that ships, and an index component this build does not know was
    downloaded, fully verified, then silently dropped. Both are fixed on the
    flat activation path.
  - **MA-03** — flat activation deleted the manifest, the receipt and every
    component tree before extracting, with no free-space check anywhere in
    the crate; it now measures and refuses first, naming the byte figure.
  - **MA-19 / MA-20 / MA-30 / MA-37** — two hand-maintained
    `REQUIRED_COMPONENTS` copies with nothing binding them; a guard test
    asserting that an array's elements are in that array; D5 repair returning
    `Unrepairable` on **every** healthy activated station because the
    per-SHA cache directory was enrolled as a component; and an idempotency
    probe whose doc guarantee was stronger than its code.

  Also fixed from the same batch's owner-observed list: the "TSDuck
  (`tsp.exe`)" Windows Security prompt that appeared inside the sandbox on
  every install test — the elevated in-sandbox harness now authors the
  firewall allow rules itself before the first bind.

- **UI walkthrough batch (2026-09-03), items 6-10.** Five findings from the
  2026-09-03 full UI walkthrough
  (`CIVICCAST-UI-WALKTHROUGH-2026-09-03.md`), triaged and fixed together:
  - **Item 6 (MAJOR-1, `_EphemeralAssetStore.mark_packaged`) — already
    fixed at this SHA, no change needed.** Investigated first since the
    walkthrough reproduced it "on two separate fresh backend boots" at the
    same commit this batch branched from. `civiccast/app.py`'s
    `_EphemeralAssetStore.mark_packaged` (added in #96, 2026-08-30) exists
    and works — confirmed by direct instantiation
    (`_EphemeralAssetStore().mark_packaged` is present, not an
    `AttributeError`). The walkthrough's reproduction predates that fix
    reaching its environment; no product change was needed or made.
  - **Item 7 (MAJOR-2, "Approve and Publish selected" did not visibly
    complete) — confirmed NOT a product bug; the walkthrough's own
    browser-automation-targeting caveat was correct.** Ran the repo's
    existing full-stack Playwright coverage
    (`apps/portal-operator/e2e/full-stack-publish.spec.ts`, tag
    `@fullstack`) against a real backend fixture. It failed on an
    unrelated, pre-existing locator ambiguity — `PublishDashboardScreen`'s
    newer "Publish readiness" preflight panel (added since this test was
    last touched) names every surface a second time, so
    `getByText('Local NAS rsync', { exact: true })` etc. now match two
    elements. Scoped those four presence assertions to `.first()` (the
    later structural assertions — `toHaveCount(3)` for the
    archive-simulated warning, `toHaveCount(0)` for a real `archive.org`
    URL — are untouched and stay exact). With that test-staleness fix
    applied, the full approve-and-publish cycle passes end to end: Portal
    moves to public, IA/NAS report verified, and the TW-1
    simulated-vs-real archive labeling is correct. No publish-flow product
    code was changed.
  - **Item 8 (MAJOR-3, public "Browse recordings" 503s under
    ephemeral/dev storage) — added a graceful fallback.**
    `RecordingsScreen` (`apps/portal-public/src/screens/RecordingsScreen.tsx`)
    now falls back from `/api/public/search` to the simpler
    `/api/public/assets` list (already used by `HomeScreen`) specifically
    on a 503, rather than hard-failing the whole screen. A new `degraded`
    load state shows a visible amber note that search is temporarily
    reduced; search/year/body/custom-field facets keep working
    client-side over the fallback set (custom-field values just won't be
    present until search recovers — that projection is search-only, see
    `types.ts`). Any other failure (network error, 500, …) still shows the
    existing plain error state and does not attempt the fallback. New
    `RecordingsScreen.test.tsx` covers all three paths (503-then-fallback,
    503-then-fallback-also-fails, non-503-skips-fallback).
  - **Item 9 (MINOR-1, First Setup fires unauthenticated staff-API calls
    before sign-in) — stopped the guaranteed-401 case.** SetupScreen's own
    `staff-identity` query (`GET /api/staff/auth/me`) fired unconditionally
    on every mount, even with no staff token stored anywhere — a request
    that cannot succeed. It's now gated on a new
    `hasStoredStaffToken()` export (`apps/portal-operator/src/api/client.ts`)
    via `useQuery({ enabled })`, mirroring the same key's shell-level
    gating in `App.tsx`. Login/setup mutations still reset this query key
    on success, so identity refetches immediately once a token exists.
    Pinned by a new test in `SetupScreen.test.tsx` asserting
    `/api/staff/auth/me` is never requested for a signed-out visitor with
    an empty token store.
  - **Item 10 (MINOR-2, `portal-public/vite.config.ts` had no `/api` dev
    proxy) — added one, matching `portal-operator`'s.** Proxies `/api/*` to
    `http://127.0.0.1:8000` by default, overridable with
    `VITE_CIVICCAST_API_PROXY_TARGET` when that port is already taken
    (e.g. another station already running). Documented in
    `apps/portal-public/README.md`'s "Run locally" section, including the
    override example.

- **Release-blocking: D3 pre-upgrade backup verification compared the
  restored copy against the wrong revision, and the flat-installer-layout
  rollback containment let setup continue anyway.** Gate A run 33681670855
  (kit 7971815, `1.0.0-beta.3` upgrading over `1.0.0-beta.2`): the upgrade
  rolled back and setup still finished, leaving beta.3 code running over a
  beta.2 (pre-migration) database serving 500s.
  - **Root cause (D3 step 3 backup verification).**
    `civiccast/native/upgrade/seams.py::default_backup` runs its pre-upgrade
    restore-drill spot check (`civiccast/dr/restore_drill.py::
    run_postgres_restore_drill`) before any migration has run, but the
    drill's `schema_ok` compared the restored copy against the running
    CODE's migration head — always false the moment a release ships any
    migration at all (beta.1 → beta.2 passed only because it shipped zero).
    `run_postgres_restore_drill` gains an `expected_revision` parameter
    (default unchanged: `expected_migration_head()`, preserving DR-drill
    semantics); `default_backup` now passes the SOURCE database's own
    current revision, so the pre-upgrade question is "does the restore
    match what was dumped" instead of "does it match tomorrow's schema".
    The drill's `errors`/schema detail is also propagated into the
    orchestrator's raised exception and the journal's `error` field instead
    of the previous generic "hash or restore-drill spot check" string.
  - **Containment (flat installer layout).**
    `civiccast/apps/installer/src-tauri/nsis-hooks-bootstrap.nsh`'s D3 exit
    10 (ROLLED_BACK) branch used to DetailPrint and continue the install —
    correct for the `app\<version>` + junction layout, where a rollback
    really does restore the old binary tree, but this bootstrap always
    invokes the engine with `--flat-installer-layout`, under which
    `adapt_flat_installer_layout`'s junction seams are no-ops over the
    single `$INSTDIR\runtime` tree already holding the NEW payload before
    D3 ever ran. Exit 10 now fails the whole install via `CIVICCAST_FAIL`
    under a new, distinct exit code (`CIVICCAST_EXIT_D3_ROLLED_BACK_FLAT`,
    124) before D4 provisioning/activation/service registration ever runs,
    naming the previous version's data as intact and the service as never
    started. The retired `$R4` continue-and-report latch/notice path is
    removed along with it.
  - **Harness honesty.** `sandbox-lab/common/CivicCastStationHarness.psm1`'s
    `Wait-CivicCastStationHealth` and `sandbox-lab/scripts/
    In-Sandbox-Report.ps1`'s station-up wait gated "STATION HEALTHY" on
    HTTP 200 + non-empty body alone, exactly the shape `/health`'s own
    docstring warns against (`civiccast/app.py`: 200 is liveness-only in
    every schema state). Both now parse the JSON body and require
    `status == "healthy"` **and** `schema == "current"`. `/health` now
    returns `schema_db_revision`/`schema_expected_head` unconditionally
    (previously only when `schema == "behind"`), so a caller can prove a
    post-upgrade migration actually landed rather than trusting the
    `current` label alone. `scripts/gate_a_verdict.py`'s `dirty_survival`
    and `download_only_no_station_dir` checks now also assert
    `POST_UPGRADE_DB_REVISION_MATCHES_HEAD=1` (written into
    `DIRTY-RESULT.txt`/`DOWNLOAD-ONLY-RESULT.txt` alongside
    `POST_UPGRADE_DB_REVISION`/`EXPECTED_HEAD`) in upgrade mode — a healthy
    station-up body and `D3_ENGINE_EXIT=0` are no longer treated as proof by
    themselves.
  - **Tests.** `tests/dr/test_postgres_restore.py::
    test_postgres_restore_drill_expected_revision_overrides_code_head`
    proves the false-negative and the fix, real Postgres. New
    `tests/native/test_upgrade_engine_postgres.py` (Postgres-gated,
    `CIVICCAST_RUN_POSTGRES_TESTS=1` marks it required in CI) runs the real
    D3 engine through the actual production seam bundle over a database
    stepped back one real migration revision, asserting `COMPLETE` and
    `post_schema_revision == expected_migration_head()`. Policy coverage in
    `tests/policy/test_native_installer_identity.py` and
    `tests/installer/test_nsis_bootstrap_hooks.py` pins the new fail-closed
    exit-10 shape. `tests/gate_a/test_gate_a_verdict.py` gains regression
    tests for the revision-mismatch judge failure. `tests/test_health_
    readiness.py` covers the unconditional `schema_db_revision`/
    `schema_expected_head` fields.

- **`test_guard_fails_a_test_that_writes_real_state` no longer collides with
  mutmut in CI.** `tests/test_hermetic_state_guard.py` spawns a nested pytest
  subprocess via `pytester` to prove the hermetic-state teardown guard fails
  closed; that nested invocation already disabled `cacheprovider` and
  `randomly` but not `mutmut`, so in the `mutation-report` CI job (and the
  `deterministic-detectors` check that reads it, where the pinned
  `mutmut==3.6.0` package is installed alongside pytest) the nested run could
  pick up mutmut's pytest integration and abort at fixture setup with
  `FileNotFoundError: Could not figure out where the code to mutate is`,
  reported as an unexpected error alongside the guard's own expected error --
  seen identically on three unrelated branches/PRs (run 33628558134, PR #130,
  PR #131). Added `-p no:mutmut` next to the existing `-p no:cacheprovider -p
  no:randomly` flags on the nested `runpytest_subprocess` call. Swept the
  rest of `tests/` for other `pytester`/nested-pytest invocations that could
  hit the same collision; this is the only one.

- **`test_ac1_verifier_green_on_registered_claims_at_head` no longer
  depends on the job's own CI re-run attempt number.**
  `tests/policy/test_claims_evidence.py`'s AC1 fixture writes synthetic
  producer meta hardcoding `"run_attempt": "1"`, but the verifier under
  test (`scripts/policy/check_claims_evidence.py`) reads the real
  `GITHUB_RUN_ATTEMPT` from the inherited CI environment whenever
  `--run-attempt` isn't passed on the CLI (it wasn't) — so on any CI
  re-run attempt (`GITHUB_RUN_ATTEMPT=2`) this positive test failed its
  own CC-WS3-004 exact-artifact-routing check with `VIOLATION: producer
  'test': meta run_attempt '1' != this workflow run's run_attempt '2'
  (prior-attempt artifact — CC-WS3-004)` — seen on `randomized-suite` job
  100290734871, run 33641309663 attempt 2, seed 1070036697. The test now
  pins `GITHUB_RUN_ATTEMPT` (and, belt-and-suspenders, `GITHUB_RUN_ID`) via
  `monkeypatch.setenv` to match the meta it writes, so the outcome no
  longer depends on the job's real attempt number. The CC-WS3-004 check
  itself is unweakened: a new negative twin,
  `test_ac1_verifier_red_when_meta_run_attempt_mismatches_env`, reuses the
  same real-registry CLI entry point with a deliberately mismatched
  `GITHUB_RUN_ATTEMPT` and asserts the verifier still exits 1 naming
  `run_attempt`/`CC-WS3-004`. Verified locally with `GITHUB_RUN_ATTEMPT=2`
  set in the shell — both AC1 tests, and the full 121-test
  `test_claims_evidence.py` suite, pass.

- **Publish preflight and approval now read the same real provider registry
  (WP-03; audit findings QA-001 and the readiness portion of ENG-001).**
  Preflight used to answer from an unrelated deterministic mock credential
  store (`civiccast.publish.credentials`, now removed) that always reported
  "healthy" -- a station that selected e.g. `CIVICCAST_PROVIDER_YOUTUBE=real`
  with no credentials configured saw preflight say `ready=true` and then hit
  an uncaught `ProviderConfigurationError` (an unhandled 500) on approval.
  Both `build_publish_preflight()` and `approve_publish()` now resolve
  Internet Archive, local NAS, YouTube, and subscriber mail/webhook
  readiness through `civiccast.platform.providers` via one provider registry
  wired onto the app (`app.state.provider_registry`) and shared route
  dependencies (`civiccast.publish.router.get_provider_registry`), so they
  cannot disagree. Missing/invalid selected-real configuration now returns
  `ready=false` at preflight (HTTP 200, a safe non-secret credential
  reference such as `CIVICCAST_PROVIDER_YOUTUBE=real`, and a next step) and a
  controlled `409 Conflict` at approval -- raised before any surface executes,
  never a 500 -- via the new `PublishConfigurationError`. Only the surfaces
  the operator actually selected are checked, so an unrelated, broken,
  unselected provider can no longer block a portal-only approval (it
  previously always resolved Internet Archive, local NAS, *and* YouTube up
  front regardless of what was selected). A subsequent runtime/network
  failure from an otherwise correctly-configured provider still marks only
  that one surface `failed` and leaves the rest of the run intact. The
  shipped mock providers remain fully usable and never block readiness; they
  stay explicitly marked simulated so they are never mistaken for
  real-provider proof, and a failed real adapter never silently falls back
  to a mock. Podcast readiness reads `unknown` ("not available yet") rather
  than claiming readiness through a registry that has no podcast provider --
  the real podcast path is separate, upcoming work. Parameterized tests
  cover missing / partial / valid-real / explicit-mock / runtime-call-failure
  for every provider family, and prove no secret value ever reaches a
  preflight/approval response or a log record.

### Added

- **Retention value/unit/forever authoring (WP-08; punch item 7; audit
  findings ENG-006, TEST-004, DOC-008).** Retention rules could previously
  only be set from the four legacy `retention_policy` presets
  (`default`/`permanent`/`meeting`/`short`) plus an operator-typed
  deadline (`retention_until`) with no fixed reference point, so a term
  couldn't say "keep this 3 years" in a way that survives an edit. Assets
  now carry an additive authoring contract
  (`civiccast/schedule/retention_terms.py`,
  `Asset.retention_term_unit`/`retention_term_value`/`retention_anchor_at`,
  migration `0087_retention_terms`): a positive integer `value` plus
  `days`/`weeks`/`months`/`years`, or `forever` with no value.
  `retention_anchor_at` is captured once, at an asset's FIRST publish
  (`PostgresAssetStore.mark_published`), and never moves -- not on
  unpublish (which clears `published_at` but leaves the anchor alone),
  not on republish (which overwrites `published_at` but not the anchor),
  and not on a later term edit (which recomputes the deadline from the
  same fixed anchor). Days/weeks are elapsed-duration arithmetic; months/
  years are calendar additions performed in the station's local timezone
  (`civiccast.installer.station_state.resolve_station_timezone`),
  end-of-month clamped, leap-day safe, converted to UTC only for the
  persisted instant. Converting a legacy row with no publication history
  falls back to the conversion instant and writes a
  `MediaLifecycleAuditEntry` recording the fallback
  (`PostgresAssetStore._apply_retention_term`). The migration backfills
  only the unambiguous case (`permanent` -> `forever`, no anchor needed)
  and reuses any already-published asset's real `published_at` as its
  anchor; ambiguous legacy `default`/`meeting` rows, and never-published
  `short` rows, are deliberately left unconverted -- `short`'s known
  30-day meaning is offered only as an operator-facing prefill suggestion
  on the Asset Detail retention editor (`AssetDetailScreen.tsx`'s new
  "Convert to a length + unit or forever term..." flow), never
  auto-applied. Enforcement is UNCHANGED by design: every write to the
  new columns mirrors the legacy `retention_policy`/`retention_until`
  pair (`forever` -> `permanent` + no deadline; every finite term ->
  `default` + a computed deadline), so
  `civiccast.schedule.retention_worker` -- untouched by this change --
  keeps flagging expired, non-held assets into the records-clerk
  disposition review queue and never deletes a byte. New coverage:
  `tests/schedule/test_retention_terms.py` (pure arithmetic -- end-of-month
  clamp, leap day, DST spring-forward, station-timezone, forever,
  invalid values; a naive 30-days-per-month mutation kills five of these),
  `tests/schedule/test_retention_term_authoring.py` (Pydantic validation,
  anchor capture/reuse/immutability across publish/unpublish/republish/
  edit, legacy-conversion audit fallback, and an explicit worker-
  integration proof that crossing an authored deadline creates a
  disposition review and deletes no media),
  `tests/schedule/test_migration_0087.py` (upgrade/downgrade/round-trip/
  single-head/empty-db/backfill against production-shaped rows), and new
  `AssetDetailScreen.test.tsx` cases for the legacy-vs-term UI branch,
  prefill suggestions, the mutually-exclusive legacy/new PATCH contract,
  and the disabled-until-valid Save button. Migration note: this
  worktree branched from `main` at `0082_egress_graphics_overlay` (the
  actual current head at branch-cut time) rather than the finalization
  plan's nominal `0086` predecessor, because `0083`-`0086` (Spanish/
  podcast/subscriber/live-source, WP-02/04/05/07) had not yet landed on
  `main`. `0084` (podcast) and `0085` (subscriber outcomes) never
  landed at all; `0083_caption_review_language` (#131) and
  `0086_live_source_probe_state` (#140) did. This integration commit
  re-parents `0087_retention_terms`'s `down_revision` onto the real
  `0086_live_source_probe_state` so `alembic heads` again reports a
  single head; no other change (columns, backfill, constraints,
  upgrade/downgrade bodies) was made as part of the re-parent.
- **Operators can check a meeting source and edit one.**
  `POST /api/staff/live/sources/{id}/probe` runs the existing bounded ffprobe
  path and records what it saw; a failed check is a 200 with the reason and the
  exact next action, not an error that leaves the screen showing the previous
  state. `PATCH /api/staff/live/sources/{id}` is the update path
  `LiveSourceStore` had deferred "until a later rung defines the edit UX" --
  role-gated to `setup_admin` like create, with optimistic concurrency
  (`expected_row_version`, 409 naming both versions) so a second Live Room
  window cannot silently discard the first operator's edit. Any change to what
  would actually be probed clears readiness in the same transaction. The Live
  Room shows each source's last observation, its age, the safe failure reason,
  and the one thing to do next.
- **One rule for which endpoint shape each live-source type accepts**
  (`civiccast/live/source_endpoints.py`), applied to create and update alike
  and keyed on the stored `source_type`. The staff API previously accepted
  `HttpUrl | str` without asking whether the address matched the type, so an
  `srt` row could hold an `http://` URL that no probe and no playout element
  could open. Embedded `user:password@` and an SRT passphrase in the address
  are both refused outright.
- **A download-only upgrade can reuse the AI model packs an activated station
  already holds.** The station bundle publisher now stamps every reviewed
  MODEL pack (`captions-floor`, `captions-large-v3`, and the three Ollama
  components — never the per-version `core` placeholder, and never a component
  outside that allowlist) with a stable identity, `station-models-1`, instead
  of the product version. It also no longer signs any build-input path into a
  pack's metadata, so the same reviewed model set produces byte-identical
  packs — and therefore identical SHA-256 digests — from one candidate to the
  next *and* from one build machine to the next; a test builds the same
  fixture from two different roots and fails if the digests diverge. The
  signed station index and `core` still carry the real product version.
  Because the index pins each pack by SHA-256 and byte count, a `setup.exe`
  that arrives with no `station\` folder beside it can now serve those packs
  from the station's existing per-SHA cache
  (`<install root>\packs\.station-cache\packs\`) rather than requiring the
  ~21 GB of model media again. A cached pack is never trusted for existing:
  its bytes must match the signed index and it must re-verify as a
  trust-root-signed pack for that component; a directory, junction, or symlink
  planted at the cache path is refused, and a cache miss or a corrupt entry
  fails closed naming both the media path and the cache path. The trade this
  makes is explicit: model packs no longer carry an independent version
  tripwire, so a publisher who signs a new index pointing at a stale-era pack
  digest gets that stale pack. The identity constants are bumped only when the
  reviewed model set itself changes.

- **The installer now carries its own signed station index, so a
  downloaded-alone `setup.exe` can activate a station.** `setup.exe` embeds
  the signed `station-index.json` and the ~1.5 KB placeholder `core.ccpack`
  as Tauri `bundle.resources`, laying them down at `$INSTDIR\station\`. The
  `d4-activate-station` install step resolves the index from
  `$EXEDIR\station\station-index.json` first — so an air-gapped station
  installing from the USB kit behaves exactly as before, using the kit's own
  bundle and its co-located component packs — and falls back to the embedded
  copy only when no kit bundle is beside `setup.exe`. It still fails the
  install loudly when neither exists, and its failure dialog no longer tells
  the operator to "publish one alongside the installer", a remedy only the
  build pipeline can perform. The multi-gigabyte model packs are still never
  embedded: `scripts/build_native_bootstrap.py` gates the resource map
  exactly, gates each embedded file under 1 MB, and fails the build when the
  index's `product_version`/`compatible_core` do not equal the product
  version the activation CLI verifies against. In CI, `build-native-beta` now
  `needs: build-native-station-bundle` and fetches those two files from a
  small dedicated artifact (never the ~18.6 GB bundle) or, on the self-hosted
  lane, from that job's local mirror. The assembled USB kit is unchanged and
  still carries the full signed bundle at `.\station\`. This is the half that
  puts a signed index on the machine; the model packs that index names come
  from the per-SHA cache described in the entry above, so a download-only
  *upgrade* completes and a download-only *first* install still fails closed —
  a machine with no cache has never held those packs.

- **Supported data-preserving install-over-existing upgrades for CivicCast
  (Native).** Setup now invokes the already-installed bootstrap's production
  native service quiescence before replacing application files, aborts before mutation
  if that teardown is nonzero or its trusted bootstrap is missing, preserves
  `C:\ProgramData\CivicCast`, and lets provisioning adopt and migrate the
  existing station database. Gate A's dirty job now proves the operation
  against an immutable, hash-distinct previous candidate left live in the
  sandbox; it fails closed if the pinned prior build/kit identity is absent or
  if the two installers are the same bytes. It also requires the current
  installer's durable D3 evidence to report the `UPGRADE` route with engine
  exit 0, so the installer's successful `FRESH_INSTALL` and
  `SAME_VERSION_NO_OP` routes cannot masquerade as cross-version proof. The
  prior uninstall-remnant shape remains available as a separate manual harness
  mode and is never combined with cross-version evidence.

- **Real SDI/HDMI input selection for scheduled recording.** CivicCast now
  discovers DeckLink inputs and Windows DirectShow video-capture devices through
  the installed FFmpeg runtime, accepts explicit station presets through
  `CIVICCAST_RECORDING_INPUT_PRESETS_JSON`, exposes the resulting catalog at
  `GET /api/staff/recording/input-presets`, and makes operators choose a real
  detected/configured input. The capture pipeline resolves that stable preset
  to backend-specific FFmpeg arguments and fails closed when it is missing or
  the source kind does not match. The LPM hardware mock lab proves the exact
  DeckLink SDI and DirectShow HDMI argument boundary used by production.
- **Recorded-Spanish captions — a published recording now carries an
  operator-reviewed Spanish caption track alongside English, and cannot
  publish without one** (owner requirement; Longmont is ~30% Latino and
  Spanish captions on published recordings are a hard requirement; live
  real-time Spanish is out of scope). The offline caption job
  (`civiccast/captions/vod_job.py`) becomes two-phase: once an operator
  approves the English caption cues, the approved English is translated to
  Spanish through the same operator-selected translation tier the live tap
  uses (local TranslateGemma by default, via `build_translator`), and the
  Spanish cues are queued for their **own** operator review pass (spec §4.2,
  operator review before publish — the Spanish text is AI output too). Only
  when both review passes are complete are both tracks attached in a single
  manifest rewrite: English default, a new `es`/"Spanish" secondary. The
  public player already renders one caption button per manifest subtitle
  track, so the Spanish option appears with no front-end change; the operator
  console's review queue gains an EN/ES language badge and a language filter.
  A new `language` column on `caption_review_items` (migration
  `0083_caption_review_language`, default/backfill `en`) keeps the two review
  passes cleanly separated on a shared asset. Spanish review rows are created
  `low_confidence=False` — they are a deterministic transform of
  human-approved English with no ASR audio to retain, so the low-confidence
  audio-evidence approval gate cannot deadlock them.

  Spanish is **required, not a setting**: there is no supported configuration
  in which a caption-eligible recording completes with only English. The
  `CIVICCAST_OFFLINE_CAPTION_SPANISH` switch is retired — a false value now
  stops startup with an error naming the variable rather than quietly
  publishing English-only recordings. The two ways the Spanish leg can come up
  empty are both blocked and operator-actionable instead of green: a station
  with no translation runtime records an attempt with a remediation on the job
  row (and ultimately `failed`, reason intact) rather than shipping English;
  an operator who rejects every Spanish cue leaves the job in
  `awaiting_review` with a remediation, retry budget untouched, until they
  edit or approve a Spanish cue — review decisions are not terminal, so that
  move is really available. A recording whose *English* pass approved nothing
  still completes uncaptioned, because there is no English track to hold it
  for either.

- **A captioned recording served through a CDN now actually gets its caption
  tracks.** Caption attach rewrites the multivariant manifest and writes the
  WebVTT tracks on local disk; for a package that was already pushed to a CDN
  before caption review finished, the copy residents watch kept the
  pre-caption manifest, and the job called itself complete anyway. The offline
  caption worker now re-publishes the rewritten manifest, both segmented
  caption tracks, and both flat sidecars to the same key prefix the package
  was published under, through the same `upload_package_files` helper the
  finalization worker publishes with (extracted from
  `LiveFinalizationWorker._upload_package` and shared, so the manifest still
  uploads **last** and a resident can never fetch a manifest naming a track
  the CDN does not have). Only the caption artifacts are re-uploaded — the
  video renditions are byte-identical and can be gigabytes. A republish
  failure fails the job with the provider's message on the row rather than
  completing it. Nothing is uploaded when no CDN is configured, or when the
  recorded manifest URL for that package is not the configured CDN's URL for
  it — which is how a locally served package, or one from a CDN the station
  has since replaced, avoids having caption files pushed to a prefix whose
  video segments were never uploaded. Proven against a mock CDN adapter, not a
  live CDN account.

- **A live-finalized recording can now be captioned.** CivicCast resolves an
  asset's packaged video through two different conventions — a live-finalized
  recording packages to `<recording>/<live_session_id>-hls/` (recorded on its
  finalization job), an uploaded one to `.civiccast-packages/<asset_id>` under
  the media storage root — and the caption path only ever knew the second. A
  live recording would therefore transcribe and fill the review queue, then
  fail every attempt to attach the reviewed track to a package directory that
  was never written. The caption path now checks the finalization job's
  manifest first and falls back to the upload convention, matching the
  media-serving path's *live-finalized* precedence. It does not match that
  path's upload branch: it resolves the standard
  `.civiccast-packages/<asset_id>` location only, so a legacy pre-rc14 package
  at `<file_path>/hls` is still not found and publishing such an asset stays
  blocked (known gap; affects only stations upgraded across rc14 that still
  hold pre-rc14 packages). This also means a station that broadcasts live but
  has no media storage root configured is no longer refused permission to
  publish: it has somewhere to write the caption track after all.

### Changed

- **`sandbox-lab/upgrade-baseline.json` repinned from candidate-23 (beta.1,
  `057ffece7157e5197e6ce9159d5a1abd84c30436`) to the beta.2 internal
  candidate kit (`564ee028cf712e26133ada9d7c25b498abe605ab`, build run
  33621209994).** PR #127's stable-pack-identity change (see the
  "download-only upgrade can reuse the AI model packs" entry above) changed
  the signed bytes of every AI model pack, and it ships with no migration
  bridge for a station already activated on the old bytes: a beta.1
  station's pack cache is keyed by the old digests and can never satisfy a
  beta.2 signed index. Gate A run 33623737236's download-only lane proved
  this directly on the beta.2 kit — installer exit 123, activation code 66
  ("could not obtain model packs") — after the clean-install and
  cross-version-upgrade lanes both passed on the same kit. Owner decision
  2026-09-02 (option B, recorded in
  `docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`): **beta.2
  is never published** — it stays an internal Gate A upgrade-baseline kit —
  and **beta.1 to beta.3 is a one-time upgrade from the full beta.3 kit**
  (`setup.exe` run over the existing install, not download-only; `setup.exe`
  alone without the kit's `station\` folder is the one unsupported path —
  corrected 2026-09-03 per Gate A run 33713004718, see
  `docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`), making
  beta.3 the first downloadable release and beta.3-to-beta.4 the first
  download-only-upgradeable pair. The
  required download-only Gate A lane (#125) stays required for every
  release from beta.3 onward — this is the failure mode it exists to catch,
  and it caught it. The #23 kit and its `D:\kit-23-FINAL-beta1` copy are
  untouched; nothing about this repin deletes or supersedes them as
  historical artifacts. The product version itself moved from `1.0.0-beta.2`
  to `1.0.0-beta.3` in this same change (every surface
  `scripts/policy/check_release_identity.py` checks), so Gate A's
  cross-version lane can prove an upgrade against the newly-pinned beta.2
  baseline (a same-version pin cannot).

### Fixed

- **Made the D3 upgrade engine use the native installer's real flat runtime
  layout.** The installer, Windows service, and station activation all use the
  D2-verified `<install root>\runtime` payload, but D3 still tried to copy that
  payload into an unused `app\<version>` tree and create a `current` junction.
  Exact beta.1-to-beta.2 Gate A diagnostics proved the drain and verified
  backup/restore drill, then rolled back before migration when Windows
  Sandbox's mapped install volume rejected `mklink /J` with access denied.
  The NSIS call now explicitly selects the flat-layout adapter: it verifies and
  selects only the already-staged runtime while retaining D3's interlock,
  quiescence, backup, migration, maintenance-health, rollback, and journal
  gates. The generic versioned-tree/junction implementation remains available
  and independently tested for callers that actually use that layout.
- **Corrected a false-positive Job Object evidence claim inherited from the
  beta.1 tag.** The hosted Windows runner is itself contained by a foreign Job
  Object, so it cannot reproduce the clean SCM-launched supervisor topology;
  the added descendant-inheritance test failed on its own PR and on every
  later Windows run. That never-green test and its "empirically proven" source
  claim are removed. Real-Win32 direct-child assignment, no-breakaway limits,
  and kill-on-close remain CI-covered; automatic descendant inheritance in the
  installed service topology is source-wired but awaits clean-machine proof.

- **Stopped presenting unfinished CG media controls as working features.** The
  existing text, schedule, feed, image/logo, ticker, alert, preview, filler,
  and overlay CG paths are unchanged. Live video in a zone and board background
  audio are now labeled "coming in a future release"; the existing audio choice
  is disabled because the current renderer does not play it.
- **The public CG feed catalog and portal display no longer expose four
  hard-coded `example.invalid` RSS/iCal/weather/social rows as "configured"
  station feeds** (`civiccast/cg/service.py`'s `build_feed_catalog()`, still
  used only by tests and an explicit demo mode). `GET
  /api/public/cg/channels/{channel_id}/feeds` and the `feed_catalog` field on
  `GET .../display` now read the durable board/feed stack
  (`CgBoardService.feed_catalog`, `CgFeedSource`, `CgBoardStore`,
  `feed_fetcher.fetch_all`): only enabled feeds bound to an active board zone
  are exposed, an approval-gated zone's items are filtered to
  operator-approved item ids, and a station with nothing configured gets an
  empty adapters list instead of invented content. The operator "Dynamic
  feeds" panel (`CgBoardScreen.tsx`) now designs its own loading, configured,
  empty ("No dynamic feeds are configured...Add an approved RSS, calendar,
  weather, or permitted social source before using feed-driven CG zones."),
  and failed states rather than always rendering the sample rows. The sample
  catalog is available only with `CIVICCAST_CG_DEMO_FEEDS=1` explicitly set;
  it is off by default in every shipping profile.
- **WP-06 follow-up: the portal-display contract's ticker zone and approved
  bulletins no longer carry sample content either.** `build_multi_zone_snapshot()`'s
  static ticker zone always read "Library board meets tonight" / "Trail work
  begins Monday", and `build_portal_display()`'s `approved_bulletins` field
  always read the CA-3 sample queue (including an unfiltered `needs_changes`
  submission) -- both unconditionally, regardless of what a station actually
  configured. `GET .../display` now builds `approved_bulletins` through the
  same durable-store + approved-state filter (`CgBulletinStore`,
  `PostgresCgBulletinStore`) the standalone `GET .../bulletins` endpoint
  already used, and rebuilds the snapshot's ticker zone from the already-
  resolved feed catalog and approved bulletin queue
  (`source: "durable-station-config"`), rather than static filler. A station
  with no durable board/feed/bulletin configuration gets an empty,
  `{"items": [], "empty": true}` ticker and an empty bulletin queue. The old
  "Trail work begins Monday" string is fully retired -- it never reappears,
  even under `CIVICCAST_CG_DEMO_FEEDS=1`, because it was static filler with
  no backing store; demo mode composes the ticker from the same gated sample
  feed/bulletin data the `/feeds` and `/bulletins` endpoints show.
- **WP-06 non-negotiable follow-up: closed the last two unconditional-sample
  paths on the public CG router.** The standalone `GET
  /api/public/cg/channels/{channel_id}/snapshot` endpoint still called
  `build_multi_zone_snapshot()` directly (the same static ticker sample
  content the `/display` fix above already removed from the embedded
  contract), and the no-store fallback on both `GET .../bulletins` (public)
  and `GET /api/staff/cg/channels/{channel_id}/bulletins` (staff) returned
  the CA-3 sample bulletin queue unconditionally -- with no
  `CIVICCAST_CG_DEMO_FEEDS` gate at all -- whenever durable storage wasn't
  wired. All three now resolve through the same shared
  `_resolve_feed_catalog` / `_resolve_public_approved_bulletins` /
  `_resolve_staff_bulletin_queue` / `_resolve_durable_snapshot` helpers the
  `/feeds` and `/display` endpoints already use: durable data when a store
  is wired, an honest empty result otherwise, and the sample catalog/queue
  only under the explicit demo flag. The production-app-factory test now
  enumerates every GET route `civiccast.cg.router.public_router` exposes
  (via its own `.routes`, not a hand-maintained list) and asserts none of
  the seven historical sample strings appear on any of them, so a future
  endpoint can't reintroduce this defect unnoticed.
- **WP-06 non-negotiable, closed for real this time: EVERY snapshot zone
  (not just ticker) is now durable-data-or-honest-empty, on `/snapshot` and
  `/display` alike.** PR #132 review caught that
  `build_multi_zone_snapshot()`'s "coming up next" schedule zone still
  returned an invented `"18:00 City Council"` / `"20:00 Planning Board"`
  occurrence, `approved: true`, ungated, on every production response --
  the earlier fix only ever touched the ticker zone. All six zone kinds are
  now resolved from a real source or an honest label naming why: `ticker` /
  `schedule` from the durable feed catalog, approved bulletin queue, and (a
  new `CgBoardService.upcoming()` method) the SAME real program-log
  occurrences the operator Schedule and Program Guide screens read;
  `primary` from genuine, non-invented platform copy (the same text
  `/idle` already returns); `logo` from the channel's real branding profile
  (`civiccast.cable.channel.get_channel_profile()`, the same source the
  audited board-preview render path already uses); `audio` as an honest
  disabled-future-control state (WP-06 plan item 5) instead of a fake
  active `"community-calendar-bed"` track; `alert` from the real EAS
  overlay provider when wired and active, else honestly inactive. Only
  `ticker` and `schedule` carry a demo sample, and only under
  `CIVICCAST_CG_DEMO_FEEDS=1`; the other four zones are never demo-gated
  because they were never sample data standing in for real configuration.
  The production-app-factory sweep is hardened past a literal-string list
  (which had already missed "City Council"/"Planning Board" once): it now
  asserts every zone's `source` on every enumerated public route is one of
  a fixed set of durable/honest values, so a brand-new invented string a
  future change might introduce is caught by provenance, not by someone
  remembering to add it to a list -- proven by a mutation that dropped the
  `audio` zone's handling and confirmed the provenance test fails on the
  reintroduced sample content while the literal-string sweep (with the
  string removed from its list, to simulate a "never seen before" fake)
  passes it through undetected.
- **WP-06 non-negotiable, second review pass: corrected the logo zone's
  "real branding profile" claim -- it wasn't one.** The entry above
  described `civiccast.cable.channel.get_channel_profile()` as "the
  channel's real branding profile"; PR #132's second review caught that
  this is a compile-time default table (`logo_text="PUBLIC"`,
  `color="#2458A6"` for every deployment's "public" channel, same as every
  other CivicCast install) -- a generic default presented as station
  identity, not real per-station data. The logo zone now sources the
  station's real commissioned name (`resolve_station_display_name()` --
  the same `station_name` the installer/first-admin setup persists and the
  Station Profile screen edits) plus the channel's durable branding row in
  `AppPlatformConfigStore` -- the SAME store instance the operator Channel
  Ops screen already reads and writes. Because `AppPlatformConfigStore`
  seeds a brand-new channel's branding row from that same compile-time
  default table, a station that has never visited Channel Ops still has a
  durable row whose values still equal the default -- so the zone compares
  the durable row against the default and only reports `source:
  "station-channel-branding"`, `configured: true` when an operator has
  genuinely changed it. Otherwise it reports `source:
  "channel-default-branding"`, `configured: false`, the real station name
  and channel id, and an operator hint -- never the default table's
  "PUBLIC"/"#2458A6" values. Proven with a fake/spy `AppPlatformConfigStore`
  fixture carrying distinctive branding values (`"ZATV"` / `"#00AB66"`) and
  a distinctive `CIVICCAST_STATION_NAME`: those exact values surface on
  both `/snapshot` and `/display`, and the default table's values appear in
  neither. **Residual, stated precisely per this review's request:**
  per-channel branding IS a durable, operator-editable setting today (via
  Channel Ops / `PATCH` through `AppPlatformConfigStore.update_channel_branding()`)
  -- this fix reads the same row Channel Ops writes, it does not invent a
  new store. What is *not* yet true: an out-of-the-box station's branding
  row is seeded from the same static per-deployment default every other
  CivicCast install starts with, so "configured" here means "an operator
  has edited it since commissioning," not "every station's default identity
  is already unique." A station that ships without ever visiting Channel Ops
  will correctly show the honest not-configured state, never a silently
  identical fake "PUBLIC" logo passed off as real.
- **WP-06 non-negotiable, third re-review: "configured" is now an explicit
  stored fact, not a value comparison.** The entry above derived
  "configured" by comparing the durable branding row against the
  compile-time default table; a PR #132 review reproduced live that an
  operator who opens Channel Ops and explicitly saves branding equal to the
  default -- a plausible choice, e.g. keeping the default color -- got
  `configured: false`, a blank logo/color, and the "set this in Channel
  Ops" hint: indistinguishable from never having visited the screen at all.
  The same bug would recur in delayed form whenever a future release
  changes the default table, silently reclassifying every station that had
  saved the old default values as unconfigured. `ChannelBranding` gained a
  `configured_at: datetime | None` field that
  `AppPlatformConfigStore.update_channel_branding()` now stamps
  unconditionally on every operator save, regardless of the values chosen
  -- never derived by comparing against
  `civiccast.cable.channel.default_channel_profiles()`. The CG logo zone
  reports `configured: true` iff `configured_at` is set. A durable row
  persisted before this field existed (whose branding already differs from
  the default, a real prior customization, but whose `configured_at` is
  unset because the field didn't exist yet) is still treated as configured
  on read, so nobody loses their branding on upgrade -- only a row that is
  BOTH unstamped AND value-equal to the default (the genuine
  never-touched-Channel-Ops state) gets the honest fallback. Covered by
  three new tests exercising the real write path end to end: (a) an
  operator saves branding equal to the default -> `configured: true` and
  the real (default-equal) values render; (b) a seeded row nobody has ever
  saved -> `configured: false`, no default literals leak; (c) a pre-existing
  row that differs from the default with `configured_at` unset (the
  upgrade case) -> `configured: true`. Checked the store's persistence
  (`app-platform-config.json`, a plain pydantic-validated JSON file with no
  `schema_version` field or migration mechanism anywhere in the
  `app_platform` module) and confirmed no version bump or migration is
  needed: a new optional field with a default validates cleanly against
  every pre-existing file on disk.
- **Six hostile-review findings against WP-07's observed-readiness work
  (ADR 0025), fixed at their root.** **(1)** Closed a fail-open race: the
  takeover gate read a live source, ran an up-to-8s probe, then persisted the
  verdict by id alone -- a PATCH that repointed the endpoint inside that
  window got silently overwritten with "ready" derived from the OLD address.
  `LiveSourceStore.record_probe_observation` now accepts the `row_version`
  and endpoint that were actually probed and raises a new
  `LiveSourceProbeConflictError` (refusing the write) when either moved;
  `LiveSourceReadinessService.verify_for_takeover` and `.probe` both carry
  their pre-probe read through and fail closed on conflict (409 from the
  probe API), never silently overwriting a fresher edit's `never_probed`.
  **(2)** `source_endpoints.normalize_endpoint` only inspected the query
  string for a passphrase and re-emitted the URL fragment unchanged, so
  `srt://host:9000#passphrase=hunter2` was accepted and persisted in
  plaintext; any non-empty fragment is now rejected outright for every
  URL-type source. **(3)** `readiness_state` clamped a negative observation
  age to zero, so a backwards clock correction left a source reading "ready"
  for the whole span of the jump; an observation timestamped more than 5s
  ahead of "now" now reads `stale`. **(4)** In the Live Room: the Probe
  button now checks the same `meeting_operator`/`setup_admin` role the
  backend requires (with an explanatory line when hidden); the source list
  polls at most every 10s so a stale pill goes stale on screen instead of
  outliving the 30s TTL silently; switching a source's type away from SRT
  now clears the credential field's state (not just its display), so an old
  handle cannot be resubmitted after switching back; and a 409 on save now
  reloads the row and tells the operator, instead of resending the same
  stale `row_version` forever. **(5)** Fixed a stale ADR filename citation in
  `source_endpoints.py`. **(6)** Documented, rather than built: ADR 0025
  gained a "Known gaps" section, and the CHANGELOG's "credentials_handle is
  no longer a dead surface" entry now says plainly that this is a readable
  handle contract with no write path yet (`save_live_source_secret` has zero
  callers anywhere in the product) and that a per-user `keyring` vault vs. the
  `LocalSystem`-registered supervisor service is an open gap, not a solved
  one.
- **Removed the Facility Router's hard-coded `government` channel.** Every
  channel-dependent action (scheduled-take preview, overlay preview, and the
  later L-bar command) now requires the operator to pick a currently
  configured channel from a new "Target channel" picker
  (`FacilityRouterScreen.tsx`), loaded through the same channel-profile API
  and cache key Channel Ops and Live Room already use
  (`listChannelProfiles`/`['channel-profiles']`) rather than a new endpoint.
  A single configured channel auto-selects but still shows in the picker; two
  or more require an explicit pick; the picker clears the selection and any
  stale overlay/schedule preview if the chosen channel disappears from the
  configured list; and both actions are disabled with a plain reason
  ("Choose a channel before scheduling a take.", "Choose a channel before
  previewing an overlay.", the no-channels-configured message, the load-error
  message, or "Scheduling a take and previewing overlays require the meeting
  operator role.") until a valid channel and role are in place. Manual
  crosspoint preview (endpoint/source/destination) is unchanged and does not
  take a channel_id. `FacilityRouterScreen.test.tsx` covers no-channel,
  one-channel (auto-selected), multiple-channel (explicit pick required),
  stale-selection, load-error, read-only-role, and mobile-viewport states;
  `e2e/facility-router.spec.ts` is updated for the new channel picker and
  role.
- **CI: hardened the "Install media test prerequisites" step against two
  distinct hosted-ubuntu apt failure modes instead of only the dpkg-lock
  one it already handled.** `ci-test.yml`'s `Unit tests` job and
  `deterministic-detectors.yml`'s `randomized-suite` job both timed out at
  exit 124 several times on 2026-09-02 across unrelated PRs — PR #131 "Unit
  tests" job 100278667553, PR #135 "randomized-suite" job 100284786583, and
  PR #132 "randomized-suite" job 100287702253. The step's own comment
  already documented `unattended-upgrades` holding the dpkg lock for 3h49m
  on 2026-08-19, but these three failures never touched the lock at all:
  each stalled mid-download of a single large package
  (`libcodec2-1.2`/`libflite1`/`libdav1d7`) on the Azure-hosted mirror,
  hitting the old 300s per-call timeout. A longer timeout alone would have
  papered over the symptom without addressing the lock risk that is still
  real. Both jobs' inline apt shell — previously duplicated between the two
  workflow files — is replaced with a single call to the new
  `scripts/ci/install_media_test_prerequisites.sh`, which: stops and kills
  `unattended-upgrades`/`apt-daily*.timer`/`apt-daily*.service` before
  touching apt; waits up to 3 minutes for the dpkg/apt locks in a bounded
  loop, printing the holder via `fuser -v` each iteration; runs every
  `apt-get` call with `DPkg::Lock::Timeout=120`, `Acquire::Retries=3`, and
  `DEBIAN_FRONTEND=noninteractive`; raises the per-call timeout from 300s to
  480s (and the step's own `timeout-minutes` from 10 to 30) so a slow mirror
  has room to finish instead of being killed mid-transfer; and, on any
  failure, dumps `ps -ef | grep -E 'apt|dpkg|unattended'` so the next
  occurrence is diagnosable from the log alone. Validated with
  `python -c "import yaml,sys; ..."` over `.github/workflows/*.yml` and
  `actionlint` (both clean) plus `bash -n` and `shellcheck` on the new
  script.

### Security

- **Triaged and allowlisted a new nltk pathsec-bypass advisory
  (`PYSEC-2026-3740` / CVE-2026-81726 / GHSA-8mgp-746c-j5xp).** `pip-audit`
  started flagging `nltk 3.10.3` (a transitive dependency of `crawl4ai`,
  pulled in only by the optional `agenda-js-import` extra behind
  `civiccast/agenda_import/js_portal.py`) for a sandbox bypass in
  `TransitionParser.train()`/`.parse()`, `AveragedPerceptron.save()`/`.load()`,
  `PerceptronTagger.save_to_json()`, and `save_maxent_params()`, which use raw
  `open()` on caller-controlled paths instead of nltk's guarded `pathsec`
  helpers. No fix version exists upstream as of this review (`pip-audit`
  reports empty `fix_versions`). `civiccast/` never imports `nltk` directly,
  and `js_portal.py`'s `crawler.arun()` call passes no `chunking_strategy`/
  `extraction_strategy`, so crawl4ai's only nltk touchpoint
  (`chunking_strategy.py`'s `sent_tokenize` punkt tokenizer) is never
  exercised — none of the five vulnerable model-persistence APIs are
  reachable from any code path in this repo. Documented in
  `security/pip-audit-allowlist.json` with a review-by date of 2026-10-01;
  re-check when nltk ships a fix.


### Known limitations

- **Uninstall destroys the downloaded model-pack cache, so a later
  download-only reinstall cannot activate (installer-path audit MA-17).**
  `RMDir /r "$INSTDIR\packs"` removes `$INSTDIR\packs\.station-cache` along
  with everything else. That is correct for an uninstall in isolation, but it
  means a machine that uninstalls and then reinstalls from `setup.exe` ALONE
  (no `station\` folder beside it) cannot activate: the signed station index
  is embedded in `setup.exe`, the ~21 GB of model packs are not, and the
  per-SHA cache they would have been served from is gone — so activation
  exits 66 and the installer aborts with 123. This collides with the standing
  "download install is the floor" rule for that one sequence.

  **Not fixed in this release, deliberately.** Preserving the cache means
  either leaving a multi-gigabyte `$INSTDIR` behind — which contradicts the
  bootstrap's own "everything gone" uninstall contract and changes what a
  silent uninstall reports to winget/Intune — or relocating the cache to
  `%ProgramData%\CivicCast` and teaching the activation step's `--cache-root`
  a second search location (audit MA-16). Both are decisions about what an
  uninstall *means*, and belong to the owner rather than to a batch fix.

  **What changed instead:** the uninstaller now says so, before it removes
  anything, on every path. Interactive uninstalls get a dialog; silent ones
  get the same text in `install-progress.log` (the notice is silent-safe by
  construction). It names what is being deleted, states plainly that
  recordings, the database and settings in `%ProgramData%\CivicCast` are
  **kept**, and gives the two remedies that actually work: reinstall from the
  full CivicCast kit folder, or copy `$INSTDIR\packs\.station-cache` aside
  first.

  **Workaround, unchanged:** installing from the full kit folder
  (`setup.exe` together with its `station\` folder) is unaffected.

## [1.0.0-beta.1] - 2026-08-31

First tagged release of the native-Windows CivicCast line — owner-held, not
a public or production release. See
[`v1.0.0-beta.1`](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.1).
Everything below was previously tracked under `[Unreleased]`.

### Changed

- Replaced the GitHub Pages front door with an evidence-grounded station-level
  landing page. The new page presents CivicCast as an open-source PEG platform,
  maps the end-to-end station workflow, explains local AI and the three-channel
  reference profile, and keeps the current beta boundaries prominent. It does
  not promote physical SDI, headend acceptance, provider delivery, OTT-store
  publication, or field operation beyond the evidence recorded in the
  repository.

### Fixed

- **A shutdown mid-recording now finalizes in-flight scheduled recordings to a
  valid asset instead of losing them.** PR #100 deferred this (its item 4).
  `_app_lifespan`'s shutdown drained the egress daemon
  (`stop_all_channels(deadline_seconds=...)`) but left in-flight
  `RecordingService` jobs (`arming`/`recording`/`finalizing`) to be torn down
  by process exit — the ffmpeg capture was killed and its already-valid,
  flushed MPEG-TS segment on disk was never concatenated or finalized, so the
  job sat orphaned until the next boot's `reconcile_orphans` marked it
  `failed`. `RecordingService.drain_in_flight(...)` (called from the lifespan
  `finally`, peer to the egress drain, via
  `ScheduledRecordingWorker.drain_in_flight`) now gracefully stops each
  in-flight job through the existing `stop_job` path — producing a finalized
  asset — bounded by `CIVICCAST_RECORDING_DRAIN_DEADLINE_SECONDS` (default
  15s, best-effort, never hangs shutdown). It runs safely alongside the still
  live scheduler poll thread through the capture pipeline's per-job lock;
  jobs not reached within the deadline fall through to `reconcile_orphans` as
  before (never worse than today). No migration.
- **Verified (no change needed): ffmpeg children spawned by `start_ffmpeg` are
  already Job-Object-contained.** PR #100's other deferred item. `start_ffmpeg`
  uses a plain `subprocess.Popen` with no explicit `AssignProcessToJobObject`;
  empirically proven (Windows, production seam) that this is sufficient — the
  control-plane process that runs it is assigned to the supervisor's job at
  startup and the job disables breakaway, so Windows captures every child it
  spawns automatically. See
  `tests/native/test_supervisor_job_object_win.py::test_popen_child_of_an_in_job_process_is_contained_without_explicit_assign`
  and the containment note in `civiccast/stream/_ffmpeg.py::start_ffmpeg`.
- **BLOCKER B1 — a live SRT/UDP/RTSP source that is unreachable or drops no
  longer crash-loops the channel forever.** Hostile-audit finding: the
  encoder process itself starts fine against a bad live source (so
  `_start`'s own `EncoderUnavailableError`/`FfmpegNotFoundError`
  fallback-to-slate seam never fires), then dies inside the pipeline once it
  can't connect to / keep reading the source — `_relaunch_after_crash` paced
  the *rate* of relaunch but always relaunched against the *same* source, so
  the channel never reached a stable on-air state. `civiccast/egress/daemon.py`
  now tracks a crash-relaunch streak that has never once reached a healthy
  uptime; once it crosses `_LIVE_SOURCE_FAILURE_FALLBACK_STREAK` (5, matching
  the existing S9-5 escalation threshold), the daemon forces the same
  fallback-slate path `_start` already uses for encoder-unavailable, instead
  of trusting the source plan again — and stays latched onto slate across a
  slate-encoder crash too, so a further crash cannot flap the channel back to
  the still-dead live source. `civiccast.egress.automation`'s existing
  `_check_slate_replan` (30s-paced reload) already retries the real source on
  its own schedule, so a source that recovers is picked back up automatically.
  "Dead air is NEVER acceptable" now has a terminal slate state to back it up
  for this failure mode, not just for a synchronous encoder-start failure.

- **MAJOR M1 — a dead HLS relay child (disk full / ffmpeg missing / OOM) no
  longer stays invisible.** Nothing polled `HlsRelaySupervisor`'s supervised
  ffmpeg relay process after `apply()` started it, and
  `civiccast.egress.health.build_default_sink_health` judged the `hls` sink
  healthy from the *main* encoder's own UDP send progress alone — blind to
  whether the separate relay child was still alive. `EgressDaemon` now polls
  `HlsRelaySupervisor.is_alive(channel_id)` every `process_once` tick
  (mirroring how the main worker is polled) and overrides the `hls` sink's
  reported health to unhealthy the moment the relay is confirmed dead, so
  `/api/staff/egress/channels/{id}/health` stops reporting "connected" for a
  relay residents are no longer actually receiving anything from.

- Noted but explicitly deferred: **C1** (per-leg SRT reconnect without a full
  pipeline rebuild) is a larger redesign, out of scope for this fix. **N1**
  (srtsrc/udpsrc connect-timeout properties in `civiccast/egress/gst/bridge.py`)
  was evaluated and skipped — the GStreamer SRT plugin's exact timeout-property
  surface could not be verified against the real runtime in this environment
  (no `gi`/GStreamer available), and shipping an unverified property name
  risks breaking the live-source element build outright; a future pass with
  `gi` available should confirm the property name before adding it.
- **Operator-console sessions had no revoke path, and a lost first-run
  recovery kit was a permanent lockout.** Two CRITICAL findings from a
  hostile audit of the #83 fratricide fix. (1) Login and recovery
  deliberately APPEND a fresh token to `operator_console.tokens` instead of
  replacing it (so a routine sign-in never signs out another already-open
  browser), but that left no way to end a lost or stolen laptop's session on
  purpose — it stayed valid until 20 more sign-ins evicted it (months, at a
  single-admin station) or a destructive full reset. A new "Sign out other
  sessions" action (`revoke_other_operator_sessions` in
  `civiccast/installer/station_state.py`, `POST
  /api/staff/installer/sessions/revoke-others`, a Security panel on the
  Station Profile screen) keeps the calling session valid and revokes every
  other one in one step. (2) The one-time first-run recovery kit had no
  regenerate path: a browser dying before the kit was saved meant the 8
  codes were gone forever, and a later lost password was a permanent
  lockout with no escape but the destructive, undocumented
  `CIVICCAST_ALLOW_FIRST_ADMIN_RESET` full-station wipe. A new "Regenerate
  recovery kit" action (`regenerate_recovery_kit`, `POST
  /api/staff/installer/recovery-kit/regenerate`, same Security panel)
  requires an already-authenticated `setup_admin` — it is the "I still have
  my password but lost my codes" path, not a lockout bypass — and mints 8
  new codes while immediately invalidating every old one.

- **Designed empty states on every operator-console screen, and the Control
  Room "banner wall" collapsed to one verdict per page.** A 38-screen field
  survey on a real box (2026-08-30) found about a dozen console pages whose
  success-empty state rendered as a bare grey one-liner ("No devices yet.",
  "No saved searches yet.") — technically correct, but reading as "nothing
  there / broken" to a non-technical viewer. A new shared
  `EmptyState` component (`src/components/EmptyState.tsx`) generalizes the
  pattern Missing Media and Assets already had (dashed panel, headline +
  plain-language explainer): one sentence on what the screen does for a
  station, one on how it gets populated. Applied to Control Room Setup
  (devices, cues), Control Room (devices, fired-cue audit), Custom Fields,
  Remote Contribution, CG Board, CG Board Designer, Auto-schedule (saved
  searches, dayparts, rules), Program Guide (slots, 7-day log), Recording
  (schedules, recordings), Agendas, EPG Export, Underwriting (spots,
  flights), Playback Policy (audit log), and the Analytics in-table empty
  rows. Separately, the readiness surfaces stacked the same red
  "Do not broadcast yet" phrase once per blocked check — five identical
  banners on a fresh box. `ControlRoomReadinessPanel` and the Live Room
  `PreflightList` now state the page verdict exactly once (headline banner /
  a new one-line summary banner with the failed-check count); blocked rows
  keep their severity via a red border and their existing next-step copy,
  and the operator-language guide's five sanctioned phrases remain the only
  readiness vocabulary. Tests updated to pin the once-per-page behavior
  (`ControlRoomReadinessPanel.test.tsx`, new `LiveRoomScreen.test.tsx`
  dedupe case).
- **The orphaned-caption-tier degrade (PR #80) is now operator-visible: its
  WARNING actually reaches `supervisor.log`, and the station raises a
  `caption-tier-degraded` alert in the System Health hub.** Field finding
  (2026-08-30, real box): PR #80's fallback works — a station whose
  `captions-large-v3` was preserved by an uninstall/reinstall upgrade but
  lost its activation receipt degrades to the proven floor tier and starts —
  but the `_LOG.warning` recording that decision reached NO on-disk log
  (full-file search of `ProgramData\CivicCast\logs` found nothing), so
  operators ran silently degraded captions. Root cause: the warning is
  emitted by `civiccast.native.station_runtime`'s module logger inside the
  supervisor service process, whose only configured handler hangs off
  `civiccast.native.supervisor` with `propagate=False`; station_runtime's
  records propagated to a handlerless root logger, and a Windows service has
  no visible stderr for logging's `lastResort`. Fix, in two halves:
  - `configure_logging` (`civiccast/native/supervisor/service.py`) now also
    wires the `civiccast` package-root logger to the SAME durable rotating
    handler instance (one handler, so rotation renames never race on
    Windows; no duplicate lines, since the supervisor logger still stops at
    its own handler), so every `civiccast.*` library record emitted in the
    supervisor host process lands in `supervisor.log`.
  - The control plane surfaces the degrade through the EXISTING S8 alert
    hub: a new `caption-tier-degraded` `AlertConditionKind`
    (`civiccast/alerting/models.py`; unseeded, "warning" fallback — same
    posture as `channel-automation-failure`), raised once per startup by
    `_build_caption_tier_startup_condition` (`civiccast/app.py`) from the
    `CIVICCAST_CAPTION_TIER_EVENT` environment `load_native_station_environment`
    already emits (`fallback: true` → firing, de-duped across degraded
    restarts; a healthy start resolves a previously-firing event, guarded on
    `_find_firing_event` so a normal boot never writes a spurious audit
    row). Registered as a lifespan startup-condition hook because
    `create_app()` must never touch the database. Regenerated
    `docs/openapi.json`, `docs/API-REFERENCE.md`, and the operator console's
    `api.generated.ts` for the new kind. Tests:
    `tests/native/test_supervisor_service.py` (library records land in
    `supervisor.log` via the real configured logging path; single shared
    handler) and `tests/test_caption_tier_startup_alert.py` (fire, de-dupe,
    resolve, no-spurious-row, garbled-env and broken-DB never raise).

### Added

- **Confirmation dialogs on every live one-click destructive action in the
  operator console — field evidence from the board-demo survey.** A survey on
  a real box found the console studded with live one-click buttons a curious
  board member could hit: a single click could take a channel off air or wipe
  config with no confirmation. Every listed action now stages an accessible
  confirmation dialog (`portal-operator/src/components/ConfirmDialog.tsx`:
  `role="alertdialog"`, focus moves to Cancel, Tab is trapped, Escape
  cancels, focus restores to the opener) whose copy names the plain-words
  resident-facing consequence, matching the console's existing two-step
  patterns (Commit-to-Air "Take off air", Paywall arm→confirm, Recording
  stop). Covered: Start/Stop/Restart-feed/drain on both the Channels screen
  and the Safe-to-broadcast readiness panel (shared copy via
  `feed-command-confirm.ts`), "Repair GStreamer runtime & restore"
  (upgraded from a bare `window.confirm`), "Run real database restore
  drill", "Run rollback rehearsal", "Open maintenance window", Media
  Lifecycle watch-folder and retention-rule "Remove", Federation "Generate
  station key", App Admin "Queue build", and Publish "Approve and Publish
  selected". App Admin's build form additionally starts with both fields
  unselected and keeps "Queue build" disabled until the form is valid.
  Safe/read-only actions (checks, previews, scans, refreshes) deliberately
  gained no confirmation — confirmation fatigue is its own bug. Tests prove
  each dialog blocks the API call until confirmed and that Cancel/Escape
  fire nothing.
- **Gate A dirty lane: an uninstall-remnant reinstall gate
  (`station-acceptance-dirty`).** Weeks of installers passed the pristine
  Windows Sandbox and then died on real machines, because every real machine
  carries the `%ProgramData%\CivicCast` state the uninstaller preserves *by
  design* — most recently DESKTOP-2BR3SJR (2026-08-30), whose preserved
  `components\captions-large-v3` without a ProgramData receipt crash-looped
  the #18 supervisor (fixed in PR #80). Gate A stayed green throughout
  because its sandbox has no history. The new lane, a second informational
  job in `gate-a-station-acceptance.yml` running after the clean lane in the
  same `sandbox-lab` concurrency group, makes the sandbox *have* history:
  `In-Sandbox-Report.ps1` (opted in via `Run-GateA.ps1 -DirtyLane` →
  `Host-Launch-Sandbox-Test.ps1 -DirtyMode` → `DIRTY_MODE.txt`) installs the
  candidate, plants real uploads, records the provisioned pgdata cluster's
  identity, runs the product's own uninstaller, verifies the preservation
  contract, optionally seeds the orphaned large-v3 remnant (real model
  required — a stub provably reproduces the fail-closed model gate, not the
  PR #80 receipt path), and then runs the full unchanged acceptance flow
  against the remnant-carrying box. `scripts/gate_a_verdict.py --lane dirty`
  adds three fail-closed checks (`dirty_prep`, `dirty_survival`,
  `dirty_orphaned_tier` — the last a loud `SKIP` when the model seed is not
  staged on the runner), and the job posts the per-check verdict table to
  the workflow run summary. Timing contract: dirty in-sandbox watchdog 210m
  < host poll 230m (the clean lane's 150 < 170 is untouched), asserted with
  the rest of the lane's invariants by new tests in
  `tests/gate_a/test_gate_a_harness_contract.py` and
  `tests/gate_a/test_gate_a_verdict.py`. Full design, covered-vs-not remnant
  shapes, and the runner seed instructions: `docs/ops/gate-a.md`, "Dirty
  lane". The clean lane's behavior, defaults, and verdict document shape are
  byte-identical to before.
- **Runtime pack now carries the three S15 CG-lite / native-HLS GStreamer plugins (`gstcompositor.dll`, `gstpango.dll`, `gsthlssink3.dll`), staged ahead of use.** PR #88 fixed the commissioning probe's false-negative on candidate #19 by narrowing `_BASE_REQUIRED_PLUGINS` to the engine's true spine, and separately recorded that `compositor`/`textoverlay`/`clockoverlay`/`hlssink3` are already present in the already-pinned `gstreamer-libs`/`gstreamer-plugins` 1.28.5 wheels — an additive packaging change with no new download, no source build, no version bump. This lands that additive change: `civiccast/native/runtime_closure.py` gains `STAGED_OPTIONAL_FACTORIES` (`compositor`, `textoverlay`, `clockoverlay`, `hlssink3`), mapped in `FACTORY_PLUGIN` and folded unconditionally into `scripts/build_native_runtime_closure.py`'s `required` seed set (`select_plugin_seeds` refuses loudly with `MissingPluginError` if one ever goes missing from a future wheel bump — never a silent drop). Deliberately NOT added to `REQUIRED_FACTORIES`: that set's own docstring is "the factories the product's pipelines cannot run without", and no pipeline in `civiccast/egress/gst/engine.py` builds a graph with any of these three yet — conflating "staged for a future feature" with "the engine cannot run without this" would be a false claim in a set other code reasons from. `civiccast/native/runtime_licenses.py`'s `PLUGIN_LICENSE` records all three as LGPL-2.1-or-later (same upstream COPYING.LIB as the rest of the gst-plugins-base/good family already in that table), so the AC7 provenance gate passes. `interpipesrc`/`interpipesink` remain out of scope: PR #88 recorded the RidgeRun interpipe plugin as absent from the pinned wheels entirely, which would need a new upstream artifact rather than an additive closure change. Proven end-to-end against the real pinned wheels in the local `uv` cache (`gstreamer_libs`/`gstreamer_plugins` 1.28.5): a full `scripts/build_native_runtime_closure.py` run places all three DLLs at `lib/gstreamer-1.0/`, lists them in `runtime-manifest.json` and `LICENSE-BOM.md`, and the closure build completes with no `UnknownProvenanceError` (their PE-import closures resolve entirely to DLLs the tree already ships, e.g. `cairo-2.dll`/`pango-1.0-0.dll` already required by the closed-caption renderer). New tests in `tests/native/test_runtime_closure.py` guard the staged set's membership, disjointness from `REQUIRED_FACTORIES`, plugin-mapping completeness, and the fail-closed missing-plugin refusal.
- **Operator control-plane wiring for the graphics-overlay lower-third banner — a real on/off switch and text field, not just the engine seam.** The previous entry (graphics-overlay leg) shipped only the engine/graph seam and its live proof, explicitly deferring "wiring an operator-facing config/UI toggle" as a separate slice — this is that slice. `EgressConfig` gains `graphics_overlay_enabled: bool = False` and `graphics_overlay_lower_third_text: str = ""` (migration `0082_egress_graphics_overlay`, `civiccast/egress/models.py`/`store.py`), both off/blank by default so an existing channel's persisted config and playout graph are unaffected until an operator opts in. `civiccast.egress.gst.bridge.graphics_overlay_leg_from_config` builds a single-layer lower-third `GraphicsOverlayLeg` from those two fields (rendering a fresh banner PNG via the existing `render_lower_third_png` rasterizer into the channel's work dir), returning `None` when disabled or blank; `GstPlayoutStrategy.start()`/`reload_content()` (`civiccast/egress/gst/strategy.py`) pass it into `graph_from_config`'s new `graphics_overlay=` parameter on every fresh start and content-reload. A dedicated staff endpoint, `GET`/`PUT /api/staff/egress/channels/{channel_id}/graphics-overlay` (`civiccast/egress/router.py`), lets an operator read/set just the toggle and text without resending the channel's full sinks/secrets/profile — 404 before the channel has a base config, matching the existing headend-profile pattern. `ChannelOpsScreen.tsx`'s new `GraphicsOverlayPanel` gives the operator a text field plus a confirm-gated on-air/off-air toggle (disabled until text is entered), wired to the new endpoint via `getGraphicsOverlay`/`updateGraphicsOverlay`. Documented limitation: this is a next-pipeline-build change, not a hot update — a saved toggle/text change takes effect on the channel's next `start()` or seamless content-reload, not on an already-live pipeline's on-screen text (the compositor holds no live text-render path; the banner is a still PNG). Station-bug/logo config is still out of scope; only the lower-third layer is operator-controllable so far.

- **Graphics-overlay leg for the GStreamer playout engine — station bug/logo + lower-third text banner, composited live.** The playout engine previously had no way to burn graphics onto program video except the existing S15 §5 CG-lite full-frame board raster (a pre-composited image an external renderer must supply whole). `graph.GraphicsOverlayLeg` (`civiccast/egress/gst/graph.py`) adds a real, independently-positioned overlay: any number of image layers (a station bug PNG at a configurable corner, plus — via `graphics_overlay.station_bug_and_lower_third_leg` — a rasterized lower-third text banner), composited between the selector and the encoder chain so it survives every source swap/reload untouched. Built against this box's ACTUAL bundled native-Windows GStreamer runtime, verified by a real `gst-inspect` enumeration rather than assumed: the runtime ships no plain `compositor`/`videomixer`/`gdkpixbufoverlay`/`textoverlay`/pango/cairo/rsvg at all — only the D3D11/D3D12 hardware compositor family — so the leg builds on `d3d11compositor` (`filesrc ! decodebin ! videoconvert ! d3d11upload ! comp.sink_N`, `d3d11download ! videoconvert` back to system memory for the unchanged encoder chain), with each layer's compositor pad set `repeat-after-eos=true` to hold a one-frame still image on screen for the pipeline's whole run (this runtime also ships no `imagefreeze`). Because no text-rendering element exists either, the lower-third banner is rasterized in pure-stdlib Python (`graphics_overlay.py`: a small built-in 5x7 block font + a `zlib`/`struct` PNG writer, no new dependency) into an RGBA PNG that rides the same real-alpha-decode compositor path as an operator-supplied logo. Strictly opt-in — `PlayoutGraph.graphics_overlay` defaults to `None`, so every existing graph (nothing sets it yet) builds byte-identically to before. Live pipeline proof on the bundled runtime (`tests/egress/test_gst_engine_wsl.py`, run via `worker.py` exactly as the daemon launches it): MPEG-TS continuity clean (0 CC errors, 0 PCR discontinuities) with the overlay on, plus a decoded-pixel check on the captured output confirming the composited colors are actually visible on screen. Scope boundary: this ships the engine/graph seam and its live proof only — wiring an operator-facing config/UI toggle the way the existing CG-lite board overlay is wired (`EgressConfig` schema, migrations, `strategy.py` plumbing, station settings UI) is a separate slice.

- **In-product operator manual (`/help` in the operator console), plus a "Generate station key" button for federation.** Field evidence from a non-technical tester (candidate #17): "In-product manual: THERE IS NONE. /docs, /help, /manual, /guide all 404"; provider setup cards told the operator to "Ask the technical admin" on a one-person station with no technical admin; ActivityPub required typing a raw `civiccast activitypub keygen ...` shell command. The manual is built from the existing `docs/USER-MANUAL.md` (the repo's canonical operator doc), not a parallel document that drifts: `scripts/render_docsite_manual.py` renders it via the same `pandoc` toolchain `scripts/render_user_manual.py` already requires for the PDF/DOCX, sanitizes the HTML through an allowlist parser (`civiccast/docsite/render.py`), and writes the committed artifact `civiccast/docsite/manual.json` plus a hash manifest (`civiccast/docsite/manual.render.json`) — the identical hash-pinning drift-gate pattern the PDF/DOCX pipeline already uses, now also enforced in `ci-docs.yml`. `civiccast/docsite/service.py` + `router.py` serve it read-only, publicly (no staff token — reachable even from the un-authenticated First Setup screen), at `GET /api/public/manual`; the operator console's new `ManualScreen.tsx` renders it as a searchable table-of-contents + content pane at `/help` (aliases `/docs`, `/manual`). Full write-up: `docs/docsite-sync.md`. The manual gained new plain-language content: a Glossary (S3 access key/secret, bucket/object store, CDN, pull-zone, OAuth client ID/secret, webhook secret, egress), a per-provider "Setting Up Providers, Plain Language" section (each provider optional, its own anchor), "Where Recordings And Backups Live", "What Each Publish Surface Means", "The CDN Cost Estimate Is A Guess, Not A Quote", and "Don't Have A GitHub Account?". Every provider readiness card (`ProviderReadinessItem.manual_section`, `civiccast/installer/service.py`) and several setup panels now carry a "Read more in the manual" link straight into the matching section. Federation: `POST /api/staff/activitypub/keygen` (`civiccast/activitypub/router.py`) generates the same RSA station key `civiccast activitypub keygen` does, server-side, behind a real button in `ActivityPubScreen.tsx` — replacing the raw CLI instruction — plus a plain-language paragraph on what federation is and that most stations don't need it. Applying the generated settings and restarting CivicCast is still a separate manual step (`load_activitypub_config` reads strictly from process environment, matching the existing beta-handoff "ask a technical administrator to restart" pattern in `civiccast/installer/handoff.py`); the CLI-typing barrier for a non-technical operator is gone regardless.

- **Assets/Library upload control, watch-folder Scan now + folder picker, and
  caption-trigger discoverability — field evidence from a non-technical
  tester (candidate #17), findings 1-6.** A tester walkthrough found the
  Assets ("Library") screen had no upload button or file input at all (only
  the six-card First Setup rehearsal picker had one, unlabeled as an
  upload); watch folders required typing an exact filesystem path with no
  "Browse..." picker and no way to force an immediate check (a fresh
  config's "Last poll: never" read as broken even when the daemon HAD
  ingested within about a minute); and nothing told an operator that
  approving publish is what starts offline caption transcription, nor that
  a running job was actually running.
  - **Assets screen upload** (`AssetUploadControl`,
    `civiccast/apps/portal-operator/src/components/assets/`): reuses the
    exact `/api/staff/assets/upload` endpoint the First Setup card already
    calls (never a second pipeline) via a new XHR-based client function,
    `uploadAssetFileWithProgress`, added alongside (not replacing) the
    existing `fetch`-based `uploadAssetFile`. Every state designed: idle
    (collapsed behind one "Upload video" button), choosing, client-side
    unsupported-type rejection naming the accepted formats before any
    network call, uploading with a real percent progress bar + a
    screen-reader `aria-live` announcement + cancel, success (asset
    appears in the table via query invalidation), and failure surfacing
    the server's plain-language reason with a "Try again" retry. Gated on
    the SAME roles the backend requires (`records_clerk`,
    `meeting_operator`, `support_admin`) — never hidden for a role that
    lacks it, only disabled with the reason stated, matching this app's
    existing "Package for playback" pattern.
  - **Watch folders** (`civiccast/schedule/media_lifecycle_router.py` +
    `MediaLifecycleSettingsScreen.tsx`): new
    `POST .../watch-folder-configs/{id}/scan-now` runs the SAME per-folder
    scan the poll daemon's own pass uses
    (`WatchFolderWorker.scan_now`, bypassing the due-check), returning what
    it found so a "Scan now" button gives real, immediate feedback instead
    of waiting out `poll_interval_seconds`. A fresh, never-polled config's
    status now reads "Not scanned yet — the next automatic check runs
    within Ns, or use Scan now" instead of a bare "Last poll: never" /
    "Last ingest: never." New `GET .../browse-folders` lists local
    directories (drive roots on Windows / `/` on POSIX when no path is
    given) for a non-technical operator to navigate instead of typing a
    path from memory — the browser cannot hand back an absolute path
    itself (the File System Access API and `<input webkitdirectory>` both
    withhold it for security), but this app's frontend and backend always
    run on the same station machine, so the backend lists directories for
    a new `FolderBrowser` modal picker instead. `monitor_path` is now
    validated server-side on create/update: a missing or unreadable
    directory 422s with a plain-language reason instead of being accepted
    and only discovered broken on the next poll.
  - **Caption-trigger discoverability** (`OfflineCaptionJobsPanel.tsx`,
    `PublishDashboardScreen.tsx`): the offline-captions panel now states
    plainly, up front, that approving a recording's portal surface on the
    Publish dashboard is what starts transcription — there is no separate
    "generate captions" control anywhere in the console, by design. The
    Publish dashboard itself now carries the same note next to "Approve and
    Publish selected" so an operator learns this before clicking, not only
    after, on the asset detail page. A running job now reads
    "Transcribing… (Xm)" with elapsed time instead of a bare "Pending"
    label indistinguishable from stalled, and sets a real-world time
    expectation (measured ~37s for 11s of audio on a 32 GB CPU-only
    reference machine — several minutes for a full meeting recording, not
    seconds). The caption engine itself is unchanged; this is copy and
    affordance only, per the tester's own note that captions already work
    end-to-end. (The AI Models screen's separately-tracked inaccurate
    "≈500 ms typical" latency claim was not touched — different screen,
    different owner.)
  - **Readiness dot vs. publish status** (`AssetsScreen.tsx`,
    `ReadinessBadge.tsx`): a tester found a packaged-and-published asset
    still showing "⚪ Not ready" and read it as broken. Investigation:
    `readiness_state` is computed purely from ingest-time transcode/proxy
    pipeline status (`civiccast/schedule/media_lifecycle_worker.py`) and
    was never meant to track publish state — `published_at`/`manifest_url`
    are a separate, already-visible column. Rather than silently
    redefining readiness semantics, the dashboard's existing (previously
    unrendered) `readiness_reason` is now shown as a tooltip +
    screen-reader text on every badge, and a published-but-not-`ready`
    asset gets an explicit note: "Already live on the portal — this dot
    tracks the optimized playback proxy, not publish status."
  - Accessibility (WCAG 2.2 AA): every new control is keyboard-operable
    with a labeled input, and upload/scan/caption progress is announced via
    `role="status" aria-live="polite"`, not conveyed by a spinner alone.
  - Tests: 3 new backend pytest classes (path validation, scan-now,
    browse-folders) in `tests/schedule/test_media_lifecycle_router.py`; new
    `AssetUploadControl.test.tsx` and `FolderBrowser.test.tsx`
    (vitest); extended `AssetsScreen.test.tsx`,
    `MediaLifecycleSettingsScreen.test.tsx`,
    `OfflineCaptionJobsPanel.test.tsx`, `PublishDashboardScreen.test.tsx`;
    new Playwright specs `e2e/assets-upload.spec.ts` and
    `e2e/media-lifecycle-watch-folders.spec.ts`, plus caption-discoverability
    coverage added to `e2e/asset-detail.spec.ts` (each with its own axe-core
    WCAG scan).
- **"Publish to residents" control on the Schedule screen — a scheduled premiere never reached the public portal without a separate, undiscoverable manual step (field evidence, candidate #17, Monday blocker).** Tester quote: "Schedule → premiere: 'Schedule premiere' succeeds (item state `scheduled`) but it NEVER appears on the portal's 'Coming up'. A separate playout commit-to-air is required, and the operator console has NO button for it." Proven live: `POST /api/staff/schedule` → 201 (`scheduled`); portal `GET /api/public/schedule/coming-up` → `[]`; only a hand-called `POST /api/staff/playout/commit` made the premiere appear — an operator schedules the board meeting, sees success, tells residents to tune in, and nothing ever airs, with no error. (The Commit-to-Air gate itself already existed — `civiccast/schedule/playout_router.py`'s `prepare-commit`/`commit` plus the review UI in `CommitToAirPanel.tsx` — buried in the separate Channel Ops screen, which a volunteer scheduling from the Schedule screen had no reason to ever visit.) Wires that existing gate into the Schedule screen: a scheduled premiere row now says **"Not yet visible to residents"**, and a new **"Publish to residents"** action runs the existing prepare-commit dry-run (same conflict/gap/missing-media review) and only commits on a second, explicit click — never auto-committed on schedule. Manually-scheduled premieres never materialize a `SlotOccurrence`, so this reuses the `manual:<schedule_item_id>` synthetic-id convention `civiccast/programlog/router.py` already established for surfacing the same items to Channel Ops. Role-gated the same way Channel Ops gates it (`publish_operator`/`setup_admin`) — disabled and explained, never hidden, for other operators. Embargo items are untouched (they release through a separate single-moment mechanism the gate structurally rejects) and never get this copy or button. Along the way, fixed `api/client.ts`'s error-detail parsing, which didn't recognize the playout commit's 409 body shape (`{message, conflicts}`) as "has a message" and was dumping raw JSON at the operator instead of the real conflict reason.
- **S7 watch-folder poll daemon (the piece PR #19 explicitly deferred).**
  PR #19 built `WatchFolderConfig`'s data model, CRUD API, and settings UI
  but shipped no daemon — nothing polled `monitor_path`, detected files, or
  called into ingest, so spec §6 DONE criterion 9 ("watch-folder hands-off;
  operator sees ingests") was unmet despite `ROADMAP.status.yaml` already
  carrying `status: built` for the section. `civiccast/schedule/
  watch_folder_worker.py`'s `WatchFolderWorker` (migration
  `0080_watch_folder_daemon`, chained after `0079_media_lifecycle`) is that
  daemon, same env-gated inline/off + poll-seconds shape as the sibling S7
  workers: polls each enabled config's `monitor_path` (local disk, USB, or
  NAS/SMB) on its own `poll_interval_seconds` (new column, spec default 5s
  — distinct from the pre-existing `settle_window_seconds`, the D13
  write-completion stability window); detects new/changed files via a
  durable per-file ledger (`watch_folder_file_state`, new table) requiring
  size+mtime unchanged across two consecutive polls before ingest (partial-
  copy safety); ingests through the SAME upload pipeline an operator's
  manual upload uses (`PostgresAssetStore.ingest_upload`) — never a
  parallel pipeline — recording provenance via `MediaIngestJob(source_kind=
  "watch_folder", source_path=<original path>)`; verifies post-copy size
  match (catches a truncated SMB copy); applies the operator's chosen
  processed-file disposition, `leave_with_ledger` (default) or
  `move_to_subfolder` (new `processed_file_mode`/`processed_subfolder_name`
  columns) — **neither mode ever deletes the source file**
  (delete-safety posture, see below); surfaces an unreachable path as a
  visible per-config degraded state (new `health_status`/`degraded_reason`/
  `degraded_since`/`last_poll_at`/`last_ingest_at` columns) rather than
  failing silently; and re-ingests a changed already-ingested file against
  the SAME asset via `MediaLifecycleStore.apply_replace_source` (now
  accepting a `source_kind` parameter so watch-folder-originated
  reprocesses are provenance-tagged correctly) instead of creating a
  duplicate asset. Concurrency: per-folder work is fully serialized; up to
  `max_concurrent_folders` (default 4) different folders may be scanned at
  once; `max_files_ingested_per_pass_per_folder` (default 25) bounds one
  pass's per-file work. Processed-file disposition, degraded-state
  visibility, and the delete-safety posture were open decisions the spec
  text itself didn't resolve — recorded in
  `docs/adr/0024-watch-folder-daemon-processed-file-and-degraded-state.md`.
  Registered as `civiccast-watch-folder-worker` in the app lifespan's
  `ThreadSupervisor` list (same RAT-001 maintenance-mode fail-closed
  posture as every other background worker). Settings screen: a new status
  column per watch folder (health, last poll, last ingest, and — when
  degraded — the reason, `role="alert"`). Tests: 10 tmp-dir-based
  end-to-end worker tests (real filesystem, real ffmpeg-generated video
  content through the real ffprobe pipeline where ffmpeg is on PATH) +
  5 app-wiring tests + 6 settings-screen vitest tests. Known gaps, called
  out in the spec file's own build note and ADR 0024 rather than silently
  claimed: no 24h unattended soak, no real-NAS/SMB field test, and the
  spec's "asynchronous retry/backoff" + "CRC" wording for SMB resilience
  is approximated (poll-interval-paced retry rather than sub-second
  backoff within a pass; size verification rather than a full source-side
  content hash, which would double read I/O over the network per file).
- **S3/S11 — CEA-708 commissioning decode-back verification.** Closes the gap
  PR #22 left honest but open: the S3 commissioning wizard's Screen 10 output
  proof previously always reported `cea708_verified: null` with a blocker when
  CEA-708 passthrough was requested, because no decode-back check existed. New
  module `civiccast/installer/cea708_verification.py` writes a deterministic
  test caption, embeds it through the product's real GStreamer sidecar
  caption-embed leg (`egress/gst/graph.py caption_embed_leg_from_sidecar`, run
  via `egress/gst/worker.py` over the same D2 control seam
  `scripts/prove_native_live_caption_transport.py`'s code already assembles
  this way for the live appsrc leg), then decodes the emitted stream back
  with the existing engine-agnostic
  `civiccast.egress.caption_proof.decode_embedded_captions` and compares.
  `run_output_proof` (`civiccast/installer/commissioning.py`) now calls this
  after the main test-pattern/TSDuck window (injectable via a new
  `caption_verifier` parameter) and reports a real `True`/`False`
  `cea708_verified` with detail — it stays `None` only when the check itself
  could not run. Standalone: `civiccast egress verify-captions` runs the same
  check outside commissioning. Along the way, found and fixed a real latent bug
  in `civiccast/egress/caption_embed.py`'s `_clean_caption_text`: it had never
  been exercised against real ffmpeg-decoded closed-caption output before
  (only hand-written SRT text in tests), so the ASS position tag
  (`{\an7}`) ffmpeg's `eia_608`/`cc_dec` decoder always wraps real decoded text
  in would have made every genuine decode-back text comparison mismatch, even
  when captions embedded and decoded correctly — fixed and covered by a
  regression test. New test fixtures
  `tests/egress/fixtures/cea708_{test_caption,no_captions}.mpegts` are real,
  tiny (~18 KB) MPEG-TS captures with genuine hand-built ATSC A/53
  CEA-608-in-708 SEI data, verified against the actual production decode path
  while building this; `tests/installer/test_cea708_verification.py`,
  `tests/installer/test_commissioning.py`, `tests/egress/test_caption_proof.py`,
  and `tests/egress/test_caption_embed.py` gained new/updated coverage. **What
  remains honestly unverified in this dev/CI sandbox**: the real GStreamer
  embed-subprocess round trip (no `gi`/GStreamer runtime here) — covered by an
  `@pytest.mark.integration` test that skips without the bundled bindings; a
  native Windows box with the packaged runtime (or the WSL/system-GStreamer dev
  tier) is required to exercise it for real. See
  `docs/spec/3.0/sections/S3-commissioning-wizard.md`'s 2026-08-25 banner.
- **S27 (Agenda Import Bridge) Phase 4 — `js_portal` source for JS-hydrated
  agenda portals.** `civiccast/agenda_import/` already bridged Legistar,
  PrimeGov, and CivicClerk (each with a documented, anonymous, plain-HTTP
  endpoint — re-verified this pass, unchanged) into a draft S25
  `MeetingAgenda`; this phase adds a fourth adapter,
  `civiccast/agenda_import/js_portal.py`'s `JsPortalSource`, for the vendor
  family that has no such endpoint — CivicPlus AgendaCenter, Granicus, and
  JS-hydrated Legistar public pages — using
  [crawl4ai](https://github.com/unclecode/crawl4ai) (Apache-2.0) with a
  headless Playwright Chromium browser plus a confidence-scored text
  heuristic (reuses `AgendaItem.confidence` from the PR #21 PDF-import
  path; net-new `ExternalAgendaItem.confidence` threads it through the
  shared mapper). Bounded and sandboxed: same-origin only, robots.txt
  fetched and respected before any navigation, at most two pages per call,
  a wall-clock timeout, and no auth flow of any kind. Config is per-import
  (`portal_url` + `portal_vendor_hint`, validated via new
  `civiccast.agenda_import.config.validate_portal_url`) rather than a new
  migration — none was needed.
  crawl4ai + Playwright ship as the new, optional `civiccast[agenda-js-import]`
  extra, pinned to `crawl4ai>=0.9.2,<0.10` — **not** the first floor this
  extra was drafted against (`0.7.4`): that version pins `lxml~=5.3`, which
  collided with `pikepdf`/`sacrebleu`'s own `lxml` floor and forced uv's
  universal resolver to downgrade the whole project's `lxml` to 5.4.0,
  reintroducing PYSEC-2026-87 (fixed in 6.1.0) into `uv.lock` — caught via
  `pip-audit` against the resulting lock during this pass, before it ever
  reached a commit. `crawl4ai>=0.9.2` relaxed its own constraint to
  `lxml<7,>=5.3`; re-locked and re-verified clean (`lxml` stays at 6.1.2,
  `pip-audit` reports no known vulnerabilities). Not bundled by the native
  Windows installer by default
  (excluded from `requirements-native-app.txt`'s `uv pip compile` extras,
  mirroring `captions-runtime`'s existing pattern); absent, the adapter
  lazy-imports and raises a new `AgendaSourceDependencyMissingError` →
  HTTP 503, and a new, always-reachable `GET
  /api/staff/agenda-sources/js-portal/posture` route reports the honest
  install posture without raising. Also closes a real gap found while
  implementing this: an import into an **already-published** agenda now
  reopens it to draft (mirrors `AgendaService.import_from_doc`'s existing
  PDF-import behavior) — applied to all four vendors, not just
  `js_portal`, since AI/agenda non-negotiables §4.2 ("operator approves
  before publish") is equally about a Legistar/PrimeGov/CivicClerk fetch,
  not only heuristic content. Operator console: `AgendasScreen.tsx` gains
  an "External agenda import" section (source picker, discover-then-import
  flow, `js_portal`'s not-installed/loading/installed posture states) —
  the vendor-bridge API had no console consumer at all before this phase.
  62 new backend tests (`tests/agenda_import/test_js_portal.py`
  plus router/mapper additions) against synthetic CivicPlus/Granicus-shaped
  fixtures (no live-site CI dependency) and 14 new frontend tests; ruff/
  mypy --strict/tsc/eslint clean. Live-smoke-tested by hand against a real
  CivicPlus tenant (`friscotexas.gov/AgendaCenter`) — the crawl pipeline
  itself works end to end, but that tenant's real meeting rows only render
  after an interactive category-selection step this v1 does not perform,
  so today's extraction is an honest low-yield miss on that shape of
  tenant, not a silent wrong answer — see `js_portal.py`'s module
  docstring for the full live-verification ledger. See
  `docs/spec/3.0/sections/S27-agenda-import-bridge.md` (net-new — no
  spec section existed for this module before this phase) for the full
  design and status.
- **S14 (Analytics / Audience Measurement) — durable viewership store.**
  Migration `0076_analytics_viewership` (three tables: `viewership_events`,
  `viewership_rollups`, `analytics_report_snapshots`) promotes the
  playback-beacon → aggregate-report chain from a single JSON file
  (`analytics-events.json`) to a durable Postgres-backed store —
  `PostgresAnalyticsStore` plus a periodic `AnalyticsRollupWorker` that folds
  raw events into VOD-24h and Live-30-min/hourly rollup buckets. Idempotent
  one-time backfill migrates any pre-existing JSON events on first durable-
  storage boot. Net-new role-gated (`support_admin`/`publish_operator`) staff
  API: `GET /api/staff/analytics/rollups`, `GET .../export.csv`,
  `POST .../reports/board-pdf` (a one-click board-ready PDF — totals, top
  content, year-over-year, live-event peaks — via `reportlab`); `GET
  .../reports/overview` extended with `stream_type`/`metric` params and
  `vod_rollups`/`live_rollups`/`year_over_year`/`ingest_configured` fields.
  Operator console: `AnalyticsScreen` gains a four-panel dashboard (toolbar,
  bar + time-series charts via a new dependency-free SVG `RollupChart`
  component, stats + expandable rollup table) and an honest "telemetry is
  off" empty state when public analytics ingest isn't configured. As-run /
  proof-of-performance reporting (Schedule Report + Shows Report parity) is
  served by the existing `civiccast/reporting` surface (S18/S23) rather than
  duplicated. See `docs/spec/3.0/sections/S14-analytics-audience-measurement.md`
  for the full build-vs-spec status and known gaps (OTT/embedded beacon
  parity and the master soak run are not yet done).
- **S1 StationBoxProfile — cable/PEG appliance-readiness capability model.**
  `civiccast/platform/station_box_profile.py` extends `hardware.probe()`
  with a full readiness report: GStreamer playout-engine prerequisite
  detection per S15 tier (`EngineReadiness`/`EngineTierVerdict`), a
  RAM-keyed AI-default table (`select_ai_defaults`, `gemma4:12b` at ≥16GB
  system RAM), the fail-closed `PegReadinessRollup`, and the
  soak-pending `CableOsVerdict` (never prints a green single-Windows-PC
  cable certification before MASTER §13.1 resolves). Computed, no DB
  table. `civiccast doctor --profile` renders it (human + `--json`); the
  plain `doctor`/`doctor --json` output is unchanged for back-compat.
  `GET /api/staff/station-box-profile[/readiness]`, role-gated. New
  `GET`/`PUT /api/staff/station/profile` exposes the mutable station
  identity (name, timezone, storage roots) with an env-override-first
  precedence loader (`resolve_station_timezone`/`resolve_station_display_name`/
  `resolve_station_storage_locations` in `installer/station_state.py`);
  `app.py`'s `_station_tz` now delegates to the shared loader instead of
  re-implementing the precedence chain inline. New operator-console
  **Station Profile** screen. 40 + 13 + 11 new tests.
- **S3 commissioning wizard (screens 8-11).**
  `civiccast/installer/commissioning.py` implements the post-first-admin
  cable commissioning flow: first-run cable checks (11 checks, reusing S1's
  `StationBoxProfile` and the existing durable-storage/NATS health probes —
  no re-implemented probes), channel-setup validation against the S2
  `HeadendProfile` catalog, a bounded output-proof run (a real ffmpeg
  SMPTE-bars+tone generator driven concurrently with the existing TSDuck
  compliance prober, fail-closed), and the final commissioning report.
  State persists to station-state JSON (`CommissioningState`, one
  namespaced key, no DB table) so a restart mid-commissioning resumes
  from the last completed step. New `POST /api/staff/cable/commissioning/
  {checks,channel-setup,output-proof,report}` + `GET .../state`. New CLI:
  `cable doctor`/`commission`/`support-bundle`, `output sdi-readiness`,
  `egress output test-pattern`. New operator-console **Cable
  Commissioning** screen (4 server-state-gated panels). Every proof run
  carries an explicit `not_claimed` boundary: this is a headend/format
  proof via ffmpeg + TSDuck, not a physical SDI/DeckLink hardware proof
  (rung 3 remains gated on real DeckLink hardware, MASTER §13.2); a
  requested CEA-708 passthrough check is always reported unverified
  (`cea708_verified: null`), never faked. 23 + 11 + 6 new tests.
- **S10 field-certification amendment.** Dated 2026-08-21 amendment atop
  `docs/spec/3.0/sections/S10-field-certification-and-proof-ladder.md`:
  field certification for the native-Windows line is proven by Gate A
  (`docs/ops/gate-a.md`) and Gate B (the real-hardware 24h reboot soak),
  not by the rung-runner pipeline S10 originally specified (never built;
  the *legacy* pre-Gate-A rung-numbered pipeline that did exist was
  removed in PR #12, commit `ef27958`). The rest of S10 is kept intact as
  a historical design record.
- **S7 media lifecycle & readiness (real build; corrects a false `status:
  built` in `ROADMAP.status.yaml`).** The five net-new S7 entities
  (`MediaIngestJob`, `TranscodeJob`, `AssetReadiness`, `WatchFolderConfig`,
  `AssetRetentionPolicy`) plus `AssetArchiveProof` and an append-only
  `media_lifecycle_audit_log` land in one migration
  (`0079_media_lifecycle`, chained after PR #21's `0078_agenda_item_confidence`
  — renumbered from an original chain onto S14's `0076_analytics_viewership`
  when `0078` merged to `main` ahead of this branch),
  backed by `civiccast/schedule/
  media_lifecycle_{models,worker,store,router}.py`. The worker (mirrors
  `retention_worker.py`'s inline/off + poll-seconds + dry-run shape)
  recomputes each asset's readiness badge, seeds and dispatches ingest-time
  transcode jobs through an injectable `TranscodeExecutor` (production:
  `FfmpegTranscodeExecutor`; tests: a stub), and verifies archival. Staff
  API: `GET /api/staff/assets/readiness-dashboard`,
  `GET /api/staff/assets/{asset_id}/readiness`,
  `PUT /api/staff/assets/{asset_id}/replace-source` (old file archived, not
  deleted), `PUT /api/staff/assets/{asset_id}/legal-hold`, and CRUD +
  storage-budget + missing-media + audit-log routes under
  `/api/staff/media-lifecycle/*`. Operator console: a Readiness column on
  the Assets screen, a Media Lifecycle detail panel on the asset editor
  (loudness gate, archive tiers, legal hold, replace-source), a new
  Missing Media screen, and a new Media Lifecycle Settings screen
  (watch folders, retention automation, storage budget).
  Also closes a previously-unflagged gap behind CLAUDE.md's §4.6 archival
  non-negotiable ("nothing is marked archive-complete unless portal + IA +
  local NAS copies are verified"): nothing persisted `ArchiveProof` values
  before this, and `public_archive_complete` was an operator-settable bool
  with no verification behind it. `AssetReadiness.archive_complete` is now
  computed by the worker from verified, non-simulated `AssetArchiveProof`
  rows only. New `Asset.legal_hold` / `legal_hold_reason` columns;
  `retention_worker.py` now skips held assets outright, regardless of how
  far past `retention_until` they are.
- **This repository.** 2,090 files, ~24 MB, copied from the native-Windows
  release line. The old (private, not archived) repository's 286 MB of
  packed history — WSL-era churn plus roughly 640 MB of historical Git-LFS
  tester binaries — does not transfer, by construction.
- **S12 OTT apps — de-duplicated, CI-built on hosted runners.**
  `.github/workflows/ci-ott-apps.yml` is the first machine build for any of
  the `civiccast/apps/ott-native/` app sources: Roku gets a real
  BrightScript static check (`brighterscript`/`bsc`) + zip package; Android
  gets a real `gradle assemble*Debug` build (checked-in wrapper —
  `android/gradle/wrapper/gradle-wrapper.jar` was missing before this);
  Apple gets a real `xcodebuild build-for-testing` (unsigned, simulator) on
  `macos-latest`; LG webOS gets a real `ares-package` build
  (`@webosose/ares-cli`, no device needed); Samsung Tizen attempts a real
  `tizen package` build and honestly falls back to a static `config.xml`
  contract validation when the ~260 MB license-gated Tizen Studio CLI can't
  complete headlessly on the runner (see `tizen/README.md`). Also
  de-duplicated the source trees: `android-tv/` and `fire-tv/` (two entire
  copied Gradle projects differing only in `applicationId` and a few
  manifest lines) are now one module, `android/tv-app`, built as the `tv`
  and `firetv` product flavors; `ios/` and `tvos/` no longer each carry
  their own copy of `CivicCastApp.swift`/`CivicCastCore.swift` — both
  Xcode projects reference the single copy in the new `apple-shared/`.
  Added the two platforms that had no source at all: `tizen/` and
  `webos/`, both thin wrappers around one canonical playback client,
  `web-shared/civiccast-player.js`. Every native target now calls the real
  `StationAppConfig`/`LiveState` app-platform contract (fetch config,
  resolve the default channel, fetch its `live_state_url`, play
  `playback_url`) instead of a flattened per-platform stand-in JSON shape.
- `docs/design/` — six design records (supervisor, installer lifecycle,
  migration contract, dual-runtime guard, native-beta recovery, the sub-300 MB
  bootstrap plan) hand-carried out of the otherwise-scratch `.agent-runs/` tree.
- `docs/evidence/` — the proof documents `docs/claims/claims.yaml` binds, also
  rescued from `.agent-runs/`.
- `scripts/wp5_lifecycle_driver.py` — the WP-5 clean-venue lifecycle proof
  driver, previously marooned in `.agent-runs/` and imported by
  `tests/native/test_wp5_lifecycle_driver.py`.
- `scripts/policy/check_workflow_timeouts.py` — fails the build when a workflow
  job declares no `timeout-minutes` (GitHub's default is 360) or exceeds the
  180-minute cap without a written exemption.
- **Gate A — automated station-acceptance release gate.** Replaces
  builder-authored "it works" claims with a machine verdict: a clean Windows
  Sandbox install of a native-beta candidate kit, K1 activation, runtime
  health, both UIs rendered, the clerk loop (upload → publish → captions),
  the product egress engine verified with TSDuck, and a bounded soak —
  judged fail-closed by `scripts/gate_a_verdict.py` against files a harness
  wrote, never from prose. `sandbox-lab/` imports a standalone, manually-
  proven harness (`Host-Launch-Sandbox-Test.ps1` + `In-Sandbox-Report.ps1`)
  plus the v3.0 tester-handoff `soak-4h/` kit; `sandbox-lab/Run-GateA.ps1` is
  the host orchestrator (kit resolution from a `native-beta-candidate-artifacts`
  run, fresh install every run, evidence preservation); `.github/workflows/
  gate-a-station-acceptance.yml` runs it after every successful candidate
  build on a new `[self-hosted, windows, sandbox-lab]` runner
  (`sandbox-lab/runner/Install-GateARunner.ps1`, an interactive-logon
  scheduled task — Windows Sandbox cannot launch from a Session-0 service).
  Informational only until 3 consecutive green runs; promotion to a required
  check is owner-only. See `docs/ops/gate-a.md` for the full verdict-criteria
  table with §12 citations, including the documented `t4_engine` policy
  (`PASS_FFMPEG_FALLBACK` is a FAIL now that GStreamer is the default engine)
  and the known Aug-19 reference-run harness quirk (that historical run has
  no `DONE.json`, so its own fixture judges FAIL on `completion` alone — not
  a bug, see the doc's "Known harness quirk" section).

### Removed

- **The legacy pre-Gate-A "rung-numbered" release-gate pipeline.** CLAUDE.md
  already stated "there is no rung ladder and no time-boxed altitude
  schedule" and that verification is layered by change type, not a fixed
  cadence — this cleared out the Stage 1-7 (release-plan rungs 3.3-to-4.0)
  script family that the statement had already superseded. Gate A (sandbox-
  lab station acceptance, `docs/ops/gate-a.md`) is the live machine-gate
  replacement; Gate B (24h reboot soak) is separate, tracked on its own.
  36 files removed, ~7,650 lines:
  - Runner scripts: `scripts/run_stage1_release_gate.py` (the named Stage 1
    orchestrator, `STAGE_ID="3.3"`) and its 12 siblings
    (`run_stage1_lifecycle_proof.py`, `run_stage2_completion_report.py`,
    `run_stage2_operator_workflow_proof.py`, `run_stage3_completion_report.py`,
    `run_stage3_control_room_adapter_proof.py`, `run_stage4_completion_report.py`,
    `run_stage4_virtual_lab_proof.py`, `run_stage5_completion_report.py`,
    `run_stage5_migration_records_proof.py`, `run_stage6_completion_report.py`,
    `run_stage7_completion_report.py`, `run_stage7_final_readiness_proof.py`),
    plus their two shared helpers `scripts/stage_report.py` and
    `scripts/run_stage_gate.ps1`.
  - Their 14 dedicated tests (`tests/test_stage1_release_gate.py` through
    `tests/test_stage7_final_readiness_proof.py`, plus `test_stage_report.py`).
  - Their 7 dedicated runbooks under `docs/ops/` (`stage-completion-gate.md`,
    `stage1-installer-lifecycle-verification.md`, `stage2-operator-workflow.md`,
    `stage4-virtual-media-studio.md`, `stage5-migration-archive-records.md`,
    `stage6-resilience-compliance.md`, `stage7-final-readiness.md`).
  - No `.github/workflows/*` ever invoked this family — it was CI-dead,
    manually run only. `docs/ops/stage3-audio-mixer-device-layer.md` and
    `docs/ops/stage3-control-room-device-adapters.md` were kept: despite the
    "Stage 3" filename pattern, they are real operator-facing device
    reference docs (Allen & Heath SQ MIDI protocol, vMix/OBS/ATEM adapter
    behavior) that live product code
    (`civiccast/control_room/lpm_lab_stage45.py`) still points operators to.
    `docs/spec/3.0/sections/S10-field-certification-and-proof-ladder.md`
    (the master §5 proof-ladder spec text) was left untouched: it already
    states its release-gate checklist is "missing" / implementation
    readiness "TBD" rather than claiming the deleted machinery exists.

- **The WSL2/Ubuntu bootstrap lane, finished.** CLAUDE.md and BRANCHES.md
  already declared the WSL2 lane retired (2026-08-19) and "not present
  here"; this cleared out the leftover code, tests, and documentation that
  still built, tested, or described it as if it were.
  - `civiccast/apps/installer/src-tauri/src/main.rs`: the entire WSL2/Ubuntu
    installer lane — `is_wsl_bootstrap_lane` and its dispatch branch, the
    `StartupBranch` native-vs-WSL split (collapsed to native-only, since
    every Windows control plane this binary produces IS the native one),
    the WSL2/Ubuntu feature-enable and provisioning pipeline
    (`launch_wsl_ubuntu_install`, `install_wsl_ubuntu_for_current_user`,
    `run_wsl_health_sequence`), and the headless runtime-bootstrap pipeline
    built around the already-deleted `headless-bootstrap.ps1` resource
    script (`run_headless_bootstrap`,
    `bootstrap_civiccast_runtime[_headless]/_via_script`, the
    `--civiccast-bootstrap-unattended` CLI flag). ~2,530 net lines removed.
    Two real leftover bugs fixed in the same pass, not just dead code: the
    "Open installer log" button pointed at two files that no longer exist
    (now points at the native runtime host's own `runtime-host.log`), and
    the "repair"/"retry"/"continue" installer actions on the runtime-family
    lanes called into the deleted headless-bootstrap pipeline (now start
    and re-verify the native runtime host process, reusing the same
    primitives the startup path already used). The runtime-host watchdog
    (`run_civiccast_runtime_host`, `--civiccast-runtime-host`) no longer
    spawns or monitors a companion `wsl.exe` process or shells into a WSL
    distro to restart `civiccast.service` — `CivicCastSupervisor` is a real
    Windows service with its own SCM restart-on-failure actions, so the
    watchdog's job for native is honest health observation, not a second
    recovery path.
  - `civiccast/apps/installer/src-tauri/nsis-hooks.nsh` — the retired WSL2
    product's NSIS hook file (distro autostart/terminate/unregister). The
    base `tauri.conf.json` no longer declares `installerHooks` referencing
    it; nothing in this repository's build scripts or CI ever built that
    base config directly (they always pass
    `--config tauri.native.conf.json`), so nothing that ships changed.
  - The installer frontend's dead WSL2 lane UI: `wsl-affordances.ts`
    (renamed `lane-affordances.ts` with the WSL predicates removed — the
    prior retirement pass had already hardcoded them to always return
    `false` rather than deleting the branches that read them),
    `keyboard-activation.ts`/`.test.ts` (its entire purpose was arming a
    shortcut on the WSL bootstrap lane, always-false and therefore dead),
    `progress-visual.ts`'s `isWindowsBootstrapProgress`/
    `windowsBootstrapProgressIsIndeterminate`, `installer-transition.ts`'s
    `markWindowsBootstrapResultPending`, and every WSL-only branch in
    `App.tsx` (the `WindowsSetupActivity` component, the WSL half of
    `continueLane`, the dead keyboard-shortcut effect).
  - `civiccast.installer.platform`/`civiccast.installer.service` (Python):
    the *backend* twin of the same leftover, and a live one —
    `/api/staff/installer/summary` (the endpoint the installer frontend
    actually polls) could still produce `platform="windows-wsl2"` and "Set
    up Windows helper" wording under real, reachable conditions, not just
    from a legacy state file. `PlatformBootstrapPlan`'s `os_family` no
    longer accepts `"windows"` (Windows readiness is decided entirely by
    this process's own native-station activation signals now); the
    Windows-drive-to-WSL-mount path translation in
    `_backup_destination_path` is gone; the support bundle's log collector
    no longer looks for `bootstrap-wsl2-ubuntu.log` under
    `%LOCALAPPDATA%\CivicCast` (a path nothing writes to anymore) and now
    reads the native runtime host's own log instead.
  - `civiccast/installer/contribution_install.py`: coturn's Windows
    guidance no longer says "run it under WSL" — coturn has no native
    Windows build, so it is now a documented **external** TURN server
    (`CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT` point at one;
    `CIVICCAST_COTURN_COMMAND` stays unset).
  - `scripts/policy/check_release_artifacts.py`'s cross-platform installer
    policy check had the WSL retirement backwards: it FAILED any doc that
    claimed "native windows service" or "without wsl2", instructing the
    author to rewrite Windows claims as WSL2-only bootstrap support. It now
    rejects the opposite — a doc that still claims the Windows installer
    requires or bootstraps WSL2. Running the corrected check immediately
    surfaced a real violation: `INSTALL-WINDOWS.md` was written entirely
    for "the public WSL2 line (`main`, `v1.0.0-rc18`)" and linked to three
    release-verification docs and a GitHub release page that belong to the
    old, private `scottconverse/civiccast` repository and do not exist or
    resolve here. Marked the WSL2-line content historical (kept, not
    deleted — rewriting a historical beta's own record would be
    revisionist) and did the same for `docs/installer/
    cross-platform-installer.md`, `docs/installer/beta-tester-handoff.md`,
    and `docs/adoption/early-adopter-quickstart.md`.
  - `tests/policy/test_windows_wsl_bootstrap_script.py` (deleted) and
    `tests/installer/test_uninstall_residuals.py` (deleted): of the former's
    ~45 tests, 32 tested the deleted WSL2 pipeline or NSIS macros; the
    other ~13 tested genuinely shared infrastructure (IPC capability,
    blocking-pool dispatch, the local installer-state read/write path) and
    were carried into the newly added
    `tests/policy/test_native_installer_runtime_infra.py`. The latter's
    tests entirely exercised the deleted `nsis-hooks.nsh` macro and a
    disposable WSL clean-machine verifier; the native hooks file
    (`nsis-hooks-bootstrap.nsh`) already has its own dedicated coverage in
    `tests/installer/test_nsis_bootstrap_hooks.py`.
  - `tests/policy/test_native_installer_identity.py`: replaced its
    "native and WSL product identities are disjoint" assertions (moot once
    there is only one product) with a positive assertion that the native
    hooks file is the only one wired and the base config declares no
    `installerHooks` of its own.
  - `tests/installer/test_platform_bootstrap.py`: rewritten to cover only
    Linux/macOS — one deleted test asserted that a *native* Windows service
    plan gets **rejected**, the exact opposite of current reality.
  - Stale "WSL2 is the primary/current/public" framing corrected in
    `README.md`, `ARCHITECTURE.md`, `FAQ.md`, `SUPPORT.md`,
    `CONTRIBUTING.md` (its base-branch instruction pointed contributors at
    a `release/native-beta-1.0.0-beta.1-rc1` branch that does not exist in
    this repository), `SECURITY.md`, `CLAUDE.md` (the old repository is
    private, not archived — two instances), and
    `civiccast/platform/hardware.py`'s `OSKind` doc (cited the
    now-superseded ADR-0003 and called native Windows "not a supported
    deployment"). `.github/ISSUE_TEMPLATE/bug-report.yml`'s deployment
    dropdown no longer offers "Windows 11 + WSL2 (Ubuntu 24.04)" or
    "Docker" as options.
  - `civiccast/native/*` and `civiccast_native_uninstall.rs`'s
    `native`/`wsl`/`absent` `ActiveRuntime` selector, cutover/rollback
    commands, and dual-runtime start guard are **unchanged, deliberately**.
    This is real coexistence-safety logic for a machine that may still
    carry a live WSL CivicCast install or registry ownership marker from
    before the retirement — it protects against a native install/repair
    silently clobbering that other product's ownership state, which is a
    different concern from installing or running CivicCast on WSL.
- **The WSL2/Ubuntu leftovers wave 1 held back, finished (wave 2).**
  - `scripts/build_release_artifacts.py` (~1,540 lines) — the WSL2-target
    release-artifact pipeline (Linux wheelhouse build for the retired
    WSL2 install target, a WSL clean-machine preflight script generator).
    Not wired into any live workflow after `release-artifacts.yml` was
    deleted; its only in-repo callers (`scripts/run_stage1_release_gate.py`,
    `scripts/run_stage7_final_readiness_proof.py`, `scripts/stage_report.py`)
    are themselves pre-Gate-A, pre-native-repo legacy orchestrators
    (rung-numbered `3.3`→`4.0`, superseded by Gate A) that only embed its
    path as a subprocess command string in unit tests, never execute it in
    CI. Deleted with its dedicated test coverage
    (`TestReleaseArtifactBuilderContracts` and the WSL clean-windows-verifier
    test in `tests/installer/test_package_artifacts.py`, the release-manifest
    coherence test in `tests/installer/test_beta_handoff.py`). Docstring/
    comment references in `civiccast/installer/packages.py`,
    `scripts/policy/check_sidecar_attestation_integrity.py`, and
    `civiccast/installer/handoff.py`'s operator-facing guidance updated to
    stop pointing at the deleted script.
  - `scripts/run_airgap_vm_proof.py` and
    `scripts/prove_native_inventory_reconciliation.py` — both required a
    WSL2 VM / an extracted WSL installer's bootstrap+wheelhouse as
    mandatory inputs that do not exist in this repository (the WSL backend
    was already purged). Deleted with their tests
    (`tests/integration/test_airgap_vm_proof.py`,
    `tests/native/test_inventory_reconciliation.py`); the collection-count
    floor in `tests/policy/test_native_caption_workflow_policy.py` re-derived
    accordingly.
  - `scripts/run_clean_windows_install_proof.py` — a genuinely native-Windows
    proof runner; kept, with its `wsl2-fresh-distro`/`wsl2-fresh-user`
    isolation strategies and their WSL-detection helpers
    (`_detect_ubuntu_wsl_distro`, `_wsl_python312_ready`, `_to_wsl_path`,
    the `partial` proof status they produced) removed, and its VirtualBox
    report validator's dependency-absent first-run check fixed: it required
    a `current_lane_id: "wsl2"` / "Set up Windows helper" installer state
    that the installer can no longer produce at all (the whole "blocked,
    needs a Windows helper" first-run status was retired with the WSL2
    lane), which meant the check could never pass on a real report. Its
    test suite (`tests/integration/test_clean_windows_install_proof.py`)
    updated to match.
  - `civiccast/apps/installer/scripts/verify-bundle-resources.mjs` — the
    Tauri bundle-resource guard required a Linux wheelhouse and a Linux
    GStreamer runtime tarball (for the retired WSL2 hand-off) that nothing
    in the shipped app reads at runtime, and its error message pointed at
    the now-deleted `build_release_artifacts.py`. `scripts/build_native_installer.py`
    already bypassed this exact guard for that reason (see its updated
    `run_tauri_build` docstring); the guard itself now only requires
    `bootstrap-manifest.json`, the one resource `main.rs` actually reads.
  - `civiccast/egress/gst/{engine,worker,graph,control}.py` — WSL-specific
    docstring/comment wording (`"WSL/Linux"`, `"WSL/LPM-validated"`)
    generalized to POSIX/Linux-macOS, since the dual-platform logic itself
    (Windows named-pipe vs. POSIX FIFO control channel) was never
    WSL-specific — it is unchanged. `docs/claims/claims.yaml` re-bound to
    the new blob hashes for all four files (two claim entries plus the
    `graph.py` fixtures entry); `audio_tap.py` had no WSL text and was not
    touched.
  - Rewrote `docs/USER-MANUAL.md`'s WSL2/Ubuntu install-flow claims (the
    installer bootstrapping a WSL2 helper and SQLite storage, GStreamer
    under `/opt/civiccast/gstreamer`, TSDuck installed into WSL2 Ubuntu,
    provisioning "inside Ubuntu WSL2") to describe the real native install
    (Windows service via SCM, bundled runtime tree, on-demand per-user
    TSDuck fetch) and repointed all 41 `scottconverse/civiccast` blob/tree
    links to `scottconverse/civiccast-native`; regenerated
    `USER-MANUAL.pdf`/`.docx`/`.render.json` (`--check-current` PASS).
    `docs/technical-ops-reference.md`'s stale WSL2 wheelhouse air-gap
    instruction removed (the paragraph already disclosed the claim as
    unproven for native).
  - `civiccast/apps/installer/README.md`'s "Current Posture" section
    described the retired WSL2 Ubuntu/systemd/`/opt/civiccast` runtime
    wholesale; rewritten to describe the real native Windows service.
  - Added historical banners (matching the existing pattern in
    `docs/installer/beta-tester-handoff.md` and
    `docs/installer/cross-platform-installer.md`) to
    `docs/tester/known-limitations.md`'s WSL Public-Beta Line section and
    `docs/tester/station-implementation-walkthrough.md`, both of which
    described the retired rc-numbered WSL2 line's setup/release process
    without any such disclaimer. Removed the WSL2 support-bundle caveat
    from `docs/tester/support-bundle-instructions.md` and corrected its
    claimed log source to the real native runtime-host log; removed the
    WSL2 Ubuntu distro field from `docs/tester/bug-report-template.md`.
  - `Makefile`'s `cleanroom`/`cleanroom-build`/`cleanroom-run`/
    `cleanroom-shell` targets referenced `docker/cleanroom.Dockerfile`,
    which does not exist in this repository (`docker/` was excluded with
    the retired lane). Removed; `.pipelines/roles/pre-push-verifier.md`'s
    matching "run `make cleanroom`" step rewritten to say plainly that no
    automated clean-box gate exists here, per the same rule already stated
    in this file's "Verification that actually gates this repo" section.
  - Fixed `gh api repos/scottconverse/civiccast/...` commands that should
    have targeted this repository in `docs/ops/branch-protection.md`,
    `docs/ops/self-hosted-ci.md`, and this file's own cross-agent audit
    protocol section — each would have queried or modified the wrong
    (private, old) repository if actually run.
  - `.github/ISSUE_TEMPLATE/config.yml`'s security-report and release-plan
    contact links repointed to this repository (both exist here); its
    Discussions link left pointing at the old repository with an honest
    note, since `scottconverse/civiccast-native` does not have Discussions
    enabled. `SUPPORT.md`'s GitHub Issues link repointed the same way.
  - Three `TODO`/`FIXME`/`HACK` markers `scripts/policy/check_no_todos.py`
    flags as blockers (`civiccast/captions/router.py`,
    `civiccast/egress/router.py`, `civiccast/native/upgrade/seams.py`)
    moved into a new `next-cleanup.md` and reworded in place per that
    policy's own stated design; `docs/openapi.json` regenerated (the routes'
    descriptions changed).

- **NATS JetStream, removed entirely (2026-08-20, owner decision).** NATS
  never did real production work in this codebase — the platform
  event-broker substrate always defaulted to an in-process adapter — so it
  is cut from the product: the supervised child process, the
  `civiccast.platform.nats_broker` module, NATS provisioning, the
  installer's NATS/JetStream mTLS readiness check, the Rust installer's
  NATS references, the `nats` certificate identity
  (`civiccast/certs/authority.py`), and the corresponding tests. ADR 0023
  records the reversal and supersedes ADR 0001 (ADRs are immutable once
  Accepted — ADR 0001's own text is untouched; the supersession is recorded
  one-directionally in ADR 0023). `civiccast.platform.broker.InProcessBrokerClient` is the only
  broker adapter for every deployment mode; `civiccast.platform.broker_config`
  no longer has a "production" mode, NATS URL/stream/mTLS settings, or a
  JetStream readiness gate. This closes out the size, process, port, config,
  and health-gate cost NATS carried without ever being load-bearing.

### Changed

- **Bounded the `testcontainers[postgres]` dependency below its 4.15 module move, which turns a deprecation warning into a hard pytest collection error.** A fresh worktree installed with `uv pip install -e ".[dev]"` (bypassing `uv.lock`, which correctly pins `testcontainers==4.14.2`) resolved to 4.15.0, whose `testcontainers.postgres` module warns at import time that it moved to `testcontainers.community.postgres`; `pyproject.toml`'s `filterwarnings = ["error", ...]` turns that warning into a collection error in the six modules that import it. Confirmed CI itself was never affected and no test file was ever silently excluded — every workflow installs via `uv sync` (which respects the lock), and a collection error is loud (pytest reports `errors`, exits non-zero), so had this reached CI it would have failed the build rather than quietly dropping the six files. The unbounded `>=4.7` specifier left the lockfile as the *only* thing preventing a broken collection for anyone doing a plain editable install or running `uv lock --upgrade` — exactly how this was found. `pyproject.toml` now pins `>=4.7,<4.15`, documented in place; `uv.lock` regenerated with a one-line change (testcontainers stays 4.14.2, nothing else moved). Verified: `uv lock --check` clean; the six previously-affected files collect 114 tests, 0 errors; full-repo collection under the lock is 10286 tests, 0 errors. Deliberately not done here: migrating the six modules to `testcontainers.community.postgres` and lifting the bound — the locked 4.14.2 predates that module, so the imports and the pin have to move together, and doing both during an active release push would risk the test infrastructure for no immediate gain.
- **Egress default engine flipped to GStreamer (S15).** `civiccast/egress/engine_select.py`'s
  `_DEFAULT` moves from `"ffmpeg-concat"` to `"gstreamer"` -- an unset
  `CIVICCAST_EGRESS_ENGINE` now selects the persistent-pipeline GStreamer engine,
  matching the native station bootstrap's own runtime contract
  (`civiccast/native/station_runtime.py`'s `EXPECTED_RUNTIME_CONTRACT`) and fixing
  the class of bug that continuity bug #151 belonged to (per-segment ffmpeg
  relaunches resetting the MPEG-TS continuity counter) for every caller that
  builds an `EncoderStrategy` without an explicit engine. `CIVICCAST_EGRESS_ENGINE=
  ffmpeg-concat` remains a live, fully-supported override for deployments that
  still need the legacy engine; the GStreamer -> self-repair -> FFmpeg ->
  fallback-slate degraded-mode chain (`station_runtime._resolve_gstreamer_egress_
  environment`, `egress.daemon.EgressDaemon`) is unchanged. Also fixes a latent
  edge case surfaced while flipping the default: a present-but-blank
  `CIVICCAST_EGRESS_ENGINE=` now resolves to the same engine as an unset one,
  instead of silently pinning ffmpeg-concat via its old membership in
  `_FFMPEG_ALIASES`.
- **Windows-only by decision.** No `docker/`, no systemd units, no WSL2 install
  target, no Linux GStreamer container build. The native product uses the
  pinned `gstreamer-*==1.28.5` PyPI wheels.
- `civiccast/egress/{service_unit,recovery,soak}.py` and the `.deb`/`.rpm`
  builders are gone, with `civiccast/cli.py`'s `egress enable` and
  `egress recovery-proof` subcommands. **`egress recovery-proof` was an
  operator-visible command** — it measured egress recovery against a systemd
  unit; the native equivalent is the supervisor plus
  `civiccast/native/gstreamer_repair.py`.
- Type checking (`ci-lint`) runs on `windows-latest`. The same commit reports
  112 mypy errors on Linux and 23 on Windows; the extra 89 are artifacts of
  checking Windows-only code on a platform this product never runs on.
- Artifact retention is **1 day** everywhere, at both the workflow and
  repository level.
- **Sigstore/cosign attestation requirement removed (ADR 0022).** Evaluated
  and denied by the owner: this release chain's only supply-chain provenance
  is Azure Trusted Signing (Authenticode) for the Windows installer plus
  ed25519 pack signing for native distribution packs
  (`civiccast/installer/native_packs.py`). `civiccast.installer.packages
  .verify_package_artifact` no longer requires a `*.sigstore.json` bundle —
  nothing in the native chain ever produced one — and instead checks real
  embedded Authenticode certificate-table evidence for a Windows `.exe`
  claiming `signed: true`; a `signed: true` claim for any non-Windows package
  kind is rejected outright, since this product line has no signing
  mechanism for those. `scripts/policy/check_sidecar_attestation_integrity.py`
  and `scripts/policy/check_release_artifacts.py` follow the same rule; package
  sidecars now always carry a null `attestation` field. `CODE_SIGNING_POLICY.md`,
  `docs/install/windows-release-trust.md`, and
  `docs/installer/cross-platform-installer.md` describe the Authenticode +
  ed25519 chain instead of Sigstore.

### Fixed

- **Assets screen readiness dot lied and the Upload video button vanished on click (candidate #17 field evidence, second report of both).** (1) An asset that was ingest-Validated AND Packaged — even one already Published and playing on the portal — still showed a bare "Not ready" dot, because the Readiness column rendered the S7 lifecycle worker's proxy-transcode readiness verbatim: whenever that worker had not written an `asset_readiness` row (fresh install, worker disabled, poll not yet due), every asset fell back to `not_ready`, and on the dashboard path with `readiness_reason=None`, so there was not even a tooltip. The column is now an honest per-asset Status derived from the asset row itself (`deriveAssetStatus` in `civiccast/apps/portal-operator/src/components/assets/assetStatus.ts`): Rejected / Missing file / Validating / Ingesting / Published / Packaged / Transcoding (n) / Queued for transcode / Not packaged yet / Not servable yet — each with a distinct label, tone, and plain-language detail (tooltip + screen-reader text). The lifecycle worker's readiness row is layered in only for transcode-in-flight and missing-file detail; its absence can no longer demote a packaged or published asset. The redundant "Packaging" column folded into the badge. Server side, `MediaLifecycleStore.dashboard()` now ships the same honest "Readiness has not been computed yet" reason the per-asset endpoint already sent instead of `None`. (2) Clicking "Upload video" made the button vanish and silently swapped in a form rendered above the operator's viewport (operator verbatim: "I assumed it was broken"). The trigger in `AssetUploadControl.tsx` now never disappears: it stays at the click location as a labeled active state ("Cancel upload", `aria-expanded`/`aria-controls`), the panel expands directly beneath it, scrolls into view, and focus moves to the Title field. Covered by new component tests in `AssetsScreen.test.tsx`, `AssetUploadControl.test.tsx`, and `tests/schedule/test_media_lifecycle_router.py`.
- **"No CG board yet" no longer logs a red 404 in the browser console on every CG Board / CG Designer open (field finding, real box, 2026-08-30).** `GET /api/staff/cg/channels/{channel_id}/board` treated a channel with no board — the normal state of every channel before an operator creates one — as an error and returned 404, so the operator console's poll left a failed network request in devtools on each page open even though the screen rendered its empty state correctly. The route (`civiccast/cg/board_router.py`) now returns `200` with JSON `null` for that state (`response_model=BoardView | None`), the contract the client was already written for: `getCgBoard` in `civiccast/apps/portal-operator/src/api/client.ts` is typed `Promise<BoardView | null>` and `CgBoardDesignerScreen.tsx` renders `null` as the empty state. Mutations against a missing board (PATCH board, zone/preview routes) still 404 — those are real errors. The screen's client-side 404→null guard (`useNoneOn404`) is kept for the preview route and for tolerance of older servers. OpenAPI artifacts regenerated (`docs/openapi.json`, `docs/API-REFERENCE.md`, `api.generated.ts`); router tests updated to pin `200` + `null` for the empty read and `404` for the mutations.
- **Staff token fratricide + stale-token self-lockout: every routine password sign-in silently signed out every OTHER browser or device, and a browser holding the rotated-out token then auto-retried it into the staff rate limiter until it was 429-locked with zero user action (owner-verified field bug, two-browser repro, 2026-08-30).** The 2026-08-29 multi-session fix made recovery APPEND to the bounded `operator_console.tokens` list but left ordinary password login REPLACING the entire list — so browser A signing in invalidated browser B's session minutes later, while the sign-in card promised the opposite ("without touching any other browser or device already signed in"). Three coordinated fixes:
  1. `civiccast/installer/station_state.py`'s `login_station_admin` now appends like recovery does (`_issue_operator_token` always appends; the `replace` parameter is gone). Concurrent sessions stay bounded at `_MAX_OPERATOR_SESSIONS` (20) with oldest-issued evicted first, and the pre-multi-session single-token legacy state shape still verifies unchanged. Renamed/updated tests: `test_station_login_and_recovery_keep_other_sessions_signed_in` (browser B's token must survive browser A's password sign-in), plus a login-flow twin of the recovery session-cap eviction test.
  2. `civiccast/apps/portal-operator/src/queryClient.ts`'s shared 401 handler now discards this browser's stored staff token the FIRST time the server rejects it (`clearStoredStaffToken` in `api/client.ts`) and records a `sessionStorage` signed-out notice. Previously every polling/screen query kept auto-resending the dead token, and each 401 spent staff-auth failure budget until the operator hit "Too many failed attempts... wait N seconds" mid-demo-prep and could not sign back in until cooldown. With the token cleared, subsequent requests carry no Authorization header at all and land on the middleware's budget-free missing-credential path (the day-one-lockout fix below), so one stale token can never saturate the limiter. Pinned in `queryClient.test.ts` (token cleared + notice recorded on 401; no notice for a never-signed-in browser; identity-query 401 also clears).
  3. `SetupScreen.tsx` shows an honest "You were signed out" notice (from that flag) above the sign-in card naming the real possible causes — oldest-session eviction under the concurrent-session cap or a sign-in state reset — and clears it on the next successful sign-in. The Admin sign-in card's existing "without touching any other browser or device already signed in" copy is now TRUE, and the recovery card's "Every other browser or device already signed in stays signed in" remains true.
- **Commissioning wizard blocked on every correct install: Screen 8 "Run cable checks" failed the bundled GStreamer 1.28.5 runtime for plugins the shipped product neither uses nor ships (field failure, candidate #19, 2026-08-30).** The `gstreamer_engine` check correctly detected the bundled runtime (the candidate-#17 PATH false-negative fix held) and then failed it as missing `compositor`, `interpipesrc`/`interpipesink`, `hlssink3`, `textoverlay`/`clockoverlay` — a probe bug, not a runtime gap. `civiccast/platform/station_box_profile.py`'s `_BASE_REQUIRED_PLUGINS` still mirrored S1 §6.5's original prose, which predates two recorded decisions: S15's dated Stage-0 decision (2026-06-14) demoted GstInterpipe to an optional future enhancement (the shipping hot-swap is `input-selector`, which `civiccast/egress/gst/engine.py` actually drives, and the RidgeRun plugin is not in the pinned wheels at all), and the engine's HLS output is the supervised ffmpeg relay over `udpsink` (`civiccast/egress/hls_relay.py` — no `hlssink*` ships) with a deliberately pango-free base slate (`civiccast/egress/gst/bridge.py`, D-S1-7). Verified against the kit's real `runtime-manifest.json` (221 files): every element the engine genuinely requires ships; none of the demanded extras do. The base-required set is now the shipped engine's true spine (`input-selector`, `mpegtsmux`, `udpsink`, `srtsink`, `videotestsrc`, `audiotestsrc`), asserted by test to stay a subset of the packaging closure's `REQUIRED_FACTORIES` so probe and pack can never drift apart again; the S15 CG-lite/native-HLS elements are still probed and honestly reported in `missing_plugins` (S1 §7-9) but no longer gate the base tier. The failure message is now actionable per runtime source: a bundled runtime missing a base element reports "incomplete install — re-run the installer's repair" instead of telling the operator to "install gst-plugins-base/good/bad/rs" into a runtime they cannot modify. Note: S1 §6.5's prose plugin list still carries the pre-decision wording and needs an owner-approved spec touch-up to match S15's recorded decision.
- **Accepted contributor content still never became airable in throwaway/dev-mode boxes, even after PR #65 (field survey, tonight's board demo, contributor flow: "accept never turns into an airable asset or a schedule item").** PR #65 (fix/contributor-accept-schedule-ingest, merged) made accept genuinely ingest the contributor's file into the asset library and made `schedule_item_id` non-null on send-to-schedule — both of those work, confirmed live. What PR #65's own end-to-end test never exercised was the packaging step: `civiccast/schedule/router.py`'s `package_staff_asset` calls `postgres_store.mark_packaged(...)` on whatever store `get_postgres_store` resolves to, and in throwaway/dev mode (`CIVICCAST_ALLOW_EPHEMERAL_STORES=1`, no `DATABASE_URL` — exactly the mode a quick board-demo box runs in) that store is `civiccast.app._EphemeralAssetStore`, which had no `mark_packaged` method at all (nor `mark_unpublished`, used by the sibling unpublish route). Packaging a validated asset in that mode — including one a contributor's accept had just created — raised `AttributeError` and surfaced as a 503 that never recorded a `manifest_url`. The asset row existed and was retrievable via the staff library (accept's own contract, honored), but could never reach a truly packaged/playable state: no manifest, nothing an operator could actually air, exactly matching the field survey's complaint even though the underlying `ContributorSubmission` row was, by that point, telling the truth. Added `mark_packaged`/`mark_unpublished` to `_EphemeralAssetStore`, mirroring `PostgresAssetStore`'s contract exactly (packaging sets `manifest_url` only — this codebase encodes "packaged" as manifest presence, not a separate state value; unpublish clears `published_at` and is idempotent). New coverage: `tests/contribute/test_router.py::test_accepted_submission_asset_reaches_packageable_state` drives the real operator sequence PR #65's test stopped short of — accept, package, confirm a real `/playlist.m3u8` manifest, still-working send-to-schedule, and idempotent unpublish — confirmed to fail on pre-fix code with the exact `AttributeError` above.
- **Scheduled recording (S21) captured nothing from a network stream on native Windows — every capture finalized to a 0-byte file (real-capture proof, this box).** S21's Recording page has claimed since it first rendered that scheduled recording can capture SDI/HDMI *and* network streams (RTSP/SRT/HLS/RTMP/MPEG-TS/NDI), but no test ever drove the real capture pipeline against a real, continuously-streamed source — every existing recording test injects a stubbed `CapturePipelineProtocol` by design. Standing up a real local UDP/MPEG-TS stream (ffmpeg, real footage) and driving the real `FfmpegScheduledCapturePipeline` end to end reproduced a total, silent failure: `arm`/`start` succeeded, the job showed `recording`, and every `stop`/`finalize` raised "ffmpeg created a zero-byte recording file" or "ffmpeg did not create a recording segment" — the job always landed `failed` with no asset. Root cause: ffmpeg's mpegts muxer buffers its output in the process's own memory (measured on this box: ~256 KiB) before an OS-level write, and `FfmpegProcessHandle.terminate()` (`civiccast/stream/_ffmpeg.py`) maps to Win32 `TerminateProcess` — an unconditional kill that gives ffmpeg zero chance to flush or write a trailer, unlike POSIX `SIGTERM`, which ffmpeg traps to shut down cleanly. Any capture whose total output never crossed that buffer threshold (which includes any short recording, and always includes the unflushed tail of a longer one) lost everything. Fixed by adding `-flush_packets 1` to the capture ffmpeg's output args in `civiccast/recording/runtime.py`'s `FfmpegScheduledCapturePipeline._launch` — the muxer now writes each packet to the OS as it's produced, so a Windows-abrupt kill loses at most the packet in flight instead of up to a quarter-megabyte of the most recent capture. Re-ran the same real-stream proof post-fix: a 5s capture at ~165 kbps produced a real, ffprobe-verified h264/aac asset (matching dimensions, nonzero duration) with `RecordingService`/`RecordingStore`/`ScheduledRecordingAssetFinalizer` all real, no stubs. New coverage: `tests/recording/test_network_capture_live_proof.py`, gated on ffmpeg/ffprobe like the existing egress live-playability proofs — real local UDP/MPEG-TS source (ffmpeg lavfi + libx264, deliberately low-bitrate so the window stays under the flush threshold), real `RecordingService.record_now_from_source` → `stop_job`, and an independent ffprobe re-check of the produced file. Verified to fail the same way pre-fix (`git stash` on the one-line fix reproduces "ffmpeg created a zero-byte recording file" every run) and pass reliably post-fix (3 consecutive runs, no flakes). SDI/HDMI/NDI capture is unproven either way — no capture-card hardware on this box; that remains open.

- **Upgrade crash-loop: an uninstall-old → reinstall-new upgrade whose previous install had acquired the optional `captions-large-v3` tier crash-looped the supervisor on every start (field failure, test box DESKTOP-2BR3SJR, UPGRADE-18-REPORT.md, 2026-08-30).** `components/captions-large-v3` under `ProgramData\CivicCast` survives uninstall by design (operator data is preserved), so `civiccast/native/station_runtime.py`'s tier resolution on the fresh install picked large-v3 with the acquisition root as its receipt root — but nothing on the new install ever wrote `activation-self-test.json` there (the elevated installer writes its receipt only at the install root; the GUI addendum writer runs only when the GUI itself downloads the tier). Model present, receipt absent → `NativeStationConfigurationError` on every start. Fresh installs are floor-tier-only with the receipt at the install root, which is why the Gate A sandbox and CI stayed green while the real upgrade path died. `load_native_station_environment` now degrades instead of raising when the resolved tier's base root has no readable/valid receipt AND the floor tier is staged: it re-validates and starts on the proven floor tier (the pre-2026-08-29 selection), logging a WARNING that names the orphaned tier and directory and tells the operator the higher caption tier will be re-validated/re-acquired from the operator console. The 2026-08-29 field fix (candidate 4eca729) is preserved exactly: a GUI-acquired large-v3 WITH its valid ProgramData addendum receipt is still preferred and validated as before, and a station with no provable tier at all (e.g. large-v3-only five-pack layout with no receipt) still fails closed. New coverage in `tests/native/test_station_runtime.py`: the exact field-failure shape (fails on pre-fix code), the no-floor fail-closed floor, and the unchanged addendum-receipt regression case.

- **Day-one lockout: a new operator who had NEVER signed in, and never typed a password, could 429-lock themselves out of the console just by loading it (adversarial audit + live browser repro, never signed in, no password ever typed).** Loading the operator console, then `#/help`, then `#/assets` — three ordinary page loads on a browser that had never authenticated — produced a run of `401`s on `/api/staff/*` followed by `429` on everything, with the on-screen message claiming "Too many unsuccessful sign-in attempts from this network," and the station recovered only after waiting out the window. Four distinct, independently-confirmed defects, all pre-existing except the last:
  1. `civiccast/auth/tokens.py`'s `_bearer_token(None)` raised the same `StaffAuthError` a wrong-token guess does, and `civiccast/auth/middleware.py`'s `staff_auth_middleware` verified both identically — so a MISSING Authorization header (the ordinary state of a signed-out browser) both spent the staff failure budget and was itself blocked by the saturation pre-check once that budget ran out. New `StaffAuthMissingCredentialError` (a `StaffAuthError` subclass) lets `_bearer_token` raise a distinguishable condition; the middleware now recognizes a missing header before either the pre-check or the budget is touched and always returns a plain `401` with zero rate-limit interaction. A present-but-wrong, malformed, revoked, or expired token still counts exactly as before — confirmed live: 15 consecutive headerless requests against a budget of 10 all returned `401`, while 10 wrong-token guesses against the same budget correctly saturated at the 11th with `429`.
  2. Amplification, introduced by PR #67: `civiccast/apps/portal-operator/src/queryClient.ts`'s shared `onError` handler invalidated `['staff-identity']` on ANY `401` from ANY query, and TanStack Query v5's `invalidateQueries` refetches active observers by default — so every sibling `401` on a signed-out screen fired a second, real network call to `/api/staff/auth/me`, roughly doubling staff-auth budget burn per screen. The handler now skips re-invalidating identity once identity already reflects the same failure (`status === 'error'`) or is already mid-refetch (`fetchStatus === 'fetching'`) — re-checked once per transition from "looked valid" to "looks dead," never again while already known dead. Pinned with a mounted `QueryObserver` test reproducing the exact live-repro shape (three sibling screens' worth of `401`s, one identity fetch).
  3. `civiccast/apps/portal-operator/src/api/client.ts` rewrote the backend's staff-auth `429` into "Too many unsuccessful sign-in attempts from this network" — false for a caller who never attempted a sign-in, and blaming an entire shared NAT/building for one connection's failed requests. Now reads "Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again" — states only what's verifiably true, invents no cause, and names the one actionable next step.
  4. **PR #67's own new defect**, whose commit message claimed its new setup-route accounting "matches the already-audited failures-only pattern `staff_auth_middleware` uses" — it did not. The staff pattern has an exact-token-match bypass (`token_matches_exactly`) so a correct token passes even against a saturated budget; `civiccast/installer/router.py`'s `_enforce_setup_rate_limit` called `limiter.saturated()` unconditionally before `/api/setup/login` or `/api/setup/recover` ever saw the credential, so a saturated budget rejected the CORRECT password or recovery code too — reproduced with `CIVICCAST_AUTH_RATE_LIMIT=3`: three wrong guesses, then the right password, returned `429` instead of `200`. New `civiccast.installer.station_state.login_credentials_correct` / `recovery_code_correct` (non-mutating peeks — the recovery-code peek loads its own throwaway state copy and never saves, so it cannot consume the one-time code) let `_enforce_setup_rate_limit` give both routes the same exact-match bypass the staff pattern already has, via a new `_setup_credential_in_body_is_correct` that reads the cached request body (`Request.json()`/`.body()` cache after the first read, so this never conflicts with FastAPI's own body parsing for the handler). Wrong guesses still saturate and stay blocked; confirmed live with a saturated 3-guess budget: a fourth wrong guess still returned `429`, and the correct password returned `200` regardless.

  **Threat-model note (OWNER DECISION):** this station's threat model is a single-box PEG station in a locked room with cleared personnel, where excessive security actively hurts the product more than it helps — every relaxation above only removes a false-positive lockout of a legitimate credential holder; a present-but-wrong credential (staff token, setup password, or recovery code) still counts against its budget exactly as before, and a caller with no correct credential at all gains nothing new. The rate limiter (`civiccast.auth.rate_limit.AuthRateLimiter`) remains process-local, in-memory state, so a future multi-worker deployment would reset each worker's budget independently — already true before this change, unchanged by it, and out of scope here; noted for the record. Recovery-code and token-list behavior were explicitly NOT touched (the 20-session cap stays practically unreachable at 8 single-use codes with no regeneration endpoint, and the admin password still never leaves the client).

  New coverage: `tests/auth/test_rate_limit.py` (signed-out page loads never trip the staff budget regardless of volume; the saturation pre-check never sweeps in a missing header; a present-but-wrong token still counts even interleaved with headerless requests; `/login` and `/recover` each survive a saturated budget with the correct credential while a still-wrong guess stays blocked), `tests/auth/test_staff_auth.py` (`verify_bearer_token(None)` raises the missing-credential subclass specifically; a present-but-malformed header does not), and `civiccast/apps/portal-operator/src/{api/client,queryClient}.test.ts` (the new 429 copy never says "sign-in attempt" or "network"; identity is fetched at most once across several sibling 401s on a dead session).

- **Watch-folder picker and config API had no path confinement at all, and the wrong role could reach it (adversarial audit of PR #69, findings 1-4, run against the real merged router with live requests, not a code read).** Finding 1 (CRITICAL): `browse_folders`'s `GET /api/staff/media-lifecycle/browse-folders` called `os.scandir(path)` on the raw query parameter with no containment whatsoever — the auditor walked from the endpoint's own no-path drive-root listing to `C:\Users` (200, real logged-in usernames) to `C:\Windows\System32` (200, full listing) to `\\localhost\C$` (200, the admin share, live over UNC/SMB) with zero prior knowledge of the box. Finding 3: `_validate_monitor_path` (used by `POST`/`PUT .../watch-folder-configs`) checked only "exists and is listable" — `C:\Windows\System32` and bare `C:\` both came back `201 Created`, meaning a watch folder could be silently misconfigured to auto-ingest from the OS system directory. Fix, `civiccast/schedule/media_lifecycle_router.py`: new raw-string path-shape validators (`_reject_unsafe_browse_path`, `_reject_unsafe_watch_folder_path`, shared helpers `_is_unc_or_device_path`/`_unc_share_is_admin_or_hidden`/`_is_drive_relative`/`_windows_local_segments`) reject the Win32 device-namespace prefix (`\\?\...`, `\\.\...`), drive-relative paths (`C:Windows`), bare drive roots (`C:\`), and a denylist of Windows system directories, deliberately implemented as string parsing rather than `pathlib`-based: verified empirically that `PureWindowsPath(r"\\host\share").is_absolute()` is `False` on this repo's own Python (3.13.5), so pathlib's own UNC/absolute detection cannot be trusted to reject one, on any Python version — and this suite's actual CI gate (`ci-test.yml`'s "Unit tests" job) runs on `ubuntu-latest`, where a `resolve()`-based check on a Windows-shaped string would silently no-op. The folder PICKER (local-disk-only by its own design) additionally rejects UNC entirely and refuses to list the bare `C:\Users` directory (account-name enumeration); the watch-folder `monitor_path` (which legitimately supports NAS/SMB per spec S7 open decision 5/D13) only rejects the Windows administrative/hidden shares (`\\host\C$`, `ADMIN$`, ...), not UNC as a class, and still allows a typed-in path under `C:\Users\...` for an operator's own profile folder. `browse_folders` additionally re-checks the RESOLVED path (post-symlink/junction) against the same denylist and containment when running on real Windows (`_enforce_local_drive_containment`) as defense-in-depth for a junction escape — a layer CI cannot itself exercise on its `ubuntu-latest` runner, stated plainly rather than claimed as covered. Finding 2: `browse-folders` and `scan-now` required only `_WRITE_ROLES` (`publish_operator` or `setup_admin`) even though they reach raw OS filesystem APIs, unlike every other `_WRITE_ROLES` route in the file (which only manipulates watch-folder/retention records) — narrowed to a new `_FS_ROLES = ("setup_admin",)`; `publish_operator` no longer passes. Finding 4: `WatchFolderWorker.scan_now` (`civiccast/schedule/watch_folder_worker.py`) had no lock, no idempotency guard, and no rate limit — five concurrent `scan-now` calls on one config produced 2 clean 200s and 3 unhandled database errors under the SQLite test harness (production is Postgres; the auditor stated plainly they had no instance to test against, so whether production 500s or merely double-scans is unconfirmed, but "no lock, no rejection" was confirmed either way). Fixed with a per-config, non-blocking `threading.Lock` (`_acquire_scan_lock`/`_release_scan_lock`) serializing `scan_now` against itself, other concurrent `scan_now` calls, AND the daemon's own `run_once` poll picking up the same config (`_scan_one_folder_guarded`); a second concurrent `scan_now` now raises the new `WatchFolderScanInProgressError`, mapped by the router to `409 Conflict`, while `run_once` coalesces (skips that config for the pass, picked back up next poll) rather than racing. New coverage: `tests/schedule/test_media_lifecycle_router.py`'s `TestUnsafePathRejection` (the exact attack strings from the audit — `C:\Users`, `C:\Windows\System32`, `\\localhost\C$`, `C:\`, drive-relative, `\\?\` prefix — plus a real-NAS-share and Users-profile-path allow-list regression) and updated role-gating tests; `tests/schedule/test_watch_folder_worker.py`'s `TestScanNowSerialization`, including a real 5-thread concurrency test instrumenting `_scan_one_folder` to prove observed concurrency never exceeds 1 (a naive "exactly one caller succeeds" assertion was tried first and correctly failed — a call arriving after an earlier one already finished is legitimately allowed to run its own scan; the real invariant is no overlap, not a fixed success count). **Also identified, not fixed here (out of this change's lane):** `civiccast/schedule/router.py`'s `upload_asset` (line ~706) catches `FfprobeNotFoundError` (line ~822) but not `FfprobeError` — confirmed by reading `civiccast/schedule/ingest.py`'s `run_ffprobe`, which raises `FfprobeError` on ffprobe's own non-zero exit or a JSON parse failure (exactly what garbage input like the auditor's 4KB `garbage.mp4` produces), and by the same function's OTHER caller in `router.py` (`~line 1042-1047`), which correctly catches both. Every existing test mocks `run_ffprobe` with a valid result, so this path has zero coverage; PR #69 did not touch `router.py` but put a prominent Upload button in front of it for the first time.

- **An `hls` egress sink was accepted by the config API with `200 OK` and crashed the channel the moment an operator started it — the product could not serve a live stream to residents at all.** Found live by an agent driving the real installed station with a real staff token: configuring an `hls` sink and issuing `start` threw `unknown sink kind: hls` inside `civiccast/egress/daemon.py`'s `_start`, logged only as `"Channel automation pass failed for government"` in `control_plane.log`. `EgressSinkKind` (`civiccast.egress.models`) has advertised `hls` since migration `0066_hls_sink_kind`, the config API validated and saved it fine, but `civiccast.egress.gst.bridge.sink_element_spec()` — the GStreamer engine's (the default engine's) config → element-graph mapper — had no `hls` branch and fell through to a bare `ValueError`, which none of `_start`'s `except` clauses (`ConfigInvalidError`/`SecretUnresolvedError`/`FfmpegNotFoundError`/`EgressError`) catch, so it propagated all the way out uncaught. Investigated rather than assumed: the shipped runtime does NOT carry an `hlssink`/`hlssink2`/`hlssink3`/`splitmuxsink` element at all (verified with `gst-inspect-1.0` against the real installed closure at `C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer\lib\gstreamer-1.0` — no `gsthls*.dll`, no `gstmultifile.dll` ships); the only HLS-shaped element present, gst-libav's `avmux_hls`, wrote **zero output files** in a live pipeline test (`avmux_hls ! filesink`, fed real video+audio, run to a clean `EOS`) — a known limitation of gst-libav's single-src-pad muxer wrapper, which cannot drive FFmpeg's own multi-file segment I/O. So a fix that just named a GStreamer element in `sink_element_spec()` would have looked done and still served nothing. Fix: new `civiccast.egress.hls_relay.HlsRelaySupervisor` (mirrors `TsRelaySupervisor`'s shape, wired into `EgressDaemon`/`PlayoutSupervisor` the same single way) supervises a real ffmpeg child that reads the GStreamer engine's ordinary MPEG-TS `udpsink` output over a loopback port and re-muxes it with FFmpeg's proven `-f hls` muxer via the EXISTING `civiccast.egress.sinks.HlsSink` — the same muxer, flags, and sliding-window (2s segments, 12s/6-segment window) the ffmpeg-concat engine already used, and `civiccast.stream.media_router`'s `/media/live/{channel_id}/...` route already served from unchanged (that router's docstring had described this exact `HlsSink`-writes/`media_router`-serves contract since before this fix — only the GStreamer engine's half was missing). `sink_element_spec()` also gets a genuine `hls` branch now (a `udpsink` at a port pure-function-derived from the sink's own configured directory, `hls_relay_uri_for`), so a bare call never raises even outside the relay's config rewrite. Proven end-to-end against the REAL installed runtime, not just unit tests: a live GStreamer pipeline (`videotestsrc`/`audiotestsrc` → `openh264enc`/`avenc_aac` → `mpegtsmux` → `udpsink`, the exact shape the daemon builds) piped into a real ffmpeg relay child running the exact args `HlsRelaySupervisor` constructs produced a real, rotating (`seg000000000-1.ts` at t≈3s → `seg000000002-8.ts` at t≈17s, old segments pruned) `playlist.m3u8` + `seg*.ts` on disk, independently confirmed playable by `ffprobe` (real H.264 640×360@30fps video + AAC audio streams). Also closed the same accept-then-crash SHAPE generally: `PUT /api/staff/egress/channels/{id}/config` now refuses a sink kind the ACTIVE engine cannot run with `422` and a message naming the supported kinds (engine-aware — `rtmp` remains genuinely unimplemented on the GStreamer engine, Stage 1 ships TS sinks only, but is still accepted when `CIVICCAST_EGRESS_ENGINE=ffmpeg-concat` is selected, since that engine's `RtmpSink` already works), instead of a config that later explodes deep inside a `start` pass. A failed channel-automation pass — or one command inside it — used to be visible ONLY as that one log line; it now raises through the existing alerting hub (`record_alert_condition`, new condition kind `channel-automation-failure`) with fire/dedupe/auto-clear semantics, and clears again once the channel completes a clean pass. Found and fixed a sibling bug in the same file while there: `_raise_egress_degraded_alert` (the existing GStreamer-degraded-to-FFmpeg operator alert) called `session_factory()` as if it returned a raw `Session` (`.commit()`/`.close()`), but production's `session_factory` (`civiccast.app._wire_stage_f_workers`'s `_session_factory`) is actually a `@contextmanager` callable — every real call has therefore always raised `AttributeError`, silently swallowed by the surrounding `except Exception`, meaning that alert has never once actually been recorded in production; fixed alongside (`with session_factory() as session:`), with a regression test — the PRE-EXISTING test for it used a fake session factory that shared the identical wrong assumption, so it never caught this. Also investigated the third live-reported symptom: after a channel's first couple of `start` commands processed, later commands (a `takeover`, then a `stop`) sat unprocessed for minutes with zero log activity. Root cause, confirmed by reading the code rather than inferred: `EgressStore.pop_pending_commands` marks the ENTIRE currently-pending batch for a channel consumed in one durable update BEFORE any of it runs, and `EgressDaemon.process_once`'s bare `for` loop meant one command raising (the `hls` crash above, or — worse — that SAME crash re-triggering on every later `takeover`/`reload` attempt for as long as the broken sink stayed configured, since those routes call back into `_start`) aborted the loop mid-batch, and every command queued alongside or after the crashing one in that batch was already marked consumed in the database — durably lost, never retried, with no trace of what happened to it. Fixed: `process_once` now isolates each command's processing (one failure can no longer take the rest of its batch down with it) and reports each failure through the same alert path above via a new `command_failure_hook`. Not fixed, and said plainly rather than papered over: the one command that actually crashes is still consumed at-most-once by design — the operator must reissue it, this change stops OTHER queued commands from being silently swept away with it. Also ruled out, not fixed: `process_once`'s `_poll_process`/`_service_backoff_relaunch` calls run BEFORE `pop_pending_commands`, so if either of those ever raised it would stall a channel's command draining without losing already-queued commands — a different and less severe failure shape; nothing in the live repro's evidence implicates that path, so it was not touched. New coverage: `tests/egress/test_hls_relay.py` (the relay supervisor's lifecycle/idempotency/config-rewrite/degraded-ffmpeg-absent behavior), additions to `tests/egress/test_gst_bridge.py` (the `hls` branch, the fallthrough error naming supported kinds), additions to `tests/egress/test_router.py` (config-time `422` rejection, engine-aware), `tests/egress/test_daemon_command_isolation.py` (the actual DEFECT D regression proof — a batch containing a raising command must still run every command after it), `tests/egress/test_automation_failure_alert.py` and additions to `tests/egress/test_automation_alert_hook.py` (the alert fire/clear contract, the wiring, and the `_raise_egress_degraded_alert` regression).
- **Provider setup, CDN cost, publish-surface, and day-one-alert copy read as if a technical admin was required and something was broken, when neither was true (field evidence, candidate #17).** Five distinct issues, one tester report: (1) Every provider card's setup steps said "Ask the technical admin to enter the keys" — on a one-person station the volunteer IS the admin. Rewrote `civiccast/installer/service.py`'s `build_provider_readiness_report()` and `_provider_item()` in first person ("Paste your own keys in yourself"), added a `manual_section` anchor per card, and reworded the not-set-up message from "is optional and not set up yet" to "is optional. Skip it for now if the station doesn't need it yet." The podcast card's undefined "Publish a local portal recording first" now explains what that means inline. (2) The Storage-and-viewing-estimate panel multiplied bandwidth by a hardcoded, unsourced `$0.005/GB` and printed it as a specific "$20.00 rough CDN estimate" — an invented number with no source. Per the owner's exact instruction, `CostForecastPanel` (`SetupScreen.tsx`) now shows "Varies by provider — Cloudflare R2 is free" and names Cloudflare R2's real, published, current $0-egress price as the one number it's willing to cite; GB storage/bandwidth math (a real function of the operator's own inputs) is unchanged. (3) The Publish Dashboard's optional "Cable file package" surface showed a red "failed: Cable file package was not created" even when it was simply never configured — indistinguishable from a real failure. `civiccast/cable/package.py` gained `CablePackageNotConfiguredError`, a subclass raised specifically for the "never turned on" case; `civiccast/publish/service.py` now maps it to the already-defined-but-unused `PublishSurfaceStateValue` of `"not_configured"` (message: "Cable file package is not set up (optional).") instead of `"failed"` — the dashboard's existing dot-color logic and `status-language.ts`'s existing `not_configured` → "Not set up yet" mapping already render this correctly with no further frontend change; a surface that WAS configured and genuinely failed (missing source file, missing caption sidecar) still reads "Failed". (4) `StationProfileScreen.tsx`'s Storage roots showed the Windows service account's raw profile path (`C:\Windows\System32\config\systemprofile\...`) with no explanation of why it isn't browsable and no way to act on it. Added a `CopyPathButton` per field, explanatory copy pointing at **Assets** as the supported way to find a recording without filesystem access, and a manual link; `civiccast/installer/service.py`'s `_backup_destination_path()` now rejects a WSL-style path (`...\mnt\c\...` or `/mnt/c/...`, matching the tester's observed `C:\mnt\c\CivicCastBackups`) with an actionable Windows-path error instead of silently accepting a location that would make "backup verified" a lie. (5) The System Health self-test panel and the Alerts screen both said "failed"/"Found a problem" in red, directly contradicting `civiccast/alerting/self_test.py`'s own deliberately-soft "did not pass" summary wording (comment tag `F-RC3-5`) shown one line below — a brand-new station's `readiness`/`backup_probe` checks are legitimately, correctly unmet on day one, not broken. `SELF_TEST_STATUS_LABEL`, the per-check pill label, and `alerts-format.ts`'s `CONDITION_LABEL['self-test-fail']` now match the backend's wording ("Did not pass yet" / "not yet" / "Automatic self-check did not pass"), and the self-test panel shows a one-line "finish Setup and Backup destination" hint specifically when those two checks are what's unmet.

- **"Report a beta issue" (operator console sidebar, First Setup's support link, resident portal) linked straight to a GitHub bug-report template, with no path for someone without a GitHub account (field evidence, candidate #17).** All three now route through the manual's new "Don't Have A GitHub Account?" section (`/help#report-without-github`) first, which explains the support-bundle-plus-forward path and, as a last resort, the maintainer email already published in `SECURITY.md` — GitHub is still offered, just no longer the only door. The identical link in `civiccast/apps/installer` (the Tauri setup wizard) was deliberately left untouched here to stay out of that surface's own active lane; same fix, same pattern, still needed there.

- **Live pre-flight could never pass for the bundled sample source, and "Run private rehearsal" was mislabeled and pointed at a dead dev port (field evidence, candidate #17, live on-air walkthrough).** Tester quotes: "the sample source has no server behind it. rtmp://127.0.0.1/live/civiccast-sample-rehearsal has NO listener... an actual ffmpeg push was refused"; "'Network reachable' and 'Recording storage' both say 'not probed; caller must run a probe before pre-flight' ... NO probe button to resolve them"; "'Run private rehearsal' is mislabeled. It is a config/readiness self-check, not a video rehearsal ... its resident_preview points at a DEV PORT http://127.0.0.1:5174 and is not_configured." Three fixes: **(1) sample source** — CivicCast ships no RTMP broker anywhere (grepped the whole repo, all three native-Windows lockfiles, and docs), so rather than fake network delivery, `civiccast.installer.service.build_sample_rehearsal_source_probe()` now routes the one sample-source id CivicCast itself creates through the same validated-local-file ffprobe check the installer's own `/rehearsal` endpoint already used privately, wired into `civiccast.app._resolve_preflight_evaluator` for every caller including the real "Run Meeting" pre-flight screen; every other, real source still gets the genuine network probe. **(2) self-probing** — the real bug was that `LiveRoomScreen.tsx` always submitted `null` for both the network and storage checks with no probe path anywhere; `PreflightEvaluator` now accepts `network_probe`/`storage_probe` callables (mirroring the existing `SourceProbe` pattern) and runs them itself when the caller submits `None`, backed by new `civiccast/live/network_probe.py` (bounded TCP connect to two well-known hosts) and `civiccast/live/storage_probe.py` (`shutil.disk_usage` on `CIVICCAST_UPLOAD_DIR`); the console no longer prints a raw reason code like `network.not_probed` — `PREFLIGHT_NEXT_STEP` in `types/live.ts` maps every code to a plain sentence with the action that clears it. **(3) naming + dev-port leak** — "Run private rehearsal" renamed to **"Check broadcast readiness"** throughout (button, heading, notice, error text) with a one-line clarifier that it doesn't play video; the 5174 default came from `civiccast.installer.service.build_resident_preview()` unconditionally falling back to the portal-public Vite dev-server port even in production, now fixed to mirror `operator_console_url()`'s existing packaged-vs-dev split (when `CIVICCAST_PUBLIC_PORTAL_DIST` is set, the preview defaults to the station's own real origin, `CIVICCAST_LOCAL_MEDIA_BASE_URL`, and reports `status="available"` instead of a dead dev URL falsely labeled `not_configured`). Separately investigated whether a station can go live end to end: RTMP is a dead end (no broker anywhere in the product); SRT is fully viable with zero new dependencies and was proven live on the Halo candidate box (a real `srtsrc mode=listener` pipeline receiving a genuine 720p30 h264/aac push from bundled ffmpeg, 569 buffers/618,332 bytes, clean PLAYING→EOS) — the remaining gap for going live is orchestration, not transport. Did not complete a full portal/HLS/captions proof: the box's `DATABASE_URL` is Administrators-only in the registry, and minting a staff token would have required escalating to a real production DB credential — declined per credential-sensitive-action policy.

- **CPU-only AI summaries never completed — a fixed 120s control-plane timeout discarded work Ollama had already finished, the advertised model default and its latency claim were both wrong for CPU-only hardware, and there was no UI path to even trigger generation (field evidence, candidate #17, AMD Ryzen 7 8745HS/32GB, CPU-only inference).** `POST /api/staff/summaries/generate` with `gemma4-12b-ollama` returned 503 after 120.6s cold and 503 after 120.2s warm (model already loaded) — Ollama's own `/api/generate` succeeded server-side (~794-840 tokens); the control plane's fixed 120s socket timeout discarded a completion Ollama had already computed. The AI Models screen advertised "≈4.2 s typical" for `gemma4-12b … default on >=16GB boxes`; measured on the same hardware class it took 366s to complete once, then two more attempts failed outright (CPU buffer allocation failure, a crashed `llama-server` process) — roughly 30x wrong, then a hard failure the number never warned about. Summary review had zero UI path to trigger generation at all (the empty state said "Next step: generate a summary" with no button anywhere), so approve/reject and the PDF/A-3B signed-record export were unreachable. Fixes: **model default** (`ai_models/models.py::detect_summary_model_default`) now gates on a real NVML-detected GPU, not RAM alone — a CPU-only box gets `gemma4:e4b` regardless of RAM, and 12B is only the default with a GPU + >=16GB RAM, threaded through the installer first-run seed, both provisioning-plan surfaces, and `civiccast doctor`. **Timeout** (`ai_runtime/ollama_client.py`): a live `/api/generate` call gets a 600s socket budget, separate from the 120s budget kept for cheap `/api/tags`/`/api/version` daemon-liveness checks. **Async job** (`summary/job.py`, `summary/persistence.py`, migration `0081_summary_generation_jobs`): summary generation now runs as a durable queued job — the same `pending`/`running`/`complete`/`failed` pattern the offline caption job (K3) already established — with `POST`/`GET /api/staff/summaries/jobs`, `GET .../{id}`, `POST .../{id}/retry`; the synchronous `POST /generate` is unchanged. **UI**: a real `GenerateSummaryPanel` on the asset detail screen, next to the offline caption job panel, with visible pending/running/complete/failed state, honest failure messages, and a Retry action. **Honest latency** (`ai-models-format.ts::tierLatencyLabel`, `catalog.py`): on-box CPU-bound tiers now render a measured, CPU-only-caveated range instead of a bare "≈X s typical" figure — also fixed captions' `whisper-medium` claim ("≈500 ms typical" vs measured ~3.3x real time, ~70x wrong). **Translation**: flagged as not connected to any output in the AI Models banner and catalog notes — the picker exists but no caller supplies a translation target, so nothing is ever actually translated; decided to be honest about this rather than build new output wiring under this task's scope. Measured before/after on the CPU-only 32GB reference station: `gemma4:e4b` 127.8s cold / 93.8s warm, completed every attempt; `gemma4:12b` 366.2s cold (completed once), then 2 more attempts failed outright.
- **`POST /api/public/contribute/uploads` returned the internal absolute server filesystem path as `upload_ref` to an anonymous public caller** (confirmed in code and independently reported by a field tester: `"COSMETIC/PRIVACY -- path leak. The public upload response returns the internal absolute path C:\Windows\System32\config\systemprofile\...\contributor-uploads\council-speech.mp4 to the resident."`). Beyond revealing the service account's profile layout, tracing what `upload_ref` was actually used for turned up a more serious consequence of the same defect: the stored filename was the contributor's own sanitized name plus a numeric collision counter (`council-speech.mp4`, `council-speech-2.mp4`) -- guessable for anything with a predictable name (this is a civic broadcast platform; meeting recordings have exactly that) -- and `sha256` is optional in the public submission payload, so a second anonymous caller who guessed or otherwise learned another contributor's `upload_ref` could attach that stranger's pending upload to their own submission with no proof of anything. Fix: `_unique_upload_path` (`civiccast/contribute/router.py`) now names the on-disk file with a `uuid4` hex token instead of the contributor's filename, and `upload_contributor_media`'s response returns only that opaque token (`destination.name`, no directory component) as `upload_ref` -- the contributor's real filename is still returned separately in `SubmissionMediaReference.filename` for display. A new `civiccast.contribute.store.resolve_contributor_upload_path` is the single place that ever turns the opaque token back into a real path, joined onto `default_contributor_upload_dir()` -- no second storage/lookup mechanism, the contributor upload directory the store already owns IS the store. `Path.__truediv__` leaves an anchored (absolute) right-hand operand unchanged, so a submission recorded before this fix -- when `upload_ref` was still a full absolute path -- resolves to the exact same file it always did with no data migration. `_verified_media_reference`'s existing containment check (`resolved.relative_to(upload_dir)`) is unchanged and still runs on every submission, so a forged or path-traversal-style ref is rejected exactly as before. Also closed the same class of leak in three public-router error paths that echoed a raw `OSError`/`ContributorStoreError` string (which can carry a filesystem path) straight into an anonymous caller's response `detail` -- the upload directory mkdir/write failure and the submission/store dependency's persistence failure now log the real exception server-side and return a generic, safe detail. Two-step public flow (`POST /uploads` then `POST /submissions`) verified end to end with the real opaque ref (`tests/contribute/test_router.py::test_public_upload_then_submit_round_trip_succeeds_with_the_opaque_ref`); the portal's public submit form needed no change -- it already treats the whole media object as an opaque pass-through between the two calls.

- **Live-takeover ignored the operator's configured live source and always fell back to a hardcoded, nothing-listening `rtmp://127.0.0.1/live/{channel_id}` placeholder (defect 1 from the live-path investigation, native beta candidate #17).** `civiccast.live.relay.build_ingest_plan()`'s `local_default` never read the `LiveSource` table at all, so an operator who added a real camera/encoder source in Run Meeting had no way to make live-takeover (`civiccast.egress.takeover_service.TakeoverService.take` → `build_live_takeover_source_plan`, which selects from exactly this plan's `local_default`/`relay_paths`) actually use it — the two systems never agreed on what "the channel's source" was. Proved live on the Halo candidate box: a `LiveRelayConfig` cloud-relay/`return_playback_url` workaround was the *only* way to get an SRT endpoint into a takeover; the `LiveSource` row Run Meeting and pre-flight already use was completely invisible to the takeover path. Fix: `build_ingest_plan()` now also takes the channel's real `LiveSource` rows and turns each into a selectable, ready `LiveIngestPath` (`_source_path`), ranked ahead of the legacy default exactly like a ready relay config already was; `GET /api/staff/live/ingest-plan` (`civiccast/live/router.py`) fetches those rows via the existing `LiveSourceStore` and passes them through. Per explicit owner direction, did **not** ship the `LiveRelayConfig` cloud-relay/`return_playback_url` workaround as the real path — that field means cloud-relay pull-back, not a local encoder, and using it that way would be a fake operator-facing path that looks legitimate and isn't; RTMP stays impossible without new infrastructure (no broker anywhere in this product), so the honest fix is: configure a real source, and live-takeover can now see it. Also stops the legacy `local_default` from claiming `enabled=True`/`health_state=ready` for an address nothing has ever listened on — it stays present only so the plan always has a `recommended_path_id` when a station has configured nothing yet, and now says so plainly (`enabled=False`, `health_state="not_configured"`, honest `operator_action`). Scope: this fixes the `civiccast/live/` side of the split only — getting a channel to actually serve real HLS also needs the unimplemented `"hls"` sink kind in `civiccast/egress/gst/bridge.py` (`sink_element_spec` has no `hls` branch and crashes with `ValueError: unknown sink kind: hls`) and a symptom where the egress command queue stopped draining after the first couple of commands (observed, not diagnosed) — both under separate investigation in `civiccast/egress/`, not touched here.

- **Cable Commissioning Screen 8 reported "GStreamer runtime not detected" and DeckLink "FAIL" on a clean station whose bundled runtime was fully installed (candidate #17), bricking the whole commissioning wizard.** Confirmed live by the tester: `C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer\bin\gst-inspect-1.0.exe` was present with its DLLs and plugins, but Screen 8's probe (`civiccast.platform.station_box_profile.probe_engine_readiness`, via `_default_gst_inspect_runner`/`_default_device_monitor_runner`) only ever did `shutil.which("gst-inspect-1.0")` — a bare PATH lookup. The control-plane service runs as LocalSystem with the stock, installer-untouched PATH (`civiccast.native.supervisor.install_layout`'s own docstring), which never carries the bundled runtime's `bin` directory, so the probe reported "not detected" against a fully installed runtime. The SAME PATH lookup also produces a FALSE PASS on a developer's own machine that happens to have a separate, user-installed GStreamer on PATH — reproduced live on Halo, where `shutil.which("gst-inspect-1.0")` resolved to `C:\Users\scott\AppData\Local\Programs\gstreamer\1.0\msvc_x86_64\bin\gst-inspect-1.0.exe`, NOT the product's own shipped runtime; a passing probe there was silently checking the wrong install. With GStreamer AND DeckLink both `FAIL`, Screen 8 offered no "Continue anyway" (only warnings get that), so Screens 9-11 (channel output setup, output proof, report) were completely unreachable — no channel could ever be configured through the wizard, and the "cable file package" publish artifact stayed permanently red because commissioning could never complete. This is NOT the same root cause as Phase 2's dead live engine, despite an initial field report linking the two: `civiccast.egress.gst.engine` (the real playout worker) already bootstraps the bundled runtime independently at import time via `civiccast.native.gstreamer_runtime.bootstrap_installed_gstreamer_runtime()` — the exact absolute-path/PATH-prepend mechanism this fix gives the commissioning probe — so egress never depended on the buggy PATH-only probe this PR fixes. The live-owning agent independently root-caused the dead live engine to a separate, concrete defect (no RTMP listener ships anywhere in the product), unrelated to this commissioning-detection bug. Two things stay worth a follow-up look in this area, reported rather than fixed here since `civiccast/egress/` is out of this change's lane: (1) `civiccast/egress/gst/engine.py`'s `bootstrap_installed_gstreamer_runtime()` call discards its `bool` return value — a bundled-runtime bootstrap failure (e.g. the child process never received `CIVICCAST_GSTREAMER_RUNTIME_ROOT`) is currently silent, falling through to an unguarded `import gi` that would import whatever GStreamer happens to be ambiently resolvable rather than the verified bundled one, or fail with a bare `ImportError` carrying no diagnostic about why the bootstrap didn't run; (2) an operator-facing repair action already exists (`POST /api/staff/repair-gstreamer` → `civiccast.native.gstreamer_repair.trigger_gstreamer_repair`, wired to `GstreamerRepairPanel` on the System Health screen) but Screen 8's `gstreamer_engine`/`decklink_sdi` checks only describe it in `next_step` text — a future pass could offer it as a one-click action on Screen 8 itself, the same way System Health already does. Fix, all in `civiccast.platform.station_box_profile`: new `_resolve_bundled_gst_tool` resolves `gst-inspect-1.0.exe`/`gst-device-monitor-1.0.exe` by ABSOLUTE path against the installed layout (`civiccast.native.supervisor.install_layout.resolve_install_root` → `<install_root>/runtime/dependencies/gstreamer/bin/...`, reusing `civiccast.native.gstreamer_runtime.installed_gstreamer_environment` for `PATH`/`GST_PLUGIN_PATH`/`GI_TYPELIB_PATH` — the SAME resolution the real playout engine already uses via `station_runtime.load_native_station_environment`, so Screen 8 now agrees with engine selection instead of running a different, PATH-only test), never a bare PATH lookup, and only falls back to PATH when no bundled closure resolves (dev/CI/system installs). Proven end-to-end on Halo by monkeypatching `resolve_install_root` at the real bundled tree: the probe correctly resolves `GStreamer 1.28.5` from the bundled path with `decklinkvideosink`/`mpegtsmux` found, and separately still reports `system-path` (not `bundled`) when only the dev GStreamer on PATH is reachable. New `EngineReadiness.runtime_source` (`"bundled" | "system-path" | "unavailable"`) makes this honest on the wire — Screen 8's `gstreamer_engine` detail now names WHICH install a passing (or failing) probe actually found, and the "not detected" `next_step` now points at the installer's repair action instead of telling the operator to install something already shipped. Also fixed: DeckLink/BMD SDK absence on a `peg-cable` station now reports `warning` ("Not installed (optional — only required for a channel that outputs via SDI)") instead of a hard `fail` — `validate_channel_commissioning_setup` already treats an SDI device as a per-channel opt-in, not a station-wide requirement, so a streaming-only/IP-only station with no capture card was being hard-blocked from a wizard step it never needed; TSDuck's existing "Not installed" warning is now explicitly labeled "(optional)" too. `civiccast.cli._doctor_check_captions` (`civiccast doctor`) gets the same bundled-first resolution so it agrees with Screen 8 instead of independently reporting "not on PATH" under the same LocalSystem service context. Not touched: the real GStreamer engine-selection/egress path (`civiccast.egress.engine_select`, `civiccast.native.station_runtime._resolve_gstreamer_egress_environment`) was already correct — it resolves the bundled closure by absolute path and was never PATH-dependent, so this was purely a commissioning-detection bug, not an engine-startup bug; the missing-live-engine symptom traces to the wizard being unable to complete, not to the engine itself failing to start. New coverage: `tests/platform/test_station_box_profile.py`'s `TestBundledGstResolution`/`TestDefaultRunnerResolutionOrder` (bundled-vs-PATH resolution order, partial-closure fail-closed, a tool absent from the closure, and the exact field-evidence "service-like environment, no bundle, nothing on PATH" case failing closed honestly) and `tests/installer/test_commissioning.py`'s new decklink/tsduck-optional and `runtime_source`-reporting tests. Regenerated `docs/openapi.json`/`api.generated.ts`/`docs/API-REFERENCE.md` for the new `runtime_source` field.

- **A person holding only the printed recovery kit could not sign in — no password was ever printed, recovering rotated the shared admin token and silently logged out every other open session, and per-network rate limiting could lock the station's only admin out of their own console (field evidence, candidate #17, real board-meeting test, non-technical tester, printed recovery kit only).** Tester quotes: "The one-page recovery card has the username (proofadmin) and 8 recovery codes but NO password. 'Admin sign-in' needs a password nobody gave them; the only other option, 'Use recovery code', BURNS one of the 8 codes and forces setting a new password"; "recovery rotates the single 'station-first-admin' operator token. Anyone already signed in ... instantly gets 'Invalid staff bearer token' ... OBSERVED LIVE during this test"; "a few failed password tries ... trip 'Too many unsuccessful sign-in attempts from this network. Wait 51 seconds, then try again.'" Three fixes: **(A) closed the credential gap** — the printed/saved recovery kit (`RecoveryKitPanel` in `SetupScreen.tsx`) now includes the admin password chosen during setup, clearly separated from the 8 emergency-only recovery codes; the password is never round-tripped through the server (it's already in the setup form's React state when the kit renders), and the backend still only ever sees/stores its PBKDF2 hash. **(B) recovery no longer logs out other sessions** — `operator_console` in station-state now holds a bounded list of concurrently valid sessions (`operator_console.tokens`, capped at `_MAX_OPERATOR_SESSIONS`=20) instead of a single slot; ordinary login still **replaces** the list, recovery now **appends** instead, since a forgotten password is not evidence any other live session is compromised. A pre-fix single-token station-state file still verifies via a documented backward-compat reader. Also fixed the error surface: `main.tsx`'s `QueryClient` (factored into `queryClient.ts` for testability) now invalidates the `staff-identity` query the instant any screen query gets a 401, so the existing sign-in redirect fires instead of a raw "Invalid staff bearer token" string sitting frozen on-screen. **(C) rate limiting no longer bricks the single admin** — `/api/setup/login` and `/api/setup/recover` now use the same failures-only accounting already shipped for `/api/staff/*` (`_record_setup_auth_failure`): only a wrong password or bad recovery code burns the per-IP-per-route budget, never a state read or a correct attempt; every other setup route keeps its original per-request budget. The 429 detail now states both the wait and a way forward: "Too many sign-in attempts from this station. Wait N seconds, then try again with the correct password, or use a printed recovery code." None of this weakens brute-force protection — the wrong-guess budget per window is unchanged; only requests that were never guesses stop being penalized. Owner-authorized relaxation for single-box PEG stations in locked, cleared-personnel rooms (comment-documented in place, `grep "OWNER DECISION 2026-08-29"` in `station_state.py` and `router.py`).

- **Accepted contributor media never became a real, airable asset — acceptance recorded a fake attestation, no library asset was ever created, and "Send to schedule" returned `schedule_item_id: null` while the resident was told the opposite (field evidence, candidate #17, verbatim).** "BLOCKER — accepted contributor content is never airable. Accept -> state 'accepted', broken-media gate 'passed'. Then 'Send to schedule' -> state 'scheduled' ... BUT schedule_item_id: null. NO library asset is ever created ... and NO actual schedule item appears ... The resident is nonetheless told 'Your program has been handed off to the schedule.'" Also: "Broken-media gate is an attestation, not a probe. On accept, the gate records 'Operator accepted the media gate from the review queue.' — an operator attestation, not an automated media check." Three fixes: **(A) acceptance now produces something airable** — Accept runs the exact ffprobe → validate → hash → thumbnail → `AssetStore.ingest_upload` pipeline the staff `/assets/upload` endpoint and the watch-folder worker already use (`civiccast.schedule.ingest` + `civiccast.schedule.store`, never a parallel pipeline); the contributor's file becomes a real, trimmable/packageable/publishable `Asset` row. "Send to schedule" creates a real `civiccast.schedule_items` row via `PostgresScheduleStore.create` and returns its real id — `schedule_item_id` can no longer come back null on success; scheduling before a real asset exists is refused with 409 naming the action still required. **(B) no more false promise** — the public status message for `scheduled` now reads "Your program has a real spot on the schedule and will air automatically," true at the moment it's shown since a real schedule item exists by then; the operator UI no longer sends a fabricated "passed" media-gate attestation on Accept. **(C) the broken-media gate is now a real probe** — Accept runs the actual ffprobe probe by default and records the true verdict; a corrupt or unsupported file is rejected with HTTP 422 before any state change. An explicit operator override (`broken_media_gate.state == "override_accepted"`) still ingests the file but keeps its own honest label, never silently rewritten into a fabricated "passed". Verified end to end on a real run: `accept` → real `asset_id` (`contributor-community-spotlight-downtown-arts-870db7ac`), `broken_media_gate: passed` with the real ffprobe verdict text; `schedule` → real `schedule_item_id`, visible via `GET /api/staff/schedule/{id}`. New tests cover accept-without-ingest refused, schedule-without-accept refused, schedule-without-a-real-item-id refused, a deliberately corrupt file caught by the real probe (422, submission stays `submitted`), and the explicit-override path, including a main end-to-end test against a real ffmpeg-generated clip, not a mock.

- **Operator console infinite setup loop after a successful install (candidate #16, 4eca729): clicking "Open operator console" opened First Setup's own "not set up yet" dead end, whose advice was to click the exact button just clicked.** Reproduced twice in one day on two different machines, station healthy both times (health/portal/operator all 200, postinstall SUCCESS). Root cause: the installer-handoff setup nonce lived in an ACL-hardened `HKLM\SOFTWARE\CivicCast\Native\SetupNonce` registry key (SYSTEM + Administrators only), but the Tauri setup wizard that builds the button's URL and writes `installer-state.json` ships `asInvoker` (non-elevated) by design — its own registry read always failed, and `write_installer_state`'s `preserved_operator_console_url()` bailed out before ever reaching the "no cache, but we have a live nonce" branch even on the rare occasions a nonce WAS available — so the very first `operator_console_url` a fresh install ever wrote was the bare, nonce-less constant, and every later write only preserved that same nonce-less value. OWNER DECISION: rather than patch the handoff (four separate field failures on this mechanism in two days — nonce unreadable across the elevated-installer/normal-user split, the W-2 recovery code file never written, "Get a new code" silently no-op'ing, the elevated `--civiccast-restore-setup-handoff` CLI printing nothing), retire it entirely. The control plane binds `127.0.0.1` only (verified live via `netstat`: `TCP 127.0.0.1:8000 LISTENING`, nothing on `0.0.0.0`), so `/api/setup/*` is already unreachable from the network by construction — the nonce was guarding a door inside a room the network cannot enter. First setup is now admitted by loopback peer address alone (`civiccast.installer.router._require_local_setup_request`, decided from the ASGI transport's own `request.client.host`, never a spoofable header); a configured station still refuses a second first-admin attempt with `409` (`civiccast.installer.station_state.complete_first_admin_setup`, unchanged). Removed: `civiccast.native.setup_nonce`, the `civiccast runtime setup-handoff` CLI, the `--civiccast-restore-setup-handoff` elevated-recovery flow, the W-2 in-product "I lost my setup link" / "Get a new code" recovery-code UI and its backend (`civiccast.installer.handoff_recovery`), and every nonce-URL function in the Rust installer (`resolved_operator_console_url`, `preserved_operator_console_url`, `native_setup_nonce_from_registry`, and siblings). The "Open operator console" button now always opens the plain, fixed console URL, and a caller reached from off the station gets an honest refusal ("First setup can only be done from the station computer itself") instead of circular button-click advice.

- **GUI acquisition screen showed "Local AI model" stuck on "Waiting" for
  15+ minutes on a real board-demo machine (candidate #16, 4eca729) even
  though station activation had already installed it and PR #56's
  `merged_ollama_model_store_root` fix was present and structurally
  correct.** Root-caused by re-deriving both sides of PR #56's path match
  from the actual code (`native_activation::compose_ollama_model_store`
  writes to `<install_root>\models\ollama\...`;
  `acquisition_catalog::merged_ollama_model_store_root(roots.staged)`
  resolves to the SAME path, since `roots.staged` is
  `acquisition_installer_directory()` = `current_exe().parent()`, and
  `--civiccast-activate-station --install-root "$INSTDIR"` passes that
  same directory as `install_root` -- so the original 9d4477b path miss is
  confirmed fixed, not the cause here) — this is a DIFFERENT defect. The
  real cause: `main.rs`'s `run_acquisition_components` is a strictly
  sequential, single-threaded driver over a FIXED list
  (`acquisition_catalog::PRODUCTION_CATALOG_IDS`: `app_runtime,
  server_binaries, captions_medium, captions_large, cuda_runtime,
  local_ai_model`) with no hardware- or selection-based gating at all
  (`start_acquisition` takes no arguments; `captions_large` and
  `cuda_runtime` are both `required: false` on the frontend but always run
  on the backend). On a station with poor or no internet, whichever
  optional entry ahead of `local_ai_model` was not staged offline could sit
  downloading for hours (`component_acquisition.rs`'s per-request timeout
  is `6 * 60 * 60` seconds) before the driver ever reached
  `local_ai_model` — even though that component's own offline-first check
  would have resolved in milliseconds. Fix: a `prescan_locally_satisfied_components`
  pass now runs every catalog component's existing no-network local-check
  (factored out as `component_acquisition::locally_verified_pinned_path`
  and `main.rs`'s `locally_verified_pack_path`, reused — never duplicated
  — by the real sequential driver) up front, before the sequential loop
  starts, and persists `found_locally` immediately for anything already
  satisfied — decoupling an already-installed component's GUI state from
  an unrelated, still-transferring one. No hash or signature check was
  weakened; the sequential loop still performs its own full run over every
  component afterward. Two new tests: `acquisition_catalog.rs`'s
  `local_ai_model_merged_store_candidate_names_a_file_compose_ollama_model_store_actually_writes`
  runs the REAL `compose_ollama_model_store` writer against a synthetic
  staged tree and asserts the catalog's own merged-store candidate names a
  file it actually wrote (mutation-tested: fails when the two path
  functions are made to disagree); `main.rs`'s
  `locally_satisfied_progress_rows_finds_a_satisfied_component_behind_an_unsatisfied_one`
  proves an already-satisfied component is recognized regardless of an
  earlier, unsatisfied component's state.

- **A station activated on the mandatory floor caption tier crash-looped
  forever after the operator acquired the OPTIONAL large-v3 tier through the
  post-install acquisition wizard, and the supervisor's own log never said
  why (field evidence, candidate 4eca729, 2026-08-29).** GUI install
  completed clean (health checks 200, `install-progress.log` SUCCESS); the
  coordinator then left the post-install acquisition wizard open and it
  genuinely downloaded the optional `captions-large-v3` component into
  `%PROGRAMDATA%\CivicCast\components\captions-large-v3`. From that point on,
  `CivicCastSupervisor` crash-restarted every ~33s ("terminated unexpectedly.
  It has done this 371 time(s)"); the Windows Event Log carried the real
  reason, `NativeStationConfigurationError: Native station activation
  self-test receipt does not match this distribution`, but `supervisor.log`
  held only the unconditional "supervisor logging initialized" line and
  nothing else. Root cause, traced end to end:
  `station_runtime._resolve_caption_tier` searches BOTH the install root and
  the non-elevated acquisition root for a staged caption tier and always
  prefers the HIGHEST one found (by design — large-v3 is the better engine);
  once the wizard staged large-v3 in the acquisition root, the runtime
  correctly resolved `tier_id="large-v3"` on the station's next start, but
  `activation-self-test.json` is written EXACTLY ONCE, by the elevated
  `d4-activate-station` NSIS step, and describes whichever tier was staged at
  THAT moment — almost always the floor tier alone, since large-v3 is an
  OPTIONAL component the non-elevated GUI can acquire later into a
  completely different root the elevated installer never touches (chain H1).
  `_validate_activation_receipt` was therefore, correctly, refusing a
  floor-tier receipt against a large-v3 identity every single time — the
  check itself was never wrong; nothing in the codebase ever produced a
  receipt for the tier the operator had just legitimately added. (No
  component was ever wiped or overwritten: `%PROGRAMDATA%\CivicCast\
  components` has never held anything besides `captions-large-v3` by
  design — nothing else is ever written there.) Fixed on both sides of the
  contract, without weakening the check: (1) `main.rs` gained
  `finalize_captions_large_acquisition`, run once the wizard's per-file
  pinned-hash verification for `captions_large` completes — it re-verifies
  the mandatory floor tier's own staged jfk.wav self-test fixture against
  its pinned identity, runs a REAL faster-whisper inference against the
  just-downloaded large-v3 model with the station's own embedded
  interpreter (the same live proof the elevated install path already gives
  the mandatory tiers), and on success writes a large-v3-only addendum
  receipt into the acquisition root (never touching `station-set.json` or
  the primary `activation-self-test.json` at the install root, so every
  already-activated component stays exactly as it was); an idempotency
  fast-path skips the ~300s inference re-run when a matching receipt is
  already on disk. (2) `station_runtime.load_native_station_environment`
  now reads the activation receipt from the SAME root the resolved tier's
  own model was actually found in (reusing the existing `_tier_base_root`
  two-root search that already resolves the model itself), instead of
  unconditionally reading it from the install root — a floor-only station is
  completely unaffected (its receipt root is always the install root, exactly
  as before). Separately, `service_host.SvcDoRun` now logs the real exception
  type and detail to `supervisor.log` via the new
  `civiccast.native.supervisor.start_failure_marker` BEFORE re-raising
  (behavior is otherwise unchanged: still fails loud, still exits, still lets
  the SCM's own restart policy decide what happens next), and once the SAME
  condition has recurred 3 times in a row it writes an operator-readable
  `STATION-START-FAILED.md` marker alongside `install-progress.log`, cleared
  automatically the moment a start actually succeeds again — so a crash loop
  is never silent even to an operator who never checks the Windows Event Log.
  11 new tests: 2 in `test_station_runtime.py` (the fail-closed floor with no
  addendum receipt present anywhere, and the regression proof once one is),
  7 in the new `test_start_failure_marker.py` (pure counter/marker decision
  logic), 2 in `test_supervisor_service_win.py` (the real `SvcDoRun`-driven
  crash-loop-then-marker sequence, and marker/counter clearing on a clean
  start); plus 5 new Rust tests driving the real addendum receipt writer
  directly (byte-for-byte identity match against the runtime's own pinned
  expectations, and proof that writing it never touches the primary receipt
  or any other already-activated component).

- **Gate A's harness lost the ability to log in the moment the setup nonce was retired, and the operator card still warned about an "unsigned app" screen the signed installer never shows (two fixes from the candidate #17 gate run and live install).** (1) Candidate #17's first gate run FAILed `t3_loop`, `captions`, and `t4_engine` while `install`, `activation`, `runtime`, `t2_render`, and `t5_soak` all passed — the shape of a harness fault, not a product regression. Cause: `In-Sandbox-Report.ps1`'s T3 content loop read the installer setup nonce from `HKLM\SOFTWARE\CivicCast\Native\SetupNonce` and sent it as `X-CivicCast-Setup-Nonce` when creating the first admin; PR #60 retired that mechanism entirely (first setup is now admitted by loopback peer address), so the read threw, no bearer token was ever obtained, and every downstream content check failed for want of a login while the station itself was healthy the whole time (health/operator/portal all 200, soak 4/4 beats). Fix: the harness runs ON the station, so it is already the trusted caller — the nonce read and header are removed, `first-admin` is posted plain, and the stale comments describing the retired flow are corrected. `tests/gate_a`: 109 passed. (2) The operator card's first instruction told the operator to expect the blue "Windows protected your PC" screen; the shipped installer is validly Authenticode-signed and timestamped (`CN=Scott Converse`, verified with `Get-AuthenticodeSignature` on the kit), so that screen never appears, and leading with it implies unsigned software. Step 2 now describes the prompt that does appear (elevation) and names the verified publisher; SmartScreen moves to troubleshooting with an explicit "stop if the publisher is anyone else" instruction.

- **Setup-handoff recovery: an unhandled write failure after the challenge
  directory was already hardened could crash the request instead of ever
  reaching the "no 200 without a real file" contract, and "Get a new code"
  gave no visible feedback at all (field session 2026-08-28, candidate
  9d4477b).** On the First Setup page's "restore setup handoff" panel,
  clicking "Get a new code" produced no visible change on screen, and a
  separate live report on the same station found the countdown-carrying
  `/api/setup/handoff-recovery/start` success response with no
  `code.txt` on disk to back it up. Reading
  `civiccast.installer.handoff_recovery.start_recovery` end to end and
  reproducing it locally against a REAL (non-mocked) `win32security` ACL
  call found the actual defect: `start_recovery` hardens the challenge
  directory to SYSTEM+Administrators-only, THEN writes `code.txt`/
  `state.json` into it — so a caller whose token does not carry the
  `SY`/`BA` SIDs it just granted the directory (the *default* Windows
  token state for an administrator account running de-elevated; UAC only
  attaches the Administrators group to a genuinely elevated process) gets
  a bare `PermissionError` writing the code file it just locked itself out
  of. That exception was never caught anywhere — not in
  `handoff_recovery.py` (only `HandoffRecoveryError` was), not in
  `civiccast.installer.router`'s `public_handoff_recovery_start` — so it
  reached the HTTP layer as an unhandled 500 with no cleanup, rather than
  the module's own fail-loud `HandoffRecoveryError`/503 contract. No code
  path in this codebase can turn a real write/ACL failure into a
  fabricated 200 (every return from `start_recovery` already required the
  writes to have succeeded), so the field station's specific "live
  countdown, missing file" combination could not be conclusively
  reproduced from source alone; it is consistent with this exact
  uncaught-exception class landing on a run where the privilege assumption
  did not hold, or with the on-machine check running under different
  privileges than the control-plane process (a non-elevated `Test-Path`
  against a SYSTEM+Administrators-only directory throws Access Denied,
  which is a well-known false-negative case for that cmdlet) — reported as
  an open question rather than settled, per this repo's own
  claims-of-absence discipline. Fixed regardless: the whole
  mkdir/ACL/write sequence in `start_recovery` is now one fail-loud unit —
  ANY exception (mkdir, ACL, either write, or a new read-back-what-was-
  just-written verification) removes any file that attempt created and
  raises `HandoffRecoveryError`, so a caller of this function gets EITHER
  a fully written, fully hardened challenge, or a clean exception and no
  trace of a half-issued one; there is no partial-success return. Frontend
  fix in the same pass: `SetupScreen.tsx`'s `HandoffRecoveryPanel` now
  shows a visible pending label on both "I lost my setup link" and "Get a
  new code" while the request is in flight, an explicit
  `role="status"` confirmation on success naming the write time and, for a
  regenerate specifically, that the old code no longer works, and disables
  the stale code input while a new one is being issued — matching the
  page's existing "never a dead control" standard (see the W-2 doc
  comment above `HandoffRecoveryPanel`). Also flagged, not fixed here (out
  of scope — `civiccast/apps/installer/` is owned by a concurrent
  session): `--civiccast-restore-setup-handoff`'s recovery pass already
  prints an explicit result on every branch, but the installer binary
  compiles as a Windows GUI-subsystem executable in release builds
  (`#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]`),
  so none of that output is visible when run from an existing terminal —
  a separate, precisely diagnosed follow-up. 3 new tests in
  `tests/installer/test_handoff_recovery.py` (a write failure after
  successful hardening raises `HandoffRecoveryError` and leaves no partial
  state; a failed read-back of the just-written code also fails loud), 3
  new tests in `src/screens/SetupScreenNoNonce.test.tsx` (pending label on
  first issue, pending label + reset countdown + explicit regenerate
  confirmation on "Get a new code", visible error on a failed regenerate).
- **GUI installer re-downloaded the 7GB local AI model even after offline-kit
  activation already installed it; "Open installer log" was a no-op; no
  shortcut existed anywhere back to the running station; and the setup CLI's
  handoff-recovery flag printed nothing from a terminal (four related field
  findings, 2026-08-28, candidate 9d4477b, USB-kit GUI installer run).**
  1. **Local AI model re-download.** Station activation's
     `compose_ollama_model_store` (`native_activation.rs`) merges every
     required model component's signed pack into
     `<install_root>\models\ollama\{blobs,manifests}\registry.ollama.ai\
     library\<repo>\<tag>`, but the GUI download screen's `local_ai_model`
     catalog entries (`acquisition_catalog.rs`) only ever checked
     `<install_root>\packs\local-ai-model\models\...` — a path nothing in
     this codebase writes. `ensure_component_available` therefore always
     fell through to a live ~7GB pull from `registry.ollama.ai`, even though
     `install-progress.log` showed every pack `copied_from_offline` and
     postinstall `SUCCESS`. `local_ai_model_items` now carries a SECOND
     `staged_at` candidate at the merged station-activation store
     (`merged_ollama_model_store_root`, additive — `CatalogItem.staged_at`
     was already a `Vec<PathBuf>` checked in order, no schema change) for
     the manifest item and every blob item (config + all layers), mirroring
     the exact relative layout `native_packs::validate_ollama_model_contract`
     already encodes. `captions-floor` had the equivalent fix from day one
     (`FLOOR_STAGED_ROOT`'s special-case); `local_ai_model` never got the
     matching candidate until now. 3 new Rust tests in
     `acquisition_catalog.rs`: every item's candidate-path shape, a
     regression pinning the exact `models\ollama` path the field miss
     needed, and `ensure_component_available` accepting a hash-matching file
     staged only at the new path without a download.
  2. **"Open installer log" did nothing when clicked.** Two stacked bugs:
     `newest_installer_log_path` (`main.rs`) only ever looked for
     `runtime-host.log` under the per-user state root — written by the
     native service, which has not started yet on the download screen — and
     never for `install-progress.log` (the NSIS elevated installer's own
     transcript, written under `%PROGRAMDATA%\CivicCast` and already
     complete by the time that screen exists); and the command hardcoded
     `notepad.exe` instead of the OS default handler
     (`cmd.exe /C start ""`, the same idiom `open_operator_console` already
     uses for URLs). Frontend compounded it: `AcquisitionFlow.tsx`'s onClick
     awaited `openInstallerLog()` with no `try`/`catch`, so a rejected
     command surfaced nowhere but the devtools console — the button visibly
     did nothing. Fixed all three: `newest_installer_log_path` now checks
     both logs and returns whichever exists and was modified most recently;
     the command opens the OS default handler; the button now surfaces a
     failure through the same `role="alert"` region "Stop downloading"
     already uses. 5 new Rust tests (pure path resolution +
     real-temp-file selection logic) and 3 new frontend tests (success,
     visible failure, error clearing on a later success).
  3. **No shortcut anywhere led back to the running station.** Once the
     setup wizard's window closed, an operator had no clickable path to the
     operator console or public portal — the setup app's own finish screen
     offers "Open operator console", but that control disappears with the
     window, and this installer created no Start Menu or Desktop entry
     pointing at either surface (only Tauri's own shortcut to the setup
     wizard itself, which just re-runs first-run setup). `NSIS_HOOK_
     POSTINSTALL` now writes a `CivicCast (Native)` Start Menu folder with
     two Internet Shortcut (`.url`, no icon-resource plumbing needed) files
     — "CivicCast Operator Console" and "CivicCast Public Portal" — plus a
     Desktop "CivicCast Operator Console" shortcut, at literal URLs matching
     `main.rs`'s own `OPERATOR_CONSOLE_URL`/`RESIDENT_PORTAL_URL` constants
     (installer-state's URL isn't resolvable yet at POSTINSTALL time — the
     GUI's own first run hasn't happened). Best-effort and silent-safe: a
     write failure logs a breadcrumb but never aborts or alerts. `NSIS_HOOK_
     POSTUNINSTALL` removes all three, unconditionally — deliberately
     outside the `$R2` service-stop-confirmed gate that guards the
     `$INSTDIR` runtime/packs tree removal, since a shortcut carries none of
     that gate's still-running-process hazard. 3 new policy tests in
     `tests/policy/test_native_installer_identity.py` (creation shape +
     placement + no dialogs, a `main.rs`-constant drift guard, and
     unconditional removal), plus one pre-existing breadcrumb-tail pin
     updated to the new true tail.
  4. **`--civiccast-restore-setup-handoff` ran and printed nothing from a
     terminal.** The top-of-file `#![cfg_attr(not(debug_assertions),
     windows_subsystem = "windows")]` makes a release build GUI-subsystem,
     so the process starts with no console at all -- `run_setup_handoff_
     recovery_pass`'s exit-0/85/86/87 messages (the whole point of this CLI
     recovery flag) had nowhere to go. `run_native_restore_setup_handoff_cli`
     now calls a new `attach_or_alloc_console_for_cli_recovery` (Windows-
     only) BEFORE that function's first print: `AttachConsole
     (ATTACH_PARENT_PROCESS)` connects to the invoking terminal when one
     exists, falling back to `AllocConsole()` when it does not. Rust
     resolves stdio handles via `GetStdHandle` fresh on every write, so
     calling this before the first print -- and nowhere else in the binary
     -- is what fixes it without touching the ordinary GUI launch (which
     still never shows a console, unchanged). 1 new text-contract test
     (`attach_console_call_precedes_the_recovery_pass_in_source_order`,
     mirroring `native_service_registration.rs`'s existing self-source-read
     convention) pins the call ordering itself, since the bug is invisible
     to a normal unit test (`windows_subsystem` is unset in debug/test
     builds, so the consoleless condition never reproduces there) and every
     real code path through this function ends in `std::process::exit`.
  Full verification: `cargo test` (399 passed) + `cargo clippy` in the
  installer crate, `npm run typecheck` + `vitest run` (145 passed) in the
  installer frontend, and the repository's `pytest tests/policy` suite
  (1828 passed) all green.

- **D4 provisioning survives a reserved/excluded Windows TCP port instead of
  crashing PostgreSQL's bind (two real LPM deployment failures, 2026-08-27,
  candidate 75cc13f).** Both independent installer runs failed identically
  at `d4-provision` (installer exit 116, engine rc 75):
  `pg_ctl start` could not bind `127.0.0.1:5432` — `WSAEACCES` ("Permission
  denied"), `could not create any TCP/IP sockets` — because the port sat
  inside a Windows-administered excluded TCP port range (a Hyper-V/WSL
  `winnat` dynamic reservation, which moves across reboots). PR #51's
  `PROVISION-RECOVERY.md` correctly named the pg_ctl diagnostic but nothing
  survived it — any program asking for that exact port would have failed
  identically. New `civiccast.native.provision.port_select` module: before
  `pg_ctl start` ever runs, the CLI test-binds the intended
  `127.0.0.1:<port>` itself; on a bind refusal it reads
  `netsh int ipv4 show excludedportrange protocol=tcp`'s excluded-range
  table and falls forward through a small documented candidate list (5432,
  5433, 5434, 5435, 5544 — 5432 always tried first), skipping any candidate
  already inside an excluded range and real-bind-testing every other one.
  The first bindable candidate becomes `context.postgres_port` — the single
  field every downstream write already derives the port from (rendered
  `postgresql.conf`, the `pg_ctl start`/`stop` argv, and (via
  `resolve_database_url`) the `DatabaseUrl` handed back to the Rust caller
  and written to `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl`, this
  station's single source of truth for the port). If every candidate is
  excluded or refuses to bind, provisioning halts fail-closed (never a
  silent guess) and `PROVISION-RECOVERY.md` now names the exact cause —
  every port tried, the Windows-excluded ranges quoted verbatim, and the
  copy-paste fix commands (`net stop winnat` / `net start winnat`, `netsh
  int ipv4 show excludedportrange protocol=tcp`) — instead of a bare pg_ctl
  crash. Consumer-side gap closed in the same pass:
  `civiccast.native.supervisor.service`'s `default_dependency_provider`
  never parsed the postgres host/port out of `DATABASE_URL` at all (unlike
  `civiccast.native.upgrade.pg_lifecycle.derive_pg_lifecycle_paths`, which
  already did this correctly for the D3 upgrade engine) — the SUPERVISED
  postgres child's own launch argv silently used `Supervisor`'s
  `"127.0.0.1"`/`5432` defaults regardless of what D4 actually provisioned,
  so a station whose port fell back off 5432 would have started its
  running service pinned to the wrong port forever, even though the
  provisioning-time fix above had already worked. `build_production_service`
  gained `db_host`/`db_port` parameters (default `"127.0.0.1"`/`5432`,
  backward compatible), `ProductionDependencies` gained matching fields, and
  `default_dependency_provider` now parses `DATABASE_URL` the same way D3
  does before threading the result through. 27 new tests: 20 in
  `tests/native/test_provision_port_select.py` (excluded-range parsing
  against realistic `netsh` output, the pure fallback-selection decision
  logic with an injected bind seam, real local TCP bind-test coverage
  against genuinely free/held ports, and a regression pinned to the exact
  LPM failure signature), 2 in `tests/native/test_provision_cli.py` (the
  honest no-port-available recovery document, and the fallback port
  actually flowing into the provisioned context), and 5 in
  `tests/native/test_supervisor_service.py` (the `db_host`/`db_port`
  wiring through `build_production_service`, `default_dependency_provider`'s
  `DATABASE_URL` parsing and its unparsable-URL fallback, and the factory's
  pass-through of both fields).

- **Runtime-dependency acquisition survives upstream release pruning
  (mirror-first fetch + reviewed fallback URLs).** Candidate build run
  33094460301 failed with a 404 in `scripts/build_native_ffmpeg_pack.py`'s
  `--acquire` because BtbN/FFmpeg-Builds pruned the pinned autobuild release
  tag (BtbN keeps only recent daily tags plus one per calendar month). PR
  #52 repinned to the next surviving build, but that pin is equally
  prunable — a lock edit can never be the durable fix. `scripts/
  provision_native_runtime_dependencies.py`'s `fetch_locked_artifact` (the
  shared acquisition primitive behind the ffmpeg, server, ollama, and cuda
  pack builders) now: (1) consults a persistent, hash-addressed archive
  mirror (`CIVICCAST_RUNTIME_ARTIFACT_MIRROR` env var or `mirror=` param,
  layout `<mirror>/<sha256>/<filename>`) before touching the network,
  ignoring-then-repairing any entry that fails verification; (2) writes
  every verified download back through to the mirror, so the pinned bytes
  outlive the upstream tag; and (3) accepts an optional, reviewed
  `fallback_urls` list in the lock (same HTTPS-host allowlist, tried in
  order after the primary URL fails, with an all-sources failure report).
  The committed lock's size+SHA-256 pin stays the sole admission authority
  on every path — mirror hits and fallback downloads are verified exactly
  like a fresh primary download. Wiring:
  `.github/workflows/native-beta-candidate-artifacts.yml` restores the
  FFmpeg archive via `actions/cache` (keyed on the runtime lock file) on
  the hosted lane, and points the self-hosted lane at the box-local
  persistent mirror `C:\CivicCastTester\runtime-artifact-mirror` (outside
  the runner work/temp trees, same box-local precedent as `kit-staging`) —
  seeded with the currently pinned FFmpeg archive, hash-verified, at review
  time. 14 new tests in
  `tests/native/test_runtime_dependency_provisioner.py` cover the
  mirror-hit-with-zero-network path, env-var configuration, corrupt-entry
  repair, write-through admission, mirror-write-failure tolerance,
  primary-404-to-fallback ordering, all-sources-fail reporting, and the
  `fallback_urls` schema boundary.

- **S7 media lifecycle worker — GPL encoder literal removed from the default
  transcode seed list, resource posture made conservative.** A regression
  audit of `civiccast/schedule/media_lifecycle_worker.py` found its default
  transcode format catalog seeded, for every validated asset by default, an
  `h265_1080p_8mbps` target whose ffmpeg args carried a bare `libx265`
  (GPL) literal — never resolved through any encoder-selection seam, unlike
  H.264's `resolve_h264_encoder()`. This repo's no-GPL posture (ADR 0007's
  compliance section) forbids exactly this. `tests/policy/test_ffmpeg_h264_encoder.py`'s
  repo-wide sweep missed it because it only ever checked for the literal
  string `"libx264"`, not because of directory scope (it already walked the
  whole `civiccast/` tree) — widened to a `_FORBIDDEN_GPL_ENCODER_LITERALS`
  set (`{"libx264", "libx265"}`) and proved with a planted-literal test
  (`test_detector_flags_a_planted_libx265_literal`) shaped exactly like the
  real defect. Independently, the same worker dispatched every seeded
  format synchronously in its own thread at normal process priority under
  ffmpeg's flat 6-hour default timeout — a large amount of unsupervised,
  full-priority ffmpeg work sharing the box with operator requests, with no
  station-level off switch (the same class of "unfiltered ladder wastes
  time on rungs the source can't fill" problem PR #45 found and fixed in
  the VOD packager, here for background proxy generation instead of a
  synchronous HTTP path). Resolved S7 spec Open decision #1 ("Transcode
  format defaults... h265_1080p_8mbps (archive)... h264-only for
  simplicity?") as the named h264-only alternative:
  `DEFAULT_TRANSCODE_FORMATS` is now a single resolution-aware
  `h264_720p_5mbps` rendition that never upscales past the source's own
  probed `height_px` (mirrors PR #45's never-upscale posture, implemented
  locally); `h264_mezzanine` stays available opt-in via
  `CIVICCAST_TRANSCODE_FORMATS`, not seeded by default; a new
  `MediaLifecycleWorkerSettings.transcode_seeding_enabled` switch (default
  `True`, so first-run ingest still produces a proxy) lets a station turn
  ingest-time transcoding off entirely; `transcode_concurrency` is an
  explicit, validated field fixed at `1`, matching what the dispatch loop
  already does, rather than an unstated implementation detail; and
  `civiccast.stream._ffmpeg.run_ffmpeg` gained an opt-in `lower_priority`
  parameter (Windows `BELOW_NORMAL_PRIORITY_CLASS`, default `False` so
  live egress and the VOD packager's synchronous request path are
  unaffected) that the worker's dispatched jobs now use together with a
  per-minute-of-source timeout budget (10 min floor, 10x-realtime, 2h
  ceiling) replacing the flat 6h default. See ADR 0007's "S7 ingest-time
  transcode defaults and resource posture" amendment for the full
  rationale. Files: `civiccast/schedule/media_lifecycle_models.py`,
  `civiccast/schedule/media_lifecycle_worker.py`,
  `civiccast/stream/_ffmpeg.py`, `tests/policy/test_ffmpeg_h264_encoder.py`,
  `tests/schedule/test_media_lifecycle_worker.py`, `tests/stream/test_ffmpeg.py`,
  `docs/adr/0007-hls-packager-design.md`,
  `docs/spec/3.0/sections/S7-media-lifecycle-and-readiness.md`. No
  operator settings UI exists yet for `transcode_seeding_enabled` or any
  other worker setting — named as real follow-up, not claimed done here.
- **Asset packaging no longer upscales — the Gate A `/package` timeout.** Gate
  A's clerk loop uploaded the real 640x360 sample clip (201 Created), called
  `POST /api/staff/assets/{asset_id}/package`, and got no response at all
  within its 30 s client budget; the station's own uvicorn access log
  (`station-diag/final/logs/control_plane.log`) has **no line for the package
  request** while it does log every later request, so the handler was still
  running — not deadlocked, not blocking the event loop, just slow. No file on
  the packaging path changed in the regression window: `git log f31618f..main`
  touches neither `civiccast/stream/packager.py` nor `_ffmpeg.py`, and
  `civiccast/schedule/router.py` is byte-identical. What was actually wrong is
  older than the window and easy to miss — `pack_vod_asset` encoded all four
  ABR rungs for every source regardless of the source's resolution, so a
  640x360 clip was **upscaled to 1920x1080 and 1280x720**: pixels invented,
  4.5 Mbps spent carrying no extra detail, and the full encode cost of a large
  frame paid twice. Measured on that clip on a fast development box: 18.4 s for
  the content ladder, of which the two upscaled rungs are 14.6 s (~81%);
  end-to-end the endpoint took **~19 s steady-state and 23 s on the first call
  in a process**, against a 30 s client timeout, on hardware considerably
  faster than the 16 GB sandbox VM. The margin was always thin; it took no
  code change to cross it. New `civiccast.stream.config.select_ladder` picks
  the rungs before encoding — never taller than the source, top rung pinned to
  the source's own resolution, the ladder's top rung still a product cap so a
  4K source publishes at 1080p and below, and the **full ladder unchanged
  whenever the source dimensions cannot be read** (the packager never guesses
  its way into a smaller ladder). `pack_vod_asset` gained
  `source_width`/`source_height`, and probes the input itself when a caller
  does not supply them, so all three call sites — the staff package endpoint,
  first-run sample seeding, and the live finalization worker — get the fix
  without needing to know about it. Same clip after the change: **3.4 s of
  content-ladder encode, an 81% reduction**, and the same booted-app
  upload-then-package measurement that read 22.8 / 19.1 / 18.8 s now reads
  **4.6 / 4.1 / 3.9 s** — from ~63% of the 30 s budget down to ~14%, so the
  sandbox VM has room to be several times slower and still answer. The
  emitted manifest is `360p` (640x360, the source's own resolution) + `240p`
  + slate, with no upscaled variant. A 1080p or larger source is unaffected
  in either time or output, which is correct: nothing upscales there. ADR
  0007 carries the amendment.
  **Not fixed, stated plainly:** packaging is still a synchronous HTTP request
  whose latency is proportional to source duration. A 90-minute 1080p meeting
  still occupies the request — and the operator console's fetch — for as long
  as the encode takes. Moving it to a job-and-poll contract like the offline
  caption jobs changes the endpoint's response contract and every caller of
  it, so it needs its own ADR and an owner decision.

- **Gate A — the stalls were `ConvertTo-Json` walking a cycle in
  `Get-Content`'s note properties.** Root cause for five runs (4, 6, 7 and both
  candidate-#11 runs), found by the liveness instrument on its very first
  outing: `driver_process_alive=true driver_cpu_seconds=449.5
  driver_working_set_mb=8318.2` — alive, CPU-hot, 8.3 GB resident in a 16 GB
  VM, so not blocked I/O at all. `Get-Content` emits `PSObject`-wrapped
  strings carrying `PSPath`/`PSParentPath`/`PSChildName`/`PSDrive`/`PSProvider`/
  `ReadCount`; `PSProvider` is a `ProviderInfo` whose `.Drives` collection
  holds `PSDriveInfo` objects that each point back at it — a cycle.
  `ConvertTo-Json` serializes note properties, so `-Depth N` walks that cycle
  `N` deep. Measured here, **one** such line: 1,889 chars at depth 3;
  3,852,872 at depth 6; **98,197,802 at depth 7 (11.2 s)**; at depth 8 it never
  finished (killed at 180 s having reached 4 GB and 178 s of CPU). The driver
  serialized **eighty** of them at depth 8 via `install_progress_log_tail`.
  The same 80 lines as plain strings at depth 8: 5,314 chars in 30 ms. This
  also explains why the stall always looked positional — the assignment was
  always followed immediately by a `Save-Summary`, so relocating the capture in
  the previous change moved the explosion earlier in the run rather than
  removing it. (Run 3's `t2-render-assert` stall is *not* explained by this and
  is not claimed to be.) Fixed with two independent defences plus a source-site
  cast: `ConvertTo-PlainForSummary` rebuilds the summary from plain types
  before serialization — recursing only into arrays and dictionaries, capping
  its own depth, and rendering anything else via `ToString()` rather than
  walking its graph (a cyclic `ProviderInfo` now serializes to 59 characters) —
  and the serialization depth drops from 8 to 6, which is one more than the
  deepest real member needs. While fixing it, a second PS 5.1 trap: the
  sanitizer's first form used `System.Collections.Generic.List[object]` with
  `return @($out)`, which throws *"Argument types do not match"* in Windows
  PowerShell 5.1 and silently degraded **every array member of the summary**
  into one space-joined string; it uses `ArrayList` and
  `return , ($out.ToArray())` now, the leading comma also keeping
  single-element arrays as arrays for the judge's counted fields. Finally, when
  the watchdog fires and the driver is still alive it now also records a CPU
  delta with a verdict (verified against a real spinning process at
  `driver_busy_percent=100.8` and a real sleeping one at `0`) and, guarded by a
  working-set cap and a 120 s timeout, a MiniDump written to `$env:TEMP` —
  never to the shipped evidence directory, since a full dump of the process
  this was written for would be 8.3 GB.
- **Gate A — the remaining synchronous `C:\CivicCastHostStore` reads are now
  bounded, and the "hung or dead?" question is finally instrumented.** The
  candidate-#11 run (`831f3df`) is the first Gate A run whose install
  succeeded end to end (`installer_exit_code: 0`, `d4-activate-station:
  returned 0` — the run-7 station-bundle failure is resolved, and
  `d4-activate-station` went 35m09 ✗ → 31m13 ✓ with the shipper quiesced,
  though against a *different* kit so that is not a controlled comparison).
  It then stalled, and for the first time the per-statement instrumentation
  named the step: `stuck_step=install-progress-copied-post-install`,
  `seq:7`, 509s. That **excludes** the expected culprit rather than
  confirming it — the hoststore reads (install-dir discovery, `station-set.json`,
  ARP, service checks) are all separately recorded steps further down and
  none appeared; what remains is two in-memory assignments and a ~2 KB local
  JSON write, against a 178-line log whose longest line is 138 characters.
  Since four runs have now ended with a signature identical whether the
  driver's thread *blocked* or its process *died*, the driver records its PID
  (`_DRIVER-PID.txt`) and both watchdog triggers now call `Get-DriverLiveness`
  as they fire, writing `driver_process_alive=true|false` (plus CPU seconds
  and working set) into `STALL-TIMEOUT.txt` / `WATCHDOG-TIMEOUT.txt` and the
  placeholder `DONE.json`. Independently, the three remaining synchronous
  readers of the mapped install target — `Test-KnownPaths`, the install-tree
  listing, and `Invoke-StationDiagCapture`'s marker copies — now run through a
  new `Invoke-BoundedProbe` (a throwaway `powershell.exe` with an arguments
  file, a result file and a hard timeout), because "targeted and
  non-recursive" was never the same as "bounded". The quiesce window also
  stops being lifted when the installer returns; it now runs to the station-up
  wait, so the 25-second tick no longer resumes underneath 10,683 files of
  post-install hoststore reads. Moving the install target to a local directory
  was considered and rejected: this file already records that staging locally
  hits "os error 112 (not enough space)" on the ~40 GB virtual disk and that
  activation "REFUSES junction/symlink install-roots", and `Run-GateA.ps1`'s
  fresh-install guarantee plus `gate_a_verdict.py`'s install/activation checks
  both read that tree host-side. Also: `_SHIPPER-QUIESCE.marker` joins the
  shipper's retraction list — the additive mirror was leaving a stale copy on
  the host that told readers the run was still quiesced when it was not.
- **Self-hosted native-beta candidate build — the same persisted-cache bug
  as #41, one script over: `civiccast-ffmpeg-pack-cache`.** Candidate run
  32858543561 (main=7bf705a) got further than ever before — the PostgreSQL
  cache fix (#41) held, K1 succeeded — then failed at `build_native_ffmpeg_pack:
  FFmpeg closure seed bin/ffmpeg.exe is missing:
  ...\civiccast-ffmpeg-pack-cache\extracted\ffmpeg\bin\ffmpeg.exe`. Same
  root cause as #41 in a different cache: `acquire_ffmpeg_pack_sources()`'s
  bare `destination.exists()` check trusted a self-hosted `--cache`'s
  persisted, interrupted-mid-extraction `extracted/ffmpeg` tree instead of
  re-extracting it. Fixed the identical way: `_extracted_ffmpeg_is_complete()`
  re-verifies a pre-existing extraction against the same pinned bin/license
  file set `build_ffmpeg_pack()` itself requires (reusing the existing
  `_ffmpeg_sources()` validator) before trusting it; an incomplete tree is
  cleared and re-extracted.

  Per the pattern of each run peeling one more layer of the same job, did a
  static sweep of every remaining script `build-native-beta`'s pack-build
  step calls for the same bug classes (idempotent-cache trust, hosted-only
  assumptions, live-network fetches, tool availability, hash pins the
  self-hosted toolchain can't reproduce) rather than waiting for the next
  run to surface the next layer. Exhaustively grepped every script for both
  the "trust because it exists" and "refuse because it's non-empty"
  shapes: `build_native_ollama_pack.py`'s acquire is already immune (always
  extracts fresh into a temp dir, validates, then atomically replaces the
  destination — never trusts stale state); `build_native_cuda_pack.py`'s
  acquire already re-verifies a cached file's hash before ever reusing it,
  deleting and re-downloading on mismatch; `build_native_bootstrap.py`
  unconditionally runs `npm ci` (npm's own clean-install operation, not a
  cache-trust check) and locates NSIS via Tauri's own tool-provisioning
  cache; every remaining `X.exists() and any(X.iterdir())` refusal
  (`civiccast-app-payload`, `civiccast-app-payload-scratch`/`pyav-build`,
  `civiccast-gstreamer-closure`, `build/wp1-native-toolchain`) is either
  already pre-cleared by the self-hosted-only step #31 added, or lives
  inside the repo checkout, always fresh via `actions/checkout`, so it can
  never trigger from self-hosted persistence. No further code changes
  found necessary in this sweep.

  `tests/native/test_build_native_ffmpeg_pack.py`: +4 tests (complete
  extraction reused; incomplete extraction — missing `ffmpeg.exe`, the
  exact observed shape — cleared and re-extracted; no-cache-yet path
  unaffected; direct unit coverage of the completeness check).
- **Self-hosted native-beta candidate build — a persisted, interrupted
  PostgreSQL cache extraction, plus a live MSYS2 keyserver dependency.**
  Candidate run 32845198987 failed identically in BOTH attempts (a
  keyring-related retry did not change the outcome) at "Build and verify
  signed component packs": `pinned PostgreSQL initdb.exe is missing:
  ...\civiccast-server-pack-cache\extracted\postgres\bin\initdb.exe`.
  Root cause: `acquire_server_pack_sources()`'s bare `destination.exists()`
  check trusted a self-hosted `--cache`'s persisted `extracted/postgres`
  tree — left incomplete by an earlier interrupted run — without
  re-verifying it, the same idempotent-scratch bug class as
  `civiccast-build-venv`/`civiccast-msvc-build-tools` (#31), applied here
  to a different cache. Fixed by re-checking a pre-existing extraction
  against the same pinned bin/lib/share file set `build_server_pack()`
  itself requires (`_extracted_tree_is_complete`, reusing the existing
  `_postgres_sources`/`_tsduck_sources` validators — no duplicated
  validation logic) before trusting it; an incomplete tree is cleared and
  re-extracted from the already hash-verified archive.

  Separately investigated per the task: attempt 1's MSYS2 pacman-key
  keyserver refresh errors (`==> ERROR: Could not update key: <id>`, ~18
  minutes wasted, non-fatal that run since MSYS2's own hook tolerates the
  failure). `build_minimal_ffmpeg()` now pre-populates the pacman keyring
  itself, offline, via a non-login `bash -c` invocation (`pacman-key
  --init` + `--populate msys2`, both sourced from the pinned, hash-
  verified MSYS2 base archive already on disk — never a keyserver) before
  the first login-shell `pacman -U`; MSYS2's own `07-pacman-key.post` hook
  then sees its trust directory already populated and skips the network
  `--refresh-keys` step entirely, with no patch to MSYS2's own shipped
  script. This code has no self-hosted/hosted branch, so the fix applies
  to both lanes — hosted merely had better keyserver luck, not immunity.
  Verified locally, outside any runner tree
  (`C:\CivicCastTester\msys2-keyring-test`, deleted after), against the
  real pinned MSYS2 base: pre-populating completes in ~7s wholly offline
  (vs. the observed ~18 minutes), and a subsequent real `pacman -U`
  against the pinned `nasm` package still passes genuine PGP signature
  verification and installs successfully.

  `tests/native/test_build_native_server_pack.py`: +4 tests (a complete
  pre-existing extraction is reused; an incomplete one — missing
  `initdb.exe`, the exact observed shape — is cleared and re-extracted;
  the no-cache-yet path is unaffected; direct unit coverage of the
  completeness check for both artifact kinds).
- **Self-hosted native-beta candidate build — "Sign the native bootstrap
  (Azure Artifact Signing)" needs the .NET SDK, not just the runtime.**
  Candidate run 32838619949 got one step from a complete build, then died:
  `Exception: Failed to install package: sign 0.9.1-beta.26227.3`.
  `azure/artifact-signing-action` installs its `sign` CLI (net8.0-targeted,
  per nuget.org/packages/sign, needing the .NET 8 SDK or later) via `dotnet
  tool install`. A hosted `windows-latest` runner ships the SDK
  preinstalled; this box had `dotnet` on PATH but RUNTIME-only (`dotnet
  --list-sdks` empty, only `Microsoft.NETCore.App 8.0.30`), so the tool
  install failed with "No .NET SDKs were found." A new self-hosted-only
  step, "Provision a pinned .NET SDK for the signing action," installs a
  pinned 8.0.424 SDK (LTS, 8.0.4xx band) via Microsoft's own
  `dotnet-install.ps1` — a non-admin, caller-owned install into this
  lane's own `RUNNER_TEMP` scratch root, pinned by exact `-Version` (never
  `latest`/`LTS`) — then exports `DOTNET_ROOT` and prepends the SDK
  directory to `GITHUB_PATH` so the signing step resolves it. Idempotent
  the same way every other self-hosted scratch dir in this job is: a
  pre-existing tree is trusted only when `dotnet --list-sdks` actually
  reports the pinned version (not a marker file alone), and an invalid one
  is cleared and reinstalled. Verified locally, outside any runner tree
  (`C:\CivicCastTester\dotnet-sdk-test`, deleted after): the exact command
  the signing action runs internally, `dotnet tool install sign --version
  0.9.1-beta.26227.3`, succeeds against this pinned SDK. Hosted lane
  untouched (the step is self-hosted-only). `tests/policy/
  test_native_beta_candidate_workflow.py`: +2 tests (the provisioning
  step's shape/ordering/pin, and a regression guard that a floating
  `latest`/`LTS` version would fail the pin).
- **PyAV reproducibility gate — the reviewed wheel hash was stale after
  extending its embedded build-provenance record.** PR #39 (the
  self-hosted av-provenance fix) added `pyav_sdist_url`/`sha256`/`bytes`
  to the wheel's embedded `FFMPEG-PROVENANCE.json`, which deterministically
  changes the compiled wheel's bytes — but `build_native_pyav_wheel.py`'s
  `EXPECTED_WHEEL_SHA256`/`BYTES` still pinned the PRE-change reference, so
  the hosted-lane "Two independent Windows workspaces" reproducibility
  gate (run 32831619693) failed on its very first build: `av-18.0.0-
  cp311-abi3-win_amd64.whl byte length 4347090 != pinned 4346940`. Not new
  non-determinism — the embedding mechanism (`SOURCE_DATE_EPOCH`, the
  fixed zip timestamp, `sort_keys=True` on the JSON) is unchanged and
  already handled the original FFmpeg-only provenance fields
  deterministically; the 3 new fields are static compile-time constants
  with no environment/timestamp dependency. Re-pinned `EXPECTED_WHEEL_
  SHA256`/`BYTES` to the real value the gate's own workspace-a build
  reported (`0f9427a4...` / 4,347,090 bytes); cascaded to
  `requirements-native-app.txt`'s `av==18.0.0` hash pin (the same reviewed
  wheel identity, enforced separately at install time) and, since that
  changes the lock file's own bytes, to `APP_REQUIREMENTS_SHA256` in
  `civiccast/native/app_payload.py` (`git diff` checked before re-pinning,
  per that constant's own standing rule: exactly one byte range changed,
  nothing else in the lock). Two test literals
  (`tests/native/test_pyav_wheel_builder.py`,
  `tests/native/test_app_payload.py`) updated to match. Not independently
  re-verified by a local double-build (this box has no pinned MSVC Build
  Tools install; provisioning one plus two full FFmpeg/PyAV compiles was
  not feasible in reasonable time) — verified by full test suite instead,
  and by letting CI's own two-independent-workspace comparison confirm on
  the next push.
- **S12 OTT build matrix — Samsung Tizen was the one dishonest cell:
  `tizen package` never actually ran; the job passed via a static
  `config.xml`-validation fallback instead of a real `.wgt` build.** Root
  cause, found via a base64-encoded `profiles.xml` dump on a diagnostic CI
  run (needed because GitHub's log masking hides the plaintext otherwise):
  Tizen Studio CLI 2.5.25's `tizen security-profiles add` writes
  `password="<path>.pwd"` into `profiles.xml` for both the author profile
  and the auto-attached default distributor profile — a path to a sidecar
  `.pwd` file that is never created, instead of the real plaintext
  password. `tizen package`'s signer then reads that path string literally
  as the PKCS#12 password and fails with `CertificationException: Invaild
  password` — not a certificate, cli-config, or DISPLAY-less quirk;
  install, certificate generation, security-profile registration, and
  cli-config all already worked. Two other projects hit the identical
  stack trace running `tizen package` headlessly
  (jellyfin/jellyfin-tizen#66, fgl27/smarttv-twitch#41); the new
  `civiccast/apps/ott-native/tizen/fix_signing_profile.py` applies the
  same fix those issues converged on — patch the bogus `.pwd` paths to the
  real plaintext passwords right before packaging — and stages just the
  four real runtime files into a clean temp directory first so the
  resulting `.wgt` doesn't ship this repo's dev/CI-only files. All 8
  `ci-ott-apps.yml` platforms now produce a real build artifact; see
  `docs/spec/3.0/sections/S12-ott-apps.md` and `tizen/README.md` for the
  full diagnosis. `civiccast-tizen-wgt` verified as a real signed widget
  (contains `author-signature.xml`/`signature1.xml`) on CI run
  32819441306.
- **Self-hosted native-beta candidate build — the advisory PyAV posture
  stopped one layer too early: the independent post-build provenance
  sweep still rejected the self-hosted-built `av` wheel outright.**
  Candidate run 32822175257 got through the PyAV build and `uv install`
  steps (#30's advisory posture) and still failed "Build and verify
  signed component packs": `"WHEELS/av-18.0.0-cp311-abi3-win_amd64.whl is
  not an authorized retained dependency wheel"` plus every one of `av`'s
  installed files reported `"is named by no wheel RECORD"`.
  `scripts/build_native_app_payload_pack.py`'s `build_app_payload_pack()`
  runs `scripts/verify_native_app_payload.py`'s independent, deny-by-
  default `check_app_payload_verification()` on the fully assembled tree
  AFTER the build — a separate code path from `install_pinned_
  dependencies()`, with no advisory posture of its own, so it re-rejected
  the same wheel on its own byte hash regardless of how the earlier steps
  had authorized it. `_retained_dependency_wheel_provenance()` now
  authorizes a byte-hash-mismatched `av` wheel by BUILD PROVENANCE instead
  (name/version pin against the reviewed lock stays a hard failure,
  unaffected): it re-asserts the two upstream inputs the wheel was
  compiled FROM — the PyAV sdist and the FFmpeg source archive, both
  always hash-verified hard-fail on every lane — by reading them back out
  of the wheel's own embedded `FFMPEG-PROVENANCE.json` (`ffmpeg_
  provenance()` in `build_native_pyav_wheel.py` now also records the PyAV
  sdist's hash/bytes, alongside the FFmpeg source archive's it already
  recorded) and re-checking against the same pinned constants — never
  trusted unchecked. Once authorized this way, the existing per-member
  ownership walk needs no further change: it already anchors every
  installed byte to the IN-RUN wheel's own bytes/RECORD, which resolves
  the RECORD-mismatch symptom for free — the RECORD was never wrong, it
  was simply never reached because the wheel was never authorized.
  `check_app_payload_verification()`/`build_app_payload_pack()` take the
  same `advisory_pyav_wheel_hash` flag threaded from the CLI; every OTHER
  retained wheel, and `av` itself on the hosted lane (flag unset, always),
  is unaffected. `tests/native/test_app_payload_builder.py`: +6 tests
  (authorizes a provenance-matching wheel; hosted lane still fails the
  same wheel; a wrong version pin still fails even advisory; a TAMPERED
  provenance claim still fails; a MISSING provenance file still fails; the
  flag does not relax any other distribution).
- **Self-hosted native-beta candidate build — `_work\_temp` scratch dirs
  from a failed run blocked the next run, starting with `civiccast-build-
  venv`.** Candidate run 32810709045 failed "Bootstrap the reviewed Python
  build environment": `uv sync` refused `civiccast-build-venv` as "not a
  valid Python environment (no Python executable was found)" because the
  PREVIOUS self-hosted run (32806127399, a different bug, fixed separately)
  died mid-`uv sync` and left a half-created venv at that exact path — a
  hosted runner's `RUNNER_TEMP` is always fresh, so this class of bug never
  surfaces there. Inventoried every `RUNNER_TEMP`-scoped scratch dir across
  both build jobs against the workflow and the scripts it calls and found
  the same shape twice more, both latent: `build_native_app_payload.py`'s
  `build()`, `build_native_pyav_wheel.py`'s `build()`, and
  `build_native_runtime_closure.py`'s `build()` all refuse to write into a
  non-empty output directory. The "Bootstrap the reviewed Python build
  environment" step now clears an invalid `civiccast-build-venv` (missing
  `Scripts\python.exe`) before `uv sync` runs, relocating to a uniquely
  suffixed sibling path if it cannot be removed (still in use by
  something) rather than failing the job; a complete, valid venv is left
  untouched and reused. A new self-hosted-only step, "Ensure a clean
  self-hosted scratch tree before the pack build", clears
  `civiccast-app-payload`, `civiccast-app-payload-scratch`, and
  `civiccast-gstreamer-closure` before every self-hosted pack build (hard
  failure with a clear diagnostic if a leftover genuinely cannot be
  removed — none of these are known to be held open by a long-running
  process the way MSVC's own toolchain is) and best-effort clears
  `civiccast-gstreamer-stage` (non-fatal; its own `build()` does not
  require an empty directory). `civiccast-msvc-build-tools` gets a
  different fix, since a real MSVC Build Tools install is expensive to
  redo (~1.8 GB, real minutes): `provision_native_build_toolchain.py`'s
  `install_msvc()` now re-verifies a pre-existing install with the same
  real `cl.exe`/`link.exe` launch-and-version check a fresh install already
  trusted before reuse, and reinstalls only when that fails. A live
  follow-up on this exact candidate found that the runner's own attempt to
  clear an invalid MSVC tree by hand left an undeletable, unknown-
  completeness 1.8 GB leftover (`vctip.exe`/`mspdbsrv.exe` still holding
  files open) — `install_msvc()` now falls back to a uniquely suffixed
  sibling directory rather than failing the job when an invalid tree
  cannot be removed, and `main()` re-exports the actual resolved path to
  `GITHUB_ENV` so every later step that reads
  `$env:CIVICCAST_MSVC_INSTALLATION_PATH` as a fixed literal (the Tauri
  build's `vcvars64.bat` import, the pack build's own env block) picks it
  up automatically. Checked (not assumed) that the toolchain/pack-build
  download caches and the Ollama-model/captions-floor caches were already
  safe: every one downloads to a `.partial` file, hash-verifies it, and
  only then atomically renames it into place, so a killed download can
  never leave a cache entry a later run would wrongly trust — no change
  needed there. `tests/native/test_build_toolchain_provisioner.py`: +5
  tests for `install_msvc()`'s reuse/replace/relocate paths and `main()`'s
  `GITHUB_ENV` re-export. `actionlint` and the full policy suite pass;
  hosted-lane behavior is unchanged in every case (a hosted runner's
  `RUNNER_TEMP` never pre-exists, so every new reuse/relocate branch is
  unreachable there and each fix falls straight through to its pre-fix
  behavior).
- **Self-hosted native-beta candidate build — the advisory PyAV wheel hash
  never reached the install step, so run 32806127399 failed
  `uv pip install --require-hashes` with "Failed to download `av==18.0.0` /
  Hash mismatch" right after the advisory build had already accepted that
  same wheel with only a `::warning::`.** `--advisory-pyav-wheel-hash`
  (`docs/process/pyav-wheel-reproducibility.md`) was wired into
  `build_native_pyav_wheel.py`'s own `verify_artifact()` check on the
  compiled wheel, but `build_native_app_payload.py`'s
  `install_pinned_dependencies()` still ran a single unconditional
  `uv pip install --require-hashes -r requirements-native-app.txt`, which
  re-enforces that exact same hosted-reviewed hash for `av==18.0.0` —
  self-hosted physically cannot produce byte-identical MSVC output (see the
  doc), so the install always failed on that lane regardless of a clean
  build. Not an index/resolver miss: `--no-index --find-links` correctly
  found the locally built wheel; it failed the hash check against the
  requirements lock. `install_pinned_dependencies()` now takes the same
  `advisory_pyav_wheel_hash` flag `build()` receives: when set, `av`
  installs from the wheelhouse by its verified-unique filename with no hash
  check of its own (a second, unconditional `--require-hashes` install still
  covers every OTHER pinned dependency against the unmodified lock); when
  unset (the hosted lane, unchanged), a single `--require-hashes` install of
  the full lock runs exactly as before. `tests/native/test_app_payload_builder.py`
  covers both the unchanged hosted-lane invocation and the new advisory
  split-install path.
- **Gate A run 7 — the evidence shipper was starving the installer of the
  shared VSMB transport.** Every mapped folder in the sandbox VM
  (`C:\CivicCastPayload`, `C:\CivicCastHostStore`, `C:\CivicCastOutput`)
  rides one Windows Sandbox VSMB transport. Run 7, the first run on the
  shipper architecture below, failed at `d4-activate-station` with *"a signed
  station bundle (station-index.json and its packs) was not found"* — on the
  same staged kit that run 6 had activated cleanly. Comparing the installer's
  own `install-progress.log` across four runs, the two steps that never cross
  VSMB are flat to the second (`vc-redist` 4m04/4m04/4m04 → 4m05;
  `d4-provision` 25s/25s/28s → 28s) while every step that does is 1.6–4.2×
  slower in run 7 alone: `stage-packs` 6m39/6m47/7m21 → 11m26,
  `d2-verify-server-binaries` 6s/5s/5s → 21s, `d2-verify-app-payload`
  1m09/1m14/1m19 → 3m16, `d4-activate-station` 14m13/14m37/15m44 (all
  succeeding) → 35m09 and exit 67. The only new thing running underneath run
  7 was the shipper's 25-second `robocopy` tick. `In-Sandbox-Report.ps1` now
  quiesces the shipper to `-ShipQuiesceIntervalSeconds` (default 300) for the
  duration of the install via `_SHIPPER-QUIESCE.marker`, raised before the
  installer and cleared in a `finally`; the marker carries its own
  `quiesce_until_utc` expiry so a removal that never happens degrades to
  "shipping speeds back up", never to "shipping stopped". 300s stays far
  inside the host's 15-minute quiet-share bound, which
  `tests/gate_a/test_gate_a_harness_contract.py` now asserts. The mechanism
  behind the slowdown is not proven — the correlation, the clean controls,
  and the absence of any other self-hosted job on the box in that window are.
- **Gate A — the kit reached the sandbox through a two-hop junction chain.**
  `Resolve-Path` does not follow reparse points, so `Run-GateA.ps1` pointed
  `kit-download` at `sandbox-lab/kit-staging/<sha>` — itself already a
  junction to `C:\CivicCastTester\kit-staging\<sha>` after the workflow's
  reuse step — and the `.wsb` handed that two-hop chain to VSMB.
  `Host-Launch-Sandbox-Test.ps1` now resolves every `<HostFolder>` through
  reparse points to the physical directory before rendering, and
  `Run-GateA.ps1` junctions `kit-download` at the physical kit. Explicitly
  **not** the cause of run 7's failure: run 6 passed with the byte-identical
  chain, and `git clean -ffdx` recursing through such a junction was measured
  on this host and does not touch the target's contents. This is hardening.
  `Run-GateA.ps1` additionally logs the station bundle's file count and total
  bytes before launch — run 7's installer failed on "station-index.json *and
  its packs*" and the harness had only ever asserted the index file existed.
- **Gate A — the finalization path is instrumented per statement, and the
  installer breadcrumb capture moved out of it.** Runs 4, 6 and 7 all stopped
  advancing in the same three or four unlabelled statements after
  `station-diag-captured-after-t3t5`, and because the two surrounding
  `Save-Summary` calls were the only instrumentation, no post-mortem can name
  the operation. Run 7 narrows it (the complete 6844-byte copy reached the
  host, so `Copy-Item`'s handle closed) but does not close it: on this host,
  against run 7's own file, the remaining `Get-Content -Tail 80` measures
  8 ms. So the capture now runs immediately after the installer returns
  instead — a single forward read of the source into memory (16 MB cap), a
  write from memory, and the tail sliced in memory, replacing the old
  copy-then-re-read-with-`-Tail` shape — with the finalization call kept only
  as a guarded second attempt. Every statement in the path records its own
  step. Note that 8 minutes is the staleness watchdog's floor: run 7 proves
  "≥8 min", where run 6 proved "≥47 min", and they may not be the same
  failure.
- **Gate A — a run that ends via the watchdog lost its entire transcript.**
  Run 7 shipped a 686-byte `sandbox-transcript.log` — header only — despite
  150 failed station-up polls that each log a terminating error. Reproduced
  on this host: a Windows PowerShell 5.1 child that logged 100+ caught
  terminating errors still had a 689-byte header-only transcript on disk, and
  it was still 689 bytes after being killed without reaching
  `Stop-Transcript`. The transcript writer buffers in user space, and every
  watchdog-terminated Gate A run therefore loses the body. `Sync-Transcript`
  (`Stop-Transcript` + `Start-Transcript -Append`) now runs after the
  install, at the station-up verdict, and immediately before the finalization
  path.
- **Gate A — the harness stalled forever on the Windows Sandbox mapped
  folder, and its own staleness watchdog could not catch it.** Three runs
  hung late with the VM alive and the driver writing nothing further: run3
  (`8579e66`) between two consecutive ~30-byte `Add-Content` appends to
  `T3T5-RESULT.txt`; run4 (`8579e66`) and run6 (`f31618f`) both in the
  four-statement window between `Save-Summary 'station-diag-captured-after-t3t5'`
  and `Save-Summary 'install-progress-log-copied'`. Run6 had *passed every
  product check* — `T3_LOOP=PASS`, `CAPTIONS=PASS`, `T4_RESULT=PASS_PRODUCT_ENGINE`,
  `T5_RESULT=PASS beats=4 unhealthy=0` — and was then failed closed 47
  minutes later by the coarse whole-script watchdog. Run6 also disproves the
  obvious theory: 42 minutes into that stall the *separate* watchdog process
  created two brand-new files in the same mapped folder, so the share was
  alive; what was wedged was the driver's own in-flight synchronous I/O
  against it, on the single thread carrying the entire run.
  `sandbox-lab/scripts/In-Sandbox-Report.ps1` now writes everything to a
  local `C:\CivicCastLocalOut` and a separate shipper process mirrors it into
  `C:\CivicCastOutput` every ~25s, one disposable child process per tick
  (plus a heartbeat file), additive `robocopy /E` with an explicit retraction
  list rather than `/MIR`. DONE.json is written locally last, excluded from
  the bulk mirror and copied across on its own afterwards, then flushed
  through a bounded final tick — so the harness's oldest contract survives
  the new channel: DONE.json appearing on the host still means everything
  else already arrived (robocopy does not copy in write order, and the host
  tears the VM down within 10s of seeing that file). The two remaining places the driver itself touches
  the share — a one-time inbound seed for host-provided
  `SOAK_MINUTES.txt`/`SKIP_MODE.txt`, and that final flush — go through a new
  bounded `Invoke-BoundedProcess` that kills the child instead of waiting
  forever.
- **Gate A staleness watchdog never armed on the run it was written for.**
  It armed by string-matching the *current* value of
  `summary.json.last_completed_step` against three names while polling every
  30s. Every one of those names is momentary: run6's `runtime-check-*` steps
  occupied `summary.json` for ~1 second and `t5-soak-complete` for ~2, so a
  30s poller missed the whole ~3s window and the staleness bound stayed
  disarmed for the entire run. Arming is now a sticky file the driver writes
  once at the station-up verdict (`_VERDICT-STAGE.marker`) — `Test-Path`
  cannot be raced — with the (widened) step-name predicate kept only as a
  redundant second path. Stall detection now keys on a new monotonic
  `summary.json.step_seq` instead of step-name equality, and the watchdog
  reads and writes the local directory so it can no longer be blocked by the
  surface it exists to bound.
- **Gate A timeout budgets were mutually inconsistent.**
  `In-Sandbox-Report.ps1 -MaxScriptMinutes` 100 → 150 (run6 proved a healthy
  full run needs more headroom), and with it `-TimeoutMinutes` 30 → 170
  (`Host-Launch-Sandbox-Test.ps1`), 120 → 170 (`Run-GateA.ps1`) and 150 → 170
  (the explicit override in `gate-a-station-acceptance.yml`, which is the one
  that actually governs every CI run — fixing only the script defaults would
  have looked correct and changed nothing). The in-sandbox watchdog is now
  always the first bound to fire, rather than the host giving up before the
  watchdog it depends on. `tests/gate_a/test_gate_a_harness_contract.py` is a
  new static contract suite that reads all four literals and fails the build
  if that ordering drifts again, alongside checks that the driver never
  writes to the mapped folder on its own thread, that the staleness watchdog
  arms on the sticky marker, and that the quiet-share filename agrees between
  PowerShell and the Python judge.
- **A broken Gate A evidence channel was reported as a product FAIL.**
  `Host-Launch-Sandbox-Test.ps1` gains a quiet-share detector: no change
  anywhere under `output\` for `-QuietShareMinutes` (default 15) while *its
  own* sandbox VM is alive (by the PIDs the shared-sandbox busy guard already
  records) means the guest-to-host channel is wedged, so it writes
  `HOST-QUIET-SHARE.txt` and exits 4 instead of burning the rest of the
  timeout. Exit 4, not 3: 3 already means "gave up waiting for a busy sandbox
  and never launched", and "never started" is a different condition from
  "started and went dark". `scripts/gate_a_verdict.py` reports such a run as
  `HARNESS_ERROR` (exit 2), never `FAIL` — the second non-verdict alongside
  the existing `BUSY`, and unlike `BUSY` it keeps the full per-check
  breakdown as forensics rather than short-circuiting, since a partially
  shipped run really does carry results. A run whose evidence never reached
  the host supports no conclusion about the candidate.
- **`sandbox-lab/scripts/Watch-Run.ps1` could not be parsed by Windows
  PowerShell 5.1 at all.** A single U+2014 em dash in a double-quoted string
  decodes under 5.1's default ANSI codepage as `â€"`, whose embedded quote
  terminates the string early (5 cascading parse errors). Replaced with
  `--`. Pre-existing since the file was added in `bb00170`; found by the PS
  5.1 AST parse sweep run for the mapped-folder fix above.

- **B2 — a real station could never take a live meeting on air.**
  `civiccast/app.py`'s `_resolve_preflight_evaluator` built the go-on-air
  `PreflightEvaluator` with no `source_probe` at all
  (`PreflightEvaluator(_session_factory)`), so the `live_source` pre-flight
  check fell into `REASON_LIVE_SOURCE_NOT_PROBED` unconditionally and every
  `POST /go-on-air` 409'd — even against a correctly configured RTMP/RTSP/
  SRT/NDI source. The only working `source_probe` in the tree was the
  installer's private System Health rehearsal, which validates a local
  recorded sample file and was never wired into the running service (spec
  §12 station-acceptance: "schedules a day and commits to air; interrupts
  with live and returns safely" — unreachable from the product UI). New
  `civiccast/live/source_probe.py` (`probe_live_source` /
  `build_source_probe`) asks `ffprobe` to open the configured source and
  confirms a real video or audio stream before the station commits to air,
  bounded by `CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS` (default 8s) so
  a hung encoder can't hang the request. `_resolve_preflight_evaluator` now
  wires it in; the installer rehearsal's sample-file probe still overrides
  it per-call via `source_probe_override`, unchanged. A failed probe's
  message now names the source and the concrete failure (e.g. "rtmp source
  'Council Room A RTMP' (room-a-rtmp) ... Connection refused"), which flows
  verbatim into the go-on-air 409's `failed_checks` detail. Credential-
  bearing sources (`LiveSource.credentials_handle`, spec §15's OS
  credential store reference) are not yet resolved by the probe — no
  resolver exists anywhere in this codebase yet; stated as a known
  limitation in the module docstring rather than silently glossed over.
- **Coturn posture (documented external TURN, PR #9) didn't read correctly
  end to end.** `civiccast/installer/contribution_install.py`'s honest
  Windows guidance ("coturn has no native Windows build... point
  `CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT` at a documented external TURN
  server") was correct, but two real gaps kept it from actually reaching an
  operator or doing its job: (1) `civiccast/live/contribution/coprocess.py`'s
  TURN-reachability probe and its unreachable-alert were both gated on a
  LOCAL coturn co-process being `"running"` — which can never happen once
  `CIVICCAST_COTURN_COMMAND` is intentionally left unset, so the probe (and
  the alert) silently never ran under the exact posture PR #9 declared
  supported; `diagnostics()` also always reported the station as unhealthy
  ("one or more co-processes are not running") in that posture, a
  permanent false negative. (2) `ContributionInstallReport`'s
  `coturn_action` guidance text had zero frontend consumer — no screen ever
  fetched `GET /api/staff/installer/remote-contribution`.
  Fixed: the probe now runs whenever a local coturn is up OR none is
  configured at all, `VdoDiagnostics` gained `turn_host`/`turn_port` (the
  effective, currently-configured target) and reports the station healthy
  once TURN is reachable regardless of whether a local process is
  supervised, and a new `POST /api/staff/contribution/diagnostics/turn-test`
  runs an on-demand probe (not the last background poll). The Remote
  Contribution screen's Diagnostics drawer now shows the configured
  TURN target, a **Test TURN connectivity** button (confirm-free since it's
  read-only; loading/success/error states), and a collapsible "How to point
  this station at coturn" section carrying the install report's platform-
  aware guidance verbatim. `docs/USER-MANUAL.md`'s env-var reference for
  `CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT`/`CIVICCAST_COTURN_COMMAND`
  expanded from a one-line stub to the same guidance.
- **GPI / serial control-room device kinds mislabeled as hardware support.**
  `tsr_service/index.mjs`'s `DEVICE_TYPE` map routes `gpi` and `serial`
  `ProductionDevice` kinds through TSR's generic `TCPSEND` adapter — there
  is no GPI contact-closure or RS-232/422 serial hardware driver, and none
  is faked. Labeled honestly everywhere the capability is surfaced:
  `ProductionDevice.kind`'s field description (feeds the OpenAPI schema and
  `docs/API-REFERENCE.md`), the operator console's device-kind picker
  (`ControlRoomSetupScreen`, relabeled "GPI (network relay)" / "Serial
  (network relay)" with an inline note when either is selected, plus the
  `gpi_pulse`/`serial_send` cue-action descriptions), `CAPABILITIES.md`,
  the S18 incumbent-parity spec section's gap-8 status line and detail
  section, and the `civiccast/control_room/`
  package/module docstrings. A station needing real hardware fronts it
  with its own TCP-to-GPI or TCP-to-serial relay box — the existing TCP
  payload path already reaches it. No behavior change (the TCPSEND routing
  was already correct); this closes the honesty gap between what the UI/
  docs implied and what the code does.
- **Two working backend routes had no operator console button.** Both
  `civiccast/captions/router.py`'s offline-caption-job retry
  (`POST /api/staff/captions/offline-jobs/{job_id}/retry`) and
  `civiccast/egress/router.py`'s GStreamer runtime repair
  (`POST /api/staff/egress/repair-gstreamer`) worked end to end but were
  backend-only, flagged in `next-cleanup.md` as waiting on console wiring.
  Added `OfflineCaptionJobsPanel` (`civiccast/apps/portal-operator/src/
  screens/OfflineCaptionJobsPanel.tsx`), mounted as a per-asset drawer
  section in `AssetDetailScreen`, listing offline caption jobs for that
  recording with a `records_clerk`-gated Retry button (confirm, loading,
  success, and per-row error states) on failed jobs. Added
  `GstreamerRepairPanel` to `SystemHealthScreen`'s egress health surface,
  gated on `setup_admin`/`support_admin`, with a confirm dialog and a
  result banner naming the remedy (`already-healthy` /
  `restage-launched` / `installer-missing` / `launch-failed`), the live
  closure-health state, and the re-stage PID when one launched. Both wire
  to the real routes via new `civiccast/apps/portal-operator/src/api/
  client.ts` functions (`listOfflineCaptionJobs`, `retryOfflineCaptionJob`,
  `repairGstreamerRuntime`); vitest coverage in
  `OfflineCaptionJobsPanel.test.tsx` and
  `SystemHealthGstreamerRepair.test.tsx`.
- **PDF agenda import — operator-upload path was a stub.**
  `AgendaService.import_from_doc` (`civiccast/agenda/service.py`) raised
  `NotImplementedError` for any non-`text/plain` upload, so an operator
  uploading a PDF agenda (the common case — municipal agendas ship as PDF,
  not plain text) always hit a 415 with no real parsing behind it. Added a
  heuristic text-layer extractor (`civiccast/agenda/pdf_import.py`, `pypdf`
  — already a repo dependency) that recognizes numbered/lettered items
  (`1.`, `3.a`, `A.`, `IV.`), ALL-CAPS section headings, and standalone
  clock-time markers, and scores each recognized line with a `confidence`
  (new nullable `AgendaItem.confidence` field, migration
  `0078_agenda_item_confidence`). `confidence` is always `None` for
  operator-authored items and exact plain-text imports — only the PDF
  heuristic path produces a score. Because PDF extraction is a guess, not a
  literal transcription, importing PDF items onto an agenda that is
  currently `published` reopens it to `draft` (AI/agenda non-negotiables
  spec §4.2 — operator approval before publish); a PDF with no recognizable
  lines now returns 422 instead of either a 415 or a silently empty import.
  The operator console's agenda screen gained a PDF file-upload control
  alongside the existing paste-text import, a per-item confidence badge in
  the items table, and a published-agenda-will-reopen-to-draft notice.
- **nanoid 3.3.17 → 3.3.18** (GHSA-2v37-7h3g-55p8, high) in both the operator
  console and the public portal.
- **pypdf 6.14.2 → 6.16.1** (PYSEC-2026-3655, PYSEC-2026-3656) — resource
  exhaustion reachable through PDF parsing, which matters because this product
  ingests operator- and contributor-supplied agenda PDFs.
- Non-HTTP control-plane URLs are refused before `urlopen`. The base is
  operator-overridable via `CIVICCAST_CONTROL_PLANE_URL`, so a mis-set value
  could turn a health probe into a local file read whose contents were then
  parsed as a health body.
- Release signing derives its cosign certificate identity from
  `GITHUB_REPOSITORY`. It was hard-coded to the old (private, not archived)
  repository, so verification would have rejected this repository's own
  signatures.
- The GStreamer playout engine's module docstrings no longer claim
  "WSL/Linux-only" — the Windows named-pipe transport ships and its suite runs
  natively.
- **Station timezone now reaches the running service (M3).** First-admin
  setup persisted the operator's chosen `station_timezone` into station-state
  JSON, but nothing propagated it to the running service — S18 daypart
  auto-scheduling silently ran on UTC for every station, corrupting
  scheduling, as-run logs, and program guides for any station not in UTC.
  `civiccast/app.py`'s `_station_tz()` now reads the persisted value (via the
  new `civiccast.installer.station_state.read_station_timezone()`) when
  `CIVICCAST_STATION_TZ` is unset; the env var still works as an explicit
  override.
- **C1 — a fresh station install could never call for help.**
  `civiccast/alerting/evaluator.py`'s dispatch path silently `return`ed with
  no record at all when an `AlertRule` had zero live channels — the exact
  state every migration-`0039`-seeded default rule ships in (an install
  cannot fabricate operator SMTP/SMS/webhook credentials). The alert event
  itself still fired, but the delivery attempt vanished without a trace: no
  suppressed-delivery row, nothing for the deliveries drawer to show, no way
  to tell "nowhere to send it" from "alerting is broken." Fixed to log a
  visible suppressed `AlertEventDelivery` on the no-channel gap (fire and
  resolve paths), per spec §6.2's "never a silent drop" contract.
- **Every fresh native install was dead on arrival — postgres never started
  (Gate A run #4, candidate SHA `8579e66`).** Installer exit 0, activation
  self-test + `station-set.json` written, `CivicCastSupervisor` running as
  LocalSystem — but nothing ever listened on 127.0.0.1:8000 across 20
  minutes / 150 health polls. `supervisor.log` showed a `postgres`
  readiness-budget exhaustion / restart loop; `postgres.log` showed, every
  attempt: `waiting for server to start....The process cannot access the
  file because it is being used by another process. / stopped waiting /
  pg_ctl: could not start server` — no postmaster output ever appeared.
  Root cause: an earlier diagnosability fix (2026-08-12, TESTER2 b5
  evidence) had `postgres_child_spec` pass `pg_ctl start -l
  <child_log_path("postgres")>` while `_file_backed_popen_factory`
  *independently* opened that SAME `postgres.log` path for `pg_ctl`'s own
  inherited stdout/stderr. On Windows, `pg_ctl -l` relaunches through
  `cmd /c "... >> <file> 2>&1"` (`src/bin/pg_ctl/pg_ctl.c`,
  `start_postmaster`); a third process reopening a file the supervisor's own
  process already has open hits `ERROR_SHARING_VIOLATION` deterministically,
  so the postmaster was never spawned — reproduced locally against the real
  `pg_ctl.exe` from the failing Gate A kit (same-file: exit 1, identical
  error text; split-file: exit 0, clean startup). `nats_child_spec` does
  NOT share this defect (`nats-server` opens its own `-l` file directly, no
  `cmd.exe` relaunch) and is unchanged. Fixed via a new
  `ChildSpec.stdio_log_name` field: when `postgres_child_spec` is given a
  `log_path` (its `-l` target), it now points the generic stdio capture at a
  separate `postgres-launcher.log` instead, so nothing ever opens
  `postgres.log` twice. `postgres.log` keeps carrying the durable postmaster
  log at the name operators and tooling already expect.
  `civiccast/native/supervisor/children.py`,
  `civiccast/native/supervisor/service.py`.
- **Gate A could hang indefinitely and gave no diagnosis when the station
  never came up.** A real run (candidate `8579e66`) polled three endpoints
  sequentially at up to 180s each (~9.5 min total), then the in-sandbox
  script hung for 30+ minutes past `t2-render-assert` with no forward
  progress and no `DONE.json` — and the station's own logs (postgres/nats/
  control-plane/supervisor) were never captured, so there was no way to
  tell why the station never listened on `:8000`. `In-Sandbox-Report.ps1`
  now waits on `/api/health` alone with a single bounded 20-minute
  deadline, captures bounded station diagnostics (logs, config, service
  state, listening ports, filtered process list, Event Log) at three
  points including unconditionally at the end, explicitly skips
  T3/T4/T5 the moment the station is confirmed down instead of falling
  through into whatever ran next, and carries a separate-process watchdog
  that force-completes the run after `-MaxScriptMinutes` (default 100) so
  the host can never wait on a zombie. `scripts/gate_a_verdict.py`'s
  `completion` check now gates on a dedicated `harness_completed` flag
  instead of a `last_completed_step` string that could never actually
  match on a real completed run.
- **BUG C2 — the as-run log (the station's legal proof-of-performance
  record) could silently lose entries on a DB hiccup during playout.**
  `civiccast/reporting/asrun_recorder.py`'s `StoreAsRunRecorder` wrote
  every as-run transition straight to the durable `ReportingStore` inside a
  bare `except Exception: log and continue` — a connection drop, a
  disk-full write, or a brief network partition during a source transition
  silently dropped that segment from the franchise-compliance ledger with
  nobody told, the exact failure §12's full-disk scenario and S23's
  "franchise operators must prove what aired" claim exist to prevent. Fixed
  with a durable transactional outbox: every as-run write now journals
  first to a local, fsync'd SQLite file (independent of the app's main DB
  connection) before it ever reaches the real store; an opportunistic drain
  makes the common case behaviorally identical to before, and a store
  failure leaves the row safely journaled instead of dropped, retried every
  `ChannelAutomationService` poll tick until the store recovers. A
  persistent drain failure now raises a visible `asrun-outbox-degraded`
  condition on the existing alert hub instead of only a log line, and
  resolves itself once the backlog clears. Exactly-once via a stable
  per-transition event id plus the store's existing idempotent
  upsert/guarded-update writes; a startup replay drains anything a prior
  crash left mid-drain, so nothing is lost across a crash either. New
  `civiccast/reporting/asrun_outbox.py`; `civiccast/reporting/
  asrun_recorder.py`, `civiccast/egress/automation.py`,
  `civiccast/alerting/models.py` (new `asrun-outbox-degraded`
  `AlertConditionKind`) updated; see `docs/adr/0023-asrun-durable-outbox.md`
  for the full design and rejected alternatives.

### Known gaps

- No per-PR gate on `civiccast/egress/gst/*`. The suite runs natively but needs
  a provisioned runtime tree (`CIVICCAST_GSTREAMER_RUNTIME_ROOT`), which CI does
  not build yet.
- The packager → HLS → real-browser playback path lost its automated gate with
  the Docker cleanroom. The Windows Sandbox harness covers more, on real
  Windows, but is not wired as a CI gate here.
- The Tauri installer still carries an inert WSL2 bootstrap branch in
  `src-tauri/src/main.rs`. It never fires on a native station; removing it is
  tracked separately.

## [1.0.0-rc18] - 2026-08-02

Inherited release identity, recorded here because `civiccast/_version.py` and
this repository's release-identity checks still track it.

`v1.0.0-rc18` is the **WSL line's** published beta. It was built, released and
documented in `scottconverse/civiccast`, not here, and this repository does not
produce it. Its full entry is in that repository's CHANGELOG.

The native product line carries its own separate version in
`civiccast/_native_version.py` -- currently `1.0.0-beta.2`, owner-held and
unpublished. Whether a native-only repository should keep tracking the retired
line's identity at all is an open decision for the owner; until it is made,
both are recorded honestly rather than one being quietly retyped as the other.
