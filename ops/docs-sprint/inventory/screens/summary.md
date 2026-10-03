# Summary review  (nav id: summary, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`. Page label on screen: "Summary + signed records".
Source files: `OP/screens/SummaryReviewScreen.tsx`, `OP/components/review/SourcedClaimList.tsx`, `OP/components/review/TranscriptCuePlayer.tsx`, `OP/types/summary.ts`. The part that **creates** summaries lives on the asset page: `OP/screens/GenerateSummaryPanel.tsx` (documented in assets.md, repeated here for the flow). Route `OP/App.tsx:287` (`/summary`, alias `/summary-review`, `OP/routes.ts:57`). Nav `OP/components/shell/Sidebar.tsx:155`. Backend: `civiccast/summary/router.py`, `civiccast/summary/store.py`, `civiccast/summary/generate.py`, `civiccast/summary/job.py`, `civiccast/records/router.py`, `civiccast/records/exporter.py`.

Who can open it: the nav entry has no `requiredRoles`, so every signed-in operator sees and can read it. GET `/api/staff/summaries/review-items` has no role dependency (`summary/router.py:117-125`).
- Approving needs `records_clerk` (`summary/router.py:163`).
- Exporting the signed record needs `records_clerk` (`records/router.py:80`).
- Creating a summary needs `records_clerk` or `support_admin` (`summary/router.py:133,192,217`).
- The screen disables Approve and Export unless the identity is a records clerk. It enables them while the identity is still loading (`SummaryReviewScreen.tsx:231`).
- After loading, a non-clerk sees: "Summary approval and signed-record export require the records clerk role. Evidence remains readable." (`:267`).
- A generic `operator`/`admin` token holds all roles (`civiccast/auth/roles.py:23-24`).

## What it is for
A checkpoint for AI-written meeting summaries. A summary is made from the approved caption cues of one recording, and every claim must point to timestamped cues. A records clerk checks the claims against the transcript, approves the summary, and exports a signed PDF/A-3B record. Summaries the system could not support with evidence are listed as "Needs evidence" and cannot be approved.

## What the user sees
1. Label "Summary + signed records", heading "Summary review", and the text "Approve only summaries whose quantitative claims link to transcript cue timestamps, then export the PDF/A-3B signed-record artifact for local record review." (`:254-261`).
2. The role note (see above). Then, optionally, a yellow bar: "{n} summary needs/items need more evidence before export. Next step: regenerate from committed transcript cues or add timestamp-backed source ranges before approving." (`:98-111`). It counts summaries that are "Needs evidence" or have no claims.
3. One card per summary (`SummaryCard`, `:114-214`):
   - A bold meeting id (this is the **asset id**), "{summary id} / {model tag}", and a status pill.
   - A red box with the operator message when present (`:154-162`).
   - The narrative paragraph.
   - Left: "Sourced claims" (claim text, then one button per source range labeled "{cue id} {m:ss-m:ss}").
   - Right: a box "Inline transcript player" with "Transcript seek target" and the cue ranges listed as "{cue id}: {m:ss}-{m:ss}".
   - Buttons **Approve summary** and **Export signed record**.
   - After export, a green box.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Source-range buttons ("{cue id} {m:ss-m:ss}") | Highlights that range in the "Inline transcript player" box | none (browser only) | - | The box shows only the cue id and times, **not the transcript text**, and plays no audio (`TranscriptCuePlayer.tsx:20-47`) |
