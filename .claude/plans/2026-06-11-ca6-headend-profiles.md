# CA-6: Headend Delivery Profiles + UDP/SPTS Cable Sink — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md). CA-1=#141, CA-2=#142, CA-3=#143, CA-4=#144, CA-5=#145.

**Goal:** CivicCast output that a cable headend will actually take: constant-mux-rate SPTS MPEG-TS over UDP (unicast or multicast), with named, citable vendor profiles. GENERIC per Scott's directive — numbers come from published vendor/spec documentation, never from any one station; the operator supplies only what their carriage agreement dictates (destination address/port + mux rate).

**Sources fetched 2026-06-11 (the numbers below cite these, not memory):**
- Comcast MTD product page (comcasttechnologysolutions.com/managed-terrestrial-distribution): SD = MPEG-2; HD = MPEG-2 or MPEG-4; HLS/DASH↔TS-for-QAM translation; ~1G redundant links.
- TelVue KB (telvue.com/knowledgebase: feed-setup-encoder-configuration, preparing-content-for-the-hypercaster, configure-inout-ports, configuring-provue-ip-encoded-output): TS over UDP/RTP, unicast/multicast/SSM; multicast 224.0.0.0–239.255.255.255; IP port 1024–65535; **constant multiplex rate** ("doesn't mean the video elementary stream must be CBR" — mux-level CBR is the requirement); video MPEG-2 or H.264; audio MPEG-1 Layer II / AC-3 / AAC; ATSC + CableLabs compatible.
- Harmonic Spectrum X/XE datasheets (harmonicinc.com/hubfs/datasheet/spectrum-x.pdf, spectrum-xe.pdf): TS ingest over IP; MPEG-2 / MPEG-4 AVC / HEVC; CBR encode supported.
- Leightronix UltraNEXUS-HD (leightronix.com + AV-iQ datasheets): decodes H.264 HD/SD and MPEG-2 SD; file-based content workflow.
- CableLabs VOD Content Spec 1.1 / OpenCable Content Encoding Profiles (account.cablelabs.com, pixeltools tech tip): SD SPTS aggregate (PAT+PMT+video+one audio+data) **≤ 3.75 Mbps**; MPEG-2 MP@ML; **GOP nominally 15** (30fps) / 12 (24fps), **closed to start**; Dolby Digital **192 kbps stereo / 384 kbps 5.1**, 48 kHz.
- Scott's pasted Comcast PEG delivery summary (2026-06-11 session): CBR SPTS MPEG-TS, UDP/IP multicast, MPEG-2 SD / H.264 HD, strict GOP, AC-3/MP2 audio.

**Architecture findings (verified in code):**
- Segments are conformed to `CanonicalProfile` at prepare time (`preparer.build_conform_source_args`: -c:v/-b:v/-g/-c:a/-b:a/-ar/-ac → mpegts). The persistent encoder concats with `-c copy` (or re-encodes only when branding overlays). So profile codecs/GOP belong on `CanonicalProfile`; **mux-level CBR belongs on the sink** via `-muxrate` (mpegts muxer null-pads → constant multiplex rate even over `-c copy`), which matches the TelVue/CableLabs requirement exactly.
- `EgressSinkSpec.extra_output_args` already allowlists `-muxrate`, `-pkt_size`, `-mpegts_flags`, `-flush_packets`, `-max_delay`.
- `local-ts` sink already accepts `udp://`, but with no CBR/multicast semantics; keep it for back-compat, add a first-class `udp-ts` kind.

## Pieces

