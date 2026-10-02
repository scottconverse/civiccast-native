# Beta10 live finding — retention refusal, caption overload, and one stuck channel

**Observed:** 2026-09-20, 17:18–17:28 Mountain Time  
**Candidate:** `a64907ac` (`fix(beta10): isolate startup proof and loop controlled schedules`)  
**Stage:** installed runtime was staged by the approved elevation helper with proof collection set to `off`, a 15-second proof timeout, a one-second startup-hook bound, and schedule looping enabled.

## What happened

The startup freeze did not recur. The supervisor stayed Running and the control plane continued logging after startup.

The first live start attempt did not produce three healthy channels:

- **Government** reached `ON_AIR` at 17:25:44 MT with a live PID, then the caption tap logged `3 settled segments exceeds the maximum 2` at 17:26:43 and paused captions for 120 seconds. Its `active.vtt` remained the 7-byte `WEBVTT` header.
- **Education** reached `ON_AIR` at 17:25:47 MT and hit the same overload/pause at 17:26:43. Its `active.vtt` also remained 7 bytes.
- **Public** remained `STARTING` with no PID and no fresh state transition after its 17:21:42 start preparation. Its caption runtime status still says `storage-refused` / `retention-verification-pending` from 17:14:09 MT.

The staff API reported `healthy` at the same time. That is not sufficient evidence of a functioning channel: the per-channel state and emitted VTTs contradict a station-wide healthy claim.

## Classification

This is a **blocking live-validation finding**, not a source-level conclusion yet. It prevents starting the 15-minute shakedown and rules out claiming that the beta10 implementation is proven live.

The evidence does **not** yet prove that the overload is caused by the new proof-process change or by the removed storage caps. It does prove that the existing max-two backlog gate still fires in the staged runtime and that at least one channel has not cleared its initial retention-verification state.

## Next investigation

1. Preserve the current log, runtime-status, VTT, and per-channel API state as the baseline.
2. Trace the retention-verification records and the public channel start/preparation path without changing thresholds or deleting data.
3. Measure the caption tap's per-channel backlog/settling timing and identify why two channels reached three settled segments during a fresh start.
4. Only after the cause is established, make the smallest contract-preserving fix, add a sensitive regression test, stage it, and repeat the controlled shakedown.

No rung is passed by this observation.

## New finding — first retention verification is now the blocker

The phase-timing receipt changed the diagnosis again. The caption scan itself is
not spending seconds in retention or ASR: its measured scan/gate work is below
the five-second segment cadence. Instead, the first retention verification stays
in flight for minutes. The live log records the bounded one-second wait and then
continues fail-closed at `retention-verification-pending`; no ASR or caption cue
is allowed while that verdict is pending.

The source shows why: `enforce_discovered()` calls `review_store.list()` and then
calls `get_audio_evidence()` once per returned review row. The installed station
has roughly twelve thousand processed caption records, so this is one database
round-trip per row during startup. The process is alive but idle on that I/O path;
all three channels remain at seven-byte VTTs. This is a real startup availability
defect, not a storage-cap refusal and not an ASR-capacity measurement.

The corrective change will keep the existing safety contract: until retention has
returned a real verdict, raw audio is not retained and captions remain fail-closed.
The implementation change is only to replace the per-row evidence lookup with a
single bulk read, then prove the same retention classification with focused RED /
GREEN tests and a fresh live start. No threshold, test expectation, or evidence
retention rule is being relaxed.

## Update after bulk-read staging and live process autopsy — 18:40 MT

The bulk-read change was staged into the installed runtime and measured directly
with the installed Python. It removed the per-row database round trips, but it
did **not** make first verification fast: 49,162 review rows (9,164 with
evidence) still took about 21 seconds through `_discover_candidates`, and about
21 seconds through `enforce_discovered` with file deletion disabled for the
measurement. The database itself is healthy: the ordered full-row query plans
at about 56–60 ms, with no blocking session or lock. The remaining cost is the
retention policy's file-level evidence verification and raw-chunk hashing, not
PostgreSQL.

The SYSTEM `py-spy` dump of the live service at 18:37 MT is also important. The
caption-tap and retention threads were both idle in their normal `run_forever`
waits; no proof-capture frame, database call, or retention function was on a
stack. The service had no active egress program after the restart (all three
VTTs were still the 7-byte header), so this snapshot cannot prove a healthy
airing path. It **does** rule out claiming that the process was currently hung
inside proof capture or a native database call. The earlier pending-verdict
timeline remains a startup-availability defect, but its exact completion path
is not yet proven.

### Corrected disposition

The next change must be a bounded, observable retention-verification path rather
than another unmeasured attribution. It must preserve fail-closed storage safety,
emit a duration/result receipt, and keep a slow maintenance sweep from
preventing captions from starting indefinitely. Before implementation, the
installed runtime will be restarted with a real three-channel schedule so the
new path is observed while channels are actually airing.

