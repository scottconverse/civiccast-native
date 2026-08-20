# CivicCast — Fire TV

Starter Leanback app for Amazon Fire TV (Fire OS). Shares almost all code with `android-tv/` — Fire OS is Android with Amazon services layered on, and Leanback works identically. The deltas are in the manifest.

## Targets

- **Min SDK**: 26
- **Target SDK**: 34
- **Form factor**: Fire TV (Stick, Cube, Edition TVs). The dual intent-filter declaration also makes it launchable on Fire Tablets if Amazon ever publishes a combined listing.

## How this differs from `android-tv/`

Code: package renamed to `com.civiccast.firetv`; everything else identical.

Manifest:

- `<uses-feature android:name="amazon.hardware.fire_tv" android:required="false" />` — Amazon's targeting hint. `required="false"` means the same APK can sideload onto an emulator for development.
- The launcher activity declares **both** `LEANBACK_LAUNCHER` and `MAIN/LAUNCHER` intent-filters. Amazon's documentation recommends declaring both so the app surfaces on every Fire OS variant.
- `android.software.leanback` is `required="false"` (rather than `true` as on android-tv) so the APK doesn't fail to install on older Fire OS images that don't advertise the feature.

Resources: `app_banner` placeholder is identical (320x180). Amazon's storefront also requires a 1280x720 banner — that's a store-listing asset, not an in-APK resource.

## Prerequisites

Same as the Android variants — JDK 17, Android SDK with `android-34`, build-tools 34.0.0+. Bootstrap the wrapper jar once with `gradle wrapper --gradle-version 8.7`.

## Build

```bash
./gradlew assembleDebug
./gradlew assembleDebug -PapiBaseUrl=https://civiccast.staging.example.com
```

APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## Sideload to a Fire TV device

Enable ADB on the Fire TV (Settings → My Fire TV → Developer Options → ADB debugging ON; Apps from Unknown Sources ON).

```bash
adb connect <fire-tv-ip>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.civiccast.firetv.debug/com.civiccast.firetv.MainActivity
```

To uninstall:

```bash
adb uninstall com.civiccast.firetv.debug
```

## What's inside

```
app/src/main/
├── AndroidManifest.xml           Amazon feature flag, dual launcher intent-filters
├── java/com/civiccast/firetv/
│   ├── ConfigResponse.kt         mirrors android-tv
│   ├── NetworkClient.kt          mirrors android-tv
│   ├── MainActivity.kt           mirrors android-tv
│   ├── MainBrowseFragment.kt     mirrors android-tv
│   ├── ChannelCardPresenter.kt   mirrors android-tv
│   └── PlayerActivity.kt         mirrors android-tv
└── res/
    ├── values/                   strings + Leanback themes (theme renamed)
    ├── drawable/app_banner.xml   320x180 launcher banner (placeholder)
    └── mipmap-mdpi/              placeholder launcher icon
```

## Follow-ups to reach Appstore-ready

- 1280x720 store banner + 1920x1080 hero asset for the Amazon Appstore listing.
- Branded `app_banner.xml` → PNG/WebP at 320x180 with real artwork.
- Amazon IAP if subscription/paywall is added (com.amazon.device.iap).
- Amazon Device Messaging (ADM) for push if needed.
- Amazon's pre-publishing validation (App Testing Service) — Fire TV's hardware capability matrix is stricter than generic Android TV.
- Recommendation card service (Fire TV row-based recommendations).
- Voice-search integration via Alexa Voice Service (search for "Fire TV catalog integration").
- Signed release build, ProGuard rules.
- Accessibility — verify D-pad focus order; Fire TV remotes lack a touch surface, so every interaction must be reachable via the directional pad.
