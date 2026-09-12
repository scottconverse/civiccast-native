# Return a read-only physical soak progress snapshot

The physical soak launched at 2026-09-12T04:26:17Z. Tester commit d29c123c
contains its job STARTED receipt and verified installed candidate identity.
That receipt does not establish the measured phase start.

Execute AUTORUN-SEP11-FIXED-BETA-SOAK-PROGRESS-R1.ps1 once. It reads the dedicated
task state and bounded tails of this mission's progress, phase SOAK-START,
verdict and publication-error files. The poller publishes its output log.
Missing files remain null; they are not treated as success or failure.

This diagnostic makes no station, schedule, task, token or marker changes.
Leave the physical soak running. Do not replay its launch order or clear any
once-only marker. Candidate 39e7ec3cbb4ccbeb3009ff3257dfc314010151f3 remains
unpublished pending physical evidence and acceptance.
