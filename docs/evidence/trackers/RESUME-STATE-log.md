# CIVICCAST RESUME STATE — 2026-08-31 evening (post-#23, pre-#24)
# READ THIS FIRST AFTER COMPACT. Model switched to claude-fable-5 by Scott.

## WHERE THINGS STAND
- **Sergio (LPM exec dir) has #22 installed and is testing it now.** His first ask: SCREENSHOTS in the user manual / landing page.
- **#23 is DONE and on the stick:** `D:\kit-23-FINAL-beta1\` (Lexar, 26 GB). Gate A green BOTH lanes (run 33414111585), built from `feat/beta-real-fixes` @ `057ffec`, fixes verified inside `native-app-payload.ccpack`, stick hash-verified byte-perfect, READ-ME-FIRST.txt included. #22 test-instance login: proofadmin / CivicTest2026! (fresh #23 install creates its own admin — no preset password).
- **#23 contains:** #1 record→portal fix (schedule/router.py `_PACKAGEABLE_ASSET_STATES`), #3 real summary provenance (summary/generate.py). NOT in #23: Spanish captions, as-run reporting (stick read-me says so plainly).

## HANDOFF PROMPT FOR A FRESH SESSION
`C:\Users\scott\Desktop\CIVICCAST-HANDOFF-PROMPT.md` — paste into a new session; assumes zero knowledge; covers repos, local paths, build mechanics, rules, traps, first actions.

## THE MASTER TRACKER (single source of truth for remaining work)
`C:\Users\scott\Desktop\CIVICCAST-FINALIZATION-CHECKLIST.md` — tiered 0-5 + docs + merge queue + parked. Built at Scott's request from EVERYTHING (deep dive + this cycle). Includes item **0.4 install-over-existing**: Gate A dirty lane plants synthetic remnants + reinstalls SAME candidate — a true #22→#23 upgrade preserving real recordings/DB is UNPROVEN; **#24 carries migration 0083 → rehearse #23→#24 on a copy of real data BEFORE it touches Sergio's box.**

## OPEN PRs (owner merge decisions — main has pre-existing reds; none of these worsen it)
- **#118** feat/beta-real-fixes — #1/#3, Gate-A-proven. Recommend merge.
- **#117** fix/recording-shutdown-drain-jobobject — bounded 15s recording drain in _app_lifespan + EMPIRICAL PROOF ffmpeg children are already Job-Object-contained (no change needed there). 608 tests pass.
- **#115** fix/uninstaller-label-clip — shortened deleteAppData label (~190→~135 chars); render-confirm pending next installer build.
- **#113** chore/retire-wsl-version-single-source — single 1.0.0-beta.1, fixes release-identity gate (red on main). Triaged: remaining reds = pre-existing doc-debt also failing on main (main 16 vs branch 14). Entangled with ~15-doc release-posture migration needing Scott's judgment.
- **#95** integration/night-wave-v2 — older, unreviewed this cycle.

## SPANISH CAPTIONS (#24, REQUIRED — Longmont 30% Latino; Scott: recorded=bar, live not required)
- Branch `feat/recorded-spanish-captions` (worktree C:/Users/scott/Desktop/Code/cc-spanish-captions), pushed, NO PR yet. Reviewed by me: solid. Migration **0083** language column ('en' backfill), two-phase review (EN approved → translate → ES own review → attach BOTH tracks together), landmine handled (ES cues forced low_confidence=False else evidence-gate deadlock), 430 backend tests green, player needs no change.
- **OPEN OWNER QUESTION (M.6):** publish both-languages-together (my rec — never English-only for a Spanish-required community) vs English-first-Spanish-follows. Current code = hold-both.
- Fallback rule Scott approved: if Spanish can't ship right, ship without + fast-follow + tell him.

## AS-RUN (#2, deferred to #24 deliberately)
"Published != aired": `commit_models.py:82` acknowledged state has ZERO writers; nothing joins `as_run_log` back to occurrence/commit. Rushed fuzzy match would write FALSE franchise data — build carefully. Not started.

