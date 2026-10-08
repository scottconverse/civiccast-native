# beta.11 Whistle development test candidate

> October 7: owner accepted the 24-hour three-station caption soak as sufficient soak evidence for Beta 11 release. [Results and limits](beta11-dev7-24-hour-caption-soak-2026-10-07.md). Station and monitor remain running; final packaged artifact verification is separate.

**Earlier October 6 milestone: successful eight-hour dev7 three-station caption soak**, accepted by the owner. All 66 sampled channel checks passed; no supervisor restart, logged caption-audio loss, caption pauses or Whistle fallback. The station and 20-minute monitor remain running for a longer observation. See [milestone evidence and memory/storage results](beta11-dev7-eight-hour-caption-soak-2026-10-06.md); loudness and full release readiness remain unverified.

This is a local development patch on the owner's installed beta.9 station,
not a signed beta.11 installer or a release-readiness claim. The source branch
is `codex/beta11-whistle`, based on main `8c3ab70bdc802f42ee573d83b284418c620c18ae`.
Current local caption-code candidate: `1.0.0-beta.11.dev7`, installed October 6 at 09:53 MDT. The base station health endpoint still identifies its installed beta.9 product; this is a local overlay, not a complete beta.11 installation. The preceding dev6 source commit was
`e385f5b7f2d18a5ae0a2eb28e83d5dd3c3846381`.

Dev7 removes automatic live review/evidence storage and retention readiness coupling, caps live caption history at 300 seconds/512 cues and waiting audio at 12 completed chunks while protecting owned/writer inputs, bounds delivery bookkeeping, and fixes reused-descriptor cleanup. Disposable beta caption tables were reset from 1,025,532 review rows and one offline job to zero; old caption working/evidence files were removed. Recorded-media review remains available. The installed tap includes the prior station diagnostics through a reviewed merge; it is intentionally not byte-identical to the source tap. In-product help was rebuilt and its complete 635-heading contents list checked over HTTP. The 15-minute three-station comparison completed at 10:10:25: 543 calls (181/channel), mean 1.198s, P95 1.422s, zero logged discards/fallback/pauses and six passing sampled caption checks; loudness remains unverified; report at `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-beta11-bounded-live-implementation-2026-10-06.md`.
Owner decision: Whistle is primary for all three live stations; Whisper is the
backup and the selectable primary for supported NVIDIA CUDA machines.
`CIVICCAST_LIVE_CAPTION_ENGINE=whistle` selects primary plus fallback;
`whisper` selects Whisper directly. No mixed-channel override is installed.
Whisper device selection uses `CIVICCAST_WHISPER_DEVICE=auto|cuda|cpu`.
CUDA requires supported NVIDIA hardware and the installed CUDA libraries;
AMD/Intel discrete graphics do not imply Whisper GPU acceleration.

Native live captions use one persistent, serial Whistle CPU process per channel,
with at most three channels. Batch captions continue to use Whisper. Whistle
inference is serialized across the station: the native DLL's CPU pools competed
under three simultaneous calls in the installed preflight, exceeding the five-second
cadence and shedding audio. Channel persistence/publishing may still overlap.
The first candidate (`dev0`, `bf68de5c5f01342d27dd26826692e2b209965068`) failed that
capacity preflight; its two-hour acceptance observation was never started.
The second (`dev1`, `50310e2e34b9e4b46bcc2d3163eecf23d7ef2037`) began observation
at 16:32:44 MDT and was aborted after the first government emitted-caption check
failed: recognized speech expired without committed captions, with a stale worker
receipt. No completed two-hour pass is claimed for either attempt.

Whistle failures replay retained audio into a separate serial Whisper process, and the
affected channel stays on Whisper until runtime restart. A failed Whisper process
may be replaced once, with the retained window replayed once. Further failures
require a runtime restart. Input writing and response waiting share a ten-second
deadline; children start suspended, enter verified Windows memory/CPU jobs before
native loading, and die on job close. Each Whistle job has a 1 GiB memory limit;
the fallback job has 4 GiB. Each job has a 25% CPU hard cap.

Live captions publish first recognition without requiring agreement between
overlapping transcriptions. Timed overlap trimming prevents repeated audio from
being published twice. The no-committed-cue watchdog was removed; native process
failure and request timeout still trigger fallback. Batch policy is unchanged.

Needle usage telemetry is forcibly disabled with `NEEDLE_TELEMETRY=0` and
`DO_NOT_TRACK=1` before import. Startup also checks its pinned Python telemetry
implementation reports disabled. Assets are local; automatic Hugging Face
downloads are disabled. Package: `cactus-needle==3.1.0` (Apache-2.0).

Pinned assets, under the station's `packs/captions-whistle`:

| Asset | SHA-256 |
| --- | --- |
| whistle.cact | b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb |
| libneedle.dll | de2e2c39cd311fbd9971fad4736abc329ed970653674c203e149c4ef27fd1c62 |

The test patch ships the factory, Whistle adapter/child, and candidate version.
Its tap worker is derived from the **installed U69 version**, preserving the
owner's shed diagnostics and adding only isolated channel concurrency and runtime
shutdown hooks. The checkout tap worker contains those same two hooks but lacks
the installed U69 diagnostics, so it must not replace the installed file wholesale.
The installed Whisper runtime and caption models match checkout bytes and remain
in place. Package files, metadata, and model/DLL are added separately with hashes.
`installed-base.sha256`, `files.json`, and backup manifests bind the actual installed
patch bytes; this hybrid patch is not wholly built from the candidate commit.