## Update after pending-verification change — 19:13 MT

The tested source was staged into the installed runtime with the existing
elevation helper.  The installed `tap_worker.py` SHA-256 matches the source,
and the supervisor restarted successfully with the beta10 environment intact.

The first live restart exposed a separate startup/backlog finding before a
15-minute shakedown could begin: **education hit the existing max-two gate with
four settled segments at 19:13:08 MT**, so captions paused for 120 seconds and
the sidecar remained the 7-byte `WEBVTT` header.  Public and government were
still within the backlog cap at the same observation.  The control plane stayed
alive; this is not the old one-second service freeze.

The log also records the intended pending-verification path (`first
verification ... after 1.0s`) and then the education overload.  This means the
new text-only rule cannot yet be credited with a clean live result: an
over-cap backlog was already present on that channel before it could be
processed.  The station-wide `/api/health` endpoint still returned `healthy`,
so per-channel state remains the authoritative check.

**Disposition:** blocking live-validation finding, not a release conclusion.
Before changing a threshold or gate, preserve the current backlog/session
timestamps and determine whether those four files were leftovers from the
previous session or were produced during the new channel start.  The next
bounded action is to establish a clean, controlled three-channel start without
changing the max-two policy, then repeat the 15-minute shakedown.  No rung is
passed by this observation.

## Update after the clean-start attempt — 19:46 MT

The controlled stop/start completed without deleting product data. The helper
received HTTP 202 for all three starts, and the service stayed Running, but the
three channels did not reach a usable airing state within the helper's six-minute
wait: the public API still reported `STARTING` for public, government, and
education. This is a separate live blocker from the earlier caption backlog
finding.

The process-level receipt identifies the immediate mechanism. Each channel has a
live ffmpeg source-preparation process writing a large MPEG-TS conform file before
the GStreamer worker can take the channel `ON_AIR`:

- education: `Senior Citizens Advisory Board - May 2026.mp4`, conform-cache
  preparation started 19:44:55 MT; its prepared file was about 1.64 GB when
  inspected, and its GStreamer worker had only just started;
- government: `City Council Regular Session - September 8, 2026.mp4`, a
  `segment-0001.ts.tmp` was still being written from a 13,264.6-second source;
- public: `Parks & Recreation Advisory Board - April 2026.mp4`, a
  `segment-0001.ts.tmp` was still being written from a 5,604.42-second source.

The same receipt shows that the HLS ffmpeg relays are alive, but the state remains
`STARTING` until source preparation completes. This makes the start path spend
minutes conforming multi-hour programs before a channel can air. It is not proof
of a caption defect, and it is not a reason to loosen the caption backlog gate.
It is a new, reproducible release-quality availability issue: a fresh three-channel
start cannot reach the requested 15-minute caption shakedown promptly because
source preparation is unbounded from the operator's perspective.

**Disposition:** blocking live validation. The next code step is to inspect and
bound the source-preparation/start contract (including cancellation and an honest
operator-visible failure) before another shakedown. No threshold was changed, no
test was weakened, and no rung is passed by this observation.

## Decision before the source-preparation fix — 20:05 MT

The live evidence rules out treating a multi-hour conform as a normal startup
operation. The practical choices were:

1. Leave the full scheduled item as one preparation job. This preserves the
   current plan shape, but leaves a fresh channel in `STARTING` for minutes and
   cannot support a controlled three-channel shakedown.
2. Put the channel on slate while the full item prepares in the background. This
   avoids the `STARTING` stall, but adds a second asynchronous handoff and risks
   a visible slate-to-program transition whose timing must be proven separately.
3. Bound each GStreamer schedule plan to a short, join-in-progress segment and
   let the existing rollover machinery prepare the next segment while the
   current one airs. This keeps the schedule and captions on the critical path,
   preserves the published wall-clock position, and reuses the existing
   seamless-reload contract.

I am implementing **option 3**. It is the smallest change that addresses the
measured blocker without hiding it behind slate, changing caption thresholds,
or changing the published schedule. The initial segment horizon is configurable
and defaults to 60 seconds for the GStreamer path; later rollovers use the same
bounded plan. The source plan and rollover tests will prove the cap and the
join-in-progress offsets before the installed runtime is staged again.

## Update after bounded source-preparation staging — 20:18 MT

The bounded source-preparation change was staged into the installed runtime
with a fresh backup and receipt. It worked on the part it was meant to fix:
the three channels reached `ON_AIR` at 20:16:57 (government), 20:16:57
(public), and 20:17:00 (education), instead of remaining in `STARTING` while
multi-hour conform files were built. The service stayed Running and
`/api/health` returned HTTP 200.

The first caption observation then produced a new blocking finding. At
20:18:04, before a 15-minute shakedown could begin, all three channels hit the
existing fail-closed backlog rule:

