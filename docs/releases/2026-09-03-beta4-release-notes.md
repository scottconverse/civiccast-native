# v1.0.0-beta.4 -- published

**Status: PUBLISHED.** `v1.0.0-beta.4` published at 2026-09-04 ~20:05Z via
`scripts/release/publish_beta_candidate.py`, target commit
`c27c6e70200406b51558ee1ef6b3a95ee4dc4426`, 8 release assets, Authenticode
`Valid`. Gate A run
[`33901203343`](https://github.com/scottconverse/civiccast-native/actions/runs/33901203343)
passed all three lanes. `docs/releases/release-truth.yaml` has been flipped
(`v1.0.0-beta.4` is now `current`, `v1.0.0-beta.3` is `superseded`).

**Publisher:** the coordinating agent, per the owner's 2026-09-02 delegation
("every green build gets tagged and published" -- see
`scripts/release/publish_beta_candidate.py`'s module docstring). **Affects:**
`docs/releases/release-truth.yaml`; every beta.3 station's upgrade path;
README / INSTALL-WINDOWS.md / `docs/tester/*` "current release" wording.

## What happened

`v1.0.0-beta.4` published as a GitHub prerelease on
[`scottconverse/civiccast-native`](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.4),
targeting source SHA `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`. Like beta.3, it is downloadable:
`setup.exe` and the five runtime `.ccpack` packs as release assets, each
under GitHub's 2 GiB/file cap, verified by a published `SHA256SUMS.txt` and
a `setup.exe.sidecar.json` sidecar.

**For Sergio/LPM (already on `v1.0.0-beta.3`): this is a download-only
upgrade.** Run `setup.exe` (with the runtime packs) over the existing
install -- no `station\` folder, no re-downloading the ~21 GB AI-model
bundle. Recordings, settings, database, and AI models already on the
machine are kept; only the beta.1 → beta.3 step ever required the full kit.
This is exactly what `INSTALL-WINDOWS.md`'s "Upgrade of an already-installed
station" section and `docs/tester/lpm-beta-test-handoff.md` already say for
"`beta.3` to `beta.4` and beyond" -- confirmed against those files before
writing this note, not assumed.

Published via `python scripts/release/publish_beta_candidate.py --kit-dir
<kit> --source-sha c27c6e70200406b51558ee1ef6b3a95ee4dc4426 --build-run-id 33854799455 --gate-a-run-id
33901203343 --tag v1.0.0-beta.4 --truth-status current`, whose
fail-closed checks all passed before any GitHub state was touched:
version identity agrees across `setup.exe` ProductVersion,
`civiccast._native_version.__version__`, and the tag (already `1.0.0-beta.4`
as of PR #150's version bump); Authenticode signature status is `Valid`;
Gate A run `33901203343` (source SHA `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`) shows `PASS` on all three
required lanes.

## Headline: the GStreamer worker's real crash cause, found and fixed since beta.3

Gate A's T4 product-engine check (`t4_engine`) starts the real GStreamer
playout engine and verifies its output with TSDuck. It has never actually
measured a passing engine: beta.3's `PASS_PRODUCT_ENGINE` grade was a false
pass from a PowerShell null-pipeline bug in `Test-TsProof` (fixed in #145,
already retracted in beta.3's own verification doc and README's "Honestly
scoped" section -- that retraction is not new information, it is repeated
here for context). Re-graded correctly, every earlier beta that shipped the
default GStreamer engine was actually streaming on the ffmpeg fallback, or
slate, without saying so.

The load-bearing bug, found and fixed this candidate:

1. **The control-plane child process never actually put the bundled
   GStreamer `bin` directory on its own `PATH`, so the worker died at
   import on every machine without a system-wide GStreamer install.**
   `build_control_plane_media_env` composes its `PATH` value over
   `os.environ` (the supervisor's stock LocalSystem `PATH`) instead of
   over the `PATH` the caller had already built with
   `station_environment_for_python` -- and because that dict is merged
   LAST into the control-plane child's environment, the
   `<runtime>\dependencies\gstreamer\bin` prepend was discarded outright
   on every station. Without it, `gi`'s girepository layer resolves
   `gstreamer-1.0-0.dll` with a bare-name Win32 `LoadLibrary` call, which
   searches `PATH` and not the per-process directory list
   `os.add_dll_directory` feeds; the lookup failed silently,
   `Gst.URIHandler`'s GType came back `G_TYPE_NONE`, and the
   `gi.overrides.Gst` import raised `TypeError: must be an interface` --
   the worker exited at import, before it could reach `PLAYING` or decode
   a single frame. This has been true since the initial commit, on every
   machine without a system-wide GStreamer install already on `PATH`
   (every customer box, every sandbox run); a dev box with GStreamer
   installed system-wide masked it completely. Fixed in #154: the
   control-plane env builder now composes on top of the caller's
   GStreamer-aware `PATH`, and the runtime bootstrap publishes its whole
   computed environment into `os.environ` so any process holding
   `CIVICCAST_GSTREAMER_RUNTIME_ROOT` can import the staged `gi` on its
   own. Proof: Gate A evidence `20260903-225553Z` on kit `9479c56` shows
   the worker start and stay alive after the fix, against the import-time
   crash recorded in evidence `20260903-195625Z` on the same kit line
   before it.

Two secondary bugs were also found and fixed this candidate -- real, but
neither could matter until the worker could import `gi` at all:

2. **A module-identity mismatch made engine dispatch miss on every program
   leg once the worker did start.** `worker.py` imported its sibling
   modules by path while `engine.py` preferred the package form; on
   native Windows both import paths succeed, so the two halves bound two
   distinct `PlaylistLeg` classes compiled from the same file, and engine
   dispatch's `isinstance` check missed on every program leg, raising
   `AttributeError` before the pipeline reached `PLAYING`. Fixed in #153.
3. **Once the worker reached `PLAYING`, on a machine with no working GPU
   video-decode path it stalled ~10s later with no bus error.** A
   hand-maintained hardware-decoder rank list missed the `d3d12` factory
   family the shipped runtime bundles, so `decodebin` autoplugged a GPU
   decoder that prerolls and then delivers no buffers on a VM/sandbox/WARP
   adapter -- the pipeline's own stall watchdog then quit and the worker
   exited non-zero, relaunching in a loop. Fixed in #154, which also
   redacts the worker's stderr tail and names the actual dead engine in
   `last_error` (it no longer always says `FFmpeg`).

A third PR, #156, landed since and fixed a separate problem discovered while
verifying the two fixes above: **the packaged `tsp.exe` shipped without the
TSDuck data files it resolves relative to its own directory on Windows**,
so even a healthy engine's TS capture would fail with errors like `file not
found: tsduck.hfbands.xml`. Without #156, T4's capture step could not
measure anything regardless of engine health.

**Resolved: Gate A's T4 check passed with a real measured packet count.**
`v1.0.0-beta.4` is the first CivicCast release whose Gate A run measured
real MPEG-TS packets from the GStreamer default engine -- not the ffmpeg
fallback, not slate. Run
[`33837269907`](https://github.com/scottconverse/civiccast-native/actions/runs/33837269907)
against kit `4b30c99`, clean lane:

```
T4_RESULT=PASS_PRODUCT_ENGINE; tsp exited 0 over 1233 analysed packets
with 0 invalid syncs / transport errors / discontinuities
```

That changed the "GStreamer engine egress: not yet proven in Gate A" line
in README.md's "Honestly scoped" section and the equivalent note in
`docs/releases/v1.0.0-beta.4-verification.md`; see those documents for the
updated wording. This does
**not** extend to the separate 120-minute engine soak (#155, T6, also on
kit `4b30c99`): the engine itself stayed live and on-air the full two
hours, but the T6 lane verdict is `FAIL`, on a relaunch-count rule, not on
liveness -- see "The 120-minute engine soak" below. No sentence in this
document says the soak "passed"; it did not.

The final beta.4 kit, `c27c6e7`, adds only the upgrade-provision fix in
#159 on top of `4b30c99` (see "Also in this candidate" below) -- it does
not touch the GStreamer engine, the TSDuck packaging, or the Gate A T4/T6
harness, so the T4/T6 results above stand for it unchanged. Its own
three-lane Gate A run
([`33901203343`](https://github.com/scottconverse/civiccast-native/actions/runs/33901203343))
passed clean install, cross-version upgrade (including the independent
`psql` schema proof), and download-only; see
`docs/releases/v1.0.0-beta.4-verification.md` for the per-lane evidence.

## The 120-minute engine soak

**2026-09-04, sandbox, lane PR #155 T6, kit `4b30c99`.** Three channels
(`public`, `education`, `government`) ran on the GStreamer default engine,
each playing three real LPM sample clips scheduled as premieres, for 120
continuous minutes -- 22 scheduling beats x 3 channels = 66 samples, every
one measured `ON_AIR` with a passing TSDuck capture (minimum 1357 packets
per 8-second capture window), worker RSS flat around 445-566 MB for the
whole run. Lane verdict as the harness wrote it:

```
T6_RESULT=FAIL reason=soak-public relaunches=8 (>3); soak-education
relaunches=6 (>3); soak-government relaunches=7 (>3) beats=22
failed_beats=0
```

**Say this plainly: the soak did not pass. The engine stayed live and
on-air for the full 2 hours; the lane failed on the relaunch-count rule,
not on liveness.** `failed_beats=0` -- nothing ever went off-air or failed
a capture. Under 120 minutes of continuous premieres, each channel
restarted 6-8 times, over T6's `>3` budget. Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`.

**Correction (2026-09-05): the original explanation for these restarts,
below, was wrong and has been retracted.** This document previously said
the restarts happened because the playout worker exits cleanly at the end
of every source plan (`civiccast/egress/source_plan.py`'s `max_segments=8`)
roughly every 10-15 minutes, and credited beta.5's #162 (seamless plan
rollover) with fixing it. That was inferred from worker pid changes across
scheduling beats, never from the worker's own logs, and it does not hold
up: this soak's `gst-worker.stderr.log` files (all three channels)
contain only

```
CTRL stall: no output for 10s — quitting for daemon restart
```

lines -- 7/9/10 occurrences across education/government/public -- with no
EOS or plan-end exit anywhere. A beta.5 retest soak (kit `e502074`,
2026-09-05) shows the identical pattern: 8/8/7 stall lines, again no
plan-end exit. The plans actually running were 28-38 minutes long while
restarts came 1-25 minutes apart, which rules out a plan-boundary cause.

Two contributing issues were found in the sandbox soaks, both dated
2026-09-05:

- **(a) Sandbox-specific output stalls.** The software-encoded channels
  see periodic output stalls in the GPU-less Windows Sandbox test
  environment while the source preparer conforms clips synchronously on
  the same box. Whether this reproduces on real station hardware (an R7
  with an iGPU, where operators have reported no such issue) is not
  established.
- **(b) A real product bug: the automation pass that handles each restart
  crashed.** Every restart's channel-automation pass then raised
  `UnicodeEncodeError: 'charmap' codec can't encode character '\ufffd' in
  position 118` -- the worker's stall message folds a `\ufffd` replacement
  character into `last_error`, and writing that value out under the
  process's `cp1252` console/client encoding failed, which skipped channel
  supervision for that channel until the next tick. Fixed in beta.5 by
  #169 (merged); #167, an earlier attempt at the same fix (ASCII-fold only,
  not the underlying state-write encoding), is closed, superseded by #169.

**#162's seamless plan rollover is a real improvement for genuine
plan-boundary transitions, but it was never exercised by either soak --
no plan boundary was ever reached -- and it is not what fixes the restarts
measured here.** Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`
(beta.4) and
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-e502074-20260905`
(beta.5 retest); see "Known issues in beta.4" below.

**Update (2026-09-05, real tester hardware): (a) and (b) above are not
what operators actually experience.** Measured on real station hardware,
the restarts operators see -- a brief on-air blip every 10-25 minutes on a
multi-channel, CPU-only station running with live captions on -- are
driven by the live caption tap, not by a sandbox artifact or the encoding
bug above. `civiccast/captions/tap_worker.py` transcribes every `ON_AIR`
channel in-process on CPU; with three channels captioning at once it
exceeds its own settled-segment backlog limit roughly every 30 seconds
(`CRITICAL civiccast.captions.tap_worker: Caption tap overload for
channel <id>: N settled segments exceeds the maximum 2 ...`) and never
backs off, driving the control-plane process to ~2.5 CPU cores and
starving the GStreamer playout workers -- each worker's own 10-second
stall watchdog then fires and exits, which the daemon relaunches. Fixed
in beta.5: #169 (the state-write `UnicodeEncodeError` above, a real bug
but not this driver). The caption-tap overload fix itself has no merged
PR yet (PR pending). **Workaround for beta.4 operators: none in the
product.** `CIVICCAST_CAPTION_TAP` is the only switch for the live
caption tap, and a native station's control-plane process hardcodes it
to `inline` unconditionally (`civiccast/native/station_runtime.py:1361`)
-- there is no per-channel or operator-console setting to turn live
captioning off on a beta.4 station.

