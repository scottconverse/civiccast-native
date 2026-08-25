# civiccast.stream — HLS Streaming Origin

Sprint 0.2 module. Encodes source video to an adaptive HLS ladder and
uploads segments to the configured CDN.

## What it does

- Accepts a source video file and produces an HLS output tree of up to five
  variants — the content rungs the source can actually fill, plus the slate:
  - **1080p** — 4.5 Mbps, H.264 High, AAC 128 kbps
  - **720p** — 2.5 Mbps, H.264 Main, AAC 128 kbps
  - **480p** — 1.0 Mbps, H.264 Main, AAC 96 kbps
  - **240p** — 350 kbps, H.264 Baseline, AAC 64 kbps
  - **Slate** — 200 kbps, always present, player falls back here if all content variants fail
- **Never upscales.** `select_ladder` (in `config.py`) drops every rung taller
  than the source and pins the top rung to the source's own resolution, so a
  640x360 clip publishes `360p` + `240p` + slate rather than spending ~81% of
  the encode inventing 1080p and 720p pixels. A 1080p (or larger) source still
  gets the whole four-rung ladder; the ladder's top rung is a product cap, so a
  4K source publishes at 1080p and below. When the source dimensions cannot be
  read, the full ladder is used unchanged — the packager never guesses.
- Writes output to a local directory; CDN upload is a separate adapter step.
- Applies optional fractional trim windows (`trim_in_seconds`,
  `trim_out_seconds`) before encoding content renditions. Slate generation is
  unchanged and always remains available as the fallback variant.
- Accepts caption sidecars from `civiccast.captions.hls`; caption tracks are
  emitted as segmented WebVTT playlists under `captions/{language}/` and
  advertised in the multivariant manifest as HLS `SUBTITLES` renditions.
- Sprint 0.2 ships VOD only. Live ingest lands at Sprint 0.4.

## Architecture

See [ADR 0007](../../docs/adr/0007-hls-packager-design.md) for design decisions
(Python + ffmpeg subprocess, slate-as-variant, 4-rendition ABR ladder).

See [ADR 0006](../../docs/adr/0006-cdn-provider.md) for CDN choice
(BunnyCDN v1 default; Cloudflare R2 + CDN as DDoS-protection-mode alternate).

## Quick start

```python
from pathlib import Path
from civiccast.stream import pack_vod_asset, pack_slate_fallback, PackagingError

try:
    result = pack_vod_asset(
        input_path=Path("/recordings/meeting.mp4"),
        output_dir=Path("/hls_output/meeting_2026-01-15"),
        trim_in_seconds=1.5,
        trim_out_seconds=3600.333,
    )
    print(f"Manifest at: {result.manifest_path}")
except PackagingError as exc:
    # Input was unreadable — serve the slate instead.
    fallback = pack_slate_fallback(Path("/hls_output/meeting_2026-01-15"))
    print(f"Serving slate manifest: {fallback.manifest_path}")
```

## CDN upload

```python
from civiccast.stream.cdn.bunny import BunnyCDNAdapter

adapter = BunnyCDNAdapter(
    storage_zone_name="myzone",
    access_key="...",          # from operator config
    cdn_hostname="myzone.b-cdn.net",
)

# Upload every file in the output directory tree.
for f in result.output_dir.rglob("*"):
    if f.is_file():
        relative_key = f.relative_to(result.output_dir).as_posix()
        adapter.upload_file(f, f"meetings/2026-01-15/{relative_key}")
```

## Captions

After captions have been stabilized and reviewed, attach them to an HLS package
before CDN upload:

```python
from civiccast.captions import CaptionHlsTrack, attach_caption_tracks_to_package

attach_caption_tracks_to_package(
    result,
    [CaptionHlsTrack(cues=approved_cues, language="en", name="English")],
)
```

This writes `captions/en/playlist.m3u8` plus `segNNN.vtt` WebVTT files and
rewrites `playlist.m3u8` with `EXT-X-MEDIA TYPE=SUBTITLES`. Empty early
segments are kept so subtitle timing stays aligned with the video timeline.

See `USER-MANUAL.md §CDN Configuration` for full BunnyCDN and Cloudflare R2 setup instructions.

## Prerequisites

- ffmpeg ≥ 4.4 on PATH (`apt install ffmpeg` on Ubuntu/Debian)
- Verify: `civiccast doctor` reports ffmpeg version as supported

## Module layout

```
civiccast/stream/
├── __init__.py        # public API
├── _ffmpeg.py         # ffmpeg subprocess wrapper (do not call subprocess directly)
├── config.py          # ABR ladder constants, RenditionConfig
├── manifest.py        # HLS multivariant manifest builder
├── slate.py           # Slate variant generator
├── packager.py        # VOD packager: pack_vod_asset(), pack_slate_fallback()
└── cdn/
    ├── __init__.py    # CDNAdapter protocol
    ├── bunny.py       # BunnyCDNAdapter (v1 default)
    ├── cloudflare_r2.py # CloudflareR2Adapter (optional R2/CDN path)
    └── stub.py        # StubCDNAdapter (testing only)
```

## Test coverage

```
tests/stream/
├── test_config.py                          # ABR ladder constants
├── test_ffmpeg.py                          # subprocess wrapper + version parsing
├── test_manifest.py                        # multivariant manifest assembly
├── test_packager.py                        # VOD packager logic
├── test_cdn_bunny.py                       # BunnyCDN adapter + stub adapter
├── test_cdn_cloudflare_r2.py               # Cloudflare R2 adapter
└── broken_media/
    └── test_broken_media_suite.py          # 30 sanitized failure modes
```

Run: `pytest tests/stream/`

Integration tests (require ffmpeg): `pytest tests/stream/ -m integration`

Coverage target: 95% (streaming origin — channel outages are the blast radius per CLAUDE.md).
