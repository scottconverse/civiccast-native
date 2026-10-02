# CHECKPOINT - Blackwell beta.8 caption-runtime fix (2026-09-16)

Resume point. Do NOT treat as final. Task is NOT complete.

## Repo state
- Worktree: C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native
- Branch: fix/blackwell-caption-runtime
- Candidate base: 41ec3dda7f5c5cf678e815ac103fd7e99d85294f
- HEAD commit: 71096432fad3649b0e038febe498118019624079 (DCO signed)
- UNCOMMITTED (on top of HEAD): civiccast/egress/gst/control.py + tests/egress/test_gst_strategy.py
  (the PTS rebase change + its tests; NOT yet committed, NOT live-validated)
- Also staged in installed runtime (matches source): tap_worker.py, daemon.py,
  automation.py, app.py, gst/control.py, native/station_runtime.py
- station_runtime.py was REVERTED to candidate earlier (claim withdrawn).

## Fixes on the branch
1. KEEP, regression-proven: session-boundary sidecar reset
   (tap_worker.begin_channel_session + daemon channel_start_hook + automation/app wiring).
   RED: 2 failed on candidate. GREEN: 2 passed.
2. KEEP but NOT ACCEPTED (no live success): gst/control.py
   align_live_caption_pts_ms rebase bound MAX_LIVE_CAPTION_FUTURE_LEAD_MS=30000.
   RED: candidate returns 3132120 for a 3132120ms cue at 90s running time.
   GREEN: patched returns 90250. Necessary-but-not-sufficient.
3. REVERTED: native/station_runtime.py validator change (claim was FALSE).

## Live evidence obtained (GPU)
- Runtime: device=cuda compute=float16 on_cuda=True, RTX 5070 Ti 16303 MiB.
- Two live captions-ON runs on public channel, weather program, ON_AIR:
  Run A 23:17Z cue "And thats the way thunderstorms in the summer are."
  Run B 23:51Z cue "For Friday, continued chance of convection."
  Both runtime within-capacity. BOTH decode-back: expected 1, decoded 0.
- Preserved artifacts: work/paired-20260916T232254Z/, work/pts-20260916T235105Z/,
  work/long-20260916T235132Z/ (18s live UDP capture, 244 GA94 markers).

## Decoder-vs-payload question (CURRENT)
- 18s capture has 244 GA94 SEI, only 2 DISTINCT payload bodies:
    0354fffc 8080 fd8080 fa0000...  (x170) null padding
    0354fffc 942c fd8080 fa0000...  (x74) non-padding
- CEA-608 data bytes: 8080->0000 pad; 942c->14 2c (0x14 = CONTROL code, 0x2c=",");
  fd80->7d 00 ("}"). => emitted SEI carries control/style + stray punctuation, NO TEXT.
- ffmpeg sees NO caption stream in TS; readeia608 clean; ffmpeg-subcc empty.
- BREAKTHROUGH this turn: drove appsrc->tttocea608->ccconverter directly with known
  text and CAPTURED 80 buffers with REAL characters (fc464f="FO", fc5220="R ").
  => tttocea608 encoder WORKS. So the live push path feeds it wrong/emptily.
- NEXT DIAGNOSTIC: compare engine.push_caption_cue buffer construction vs the working
  probe. Prime suspect: buffer missing capsframe/timestamp semantics OR the live appsrc
  buffer lacks Gst.Buffer pts/duration validity, OR the caption text never arrives
  (feed _sent dedup marking cues seen after a False ack, or window/ack mismatch).
  Check worker.py line ~277 caption dispatch and engine.push_caption_cue around line 1019.

## Auth/service cleanup state
- service Environment value: ABSENT (restored).
- machine CIVICAST_STAFF_TOKENS + FALLBACK: empty.
- blackwell-validator DB token rows: REVOKED (2 rows).
- validation operator-console tokens: REMOVED (back to original 19).
- work/.op-token.tmp and .op2.tmp: REDACTED.
- CivicCastSupervisor: must verify Running + /api/health healthy (was Running/healthy).
- public channel: STOPPED (stopped this turn).

