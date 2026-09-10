# HANDOFF

## 2026-09-10 local F-1 implementation update

Scott authorized GO following the cold takeover. Active branch:
`fix/f1-reload-readiness-20260910`, base `d77b634e3685de8fb077956b8099fc92c3927243`.
Local worktree:
`C:\Users\scott\Documents\Codex\2026-09-10\openai-multi-agent-c-users-scott\work\f1-integration`.
No PR, push, merge, tag, publication, station service start, Gate A, or sandbox soak
has been performed for this work. See `docs/evidence/f1-local-2026-09-10/VERIFICATION.md`
for the current implementation/review evidence and remaining release gates.

F-1 changes bind preroll callbacks to their reload, require every replacement
stream before retirement, and recover unexpected clean worker exits while honoring
Stop/Drain. F-4 exit and fire logging is included. F-2 remains unstarted. The
existing `795cdab5` beta.6 kit is unchanged and still must not be published.

Older task lists below are historical; they do not authorize starting old work
or publishing the existing kit. The current owner per-action authority governs.

> **2026-09-10 11:10 AM — READ `PROJECT-STATUS.md` FIRST.** It is tracked in git (this file is
> gitignored) and it is the full cold-start handoff: where the project is, both overnight soak
> results with independent verification, the blocker that stops beta.6 shipping, every fix with its
> definition of done, the test gates, and the location of every file on this machine and on GitHub.
> **The built beta.6 kit must not be published** — the 2026-09-09 soaks found a blocker it does not
> fix.


Any session, on any plan or tool, continues from this file. Times below are Mountain (America/Denver).
Rules in force: no new features; finish and test what exists; commit after each task; update this file after each task; stop at a clean state.

## Task list, most important first

1. DONE 10:14 PM: **v1.0.0-beta.5 PUBLISHED** https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.5 (8 assets, prerelease, target 148c8d21; Gate A 34423542177 all three lanes PASS). First attempt was refused (body > 125,000 chars, HTTP 422); the renderer fix is PR #210. release-truth.yaml flipped by the publisher and committed. Command used:
   `python scripts/release/publish_beta_candidate.py --kit-dir C:\CivicCastTester\kit-mirror\148c8d2172dd6b63cbbb856b429b68aa020dc421 --source-sha 148c8d2172dd6b63cbbb856b429b68aa020dc421 --build-run-id 34405681086 --gate-a-run-id 34423542177 --tag v1.0.0-beta.5 --truth-status current`
   The dry run already passed layout, version and Authenticode. The publisher updates docs/releases/release-truth.yaml; commit that.
