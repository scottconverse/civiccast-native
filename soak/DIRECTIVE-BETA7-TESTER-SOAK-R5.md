# Beta.7 physical soak R5

Run only `soak/autorun/AUTORUN-BETA7-TESTER-SOAK-R5.ps1` on
`DESKTOP-VBMA6O5`. Preserve R1, R2, the parsed R3 failure receipt, and the R4
autorun failure history. R3 failed before creating a physical-soak-r3 output
directory; R5 therefore requires `physical-soak-r3-job.json` with exact
`job_state=FAIL` and source `a963c39cc44e2643065a818aac0206b110d515d4`.
It does not require an R4 output because R4 never created its task.

R5 retains R4's Windows PowerShell 5.1-safe two-step 180-row plan parse and all
R3 controls: exact installed a963 identity and upgrade PASS, no installer or
kit transfer, existing return checkout, bounded fresh schedule cancellation,
serialized TSDuck, receive and lifecycle bounds, stable ON_AIR/PID checks,
admission before both phases, strict measured 0/0/0, and F1/F2/F3 grading.
