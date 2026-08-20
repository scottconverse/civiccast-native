# ADR 0015 - Egress continuity mechanism starts with single persistent concat encoder

**Status:** Accepted
**Date:** 2026-06-05
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** E.1 - One file to one SRT sink, supervised; E.2 - Gapless continuity and loudness
**Related spec section:** Channel Egress Engine build plan, Architecture Gate and E.2 hard exit criteria
**Supersedes:** None
**Superseded by:** None

---

## Context

The channel egress engine depends on one hard architectural question: can
CivicCast keep one encoder and one output connection alive while source
boundaries advance, or does it need a more expensive two-encoder software
switcher? The implementation plan calls this the budget and architecture gate
because the answer changes CPU cost, runtime complexity, and the amount of
software needed before multi-channel rollout.

The first proof harness in `scripts/egress-continuity-spike.py` tested the
cheapest desired strategy: one FFmpeg process reading a pre-conformed
concat-demuxer plan and keeping one output open across source boundaries. The
proof was deliberately scoped. It used FileSink and receiver-instrumented
loopback SRT on a Windows tester machine. It did not use a cable headend,
QAM modulator, SDI appliance, EAS path, CEA-708 caption decoder, or live
station network.

The clean Windows tester result at
`tester-handoff/v2.0.1/test-results/windows/20260605-085355-msi-egress-spike-f4f2114.md`
passed against work branch commit `f4f2114` and directive commit `b7c7884`.
The FileSink run and the loopback SRT run both reported `passed: true`,
`boundary_count: 5`, measured duration `3.155` seconds against an expected
`3.0` seconds, and receiver-side SRT metrics with return code `0` and duration
within tolerance.

## Decision

CivicCast will proceed into E.1 using the single persistent FFmpeg
concat-demuxer encoder strategy as the first implementation path.

This decision does not claim real headend validation. E.2 must still prove a
larger multi-program playlist on a real or representative SRT path before the
release language can say the continuity mechanism is broadly validated.

## Alternatives considered

**Option A - Single persistent encoder with concat-demuxer input.** One FFmpeg
process owns the output side for the whole channel while a concat plan feeds
pre-conformed sources through the same encoder. It is the cheapest and simplest
strategy, and the Windows tester proof shows it can preserve a short
FileSink and loopback SRT output across five boundaries. This is the selected
starting implementation path.

**Option B - Single persistent encoder with FIFO input.** One FFmpeg process
owns the output side while the supervisor feeds a named pipe or equivalent
input stream. This may still be useful if concat-demuxer limitations appear in
E.2, but it was not the first passing proof and carries more supervisor
responsibility around backpressure and writer lifecycle.

**Option C - Two encoders plus a software switcher.** Two encoder paths pre-roll
current and next sources, and a switcher cuts between them. This remains the
contingency if E.2 discovers discontinuities that the single-encoder approach
cannot solve. It was not selected now because it increases CPU cost and adds
another always-on switching component before the simpler path has failed.

## Consequences

### Positive

- E.1 can start with a bounded implementation: config, sink abstraction, daemon
  process, state, health, and a single persistent encoder path.
- The first implementation path matches the passing FileSink and loopback SRT
  harness instead of speculating from documentation alone.
- Option B remains available if the longer E.2 proof exposes a seam problem.

### Negative

- The first production path inherits concat-demuxer constraints and must keep
  every source conformed to a stable canonical profile before it reaches the
  encoder.
- Short loopback SRT proof is not enough to declare production-grade
  continuity across real headend equipment or station networks.
- SRT proof on Windows required explicit sender `linger=5` behavior and
  receiver option normalization; production code must keep protocol options
  reviewable and testable.

### Risks

- Engineers may overstate this ADR as headend validation. Mitigation: release
  language and docs must keep the FileSink/loopback boundary visible, and E.2
  must still run the representative SRT proof.
- The five-boundary spike may miss longer-run timestamp, drift, or downstream
  receiver behavior. Mitigation: E.2 requires at least 50 boundaries on a real
  or representative SRT path before broader claims.
- A future FFmpeg/libsrt version may differ in close/linger behavior.
  Mitigation: keep the SRT loopback proof in regression coverage and record
  FFmpeg version in external proof results.

## Compliance

- `civiccast.egress` implementation starts with a strategy boundary so a later
  switch to FIFO or two-encoder switching can be isolated.
- E.1 code must not claim headend validation from this ADR.
- E.2 evidence must include a multi-program SRT proof with at least 50
  boundaries before the continuity claim expands beyond the spike scope.
- Release notes must use the narrowest true wording: FileSink and loopback SRT
  proof passed on one Windows tester machine; real headend validation remains
  unproven until separately recorded.

## References

- `docs/spec/2.0/channel-egress-engine-build-plan.md`
- `scripts/egress-continuity-spike.py`
- `audit-lite-egress-srt-loopback-fix-2026-06-05.md`
- `tester-handoff/v2.0.1/test-results/windows/20260605-085355-msi-egress-spike-f4f2114.md`
- `docs/adr/0014-egress-loudness-target.md`

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
