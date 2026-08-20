# ADR 0021 — Native Windows runtime (supersedes ADR-0003 Option B rejection)

- **Status:** Accepted (rung-3 dual review complete: auditor design review
  PASSED — audit-control verdict history — and owner merge authorized by
  Scott Converse, 2026-07-18)
- **Date:** 2026-07-17
- **Supersedes:** ADR-0003's rejection of Option B (native Windows). ADR-0003's
  Status flips to Superseded with a pointer here when this merges, per its own
  footer.
- **Program:** chartered in `scottconverse/civiccast-audit-control` (CHARTER.md);
  this ADR records the decision in the product repo the charter governs.

## Decision

CivicCast **adds a native Windows runtime as a first-class deployment line**:
a session-0 Windows service supervising PostgreSQL, NATS, the Python/FastAPI
control plane, and the **existing Python/PyGObject GStreamer media worker**
running on the official GStreamer 1.28.5 MSVC runtime. Tauri remains the
operator console and is never load-bearing for playout. Per the owner's
parallel-ship decision (2026-07-17), the WSL line and the native line ship
alongside — neither replaces the other by decree; the WSL line is
maintenance-posture and feature-diverged, and **its retirement/sunset remains
a FUTURE owner decision made on adoption and field evidence**, not an effect
of this ADR. What this ADR does supersede is ADR-0003's *rejection* of the
native option and its two premises, below.

## Falsified premises of ADR-0003 (the "why now")

1. **"Requires a permanently forked code path."** Falsified 2026-07-17 by the
   decision-gate evidence (`.agent-runs/native-windows/spike-decision-gate/`):
   the UNMODIFIED production `engine.py`/`worker.py` ran natively — 4 hot
   source swaps producing clean TS, hard-kill reaped in 0.00s with clean
   relaunch, three concurrent channels. Zero ENGINE porting cost; what the
   supervisor spec adds is a bounded platform seam (the worker control
   channel: POSIX FIFO → named pipe transport, acknowledged envelope), not a
   forked media path. The Rust `gstreamer-rs` port evaluated as the
   conditional fallback is CLOSED as unnecessary (remains the recorded
   fallback if soak evidence later demands it).
2. **"Benefit is marginal given WSL2's ubiquity."** Falsified by the measured
   WSL cost record: thirteen release candidates, a per-user HKCU-Run keepalive
   host babysitting `wsl.exe`, the rc13 withdrawal after a genuinely clean
   Windows test, and a roadmap (DeckLink SDI, PCIe) that WSL2 cannot reach at
   all (no PCIe passthrough).
3. **Media closure was assumed Linux-bound.** All 51 required GStreamer
   factories exist in the official Windows runtime, including the caption-SEI
   leg with byte-verbatim decode-back
   (`.agent-runs/native-windows/spike-gstreamer-bundle/`); PyGObject installs
   from pip (`gstreamer-bundle==1.28.5`); session-0 service execution is
   PROVEN (`.agent-runs/native-windows/spike-session0/`: engine broadcasting
   12s after boot, 6m14s before any interactive logon).

## Accepted costs (what Option B was rejected for, now owned deliberately)

(Spec paths below are repo paths under `.agent-runs/native-windows/specs/`.)

- Windows service management: the supervisor subsystem (`spec-supervisor.md`).
- A separate installer surface: a DISTINCT native Windows product built from
  the same installer codebase (`spec-installer-lifecycle.md` D1), full
  lifecycle proof matrix owed on two pristine class-6 environments.
- Path handling: one recorded WSL→Windows translation map applied by the
  migration runbook (`spec-migration-contract.md`).
- Expanded CI matrix: clean-environment verification of the packaged runtime
  closure (`spec-packaging-closure.md` D6).
- Larger download than the 244 MB WSL-era installer (native bundles what apt
  provided). Installed footprint and failure surface are EXPECTED to shrink;
  both are measured claims owed by the packaging evidence, asserted nowhere
  until then.

## Owner-risk acceptance register (merging this ADR accepts these EXPLICITLY)

1. **LocalSystem service identity for the beta** (least-privilege virtual
   account is a tracked follow-up) — a deliberate security-risk window, per
   supervisor spec D4.
2. **OpenH264/FFmpeg licensing posture** — accepted only after the packaging
   slice's evidence memo (exact binaries, build configuration, patent
   stance); this ADR records the QUESTION as owned, not the answer.
3. **Migration downtime window** — the WSL→native migration takes the station
   offline for the freeze period (migration spec D1).
4. **JetStream discard at migration** — decided only after the stream-catalog
   inventory (migration spec D6).
Items 2 and 4 may be accepted later than this ADR; they block their own
slices, not this record.

## Standing positions this ADR carries forward

- **Dual-runtime exclusion** before any side-by-side install
  (`.agent-runs/native-windows/specs/spec-dual-runtime-guard.md`): host-owned
  `ActiveRuntime` selector, bidirectional refusal enforced at each
  transmitter's own start path, cutover/rollback commands with an explicit
  post-activation data boundary.
- **NDI/SDI egress stays BYO-ffmpeg.** NDI licensing is dormant, not moot; it
  activates if CivicCast ever bundles NDI components. Trademark/attribution
  check recorded as owed before any bundling decision.
- **NATS stays** (ADR-0001); replacing it needs its own ADR.
- **No GPL in the shipped runtime**; x264 no-ship stands; `openh264enc`
  default; conditional encoders guard/remap per packaging spec D4.
- **Claims-evidence rule**
  (`.agent-runs/native-windows/specs/spec-claims-evidence-rule.md`) ships
  with this ADR: capability claims in prose bind to registered, executed
  evidence.

## Consequences

Charter §8 gates 4–7 remain the roadmap: dual-runtime guard, supervisor +
packaging + installer with two-pristine-machine proofs, hardware/live-peer
proofs at LPM, owner-gated LPM cutover with rehearsed rollback. macOS is a
separate future program. Nothing in this ADR tags, releases, or cuts over
anything — those are owner actions.
