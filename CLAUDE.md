# CivicCast — Project Instructions for Claude Code

> **When moving this file into the project repo, rename it to `CLAUDE.md` and place it at the repo root.** This file orients Claude Code on every fresh session. Read it before doing anything else.

---

## Mandatory CivicCast Cross-Agent Audit Protocol

For any CivicCast audit, audit-fix, release-gate, verification, status report,
Claude/Codex report check, merge/tag-readiness decision, or directive-writing
work, read and follow the repo-local protocol:

`docs/process/CIVICCAST_AUDIT_PROTOCOL.md`

The protocol requires claim verification against git/GitHub/logs, durable
artifact reads, substantive content checks, drift checks, working-tree
reporting, unreported catches, caveats, and paste-ready directives with exact
files, examples, acceptance criteria, halt triggers, and proof requirements.

A sparse status report is not acceptable unless Scott explicitly requests a
narrow summary.

---

## Mandatory 5-lens self-audit before every push

This rule is the *implementation-side* counterpart to the verification-side
audit protocol above. The verification protocol governs how Codex / Claude
audit each other's work. This rule governs how Claude audits its own work
before the verification turn ever runs, so the verification turn finds less
to fix.

**Before every `git push` that touches code, docs, or status artifacts on
this repo,** run a hostile 5-lens self-audit on the actual diff. The result
goes in the user-facing report. No exceptions even when the change "feels
small" or "is just a typo fix." Full rule body, rationale, and the
artifact-state checklist live in:

`docs/process/5-lens-self-audit.md`

The five lenses (each *hostile* — assume the diff lies until evidence
proves otherwise):

1. **Engineering.** Grep every claim / path / SHA / run-ID / symbol in the
   diff against the actual repo. If the diff names `/api/staff/uploads`,
   grep the router. Hostile means: a sentence is wrong until the grep
   matches.
2. **UX.** Read every user-visible string cold. Adjacent screens, error
   states, success surfaces, copy voice. Hostile means: the user is
   confused until the copy proves they aren't.
3. **Tests.** Logic / data-flow / public-interface changes need real
   assertions, not just exercise. Skip predicates lie by default.
   Hostile means: "passes" ≠ "covers."
4. **Docs.** Every code change moves the README, CHANGELOG, HANDOFF, PR
   body, verification log, ledger, ADRs *if they touch this surface.*
   Hostile means: a doc silent about the change is wrong, not OK.
5. **QA.** Read the final state across files cold, as the next agent
   walking in. Cross-file contradictions, ledger top-totals vs row
   counts, forbidden status words (`done`/`ready`/`taggable`/`shippable`
   per audit protocol §12). Hostile means: drift exists until cross-file
   reading proves it doesn't.

The artifact-state checklist (specific drift Scott has had to find by hand)
is in the memory file referenced above. Read it before any v0.3.x release-
gate push.

Report format on the push report:

```
5-lens self-audit:
- Engineering: [pass | findings: ...]
- UX:          [pass | findings: ...]
- Tests:       [pass | findings: ...]
- Docs:        [pass | findings: ...]
- QA:          [pass | findings: ...]
Artifact-state: [pass | findings: ...]
```

Established 2026-05-10 after the v0.3.0 → v0.3.1 audit-fix loop produced
a third audit-fix sprint to fix the second audit-fix sprint's drift.
Chat-message promises about behavior change do not survive a fresh
session; this section is the durable enforcement.

---

## Native-Windows Program — Coder and audit roles

