# beta.11 Whistle development test candidate

This is a local development patch on the owner's installed beta.9 station,
not a signed beta.11 installer or a release-readiness claim. The source branch
is `codex/beta11-whistle`, based on main `8c3ab70bdc802f42ee573d83b284418c620c18ae`.
The second candidate version is `1.0.0-beta.11.dev1`.

Native live captions use one persistent, serial Whistle CPU process per channel,
with at most three channels. Batch captions continue to use Whisper. Whistle
inference is serialized across the station: the native DLL's CPU pools competed
under three simultaneous calls in the installed preflight, exceeding the five-second
cadence and shedding audio. Channel persistence/publishing may still overlap.
The first candidate (`dev0`, `bf68de5c5f01342d27dd26826692e2b209965068`) failed that
capacity preflight; its two-hour acceptance observation was never started.
Whistle
failures replay retained audio into a separate serial Whisper process, and the
affected channel stays on Whisper until runtime restart. A failed Whisper process
may be replaced once, with the retained window replayed once. Further failures
require a runtime restart. Input writing and response waiting share a ten-second
deadline; children start suspended, enter verified Windows memory/CPU jobs before
native loading, and die on job close. Each Whistle job has a 1 GiB memory limit;
the fallback job has 4 GiB. Each job has a 25% CPU hard cap.

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

The authorized acceptance run is two hours with public, government, and education
simultaneously on air. Use the existing read-only output observer, retaining decoded
caption evidence, HLS freshness, A/V timestamp continuity, loudness, station logs,
and shed/timing diagnostics. Stop on unsafe resource pressure or sustained output
failure. A controlled Whistle failure must also demonstrate installed fallback.
Report measured results and gaps; do not infer correctness from engine agreement.
There is no reviewed transcript establishing broad caption accuracy, and no longer
soak, clean-machine install, signed installer, publication, or production cutover
is authorized by this test.
