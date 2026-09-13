# Beta.7 physical soak R4

Run only `soak/autorun/AUTORUN-BETA7-TESTER-SOAK-R4.ps1` on
`DESKTOP-VBMA6O5`. Preserve R1, R2, and R3 completely. R3 failed before station
mutation because Windows PowerShell 5.1 preserved the top-level R1 plan array
as one pipeline object during direct assignment. R4 first assigns the parsed
JSON and then wraps it with `@($r1PlanData)`, matching the established driver
pattern and recovering all 180 plan rows.

R4 otherwise retains R3 unchanged: exact installed a963 identity and PASS
upgrade receipt, existing return checkout, no installer or kit transfer,
fresh supported schedule with cancellation restricted to the 180 exact R1
schedule IDs, serialized TSDuck with the documented 10-second receive timeout
and 60-second hard bound, stable three-channel ON_AIR/PID assertions, excluded
diagnostic plus clean admission before both phases, and strict measured 0/0/0
transport plus F1/F2/F3 grading.
