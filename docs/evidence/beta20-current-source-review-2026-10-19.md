# Beta 20 current-source review tripwire renewal
## October 27 incoming reload state refusal

`reload_program` previously ignored a false `sync_state_with_parent()` return
and continued activating the incoming leg. A focused regression reproduced that
failure to abort. The loop now raises with the refusing element's name and uses
the existing `build-error` unwind. The test verifies one failure settlement,
retirement of only the incoming elements, preserved outgoing pads/elements,
released incoming holds, and no activation of later elements. The affected
ordering suite passed 129 tests with 2 skips in 2.47 seconds.

This is a proven failure-handling correction, not a diagnosis of historical
run40165319415's incoming filesrc11 stream error. No preserved evidence shows
that run returned a state-sync refusal. Existing incoming bus-error logging
already retains URI-redacted Gst debug detail for a matching recurrence.
Only the engine current-source tripwire is renewed; historical installed and
release evidence is unchanged. Hosted CI and installed testing remain separate.

## October 26 retained caption stream PMT discovery correction

Required Windows121552808917 retained the exact failing TS/worker/decoder log.
Default movie-filter extraction reproduces exit-22 (unspecified video size,
empty pixel format); larger probe/time bounds alone do not fix it. The same
bytes decode with format_opts=scan_all_pmts=1, matching ffprobe's explicit
MPEG-TS default (FFmpeg fftools/ffprobe.c open_input_file). Outgoing caption ends
4.367s; queued old caption ends10.154s before actual switch10.155s; incoming
caption10.888-12.521s is present and delayed stale speech absent. The inline
native-test decoder now selects that demux option; boundary assertions and
product bytes are unchanged. Only its existing source tripwire is renewed.
Signed candidate40317362877/42339334 remains valid; no installer rebuild.

## October 26 static PNG and workflow floor tripwire renewal

Required CI40310373196 Windows job121529748466 passed in13m30s, including
all native media cases and the delayed static-PNG overlay regression. Local
forced200ms admission failed before the indefinite-duration correction (4.83s)
and passed after (4.61s), with logo/banner, continuity and clean teardown checks.
Only static repeat-after-eos PNG buffers receive indefinite duration; live
layer timing is unchanged. Current-source engine and native-test blob bindings
now identify that reviewed correction. The ci-test workflow binding identifies
native collection floor2034/2273 updates retaining the existing50-test margin.
No registered producer node, control, verifier rule or historical acceptance
status changes. Required unit job121529748660 found18 stale-binding assertions
(11783 other tests passed); these source tripwires are renewed without claiming
installed, pre-login, hardware or current external-service acceptance. Those
outcomes remain separate; F4 historical filesrc provenance remains unexplained.



## October 26 caption extraction diagnostic binding

Windows job121419690914 passed the F4 supersession case but failed the F7
caption-boundary proof with empty extracted text. The worker committed and
terminated cleanly; the decoder previously discarded exit status and stderr.
No failed stream was retained, so its exact cause is unresolved. One local
scenario passed25.82s; this does not explain CI. The native test tripwires now
bind decoder status/stderr preservation and failure-only stream/log retention
under the existing caption-worker-failure artifact. No product behavior changed.

## October 25 F6/F7 caption boundary and preview correction

The current-source tripwires for worker, engine, control, audio tap, native test
file and workflow now bind the F6/F7 candidate. Live program changes fence queued
ASR, WAVs, public WebVTT and embedded commands with a program token. The sparse
caption source is replaced at selector handoff and emits CEA-608 erase through
the existing cc_data path. Live cccombiner uses timestamp aggregation without
its optional scheduling FIFO: native packet inspection found the retained FIFO
delayed erase three frames after request-pad replacement. The decoded boundary
regression passed locally in25.33 seconds with continuous TS/audio and incoming
captions. It joins the existing Windows media job; registered producer nodes,
controls and verifier enforcement are unchanged. Existing production-pressure
encoder settings do not decode on the older local probe runtime; this focused
caption proof uses the existing standard encoder settings, not a repaired encoder.

