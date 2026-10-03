# Shell: layout, sidebar, route table and role model  (shared surface, all screens)
Source files (under `civiccast/apps/portal-operator/src/`): `components/shell/Sidebar.tsx`, `Layout.tsx`, `TopBar.tsx`, `App.tsx`, `routes.ts`, `auth/roles.ts`, `auth/recoveryKitGate.ts`, `hooks/useFocusTrap.ts`.
Server: `civiccast/auth/{roles,models,router,middleware,tokens}.py`, `installer/station_state.py:795-811`, `cli.py:2065-2170`.
Companion files: `_shell-signin-and-session.md` (sign-in, token, sign-out), `_shell-shared-components.md` (dialogs, badges, toasts, banners, keyboard).

## 1. Layout
- **Top bar** (`TopBar.tsx:262-293`): `C` logo + `CivicCast` + version `v<x.y.z>` (from `GET /api/version`, else build value, :27-34); centre (desktop only, hidden under 768 px): pill `No live meeting broadcast` and clock `Local <time> / Next No events scheduled`; right: theme button, operator badge (initials), `Sign out`.
- **Sidebar** (`Sidebar.tsx:363-408`, `aside` labelled `Primary navigation`): profile card, six collapsible sections, footer.
- **Main** (`<main id="main-content" tabIndex=-1>`): the screen. First thing in tab order: link `Skip to main content` (visible only on focus, `Layout.tsx:35-68`).
- **Phones / narrow (< 768 px)** (`Layout.tsx:25,163-191`): sidebar becomes a drawer opened by the `Open navigation` button; drawer is a modal dialog `Primary navigation` with a backdrop button `Close navigation`, focus is trapped (`useFocusTrap`), Escape closes (:153-161), picking an entry closes it.
- **Profile card** (`Sidebar.tsx:83-86,265-286`): always the fixed text `CivicCast station` over `Public meetings`; it does **not** show the configured station name (see SHELL-01).
- **Footer** (`Sidebar.tsx:390-406`): link `Report a beta issue` (-> `/help#report-without-github`), text "No GitHub account? That's fine — the link above covers that too. Do not include passwords, recovery codes, staff tokens, or private meeting material.", tag `Operator-first beta`.
- **Section behaviour** (`Sidebar.tsx:288-352`): each section is a `<details>`; summary tooltip = section summary; sections marked collapsed by default start closed (Help, Setup, System Health) but the section holding the current screen is forced open (:307-309). Section with no visible items is not rendered (:310). Header button label: `Show <name> navigation` / `Hide <name> navigation`.
- **"Kit pending" behaviour:** while the one-time first-setup recovery kit is waiting (`sessionStorage` key `civiccast.pendingRecoveryKit`), every nav row is disabled (grey, tooltip "Save or print your recovery kit and confirm it on First Setup before leaving that screen.") **except `Manual`** (`availableWhileKitPending`, `Sidebar.tsx:69-73,93`); `Sign out` is disabled with the same tooltip; any other URL redirects to `#/setup` (`App.tsx:222-224`); only `/setup` and `/help` are allowed (`routes.ts:96-99`). `Report a beta issue` stays clickable.
- Unused nav features in code: `disabled`, `plannedLabel` ("<label> is planned for a later public-beta update.") and `count` badges exist in `NavRow` but no nav item sets them today (`Sidebar.tsx:57-74,222-260`).

## 2. Sidebar sections, labels and routes (37 entries)
Hash routes are `#/<path>`. Roles: S = setup_admin, M = meeting_operator, R = records_clerk, P = publish_operator, A = support_admin. `Y` = entry shown, `-` = hidden (`isItemVisible`, `Sidebar.tsx:203-207`). While identity has not loaded, role-limited entries are hidden (fail closed, :204-205).

