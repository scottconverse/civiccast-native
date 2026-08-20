# Execution spec — session-0 native supervisor (`slice:ws5-supervisor`)

**Decision state: Proposed → revised per auditor design review SDR-002,
SDR-003, SDR-009. Not owner-approved.**

Charter §7 step 1. Session-0 viability proven (spike-session0).

## Decisions (v2)

- **D1. Language/runtime:** Python 3.12 + `pywin32` ServiceFramework.
  Production registers a real service; NSSM was spike scaffolding only.
- **D2. Process/ownership model (revised per SDR-003 — the seam preserves
  the production contract instead of breaking it):** the supervisor's DIRECT
  children are PostgreSQL, NATS, and the FastAPI control plane. **Media
  workers remain owned by the egress daemon inside the control plane**, spawned
  by `GstPlayoutStrategy.start()` exactly as production does today — the
  supervisor does NOT take over per-channel worker lifecycle, schedules,
  graphs, or captions; that contract already exists and is proven. What
  changes for Windows is ONE seam: the worker control channel. The POSIX FIFO
  (`os.mkfifo`, explicitly unavailable on Windows in `worker.py`) is replaced
  by a per-channel named pipe `\\.\pipe\civiccast-worker-<channel_id>` carrying
  the SAME line protocol (`parse_control_line` unchanged): `worker.py` gains a
  pipe-reader branch where the FIFO branch lives; the strategy gains a pipe
  writer. Same messages, same semantics (reload, swap, caption), same
  owner (the strategy holds the process handle and the pipe handle). Pipe
  ACL: SYSTEM + the service identity only — tighter than the FIFO it
  replaces; graph/secret temp files keep their existing protections.
  **Round-2 correction — acknowledged delivery, not fire-and-forget:** the
  current contract's "success" is an `os.write` return; written ≠ parsed ≠
  applied. The Windows transport therefore carries a versioned envelope:
  strategy → worker `{"v":1,"id":<uuid>,"cmd":"<existing line>"}`, worker →
  strategy `{"v":1,"id":<same>,"result":"applied"|"error","detail":...}` on
  the same duplex pipe after the engine applies the command. Bounded retry
  keyed by `id` (worker deduplicates ids — idempotent redelivery); a command
  unacknowledged past its deadline surfaces to the daemon as a channel
  error. **Per-verb delivery/replay policy (round-3 closure — the four
  `parse_control_line` verbs have different safety shapes):**
  - `reload` — at-least-once, idempotent; restart/reconnect reissues
    DESIRED STATE (current graph), never a command history;
  - `swap` (role) — at-least-once, idempotent; desired-state reissue
    (current role) on restart/reconnect;
  - `caption` — **at-most-once, never replayed**: cues are time-bound and a
    stale replayed cue is worse than a missed one; lost-ack or restart ⇒
    reported to the daemon as dropped, no redelivery;
  - `stop` — terminal, exactly-once-EFFECTIVE: an unacknowledged stop
    SUPPRESSES restart and desired-state replay (channel pinned stopping);
    resolution comes from observed process exit (the handle is ground
    truth), not from the ack; timeout escalates to the existing kill path.
  The inner command grammar is unchanged; the Linux FIFO path is untouched
  (WSL line stays as-is). Falsifications owed, PARAMETERIZED ACROSS ALL FOUR
  VERBS: lost ack, duplicate delivery, worker restart between write and
  apply, reconnect under multi-channel load — asserting reload/swap converge
  to desired state, caption drops rather than replays, stop never resurrects
  a channel.
- **D3. Containment (SDR-002):** the supervisor creates a Job Object with
  `KILL_ON_JOB_CLOSE` + breakaway disabled and assigns every child; workers,
  as descendants of the control plane, are captured automatically. Supervisor
  death ⇒ kernel kills the whole tree ⇒ SCM restarts the service ⇒ singleton
  named mutex (`Global\CivicCastSupervisorSingleton`) prevents duplicates; a
  starting supervisor also sweeps for stragglers by job-name/process-marker
  before spawning (defense in depth; expected to find none).
