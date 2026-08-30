# civiccast.summary Changelog

## Unreleased - 2026-08-29

- Fixed: field evidence (candidate #17, 32GB CPU-only reference station) showed
  `POST /api/staff/summaries/generate` 503ing at ~120s even when Ollama itself
  produced a completion, because the control-plane socket budget
  (`ai_runtime.ollama_client._request_json`) was fixed at 120s for both cheap
  metadata calls and live generation. Live generation now gets a 600s budget
  (`DEFAULT_GENERATE_TIMEOUT_SECONDS`).
- Added: async summary generation job (`civiccast/summary/job.py`,
  `civiccast/summary/persistence.py`, migration `0012_summary_generation_jobs`) —
  the same durable-queue-plus-worker pattern the offline caption job (K3)
  established, so a legitimate multi-minute CPU-only generation survives instead
  of blocking (or discarding) an HTTP request. New endpoints:
  `POST /api/staff/summaries/jobs`, `GET /api/staff/summaries/jobs`,
  `GET /api/staff/summaries/jobs/{job_id}`,
  `POST /api/staff/summaries/jobs/{job_id}/retry`. `POST /generate` (synchronous)
  is unchanged and still works.
- Added: "Generate summary" operator control (`GenerateSummaryPanel`, asset
  detail screen, next to the offline caption job panel) — previously the Summary
  review screen said "Next step: generate a summary" with no button anywhere in
  the UI to do so.
- Fixed: the AI Models console's summary latency claim ("≈4.2 s typical") was
  ~30x wrong on the CPU-only reference station (measured 94-366s+); captions'
  claim ("≈500 ms typical") was ~70x wrong (measured ~3.3x real time). Local
  on-box tiers now render a CPU-only-caveated range instead of false precision
  (`ai-models-format.ts::tierLatencyLabel`).
- Fixed: the summary adaptive default (`detect_summary_model_default`) picked
  `gemma4:12b` on any >=16GB box regardless of GPU presence. On the CPU-only
  reference station 12B took 366s to complete once and then failed twice more
  under realistic memory pressure; `gemma4:e4b` completed every attempt
  (94-128s). The default now requires a real GPU (NVML-detected) before
  offering 12B; every CPU-only box gets e4b regardless of RAM. Threaded through
  the installer's first-run seed and provisioning-plan surfaces
  (`installer/station_state.py`, `installer/model_download.py`) and the
  `civiccast doctor`/station-box-profile report
  (`platform/station_box_profile.py::select_ai_defaults`) so they agree with
  the runtime default on the same hardware.
- Documented: translation is exposed as a selectable, latency-quoted model in
  the AI Models console but no caller supplies a translation target, so it is
  never actually invoked and no translated caption track is published. The
  console now says so plainly instead of implying a working capability.

## v0.6.0 - 2026-05-14

- Added sourced-summary Pydantic contracts.
- Added quantitative extraction and transcript range validation.
- Added deterministic summary generation with one retry and refusal on
  unsupported evidence.
- Added transcript CSV export.
- Added in-memory and Postgres-backed summary stores.
- Added summary approval metadata persistence for signed-record export gates.
