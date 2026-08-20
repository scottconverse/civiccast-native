# ADR 0001 — Messaging substrate: NATS JetStream

**Status:** Accepted
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** Day 0 bootstrap / 0.1 — Foundation
**Related spec section:** §5.1 Platform substrate, §22 Open Decisions (D3)
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

CivicCast is a streaming-first broadcast platform with multiple modules that fan out work asynchronously: stream packaging, captions, summaries, archive uploads, syndication, podcast feed generation, subscriber notifications. The platform substrate needs a messaging layer that supports:

- **Persistent streams with replay.** A failed Whisper job, archive upload, or syndication push must be re-runnable from the same event source without losing position. Lost events mean missed captions, missed archive deposits, or missed publish notifications — any of which would violate the spec's three-tier-publish non-negotiable.
- **Consumer groups with at-least-once delivery.** Multiple workers per surface, durable subscriptions, ack-based redelivery. The captions module needs a Whisper worker pool; the archive module needs an IA upload worker that retries cleanly across process restarts.
- **Sub-millisecond local latency** for the orchestrator's per-frame coordination during live ingest, where every millisecond of substrate latency erodes the live-to-air budget.
- **Open license posture, with no procurement smell.** CivicCast is targeted at municipal evaluators, school district AV leads, public access TV operators, and HOA boards. A "we use a fork because the upstream went non-OSI" story creates real procurement friction; OSI-approved licenses are required.
- **Single-binary install** so operators on the Tier 1 Streaming reference build don't need to provision a separate cluster manager. Zero external dependencies on the wire-protocol path.
- **Clean clustering for the Mode B future.** When Mode B (CivicSuite federation) eventually needs multi-host messaging, the same substrate must scale without forcing a substrate swap.

This decision was identified as Open Decision **D3** in the spec (§22). The release plan resolves it before rung 0.1 because every subsequent rung depends on the messaging substrate being known.

## Decision

**CivicCast uses NATS JetStream as its messaging substrate.** All inter-module event traffic, work-queue distribution, and durable replay flows through NATS JetStream. PostgreSQL `LISTEN/NOTIFY` is retained for low-volume "tell the UI a row changed" notifications only — not as the broadcast event bus.

## Alternatives considered

**Option A — NATS JetStream.** Apache 2.0 license. Single Go binary install. Sub-millisecond local latency. JetStream provides persistent streams, consumer groups (durable consumers), at-least-once and exactly-once delivery semantics, server-side filtering, and clean horizontal clustering. Upstream is healthy, well-funded (Synadia + CNCF graduated project), and has not signaled any license change. This was selected.

**Option B — Redis Streams.** Mature, fast, broadly understood. Rejected for license posture: Redis 7.4+ moved to a dual SSPL/RSAL license that is not OSI-approved for many use cases. The Valkey fork is OSI-clean, but a "we use Valkey because Redis went non-OSI" footnote in the substrate documentation creates exactly the procurement smell municipal evaluators flag — and re-flag every license-review cycle. The capability is fine; the procurement story is not.

**Option C — PostgreSQL `LISTEN/NOTIFY`.** Already in the stack (the schema substrate per §5.1 and the closed monorepo decision in CLAUDE.md). Zero additional dependencies. Rejected for capability: 8KB payload limit (truncates at-scale event payloads), no durable replay (a missed notification is gone), no consumer groups (every listener gets every notification, no work distribution semantics), and no acknowledgement model. The wrong tool for a broadcast event bus or for coordinating multi-step publish pipelines. **Retained for low-volume UI-coherence notifications** where "tell the browser a row changed" is the entire requirement.

**Option D — RabbitMQ.** Mature, AMQP-standard, capable. Rejected for operational weight: Erlang runtime, multi-binary install, and a feature surface (exchanges, bindings, federation) that exceeds CivicCast's needs. Operator overhead matters; CivicCast targets organizations whose IT capability is "set up a Windows machine and follow an install script."

