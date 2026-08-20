# Build Step 10 — S11: CEA-708 Captions + Per-Sink Loudness + EAS Software Layer

**Branch:** `work/3.0-gstreamer-engine` (parent at authoring: `8a399535`, step-9 close).
**Authored:** 2026-06-17. **Spec:** `docs/spec/3.0/sections/S11-captions-loudness-eas-compliance.md`.
**North star (Scott, explicit):** functional coverage matching incumbent PEG workflows, in software only. Improve where software lets us (local/free captions); never add legal liability an incumbent PEG platform avoids (no SAME, no auto-EAS-takeover).

## Migration-numbering reality (ADR 0008 pattern)
The spec's planned `0044_loudness_and_eas` is **stale** — `0044` is already `cg_board_designer` and the chain is at `0048_remote_contribution`. S11 takes the next free numbers:
- **`0049_loudness_and_eas`** — per-sink loudness columns on `egress_sinks` + `EgressCaptionProofSample` table + the EAS tables (`eas_cap_sources`, `eas_cap_alerts`, `eas_display_decisions`).
- **`0050_secondary_audio`** — `audio_program_tracks` (SAP / descriptive audio).
Both on the single global Alembic chain. **Reminder (from step-9):** real Postgres enforces schema-qualified seeds, timestamptz types, and the `alembic_version` width — every new migration MUST be exercised by `TestRealPostgresFullMigrationChain` (run the gated real-PG suite, do not trust SQLite).

