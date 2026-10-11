# CivicCast roadmap

**Current release: [v1.0.0-beta.12](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.12)**, published October 10, 2026 (Mountain time). CivicCast is one native Windows product.

## What Beta 12 delivers

Beta 12 hardens unattended station operation and the existing operator workflows: caption health and lazy Whisper fallback, bounded supervisor logs, scheduled recordings, summary approval and signed-record exports, local administrator recovery, Control Room session recovery, remote guest media controls, alert routing and emergency presentation, paywall-secret preservation, and updated documentation.

Whistle is the CPU primary for live captions. Whisper provides per-channel fallback and recorded-media transcription, with optional supported NVIDIA acceleration.

## Measured operation

A Beta 11 host ran public, government and education channels together for 48 hours, with **99.88% live caption-input coverage**. The [soak report](ops/beta11-host-caption-performance-48-hour-2026-10-10.md) records the measurements. This is a measured result from that run; the [Beta 12 verification record](releases/v1.0.0-beta.12-verification.md) separately records the current package's checks.

## Next work

The owner sets the next implementation and release scope. Remaining exact-package checking from the Beta 12 handoff concerns interrupted-install recovery and completion of the post-upgrade observation. Target-machine installation and sustained-operation reports are owner-managed field work, not a mandatory Ryzen or release gate.

Future priorities will use actual station feedback and measured problems. No dates or additional features are promised by this page. Caption reporting benchmarks are advisory; Scott decides release acceptance.

## Earlier roadmap

The [earlier roadmap](history/roadmap-before-beta12-doc-audit-2026-10-11.md) is retained as historical planning. Its WSL/rc release line, old milestone numbers and implementation cursor are not the current native Windows roadmap.
