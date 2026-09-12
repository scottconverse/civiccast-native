# Correct the physical soak harness and launch attempt R2

Read-only progress receipt 8c5f59d3 proves R1 stopped at 2026-09-12T04:27:04Z
before either measured phase. The channel-inventory preflight rejected the
response. Locally reproduced PowerShell 5.1 behavior shows the REST helper
emits an entire JSON array as one pipeline object; capturing and returning the
response enumerates the rows correctly. The helper now normalizes all list
responses and saves the observed channel count/IDs before checking them.

R1's failure-report upload separately failed because ZipArchiveMode was not
loaded. The wrapper now loads both compression assemblies and publishes the
terminal job status even if archiving fails. R1's old remote STARTED receipt is
superseded by the returned local FAIL evidence, not evidence of a running soak.
No GStreamer runtime verdict was established by R1.

Execute AUTORUN-SEP11-FIXED-BETA-PHYSICAL-SOAK-R2.ps1 once. This is a new attempt,
not a replay of R1. It requires R1 to be stopped with a local FAIL result. It
preserves the R1 task, scripts, logs, return checkout and once-only markers.
The verified installed identity remains at the original mission bin path.

Under C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c, R2 uses new paths:
physical-soak-r2-bin, physical-soak-r2, return-repo-r2,
physical-soak-r2-job.json/log and physical-soak-r2-publish-error.txt.
Task: CivicCast-FixedBeta-39e7-PhysicalSoak-R2, six-hour limit, once only.
Evidence branch destination: soak/fixed-beta-39e7/physical-soak-r2/job.json and
evidence.zip. Preserve all three CivicCastSoak coordination tasks.

Candidate 39e7ec3cbb4ccbeb3009ff3257dfc314010151f3 remains installed, verified and
unpublished. No installer or runtime change occurs. Measurement remains two
120-minute phases ON/OFF with five-minute programme changes, exact three test
channels, GStreamer worker/transport evidence and subsequent raw-log assessment.
Setup time does not count. No measured phase has passed yet.
