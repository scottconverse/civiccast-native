# Underwriting (nav id: underwriting)

Console group: Publish. Spec for the in-app help of the sponsor-spot planning screen. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/UnderwritingScreen.tsx` unless stated.

## Where the help text lives now
- Heading 1419; intro 1421-1424; date-range note 1426-1428. Wrong-role banners 1168, 1406, 1412.
- Spots: "Create spot" / "Edit spot" 259; labels 263, 278, 292, 330; attestation 317; reminder text `screens/underwriting-format.ts:66-72`; row text 398-399; delete warning 443; empty 1482-1483.
- Flights: "Create flight" 541; Flight ID 545; Spot drop-down 570; Start date 581; date warning 607; Frequency cap 612 (error 628); Daypart 634 (help 646); Channels 652; delete warning 759; empty 1559-1560.
- Placements empty 873-875.
- Affidavits: Underwriter (exact match) 953; empty box 1066-1082; not-ready text 1663; download links 1019-1048 (labels 1032, 1044).
- Role gate: `components/shell/Sidebar.tsx:168`; API `civiccast/underwriting/router.py`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Manage sponsorship spots, schedule flights, see what the trafficking compiler placed, and export per-underwriter affidavits for billing. The 47 CFR 73.503 sponsor-ID boundary is enforced by your editorial attestation — content is not auto-checked." | Intro | :1421-1424 |
| "Date ranges: the Placements tab uses a half-open window ([From, Through)) — for a single day, pick today as From and tomorrow as Through. The Affidavits tab includes both ends of the period." | Intro | :1426-1428 |
| "Spot ID"; "Underwriter"; "Asset ID (the :15 / :30 acknowledgment video)" | Spot form | :263, 278, 292 |
| "I attest this spot meets 47 CFR 73.503." | Checkbox | :317 |
| "FCC 73.503 attested." / "NOT attested — operator must attest before traffic." | Spot row | :398-399 |
| "Confirming will also delete every flight + placement that referenced this spot." | Spot delete | :443 |
| "No underwriting spots yet." / "Underwriting spots are the sponsor acknowledgements this station airs between programs. Create a spot with the form above and it appears here." | Spots empty | :1482-1483 |
| "Channels (comma- or newline-separated)" (no "required" mark) | Flight form | :652 |
| "Daypart block management is coming in a future release. For now, type the block ID you got from your scheduling team." | Flight form | :646 |
| "No flights yet." / "A flight is a sponsor's run — which spot airs, on which channels, between which dates. Create a flight with the form above and airing reports build from it." | Flights empty | :1559-1560 |
| "No placements in the selected window. Placements are materialized by the trafficking compiler; they will appear here automatically once a flight is in range and the compiler runs." | Placements empty | :873-875 |
| "Underwriter (exact match)" | Affidavit filter | :953 |
| "No airings recorded for {name} between {from} and {to}." / "This could mean any of:" | Affidavit empty | :1066, 1069 |
| "Download CSV" / "Download XML" / "Download PDF" (plain links) | Affidavit | :1032-1044 |

## What the screen really does
It keeps a catalog of sponsor acknowledgment spots (a short video plus the sponsor's name), flights (which spot, which channels, which dates), a placements list and a per-sponsor affidavit. In beta.10 it is a planning list. Nothing in the station reads placements to put a spot on the air, the only way to create placements is a manual call to the station's programming interface (no button here), and the playout engine never records an airing of kind `spot`, which is the only kind the affidavit counts. The affidavit is therefore expected to stay empty, and its three Download links are plain web links that cannot carry the sign-in the server needs, so they are expected to show "Missing Authorization header. Use Bearer <staff-token>." instead of a file. These points are from code, not from a live station. The attestation tick is a record that a person reviewed the spot; CivicCast does not check the content or the Asset ID. Spots, Flights and Placements need publish operator or setup admin; Affidavits need support admin.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "airing reports build from it"; "appear here automatically once … the compiler runs" | The only caller of the compiler is a manual API request (`underwriting/router.py:606-640`); nothing reads placements; no `spot` as-run entries exist (`egress/asrun.py:90-108`, `underwriting/service.py:539-546`) | blocks work |
| HELP-02 | Download CSV / XML / PDF | Plain links with no sign-in header; expected to show an error instead of a file (`auth/middleware.py:88-94`). Not clicked on a live station | blocks work |
| HELP-03 | "will appear here automatically" | Same as HELP-01 | blocks work |
| HELP-04 | "trafficking compiler", "flight", "placements", "affidavit", "47 CFR 73.503" | Jargon, not defined | misleading |
| HELP-05 | "NOT attested — operator must attest before traffic." | An un-attested spot saves and is not blocked unless the station setting `CIVICCAST_REQUIRE_FCC_ACK=1` is on | misleading |
| HELP-06 | Channels has no "required" mark | Server refuses a flight with no channel (`models.py:148-154`) | misleading |
| HELP-07 | Asset ID typed by hand | A wrong ID saves without warning | misleading |
| HELP-08 | Affidavit empty box lists three causes | A fourth: nothing records spot airings in beta.10 | misleading |
| HELP-09 | Date rules in one paragraph | Placements: From included, Through excluded; Affidavits: both included; all UTC | misleading |
| HELP-10 | Spot delete warning | Also changes that sponsor's records; cannot be undone | misleading |

## Proposed text
What this is for (new, under heading): "A list of sponsor acknowledgment spots (for example "Support for this program comes from Acme Co-op"), when each should run, and a report of when each aired."
Who can use it (new): "Spots, Flights and Placements: publish operator or setup admin. Affidavits: support admin."
Warning banner (new, honest for now): "Beta.10: this screen records spots and flights. It does not put a spot on the air, and the affidavit stays empty. Do not tell a sponsor that CivicCast will insert their message or produce billing proof."
After fix (compiler and playout wired): "Spots in flights are placed in the schedule and recorded when they air."
Intro: "Spot = one short sponsor video with the sponsor's name. Flight = a sponsor's run: which spot, which channels, between which dates. Placement = a specific schedule slot a spot was assigned to. Affidavit = a list of every time a sponsor's spot aired, for billing. CivicCast does not check what a spot says. Your tick on the attestation box is the only check."
Date note: "Dates and times are UTC. Placements: From is included and Through is not; for one day pick that day and the next. Affidavits: both the first and last day are included. A Mountain-time evening airing can fall on the next UTC day."
Spot Asset ID helper: "The recording's ID, copied from the Assets screen. CivicCast does not check that it exists." Underwriter helper: "The sponsor's business name. Type it the same way later: the affidavit matches it exactly, including capitals."
Attestation: keep the verbatim reminder; add "Review the spot before ticking. In beta.10 a spot without the tick still saves unless your IT person turned on the station policy."
Row text: "Attested." / "Not attested yet. Tick the box under Edit." (add "Not blocked unless station policy is on" until fixed).
Channels label: "Channels (required; separate with commas), for example pub-1, gov-1".
Spot delete warning: "Deleting a spot also deletes its flights and placements and changes that sponsor's affidavit. This cannot be undone."
Placements empty: "No placements in this range. In beta.10 placements are made only by a manual request to the station's programming interface, so this list is usually empty." After fix: "...they appear after a flight is in range and the compiler runs."
Affidavit empty: keep the three causes and add: "Spot airings are counted only if the station records them as spot airings. In beta.10 it does not, so this is expected to be empty."
Download links (honest): "Downloads are not working in beta.10. Read the totals on screen, or ask your IT person for the file." After fix: authenticated downloads.

## Notes for the coder
- Edit `UnderwritingScreen.tsx` and `underwriting-format.ts`.
- Tests that pin strings (verified by grep): `screens/UnderwritingScreen.test.tsx` ("Confirming will also delete", "Download affidavit", and the verbatim FCC reminder from `underwriting-format.ts`). "NOT attested", "No flights yet" and "No underwriting spots" are not pinned.
- Code fixes, not text fixes: header-carrying downloads like `downloadStaffBlob` in Reports (HELP-02); wire the compiler, placements and a `spot` as-run entry or label the whole screen planning-only (HELP-01); required marker and validation for Channels (HELP-06); an asset picker (HELP-07).
- UNVERIFIED in the inventory: that nothing else writes `source_kind="spot"` rows; browser behavior of the download links; whether the program-log builder ever calls the compiler; PDF layout.
