# Readiness  (nav id: health, section: System Health)
Source files (all under `civiccast/apps/portal-operator/src/`): `screens/SystemHealthScreen.tsx`, `screens/health-check-anchor.ts`,
`screens/status-language.ts`, `screens/feed-command-confirm.ts`, `components/ConfirmDialog.tsx`, `api/client.ts`.
Server side read for facts: `civiccast/installer/service.py` (`build_system_health_report` :3637, `run_private_rehearsal` :3766), `installer/router.py`.
Route: `#/health` (aliases `/readiness`; also where a successful sign-in lands by default, `App.tsx:142`).
Who can open it: everyone signed in (no `requiredRoles`, `Sidebar.tsx:177`). Buttons inside are role-gated (table below).

## What it is for
One page that answers "can we broadcast right now?" It combines (a) the live on-air signal for each channel (polled every 5 s),
(b) an install-time checklist of required and optional items, (c) a "private rehearsal" button, (d) per-channel feed controls,
and (e) the support, backup/restore and update/rollback tools. Nav calls it "Readiness"; the page calls itself "Safe to broadcast"
(`SystemHealthScreen.tsx:1515`) under an eyebrow "System Health" (`:1513`).

## What the user sees (top to bottom)
1. Header: eyebrow `System Health`, h1 `Safe to broadcast`, text "One place to see whether the station is ready, what needs setup, and what residents can see." (`:1517`), and a coloured pill (right) from `COLOR_TONE` (`:63-78`).
2. **On air right now** banner (`RuntimeSafeToAirBanner` :301). Heading = server `status.label`, text = `status.operator_message`, pills "`N` critical" / "`N` warning", button `Review alerts` (if any alerts) or `Open alerts` (goes to `/alerts`, `:1523`), one tile per channel (channel id, state words, pill), footer "Live check `<time>`". Polls every 5 s (`:1378`). Live region: assertive when red.
3. Loading text `Checking station readiness...` (`:1532`) then the **top card**: heading = server `report.label`, `report.operator_message`, "Last checked `<date time>`", link `Open resident preview` (opens `report.resident_preview.public_url` in a new tab) and button `Check broadcast readiness`.
4. After the button runs: **Broadcast readiness check result** card (`RehearsalPanel` :149).
5. **Outgoing channel feed** (`EgressReadinessPanel` :622): one card per channel with Start / Stop / Restart feed / Finish current item, then stop.
6. **GStreamer engine repair** (:802).
7. Three columns: **Backup and restore readiness** (:863), **Update and rollback** (:986), **Support bundle** (:1226).
8. **Latest self-check** (:412) and **Machine health** (:529).
9. **Required before broadcast** and **Optional and advanced** lists of check rows (`CheckRow` :92).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Open alerts` / `Review alerts` | Goes to Alerts | client-side nav `/alerts` | none | `:339-346` |
| `Open resident preview` | Opens the resident portal URL in a new tab | link, `target=_blank` | none | URL from system-health report |
| `Check broadcast readiness` | Runs a **private rehearsal** | `POST /api/staff/installer/rehearsal` | server: `meeting_operator` (`installer/router.py:513`); UI: enabled unless identity loaded and lacks `meeting_operator` (`:1488`) | No confirm. Server creates a private live session "Private first-broadcast rehearsal" on channel `government`, copies the sample video, finalizes a recording asset (`service.py:3889-4004`). Button shows no "running" text. See HELP-04 |
| `Start` / `Stop` / `Restart feed` / `Finish current item, then stop` | Queue a command for that channel's feed worker | `POST /api/staff/egress/channels/{id}/commands` body `{action}` | server `meeting_operator` only (`egress/router.py:1168`); UI same (`canControl`) | Opens ConfirmDialog from `feed-command-confirm.ts:15-48`. Button text `Queuing...` while sending. Start without egress config -> 409 with reason |
| `Repair GStreamer runtime & restore full egress` | Re-verify the native video engine, re-stage if broken | `POST /api/staff/egress/repair-gstreamer` | server+UI `setup_admin` or `support_admin` | ConfirmDialog "Repair the GStreamer runtime?" (`:1620`), confirm `Repair runtime` |
| `Check backup storage` | Backup/restore rehearsal | `POST /api/staff/installer/restore/rehearsal` | `setup_admin` or `support_admin` | No confirm |
| `Run real database restore drill` | Restores latest backup into an isolated copy, tests crash recovery | `POST /api/staff/installer/dr/run-drill` | same | ConfirmDialog "Run the real database restore drill?" confirm `Run restore drill` (tone brand) |
| `Run update preflight` / `Rerun update preflight` | Pre-update checks | `POST .../update-rollback/preflight` | same | Enabled only when status is `update_available` (`:1021`) |
| `Open maintenance window` | Flags station as under maintenance for 60 min | `POST .../update-rollback/maintenance-window` `{duration_minutes:60}` | same | Needs preflight done + rollback proof `passed` (`:1022-1027`); ConfirmDialog "Open a 60-minute maintenance window?" |
| field `Rollback artifact path` + `Save rollback artifact` | Records path to an older installer | `POST .../rollback-artifact` | same | Placeholder `Example: C:\\CivicCast\\releases\\CivicCast_1.4.0_x64-setup.exe` (`:1175`) |
| `Run rollback rehearsal` | Exercises the rollback installer | `POST .../rollback-rehearsal` | same | Needs rollback configured; ConfirmDialog "Run the rollback rehearsal?" |
| `Run failed-update rehearsal` | Simulates a failed update | `POST .../failed-update-rehearsal` | same | Needs rollback proof `passed`; ConfirmDialog |
| `Run post-update proof` | Re-runs readiness proof on installed build | `POST .../post-update-proof` | same | ConfirmDialog "Run the post-update proof?" |
| field `Short note` + `Create support bundle` | Builds a redacted troubleshooting file | `POST /api/staff/installer/support-bundle` `{operator_note}` | server+UI `support_admin` only | Then `Download support bundle` -> `GET .../support-bundle/{id}/download`, saves `<bundle_id>.json` |
| `Run daily self-check now` / `Run weekly self-check now` | Runs the self-test set | `POST /api/staff/self-tests/run?kind=daily|weekly` | `setup_admin` or `support_admin` | Labels flip to `Running self-check...` |

Non-role message strings: "Checking broadcast readiness requires the meeting operator role. Health checks remain visible." (`:1584`); "Outgoing feed controls require the meeting operator role." (`:784`); "Running a self-check requires setup admin or support admin." (`:513`); "Repairing the GStreamer runtime requires setup admin or support admin." (`:856`); "Backup and restore checks require setup admin or support admin." (`:979`); "Update preflight requires setup admin or support admin." (`:1162`); "Rollback setup requires setup admin or support admin." (`:1218`); "Support bundles require support admin." (`:1279`).

## States
| State | Text |
|---|---|
| Report loading | `Checking station readiness...` |
| Report failed | `Could not load System Health.` + detail or `Check setup and staff-token state.` (`:1538-1540`); the rest of the page is hidden |
| Live signal failed | `The live on-air signal could not load.` |
| No channels set to run | `No channels are set to run automatically, so there is nothing on air to watch yet.` (`:352`) |
| No channel profiles | `No channel profiles are configured yet.` (`:674`) |
| Feed panel loading | grey pill `checking`; failure `Outgoing channel feed could not load.` |
| No health sample | `No sample yet` (on air, dropped frames, loudness) / `Not measured yet` (encoder, bitrate) |
| No self-check yet | `CivicCast has not run an automatic self-check yet. The first daily check runs overnight.` (`:443`) |
| No resource sample | `No resource sample has been taken yet.` |
| Restore/update status loading | `Checking restore status...` / `Checking update status...` |
| Offline/API down | no special offline state; fetch failures show the browser error text through `apiMessage` |
Page does not auto-refresh except the on-air banner (5 s). The checklist, feed cards, restore and update panels refetch only after one of their own actions or when the page is re-opened after 30 s (`queryClient.ts:54-55`). There is no Refresh button.

## Typical task flows
1. Before a meeting: open Readiness -> read top card colour and text -> click `Check broadcast readiness` -> read "Rehearsal result" and "Broadcast gate" lines -> click a blocking item link (see HELP-02) -> fix it on the screen named in its "Next step".
2. Feed stuck: Outgoing channel feed -> `Restart feed` -> confirm -> watch state pill and Process row (page does not auto-refresh; reopen to see the result).
3. Support request: `Create support bundle` (support admin) -> `Download support bundle` -> send file.
4. Before updating: backup check -> restore drill (off-hours) -> save rollback artifact -> rollback rehearsal -> update preflight -> maintenance window.

## Statuses and words on this screen
- Top pill / banner colours (`COLOR_TONE`, `:63-78`): green `Ready`, yellow `Check before meeting`, red `Do not broadcast yet`. These are three of the five phrases in `status-language.ts:31-35` (others: `Not set up yet`, `Needs IT help`). The server's card heading can also be `Ready with optional items` (`service.py:3714`) - not one of the five.
- Check-row pill = `readinessLabel(check.state)` (`status-language.ts:125`); row tag on the right = raw `check.kind` (`required` / `optional` / `advanced`).
- Rehearsal result: `Passed` (A private session ran, passed preflight, and finalized a recording.), `Failed` (The private session started but stopped before a recording was finalized.), `Not run` (A precondition kept the private session from starting.) (`:124-143`).
- Broadcast gate pill: `N required item(s) not ready` / `N required item(s) need attention` / `All required items ready`.
- Channel runtime pill (`:272`): `Needs attention` (red), `Working` (yellow), `On air` / `Ready` (green). Extra text: ` · on safety slate`, ` · live captions off`.
- Feed state words via `stateLabel`: Stopped, Starting, On air, Changing source, Showing slate, Finishing current item, Stopping, Needs attention (`status-language.ts:207-250`). Process row: `PID n` / `Preparing source` / `Not running`.
- Captions row: `On` / `Off (switched off in the station profile)` / `Not verified; open channel caption proof`.
- Cable sink pill: `<sink>: connected|not connected` or `local send: active (receiver not verified)` / `local send: not verified (receiver not verified)`.
- Schema pill: `Schema OK` / `Schema drift` / `No sample yet`.
- Self-check: `Passed` / `Passed with warnings` / `Did not pass yet`; per-check `<name>: ok|not yet` with names from `CHECK_LABEL` (:397) - Station readiness, Recording continuity, Backup, AI engine, Restore rehearsal, SRT streaming, Cable verification, Alert delivery ready.
- Machine health rows: Processor `n% busy`, Memory `a / b GB used`, Media space / Backup space `n GB free`, Database `Reachable`/`Unreachable`, Service `Running`/`Stopped`.
- Checks returned by the server (`service.py:3676-3698`): required - First admin, Recovery kit, Durable records storage, Backup, Camera or meeting source, Local recording, Resident portal, Station policy; optional - Contributor upload storage, Caption inference device, Cable headend verification (only when headend rollup exists), 24/7 channel automation (only when automation rollup exists), YouTube, Subscriber notices, Federation, Internet Archive, Archive storage, Internal service certificates (kind `advanced`).

## Related settings / env / CLI / API
`/api/staff/installer/system-health`, `/api/staff/runtime-safe-to-air`, `/api/staff/installer/rehearsal`, `/api/staff/egress/*`, `/api/staff/self-tests/run`, `/api/staff/installer/{restore,dr,update-rollback,support-bundle}`; `CIVICCAST_UPLOAD_DIR` (rehearsal needs it); `civiccast dr run-drill`, `civiccast cable support-bundle` (`cli.py:2689`, `:674`).

## Help-text findings
- [HELP-01] SystemHealthScreen.tsx:1520 vs :1552 - header pill says `Check before meeting` for every yellow, while the card below shows the server label, which is `Ready with optional items` when only optional items are yellow - the same page shows two different verdicts for one state, and the second is not one of the five approved phrases. Fix: one phrase, or make the pill use `report.label`.
- [HELP-02] SystemHealthScreen.tsx:198-203 - gate items are `<a href="#health-check-<id>">`. The console runs under `HashRouter` (`main.tsx:14`); `Layout.tsx:36-46` documents that a bare `#...` link is read as a route and lands on "Page not found". UNVERIFIED at runtime, but the same codebase calls this a known failure. Fix: scroll with JS like the skip link does.
- [HELP-03] Name drift: nav `Readiness`, h1 `Safe to broadcast`, eyebrow/copy `System Health`, server text "Use Run Meeting for the live event and keep System Health open." (`service.py:4088`). A first-time user cannot tell these are one place. Fix: pick one name.
- [HELP-04] `Check broadcast readiness` (:1577) hides what it does: the server makes a private live session on channel `government`, copies the sample video and finalizes a recording asset (`service.py:3889-4004`). Panel text says only "checks configuration, storage, and the bundled sample video" (:166). Fix: say "This creates a short private test recording in your media library" (UNVERIFIED whether it is visible on Assets) and name the result "Private rehearsal".
- [HELP-05] :1517/:1553 "Last checked" - no Refresh control, and the checklist does not poll (see States). Fix: add `Refresh` and say when it updates.
- [HELP-06] Jargon with no explanation for a non-technical reader: `GStreamer closure`, `FFmpeg fallback engine` (:826-828), `SHA-256`, `Schema drift ... re-migrate` (:610), `proof event`, `Migration safety`, `Window expires`, `Rollback artifact`, `SRT`, `Dropped frames`, `LUFS`. Fix: one-line plain definitions or a manual link (`manualLink()` exists but this screen never uses it).
- [HELP-07] :1657 "Close of the window happens automatically when it expires." - garbled sentence. Fix: "The window closes by itself after 60 minutes."
- [HELP-08] :1026-1027 buttons are greyed out with no reason (e.g. `Open maintenance window` needs preflight and rollback proof; `Run failed-update rehearsal` needs proof `passed`). Only the three role notes explain disabled state. Fix: show the missing prerequisite under the button.
- [HELP-09] :783 and :1584 name roles ("meeting operator") but the screen never says how an operator gets that role; role labels in the top bar are hover-only (`TopBar.tsx:152`).
- [HELP-10] :1254 "Generate a redacted troubleshooting file for tester support." - "tester" is beta-only wording and does not say where the file goes or who may read it. Fix: "for CivicCast support" plus what is redacted (UNVERIFIED - read `support_bundle` redaction code).
- [HELP-11] Feed controls (:756-761) do not say the command is only queued; nothing tells the user to wait or refresh, and the egress panel has no polling. After `Restart feed` the pill may stay on the old state.
- [HELP-12] :1175 placeholder path ends `CivicCast_1.4.0_x64-setup.exe` - a 1.4.0 example on a 1.0 beta product; may mislead.

## Screenshot plan
1. Healthy station: green banner + Ready top card + all required rows green.
2. Red state with a blocking required item (e.g. no recovery kit or no backup) showing the red card and the row's "Next step".
3. After `Check broadcast readiness`: result card with "Rehearsal result" and "Broadcast gate" lines.
4. Outgoing channel feed with one ON_AIR channel and the four buttons; and the ConfirmDialog for `Stop feed`.
5. Update-and-rollback panel with at least one disabled button; Support bundle after creation.
6. Same page signed in as a role-limited token to show the grey notes (needs a CLI-issued single-role token).

## UNVERIFIED / open questions
- UNVERIFIED: whether HELP-02 anchor links really route to Page not found (needs a run).
- UNVERIFIED: whether the private-rehearsal recording appears in Assets/Publish and whether it can be deleted.
- UNVERIFIED: what exactly the support bundle redacts and where `bundle.path` is written (server code not read).
- UNVERIFIED: how fast a queued feed command takes effect (daemon side not read).
- UNVERIFIED: semantics of backend states for `update.status` values other than `update_available` (not read).
