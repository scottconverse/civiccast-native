# U16 - coordinator answer (2026-09-24 22:31 MDT)

Good stop, and good work: sections 1.4-1.8 are exactly the evidence I needed. You were right that the brief's
section B was a no-op. Decision (engineering call, mine): do NOT change the rebase policy (keep `max`).
Instead ship the three items below, in this order, each red-then-green, small commits, `git status --porcelain`
before each, never amend. Worktree rules are unchanged (`civiccast-ds`, branch `beta10-ds`), except item C, which
is in the OTHER worktree as stated.

## A. Diagnostics (engine) - make the next occurrence decomposable
In `civiccast/egress/gst/engine.py`, on every reload commit, print to stderr on ONE line beside the existing
"finite switch rebased" line: each outgoing pad's `state["end"]` (stream name + value in seconds, or `none`),
whether the fallback path was used, `self._pipeline_running_time_ms()`, and the chosen `switch_running_time`.
Then, for the NEW leg, print once per stream the running time of that stream's first buffer AFTER the offset
is applied (a pad probe on each new-leg src pad that removes itself after one buffer). Also print, once per
stream at worker start, the running time of the first buffer that reaches the mux sink pad.
Format: `CTRL reload diagnostic: ...` / `CTRL start diagnostic: ...` like the existing diagnostics. Always on
(no env switch). Unit test with a fake pad/probe; a real-GStreamer test that asserts the lines appear if the
bundled runtime is available (skip cleanly otherwise, and say so).

## B. Output A/V guard (daemon) - self-heal what we cannot yet prevent
Live facts: public held +108.95 s for 15+ min after a switch; government held +2.79 s from a fresh start;
a channel restart cured both (government 21:57: +2.79 s -> 0.005 s). U12's relay now probes the newest HLS
segment's stream kinds. Extend that machinery (reuse its ffprobe resolution, timeout and tri-state fail-safe)
so the daemon, per channel, about every 30 s, probes the newest COMPLETE segment for the first packet PTS of
the video stream and of the audio stream.
- If |audio first PTS - video first PTS| > 1.0 s on 3 consecutive probes, log ONE ERROR line naming the
  channel, the three measured offsets and the segment names, and restart that channel's WORKER (the same
  restart path a dead encoder takes - not the relay alone, because the offset is created in the engine).
- Bound it: at most 3 guard restarts per channel per rolling hour; after that, log an ERROR every 10 min
  and do not restart.
- A probe that cannot measure (None, missing stream, timeout) counts as "no measurement": it neither
  advances nor resets the streak, and never restarts anything.
- Do not probe a channel that is not ON_AIR, and reset the streak whenever the worker pid changes.
Tests: streak logic (3 in a row, reset on a good sample, None ignored, pid change resets), budget logic, the
restart call is the dead-encoder path, and a real ffprobe test against two small TS files you generate (one
in sync, one with a 2 s audio `-itsoffset`) using the ffprobe resolution U12 uses. `tests/egress -q -p
no:randomly` -> 1 known failure only; ruff + mypy on changed files.

## C. Licence table fix - in the OTHER worktree
In `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-gst` (branch `beta10-gst1287`), correct
`civiccast/native/runtime_licenses.py`'s entry for `gsthlssink3.dll` from `LGPL-2.1-or-later` to `MPL-2.0`
(U17 found `gst-inspect-1.0` reports `License=MPL` on both 1.28.5 and 1.28.7). Update any test pinning the old
value, run `tests/native/test_runtime_licenses.py` there, one commit. Touch nothing else in that worktree.

## Report
Append to `reports\U16.md` a section "U16 part 2" with the commits, the raw proof for A/B/C, and doubts.
