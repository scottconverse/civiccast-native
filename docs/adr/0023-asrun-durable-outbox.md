# ADR 0023 — As-run ledger writes go through a local durable outbox

**Status:** Accepted
**Date:** 2026-08-21
**Deciders:** Scott Converse (owner) — implemented on coder authorization (BUG C2 fix)
**Related rung:** Native-Windows Program (S23 as-run / proof-of-performance)
**Related spec section:** `docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md` §12 Global gates
  ("failure scenarios ... full disk"); `docs/spec/3.0/sections/S23-asrun-epg-franchise-reporting.md`
  §1/§3/§6 (the as-run ledger is the franchise-compliance proof-of-performance record)
**Supersedes:** none
**Superseded by:** none

---

## Context

`civiccast/reporting/asrun_recorder.py`'s `StoreAsRunRecorder` is the concrete implementation of
the playout engine's as-run capture seam (`civiccast.egress.asrun.AsRunRecorder`). At every actual
source transition it wrote an `AsRunLogEntry` straight to the durable `ReportingStore`
(Postgres or SQLite, per the station's configured `DATABASE_URL`) inside a bare
`except Exception: log and continue` — the module's own docstring called this out explicitly as
"the current swallow-and-log behavior."

The as-run log is the station's legal proof-of-performance record: S23 §3 frames it as a
franchise-compliance ledger ("municipal franchise agreements require PEG operators to prove what
aired"), and the master spec's §12 release-readiness gate requires the product to survive a
**full-disk** failure scenario, among others, without silent data loss. A transient DB hiccup
during playout — a connection drop, a disk-full write, a brief network partition to a remote
Postgres — is exactly the moment the ledger matters most, and the prior code silently dropped the
row and told nobody. This is BUG C2 from the station-acceptance audit.

## Decision

**Every as-run write goes through a local, durable, transactional outbox before it ever reaches
the real store**, implemented in the new module `civiccast/reporting/asrun_outbox.py`:

1. **Journal first.** `AsRunOutbox` opens a small SQLite file (`asrun_outbox.sqlite3`, station
   data dir, `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=FULL`) independent of the app's main
   database connection. Every write is `INSERT`ed there — and fsync'd — before anything touches
   the real `ReportingStore`.
2. **Drain, then retry.** Immediately after journaling, the outbox attempts an opportunistic drain
   to the real store. In the common case (store reachable) this is transparent: the row lands in
   the real store before `record_transition`/`close_open` returns, identical to the prior
   behavior. On a store failure, the row stays journaled — nothing is lost — and
   `ChannelAutomationService.run_once`'s existing poll cadence (already driving every other
   channel-automation concern) retries the drain every tick until the store recovers.
3. **Visible health, not silence.** A drain failure raises `asrun-outbox-degraded` on the existing
   alert hub (`civiccast.alerting.store.record_alert_condition`) — a new
   `AlertConditionKind`, unseeded (no migration-0039-style default rule row), matching every
   condition kind added to that Literal since migration 0039 shipped (`self-test-fail`,
   `eas-source-unavailable`, `scheduled-recording-*`); the operator can raise its severity from
   the "warning" fallback in Alert Settings if a station wants it to page. The condition resolves
   itself (queried against the DB, not an in-process flag, so it self-heals across a restart) once
   a drain call finds the backlog empty.
4. **Exactly-once.** Each journaled row carries a stable `event_id` derived from the recorder's own
   per-transition UUID (`asrun-open:<entry_id>` / `asrun-close:<entry_id>`) as a SQLite `UNIQUE`
   column, so re-journaling the same op is a no-op. Draining is *also* idempotent —
   `ReportingStore.append_as_run` upserts by `entry_id` and `ReportingStore.close_entry` is a
   guarded `WHERE duration_s == 0` UPDATE — so replaying an already-drained row across a crash
   (DB commit succeeded, local "mark drained" did not) reproduces the identical result rather than
   a duplicate.
5. **Startup replay.** `AsRunOutbox.replay_pending()` drains every row left over from a prior
   process before the engine emits its first proof event of a new run, wired into
   `build_channel_automation`.

The recorder's only remaining bare-except path is `AsRunOutboxJournalError` — the true last
resort where even the local journal write itself fails (e.g. local disk full). That path now logs
at `CRITICAL` (not the previous routine exception log) and still must never break playout, per the
existing contract that a capture error can never take the channel off air.

## Alternatives considered

**Option A — Try/retry with exponential backoff, no local journal.** Rejected: without a durable
local record of the pending write, a process crash or restart during the retry window still loses
the event. The spec's full-disk/crash failure scenarios require surviving exactly that window.

**Option B — JSONL append-only file instead of SQLite.** Considered, since two sibling modules
(`civiccast.native.upgrade.journal`, `civiccast.native.provision.journal`) already hand-roll an
atomic single-document JSON journal (temp file + fsync + `os.replace`). Rejected for this use
case: those modules persist one evolving document, not a many-row append-only log with
"drained vs pending" state and dedupe-by-id, and re-deriving crash-safe torn-line recovery,
atomic append, and idempotent replay on top of hand-rolled JSONL would reproduce most of what
SQLite already gives for free (atomic commits, a durable index, `INSERT OR IGNORE` dedupe). SQLite
is already a first-class dependency in this codebase (the main app DB itself runs on SQLite in the
default first-mile install path — see `civiccast/db/url.py`), so this adds no new dependency.

**Option C — Reuse an existing seeded-critical `AlertConditionKind` (e.g. `db-unreachable`)
instead of minting a new kind**, mirroring `civiccast.egress.automation._raise_egress_degraded_alert`'s
reuse of `encoder-death`. Rejected: `db-unreachable` is resource-sampler-owned with its own
dedupe/resolve contract keyed to `resource_ref="host"`; the as-run outbox condition needs its own
`resource_ref` and life cycle regardless, and the codebase's own precedent since migration 0039 is
to mint a new first-class kind for a new failure mode rather than overload an existing one's
dashboard label (see `self-test-fail`, `eas-source-unavailable`, `scheduled-recording-*`).

## Consequences

* **Positive.** A DB hiccup during playout no longer drops an as-aired row from the legal record.
  The operator sees a real, visible alert condition instead of only a log line. A crash mid-drain
  loses nothing. No new runtime dependency.
* **Negative / accepted limitation.** If the alert hub's own database is the thing that is down
  (the same outage causing the drain failure), the health condition itself may fail to write until
  the DB returns — the same accepted limitation `_raise_egress_degraded_alert` already carries.
  The as-run event itself is unaffected (it is durable in the local journal regardless); only the
  *notification* of the outage can be delayed until the DB is reachable again for at least the
  alert-hub write.
* **Negative / accepted limitation.** The new `asrun-outbox-degraded` condition defaults to
  `warning` severity (no seeded rule), so it does not automatically escalate the operator's
  runtime safe-to-air surface to red the way `off-air`/`encoder-death`/`db-unreachable` do. This
  matches every condition kind added since migration 0039; a station that wants it to page raises
  its severity in Alert Settings post-install.
* **Follow-up (not in this change's scope).** No change was made to the resource-sampler's disk
  space thresholds; a full local disk severe enough to fail the outbox's own journal write is
  still detected by that pre-existing `disk-low` condition, but not specifically tied to this
  module.

## Compliance

Verified in `tests/reporting/test_asrun_outbox.py` (9 cases: DB-down journals instead of drops,
drain failure raises the alert, backlog drains + alert resolves once the DB returns, redundant
drains create no duplicate rows or duplicate resolve events, no loss/no duplication across a
simulated crash for both the append and close ops, exactly-once dedupe on a repeated journal call,
and an end-to-end `StoreAsRunRecorder` outage-and-recovery case) plus the full pre-existing
`tests/reporting/` and `tests/egress/test_asrun_capture.py` / `tests/egress/test_automation.py`
suites, unmodified and still green. `ruff check`/`ruff format --check` and `mypy civiccast`
(strict) clean.

## References

- `civiccast/reporting/asrun_outbox.py` — the outbox implementation (module docstring has the
  full design narrative).
- `civiccast/reporting/asrun_recorder.py` — the recorder, now routed through the outbox.
- `civiccast/egress/automation.py::build_channel_automation` — process wiring + startup replay;
  `ChannelAutomationService.run_once` — periodic drain tick.
- `civiccast/alerting/models.py` — the new `asrun-outbox-degraded` `AlertConditionKind`.
- `docs/spec/3.0/sections/S23-asrun-epg-franchise-reporting.md` — the as-run ledger's spec.
