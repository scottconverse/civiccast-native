# CivicCast — Android Mobile (phones & tablets)

Starter Kotlin app that fetches the public app config from a CivicCast backend and plays a selected channel's HLS stream with Media3 ExoPlayer.

## Targets

- **Min SDK**: 24 (Android 7.0)
- **Target SDK**: 34
- **Form factor**: phone + tablet (no foldable-specific layouts yet)

## Prerequisites

- JDK 17
- Android SDK with `android-34`, build-tools 34.0.0+, platform-tools
- `ANDROID_HOME` (or `ANDROID_SDK_ROOT`) set
- One bootstrap of the Gradle wrapper: `gradle wrapper --gradle-version 8.7` from this directory (we ship only the wrapper props + scripts, not the binary jar)

## Build

```bash
./gradlew assembleDebug
# Custom API base:
./gradlew assembleDebug -PapiBaseUrl=https://civiccast.staging.example.com
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## Sideload to a device

```bash
adb devices                                              # confirm one connected
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.civiccast.mobile.debug/com.civiccast.mobile.MainActivity
```

To uninstall:

```bash
adb uninstall com.civiccast.mobile.debug
```

## What's inside

```
app/src/main/
├── AndroidManifest.xml         Internet permission, single MAIN/LAUNCHER activity
├── java/com/civiccast/mobile/
│   ├── ConfigResponse.kt       @Serializable data classes for /api/public/app/config
│   ├── NetworkClient.kt        OkHttp + kotlinx.serialization wrapper
│   ├── MainActivity.kt         AppCompat activity, MVVM, RecyclerView of channels
│   └── PlayerActivity.kt       Media3 ExoPlayer HLS playback
└── res/
    ├── layout/                 activity_main, activity_player, item_channel
    ├── values/                 strings, Material 3 themes
    └── mipmap-mdpi/            placeholder vector launcher icon
```

## Configuration

The backend base URL is wired through Gradle → `BuildConfig.API_BASE_URL`. Default is `https://civiccast.example.com`. Override per build:

```bash
./gradlew assembleDebug -PapiBaseUrl=https://your.host
```

For a runtime toggle (per-device override), add a debug-only settings screen that writes to `SharedPreferences` and have `NetworkClient` prefer the pref over `BuildConfig`. Not wired yet.

## Follow-ups to reach store-ready

These are explicit gaps left for a follow-up engineer — not bugs:

- Real launcher icon set (adaptive + density buckets).
- Signed release build (`signingConfigs` + keystore, `release` buildType with `isMinifyEnabled = true` + ProGuard rules).
- Play Console listing: title, descriptions, screenshots, content rating, data-safety form, privacy policy URL.
- Auth / account binding (if CivicCast moves off public config).
- Picture-in-picture (declare `android:supportsPictureInPicture="true"` on `PlayerActivity` and react to `onPictureInPictureModeChanged`).
- Chromecast — add `androidx.mediarouter` + a `CastContext`.
- Background audio / `MediaSession` integration for lock-screen controls.
- Crash reporting (Firebase Crashlytics or Sentry).
- Localized strings — currently English only in `values/strings.xml`.
- Larger-screen `sw600dp` and `sw720dp` layout overrides for tablets.
- Accessibility pass — content descriptions on the player surface, focus order in the channel list.
- Image loading for `posterUrl` / `logoUrl` — currently the fields exist on the data model but are not rendered. Add Coil and a `posterImage` view to the channel item.