## Known issues in beta.4

1. **Each channel's playout worker restarts periodically under continuous
   premiere scheduling, causing a short on-air blip.** Measured above as
   the T6 soak's relaunch-count `FAIL` (engine liveness itself was
   unaffected: `failed_beats=0`). This document previously attributed the
   restarts to the worker reaching the end of its source plan
   (`max_segments=8`) every 10-15 minutes and credited beta.5's #162 with
   the fix; that explanation was an unverified inference and is retracted
   -- see "The 120-minute engine soak" above for what the worker's own
   logs actually show (only stall-watchdog exits, no plan-end exit).
   Contributing issues found in the sandbox soaks, 2026-09-05: (a)
   periodic output stalls specific to the GPU-less Windows Sandbox test
   environment, not established to reproduce on real station hardware;
   and (b) a `UnicodeEncodeError` in the channel-automation pass on every
   restart, which skipped channel supervision for that channel -- a real
   product bug, fixed in beta.5 by #169 (#167, an earlier attempt, is
   closed/superseded). #162's seamless plan rollover is a genuine
   improvement for plan-boundary transitions but does not address either
   issue above.
   **What operators actually see, measured on real tester hardware
   (2026-09-05): a brief on-air blip every 10-25 minutes on a
   multi-channel, CPU-only station with live captions on**, driven by the
   live caption tap (`civiccast/captions/tap_worker.py`) transcribing
   every `ON_AIR` channel in-process on CPU. On three simultaneous
   channels it exceeds its own backlog limit every ~30 seconds
   (`CRITICAL civiccast.captions.tap_worker: Caption tap overload for
   channel <id>: N settled segments exceeds the maximum 2 ...`), never
   backs off, and drives the control-plane process to ~2.5 CPU cores,
   starving the GStreamer playout workers -- their 10-second stall
   watchdog then exits, which the daemon relaunches. Fixed in beta.5:
   #169 (the encoding crash above). The caption-tap overload fix itself
   has no merged PR yet (PR pending). **Workaround for beta.4: none in
   the product** -- `CIVICCAST_CAPTION_TAP` is hardcoded to `inline` on
   every native station (`civiccast/native/station_runtime.py:1361`),
   with no per-channel or operator-console setting to disable it.
