# Review queue (nav id: review)

Console group: Review Records. The page label on screen is "Caption review". Spec for the in-app help of the caption review queue. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`.

## Where the help text lives now
All in `screens/ReviewQueueScreen.tsx` unless stated.
- Label, heading, intro: 507-513. Search placeholder 528. Status tabs 24-28. Language tabs 33-36 and label 562.
- Role note 613. Low-confidence bar 157. No-audio message 184-185.
- Card: Machine cue 303; Reviewed text 311; Last note 330; Load review audio 234; audio errors 202, 219; checkbox label 354; buttons Approve 381, Save edit 393, Reject 406.
- Empty queue 139-143. Filter-empty 636. Spanish-empty 604-606.
- Error box (load and save): 110, 116-118; the same box is reused for failed Approve, Save edit and Reject 619-628.
- Server texts for low confidence and missing media: `civiccast/captions/router.py:254,260`; `civiccast/captions/review.py:318-336`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Review low-confidence captions, preserve the machine cue, and approve the text that should become part of the public record." | Intro | :511-512 |
| "Search asset or caption text..." | Search | :528 |
| "No caption cues need review." / "Stable caption cues will appear here after the captions runtime emits review items. Next step: run a captioned recording or live session." | Empty queue | :139-142 |
| "No captions match the current search and filter." | Filter empty | :636 |
| "Spanish cues appear here after English captions are approved and translated. The recording is public immediately; captions attach after review — both languages together, never English alone." | Spanish tab, no rows | :604-606 |
| "Could not load caption review." / "Caption review backend unavailable." | Error title (also after a failed Approve, Save edit or Reject) | :110 |
| "Retry this request. If it fails again, check caption review logs in deployment settings." / "Start the CivicCast server with a connected database, then retry." | Error next step | :116-118 |
| "{n} low-confidence cue(s) need reviewer attention. Next step: open each flagged cue, compare against the audio, then approve, edit, or reject it." | Yellow bar | :157-158 |
| "Machine cue" / "Reviewed text" / "Last note: …" | Card | :303,311,330 |
| "Load review audio" / "Loading review audio…" | Button | :234 |
| "I compared this low-confidence cue with its audio evidence." | Checkbox, grey until the audio can play | :354 |
| "Audio evidence is unavailable. Approval of this low-confidence cue is blocked." | Red message | :184-185 |
| "Approve" / "Save edit" / "Reject" (no hints, no confirmation) | Buttons | :381,393,406 |
| "Caption review actions require the records clerk role. The queue stays visible for read-only review." | Role note | :613 |

## What the screen really does
Machine-made caption lines ("cues") for a recording wait here until a person checks them. The Language row shows English, Spanish, or both. Approve marks a cue Approved using the text already stored: the machine text, or the text from your last Save edit. Text typed in the Reviewed text box and not saved is ignored by Approve. Save edit stores the box text and marks the cue Edited. Reject marks the cue Rejected, discards any reviewed text and asks no question. Approved and Edited cues become captions; Rejected cues are left out; Pending cues hold everything back. Captions are attached to the recording only after every cue in a language is decided, English first, then Spanish. A cue flagged low confidence cannot be approved until its audio has been loaded and played and the box is ticked; Save edit has no such check. Anyone signed in can read the queue; only a records clerk can use the buttons.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | Approve sits beside an editable Reviewed text box | Approve ignores unsaved text and approves the old text, with no warning (`:362-367,453-458`; `captions/review.py:318-336`) | blocks work |
| HELP-02 | Intro never says captions attach only when every cue (English, then Spanish) is decided | See `captions/vod.py:430-480`; cards show a bare asset ID, no recording title | misleading |
| HELP-03 | "Could not load caption review." after a failed Approve, Save edit or Reject | The change was not saved (`:619-628`) | misleading |
| HELP-04 | "check caption review logs in deployment settings"; "captions runtime emits review items" | No such screen for a clerk; jargon. Normal path: approving a recording on the Publish screen starts captioning | misleading |
| HELP-05 | Reject has no confirmation or explanation | A rejected cue is dropped; approving it later approves the machine text, not the earlier correction | misleading |
| HELP-06 | "run a captioned recording or live session"; "translated" | Normal path omitted; the Spanish text is a machine translation and needs review too | misleading |
| HELP-07 | Grey checkbox with no reason | Enabled only after the audio plays | cosmetic |
| HELP-08 | Every card renders at once | No paging or "next pending"; performance UNVERIFIED | cosmetic |
| HELP-09 | No Manual link; role note appears only after identity loads | n/a | cosmetic |

## Proposed text
What this is for (new, under the heading): "A person checks the computer-made caption lines for a recording before the public sees them."
Who can use it (new): "Anyone signed in can read the queue and play the audio. Only a records clerk can approve, edit or reject."
Intro: "Each card is one caption line (a cue) with its time range. The Machine cue box is the computer's text. Reviewed text is yours to correct. Approve, Edit and Reject every line. CivicCast attaches captions to the recording only when every English line is decided, and then every Spanish line. Until then, no captions appear on the video. Approved and Edited lines become captions. Rejected lines are left out."
Card, Reviewed text helper: "If you change this text, click Save edit. Approve uses the SAVED text, not what is typed here." After fix: "Approve uses the text in this box."
Approve hint: "Marks the line as correct as stored. Does not save changes typed in the box."
Save edit hint: "Saves your corrected text. The line counts as decided; you do not have to click Approve as well."
Reject hint and confirm (confirm after fix): "Leaves this line out of the captions and throws away your edit. You can approve it later, but that approves the original machine text."
Checkbox: "I compared this low-confidence cue with its audio evidence." with line "Click Load review audio and play it first. This box is grey until the audio can play."
Yellow bar: "{n} line(s) the computer was unsure about. Play the audio for each, then approve, edit or reject it."
Empty queue: "No caption lines to review. Lines appear after you approve a recording for the portal on the Publish screen and CivicCast finishes transcribing it. The recording's Offline caption jobs card (on its Assets page) shows Transcribing… and then Awaiting review."
Filter empty: "No lines match this tab or search. After you decide the last Pending line you will see this. Click All, Edited, Approved or Rejected to see decided lines."
Spanish empty: "Spanish lines are made by machine translation after every English line is decided. They need review too, like the English lines."
Error, load: "Caption review could not be loaded. If this repeats, tell your IT person." Error, action: "That change was not saved: {reason}." 503: "The station's database is not connected. Tell your IT person."
Role note: "You can read and play audio. Approving, editing and rejecting need the records clerk role. Ask your station administrator."
Progress line (new, after fix): "{n} of {total} lines left for {recording title}".

## Notes for the coder
- Edit `screens/ReviewQueueScreen.tsx`, `types/captions.ts` (status words) and, for the server texts, `civiccast/captions/router.py`.
- Tests that pin strings (verified by grep): `screens/ReviewQueueScreen.test.tsx` exists; e2e `e2e/caption-review.spec.ts` pins "No caption cues need review". "Stable caption cues", "Could not load caption review", "Spanish cues" and "I compared" were not found in any test.
- Code fixes, not text fixes: Approve must send the edited text or be disabled while the box differs from the saved text (HELP-01); a separate error box for failed actions (HELP-03); paging or a Next pending button (HELP-08); recording title on cards (HELP-02); a confirmation for Reject (HELP-05).
- UNVERIFIED in the inventory: when the Spanish rows are created and that they are machine-translated; whether live-session cues also land here; behavior with thousands of cards.
