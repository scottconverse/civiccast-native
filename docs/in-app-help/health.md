> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Readiness (nav id: health)

Sidebar: System Health > **Readiness**. The page H1 is "Safe to broadcast" and its small label is "System Health": three names for one screen. A successful sign-in lands here. Manual authority: `docs/manual/src/17-something-wrong.md` section "Check whether the station is ready (Readiness)" (`#check-whether-the-station-is-ready-readiness`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/SystemHealthScreen.tsx` (1751 lines), `status-language.ts`, `feed-command-confirm.ts`, `health-check-anchor.ts`. Server words (card heading, check rows, next steps) come from `civiccast/installer/service.py:3637-3720` and `:3766-4004`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "System Health" (label); "Safe to broadcast"; "One place to see whether the station is ready, what needs setup, and what residents can see."; header pill "Ready" / "Check before meeting" / "Do not broadcast yet" | page header | SystemHealthScreen.tsx:1513, 1515, 1517, 75-77, 1520 |
| "On air right now"; "Review alerts" / "Open alerts"; "No channels are set to run automatically, so there is nothing on air to watch yet."; "Live check <time>"; "The live on-air signal could not load." | on-air banner | 326, 345, 352, 376, 1526 |
| "Checking station readiness..."; "Could not load System Health." + "Check setup and staff-token state."; card heading (server `label`, can be "Ready with optional items"); "Last checked <time>"; "Open resident preview"; "Check broadcast readiness" | top card | 1532, 1538-1540, 1557, 1568, 1577; service.py:3713 |
| "Checking broadcast readiness requires the meeting operator role. Health checks remain visible." | role note | 1584 |
| "Broadcast readiness check result"; "This checks configuration, storage, and the bundled sample video -- it does not play video in this screen. Use Open resident preview to see what residents will see."; "Rehearsal result:" Passed / Failed / Not run; "Broadcast gate:" | rehearsal card | 162, 166-167, 171, 129-143, 180 |
| Gate items are links `#health-check-<id>` followed by the next step | gate list | 198-203 |
| "Required before broadcast"; "Optional and advanced"; row tags required / optional / advanced | lists | 1721, 1730 |
| "Outgoing channel feed"; buttons "Start", "Stop", "Restart feed", "Finish current item, then stop"; "Queuing..."; "Outgoing feed controls require the meeting operator role."; "No channel profiles are configured yet."; "Outgoing channel feed could not load." | feed panel | 656, 756-760, 777, 784, 674, 669 |
| "GStreamer engine repair"; "If a corrupt GStreamer closure has degraded a channel onto the FFmpeg fallback engine, this re-verifies it in place and, if it's still broken, launches a signed re-stage. Never a reinstall."; dialog "Repair the GStreamer runtime?" ("Repair runtime") | repair | 824-828, 1620-1622 |
| "Backup and restore readiness"; "Checking restore status..."; "Check backup storage"; "Run real database restore drill"; dialog "Run the real database restore drill? ... run it outside broadcast hours. The live database is not modified." | backup panel | 895, 899, 965, 974, 1636-1640 |
| "Update and rollback"; "Checking update status..."; "Run update preflight"; "Window expires"; "Migration safety"; "Rollback artifact"; "Rollback artifact path" (placeholder "Example: C:\CivicCast\releases\CivicCast_1.4.0_x64-setup.exe"); "Save rollback artifact"; "Run rollback rehearsal"; "Run failed-update rehearsal"; "Run post-update proof"; maintenance dialog "Open a 60-minute maintenance window? ... Close of the window happens automatically when it expires." | update panel | 1038, 1042, 1149, 1079, 1083, 1094, 1167, 1175, 1186, 1195, 1204, 1213, 1656-1657 |
| "Support bundle"; "Generate a redacted troubleshooting file for tester support."; "Short note"; "Create support bundle"; "Support bundles require support admin."; "Download support bundle" | support panel | 1251, 1253, 1257, 1275, 1279, 1297 |
| "Latest self-check"; "CivicCast has not run an automatic self-check yet. The first daily check runs overnight."; "Run daily self-check now" / "Run weekly self-check now"; "Running a self-check requires setup admin or support admin." | self-check | 436, 443, 495, 506, 513 |
| "Machine health"; "No resource sample has been taken yet."; "Not measured yet"; "No sample yet"; "Schema OK" / "Schema drift" and "...update or re-migrate before relying on this data" | machine health | 535, 538, 526, 588, 599, 610 |

## What the screen really does
It answers "can we broadcast right now?". The top banner polls every 5 seconds; everything else refetches only after its own button or when you re-open the page after about 30 seconds, and there is no Refresh button. The card verdict and the Required list come from the server (eight required checks: first admin, recovery kit, durable storage, backup, camera or meeting source, local recording, resident portal, station policy). "Check broadcast readiness" (Meeting operator) runs a private rehearsal: it creates a private live session "Private first-broadcast rehearsal" on the channel `government`, copies the sample video and saves a test recording. Feed buttons only queue a command for the channel's feed worker; the pill may keep the old state until you reload. The lower panels (repair, backup and restore, update and rollback, support bundle) are for IT staff or trained staff.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | Header pill says "Check before meeting" for every yellow (1520) | The card below shows the server label, "Ready with optional items" when only optional items are yellow (service.py:3713); the second phrase is not one of the five | misleading |
| HELP-02 | Gate items are `<a href="#health-check-<id>">` (198-203) | The console is a HashRouter app; a bare `#...` link is read as a route (Layout.tsx:36-46). In testing we could not confirm it lands on "Page not found" (UNVERIFIED) | misleading |
| HELP-03 | "System Health" (label, messages) vs "Readiness" (nav) vs "Safe to broadcast" (H1) | One screen, three names; server text "keep System Health open" (service.py:4088) | misleading |
| HELP-04 | "This checks configuration, storage, and the bundled sample video" (166) | Also creates a private live session and a test recording (service.py:3889-4004); the button shows no running text | misleading |
| HELP-05 | "Last checked <time>" (1557) | No Refresh; the checklist does not poll | misleading |
| HELP-06 | "GStreamer closure", "FFmpeg fallback engine", "SHA-256", "Schema drift ... re-migrate", "proof event", "Migration safety", "Window expires", "Rollback artifact", "SRT", "Dropped frames", "LUFS" | Jargon with no definition; `manualLink()` exists but this screen never uses it | cosmetic |
| HELP-07 | "Close of the window happens automatically when it expires." (1657) | Garbled sentence; the window lasts 60 minutes | cosmetic |
| HELP-08 | Greyed buttons (1026-1027) | "Open maintenance window" needs a preflight and rollback proof "passed"; "Run failed-update rehearsal" needs proof "passed"; nothing says so | misleading |
| HELP-09 | Role notes name roles (783, 1584) | The screen never says how a person gets a role; role labels are hover-only | cosmetic |
| HELP-10 | "...troubleshooting file for tester support." (1253) | "Tester" is beta wording; does not say where the file goes or who may read it; only Support admin can make one | misleading |
| HELP-11 | Feed buttons give no hint that a command is only queued | After "Restart feed" the pill may stay on the old state; nothing tells you to wait or reload | misleading |
| HELP-12 | Placeholder "CivicCast_1.4.0_x64-setup.exe" (1175) | A 1.4.0 example on a 1.0 beta product | cosmetic |
| NEW-1 | Stop confirm: "Residents ... lose the stream until the feed is started again" (feed-command-confirm.ts:30) | With "Keep this channel on air" ticked the automation restarts the feed (manual `22-configuration.md`) | misleading |
| NEW-2 | Support bundle panel shown to every role | Only the Support admin role can create one; a Setup-admin-only token clicks and gets 403 | misleading |

## Proposed text
**Header:** label "Readiness"; H1 "Readiness: is the station safe to broadcast?"; intro "What this is for: see whether the station is ready to broadcast right now, what still needs setup, and what residents can see. Who can use this: everyone signed in. Some buttons need a role; a button you cannot use shows a grey note naming the role." Use "Readiness" in every message (replace "System Health").
**Verdict (one phrase):** show the server label in the pill and the card. Replace "Ready with optional items" with "Ready" and the line "Optional items still need a look." (or "Check before meeting").
**Top card extras:** "Last checked <time>. This page does not refresh by itself (except On air right now). Reload to update." After fix: a Refresh button.
**Check broadcast readiness:** helper under the button: "This starts a private test on channel 'government': CivicCast makes a short private recording from the bundled sample video and checks the whole path. No residents see it. Run it before a meeting, not during one. Needs the Meeting operator role." Result card intro: "This did a private test. The test recording may be saved in your media library." (UNVERIFIED whether it shows in Assets.)
**Gate links:** scroll to the row with script (like the skip link) instead of a bare `#` link.
**Feed buttons:** under the panel: "A button sends a request to the channel's feed. It may take a minute to show here; reload the page to see the new state." Stop dialog: "This takes <channel> off the air. Residents lose the stream. If 'Keep this channel on air' is ticked on Channels, CivicCast may start it again within about 30 seconds."
**Maintenance dialog:** "While the window is open the station is marked as under maintenance and an update may be applied. The window closes by itself after 60 minutes."
**Disabled buttons:** show the reason under the button: "Needs: update preflight done; rollback proof passed."
**Jargon (one line each, or link `/help#app-glossary`):** GStreamer = "the video engine"; closure = "its set of files"; SHA-256 = "a file fingerprint"; SRT = "a streaming protocol"; LUFS = "a loudness unit"; Dropped frames = "pictures that were lost".
**Support bundle:** "A support bundle is a file that helps CivicCast support find a problem. Passwords and keys are removed (we did not check exactly what else it contains). Only the Support admin role can make one. Do not post it publicly."
**Rollback placeholder:** "Example: C:\CivicCast\releases\CivicCast_<version>_x64-setup.exe".

## Notes for the coder
- Files: `SystemHealthScreen.tsx` (header 1513-1520, 166, 783-784, 1253, 1657), `feed-command-confirm.ts`, `status-language.ts`, `civiccast/installer/service.py:3713, 4088`.
- Pins: `SystemHealthRehearsalPanel.test.tsx` ("Rehearsal result", "Broadcast gate", `health-check-` anchors), `SystemHealthAlerting.test.tsx` ("Outgoing channel feed", "Run daily self-check now"), `SystemHealthGstreamerRepair.test.tsx` ("Repair GStreamer runtime"), `SchemaBadge.test.tsx` ("Schema drift"), `ControlRoomScreen.test.tsx` ("Support bundles require support admin."), `e2e/operator-first-mile.spec.ts` (H1 "Safe to broadcast", "Ready with optional items" at lines 60/726, "Check broadcast readiness", "Open resident preview", "Rollback artifact path", the 1.4.0 placeholder, "Finish current item, then stop"), `e2e/setup-real-boundary.spec.ts` ("Safe to broadcast", "Short note"), `tests/installer/test_installer_api.py` ("Safe to broadcast", "CivicCast_1.4.0"), and the policy test `tests/policy/test_readiness_label_consistency.py` plus `docs/operator-language-guide.md` (the three readiness labels must read the same everywhere; update the guide in the same change).
- Code fix needed, not text: gate-link scrolling (HELP-02); Refresh button or polling (HELP-05); disabled-state reasons (HELP-08); feed state polling or optimistic text (HELP-11); pass the real role rule to `SupportBundlePanel` (NEW-2).
