# Diagnose the measured R3 worker stall

R3 began its measured captions-ON phase at 2026-09-12T05:46:33Z. At
2026-09-12T05:55:45Z the government channel changed from ON_AIR PID 3644 to
STARTING with no PID. Its last error says the GStreamer worker exited nonzero
after output stopped for 10 seconds and the daemon began relaunching it. The R3
collector then performed its normal failure cleanup and stopped all channels.

Execute AUTORUN-SEP12-FIXED-BETA-R3-FAILURE-DIAGNOSTIC-R1.ps1 once. It returns
bounded, hashed tails of the installed worker stdout/stderr and relevant service
logs, the R3 task/job/run records, and non-secret process metadata. This is a
read-only diagnostic. It does not call the CivicCast API, read or publish tokens,
start or stop channels, alter schedules, change tasks, replay a soak, or remove
any once-only marker.

Preserve R1, R2 and R3 evidence and the three CivicCastSoak coordination tasks.
Do not restart a soak. Candidate 39e7ec3c remains unpublished while the
coordinator identifies the stall cause and prepares a corrected candidate.
