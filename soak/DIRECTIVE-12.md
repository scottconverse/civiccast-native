# Return the R2 physical soak phase-start evidence

R2 job STARTED at 2026-09-12T05:06:17Z is recorded in tester commit febde802.
Request one read-only progress snapshot after its setup window: execute
AUTORUN-SEP11-FIXED-BETA-SOAK-PROGRESS-R2.ps1 once. It uses the previously
verified bounded scalar diagnostic, targeting the R2 task and mission paths.
It also returns CHANNEL-INVENTORY.json to verify the corrected list handling.

Return task state and available phase SOAK-START, progress, verdict and
publication-error tails through the normal autorun log. Missing records remain
null. This order makes no station, schedule, task, token or marker changes.
Do not restart or replay R2 or R1. Candidate39e7 remains unpublished; measured
phase start and physical acceptance are not established by the launch receipt.
