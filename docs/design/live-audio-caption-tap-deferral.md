<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Design Deferral — Live-Audio Caption Tap

Status: **resolved and built** (Beta sprint B6, 2026-06-10). Scott picked
**option 1 — egress audio fork**. The egress encoder forks rolling mono
16 kHz WAV segments per channel (`civiccast/captions/tap.py`,
`CIVICCAST_CAPTION_TAP_DIR`); the supervised caption tap worker
(`civiccast/captions/tap_worker.py`,
`CIVICCAST_CAPTION_TAP=off|inline|external`, default `off` — opt-in because
it needs a local transcription model) consumes settled segments into the
durable review queue through the existing live caption seam. The lifecycle
reuses the finalization worker's hybrid pattern, as recommended below.

The original deferral record follows for history.

---

Recorded during audit sprint Stage E, 2026-06-09.
Owner of the pending decision: Scott (product) with the dev for sizing.

## What exists today

- A real caption transcription worker and pipeline
  (`civiccast/captions/worker.py`, `pipeline.py`, `stabilize.py`) that turns
  audio into stabilized cues, plus WebVTT/HLS emission and the operator
  review queue (now durable — `caption_review_items`, Stage E).
- A proof script that exercises the worker end-to-end by feeding it
  **synthetic silence** (`scripts/prove-live-caption-path.py`).
- Capability matrix truth: the worker is `real component → implemented but
  not wired` — nothing bridges **live broadcast audio** into it, and no
  lifecycle starts/supervises it in a deployment.

## What is missing (the tap)

A production path that takes the audio of an in-progress live session and
feeds it to the caption worker with acceptable latency, plus the same
lifecycle questions the finalization worker already answered (start mode,
supervision, self-healing, status surface).

## Options sketched (not decided)

1. **Egress audio fork:** the egress/playout supervisor (which already owns
   the ffmpeg process graph) forks a low-bitrate audio-only output (e.g.
   16 kHz mono PCM over a local socket or named pipe) consumed by the caption
   worker. Pros: single owner of media processes; works for every source the
   station can broadcast. Cons: couples captions to egress lifecycle.
2. **Recorder sidecar tap:** the component writing the recording file also
   tees audio frames to the worker. Pros: same provenance as the recording.
   Cons: the recorder is the least-supervised piece today; adds a second
   consumer to its output path.
3. **Post-hoc only (explicit non-live posture):** run transcription against
   the recording as a finalization-worker step; live broadcasts go uncaptioned
   in real time. Pros: smallest build, reuses the Stage B+D worker pattern.
   Cons: no live accessibility — a real product trade-off that needs an
   explicit decision, not a default.

## Why deferred

The audit sprint plan scopes Stage E to the durable review store and names
the live-audio tap design as deferred ("defer live-audio caption tap
design"); the tap depends on the egress supervisor architecture (Stage C of
the release ladder / E.2 validation work) and on a latency/accessibility
product decision that hasn't been made. Building it now would guess at both.

## What unblocks it

1. Scott picks the posture: live captions required at launch (options 1–2)
   vs post-hoc captions acceptable initially (option 3).
2. If live: pick the tap point (egress fork recommended for single-owner
   media processes) and size the latency budget end-to-end
   (tap → worker → stabilize → HLS cue injection).
3. Reuse the finalization worker's hybrid lifecycle pattern
   (inline thread / external process / off + supervision + status surface) —
   do not invent a new daemon shape.
