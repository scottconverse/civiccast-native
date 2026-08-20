# S16 — Production & Control Room (External Switcher Control via TSR)

> **Status:** Built optional production-control tier for v3.0.0-beta1.
> **Disposition:** **net-new** control surface (a thin CivicCast control UI built on top of TSR);
> the *feed it produces* enters the existing `live/` ingest and plays out through the S15
> GStreamer engine.
> **Relates to:** Master §2 (PEG automation coverage), §3 (built-already inventory), §5 (proof ladder),
> §6 (entity model), §9 (reconciliation), §10 (build order); S15 (the engine this feeds into),
> S5 (the *internal* egress takeover — kept distinct), S2 (NDI/SRT/capture as the feed path),
> S9 (co-process supervision), S1/S3 (per-tier component install). Binding: `RECONCILIATION.md`.

---

## 1. Goal & PEG automation rationale

### What incumbent PEG platform does
incumbent PEG platform markets **"Virtual Control Rooms"** and **"Live & Remote Switching"** — the ability for a
PEG station to switch a multi-source live production (council chamber cameras, a podium mic, a
playback machine, a remote presenter) and send the cut program to a channel. In the incumbent PEG platform world
this is proprietary hardware/software plus their VIO appliances.

### The CivicCast posture (Scott-locked, 2026-06-13)
A small PEG station already owns the open-source production tools the rest of the industry uses —
overwhelmingly **OBS Studio**, and increasingly **vMix** or a **Blackmagic ATEM** hardware switcher.
S16 does **not** rebuild a production switcher. It delivers a **thin CivicCast control surface** that
*drives the switcher(s) the station already has*, then routes the resulting live program feed into the
S15 playout engine as a source. The parity feature ("Virtual Control Rooms / Live & Remote Switching")
is achieved **on top of the OSS the membership already runs**, not by selling them another box.

The abstraction that makes this tractable — and that makes it OBS-*and*-vMix-*and*-ATEM rather than
OBS-only — is **TSR (timeline-state-resolver)**. TSR is the open-source device-control library
extracted from the Sofie broadcast-automation project; it already ships adapters for **~20 device
types** (OBS via obs-websocket, vMix via its HTTP/TCP API, Blackmagic ATEM, HyperDeck, CasparCG,
PTZ/VISCA, OSC, generic HTTP/TCP, and more). We drive TSR; TSR drives the devices. **We do not
hand-build one adapter per tool.**

### The boundary that must be stated explicitly (do not blur it)
- **OBS (and any external switcher) is for operator-driven *live production / switching*, NOT 24/7
  unattended playout.** Unattended channel playout is the **S15 GStreamer engine** — persistent
  pipeline, machine-proven soak target, the thing that fixes #151. S16 is the *attended* live-cut
  surface whose output becomes one more *source* into S15.
- **S16 is the EXTERNAL production-switcher control. S5 (Software Force Matrix) is the INTERNAL
  egress takeover.** They are different layers and must stay cross-referenced but distinct:
  - **S5** arbitrates *which already-running source the CivicCast egress puts on a channel* (the
    supervisor priority model: emergency-slate > live-takeover > committed-schedule > filler). It is
    inside the playout engine.
  - **S16** controls *external production hardware/software* to *produce* a clean program feed in the
    first place. That feed arrives at CivicCast over NDI/SRT/capture, becomes a `live/` ingest source,
    and is then eligible to be taken to air by S5. **S16 produces the source; S5 decides if/when it
    airs.** Neither owns the other.

### What 3.0 delivers (control-room tier — optional feature module)
1. A **CivicCast-owned control plane** (Python/FastAPI) that exposes production control as a
   first-class CivicCast feature, **never** linking GPL code into the core (see §7 license hygiene).
2. A **small Node control service** that embeds TSR (a Node library) behind a CivicCast-owned
   REST/IPC contract; the Python control plane is the only caller.
3. An **operator console** for arming and firing **timeline cues** (take camera 2, roll the playback
   deck, push a lower-third, recall an ATEM macro, point a PTZ preset) across whichever devices the
   station has configured.
4. Device **profiles and inventory** (`ProductionDevice`, `DeviceProfile`) so a station declares
   "I run OBS at this host" or "I have an ATEM at this IP" once, and CivicCast knows how to reach it.
