# CivicCast prioritized execution plan

Prepared for Scott Converse on October 25, 2026 (Mountain Time).

## Purpose and authority

Improve current user workflows first, then add features with the greatest practical benefit to prospective stations, municipal staff, and residents. This document records the prioritized recommendations, bounded implementation goals, and definitions of done. It does not claim that the work has been implemented or verified.

Scott's request that produced this file authorized saving the plan, not beginning implementation. A subsequent execution instruction defines the active scope. If Scott selects a batch or named goals, execute those and stop. If Scott explicitly authorizes the entire plan, execute all numbered goals serially; do not silently reduce the assignment to the first batch. Deferred ideas and excluded work remain excluded unless separately authorized. Publication, paid services, account creation, destructive changes, and operational interruptions must stay within the authority Scott actually supplies.

Recommended first assignment: **F1, F2, and F3**. Recommended first new-feature assignment after that: **N1**. The rest is ordered backlog, not a condition for shipping either assignment.

## Repository and evidence baseline

- Repository: <https://github.com/scottconverse/civiccast-native>
- Reviewed main: `933dd6571ab57ee5891f76c1148b79cb9c77bbc0`.
- Source permalink: <https://github.com/scottconverse/civiccast-native/tree/933dd6571ab57ee5891f76c1148b79cb9c77bbc0>
- Public release: <https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.20>
- Published Beta20 documentation-revision installer source: `2e19612467fda894d63e499580e4d7b5f029f5f2`. Main and the published installer are different identities.
- Read current repository `AGENTS.md`, `CLAUDE.md`, and `docs/handoff/CURRENT.md`; use `docs/handoff/BUILD-ASSETS.md` when packaging is actually in scope. Historical notes in those files may be superseded by later commits or explicit owner instructions.
- The assessment behind this plan read reports, source, and existing CI records. It ran no product tests, builds, installs, station changes, or release jobs. Source findings are not fresh installed-runtime reproductions.
- The Windows resource-classification correction and Brotli optional-import dependency correction are already merged at this baseline. Do not implement them again. Updating source does not by itself update an installed environment.

At execution start, identify the current branch, commit, working-tree changes, and relevant changes since this baseline. Reconcile only the selected goals. Preserve other agents' and Scott's work. Do not assume every old open PR represents missing functionality.

## Execution contract: mandatory boundaries

1. **Work toward named outcomes.** Every implementation step, check, audit, and rebuild must serve an active goal's definition of done, a concrete defect in that work, or required repository CI. If it serves none of those, skip it.
2. **One executor and one current candidate by default.** No automatic subagents, parallel competing builds, model changes, or new harnesses. Use existing tools and repository workflows.
3. **Use one existing current work record.** Record selected goals, candidate, passed evidence, unresolved defects, owned background jobs, and the next action there. Do not generate competing ledgers or repeatedly prepend conflicting current states.
4. **Check proportionally.** Prefer existing focused tests and one representative workflow for the changed behavior. Add a regression test when it protects a real corrected defect, not to mirror implementation or test prose. Run required CI. Informational/optional jobs do not become acceptance gates. Mutation testing remains excluded.
5. **Reuse unaffected evidence.** A documentation, test-fixture, or bookkeeping change does not invalidate unrelated product behavior or signed artifacts. Recheck only what a correction affects, plus required CI.
6. **Diagnose repeated failure.** After two failures for the same cause, explain the cause and change the approach before a third attempt. Do not repeatedly rerun until green or expand into a project-wide audit. A passed retry does not explain away an earlier failure.
7. **No invented validation campaigns.** No new soak duration, universal coverage target, arbitrary latency target, hardware requirement, five-lens review cycle, or new performance benchmark. Missing historical evidence is not an instruction to rerun everything.
8. **Protect operations and data.** Preserve the existing endurance run. Do not restart, reinstall, stress, or interrupt the station for convenience. Use existing isolated software tests and documented API simulators. Never request physical Roku or other hardware as a gate. Preserve recovery, legal holds, data, and required signing safeguards; no host reboot.
9. **No LFS transfers or spending through October 2026.** Do not fetch/pull/push LFS objects or purchase services. Preserve any newer owner restrictions. Use available assets and metadata; do not download large kits to answer a source question.
10. **Hide all consoles and helpers.** On this Windows machine use invisible ConPTY (`tty:true`, `login:false`). Children must use Hidden/CreateNoWindow. Preserve the hidden elevated-helper launcher and disabled GitHub CLI telemetry.
11. **Consolidate delivery.** Do not sign/build after each small fix. When an authorized package is needed, finish the selected package-affecting corrections first and produce one justified candidate. Rebuild only when a concrete change or required failure invalidates that candidate. Source-only work does not require an installer.
12. **Report states honestly.** Distinguish source implemented, focused checks passed, required CI passed, installed acceptance passed where applicable, and delivered. A blocker or partial workflow is incomplete. Do not claim field proof from mocks, compliance from automated checks, or delivery from an active process.
13. **Finish, then stop.** Review the affected work once for material defects; re-review necessary corrections only. Complete the authorized delivery, report evidence and limitations, and stop. Do not invent follow-up tasks. Respect a newer stop/pause; never pause an active goal without a current owner request.

