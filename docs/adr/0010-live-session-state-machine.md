# ADR 0010 -- Live session state machine: forward-only transitions via conditional UPDATE

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Scott Converse (human director)
**Related rung:** 0.4 -- Broadcast spine and contracts (Slice 1)
**Related spec section:** Live broadcast lifecycle (`docs/research/v04-slice1-broadcast-spine-design.md`); v0.4 scope-lock §1 "Required Content"
**Supersedes:** N/A
**Superseded by:** N/A
**Closes:** N/A (new ADR; documents the state-machine pattern Slice 1 ships)

---

## Context

Slice 1 of rung 0.4 introduces the live-broadcast spine. A `LiveSession` row tracks one operator-driven broadcast from creation through preflight, on-air, ending, and finalized-as-recording. The states are:

| State | Meaning |
|:------|:--------|
| `idle` | Session row created; not yet preflighted. |
| `preflight` | Pre-flight checklist running; not yet on air. |
| `on_air` | Live broadcast in progress. |
| `ending` | Operator clicked End; finalization in progress. |
| `recorded` | Finalization complete; an asset row exists at state `recorded`. |

The state machine has three correctness requirements:

1. **Concurrent writers must not both succeed.** Two operators racing the same transition produce exactly one winner; the loser raises a structured error.
2. **State drift between read and write must be impossible.** A naive "read state, check it equals what we expect, write new state" sequence races against a third writer who flips state between the read and the write.
3. **Every transition is auditable.** A future agent walking the run-log must be able to see which transition fired when, and what state preceded it.

The audit-team v0.3.0 pass and the v0.4 design note both call out that this is the most correctness-sensitive surface in Slice 1: every other Slice 1 piece (preflight evaluator, staff API, recording finalization) consumes the state and trusts its transitions. A bug here cascades.

## Decision

Implement state transitions as **conditional UPDATE statements** whose `WHERE` clause filters on the expected current state. The pattern is:

```sql
UPDATE civiccast.live_sessions
   SET state = '<new-state>', <optional setters>
 WHERE live_session_id = :id
   AND state = '<expected-state>'
```

The transition's success is determined by the cursor's `rowcount`:

- `rowcount == 1` -- the transition committed; return the updated row.
- `rowcount == 0` -- either the row doesn't exist or it's in a different state. Re-read to distinguish, then raise the matching domain exception (`LiveSessionNotFoundError` or `LiveSessionStateError`).

The transitions are **forward-only**: `idle -> preflight -> on_air -> ending -> recorded`. There is no `cancel_preflight` or `back-to-idle` transition in Slice 1. Operator-cancel semantics are tied to the preflight evaluator's contract; introducing a backwards transition without a UX-validated cancel flow would commit to semantics ahead of the contract. A future commit can add cancel transitions when the operator UI lands in Slice 2.

The transition set lives in a module-private `_TRANSITIONS` dict at `civiccast/live/store.py`:

```python
_TRANSITIONS: dict[str, tuple[str, str]] = {
    "start_preflight": (LIVE_SESSION_STATE_IDLE, LIVE_SESSION_STATE_PREFLIGHT),
    "go_on_air":       (LIVE_SESSION_STATE_PREFLIGHT, LIVE_SESSION_STATE_ON_AIR),
    "end_broadcast":   (LIVE_SESSION_STATE_ON_AIR, LIVE_SESSION_STATE_ENDING),
    "mark_recorded":   (LIVE_SESSION_STATE_ENDING, LIVE_SESSION_STATE_RECORDED),
}
```

Each public method on `LiveSessionStore` (`start_preflight`, `go_on_air`, `end_broadcast`, `mark_recorded`) delegates to a shared `_transition` helper that runs the conditional UPDATE + rowcount check.

### Concurrency proof

The proof that two concurrent transitions on the same session produce exactly one winner lives in `tests/live/test_real_postgres.py::TestRealPostgresLiveSessionStateMachineConcurrency::test_two_concurrent_start_preflight_exactly_one_wins`. Two threads, two engines, one `threading.Barrier(2)` synchronizing them at the moment of UPDATE. Postgres's row-level write lock serializes the UPDATEs; one returns `rowcount=1` (commits), the other returns `rowcount=0` after the winner's commit (because the WHERE predicate no longer matches the post-commit state), re-reads, and raises `LiveSessionStateError` with `current_state="preflight"`.

The SQLite test path in `tests/live/test_store.py` cannot demonstrate true row-level contention (SQLite serializes all writers at the database level). The single-session control-flow tests there cover every transition's happy + illegal-state + missing-session paths, but the actual race-proof requires real Postgres.

## Consequences

**Positive:**

