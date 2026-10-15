# CivicCast Roku channel

Closes the S12 D1 gap for Roku (the "native OTT app source is absent" claim).
This is a real BrightScript + SceneGraph channel a Roku developer can
sideload to a device in developer mode. It browses and plays the station's
public live channels and published replays.

## What this ships

```
roku/
├── manifest                       # Roku channel manifest (sideload-ready)
├── source/
│   └── main.brs                   # Roku entry point (Main() / Scene boot)
├── components/
│   ├── CivicCastScene.xml         # Root SceneGraph component layout
│   └── CivicCastScene.brs         # Component behavior (config fetch + UI)
└── images/                        # CivicCast icons and splash artwork
```

What it does:
- Boots a Scene at launch.
- Fetches `/api/public/app/config` (the real `StationAppConfig` contract —
  see `civiccast/app_platform/models.py`) from the CivicCast public API and
  renders the channel list from `channels[].branding.display_name`.
- On row select, fetches that channel's `live_state_url` (a second request —
  `LiveState.playback_url` is the HLS manifest, it is not on the config
  response) and plays it in a built-in `Video` node.
- Shows an explicit setup/error message (not fake content) when the API is
  unreachable, returns no channels, or a channel has no live program —
  see `showEmptyState()` / `fetchLiveStateAndPlay()` in `CivicCastScene.brs`.
- Loads channel logos and replay posters, searches the catalog, accepts
  Roku content-ID deep links, and retains the native player options for
  audio and captions.

## Platform publication

Store metadata, a Roku developer account, and on-device certification are
publication steps. The Video node uses Roku's system audio and caption
preferences and options. The channel itself has no purchase or protected
viewer-login workflow.

## Build + sideload

The Roku tooling is "zip the channel root, upload via the dev portal." On
the Roku device:

1. Enable developer mode: Home 3x → Up 2x → Right → Left → Right → Left →
   Right. Enter a dev password; record it.
2. From a terminal in this directory:
   ```sh
   # macOS / Linux
   zip -r ../civiccast-roku-channel.zip ./manifest ./source ./components ./images

   # Windows (PowerShell)
   Compress-Archive -Path manifest, source, components, images `
       -DestinationPath ..\civiccast-roku-channel.zip
   ```
3. Navigate to `http://<your-roku-ip>` in a desktop browser, log in with
   `rokudev` + the password you set in step 1.
4. "Upload" → select `civiccast-roku-channel.zip` → "Install" or "Replace".

The channel appears on the Roku home screen as "CivicCast" — open it,
confirm the channel list renders, select a row to start playback.

## Configuration

Press `*` while browsing, choose **Station address**, and save the station's
HTTPS public host. The URL persists in Roku's registry. The example default
in `getApiBaseUrl()` is only a first-launch prompt target.

## Validation

The Roku platform ships a `bs` (BrightScript) static analyzer that runs
on macOS/Linux/Windows. To check the BrightScript source for syntax +
basic shape issues without a device:

```sh
npm install -g brighterscript     # ~30s, no Roku SDK needed
bsc --project bsconfig.json       # syntax + linting (TODO: add bsconfig.json)
```

`bsconfig.json` is included. Sideloading is still needed to check the actual
device's playback and remote behavior.

## Architecture note (why SceneGraph and not Direct Publisher)

Roku Direct Publisher accepts an MRSS feed + branding and produces a
channel without any code — that's the path for stations that just want a
VOD catalog. CivicCast 3.0 needs live + VOD + schedule + captions +
chapters, which is beyond Direct Publisher's surface. SceneGraph
(BrightScript + XML) is the supported lower-level API. This starter is
the SceneGraph path. A Direct Publisher MRSS feed for a strict-VOD subset
of the catalog could ship as a parallel deliverable if a station wants
the "appears in Roku channel store without engineering" path.
