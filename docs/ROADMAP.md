# CivicCast roadmap

CivicCast brings station scheduling, channel playout, meeting recording,
caption review, and resident publication into one native Windows system.

## Source work being prepared for Beta 16

The owner is preparing `v1.0.0-beta.16` as an unpublished candidate from the
current source. Recent work adds:

- Encrypted station backup and restore, supported network setup, staff accounts and sessions, and a restricted Windows service identity. See the [station operations record](ops/station-operations-goal.md).
- Station-local scheduling across daylight-saving changes, bounded operational storage with usage reporting, low-disk handling, and automatic output recovery. See [Sprint 2](ops/sprint2-unattended.md).
- RTMP output, per-output audio processing, complete programme endings, coordinated HLS segment retention, and explicit recorded-caption language and completion settings. See [Sprint 3](ops/sprint3-output-completion.md).
- Updated product and operator guidance for this combined source edition.

These are source capabilities and focused implementation results. Until
publication, the current downloadable release remains [Beta
15](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.15);
use its [verification record](releases/v1.0.0-beta.15-verification.md) for
package-specific evidence. The [Beta 16 candidate verification
record](releases/v1.0.0-beta.16-verification.md) tracks package status.

## Deferred follow-up

The owner deferred the field and workflow follow-ups in the [Beta 17
backlog](ops/beta17-deferred.md) until after Beta 16 is released. The list
separates confirmed Beta 15 observations from causes and workflows that remain
unconfirmed or incomplete. It does not qualify the Beta 16 source candidate.

## Measured operation history

A Beta 11 host ran Public, Government, and Education together for 72 hours
with **99.78% live caption-input coverage**. The [72-hour host
report](ops/beta11-host-caption-performance-72-hour-2026-10-11.md) explains the
channel totals and measurement. This remains historical Beta 11 evidence; it
is not a Beta 15 field result or Beta 16 package qualification.

## Roadmap ownership and evidence

The owner sets implementation and release scope. The [Beta 15 verification
record](releases/v1.0.0-beta.15-verification.md) documents that package's exact
identity and installation observations. The [Beta 17 deferred
backlog](ops/beta17-deferred.md) cites the separate Beta 15 R9 field report and
describes what that host evaluation did and did not establish. No release date
or additional feature is promised here.

The [earlier roadmap](history/roadmap-before-beta12-doc-audit-2026-10-11.md) is retained as historical planning. Its WSL/rc release line, old milestone numbers, and implementation cursor are not the current native Windows roadmap.