5. A clean handoff: the produced program feed is registered as a **`live/` ingest source** (NDI/SRT/
   capture), so it plays out, records, and reaches the headend through the **existing** S15 path —
   no new egress code.

This is an **opt-in deployment profile**. A streaming-only or single-camera station never configures
a control room; the module is dark and adds no runtime cost.

---

## 2. Current state (file:line — honest: the control surface is net-new)

| Component | Location | Status |
|-----------|----------|--------|
| AV facility router (preview/take **planning**) | `facility/models.py:36-255`, `facility/router_control.py:27-163` | **Built (planning tier, in-memory).** Plans deterministic vendor commands (Blackmagic Videohub, Ross RossTalk, Utah, Evertz, generic text/hex) and returns a `RouterTakePlan`/`VirtualRouterPanel`. `proof_boundary` is explicit: *"Command planning only; no hardware connection is opened by this API"* (`router_control.py:49,85`). **Relate to S16 but do not merge:** facility is SDI/baseband *router crosspoint* planning (source→destination matrix), with no live socket. S16 is *production switcher* control (scenes/cuts/macros/decks/PTZ) with a live device session via TSR. The facility router is the *physical-routing* cousin; S16 can later drive a router crosspoint **through TSR's generic TCP/HTTP adapter**, but V1 keeps them separate and cross-referenced. |
| Live ingest (the feed enters here) | `live/router.py` (32 KB), `live/models.py:68-90,212-280` | **Built.** `LiveSource.source_type` ∈ `rtmp|rtsp|ndi|srt` (`live/models.py:79`, CHECK `:224`); preflight (`live/preflight.py`), recording/finalization (`live/finalization*.py`). The S16 program feed is registered as one of these (NDI/SRT preferred for clean broadcast handoff). **No net-new ingest code required** — S16 reuses this. |
| Egress engine (the feed plays out to) | `egress/` → being re-platformed to GStreamer (S15) | **Built / re-platforming.** S16 output is a *source into* S15, not a new sink. |
| Internal egress takeover (S5 — kept distinct) | `egress/supervisor.py:53-72`, `egress/live_takeover.py:12-57` | **Built (rung-0 contract), unwired.** This is the *internal* arbiter; `build_live_takeover_source_plan()` already accepts a `LiveIngestPlan` and emits an `EgressSourcePlan` — that is the exact seam where an S16-produced feed becomes air-eligible. |
| Auth roles | `auth/roles.py:14-20` | **Built.** Five real roles: `setup_admin`, `meeting_operator`, `records_clerk`, `publish_operator`, `support_admin`. `require_any_role(...)` per endpoint (`:60-80`). |
| **TSR control plane (Python side)** | — | **Net-new.** No production-switcher control exists today. |
| **TSR Node control service** | — | **Net-new.** No vendored TSR, no Node sidecar today. |
| **Operator control-room console** | — | **Net-new.** `ChannelOpsScreen`/`FacilityRouterScreen` exist; a production console does not. |
| **Device profiles / cue model / persistence** | — | **Net-new.** No `ProductionDevice`/`ControlSurface`/`TimelineCue`/`DeviceProfile` table. |

**Honest summary:** the *feed path* (`live/` ingest → S15 egress) already exists and is reused
wholesale. The *facility router* is a related-but-different planning surface. **Everything that makes
this a control room — TSR embedding, the Node sidecar, device profiles, the cue/timeline model, and the
operator console — is net-new.**

---

## 3. Entities / data model & migrations

### New entities (add to a new `civiccast/control_room/models.py`)