Evidence directory on this machine:
`C:\Users\scott\Documents\Codex\2026-10-04\rea\work`.
The staging and install scripts are `stage-beta11.py` and `install-beta11.ps1`.
The successful first patch backup is `work\beta11-backup-2`; the first install
attempt restored the original files after its sanity check hit PowerShell quoting.
The serialized update backup is `work\beta11-backup-serialized`. Delivery-health
changes additionally patch `pipeline.py`, whose installed baseline matches checkout.
The existing `Install-Candidate.ps1` / `Rollback-Candidate.ps1` handle replaced
application files; added dependency/asset paths are recorded separately. Installation
stops the service before copying, verifies installed hashes/imports, and restarts
it. Installation failure restores original application files and removes additions.
For manual rollback, stop the service, run `Rollback-Candidate.ps1 -NoRestart`,
remove only the recorded `extra-added-files.json` paths under the station root,
then start the service.

Focused regressions cover exact-window fallback, channel isolation, absolute word
times, silence, invalid timestamps, missing assets, three-channel dispatch, shutdown
races, concurrent native cleanup, continued cleanup after an error, and blocked
input deadline. A real-engine smoke checks three-channel stabilization, silence,
and a suspended native child triggering bounded fallback/cleanup. Medium Whisper
**CPU** fallback missed the ten-second deadline in this smoke; CPU fallback real-time
viability is not established. CUDA smoke and installed station output must be judged
from their recorded results, rather than unit tests.

## Measured results and current acceptance run

All-three Whistle with serialization completed two hours on 2026-10-05:
12/12 three-channel caption checks and 4/4 audio checks passed, no fallback,
with one five-second education catch-up discard. All-three Whisper completed
83 minutes before the owner opened a game and the memory safeguard stopped
the service; the owner accepted that duration. Eight caption checks and three
audio checks passed before interruption.

Removing the global lock in dev5 confirmed three concurrent native calls,
but full-window calls took 8.750–9.360 seconds. Education exceeded the ten-second
deadline, switched to Whisper, and other stations later dropped queued audio.
This is distinct from the removed caption-agreement rule. Dev6 restores the lock.

The owner authorized a four-hour run of all three stations on Whistle primary
with Whisper fallback available. Status: completed 2026-10-05 22:06:38 to 2026-10-06 02:07:06 MDT (four hours 28 seconds). All 23 three-station caption/freshness/timing checks passed; no Whisper fallback, pause, restart or resource stop. Raw observer verdict FAIL: first public loudness window -17.7 LUFS, unresolved source position. Seven later three-station loudness rounds passed. Seven catch-up events discarded 85 seconds of audio (public 55, government 20, education 10); two caption file I/O errors and two education boundary-reload retries remain findings. This is sustained engine operation, not a loss-free caption pass or release acceptance. Evidence: `ops/beta10-oversight/evidence/rung-beta11-dev6-whistle-all3-4h-20261005-220637`. Use the existing read-only
output observer: freshness every 30 seconds, decoded captions/A/V continuity
every ten minutes, emitted-audio loudness every 30 minutes. Retain resource logs
and inference durations throughout. Stop on unsafe resource pressure; report
fallbacks and audio shedding separately from output delivery. A fallback does
not constitute a Whistle-only pass. No forced failure during this soak.

CPU-only primary feasibility is preferred, not a release requirement; the host
has a GPU-backed Whisper standby. No broad accuracy claim is supported by a
reviewed reference transcript. The four-hour measurements are recorded above. Signed installer, clean-machine
acceptance, publication and production cutover remain unproven here.

## October 6 overnight diagnosis — runtime left unchanged

At the 08:35 MDT log snapshot, 22,145 native requests had completed since
22:06:38; 171 catch-up events discarded 2,480 seconds of station audio,
summed across all three channels. These are transcription opportunities lost,
not a measured count of missing spoken words. The 07:00 hour alone discarded
635 seconds, while native median request time remained 1.203 seconds.

Two nonblocking live GIL profiles identify retention as the strongest measured
bottleneck: 563/632 samples (89.08%) in bulk review reconstruction in the first;
349/397 samples (87.91%) in retention overall, including 244 bulk reconstruction
samples, in the second. These are captured Python/GIL samples, not whole-host CPU
or an overnight wall-time percentage. Both tap and readiness retention callers
appear; discovery is serialized but not coalesced.

Read-only SQL counted 1,023,540 review rows, of which only 24,592 carry audio
evidence. The current bulk reader reconstructs all rows on each discovery pass.
Evidence-only lightweight selection, shared discovery and bounded live caption
history are the prioritized performance repairs, preserving retention/refusal
policy. A temporary-file reproduction separately confirms stale descriptor
cleanup can close an unrelated reused reader after sidecar replacement failure.
The installed sidecar matches the checked source. Exact historical descriptor
reuse is not proven.

Relay-log trimming is routine maintenance. Education worker output confirms
incoming-leg preroll timeout and pre-commit decoder-error mechanisms with the
current leg preserved; exact asset/event pairing needs reload-ID correlation.
Public -17.7 LUFS remains a real failed measurement with unresolved source
alignment; its original temporary captured segments are no longer present.

Full diagnosis and proposed verification order on this machine:
`C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-caption-pipeline-deep-analysis-2026-10-06.md`.
No runtime repair, restart, model load or new soak was performed for this analysis.
