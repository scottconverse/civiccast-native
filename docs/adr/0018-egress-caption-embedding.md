# ADR 0018 - Egress captions stay not-verified until emitted-stream decode-back

**Status:** Accepted
**Date:** 2026-06-05
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** E.4 - Captions, full UI, telemetry, additional sinks, soak
**Related spec section:** Channel Egress Engine build plan, Sections 11.3, 13.2, and 18 required ADRs
**Supersedes:** None
**Superseded by:** None

---

## Context

CivicCast already has caption generation, review, and HLS sidecar caption
surfaces. Channel egress is a different surface: it emits an MPEG-TS-oriented
linear handoff for SRT, RTMP, LocalTS, or FileSink. A caption track that exists
elsewhere in CivicCast does not prove captions are present in the emitted
linear stream.

The egress build plan deliberately separates a caption interface from a caption
claim. `caption_embed.py` provides a pass-through default and a decode-back
proof function. The operator UI and API expose `caption_status`, which must
remain `not-verified` unless a real emitted stream is decoded and the expected
cues are found with acceptable timing.

The unresolved implementation fork is whether the eventual production path
embeds CEA-708-style caption data into the stream, muxes sidecar captions for
handoff cases that accept sidecars, or uses a station-specific downstream
encoder to handle the final caption embedding. The release must not claim any
of those as working until E.4 proves the emitted result.

## Decision

CivicCast will keep egress caption embedding as a declared boundary with an
honest non-claim until E.4 decode-back proof passes. The default embedder is
pass-through and reports `not-verified`.

The first shippable caption claim requires emitted-stream decode-back: the test
or proof must decode the actual egress output, compare it with expected cues,
and only then allow `caption_status` to become `on` for that output under test.

For implementation planning, CEA-708 ancillary-data embedding is the preferred
target for linear/cable-style handoff, because it puts captions into the
emitted stream. Sidecar caption muxing remains allowed for sinks or downstream
systems that explicitly accept a sidecar handoff, but sidecar availability must
not be described as embedded linear captions.

## Alternatives considered

**Option A - Claim captions from existing CivicCast caption sidecars.** This is
tempting because caption data already exists elsewhere in the product. It is
rejected for egress because it proves the authoring/review surface, not the
emitted SRT/RTMP/TS stream.

**Option B - Keep captions pass-through and never claim egress captions.** This
is honest and safe, but it leaves a major release capability unfinished. It is
acceptable as an interim state only.

**Option C - Implement CEA-708-style stream embedding and require decode-back
before claiming it.** This best matches the linear-channel goal and gives the
project a real proof boundary. This is the selected target, with the proof gate
kept ahead of any release claim.

**Option D - Use sidecar muxing or downstream caption hardware where accepted.**
This may be valid for a particular station or appliance, but it is not the same
claim as embedded stream captions. It remains a supported deployment-specific
path only when the evidence names that boundary precisely.

## Consequences

### Positive

- CivicCast does not overclaim accessibility or cable caption readiness from
  unrelated caption surfaces.
- The UI/API status has a clear rule: `on` means emitted-stream decode-back
  passed; otherwise it remains `not-verified`.
- E.4 can support different downstream caption strategies without weakening the
  proof requirement.

### Negative

- Caption status remains conservative until a decoder proof exists.
- Real CEA-708 embedding may require FFmpeg capability, downstream appliance
  behavior, or an additional caption encoder that is not exercised by simple
  unit tests.
- Sidecar-capable deployments require careful wording so users understand what
  is and is not embedded in the stream.

### Risks

- Operators may mistake reviewed CivicCast captions for egress-stream captions.
  Mitigation: System Health and API status use `not-verified` until decode-back
  passes, and docs must distinguish reviewed captions from emitted-stream
  captions.
- A future implementation may set `caption_status="on"` after building FFmpeg
  args but before decoding the emitted output. Mitigation: tests must require
  `evaluate_caption_decode_back(...)` or equivalent emitted-stream evidence
  before the status flips.

## Compliance

- Default egress caption plans must report `not-verified`.
- `caption_status` may become `on` only after emitted-stream decode-back passes
  for the output under test.
- API, UI, docs, and release notes must not describe sidecar captions as
  embedded linear-stream captions.
- Any E.4 release evidence that claims captions must name the decoder, emitted
  stream path or sink, expected cue count, decoded cue count, matched cue count,
  timing tolerance, and blocker if failed.

## References

- `civiccast/egress/caption_embed.py`
- `civiccast/egress/models.py` - `CaptionStatus` and `EgressHealthSample`.
- `civiccast/apps/portal-operator/src/screens/SystemHealthScreen.tsx`
- `docs/spec/2.0/channel-egress-engine-build-plan.md`
- `docs/adr/0015-egress-continuity-mechanism.md`

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
