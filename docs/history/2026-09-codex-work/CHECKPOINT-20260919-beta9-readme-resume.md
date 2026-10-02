# CHECKPOINT — 2026-09-19 ~15:30 MT — beta.9 README shortfalls + LPM library + rung state

PURPOSE: durable resume point before compaction. Written by the coder session.
Repo: C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native

================================================================
## 1. ONE-LINE STATUS
================================================================
beta.9 is approved by Scott to SHIP AS "close enough" on the condition that its
shortfalls are written into the user-facing docs. The shortfalls text is WRITTEN
into README.md (uncommitted) — BUT the installer does NOT ship README.md, so the
write-up currently reaches no operator. A decision is pending (see S6).

================================================================
## 2. GIT / TREE STATE (verified)
================================================================
- Branch: fix/caption-phase-timing
- HEAD: df3b3f69dcf1d2f8e5fe531430980a084f8453de
- main: 41ec3dda (per local ref; the beta.9 candidate was built from b1f165bb on main)
- Tracked changes: ONLY ` M README.md` (+50 lines, docs-only)
- Untracked: 809 files (all scratch/evidence — do NOT blanket-add, do NOT delete)
- Nothing committed/staged/tagged/pushed this segment.

Branch commit roles (this session, all author+signoff = Scott Converse <scott@civiccast.org>):
- 12c1498c  fix(captions): isolate one channel's publish failure from the scan pass
- 73e4d124  feat(captions): instrument the overload ladder
- df3b3f69  test(captions): resolve the backoff-contract xfail on live evidence
- (43faca1e, b7a7c869, e8631746, b508c821, etc. are earlier on the branch)

================================================================
## 3. WHAT WAS DONE THIS SEGMENT
================================================================
A. RUNG (parked): 8h caption rung opened 08:44:19 MT on the staged runtime.
   - The scheduled test programming RAN OUT at 10:38:13 MT (last published item
     ended exactly then; zero published items remain). So the rung's meaningful
     speech stretch was 08:44:19 -> 10:38:13 (~1h54m). THE 8H RUNG IS NOT PASSED
     and cannot be claimed. "No trips after 10:20" = nothing-to-caption.
   - It is now an END-OF-SCHEDULE BEHAVIOUR WATCH, not a duration soak. 25h/72h
     rungs are MOOT (no speech; scheduling is not ours).
   - Watchers armed (12 python procs): burst_watch_8h, vtt_shrink_watch,
     event_recorder_8h, trip_ledger_8h, hires_arrivals, trip_sequence_8h.
     Evidence in C:\CivicCastTester\soak-beta9-20260918\.
   - Station now (last check 15:00): government + education egress STOPPED,
     public idle 7 B, all on slate, schedule exhausted; /api/health still 200
     (monitoring gap — health does not reflect egress state).
