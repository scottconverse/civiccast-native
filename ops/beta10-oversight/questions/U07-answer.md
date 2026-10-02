# Coordinator answer to questions\U07.md

Good stop - your analysis is correct and Option B is the right call. Decisions:

**Q1: Option B.** Keep the cheap volume-divergence check synchronous (refactor it into its own method that
`enforce_discovered` also calls, so there is one implementation) and return today's exact refusal on
divergence. Move ONLY discovery/enforcement to the background verdict. With no fresh verdict, return
`CaptionRetentionResult(ready=True, refusal_reason=None, requires_fallback_slate=False)`.
No type change (not Option C) in this unit. Instead, log ONE INFO line per start when the start proceeded
without a fresh verdict, e.g.
`"channel %s: caption retention verdict pending (none yet / stale %.0fs); start proceeds, divergence check passed; background sweep in flight=%s"`.

**Q2: yes** - freshness bound 180 s from verdict PUBLICATION, monotonic clock.
**Q3: yes** - the egress provider owns its background sweep when no tap worker exists: one daemon thread,
one verdict slot per process, at most one sweep in flight, re-arms on its own cadence (use the same 60 s
interval constant as the tap worker - import it rather than duplicating the number).
When the tap worker DOES exist (this lab station runs it inline), it is acceptable for the provider to keep
its own background sweep rather than wiring a new seam into the tap worker - but then say in the report how
many full sweeps per minute the process now runs in total (tap + provider) and whether they can overlap.
If they can overlap, serialize them (one lock around the heavy discovery) so the disk never gets two
concurrent full scans.
**Q4: yes** - on a background refusal verdict publish `state="storage-refused"` to the sidecar per channel
exactly as the synchronous path does today.

Also:
- The 9 failing `tests/captions/test_startup_diagnostics.py` tests (`_startup_sequence` missing) are
  pre-existing; do not fix them in this unit. Keep them failing identically and list them in the report.
- Proceed with the Red/Green list from the brief, plus: divergence is still refused synchronously
  (test must show the refusal returns without waiting for a blocked discovery).
- Then finish the unit exactly as the brief says (commits, suites, report incl. the chunk-accumulation answer).