## Locked decisions (the 5 open spec decisions, resolved by Scott on parity grounds)
1. **Loudness multi-regime → per-sink (NOT single-regime-per-channel).** The incumbent PEG workflow normalizes per destination (cable −24 LKFS / streaming −16 LUFS) from one show. We do the same: `loudness_target_lufs`/`loudness_regime` live on `EgressSinkSpec`; the conform/egress path applies the resolved target per sink.
2. **CEA-708 ffmpeg → ship a 708-capable ffmpeg build (NOT BYO).** We already ship ffmpeg; captions are a carriage obligation, not a hardware add-on. The incumbent PEG workflow sells captioning ($12/hr cloud); we provide it built-in, local, free. `doctor` verifies the 608/708 lane; if our shipped build lacks it, fix the build (our task, not the operator's).
3. **EAS auto-escalation → operator-controlled, NO auto forced-takeover.** The incumbent PEG baseline is NOT an EAS device; match that posture. Auto-*surface* informational alerts (crawl/overlay) is the software "better"; full-screen pre-emption always needs a human (or explicit pre-authorized source). Keeps us off the "EAS device" line.
4. **SAME local origination → DO NOT BUILD.** The incumbent PEG baseline does not generate SAME; building it adds legal liability without parity benefit. Drop it entirely (was spec-optional).
5. **Alert feeds → NWS + AMBER out-of-box; IPAWS operator-supplied COG endpoint.** FEMA gates live IPAWS behind COG credentialing — a federal access fact, not a corner we cut. NWS (open) + AMBER work immediately.
- **SAP / secondary audio (gap 9) is COVERAGE-MANDATORY**, not optional: The incumbent PEG workflow has Multiple Audio Programs (MAP, v7.8+). Build it (second audio PID on cable; audio-track toggle on web; descriptive-audio = same path).
- **EAS attention-tone stripping (gap B)** on OTT sinks: `eas_tone_strip_enabled` on `EgressSinkSpec` (default ON for srt/rtmp/hls/web, OFF for cable udp-ts/sdi). Notch 853/960 Hz bursts; FCC §11.31.

## Slices (per-slice `/audit-lite` → fix → reaudit → fix → push)

### Slice 1 — Per-sink loudness (S11b) + migration 0049 (loudness columns)
- Add to `EgressSinkSpec` (`egress/models.py:94`): `loudness_target_lufs: float|None`, `loudness_regime: Literal["streaming","atsc-a85","ebu-r128","inherit"]="inherit"`, `loudness_tolerance_lufs: float|None`, `eas_tone_strip_enabled: bool=True`.
- Regime defaults: streaming −16 / atsc-a85 −24 / ebu-r128 −23 / inherit→channel `EgressConfig.loudness_target_lufs`.
- Resolver: `effective_target = sink.loudness_target_lufs or REGIME_DEFAULT[regime]`; conform applies per-sink (per-destination, parity decision 1). `HeadendProfile.recommended_loudness_regime="atsc-a85"` advisory; S2/S3 apply sets cable sinks to atsc-a85 explicitly at apply time.
- Generalize `check_streaming_loudness` → `check_loudness(..., standard_label)` (no hardcoded "−16 LUFS" at `stream/loudness.py:97`).
- Migration `0049` adds the 4 columns to `egress_sinks`, nullable + server_default mirroring `inherit`/NULL (un-migrated rows behave as today).
- API: extend egress config write (per-sink fields, `setup_admin`); `GET /channels/{id}/loudness-plan` (`setup_admin`,`support_admin`).
- UI: per-sink regime label (Cable −24 / Streaming −16 / Broadcast −23 / Inherit) + last-measured value on sink/health screens.

### Slice 2 — CEA-708 embedder + live decode-back loop (S11a)
- `Cea708CaptionEmbedder` (3rd `CaptionEmbedder` in `egress/caption_embed.py`) producing `mode="cea-708"` FFmpeg args (608/708 lane); `status="not-verified"` until proven. Confirm/repair the shipped ffmpeg's 708 capability + `doctor` check.
- New persisted `EgressCaptionProofSample` table (0049): channel_id, sampled_at, PASS/FAIL, matched/expected, decoder, proof_boundary, blocker. Rolling/capped (S9 discipline).
- Live decode loop (per ON_AIR channel): tap emitted stream → decode → `evaluate_caption_decode_back` (reuse, `caption_embed.py:125`) → persist sample → `caption_status_provider` closure returns `"on"` iff latest PASS within freshness, else `"not-verified"`. Inject into daemon (`daemon.py:94`) so `caption_status` is finally fed (today hardwired not-verified).
- Fail-closed: no expected cues → not-verified; mismatch → FAIL + S8-alertable condition.
- API: `GET /channels/{id}/caption-status`, `/caption-proofs?limit=N` (`setup_admin`,`meeting_operator`,`support_admin`). Keep the CLI proof tool.
- UI: `ChannelOpsScreen` caption chip (on only when live proof PASS) + proof drawer + caption-mode selector.

### Slice 3 — EAS ingestion → display (S11c), net-new `civiccast/eas/` + migration 0049 (EAS tables)
- Models: `EasCapSource` (ipaws-cap/nws-cap/amber-cap/manual, geocode_filter, severity_floor, poll_seconds), `EasCapAlert` (CAP 1.2 normalized; dedup on (sender,identifier); supersession via references), `EasDisplayMode` (crawl/overlay/forced_slate), `EasDisplayDecision` (resolved action + mandatory `eas_claim="not_eas"` stamp).
- Poll worker per enabled source (supervised, S9 no-unguarded-waits): fetch IPAWS-OPEN / api.weather.gov / state AMBER → parse CAP → filter geocode+severity → dedup/supersede/expire → persist. Fail-closed (fetch/parse error never fabricates/clears an alert; surfaces source-health → S8).
- Decide display mode (severity→mode escalation, decision 3): auto-surface severe+ as overlay/crawl; `forced_slate` requires operator confirm unless source is "official + auto-force". **NO SAME** (decision 4).
- Render via the EXISTING path (do NOT build a parallel one): populate `EmergencyOverlay` / CG `alert` zone → `build_cg_overlay_egress_proof` + `build_branding_filter_plan` (alert zone last) → linear/SDI/UDP + public `GET /api/public/cg/emergency-overlay` (now real, not mock). Clear on expiry/operator via `build_cg_overlay_clear_egress_proof`.
- EAS tone-strip (gap B): apply the 853/960 Hz notch on `eas_tone_strip_enabled` OTT sinks; fixture `same_burst_with_tones.wav` → assert tones removed, program audio survives; build-failing test that no web/OTT sink ships `eas_tone_strip_enabled=false` without explicit override+ack.
- API: `/api/staff/eas/sources` CRUD (`setup_admin`), `/alerts?active=true` (3 roles), `/alerts/{id}/display` + `/clear` (`setup_admin`,`meeting_operator`, audited). Public API never exposes anything labeled "EAS".
- UI: net-new `EasScreen` (Sources / Active alerts / **non-dismissible posture banner**: "CivicCast displays public-safety information … It is not an EAS device …"). Honesty-guard test: build fails if any public string contains "EAS-compliant"/"provides EAS"/"EAS device".

### Slice 4 — SAP / descriptive audio (gap 9) + migration 0050
- `AudioProgramTrack` (track_id, scope asset|channel, target_id, kind primary|sap|descriptive, language BCP-47, source). Migration `0050_secondary_audio` after 0049.
- Cable MPEG-TS: S15 engine muxes secondary audio as additional audio PIDs (TV SAP button works). Web/OTT: selectable audio-track toggle. Descriptive = same path. Per-track loudness normalization (slice 1) applies.
- Done-criteria: DC-SAP1 (2nd PID, TSDuck PID check), DC-SAP2 (web toggle switches audio), DC-SAP3 (descriptive announced as audio-description), DC-SAP4 (each track loudness-normalized).

## Honesty boundary (master §7 — the hard line)
- Captions: claim "CEA-708 embedded + proven by emitted-stream decode-back at the declared boundary." NEVER claim FCC Part 79 compliance.
- Loudness: claim "normalized to the per-sink target + measured back within tolerance." Never claim headend-accepted loudness without rung-4 (S2).
- EAS: NEVER "EAS-compliant / provides EAS / EAS device / EAS relay." Say: "ingests + displays CAP/IPAWS, NWS, AMBER as on-channel information; the mandatory FCC Part 11 relay is the cable operator's certified headend equipment." Every artifact stamps `eas_claim="not_eas"`.

## Stage close
Per-slice `/audit-lite` (fix→reaudit→fix→push). At step-10 completion: `/walkthrough` THEN `/audit-team` to **0/0/0/0/0**, push. Run the real-Postgres gated suite (portable PG) so 0049/0050 are chain-verified, not just SQLite.

## Done criteria (S11 §9, condensed)
Cea708 embedder + live decode loop feeding real `caption_status`; per-sink loudness with cable→−24 default + correct standard label; migration 0049/0050 clean on real PG with back-compat; `civiccast/eas/` ingests CAP/NWS/AMBER, renders via existing overlay, clears correctly; SAP/descriptive on cable PID + web toggle; non-dismissible EAS posture banner + honesty-guard test; no SAME; rung-honest tagging; tests green every tier; 0/0/0/0/0.
