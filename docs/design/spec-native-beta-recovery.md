# CivicCast native-Windows beta recovery execution contract

**Decision state:** Owner-directed execution scope; technical amendments remain
subject to the owner gates named below.

**Owner:** Scott Converse

**Coder:** Claude (coder seat transferred from Codex by the owner,
2026-07-29 evening)

**Effective:** 2026-07-25

**Owner amendments:** 2026-07-29 — CPU-only operation is mandatory; hardware
acceleration is optional and cannot gate installation, captions, or beta
readiness. External hardware validation is outside this contract. Windows
Sandbox is the primary cleanroom; a persistent VM is used only for proof gaps
that Sandbox cannot faithfully establish.

**Owner amendments (2026-07-29 evening):** (1) Caption model contract is
adaptive-tier with a pinned floor — see WP1; the exact large-v3-only mandatory
contract is superseded. (2) Non-implementation preparation (test authorship,
documentation drafting, driver skeletons) may run in parallel with the active
implementation package; the one-active-package rule continues to govern
implementation work and tree writes. (3) The R7 tester lane operates under
controller requests recorded in `tester-handoff/native-caption-r7/controller/`.

## 1. Purpose and authority

This contract converts the complete inherited native-Windows scope into
bounded, remotely checkpointed work packages. It incorporates the lessons in
[`docs/process/CODEX-NATIVE-BETA-HANDOFF-2026-07-24.md`](../../../docs/process/CODEX-NATIVE-BETA-HANDOFF-2026-07-24.md)
and does not narrow the owner-approved v3 lifecycle specification.

Authority order for this recovery:

1. Scott Converse's explicit current instructions and decisions.
2. The owner-approved v3 lifecycle specification,
   [`spec-installer-lifecycle.md`](spec-installer-lifecycle.md).
3. The remaining owner-approved native-Windows execution specifications.
4. The 2026-07-24 handoff for verified inheritance and lessons learned.
5. This execution contract for sequencing and evidence.

If two authorities conflict, work stops only at the conflicting decision
boundary; all independent work continues. Nothing is removed because it is
difficult, expensive in engineering time, or requires more testing.
**Captions are legally required** and are a release-blocking product
capability.

## 2. Source-control boundary

- Preserve `agent/civiccast-recovery-2026-07-25` at
  `ccf75b58a81feda8769c91783453d8a335867b8b`.
- Build the candidate on
  `agent/civiccast-native-beta-candidate-2026-07-25`, starting from
  `35a4ab4e39a19e632aa6a25c3492cae6c4489283`.
- Reapply each archival recovery package without carrying its commit object.
- Every new commit is a Conventional Commit with a DCO `Signed-off-by` trailer.
- Disable automatic Git cryptographic commit signing for these recovery
  commits. Release and binary signing remain owner-gated.
- Never force-push, bypass a gate, merge, tag, publish, sign a release artifact,
  or ship.

## 3. Per-package advancement rule

Only one implementation package may be active. Before another begins, the
active package must have:

1. an explicit requirement and blast-radius trace;
2. a red test or falsification for each repaired defect;
3. focused green tests plus the relevant broader suite;
4. recorded randomized seed and deterministic-detector result;
5. mutation coverage for changed high-blast logic, with every survivor
   disposed;
6. engineering, UX, test, documentation, and QA self-audit findings reduced to
   zero;
7. a DCO-compliant, non-cryptographically-signed commit;
8. an ordinary push of that exact package commit to the candidate branch.

Evidence must record the source SHA, exact command, environment, exit status,
timestamp, and output or artifact hash. Evidence from a different SHA is
historical context, never current proof.

## 4. Work packages

### WP0 — Recovery governance and inventory

Deliver:

- exact 218-row inventory ledger and reconciliation;
- complete inherited handoff in the repository;
- this no-scope-loss package contract;
- a sub-300 MB bootstrap plan that preserves mandatory offline captions;
- correction of stale role, commit, signing, and release-policy statements.

Exit:

- inventory sets reconcile exactly to the archival recovery range;
- documentation/policy checks pass;
- five-lens review has zero required findings;
- DCO-clean remote checkpoint exists.

### WP1 — Native payload and legally required captions

Deliver:

- line-by-line WSL-versus-native installed/runtime inventory reconciliation;
- deterministic operator and public frontend builds with manifest coverage;
- captions runtime and an offline, pinned, license-screened model delivery path;
- CPU-only caption operation as the mandatory baseline via an
  **owner-approved adaptive tier contract (2026-07-29 evening amendment)**:
  a measured floor tier (`medium` or `large-v3-turbo`, selected from R7
  target-hardware evidence) is the mandatory CPU baseline that every station
  must satisfy; `large-v3` remains in the caption pack as the quality tier,
  auto-selected only when measured hardware capacity allows, with fail-safe
  fallback to the floor tier. Tier selection must be explicit, logged, and
  provable; hardware acceleration may improve performance but must never be
  required for startup, caption generation, or a passing beta proof;
  (basis: exact large-v3 CPU/int8 measured 17.2-20.0 s and distil 13.7 s
  against the 10-second gate on the R7 target — encoder-bound; see
  `tester-handoff/native-caption-r7/evidence/` and
  `.agent-runs/native-windows/wp1-caption-integrity/OWNER-DECISION-caption-adaptive-tier.md`)
- Cloudflare R2 and S3 CDN adapter dependencies;
- pinned, licensed PostgreSQL, FFmpeg, and TSDuck runtime closure;
- explicit proof that no beta feature silently depends on a local LLM;
- audio-tap to ASR to stabilized review row to `active.vtt` integration;
- CEA-708 insertion and emitted-stream decode-back proof;
- durable review audio evidence and API-enforced low-confidence review policy;
- measured three-channel performance on the supported CPU/RAM target with
  Windows Sandbox GPU virtualization disabled, with fail-closed overload
  behavior.

