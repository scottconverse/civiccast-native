# Slice D - Documentation correctness and file hygiene

Repo: `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-release`, branch `release/beta10`, HEAD `4173301d`. Read-only audit, 2026-10-02.
Method: git ls-tree sizes, grep of code for every env var / CLI command / route / UI label the operator docs name, scripted link and anchor checks over 30 docs, cross-read of version wording, comparison with `docs/releases/v1.0.0-beta.10-verification.md`.

Counts: Blocker 0, Critical 0, Major 14, Minor 6, Nit 1 (21 findings).

---

### D-001 Major: INSTALL-WINDOWS.md recovery section documents a retired mechanism and commands that do not exist
**Dimension:** Docs
**Evidence:** `INSTALL-WINDOWS.md:141-202` ("If The Operator Console Says 'Could Not Read Setup State'") tells the operator to run `"...\CivicCast Native.exe" --civiccast-restore-setup-handoff` (Option A, line 171) or `python.exe -m civiccast.native.runtime_cli setup-handoff` (Option B, line 185) and to treat a `?nonce=` URL as a password. Commit `3497cdb1` "retire the setup-nonce handoff, admit First Setup by loopback alone (#60)" removed that mechanism. `civiccast/native/runtime_cli.py` registers only `status`, `probe`, `cutover-to-native`, `rollback-to-wsl` (lines 140/175/1143/1516); `grep -rn "restore-setup-handoff" civiccast` finds only two UI tests asserting the text is NOT shown. `docs/QUICKSTART-OPERATOR.md:52`, `docs/USER-MANUAL.md:833`, `docs/tester/START-HERE.md:109` and others still say "installer handoff URL".
**Why it matters:** An operator who is stuck on the setup screen is told to run two commands that fail, and to guard a URL that no longer carries a secret.
**Fix path:** Delete lines 141-202 (or replace with the current loopback-only behaviour: open `http://127.0.0.1:8000/operator/` on the station itself). Reword "installer handoff URL" in QUICKSTART, manual, tester docs to "the Operator Console shortcut".

### D-002 Major: Landing page claims that the code and the repo's own docs contradict (captions, model, hardware check, readiness badge)
**Dimension:** Docs
**Evidence:** `docs/index.html`:
- line 625 hero badge "PEG Station Ready" on a page that also says "Sustained production use at a real PEG station" is not proven; README says "not a production release".
- lines 683/750 name `whisper-large-v3 INT8` as the caption model. `civiccast/ai_models/catalog.py:153-217` binds the default to `whisper-medium-faster` (owner decision 2026-07-30: medium is the mandatory floor, large-v3 is optional and auto-selected only when hardware allows).
- line 800 "AI captioning activates automatically based on your detected hardware tier". `CAPABILITIES.md:68` and `docs/tester/known-limitations.md:21`: live captions are OFF by default (Setup > Station Profile > Show live captions on air).
- line 795 "`civiccast doctor` ... configures CivicCast for your optimal tier ... completes in under 30 seconds". `civiccast/cli.py:177-190`: doctor only probes and reports; no timing evidence exists.
- line 617 "Real-Time AI Captioning" with the known-limit that 13 catch-up discards happened in the 8 h run.
**Why it matters:** The first screen a station director reads promises readiness and automatic captioning that the product does not deliver by default, and captions carry legal weight (verification record limit 1 says so).
**Fix path:** Replace the badge with "Public beta"; state captions are off by default and how to enable; say the default model is `medium` with large-v3 optional; describe `doctor` as "reports your hardware tier"; delete the 30-second claim. Not covered by any policy test (`tests/docs/test_public_surface_integrity.py` checks release posture only).

### D-003 Major: Landing page promises multi-destination live streaming (Facebook Live, simultaneous outputs, "Go Live") that no code or doc supports
**Dimension:** Docs
**Evidence:** `docs/index.html:690` "Multi-output streaming to cable headend, YouTube Live, Facebook Live, and custom RTMP endpoints - simultaneously from one interface"; line 800 "Connect your capture card, configure stream destinations, and broadcast". `git grep -il facebook` hits only `docs/index.html`, old specs, SECURITY.md and CLAUDE.md; nothing under `civiccast/`. `FAQ.md:98-130` says the stock build cannot verify a live source, shows "Source preview unavailable" and "does not claim a working live broadcast". `docs/USER-MANUAL.md:173,193` say YouTube simulcast and Internet Archive need station credentials and are unproven; `README.md:256-260` agrees.
**Why it matters:** A station could plan a Facebook simulcast and live capture-card workflow from the landing page that the product cannot do.
**Fix path:** Remove "Facebook Live" and "simultaneously"; align the Go Live step with FAQ wording (recorded-media path is the proven one; live ingest needs an integrator-supplied media probe).

