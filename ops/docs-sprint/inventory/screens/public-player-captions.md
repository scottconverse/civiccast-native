# Video player and captions  (nav id: public-player-captions, section: Public)
Source files: `civiccast/apps/portal-public/src/HlsPlayer.tsx` (line cites), `analytics.ts`
Used by: Home live panel, Watch page, `?manifest=` preview. Who can open it: everyone.

## What it is for
Plays a station HLS video (live or recorded) in the browser and offers caption buttons when the video includes caption tracks. It uses the `hls.js` library in most browsers and the browser's built-in HLS in Safari/iOS (`HlsPlayer.tsx:170-231`).

## What the user sees
A 16:9 video with the browser's native controls (`aria-label="Meeting video player"`, 360). Over it: "Loading video…" while starting (371); on failure a red box with the message. Below it, only if the video lists caption tracks, a bar "Captions" with buttons "Off" and one button per track (389-410; group label "Caption track controls" for screen readers, 391).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Native play/pause/seek/volume/fullscreen | browser controls | none | none | `controls`, `playsInline` |
| Captions: Off | hides captions | sets track to none (335-349) | none | `aria-pressed` shows which is on |
| Captions: `<track name>` (e.g. English, Spanish) | shows that caption track | selects the HLS subtitle track | none | label = the manifest's track name, else language code, else "Track N" (276,195) |
Captions start on the track the manifest marks DEFAULT=YES (281-283), otherwise off. The viewer's choice is not remembered between recordings (UNVERIFIED across reloads; no storage code in the file).

## States and exact error text
- Loading: "Loading video…" (371).
- Browser has no HLS support: "Your browser does not support HLS playback. Please try a recent version of Chrome, Firefox, Safari, or Edge." (227)
- Safari/iOS load error: "The video could not be loaded. Please try again." (206)
- Network failure (hls.js fatal): "Network error while loading the video. Check your connection and try again." (320)
- Other fatal: "The video could not be played. The stream may be unavailable." (321)
- No Retry button; the viewer must reload the page. When the source URL changes, the player restarts itself (333).
- Seeking from the agenda: clamps to the video length and starts playback if paused (66-79).
- Live stream: the Home page re-resolves the source every 4 seconds and the player swaps source when `manifest_url` changes (`HomeScreen.tsx:179-195`).

## Captions: what the code shows and does not show
- The portal only DISPLAYS caption tracks the video manifest advertises; it does not create captions. Tests use English and Spanish track names (`e2e/a11y.spec.ts:220,565`); the real list comes from the station. Whether a station's recordings actually include English/Spanish tracks depends on the server captions pipeline (not in this inventory): UNVERIFIED.
- No transcript view, no caption styling controls, no language selection other than these buttons.

## Typical task flows
1. Press play. If a "Captions" bar is shown, click English (or another track) to turn captions on; click Off to hide.
2. Keyboard: Tab to the caption buttons; Enter/Space toggles (native buttons).

## Related settings / env / CLI / API
Manifest `.m3u8` URL from `/api/public/live/current` or `/api/public/assets/{id}`; analytics events `playback_*` (see `public-shell.md`).

## Help-text findings
- [HELP-28] `HlsPlayer.tsx:227` "does not support HLS playback" — jargon; suggest "This browser cannot play the video. Try the latest Chrome, Edge, Firefox or Safari."
- [HELP-29] `HlsPlayer.tsx:321` "The stream may be unavailable." — for a recording this wording is wrong (it is not a stream) and no next step is given; suggest "The video could not be played. Please reload the page; if it still fails, contact the station."
- [HELP-30] No message appears when a video has no captions, so a resident who needs captions cannot tell "none exist" from "not loaded yet". Missing line: "Captions are not available for this video."
- [HELP-31] The caption bar says only "Captions" with raw track names; no help that Spanish or other languages may be machine-translated (UNVERIFIED if they are).
- [HELP-32] There is no Retry on player errors (text says "try again").

## Screenshot plan
Playing recording with Captions bar (English active); same with Spanish; recording without captions (no bar); error box (point at a broken manifest via `?manifest=`); Loading state.

## UNVERIFIED / open questions
- UNVERIFIED: caption latency/accuracy for live captions (not in the player); which track names the station emits.