- **D4. Service account:** `LocalSystem` for the beta — **explicit owner-risk
  acceptance item in ADR-0021's register, not a default silently taken**
  (SDR-010). Least-privilege virtual account is a tracked follow-up. ACL
  table shipped with this slice regardless of account:
  `ProgramData\CivicCast\secrets` = SYSTEM+Administrators (no inheritance);
  `conf` = admin-write, service-read; `data\*` = service+admins; `logs` =
  service-write, admins-read, Users nothing; Program Files tree = default
  (admin-write, users-read).
- **D5. Restart policy:** exponential backoff 1s→30s ±20% jitter; ≥5 restarts
  /10 min ⇒ `degraded` (service stays up; alert via the existing alerting
  module — the Twilio/webhook path in `civiccast/alerting`, named here so
  "existing alerting" is checkable). Graceful-stop contracts, each with a
  15s deadline then `TerminateProcess`, each PROVEN by a dedicated test:
  - PostgreSQL: `pg_ctl stop -m fast` (documented, upstream-supported);
  - NATS: lame-duck mode (`nats-server --signal ldm=<pid>`), then terminate;
    JetStream durability proven by the falsification in AC-N4 (publish-ack'd
    messages survive stop/start);
  - control plane: CTRL_BREAK_EVENT to its process group (uvicorn graceful),
    deadline, terminate;
  - workers: owned by the strategy (D2) — the supervisor never signals them
    directly; stopping the control plane gracefully drains channels through
    the existing daemon shutdown path; the Job Object is the backstop.
- **D6. Startup order + readiness (measurable, SDR-009):**
  postgres → ready = `SELECT 1` (psycopg, 60s budget) →
  NATS → ready = **authenticated JetStream round-trip**: publish to a probe
  stream and receive the ack (TCP accept is explicitly NOT readiness) →
  control plane → ready = `GET /healthz` 200 with body reporting DB+NATS
  connectivity → (workers come up via the daemon as scheduled). State machine
  states: `starting / ready / degraded / blocked_wsl_active / stopping`,
  transitions logged with timestamps; "dependent behavior" = a child whose
  dependency leaves `ready` gets a controlled restart AFTER the dependency
  re-enters `ready`, with its own deadline — asserted in tests by state
  sequence, not vibes.
- **D7. Control pipe (SDR-002 authorization; round-2 platform corrections):**
  `\\.\pipe\civiccast-supervisor`, JSON-lines, `{"v":1}`. **Explicit
  security descriptor, never the default DACL** (defaults grant Everyone/
  anonymous read, and FILE_GENERIC_WRITE includes FILE_CREATE_PIPE_INSTANCE):
  SYSTEM + Administrators read/write; Authenticated Users read (status tier);
  explicit DENY for NETWORK (local-only); create-instance rights held by the
  service identity only. `FILE_FLAG_FIRST_PIPE_INSTANCE` is set for
  DETECTION, not prevention: if a rogue process pre-created the name, the
  service gets ERROR_ACCESS_DENIED — the defined fail-closed path is: log +
  Event Log entry naming the owning PID, enter `degraded` (children keep
  running; control unavailable), retry with backoff. Clients verify the
  server identity (SYSTEM) before sending any command, so a rogue endpoint
  can deny control but never impersonate it. 16 KiB frame cap;
  malformed/oversized frame ⇒ close connection. The singleton and
  runtime-owner GLOBAL objects carry the same explicit SD (SYSTEM+Admins
  only) so an unprivileged local process can neither forge ownership nor
  hold the station offline.
  **Two-tier authorization enforced per command, not per pipe:** the server
  impersonates the client (`ImpersonateNamedPipeClient`), extracts the token,
  and checks group membership: `status`/`version` require Authenticated
  Users; `start/stop/restart/drain/runtime set` require BUILTIN\Administrators
  (or SYSTEM). INTERACTIVE alone gets read-only. Every mutating command is
  audit-logged with the caller SID.