| Section (tooltip) | Nav label | id | Path | S | M | R | P | A |
|---|---|---|---|---|---|---|---|---|
| Help ("Operator manual, glossary, and provider setup guides") | Manual | help | /help | Y | Y | Y | Y | Y |
| Setup ("Admin setup and station configuration") | First Setup | setup | /setup | Y | Y | Y | Y | Y |
| | Control Room Setup | controlroomsetup | /control-room-setup | Y | - | - | - | - |
| | Station Profile | station-profile | /station-profile | Y | Y | - | - | Y |
| | Cable Commissioning | commissioning | /commissioning | Y | - | - | - | Y |
| | AI Models | ai-models | /ai-models | Y | Y | - | - | - |
| | Custom Fields | custom-fields | /custom-fields | Y | - | - | - | - |
| | Paywall | paywall | /paywall | Y | - | - | - | - |
| Run Meeting ("Night-of-broadcast controls") | Live | live | /live | Y | Y | Y | Y | Y |
| | Facility | facility | /facility | Y | Y | Y | Y | Y |
| | Control Room | controlroom | /control-room | Y | Y | Y | Y | Y |
| | Remote Contribution | remotecontribution | /remote-contribution | Y | Y | - | - | Y |
| | Channels | channels | /channels | Y | Y | Y | Y | Y |
| | CG Board | cg | /cg | Y | Y | Y | Y | Y |
| | CG Designer | cgdesigner | /cg-board | Y | - | - | Y | Y |
| | Schedule | schedule | /schedule | Y | Y | Y | Y | Y |
| | Auto-schedule | autoschedule | /auto-schedule | Y | - | - | Y | Y |
| | Program Guide | guide | /guide | Y | Y | Y | Y | Y |
| | Recording | recording | /recording | Y | Y | - | - | Y |
| Review Records ("Assets, captions, summaries, agendas, and signed records") | Assets | assets | /assets | Y | Y | Y | Y | Y |
| | Missing Media | missingmedia | /missing-media | - | Y | - | Y | Y |
| | Media Lifecycle Settings | medialifecycle | /media-lifecycle | Y | - | Y | Y | - |
| | Contributors | contribute | /contribute | Y | Y | Y | Y | Y |
| | Review queue | review | /review | Y | Y | Y | Y | Y |
| | Summary review | summary | /summary | Y | Y | Y | Y | Y |
| | Agendas | agendas | /agendas | - | Y | Y | - | - |
| Publish ("Resident portal, archives, and notifications") | Publish | publish | /publish | Y | Y | Y | Y | Y |
| | Playback policy | playback | /playback-policy | Y | Y | Y | Y | Y |
| | Analytics | analytics | /analytics | Y | Y | Y | Y | Y |
| | Reports | reports | /reports | - | - | - | - | Y |
| | EPG Export | epg | /epg | Y | - | - | Y | - |
| | Underwriting | underwriting | /underwriting | Y | - | - | Y | Y |
| | App Admin | appadmin | /app-admin | Y | - | - | Y | - |
| System Health ("Readiness, federation, and advanced health") | Readiness | health | /health | Y | Y | Y | Y | Y |
| | Alerts | alerts | /alerts | Y | Y | Y | Y | Y |
| | Emergency Alerts | eas | /emergency-alerts | Y | Y | - | - | Y |
| | Federation | activitypub | /activitypub | Y | Y | Y | Y | Y |

Aliases (`routes.ts:47-67`): `/docs`,`/manual` -> help; `/login`,`/sign-in` -> setup; `/readiness` -> health; `/today` -> schedule; `/archive` -> assets; `/subscribers` -> paywall; `/cg-designer` -> cg-board; `/program-guide` -> guide; `/contributors` -> contribute; `/review-queue` -> review; `/summary-review` -> summary; `/epg-export` -> epg. Extra routes not in the nav: `/assets/:assetId` (asset detail) and `/assets/:assetId/trim` (full-screen trim editor, no shell). Unknown path: `Page not found` / "This operator route does not exist in this build." with buttons `Manual`, `First Setup`, `Recording`, `Reports`, `Readiness` (`App.tsx:98-133`).

## 3. Role model (code facts)
- Five roles, exactly (`civiccast/auth/roles.py:14-20`, `models.py:11-17`): `setup_admin` (label `Setup admin`), `meeting_operator` (`Meeting operator`), `records_clerk` (`Records clerk`), `publish_operator` (`Publish operator`), `support_admin` (`Support admin`) (`auth/roles.ts:6-12`).
- A token carries **scopes**; the server expands them into roles (`roles_for_identity`, `roles.py:43-57`). Aliases: `admin` and `operator` = all five roles; `setup|setup-admin`, `meeting|meeting-operator`, `records|records-clerk`, `publish|publish-operator`, `support|support-admin` = the single role. No scopes = no roles (fail closed). Unknown scopes are rejected at startup for env tokens (`tokens.py:111-119`).
- **Who gets what:** the first admin created in First Setup, and anyone signing in with that admin's password or a recovery code, gets scope `admin` = **all five roles** (`station_state.py:811`). Tokens made with `civiccast token issue --scopes ...` default to `operator` (= all five) unless narrowed (`cli.py:2072-2090`, `auth/store.py:39`). Env tokens `CIVICCAST_STAFF_TOKENS` must list roles (`tokens.py:62-135`).
- The only way to sign in from the console UI is the first-admin username/password or a recovery code (see `_shell-signin-and-session.md`). There is no console screen to create operators, assign roles, or paste a token. So in a normal station every console user is effectively all five roles; role-limited behaviour is reachable only with a CLI/env-issued token (UNVERIFIED how such a token is loaded into a browser; no paste field exists).
- The identity shown in the top bar: initials badge; hover/read-aloud text "`<display name> / <role labels>`" (`TopBar.tsx:148-159`). Roles are never displayed as visible text.
- The nav filter is a convenience, not security; each screen and each API route enforces its own gate (`Sidebar.tsx:1-6`). Roles are OR'd: one matching role is enough.