| Approve summary | Marks the summary approved and records who approved it | POST `/api/staff/summaries/{id}/approve` (`summary/router.py:159-186`). The server stores the signed-in operator's id/name and the note | records_clerk | Enabled only for status Pending review **with at least one sourced claim** (`:137,176-178`). Sends `{operator_id:"operator-console", operator_display_name:"Operator console", approval_note:"Approved after checking sourced-claim transcript links."}` (`:10-14,234`). **See HELP-01: the server model accepts only `approval_note`** |
| Export signed record | Builds the PDF/A-3B signed record from the approved summary and a timestamp proof | POST `/api/staff/records` with `{summary_id, summary_status}` (`records/router.py:75-132`) | records_clerk | Enabled only when status is Approved (`:138`). Success box: "Signed record exported: {record id}. Digest {sha256…}. The server validates the PDF/A-3B artifact; timestamp authority remains deterministic unless a real authority is configured." (`:206-209`). 409 "Approve the sourced summary before exporting a signed record. Open the summary review item, verify timestamp evidence, then approve." 409 "PDF/A export dependencies are not installed…" |
| Retry (error box) | Refetch / reset | - | - | The box title is "Could not load summary review." even when Approve or Export failed (`:61,273-281`) |

There is no Reject button, no regenerate button, no download button and no "verify" button on this page.

## States
- **Loading:** two grey bars.
- **Empty:** "No summaries need review." / "Next step: open a recording's asset detail page and use the "Generate summary" action there (next to its offline caption jobs) to start one from its committed transcript cues. New pending summaries and evidence refusals will appear here once generation completes." (`:87-92`).
- **Error:** "Could not load summary review." + server text + "Next step. Retry this request. If it fails again, check summary review logs and confirm the CivicCast database is connected." (`:61-67`).
- **Needs-evidence card:**
  - A red message: "Summary refused because the model output could not be tied to committed transcript timestamp evidence. Review the transcript and regenerate after correcting missing or ambiguous cues. Next step: regenerate after adding transcript evidence for each quantitative claim." (server `summary/generate.py:127-134` + `:159-160`).
  - An empty narrative paragraph.
  - "This summary has no sourced claims. Next step: regenerate the summary from committed transcript cues before approval." (`SourcedClaimList.tsx:24-25`).
- **List contents:** only summaries in status Pending review or Needs evidence (`summary/store.py:54-59,148`).

## Typical task flows
1. **Make a summary (Assets):**
   - Open the recording, then the "AI summary" card, then "Generate summary". This needs at least one **Approved** caption cue (see review.md).
   - The chip reads "queued" or "generating…" for 1-6 minutes on a CPU-only PC (`GenerateSummaryPanel.tsx:24-27`).
   - Then: "Summary generated. Review it in Summary review".
   - The job finishes as "done" even when the result is "Needs evidence" (`summary/job.py:30-39`).
2. **Review:** open Summary review, read the narrative and each claim, click each cue button, then Approve summary.
3. **Export:** the card should now show Export signed record; click it and note the record id and digest. The code suggests step 3 cannot be done from this page (see HELP-02).

## Statuses and words on this screen
(`status-language.ts` is not used.)
- Pills from `OP/types/summary.ts:6-11`:
  - **Pending review** (amber)
  - **Approved** (green)
  - **Rejected** (red)
  - **Needs evidence** (red; internal name `refused`)
- "Rejected" is declared, but no route in `summary/router.py` or the store sets it.
- Claim types in the data (for example "quantitative") are not shown on screen.
- Related job chips on Assets: queued, generating…, done, failed (`GenerateSummaryPanel.tsx:77-90`).

## Related settings / env / CLI / API
- The local Ollama runtime and the summary model (see the AI Models screen; 503 text `OLLAMA_NOT_CONFIGURED_MESSAGE`).
- Summary routes:
  - GET `/api/staff/summaries/review-items`
  - POST `/api/staff/summaries/{id}/approve`
  - POST `/api/staff/summaries/jobs`
  - GET `/api/staff/summaries/jobs`
  - POST `/api/staff/summaries/jobs/{id}/retry`
  - POST `/api/staff/summaries/transcript.csv` (cue CSV; no button in the console)
- Records routes:
  - POST `/api/staff/records`
  - GET `/api/staff/records/{id}/download`
  - GET `/api/staff/records/{id}/verify`
  - GET `/api/staff/records` (disposition queue, `records/router.py:39-47`)
- In the console source, only the export POST is called. A grep for `api/staff/records` in `OP/` finds only `client.ts:2216`.

