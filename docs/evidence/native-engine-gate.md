# Decision-gate evidence — native Python media engine (charter §2 gate)

**Date:** 2026-07-17 · **Machine:** Windows 11 Pro 10.0.26200, developer box
(confidence class 3) · **Runtime:** stock CPython 3.12.13 venv +
`gstreamer-bundle==1.28.5` (pip) · **Engine code:** `civiccast/egress/gst/`
worker.py + engine.py + graph.py at integration-branch HEAD, **zero
modifications** — the exact files WSL production runs.

## Gate behaviors (charter: switching, recovery, multichannel)

1. **Hot source-swapping** — `SWAPS=4 INTERVAL=2 python worker.py demo-graph.json`
   → `WORKER_RESULT {'swaps': 4, 'error': None, 'teardown_clean': True}`,
   exit 0, 4,163,072-byte TS; ffprobe: h264, 10.5s; full decode via
   `ffmpeg -f null` with ZERO errors.
2. **Crash recovery** — worker hard-killed mid-broadcast after 6s
   (3,312,372 bytes written): process reaped in **0.00s, no hang, no
   zombie** (`os._exit` teardown held natively); immediate relaunch produced
   3,316,132 bytes in the next 6s. The pathology the WSL keeper existed to
   babysit does not manifest natively.
3. **Multichannel** — three concurrent engine processes, 8 swaps each,
   distinct outputs: all `{'swaps': 8, 'error': None, 'teardown_clean':
   True}`, exits 0, ~11.4 MB each, 18.9s wall clock.

## Verdict input (per charter §2 decision gate)

The Python engine meets switching/recovery/multichannel natively with zero
porting cost. **Gate verdict: the Python engine is validated** for hot
source-swapping, crash recovery, and multichannel operation (the three
behaviors above); recommendation is to retain the Python media worker — the
Rust `gstreamer-rs` port is closed as unnecessary (remains the recorded
fallback if soak/session-0 evidence later demands it). This verdict is
machine-bound to evidence via `docs/claims/claims.yaml`, pending owner
trust-root acceptance (D6) — the correct honest state until Scott accepts
the pin. <!-- claim:native-decision-gate -->

## Out of scope here (remaining gate items, tracked)

Session-0 service execution (next spike) · packaging/minimal closure ·
memory/soak stability · clean-machine · live-peer/hardware sinks.
Commands and raw outputs preserved in the program transcript. CORRECTION
(2026-07-17): this file originally said "the committed demo-graph JSONs" —
no graph JSON was committed with this evidence. Reruns are one command each
from `graph.demo_test_graph()` (which generated the gate's graphs), or from
the equivalent graph now committed at
`../spike-session0/evidence/demo-graph.json`.