F4 required CI40274379021 failed the superseding scenario: only one replacement
stream became ready; outgoing audio stopped and abort retirement remained blocked.
The abort-only teardown still flushed a connected selector and NULLed before
releasing request pads, unlike the established confirmed-retirement contract.
It now reuses that fenced release-before-NULL path; a focused ordering assertion
checks isolation without any connected flush. Local ordering128pass and the same
native scenario passed15.54 seconds. Required CI must validate this correction.
The historical first-attempt filesrc flow error still has no preserved Gst debug
cause; its log now records URI-redacted detail for a future recurrence. This
structural correction does not claim every historical transient is explained.
These source bindings do not renew historical installed, hardware, pre-login or
release acceptance. Completed required hosted CI remains necessary.

## October 24 checker-integration workflow binding

PR265's collection-floor correction changed only comments and the two native
JUnit minimums: pure 2019 -> 2032 and Windows 2261 -> 2271. Live collection is
2082 pure / 2324 total / 2321 Windows non-integration, retaining the existing
50-test margin. The reviewed diff is `50b4e11..8b3c901` for
`.github/workflows/ci-test.yml`.

The six workflow source tripwires now bind Git blob
`b6713dea345b6cef8e2e62677807dd336813938f`, replacing
`a3462ce42bd0de358a693e2080d5e31a2c06bed2`. Producer jobs, metadata, registered
nodes, controls, result wiring and verifier enforcement are unchanged. No code,
test, fixture or historical evidence binding is renewed by this update.

Run `40158115701` passed the real Windows closure/native job but its unit job
failed because these six workflow bindings had not been updated. That failure
and its downstream claims failure are not passes. Local registry-drift checks
reproduced the six mismatches before rebinding. Completed same-run CI is still
required; local policy tests use their documented synthetic artifact fixtures
and do not establish real producer acceptance. No installed, hardware, pre-login,
release or signing claim is changed.

Focused verification after rebinding: all 125 tests in
`tests/policy/test_claims_evidence.py` passed in 67.49 seconds. This includes
real-registry drift checks and deliberately failing binding/control fixtures;
it is not a completed hosted producer result. `git diff --check` passed.

## October 20 final-candidate CI reconciliation

Signed source `34e213fec46fa69245822dc29ebb269d251e29a3` retains build run
`39411797489`; the following test, workflow and evidence corrections do not change
its application or installer inputs. Its Windows WS4 job `118591350196` passed
the actual native/media suites. Required overall CI and installed acceptance
remain separate, pending outcomes.

Informational randomized job `118591165152` reported 21 failures: two handback
callback stubs rejected the new `handoff_at` keyword; one watchdog fixture assumed
that an expired boundary would never request immediate termination; two native
collection/floor assertions omitted the added portable closure-baseline case; and 16
policy failures reflected the eight stale bindings and their derived checks.
The handback stub now checks that the explicit boundary falls within the actual
handback call. The pinned-worker fixture ignores the initial termination request,
asserts that it occurred, and then permits watchdog termination. This preserves
the watchdog recovery assertions without reverting the corrected boundary behavior.
Collection expectations are 2,030 pure and 2,272 total; the Windows floor is
2,219 for 2,269 non-integration cases, preserving the existing 50-case margin.

The six workflow tripwires bind the reviewed floor correction and failure-artifact
upload addition. Producer identity, registered nodes, controls, result wiring and
verification requirements are unchanged. The two GStreamer test-file tripwires
bind the production-pressure fixture's use of the actual station encoder helper;
their registered continuity and teardown test bodies are unchanged. The real WS4
pass supports this source review, not a new installed or historical acceptance
claim. Claim wording, historical evidence dates, verifier and control enforcement
are unchanged; completed same-run producer evidence is still required.

Permanently informational mutation job `118591165379` stopped at the logging-storm
timing check: best supervised 3.10 seconds versus DEVNULL 2.45 seconds at the 1.10x
bound, after 4,052 passes. This is a recorded nonblocking timing failure; no bound
was relaxed and no production change is inferred from it.

Local reconciliation checks passed: 42 handback/watchdog/native-workflow policy
cases, 141 claims-evidence/retraction cases, focused Ruff lint/format and diff
checks. These are source checks, not completed hosted CI or installed acceptance.

On October 19, 2026, a focused review at source `c6be85b7b165d43b75f6cc124f26ae918e5830d2` found nine deterministic claims-bookkeeping drifts: six registered workflow blobs, two current-source `engine.py` blobs, and one workflow job missing from the contract inventory. This note records the limited review and registry correction. It does not change historical acceptance evidence.

