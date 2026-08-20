# ADR 0011 -- Recording finalization: idempotent transactional event + asset insert

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Scott Converse (human director)
**Related rung:** 0.4 -- Broadcast spine and contracts (Slice 1)
**Related spec section:** Recording finalization contract (`docs/research/v04-slice1-broadcast-spine-design.md` § "Finalization Event Design"); v0.4 scope-lock §1 line 129
**Supersedes:** N/A
**Superseded by:** N/A
**Closes:** N/A

---

## Context

A live broadcast ends with the operator clicking End. The system has to:

1. Persist a record that the session was finalized.
2. Create an `assets` row at state `recorded` so the recording appears in the operator's asset library.
3. Advance `LiveSession.state` from `ending` to `recorded`.

All three must happen atomically: a crash between any two of them leaves an inconsistent partial state (an event with no asset; an asset with no event; a recorded LiveSession without an asset to play). The crash window is real -- the live module can die mid-finalize, a network partition can cut the orchestrator off, the operator can hard-quit Cowork between the asset write and the state advance.

Additionally, finalization must be **idempotent**. If the same `session.finalized` event fires twice -- because the live module crash-restarted before the first attempt's transaction committed, or because a worker retries the finalization, or because a future caller invokes the finalizer redundantly -- the second invocation must NOT produce a second asset row. The asset library must contain exactly one recording per finalized live session.

The audit-team v0.3.0 deep-dive and the v0.4 design note both flagged this as the single highest-risk contract in Slice 1. Every later slice (Slice 2 operator live room, Slice 3 resident portal, Slice 4 trim precision) consumes the asset that this contract produces. A duplicate asset, a missing asset, or a stale-state asset cascades through every downstream surface.

## Decision

Adopt a **transactional persisted-event pattern**: the `session.finalized` event row, the asset row, and the `LiveSession` state advance all commit in **one Postgres transaction**. Idempotency is structurally enforced via the event table's **composite primary key**.

### Event table shape

New table `civiccast.live_session_events` (migration `0008_finalization_spine`):

| Column | Type | Notes |
|:-------|:-----|:------|
| `live_session_id` | `String(64)` | FK target |
| `event_type` | `String(32)` | CHECK: in (`session.started`, `session.ended`, `session.finalized`) |
| `event_seq` | `Integer` | monotonic per session, starts at 1; CHECK >= 1 |
| `payload_json` | `Text` | nullable; serialized JSON payload (recording_uri, duration_seconds, finalized_at) |
| `created_at` | `DateTime(tz=True)` | `server_default=now()` |

**Primary key:** composite `(live_session_id, event_type, event_seq)`. The PK IS the idempotency gate -- a duplicate `(session, 'session.finalized', 1)` insert collides on the PK and the entire transaction rolls back. No separate UNIQUE constraint is needed.

### Asset row link

New column `civiccast.assets.source_live_session_id` (nullable, `String(64)`). Set on finalization-derived assets; `NULL` for uploaded assets.

**Partial unique index** `assets_source_live_session_unique` enforces "at most one asset per source live session" via `WHERE source_live_session_id IS NOT NULL`. This is defense-in-depth against an application-layer bypass: if a future caller forgets the event-row uniqueness path and writes an asset row directly, the partial unique index still rejects the second one.

### Finalizer transaction shape

`civiccast/live/finalization.py::LiveRecordingFinalizer.finalize_recording(live_session_id, *, recording_uri, duration_seconds, finalized_at)`:

