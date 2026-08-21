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

CI (`.github/workflows/ci-ott-apps.yml`) builds this on `ubuntu-latest`. Real,
CI-confirmed status as of 2026-08-21 (PR #17):

- **The headless install genuinely works.** The ~260 MB `web-cli` installer
  from `download.tizen.org` installs non-interactively with
  `--accept-license --no-java-check`; `tizen version`, `tizen certificate`
  (author cert generation), `tizen security-profiles add`, and
  `tizen cli-config profiles.path=...` all succeed for real on the runner.
  This is further than "can't possibly work" — most of the toolchain does.
- **`tizen package -t wgt -s <profile> -- .` itself still fails** with an
  opaque `An error has occurred. See the log file .../cli.log.` The
  workflow now searches for and dumps the real `cli.log` on failure (it
  previously guessed the wrong path and printed nothing) — the next
  debugging pass should start there.
- **The job passes anyway**, via the honest fallback: static `config.xml`
  contract validation (`validate_config.py`) — a `tizen package`-equivalent
  check (required elements present, referenced files exist), not a real
  IPK/WGT build. See the workflow's `tizen` job for exactly which path ran
  on any given run (`$GITHUB_STEP_SUMMARY` records it explicitly).

Manual packaging with the real Tizen Studio (once installed):

```sh
tizen package -t wgt -s <your-signing-profile> -- .
```

## What this does NOT yet ship (the documented follow-up)

Starter-grade. To reach Tizen Store submission: branded icon (the
placeholder is a solid-color PNG), a real signing profile + Samsung
Certificate, remote-control D-pad focus styling beyond the generic CSS
`:focus` outline, captions/audio-track UI, search, and deep-link handling.