## Remaining acceptance items
- Prove live captions reach emitted TS text (decode-back with actual TEXT).
- Isolate + fix the live text-delivery defect; add meaningful regression RED/GREEN.
- Installed-runtime correspondence for EVERY changed file (currently True for 6 files).
- DCO-signed commit on the dedicated branch.
- Exact-candidate release gates (per handoff: focused tests, ruff, format, mypy, DCO).
- Final durable report + SHA-256 manifest, repository-relative.
- If live text still cannot be produced: explicit BLOCKED verdict + revert or mark
  the PTS change unaccepted with the exact evidence boundary.

---

## UPDATE after compaction request (resume here)

### Tree now unambiguous
- Unstaged the revert no-ops. Working-tree diff vs candidate 41ec3dda is exactly 8 files:
    civiccast/app.py                                  (+8/-1)
    civiccast/captions/tap_worker.py                  (+22)
    civiccast/egress/automation.py                    (+3)
    civiccast/egress/daemon.py                        (+4)
    civiccast/egress/gst/control.py                   (+45/-5)   <-- PTS rebase, uncommitted
    tests/captions/test_caption_tap_worker.py         (+35)
    tests/egress/test_daemon.py                       (+25)
    tests/egress/test_gst_strategy.py                 (+35)     <-- uncommitted
  station_runtime.py is EXACTLY candidate (no diff) - revert confirmed.

### NEW BREAKTHROUGH: the encoder is PROVEN GOOD
Ran tttocea608 directly through bundled GI (how to reach it):
    os.environ["CIVICCAST_GSTREAMER_RUNTIME_ROOT"] = r"C:\Program Files\CivicCast (Native)\runtime"
    sys.path.insert(0, r"C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages")
    from civiccast.native.gstreamer_runtime import bootstrap_installed_gstreamer_runtime
    bootstrap_installed_gstreamer_runtime()
    import gi; gi.require_version("Gst","1.0"); from gi.repository import Gst, GLib
  (GStreamer 1.28.5; NO gst-launch.exe shipped - only gst-inspect/gst-discoverer.
   gi lives at runtime\dependencies\gstreamer\python\gi)

Pipeline appsrc -> tttocea608(pop-on) -> ccconverter -> capsfilter(x-cea-708) -> fakesink,
probe on capsfilter src, push UTF-8 text buffer with pts/duration:
  "For Friday, continued chance of convection."   -> 80 buffers, chars present
     (fc46ef etc.)
  "FOR FRIDAY, CONTINUED CHANCE OF CONVECTION."   -> 80 buffers
     first payloads: fc464f("FO"), fc5220("R "), fc4652, fc49c4...
  "HELLO WORLD"                                   -> 94 buffers
  => tttocea608 + ccconverter CORRECTLY encode text to CEA-708 cc_data on this box.

### The live-emitted payload (18 s capture, work/long-20260916T235132Z/capture.ts)
244 GA94 SEI, only 2 distinct bodies:
   x170  0354fffc 8080 fd8080 fa0000...   (null padding)
   x74   0354fffc 942c fd8080 fa0000...   (non-padding)
CEA-608 data decode: 942c -> 14 2c  (0x14 = CONTROL code, 0x2c = ",")
Note the encoder's own preamble in the probe is fc9420/fc94ae/fc9470; the live body
shows 942c = a 0x14-class CONTROL pair, NOT a text character pair. NO text characters
appear anywhere in the live capture.

### Therefore (bounded conclusion so far)
Encoder = GOOD. Emitted payload carries only control/padding, no text. So either:
  (a) the feed never delivers the cue text to appsrc (dedup/ack/delivery path), or
  (b) the cue is delivered but scheduled outside the captured window (PTS), or
  (c) the caption leg in the RUNNING pipeline is not the live leg that is being pushed to.