1. **`civiccast/egress/headend.py`** (new, TDD):
   - `HeadendProfile` (pydantic, extra=forbid): `profile_id`, `label`, `vendor`, `source_urls` (citations), `canonical_profile: CanonicalProfile`, `muxrate_kbps`, `transport: udp-unicast|udp-multicast|file-drop`, `pkt_size=1316` (7×188), `mpegts_extra_args`, `operator_must_supply: list[str]`, `not_claimed: list[str]` (honesty: "built from published specs; not field-proven at a headend until the LPM beta").
   - Registry `HEADEND_PROFILES`:
     - `generic-udp-spts` — baseline any-headend: H.264 1280×720p30 @ 5000k video, AC-3 192k 48kHz stereo, GOP 30 (1s, closed via conform), muxrate 8000k, udp-unicast.
     - `comcast-mtd-sd` — MPEG-2 (mpeg2video) 720×480@30, video 3180k, AC-3 192k 48k, **GOP 15**, **muxrate 3750k** (CableLabs SD aggregate), udp-multicast.
     - `comcast-mtd-hd` — H.264 (libx264) 1920×1080@30, video 10000k, AC-3 384k, GOP 30, muxrate 12000k (operator_must_supply: confirm rate from carriage agreement), udp-multicast.
     - `telvue-hypercaster-ip` — H.264 1280×720p30 @ 5000k, MP2 (mp2) 192k OR AC-3 — pick AC-3 192k default, muxrate 8000k, udp (unicast or multicast; port must be 1024–65535 per TelVue KB), udp-unicast default.
     - `harmonic-spectrum-ts` — H.264 1080p30 @ 8000k, AC-3 192k, muxrate 10000k, udp-unicast.
     - `leightronix-file-drop` — H.264 HD file handoff (UltraNEXUS decodes H.264 HD/SD, MPEG-2 SD); transport file-drop → reuses existing `file` sink / cable file-package lane; no muxrate.
   - `apply_headend_profile(config, profile, *, destination_uri, muxrate_kbps_override=None, label=None) -> EgressConfig`: returns a new config with the profile's canonical_profile and ONE udp-ts (or file) sink carrying `-muxrate {n}k` + profile mpegts args; validates destination scheme/transport match (multicast profiles require a 224.0.0.0/4 host).
2. **`udp-ts` sink kind** (models.py `EgressSinkKind` + sinks.py `UdpTsSink`, TDD):
   - Requires `udp://host:port`; port 1..65535; appends `pkt_size=1316` to the URL query when absent (overridable via existing query); appends `ttl` only if present in spec query already (no new columns).
   - Multicast detection (host in 224.0.0.0/4) reflected in `describe()`; unicast also valid (TelVue accepts both).
   - `output_args()` = extra_output_args + `-f mpegts <target>`; counts as realtime sink in `runtime.build_persistent_encoder_args` (add to the `-re` set) and anywhere `local-ts` is special-cased (grep: daemon/service/health).
3. **Staff API** (egress/router.py, TDD): `GET /api/staff/egress/headend-profiles` (list, sanitized full registry) + `POST /api/staff/egress/channels/{channel_id}/config/headend-profile` (body: profile_id, destination_uri, muxrate_kbps optional, keep_existing_sinks: bool=false) — setup_admin-gated, upserts through the existing store, 404 unknown profile, 422 destination/transport mismatch, 503 storage.
4. **Console** (ChannelOpsScreen): "Cable headend delivery" panel — profile select (label + vendor + operator_must_supply hints), destination address input, optional mux-rate override, Apply button → new client fn; shows the applied sink summary from config. e2e in channel-app-config.spec.ts pattern.
5. **Docs:** runbook section "Sending a channel to a cable headend" (profile table w/ source citations, udp unicast vs multicast, firewall/TTL notes, TSDuck verification pointer = CA-7); CAPABILITIES "Cable delivery" row updated (udp-ts production-wired, file-package unchanged, headend field proof pending CA-8/LPM); OpenAPI regen.

## Steps
branch `work/ca6-headend-profiles` → headend module TDD (profiles registry + apply) → udp-ts sink TDD (incl. realtime `-re` + allowlist passthrough) → staff API TDD → console panel + client fn + e2e → docs + OpenAPI regen → builds + Playwright (operator a11y suite) + full backend gate → PR `refs cable-automation CA-6` → merge.

**Migration 0034 required** (verified): `egress_sinks_kind_check` CHECK pins `kind IN ('srt','rtmp','local-ts','file','sdi')` — extend to include `'udp-ts'`; advance the single-head pin in tests/live/test_real_postgres.py to 0034.
