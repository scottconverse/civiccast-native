# Underwriting  (nav id: underwriting, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/UnderwritingScreen.tsx` (line numbers below, spot-checked with grep),
`.../screens/underwriting-format.ts`, `.../api/client.ts:3140-3300` (`affidavitExportUrl` at 3285), `.../components/EmptyState.tsx`.
Backend: `civiccast/underwriting/router.py`, `service.py`, `models.py`, `store.py`; `civiccast/auth/middleware.py:73-139`; `civiccast/egress/asrun.py:90-108`;
`civiccast/app.py:3196-3226`.
Who can open it: `Sidebar.tsx:168` `requiredRoles: ['setup_admin', 'publish_operator', 'support_admin']`. Screen-level: `MANAGE_ROLES = publish_operator, setup_admin` (Spots, Flights, Placements); `AFFIDAVIT_ROLES = support_admin` (Affidavits) (lines 70-72). A person with only one family sees the other tabs as a blue note: "This tab requires the publish operator or setup admin role. Ask your station admin for access." (lines 1405-1407) or "Affidavits require the support admin role. Ask your station admin for access." (line 1412). Other roles get "Underwriting requires the publish operator, setup admin, or support admin role. Ask your station admin for access." (lines 1168-1169). The first tab is Spots for managers, Affidavits for a support-admin-only user (line 1191). The API repeats these gates (`underwriting/router.py:70-71,169,190,...,497,537,610`). Not reachable while the recovery kit is pending.

## What it is for
Underwriting means paid-for "sponsor acknowledgment" messages (for example "Support for this program comes from Acme Co-op"). The screen keeps a list of those short videos ("spots"),
the date windows in which each should run ("flights"), a read-only list of where they were placed in the schedule ("placements"), and a per-sponsor proof-of-airing report ("affidavit") for billing.
What it records is a catalog and a billing report. See HELP-01: no code was found that actually inserts a spot into the broadcast or writes the airings the affidavit counts.

## What the user sees (top to bottom)
1. h1 "Underwriting"; text: "Manage sponsorship spots, schedule flights, see what the trafficking compiler placed, and export per-underwriter affidavits for billing. The 47 CFR 73.503 sponsor-ID boundary is enforced by your editorial attestation — content is not auto-checked." and "Date ranges: the Placements tab uses a half-open window ([From, Through)) — for a single day, pick today as From and tomorrow as Through. The Affidavits tab includes both ends of the period." (lines 1419-1429)
2. Tabs: Spots, Flights, Placements, Affidavits (lines 116-125); arrow keys move.
3. Spots tab: form "Create spot" / "Edit spot", then list "Spots" (sorted by underwriter, then id).
4. Flights tab: form "Create flight" / "Edit flight", then list "Flights" (by start date).
5. Placements tab: filters From, Through, Channel (optional), Flight (optional); table.
6. Affidavits tab: filters, three download links, table with totals.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Spot ID (placeholder `acme-15s-2026q3`) | Unique name of the spot | `spot_id` slug | publish_operator / setup_admin | Locked when editing. Lowercase letters, digits, `_`, `-`. Existing id gives 409 "Underwriting spot '...' already exists. Use PATCH to update." (`router.py:211-218`) |
| Underwriter (placeholder `Acme Co-op`) | Sponsor's business name | `underwriter` | | Free text; affidavits match it EXACTLY and case-sensitively (line 953; `service.py` `list_spots(underwriter=)`) |
| Asset ID (the :15 / :30 acknowledgment video) | Library recording id of the video | `asset_id` slug | | Not checked against real assets (loose reference); a wrong id saves fine |
| Checkbox "I attest this spot meets 47 CFR 73.503." + reminder text | Records the human's attestation | `fcc_compliant_ack` | | Reminder text (verbatim, `underwriting-format.ts:66-72`): "Per 47 CFR 73.503, underwriting acknowledgments may identify the sponsor by name, logo, location, and a value-neutral description only. Calls to action, prices, comparative or qualitative claims, and promotional language are not permitted. Tick this box only after you have reviewed the spot and confirmed it meets these rules. Content is not auto-checked — your attestation is the editorial gate." Not required to save unless the server has `CIVICCAST_REQUIRE_FCC_ACK=1`, then an unticked save fails with 422 "Station policy requires fcc_compliant_ack=true ..." (`router.py:84-117`) |
| Review notes (optional) | Free note (placeholder "What you checked; any caveats; reviewer initials + date.") | `review_notes` | | |
| Create spot / Save changes / Cancel | Saves | `POST /api/staff/underwriting/spots`, `PATCH .../spots/{id}` | | Enabled when Spot ID, Underwriter, Asset ID filled. Station fixed to `civiccast-station` (line 73) |
| Spot row: Edit; Delete -> Confirm delete (aria "Delete {id}", "Confirm delete {id}") | Two-step delete | `DELETE .../spots/{id}` | | Warning "Confirming will also delete every flight + placement that referenced this spot." (line 443). Irreversible; the affidavit history for those placements is lost |
| Spot row text | "FCC 73.503 attested." or "NOT attested — operator must attest before traffic." (line 399) | | | The second wording implies a block that only exists when the policy env is set |
| Flight ID (placeholder `acme-2026q3-pubgov`) | Unique name | `flight_id` | | Locked on edit |
| Spot (drop-down "Pick a spot…" / "Loading spots…", options `{id} — {underwriter}`) | Which spot this flight runs | `spot_id` | | Locked on edit |
| Start date / End date | Inclusive date window | `start_date`, `end_date` | | Warning "Start date must be on or before end date (inclusive window)." (line 607). Dates are plain dates; time zone not stated |
| Frequency cap (per day, optional) | Max airings per day | `frequency_cap_per_day` | | Whole number 1-1440 or blank; error "Frequency cap must be a whole number 1–1440 (or blank)." (line 628) |
| Daypart block ID (optional) | Restricts to a daypart | `daypart_block_id` | | Help: "Daypart block management is coming in a future release. For now, type the block ID you got from your scheduling team." (line 646). A block id that does not resolve causes the flight to be dropped by the compiler (`service.py` comment on `DaypartResolver`) |
| Channels (comma- or newline-separated; placeholder `pub-1, gov-1`) | Channels the flight covers | `channels` | | The server requires at least one channel (`models.py:148-154`) but the form shows no "required" marker and enables Create without one; the server then returns 422 |
| Create flight / Save changes / Cancel; flight Edit / Delete / Confirm delete | As spots | `POST /flights`, `PATCH /flights/{id}`, `DELETE /flights/{id}` | | Delete warning: "Confirming will also delete every placement that referenced this flight." (line 759) |
| Placements: From, Through (UTC), Channel (optional), Flight (optional) | Filters, default today to tomorrow | `GET /api/staff/underwriting/placements` | publish_operator / setup_admin | Needs From < Through |
| Affidavits: Underwriter (exact match), From, Through | Filters, default first to last day of this UTC month; inclusive both ends | `GET /api/staff/underwriting/affidavits` | support_admin | Query waits until a name and a valid range exist |
| Download CSV / XML / PDF (links, aria "Download affidavit CSV" etc.) | Meant to save the affidavit | plain browser link to `/api/staff/underwriting/affidavits/export?underwriter&from&to&format` (lines 1019-1048) | support_admin | See HELP-02: the link carries no sign-in header, so the server answers "Missing Authorization header. Use Bearer <staff-token>." |