- education: 3 settled segments, maximum 2;
- government: 4 settled segments, maximum 2;
- public: 3 settled segments, maximum 2.

Each channel logged the existing 120-second caption pause, cleared its active
captions, and discarded stale audio. All three `active.vtt` files were back to
the 7-byte `WEBVTT` header. This is not evidence that the source-preparation
fix failed; it is evidence that startup caption work still arrives faster than
the unchanged tap gate can drain it on a three-channel start.

The same live log recorded phase timing immediately before the gate: three ASR
batches totaling 11.453 seconds (maximum 4.031 seconds), retention sweeps with
a 1.062-second maximum, and scan/backlog-gate work with a 2.547-second maximum.
Those measurements identify the next investigation surface, but they do not
justify changing the max-two policy or declaring a caption pass.

**Disposition:** the source-preparation blocker is resolved enough to reach
air, but three-channel caption validation remains blocked by a reproducible
startup backlog. The next action is a read-only startup timeline and queue
provenance check (including whether the initial settled files are leftovers or
newly produced), followed by the smallest contract-preserving drain fix. No
threshold is being relaxed, no test is being weakened, and no rung passes from
this run.

## Correction after restart-boundary audit — 20:23 MT

The timestamp audit narrows the claim above. The staging receipt completed at
20:17:36 MT, and the new `CivicCastSupervisor` process was created at
20:17:33 MT. The repeated `ON_AIR` lines at 20:16:57 and earlier therefore
belong to the preceding service instance. I am **not** counting those lines as
proof that the bounded source-preparation fix carried a clean restart to air.

The post-restart log shows the new caption workers starting at 20:17:57 and
20:18:02, followed by the three overloads at 20:18:04, but it does not contain
a post-restart `ON_AIR` receipt for each channel. The prior statement that the
fix had already proved a clean three-channel air transition was too strong and
is withdrawn. The fix is statically tested and staged; its clean-start runtime
effect remains unproven until a fresh, attributable per-channel `ON_AIR` set is
captured.

This does not change the caption finding: all three channels still reached the
same reproducible startup backlog gate, and all three sidecars were cleared.
The next run must capture the service/process boundary and per-channel air
receipts together, then measure whether the initial caption files are new or
leftovers. No pass is claimed.

## Clean-session shakedown after the boundary correction — 20:30 MT

The authorized stop-all/start-all-clean receipt now provides an attributable
session boundary.  All three `START` commands returned HTTP 202.  The live
log records:

- government `STARTING` at 20:27:46, then `ON_AIR` at 20:27:49;
- education `STARTING` at 20:27:09, then `ON_AIR` at 20:27:49;
- public `STARTING` at 20:26:46, a brief fallback slate while its plan
  expired, then `ON_AIR` at 20:27:58.

This is the first clean, attributable three-channel air transition after the
source-plan change.  The bounded rollover preparations that followed took
about 2.2 seconds for one segment.  The caption runtime also emitted a direct
loaded-model receipt at 20:28:00: `loaded_device=cuda`,
`loaded_compute_type=float16`, `on_cuda=True`, `num_workers=3`.

At 20:30 MT, all three `active.vtt` files were larger than the 7-byte header
(public 3,150 bytes; government 2,960; education 2,464), and each per-channel
runtime status was `within-capacity` with no new overload.  This is a positive
in-progress shakedown result, not a completed rung.  The watch remains active
until the full 15-minute interval is measured; only then can the next bounded
step be selected.

## New failure during the clean-session shakedown — 20:40 MT

The clean session stayed healthy through 20:39:17 MT: all three VTTs were
growing, each channel reported `within-capacity`, and the overload count was
zero. At 20:39:28 MT the same session hit the fail-closed backlog rule on all
three channels:

- education: 4 settled segments;
- government: 5 settled segments;
- public: 4 settled segments.

The configured maximum remained 2. The tap paused captions for 120 seconds and
cleared all three sidecars; by 20:39:47 each VTT was back to the 7-byte header
and each runtime status was `paused`. This is a real failure after roughly
12 minutes of clean three-channel captioning, not a startup-leftover event.

The timing receipt adds an important clue without proving the cause. The live
phase summary still showed only **three completed ASR batches** (maximum
1.610 seconds) while the scan loop continued and the settled backlog grew to
4–5 files. No later ASR batch completion was recorded before the overload. A
government egress worker then exited cleanly at 20:39:49 and was relaunched,
but that happened **after** the caption overload and is not its cause.

**Disposition:** the source-preparation/start fix is useful and the explicit
session reset prevented the earlier immediate overload, but the three-channel
caption path still fails within the first short shakedown. The next action is
read-only thread/queue inspection and segment-timeline reconstruction to locate
why ASR stops completing while scans continue. I will not change the max-two
threshold, weaken the pause rule, or claim a 15-minute shakedown pass from this
run.

## Live retention-thread finding — 20:55 MT