### FIRST NEXT DIAGNOSTIC after resume (do these in order)
1. Verify which caption_embed leg the RUNNING worker actually built. Check the channel
   playout-graph.json written at start (C:\ProgramData\CivicCast\data\egress\public\
   playout-graph.json) - confirm graph.captions is the live appsrc leg and that
   appsrc name == "captionsrc" as the engine looks up (LIVE_CAPTION_APPSRC_NAME).
2. Confirm the feed is actually CALLING send_caption_cue. Cheap, decisive: the feed
   marks a cue sent ONLY on a True ack (caption_feed.run_once adds page to
   acknowledged_pages only when send returns True). Instrument/log or read
   gst-worker stdout for the "caption" control command arriving. If the worker never
   receives `caption <pts> <dur> <b64>`, this is a FEED/WINDOW problem, not insertion.
3. Check worker pipe ack: worker.py ~line 277 returns "error","no live caption source"
   when engine.caption_appsrc is None. If that ack is being returned, the pipeline has
   no live caption source => graph built without the live leg.
4. If (1)-(3) show delivery is fine, test the PTS hypothesis directly: compare
   engine._pipeline_running_time_ms() vs the aligned PTS at push time, and confirm the
   cue lands inside the 6 s proof window.

### Then
- Add a meaningful regression for whichever hop is broken (RED before, GREEN after).
- Make the scoped fix. Re-run live CUDA/float16 cue + contemporaneous TS/VTT +
  TEXT decode-back. Only then commit.
- If live text still cannot be produced: explicit BLOCKED verdict; keep the PTS change
  clearly UNACCEPTED (or revert it) with the exact evidence boundary.

### Cleanup state (verify again on resume)
- service Environment ABSENT; machine CIVICAST_STAFF_TOKENS + FALLBACK empty.
- blackwell-validator DB rows REVOKED. Validation operator-console tokens removed (19 left).
- work/.op-token.tmp and work/.op2.tmp REDACTED.
- CivicCastSupervisor RUNNING; /api/health healthy; public channel STOPPED.

---

## ROOT CAUSE FOUND (2026-09-17) - stabilizer bucket geometry

### Reproduced deterministically
Real tap geometry: 5 s segments + 4 s overlap = 9 s ASR windows advancing 5 s.
CaptionStabilizer() defaults: window_seconds=4.0, stable_windows=2.

Trace of 5 real-shaped windows:
  win0 start=0  bucket=0 pending=1 committed=0 expired=0
  win1 start=5  bucket=1 pending=2 committed=0 expired=0
  win2 start=10 bucket=2 pending=2 committed=0 expired=1
  win3 start=15 bucket=3 pending=2 committed=0 expired=2
  win4 start=20 bucket=5 pending=2 committed=0 expired=3
  TOTAL committed = 0

Each window advances 5 s, landing in a DIFFERENT 4 s bucket, so:
- _matching_pending (exact text + |start delta| <= 4 s) never matches,
- _revision_candidate (>=0.5 overlap of the SHORTER span) also misses for
  consecutive windows,
- so every hypothesis becomes a fresh pending cue and expires 8 s later.
=> Continuous live speech commits ZERO cues; active.vtt stays empty; nothing
   reaches the emitted stream (A/53 null padding only).

### Verified against the live machine
- ASR on real captured segments: device=cuda/float16, RTF 0.05-0.30, GOOD text
  (e.g. "Dewpoints in Arizona. We're in the 40s and 30s.").
- Live tap processed 960+ chunks; runtime within-capacity; active.vtt = 7 bytes.
- Emitted 18 s UDP capture: 244 GA94 SEI, only 2 distinct payloads, CEA-608 data
  bytes 0000 (padding) and 0x14-control/0x2c; NO text characters.

