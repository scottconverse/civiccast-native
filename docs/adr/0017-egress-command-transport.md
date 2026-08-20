# ADR 0017 - Egress command transport starts with durable polling

**Status:** Accepted
**Date:** 2026-06-05
**Deciders:** Scott Converse, CivicCast engineering
**Related rung:** E.1 - One file to one SRT sink, supervised; E.3/E.4 operator control and recovery
**Related spec section:** Channel Egress Engine build plan, Section 7 command transport and Section 18 required ADRs
**Supersedes:** None
**Superseded by:** None

---

## Context

CivicCast egress splits control plane from data plane. The web app writes
operator intent, and the egress daemon reads that intent while running as its
own long-lived process. This prevents the staff API process from owning FFmpeg
or blocking the web request path.

The implementation already has a durable command row contract:
`EgressCommand` carries `start`, `stop`, `reload`, and `drain`, and
`EgressService` calls `pop_pending_commands` on each daemon tick. The open
transport decision is whether the daemon should keep this polling loop or move
to Postgres `LISTEN/NOTIFY`.

Start, stop, drain, and reload are low-volume operational commands for a
24-hour channel. A few seconds of command latency is acceptable. Losing a
command is not acceptable, and adding a second persistent database connection
with notification reconnect logic would make the daemon harder to reason about
before egress has finished its continuity and recovery gates.

## Decision

CivicCast will ship the egress command transport as durable database polling.
The staff API enqueues command rows. The daemon periodically calls
`pop_pending_commands(channel_id)` and marks consumed rows. Polling is the
release default.

Postgres `LISTEN/NOTIFY` remains a future optimization only. It may be added
later if real operators report that command latency is a problem, but it must
not replace the durable command row as the source of truth.

## Alternatives considered

**Option A - Durable polling.** The daemon polls the command table on its normal
tick. This is simple, durable across web-app restarts, easy to test with the
existing store protocol, and operationally sufficient for start/stop/reload
latency. This is the selected option.

**Option B - Postgres LISTEN/NOTIFY.** Notifications could wake the daemon
faster, but they add notification connection lifecycle, reconnect handling, and
missed-notification recovery. Because the command row must still exist for
durability, this is an optimization rather than a simpler architecture.

**Option C - Direct web-app call into the daemon.** The web app could call an
in-process or local RPC daemon method. This violates the control-plane/data-plane
split, complicates multi-host deployment, and risks tying channel playout to
web request lifecycle.

## Consequences

### Positive

- Commands survive web-app restarts and daemon restarts.
- Tests can exercise command behavior through the same `EgressStore` protocol
  used by production.
- The daemon has one simple main loop: poll commands, reconcile process state,
  write state and health.
- Operators do not need any additional message-bus service for egress.

### Negative

- Commands are not instant; latency is bounded by the daemon poll interval.
- The command table needs retention or cleanup after rows are consumed.
- If future operators demand sub-second control response, polling alone may
  feel slower than necessary.

### Risks

- A future developer may add `LISTEN/NOTIFY` and accidentally rely on
  notifications as the source of truth. Mitigation: the command row remains the
  durable contract, and any notification path must only wake a poll.
- A too-long poll interval could make stop/reload feel unresponsive. Mitigation:
  the default service poll interval remains small and configurable.

## Compliance

- The staff API must enqueue durable `EgressCommand` rows rather than invoking
  FFmpeg or daemon methods directly.
- The daemon/service loop must consume commands through `pop_pending_commands`.
- `LISTEN/NOTIFY`, if added later, may only wake or accelerate polling; it must
  not become the only command delivery mechanism.
- Operator-facing docs should describe start/stop/reload as commands handled by
  the background egress service, not as immediate web-app actions.

## References

- `civiccast/egress/models.py` - `EgressCommand`.
- `civiccast/egress/service.py` - polling service loop.
- `civiccast/egress/daemon.py` - command processing.
- `docs/spec/2.0/channel-egress-engine-build-plan.md`
- `docs/adr/0008-database-session-pattern.md`
- `docs/adr/0015-egress-continuity-mechanism.md`

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR
that references this one.*
