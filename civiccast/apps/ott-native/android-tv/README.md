# CivicCast — Android TV

Starter Leanback app for Android TV. Fetches the public app config and plays a selected channel with Media3 ExoPlayer.

## Targets

- **Min SDK**: 26 (Android 8.0 — the floor Google recommends for TV)
- **Target SDK**: 34
- **Form factor**: TV only — `LEANBACK_LAUNCHER` intent-filter; will not appear in phone-style launchers

## Prerequisites

Same as the mobile variant — JDK 17, Android SDK with `android-34`, build-tools 34.0.0+, `ANDROID_HOME` set. Bootstrap the wrapper jar once with `gradle wrapper --gradle-version 8.7`.

## Build

```bash
./gradlew assembleDebug
./gradlew assembleDebug -PapiBaseUrl=https://civiccast.staging.example.com
```

APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## Sideload to an Android TV device

Enable developer mode + ADB debugging on the TV (Settings → Device → About → click "Build" 7 times, then Settings → Developer options → USB debugging or Network debugging).

```bash
adb connect <tv-ip>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.civiccast.tv.debug/com.civiccast.tv.MainActivity
```

The app will appear in the Android TV launcher's apps row once installed.

## Sideload to the Android TV emulator

```bash
# Create AVD if needed:  Android Studio → Device Manager → Create Device → TV → Android TV (1080p)
emulator -avd Android_TV
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## What's inside

```
app/src/main/
├── AndroidManifest.xml           Leanback feature required, banner declared, LEANBACK_LAUNCHER only
├── java/com/civiccast/tv/
│   ├── ConfigResponse.kt         @Serializable data classes (mirrors android-mobile)
│   ├── NetworkClient.kt          OkHttp wrapper (mirrors android-mobile)
│   ├── MainActivity.kt           FragmentActivity hosting MainBrowseFragment
│   ├── MainBrowseFragment.kt     BrowseSupportFragment with one row of channels
│   ├── ChannelCardPresenter.kt   Renders each channel as an ImageCardView
│   └── PlayerActivity.kt         Media3 PlayerView for HLS playback
└── res/
    ├── values/                   strings + Leanback themes
    ├── drawable/app_banner.xml   320x180 launcher banner (placeholder)
    └── mipmap-mdpi/              placeholder launcher icon
```

## Configuration

Identical to mobile — `-PapiBaseUrl=https://your.host` at build time → `BuildConfig.API_BASE_URL`.

## Follow-ups to reach store-ready

- Branded `app_banner` PNG/WebP at 320x180 (currently a solid color shape).
- Image loading library (Coil) for channel posters + station logo.
- Recommendation card service (Android TV "Watch Next" row).
- Search support via `BrowseSupportFragment.setOnSearchClickedListener` + `SearchSupportFragment`.
- Playback row / related-content UI — swap PlayerActivity to a `PlaybackSupportFragment` + `LeanbackPlayerAdapter` once VOD is wired.
- Signed release build, ProGuard rules, Play Console TV listing (TV banner asset 1280x720, content rating).
- Accessibility — D-pad focus order auditing on the browse row + player controls.
- DRM (Widevine L1 on TV hardware) for premium streams if needed.
- Channel logos, station identity in the BrowseFragment title bar.