## 4. Screen-level gates found in the code (beyond nav)
From `hasOperatorRole` / role-list searches. Marked (read) where I read the screen for this inventory, otherwise (grep) = a line-level hit only, not read in full.
| Screen / control | Gate in the UI | Source |
|---|---|---|
| Readiness (read) | feed buttons + `Check broadcast readiness`: M; repair / restore / update / rollback / self-checks: S or A; support bundle: A | `SystemHealthScreen.tsx:1488-1496` |
| Alerts (read) | manage rules/destinations: S or A (server: S only for changes) | `AlertsScreen.tsx:765-768` |
| Emergency Alerts (read) | page: S, A, M; display/clear: S, M | `EasScreen.tsx:34-35` |
| Federation (read) | none in UI (server: moderation P or A; keygen S) | `ActivityPubScreen.tsx` |
| Setup providers (grep) | S | `SetupScreen.tsx:1447` |
| Review queue / Summary review (grep) | review actions: R | `ReviewQueueScreen.tsx:440`, `SummaryReviewScreen.tsx:231` |
| Publish (grep) | P | `PublishDashboardScreen.tsx:836` |
| Schedule (grep) | write: P or S | `ScheduleScreen.tsx:546-547` |
| Auto-schedule / CG Designer (grep) | write: P or S; read adds A | `AutoScheduleScreen.tsx:852-854`, `CgBoardDesignerScreen.tsx:487-488` |
| Live / Facility / Channels (grep) | M, S, P+S combinations | `LiveRoomScreen.tsx:1107-1117`, `FacilityRouterScreen.tsx:656-657`, `ChannelOpsScreen.tsx:1950-1965` |
| Control Room Setup (grep) | S | `ControlRoomSetupScreen.tsx:327` |
| Assets (grep) | P or S; R, M or A | `AssetsScreen.tsx:178-188` |
| App Admin (grep) | queue builds: S; P otherwise | `AppAdminScreen.tsx:212-214` |
| Cable verification card (grep) | S or A | `CableVerificationCard.tsx:140-141` |
| Paywall (grep) | text "Forbidden — the subscription paywall is a setup-admin surface." | `PaywallScreen.tsx:188` |
| Recording (grep) | text "Forbidden — scheduled recording is an operator / setup-admin / support-admin ..." | `RecordingScreen.tsx:267` |
| Sample-seed retry banner | retry button: S or P | `SampleSeedNotice.tsx:155-158` |

## 5. Server-side gates by API area (scan, approximate)
Method: parsed every `*.py` route decorator and parameter default for `require_any_role(...)` (495 routes found across all routers; 321 have one). `(n/m)` = gated endpoints in that area that allow the role / all gated endpoints in the area. **Routes with no `require_any_role` (174, 100 under `/api/staff`) are not counted: they may be open to any signed-in role or checked inside the function (UNVERIFIED).** Areas with the most ungated routes: producer-ops 21, installer 19, egress 11, live 10.
- **setup_admin** - 31 areas, notably: ai-models 8/8, alert-channels 4/4, alert-rules 2/2, app 8/8, auto-schedule 17/17, cable 9/9, cg 18/18, custom-fields 5/5, eas 9/9, epg 6/6, installer 29/33, migrate 4/4, paywall 6/6, playout 5/5, recording 9/9, schedule 4/4, underwriting 12/14; **not** allowed: agendas, captions, summaries, reports, publish, contribute, facility, programlog, activitypub moderation.
- **meeting_operator** - 24 areas: agendas 11/11, contribute 5/5, contribution 12/15, control-room 11/21, egress 8/15 (feed commands are M only), eas 6/9 (read + display), facility 2/2, live 7/12, programlog 4/4, recording 9/9, alert-events 2/2, assets 8/12, installer 1/33 (the private rehearsal).
- **records_clerk** - 11 areas: agenda/agendas 12/12, captions 6/6, summaries 5/5, records 1/1, assets 7/12, analytics 1/5, custom-fields 2/5.
- **publish_operator** - 18 areas: activitypub 4/5 (moderation), analytics 5/5, app 7/8, auto-schedule 17/17, cg 18/18, contribute 5/5, epg 6/6, playback-policy 2/2, playout 5/5, podcast 1/1, publish 2/2, schedule 4/4, subscribe 1/1, underwriting 12/14, assets 5/12, installer 2/33.
- **support_admin** - 34 areas: installer 18/33 (restore, drill, update/rollback, support bundle), reports 4/4, activitypub 4/5, alert-events/-rules/-channels (read), analytics 5/5, self-tests 2/2, system-resources, eas 4/9 (read only), underwriting 2/14, contribution 6/15, control-room 9/21, programlog 4/4.
- `runtime-safe-to-air` allows all five roles. `/api/staff/auth/me` and `/api/staff/auth/sign-out` allow any signed-in token (`auth/router.py:51-72`).
- Wrong role => HTTP 403 with text "This action requires one of these CivicCast roles: `<role ids, alphabetical>`." using the raw ids, not the friendly labels (`roles.py:93-98`); no identity => 401 "Staff identity is required for this action."

