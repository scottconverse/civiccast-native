# ADR 0019 - Production control-room device control via a vendored Sofie TSR Node sidecar

**Status:** Proposed
**Date:** 2026-06-29
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** S16 - Production control room (device control); 3.1 field hardening (live-device proof)
**Related spec section:** Control room / production device control (S16)
**Supersedes:** None
**Superseded by:** None

---

> **Backfill note.** This ADR records a decision that is **already implemented in
> the 3.0 tree** but was never written up as an ADR — a doc-currency gap caught
> while assessing OSS-reuse candidates. The code under `civiccast/control_room/`
> and `civiccast/control_room/tsr_service/` already embodies this decision; this
> ADR makes the decision auditable and states the proof boundary that remains
> open for 3.1. Promote Status from Proposed to Accepted once the human director
> ratifies the backfill.

## Context

CivicCast's production control room lets an operator drive live-production
devices — vision switchers and sources such as OBS (obs-websocket), vMix, Blackmagic
ATEM, HyperDeck, PTZ cameras, OSC endpoints, and CasparCG — from a single
timeline/cue surface. The hard architectural question is **how the Apache-2.0
Python control plane drives those devices without linking device-control code of
an incompatible license, and without coupling live playout to a browser tab.**

Constraints:

- **License posture (non-negotiable).** The CivicCast core is Apache-2.0. Device
  control libraries in the broader ecosystem carry mixed licenses; nothing
  GPL/AGPL may be linked into the Apache tree.
- **Operational posture.** Production control must not depend on an operator's
  browser staying open. A dropped tab cannot drop the channel.
- **Engine posture (closed).** GStreamer is the soaked egress/playout engine
  (ADR 0014–0018). Device *control* is a separate concern from the egress data
  plane and must not reopen the engine decision.
- **Proof posture.** Driving a real switcher requires the physical device; that
  proof belongs in the LPM lab, not CI.

The reference device-control library in the open-source broadcast world is
**Sofie's `timeline-state-resolver` (TSR)** — MIT-licensed, extracted from the
NRK Sofie project, production-tested, and already supporting the device set
CivicCast targets (ATEM, OBS, vMix, HTTP, TCP, WebSocket, OSC, CasparCG, GPI/serial).
TSR is a Node library; CivicCast's control plane is Python. That language gap is
the integration question this ADR answers.

## Decision

CivicCast drives production-control devices through a **CivicCast-owned localhost
Node sidecar that embeds TSR (`timeline-state-resolver`, MIT)**, reached only over
a loopback HTTP/IPC contract owned by CivicCast. The Python control plane sends
*desired state* (cues → timeline + mappings) to the sidecar; TSR computes the
device command diff and drives the device. The Python plane never speaks a device
protocol directly, and no GPL/AGPL device-control source is vendored into the
Apache tree.

The contract lives in `civiccast/control_room/tsr_client.py`:

- `TsrClient` (Protocol) — the surface the control plane calls.
- `NullTsrClient` — **fail-closed default** when no sidecar is configured: opens
  no socket, probes report unreachable, the operator console shows production
  control as unavailable.
- `HttpTsrClient` — the real loopback HTTP client, selected by `app.py` when
  `CIVICCAST_CONTROL_ROOM_TSR_URL` is set (e.g. `http://127.0.0.1:7717`).

The sidecar lives under `civiccast/control_room/tsr_service/` (`timeline-state-resolver@9.3.2`,
bound to `127.0.0.1`, started with `CIVICCAST_TSR_PORT=… npm start`, installed
with `npm install --ignore-scripts --omit=optional`). The operator console is the
**timeline editor and monitor**, not the control transport — control survives a
closed browser because the sidecar and the Python service own execution.

For 3.1, the sidecar also becomes a supervised station runtime. The installer or
runtime supervisor must start it, health-check it, restart it after a crash, pin
and report the TSR version, surface "sidecar down" to the operator console, and
include redacted sidecar evidence in the support bundle. A missing or unhealthy
sidecar keeps production control unavailable.

OBS and vMix are the first software-device proof targets. OBS is pinned to
obs-websocket 5.x. vMix uses its HTTP `/api` status/function surface and TCP/TALLY
where appropriate for program/preview state. CivicCast may build read-only
state, fixture, and proof helpers around those devices, but live device writes
continue to flow through the sanctioned control-room dispatcher/TSR boundary.

## Alternatives considered

**Option A — Vendored TSR Node sidecar behind a CivicCast-owned loopback contract (selected).**
Reuses the reference MIT device-control library; keeps the Apache tree free of any
linked device-control code (TSR is a separate process; devices are reached over
their own socket protocols, never linked); decouples control from the browser.
Cost: a Node runtime dependency and a second process to supervise. This is what
the 3.0 tree already implements.

**Option B — Hand-rolled Python device control.** CivicCast writes its own ATEM /
obs-websocket / vMix / OSC clients. Rejected: large surface area, reinvents
battle-tested protocol handling, and every device added is new bespoke code to
maintain and prove. TSR already covers the device matrix.

