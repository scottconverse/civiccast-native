# CivicCast Android — TV, Fire TV, and mobile

One Gradle project, one wrapper, three real app variants. This is the S12
de-duplication of what used to be three entire copied source trees
(`android-tv/`, `fire-tv/`, `android-mobile/`) that differed mostly in
`applicationId` and a handful of manifest lines.

| Module | Flavor(s) | Storefront | Devices | Package |
|---|---|---|---|---|
| `:tv-app` | `tv` | Google Play (Android TV / Google TV) | Android TV, Google TV | `com.civiccast.tv` |
| `:tv-app` | `firetv` | Amazon Appstore | Fire TV | `com.civiccast.firetv` |
| `:mobile-app` | (default) | Google Play (phones/tablets) | Android phones/tablets | `com.civiccast.mobile` |

`:tv-app`'s two flavors share 100% of the Kotlin source
(`tv-app/src/main/java/com/civiccast/tv/`) and 100% of the layout/theme
resources. The only per-storefront differences — the Amazon hardware hint,
the extra Fire launcher intent-filter, and whether `android.software.leanback`
is `required` — live in `tv-app/src/tv/AndroidManifest.xml` and
`tv-app/src/firetv/AndroidManifest.xml`, merged by the Android Gradle
Plugin's manifest merger. `:mobile-app` is a genuinely different UI
(RecyclerView phone layout vs. Leanback browse) so it stays its own module.

## Real API contract

All three variants call the real CivicCast app-platform contract, not a
flattened stand-in:

1. `GET <API_BASE_URL>/api/public/app/config` → `StationAppConfig`
   (`station_name`, `default_channel_id`, `channels[].branding.display_name`,
   `channels[].live_state_url`, ...). See
   `civiccast/app_platform/models.py` and
   `civiccast/apps/app-platform-shells/fixtures/station-app-config.sample.json`.
2. `GET <API_BASE_URL><channel.live_state_url>` → `LiveState`
   (`state`, `playback_url`, ...). `playback_url` is the HLS manifest handed
   directly to ExoPlayer/Media3.

`live_state_url` is a path relative to the API host — `NetworkClient`
resolves it against `baseUrl` before fetching.

## Build

```sh
cd civiccast/apps/ott-native/android

# Android TV (Google Play)
./gradlew :tv-app:assembleTvDebug -PapiBaseUrl=https://api.example.tv

# Fire TV (Amazon Appstore)
./gradlew :tv-app:assembleFiretvDebug -PapiBaseUrl=https://api.example.tv

# Mobile (Google Play)
./gradlew :mobile-app:assembleDebug -PapiBaseUrl=https://api.example.tv
```

CI builds all three variants on `ubuntu-latest` — see
`.github/workflows/ci-ott-apps.yml`.

## Viewer experience

All three variants include CivicCast launcher artwork, load station logos
and replay posters, search channels and published replays, and play HLS
through Media3. The in-app Station address control persists an HTTPS station
URL; `-PapiBaseUrl` sets the first-launch default. Links shaped
`civiccast://channel/<id>` and `civiccast://replay/<id>` open the matching
item. In the player, Audio / captions opens the available track picker.

Store signing and physical-device certification are separate publication
steps. These source apps consume the public station catalog.