2. DONE 12:53 AM: **PR #165 merged** (main 76817e3d) -- release notes + the beta.4->beta.5 surface flip + the release-truth dedupe. Main is green.
2b. old note: (branch docs/release-beta5, worktree cc-docs165): all tokens filled, headers PUBLISHED, known issues 99/100 added, duplicate release-truth entry fixed. Being rebased onto main after #206/#210; merge on green.
3. DONE 11:06 PM: PR #206 merged (journal tolerant of legacy NATS keys; item 99).
4. DONE 10:14 PM: PR #207 (docs/INSTALL-HELPER-PROMPT.md) merged.
5. **Ownership-check fix = PR #209** (round 4 running 12:25 AM: the NSIS dialog budget really is blown -- static text measures 580/579 chars, so the 420 cap yields 1029/1028 against `assert total < 1023`; max safe cap 413. Also OWNERSHIP-RECOVERY.md says exit 127 where the code is 135, and the PresentInert rule can misfire when the owner hive is not loaded.)
5b. old note: (branch fix/runtime-ownership-claim-diagnosable, worktree cc-ownership-claim, head d6d5ea2f): hostile review said MERGE with follow-ups; round 2 in progress (5 s bound on `sc query`, dialog wording on upgrades, const assert, skip-predicate pin). Merge on green after round 2. Item 101 (forward the provisioning CLI's stderr into install-progress.log) is NOT in this PR: it needs a file handoff like ownership-observation.txt plus a policy test that no stderr line can carry the database URL; do it as its own PR later.
6. DONE 10:20 PM: PR #208 merged (main a2ccfc98): product version is now 1.0.0-beta.6; Gate A baseline repinned to the beta.5 kit.
7. **PR #202** (reload wedge off-air retirement, crash at stop; head 399c4618, draft, rebased on 148c8d21): needs a sandbox soak proving on every rollover that `stage=holds-released` precedes `stage=old-leg-disposed`, zero `reload-commit-timeout`, then 20+ loaded runs at 100% CPU (only when the box is otherwise idle), then a delta review, then merge.
7b. **PR #212** (slate boundary relaunch instead of STOPPED; branch fix/slate-boundary-relaunch-not-stopped, worktree cc-boundary-stop): round 2 of the hostile review landed (consecutive-relaunch counter, crash-latch/streak honoured, queued stop wins, `peek_pending_commands`, label to TRANSITIONING, "Preparing source" row). Sandbox soak brief: commit a program 2-3 min after a slate start so the slate's finite plan ends at the boundary, then GRADE THE BOUNDARY FROM `control_plane-app.log` (the `_write_state` STARTING -> TRANSITIONING -> ON_AIR lines with the program's label), not from the RestartClassifier ring alone -- the ring can miss the post-prepare TRANSITIONING sample (pre-existing gap) and would count the pid change as unplanned. Expect exactly one relaunch per boundary and zero `stopped instead of looping` last_errors; with a deliberately unplayable asset expect ONE relaunch then STOPPED with that last_error and no further worker every ~2 min.
8. **beta.6 kit**: after 3-7, build with `scratchpad\build-chain.sh <main sha>`, cancel the auto Gate A, kill the orphan sandbox VM via the elevated helper, soak 15 min (captions OFF default, seamless ON), dispatch Gate A full, publish `--tag v1.0.0-beta.6`. Never run anything I/O or CPU heavy during Gate A (two attempts failed tonight from host load).
9. **Captions root cause** (item 96): with live captions ON, video holds 25-30 s then bursts, every 1-2 min. Needs a `GST_DEBUG=cccombiner:6,aggregator:5` discriminator soak. Not before 1-8.

## Added 10:35 PM from the clean-machine walkthrough (tester report, beta.5)
Three fix PRs are being built in parallel; each gets a hostile review, then merges on green, then joins the beta.6 kit:
- cc-boundary-stop / fix/slate-boundary-relaunch-not-stopped: a finite slate plan reaching EOS relaunches onto the due program instead of STOPPED; STARTING written before prepare; Channels elapsed-time polling. (items 105, 110)
- cc-portal-live / fix/portal-live-follows-egress-and-hls-truth: resident /api/public/live/current follows egress when an hls sink exists; Channels shows the real HLS URL or says web output is off; local rehearsal HLS preset. (item 104)
- cc-setup-session / fix/first-setup-recovery-kit-signout-autofill: recovery kit survives navigation until confirmed; Sign out control + route; no browser autofill on first setup. (items 102, 103, 97)
Not started (beta.6 or later): 106 startup page, 107 state authority, 109 sample live source, 112-115 copy/mobile/docs. Full list: Desktop\floatsom\CIVICCAST-BATCH-FIX-LIST-2026-09-03.md items 102-135.

- DONE 11:08 PM: PR #210 merged (release-body bound under GitHub's 125k limit).

## Added 10:55 PM from the upgrade-machine walkthrough (Blackwell, 5070 Ti; items 120-135)
- PR #212 (slate boundary relaunch): review CHANGES (relaunch bypasses the crash-escalation latch; the 30 s cap can never fire because the slate plan is 120 s; STOP race; stale stamp). Round 2 in progress in cc-boundary-stop.
- cc-setup-auth / fix/setup-api-no-secrets-unauthenticated: CRITICAL item 120 -- /api/setup/storage served the PostgreSQL URL with password unauthenticated; setup endpoints require the staff token after setup. Builder running.
- cc-honesty / fix/publish-default-portal-and-channel-honesty: Publish defaults to Portal only (121); Channels drops fabricated sample rows (122); Start refuses without egress (123); readiness separates rehearsal result from the gate (124). Builder running.
- PR #209 round 3 (cc-ownership-claim): the real cause on the Blackwell box was a PRESENT per-user ARP entry for the WSL-era "CivicCast Installer 3.0.0-beta1" (inert), not an Unknown probe; adding a PresentInert -> claim-native rule with a warning and a product-naming refusal. Builder running.
- PR #211 also carries docs/SOAK-PROMPT.md (overnight soak brief for a station PC). Copies on the USB root and the owner's Desktop.
- Still open from that report: 125 Live screen has no controls / manual names a missing button; 126 CLI/env-var copy on operator screens; 127 scheduled premiere not visible to residents; 128 media under the SYSTEM profile vs docs saying ProgramData; 129 responsive tables; 130 sign-in UX (recovery confirm, username hint, code format, landing page); 131-135 minor.

## Done tonight (2026-09-09 to 09-10)
- Merged: #199 reload/caption-flow (39d852e5), #178 seamless default proof (8920a6c7), #203 live captions OFF by default (508e637a), #204 rollover horizon race (7891109b), #205 manual note + tolerant resolver (148c8d21).
- Kit 148c8d21 built (run 34405681086), verified, mirrored; installer sha256 775b9a3e63a94183f1c065bb4168d03c0aeb2d72d608c1dbed5c875a94e05842, Authenticode Valid.
- USB stick D: (CIVICCAST-BETA5) holds the verified kit, README-START-HERE.txt and INSTALL-HELPER-PROMPT.md.
- Sandbox soaks: candidate 1 (39d852e5) x3 FAIL led to #203/#204; candidate 2 soak: 0 stalls, 11/12 seamless rollovers, one reload-commit-timeout relaunch (20 s) = known issue.
- Gate A: attempts 34412708089 and 34419203610 failed at activation after ~30 min from host load; attempt 34423542177 lanes 1 and 2 PASS.
- Open PRs: #165 notes, #202 draft, #206, #207, #208.

## Not done
- MAIN IS GREEN AGAIN (12:53 AM). #165 MERGED as main 76817e3d. Two causes, both fixed there: (a) release-truth.yaml carried DUPLICATE v1.0.0-beta.5 entries (publisher `current` + leftover `staging`) so check_release_truth.py reported DRIFT; (b) README.md / INSTALL-WINDOWS.md / docs/index.html / docs/install-windows.html still named v1.0.0-beta.4 as the current download. Verified on main after the merge: `pytest tests/policy/test_release_truth.py tests/policy/test_windows_release_downloader.py tests/test_audit_protocol_docs.py -p no:randomly` = 29 passed. Every other PR had inherited this; they are all merged with main and re-pushed.
- CHANGELOG merge shape you WILL hit on every remaining branch: the branch carries a duplicate of #206's "beta.5.1: provisioning tolerates legacy journal fields" entry inside the released `## [1.0.0-beta.5]` -> `### Fixed` section, while main now has that entry once in `## [Unreleased]` -> `### Fixed`. Resolution: delete the duplicated #206 entry from the conflict block entirely, and move the branch's OWN entries into `## [Unreleased]` -> `### Fixed` after main's. Done that way for #212 (233e8e18) and #213 (c47b0c18).
- PROCESS LESSON (cost a false public claim): a subagent reporting `status: completed` is often NOT finished -- it stops while waiting on a background command and then resumes itself. I took over #214's and #215's worktrees on that signal; #215 had already made a real extra fix commit I had publicly dismissed as "test order pollution" and I had to post a correction on the PR. Check the agent's own last line before touching its worktree.
- Shared-state hazard: concurrent pytest runs in different worktrees all write `%LOCALAPPDATA%\CivicCast\installer-state.json` and the managed-storage sqlite, which produces phantom teardown ERRORs in whichever run loses. Re-run the named tests in isolation before believing them.
- **ALL SEVEN FIX PRs ARE MERGED. Main is 2d7fd65b.** In order: #211 74e3d7c5 (install-helper screen names + SOAK-PROMPT), #212 bc32dfa3 (a finite slate plan reaching EOS relaunches onto the due program instead of writing STOPPED; STARTING before prepare), #215 184398d9 (CRITICAL item 120 -- the setup API never serves the database credential, and POST /storage, /first-admin, /recovery-kit/acknowledge require `setup_admin` after setup), #213 24894218 (recovery kit survives navigation; Sign out; no autofill on first setup), #209 91ebe7c7 (the runtime-ownership claim runs first, gathers machine-wide evidence, records why it refused), #216 0cc34881 (Publish defaults to Portal only; Channels shows real state not sample rows; Start refuses without egress; readiness separates rehearsal from the gate), #214 2d7fd65b (resident live state follows egress; the real HLS URL or an honest "web output is off"; local rehearsal preset).
- Every one was hostile-reviewed to a MERGE verdict with delta rounds: #212 and #213 one round, #215 and #216 three, #214 five, #209 six. Reviewers executed rather than read -- 71 adversarial database URLs, all nine ARP state combinations compiled into the crate, ten now/next probes, a real `mklink /J` junction swapped in inside the resolver cache TTL, and mutation-reverts of every claimed fix.
- MERGE-ORDER HAZARD, learned the hard way: every PR carries `[Unreleased]` CHANGELOG entries, so each merge invalidates the next and costs a full CI round. #209, #213, #214 and #216 each needed a re-merge after an earlier one landed. Resolve with `python "<scratchpad>\opus-changelog-resolve.py"` run from the worktree root: main's entries first, then the branch's, and it prints every bullet it kept. Scratchpad path is in "Where things are" below.
- SILENT-COLLISION HAZARD: #214's merge with #216 broke `tests/cable/test_channel_contracts.py` WITHOUT a conflict -- both PRs had added a module-level `_client_with_egress_store` in different places, git kept both, and the later definition shadowed the earlier one. `git merge` reported success. Only running the tests caught it. After merging two PRs that touch the same test module, grep for duplicate top-level definitions.
- INSTRUMENT TRAP: this box's global ruff (0.16.4) and global mypy (2.3.1) both disagree with the repo's locked versions (ruff 0.15.12, mypy 2.0.0). The global mypy reports 2440 errors in 376 files where the locked one is clean. Always gate with `uv run --frozen`.
- FOLLOW-UPS FILED, none blocking beta.6: (a) the FALLBACK_SLATE Start watchdog can never fire because the daemon rewrites that row's `updated_at` every 2 s, and the test that pins it freezes `updated_at` (full reproduction in #216's round-2 review); (b) withhold `current_source_label` on the unauthenticated `GET /api/public/egress/channels/{id}/now`; (c) SetupScreen renders the sign-in form twice on a 429; (d) the "Recovery kit never confirmed" button swallows a 403; (e) a resolver-cache TTL window can advertise a `manifest_url` the router then 404s.
- Then the beta.6 kit pipeline (task 8); #202 soak; captions root cause (9).
- Full fix list: C:\Users\scott\Desktop\floatsom\CIVICCAST-BATCH-FIX-LIST-2026-09-03.md (items 93-135); run log: CIVICCAST-RESUME-STATE.md.
- Both tester machines started 8-hour soaks of beta.5 at 11:00 PM (docs/SOAK-PROMPT.md); reports due ~7 AM as Desktop\SOAK-<pc>-<date>.zip on each machine.

