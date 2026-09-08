# Native beta.5 playback-retirement diagnosis

Checkpoint: 2026-09-08. This is diagnosis evidence, not release acceptance.
Production source-level results below are not installed-candidate acceptance.

Superseding normal-logging proof:91000 PASSED65.97s with temporary per-element
trace removed. Engine7c69b3049cf179f41852a4b8dc8e5b14068e44a7fe6c991f61522c4b8ce6367e,
fixture1f2e937e5e1decbc2cdf6b94bfdf627982a9ad47da0299c51b485492a43ccea9.
Evidence native-reload-retirement-normal-logging-20260908a. Independent
read-only review found no blocking defect; GI-free119passed/6skipped,
daemon/exit139passed, docs68passed. Full nativeengine41507 PASSED24tests,
zero skips,139.98s. Evidence native-reload-retirement-full-suite-20260908a.
Six GI-free skips are POSIX-FIFO-only cases; Windows pipe cases ran.
No signed rebuild, installedcandidate verification or physical2hsoak yet.

Superseding22:25UTC: production reload60893 PASSED65.73s, engine
bcfb59a9d8a5a30c7f2b44f63b8b730d235a69f5df00e3d8a2dcbcc07c449c01,
fixture1f2e937e5e1decbc2cdf6b94bfdf627982a9ad47da0299c51b485492a43ccea9.
This fixture adds a real late caption command each worker/cycle to the earlier
three-worker/six-commit transport/tap/receipt/stop proof. Source remains
uncommitted; temporary detailed tracing will be removed and rerun at normal
logging before release. Evidence native-reload-retirement-production-20260908a.

Separate nonshipping caption-queue guard final regression55782 PASSED51.04s:
three rounds xthree workers, complete >=9.5s video AND audio packet spans,
TS/PCR continuity, audio-tap chunks/no partials, clean exit. Path
native-caption-flow-final-guard-20260908b. Exactbe enginee9482ac7,
wrapper3b1a6e052bf76a8205bc42e0e9169d4b22ac554fa08e19f8cfaea38f0662e51b,
newtestdc13bc2027541063790d4e67a70bf58cfb54ae714f225af9df82fec4908af6da.
Baseline33382 FAILED26.93s atstall673 before packet-span checks, path
native-caption-flow-final-baseline-20260908a. Guard29120 first attempt had
TESTmetadataKeyError (TS audio stream duration omitted) after clean worker,
notproductfailure; switched to actual per-stream packet PTS+duration spans.
Guarded later-cue native decode-back test PASSED6.44s in
native-caption-guard-cue-proof-20260908a. Production caption integration still
absent. GI-free gate6tests passed; it bounds heartbeat GAPs only, not cuebuffers.

Superseding22:12UTC, separate caption-path isolation: exact-baseline no-debug
caption queue only75087 and99466 both completed [0,0,0], paths
native-playlist-caption-queue-control-20260908a/b. Interleaved unchanged
baseline68812 failed [1,0,0], output stalled at673 buffers, path
native-playlist-caption-queue-baseline-20260908b. Same fixture67404c12.
The only graph change places nonleaky queue200buffers/10MiB/1s afterappsrc
and beforetttocea608. These caps do NOT bound serialized GAP events:
GStreamer1.28.5 gstqueue.c867-908/1291-1294 accounts only buffers, while
events always enter its FIFO. Exact gstappsrc.c serialized send_event also
returns enqueue acceptance, not downstream consumption. Failed full-flow
run13673 had logical cursor18.006s but lastappsrcGAP7.676s, consistent with
queued-but-not-forwarding events, not proof that captions covered video.

A nonshipping guard now tests one pending GAP seqnum, cleared atqueue.src
before downstream push: at most current-in-push plus one waiting heartbeat.
Prime must use the same guard and retain the existing250ms startupGAP.
First guard37610 was a DIAGNOSTIC DEFECT: [0,0,3] because its prime wrongly
reused the elapsed-time helper and could emit no GAP atclock0, timing out
preroll30s. Wrapper8bdf1d9cdb812827e1ce77518d732bbfc66f8b7890d578f53a955c49a8aaa59e;
path native-playlist-caption-guard-control-20260908a. Corrected75307 pending
in ...20260908b. No shipping caption-queue/guard change exists yet.

Superseding22:01UTC: identical combined diagnostic repeat57442 PASSED66.04s
in native-reload-queues-held-async-diagnostic-20260908b, same wrapper/engine/
fixture hashes as29622. Production implementation remains pending. The
untested queue+async-without-hold combination has no result; do not infer
every strict subset failed.

