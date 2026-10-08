> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Missing Media (nav id: missingmedia)

Console group: Review Records. Spec for the in-app help of the Missing Media warning list. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`.

## Where the help text lives now
- `screens/MissingMediaScreen.tsx`: small label 141-143; heading 144; intro 145-148; error heading 37; error detail 40; Retry 49; empty state 62-65; card line with raw state 96; badge 105; reason (server text) 109; Open asset 119.
- Server reason sentences: `civiccast/schedule/media_lifecycle_worker.py:859-864`.
- Nav entry and roles: `components/shell/Sidebar.tsx:143-147`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Media Lifecycle" | Small label above heading | MissingMediaScreen.tsx:142 |
| "Missing Media" | Heading | MissingMediaScreen.tsx:144 |
| "Meetings scheduled in the next 7 days whose source asset is not validated, not recorded, or missing its file. Fix these before air check." | Intro | MissingMediaScreen.tsx:146-147 |
| "{channel id} · source asset '{asset id}' · state: {asset state}" (raw codes) | Card line | MissingMediaScreen.tsx:96 |
| "🔴 Not ready" | Badge on every card | MissingMediaScreen.tsx:105 |
| "Referenced asset no longer exists." / "Asset is in state '{state}', not validated/recorded." / "Asset's backing file is missing." | Reason sentence (from server) | media_lifecycle_worker.py:859-864; shown at MissingMediaScreen.tsx:109 |
| "Open asset" | Button | MissingMediaScreen.tsx:119 |
| "Nothing missing." | Empty heading | MissingMediaScreen.tsx:62 |
| "Every asset scheduled in the coming week is validated or recorded and ready for air." | Empty text | MissingMediaScreen.tsx:64 |
| "Could not load missing-media alerts." / "Durable storage is not ready." (HTTP 503) | Error heading | MissingMediaScreen.tsx:37 |
| "Request failed: {message}" or the server's sentence | Error detail | MissingMediaScreen.tsx:40 |
| "Retry" | Error button | MissingMediaScreen.tsx:49 |

## What the screen really does
It lists schedule items that are still drafts (state `scheduled`) and start within the next 7 days (the number is a station setting) where the video cannot be used: the recording record is gone, the recording is in a state other than Validated or Recorded, or CivicCast flagged its file as missing. The list is worked out again each time the page opens and is not refreshed while you look at it. The file-missing flag comes from an hourly check, so a file deleted in the last hour may not show yet. Schedule items already committed to air are not checked at all. The only action is Open asset, which goes to the recording's detail page; fixing the file there needs the publish operator or setup administrator role.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "Every asset scheduled in the coming week is validated or recorded and ready for air." | Only draft items are checked; items already committed to air (`published`, the ones that actually air, `schedule/router.py:211-217`) are not (`media_lifecycle_worker.py:849-855`). A file deleted within the last hour is not flagged yet | blocks work |
| HELP-02 | "next 7 days"; "source asset", "validated", "air check" | The 7 is a setting (`CIVICCAST_MISSING_MEDIA_HORIZON_DAYS`, default 7); the terms are unexplained | misleading |
| HELP-03 | "🔴 Not ready" on every card; raw state codes | Same badge for all three reasons; state shows `pending_ingest` etc. (`:96,105`) | misleading |
| HELP-04 | Nothing says how to fix a card | Replace source file and Package need publish_operator or setup_admin; meeting_operator and support_admin can open this page but not fix (`media_lifecycle_router.py:83`) | misleading |
| HELP-05 | Label "Media Lifecycle" | Looks like the settings page; this is a check list | cosmetic |
| HELP-06 | Raw "Request failed: …" and the role sentence | Page never says which roles may open it | cosmetic |
| NEW-1 | "Open asset" on every card | If the reason is "Referenced asset no longer exists", the button leads to "Could not load asset." (inventory flow 2) | misleading |

## Proposed text
What this is for (new line under the heading): "A warning list of meetings on the Schedule that do not have a playable video yet. Check it before a meeting week, not during a meeting."
Who can use it (new line): "Meeting operator, publish operator, support admin. To replace a missing file you need the publish operator or setup administrator role."
Label above heading: "Schedule check".
Intro: "Meetings on the Schedule in the next 7 days whose video is not ready to play. This list covers schedule items that are still drafts. Items you have already committed to air are not checked here. The check for deleted files runs once an hour, so a new problem can take up to an hour to appear. The list does not refresh while the page is open; leave and come back."
Card line: "Channel: {channel name} · Recording: {asset id} · Status: {Validating | Rejected | Missing file | Recording not found}" using the Assets screen words.
Badge: "Not ready" with the reason beside it in plain words. Per reason:
- Missing file: "CivicCast cannot find the video file. Open the recording and replace the file, or ask a publish operator to."
- Not validated: "CivicCast has not finished checking this recording. Wait a few minutes, then reload this page. If it stays, ask your IT person."
- Recording no longer exists: "This schedule item points to a recording that was removed. Open the Schedule and pick another recording."
Empty heading: keep "Nothing missing." Empty text: "No draft schedule items in the next 7 days have a video problem. Items already committed to air are not checked here."
After fix: "No scheduled items in the next 7 days have a video problem."
Error 503: "The station's storage is not ready. Ask a setup administrator to finish storage setup under First Setup." Error 403: "This page is for meeting operators, publish operators and support admins. Ask your station administrator for the role."
Open asset: keep, add hint "Opens the recording's detail page".

## Notes for the coder
- Edit `MissingMediaScreen.tsx` only for text; the reason sentences and the per-reason hints can be added client-side by matching `row.asset_state` and `row.reason`, or changed in `media_lifecycle_worker.py:859-864`.
- Tests that pin strings (verified by grep): `screens/MissingMediaScreen.test.tsx` ("Nothing missing"). "Every asset scheduled" and "Not ready" are not pinned by that test file. Also check `tests/schedule/test_media_lifecycle_router.py` before changing server reason sentences.
- Code fixes, not text fixes: include committed (`published`) items in the check (HELP-01) and re-check them after commit; add a refresh control or refetch on focus; a role-aware fix path (HELP-04); the hourly delay (`CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS`).
- UNVERIFIED in the inventory: whether the "not validated/recorded" reason can appear in practice (depends on whether anything sets `pending_ingest`, `ingesting` or `rejected`); whether every deployment wires the missing-media reader (`media_lifecycle_router.py:939-942`).
