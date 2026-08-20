# ADR Template

> **When moving this file into the project repo, place it at `docs/adr/0000-template.md`.** Copy this template to create new ADRs at `docs/adr/NNNN-short-title-in-kebab-case.md`. Numbers are sequential and never reused.

---

## How to use this template

ADRs (Architecture Decision Records) capture architectural decisions and their rationale. They are immutable once **Accepted**: you do not edit a past ADR to change a decision; you write a new ADR that **Supersedes** it. This is the discipline that makes the project's architectural history auditable.

When to write an ADR:

- A closed decision from the spec's §22 Open Decisions list resolves at a rung. Write an ADR recording the resolution.
- A new architectural choice is required (e.g., picking a CDN provider, choosing a podcast feed publishing surface). Write an ADR.
- A previous ADR needs to be reversed or refined. Write a new ADR that supersedes it.
- A non-trivial dependency or library is added. Write an ADR.

When NOT to write an ADR:

- A bug fix or a routine refactor. The verification log captures these.
- A typo correction or doc edit. CHANGELOG entry suffices.
- A trivial dependency bump. Lockfile diff suffices.

ADR numbering: sequential integers starting at 0001. ADR 0000 is reserved for this template. Numbers are never reused even when an ADR is superseded — the old one stays in `docs/adr/` with status updated.

---

# ADR NNNN — [Title in sentence case]

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR XXXX
**Date:** YYYY-MM-DD
**Deciders:** [Names — typically the human director plus any consulting role]
**Related rung:** [Release ladder rung, e.g., 0.1 — Foundation]
**Related spec section:** [§ reference — e.g., §11.2 Captions]
**Supersedes:** [ADR number, if applicable]
**Superseded by:** [ADR number, if this ADR has been replaced]

---

## Context

[What is the issue or choice that motivates this decision? One to three paragraphs.

State the constraints from the spec, the workload, the audience, the license posture, and the non-negotiables. Name the alternatives that exist in the broader ecosystem. Identify what makes this a non-trivial choice — if the answer were obvious, no ADR would be needed.

Reference benchmarks, vendor licenses, and prior project decisions where they bear on the choice.]

## Decision

[The decision in one or two sentences. State it positively: "We will use X." Not "X looks good." Not "X seems best." Pick a side.]

## Alternatives considered

**Option A — [name].** [What it is. Why it was considered. The case for it. The case against it. The reason it was not chosen.]

**Option B — [name].** [Same shape.]

**Option C — [name].** [Same shape, if applicable.]

[Three options is typical. More than four suggests the choice space hasn't been narrowed enough. Fewer than two suggests the decision wasn't actually contested.]

## Consequences

[What becomes easier or harder because of this decision? What new risks or obligations does it introduce? What is unaffected? Be honest about the tradeoffs.]

### Positive

- [What this decision enables or simplifies.]
- [Capabilities or properties it gives the project.]

### Negative

- [What this decision costs or constrains.]
- [Operational overhead, lock-in, or capability gaps it introduces.]

### Risks

- [What could go wrong because of this decision.]
- [Mitigation: how the project guards against the risk.]

## Compliance

[How will future code respect this decision? What review or test catches violations?

Examples:
- "Lint rule X enforces this."
- "Module Y's public API encapsulates this; cross-module imports are forbidden."
- "Pre-commit hook Z verifies this on every commit."
- "The verification log's [section] item explicitly checks this."]

## References

- [Spec section reference.]
- [Release plan rung reference.]
- [External references — vendor docs, license texts, benchmarks, prior art, related ADRs in this project or in CivicSuite.]

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one. Do not edit the substance of an Accepted ADR — only its Status field and a one-line note pointing to the superseding ADR.*
