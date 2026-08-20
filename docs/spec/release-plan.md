# CivicCast — Release Plan, 0.1 → 1.0

**Companion document to:** `CivicCastUnifiedSpec-v2.md`
**Purpose:** A solo-developer + autonomous-coding-agent release ladder, walking from empty repo to first public pilot. Each rung is a thin vertical slice that proves one capability and meets the verification gate before the next rung begins.
**Scope of this plan:** 0.1 through 1.0. Post-1.0 (pilot adoption, Mode B / CivicSuite federation, cable add-on, Phase 2+ governance) is a separate plan handled after 1.0 ships.

---

## Why this plan, not a team-sprint plan

A team sprint plan is built around capacity-shaped scarcity: who has how many points-worth of focus over a two-week window, accounting for PTO and meetings. That model assumes labor is the bottleneck. With one human director and Claude Code running autonomously on a 20x Max plan, labor is functionally unbounded. The bottlenecks are different:

1. **Verification rigor.** The CLAUDE.md layered audit pattern (per-commit careful-coding, per-checkpoint sanity sweep, per-rung audit-lite, per-release audit-team) is the real budget. A milestone is not done until the per-rung audit-lite is clean and the verification log is signed.
2. **Real-time elapsed.** Days and weeks of wall-clock time, governed by review cycles and how long agent runs take to converge on something that survives the verification gate.
3. **Order-of-operations correctness.** Each rung depends on the rung before it. Captions depend on a streaming origin. Summaries depend on captions. Three-tier publish depends on a finalized recording. Skipping rungs creates silent integration debt.

So the unit of planning is a **version increment** (0.1, 0.2, 0.3, …) not a sprint. Each version is one well-defined capability proof. Each version ends with the verification log signed off and the next version starts only then.

---

## Cross-cutting discipline (applies to every rung)

These do not get their own version number because they apply to all of them. They are the per-rung floor.

**Every version ships with documentation parity.** Inline comments accurate, USER-MANUAL.md updated for the user-visible behavior, CHANGELOG entry written, breaking changes flagged. Documentation is not a separate version. A version with code but no docs is not done.

**Every version ships with tests proportional to the surface introduced.** Unit tests for new logic, integration tests for new module boundaries, at least one manual-verified end-to-end walkthrough of the new capability across the affected states (loading, success-with-data, success-empty, error, partial). The test suite blind-spot section of the verification log names what the tests do *not* cover and how each gap was addressed.

**Every version applies the layered audit pattern** (CLAUDE.md). Per-commit careful-coding (5–10 min per non-trivial commit, template at `docs/templates/careful-coding.md`). Per-checkpoint sanity sweep (2 min, every 2–3 commits, template at `docs/templates/checkpoint.md`). Per-rung audit-lite at rung end (5 min, invokes the `audit-lite` skill, output landed in the verification log at `docs/templates/verification-log.md`). Per-release audit-team at the 1.0 boundary only (30–60 min, invokes the `audit-team` skill). The mid-rung overflow rule applies: every audit finding gets explicit dispatch by severity (Blocker stops rung, Critical only if it fits, Major queues to next rung, Minor/Nit collects in `next-cleanup.md`) — never silently folded.

**Every version is runnable end-to-end on the Tier 1 Streaming reference build.** No version produces shelfware. No version requires "we'll wire this up next sprint." If a capability isn't reachable from the operator UI by the end of the version, the version isn't done.

**Architecture decisions are baked in at the start** (see "Architecture decisions baked in" below). Other Open Decisions from the spec resolve at the latest rung that depends on them; none are allowed to drift past 1.0.

---

## Architecture decisions baked in

Two architectural decisions from the spec's Open Decisions list (§22) are resolved before rung 0.1 begins. Day-1 work includes recording the ADRs, not deliberating the choices.

