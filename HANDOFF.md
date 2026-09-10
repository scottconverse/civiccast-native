# HANDOFF

Any session, on any plan or tool, continues from this file. Times below are Mountain (America/Denver).
Rules in force: no new features; finish and test what exists; commit after each task; update this file after each task; stop at a clean state.

## Task list, most important first

1. DONE 10:14 PM: **v1.0.0-beta.5 PUBLISHED** https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.5 (8 assets, prerelease, target 148c8d21; Gate A 34423542177 all three lanes PASS). First attempt was refused (body > 125,000 chars, HTTP 422); the renderer fix is PR #210. release-truth.yaml flipped by the publisher and committed. Command used:
   `python scripts/release/publish_beta_candidate.py --kit-dir C:\CivicCastTester\kit-mirror\148c8d2172dd6b63cbbb856b429b68aa020dc421 --source-sha 148c8d2172dd6b63cbbb856b429b68aa020dc421 --build-run-id 34405681086 --gate-a-run-id 34423542177 --tag v1.0.0-beta.5 --truth-status current`
   The dry run already passed layout, version and Authenticode. The publisher updates docs/releases/release-truth.yaml; commit that.
2. **Finish release notes PR #165** (branch docs/release-beta5, worktree C:\Users\scott\Desktop\Code\cc-docs165, head 834d68f5): fill the last tokens (GATE-A-XVER = PASS, GATE-A-DLONLY, RELEASE-URL, ASSETS-TABLE; release-notes.md ~487-491, verification.md ~80-88, 112), add known issues 99 (legacy NATS journal halts August-install upgrades) and 100 (ownership check exit 85/127 on boxes with uninstall history) with the workarounds in docs/INSTALL-HELPER-PROMPT.md, then merge.
3. **Merge PR #206** (journal tolerant of legacy NATS keys) on green CI at e2537f13 (adds the +13 native test-count pin). Reviewed twice; round-3 delta accepted.
4. DONE 10:14 PM: PR #207 (docs/INSTALL-HELPER-PROMPT.md) merged.
5. **Ownership-check fix = PR #209** (branch fix/runtime-ownership-claim-diagnosable, worktree cc-ownership-claim, head d6d5ea2f): hostile review said MERGE with follow-ups; round 2 in progress (5 s bound on `sc query`, dialog wording on upgrades, const assert, skip-predicate pin). Merge on green after round 2. Item 101 (forward the provisioning CLI's stderr into install-progress.log) is NOT in this PR: it needs a file handoff like ownership-observation.txt plus a policy test that no stderr line can carry the database URL; do it as its own PR later.
6. DONE 10:20 PM: PR #208 merged (main a2ccfc98): product version is now 1.0.0-beta.6; Gate A baseline repinned to the beta.5 kit.
7. **PR #202** (reload wedge off-air retirement, crash at stop; head 399c4618, draft, rebased on 148c8d21): needs a sandbox soak proving on every rollover that `stage=holds-released` precedes `stage=old-leg-disposed`, zero `reload-commit-timeout`, then 20+ loaded runs at 100% CPU (only when the box is otherwise idle), then a delta review, then merge.
8. **beta.6 kit**: after 3-7, build with `scratchpad\build-chain.sh <main sha>`, cancel the auto Gate A, kill the orphan sandbox VM via the elevated helper, soak 15 min (captions OFF default, seamless ON), dispatch Gate A full, publish `--tag v1.0.0-beta.6`. Never run anything I/O or CPU heavy during Gate A (two attempts failed tonight from host load).
9. **Captions root cause** (item 96): with live captions ON, video holds 25-30 s then bursts, every 1-2 min. Needs a `GST_DEBUG=cccombiner:6,aggregator:5` discriminator soak. Not before 1-8.

