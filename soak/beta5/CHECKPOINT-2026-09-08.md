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
