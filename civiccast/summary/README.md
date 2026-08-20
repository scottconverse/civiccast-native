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
- Transcript CSV export includes cue id, start/end seconds, formatted
  timestamps, cue text, confidence, and low-confidence flags.

## Persistence

`InMemorySummaryStore` supports tests and no-DB local runs.
`PostgresSummaryStore` persists summaries, sourced claims, approvals,
provenance, operator messages, and audit fingerprints using the v0.6 Alembic
migration tables.
