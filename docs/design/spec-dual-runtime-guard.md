# Execution spec — dual-runtime exclusion guard (`slice:ws4-dual-runtime-guard`)

**Decision state: Proposed → revised per auditor design review SDR-001
(audit-control reviews/2026-07-17-specs-design-review.md). Not owner-approved.**

Charter §6 / gate 4. The hazard: both runtimes transmit on one machine.
Charter requires BIDIRECTIONAL refusal before any side-by-side install.

## Decisions (v2 — reconciled with SDR-001)

- **D1. Authoritative selector:** `HKLM\SOFTWARE\CivicCast\ActiveRuntime` =
  `wsl` | `native`. Machine-global, admin-writable only, host-owned. Absent ⇒
  `wsl` if any CivicCast WSL install is detected, else `native`.
- **D2. "Installed" is not "active" (fixes the impossible state).** A
  registered distro is ROLLBACK MEDIA, never by itself a refusal condition.
  Refusal conditions are ACTIVITY, not presence:
  - A1: a live keeper process (Windows-side `wsl.exe` argv carrying the
    keeper marker) or keeper `Run` entry in any LOADED hive **combined with**
    `ActiveRuntime != native`;
  - A2: in-distro CivicCast services active
    (`wsl -d <distro> systemctl is-active 'civiccast*'`, 5s bound);
  - A3: failure to acquire the ownership mutex (D4).
  Distro-registered-but-quiescent with `ActiveRuntime=native` is the NORMAL
  post-cutover state and starts natively without friction.
- **D3. One decision table (fixes the contradictory ambiguity policy).**
  | Selector | Activity probes | Result |
  |---|---|---|
  | native | all negative | start |
  | native | any POSITIVE (A1–A3) | refuse, name the probe |
  | native | A1 error/timeout, A2 readable-negative | start + log `probe-degraded`, re-probe per D5 |
  | native (explicitly written) | **A2 unreadable/timeout** | **AMENDED 2026-08-01 (chain I, owner-decided): `start_degraded` naming A2 + a structured supervisor WARNING, re-probe per D5** — see the amendment note below |
  | wsl | — | never start natively |
  | absent | WSL install detected | refuse + instruct (set selector or run cutover) |
  | absent | no WSL install | start (treat as native) |
  | absent (treated as native) | **A2 unreadable/timeout** | **NON-AUTHORIZING: `blocked_probe_unavailable`, bounded retry (10s), alert after 3** — unchanged |
  A positive probe is never overridden by the selector toward double
  transmission; an *error* is never escalated into a permanent both-stopped
  deadlock. Exactly one row applies to every state.

  **Amendment 2026-08-01 (chain I, owner-decided) — the `native` + "A2
  unreadable" row.** Its original verdict was `blocked_probe_unavailable`,
  justified as "A2 is the WSL-transmitter lifetime proof; transmission never
  starts on its absence". Real-hardware evidence (R7 request 0052) showed the
  cost: a correctly installed native station with no WSL on the machine at all
  never started its control plane, because on a WSL-less box `wsl.exe` is the
  OS inbox stub and every A2 invocation is unreadable. The decided resolution
  does not weaken the hazard boundary, it names the authority the boundary was
  always asking for: `ActiveRuntime` (D1) is *the* mechanism this spec defines
  for establishing which runtime owns the machine — the guard's own blocked
  message says the missing thing is "the authority basis for a native start" —
  so an EXPLICIT, validly-read `ActiveRuntime = "native"` supplies it. In that
  one cell an A2 the guard could not READ degrades the start (D3 row 3's
  existing `probe-degraded` vocabulary) and is recorded as a structured
  supervisor WARNING, instead of withholding the station.

  Everything else is unchanged and separately pinned:
  `absent`-treated-as-native still blocks (no selector was ever written, so
  there is no authority artifact); a READABLE A2 `positive` under `native`
  still refuses (a real conflict, not probe noise); D4's mandatory
  abandoned-mutex A2 re-verify still blocks; and D5 continuous enforcement is
  untouched — `start_degraded` is an authorizing action, so the monitor keeps
  re-probing every interval and a later positive A2 still triggers the
  controlled stop. A differential test over the full 3888-point enumeration
  asserts the change moves EXACTLY 18 points and nothing else
  (`tests/native/test_guard_table.py::
  test_chain_i_changes_exactly_the_one_decided_cell_and_nothing_else`).

  Consequence, stated plainly: AC9's "alert after 3" no longer fires for this
  cell, because the cell no longer produces `blocked_probe_unavailable`. The
  alert mechanism itself is unchanged and still proven on every cell that does
  block; the degraded start's own visibility is the per-spawn WARNING.
- **D4. Enforcement lives at the TRANSMITTER, not its babysitter (round-2
  correction).** The in-distro `civiccast.service` is enabled with
  `Restart=always`: its lifetime is NOT the keeper's lifetime, so a
  keeper-held mutex cannot carry the WSL side's refusal. The WSL-side patch
  therefore goes into the SERVICE's own start path: an
  `ExecCondition`/`ExecStartPre` that reads the host selector (via
  `/mnt/c ... reg.exe query`) and the D7a maintenance interlock, and refuses
  BEFORE transmission when `ActiveRuntime=native`, when the interlock is
  held, or when the authority CANNOT be read (fail-closed on the WSL side —
  a transmitter that can't check permission doesn't transmit). systemd
  re-evaluates the condition on every start attempt including
  `Restart=always` restarts, which is exactly the property the keeper lacks.
  The Windows named mutex `Global\CivicCastRuntimeOwner` remains as a
  SECONDARY fast-path between the native supervisor and the patched keeper,
  with an explicit security descriptor (SYSTEM + Administrators full, no
  Everyone — an unprivileged local process must be unable to acquire it and
  hold the station offline). An ABANDONED mutex is never treated as free:
  the acquirer must additionally verify A2 (in-distro service inactive)
  before starting transmission, per Microsoft's abandoned-mutex
  indeterminacy caution.