### Safety contracts that MUST NOT be broken (existing tests)
- test_changed_hypothesis_resets_stability_count: a CHANGED transcript resets the
  count (a wrong first reading must not be confirmed by a different second one).
- test_expired_pending_is_counted_and_routed_never_silently_dropped: an
  unconfirmed stale cue must NEVER be committed/air.
So the fix must make real overlapping speech reach stable_windows WITHOUT
loosening either contract.

### Attempted fixes REVERTED (both broke a safety contract)
1. Committing stale pending on expiry -> violated "never commit unconfirmed".
2. stable_count += 1 on revision -> violated "changed hypothesis resets count".
Both reverted; civiccast/captions/stabilize.py is currently EXACTLY candidate.

### Next fix direction (not yet implemented)
The tap's overlap (4 s) is smaller than the stabilizer window (4 s) relative to
the 5 s advance, so windows never align. Candidate approaches, each needing its
own RED/GREEN and a check against both safety contracts:
  (a) make the LIVE stabilizer's window_seconds track the tap's segment advance
      (>= segment_seconds) so consecutive speech windows can re-confirm, or
  (b) have the tap emit the SAME window's text twice / align chunk starts, or
  (c) treat a genuinely overlapping window as continued speech ONLY when the
      overlap is high AND the text is a prefix/superset (still resets on a true
      correction like carries->failed).
Prefer the smallest change that keeps both safety tests green and produces a
committed cue for the real 5 s-advance/9 s-window geometry.

---

## CONCLUSION (2026-09-17) - live cue loss is a CONSTRUCTIVE mismatch, by design

### Proven chain
1. GPU runtime is correct: device=cuda/float16, ASR text good, RTF 0.05-0.30.
2. Delivery is correct: worker acks caption commands "applied" (verified live).
3. Encoder is correct: appsrc->tttocea608->ccconverter->cccombiner->h264ccinserter
   ->TS->ffmpeg-subcc decodes "HELLO LIVE CIVICCAST" end-to-end (verified).
4. THE BREAK: cues never reach active.vtt, because the stabilizer requires the
   SAME normalized text twice within window_seconds=4.0, while the live tap
   produces 9 s windows (5 s segment + 4 s overlap) ADVANCING 5 s. Two different
   audio windows over continuous speech do not transcribe to identical text, so
   _matching_pending never matches, stable_windows=2 is never reached, and every
   pending cue expires. active.vtt stays 7 bytes; emitted TS carries only A/53
   null padding.

### Reproduced deterministically with real text and real geometry
  win0 start=0  bucket=0 pending=1 committed=0 expired=0
  win1 start=5  bucket=1 pending=2 committed=0 expired=0
  win2 start=10 bucket=2 pending=2 committed=0 expired=1
  win3 start=15 bucket=3 pending=2 committed=0 expired=2
  win4 start=20 bucket=5 pending=2 committed=0 expired=3
  TOTAL committed = 0

### Why the obvious fixes were REJECTED
Three scoped attempts each broke a DOCUMENTED safety contract, so all were
reverted (civiccast/captions/stabilize.py is EXACTLY candidate):
  a) commit stale pending on expiry -> broke
     test_expired_pending_is_counted_and_routed_never_silently_dropped
     ("unconfirmed stale cue must never air").
  b) stable_count += 1 on revision -> broke
     test_changed_hypothesis_resets_stability_count
     ("a wrong first reading must not be confirmed by a different second one").
  c) word-containment continuation rule -> broke
     test_end_of_stream_without_flush_commits_nothing AND the flush test, which
     assert that "Council meeting will come to order." -> "will come to order."
     must STAY PENDING (continuation inference is explicitly out of scope).
Also measured: text similarity CANNOT separate continuation from correction
(real consecutive windows 0.11-0.46 vs "motion carries"->"motion failed" 0.33),
so a similarity threshold is not a valid lever either.

