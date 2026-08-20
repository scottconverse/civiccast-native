# civiccast.org Holding Page Draft

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

Status: current public-facing copy for the rc18 Windows controlled beta.

Date: 2026-07-23

## Headline

CivicCast

## Subheadline

Record and publish civic meetings on infrastructure you control.

## Primary Call To Action

Do not install rc13. The current controlled Windows beta is
`v1.0.0-rc18`: its rc15 foundation passed genuine clean-Windows validation
through cold-reboot recovery, rc17 added the published rc16 UI/UX repairs
plus the six audited beta-blocker fixes, and rc18 remediates all sixteen
findings from the stage gate raised against the rc17 line.
Download it from the [public rc18 GitHub release](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc18).

## Body

CivicCast is open-source meeting recording and publication software for school boards, HOA
boards, city councils, commissions, nonprofit boards, public-access stations,
and community media teams.

Use it to:

- upload a meeting recording, rehearse that exact sample privately, and package
  it without publishing;
- explicitly approve recorded video for the public Portal;
- generate captions, translated captions, and reviewed summaries;
- export signed record packages;
- keep archive copies for public-record workflows;
- notify residents through email, webhook, RSS, and podcast feeds;
- run a database-scoped restore drill, update readiness, rollback proof, and
  support bundles;
- plan channel-style programming and publish a reference CTV feed;
- optionally test provider and ActivityPub lanes behind operator controls.

## First Broadcast Path

The public Windows installer is attached to `v1.0.0-rc18`. The bounded
acceptance path is: verify and install it, create the
first admin, run the database-scoped recovery drill, confirm unverified live
sources fail closed, create or upload sample recorded media, package it
privately only after an exact-sample private rehearsal, explicitly approve
Portal publication, and confirm playback from a second browser.

## Who Should Try The Early Adoption Candidate

CivicCast is recruiting controlled technical acceptance testers for the exact
public rc18 Windows beta. It is available as a controlled beta download, with the
bounded acceptance limits stated in the tester packet.

## Release Status

The current beta adoption line is the early adoption readiness path: public
download posture, support intake, procurement/legal language, release policy,
and proof bundles that connect installer, operations, resilience, and
channel/CTV evidence. Controlled station tests can use newer beta artifacts
when their handoff names a specific release tag.

External provider credentials, public target-instance federation, live cable
headend proof, SDI/DeckLink, streaming-TV app-store publication, DRM, and
hardware delivery remain separate proof lanes unless a station records separate
redacted evidence.

## Secondary Links

- Repository: `https://github.com/scottconverse/civiccast`
- User Manual: `docs/USER-MANUAL.md`
- Admin Guide: `docs/admin-guide.md`
- Meeting Operator Guide: `docs/meeting-operator-guide.md`
- Records Clerk Guide: `docs/records-clerk-guide.md`
- Technical Operations Reference: `docs/technical-ops-reference.md`
- FAQ: `FAQ.md`
- Windows release trust: `docs/install/windows-release-trust.md`
- Early-adopter quickstart: `docs/adoption/early-adopter-quickstart.md`
- Support intake: `docs/adoption/support-intake.md`
- Procurement/legal posture: `docs/adoption/procurement-legal-brief.md`
- v1.7 proof bundle: `docs/releases/v1.7-proof-bundle.md`
- API guide: `docs/API-REFERENCE.md`
- Tester packet: `docs/tester/START-HERE.md`

## Footer

CivicCast is open source. Code is Apache-2.0. Documentation is CC BY 4.0.