**D3 — Messaging substrate: NATS JetStream.** Apache 2.0, single-binary install, sub-millisecond latency, persistent streams with consumer-group fan-out, clean clustering when Mode B eventually needs multi-host. Redis Streams was rejected for license posture (Redis 7.4+ went SSPL/RSAL for some uses; "we use Valkey because Redis went non-OSI" is a procurement smell municipal evaluators will flag). Postgres LISTEN/NOTIFY was rejected for capability (8KB payload limit, no durable replay, no consumer groups — the wrong tool for the broadcast event bus and the publish-pipeline coordination). Postgres LISTEN/NOTIFY is still used for low-volume "tell the UI a row changed" purposes, just not as the broadcast event bus. ADR 0001 records this in rung 0.1.

**D4 — Canonical Whisper runtime: faster-whisper.** MIT, Python-native via CTranslate2, in-process API that maps cleanly onto the stabilization layer, INT8 path well-tested on the Tier 1 Streaming reference hardware (NVIDIA RTX 4060). Whisper.cpp is registered as a future alternate but not shipped in v1.0. The captions module is designed against an internal runtime adapter interface from day one, so a community-contributed Whisper.cpp adapter — for embedded or edge use cases — slots in later without rewriting the module. ADR 0002 records this in rung 0.1; the runtime adapter interface lands as part of rung 0.5's design.

These decisions are not reopened during the 0.1 → 1.0 ladder. Any reconsideration is a post-1.0 question.

---

## The release ladder

### 0.1 — Foundation (~3–5 days real time)

**Proves:** the project can build, test, and ship anything at all.

**Scope:**
- `CivicCast/civiccast` umbrella repo created. License files, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, SUPPORT.md, README.md skeleton, GitHub issue/PR templates.
- Monorepo decisions resolved (workspace tool, package layout, docs build).
- CI green from day one: lint, type-check, unit-test scaffolding, accessibility scaffolding, docs PDF/DOCX render check.
- Hardware probe (`/api/hardware`) returns CPU/RAM/disk/GPU/VRAM. The `civiccast doctor` CLI prints the probe.
- Verification log template established.
- ADR 0001 (NATS JetStream as messaging substrate) and ADR 0002 (faster-whisper as canonical Whisper runtime) drafted and committed to `docs/adr/`. NATS server installed and reachable from the dev environment.

**Exit criteria:** `pip install civiccast && civiccast --version && civiccast doctor` succeeds on a clean Tier 1 Streaming machine. CI is green. The verification log is signed off.

**Risk:** This rung is deceptively easy to under-invest in. Cutting corners here costs 5x at every later rung. Spend the time.

---

### 0.2 — Streaming origin (~5–7 days real time)

**Proves:** a video file can be served as adaptive HLS to a public portal page.

**Scope:**
- `civiccast-stream` module: ffmpeg-based HLS packager, ABR ladder (1080p/720p/480p/240p), CDN upload (D16 resolves here — pick a default CDN).
- Public VOD portal Vite app with HLS.js player (or native HLS where supported), accessibility shell (WCAG 2.2 AA scaffolding via axe-core CI gate from this rung onward).
- Hard-coded test asset; no asset library, no schedule, no live, no AI.
- Embed widget API (basic).
- Broken-media regression suite seeded with 3–5 pathological assets; orchestrator falls back to slate cleanly.

**Exit criteria:** A test video plays on a publicly-reachable portal URL via the configured CDN. The page passes WCAG 2.2 AA on axe. The broken-media gate fails over to slate without crashing. Mobile and desktop renders verified.

**Risk:** CDN configuration is per-provider quirky. Pick one (D16) and don't try to abstract across all of them in this rung.

---

### 0.3 — Assets + scheduling (~5–7 days real time)

**Proves:** an operator can upload an asset and schedule it to publish at a specific time.

