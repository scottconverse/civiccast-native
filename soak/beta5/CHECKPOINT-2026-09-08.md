# Beta.5 tester support checkpoint

## Inert browser support: 2026-09-08, 17:31 UTC

Seven new browser-proof files, plus these support docs and README banner.
No new autorun, remote browser launch, installed-service change or original
stable mission-bin edit. The physical tester has not returned its newcandidate
install receipt or two-hour verdict. Its 17:06 heartbeat reflects the older
running service, not proof of this candidate. The inventory autorun remains
queued behind the existing poller; do not replay installation blindly.

Root and independent Terra both executed the Node contracts/full fake runner
and PS5.1/PS7 inert-plan tests successfully. The initial cosmetic button gap
was corrected: each language must transition from all text tracks disabled
to the sole showing language with an active timed cue bound to a same-language
browser-fetched VTT. Previously fetched same-context responses are accepted
because real browsers may prefetch/cache subtitles. One deadline includes
browser cleanup; failure to remove the temporary profile forces FAIL.

Privacy proof is scoped to page requests after route registration, not an OS
network audit of browser-engine startup. Explicit installed tooling only;
no downloads, staff token, staff API or outgoing provider publication.
Fake-browser tests are proof of harness logic, not installed playback.

Gate A retry34248734841 clean lane PASSED and both evidence/verdict uploaded.
Cross-version upgrade is running; download-only remains pending. Signedbuild
34237280539/sourcebe1260bd0630261c571e3adf5aac6a6cbebd9e3a unchanged.
Original kickoff Gate34242157263/PENDING remains an immutable historical
dispatch fact. Public beta.4 remains current; no beta.5 tag/publication.

## Support and inventory update: 2026-09-08, 16:32 UTC

The candidate, signed kit, delivery manifest and original install dispatch are
unchanged. Gate A34242157263 produced an authoritative clean PASS, but its
separate GitHub evidence attachment failed with HTTP403; both upgrade lanes
were skipped. All98 local files were preserved with matching hashes. A normal
full retry34248734841 targets the same signed build34237280539. The original
tester's kickoff34242157263/PENDING is immutable, not rewritten to imply PASS.

Three scoped support changes are prepared:

1. The control START-SOAK copy now finds ffprobe in the actual signed install
   location, dependencies/ffmpeg/bin, before its two compatibility fallbacks.
   Both old candidate locations were absent in the verified local installation.
   The new regression was red before the resolver was added; complete support
   integration tests then passed in Windows PowerShell5.1 and PowerShell7.
   The installed tester's stable script is NOT changed by this control edit.
   Inspect the actual install receipt and absence of an active/terminal soak
   before deciding whether a continuation is needed. Do not reinstall blindly.
2. The inert caption-proof package adds exact-asset EN/ES review, current
   runtime-file hashing before/after, anonymous HLS/VTT delivery, durable
   pre-approval intent events and service/channel continuity. Core, actual
   HTTP construction and non-executing planning tests pass in PS5.1 and PS7.
   These are hermetic tests, not installed caption or resident-browser proof.
3. A unique BROWSER-INVENTORY-R1 autorun reads only known browser/tool paths
   and mission-stage file presence. It reads no token and calls no station
   API. It publishes one JSON result from its own separate shallow checkout,
   leaving the active sampler checkout alone. Its dry-run passes. Actual
   pickup still depends on the existing poller finishing any running task.

No caption approval or browser playback is dispatched by this update. The
physical installation, two-hour media verdict and post-soak acceptance remain
pending. The control branch is not a product branch and must not be merged
over current main.

## Current dispatch: 2026-09-08, 15:04 UTC

The exact-candidate wrapper `soak/autorun/AUTORUN-SEP8-BETA5-BE1260-R1.ps1`
is prepared for the dedicated tester poller. Candidate
`be1260bd0630261c571e3adf5aac6a6cbebd9e3a` has successful signed build34237280539.
New full Gate A34242157263 has resolved that build and entered its clean-install
step. The prior Gate A34240734122 was externally canceled before producing a
verdict; it is not acceptance evidence. The new kickoff truth is `PENDING`.

