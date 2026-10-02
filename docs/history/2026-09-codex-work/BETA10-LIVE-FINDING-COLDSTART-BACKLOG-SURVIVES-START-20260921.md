# BETA.10 LIVE FINDING - cold-start caption backlog survives an explicit START

**Recorded:** 2026-09-21 ~22:50 MT
**By:** coder session (thread 01a0bdd6-b74a-7bf2-b09b-f96218493a8d)
**State under test:** repo HEAD 35d60b75 (main); installed runtime byte-identical for
captions/runtime.py; control-plane pid 42488 started 22:43:09 MT.
**Written BEFORE any code change, per the project rule.**

---

## 1. What was observed (authoritative, on disk)

After the greedy-CUDA runtime was staged and the service restarted, explicit STARTs were
issued for all three channels and accepted (HTTP 202):

    22:44:31 public     202
    22:44:31 government 202
    22:44:32 education  202

Six seconds into the new caption tap's life, ALL THREE channels tripped the backlog gate:

    22:43:31 education  4 settled segments exceeds max 2 -> PAUSED 120s, captions cleared
    22:43:31 government 3 settled segments exceeds max 2 -> PAUSED 120s, captions cleared
    22:43:31 public     4 settled segments exceeds max 2 -> PAUSED 120s, captions cleared

All three caption sidecars read exactly 7 bytes (`WEBVTT`, no cues) and stayed there:

    public     active.vtt 7 B, age 185 s
    government active.vtt 7 B, age  74 s
    education  active.vtt 7 B, age 131 s

So the station was UP and two channels reported ON_AIR, but caption-dead from startup.

## 2. Root cause - the session-start hook is UNREACHABLE on this path

`CaptionTapWorker.begin_channel_session()` is the ONLY caller of
`_discard_settled_segments()` (tap_worker.py:827). It is wired to the daemon as
`channel_start_hook`. In `EgressDaemon._start_steps` the hook is invoked at daemon.py:1331,
but that line sits AFTER this guard at daemon.py:1314-1330:

    existing_process = self._processes.get(channel_id)
    if existing_process is not None and _process_poll(existing_process) is None:
        state = self._store.read_state(channel_id)
        current_state = "DRAINING" if ... else "ON_AIR"
        self._write_state(channel_id, current_state, ...)
        self._append_health(channel_id, current_state, ...)
        return None            # <-- EARLY RETURN, before the hook

When an operator START arrives for a channel whose tracked process is still alive,
`_start_steps` returns at that guard and the hook is never called. Therefore
`_discard_settled_segments()` never runs, the previous session's settled WAVs remain in the
tap root, and the very next scan finds 3-4 of them and fails closed.

This is exactly the scenario the cleanup was written for. The code comment at
tap_worker.py:817-833 states the discard "runs ONLY on an explicit START command" and
explicitly lists a "restart without START" variant as NOT implemented -- but it did not
anticipate that a START issued while the daemon still tracks a live process ALSO skips the
hook. The cleanup is unreachable in the restart-recovery case it exists to serve.

## 3. Why the guard cannot simply be moved (the real constraint)

`_process_command` carries an explicit note (daemon.py:1128-1140) that the hook must NOT be
called on a DUPLICATE start: "Calling it here ran the hook for a DUPLICATE start on an
already-live channel -- which is a no-op that keeps the current writer running -- so its
session-scoped cleanup would have discarded the LIVE session's own audio."

So there are two genuinely different situations that currently collapse into the same early
return:

    (a) DUPLICATE start on a genuinely live session  -> must NOT discard audio
    (b) RECOVERY start after a restart/reload where the tracked process is stale-but-alive,
        and the settled backlog belongs to a PREVIOUS session -> MUST discard

The fix must distinguish (a) from (b) rather than moving the hook unconditionally.

## 4. Candidate seams (to be decided by red test, not by argument)

- **A. Daemon-side.** Detect the recovery case at the early-return guard (e.g. the tracked
  process predates the current control-plane process) and invoke the hook there, leaving the
  duplicate-start case untouched.
- **B. Tap-side.** Give the tap a first-scan discard keyed to a session boundary that does
  not depend on the daemon hook. NOTE the stated reason this was rejected before: the WAV
  writer is a separate per-channel GStreamer subprocess, so file mtime cannot establish
  which process produced a chunk. Any B must not rely on mtime alone.

Recommendation: A, because it preserves the existing "no writer for the new session exists
yet" soundness argument at a real transition, and leaves the duplicate-start protection
intact.

## 5. Relation to the greedy-CUDA fix (do not conflate)

Commit 35d60b75 (live tap decodes greedily on CUDA) is CORRECT, staged, loaded, and proven
by hash identity and by unit tests. It is NOT the fix for this failure: the backlog in this
event consisted of 3-4 segments ALREADY SETTLED ON DISK before any new transcription ran.
Faster decoding cannot drain a backlog that accumulates before the gate is evaluated. Both
fixes are needed; neither substitutes for the other.

## 6. Status at time of writing

    public     STARTING  (state row updated 22:45:24)
    government ON_AIR    (state row updated 22:42:36)
    education  STARTING  (state row updated 22:46:23)
    all three caption sidecars: 7 bytes
    control-plane pid 42488, health 200, listener 127.0.0.1:8000
    greedy-CUDA runtime: loaded (installed hash == repo hash)
    rung: NOT re-run and NOT startable from this state
---

## 7. CORRECTION + PRECISION (23:05 MT, from the RED test)

The section-2 mechanism was directionally right but imprecise about WHICH guard eats the
start. The RED test (`test_start_on_a_still_tracked_process_still_runs_the_session_hook`)
shows `daemon.process_once("gov")` returning **0** -- the command was never even drained.
So the loss is one layer earlier than `_start_steps`.

Precise chain, from the live code:

1. `process_once` runs a fixed poll tuple BEFORE draining commands:
   `(_poll_hls_relay, _poll_process, _service_backoff_relaunch, _poll_reload_settlement)`.
2. `_poll_process` (daemon.py:2206) sees `_processes[channel_id]` non-None and
   `_process_poll(process) is None` (still alive).
3. It writes health + state for the channel and then executes a **bare `return`**
   (daemon.py:~2255) -- it does NOT pop the pending command.
4. The `start` command stays queued, so `process_once` drains nothing and returns 0.
   `_start` / `_start_steps` are never entered at all, so the hook at daemon.py:1331
   cannot run.

Net effect is the same: `begin_channel_session()` -> `_discard_settled_segments()` never
fires, the previous session's settled WAVs remain, and the tap fails closed at 3-4 segments.

The distinction that still matters (unchanged):

    duplicate start on THIS daemon's own live process  -> must NOT discard live audio
    restart-recovery start against a process ADOPTED from a previous control plane
                                                       -> MUST discard stale backlog

The RED test encodes exactly that difference via `_adopted_previous_process()`.

Remaining open question for the fix: `_poll_process` is described in its own comments as a
pure poll (health + state), so the cleanest seam may be to let the command drain proceed and
run the session reset in the recovery case there, rather than making `_poll_process` mutate
caption state. That decision belongs with the fix, not this finding.