A read-only `py-spy` dump of the still-running service after the overload caught
the dedicated `civicast-caption-retention` thread actively inside
`tap_worker._run_retention_sweep -> retention.enforce_discovered ->
_discover_candidates -> _wav_duration -> wave.open`. At the same instant, the
caption tap worker itself was idle in `run_forever`, with no active ASR batch
stack. The phase ledger for this process records 293 retention dispatches in
the ten-minute window (1.062 seconds total, 1.047 seconds maximum) while only
three ASR batches completed.

This proves that retention verification is doing repeated per-WAV reads on its
own live thread while caption production is no longer making progress. It does
**not** by itself prove that retention caused the 20:39 backlog or that moving
the sweep is the fix; the dump was taken after the overload. It is therefore a
new, bounded diagnostic finding: next I am reconstructing the lock/queue and
segment timeline around the first missing ASR completion before changing code.
No threshold, pause rule, or test is being relaxed.

## Fresh clean-session throughput finding — 21:15 MT

The controlled restart plus explicit stop/start session reset produced a fresh
runtime (PID 46028) with a direct CUDA receipt: `loaded_device=cuda`,
`loaded_compute_type=float16`, `on_cuda=True`, `num_workers=3`. All three
channels reached attributable `ON_AIR` and the tap completed **65 ASR batches**
by 21:16 MT. The phase ledger reports `asr_process_batch` with a **5.000 s
maximum** and 177.981 s total, while the audio writer produces one settled
segment every 5 s.

This is a different mechanism from the old startup freeze: the scan creates a
three-worker pool and waits for the whole pool before it can scan again. A
single batch that reaches the 5 s cadence leaves no scheduling margin; the
government channel then hit the unchanged max-2 backlog gate at 21:15:04 and
paused. The measurement proves the system is operating at the edge of its
arrival rate, but it does not yet prove whether the cause is serialized GPU
work, persistence, or the per-scan executor/barrier. The next read-only check
is to correlate per-channel ASR durations with process-pool concurrency before
choosing the smallest contract-preserving change.
## Fresh live throughput and playout-recovery finding — 21:21 MT

The station is currently live after the clean-session restart: public, government,
and education each report `ON_AIR`; the three caption sidecars are 211, 288, and
231 bytes rather than the empty 7-byte sentinel; and the runtime status for each
channel is `within-capacity` with backlog 1 of max 2. The service health endpoint
still returns HTTP 200 `healthy`.

The phase ledger for PID 46028 has advanced to 142 ASR batches in its bounded
window, 431.136 seconds of ASR time, and a worst batch of 8.671 seconds. This is
materially different from the earlier 5-second edge and shows that the live run is
still operating, but it is not a clean three-channel acceptance result: the same
log window records an education GStreamer worker exit/relaunch at 21:19:43–21:20:40
(`exit_code=5`, `reload-commit-timeout`). It recovered to `ON_AIR`, so this is a
playout recovery event, not a pass.

This narrows the next diagnostic question to concurrency and recovery under load:
whether ASR calls for the three channels overlap on the loaded CUDA runtime, and
whether the per-scan executor/barrier is allowing an ordinary slow batch to push a
channel over the max-two backlog. No threshold or test has been changed from this
finding. The next action is read-only thread-stack sampling during active ASR.

## Caption scan queue implementation finding — 21:45 MT

The source-level diagnosis is now converted into a contract-preserving fix. The
live loop no longer constructs a new executor and waits on `pool.map` on every
scan. It keeps one bounded executor for the worker lifetime, submits channel
batches without waiting, and tracks each channel's in-flight batch. A second
batch for the same channel is not submitted concurrently because the live
caption worker carries stabilization state across segments; sibling channels
still run concurrently up to the resolved CUDA capacity. `run_once()` remains
synchronous by default for the external one-shot entry point and existing
callers/tests.

The backlog gate still uses the unchanged maximum of 2. It now counts only
settled files that are not owned by a live batch, so a slow ASR call is not
counted twice as both active work and queued backlog. If queued work genuinely
exceeds 2 after the active batch completes, the existing fail-closed pause,
sidecar clear, and audio discard remain unchanged. Late results are generation
checked and cannot republish captions after a session reset or overload.

The new regression holds ASR open, lands another settled file while the first
batch is still running, and verifies that the scan returns without a false
overload. Focused caption worker/retention tests are **87 passed**; ruff check
and format are clean. This is source proof only until the exact files are staged
into the installed runtime and a fresh three-channel shakedown produces live
CUDA, ON_AIR, nonempty VTT, and no overload evidence.

## Post-stage shakedown finding — 22:06 MT

