# Beta 10 startup freeze — live autopsy

**Observed:** 2026-09-20 16:14 MT

## What is proven

- `CivicCastSupervisor` and its control-plane Python child are still present. The child is PID `39496`; the service host is PID `27540`.
- The control-plane log stops at **14:46:42 MT** immediately after:
  `Caption retention first verification is still running after 1.0s; the scan proceeds FAIL-CLOSED...`
- The child is effectively idle/frozen: 27 threads, zero accumulated CPU in the current snapshot, and no new control-plane log output.
- `/api/health` still returns HTTP 200 with `{"status":"healthy"}` while all three channels are dark.
- `public`, `government`, and `education` `active.vtt` files are each 7 bytes (`WEBVTT`) and have not carried caption cues.
- The earlier six-hour ffmpeg timeout is real, but it occurred at **09:24 MT**, hours before this startup freeze. The proof worker polls every 30 seconds, so that traceback does not establish that it caused the one-second startup freeze.

## What is not proven

- A Python stack dump or wait-chain for PID `39496` could not be captured from this Codex process: Windows denied non-debugger process inspection, and the installed elevation helper's scheduled-task entry is no longer discoverable. The existing helper queue job remains untouched for later recovery.
- Therefore the current freeze cannot honestly be attributed to proof capture, retention, or any other worker yet. The last log line is a clue, not a causal proof.

## Consequence for the plan

The proof-capture timeout remains a real beta.10 defect to fix, but it is **not** the confirmed cause of this startup freeze. Before a code change, the next run must add bounded startup-phase evidence (or obtain a real stack dump) so the fix targets the blocker actually holding the station. Any resulting finding will be recorded before code changes; non-blocking proof-worker defects stay on the beta.10 list while the critical path is repaired.

Static inspection found one concrete critical-path risk that fits the timeline: after the
background threads are started, the app runs one-shot startup-condition hooks
synchronously on the lifespan thread. The recording-reconcile hook performs a database
query with no timeout. A stalled database call there can leave the control plane serving
health while never completing the rest of startup. This is a **candidate mechanism**, not
yet a causal proof from the unavailable stack dump; it is the first bounded-startup fix
to test because it protects air from any slow startup housekeeping, regardless of which
hook is slow.

## Safety

No product files, thresholds, tests, schedules, or runtime state were changed for this autopsy. No files were deleted, and no merge, tag, or publication was performed.