Separate exact-baseline snow/no-reload results (driver collection exit0 does
not mean workers passed):
- 96071 queue-only: [0,1,0], native-playlist-queues-snow-control-20260908a.
- 32012 latency query observation: [1,1,1], native-playlist-latency-observe-control-20260908a.
- 28245 LATENCY recalculation: [1,0,1], native-playlist-latency-recalc-control-20260908a.
- 13673 numeric full-flow trace: [1,0,0], native-playlist-full-flow-trace-control-20260908a.
  Failed channel video/inserter/mux-video ended at7.533s; mux audio9.472s,
  mux output7.467s. No failed-channel EOS; this does not localize root cause.
- 95791 encoder bitrate mode only: [0,1,1], native-playlist-bitrate-mode-control-20260908a.
- 26771 aggregator/mux disk debug: [0,0,0], native-playlist-mux-debug-control-20260908a.
- 66340 bounded in-memory aggregator/mux debug: [0,0,0], native-playlist-mux-ring-control-20260908a.
Logging-sensitive success is diagnostic, not a verified correction. No
shipping latency or encoder change follows these inconclusive experiments.

Superseding result, 21:38 UTC: combined bounded queue isolation, held
replacement through retirement, and off-main-loop commit diagnostic29622
PASSED in66.05sec. All three workers completed six commits; the native test
also checked TS continuity/PCR, ffprobe A/V, audio-tap output, settlement and
clean stop. Exact baseline engine remains e9482ac7; diagnostic wrapper SHA
4526a855e05912dd98420e94a8c5f3610c96e94fe42e348d5c80a9b888ad5a28,
testSHA4c76d9d9. Evidence native-reload-queues-held-async-diagnostic-20260908a.
Identical repeat57442 is running in the corresponding ...20260908b path.
This wrapper is NOT production-safe for concurrent reload/stop and cannot
ship. The production lifecycle and its independent review remain pending.

The corrected synchronous queue+held probe39085 failed in65.18sec at the
third switch on channel3, old-element NULL. Channels1/2 completed three
commits, not all three channels. Preserved ...queues-held-diagnostic-20260908b.
Only the combined asynchronous diagnostic above has passed the final fixture.

Superseding diagnostic matrix, 21:34 UTC (all exact-be engine, not shipping):

- Async commit only:31208 FAIL48.65sec at second switch, request-pad release
  blocked and10second output stall. Path native-reload-async-commit-diagnostic-20260908a.
- Async commit with numeric caption trace:5062 FAIL46.04sec at second switch.
  Caption data covered the queued video interval; downstream of combiner
  stopped. Path native-reload-async-caption-trace-20260908a.
- Async commit with replacement held:16684 FAIL37.21sec on first switch,
  old-element NULL blocked. Path native-reload-async-held-diagnostic-20260908a.
- Standard bounded non-leaky queues prepended to video/audio encoder paths,
  synchronous original commit:84556 FAIL37.24sec at request-pad release.
  Old-element NULL now completed. Path native-reload-selector-queues-diagnostic-20260908a.
  Wrapper SHA6817371a7f80e0a00e6528500f1bc922a324b3e9441e7d0e828254155deb560b.
- Queues plus held replacement, synchronous:44367 FAIL37.73sec due to a
  diagnostic-wrapper TypeError after old retirement completed. The wrapper
  incorrectly passed self to the static _release_hold_probes(pending).
  This is a harness defect, not evidence against that topology. Preserved
  native-reload-queues-held-diagnostic-20260908a; corrected rerun39085 is
  pending in native-reload-queues-held-diagnostic-20260908b. Corrected
  wrapper SHA5285caddea3bb8fb6413259e60368691a08f1d449c947719a1b1c27f9e0ff897.

All these runs use production-pressure function unchanged; current test-file
SHA4c76d9d9c9fc687c198e1a18d909ce0fb84ee095b0a1de4f4da973ed611be275
also contains the older small test's stage-order assertions. Watchdog and
transport-continuity acceptance were not relaxed. No successful fix yet.

Superseding diagnosis, 21:23 UTC: per-element traces locate the block at
`aconcat_program_1`, element2/38, `set_state(NULL)`. All three channels first
NULL `vconcat_program_1` successfully in0ms, then never finish audio concat.
This occurred both holding new buffers (34292,37.18sec, enginec2ba6670,
testc169ebfa, `native-reload-dispose-element-trace-20260908a`) and releasing
new buffers first (6440,36.83sec, engine0550bdd0, test4c76d9d9,
`native-reload-original-order-element-trace-20260908a`). Neither ordering is
a fix. Selector request-pad release is never reached in these traces.

An isolated exact-baseline wrapper now tests whether keeping the original
GLib caption/control loop live during the blocking commit permits progress.
`diagnostic_async_commit_worker.py` is explicitly a nonshipping experiment:
it does not establish concurrent reload/stop ownership. Its result is pending.
Separately, no-reload snow/caption/tap playback with category debug logging
(26103, `native-playlist-caption-debug-control-20260908a`) completed all three
workers cleanly with301video buffers each; overhead-sensitive success does
not erase the prior no-debug failures or prove the stress issue fixed.