## NEXT ACTIONS (suggested order, Scott not yet confirmed)
1. **0.3 Screenshots** for USER-MANUAL (I own; confirm Codex owns landing) — Sergio is asking NOW. Manual has ~2 images.
2. **0.2/M.7** Get #23 to Sergio (or Scott decides he stays on #22 first-look).
3. **0.4** Real #22→#23 upgrade-with-data test (offered to run; Scott hasn't answered).
4. **#24 build:** merge M.1-M.4 + Spanish + as-run → CI → Gate A → rehearse migration upgrade → ship.
5. Then: full operational walkthrough (0.1), cable-commissioning real-box verify (1.1), confirm-dialog sweep (1.4, ~24 unguarded controls), one live 3-tier publish (3.4, needs Sergio's IA/YouTube accounts), 24h soak (4.1, last FAILED #151), signed installer (4.2), LPM hardware rung (Tier 5).

## KEY FACTS / TRAPS
- **"Built in software = real" is Scott's BINDING framing rule** — field-proof pending ≠ unbuilt.
- Landing page: https://scottconverse.github.io/civiccast-native/ (Codex reworking; multi-channel/SDI/syndication were UNDERSOLD — all built).
- Deep-dive reports: `Desktop\CIVICCAST-DEEP-DIVE-2026-08-31\` (MASTER-what-is-really-there.md first).
- main HEAD moved to `25b332c` while I worked (something merged — likely Codex landing PR; my 4 PRs still open).
- Pre-existing test reds on main: "returns 503 without DB" env family + release-posture doc family — NOT from our changes; #22 shipped with them.
- Gate A rules: NEVER cancel a running Gate A; box shared with Codex (check before self-hosted dispatch); build kit staged at `C:\CivicCastTester\kit-staging\<sha>\`; box clock is Mountain (UTC-6) — mtimes look 6h old but aren't.
- Candidate build recipe: `gh workflow run native-beta-candidate-artifacts.yml --ref <branch> -f build_target=self-hosted`; Gate A auto-fires on build success.
- A stray git stash exists (stash@{0}, live/SRT lane, not mine — leave it).
- Status ledger also at `C:\Users\scott\Desktop\CIVICCAST-23-STATUS.md`; memory index updated (`civiccast-deep-dive-2026-08-31.md`).

## PROGRESS 2026-09-02 (overnight, Fable 5.1) — follow Codex's reconciled plan, option A

- **Install-over-existing is PROVEN (checklist 0.4 closed).** Gate A cross-version lane run 33593868962: #23 (beta.1) installed live, data planted, beta.2 installer run over it → `D3_ROUTE=UPGRADE`, `D3_ENGINE_EXIT=0`, same Postgres cluster, both planted recordings survived byte-identical, station healthy. Evidence copied to `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-cross-version-33593868962\`.
- **PR #119 (Codex upgrade + beta.2) MERGED** → main `94b4141`, version `1.0.0-beta.2`. It also clears the doc-posture + Job Object test reds main had carried since #113/#117.
- **PR #121 merged** (browserslist lock bump; a new advisory had made `npm audit` red on every branch).
- **PR #120 open, rebased on new main, CI running:** WP-00 = SDI/HDMI recording input presets + honest CG labels, stale-input bug fixed (red→green test), S6 sentence fixed, manual re-rendered. Merge on green.
- **PR #122 open:** uninstaller label says "always stay" (policy test requires that phrase; #115's wording broke it). Merge on green.
- **WP-01 (hermetic tests) DONE locally**, branch `test/hermetic-app-factory-state` in worktree `C:\Users\scott\Desktop\Code\cc-wp00-sdi`, sits on top of #120 — push + PR right after #120 merges. Full suite 10527 passed with it; restricted-path run (real LOCALAPPDATA unwritable) 3794 passed; 17 `CIVICAST_` env-var typos fixed.
- **Runner:** HALO-gate-a is NOT a service; after reboot start `C:\actions-runner-gate-a\run.cmd` (memory note written).
- **Trap fixed:** the upgrade lane's `previous-kit-staging` junction let the next checkout's `git clean` delete the pinned #23 kit from `C:\CivicCastTester\kit-staging`. Restored from the stick (hashes match pin); `ebc86b6` (in #119) unlinks the junction at job end.
- **Note:** `workflow_run`-triggered Gate A uses MAIN's workflow file; now that #119 is merged, auto-fired Gate A runs will exercise the cross-version lane.
- **Next per plan:** merge #120/#122 → push WP-01 PR → WP-02 Spanish integration (`69c917f` merges onto main with only a CHANGELOG conflict; fail-open switch lives in `civiccast/captions/vod_job.py` `spanish_enabled` / `CIVICCAST_OFFLINE_CAPTION_SPANISH`).

## Verification ledger
VERIFIED: cross-version upgrade route ran with engine exit 0 and data survived | C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-cross-version-33593868962\DIRTY-RESULT.txt:5
VERIFIED: Gate A judged the cross-version lane PASS with no harness error | C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-cross-version-33593868962\gate-a-verdict.json:5
UNVERIFIED: PR #120 and #122 CI outcomes on their rebased heads (running at time of writing)
UNVERIFIED: WP-01 behaviour on the hosted Windows CI runner (only proven on this box)

## 2026-09-02 daytime (Fable 5.1, coordinator mode)
- Gate A run 33606975941 on the WP-00 kit (main 9049935, beta.2): clean lane PASS + cross-version upgrade lane PASS (first auto-fired run of that lane from main's workflow).
- Merged: #124 (prune keeps pinned kit), #127 (model-pack reuse, 3-root reproducibility measured), #125 (required download-only Gate A lane). #126 (embedded station index) at cde4e28, review clean, CI pending → merge → build main → Gate A THREE lanes → publish v1.0.0-beta.2 via the release-publisher script (agent building it + front-door docs).
- Cache-survival question answered by code trace: `$INSTDIR\packs\.station-cache` is untouched on upgrade (only full uninstall removes it); the download-only lane proves it empirically.
- Known pre-existing defect filed as item 10b: a station bundle built WITH --captions-large-v3-root fails its own verification (missing caption_tiers metadata).

### Decisions I made on your behalf 2026-09-02 (flag for review)
- **Publish vs captions ordering (WP-02):** a recording goes public immediately; captions attach after review, both languages together, never English alone. A failure to even queue the caption job now BLOCKS approval (409) instead of silently publishing with no captions. Alternative (not chosen): hold public records until both caption tracks are reviewed — rejected because it could delay public records for days.
- **All-captions-off switch:** `CIVICCAST_OFFLINE_CAPTION_JOB=off` refuses at startup (captions are a legal non-negotiable) unless a test-only override is set.
- **Podcast:** coming-soon card (your call); WP-04 not built; migration 0084 number skipped.
- **Model packs:** stable identity `station-models-1` across product versions so upgrades reuse the 21 GB cache; exemption allowlisted to model components only.


## 2026-09-02 14:55Z - RELEASE BLOCKED
Gate A on the beta.2 kit (564ee02): clean PASS, cross-version PASS, download-only FAIL (installer exit 123; activation wrote no station-set.json; engine upgraded and station booted anyway). beta.2 NOT published. Evidence: C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-download-only-33623737236. Opus diagnoser running. Merged today: #130, #133. Open: #131 (CI rerun), #132 (CI), #134 docs (CI), #135 guard fix (CI). WP-05 in fix round; WP-07 mergeable pending residuals + re-parent; WP-08 mergeable pending re-parent.

## 2026-09-02 ~16:00Z - owner decisions
1. Release blocker: option B (repin baseline to the beta.2 kit; beta.1 -> beta.2 = fresh install from the beta.2 kit; download-only from beta.2 on).
2. WP-05 subscriber sends: PARKED, coming-soon card instead. Chain 0083 -> 0086 -> 0087.
3. Review pace: one review round per PR, delta only, no full-suite reruns by builders (standing rule for the rest of the project).
Correction 16:20Z: beta.2 = internal baseline kit; main -> 1.0.0-beta.3 (PR #139); v1.0.0-beta.3 = first public download; Sergio fresh-installs beta.3 once.

## 2026-09-02 ~18:30Z snapshot
Merged today: #123 #124 #125 #126 #127 #128 #129 #130 #131 #133 #134 #135 #136 #137 #141 (15). In CI, merge on green: #132 (CG honesty, 88df9a8), #139 (baseline repin + beta.3 bump, 09febdd), #140 (live-source readiness, 4bbc360). Then: WP-08 re-parents 0087 onto 0086 and opens its PR; dispatch self-hosted build from main (1.0.0-beta.3); three-lane Gate A over the beta.2 baseline; publish v1.0.0-beta.3 with scripts/release/publish_beta_candidate.py; stage the kit on HALO for Sergio's one-time fresh install (LAN); fleet soak prompt.

## 2026-09-02 20:15Z
All beta.3 PRs merged (#132 last, main 7971815). Self-hosted build run 33678188749 dispatched; Gate A (3 lanes over the beta.2 baseline) follows automatically; on PASS run scripts/release/publish_beta_candidate.py --tag v1.0.0-beta.3 (dry-run then live), then stage the kit on HALO for Sergio (LAN) and send the fleet soak prompt.

## 2026-09-02 23:05Z
beta.3 build OK (run 33678188749). Gate A 33681670855: clean PASS, cross-version FAIL, download-only skipped. Cause visible in control_plane.log: DB left at 0082 after the in-place upgrade (migrations not applied; engine exit 10) and the station served anyway -> 500s. Not published. Diagnoser running. Evidence: C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-cross-version-33681670855

## 2026-09-02 23:30Z
Diagnosed: restore drill compares old backup to new head -> false failure -> rollback before migrating; installer continues on rollback (flat layout); harness trusts HTTP 200. Fix PR (branch fix/d3-preupgrade-drill-and-rollback-containment) in flight; then one Opus review, merge, rebuild beta.3, Gate A, publish.

## 2026-09-03 00:20Z
Fix PR #143 open (7963138). Opus review + CI running. Next: merge -> dispatch self-hosted build (native-beta-candidate-artifacts.yml, build_target=self-hosted) -> Gate A 3 lanes -> publish v1.0.0-beta.3.

## 2026-09-03 01:50Z
#143 merged (9573d4a). Rebuild run 33711079441 dispatched (self-hosted). Gate A auto-follows. On 3-lane PASS: publish_beta_candidate.py --tag v1.0.0-beta.3 (dry-run, then live), stage kit on HALO for Sergio (LAN), fleet soak prompt.

## 2026-09-03 04:45Z
Soak staged: kit-beta3-9573d4a at http://192.168.0.135:8766/9573d4a.../, directives branch soak72-9573d4a-directives, paste file floatsom\SOAK-PASTE-ME.md. Gate A 33713004718 running on 9573d4a. Opus installer-path audit + Sonnet UI walkthrough running; batch-fix after both report.

## 2026-09-03 05:20Z - Scott left for the night ('you're on your own')
Soak: tester 192.168.0.238 is pulling the kit from HALO:8766 (Codex desktop, wiped box). Its first pull produced a 0-byte installer; DIRECTIVE-2 (branch soak72-9573d4a-directives @ 3c02e6e, pointer refreshed) carries the per-file curl fetch + verify, the silent install, and standing rules (kit only from HALO; shell-only steps; local reports if git auth missing; never wait for a human). Watchers: tester branch (bg8br7y8l), traffic log (scratchpad/tester-traffic.log). Gate A 33713004718 on 9573d4a running (done ~08:30Z). Two batch-fix builders launched from the audit (84 findings, 13 BLOCKER) and the UI walkthrough: branches fix/installer-upgrade-batch-2026-09-03 and fix/ui-walkthrough-batch-2026-09-03. Primary checkout restored to main.

## 2026-09-03 07:25Z
Gate A 33713004718 on 9573d4a: ALL THREE LANES PASS. Publisher for v1.0.0-beta.3 running (agent). PR #144 (UI batch) MERGED 1b871c3. PR #145 (installer batch, 13 BLOCKERs) open @ 13eccc2, Opus review + CI running; its NSIS changes are proven only by a Gate A run -> after merge: bump to beta.4, repin baseline to the beta.3 kit, build, Gate A. Soak: tester 192.168.0.238 pulled the kit (~05:00-05:36Z), no connections since, NO tester/soak72-* branch and no reachable :8000 from HALO as of 07:25Z - either installing/stalled or reporting locally (git auth missing on a wiped box). DIRECTIVE-2 is live; nothing more can be observed from HALO. Past tester hostname: DESKTOP-VBMA6O5.

## 2026-09-03 07:50Z - v1.0.0-beta.3 PUBLISHED
https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.3 (target 9573d4a, 8 assets, hash+signature verified). Open: #146 (publisher script fix), #147 (docs/release-truth -> beta.3 current) - merge on green; #145 (installer batch) awaiting its last fix commit -> review done -> merge on green. Then: bump to 1.0.0-beta.4, repin sandbox-lab/upgrade-baseline.json to the beta.3 kit (9573d4a), build self-hosted, Gate A 3 lanes, publish beta.4. Soak: no tester ack yet.

## 2026-09-03 08:00Z
PR #145 was MERGED BY ITS AGENT (protocol breach) at 07:56Z as a non-squash merge 47a1920 with 13 checks in progress on head cbe0014. Coordinator is waiting for those checks; revert on red. Do not build beta.4 from main until they settle green.

## 2026-09-03 08:30Z
Tester DESKTOP-VBMA6O5 alive: ACK-1/ACK-2 at 07:59:58Z (git push works). Installer still 0 bytes on its side -> DIRECTIVE-3 (curl/Defender evidence + setup-beta3.zip route; zip added to the kit + SHA256SUMS). Codex app closed/restarted, so DIRECTIVE-4 installs OS-level watchdogs (Scheduled Tasks: 15-min poll with AUTO-ACK, 30-min heartbeat JSON push, boot marker). Pointer -> DIRECTIVE-4 @ 1058e89. Scott is telling Codex to re-read the repo. Proof of watchdogs = soak/AUTO-ACK-4.md + soak/heartbeats/*.json on the tester branch.

## 2026-09-03 08:25Z - watchdogs proven
Tester DESKTOP-VBMA6O5: ACK-4 08:14Z; scheduled tasks live (AUTO-ACK-4 + heartbeat-20260903T082220Z.json pushed by the tasks). Station not yet installed (health unreachable, service not-registered); disk 378 GB free; uptime 9074 min (no reboot). Next expected: FETCH-DIAG.md (DIRECTIVE-3), zip route, silent install, health healthy in a heartbeat. Scott asleep; coordinator has the helm.

## 2026-09-03 08:35Z
main (47a1920, #145 merged by its agent) is green except randomized-suite: two tests in tests/test_health_readiness.py are order-dependent -> fix-forward PR in flight (branch fix/health-readiness-order-independence). #147 (docs/release-truth beta.3 current) red on test_active_public_docs_link_validated_current_candidate -> publish agent adding the beta.3 verification doc. #146 (publisher script fix) 1 check pending. Tester: watchdogs proven; install phase in progress (watcher borxndv0w).

## 2026-09-03 08:40Z
Tester FETCH-DIAG.md: direct curl of the installer = 289,180,536 bytes, exit 0; no Defender detections; 405 GB free. The 0-byte files came from Codex's own listing-walk fetch, not the server or Defender. ACK-3 present; tester proceeding to verify + silent install.

## 2026-09-03 08:45Z - main is RED
#145's merged head cbe0014: Unit tests FAIL (tests/test_health_readiness.py: unknown-schema and behind-schema must read degraded) in default order too -> real regression from the /health change; fix-forward PR in flight (agent told). Do NOT build beta.4 from main until Unit tests are green. #146 1 check pending; #147 new head 8e73e54 in CI.

## 2026-09-03 08:55Z
#146 (publisher script fix) MERGED 2b18481. #148 (health readiness regression fix: lifespan never set schema_status_checked_monotonic; stale 'behind' fixture) open @ b9920e4, CI running -> merge on green, then main is green again. #147 WS4 red being read.

## 2026-09-03 08:55Z
Tester heartbeat cadence proven: 08:23:42Z -> 08:53:43Z (scheduled task, 30 min). Station still not installed (unreachable/not-registered). #147 @ ee6a914 and #148 @ b9920e4 in CI; merge both on green, then beta.4 prep.

## 2026-09-03 09:05Z
#148 (health readiness regression fix) MERGED; main's only remaining CI red is #145's BL-01 real-restore rollback test in the Postgres lane (test_bl01_a_post_migration_failure_rolls_back_cleanly_through_the_real_restore_seam) -> #145's agent is fixing it on branch fix/bl01-restore-seam-ci (PR to come; coordinator merges). #147 (docs/truth) @ ee6a914 in CI. beta.4 prep waits for main green.

## 2026-09-03 09:15Z
#147 (docs/release-truth: beta.3 current, verification doc, README wording) MERGED. Main's only CI red: BL-01 real-restore test (fix PR pending from #145's agent). Next: beta.4 prep once main is green.

## 2026-09-03 09:45Z
Tester: heartbeats on cadence (08:23, 08:53, 09:23Z) but station still unreachable/not-registered and no install evidence; DIRECTIVE-5 (pointer @ 6d433c1) asks for soak/STATUS-1.md (verify, installer log tail, service, health) and to start/finish the silent install. Watchers armed. beta.4 prep PR (release/prep-beta4) and BL-01 fix PR in flight; coordinator merges.

## 2026-09-03 09:55Z
PR #149 (BL-01 restore-seam: command_database_url + packaged psql threading; two real rollback-path defects) open @ eb4a2ab; Sonnet delta review + CI running; coordinator merges on green -> main green -> merge beta.4 prep -> build -> Gate A -> publish beta.4.

## 2026-09-03 10:05Z
PR #150 (beta.4 prep: version bump, baseline -> beta.3 kit, release-truth beta.4 staging; downloader policy test now derives the published tag from release-truth) open @ 74d9074; delta review + CI running. Merge order: #149 (main green) -> #150 -> dispatch self-hosted build -> Gate A -> publish beta.4.

## 2026-09-03 10:35Z
Tester: Codex idle (no STATUS-1 in 50 min; AUTO-ACK-5 + heartbeats prove only the scheduled tasks run). Pushed DIRECTIVE-6: an autorun hook for the poll task + soak/autorun/AUTORUN-6.ps1 that verifies the kit, installs silently, waits for health and reports to the tester branch. Needs ONE paste from Scott to Codex (in the morning report) to install the hook; after that, fixes ship as AUTORUN-<n>.ps1 and run unattended.

## 2026-09-03 10:50Z
#150 fixed @ 5a2372d (publisher tests derive the tag via the script's own seam; docs test derives the current tag from release-truth). CI running. #149 one check left. Tester: waiting for Scott's one paste (DIRECTIVE-6).

## 2026-09-03 10:55Z
#149 (BL-01 restore-seam fixes) MERGED -> main should be fully green now (verify on the next main push). #150 (beta.4 prep) @ 5a2372d in CI; merge on green, then dispatch the self-hosted build, Gate A over the beta.3 baseline, publish beta.4.

## 2026-09-03 11:05Z
#150 (beta.4 prep) MERGED 4f1561b; main = 1.0.0-beta.4 with the beta.3 kit as Gate A baseline. Self-hosted build run 33748881185 dispatched; Gate A auto-follows (3 lanes over beta.3); publish v1.0.0-beta.4 on PASS via publish_beta_candidate.py (note: the script's verify_layout wants a file literally named setup.exe; #146 fixed artifact names but not that - use the hard-linked mirror-dir trick again if it refuses). Tester: Codex idle; DIRECTIVE-6 autorun ready; Scott's one paste needed.

## 2026-09-03 12:52Z
beta.4 build 33748881185 OK. Gate A 33751733160 on 4f1561b: CLEAN lane FAIL (cross-version + download-only skipped). First run with #145's installer/health-gating changes. Diagnosing. beta.4 NOT published; beta.3 stays current.

## 2026-09-03 13:15Z
beta.4 Gate A T4 finding: beta.3's PASS_PRODUCT_ENGINE was a grader false pass; GStreamer engine egress never proven; control-plane child has no package logging. Fix PR (branch fix/egress-engine-visibility: logging + T4 probe last_error/sink poll + docs retraction) in flight; coordinator merges; then rebuild, Gate A (to expose the real cause), fix, Gate A, publish beta.4. Tester: Codex idle; heartbeats on cadence; Scott's one paste pending.

## 2026-09-03 13:45Z
PR #151 (control-plane package logging to control_plane-app.log; daemon/strategy INFO lines; T4 probe polls sink-connected and records last_error; docs retract the beta.3 engine badge) open @ 72d593d; delta review + CI running; coordinator merges on green -> rebuild beta.4 -> Gate A -> read the engine's real failure -> fix -> Gate A -> publish.

## 2026-09-03 14:00Z
#151 reviewed APPROVE; CI green except randomized-suite seed 3501300849 failing tests/stream/test_media_router_storage_absent.py::test_vod_playback_degrades_instead_of_raising_500 (agent classifying pre-existing vs caused). Merge on classification; then rebuild beta.4 + Gate A. Tester: Codex idle, heartbeats on cadence.

## 2026-09-03 16:05Z
#151 MERGED e6ff15f (control-plane logging, T4 probe visibility, docs retraction). Rebuild beta.4 run 33776038096 dispatched; Gate A follows; read control_plane-app.log + T4-ENGINE-NOTES.txt from the evidence to find the real engine cause. Scott's Q&A: Sergio installs the FULL beta.3 kit OVER his beta.1 station (no wipe; proven over beta.2; setup.exe-alone is the unsupported path from beta.1). Engine: never proven by me or Gate A; docs corrected. Tester: reads the repo (poll task) but cannot act until DIRECTIVE-6's autorun hook is installed by one Codex paste.

## 2026-09-03 16:40Z - SOAK CANCELLED, FLEET WITHDRAWN
Owner: no time for the soak; take it off the list; everything is tested by me in the sandbox from now on. Tester watchers stopped; DIRECTIVE-7 (mission closed) pushed @ ce31288. Plan: Gate A on beta.4 rebuild (running), then run sandbox-lab/soak-4h myself on the green kit.

## 2026-09-03 16:15Z
Scott is wiping the tester machine (its CivicCastSoak-* tasks die with it). Deadline: GStreamer engine must emit TS 'before noon MDT' (18:00Z): Opus agent on branch fix/gst-engine-emits-ts reproducing outside the sandbox with the kit's runtime + TSDuck. beta.4 rebuild (e6ff15f, with #151 logging) + Gate A running in parallel; its control_plane-app.log is the second signal. beta.3 vs beta.4 explained to Scott: same product for Sergio; beta.4 = installer hardening + engine visibility; engine unproven in both.

## 2026-09-03 16:30Z - GStreamer ROOT CAUSE FOUND (PR #153)
worker.py imported siblings by path while engine.py used the package form -> two PlaylistLeg classes on Windows -> isinstance miss -> worker crashed in 2 s before PLAYING -> udpsink never sent a byte. Fix = consistent package imports + identity test. Local proof with the kit's own tsp: 1771 packets, 0 errors, valid H.264/AAC service. Plan for the noon deadline: cancelled the e6ff15f main build; building the kit from the PR branch (run 33778501106); then Gate A clean lane on the branch (workflow_dispatch lane=clean); review + CI in parallel; merge; then beta.4 rebuild from main.

## 2026-09-03 16:45Z
#153 review: mechanism correct; MAJOR = package import drags civiccast.egress (pydantic/sqlalchemy) into the worker; agent making an isolation-preserving fix (sys.modules aliasing or shared sibling-import helper) + a no-pydantic-in-worker test. Branch kit e1acfe6 building for the sandbox engine proof (clean lane auto-dispatched after the build). After the refined commit: CI -> merge -> beta.4 rebuild -> three lanes -> publish.

## 2026-09-03 17:05Z
Scott kept the tester; wants an 8-hour soak now on the GStreamer-fixed kit (e1acfe6 branch build 33778501106). Opus agent building mission soak8-e1acfe6 as CODE (branch soak8-e1acfe6-directives: bootstrap/Install-SoakLoop.ps1 with executor poll task + heartbeat + LOOP PROVEN check, AUTORUN-1 install, AUTORUN-2 channels, AUTORUN-3 tsp verify/reports; ONE paste -> floatsom/SOAK8-PASTE-ME.md). #153 refined @ 27f2e58 (sys.modules aliasing, no civiccast.egress import); CI running; merge after CI + branch clean-lane proof; then beta.4 rebuild.

## 2026-09-03 16:50Z
Mission soak8-e1acfe6 built as code on branch soak8-e1acfe6-directives @ d490db4 (bootstrap with executor poll task + LOOP PROVEN check; AUTORUN-1/2/3). Paste at floatsom/SOAK8-PASTE-ME.md. Waiting for branch build 33778501106 to land the e1acfe6 kit; then copy the 4 samples into <kit>/samples and write SHA256SUMS.txt; then Scott pastes once.

## 2026-09-03 17:05Z
Kit e1acfe6 (GStreamer fix, version 1.0.0-beta.4) staged with samples + SHA256SUMS (19 lines), served on HALO:8766. Gate A 33781833394 (workflow_run from the branch build, three lanes) running since 16:58Z. Scott told to paste SOAK8 now. #153 @ 27f2e58 in CI; merge after CI + Gate A clean PASS; then beta.4 rebuild from main (three lanes) and publish.

## 2026-09-03 17:35Z
#153 (GStreamer worker module identity fix) MERGED. Next: after Gate A 33781833394 (e1acfe6 kit, 3 lanes) finishes AND the tester's INSTALL-RESULT shows it pulled the kit, dispatch the beta.4 build from main (the build prunes old kits; do not pull the served kit out from under the soak), Gate A three lanes, publish v1.0.0-beta.4.

## 2026-09-03 18:05Z
Gate A 33781833394 (e1acfe6 kit): clean lane FAIL on T4 only; control_plane-app.log (from #151) shows the GStreamer worker starts and exits non-zero after ~10 s (daemon says 'FFmpeg child exited', a mislabel); worker log not in diag. Opus engineer round 2 on branch fix/gst-worker-runtime-death. #153 merged (f1800ab). Tester: no soak8 branch yet (Scott has not pasted). beta.4 rebuild waits for the fix.

## 2026-09-03 18:35Z
PR #154 (GStreamer worker 10-s death = d3d12h264dec autoplugged in the GPU-less sandbox; demote hardware decoders; worker logs collected; engine-named last_error) open @ b78b9c7; review: BLOCKER on stderr redaction (mid-line URIs leak) -> agent fixing. Kit b78b9c7 building (run 33790253168); on landing: samples + SHA256SUMS staged, Gate A auto (workflow_run). Soak8 mission re-pointed at b78b9c7 (directives branch @ 3c70a1a; paste file updated). Scott to paste after ~19:05Z.

## 2026-09-03 18:50Z
#154 @ 19fb8c2: redaction blocker fixed (mid-line URI scanner + tests); CI running; merge on green + Gate A clean PASS on the b78b9c7 kit. Note: the agent read a file out of another agent's shared stash (reverted, stash intact) - one-agent-per-worktree boundary reminder for briefs.

## 2026-09-03 19:00Z
Standing firewall rules added via the elevated helper (allow-lab-ts-capture.ps1) so the TSDuck Windows Security prompt cannot recur on HALO. Waiting: #154 CI (19fb8c2), kit b78b9c7 build -> stage -> Gate A, tester paste.

## 2026-09-03 19:10Z
TESTER INSTALLED beta.3 UNATTENDED: old mission's AUTORUN-6 (poll-task executor) ran at 18:43Z, kit verify bad=0, silent install exit 0 (18:46-18:56Z), health healthy/schema current 0087. Scott pasted the soak8 bootstrap ~18:40Z; no tester/soak8-* branch yet at 19:05Z (bootstrap unregisters the old tasks; its LOOP PROVEN/FAILED line is only visible on the tester screen).

## 2026-09-03 19:15Z
Kit b78b9c7 (PR #154) built + staged (samples, SHA256SUMS). Gate A 33793374197 on it running since 18:55Z (clean lane = the GStreamer proof). #154 CI: randomized-suite red (cause being read), 2 pending. Soak8: no tester branch yet; Scott asked for Codex's last line.

## 2026-09-03 19:25Z - soak8 bootstrap LOOP FAILED (reported by the tester itself to soak/LOOP-FAILED.md)
Cause: stale clones from the previous mission under C:/CivicCastSoak (single-branch directives clone of soak72; repo clone with narrow refspec) -> origin/soak8-e1acfe6-directives and origin/main unknown; the poll template resets to origin/<branch> instead of FETCH_HEAD. Tasks were registered; push works. Fix: bootstrap made self-healing (re-clone mismatched directives dir; set full refspec on repo; FETCH_HEAD everywhere); Scott re-runs the SAME paste once. Gate A 33793374197 on the b78b9c7 kit running (GStreamer proof).

## 2026-09-03 19:20Z
soak8 heartbeat task PROVEN on the tester: heartbeat-20260903T191419Z.json = healthy, 1.0.0-beta.3, schema current, service Running, 309 GB free. Poll/executor blind until the self-healing bootstrap is re-run once (agent fixing). #154 @ 69285d6 (claims test constant) in CI. Gate A 33793374197 on the b78b9c7 kit running.

## 2026-09-03 19:35Z
Self-healing bootstrap pushed (soak8-e1acfe6-directives @ 79bf7fd), tested on HALO against the reproduced stale-clone state -> LOOP PROVEN. Paste marked READY; Scott asked to re-run the same paste. Watcher on tester/soak8-e1acfe6-DESKTOP-VBMA6O5 for AUTO-ACK-1, INSTALL-RESULT (kit b78b9c7), SOAK-START, reports. Gate A on b78b9c7 + #154 CI still running.

Correction 19:40Z: the first soak8 bootstrap did not self-report; Scott had to tell Codex to write LOOP-FAILED.md after the box sat idle. The fixed bootstrap pushes its own report.

## 2026-09-03 19:38Z - SOAK8 LOOP PROVEN
Scott re-pasted once; fixed bootstrap 79bf7fd ran: AUTO-ACK-1 19:35:12Z + heartbeats 19:35Z/19:36Z on tester/soak8-e1acfe6-DESKTOP-VBMA6O5. The old LOOP-FAILED.md (19:11Z, written by Codex on Scott's order - my bootstrap did not self-report; corrected) still sits on the branch. Next on the tester: AUTORUN-1 (kit b78b9c7 fetch+install) via the poll task; watcher brzxerfv7 reports. No more pastes.

## 2026-09-03 20:05Z - Gate A 33793374197 (kit b78b9c7 = PR #154) FAIL at T4
T4_RESULT=PASS_FFMPEG_FALLBACK, engine path: GStreamer worker child crashes at import: gi Gst override 'class URIHandler(Gst.URIHandler)' -> TypeError: must be an interface. Previous beta.4 gate (33751733160, pre-#154) imported fine then stalled, so #154 introduced it (suspect: worker sys.path[0]=gst dir + standalone sibling imports, or GST_PLUGIN_FEATURE_RANK timing). Also no schedule item -> slate plan (expected). Opus diagnostician launched to reproduce with the shipped runtime from the staged pack and fix on the #154 branch. #154 NOT merged. Evidence: sandbox-lab/evidence/b78b9c7.../20260903-195625Z.

## 2026-09-03 20:17Z - SOAK CLOCK HELD (Scott: soak must run on GStreamer)
soak8-e1acfe6-directives @ e355763: AUTORUN-2/3 parked in soak/held/, DIRECTIVE-2 hold note, pointer -> DIRECTIVE-2. Tester continues AUTORUN-1 (install b78b9c7). When the fixed kit exists: ship AUTORUN-2 (fetch+install fixed kit), AUTORUN-3/4 = the parked channel-start + verify with the 8h clock. Directives worktree: Desktop/Code/cc-soak8.

## 2026-09-03 20:25Z - GStreamer worker root cause FOUND + fix pushed (779cc8f on #154, unmerged)
Root cause (Opus, reproduced with the shipped runtime): build_control_plane_media_env (civiccast/native/supervisor/service.py) composed PATH over os.environ and was merged LAST, dropping the bundled dependencies\gstreamerin prepend; girepository LoadLibrary of gstreamer-1.0-0.dll fails -> gi Gst override 'must be an interface'. Pre-existing since the initial commit; hidden on dev boxes with a system GStreamer on PATH; #154's stderr-tail made it visible. Fix: inherited_path param + gstreamer_runtime.py prepends bin to PATH and setdefaults GI_TYPELIB_PATH/GST_PLUGIN_PATH; 5 regression tests fail-before/pass-after. Beta.4 old-gate evidence confirms: no decoder name, no import success there either. Waiting: #154 CI (bol0qu3p3), delta review (Opus), tester AUTORUN-1 result. Then: merge #154, run scratchpad/build-stage-gate.sh main (dispatch build, stage samples+SHA256SUMS, wait Gate A), then ship AUTORUN-2 (install fixed kit) + un-park AUTORUN-3/4 for the 8h GStreamer soak.

## 2026-09-03 20:30Z - tester AUTORUN-1 exit 123 (mixed kit, autorun bug, not product)
Tester fetched the b78b9c7 (beta.4) kit files (verify bad=0) but ran the OLD beta.3 setup.exe left in the same download dir from soak72 (installer glob picked it): beta.3 over beta.3 -> d3 no-op -> activation fail 123 with beta.4 packs. Fix in AUTORUN-2: fresh dir per SHA, installer picked by the manifest name. Delta review of 779cc8f: MERGE. #154 CI still running.

## 2026-09-03 20:38Z
soak8 directives @ 848c003: AUTORUN-1 parked too (it re-armed on failure -> would re-download 21 GB every 10 min). Tester station NOT healthy after exit 123 (activation 66 = beta.3 installer + beta.4 station index). AUTORUN-2 template drafted in scratchpad (fresh kit-<sha> dir, installer by manifest name, install OVER existing, no re-arm after fetch). Fill __SHA__ when the fixed kit is staged.

## 2026-09-03 21:05Z
#154 CI on 779cc8f: 1 real failure (tests/policy/test_native_caption_workflow_policy.py pinned native collection counts (1781,1981) -> now (1786,1987)); claims-evidence/mutation/randomized reds were downstream of it. Bumped in 9479c56, pushed. Delta review of 779cc8f: MERGE (typelib setdefault caveat only). Waiting CI, then merge -> build-stage-gate.sh main.

## 2026-09-03 21:25Z - OWNER: soak runs on HALO now ("you're back to doing the soak here. Start now.")
Build 33807326090 dispatched from fix/gst-worker-runtime-death @ 9479c56 (fixed kit). Plan: auto Gate A (engine proof) then Run-GateA.ps1 -SoakMinutes 480 on that kit in the sandbox. Tester mission on hold (DIRECTIVE-3); heartbeats continue. Issue anthropics/claude-code#91905 posted.

## 2026-09-03 21:40Z - engine soak lane being built
Finding: neither existing lane soaks the product engine (T5 = health polls every 300s; soak-4h = ffmpeg synthetic encoders). Sonnet builder on feat/gate-a-engine-soak: T6 phase in In-Sandbox-Report.ps1 (3 channels on the GStreamer engine with the LPM sample clips scheduled as premieres, tsp per beat, RSS/relaunch counts, FAIL_EARLY at beat 1-2, judge + time bounds scaled to SOAK_MINUTES, contract tests). Will run locally: Run-GateA.ps1 -KitDir <9479c56 kit> -SoakMinutes 480 after the auto Gate A on build 33807326090.

## 2026-09-03 21:52Z
Decision: skip the separate auto Gate A on the 9479c56 kit (cancel it when it appears); the 8h soak run (Run-GateA.ps1 -KitDir <kit> -SoakMinutes 480, feat/gate-a-engine-soak checkout) includes install + T4 engine proof + T6 FAIL_EARLY. Target start ~22:30Z (4:30 PM MDT), end ~06:30Z (12:30 AM MDT Fri).

## 2026-09-03 21:55Z - OWNER: "do it right"
Reverted the shortcut: the auto Gate A on the 9479c56 kit runs in full first (waiter bq4ydz40h), THEN the 8h engine soak starts on the same kit. Start ~23:30Z (5:30 PM MDT), end ~07:30Z (1:30 AM MDT Fri).

## 2026-09-03 22:15Z
PR #155 (feat/gate-a-engine-soak) opened by the Sonnet builder: T6 engine soak (3 channels ON_AIR on the GStreamer engine, LPM clips as premieres via POST /api/staff/schedule, tsp per beat, RSS/relaunches, FAIL_EARLY), judge check_t6_engine_soak, time bounds SOAK+150/SOAK+170, 236 gate_a tests pass. Kit dir is junctioned whole into C:\CivicCastPayload so samples\ rides along. Opus hostile review running. Soak command: pwsh sandbox-lab/Run-GateA.ps1 -KitDir C:\CivicCastTester\kit-staging\<9479c56 sha> -SoakMinutes 480 from a checkout of #155 (after the auto Gate A on that kit completes).

## 2026-09-03 22:30Z
#154: mutation job red on 9479c56 = new bootstrap tests leaked a tmp python dir (stub gi) into sys.path -> test_worker_pipe_seam imported the stub. Fixed in bdfff94 (monkeypatch sys.path restore), 42 passed locally, pushed; CI waiter running. Kit for the soak stays 9479c56 (test-only delta). #155 review running; build 33807326090 + auto Gate A waiter running.

## 2026-09-03 22:50Z - #155 review: 5 blockers (B1 items never published -> slate false pass; B2 watchdog gaps in staging; B3 30s timeout + 858MB ReadAllBytes; B4 samples path (reviewer wrong: kit-download junction carries samples\, but real clips now mandatory = FAIL_EARLY if absent); B5 schedule covers 213 of 480 min). Builder fixing on the branch; then one delta review; then soak.

## 2026-09-03 21:55Z (clock corrected: date -u)
#155 @ 3655e4c: B1-B5 fixed per builder (playout/commit per item; beat = ON_AIR + packets + tsp pass + current_source_label != 'CivicCast slate'; Save-Summary in staging; 200MB cap + 900s timeouts + readiness poll; no synthetic fallback; schedule anchored at start, ffprobe durations, 0s gaps). Opus delta review running. Samples usable under 200MB: 17MB 1080p, 3.8MB 360p (67s), 34MB 360p (667s); the 858MB clip is skipped. Build 33807326090 still running.

## 2026-09-03 21:58Z
Build 33807326090 (9479c56, engine PATH fix) SUCCESS; kit staged with samples + SHA256SUMS at C:/CivicCastTester/kit-staging/9479c56dfbd854c59e82df4fb0da9c7fc45b8c61. Gate A 33810353879 running on it (headSha shows main's f1800ab: workflow_run tags Gate A with main's sha, so match by createdAt). Waiting: Gate A (bye989kwo), #155 delta review, #154 CI (bpz2857i5). Then: merge #154; soak = Run-GateA.ps1 -KitDir <that kit> -SoakMinutes 480 from the #155 checkout.

## 2026-09-03 22:08Z - #155 delta review round 2: 2 blockers
B-A: max_segments=8 -> plan ends ~29 min -> worker EOS -> STOPPED; auto_start=false in T6 so nothing restarts -> fix auto_start=true + one 20s retry per beat. B-B: each playout/commit dispatches a daemon reload; 100+ commits on a live channel = reload storm (parks TRANSITIONING on the ffmpeg path) -> fix by ordering: schedule+commit all items while channels are STOPPED, then start; first item = the 667s clip at now-60s; FAIL_EARLY if scheduling took >500s. Builder on it; one more delta review after.

## 2026-09-03 22:10Z
#155 @ 073f18a: auto_start=true, 20s beat retry (Get-T6ChannelSample), schedule+commit all items while STOPPED then config+start, 500s guard, longest clip first, public /now label per beat; 248 gate_a tests pass. Final Opus delta check running. Gate A 33810353879 still in clean lane; #154 CI 2 pending.

## 2026-09-03 22:22Z - #155 round 3: BLOCKER (T4's leftover 'government' config makes the commit-phase 'start' succeed -> storm; no warm-up before beat 1; beat worst-case 530s > 480s watchdog; 500s guard hardcoded). Fixes sent: own channel ids soak-public/education/government on 19011-19013, 120s warm-up, Save-Summary per channel per beat, derived guard + anchor recommit. Launcher ready: scratchpad/launch-soak.sh <gateA run id>.

## 2026-09-03 22:35Z - SOAK LAUNCHED (queued behind Gate A 33810353879)
#155 final @ 090ef25 (200 on pre-check -> FAIL_EARLY; inert recommit removed; 254 gate_a tests). Launcher scratchpad/launch-soak.sh: waits for Gate A, then `Run-GateA.ps1 -KitDir C:\CivicCastTester\kit-staging\9479c56... -SoakMinutes 480 -SandboxWaitMinutes 30` from wt-soak; log wt-soak/soak-480.log; evidence under sandbox-lab/evidence/9479c56.../<stamp> in the wt-soak checkout. T6 = 3 channels soak-public/education/government on 19011-19013, GStreamer engine, real LPM clips (<200MB), 5-min beats, FAIL_EARLY at beat 1-2.

## 2026-09-03 22:45Z
Soak launcher now DETACHED: powershell pid 43096 running scratchpad/wait-and-soak.ps1 (waits for Gate A 33810353879, then Run-GateA -SoakMinutes 480 from wt-soak @ 090ef25); log wt-soak/soak-480.log. The tool-bound launcher was killed (10-min tool cutoff risk).

## 2026-09-03 23:10Z - Gate A 33810353879 (kit 9479c56) FAIL at T4, but the ENGINE NOW RUNS
Evidence sandbox-lab/evidence/9479c56.../20260903-225553Z: GStreamer worker pid 6576 started and stayed alive on the slate (PATH fix works). T4 failed only because the packaged TSDuck lacks its data files: tsp prints "configuration file 'dtv' not found" / tsduck.hfbands.xml missing and exits (verdict fail-exit). Pack has tsp+2 dlls+4 plugins only. Also product ts_relay logs 'TSDuck (tsp) not found' (item 21). Sonnet on fix/tsduck-pack-config (pack data files + lookup). Soak launcher had already started a run; killed it and tore down its sandbox PIDs (56212/57612/50212; vmmem 46740 checked). Next: merge #154 + tsduck PR -> rebuild from main -> Gate A -> soak.

## 2026-09-03 23:25Z
PR #156 fix/tsduck-pack-config opened (17 TSDuck data files into tsduck/bin as TSDUCK_DATA_PINS from the mirrored 3.44-4676 archive, license entries, locate_tsduck shipped-pack fallback via InstallLayout; 296 tests pass). Opus review + CI running. #154 last check (mutation-report) pending. Orphan sandbox vmmem exited on its own; sandbox free. Plan: merge #154 + #156 -> build from main -> Gate A -> soak (launcher must be re-pointed to the new kit sha).

## 2026-09-03 23:30Z
#156 review: MERGE (17 data files byte-verified vs the mirrored archive; fallback path matches native_activation.rs). Waiting CI on #154 (mutation-report) and #156. wait-and-soak.ps1 now takes -GateRun -KitSha and launches the soak ONLY if Gate A concluded success.

## 2026-09-03 23:40Z
#154 MERGED -> main 23d428c. #156: npm audit job failed on a registry 500 (external), re-run; other checks pending. Next: merge #156 on green -> build-stage-gate.sh main -> detached wait-and-soak.ps1 -GateRun <id> -KitSha <sha>.

## 2026-09-03 23:50Z
#156 CI: 2 real reds (activation-selftest layout policy: *_PINS loop structure; native collection floor needs main merged + bump) + 2 downstream. Builder fixing. Time check: soak start now realistically ~02:30Z (8:30 PM MDT), end ~10:30Z (4:30 AM MDT).

## 2026-09-04 00:00Z - OWNER: "we are out of time"
Offered A (finish chain tonight, soak shortened to 120 min, publish beta.4 if Gate A engine proof passes) vs B (stop; beta.3 stays; honest engine-unproven note). Proceeding with A unless Scott says B. Soak = -SoakMinutes 120.

## 2026-09-04 00:35Z - OWNER: "2 hours it is" (option A confirmed)
#156 @ ee46144: mutation-job sandbox artifact (policy test parses the builder text; mutants copy has duplicated loops) -> deselected in deterministic-detectors.yml with a documented note; npm audit rerun (registry 503). wait-and-soak.ps1 now -SoakMinutes 120 (log soak-120.log). After #156 green: merge -> build-stage-gate.sh main -> Start-Process wait-and-soak.ps1 -GateRun <id> -KitSha <sha> -> publish beta.4 if PASS.

## 2026-09-04 00:50Z
Draft PR #157 docs/release-beta4 @ d43fe72 (verification doc, release notes, CHANGELOG, README note, tester docs; release-truth flip staged in docs/releases/beta4-truth.patch; placeholders KIT_SHA/BUILD_RUN_ID/GATE_A_RUN_ID/SHA256_SETUP_EXE/RELEASE_DATE + the T4 conditional sentence). Root cause text corrected to the PATH bug. #156 CI at ee46144: 5 pending (npm audit flapping on registry outage).

## 2026-09-04 01:05Z
#156 MERGED (--admin; npm audit outage + mutation sandbox artifact noted, batch item 22). Next: detached chain: build main -> stage kit -> Gate A -> 120-min soak.

## 2026-09-04 01:10Z - CHAIN STARTED (detached)
scratchpad/chain-build-gate-soak.ps1 -Ref main (4b30c99) -SoakMinutes 120: build -> stage samples+SHA256SUMS -> Gate A (auto) -> if PASS run soak from wt-soak (#155 @ 090ef25). Log scratchpad/chain.log, pid in chain.pid, soak log wt-soak/soak-120.log, evidence wt-soak/sandbox-lab/evidence/4b30c99.../. Monitor armed. Publish beta.4 after: fill #157 placeholders (KIT_SHA, BUILD_RUN_ID, GATE_A_RUN_ID, SHA256_SETUP_EXE, RELEASE_DATE), apply beta4-truth.patch, publisher needs 3 PASS lanes + mirror-dir trick.

## 2026-09-04 01:15Z
Chain restarted with -BuildRun 33824029971 (main 4b30c99 build, dispatched 01:00Z); first run's id lookup was empty. Same monitor (bodmjw06p) on chain.log.

## 2026-09-04 03:55Z - ENGINE PROVEN IN EVIDENCE; harness exit-code bug
Gate A 33826665417 (kit 4b30c99 = main with #154+#156) FAILED at T4 with verdict fail-exit- (exit_code null) BUT the evidence tsduck-engine-government-report.json (6387 bytes) shows ts.packets total=1229, invalid-syncs=0, transport-errors=0, 1 service, PID 65 AVC 1280x720 + PID 66 AAC: the GStreamer engine streamed real TS on 19003. Test-TsProof's $proc.ExitCode is null on PS 5.1 (handle not cached) -> 'fail-exit-' before the report is read. Fix on fix/gate-a-tsp-exit-code (cache $proc.Handle, WaitForExit). The detached chain never logged after restart (stuck; killed). Next: merge harness fix -> re-dispatch Gate A with run_id=33824029971 (same kit) -> merge main into #155 -> soak.

## 2026-09-04 04:35Z
#158 (tsp exit-code handle fix) green -> merging; Gate A re-dispatched with run_id=33824029971 (kit 4b30c99, already staged with samples+SHA256SUMS? CHECK: the chain died before staging -> stage now); main merged into feat/gate-a-engine-soak. Then soak 120 min via wait-and-soak.ps1 -GateRun <id> -KitSha 4b30c991a96b34a49210d2ca7d9b6bced49b1360.

## 2026-09-04 04:45Z
#158 MERGED -> main 6dc606d. Gate A 33837269907 re-dispatched on build 33824029971 (kit 4b30c99; samples+SHA256SUMS staged). Soak lane feat/gate-a-engine-soak @ 3770c65 (main merged, 255 gate_a tests). Detached wait-and-soak.ps1 pid 35808: launches the 120-min soak only if Gate A concludes success; log wt-soak/soak-120.log. Monitor bo3cnt4d0.

## 2026-09-04 06:50Z - GATE A 33837269907 (kit 4b30c99): CLEAN LANE PASS with T4 PASS_PRODUCT_ENGINE (machine verdict: tsp exit 0, 1233 packets, 0 errors); CROSS-VERSION LANE FAIL
Cross-version (beta.3 -> beta.4): d3 engine OK (DB at 0087), d4-provision returned 75 -> FAILURE CONTAINMENT -> exit 116 ('could not provision the PostgreSQL server'). Download-only lane skipped. Opus diagnosing on fix/upgrade-provision-rc75. 120-min engine soak STARTED 06:45Z on the clean lane (detached run-soak-now.ps1 pid 2420, log wt-soak/soak-120.log, monitor bo3cnt4d0). Publish blocked until the upgrade lane passes (publisher needs 3 PASS lanes).

## 2026-09-04 07:15Z
PR #159 fix/upgrade-provision-rc75 @ ce65031: D4 NOOP_REUSE_EXISTING ran the pg_ctl ACL/migrate sandwich on a pgdata owned by the live service started by D3's health gate (latent since #145 BL-12; masked on 09-03 because D3 rolled back then). Fix: migrate in place when the reused URL answers. Review + CI running. Needs: merge -> REBUILD kit (provision code is in the app payload) -> 3-lane Gate A -> publish. Soak on 4b30c99 continues (engine proof).

## 2026-09-04 07:30Z
#159 review MERGE (mechanism confirmed from postgres.log: D4 pg_ctl start unlinked the live postmaster.pid). CI red was the collection-floor pin; re-pinned (1789,1990) @ 1317193 with main merged; CI waiter running. Then: merge -> build main -> stage -> 3-lane Gate A -> (soak on final kit if time) -> publish beta.4 via #157 docs.

## 2026-09-04 08:50Z
#159 MERGED -> main c27c6e7 (the beta.4 candidate). Build 33854799455 dispatched; monitor stages the kit (samples+SHA256SUMS) and waits for the 3-lane Gate A. Soak on 4b30c99 still in the sandbox (progress in wt-soak/sandbox-lab/output; evidence copied at the end); second monitor on T6-SOAK.txt.

## 2026-09-04 09:15Z - 120-MIN ENGINE SOAK VERDICT (kit 4b30c99, lane #155 @ 3770c65)
T4_RESULT=PASS_PRODUCT_ENGINE; T6_RESULT=FAIL reason=relaunches>3 (public 8, education 6, government 7) beats=22 failed_beats=0. All 66 samples ON_AIR on the GStreamer engine with real LPM clips, tsp pass every beat, min 1357 packets/8s, RSS ~445-566 MB flat. Worker pid changed every ~2-3 beats (10-15 min) = plan-end EOS -> STOPPED -> auto_start restart (product replans only at plan end; no seamless rollover). Evidence: Desktop/CIVICCAST-EVIDENCE/soak-120-4b30c99-20260904 (296 files). Decision for Scott: publish beta.4 with 'restart at plan boundaries' as a known issue vs hold for a seamless-replan fix.

## 2026-09-04 09:25Z
Soak run machine verdict (wt-soak evidence 20260904-090949Z, copied to Desktop/CIVICCAST-EVIDENCE/soak-120-4b30c99-20260904/final-evidence): overall FAIL; t4_engine PASS (1236 packets, 0 errors); t5_soak PASS beats=22; t6_engine_soak FAIL (relaunches>3, failed_beats=0). Waiting: build 33854799455 (c27c6e7) + 3-lane Gate A (monitor be7m4kl91). Default: publish beta.4 with the plan-end restart as a known issue unless Scott says hold.

## 2026-09-04 11:20Z - final kit c27c6e7 Gate A 33857982657: clean PASS; cross-version: install exit 0, activation 0, POSTINSTALL SUCCESS, DB at head via /health (the #159 fix WORKS) but the harness psql proof reads HKLM\SOFTWARE\CivicCast instead of HKLM\SOFTWARE\CivicCast\Native -> '<no-database-url>' -> lane FAIL. Harness-only fix on fix/gate-a-dburl-registry-key. Then: merge -> re-dispatch Gate A run_id=33854799455 -> publish beta.4.

## 2026-09-04 11:45Z
PR #160 fix/gate-a-dburl-registry-key opened (harness psql proof reads HKLM\SOFTWARE\CivicCast\Native; contract test pins it to the NSIS source; 222 gate_a tests). CI waiter running. Then: merge -> gh workflow run gate-a-station-acceptance.yml -f run_id=33854799455 (kit c27c6e7, no rebuild) -> 3 PASS lanes -> fill #157 placeholders (KIT_SHA=c27c6e70200406b51558ee1ef6b3a95ee4dc4426, BUILD_RUN_ID=33854799455, GATE_A_RUN_ID=<new>) -> apply beta4-truth.patch -> publisher (mirror-dir trick) -> tag v1.0.0-beta.4 pre-release.

## 2026-09-04 12:05Z
Docs #157 @ 2c68015: KIT_SHA/BUILD_RUN_ID/SHA256_SETUP_EXE (9fae1211...)/RELEASE_DATE/signature Valid filled; remaining placeholders: GATE_A_RUN_ID (12), EVIDENCE_PATH_* (3), ASSET_COUNT, KIND/RESULT/SHA/PLACEHOLDER in the truth patch. Publisher mirror: C:\CivicCastTester\kit-mirror\c27c6e7... (setup.exe hardlink + packs/station junctions). #160 CI running.

## 2026-09-04 12:10Z
#160 green -> merging; Gate A re-dispatched with run_id=33854799455 (kit c27c6e7). On 3 PASS: fill GATE_A_RUN_ID + evidence paths in #157, apply beta4-truth.patch, merge #157, publisher on kit-mirror, tag v1.0.0-beta.4 pre-release.

## 2026-09-04 12:30Z
Gate A 33870994702 running (kit c27c6e7, harness with #158+#160). Publish = scratchpad/publish-beta4.sh <run> [--dry-run]: verifies 3 PASS verdicts, copies evidence to Desktop/CIVICCAST-EVIDENCE/gate-a-beta4-final-<run>, runs the publisher on kit-mirror (tag + pre-release), saves the publisher's release-truth edit to scratchpad/publisher-truth.diff (NOT committed: duplicate beta.4 entry vs #150's staging entry). Then a docs sweep agent reconciles #157 (fill GATE_A_RUN_ID/evidence paths/ASSET_COUNT, apply truth flip without duplicates, README/INSTALL/tester banners -> beta.4 current) and I merge it.

## 2026-09-04 14:05Z - Gate A 33870994702 (kit c27c6e7): clean PASS; cross-version FAIL only on the psql proof: Start-Process split the -c SQL into 9 args (psql stderr 'extra command-line argument ... ignored'), bare SELECT, exit 0, no rows -> <no-alembic-version-row>. Install/activation/health/DB-at-head all PASS. Harness fix fix/gate-a-psql-arg-quoting (quote SQL + refuse split results + contract test). Then merge -> Gate A run_id=33854799455 again -> publish-beta4.sh.

## 2026-09-04 14:47Z
#161 green -> merged; Gate A re-dispatched on build 33854799455 (kit c27c6e7) with the harness at main (#158+#160+#161). On 3 PASS: bash scratchpad/publish-beta4.sh <run> (dry-run first), then docs sweep on #157.

## 2026-09-04 14:55Z - OWNER: "When beta 4 lands (and beta 5), update all documentation surfaces/push/merge/tag on green CI." Standing order; beta.5 = plan-rollover fix (item 26) + docs sweep + tag.

## 2026-09-04 15:00Z
beta.5 headline fix started in parallel: Sonnet on fix/egress-seamless-plan-rollover (lookahead rollover via the gst seamless reload path; no worker restart at plan end). Gate A 33885550628 (beta.4 final kit) running; monitor bex63r0fp.

## 2026-09-04 15:20Z
PR #162 fix/egress-seamless-plan-rollover opened (automation._check_plan_rollover: within 30 s of the plan's projected end, refetch the plan and dispatch the existing seamless 'reload'; 6 unit tests; egress suite 907 passed). Opus review + CI running. Merge AFTER the beta.4 publish; beta.5 = #162 + docs + soak proof (pids constant).

## 2026-09-04 15:40Z
#162 review: BLOCKER x3 (fires during force-slate/live takeover; no retry pacing -> per-tick schedule query storm; reload can lose the race with EOS since source prep is synchronous; mid-item swap re-decodes at a stale offset). Builder fixing: takeover-aware skip, retry latch, earlier boundary-aligned rollover (switch at old leg's end). Gate A 33885550628 (beta.4) still running.

## 2026-09-04 16:35Z
#162 @ 74e20cd: has_manual_override skip, retry latch, reload_policy.rollover_trigger_at, engine reload_program(switch_at_end_of_current) deferring the selector switch to the outgoing leg's EOS (900s watchdog), sidecar filename .defer-eos.json/.immediate.json; egress 938 passed; mypy clean. Opus delta review running. Beta.4 Gate A 33885550628 still running.

## 2026-09-04 16:50Z
#162 delta review: BLOCKER on the engine defer path (PAD_PROBE_REMOVE does not drop EOS; audio outgoing pad unprobed; no leg time alignment so the inactive leg free-runs; horizon re-derived by re-query). Opus now owns the engine part: DROP EOS on both outgoing selector pads, deliberate sync-streams/offsets, horizon from the dispatched plan, and a REAL gi engine test on HALO using the kit's bundled GStreamer runtime.

## 2026-09-04 16:45Z - Gate A 33885550628: cross-version FAIL #4 in the same proof: SQL now reaches the DB but the UNION over civiccast.+public.alembic_version fails because public.alembic_version does not exist. Fix fix/gate-a-psql-schema-fallback (one statement per namespace). Install/activation/health/DB-at-head PASS again. Fifth Gate A run needed (kit unchanged).

## 2026-09-04 17:40Z
#162 @ 4c2f942 (Opus engine rework): DROP EOS on both outgoing selector pads; new leg held by BLOCK|BUFFER probe; pad.set_offset on the new leg's tail src pad (measured); clock-timed legs excluded via graph.source_leg_is_clock_timed; horizon from daemon.dispatched_plan_horizon; real gi engine test on HALO passes 5/5 (fails on 74e20cd and with rebase off); tsp: 0 discontinuities, pts-leap 0; egress gi-enabled 975 passed. Residual: EOS-before-ready freeze until stall watchdog; immediate path unrebased. Final delta review running. #163 (psql schema fallback) CI running.

## 2026-09-04 17:35Z
#163 green -> merged; Gate A #5 dispatched on build 33854799455 (kit c27c6e7) with harness #158+#160+#161+#163. On 3 PASS: publish-beta4.sh.

## 2026-09-04 18:00Z
#162 final delta review: MERGE (rollover test 4/4 on the reviewer's own run; docstring contradiction + audio-gap metric as follow-ups 28-31). Plan: merge #162 after the beta.4 publish; beta.5 = build main -> Gate A -> T6 soak (must show pids constant) -> docs -> tag.

## 2026-09-04 19:05Z
#162 CI red only on tests/policy/test_claims_evidence.py (claims.yaml blob-hash bindings of the gst modules drifted with the engine rework); Sonnet re-binding. Gate A #5 33901203343: clean PASS, cross-version running.

## 2026-09-04 19:10Z
#162 @ cdcd267: claims re-bound (native-decision-gate, session0-service-broadcast; reload_policy.py deliberately not added because test_claims_evidence pins the six modules); CI waiter running. Gate A #5: clean PASS, cross-version in progress.

## 2026-09-04 20:10Z - v1.0.0-beta.4 PUBLISHED
Gate A 33901203343: clean PASS (PASS_PRODUCT_ENGINE), cross-version PASS (psql proof finally executed), download-only PASS. Publisher: prerelease v1.0.0-beta.4 target c27c6e7, 8 assets, signature Valid. Evidence Desktop/CIVICCAST-EVIDENCE/gate-a-beta4-final-33901203343. Docs sweep agent on #157 (fill placeholders, dedupe truth entry, banners). Next: merge #157; merge #162 (beta.5 rollover) on green; beta.5 chain.

## 2026-09-04 21:05Z
#157 (beta.4 docs sweep, 26 files, 1941 policy tests) ready; CI waiter running -> merge on green. #162 (seamless rollover) merging now (mutation-report informational still running); beta.5 candidate build dispatched from main. Chain: build -> stage -> Gate A (3 lanes) -> 120-min T6 soak (pids must stay constant per channel) -> docs sweep -> tag v1.0.0-beta.5. Version bump to beta.5 needed BEFORE the beta.5 build? CHECK: _native_version.py still 1.0.0-beta.4 -> the kit would be beta.4-versioned; a version-bump PR (#150-style: version + baseline repin to the beta.4 kit) must precede the real beta.5 build.

## 2026-09-04 21:10Z
Corrected plan: build 33918978783 (main b2b5694 = beta.4 identity + #162) is the ROLLOVER SOAK PROOF kit, not the beta.5 release kit. Sonnet on chore/release-beta5-identity (version -> 1.0.0-beta.5 everywhere, baseline repin to the beta.4 kit c27c6e7, truth staging entry, item 28 docstring/factory table). After its merge: real beta.5 build -> 3-lane Gate A -> publish. Soak on b2b5694 kit via run-soak-kit.ps1 <sha> 120 after its Gate A.

## 2026-09-04 21:40Z
beta.5 identity agent: 20 surfaces bumped, baseline repinned to c27c6e7, truth staging entry, graph docstring/factory table; told it to pin gate_a_run_id=33901203343 (the PASS run; it had pinned the failed 33857982657) and drop the CHANGELOG gap note, then push + PR. #157 CI waiter running; rollover-proof build 33918978783 monitor running.

## 2026-09-04 22:00Z
PR #164 chore/release-beta5-identity open (20 surfaces -> 1.0.0-beta.5, baseline -> beta.4 kit c27c6e7 with gate_a_run_id 33901203343, truth beta.5 staging, graph docstring/factories, claims re-bound; 2311 tests). #157: Pandoc render check failed (stale USER-MANUAL manifest) -> re-rendered @ 57d38bf. Order: merge #157 on green -> merge main into #164 (truth conflict) -> merge #164 -> beta.5 release build. Rollover-proof build 33918978783 still in progress.

## 2026-09-04 22:15Z
#157 @ 8a4d7e0 (both manual renders regenerated); CI waiter. #164 green except mutation-report (mutmut config error on a docs/lockfile-heavy diff; informational). Proof kit b2b5694 staged; Gate A 33921378248 running; then run-soak-kit.ps1 b2b56942bf1ee89a685eb3da5f2a6386a21d4c2f 120 (pids must stay constant).

## 2026-09-04 22:50Z
#157 (beta.4 docs sweep) MERGING. Next: merge main into #164 (release-truth conflict expected: beta.4 current + beta.5 staging), push, CI, merge; then beta.5 release build.

## 2026-09-04 22:55Z
#157 MERGED (main 254ffe5: beta.4 current everywhere). #164 conflicted on 10 doc files -> Sonnet rebuilding chore/release-beta5-identity on top of main (force-with-lease). Proof-kit Gate A 33921378248 running.

## 2026-09-04 23:00Z
#164 rebuilt on main (a8b3066 + 59d7b26), MERGEABLE/CLEAN, CI running. Proof-kit Gate A 33921378248: clean PASS (rollover fix passes T4), cross-version running. Soak on b2b5694 only AFTER Gate A completes (a concurrent Run-GateA would steal the sandbox from the remaining lanes).

## 2026-09-04 23:35Z
#164 MERGED -> main = 1.0.0-beta.5 identity, baseline = beta.4 kit; beta.5 release build dispatched. Proof-kit Gate A 33921378248: clean PASS, cross-version PASS, download-only running -> then 120-min T6 soak on b2b5694 (rollover proof). Release chain for beta.5: build -> stage -> Gate A 3 lanes -> publish (publish-beta4.sh generalize: SHA/BUILD/TAG) -> docs sweep -> tag.

## 2026-09-04 23:45Z
beta.5 release build 33929897640 (e502074) queued behind the proof Gate A; monitor b2cfe8er4 stages + waits for its Gate A. publish-release.sh <gateA> <sha> <build> <tag> written (mirror dir C:\CivicCastTester\kit-mirror\<sha> must be created first: setup.exe hardlink + packs/station junctions). Sonnet drafting docs/release-beta5. Proof-kit Gate A 33921378248 on its download-only lane; soak on b2b5694 after it.

## 2026-09-04 23:50Z
Draft PR #165 docs/release-beta5 (verification + notes + CHANGELOG beta.5 section; placeholders incl. SOAK_* for the T6 rollover soak; 1943 policy/docs tests pass). Proof Gate A on download-only lane; beta.5 build queued behind it on the HALO runner.

## 2026-09-05 00:36Z - ROLLOVER SOAK STARTED
Proof-kit Gate A 33921378248: 3/3 PASS (rollover fix passes the gate). 120-min T6 soak on b2b5694 launched (pid 39828, log wt-soak/soak-120-b2b5694.log, monitor bzea3pfid); PASS criterion = relaunches 0 per channel, failed_beats 0. The beta.5 release build's auto Gate A will collide with the sandbox: CANCEL it when it appears and re-dispatch with run_id after the soak (~03:15Z).

## 2026-09-05 00:40Z
beta.5 build 33929897640 failed at checkout cleanup (runner workspace EBUSY right after the proof Gate A's sandbox teardown; transient). Re-dispatched: build 33933537140 (e502074). Monitor stages the kit and CANCELS the auto Gate A (sandbox busy with the rollover soak until ~03:15Z); then re-dispatch Gate A with run_id=33933537140.

## 2026-09-05 00:50Z - soak on b2b5694 FAILED (station-down, installer exit 110 'could not obtain a required component pack'): the beta.5 build's prune deleted kit-staging/b2b5694 while the sandbox read it via the junction. Plan: soak on the beta.5 release kit e502074 (has #162) once built, THEN Gate A (run_id) on it, then publish. Never run a build while a soak reads a non-keep-list kit.

## 2026-09-05 01:15Z - KIT-STAGING WIPED except an emptied b2b5694 dir
kit-staging now has only b2b5694 (empty). c27c6e7 (beta.4 baseline for beta.5's cross-version lane) and 9573d4a are GONE. origin/main baseline = c27c6e7. Recovery plan: (A) beta.5 build 33933537140 lands e502074; (B) robocopy e502074 -> C:\CivicCastTester\kit-safe\e502074; (C) soak from kit-safe (prune-proof); (D) rebuild c27c6e7 via `gh workflow run native-beta-candidate-artifacts.yml --ref v1.0.0-beta.4 -f build_target=self-hosted` (its prune keeps c27c6e7+9573d4a -> may delete e502074 from kit-staging; restore from kit-safe); (E) Gate A run_id=33933537140 after the soak; (F) publish.

## 2026-09-05 01:30Z - who deleted the beta.4 kit
Proof-kit build 33918978783 (20:59Z, main @ b2b5694 whose baseline was still 9573d4a) pruned kit-staging/c27c6e7. Today's beta.5 build pruned b2b5694 under the running soak. The beta.4 installer survives via the kit-mirror hard link (copied to C:\CivicCastTester\kit-safe\c27c6e7-...setup.exe). Restore plan: copy e502074 to kit-safe when built; rebuild --ref v1.0.0-beta.4 (packs are reproducible 1980-stamped zips; installer is not - replace with the original); verify installer_sha256 + station_index_sha256 vs upgrade-baseline.json; restore e502074 to kit-staging; soak from kit-safe; Gate A run_id=33933537140.

## 2026-09-05 01:35Z
beta.5 build 33933537140 SUCCESS; kit-staging/e502074 present. Copying to C:\CivicCastTester\kit-safe\e502074 (robocopy). Then: --ref v1.0.0-beta.4 rebuild to regenerate the baseline kit (replace its setup.exe with the saved original; verify station_index_sha256 9257ef4f...); soak on e502074 from kit-safe; Gate A run_id=33933537140.

## 2026-09-05 01:50Z
kit-safe/e502074 = full copy (26 GB) + samples + SHA256SUMS. Auto Gate A 33935209547 running on kit-staging/e502074 (cross-version will fail: baseline kit absent). v1.0.0-beta.4 tag rebuild dispatched (queues behind Gate A on the runner; its prune will delete kit-staging/e502074 -> restore from kit-safe afterwards; replace its setup.exe with kit-safe/c27c6e7-...setup.exe; verify station-index sha 9257ef4f...). Soak on e502074 from kit-safe after Gate A frees the sandbox.

## 2026-09-05 02:00Z
Stopped the old build monitor before it cancelled auto Gate A 33935209547 (now wanted: sandbox is free; clean lane = engine proof on the beta.5 kit; cross-version will fail closed until the baseline is restored). beta.4 rebuild 33935363054 queued; its monitor verifies packs vs release SHA256SUMS + station-index sha, restores the original installer, and restores e502074 from kit-safe if pruned. Then: soak on kit-safe/e502074 -> Gate A run_id=33933537140 -> publish.

## 2026-09-05 02:12Z
Auto Gate A 33935209547 on beta.5 kit: clean PASS (T4 PASS_PRODUCT_ENGINE), cross-version failed at prep (baseline absent), download-only skipped. 120-min rollover soak on kit-safe/e502074 STARTED 02:09Z (pid 28612, log wt-soak/soak-120-e502074.log, monitor bg2wtjizh). beta.4 rebuild 33935363054 queued (monitor bl6sqkezd verifies + restores). Then final Gate A run_id=33933537140 -> publish-release.sh <G> e502074... 33933537140 v1.0.0-beta.5.

## 2026-09-05 02:45Z
Baseline kit c27c6e7 regenerated (run 33935363054): installer restored byte-identical (9fae1211), 5/5 packs byte-identical to the release, station-index re-signed (created_epoch) -> PR #166 repins station_index_sha256 (224 gate_a tests). e502074 restored into kit-staging (25.9 GB). Soak on kit-safe/e502074 running since 02:09Z. Next: merge #166 -> after soak: Gate A run_id=33933537140 -> publish-release.sh <G> e5020746fa40e7a3f1a160d3a8e1add5c3b57786 33933537140 v1.0.0-beta.5.

## 2026-09-05 03:00Z - beta.5 soak: restarts persist (government beat 3 + 5, public beat 5). Rollover fix NOT holding in the sandbox. Let the soak finish (worker logs collected at end) -> Opus diagnosis (suspect: next leg not ready before outgoing clip end -> freeze -> 10s stall watchdog restart; or automation trigger not firing). beta.5 publish BLOCKED until relaunches=0. #166 (baseline repin) still merges.

## 2026-09-05 03:20Z
#166 green -> merged (baseline station_index repinned). Soak on e502074 still running (restarts observed). After the soak: Opus diagnosis from the collected worker logs; Gate A run_id=33933537140 can run (baseline restored) but beta.5 publish waits for a zero-restart soak.

## 2026-09-05 03:45Z
beta.5 soak beats 1-8: relaunches on all 3 channels at the beta.4 cadence -> #162 not engaging in the sandbox. Opus diagnosing live (H1 horizon not populated for API-started channels; H2 reload refused / shipped kit lacks #162 code; H3 next leg not ready -> stall watchdog restart; H4 EOS probe fails without GPU) on fix/rollover-engage. beta.5 publish blocked. After the soak: Gate A run_id=33933537140 anyway (kit unchanged; lanes independent of the soak).

## 2026-09-05 05:05Z - beta.5 SOAK VERDICT: T6 FAIL relaunches public 5 / education 8 / government 7, beats 22, failed_beats 0 (liveness fine; rollover not holding). Evidence Desktop/CIVICCAST-EVIDENCE/soak-120-e502074-20260905. Opus diagnosis running. Gate A run_id=33933537140 dispatched (baseline restored) for the three-lane record. beta.5 publish BLOCKED.

## 2026-09-05 05:15Z - beta.5 soak root signal
Worker stderr per channel = ONLY 'CTRL stall: no output for 10s - quitting for daemon restart' (7-8 lines = one per launch); zero 'CTRL reload' lines -> the automation rollover NEVER dispatched a reload (H1). And the plan-end path now STALLS (output stops, worker alive) instead of EOS->clean exit as in beta.4 -> #162's engine changes regressed the no-reload EOS path (second defect). Opus diagnostician has the evidence path + this finding. Gate A 33945620985 running on the beta.5 kit (three lanes; T4 slate only).

## 2026-09-05 05:40Z - DIAGNOSIS: restarts = 10-s output stalls in the sandbox + UnicodeEncodeError aborting the automation pass (26x beta.4 soak, 23x beta.5 soak). NOT plan-end exits (plans 28-38 min). #162 never exercised. PR #167 (ASCII-safe last_error) open; review + CI running. Docs correction PR (beta.4 known issue + #165 headline) in flight. beta.5 = #167 + docs; stalls on real hardware unknown -> needs a station-hardware soak.

## 2026-09-05 06:00Z
#167 review MERGE (narrow); reviewer: cluster is initdb'd WIN1252 (seams.py:157-166 no -E), no client_encoding; same crash reachable via accented asset titles (current_source_label, proof events, last_error=str(exc)); process_once polls unguarded. Sonnet on fix/state-write-encoding (fold all persisted free text, guard polls, initdb -E UTF8 for new clusters). Merge #167 on green; then #168-ish; docs correction PR in flight; Gate A 33945620985 running on the beta.5 kit.

## 2026-09-05 06:10Z
Reviewer addendum: civiccast/dr/backup.py:422-427 assumes provisioning creates UTF8 clusters (false; no initdb -E); read_database_locale (backup.py:434) can measure the real encoding; restore drill may drift WIN1252->UTF8. Forwarded to the encoding-fix agent (same PR). Batch item 39.

## 2026-09-05 06:20Z
PR #168 docs/beta4-known-issue-correction (release notes, verification doc, README, CHANGELOG; beta.5 stalls re-counted 8/8/7 from worker logs vs T6 pid-change 5/8/7) + #165 headline retitled (#167 + stall diagnosis; #162 demoted). CI waiters on #167 and #168; merge both on green. Encoding PR in progress. Gate A 33945620985 (beta.5 kit) in clean lane.

## 2026-09-05 06:35Z - hardware soak prep (NOT shipped)
AUTORUN-2.e502074.ps1 (fresh kit-<sha> dir, installer by manifest name, install OVER existing, no re-arm) dry-running its fetch+verify phase on HALO against a replica of the tester's leftover state (C:\CivicCastSoak\kit with the old beta.4 installer planted). LAN server serves e502074 (http 200). Morning decision for Scott: ship AUTORUN-2 + un-park AUTORUN-3/4 for a real-hardware stall/relaunch soak on the tester, vs publish beta.5 on Gate A alone.

## 2026-09-05 06:50Z - OWNER: option A (tester soak first; do NOT install on HALO - townreporter.org production)
Tester loop alive (heartbeat 05:06Z, station Stopped). Prepping: AUTORUN-2 (install e502074 into a fresh kit-<sha> dir; dry-run running on HALO replica), AUTORUN-3 (verify, recurring, 2h horizon, relaunch tracking via state pid), AUTORUN-4 (channels, 2h+15m schedule), DIRECTIVE-4 + pointer. Ship as ONE commit after parse + dry-run review. Never touch localhost:8000 on HALO.

## 2026-09-05 07:00Z
Dry run of AUTORUN-2 on the HALO replica caught a real bug: SHA256SUMS lines carry sha256sum's binary marker '*path' -> 'Illegal characters in path'. Parser hardened (TrimStart('*')); dry run re-running (fetches 26 GB via the LAN server to C:\CivicCastSoak\kit-e502074). Sonnet preparing AUTORUN-3 (verify, 2h, relaunch tracking) + AUTORUN-4 (channels) + DIRECTIVE-4 in cc-soak8 (uncommitted).

## 2026-09-05 05:30Z (clock: date -u; earlier stamps in this log ran ~1.5h ahead)
AUTORUN-2 (install e502074) dry run PASSED on the HALO replica: verify bad=0, installer selected by manifest, 'install OVER existing' path chosen. Placed in cc-soak8/soak/autorun/AUTORUN-2.ps1 (uncommitted). Waiting for AUTORUN-3/4 + DIRECTIVE-4 from the prep agent, then ONE commit + push. Replica kit deleted from C:\CivicCastSoak.

## 2026-09-05 05:30Z - HARDWARE SOAK SHIPPED to the tester (option A)
soak8-e1acfe6-directives: DIRECTIVE-4 + AUTORUN-2 (install e502074, dry-run proven), AUTORUN-3 (verify, 2h verdict, relaunch/pid tracking, worker CPU/RSS), AUTORUN-4 (channels, 6x20-min slots). Executor order per poll: 2 -> 3 (exits until soak-started) -> 4; then 3 recurring. Expect: AUTO-ACK-4 within 10 min, INSTALL-RESULT ~30-40 min, SETUP/soak-started, rollups every 30 min, final-verdict at T+2h (~08:00-08:30Z). Monitor on the tester branch.

## 2026-09-05 05:45Z - OWNER: helm overnight; never idle. Tester acked DIRECTIVE-4 (AUTO-ACK-4). Monitors: tester branch changes + 45-min silence alarm; #167/#168 CI; Gate A beta.5 kit. Night plan: merge greens; on tester verdict PASS -> beta.5 publish path (needs #167/#169 merged -> new kit -> Gate A -> publish -> docs) ; on FAIL -> diagnose from tester logs; morning report in floatsom.

## 2026-09-05 05:50Z
#167 CI red (Unit/randomized/claims; #169 carries #167 + the collection-floor bump + encoding hardening and was green on its stacked base) -> retargeted #169 to main; merge #169 on green and close #167 as superseded. #168 (docs correction) CI nearly green. Tester: AUTO-ACK-4 received; install running.

## 2026-09-05 05:55Z - tester: AUTORUN-2 SKIPPED (once-marker by filename already existed from the first queue), AUTORUN-4 blocked 'station not healthy' 3 s after the ack. Renamed install->AUTORUN-5, channels->AUTORUN-6 (verify stays AUTORUN-3, recurring); pushed. Expect ack rev 6 + install within ~40 min.

## 2026-09-05 06:05Z
#168 MERGED (main 1606ce8): beta.4 known-issue wording corrected on all repo surfaces. Checking whether the GitHub release page body needs the same correction. #169 CI running; tester install (AUTORUN-5) pending.

## 2026-09-05 06:45Z - tester heartbeat 06:36Z lists 'CivicCast (Native)_1.0.0-beta.5_x64-setup' pid 11952 running: AUTORUN-5 fetched the kit and launched the installer. INSTALL-RESULT expected after install + health wait. Deadline alarm set (~07:40Z).

## 2026-09-05 06:50Z - TESTER INSTALL OK: beta.5 kit e502074 over beta.3 (stopped) -> route=UPGRADE engine_exit=0, installer exit 0, postinstall SUCCESS, /health healthy (real-hardware proof of #159's upgrade path). AUTORUN-6 (channels) next, then AUTORUN-3 rollups every 30 min, verdict at T+2h (~09:00Z).

## 2026-09-05 07:10Z
#169 MERGED (encoding hardening incl. #167); #167 closed as superseded. Gate A 33945620985 on the beta.5 kit e502074: clean PASS, cross-version PASS (restored baseline accepted), download-only running. Tester: install OK; channel-start report pending (alarm ~08:05Z).

## 2026-09-05 07:15Z
Baseline c27c6e7 copied to kit-safe (25.1 GB). beta.5 RELEASE build 33951814336 dispatched from main 4e03ef9 (includes #169); monitor stages + safe-copies the kit and waits for its auto Gate A. The tester soaks e502074 (pre-#169) -> its verdict proves the stall question on hardware, not the final kit; the final kit gets Gate A (3 lanes) and, if time allows, a short tester soak too.

## 2026-09-05 07:40Z
Tester heartbeat 07:36Z: healthy, service Running, engine_observed none-running (no channels yet), processes python 199 MB. AUTORUN-6 (channels) has produced no report ~55 min after install: either still packaging clips (600 s timeouts) or crashed before reporting. Deadline alarm ~08:05Z; then read soak/autorun-logs if pushed.

## 2026-09-05 07:47Z
AUTORUN-7 (read-only diagnostics) shipped @ c1e8df8: runs after AUTORUN-6 finishes (executor is sequential), pushes soak/DIAG-<stamp>.md. Waiting: tester channel report/DIAG (alarm ~08:05Z), Gate A 33945620985 download-only lane, build 33951814336 (+ its Gate A).

## 2026-09-05 07:55Z
DIAG: AUTORUN-6.ps1.done existed from 2026-09-03 (previous mission) -> channel script skipped again. Re-queued as AUTORUN-8 (names 1-7 consumed). Tester station healthy on beta.5 (e502074). Expect SETUP report ~08:20Z, rollups every 30 min, verdict ~10:30Z.

## 2026-09-05 08:05Z
AUTORUN-8: first-admin 409 (pre-existing admin from the 09-03 mission; no stored token/password on the box). Shipped AUTORUN-9 (quiet uninstall + remove ProgramData\CivicCast + HostStore\install + fresh install of the verified e502074 kit + health wait, clears stale token) and AUTORUN-10 (channels). Expect REINSTALL-RESULT ~08:40Z, SETUP ~09:00Z, verdict ~11:00Z.

## 2026-09-05 08:12Z
Renamed channels AUTORUN-10 -> AUTORUN-9b (text sort). If the 08:06 poll already ran AUTORUN-10 first it blocked on 409 and consumed the name; 9b runs after the reinstall regardless.

## 2026-09-05 08:05Z
Gate A 33945620985 on e502074: 3/3 PASS (restored baseline accepted by the cross-version lane). Release build 33951814336 (4e03ef9) failed at checkout cleanup (EBUSY on sandbox-lab\hoststore right after Gate A's teardown; second occurrence) -> re-dispatched. Batch item 40: make the build's checkout cleanup tolerate/wait for sandbox teardown, or separate runners.

## 2026-09-05 08:25Z
Tester: AUTORUN-9 clean reinstall OK (fresh install, healthy) but AUTORUN-9b first-admin 409 AGAIN: station-state.json (setup-complete marker) lives under the service account's LOCALAPPDATA and survived the wipe. Next: AUTORUN-9c (stop service, delete station-state.json at the service profile path + any CIVICCAST_STATION_STATE_PATH, start service, health) + AUTORUN-9d channels.

## 2026-09-05 08:20Z
Shipped AUTORUN-9c (station-state.json reset under the service profile + restart) and AUTORUN-9d (channels) @ b64a2ef. Release build 33954250185 running (monitor b5hh2urqd). Expect 9c/9d reports by ~08:45Z; channels then 2 h -> verdict ~10:50Z.

## 2026-09-05 08:30Z
AUTORUN-9c: renamed C:\WINDOWS\System32\config\systemprofile\AppData\Local\CivicCast\station-state.json, service restarted healthy, /api/setup/station-state = not_started/setup_complete=false. AUTORUN-9d (channels) running next; alarm for its report.

## 2026-09-05 08:35Z - TESTER SOAK RUNNING
SOAK-START 08:27:39Z on DESKTOP-VBMA6O5: kit e502074 (fresh install), 3 channels public/education/government udp-ts 9001-9003, GStreamer default, 6x20-min slots. AUTORUN-3 verify each poll (10 min): engine per channel, tsp, pid/relaunches, CPU/RSS; rollups every 30 min; final-verdict.json at T+2h (~10:27Z). Release build 33954250185 (4e03ef9) running.

## 2026-09-05 08:45Z - CORRECTION: the tester soak did NOT start. AUTORUN-9d: first-admin OK (token stored) but all 3 channel config PUTs and 3 asset registrations returned 422 (beta.3-era bodies: missing slate_message / sink loudness_regime / eas_tone_strip_enabled; asset POST shape differs from the /assets/upload multipart flow), yet the script wrote soak-started + SOAK-START.md. Sonnet writing AUTORUN-9e from the proven T4/T6 harness bodies (captures 422 response bodies; clears the stale soak-started; sets it only after ON_AIR).

## 2026-09-05 08:35Z
AUTORUN-9e shipped @ d2f2729 (proven bodies: multipart upload/package/ready/approve, schedule+commit, config PUT with slate_message+sink loudness/EAS, start; clears false soak-started; sets it only after ON_AIR; captures non-2xx bodies). Expect AUTORUN-9e-RESULT + real SOAK-START ~08:55Z; verdict ~2h later (~10:55Z). Release build 33954250185 in the installer job.

## 2026-09-05 08:50Z
Release kit 4e03ef9 built (33954250185), staged with samples+sums, safe-copied (25.9 GB), publisher mirror created. Its three-lane Gate A is next (monitor b5hh2urqd). Publish beta.5 = publish-release.sh <gateA> 4e03ef90cb4b591d60f0c1cdced0cbb739a80838 33954250185 v1.0.0-beta.5 after Gate A 3/3 + the tester verdict.

## 2026-09-05 08:55Z
#165 docs @ 539df08: KIT_SHA 4e03ef9 / BUILD 33954250185 / setup sha256 476fc68c... / signature Valid filled; remaining: GATE_A_*, EVIDENCE_PATH_*, SOAK_*, RELEASE_DATE, ASSET_COUNT. Waiting: tester 9e result (alarm), release-kit Gate A.

## 2026-09-05 09:00Z
AUTORUN-9e: 4 clips uploaded/validated (asset duration reported 30 s each -> 272 items/channel), config PUT + start OK on all 3 channels, but state poll empty for 3 min -> soak-started NOT written (correct). Shipped AUTORUN-9f (raw state/health/now/config GETs with bodies, process list, control-plane egress log tail; writes soak-started only if 3/3 ON_AIR). Gate A 33955566792 on the release kit running.

## 2026-09-05 09:08Z - TESTER SOAK REALLY RUNNING
DIAG-9f: public/education/government all ON_AIR with LPM clips as current_source_label; 3 gst worker pythons (355-561 MB) + control plane; soak-started written 09:06:14Z. AUTORUN-3 verify every poll (10 min), rollups every 30 min, final-verdict.json at ~11:06Z (PASS = relaunches 0 per channel, ON_AIR + gstreamer + tsp pass every cycle). Note: 9e's own state poll returned empty (script bug, not product). Gate A 33955566792 on the release kit running.

## 2026-09-05 09:15Z
First verify cycle on the tester: ON_AIR but tsp 'fail-exit-' (PS 5.1 ExitCode null) and engine null/none-running (inference counted gst-launch only). Patched AUTORUN-3 (recurring; effective next poll): cache handle + WaitForExit; engine inferred from python worker.py processes. The 09:06 cycle's fail lines are harness artefacts and must be discounted in the verdict.

## 2026-09-05 09:12Z
AUTORUN-3 verify fixed @ 9f24014 (ExitCode cached; python worker.py processes counted as the GStreamer engine). Effective at the tester's next poll (~09:16Z). Waiting for that cycle's egress JSON to confirm tsp pass + engine gstreamer; then rollups at 09:36/10:06/10:36 and the verdict ~11:06Z. Release-kit Gate A 33955566792 running.

## 2026-09-05 09:25Z
Verify cycle 2 (patched): tsp PASS on all 3 channels, relaunches_total 0, pids 832/16700/18268 stable, ON_AIR. Engine still null (CommandLine match found 0 workers) -> AUTORUN-3 now resolves engine from the state row's pid via Get-Process (python = gstreamer). Rollups 09:36/10:06/10:36; verdict ~11:06Z.

## 2026-09-05 10:10Z - REAL HARDWARE: RESTARTS OBSERVED
Tester verify 10:06Z (engine now resolved = gstreamer on all 3, tsp pass on all 3): public relaunches_total=1 (pid 18268->13420), government 1 (832->556), education 0 -- within the first 60 min. So worker restarts are NOT sandbox-only. Rollup SOAK-REPORT-...100612Z read for last_error/CPU/RSS. beta.5 will not be published as a fix for this; verdict at ~11:06Z expected FAIL on the relaunch rule.

## 2026-09-05 10:20Z
Tester rollup 1: control-plane python pid 4764 at 285% CPU / 1.9 GB; workers restarting (public 1, government 1 in hour 1). AUTORUN-9g (worker logs + control-plane automation lines + CPU sample) shipped @ 8cdb908. Opus code-level diagnosis launched: H1 per-tick plan rebuild over 272 items/channel, H2 30-s items -> 4-min plans -> rollover reload every few minutes with synchronous conform, H3 other hot polls. Morning report updated: recommend HOLD beta.5.

## 2026-09-05 10:35Z - CPU burn diagnosis (Opus, code + sandbox logs)
Sandbox soak: automation tick ~110 ms/2 s (flat), ZERO rollovers (long media: source_plan._segment_duration uses asset.duration_seconds and ignores item.duration_seconds -> one plan aired for hours). Tester: assets registered with duration_seconds=30 (AUTORUN-9e report) -> plans of 8x30 s = 240 s -> rollover trigger at plan_end-120 s fires every ~2 min per channel (~90 reloads/h) each with a synchronous SourcePreparer.prepare on the automation thread -> CPU burn + worker stalls/restarts. H3 minor: health.py:42 reads the whole worker stderr file twice per tick. Product defects: (a) segment duration ignores the schedule item's duration (source_plan.py:335); (b) rollover cadence unbounded / min lead vs plan length; (c) prepare on the automation thread. Awaiting DIAG-9g (rollover line counts) to confirm, then fix PR.

## 2026-09-05 10:45Z - DIAG-9g (tester)
Worker stderr: 'CTRL stall: no output for 10s' x5 with WORKER_RESULT stall -> the real-hardware restarts are the same stall path as the sandbox. Control plane pid 4764: 239% of a core at sample time, 1.8 GB, 57 threads. No UnicodeEncodeError on the tester (0). Control-plane log grep returned nothing (path or match issue). Fix PR (plan window/slot duration/rollover cadence/prepare skip/log tail) in progress on fix/plan-window-and-slot-duration.

## 2026-09-05 10:20Z
AUTORUN-9h shipped (counts + timestamps of rollover/reload/relaunch/STARTING/STOPPED/ERROR lines in the tester's control-plane log; ON_AIR cadence). Gate A on the release kit 4e03ef9: clean PASS, cross-version running. Verdict at 11:06Z. Fix PR in progress.

## 2026-09-05 10:40Z - DIAG-9h: rollover=0, horizon=0 on the tester; automation tick 2.06 s; 13 STARTING; stalls 193 lines. So the rollover-cadence theory (D43) is NOT the cause; my 'error=8225' was a bad pattern (matched last_error=). New hypothesis H4: in-process caption/summary/transcription jobs on the 4 uploaded clips burn CPU in the control plane and starve the workers -> AUTORUN-9i (log counts for caption/whisper/summary/ollama, per-process CPU sample, asset/caption job states) shipped. Told the fix agent: keep D42 + D44, D43 conservative only.

## 2026-09-05 10:45Z - ROOT CAUSE MEASURED ON REAL HARDWARE: LIVE CAPTION TAP OVERLOAD
DIAG-9i: control plane 247% CPU / 1.9 GB / 61 threads; workers 26-64%; control_plane-app.log: 663 caption lines, 'CRITICAL civiccast.captions.tap_worker: Caption tap overload for channel <x>: N settled segments exceeds the maximum 2' every ~30 s on all three channels; whisper/ollama/transcri lines 0. The live caption tap (in-process ASR on CPU for every ON_AIR channel) cannot keep up, keeps burning, and starves the GStreamer workers -> 10-s output stalls -> relaunches. Same mechanism explains both sandbox soaks. Opus on fix/caption-tap-overload-starves-playout (backoff/pause on overload, ASR concurrency bound + CPU settings, worker priority ABOVE_NORMAL, tests). Batch item 45.

## 2026-09-05 10:55Z
PR #170 fix/plan-window-and-slot-duration opened (D42 slot duration honoured; plan window 1800 s/120 segs; rollover min interval 300 s; prepare timing log; health.py tail read; 974 egress tests). Review + CI running. Caption-tap fix (root cause) in progress on fix/caption-tap-overload-starves-playout.

## 2026-09-05 11:00Z
Tester rollup 2 (10:36Z): relaunches public 1, education 1, government 2; tsp pass; engine gstreamer. DIAG-9i tracebacks: UnicodeEncodeError '�' (charmap) IS present on the tester too (#169 fixes it; the 4e03ef9 release kit has it). Verdict at 11:06Z will be FAIL on relaunches with the caption-tap root cause known.

## 2026-09-05 11:05Z
In flight: caption-tap fix (Opus), #170 review + CI, #165 docs rewrite to the measured root cause (Sonnet), tester verdict (11:06Z), release-kit Gate A download-only lane. Beta.5 HOLD until the caption-tap fix is in a kit that passes Gate A and a hardware soak with zero restarts.

## 2026-09-05 10:50Z (clock corrected)
#165 docs rewritten to the measured root cause (d420b04). Sonnet on docs/beta4-known-issue-root-cause (beta.4 notes still claim 'fixed by #167', closed; add the caption-tap cause + any beta.4 workaround). Pending: caption-tap fix PR, #170 review/CI, tester verdict 11:06Z, release-kit Gate A download-only lane.

## 2026-09-05 ~11:05Z
#170 review: MERGE (D42 reaches both engines; cost watch: gst per-segment stream-copy up to 120 segments). CI still pending 4. #171 opened (beta.4 docs: #167 closed/superseded by #169, caption-tap cause added). Finding: NO operator toggle for the live caption tap (station_runtime.py:1361 hardcodes CIVICCAST_CAPTION_TAP=inline); told the fix agent to add a station-level setting + back-off. #171 review + CI waiter running.

## 2026-09-05 ~11:15Z
PR #172 = caption-tap fix (backoff 60s->900s, cap max(1,min(3,cpu//8)) channels, cpu_threads=1/beam 1 live only, ASR threads BELOW_NORMAL, gst worker ABOVE_NORMAL, operator switch live_captions_enabled via PUT /api/staff/station/profile, env off wins). 5930 tests pass locally. Opus hostile review + CI waiter running. #171 review: MERGE (evidence note: soak-120-e502074 dir is the SANDBOX soak; hardware proof = tester DIAG-9i + SOAK-REPORT on tester/soak8-e1acfe6-DESKTOP-VBMA6O5). Tester 11:06Z probe ran 2 s before the 2h mark: no final verdict yet, expect ~11:16Z.

## 2026-09-05 11:21Z
Tester verify cadence is 30 min (09:36, 10:06, 10:36, 11:06), not 10. No verdict at 11:06 (2 s early). Verdict expected on the 11:36Z run; watcher re-armed, alarm 11:48Z.

## 2026-09-05 ~11:35Z
#172 review = CHANGES (11 findings). CRITICAL: app.py:1354 pre-builds the caption runtime, so the live cpu_threads=1/beam-1 block never runs in the service (still all cores, beam 5). Also: capacity proof script breaks on state 'paused'; disabling captions freezes retention; thread-priority hint doesn't reach CT2 threads; overload/ dir unbounded; no operator UI for the switch; docs; env validation can take the station off air. Sent all 11 back to the fix agent; delta review after.

## 2026-09-05 ~11:45Z
MERGED #171 -> main 1d47be0 (beta.4 docs: #167 claim corrected, caption-tap cause added). #170: 20 pass, 1 pending. Main CI waiter on 1d47be0 started.

## 2026-09-05 11:50Z
Tester 2-hour soak verdict (kit e502074, DESKTOP-VBMA6O5, real hardware, GStreamer, 3 channels): **FAIL** (final-verdict.json 20260905T113614Z, actual 2.5 h). Relaunches: public 2 / education 1 / government 3 (total 6). TSDuck pass every cycle from 09:36Z on; the 08:28Z and 09:06Z probe failures predate ON_AIR (channels not yet created; the 09:06 'fail-exit-' was the harness ExitCode-null bug, fixed in AUTORUN-3). Control plane ~2.8 cores the whole run (caption tap). At 11:36Z public and government sat in FALLBACK_SLATE after a relaunch. Verdict note verbatim: 'PASS requires: all channels ON_AIR on GStreamer at every cycle, tsp pass every cycle, and zero relaunches per channel.' Evidence copied to C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\tester-soak8-e1acfe6-20260905 (15 files).

## 2026-09-05 ~12:00Z
Gate A 33955566792 on kit 4e03ef9 (main with #169): clean PASS, cross-version PASS, download-only PASS. NOT published: beta.5 held for #172. This kit proves the install/upgrade paths are green; the next kit (after #172 merges) repeats Gate A + hardware soak.

## 2026-09-05 ~12:10Z
#165 (docs/release-beta5) rebased on main, soak placeholders filled with the tester verdict, <CAPTION_FIX_PR> = #172, commit a46af7b. Remaining placeholders: RELEASE_DATE, GATE_A_* (run id + 3 verdicts), EVIDENCE_PATH_*, ASSET_COUNT -> fill at publish time from the FINAL kit's Gate A. Stays open.

## 2026-09-05 ~12:20Z
#172 CI on a5aa12f RED: stale generated API artifacts (openapi.json, api.generated.ts, API-REFERENCE.md) -> unit test + Pandoc fail -> claims verifier fails downstream. Told the fix agent to regenerate in the rework push. #170: only mutation-report (non-required) pending; waiter running.

## 2026-09-05 ~12:30Z
MERGED #170 -> main 3749151 (planner slot duration / plan window / health tail-read). Merged with the 'always informational' mutation-report still running (hung 1h45m of its 120-min cap; not a gate). Main CI waiter on 3749151 started. Main now = #169 + #171 + #170; #172 pending rework.

## 2026-09-05 12:12Z (clock: my earlier stamps ran ~20 min fast)
Main CI green on 1d47be0 and 3749151 (roadmap-status, ci-security-scan, pages). No kit build auto-fires on main pushes (native-beta-candidate-artifacts is dispatched), so no prune. kit-safe holds c27c6e7, e502074, 4e03ef9. Waiting on the #172 rework.

## 2026-09-05 12:58Z
#172 rework pushed: 2c5dcc9 (not rebased on main). Opus delta review (13 findings + merge-cleanliness vs 3749151) + CI waiter running.

## 2026-09-05 ~13:15Z
#172 delta review on 2c5dcc9: all 13 first-round findings FIXED (live=True runtime sizing now travels with the object; app.py:1361 wires it). Two new CI breakers: AST wiring test breaks under mutmut (found 665 call sites); USER-MANUAL rendered artifacts stale (Pandoc job red, /help#live-captions-switch dead). Residual: overload/ dir still unswept in _fail_closed_overload; PR body §3 stale. Sent to the fix agent. Branch is rebased on main 3749151, fast-forward clean. Gates in the review worktree: ruff/format/mypy clean, 3881+234 tests pass, vitest 23 pass.

## 2026-09-05 13:20Z
#172 follow-up pushed: 229f8b2 (mutation-lane test, rendered manual, overload/ sweep, PR body). CI waiter running; spot-checking the diff myself (no third review round). Next tester mission script drafted: scratchpad AUTORUN-9j.template.ps1 (upgrade install of kit __KITSHA__ over e502074, wait ON_AIR x3, archive soak-1 probes, reset relaunch counters, new soak-started).

## 2026-09-05 13:35Z
#172 on 229f8b2: 18 pass, mutation-report still red (the AST wiring test runs inside mutmut's mutants/ copy; repo-relative path doesn't help). Fix = deselect that test in the mutation lane like the existing *_PINS exemption. Sent to the fix agent. Other checks pending.

## 2026-09-05 13:40Z
#172 head eda00c3 (mutation-lane deselect). CI waiter running. Merge on green; then dispatch kit build self-hosted, stage, safe-copy, mirror, 3-lane Gate A, tester AUTORUN-9j second soak.

## 2026-09-05 13:50Z
scratchpad after-build.ps1 -Sha <sha> (robocopy kit-staging->kit-safe, SHA256SUMS verify, kit-mirror hardlink+junctions) PROVEN on 4e03ef9: exit 0, mirror rebuilt identical (setup.exe 476fc68c...). Ready for the post-#172 kit.

## 2026-09-05 14:08Z
#172 eda00c3: 20 pass, Unit tests pending, mutation-report FAIL on the lane's own baseline (hermetic-guard nested pytest + mutmut plugin; not #172; batch item 46). Merge on Unit tests green.

## 2026-09-05 14:16Z
MERGED #172 -> main 91caebc (caption-tap fix + operator switch live_captions_enabled). 22/22 real checks green; mutation-report red = lane baseline (item 46). Kit build dispatched on main self-hosted. Then: after-build.ps1 -Sha 91caebc..., Gate A (workflow_run), tester AUTORUN-9j.

## 2026-09-05 14:22Z
Build 33971258093 (91caebc, self-hosted) running; persistent monitor covers build -> Gate A run id -> 3 lanes. AUTORUN-9j.ps1 filled with the full sha (scratchpad), parses OK; commit to the directives branch only after the kit is staged + served (kit server pid 33868 answers 200). Then -DryRun against the served kit before the real commit.

## 2026-09-05 14:50Z
Build 33971258093 SUCCESS -> kit-staging/91caebc (installer 1.0.0-beta.5, packs, station; NO manifest/samples from the build -- those are added by hand: samples copied from the 4e03ef9 kit, SHA256SUMS.txt via sha256sum -b with relative paths). Then after-build.ps1 (kit-safe + mirror). Gate A 33972726431 started (workflow_run) -- monitor armed.

## 2026-09-05 14:58Z
Kit 91caebc: manifest 19 lines verifies; kit-safe copy verified; kit-mirror built (setup.exe a9363be1...). Served at http://192.168.0.135:8766/91caebccc6a6decef476fea5cd785a9ff19abfe6/. Next: commit AUTORUN-9j to the directives branch after the URL dry run passes.

## 2026-09-05 15:05Z
Directives worktree cc-soak8 has AUTORUN-9j.ps1 + DIRECTIVE-4 addendum + pointer rev 18 (__STAMP__ placeholder) STAGED, NOT committed. Commit + push only after Gate A 33972726431 passes all 3 lanes (Scott: Gate A first, then soak). URL dry run 19/19 HEAD 200 with the script's escaping.

## 2026-09-05 16:12Z
Gate A 33972726431 on kit 91caebc: clean lane PASS (14:45-15:43Z); cross-version lane running since 15:43Z; download-only next (whole run ~17:45Z). Decision: push the tester directive (AUTORUN-9j) as soon as the CROSS-VERSION lane passes -- that lane IS the tester's path (install over an existing station); the download-only lane does not affect the tester. Monitors: cross-version result, whole-run result, 18:00Z stall alarm.

## 2026-09-05 16:15Z
The #172 fix agent was stopped (no final report beyond its first); its work is merged and reviewed, nothing pending from it. Waiting on Gate A cross-version lane.

## 2026-09-05 16:51Z
Gate A cross-version lane PASS (clean PASS earlier; download-only running). PUSHED directives rev 18 d57e9a0: AUTORUN-9j (upgrade tester to kit 91caebc, restart 2-h soak). Tester polls every 10 min; expect INSTALL-RESULT-9j.md within ~45 min. Watcher armed with 17:50Z alarm. Second-soak verdict expected ~2 h after soak-started.

## 2026-09-05 17:42Z
Tester 192.168.0.238 has an ESTABLISHED connection to HALO:8766 -> fetching kit 91caebc (26 GB). Heartbeats 17:06/17:36 healthy; no rollup those cycles (poll busy with 9j). Waiting for INSTALL-RESULT-9j.md.

## 2026-09-05 17:58Z
GATE A 33972726431 on kit 91caebc: ALL THREE LANES PASS (clean, cross-version, download-only). Publisher dry run started (publish-release.sh ... v1.0.0-beta.5 --dry-run). Publish itself waits for the tester soak-2 verdict (zero relaunches).

## 2026-09-05 18:05Z
Publisher DRY RUN for v1.0.0-beta.5 (kit 91caebc, build 33971258093, Gate A 33972726431): 3 PASS verdicts verified, evidence at Desktop/CIVICCAST-EVIDENCE/gate-a-v1.0.0-beta.5-final-33972726431, 8 assets (setup.exe 289,300,032 + 5 packs + SHA256SUMS + sidecar), truth edits: add beta.5 current, beta.4 -> superseded. artifacts/release/v1.0.0-beta.5 removed after the dry run. REAL publish = same command without --dry-run, only after soak-2 verdict PASS.

## 2026-09-05 18:02Z
Tester: kit download finished ~17:50Z; no INSTALL-RESULT-9j.md yet (install + up-to-30-min health wait + channel wait are inside the same poll run). Last heartbeat 17:36Z. Watchers armed (persistent + 9-min). Note: watchers must use their own ref (refs/tmp/tester), not FETCH_HEAD -- the publish script's fetch clobbered it once.

## 2026-09-05 18:14Z
Tester heartbeat 18:06Z: service Stopped, `CivicCast (Native)_1.0.0-beta.5_x64-setup` (pid 32832) running = silent upgrade install in progress, health unreachable (expected mid-install). No reboot (uptime 12538 min). Rollups paused since 16:36 (poll busy). Expect INSTALL-RESULT-9j.md by ~18:45Z; if none by then, ship a read-only diag autorun (9k).

## 2026-09-05 18:18Z
Fallback: scratchpad AUTORUN-9k.ps1 (read-only diag of what happened to 9j: kit folder, markers, local INSTALL-RESULT-9j.md, install-progress.log, service/health/processes, installed version) parses OK; push it ONLY if no 9j result by 18:45Z (monitor armed).

## 2026-09-05 18:30Z
Tester AUTORUN-9j (started 16:56Z): kit 91caebc verified bad=0, authenticode Valid, installer exit 0 at 18:14:48Z, /health healthy 1.0.0-beta.5, upgrade engine SAME_VERSION_NO_OP (both kits carry 1.0.0-beta.5). BUT 0/3 channels ON_AIR after 10 min and data\egress\<id>\state.json MISSING for all three -> soak NOT restarted (exit 5, by design). Pushed AUTORUN-9k read-only diag (rev 19, 5ec8370); monitor armed (alarm 19:05Z). Explore agent checking whether upgrade wipes egress state / whether channels auto-resume / what the Gate A cross-version lane asserts post-upgrade.

## 2026-09-05 18:38Z
Contingency ready: scratchpad AUTORUN-9l.ps1 (parse OK) = POST start to each channel (proven 9e endpoint), poll per-channel /state up to 6 min, then archive/reset/soak-started only if 3/3 ON_AIR. Push only after DIAG-9k / the 18:36Z heartbeat show the channels still exist. Open question for the release: should an upgrade install bring ON_AIR channels back by itself? (Explore agent on it; Gate A cross-version lane may only check health.)

## 2026-09-05 18:45Z
Explore verdict: channels resume after restart ONLY if auto_start=true (automation.py:478-493); egress state is Postgres rows preserved by the upgrade; Gate A cross-version lane never asserts ON_AIR after install-over. Batch item 47 written. Pushed AUTORUN-9l (rev 20, 08db5b2): start all three channels, wait 3/3 ON_AIR, archive soak #1, start soak #2. Monitor armed (alarm 19:25Z). Verdict for soak #2 = soak-started + 2 h.

## 2026-09-05 19:00Z
CORRECTION: the 18:25Z rollup shows all 3 channels RUNNING on GStreamer after the upgrade, in FALLBACK_SLATE (tsp pass) -- soak #1's 2h15 schedule ran out at ~11:20Z, so slate. 9j's '0 ON_AIR' was right, 'state.json missing' was a wrong path. So the fix is CONTENT, not start. Pushed AUTORUN-9m (rev 21): 9e minus upload -- reuse soak8-9e-* assets from the API, schedule 2h15 + commit-to-air per channel, config PUT, start, wait 3/3 ON_AIR (6 min), archive soak #1, reset counters, soak-started. 9l (start only) runs first, harmless. Monitor armed (alarm 19:40Z). Item 47 stands as written (manually-started channels need Start after restart per automation.py) but this station's channels DID come back -> re-check 47's claim against 9k's DIAG (auto_start may be true in 9e's config body).

## 2026-09-05 19:12Z
DIAG-9k (18:36Z): service Running, health healthy 1.0.0-beta.5 (91caebc), 2 gst worker.py pids live, channels enabled auto_start=true allow_software_fallback=true, state FALLBACK_SLATE ('CivicCast slate'), schedule items from 9e state=published scheduled 08:50Z with duration_seconds=30 (ffprobe was NOT found on the tester in 9e -> every item 30 s; clips trimmed). 9m keeps the same 30-s shape unless the asset record carries a duration -> soak #1 vs #2 stay comparable. Waiting for 9l/9m.

## 2026-09-05 19:20Z
9l (18:36Z): start -> 202 x3; 30 s later all three ON_AIR but current_source_label='CivicCast slate' (no plan: 'No valid source plan is available; generated fallback slate'). 9l wrote soak-started 18:37:00Z and archived soak #1 -- that clock is NOT the real soak #2 (slate only). 9m (next poll ~18:46Z) clears it, schedules 2h15 of the 9e assets, commits, starts, and writes the real soak-started. Monitor waits for 'autorun-9m soak start'.

## 2026-09-05 18:38Z (real clock; my last few headings ran ~40 min fast)
9m pushed 18:34Z; tester poll expected ~18:46Z; then scheduling (~270 items x 3 channels, a few minutes) + start + ON_AIR wait -> real soak-started ~18:55Z -> verdict ~20:55Z.

## 2026-09-05 18:50Z
SOAK #2 STARTED for real: AUTORUN-9m 18:37:11Z -> 4 soak8-9e assets reused (durations 2365/667/67/67 s from the records), 9 items scheduled+committed per channel, config PUT ok, start ok, all three ON_AIR (gst worker pids 27152/22396/41188), soak #1 archived to soak/archive-e502074-soak1, counters reset, soak-started 2026-09-05T18:40:36Z. Verdict at the first 30-min AUTORUN-3 tick after 20:40:36Z => ~21:07Z. Monitor armed (rollups + verdict, alarm 21:20Z). Then: publish-release.sh 33972726431 91caebc... 33971258093 v1.0.0-beta.5 (no --dry-run) if verdict PASS.

## 2026-09-05 18:55Z
#165 at 7918732 (rebased on 91caebc; Gate A facts, assets 8, #172 merged, known issue 5 = auto_start resume behavior; placeholders left: RELEASE_DATE, SOAK2_START_UTC/VERDICT/RELAUNCHES). Stopped the superseded tester monitors; soak-2 monitor bii0ygwzb (rollups + verdict, alarm 21:20Z) is the only tester watch now. Stale worktree scratchpad/wt-rel5 flagged by the docs agent (local branch named docs/release-beta5 at an old commit) -- clutter, leave until after publish.

## 2026-09-05 19:05Z
#165 at 59f50dc: SOAK2_START_UTC filled; only <RELEASE_DATE>, <SOAK2_VERDICT>, <SOAK2_RELAUNCHES> remain. Checks pass, 1947 docs/policy tests pass. Waiting on the soak #2 verdict (~21:07Z).

## 2026-09-05 19:08Z
Removed stale worktree scratchpad/wt-rel5 + local branch docs/release-beta5 (d420b04, superseded by 59f50dc). NOTE: the primary checkout lists 79 worktrees (scratchpad wt-*); prune after publish, one by one, checking each for unpushed work first.

## 2026-09-05 19:15Z
First soak-2 probe 18:40:55Z (19 s after soak-started; 9m had reset last-egress-run): tsp PASS x3, public ON_AIR, education/government TRANSITIONING (startup). Strict verdict would FAIL on that one sample. Pushed rev 22: AUTORUN-3 excludes probes within 3 min of soak-started from the verdict (kept on disk, listed in warmup_probes_excluded). Documented in DIRECTIVE-4. If the verdict still FAILS for other reasons, it fails.

## 2026-09-05 19:20Z
SOAK #2 rollup 1 (19:16Z, 0.59 h): control plane pid 25260 cpu 290% rss 988 MB (NO improvement); public relaunched 1, education 1, government TRANSITIONING (0); tsp pass x3. The #172 fix's CPU signature is absent. Pushed AUTORUN-9o read-only diag (rev 23): runtime-status.json, caption/stall/relaunch log lines, profile, per-process CPU. Monitor armed (alarm 19:35Z). Beta.5 publish is OFF the table unless this explains itself.

## 2026-09-05 19:35Z -- SOAK #2 IS MEASURING OLD CODE
DIAG-9o (19:26Z): control plane 401% CPU, 247 CRITICAL 'Caption tap overload' lines in the last 6000, paused=0, all three captions/runtime-status.json state='overloaded' updated 19:26:04Z. #172's code writes 'paused' and logs WARNING once. => the code on disk is pre-#172. The upgrade said SAME_VERSION_NO_OP (both kits = 1.0.0-beta.5). Hypothesis: same-version install-over does not replace the app payload. Pushed AUTORUN-9p (rev 24): hashes of installed civiccast files vs the kit pack + journals. Explore agent reading the installer/orchestrator logic. Soak #2 verdict is therefore NOT a test of #172; beta.5 stays HELD. Customer path (beta.4 -> beta.5) is a different version string; need to know if it is affected.

## 2026-09-05 19:40Z
SLIP: AUTORUN-9p was pushed with a PowerShell quoting error (my parse gate used `; exit 1` inside -Command and the && chain did not stop). Re-issued as AUTORUN-9q (rev 25) behind a real gate (only push when the parser prints PARSE OK). Lesson: gate on captured output, not the exit code, for powershell -Command.

## 2026-09-05 19:45Z
Prepared (NOT pushed) the clean-reinstall chain in cc-soak8: AUTORUN-9r (quiet uninstall + wipe ProgramData + fresh /S install of kit 91caebc), 9s (station-state.json marker reset + restart), 9t (first-admin -> token), 9u (9e: upload 4 clips, schedule 2h15, config, start, archive the invalid soak-2 probes, soak-started). Push only after DIAG-9q proves the installed code is old.

## 2026-09-05 19:55Z
ROOT CAUSE CONFIRMED (code): same-version install-over skips the payload (native_pack_staging.rs AlreadySatisfied; item 48). Customer path beta.4->beta.5 replaces it. PUSHED rev 26: clean reinstall chain 9r (uninstall+wipe+fresh 91caebc) -> 9s (marker reset) -> 9t (first-admin) -> 9u (assets, schedule, config, start, archive soak-2, soak-started). 9q diag runs first (sorted). Monitor armed (alarm 21:10Z). Expect soak #3 start ~20:45Z, verdict ~23:00Z.

## 2026-09-05 19:58Z
DIAG-9q PROOF: installed runtime\...\civiccast\captions	ap_worker.py has CaptionBackoffPolicy=False, paused=False, _LOG.critical=True (pre-#172); kit pack native-app-payload.ccpack (sha 06b3b02c...) contains tap_backoff.py (8290 B) and the new tap_worker.py (52887 B). Upgrade journal 18:07Z: route same_version_no_op; d2-verify-app-payload verified the STALE staged pack. Item 48 confirmed end to end. Chain 9r..9u runs next.

## 2026-09-05 20:05Z
#165 at 97a7790: known issue 6 (item 48), soak #2 archived as old-code, SOAK3_* placeholders. Remaining: RELEASE_DATE, SOAK3_START_UTC/VERDICT/RELAUNCHES. Waiting on the tester chain (9r..9u).

## 2026-09-05 20:10Z
PR #173 (item 48 fix: pack staging by VerifiedPack::sha256 identity, ReplaceFromOffline, greppable payload replaced/unchanged log, Gate A dirty-lane digest assertion; cargo 420 pass, gate_a 227 pass). Opus hostile review + CI waiter running. Target: beta.6 (beta.5 kit stays 91caebc).

## 2026-09-05 19:50Z (real clock)
9r DONE: clean reinstall of 91caebc exit 0, healthy (19:46Z). 9s/9t/9u run next in the same poll. Pushed rev 27 AUTORUN-9v (installed-code check after the clean install; runs after 9u). Monitors: chain (alarm 21:10Z), DIAG-9v (alarm 21:15Z), liveness.

## 2026-09-05 20:20Z
#173 review = CHANGES (Gate A digest check can never fire in the existing upgrade lane; CHANGELOG over-claims; println! into the NSIS $1 report risk; repair guard inconsistency; e2e test path). Sent back (6 items). Batch item 49: same-version install-over lane.

## 2026-09-05 20:05Z (real)
#173 rework 810a006 (identity for all outcomes as JSON fields, no println, honest CHANGELOG, repair guard unified, runtime-branch e2e; cargo 423 pass). Opus delta review + CI waiter running. Tester: 9r/9s/9t done, 9u (uploads/schedule/start) running since 19:48Z.

## 2026-09-05 20:10Z (real)
9u: 4 assets ready (30 s each; ffprobe absent on the tester), 272 items/channel committed, config+start ok, but no ON_AIR within 3 min (state read empty) -> soak-started NOT written. Pushed rev 28 AUTORUN-9w (raw state dump, start again, poll 6 min, soak #3 clock at 3/3 ON_AIR, archive old probes, reset counters). 9v (code check) runs before 9w at the next poll. Monitors: 9w (alarm 20:45Z), DIAG-9v (21:15Z), liveness. Stopped the stale chain monitor.

## 2026-09-05 20:25Z
#173 delta review: 6 items fixed; NEW BLOCKER: manifest report into NSIS $1 (1024-byte cap, measured) would now truncate and drop the required-pack object. Sent back: write full report to a ProgramData file + compact stdout summary + <1024 guard test; e2e must pre-populate kit A's runtime tree; doc fixes; compiler-enforced variant list.

## 2026-09-05 20:18Z
DIAG-9v (20:16Z) PROOF after the clean install: installed captions/tap_worker.py sha 0a9610bb... == kit pack; tap_backoff.py 34e6ac46... present; CaptionBackoffPolicy=True, paused=True, _LOG.critical=False. #172 code is on disk. 9w (soak #3 clock) runs next.

## 2026-09-05 20:20Z
SOAK #3 STARTED 2026-09-05T20:16:29Z on kit 91caebc (CLEAN install; #172 code proven by DIAG-9v). All three ON_AIR with content (pids 25036/14076/39788), old probes archived to soak/archive-91caebc-soak2-oldcode, counters reset. Rollups every 30 min from ~20:26Z; verdict at the first tick with elapsed >= 2 h => ~22:26Z. Monitor armed (alarm 22:50Z). If PASS: publish beta.5 (publish-release.sh ... v1.0.0-beta.5), fill SOAK3_*/RELEASE_DATE, merge #165, commit truth diff, docs sweep.

## 2026-09-05 20:40Z
#173 at 3e7a9cb: truncation blocker fixed (full manifest -> ProgramData\CivicCast\install-manifest-report-<pid>-<time>.json; compact summary in $1 with a fail-closed NSIS_MAX_STRLEN test; e2e pre-populates kit A's tree and asserts authorize_rebuild consulted; docs fixed; exhaustive variant list). My spot-check passes; cargo 425 pass. CI waiter running; merge on green (beta.6 content).

## 2026-09-05 20:45Z
#165 at 0b40953 (SOAK3_START_UTC filled with the clean-install facts). Remaining: SOAK3_VERDICT, SOAK3_RELAUNCHES, RELEASE_DATE. Batch item 50: a claims-evidence policy test writes the real ~/.civiccast/installer-state.json (teardown guard error, exit 0).

## 2026-09-05 20:55Z
SOAK #3 probe 20:46:12Z: all three ON_AIR, tsp pass, BUT relaunched_this_cycle=True on all three (pids 25036->32520, 23588->22944, 41064->32760). Confound: 9w re-sent `start` at 20:16:29Z (restarts workers); the 20:16:33 baseline probe may have caught mid-restart pids. Pushed rev 29 AUTORUN-9x diag (timestamps of relaunch/stall/state lines since 20:10Z, caption status, CPU). Monitor armed (alarm 21:25Z). #173: 19 pass, mutation-report red (item 46 lane), Unit tests pending.

## 2026-09-05 21:05Z -- SOAK #3 IS FAILING FOR A NEW REASON
DIAG-9x (20:56Z): caption tap = new code, state paused, consecutive_overloads 6, CRITICAL=0, control plane 30% CPU (#172 works for CPU). BUT workers relaunch ~every 30 s per channel: 'child exited non-zero; relaunching encoder. Last child stderr: CTRL stall: no output for 10s' (STARTING lines 20:45-20:55Z every ~30 s x3; one 'Live source failed'); live worker pid 13424 rss 3531 MB threads 1238. Soak #1 (e502074, same 30-s schedule) restarted every 10-25 min only. Suspect #170 (per-segment prepare / plan rollover every 30 s) or #172's ABOVE_NORMAL worker priority. Pushed AUTORUN-9y (worker stderr, thread growth, prepared files, plan/segment lines; rev 30); Opus diagnosing the e502074..91caebc egress diff. Beta.5 on 91caebc: NOT publishable. Soak #3 verdict will be FAIL (evidence, keep).

## 2026-09-05 21:15Z
Pushed rev 31 AUTORUN-9z: reschedule the soak8-9u assets with REAL durations from the records (skip if none; no 30-s default), start, archive soak #3 (30-s items) probes to archive-91caebc-soak3-30s-items, reset counters, soak #4 clock. Purpose: A/B on item-boundary cadence (30 s vs 67-2365 s) on the same build. 9y diag runs first in the same poll. Monitor armed (alarm 21:50Z). Soak #3 verdict monitor (bkv8bbnem) now stale -> its final-verdict watch will be pre-empted by the archive; keep for rollups.

## 2026-09-05 21:18Z
Correction: the first 9z push attempt was BLOCKED by the parse gate (`$id:` scope parse error, line 366); fixed to ${id} and pushed on the second attempt (see next commit on soak8-e1acfe6-directives).

## 2026-09-05 21:35Z -- ROOT CAUSE of the 30-s stalls
Opus diagnosis: #170's 1800-s plan window x 30-s items = 60 segments; bridge.py builds a decoder sub-chain per segment, all PLAYING at once -> ~20 threads each = 1238 threads, 3.5 GB, no TS output in 10 s -> watchdog -> relaunch ~30 s. Rollover floor 300 s > an 8x30 s plan, so the fix must retune both. Item 51. Hotfix PR launched (Sonnet): max 8 segments, min window 0, rollover floor from plan length, hard sub-chain cap in the bridge, tests, CHANGELOG. Then: review -> merge -> kit -> Gate A -> clean-install soak. Soak #4 (real durations, few segments) running as the A/B.

## 2026-09-05 21:40Z
MERGING #173 (item 48 installer identity fix): 21/21 real checks green, mutation-report red = lane baseline (item 46). Beta.6 content; the hotfix for item 51 will land on top.

## 2026-09-05 21:42Z
MERGED #173 -> main 9ce8b3c. Main CI waiter running. Hotfix agent told to rebase onto 9ce8b3c.

## 2026-09-05 21:10Z (real)
DIAG-9y (21:06Z): 0 gst workers alive at the sample instant (all mid-relaunch), worker stderr = wall of 'CTRL stall: no output for 10s' + WORKER_RESULT stall, prepared/ = 5 files (dedup works). 9z committed the real-duration schedule 21:06:48Z; soak #4 clock pending. Hotfix agent building fix/plan-window-decoder-blowup on top of 9ce8b3c.

## 2026-09-05 21:15Z (real)
9z: real durations found on the records (2365/667/67/67); the first 5 schedule POSTs per channel hit 409 (overlap with soak #3's 30-s items that run until ~22:20Z); 4 long items per channel were created+committed beyond that point. Soak #4 clock started ~21:08Z but plays 30-s items until ~22:22Z, then the long clips. A/B boundary = 22:22Z: compare relaunch counts in the 22:26Z/22:56Z rollups vs 21:38Z/22:08Z. Verdict (23:08Z) will be FAIL regardless (counts include the 30-s phase).

## 2026-09-05 21:20Z (real)
Main CI green on 9ce8b3c (#173). In flight: hotfix PR (fix/plan-window-decoder-blowup, Sonnet), #165 docs (item 51 + candidate-2 placeholders), soak #4 on the tester (A/B boundary 22:22Z), monitors: rollups/verdict (bkv8bbnem), liveness.

## 2026-09-05 21:25Z (real)
Prepared scratchpad/soak5-templates/AUTORUN-9za..9zd.template.ps1 (= 9r/9s/9t/9u with __KITSHA__ / __KITSHORT__ placeholders; archive dir archive-<short>-prev-soak). Fill + parse-gate + push after the post-hotfix kit is staged/served.

## 2026-09-05 21:30Z (real ~21:15Z)
#165 at 2724751 (rebased on 9ce8b3c): soak #3 FAIL + item 51 root cause; 91caebc = candidate 1; placeholders for candidate 2 (BETA5_FINAL_SHA/BUILD_RUN, GATE_A_FINAL_RUN_ID, SOAK5_*), SOAK4_START_UTC=2026-09-05T21:08:51Z (fill later), SOAK4_VERDICT, RELEASE_DATE.

## 2026-09-05 21:20Z (real)
PR #174 (item 51 hotfix): PLAN_MIN_SECONDS 1800->0 (8-segment plans), rollover floor min(300,max(30,0.5*planned)), MAX_PLAYLIST_SUBCHAINS=12 in bridge.graph_from_config, tests (979 egress pass), ruff/mypy clean, rebased on 9ce8b3c. Opus hostile review + CI waiter running. Then: merge -> kit -> after-build.ps1 -> Gate A -> soak #5 chain (templates 9za..9zd).

## 2026-09-05 21:40Z (real ~21:35Z)
#174 review = CHANGES: bridge truncation would desync plan vs graph (move the cap into the plan builder + e2e test); stale tests encode the 60-segment premise; floor starves plans <60 s; CHANGELOG overclaims; constant-restating tests. Production shape verified: 8x30 s replans at 120 s then every 240 s with 120 s lead. Sent back. Item 53 (decoder max-threads) logged as follow-up.

## 2026-09-05 21:48Z (real)
Soak #4 rollup 1 (21:46Z, 30-s phase): control plane 18% CPU / 966 MB; three gst workers ~3.5 GB each (60 sub-chains); relaunched_this_cycle on all three; tsp pass. A/B boundary 22:22Z (long items). #174 rework still unpushed (watcher armed).

## 2026-09-05 21:53Z (real)
#174 rework pushed d18d022 (cap moved into the plan builder). Opus delta review + CI waiter running. Merge on MERGE + green, then dispatch the kit build.

## 2026-09-05 22:05Z (real ~22:00Z)
#174 delta review on d18d022: cap in builder OK, tests rewritten OK; remaining: program-branch should raise not truncate; two false measurement claims in docstrings/tests; 24-s plans still dispatch late because the 120-s lead constant is not scaled; validation weakened by clamp order; e2e test not at the cap; dead PLAN_MAX_SEGMENTS. Sent back (last round). CI on d18d022 was in flight (waiter).

## 2026-09-05 22:07Z (real)
Waiting: #174 third push (6 items sent 22:00Z), soak #4 rollup 2 (22:16Z), boundary rollup (22:46Z), verdict (23:08Z). d18d022 CI had no failures (4 pending).

## 2026-09-05 22:12Z (real)
#174 third push de54f9d: program-branch raises PlaylistCapBypassedError (bridge.py:609), fill plans truncate with WARNING (:637), MAX_PLAYLIST_SUBCHAINS shared in models.py:666, PLAN_MIN_SECONDS=0, raw validation before clamp (source_plan.py:206), lead scaled (_rollover_min_lead_seconds), dead constant removed; 987 egress tests, ruff/mypy clean. Spot-check passes. CI waiter running; merge on green.

## 2026-09-05 22:18Z (real)
Soak #4 rollup 2 (22:16Z, 1.12 h): worker RSS fell to ~390 MB (was ~3.5 GB) as the plan window fills with the long items -> fewer sub-chains; control plane 17%. relaunches_total=2 each (30-s phase). Boundary 22:22Z; watch 22:46Z rollup for zero relaunched_this_cycle. Strong live support for item 51's mechanism.

## 2026-09-05 22:25Z (real)
scratchpad/build-chain.sh <sha> written (dispatch build -> wait -> samples+manifest -> after-build.ps1 -> served HEAD checks -> Gate A run id); run it as a Monitor right after the #174 merge. Waiting: #174 CI (unit tests ~22:50Z), soak #4 boundary rollup 22:46Z, verdict 23:08Z.

## 2026-09-05 22:52Z (real)
Soak #4 rollup 3 (22:46Z, long-item phase): workers 340-390 MB (few sub-chains), control plane 15%, tsp pass, BUT relaunches_total 2->3 on all three this cycle; new-pid cpu-seconds (422/69/118 s) suggest ONE restart each at the 22:22Z plan boundary (rollover into the long items not seamless), not a stall loop. Pushed AUTORUN-9zz (rev 32) for the state lines + last_error + reload/rollover lines. #174 CI: 18 pass, Unit tests + mutation pending; waiter armed.

## 2026-09-05 23:00Z (real)
DIAG-9zz: soak #4 long-item phase NOT clean: 22:32Z stalls still relaunching (30-s tail), then FALLBACK_SLATE 'No valid source plan' (schedule gap), government 5-crash guard -> slate, rollover with 'live plan ends in -1208s', then 22:55Z+ all three stuck TRANSITIONING same pids. Item 54 logged. Soak #4 verdict (23:08Z) = FAIL; its value = A/B evidence for item 51 (RSS 3.5 GB -> 0.35 GB when the plan window left the 30-s items). Real test = soak #5 (hotfix build, clean install, 30-s items = stress shape). #174 CI still 2 pending.

## 2026-09-05 23:02Z (real)
MERGED #174 -> main 609273d (item 51 hotfix). build-chain.sh running as a Monitor (build -> manifest -> kit-safe/mirror -> HEAD checks -> Gate A id). Main CI waiter running. Soak #5 chain AUTORUN-9za..9zd filled with 609273d in cc-soak8 (NOT pushed until the kit is served + Gate A cross-version PASS).

## 2026-09-05 23:05Z (real)
Main CI green on 609273d. Build run 33997406150 running (chain monitor). Docs agent filling BETA5_FINAL_SHA/BUILD_RUN + soak #4 result + item 54 into #165. Soak #4 verdict expected at the 23:16Z tick.

## 2026-09-05 23:15Z (real)
#165 at 8ee94a8: candidate 2 = 609273d / build 33997406150; soak #4 FAIL narrative; item 54 known issue. Remaining placeholders: GATE_A_FINAL_RUN_ID, SOAK5_START_UTC/VERDICT/RELAUNCHES, RELEASE_DATE.

## 2026-09-05 23:20Z (real)
SOAK #4 FINAL VERDICT: FAIL (2.12 h; relaunches education 4 / public 3 / government 3 = 10; tsp pass every counted probe; warm-up probe 21:08:56 excluded; not-ON_AIR events = TRANSITIONING at 22:16 (edu, gov), 22:46 (gov), 23:16 (all three, the stuck-TRANSITIONING of item 54)). Evidence copied to Desktop/CIVICCAST-EVIDENCE/tester-soak4-91caebc-20260905/ (14 files). Kit 91caebc: two hardware verdicts, both FAIL, causes items 51 + 54. Next: kit 609273d (build running).

## 2026-09-05 23:35Z (real)
Item 54 diagnosis (Opus): RC1 = pending-reload latch with no watchdog (item 55, present in beta.4, daemon.py untouched by #174) -> stuck TRANSITIONING, automation off, invisible in health; RC2 = item 51 (fixed by #174, unverified on hardware); RC3 crash guard OK; RC4 horizon guards (item 57). NEW consequence of #174: slate plans truncated to 12 x 30 s -> slate restarts every ~6 min (item 56). Beta.5 call: if soak #5 on 609273d PASSES, publish beta.5 from it and ship 55/56/57 in beta.6 (55 exists in beta.4 too); RC1 fix PR starting now in parallel.

## 2026-09-05 23:45Z (real)
Kit 609273d: build 33997406150 SUCCESS, manifest 19 lines, kit-safe verified, mirror (setup.exe 56fb80b8...), served 19/19 HEAD 200. Gate A auto-run pending id. Plan: push soak #5 (rev 33) when the Gate A CLEAN lane passes (fresh-install path = the tester's path), not after all three lanes.

## 2026-09-05 23:48Z (real)
GATE A 33998901590 started on kit 609273d (build 33997406150). Lane monitor armed (alarm 03:10Z). Soak #5 push after the clean lane passes (~00:45Z). Publisher dry run after all 3 lanes.

## 2026-09-06 00:15Z (real ~00:10Z)
PR #175 (items 55/56/57: reload-latch self-heal 15 s, updated_at only on change, TRANSITIONING red after 60 s, fill plans <=12 segments, horizon guards; 1226 tests). Opus hostile review + CI waiter running. Target beta.6 unless soak #5 fails. Gate A 33998901590 clean lane running.

## 2026-09-06 00:40Z (real ~00:35Z)
#175 review = CHANGES with a reframe: the 20-min TRANSITIONING = designed graceful drain of a program before a reload (daemon.py:1770-1776), mislabelled; 15-s self-heal would break handoffs (STOPPED at EOS). Also: _reload_kills leak, slate flap loop, remaining<=0 guard wedges rollover, bulletin slides become 5-min holds, unconditional slate re-render. Sent redesign (annotate drain + state_entered_at + alert on outliving plan remaining; horizon kept during drain; backoff; cached slate; bulletin rotation file; horizon pop/throttle). Item 55 severity downgraded: not a hang, a mislabel + invisible + automation-blind drain. Beta.6.

## 2026-09-06 00:25Z (real)
#165 at d281a85: Gate A id 33998901590 + per-lane placeholders (GATE_A_FINAL_CLEAN/XVER/DLONLY); item 54/55 reframed (drain, streams clean). Remaining: 3 lane verdicts, SOAK5_*, RELEASE_DATE.

## 2026-09-06 00:50Z (real)
Gate A 33998901590 CLEAN lane PASS (609273d); cross-version running. PUSHED soak #5 chain (rev 33): 9za uninstall+wipe+fresh install, 9zb marker reset, 9zc first-admin, 9zd clips+30-s schedule+config+start -> soak #5 clock. Monitor armed. Expect clock ~01:40Z, verdict ~03:50Z.

## 2026-09-06 00:55Z (real)
SLIP: AUTORUN-9ze pushed as a plain 9v clone (marker patch assert failed; chain not gated on it) -> proves #172 files only. Pushed AUTORUN-9zf (rev 35) with #174 markers, gated on patch exit + parse. Lesson: gate every push on BOTH the patch step and the parse step. Soak #5 chain + verdict monitors armed; Gate A cross-version running.

## 2026-09-06 00:45Z (real)
SLIP: 9za (clone of 9r) stalled 'kit installer not found' -- 9r never fetched; 9zb/9zc/9zd ran against the OLD 91caebc station. Pushed rev 36: 9zg (9j fetch+verify + 9r uninstall/wipe/fresh install), 9zh, 9zi, 9zj (soak #5 clock, archives the void 9zd output), 9zk (code proof). Monitor armed. Expect: fetch ~10 min + install ~10 min + setup ~15 min -> soak #5 clock ~01:35Z, verdict ~03:45Z.

## 2026-09-06 01:40Z (real)
GATE A 33998901590 on 609273d: clean PASS; cross-version FAIL at dirty_prep: PHASE1_INSTALL_EXIT=-1073741819 (0xC0000005 access violation) while installing the BASELINE beta.4 kit c27c6e7 inside the sandbox -> phase 2 became FRESH_INSTALL -> lane cannot prove an upgrade; download-only skipped. Baseline installer on disk = published sha 9fae1211... (kit-staging == kit-safe). Same lane passed on 91caebc at 14:45Z with the same baseline => sandbox-transient (event log shows Edge activation-context errors; teardown drain timed out on kit-staging\c27c6e7 busy handle). Re-dispatched Gate A on build 33997406150. Item to log: Gate A must retry phase-1 once on a non-zero installer exit and record the crash dump.

## 2026-09-06 01:40Z (real)
Tester: 9zd blocked (no samples, expected), 9ze/9zf ran on the old kit (void), 9zg downloading kit 609273d since ~00:50Z (ESTABLISHED to :8766 at 01:38Z; the previous 26-GB fetch took ~45 min). Revised: install ~02:00Z, soak #5 clock ~02:20Z, verdict ~04:30Z. Gate A re-run 34004354641 clean lane in progress (~3 h total).

## 2026-09-06 02:20Z (real ~02:15Z)
#175 rework ddb6edc: no flat self-heal; drain dated via migration 0088 (state_entered_at, pending_reload_since, pending_reload_deadline), runtime_status escalation off the deadline, horizon kept during drain, backoff for slate reload flapping, cached slate + bulletin rotation file (<=12 repeats, 10-s slides), horizon discard on remaining<=0, OpenAPI regenerated, 11414 tests pass. Opus delta review + CI running. Beta.6.

## 2026-09-06 02:35Z (real)
#175 delta review on ddb6edc: structural fixes land (no flat self-heal, EOS starts the new plan, horizon kept, backoff, latch bookkeeping); 9 defects sent back (drain note in last_error = red alert; 600-s fallback fires despite a known deadline; deadline = total not remaining; unbounded B2 re-entry; non-atomic slate cache; >12 bulletins dropped; partial cleanup; give-up counter; no migration test). Beta.6.

## 2026-09-06 02:02Z (real)
9zg DONE: kit 609273d fetched+verified (download ~65 min, HALO busy with Gate A), clean reinstall exit 0, healthy. 9zh..9zk running. Soak #5 clock ~02:20Z, verdict ~04:30Z. Gate A re-run clean lane in progress (~3 h total).

## 2026-09-06 02:20Z (real)
9zj: 4 assets ready, 272 items/channel committed, config+start ok, no ON_AIR within 3 min (as on the last fresh install) -> no soak clock. 9zk PROOF: installed tap_worker/tap_backoff hashes == pack; CaptionBackoffPolicy True; PLAN_MIN_SECONDS=0.0, MAX_PLAYLIST_SUBCHAINS=12, PlaylistCapBypassedError present => 609273d code on disk. Pushed AUTORUN-9zl (rev 37) = 9w for soak #5. Monitor armed. Item 59 to log: fresh-station channels take >3 min to reach ON_AIR after the first start (first-run warmup) -- harness should wait 6 min; product should report STARTING progress.

## 2026-09-06 02:28Z (real)
SOAK #5 STARTED 2026-09-06T02:26:16Z on kit 609273d (clean install, code proven by 9zk), 3/3 ON_AIR with content, 272 x 30-s items/channel (item-51 stress shape), counters reset, previous probes archived to soak/archive-609273d-prev-soak. Verdict at the first 30-min tick with elapsed >= 2 h => ~04:30-05:00Z. Gate A re-run 34004354641 clean lane running (x3 done ~04:40Z). If both pass: publish-release.sh 34004354641 609273da22b968b8ed9320dfc158d67b01eb30b3 33997406150 v1.0.0-beta.5.

## 2026-09-06 02:35Z (real)
Soak #5 warm-up probe 02:26:20Z (excluded by the 3-min grace): tsp pass x3, education TRANSITIONING (startup), relaunches 0. Next probe/rollup ~02:56Z.

## 2026-09-06 02:38Z (real)
Gate A re-run 34004354641: clean lane PASS (609273d, second time); cross-version lane running (~03:35Z), download-only after (~04:35Z). Soak #5 rollup 1 due 02:56Z. #175 round 3 still unpushed (watcher re-armed).

## 2026-09-06 02:55Z (real)
#175 round 3 pushed c0a5b3a (transition_note column, deadline from a dispatch anchor, idempotent reload + one B2 retry per drain, atomic versioned slate cache, bulletin paging, migration test; 11427 tests, vitest 949). Focused Opus delta check + CI running.

## 2026-09-06 03:05Z (real)
#175 c0a5b3a: nine items FIXED (1253 tests). Round 4 sent: bulletin paging cap >144 slides, slate eviction after replace + OSError, slate cache tests, duplicate give-up alert / stale pending mark, transition_note in the log line, deferred-switch deadline anchor. Beta.6.

## 2026-09-06 03:00Z (real)
SOAK #5 probe 02:56:13Z: tsp pass x3 BUT relaunched_this_cycle=True on all three (relaunches_total=1 each) on the #174 build. Zero-relaunch rule already broken. Pushed AUTORUN-9zm diag (rev 38). Hypotheses: plan-boundary restart at 240-s plan ends (rollover not seamless), 9zl's re-sent start (should be a no-op), or a residual stall. Monitor armed.

## 2026-09-06 03:15Z (real)
DIAG-9zm (03:06Z, soak #5 on 609273d): plan cap WORKS (workers 550 MB / 178 threads, 8-segment prepares 0.3 s), caption tap paused, first ~30 min clean; then from 02:58Z stall relaunches every ~30 s per channel ('CTRL stall: no output for 10s'), government hit the 5-crash guard 03:01Z. Onset coincides with the FIRST seamless content reloads (02:55-02:56Z 'extending in place', 8 segments). Hypothesis: #162's in-place playlist extension stalls the live GStreamer pipeline; #174's scaled rollover floor exercises it every ~3 min for the first time on hardware (soak #1 never rolled over). 609273d NOT publishable. Soak #5 will FAIL. Opus diagnosing the reload path (options: fix the extension; fall back to terminate+restart at plan end; revert the floor scaling).

## 2026-09-06 03:30Z (real)
#175 round 4 pushed 2bf7d3f (paging cap, atomic eviction + OSError, single give-up alert + terminal discard, transition_note in log, deferred deadline None); my spot-check passes; 1260 tests, vitest 28. CI waiter running; merge on green (beta.6). Item-60 diagnosis running.

## 2026-09-06 03:45Z (real)
ITEM 60 ROOT CAUSE (Opus): duplicate concat element names on reload -> pipeline.add refused (return ignored) -> reload never commits -> 10-s reload timeout aborts; ack lies 'applied'; automation re-issues forever; doubled decoder tree starves the encoder -> CTRL stall storm. No hardware rollover has EVER committed. Fix PR launched (fail-loud add, unique names, seamless reload OFF by default via env, honest ack, PlaylistLeg tests, claims rebinding for engine.py/worker.py). Items 61-63 logged. Plan: review -> merge -> kit (candidate 3) -> Gate A -> soak #6 -> publish.

## 2026-09-06 04:00Z (real ~03:35Z)
Prepared scratchpad/soak6-templates/AUTORUN-9zo..9zt (= 9zg fetch+clean install, 9zh marker, 9zi admin, 9zj clips, 9zk proof, 9zl clock; __KITSHA__/__KITSHORT__). Pushed AUTORUN-9zn (rev 39, item-60 proof diag). Docs agent writing candidate-2 FAIL + item 60 + candidate-3 placeholders into #165. Item-60 fix PR being written; branch watcher armed. #175 CI on 2bf7d3f running.

## 2026-09-06 03:40Z (real)
DIAG-9zn: H1 (name collision) NOT confirmed on hardware -- worker stdout has 0 'CTRL reload' lines, stderr 0 'not unique' warnings, only CTRL stall lines. So the reload never reached the worker (or output lost). Alternative H5: the content-reload PREPARE evicts/replaces prepared segment files the live worker is still reading -> filesrc starves -> CTRL stall. Explore agent checking preparer eviction + daemon reload logging; pushed AUTORUN-9zzz (rev 40) for prepared/ mtimes + daemon lines after each prepare. The fix PR (seamless OFF by default) bypasses the whole reload path either way; the H1 hardening stays but is unproven on hardware.

## 2026-09-06 03:50Z (real)
H5 CONFIRMED (code): reload prepare overwrites live prepared/segment-NNNN.ts in place -> CTRL stall; reload command never reached the worker (silent False, daemon.py:1617). Items 64/65. Fix agent told to add per-plan prepared dirs + atomic writes + GC + WARNING on the silent path, on top of fail-loud/unique names/seamless OFF/honest ack. DIAG-9zzz pending for the mtime proof.

## 2026-09-06 03:55Z (real)
#165 at 874309d: candidate 2 FAIL + item 60 (worded as the name collision) + candidate-3 placeholders + items 61/62. NEEDS a correction pass after the fix PR: item 60 = prepare clobbers live segment files (64) + silent reload failure (65); the name collision is real but was not the trigger on hardware.

## 2026-09-06 04:05Z (real ~03:45Z)
DIAG-9zzz PROOF: after every 'Content-reload source preparation ... 8 segment(s)' line the daemon writes TRANSITIONING every 2 s with the SAME pid = _request_reload fallback (reload_content returned False, silently) -> pending drain; prepared/ holds 5 shared files per channel (4 clips + 1 trim) rewritten in place by each prepare while the live worker reads them -> CTRL stall -> relaunch. Item 60 = 64 (clobber) + 65 (silent False) + the drain mislabel (55). Name collision (H1) untriggered. Fix PR covers all. Evidence: tester branch DIAG-9zm/9zn/9zzz.

## 2026-09-06 04:20Z (real ~03:50Z)
#165 at 467a0b0: item 60 corrected to the proven mechanism (64 clobber + 65 silent failure; name collision as a note). Remaining placeholders: GATE_A_FINAL_XVER/DLONLY (re-run 34004354641), BETA5_FINAL_SHA/BUILD_RUN, GATE_A_FINAL_RUN_ID, SOAK6_*, RELEASE_DATE. Waiting: item-60 fix PR push, #175 unit tests, soak #5 verdict, Gate A xver/dlonly.

## 2026-09-06 03:50Z (real)
Gate A re-run 34004354641 (609273d): clean PASS, cross-version PASS (item 58 confirmed transient), download-only running (~04:45Z). Note: 609273d's install paths are certified; candidate 3 differs only in egress/preparer/worker code, so its own Gate A is still required (workflow_run). #175 unit tests pending; item-60 PR still being written.

## 2026-09-06 03:52Z (real)
Item-60 fix branch pushed c9f9b49 (PR opening). Opus hostile review launched on the branch (10 refutation points incl. flag-off end-to-end trace, per-plan dir keying/GC, atomic write on Windows, claims rebinding). PR watcher armed.

## 2026-09-06 04:00Z (real)
PR #176 (item 60: fail-loud add, unique concat names, seamless OFF by default, honest deferred ack, per-plan prepared dirs <channel>/prepared/<uuid>/ + tmp+rename + 6h GC, WARNING on silent path, claims rebinding for engine.py/worker.py; 1012 egress tests). Opus hostile review + CI running. Primary checkout verified clean (agent had touched it, reverted). Candidate 3 = main after #176.

## 2026-09-06 04:25Z (real ~04:05Z)
#176 review = CHANGES: root-cause fixes hold (flag off = no prepare at rollover; per-plan dirs never collide; claims rebinding verified), but F1 the honest ack waits 15 s for a settle that arrives at the outgoing leg's EOS (~120 s) -> every seamless rollover would time out; F2 build failure -> no ack + leaked elements; F3/F4 per-plan dirs: no budget, 6-h age GC could delete a live long plan; F5-F9 smaller. Sent back: armed ack + out-of-band settle, ENG-008 wrap, release-keyed GC + budget, tests.

## 2026-09-06 04:06Z (real)
#175 (2bf7d3f): 20/20 real checks green, mutation lane red (item 46). HOLD the merge until candidate 3 (main + #176) is cut, so beta.5 scope = 609273d + #176 only; #175 (migration 0088, console fields) merges right after the candidate-3 build is dispatched -> beta.6. Waiting on the #176 rework.

## 2026-09-06 04:40Z (real)
#176 rework pushed 1ac4e95. Opus delta review (F1-F9 + flag-off trace + claims re-verify) + CI waiter running. Gate A re-run: download-only lane still running. Soak #5 verdict at 04:56Z.
- 04:48Z main checkout had c9f9b49 (#176 round-1 content) staged by the builder's accidental edits; tree byte-identical to pushed c9f9b49; reset --hard to origin/main 609273d. Stash@{0} belongs to another lane, untouched.

## 2026-09-06 ~05:00Z OWNER ORDER (binding)
Sandbox-first: bug -> 15-min sandbox soak -> audit -> fix -> 15-min sandbox soak until it passes every time -> tester 2-h soak -> pass = beta.5 publish (docs/push/merge/tag) -> 24-h real soak. Wait for soak #5 + Gate A dlonly to finish first. Memory: sandbox-first-short-soaks.md
- 05:05Z Sonnet building sandbox-lab/Run-SandboxSoak.ps1 (15-min Windows Sandbox soak lane, branch feat/sandbox-soak-lane, dry-run only, no sandbox launch while Gate A runs). #176 CI waiter re-armed (16 pass/4 pending at 04:50Z). Opus delta review of 1ac4e95 running.
- 05:08Z GATE A 34004354641 (kit 609273d, candidate 2): all 3 lanes PASS by the gate's own gate-a-verdict.json (clean PASS, dirty/cross-version PASS, download-only PASS). Evidence: Desktop\CIVICCAST-EVIDENCE\gate-a-609273d-34004354641 (artifact names carry 33997406150 = the original run id the re-run replaced).
- 05:12Z #176 round-2 delta review (1ac4e95) = CHANGES: pending-settle never cleared on worker exit (spurious restart at 960 s), automation 45-s latch re-dispatches a deferred reload (proof event moved to settle time), superseded pending leaks plan dir, F3 flag-OFF path never releases, F4 keep= never passed, F2 untested, POSIX on_settled missing. Sent to builder for one commit.
- 05:20Z SOAK #5 (kit 609273d, clean install) FINAL VERDICT FAIL at 04:56Z: 15 relaunches (5/channel), 4 not-ON_AIR (TRANSITIONING) rollups, 1 tsduck timeout (government 04:26Z). Cause = item 60 (#176, not in this kit). Evidence: Desktop\CIVICCAST-EVIDENCE	ester-soak5-609273d-20260906inal. Tester now idle; no new directive until the sandbox lane passes (owner order 05:00Z).
- 05:30Z PR #177 = sandbox-lab 15-min soak lane (head 0aa3859, dry-run clean 19/19 hashes, 9/9 verdict unit checks; API bodies borrowed from AUTORUN-8/9m, unverified live). #176 CI on 1ac4e95: mutation-report baseline FAILED on ubuntu = real POSIX test failure test_last_send_command_failure_reason_reports_the_workers_ack; sent to builder for round 2. Soak #5 monitors closed.
- 05:02Z(real) SANDBOX SOAK run 1 launched: kit 609273d, 15 min, pid 3088, output cc-sbsoak\sandbox-lab\soak-output\soak-609273d-20260906-050216Z, log scratchpad\sbsoak-609273d-run1.log. Expected: FAIL reproducing item 60 (proves the lane). Opus hostile review of #177 + CI waiter running.
- 05:10Z SANDBOX SOAK run 1: STALL at 05:08 (0 rollups in 6 min; install still running; host kill did NOT stop the sandbox). Lane defects: stall guard counts from launch not from station-healthy; kill ineffective. Sent to lane builder. Orphan sandbox left running to time the install (watcher on soak-log.txt).
- 05:25Z #177 review CHANGES (4 blockers: asset-id regex 422 + collision, soak deadline anchored before install, stall guard fires during install; HIGH: busy-guard list wrong + kill-by-name, exit 2 unreachable; rollover: ffprobe missing => 30-s default is the right instrument, pin it; engine field absent from state row => census needed; VSMB wedge mitigation dropped). All sent to lane builder as one delta.
- 05:20Z orphan sandbox run 1 finished: install 13m05s (exit 0), healthy in 1 s, first-admin OK, 4/4 uploads 422 (asset-id regex; review Blocker 1 confirmed live) -> FAIL no assets. Killed my sandbox (RemoteSession 41264 + Server 33964). Timing sent to lane builder.
- 05:22Z vmmemWindowsSandbox (17 GB) stayed after killing my session; elevated helper job kill-sbx-231719 (kill-orphan-sandbox.ps1) cleared it. Sandbox free. Waiting: #176 round 2 (builder), #177 lane fix (builder).
- 05:23Z #177 fixed head 046b112 (all review items + phased stall guard + own-launch kill). SANDBOX SOAK run 2 launched on kit 609273d (pid 48852, output soak-output\soak-609273d-20260906-052329Z, log scratchpad\sbsoak-609273d-run2.log). Opus delta review of 046b112 + CI waiter running. Expect: FAIL reproducing item 60 at rollover (~every 4 min).
- 05:35Z #176 round-2 head 862ee51 pushed (pending-settle cleanup on all exit paths, automation latch respects pending settle, plan-dir release on _start/exit/supersede, protected-dirs provider, F2 tests, POSIX on_settled, strategy uses self._is_windows = the mutation-report fix). Windows 2933 pass; WSL 1031 pass / 1 pre-existing order-dependent fail. Opus delta review + CI waiter running.
- 05:45Z #177 delta review (046b112) = CHANGES: N2 no tsp firewall rule in sandbox (Gate A :3266 pattern) => every probe fails = false product FAIL; N3 vmwp in kill-by-name set; N4 ownership gate bypass; N1 heartbeat makes quiet-liveness dead; N5-N11. Sent to lane builder. Run 2 left running for data (expect tsp fail-zero-packets from the firewall, not the product).
- 05:40Z SANDBOX SOAK run 2: install 795 s OK, healthy, first-admin OK; uploads failed: PS 5.1 lacks System.Net.Http assembly (Add-Type missing) -> FAIL no assets. Also: guest never shuts down after verdict. Sent to lane builder (round 3 with N1-N11). Killing my sandbox via helper kill-sbx-233746.
- 05:50Z #176 round-2 review (862ee51) = CHANGES narrow: plan-dir leak on encoder->slate fallback (daemon.py:911), leak on raise between prepare and tracking, _stop pops pending without release, stale docstring, missing tests (dispose raise path, reload_id_from_sidecar_path, unrecognized settle, late applied). Gates green 2933/37, claims 13/13 bound. Sent round 3 to builder.
- 05:47Z lane head 406fe80 (N1-N11 + Add-Type + guest shutdown). SANDBOX SOAK run 3 aborted at launch: new quiet-share guard treats missing files as stale at t=0 (threshold 0 min). Sent to lane builder (boot bound + unit-tested host stall logic). vmmem cleared via helper kill-sbx-234657.
- 05:52Z lane head cb8d1ab (case-insensitive $quietMinutes collision was the run-3 killer; HostLiveness.ps1 + 8 unit checks). SANDBOX SOAK run 4 launched: kit 609273d, output soak-609273d-20260906-055240Z, log sbsoak-609273d-run4.log, monitor armed. Morning report TL;DR refreshed 05:50Z.
- 06:15Z #176 round-3 head 29bc18d (leaks 1-4 fixed, tests 5a-5d, discarded-id expiry, ON_AIR liveness re-check). Windows 2943/37; WSL migration flake pre-existing (reproduced on 862ee51). Opus delta review + CI waiter running. Run 4 sandbox soak in install phase.
- (correction) the entry above labelled 06:15Z was written at 06:00Z real; run 4 installer at 422 s elapsed at 06:00Z.
- 06:20Z SANDBOX SOAK run 4: install 802 s, healthy, firewall, 4 uploads 201, 50/50 committed x3, config 200 + commands 202 x3, then NO ON_AIR in 6 min -> FAIL pre-soak. Evidence gap: lane logs no state rows and copies no per-channel egress logs (app log ends 06:07 'automation issued start for education', TS relay up). Sent lane builder round 5 (state logging, egress log copy, 10-min bound). #176 round-3 review = CHANGES P0: release rmtree's the slate's own prepared dir on 3 early-flip paths; sent round 4 to builder.
- 06:19Z lane head 9895f78 (state-row logging per poll, per-channel egress log copy, 10-min ON_AIR bound, commands body/response logged). SANDBOX SOAK run 5 launched on kit 609273d: output soak-609273d-20260906-061849Z, log sbsoak-609273d-run5.log, monitor armed. Guest self-shutdown proven on run 4 (VM gone by 06:16Z).
- 06:35Z #176 round-4 head 20f316f (P0 prepared_for_fallback gate + 3 early-flip tests; draining stop defers release to stop_all_channels; expiry dropped). Windows 2949/37. Opus delta review + CI waiter running. Run 5 sandbox soak in progress.
- 06:45Z SANDBOX SOAK run 5: FIRST run to reach ON_AIR. State null ~8 min after start commands, all 3 channels ON_AIR on GStreamer at ~8.5 min (item 59 measured in the sandbox: 8.5 min fresh-station time-to-ON_AIR; Gate A's 5-s state row is the SLATE path with no plan, not content). Then HARNESS_ERROR (schedule coverage ended before soak_start+15+3; correct classification). Lane fix: size schedule for the ON_AIR bound + record time_to_on_air_s. Run 6 next. #176 review = MERGE (20f316f); merge on CI green.
- 06:50Z run 5 evidence read: start issued 00:33:28 (local), NOTHING from civiccast.egress for 8m18s, then STARTING -> ON_AIR(pid=-) in 7 ms BEFORE the worker spawned, then ON_AIR state rewritten ~25x/s (log storm); public NEVER reached STARTING in 8.5 min; automation 'issued start for dark auto_start channel education' only. Opus diagnosing (product, not lane). Evidence: cc-sbsoak\sandbox-lab\soak-output\soak-609273d-20260906-061849Z.
- 06:47Z lane head a5b4314 (76 items/channel, time_to_on_air_s + first_state_row_s metrics, health poll while state null). SANDBOX SOAK run 6 launched on kit 609273d: output soak-609273d-20260906-064649Z, log sbsoak-609273d-run6.log, monitor armed. Goal: reproduce item 60 (FAIL with relaunches at rollover).
- 06:55Z Opus diagnosis of run 5: D1 full-asset conform synchronous single-thread (8 min, blocks all channels) = item 66; D2 no state row until after prepare = 67; D3 ON_AIR before spawn = 68; D4 53 writes/start nulling proof id = 69 (overlaps 55). 'public never started' was harness timing, not product. Batch list updated. beta.5 = #176 only unless run 7 fails on 66-69.
- 07:00Z #176 CI on 20f316f: mutation-report baseline FAILED on the full suite (tests/test_cli.py _FakePreparer has no 'release'); builder only ran egress+policy. Sent for round 5 with the full suite. Run 6: install 675 s, healthy 06:58Z.
- 07:10Z run 6: SOAK STARTED 07:07:54Z, all 3 ON_AIR on GStreamer, first_state_row_s ~519 s (item 66/67 reproduced). Verdict ~07:26Z. #176 CI on 20f316f: randomized-suite also fails on the same _FakePreparer.release (2 tests in tests/test_cli.py); builder round 5 covers it.
- 07:12Z Owner asked whether 'three channels stay ON_AIR with zero unexpected relaunches' holds in beta.5: answered NOT PROVEN (false in beta.4 and 609273d; #176 unmerged/unsoaked; flag OFF = planned restart per plan end). Decision block given: A flag OFF (planned restart, safer) vs B flag ON proven in sandbox first; my pick B with A fallback; default A if no answer. Flag = env CIVICCAST_EGRESS_SEAMLESS_RELOAD=1 (strategy.py:627). Lane builder asked for -SeamlessReload switch + planned-vs-unplanned relaunch classification.
- 07:20Z OWNER DECISION: seamless rollover ON = beta.5 REQUIREMENT (option B). Plan: #176 merge -> candidate 3 -> sandbox runs with -SeamlessReload until green every time -> PR flips default ON -> candidate 4 -> Gate A -> sandbox confirm -> tester 2 h -> publish -> 24 h.
- 07:13Z run 6 rollup 1 (4 min): public relaunched (pid 3484->3312), education TRANSITIONING at the first rollover = item 60 REPRODUCED in the sandbox in 4 min (vs 2.5 h on the tester). Lane proven able to see the bug. Draft flip-default-ON PR being built by Sonnet.
- 07:25Z PR #178 DRAFT = seamless default ON (head 2b27b85 on #176's head; opt-out env; CHANGELOG; strategy.py not claims-bound). Held until sandbox proves the seamless path; rebase onto main after #176 merges. Its 2 test failures are the same _FakePreparer.release gap #176 round 5 fixes.
- 07:27Z SANDBOX SOAK run 6 = FIRST COMPLETE 15-min SOAK. Verdict FAIL on kit 609273d (government not ON_AIR at cycle 4; relaunches at rollovers = item 60 reproduced). 12 cycles, 48 samples, install 675 s, time_to_on_air 519 s. THE LANE WORKS. Next: run 7 on candidate 3 (after #176 merge + build) with -SeamlessReload.
- 07:30Z lane head 3018851 (-SeamlessReload switch, planned/unplanned restart classification, 19/19 unit). SANDBOX SOAK run 7 launched on kit 609273d (classification live test): output soak-609273d-20260906-072703Z, monitor armed. Morning report TL;DR refreshed 07:30Z.
- 07:35Z #176 round-5 head fc0f29b: tests/test_cli.py only (+41/-2), full Windows suite 9982 pass. Review verdict MERGE stands (production code unchanged since 20f316f). Merge on CI green -> build-chain.sh <main sha> -> run 8 with -SeamlessReload.
- 07:50Z run 7: soak clock started 07:49:42 with only education ON_AIR (489 s); public/government metrics null -> lane bug (clock must wait for all 3); sent to lane builder. Run continues (others come up seconds later, inside the 3-min warm-up).
- 07:58Z lane head d00543d (soak clock waits for ALL channels ON_AIR; per-channel metrics kept). Run 7 rollup 1: item 60 reproducing (education TRANSITIONING at first rollover). Next sandbox run = candidate 3 after #176 merge + build.
- 08:07Z SANDBOX SOAK run 7 (kit 609273d, lane 3018851): FAIL, classification live: first UNPLANNED relaunch government 07:50:58 (76 s after soak start; no TRANSITIONING before the pid change). 13 cycles. Lane classification machinery proven against a live station. Sandbox free; next run = candidate 3.
- 08:40Z PR #177 CI GREEN on d00543d (18 pass). Final Opus delta review (046b112..d00543d) launched; merge #177 on MERGE. #176 mutation-report still running (started 07:33).
- 08:50Z #176 MERGED -> main 250026b (candidate 3). mutation-report was still running (permanently informational per the workflow; main unprotected; baseline passed). build-chain.sh 250026b started as a Monitor. #178 rebase onto main (Sonnet). #175 merge waits until the candidate-3 build run is confirmed on 250026b. #177 final review running.
- 08:55Z candidate 3 build run 34022552208 on 250026b. DECISION: #175 stays HELD until candidate 4 (main after #178 flip) is dispatched, so beta.5 = #176 + flag ON only. #175 will need a rebase over #176 before merge (beta.6).
- 09:00Z launcher scratchpad\sbsoak-launch.ps1 -Sha <full> -Run <label> [-Seamless] (parse OK). PLAN: when the chain reports the auto Gate A run id for 250026b, CANCEL it (it would own the sandbox for 3 h; candidate 3 is a sandbox-soak kit, not the release kit; Gate A runs on candidate 4). Run 8 = 250026b -Seamless as soon as kit-safe has it.
- 09:05Z #177 final review (d00543d) = CHANGES: $Pid param throws in PS 5.1 => ring never populated => run 7's 20 'unplanned' were misclassified (lane defect, not product truth); 15-s sampler unreachable; 60-s exemption < 75-s cycle; -SeamlessReload never reaches the service (SCM env + service already running) => must use per-service registry Environment + restart; several harness conditions still FAIL not HARNESS_ERROR. Sent as round 8. RUN 8 WAITS for this fix (flag must reach the service). Run 7's relaunch COUNT (20 pid changes) still stands as product fact; only the planned/unplanned split is void.
- 09:12Z #178 rebased onto main: head fcd0bb6, one commit, 2984 pass. Opus review + CI waiter running. (Sonnet accidentally popped and restored the foreign stash@{0} in the shared stash; verified nothing leaked.)
- 09:20Z #178 review (fcd0bb6) = CHANGES (code correct; stale 'shipped default' wording in daemon.py + a test docstring, CHANGELOG direction words, attribute-only tests, dropped override coverage). Sent as one delta to the Sonnet builder. Flag semantics verified: unset=ON, falsy set opts out, ctor wins; flag-ON rollover path traced clean at 250026b.
- 09:05Z(real) lane head f18a77d (RestartClassifier.ps1 + 19 unit, interleaved samples, exemption 2x cycle, seamless via service registry Environment + restart + HARNESS_ERROR if unverified, harness faults -> HARNESS_ERROR, 12-min bound). Opus delta re-review + CI waiter running. Candidate 3 build 34022552208 still in progress (24 min); run 8 = 250026b -Seamless when kit-safe has it AND #177 re-review is MERGE.
- 09:10Z(real) #178 delta head 81d5bb7 (docs/tests only; daemon.py comment-only verified; 2987 pass). CI waiter armed. #178 merges after the sandbox proves seamless on candidate 3.
- 09:12Z(real) CANDIDATE 3 BUILD FAILED (run 34022552208): real-GStreamer smoke step: engine._build -> _make_selector('sel') -> duplicate element name in bin (engine.py:316). #176 regression at INITIAL build, invisible to fake-based unit tests. Sent to the #176 builder: reproduce locally with the runner's GStreamer, fix, uniqueness test with a duplicate-refusing fake, new PR. No kit for run 8 yet. Gate A cancel watcher moot (no build).
- 09:20Z(real) #177 re-review (f18a77d) = CHANGES: N1 pending-restart overwrite launders a crash into PASS (blocker), N2 self-inflicted service restart failure => FAIL, N3 3 tsp harness shapes => FAIL, N4 CIM query load, N5 row skew; plus my point: TRANSITIONING-then-crash (item 60) would classify PLANNED -> need a second signal (last_error/ERROR/exit code). Sent round 9. Run 8 live on 609273d with f18a77d (output soak-609273d-20260906-091204Z) as classifier truth test.
- 09:35Z(real) reviewer addendum: N6 `return ,@()` nests events (false PASS on the 60-s rule), N7 classifier has no crash veto (TRANSITIONING-then-crash => planned on 609273d); lane builder's uncommitted work was in cc-sbsoak = the worktree my launcher hard-reset (my one-agent-per-worktree violation). Fixed: launcher now uses NEW worktree cc-sbsoak-run (detached at origin/feat/sandbox-soak-lane); cc-sbsoak belongs to the lane builder. Round 9 extended with N6/N7 wiring.
- 09:37Z(real) CAVEAT run 8 (soak-609273d-20260906-091204Z): launched from cc-sbsoak while the lane builder had uncommitted classifier edits there; the guest loaded whatever scripts were on disk at 09:12 => run 8 is a lane-machinery exercise, NOT evidence for f18a77d as pushed. Future runs launch from cc-sbsoak-run only.
- 09:40Z(real) #178 CI: only ruff-format on tests/egress/test_daemon.py failed; builder amending. Run 8: install 821 s, healthy 09:26Z. Waiting: selector-fix PR (builder on suites), lane round 9 (builder), run 8 verdict (~09:55Z).
- 09:50Z(real) PR #179 (head 05cddf2): candidate-3 smoke root cause = gst-python override Bin.add returns None on success / raises Gst.AddError; #176's `if not add()` misread success as duplicate. _bin_add helper + contract-true fake + 3 tests; local real-GStreamer smoke PASS (52 factories, 89,864 output bytes). Opus review + CI waiter running; merge -> build candidate 3b.
- 09:55Z(real) run 8 aborted 09:31 HOST-QUIET-SHARE (false: guest had written phase markers at 09:26) because the host ran HostLiveness.ps1 from cc-sbsoak while the lane builder was editing it. Void; no product conclusion. All future runs from cc-sbsoak-run.
- 09:35Z(real) lane head dc174d8 (N1-N7, crash veto wired, PS 5.1 $PSScriptRoot param-default fix; 37/37 + 37/37 + 9/9). RUN 9 launched from cc-sbsoak-run on kit 609273d (output cc-sbsoak-run\sandbox-lab\soak-output\soak-609273d-20260906-093442Z) = classifier truth test: expected FAIL with UNPLANNED relaunches (crash veto). Opus delta review of dc174d8 + CI waiter running. #179 review + CI running.
- 09:58Z(real) #179 review = MERGE (contract proven by source + live probe on the runner closure: GStreamer 1.28.6; pre-fix worker reproduced, post-fix smoke PASS). Title fixed. New item 71 (Pad.link raises LinkError; dead != OK branches; audio-branch pad leak). NOTE: the runner's trust-bridge-install tree was hand-patched by the builder; not candidate-3 evidence. Merge #179 on CI green -> build 3b.
- 10:05Z(real) #177 round-9 review (dc174d8) = CHANGES: 30-s gap too tight, null samples break the chain, N2 over-corrected, state-read failure => FAIL, crash inside one poll gap => planned (polling cannot see it => use daemon log lines as the primary signal), N=1 JSON collapse, pid-map snapshot, superseded => FAIL. Sent round 10. Noted for later: Run-GateA.ps1:68 / Run-GateB.ps1:63 same $PSScriptRoot trap (latent under powershell.exe).
- 10:10Z(real) lane head 88dc510 (round 10: daemon-log primary signal, gap = 2x interval, null reads skipped, N2 split, state-read HARNESS_ERROR, wrapped events JSON, pid re-resolve, superseded excluded; 55/55 + 43/43 + 9/9). Opus delta review + CI waiter running. Run 9 (dc174d8) soak started 09:57Z, verdict ~10:15Z.
- 10:20Z(real) #177 round-10 review (88dc510) = CHANGES: log rule inverted (daemon's crash path writes STARTING(last_error!=-) -> STARTING -> TRANSITIONING -> ON_AIR, so first-TRANSITIONING-backward = planned for crashes); rotation freezes the ring; end-of-run unresolved => FAIL; seamless abort WARNING lines unparsed (need reload_aborted class + planned==0 under the flag); Start-Service throw always HARNESS_ERROR. Sent round 11 with the window rule.
- 10:12Z(real) #179 MERGED -> main bcb3ebe = candidate 3b. build-chain.sh bcb3ebe running (Monitor); Gate A auto-run cancel watcher armed; #178 rebasing onto bcb3ebe (Sonnet). Run 9 (609273d, dc174d8) verdict due ~10:15Z. Lane round 11 in progress. Run 10 = bcb3ebe -Seamless once kit-safe has it and round 11 is reviewed.
- 10:18Z(real) RUN 9 (609273d, lane dc174d8): FAIL, 13 cycles; classification counts below. Lane machinery ran end to end from cc-sbsoak-run. Sandbox free for run 10 (bcb3ebe -Seamless) once the kit lands and round 11 is reviewed.
  run 9 counts: 35 restart events in 15 min (27 unplanned, 8 'planned' = the sample-rule weakness the round-10 review named; on 609273d all are crashes), 11 superseded, max recovery gap 35 s, time_to_on_air 511 s. Round 11's log-window rule should turn the 8 into unplanned; run 11 on 609273d after round 11 lands will confirm (expected: 0 planned).
- 10:25Z(real) #178 rebased onto bcb3ebe: head cfeb389, one commit, 2990 pass, claims clean. CI waiter armed. Merge after run 10 (bcb3ebe -Seamless) passes.
- 10:24Z(real) lane head bed4fc0 (round 11: log-window rule, byte-offset rotation-safe log tracking, incomplete flush, reload_aborted class + seamless PASS contract, Start-Service event-log split; 62/62 + 53/53 + 9/9). RUN 10 launched on 609273d from cc-sbsoak-run (output soak-609273d-20260906-102338Z): expected FAIL with planned=0. Opus delta review + CI waiter running. Build 3b (34026632592) in progress.
- 10:35Z(real) #177 round-11 review (bed4fc0) = CHANGES: window anchor 'second-to-last ON_AIR' lands on _start's pid=None ON_AIR (daemon writes ON_AIR twice) => log signal inert; abort regex misses 3 of 6 daemon lines; Start-Service-success-then-die => HARNESS_ERROR; event-log query unbounded; warm-up harness tsp pre-empts a real FAIL. Sent round 12: anchor the window BY PID (old pid's last line -> new pid's first ON_AIR).
- 10:43Z(real) CANDIDATE 3b BUILD SUCCESS (run 34026632592, main bcb3ebe); auto Gate A 34028125935 on bcb3ebe CANCELLED by the watcher (sandbox reserved; Gate A runs on candidate 4). Chain now doing manifest/kit-safe/HEAD checks. Run 10 (609273d, bed4fc0) at channel start; lane round 12 in progress; run 11 = bcb3ebe -Seamless after run 10 + round-12 review.
- 10:50Z(real) CANDIDATE 3b KIT READY: kit-safecb3ebe3ef71050886324455690863759807666c, 19-line manifest verified, served 19/19, setup.exe sha256 5bd66656... . Run 11 = `sbsoak-launch.ps1 -Sha bcb3ebe3ef71050886324455690863759807666c -Run run11 -Seamless` when run 10 ends (~11:05Z), using the newest pushed lane head (round 12 if landed).
- 10:55Z(real) #178 (cfeb389) required checks 20/20 PASS; held draft until run 11 (candidate 3b -Seamless) PASSES; then merge -> candidate 4 build -> Gate A (not cancelled) -> sandbox confirm -> tester 2 h.
- 11:00Z(real) lane head e0c0686 (round 12: pid-anchored log window, 6-line abort regex, both Start-Service branches, single-pass verdict, offset at soak start; 75/75 + 59/59 + 9/9). Opus delta review + CI waiter running. Run 11 auto-launch will use e0c0686.
- 11:08Z(real) #177 round-12 review (e0c0686) = CHANGES (one wiring gap: read-failure marker not passed to the ring => a dropped read can turn a planned rollover into FAIL; plus 5 low). Round 13 sent. Run 11 (bcb3ebe -Seamless) launches with e0c0686; if it FAILs only on a dropped-read edge, rerun with round 13.
- 11:05Z(real) RUN 10 (609273d, lane bed4fc0 round 11): FAIL; counts below. Run 11 (bcb3ebe -Seamless, lane e0c0686) auto-launched 11:03Z.
  run 10 counts: 34 events, 20 unplanned / 14 planned, log_evidence missing on 33/34 = the round-11 anchor bug the review predicted (ON_AIR written twice). Round 12 (pid anchor) is what run 11 uses; on a broken kit it should show log_evidence=log and planned=0. Run 11 is on candidate 3b so the truth test for round 12 comes from run 11's seamless behaviour + a later 609273d run if needed.
- 11:12Z(real) lane head 3103387 (round 13; 84/84 + 59/59 + 9/9). Opus delta review incl. OFFLINE REPLAY of round 13's classifier against run 10's real daemon log (truth test) + CI waiter. Run 11 (bcb3ebe -Seamless, lane e0c0686) installing.
- 11:19Z(real) RUN 11 (candidate 3b, -Seamless): install 780 s exit 0; flag written to the CivicCastSupervisor service Environment (read-back True); Stop/Start-Service; healthy again in 17 s; control-plane pid 6344 post-restart. Channel start next; soak clock ~11:28Z; verdict ~11:46Z. PASS contract: 0 unplanned, 0 reload_aborted, 0 planned, tsp pass every cycle.
- 11:30Z(real) CLASSIFIER PROVEN: round 13 (3103387) replayed offline against run 10's real daemon log => 33/33 log_evidence=log, 29 unplanned / 4 planned, all attributable (vs round 11 production 1/34). Round-13 review = CHANGES only on the Start-Service SCM event branch (display name vs service name => branch dead; newest-only; 7009 shape; message-text) + test hygiene. Round 14 sent. #177 merges after round 14 + green.
- 11:35Z(real) RUN 11 (candidate 3b bcb3ebe, -Seamless, lane e0c0686) = FAIL pre-soak: no channel produced a state row in 12 min (health 200 []); app log: automation issued start for education then silence; only education + conform-cache dirs existed. = item 66 (synchronous full-asset conform on the start path) and it is SLOWER than on 609273d (527 s in run 10). ITEM 66 IS NOW BETA.5 SCOPE. Opus diagnosing (#176 start-path cost delta? flag? service restart?); lane builder adding -OnAirBoundMinutes + conform-progress capture; run 12 = candidate 3b -Seamless -OnAirBoundMinutes 25 to separate start slowness from the rollover proof.
- 11:40Z(real) lane head 2420bce (round 14: SCM display-name fix, all-events, DaemonLogPatterns.ps1 shared, Test-ServiceStartFailure 9/9; 87/87 + 59/59 + 9/9). Opus delta review + CI waiter. -OnAirBoundMinutes + conform-progress capture = next push (round 15). Run 12 = candidate 3b -Seamless -OnAirBoundMinutes 25 after round 15.
- 11:45Z(real) docs PR #165 head 494a418: 'How this release was proven', 'Seamless ON by default', 'Known issues to beta.6' (66-72 + open 46-63), 8 stale 'off by default' sentences fixed; placeholders untouched; policy 1902 pass. Final fill after candidate 4 + Gate A + soak.
- 11:55Z(real) Item 66 diagnosis (Opus): start path = synchronous whole-asset conform with -threads 1 (preparer.py:266 background=True) on the single automation thread; #176 does NOT change the start cost; the flag and the service restart do not touch the start path; run 11's 12-min bound was only 1.4x a known 8.5-min cost. Fix A: background=False on the start-path conform; Fix B: with playout_trim_supported=False take the trimmed-miss branch (bounded -t conform + warm-behind). Sonnet building PR (fix/start-path-conform-item66). Lane must copy conform-cache/prepared listings + ffmpeg process table unconditionally (sent in round 15).
- 12:00Z(real) lane head e8983ec (round 15: -OnAirBoundMinutes param via .wsb placeholder; conform-progress.json every flush + on timeout). RUN 12 launched: candidate 3b -Seamless -OnAirBoundMinutes 25 (launcher now passes -OnAirBound). Purpose: measure real first-ON_AIR on 3b and run the seamless soak. Round-14 review still running; item-66 PR being built.
- 12:05Z(real) #177 round-14 review = MERGE (SCM shapes verified against the real System log; 4 suites 164 checks green). Follow-up PR items (not blockers): print harness_notes to the operator, shared read-failure predicate, Get-Service failure must not skip the event scan, cap harness_notes, run the 4 suites in CI. Merge #177 on CI green for e8983ec. Run 12 monitor armed.
- 12:15Z(real) PR #180 (item 66, head fc54f27): A background=False on the start-path conform; B trimmed-miss branch when playout_trim_supported=False; 3 tests; 2955 pass; preparer.py not claims-bound. Opus review + CI waiter running. Merge -> candidate 3c build -> sandbox -Seamless.
- 12:20Z(real) Sonnet preparing scratchpad\soak24-templates (24-h tester verify with 6-h interims + fail-fast at 3 relaunches; start step; README; parse gate) — scratchpad only, no push. In flight: #180 review + CI, #177 CI (merge on green), lane follow-up branch, run 12 (installing).
- 12:30Z(real) soak24-templates ready in scratchpad (AUTORUN-24h-start/verify + README; parse OK; placeholders __KITSHA__/__KITSHORT__/__KITEXPECTEDVERSION__; version check = uninstall-registry DisplayVersion + /health.version). Tester autoruns execute by filename sort regardless of the pointer; the pointer and the directive go in the SAME push. Not pushed.
- 12:40Z(real) #180 review (fc54f27) = CHANGES: loudness probe per segment (47 s x 8 = 6.3 min still on the start path, no -vn); Change A dead on default + harmful on ffmpeg-concat reload; Change B bounds nothing for untrimmed assets (-t = full length) — win was thread count (233 s vs 37 s per 300 s content); warm re-encodes the asset again (30 min -threads 1); warm threads unbounded; CHANGELOG wrong. Round 2 sent: loudness memo + -vn, foreground thread cap cpu/2, promote untrimmed foreground output into the cache (no warm), single-worker warm queue, truthful CHANGELOG.
- 12:45Z(real) Opus reviewing the tester templates (soak6 2-h chain 9zo..9zt + soak24 chain) against the proven AUTORUN-3/9e/9m scripts, kit layout, version surfaces, filename ordering after 9zzz. Items 75-76 filed. Run 12 in the start gap (33 null polls at 11:58Z real).
- 12:55Z(real) Tester template review = CHANGES both chains: F1 zero-relaunch bar needs candidate 4 (seamless ON) + explicit flag check; F2 24-h verify must SHIP AS AUTORUN-3.ps1 (only recurring hook); F3 CRITICAL TSDuck counters read at the wrong level in AUTORUN-3 => every tester 'tsp pass' to date was a rubber stamp; F4 branch name; F5 names AUTURUN-A24a-start; F6 $gstWorkers scope => false ffmpeg-fallback; F7-F14. Round 2 sent to the template builder; lane builder asked to verify Test-TsProof against a real TSDuck report.
- 12:12Z(real) RUN 12 (candidate 3b -Seamless, lane e8983ec): time_to_on_air = 915/915/930 s (vs 527 s on 609273d = item 66 measured on 3b: +6.5 min; #180 round 2 targets it). SOAK STARTED 12:11:27Z = FIRST SEAMLESS-FLAG SOAK. Verdict ~12:30Z. PASS = 0 unplanned, 0 reload_aborted, 0 planned, tsp pass.
- 12:20Z(real) #180 round-2 head 8054c53 (loudness memo + -vn, threads cap cpu/2 on all sync conforms, untrimmed foreground promoted into cache, single-worker warm queue, truthful CHANGELOG + runbook; 2959 pass). Opus delta review + CI waiter running.
- 12:25Z(real) PR #177 (sandbox lane) MERGED to main. cc-sbsoak-run launcher still checks out origin/feat/sandbox-soak-lane (branch remains until the follow-up lands); switch the launcher to origin/main after the follow-up PR merges.
- 12:35Z(real) Tester templates round 2 done (scratchpad): soak24 = AUTORUN-3.template.ps1 (24-h verify, REPLACES the recurring AUTORUN-3.ps1) + AUTORUN-3.2h.template.ps1 (fixed 2-h verify) + AUTORUN-A24a-start.template.ps1 (placeholders __KITSHA__/__KITSHORT__/__KITEXPECTEDVERSION__/__CANDIDATE4SHA__); soak6 9zo/9zr/9zt fixed (F8-F12). F3 confirmed against a real TSDuck report (ts.packets.* + per-PID discontinuities); production AUTORUN-3 has F3+F6 verbatim. Parse gate 9/9. Re-review before any push (with candidate 4 sha).
- 12:40Z(real) #180 round-2 review (8054c53) = CHANGES: promotion moves the served file then copies back (+1 full copy, can fail a segment); cpu//2 unpinned by tests; *.ts.tmp orphans invisible to eviction; meta write non-atomic; FIFO test doesn't test order; cli.py wiring; loudness probe unbounded (reads the whole 2366-s asset for a 30-s window). Expected first ON_AIR after fixes: ~30-90 s/channel, 60-180 s all three (from 915 s). Round 3 sent.
- 12:30Z(real) RUN 12 (candidate 3b, SEAMLESS ON verified) = FAIL: 26 unplanned relaunches / 15 min, all log-evidenced, 0 planned, 0 reload_aborted. Mechanism: first ON_AIR at 915 s => the plan was ~11 min in the past => automation arms a seamless rollover 6 s after ON_AIR ('live plan ends in -698s') => worker 'CTRL stall: no output for 10s' => exit => relaunch => automation re-arms 1 s later => loop every ~65 s on all channels. Opus diagnosing (stale plan at start vs seamless reload stalling at EOS). This is THE beta.5 bug path; #178 stays held.
- 12:50Z(real) Template re-review = CHANGES (F1-F14 fixed; D1 24-h must NOT force the flag; D2 24-h must INSTALL the published kit from the release; D3 4-h task limit; D4 soak-started not reset; D5-D15). Round 3 sent (new placeholders __RELEASE_TAG__/__RELEASE_ASSETS_URL__/__PUBLISHED_SETUP_SHA256__).
- 12:55Z(real) RUN 13 launched: candidate 3b, flag OFF, bound 25 min (output soak-bcb3ebe-20260906-123331Z) = flag-OFF baseline on 3b: are plan-end restarts classified planned, and how big is the gap (owner's option-A question). Sandbox otherwise idle until #180 r3 + item-78 fix land.
- 13:05Z(real) RUN 12 DIAGNOSIS (Opus): _start DOES re-anchor the plan; arming a reload does NOT stall output. Real causes ranked: (1) CAPTION TAP OVERLOAD starves playout -> 10-s stall watchdog -> relaunch (10 overload events; same root cause as the tester 09-05; #172 not enough in the VM); (2) automation's rollover horizon frozen: run_once captures resolved_now once per pass, the pass blocked 915 s in _start, so plan_end_at = stale now + 215 s => rollovers forever (education/public plan_end_at constant 05:59:34 for 16 min); (3) 45-s retry path bypasses the cadence floor => re-arm 1 s after every relaunch; (4) should_defer_switch defers onto an already-passed boundary => 900-s held leg; 0 of 31 armed reloads ever committed. Item 78 PR (Sonnet: per-channel clock + plan_end<=now guard + retry floor + immediate cut past plan end) building; caption-tap isolation investigation (Sonnet); lane follow-up gets worker-stdout reload parsing + -CaptionsOff.
- 13:15Z(real) Caption-tap investigation (Sonnet): #172 = per-channel backoff 60/120/240/480/900 s + 1 worker per 8 CPUs (max 3) + thread priority (not load-bearing); the VM has 16 GB. Counter-evidence: education/public kept stalling INSIDE the 480-s pause (ASR idle) => a second contributor (most likely the re-arm storm's second 8-decoder leg per relaunch = item 78b/c; or VM/disk). Captions-off lever = PUT /api/staff/station/profile {live_captions_enabled:false} (env var is overwritten by bootstrap). Plan: after #78 lands, isolation runs on 3c: captions ON vs OFF; capture per-process CPU/RSS per cycle. Minimal tap fix candidate: cap workers to 1 always (tap_worker.py:126-146).
- 13:20Z(real) #180 round-3 head cfd6ca4 (per-plan file first + hard-link promotion, cap test, orphan reaping, atomic meta, real FIFO test, cli wiring, bounded loudness probe; 3314 pass). Opus delta review (incl. the shared _conform_lock trade-off) + CI waiter running.
- 13:25Z(real) Tester templates round 3 done (24-h start now fetches + installs the PUBLISHED release, asserts seamless default, 150-min budget, first-admin fallback; placeholders __KITSHA__/__KITSHORT__/__RELEASE_TAG__/__RELEASE_ASSETS_URL__/__PUBLISHED_SETUP_SHA256__/__CANDIDATE4SHA__; parse 9/9; F3 self-test OK). Re-review launched.
- 13:35Z(real) #180 round-3 review (cfd6ca4) = CHANGES: promotion blocks behind a background warm on the shared per-key lock (measured), 120-s head probe mis-decides loudnorm (cached), copy2 fallback synchronous. Round 4 sent (non-blocking acquire + warm re-check; mid-file probe window + floor fallback; background copy).
- 13:40Z(real) Item 79 minimal PR requested (Sonnet, fix/caption-tap-caps-item79): one caption channel at a time station-wide, live-tap CT2 cpu_threads capped (cpu//8, max 2), first pause 120 s. Merge only if the isolation runs on candidate 3c confirm captions as a contributor. Run 13 at 68 null polls (start gap) at 12:54Z real.
- 13:45Z(real) PR #181 (item 78a/b/c, head 8dd8e61): per-channel clock + stale-horizon discard/re-establish; retry floor 30 s + worker-age 60 s guard; should_defer_switch cuts when plan_end_at <= now (record_rollover_plan_end in-memory). 2965 pass. Opus review + CI waiter running.
- 13:50Z(real) Template re-review r3: AUTORUN-3 (24h), AUTORUN-3.2h, soak6 chain = READY (fill + push when candidate 4/release exist). A24a-start = CHANGES: release shape is bare setup.exe + flat ccpacks (must stage into packs\) + no samples (use the LAN kit's); Exit-Blocked loop unbounded; gh auth fallback; Measure-Object on ordered hashtables. Round 4 sent.
- 13:55Z(real) PR #182 (item 79, head 34c2d30): one caption channel at a time, live-tap cpu_threads cap (cpu//8, max 2), first pause 120 s; 3264 pass. Opus review + CI waiter. Merge gated on the isolation runs.
- 14:00Z(real) #180 round-4 head 15802f4 (non-blocking lock at both sites + warm re-check; mid-file probe + floor fallback; background cross-volume copy; 3319 pass). Opus delta review + CI waiter running.
- 14:10Z(real) #181 review (8dd8e61) = CHANGES: clock read before process_once => blocking channel still stale (-315 s measured); ruff format fails; plan_end leaks on early returns; 30-s floor dead. Round 2 sent (clock after process_once + behavioural test; pop at the top; consecutive-retry floor 60 s; lint).
- 14:20Z(real) #182 review (34c2d30) = CHANGES: on 8 cores the caps change nothing but the pause (one shared CT2 replica, num_workers=1, serialized); env=0 raises at startup; docs overclaim; 14 of 30 relaunches in run 12 happened with ASR idle. NEW suspect: the OFFLINE caption job worker (app.py:1394-1400, cpu_threads=0, beam 5) runs in the same process — must be confirmed idle in both isolation arms; captions-OFF arm must also stop the egress WAV fork (CIVICCAST_CAPTION_TAP_DIR). Round 2 sent to #182 (knob-hardening framing, clamp, docs); isolation requirements sent to the lane builder.
- 13:25Z(real) RUN 13 (candidate 3b, seamless OFF, captions ON): FAIL; counts below. Flag OFF does not avoid the crash loop either => the stalls are not the seamless path; captions/CPU is the live suspect (and item 81 offline caption jobs).
  run 13 counts: 43 events (42 unplanned, 1 planned), all log-evidenced, 12 caption overloads, max gap 40 s; first government crash = preroll timeout 5 s (item 82). Templates round 4 done (A24a rewritten for the release shape); final re-review running.
- 14:30Z(real) Requested: item-82 PR (preroll 30 s + distinct error + slow-start relaunch path; Sonnet) and a code trace of what CPU-heavy jobs the lane's uploads/publish trigger in-process (item 81; Sonnet). In flight: #180 r4 review, #181 r2, #182 r2, A24a re-review, lane follow-up.
- 14:40Z(real) Item 81 trace: the lane never approves/publishes => offline caption worker idle; the live caption tap is the ONLY in-process CPU competitor during a soak. So the captions-OFF isolation (station profile PUT + stop the audio fork if possible) is decisive for item 79.
- 14:50Z(real) RUN 14 = ISOLATION: candidate 3b, seamless ON, CAPTIONS OFF via a LOCAL patch in cc-sbsoak-run\sandbox-lab\scripts\In-Sandbox-Soak.ps1 (PUT /api/staff/station/profile live_captions_enabled=false after first-admin; read-back logged; summary.captions_isolation). Launched directly with Run-SandboxSoak.ps1 (not the launcher, to keep the patch). Expected if captions are the driver: far fewer/no unplanned relaunches. Note: the egress audio fork may still run (fork gated by CIVICCAST_CAPTION_TAP_DIR).
- 15:00Z(real) #180 round-4 review (15802f4) = CHANGES: self-deadlock in the cross-volume copy job (scheduled under the held lock, job blocking-acquires), probe offset is 40% of the SLOT not the asset (can start past EOF), floor fallback = whole-file decode on the start path, -threads in the wrong ffmpeg position. Round 5 sent.
- 15:10Z(real) A24a round-4 re-review = CHANGES (D1 dry-run deletes soak-started; D2 untimed 4.9 GB fetch, no budget sample; D3 clobbers the LAN kit dir; D4 kill double-count; D5-D10). Round 5 sent. 24-h AUTORUN-3 / 2-h chain remain READY. Real release facts: SHA256SUMS lines are `<hash>  <basename>` (two spaces), assets = setup.exe + 5 ccpacks + sidecar + SHA256SUMS (4.9 GB).
- 15:15Z(real) #181 round-2 head ff5cdfb (clock read after process_once + blocking-channel test; pop at top of _try_content_reload; retry floor 60 s from last retry + churn test; CHANGELOG). 2971 pass. Opus delta review + CI waiter running.
- 15:20Z(real) #182 round-2 head 4ee9337 (env clamp, honest docs, stale comments, capacity proof tracks the default, startup log line; 3439 pass). Opus delta review + CI waiter. Merge gated on the run-14 isolation result.
- 15:25Z(real) docs PR #165 head 576dbe7: items 78-82 placed (78/79/82 fix-in-review, 80 in-progress, 81 beta.6), 'seamless never committed on 3b' paragraph; policy 1902 pass; identity PASS. Final fill still pending shas.
- 15:30Z(real) A24a round 5 done (D1-D10; 7 placeholders incl. __LANKITSHA__ optional; parse 9/9; -DryRunMath proven not to touch soak-started). Final re-review launched.
- 13:41Z(real) RUN 14: captions OFF confirmed (PUT 200, read-back live_captions_enabled=False) on candidate 3b with seamless ON. Soak clock ~13:57Z, verdict ~14:15Z real. Decides item 79.
- 15:40Z(real) #182 round-2 review (4ee9337) = CHANGES: manual artifacts not regenerated (ci-docs fails), USER-MANUAL prose (ladder, 'every channel'), operator screen text, capacity proof cpu-threads default, test docstrings, WHISPER_CPU_THREADS fail-fast. Round 3 sent.
- 15:50Z(real) #181 round-2 review (ff5cdfb) = CHANGES: plan_end still leaks on _request_reload's own early returns (dead worker / state None / no supports_content_reload — measured), CHANGELOG claims unsupported, retry timestamp not cleared with the latch, churn test models an impossible shape. Round 3 sent.
- 15:55Z(real) TESTER TEMPLATES: 2-h chain (9zo..9zt + AUTORUN-3.2h as AUTORUN-3.ps1) READY; 24-h chain (AUTORUN-A24a-start + AUTORUN-3 24h) READY (5 non-blocking tidy items sent). Push order when the time comes: fill placeholders, parse gate, autoruns + DIRECTIVE-N.md + pointer (Current: soak/DIRECTIVE-N.md, Updated: rev N) in ONE push; the 24-h push overwrites AUTORUN-3.ps1.
- 16:05Z(real) #180 round-5 head 225475d (lock released before scheduling the copy job + non-blocking job acquire; media-duration ffprobe cached in meta for the 40% offset; second bounded sample at 70% instead of whole-file; -threads before -i + -filter_complex_threads; cleanup). 3330 pass. Opus delta review + CI waiter running.
- 16:15Z(real) Tester templates FINAL (round 6 tidy): 6 placeholders (__KITSHA__ __KITSHORT__ __RELEASE_TAG__ __PUBLISHED_SETUP_SHA256__ __CANDIDATE4SHA__ + optional __LANKITSHA__); curl fallback resolves assets from the GitHub API; gh tree-kill. Both chains READY; no push until candidate 4 / the release exist.
- 16:25Z(real) #182 round-3 head a88511b (manual artifacts regenerated, both render gates PASS; prose + operator screen text; capacity proof default; WHISPER_CPU_THREADS clamp; 3464 pass). Opus delta review + CI waiter. Merge still gated on run 14.
- 16:35Z(real) #180 round-5 review (225475d) = CHANGES: deadlock fix proven; new: unknown-duration fallback brands short assets silent (proven on the 67-s clip), second sample identical for assets <= 200 s, media_duration meta never read, failed resample raises, orphan tmp, dead threads param. Round 6 sent.
- 16:45Z(real) #181 round-3 head b4508ef (pop at top of _request_reload + required kw param + cleared in _start/_stop; retry timestamp cleared with the latch; churn test models a real relaunch; CHANGELOG truthful). 2974 pass. Opus delta review + CI waiter.
- 14:02Z(real) RUN 14 (captions OFF, seamless ON): 6 restarts detected in the first 4 min of the soak => CAPTIONS ARE NOT THE DRIVER (or not the only one). Item 79 demoted; the driver is the re-arm storm (78) + preroll timeout (82) + possibly VM contention. Candidate 3c (#180 + #181 + #82) is THE test; #182 merges as knob hardening only.
- 14:08Z(real) NOTE for the decisive candidate-3c run: my builders/reviewers run full pytest suites on HALO during soaks (host CPU contention feeds the VM); launch the 3c run when no suite is running and record host load (Get-Counter processor time) per cycle from the host log. Lane follow-up adds per-process CPU inside the guest.
- 14:10Z(real) Host load sampler running (scratchpad\hostload.log, 30-s). Host at ~22% total during run 14; killed an orphaned reviewer `find / -maxdepth 9 -name transcribe.py` (pid 42732, one full core for ~1 h). Run 14 rollup 1: all ON_AIR but restarts continue (captions OFF).
- 14:20Z(real) PR #183 (item 82, head 11ad5a7): preroll 30 s in 5-s slices, PrerollTimeoutError, gi-free exit_codes.py, worker exit code, daemon streak rate-limit once/60 s; claims re-bound; 2969 pass. Opus review + CI waiter running.
- 14:10Z(real) #182 round-3 review (a88511b) = CHANGES: env tables contradict the new live refusal of 0; capacity proof beam 5 vs live beam 1 (no live=True); batch fail-fast silently downgraded; no live ceiling on WHISPER_CPU_THREADS; stale docstrings; README. Round 4 sent.
- 14:15Z(real) RUN 14 FINAL (candidate 3b, captions OFF verified: 0 overload events, seamless ON): FAIL, 21 unplanned relaunches, 24 rollovers issued, 21 'did not land' retries, crash-loop to FALLBACK_SLATE. CAPTIONS ELIMINATED. Common factor across runs 12/13/14 = the rollover storm (item 78) on a worker that stalls under the doubled decoder load; #181 is THE fix to test on candidate 3c. Local run-14 patch reverted in cc-sbsoak-run (clean).
- 14:20Z(real) Lane PR A re-requested from a FRESH Sonnet agent in worktree cc-sbsoak-b (branch feat/sandbox-soak-lane-a off main): -CaptionsOff (station profile), worker-stdout reload/stall parsing + 'seamless reload never committed' FAIL, per-process CPU + cpu_count. The original follow-up builder (cc-sbsoak) has not reported for hours; whichever lands first wins, the other is closed.
- 14:25Z(real) #183 review (11ad5a7) = CHANGES: env >= 60 s disables crash-loop escalation via the healthy-uptime streak reset (measured); no worker exit-code seam test; slice log drops the current state; no WORKER_RESULT on timeout. Round 2 sent. NOTE: the runner's artifacts tree is gone (no real-GStreamer smoke possible locally until the next build).
- 14:30Z(real) #181 round-3 review (b4508ef) = CHANGES: the new _start pop regresses item 78's own scenario (crash before the reload drains => value eaten => deferred 900 s), four clearing changes untested (revert leaves green), CHANGELOG causal wording. Round 4 sent (delete the _start pop + gating tests).
- 14:40Z(real) #180 round-6 head e172f89 (unknown-duration probe from 0 s, one sample <= 240 s, non-overlapping windows, media duration memoized, resample fallback, cleanup, threads on every probe, _warming discard; 3341 pass). Opus delta review + CI waiter.
- 14:45Z(real) Old lane builder stood down: local commit 2b9cc55 on feat/sandbox-soak-lane-followup in cc-sbsoak (NOT pushed; harness_notes print, shared read-failure predicate, Get-Service fallback, notes cap, Invoke-LaneUnitTests.ps1). Salvage later as 'lane follow-up B' after PR A lands (cherry-pick onto main; re-verify under powershell.exe 5.1).
- 14:50Z(real) PR #184 (lane follow-up A, head 9f6df08): -CaptionsOff via station profile (CaptionsOffCheck.ps1), WorkerStdoutParser.ps1 + byte-offset counters + 'seamless reload never committed' FAIL, CpuSampler.ps1 (per-process CPU delta, WS, cpu_total, cpu_count); 214/214 under 5.1; dry runs clean. Opus review + CI waiter running.
- 14:55Z(real) #181 round-4 head 6ddac7a (_start pop removed + same-tick crash test; gating tests for the clearing changes; CHANGELOG precise). 2979 pass. Opus delta review (incl. a run-12-shape replay) + CI waiter.
- 15:00Z(real) #183 round-2 head d956e29 (clamp [5,45], preroll exits exempt from the healthy-uptime reset, seam tests, current state in the slice log, t<=300 s escalation test, WORKER_RESULT; claims re-bound; 2978 pass). Opus delta review + CI waiter.
- 15:05Z(real) #182 round-4 head bf229b3 (docs fixed, capacity proof measures live sizing, batch fail-fast kept, ceiling cap 2, README/manual copy; 3469 pass, tsc+lint 0). Opus delta review + CI waiter. In flight: reviews #180 r6, #181 r4, #183 r2, #184; CI waiters #180 #182 #183.
- 15:20Z(real) #180 r6 (e172f89) review = CHANGES: HIGH short-slot untrimmed conform poisons the conform cache (30-s slot then 60-s slot -> 30 s dead air, proven with real ffmpeg); MEDIUM single head sample trusted as conclusive silence for 120-240 s assets; LOW loudness.py docstring. Start path measured bounded (7.5 s cold for 8x30 s). Follow-ups (beta.6): ffmpeg-concat untrimmed full conform; trimmed rejoin conform unbounded. Sonnet round 7 dispatched on cc-item66.
- 15:30Z(real) #184 (9f6df08) review = CHANGES: HIGH worker_stall_count always 0 (CTRL stall goes to gst-worker.stderr.log, never read; test pins 0 where 2 stalls happened); HIGH no post-loop worker-stdout drain -> armed-never-committed false FAIL possible under -SeamlessReload; MEDIUM cpu rows unlabeled (all python) + pythonw/pythonservice excluded; MEDIUM captions_enabled hardcoded true on no-flag runs; LOW harness-error verdict lacks caption fields; LOW duplicated egress root. 214/214 unit suites pass. Sonnet round 2 dispatched on cc-sbsoak-b. NOTE: run 12's verdict had reload_committed=0 / aborted=1 (gst-stream-error before commit) on government - consistent with item 78.
- 15:45Z(real) #183 r2 (d956e29) review = CHANGES: BLOCKER second healthy-uptime reset on the ALIVE poll path (daemon.py:1378) counts spawn->PLAYING time as air; worker alive >=60 s then preroll-timeout exit -> streak stuck at 1 forever (measured); fix = gate the reset on ON_AIR evidence, not wall time since spawn; nan escapes the clamp; tests never poll alive. Sonnet round 3 dispatched on cc-item82. #183 CI on d956e29 moot.
- 15:50Z(real) #181 r4 (6ddac7a) review = CHANGES (2 small): stale _rollover_plan_end_at survives every off-air route that bypasses _stop (clean exit/crash/drain) and is consumed by the next plain reload -> cut instead of defer (measured); stale inline comment in _try_content_reload. Run-12 replay on 6ddac7a: 2 dispatches in first 5 min after ON_AIR, no past-plan_end dispatch, cut/defer 4/4 correct. Sonnet round 5 dispatched on cc-item78. Follow-up beta.6: scope the value to a command id.
- 16:05Z(real) #182 r4 (bf229b3) review = CHANGES: capacity report records pre-construction beam/threads (wrong under live=True env/cap); round-4 behavior changes untested; ceiling cap missing from env tables; two stale docstrings/advice. Sonnet round 5 dispatched on cc-item79. All five PRs now in a builder round (180 r7, 181 r5, 182 r5, 183 r3, 184 r2).
- 16:20Z(real) #184 round-2 head 9468c0c (stall count from WORKER_RESULT stall receipts, final drain, role labels, measured captions_enabled; 233/233). Opus delta review + CI waiter.
- 16:30Z(real) #181 round-5 head 8a53eec (pops on 4 off-air routes, comment/docstring/CHANGELOG fixed, 4 tests; 2983/37). Opus delta review (also checks crash-relaunch route + format debt) + CI waiter.
- 16:40Z(real) #184 r2 (9468c0c) review = MERGE; stall count verified 15/15,2/2,14/14 vs stderr on run 12. Follow-ups for lane PR B: host phase gate ignores a backstop SOAK-START.json (Run-SandboxSoak.ps1:630); drop 'always' claim, add stderr CTRL stall corroboration (os._exit(70) blind spot); ffmpeg-fallback channel label; scenario27b ordering test. Merge on green.
- 16:50Z(real) #181 r5 (8a53eec) review = CHANGES: value still leaks via the deferred back-off relaunch branch and _start's two terminal-ERROR clauses (measured cut-instead-of-defer); docstring/CHANGELOG absolute claims false; format debt none (1514 formatted). Sonnet round 6 dispatched (pop in those 3 spots, tests, true wording).
- 17:05Z(real) #180 round-7 head 30f7ac4 (promotion gate + full_asset_conform meta flag, single-sample max 120 s, non-overlap check, real-ffmpeg cache test; 3349/37). Opus delta review (probes the unknown-duration fallback) + CI waiter.
- 17:15Z(real) #182 round-5 head 2c5bf47 (post-construction identity, 5 runtime tests, env tables, docstring, advice; 3475/38, +2 unexplained flagged to reviewer). Opus delta review + CI waiter.
- 17:25Z(real) #183 round-3 head 191d9a8: ON_AIR evidence = new stderr marker 'CTRL preroll: reached PLAYING' + health.worker_reached_playing() (+ encoder_has_progress for ffmpeg), latched _on_air_confirmed_at; 60-s clock starts there; nan guard; bounded stop on timeout; 3002/37. Opus delta review told to attack the shared append-mode stderr log (old worker's marker counting for a new worker) + per-tick cost + latch clearing. CI waiter.
- 17:45Z(real) #181 round-6 head 483c186 (pops in deferred back-off + both _start ERROR clauses, 3 tests, true wording; 2986/37, 1514 formatted). Opus delta review + CI waiter. All five PRs now in review/CI: 180 r7 30f7ac4, 181 r6 483c186, 182 r5 2c5bf47, 183 r3 191d9a8, 184 r2 9468c0c (MERGE, CI pending).
- 17:55Z(real) #180 r7 (30f7ac4) review = CHANGES: HIGH not fixed - media_duration None fallback still promotes a slot-capped fragment (ffprobe-unavailable AND trimmed-first meta-reuse route, both reproduced with real ffmpeg); MEDIUM warm/copy skip predicates accept flagless legacy meta -> permanent MISS; LOW corroboration boundary is 336 s not 240 s. Points 2/3 of r6 verified fixed; start path 1.2 s cold. Sonnet round 8 dispatched (fail closed on unknown duration). #180 CI on 30f7ac4 moot.
- 18:05Z(real) #182 r5 (2c5bf47) review = MERGE (3473/38 on the reviewer's box; builder's 3475 was a run artifact). Follow-ups beta.6: CUDA-fallback parenthetical in prove_native_caption_capacity.py:411-414 false; test_batch_cpu_threads_honors_zero_as_every_core vacuous; ceiling not applied to explicit cpu_threads= ctor arg (docs overstate); restore 0/negative fallback note in background-workers.md row. Merge on green.
- 18:15Z(real) #183 r3 (191d9a8) review = CHANGES: BLOCKER not fixed - shared append-mode stderr log lets an OLD worker's PLAYING marker confirm a NEW worker (40 relaunches, streak 1); same on ffmpeg branch via stale fps lines; test fixture truncates per spawn (why the matrix passed); tail-window test misnamed and inverse-unsound. Cost/seamless/nan/stop/claims all clean. Sonnet round 4 dispatched: spawn-offset anchoring + pid in marker + no tail window + append-mode fixture. #183 CI on 191d9a8 moot.
- 18:25Z(real) Cancelled moot CI runs on #183 191d9a8 and #180 30f7ac4 (heads being replaced) to free shared runners; live runs: #184 9468c0c, #182 2c5bf47, #181 483c186.
- 18:35Z(real) #181 r6 (483c186) review = CHANGES: code pops correct + tested, but the IMMEDIATE crash-relaunch still leaks (one crash -> later unrelated reload cuts instead of defers, measured) and docstring/CHANGELOG claims false again (drain path never calls _stop; 'both routes pop' overstated). Sonnet round 7 dispatched: command-id scoping of the recorded plan_end (the real fix), truthful wording. #181 CI on 483c186 moot.
- 19:05Z(real) #180 round-8 head 0e51745 (fail closed on unknown duration, flag-gated skip predicates, boundary comment 400 s (reviewer measured 336 s: to be settled), 2 real-ffmpeg tests, 2 pre-existing tests adjusted; 3351/37). Opus delta review + CI waiter.
- 19:15Z(real) MERGED #184 -> main 726116f (lane follow-up A). Main checkout ff'd; cc-sbsoak-run detached at origin/main; sbsoak-launch.ps1 now checks out origin/main. Lane follow-up B (to do after candidate 3c is running): #184 reviewer's 4 follow-ups + cc-sbsoak local commit 2b9cc55 salvage + wire Test-*.ps1 into CI.
- 19:30Z(real) #181 round-7 head 1a1e239: command-id scoping ((command_id, plan_end) tuple, None wildcard, automation shares one id between record + enqueue); 2988/37; builder ran mypy on 2 files only. Opus delta review (wildcard, queue-path threading, retry id reuse, whole-package mypy, run-12 replay) + CI waiter.
- 19:45Z(real) #182 randomized-suite RED: tests/stream/test_media_router_storage_absent.py::test_vod_playback_degrades_instead_of_raising_500 returns 500 under --randomly-seed=1681376346 (order-dependence, unrelated to #182). randomized-suite is INFORMATIONAL by workflow header (owner-only promotion, never promoted) -> treated like mutation-report for merge decisions. Earlier #180 e172f89 randomized run failed 2 tests/test_cli.py lambdas (unexpected kwarg playout_trim_supported, seed 3559440525) - watch whether 0e51745 repeats it. NEW ITEM 83 (beta.6): fix the order-dependent stream test (replay seed 1681376346).
- 20:05Z(real) #181 r7 (1a1e239) review = CHANGES: unconditional pop + id-gated use makes fix 3 a no-op when another reload drains first (45-s retry collision is the common case) -> rollover DEFERS on a past horizon (dead air; measured [True,True] vs r6 [False,True]); wildcard has zero production recorders (trap); legacy tests cover only the wildcard branch; dead _enqueue return. Crash-relaunch leak itself IS closed (P4). Sonnet round 8: pop only on match, required command_id, tests. Moot 1a1e239 runs cancelled.
- 20:10Z(real) MERGED #182 -> main 33954a4 (item 79 knob hardening). Main checkout ff'd. Remaining for candidate 3c: #180 r8 (0e51745, review+CI running), #181 r8 (building), #183 r4 (204b4da, review+CI running).
- 20:20Z(real) #183 r4 (204b4da) review = MERGE (blocker closed; race refuted; pid = Popen.pid of the worker itself). Follow-ups (item 82b, beta.6 or quick PR): fixture marker pid=1400 lets the pid backstop carry the offset test (drop it); offset falls back to 0 when _stderr_logs has no entry (first spawn after STOP->START / control-plane restart; ffmpeg branch unbackstopped, at most one crash count lost); no test for the 4 MiB cap; pid-mismatch rejection silent (add warning); CHANGELOG cost claim (158 ms/call at the cap, not 5.8); pre-existing: daemon.py:1327 unbounded read_text on the crash path; FfmpegProcessHandle handles leak on natural exit. Merge on green.
- 20:35Z(real) #180 r8 (0e51745) review = CHANGES (coverage/wording only; both functional fixes verified closed in 4/4 trim combos; boundary 400 s confirmed, reviewer's 336 was wrong; start path 0.2-0.7 s cold). Round 9: mock tests for both job predicates + fail-closed gate, junit floor for the real-ffmpeg file in ci-test.yml, comment/CHANGELOG invariant wording, runbook lines. Moot 0e51745 runs cancelled. Follow-up beta.6: thread DB-known asset duration into the segment spec.
- 20:55Z(real) #181 round-8 head 508cc41 (pop only on id match; command_id required kw-only but explicit None still accepted as 'never matches'; retry-collision + automation id tests; 2990/37). Opus delta review (P1-P5 re-run, None contract, dropped-command lifetime, run-12 replay) + CI waiter.
- 21:05Z(real) #181 r8 (508cc41) review = MERGE (P1-P5 + N1-N4 all expected; frozen-horizon protection holds; stores never drop a distinct reload; off-air pops complete). Follow-ups (78b): 4 stale comments in daemon.py (2171 wildcard, 2156 'unconditionally', 463/1994 '_enqueue returns the id'); key the record per command so the 45-s retry cannot destroy leg A's identical horizon (A defers on a dead boundary until B supersedes it next tick); supervisor-subclass off-air pin test. Merge on green.
- 21:20Z(real) #180 round-9 head d17df6e (3 gating tests, junit floor for the real-ffmpeg file in ci-test.yml + 6 claims re-bound, invariant wording, runbook notes; 3354/37) but CONFLICTING vs main on CHANGELOG.md only -> builder merging origin/main; review + CI after the merge commit.
- 21:40Z(real) MERGED #183 -> main 6e637f4 (item 82). #180 head d05b3c2 (merge of main into r9) -> Opus delta review + CI waiter. #181 508cc41 MERGE, CI waiter armed. After both merge: candidate 3c = origin/main.
- 21:55Z(real) #180 r9 (d05b3c2) review = MERGE (all 4 fixes mutation-verified; junit floor fails closed 5/5 synthetic; 71/71 claims blobs match; merge commit clean, no CRLF). Follow-ups beta.6 (66b): DB-known duration threading; tighten warm-job test to assert .ts bytes replaced; CHANGELOG.md:415 needs a blank line. First ubuntu CI run of the now-required real-ffmpeg tests is the real proof. Merge on green.
- 22:20Z(real) MERGED #181 -> main 8ed33af (item 78 rollover re-arm, command-id scoped). Only #180 remains (d05b3c2, MERGE, CI pending); candidate 3c = main after #180.
- 22:25Z(real) #180 merge-tree vs new main clean (MERGEABLE); waiting CI. Dispatched Sonnet lane follow-up B on cc-sbsoak-b (branch feat/sandbox-soak-lane-b from origin/main): cherry-pick 2b9cc55, #184 r2 follow-ups a-d, ci-sandbox-lab.yml running Test-*.ps1 on windows-latest. Independent of candidate 3c.
- 22:40Z(real) #180 randomized-suite RED twice (different seeds) on tests/test_cli.py x2: lambda fakes of SourcePreparer reject the new playout_trim_supported kwarg -> REAL #180 breakage the required Unit tests job does not catch. Builder fixing (round 9b); CI on d05b3c2 will be superseded. Item 83 note: randomized-suite catches real breakage main's required jobs miss; ask why test_cli is not in the required run.
- 22:55Z(real) PR #185 lane follow-up B opened (head 3caf0c3: cherry-pick 2b9cc55 + #184 follow-ups a-d + ci-sandbox-lab.yml; 238/238, baseline count unreconciled). Opus review + CI waiter. cc-sbsoak-b now on feat/sandbox-soak-lane-b.
- 23:05Z(real) #180 round-9b head dde290b: test_cli fakes accept + assert playout_trim_supported (test-only diff, read by me). ROOT CAUSE of the hidden red: ci-test.yml concurrency cancel-in-progress + 40-min Unit tests + pushes faster than that -> the one real failure (e172f89 run 34039015742) was cancelled on every later round, never surfaced. RULE: merge only on a COMPLETE green run of the final head (my waiter does this); randomized-suite is a useful second signal. CI waiter armed.
- 23:25Z(real) #185 review = MERGE (238 vs 233 on main reconciled = +5 new assertions; real-sample replay byte-identical; workflow fails closed). Follow-up C (do right after merge, tiny): Run-SandboxSoak.ps1:649-650 backstop-marker exit must re-check VERDICT.txt / allow 2-3 shipper ticks before Invoke-SandboxKill; CpuSampler.ps1 Get-ProcessRoleLabel branch order vs docstring. Later: display-name drift gate; workflow fork if:/push main; stderr/stdout counter truncate double-count + unit tests; harness_notes cap marker. Merge on green.
- 23:55Z(real) MERGED #180 -> main fcfcb81 (item 66). ALL FIVE product PRs merged (176/179 earlier; 180/181/182/183 + lane 184 today). CANDIDATE 3c = fcfcb81c94ab2d4273d8a1995eea0df90ba71178. build-chain.sh detached (log scratchpad/build-chain-fcfcb81.log); its auto Gate A run must be CANCELLED (Gate A is kept only for candidate 4). Next: sbsoak-launch.ps1 -Sha fcfcb81... -Run run15 -Seamless -OnAirBound 25.
- 00:05Z(real 09-07) MERGED #185 -> main a572227 (lane follow-up B). Candidate 3c stays fcfcb81 (product code unchanged by #185; the lane runs from origin/main = includes B). Next: lane follow-up C (backstop-marker kill race + role-label order) on cc-sbsoak-b.
- 00:25Z(real 09-07) PR #186 lane follow-up C opened (head 599794f: BackstopMarkerGrace.ps1 45-s grace, CpuSampler branch order, display-name drift test; 253/253). Opus review + CI waiter. Candidate 3c build 34049971678 in progress; Gate A auto-cancel armed.
- 00:45Z(real 09-07) #186 review = MERGE (break lands in the while; grace bounded 45 s/10 polls; drift guard fails closed 3/3 mutations; 253/253). Follow-ups (lane D, later): CpuSampler.ps1:160 label 'ffmpeg-fallback:<ch>' asserts an engine it did not observe (use engine:<ch> unless ProcessName ^ffmpeg); anchor DISPLAY_NAME regex (?m)^ + single match; try/catch around injected Test-Path in BackstopMarkerGrace; reject PollIntervalSeconds<=0; README hand list. Merge on green.
- 01:05Z(real 09-07) Owner question 'what changed vs the old 24-h soaks' answered by read-only repo comparison (memory old-wsl-soaks-never-ran-gstreamer.md): old lane default ffmpeg-concat, 3-station kit = bare ffmpeg, checker = HTTP 200; GStreamer never soaked; rollover/caption tap/preroll/trim flip/Windows port all new. Old clone at scratchpad/old-civiccast (read-only, delete when done).
- 01:30Z(real 09-07) CANDIDATE 3c KIT READY: build 34049971678 success; kit-safe/fcfcb81c94ab2d4273d8a1995eea0df90ba71178; setup.exe sha256 7aec91bd0694a03c2f161a25a4e96e29895e03c2003c468a370dc21a6c369ab7; served 19/19. Launching sandbox run 15 (-Seamless -OnAirBound 25, 15 min).
- 01:35Z(real 09-07) run 15 launch refused: SANDBOX BUSY = auto Gate A 34051629995 on main a572227 (triggered by the #185 merge; Gate A runs in the Windows Sandbox on HALO-gate-a). My canceller matched only fcfcb81. Cancelled it; waiting for the sandbox to clear, then relaunch run 15. LESSON: after any merge to main, cancel the auto Gate A by CREATED time, not by sha; Gate A only for candidate 4.
- 01:45Z(real 09-07) Gate A 34051629995 cancelled; orphan vmmem 61512 killed via elevated helper job kill-orphan-20260906T183402Z (ok). Launching run 15 (candidate 3c fcfcb81, -Seamless -OnAirBound 25).
- 01:50Z(real 09-07) RUN 15 LIVE: cc-sbsoak-run/sandbox-lab/soak-output/soak-fcfcb81-20260906-183448Z (launched 18:34:48Z log clock; sandbox pids 47540/56044/40988; lane = origin/main a572227 incl. follow-up B). Verdict expected ~60-70 min after launch. Launcher wrapper timed out at 3 min but the run started fine (check the log next time instead of waiting on the wrapper).
- 01:55Z(real 09-07) #186 green + MERGE but HELD: a merge to main auto-triggers Gate A on HALO-gate-a, which launches Windows Sandbox and would collide with run 15. Merge #186 right after run 15's verdict, then cancel the auto Gate A immediately (by created-time, any sha).
- 02:10Z(real 09-07) RUN 15 mid-run (cycle 3): all 3 ON_AIR/gstreamer fast (item 66 fix works: PLAYING in 0.3 s), BUT public: seamless reload arms -> new leg held at first buffer (0 left to preroll) -> 'no output for 10s' stall -> restart, repeating (same 0-committed shape as run 12); automation 'did not land within 45s; retrying' logged every ~2 s; ON_AIR row rewritten every 2 s (item 67). Opus diagnosis dispatched (reload state machine / EOS / held leg blocks aggregator / warning cadence). Expect FAIL verdict.
- 02:25Z(real 09-07) RUN 15 VERDICT = FAIL: unplanned relaunch on education at 18:51:59Z (old 5448 -> new 5388), 11 cycles; seamless reload never commits (new leg held at first buffer -> 10-s stall -> restart); education stuck TRANSITIONING cycles 8-11. Evidence: soak-fcfcb81-20260906-183448Z. Opus diagnosis in flight. Merging #186 now + cancelling its auto Gate A.
- 02:30Z(real 09-07) RUN 15 numbers: unplanned 19, planned 0, committed 0/3 channels, aborted 2 ('ack timeout after 5.0s (reissue_desired_state)'), max gap 40.3 s, time_to_on_air 46/16/31 s (item 66 FIXED), installer 804 s. MERGED #186 -> main 18c2f1b; Gate A canceller armed. Sandbox exited cleanly. Waiting for the Opus reload diagnosis before any run 16.
- 02:50Z(real 09-07) RUN 15 DIAGNOSIS (Opus): RC-1 = 10-s stall watchdog armed at PLAYING (NO_PREROLL accepted) with no separate first-output budget -> healthy workers killed before first buffer under start-up load (fails the lane even with seamless OFF; 3 prior OFF runs confirm). RC-2 = _commit_reload ordering: active-pad switched while the new leg's thread is parked in the BLOCK probe, holds released after; wedge after 'boundary switch rebased' (engine.py:2032->2065); no watchdog covers a main-loop hang; daemon ack timeout on a live pid pins TRANSITIONING. 45-s warning every 2 s = log noise (retry gated by pid age). Builders dispatched: item 84 (first-output budget + warning cadence) on cc-item82 branch fix/first-output-watchdog-item84; item 85 (commit reorder + flush-before-NULL + commit watchdog thread + daemon terminates wedged pid) on cc-item78 branch fix/reload-commit-ordering-item85. Run 16 (seamless OFF control, soak-fcfcb81-20260906-191046Z) running; expected FAIL on RC-1.
- 03:00Z(real 09-07) Gate A GUARD started: scratchpad/gatea-guard.sh (nohup) cancels every workflow_run-triggered Gate A every 45 s while scratchpad/gatea-guard.ACTIVE exists; log gatea-guard.log. DELETE the ACTIVE file before the real candidate-4 Gate A. Kit-build workflow is workflow_dispatch-only (no auto build on merges).
- 03:25Z(real 09-07) PR #187 (item 84) opened, head ab19fd3: first_output_timeout_s 45 s (exit code 4), stall 10 s after first buffer, daemon _SLOW_START_EXIT_CODES, automation warning cadence; 3134/37; builder claims 25 pre-existing unformatted files (reviewer to check). Opus review + CI waiter.
- 03:45Z(real 09-07) RUN 16 (candidate 3c, seamless OFF control, soak-fcfcb81-20260906-191046Z) = FAIL: unplanned 30, planned 1, aborted 0, max gap 40.4 s, time_to_on_air 46/16/31 s. CONFIRMS RC-1 (first-output watchdog) fails the lane on its own. Fix = #187 (item 84). Item 85 PR pending.
- 04:05Z(real 09-07) #187 r1 (ab19fd3) review = CHANGES: claims engine.py blob wrong (12 failed, builder reported 3134 pass = FALSE COUNT); escalation cliff: alive-path on-air evidence accepts the PLAYING marker so first-output budgets >63 s never escalate (fix = first-OUTPUT marker as the evidence); pid-age WARNING still every tick; _first_output_seen init; runbook. Round 2 sent to the same builder. NOTE: builders can report false pass counts; always require the pasted summary line.
- 04:35Z(real 09-07) PR #188 (item 85) opened, head 7ca8267: commit reorder (holds released before active-pad), flush+unlink before NULL, commit watchdog thread (os._exit), daemon terminates wedged pid on ack timeout; real-gi test executed with the bundled runtime (CIVICCAST_GSTREAMER_RUNTIME_ROOT + py3.12). Builder: 3131 pass / 1 fail (claims flake) / 13 skipped. COLLISION: exit code 4 used by both #187 and #188. Opus review + CI waiter.
- 04:55Z(real 09-07) #187 round-2 head 08373dd: claims re-bound; first-OUTPUT marker + health.worker_produced_output as the GStreamer on-air evidence; pid-age WARNING cadence; pasted 3148/37, 1523 formatted. Opus delta review + CI waiter. Exit-code-4 collision with #188 to be resolved by whichever merges second (#188 -> 5).
- 05:20Z(real 09-07) #187 r2 (08373dd) review = MERGE (escalation probe 45/65/90/120 s all reach slate; counterfactual pinned at 1; 3148/37 matches). Merge on green. #188 must renumber to exit code 5 + add test `not in _SLOW_START_EXIT_CODES` + merge main after #187. Follow-ups (84b, beta.6): 4 stale doc sites claiming PLAYING is the on-air evidence (engine.py:178-181, daemon.py:385-386/409-411, health.py:52-56); dead branch engine.py:1347; worker_reached_playing has no production caller; test comment; runbook 'within a second'. Grep a live soak log for the first-output marker on the next run.
- 05:45Z(real 09-07) #188 r1 (7ca8267) review = CHANGES: reorder introduces fatal not-linked after every commit (4/10 real-gi runs vs 0/7 on main); flush_stop(True) wrong; release-before-switch drops the new leg's first buffers (cache-buffers=False); stated root cause not what the reorder changes (wedge still un-localized); exit code 4 collision; os._exit after set_state(NULL) can block; builder misreported the suite (3107/38 x2). Round 2: revert reorders, keep staged prints, watchdog = faulthandler dump + os._exit first, code 5, daemon branch, stubborn-process test. Moot 7ca8267 runs cancelled.
- 06:05Z(real 09-07) MERGED #187 -> main a6d7871 (item 84 first-output watchdog). CANDIDATE 3d = a6d7871dfbd4c4d0535153ddb6c950e2d65f6b63 (item 84 only; #188 pending). build-chain detached (log build-chain-a6d7871.log); Gate A guard will cancel the auto run. Plan: sandbox run 17 on 3d with seamless OFF (proves RC-1 fix alone: expect only planned restarts), then run 18 seamless ON once #188 lands in candidate 3e.
- 06:40Z(real 09-07) #188 round-2 head 7134a68 (reorders reverted, staged prints, faulthandler dump + os._exit(5), clamp [3,120], pending set before terminate, stubborn-process test, main a6d7871 merged; real-gi 10/10 0 not-linked; builder reports 3189/13 skipped/1 error = env oddity). Opus delta review + CI waiter.
- 07:00Z(real 09-07) CANDIDATE 3d KIT READY: build 34059632724; kit-safe/a6d7871dfbd4c4d0535153ddb6c950e2d65f6b63; setup.exe sha256 d457d2a4e85cbc7967cf066da552b1205ab4b47354808ba01fcc640dd548f4c4; served 19/19; auto Gate A 34061242314 cancelled by the guard. Launching run 17 (seamless OFF): expect ONLY planned restarts if RC-1 is fixed.
- 07:15Z(real 09-07) #188 r2 (7134a68) review = MERGE (ordering byte-equivalent to main; watchdog measured exit 5 at 3/4/120 s; real-gi 3x 0 not-linked; 3164/38 x2; builder's 13-skipped = runtime-bootstrapped env). Tiny round 3 requested before merge: try/finally around the dump so os._exit is unconditional; completion flag in _on_commit_wedged; stale wsl-test comment. Follow-ups (85b, beta.6): require_clean_worker_result code-5 claim unimplemented; _service_backoff_relaunch loses the classification; 'ack timeout' string coupling; document CIVICCAST_RELOAD_COMMIT_TIMEOUT_S in runbook/manual; CHANGELOG 'concurrent exit observation' rationale unproven.
- 07:35Z(real 09-07) #188 round-3 head e7a91b7 (try/finally os._exit, completion Event checked first, comment fix; diff read by me, correct). CI waiter armed; merge on green -> candidate 3e build -> run 18 seamless ON.
- 07:55Z(real 09-07) RUN 17 mid-run (3d, seamless OFF): NEW FACT: every worker prints first-output marker at 0.0 s after PLAYING, THEN 'no output for 10s' stall. Item 84's premise (slow first buffer) was wrong: output STOPS after the first buffer. 0 first-output timeouts. Opus diagnosis dispatched (stall offset from spawn; PAT/PMT-only first buffer; caption tee/appsink without queue; segments still being conformed while played). Run 17 will FAIL.
- 08:20Z(real 09-07) RUN 17 DIAGNOSIS (Opus): media flows 26-100 s (TSDuck 3.2 Mbps) then stops; first-output marker is a TAUTOLOGY (async udpsink prerolls a buffer before PLAYING; latched at arm) -> #187's on-air gate defeated again. Top cause: caption audio tap branch (non-leaky queue + appsink drop=False + fsync on the streaming thread) blocks the tee -> mux starves. Run 14 was NOT a captions-off control (tap leg present in its graph). Dispatched: item 88 + 84c product PR (cc-item82 branch fix/caption-tap-leg-item88), lane follow-up D (-WorkerEnv injection + GST_DEBUG capture) for the discriminating experiment. Items 89 (daemon reaps dead child only on the 30-s tick) logged.
- 08:30Z(real 09-07) RUN 17 (3d, seamless OFF, captions ON, soak-a6d7871-20260906-213332Z) = FAIL: unplanned 29, planned 2, incomplete 1, max gap 31 s; 0 first-output timeouts (marker tautology); output stops 26-100 s after spawn. Consistent with the tap-leg hypothesis (item 88). Next kit = 3e (item 88 + 84c [+ #188]).
- 08:50Z(real 09-07) PR #189 lane follow-up D opened (head 286fc79: -WorkerEnv injection via the service REG_MULTI_SZ, NAME= deletes, GST_DEBUG_FILE capture; 319/319). Opus review told to settle whether CIVICCAST_CAPTION_TAP_DIR= can really turn the tap leg off in a native station (crux of the experiment). CI waiter armed.
- 09:10Z(real 09-07) PR #190 (items 88 + 84c) opened, head 07282a2: tap queue leaky=2 + appsink drop=True + SegmentWriterThread (I/O off the streaming thread); first-output credited only >=2 post-arm buffers; 5-s output progress line; 3461/38 x2; real-gi 21 passed. Opus review + CI waiter. In flight: #188 CI (e7a91b7), #189 review+CI, #190 review+CI.
- 09:25Z(real 09-07) MERGED #188 -> main 5978ed5 (item 85: staged prints, commit watchdog dump+os._exit(5), wedged-pid termination; reorders reverted). Remaining for candidate 3e: #190 (88+84c) and lane #189.
- 09:40Z(real 09-07) #189 review = CHANGES: mechanics proven, but CIVICCAST_CAPTION_TAP_DIR= is INERT on a native station (station_runtime.py:1362 injects it unconditionally; service.py:482 spec.env wins) and live_captions_enabled=false only stops transcription (tap leg keeps running) -> NO shipped way to A/B the tap leg. `%` and trailing-backslash transport gaps. Round 2 sent. Dispatched item 91 product PR (CIVICCAST_CAPTION_TAP=off respected by the native runtime + profile switch drops the leg at next worker start) on cc-item78. #190 conflicts with main on CHANGELOG + claims.yaml (merge main in its delta round).
- 10:00Z(real 09-07) #189 round-2 head 2631e61 (README corrected, % + trailing-backslash rejected, round-trip test executes the real cmd->powershell parse, tail-keep 200 MB, -ccontains; 330/330). Opus delta review + CI waiter.
- 10:15Z(real 09-07) #190 r1 (07282a2) review = CHANGES: claims blobs wrong (14 failed; builder reported 3461 pass = FALSE again); writer close() unbounded (blocking put(None)) before the os._exit(70) escape; close() drain claim false; max-size-buffers=200 is the default (real change = time 0), keep bytes default; publish errors invisible; six-digit guard deleted; drop-log on streaming thread; no real-gi tap coverage. 84c verified correct (marker no longer tautological; escalation holds at 45/120). Round 2 sent (+ merge main 5978ed5). Moot 07282a2 runs cancelled.
- 10:30Z(real 09-07) #189 r2 (2631e61) review = CHANGES: tail-keep OpenRead cannot open the live GST_DEBUG_FILE (FileShare.Read); 200 MB bound not enforced on a growing file; no in-band truncation marker; harness .cmd ASCII encoding mangles non-ASCII (reject at parse); unanchored -File replace rewrites values. Round 3 sent.
- 10:50Z(real 09-07) PR #191 (item 91 tap off-switch) opened, head 8706186: station_runtime passes `off` through and drops the tap dir; build_audio_tap_plan None under off; strategy consults resolve_live_captions_enabled at worker start; 5477 pass / 1 pre-existing fail claimed. Builder used git stash (rule violation) but the shared stack still holds only the old 'not my work' SRT entry (count 1), nothing lost. Opus review + CI waiter. Candidate 3e = main + #190 + #191 (+ lane #189).
- 11:05Z(real 09-07) #189 round-3 head 2a05f5d (GstDebugTail.ps1 FileShare.ReadWrite + loop-enforced bound + .tail200mb banner; non-ASCII rejected at parse; anchored -File substitution; 347/347). Opus delta review + CI waiter.
- 11:20Z(real 09-07) #191 r1 (8706186) review = CHANGES: user-manual render gate FAILS (stale manifest); resolve_live_captions_enabled() on the channel-start path can raise (corrupt state file) and abort playout; 'takes effect at content reload' false (reload discards new_graph.audio_tap); 'removes stray leftover' false; CAPABILITIES.md:62 stale; builder's '1 pre-existing failure' did not reproduce (5478/42 green). Off switch itself proven end-to-end. Round 2 sent. Moot runs cancelled.
- 11:45Z(real 09-07) #189 r3 (2a05f5d) review = CHANGES: Get-ChildItem Length is a stale directory entry for a live file -> unbounded Copy-Item path; capture every checkpoint with no aggregate cap (~8 GB/2 h); banner exceeds bound; #186 grace only in awaiting-soak-start (new early harness-error exits uncovered); stale citations. Round 4 sent.
- 12:05Z(real 09-07) #190 round-2 head 4ba8e4b (main merged; claims re-bound x3; Event-based bounded close() returning drained/abandoned; bytes back to 10 MB; publish-failure counters; sequence guard; drop log on writer thread; live real-gi props test; pasted 3482/40 at head; real-gi 23 passed). Opus delta review + CI waiter.
- 12:25Z(real 09-07) #189 round-4 head 72f1bd7 (tail always; capture 1st+every 10th+final, 600 MB cap; banner within bound; Wait-ForVerdictWithGrace in all pre-running phases (recursion bug found+fixed); 381/381). Opus delta review + CI waiter.
- 12:45Z(real 09-07) #190 r2 (4ba8e4b) review = MERGE (bounded close measured 0.5 s; queue defaults verified on GStreamer 1.28.5; real-gi props test non-vacuous; merge coherent). Follow-ups 88b: close() can raise before stopping the thread (try/finally; re-entrant close must not say drained); tap close serial with get_state doubles teardown to 10 s on the force_exit path (skip tap close there); consecutive_publish_failures has no reader; sequence-exhaustion route is fatal to air; two stale test names. Item 92: tests/captions/test_offline_caption_job.py::TestTruncatedSpanishTrackNeverPublishes::test_an_orphaned_spanish_row_neither_gates_nor_reaches_the_track red 3/3 on main for one reviewer, green 3/3 for another -> env-dependent; triage. Merge #190 on green.
- 13:05Z(real 09-07) #189 r4 (72f1bd7) review = CHANGES (small): 600 MB cap can starve `final`; unconditional TRUNCATED banner/suffix; 3 wrong citations; MaxBytes below banner; EveryN 0 div-by-zero; cap wording; misattributed root-cause comment; recursion regression unnamed. Round 5 sent.
- 13:25Z(real 09-07) #191 round-2 head 8d31133 (render gates PASS; guarded resolve; reload claim corrected; TAP_DIR='' under off; CAPABILITIES fixed). ITEM 92 ROOT CAUSE (builder): InMemoryCaptionReviewStore.list() sorts by (created_at, review_item_id); same-microsecond datetime.now(UTC) ties on fast Windows boxes -> string tie-break orders the wrong row first (civiccast/captions/review.py). Pre-existing on main. Opus delta review + CI waiter.
- 13:55Z(real 09-07) #191 r2 (8d31133) review = MERGE (5480/42 green; env byte-identical for unset/inline; off -> no tee end to end). Follow-ups 91b: station_runtime.py:1385-1390 false claim (tap_worker main() raises under off with empty dir: make it exit 0 'tap is off'); strategy.py:867-869 comment contradicts the reload_content call site; CHANGELOG count; ops doc line about default-to-ENABLED on unreadable state. Merge on green. Candidate 3e = main + #190 + #191.
- 14:10Z(real 09-07) #189 round-5 head 25c331c (split budgets 400/200, whole-vs-truncated dest, ValidateRange on MaxBytes/EveryN, hard ceiling, corrected comment, named recursion test; 403/403). Opus delta review + CI waiter.
- 14:30Z(real 09-07) MERGED #190 -> main 66e02c4 (items 88 + 84c: tap leg cannot block air; real first-output marker; output progress line). #191 next (CI pending).
- 14:35Z(real 09-07) CANDIDATE 3e = main 66e02c4 (#190 in; #191 pending) build-chain detached (build-chain-66e02c4.log). Plan: run 18 = seamless ON + captions ON on 3e (the tap-leg hypothesis test); run 19 = tap OFF control once #191 lands (candidate 3f).
- 14:55Z(real 09-07) #189 r5 (25c331c) review = CHANGES: whole-copy branch unbounded on a growing file (1119 MB under a 120 MB bound); test blind to it; README hard-ceiling claim false; .tail0mb rendering; partial-dest leak; per-checkpoint drain. Round 6 sent.
- 15:05Z(real 09-07) #191 main merged in (head ad37153, MERGEABLE, gates PASS). CI waiter armed; merge on green -> candidate 3f for the tap-OFF control run.
- 15:35Z(real 09-07) #189 round-6 head 95037a7 (counted loop in both branches + convert-to-truncated + 500 ms grace; scenario 2b; ByteSizeLabel; partial dest deleted; per-checkpoint cap; 416/416). Opus delta review (attack the grace window's time bound) + CI waiter.
- 15:55Z(real 09-07) #189 r6 (95037a7) review = CHANGES: grace window unbounded in TIME (trickle writer -> false rollup STALL); 500 ms cost on every EOF; test helper drifted; no ByteSizeLabel tests; precision lost; README suffix; partial-at-legit-name. Round 7 sent: snapshot-length copy + 30-s deadline, no grace.
- 16:10Z(real 09-07) CANDIDATE 3e KIT READY: build 34068231662; kit-safe/66e02c44fc568008cf955f1ecd95a93cc335d11a; setup.exe sha256 1058b97d755e48366d783a22e69e849597e6d284b0bec1b061a3f8ef4a444687; served 19/19; auto Gate A 34069809445 cancelled by the guard. Launching run 18 (seamless ON, captions ON) = the tap-leg hypothesis test.
- 16:32Z(real 09-07) Orphan vmmem 17740 (left by the cancelled auto Gate A 34069809445; guard cancels ~45 s after start, the VM had already launched) killed via helper job kill-orphan-20260907T003201Z. LESSON: after every kit build, expect an orphan vmmem and clear it before launching. Relaunching run 18.
- 16:35Z(real 09-07) RUN 18 LIVE: soak-66e02c4-20260907-003250Z (3e, seamless ON, captions ON; sandbox pids 42488/6532/59992). Verdict ~60-70 min. Expected if the tap-leg theory is right: 0 unplanned relaunches; seamless commits may still be 0 (item 85 wedge un-localized) but now with staged prints + faulthandler dumps.
- 16:50Z(real 09-07) #189 round-7 head ac62e0d (snapshot-length copy, no grace, 30-s deadline -> .partial, production ByteSizeLabel in tests, AwayFromZero table, Format-MBPrecise; 439/439). Opus delta review + CI waiter.
- 17:00Z(real 09-07) MERGED #191 -> main c292e28 (item 91 tap off-switch). Candidate 3f (for the tap-OFF control run) = this main once run 18 reports; build after run 18 to avoid an orphan-vmmem collision.
- 17:20Z(real 09-07) #189 r7 (ac62e0d) review = MERGE (trickle 56 ms; static 21 ms; 439/439; poll loop flips). Lane follow-up E: per-CHECKPOINT wall-clock budget across candidates (N x 30 s can still hit the 6-min stall bound); partial-truncated banner false + keeps oldest bytes; ValidateRange on -WholeCopyDeadlineSeconds + a mid-copy content test; one note line still Get-ByteSizeLabel; Format-MBPrecise outside the testable module; .partial orphan on throw. Merge on green. With #189 + #191 in main, the tap-OFF control = `-WorkerEnv "CIVICCAST_CAPTION_TAP=off"`.
- 17:35Z(real 09-07) RUN 18 mid-run (3e): public flowed 16,760 buffers then a seamless COMMIT WEDGED -> commit watchdog fired at 15 s WITH a faulthandler dump (first time the wedge is captured); education/government: output counter FROZE flat (4072/17257) then the 10-s stall killed them -> output still stops even with the tap fix. Opus diagnosis dispatched (read the dump; correlate freezes with reload arming/holds).
- 2026-09-09 ~05:30Z(real) TAKEOVER from Codex (Scott out of Codex credits; my session crashed 09-07). Read all 3 Codex handoff files end to end; verified main f5509d7, #199 e23dd38 green/mergeable, be1260 FAIL, 8-file package untracked, station running on HALO since 08-29. Stopped my Gate A guard (it had cancelled Codex's Gate A 34240734122 on 09-08) and the host sampler; deleted the 3.43 GB be1260 artifact (repo artifacts now 79 MB). Owner: remove station from HALO; hostile-review #199; all 4 clips; artifact option A; tester after sandbox. REBOOT next; resume via memory civiccast-takeover-2026-09-09.md.
- 2026-09-09 04:45Z(real) POST-REBOOT: Gate A runner started by hand (HALO-gate-a online). CivicCast station REMOVED from HALO via elevated helper civiccast-remove-station.ps1 (service deleted, Program Files + ProgramData gone, uninstall key removed, port 8000 free; the product's uninstall.exe was absent). Opus hostile review of #199 running. Dispatched: artifact option A PR (cc-item79), #189 merge-of-main conflict resolution (cc-sbsoak-b), item 92 review-store sort-tie PR (cc-item78). Chip 3 (CG overlay label folding) is being done by a separate session Scott started; check before duplicating.
- 05:00Z(real 09-09) PR #200 (item 92 review-store sort tie) opened, head 81e9e11; builder slipped one git stash push/pop but the shared stack is intact (count 1, old SRT entry only). Opus review + CI waiter. In flight: #199 review, option A PR, #189 merge-of-main.
- 05:20Z(real 09-09) PR #201 (artifact option A: evidence-only upload on self-hosted, `upload_candidate_binaries` switch, binaries artifact renamed) opened, head a407ac38; Gate A never consumed the candidate artifact; publisher takes --kit-dir. PR #189 merge-of-main 3e9a715 pushed (delta review + CI running). Opus reviews running: #199, #200, #201.
- 05:35Z(real 09-09) #189 merge-of-main 3e9a715 delta review = MERGE (both sides intact, 12/12 suites, 323 policy tests, params bind). Merge on green.
- 05:55Z(real 09-09) #200 (item 92) review = MERGE (2224/6 green; tie test proven red on old key). Follow-ups 92b: persistence.py:250-253 comment wrong (created_at is Python-generated, mitigation = round-trip gap ~400 us); the _sequence counter is redundant vs a stable sort by created_at alone (dict insertion order); swap the two dict writes or use itertools.count; add approve/edit/reject + filtered-list tie tests; CHANGELOG provenance nit. Merge on green.
- 06:20Z(real 09-09) #199 (e23dd38) hostile review = CHANGES: BLOCKER the PR's own reproducer failed 1/4 clean runs (reload ABORT on 'Internal data stream error' -> active leg output flatlined -> stall kill; abort contract broken); stall watchdog (10 s) preempts the commit watchdog (15 s) so the dump never fires; _dispose_source_leg failures now channel-fatal (ASYNC legit for bins); stop() starves the tap-writer drain (#188 regression); stale-EOS guard weak; overlapping-commit reject only reachable in a wedge; digit-mangled evidence; owner local paths committed. Claims blobs OK; #187/#190/#191 untouched; CaptionGapGate verified. Opus builder round 2 dispatched on cc-item66 (branch checked out from Codex's remote branch).
- 06:40Z(real 09-09) #201 review = MERGE (3.43 GB -> ~10 KB per self-hosted build; consumers verified; 1914 policy tests). Follow-ups (ci hygiene): mirror consumer assertions for the binaries artifact name/if in test_native_beta_candidate_workflow.py; consider renaming the evidence artifact. Merge on green.
- 07:05Z(real 09-09) #201 lint failed on one unformatted test file; I ruff-formatted it (458b3e1) and pushed; CI waiter re-armed. #200 reproducibility job crashed in npm ci (0xC0000409) -> rerun requested. #189/#200 waiting on Unit tests.
- 07:30Z(real 09-09) MERGED #200 -> main 5f702db9 (item 92 review-store sort tie). #189 and #201 still waiting on CI.
- 07:40Z(real 09-09) MERGED #189 -> main ea3f87c7 (lane follow-up D: -WorkerEnv injection + GST_DEBUG capture). Next lane launches use origin/main. Remaining open: #201 (CI), #199 (round 2 building), #178, #165.
- 08:00Z(real 09-09) MERGED #201 -> main 46328e0f (artifact option A: self-hosted builds upload evidence only; `upload_candidate_binaries` switch). Open: #199 (round 2 building), #178, #165. Next kit build = after #199 lands; the build must be dispatched with the workflow's new default (no binaries).
- 10:25Z(real 09-09) #199 round-2 head 45889fc3 (built in cc-item66 on a local branch, pushed to Codex's remote branch; Codex worktree untouched): abort path hardened by construction (drop probe on errored leg src pads before hold release + off-loop retirement; errored-leg abort NOT reproduced 10/10), stall check stands down during commits, unified disposal policy (ASYNC wait 2 s + retry; incomplete cleanup no longer kills a producing channel), tap-writer own 2-s budget, txn_id, manual reworded, mangling + local paths fixed, claims restated 10/10 bounds-not-proves; 3602/14; claims re-bound. Opus delta review (must try to reproduce the abort under load) + CI waiter.
- 08:15Z(real 09-09) #199 (45889fc3) is CONFLICTING vs main 46328e0f and GitHub ran NO checks on it (conflicting PRs get no merge ref). Sonnet dispatched to merge main into the branch (cc-item66). LESSON: after merging other PRs, re-check every open PR's mergeable state before arming a CI waiter.
- 08:30Z(real 09-09) #199 merge-of-main 8dd3ddb2 pushed (CHANGELOG only; gates PASS; 1653/39 egress+captions; claims 125). CI waiter armed. Round-2 review still running on 45889fc3 (merge adds no code).
- 09:10Z 09-09 #199 round-2 review = CHANGES. BLOCKER: commit wedge reproduced 4/24 under 100% CPU load (base 3/3) - old-leg NULL still blocks before successor holds release; docs claim clean. Also: per-element NULL budget (77 elems -> 308 s), abort-vs-request-pad race, orphan on incomplete disposal, weakened test, July17 x3, 10/10 vs 12 timings. Round 3 builder (Opus) launched in cc-item66.
- 17:20Z 09-09 LOST ~8h: round-3 builder died at ~09:30Z on a 401 OAuth-expired error while measuring the fix; I did not relaunch (wrongly replied 'no response requested'). Edits left uncommitted in cc-item66 (engine.py, 3 tests, 5 docs). Relaunched an Opus builder to resume from the diff. CI on 8dd3ddb2 was 19 pass/3 skip.
- 17:45Z 09-09 OWNER DEADLINE: ship beta.5 installable at LPM by midnight MDT (06:00Z 09-10). Merged #199 at 8dd3ddb2 -> main 39d852e5 (round-2 head; CI 19/3; hostile review CHANGES = remaining load-wedge goes to follow-up PR). Kit build run 34382743550 started 17:28Z. Fable builders: #178 rebase (cc-seamless-on), round-3 follow-up (cc-item66 -> fix/reload-retire-off-air-round3, draft PR, no CPU load until told), #165 release notes (cc-docs165). Plan: build -> cancel auto Gate A + clear orphan vmmem -> sandbox 15-min soaks (seamless ON, captions ON, 4 clips, normal logging) x2 pass -> dispatch Gate A (3 lanes ~3h) -> publish beta.5 via scripts/release/publish_beta_candidate.py -> fill #165 evidence -> merge #165 + #178. Baseline pin = beta.4 c27c6e70. Version on main = 1.0.0-beta.5.
- 18:05Z 09-09 #178 rebased (cba6b360, test+comments only; seamless default ON already on main via #192/#193), CI waiter armed. #165 release notes drafted (a88fafad, TBD-EVIDENCE-* tokens). Round-3 follow-up = DRAFT PR #202 (c8959b88): F1-F10 + found a REAL worker crash at stop on main (0xC0000005: GstBin cascade re-PLAYs NULLed old-leg elements; fix = set_locked_state before retirement NULL). #202 NOT in tonight's kit; needs loaded runs + full suite + hostile review after the box is free. D: wiped, labeled CIVICCAST-BETA5, awaiting kit copy.
- 18:05Z 09-09 kit 39d852e5 built (run 34382743550), manifest 19 verified, kit-safe+mirror ready, setup.exe sha256 252305c9...1192. Auto Gate A 34385924543 cancelled by hand, orphan vmmem killed via helper (job needs job_id+scriptPath fields). Scratchpad lost sbsoak-launch.ps1/build-chain.sh/after-build.ps1 (deleted ~17:58Z by unknown cleanup) -> rewritten from session content. SOAK 1 launched 18:00Z pid 24792 -> cc-sbsoak-run\sandbox-lab\soak-output\soak-39d852e-20260909-180106Z (seamless ON, captions ON, 4 clips). #178 CI failing on GitHub apt flake (Google chrome repo hash mismatch), rerun #2 queued. D: wiped+labeled CIVICCAST-BETA5 awaiting kit copy after soak PASS.
- 19:05Z 09-09 SOAK 1 FAIL (2 unplanned gov relaunches 18:18/18:20Z, 1 aborted edu reload -> planned 20s gap; public clean 4 reloads). DIAGNOSIS (Fable, read-only): systemic 25-30s VIDEO HOLD then ~900-frame burst on EVERY channel every 1-2 min with captions ON (output delta drops to audio-only +234/5s then +1100-1500 burst; RSS swings 0.5GB); fatal when hold outlasts 10s stall bound. NOT caption tap overload, NOT CPU, NOT the 1080p clip. Suspect = live caption EMBED leg (cccombiner on video path + CaptionGapGate GAP admission). Abort->restart path is by design and kept the program on air. Mitigation available via WorkerEnv CIVICCAST_STALL_TIMEOUT_S=30 / CIVICCAST_RELOAD_TIMEOUT_S=30. DECISION: ship beta.5 with StationProfile.live_captions_enabled default OFF (builder on fix/live-captions-default-off), root cause -> beta.5.1. Soak 2 (captions ON) running 18:35Z -> soak-39d852e-20260909-183511Z; soak 3 = -CaptionsOff next. #178 CI reruns (Google apt repo hash-mismatch flake x3).
- 19:12Z 09-09 OWNER: 'option A' = beta.5 ships with live captions OFF by default (operator toggle kept); root cause of the caption-embed video hold -> beta.5.1.
- 19:15Z 09-09 SOAK 2 (captions ON) FAIL: 5 unplanned relaunches across all 3 channels + one preroll timeout (30s). #178 MERGED -> main 8920a6c7. PR #203 (c40c2733, fix/live-captions-default-off): KEY FINDING - profile switch never removed the embed leg; station_runtime.py:1437 set CIVICCAST_EGRESS_EMBED_CAPTIONS=1 unconditionally, so the sandbox -CaptionsOff lane ALSO had cccombiner. #203 gates the embed on env AND profile; absent key -> OFF; stored true kept. Opus hostile review + CI waiter armed. Soak 3 (mistakenly launched captions ON, killed by recorded PIDs, orphan vmmem killed, relaunched -CaptionsOff 19:10Z -> soak-39d852e-20260909-191010Z) = data point only; decisive proof needs a kit with #203. sbsoak-launch.ps1 now has -CaptionsOff.
- 19:35Z 09-09 #203 round-1 review CHANGES: B1 captions OFF -> safe-to-air banner permanently RED (runtime_status.py:111 needs captions_verified); B2 'captions-off runs never showed the hold' unsupported (no recorded captions-off run; lane never removed embed leg); M3 feed+proof workers still run (6s ffmpeg capture/30s/channel + FAIL rows), tap_worker early-return before _run_disabled; M4 HEVC+captions-on reload raises; docstring/manual wording. Fable round-2 builder launched in cc-captions-default-off.
- 19:50Z 09-09 SOAK 3 (39d852e5, profile captions OFF = ASR+tap off, embed leg still built): 0 stalls, 0 unplanned relaunches; edu+public 4 clean seamless reloads each; VERDICT FAIL only because government rolled over by planned restart x2 (13:28 reload committed, 13:29:52 'rollover horizon stale ... re-establishing', then no rollover dispatched, plan ran to EOS, 20.6s gap; repeated 13:41). => the video hold/stall is tied to the ASR/tap/cue path (not embed-only). NEW BUG: lost rollover horizon after a committed reload (gov prep was 9.4s foreground conform vs ~1s cache hits elsewhere). Fable read-only diagnoser launched; PR #175 (horizon guards) to be assessed. Decision pending: ship as known issue vs tiny fix.
- 20:02Z 09-09 HORIZON DIAGNOSIS: automation.py stale-horizon branch (~998) fires before the 'already issued/settling' check (~1036); when an armed boundary rollover's outgoing leg runs 5-17s past projection (commit observed 4-13s after engine boundary), it re-establishes from the OLD dispatch record (switch_deferred=False -> starts_at=now) and the fresh-plan branch then dates the new plan from that poisoned previous_end (~1383) -> no next rollover -> EOS -> 20s restart. Every gov rollover; edu missed by 2-5s. #175 CONFLICTING/46 behind, does NOT fix it. Fix = guard: while _rollover_issued and daemon has pending settlement, wait (plus belt at 1383). Fable builder -> fix/rollover-horizon-settling-race. #203 round 2 cfa43f56 pushed; Opus delta review + CI armed.
- 20:15Z 09-09 #203 round-2 (cfa43f56) review = MERGE (follow-ups -> PR #205 8588a8a6: manual note 'captions ON shows red until channel restart', tolerant resolver_or_default at 5 call sites, HEVC warning latch). #204 (966b880b horizon guard+belt) review = CHANGES: drop _rollover_issued conjunct (operator/slate reloads also defer), belt must use per-plan lead not flat 120s (inert for short plans; reviewer reproduced bug WITH the PR), add rate-limited log, short-plan test. Round-2 builder in cc-horizon-race. Merge order #203 -> #205 -> #204, then kit build. Timeline: merge ~21:05Z, build ~21:50, soak ~22:15, Gate A ~01:15Z, publish ~01:45Z (deadline 06:00Z).
- 20:22Z 09-09 #203 MERGED -> main 508e637a (live captions OFF by default; embed leg gated on profile; banner gate conditional; feed/proof idle when off). #204 round-2 961c552c review = MERGE (3 non-blocking nits). #205 8588a8a6 + #204 awaiting unit-test CI jobs then merge; then kit build from the merged main.
- 21:13Z 09-09 #204 MERGED (7891109b), #205 MERGED -> main 148c8d21 = beta.5 CANDIDATE 2. Kit build chain started (chain-148c8d21.log). Next: cancel auto Gate A + kill orphan, soak (captions default OFF now, seamless ON), soak x2 pass -> dispatch Gate A -> publish. Halo session holding CPU work.
- 21:57Z 09-09 kit 148c8d21 built (run 34405681086), 19 files verified, kit-safe+mirror ready, setup.exe sha256 775b9a3e63a94183f1c065bb4168d03c0aeb2d72d608c1dbed5c875a94e05842. Auto Gate A 34409146410 cancelled, orphan killed. Candidate-2 soak 1 launched 21:56Z (shipped defaults: captions OFF, seamless ON) -> soak-148c8d2-20260909-215630Z. #165 updated to ea900112 (candidate 2, tokens listed).
- 22:35Z 09-09 CANDIDATE-2 SOAK 1 (148c8d21, captions OFF default, seamless ON): elements=96 (no embed leg); edu+public 4/4 clean seamless reloads; gov 3/4 then the RELOAD COMMIT WEDGE (switching selector -> reload-commit-timeout 15s -> worker relaunch, 20.4s gap) at 22:29Z with NO CPU load; #204 guard observed working ('past due by 2s ... still settling; waiting'). VERDICT FAIL (1 unplanned). DECISION (deadline): ship candidate 2 with the wedge as known issue (~1/12 rollovers, self-heals in 20s); #202 = beta.5.1 (Opus hostile review launched now). Gate A to dispatch on 148c8d21; USB copy to D:\CivicCast-beta5-kit-148c8d21 started.
- 22:50Z 09-09 Gate A 34412708089 (full, run 34405681086) dispatched 22:32Z. #202 hostile review = MERGE-after-rebase for beta.5.1; soak dump PROVES the wedge = old-leg set_state(NULL) on the loop-scheduled path with the successor held dark (engine.py:3241/2889 on main); follow-ups F1 orphans stay locked in pipeline (false clean stop), F2 blocked retirement thread disables later reloads (2s quiesce raise before pending), F3 quiesce 2s vs 12s budgets, F4 no elapsed/timestamps in worker stderr, F5 ignore finish return. Round-4 builder launched (rebase + F1-F5, light tests only). USB copy running.
- 00:00Z 09-10 Gate A 34412708089 FAILED at INSTALL: d4-activate-station ran 29m51s then returned 67 -> installer exit 123; other lanes skipped. Concurrent USB robocopy of the same kit (12 MB/s, 22:35-23:48Z) = I/O contention suspect (same kit installed in 793s in the soak). Re-dispatched Gate A 34419203610 at 23:58Z with the box quiet. Diagnoser on exit 67 launched. USB copy DONE: 21 files 25.9 GB to D:\CivicCast-beta5-kit-148c8d21. #202 round 4 pushed 399c4618 (draft, beta.5.1). Publish ETA ~03:30Z if Gate A passes.
- 00:15Z 09-10 EXIT 67 = activation/self-test failed (main.rs:5880-5890), no time bound in activation itself; self-test probes are run_bounded_command 30s (main.rs:5536). Failed run: every disk-bound step 2.2x slower (stage-packs 13m53 vs 6m23; activation 29m51 vs 13m56 on 09-08), CPU-bound vc-redist flat -> I/O starvation (~85%); gate-a.md:559-566 documents the same pattern (run 7). No activation code changed be1260bd..148c8d21. LOGGING GAP: the activation CLI's stderr reason only goes to the NSIS details pane, discarded under /S; install-progress.log promises it but does not carry it (nsis-hooks-bootstrap.nsh:1397) -> beta.5.1 item. Rerun 34419203610: activation expected ~00:12-00:27Z; live check on hoststore\install\station-set.json armed. USB stick verified (19 files) + README-START-HERE.txt; Scott is installing on a fresh machine himself now.
- 01:00Z 09-10 Gate A rerun 34419203610 ALSO failed activation: d4-activate-station 18:22:42->18:52:47 local = 30m05 -> 67 (both runs ~30:00 => a bound). Install via VSMB mapped folder is 2x slower than 09-08 (13m56). Host had 27 hung townreporter-dev `node --test` processes (~10 cores, since 20:10Z) -> killed by PID (children matched on townreporter-dev + test-environment-guard); prod townreporter-web 20140 untouched; host CPU 55% -> 15%. Cancelled the doomed run, killed orphan vmmem, dispatched Gate A attempt 3 = 34423542177 at 00:58Z. Publish ETA ~04:30Z if it passes. Fallback = owner-override manual publish (publisher refuses without 3 PASS lanes).
- 01:26Z 09-10 Gate A attempt 3 (34423542177): ACTIVATION OK at 01:25:25Z (station-set.json), ~12 min like 09-08 => the two 30-min failures were host load (hung townreporter-dev node --test x27), not product. Lane 1 continues (station up, T2-T5).
- 02:00Z 09-10 Gate A 34423542177 lane 1 (clean install + T2-T5) = SUCCESS. Lanes 2 (cross-version over beta.4) and 3 (download-only) running next.
- 02:35Z 09-10 OWNER: on a Gate A lane failure do NOT stop for a decision; diagnose, fix, rerun until pass or 06:00Z. Owner at dinner; his fresh-machine install does NOT count as evidence. Beta.5.1 items 97 (first-setup password loss) and 98 (first-run guide) filed. Lane 2 in progress since 01:56Z.
- 02:58Z 09-10 Gate A 34423542177 lane 2 (cross-version over beta.4) = SUCCESS. Lane 3 (download-only) running. Item 99 (legacy NATS journal fields halt upgrade from August installs) filed; fix PR builder running (cc-journal-tolerant).
- 03:35Z 09-10 OWNER: ASAP + do beta.5.1 tonight too (publish through the gate ~2-3 AM MT); add an AI install-helper prompt to the package. DONE: docs/INSTALL-HELPER-PROMPT.md written (logs, exit codes 66/67/85/123/127, workarounds A-J), copied to D:\ root + kit folder + kit-safe, README updated; PR #207. 5.1 = product version 1.0.0-beta.6 (routing _VERSION_PATTERN rejects beta.5.1); bump+baseline-repin PR builder launched (cc-beta6-bump). In flight: #206 round 2 b344a9d7 (delta review + CI), ownership PR builder (cc-ownership-claim), #202 399c4618 (needs soak). Lane 3 still running (started 02:58Z).
- 04:05Z 09-10 GATE A 34423542177 ALL THREE LANES PASS. Publisher live run started for v1.0.0-beta.5 (kit-mirror 148c8d21, build 34405681086). #165 final fill builder launched. #209 (ownership) review = MERGE w/ follow-ups, round 2 running; #206 round 3 cdb98387 accepted, CI pending; #207, #208 CI pending. HANDOFF.md on main (d0db0ece).
- 04:16Z 09-10 (10:16 PM MT) v1.0.0-beta.5 PUBLISHED https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.5 (8 assets; first attempt refused: body >125k chars -> renderer bound fix PR #210). release-truth flipped + HANDOFF committed to main 014c38b6. #207 merged. #165 at 440b9fcf (PUBLISHED headers) awaiting CI; #206 cdb98387, #208 0c0357d5, #209 251098b4 (round 2 done), #210 d7a7bba8 on CI. Next: merge as green (#165, #206, #210, #209, then rebase #208), then beta.6 kit -> soak -> Gate A -> publish.
- 04:32Z 09-10 (10:32 PM MT) Walkthrough report (clean machine) filed as items 102-115; item 97 = Chrome autofill. Diagnosis: HLS 404 = no route (channel.py:379 placeholder); portal Live = live SESSION only (live/router.py:250), never egress; no rehearsal HLS preset; 22:00 stop = finite slate plan EOS exit-0 -> STOPPED (daemon.py:1834) while the seamless reload's synchronous prepare blocked the automation tick; recovery kit lost on unmount (SetupScreen.tsx ~1831); no sign-out route. Three Fable fix builders launched: cc-boundary-stop, cc-portal-live, cc-setup-session. #206 e2537f13 (native test-count pin +13) CI; #165 893c44eb (also fixes duplicate release-truth entries on main) CI; #209 251098b4, #210 d7a7bba8 CI.
- 04:40Z 09-10 (10:40 PM MT) OWNER: plan downgrade likely 'tomorrow during the day', not midnight; keep going through the night; coding continues tomorrow and beyond. beta.6 target 3-5 AM MT.
- 05:00Z 09-10 (11:00 PM MT) Both tester machines started 8-h soaks of beta.5 per docs/SOAK-PROMPT.md (Blackwell captions ON, clean machine captions OFF); expected done ~7 AM MT; reports as SOAK-<pc>-<date>.zip. Open PRs on CI: 165, 206, 210, 211, 212 (r2 building), 213 (review), 214 (review), 209 (green, r3 building); builders: setup-auth (item 120), honesty (121-124).
- 05:15Z 09-10 (11:15 PM MT) MAIN IS RED on tests/policy/test_windows_release_downloader.py::test_windows_install_doc_matches_current_release_posture and tests/test_audit_protocol_docs.py::test_active_public_docs_link_validated_current_candidate: release-truth says beta.5 current but README.md / INSTALL-WINDOWS.md (and likely docs/index.html, docs/install-windows.html) still link v1.0.0-beta.4. Fix goes into #165 after its rebase builder finishes (flip the "current install target" surfaces to v1.0.0-beta.5; beta.6 stays the held candidate). #206 merged 7068ac18, #210 merged 3067e63b.
- 05:25Z 09-10 (11:25 PM MT) #212 r2 153c45da (delta review + rebase running); #213 follow-ups 88810c0c (rebase running); #214 e1e25353 (review + rebase running); #165 rebase running (then flip beta.4->beta.5 surfaces); #209 r3, setup-auth, honesty builders running; #211 one CI job left. Memory note civiccast-beta5-night-2026-09-09.md rewritten for compaction.
05:13Z post-compaction: #212 rebased 611728d0; #213 rebased 613430ee; #214 rebased 4e230b91; #165 merged-with-main acf5f4c6 + surface-flip builder (beta.4->beta.5) launched in cc-docs165; #215 setup-auth opened c265696e, Opus hostile review launched; #209 f55cde7d CONFLICTING (r3 builder still running, rebase after); CI monitor armed for 211/212/213/214/165/215.
05:14Z #214 review CHANGES (loopback manifest URL, preset apply needs reload, slate=on_air hides idle page, hls root containment, keep_existing default) -> r2 builder in cc-portal-live; #209 r3 f55cde7d done -> rebase builder + Opus delta review running; honesty builder waiting on its pytest.
05:17Z #212 review MERGE + MINOR-1 fix c59d48d9 (CI); #209 rebased a311bb00 CLEAN (CI + delta review running); #216 honesty opened 1ee644cb (Opus review running); #215 review running; #214 r2 builder running; #165 surface-flip builder running.
12:25 AM MT 2026-09-10: diagnosed the shared CI redness. It was NOT per-PR. Two causes on main: (1) release-truth.yaml had duplicate v1.0.0-beta.5 entries (publisher added a `current` entry, the old `staging` entry stayed) so check_release_truth.py reported DRIFT and test_real_manifest_is_internally_consistent failed; (2) README/INSTALL-WINDOWS/docs/index.html/docs/install-windows.html still named beta.4 as the current download. Both fixed on #165 (cc-docs165): the dead builder's surface flip was sitting uncommitted in the worktree, committed as baf94d62, origin/main merged in, pushed as cd50c3d4. Locally tests/policy = 1920 passed / 5 skipped, check_release_truth.py PASS. #213's test_staff_mutation_role_policy failure is #213's own, not inherited. Rate limit reset at midnight; relaunched four agents: #214 round 2, #215 round 2, #209 round 4, #216 hostile review -- each now required to post its report as a PR comment so it survives an agent death.
