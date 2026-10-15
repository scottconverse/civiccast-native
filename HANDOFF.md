# Current handoff: Beta 19 release preparation (2026-10-15)

Current branch: `feat/sprint5-board-audio`. Read current HEAD with
`git rev-parse HEAD`.
Current published tag: `v1.0.0-beta.18`; Beta 19 remains unpublished.
PR: https://github.com/scottconverse/civiccast-native/pull/257.
The source branch now includes Sprint 5 remote-guest composition and relay
commissioning, bulletin-board live video and audio, and native viewer
completion, along with the earlier Beta 17/18 publication/import work.
Beta 19's signed kit was built from
`7d61cbede3123a65b4a0d6d4b413ae99edbc3f04` in
[workflow 38797808863](https://github.com/scottconverse/civiccast-native/actions/runs/38797808863).
Its package identity and scoped checks are in the
[Beta 19 verification record](docs/releases/v1.0.0-beta.19-verification.md).
Merge, tag and publication remain pending; the earlier Beta 18 download stays
current until then.
The historical Beta 17 record below is retained for attribution.

## Beta 17 release (2026-10-15)

[PR #251](https://github.com/scottconverse/civiccast-native/pull/251) merged as
`4a5804608c38774bc04b4c2a5c6f34f56ebdea26`, the Beta 17 tag target.
The signed installer was built from `597b97fd21ad1e9e5fd52bb399f81214ffdb88f0`.
The [Beta 17 release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.17)
and [package record](docs/releases/v1.0.0-beta.17-verification.md) identify
its assets and scoped checks.

Completed Sprint 5 source work covers subscriber notices with receipts and
retries, Podcast MP3 enclosures and RSS, and saved
underwriting daypart selection. Sprint 5 remote-guest composition,
bulletin-board media, station-import UI, and native viewer completion remain
open. Protected paywall media remains deferred. The signed package's
installation checks passed; its Windows Sandbox product-engine stream capture
did not. The exact result is in the package record. Historical Beta 16 results
below belong only to Beta 16.

At Beta 17, the source brought together station operations, unattended scheduling,
broadcast output, programme transitions, HLS retention, and recorded-caption
work. Signed `v1.0.0-beta.17` was that edition's [published release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.17); the
[package verification record](docs/releases/v1.0.0-beta.17-verification.md)
identifies its installer and checks.

PR #249 merged to `main` as `efcab4c1f618e4a46bf62491ee410a9fcd9e7618`, the Beta 16 tag target.
The signed Beta 16 package was built from
`e92bebd4b5289dce969f81b72515cfa0d45eba55`, successful
[build 38635220200](https://github.com/scottconverse/civiccast-native/actions/runs/38635220200).
The corrected package passed upgrade, administrator/profile preservation,
restricted service/process identity, installed GStreamer smoke, and uninstall
in the 240 GiB Hyper-V guest. Clean fresh installation also passed, including
new administrator setup, healthy/current Beta 16, restricted process ownership
and installed runtime smoke. The owner subsequently authorized publication.
The earlier candidate used
`9b83d7b89cddc987fbbcc5e23a1433339810d5d6` on `codex/beta16-release`,
[build 38579665236](https://github.com/scottconverse/civiccast-native/actions/runs/38579665236).
That candidate failed upgrade service registration in the replacement 160 GiB
Hyper-V guest and restored healthy Beta 15 with the saved station profile.
The corrected source stops the service before migrating its identity.
Results are tracked in the package verification record above.

Current source work includes:

- [Station operations](docs/ops/station-operations-goal.md): encrypted backup and restore, supported network setup, staff accounts and sessions, and restricted Windows service identity.
- [Sprint 2](docs/ops/sprint2-unattended.md): station-local recurrence, bounded operational storage, low-disk handling, and recovery after repeated output failures.
- [Sprint 3](docs/ops/sprint3-output-completion.md): RTMP output, per-output audio processing, complete programme endings, coordinated HLS retention, and recorded-caption settings.
- Updated product guidance for the combined source edition; see the [roadmap](docs/ROADMAP.md).

The previous [CivicCast Beta 15 release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.15), published October 13, 2026, retains its exact package identity and scoped results in the [Beta 15 verification record](docs/releases/v1.0.0-beta.15-verification.md).

The Beta 15 R9 field report recorded scheduled speech appearing as slate, a CG
playlist referring to missing segments, an unsigned installed native
executable, and a trimmed-caption range mismatch. Its causes and incomplete
workflows remain bounded as described in the [Beta 17 deferred
backlog](docs/ops/beta17-deferred.md). The owner deferred those follow-ups
until after Beta 16 is released. They are not Beta 16 package results.

Historical source merges remain traceable through [PR #245](https://github.com/scottconverse/civiccast-native/pull/245), [PR #246](https://github.com/scottconverse/civiccast-native/pull/246), and [PR #247](https://github.com/scottconverse/civiccast-native/pull/247). Their sprint records preserve contemporaneous implementation evidence and limitations.

## Historical Beta 14 publication handoff

The following is retained history, not the current station or work status.

Beta 14 is published: https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.14
Published 2026-10-12 10:25:01 UTC. All 26 assets passed name/size and SHA-256
digest verification. Six actual public downloads matched SHA-256; the
downloaded installer has a Valid Scott Converse Authenticode signature.

Signed source: `44525c14265d21ae461c2435d4d5a9a6acd58af3`; build `38217950172`.
Release target / merged PR 240: `ed2f5069004abb6c3c6b4375ac82a07fcabe9a7b`.
Installer SHA: `e22d1cb9ae064841c45bed64a37e8ce9bd1e5176e0ff80945edccc362447082f`.
Bookkeeping branch: `codex/beta14-publication-record`.

All 28 requested product goals have focused evidence in
[task completion](docs/ops/beta14-task-completion.md). Exact package passed
fresh offline Sandbox installation, five three-channel observations and
installed Help inspection. Sandbox closed. Same installer ran once on host,
exited 0, and passed component verification and two three-channel observations.
Host remains running: Whistle primary, H.264/AAC, advancing HLS and captions.
No extended Beta 14 soak requested or claimed. Original observer failures are
preserved; corrections did not rerun setup or rebuild the signed application.
Final receipt: `outputs/beta14-work/host-runtime-final/consumer-evidence-receipt.json`.
Raw pre-install snapshot was not retained; account/schedule rows not compared.
Historical R9 TSDuck cause and one unavailable recording segment cause remain
unknown; focused current fixes are evidenced separately.

D: kit: `D:\CivicCast-Beta14-Kit-44525c14`, 19 members, 26,916,076,058 bytes.
Assembly and USB receipts alongside; both installation prompts name Beta 14.
Assembly SHA: `2338fddc987b4cb73bfbea4947901899a11ef0338231b24772f2a756604f77a4`.
Redundant closed Sandbox expansion and twelve uploaded archive parts removed;
evidence/component manifest and working C:/D: kits retained. C: free 403.9 GB.

Goal ACTIVE until this final record lands and live Pages verification finishes.
Only owner may pause. Publisher session 8097 finished; do not restart/build.
Next: land reconciliation, verify live landing page, then mark goal complete.
72-hour/three-channel/99.78% result remains Beta 11 history.
Live release-truth alarm has 17 absent historical releases, none Beta 14.
Preserve unrelated `ops/beta10-oversight/evidence/`.