Superseding result, 21:15 UTC: reorder-only attempt failed in37.62sec on
the first commit, all three workers exit5. Engine SHA256
`7d4135881bc8aabff6751f8d0272e7a9f93be6fc66f0ba8d7860f7c399df6de6`,
test SHA256 `e008e6ff570a14d9ea764a296bee5493811e3a0c6af6f5949e96a2c31d6ffc36`.
The test's final receipt assertion now uses actual worker result `applied`
and excludes bool timestamps; workload and watchdog bounds are unchanged.
Execution72124, evidence `native-reload-reorder-fixed-20260908a`: watchdog
stack at `_dispose_source_leg:2762` (`element.set_state(NULL)`), before
replacement holds were released. This ordering is not a proven fix either.
Next investigation identifies the exact blocked element and checks source-
graph teardown ordering. No playback change has been committed or pushed.

Superseding result, 21:04 UTC: the production-safe caption-thread attempt
(engine `f4845ce4bf7621efe23552ac5a9e72ee4b27793b849a2d532cfff66e0bd22706`)
failed the final native fixture after55.88sec, on the second commit. The
caption thread remained alive while disposal blocked. Its42focused unit tests
did not establish native correctness. The same final fixture (testSHA
`f717148bfba75fc897320c49ccfd428e73487907e60f70e4c5e8a5471ffe64f6`)
failed against the baseline in37.00sec and captured the unchanged15second
watchdog at baseline `_dispose_source_leg:2720`. Evidence directories:
`native-reload-caption-clock-final-baseline-20260908a` and
`native-reload-caption-clock-final-fixed-20260908a`.
The independent-clock proposal is insufficient and must not be shipped as a
proven fix. A reorder-only experiment is next; its outcome is not yet known.

## Identity and environment

- Signed baseline source: `be1260bd0630261c571e3adf5aac6a6cbebd9e3a`.
- Baseline engine SHA256:
  `e9482ac7ae1c75ea062371947202ab6057d8f711736e85dda9a1f2bee9ab861c`.
- Native Windows host: Halo. Embedded Python 3.12.10 and bundled GStreamer
  1.28.5 from `C:\Program Files\CivicCast (Native)\runtime`.
- Tests used the real Windows worker named-pipe seam and temporary media.
  The installed Halo service was not replaced or restarted.
- Native named-pipe tests required normal signed-in-user execution. A separate
  provider-sandbox pipe timeout is not counted as a product media failure.
- Workspace evidence root:
  `C:\Users\scott\Documents\Codex\2026-09-01\is-this-tool-plugin-real-https`.

## Installed failures, independently corroborated

The exact baseline passed the three installer lifecycle lanes in Gate A run
`34248734841`, but failed real media acceptance. These are different claims.

Local installed Sandbox soak `soak-be1260b-20260908-191210Z` finished FAIL:
11 cycles, 9 evaluated, 28 unplanned relaunches. Captions and default seamless
reload stayed enabled. Worker traces stopped in `_dispose_source_leg` at
`set_state(NULL)` (baseline line 2720) or `release_request_pad` (2730).

Physical tester `DESKTOP-VBMA6O5` returned immediate-cycle FAIL at
`2026-09-08T19:41:33.6769561Z`: one PID change, public timed out, education
had three transport discontinuities, government passed. No two-hour soak pass.

Read-only R5 receipt, return branch commit `626e0ca2`, observed
`2026-09-08T20:26:13.3107071Z`, confirmed installed source, signed installer,
manifest and two checked current runtime-file hashes matched the baseline.
Education logged selector/hold stages twice with no disposal/commit and the
same `_dispose_source_leg:2730` frame. Government logged three complete commits.
This receipt confirms identity and failure location, not field acceptance.

## Native controlled experiments

All worker exit lists below are channel 1, 2, 3. A diagnostic driver's exit 0
only means collection finished; worker results determine playback outcome.