### Assessment
This is a genuine DESIGN/IMPLEMENTATION gap, not a simple bug: the live tap
geometry (5 s + 4 s overlap, 5 s advance) is constructively incompatible with the
live stabilizer's exact-repeat contract (4 s window, 2 confirmations), and the
existing tests encode that exact-repeat contract ON PURPOSE. Deciding the right
resolution is an owner/design decision (options: change tap overlap/advance so
the same audio is re-transcribed identically; make the live stabilizer confirm on
a time-overlap basis with its own contract; or revisit stable_windows for live).
It must NOT be resolved by weakening the two safety tests.

### State
- Tree: 8 files vs candidate (5 source, 3 test) - the session-reset fix, the PTS
  rebase fix (uncommitted), and their tests. station_runtime.py == candidate.
- All 6 installed runtime files hash-match source.
- Live acceptance (text decode-back) NOT achieved.
- Auth/service cleanup done: service Environment absent, machine staff vars
  empty, blackwell-validator rows revoked, validation console tokens removed,
  scratch tokens redacted; supervisor Running/healthy; public channel stopped.

---

## UPDATE 2026-09-17 - stable_windows=1 candidate WITHDRAWN; second blocker found

### Withdrawn (per monitor correction)
CaptionTapWorker(stable_windows=1) was rejected as a THRESHOLD RELAXATION
(BLACKWELL-CODER-START-HERE.md line 32 forbids that) because it removes live
re-confirmation rather than preserving its guarantee. Reverted:
  civiccast/captions/tap_worker.py            -> candidate
  tests/captions/test_caption_tap_worker.py   -> candidate
  tests/native/test_caption_stabilizer_flush.py -> candidate
Nothing was installed or claimed from that build.

### SECOND, mechanical blocker found (not a threshold issue)
The stabilizer's _matching_pending requires |prev.start - curr.start| <=
window_seconds. The tap stamps start = index * segment_seconds = index * 5.0, so
consecutive chunks are exactly 5.0 s apart while window_seconds defaults to 4.0.
Proof: with BYTE-IDENTICAL text and starts 5.0 s apart, ZERO cues commit;
with the same identical text 2.0 s apart, a cue DOES commit. So even a perfect
repeat is rejected purely by the 5.0 vs 4.0 geometry mismatch.

Aligning window_seconds to the tap advance (5.0) does make the identical-text
case commit and keeps BOTH safety contracts green (changed-text reset;
unconfirmed never airs). BUT measured against 6 REAL transcribed segments:
  default window=4.0  -> committed_cues=0 review_rows=0
  aligned window=5.0  -> committed_cues=0 review_rows=0
because real ASR does not emit identical text twice for overlapping windows.

### Therefore
Two independent obstacles block live captions, and neither is a threshold tweak:
  (1) the tap advances 5.0 s per chunk while the stabilizer matches within 4.0 s
      (a genuine off-by-geometry defect), and
  (2) the stabilizer's confirmation rule is exact-text equality, which continuous
      speech never satisfies across differing ASR windows.
A real source fix needs a LIVE-SPECIFIC confirmation mechanism with an explicit
safety contract that still (a) resets on a changed transcript and (b) never airs
an unconfirmed stale cue - e.g. confirming a cue when a SUBSEQUENT window's
overlapping audio region agrees, using the tap's known window geometry rather
than text equality. That is the direction to implement next; it is in-scope
caption-runtime work, not an owner decision and not a budget stop.

### Current tree (candidate-relative)
Only the session-reset fix and the PTS rebase fix remain:
  civiccast/app.py, captions/tap_worker.py(session reset only), egress/daemon.py,
  egress/automation.py, egress/gst/control.py + tests/egress/test_daemon.py,
  tests/egress/test_gst_strategy.py
station_runtime.py == candidate. stabilize.py == candidate.
Installed runtime: all 6 files hash-match source (previous stage); the withdrawn
stable_windows=1 build was NOT installed.


