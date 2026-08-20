# ADR 0016 - Egress canonical profile starts at 720p MPEG-TS

**Status:** Accepted
**Date:** 2026-06-05
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** E.1 - One file to one SRT sink, supervised; E.2 - Gapless continuity and loudness
**Related spec section:** Channel Egress Engine build plan, E.1/E.2 hard exit criteria and canonical profile requirements
**Supersedes:** None
**Superseded by:** None

---

## Context

The egress continuity strategy depends on every source reaching the persistent
encoder in one stable shape. If two adjacent programs have different
resolution, frame rate, codecs, GOP cadence, sample rate, or container shape,
FFmpeg or the downstream receiver may need to renegotiate at the boundary. That
is exactly the dropout risk the egress project is designed to avoid.

The code already carries a default `CanonicalProfile`: 1280x720, 30 fps,
H.264/libx264 video at 6000 kbps, GOP 60, AAC audio at 192 kbps, 48 kHz stereo,
and MPEG-TS output. The new `SourcePreparer` conforms source segments to that
profile before the concat plan reaches the persistent encoder.

This default is a starting egress profile, not a universal headend contract.
Longmont or another station may need a different bitrate, GOP, or resolution
based on its SRT appliance, transcoder, or cable handoff requirements. Like
loudness, the profile must remain configurable and the accepted deployment
profile must be recorded in evidence.

## Decision

CivicCast will use the existing 720p MPEG-TS `CanonicalProfile` as the E.1
default egress profile:

- Width/height: 1280x720
- Frame rate: 30 fps
- Video codec: libx264
- Video bitrate: 6000 kbps
- GOP size: 60 frames
- Audio codec: AAC
- Audio bitrate: 192 kbps
- Audio sample rate: 48000 Hz
- Audio channels: 2
- Container: MPEG-TS

The profile remains per-channel configurable through `EgressConfig`. E.1 and
E.2 proof artifacts must record the profile actually used for the handoff test.

## Alternatives considered

**Option A - Use the existing 720p MPEG-TS profile as the default.** This gives
the persistent encoder a stable, cable-friendly HD shape, matches the current
code defaults, and is practical for SRT/RTMP/TS handoff. This is the selected
option.

**Option B - Default to 1080p.** This may be appropriate for some stations, but
it raises bitrate and CPU cost before the single-channel continuity path has
completed E.2. It also risks over-sizing the first Longmont proof without a
headend requirement.

**Option C - Leave the profile unspecified until deployment.** This is flexible
but unsafe for implementation. The source preparer and persistent encoder need
a concrete default so tests, package metadata, and operator setup have a
deterministic baseline.

## Consequences

### Positive

- Source preparation, concat planning, FileSink proof, and SRT proof all share
  one explicit default shape.
- The default is good enough for E.1 without blocking on every possible station
  profile.
- Operators and testers can see the profile in `EgressConfig` instead of
  reverse-engineering FFmpeg arguments.

### Negative

- Some downstream systems may require profile overrides before acceptance.
- 720p/6000 kbps may be heavier than needed for some web-first RTMP targets.
- A single default can be mistaken for a compliance guarantee if release
  language is not precise.

### Risks

- A station may run the default profile when the headend expects different
  settings. Mitigation: E.1/E.2 evidence must record the accepted profile, and
  release notes must claim only the configured profile that was actually
  tested.
- Future code may add output-specific profile changes after preparation,
  reintroducing boundary renegotiation. Mitigation: `SourcePreparer` and
  `build_persistent_encoder_args` tests must keep the prepared source and
  persistent encoder contract aligned.

## Compliance

- `CanonicalProfile` remains the typed source of truth for default egress
  resolution, codec, bitrate, GOP, sample rate, channel count, and container.
- `SourcePreparer` must conform source segments to the configured profile before
  the persistent encoder consumes them.
- The daemon path used by `civiccast egress run` must wire the source preparer
  before writing the concat plan.
- E.1/E.2 tester evidence must record the configured profile used in the proof.
- Release language must say "configured egress profile" unless a specific
  downstream acceptance test has proven a named profile.

## References

- `civiccast/egress/models.py` - `CanonicalProfile` and `EgressConfig`.
- `civiccast/egress/preparer.py` - source conform path.
- `civiccast/egress/runtime.py` - persistent concat encoder arguments.
- `docs/spec/2.0/channel-egress-engine-build-plan.md`
- `docs/adr/0014-egress-loudness-target.md`
- `docs/adr/0015-egress-continuity-mechanism.md`

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
