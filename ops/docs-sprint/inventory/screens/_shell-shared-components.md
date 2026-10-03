# Shell: shared components, status language, banners, toasts, keyboard and accessibility  (shared surface)
Source files (under `civiccast/apps/portal-operator/src/`): `components/ConfirmDialog.tsx`, `ReadinessBadge.tsx`, `StateBadge.tsx`, `Toast.tsx`, `toast-context.ts`, `EasPostureBanner.tsx`,
`EmptyState.tsx`, `AuthRequiredState.tsx`, `SampleSeedNotice.tsx`, `components/assets/assetStatus.ts`, `screens/status-language.ts`, `components/shell/Layout.tsx`, `hooks/useFocusTrap.ts`, `App.tsx`, `index.css`, `index.html`.
Who sees them: every signed-in user, on whichever screen mounts them.

## What it is for
The small pieces every screen reuses: the confirmation box before risky actions, the colour/word system for "is it OK?", the pop-up
messages, the global notices, and the keyboard rules. Documenting them once lets the manual say "the console always asks before..." accurately.

## ConfirmDialog (`ConfirmDialog.tsx`)
- Appearance: centred box over a dimmed page; heading (the question), one paragraph (the consequence), two buttons: `Cancel` (default label, left) and the action button (right). `role="alertdialog"`, named by the heading, described by the paragraph (:104-122).
- Rules: focus starts on `Cancel`; Tab/Shift+Tab stay inside; `Escape` cancels; clicking the dimmed background cancels; focus returns to the button that opened it (:53-91). While `busy` both buttons are disabled.
- Tone: `danger` = red action button (default), `brand` = dark button. Confirm label is verb-first, never "OK" (:26).
- Used in 17 source files (grep): Channels, Control Room, Live, Remote Contribution, Schedule, Program Guide, Publish, Asset detail, Media Lifecycle (panel and settings), CG Board, App Admin, Commissioning, Offline caption jobs, **Readiness, Emergency Alerts, Federation**. Not used for read-only actions by design (:15-16).
- Dialog texts for this inventory's screens are listed in `health.md`, `eas.md`, `activitypub.md`. Feed command wording (`feed-command-confirm.ts:15-48`): `Start the outgoing feed for <channel>?` / `Stop...` / `Restart...` / `Finish the current item, then stop <channel>?` with confirm labels `Start feed`, `Stop feed`, `Restart feed`, `Finish, then stop`.
- Not everything uses it: Alerts destination delete uses an inline `Delete` -> `Confirm delete?` (`AlertsScreen.tsx:612-630`); Emergency Alerts `Forced slate` uses a tick-box (`EasScreen.tsx:177-196`); Readiness `Check broadcast readiness` has no confirm although it creates a private recording.

## Status language (`screens/status-language.ts`)
- **Five readiness phrases** (the only ones allowed for "can I act?"): `Ready` (green), `Check before meeting` (amber), `Do not broadcast yet` (red), `Not set up yet` (amber), `Needs IT help` (red) (:31-35, tones :136-142).
- Backend words -> phrase (:59-109): ready/ok/pass/passed/proof_passed/verified/complete(d)/current/green -> Ready; needs_attention/needs_live_proof/needs_input/warning/warn/degraded/yellow -> Check before meeting; blocked/preflight_blocked/fail(ed)/failed_needs_action/proof_failed_redaction/error/red -> Do not broadcast yet; not_set_up/not_configured/credential_or_secret_required/not_started/not_tested/not_applicable/skipped_optional (or empty) -> Not set up yet; needs_it_help/hardware_required -> Needs IT help. Any other word is sentence-cased (`pending` -> `Not run yet`).
- **Lifecycle words** (`stateLabel`, :207-260): On air, Undeliverable (dead letter), Live on the portal (portal_live), Reaching fewer places than planned (reach_degraded), Archive pending, Archive verified, Waiting for media (pending_ingest), Needs changes, Under review, Showing slate, Starting, Stopping, Finishing current item (draining), Changing source (transitioning), Stopped, Needs attention (error), Draft, Preflight blocked, Publishing, Complete, Needs action, Not run yet. Unknown -> `Unknown`.
- Tones for feeds: ON_AIR green, ERROR red, everything else amber (:173-178). Delivery: delivered/sent/success/ok green; failed/dead_letter/error red; else amber (:192-199).
- Captions row text (:270-277) and Process row text (:284-288) are shared by Readiness and Channels.
- Rule: raw snake_case enums should never be the words on screen (:1-28); exceptions exist (see findings).

## Badges
- **ReadinessBadge** (media lifecycle, `ReadinessBadge.tsx:14-24`): dot + label: `Ready` (green), `Transcoding` (+ `(n%)` or `(n)` jobs), `Queued for transcode`, `Missing` (red), `Rejected` (red), `Not ready` (grey); optional server reason shown as hover text and read aloud. Only the Media Lifecycle panel uses it (`MediaLifecyclePanel.tsx:107`). (`StationProfileScreen.tsx:113` has an unrelated local component of the same name.)
- **StateBadge** (asset ingest state, `types/asset.ts:54-80`): `Analyzing`, `Ingesting`, `Validated`, `Rejected`, `Recorded`; hover text e.g. "ffprobe is running on the uploaded file."
- **AssetStatusBadge** (`assetStatus.ts`): ids rejected, missing_file, validating, ingesting, published, packaged, transcoding, queued_transcode, not_packaged, not_servable (labels/details in that file; owned by the Assets inventory).

