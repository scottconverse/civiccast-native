# Stage 7 Final 4.0 Readiness

Stage 7 is the final integrated readiness envelope for the Stage 1 through Stage
6 work and the local release-hardening package that runs inside Stage 7. It is
not a publication action by itself.

## Required Inputs

- Stage 1 report and GauntletGate evidence.
- Stage 2 report and GauntletGate evidence.
- Stage 3 report and GauntletGate evidence.
- Stage 4 report and GauntletGate evidence.
- Stage 5 report and GauntletGate evidence.
- Stage 6 report and GauntletGate evidence.
- Stage 7 local release-hardening package.
- Current-head full-stack test run from `scripts/run_full_test_stack.ps1` with
  Python, web, installer, and skip-ledger lanes present.
- Local release artifacts manifest.
- Final 4.0 installer lifecycle proof, the final installer lifecycle evidence,
  covering clean install, first-run,
  repair, uninstall, reinstall, upgrade, app launch, health checks, and support
  bundle evidence using the final installer artifact.
- Upgrade matrix proof for all required 3.0/3.1/3.2 origins, including an
  explicit not-applicable classification when no local 3.1 release artifact
  exists.
- Clean Windows rendered first-run evidence that reaches the core CivicCast
  feature, not only the dependency-absent helper prompt.
- Current-head cleanroom evidence with skip-ledger classification and zero
  required skipped checks.
- Current-head final GauntletGate All report with all lanes run, zero findings,
  no skipped or waived required checks, and the current source HEAD recorded.
- 31-item 3.3-to-4.0 scope matrix with passed evidence for every item.

## Final Readiness Boundary

The Stage 7 proof checks the prior reports, requires a current-head full-stack
summary, runs local release hardening, builds local release artifacts,
verifies final 4.0 installer lifecycle evidence, and writes a 31-item evidence
matrix. Native installer execution is only claimed when a native installer
artifact and matching clean-machine lifecycle proof exist. Final installer
lifecycle readiness is still blocked until a clean Windows user reaches the
core CivicCast feature from the packaged installer path. A helper prompt,
UAC boundary, host WSL proof, or native install/app-launch transcript is useful
evidence, but it is not a clean Windows core-reached pass by itself.

Stage 7 does not publish a public release. Station-device evidence beyond prior
explicit station-bound artifacts is not claimed, and Stage 7 does not replace
GauntletGate.
