# Browse recordings  (nav id: public-recordings, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/RecordingsScreen.tsx`, `router.ts`, `screens/HomeScreen.tsx:764-782` (RecordingCard), `api.ts`
(line cites are RecordingsScreen.tsx unless stated). Route `#/recordings?...`.
Who can open it: everyone.

## What it is for
The searchable archive of every published meeting recording. Residents search by words, pick a year or meeting body, filter by extra station-defined fields, and page through results. The filter state lives in the URL so any search can be shared.

## What the user sees
1. H2 "Browse recordings" and "Search and replay every published meeting recording. Each page, search, and recording has its own shareable link." (239-244).
2. A search row: "Search recordings" box (placeholder "Search by title or description"), "Year" menu, "Meeting body" menu, "Search" button (247-313).
3. Optional extra menus, one per station-defined searchable field (label = the field's label, option "All") (316-345).
4. A status line and a grid of 12 cards per page (RECORDINGS_PAGE_SIZE = 12, line 27); each card: title, description or "Recording description not posted.", "Published `<date>`", button-link "Watch recording".
5. Page controls "Previous", numbered buttons, "Next" when there is more than one page (412-446).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Search recordings + Search | sets `q` in the URL | filter is done in the browser over words in title+description (68-91) | none | pressing Enter also submits |
| Year | sets `year` | menu = years of `published_at` in the data, newest first (164-172); "All years" | none | a deep-linked year with no data shows "`<year>` (no recordings)" (276-278) |
| Meeting body | sets `body` | menu = distinct `meeting_body` values (174-180); "All bodies" | none | untagged recordings never match a body filter (comment lines 7-9); ghost value shows "`<body>` (no recordings)" |
| (custom field menus) | sets `cf.<key>` | exact-match, all must match | none | only fields that the server exposes (`searchable` and `api_exposed`) appear (`types.ts:16-19`) |
| Previous / page numbers / Next | changes `page` | none | none | Previous/Next disabled at ends; current page has `aria-current="page"` |
| Retry | reloads the list | repeats `GET /api/public/search` | none | only in the error state (375-381) |
| Watch recording | opens `#/watch/<asset_id>` | none | none | |
Changing any filter resets to page 1 (215-229).

## States
- Loading: "Loading published recordings." (353).
- Normal data source: `GET /api/public/search`. If that returns HTTP 503 (search index not ready) it falls back to `GET /api/public/assets` and shows an amber note: "Showing recordings in a reduced-search mode — full search is temporarily unavailable, so some filters below may show fewer results than normal. Try again shortly for full search." (140-146,363-365). In that mode the extra-field menus are absent because the fallback has no custom fields (`types.ts:16-19`).
- Error (anything else): "Published recordings could not be loaded. Try again or contact the station." + Retry (374).
- Empty archive: "No recordings have been published yet. See what's on the channels — new meeting recordings appear here after they are published." with "what's on the channels" linking to `#/schedule` (389-393).
- Filter matches nothing: "No recordings match this filter. Clear the search or facets to browse everything." (396). There is no "Clear filters" button; the user must clear each control.
- Results line: "`N` recording(s) match this filter / page `x` of `y`" or "`N` recordings published / page ..." (404-405).

## Typical task flows
1. Type "budget", press Enter, open a card.
2. Choose Year 2025 and Meeting body "City Council"; copy the browser URL to share the result.
3. Page through with Next.

## Statuses and words on this screen
No status vocabulary beyond the strings above.

## Related settings / env / CLI / API
`/api/public/search`, `/api/public/assets`; meeting-body tags and custom fields are set on the operator side (not in this inventory).

## Help-text findings
- [HELP-20] `RecordingsScreen.tsx:396` says "Clear the search or facets" but there is no clear button, and "facets" is jargon; suggest "Try different words or choose All years / All bodies" and add a "Clear all" control.
- [HELP-21] The search only looks at title and description (88-89), not the meeting transcript, agenda item text or captions. The placeholder says so ("Search by title or description") but the intro line says "Search and replay every published meeting recording"; docs must not promise transcript search.
- [HELP-22] Cards show "Recording description not posted." for untitled-description assets (HomeScreen.tsx:769) — wording suggests an error; suggest hiding the line.
- [HELP-23] Reduced-search note (363-365) uses an em dash and "reduced-search mode"; suggest "Search is limited right now. Some filters may show fewer results. Please try again soon."
- [HELP-24] Search is case-insensitive substring only; no mention of this.

## Screenshot plan
Default view with 12 cards and pagination; one filter applied with results line; empty archive; no-match state; degraded note (needs search index down); error with Retry.

## UNVERIFIED / open questions
- UNVERIFIED: which recordings the server lists (published only, per the code comments) and how `meeting_body` and custom fields get set.