- **`ProductionDevice`** — one externally-controlled device the station owns.
  - `device_id: str` (uuid); `label: str`; `kind: ProductionDeviceKind`
    (`obs | vmix | atem | hyperdeck | ptz | osc | tcp | http | casparcg`);
    `host: str | None`, `port: int | None`; `transport: Literal["tcp","udp","http","websocket"]`;
    `enabled: bool`; `notes: str | None`. Credentials/secrets are **never** stored here in cleartext
    — a `secret_ref` points at the keyring store (`auth/keyring_store.py` pattern), mirroring how
    `live/` keeps credentials out of operator-facing plans.
  - **License note carried in the model:** `kind="obs"` is annotated as *arms-length GPLv2 control*
    (we speak obs-websocket's JSON protocol over a socket; we never link OBS code). See §7.

- **`DeviceProfile`** — the TSR mapping/config blob for a `ProductionDevice`: which TSR device type,
  options (e.g. obs-websocket port + secret_ref, vMix endpoint, ATEM model), and the CivicCast-owned
  capability map (what cues this device exposes). Versioned so a device firmware/app change is auditable.

- **`ControlSurface`** — a named operator layout (e.g. "Council Chamber A/B/C + podium"): an ordered set
  of `TimelineCue`s grouped into rows/banks, with `assigned_role` gating (which of the five real roles
  may fire it). One control room may have several surfaces.

- **`TimelineCue`** — one fireable action resolved against TSR's timeline-state model:
  `cue_id`, `surface_id`, `label`, `device_id`, `action`
  (`scene|input|transition|macro|deck_play|deck_cue|ptz_preset|osc|http|overlay_push|overlay_clear`),
  `payload: dict` (e.g. `{"scene":"CAM2"}`), `confirm_required: bool`, `proof_boundary: str`.
  Cues are *planned and validated server-side* before any socket opens (same discipline as
  `facility/router_control.py`'s plan-then-send split).

- **`ControlRoomSession`** — audit record of a live production session: `session_id`, `surface_id`,
  `operator_id`, `started_at`, `ended_at`, `program_feed_source_ref` (the `live/` source the cut feeds),
  and an append-only `cue_fired` log (`cue_id`, `operator_id`, `at`, `device_id`, `result`). This is the
  who-did-what-when trail PEG stations need for franchise/compliance, parallel to S5's `TakeoverSession`
  but for *production* actions rather than *air* actions.

### Migration

- **`0047_production_control`** — single global alembic chain, next free number after the
  RECONCILIATION table's `0046_analytics_viewership` (head verified at `0037_asset_meeting_body`;
  0038–0046 are assigned to S4–S14). Adds:
  `production_devices`, `device_profiles`, `control_surfaces`, `timeline_cues`,
  `control_room_sessions` (+ the `cue_fired` audit child). Secrets live in the keyring, not these tables.

> **RECONCILIATION addendum line (to fold into `RECONCILIATION.md`):**
> *S16 (Production & Control Room) takes migration `0047_production_control` on the single global
> chain (after `0046_analytics_viewership`); entities `ProductionDevice`, `DeviceProfile`,
> `ControlSurface`, `TimelineCue`, `ControlRoomSession`. S16 is the EXTERNAL production-switcher
> control and is distinct from S5 (internal egress takeover). The produced feed enters via `live/`
> ingest (NDI/SRT/capture) and plays out through S15 — S16 adds no egress sink. The head pin in
> `tests/live/test_real_postgres.py` advances to `0047` when S16 merges.*

---

## 4. API surface (+ the five real auth roles)

All under `/api/staff/control-room/...`, FastAPI, `require_any_role(...)` per endpoint. The Python
control plane is the **only** caller of the Node TSR service (which is bound to localhost / IPC and is
not publicly reachable).

| Method · path | Roles (`auth/roles.py:14-20`) | Purpose |
|---|---|---|
| `GET /devices` | `setup_admin`, `support_admin`, `meeting_operator` | List configured `ProductionDevice`s + live reachability (read-only). |
| `POST /devices` · `PATCH /devices/{id}` | `setup_admin` | Configure a device (host/port/kind/profile); secret goes to keyring. Commissioning-class action. |
| `POST /devices/{id}/probe` | `setup_admin`, `support_admin` | Open a *control* connection to verify reachability; returns capability map. Diagnostic. |
| `GET /surfaces` · `GET /surfaces/{id}` | `meeting_operator`, `support_admin`, `setup_admin` | Read control surfaces + their cues. |
| `POST /surfaces` · `PATCH /surfaces/{id}` | `setup_admin` | Author/edit a surface and its cues. |
| `POST /sessions` (start) · `DELETE /sessions/{id}` (end) | `meeting_operator` | Open/close a live production session bound to a `live/` program feed source. |
| `POST /sessions/{id}/cues/{cue_id}/plan` | `meeting_operator`, `support_admin` | **Plan-only**: validate + preview the resolved TSR action; opens no socket (mirrors `router_control` plan/send split). |
| `POST /sessions/{id}/cues/{cue_id}/fire` | `meeting_operator` | Fire the cue via TSR (the live action). Appends to the session audit. |
| `GET /sessions/{id}` | `meeting_operator`, `support_admin` | Live session state + fired-cue audit (read-only). |

**Role rationale:** device *configuration* is a `setup_admin` (commissioning) act; live *operation*
(open session, fire cues) is `meeting_operator` (the role that runs a meeting/production); read-only
diagnostic surfaces add `support_admin` per RECONCILIATION D1. `records_clerk`/`publish_operator` have
no control-room write authority. `operator`/`admin` remain all-roles aliases only.

---

## 5. Operator UI

A new **Control Room** console (mobile-first, consistent with `ChannelOpsScreen`/`FacilityRouterScreen`):

- **Device strip** — each `ProductionDevice` as a status chip (reachable / unreachable / disabled) with
  the device kind and an honest reachability dot. A red chip never blocks the *rest* of the surface.
- **Surface grid** — the `ControlSurface`'s cue banks rendered as large tap targets (PROGRAM cuts, deck
  transport, PTZ presets, overlay push/clear, ATEM macros). `confirm_required` cues show a two-step
  confirm (parity with the facility panel's `requires_confirmation`).
- **Plan-before-fire affordance** — long-press / "preview" shows the resolved TSR action and its
  `proof_boundary` text before the operator commits, so an operator can see *exactly* what will be sent.
- **Program-feed banner** — shows which `live/` source the cut is feeding and whether S5 currently has
  it on a channel (read-only mirror of egress state; firing air is an S5 action, not an S16 one — the
  banner makes the S16↔S5 boundary visible in the UI).
- **Session audit drawer** — the append-only fired-cue log for the active `ControlRoomSession`.

The console degrades honestly: if the Node TSR service is down, the console shows a clear
"production control unavailable" state and **does not** silently appear functional.

---

## 6. Behavior / algorithms

1. **Three-tier control path.** Operator UI → CivicCast Python/FastAPI control plane → CivicCast-owned
   REST/IPC → **Node TSR service** → device. TSR resolves a declarative **timeline state** into the
   minimal device commands needed to reach it (its core competency); CivicCast sends *desired state*,
   TSR computes the diff and emits device I/O. We treat TSR as a black-box state resolver behind our
   own contract so the public API never leaks TSR's shape.
2. **Plan / fire split (borrowed from `facility/router_control.py`).** Every cue is *resolved and
   validated server-side* (`/plan`) before any device socket carries a live command (`/fire`). Planning
   never opens a connection; firing does. This keeps the same auditable, preview-first discipline the
   facility router already proves.
3. **Equal-footing device support.** Because TSR already ships OBS, vMix, ATEM, HyperDeck, PTZ, OSC and
   generic TCP/HTTP adapters, adding a device kind is *configuration*, not a new adapter. The cue model
   maps CivicCast actions onto TSR device types; OBS and vMix are reached the *same* way from the
   operator's point of view. **No OBS-only special-casing.**
4. **Feed handoff (the only coupling to the rest of CivicCast).** The produced program feed reaches
   CivicCast over **NDI or SRT** (preferred) or a capture device, is registered as a `LiveSource`
   (`live/models.py`), and from there `build_live_takeover_source_plan()` (`egress/live_takeover.py:12`)
   can turn it into an `EgressSourcePlan` for S5 to arbitrate. **S16 stops at producing the source.**
5. **No unattended duty.** A `ControlRoomSession` is operator-bound and explicitly ended; there is no
   autonomous cue firing. Unattended playout remains the S15 engine. If a session is left open, S8
   alerting can flag "control-room session open >N hours" (analogous to S5's takeover-stuck watch), and
   S9 co-process supervision covers the Node service and any locally-run OBS/CasparCG process identity.
6. **Worked-example mining, not platform adoption.** We **do not** adopt Sofie-core or SuperConductor as
   a platform. SuperConductor is an **AGPL GUI with an unstable API** — unsuitable to depend on — but its
   source is the best public worked example of driving TSR, so we *read* it to learn the TSR call
   patterns and write our own thin Node service. (Reading AGPL source for understanding is fine; we ship
   none of its code.)

---

## 7. Proof tier (rung) + honest claim boundary

**Current rung: 0 (Contract).** No control-room code exists; this is a spec.

**Ladder targets (master §5):**
- **Rung 0 → 1 (Lab-proven):** the Node TSR service drives a *real* OBS instance (and, separately, a
  *real* vMix or ATEM) on a loopback/lab bench — fire a cue, observe the device change, register the
  produced feed as a `live/` source, and confirm S15 plays it out. `proof_boundary` declared per device
  kind (e.g. "OBS 30.x via obs-websocket 5.x on localhost").
- **Rung 2 (Machine-proven):** control-room module survives the clean-install + soak harness alongside
  the engine (the module is *dark* unless configured, so its rung-2 bar is "does no harm when off, and a
  configured session reconnects cleanly across a Node-service restart"). It is **not** part of the
  unattended-playout soak claim — S16 is attended by design.
- **Rung 3 (SDI) / 4 (Headend) / 5 (Field):** inherited from S15/S2 for the *played-out feed*, not
  claimed by S16 itself.

**Honest claim boundary (do not overclaim):**
- We claim "**CivicCast controls your existing OBS / vMix / ATEM / HyperDeck / PTZ via TSR**" only for
  device kinds we have *lab-proven* against a real device; everything else is "contract / configurable,
  unproven against that specific device."
- We **never** claim CivicCast *is* a production switcher or replaces OBS/vMix — it **controls** them.
- We **never** claim OBS is suitable for 24/7 unattended playout (that is S15).
- The TSR device matrix says ~20 device types; we claim only the *subset CivicCast ships profiles and
  tests for in V1*, and document the rest as "TSR-supported, profile not yet shipped."

---

## 8. Test plan + 0/0/0/0/0 audit

1. **Contract tests (rung 0):** `ProductionDevice`/`DeviceProfile`/`ControlSurface`/`TimelineCue`/
   `ControlRoomSession` validation; API role-gating for all five real roles (positive + 403 negative);
   plan-only endpoints open no socket (assert no I/O); secrets never serialized into responses or tables.
2. **Node-service contract tests:** the CivicCast REST/IPC contract is honored; a mocked TSR confirms
   desired-state → command-diff resolution and reconnect logic; the Python side is the only caller.
3. **Lab device proof (rung 1):** drive a real OBS via obs-websocket (scene cut + overlay push);
   separately drive a real vMix and/or an ATEM via TSR; capture the device-state change as proof with a
   declared per-device `proof_boundary`.
4. **Feed-handoff integration:** produced feed → `live/` `LiveSource` (NDI/SRT) → S15 playout; assert the
   S16→S5 boundary holds (S16 produces; S5 airs).
5. **Failure modes:** Node service down (console shows unavailable, no false-positive controls); device
   unreachable (chip red, surface still usable for reachable devices); session left open (S8 alert fires).
6. **License-hygiene test:** CI check that no GPL/AGPL source (OBS, obs-websocket, SuperConductor,
   CasparCG) is vendored into the Apache tree; TSR (MIT) vendoring carries its license; the Node service
   talks to OBS only over the socket (process separation asserted in S9 co-process inventory).
7. **Playwright walkthrough:** Control Room console — configure device, author surface, open session,
   plan a cue, fire a cue, read audit, end session.
8. **0/0/0/0/0 audit:** `audit-lite` after each fix; full `audit-team` + `walkthrough` at section
   completion. Every audit reaches **0 Blocker / 0 Critical / 0 Major / 0 Minor / 0 Nit** before DONE.

---

## 9. DONE

S16 is done when:
- A station configures its real OBS (and at least one of vMix / ATEM) once as `ProductionDevice`s, and
  the CivicCast Control Room console fires cues that visibly change those devices via TSR (rung-1 proof
  captured per device kind).
- The produced program feed is registered as a `live/` source over NDI/SRT and plays out through the
  S15 engine, with the S16↔S5 boundary intact (S16 produces the source; S5 arbitrates air).
- Migration `0047_production_control` is applied on the single global chain; `RECONCILIATION.md` carries
  the addendum line; the head pin advances to `0047`.
- The five real roles gate the API correctly; secrets stay in the keyring; the module is **dark and
  cost-free when unconfigured**.
- License hygiene is CI-enforced: TSR (MIT) vendored with license; OBS/obs-websocket (GPLv2) and
  CasparCG (GPLv3) reached only as separate processes over a socket; vMix reached via its proprietary
  API; **zero GPL/AGPL source in the Apache core**; SuperConductor used as a read-only worked example
  only.
- 0/0/0/0/0 audit + Playwright walkthrough pass.

---

## 10. Dependencies / cross-refs + open decisions

**Dependencies / cross-refs:**
- **S15 (playout engine):** the produced feed is a *source into* S15; S16 adds no sink. The OBS-vs-S15
  boundary (attended production vs unattended playout) is owned here and asserted there.
- **S5 (Software Force Matrix):** S16 produces the feed; **S5** decides if/when it airs via the
  supervisor priority model. Kept distinct; `build_live_takeover_source_plan()` is the seam.
- **S2 (headend/NDI/SRT):** the feed-handoff transport (NDI/SRT/capture) reuses S2's I/O paths.
- **`live/`:** the produced feed is an ordinary `LiveSource` (`source_type` ndi/srt) — no new ingest code.
- **`facility/`:** the SDI/baseband *router crosspoint* planner is the related-but-distinct cousin; V1
  keeps it separate; a future S16 cue could drive a router crosspoint through TSR's generic TCP/HTTP
  adapter.
- **S9 (reliability / process identity):** the Node TSR service and any locally-run OBS/CasparCG get the
  process-identity primitive (pid + image + create_time) and co-process supervision; the device-lock
  concern (a co-process holding hardware after unclean restart) is S9's, applied to this tier.
- **S8 (alerting):** "control-room session open >N hours" and "configured production device unreachable"
  are alert conditions S8 surfaces.
- **S1/S3 (commissioning / per-tier install):** the control-room tier is an optional component install —
  Node runtime + vendored TSR + (operator-installed) OBS/vMix/NDI runtime — folded into S3's component
  list, not a new wizard screen (RECONCILIATION D12).
- **S13 (AI):** none.

**License citations (precise):**
- **TSR — timeline-state-resolver:** **MIT** (Sofie project, `nrkno/sofie-timeline-state-resolver`).
  Apache-clean; **vendorable** into the CivicCast tree. This is the only production-control dependency
  we ship.
- **OBS Studio:** **GPLv2**. **obs-websocket** (the control plugin/protocol): **GPLv2**. Reached
  **arms-length over a socket only** — separate process, never linked, no source vendored.
- **CasparCG:** **GPLv3** — optional premium co-process (per S15 §5), bridged over NDI/SDI + AMCP;
  never linked.
- **SuperConductor:** **AGPL** GUI with an **unstable API** — **not** adopted as a platform; its source
  is read as a TSR worked example only, **zero code shipped**.
- **Sofie-core:** **not adopted** as a platform (we take only the MIT TSR library out of the ecosystem).
- **vMix:** **proprietary**; controlled via its documented **HTTP/TCP API** (no code, no linking).
- **Blackmagic ATEM / HyperDeck:** controlled via Blackmagic's protocols through TSR; BMD SDKs/runtimes
  are installed-not-redistributed where needed (consistent with S15's SDI/NDI runtime posture).
- **CivicCast control plane + Node TSR service + cue templates:** **Apache-2.0** (our code/content).

**Open decisions for Scott:**
1. **V1 device set to lab-prove (rung 1):** confirm the subset we test against *real* devices for V1.
   Recommendation: **OBS (universal) + ATEM (the common PEG hardware switcher) + vMix (the common
   software competitor)** to prove the "equal-footing, not OBS-only" claim concretely; HyperDeck/PTZ/OSC
   ship as TSR-supported-but-profile-unshipped until a station needs them. *(Recommend OBS+ATEM+vMix.)*
2. **Node sidecar packaging:** confirm the small Node TSR service ships as a managed CivicCast service
   (installed/supervised like the other components under S1/S3, lifecycle-managed by S9) rather than a
   user-run process. *(Recommend managed service.)*
3. **Is the control-room tier in V1 at all, or a documented post-V1 module?** It is coverage-relevant
   (incumbent PEG platform Virtual Control Rooms) but it is *attended* and orthogonal to the unattended-playout
   machine-proof that gates the core release. *(Recommend: ship the contract + OBS rung-1 proof in V1;
   expand the device matrix post-V1 — but no coverage-relevant capability is *deferred*, only additional
   device profiles.)*

---
## Comparative additions (incumbent PEG platform gap closure → S18)
This section gains **GPI / serial (RS-232/422) + router/switcher control** with Take-Delay/Post-Roll
transition timing (S18 gap 8 — extends `ProductionDevice`/`DeviceProfile` + a `device_command` audit
on migration `0047`). See the S18 comparative appendix.
