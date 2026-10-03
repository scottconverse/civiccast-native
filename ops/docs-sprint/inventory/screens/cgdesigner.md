# CG Designer  (nav id: cgdesigner, section: Run Meeting)
Path prefix `S` = `civiccast/apps/portal-operator/src`; `B` = `civiccast/cg`.
Source files: `S/screens/CgBoardDesignerScreen.tsx`, `S/screens/FeedApprovalQueue.tsx`, `S/screens/cg-board-format.ts`, `S/auth/roles.ts`, backend `B/board_router.py`, `B/board_service.py`, `B/board_models.py`.
Who can open it: nav entry visible only to `publish_operator`, `setup_admin`, `support_admin` (`S/components/shell/Sidebar.tsx:127`). Route `/cg-board` (alias `/cg-designer`) (`S/routes.ts:14,53`). Inside the screen: read = publish_operator / setup_admin / support_admin; write = publish_operator / setup_admin only (`CgBoardDesignerScreen.tsx:485-488`; backend `B/board_router.py:58-59`). A signed-in user with none of the three roles who types the URL sees `Viewing and managing the CG board designer requires the publish operator, setup admin, or support admin role.` (`:62-67,:570`). Heading is `CG Board Designer`, nav label is `CG Designer`.

## What it is for
Lets a station set up the durable "community board" for one channel: pick a template, define zones (a zone is one box on the board such as a ticker, schedule or logo and where its content comes from), register outside feeds (RSS, calendar, weather, social links) and approve individual feed items, with a live preview and a change history. Support admins can look but not change.