**Scope:**
- `civiccast-assets`: upload, ffprobe ingest, validation gate, trim, chapter editor (keyboard-driven, frame-step controls persisted to millisecond precision), mobile-friendly, metadata edit, retention placeholder.
- `civiccast-schedule`: premiere scheduling, embargoed-release scheduling, conflict detection at the database level (btree_gist exclusion constraint).
- Operator shell skeleton: top bar with "Streaming Now" indicator, left sidebar nav (only the 3 modules that exist so far), main pane, right inspector. Profile-aware navigation skeleton (§18.2a) — even if only Public Meetings profile exists yet.
- Asset state machine wired to the database with check constraints.

**Exit criteria (revised 2026-05-10 per audit-team v0.3.0 QA-002 + Scott independent audit Step 4):**
1. Operator uploads a file. ✓ (rung 0.3)
2. Operator schedules it for 5 minutes from now. ✓ (rung 0.3)
3. Operator-visible: scheduled item appears in the staff library + schedule UI with the conflicting-overlap rejection visible at the DB layer. ✓ (rung 0.3)
4. **Resident-visible: comes back, sees it on the portal.** ✗ ([rung 0.4](#04--live-source--recording-finalization-710-days-real-time)). v0.3 ships the data model + operator-side surface; the public portal asset directory + scheduled-items widget land at rung 0.4 alongside the packager that fills `manifest_url`. Until 0.4, residents see only the assets a future packager has produced; v0.3 ships none of those.
5. State machine transitions logged. Operator-visible (cancel endpoint, schedule UI list view); the immutable audit table per spec §13.4 lands at rung 0.4.
6. Conflict detection actually rejects overlapping schedule items at the DB layer. ✓ (rung 0.3 btree_gist EXCLUDE).

**Risk:** The trim/chapter editor on a phone is the hidden hard part. Don't claim mobile-first if the trim controls fail under one-thumb operation. (Outcome: v0.3 ships a 44px touch-target floor enforced in CI; verified.)

---

### 0.4 — Live source + recording finalization (~7–10 days real time)

**Proves:** an OBS / NDI / RTMP source produces a live portal stream that finalizes into a reviewable recording.

**Scope:**
- `civiccast-live`: RTMP, RTSP, NDI, SRT input adapters. Source-drop fallback to slate. Source switching during a broadcast.
- `civiccast-vod` recording-finalization path: live ends, recording becomes a queued asset, asset state advances to `recorded`.
- Operator UI: "Start Live Stream" / "End Live Stream" buttons, source switcher panel, on-air preview.
- Pre-flight checklist v1 (network, storage, AI runtime stub, live source, recording target, operator confirm). The syndication / IA / NAS pre-flight items appear as "not configured" placeholders.
- **Public-portal asset directory + "Coming up" widget.** Surfaces scheduled premieres and published recordings to residents on the public portal.
- **Trim metadata uses fractional seconds.** Migration `0010_fractional_asset_trim` widens `Asset.trim_in_seconds`/`trim_out_seconds` from `Integer` to `Numeric(10, 3)` so the API, operator editor, and packager honor sub-second trim points.

**Exit criteria:** OBS pushes RTMP to the station; portal shows the live stream within budget; operator ends the stream; recording appears in the asset library at state `recorded`. Source-drop test forces a slate fallback without operator intervention. Resident loads the public portal and sees both the upcoming-premieres widget and the directory of published recordings.

**Risk:** Latency budgets compound. If the HLS segment duration is too long, the broadcast feels broken even when it's working.

---

### 0.5 — Captions (~7–10 days real time)

**Proves:** the strategic wedge — Whisper-large-v3 INT8 streaming captions appear on the portal player and survive operator correction.

**Scope:**
- `civiccast-captions`: faster-whisper (per ADR 0002), Whisper-large-v3 INT8 default model. Stabilization layer (4-second window, 2-window-stable commit, no rewriting on screen).
- Internal runtime adapter interface (`civiccast.captions.runtime` protocol) defined so a future Whisper.cpp implementation can plug in without rewriting the module. Only the faster-whisper adapter ships in v1.0; the abstraction is the design discipline that protects against upstream-runtime risk later.
- Custom vocabulary support (per-channel files; initial-prompt context up to 224 tokens).
- WebVTT cue output committed to the bus and to the HLS stream as WebVTT segments.
- Operator review queue UI: cue list, low-confidence flagging, in-line caption editor, per-cue approve/edit/reject.
- `civiccast-translate` is *not* part of this rung; comes at 0.9.

**Exit criteria:** A 30-minute live test produces captions visible on the portal player within 4 seconds of speech. Operator corrects a misspelled name in the review queue post-broadcast. Captions never rewrite on screen during live (verified by recording the live caption stream and checking for retroactive edits).

**Risk:** The stabilization layer is the technical core. Get it wrong and captions either lag too much or rewrite mid-broadcast. Plan for 2 days of just iterating on the stabilization window logic.

---

### 0.6 — Summary + signed records (~7–10 days real time)

**Proves:** an AI summary of a meeting passes operator review and exports as a signed PDF/A legal record.

**Scope:**
- `civiccast-summary`: Gemma 4 E4B via Ollama, regex pre-extraction (motions, seconds, votes, roll-call tallies, dollar amounts), structured summary prompt, sourced-claim enforcement (every claim cites a transcript timestamp range or the summary is rejected and retried once), refusal on uncertainty.
- `civiccast-records`: PDF/A-3 export with embedded metadata (model provenance, audit-log fingerprint, operator approval, signature). Sigstore or RFC 3161 timestamp authority signing.
- Review queue surfaces sourced-claim hyperlinks that seek the inline transcript player.
- Optional companion: CSV transcript export with timestamps and confidence scores.

**Exit criteria:** A 1-hour test meeting produces an operator-approved summary in which every quantitative claim ties to a transcript timestamp, plus a downloadable signed PDF/A transcript that opens in a PDF/A-conformant viewer and verifies its embedded signature.

**Risk:** This is the highest-difficulty AI rung. Sourced-claim enforcement requires good prompting *and* a deterministic post-processor that fails closed when the LLM doesn't cite. Budget extra time. The PDF/A signing path is also fiddly — pick Sigstore or RFC 3161 (decide before this rung starts).

---

### 0.7 — Three-tier publish (~10–14 days real time)

**Proves:** one operator approval lands a recording on the canonical portal, the Internet Archive, the local NAS, and YouTube — independently and asynchronously, with the publish dashboard showing per-surface state.

**Scope:**
- `civiccast-syndicate`: RTMP fan-out (YouTube Live as primary), YouTube Data API VOD upload, per-target credential management against the OS credential store, retry/backoff, `syndication.completed` event.
- `civiccast-archive`: Internet Archive S3-compatible upload, item creation with metadata + WebVTT sidecars, hash verification post-upload. Local NAS archive via ZFS send or rsync, hash-comparison verify. D17 resolves here (IA partnership terms).
- Publish dashboard component (§18.3a) with the seven plain-language states. Canonical-vs-reach-vs-archive distinction enforced in UI.
- Pre-flight checklist v2: full syndication, IA, NAS health checks added.
- Audit log captures every publish event with per-surface URL.

**Exit criteria:** Operator clicks "Approve and Publish" once. Portal goes public within seconds. YouTube VOD URL appears in the dashboard within minutes. IA item URL verifies hash-match. Local NAS shows the file. Each surface's state is independently visible. A deliberately-failed YouTube credential surfaces as a degraded reach state without blocking portal/archive completion.

**Risk:** This is the hardest *integration* rung. Each external surface has its own quirks (YouTube's quota model, IA's eventual-consistency on item availability, NAS's permission edge cases). Budget extra time. Also: D17 must close *before* this rung lands — partnership posture affects credential management design.

---

### 0.8 — Subscribers + podcast (~7–10 days real time)

**Proves:** a publish triggers email/RSS notifications and a podcast episode appears in a public RSS feed.

**Scope:**
- `civiccast-subscribe`: email signup (double opt-in), RSS feed (per-channel and per-meeting-body), webhook notifications with HMAC payload signing. Per-subscriber encryption at rest. ActivityPub deferred to post-1.0 unless D22 says v1.0 (decide at 0.7 latest).
- `civiccast-podcast`: audio extraction, -16 LUFS loudness normalization, RSS feed with chapters, transcript link (to signed PDF/A), summary in show notes.
- Public subscription signup page on the portal (resident-facing, accessible, double-opt-in flow).
- Subscription privacy posture (§15.7) enforced: no third-party trackers, no remote-image tracking pixels, encrypted at rest.

**Exit criteria:** A test resident subscribes via email, confirms via the double-opt-in link, receives a notification when a test meeting publishes. RSS feed parses against `feedvalidator.org`. Podcast feed parses against Apple's podcast validator. Webhook notification delivers with valid HMAC.

**Risk:** Email deliverability is the boring-but-real risk. Sending email from a self-hosted civic-tech stack often hits spam filters. Decide whether to use a transactional email service (Postmark, SES, Mailgun) or roll SMTP — pick before this rung starts.

---

### 0.9 — Translation + accessibility hardening (~7–10 days real time)

**Proves:** captions translate to a second language and the entire UI passes WCAG 2.2 AA.

**Scope:**
- `civiccast-translate`: TranslateGemma 4B via Ollama, glossary engine with `§§NNNN§§` placeholder tokens, per-language WebVTT track output, latency budget under 800ms per cue at 95th percentile. MADLAD-400 alternate registered.
- Live caption translation to one second-language target (recommend `es` based on the docs site bilingual default).
- Full WCAG 2.2 AA pass on operator UI and public portal: zero axe violations on AA rules, color-contrast audit, keyboard navigation across every workflow, screen-reader pass on the review queue and publish dashboard, focus-state visibility.
- 21st CVAA / Section 508 captioning compliance documented in operator manual (§16.3a).

**Exit criteria:** Live test stream produces English + Spanish caption tracks selectable in the player. Axe-core CI gate is zero-violation across all pages. A keyboard-only run-through of the full operator workflow (upload → schedule → live → review → publish) succeeds. Screen-reader run-through with NVDA or VoiceOver lands without major issues.

**Risk:** Accessibility regressions hide in the boring places (form errors, modal focus, dynamic content announcements). Plan a full sweep, not a spot check.

---

### 0.10 — Installer + idle page + first-run E2E (~10–14 days real time)

**Proves:** a fresh Tier 1 Streaming machine can be brought up to "live broadcast → publish → archive" by following the user manual without project intervention.

**Scope:**
- `civiccast-installer`: 11-screen profile-driven wizard. Hardware probe + tier recommendation. Storage configuration. Profile-aware step 6 (only relevant publish targets shown). Operator account creation. Cloud fallback opt-in (off by default). Model download with hash verification. First-run health check including syndication / IA / NAS / podcast tests. "You are streaming" confirmation.
- `civiccast-cg`: between-streams idle page, emergency-notification overlay, cellular fallback for emergency push.
- Profile-specific quickstarts and "first useful broadcast" checklists in the user manual (per §17.1a adoption surfaces).
- Air-gapped offline bundle (`civiccast model download --offline-bundle`).

**Exit criteria:** A clean Linux machine, zero CivicCast packages installed. Run the documented install procedure. Configure Public Meetings profile. Run a 30-minute live test broadcast. Produce a published recording with portal + IA + YouTube + local NAS + podcast + signed transcript + subscriber notifications all green. Total time-to-first-broadcast under one workday for someone following the manual cold.

**Risk:** Installer is "the most-tested module per dollar of effort" per the spec. The only way to know it works is to do the fresh-machine cold install yourself, with the manual open, and not touch any code shortcuts. Budget for at least two cold-install attempts before declaring this rung done.

---

### 1.0 — Release readiness (~7–14 days real time)

**Proves:** the project is ready to be installed by people who are not Scott.

**Scope (no new features — only readiness):**
- AI quality benchmarks published with regression history (captions WER, translation BLEU+COMET, summary ROUGE-L + factual-correctness subset).
- Broken-media regression suite expanded to ≥30 sanitized real-world failure modes.
- Three-tier publish integration test category running nightly (§19.6).
- Soak test rig running nightly on a dedicated Tier 1 Streaming build, soak schedule per §19.3.
- All required documentation artifacts present and renderable (README.md, USER-MANUAL.md/.pdf/.docx, CHANGELOG.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, SUPPORT.md, LICENSE, LICENSE-CODE, LICENSE-DOCS).
- Sigstore-attested release artifacts (Python wheels, container image, .deb, .rpm, source tarballs, model bundle manifest). macOS `.pkg` support is beta for v1.0 and finalized after v1.0.
- Air-gapped offline bundle tested on a network-isolated machine.
- Foundation bylaws drafted; Steering Committee composition agreed (governance scaffolding per Phase 0 deliverables).
- Public-facing announcement page on `civiccast.org` (or holding domain) with the Public Meetings and Community Media profile landing pages.
- One internal end-to-end pilot deployment running on real hardware for at least 7 days continuous, including 2+ real or simulated meeting broadcasts that completed the full publish pipeline. Scott deferred this proof until after the 1.0 milestone on 2026-05-15, so v1.0 must not claim completed pilot, public-adoption, certified-integrator, or non-Scott production-deployment readiness.
- The Market Evidence & Validation Ledger (Appendix C) reviewed: every "Open validation item" either resolved or explicitly carried into the post-1.0 backlog with an owner and deadline.

**Audit gate (altitude 4 — audit-team).** Run the `audit-team` skill scoped to the v0.10 + 1.0-readiness diff range. Five-role parallel pass: Engineering / UX / Documentation / Tests / QA. Time budget: 30–60 minutes. Output: executive report + this-sprint punchlist + watchlist. The result feeds Calibration Gate 3 (above): clean → tag 1.0; open Blockers → fix and re-run audit-team scoped to fixes; open Criticals beyond ~7 calendar days → ship 0.11 instead.

This is the only rung that runs audit-team. Per-rung audit-lite still runs at the end of 1.0's own work, but the release gate is audit-team.

**Exit criteria:** 1.0 release tag signed and published. The release notes name every module's status and link the verification logs from 0.1 through 1.0 plus the audit-team executive report. A second person (not Scott) can install CivicCast on their own hardware by following the user manual and successfully complete a test broadcast. The release-ready announcement is drafted but not yet published — that's a post-1.0 marketing decision.

**Risk:** The temptation at this rung is to add "just one more feature." Don't. Every feature added at 1.0 reopens the verification gate for the whole stack. If something is missing, it's a 1.1 feature.

---

## Estimated total real-time elapsed

Summing the rung estimates: **77–107 days of real time**, or roughly **11–15 weeks**. Counting weekends as work-eligible time when the autonomous agent is running, this compresses meaningfully — call it **8–12 calendar weeks** as the planning range, with the upper end accounting for the verification gate slowing things down at 0.6, 0.7, and 0.10.

This is consistent with the spec's revised Phase 0 (months 0–4) → Phase 1 (months 4–10) calendar. The 1.0 release ladder lands inside Phase 0's tail and the early part of Phase 1.

---

## What 1.0 explicitly does NOT include

These items are real, important, and out of scope for the 0.1 → 1.0 plan. They have their own post-1.0 trajectories:

- **Mode B / CivicSuite federation** — Phase 2 in the spec. The `civiccast-civicclerk-bridge` module, the `civiccore` substrate dispatch, and the multi-stream support are post-1.0. The two-mode architecture exists in 1.0 (it has to, structurally) but only Mode A is exercised end-to-end.
- **Cable add-on (`civiccast-cable`)** — Phase 3+. SDI output, frame-accurate playout, ATSC A/85 / FCC Part 79 cable compliance, 24/7 channel programming. Funded separately when the PEG slice raises money.
- **Native OTT apps** — Web PWA ships in 1.0. Roku is Phase 4+ contingent on funding. iOS/Android/AppleTV/AndroidTV/FireTV are post-1.0 if they return at all.
- **Phase 1 pilot adoption count (5+ stations)** — pilot adoption is post-1.0 community work. The project-internal 7-day pilot was deliberately moved after the 1.0 milestone on 2026-05-15.
- **Foundation incorporation as 501(c)(3)** — Phase 2 in the spec. 1.0 ships under maintainer governance with bylaws drafted and SC composition agreed; incorporation comes later.
- **The CivicCast Network nonprofit** — paused per D20; post-1.0 question.
- **Per-state retention preset library at full scope** — D21 calls for top 10 states by adoption in v1.0 and the rest in v1.1; 1.0 ships with the v1.0 subset. The rest is post-1.0.

---

## Per-rung discipline reminders

These are the per-rung gates that turn a "feature ships" event into a "verification log signed off, version tagged" event. They are restated here because they are the actual budget on the project.

The layered audit pattern (CLAUDE.md) operates at four altitudes; each rung exercises altitudes 1–3, with altitude 4 reserved for the 1.0 release boundary.

| Altitude | Per-rung activity | Time budget | Output |
| :---- | :---- | :---- | :---- |
| 1. Per-commit careful-coding | Every non-trivial commit during the rung | 5–10 min/commit | No artifact; discipline check |
| 2. Per-checkpoint sanity sweep | Every 2–3 commits | 2 min/sweep | No artifact; discipline check |
| 3. Per-rung audit-lite | At rung end | 5 min | `docs/releases/v0.X.0-verification.md` |
| 4. Per-release audit-team | Only at 1.0 | 30–60 min | Audit-team executive report + punchlist |

The per-rung audit-lite produces a verification log scoped to the four lenses (engineering, tests, docs, runtime). Each lens gets ~75 seconds of structured reflection plus its findings. Findings dispatch by the overflow rule: Blocker stops the rung, Critical only if it fits the remaining time, Major queues to the next rung as P1, Minor/Nit collects in `next-cleanup.md`. Never silently folded.

When a Blocker or Critical is fixed mid-rung, run audit-lite **scoped to the changed files only** (~2 min). Never run an unscoped re-audit; that's the runaway cycle the layered pattern exists to prevent.

If the per-rung audit-lite cannot be completed in 5 minutes, the rung was too big — surface to the human director. If a finding's severity is unclear, surface to the human director. The discipline matters more than the classification.

This is the discipline that makes solo + autonomous-agent work credible at municipal-procurement-grade. Without it, the project ships fast and breaks in production. With it, the project ships slower and survives.

---

## Calibration gates

Three explicit go/no-go checkpoints in the ladder. None are optional.

### Gate 1 — After rung 0.4 (foundation through live capture)

**Trigger:** rung 0.4 verification log signed.

**Check:** actual real-time pace through 0.1–0.4 vs. the planned 20–30 days. Count calendar days from `v0.1.0` tag to `v0.4.0` tag.

**Decision rules:**

- If pace is within 30% of plan: continue with 0.5–1.0 unchanged.
- If pace is 30–50% over plan: trim scope from later rungs. Likely candidates: `civiccast-translate` (defer to v1.1), additional syndication targets beyond YouTube (defer), Roku reference app (already deferred to Phase 4+). Document the trim in this plan and in the spec's roadmap.
- If pace is over 50% over plan: stop, hold a real retrospective with the human director, and re-resize the remaining ladder before continuing.

**Artifact:** brief calibration note appended to `docs/releases/v0.4.0-verification.md` recording the decision.

### Gate 2 — After rung 0.10 (pre-1.0 retrospective)

**Trigger:** rung 0.10 verification log signed.

**Check:** full retrospective before tagging 1.0. The 0.10 audit-lite is the last per-rung audit before the 1.0 audit-team. Did the rung themes actually land?

**Decision rules:**

- If audit-lite at 0.10 surfaces a class of bug we thought was closed earlier (e.g., a regression in the publish pipeline that was supposed to be solid by 0.7), re-plan 1.0 around closing that class before tagging. Do not paper over it.
- If the per-state retention preset library, the IA partnership posture (D17), or the ActivityPub decision (D22) is still ambiguous, resolve them now. They cannot drift past 1.0.
- If `next-cleanup.md` has more than ~15 Minor/Nit findings, allocate cleanup time before 1.0. A messy 1.0 is worse than a delayed 1.0.

**Artifact:** `docs/releases/pre-1.0-retrospective.md` recording what landed, what slipped, what's deferred, what cleanup is required before tagging.

### Gate 3 — Before tagging 1.0 (post-audit-team go/no-go)

**Trigger:** audit-team has produced its report against the v0.10 + 1.0-readiness work.

**Check:** any unresolved Blocker or Critical from audit-team blocks 1.0. Period.

**Decision rules:**

- If audit-team is clean: tag `v1.0.0`. Sign release notes. Push.
- If audit-team has open Blockers: do not tag. Fix and re-run audit-team scoped to the fixes (not unscoped). Iterate until clean.
- If audit-team has open Criticals and they cannot be fixed within ~7 calendar days: hold and ship `v0.11.0` instead, with the Criticals listed in the release notes as known-issue-fixes-targeted-for-1.0. 1.0 should not ship with known Criticals; better to ship a clearly-named pre-release.
- If anything material in the spec or release plan is still ambiguous about 1.0 readiness — non-negotiables, archival path, three-tier publish behavior under load — hold.

**Artifact:** `docs/releases/v1.0.0-go-no-go.md` recording the decision and the audit-team executive summary.

---

## Decisions that resolve during the ladder

These are the Open Decisions from the spec (§22) that have to close at specific rungs. The rung listed is the latest the decision can be made without blocking work.

| ID | Decision | Resolves by rung |
| :--- | :--- | :--- |
| D6 | ZFS vs mdadm storage default | 0.7 |
| D16 | Default CDN provider | 0.2 |
| D17 | IA partnership posture (informal vs MOU; per-station vs project-level) | 0.7 |
| D18 | Podcast as own module vs sub-target of syndicate | 0.8 |
| D22 | ActivityPub in v1.0 vs v1.1 | 0.8 |
| D2, D5, D7, D8, D9, D11, D12, D13, D15, D19, D20, D21 | Various Phase-1+ decisions | post-1.0 |

D1 (Rust vs Go for cable-grade playout) and D14 (full loudness preset library) are closed at the spec level — both moved to the cable add-on doc. **D3 (messaging substrate: NATS JetStream) and D4 (Whisper runtime: faster-whisper) are resolved in this plan** per the "Architecture decisions baked in" section above; ADRs 0001 and 0002 land as part of rung 0.1.

---

## What to do right now (Sprint 0.1, day 1)

1. Write ADR 0001 (NATS JetStream as messaging substrate) and ADR 0002 (faster-whisper as canonical Whisper runtime) per the "Architecture decisions baked in" section. These are documentation tasks recording resolved decisions, not deliberations — a few hundred words each citing the constraints from the spec.
2. Create the `CivicCast` GitHub org and the `civiccast` umbrella repo. Push the license files, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, SUPPORT.md, README.md skeleton, and GitHub issue/PR templates from the spec's documentation non-negotiables list. Drop the two ADRs into `docs/adr/`.
3. Install `nats-server` in the dev environment; verify the `nats-py` client connects and a round-trip publish/subscribe works.
4. Stand up CI: lint, type-check, unit-test scaffolding (pytest), accessibility scaffolding (axe-core/playwright), docs PDF/DOCX render check.
5. Write the first verification log against this README/scaffolding work to establish the template. The verification log is a real artifact from rung 0.1 onward.
6. When 0.1's verification log is complete and signed, tag `v0.1.0` and start 0.2.

Everything else is downstream of that.

---

*End of release plan v0.1 → v1.0.*