- **D8. Logging:** rotating `supervisor.log` (10 MB × 10) + per-child logs +
  Event Log source for lifecycle transitions.
- **D9. Guard integration:** D5-loop + pre-start evaluation per
  spec-dual-runtime-guard v2 (continuous, mutex-holding).

## Charter §7 session-0 obligations — explicit ACs (SDR-009)

- AC-S1 Firewall: installer/service creates the required inbound rules
  (portal/API ports); proven by netsh dump + a request from a CLEAN
  software-lab peer (second Sandbox/VM instance, class-6 per the owner
  testing policy); physical-network/device cases defer to LPM.
- AC-S2 Credential storage (round-2 correction — machine-scope DPAPI alone
  is decryptable by ANY local user per Microsoft, so it can never satisfy
  the denial criterion): secrets are protected by the D4 restrictive file
  ACL (SYSTEM+Administrators, inheritance off) as the MANDATORY layer, with
  DPAPI as optional defense-in-depth on top. Proven both directions: the
  service reads; a non-admin local user is denied.
- AC-S3 UNC/network-share media access under the service identity: schedule
  an asset from `\\share\...`; document the LocalSystem machine-account
  caveat and the tested outcome.
- AC-S4 Service-account permission audit: icacls dump of every D4 path in
  evidence.
- (GPU/DeckLink session-0 access remain LPM-lane items per testing policy.)

## Functional ACs

- AC1 Boot, no login: children ready in D6 order; a scheduled channel's
  worker (spawned by the daemon) produces output growth pre-login.
- AC2 Kill each direct child → recovery per D5 within budget; state
  transitions recorded; dependents follow D6 semantics.
- AC3 Restart-storm ⇒ `degraded`, service up, alert fired (assert against
  the alerting module's outbox/test transport).
- AC4 **Kill the SUPERVISOR mid-playout** (SDR-002): Job Object kills the
  tree (no orphan `postgres.exe`/`nats-server.exe`/python workers survive —
  asserted by process sweep), SCM restarts it, singleton mutex holds, full
  recovery to `ready`.
- AC5 Tauri console restart during playout: zero playout interruption.
- AC6 Worker control over the D2 named pipe on Windows: hot reload, source
  swap, caption cue — the decision-gate behaviors driven through the REAL
  strategy path (not SWAPS smoke mode), multi-channel.
- AC-N1 Unprivileged INTERACTIVE token: `status` succeeds, `stop` is DENIED
  (the exact hole SDR-002 named).
- AC-N2 Pipe pre-creation denial (renamed per round 2 — this is detection +
  fail-closed, not prevention): with a rogue process holding the pipe name,
  the service detects ERROR_ACCESS_DENIED, logs the owner, enters `degraded`
  with children unaffected, and recovers when the name frees; clients refuse
  to send to the rogue endpoint (server-identity check). A REAL pre-creation
  test, not a simulation.
- AC-N3 Malformed/oversized frames and command floods: connection closed,
  service healthy.
- AC-N4 JetStream durability: publish-ack'd messages survive `stop`/`start`
  of NATS via D5's graceful path.
- AC-N5 Concurrent conflicting commands (stop+restart+cutover): serialized
  or rejected deterministically; no torn state.

## Build steps

1. `civiccast/native/supervisor/`: config model, child state machine (pure,
   CI-tested), Job Object + mutex wrappers, pipe server with per-command
   token authorization, service shim.
2. Worker-pipe seam (D2): `worker.py` pipe branch + strategy pipe writer +
   Windows-marked tests (CI-skippable, dev-box-executed with evidence).
3. Windows integration script executing every AC above with captured
   evidence (spike-session0 verification pattern for the boot rows).

## Halt triggers

- Any need to touch `main`/rc-line.
- `pg_ctl` child semantics unworkable ⇒ ownership-story change ⇒ decision
  record before proceeding.
- The D2 seam turns out to require protocol changes beyond transport (new
  message types, ack semantics) ⇒ that is a versioned-contract design change:
  stop, write the contract addendum, get it reviewed before building.
