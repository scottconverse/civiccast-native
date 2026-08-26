# CivicCast Native OTT Apps

Closes S12 (`docs/spec/3.0/sections/S12-ott-apps.md`) §11's "4 codebases →
6 storefronts" build matrix. Four native codebases, each independently
buildable and CI-built on hosted runners — see
`.github/workflows/ci-ott-apps.yml`.

## Layout (canonical, de-duplicated)

| Codebase | Path | Language | Storefront(s) | Devices |
|---|---|---|---|---|
| Roku | `roku/` | BrightScript + SceneGraph | Roku Channel Store | Roku players + Roku TVs |
| Apple | `ios/`, `tvos/`, `apple-shared/` | Swift 5.9 + SwiftUI | Apple App Store | iPhone/iPad + Apple TV |
| Android | `android/` (`:tv-app` flavors `tv`/`firetv`, `:mobile-app`) | Kotlin | Google Play (TV + mobile) + Amazon Appstore | Android TV/Google TV + Fire TV + phones/tablets |
| Web/HTML | `tizen/`, `webos/`, `web-shared/` | HTML/JS (native `<video>`, no framework) | Samsung Tizen Store + LG Content Store | Samsung Tizen TVs + LG webOS TVs |

**This is the S12 de-duplication.** Before this change, `android-tv/` and
`fire-tv/` were two entire copied Gradle projects (own wrapper, own
`settings.gradle.kts`) differing only in `applicationId` and a few manifest
lines; `ios/` and `tvos/` each carried their own byte-for-byte-near-identical
copy of `CivicCastApp.swift`/`CivicCastCore.swift`; and Tizen/webOS had no
source at all. Now:

- `android/` is one Gradle project. `:tv-app` shares 100% of its Kotlin
  source across the `tv` and `firetv` product flavors — only the real
  per-storefront differences (Amazon hardware hint, extra launcher
  intent-filter, leanback `required` flag) live in per-flavor manifest
  overlays (`android/tv-app/src/tv/`, `android/tv-app/src/firetv/`).
- `apple-shared/CivicCastApp.swift` and `apple-shared/CivicCastCore.swift`
  are each a single file, referenced by both `ios/CivicCast.xcodeproj` and
  `tvos/CivicCast.xcodeproj` via a `SOURCE_ROOT`-relative file reference —
  not copied. Per-target UI (`ContentView.swift`, `PlayerView.swift`) stays
  per-target on purpose; tvOS focus-engine layout and iOS touch layout are
  legitimately different.
- `web-shared/civiccast-player.js` is the single playback client for both
  Tizen and webOS. The build copies it into each platform's package
  directory (a `.gitignore`'d build artifact, not a second source file) —
  see `web-shared/civiccast-player.js`'s header.

`app-platform-shells/` (the pre-existing generic HTML5 shells, one level up
in `civiccast/apps/`) is a **different, deliberately separate** artifact: a
thin contract-conformance reference (renders text, does not play video) that
demos the `/api/public/app/config` contract for all seven `AppTarget`
values and backs Roku Direct Publisher's MRSS-only path. It is not a
duplicate of the native/Web-app sources here — see its own README.

## Real API contract (all six targets, no simplified stand-in)

Every target below calls the REAL CivicCast app-platform contract
(`civiccast/app_platform/models.py`, `civiccast/app_platform/router.py`) —
the same one `civiccast/apps/app-platform-shells/src/shell.mjs` uses, not a
flattened per-platform projection:

1. `GET <API_BASE_URL>/api/public/app/config` → `StationAppConfig`:
   ```json
   {
     "station_name": "Lansing Public Media",
     "default_channel_id": "public",
     "channels": [
       {
         "channel_id": "public",
         "branding": { "display_name": "Public Channel", "color": "#2458A6" },
         "live_state_url": "/api/public/app/channels/public/live"
       }
     ]
   }
   ```
2. `GET <API_BASE_URL><channel.live_state_url>` → `LiveState`:
   ```json
   { "state": "on_air", "playback_url": "https://.../public/index.m3u8" }
   ```
   `playback_url` is the HLS manifest handed to the platform's native
   player (AVPlayer / Media3 ExoPlayer / Roku `Video` node / `<video>`).

`live_state_url` is a path **relative to the API host**, not an absolute
URL — every client resolves it against its configured base URL before
fetching. See `civiccast/apps/app-platform-shells/fixtures/
station-app-config.sample.json` for a full worked example.

## What these are NOT (the documented follow-up)

Starter source trees, NOT store-ready submissions. Each target's own
README lists its full follow-up checklist; the common items across all six
are: branded artwork (placeholders are solid-color rectangles/PNGs), image
loading for posters/logos, search (Roku Channel Store and Google Play TV
both expect one), caption/audio-track manual-override UI, deep-link
routing, and accessibility polish.

## CI

`.github/workflows/ci-ott-apps.yml` builds all four codebases on hosted
GitHub runners (`ubuntu-latest` for Roku/Android/Tizen/webOS, `macos-latest`
for Apple), with per-platform artifacts uploaded and honest reporting for
the (currently theoretical) case where the headless Tizen Studio install
itself fails on a given run and the job falls back to static `config.xml`
validation instead of a real `.wgt` — see `tizen/README.md`. Triggers on
changes under this directory plus `workflow_dispatch`.

## Build matrix (developer machine requirements, for local work outside CI)

| Target | Toolchain | OS |
|---|---|---|
| Roku | `zip` (or `roku-deploy`) + a Roku device on the LAN in dev mode for sideload | any |
| iOS / tvOS | Xcode 15+ | macOS 13.5+ |
| Android (`tv`/`firetv`/mobile) | `gradle` 8.7+ (wrapper checked in) + Android SDK | any |
| Tizen | Tizen Studio CLI (installs and packages headless on hosted CI — see `tizen/README.md`) | any |
| webOS | `@webosose/ares-cli` (npm, no device needed for packaging) | any |