## Added 10:35 PM from the clean-machine walkthrough (tester report, beta.5)
Three fix PRs are being built in parallel; each gets a hostile review, then merges on green, then joins the beta.6 kit:
- cc-boundary-stop / fix/slate-boundary-relaunch-not-stopped: a finite slate plan reaching EOS relaunches onto the due program instead of STOPPED; STARTING written before prepare; Channels elapsed-time polling. (items 105, 110)
- cc-portal-live / fix/portal-live-follows-egress-and-hls-truth: resident /api/public/live/current follows egress when an hls sink exists; Channels shows the real HLS URL or says web output is off; local rehearsal HLS preset. (item 104)
- cc-setup-session / fix/first-setup-recovery-kit-signout-autofill: recovery kit survives navigation until confirmed; Sign out control + route; no browser autofill on first setup. (items 102, 103, 97)
Not started (beta.6 or later): 106 startup page, 107 state authority, 109 sample live source, 112-115 copy/mobile/docs. Full list: Desktop\floatsom\CIVICCAST-BATCH-FIX-LIST-2026-09-03.md items 102-135.

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
- beta.5 publish (waiting on lane 3), #165 merge, beta.6 pipeline (tasks 3-8), captions root cause (9).
- Beta.6 hygiene list lives in C:\Users\scott\Desktop\floatsom\CIVICCAST-BATCH-FIX-LIST-2026-09-03.md (items 93-101) and the run log in CIVICCAST-RESUME-STATE.md.

## Where things are
- Main checkout: C:\Users\scott\Desktop\Code\civiccast-native. Worktrees: cc-docs165 (#165), cc-journal-tolerant (#206), cc-install-helper (#207), cc-ownership-claim (ownership fix), cc-beta6-bump (#208), cc-item66 (#202), cc-sbsoak-run (sandbox lane, detached at origin/main).
- Session scratchpad with build-chain.sh, after-build.ps1, sbsoak-launch.ps1: C:\Users\scott\AppData\Local\Temp\claude\C--Users-scott-Desktop-Code\9e39825a-17bf-473c-8ada-72211a0f3e03\scratchpad
- Gate A runner: C:\actions-runner-gate-a (start run.cmd after a reboot). Evidence: C:\actions-runner-gate-a\_work\civiccast-native\civiccast-native\sandbox-lab\evidence\<sha>\.
- Elevated helper: queue JSON {job_id, action: RunTrustedPowerShellScript, scriptPath} in C:\dev\ClaudeElevatedHelper\queue, then Start-ScheduledTask ClaudeElevatedDevHelper; kill-orphan-sandbox.ps1 clears a leftover vmmemWindowsSandbox.
- Shared git stash must stay at exactly 1 entry. Never `git stash`.

## Verification ledger
VERIFIED: the upgrade routing accepts only `<major>.<minor>.<patch>[-<label>.?<number>]`, so `beta.5.1` is not a legal version and the follow-up is `1.0.0-beta.6` | civiccast/native/upgrade/routing.py:150
VERIFIED: Gate A is dispatched with inputs `run_id` (build run id) and `lane` (full | cross-version-only | download-only-only) | .github/workflows/gate-a-station-acceptance.yml:75-89
VERIFIED: the publisher requires --kit-dir, --source-sha, --build-run-id, --gate-a-run-id, --tag, --truth-status and refuses without Gate A verdict artifacts (dry run output 2026-09-09) | scripts/release/publish_beta_candidate.py:1 (--help)
VERIFIED: the Gate A cross-version baseline pin schema (schema_version 2, source_sha, run_id, gate_a_run_id, installer_sha256, station_index_sha256, product_version, notes) | sandbox-lab/upgrade-baseline.json:1-11
VERIFIED: HANDOFF.md is gitignored in this repo and must be force-added | .gitignore:146
VERIFIED: 1.0.0-beta.5 is the product version on main 148c8d21 | civiccast/_native_version.py:34
VERIFIED: the sandbox soak lane's Run-SandboxSoak.ps1 takes -SeamlessReload, -OnAirBoundMinutes, -CaptionsOff, -WorkerEnv | sandbox-lab/Run-SandboxSoak.ps1:105-135
UNVERIFIED: the builder-reported line numbers for PRs #202, #206, #208, #209 - taken from builder and reviewer reports, not re-read by this session
VERIFIED: Gate A run 34423542177 concluded success with all three lanes PASS; v1.0.0-beta.5 release exists with 8 assets, isDraft=false | gh run view 34423542177 / gh release view v1.0.0-beta.5 (2026-09-10 04:14Z)
