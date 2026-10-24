# Focused review checklist (optional guidance)

Owner-approved replacement, 2026-10-19. This file no longer mandates a five-lens
audit before every push, fixed report, post-push documentation cycle, or broader
audit when a narrow review finds an issue. `CLAUDE.md` defines the current workflow.
Required CI, repository review requirements, and task acceptance remain mandatory.

Use only the questions relevant to the actual change:

- Engineering: does the changed path work, including affected callers and contracts?
- UX: if a user workflow changed, are its relevant states clear and accessible?
- Tests: do the affected checks assert the changed behavior? Report skips honestly.
- Documentation: did any relied-upon instruction or claim become inaccurate?
- QA: do final behavior and completion claims match the evidence?

For a mechanical or bookkeeping change, inspect the diff and run one appropriate
check. Do not create a new harness, ledger, baseline suite, or independent review.
For a bug, reproduce the failure when practical, fix it, and run affected checks.
For migrations, verify the affected data contract, defaults, and recovery behavior.
For installed or public behavior, use actual relevant runtime evidence.

Preserve proof-anchor SHAs and run IDs as historical evidence. Record the current
candidate separately. A tracked file cannot contain its own final commit hash;
do not amend and push repeatedly just to update that reference. Update the existing
current status when needed, without rewriting all historical evidence for each push.

Report what changed, the checks run, and material limitations. Fix defects affecting
acceptance; defer unrelated improvements. Do not claim completion while required
outcomes remain unresolved. A clean diff or green source suite alone is not release
acceptance. Never weaken required checks or invent test/approval evidence.
