# CivicCast beta.5 tester deployment package

The dedicated tester dispatch is
`soak/autorun/AUTORUN-SEP8-BETA5-BE1260-R1.ps1`, bound to candidate
`be1260bd0630261c571e3adf5aac6a6cbebd9e3a`, successful signed build34237280539,
and Gate A34242157263 with immutable kickoff status `PENDING`. The signed
installer and the complete 20-entry delivery manifest were independently hashed.
This is a dispatch record, not a successful installation or soak result.
The original dispatch's stable scripts remain unchanged on the tester. The
control copy now recognizes the signed installer's actual ffprobe location,
`dependencies\ffmpeg\bin\ffprobe.exe`, before its older-layout fallbacks.
If the original setup stops at that discovery step, inspect its installed
receipt and mission state before dispatching a source-bound continuation.
Do not reinstall or replace stable scripts while a mission is active.
The placeholder file `AUTORUN-SEP8-BETA5.ps1` in this support directory remains
an inert template for comparison, not an additional executable directive.

## Control-branch layout

Place exactly one new file in the existing poller's executable directory:

```text
soak/autorun/AUTORUN-SEP8-BETA5-BE1260-R1.ps1
```

Place the support package where the poller will not execute each step as a
separate autorun:

```text
soak/beta5/Beta5Tester.Common.ps1
soak/beta5/ProbeContracts.psm1
soak/beta5/Invoke-Beta5TesterMission.ps1
soak/beta5/AUTORUN-SEP8-BETA5-01-PREFLIGHT.ps1
soak/beta5/AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1
soak/beta5/AUTORUN-SEP8-BETA5-03-START-SOAK.ps1
soak/beta5/AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1
soak/beta5/AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1
```

The wrapper resolves `../beta5`, copies those scripts to
`C:\CivicCastSoak\missions\beta5-sep8-<sha12>\bin`, and only then runs the
stable copies. A reset of the directives checkout cannot change the scheduled
task's script path mid-run. The old recurring `AUTORUN-3.ps1` and general
poll/heartbeat jobs remain independent.

## Facts required before tester dispatch

Replace every placeholder in the wrapper from actual evidence:

- exact 40-character candidate SHA;
- the signed build run's exact `headSha`, successful conclusion, and positive run ID;
- the Gate A run's exact source SHA, positive assigned run ID, and truthful
  `PENDING` or `PASS` status;
- SHA-256 of the downloaded `SHA256SUMS.txt`, recorded independently;
- SHA-256 of the signed installer, recorded independently;
- candidate-bound LAN kit URL ending in `/<full-sha>/`;
- expected host `DESKTOP-VBMA6O5` and version `1.0.0-beta.5`.

The current LAN server serves `C:\CivicCastTester\kit-staging` on port 8766,
so the candidate directory must be a direct child of that directory. Do not
dispatch the wrapper while its candidate-bound kit, successful signed-build
evidence, assigned exact-source Gate A run, or signed hash receipts are absent.

`PENDING` authorizes only concurrent testing on the dedicated physical tester.
It is stored as immutable kickoff evidence and is never rewritten to `PASS`.
Public candidate publication or promotion remains separately gated on all three
Gate A lanes reaching `PASS`; neither tester startup nor a soak result satisfies
that release gate.

## What the mission does

1. Preflight rejects a wrong host, mismatched build/Gate A SHAs, a Gate A
   verdict other than truthful `PENDING`/`PASS`, a non-successful build, an
   unbound URL, or missing facts before writes. An existing
   identity is immutable: an exact rerun keeps its verification/install
   receipts; a differing rerun fails.
2. Fetch verifies the manifest against the independent manifest digest before
   trusting it. Every relative manifest path is confined under the kit root,
   traversal/absolute/ADS/reparse paths and duplicates are rejected, every file
   is hash checked, and the kit must contain exactly one root
   `*_x64-setup.exe` plus manifest-bound sample media.
3. Install verifies the installer again against its independent digest,
   ProductVersion `1.0.0-beta.5`, Authenticode `Valid`, and signer simple name
   `Scott Converse`. It performs a normal silent upgrade to
   `C:\CivicCastHostStore\install`. It does not uninstall, wipe ProgramData,
   delete the install root, or reboot.
