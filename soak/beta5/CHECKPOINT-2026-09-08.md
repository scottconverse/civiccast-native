# Beta.5 tester support checkpoint

This support-only change does not dispatch a test, install software, restart a
station or create a scheduled task. The unresolved wrapper template is stored
under `soak/beta5`, outside the poller's executable `soak/autorun` directory.

The product candidate being built is
`be1260bd0630261c571e3adf5aac6a6cbebd9e3a`, build34237280539. Its build and
installation/soak evidence are not complete at this checkpoint. Do not infer
artifact verification from this support commit or fill missing facts by guesswork.

The package verifies independent manifest/installer digests, signed publisher,
clean candidate app-pack identity, and installed runtime-file hashes. It uses
normal upgrade on the dedicated tester, not uninstall/data removal. It retains
the legacy heartbeat/poller and archives only the prior soak trigger marker.
Two approved sample IDs/titles/durations are recorded; three channels are fully
scheduled before start. A new run needs actual GStreamer PIDs and transport
packets, zero restart/reload/stall counters, bounded sample gaps and two hours.

Successful signed build plus exact-source Gate A PENDING allows parallel tester
operation; public publication still requires all three Gate A lanes to PASS.
Kickoff evidence stays immutable. A completed/active mission cannot be replayed.

Verification: parent reran both PowerShell integration and strict-verdict tests;
the independent implementation/review agent also checked all 11 executable
scripts/modules with Windows PowerShell 5.1. Actual-media parsing was checked
against the shipped TSDuck schema, not only invented fixture keys. These are
support-contract checks, not tester installation or two-hour acceptance.

The older product code and manuals on this control branch are historical and
must not be merged over current product main. Product fixes use PR193; this
branch exists solely for dedicated tester execution/evidence coordination.

## Follow-up: finite-media rounding and installed filler probe

Parent review found that the helper rounded fractional durations up, while
`civiccast/schedule/ingest.py` uses `int(float(format.duration))`. The old
function returned32 for a31.75-second fixture; the product returns31. The helper
now matches the product's whole-second duration, and rejects nonfinite, invalid,
subsecond and overflowing values. Integration and strict-verdict suites pass.

The `filler-probe` subdirectory contains an additional inert post-soak test.
It requires the real three-channel PASS verdict and exact installed identity,
uses the two recorded approved assets, refuses an existing channel ID, and
creates a separate loopback test channel. It observes program/filler/program
states with unchanged GStreamer PID and real transport packets. Cleanup always
attempts stop and disable; the API has no channel-delete operation, so the
dedicated channel remains disabled. Thirteen accepted bulletin records prove
retention, not that all thirteen slides were visually observed on air.

Parent verification:15 script/module parser checks passed, all three functional
PowerShell test suites passed, and the preserved real bundled-TSDuck fixture
parsed65 packets with zero sync/transport/discontinuity counters. No filler
probe has run against a live tester at this checkpoint.
