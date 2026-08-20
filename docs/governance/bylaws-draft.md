# CivicCast Foundation Bylaws Draft

Status: v1.0 launch draft.

Date: 2026-05-15

This draft is the governance artifact required for CivicCast v1.0 readiness.
It is not a filed legal document. It establishes the operating posture for the
project until a formal nonprofit, fiscal sponsor, or foundation structure is
approved.

## Purpose

CivicCast exists to provide open, self-hostable civic broadcast software for
public-interest meetings, community media, and public-record video workflows.
The project prioritizes resident access, durable public records,
accessibility, open formats, local operator control, and low total cost of
ownership.

## Governance Principles

- Public-interest user experience comes first.
- Documentation, QA, accessibility, and release evidence are release
  requirements.
- No vendor lock-in: public records must remain exportable in open formats.
- No hidden AI publication: AI captions, translations, summaries, and signed
  records require operator review before publication.
- Security and privacy disclosures must be plain enough for small
  organizations to act on.

## Interim Authority

Until a formal Steering Committee is seated, Scott Converse is the interim
project maintainer and release authority for v1.0 readiness decisions.

The interim maintainer may:

- approve release scope;
- merge release-readiness pull requests;
- accept or defer audit findings;
- appoint additional maintainers;
- publish v1.0 release artifacts after the go/no-go gate is green.

The interim maintainer may not:

- remove the open-source license from existing code or docs;
- publish a v1.0 release with unresolved Blocker or Critical readiness findings
  unless those findings are explicitly moved to a named pre-1.0 or post-1.0
  release path;
- add proprietary-only dependencies to the default self-hosted path without a
  public ADR.

## Steering Committee Draft

The v1.0 Steering Committee target is three to five voting members:

- one maintainer seat for project/release stewardship;
- one operator seat for public-meeting or community-media deployment feedback;
- one accessibility/privacy seat for resident-impact review;
- optional technical maintainer seats for installer, streaming, AI quality, or
  archive work.

Initial committee membership is not yet seated. The maintainer bridge above is
the v1.0 launch posture until the committee is formed.

## Decision Process

Routine implementation decisions are made through pull request review and
release evidence. Material decisions require a tracked ADR or release evidence
update when they affect:

- public-record durability;
- resident accessibility;
- AI publication behavior;
- installer/deployment posture;
- privacy/security guarantees;
- release gating.

## Release Gate

A v1.0 release may be published only after:

- all Blocker/Critical v1.0 readiness findings are closed or explicitly moved
  out of v1.0 with a named owner and release path;
- release identity checks pass;
- required local and CI verification passes;
- the v1.0 go/no-go document records the final decision.

## Amendments

Before a formal committee is seated, this draft can be amended by pull request
with the interim maintainer's approval. After the committee is seated,
amendments require a recorded committee decision.