```python
with self._session_factory() as session:
    # 1. Verify session exists + is in 'ending' state (fast-path the
    #    duplicate-finalize case if state is already 'recorded').
    live_session = session.execute(SELECT...).scalar_one_or_none()
    if live_session is None:
        raise LiveSessionNotFoundError(...)
    if live_session.state == LIVE_SESSION_STATE_RECORDED:
        return _build_idempotent_result(...)   # state is already past
    if live_session.state != LIVE_SESSION_STATE_ENDING:
        raise LiveSessionStateError(...)

    # 2. Stage three writes inside the same transaction.
    session.add(LiveSessionEvent(event_type='session.finalized', event_seq=1, ...))
    session.add(Asset(state='recorded', source_live_session_id=..., ...))
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        return _handle_integrity_error(session, ..., exc)
        # Differentiates event-PK collision (idempotent path) from
        # asset-PK collision (LiveRecordingAssetCollisionError).

    # 3. Conditional state advance (per ADR 0010 pattern).
    update_result = session.execute(
        UPDATE live_sessions SET state='recorded'
         WHERE live_session_id=:id AND state='ending'
    )
    if update_result.rowcount != 1:
        session.rollback()
        raise LiveSessionStateError(...)

    # 4. Commit.
    session.commit()
    return FinalizationResult(asset=..., event=..., idempotent=False)
```

### Idempotency proof

The proof that two concurrent finalizers produce exactly one asset row + one event row is at `tests/live/test_real_postgres.py::TestRealPostgresFinalizationIdempotency::test_two_concurrent_finalize_recording_calls_produce_one_asset`. Two threads, two engines, `threading.Barrier(2)`. One wins (returns `idempotent=False`), the other catches the IntegrityError on its event INSERT, rolls back, re-queries, and returns `idempotent=True` referencing the winner's rows.

## Why this and not NATS

A pub-sub message bus is the canonical "fire an event" pattern. CivicCast's ADR 0001 commits to NATS JetStream as the eventual event bus. For finalization, NATS was rejected for Slice 1 because:

1. **No deployment runs NATS yet.** Adding NATS to the v0.4 deployment is a substrate decision that requires its own ADR + an operator-facing install step (spec section 5.3). Slice 1's scope is the broadcast spine, not the messaging substrate.

2. **The use case is transactional, not pub-sub.** Finalization has one producer (the finalizer) and one consumer (the asset library, in the same process). The atomic guarantee "event + asset commit together or neither commits" is what we want. NATS doesn't give that -- NATS gives at-least-once delivery, which would require a separate idempotency mechanism on the consumer side anyway. Two idempotency mechanisms is worse than one.

3. **NATS belongs in cross-transaction, cross-module rungs.** Captions (rung 0.5), syndication (rung 0.7), archive (rung 0.7), and subscriptions (rung 0.8) are multi-subscriber and inherently cross-transaction. NATS will land when those rungs need it.

The transactional event row is the right pattern for *this* use case. Future rungs add NATS for *those* use cases. Both can coexist.

## Why not just a unique constraint on `assets.source_live_session_id` alone

The partial unique index on `assets.source_live_session_id` (defense-in-depth) is necessary but not sufficient. Without the event row:

- A retry that's "still pending" would have no way to know its previous attempt is in flight; it would race to INSERT an asset and the unique index would arbitrate. The loser would not be able to recover the winning attempt's payload (duration, recording_uri) -- they'd have to re-query and reconstruct.
- A future feature wanting "what was the most recent finalization event for session X" has no event log to walk.
- The audit trail is lost. An asset with `source_live_session_id` set tells you it came from a live session; the event row tells you when, with what payload, and (if seq > 1) whether finalization was retried.

The event row IS the audit trail. The asset row is the application's view. They're separate concerns.

## Consequences

**Positive:**

- Single atomic transaction. No partial state.
- Idempotent by construction. Composite-PK collision is the gate; no application-layer "have I seen this before?" logic is needed.
- Audit trail per finalization. The event table answers "when did session X finalize? with what payload?"
- Pattern generalizes. `session.started` and `session.ended` events can land in later commits (the CHECK constraint already allows them; the schema is unchanged).
- Defense in depth via the partial unique index. An application-layer bypass that writes an asset directly can't accumulate duplicates.

**Negative:**

