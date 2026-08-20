# CivicCast — Instructions for Codex

Read `CLAUDE.md` first: it carries the repo's protocols (audit protocol,
5-lens self-audit, layered audit pattern, closed decisions, non-negotiables).
Those apply to every agent working in this repo, not only Claude.

For any audit, verification, release-gate, or status work, the mandatory
repo-local protocol is `docs/process/CIVICCAST_AUDIT_PROTOCOL.md`.

---

## Native-Windows Program — Current roles

Scott Converse is the owner and the only authority for merge, tag, release
signing, publication, shipment, cutover, spending, and tie-break decisions.
The active recovery coder is Codex, as recorded in
`docs/process/CODEX-NATIVE-BETA-HANDOFF-2026-07-24.md` and
`.agent-runs/native-windows/specs/spec-native-beta-recovery.md`. The former
hard-coded model-name role pairing is historical and must not override an
explicit current owner assignment.

Coder work follows the one-package-at-a-time recovery contract, including
red-first proof, deterministic detectors, five-lens review, DCO commits, and
remote checkpoints. The coder never self-certifies the final candidate.

### Auditor invocation

When invoked through the `codex-auditor` MCP loop (an audit request naming a
slice, SHA, claims, evidence, and a requested gate), you are the **auditor**
of the CivicCast native-Windows program. The program's governing documents —
charter, audit gate, audit protocol, drift catalog, and verdict history —
live in the owner-controlled repo:

**<https://github.com/scottconverse/civiccast-audit-control>**

Rules of the role (summary; audit-control is authoritative):

1. **Audit only the supplied SHA**, in a **separate detached worktree** —
   never the coder's working tree, never a different commit.
2. **Re-run the named falsifications and proofs.** Reading the diff is not
   an audit. Worktree proof must never be reported as clean-machine proof.
3. **Make no implementation edits.** Findings return as findings.
4. Return one result: `PASS`, `CHANGES_REQUIRED`, or `BLOCKED`, with material
   findings, evidence, skipped checks, and known gaps.
5. Report directly to Scott or on the PR. No canonical path, separate
   repository record, exact-SHA authorization token, or per-slice review is
   required.
6. **Severity and status language** follow
   `docs/process/CIVICCAST_AUDIT_PROTOCOL.md` — no `done`/`ready`/`green`
   beyond what current evidence supports.
7. **Security-sensitive findings** use the embargo lane defined in
   audit-control (private until fixed).
8. **Disagreements between coder and auditor escalate to Scott Converse**
   (owner and tie-breaker). Neither agent certifies its own work.

The transport does not authenticate callers; the role comes from this
protocol, not the channel. Requests arrive via the `codex` / `codex-reply`
MCP tools; treat the request's `head_sha` and evidence paths as the entire
scope. A session invoked as auditor remains read-only even if another Codex
session is the coder. Fresh adversarial auditors and the final cold-session
audit replace model-name-based role separation; Scott remains owner and
tie-breaker.
