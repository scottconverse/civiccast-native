# CivicCast — tvOS app

Apple TV SwiftUI app for CivicCast. Runs on tvOS 17+ (Apple TV HD and Apple TV 4K).

- Bundle identifier: `com.civiccast.app.tv`
- Min deployment: tvOS 17.0
- Swift 5.9, SwiftUI, `@main` macro entry point
- AVPlayer (native HLS) via `VideoPlayer` — gets the standard tvOS transport bar for free
- `URLSession` + `Codable` for the API client — no third-party dependencies

## What this app does

1. Stores the station HTTPS address in the app; `APIBaseURL` in `Info.plist`
   supplies its initial value.
2. Browses and searches live channels and published station replays, with
   station logos and replay posters.
3. Plays HLS through the tvOS player and its native transport and caption
   controls.
4. Opens `civiccast://channel/<id>` and `civiccast://replay/<id>` links.

See the [parent README](../README.md) for the shared API contract.

## Focus engine — how this app handles it

tvOS navigation is driven by the focus engine: every UI element opts in by being focusable, and the platform draws the highlight ring. Notes specific to this codebase:

- `NavigationStack` + `LazyVStack` of `NavigationLink(value:)` rows is the supported pattern in SwiftUI 5+. Each `NavigationLink` is focusable by default on tvOS.
- The channel cards use `.buttonStyle(.card)` which is the canonical tvOS card style — gives the lift + parallax + glow on focus. This style exists on tvOS only; it is one of the two API divergences from the iOS source (the other is `controlSize(.large)` on the loading spinner is rendered bigger by default on tvOS).
- The "Retry" button uses `.buttonStyle(.borderedProminent)` + `.focusable()`. `.borderedProminent` already gets the focus ring on tvOS; the explicit `.focusable()` is belt-and-suspenders.
- `.focusEffectDisabled(false)` (the default) is called out in a comment in `ContentView.swift` so a grep for "focus" finds the relevant code path immediately.

There is no custom `FocusState` or `@FocusedValue`; the focus engine handles
linear navigation through the list and station setting.

## Build

You need:

- macOS 13 Ventura or later
- Xcode 15 or later (the tvOS 17 SDK ships with Xcode 15)
- For on-device install: an Apple Developer account + an Apple TV in developer mode, paired with Xcode

### Build for the simulator

```bash
cd tvos/
xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'platform=tvOS Simulator,name=Apple TV' \
    build
```

### Install + run in the simulator

```bash
xcrun simctl boot "Apple TV" || true
open -a Simulator

xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'platform=tvOS Simulator,name=Apple TV' \
    -derivedDataPath ./build \
    build

xcrun simctl install booted ./build/Build/Products/Debug-appletvsimulator/CivicCast.app
xcrun simctl launch booted com.civiccast.app.tv
```

### Build for an Apple TV (on device)

1. Connect the Apple TV to the same Wi-Fi as your Mac.
2. In tvOS: `Settings > Apps > Developer Apps` — enable developer mode.
3. In Xcode: `Window > Devices and Simulators`, pair with the Apple TV (Code shown on TV).
4. Open the project:

   ```bash
   open CivicCast.xcodeproj
   ```

5. Pick the `CivicCast` scheme, pick the paired Apple TV as the destination, ⌘R.

Command-line equivalent:

```bash
xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'platform=tvOS,id=<TV_UDID>' \
    -allowProvisioningUpdates \
    build
```

## Configure the API host

Same as the iOS target — override `APIBaseURL` in `CivicCast/Info.plist`. For plain-HTTP dev backends add an ATS exception under `NSExceptionDomains`. The default `Info.plist` ships with `civiccast.example.com` explicitly allowed.

## File layout

```
tvos/
├── CivicCast/
│   ├── ContentView.swift      # NavigationStack + focusable card list (tvOS-specific)
│   ├── PlayerView.swift       # VideoPlayer (HLS) (tvOS-specific)
│   └── Info.plist
├── CivicCast.xcodeproj/
│   └── project.pbxproj        # references ../apple-shared/*.swift directly (SOURCE_ROOT-relative)
└── README.md

../apple-shared/                # SHARED with ios/ — single canonical copy, not a per-target fork
├── CivicCastApp.swift          # @main, ConfigStore
├── CivicCastCore.swift         # NetworkClient, ConfigResponse, Channel, LiveState
└── ColorHex.swift              # Color(hex:) for ChannelBranding.color
```

## Sideload checklist (TestFlight-free internal distribution)

1. In Xcode, set the team under `Signing & Capabilities`.
2. `Product > Archive`.
3. From the Organizer, `Distribute App > Development` or `Ad Hoc`.
4. The Apple TV must be paired and in developer mode. Use Xcode's `Window > Devices and Simulators > Apple TV > Install App` to drag the `.ipa`, or `xcrun devicectl device install app --device <UDID> <path-to-app>`.

## Platform publication

The app includes CivicCast icon artwork. Store signing, top-shelf marketing
art, privacy declarations, localization, protected channels, and device-specific
accessibility review belong to the platform publication process. The viewer
consumes the public station catalog; it does not log viewers in to protected
channels.

## Backend contract

Same real `StationAppConfig` / `LiveState` contract as the iOS variant (both
targets share `../apple-shared/CivicCastCore.swift`) — see that file's
header for the exact shapes, and [parent README](../README.md) for the
schema note shared across all six S12 targets.