- Single-source-of-truth for which transitions exist and which states are expected (`_TRANSITIONS` dict).
- Race-safe by construction. No application-layer locking needed.
- Failure modes carry structured error data (`current_state`, `attempted_transition`, `live_session_id`) so the router maps them to actionable 404 / 409 responses without re-querying.
- The pattern generalizes. Recording finalization (Slice 1 Commit 7) uses the same conditional-UPDATE approach for the `ending -> recorded` write inside the broader idempotent-finalization transaction.

**Negative:**

- The transitions are not freely reorderable. A future feature that wants to allow operator-cancel from any state has to either add new transitions to `_TRANSITIONS` (with their own `WHERE` clauses) or restructure into a more general state-graph abstraction. The Slice 1 design accepts this rigidity in exchange for the simplicity of "one dict, four transitions."
- The error path requires a re-read on `rowcount=0`. That's an extra query per failed transition. For the failure case this is fine; the success case is one query.
- Audit trail of past transitions is not stored on the LiveSession row itself. The `live_session_events` table (ADR 0011) records `session.finalized` events; future commits may add `session.started` and `session.ended` events to the same table for full audit coverage. For Slice 1 only the finalized event is emitted.

## Alternatives considered

### Optimistic concurrency with a version column

Add a `version` integer to `LiveSession`, increment on every transition, accept `expected_version` from the caller. This is the pattern v0.3 uses on `Asset.update_metadata` (QA-008).

Rejected for Slice 1 because:
- The state machine has 5 states and 4 explicit transitions. The valid `(current_state, new_state)` pairs are a small enum, not a version-counter scalar. A version-counter approach loses the structured "which transition were you trying?" error data.
- The operator UI calls transitions in response to button clicks, not after reading a stale snapshot. The OCC pattern's "you've been preempted by a more recent write" semantic isn't quite right; the better semantic is "the session isn't in the state your transition expects."

A version column may still land in a later rung if cross-cutting concerns (e.g., a public API consumer wants to subscribe to state changes) demand it. The conditional-UPDATE pattern doesn't preclude it.

### Database-level enum + trigger-enforced transitions

Define `live_session_state` as a Postgres ENUM type and add a per-row trigger that allows only the four valid transitions. Centralizes the rule at the DB layer.

Rejected because:
- The ORM layer (SA + Alembic) handles enums awkwardly. Migrations to add a new enum value require multiple steps.
- The trigger logic would duplicate `_TRANSITIONS` in PL/pgSQL, doubling the source of truth and risking drift between the Python rule and the DB rule.
- SQLite (the test path) has neither enums nor triggers as we want them. We'd lose test parity.
- The conditional-UPDATE pattern is already race-safe; the trigger adds belt-and-suspenders for application-layer bypasses that don't exist in our code.

If a future deployment surfaces an application-layer bypass concern (e.g., a CLI tool that writes state directly), the trigger can be added as a defense-in-depth layer without restructuring the application logic.

### Saga-style explicit-event approach

Instead of mutating `LiveSession.state`, emit events to `live_session_events` and derive the state at read time by replaying events.

Rejected because:
- Slice 1's read path (router, preflight evaluator, finalizer) is hot. Replaying events on every read is more expensive than reading a single column.
- The `live_session_events` table exists for a different purpose (recording-finalization idempotency, ADR 0011). Overloading it as the system-of-record for state would couple two concerns that benefit from separation.
- The structural state machine is small enough (5 states) that the saga overhead isn't justified.

A future rung that needs cross-session event-sourcing semantics (e.g., resilient distributed broadcast with multiple replicas) can adopt a saga approach without breaking the v0.4 contract; the saga layer would consume the same `live_session_events` rows.

## References

- `civiccast/live/store.py` -- `LiveSessionStore` + `_TRANSITIONS` dict + `_transition` helper.
- `civiccast/live/models.py` -- `LiveSession` SA model + state constants + `live_sessions_state_check` CHECK constraint.
- `civiccast/live/migrations/versions/0007_live_sessions.py` -- creates the table + CHECK.
- `tests/live/test_store.py` -- single-session control-flow tests (count grows with the module; run the file for the current number).
- `tests/live/test_real_postgres.py::TestRealPostgresLiveSessionStateMachineConcurrency` -- two-thread race-proof.
- `docs/research/v04-slice1-broadcast-spine-design.md` -- design note.
- v0.4 scope-lock §1 line 124 -- "Live session model: a `LiveSession` SQLAlchemy entity with state machine `idle -> preflight -> on-air -> ending -> recorded`."
- ADR 0011 (this rung) -- recording finalization transactional event, which composes the `ending -> recorded` transition with an idempotent event + asset insert.