## States
- Identity loading: "Loading…". Identity error: "Could not load your staff identity (...)..." (lines 1152-1159).
- Spots empty: headline "No underwriting spots yet." body "Underwriting spots are the sponsor acknowledgements this station airs between programs. Create a spot with the form above and it appears here." Flights empty: "No flights yet." / "A flight is a sponsor's run — which spot airs, on which channels, between which dates. Create a flight with the form above and airing reports build from it." (lines 1482-1483, 1559-1560)
- Loading texts: "Loading spots…", "Loading flights…", "Loading placements…", "Loading affidavit…". Error banners: "Could not create/save/delete the spot." / "...flight.", "Could not load spots/flights/placements/the affidavit." with the server detail. Server 503 "Durable storage is not ready yet."
- Placements empty: "No placements in the selected window. Placements are materialized by the trafficking compiler; they will appear here automatically once a flight is in range and the compiler runs." (lines 873-875). "automatically" is not supported by code (HELP-03).
- Affidavit not ready: "Enter an underwriter name and a valid date range to load and download the affidavit." (lines 1663-1664). Affidavit empty (blue box): "No airings recorded for {name} between {from} and {to}." then "This could mean any of:" three bullets: name does not match a spot exactly (case-sensitive), spots but no flights/overlap, flights exist but nothing aired yet (lines 1066-1082).
- Affidavit table: Aired (UTC), Channel, Spot, Asset, Placement, Duration, and line "Totals: {n} airing(s) · {h m s} ({s}s)" (lines 1090-1122).

## Typical task flows
1. Add a sponsor: Spots > fill Spot ID, Underwriter, Asset ID, read the reminder, tick the attestation, Create spot.
2. Schedule a run: Flights > pick spot, set dates, Channels `pub-1`, optional cap, Create flight.
3. Check placements: Placements > set range, read the table.
4. Bill a sponsor: Affidavits > exact sponsor name, month, read the table or press Download.
Rule on dates: Placements = From inclusive, Through excluded; Affidavits = both days included.

## Statuses and words on this screen
Not routed through `status-language.ts`. Words: "attested" / "NOT attested"; "Placement" ids look like `pl-<schedule_item_id>` (`service.py` compiler docstring). Affidavit period is read as UTC days (`service.py:522-523`).

## Related settings / env / CLI / API
`CIVICCAST_REQUIRE_FCC_ACK=1` (refuse un-attested spots), `CIVICCAST_STATION_ID`. API (all `/api/staff/underwriting/...`): `spots` (GET, POST), `spots/{id}` (GET, PATCH, DELETE), `flights` (+`/{id}`), `placements`, `affidavits`, `affidavits/export`, and `POST /compile` (publish_operator/setup_admin; takes a date, a list of candidate break slots and a time zone offset; there is NO button for it on this screen).
Data comes from the program as-run log (Reports screen) filtered to entries of kind `spot`.