The workflow review compared the recorded binding with `.github/workflows/ci-test.yml` at this source. The current workflow adds isolated PostgreSQL caption coverage and its JUnit upload, pinned Windows media and installer dependencies with explicit no-skip checks, a longer Windows timeout, and the `external-integration` job. It replaces an obsolete Linux-engine coverage-gap comment with the native coverage. The `test` producer, producer metadata, registered test nodes and controls, claims-verifier `needs`, and result wiring remain in place. The six workflow tripwires therefore bind current workflow source; the cancelled producer's test evidence is still required from a completed same-run CI.

The contract inventory now includes `external-integration` as a real workflow job, alongside the existing `windows-native` non-producer. Neither is a claims producer. `expected_producers`, the verifier's `needs`, and the workflow result wiring remain unchanged.

The two current-source `engine.py` tripwires now bind blob `c7e9039dcf385fd9cfb57122c15b4932a01905a9`. The reviewed delta is the aborted-reload descendant snapshot and attribution correction documented in the focused Windows reload diagnosis and independent source review. The old Windows-native job from run `39204762080` succeeded against source `267b463501f6188aef7296d064503c87aaccde8d`, whose `engine.py` blob is the same `c7e9039dcf385fd9cfb57122c15b4932a01905a9`: its retained JUnit had 2,260 native cases, 35 installer cases, and 56 media cases, with zero failures, errors, or skips. It included `test_build_play_teardown_clean` and `test_superseding_a_held_deferred_reload_keeps_the_current_program_on_air` as passing.

That old run's `test` producer was cancelled, so the run is not a full green claims result. Its missing `test-junit` artifact does not establish that registered tests or controls failed or disappeared. The successful Windows-native evidence supports review of the exact engine blob only; it cannot replace same-run producer evidence or establish current installed-service, hardware-spike, or pre-login acceptance. Historical evidence dates, claim wording, and stated limitations remain unchanged. The inert external-resolution control remains inert, and D2 blob-drift enforcement remains active.

## Options and recommendation

Ignoring the old run's violations would leave nine deterministic current-source drift failures. Blindly replacing hashes, weakening the verifier, or inferring a producer pass from unrelated artifacts would misstate the evidence. The narrow correction is to inventory the real non-producer job and renew only the six workflow and two engine source tripwires after the focused review above. This is the recommended path; it preserves historical acceptance and leaves completed same-run CI as a separate requirement.

The signed candidate workflow `39208157501` at `c6be85b7b165d43b75f6cc124f26ae918e5830d2` is preserved. This documentation and registry-only follow-up does not alter its signed bytes and does not re-label them as built from a later source revision. Current-candidate claims acceptance remains pending successful same-run producer metadata, JUnit, bound-node and control evaluation.

## Completed-run bookkeeping follow-up

CI run `39208155850` for c6be85b7 completed with 28 unit failures: 18 claims-binding failures, three strategy test-setup failures, and seven documentation/policy failures. Its Windows job passed 2,265 native, 35 installer, and 56 media cases without failures, errors, or skips. This is scoped Windows evidence, not a successful overall CI run or installed acceptance.

The recommended follow-up preserves public Beta 19 download defaults and the signed c6be85b7 candidate. Three control-channel tests explicitly disable hardware encoder probing at their fake worker boundary; their original control assertions remain. Documentation tests now check the authored candidate/published sections and installed-edition guidance instead of obsolete sentences or table layout. The architecture reference describes the default timestamp as a deterministic local token rather than an authority-issued RFC 3161 timestamp. Native collection expectations are 2,033 pure and 2,268 total; executed non-integration Windows cases are 2,265. Floors 1,983 and 2,215 preserve the existing 50-case margin. Six workflow blob bindings follow that reviewed floor-only workflow delta; historical claim wording and acceptance dates are unchanged.

Tracked manual PDF/DOCX bytes were reused from the successful exact-source manual job in signed-build run `39208157501`. Its receipt binds source `c6be85b7b165d43b75f6cc124f26ae918e5830d2`, unchanged Markdown SHA-256 `d73aed3ffbbb967e69f8a7324ac2585f19273dbdffea10c72ace249c9477de54`, and both output hashes. Only manifest artifact paths were remapped to `docs/`; the generated documents were not changed or regenerated. The source/header/artifact check passed.

