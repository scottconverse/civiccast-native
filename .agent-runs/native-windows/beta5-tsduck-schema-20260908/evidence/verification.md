# Sandbox TSDuck report parsing repair

This is test-harness maintenance, not product acceptance or a release claim.
The signed application candidate remains be1260bd0630261c571e3adf5aac6a6cbebd9e3a.

## Failure and contract

The installed three-channel run `soak-be1260b-20260908-191210Z` finished FAIL
on 2026-09-08 with 28 unplanned restarts. Its old sampler treated the current
TSDuck `ts.packets` object as a scalar and consequently lost 27 probe verdicts.
The other six probes timed out and did not produce valid analysis.

The repaired sampler reads required nonnegative Int64 counters from
`ts.packets.total`, `ts.packets.invalid-syncs`, and
`ts.packets.transport-errors`. It sums the explicitly named per-PID
`packets.discontinuities` counters. That is not a PCR-only measurement.
Absent/malformed counters fail closed; timeout and restart criteria do not change.
The helper is parsed by the host and loaded by the actual guest driver.

## Executed verification

- Root ran `powershell.exe -NoProfile -File sandbox-lab/scripts/Invoke-LaneUnitTests.ps1`:
  all 10 discovered suites passed, including the new classifier, real dry-run
  host/template/guest bounds, and all 70 existing final-verdict assertions.
- Implementer ran classifier and verdict suites in PowerShell 5.1 and 7:
  both passed; missing/null/negative/noninteger and large Int64 cases included.
- Root replayed the new parser against all 33 original report files, read-only:
  19 pass, 8 fail-stream-errors, 6 no-valid-analysis. Original reports and
  the original FAIL verdict were not modified or replaced.
- Focused Python wiring contracts and Ruff passed locally. Exact-head remote
  CI must pass before merge; local success is not a remote-CI claim.

The mutation workspace fixture-copy correction matches the independently
reviewed PR197 correction: policy tests require `sandbox-lab` in that copy.
No tests are skipped to accommodate its absence.

## Scope review

Engineering: actual nested schema and guest call path verified.
UX: the harness README explains the counters and unchanged failure criteria.
Tests: real PowerShell decision assertions and retained-report replay, not just grep.
Docs: README and CHANGELOG aligned; application/manual/version untouched because
this change adds no product capability or installation behavior.
QA: the failed candidate remains failed and unpublished; no readiness claim.

The physical tester independently reported a changed PID, Education stream
discontinuities and a Public timeout at 19:41:33 UTC. This parsing repair does
not resolve any of those product signals. A corrected product still needs a
new source-bound build, installer acceptance and continuous media acceptance.
