# ADR 0023 — NATS removed: in-process event bus

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** Scott Converse (owner)
**Related rung:** Native-Windows Program (platform substrate / native supervisor)
**Related spec section:** §5.1 Platform substrate (see the dated amendment note in
`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md`'s messaging section)
**Supersedes:** ADR 0001 — Messaging substrate: NATS JetStream
**Superseded by:** none

---

## Context

ADR 0001 (2026-05-08) chose NATS JetStream as CivicCast's messaging substrate: persistent
streams, consumer groups, sub-millisecond local latency, an Apache 2.0 license, and a
single-binary install. That decision assumed NATS would carry real inter-module event traffic
in production.

It never did. Auditing the native-Windows line's actual runtime wiring
(`civiccast/platform/broker.py`) showed `get_broker_client()` unconditionally returned
`InProcessBrokerClient()` — the in-process, in-memory adapter used for local tests and v1.2
evidence — regardless of configured mode. The `NATSJetStreamBrokerClient` production path
existed and was unit-tested in isolation, but nothing in the shipped product ever selected it in
a real deployment. NATS was, in practice, only ever:

- a fourth supervised child process (`civiccast/native/supervisor/children.py`'s `nats_child_spec`),
  sequenced in the D5/D6 startup order alongside PostgreSQL and the control plane;
- a `nats-server.conf` file the installer provisioned (`civiccast/native/provision/conf.py`'s
  `render_nats_conf`) into a `data\nats-store` directory that existed for nothing else;
- a `nats-server.exe` binary bundled into the native-server-binaries pack
  (`scripts/build_native_server_pack.py`), adding install size and a pinned upstream dependency
  to track;
- a health/readiness gate (`nats-jetstream` in the installer's first-run health check and beta
  handoff lane) that could fail a station's readiness report for a service nothing else on the
  station depended on;
- a certificate identity (`nats` in `civiccast.certs.authority.REQUIRED_SERVICE_IDENTITIES`)
  requiring its own mTLS rotation story;
- a CI job (`nats-boundary`) and a v12 import-boundary policy test asserting nothing outside
  `civiccast/platform/` imports the `nats` provider — a boundary that, once NATS is gone
  entirely, is enforced by the dependency's simple absence.

None of this delivered the capability ADR 0001 was written to obtain. The persistent-stream,
consumer-group, durable-replay behavior that justified NATS over Postgres `LISTEN/NOTIFY` was
never exercised in production; every real publish event flowed through the in-process adapter's
plain Python dict.

## Decision

**NATS JetStream is removed from the product.** `civiccast.platform.broker.InProcessBrokerClient`
is now the only `BrokerClient` implementation; the `BrokerClient` Protocol seam is retained so a
future adapter can still be substituted behind it if a real cross-process or cross-host messaging
need materializes. Concretely, this removes:

- the `nats` supervised child, its D5 graceful-stop (lame-duck signal) handling, and its D6
  readiness check from the native supervisor;
- NATS config/store provisioning from the installer's provisioning engine;
- `nats-server.exe` and its license file from the native-server-binaries pack;
- the `nats-jetstream` installer health check and beta-handoff lane;
- the `nats` certificate identity (mTLS rotation now covers only `civiccast-api` and
  `civiccast-worker`);
- the `nats-boundary` CI job and its now-vacuous import-boundary policy assertion;
- the `nats-py` Python dependency and the `NATSJetStreamBrokerClient` implementation entirely.

PostgreSQL `LISTEN/NOTIFY` remains unchanged for its existing low-volume "tell the UI a row
changed" purpose — it was never the broadcast event bus and this decision does not touch it.

## Alternatives considered

**Option A — Keep NATS, wire the production adapter for real.** Rejected. This would mean
building and proving a genuine production NATS deployment (JetStream stream lifecycle, mTLS
credential rotation, a real cross-process consumer) for a capability nothing in the current
product actually needs yet. The install-size, process-count, port, config-file, and health-gate
cost would be paid indefinitely against a hypothetical future requirement, not a real one.

**Option B — Keep NATS staged but unused (status quo).** Rejected. This is what ADR 0001's
decision had silently become: a supervised child, a config file, a bundled binary, and a health
gate that could fail a station, all in service of an adapter path nothing selected. Carrying
inert infrastructure is worse than carrying none — it is a maintenance and audit cost with no
offsetting benefit, and a `nats-jetstream` health-check failure on a station that never used NATS
for anything was a false alarm risk to operators.

**Option C — Remove NATS, keep the in-process adapter as the sole implementation.** Selected.
Matches what the product actually does today. The `BrokerClient` Protocol seam is deliberately
retained (not collapsed into a hard-coded call site) so a real cross-process substrate — NATS or
otherwise — can be reintroduced behind that seam if and when a real production need for it is
identified and proven, without another retrofit of the publish-seam call sites.

## Consequences

### Positive

- Smaller install: one fewer supervised process, one fewer bundled binary, one fewer config file,
  one fewer certificate identity to rotate, one fewer port to reason about.
- One fewer health/readiness gate that could report a station "not ready" over a service nothing
  else on the station depended on.
- Simpler startup sequencing: the native supervisor's D6 order is now `(postgres, control_plane)`
  instead of `(postgres, nats, control_plane)`.
- `civiccast.platform.broker`'s dependency surface shrinks to exactly what is used in production.

### Negative

- If a genuine cross-process or cross-host messaging need arises later (e.g., true Mode B /
  CivicSuite federation), a real substrate decision will need to be made again from scratch —
  this ADR does not pre-select NATS or any alternative for that future need. The `BrokerClient`
  Protocol seam exists specifically so that decision, when it comes, is a new adapter behind an
  existing seam rather than a call-site rewrite.
- The `nats-py` client, `NATSJetStreamBrokerClient`, and their test coverage are deleted outright,
  not archived behind a feature flag. Recovering NATS support later means re-deriving that
  adapter, not un-commenting it.

### Risks

- **Premature closure of a real future need.** Mitigated by keeping the `BrokerClient` Protocol
  seam and by this ADR itself recording exactly what NATS was providing (and not providing) so a
  future decision starts from an honest baseline rather than re-litigating ADR 0001's original
  (still-valid, just currently unneeded) reasoning about persistent streams and consumer groups.

## Compliance

- `civiccast.platform.broker.get_broker_client()` returns `InProcessBrokerClient` unconditionally;
  there is no production-mode branch to drift out of sync with reality again.
- `civiccast.certs.authority.REQUIRED_SERVICE_IDENTITIES` no longer includes `nats`.
- `civiccast.native.supervisor.config.STARTUP_ORDER` is `("postgres", "control_plane")`.
- CI's `nats-boundary` job and the `nats`-specific provider-import assertion are removed; the
  general publish-seam broker-import test in `tests/platform/test_broker_import_policy.py`
  remains.
- The 3.0 MASTER spec's messaging-substrate section carries a dated amendment note pointing here
  rather than being rewritten wholesale.

## References

- ADR 0001 — Messaging substrate: NATS JetStream (superseded by this ADR)
- `civiccast/platform/broker.py`, `civiccast/platform/broker_config.py`
- `civiccast/native/supervisor/children.py`, `civiccast/native/supervisor/config.py`
- `civiccast/certs/authority.py`
- `docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md` §5.1 (messaging substrate, amended)

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references
this one.*
