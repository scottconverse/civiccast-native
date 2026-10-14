# CivicCast roadmap

**Current release: [v1.0.0-beta.15](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.15)**, published October 13, 2026. CivicCast is one native Windows product. The exact package identities and observations are in the [Beta 15 verification record](releases/v1.0.0-beta.15-verification.md).

## What Beta 15 delivers

Beta 15 is the corrected installer and programme-transitions release. It carries forward the unattended station operation and operator workflows delivered in earlier releases: caption health and lazy Whisper fallback, bounded supervisor logs, scheduled recordings, summary approval and signed-record exports, local administrator recovery, Control Room session recovery, remote guest media controls, alert routing and emergency presentation, paywall-secret preservation, and updated documentation.

Whistle is the CPU primary for live captions. Whisper provides per-channel fallback and recorded-media transcription, with optional supported NVIDIA acceleration.

## Main after Beta 15

The following source changes are merged on `main` after the published Beta 15 package. They are not part of that release:

- [PR #245](https://github.com/scottconverse/civiccast-native/pull/245) completes station backup, network access, staff management and service identity.
- [PR #246](https://github.com/scottconverse/civiccast-native/pull/246) hardens station-local scheduling and unattended operation.
- [PR #247](https://github.com/scottconverse/civiccast-native/pull/247) completes broadcast outputs, programme transitions, HLS retention and recorded-caption settings.

## Measured operation

A Beta 11 host ran Public, Government and Education channels together for 72 hours with **99.78% live caption-input coverage**. The [72-hour host report](ops/beta11-host-caption-performance-72-hour-2026-10-11.md) gives the channel totals and measurement. The [Beta 15 verification record](releases/v1.0.0-beta.15-verification.md) separately records the published package's checks.

## Next work

The owner sets the next implementation and release scope. The Beta 15 verification record documents its exact-package installation and restoration observations, including the limits on cross-version upgrade and interrupted-install claims. Target-machine installation and sustained-operation reports remain owner-managed field work.

Future priorities will use actual station feedback and measured problems. No dates or additional features are promised by this page. Caption reporting benchmarks are advisory; Scott decides release acceptance.

## Earlier roadmap

The [earlier roadmap](history/roadmap-before-beta12-doc-audit-2026-10-11.md) is retained as historical planning. Its WSL/rc release line, old milestone numbers and implementation cursor are not the current native Windows roadmap.
