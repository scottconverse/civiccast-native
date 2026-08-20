# CivicCast — iOS starter app

iPhone + iPad SwiftUI app for CivicCast. Runs on iOS 17+.

- Bundle identifier: `com.civiccast.app`
- Min deployment: iOS 17.0
- Universal (iPhone + iPad)
- Swift 5.9, SwiftUI, `@main` macro entry point
- AVPlayer (native HLS) for playback
- `URLSession` + `Codable` for the API client — no third-party dependencies

## What this app does

1. Reads `APIBaseURL` from `Info.plist` (default `https://civiccast.example.com`).
2. Calls `GET <APIBaseURL>/api/public/app/config`.
3. Renders the station name and a list of channels.
4. On tap, pushes an AVPlayer view that plays the channel's HLS URL.

That is the entire feature surface. See the [parent README](../README.md) for the project-wide rationale.

## Build

You need:

- macOS 13 Ventura or later
- Xcode 15 or later
- Apple Developer account (for on-device install; the simulator does not require one)

### Build for the simulator

```bash
cd ios/
xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'platform=iOS Simulator,name=iPhone 15' \
    build
```

### Install into the simulator

```bash
# Make sure a simulator is booted:
xcrun simctl boot "iPhone 15" || true
open -a Simulator

# Build, then install + launch:
xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'platform=iOS Simulator,name=iPhone 15' \
    -derivedDataPath ./build \
    build

xcrun simctl install booted ./build/Build/Products/Debug-iphonesimulator/CivicCast.app
xcrun simctl launch booted com.civiccast.app
```

### Build for an iPhone over USB

```bash
xcodebuild \
    -project CivicCast.xcodeproj \
    -scheme CivicCast \
    -configuration Debug \
    -destination 'generic/platform=iOS' \
    -allowProvisioningUpdates \
    build
```

Then install via Xcode (`Window > Devices and Simulators`, drag the `.app`) or via `xcrun devicectl device install app --device <UDID> <path-to-app>`.

### Open in Xcode

```bash
open CivicCast.xcodeproj
```

Pick the `CivicCast` scheme and a destination, then ⌘R.

## Configure the API host

Override `APIBaseURL` in `CivicCast/Info.plist` to point at a non-production backend:

```xml
<key>APIBaseURL</key>
<string>http://192.168.1.10:8080</string>
```

A plain-HTTP URL also needs an App Transport Security exception. Either:

- Add a per-domain entry under `NSExceptionDomains` in `Info.plist`, or
- For local-only testing, temporarily set `NSAllowsArbitraryLoads` to `true` (production builds MUST ship with ATS enforced).

The default `Info.plist` ships with an explicit allow-entry for `civiccast.example.com` as a documentation anchor.

## File layout

```
ios/
├── CivicCast/
│   ├── CivicCastApp.swift     # @main, ConfigStore (ObservableObject)
│   ├── ContentView.swift      # NavigationStack + channel list
│   ├── PlayerView.swift       # AVPlayer (HLS) via VideoPlayer
│   ├── CivicCastCore.swift    # NetworkClient, ConfigResponse, Channel
│   └── Info.plist
├── CivicCast.xcodeproj/
│   └── project.pbxproj
└── README.md
```

## Sideload checklist (TestFlight-free internal distribution)

1. In Xcode, set the team under `Signing & Capabilities`.
2. `Product > Archive`.
3. From the Organizer, `Distribute App > Ad Hoc` (or `Development`).
4. Export the `.ipa`; install with `xcrun devicectl device install app` or with Apple Configurator 2.

## What this starter intentionally does NOT do

These are the documented follow-ups to take the app from starter to App Store submittable:

- App icon / launch image (Asset Catalog) — the project compiles without one but the springboard tile will be the default white square.
- Privacy Manifest (`PrivacyInfo.xcprivacy`) — required for App Store submission in 2024+.
- Accessibility audit (VoiceOver labels, Dynamic Type review, contrast).
- Localized strings — English only.
- Push notifications / EAS alert integration.
- DRM (FairPlay), offline downloads, AirPlay, picture-in-picture, background audio.
- Sign-in (account binding, parental controls / age gates).
- Crash reporting + analytics.
- Universal Links / deep linking into specific channels.
- VOD / catch-up — only live HLS is wired.
- Auth-protected channels — `/api/public/app/config` is the public projection only.

## Backend contract

The app expects this simplified JSON shape (matches the Android variants — see [parent README](../README.md) for the full schema mapping note):

```json
{
  "station": { "name": "City of Example Civic TV", "logoUrl": "https://cdn.example.com/logo.png" },
  "channels": [
    { "id": "ch1", "name": "Government Channel", "hlsUrl": "https://cdn.example.com/hls/ch1/master.m3u8", "posterUrl": "https://cdn.example.com/posters/ch1.jpg" }
  ]
}
```
