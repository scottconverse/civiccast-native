# CG Designer (nav id: cgdesigner)

Console group: Run Meeting. The page heading reads "CG Board Designer"; the menu label is "CG Designer". Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/screens/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` ("Design the community board (CG Designer)") and `ops/docs-sprint/inventory/screens/cgdesigner.md`. Line numbers re-checked in `CgBoardDesignerScreen.tsx`.

## Where the help text lives now
- `CgBoardDesignerScreen.tsx`: access note 62-67 and 570; heading and subtitle 533-536; channel menu 540-552; load and error lines 562-580; create form 133-170 (label 143); no-board text 596-597; board panel 587-622; zone form 173-315; zones panel 632-661; feed form 318-410; feed panel 672-722; live preview 422-455; board history 735-740; "Saving…" 751.
- `FeedApprovalQueue.tsx` (36, 44, 110, 115, 129); `cg-board-format.ts` (template names 9-11, zone line 72, feed health 77-79); `civiccast/cg/board_router.py:58-65` (roles, storage message).

## Current text
| String | Where | Source line |
|---|---|---|
| "CG Board Designer" / "Configure the durable bulletin board: template, zones, feed sources, and a live preview. The engine composites this board into the channel." | Heading, subtitle | CgBoardDesignerScreen.tsx:533, 535-536 |
| "Channel" / "Public board" | Menu | CgBoardDesignerScreen.tsx:540, 552 |
| "Viewing and managing the CG board designer requires the publish operator, setup admin, or support admin role." | Access note | CgBoardDesignerScreen.tsx:65, 570 |
| "Could not verify your access — {detail}." / "Could not load the board." | Errors | CgBoardDesignerScreen.tsx:567, 573 |
| "Create a CG board for this channel" / "Template" / "Create board" / "Creating…" | Create form | CgBoardDesignerScreen.tsx:143, 162 |
| "Standard community board", "Live lower banner", "Schedule forward board" | Template names | cg-board-format.ts:9-11 |
| "No board on this channel yet." / "The board designer controls what the community board looks like on air — its zones, feeds, and styling. A station admin creates the board for this channel; once created, it appears here." | Read-only empty | CgBoardDesignerScreen.tsx:596-597 |
| "Board" / "Board template" (menu) or "Template: {id}" (read-only) | Board panel | CgBoardDesignerScreen.tsx:587, 608, 622 |
| "Zones" / "Add zone" / "Close" / "No zones yet." | Zones panel | CgBoardDesignerScreen.tsx:632, 635, 645 |
| "Region" / "Zone kind" / "Content source" / "Feed source" / "Select a feed…" / "Manual text" | Zone form | CgBoardDesignerScreen.tsx:202, 212, 224, 258, 270 |
| "Board background audio — coming in a future release" and the "Future CG options" block: "Live video in a zone — coming in a future release" ... "This option is disabled because the current renderer does not play it." | Zone form | CgBoardDesignerScreen.tsx:217, 236-250 |
| "Require operator approval of feed items before they show" | Zone form checkbox | CgBoardDesignerScreen.tsx:276 |
| "Allowed tags (comma-separated; empty = show all)" | Zone form | CgBoardDesignerScreen.tsx:279 |
| "A feed-sourced zone must name a feed." / "Add zone" / "Save changes" / "Saving…" | Zone form | CgBoardDesignerScreen.tsx:292, 297 |
| "Edit" / "Delete" / "Confirm delete?" / "Cancel" | Zone and feed rows | CgBoardDesignerScreen.tsx:105, 117, 125, 653 |
| "Feed sources" / "Add feed" / "No feeds registered." | Feed panel | CgBoardDesignerScreen.tsx:674, 677, 687 |
| "Feed kind" / "Trust tier" / "Feed label" (placeholder "Community news") / "Source URL" (placeholder "https://example.gov/news.rss") / "Refresh (minutes)" / "Enabled" / "Feed tags" | Feed form | CgBoardDesignerScreen.tsx:344, 354, 366, 369-370, 374, 379, 385 |
| "Weather feeds must be operator or partner curated (not public)." / "Register feed" | Feed form | CgBoardDesignerScreen.tsx:396, 401 |
| "Last fetched {time}" / "Last fetch failed: {error}" / "Not fetched yet" | Feed health | cg-board-format.ts:77-79 |
| "Review items" / "Hide items" / "Loading feed items…" / "No items in this feed right now." / "{N} pending · {M} approved" / "Approve" / "Pending" / "Approved" | Item review | CgBoardDesignerScreen.tsx:715; FeedApprovalQueue.tsx:36, 44, 110 |
| "Could not load feed items." / "Could not approve this item. Try again." | Errors | FeedApprovalQueue.tsx:115, 129 |
| "Live preview" / "Using defaults for unconfigured zones: {kinds}." / "Feed unavailable — this zone is empty until its feed is restored." | Preview | CgBoardDesignerScreen.tsx:427, 430, 444 |
| "Board history" / "No history yet." | History | CgBoardDesignerScreen.tsx:736, 738 |
| "Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment." | Server error | civiccast/cg/board_router.py:62-65 |

## What the screen really does
CG Designer sets up the board a channel shows between programs: a template, zones (one box each, such as a ticker, schedule, logo or sponsor), outside feeds, a live preview and a history of changes. Publish operators and Setup admins can change things; Support admins can look only, and the Add, Edit and Delete buttons are simply missing for them. Changing the Board template takes effect at once with no confirmation, and in the code read it only rewrites the template name, so what happens to existing zones is not confirmed. There is no way to switch a board off from here. Two zone options (live video in a zone, board background audio) are shown as "coming in a future release" and do nothing.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "The engine composites this board into the channel." | Jargon; the board shows between programs as filler when the channel's filler is Community bulletins (`civiccast/egress/bulletin_filler.py:5-7`). | cosmetic |
| HELP-02 | (nothing) | Support admin can open the screen but every edit control is hidden with no explanation (`CgBoardDesignerScreen.tsx:485-488`). | misleading |
| HELP-03 | "Region", "Zone kind", "Content source", "feed adapter", "emergency", "bug", "sponsor" | Raw terms, not explained (:202-231). | cosmetic |
| HELP-04 | "Require operator approval of feed items before they show" | Shown for every content source; it matters only for feed zones (UNVERIFIED for others). | misleading |
| HELP-05 | "Trust tier", "Feed tags", "Allowed tags" | Unexplained; how feed tags and a zone's allowed tags relate is only in a code comment (`civiccast/cg/board_models.py:97-98`). | misleading |
| HELP-06 | Board template menu | Saves on selection with no confirmation (:608-610); `board_service.py:255-270` only rewrites `template_id`. | misleading |
| HELP-07 | (nothing) | No control to switch a board off; the server supports `active` but the screen never sends it. | cosmetic |
| HELP-08 | "CG" | Never spelled out; page title, nav label and heading differ ("CG Board Designer", "CG Designer"). | cosmetic |
| HELP-09 | (nothing) | Feed panel appears only after a board exists; nothing says "create a board first". | misleading |
| NEW-1 | "A station admin creates the board for this channel" (:597) | Publish operators can also create it. | cosmetic |
| NEW-2 | "coming in a future release" options (:217, 236-250) | Described in the beta.10 screen as a promise; they do nothing today. | cosmetic |

## Proposed text
- Subtitle (:535-536): "Set up what viewers see between programs on this channel: choose a template, add zones (boxes such as a ticker, schedule or logo), connect outside feeds, and check the preview. CG means 'character generator', the part that puts text and graphics on screen."
- Who can use this (new): "Publish operator or Setup admin: create the board and change zones and feeds. Support admin: look only."
- Read-only note for Support admin (new, shown when `canWrite` is false): "You can view this board but not change it. Changing it needs the Publish operator or Setup admin role."
- Access note (:65): keep the sentence; add "Ask your station admin for access."
- Read-only empty text (:597): "This channel has no board yet. A Publish operator or Setup admin creates one. Then its zones and feeds appear here."
- Create form, add line: "Create a board first. Then you can add zones and feeds."
- Board template menu (:608): add a line: "Changing the template takes effect at once. There is no confirmation. CivicCast does not say what happens to your existing zones, so check the preview afterwards." After fix (confirm and zone handling defined): describe the behavior.
- Zone form helper lines: "Region: which part of the screen the zone sits in (Main, Lower, Side, Bug is a small corner mark, Background)." "Zone kind: what the box is for (ticker, schedule, logo, sponsor, alert)." "Content source: where its words or picture come from. Manual means text you type here. Feed adapter means an outside feed you registered. Schedule shows your program schedule. Clock shows the time." (Add the other sources only after the coder confirms what each renders.)
- Approval checkbox (:276): show only for Feed adapter zones, label: "Show a feed item only after someone approves it (use Review items under Feed sources)."
- Allowed tags (:279): "Only feed items that carry one of these tags show in this zone. Leave empty to show all items."
- Feed tags (:385): "Tags added to every item from this feed. A zone with Allowed tags shows only items with a matching tag."
- Trust tier (:354): "How much you trust this source: operator curated, partner curated, or public permitted. Weather feeds cannot be public." Add the effect of each tier only after the coder confirms it.
- "Future CG options" block (:236-250): retitle "Not available yet" and say "These two options do nothing in this version." After fix: remove or enable them.
- Delete: "Delete" then "Confirm delete?" keep; add on a feed: "Zones that use this feed are not changed. Check the zones afterwards." only after the coder confirms.
- Feed panel empty (:687): "No feeds yet. Press Add feed to connect a news, calendar, weather or social source, then add a zone that uses it."
- Board history (:736): "Board history: the last 20 changes and who made them. Times are in your computer's time zone." (confirm 20 and time zone with the coder before use).

## Notes for the coder
- Files: `CgBoardDesignerScreen.tsx`, `FeedApprovalQueue.tsx`, `cg-board-format.ts`.
- Tests that pin strings: `CgBoardDesignerScreen.test.tsx` pins "Create board" (:29), "Add zone" (:38, 53), the label 'Content source', /must name a feed/ (:52), 'Allowed tags', 'Zone kind', /Live video in a zone/i and /current renderer does not play it/i (:95-96), 'Register feed', 'Feed label', 'Source URL', 'Refresh (minutes)', 'Feed tags', /must be operator or partner curated/ (:128), /Using defaults for unconfigured zones: logo/ (:154), /Feed unavailable/ (:156) and /requires the publish operator, setup admin, or support admin role/ (:207). Keep the aria labels when you add helper text.
- Code fixes, not text fixes: show a read-only banner for Support admin (HELP-02); confirm before a template change and say what happens to zones (HELP-06); hide the approval checkbox for non-feed zones (HELP-04); add a way to switch a board off (HELP-07); allow `image_asset_ref` for the image source (the form never sends it; effect UNVERIFIED).
- Not verified: effect of a template change on existing zones; whether deleting a feed leaves zones pointing at it; what the image, emergency, clock and schedule sources and the Trust tier render on air; what sponsor and bug look like on air.