Keeping stale expectations would preserve known false failures. Pointing downloads at unpublished Beta 20, weakening drift/floor checks, removing timestamp limitations, or rebuilding the installer solely for this bookkeeping would either misrepresent availability/evidence or add unnecessary work. These narrow corrections preserve the intended constraints and leave full CI and installed acceptance as separate requirements.

Focused results: the three strategy cases failed before the fixture correction and passed afterward. The seven documentation/policy failures and related adoption negative controls passed (10 cases). A broader local Windows strategy-module run hit 20 other real-GStreamer registry failures in the unprovisioned development environment; it is not a full-module pass. No application, installer, manual Markdown, or candidate-producing workflow changes are part of this follow-up.

## Native platform-marker follow-up

CI run `39214715724` on `01e87d0c2e94fc40da8e37cd70dc1ee64a2fd063` passed the main pytest run (11,675 passed, 103 skipped, 5 deselected), the Windows job, and optional integration. The dedicated native pure run had 2,029 passes and four skips; its no-skip guard correctly rejected four Windows ACL/DPAPI cases lacking the `windows_only` marker. Add that existing marker while retaining runtime skip guards and all assertions. This preserves Windows execution, excludes those four from the Linux pure selection, and keeps portable private-file cases. Weakening the no-skip guard or removing runtime guards would conceal the classification error; neither was selected.

The corrected exact collection is 2,029 pure / 2,268 total, with 2,265 Windows non-integration cases. Unchanged floors 1,983 / 2,215 leave margins 46 / 50 within the existing 50-case allowance. Four focused collection/workflow policy checks passed, and touched-file Ruff passed. This is collection/metadata proof; the next hosted native pure execution remains required. No workflow or claim binding changed.

The Windows mypy error for the guarded POSIX `os.fchmod` call was corrected separately by a line-specific annotation in `aa49d3df0cc4c30d26fe7c4ab577c996e19f9c13`. Windows and Linux type checks passed; independent marshaled-code comparison proved identical compiled code including line tables. The signed c6be85b7 kit is preserved. Local kit verification and guest transfer passed; replacement installation is running, with functional acceptance still pending.

## Service-profile junction follow-up

Revision 4b85a2b CI 39219234054 subsequently passed all jobs. The signed c6be85b7 kit passed local and guest verification but its installation failed registration 70; automatic restoration returned the guest to a healthy prior installation, and five API collection hashes matched before/after. A controlled registration diagnostic on that restored installation reproduced 70: identity migration rejected the profile's Content.IE5 junction to INetCache/IE. No fixture creator was established.

The correction skips redirected descendants during recursive permission updates, uses bounded native handles without recursive propagation, preserves protected DACL state and unrelated ACEs, and rejects redirected roots/ancestors. Nonrecursive root grants retain normal inheritance; actual Windows probes show the junction object may inherit an ACE while the redirected target remains unchanged. This avoids both deleting a cache compatibility junction and narrowing existing service access. Ancestor rechecks are not atomic against concurrent replacement; no broader race-proof claim is made.

The actual Windows regression failed before the fix; all 14 affected tests pass afterward, including 2 new junction cases proving external-target ACL preservation, ordinary inheritance, protected children, and root rejection. Ruff and focused Windows mypy pass. Independent source review found no concrete blocker. Native count/floor policies correctly failed on the added cases before reconciliation: 2029 pure / 2270 total / 2267 non-integration. The Windows floor advances from 2215 to 2217; six workflow bindings follow that floor/comment-only workflow change. Historical evidence claims remain historical. New signed and installed acceptance is still required.

## Running-image permission correction

Signed 7ad7b44d build 39224848934 and CI 39224839230 both succeeded. The verified kit's isolated install failed registration 70 with measured setup exit 118; recovery restored the prior guest healthy. All five API record hashes remained unchanged. No acceptance claim attaches to 7ad.

The exact candidate identity module, invoked through the restored installed interpreter, failed CreateFile error 32 on its loaded runtime/_asyncio.pyd. Invoking that module from outside the installation passed. A separate probe opening its own running executable failed with MAXIMUM_ALLOWED and succeeded with READ_CONTROL|WRITE_DAC. These captured reproductions establish the file-access defect; the missing original installer stderr was not recovered.