**Option C — Browser-based device control (operator tab drives devices).** Rejected
on the operational non-negotiable: production control cannot depend on a browser
tab staying open; a refresh or crash must not drop the channel.

**Option D — Restrict control to CasparCG only (drive it directly).** Rejected as
too narrow: stations use ATEM/OBS/vMix far more than CasparCG. (Note: CasparCG
remains reachable *as a TSR device* under Option A — driving CasparCG as a
control target is distinct from adopting it as the egress engine, which ADR
0014–0018 already closed against.)

## Consequences

### Positive

- Reuses the proven MIT reference implementation; CivicCast does not maintain
  device protocol clients.
- License-clean: the Apache core links nothing GPL/AGPL; TSR is MIT and runs as a
  separate process; devices are reached over their own protocols.
- Control survives a closed/crashed operator browser; the console is editor +
  monitor, not the transport.
- New devices that TSR already supports become available without CivicCast core
  changes — only the device-kind → `DeviceType` mapping is touched.
- Fail-closed by default: with no sidecar configured, `NullTsrClient` guarantees
  no surprise socket activity and an honest "unavailable" surface.

### Negative

- Adds a Node runtime and a supervised sidecar process to the deployment story
  (install, start, health, port binding).
- Two-language control path (Python contract ↔ Node sidecar) to reason about and
  document.
- TSR version bumps must be tracked and re-proven against the device matrix.

### Risks

- **Live-device behavior is unproven in CI.** Machine-verified today: TSR imports,
  the device-kind → `DeviceType` mapping and cue → timeline/mappings translation
  (`buildCueState`, `builder.test.mjs`), and the sidecar HTTP server + `/healthz`.
  **Not yet proven:** opening a TSR connection (`connectionManager.createConnection`)
  to a real OBS/ATEM/vMix and observing the device change on a fired cue.
  *Mitigation:* this is the explicit 3.1 LPM-lab station-device evidence item;
  until it passes, the console must not represent device control as
  station-device-proven.
- A future change could leak device-protocol shape or secrets through the contract.
  *Mitigation:* the sidecar redacts secrets before any payload returns; error
  messages carry failure type/summary only; the Python plane treats TSR as a
  black-box state resolver.
- A future developer could try to drive a device from Python directly.
  *Mitigation:* compliance rules below; the only sanctioned path is `TsrClient`.
- A future release could overstate mocked or lab-only device proof.
  *Mitigation:* every 3.1 claim must name its proof level: mocked, lab-proven, or
  station-device-proven. Mocked features are documented but excluded from
  station-device release claims.

## Compliance

- The Python control plane MUST drive devices only through `TsrClient`
  (`NullTsrClient` / `HttpTsrClient`); it MUST NOT open a device protocol socket
  directly.
- The sidecar MUST bind to `127.0.0.1` only and MUST be the sole process that
  links/loads `timeline-state-resolver`.
- No GPL/AGPL device-control source may be vendored into the Apache tree; TSR
  (MIT) is the only vendored device-control dependency and lives under
  `control_room/tsr_service/`.
- With no `CIVICCAST_CONTROL_ROOM_TSR_URL` configured, the system MUST use
  `NullTsrClient` and surface production control as unavailable (fail-closed).
- Any release evidence that claims live device control MUST name the device, the
  cue fired, and the observed device-state change from a real device — not a
  `/healthz` or import check.
- TSR version changes are a dependency ADR or a lockfile note plus a re-proof
  against the device matrix.
- vMix input rename, input delete, shortcut mutation, global vMix configuration
  mutation, and recording-destination mutation MUST NOT be exposed as 3.1 cue
  actions. They are configuration changes, not live cue actions.
- Live Fire MUST compare only the material-state fingerprint for the cue being
  fired, not the whole device-state store. Unrelated meter, heartbeat, or tally
  changes must not make the control surface unusable.
- A safe-state cue MUST be configured before On-Air Mode is available; replacing
  that safe-state cue while any relevant session is On-Air is forbidden.
- Cue versions referenced by fired-action audit rows MUST remain immutable.

## References

- `civiccast/control_room/tsr_client.py` — `TsrClient`, `NullTsrClient`, `HttpTsrClient`.
- `civiccast/control_room/tsr_service/` — Node sidecar; `package.json` (`timeline-state-resolver@9.3.2`), `README.md` (verification boundary).
- `civiccast/control_room/router.py`, `models.py`, `service.py`, `store.py`, `secrets.py` — timeline/surface/cue control surface.
- `civiccast/app.py` — sidecar selection via `CIVICCAST_CONTROL_ROOM_TSR_URL`.
- Sofie `timeline-state-resolver` (MIT): <https://github.com/nrkno/sofie-timeline-state-resolver>
- Related: ADR 0017 (egress control-plane/data-plane split), ADR 0014–0018 (egress/GStreamer engine — not reopened by this ADR).

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