The exact staged file was loaded by a fresh service process (PID 33572). The
installed `civicast\captions\tap_worker.py` SHA-256 equals the repository file
(`41DEE0E3...497616CB6`), and the process logged
`loaded_device=cuda`, `loaded_compute_type=float16`, `on_cuda=True`,
`num_workers=3`. A controlled stop/start reached `ON_AIR` on all three
channels; public, government, and education had nonempty VTTs before the
failure. The scheduler also issued seamless rollovers with media preparation
completing in 2.4–7.5 seconds, so this was not the earlier startup freeze.

The shakedown nevertheless failed its caption criterion at **22:06:23 MT**:
government reached **five settled segments** and tripped the unchanged
max-two gate; its VTT was cleared to the 7-byte sentinel and captions paused
for 120 seconds. Public and education remained caption-live at that instant.
The live phase receipt for PID 33572 had 78 ASR batches by 22:06:27, a 7.219
second maximum, and 234.780 seconds total; it also shows the scan loop
continuing (669 gate events) while ASR work completed. This means the old
per-scan `pool.map` barrier is gone, but the fix does **not** yet prove that
each channel can drain its own five-second arrival rate under this content.

A 24-sample read-only `py-spy` capture after the pause found three persistent
`civicast-caption-channel_{0,1,2}` executor threads, all idle at the sample
instants. Because the capture followed the overload and pause, it cannot prove
whether the CUDA calls overlapped during the failure. No threshold or test was
relaxed, and this is not a pass. The next bounded step is a fresh-session
throughput trace that records per-channel ASR duration and in-flight ownership
while all three channels are actively captioning, then chooses the smallest
contract-preserving change based on that evidence.

## Measurement gap before the next live trace — 22:24 MT

The existing phase ledger proves aggregate ASR cost (113 batches, 319.576 s
total, 15.453 s maximum in the latest window), but it discards the `channel`
metadata supplied by the tap. That means it cannot answer the live question
that matters: whether one channel is slow while the other two overlap normally,
or whether all three calls are serialized/contending on the loaded CUDA model.

I am adding bounded, opt-in per-channel attribution to the existing timing
collector only. It will preserve the current aggregate fields, add no audio or
text, and remain default-off. This is measurement, not a threshold change or a
caption-policy change. I will stage it with the already-tested tap worker, run
the focused tests, and then capture a fresh clean session before selecting the
next behavior change.

## Per-channel trace staged; fresh session opened — 22:34 MT

The diagnostic collector and queue worker are now installed from the exact
repository files. Source and installed SHA-256 values match for both modules:
`tap_worker.py` `41DEE0E3...497616CB6` and `phase_timing.py`
`396E675D...02048D6`. The elevation helper recorded a new, recoverable backup
at `C:\CivicCastTester\beta10-runtime-backup-phase-timing-20260920-222849`.

I then issued an explicit stop-all/start-all reset. The helper saw all three
channels reach their requested states; the new caption process is PID 25328 and
the loaded-runtime receipt again says CUDA/float16 with three workers. The
first per-channel phase summary is now available, so this run can distinguish
channel-specific ASR cost from aggregate cost. It is a diagnostic run only;
the 2/4/8-hour ladder is still not started and no pass is claimed.

## Fresh per-channel trace: slow ASR and an independent playout exit — 22:37 MT

The new clean session produced the attribution the previous ledger could not.
By 22:35:25, education had 27 ASR batches (66.736 s total, 5.156 s max),
government had 27 (63.252 s total, 6.047 s max), and public had only one
completed batch — **18.234 s** — while its five-second audio arrivals continued.
At 22:35:57 the same process had education 33 batches, government 33, and
public only five. This is direct evidence that the channels do not have equal
service time: public is falling far behind while the other two continue.

At 22:36:10 government then reached four queued settled segments and hit the
unchanged max-two fail-closed rule, clearing its VTT and pausing captions. This
is a real caption failure in the fresh session, not a startup leftover. At
22:36:38 the government GStreamer worker also exited with `exit_code=5` during a
reload-commit timeout and was relaunched. That is a separate playout failure;
it is not being folded into the caption diagnosis.

No policy threshold was changed. The next engineering action is to identify why
the public channel's first ASR call took 18.234 s and whether the loaded
three-worker CUDA model is serializing or suffering contention. The evidence
now distinguishes that question from the government reload exit.

The watch then produced the same class of failure on education at 22:37:12:
four settled segments, max-two gate, VTT cleared. By that point the per-channel
ledger showed education's maximum ASR batch had grown to **21.453 s**, while
public had a sustained **18.234 s** maximum and government remained around
6.047 s. This is not a single-channel schedule hiccup: two channels are
running materially slower than the five-second arrival cadence on the same
loaded CUDA runtime. The fresh session therefore fails the caption criterion
well before 15 minutes, and the bounded shakedown is stopped as a failed
diagnostic run rather than allowed to masquerade as soak evidence.

## Read-only packaged-runtime concurrency benchmark — 22:45 MT

Before changing the live caption path, I ran the packaged model directly against
12 preserved WAV samples. The installed runtime reported `device=cuda`,
`compute_type=float16`, `on_cuda=true`, and `num_workers=3`.