Recommendation implemented: retain MAXIMUM_ALLOWED for recursive directories to suppress automatic propagation; request only READ_CONTROL|WRITE_DAC for files. Skipping locked files would omit required permissions; changing every handle would alter directory propagation. The fix preserves final-handle reparse checking, checks that the object type did not change before opening, and leaves root-only inheritance and protected ACL behavior intact.

The new Windows regression launches a copied Python executable inside the grant tree: witnessed RED with error 32, GREEN with the fix; all 15 affected tests pass. Independent source review found no material issue. A corrected-source overlay (SHA256 5377d9c2d93046e0f5246d2330c26a7dcce5145fb272a84258fb48ba2e942b75) passed the guest identity operation through the installed interpreter; service restarted healthy. This is diagnostic source proof, not a signed-installer pass. Windows mypy and two native count/floor policies pass. Collection is 2029 pure / 2271 total / 2268 Windows non-integration; floor 2218 retains the 50-case Windows margin. Six workflow bindings track that delta without changing historical claims.

Five-lens review: engineering reproductions bind the actual loaded-image failure; UX behavior is installer registration without a new operator control; tests execute a real in-tree interpreter and retain junction/inheritance assertions; changelog and handoff distinguish source proof from candidate acceptance; QA retains the failed candidate and recovery evidence. README, Help and API contracts are unaffected by this internal access correction. Corrected exact-source signing and installed acceptance remain required; no publication or host operation is authorized by this evidence.

The affected claims-evidence/retraction suites also passed (141 tests); touched-file Ruff and diff whitespace checks passed. Guest post-diagnostic inventory again matches all five pre-install record hashes.

## Virtual-environment regression fixture follow-up

Windows job 118022447733 in CI 39241285128 completed with 2267 passes and one failure: the copied interpreter was a virtual-environment launcher, which exited106 with `No pyvenv.cfg file` before exercising the ACL function. Fix the fixture, not the product: copy `sys._base_executable`, retain adjacent Python DLLs, expose the installed pywin32 support-DLL directory, and assert the child interpreter resides inside the tested tree. The project virtual-environment run now passes all 15 tests; a temporary child-only forced-MAXIMUM_ALLOWED probe still fails with CreateFile error 32. Ruff and whitespace checks pass. Root reviewed the diff independently of the worker; there are no production-code or candidate-workflow changes.

The public Legistar live integration also disconnected once; the exact live test passed locally afterward. Fresh CI includes that integration, so the queued old-job-only retry was cancelled before submission. Superseding the old CI via the normal concurrency policy avoids completing a known-failed run before starting the necessary corrected one. Do not claim the unfinished old unit job passed.

Five-lens review: engineering and tests preserve actual in-tree execution and sensitivity; UX/API/Help are unaffected; handoff/evidence explain test-only provenance; QA preserves signed source 8717c2a2 and its running build 39241295587. No signed rebuild or release-readiness claim follows from this correction.

## Installer working-directory registration failure

Signed8717c2a2/run39241295587 and CI191ee02c/run39243436914 passed their workflows; complete local kit verification passed. Exact isolated installation failed registration70/setup118. Automatic recovery returned0 at October19 06:57:57MDT; prior guest was healthy/Running/Auto on schema0094. All five APIcollection hashes matched preinstall. This does not prove raw-media preservation or installed acceptance.

Exact candidate identity-module diagnostics passed from an external cwd, as did full restored-bootstrap registration with that candidate module, with and without the installer transaction environment. Changing only the registration process cwd to the installation root reproduced70/CreateFile32 in the root permission walk. A local independent probe reproduced the same directory-sharing conflict. Pinned TauriCLI2.11.2 sets OUTDIR=INSTDIR before POSTINSTALL; original installer stderr was not retained, so the evidence is a controlled reproduction plus template/source tracing, not recovery of its original traceback.

Recommendation: release the installer parent's current-directory handle and let the child inherit a scratch cwd by temporarily setting OUTDIR=PLUGINSDIR around registration. Restore OUTDIR and preserve exit status before existing branching. Keep the permission algorithm unchanged; changing directory handle access would alter automatic ACL propagation. Capture bounded child output in the persistent log for silent-install diagnosis. The focused compiled NSIS regression passed for child exits0/70, verifying cwd separation, restored file output, and preserved status; all47 affected hook tests passed. Independent source review found no blocker. A new signed candidate and actual installation are still required. Host and all nine goal requirements remain unchanged.

