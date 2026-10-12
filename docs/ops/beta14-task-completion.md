# Beta 14 field fixes and delivery

## Authorized scope

Finite engagement: complete the 28 owner goals in
`C:\Users\scott\Desktop\Goals\CIVICCAST GOALS B14.md`, then ship a clean
working Beta 14. The owner also requires initial Windows Sandbox testing
and a final real installation on this machine. Those are separate required
outcomes; earlier Beta 13 results do not prove them.

Base: merged main `3c3ac6ba4a1e185a475a48aa3733a0d1a79a9d1e`.
Branch: `codex/beta14-field-fixes`. Published version remains Beta 13.
No Beta 14 candidate has been built or installed.

The Desktop goal document owns each description, fix and definition of done.
This record tracks execution and evidence without narrowing those criteria.
An uncertain field finding requires diagnosis, rather than a speculative fix
or an assertion that unchanged code proves the field failure still occurs.

## Work and evidence

| Goal | Requirement | State / owner |
| --- | --- | --- |
| 1 | Installer selections control downloads | Focused Rust/frontend checks passed; installation pending |
| 2 | Resolve Whistle assets correctly | Focused runtime checks passed; installation pending |
| 3 | Displayed and loaded model selections agree | Focused API/UI checks passed; installation pending |
| 4 | CPU Whisper fallback deadline | Focused checks passed; candidate installation pending |
| 5 | Caption verification clock alignment | Real offset fixture passed; bundled-runtime installation pending |
| 6 | Truthful caption capacity status | Focused checks passed; generated API synchronized; installation pending |
| 7 | Summary resource protection | Focused admission/unloading/serialization checks passed; integration pending |
| 8 | Actual live-source preflight | Focused checks passed; candidate installation pending |
| 9 | Live-session/output state agreement | Focused API/UI checks passed; integration pending |
| 10 | Recording duration and continuity | Focused boundary/reconnect checks passed; integration pending |
| 11 | UI recording-to-package-to-publish workflow | Focused packaging/UI checks passed; integration pending |
| 12 | Friendly recording-duration validation | Focused form/API checks passed; integration pending |
| 13 | Saved ticker reaches public output | Focused public snapshot/compositor checks passed; integration pending |
| 14 | Bulletin-filler continuity | Focused render-failure containment checks passed; integration pending |
| 15 | Signed-summary PDF wrapping | Focused checks passed; final manual/candidate integration pending |
| 16 | Summary source playback | Focused checks passed; final manual/candidate integration pending |
| 17 | Complete manual PDF clipping correction | Canonical 499-page PDF scan and visual checks passed; candidate artifact scan pending |
| 18 | Help contents navigation | Focused checks passed; final manual/candidate integration pending |
| 19 | Chapter-to-agenda synchronization | Focused checks passed; candidate integration pending |
| 20 | Publish count/filter agreement | Focused checks passed; candidate integration pending |
| 21 | Resident archive navigation | Focused checks passed; candidate integration pending |
| 22 | Schedule refresh and playback transitions | Focused checks passed; candidate integration pending |
| 23 | Translation activity status | Focused persisted-activity/API/UI checks passed; API synchronized; installation pending |
| 24 | Packaged-media trim preview | Focused checks passed; candidate integration pending |
| 25 | Recorded-caption review audio coverage | Review/audio and chunk-bound focused checks passed; integration pending |
| 26 | Supported continuous scheduling and time accounting | Focused checks passed; candidate integration pending |
| 27 | Backup/readiness and local output-proof consistency | Focused readiness/UI checks passed; real proof pending; original failure receipt absent |
| 28 | Actual installation/storage paths | Focused setup/profile checks passed; installation pending |

No row is complete until its own acceptance behavior is demonstrated.
Implementation claims, component checks, actual installation and public
delivery remain distinct evidence layers.

## Delivery requirements

