# CivicCast — tvOS starter app

Apple TV SwiftUI app for CivicCast. Runs on tvOS 17+ (Apple TV HD and Apple TV 4K).

- Bundle identifier: `com.civiccast.app.tv`
- Min deployment: tvOS 17.0
- Swift 5.9, SwiftUI, `@main` macro entry point
- AVPlayer (native HLS) via `VideoPlayer` — gets the standard tvOS transport bar for free
- `URLSession` + `Codable` for the API client — no third-party dependencies

## What this app does

1. Reads `APIBaseURL` from `Info.plist` (default `https://civiccast.example.com`).
2. Calls `GET <APIBaseURL>/api/public/app/config`.
3. Renders the station name and a focusable list of channel cards.
4. On Siri Remote select, pushes a `VideoPlayer` that plays the channel's HLS URL.

That is the entire feature surface. See the [parent README](../README.md) for the project-wide rationale.

## Focus engine — how this app handles it

tvOS navigation is driven by the focus engine: every UI element opts in by being focusable, and the platform draws the highlight ring. Notes specific to this codebase:

- `NavigationStack` + `LazyVStack` of `NavigationLink(value:)` rows is the supported pattern in SwiftUI 5+. Each `NavigationLink` is focusable by default on tvOS.
- The channel cards use `.buttonStyle(.card)` which is the canonical tvOS card style — gives the lift + parallax + glow on focus. This style exists on tvOS only; it is one of the two API divergences from the iOS source (the other is `controlSize(.large)` on the loading spinner is rendered bigger by default on tvOS).
- The "Retry" button uses `.buttonStyle(.borderedProminent)` + `.focusable()`. `.borderedProminent` already gets the focus ring on tvOS; the explicit `.focusable()` is belt-and-suspenders.
- `.focusEffectDisabled(false)` (the default) is called out in a comment in `ContentView.swift` so a grep for "focus" finds the relevant code path immediately.

There is **no** custom `FocusState` or `@FocusedValue` in this starter — the focus engine handles linear navigation through the list. Custom focus management (skip-rails, modal traps, focus debugging overlays) is the documented follow-up.

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
│   ├── CivicCastApp.swift     # @main, ConfigStore
│   ├── ContentView.swift      # NavigationStack + focusable card list
│   ├── PlayerView.swift       # VideoPlayer (HLS)
│   ├── CivicCastCore.swift    # NetworkClient, ConfigResponse, Channel (inline copy of ios/ counterpart)
│   └── Info.plist
├── CivicCast.xcodeproj/
│   └── project.pbxproj
└── README.md
```

## Sideload checklist (TestFlight-free internal distribution)

1. In Xcode, set the team under `Signing & Capabilities`.
2. `Product > Archive`.
3. From the Organizer, `Distribute App > Development` or `Ad Hoc`.
4. The Apple TV must be paired and in developer mode. Use Xcode's `Window > Devices and Simulators > Apple TV > Install App` to drag the `.ipa`, or `xcrun devicectl device install app --device <UDID> <path-to-app>`.

## What this starter intentionally does NOT do

These are the documented follow-ups to take the app from starter to App Store (Apple TV App Store) submittable:

- App icon (`tvOS App Icon` — layered front/middle/back, requires Asset Catalog) and top-shelf images (1920×720 / 4640×1440 marketing).
- Privacy Manifest (`PrivacyInfo.xcprivacy`) — required for App Store submission.
- Parental gate — required if any of the channels include content that could trigger age-rating. Apple's tvOS HIG mandates a numeric or button-tap challenge before any external purchase / external sign-in.
- TV-specific accessibility: VoiceOver-on-Siri-Remote labels, Reduce Motion respect, focus-engine debugging in `LLDB > po UIFocusDebugger`.
- DRM (FairPlay) — non-trivial setup for protected streams.
- AirPlay / Multi-User (per-Apple-ID profile state).
- Sign-in / account binding — tvOS uses TVUIKit's `TVTopShelf` and TVAuthenticationController patterns, neither wired here.
- Localized strings — English only.
- Universal Links / deep linking into specific channels.
- VOD / catch-up — only live HLS is wired.

## Backend contract

Same shape as the iOS variant — see [parent README](../README.md) for the canonical JSON.