B. MARK REPORTS (delivered, NOT committed):
   C:\CivicCastTester\soak-beta9-20260918\CIVICCAST-BETA9-8H-RUNG-HUMAN-REPORT-v1.md
   ...v2.md (additive; bimodal settle {3:62,7:60}; exit family {0,1,5};
   snapshot-hash semantics; coordinator's settlement-elevation error recorded)
   EVIDENCE-MANIFEST-v1.json (hashes; jsonl streams snapshot-hashed)
   BETA10-LIST-ADOPTED.md (coordinator-set order)
C. LPM TEST LIBRARY BUILT (download-and-characterise task, complete):
   C:\Users\scott\Desktop\LPM-test-library — 80 media files, 45.25 GB (< 125 GB cap)
     shows 53 (43.68 GB) / bumpers 12 (0.17) / format-samples 6 (0.79) / podcasts 9 (0.62)
   LPM-LIBRARY-MANIFEST.json (per-file codec/res/fps/bitrate); READMEs in podcasts\ and format-samples\
   Codec mix: h264 55, audio-only 9, av1 9, vp9 7 (vp9/av1 = pre-existing old-bestvideo items + 2 deliberate AV1)
   FORMAT PRE-TEST (sanctioned staff ingest, NO scheduling): h264 PASS, AV1 PASS,
     vertical PASS, AUDIO-ONLY MP3 -> REJECT 422 "No video stream detected.
     CivicCast only accepts video files."
   RSS/podcast-feed ingest: NO (only the CG feed fetcher, which renders text/graphics;
     no enclosure/media ingest). NOT to appear in any write-up (withdrawn by coordinator).

================================================================
## 4. THE FOUR CONFIRMED DEFECTS + SECOND MECHANISM (record)
================================================================
- Publish blast-radius (WinError 5 aborting the pass): FIXED unit-level 12c1498c, NOT live-verified.
- Ladder escalation INERT: rung>0 = 0 across both logs; pre-staging 20:43-20:53 cluster
  showed government/public re-tripping 4x in 10 min, all "overload #1". ALARMING, not benign.
- Gate blackout ~210 s/trip (120 s pause + ~90 s recovery bar), NOT 120 s.
- Reload-timeout -> worker restart blackouts: 2.3 / 2.8 / 4.6 min. Exit family = {0,1,5};
  clean exits (code 0) occur in BOTH ON_AIR and slate.
- End-of-schedule: daemon.py:183/:2354/:2357/:2465 — designed EOS path + bounded relaunch
  (max 1) -> STOPPED with a MISLEADING "check the program's media" message when the schedule
  is simply empty. Predicate keys on relaunch COUNT, not WHY it failed.
- Monitoring gap: /api/health 200 while a channel cannot air.
- Decode-back: no working proof exists; caption-proof worker fails on some cue timings.
- Second mechanism (gate trips): cause UNPROVEN. Alignment reading n=1 discriminating
  (10:20:18 edu+public trip, offsets 0.60/0.78/3.48 s). Phase structure: edu+public are a
  phase-PAIRED group (~0.15 s apart); government is an outlier (~2.1 s away). Measured over
  hundreds of cycles, not n=1. Trip prediction stays n=1.

================================================================
## 5. THE README EDIT (uncommitted) — exact state
================================================================
File: C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native\README.md
Inserted at lines 187-234 (new ### "Known limitations of this build (v1.0.0-beta.9)"),
under the existing "## Honestly scoped as beta / roadmap — not done" (line 180).
Content: beta.10 sentence + practical advice at top; then caption reliability (2ch clean ~5.3 s
0 trips; 3ch pre-fix 4+ trips/106 s spike, not GPU; 30-min 0 trips vs 111/103min; sustained NOT
proven 2/4/8/25/72h not completed); program-change interruptions (2.3/2.8/4.6 min; clean exit 0;
ladder never escalates; ~210 s per trip); end-of-schedule STOPPED + misleading message; health
endpoint gap; no decode-back proof. No softeners. All measured numbers.
git diff: README.md | 50 ++++++ (1 file, 50 insertions). Nothing else tracked changed.

================================================================
## 6. *** THE OPEN DECISION (Scott's) ***
================================================================
The README write-up does NOT reach an installing operator as-is:
- The kit (kit-staging\b1f165bb... and RELEASE-CANDIDATE-beta9) ships the installer +
  packs\ + station\ + QUICKSTART-OPERATOR.md — NOT README.md.
- The INSTALLED app (C:\Program Files\CivicCast (Native)\) contains NO README / QUICKSTART / docs.
- The operator doc that DOES ship next to the installer is docs/QUICKSTART-OPERATOR.md
  (co-located by native-beta-candidate-artifacts.yml:1427-1432).
=> Committing README.md to main and rebuilding beta.9 would NOT deliver the write-up to operators,
   because README.md is not in the shipped payload.

OPTIONS FOR SCOTT:
  A. Put the shortfalls into docs/QUICKSTART-OPERATOR.md (the shipped operator doc), commit to main,
     rebuild beta.9 -> new signed installer, new SHA-256, re-secure durable copy, RE-VERIFY the
     installer embeds it. Real cost: new build + new hash; current signed installer superseded.
  B. Leave it on the branch for beta.10; note that beta.9 shipped WITHOUT the write-up.
  Recommendation: A — but ONLY if the text goes into QUICKSTART-OPERATOR.md (the doc that actually
  ships), not README.md. Verify the installer's QUICKSTART content after rebuild.
DO NOT act on A or B without Scott's explicit choice.

================================================================
## 7. FIRST ACTIONS ON RESUME
================================================================
1. Await Scott's A/B decision on S6. Do NOT rebuild or commit anything before it.
2. If A: move the shortfalls text into docs/QUICKSTART-OPERATOR.md (keep README.md edit or mirror
   it per Scott's preference), commit docs-only with DCO (author+signoff = Scott Converse
   <scott@civiccast.com>), get onto main, re-run native-beta-candidate-artifacts (self-hosted,
   upload flags FALSE), then IMMEDIATELY copy the installer to the workflow-immune path before any
   prune, and verify QUICKSTART-OPERATOR.md in the kit carries the shortfalls.
   PRUNE HAZARD: every native-beta-candidate-artifacts run auto-dispatches Gate A, whose cleanup
   prunes candidates\ and kit-staging\ to {its sha + baseline sha}. Durable = RELEASE-* dirs.
3. If B: note in the beta.9 release record that the write-up is deferred to beta.10.
4. Keep the end-of-schedule watch running; report only on new trips/clears/exits/STOP or unhealthy.
5. Standing absolutes: NO deletions anywhere; no repins; no ffmpeg/GStreamer/caption-runtime
   changes; no publish/tag/merge; no CPU substitution; no unrelated GPU kill; no security/ACL/
   Defender changes; do not blanket-add or delete work/; nothing committed without Scott's word.

================================================================
## 8. KEY PATHS / ARTIFACTS
================================================================
Repo:            C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native
Rung evidence:   C:\CivicCastTester\soak-beta9-20260918\        (reports v1/v2, manifest, event/shrink/arrival ledgers)
Signed candidate:C:\CivicCastTester\RELEASE-CANDIDATE-beta9\CivicCast (Native)_1.0.0-beta.9_x64-setup.exe (0.23 GB, sha 927da3d2...)
Beta.5 baseline: C:\CivicCastTester\RELEASE-BASELINE-beta5-148c8d21\  (~20.5 GB, keep)
Shipped kit doc: docs/QUICKSTART-OPERATOR.md  (in repo) -> kit root QUICKSTART-OPERATOR.md
LPM library:     C:\Users\scott\Desktop\LPM-test-library\      (80 files, 45.25 GB)
Disk cleanup advice given (NOT executed): ~300 GB reclaimable in CivicCastTester caches/builds;
  Tier-0 keep = the beta.9 installer + beta.5 baseline; confirm Actions runner idle before deleting candidates\ / kit-staging\.
