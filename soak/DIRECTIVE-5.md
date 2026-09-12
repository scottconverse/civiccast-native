# Fixed beta tester takeover - September 11, 2026

Target: DESKTOP-VBMA6O5. The owner has authorized this tester for the remaining
CivicCast beta installation and soak work, keeping heavy tests off Halo.

Candidate source: 39e7ec3cbb4ccbeb3009ff3257dfc314010151f3.
Signed build: 34633364038. The earlier 795cdab5 kit remains blocked.
Harness fixes are merged separately at 5e8551a0b8983b8a3b2f54f7cb1641f55bec54cc.

The first order, AUTORUN-SEP11-FIXED-BETA-READINESS-R1.ps1, reads readiness and
prints a bounded report through the existing poller's autorun log return. It
does not install, stop channels, alter tasks, read token contents, or start a soak.
Do not manually rerun it or remove any completed-order marker.

A fresh heartbeat was received at 2026-09-12T01:36:11Z. It reports beta.5 and
soak_started=false. Its ON_AIR labels with disconnected sinks do not prove playout.
The new autorun receipt must establish that the poller is executing current orders.

Next: use the readiness report to transfer and verify the fixed kit, then run
the remaining installer acceptance and captions ON/OFF programme-change tests.
No fixed candidate release or physical-tester soak PASS is claimed yet.
