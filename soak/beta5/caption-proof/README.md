# CivicCast beta.5 post-soak caption acceptance

This inert tester-side package closes one specific evidence gap after the normal
two-hour, three-channel soak. It does not change CivicCast source or Gate A, install
or restart anything, extend schedules, configure channels, publish to a provider,
launch a browser, or push evidence. The parent release operator owns review, copy,
dispatch, and publication of its results.

The reviewed deployment layout is
`<control-repo>/soak/beta5/caption-proof/`. From there, the entry points' defaults
resolve `Beta5Tester.Common.ps1` from `..` and the full tester evidence contract from
`../filler-probe/ProbeContracts.psm1`. The standalone workspace source directory has
different sibling names; invoke from that development location only with explicit
`-TesterPrepRoot ..\tester-beta5-prep` and
`-EvidenceContractsPath ..\tester-beta5-filler-probe\ProbeContracts.psm1`.

## Evidence boundaries

Gate A documents its `captions` criterion as proving that the offline pipeline
generated real cues from a real speech clip (`docs/ops/gate-a.md`, caption check).
Its current `CAPTIONS=PASS` is therefore generation-stage evidence, not inherently a
false result. A job with `cue_count > 0`, `state=awaiting_review`, and
`published_cue_count=0` is nevertheless insufficient for the broader installed
journey's caption-review and publication requirement.

`Invoke-Beta5CaptionAcceptance.ps1` separately proves the installed software
workflow for one exact asset already recorded in `identity.approved_assets`:

1. the v3 run identity and terminal PASS verdict match the expected candidate;
2. installed version and supervisor identity are still valid, and the exact current
   bytes of `runtime/Lib/site-packages/civiccast/egress/daemon.py` and
   `runtime/Lib/site-packages/civiccast/egress/gst/strategy.py` match the two-key
   candidate payload receipt immediately before and after the workflow;
3. the staff and public asset rows match the receipt and point to the exact local
   `/media/vod/<asset>/playlist.m3u8` path;
4. all generated English review rows belong to that asset and carry unique review
   and cue IDs;
5. low-confidence audio preview bytes are fetched and their size/hash evidence is
   recorded before the corresponding acknowledgement is sent; the complete selected
   review/cue ID set and a pre-POST intent event are also durably recorded, so a crash
   leaves an explicit partial-state boundary rather than an ambiguous replay signal;
6. English approval leads to an exact-size Spanish review pass, both languages are
   approved, and the same job completes with `published_cue_count == cue_count`;
7. the public master, English/Spanish caption playlists, referenced VTT segments,
   all referenced VTT segments, and both flat VTT sidecars are fetched anonymously
   over loopback and validated; and
8. the supervisor process, channel configuration identities, and available worker
   PIDs are unchanged afterward.

The only product mutations the helper can issue are
`POST /api/staff/captions/review-items/<exact-id>/approve` for the selected asset's
English and Spanish rows. It contains no schedule, channel command/configuration,
asset publication, job retry, install, service, reboot, Git, or provider-write call.
The bearer token is read from the existing tester token file and is never printed or
written to evidence.

This is an automated acceptance-test decision on mission-owned sample media. It
does **not** certify transcript or translation editorial accuracy. A human quality
review must listen and correct text as appropriate; the automation only proves that
the review controls, low-confidence evidence gate, translation phase, packaging,
and public delivery contracts function end to end.

HTTP/HLS success also does **not** prove resident browser playback. The result always
records `resident_browser_playback=NOT_RUN_REQUIRES_SEPARATE_BROWSER_PROOF`.

## Planning and execution

Without `-Execute`, the entry point validates the source-bound identity and PASS
verdict and emits a JSON plan. It does not read the token or contact the API.

```powershell
powershell.exe -NoProfile -File .\Invoke-Beta5CaptionAcceptance.ps1 `
  -ExpectedSha <40-hex-candidate-sha> `
  -ExpectedVersion 1.0.0-beta.5 `
  -AssetId <one-id-from-identity-approved_assets> `
  -RunIdentityPath C:\CivicCastSoak\missions\<mission>\run-identity.json `
  -FinalVerdictPath C:\CivicCastSoak\missions\<mission>\return-repo\soak\beta5\<mission>\final-verdict.json