## 6. Visible but forbidden (screens in this inventory)
| Role | Opens but cannot use |
|---|---|
| records_clerk | Alerts: list returns 403 (red `Alerts could not load.`); Federation Approve/Reject/Block -> 403 |
| publish_operator | Alerts: list returns 403; Federation moderation is allowed |
| setup_admin (without P or A) | Federation Approve/Reject/Block -> 403 (key generation is allowed) |
| support_admin | Alerts rule/destination `Save`, `Add destination`, `Delete` -> 403; feed buttons disabled (note shown) |
| meeting_operator | Alerts rules/destinations: access note; Readiness: restore/update/support-bundle controls disabled with notes |

## Help-text findings
- [SHELL-01] `Sidebar.tsx:83-86` profile card always reads `CivicCast station` / `Public meetings`; the station's real name (set in First Setup / Station Profile) never appears anywhere in the shell. Fix: show the configured station name.
- [SHELL-02] `TopBar.tsx:98` the clock says `Next No events scheduled` unconditionally and the pill `No live meeting broadcast` is also fixed (`:58,78`); both are placeholders ("Sprint 0.3: no live module yet; pill always idle") that never change, even during a live meeting or with a full schedule. A first-time user will believe the schedule is empty. Fix: hide until wired, or wire to real data.
- [SHELL-03] Section names and page names disagree across the shell: nav `Readiness` vs page `Safe to broadcast`/`System Health`; nav `Federation` vs `ActivityPub federation`; nav `CG Designer` -> path `/cg-board` but `CG Board` -> `/cg`; nav `Alerts` vs `Alerts & monitoring`. Manual text uses the page names.
- [SHELL-04] Role names appear only as raw ids in 403 messages ("meeting_operator, setup_admin") and nowhere visibly; nothing explains who can grant a role or that a normal first-admin holds all five. Fix: friendly labels (`ROLE_LABELS`) in every access note.
- [SHELL-05] Nav hides screens a role cannot use, but several visible screens (Alerts, Federation) still contain controls that role will be refused; and nav hides `Missing Media` and `Agendas` from `setup_admin` even though that role is the usual all-powerful admin - harmless for first-admin tokens (all five) but confusing for a role-limited setup admin.
- [SHELL-06] Sidebar tooltip for the `Help` section lists "glossary, and provider setup guides" but there is one row (`Manual`).

## Screenshot plan
1. Desktop shell, signed in as first admin, all sections open (Help/Setup/System Health expanded by hand).
2. Same at 375 px width with the drawer open.
3. Kit-pending state: nav greyed with tooltip (needs a fresh first-setup run).
4. Skip link focused (press Tab once on a fresh load).
5. Role-limited nav (needs a CLI token with e.g. `records_clerk` only) - UNVERIFIED how to load it into a browser.

## UNVERIFIED / open questions
- UNVERIFIED: how a CLI/env-issued token reaches the browser (no paste field; `window.__CIVICCAST_STAFF_TOKEN__` is read by `api/client.ts:355-369` but nothing in the console sets it).
- UNVERIFIED: the 174 unguarded routes (function-level checks or genuinely open).
- UNVERIFIED: the "(grep)" screens' exact controls.
- UNVERIFIED: whether `records_clerk` can approve publishing (manual says yes; the screen gate and scan say `publish_operator`).
