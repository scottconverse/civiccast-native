# civiccast.summary

v0.6 Summary module for sourced meeting summaries.

## Contract

- Input source of truth is committed caption cue data.
- Every quantitative claim must cite one or more transcript timestamp ranges.
- Unsupported quantitative claims are rejected and retried once by the
  generation pipeline.
- If evidence still cannot support the claim, the summary is returned as
  `refused` with an operator-facing next step.
- Operator approval is persisted separately from the summary draft and gates
  signed-record export.
- Approval requires a pending or already-approved summary with at least one
  claim and timestamp-backed source ranges for every claim. Refused, rejected,
  and unsourced drafts cannot be approved. Signed-record export applies the
  same evidence check to existing approved data.
- Fresh export also requires separately persisted approval metadata whose
  summary ID matches the export. Approved status alone is insufficient. Orphan
  approved items show **Reapprove summary**, with export disabled until a clerk
  explicitly reviews the sources and approves through the authenticated route.
  No approver is manufactured or backfilled.
- The approval request accepts only `approval_note`; the verified staff bearer
  identity supplies the approver. Approval and export require `records_clerk`.
- Transcript CSV export includes cue id, start/end seconds, formatted
  timestamps, cue text, confidence, and low-confidence flags.

## Persistence

`InMemorySummaryStore` supports tests and no-DB local runs.
`PostgresSummaryStore` persists summaries, sourced claims, approvals,
provenance, operator messages, and audit fingerprints using the v0.6 Alembic
migration tables.

New generated claim IDs are scoped to their fresh summary ID, so regenerating
corrected cues cannot collide with a prior model-local ID such as `claim-1`.
Existing summaries, claim IDs, approvals and exported records are not rewritten.
A completed generation job must link a persisted draft; an insert conflict is
recoverable only when that exact draft is already stored. Other conflicts use the
normal bounded retry/failure state, not a successful completion.

## Review and export discovery

`GET /api/staff/summaries/review-items` still lists only pending and refused
items by default. `?include_approved=true` also includes approved summaries,
so the operator screen can refetch or reload without losing its export action.
Both stores support the same optional `include_approved` argument.
The opted-in response includes `approval_required_summary_ids` for approved
items with missing/mismatched approval. The legacy default response shape is
unchanged. Approval lookup failures remain errors, not invented absence.

The console waits for a successful, current role lookup before enabling
approval or export. After export, **Download PDF** retrieves the authenticated
artifact. **Verify record** checks the existing endpoint's artifact digest and
timestamp proof structure. A deterministic test timestamp is labelled as such;
this is not independent timestamp-authority trust-chain validation. Approval,
export, download, and verification failures have separate retry messages.
The displayed PDF SHA-256 is the final exported file's artifact digest, not the
timestamp-input digest. Older responses without that field say it is unavailable.
Action retries are disabled while any approval, export, download, or verification
request is pending, and become available again when that action completes.
The default deterministic timestamp authority is not an external trusted
timestamp service; configure a real authority separately where required.
Existing stored-record Verify retains its digest/proof-structure meaning; a
verified result does not retroactively certify human-approval provenance.