---

## FINAL STATUS (2026-09-17) - LIVE ACCEPTANCE PASSED

- HEAD: 9a97efa5e3c2128bb55740f948629c4077228122 (DCO signed) on
  fix/blackwell-caption-runtime, candidate base 41ec3dda.
- LIVE ACCEPTANCE PASSED: Public channel ON_AIR on the real Beta7 Sample 3 Weather
  program with runtime device=cuda / compute_type=float16 / on_cuda=True.
  active.vtt = 22 fresh real-speech cues; contemporaneous 150 s TS preserved;
  bounded 20 s decode-back recovered 32 caption entries with real text matching
  the sidecar.
- Evidence dir: work/accept-20260917/ (capture.ts, active.vtt, decodeback-20s.srt,
  playout-graph.json, evidence-manifest.json).
- Human report: work/BLACKWELL-CAPTION-FIX-REPORT-v4.md.
- Gates: ruff check PASS, ruff format --check PASS (1433 files), git diff --check
  clean, focused tests 627 passed / 7 skipped, RED-before 4 failed -> GREEN-after
  pass.
- Installed runtime correspondence: all 7 changed modules hash-match source.
- Auth cleanup VERIFIED: service env absent, machine staff vars empty, DB temp
  staff token rows 0, operator-console tokens restored to 19, scratch tokens
  deleted, supervisor Running + /api/health healthy.
- Not done (out of scope): PR/merge/tag/CI changes.


---

## 2026-09-17 - OVERLOAD CAUSE MEASURED (Phase 1 complete)

Objective (owner + auditor): finish beta.8 captions ON / Blackwell GPU. Contract-preserving fix only.
Do NOT relax max_backlog_segments=2 or the 120s fail-closed. Do NOT edit the six safety tests to fit.

### HEAD / state at Phase 0
- HEAD 2a34d0e3, branch fix/blackwell-caption-runtime, 12 commits after 41ec3dda
- baseline tests/captions: 323 passed, 1 skipped
- supervisor PID 6696 Running, /api/health 200

### MEASURED cost of one enforce_discovered() on this host
- _refresh_system_capacity           0.00s
- _discover_candidates (TOTAL)       4.78s   <-- DOMINANT
    - SHA-256 of 6,747 processed chunk-*.wav   1.01s
    - SHA-256 of unclassified evidence WAVs    0.19s
    - review-store list() + per-row get_audio_evidence()  ~3.5s remainder  <-- PRIME SUSPECT
- enforce(candidates) 8,105 candidates  0.83s
TOTAL ~4.1-5.6s per sweep.

### WHY THIS CAUSES THE OVERLOAD (mechanism, from measured numbers)
- segments arrive every 5.0s; tap scans every 2.0s
- ONE sweep blocks the caption tap thread for ~5s (>2 scan intervals)
- during the block ~1-2 settled segments accumulate
- backlog gate then sees len(segments) > 2 -> _fail_closed_overload
  -> 120s PAUSE + VTT CLEARED + audio discarded, with ZERO ASR attempted
- warm ASR is 0.11s/segment, so the tap could clear that backlog in <0.3s
=> the overload is SELF-INFLICTED by retention cleanup running on the caption
   critical path. max-2 is not wrong; it is being fed a backlog cleanup created.

