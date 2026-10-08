> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Publish (nav id: publish)

Console group: Publish. The page heading on screen is "Publish dashboard". Spec for the in-app help of the Publish screen. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/PublishDashboardScreen.tsx` unless stated.

## Where the help text lives now
- Header: label 885; heading 887; intro 889-891. Tiles 894-919. Filter tabs 925-945 (words from `screens/status-language.ts:240-250`).
- Card facts: Canonical, Archive "IA and local NAS verified / required", Published "Not public yet" 616-638 (83).
- Surface rows: "Coming in a future release" 178; "Required" 190; "{kind} / {state}" 202-203; Simulated note 215-217; "Next step." 245; checkbox "Approve this surface" 258; override checkbox 270 and justification box 274; "Retry this surface" 301.
- Readiness panel: heading 365; "Checking readiness…" 369; error 374; next step 407.
- Caption paragraph 668-673 (shown only when a Portal row can be approved); "opt-in ... this time" paragraph 677-679; required-archive warning 684-687.
- Approve button 706; role note 729; failure text 734-737; confirm dialog title and body 743-749.
- Empty 803-807; filter-empty 956; load error 772-781.
- Menu summary: `components/shell/Sidebar.tsx:161`.
- Server messages: `civiccast/publish/router.py:452-459,470-481`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Canonical portal, archive, reach, and signed-record surfaces are tracked separately so a YouTube problem never hides the public record state." | Intro | :889-891 |
| "Resident portal, archives, and notifications" | Menu group summary | Sidebar.tsx:161 |
| "IA and local NAS verified" / "IA and local NAS required" / "Not required" | Card, Archive fact | :628-632 |
| "Required" and `canonical / archive / reach / record / audience` / `pending / approved / overridden` shown raw | Surface rows | :190, 202 |
| "Simulated — nothing was actually archived. This is not the legal archive copy. Ask an admin to enable the real provider." | Archive rows with a mock provider | :215-217 |
| "Approving the portal surface also starts offline caption transcription for this recording automatically. Expect several minutes for a full meeting recording (measured ~37s for 11s of audio on a 32 GB CPU-only reference machine) — check progress on the asset's Offline caption jobs panel." | Under rows | :668-673 |
| "Only the Portal surface is selected by default. Archive and reach surfaces (Internet Archive, local NAS, YouTube, cable package) are opt-in: tick each one you mean to publish this time." | Under rows | :677-679 |
| "Approve and Publish selected" / "Publishing selected surfaces..." | Button | :706 |
| "Publish operator role required to approve or retry surfaces." | Role note | :729 |
| "Publish stopped. {detail} Nothing else was published; correct the named issue and retry." | Failure | :734-737 |
| `Publish "{title}" to residents?` / "{n} selected surface(s) publish(es) for real: {labels}. The portal surface becomes publicly visible to residents immediately and starts offline caption transcription." or "The portal surface is not part of this approval." | Confirm dialog | :743-748 |
| "Use audit-logged archive override for this platform" | Override checkbox | :270 |
| "Publish dashboard needs a database." / "Open deployment settings, connect the CivicCast database, then reload this screen." | 503 | :772, 780 |
| "No assets are ready for publish review." / "Upload or record a meeting first. Packaged recordings will appear here with portal, Internet Archive, local NAS, YouTube, and signed-record status." | Empty | :803-807 |

## What the screen really does
It shows one card per recording with nine rows. Ticking Portal and clicking Approve and Publish selected sets the recording's public publish date, which puts it on the resident portal at once; it also queues caption transcription first, on every approval, and refuses to publish if the caption job cannot be queued. Internet Archive, local NAS and YouTube rows are simulated by default and send nothing; Podcast episode and Subscriber notifications cannot be ticked and send nothing. A second approval rebuilds the whole run, so any row not ticked again goes back to "Not run yet", even Portal, while the recording stays public. If the station's federation setting is on, an approval also posts a public notice to outside servers that cannot be recalled. The audit trail records every approval as "Operator dashboard", not the signed-in person. Only the publish_operator role can approve or retry; others can look.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "opt-in: tick each one you mean to publish this time" | A later approval resets rows not ticked again, including Portal; card can read Draft while still public (`publish/service.py:543-589,820-829`) | blocks work |
| HELP-02 | "IA and local NAS verified"; state "Archive verified" | True also when copies were simulated or overridden (`service.py:973-975`) | blocks work |
| HELP-03 | YouTube rows show success, with no Simulated note | Mock provider returns made-up URLs; nothing is sent (`syndicate/models.py:22-37`) | misleading |
| HELP-04 | "Resident portal, archives, and notifications" | Notifications send nothing in beta.10 | misleading |
| HELP-05 | Dialog and paragraphs never mention fediverse notice or irreversibility | Federation notice goes out when federation is on (`router.py:520-534`); real archive and YouTube uploads cannot be undone from CivicCast | blocks work |
| HELP-06 | "Nothing else was published" | Surfaces that finished before the error stay published | misleading |
| HELP-07 | Raw words canonical / archive / reach / record / audience, pending / approved / overridden, Required | Not defined on screen | misleading |
| HELP-08 | "Cable file package" ends "not set up (optional)" | No checkbox or Retry afterwards, even after IT sets the folder | misleading |
| HELP-09 | Tab "Reaching fewer places than planned" vs tile "Degraded" | Two phrases for one state | cosmetic |
| HELP-10 | Audit shows "Operator dashboard" | Not the person's name (`:594-595`); UNVERIFIED that no other layer replaces it | misleading |
| HELP-11 | Dialog title "to residents" when only archive rows are ticked | Body corrects it | cosmetic |
| HELP-12 | "Open deployment settings" | No such screen; backend says Setup then Prepare storage (`router.py:79-82`) | misleading |
| NEW-1 | Caption paragraph "measured ~37s for 11s of audio on a 32 GB CPU-only reference machine" (`:670-671`) | Lab figure a volunteer cannot use; same text as assets HELP-11 | cosmetic |
| NEW-2 | Confirm body when Portal is not ticked: "The portal surface is not part of this approval." | Caption job is still queued on every approval (manual ch.15; `router.py:470-481`), and the caption paragraph is hidden when no canonical row is approvable | misleading |

## Proposed text
What this is for (new, under heading): "This is where you decide what leaves the station. Each recording has a card with one row for each place it can be sent. Ticking Portal makes the recording public to residents right away."
Who can use it (new): "Anyone signed in can look. Only a publish operator can approve or retry a row. A setup administrator or support admin needs the publish operator role as well."
Warning (new, above the Approve button): "Publishing to the portal is public immediately. You can take it down later with Remove from portal on the recording's Assets page. Taking it down does not undo anything sent to other places."
Intro: "Each card is one recording. A row is one place it can go: the resident portal, an archive, an outside service or a cable file. Tick everything you want, then approve once. Approving again later resets rows you did not tick again."
After fix (HELP-01): "Approving again keeps earlier results; only the rows you tick run."
Paragraph "opt-in" (honest for now): "The Portal row is ticked by default. The other rows are not. Tick every row you want in one approval; in beta.10 a second approval resets any row you do not tick again, even Portal."
Archive fact: "Archive copies recorded", with "(simulated: nothing was archived)" when any required row is simulated or overridden. Card tile "Archive verified" renamed "Archive copies recorded".
Simulated note: keep, and add the same note on YouTube rows: "Simulated. Nothing was sent to YouTube."
Row words: Portal = "Public portal"; archive = "Archive copy"; reach = "Outside service"; record = "Cable file"; audience = "Podcast and notices". "Required" tooltip: "Needed before a public-record meeting counts as archived." Approval words: Waiting, Approved, Skipped with a reason.
Confirm dialog, portal ticked: "{n} places will be sent to for real: {labels}. The recording becomes public to residents immediately. CivicCast also starts making captions. If your station's federation setting is on, a public notice is posted to other servers and cannot be recalled. Uploads to the Internet Archive or YouTube cannot be taken back from CivicCast."
Confirm dialog, portal not ticked: "The portal is not part of this approval. CivicCast still starts making captions for this recording."
Failure text: "Publish stopped. {detail} Rows that finished before the problem stay published. Check each row, fix the named problem and retry that row."
Caption paragraph: "Approving also starts captions for this recording. A full meeting can take longer than the meeting itself. Follow progress on the recording's Offline caption jobs card (Assets). Captions are attached only after every caption line is reviewed in Review queue."
Menu summary: "Resident portal, archives, and outside services".
503: "The station's storage is not ready. Ask a setup administrator to open Setup and choose Prepare storage."
Cable file row, not set up: "Not set up. Ask your IT person to choose the cable folder; in beta.10 a recording that was skipped cannot be sent afterwards from this screen."
Override box help: "Skip a required archive copy. Write why in at least 20 characters. The reason is saved in the audit log."
Audit note (new, small print): "Beta.10 records approvals as Operator dashboard, not your name."

## Notes for the coder
- Edit `PublishDashboardScreen.tsx`, `status-language.ts`, `components/shell/Sidebar.tsx`.
- Tests that pin strings (verified by grep): `screens/PublishDashboardScreen.test.tsx` ("opt-in", "to residents", "Approve and Publish"); e2e `e2e/publish-dashboard.spec.ts` ("Canonical portal", "Archive verified", "Approve and Publish"), `e2e/full-stack-publish.spec.ts` and `e2e/real-boundary-smoke.spec.ts` ("IA and local NAS", "Approve and Publish"), `e2e/full-ui-walkthrough.spec.ts` ("opt-in"). Also `screens/ScheduleList.publish.test.tsx` and `e2e/program-guide.spec.ts` for the Schedule side. Update these together with any change to the intro, card facts or paragraphs.
- Code fixes, not text fixes: merge a new approval into the previous run (HELP-01); do not report "Archive verified" for simulated or overridden copies (HELP-02); mark the mock YouTube result simulated (HELP-03); Retry for `not_configured` rows (HELP-08); send the signed-in person, not the constant (HELP-10).
- UNVERIFIED in the inventory: what the real YouTube and Internet Archive adapters do; the dialog's rendered look.