## Help-text findings
- [HELP-01] Empty-state lines 1559-1560 "airing reports build from it" and 873-875 "appear here automatically once ... the compiler runs", and the whole screen premise — from code: (a) the only caller of the trafficking compiler is the manual `POST /api/staff/underwriting/compile` endpoint (`router.py:606-640`); no scheduler or program-log code calls it. (b) Nothing outside `underwriting/` reads placements (grep of `civiccast/` for `SpotPlacement`, `list_placements`, `spot_placements` outside tests/migrations finds only `app.py` wiring). (c) The playout engine never records an as-run entry of kind `spot`: `map_source_kind` returns only program, live, slate or filler (`egress/asrun.py:90-108`), yet the affidavit counts only `source_kind="spot"` entries (`service.py:539-546`). So creating spots and flights does not make anything air, and affidavits will be empty. UNVERIFIED by running (no live station). Until proven otherwise the manual must describe this as a planning list and must not tell clerks it will insert sponsor messages or produce billing proof. Suggested screen banner: "Beta: sponsor spots are recorded here but are not yet inserted into the broadcast automatically."
- [HELP-02] Affidavit "Download CSV/XML/PDF" (lines 1019-1048) — these are ordinary links (`<a href download>`), and every `/api/staff/*` route needs an `Authorization: Bearer ...` header (`auth/middleware.py:88-94`; no cookie or query-token path found). A browser link cannot send that header, so the expected result is a saved or shown error "Missing Authorization header. Use Bearer <staff-token>." instead of a file. Reports and Analytics were already converted to header-carrying downloads (`ReportsScreen.tsx:270-282`, `AnalyticsScreen.tsx:341-360`); this one was not. UNVERIFIED in a browser. Fix: use `downloadStaffBlob` like Reports. Until then do not document these buttons as working.
- [HELP-03] lines 873-875 — see HELP-01; "automatically" is unsupported.
- [HELP-04] lines 1419-1423 — jargon: "trafficking compiler", "flight", "placements", "affidavit", "47 CFR 73.503". Define each in one sentence in the manual and in a short helper line: flight = a sponsor's dates and channels; placement = a specific schedule slot a spot was assigned to; affidavit = a sponsor-ready list of every time their spot aired.
- [HELP-05] lines 397-399 "NOT attested — operator must attest before traffic." — "traffic" is broadcast jargon and the unattested spot is not actually blocked unless `CIVICCAST_REQUIRE_FCC_ACK=1` (UNVERIFIED that the compiler skips un-attested spots; the compiler is documented as honoring a policy gate, `service.py` header). Say "Not attested yet. Tick the box in Edit before this spot can be used."
- [HELP-06] Channels field (lines 652-658) — no "required" marker; the server rejects an empty list ("channels must list at least one channel slug"). Mark required and list real channel ids.
- [HELP-07] lines 292, 270, 277 — Asset ID is typed by hand with no way to pick a recording; an unknown id is accepted silently. Add a picker or say "Copy the ID from Assets".
- [HELP-08] lines 1066-1082 — good three-cause empty state, but add a fourth: "Spot airings are only counted if the station records them as spot airings (see Reports > As-Run, Source = spot)". Remove once HELP-01 is resolved.
- [HELP-09] Date semantics differ between tabs (Placements half-open, Affidavits inclusive) and are explained only in a paragraph (line 1426-1428); put a one-line hint under each date pair. Dates and times are UTC; a Mountain-time evening airing can land on the next UTC day.
- [HELP-10] Delete spot warning mentions flights and placements but not that the affidavit for that sponsor changes; also no undo. Add "This cannot be undone."

## Screenshot plan
1. Spots tab empty, then with the filled form showing the FCC reminder box and attestation checkbox.
2. A spot list with one attested and one "NOT attested" row, and the delete confirmation line.
3. Flights form with the daypart help line; flights list.
4. Placements empty state; placements with rows (needs compile via API).
5. Affidavits: not-ready text; empty three-cause box; and (if achievable) a populated table.
6. A download attempt result (HELP-02) - capture what the browser actually saves/shows.
7. Role views: `publish_operator` only (Affidavits tab note), `support_admin` only (Spots tab note).
Setup: tokens for publish_operator and support_admin; one real asset id; optional `CIVICCAST_REQUIRE_FCC_ACK=1` for the 422 text.

## UNVERIFIED / open questions
- UNVERIFIED: that no other writer produces `source_kind="spot"` as-run rows (grep for the string found only definitions and readers; the as-run outbox `reporting/asrun_outbox.py` and `asrun_recorder.py` were not read in full).
- UNVERIFIED: browser behaviour of the affidavit download links (see HELP-02).
- UNVERIFIED: whether the program-log builder ever calls the compiler (comment says "Slice 4 wires this"; no caller found).
- UNVERIFIED: how a compiled placement leads to air (no consumer found).
- UNVERIFIED: PDF layout (`service.py::export_affidavit_pdf` not read).
