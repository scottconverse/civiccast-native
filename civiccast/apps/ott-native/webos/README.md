# CivicCast LG webOS TV app — starter native source

Closes the S12 gap for LG webOS (previously: no source existed at all for
this platform — see the S12 spec gap note in `docs/spec/3.0/sections/
S12-ott-apps.md`). This is a real webOS web app (the supported app model
for webOS TV), built on Codebase 4 of the S12 platform build matrix — see
`../README.md` §"Platform build matrix".

## What this ships

```
webos/
├── appinfo.json    # webOS app manifest (id, main, icon, resolution)
├── index.html       # App shell — imports civiccast-player.js
├── icon.png          # 80x80 placeholder icon (solid color; replace before submission)
└── largeIcon.png     # 130x130 placeholder icon
```

`civiccast-player.js` — the actual playback client (config fetch, channel
list, live-state resolution, `<video>` playback) — is **not** checked in
here. It lives once, canonically, at `../web-shared/civiccast-player.js`
and is shared with `../tizen/`. See that file's header for why, and "Local
development" below for how to stage it.

## Real API contract

Calls the real CivicCast app-platform contract, not a flattened stand-in —
see `../web-shared/civiccast-player.js`'s header for the exact shapes:

1. `GET /api/public/app/config` → `StationAppConfig`
2. `GET <channel.live_state_url>` → `LiveState` (`playback_url` is the HLS
   manifest played in the `<video>` element)

Both are the same endpoints `civiccast/apps/app-platform-shells/src/shell.mjs`
and every other S12 native target call.

## Local development

```sh
cd civiccast/apps/ott-native/webos
cp ../web-shared/civiccast-player.js .
python3 -m http.server 8080   # ES module imports require http(s), not file://
# open http://localhost:8080/index.html?config=https://<station-host>/api/public/app/config
```

## Build / package

CI (`.github/workflows/ci-ott-apps.yml`) builds this on `ubuntu-latest`:

`@webosose/ares-cli` (the official webOS CLI) installs from npm with no
device or interactive EULA, so this platform gets a real package build —
unlike Tizen, no static-validation fallback is needed here. The job stages
`civiccast-player.js` in, then runs:

```sh
npm install -g @webosose/ares-cli
ares-package .
```

producing a `.ipk`. No emulator/device is used — packaging only.

## What this does NOT yet ship (the documented follow-up)

Starter-grade. To reach LG Content Store submission: branded icons (the
placeholders are solid-color PNGs), a real signing/developer-mode setup,
remote-control D-pad focus styling beyond the generic CSS `:focus` outline,
captions/audio-track UI, search, and deep-link handling.
