# CivicCast beta.8 - frozen 24-hour soak plan (HUMAN REPORT v1)

Prepared 2026-09-17, Mountain Time. STATUS: **proposed, not started.**
Starting requires Scott's explicit go/no-go. This plan is frozen BEFORE the run:
do not change duration, targets, or success criteria after it starts, and do not
shorten it after a failure.

## Purpose

Prove the EXACT public distributable runs captions ON, on the Blackwell NVIDIA
GPU, across all three channels, for 24 uninterrupted hours, and answer the one
open question the short runs could not: whether the intermittent
`Caption tap overload` pause recurs in normal operation.

## Inputs (must be pinned before start)

- Distributable: the beta.8 public release asset from the owner-authorized
  publication step. Record here at start: release URL, `setup.exe` SHA-256, every
  `.ccpack` SHA-256, and `SHA256SUMS.txt`.
- Install: clean install from that exact installer on the Blackwell station
  (does NOT reuse the working install from the caption-fix session).
- GPU: captions must load `cuda` / `float16`. The soak must capture the
  post-prepare loaded-backend identity line
  (`loaded_device=cuda loaded_compute_type=float16`) in-window, bound to the
  soak's own worker PID.
- Captions: ON for all three channels (`public`, `government`, `education`).
- Output: outgoing feed per channel (UDP mirror or the operator's normal
  headend), so TS can be preserved.

## Settings for the station

- Live captions: **ON**. Set under Station Profile, "Show live captions on air".
  Restart each channel after changing it.
- Soak length: **24 hours** (proposed; Scott may change BEFORE start only).
- Output: the Generic CBR SPTS over UDP headend preset on each channel,
  destination `udp://127.0.0.1:5000` (Public), `:5001` (Government),
  `:5002` (Education).

## Setup, once

1. Upload the kit's sample clips; wait until each shows Ready.
2. Schedule clips back-to-back on all three channels so each channel has
   programming covering the whole 24 hours. Mix the clips; the scheduled program
   change is part of what is under test.
3. Apply the output preset per channel and Start each channel. Confirm all three
   reach On air within two minutes.
4. Screenshot the Readiness page once as the start-of-soak record.

## Sampling every 5 minutes, for 24 hours

One CSV row per channel in `Desktop\SOAK-samples.csv`:
time, channel, state, pid, source label, seconds on air, dropped frames,
captions state, RSS(MB) of every CivicCast `gst-worker`/`python.exe`.

Also record the caption tap backlog status per channel (the sidecar status the
console shows) and any red/yellow Readiness banner.

## Caption-specific evidence required by the handoff

At least once per hour, and at every event:

- Preserve the **cue-bearing outgoing VTT** BEFORE any clear
  (`C:\ProgramData\CivicCast\data\egress\<channel>\captions\active.vtt`),
  with the file's mtime.
- Preserve contemporaneous **TS** for the same interval.
- Run a bounded **15-20 second text decode-back** of the preserved TS and keep
  the output, showing that speech text reached the stream.
- Pick ONE run-specific expected cue in advance per check and prove its text
  appears in the decode-back; do not select the cue after seeing output.

## Events to log with timestamps (Mountain Time)

- Any channel state other than On air.
- Any channel pid change (relaunch).
- A scheduled program change that did not occur within 30 seconds.
- Dropped frames increasing.
- Any alert on the Alerts screen.
- **Every `Caption tap overload` line**, verbatim, with its timestamp - this is
  the primary question the soak answers.
- Any caption pause / cleared sidecar, with the preceding log line.
- RSS growth of any worker across an hour.
- Any freeze longer than 5 seconds on the monitored output.

## Failure handling (frozen)

- A failure does NOT end the soak silently. Record it, keep the run going unless
  the station cannot serve output at all, and preserve the evidence.
- Do not restart the service to "fix" a sample unless the run is already
  unrecoverable; if you do, log the exact time and reason and mark the window as
  interrupted.
- Do NOT change thresholds (backlog max 2, 120 s pause), do not disable
  captions, do not substitute CPU, and do not kill unrelated GPU workloads to
  make a sample pass.
- The soak duration is not shortened because of failures.

## At the end

1. Stop all three channels.
2. Copy to `Desktop\SOAK-evidence\`:
   - `C:\ProgramData\CivicCast\logs\control_plane-app.log`
   - `C:\ProgramData\CivicCast\logs\supervisor.log`
   - per channel: `...\data\egress\<channel>\logs\gst-worker.stderr.log` and
     `gst-worker.stdout.log`
   - the final cue-bearing `active.vtt` per channel, taken BEFORE stopping
   - the last preserved TS per channel plus its decode-back SRT
   - `SOAK-samples.csv`, the start screenshot, and every event note
3. Do not delete anything.

## Verdict rule (frozen)

- The soak PASSES only if: all three channels served output for the whole
  24 hours; captions were ON and produced fresh cues throughout; the
  decode-back shows real speech text reaching the stream including after any
  program change; loaded runtime identity shows cuda/float16 in-window; and no
  unresolved release blocker remains.
- **Any `Caption tap overload` pause is a finding, not automatically a failure**
  of the soak, but it MUST be reported with its timestamp and the
  backlog/retention state at that moment, and it reopens the intermittency
  question rather than being waved through.
- A PASS must name its limits: it is a 24-hour observation of one station, not a
  general reliability guarantee.

## Not covered by this soak

- Cross-version upgrade correctness (that is Gate A's job).
- Reboot/kill/restart unattended recovery beyond what incidentally occurs.
- Any channel or hardware not on this station.
