# soak8-e1acfe6 Latest Test Directive

Current: `soak/DIRECTIVE-BETA7-INVALIDATE-R5-E27A91.md`

Autorun: `soak/autorun/AUTORUN-00-BETA7-INVALIDATE-R5-E27A91.ps1`

Candidate: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`, build `34762831824`,
Gate A PASS run `34772707033`.
R5 is invalid and must stop. Two independent audits found multiple false-pass
paths and an impossible transport cadence. The invalidation order disables the
R5 task, proves its exact job process is gone, cancels only its own verified
schedule rows, records an immutable invalidation receipt, and leaves the three
channels enabled, stopped, and with auto-start disabled.

No replacement soak is authorized by this directive. Failed and invalidated
missions, completion markers, state, and evidence remain preserved.
