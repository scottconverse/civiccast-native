> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Assets (nav id: assets)

Console group: Review Records. Spec for the in-app help of the Assets list, the asset detail page and its panels. Written against beta.10. All paths below are under `civiccast/apps/portal-operator/src/`.

## Where the help text lives now
- `screens/AssetsScreen.tsx`: page heading and intro 218-223; search placeholder 253; filter tabs 20-26; empty list 107-110; no-match 295; list error 65, 75-76; column heads 310-317; Edit trim 418-420; Package button and role note 437-447; packaging failure 454.
- `components/assets/AssetUploadControl.tsx`: button 197; panel heading and helper 218-222; wrong-type error 127; progress 293-309; success 320-331.
- `types/asset.ts`: State words and tooltips 54-79. `components/assets/assetStatus.ts`: Status words and tooltips 53-95 (Missing file detail 71-77, Validating 84-90).
- `screens/AssetDetailScreen.tsx`: loading 142; load error 162; "Library · asset detail" 420; "Public metadata" 443; title counter 471; records-officer notice 568; retention deletion text 684-686; Save errors 730, 745; Technical card 819-822; manifest line 884; Remove from portal button 862 and dialog 945-946.
- `screens/MediaLifecyclePanel.tsx`: readiness error 100; loudness fail 138; archival 159; legal hold 171-217; replace-source dialog 253-254.
- `screens/OfflineCaptionJobsPanel.tsx`: running text 46; awaiting-review text 49; empty 121; role note 211; retry dialog 256-257.
- `screens/GenerateSummaryPanel.tsx`: no-cues 103; role note 137; retry note 203.

## Current text
| String | Where | Source line |
|---|---|---|
| "Recorded files uploaded for trim, scheduling, and publish. Files are kept untouched; trim and chapter edits are non-destructive." | List intro | AssetsScreen.tsx:222-223 |
| "Search by title or asset ID…" | Search box | AssetsScreen.tsx:253 |
| "Accepted types: MP4, MOV, MKV, WebM, AVI, or MPEG-TS. The file is added to this list once ingest validation finishes." | Upload panel helper | AssetUploadControl.tsx:220-221 |
| "It now appears in the table below as {state}. Ingest validation runs automatically; no further action is needed here." ({state} prints the raw code) | Upload success | AssetUploadControl.tsx:322 |
| "ffprobe is running on the uploaded file." | State tooltip, Analyzing | types/asset.ts:58 |
| "Validating" with "Ingest validation is analyzing the file. This usually takes under a minute." | Status, same row as State "Analyzing" | assetStatus.ts:84-88 |
| "Backing file not found on disk; relink or replace the source." | Status tooltip, Missing file | assetStatus.ts:71-77 |
| "A publish operator or setup administrator must package this recording." | Package button note | AssetsScreen.tsx:447 |
| "Durable storage is not ready." / "Open Setup, prepare durable storage, then return here." | List error | AssetsScreen.tsx:65,75 |
| "Could not load assets." / "Try again, or check the server logs for more detail." | List error | AssetsScreen.tsx:65,76 |
| "No assets yet." / "Use Upload video above, add a watch folder under Media Lifecycle Settings, or add a bundled sample from Setup." | Empty list | AssetsScreen.tsx:107-110 |
| "No assets match the current search and filter." | Filter empty | AssetsScreen.tsx:295 |
| "{n}/200 · shown to residents on the portal" | Title counter | AssetDetailScreen.tsx:471 |
| "Records officer review required. State presets provide a starting point, but local schedules, litigation holds, and official-minutes rules can require longer retention." | Retention notice | AssetDetailScreen.tsx:568 |
| "Deletion is never automatic. When this term's deadline passes, the asset is flagged into the records-clerk disposition review queue -- it stays in place until a clerk acts." | Retention term | AssetDetailScreen.tsx:684-686 |
| State row prints the raw code (`validated`) | Technical card | AssetDetailScreen.tsx:822-823 |
| "Not yet servable. Set a public manifest URL in Setup to publish live recordings." | Technical > Published/Manifest, recorded row | AssetDetailScreen.tsx:884 |
| "Residents will no longer be able to view or find it there. This only affects portal visibility -- the asset row, its media, and the Internet Archive / syndication copies are untouched." | Remove-from-portal dialog | AssetDetailScreen.tsx:945 |
| "Failed — normalize before air" | Loudness gate | MediaLifecyclePanel.tsx:138 |
| "Archival (CLAUDE.md §4.6): portal + Internet Archive + local NAS, all verified" | Archive row | MediaLifecyclePanel.tsx:159 |
| "…The current file is archived alongside the asset, not deleted, but every viewer sees the new file immediately once processing finishes." | Replace-source dialog | MediaLifecyclePanel.tsx:254 |
| "Transcribing now. Measured ~37 seconds for 11 seconds of audio on a 32 GB CPU-only reference machine — expect several minutes for a full meeting recording, not seconds." | Caption job, running | OfflineCaptionJobsPanel.tsx:46 |
| "Transcription finished. The cues are waiting in the caption review queue for an operator to approve before they publish." | Caption job, awaiting review | OfflineCaptionJobsPanel.tsx:49 |
| "This restarts transcription from scratch with a fresh attempt budget. Any partial progress from the current attempt is discarded." | Retry dialog | OfflineCaptionJobsPanel.tsx:257 |
| "No committed transcript cues yet. Approve caption review items for this recording first, then a summary can be generated from them." | AI summary card | GenerateSummaryPanel.tsx:103 |

