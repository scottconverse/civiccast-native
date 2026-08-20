# 5-lens self-audit (before every push)

This is the implementation-side counterpart to the verification-side audit
protocol at `docs/process/CIVICCAST_AUDIT_PROTOCOL.md`.
The verification protocol governs how an auditor (Codex, Scott independent
audit, audit-team) audits work that has already landed. This document
governs how the implementing agent audits its own work *before* a push,
so the verification turn finds less to fix.

Both Claude and Codex read this file. The rule body, the artifact-state
checklist, and the report format below are shared. The implementing-agent-
side discipline (chat-promise rejection) and the verifier-side discipline
(mandatory 10-section output) live in their respective files.

## The rule

**HARD RULE.** Before any `git push` that touches code, docs, or status
artifacts, run a hostile 5-lens self-audit on the actual diff. The audit
result is part of the report to Scott. No exceptions even when the change
"feels small" or "is just a typo fix."

## Why this rule exists

The failure mode it prevents: an implementation commit lands, CI is green,
the implementing agent declares "done," and then the auditor finds a list
of real drift items the implementing agent should have caught - wrong
endpoint paths, stale totals, contradictory sign-off blocks, overclaims,
"zero skips" without qualification, "Closed" without cited evidence, and
durable docs (README, CHANGELOG, HANDOFF, PR body, verification log)
drifting in parallel because they're treated as artifacts to update
sometimes rather than as state to maintain.

The drift isn't in features. It's in the surrounding durable artifacts
that should move with every code commit but don't because the implementing
agent treats them as artifacts instead of state.

## The five lenses

Each lens is *hostile* - assume the diff lies until evidence proves
otherwise.

1. **Engineering.** Read the diff. For every claim, name, path, version,
   or API in the changes: grep the actual code/config to verify it
   matches reality. If the diff names `/api/staff/uploads`, grep the
   router. If it names a SHA or run ID, verify it against `gh run view`.
   If it names a file, verify the file exists. If it names a function or
   symbol, verify it's exported. Hostile means: assume the diff lies
   until grep proves otherwise.

2. **UX.** For any user-visible string, message, label, or workflow
   change: read it cold as if you'd never seen the feature. Does it make
   sense to a first-time operator? Does it match the copy in adjacent
   screens (terminology, voice, formality)? Does an error path have a
   "Next step" line? Does a success path actually surface to the user
   before the dialog unmounts? Hostile means: assume the user is
   confused until the copy proves it doesn't confuse them.

3. **Tests.** For any logic / data-flow / public-interface change: is
   there a test? Does it run? Does it lock the behavior, or does it
   merely *exercise* the code path? Does it actually execute in CI, or
   does it skip? Hostile means: a green check is not a real assertion;
   "passes" is not "covers." Skip predicates lie by default - verify
   they don't apply.

4. **Docs.** For every code change: did the README move with it? The
   CHANGELOG? The HANDOFF (if applicable)? The PR body? The verification
   log? The finding ledger if there is one? The ADRs if an architectural
   decision changed? Hostile means: a doc that's silent about a change
   you just made is wrong, not "OK because the code is right."

5. **QA.** Read the final state, not the diff. Open the changed files as
   the next agent walking in cold. Are there contradictions across
   files? Does the README say one thing while the ops doc says another?
   Does the ledger top-totals row reconcile with the row count? Are
   status words used per the audit protocol (`Closed` / `Implemented` /
   `Open` / `Deferred by Scott` / `Blocked`, never `done` / `ready` /
   `taggable` / `shippable`)? Hostile means: assume drift until cross-
   file reading proves there is none.

## Artifact-state checklist

This is the specific drift that has bitten Scott most. Run every item
before push.

- [ ] Finding ledger top-totals row matches the actual row count by
      severity.
- [ ] Every `Closed` row cites: implementing SHA + verification (CI run
      ID or grep/pytest command) + docs touched.
- [ ] No row says `(this commit)` - replace with the actual SHA before
      pushing.
- [ ] PR body matches branch state: no stale `N of M` counts, no
      checkbox left unchecked for an item now Closed, no missing run
      IDs.
- [ ] CHANGELOG `[Unreleased]` or version block matches what shipped -
      no "All exit criteria met" if there was a carve-out, no stale test
      counts.
- [ ] HANDOFF.md (gitignored, project-local) names the current branch,
      current HEAD, current tag, current PR. Read it like a new agent
      walking in.
