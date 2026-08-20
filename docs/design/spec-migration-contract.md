# Execution spec — WSL→native migration contract (`slice:ws6-migration`)

**Decision state: Proposed → revised per auditor design review SDR-007,
SDR-010. Not owner-approved. The NATS-state and downtime-window items below
are explicit OWNER-ACCEPTANCE entries, not settled facts.**

Charter §7 "Migration". Beta-scale: backup → native install → restore; the
WSL line is the named rollback. No generalized in-place framework.

## Decisions (v2)

- **D1. Coherent snapshot via an ENFORCED freeze (SDR-007, round-2
  precision).** Migration begins with a station-offline window
  (owner-accepted downtime): stop all CivicCast APPLICATION services and
  workers in the distro — **PostgreSQL itself stays up, serving solely the
  migration connection** (pg_dump needs a live server; "stop all services"
  is never executable as "stop the database"). Quiescence is verified
  (no CivicCast processes; `pg_stat_activity` shows only the migration
  connection). The freeze is not a one-shot observation: the D7a maintenance
  interlock from the guard spec (registry record + generation counter,
  honored by the native supervisor, the patched keeper, AND the patched
  in-distro ExecCondition) is taken FIRST and held through ownership
  transfer, so a transient start-write-stop during migration is prevented at
  the start paths, not just hoped against; the final no-write check
  re-verifies snapshot equality AND that the interlock generation never
  changed.
- **D2. Database:** WS2 machinery, second execution per charter §5 — dump +
  globals from the WSL Postgres (clients from the NATIVE package so client ≥
  server), restore into the native cluster, then the FULL WS2 equivalence
  verification (tables/checksums/sequence state/constraints/indexes/grants/
  extensions/alembic head/app read-through/globals coverage). Independent
  evidence; inherits nothing from the drill's own runs.
- **D3. Media (fixes the executed falsification in SDR-007):** copy
  `\\wsl$\<distro>\<media-root>` → `ProgramData\CivicCast\media` with
  `robocopy` WITHOUT `/MIR` (no deletion semantics) after ASSERTING the
  destination is empty (fresh native install ⇒ it must be; a non-empty
  destination halts with an operator-reviewed listing — deletion is never
  implicit). Verification = **full-file SHA-256 on BOTH sides, every file**
  — the bounded head+tail fingerprint (`build_media_manifest`) is for drift
  monitoring, NOT for one-time migration integrity; the auditor proved a
  middle-byte corruption passes it. One-time full hashing cost is accepted
  and measured (beta-scale libraries; hours at worst, recorded).
- **D4. Config/secrets:** inventory built from the RUNTIME READ SET — what
  the services actually consult (env files referenced by systemd units,
  config paths the app opens, operator-added overrides, external/cert
  paths) — with the installer bootstrap's write list used as a SEED to
  cross-check, never as the authority (round-2 correction: the historical
  write list misses operator additions). Unexplained reads or unread writes
  are reconciled in evidence. Translate paths via the recorded map; secrets
  land in `secrets\` with verified ACLs (SYSTEM+Admins, inheritance off,
  post-copy icacls in evidence); every translated key enumerated.
- **D5. Path rewrite:** one idempotent script over DB-stored media paths;
  dry-run prints every row; applied count must equal dry-run count (AC3).
- **D6. NATS JetStream — OWNER DECISION, evidence first (SDR-010):** step 1
  of implementation is a stream-catalog inventory proving what actually
  lives in JetStream durably. Only after that inventory does the owner
  accept/reject the discard posture ("fresh JetStream on native; in-flight
  events lost"). The spec RECOMMENDS discard based on the DB-is-record
  design, but does not settle it. If the inventory finds durable
  public-record data in streams: HALT, re-spec.
- **D7. Resume integrity (SDR-007):** the runbook journal binds every
  completed step to: run ID, source identity (distro name + DB cluster ID),
  destination identity, the step's input manifest hashes, tool versions, and
  a re-checkable postcondition. `--resume` re-verifies postconditions before
  skipping; stale or mismatched-identity evidence forces the step to re-run.
- **D8. Ownership transfer & rollback:** WS4 cutover is the final step;
  rollback per WS4 with the pre-cutover backup as the recovery point.
  Rehearsal (full dry-run AND rollback rehearsal) on a WSL-carrying test
  environment BEFORE LPM; LPM cutover is owner-gated (charter gate 7).

## Acceptance criteria

- AC1 Rehearsal end-to-end from a quiesced source: native station plays the
  same schedule/media; D2 verification green; media full-hash sets equal.
- AC2 Rollback rehearsal returns WSL to service; boundary statement present.
- AC3 Path-rewrite dry-run count == applied count.
- AC4 **Middle-byte corruption of one copied file → full-hash comparison
  names it** (the auditor's executed falsification, now caught).
- AC5 Concurrent-start attempt during the freeze window (manual
  `systemctl start` + distro restart mid-migration) → **REFUSED at the start
  path by the D7a interlock; zero writes occur** (that is D1's contract).
- AC5b Defense-in-depth control: with the interlock deliberately
  bypassed/corrupted (test hook), the D1 final no-write check catches the
  resulting drift and halts the migration — proving the final check is a
  real second layer, not the primary mechanism.
- AC5c Operator-added config file OUTSIDE the bootstrap write list →
  discovered by the D4 runtime-read-set inventory (seeded fixture).
- AC5d Source file mutated DURING the full-hash pass → the hash comparison
  detects it (re-verify pass mismatch), migration halts.
- AC5e Resume with a reused step identity but CHANGED content → postcondition
  re-check forces the step to re-run (stale evidence never skips work).
- AC6 Interrupted copy/restore/rewrite at each step → resume re-verifies and
  completes; a tampered journal entry (wrong hash) forces re-run.
- AC7 Destination-not-empty → halt with listing (no deletion ever).
- AC8 Disk-full during media copy and a >260-char path: defined failures
  with operator guidance (long-path support enabled and tested).
- AC9 Secret ACL check: non-admin read of a migrated secret DENIED.

## Halt triggers

- D6 inventory finds durable public-record data in JetStream.
- WSL pg major version > native packaged pg version.
- Any pressure to skip the freeze window: the coherent snapshot IS the
  contract; a no-downtime migration is a different (unchartered) product.
