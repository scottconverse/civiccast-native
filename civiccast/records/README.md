# civiccast.records

v0.6 signed-record export module.

## Contract

- Fresh export requires a persisted, server-side approved summary and separately
  persisted approval metadata matching that summary ID. Missing/mismatched
  approval requires explicit authenticated clerk reapproval, not backfill.
- The staff route rejects missing or unapproved summaries before rendering.
- `SignedRecordExporter.export(...)` renders a veraPDF-validated PDF/A-3B
  signed-record artifact, attaches sourced-claim, provenance, approval, and
  timestamp sidecars, and returns signed-record metadata.
- The timestamp authority and signing authority are deterministic/local by
  default. Do not use this module to claim real TSA proof or legal-record status
  without a configured and verified external authority.
- Verification returns persisted record metadata when a record exists and a
  failed verification response for unknown record ids.
  Existing archived-record verification retains its artifact-digest and proof-
  structure meaning; it does not retroactively certify approval provenance.

## Persistence

`InMemoryRecordStore` supports tests and no-DB local runs.
`PostgresRecordStore` persists record exports, timestamp proof metadata,
artifact digests, PDF/A metadata, and artifact bytes using the v0.6 Alembic
migration tables.
