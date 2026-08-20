# CA-7: TSDuck Compliance Verification + Headend Readiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md). CA-1..6 = #141-#146.

**Goal:** Machine-verified confidence that the CA-6 udp-ts output is headend-grade, without claiming more than the tooling proves. BYO-TSDuck (BSD license — bundling allowed later): when `tsp` is installed the station can run a bounded analysis probe of the live stream (TS sync, continuity, PAT/PMT, PCR presence, bitrate-vs-muxrate stability) plus a TCP reachability probe of their headend device (TelVue/Leightronix web management surfaces). Absent TSDuck → honest "not installed" status with an install pointer, never a faked pass.

**Honesty boundary (bake into models + docs):** the probe runs TSDuck's `analyze` plugin over a bounded capture — a *subset* aligned with TR 101 290 priority-1 concerns (sync, continuity, PAT/PMT), not the full TR 101 290 monitoring suite, and not headend field proof. Continuous monitoring during the 24h run is CA-8; field proof is the first-station beta.

**Verified context:**
- `tsp` not on PATH on this box — the real-probe test is env-gated (skip without TSDuck), contract tests use a fake runner. For CA-8 monitoring, install portable TSDuck under `C:\CivicCastTester\tools\tsduck` (authorized local toolchain).
- CA-4 pattern for optional System Health checks: `build_system_health_report(..., channel_automation=...)` + `_automation_rollup` never-raises adapter in installer/router.py — repeat for headend readiness.
- udp-ts destination + expected muxrate are recoverable from the channel's egress config (sink kind `udp-ts`, `-muxrate Nk` in extra_output_args).
- Listening posture: multicast destinations can be probed alongside the real headend (multiple group members); unicast destinations are probed *in place of* the receiver during commissioning — document, don't hide.

## Pieces

1. **`civiccast/egress/compliance.py`** (new, TDD):
   - `TsduckStatus` (installed: bool, version, path, install_hint) + `locate_tsduck()` (env `CIVICCAST_TSDUCK_PATH` wins, else PATH; version via `tsp --version`).
   - `build_compliance_probe_args(destination_uri, seconds, json_report_path)` → `tsp -I ip <host:port> [--local-address] -P until --seconds N -P analyze --json-line/--json <file> -O drop` (exact flags pinned by tests; pure function).
   - `evaluate_tsduck_report(report_dict, *, expected_muxrate_kbps, tolerance_pct=5)` → pure: ts bitrate within tolerance, PAT/PMT present, PCR pid count > 0, continuity/sync error counts → verdict pass|fail with per-check detail list.
   - `ComplianceProbeResult` (pydantic, extra=forbid): channel_id, destination, probed_at, seconds, checks (list of {check, status, detail}), verdict (`pass|fail|not-run`), tsduck_version, raw_report_path, `not_claimed` (TR-subset + no-field-proof lines).
   - `run_compliance_probe(channel_config, *, seconds, work_dir, runner=subprocess seam, locator)` — resolves udp-ts sink + muxrate, runs tsp, parses, writes result JSON to `work_dir/<channel>/compliance-last.json` (read by the health check), returns the result. Errors → verdict fail with honest detail (timeout, no packets, tsduck missing → not-run).
   - `probe_device(host, ports=[80, 443], timeout_s=3)` → TCP connect per port (socket seam for tests) → `DeviceProbeResult` (vendor-agnostic; TelVue/Leightronix manage over their web UIs).
2. **Staff API** (egress/router.py, TDD):
   - `GET /api/staff/egress/headend-readiness` → TsduckStatus + per-udp-ts-channel last-probe summary (from work-dir JSON; never raises).
   - `POST /api/staff/egress/channels/{id}/compliance-probe` (setup_admin; body: seconds=10) → runs the probe inline (bounded), 409/422 when the channel has no udp-ts sink, 503 storage, honest `not-run` verdict when TSDuck missing (200 with status, not an error — the report IS the answer).
   - `POST /api/staff/egress/headend-device-probe` (setup_admin; body: host, ports) → DeviceProbeResult.
3. **System Health** (installer/service.py + router, CA-4 pattern): optional `headend-readiness` check — green `not_set_up` when no udp-ts channels; yellow-info when udp-ts configured but TSDuck absent (BYO hint); green pass / red fail from each channel's last probe.
4. **CLI**: `civiccast egress verify --channel <id> --seconds N` → runs the same probe, prints the report, exit 1 on fail (CA-8 will loop it).
5. **Console** (ChannelOps headend panel): "Verify stream (TSDuck)" button + last-verdict line (per-check list, honest not-run copy when TSDuck missing); client fns; e2e in channel-app-config.spec.ts.
6. **Docs**: runbook "Verifying The Headend Stream" (install TSDuck pointer, multicast-vs-unicast listening posture, what the checks do/don't prove); CAPABILITIES row update; OpenAPI regen.

## Steps
branch `work/ca7-tsduck-verify` → compliance module TDD (locator/args/evaluate/run + device probe) → staff API TDD → health check TDD → CLI → console button + e2e → docs + OpenAPI → full gate → PR `refs cable-automation CA-7` → merge. **No migration** (last-probe state is a work-dir artifact, not a table). Install portable TSDuck locally afterward for a real smoke + CA-8.