2. **TSDuck data files now shipped beside `tsp.exe`** (#156) -- the
   packaged binary previously had its plugin DLLs but not the data files
   TSDuck resolves relative to its own directory on Windows, so TS capture
   failed even against a healthy engine. This is what makes the T4
   `PASS_PRODUCT_ENGINE` result above possible.
3. **Upgrade over a running beta.3 station fixed** (#159). Before the fix,
   the upgrade's provision step unconditionally start/stopped a PostgreSQL
   cluster the freshly started station service already owned and had
   running -- that collision with the live service's own instance of the
   same cluster failed the install and forced a crash recovery of the
   database on the next successful start. The fix migrates the cluster in
   place instead of restarting it out from under the live service.

## Also in this candidate

- **#146 -- Gate A verdict artifact names now use the build run id.** Same
  bug class the beta.3 publish record found in `publish_beta_candidate.py`
  itself, fixed here in the Gate A verdict-aggregation path.
- **#148 -- schema-status health check TTL checkpoint set at `lifespan`
  startup**, not lazily on first request.
- **#149 -- the D3 rollback restore's CLI tools now resolve the right
  server and `psql`** instead of risking a rollback that fails or targets
  the wrong instance during a failed upgrade's unwind.
- **#143 -- D3 pre-upgrade drill false-negative and flat-layout rollback
  containment fixed.**
- **#145 -- installer-path audit batch:** every BLOCKER and release-path
  MAJOR found in a dedicated audit of upgrade/install/uninstall, including
  the `Test-TsProof` null-pipeline bug behind beta.3's false
  `PASS_PRODUCT_ENGINE` grade.
- **#144 -- UI walkthrough batch 6-10:** publish retest, search fallback,
  first-setup gating, and a dev-proxy fix; Playwright was not run for this
  batch's changes in the session that produced it.
- **#150 -- release-prep version bump to `1.0.0-beta.4`** across every
  `check_release_identity.py`-bound surface, and `sandbox-lab/upgrade-baseline.json`
  repinned to the published beta.3 kit so Gate A's cross-version and
  download-only lanes upgrade from the real current release.
- **#151 -- control-plane child process INFO-level logging**, closing the
  gap where the supervisor's own uvicorn child dropped every INFO record
  (pipeline state transitions, fallback reasons, `last_error`, the
  GStreamer worker's launch command line), leaving beta.3's Gate A T4
  `FALLBACK_SLATE` finding with no diagnostic trail.
- **#152 -- doc correction: "beta.1 to beta.3 is a fresh install" read as
  "wipe the station," which is not what Gate A's cross-version lane
  proved.** Corrected across README, INSTALL-WINDOWS.md, and the tester
  handoff docs.

Full detail for every item above is in the dated `[1.0.0-beta.4]` section
of `CHANGELOG.md`.

## Evidence

- **Release:** `gh release view v1.0.0-beta.4 -R scottconverse/civiccast-native
  --json isDraft,assets,targetCommitish,tagName` -- `isDraft: false`, 8 assets,
  `targetCommitish: c27c6e70200406b51558ee1ef6b3a95ee4dc4426`, `tagName:
  v1.0.0-beta.4`.
- **Hash + signature, verified from the outside:**
  `scripts/download_windows_release_artifacts.ps1 -AssetSet NativeCandidate`
  downloaded `SHA256SUMS.txt`, `setup.exe`, and the sidecar from the live
  release and verified all three against each other. The downloaded
  `setup.exe`'s SHA-256 (`9fae1211c8cb1f7d51c59d3088e0dd1d311be32493652b61917efebc0274628f`) matches the kit's own
  installer byte-for-byte, and `Get-AuthenticodeSignature` on the
  downloaded file reports `Valid` (signer: Scott Converse).
- **Gate A:** run
  [`33901203343`](https://github.com/scottconverse/civiccast-native/actions/runs/33901203343),
  all three lanes `PASS` -- clean install, cross-version upgrade (over the
  pinned beta.3 baseline, including the independent `psql` schema proof),
  and download-only. Evidence copied to
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-beta4-final-33901203343\`
  (`gate-a-33854799455` = clean, `gate-a-dirty-33854799455` = cross-version,
  `gate-a-download-only-33854799455` = download-only; each subdirectory has
  its own `gate-a-verdict.json`). See
  `docs/releases/v1.0.0-beta.4-verification.md` for the per-lane table.
- **Test suite:** `uv run pytest tests/docs tests/policy -q` re-run for this
  publish; see the commit history on this branch for the result.

## What did NOT change

- The kit-staging directory the live soak tester reads is not touched,
  moved, or deleted by this publish.
- The ~21 GB `station\` AI-model bundle is not, and will never be, a
  GitHub release asset.
- No tag or draft release is left orphaned; if the publish does not
  succeed end to end, this document stays a draft and nothing above is
  presented as done.

## Related

- `docs/releases/release-truth.yaml` -- the authored release-state record;
  the flip (`v1.0.0-beta.4` staging → current, `v1.0.0-beta.3` current →
  superseded) has been applied.
- `docs/releases/v1.0.0-beta.4-verification.md` -- this candidate's
  verification record (Gate A run, asset/hash/signature checks).
- `README.md`, `INSTALL-WINDOWS.md`, `docs/tester/lpm-beta-test-handoff.md`,
  `docs/tester/START-HERE.md`: "current release" wording updated to point at
  `v1.0.0-beta.4`.
- `docs/releases/2026-09-03-beta3-first-downloadable-release.md` -- the
  immediately prior publish record, same pattern this document follows.
