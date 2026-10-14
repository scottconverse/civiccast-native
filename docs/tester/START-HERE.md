# Beta16 tester quickstart

**`v1.0.0-beta.16` is an unpublished candidate.** Check the [candidate
verification record](../releases/v1.0.0-beta.16-verification.md) and the active
[owner handoff](../../HANDOFF.md) for package status and the exact kit assigned
for testing. Public release downloads continue to serve Beta15 until publication.

## Install, open, and check

1. **Confirm the candidate is ready for your assigned check.** The verification
   record must identify the package, and the active handoff must name the exact
   artifact and requested test. Do not substitute the public Beta15 download.
2. **Prepare the complete kit.** Keep `setup.exe`, `packs\\`, and `station\\`
   together. Compare its manifest, installer hash, and signature with the active
   handoff using [Windows release trust](../install/windows-release-trust.md).
   Stop and report any mismatch before running setup. If Windows shows
   **Windows protected your PC**, use the
   [SmartScreen walkthrough](SMARTSCREEN-WALKTHROUGH.md) after checking the
   package identity.
3. **Install on the named Windows station.** Run `setup.exe` from the kit and
   follow the installer prompts, approving Windows administrator access when
   requested. For an assigned upgrade, back up the station and plan for the
   service interruption; use the handoff's exact upgrade baseline and steps.
   See [Install CivicCast on Windows](../../INSTALL-WINDOWS.md) for the station
   requirements and folder layout.
4. **Open the operator console** from the CivicCast shortcut or visit
   <http://127.0.0.1:8000/operator/> on the station computer. On a fresh station,
   name it, create the first administrator, and save the recovery kit. Open
   **System Health** and confirm the station and configured services report
   their current state.
5. **Run the assigned feature checks.** The Beta16 source work covers station
   operations, unattended scheduling, broadcast outputs, and recorded captions.
   Follow the handoff's scenarios, and record what you actually observed,
   including any incomplete or blocked step.
6. **Send useful evidence.** Record the candidate version, package hash, station,
   date and time, steps, results, and relevant logs. Create a redacted
   [support bundle](support-bundle-instructions.md) when requested. Exclude passwords,
   recovery codes, provider secrets, and resident personal information.

## If setup or the station does not work

Preserve the exact error, installer exit code, and
`C:\\ProgramData\\CivicCast\\install-progress.log`. Check the service and
installation logs before retrying. Use the [support guide](../../SUPPORT.md) and
[bug report template](bug-report-template.md); report package identity and
station observations separately. Do not infer a cause from a screen or a single
failed step.

For a meeting-night rehearsal, use the
[first broadcast checklist](first-broadcast-checklist.md). For station recovery,
use [recovery kit help](recovery-kit-help.md). The [current user
manual](../USER-MANUAL.md) describes operator features.

## Historical package evidence

The currently published native release remains `v1.0.0-beta.15`; its public
download is not the Beta16 candidate. The [Beta15 verification
record](../releases/v1.0.0-beta.15-verification.md) contains package-specific
results. Its R9 field findings and follow-up work are listed in the
[Beta17 deferred backlog](../ops/beta17-deferred.md). Those observations do not
establish Beta16 runtime behavior.

Historical Beta11 evidence is separate from current package checks. A Beta11
host ran Public, Government, and Education together for 72 hours, with 99.78%
live caption-input coverage and 216 healthy scheduled checkpoints. See the
[72-hour host report](../ops/beta11-host-caption-performance-72-hour-2026-10-11.md).

Older Beta10 and earlier verification records are retained in
[`docs/releases`](../releases/). They describe their specific packages and do
not establish Beta15 or Beta16 results. The retired WSL2 product line and its
`rc` releases belong to a separate repository and are not current tester
instructions.
