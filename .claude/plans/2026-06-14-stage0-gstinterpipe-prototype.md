# Plan — Stage 0: GstInterpipe seamless-swap prototype (the go/no-go risk gate)

Date: 2026-06-14 · Branch: `work/3.0-gstreamer-engine` · Spec: S15 §9 (hardened criteria) · Task #58

## Why (Hard Rule 11 plan)
The entire 3.0 re-platform rests on one unproven assumption: a **persistent GStreamer pipeline can
hot-swap raw-domain sources (program→filler→live→slate) while the mux/output stays in PLAYING**, so
MPEG-TS continuity counters never break (the #151 fix). Pre-build validation found GstInterpipe has
unresolved audio-sync (#56) + memory (#99) bugs and **no published 24/7 case study**, and GStreamer
does not *explicitly* guarantee mpegtsmux CC persistence across an upstream swap. So this is a true
**GO/NO-GO gate**, validated before committing the broader build.

## Approach
1. **Toolchain** (env setup): WSL Ubuntu-24.04 (root), full GStreamer stack + python3-gi + ffmpeg via
   apt; **GstInterpipe built from RidgeRun source** (`/opt/gst-interpipe`, meson/ninja). See
   `install_gst.sh`.
2. **Prototype** (`prototype/` in repo, Python + PyGObject): a persistent output pipeline
   (`interpipesink`-fed sources → `compositor`/queue → `x264enc` → `mpegtsmux` → `udpsink`/filesink)
   that **stays in PLAYING** while a controller swaps `interpipesrc.listen-to` among ≥3 named source
   pipelines (program/filler/slate; live = a 4th), cycling automatically for a multi-hour run.
3. **Instrumentation:** capture the emitted TS to file; analyze per-PID **continuity counters** across
   every swap (ffprobe / TSDuck-style CC check); measure **A/V sync** and **RSS** over the run.

## Hardened PASS criteria (all required; per S15 §9)
- **CC continuity:** 0 MPEG-TS continuity-counter errors across every swap.
- **Audio:** no blip/skip; A/V sync within tolerance across N swaps (#56 failure mode).
- **Memory:** flat RSS over a multi-hour cycling run (#99 failure mode).
- **Caps:** no caps-renegotiation glitch (`allow-renegotiation=false`; matched source caps).

## Decision rule
- ALL pass → commit the re-platform; proceed to Stage 1 (S15 engine).
- ANY fail → **STOP. Write a report with the failure data + the recommended Plan-B branch**
  (a: fallbackswitch+input-selector 2-state; b: separate-pipelines-via-UDP-multicast [Ideal World];
  c: fork+fix GstInterpipe) and **pause for Scott** — no silent pivot.

## Out of scope (Stage 0)
SDI/DeckLink output (needs hardware), the full engine, CG/WPE, the program-log control plane — those
are Stage 1+. Stage 0 proves *only* the seamless-swap + CC-continuity premise on commodity CPU.

## DONE
A documented prototype result (PASS with the 4 metrics, or FAIL + Plan-B report), committed on the
branch, plus a Stage-0 stage report for Scott.