- [ ] Verification log on tag candidates: no "Ready to tag" claim
      without the tag-blocking gates Closed with proof.
- [ ] Status words: no `done`, `green`, `ready`, `taggable`, `shippable`,
      `complete` unless the release gate actually supports them.
- [ ] Working tree clean except intentional/declared uncommitted work
      (state it explicitly in the report).
- [ ] Cleanroom claims qualified: CI cleanroom skips are CI-only; local
      cleanroom skips are local-only; never collapse them.
- [ ] Whole-PR diff scope check: `git diff --name-status main..HEAD`
      must contain only the slice's intended file set. `git status
      --short` is not sufficient; sibling commits can land unrelated
      files.
- [ ] For every new SA model column with `server_default`, the default
      is a real SQL expression (`text("CURRENT_TIMESTAMP")` or
      equivalent), not a string literal (`"now()"`). Run an insert via
      the SA model path to confirm the default populates.
- [ ] For every new per-module Alembic migration directory, register
      the path in `alembic.ini`'s `version_locations` list. The static
      ini list is load-bearing; the `env.py` runtime helper is
      defense-in-depth only.
- [ ] For every claim that the cleanroom or a specific CI job ran a
      specific test path, grep that gate's runner script for the path
      before claiming it (e.g. `docker/run-cleanroom.sh` for cleanroom
      Gate 7).
- [ ] Non-ASCII scan on every new/modified durable doc: em-dashes
      (`-`), arrows (`-`/`->`), and section signs (`section`) must be
      ASCII. Run `grep -P '[^\x00-\x7F]'` (with `LC_ALL=C.UTF-8` on
      Windows Git Bash) before push.

## Post-push SHA-propagation step

Separate post-push pass, not optional. After `git push` succeeds:

1. Capture the new HEAD SHA (`git rev-parse HEAD`).
2. Wait for CI to complete on that SHA, then capture the new run IDs
   (`gh run list --branch <branch> --limit 8`).
3. Update PR body via `gh pr edit` so:
   - Every "Branch state on `<SHA>`" header names the new HEAD.
   - Every CI run ID link in the body matches `gh run list` for the new
     SHA. Old run IDs are stale and misleading even if they were green.
4. Update HANDOFF.md so:
   - `Current HEAD:` line matches the new SHA.
   - Last-updated date is today.
   - CI run IDs cited match the new SHA.
   - Status sentence accurately describes what's blocking (don't carry
     forward yesterday's blocker sentence).
5. If the finding ledger cites SHAs/run IDs as proof of Closed status,
   *decide explicitly* whether to update them to the new SHA or leave
   them as historical proof anchors. Either is defensible. What is NOT
   defensible: mixing without an explanation. Cite the policy in the
   ledger preamble.
6. Re-run the verification grep from the audit protocol against the new
   state, not the pre-push state.

The previous push's report cannot honestly say "Artifact-state: pass"
until this post-push pass completes.

## The proof-anchor vs release-target distinction

A tracked file cannot self-cite its own commit SHA: adding or amending
the file changes the SHA. Verification logs, ledgers, and release notes
must therefore distinguish:

- **Proof-anchor SHA** - the SHA whose tree contains the first
  green-CI-and-cleanroom evidence. Row-level proof citations pin here.
- **Release/tag target** - the final branch or merge commit after Scott
  confirms release. Tags go here, not at the proof anchor.

The proof anchor and the tag SHA are distinct concepts. Collapsing them
produces an infinite-regress loop because every amend-to-cite-the-new-
SHA commit moves the SHA.

## Report format

Include in the user-facing report after the push:

```
5-lens self-audit:
- Engineering: [pass | findings: ...]
- UX:          [pass | findings: ...]
- Tests:       [pass | findings: ...]
- Docs:        [pass | findings: ...]
- QA:          [pass | findings: ...]
Artifact-state: [pass | findings: ...]
```

If any lens has findings, fix before push. If after a push an
adversarial audit (Codex, Scott independent, audit-team) still finds
drift, that is direct evidence this rule isn't sticking; update or
strengthen it.

## Cross-references

- `docs/process/CIVICCAST_AUDIT_PROTOCOL.md` - the verification-side audit
  protocol. The mandatory output shape and verifier evidence-pass rules live
  there.
- Project-level (CivicCast `CLAUDE.md`) - names this file as the
  before-every-push discipline.
