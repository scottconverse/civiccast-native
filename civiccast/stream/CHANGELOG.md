# civiccast.stream — Changelog

All notable changes to the streaming origin module are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows the parent `civiccast` package version.

## [Unreleased]

### Changed

- H.264 FFmpeg CLI requests are resolved against the exact runtime binary in
  NVENC -> Media Foundation -> OpenH264 -> libx264 order, each candidate
  proven usable by a one-frame null encode before selection ("advertised" is
  not "usable": nvenc-enabled builds list h264_nvenc even with no NVIDIA
  runtime). libx264 (GPL) is strictly last and reachable only when the
  station's own binary carries it -- the pinned LGPL pack does not, so
  native-line resolution can never select it. No silent fallback when the
  binary exposes no usable candidate. `-profile:v` is translated to the
  resolved encoder's dialect at the same spawn boundary (h264_mf accepts no
  named profile values, so the option is omitted there; libopenh264 spells
  baseline as `constrained_baseline`) -- measured live against the pinned
  pack binary.

### Added
- `civiccast.stream.cdn.cloudflare_r2.CloudflareR2Adapter`: optional
  Cloudflare R2 storage adapter for stations that need the documented
  DDoS-protection CDN path.

## [0.2.0] — Sprint 0.2 Streaming origin

### Added
- `civiccast.stream.config`: `RenditionConfig` dataclass, `ABR_LADDER` (1080p / 720p / 480p / 240p),
  `SLATE_RENDITION`, HLS constants. All values frozen at import time.
- `civiccast.stream._ffmpeg`: Thin subprocess wrapper (`run_ffmpeg`, `check_ffmpeg`).
  `FfmpegNotFoundError` / `FfmpegError` exceptions. Version range enforcement (≥ 4.4).
  Called by `civiccast doctor` to report ffmpeg status.
- `civiccast.stream.manifest`: `build_multivariant_manifest` / `write_multivariant_manifest`.
  RFC 8216-compliant HLS multivariant playlist with BANDWIDTH, RESOLUTION, CODECS attributes.
- `civiccast.stream.slate`: `generate_slate` — lavfi color+drawtext slate with branded error
  message; falls back to plain-color slate if drawtext / fontconfig unavailable.
- `civiccast.stream.packager`: `pack_vod_asset` (encode → all 5 variants → manifest) and
  `pack_slate_fallback` (slate-only manifest for broken-media orchestration). `PackagingError`
  exception for clean error handling without unhandled crashes.
- `civiccast.stream.cdn.CDNAdapter`: Protocol for all CDN adapters.
- `civiccast.stream.cdn.bunny.BunnyCDNAdapter`: BunnyCDN Storage API adapter (v1 default per ADR 0006).
- `civiccast.stream.cdn.stub.StubCDNAdapter`: Local filesystem adapter for testing.
- `civiccast doctor`: Extended to report ffmpeg version and supported status.
- Broken-media regression suite: 5 pathological asset categories (empty, truncated, garbage,
  audio-only, slate-always-present). Unit tests mock ffmpeg; integration tests use real ffmpeg.
- `httpx>=0.27.0` added to main production dependencies (BunnyCDN adapter).

### Design decisions recorded
- ADR 0006 — BunnyCDN as v1 default CDN (Cloudflare R2 + CDN documented as alternate).
- ADR 0007 — HLS packager: Python + ffmpeg subprocess + slate-as-variant (Sprint 0.1 branch).

### Not in this release
- Live ingest (RTMP / RTSP / NDI / SRT) — Sprint 0.4.
- Per-channel ABR ladder overrides — Sprint 0.3.
- CDN upload orchestration / retry in publish pipeline — Sprint 0.7.
- Cloudflare R2 live-credential proof remains operator-gated.