- Consolidate related fixes and independently review their actual behavior.
- Update affected software screens, contextual Help, manual, README, landing
  page, release notes and version identities for Beta 14.
- Include the owner-requested prominent positive 72-hour, three-channel,
  99.78% caption-input coverage result with its actual historical evidence.
- Run an initial exact-candidate installation in Windows Sandbox; no new soak.
- Perform the final real installation on this machine using the completed
  candidate, preserving applicable existing station data and verifying its
  operation. Keep the station running until that installation is ready.
- Publish the verified Beta 14 package, reconcile public downloads/main/Pages
  and the D: kit and installation prompt, and promptly remove redundant owned
  staging while preserving needed release artifacts and evidence.

## Execution controls

Use Luna Extra High for ordinary work and Sol 6.1 Medium for difficult work
or repeated worker mistakes. No DeepSeek. Global compaction configuration
was read back at 260000 tokens. No test theater, invented release gates,
extra scope, elaborate harnesses or extended soaks. Use existing focused
checks and meaningful regressions; consolidate necessary corrections and
preserve signed artifacts when only tests or bookkeeping change.

Caption percentages are reported evidence, not an automatic release veto.
Accurate late captions count as successful under the owner's definition.
Do not add hardware/provider requirements from blocked field checks to this
scope. Preserve unrelated working files and the independent host monitor.

## Initial observations

- Service `CivicCastSupervisor` was Running at task start. C: had about
  407 GiB free; D: about 19 GiB free. No guest or installer was started.
- The saved next-release documentation patch applied to the Beta 14 branch.
  Inspection found that it omitted the current README soak paragraph; that
  paragraph now uses the measured 72-hour result and positive wording too.
  Generated manuals will be synchronized after behavior/source changes settle.
- Caption worker baseline:
  `.venv/Scripts/python.exe -m pytest tests/captions/test_whistle_runtime.py tests/captions/test_review_media.py tests/egress/test_caption_proof.py tests/egress/test_caption_proof_worker.py -q`
  returned `68 passed in 3.35s`.
- Caption-clock tracing found that embedding rebases source times to the
  live transport clock. The correction must use actual accepted delivery
  timing and capture origin; an arbitrary offset chosen to pass comparison
  would not satisfy goal 5.
- Caption worker reports a real offset MPEG-TS fixture passing with matching
  captions (0.000311-second delta) and rejecting wrong text. Integrated
  runtime and candidate results remain pending.
- The recording worker traced excess media duration to capture launching
  during the 30-second arming lead, plus stop handling on the scheduler's
  next tick. Its correction moves capture to the scheduled start and bounds
  capture/reconnect to the remaining recording window.
- Manual source chapters still contained the obsolete 10-second Whistle
  deadline and permanent fallback description. Those affected paragraphs now
  describe automatic recovery, the 30-second primary deadline and the
  configurable 120-second fallback deadline. Generated formats remain pending.
- The caption unit's consolidated affected run passed 259 tests in 39.10s:
  Whistle runtime, review media/router, tap worker, runtime status, caption
  proof/worker, GStreamer caption admission and worker reload acknowledgement.
  Affected Python Ruff checks passed. The fixed-offset transport mapping was
  checked against the exact pinned GStreamer 1.28.5 source. This is component
  evidence; a bundled-runtime installation has not yet run.
- Installer/model evidence is recorded in the workspace receipt
  `outputs/beta14-work/install-model-receipt.md`: six focused Python
  regressions, two Rust selection checks, four installer UI checks and
  90 operator UI checks passed; affected Python lint and portal typecheck
  passed. Python 3.14 fixture teardown warnings required a scoped warning
  filter for those six assertions; this is not an unfiltered-suite pass.
  Existing broad Rust formatting drift was reported and left untouched.
- Model selection now distinguishes the saved choice from the service-start
  live runtime. A differing live fallback tier requires a service restart;
  newly started recorded-caption jobs use the saved choice. The UI explains
  this lifetime rather than claiming an already-created runtime changed.