### D-004 Major: Operator docs contradict each other on whether setup downloads the AI models
**Dimension:** Docs
**Evidence:** "Do not assume the installer will fetch models later in the background": `INSTALL-WINDOWS.md:52-53,125`, `docs/tester/START-HERE.md:43,104`, `docs/tester/lpm-beta-test-handoff.md:41,134`, `docs/USER-MANUAL.md:815-817`. Opposite: `FAQ.md:61-66,82-85` ("downloading only the tags still missing, in the background once the console is already open") and `docs/USER-MANUAL.md:1362-1368`. The installer code has an interactive download path: `civiccast/apps/installer/src-tauri/src/acquisition_catalog.rs` (component catalog with `local_ai_model`, `captions_medium`), `AcquisitionFlow.tsx:891` "Stop downloading", and `docs/QUICKSTART-OPERATOR.md:44,75` itself tells operators about "Found locally" and "Stop downloading". The first-install requirement (21 GB USB bundle) is therefore stated as the only path while the installer UI downloads components.
**Why it matters:** A first-time installer cannot tell whether to bring a 21 GB USB kit or rely on downloads; FAQ and manual contradict themselves.
**Fix path:** Decide against the actual beta.10 installer behaviour (owner's settled design: small base, big components downloaded during install with progress UI), then rewrite all eight places once, naming which components download and which need the kit.

### D-005 Major: Linux and macOS support text survives in active docs for a Windows-only product
**Dimension:** Docs
**Evidence:** `FAQ.md:77` "A Windows 11, Linux, or macOS host that passes `civiccast doctor`"; `ARCHITECTURE.md:192-193` "Native Linux is the Linux CI-oriented path. macOS package proof exists as metadata/posture"; `docs/USER-MANUAL.md:1200-1209,1280-1281` (`civiccast installer platform-plan [--os-family linux|macos]`, coturn on Linux/macOS); `docs/install/macos.md` and `docs/installer/cross-platform-installer.md` are whole files. README/BRANCHES/INSTALL say "no WSL, no Docker, no Linux install target" (retired 2026-08-19).
**Why it matters:** Directly contradicts the product statement in the same repo; a reader could try a Linux install.
**Fix path:** Edit FAQ line 77 to Windows 11 only; delete the ARCHITECTURE sentence; keep the manual's CLI line but label it "development planning only" or drop it; move the two cross-platform docs to `docs/history/` (tests `tests/policy/test_cross_platform_installer_policy.py` pin the retirement wording - keep that wording).

### D-006 Major: Five tester docs still name beta.8 as the unpublished candidate
**Dimension:** Docs
**Evidence:** `docs/tester/nontechnical-walkthrough.md:17` "Beta.8 remains an unpublished candidate while its release checks run"; `docs/tester/technical-walkthrough.md:18` "Beta.8 is an unpublished candidate"; `docs/tester/SMARTSCREEN-WALKTHROUGH.md:17`; `docs/tester/lpm-beta-test-handoff.md:72,96`. Everywhere else (README, FAQ, SUPPORT, BRANCHES, CHANGELOG, verification record) says beta.8 and beta.9 were never published and beta.10 is the owner-held unpublished candidate. `docs/tester/known-limitations.md:25` is correct.
**Why it matters:** Version/status wording is not consistent; a tester is told to expect a build that will never ship.
**Fix path:** Replace "Beta.8" with "`v1.0.0-beta.10` ... owner-held unpublished candidate" in those five spots. No policy test pins the beta.8 sentence (checked `scripts/policy/check_no_contradictory_release_banners.py`).

### D-007 Major: CAPABILITIES.md ("canonical, living record") is baselined on a pre-reset build, cites missing evidence, and mixes retired-line claims
**Dimension:** Docs
**Evidence:** `CAPABILITIES.md:36` baseline "v2.0.10 (commit 02c9e6c), 2026-06-09" and a pointer to `docs/releases/archive/pre-reset/README.md` (path does not exist); line 71 cites `tester-handoff/v2.1.0/test-results/windows/20260612-0824-local-ca8-4h-acceptance.md` for a "4h three-channel acceptance passed" (no `tester-handoff/` in the repo; BRANCHES.md says it was not carried over); the "Proof Is Not Production" section (line ~88) says "The v0.1.0-rc6 public-beta line has clean Windows, release-artifact, and local public-beta soak evidence" (a retired line); the scope note (line ~28) says the Windows evidence "describes the retired WSL2 line" unless a row says otherwise. About 20 rows carry the label `production-wired` on a beta product.
**Why it matters:** The file says "update this file in the same commit" and docs defer to it, but its evidence column cannot be checked and part of it belongs to another product.
**Fix path:** Re-baseline on beta.10, drop or relabel rows whose evidence is not in this repo, rename `production-wired` to something that does not imply production (e.g. `wired, config-gated`), and delete the two dead path references.

### D-008 Major: ARCHITECTURE.md never mentions the playout engine, egress, or native service
**Dimension:** Docs
**Evidence:** `grep -n -i "egress\|gstreamer\|supervisor\|playout\|civiccast.native" ARCHITECTURE.md` returns only two unrelated hits in the banner (lines 5, 29). The "Major Modules" table (lines ~85-100) lists 14 packages but not `civiccast.egress` (largest package: `daemon.py` 384 KB, `gst/engine.py` 456 KB), `civiccast.native` (service supervisor), `programlog`, `alerting`, `eas`, `cg`. "Runtime Entry Points" omits `civiccast/egress/daemon.py` and the Windows service. `docs/USER-MANUAL.md` Section C does cover the GStreamer engine, so the two disagree on scope.
**Why it matters:** The architecture overview describes a recorded-meeting web app, not the 24/7 playout product that beta.10 is about; engineers and auditors get the wrong map.
**Fix path:** Add a "Playout and native service" section (service -> supervisor -> daemon -> GStreamer worker -> HLS/TS output, caption tap, conform cache) and add the missing packages to the module table.

### D-009 Major: Settings, route and command named in the manual that do not work
**Dimension:** Correctness
**Evidence:** Of 202 distinct `CIVICCAST_*` names in the operator docs, 195 resolve in code; the other 7 break down as:
- `CIVICCAST_CAPTION_PROOF_POLL_SECONDS` (`docs/USER-MANUAL.md:1031`): `civiccast/app.py:1673` reads the one-C spelling `CIVICAST_CAPTION_PROOF_POLL_SECONDS` (and `:1675` `CIVICAST_CAPTION_PROOF_TIMEOUT_SECONDS`). Setting the documented name is silently ignored. Same defect class that `civiccast/egress/env_vars.py` was written to end.
- `CIVICCAST_EVENTS` (`USER-MANUAL.md:1037`): no code reads it (`grep` finds only manual.json).
- `/api/tokens` (`USER-MANUAL.md:1295`): no such route; auth routes are under `/api/staff/auth`.
- `civiccast egress recovery-proof` (`USER-MANUAL.md:1312`): not registered; egress commands in `cli.py` are `run, verify, trim-health, continuity-proof, srt-continuity-proof, caption-decode-proof, verify-captions` (the last is undocumented).
- Remaining three are prefix wildcards or test-only names (`..._RETRY_*`, `CIVICCAST_RUN_AGENDA_SOURCE_PROOF`, `CIVICCAST_TSR_*` - the last two are real in the Node service/tests).
**Why it matters:** An IT person tuning caption proof cadence changes nothing and gets no error.
**Fix path:** Fix the two `CIVICAST_` reads in `app.py` using the existing `env_vars.py` fallback helper (code change, route to the engineering slice); remove `CIVICCAST_EVENTS`, `/api/tokens`, `recovery-proof` from the manual or implement them; add `verify-captions`.

### D-010 Major: Four overlapping handoff/status documents, three of them stale, at the repo root
**Dimension:** Docs
**Evidence:** `HANDOFF-PROMPT.md` (4 KB) is the beta.5/beta.6 cold-start prompt: "DO NOT publish the built beta.6 kit", "Nothing is in flight", reads `HANDOFF.md` "gitignored" (it is tracked: `.gitignore:146` lists it but it was force-added). `HANDOFF.md` is 938 lines, mostly beta.5-beta.8 checkpoints; only its first paragraph is current. `PROJECT-STATUS.md` is 880 lines: first 30 lines current, then eleven stacked "latest/current" blocks (lines 28-362) and sections 2-11 (beta.5/6 task list, kit-LAN-server commands at lines 767-815, local paths `C:\CivicCastTester\kit-safe`, `D:\RUN-THIS-...`). The authoritative handoff is `ops/beta10-oversight/HANDOFF-2026-10-01.md`. `next-cleanup.md` is a 12-line deferred-work note read by `scripts/policy/check_no_todos.py`.
**Why it matters:** A fresh agent following HANDOFF-PROMPT.md would conclude the project is at beta.5 with an unpublished beta.6 kit and a blocker still open.
**Fix path:** Delete `HANDOFF-PROMPT.md`; move `HANDOFF.md` and PROJECT-STATUS sections 2-11 and dated blocks to `docs/history/`; keep a short PROJECT-STATUS.md (current block + pointer to the ops handoff). Keep `next-cleanup.md` (policy script reads it) or move it and update `check_no_todos.py`/`pyproject.toml`.

### D-011 Major: CLAUDE.md and AGENTS.md carry a stale standing release authorization and template residue
**Dimension:** Docs
**Evidence:** `CLAUDE.md:8-18` "Current owner authorization - 2026-09-08 beta.5 release ... authorized to ... push, merge on green CI, tag, and publish ... Do not use staged-build, Workflowwright, GauntletGate, Proof Gate, or Audit Team skills"; `AGENTS.md` repeats the authorization (lines 1-12). `CLAUDE.md:3` still says "When moving this file into the project repo, rename it...". `PROJECT-STATUS.md:5-7` instead records a fresh 2026-10-02 authorization, and `ops/beta10-oversight/HANDOFF-2026-10-01.md:8-12` says push, merge, tag, release wait for the owner.
**Why it matters:** Any agent reading these files inherits a standing tag-and-publish permission scoped to a release that shipped three weeks ago, and a ban on the audit skills this audit uses.
**Fix path:** Owner decision: delete the dated authorization block (or replace with "release actions are owner-only unless the owner states otherwise in chat"), and delete line 3.

### D-012 Major: FILE-HYGIENE rule is enforced for new files only; about 13 MB of scratch/evidence is still tracked
**Dimension:** Correctness
**Evidence:** `.gitignore:272-295` now ignores `/work/`, `*.jsonl`, `*.mp4`, `*.zip`-style evidence only by pattern, but ignore does not untrack. Tracked today (3375 files, 62.97 MiB total): `work/` 82 files 1.64 MB (rung receipts, `*.jsonl`, caption reports); `docs/evidence/` 80 files 6.48 MB incl. 7 evidence `.zip` (5.77 MB), 15 raw `worker.log`/`*-channel-N.log`, patches, trackers; `docs/releases/evidence/` 174 files 5.03 MB of v0.4-v0.10 and v2.1.0/v3.0.0-beta1 screenshots from the retired pre-reset ladder, 3.67 MB not referenced by any other file; `sandbox-lab/scripts/lpm-sample-short.mp4` 3.67 MB (a `*.mp4`, referenced by `In-Sandbox-Report.ps1`); `.agent-runs/native-windows/` 71 files 0.31 MB; `.claude/` 43 files. `docs/FILE-HYGIENE.md` rule 2 and 4 say none of this belongs in git. Working tree itself is clean (71 MB on disk, nothing untracked), history pack is 58.5 MiB, so a normal `git rm` is enough; no history rewrite is needed or recommended.
**Why it matters:** The rule's goal (repo holds source/tests/docs/durable state) is not met by the current tree, and the ignored patterns hide the leftovers from `git status`.
**Fix path:** `git rm -r --cached work docs/evidence/**/*.zip docs/evidence/**/*.log docs/releases/evidence/<unreferenced>`; keep verdict `.md` notes registered in `docs/claims/claims.yaml:46-67`; keep `.agent-runs/` dirs that tests cite until those tests are repointed; replace the mp4 with a generated fixture or a Release asset.

### D-013 Major: The new `*.ts` ignore rule hides every TypeScript source file
**Dimension:** Correctness
**Evidence:** `.gitignore:287` `*.ts` (intended for MPEG transport-stream media). `git check-ignore -v civiccast/apps/installer/src/newfile.ts` -> `.gitignore:287:*.ts`; same for `NEW.test.ts`. 136 tracked `.ts` files exist (installer `src/*.ts`, e2e specs, `playwright.config.ts`); the only negation is `!tests/fixtures/media/README*`. `*.bin` (line 292) similarly matches any `.bin` including legitimate fixtures.
**Why it matters:** The next new TypeScript file an agent creates in the installer or operator UI will not appear in `git status` and will be left out of the commit; CI then fails or, worse, builds without it.
**Fix path:** Replace with `*.ts` limited to media paths (e.g. `/media/**/*.ts`, `outputs/**/*.ts`) or add `!civiccast/apps/**/*.ts`, `!civiccast/apps/**/*.tsx`, `!tests/**/*.ts`; add a policy test that `git check-ignore` is empty for a sample `.ts` in `civiccast/apps/installer/src/`.

### D-014 Major: SUPPORT.md cites a clean-machine verification record that does not exist in the repo
**Dimension:** Docs
**Evidence:** `SUPPORT.md:100-104`: "A clean-machine verification record exists at `.agent-runs/native-windows/k1-clean-box-proof/evidence/` (clean-box install -> activation -> clerk loop -> captions -> product-engine egress, 2026-08-19)". `ls .agent-runs/native-windows` shows no such directory; `git log --diff-filter=D` finds no deletion, so it was never committed here.
**Why it matters:** An evidence claim whose evidence cannot be opened; SUPPORT.md is a public trust page.
**Fix path:** Delete the sentence or point to a record that exists (e.g. `docs/releases/v1.0.0-beta.7-verification.md`).

### D-015 Minor: Stale scripts, dead workflows and config clutter
**Dimension:** Correctness
**Evidence:** `scripts/bump-to-v3.0.0-beta1.sh` bumps 2.1.0 -> 3.0.0-beta1 (zero references; this line is 1.0.0-beta.10). `.github/workflows/ai-release-proof.yml:13`, `benchmark-caption-runtime.yml:35`, `diagnose-blackwell-runtime.yml:23` target `[self-hosted, linux ... scott-desktop ... ubuntu-2404]`, the retired WSL runner; `docs/ops/self-hosted-ci.md` documents that runner (WSL2, Docker, systemd). `.mcp.json` configures `codex-auditor`, whose protocol CLAUDE.md says was removed. `.claude/plans/` holds 39 June 2026 sprint plans (stale; agent plans). `docs/og.png` 1.59 MB is referenced nowhere (index.html has no og:image). `civiccast/apps/portal-operator/package.json:4` is `1.0.0-beta.7` while every other version file is `1.0.0-beta.10`. `scripts/egress-continuity-spike.py` is a spike but is tested by `tests/egress/test_continuity_spike.py` - keep.
**Why it matters:** Dead workflows can never run; stale scripts invite misuse; version drift in a package file.
**Fix path:** Remove the bump script, `.mcp.json`, `.claude/plans/`, `og.png` (or wire it); delete or retarget the three workflows and the self-hosted-ci doc; set operator package version to beta.10 (check `tests/policy/test_operator_version_label.py` first).

### D-016 Minor: README is a 522-line changelog; some of it is stale or omits known limits
**Dimension:** Docs
**Evidence:** `README.md:169` "landed for the first time in candidate #22" and "What's proven in this candidate" (line 121) never say which candidate; lines 275-359 are a beta.3-beta.5 soak narrative with PR numbers; line 354 cites `civiccast/native/station_runtime.py:1361` for "hardcodes it to inline unconditionally", but that code now honours `CIVICCAST_CAPTION_TAP=off` (comment block lines 1347-1366). `docs/releases/v1.0.0-beta.10-verification.md` limits 5-6 (eleven daemon/automation unit tests fail identically on the installed tree and candidate; an unexplained rebuild of a cached program) are missing from README, QUICKSTART and the manual's known-limit lists.
**Why it matters:** The front page buries the beta.10 status under history, and an operator-relevant open item (unexplained rebuild) is not listed where operators look.
**Fix path:** Cut README to status, install, links; move lines 83-117 and 167-359 to `docs/history/`; add the two missing limits (or state why they are developer-only).

### D-017 Minor: Operator-facing docs use jargon a station volunteer cannot follow
**Dimension:** Docs
**Evidence:** `docs/USER-MANUAL.md:14-130` opens Section A ("No jargon") with release-note language: "conform cache", "decode-back check", "slate or filler", "seamless reload", "Gate A", "soak", "egress". `docs/QUICKSTART-OPERATOR.md:19-25`: "SHA-256", "Authenticode", "sidecar", "candidate SHA". `INSTALL-WINDOWS.md:5-8,158`: "SCM", "session-0", "registry key restricted to SYSTEM". `docs/index.html:771,750,760`: "RTX caption proof", "INT8 quantization", "Multi-stream captioning". LUFS is explained once in README/QUICKSTART/manual; the others are not. A glossary exists (`docs/operator-language-guide.md`, linked from README) but is not linked from QUICKSTART or INSTALL.
**Why it matters:** The documents most likely to be read by a small TV station assume engineering vocabulary.
**Fix path:** Move the manual's beta.10 "what adds/measured" block to an appendix; add one-line plain definitions at first use; link the language guide from QUICKSTART and INSTALL.

### D-018 Minor: Retired WSL2 narrative still sits inside active operator docs
**Dimension:** Docs
**Evidence:** `INSTALL-WINDOWS.md:224-300` (75 lines), `docs/tester/START-HERE.md:144-191`, `docs/tester/known-limitations.md:73-195`, `docs/tester/lpm-beta-test-handoff.md:413-457`, `SUPPORT.md:51-66`, whole files `docs/adoption/early-adopter-quickstart.md` and `docs/tester/station-implementation-walkthrough.md`. All carry "Historical: retired" banners and some tests require those banners (`tests/policy/test_v17_adoption_gate.py:23`, `tests/policy/test_cross_platform_installer_policy.py:28`), so this is not an accuracy defect.
**Why it matters:** More than 400 lines of non-applicable install steps (`wsl --unregister`, helper reboots) sit one scroll below the current instructions.
**Fix path:** Move bodies to `docs/history/` and keep the banner plus a link, updating the tests' expected text in the same commit.

### D-019 Minor: Publishing beta.10 requires hand-editing about 28 files; QUICKSTART already names an installer that does not exist
**Dimension:** Docs
**Evidence:** `git grep -il "owner-held unpublished\|unpublished candidate"` outside `ops/` and history: 28 files (README, FAQ, SUPPORT, BRANCHES, ARCHITECTURE, CAPABILITIES, INSTALL-WINDOWS, ROADMAP, release-policy, index.html, install-windows.html, tester docs, manual, and policy scripts). `docs/releases/release-truth.yaml` (the stated "single source of truth") has no beta.10 entry and still says the live line is `v1.0.0-rc*` (header comment). `docs/QUICKSTART-OPERATOR.md:30` tells operators to run `CivicCast (Native)_1.0.0-beta.10_x64-setup.exe`; `docs/releases/v1.0.0-beta.10-verification.md` states no installer has been built. The in-product manual (`USER-MANUAL.md:48-56`) says beta.10 "has not been published", and ships inside the installer, so it will be wrong the day it is published unless re-rendered.
**Why it matters:** The flip from candidate to current is the moment these docs are most likely to contradict each other.
**Fix path:** Add a publish-time checklist (or script) that lists the 28 files, re-renders the manual, and updates `release-truth.yaml`; consider a policy test that fails when `_version.py` equals a tag the docs call unpublished.

### D-020 Minor: Landing page HTML lacks doctype, charset, viewport, lang; third-party scripts are not integrity-pinned
**Dimension:** Correctness
**Evidence:** `docs/index.html` line 1 is `<title>`; there is no `<!doctype>`, `<html lang>`, `<meta charset>` or `<meta viewport>` (`grep -c -i "doctype\|viewport\|charset\|<html\|lang="` = 0), yet the CSS has `@media (max-width: 900px/640px/420px)` rules that will not fire on phones without a viewport tag. Line 5 loads `three.js r128` from cdnjs and lines 2-4 Google Fonts, with no `integrity=` (0 matches). `docs/install-windows.html` is well formed.
**Why it matters:** Quirks mode, no language for screen readers, unreliable phone layout, and a third-party script executing on the project's public page.
**Fix path:** Add the four standard tags, add SRI hashes (or self-host three.js and fonts).

### D-021 Nit: Editing residue and small inconsistencies
**Dimension:** Docs
**Evidence:** `ARCHITECTURE.md:33` stray fragment "> differs architecturally."; `CLAUDE.md:3` template instruction; `BRANCHES.md:36-41` lists `docs/releases/` and `.agent-runs/` scratch as not carried over although both are tracked (201 and 71 files); `docs/releases/release-truth.yaml` header comment calls `v1.0.0-rc*` the live line.
**Why it matters:** Small trust erosion for readers who check.
**Fix path:** Delete the fragment and template line; reword the BRANCHES bullet; fix the header comment.

---

## Hygiene inventory

Total tracked: 3375 files, 62.97 MiB (`git ls-tree -r -l HEAD`). History: 695 commits, pack 58.5 MiB plus 2.3 MiB loose; no LFS. Working tree on disk 71 MB, clean, no untracked scratch.

| Group | Files | MB | Recommendation |
|---|---|---|---|
| `work/` (rung receipts, caption reports, `*.jsonl`, harness copies) | 82 | 1.64 | REMOVE from index (`/work/` is already ignored); move the six `BLACKWELL-CAPTION-FIX-REPORT-v*.md` and BETA10-* notes to `docs/history/` if wanted |
| `docs/evidence/` zips (7), raw logs, patches, trackers | ~60 of 80 | ~6.0 of 6.48 | REMOVE zips/logs/patches; KEEP verdict `.md` registered in `docs/claims/claims.yaml:46-67` |
| `docs/releases/evidence/` pre-reset screenshots, samples json/jsonl | ~106 of 174 | ~3.5 of 5.03 | REMOVE files not referenced elsewhere (retired v0.x-v3.0.0-beta1 ladder); KEEP files cited by tests (`test_claims_retraction.py`, installer API tests) |
| `docs/og.png` | 1 | 1.59 | REMOVE (unreferenced) or wire as og:image after compressing |
| `.claude/` (39 June plans, commands, launch/settings), `.mcp.json` | 44 | 0.23 | REMOVE (agent config/plans per FILE-HYGIENE rule 2) |
| **Firm reclaim from working tree** | | **about 13** | |
| `sandbox-lab/scripts/lpm-sample-short.mp4` | 1 | 3.67 | CONDITIONAL: referenced by `In-Sandbox-Report.ps1` and `docs/ops/gate-a.md`; generate at run time or fetch from a Release asset, then remove |
| `.agent-runs/native-windows/` | 71 | 0.31 | CONDITIONAL: several tests cite paths under it; prune after repointing |
| `ops/beta10-oversight/reports/` (U25 0.33, U59 0.25, U56 0.17 ...) | 81 | 3.10 | KEEP per rule 1; consider summarizing the three largest |
| **Conditional extra** | | **about 4-7** | |
| `docs/openapi.json` (generated, drift-tested), `docs/API-REFERENCE.md` | 2 | 2.28 | KEEP |
| `docs/USER-MANUAL.pdf`, `.docx`, `civiccast/docsite/manual.json` + render json | 5 | 1.05 | KEEP (render hashes pinned by `tests/test_user_manual_render.py`; verified in sync) |
| `docs/spec/` (superseded `spec.md` 0.23, one `.docx`) | 60 | 1.18 | KEEP; move superseded spec to history if desired |
| Root clutter: `HANDOFF.md` 0.07, `HANDOFF-PROMPT.md`, `PROJECT-STATUS.md` 0.06, `next-cleanup.md`, `scripts/bump-to-v3.0.0-beta1.sh` | 5 | 0.14 | DELETE HANDOFF-PROMPT and bump script; MOVE HANDOFF/PROJECT-STATUS history to `docs/history/` (D-010); KEEP next-cleanup (policy script reads it) |
| Dead workflows and doc: `ai-release-proof.yml`, `benchmark-caption-runtime.yml`, `diagnose-blackwell-runtime.yml`, `docs/ops/self-hosted-ci.md` | 4 | <0.1 | DELETE or retarget (D-015) |
| Source, tests, lock files, fonts (`DejaVuSans.ttf` 0.72), installer sources | rest | ~40 | KEEP |

Largest 25 tracked files (MiB) with disposition:
1 `sandbox-lab/scripts/lpm-sample-short.mp4` 3.67 conditional; 2 `docs/evidence/f1-ci-repair-2026-09-10/ci-third-cycle-evidence.zip` 2.56 remove; 3 `.../ci-second-cycle-evidence.zip` 2.40 remove; 4 `docs/openapi.json` 1.81 keep; 5 `docs/og.png` 1.59 remove; 6 `work/instrumented-harness/v2/accept9-gpu/arrival-index.jsonl` 0.96 remove; 7 `uv.lock` 0.85 keep; 8 `civiccast/records/fixtures/DejaVuSans.ttf` 0.72 keep; 9 `docs/evidence/soak-2026-09-09-beta5/blackwell-evidence.zip` 0.68 remove; 10 `CHANGELOG.md` 0.60 keep (could split by year); 11 `docs/API-REFERENCE.md` 0.45 keep; 12 `civiccast/egress/gst/engine.py` 0.44 keep; 13 `civiccast/egress/daemon.py` 0.37 keep; 14 `docs/USER-MANUAL.pdf` 0.34 keep; 15 `tests/egress/test_daemon.py` 0.33 keep; 16 `ops/beta10-oversight/reports/U25.md` 0.31 keep/summarize; 17 `civiccast/docsite/manual.json` 0.29 keep; 18 `installer/src-tauri/src/main.rs` 0.27 keep; 19 `native_service_registration.rs` 0.27 keep; 20 `docs/releases/evidence/v2.1.0-vm-01-installer-welcome.png` 0.26 remove; 21 `civiccast/installer/service.py` 0.25 keep; 22 `ops/.../reports/U59.md` 0.24 keep/summarize; 23 `work/release-beta8-word-replay/blackwell-final-word-replay-A.json` 0.23 remove; 24 `sandbox-lab/scripts/In-Sandbox-Report.ps1` 0.23 keep (consider splitting); 25 `docs/evidence/trackers/RESUME-STATE-log.md` 0.23 remove.

## What's working

- Link hygiene: scripted check of every relative link, image src and anchor in 30 docs (README, INSTALL, QUICKSTART, manual, SUPPORT, CAPABILITIES, ARCHITECTURE, FAQ, BRANCHES, tester/*, admin guides, both HTML pages) found 0 broken links and 0 missing anchors. The only dead file references are the backticked paths in D-007 and D-014.
- Settings and commands: 195 of 202 `CIVICCAST_*` names in the operator docs resolve in code; about 18 CLI commands and flags checked (doctor, installer plan/health-check/verify-package/beta-handoff, model download/import-offline/set-provider-key, cable ndi-check/ndi-plan, egress run/verify/trim-health/continuity-proof/caption-decode-proof, cert rotate) exist with the documented options. `/api/health`, `/api/hardware`, `/api/version`, `/operator/`, `/api/public/manual`, `/api/staff/records/disposition-queue`, `/api/staff/activitypub/delivery-retries` exist. UI labels the docs quote (Open operator console, Print kit, Stop downloading, Found locally, Show live captions on air, Station Profile, Run Meeting, Program Guide, Create support bundle, Do not broadcast yet, Source preview unavailable) exist in the apps; `CivicCast Operator Console.url` shortcut exists in the NSIS hook.
- Numbers: every beta.10 figure in README, QUICKSTART, manual, tester docs, landing page (40 of 41 checks, 16 of 16 windows, 50 changes, 0.033 s / 0.041 s, 13 discards, about 160 s, 34 hours, 1.94 LU) matches `docs/releases/v1.0.0-beta.10-verification.md`.
- Version/status wording for beta.10 (owner-held, unpublished) and beta.7 (published 2026-09-15), beta.8/9 (never published), beta.2 (never published) is consistent in README, FAQ, SUPPORT, BRANCHES, ARCHITECTURE, CAPABILITIES, INSTALL, QUICKSTART, ROADMAP, CHANGELOG, both HTML pages and the manual; code versions agree (`_version.py`, `_native_version.py`, installer `package.json`, `tauri.conf.json`, `Cargo.toml`, `docs/openapi.json` = 1.0.0-beta.10). Only exceptions: D-006 and the operator `package.json`.
- Claims discipline: no "production-ready", FCC/ADA/WCAG compliance, uptime, "free forever" or "Gate A passed for beta.10" claim anywhere in README, landing, INSTALL, QUICKSTART, FAQ, SUPPORT; EAS is explicitly "not certified"; Gate A is stated as not run for beta.10 in every surface that mentions it.
- Rendered manual artifacts are in sync: `USER-MANUAL.md` sha 1a670d4c... matches `docs/USER-MANUAL.render.json`, `civiccast/docsite/manual.render.json` and `manual.json`; PDF/DOCX hashes match.
- No secrets or private keys in tracked files (token, key and PEM patterns); no mojibake in the checked docs; no `LFS` objects; history pack is small (58.5 MiB).
- `docs/FILE-HYGIENE.md` and the new `.gitignore` block are sound in intent and already stop new scratch (except the `*.ts` defect, D-013).

## Not checked

- External URLs (GitHub release pages, actions runs, PR links): no network fetch performed.
- Bodies of `docs/spec/`, `docs/adr/`, `docs/ops/` runbooks (except self-hosted-ci), `docs/releases/` older records, `CHANGELOG.md` entries before beta.10, `docs/public/`, `docs/governance/`.
- `docs/USER-MANUAL.md` Sections B and C beyond the sampled lines (about 1730 lines; sampled 1-130, 800-1040, 1160-1370); PDF and DOCX body content; `docs/tester/lpm-beta-test-handoff.md` lines 60-410 only skimmed.
- Whether the beta.10 installer actually downloads components at install time (D-004 needs the owner/engineering answer); whether any test collects `ops/beta10-oversight/bin/test_*.py`.
- Visual rendering of the landing page (3D canvas, mobile); ports other than 8000 (no other port is named in the operator docs).
- Whether the per-file "unreferenced" estimate for `docs/releases/evidence/` (basename match, about 3.5 MB) holds file by file; do a per-file `git grep` before deleting.
