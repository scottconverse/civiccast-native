# Review queue  (nav id: review, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`. This is the **caption review** queue (page label "Caption review").
Source files: `OP/screens/ReviewQueueScreen.tsx`, `OP/types/captions.ts`; route `OP/App.tsx:285` (`/review`, alias `/review-queue`, `OP/routes.ts:56`); nav `OP/components/shell/Sidebar.tsx:154`. Backend: `civiccast/captions/router.py`, `civiccast/captions/review.py`, `civiccast/captions/vod_job.py`, `civiccast/captions/vod.py`, `civiccast/captions/review_media.py`.

Who can open it: nav entry has no `requiredRoles`; everybody signed in can open and **read** the queue and play the audio (the GET routes carry no role dependency, `captions/router.py:149-168,190-215`). Approve, Save edit and Reject need `records_clerk` (`captions/router.py:302,339,357`). The screen mirrors that: while the identity is loading all buttons are active; once loaded and the user is not a records clerk, every box and button is disabled and a yellow note says "Caption review actions require the records clerk role. The queue stays visible for read-only review." (`ReviewQueueScreen.tsx:440,611-614`). A generic `operator`/`admin` token holds all roles (`civiccast/auth/roles.py:23-24`).

## What it is for
Caption lines (called "cues") made by speech-to-text for a recording are held here for a human to check before they become public. The reviewer sees the machine's text next to an editable copy, can listen to the audio around the cue, and approves, corrects or rejects each line. Captions are attached to a recording's public video only after every cue is decided (see Statuses). Approved cues are also what the AI summary feature reads (see summary.md).

## What the user sees
1. Label "Caption review", heading "Review queue", text "Review low-confidence captions, preserve the machine cue, and approve the text that should become part of the public record." (`:506-513`).
2. Search box "Search asset or caption text..." (aria-label "Search caption review", `:524-529`) and status tabs **All, Pending, Edited, Approved, Rejected** (`:23-29`); the page opens on **Pending** (`:414`).
3. A "Language" row: **All languages, English, Spanish**; the active one shows a count of rows loaded (`:557-601`).
4. Optional yellow bars: the role note; "{n} low-confidence cue(s) need reviewer attention. Next step: open each flagged cue, compare against the audio, then approve, edit, or reject it." (`:148-161`).
5. One card per cue (`ReviewCard`, `:246-411`): top-left the **asset id** (as a bold title) and "{review item id} / {m:ss}-{m:ss}"; top-right badges EN or ES, "Low confidence" (if flagged) and the status pill; two columns "Machine cue" (read-only) and "Reviewed text" (editable box, starts with the reviewed text if any, else the machine text); "Last note: …" if present; the audio block; for low-confidence cues a checkbox; buttons **Approve**, **Save edit**, **Reject**.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Search | Filters loaded rows by asset id, machine text or reviewed text | none | - | |
| Status tabs | Filters loaded rows by status | none (browser) | - | |
| Language tabs | Re-fetches only that language's rows | GET `/api/staff/captions/review-items?language=en\|es` | - | Others show no count (`:492-496`) |
| Load review audio | Fetches a short WAV around the cue and shows an audio player (button changes to "Loading review audio…") | GET `/api/staff/captions/review-items/{id}/clip` (`captions/router.py:190-295`) | none | Needs ffmpeg and the local media file; failure texts shown in red: server detail, or "Could not load the retained caption audio." / "The retained caption audio could not be played." (`:202,219`). 409 "This caption cue has no local meeting media to review." / "The local meeting media is missing. Relink or restore the asset, then retry." (`router.py:254,260`) |
| Checkbox "I compared this low-confidence cue with its audio evidence." | Required before Approve on a low-confidence cue | sent as `low_confidence_acknowledged` | records_clerk | Enabled only after the audio has been loaded and can play (`:350`) |
| Approve | Marks the cue approved. **Approves the stored text (the machine text, or the text from the last "Save edit"); anything typed in the box but not saved is ignored** (`:362-367`, `:453-458`; `captions/review.py:318-336`) | POST `…/review-items/{id}/approve` | records_clerk | Low-confidence cue: disabled until audio has played and the box is ticked; server also refuses (409) "This is a low-confidence caption cue. Compare it with the retained audio, then explicitly acknowledge that review before approval." or "…cannot be approved because its retained audio evidence is unavailable or invalid: {reason}". Note saved: "Approved in operator console." (or "…after audio comparison.") |
| Save edit | Stores the box text as the corrected text; status becomes "Edited" | POST `…/review-items/{id}/edit` | records_clerk | Disabled unless text changed and non-empty. Note "Edited in operator console." |
| Reject | Marks the cue rejected and discards its reviewed text | POST `…/review-items/{id}/reject` | records_clerk | **No confirmation.** Note "Rejected in operator console." Statuses can be changed again later (no state check in the store), so a rejected cue can be approved again. |
| Retry (error boxes) | Refetch, or reset the failed action | - | - | |
All three mutations refetch every list afterwards (`:442-443`).

## States
- Loading: three grey bars.
- Empty (whole queue): "No caption cues need review." / "Stable caption cues will appear here after the captions runtime emits review items. Next step: run a captioned recording or live session." (`:139-143`).
- Filter hides all: "No captions match the current search and filter." (`:636`).
- Spanish tab with zero rows: "Spanish cues appear here after English captions are approved and translated. The recording is public immediately; captions attach after review — both languages together, never English alone." (`:604-606`).
- Error: "Could not load caption review." or, for 503, "Caption review backend unavailable."; then server text; "Next step. Retry this request. If it fails again, check caption review logs in deployment settings." / "Start the CivicCast server with a connected database, then retry." (`:109-119`). The same box (same title) is used when Approve/Save edit/Reject fails (`:619-628`).
- Low-confidence cue with no retained audio: red "Audio evidence is unavailable. Approval of this low-confidence cue is blocked." (`:183-185`).
- Read-only (not records clerk): see role note.