## Help-text findings
- [HELP-01] `SummaryReviewScreen.tsx:10-14,234` — The Approve button sends extra fields `operator_id` and `operator_display_name`. The server's request model forbids anything except `approval_note` (`summary/router.py:111-115`, `extra="forbid"`). A Pydantic copy of that model rejects the same body (checked in a throwaway Python call; the running station was not exercised). Approve most likely fails with HTTP 422, and the page shows "Could not load summary review." with a JSON error. If confirmed, this blocks the whole summary workflow. Fix for the coder: send only `approval_note` (the server already takes the operator from the signed-in token, `router.py:174-181`) and change the error title. (Coordinator re-checked the model definition and the screen's payload on 2026-10-03: both as described.)
- [HELP-02] `:138,201-211` and `summary/store.py:54-59` — After a successful Approve the summary becomes Approved and drops out of this list (only Pending review and Needs evidence are listed). The "Export signed record" button (enabled only for Approved) can then no longer be reached, and nothing in the console lists, downloads or verifies records. The header promises "then export the PDF/A-3B signed-record artifact" (`:259-260`). Fix: list Approved items (or add an "Approved" tab) and add Download and Verify links.
- [HELP-03] `TranscriptCuePlayer.tsx:20-26` — "Inline transcript player" and "Transcript seek target" show only cue ids and times. The reviewer cannot read the quoted transcript or hear the audio here, yet the page says to "approve only summaries whose quantitative claims link to transcript cue timestamps". Fix: show the cue text, or rename the box "Source cues" and link to Review queue or the recording.
- [HELP-04] `:159-160`, `:108-109`, `SourcedClaimList.tsx:24` tell the reader to "regenerate", but there is no regenerate button here. On the asset page, the AI summary card shows only "Summary generated. Review it in Summary review" once any job exists (`GenerateSummaryPanel.tsx:392-399,453-461`). Fix: add "Generate again" for finished jobs.
- [HELP-05] `:146` — The card title is the asset id ("meeting id"), not the meeting name. `:148` shows the raw summary id and model tag (jargon). Fix: show the recording title and date, and move ids to a "details" line.
- [HELP-06] `:259-261` — Jargon: "quantitative claims", "cue timestamps", "PDF/A-3B", "signed-record artifact". Nothing explains what a signed record is for, or that the timestamp authority is a test one by default (`:207-209` "remains deterministic unless a real authority is configured" is unreadable to a clerk). Fix: a plain description and a clear warning when no real timestamp service is set up.
- [HELP-07] `:61,273-281` — Action failures get the same wrong title, and a 422 error is shown as raw JSON.
- [HELP-08] `types/summary.ts:10` and the yellow bar say "more evidence" but not what the clerk should do (fix cues in Review queue, then generate again).
- [HELP-09] There is no link to the Manual or to Review queue.

## Screenshot plan
1. The empty state.
2. A Pending review card with 2-3 claims and the transcript box with one range selected.
3. A "Needs evidence" card with the red message and empty narrative, plus the yellow bar.
4. The Approve flow: before the click, then the error after the click (if HELP-01 is real) or the success state.
5. The green "Signed record exported" box (if reachable).
6. The read-only view for a non-records-clerk token (yellow role note, buttons grey).

Setup: approve several caption cues for one recording in Review queue, then run "Generate summary" from the asset page with the local model running.

## UNVERIFIED / open questions
- UNVERIFIED: that Approve really returns 422 on a running station. This is derived from the code and a standalone Pydantic copy. No test calls the real route with these fields: `tests/summary/test_summary_router.py:120` posts `{}` only, and there is no `SummaryReviewScreen.test.tsx`.
- UNVERIFIED: that the card disappears after approval in practice. The code path is `queryClient.invalidateQueries` followed by a list filtered to pending/refused; it was not run.
- UNVERIFIED: whether another screen (Publish, Reports, Setup) lists signed records or offers the PDF download. I searched only the operator-console API client.
- UNVERIFIED: what would make a Pending review summary have zero claims. The generator returns either claims or a refusal, so the "no sourced claims" message may only occur for Needs evidence.
