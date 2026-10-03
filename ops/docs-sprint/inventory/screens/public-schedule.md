# Channel schedule  (nav id: public-schedule, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/ChannelGuideScreen.tsx` (line cites), `router.ts:51-54,83-87`, `types.ts:41-51`
Route `#/schedule?channel=<id>` (default channel `public`). Who can open it: everyone.

## What it is for
Shows what airs on each station channel over the next 72 hours, from the station's program log. Times are shown in the visitor's own time zone.

## What the user sees
H2 "Channel schedule"; "What airs over the next three days. Times are shown in your local timezone." (105-106); a row of channel buttons (`aria-label="Channels"`); then one block per day (e.g. "Tuesday, October 6") listing time, title and length (e.g. "7:00 PM  City Council   120 min").
The entry on the air right now has a green left bar and a tag "On now" (180-200).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Channel buttons (channel display names) | switch channel | `#/schedule?channel=<id>`; guide fetched with `GET /api/public/programlog/channels/<id>/guide?hours=72` (68-70) | none | names from `GET /api/public/app/config` `channels[].branding.display_name`; if that fails only the current channel id is shown (93-96) |
| Retry | reloads the guide | same call | none | error state only |

## States
- Loading: "Loading the channel schedule." (136)
- Error: "The schedule could not be loaded. `<server message>` Try again, then contact the station if the problem continues." (146-147)
- Empty: "Nothing is on the schedule for this channel yet. Check back soon." (161)
- "On now" is computed in the browser from the entry's start and length; entries without a length are never marked.

## Typical task flows
1. Open Schedule, see today's lineup, click another channel tab.
2. Share the URL with `?channel=` to link to one channel.

## Statuses and words on this screen
"On now" (live marker). Length is "N min", "N sec" or "Duration not posted" (`api.ts:217-222`).

## Related settings / env / CLI / API
`/api/public/programlog/channels/{id}/guide`, `/api/public/app/config`.

## Help-text findings
- [HELP-41] Entries are not links; a resident cannot click "On now" to watch it, nor see which channel number on the cable system it is. Missing cross-link to Home's player; the page does not say whether the channel is also online.
- [HELP-42] If the server error text is raw (e.g. an HTTP status), it is spliced into the sentence (147); suggest hiding it.
- [HELP-43] Day headings and times use browser locale; nothing states the station's own time zone, which matters when residents compare with the posted cable schedule.
- [HELP-44] Home's "Coming up" (premieres, `/api/public/schedule/coming-up`) and this guide (program log) are two different lists with no explanation of the difference.

## Screenshot plan
Schedule with "On now" tag and two channel tabs; empty channel; error with Retry.

## UNVERIFIED / open questions
- UNVERIFIED: whether the guide includes live meetings, only automation playout, or both (backend not read).