## What the user sees
1. Header `CG Board Designer`, subtitle "Configure the durable bulletin board: template, zones, feed sources, and a live preview. The engine composites this board into the channel." (`:533-537`), `Channel` dropdown (`Public board` + channels) (`:539-559`).
2. Status lines: `Loading…`, access error, access note (`:562-570`), board load error, action error (`:571-580`).
3. Left column: `Board` panel; `Zones` panel (when a board exists); `Feed sources` panel.
4. Right column: `Live preview` (when preview returns), `Board history`.
5. Bottom: `Saving…` (aria-live) while any save is in progress (`:751`).
Board, preview and history refetch every 30 s (`:468,:497`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Channel` dropdown | Picks the channel whose board is edited; closes open edit forms | `GET /api/staff/app/config` (channel names) | all | `Public board` = id `public` (`:552`) |
| `Create a CG board for this channel` form: `Template` dropdown + `Create board` (`Creating…`) | Creates and activates a board bound to the template | `POST /api/staff/cg/channels/{id}/board` `{template_id}` (`client.ts:2631`) | write | Only shown when channel has no board. Template choices: `Standard community board`, `Live lower banner`, `Schedule forward board` (`cg-board-format.ts:8-12`). Read-only users instead see EmptyState "No board on this channel yet." / "The board designer controls what the community board looks like on air — its zones, feeds, and styling. A station admin creates the board for this channel; once created, it appears here." (`:596-597`) |
| `Board template` dropdown (shown as plain `Template: <id>` to read-only users) | Changes the template immediately on selection, no confirm | `PATCH .../board` `{template_id}` | write | Audit event `board_updated`. UNVERIFIED what happens to existing zones when template changes (service just rewrites template_id, `board_service.py:259-266`). |
| `Add zone` / `Close` | Opens zone form | none | write (button hidden otherwise) | |
| Zone form: `Region` (main, lower, side, bug, background), `Zone kind` (primary, ticker, schedule, logo, sponsor, alert; `audio` shown disabled as `Board background audio — coming in a future release`), `Content source` (feed adapter, manual, schedule, emergency, image, clock), `Feed source` (only if feed adapter; `Select a feed…`), `Manual text` (only if manual), checkbox `Require operator approval of feed items before they show`, `Allowed tags (comma-separated; empty = show all)` (placeholder `events, alerts`) | Describes the zone | | | Feed adapter with no feed: red `A feed-sourced zone must name a feed.` and button disabled (`:290-294`). Info block `Future CG options`: `Live video in a zone — coming in a future release` and `Board background audio — coming in a future release` (disabled, "the current renderer does not play it"). `Content source` = image has no image picker in this form; `image_asset_ref` is never sent (UNVERIFIED effect). Manual text max 500 chars server-side, no UI limit. |
| `Add zone` (submit; `Saving…`) / `Save changes` (editing) | Adds / updates the zone | `POST .../zones` (`client.ts:2642`) / `PATCH .../zones/{zoneId}` | write | 422 shows raw server validation text (`B/board_router.py:123`, `board_service.py:294-295`). |
| Zone `Edit` / `Close` | Toggles inline edit form | none | write | |
| Zone `Delete` -> `Confirm delete?` / `Cancel` | Two-step delete; deletes the zone | `DELETE .../zones/{zoneId}` | write | Audit `zone_removed` |
| `Add feed` / `Close` | Opens feed form | none | write | |
| Feed form: `Feed kind` (rss, ical, caldav, weather, social), `Trust tier` (operator curated, partner curated, public permitted), `Feed label` (placeholder `Community news`), `Source URL` (placeholder `https://example.gov/news.rss`), `Refresh (minutes)`, `Enabled` checkbox, `Feed tags` (`Tags (comma-separated; stamped onto this feed's items)`, placeholder `events, community`) | Describes feed | | | Button disabled unless label, URL non-blank and refresh between >0 and 1440 min (`:335-338`). Red `Weather feeds must be operator or partner curated (not public).` Server rejects non-http(s) URLs (`board_models.py:132-140`). |
| `Register feed` (`Saving…`) / `Save changes` | Adds / updates feed | `POST .../feeds`, `PATCH .../feeds/{id}` | write | `Could not register the feed.` / `Could not update the feed.` on failure |
| Feed `Edit`/`Close`, `Delete` -> `Confirm delete?` | Edit/delete feed | `DELETE .../feeds/{id}` | write | Whether zones that used the feed are changed: UNVERIFIED (service just deletes the feed row, `board_service.py:394-405`) |
| Feed `Review items` / `Hide items` | Fetches the feed live and lists its current items with approval status | `GET .../feeds/{id}/items` (`client.ts:2684`); server fetches the URL, 10 s limit (`board_router.py:530-562`) | read (all three roles) | Text: `Loading feed items…`, `No items in this feed right now.`, `N pending · M approved`, badges `Approved` / `Pending`; failures `Could not load feed items.`; timeout `Feed fetch timed out after 10s.` |
| Feed item `Approve` | Records that this item may show | `POST .../feeds/{id}/items/{itemId}/approve` | write | Read-only roles see `Pending` badge instead of button. Error: `Could not approve this item. Try again.` |

## States
- Empty: `No zones yet.` (`:645`), `No feeds registered.` (`:687`), `No history yet.` (`:738`), board empty-state above.
- Loading: `Loading…` (identity or board).
- Error: `Could not verify your access — <detail>.`; `Could not load the board.`; storage 503 "Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment." (`B/board_router.py:62-65`).
- Preview warnings: `Using defaults for unconfigured zones: <kinds>.`; per zone `Feed unavailable — this zone is empty until its feed is restored.` (`:430,:444`). Preview is hidden if the preview call returns nothing.
- Read-only (support_admin): all Add/Edit/Delete buttons absent; nothing says why (no banner).

## Typical task flows
1. First time: choose channel -> `Create board` -> `Add zone` (e.g. kind ticker, source manual, type text) -> `Add zone` -> check `Live preview`.
2. Connect an outside feed: `Add feed` -> fill kind/label/URL/refresh -> `Register feed` -> `Add zone` with Content source `feed adapter` and pick the feed -> tick approval box if you want to vet items -> `Review items` -> `Approve` items.
3. Check who changed what: read `Board history` (last 20 events, e.g. `board created by <operator> · <local time>`).

## Statuses and words on this screen
| Word | Meaning |
|---|---|
| Trust tier `operator curated` / `partner curated` / `public permitted` | how trusted the feed is; weather must not be public (`board_models.py:146-148`). What each tier changes at render time: UNVERIFIED |
| Zone summary line e.g. `ticker via manual · approval required` (`cg-board-format.ts:67-74`) | one-line zone description |
| `Last fetched <time>` / `Last fetch failed: <error>` / `Not fetched yet` (`cg-board-format.ts:76-80`) | feed health |
| History lines: event kinds `board created`, `board updated`, `zone added`, `zone updated`, `zone removed`, `feed added`, `feed updated`, `feed removed`, `feed item approved` (underscores replaced by spaces; `board_service.py:242-426`) | audit trail |
Shared status words not used.

## Related settings / env / CLI / API
`/api/staff/cg/channels/{id}/{board,zones,feeds,board/preview,board/audit}` (`B/board_router.py`); Community bulletins live on CG Board; Channel Ops filler policy; `CIVICCAST_CG_DEMO_FEEDS`.

## Help-text findings
- [HELP-01] `:535-536` "The engine composites this board into the channel." — jargon; does not say when it shows (between programs as filler per `egress/bulletin_filler.py:5-7`). — "This board is what viewers see between programs on this channel."
- [HELP-02] `:62-67` vs `Sidebar.tsx:127` — support_admin can open the screen but every editing control silently disappears with no banner. — Show "You can view this board but not change it. Changing it needs the publish operator or setup admin role."
- [HELP-03] `:204-231` — labels `Region`, `Zone kind`, `Content source`, `feed adapter`, `emergency`, `bug`, `sponsor` are unexplained; values are raw enum text with underscores replaced. — add one-line helper under each ("Region = which part of the screen"), and say what each content source shows.
- [HELP-04] `:275-277` — "Require operator approval of feed items before they show" appears for every content source although it only matters for feed zones (UNVERIFIED for other sources). — show only for feed adapter.
- [HELP-05] `:384,:355` — `Trust tier`/`Feed tags`/`Allowed tags` unexplained; relationship between feed tags and zone allowed tags is only in a code comment (`board_models.py:97-98`). — "Only feed items with one of these tags will appear in this zone."
- [HELP-06] `:610` — changing `Board template` saves instantly with no confirmation or hint of effect. — add note or confirm.
- [HELP-07] `:589-593` — no button to switch a board off (API supports `active`, UI never sends it). Not a bug, but a manual should not promise it.
- [HELP-08] Header word `Designer` and nav label `CG Designer` vs title `CG Board Designer`; CG = "character generator" never spelled out anywhere in `portal-operator/src` (grep for "character generator" returns nothing). — spell out once.
- [HELP-09] No place says feeds can't be added unless a board exists (`:671` Feed panel only renders when a board exists). — empty-state text on Board should say "Create a board first, then add zones and feeds."

## Screenshot plan
(a) no board yet (write role) with Create form; (b) board with 3 zones + 1 feed + live preview + history; (c) zone form with Content source = feed adapter; (d) `Future CG options` block; (e) feed with `Last fetch failed:` message; (f) `Review items` with pending and approved items; (g) `Confirm delete?` state; (h) support_admin read-only view; (i) access note view (e.g. records_clerk by URL). Setup: admin token; a reachable RSS URL.

## UNVERIFIED / open questions
- UNVERIFIED: effect of changing template on existing zones.
- UNVERIFIED: whether deleting a feed leaves zones pointing to it (store not read).
- UNVERIFIED: what `image`, `emergency`, `clock`, `schedule` content sources render and what Trust tier changes at render time (`board_resolver.py` only partly read).
- UNVERIFIED: whether `Live preview` ever shows an image; the PNG preview endpoint exists (`board_router.py:606-632`) but this screen does not call it.
- UNVERIFIED: what the `sponsor` and `bug` kinds/regions look like on air.