## Typical task flows
1. Publish approval of a recording queues its offline caption job (`civiccast/publish/router.py:306,473-481`); the job transcribes (Assets > recording > "Offline caption jobs" shows "Transcribing…") and fills this queue; the job then shows "Awaiting review".
2. Open Review queue (Pending tab) -> read each Machine cue; for a flagged cue click Load review audio, listen, tick the checkbox -> Approve; for a wrong line edit the box -> **Save edit** (and then Approve if you also want it counted as approved) ; for a bad line -> Reject.
3. When no cue of a language is still Pending the system attaches the approved/edited text to the recording as the captions track (`captions/vod.py:430-480`; English first, Spanish only after English, `vod_job.py:919,1206`). Rejected cues are left out.
4. Check progress: tabs All/Pending show how many are left (the Language chip shows the count loaded).

## Statuses and words on this screen
(`status-language.ts` not used.) Cue status pills (`OP/types/captions.ts:38-46`): **Pending** (amber; not yet decided), **Approved** (green), **Edited** (green; operator-corrected text, publishable), **Rejected** (red; dropped from captions). Both Approved and Edited text become captions; Pending blocks attaching (`captions/vod.py:466-480`). Language badges EN/ES, titles "English caption review" / "Spanish caption review" (`:45`). "Low confidence" = the machine flagged the cue. Related job states (shown on Assets): Transcribing…, Awaiting review, Complete, Failed (`captions/vod_job.py:73`). For the AI summary only **Approved** cues count (`GenerateSummaryPanel.tsx:225`); Edited-but-not-approved cues are not used.

## Related settings / env / CLI / API
GET `/api/staff/captions/review-items` (filters `asset_id`, `status_filter`, `language`), `/review-items/{id}`, `/review-items/{id}/clip`; POST `/review-items/{id}/approve|edit|reject`; GET `/offline-jobs`, POST `/offline-jobs/{id}/retry`; ffmpeg required for audio; caption model staged by the installer (see AI Models screen); `CIVICCAST_*` caption worker settings not read here.

## Help-text findings
- [HELP-01] `ReviewQueueScreen.tsx:362-367` **Approve ignores text typed in "Reviewed text" unless Save edit was clicked first**; the card does not say so and there is no warning when the box differs from the saved text. A volunteer who corrects a word and clicks Approve publishes the old text. Fix: Approve should send the edited text (or disable Approve while the box has unsaved changes and say "Save edit first").
- [HELP-02] `:509-513` The page never explains that captions reach the video only after **every** cue (English, then Spanish) is approved, edited or rejected, nor which recording a cue belongs to beyond a bare asset id (`:281`, no title). Fix: add "{n} of {total} cues left for {recording title}" and the rule sentence.
- [HELP-03] `:619-628` and `:110` failures of Approve/Save/Reject are titled "Could not load caption review." Fix: "That change was not saved: {reason}".
- [HELP-04] `:118` "check caption review logs in deployment settings" — no such screen for a non-technical user; `:141-143` "captions runtime emits review items" is jargon. Fix: "Cues appear here after you approve a recording for the portal on the Publish screen (that starts captioning) and it finishes transcribing."
- [HELP-05] `:359-407` Reject has no confirmation and no explanation that a rejected line is simply left out of the captions; Approve/Reject do not explain "Edited" vs "Approved" (both publish).
- [HELP-06] `:134` Empty-state next step "run a captioned recording or live session" omits the normal path (publish a recording). `:604-606` Spanish explanation says "translated" without saying the translation is machine-made and also needs review (the same cards, ES badge).
- [HELP-07] `:354` "I compared this low-confidence cue with its audio evidence." is enabled only after the audio plays, but nothing says why the box is grey. Add "Play the audio first."
- [HELP-08] A page with thousands of cards (`:424-427` comment: "thousands of rows" for a council session) has no paging or "next unreviewed" jump; it renders every visible card at once. Fix: paging or a "Next pending" button (performance UNVERIFIED).
- [HELP-09] No link to the Manual; role note appears only after identity loads.

## Screenshot plan
1. Pending tab with 2-3 cards: a normal cue and a low-confidence cue (amber badge and the amber bar).
2. A low-confidence card before and after "Load review audio" (checkbox grey, then enabled, Approve enabled).
3. Card after Save edit (pill Edited), after Approve, after Reject.
4. Language row with Spanish selected (empty message) and with rows (ES badge).
5. Empty queue; read-only view as a non-records-clerk token; error box (stop the server or use a 503).
Setup: publish a short recording with speech so the offline caption job runs; keep ffmpeg available for audio.

## UNVERIFIED / open questions
- UNVERIFIED: when the Spanish rows are created and whether they are machine-translated (text on screen says "after English captions are approved and translated"; `queue_translated_captions` in `captions/vod.py` and `translate/service.py` not read).
- UNVERIFIED: live-session caption cues also land here (empty-state text says "live session"); the live path (`captions/runtime.py`, `tap_worker.py`) was not read.
- UNVERIFIED: performance with thousands of cards.
- UNVERIFIED: the "Edited" -> publish behavior for a cue whose text was cleared (code says a cleared text is dropped, `captions/vod.py:476-480`; the UI blocks saving an empty edit).
