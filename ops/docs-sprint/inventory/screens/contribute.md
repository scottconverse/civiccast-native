# Contributors  (nav id: contribute, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`. The page heading on screen is "Contributor submissions".
Source files: `OP/screens/ContributeScreen.tsx` (all of it: queue, producer report, notification list), `OP/screens/contribution-format.ts` (only the `hasRole` helper is used here); route `OP/App.tsx:283` (`/contribute`, aliases `/contributors`, `OP/routes.ts:55`); nav `OP/components/shell/Sidebar.tsx:153`. Backend: `civiccast/contribute/router.py`, `civiccast/contribute/store.py`, `civiccast/contribute/models.py`. Public side that creates the submissions: `civiccast/apps/portal-public/src/screens/HomeScreen.tsx:603-734`.

Who can open it: nav entry has no `requiredRoles` (`Sidebar.tsx:153`): every signed-in operator sees it. The API is narrower and the screen has no gate of its own:
- Read queue, report, notification list: `publish_operator`, `meeting_operator`, `support_admin` (`contribute/router.py:675-681,1214-1220,1228-1234`). A `records_clerk`- or `setup_admin`-only token gets the red box "Contributor queue could not load." with the server role sentence.
- Review actions (Start review, Request changes, Accept, Send to schedule, Decline): `publish_operator`, `meeting_operator` only (`:1093`). A `support_admin` can read the queue but every action button is enabled and then fails with a 403 (shown in the same red box, see findings).
A generic `operator`/`admin` token holds all roles (`civiccast/auth/roles.py:23-24`).

## What it is for
The station's inbox for programs sent in by outside producers. A producer fills in the "Submit a program" form on the public portal home page and uploads a video; staff then review it here: ask for changes, accept it (CivicCast checks the file and copies it into the Assets library), hand it to the Schedule as a draft entry, or decline it. Contributors never get operator access (`ContributeScreen.tsx:492-495`).

## What the user sees
1. Label "Producer workflow", heading "Contributor submissions", text "Review programs from external producers, keep the broken-media gate visible, and hand accepted content to scheduling without giving contributors operator access." (`:489-495`).
2. Three number tiles: "Needs action" (submissions in Submitted, Reviewing or Needs changes), "Total submissions", "Status notices" (`:499-501`; `contribute/store.py:222-228`).
3. A search box ("Search title, producer, or tag...", aria-label "Search contributor submissions") and tabs All, Submitted, Reviewing, Needs changes, Accepted, Scheduled, Declined (`:34-42`, no tab for Published).
4. One card per submission, oldest first (`store.py:213-216`): title, "{producer} / {organization or contact name}", mono line "{submission id} / requested {date}" ("Not requested" if none; "Unreadable date" if the producer typed a bad date, `:57-67`), status pill, the producer's description, three small facts **Media** ("{file name} / {n} KB"), **Media gate** and **Agreement** ("{agreement id} / {version}", or "missing / -"), tag chips, then five editable boxes (Review title, Review tags, Review description, "Operator note or change request", "Decline reason") and the action buttons.
5. After the cards, if any exist: "Producer activity" tiles ("{n} submitted / {n} scheduled / {n} declined" per producer, `:113-139`) and "Status notification outbox" (the last 6 notices: kind, time, "{target} / {state}", message, `:143-177`).