Five-lens integration review: engineering traced parent/child cwd and preserved exit handling; UX now points to captured diagnostic output without promising a complete traceback; tests witnessed the cwd regression fail, then47 cases passed including compiled success/failure paths; documentation and PR distinguish old-candidate recovery from pending acceptance; QA retains the failed kit and does not infer installation success from diagnostics. Artifact-state review found no readiness claim; original payload/signing evidence remains historical. Focused Ruff and diff checks pass. README, Help and API contracts are unaffected by this internal installer correction; no credentials or environment values are added to the diagnostic log.

## Installed rapid-reload lifecycle correction

Exact signed source51c886874ea7eeb53457604c1a0ce9689312f543 passed build39257884570 and CI39257879140. The verified kit installed successfully in the isolated guest: setup0, service registration0, healthy schema0094. Five API collection hashes matched preinstall. Initial playlists and segments returned200 for all three channels. These resolve the prior installer failure, not full station acceptance.

The actual committed three-channel run failed: two queued reloads restarted fallback slate, but stale pending-reload and deliberate-kill state remained attached to the replacement worker. The next poll labeled it TRANSITIONING, preventing the slate-replan path from dispatching due programs. Captures completed; the inspected government frame shows slate and caption VTTs contain no cues.

The correction clears the departed worker's reload pin, kill markers and watchdog state at a genuine fresh start, after the live-worker no-op guard. Abandoned held prepared plans are released; a plan explicitly supplied to the start remains owned by it. Polling inside the reload caller risks additional restart handling, while waiting for the watchdog misses airtime; cleanup at the existing fresh-start boundary is the focused choice.

Baseline daemon suite:209 passed. Before the change, two regression assertions failed (incorrect TRANSITIONING and unreleased abandoned plan); live-worker preservation passed. Afterward, all212 daemon cases passed, including queued distinct reload commands and prepared-plan ownership. Root independently reran the three new cases (3 passed,209 deselected) and the existing slate-replan class (3 passed). Attempts to start another independent reviewer failed at the agent thread limit; the parent performed a fresh serial review of the worker's diff and checks. This is source-level evidence, not installed recovery proof. Exact commands and full output remain in the workspace transition-diagnostic evidence directory.

README, Help and API contracts are unchanged: this restores scheduled playout behavior without a new control or contract. Changelog and handoff record the defect and remaining acceptance. Historical claims bindings are unchanged because daemon.py is not one of their bound source files. A corrected signed kit and real three-channel run remain required; all nine outcomes and the no-reboot host constraint remain active.

## CG approval correction

Installed51c evidence: real BBC RSS fetched32 items HTTP200; URL-ID approval returned404. Options: preserve native IDs with a path converter (minimal compatible correction); hash IDs (breaks existing approval keys); add a body endpoint (unnecessary contract expansion). Selected the path converter. The client already percent-encodes the ID; the unchanged service checks channel/feed ownership and the route still requires a write role.

Worker baseline19 passed; sensitive focused RED4 failed/1 passed; focused GREEN5 passed/17 deselected; full tests/cg/test_board_api.py22 passed. Independent source_review found no route collision or concrete blocker. The actual BBC case uses unmodified TestClient routing. Only the synthetic literal-percent case adapts TestClient raw_path decoding to match the real ASGI contract; no application-side unquote was added.

Parent checks: scripts/generate-openapi-artifacts.py --check exit0 (no generated changes), scoped Ruff exit0. Source/test evidence and independent review are under workspace outputs/replacement-candidate-51c88687/vm-check/cg-confirmation. Those checks concern uncommitted changes atop fe7dc1df, not the unchanged fe7 signed artifact. Installed acceptance is pending.

Five-lens review: engineering PASS (single route converter, unchanged identity/auth checks); UX PASS (existing Approve workflow restored, no new copy); tests PASS (sensitive failure and exact-ID/403/service404 assertions); docs PASS (CHANGELOG/HANDOFF/evidence updated, API artifact check unchanged, no new operator steps); QA PASS for this source correction (no installed or release-readiness claim). Artifact-state remains pending exact resulting SHA/CI/build propagation after push. No ledger closure or publication is claimed.
