# CivicCast F1–F3 execution prompt

You are implementing three specific CivicCast corrections for Scott Converse. Execute the work; do not stop at a proposed plan. This assignment supersedes historical stop-on-start instructions for these three goals only.

## Repository and starting documents

- Repository: https://github.com/scottconverse/civiccast-native
- Documentation branch: `docs/prioritized-plan-20261025`
- Execution plan: https://github.com/scottconverse/civiccast-native/blob/docs/prioritized-plan-20261025/docs/handoff/PRIORITIZED-EXECUTION-PLAN-2026-10-25.md
- This prompt: https://github.com/scottconverse/civiccast-native/blob/docs/prioritized-plan-20261025/docs/handoff/F1-F3-AGENT-PROMPT-2026-10-25.md
- Reviewed baseline main: `933dd6571ab57ee5891f76c1148b79cb9c77bbc0`.

Read the plan, current root `AGENTS.md` and `CLAUDE.md`, and `docs/handoff/CURRENT.md`. Use your checkout's paths, not the original machine's drive paths. Reports named in the plan are background sources, not missing execution prerequisites. Reconcile relevant changes after the baseline; historical handoff text is not proof of current state.

Preserve existing checkout changes and other agents' work. If cloning on Windows:

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
$env:GIT_LFS_SKIP_PUSH = '1'
git clone --single-branch --branch docs/prioritized-plan-20261025 https://github.com/scottconverse/civiccast-native.git civiccast-native
Set-Location civiccast-native
git fetch --no-tags origin main
git switch -c fix/f1-f3-caption-publish-dependencies
```

If fetched main has advanced beyond the documentation branch, reconcile newer source changes into your working branch before implementing; do not overwrite them or repeat delivered fixes. Use a fresh branch name if that name belongs to another task. Do not edit frozen candidates.

## Hard active goal and delivery boundary

Set the active goal to: **Complete F1, F2, and F3 from the linked plan, with their definitions of done, focused verification and required CI; push the implementation and deliver a review-ready PR against main with honest acceptance results.** Use the native goal facility if available; otherwise track this same objective in the existing handoff. Do not invent a goal harness.

Authorized: affected source/documentation changes, isolated development environments, focused checks and required CI, DCO-signed commits, branch push, and PR creation/update. Not authorized: merge, tag, public release, installer rebuild, installed-station upgrade, spending, or provider account creation. The deliverable is a review-ready PR, not an installed release.

## F1 — Captions follow trimmed video

Correct the source-to-published-video timeline mismatch. Beginning/end-trimmed recordings must have aligned captions, no removed material retained in cues, no negative/out-of-range cues, and no stale cues restored by republishing. Preserve untrimmed behavior.

Reproduce with one small isolated sample where practical; correct the cause and run focused regression checks plus that workflow. Do not replace the caption engine.

## F2 — Provider setup and YouTube Live deliver real output

Make saved provider configuration securely reach existing real adapters without duplicate manual environment setup. Clearly distinguish simulated behavior from delivery. Complete existing YouTube Live publishing so the selected channel reaches its correctly configured event, with valid metadata, lifecycle handling, and truthful configured/starting/live/failed status. Protect stream keys and return viewer links for viewing. Provider failures must not disable the local portal.

Use existing fixtures/software receivers and authorized provider access. Simulator proof is not external-delivery proof. If account/access is unavailable, name that exact acceptance blocker and continue F1/F3; do not claim full F2 completion. Do not expose credentials, create accounts, or spend money. No Facebook, new providers, new scheduled-distribution feature, or unrelated provider rewrite.

## F3 — Targeted dependency advisory corrections

Determine current advisory identities and runtime versus development exposure. Baseline findings include filelock, pypdf, setuptools, virtualenv, Zod, Vitest/mocker, and Undici; verify current versions/findings. Brotli and the Windows resource-classification issue are already corrected in main—do not redo them.

Use compatible targeted updates. Relevant scans and affected behavior must pass for findings claimed resolved. Document any installed-environment update needed without performing it. No blanket audit-fix, unrelated major upgrades, suppressed advisories, lowered thresholds, or general security audit. A finding with no compatible correction stays incomplete.

Triage exposure early. A reachable serious runtime vulnerability takes precedence; otherwise work serially through F1/F2/F3.

## Anti-drift rules

1. F4–F7, all N-series features, and all deferred work are OUT OF SCOPE. Record unrelated findings without implementing them or making them new PR gates.
2. One executor, one candidate, existing tools, and one concise current outcome/evidence/blocker record in `docs/handoff/CURRENT.md`. No automatic subagents, model changes, frameworks, harnesses, or duplicate ledgers.
3. Every additional check must serve changed behavior, an unresolved concrete defect in these goals, or required CI. Otherwise skip it. Add regression tests only for real behavior, not to mirror code.
4. Reuse unaffected evidence. Run required CI without weakening gates. Informational jobs do not become completion requirements. F3's targeted scans establish its remediation outcome, not new global CI policy. No mutation testing.
5. Review affected work once for material defects, then recheck necessary corrections only. No repeated full suites, universal documentation audits, new soaks, arbitrary latency targets, or installer campaigns.
6. After two same-cause failures, diagnose and change approach before retrying. Do not retry for a green badge or launch a broader audit without evidence.
7. Track owned background jobs and expected terminal results; use existing waiting mechanisms. No status-only continuation loops or stopping merely to report activity.
8. No LFS transfers or spending through October 2026. Preserve skip settings and newer owner restrictions. No unnecessary model/installer downloads.
9. Preserve data, recovery, legal holds, the existing endurance run, and unrelated work. No station restart, reinstall, upgrade, host reboot, or station stress. Use isolated software/API simulators; no hardware acceptance gate.
10. Hide Windows consoles/helpers: invisible ConPTY (`tty:true`, `login:false`), Hidden/CreateNoWindow children. Preserve disabled gh telemetry and existing hidden launchers.
11. Do not pause the goal without Scott's current explicit request. A newer resume overrides an old pause. Do not mark incomplete work complete; finish independent authorized work if an external dependency blocks another goal.

## Finish and stop

Deliver the PR URL, branch/commit, F1/F2/F3 statuses, actual focused-check and required-CI results, reused evidence, and exact remaining limitations. State whether YouTube was accepted using a simulator or real destination. Update only documentation affected by these changes.

Completion requires all three selected definitions of done plus the authorized PR delivery. Partial or blocked work remains incomplete. Do not merge, publish, or start another feature. Stop at this boundary.
