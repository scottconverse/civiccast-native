# Watch a recording  (nav id: public-watch, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/WatchScreen.tsx`, `HlsPlayer.tsx`, `MeetingAgendaSidebar.tsx`, `PaywallGate.tsx`, `router.ts`
(line cites are WatchScreen.tsx unless stated). Route `#/watch/<asset_id>`.
Who can open it: everyone, unless the station has put the recording behind a subscription (then a gate card appears in place of the player; see `public-paywall.md`).

## What it is for
The page for one recording: video player with captions, the meeting agenda beside it (if the station published one), the description, and a button that copies a shareable link.

## What the user sees (top to bottom)
1. Link "Back to all recordings" (78).
2. Loading: "Loading this recording." (87).
3. Heading (the recording title), then "Published `<date>` / `<duration>`" (129-134). Duration looks like "47 min", "30 sec", or "Duration not posted" (`api.ts:217-222`).
4. Two columns on wide screens (player left, agenda right, `lg:grid-cols-[1fr_minmax(320px,440px)]`, 148); stacked on phones. Player is wrapped in the paywall gate, the agenda sits outside it (143-160).
5. Description or "Recording description not posted." (161-163).
6. Button "Copy share link" (170); after success "Link copied." (174).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Back to all recordings | goes to `#/recordings` | none | none | |
| Video player and its caption buttons | see `public-player-captions.md` | manifest URL from the asset | none | |
| Agenda item buttons | seek the video | see `public-agenda.md` | none | |
| Copy share link | copies `<origin><path>#/watch/<id>` to the clipboard | `navigator.clipboard` | none | if the browser blocks it, a prompt box "Copy this link to share the recording:" shows the URL (68) |
| Retry | reloads the recording | repeats `GET /api/public/assets/<id>` | none | error state only |

## States
- Data call: `GET /api/public/assets/<asset_id>` (34).
- Not found: heading "Recording not found" and "This recording does not exist or is no longer published. Browse the archive for the current recordings." (96-101). Chosen when the server's error message contains the text "not found" (43); any other failure falls to the error state.
- Error: "This recording could not be loaded right now. Try again, then contact the station if the problem continues." + Retry (112-120).
- Player errors appear on top of the video (see player file).

## Typical task flows
1. Open a card from Home or Recordings, press play, turn captions on, click an agenda item to jump.
2. Click "Copy share link" and paste into an email.

## Statuses and words on this screen
None beyond the strings above.

## Related settings / env / CLI / API
`/api/public/assets/{asset_id}`, `/api/public/agendas/{asset_id}`, `/api/public/paywall/*`.

## Help-text findings
- [HELP-25] `WatchScreen.tsx:43` "Recording not found" depends on the server message containing the words "not found"; if the server text differs the resident gets the generic error with a Retry that cannot succeed. UNVERIFIED backend text (`civiccast/vod/router.py` not read). Needs coder check.
- [HELP-26] No on-page help for how to turn captions on or use agenda items; the caption bar appears only when the video has caption tracks and says nothing when it has none.
- [HELP-27] Share link uses the page's own address; on a station reached by an internal or temporary address, copied links will not work for outside residents. Not stated anywhere.

## Screenshot plan
Recording with agenda + captions (wide); same on a phone-width window; not-found (`#/watch/nope`); error with Retry; gated recording.

## UNVERIFIED / open questions
- UNVERIFIED: whether `description` is plain text or can contain markup (rendered as plain text here, line 162).
