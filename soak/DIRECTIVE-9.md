# Run the fixed candidate's physical soak

Candidate: 39e7ec3cbb4ccbeb3009ff3257dfc314010151f3.
Signed build: 34633364038. Gate A 34656528653 completed successfully with
clean-install, cross-version upgrade and download-only PASS verdicts for this
candidate. The workflow harness SHA differs intentionally from the candidate.

Tester upgrade PASS is recorded in tester commit
26e904b049af14b4facfc32dd433f9c1eb5429ce, autorun log
AUTORUN-SEP11-FIXED-BETA-UPGRADE-R1-20260912T030611Z.log. It verifies the manifest,
installer signature/hash, installed beta.6 service and daemon/strategy hashes.
Installation finished at 2026-09-12T04:07:29Z. The installed identity's Gate A
PENDING field is the historical snapshot from the installation order; this
directive records the subsequently completed Gate A without replacing that
identity or its actual installed hashes.

Execute AUTORUN-SEP11-FIXED-BETA-PHYSICAL-SOAK-R1.ps1 once. It launches the
dedicated task CivicCast-FixedBeta-39e7-PhysicalSoak-R1 with a six-hour limit.
The poller returns after requesting launch; its four-hour limit must not wrap
the full soak. Keep CivicCastSoak-Poll, Heartbeat and Boot enabled.

The task verifies the installed candidate again, then uses the existing three
test channels and published assets through supported APIs. It snapshots and
replaces overlapping test schedules, preserves station data and tokens, and
measures 120 minutes with captions ON followed by 120 minutes OFF. Programmes
change every five minutes. Setup includes a fifteen-minute schedule lead and
does not count toward measured time. Software fallback is disabled for these
GStreamer measurements. Channels stop after collection.

The task records channel state, worker PID/RSS, CPU/RAM, caption proofs, raw
worker logs, boundary timing and periodic asynchronous TSDuck loopback probes.
It publishes job.json and the final evidence.zip under
soak/fixed-beta-39e7/physical-soak-r1 on the tester evidence branch. Local files
remain in C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c.

LAUNCH_REQUESTED and job STARTED do not prove measured time has begun. Inspect
the phase SOAK-START.json records. COLLECTION_PASS covers timing, worker lifetime
and transport only; the coordinator must still assess transaction-specific
preroll, healthy pipeline topology and caption evidence. No release or physical
headend acceptance is claimed by this order. The candidate is not published.

Do not replay this order, remove once-only markers, or restart a running soak.
Failures preserve their evidence for a later unique corrective order.