## Controls and what they do
All buttons call POST `/api/staff/contribute/submissions/{id}/review` (`router.py:1074`) with an `action`; all are disabled while any review is running. There are **no confirmation dialogs**.
| Control (exact label) | What it does | Enabled when | Notes |
|---|---|---|---|
| Start review | Marks "under review" and saves the operator note | state = Submitted (`:315`) | Contributor notice queued: "An operator is reviewing your program." |
| Request changes | Saves edited title/description/tags and the note (default "Changes requested from operator review queue.") and sets "needs changes" (`:325-331`) | Submitted, Reviewing, Needs changes | The only way the contributor learns what to fix is this note — see findings on notifications |
| Accept | Saves edits, then the **server runs ffprobe on the uploaded file**; a corrupt/unsupported file is refused (HTTP 422, state unchanged); otherwise the file is **copied** into the library as a new asset in state `validated` with ID `contributor-{submission}-{random}`, and the Media gate becomes "passed" (`router.py:727-919`) | Submitted, Reviewing, Needs changes | The contributor's original stays in the intake folder. Needs ffprobe installed (503 otherwise) and `CIVICCAST_UPLOAD_DIR` |
| Send to schedule (+ "Minutes" box, default 30, minimum 60 s) | Creates a **schedule entry** for the new asset: mode premiere, channel = the submission's channel, start = the requested air date or **right now** if none, length = Minutes (`:350-355,448-457`; `router.py:922-974`) | state = Accepted only | A schedule conflict returns 409 "Schedule conflict on channel '…': …". The entry is created as a draft (`scheduled`); only `published` items air, and publishing happens with Commit-to-Air on the Schedule screen (`civiccast/egress/source_plan.py:507-509`) |
| Decline | Sets "declined" with the reason (default "Declined from operator review queue."); if the submission already had a schedule entry, that entry is cancelled first and the decline is refused if the cancel cannot be done (`router.py:977-1040`) | not Declined, Scheduled or Published (`:374`) | Declining a published item: 409 "Cannot decline a submission that has already been published." |
| Search / tabs | Filter in the browser by title, producer name or tag / by state | - | - |
| Retry (red error box) | Clears the review error, or refetches the queue | - | The box title is always "Contributor queue could not load." (`:97`) even when the failure was a review action |

## States
- Loading: one grey pulsing bar.
- Empty: "No contributor submissions are waiting." (`:560`). Filter/search hides all: "No contributor submissions match the current filter." (`:568`).
- Error: "Contributor queue could not load." + server text + "Retry" (`:97-108`).
- Producer activity and notification boxes are simply absent when empty.
- Offline: the browser error text appears in the same red box.

## Typical task flows
1. New submission: open page -> read card -> "Start review" -> adjust title/description/tags if needed -> "Accept" -> state Accepted and a new asset exists in Assets (Validated).
2. Schedule it: "Send to schedule" (set Minutes) -> state Scheduled -> go to Schedule, find the new entry, Commit to Air (the screen does not say this).
3. Ask for changes: type in "Operator note or change request" -> "Request changes".
4. Refuse: type reason in "Decline reason" -> "Decline".
Public side (for the manual): the producer opens the public portal home page, section "Submit a program" (`HomeScreen.tsx:603-604`), agrees to the agreement, uploads media, submits, and receives a receipt token; "Check submission status" (`:716`) shows the contributor-safe status.

## Statuses and words on this screen
(`status-language.ts` not used.) Submission pill = state with underscore replaced, upper-cased by CSS (`:85`): SUBMITTED, UNDER REVIEW, NEEDS CHANGES, ACCEPTED, DECLINED, SCHEDULED, PUBLISHED (`contribute/models.py:18-26`). Tab "Reviewing" = UNDER REVIEW. Colors: declined red; accepted/scheduled/published green; needs changes amber; others grey (`:69-76`). Media gate values: "not run", "passed", "failed", "override accepted" (`models.py:28`); this console never sends an override, so only "not run" and "passed" occur. Legal transitions: accept from Submitted/Under review/Needs changes; schedule only from Accepted; Scheduled/Published cannot go back to review (`store.py:701-734`). Contributor-facing messages queued per state (`store.py:840-858`): e.g. Scheduled = "Your program has a real spot on the schedule and will air automatically."

## Related settings / env / CLI / API
`CIVICCAST_CONTRIBUTOR_STORE_PATH` (a JSON file `contributor-submissions.json` in the storage folder, `store.py:47,447-453`), `CIVICCAST_CONTRIBUTOR_UPLOAD_DIR` (intake folder), per-file / per-address / folder-total upload caps and rate limits (`router.py:95-160,321-400`), `CIVICCAST_UPLOAD_DIR`, `CIVICCAST_UPLOAD_MAX_BYTES`. API: public `/api/public/contribute/{agreements/current,uploads,submissions,submissions/{id}/status}`; staff `/api/staff/contribute/{submissions,submissions/{id},submissions/{id}/review,reports/producers,notifications/outbox}`.

