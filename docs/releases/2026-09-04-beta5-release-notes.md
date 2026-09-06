# v1.0.0-beta.5 -- draft, not yet published

**Status: DRAFT.** `v1.0.0-beta.5` has not been published. This document is
prepared ahead of tonight's publish, following the
`2026-09-03-beta4-release-notes.md` pattern, so the publish itself is a
fill-in-the-placeholders-and-run operation rather than a from-scratch write.
`docs/releases/release-truth.yaml` still carries `v1.0.0-beta.4` as
`current` and `v1.0.0-beta.5` as `staging` -- neither this document nor any
other surface in this PR flips that.

**Update 2026-09-05: kit `91caebc` was NOT the beta.5 release candidate.**
Its clean-install hardware soak (soak #3, below) FAILED: every GStreamer
playout worker relaunched roughly every 30 seconds per channel. Root cause
(item 51 in "Known issues" below) was a regression introduced by #170 --
not present in beta.4 -- where a widened plan window builds far more
decoder chains than an 8-core CPU-only station can run at once. Hotfix
`fix/plan-window-decoder-blowup` merged as #174, cutting **candidate 2** at
source SHA `609273da22b968b8ed9320dfc158d67b01eb30b3` (`609273d`, build run
`33997406150`). Everything below that names `91caebc` / build
`33971258093` / Gate A `33972726431` describes **candidate 1**: Gate A
PASS x3, hardware soak FAIL (item 51).

**Update 2026-09-06: candidate 2 (`609273d`) is also NOT the beta.5 release
candidate.** Gate A run `33998901590` (started 2026-09-05T23:48Z): clean
lane `PASS`; the cross-version lane FAILED at its own phase 1 -- the
pinned beta.4 baseline installer crashed inside the sandbox before any
upgrade step ran, even though the baseline `setup.exe`'s bytes were
independently verified identical to the published `v1.0.0-beta.4` release
asset -- a harness/sandbox gap (item 58), not a product defect. A re-run,
Gate A `34004354641`, is in progress. Candidate 2's clean-install hardware
soak (soak #5, clock `2026-09-06T02:26:16Z`) confirmed both the
caption-tap fix (#172) and the plan-window fix (item 51) hold on real
hardware for the first 30 minutes (control plane ~20% CPU, caption tap
backed off; workers ~550 MB RSS / 178 threads instead of 3.5 GB / 1,238),
but from roughly 02:58Z every worker began relaunching about every 30
seconds again, and `government` tripped the 5-crash guard at 03:01Z.
**Verdict: FAIL** (relaunches: one per channel by 02:56Z, then about every
30 s). Root cause (item 60, tester-proven 2026-09-06,
`tester-soak5-609273d-20260906`): when the planner extends a running plan,
(a) the reload's prepare step writes the new plan's segment files onto the
*same paths the live worker is still playing*
(`<work>/<channel>/prepared/segment-NNNN.ts`, keyed by channel only,
written in place, not atomically -- `civiccast/egress/preparer.py:342`/
`378`, `:246-268`, `:465-476`), starving playback and tripping the same
10-second stall watchdog, which relaunches the worker; and (b) the
in-place reload command itself sometimes never reaches the worker at
all, and the daemon returns without logging that failure
(`civiccast/egress/daemon.py:1617-1618`), falling into the drain path
(`TRANSITIONING`) with the worker's own logs showing no reload ever
arrived. The `vconcat_program`/`aconcat_program` element-name collision is
a real defect in the same code path but was not the trigger measured on
hardware. Present in beta.4 as well; it simply fired far less often there.
Fix `fix/gst-reload-concat-collision` (per-plan prepared directories with
atomic writes and cleanup, a logged failure instead of a silent one,
unique element names, an honest reload acknowledgement, and the seamless
in-place rollover disabled by default for the GStreamer engine in beta.5,
`CIVICCAST_EGRESS_SEAMLESS_RELOAD=1` re-enables it) will cut **candidate
3**. Candidate 3's identity is pending: source SHA
`<BETA5_FINAL_SHA>`, build run `<BETA5_FINAL_BUILD_RUN>`, Gate A run
`<GATE_A_FINAL_RUN_ID>`, hardware soak clock `<SOAK6_START_UTC>`, verdict
`<SOAK6_VERDICT>`, relaunches `<SOAK6_RELAUNCHES>`.

**Publisher (once run):** the coordinating agent, per the owner's
2026-09-02 delegation ("every green build gets tagged and published" --
see `scripts/release/publish_beta_candidate.py`'s module docstring).
**Will affect:** `docs/releases/release-truth.yaml`; every beta.4 station's
upgrade path; README / INSTALL-WINDOWS.md / `docs/index.html` /
`docs/tester/*` "current release" wording -- see "Surfaces to flip at
publish time" below for the exact list, prepared but not applied here.

## What will happen

**Neither candidate 1 (`91caebc`, item 51) nor candidate 2 (`609273d`, item
60) passed its hardware soak, and neither will be published; the paragraph
below records what each candidate's publish command and Gate A run were, as
history, not as a live plan.** `v1.0.0-beta.5`
will publish as a GitHub prerelease on
[`scottconverse/civiccast-native`](https://github.com/scottconverse/civiccast-native/releases),
targeting source SHA `<BETA5_FINAL_SHA>` once candidate 3 (cut after
`fix/gst-reload-concat-collision` merges) passes its own Gate A and
hardware soak. Like beta.3/beta.4, it will be
downloadable: `setup.exe` and the runtime `.ccpack` packs as release assets,
verified by a published `SHA256SUMS.txt` and a `setup.exe.sidecar.json`
sidecar.

**For Sergio/LPM (already on `v1.0.0-beta.4`): this will be a download-only
upgrade**, exactly as beta.3 -> beta.4 was. Run `setup.exe` (with the
runtime packs) over the existing install -- no `station\` folder, no
re-downloading the ~21 GB AI-model bundle. Recordings, settings, database,
and AI models already on the machine are kept.

Candidate 1 would have published via `python scripts/release/publish_beta_candidate.py
--kit-dir <kit> --source-sha 91caebccc6a6decef476fea5cd785a9ff19abfe6 --build-run-id 33971258093
--gate-a-run-id 33972726431 --tag v1.0.0-beta.5 --truth-status current`
(never run -- the hardware soak failed first). Candidate 2's equivalent
command likewise never ran (its own hardware soak, soak #5, also failed):
`--source-sha 609273da22b968b8ed9320dfc158d67b01eb30b3 --build-run-id
33997406150 --gate-a-run-id 33998901590`. Candidate 3's command, once its
own Gate A run and hardware soak pass, uses `<BETA5_FINAL_SHA>`,
`<BETA5_FINAL_BUILD_RUN>`, and `<GATE_A_FINAL_RUN_ID>`. The publisher's
fail-closed checks must all pass before any GitHub state is touched:
version identity agreeing across `setup.exe` ProductVersion,
`civiccast._native_version.__version__`, and the tag (already
`1.0.0-beta.5` as of PR #164's version bump); Authenticode signature status
`Valid`; Gate A run `<GATE_A_FINAL_RUN_ID>` showing `PASS` on all three required
lanes.

## Headline: the real cause of the playout-worker restarts, found on real station hardware (#172, merged)

Two earlier rounds of this document attributed the beta.4 soak's
relaunch-count `FAIL` first to plan-boundary worker exits (retracted, see
`docs/releases/2026-09-03-beta4-release-notes.md` and
`docs/releases/v1.0.0-beta.4-verification.md`), then to a mix of a
sandbox-only output stall and a `UnicodeEncodeError` in the automation
pass. **That second explanation was also incomplete.** A soak on the
tester's own real hardware (`DESKTOP-VBMA6O5`, 2026-09-05) reproduced the
same restarts with no sandbox involved, which ruled out "sandbox-specific
stall" as the driver and pointed at the one thing common to every
environment: the live caption tap.

**Root cause: the caption tap transcribes every `ON_AIR` channel's audio
in-process on CPU, and with three channels running it overloads.**
`civiccast/captions/tap_worker.py` runs speech-to-text for every on-air
channel in the same process, on the CPU, with no backoff. On the tester's
three-channel real-hardware soak (`DESKTOP-VBMA6O5`, kit `e502074`,
mission `soak8-e1acfe6`, planned 2 hours, actually run 2.5 hours,
2026-09-05T09:06:14Z -- 11:36:14Z), the control-plane log recorded this
line roughly every 30 seconds, on all three channels, throughout the run:

```
CRITICAL civiccast.captions.tap_worker: Caption tap overload for channel <id>: N settled segments exceeds the maximum 2; active captions were cleared and stale audio was moved to overload evidence
```

It never backs off. Sustained, it drives the control-plane process to
roughly 2.8 CPU cores (1.4-1.9 GB resident) throughout the run, which
starves the GStreamer playout workers of CPU time. Each starved worker
trips its own stall watchdog (`CTRL stall: no output for 10s`) and exits,
and the daemon relaunches it -- on the tester's real-hardware soak, public
relaunched twice, education once, government three times (6 relaunches
total); at the final probe, public and government were in
`FALLBACK_SLATE` after a relaunch and education was still `ON_AIR`; the
sandbox soaks saw 5-10 relaunches per channel in 2 hours. TSDuck (`tsp`)
packet-level checks passed on every 30-minute probe cycle from 09:36Z
onward (the two earlier probe failures, at 08:28Z and 09:06Z, predate
`ON_AIR` -- the channels had not yet been created -- and are excluded),
and the upgrade path passes independently on real hardware -- the
restarts are a CPU-contention symptom of the caption tap, not an engine
or upgrade defect.

**Fixed in this candidate by #172 (merged):** overload backoff/pause in
the caption tap so it stops driving unbounded CPU load once it is behind,
a bounded ASR workload, and higher process priority for the playout
workers so they are not the first thing starved when the box is under
load.

**Contributing, also fixed: a state-write crash on non-cp1252 characters
(PR #169, merged).** Independently of the CPU-contention root cause, every
restart's channel-automation pass on the earlier soaks also raised
`UnicodeEncodeError: 'charmap' codec can't encode character '\ufffd' in
position 118` -- the worker's stall message folds a `\ufffd` replacement
character into `last_error`, and writing that value out under the
process's `cp1252` client encoding failed, which aborted that channel's
automation pass until the next tick. Seen on the tester and on both
sandbox soaks. #169 fixed this by folding all persisted free text for
non-cp1252 clusters, and creates new clusters as UTF-8 going forward.

**Planner defects found on the way (PR #170, open, not yet in this
candidate):** while instrumenting the rollover and health-poll paths to
chase this bug, three more defects turned up in the schedule planner --
schedule slot duration was ignored entirely (a 30-second slot of long
media could air for hours), plans were sized by item count (8 items)
rather than duration so a run of short items produced 4-minute plans, and
the health poll re-read a worker's entire growing stderr log every 2
seconds instead of tailing it. None of these were the restart's root
cause; #170 is tracked separately.

**The seamless plan rollover (PR #162, merged) is a real improvement for
genuine plan-boundary transitions, but it did not fire in any soak (0
rollovers in the tester's 2-hour log) and did not cause, and does not fix,
the restarts.** Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`
(beta.4 sandbox), `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-e502074-20260905`
(beta.5 sandbox retest), and the tester's real-hardware soak on
`DESKTOP-VBMA6O5` (2026-09-05).

**Known limit, carried forward in beta.5:** captions are best-effort. When
the box cannot keep up, they pause and playout wins -- a three-channel,
CPU-only station will pause captions under load rather than risk playout.

**What beta.5 is, in full:** the caption-tap overload fix (#172, merged,
above) is the headline; also in this candidate are the state-write encoding
fix (#169, merged), the four Gate A harness fixes below (#158/#160/#161/#163),
and the release-prep identity bump (#164). The seamless plan rollover (#162)
shipped in an earlier round of this candidate and is described below for
completeness; the planner defects (#170) are tracked separately and are not
part of this candidate.

## Also in this candidate: seamless source-plan rollover for genuine plan-boundary transitions (#162)

Independent of the diagnosis above, the playout worker genuinely does
exit cleanly at the end of every source plan
(`civiccast/egress/source_plan.py`'s `max_segments=8` bounds how many
segments one worker process plans before it exits by design), which can
happen under continuous back-to-back premieres, and each exit-and-restart
is a short on-air blip. `v1.0.0-beta.5` fixes that at the root:

- New `ChannelAutomationService._check_plan_rollover`
  (`civiccast/egress/automation.py`) runs every automation tick and tracks
  the projected wall-clock end of the plan a channel is actively airing.
- Within 30 seconds of that projected end, it re-fetches the schedule
  through the same `source_plan_provider` already in use. Because
  `build_source_plan_from_schedule` always resumes the currently-airing
  item and windows forward from "now," a later fetch naturally reaches
  further into the schedule once more content has been published -- that
  recompute *is* the rollover.
- If the fresh plan extends further than the one already loaded, the
  channel enqueues the same `"reload"` command the existing slate-to-program
  transition already uses. The engine switches both video and audio to the
  new leg at the outgoing clip's end: EOS is dropped on the outgoing
  selector pads, running-time is rebased, and the new leg is held prerolled
  so there is nothing left to wait on at the switch point. The channel's
  `state` stays `ON_AIR` the whole time; only a `TRANSITIONING` proof event
  is recorded, matching the slate-to-program transition's own behavior.
- If nothing further is published yet, this is a deliberate no-op and the
  plan is left to reach its natural end -- closing that smaller residual
  gap is a separate follow-on, not part of this fix.
- The immediate-switch path (used when a channel is not mid-plan, e.g. the
  slate-to-program transition itself) is unchanged.

**Proven on HALO with the bundled GStreamer:** the rollover engine test
suite passed 5/5, TSDuck measured 0 discontinuities and 0 PCR/PTS leaps
across the monitored rollovers. **Known residual:** if the next leg is not
ready before the outgoing clip ends, the output freezes until it is ready
or the existing 10-second stall watchdog restarts the channel -- see "Known
issues in beta.5" below.

**T6 relaunch-count retest, real-hardware soak on tester `DESKTOP-VBMA6O5`,
kit `e502074` (mission `soak8-e1acfe6`, planned 2 hours, actually run 2.5
hours):**

```
T6_RESULT=FAIL beats=83 failed_beats=0
relaunches_public=2
relaunches_education=1
relaunches_government=3
```

`beats` counts the harness's 83 recorded heartbeats over the run;
`failed_beats=0` because TSDuck (`tsp`) passed on every 30-minute probe
cycle from 09:36Z onward -- the only two probe failures, at 08:28Z and
09:06Z, predate `ON_AIR` (the channels had not yet been created) and are
excluded. PASS criterion is `relaunches=0` per channel; this run did not
meet it. Kit `e502074` was `main` at soak time -- it carries #169's
state-write encoding fix but not the caption-tap overload fix (#172,
merged), so this retest measures the caption-tap-driven relaunches
described above, not a regression in the rollover fix itself (0 rollovers
fired in this run). Evidence: tester branch
`tester/soak8-e1acfe6-DESKTOP-VBMA6O5` (`soak/final-verdict.json`,
`soak/SOAK-REPORT-DESKTOP-VBMA6O5-20260905T113614Z.md`,
`soak/DIAG-9i-20260905T103612Z.md`); local copy
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\tester-soak8-e1acfe6-20260905\`.

**Second real-hardware soak, first attempt -- ARCHIVED, not evidence about
#172.** Soak clock started `2026-09-05T18:40:36Z` on tester
`DESKTOP-VBMA6O5`: installing kit `91caebc` (the final beta.5 candidate,
carrying #172) as an install-over the still-live `e502074` station from
the soak above. Because both kits declared the same `1.0.0-beta.5`
version string, known issue 6 above applied: the installer's pack staging
treated the app payload as already satisfied and never replaced it, so
this run kept executing the *old*, pre-#172 caption tap the whole time
-- the installer exited `0` and `/health` came back healthy regardless,
because from the installer's perspective nothing needed to change. The
control plane ran at roughly 4 CPU cores with the same `CRITICAL` caption
overload lines described above, and the station relaunched channels twice
in the first 35 minutes -- the exact behavior #172 was written to fix,
reproduced because the fix's own code never actually made it onto the
box. **This run is archived and is not read as evidence for or against
#172** -- it measured the previous candidate under a new label, not the
new one.

**Second real-hardware soak, valid retest: clean install of kit
`91caebc`.** To get a real measurement, the tester uninstalled the
station completely (including a data wipe) and ran a fresh `/S` install
of kit `91caebc` from scratch -- this sidesteps known issue 6 entirely,
since there is no prior install for the version-string comparison to
match against. The installed `captions/tap_worker.py` hashed to sha256
`0a9610bb...`, equal to the kit's app-payload pack, and `tap_backoff.py`
was present. First admin was created, and the same four approved LPM
clips were uploaded across three GStreamer channels (`public`,
`education`, `government`); ffprobe is not present on this box, so the
schedule setup fell back to its 30-second default clip duration (the
playout engine trims each clip to fit at air), committing 272
thirty-second schedule items per channel. All three channels were
ON_AIR with content when the clock started. Soak clock started
`2026-09-05T20:16:29Z` on tester `DESKTOP-VBMA6O5`.

**Verdict: FAIL.** The caption-tap fix itself worked as designed: the
control plane ran at roughly 30% CPU, the caption tap sat in state
`paused` with backoff engaged, and there were zero `CRITICAL` overload
lines in the run. **But every GStreamer playout worker exited with `CTRL
stall: no output for 10s` and was relaunched -- one per channel in the
first 30 minutes, then roughly every 30 seconds -- the rule is zero
relaunches.** One worker was observed at 3.5 GB RSS and 1,238 threads.
This is a different failure than the caption-tap starvation soak #3 was
designed to retest -- see "Root cause of soak #3" immediately below.

## Root cause of soak #3: the #170 plan-window regression drives a decoder pileup (item 51)

Soak #3 proved the caption-tap fix (#172) works, and disproved the
hypothesis that fixing the caption tap alone would make the hardware soak
pass. The relaunches it measured are a **separate, newly introduced
defect, not present in beta.4** -- a regression from #170
("honour the schedule slot in source plans; size the plan window by
duration"), which merged into this candidate after beta.4 shipped.

**Mechanism:** #170 widened the playout plan window to hold 30 minutes of
schedule (`PLAN_MIN_SECONDS=1800`, `PLAN_MAX_SEGMENTS=120` in
`civiccast/egress/source_plan.py`). Before #170, a plan held at most 8
segments (`max_segments=8`). With the soak's 30-second schedule items, a
30-minute plan now holds 60 segments. `civiccast/egress/gst/bridge.py`
builds one H.264 decoder chain per segment in the plan and starts them all
in a single pipeline (`engine.py`'s `_build_playlist`) -- so three channels
x 60 decoders each means 180 concurrently-running decoder chains on an
8-core, CPU-only, GPU-less station. That station cannot produce output
from any of them inside the existing 10-second stall watchdog, so every
worker trips it and gets relaunched, over and over.

**Hotfix, open, not yet merged:** `fix/plan-window-decoder-blowup` --
caps plans at 8 segments regardless of duration, ties the replan-trigger
floor to the plan's actual segment count rather than a fixed time window,
and hard-caps how many decoder chains the engine will build at once. Once
merged, `v1.0.0-beta.5` will be cut from `main` at the new head, built,
and put through a fresh Gate A run and a fresh clean-install hardware
soak -- **candidate 2**, not a re-test of `91caebc`.

## Fourth real-hardware soak: real clip durations, to isolate the item-boundary question

**Purpose:** show whether the stall soak #3 measured is driven by item
(schedule-segment) boundaries specifically, or is purely a function of
decoder count regardless of how the segments are shaped. Same build
`91caebc` as soak #3 (pre-hotfix); same tester `DESKTOP-VBMA6O5`. The four
approved LPM clips were rescheduled with their real durations -- 67s, 67s,
667s, and 2365s -- instead of the 30-second default soak #3 used, which
sharply cuts the number of schedule items (and therefore decoder chains)
a 30-minute plan window holds without touching #170's plan-window code at
all. Soak clock started `2026-09-05T21:08:51Z` on kit `91caebc`.

**Result: FAIL (relaunches).** The rescheduled long items collided (HTTP
409) with the 30-second items still queued, which stayed in the plan
until roughly `22:20Z` -- so the first ~70 minutes of the run stayed on
the 30-second items and kept relaunching. Once the plan window actually
held the long clips, each worker's RSS fell from roughly 3.5 GB to
roughly 0.35 GB -- the item-51 decoder-pileup mechanism seen live,
confirming rather than disproving the root cause rather than isolating a
separate item-boundary effect. The long-item phase then hit a schedule
gap (`No valid source plan is available`, falling back to slate); one
channel tripped the 5-crash guard; the planner then issued a rollover for
a plan it believed had ended 1,208 seconds earlier; and all three
channels sat in `TRANSITIONING` from `22:55Z` onward. The streams
themselves stayed clean throughout (TSDuck probes kept passing; no
channel went off air) -- this is the product's designed graceful drain,
not a hang: when a live content reload cannot be applied seamlessly, the
running program is allowed to play to its natural end before the new
plan starts. The defects are operator- and automation-facing, not
streaming ones -- logged as items 54/55 in "Known issues" below.

## Fifth real-hardware soak: candidate 2 (`609273d`), clean install

Clean-install hardware soak for candidate 2 (cut after
`fix/plan-window-decoder-blowup` merged as #174), tester `DESKTOP-VBMA6O5`,
fresh `/S` install from scratch. Soak clock started
`2026-09-06T02:26:16Z`.

**First 30 minutes: both carried-forward fixes held on real hardware.** The
caption-tap fix (#172) worked as designed (control plane ~20% CPU, caption
tap backed off, zero `CRITICAL` overload lines), and the plan-window fix
(item 51) also worked as designed (workers at roughly 550 MB RSS / 178
threads, against the prior candidate's 3.5 GB / 1,238 threads).

**From roughly 02:58Z, every worker began relaunching about every 30
seconds again**, and `government` tripped the 5-crash guard at 03:01Z.
**Verdict: FAIL** (one relaunch per channel by 02:56Z, then about every 30
seconds). This is a different failure than item 51 -- see "Root cause of
soak #5" immediately below.

## Root cause of soak #5: in-place plan rollover can never actually commit (item 60)

**Tester-proven 2026-09-06** (`tester-soak5-609273d-20260906`, in
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\`). When the planner extends a
running plan with a new plan, two defects fire in the same reload path:

**(a) The reload's prepare step clobbers the segment files the live
worker is still reading.** `SourcePreparer.prepare` derives its output
directory from the channel id alone --
`prepared_dir = self._work_dir / config.channel_id / "prepared"`
(`civiccast/egress/preparer.py:342`) -- and writes each new plan's
segments onto the same `segment-NNNN.ts` paths
(`civiccast/egress/preparer.py:378`) that the *currently airing* plan's
GStreamer pipeline still has open for read, because the directory is
keyed by channel, not by plan. Both segment-write paths write straight to
that final path with no temp-file-plus-rename step --
`civiccast/egress/preparer.py:246-268` (cache-hit trim-out via `ffmpeg
... -c copy <output_path>`) and `civiccast/egress/preparer.py:465-476`
(cache-miss conform via `build_conform_source_args(... output_path=
output_path)`) both hand `output_path` to `ffmpeg` directly. (Contrast
`_conform_full_asset_into_cache`, which writes to a `.tmp` file and
`Path.replace()`s it into place -- that write *is* atomic; the per-plan
prepared segments are not.) The live worker reads a half-overwritten or
truncated file mid-playback, playback starves, and the existing
10-second stall watchdog fires and relaunches the worker -- the same
`CTRL stall: no output for 10s` signature as item 51, from a different
mechanism.

**(b) The in-place reload command can fail to reach the worker at all,
silently.** `EgressDaemon`'s reload path calls
`self._encoder_strategy.reload_content(...)`; when it returns falsy,
`civiccast/egress/daemon.py:1617-1618` is `if not applied: return False`
-- no log line, no proof event, nothing recorded. The caller (channel
automation) falls through into the ordinary drain path and the channel
sits in `TRANSITIONING` believing a graceful hand-off is in progress,
while the worker's own logs show no reload ever arrived. This is the same
silent-failure shape as item 54/55's drain-visibility gap, but on the
control-plane side rather than the worker side.

**The `vconcat_program`/`aconcat_program` element-name collision
(`civiccast/egress/gst/engine.py:361-363`,
`civiccast/egress/gst/bridge.py:639`) is a real defect in this same
reload path** -- GStreamer does refuse to add a second element under a
name already present in the pipeline -- **but tester evidence shows it
was not the trigger on hardware**: the segment-clobber (a) and the
silent reload failure (b) above are what soak #5 actually measured.
**No in-place rollover has ever committed on real hardware.** Present in
beta.4 as well -- none of this is new code in this candidate, but beta.4
fired the in-place rollover path far less often because #162 (the
feature that attempts an in-place rollover at all) postdates beta.4.

**Fix, `fix/gst-reload-concat-collision` (candidate 3):** give each plan
its own prepared directory (not just each channel) with atomic writes and
cleanup of superseded plans' directories, so a reload's prepare step can
never touch a file the live worker still has open; log and record a
failed reload instead of silently falling through to drain; fail loud
when GStreamer refuses to add a duplicately-named element instead of
silently timing out; give each rollover's new concat elements unique
names; make the worker's reload acknowledgement honest; and, until this
is proven stable on hardware, **disable the seamless in-place rollover by
default for the GStreamer engine in beta.5**
(`CIVICCAST_EGRESS_SEAMLESS_RELOAD=1` re-enables it). With it disabled, a
plan's natural end becomes one ordinary encoder restart instead of an
attempted in-place splice -- rare with real 10-40 minute schedule items,
but roughly every 4 minutes with 30-second items.

## Also in this candidate: the Gate A schema proof now actually executes

Four sequential harness-only bugs, each exposed by fixing the one before it,
all on the cross-version-upgrade lane's independent post-upgrade `psql`
schema proof:

- **#158 -- `tsp.exe`'s exit code came back `null` on PowerShell 5.1**
  (`Start-Process -PassThru` + `Wait-Process -Id` needs the process handle
  touched first), which judged a fail-exit- against Gate A run
  `33826665417`'s otherwise fully healthy TSDuck capture (1229 packets, 0
  invalid syncs, 0 transport errors). Fixed by caching `$proc.Handle`.
- **#160 -- the schema proof read `DatabaseUrl` from the wrong registry
  key** (`HKLM\SOFTWARE\CivicCast` instead of the installer's actual
  `HKLM\Software\CivicCast\Native`), judging every reaching upgrade run
  `<no-database-url>` (first seen: Gate A run `33857982657`, kit `c27c6e7`,
  install/activation/health all independently passing). Fixed; contract
  test pins the key against the NSIS source.
- **#161 -- the proof's SQL argument to `psql` was not quoted**
  (`Start-Process -ArgumentList` splits unquoted arguments), so `psql`
  warned about an ignored extra argument, ran a bare `SELECT`, and exited 0
  with no rows -- judged `<no-alembic-version-row>` (Gate A run
  `33870994702`, kit `c27c6e7`). Fixed by quoting the SQL and treating an
  exit-0-with-warnings result as a failed proof.
- **#163 -- the proof's single `UNION ALL` query failed outright when only
  one of `civiccast.alembic_version`/`public.alembic_version` exists** (the
  product keeps its version table in the `civiccast` schema only) -- Gate A
  run `33885550628` (kit `c27c6e7`) recorded `<psql-failed>` with `relation
  "public.alembic_version" does not exist` while
  install/activation/health/DB-at-head all independently passed. Fixed by
  querying each namespace in its own statement and falling through cleanly
  on "does not exist."

Each bug was found only after the one before it was fixed. Tonight's Gate A
run is the first whose cross-version-upgrade lane can reach a real,
independent `psql`-read verdict on the post-upgrade schema instead of
failing inside the harness before producing one. This is a harness-only
class of fix -- it does not touch the product's own upgrade/migration code
path, only the independent proof that checks it from the outside.

## Known issues in beta.5

1. **Seamless rollover has a residual freeze case (#162).** If the next leg
   is not ready before the outgoing clip ends, the output freezes until it
   becomes ready or the existing 10-second stall watchdog restarts the
   channel. The immediate-switch (non-rollover) path is unchanged. Not yet
   scheduled; tracked as a follow-on to #162.
2. **Gate A harness self-test lane still to add (batch 27).** The four
   independent-proof bugs fixed above (#158, #160, #161, #163) were each
   found by a real Gate A run failing in a new way, one at a time, rather
   than by a test exercising the harness's own proof logic in isolation. A
   self-test lane for the harness is queued as batch 27 and is not part of
   this candidate.
3. **Captions are best-effort and pause under load (#172, merged).** The
   caption tap's overload backoff means a box that cannot keep up pauses
   captions rather than risk playout -- a three-channel, CPU-only station
   will see captions pause under sustained load. Playout always wins over
   captioning.
4. **Planner defects tracked separately (#170, open).** Found while
   diagnosing the restarts above: schedule slot duration was ignored (a
   30-second slot of long media could air for hours), plans were sized by
   item count rather than duration, and the health poll re-read a worker's
   entire growing stderr log every 2 seconds. Not part of this candidate.
5. **A channel an operator started by hand does not come back on its own
   after an upgrade install or any service restart -- only a channel with
   "Start automatically" turned on does (beta.4 and beta.5).** On every
   restart, channel automation re-starts a dark channel only when its
   config has `auto_start=true`; a channel the operator switched on by
   hand without that setting stays off the air until the operator opens it
   and presses Start again (`civiccast/egress/automation.py:478-493`). A
   channel's on-air/off-air choice and its `auto_start` setting are both
   ordinary config/state rows (`egress_configs`, `egress_states`) and
   survive an upgrade install untouched -- nothing is lost, the automation
   loop simply does not act on a channel that was never marked to
   auto-start. **Operator action:** after any upgrade or restart, check
   each channel you run by hand and press Start if it is not already on
   air, or turn on "Start automatically" for it so this is not needed
   again. Gate A's cross-version-upgrade lane does not assert on-air state
   after install-over, so this gap is not caught by that lane.
6. **Installing a kit over a station that already reports the same version
   string does not replace the app -- it silently does nothing.** The
   installer's pack staging
   (`civiccast/apps/installer/src-tauri/src/native_pack_staging.rs`,
   `classify_dest_pack_state` -> `AlreadySatisfied`, and
   `ensure_pack_extracted`'s matching early return) decides whether to
   re-stage a pack by comparing the already-installed pack's declared
   `product_version` string to the kit's -- it never looks at the pack's
   actual content. When a kit is rebuilt without bumping that version
   string, installing it over a station already on that version leaves the
   old files in place: the installer still exits `0` and `/health` still
   comes back healthy, because nothing about the running station actually
   changed. **Measured on the tester:** installing kit `91caebc` over a
   station that was already installed from an earlier `1.0.0-beta.5`
   candidate left the pre-#172 caption tap running underneath it -- proven
   by comparing file hashes before and after the install, not by anything
   the installer or the health check reported. **This does not affect the
   customer upgrade path:** a real beta.4 -> beta.5 upgrade carries two
   different version strings, so the version comparison correctly sees a
   change and replaces the payload, exactly as documented above. It only
   affects re-installing the *same* declared version to pick up a kit that
   was rebuilt without a version bump -- something only this project's own
   release process does today. **Workaround:** uninstall the station
   completely, then install the new kit fresh, rather than installing over
   the existing station. **Fix pending:** tracked as
   `fix/pack-staging-identity-not-version-string` -- not part of this
   candidate.
7. **(item 51, RESOLVED -- confirmed fixed on hardware by soak #5) Every
   GStreamer playout worker relaunched under a real schedule -- a
   regression from #170, not present in beta.4.** #170's 30-minute plan
   window (`PLAN_MIN_SECONDS=1800`, `PLAN_MAX_SEGMENTS=120` in
   `civiccast/egress/source_plan.py`) built far more decoder chains than
   an 8-core CPU-only station can run at once when schedule items are
   short -- see "Root cause of soak #3" above for the full mechanism.
   MEASURED broken: soak #3, clean install of kit `91caebc`, 30-second
   schedule items, FAIL -- one relaunch per channel in the first 30
   minutes, then roughly every 30 seconds (rule is zero). Fixed by
   `fix/plan-window-decoder-blowup` (merged as #174, part of candidate 2)
   -- caps plans at 8 segments, ties the replan floor to the plan length,
   and hard-caps decoder chains in the engine. **MEASURED fixed:** soak #5
   (candidate 2, `609273d`), first 30 minutes -- workers at roughly 550 MB
   RSS / 178 threads, against the prior 3.5 GB / 1,238 threads. Candidate
   2's hardware soak still FAILED overall, but on a different, later-firing
   defect -- item 60, below.
8. **(item 54) A long `TRANSITIONING` state is the product's designed
   graceful drain, but the operator cannot tell it from a hang.** When a
   live content reload cannot be applied seamlessly, the running program
   is deliberately allowed to play to its natural end before the new plan
   starts -- this is expected behavior, not a fault, and the streams
   themselves stayed clean throughout (TSDuck probes kept passing; no
   channel went off air). MEASURED: soak #4, kit `91caebc` -- once the
   plan window held the rescheduled long clips, a schedule gap fell back
   to slate, one channel tripped the 5-crash guard, and the planner then
   issued a rollover for a plan it believed had ended 1,208 seconds
   earlier; all three channels sat in `TRANSITIONING` from `22:55Z`
   onward. The defect is that the operator has no way to distinguish this
   drain from a stall: there is no label for it, no time-in-state shown,
   and the health view resets its clock on every write, so a drain in
   progress looks identical to a fresh healthy poll. **Operator action:**
   none needed for an ordinary drain; if a channel stays in
   `TRANSITIONING` past the end of its current program, Stop then Start
   it. **Fix pending:** PR #175, targeted for beta.6.
9. **(item 55) During a graceful drain, automation bookkeeping and a lost
   control-pipe acknowledgement both go unsurfaced.** Two related gaps
   surfaced by the same soak #4 drain: channel automation stops updating
   its own rollover bookkeeping while a channel is draining, so its
   internal state can drift from what is actually airing; and a lost
   control-pipe acknowledgement (the worker's ack of the reload command)
   is never surfaced anywhere, so there is no signal when the drain's own
   command handshake fails silently. Neither is addressed by hotfix #174.
   **Fix pending:** PR #175, targeted for beta.6.
10. **(item 58) Gate A's cross-version-upgrade lane failed at its own phase
    1 on a harness/sandbox gap, not a product defect.** Gate A run
    `33998901590` (candidate 2, `609273d`): the pinned `v1.0.0-beta.4`
    baseline installer crashed inside the sandbox before any upgrade step
    ran. The baseline `setup.exe`'s bytes were independently verified
    identical to the published `v1.0.0-beta.4` release asset, ruling out a
    corrupted or wrong baseline artifact. Because the lane never reached
    the candidate's own upgrade or post-upgrade schema proof, this run
    says nothing either way about candidate 2's upgrade path. **Fix
    pending:** the sandbox/harness gap that let the baseline install
    itself crash before phase 1 started; re-run in progress as Gate A
    `34004354641`.
11. **(item 60) When the planner extends a running plan, the in-place
    reload starves live playback and can fail silently -- present since
    #162, previously masked by item 51.** Tester-proven 2026-09-06
    (`tester-soak5-609273d-20260906`): (a) the reload's prepare step
    writes the new plan's segment files onto the same paths the live
    worker is still playing -- `<work>/<channel>/prepared/segment-NNNN.ts`,
    keyed by channel only and written in place, not atomically
    (`civiccast/egress/preparer.py:342`/`378`, `:246-268`, `:465-476`) --
    so playback starves and the existing 10-second stall watchdog
    relaunches the worker; and (b) the in-place reload command itself can
    fail to reach the worker at all, and the daemon returns without
    logging it (`civiccast/egress/daemon.py:1617-1618`), falling into the
    drain path (`TRANSITIONING`) with the worker's own logs showing no
    reload ever arrived. The `vconcat_program`/`aconcat_program` element
    name collision (`civiccast/egress/gst/engine.py:361-363`,
    `civiccast/egress/gst/bridge.py:639`) is a real defect in the same
    reload path but was not the trigger measured on hardware. No in-place
    rollover has ever committed on real hardware. Present in beta.4 as
    well -- beta.4 simply never exercised the code path, since #162
    postdates beta.4. **MEASURED:** soak #5 (candidate 2, `609273d`),
    clean install, FAIL from roughly 02:58Z -- see "Root cause of soak #5"
    above. **This is why `609273d` is not the beta.5 release candidate.**
    Fix: `fix/gst-reload-concat-collision` (open, not yet merged) -- gives
    each plan its own prepared directory with atomic writes and cleanup,
    logs a failed reload instead of silently falling through to drain,
    fails loud on a refused element add, gives each rollover's concat
    elements unique names, makes the reload acknowledgement honest, and
    disables the seamless in-place rollover by default for the GStreamer
    engine in beta.5 (`CIVICCAST_EGRESS_SEAMLESS_RELOAD=1` re-enables
    it). Not part of candidate 2; will be part of candidate 3.
12. **(item 61, targeted for beta.6) A worker's reload acknowledgement
    reports success before the reload actually commits.** The same defect
    underlying item 60's masking: the control-pipe reload ack is sent once
    a reload is attempted, not once GStreamer confirms the new elements
    are actually in the pipeline. Item 60's fix makes this specific ack
    honest for the concat-collision case; a general, structural
    ack-after-commit guarantee is tracked separately for beta.6.
13. **(item 62, targeted for beta.6) The decoder-chain cap is enforced per
    plan, not per pipeline.** `MAX_PLAYLIST_SUBCHAINS` bounds how many
    decoder chains a single plan can build, but a pipeline can briefly
    carry more than one plan's worth of chains during a rollover attempt
    (the outgoing plan's chains plus the incoming plan's chains
    coexisting) -- the cap does not account for that overlap. Tracked for
    beta.6.
14. **(item 64, part of item 60) The prepare step for a rollover clobbers
    the live worker's own segment files.** `SourcePreparer.prepare` keys
    its output directory by channel id only
    (`civiccast/egress/preparer.py:342`) and writes each new plan's
    segments over the same `segment-NNNN.ts` paths
    (`civiccast/egress/preparer.py:378`) the currently-airing plan is
    still reading, with no per-plan directory and no atomic write. Fix:
    `fix/gst-reload-concat-collision` (per-plan prepared directories,
    atomic writes, cleanup).
15. **(item 65, part of item 60) A failed in-place reload is never
    logged.** `EgressDaemon`'s reload path returns `False` with no log
    line or proof event when `reload_content` fails
    (`civiccast/egress/daemon.py:1617-1618`), so a reload that never
    reached the worker is indistinguishable, from the logs, from one that
    was never attempted. Fix: `fix/gst-reload-concat-collision` (logged,
    honest reload failure).

## Also in this candidate: release-prep

- **#164 -- identity bump to `v1.0.0-beta.5`, baseline repin to the
  published beta.4 kit, clock-timed source-factory table.** Every
  `check_release_identity.py`-bound surface now reads `1.0.0-beta.5`;
  `sandbox-lab/upgrade-baseline.json` is repinned from the beta.3 kit to
  the published beta.4 kit (source SHA
  `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`, build run `33854799455`, Gate
  A run `33901203343`) so Gate A's cross-version and download-only lanes
  upgrade from the actual current published release. Also fixes a
  `source_leg_is_clock_timed` docstring/code mismatch (the fail-safe
  default for an unknown source factory has always been `False`, not
  `True` as documented) and adds the Windows live-capture device factories
  to `CLOCK_TIMED_SOURCE_FACTORIES`. See `[Unreleased]`/`[1.0.0-beta.5]` in
  `CHANGELOG.md` for the full account.

Full detail for every item above is in the dated `[1.0.0-beta.5]` section of
`CHANGELOG.md`.

## Surfaces to flip at publish time (prepared list, not applied in this PR)

This PR deliberately does **not** change any of the following to say
`v1.0.0-beta.5` is current -- that flip happens only at actual publish time,
alongside `docs/releases/release-truth.yaml`'s `staging` -> `current` flip
for `v1.0.0-beta.5` and `current` -> `superseded` flip for `v1.0.0-beta.4`.
Prepared here so publish is a mechanical sweep, not a rediscovery:

- `README.md` -- "Current version" banner, the beta.4 GitHub Release link,
  the `v1.0.0-beta.4-verification.md` link, and the "next candidate"
  paragraph naming beta.5 as owner-held/unpublished.
- `docs/index.html` -- the version-identity HTML comment, the FAQ's "is
  this the current release" answer, and the "next candidate" paragraph.
- `INSTALL-WINDOWS.md` -- any "upgrade of an already-installed station"
  wording that names beta.4 as the target of an in-place upgrade.
- `docs/tester/START-HERE.md`, `docs/tester/lpm-beta-test-handoff.md`,
  `docs/tester/known-limitations.md`, `docs/tester/SMARTSCREEN-WALKTHROUGH.md`,
  `docs/tester/technical-walkthrough.md` -- "current release" wording.
- `ARCHITECTURE.md`, `SUPPORT.md`, `FAQ.md`, `CAPABILITIES.md` -- release
  posture paragraphs naming the current candidate.
- `docs/adoption/release-policy.md` -- any current-release cross-reference.
- `docs/releases/release-truth.yaml` -- flip `v1.0.0-beta.5` `staging` ->
  `current`, `v1.0.0-beta.4` `current` -> `superseded` (`superseded_by:
  v1.0.0-beta.5`).
- This document and `v1.0.0-beta.5-verification.md` themselves --
  `Status: DRAFT` -> `Status: PUBLISHED`, all `<PLACEHOLDER>` tokens filled
  with the real run ids, hashes, and evidence paths from tonight's actual
  run.

## Evidence

**Candidate 1 (`91caebc`) -- Gate A PASS x3, hardware soak FAIL (item 51). Not
publishable.**

- **Gate A:** run `33972726431`, all three lanes PASS, evidence copied to
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-verdict-33971258093\gate-a-verdict.json` /
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-dirty-verdict-33971258093\gate-a-verdict.json` /
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-download-only-verdict-33971258093\gate-a-verdict.json`.
- **T6 relaunch-count retest (caption-tap-driven, pre-#172):** tester branch
  `tester/soak8-e1acfe6-DESKTOP-VBMA6O5` and local copy
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\tester-soak8-e1acfe6-20260905\`
  (see "T6 relaunch-count retest" above -- real-hardware, `FAIL`).
- **Soak #3 (clean install, decoder-pileup regression, item 51):** clock
  started `2026-09-05T20:16:29Z` on tester `DESKTOP-VBMA6O5`, `FAIL` --
  see "Root cause of soak #3" above.
- **Soak #4 (real clip durations, item-boundary diagnostic):** clock
  started `2026-09-05T21:08:51Z` on kit `91caebc`, result `FAIL
  (relaunches)` -- see "Fourth real-hardware soak" above; also surfaced
  the designed graceful-drain visibility gaps, items 54/55 (operator
  cannot tell a drain from a hang; automation bookkeeping and a lost
  control-pipe ack go unsurfaced during one).

**Candidate 2 -- source SHA `609273da22b968b8ed9320dfc158d67b01eb30b3`
(`609273d`), build run `33997406150`, cut from `main` after
`fix/plan-window-decoder-blowup` merged as #174. Gate A clean PASS,
hardware soak FAIL (item 60). Not publishable.**

- **Gate A:** run `33998901590`, started 2026-09-05T23:48Z. Clean `PASS`;
  cross-version FAILED at phase 1 on a harness/sandbox gap (item 58), not
  a product result; download-only not reached. Re-run in progress: Gate A
  `34004354641`.
- **Clean-install hardware soak (soak #5):** clock `2026-09-06T02:26:16Z`,
  verdict `FAIL` -- relaunches one per channel by `02:56Z`, then about
  every 30 seconds -- see "Fifth real-hardware soak" and "Root cause of
  soak #5" above.

**Candidate 3 -- cut from `main` after `fix/gst-reload-concat-collision`
(item 60's fix) merges. Remaining evidence pending:**

- **Release:** `gh release view v1.0.0-beta.5 -R scottconverse/civiccast-native
  --json isDraft,assets,targetCommitish,tagName`.
- **Hash + signature, verified from the outside:**
  `scripts/download_windows_release_artifacts.ps1 -AssetSet NativeCandidate`,
  cross-verified against `SHA256SUMS.txt` and `Get-AuthenticodeSignature`.
- **Source SHA:** `<BETA5_FINAL_SHA>`. **Build run:**
  `<BETA5_FINAL_BUILD_RUN>`.
- **Gate A:** run `<GATE_A_FINAL_RUN_ID>`. Lanes pending: clean, cross-version,
  download-only.
- **Clean-install hardware soak:** clock `<SOAK6_START_UTC>`, verdict
  `<SOAK6_VERDICT>`, relaunches `<SOAK6_RELAUNCHES>`.
- **Test suite:** `uv run pytest tests/docs tests/policy -q` re-run for this
  publish; see the commit history on this branch for the result.

## What did NOT change

- The kit-staging directory the live soak tester reads is not touched,
  moved, or deleted by this draft.
- The ~21 GB `station\` AI-model bundle is not, and will never be, a GitHub
  release asset.
- No tag or draft release exists yet for `v1.0.0-beta.5`. If the publish
  does not succeed end to end, this document stays a draft and nothing
  above is presented as done.
- Candidate 1 (`91caebc`) was never published -- it failed its hardware
  soak (item 51) before reaching the publish step.
- Candidate 2 (`609273d`) was never published either -- it failed its own
  hardware soak (item 60) before reaching the publish step.

## Related

- `docs/releases/release-truth.yaml` -- the authored release-state record;
  unchanged by this PR (`v1.0.0-beta.4` stays `current`, `v1.0.0-beta.5`
  stays `staging`).
- `docs/releases/v1.0.0-beta.5-verification.md` -- this candidate's draft
  verification record (Gate A run, asset/hash/signature checks -- all
  placeholders pending tonight's run).
- `docs/releases/2026-09-03-beta4-release-notes.md` -- the immediately
  prior publish record, same pattern this document follows.
