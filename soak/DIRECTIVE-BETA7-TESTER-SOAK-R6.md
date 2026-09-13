# Beta.7 physical soak R6

Run only `soak/autorun/AUTORUN-BETA7-TESTER-SOAK-R6.ps1` on
`DESKTOP-VBMA6O5`. Preserve R1 through R5. R6 requires the exact local R5 FAIL
receipt for source `a963c39cc44e2643065a818aac0206b110d515d4` and its exact admission error,
plus the preserved R5 evidence and 180-row published plan. It reuses the verified
installed candidate and return checkout; it performs no installer or kit transfer.

R5 proved normal TSDuck exit and nonzero packet acquisition with zero invalid syncs
and zero transport errors. Its clean-admission failures were exactly one raw
discontinuity on each of PIDs 0, 32, 65, and 66 in each fresh receiver capture.
That pattern is consistent with receiver acquisition, while R5 did not record packet
positions that can prove the cause. R6 keeps the excluded acquisition diagnostic as an untrimmed
30-second probe. For clean admission and every measured verdict probe, the same
`tsp` process discards its first five seconds with `skip --seconds 5`, stops after
35 seconds, and analyzes only the remaining 30-second window. The classifier stays
strict: any raw PID discontinuity, invalid sync, transport error, zero packets,
abnormal exit, missing report, or timeout fails.

R6 otherwise retains the R5 controls: fresh supported schedule replacement limited
to the exact 180 IDs in the R5 plan, serialized bounded probes with a 10-second
receive timeout and 60-second process deadline, stable all-channel ON_AIR/PID checks,
diagnostic plus clean admission before both phases, full 120-minute captions ON and
120-minute captions OFF measurement, and unchanged F1/F2/F3 grading.
