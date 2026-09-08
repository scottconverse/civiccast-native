# CivicCast beta.5 resident-browser proof

This inert helper is the browser portion of the post-soak acceptance sequence. It
uses an explicitly supplied `node.exe`, an absolute installed `playwright-core`
package, and an explicit installed Edge or Chrome executable. It never runs npm,
installs or downloads a browser, reads a CivicCast staff token, or calls a staff
API.

Without `-Execute`, the PowerShell entrypoint validates its explicit paths and
prints a `NOT_RUN` plan. It does not create the evidence directory or launch a
process. Live execution has intentionally not been performed while this package
is in the workspace.

## Outer acceptance guard required

A parent post-soak wrapper must establish all of the following before adding
`-Execute`:

- exact tester hostname and beta.5 mission identity;
- terminal post-soak PASS;
- the selected asset is one of the two approved assets recorded by the caption
  acceptance evidence;
- stable installed service identity and fresh installed hashes for
  `civiccast/egress/daemon.py` and `civiccast/egress/gst/strategy.py`;
- a fresh, mission-confined evidence directory that does not already exist.

The runner's `candidate_source_sha` is an outer-guard input, not independent
proof of installed source.

## Live contract

For `http://127.0.0.1:8000/#/watch/<exact asset id>`, the runner uses a fresh
temporary persistent context under the evidence directory. `USERPROFILE`,
`APPDATA`, `LOCALAPPDATA`, `HOME`, `TEMP`, and `TMP` are redirected into that
temporary root. The directory is removed after pass or failure. This is
environment and browser-profile isolation, not an OS sandbox.

Every page request is restricted to exact origin `http://127.0.0.1:8000`, and
any Authorization header fails the proof. Only GET/HEAD requests reach the
station. The portal's expected playback-analytics POST is aborted inside the
browser routing layer and recorded as blocked before network; any other
mutation attempt fails the proof. Real HLS requests are not mocked.

PASS requires:

- anonymous public asset metadata for the exact asset ID;
- its loopback master playlist with declared variants and exactly the required
  English and Spanish subtitle languages;
- a browser-fetched 200 variant playlist with real media references;
- browser-fetched 200 English and Spanish subtitle playlists and at least one
  timed WebVTT segment from each;
- the shipped `Meeting video player` element decoding visible video without a
  media error and advancing `currentTime` from the reset start to at least three
  seconds;
- an explicit Off state before each language selection, then exact English and
  Spanish buttons becoming `aria-pressed="true"` **and** the corresponding
  `video.textTracks` language becoming the sole `showing` track;
- a nonempty browser cue list and an active timed cue while the video is
  playing, with that active cue matched by timing and text to a 200 WebVTT
  response fetched for the same manifest language.

The response ledger is intentionally cumulative within the fresh isolated
context. A browser may legitimately cache or prefetch a subtitle playlist and
VTT before a later click, so PASS does not demand a duplicate network request
after every selection. Causality instead comes from the measured transition
from real text tracks Off to the requested sole `showing` language; the
previously fetched response must still bind to that active cue.

`TimeoutSeconds` is a single end-to-end deadline, with a reserved cleanup
window, rather than a fresh timeout for every polling stage.

The evidence records response status, byte length, and SHA-256, not caption
text. This proves actual resident-browser playback and caption-control wiring.
It does not certify transcript editorial accuracy.

Example plan only:

```powershell
.\Invoke-Beta5ResidentBrowserProof.ps1 `
  -NodePath 'C:\Program Files\nodejs\node.exe' `
  -PlaywrightCorePath 'C:\approved\node_modules\playwright-core' `
  -BrowserExecutablePath 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' `
  -AssetId '<approved asset id>' `
  -CandidateSourceSha '<40hex candidate SHA>' `
  -EvidenceRoot 'C:\CivicCastSoak\missions\<mission>\resident-browser-proof-r1'
```

`-Execute` is deliberately omitted above.

## Hermetic tests

The tests do not start CivicCast or a browser:

```powershell
node.exe .\Test-BrowserProofContracts.cjs
node.exe .\Test-ResidentBrowserRunner.cjs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Test-BrowserProofPlan.ps1
pwsh.exe -NoProfile -File .\Test-BrowserProofPlan.ps1
```

They cover exact-origin and credential rejection, exact asset validation, HLS
master/variant/subtitle/VTT parsing, bilingual-track requirements, entrypoint
syntax, and the no-execution plan contract. The full fake-browser runner tests
also reject cosmetic-only buttons, the wrong showing language, missing active
cues, Authorization/non-loopback/mutation attempts, cleanup failure, and global
deadline expiry. That fake-browser suite validates proof logic only; it is not
live playback evidence.
