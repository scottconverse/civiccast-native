# Diagnose the R2 startup timeout

R2 failed before measurement with "ON: all three channels did not reach ON_AIR."
Tester commit babb6825 returned the FAIL verdict and evidence archive. The
inventory correction worked: three expected channels were observed, and all
180 five-minute schedule slots were published. The first slot was scheduled
for 2026-09-12T05:21:32Z; the job ended at05:22:04Z. No measured phase began.

Execute AUTORUN-SEP11-FIXED-BETA-STARTUP-DIAGNOSTIC-R1.ps1 once. It returns
bounded worker stdout/stderr and relevant service-log tails, plus R2 progress
records. This read-only diagnostic does not start channels, replay a soak,
change schedules, modify tasks or read tokens. Preserve both failed attempts.
The coordinator will use these logs to distinguish startup timing from a
runtime failure before issuing the next corrected run.