| Evidence directory | Configuration | Result |
| --- | --- | --- |
| `native-reload-production-baseline-20260908b` | Exact baseline, three 720p workers, SMPTE/snow TS clips, captions and tap enabled | FAIL, 46.32 s. Channels 1/3 committed then OpenH264 error 3; channel 2 stalled before commit. |
| `native-reload-production-fixed-20260908a` | Proposed wait-for-both-EOS implementation | FAIL, 36.94 s; all three observed only one outgoing EOS and stalled. Disproven fix. |
| `native-reload-production-eos-label-20260908a` | Same proposal plus stream labels | FAIL, 37.23 s; channel 3 observed video EOS only; channels 1/2 stalled without EOS. |
| `native-playlist-no-reload-control-20260908a` | Exact baseline, same snow clips, captions on/tap on, no reload | Worker exits `[1,0,0]`; channel 1 stalled at 673 mux buffers. |
| `native-playlist-no-captions-control-20260908a` | Same clips, captions off/tap on, diagnostic only | Worker exits `[0,0,0]`, clean results. |
| `native-playlist-no-audio-tap-control-20260908a` | Same clips, captions on/tap off, diagnostic only | Worker exits `[1,1,1]`, stalls at 673 mux buffers. |
| `native-reload-ball-baseline-20260908a` | Exact baseline, SMPTE/moving-ball clips; otherwise same production-shaped rollover test | FAIL, 27.57 s; all three switched selector and released holds, then failed to dispose/commit. |
| `native-reload-ball-flush-fixed-20260908a` | Proposed upstream-only retiring-leg FLUSH_START | FAIL, 26.84 s; video flush accepted, audio flush rejected, still blocked. Disproven fix. |
| `native-reload-ball-independent-gap-20260908a` | Exact baseline plus diagnostic independent 100 ms caption GAP thread | PASS, 66.15 s; six commits per worker, stable workers, in-tree TS continuity/PCR checks, audio/video checks and clean stop. |
| `native-playlist-independent-gap-control-20260908a` | Diagnostic GAP thread, original snow clips, no reload, captions/tap on | Worker exits `[1,1,1]`, stalls at 283 buffers. Separate stress case remains unresolved. |
| `native-playlist-ball-baseline-control-20260908a` | Exact baseline, SMPTE/ball clips, no reload, captions/tap on | Worker exits `[0,0,0]`, clean results. |
| `native-playlist-caption-trace-control-20260908a` | Exact baseline, original snow clips, numeric pad probes only | Worker exits `[0,1,0]`; channel 2 stalled while the main-loop GAP producer continued. |

An initially reported 720p-to-360p fixture mismatch was retracted after
structured inspection: all four subchains in the saved `sources[0]` are 720p.
The worker reloads only `new_graph.sources[0]`. The 360p values were unused
fallback/encoder fields. They do not invalidate these experiments.

The independent-GAP diagnostic is NOT production code. It issues no caption
cue commands, and its simple stop wrapper does not prove the required
concurrent cue/GAP ordering and lifecycle contract. Its source is the workspace
`diagnostic_caption_clock_worker.py`, SHA256
`c7d660d599ff9ccd1ae9dbdaf4dca4f48dc892725a444fcd2a918199c9fa3a86`.
The test version at that run has SHA256
`f9e27fce35f5f32cad77427327bb76b37751dd8972021102266b11789ade4363`.
The test wrote per-worker payloads into a shared parent and emitted a
`reload-status.json` write-collision warning despite its PASS. Final regression
tests must use per-channel parents and assert their own settled receipts.

## Causal mechanism and limits

GStreamer 1.28.5 `gstinputselector.c` acquires `active_sinkpad_lock` for reading
in the pad chain (1130), holds it across downstream `gst_pad_push` (1269), and
releases it at 1285. Request-pad disposal needs the write lock (2091).
Thus a new active stream blocked downstream can block removal of the old pad.
The previous caption GAP timer ran on the same GLib main loop doing disposal.
The controlled independent-clock PASS supports this circular-wait explanation.

Primary source, read from the exact upstream tag through GitHub's contents API:
<https://github.com/GStreamer/gstreamer/blob/1.28.5/subprojects/gstreamer/plugins/elements/gstinputselector.c>.

OpenH264 return 3 is a memory/bitstream/VLC-overflow-class return, not proof of
invalid resolution. Its lower-level cause in the snow stress case remains
unknown. Do not describe replacing test inputs as fixing that encoder issue.

The numeric trace separately observed a snow-clip stall at pipeline time
17.984 s while the application caption position had reached 17.922 s. The
caption appsrc output pad had only delivered GAP `[7.653, 7.753]` seconds,
and the combiner caption input stopped at PTS 7.667 s. Its video input segment
had start 0.125 s/base 7.5 s, last PTS 0.258 s (running time 7.633 s); video
output stopped at running time 7.533 s. Thus the producer was still queuing
GAPs but downstream progress had stopped. This is not evidence that the
independent clock fixes that separate stress case, nor proof of a specific
upstream plugin defect yet.

## Required follow-through

1. Production-safe caption clock: serialized cue/GAP state, one thread, bounded
   stop without joining under its lock, truthful failure/cleanup behavior.
2. Red/green native regression with per-channel receipts and all features on;
   real caption commands and shutdown/error cases, not only sparse GAP traffic.
3. Full tests and independent review, aligned docs, scoped push and green merge.
4. New source-bound signed build, installer lifecycle checks, installed Sandbox
   media run, physical tester two-hour soak and operator/browser acceptance.
5. Only then release/tag the accepted candidate. The old signed baseline must
   not inherit acceptance from a modified local worker.