**Option E — Apache Kafka.** Industry standard for event-streaming at scale. Rejected for operational weight (JVM, ZooKeeper or KRaft, multi-broker minimum for production guarantees) and the resulting hardware footprint, which would push the Tier 1 Streaming reference build well above the $2,000 commodity-machine target.

## Consequences

### Positive

- Persistent streams with consumer groups give every CivicCast publish surface (portal, IA, syndicate, podcast, subscribe) a clean fan-out point with durable replay.
- Apache 2.0 license with a healthy upstream removes the procurement-smell risk for municipal, school district, and nonprofit evaluators.
- Single Go binary install matches the Tier 1 Streaming reference build's "one machine, one installer" deployment story.
- NATS JetStream's clustering story unblocks Mode B (CivicSuite federation) without requiring a substrate swap when that future arrives.
- Sub-millisecond local latency keeps the live-orchestrator's per-frame coordination budget intact.
- Native subject-hierarchical routing (e.g., `civiccast.publish.portal.complete`, `civiccast.publish.ia.failed`) maps cleanly onto the per-surface fan-out documented in spec §2.6.

### Negative

- One additional service operators must run alongside PostgreSQL, the Python services, and the frontend. Mitigated by single-binary install and the installer (Sprint 0.1) handling NATS bootstrap automatically — operators do not configure NATS by hand for the reference deployment.
- NATS clients exist in many languages but the Python client (`nats-py`) is the canonical one for CivicCast. Other-language integrations (e.g., a Go-based future module) need separate client maintenance.
- JetStream stream and consumer configuration is a real surface area that needs explicit ADR coverage as patterns emerge (subject hierarchy, retention policies, max-msgs, deduplication windows). Future ADRs will document these as they're decided.

### Risks

- **Upstream license drift.** The Redis lesson is real: an OSI-licensed substrate can become non-OSI in a single release. Mitigation: monitor NATS upstream license posture; the substrate-adapter pattern (planned for Sprint 0.5+ alongside the Whisper runtime adapter from ADR 0002) keeps the substrate replaceable if NATS ever changes course.
- **Operator unfamiliarity.** NATS is less broadly known than Redis or RabbitMQ in the small-org IT world. Mitigation: the CivicCast installer hides NATS configuration entirely; `civiccast doctor` reports NATS health; the user manual covers operational basics (start, stop, log location, stream-state inspection).
- **Schema drift between modules.** Without governance, multiple modules can publish overlapping or contradictory event types. Mitigation: spec §5.1 will be extended in Sprint 0.1 with the canonical event-schema registry; new event types require a CHANGELOG entry and (for cross-module events) an ADR.

## Compliance

- The platform substrate package (`civiccast.platform.*`, spec §8.19) provides the only sanctioned NATS client surface. Modules import the platform substrate, not `nats-py` directly, so the substrate adapter pattern remains a one-line swap if needed.
- Lint or CI rule (Sprint 0.1) flags direct `nats-py` imports outside `civiccast.platform.*`.
- The verification log for Sprint 0.1 confirms NATS install, stream creation, and durable-consumer round-trip on a clean Tier 1 Streaming reference build.
- Pre-commit hook (Sprint 0.1) verifies any new event-publishing code references a documented event type.

## References

- CivicCastUnifiedSpec-v2.md §5.1 Platform substrate
- CivicCastUnifiedSpec-v2.md §22 Open Decisions (D3 — messaging substrate)
- CivicCastUnifiedSpec-v2.md §2.6 Three-tier publish (load-bearing principle)
- CivicCast-ReleasePlan-0.1-to-1.0.md — "Architecture decisions baked in" (D3 resolution)
- [NATS JetStream documentation](https://docs.nats.io/nats-concepts/jetstream)
- [NATS license — Apache 2.0](https://github.com/nats-io/nats-server/blob/main/LICENSE)
- [Redis license change context](https://redis.io/legal/licenses/)
- ADR 0002 — Canonical Whisper runtime: faster-whisper
- ADR 0003 — Project development hardware and primary deployment OS target

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*