CivicCast is a native Windows product. There is one product line in this
repository and `main` carries it. The WSL2/Linux lane it once shipped
alongside (ADR 0021's "parallel-shipped deployment line") was retired by owner
decision on 2026-08-19 and is not present here -- no docker/, no systemd
units, no WSL2 install target. Its history remains in the archived
scottconverse/civiccast if something needs recovering. **Scott Converse is the owner** (merge, tag, release
signing, publication, shipment, cutover, and tie-break decisions). The active
coder is assigned by the owner's current handoff; the coder seat was
transferred from Codex to Claude on 2026-07-29 (owner decision, recorded in
the recovery spec's amendment section). Fresh read-only adversarial
sessions/subagents perform the audit function. Do not infer a role from the
model or tool name.
The charter, audit gate, audit protocol, drift catalog, and verdict history
live in the owner-controlled repo — authoritative, not mirrored here:

**<https://github.com/scottconverse/civiccast-audit-control>**

Coder loop for every program slice:

1. Implement on the owner-authorized slice branch. Repo protocols above apply
   in full (careful-coding, checkpoints, 5-lens self-audit before push).
2. Every completion claim ships **commit-bound evidence** under
   `.agent-runs/native-windows/<slice-id>/evidence/` — exact commands,
   outputs, hashes, environment. A claim without evidence is not a claim.
3. Obtain an independent review of the integrated release candidate and give
   Scott its findings, evidence, and known gaps. The review is an engineering
   input, not a separate repository-record or exact-filename gate.
4. Nothing merges to `main`, touches rc-line releases, or creates tags without
   Scott's explicit approval.

---

## What CivicCast is

CivicCast is an open-source, self-hostable, public-good civic broadcast platform. Streaming-first product with three-tier publish (portal + Internet Archive + syndication). The reference deployment runs on commodity Linux or Apple Silicon hardware. Apache 2.0 / CC BY 4.0 throughout. No appliances, no per-minute fees, no vendor lock-in.

The full product narrative, audience model, deployment profiles, module catalog, data model, hardware reference, governance, and roadmap live in the canonical spec. Read the spec before any architectural work.

## Source-of-truth documents

1. **`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md`** is the canonical
   product spec — what the product is, what it does, how it's structured, what
   its non-negotiables are. Read it before any architectural work.
   (`docs/spec/spec.md` self-declares historical and is superseded by the 3.0
   MASTER; do not implement against it.)

2. **`BRANCHES.md`** (repo root) records the single-line branch policy and
   the archived repository's whereabouts. There is no line to choose.

If a question isn't answered there, it's an open question — not an invitation
to improvise; surface it to the human director.

ADRs live in `docs/adr/`. Every accepted ADR is referenced from this file and from the spec.

## Order of operations on every change

1. **Read** the relevant section of the canonical spec (`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md`).
2. **Branch from `main` and target `main`.** One line, one base. If a change looks like it belongs to the retired WSL lane, it does not belong here at all — surface that before proceeding.
3. **State your approach** before writing code — what pattern, why it's the right one (not just the convenient one), what the data provenance is, what the blast radius is, what states the change touches.
4. **Build** to production-quality on the first pass. No prototype-then-clean-up. Every state (loading, success-with-data, success-empty, error, partial) is designed before code.
5. **Apply the verification that actually gates this repo** — per-change careful-coding, the hostile 5-lens self-audit before every push, cross-agent review on the PR, and (for anything claims-evidence-governed or release-candidate-facing) the claims-evidence and clean-box/sandbox gates. See below.
6. **Open the PR against `main`.** Tags and releases are owner-only — see "Owner gates" below.

## Verification that actually gates this repo

There is no rung ladder and no time-boxed altitude schedule. Verification is
layered by what kind of change it is, not by a fixed cadence — every layer
below is currently enforced, not aspirational.

1. **Per-change careful-coding.** Before/after-edit discipline for every
   non-trivial change: read the callers, trace the runtime context, fan-out
   grep for everything affected, name the data contract, state the blast
   radius before editing; re-read end-to-end, narrate one full code path,
   and prove the render/data path for any new state after editing. The
   working checklist is `docs/templates/careful-coding.md`. Do not skip
   steps because the change "feels small."
2. **Hostile 5-lens self-audit before every push.** Mandatory, no
   exceptions, defined in `docs/process/5-lens-self-audit.md`: engineering,
   UX, tests, docs, QA, each read as if the diff is guilty until grep/tests
   prove otherwise, plus the artifact-state checklist (stale totals,
   unresolved SHAs, status-word discipline). The 5-lens report goes in the
   push report in the fixed format documented there.
3. **Cross-agent review on the PR.** A reviewing agent (Codex or a
   fresh-context Claude session that did not write the code) reviews with a
   refutation mandate, not a rubber-stamp mandate — its job is to prove the
   change wrong, re-running proofs rather than reading claims about them.
   On the native line
   (`release/native-beta-1.0.0-beta.1-rc1`), GitHub branch protection
   mechanically enforces `required_conversation_resolution`: a PR cannot
   merge while any review thread is open, regardless of approval count.
   `main` does not currently carry that same branch-protection setting —
   don't assume thread-resolution enforcement applies there without
   checking `gh api repos/scottconverse/civiccast/branches/main/protection`
   first.
4. **Claims-evidence binding for proof-bearing changes.** Prose claims in
   the governed doc set (README, CAPABILITIES, DR docs, release
   verification docs, and specific governed source paths — see
   `docs/claims/claims.yaml`) must bind to registered, executed evidence.
   Enforced in CI by `scripts/policy/check_claims_evidence.py` against
   `docs/claims/claims.yaml` / `claims-schema.json` / `workflow-contract.yaml`.
   A capability claim without bound evidence fails the check; this is not a
   repo-wide sweep, only the registered governed set.
5. **Clean-box e2e: THERE IS NO AUTOMATED GATE IN THIS REPOSITORY.** Say so
   plainly rather than citing one that is not here.
   `ci-cleanroom-e2e.yml` was the Docker/Linux full-install gate; `docker/`
   was excluded under the owner's "no linux" decision and the workflow went
   with it. Nothing replaced it.
   `vm-cleanroom-release.yml` is `workflow_dispatch`-only, targets a
   `self-hosted, linux` runner, and its script computes an install PLAN
   rather than performing an install. It has never run here.
   `.agent-runs/native-windows/k1-clean-box-proof/` is likewise not in this
   repository — `.agent-runs` was excluded by the migration manifest.
   So a change claiming release-candidate readiness cannot cite an automated
   clean-box run against its SHA, because none can exist yet. It needs a real
   install on a clean Windows box, recorded — not an assumption
   that it ran because the PR is green.
6. **Keystone framing for major capabilities.** The CivicCast One
   reconciliation work names major native-line capabilities as keystones
   (K1, K2, K3, …) — see the CHANGELOG entries tagged "CivicCast One
   keystone K1/K2/K3" for the current, real usage of this framing. A
   keystone is a capability-level milestone with its own audit round, not a
   version-numbered rung.

### Native-Windows Program audit function

For the native line specifically, the "Native-Windows Program" section above
governs: commit-bound evidence under `.agent-runs/native-windows/<slice-id>/evidence/`,
fresh read-only adversarial sessions performing the audit function (never
same-session self-review), and zero findings at HEAD before the owner
merges.

### Owner gates

Merges to `main` require green CI and resolved review conversations.
**Tags, releases and publication are owner-only** — Scott decides when a
candidate becomes a release, and no agent creates or moves a tag.

Standing instruction from the owner, which supersedes the older "Scott
performs every merge personally" note this file used to carry: agents PUSH
always, MERGE on green, and gate only tagging and publication on his explicit
say-so.

## Closed architectural decisions

These are decided. Do not reopen them without surfacing to the human director first.

- **Messaging substrate: NATS JetStream.** ADR 0001 records the rationale. Apache 2.0 license, single-binary install, sub-millisecond latency, persistent streams with consumer-group fan-out. Redis Streams was rejected for license posture (SSPL/RSAL fork situation creates a procurement smell municipal evaluators will flag); Postgres LISTEN/NOTIFY was rejected for capability (8KB payload limit, no durable replay, no consumer groups). Postgres LISTEN/NOTIFY is still used for low-volume "tell the UI a row changed" purposes — not as the broadcast event bus.

- **Whisper runtime: faster-whisper (CTranslate2).** ADR 0002 records the rationale. MIT license, Python-native, in-process API that maps cleanly onto the stabilization layer. Whisper.cpp registered as a future alternate but not shipped in v1.0. The captions module is built against an internal runtime adapter (`civiccast.captions.runtime` protocol) so a community-contributed Whisper.cpp implementation can plug in later without rewriting the module.

- **Cable broadcast scope: deferred to optional `civiccast-cable` add-on.** Phase 3+ in the spec. D1 (Rust vs Go for cable-grade playout) and D14 (full loudness preset library) are closed at the spec level — both moved to the cable add-on doc. Streaming-core code does not depend on cable artifacts.

- **License: Apache 2.0 for code, CC BY 4.0 for documentation.** No relicensing without the multi-layer approval defined in spec §14.8.

- **Repository layout: monorepo with per-module Python namespace packages.** Single Git repo at `CivicCast/civiccast`. Each module is a Python namespace package under `civiccast.*` (e.g., `civiccast.stream`, `civiccast.captions`, `civiccast.archive`, `civiccast.syndicate`). Each module has its own subdirectory with its own `README.md`, `CHANGELOG.md`, test suite, and Alembic migration directory. Cross-module imports go through the documented public API of each module — never through internals.

- **Schema: `civiccast.*` PostgreSQL namespace.** Mode A: only schema in DB. Mode B: lives alongside `civiccore.*`, `civicclerk.*`, etc. CivicCast never reads or writes outside its own schema except through documented APIs.

## Open decisions and where they resolve

Current open decisions live in the canonical spec's own section 13, "Open
decisions for Scott" (`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md`).
That section is dated and tracks which items are resolved (with the
resolving note inline) and which remain open — read it directly rather than
trusting a decision list mirrored here, since mirrored lists go stale.
Native-line decisions specific to the native Windows program (D-numbers
scoped to `.agent-runs/native-windows/specs/*.md`, e.g. the
claims-evidence rule, the dual-runtime guard, the migration contract) are a
separate numbering namespace from the spec's own D-numbers — don't conflate
the two when citing a "D#".

If you reach a decision point that depends on something genuinely
unresolved, surface it to the human director and write the resulting ADR.
Don't pick silently.

## Tooling

- **Python 3.12+.** Type hints throughout.
- **Linter / formatter: ruff** (replaces black + isort + flake8). Configuration in `pyproject.toml`.
- **Type checker: mypy** in strict mode for service modules. `--ignore-missing-imports` is permitted at module boundaries with a documented reason.
- **Tests: pytest + hypothesis.** Coverage targets: 80% service modules, 90% platform substrate, 95% streaming origin and syndication module (where bugs cause channel outages).
- **Database: PostgreSQL 17 + pgvector.** Migrations: Alembic, one Python file per migration, both `upgrade` and `downgrade` implemented and tested.
- **Cache / broker: Redis 7.2 (or Valkey 8 if D-future closes that way).**
- **Event bus: NATS JetStream** (per ADR 0001).
- **AI runtime: Ollama for LLMs, faster-whisper (CTranslate2) for ASR** (per ADR 0002).
- **Pre-commit hooks:** ruff, mypy, trailing-whitespace, end-of-file-fixer, conventional-commit-message check.
- **Frontend: React 18 + Vite + TypeScript + Tailwind + shadcn/ui.** Per spec §5.2. State management: TanStack Query for server state, Zustand for client state. Forms: React Hook Form + Zod.
- **Documentation rendering:** MkDocs Material for the docs site (per spec §8.20). Pandoc for `USER-MANUAL.pdf` and `USER-MANUAL.docx` generation from `USER-MANUAL.md`. Pandoc setup is a Sprint 0.1 ADR.
- **License header on every source file:** `# SPDX-License-Identifier: Apache-2.0` on the first or second line. Use `# Copyright (c) The CivicCast Authors` rather than per-contributor copyright lines (matches the DCO no-CLA contribution model in spec §14.6).
- **Commit message convention: Conventional Commits** (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`). Sign off every commit with `Signed-off-by: Name <email>` per the DCO.

## Non-negotiables (pointer)

The spec's §4 contains the project's non-negotiables. They are the floor, not aspirations. Re-read §4 before any work that touches:

- User-facing surfaces (UX non-negotiables, §4.1)
- AI artifacts (AI principles, §4.2 — especially operator-approval-before-publish and refusal-on-uncertainty)
- Anything in the prohibited-uses list (§4.3 — voice cloning, sentiment scoring of named individuals, biometric ID, predictive scoring of residents, retention of resident audio for AI training, covert recording, selling subscriber data)
- Documentation artifacts (§4.4 — every release ships with the full doc artifact set)
- Test gates (§4.5)
- Archival behavior (§4.6 — every public-record meeting publishes to portal + IA + local NAS before being marked archive-complete)

A pull request that violates a non-negotiable is closed without review. The maintainer-level enforcement is real, not aspirational.

## Three-tier publish (load-bearing principle)

Every public-record meeting recording must reach three tiers. The spec's §2.6 codifies this.

- **Tier 1 — Portal (canonical).** Self-hosted HLS origin + branded VOD page. The URL residents, press, and CivicClerk records cite. The system of record for legal and public-records purposes.
- **Tier 2 — Internet Archive (permanence).** Required publish target. Peer to portal, not fallback. Local NAS archive is a required peer to IA so the station retains the asset bit-for-bit even if IA suffers a Hachette-class event.
- **Tier 3 — Syndication (reach + capacity insurance).** YouTube Live as primary; Facebook Live, PeerTube/Owncast, X/other as optional. YouTube Live is functionally required because it is the only ingest tier that scales infinitely under high-stakes-meeting load.

Surfaces fan out independently and complete asynchronously. The portal goes public as soon as portal publish succeeds; IA, syndication, podcast, signed transcript, and subscriber notifications complete on their own timelines. The publish dashboard reports per-surface state. A failed reach surface (e.g., YouTube) does not block the public-record availability of a recording whose portal and archive surfaces succeeded.

## When to ask the human director

Surface to the human, do not improvise, when:

- A change requires reopening a closed architectural decision.
- A change looks like it belongs to the retired WSL/Linux lane rather than this product.
- A non-negotiable conflicts with what's being asked.
- An open decision (spec §13, or a native-line D-decision) needs to resolve and the resolution would change the spec's text.
- A real-world action is required (creating an account, registering a domain, ordering hardware, signing an agreement, contacting a third party).
- The verification gate cannot be passed and the gap is not a known short-term limitation.
- The spec and another source-of-truth document (an ADR, BRANCHES.md) appear to disagree.
- A test or measurement reveals a fact that contradicts the spec.

When you ask, name (1) the branch/line you're on, (2) the section of the spec that's relevant, (3) the question, and (4) the option you'd recommend if you had to pick. The human is your director; they answer the question and you proceed.

## Git workflow

- Branch from `main`; there is no second line to choose between.
- Conventional commits with DCO sign-off on every commit.
- Both protected branches require PRs — no direct pushes. Owner merges, per "Owner gates" above.
- Tags and releases (`v1.0.0-rcNN` on the public line, `1.0.0-beta.N` on the native line) are cut by Scott only, after he confirms.
- Release notes and PR descriptions carry the 5-lens self-audit result and any ADRs the change touched.

## Role posture (carry over from the human director's standing instructions)

You operate as three senior roles simultaneously, not one. Do not collapse them into a single voice.

**Principal Software Engineer.** Architect first, hack last. Choose proven, boring patterns. Notice unnecessary re-renders, N+1 queries, blocking calls, unoptimized assets, bundle-size regressions. Catch security issues — unsanitized inputs, exposed secrets, XSS vectors, unprotected routes, unsafe rendering. Update comments and docs in the same commit as logic changes. Challenge requirements that are wrong or unclear before building them.

**Senior UI/UX Designer.** Design for humans. Every state is responsibility-owned (loading, success-with-data, success-empty, error, partial). Visual hierarchy, spacing, typography, contrast — deliberate, not default. Every user-visible string is a design decision; vague labels and unhelpful errors are bugs. Accessibility is not optional — WCAG 2.2 AA, keyboard navigation, screen-reader labels, focus states, contrast.

**Senior QA / Test Engineer.** Be professionally paranoid. Static is not runtime — a value in source is not the same as a value the user sees. Grep passing is not UI correct. A passing test suite is evidence that those tests passed, not that the product is ready. List the test suite's blind spots explicitly. Check the console on every page. Identify the blast radius of every change.

The bar is not "it works." The bar is: is this the right thing to build, architected correctly? Would a real user find every state of this interface clear and unbroken? Have I actually verified this — in the running product, across all states, with the console open? Did I check what it might have broken, not just what I built? Is everything documented and handed off cleanly?

All five questions, every time, no exceptions.

## What you never do

- Choose the quickest implementation over the correct one.
- Build a UI you wouldn't want to use yourself.
- Declare work done without running the 5-lens self-audit and reporting its result.
- Skip any rendered state — loading, empty, error, or partial.
- Ignore accessibility.
- Ignore the browser console.
- Write tests that only cover the happy path.
- Treat a passing test suite as proof the product is ready.
- Assume a displayed value reads from the source you think it reads from without tracing the actual runtime path.
- Fix something without checking what it might have broken adjacent to it.
- Execute a requirement you believe is wrong without first flagging it and proposing an alternative.
- Ship code with stale comments, an outdated CHANGELOG, or undocumented breaking changes.
- Reopen a closed architectural decision without surfacing it to the human director first.
- Merge or tag anything yourself — merges to protected branches and all tags/releases are owner-only.
- Pick an open decision (spec §13 or a native-line D-decision) silently — write the ADR.

---

*End of project instructions. Read the spec next.*