- **D5. Continuous enforcement:** the supervisor re-evaluates A1/A2 every 30s
  and before every child (re)start. A positive probe mid-operation triggers a
  controlled stop of transmission children and `blocked_wsl_active` state
  (status pipe + console visible). Startup is just the first evaluation.
- **D6. Bidirectional refusal is a GATE-4 PREREQUISITE, not a follow-up.**
  This slice delivers: (a) the native half; (b) the WSL-keeper patch (mutex
  acquisition + `ActiveRuntime=native` refusal + in-distro stop command),
  ready for the rc line. Gate-4 advancement and ANY co-install require the
  owner to have landed (b) in the shipping WSL product first — recorded as an
  explicit prerequisite, never waived by this program. Native installs on
  machines WITHOUT any WSL CivicCast install don't wait (nothing to exclude),
  which is what unblocks clean-machine beta work in parallel.
- **D7a. Maintenance/freeze interlock (shared with the migration spec):** a
  journaled interlock record (`HKLM\SOFTWARE\CivicCast\Maintenance` value +
  generation counter + owner run-ID) that EVERY start path honors — the
  native supervisor, the patched keeper, and the patched in-distro
  `ExecCondition`. While held, neither runtime starts transmission. This is
  the enforceable freeze SDR-007 requires and the transfer bracket cutover
  runs inside.
- **D7. Cutover command** (`civiccast-runtime cutover-to-native`, admin):
  journal-backed phases, each idempotent and resumable: (1) in-distro
  disable+stop of CivicCast services; (2) keeper `Run` entry removal from
  every LOADED hive; unloaded profiles are ENUMERATED into the cutover
  evidence AND the patched keeper's selector check (D6b) covers any that
  later log in — the resurrection path is closed by the patch, not by hive
  surgery; (3) selector := native; (4) distro retained as rollback media;
  (5) evidence file (timestamps, probe results, removed entries, unloaded
  profiles) under `ProgramData\CivicCast\logs\`. Partial failure at any phase
  leaves the journal consumable by re-run; falsification required per phase.
- **D8. Rollback command** mirrors D7 (stop native children → selector :=
  wsl → re-enable in-distro services → keeper restore for the invoking user),
  requires `--ack` carrying the post-activation data boundary statement
  (native-era rows/media do not flow back; recovery point = pre-cutover
  migration backup).

## Build steps

1. `civiccast/native/runtime_guard.py`: selector I/O, activity probes A1–A3,
   the D3 decision table as a pure function (unit-tested exhaustively —
   every selector × probe-state row, including error/timeout rows and
   abandoned-mutex), mutex acquisition wrapper.
2. CLI verbs + supervisor integration (D5 loop + pre-child-start checks).
3. WSL-keeper patch (D6b) as a ready diff + tests in slice evidence — NOT
   applied to any branch by this program; owner routes it to the rc line.
4. Windows integration tests: real `wsl.exe` where available; where the
   probe target can't exist in CI, the seam is the probe layer and the REAL
   probes get dev-box integration runs recorded as evidence (fixture-only
   proof is explicitly insufficient — SDR-001).

## Acceptance criteria (falsifications are the criteria)

- AC1 Retained-but-quiescent distro + selector=native → native starts.
- AC2 Live keeper (real `wsl.exe` on the dev box) → native refuses, names A1.
- AC3 Keeper starts AFTER native is up → D5 detects within 30s, transmission
  children stop, state=blocked; keeper patched-half meanwhile refuses via D4
  mutex (dev-box two-process test using the real mutex).
- AC3b **In-distro service starts WITHOUT the keeper** (direct
  `wsl -d <distro> systemctl start`, and distro-boot autostart): the
  ExecCondition refuses while `ActiveRuntime=native`; and with the selector
  unreadable (interop off) it also refuses (WSL-side fail-closed proof).
- AC3c **Keeper crash while the in-distro service stays alive**: native must
  NOT start on the abandoned/free mutex alone — A2 verification blocks it
  until the service is actually inactive.
- AC4 Both start orders with the patched keeper: exactly one side ever owns
  the mutex; the loser reports the winner. An unprivileged token attempting
  to acquire either global object is DENIED (security-descriptor control).
- AC5 Cutover: each phase interrupted (kill mid-phase) then resumed completes
  correctly; evidence lists unloaded profiles; post-cutover boot is AC1.
- AC6 Rollback: refuses without `--ack`; with it, WSL line returns to
  service; boundary statement in transcript.
- AC7 Selector tampering mid-operation (flip to wsl while native transmits) →
  D5 controlled stop within one probe interval.
- AC8 Negative control: decision function stubbed always-allow → AC2 red.
- AC9 **Live keeperless WSL service + injected A2 timeout → native NEVER
  starts** (enters `blocked_probe_unavailable`); A2 restored-negative →
  native starts (the round-3 fail-open closure, proven both directions).

## Halt triggers

- Keeper registration surfaces beyond HKCU Run discovered → inventory, extend
  A-probes, re-review.
- The mutex contract can't be honored on the WSL-keeper side for any reason →
  gate 4 stays closed; surface to owner. No co-install without D6.
