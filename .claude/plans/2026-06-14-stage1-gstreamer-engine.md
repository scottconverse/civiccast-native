# Stage 1 — GStreamer Playout Engine (S15) — Build Plan

> Written 2026-06-14. Autonomous build, branch `work/3.0-gstreamer-engine`.
> Stage 0 PASSED (input-selector hot-swap → 0 MPEG-TS continuity errors, 40 swaps, flat RSS).
> Cadence: TDD per slice → `/audit-lite` to 0/0/0/0/0 → commit. Stage report + `/walkthrough` + `/audit-team` at close.

## Goal
Re-platform the channel playout *encode/mux core* from the single-ffmpeg `ConcatEncoderStrategy`
onto a **persistent GStreamer pipeline with seamless source hot-swap** that fixes #151 by design,
while reusing the existing orchestration unchanged (automation/scheduler, store, supervisor, health,
branding, the `EgressSinkSpec` config contract).

## Integration seam (verified by reading the code 2026-06-14)
- `civiccast/egress/encoder_strategy.py` — `EncoderStrategy` Protocol: `start(EncoderStartRequest) -> EncoderStartResult`. Current impl `ConcatEncoderStrategy` ("concat-demuxer-single-ffmpeg-process", ADR-0015 Option A).
- `civiccast/egress/runtime.py` — `build_persistent_encoder_args()` builds the ffmpeg command; `start_persistent_encoder()` spawns it.
- `civiccast/egress/sinks.py` — `EgressSink` hierarchy builds **ffmpeg output args** per `EgressSinkSpec` (srt/rtmp/local-ts/udp-ts/file/sdi). `build_sink()` dispatcher.
- `civiccast/egress/models.py` — `EgressSinkSpec` (kind/uri/secret_ref/latency/extra_args), `EgressConfig` (sinks + `canonical_profile` codec/bitrate/GOP + slate/loudness/fill_policy), `EgressSourcePlan` (ordered segments). DB rows + states (STOPPED→STARTING→ON_AIR→TRANSITIONING→FALLBACK_SLATE→DRAINING→STOPPING→ERROR), `pid`, health samples, proof events.
- `civiccast/egress/daemon.py` / `supervisor.py` — `EgressDaemon` / `PlayoutSupervisor` consume commands (start/stop/reload/drain), track state + pid (encoder reaping #161).

## Design decisions (record in Stage-1 report)
- **D-S1-1 — New `EncoderStrategy` impl, not a rewrite.** Add `GstPlayoutStrategy` implementing the existing Protocol; select via an `engine` setting (`"ffmpeg-concat"` default / `"gstreamer"` opt-in). ffmpeg path stays for back-compat; both coexist during transition. Reuse `EgressSinkSpec` (uri/kind), NOT the ffmpeg `output_args()`.
- **D-S1-2 — Per-channel playout *worker process*** running PyGObject + a GLib mainloop, spawned/supervised exactly like the ffmpeg process (pid → supervisor reap/restart, #161). Keeps a pipeline crash from taking down the API. S15 "in-process" = source-swap is in-process *within* the worker (no separate mux process), which this satisfies.
- **D-S1-3 — Pluggable swap mechanism.** `SwapController` interface: `InputSelectorSwap` (default, Stage-0 proven, apt-clean) + `InterpipeSwap` (stub; drop-in iff Scott authorizes the GstInterpipe source build). GstInterpipe is NOT required for Stage 1.
- **D-S1-4 — Graceful teardown is first-class** (Stage-0 finding): unblock/flush source pads before `→NULL`, plus a hard shutdown watchdog so playout can never hang (the 6-hour hang must be impossible in production).
- **D-S1-5 — Test split:** pure builders (pipeline-desc string, sink-element mapping, CC parser) unit-tested on Windows; live Gst execution integration-tested in WSL Ubuntu-24.04 (where GStreamer 1.24.2 + python3-gi live). `/audit-lite` gates each slice.
- **D-S1-6 — Source model (RECORDED 2026-06-14; implement in slice 3b).** `EgressSourcePlan` is a *sequential* list of segments (the ffmpeg-concat paradigm); the engine selector exposes *parallel* source roles. Options: **(A)** a **"program" source leg that plays the plan's segments gaplessly** (a `concat`/playlist sub-pipeline feeding one selector pad) + dedicated `slate` and `live` selector pads — the supervisor's existing reload rebuilds the program leg's playlist while the **output half stays PLAYING** (truest #151 fix, supervisor logic unchanged); **(B)** pre-roll every segment as its own selector pad and swap per segment (pad explosion; breaks the plan-as-unit model); **(C)** one decodebin per segment chained manually (no gaplessness). **DECISION: Option A** — it preserves the supervisor's plan/reload/look-ahead/live-takeover/slate semantics (they "port over unchanged" per S15) AND delivers the persistent-output #151 fix. Slice 3b implements: the gapless program leg, slate + live legs, `graph_from_config(config, source_plan)`, and the worker/strategy that maps the supervisor's *reload → selector swap* (never a process restart).
- **D-S1-7 — Slate message rendering (RECORDED 2026-06-14, env-driven).** Stock Ubuntu 24.04 `gstreamer1.0-plugins-base` 1.24.2 ships **no pango plugin** — `textoverlay`/`clockoverlay`/`timeoverlay` are unavailable on a commodity box (verified: no `libgstpango.so`, even after reinstall). So the slate must NOT depend on pango. **DECISION:** the base slate is a solid background; the slate *message* (`config.slate_message`) is rendered to an image via the existing **S6 CG render path** and shown with `gdkpixbufoverlay`/`imagefreeze` (plugins-good, present) — richer than pango text (logos/layout) and dependency-clean. Implement the image-slate in a later slice (with S6 CG integration); until then the slate is a solid color. Commissioning note (S3): do NOT assume the pango plugin is present.
- **D-S1-8 — TS rate control (RECORDED 2026-06-14).** Headend CBR is applied as HRD **constant-bitrate VIDEO** (x264enc `nal-hrd=cbr` + VBV at the target rate) — the main lever, validated. GStreamer `mpegtsmux` does **not** expose ffmpeg-style `-muxrate` null-packet stuffing to a fixed *transport* rate. For IP-TS to a headend that re-muxes/QAMs, CBR-video is sufficient; if a specific headend requires a constant TS mux rate, add a stuffing stage / muxrate-capable mux later (follow-up, not a blocker). TSDuck `run_compliance_probe` (CA-7, BYO `tsp`) is the field verifier on the same udp-ts sink; dev proof = `check_ts` TR-101-290 P1 continuity (0 errors on the file sink AND the captured UDP stream).

## Slice sequence (TDD; each ends at 0/0/0/0/0 + commit)
- **Slice 0 — scaffold + spec reconcile.** Create `civiccast/egress/gst/` package. Reconcile S15 spec: primary mechanism = `input-selector`/`fallbackswitch`; GstInterpipe → optional-pending-authorization. Add `engine` config flag (default ffmpeg-concat).
- **Slice 1 — pure pipeline builder.** `build_playout_pipeline_desc(config, sources, sink_elements)` → Gst launch string; `gst_sink_element(EgressSinkSpec)` mapping: `udp-ts`→`udpsink host/port` (+ multicast), `file`→`filesink`, `local-ts`→udp|file, `srt`→`srtsink`. Windows unit tests (string assertions, no Gst import).
- **Slice 2 — engine runner + swap + teardown.** `GstPlayoutEngine` (build → PLAYING → controller swaps active source → graceful teardown + watchdog) and `SwapController`/`InputSelectorSwap`. WSL integration test = productionized Stage-0 prototype: ≥20 swaps, **0 CC errors**, flat RSS, clean exit (no hang).
- **Slice 3 — strategy wiring.** `GstPlayoutStrategy(EncoderStrategy)` → `EncoderStartResult` with the worker process handle; daemon selects it when `engine="gstreamer"`; supervisor pid/reap works.
- **Slice 4 — headend egress (the three paths Scott directed).** Direct IP `udpsink` unicast + multicast with **CBR muxrate/PCR** from `canonical_profile`; IP/ASI-to-demarc and IP/ASI-to-on-prem-QAM share the IP-TS path (ASI = declared-future sink needing a card). TSDuck verify hook (reuse CA-7) on TS sinks.
- **Slice 5 — A/V + CG-lite.** `audiotestsrc`/real audio with atomic A+V swap; `textoverlay`/`clockoverlay`/`gdkpixbufoverlay` for titles/crawl/clock/bug. (Rich CG, captions/CEA-708, SAP → later stages per spec.)

## Done-criteria (S15 §9 — gate the stage report on these)
1. **0 MPEG-TS continuity-counter errors across every swap** (per-PID CC + TSDuck-verified).
2. **A/V sync within tolerance, no audible blip** across N swaps (the #56 failure mode).
3. **Flat RSS** over a sustained cycling run (the #99 failure mode).
4. **No caps-renegotiation glitch** (`allow-renegotiation=false`; pre-verify source caps match).
5. **Per-sink output proof** (udp/file/srt) with TSDuck on TS paths.
6. Engine drives a channel end-to-end via the existing program-log/scheduler control plane; #151 gone.

## Flagged for Scott (non-blocking)
- Authorize the GstInterpipe external source build → only needed to validate `InterpipeSwap` head-to-head; the engine ships on `input-selector` regardless.
- Confirm LPM's physical Comcast drop (IP hand-off vs fiber-return device vs on-prem QAM) → last-mile config only; egress is built selectable for all three.

---

## RE-OPEN — Stage-1 completion (2026-06-14, after Scott caught deferred items)

Stage 1 had been declared "closed" with real work deferred behind soft language ("post-close",
"limitations"). Scott re-opened it: leave NOTHING undone, build the missing infra, prove it.
Four gaps closed, each DONE (not deferred), all tests green:

- **Gap 1 — engine selection wiring (was: nothing selected gstreamer).** `engine_select.build_encoder_strategy()`
  reads `CIVICCAST_EGRESS_ENGINE` (default `ffmpeg-concat`; `gstreamer` → `GstPlayoutStrategy`), wired at BOTH
  `EgressDaemon` construction sites (`cli._run_egress_service`, `automation` builder). 4 unit tests.
- **Gap 2 — program content-reload (the real D-S1-6, was skipped).** Found the slice-6 reload→swap routing was
  in `PlayoutSupervisor`, which the app never constructs — the app drives reloads through the base
  `EgressDaemon` command queue (`automation` enqueues `action="reload"` when a program is due). So the seamless
  path was wired where it belongs: `EncoderStrategy.supports_content_reload`/`reload_content()`; the daemon's
  `_request_reload` now does a **seamless content-reload** for a capable strategy (resolve the new plan → tell
  the worker to rebuild the program leg in place), falling back to terminate+restart on any case it can't own.
  The engine got `reload_program()` — runtime pipeline surgery: build the new program leg on the live PLAYING
  pipeline, preroll it, switch the selector on the new leg's **first buffer** (pad-probe → main-loop idle, never
  blocking output), then dispose the old leg. Proof chain still records the source→source transition (no
  TRANSITIONING *state* — output never drops). Control protocol gained `reload <graph.json>`.
- **Gap 3 — live source leg (was: only program+slate built).** `source_first_element()` maps a live segment
  (`kind="live"`) to the live source element by URI scheme (`srtsrc`/`udpsrc`/`rtmpsrc`/`rtspsrc`/`souphttpsrc`)
  → `decodebin`; the engine plays a live feed via start OR a content-reload takeover (reuses Gap 2). Proven by a
  real UDP-TS ingest round-trip in WSL (0 CC). **DEFERRED to S16 (Production/Control Room, optional later tier,
  master step 9) WITH reason — not "post-close":** the dedicated always-hot `live` selector role (instant-cut)
  and the operator live-takeover control surface (TSR/switcher UI + `PlayoutSupervisor` app-wiring) need the S16
  operator surface, which is that stage's scope.
- **Gap 4 — real WSL-pytest gated harness (was: by-hand smoke scripts).** `tests/egress/test_gst_engine_wsl.py`
  drives the **production** worker subprocess over the control FIFO and checks captured MPEG-TS for CC errors:
  build/teardown-clean, swap continuity, **content-reload continuity** (Gap 2), no-hang-on-stop, live UDP ingest.
  Auto-skips on Windows (no gi) so the cross-platform suite stays green. Runner: `tests/egress/run_wsl_engine_tests.sh`
  (creates `~/cc-wsl-venv`, system-site gi + pytest>=8). Infra built under Scott's standing admin authority.

**Result:** Windows egress suite **398 passed, 5 skipped**; WSL live-engine harness **5 passed** (0 CC on swap,
content-reload, and live ingest). New deployment flag `CIVICCAST_EGRESS_ENGINE`. The only Stage-1 deferral is the
S16 operator live-control surface, named + reasoned above.
