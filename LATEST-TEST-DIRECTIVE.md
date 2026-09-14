# soak8-e1acfe6 Latest Test Directive

Current: `soak/DIRECTIVE-BETA7-FINALIZE-R5-INVALIDATION-E27A91B.md`

Autorun: `soak/autorun/AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91B.ps1`

Candidate: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`, build `34762831824`,
Gate A PASS run `34772707033`.
R5 is invalid. Its cleanup order ran, but normal Git progress on stderr was
misclassified as a PowerShell failure before the invalidation receipt could be
published. The first receipt finalizer then required a field absent from the
older per-run `IDENTITY.json` and also halted before writing. This corrected
once-only order performs read-only verification of the exact R5 task,
processes, channel configs/states, and owned schedule rows, then publishes and
remotely verifies only `job.json` and `INVALIDATED.json`.

No replacement soak is authorized by this directive. Failed and invalidated
missions, completion markers, state, and evidence remain preserved.