For a background job, record ownership, start time, expected terminal result, next action, and cancellation route. Use the existing waiting mechanism; do not generate status-only continuation loops. An external blocker stays incomplete while independent authorized work proceeds.

## Current-software fixes, ranked

### F1 — Align captions with trimmed video

**Priority rationale:** Direct accessibility and viewing harm; also a prerequisite for reliable transcript time links. The publication path queues the original recording while the offline-caption job lacks trim information, consistent with the earlier reported misalignment.

**Goal:** Make caption production/publication use the same timeline as the packaged recording.

**Definition of done:**
- An existing isolated sample trimmed at the beginning/end has caption cues aligned with the published video.
- Cues outside the retained interval are omitted; boundary cues are handled consistently without negative timestamps or cues extending past the published interval.
- Normal untrimmed recordings retain their behavior, and republishing does not restore stale cues.
- The affected user documentation describes the actual behavior.

**Bounded verification:** Reproduce the trim mismatch on one small sample where practical; run the focused timeline/publication regression checks and inspect the corrected sample. No caption-engine rewrite or broad accuracy campaign.

**Source:** `civiccast/publish/router.py`, `civiccast/captions/vod_job.py`, and the existing packaging trim path.

### F2 — Make provider setup and YouTube publishing deliver what the UI says

**Priority rationale:** A configured Publish action that does not deliver output is a direct adoption obstacle and trust failure. Current setup credentials do not feed the real adapter configuration; the YouTube Live adapter creates/binds an event but does not send channel output.

**Goal:** Complete the existing provider configuration path and connect existing YouTube Live publishing to actual channel output.

**Definition of done:**
- Credentials saved through the supported setup UI are securely consumed by the intended existing provider adapter; normal users do not have to duplicate them manually in service environment variables.
- Mock/demonstration behavior is clearly identified and never presented as real delivery.
- YouTube Live uses the selected channel and valid event metadata, connects its output, and handles start/stop/failure without leaving falsely successful state.
- A configured event, attempted stream, and confirmed live destination are distinct states. Success is supported by actual delivery evidence when live delivery is claimed.
- Viewer links are watch links; ingest credentials are protected, not displayed as public viewing links or written into ordinary logs.
- Provider failure remains isolated from the local resident portal as intended.

**Bounded verification:** Focused configuration/adapter/output-lifecycle checks using existing fixtures and software receiver paths. If an authorized account is available, perform one bounded destination check. If account access is unavailable, record that external acceptance as incomplete; do not create accounts, spend money, or fake live proof. Do not rebuild unrelated publishing systems.

**Excluded:** Facebook, new providers, new scheduling features, and arbitrary changes to working Internet Archive/NAS behavior beyond the shared configuration correction.

**Sources:** `CAPABILITIES.md`, `civiccast/publish/service.py`, `civiccast/publish/providers.py`, `civiccast/platform/providers.py`, `civiccast/syndicate/youtube.py`, and existing setup credential storage.

### F3 — Correct remaining exposed dependency vulnerabilities