With one concurrent transcription, six rounds took about **0.7 seconds** each.
With two concurrent calls, wall time was about **1.0 second**. With three
concurrent calls, wall time was about **1.8 seconds** (the individual calls
completed in about 1.2–1.8 seconds).

This is a read-only benchmark: it did not change the service, source, settings,
thresholds, or tests. It shows that the **18.234-second public** and
**21.453-second education** service phases are not explained by the bare packaged
model being unable to handle three CUDA calls. The live phase currently wraps
`LiveCaptionWorker.process_batch`, which includes model work plus pipeline
processing, stabilization, review persistence, and audio-evidence creation.

The next diagnostic therefore splits those phases in the service path and checks
for persistence/evidence or lock contention. No pass is claimed and no policy
threshold is changed.

## Fresh phase-breakdown trace: reload cadence is a live playout failure — 23:12 MT

The four-module diagnostic was staged into a fresh service process (caption tap
PID **14440**; source and installed hashes matched). All three channels reached
ON_AIR at 23:03 MT, and the new phase ledger showed the caption work itself was
initially bounded: by 23:06:26, education had 39 runtime batches totaling
49.637 seconds (4.031-second maximum), government had 36 totaling 91.857
seconds (6.453-second maximum), and public had 39 totaling 89.683 seconds
(6.391-second maximum). Runtime decode, not stabilization or lock waiting,
accounted for nearly all of that phase. Review-store writes were normally small,
although later samples recorded occasional roughly one-second writes.

The same run exposed a separate and repeatable playout defect. With the staged
GStreamer preparation horizon at **60 seconds**, automation issued a rollover
about once per minute. At 23:06:28 the government worker exited with `exit_code=5`
while committing a reload (`reload-commit-timeout`, old-leg retirement blocked),
and its reload was discarded. At 23:07:25 education exited cleanly with
`exit_code=0` while still expected to air; at 23:09:32 public did the same.
The log then recorded repeated lost command acknowledgements, and at 23:10:24
education and government both entered FALLBACK_SLATE because their scheduled
source plans expired during preparation. The bounded watcher stopped at 23:11:44
with public ON_AIR, government FALLBACK_SLATE, and education STARTING; the
government and education VTTs had no cues. Evidence is preserved at
`work/beta10-phase-breakdown-watch-20260920-231144.json`.

This is a real failure of the diagnostic run, not a caption pass. It identifies
the one-minute reload cadence as a direct stressor on the GStreamer reload path;
it does not yet prove that the longer ASR tail is unrelated. The next
contract-preserving change is to use a long bounded preparation horizon (one
30-minute slice, still one decoder chain) so the 30-minute shakedown does not
force 30 reloads. The existing 60-second behavior will remain covered by a
focused source-plan test; no caption threshold, backlog rule, or test criterion
is relaxed.
## New finding: bounded 30-minute-horizon shakedown still emits a source-preparation timeout — 23:29 MT

The first fresh watcher after staging the 30-minute GStreamer source horizon started at **23:28:04 MT** from a clean all-channel ON_AIR baseline. At the first observation, all three channels were ON_AIR and each VTT contained fresh cues:

- public: 28 cues, 2,897 bytes
- government: 28 cues, 2,998 bytes
- education: 27 cues, 2,801 bytes

At **23:28:34 MT**, the watcher captured a new control-plane traceback:

`civicast.egress.errors.SourcePrepareError: FFmpeg source preparation timed out after 300s; the channel will use its configured fallback until the source can be prepared.`

The same observation still showed all three channels ON_AIR and growing VTTs (34 / 34 / 32 cues). That recovery does not erase the failure: a source-preparation job exceeded its five-minute bound during the watched run. The traceback is emitted by the installed runtime at `egress/preparer.py:1375`; it is not a caption-threshold result and does not justify weakening caption tests.

The evidence is `work/beta10-phase-breakdown-watch-20260920-232804.json`. The run is **failed for reliability** and is not a passed shakedown. Before another run, isolate which source-preparation job timed out and whether the job was stale from the earlier session or was triggered by the fresh start; preserve this receipt and inspect the preparer queue/timeout path before changing code.

### Context correction — 23:34 MT

The surrounding log line identifies this particular timeout as:

`civiccast.egress.preparer: Conform-cache warm failed; next airing re-warms.`

That means the failed FFmpeg job was the **background full-asset cache warm**, not the foreground source preparation that kept the currently airing channels alive. At the same observation all three channels remained ON_AIR and their VTT cue counts grew from 28/28/27 to 34/34/32. This is therefore a real long-run efficiency/reliability problem (the cache warm never finishes within the five-minute bound), but it is not the cause of the 23:28 live captions continuing or stopping. The next action is measurement of the warm job's actual asset, duration, and resource cost—not an unproved timeout increase.

