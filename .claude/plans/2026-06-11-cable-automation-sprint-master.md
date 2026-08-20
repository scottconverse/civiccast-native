# Cable Automation Sprint (PEG automation system) — Master Plan

> Scott's directive 2026-06-11: "We just need to get the SOFTWARE written to DO it all, together, in a coherent easy to operate way so you can, literally, drop CivicCast in as a replacement for an incumbent PEG platform... Our testing only needs to be, say, one 24 hour period on a test machine, then we have something we can REALLY beta test." Green-lit with "Go". This jumps ahead of NDI/SDI/macOS in the queue.

**Goal:** Three concurrent cable channels running 24/7 from an operator-editable program log — programs from the recordings library, bulletin/slate fill between programs, headend-grade output (CBR SPTS MPEG-TS over UDP) with named provider profiles and machine-verified compliance. Acceptance gate: one unattended 24-hour three-channel run on this machine including a forced encoder crash, then LPM beta.

**What the survey found we ALREADY have (do not rebuild):**
- `egress/supervisor.py` `PlayoutSupervisor` — per-channel encoder lifecycle w/ live takeover/handback, forced-slate fallback, command queue (start/stop/reload/drain).
- `egress/source_plan.py` `ScheduleSourcePlanProvider` — schedule_items → ordered `EgressSourceSegment`s (asset file_path + trim), `SlateSourceGenerator` fallback, gap tolerance, 8-segment lookahead.
- `egress/branding.py` CG→filter_complex; `egress/models.py` durable `EgressConfigDb`/`EgressSinkDb`/health samples; sink kinds incl. `local-ts` (mpegts) — `sdi` stub.
- `cg/models.py` bulletin submissions w/ moderation states, templates/zones, `MultiZoneCgSnapshot`.
- `cable/channel.py` ChannelProfile/PlayoutBlock/ChannelNowNext contracts; `cable/package.py` file-package path.
- `platform/worker_runtime.py` ThreadSupervisor pattern; schedule premiere collision EXCLUDE constraint (Postgres).

**What's missing (the sprint):** recurring scheduling, program-log semantics + materialization, bulletin-loop filler video, guide editor UI, N-channel orchestration + health rollup, UDP/SPTS sink + headend profiles, TSDuck verification, the 24h proof.

## Stages
- **CA-1 Program log:** `channel_program_slots` (recurrence: once/daily/weekly/weekdays) + occurrence link table (migration 0031); materializer worker writes real `schedule_items` (mode=premiere) over a rolling 72h horizon, idempotent, collision-skipping with surfaced warnings; staff CRUD API + materialized-log preview endpoint. Existing source-plan path then plays it with ZERO egress changes.
- **CA-2 Continuous channel driver:** wire PlayoutSupervisor into app lifespan per enabled channel (`CIVICCAST_CHANNEL_AUTOMATION=inline|off`), crash recovery = supervisor restart + join-in-progress (seek into current program by wall clock), proof events into the existing playout-proof trail.
- **CA-3 Bulletin filler:** render the channel's approved CG bulletins into a looping MPEG-TS filler video (ffmpeg drawtext/image pipeline, regenerate on bulletin change); fill policy per channel: bulletins | slate. Slate remains the fallback of last resort.
- **CA-4 Three channels:** N supervisors from channel config, per-channel health in System Health + egress health rollup, resource guard notes (3× ffmpeg on one box).
- **CA-5 Guide editor:** operator console screen — weekly grid per channel, place recordings (search the library), recurrence pick, fill-policy pick, conflict warnings from materializer; resident portal "schedule" view from the materialized log.
- **CA-6 Headend profiles + UDP sink:** new sink kind `udp-ts` (multicast, pkt_size=1316, CBR via -b:v/-maxrate/-bufsize/-muxrate, strict closed GOP, mpeg2video|libx264, mp2|ac3 audio); named profiles `comcast-mtd-hd`, `comcast-mtd-sd`, `telvue-hypercaster-ip`, `harmonic-spectrum`, `generic-udp-spts`. **Scott's directive 2026-06-11: build GENERIC from the published vendor documentation (Comcast MTD, Harmonic/Spectrum ingest specs, TelVue HyperCaster config, Leightronix) — no station-specific tailoring, no LPM spec dependency. This must read like a product any new station downloads cold; LPM is simply beta #1 to surface pain points.** Fetch the public docs at build time; profiles bake the spec numbers, operator supplies only address + bitrate from their carriage agreement.
- **CA-7 TSDuck compliance + discovery:** BYO-TSDuck (BSD — bundling allowed later) `tsp`-based verification of the live output against the profile (CBR stability, PCR, TR 101 290 priority-1/2), readiness probe results in System Health; TelVue/Leightronix device reachability probes.
- **CA-8 Acceptance:** 24h unattended 3-channel run on this machine — real program logs, bulletin fill, rollovers incl. midnight, forced encoder kill mid-program with auto-recovery, TSDuck monitoring on one channel; result file under tester-handoff, runbook, CAPABILITIES truth pass. THEN LPM beta.

Per-stage detailed plan files: `.claude/plans/2026-06-11-ca1-program-log.md` (et seq). Every stage: TDD, full backend gate, PR to main, honest CAPABILITIES updates (claims say "verified on one machine / not yet field-proven at a headend" until LPM).