- Three writes per finalization (event INSERT, asset INSERT, conditional UPDATE). Slightly more expensive than a single write, but finalization is once-per-session and not in the hot path.
- The event table grows unboundedly. Slice 1 doesn't add a retention policy; a future rung (likely 0.10 polish) will define one. For typical municipal volumes (tens to hundreds of broadcasts per month) the unbounded growth is fine for years.
- Coupling between `civiccast/live/` and `civiccast/schedule/`. The finalizer reads/writes both `live_session_events` and `assets`. The cross-module boundary is documented in this ADR + in the `civiccast/live/finalization.py` docstring; future maintainers must not "tidy" the coupling into separate transactions.

**Operational notes:**

- The downgrade path for migration 0008 refuses to drop the table or column while data exists. Operators downgrading past 0008 must first delete or null the relevant rows. This is the same pattern as 0006 (asset state widening); ADR 0006's downgrade-safety reasoning applies here too.

## Alternatives considered

### Asset-only path (no event table)

Just write the asset row at state `recorded`, rely on the partial unique index on `source_live_session_id` for idempotency.

Rejected because (a) loses the audit trail; (b) loses the retry-payload-recovery path; (c) commits us to "asset is the only persisted record of finalization" -- a future feature wanting per-session event history would have to migrate the schema and backfill events for historical sessions. Cheaper to bake the event table in from Slice 1.

### Event-only path (no asset insert in the finalizer)

Write the event row in the finalizer; let a downstream worker pick up the event and create the asset asynchronously.

Rejected because:
- The v0.4 scope-lock's exit criterion is "recording appears in the asset library at state `recorded`." A two-stage approach with an async gap means the asset doesn't appear immediately; operators see a stale library until the worker runs.
- Two-stage approaches are race-prone in their own way (what if the worker crashes mid-create?) and shift the idempotency problem to the worker.
- The single-transaction approach is simpler and gives the operator immediate library visibility.

A future rung that needs cross-process async finalization (e.g., very large recordings whose finalization triggers extensive post-processing) can adopt a two-stage variant by adding a `session.queued_for_finalization` event without changing the `session.finalized` semantics.

### Asset-id == live_session_id without separate source FK column

Map the live session 1:1 to the asset by using the same id. No `source_live_session_id` column needed.

Rejected because:
- Slug collisions. Operators may have an upload with id `council-2026-05-15` predating the live session with the same id. Forcing the asset_id to match the live_session_id would silently overwrite or fail loudly with no actionable error.
- The 1:1 binding loses information: an asset's `source_live_session_id` makes the relationship queryable in both directions (find the live session that produced this asset; find the asset for this live session); a shared id doesn't carry that semantic.

Slice 1 uses the simpler `asset_id = live_session_id` derivation for the actual write, AND the `source_live_session_id` column for the relationship. If an asset collision happens at write time, the finalizer raises `LiveRecordingAssetCollisionError` and the operator can rename. The relationship column survives the collision-rename surface.

## References

- `civiccast/live/finalization.py` -- `LiveRecordingFinalizer.finalize_recording` + `FinalizationResult` + `LiveRecordingAssetCollisionError`.
- `civiccast/live/models.py` -- `LiveSessionEvent` SA model + event-type constants + Pydantic peer.
- `civiccast/live/migrations/versions/0008_finalization_spine.py` -- creates the events table + the asset link column + the partial unique index.
- `tests/live/test_finalization.py` -- 14 SQLite-path tests (happy + idempotent + wrong-state + missing-session + asset-id-collision + payload roundtrip).
- `tests/live/test_real_postgres.py::TestRealPostgresFinalizationIdempotency` -- two-thread concurrency proof.
- `docs/research/v04-slice1-broadcast-spine-design.md` § "Finalization Event Design".
- v0.4 scope-lock §1 line 129 -- "Recording finalization contract: the event payload emitted at on-air -> ending -> recorded, the asset-row insert it triggers, the idempotency guarantee."
- ADR 0001 -- messaging substrate (NATS, deferred per this ADR).
- ADR 0010 -- live session state machine (the conditional-UPDATE pattern this ADR composes with).
