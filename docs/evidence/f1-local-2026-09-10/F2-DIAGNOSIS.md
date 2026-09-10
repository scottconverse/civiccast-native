# F-2 scheduled-boundary diagnosis (read-only)

Base inspected: `d77b634e3685de8fb077956b8099fc92c3927243`; files inspected were
`civiccast/egress/automation.py`, `civiccast/egress/source_plan.py`,
`civiccast/egress/gst/reload_policy.py`, and the F-2 section of `PROJECT-STATUS.md`.
No implementation, tests, processes, or services were changed or started.

## Proven runtime path

`ChannelAutomationService._run_channel_pass` calls `daemon.process_once` first,
then calls `_check_slate_replan` and `_check_plan_rollover` using a timestamp read
after `process_once` returns. `daemon.process_once` can synchronously execute
`SourcePreparer.prepare` through `_try_content_reload`; this is on the automation
thread. The archived control-plane log measured 35.0s preparation for government
and 16.3s for public at 23:20, followed by the government's `ack timeout after
5.0s; falling back to restart`. These are direct log observations, not estimates.

`_check_slate_replan` only runs when the persisted state is `FALLBACK_SLATE`, has a
one-shot `_reload_issued` latch, and applies a 30s `_replan_retry_at` cooldown.
`_check_plan_rollover` only runs for `ON_AIR` or `FALLBACK_SLATE`, requires a
tracked dispatched-plan horizon keyed by proof-event id, skips manual overrides,
and waits for `rollover_trigger_at(plan_end_at, last_segment_start_at,
min_lead_seconds)`. It then applies a per-channel dispatch floor derived from
the planned segment duration and waits while a reload settlement is pending.
The reload itself reaches `_request_reload` -> `_try_content_reload` -> strategy
`reload_content`; `should_defer_switch` defers only an ordinary `ON_AIR` reload
or a finite slate with a tracked horizon. A stale or absent horizon does not
constitute proof that a boundary was missed.

`build_source_plan_from_schedule` sorts published premiere items, selects the
currently active item, clips each segment to its slot, stops on a gap or short
media, and bounds the plan by `max_segments`/`segment_cap`. A multi-segment plan
therefore represents several future slots; a worker log that lacks a line at a
particular wall-clock minute cannot by itself prove that source was absent or
that the worker should have switched at that minute.

## Archived Blackwell evidence

The ZIP was inspected with `tar -tf`/`tar -xOf`; it was never extracted over the
repository. `SOAK-events.log` records missed checks at `23:25`, `23:50`, and
`23:55` for all three channels, and the control-plane log contains reload issue
lines at `23:20:01` for government/public, 35.0s/16.3s synchronous preparation,
and the government 5.0s acknowledgement timeout. The status report records the
observed automation issue pattern as `:00 :05 :10 :15 :20 :30 :35 :40 :45`, with
no `:25 :50 :55` dispatches. The raw evidence establishes the outcome and the
timing, but does not identify which gate suppressed each missing boundary.

## Candidate causes

Proven contributors are synchronous preparation on the shared automation thread
and the 5-second acknowledgement fallback to full restart. Both can delay later
channel passes and cause a boundary sampler to observe the old source.

The missing-minute pattern is a separate unresolved cause. The most plausible
code-level candidate is horizon/trigger gating: rollover dispatch is derived from
the currently dispatched multi-segment plan's last-segment start and lead floor,
then filtered by per-channel cadence and pending-settlement latches. That can
legitimately produce a non-clock-aligned dispatch schedule, but the current
evidence does not prove it is the cause of exactly `:25/:50/:55`.

Other hypotheses still requiring instrumentation are: schedule materialization
or conflict state at those three minutes; a source-plan provider returning a
shorter plan or `None`; `_run_channel_pass` delayed by another channel's prepare;
and a reload command queued but consumed after a restart/settlement path. The
existing logs do not distinguish these.

## Smallest first regression ticket

Add a deterministic automation test with three channels, a fake monotonic clock,
an injected preparation callback that blocks one channel, and schedule items at
five-minute boundaries including `:25`, `:50`, and `:55`. Capture per-channel
pass start/end, provider calls, `_enqueue` calls, `plan_end_at`, trigger time,
cadence gate, and pending-settlement state. First assert that a blocked prepare
cannot prevent the other channels' boundary checks from running; independently
assert that each due boundary either enqueues exactly one reload or records the
specific gate that deferred it. This separates the shared-thread defect from
the minute-pattern defect before choosing an implementation fix.