## Toasts, banners and notices
| Item | Where | Text / behaviour | Source |
|---|---|---|---|
| Toast | bottom centre of any screen using `useToast` (six source files: Schedule, Trim editor, Program Guide, CG Board, Media Lifecycle panel and settings) | tones success (tick), error (`!`), info (`i`); message + optional detail; auto-closes after 4.5 s; button `Dismiss notification`; error is announced assertively, others politely | `Toast.tsx:39,102-145` |
| Sample-seed banner | top of every screen except `/setup` | red alert `CivicCast could not finish first-run sample setup`; "Something went wrong while `<creating the sample video / packaging the sample video for playback / publishing the sample video to the portal / creating the starter schedule item>`: `<error>`"; "Setup itself finished normally -- only the sample video and starter schedule item were affected. Add content and a schedule manually from Assets and Schedule, or retry sample setup below."; buttons `Retry sample setup` (setup admin or publish operator only) and `Dismiss` | `SampleSeedNotice.tsx:28-111` |
| Emergency posture banner | top of Emergency Alerts, cannot be closed | `Public-safety display — not an EAS device` + disclaimer (full text in `eas.md`) | `EasPostureBanner.tsx` |
| Runtime on-air banner | top of Readiness | see `health.md` | `SystemHealthScreen.tsx:301` |
| Recovery-kit hold | nav greyed, redirect to First Setup | tooltip "Save or print your recovery kit and confirm it on First Setup before leaving that screen." | `recoveryKitGate.ts:132` |
| Loading a screen | whole content area | `Loading this CivicCast screen...` (role status) | `App.tsx:248-254` |
| Not found | unknown path | `Page not found` | `App.tsx:98-133` |
| Auth problem | screens that call `AuthRequiredState` | "Could not verify your `<staff identity>` (`<detail>`). Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then retry once the local API is running." | `AuthRequiredState.tsx:8-10` |
| Empty state | many screens | dashed panel: bold one-line headline + one-sentence explanation + optional action | `EmptyState.tsx:20-41` |

No global "you are offline" or "station stopped" banner exists in the shell; each screen reports its own fetch failure.

## Keyboard and accessibility behaviour (code facts)
- Tab order starts with the `Skip to main content` link (shown on focus), then top bar, sidebar, main.
- After a route change **caused by a click or key press**, focus moves to the main area (`#main-content`); not on first load (`App.tsx:196-216`).
- Mobile drawer and ConfirmDialog trap focus; Escape closes both (`Layout.tsx:153-161`, `ConfirmDialog.tsx:58-63`). `useFocusTrap` skips closed `<details>` content (`useFocusTrap.ts:13-35`).
- Visible focus ring: 2 px brand-colour outline on every focusable element (`index.css:287-291`).
- Live regions: runtime on-air banner (assertive when red), alert list (polite), toasts, posture banner (polite), several `role="alert"` error boxes (23 `aria-live` uses in the source).
- Sidebar: `aside` `Primary navigation`; current page has `aria-current="page"`; section headers are native `<details>`/`<summary>` with labels `Show/Hide <name> navigation`.
- Theme: `Switch to dark theme` / `Switch to light theme` button (`TopBar.tsx:113`); starts light (`index.html:2`), is **not remembered** after reload and does not follow the computer's setting (state only, :104-111).
- Language `en`; page title is always `CivicCast Operator` on every screen (`index.html:6`; no code sets `document.title`).
- No `prefers-reduced-motion` rule was found in `index.css` or `civiccast-tokens.css` (search); buttons have a small press animation (`index.css:266-272`).
- Contrast: status pills use dark ink on soft tints because the accent-on-tint colours measured below 4.5:1 (`ReadinessBadge.tsx:30-36`).
- Dates/times use the browser's locale (`toLocaleString`); alert quiet hours use UTC.

## Help-text findings
- [SHELL-14] `AuthRequiredState.tsx:8-10` obsolete advice (see `_shell-signin-and-session.md` SHELL-09).
- [SHELL-15] `StateBadge` hover text uses a tool name: "ffprobe is running on the uploaded file." (`types/asset.ts:58`). Fix: "CivicCast is reading the file to check it can be used."
- [SHELL-16] The word `Ready` means different things in different badges: `ReadinessBadge` `Ready` = proxy file ready for air; Readiness page `Ready` = whole station ready; Assets `Packaged`/`Published`. The manual's glossary should define each separately.
- [SHELL-17] Status text mixes raw backend words with the five phrases: Federation `Mode` tile shows `approval-only`; Alerts severity shows `critical|warning|info`; Emergency Alerts severities and decision `mode` show raw lowercase words (`forced_slate`); Readiness shows the extra phrase `Ready with optional items` (not one of the five).
- [SHELL-18] Toasts are used in only six source files; elsewhere success is silent (Alerts `Save`, Emergency `Show crawl`, Federation `Approve`, Readiness feed commands). A first-time user cannot tell an action worked. Fix: use the toast for every successful save/queue.
- [SHELL-19] The manual section `destructive-actions-confirm` says "Nearly every one-click action ... shows a confirmation dialog"; see exceptions above.
- [SHELL-20] Theme choice is lost on reload and ignores the OS dark-mode setting; the page title never changes, so browser tabs/history/screen readers cannot tell screens apart.

## Screenshot plan
1. A ConfirmDialog (`Stop the outgoing feed for <channel>?`) with focus ring on `Cancel`.
2. A success toast and an error toast (Schedule save is the easiest source).
3. Sample-seed failure banner (needs a failed seed; UNVERIFIED if the lab station can produce one).
4. Dark theme (`Switch to dark theme`) on Readiness.
5. Skip link focused.

## UNVERIFIED / open questions
- UNVERIFIED: which other screens call `useToast` beyond the six files found by search (listed via grep of files; call sites not read).
- UNVERIFIED: the full ConfirmDialog usage list (grep of file names only).
- UNVERIFIED: print behavior and zoom/reflow behavior of the shell.