## New finding: timed-out conform warms leak partial `.ts.tmp` files — 23:39 MT

The preparer traceback includes the exact warm command and source. It repeatedly tries to conform the 7,793-second Parks and Recreation recording with `-threads 1`, then times out at the five-minute bound:

`C:\ProgramData\CivicCast\data\uploads\lpmrot-07-parks\Parks_and_Recreation_Advisory_Board_-_August_2026.mp4`

The failed command writes to the temporary cache target `95f47f6c8294d5fa6057a3b668fa98a6.ts.tmp`. The live conform-cache currently contains orphaned temporary outputs from these failures, including:

- `95f47f6c8294d5fa6057a3b668fa98a6.ts.tmp` — 2,369,257,472 bytes
- `b041ec2720b399cbfec4c602a6a6c8bb.ts.tmp` — 1,675,100,160 bytes

The timeout path in `_conform_full_asset_into_cache()` removes the temporary file only for explicit cancellation; a `SourcePrepareError` from `subprocess.TimeoutExpired` is re-raised without unlinking it. This is a real disk-growth bug and is separate from the caption thresholds. I am preserving these existing files and will fix only the future-failure cleanup, with a red-first test proving a timed-out conform leaves no `.ts.tmp` behind.

## New finding: cleanup fix did not prevent the three-channel overload — 23:47 MT

After staging the timeout-cleanup patch into the installed runtime and restarting
`CivicCastSupervisor`, all three channels reached ON_AIR again at 23:30 MT. The
service remained healthy and the caption files were initially active. At
**23:46:36 MT**, however, all three caption taps emitted the same fail-closed
event: **four settled segments exceeded the maximum backlog of two**, so live
captions were paused for 120 seconds and the active captions were cleared.

This is a real three-channel caption failure. The partial-cache cleanup patch is
working as a disk-safety fix, but it does not address the caption backlog
overload. I am recording the failure before changing anything else; the next
step is to capture the per-channel phase/backlog evidence and identify whether
the overload is caused by shared-thread contention, a specific source rollover,
or another runtime path. No backlog threshold is being relaxed.

## New finding: the reproduced startup overload was stale audio plus no automatic start — 00:03 MT

The 23:46 MT service restart produced one live control-plane process (PID 23984)
and no running media writer. The tap was constructed at 23:46:29/23:46:34,
then its first retention verification was still pending at 23:46:35.793. At
23:46:36.852–.866, all three channels immediately saw **four settled segments**
and fail-closed. No channel-start hook or "discarded leftover segment" line
appeared in that startup interval. The caption tap therefore consumed settled
audio already present from the prior session; it did not overload on four newly
arrived segments from the new broadcast.

The persisted egress configurations confirm why the hook did not run: `public`,
`government`, and `education` are all `enabled=true` but `auto_start=false`.
The service restart alone therefore does not enqueue a new `start` command, and
the session-scoped cleanup in `begin_channel_session()` is intentionally called
only on a real start transition. This is a test/setup finding, not evidence that
the backlog threshold is wrong and not permission to delete raw caption audio
blindly. The safe operational sequence is to issue an explicit start for each
channel (which invokes the hook before the new writer exists), then observe the
three-channel run.

Evidence: control-plane startup log lines at 23:46:25–23:46:36, one child PID
23984 listening on port 8000, no media descendants, and read-only API config
receipts showing `auto_start=false` for all three channels. The existing settled
audio was left untouched. Next action: run the explicit three-channel start
sequence under a read-only startup trace; if the channels start cleanly and the
trace shows no inherited backlog, keep product code unchanged for this finding.

## New finding: explicit start clears the stale-start condition, but the live three-channel run still overloads one tap — 00:27 MT

The explicit start sequence was issued for all three channels under the
read-only trace. It did invoke real media workers and the caption runtime
resolved to the Blackwell GPU (`loaded_device=cuda`, `loaded_compute_type=float16`,
`on_cuda=true`, `num_workers=3`). Education and government reached real ON_AIR
with fresh caption files; their VTTs grew to 1,286 and 4,228 bytes by 00:26 MT.

That proves the previous immediate overload was not caused by the start hook
failing to run. It also does not prove a passing three-channel run. At
**00:23:04 MT**, while the explicit run was live, education again hit the
unchanged fail-closed gate: **four settled segments exceeded the maximum of
two**, pausing captions for 120 seconds and clearing its active cues. The
government channel continued producing fresh cues. Public was still in source
preparation at the end of this observation and its VTT remained the old 7-byte
sentinel, so the three-channel acceptance condition was not met.

The current evidence narrows the engineering problem: stale startup audio is a
real test/setup issue and explicit starts handle it, but shared three-channel
caption processing still creates a live backlog on at least one channel after
the workers start. I am not changing the backlog threshold. Before any code
change, I will capture per-channel arrival, settle, ASR, and publish timing for
the fresh run and identify whether the delay is shared GPU/model contention,
source preparation interference, or a synchronization/queueing defect.