## What the screen really does
The Assets list shows the first 50 recordings the server returns, published ones first and then the rest by asset ID; search and the tabs filter only those 50, and the screen never says so. Upload checks the file type and, on the server, whether the file is a real supported video: a good file becomes State "Validated" at once, a bad file is refused and nothing is saved. "Package for playback" makes a streamable copy and does not show the video to residents; the Publish screen does that. The detail page edits the public title, description, meeting body and retention, takes a recording off the portal, places or clears a legal hold, replaces the source file, and shows the caption job and AI summary for that recording. Most buttons are enabled for every role; a wrong-role click returns the server's error text.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | Intro implies the list is the whole library | Only the first 50 rows load, search and tabs cover only those (`schedule/router.py:245-280`; `X-Total-Count` never read). A new upload sorts after published files and can be missing from the list | blocks work |
| HELP-02 | State "Analyzing" next to Status "Validating" | Two words for one thing (`types/asset.ts:55`, `assetStatus.ts:84`) | misleading |
| HELP-03 | "ffprobe is running on the uploaded file." | Jargon; uploads are never in this state, only the schedule-migration import sets it (`migrate/service.py:295`) | cosmetic |
| HELP-04 | State prints `validated`, `pending_ingest` | Raw codes in Technical card and upload success (`AssetDetailScreen.tsx:823`, `AssetUploadControl.tsx:322`) | cosmetic |
| HELP-05 | "added to this list once ingest validation finishes" | Validation finishes before "Uploaded" shows; a refused file leaves no row; no size limit is shown (server default 10 GB, `schedule/router.py:809`) | misleading |
| HELP-06 | Package, Publish and Remove from portal are never explained | "Packaged" does not mean residents can see it; Publish screen does (`AssetsScreen.tsx:222`) | misleading |
| HELP-07 | Recorded rows show no Package button; recorded row says "Set a public manifest URL in Setup" | API packages `recorded` rows too (`router.py:86,405`); the Setup advice is stale (`AssetDetailScreen.tsx:883-884`) | misleading |
| HELP-08 | Save metadata, Remove from portal, legal hold, Replace source look available to all | Wrong role gets raw "This action requires one of these CivicCast roles: …" after the click | misleading |
| HELP-09 | "Archival (CLAUDE.md §4.6)"; "normalize before air" | Developer file reference; no control to normalize (`MediaLifecyclePanel.tsx:144,159`) | cosmetic |
| HELP-10 | Replace dialog: viewers see the new file "immediately" | Row resets to Validated but old package and publish date stay; residents keep the OLD video (`media_lifecycle_store.py:427`) | blocks work |
| HELP-11 | "Measured ~37 seconds for 11 seconds of audio on a 32 GB CPU-only reference machine" | Lab figure a volunteer cannot use | cosmetic |
| HELP-12 | "waiting in the caption review queue ... before they publish" | Nothing is attached until every English cue, then every Spanish cue, is decided (`captions/vod.py:430-480`); the screen does not say where the queue is | misleading |
| HELP-13 | "relink or replace the source" | There is no relink control; only Replace source file exists | misleading |
| HELP-14 | No link to the Manual from any panel | n/a | cosmetic |
| NEW-1 | "flagged into the records-clerk disposition review queue" (`AssetDetailScreen.tsx:684-686`) | The console has no screen for that queue; it exists only in the API (`GET /api/staff/records/disposition-queue`, manual ch.14) | misleading |

## Proposed text
Page intro (`AssetsScreen.tsx:222`): "What this is for: the library of every meeting video your station holds. Upload a file, fix its public title, make it streamable (Package for playback), and take it off the portal. Packaging does not show a video to residents; the Publish screen does. Original files are never changed; trims and chapters are saved beside them. Who can use it: anyone signed in can look; each button names the role it needs. Beta.10 shows only the first 50 recordings: published ones first, then the rest in ID order. If a new upload is not in the list, search will not find it either; ask your IT person to look it up."
After fix (paging): "Showing {n} of {total}. Use Next to see more."

