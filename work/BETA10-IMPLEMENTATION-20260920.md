# CivicCast beta.10 implementation report

**Report time:** 2026-09-20 16:41 Mountain Time  
**Checkout:** `main` at the existing local HEAD plus the uncommitted beta.10 changes  
**Scope:** startup freeze containment, bounded caption proof work, and an explicit
controlled schedule loop. No merge, tag, publish, or deletion was performed.

## What was proven before changing code

The installed station froze about one second after startup while `/api/health`
continued to return HTTP 200. All three caption sidecars were empty (`7` bytes),
and the control-plane log stopped after the first retention-verification warning.
The process stack could not be captured with the available tools, so the exact
blocking call is not proven.

An earlier six-hour ffmpeg timeout is a real defect, but it is not a proven cause
of this one-second startup freeze. It is therefore fixed as a containment issue,
not reported as the freeze's root cause.

## Changes implemented

1. **Startup hooks are bounded and isolated.** One-shot startup housekeeping now
   runs in daemon threads and is given a one-second budget by default. A slow
   hook can finish in the background and cannot hold the airing/control path.
2. **Caption proof capture and decode-back are bounded.** Both ffmpeg call sites
   fail closed after 15 seconds by default (`CIVICAST_CAPTION_PROOF_TIMEOUT_SECONDS`).
   A timeout records a failed proof sample; it is never treated as caption
   success.
3. **Supervised proof work is isolated.** When the service is supervised, proof
   work defaults to a separately supervised child process. The child is
   restarted after a bounded failure and is terminated cleanly on shutdown.
   Unsupervised developer launches retain the inline worker unless the process
   mode is selected explicitly.
4. **Controlled schedule looping is explicit.** Setting
   `CIVICAST_SCHEDULE_LOOP=1` repeats the published sequence for a soak while
   preserving its assets and gaps. The default finite schedule behavior is
   unchanged.
5. **Operator documentation now names the switches and their limits** in
   `docs/ops/channel-egress-runbook.md`.

## Verification so far

- Prior focused baseline: **139 passed**.
- New focused regression set: **79 passed** in 12.95 seconds.
- Ruff check/format: clean on the changed Python files.

These are source-level receipts. They do **not** prove that the installed
service has loaded the changes or that a live three-channel rung passes.

## Next live sequence

1. Compare the installed module hashes and service configuration with this exact
   checkout; preserve the current installed state before staging.
2. Stage only the changed runtime modules into the installed runtime, retaining
   a reversible copy and recording hashes.
3. Configure the controlled soak with `CIVICAST_SCHEDULE_LOOP=1`, without
   changing product thresholds or deleting any existing evidence.
4. Restart the test service once through the existing elevation path.
5. Verify real service behavior: log continuity, `/api/health`, per-channel
   `ON_AIR`, non-empty caption sidecars, and the loaded process/module identity.
6. Run the planned 15-minute shakedown, then a 15-minute proof-enabled
   shakedown, then the watched 30-minute three-channel soak. Capture the
   evidence ledger and any failure verbatim.
7. Confirm a schedule rollover on disk before advancing to the 2-hour rung.

If the live evidence identifies a different startup blocker, the proof-capture
and hook changes remain bounded safety improvements, but the next code change
will follow the observed blocker rather than an assumption.

## Current verdict

**Implementation is not yet live-validated.** The source changes and focused
tests are green; the station is not a pass until the staged installed runtime
survives the real shakedowns with all three channels airing captions.