Installer signature is Valid, signer Scott Converse, ProductVersion beta.5;
app-pack manifest binds the exact clean candidate. Four existing LPM samples
were checked against the preserved kit's historical manifest before copying.
The delivery kit contains the unchanged signed installer/packs, full station
bundle, samples, and a generated complete 20-entry SHA256 manifest.

- Installer SHA256: `5b3fec96cac6bd76cfc88fc7993f5e731d9b945d6606dd4c28f9a256c2c8b7e0`
- Manifest SHA256: `97fe8a28fcbadf92abe31d7ae747fa6ef7fe905bff5c72cc99ff9fa6bf1be43a`
- Mission: `beta5-sep8-be1260bd0630`
- Host: `DESKTOP-VBMA6O5`

Tester installation, first real-media cycle, two-hour verdict, and post-soak
filler transitions are still unproven. No LPM production cutover is requested.

## Historical support-only checkpoint

This support-only change does not dispatch a test, install software, restart a
station or create a scheduled task. The unresolved wrapper template is stored
under `soak/beta5`, outside the poller's executable `soak/autorun` directory.

The product candidate being built is
`be1260bd0630261c571e3adf5aac6a6cbebd9e3a`, build34237280539. Its build and
installation/soak evidence are not complete at this checkpoint. Do not infer
artifact verification from this support commit or fill missing facts by guesswork.

The package verifies independent manifest/installer digests, signed publisher,
clean candidate app-pack identity, and installed runtime-file hashes. It uses
normal upgrade on the dedicated tester, not uninstall/data removal. It retains
the legacy heartbeat/poller and archives only the prior soak trigger marker.
Two approved sample IDs/titles/durations are recorded; three channels are fully
scheduled before start. A new run needs actual GStreamer PIDs and transport
packets, zero restart/reload/stall counters, bounded sample gaps and two hours.

Successful signed build plus exact-source Gate A PENDING allows parallel tester
operation; public publication still requires all three Gate A lanes to PASS.
Kickoff evidence stays immutable. A completed/active mission cannot be replayed.

Verification: parent reran both PowerShell integration and strict-verdict tests;
the independent implementation/review agent also checked all 11 executable
scripts/modules with Windows PowerShell 5.1. Actual-media parsing was checked
against the shipped TSDuck schema, not only invented fixture keys. These are
support-contract checks, not tester installation or two-hour acceptance.

The older product code and manuals on this control branch are historical and
must not be merged over current product main. Product fixes use PR193; this
branch exists solely for dedicated tester execution/evidence coordination.

## Follow-up: finite-media rounding and installed filler probe

Parent review found that the helper rounded fractional durations up, while
`civiccast/schedule/ingest.py` uses `int(float(format.duration))`. The old
function returned32 for a31.75-second fixture; the product returns31. The helper
now matches the product's whole-second duration, and rejects nonfinite, invalid,
subsecond and overflowing values. Integration and strict-verdict suites pass.

The `filler-probe` subdirectory contains an additional inert post-soak test.
It requires the real three-channel PASS verdict and exact installed identity,
uses the two recorded approved assets, refuses an existing channel ID, and
creates a separate loopback test channel. It observes program/filler/program
states with unchanged GStreamer PID and real transport packets. Cleanup always
attempts stop and disable; the API has no channel-delete operation, so the
dedicated channel remains disabled. Thirteen accepted bulletin records prove
retention, not that all thirteen slides were visually observed on air.

Parent verification:15 script/module parser checks passed, all three functional
PowerShell test suites passed, and the preserved real bundled-TSDuck fixture
parsed65 packets with zero sync/transport/discontinuity counters. No filler
probe has run against a live tester at this checkpoint.