Search placeholder: keep. Upload helper: "Accepted types: MP4, MOV, MKV, WebM, AVI, or MPEG-TS. CivicCast checks the file when you click Upload. If it is not a usable video you see the reason here and nothing is saved. Large files can take several minutes; your IT person sets the size limit (10 GB unless changed)."
Upload success: "It is now in the list as {State word from the table}. Next: open it to set the public title and meeting body, then Package for playback."

State tooltip, Analyzing: "CivicCast is checking the video file." Rename the State word to "Validating" so State and Status agree. Show friendly words in the Technical card and upload success (Validated, Recorded) rather than codes.
Missing file tooltip: "CivicCast cannot find this video's file. Open the recording and use Replace source file (publish operator or setup administrator)."
Package note when not allowed: "Needs the publish operator or setup administrator role. Ask your station administrator." After fix: disable the button and show this line; also show Package for Recorded rows.
Package help line (new, under the row action or in the detail card): "Package for playback makes a copy that web browsers can stream. It does not publish. To show a video to residents, approve it on the Publish screen."

Retention term text: "CivicCast never deletes a recording on its own. When the retention date passes, the recording is marked as due for a records review and stays where it is. In beta.10 there is no screen for that review list; ask your IT person to read it for the records clerk." After fix: "...it appears on the Disposition review screen."
Remove-from-portal dialog: keep the current body and add "Residents lose access right away. You can publish it again later from the Publish screen." Who: publish operator or setup administrator.
Technical > recorded row manifest line: "Not streamable yet. Use Package for playback." (after HELP-07 fix); until then: "Not streamable yet. Ask a publish operator to package it."
Loudness gate: "Failed: the sound is too loud or too quiet for broadcast (target -16 LUFS, plus or minus 1). Information only; this screen cannot fix it. Ask the person who edits audio." Archival line: "Portal, Internet Archive and local NAS (a network storage box at the station): all three copies checked."
Replace-source dialog (honest for now): "The current file is renamed and kept, not deleted. The video goes back to Validated. In beta.10 residents keep seeing the OLD video until someone packages the new file again. Do not replace the file of a published recording unless your IT person can repackage it."
After fix: "...Package for playback again; residents see the new video after you publish it."
Legal hold button hint (new): "A legal hold stops this recording from ever being flagged for deletion. Who: records clerk or support admin. Every hold and release is written to the audit log."
Caption job running: "Transcribing now. A full meeting can take longer than the meeting itself." Awaiting review: "Transcription is finished. Open Review queue in the left menu and approve, edit or reject every English caption line. Spanish lines follow. No captions are attached to this video until every line in both languages is decided."
Summary no-cues text: keep; add "Approve (not only edit) caption lines in Review queue first; only Approved lines are used."

## Notes for the coder
- Edit: AssetsScreen.tsx, AssetUploadControl.tsx, assetStatus.ts, types/asset.ts, AssetDetailScreen.tsx, MediaLifecyclePanel.tsx, OfflineCaptionJobsPanel.tsx, GenerateSummaryPanel.tsx.
- Tests that pin strings (verified by grep): `screens/AssetsScreen.test.tsx` ("ingest validation", "Analyzing", "Not ready", "Validating", "Packaged", "Use Upload video above"), `screens/OfflineCaptionJobsPanel.test.tsx` ("waiting in the caption review"), `components/assets/AssetUploadControl.test.tsx`, `screens/AssetDetailScreen.test.tsx`, `screens/MediaLifecyclePanel.test.tsx`, `screens/GenerateSummaryPanel.test.tsx`; e2e `e2e/assets-upload.spec.ts`, `e2e/asset-detail.spec.ts`, `e2e/full-ui-walkthrough.spec.ts` ("ffprobe"). The word "CLAUDE.md" appears in `tests/schedule/test_media_lifecycle_worker.py`; check whether it pins the `MediaLifecyclePanel.tsx:159` text before editing it.
- Code fixes, not text fixes: paging using `X-Total-Count` (HELP-01); repackage after replace-source or stop the publish date surviving it (HELP-10); show Package for `recorded` (HELP-07); disable controls by role (HELP-08); relink control or reword (HELP-13); a disposition-review screen (NEW-1); one vocabulary for State and Status (HELP-02).
- UNVERIFIED in the inventory: whether `ingesting` and `rejected` are ever set, so the Analyzing and Rejected tabs may always be empty.
