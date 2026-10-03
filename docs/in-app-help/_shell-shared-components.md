# Shared components: confirmation boxes, status words, toasts, banners (nav id: _shell-shared-components)

A shared surface used by every screen. Manual authority: `docs/manual/src/11-signing-in.md` ("Read the colors and status words", "Messages and confirmation boxes", "Use the keyboard or a screen reader"), Appendix E (`app-status`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/` : `components/ConfirmDialog.tsx`, `Toast.tsx`, `SampleSeedNotice.tsx`, `EasPostureBanner.tsx`, `EmptyState.tsx`, `AuthRequiredState.tsx`, `ReadinessBadge.tsx`, `StateBadge.tsx`, `types/asset.ts`, `screens/status-language.ts`, `screens/feed-command-confirm.ts`, `App.tsx`, `index.html`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Confirmation box: heading = the question, one paragraph = the consequence, buttons "Cancel" (default) and a verb-first action label; focus starts on Cancel; Escape and the dim background cancel | `ConfirmDialog` | ConfirmDialog.tsx:20-36 (props), :40 (default label) |
| "Start the outgoing feed for <channel>?" / "<channel> goes live to its configured outputs and becomes visible to residents." (button "Start feed") | feed buttons on Readiness and Channels | feed-command-confirm.ts:22-23 |
| "Stop the outgoing feed for <channel>?" / "This takes <channel> off the air. Residents watching lose the stream until the feed is started again." ("Stop feed") | same | feed-command-confirm.ts:29-30 |
| "Restart the outgoing feed for <channel>?" / "The stream drops briefly for residents while <channel> restarts." ("Restart feed") | same | feed-command-confirm.ts:36-37 |
| "Finish the current item, then stop <channel>?" / "<channel> plays out its current item and then goes off the air until the feed is started again." ("Finish, then stop") | same | feed-command-confirm.ts:43-44 |
| The five readiness phrases: Ready, Check before meeting, Do not broadcast yet, Not set up yet, Needs IT help | everywhere a status pill shows | status-language.ts:31-35 |
| Lifecycle words (On air, Showing slate, Starting, Stopping, Finishing current item, Changing source, Stopped, Needs attention, Archive pending, Not run yet, Unknown ...) | `stateLabel` | status-language.ts:207-260 (fallback 'Unknown' at 252) |
| "Analyzing" with hover text "ffprobe is running on the uploaded file." | asset state badge | types/asset.ts:58 |
| Pop-up message with button "Dismiss notification"; closes after 4.5 s | `Toast` | Toast.tsx:136, :39 |
| "CivicCast could not finish first-run sample setup"; "Something went wrong while <creating the sample video / packaging the sample video for playback / publishing the sample video to the portal / creating the starter schedule item>: <error>"; "Setup itself finished normally -- only the sample video and starter schedule item were affected. Add content and a schedule manually from Assets and Schedule, or retry sample setup below."; buttons "Retry sample setup", "Dismiss" | red banner on every screen except First Setup | SampleSeedNotice.tsx:61, 65-66, 21-24, 70-72, 84, 95 |
| "Public-safety display — not an EAS device" + the EAS disclaimer | top of Emergency Alerts | EasPostureBanner.tsx:24-31 |
| "Could not verify your <staff identity> (...). Sign in again from the CivicCast installer handoff ..." | AuthRequiredState | AuthRequiredState.tsx:8-10 (see `_shell-signin-and-session.md`) |
| "Loading this CivicCast screen..." | screen loading | App.tsx:251 |
| Browser tab title "CivicCast Operator" on every screen; language `en` | page | index.html:7, :2 |
| "Switch to dark theme" / "Switch to light theme" | top bar | TopBar.tsx:113 |
| "Skip to main content" | skip link | Layout.tsx:65 |

## What the screen really does
These pieces are reused. The confirmation box appears only on some risky actions: Channels, Control Room, Live, Remote Contribution, Schedule, Program Guide, Publish, asset detail, Media Lifecycle, CG Board, App Admin, Commissioning, offline caption jobs, Readiness, Emergency Alerts (Clear) and Federation (Reject, Block, Generate key). Others act at once: Alerts destination Delete uses a two-click inline button, Emergency Alerts "Forced slate" uses a tick box, "Check broadcast readiness" and "Save" buttons have no confirm. Pop-up messages exist on only six source files (Schedule, trim editor, Program Guide, CG Board, Media Lifecycle panel and settings), so on other screens a successful save is silent. The five readiness phrases mean the same wherever they appear; other status words are mixed with raw backend words. The theme resets to light on every reload.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| SHELL-14 | AuthRequiredState advice (installer handoff, operator-console link) | Both retired; real step is Admin sign-in (see sign-in file SHELL-09) | blocks work |
| SHELL-15 | "ffprobe is running on the uploaded file." (types/asset.ts:58) | Tool name means nothing to a clerk | cosmetic |
| SHELL-16 | "Ready" | Means a different thing in each place: station ready (Readiness), one video's playable copy ready (media panel), Packaged / Published (Assets) | misleading |
| SHELL-17 | "five phrases" rule | Raw words appear: `approval-only` (Federation), `critical`/`warning`/`info` (Alerts), `forced_slate` and severities (Emergency Alerts), `GREEN/YELLOW/RED` (Station Profile), `PASS/FAIL` (Commissioning), plus the extra phrase "Ready with optional items" (installer/service.py:3713) | misleading |
| SHELL-18 | Success is silent on most screens | Alerts Save, Emergency "Show crawl", Federation Approve, Readiness feed commands give no message | misleading |
| SHELL-19 | Manual/section text that "nearly every one-click action shows a confirmation dialog" | See exceptions above | misleading |
| SHELL-20 | Theme and page title | Theme not remembered and ignores the computer's dark-mode setting; title is "CivicCast Operator" on every screen | cosmetic |
| NEW-1 | Feed-stop text: "Residents watching lose the stream until the feed is started again." | With "Keep this channel on air" ticked the automation restarts the feed (manual `22-configuration.md`, Known issue under Encoders) | misleading |
| NEW-2 | Sample-setup banner "Setup itself finished normally" | Banner can say "retry" only for Setup admin or Publish operator (SampleSeedNotice.tsx:155-158) and does not say that | cosmetic |

## Proposed text
- **Confirmation boxes (rule for every screen):** the heading names the action and the thing; the paragraph says what residents see and whether it can be undone; the action button names the action ("Stop feed"), never "OK". Every button that takes a channel off the air, deletes data or cannot be undone gets one. Until then, no text change.
- **Stop feed paragraph:** "This takes <channel> off the air. Residents lose the stream. If 'Keep this channel on air' is ticked on the Channels screen, CivicCast may start it again within about 30 seconds; untick it first if you want the channel to stay off."
- **Status help (hover or small "What do these colours mean?" link to `/help#read-the-colors-and-status-words`):** Ready (green) "The required checks passed." / Check before meeting (amber) "Something optional or recoverable needs attention." / Do not broadcast yet (red) "A required check failed for tonight's broadcast." / Not set up yet (amber) "An optional provider or feature has no sign-in details or proof yet." / Needs IT help (red) "The next step needs administrator, certificate, database or service work."
- **Readiness badge words:** media panel "Ready" -> "Playable copy ready"; keep Assets "Packaged" and "Published" but define each in the Assets help. Replace "Ready with optional items" with "Ready" plus the line "Optional items need a look" (or map to "Check before meeting").
- **StateBadge "Analyzing":** "CivicCast is reading the file to check it can be used."
- **Sample-setup banner:** "The sample video or starter schedule item could not be made. Setup itself finished. Add your own video in Assets and your own schedule item in Schedule, or press Retry sample setup (Setup admin or Publish operator only)."
- **Pop-up messages (after fix):** a short "Saved." or "Sent." toast for every save and command (Alerts Save, Emergency Show crawl, Federation Approve, feed commands).
- **Raw words (after fix):** show "Approval needed" for `approval-only`, "Critical / Warning / Info" for severities, "Full-screen takeover" for `forced_slate`, and the five phrases for GREEN/YELLOW/RED and PASS/FAIL.
- **Page title (after fix):** "<Screen name> - CivicCast" and keep the theme in `localStorage`.

## Notes for the coder
- Edit: `feed-command-confirm.ts` (and its caller text in Readiness/Channels), `types/asset.ts:58`, `SampleSeedNotice.tsx`, `status-language.ts`, `index.html`/a `useEffect` for the title, `TopBar.tsx` theme state.
- Pins: `SampleSeedNotice.test.tsx` ("could not finish first-run sample setup"), `src/api/client.test.ts` and `src/queryClient.test.ts` ("Too many failed attempts"), `status-language.test.ts` (all phrases), `ConfirmDialog.test.tsx`, `TopBar.test.tsx` and `e2e/control-room-readiness.spec.ts` ("Switch to dark theme"). None of the strings "ffprobe is running", "Dismiss notification" or "Loading this CivicCast screen" appeared in any test searched.
- Code fix needed, not text: toasts on every successful action; a confirmation (or two-step) for Alerts Delete via `ConfirmDialog` (HELP-09 in `alerts.md`); a global "cannot reach the station" banner (none exists).