### Code sites (retention.py)
- enforce_discovered -> _discover_candidates (line ~238)
- line ~304: glob every */captions/evidence/*.wav and _sha256 each
- line ~322-340: glob every <channel>/processed/chunk-*.wav and _sha256 each
- _sweep_retention called at the TOP of run_once (tap_worker.py ~589), BEFORE the
  gate at ~628 and before prepare_runtime at ~672.

### NEXT (Phase 2)
Smallest effective fix that keeps max-2 + 120s fail-closed intact, e.g. take
retention off the caption-critical path (own thread/cadence) or make discovery
incremental. RED test must reproduce cleanup latency -> false overload; GREEN must
show cleanup cannot starve caption processing while real >2 backlog still fails closed.


---

## 2026-09-17 - OVERLOAD ROOT CAUSES (two, both fixed)

HEAD now 572a02e2. Scoped fix commits on top of 41ec3dda:
  71096432, 6c668ff5, 9a97efa5, da805246, 05f628d7, fd07be5e, 6891d385,
  194386a7, 57c626ee, 182581c1, 1b9be268, 7d6474d6, 223? (retention fail-closed),
  907df5c0, d7ca7b4d, 572a02e2.

### Cause 1 (FIXED, 7d6474d6/0223f6be/d7ca7b4d): retention cleanup on the caption path
- enforce_discovered MEASURED 4.1-5.6s; _discover_candidates 4.78s (SHA of 6,747
  chunks 1.01s + evidence 0.19s; ~3.5s review-store lookups, MODELED not measured);
  enforce 0.83s over 8,105 candidates.
- ran INLINE at the top of run_once on the caption thread, before the backlog gate.
- Fix: sweep WORK on its own thread; first sweep stays synchronous so the verdict
  precedes ASR; later sweeps async. max_backlog_segments=2 and the 120s fail-closed
  are UNCHANGED. Verdict is fail-closed on unknown/failed/refused, atomic under a
  lock, and recovers on the next successful sweep. Scan loop joins the sweep on
  exit (bounded 10s). No overlapping sweep is reachable: _retention_in_flight gates
  dispatch (verified by deleting the guard branch and re-running).

### Cause 2 (FIXED, 572a02e2): leftover segments inherited at session start
- PID 10588 started 04:21:47, overloaded 04:22:15 while public was FALLBACK_SLATE.
- 4 SETTLED segments left by the PREVIOUS broadcast were counted as backlog and
  fail-closed 120s before any new audio existed.
- begin_channel_session reset sidecar/worker/backoff but NOT the chunk files.
- Fix: discard ALL leftover chunks at session start (raw enumeration, since
  _settled_segments omits the newest for live-scan safety).

### accept5 (exploratory, NOT acceptance)
- capture start 04:23:01; START 04:23:34 (capture-before-enable ESTABLISHED, 33s)
- real session overload at 04:22:15 (28s after process start) -> within-capacity
  by 04:24:05; first cue 04:24:12; grew to 26+ cues over ~4 min, backlog 1.
- controlled stop 04:29:39 / start 04:29:54 -> cue count 0 then 0->8 by 04:32:09,
  within-capacity, backlog 1. (Recovery observed; capture had ENDED 04:28:28, so
  the controlled phase is NOT covered by the TS -> needs a fresh run.)
- PRESERVED: active.vtt (28 cues, 3351B), active-postrecovery.vtt (22 cues),
  capture.ts (~39.5MB), run-timeline.jsonl, PREDECLARED-CRITERIA.json.
- NOTE: VTT timestamps are MEDIA PTS (e.g. 10:43:46), NOT Mountain wall clock.

### Evidence-hygiene lessons (repeated mistakes to avoid)
- git stash push restores HEAD; it is NOT a pre-fix baseline. Use an isolated
  worktree at the exact pre-fix commit (cc-prefix-2a34d0e3) for RED proof.
- git diff --check must run on the COMMITTED RANGE, not the worktree.
- Verify a RED by reverting the fix and confirming the test FAILS for the right
  reason (not AttributeError / not the test's own join masking the behavior).
- Test doubles must delegate, not swallow nested policies.

### NEXT
Definitive run per PREDECLARED-CRITERIA.json (amended): fresh controlled recovery
cycle, ONE capture started BEFORE stop/start, running THROUGH the whole
post-recovery window, preserving the FIRST post-recovery cue, then decode-back
with the 6-consecutive-word matching rule.