**Priority rationale:** Known vulnerable components undermine deployment confidence. Start exposure triage early; a reachable serious runtime vulnerability takes precedence over F1/F2. Scanner findings are not all equally exposed.

**Goal:** Resolve the remaining applicable advisories through compatible targeted corrections.

**Baseline:** Main security run `40169462304` fails Python and both portal dependency scans. The supplied review identifies filelock, pypdf, setuptools, virtualenv, Zod, Vitest/mocker, and Undici findings. Retrieve the current advisory identities rather than assuming this list or affected versions remain unchanged. Brotli is already corrected in source.

**Definition of done:**
- Each current applicable finding has a recorded affected dependency, runtime/development scope, and correction.
- Compatible targeted updates clear the relevant findings without newly suppressing advisories or weakening thresholds.
- Affected checks and required CI pass.
- The record states whether any installed/deployed environment requires an update; a merged lockfile is not described as an installed fix.
- If no compatible correction exists, the exact finding and blocker remain explicitly incomplete.

**Bounded verification:** Relevant lock consistency, affected behavior, and dependency scans. No blanket audit-fix, unrelated major upgrades, or general security audit. Existing informational scans remain informational; this named remediation goal does not silently change repository gate policy.

### F4 — Diagnose and correct the specific program-transition failure

**Priority rationale:** Transition failures can affect an entire channel, but available evidence does not establish a general outage or identify a single root cause.

**Goal:** Resolve the recorded held/deferred reload failure while preserving the currently airing program until a replacement is ready.

**Definition of done:**
- The recorded failing transition has a concrete diagnosis and correction, or decisive evidence that current code already resolves that exact failure.
- The focused scenario demonstrates safe replacement, failure handling, and continued outgoing playback while replacement is unready.
- Related old PRs are used only as relevant evidence; do not merge historical branches wholesale.
- An unreproduced/unexplained failure remains unresolved, not silently closed by a green retry.

**Bounded verification:** Existing isolated transition tests and the named failing scenario. Do not disturb the endurance station or begin a new open-ended soak.

### F5 — Sign installed executables during the next authorized packaging task

**Priority rationale:** Institutional IT deployment and user trust. The supplied review reports an unsigned installed launcher/uninstaller; signing the outer setup does not sign its contents.

**Goal:** Correct the signing order for the installed executables intended to carry Authenticode signatures.

**Definition of done:** The launcher and uninstaller are correctly signed in the package and retain valid expected signatures after isolated installation, without weakening existing pack/signature checks. Existing install/uninstall acceptance applicable to that package passes.

**Bounded verification:** Inspect the packaging/signing path and the actual resulting installed files in the next authorized package. Do not run a separate speculative installer build merely to prepare this change. Required signing access that is unavailable is a named blocker.

### F6 — Repair or explicitly withdraw the unusable standalone CG preview

**Priority rationale:** A broken preview wastes operator time and makes working channel graphics look broken. Scope is the separate CG stream, not all overlays or bulletin-board rendering.

**Goal:** Stop advertising a playable stream that references nonexistent segments.

**Definition of done:** Either the preview serves real available segments and plays, preferably by reusing an existing renderer/output path, or that unsupported preview is clearly unavailable in API/UI/help. The UI must not show a broken player as a functioning feature. Existing channel graphics remain intact.

**Bounded verification:** One focused manifest/segment check and affected preview workflow. Choose the smallest honest implementation; do not create a new graphics engine.

**Source:** `civiccast/cg/service.py`, `civiccast/cg/router.py`, and the consuming preview UI.

### F7 — Correct caption carryover at program boundaries

**Priority rationale:** Captions attributed to the wrong program can mislead viewers. Preventing that is more concrete than chasing an arbitrary speed target.

**Goal:** Keep queued/emitted caption cues associated with the correct program timeline across transitions.

**Definition of done:** A focused transition scenario shows no previous-program text displayed over the next program, while valid captions for the incoming program continue. Flush/cancel/rebase behavior is explicit and does not clear unrelated channels.

**Bounded verification:** One existing isolated program-transition/caption scenario and affected regression checks. Beta20's accepted approximately 8.8-second sample delay remains accepted. Reducing latency further requires a separately selected measurable target; it is not an additional gate for F7 or the released Beta20.

