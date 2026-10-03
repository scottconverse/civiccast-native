# After the meeting: assets, captions, summaries, approvals {#ch-after-meeting}

This chapter covers everything that happens to a meeting video once the meeting is over: finding it in the library, trimming it, making it ready for residents to watch, correcting its captions, reviewing the AI summary, and keeping the library healthy. It is normally done by a records clerk, a video editor, or a station volunteer. Publishing the video to residents is the next chapter: [Publishing, and what residents see](#ch-publishing).

## Before you start

You need to be signed in to the staff console (see [Signing in](#ch-signing-in)). Almost every screen in this chapter is in the left-hand menu under **Review Records**: **Assets**, **Missing Media**, **Media Lifecycle Settings**, **Review queue** and **Summary review**.

Words used in this chapter:

- An *asset* is one video in the library, with its title, details and files.
- *Packaging* means making a ready-to-stream copy of the video so residents can watch it in a web browser. It does not show the video to residents. Publishing does that.
- A *cue* is one caption line: a short piece of text with a start time and an end time.
- *Retention* is how long the station must keep a record before it may be deleted.

CivicCast gives each person one or more roles. The role decides which buttons work. In beta.10 most buttons look clickable to everyone, and a wrong-role click gives an error message such as "This action requires one of these CivicCast roles: ..." instead of being greyed out. The table lists who can do what in this chapter.

| Task | Role that can do it |
| --- | --- |
| See the Assets list, open a recording, read the Review queue | Any signed-in staff member |
| Upload a video | records_clerk, meeting_operator, support_admin |
| Edit title, description, meeting body, retention | records_clerk, meeting_operator, support_admin |
| Package for playback; replace the source file | publish_operator, setup_admin |
| Place or clear a legal hold | records_clerk, support_admin |
| Approve, edit or reject a caption cue; retry a failed caption job | records_clerk |
| Generate an AI summary | records_clerk, support_admin |
| Approve a summary | records_clerk |
| Missing Media list | meeting_operator, publish_operator, support_admin |

> **Note:** A sign-in whose token has the administrator or operator scope holds all five roles, so nothing is refused. Role differences show up when a person has a limited, role-only sign-in.

> **For IT staff:** Role names and how to create role-limited sign-ins are in Part II (security chapter) and the roles appendix.

## Find a video in the Assets list

1. In the left menu, click **Assets**.
2. To look for a video, type part of its title or its asset ID in the **Search assets** box. To narrow the list, click one of the tabs **All**, **Validated**, **Recorded**, **Analyzing** or **Rejected**.
3. Click a video's title to open its detail page.

You should see a table with the columns Title, State, Status, Duration, Size, Codec and Published. The asset ID appears in small type under each title.

The **State** and **Status** columns describe the same video in two ways.

| State | What it means |
| --- | --- |
| Validated | The file passed CivicCast's checks. It is ready to trim, package or schedule. Every upload, accepted contributor video and watch-folder file starts here. |
| Recorded | A live meeting recording that CivicCast has finished and saved. |
| Analyzing | CivicCast is still checking the file. |
| Rejected | The file failed the check. |

| Status | What it means |
| --- | --- |
| Not packaged yet | The file is validated, but residents cannot stream it yet. Use **Package for playback**. |
| Packaged | A streamable copy exists. Residents still cannot see it until it is published. |
| Published | Live on the resident portal. |
| Not servable yet | A live recording that has no streamable copy yet, so residents cannot play it. |
| Missing file | CivicCast cannot find the video file on disk. |
| Validating, Ingesting, Transcoding, Queued for transcode | CivicCast is working on the file. |

> **Known issue (beta.10):** The Assets list shows only the first 50 assets, ordered with published videos first (most recently published first), then everything else by asset ID. A new upload is not published yet, so it sorts after the published videos. The search box and the tabs search only those 50. A station with more than 50 videos can upload a file and not see it in the list. The screen does not say this and has no "next page" button. Workaround: ask IT staff to list assets through the API with a larger page size.

> **For IT staff:** The list calls `GET /api/staff/assets`, which takes `limit` (default 50, maximum 500) and `offset`, and returns the real total in the `X-Total-Count` header. See the API appendix.

![The Assets list. Each row shows a title, state, status, duration, size, codec and published date, with Upload video, a search box and tabs above it.](manual/images/operator-assets-list.png){width=90%}

*Figure: the Assets list.*

## Upload a video

Use this for a video that was not recorded by CivicCast, such as a file from a camera card or another recording system.

1. On the Assets screen, click **Upload video**.
2. In the **Video file** box, choose the video file. (While the panel is open, the **Upload video** button reads **Cancel upload**.) The accepted types are MP4, MOV, MKV, WebM, AVI or MPEG-TS (file endings .mp4, .mov, .mkv, .webm, .avi, .ts, .m2ts).
3. Check the **Title**. CivicCast fills it in from the file name, turning underscores and dashes into spaces. Change it if it is not what residents should see.
4. Click **Upload**. A progress bar shows "Uploading {file}…" and a percentage. Click **Cancel** to stop.

When it finishes you should see "Uploaded: {title}". The text below says the video now appears in the table, and the new row shows State **Validated** and Status **Not packaged yet**. No further action is needed for the check itself; CivicCast runs it before it says "Uploaded".

> **Note:** If CivicCast cannot read the file as a supported video, it refuses it and keeps nothing. The error appears in the upload panel and no row is created. The panel does not show a size limit. The server's default limit is 10 GB, set by the station's IT person.

> **Tip:** After uploading, set the title, description and **Meeting body** on the video's detail page right away (see the next section). Residents search and filter by these.

![The Upload video panel open above the Assets table, with the Title box and the Video file chooser.](manual/images/operator-assets-upload.png){width=90%}

*Figure: the upload panel.*

## Edit a video's public details

The title, description and meeting body are shown to residents on the portal. Edit them on the detail page.

1. On the Assets screen, click the video's title.
2. In the **Public metadata** card, change **Title** (up to 200 characters), **Description** (optional, up to 2000) and **Meeting body** (optional, up to 120). The meeting body is the group that held the meeting, for example "City Council". Residents filter the Recordings page by it. Leave it blank and the video is not tagged, so it never matches a meeting-body filter.
3. Click **Save metadata**. The button says "Saving…" and then "Saved".

> **Warning:** If the video is attached to a schedule item that is already published (committed to air), the save is refused. The message reads "Asset X cannot be edited: N linked schedule item(s) already published. Unpublish or cancel the named items before retrying the edit."

The same card holds the retention controls. The four cards are **Default**, **Permanent**, **Meeting (long)** and **Short**, plus an optional **Retention deadline**. The screen reminds you: "Records officer review required. State presets provide a starting point, but local schedules, litigation holds, and official-minutes rules can require longer retention." It also says deletion is never automatic: expired items are flagged for the records clerk to review. A button, **Convert to a length + unit or forever term...**, switches the card to a length-and-unit form (days, weeks, months, years or forever).

> **Known issue (beta.10):** The console has no screen that lists the videos flagged for records review. The list exists only in the API (`GET /api/staff/records/disposition-queue`), and it is a list only: the code says an action screen is a later follow-up. Ask IT staff to read it for the records clerk.

> **Note:** Below the retention controls there is a custom-fields editor for any extra fields your station has defined. It is not described here because the fields differ from station to station.

## Trim a video and mark chapters

Trimming sets where the video starts and ends. It does not change the original file.

1. Open the video's detail page and click **Edit trim & chapters**. On the Assets list you can click **Edit trim** instead, for a Validated row.
2. Use the timeline to move the playhead. The buttons step back or forward by one second (**-1s**, **+1s**) or one frame (**-1f**, **+1f**), or jump to the start and end.
3. At the moment the video should start, click **Set IN**. At the moment it should end, click **Set OUT**. You can also drag the **IN** and **OUT** handles on the timeline.
4. To mark a chapter, move to that moment and click **+ Mark**, then type a name for it. Remove a chapter with its remove button.
5. Click **Save trim & chapters**. A toast says "Saved." and the editor closes. To leave without saving, click **Discard**.

> **Known issue (beta.10):** The editor does not play the video. The preview area shows only the current time and the text "Packaged manifest lands at Sprint 0.4". You choose points by time, not by watching the picture. Play the video elsewhere to find the times, then type or step to them.

> **Known issue (beta.10):** Chapters you mark are saved with the video, but we found nothing in the packaging code that writes them into the packaged video. The resident portal shows the meeting's agenda, not these chapters (see [Publishing, and what residents see](#ch-publishing)). Do not promise residents chapter marks from this editor.

> **Warning:** For an uploaded video, the trim you save is used when the video is packaged. Set the trim before you click **Package for playback**. Once a video is packaged, the console does not offer **Package for playback** again for that row, so a later trim change does not reach the packaged copy. For a live recording, the detail page says "Saving a trim re-renders the published recording automatically."

> **Note:** The trim also applies when the video airs from the schedule on a channel.

If saving fails with a message about another writer, someone else changed the video while you were editing. Close the editor, open the video again and redo your change. If the video is already on a schedule item that is committed to air, the save is refused with the "cannot be edited ... already published" message described under [Edit a video's public details](#ch-after-meeting).

## Package a video for playback

1. On the Assets screen, find a Validated row that says **Not packaged yet**.
2. Click **Package for playback**. The button says "Packaging..." while it works.

You should see the Status change to **Packaged**. This needs the publish_operator or setup_admin role; otherwise the row says "A publish operator or setup administrator must package this recording."

CivicCast packages one video at a time. If another is already running you see "Another recording is already being packaged…". Wait and try again. If packaging fails, the message is the server's text or "Packaging failed. The original file was kept; try again."

> **Known issue (beta.10):** The list shows **Package for playback** only on Validated rows that have a stored file and no streamable copy yet. **Edit trim** shows on every Validated row, packaged or not. Live recordings are finished and packaged by CivicCast itself.

Packaged is not the same as published. Next, go to the Publish screen ([Publishing, and what residents see](#ch-publishing)).

## Take a video off the public portal

1. Open the video's detail page.
2. In the **Technical** card, next to **Published**, click **Remove from portal**.
3. Read the dialog and confirm. It says: "Residents will no longer be able to view or find it there. This only affects portal visibility -- the asset row, its media, and the Internet Archive / syndication copies are untouched."

The video disappears from the resident portal. This needs publish_operator or setup_admin.

## Check a video's readiness, hold it, or replace its file

At the bottom of the **Technical** card is the **Media lifecycle** panel.

- A **readiness badge** says Ready, Transcoding (n%), Queued for transcode, Missing, Rejected or Not ready.
- **Loudness gate** shows "OK (-x.x LUFS)", "Failed — normalize before air" or "Not checked yet". LUFS is a measure of how loud the audio is. CivicCast checks against -16 LUFS with a margin of 1. The screen has no button for fixing a failed loudness result, so the line is for information.
- **Archival** lists three copies: the portal, the Internet Archive and a local NAS (a network storage box at the station). Each shows "verified" or "not verified", and the panel ends with "Archive-complete" or "Not archive-complete yet".

To place a **legal hold**, optionally type a reason, click **Place legal hold (blocks expiry)** and confirm "Place a legal hold on this asset?". A held video cannot expire under its retention rule. To release it, click **Clear legal hold** and confirm. Both actions are recorded in an audit log. This needs records_clerk or support_admin.

To replace the video file, choose a **Replacement video file** and confirm "Replace this asset's source file?". CivicCast renames the old file aside and never deletes it, and the video goes back to State **Validated**. This needs publish_operator or setup_admin.

> **Warning:** The replace-source dialog says viewers see the new file "immediately once processing finishes". In beta.10 that is not what the code does. The replacement resets the video to Validated and clears its transcode jobs, but it leaves the old streamable copy and the publish date in place. Residents keep seeing the old video. The Assets list also hides **Package for playback** because a streamable copy still exists. Do not rely on replacing a published video's file to change what residents see.

> **For IT staff:** To rebuild the copy, an administrator can call `POST /api/staff/assets/{id}/package` for that asset. See the API appendix.

## Audio tracks, loudness plan and caption status

Three read-only cards are on the **Channels** screen, not on Assets. They describe a channel on the air, not a recording.

- **Audio tracks (SAP / descriptive)** lists any secondary audio tracks, such as a second language (SAP) or described video, each marked "on air" or "disabled". If there are none, it says "Single audio program — no secondary (SAP / descriptive) tracks configured." There is nothing to edit in the console.
- **Loudness** shows, for each output of the channel, the target loudness and standard, and a "Measured -x.x LUFS" chip. The card says each output is set to its destination's standard: cable to ATSC A/85 (-24 LKFS) and streaming to -16 LUFS. It is visible only to setup_admin and support_admin; a meeting operator sees a refusal message in the card.
- **Captions** shows whether captions are reaching the output: "Captions on", "Captions off", "Caption proof failed" or "Not verified". It reads "on" only after a recent passing check. The card says: "This proves carriage at the egress boundary; it is not a claim of FCC Part 79 compliance." It refreshes every 30 seconds.

See [Running the meeting](#ch-running-meeting) for the Channels screen.

## Offline captions: how a recording gets its captions

Captions for a recording are made in the background after you approve publishing on the Publish screen. There is no separate "make captions" button. The steps are:

1. You approve publishing the recording. CivicCast queues a caption job for it first, on every approval, even one that does not tick the Portal row. If it cannot queue the job, it refuses to publish and nothing is published. (A recording with no stored video file gets no caption job.)
2. The job transcribes the audio into English cue lines. On the video's detail page, the **Offline caption jobs** card shows **Transcribing…**. A full meeting can take several minutes, not seconds.
3. When transcription ends, the card shows **Awaiting review**. The cues are now in the **Review queue**.
4. You decide every English cue. CivicCast then makes a machine translation into Spanish and queues those cues for review too.
5. You decide every Spanish cue. Only then does CivicCast attach both caption tracks to the recording. The card shows **Complete**.

> **Note:** A published recording must carry reviewed English and Spanish captions together. There is no English-only result. Until every cue in a language is decided, nothing is attached to the video.

If the job runs out of attempts, the card shows **Failed** with the reason in the **Last error** column. A records clerk can click **Retry** and confirm "Retry this offline caption job?". This restarts transcription from scratch with a fresh attempt budget and discards partial progress. Without the records clerk role the card says "Retrying a failed job requires the records clerk role."

The job can also be held. These are the reasons CivicCast puts on the row:

- Every English cue was rejected. Open the Review queue, choose English, and edit or approve cues. If the audio is truly unusable, ask a technical administrator to cancel the job.
- Every Spanish cue was rejected. Open the Review queue, choose Spanish, and edit or approve cues. Publishing continues on its own once at least one Spanish cue is approved or edited.
- No translation model is available. The row says to install or repair it under "Settings > AI Models > Translation" and run 'civiccast doctor'. CivicCast retries a few times with growing waits. When its attempts run out the card shows **Failed**, and a records clerk must click **Retry** after the model is repaired.

## Review and correct captions

The **Review queue** (page heading "Caption review") is where a person checks the machine's caption lines before the public sees them.

1. In the left menu, click **Review queue**. It opens on the **Pending** tab. The other tabs are **All**, **Edited**, **Approved** and **Rejected**, and a **Search** box above them filters by asset ID or caption text.
2. To work on one language, click **English** or **Spanish** in the **Language** row. **All languages** shows both.
3. Each card is one cue. It shows the recording's asset ID, the cue's time range, a language badge (EN or ES) and a status. The left box **Machine cue** is the computer's text and cannot be changed. The right box **Reviewed text** is yours to edit.
4. If the cue is wrong, change the **Reviewed text**, then click **Save edit**. The status becomes **Edited**.
5. If the cue is right, click **Approve**. The status becomes **Approved**.
6. If the cue should not be shown at all, click **Reject**.

You should see the card leave the Pending tab and the status pill change. The list refreshes after every decision.

What each button really does:

| Button | Result |
| --- | --- |
| **Approve** | Marks the cue Approved. It approves the text that is already stored: the machine text, or the text from your last **Save edit**. |
| **Save edit** | Stores what is in the **Reviewed text** box and marks the cue Edited. It is available only when the text has changed and is not empty. |
| **Reject** | Marks the cue Rejected and throws away any reviewed text. A rejected cue is left out of the captions. |

Approved and Edited cues both become captions, using the reviewed text. Rejected cues are left out. Pending cues hold everything back.

> **Known issue (beta.10):** **Approve** ignores text you typed in **Reviewed text** and did not save. If you correct a word and click **Approve** without clicking **Save edit** first, CivicCast approves the old text. The screen does not warn you. Always click **Save edit** after correcting a line. After **Save edit** the cue is already counted as decided, so you do not need to click **Approve** as well. Approve it afterward only if you need the status to read Approved (see the summary section, which uses Approved cues only).

> **Warning:** **Reject** asks no question and discards the reviewed text. A rejected cue can be approved again later, which then approves the machine's original text, not your earlier correction.

### Low-confidence cues

A cue the machine was unsure of carries a **Low confidence** badge, and a yellow bar at the top says how many need attention. For these cues, **Approve** stays disabled until you do two things:

1. Click **Load review audio**. CivicCast fetches a short clip around the cue and shows an audio player. Play it.
2. Tick **I compared this low-confidence cue with its audio evidence.** This box becomes available only after the audio can play.

This audio check applies to **Approve** only. **Save edit** has no such check, so a low-confidence cue can be edited and counted as decided without anyone playing the audio.

If the audio is not available, the card says "Audio evidence is unavailable. Approval of this low-confidence cue is blocked." You cannot approve that cue until the audio is available, so ask IT staff. If the recording's media file is missing, loading the audio fails with "The local meeting media is missing. Relink or restore the asset, then retry."

### Who can use it

Everyone can read the queue and play audio. Only a records clerk can approve, edit or reject. For anyone else a yellow note says "Caption review actions require the records clerk role. The queue stays visible for read-only review." and the boxes and buttons are disabled.

![The Review queue on the Pending tab. Each card shows the Machine cue, an editable Reviewed text box, and Approve, Save edit and Reject buttons.](manual/images/operator-review-queue.png){width=90%}

*Figure: the Review queue.*

### If it did not work

| What you see | Cause and fix |
| --- | --- |
| "No caption cues need review." | There are no cues at all for the chosen language, in any tab. Cues appear after a recording is approved for publishing on the Publish screen and the caption job has finished transcribing. |
| "No captions match the current search and filter." | Cues exist, but not under the tab or search you chose. After you decide the last cue on the **Pending** tab you will see this line. Click **All**, **Edited**, **Approved** or **Rejected** to see the decided cues. |
| "Spanish cues appear here after English captions are approved and translated." | Shown beside the **Language** row when the **Spanish** choice has no cues. The Spanish cues are made only after the English pass is fully decided. The Spanish text is a machine translation and needs review too. |
| "Caption review backend unavailable." | The station's database is not connected. Tell your IT person. |
| "Could not load caption review." after you clicked a button | The change was not saved. The box has the same title for load and save errors. Read the line under it and try again. |
| "This is a low-confidence caption cue. Compare it with the retained audio, then explicitly acknowledge that review before approval." | Load and play the audio, tick the box, then Approve. |

## Review an AI summary

CivicCast can write a draft summary of a meeting from its approved caption lines. The summary is saved for a records clerk to check. In beta.10, treat this feature as unfinished.

### Make a summary

1. Approve at least some caption cues for the recording in the Review queue. Only **Approved** cues are used. Cues that are Edited but not Approved are not used.
2. Open the recording's detail page and find the **AI summary** card, under the **Offline caption jobs** card.
3. Click **Generate summary**. The chip reads "queued" and then "generating…". The screen says generating locally can take 1-6 minutes on a CPU-only station, and you can close the tab; the job keeps running.
4. When it finishes the card says "Summary generated. Review it in Summary review".

If there are no approved cues the card says "No committed transcript cues yet. Approve caption review items for this recording first, then a summary can be generated from them." You need the records_clerk or support_admin role. If the job fails, the card shows **Failed** with the reason and a **Retry** button, which only a records clerk can use. The local AI program (Ollama) must be running with the summary model installed. If it is not, the job fails and the card says "Local Ollama AI runtime is not reachable. Start Ollama and retry, or configure a different summary model in AI model settings."

### Look at a summary

1. In the left menu, click **Summary review** (page heading "Summary review", label "Summary + signed records").
2. Each card shows the asset ID, a status, the summary paragraph, and a list of **Sourced claims**. Under each claim are buttons labeled with a cue ID and its time range.
3. Click a cue button. The **Inline transcript player** box highlights that range.

The statuses are **Pending review**, **Approved**, **Rejected** and **Needs evidence**. A **Needs evidence** card has an empty paragraph and a red message: the model's output could not be tied to caption cues with timestamps. A yellow bar counts the summaries that need more evidence. The only list shown is Pending review and Needs evidence.

If nothing is waiting, the page says "No summaries need review." and tells you to use **Generate summary** on a recording's detail page.

> **Known issue (beta.10):** The **Inline transcript player** does not show the caption text and does not play audio. It shows only cue IDs and times. You cannot check a claim against the words from this page. Open the **Review queue** or the recording to read the cues.

### What Approve summary can and cannot do

> **Known issue (beta.10):** **Approve summary** most likely does not work. The button is enabled only for a Pending review summary that has at least one sourced claim, and only for a records clerk. When clicked, it sends the server three fields: an operator ID, an operator name and a note. The server accepts only the note and rejects any extra field. In our reading of the code the server should refuse the request (HTTP error 422), and the page would show a red box titled "Could not load summary review." with a technical message. We found this by reading the code, not by clicking the button on a running station. Treat the summary workflow as not usable in beta.10.

A second problem sits behind the first. If **Approve summary** did succeed, the summary would become **Approved** and disappear from this page, because the page lists only Pending review and Needs evidence. **Export signed record** is enabled only for Approved summaries, so it could no longer be reached. Nothing in the console lists, downloads or checks signed records.

What is possible today:

- You can generate a summary and read it on the Summary review page.
- You cannot reject a summary, regenerate one from this page, download a signed record, or check one. There are no buttons for them.
- Yellow-bar and refusal messages tell you to "regenerate". The AI summary card does not offer a second **Generate summary** once a job exists.

> **Warning:** Do not tell your records officer that summaries are approved or signed records exported from this screen in beta.10.

> **For IT staff:** The approve route is `POST /api/staff/summaries/{id}/approve`, which accepts `{"approval_note": ...}` only. The signed-record export is `POST /api/staff/records`, with download and verify routes under `/api/staff/records/{id}`. The signing timestamp is a deterministic test timestamp unless a real timestamp authority is configured. See the API appendix.

![The Summary review page with one Pending review card showing sourced claims and the Inline transcript player box.](manual/images/operator-summary-review.png){width=90%}

*Figure: Summary review.*

## Check for videos that are missing before a meeting

The **Missing Media** page is a warning list. It shows meetings on the schedule for the next 7 days whose video is not ready to play.

1. In the left menu, click **Missing Media**. Only meeting operators, publish operators and support admins see this entry.
2. Read each card. It names the meeting and its time, the channel, the video's asset ID and state, and gives a reason.
3. Click **Open asset** to go to the video's detail page and fix it.

The reasons are: "Referenced asset no longer exists.", "Asset is in state '{state}', not validated/recorded." and "Asset's backing file is missing." Every card shows "Not ready" whatever the reason. When nothing is wrong the page says "Nothing missing."

The page loads once when you open it. Leave it and come back to refresh. To fix a card you usually need to upload a replacement file or ask a publish operator to replace the file.

> **Known issue (beta.10):** "Every asset scheduled in the coming week is validated or recorded and ready for air" is too strong. The page checks only schedule items that are still drafts. Items already committed to air are not checked. A file deleted in the last hour may not be flagged yet, because the file check runs once an hour by default.

If you open the page with a role that is not allowed, you see "This action requires one of these CivicCast roles: meeting_operator, publish_operator, support_admin."

## Watch folders, retention rules and storage (Media Lifecycle Settings)

This page holds three station-wide settings. In the left menu it is **Media Lifecycle Settings**, shown to setup_admin, publish_operator and records_clerk.

- **Watch folders.** A watch folder is a folder on the station's computer (a local disk, a USB drive or a network share) that CivicCast checks automatically and copies new videos from. Type the folder path in **Watch folder path** or click **Browse…**, then click **Add watch folder**. A new file is imported once it has stopped growing. The original stays where it is, and the new video appears in Assets as Validated. Click **Scan now** to check immediately, or **Remove** to stop watching (files already imported stay).
- **Retention automation.** A rule sets a video's retention policy by its meeting body. Fill in **Rule name**, **Meeting body (exact match)** and **Retention policy**, then click **Add rule**. Then click **Apply rules now**.
- **Storage budget.** A read-only view of how much disk the library uses, with a table by retention policy.

Each folder row shows **Not scanned yet**, **OK** with "Last poll" and "Last ingest" times, or **Degraded** with the reason, for example a drive that was unplugged.

> **Known issue (beta.10):** Retention rules do not run by themselves, even though the card says it will "Assign a retention policy automatically by meeting series". We found no code that applies them on a schedule. They take effect only when someone clicks **Apply rules now**. A rule whose **Meeting body** is blank matches nothing. Applying a rule sets the retention policy label on every video whose meeting body matches, replacing a policy someone chose by hand on that video. We found no code in that step that recalculates the retention deadline.

> **Warning:** The **Browse…** and **Scan now** buttons need the setup_admin role, adding or removing a watch folder needs publish_operator or setup_admin, and retention buttons need records_clerk or setup_admin. The page shows every button to every role, and a wrong-role click returns an error message.

> **For IT staff:** Watch folders, upload storage and the storage budget are set up in Part II (configuration and operations chapters). If the budget card says no budget is configured, the setting is an environment variable that only IT can change.

![Media Lifecycle Settings with the Watch folders, Retention automation and Storage budget cards.](manual/images/operator-media-lifecycle-settings.png){width=90%}

*Figure: Media Lifecycle Settings.*

## If it did not work

| What you see | Cause and fix |
| --- | --- |
| `"{name}" is not a supported video file. Accepted types: MP4, MOV, MKV, WebM, AVI, or MPEG-TS.` | The file ending is not one of the accepted types. Convert the video and upload again. |
| "Durable storage is not ready." with "Open Setup, prepare durable storage, then return here." | The station's storage has not been set up. Ask a setup administrator. |
| "Could not load assets." | Click **Retry**. If it fails again, tell your IT person. |
| "Save failed." on the detail page | Another person changed the video, or a linked published schedule item blocks the edit. Reload and retry, or unpublish the named items. |
| "Another recording is already being packaged…" | CivicCast packages one video at a time. Wait and click again. |
| "This action requires one of these CivicCast roles: ..." | Your sign-in does not have the needed role. Ask your station administrator. |

## Related

- [Publishing, and what residents see](#ch-publishing)
- [Before the meeting: schedules, agendas, recording schedules](#ch-before-meeting)
- [Running the meeting](#ch-running-meeting)
- [When something looks wrong](#ch-something-wrong)

<!-- SOURCES: inventory/screens/assets.md; inventory/screens/review.md; inventory/screens/summary.md; inventory/screens/missingmedia.md; inventory/screens/medialifecycle.md; civiccast/apps/portal-operator/src/screens/{AssetsScreen,AssetDetailScreen,TrimEditorScreen,ReviewQueueScreen,SummaryReviewScreen,GenerateSummaryPanel,OfflineCaptionJobsPanel,MediaLifecyclePanel,MissingMediaScreen,MediaLifecycleSettingsScreen}.tsx; civiccast/summary/router.py:111-186 (SummaryApprovalRequest extra=forbid; approve_summary); civiccast/apps/portal-operator/src/screens/SummaryReviewScreen.tsx:10-14,234 (OPERATOR payload); civiccast/captions/review.py:318-345 and civiccast/captions/persistence.py:291-335 (approve keeps stored reviewed_text; reject clears it); civiccast/captions/vod.py:430-480 (approved/edited become cues, pending counted, rejected dropped); civiccast/captions/vod_job.py:893-1010 and 100-165 (Spanish required, hold reasons); civiccast/schedule/router.py:245-280 (limit 50, X-Total-Count), 372-470 (package uses trim_in/out); civiccast/schedule/media_lifecycle_store.py:395-460 (replace-source leaves manifest_url and published_at); civiccast/egress/source_plan.py:1092 (trim used on air); civiccast/schedule/media_lifecycle_worker.py:141-145 (-16 LUFS, tolerance 1); civiccast/publish/router.py:442-480 (caption job queued before publish) -->