## New finding: the first live overload follows cold GPU model preparation — 00:30 MT

The fresh run's timestamps identify a narrower mechanism. Education reached
ON_AIR at **00:22:24 MT** and government at **00:22:29 MT**. The caption model
did not report its loaded CUDA identity until **00:22:39 MT**. During that
roughly 10–15 second cold-load interval, audio continued arriving while the
tap could not yet submit ASR work. Education then hit four settled segments at
**00:23:04 MT** and entered the unchanged 120-second fail-closed pause. This
is consistent with cold model preparation allowing the initial backlog to form;
it is not evidence that the 2-segment safety threshold should be relaxed.

This is still a measured correlation, not a complete causal proof: the current
phase collector had already reached its 600-second window before the explicit
start, so it did not capture fresh `runtime_prepare`/`asr_process_batch`
durations for this run. The next controlled run will restart the service to
reset that bounded collector, issue the explicit starts immediately, and
capture the fresh phase timings. If the same ordering repeats, the corrective
change will be to warm/verify the caption runtime before the first channel is
allowed to air, preserving the existing backlog gate and all thresholds.

## New finding: cold-start overload is real, but the same run recovered without a threshold change — 01:18 MT

The controlled run `beta10-controlled-15m-shakedown-20260921-0135` ran for
900 seconds after a clean service restart and explicit starts for all three
channels. It is **not an acceptance pass** because the run had a real early
failure:

- education hit **4 settled segments** at 01:04:28 MT;
- public hit **5 settled segments** at 01:04:28 MT;
- government hit **7 settled segments** at 01:04:36 MT;
- each event invoked the unchanged 120-second fail-closed caption pause and
  cleared active cues;
- public also had a clean encoder exit and relaunch at 01:04:39 MT.

The run also gives useful recovery evidence. After the initial failures, all
three channels returned to and remained `ON_AIR` through the end of the
15-minute window (01:15:56 MT); each channel's VTT grew well beyond the
7-byte sentinel, with final samples of 11,247 bytes (education), 9,019 bytes
(government), and 10,988 bytes (public). No backlog threshold or caption
test was changed.

The fresh phase summary makes two performance facts concrete:

- the caption runtime resolved to **CUDA/float16 with `num_workers=3`** only
  at 01:04:20 MT, after the first channels were already on air;
- `retention_sweep_work` still recorded a **5,203 ms maximum** and
  `asr_process_batch` a **12,875 ms maximum** in the same run. The retention
  timing is now a measured cost, not a theory, but this receipt does not yet
  prove which internal retention operation consumed those 5.2 seconds.

The correct conclusion is therefore: **the cold-start/backlog failure is
reproduced; the system can recover and produce captions afterward; the
three-channel rung remains failed.** Before changing code, I will trace the
retention phases and the startup ordering. Any fix must prevent the initial
backlog without relaxing the existing safety gate.

## New finding: prewarm fixes startup ordering, but CUDA ASR throughput still misses the live cadence — 01:48 MT

The next controlled run (`beta10-controlled-15m-prewarm-20260921-0140`) loaded
the live caption runtime before channel automation and then started all three
channels explicitly. The prewarm receipt is direct: at **01:36:42 MT** the
service logged `loaded_device=cuda`, `loaded_compute_type=float16`,
`on_cuda=true`, and `num_workers=3` before the egress workers were started.
That removes cold model loading as the explanation for this run's later
failure.

The run still produced a real overload: education reached **3 settled
segments** at **01:40:40 MT** and entered the unchanged 120-second fail-closed
pause. This was not a stale-start artifact. At the same time all three
channels were ON_AIR, and all three VTTs were cue-bearing and growing. The
channels recovered and continued ON_AIR afterward; the receipt ended early at
about **01:46:37 MT** because the elevated observer job did not complete its
15-minute wrapper, so this is a bounded diagnostic run, not an acceptance
rung.

The phase data identifies the next bottleneck. With CUDA/float16 already
loaded, live `runtime_transcribe` batches reached **8,265 ms** (education),
**6,594 ms** (government), and **6,172 ms** (public), while source audio
arrives on a roughly **5-second** cadence. The backlog gate itself remained
under **906 ms**. In other words, the three-channel CUDA path can fall behind
even after prewarm; the evidence points to per-channel ASR latency/decoder
settings and shared runtime scheduling, not the storage cap, startup model
load, or a justified threshold change.

This narrows the next experiment: measure the same controlled three-channel
run with a lower live GPU decode cost (greedy `beam_size=1`) while preserving
the existing backlog limit, captions, GPU path, and all safety behavior. If
that removes the overload, the product fix is a documented live-GPU latency
setting with regression coverage; if it does not, the next investigation is
runtime batching/worker scheduling. No threshold is being relaxed and no
acceptance claim is being made from this diagnostic.