## Next-version features, ranked

These are separately deliverable goals. Dependencies do not authorize implementing unrelated lower-ranked features.

### N1 — Spoken-word search and interactive transcripts

**Priority rationale:** Highest broad resident/staff benefit from data CivicCast already generates. Find a short relevant discussion inside a long meeting without introducing another AI service.

**Goal:** Deliver the complete workflow: search words spoken in a published recording → read a matching passage → play the exact moment.

**Definition of done:**
- Published, reviewed transcript cues are searchable with useful excerpts and timestamped results using existing storage/search infrastructure where practical.
- Selecting a result seeks the correct published recording timeline, including a recording corrected under F1.
- The watch page offers an accessible, clickable transcript linked to playback.
- Caption corrections update results; withdrawal/unpublishing removes public access and search visibility. Existing publication/access restrictions apply to the text as well as video.
- Recordings without transcripts remain browsable and are honestly labeled; existing metadata search still works.

**Bounded verification:** One representative archive workflow covering search, seek, correction, and withdrawal; focused query/access-control/UI checks. No semantic chatbot, vector database, speaker identification, or topic-alert engine.

### N2 — Simplify installation and first successful setup

**Priority rationale:** Reduce the effort required to try CivicCast. Current instructions require PowerShell and about 100 GB of preparation space, with roughly 22 GB of models.

**Goal:** Provide a clear supported path from download to one working channel or published recording, exposing actual configuration/resource status.

**Definition of done:**
- The supported download/install entry point clearly identifies required components, preparation space, progress, and actionable failure recovery.
- Existing setup screens guide station identity, recovery, storage, source/channel, and provider configuration without requiring internal IDs or duplicate secret entry where the selected workflow can avoid it.
- A user can reach one functioning channel or published recording by following that path; connection readiness is checked against actual configured components.
- Preserve the complete offline kit and existing data-preserving upgrade behavior.

**Bounded verification:** One isolated first-use walkthrough and focused checks for changed setup behavior. The initial goal does not require a new installer architecture. Investigate selective model installation only enough to record a concrete feasibility decision; implementation of optional-model acquisition is a separate scope choice, not an automatic dependency of N2.

### N3 — Caption workbench and archive backlog management

**Priority rationale:** Improves the accuracy and staff workload behind CivicCast's local-caption value proposition before expanding its language claims.

**Goal:** Extend the existing review UI with caption status across recordings, bounded batch jobs, timing correction, and local vocabulary configuration.

**Definition of done:**
- Operators can identify recordings with missing, pending, or approved captions and queue a selected batch using the existing job system.
- Batch progress, failure, cancellation, and resume/retry are understandable; processing respects existing resource limits and does not automatically consume unlimited station capacity.
- Operators can correct cue timing as well as existing text; corrected cues publish on the right timeline.
- Local names/terms can be configured and demonstrably reach the supported transcription path. Do not claim every engine supports vocabulary if it does not.
- Publication status does not equate a completed inference job with human approval or perfect word accuracy.

**Bounded verification:** One small selected batch and one edit/publish workflow, plus focused persistence/timeline/configuration checks. No transcription-engine replacement, universal accuracy benchmark, or blanket accessibility certification.

### N4 — Embeddable playback and scheduled YouTube delivery

**Priority rationale:** Reach residents on existing municipal websites and channels, reducing the need for a second service.

**Goal:** Add a supported website embed and scheduled operation of the completed YouTube path from F2.

**Definition of done:**
- An operator can copy an embed for a live channel or published recording; it plays with available captions on a normal external website.
- Embedding respects publication/access restrictions, safe framing policy, and responsive keyboard-accessible playback.
- A scheduled meeting can create/update the intended YouTube event and start/stop output without duplicate events on ordinary retry.
- Destination failures are visible and do not disable local playback.

**Bounded verification:** One embed workflow and focused scheduled-provider lifecycle checks; use existing simulators and authorized external access only. Facebook and other platforms are deferred, not bundled prerequisites.

### N5 — Live agenda marking and usable time entry

**Priority rationale:** Saves clerk time now and provides reliable structure for later minutes without building a whole legislative-management system.

