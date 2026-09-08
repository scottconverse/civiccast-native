# Exact candidate pre-install retry

This is dedicated-tester support, not CivicCast product code. The original
verification loop used `$matches`, which PowerShell overwrites as its built-in
`$Matches` during the SHA-256 regex. Reading the next record then fails before
artifact-verification receipts or installation. The corrected helper uses
`$runtimeEntries`; both real candidate runtime hashes are checked in tests.

The retry requires the actual R4 report from the confirmed tester run: its
bounded signal must contain both `property_missing` and `native_command_error`,
identify missing property `sha256`, mention
`AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1`, contain no structured script
location, and contain only outer line locations 51 and 56. It does not claim a
remote source line. The retry also requires the same initial unprogressed
identity, unchanged old service PID/start, and no active installer, soak, exact
sampler task, or previous retry state.
It verifies six reviewed script hashes, copies them to a NEW child directory
`missions\beta5-sep8-be1260bd0630\bin\install-retry-r1`, rechecks copied bytes,
and preserves every original mission script file. Git enforces LF for all
six files; the approved manifest contains the actual LF file-byte SHA-256.

It reuses already downloaded matching files, verifies every artifact again,
and performs one normal upgrade of the dedicated tester. There is no uninstall,
station-data removal or reboot. The installer wait records PID/start before
waiting for the primary setup process, not all descendants. A45-minute timeout
leaves the process running for diagnosis and refuses blind replay.

After installation, the existing source/health checks must pass. The corrected
ffprobe discovery finds the signed install layout. Two mission assets are
prepared and the three loopback test channels are scheduled. The first actual
three-channel GStreamer/TSDuck measurement must pass before the exact recurring
sampler is registered. The two-hour timer/verdict criteria are unchanged.

A new journal directory and exclusive persistent lock record progress. Failure
or partial output requires reconciliation of actual state, not rerunning this
entry point. The initial dispatch's historical Gate A/PENDING remains intact;
the current Gate A result is separate evidence.

Default execution is plan-only. The unique authorized autorun supplies
`-Execute` after parent verification. Tests cover facts/negative guards on
PS5.1/PS7, actual source-loop extraction against the signed be app manifest,
and real short child-process exit0/7 plus timeout-without-kill. None of those
tests is a completed tester installation or a two-hour media verdict.

The dispatcher verifies the wrapper's own manifest hash as well as all six
support hashes, copies them into a separate dispatch directory, and returns
`install-retry-r1.json` on the tester evidence branch. On failure that receipt
contains the actual journal stage and bounded exception type/source basename/
line, never token values or raw logs. The report is not a terminal soak PASS.
The R2 browser prerequisite directive uses the corrected common Git helper;
it only inventories installed tools and returns a fresh report, without
launching a browser or changing the installed station.

`Beta5Tester.Common.ps1` uses scoped native stderr capture for Git: successful
Git progress on stderr is returned as plain strings, while a non-zero exit code
still fails the operation. `Test-Beta5GitInvocation.ps1` covers both cases with
a local stub and no network access.