## Help-text findings
- [HELP-01] `ContributeScreen.tsx:97` every failure, including a failed Accept/Decline/Schedule or a 403 for a support admin, is titled "Contributor queue could not load." Fix: a separate box "That action did not go through: {reason}".
- [HELP-02] `contribute/store.py:855` (shown to the contributor and listed in "Status notification outbox") says a scheduled program "will air automatically", but "Send to schedule" only creates a draft entry; it airs after Commit-to-Air (`egress/source_plan.py:507-509`). Operators are not told that step is still theirs. Fix: button hint "Creates a draft entry on the Schedule. Commit it there to put it on air." and change the contributor wording.
- [HELP-03] `ContributeScreen.tsx:143-153` "Status notification outbox" and "Status notices" suggest messages were sent. Notices are only recorded in the submission file; no code outside `civiccast/contribute/` reads them (`grep notifications_sent` / `notification_outbox`), no mail is sent from here. Contributors see status only by pasting their receipt token on the public "Check submission status" box. Fix: label "Status messages (not emailed)" and tell producers to keep the receipt.
- [HELP-04] `:353-355` "Send to schedule" uses the requested air date or the current time, the channel stored on the submission (the public form always sends channel `public`, `HomeScreen.tsx:273`), and 30 minutes; none of this is shown before clicking. Fix: show "Channel: {id}, start: {date}" under the button and warn when no date was requested.
- [HELP-05] `:296,300-303` "Decline reason" and "Operator note" are not explained: are they shown to the producer? Code: the decline reason is returned in the contributor status (`store.py:207`); notes are not visible to producers (UNVERIFIED, see below). Fix: say who sees each box.
- [HELP-06] `:341-346` "Accept" does not say it will check the file and copy it into the library, that a bad file is refused, or that the asset then appears in Assets. `:231-234` "Media gate" prints `not run`/`passed` without explanation. Fix: hint text on the buttons and a tooltip on "Media gate".
- [HELP-07] Page heading "Contributor submissions" vs nav "Contributors"; label "Producer workflow"; "Agreement: {id} / {version}" shows internal ids. Fix: "Agreement accepted: {title}, version n".
- [HELP-08] The page never says where producers submit (public portal home page, "Submit a program") or gives a link/copy button to give to producers. Add one sentence and a link.
- [HELP-09] `:34-42` no "Published" tab although that state exists; Accept/Decline/Send to schedule have no confirmation, and Decline of a Scheduled/Accepted item cancels a schedule entry silently.
- [HELP-10] No link to the Manual on this page; the nav shows the page to roles that cannot use it (records_clerk, setup_admin) and shows actions to roles that cannot act (support_admin).

## Screenshot plan
1. Empty queue.
2. Queue with one card in each of Submitted, Under review, Needs changes, Accepted, Scheduled, Declined. Setup: submit 3-4 test programs through the public home page "Submit a program" form, then drive them through the buttons; use a small valid MP4 and one corrupt file for the Accept error.
3. Card detail showing Media, Media gate (not run, then passed) and Agreement.
4. Producer activity tiles + notification outbox.
5. The red error box after a failed Accept (corrupt file) and after a 403 (support_admin token).

## UNVERIFIED / open questions
- UNVERIFIED: whether producers can see the "Operator note" text (public status model `PublicSubmissionStatus` fields not fully read; `store.py:200-212` shows `decline_reason` and a status message).
- UNVERIFIED: whether channel `public` exists on a normal station; if not, "Send to schedule" may fail or create an entry on a channel nobody watches (the schedule store's channel check was not read).
- UNVERIFIED: that "Needs action" and the pills update without a reload (they refetch after each action via `invalidate`, `ContributeScreen.tsx:413-417`; page does not poll).
- UNVERIFIED: whether the Schedule screen labels the new entry so an operator can tell it came from a contributor (notes text is "Created from contributor review queue.", `:455`).