- Live/recording worker reported 11 source/status checks, five packaging
  checks, 38 recording checks, 23 commissioning/backup checks, 99 operator
  UI checks and four resident-state checks passing. Affected Python lint and
  whitespace checks passed. Some mixed router runs encountered pre-existing
  authentication fixture/environment interference; isolated affected routes
  passed. These results do not establish a full-suite or installation pass.
- Goal 27's original R7/R9 TSDuck failure cannot yet be attributed: the
  pasted reports omit its check-level receipt and the named raw folders are
  absent here. Current UI now displays nested check reasons. The owner was
  asked for raw paths while independent work continues; actual current local
  output verification remains part of candidate installation. The owner
  confirmed on October 12 that no additional field files are available;
  do not ask again or invent an original failure cause.
- Goals 7, 13, 14 and 23 have focused component evidence: 101 Python checks,
  37 AI Models screen checks, TypeScript and affected Ruff checks passed.
  This covers summary memory admission/unloading, ticker propagation, bulletin
  rendering failure containment and persisted translation activity. The worker
  receipt distinguishes filtered fixture warnings and unavailable external
  PostgreSQL from actual assertion results. Candidate installation remains pending.
- Publisher compatibility now includes Beta 14 in the existing physical-host
  receipt contract without restoring a caption-performance veto. A new Beta 14
  regression first failed that policy and then passed; all 16 physical-host
  publisher checks and affected Ruff checks passed. Sandbox proof will be
  recorded separately; a host receipt alone does not claim Sandbox checks.
- Independent Sol review found an actual goal 3 child-process boundary defect:
  the live fallback could inherit the old activation tier despite the verified
  operator selection. The verified explicit model path and tier now cross that
  boundary. The live regression was observed failing, then all 24 runtime-wiring
  checks passed with the documented fixture warning filter; affected lint and
  formatting checks passed. Independent Sol confirmation reran the two batch/live
  cases and returned scoped PASS. Model loading and installation remain pending.
- D: had only 18.94 GiB free, insufficient for the complete offline kit.
  Removed the obsolete owned `D:\CivicCast-Beta11-Documentation-Kit-400cff08`
  after verifying the exact directory and absence of reparse points. Its 19
  files occupied 26,915,294,076 bytes; removal was confirmed and D: had
  47,250,276,352 bytes free afterward. The newer Beta 11, Beta 12/13 kits
  and evidence were preserved. Receipt: `outputs/beta14-work/usb-obsolete-kit-cleanup.json`.

## Consolidated integration checkpoint — October 12

Independent source review returned scoped PASS after correcting the live fallback tier boundary, private-playback import cycle, typed chapter provider and same-URL preview renewal. Exact checks and scope are in `outputs/beta14-work/independent-review.md`. No installer result is implied.

The remaining UI group passed 79 focused operator assertions; actual MPEG-TS trim playback and resident playback-title timing each passed a Chromium check. The production agenda provider and service/router group passed 94 checks. Two existing two-program schedule-loop checks passed, and the manual now contains the supported continuous-rotation recipe and planned/actual-time explanation. Summary citation playback passed two focused UI checks and independent review.

The API/OpenAPI and bundled Help manual were regenerated. All 691 Python source files passed mypy after consolidated mechanical corrections. The full source-built PDF scan, affected Python suite, final candidate build, Sandbox installation, host installation and publication are being completed; those remain required outcomes.

Final canonical manual: 499 pages, 794,753 non-whitespace characters, zero outside-page characters. Representative tables/commands/path samples were visually checked and command spaces retained. Public scan and independent review receipts are under `docs/ops/evidence/`. Consolidated affected Python run: 1087 passed, five stale fixtures failed; corrected fixture selections passed 26 caption/runtime and 29 public-current checks. Both portals build, generated API/Help currentness, release identity, mypy691 and affected Ruff checks pass. No repeat broad suite is required by these fixture corrections.