4. Post-install requires `/health` `healthy`, schema `current`, exact version,
   a running `CivicCastSupervisor` whose executable is confined under the
   install root, and matching Installed Programs identity. Because beta.5 can
   replace another beta.5, version equality is not accepted as source proof:
   the verified `native-app-payload.ccpack` manifest must name the exact clean
   candidate SHA, and installed `runtime\Lib\site-packages` copies of
   `egress\daemon.py` and `egress\gst\strategy.py` must hash-match that pack.
   The supervisor PID/start time must also prove the service restarted after
   this installer invocation.
5. Start reuses the existing token at `C:\CivicCastSoak\state\token`; it never
   creates, prints, or commits credentials. Exactly two verified kit samples
   are uploaded through the proven multipart API, packaged, readied, approved,
   and measured with installed `ffprobe.exe`. Scheduling uses whole seconds
   rounded down, matching the product ingest API; it never adds a nonexistent
   fractional tail. After both approvals succeed,
   their IDs, durations, and exact titles are stored in deterministic program
   order as the identity's `approved_assets` receipt for the post-soak filler
   probe; existing install and immutable kickoff receipts are retained.
6. All three 2h15m schedules and Commit-to-Air calls complete before the first
   channel config or start. `public/9001`, `education/9002`, and
   `government/9003` must all prove `ON_AIR` on real Python
   `egress\gst\worker.py` processes before the soak clock is written.
7. An immediate TSDuck cycle must prove positive packets and zero invalid sync,
   transport-error, and discontinuity counters for all channels. Only then is
   a mission-specific recurring task registered at the identity's 60-second
   cadence. `IgnoreNew` prevents overlapping task instances.
   Before upgrade/sampling, the exact legacy `state\soak-started` trigger is
   moved recoverably into the new mission's `archive` directory. This prevents
   legacy `AUTORUN-3` from competing for UDP 9001-9003 while preserving all old
   evidence and leaving the control poll/heartbeat jobs alive.
8. Verdict evaluation fails closed on a wrong/missing channel, missing or
   changed PID, non-GStreamer worker, absent/nonpositive packet evidence,
   missing/nonzero counters, reload abort/stall, identity drift, or a gap over
   180 seconds. Elapsed time alone cannot PASS. PASS requires at least 7200
   seconds of actual continuous coverage.
9. Telemetry is confined to `soak/beta5/<mission>/`. Before every commit the
   return checkout pulls/rebases its fixed tester branch, reducing races with
   the existing publisher. After a terminal PASS or FAIL is successfully
   published, only the exact beta.5 mission task unregisters itself.

## Local verification (safe; no tester deployment)

Run in Windows PowerShell 5.1 from this directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Test-Beta5TesterIntegration.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Test-Beta5SoakVerdict.ps1
```

The integration test uses only a temporary directory and mocked API calls. It
checks path confinement, exact-source `PENDING` kickoff acceptance, invalid
verdict/source rejection, required/immutable identity behavior, the ordered
two-asset approval receipt, flat installer and sample manifest handling,
all-schedules-before-start ordering, unresolved
wrapper failure, and scheduler contracts. The verdict test includes timer-only,
empty-channel, missing PID/packets/counters, gap, SHA, relaunch, and reload-abort
negative cases.

These tests and parser checks prove the package contracts, not a deployment.
Tester acceptance still requires the final signed kit, real tester upgrade,
real API provisioning, two hours of TSDuck samples, and the published verdict.
Release publication additionally requires the independently recorded PASS from
all three Gate A lanes.

After the three-channel soak passes, the separate
[installed filler probe](filler-probe/README.md) can verify program-to-bulletin
and bulletin-to-program handoffs on a new loopback-only test channel. It is
not automatically dispatched by this support package.

The [caption acceptance package](caption-proof/README.md) is also inert until
an explicit post-soak invocation. It requires the exact candidate's terminal
PASS, fresh installed runtime hashes and mission-owned sample assets. It tests
English/Spanish approval and anonymous VTT delivery, not editorial accuracy or
resident browser playback.

The separate `AUTORUN-SEP8-BETA5-BROWSER-INVENTORY-R1.ps1` directive performs
only an exact-host inventory of known Node/npm/browser/Playwright paths and
mission-stage file presence. It reads no operator token, calls no station API,
starts no browser and changes no service, channel, schedule or installation.
It publishes one JSON report through a separate checkout of the established
tester return branch, leaving the active sampler checkout alone. The normal
poller's non-overlap rule determines when it can run; a queued inventory is
not proof that the tester has executed it.
