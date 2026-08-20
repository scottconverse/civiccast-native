# ADR 0014 - Egress loudness target is configurable per channel

**Status:** Accepted
**Date:** 2026-06-04
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** E.1 - Channel egress spike and first SRT handoff
**Related spec section:** Channel Egress Engine implementation plan, Section 13 build ladder; CivicCast unified spec Section 16.2a streaming loudness
**Supersedes:** None
**Superseded by:** None

---

## Context

CivicCast already has a streaming loudness path. The active unified spec names
a streaming target of `-16 LUFS` for OTT-typical output, configurable per
channel. The channel egress engine is a different output surface: it will emit a
continuous IP/SRT or RTMP handoff that may be accepted by a cable headend or a
headend-adjacent appliance.

Those two worlds can have different expectations. Web streaming and podcast
workflows commonly target louder program audio than cable/broadcast workflows.
Cable carriage and ATSC A/85 practice commonly point toward `-24 LUFS`, while
the existing CivicCast streaming path is grounded in `-16 LUFS`.

The egress implementation cannot safely hard-code either number. Longmont or
any other station may need a target dictated by the specific headend, appliance,
contract, or operator acceptance test. This must be decided during the E.1
handoff proof, not guessed in the package model.

## Decision

The egress engine will make loudness target and tolerance configurable per
channel/output. The implementation may default to the verified existing
streaming target until a station-specific egress target is configured, but E.1
must explicitly confirm the deployment target with the headend or downstream
handoff owner before release claims are made.

The `-16 LUFS` versus `-24 LUFS` fork is a tracked deployment decision, not an
implicit constant.

## Alternatives considered

**Option A - Hard-code -16 LUFS for all egress.** This matches the existing
streaming path and is simple to implement. It risks handing a cable operator a
feed that is too hot for their loudness expectations.

**Option B - Hard-code -24 LUFS for all egress.** This matches common
cable/broadcast convention and may be correct for a headend handoff. It risks
surprising stations that use egress for web-first or RTMP-first delivery and
expect the existing CivicCast streaming loudness target.

**Option C - Configure target and tolerance per channel/output.** This adds a
small configuration burden, but it matches the product reality: egress can feed
different downstream systems with different acceptance requirements. This is
the selected option.

## Consequences

### Positive

- Egress can support both web-style and cable-style handoffs without code
  changes.
- E.1 can record the actual Longmont/headend target instead of baking in a
  guess.
- Release notes can make a precise claim: CivicCast emitted within the
  configured target, not within a universal target that may not exist.

### Negative

- Operators and integrators must know or obtain the correct target for the
  downstream handoff.
- Tests must cover at least the default target and an override target.
- Documentation must explain that loudness target is a station/headend
  acceptance setting, not a cosmetic preference.

### Risks

- A station may leave the default in place when the headend expects a different
  target. Mitigation: E.1 handoff proof must record the accepted target and the
  System Health egress UI should surface the configured target clearly.
- Engineers may describe egress as compliant with ATSC A/85 without a
  headend-specific proof. Mitigation: release language must say "within the
  configured loudness target" unless an external compliance proof exists.

## Compliance

- Egress models must expose `loudness_target_lufs` and
  `loudness_tolerance_lufs` as configuration, not module constants.
- Source preparation must pass the configured values into
  `check_streaming_loudness(...)` or the egress-specific loudness gate.
- E.1 evidence must record the configured target used for the handoff proof.
- E.2/E.4 evidence must measure emitted loudness against the configured target.
- Any release or operator-facing claim must distinguish "configured loudness
  target passed" from "broadcast/cable compliance certified."

## References

- `docs/spec/spec.md` - streaming loudness target language.
- `civiccast/stream/loudness.py` - existing loudness gate.
- `docs/spec/2.0/channel-egress-engine-build-plan.md` - egress build ladder and
  exit criteria.
- ATSC A/85 and CALM Act context for cable/broadcast loudness expectations.

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
