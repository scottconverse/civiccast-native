# BYO-NDI Relay (issue #116, Scott's option c) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Scott's decision (option c):** productize an "easy to connect wire" for NDI — the station gets the NDI runtime/an NDI-capable FFmpeg build from NDI/NewTek themselves (license is theirs to accept), and CivicCast supervises a production NDI output once the wire exists. Same BYO posture as TSDuck (CA-7): detect honestly, never fake readiness.

**License/technical reality (why BYO):** mainline FFmpeg removed the NDI muxer in 2019 after the NewTek GPL dispute; stations must build/obtain an NDI-capable FFmpeg themselves plus the NDI runtime. CivicCast's bundled ffmpeg cannot and must not ship it. `civiccast/cable/ndi.py` already detects runtime/SDK/muxer (`check_ndi_runtime`) — reuse it.

**Design — supervised side-relay, not an encoder output leg:**
The channel's persistent encoder already emits MPEG-TS (udp-ts/local-ts/srt). The NDI wire is a *separate supervised process* per channel:
`<byo-ffmpeg> -i udp://127.0.0.1:<port> -vf scale=...,fps=... -pix_fmt uyvy422 -f libndi_newtek "<NDI name>"`
Reasons: (a) the BYO binary is a *different ffmpeg* than the bundled one — the main encoder must not depend on it; (b) NDI needs raw uyvy422 video (a re-encode leg), keep it out of the on-air process; (c) crash isolation — a dying NDI relay must never take the cable channel down; (d) everything (programs/slate/bulletins/join-in-progress) composes for free because the relay eats the channel's output.

## Pieces
1. **`civiccast/egress/ndi_relay.py`** (new, TDD):
   - `NdiRelaySettings` (env): `CIVICCAST_NDI_FFMPEG` (path to the station's NDI-capable build; REQUIRED for the relay — bundled ffmpeg refused with honest copy), `CIVICCAST_NDI_RELAY=inline|off` (default inline — supervise when configured).
   - `build_ndi_relay_args(source_uri, ndi_name, *, video_size, framerate)` pure (reuses cable/ndi.py constants + name sanitizer).
   - `NdiRelaySupervisor`: per-channel process lifecycle (start/health/restart with backoff/stop), state surfaced as `ndi_relay` field on the channel's health sample or its own status row; restart caps + last_error copy mirroring the egress daemon conventions.
   - Readiness gate at start: `check_ndi_runtime` with the BYO binary; not ready → honest `not-run/blocked` status with the next_step from cable/ndi.py, never a crash loop.
2. **Durable config**: new `ndi` sink kind is WRONG for this (it is not an encoder output). Instead: `egress_configs` gains `ndi_relay_name TEXT NULL` (NULL = off) — **migration 0035**; relay source = the channel's first udp-ts/local-ts udp:// sink.
3. **Staff API** (egress/router.py, TDD): config PUT/GET already carry the new field via EgressConfig model; `GET /api/staff/egress/ndi-readiness` (check_ndi_runtime against the BYO binary + per-channel relay status); relay state included in channel detail.
4. **Automation wiring**: channel automation driver starts/stops the relay supervisor alongside the channel when `ndi_relay_name` is set (app lifespan + CLI worker both).
5. **Console**: ChannelOps "NDI output" mini-panel — name field + enable, readiness copy (honest BYO hint when no NDI-capable ffmpeg), relay status line. e2e.
6. **System Health**: fold into headend/channel checks only if cheap; otherwise relay state lives on the channel detail (avoid check sprawl).
7. **Docs**: runbook "NDI output (bring your own NDI-capable FFmpeg)" — where to get NDI Tools/SDK, the license posture, receiver proof boundary ("not claimed until a real NDI receiver shows the stream — Studio Monitor screenshot = station-side proof"); CAPABILITIES row `real component (config-gated, BYO ffmpeg, receiver proof pending)`; OpenAPI regen.

## Boundary honesty
No NDI-capable ffmpeg exists on this dev box → unit/contract tests use runner seams; the live receiver proof is a station-side step documented in the runbook (LPM has NDI in the building). CAPABILITIES must say exactly that.

## Steps
branch `work/ndi-relay` → relay module TDD → migration 0035 + EgressConfig field (+ head pin advance) → API + automation wiring TDD → console panel + e2e → docs + OpenAPI → full gate → PR `refs #116` → merge.
