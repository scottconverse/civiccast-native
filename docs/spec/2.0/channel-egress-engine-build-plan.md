# Channel Egress Engine Build Plan

Status: project memory for the 2.x egress build.

This page preserves the converged implementation understanding for the future
`civiccast.egress` subsystem. It is not product code and it is not release
proof. It records the gates the implementation must pass before CivicCast can
claim a continuous IP/SRT channel handoff.

## Stable Understanding

The channel egress engine is the first long-running "muscle" attached to the
existing planning brains in `civiccast.cable` and `civiccast.cg`. The planning
code can describe what should air; egress must prove that CivicCast can keep
valid bytes flowing to a downstream endpoint without dead air.

The first task is not "implement all of `civiccast.egress`." The first task is
to prove or disprove the persistent FFmpeg continuity strategy on a real or
representative SRT link.

## Architecture Gate

The continuity spike is the budget and architecture gate.

Spike question:

> Can one persistent FFmpeg encoder switch between conformed assets through a
> FIFO or concat-demuxer strategy on a real SRT path without downstream-detected
> discontinuities?

If the answer is yes, the project proceeds with the single persistent encoder
strategy. If the answer is no, the project moves to the two-encoder plus
software-switcher contingency and must be re-estimated for CPU cost, runtime
complexity, and multi-channel sizing before broader implementation continues.

Loopback SRT and FileSink tests are useful, but they are not equivalent to a
real headend or representative downstream receiver.

## Continuity Spike Result

Stage 1 spike evidence is recorded in
`docs/releases/evidence/v2.0.8-egress-continuity-spike-proof.md` and
`docs/adr/0015-egress-continuity-mechanism.md`.

The Windows tester proof for work commit `f4f2114` passed both FileSink and
receiver-instrumented loopback SRT:

- FileSink: `passed: True`, `boundary_count: 5`, measured duration `3.155`
  seconds against expected `3.0`, FFmpeg return code `0`.
- Loopback SRT: `passed: True`, `boundary_count: 5`, sender FFmpeg return code
  `0`, receiver return code `0`, receiver duration within tolerance.

Decision: proceed into E.1 with the single persistent FFmpeg concat-demuxer
encoder strategy as the first implementation path.

Boundary: this result is not real headend validation, not QAM or SDI proof, not
caption proof, not EAS proof, and not a long soak. E.2 still requires at least
50 boundaries on a real or representative SRT path before the continuity claim
can expand beyond the spike boundary.

## Build Ladder

### E.1 - One file to one SRT sink, supervised

Goal: prove a single channel can run under the daemon/process model, feed one
asset to an SRT sink, expose staff control, write state, and recover under
systemd supervision.

Hard exit criteria:

- Operator can start and stop the channel from the staff control surface.
- The daemon writes durable state and health.
- The output can be watched on an SRT receiver.
- Killing the daemon returns the channel to air within the documented recovery
  window.
- The loudness target for the deployment is recorded. See
  `docs/adr/0014-egress-loudness-target.md`.

### E.2 - Gapless continuity and loudness

Goal: resolve the continuity spike and prove multi-program output across many
boundaries.

Hard exit criteria:

- The spike has selected Option A or Option B.
- A multi-program playlist crosses at least 50 boundaries on a real or
  representative SRT path with no downstream-detected discontinuity.
- Program audio measures within the configured loudness target and tolerance.
- FileSink CI proves real FFmpeg output behavior without pretending to be
  headend validation.

### E.3 - Slate, CG, and live takeover

Goal: prove fallback and interruption behavior, not just ordinary playlist
playout.

This rung is not routine plumbing. It carries correctness risk because "it
runs" and "it aired the correct thing at the correct boundary" can diverge.

Hard exit criteria:

- Missing or failed assets transition to slate without black, dead air, or a
  dropped output connection.
- Slate enter and exit events are written to the proof log.
- CG and emergency-overlay rendering use real contracts and do not imply EAS
  origination or EAS certification.
- A live source can take over and hand back to schedule without dropping the
  stream.
- Every takeover, handback, slate, and CG event is auditable in proof output.

### E.4 - Captions, full UI, telemetry, soak, and additional sinks

Goal: prove the remaining correctness and compliance-adjacent surfaces before
release language expands.

This rung is also not routine plumbing. Caption behavior, telemetry, and soak
must prove behavior, not just process uptime.

Hard exit criteria:

- Caption embedding remains labeled `not-verified` until decode-back proof
  shows captions can be recovered from the emitted transport stream.
- Emergency overlays remain documented and labeled as CivicCast CG banners, not
  EAS.
- RtmpSink, LocalTsSink, and FileSink behavior is tested at the correct proof
  boundary.
- System Health exposes useful live state without leaking sink secrets.
- Soak evidence measures source changes, fallback behavior, daemon recovery,
  memory growth, dropped frames, encoder speed, and sink connectivity.
- A short run cannot be called six-hour release evidence.

## Loudness Decision

Egress loudness is configurable per channel/output. The existing CivicCast
streaming path uses a `-16 LUFS` style target, while cable/broadcast handoff
expectations may require `-24 LUFS`. The implementation must not bury that fork
as a constant.

The E.1 proof must record the Longmont/headend target that was actually used.
The release claim must say CivicCast emitted within the configured loudness
target unless an external compliance proof exists.

See `docs/adr/0014-egress-loudness-target.md`.

## Canonical Profile Decision

Egress source preparation conforms every source to a stable canonical profile
before it reaches the persistent encoder. The E.1 default is the current 720p
MPEG-TS profile recorded in `docs/adr/0016-egress-canonical-profile.md`, and the
profile remains configurable per channel. E.1 and E.2 evidence must record the
profile actually used for the handoff proof.

## Claims To Avoid

Do not claim:

- Egress is headend-validated from FileSink or loopback SRT alone.
- Emergency overlay is EAS.
- Caption embedding is compliant before decode-back proof.
- A process stayed alive for six hours if the behavior under test did not stay
  correct for six hours.
- The single-encoder strategy is the architecture before the spike proves it.

## Project Memory Summary

The settled project understanding is:

- The continuity spike gates architecture and budget.
- E.1 through E.4 are hard gates with real exit criteria.
- Loudness is a tracked per-channel/per-output decision, not a guessed number.
- E.3 and E.4 remain hard correctness and compliance rungs even after the
  continuity spike passes.
