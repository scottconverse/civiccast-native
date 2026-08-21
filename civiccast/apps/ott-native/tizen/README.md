# CivicCast Samsung Tizen TV app — starter native source

Closes the S12 gap for Samsung Tizen (previously: no source existed at all
for this platform — see the S12 spec gap note in `docs/spec/3.0/sections/
S12-ott-apps.md`). This is a real Tizen web app (W3C widget packaging, the
supported app model for Tizen TV) built on Codebase 4 of the S12 platform
build matrix — see `../README.md` §"Platform build matrix".

## What this ships

```
tizen/
├── config.xml       # Tizen widget manifest (id, icon, privileges, profile=tv)
├── index.html        # App shell — imports civiccast-player.js
└── icon.png           # 117x117 placeholder icon (solid color; replace before submission)
```

`civiccast-player.js` — the actual playback client (config fetch, channel
list, live-state resolution, `<video>` playback) — is **not** checked in
here. It lives once, canonically, at `../web-shared/civiccast-player.js`
and is shared with `../webos/`. See that file's header for why, and "Local
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
cd civiccast/apps/ott-native/tizen
cp ../web-shared/civiccast-player.js .
python3 -m http.server 8080   # ES module imports require http(s), not file://
# open http://localhost:8080/index.html?config=https://<station-host>/api/public/app/config
```

## Build / package

CI (`.github/workflows/ci-ott-apps.yml`) builds this on `ubuntu-latest`:

- **If the Tizen CLI installs headlessly on the runner:** stages
  `civiccast-player.js` in, then runs `tizen package -t wgt -s <profile> -- .`
  to produce a `.wgt`.
- **Otherwise (documented, not hidden):** the Tizen Studio CLI is a ~1-2 GB
  interactive-EULA download not designed for headless CI. The job instead
  runs a static contract validation (W3C widget `config.xml` well-formedness,
  required `tizen:application`/`content`/`icon` elements present, `index.html`
  resolves) — a `tizen package`-equivalent check, not a full IPK/WGT build.
  See the workflow's `tizen` job for exactly which path ran and why.

Manual packaging with the real Tizen Studio (once installed):

```sh
tizen package -t wgt -s <your-signing-profile> -- .
```

## What this does NOT yet ship (the documented follow-up)

Starter-grade. To reach Tizen Store submission: branded icon (the
placeholder is a solid-color PNG), a real signing profile + Samsung
Certificate, remote-control D-pad focus styling beyond the generic CSS
`:focus` outline, captions/audio-track UI, search, and deep-link handling.