**Goal:** Let staff select a meeting/recording by name, enter `hh:mm:ss`, and mark the current agenda item during recording.

**Definition of done:** A user links an agenda without typing an internal asset ID, marks or corrects item times, and publishes chapters that seek the correct recording. The UI handles invalid/out-of-range times and late publication clearly. Draft agenda content remains private until publication.

**Bounded verification:** One meeting with several item markers, one corrected time, and resident playback of the resulting chapters. No motions/votes system, automatic chapter inference, or AI minutes in this goal.

### N6 — Daily station operation improvements

**Priority rationale:** Repeated operational time savings and clearer failure visibility retain station users better than niche integrations.

**Goal:** Deliver three bounded improvements using existing endpoints: consolidated channel confidence view, selected-asset metadata editing, and storage-cleanup review.

**Definition of done:**
- Operators see the current output/program and existing audio/caption health for each channel, with stale/unavailable status distinguished from healthy.
- Operators can select assets and apply supported common metadata edits with clear partial-failure reporting and existing permissions enforced.
- Storage review identifies usage and eligible cleanup candidates while respecting holds/retention. Destructive action stays within existing authorized deletion safeguards.

**Bounded verification:** Focused checks of displayed state, selected-record edits, and protected cleanup cases. No new NDI multiview engine, failover cluster, automatic retention purge, or hardware monitoring campaign.

### N7 — Selected additional languages and a public caption display

**Priority rationale:** Improves access for underserved residents. Move higher only when an actual prospective station identifies a concrete language need; model language counts are not product acceptance.

**Goal:** Extend recorded translation/review to a finite selected language set and provide a large-text phone/browser caption view.

**Definition of done:**
- The selected languages are explicitly recorded before implementation; translation, review, publication, and player selection work for each.
- The public caption display follows the selected public channel, supports readable text sizing and accessible navigation, and provides a QR/link entry route.
- Unavailable captions, unsupported languages, and interrupted input are honestly shown.
- Unreviewed translation is not presented as an approved official record.

**Bounded verification:** A small representative sample per selected language with qualified language review where needed, plus the display workflow. If the language set or appropriate review is unavailable, report that specific input need; do not substitute claims based on model metadata. Live translation is deferred until separately selected with an explicit quality/resource/latency target.

### N8 — Human-approved agenda-based draft minutes

**Priority rationale:** Potentially high value for clerks, but larger and more consequential than search or chapter marking. Depends on N1 and N5, or equivalent existing delivered behavior.

**Goal:** Draft discussion summaries by agenda item while preserving human control of motions, votes, and publication.

**Definition of done:**
- Discussion drafts cite transcript/video locations and can be corrected by staff.
- Motions and votes use structured, human-confirmed entries; AI guesses do not silently become official facts.
- Draft status is visible, human approval is required for publication, and export reflects the approved version.
- Source citations, edits, and approval history persist through the existing storage/records mechanisms.
- An unavailable or failed model produces an actionable error and leaves a usable manual workflow.

**Bounded verification:** One representative meeting with discussion, motion, vote, correction, approval, and export. Use the existing summary engine. No full parliamentary rules engine, autonomous certification, or guarantee of legal sufficiency.

## Accessibility claims and legal boundaries

Build useful accessibility workflows, not a blanket compliance promise. A transcript is not generally a substitute for synchronized captions. Automated accessibility checks alone do not establish full conformance, and audio-description requirements are distinct. Existing retention safeguards do not imply compliance with every jurisdiction's records law; do not import generic automatic-deletion schedules from the supplied strategic report.

At the assessment date, DOJ guidance lists April 26, 2027 for entities of 50,000 or more and April 26, 2028 for smaller entities and special districts. Recheck official guidance before publishing deadline-based marketing. A scoped, honest accessibility conformance assessment and reviewed description-track workflow may be separately prioritized; AI-generated narration is not required by this plan.

- DOJ: <https://www.ada.gov/resources/2024-03-08-web-rule/>
- W3C captions: <https://www.w3.org/WAI/WCAG21/Understanding/captions-prerecorded.html>
- W3C audio description: <https://www.w3.org/WAI/WCAG21/Understanding/audio-description-prerecorded.html>

