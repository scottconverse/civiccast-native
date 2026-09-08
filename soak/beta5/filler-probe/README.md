# CivicCast beta.5 installed-runtime filler acceptance probe

This probe targets one explicitly named disposable TEST station and channel. It does
not install CivicCast, discover machines, wipe state, restart services, or reboot.
Without `-Execute`, it only validates parameters and writes a plan. With `-Execute`,
it creates two schedule items and optionally 13 approved bulletins through the
installed station API, then observes the already-running channel.

Expected wall time is about 8–15 minutes: setup lead + first finite program + a
90-second filler gap + second program + observation slack. Use a dedicated channel
with no overlapping published schedule. `-LongBoard` proves all 13 submissions are
retained by the installed API and that the resulting filler remains valid TS across
the gap. It does **not** claim that all 13 individual slides were visually observed;
the public/state contracts expose the board queue and filler source, not the current
slide identity. A full visual rotation needs external frame capture/OCR or a longer
operator review.

Example planning-only invocation:

```powershell
powershell.exe -NoProfile -File .\Initialize-FillerProbe.ps1 `
  -ApiBase http://TEST-VM:8000 -ChannelId filler-probe -BearerToken REDACTED `
  -ExpectedSha 012345... -ExpectedVersion 1.0.0-beta.5 `
  -RunIdentityPath C:\CivicCastSoak\missions\MISSION\run-identity.json `
  -FinalVerdictPath C:\CivicCastSoak\missions\MISSION\return-repo\soak\beta5\MISSION\final-verdict.json `
  -UdpPort 19091 -TspExe C:\path\tsp.exe
```

Add `-LongBoard` for the 13-bulletin retention check. Add `-Execute` only after
confirming the named machine/channel is disposable and the
candidate is installed. Evidence is written beneath `results/<run-id>/`; the token
is never written. The caller should archive the installed candidate manifest and
installer hash alongside the result directory.

Run the executable probe locally on the named TEST machine: it resolves the reported
PID through `Win32_Process` and refuses a PID that is not the installed GStreamer
worker. The install receipt must contain the exact candidate SHA; its own SHA-256 and
path are retained in the result.

Pass requires observed `ON_AIR -> FALLBACK_SLATE -> ON_AIR`, unchanged nonzero
GStreamer PID, successful TS probes during all three phases, expected source labels,
and the expected version/SHA strings supplied by the dispatcher. SHA is recorded as
an asserted candidate identity; this API does not independently expose Git SHA, so
the installed kit manifest remains the authoritative SHA binding.

`Initialize-FillerProbe.ps1` is the post-soak entry point. It refuses unless the
actual `civiccast-native-beta5-media-verdict-v3` says `PASS` for the same mission and
`candidate_source_sha`, and the v3 run identity binds expected/actual installer,
manifest, and runtime hashes plus installed version. It refuses to replace any
existing channel id, resolves the identity's exactly two `approved_assets` against
the installed API as packaged, published, manifest-backed assets, records their API
identity, creates a fourth loopback
UDP channel, and starts the acceptance probe. After the probe returns it queues a
stop and retains the fourth channel disabled because the API has no delete endpoint.
Choose a new dedicated id and unused UDP port. A `finally` block attempts both stop
and disable even if start or acceptance fails, and records either cleanup failure;
the script never alters any pre-existing channel.

## In-process token boundary

This correction was developed and tested in a separate workspace before being
integrated into this control package. The verified baseline SHA-256 values were
`e0190c2dd7f5d6ac08c6b0024486950310fdc10d067140ceac690d8292eb3969` for
`Initialize-FillerProbe.ps1` and
`98e0efcfddf6856dcd72989a7784d2ff25f29292a0e1481b1af107f0570f7081` for
`Invoke-FillerAcceptance.ps1`.

The initializer now calls the acceptance script in the same PowerShell process
with a splatted parameter hashtable. The bearer value remains an in-memory
PowerShell argument and is not placed in a native child process command line.
Actual `.ps1` child tests corrected an earlier scriptblock-based inference: `exit`
from a called script file returns to its caller, sets `$LASTEXITCODE`, and allows
the caller's `finally` and result-writing logic to run under both Windows
PowerShell 5.1 and PowerShell 7. The initializer clears stale `$LASTEXITCODE` before
the call and accepts only explicit `0`, `1`, or `2` results.

`Test-FillerInvocationBoundary.ps1` invokes copied production acceptance bytes for
plan and early trapped-error paths, then invokes the actual initializer with
hermetic HTTP/acceptance stubs. It covers PASS, proof FAIL, trapped error, invalid
exit, and a child that returns without setting an exit code, without contacting
CivicCast.
