# CivicCast Native OTT Apps

Closes S12 D1 — the "native OTT app source is absent" gap. Six starter
native app source trees, each independently buildable with the standard
toolchain for its platform.

## Targets

| Target | Path | Language | SDK / Min | Build |
|---|---|---|---|---|
| Roku | `roku/` | BrightScript + SceneGraph | OS 12.0+ | zip + sideload via dev portal |
| iOS / iPadOS | `ios/` | Swift 5.9 + SwiftUI | iOS 17 | `xcodebuild` |
| Apple TV (tvOS) | `tvos/` | Swift 5.9 + SwiftUI | tvOS 17 | `xcodebuild` |
| Android mobile | `android-mobile/` | Kotlin + Material 3 | API 24 | `./gradlew assembleDebug` |
| Android TV | `android-tv/` | Kotlin + Leanback | API 26 | `./gradlew assembleDebug` |
| Fire TV | `fire-tv/` | Kotlin + Leanback + Amazon | API 26 | `./gradlew assembleDebug` |

Each target ships:
- Real source that the platform toolchain will compile + package.
- A fetch of `/api/public/app/config` from the CivicCast public API.
- Render of the station name + a channel list.
- HLS playback of the selected channel via the platform's native player.
- A per-target `README.md` with the exact build + sideload command.

## What these are NOT (the documented follow-up)

These are starter source trees, NOT store-ready submissions. Each target
README lists its own follow-up checklist, but the common items across all
six are:

- Branded artwork: app icons, splash screens, store hero images. The
  starters ship placeholder icons (grayscale rectangles) so the build
  succeeds; they MUST be replaced before store submission.
- Store-policy compliance: age-gating, parental controls, content
  ratings, privacy manifests (Apple), Amazon's Fire TV requirements.
- Search interfaces: Roku Channel Store requires a search surface
  for VOD channels; Google Play TV recommends one.
- Caption + audio-track UI: the platform players surface these for
  free, but a "manual override" picker is store-recommended for
  accessibility.
- Deep linking: each platform has its own deep-link protocol
  (Roku `roSGNode` `args`, Apple Universal Links, Android intent
  filters) — starters pass launch args through but don't route on
  them yet.

## Architecture notes

### Shared code policy

Each target keeps its own copy of the network / config-decoder code
(~70-120 LOC per target). Promotion to a real shared module (a Gradle
`:common` library for the Android variants, a SwiftPM package for the
Apple variants) is deferred until the shared surface crosses ~300 LOC.
The decision and rationale are documented in each target's source
header.

### Why HTML5 shells + native source

The existing `civiccast/apps/app-platform-shells/` ships browser-rendered
HTML5 shells that share a runtime — that path supports Roku Direct
Publisher (MRSS) and the incumbent PEG platform "Branded Streaming App" packaging
style for stations that want zero engineering. The native source trees
here ship the OTHER path: a real platform-idiomatic app a station can
take to the platform store, with the full feature surface (live + VOD +
schedule + chapters + captions) that exceeds Direct Publisher's
capability ceiling.

### API contract

All six targets call `GET /api/public/app/config` and expect a JSON
shape:

```json
{
  "station_name": "Lansing Public Media",
  "channels": [
    {"title": "Public", "hls_url": "https://.../public/index.m3u8"},
    {"title": "Education", "hls_url": "https://.../education/index.m3u8"},
    {"title": "Government", "hls_url": "https://.../gov/index.m3u8"}
  ]
}
```

This is a SIMPLIFICATION of the full `StationAppConfig` schema the
existing app-platform contract returns — the projection from
`StationAppConfig.channels[].outputs[kind=hls].target` to the flat
`Channel.hls_url` lives at the gateway. Documenting the projection
(and reconciling whether to ship the gateway endpoint or have every
client traverse the full schema) is a future-slice decision.

## Build matrix (developer machine requirements)

Each target's build requires its own toolchain. None of them can be
built from the dev box this directory lives on without the SDK.

| Target | Toolchain | OS |
|---|---|---|
| Roku | Just `zip` + a Roku device on the LAN in dev mode | any |
| iOS / tvOS | Xcode 15+ | macOS 13.5+ |
| Android variants | Android Studio Hedgehog+ or `gradle` 8.7+ + Android SDK | any |

CI (a follow-up) would add per-target build jobs gated on the relevant
runner OS.
