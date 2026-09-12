# Return-path diagnosis for the fixed beta tester

The tester acknowledged Directive 5 and continues to publish heartbeats, but
no R1 or R2 readiness receipt has reached Git as of 2026-09-12T02:10Z.
This does not establish whether the probes ran, failed, or were suppressed.

AUTORUN-0-SEP11-READINESS-RETURN-R3.ps1 reads the poll tail and only the new
R1/R2 readiness logs, then commits a JSON receipt directly. It does not rerun
probes, delete markers, change the station, install anything, or alter tasks.
Its leading 0 lets the next poll run the short diagnostic before older orders.
The unique directive pointer requests a fresh automatic acknowledgment too.

Expected return: soak/fixed-beta-39e7/readiness-return-r3.json on
tester/soak8-e1acfe6-DESKTOP-VBMA6O5. Preserve existing results and all three
CivicCastSoak coordination tasks. Candidate and release state remain as recorded
in Directive 5; no remote installation or soak PASS is claimed.
