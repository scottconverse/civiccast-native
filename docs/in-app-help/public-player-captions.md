> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Video player and captions (shown on Home, on Watch pages and in `?manifest=` previews)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/HlsPlayer.tsx` unless noted.

## Where the text lives now
All player text is in `src/HlsPlayer.tsx` (lines 206, 227, 320-321, 351-414). Tests set the English and Spanish names; the real track names come from the video file (the station's caption job, not the portal).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Meeting video player | aria-label of the `<video>` | 360 |
| Loading video… | Over the video while starting | 372 |
| The video could not be loaded. Please try again. | Error, Safari/iPhone path | 206 |
| Your browser does not support HLS playback. Please try a recent version of Chrome, Firefox, Safari, or Edge. | Error, old browser | 227 |
| Network error while loading the video. Check your connection and try again. | Error, network | 320 |
| The video could not be played. The stream may be unavailable. | Error, other | 321 |
| Caption track controls | Hidden group label (screen readers only) | 391 |
| Captions | Visible word beside the buttons | 394 |
| Off | Button | 397 |
| `<track name>` (for example English, Spanish); else the language code; else "Track N" | One button per track | 276, 195, 403-407 |

## What the page really does
The player shows a normal browser video with its own controls. The Captions bar appears only if the video file lists caption tracks. A track starts on only if the video file marks it as the default; otherwise captions start off. Pressing a language button shows that track; pressing Off hides captions. The portal does not make captions and has no transcript, no caption style settings and no language switcher. The choice is not remembered: there is no storage code in `HlsPlayer.tsx`, so every recording starts again from the video's default. Errors cover the whole video. There is no Retry button; the resident must reload the page. Agenda clicks move the video through `seekTo` (66-79).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-player-captions/HELP-28 | "does not support HLS playback" | Jargon (227); the next step is vague. | Medium |
| public-player-captions/HELP-29 | "The stream may be unavailable." | Wrong word for a recording; gives no next step (321). | Medium |
| public-player-captions/HELP-30 | (missing) | When a video has no caption tracks nothing is shown (the bar needs `subtitleTracks.length > 0`, 389; the sync returns early with no tracks, 272). A person who needs captions cannot tell "none" from "still loading". | High |
| public-player-captions/HELP-31 | Button names | Raw names from the file; nothing says whether Spanish or other languages are human-made or machine-made. UNVERIFIED how the station makes them. | Low |
| public-player-captions/HELP-32 | "Try again" in errors | There is no button to try again (the error box has text only, 377-386). | Medium |
| public-player-captions/NEW-1 | Caption buttons | They use `px-3 py-1.5` with no minimum height (430), so they are shorter than the 44 px used on the rest of the portal. Hard to hit on a phone or with a tremor. | Medium |
| public-player-captions/NEW-2 | Button names for screen readers | A button reads only "English" or "Off" with "pressed"; the word "captions" is not in the name (the group label is hidden, 391). | Medium |
| public-player-captions/NEW-3 | Video label | Every video is "Meeting video player"; the title of the recording is not part of it. | Low |
| public-player-captions/NEW-4 | Captions start state | A resident who needs captions must find the bar each time; the choice is not saved. | Medium |
| public-player-captions/NEW-5 | Error box | It sits over the whole video (`absolute inset-0`, 380) and the same text appears for any "other" failure. No station contact is offered. | Low |

## Proposed text
| Replace | With |
| --- | --- |
| 372 | Loading video… |
| 206 | The video could not be loaded. Please reload the page. If it still fails, contact the station. |
| 227 | This browser cannot play the video. Please try the latest Chrome, Edge, Firefox or Safari. |
| 320 | The video stopped because the connection was lost. Check your internet, then reload the page. |
| 321 | The video could not be played. Please reload the page. If it still fails, contact the station. |
| 394 visible label | Captions |
| 397 button | Off (aria-label "Captions off") |
| Track button aria-label (add) | `<track name>` captions (for example "English captions") |
| 391 legend | Captions (make it visible instead of screen-reader only) |
| New line when a **recording** has no tracks (new) | Captions are not available for this video. |
| New help line under the bar (new) | Press a language to show captions. Press Off to hide them. Your choice is not saved for the next video. |
| 360 aria-label | Video player: `<recording title>` (Home live: "Live video player") |

**No-captions line, today (beta.10).** This line needs a code change (see notes). Until then, the Watch page text in `public-watch.md` tells residents to look for the Captions bar. **After fix:** show "Captions are not available for this video." once the video file has loaded and listed no caption tracks. Do not show it for a live stream until a live caption source is proven; this audit did not verify live captions.

**Accessibility and keyboard.** Tab reaches the video, then each caption button. Enter or Space presses a button. The pressed button reports `aria-pressed="true"`. Errors are announced (`role="alert"`, 378). Make the buttons at least 44 px tall. Keep the video's own controls (play, volume, full screen) as they are.

## Notes for the coder
- Edit `HlsPlayer.tsx`. Code fixes: add a Retry button to the error box (re-run the load effect); track "manifest parsed with zero subtitle tracks" and show the no-captions line; add `min-h-11`; remember the caption choice in `localStorage` or `sessionStorage` (private-mode safe, in a `try`).
- Tests that pin strings: `HlsPlayer.hlsjsCaptions.test.tsx:149-222` and `HlsPlayer.nativeCaptions.test.tsx:58-73` use button names "English", "Spanish" and "Off" and `aria-pressed`; if you add `aria-label` such as "English captions", `getByRole('button', { name: 'English' })` (exact) will fail. `e2e/a11y.spec.ts:493` (label "Meeting video player"), `a11y.spec.ts:564-589` (button names).
- Not verified: caption speed or accuracy, and which languages a station actually makes.
