# Sprint 3 item 9: unequal A/V ending evidence

## Behavior implemented

For a deferred switch at a finite program end, the engine records each selected stream's last buffer and end time, waits for both outgoing EOS events, and switches at the later measured end. After the first stream ends, a worker on the selector output fills only that stream's remaining interval: it repeats the final video frame or emits format-shaped PCM silence. The producer paces against pipeline running time and follows the still-active stream's latest end. It pushes outside the selector pad-probe callback and does not hold the engine lock while pushing.

Reload abort and engine stop signal and wake the filler; stop also removes a queued GLib filler-start callback. The common-end mux drain confirmation remains in place. Its timeout is extended by graph-declared per-output audio processing latency (including the output worker's 3-second `audioloudnorm` metadata), without counting queue capacity as latency.

## Focused verification

Native Windows GStreamer 1.28.5, Python 3.14, and the pinned GI bindings were used. The focused command was:

```powershell
C:\Python314\python.exe -m pytest tests/egress/test_gst_engine_wsl.py::test_deferred_rollover_switches_at_the_common_av_end_without_eos -q
```

Exact final output:

```text
..                                                                       [100%]
2 passed in 17.37s
```

The two cases used video/audio durations 2.4/4.0 seconds and 4.0/2.4 seconds. The test observed both outgoing EOS events and filler completion for the shorter stream; verified the worker remained alive through handoff, both elementary streams continued in the emitted TS, transport continuity had no CC errors or backward PCR/PES PTS steps, and ffprobe found both codecs with maximum packet PTS gaps under 150 ms for video and 120 ms for audio near the switch. It then stopped the worker cleanly.

Focused reload-ordering checks:

```powershell
.venv\Scripts\python.exe -m pytest tests/egress/test_gst_engine_reload_commit_ordering.py::test_deferred_commit_waits_for_both_outgoing_eos_and_tail_fill tests/egress/test_gst_engine_reload_commit_ordering.py::test_switch_running_time_uses_common_maximum_without_trimming tests/egress/test_gst_engine_reload_commit_ordering.py::test_deferred_video_only_commit_still_settles_on_its_only_eos tests/egress/test_gst_engine_reload_commit_ordering.py::test_u30_a_dropped_outgoing_eos_is_named_before_it_is_dropped -q
```

Exact output:

```text
....                                                                     [100%]
4 passed in 1.43s
```

`py_compile` for the engine and both touched test modules passed with exit code 0. `git diff --check` for those files passed with exit code 0.

Final formatting sweep covered the engine, HLS relay, and both focused test modules: `ruff format --check ...` reported `4 files already formatted`. After formatting, `py_compile` and `git diff --check` passed again. HLS was formatted only; its existing scoped checks were not rerun for whitespace changes.

## Limits and documentation notes

The native asymmetric proof used the existing selected-audio chain, not a graph with per-output `audioloudnorm`; that branch's extra drain bound is based on the graph's declared latency and was not exercised by this test. The filler requires a copyable final video buffer or supported interleaved `audio/x-raw` PCM caps. If the filler cannot produce buffers, the engine emits a WARN and settles the completed EOS transaction at its common boundary, so an output gap remains possible in that failure case. The deferred-switch watchdog can also force a boundary from the latest observed end when natural EOS does not arrive. User-facing docs should describe the common-end handoff only if documenting output transition behavior; no new operator action is required.

During verification, the first assertion pass exposed issues in the new test's accounting (it expected both EOS lines to be `2/2`) and ffprobe parsing (CSV side-data commas and the MPEG-TS 3600-second PTS epoch). The assertions/helper were corrected; the final native run above passed both asymmetric directions.

## Existing ordering-module reconciliation

The parent reported an initial ordering-module run of `112 passed, 2 skipped, 16 failed`. Inspection confirmed production pending reloads initialize the filler events before publishing the transaction, so abort cleanup was correct; several test-only pending dictionaries that exercise abort lacked those fields. The shared abort fixture and the three commit-failure fixtures now carry fresh lifecycle Events. Existing ordering assertions were also updated where they encoded the old shorter-end rule: with ends at 1.0s and 1.1s, rebase and selector cutoff now use 1.1s; the build-race test expects the first of two EOS events to leave the transaction unsettled. One measured mux-fence test now uses video end 1.8s and audio end 1.1s so it still proves the audio fence targets its own end separately from the common switch point.

The first post-consolidation ordering-module run found two remaining stale shorter-end assumptions (`test_finite_commit_arms_selector_cutoffs_before_rebase_snapshot` expected a 1.0s offset, and the measured mux-fence case made common cutoff equal the audio target). Those test inputs/assertions were corrected. Final focused result:

```text
128 passed, 2 skipped in 3.13s
```

The two skips are the module's existing real-runtime diagnostic cases; this invocation did not declare `CIVICCAST_GSTREAMER_RUNTIME_ROOT`. No native asymmetric test was rerun for these test-only corrections.