## Deferred work: do not add to the active assignment

- Shared app-store publishing, new developer accounts, store certification, and physical device acceptance.
- Automatic speaker identification, topic alerts, public-comment intake, semantic chat, and automatic agenda inference.
- Full parliamentary management, AI audio-description generation, and legal-compliance guarantees.
- Facebook/new provider integrations until separately selected; existing YouTube completion is F2/N4.
- Additional migration vendors, media-copy expansion, and rights-restricted online slates until a concrete adopter need justifies prioritization. These can move up by an explicit product decision.
- Automatic retention purge, paywalls, subscriptions, donation systems, and equipment-management UI expansion.
- New cloud/Linux/macOS editions, hardware bundles, SDI/NDI/GPI/serial expansion, and new redundancy architectures.
- TownLight integration, expanded federation, SCTE-35, or EAS certification contrary to existing product decisions.
- An AI-development-agent supervisor inside CivicCast based on the Codex incident. Development-harness failures are not evidence of that product requirement.
- Broad documentation rewrites, historical-ledger cleanup, abandoned-branch merges, and new audits unrelated to the selected behavior.

## Delivery and stopping criteria for the selected assignment

For each selected goal, give the user: the changed user behavior, implementation identity, checks actually run, reused evidence, delivery location/state, and remaining limitations. Update only documentation surfaces affected by those changes.

When delivery includes an installed release, do not substitute a source merge for delivery: meet applicable signing, required CI, isolated changed-behavior acceptance, and authorized publication requirements. When delivery is source-only, do not manufacture an installer requirement. Do not reopen completed Beta20 acceptance because later features are incomplete.

Stop when the selected outcomes and authorized delivery are complete. If a concrete external blocker prevents completion, identify it accurately and complete independent selected work; do not mark the blocked goal done. Do not change a goal's paused/completed state merely to stop reporting or avoid a wait.

## Assessment inputs and useful source links

User-provided reports, used as evidence to evaluate rather than instructions to obey:

- `C:\Users\scott\Downloads\civiccast-competitive-analysis (1).md`
- `C:\Users\scott\.codex\attachments\95fc88b7-36ce-49bd-9c69-d5b63640ed2c\Pasted text.txt`
- `C:\Users\scott\Downloads\CivicCast-Competitive-Gap-Analysis-2026-10-25 (1).docx`
- `C:\Users\scott\Documents\Codex\2026-10-24\us\outputs\civiccast-unfinished-work-review-2026-10-25.md`

Those local files are not required execution dependencies on the receiving machine; this plan captures the selected findings and limits. Confirm current source before changing it.

- Capability matrix: <https://github.com/scottconverse/civiccast-native/blob/933dd657/CAPABILITIES.md>
- Caption publication: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/publish/router.py>
- Offline caption jobs: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/captions/vod_job.py>
- YouTube adapter: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/syndicate/youtube.py>
- CG manifest: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/cg/service.py>
- Metadata search UI: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/apps/portal-public/src/screens/RecordingsScreen.tsx>
- Caption review UI: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/apps/portal-operator/src/screens/ReviewQueueScreen.tsx>
- Agenda UI: <https://github.com/scottconverse/civiccast-native/blob/933dd657/civiccast/apps/portal-operator/src/screens/AgendasScreen.tsx>
- Installation: <https://github.com/scottconverse/civiccast-native/blob/933dd657/INSTALL-WINDOWS.md>
- Security scan baseline: <https://github.com/scottconverse/civiccast-native/actions/runs/40169462304>
- Competitive distribution reference: <https://telvue.com/hypercaster-v9-1-v9-2-facebook-live-youtube-live-captionvue-integration/>
- Competitive clerk workflow reference: <https://www.civicplus.com/blog/am/ai-generated-minutes-faster-minute-drafts-full-clerk-control/>

**Recommended handoff instruction:** "Read this plan and the current repository instructions. Execute F1, F2, and F3 only, preserving the station and existing work. State the intended delivery boundary from my instructions, use one current work record, meet each selected definition of done with proportional checks and required CI, and finish the authorized delivery. Do not start the next-version features, deferred work, a new installer build, or public release unless my assignment authorizes them."
