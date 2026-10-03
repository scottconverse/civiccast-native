# CG Board  (nav id: cg, section: Run Meeting)
Path prefix `S` = `civiccast/apps/portal-operator/src`; `B` = `civiccast/cg`.
Source files: `S/screens/CgBoardScreen.tsx`, `S/screens/cg-board-format.ts` (NOT used by this screen; used by CG Designer), `S/components/EmptyState.tsx`, backend `B/router.py`, `B/models.py`, `B/board_resolver.py`, `S/components/shell/Sidebar.tsx`, `S/routes.ts`.
Who can open it: nav entry has no `requiredRoles`, so every signed-in operator sees it (`S/components/shell/Sidebar.tsx:126`). Route `/cg` (`S/routes.ts:13`). **But the Community bulletins panel needs `setup_admin` or `publish_operator`** (`B/router.py:630,647,681`); other roles get the API's 403 text in a red box (see Help-text findings).

## What it is for
CG Board shows a read-only preview of the "between-streams" community board for one channel (template layout, where each zone's content comes from, the configured feeds, and the output URLs) and holds the Community bulletins queue: staff add short announcements and approve, send back or decline them. Approved bulletins are what the channel can show as rotating filler slides between programs when that channel's filler is set to "Community bulletins". Building the board itself (zones, feeds, template) is done on CG Designer, not here.

## What the user sees
1. Heading `CG Board` and subtitle "Build the between-streams board, live ticker, schedule zones, and streaming output contract." (`CgBoardScreen.tsx:712-715`), with a `Channel` dropdown at right (`:717-736`).
2. Red alert box if the channel list or display fails to load (`:739-743`).
3. `Template library` row of 3 template buttons (`:745-754`), each showing its label and "`N` regions / `ratio`" (`:96-99`).
4. Left: panel `Visual layout editor` (`:126`) with the template id under it and, in a pill at right, the `proof_boundary` string (`:135`), then a grid of region boxes (Main/Lower/Side/Bug/Background) each containing zone cards (`:146-186`).
5. Right column, top to bottom: `Output paths` (`:663`), `Dynamic feeds` (`:611`), `Community bulletins` (`:454`).
Layout is a 2-column grid on wide screens (`:756`). The display is refetched every 30 s (`POLL_MS`, `:23,:699`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Channel` dropdown (`Public board` + one option per channel `branding.display_name`) | Switches which channel's display and bulletin queue are loaded; clears the chosen template | `GET /api/staff/app/config` for the channel list (`client.ts:1497`); `GET /api/public/cg/channels/{id}/display[?template_id=]` (`client.ts:2068-2076`) | channel list: any signed-in staff (`app_platform/router.py:137-143`, no role dep); display: public, no auth (`B/router.py:752-757`) | The first option value is the literal id `public` (`:689,:729`). |
| Template buttons (`Standard community board`, `Live lower banner`, `Schedule forward board` - labels come from the server template library) | Changes only the on-screen preview (re-requests display with `template_id`) | `GET .../display?template_id=` | any | `aria-pressed`. Does NOT save anything or change what airs. UNVERIFIED that server labels match the three in `cg-board-format.ts:8-12` (that list is the Designer's). |
| `Add bulletin` (header button of Community bulletins; toggles to `Close`) | Opens/closes the add form | none | panel visible to all, but API needs setup_admin/publish_operator | `:455-462` |
| Add form fields `Organization`, `Submitted by`, `Title`, `Message` | Text inputs; all four required | | | Button disabled until all four non-blank (`:219-220`). Server limits: organization/submitter 160, title 200, message 500 chars (`B/models.py:174-177`; UI sets no maxLength). |
| `Add bulletin` (form submit; shows `Adding…`) | Creates a bulletin in state `submitted` for the current channel | `POST /api/staff/cg/channels/{id}/bulletins` (`client.ts:2597`); sent with default `target_zone_kind="primary"` and no start/end (`B/router.py:320-322`) | `setup_admin` or `publish_operator` | Form closes and queue refreshes on success. On 503: "Durable storage is not ready. Open Setup and choose Prepare storage before managing community bulletins." (`B/router.py:659`). The UI has no fields for air-from/air-until dates even though the server supports them. |
| `Approve` (only on `Submitted` / `Needs changes` items) | Sets state `accepted`, stamping your operator id as approver | `PATCH /api/staff/cg/channels/{id}/bulletins/{sid}` `{state:'accepted', approved_by_operator}` (`:437-440`) | `setup_admin` or `publish_operator` | No confirmation. If identity not loaded: "Your staff identity has not loaded yet — try again in a moment." (`:434`). |
| `Request changes` (same items) | Opens dialog `Request changes`; on send sets state `needs_changes` with your note | PATCH `{state:'needs_changes', moderation_notes}` | same | Dialog textarea placeholder "What needs to change before this bulletin can air?"; buttons `Cancel` / `Send request`. Blank note: toast "Enter a note before submitting — it tells the submitter what to fix." (`:318`). Cancel toast: "Request changes cancelled — no note was sent." |
| `Decline` (any state except Declined) | Opens dialog `Decline bulletin`; on submit sets state `declined` with your note | PATCH `{state:'declined', moderation_notes}` | same | Placeholder "Why is this bulletin declined? (Required.)"; submit button `Decline bulletin`; cancel toast "Decline cancelled — the bulletin was not declined." Shown even for already-approved/scheduled bulletins, so it is also how you pull an airing bulletin. Declined bulletins cannot be re-approved from this screen (Approve only shows for submitted/needs_changes). |

## States
- Loading: layout title shows `Loading template…`, pill shows `Loading…`, output paths show `Loading…` (`:128,:135,:668`); feeds show `Loading configured feeds…` (`:615`).
- Display load error: red box with server detail or `CG board could not load.` (`:741`).
- Bulletin queue error: red `Could not load the bulletin queue.` or server text (`:471`) (e.g. 403 for roles without access).
- Action error (add/moderate): `Could not add the bulletin.` / `Could not update the bulletin.` or server text (`:415,:425`). 422 text is the raw validation message from the server (`B/router.py:716-718`).
- No bulletins: EmptyState "No bulletins yet." / "The community board runs station and community announcements on this channel between programs. Add the first bulletin above to get it started." (`:485-486`). ("above" is wrong: the Add button is at the top of the same panel; fine, but wording is loose.)
- No feeds: EmptyState "No dynamic feeds are configured." / "Add an approved RSS, calendar, weather, or permitted social source before using feed-driven CG zones." (`:630-632`) - does not say where (CG Designer).
- Zone cards with nothing: `Unassigned` / `source-pending` (`:61,:178`).
- Not ready storage: bulletin writes return 503 text above; reads fall back to an empty queue unless `CIVICCAST_CG_DEMO_FEEDS=1` (`B/router.py:636-639`).

## Typical task flows
1. Post an announcement: pick channel -> `Add bulletin` -> fill 4 fields -> `Add bulletin` (state = Submitted) -> `Approve`. It becomes eligible to air (accepted/scheduled and inside any time window, `B/board_resolver.py:50,258-266`).
2. Send back: `Request changes` -> type note -> `Send request`.
3. Pull a bulletin: `Decline` -> type reason -> `Decline bulletin`.
4. Check what the board would show: choose template buttons and read the zone cards (preview only).

## Statuses and words on this screen
| Word | Meaning (code) |
|---|---|
| `Submitted` | state `submitted`, awaiting moderation (`:196`) |
| `Needs changes` | state `needs_changes`; note required (`:197`, `B/models.py:195`) |
| `Approved` | state `accepted`; approver required (`:198`) |
| `Scheduled` | state `scheduled`; counts as airable like Approved (`:199`, `board_resolver.py:50`). Nothing in this UI sets it. |
| `Declined` | state `declined`; note required (`:200`) |
| `Notes: …` | moderation note in amber (`:513`) |
| zone line `<kind> / <source>` and `refresh N min`, `proof_boundary` pill | raw technical strings from the API |
Shared status words: not used (`status-language.ts` not imported).

## Related settings / env / CLI / API
Channel Ops "Between programs, show" -> `Community bulletins` (`ChannelOpsScreen.tsx:957`, description "Rotates approved bulletin-board slides; falls back to slate when none are approved."); `CIVICCAST_CG_DEMO_FEEDS`; `CIVICCAST_BULLETIN_EXPIRY=off` disables the purge worker, which deletes bulletins whose end time is more than 7 days past (`B/bulletin_expiry_worker.py:10-14,47-50`); API `/api/public/cg/channels/{id}/{display,snapshot,feeds,templates,bulletins,render-plan,stream.m3u8,overlay-contract}`; `/api/staff/cg/channels/{id}/bulletins`.

## Help-text findings
- [HELP-01] `CgBoardScreen.tsx:713-715` — "Build the between-streams board, live ticker, schedule zones, and streaming output contract." — The screen cannot build anything except bulletins; zones, feeds and template are edited on CG Designer. — "Preview the community board and approve community bulletins for this channel. To change the board's layout, zones or feeds, use CG Designer."
- [HELP-02] `CgBoardScreen.tsx:126` — heading `Visual layout editor` — Read-only preview; nothing is editable and template buttons do not save. — Rename `Layout preview` and add "Choosing a template here only changes this preview."
- [HELP-03] `Sidebar.tsx:126` / `B/router.py:630` — CG Board is visible to everyone but bulletin queue requires publish_operator or setup_admin; a meeting_operator or support_admin sees a raw server message ("This action requires one of these CivicCast roles: publish_operator, setup_admin.") in a red box — hide the panel or show "Managing bulletins requires the publish operator or setup admin role." (CG Designer already has such an `AccessNote`, `CgBoardDesignerScreen.tsx:62-67`).
- [HELP-04] `CgBoardScreen.tsx:464-467` — "Approved bulletins air as branded filler slides between programs on channels set to “Community bulletins”." — correct but gives no path. — Add "(Channels -> Between programs, show)". Also: new bulletins start as Submitted and do not air until you press Approve.
- [HELP-05] `:630-632` — "Add an approved RSS, calendar, weather, or permitted social source…" — no pointer to where; jargon "feed-driven CG zones". — "No outside news or calendar feeds are connected. Add one in CG Designer -> Feed sources."
- [HELP-06] `:178,:135,:650` — raw strings `source-pending`, `proof_boundary`, `feed_adapter`-style kinds shown to operators — jargon. — Hide or caption.
- [HELP-07] `:719-735` — option `Public board` is channel id `public`, not a real channel; unexplained. — Caption: "Public board = the default board shown on the resident web portal."  UNVERIFIED that this is the meaning (code only shows id `public` used as default `channel_id`).
- [HELP-08] `:461` — two different buttons both labelled `Add bulletin` (panel header and form submit) — confusing for manual/screenshots. — Rename the submit to `Save bulletin`.

## Screenshot plan
(a) Default load with a channel with templates, preview populated; (b) Community bulletins with one Submitted, one Approved, one Needs changes (with Notes), one Declined; (c) `Request changes` dialog open; (d) Add form expanded; (e) empty state with no bulletins and no feeds; (f) the 403 box as a meeting_operator. Setup: sign in as admin; create bulletins via the form; channel list needs channels in Channel Ops.

## UNVERIFIED / open questions
- UNVERIFIED: that a `scheduled` bulletin state is ever produced (no UI/code path seen setting it).
- UNVERIFIED: exact template labels/regions returned by `build_template_library` (not read; `cg-board-format.ts:6-12` says it mirrors it).
- UNVERIFIED: how rotation order/timing of bulletins on air works (`egress/bulletin_filler.py` only skimmed).
- Role-denied text (verified, `civiccast/auth/roles.py:80-97`): "This action requires one of these CivicCast roles: publish_operator, setup_admin." (role ids, alphabetical). UNVERIFIED only that the live app surfaces it in the red box unchanged.
- UNVERIFIED: that Delete/expiry purge deletes only after end time + 7 days with default settings (read from worker defaults; env override of settings not checked).