```

After parent review, add `-Execute`. The default bound allows up to 30 minutes for
the worker's English-to-Spanish transition and final attachment. A failed or partial
run must not be replayed blindly: review its JSON evidence and current queue state
first. The helper deliberately requires a clean generated-but-unreviewed boundary,
so it will not silently reinterpret a partially reviewed or already-complete job as
a new end-to-end proof.

The three existing schedules end shortly after the two-hour soak. A legitimate
channel may therefore transition between `ON_AIR` and `FALLBACK_SLATE` while this
post-soak check runs. Both are accepted healthy states. The report records such a
transition separately and fails only for a changed configuration, changed available
worker PID, unhealthy state, or changed supervisor PID/start time. The helper issues
zero channel or schedule mutations and does not extend the schedule merely to keep a
test green.

Evidence is written beneath the selected mission state root. It contains hashes and
sizes of preview/VTT bytes, not preview audio, caption text, or the bearer token.
The before/after service evidence includes the two freshly measured installed-runtime
hashes. `Assert-CaptionInstalledRuntimeHashes` is exported from the contracts module
so the parent can reuse the same exact-byte check in a later filler wrapper without
changing the shared tester common helper.

## Resident browser proof: inventory and plan only

`Get-Beta5BrowserPrerequisites.ps1` is a read-only inventory restricted to
`DESKTOP-VBMA6O5`. It checks fixed Node/npm/Edge/Chrome paths, performs read-only
`Get-Command` path resolution for Node/npm without executing them, and checks the known
portal-public `node_modules/@playwright/test/package.json`, Playwright config, and
existing mocked caption spec beneath the identity's return repository. It reads file
metadata/package manifests; it does not execute Node/npm, launch a browser, scan user
profiles, or install anything. It emits structured JSON to stdout.
The Node/npm availability flags include both fixed paths and successful PATH
discovery, so a portable installation is not incorrectly reported as absent.

```powershell
powershell.exe -NoProfile -File .\Get-Beta5BrowserPrerequisites.ps1 `
  -RunIdentityPath C:\CivicCastSoak\missions\<mission>\run-identity.json
```

Python Playwright must not be assumed: the repository declares it only in an
optional extra and the native installer does not bundle it. If the inventory proves
an existing Node Playwright package and Edge or Chrome, a later, separately reviewed
resident-browser helper can open
`http://127.0.0.1:8000/#/watch/<encoded-asset-id>` and require all of the following:

- the public asset, local master/variant, selected caption playlist, and VTT segment
  requests succeed;
- the `Meeting video player` is visible with no player error;
- a user-initiated play leaves `paused=false` and advances `currentTime`;
- English and Spanish caption buttons exist; and
- choosing each track sets its own `aria-pressed=true` while its caption playlist and
  segment are fetched.

That browser action is intentionally absent from this package until prerequisites
and the exact installed harness are reviewed.

## Safe mocked verification

`Test-CaptionProofContracts.ps1` exercises the acceptance core entirely with mocked
HTTP/service data. Its in-memory `HttpMessageHandler` also exercises the real request
constructor without opening a socket: staff-only bearer placement, anonymous public
and media reads, JSON request/response, text and binary bodies, response disposal, and
redirect refusal. The suite covers the successful bilingual flow, preview-before-ack order,
local-manifest refusal before writes, mismatched cue identity, bounded missing-Spanish
failure, channel configuration drift, supervisor drift, expected
`ON_AIR -> FALLBACK_SLATE`, asset-path confinement, and absence of channel/schedule/
retry routes from the core. Temporary-file cases prove current runtime hash success
and fail closed for a changed file, missing file, or extra receipt key.

```powershell
powershell.exe -NoProfile -File .\Test-CaptionProofContracts.ps1
```
