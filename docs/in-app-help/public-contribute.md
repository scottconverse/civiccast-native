> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Submit a program (form at the bottom of Home, `#/`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/HomeScreen.tsx` unless noted. Staff review these on the Contributors screen (manual chapter 12).

## Where the text lives now
All form text is in `HomeScreen.tsx` (lines 237-327 for messages, 598-757 for the form). The agreement title and summary come from the server (`civiccast/contribute/store.py:48-57`). The status sentences come from the server (`contribute/store.py:840-856`). Upload refusals come from the server (`contribute/router.py:476-540`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Submit a program | Heading | 604 |
| Community producers can send video to the station review queue. Operators review every file before anything airs or publishes. | Intro | 607-608 |
| Submission agreement / Your submission is accepted only after station review. | Box if the agreement cannot load | 612, 616 |
| Community media submission agreement / Contributors confirm they have rights to submit the program, consent to operator review, and understand that operators decide what airs or publishes. | Box title and summary (server) | `store.py:51-55` |
| Producer name; Email; Organization; Program title; Description; Tags; Requested air date; Video file | Field labels | 624; 629; 636; 642; 647; 660; 667; 675 |
| arts, community | Tags placeholder | 664 |
| Send to review / Uploading | Button / while sending | 689 |
| Choose a video file before submitting. | No file chosen | 241 |
| Your program was sent to the station review queue. | Success | 304 |
| Receipt: `<id>` / Status token: `<token>` | Under the success line | 704-705 |
| Submission failed. (or the server's sentence) | Failure | 307 |
| Check submission status | Heading of second form | 716 |
| Receipt; Status token | Its labels | 719; 724 |
| Check status / Checking | Button / while looking | 734 |
| Status lookup failed. (or the server's sentence) | Failure | 325 |
| `<title>` / `<state>` / updated `<date>` [/ `<decline reason>`] | Result line | 749-751 |
| Your program has been received and is waiting for operator review. (and six more, one per state) | Result sentence (server) | `store.py:841-856` |

## What the page really does
The producer fills the form and picks a video. "Send to review" first uploads the file, then sends the details to the station's review queue. The channel is always `public` (273). The agreement is not shown with a checkbox: pressing the button records that the person typed in "Producer name" accepted it (280-287). The page then shows a Receipt and a Status token on the page only; reloading loses them. Later the producer pastes both into "Check submission status" to see one fixed sentence for the current state. Nothing airs or publishes without staff review. No email goes to the producer: the form lists the email as a notice target (288-293), but the station only records notices in the submission and sends no mail (`civiccast/contribute/` has no mail sending code; manual chapter 12).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-contribute/HELP-15 | "Receipt" and "Status token" | Two codes with no explanation, not saved, no copy button (704-705). Losing them means no way to check. | High |
| public-contribute/HELP-16 | (missing) | No word on file types, size, length or how long review takes. The picker accepts any video (679). By default files over 2 GiB are refused (`contribute/router.py:91,515-520`); the station and each address also have total limits. | Medium |
| public-contribute/HELP-17 | Agreement box | No "I agree" box; sending counts as agreeing, in the typed name (282-286). Owner/legal decision. | High |
| public-contribute/HELP-18 | `<state>` in the result line | Raw state with the first underscore swapped: "under review", "needs changes" (749). Only the first underscore is replaced. | Low |
| public-contribute/HELP-19 | Email field | Nothing says no email will be sent. The only way to learn the state is "Check status". | High |
| public-contribute/NEW-1 | Field labels | Required and optional fields look the same. Only the browser's own check says "Please fill out this field" (`ContributorInput`, 802-809). | Medium |
| public-contribute/NEW-2 | Failure text | The server's sentence is pasted in (307). Examples use staff words: "Ask the station for a direct hand-off if the programme is larger." (`contribute/router.py:517-520`), "This station's contributor upload storage is full..." (`router.py:488-495`). | Medium |
| public-contribute/NEW-3 | "Requested air date" | The box has no time zone note and the value is sent with no zone (`datetime-local`, 667-671, 278). Manual chapter 12 expects "Send to schedule" to fail for any submission that has this date. | Medium |
| public-contribute/NEW-4 | "Uploading" | No progress bar and no warning that a big file takes a while; the button is just disabled (684-689). | Medium |
| public-contribute/NEW-5 | Status words | The "needs changes" sentence does not carry the staff note; only a decline reason is shown (manual chapter 12, Known issue). | Medium |
| public-contribute/NEW-6 | Name and email boxes | No `autocomplete` hints (806-809); harder for people who use browser or assistive autofill (WCAG 1.3.5). | Low |
| public-contribute/NEW-7 | "Check status" form | Placed under the first form with a "Receipt" label that is also the success text; the id looks like random letters, easy to mistype. | Low |

## Proposed text
| Replace | With |
| --- | --- |
| 607-608 | Send your program to the station for review. Station staff look at every video before anything airs or goes online. |
| Labels (add the word) | Producer name (required); Email (required); Organization (optional); Program title (required); Description (required); Tags (optional, separate with commas); Requested air date (optional); Video file (required) |
| Requested air date help (new) | Use your own local time. The station may choose a different time. |
| Video file help (new, today) | Any video file. Very large files may be refused. The station sets the limit. |
| Video file help (after fix) | Largest file: `<limit from the station>`. Allowed types: `<list>`. |
| New line under the button | When you press Send to review, you agree to the agreement above. Large files can take a while to send. Please keep this page open. |
| 304 | Your program was sent. Please save the two codes below. You need both to check on it later. |
| 704-705 | Receipt number: `<id>` / Status code: `<token>` |
| New line under the codes | These codes are not saved on this page. Copy them now. We will not email you about this form. |
| New buttons | Copy receipt number; Copy status code |
| 716 | Check on a program you sent |
| 719; 724 | Receipt number; Status code |
| 734 | Check status |
| 749 | `<title>`. Status: `<plain words>`. Last updated `<date>`. |
| State words | submitted: Received. under_review: Being reviewed. needs_changes: Needs changes. accepted: Accepted. declined: Declined. scheduled: Scheduled. published: Published. |
| 241 | Please choose a video file first. |
| 307 / 325 fallback | We could not send your program. Please try again, or contact the station. / We could not find that program. Check both codes and try again. |

**After fix (agreement):** a required checkbox "I have read and agree to the Community media submission agreement" before the button is enabled; the agreement text opens in full from a link. **After fix (email):** if the station turns on mail, "We will email you when the status changes."

**Accessibility.** Every field has a visible label tied to its box (keep). Error and success messages use `role="alert"` and `role="status"` (keep). Add "required" in the label text, not only the browser check. Keep 44 px boxes and buttons. The file button is a native control; keep it. The token is shown in a wrapping block (`break-all`); keep it selectable.

## Notes for the coder
- Edit `HomeScreen.tsx` (lines 598-757). Code fixes: required checkbox for the agreement; copy buttons; progress for uploads; show server limits (extend the agreement response or add a limits endpoint); map `state` to plain words; send the requested date with a time zone; stop pasting raw server sentences for upload errors, or rewrite them in `contribute/router.py`; set `autoComplete="name"` and `"email"`.
- Tests that pin strings: none found for the form labels or messages (grep of `e2e` and `src` tests for "Submit a program", "Send to review" and "Choose a video file" finds only the page). The e2e specs mock `/api/public/contribute/agreements/current` (`a11y.spec.ts:88`, `contrast.spec.ts:259`, `analytics.spec.ts:35`); `a11y.spec.ts:326-330` checks Home headings.
- Not verified: the exact list of limits on a live station, and whether status sentences arrive unchanged (read from `store.py:840-856`).
