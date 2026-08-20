# CivicCast Roku channel — starter native source

Closes the S12 D1 gap for Roku (the "native OTT app source is absent" claim).
This is a real BrightScript + SceneGraph channel a Roku developer can
sideload to a device in developer mode and a starting point for store
submission via Roku Direct Publisher's "Custom Channel" path.

## What this ships

```
roku/
├── manifest                       # Roku channel manifest (sideload-ready)
├── source/
│   └── main.brs                   # Roku entry point (Main() / Scene boot)
├── components/
│   ├── CivicCastScene.xml         # Root SceneGraph component layout
│   └── CivicCastScene.brs         # Component behavior (config fetch + UI)
└── images/                        # Channel icons + splash (placeholder pngs;
                                   # replace with branded artwork before
                                   # store submission)
```

What it does:
- Boots a Scene at launch.
- Fetches `/api/public/app/config` from the CivicCast public API and renders
  the channel list (title + HLS URL).
- On row select, plays the HLS stream in a built-in `Video` node.
- Falls back to a 3-channel placeholder list (Public / Education / Government)
  when the API is unreachable, so a developer can sanity-check the surface
  without a live backend.

## What it does NOT yet ship (the documented follow-up)

This is starter-grade. To reach a Roku store submission, add:

1. A real `Task`-component config fetcher (replace the inline `urlTransfer`
   in `CivicCastScene.brs` with `ConfigFetchTask.brs` on its own thread)
2. Branded icons + splash screen in `images/` (the placeholders are 100x100
   gray PNGs)
3. Roku Pay / channel-store metadata
4. Deep link handling (Roku launches with `args.contentId` for deep-linked
   playback; the starter passes them through but doesn't route on them yet)
5. Accessibility (audio descriptions, voice guide narration override)
6. Captions UI (Roku's caption picker comes for free from the Video node;
   the starter does NOT yet surface a manual override)
7. Search interface (Roku Channel Store requires search for VOD channels)

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

The starter ships with `API_BASE_URL = "https://civiccast.example.com"` in
`components/CivicCastScene.brs`. Before sideloading to a real station's
device, edit that constant to the station's public API host (e.g.
`https://api.lpmofficial.tv`).

Production override path: replace the inline constant with a
Roku-`registry` read so the station administrator can change the base URL
through a "Settings" screen without re-uploading the channel. That screen
is part of the documented follow-up.

## Validation

The Roku platform ships a `bs` (BrightScript) static analyzer that runs
on macOS/Linux/Windows. To check the BrightScript source for syntax +
basic shape issues without a device:

```sh
npm install -g brighterscript     # ~30s, no Roku SDK needed
bsc --project bsconfig.json       # syntax + linting (TODO: add bsconfig.json)
```

The starter does NOT ship a `bsconfig.json` yet — adding it is part of the
"polish to store-ready" path documented above. Until then, the sideload +
on-device launch is the smoke test.

## Architecture note (why SceneGraph and not Direct Publisher)

Roku Direct Publisher accepts an MRSS feed + branding and produces a
channel without any code — that's the path for stations that just want a
VOD catalog. CivicCast 3.0 needs live + VOD + schedule + captions +
chapters, which is beyond Direct Publisher's surface. SceneGraph
(BrightScript + XML) is the supported lower-level API. This starter is
the SceneGraph path. A Direct Publisher MRSS feed for a strict-VOD subset
of the catalog could ship as a parallel deliverable if a station wants
the "appears in Roku channel store without engineering" path.
