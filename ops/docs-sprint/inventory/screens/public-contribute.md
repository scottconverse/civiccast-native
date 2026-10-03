# Submit a program (community contributor form)  (nav id: public-contribute, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/HomeScreen.tsx:79-94,237-327,598-757`, `api.ts:51-89`, `types.ts:110-141`
(line cites are HomeScreen.tsx). Bottom of Home (`#/`).
Who can open it: everyone, no account.

## What it is for
Lets a community producer upload a video file and details to the station's review queue, then check its status later using a receipt id and a status token. Nothing airs or publishes without operator review (text at 606-609).

## What the user sees
Left: heading "Submit a program"; "Community producers can send video to the station review queue. Operators review every file before anything airs or publishes."; a box with the agreement title (server) or "Submission agreement" and its summary or "Your submission is accepted only after station review." (612-617).
Right: a form, then below it a "Check submission status" form (716).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Producer name | required text | sent as `producer_name`, `display_name`, `accepted_by_name` | none | |
| Email | required email | `contact_email`; also the email notification target | none | the account id is derived from the email (264-268) |
| Organization | optional | `organization` | none | |
| Program title | required | `title` | none | |
| Description | required textarea | `description` | none | |
| Tags | optional, placeholder "arts, community" | split on commas | none | |
| Requested air date | optional `datetime-local` | `requested_air_date` | none | |
| Video file | required file, `accept="video/*"` | uploaded first | none | no size or format limit text shown |
| Send to review | uploads the file, then submits | `POST /api/public/contribute/uploads` (multipart `file`), then `POST /api/public/contribute/submissions` with `channel_id:'public'`, the agreement id/version accepted now by the typed producer name (247-295) | none | label "Uploading" while busy (689). No separate "I agree" checkbox: submitting counts as acceptance of the agreement shown |
| Receipt (status form) | the submission id | none | none | required |
| Status token | the receipt token | none | none | required |
| Check status | looks up one submission | `GET /api/public/contribute/submissions/<id>/status?receipt_token=<t>` (317-319) | none | label "Checking" while busy (734) |

## States
- No file chosen: "Choose a video file before submitting." (241).
- Success: "Your program was sent to the station review queue." plus "Receipt: `<submission_id>`" and "Status token: `<token>`" shown on the page (304,704-705); the status form is pre-filled with them (297-300). Shown only in the page; lost on reload.
- Failure: server error text or "Submission failed." (307).
- Status result: server `status_message` bold, then "`<title>` / `<state with _ replaced by space>` / updated `<date>`" and " / `<decline_reason>`" if declined (746-752). Failure: error text or "Status lookup failed." (325).
- Agreement fetch fail: box shows the fallback text above (120-121).

## Typical task flows
1. Fill every required field, pick a video, click Send to review, copy the Receipt and Status token.
2. Later, paste them into Check submission status and press Check status.

## Statuses and words on this screen
Submission `state` is a server string (`PublicSubmissionStatus.state`, `types.ts:136`); the UI only swaps the first underscore for a space (`state.replace('_',' ')`, 749). UNVERIFIED: the possible state values (see the operator-side contributor review screen inventory).

## Related settings / env / CLI / API
`/api/public/contribute/agreements/current`, `/uploads`, `/submissions`, `/submissions/{id}/status`.

## Help-text findings
- [HELP-15] `HomeScreen.tsx:704-705` "Receipt" and "Status token" — two unexplained codes; nothing says "write these down, you will need both to check status; they are not saved on this page". Suggest an explanatory line and a Copy button.
- [HELP-16] No text states accepted file types, maximum size, expected length or the review turnaround; `accept="video/*"` only. Missing.
- [HELP-17] No explicit agreement checkbox; the form records acceptance silently using the producer name (282-286). For a legal agreement that is surprising to the resident; flag for owner/legal.
- [HELP-18] `HomeScreen.tsx:749` the state text can read like `under review` or a raw code; replace with a fixed plain-English map once the state list is known.
- [HELP-19] Whether the resident receives an email at the address entered is not stated (the form passes it as a notification target, 288-293); UNVERIFIED that mail is sent.

## Screenshot plan
Form empty; after a successful submit showing receipt and token; status lookup result; error with no file selected.

## UNVERIFIED / open questions
- UNVERIFIED: size limits and which states exist; whether notifications are sent; where operators review these (not in this inventory).
