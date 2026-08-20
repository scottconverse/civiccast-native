# CivicCast Audit Protocol

Status: repo-local mandatory protocol
Applies to: audits, audit-fix work, release gates, verification reports,
merge/tag-readiness decisions, tester directives, and status reports for
CivicCast.

This protocol replaces older machine-local instructions that lived outside the
repository. A missing user-profile file must never block or weaken a CivicCast
audit. If another agent has a private copy, it may use that copy as extra
context, but this file is the stable repo-local rule.

## Required Inputs

Before reporting readiness or writing a directive, verify the current state from
the repo and artifacts, not memory or chat:

- `git status --short --branch`
- `git rev-parse HEAD`
- `git remote -v`
- current branch or PR identity, if applicable
- relevant gate logs, test logs, release notes, handoff docs, and artifact
  manifests
- working-tree diff for every file you mention

If a referenced artifact cannot be read, report it as missing. Do not infer a
pass from a filename, past conversation, or a stale summary.

## Evidence Rules

Every claim must name its evidence. Prefer direct artifacts:

- exact command and result
- path to the log or report
- commit SHA, tag, release, or run id
- artifact hash and size when release assets are involved
- screenshots or UI traces when behavior is visual
- redacted logs when secrets or credentials are involved

When proof is partial, say what it proves and what it does not prove. Do not
promote mocked, simulated, API-contract, software-lab, or local cleanroom proof
into LPM field proof.

## Status Language

Use precise status words:

- `Closed` only when the fix is implemented and verified by current evidence.
- `Open` when the issue is still present.
- `Blocked` when a required external condition prevents progress.
- `Deferred by Scott` only when Scott explicitly defers the item.
- `Implemented` when code exists but verification is not complete.

Do not use `ready`, `shippable`, `taggable`, `done`, or `green` unless the
current gate actually supports that claim and every required skip is accounted
for.

## Required Audit Sections

A broad CivicCast audit or release-gate report must include:

1. repo identity and working-tree state
2. scope of the audit
3. exact commands and artifacts read
4. severity rollup
5. findings ordered by severity
6. proof that passed
7. skipped, waived, or unrun checks
8. field-proof boundaries
9. source-control actions performed or not performed
10. plain-language conclusion

Narrow spot checks may be shorter only when Scott explicitly asks for a narrow
summary.

## Severity

- Blocker: cannot advance the requested gate.
- Critical: likely to break release claims, safety, security, data integrity, or
  required verification.
- Major: important product, UX, docs, test, or operability issue that should be
  fixed before advancing.
- Minor: lower-risk issue that should be cleaned up but does not block the
  current gate by itself.
- Nit: style or polish.

## Directive Requirements

Tester or agent directives must include:

- target branch, tag, commit, and artifact identity
- nonce or run id when applicable
- exact files to read or write
- steps to perform
- halt triggers
- evidence to collect
- acceptance criteria
- what may be claimed and what must not be claimed

## Redaction

Never paste secrets, passwords, private tokens, or raw credential material into
reports. Redact secret-bearing values and preserve enough structure to prove the
path was exercised.

## Final Check

Before sending a final readiness answer, reread the newest user request and make
sure the answer addresses that request, not an older gate or watcher state.