The product must not claim broadcast readiness when the required caption model,
caption egress, or decode-back proof is missing. No smaller model may silently
replace the owner-approved model contract: under the adaptive tier contract,
the approved contract is the floor tier plus the logged selection policy, and
any deviation from that selection policy — including silently serving a lower
tier than the hardware qualifies for — is a release-blocking defect. The
caption pack builder and verifier must carry per-tier file inventories (the
prior verifier hard-coded large-v3's inventory, which structurally blocked any
other tier; that defect is in scope for this package).

Exit:

- payload manifests are complete and reproducible;
- offline socket-denied ASR succeeds from the packaged runtime;
- three real channels produce review rows, active WebVTT, caption feed, and
  decoded CEA-708;
- randomized, pollution, mutation, lint, type, license, and package tests pass;
- five-lens review, DCO commit, and remote checkpoint are complete.

### WP2 — Installer, provisioning, repair, and lifecycle

Deliver every v4 D1-D7 requirement and all 17 lifecycle rows, including:

- separate product identity and update channel;
- pre-execution payload trust verification;
- real PostgreSQL, TSDuck, service, ACL, firewall, and registry
  provisioning;
- journaled upgrade, real incompatible-schema rollback, power-loss resume,
  rollback-failure halt, and recovery instructions;
- exact bidirectional uninstall inventory and verified eventual SCM removal;
- repair that detects and restores corruption in the installed application,
  version, selector, runtime, dependency, and caption trees;
- exact `%ProgramData%\CivicCast` preserve/purge safety;
- same-version repair, UAC-denial, partial-service, concurrent-start,
  reboot/logout, WSL coexistence, and selector cases;
- a complete fresh-Windows Sandbox lifecycle matrix, including restart-required
  flows inside the running sandbox;
- focused persistent-VM proof only for requirements Sandbox cannot faithfully
  establish, such as an ambiguous pre-login service boundary, multi-session
  upgrade chains, or account/policy isolation.

Exit:

- all 17 rows pass on the exact package SHA in the venues assigned by D7;
- negative controls prove the drivers and verifiers detect failure;
- no row is represented by a mock when the specification requires a real OS,
  database, service, reboot, or co-install boundary;
- focused and broad tests, five-lens review, DCO commit, and remote checkpoint
  are complete.

### WP3 — Stage 2 operator and resident workflow

Deliver:

- operator console, source/route/schedule control, caption review, system
  health, rehearsal, and failure recovery;
- resident portal anonymous access, schedule/program visibility, stream,
  caption and transcript download, and accessibility;
- correct public asset ownership and collision-free evidence paths;
- bounded review processing without per-cue process explosion;
- installed-payload, three-channel, restart, browser, mobile, and support-bundle
  proof.

Exit:

- first-run through three-channel operation is verified from the installed
  native product, not a development server;
- every required screen and public path has functional and accessibility proof;
- the installed-product journey covers install through first run, media ingest,
  schedule, rehearsal, three-channel operation, caption review and publication,
  recording/output verification, support collection, and uninstall;
- UI/UX proof includes keyboard-only operation, focus order, accessible names,
  loading/empty/error/partial states, browser-console review, responsive
  layouts, and captured screenshots plus Playwright traces;
- failure E2E covers network loss, damaged caption packs, service/worker
  termination, low disk, reboot interruption, and recovery;
- focused/broad tests, five-lens review, DCO commit, and remote checkpoint are
  complete.

### WP4 — Documentation and operator truth

Deliver:

- reconcile v3 spec, implementation plan, handoff, ADRs, native guides, install
  guides, recovery instructions, and release blockers;
- remove stale WSL/native ambiguity and claims contradicted by current code;
- document online and air-gapped installation, captions, repair, uninstall,
  failure recovery, and support collection;
- keep every readiness claim bound to exact current evidence.

Exit:

- documentation policy tests and visitor-grade walkthrough pass;
- all instructions are exercised against the installed candidate;
- five-lens review, DCO commit, and remote checkpoint are complete.

### WP5 — Frozen candidate proof and independent audit

After WP0-WP4 are remotely checkpointed, freeze one candidate commit and run:

- full test suite and recorded-seed randomized suite;
- pollution and order-dependence detector;
- diff-scoped mutation testing with survivor disposition;
- lint, formatting, type, policy, security, license, and dependency checks;
- two-workspace reproducible payload and bootstrap builds;
- online and air-gapped offline-caption proofs;
- live three-channel rehearsal and operator/public workflows;
- failure drills and the complete clean-Windows Sandbox lifecycle matrix;
- focused persistent-VM rows for any requirement Sandbox evidence cannot
  faithfully prove;
- a fresh independent review that did not author the implementation.

Material findings from that review must be fixed or explicitly dispositioned by
Scott. The review is reported with the candidate evidence; no canonical
audit-control record, exact verdict filename, or `AUDIT_PASS` token is required.

Physical DeckLink, production routing, station-driver, and other external
hardware behavior is outside this software candidate gate. The software gate
ends at the documented API/interface, contract tests, failure handling, and
honest readiness states for that hardware.

## 5. Final owner gate

The coder presents one exact candidate SHA with a requirement-to-evidence
matrix. Scott Converse alone decides whether to merge, sign, tag, publish, or
ship. A pushed candidate branch or independent review does not perform or imply
any of those owner actions.