## Where things are
- Main checkout: C:\Users\scott\Desktop\Code\civiccast-native. Worktrees: cc-docs165 (#165), cc-journal-tolerant (#206), cc-install-helper (#207), cc-ownership-claim (ownership fix), cc-beta6-bump (#208), cc-item66 (#202), cc-sbsoak-run (sandbox lane, detached at origin/main).
- Session scratchpad with build-chain.sh, after-build.ps1, sbsoak-launch.ps1: C:\Users\scott\AppData\Local\Temp\claude\C--Users-scott-Desktop-Code\9e39825a-17bf-473c-8ada-72211a0f3e03\scratchpad
- Gate A runner: C:\actions-runner-gate-a (start run.cmd after a reboot). Evidence: C:\actions-runner-gate-a\_work\civiccast-native\civiccast-native\sandbox-lab\evidence\<sha>\.
- Elevated helper: queue JSON {job_id, action: RunTrustedPowerShellScript, scriptPath} in C:\dev\ClaudeElevatedHelper\queue, then Start-ScheduledTask ClaudeElevatedDevHelper; kill-orphan-sandbox.ps1 clears a leftover vmmemWindowsSandbox.
- Shared git stash must stay at exactly 1 entry. Never `git stash`.

## Verification ledger
VERIFIED: all seven fix PRs are merged and main is 2d7fd65b | gh pr list --state open (only #202, #175, #155, #138 remain, all pre-existing) + git log origin/main (2026-09-10 4:05 AM MT)
VERIFIED: #214's final gates at b7613b61 -- 3379 passed / 101 skipped, mypy clean on 675 files, ruff clean, 1033 + 61 portal tests, 254 a11y checks including the new dark-mode axe scans | builder report + required CI green before I merged
VERIFIED: #211, #212 and #215 are merged; main is 184398d9 | git log --oneline origin/main (2026-09-10 2:05 AM MT)
VERIFIED: #215's own gates at 65abe704 were 2416 passed / 10 skipped (pytest tests/policy tests/installer) and 958 operator-portal tests, and its required CI checks were all green before I merged | builder report + gh pr checks 215
UNVERIFIED: the delta-review findings for #214 round 3, #216 round 2 and #209 round 5 - read from the reviewers' PR comments, not independently re-measured by this session
VERIFIED: after #165 merged, main 76817e3d passes the three previously-red doc/release tests -- 29 passed | pytest tests/policy/test_release_truth.py tests/policy/test_windows_release_downloader.py tests/test_audit_protocol_docs.py -p no:randomly (2026-09-10 12:56 AM MT)
VERIFIED: #213's own failure was `POST /api/staff/auth/sign-out` having no role dependency; the route's own docstring says any role may call it, so it is recorded in ALLOWED_UNGUARDED_STAFF_MUTATION_ROUTES with the reason -- 2 passed | tests/policy/test_staff_mutation_role_policy.py at 4288ffa2
VERIFIED: #212 at 233e8e18 passes its own suites -- 151 passed | pytest tests/egress/test_daemon.py tests/egress/test_store.py -p no:randomly
UNVERIFIED: the delta-review findings for #209 round 4, #214 round 2 and #215 round 2 - read from the reviewers' PR comments, not independently re-measured by this session
VERIFIED: main 27dfc076's docs/releases/release-truth.yaml had two `v1.0.0-beta.5` entries and check_release_truth.py reported `DRIFT: manifest: duplicate tags in entries` | docs/releases/release-truth.yaml:39-63 + checker run 2026-09-10 12:10 AM MT
VERIFIED: the four required-check failures shared by #211/#165/#209/#213/#212 are the release-truth + current-release doc tests, not per-PR breakage | gh run view --job 102753825811 --log-failed (PR #213 Unit tests)
VERIFIED: on #165 head cd50c3d4 the whole tests/policy suite is 1920 passed, 5 skipped and check_release_truth.py prints `release-truth: PASS` | local pytest run 2026-09-10 12:18 AM MT
VERIFIED: `tests/policy/test_staff_mutation_role_policy.py` passes on #165's tree, so #213's failure of that test is #213's own | same local run
VERIFIED: the upgrade routing accepts only `<major>.<minor>.<patch>[-<label>.?<number>]`, so `beta.5.1` is not a legal version and the follow-up is `1.0.0-beta.6` | civiccast/native/upgrade/routing.py:150
VERIFIED: Gate A is dispatched with inputs `run_id` (build run id) and `lane` (full | cross-version-only | download-only-only) | .github/workflows/gate-a-station-acceptance.yml:75-89
VERIFIED: the publisher requires --kit-dir, --source-sha, --build-run-id, --gate-a-run-id, --tag, --truth-status and refuses without Gate A verdict artifacts (dry run output 2026-09-09) | scripts/release/publish_beta_candidate.py:1 (--help)
VERIFIED: the Gate A cross-version baseline pin schema (schema_version 2, source_sha, run_id, gate_a_run_id, installer_sha256, station_index_sha256, product_version, notes) | sandbox-lab/upgrade-baseline.json:1-11
VERIFIED: HANDOFF.md is gitignored in this repo and must be force-added | .gitignore:146
VERIFIED: 1.0.0-beta.5 is the product version on main 148c8d21 | civiccast/_native_version.py:34
VERIFIED: the sandbox soak lane's Run-SandboxSoak.ps1 takes -SeamlessReload, -OnAirBoundMinutes, -CaptionsOff, -WorkerEnv | sandbox-lab/Run-SandboxSoak.ps1:105-135
UNVERIFIED: the builder-reported line numbers for PRs #202, #206, #208, #209 - taken from builder and reviewer reports, not re-read by this session
VERIFIED: Gate A run 34423542177 concluded success with all three lanes PASS; v1.0.0-beta.5 release exists with 8 assets, isDraft=false | gh run view 34423542177 / gh release view v1.0.0-beta.5 (2026-09-10 04:14Z)
