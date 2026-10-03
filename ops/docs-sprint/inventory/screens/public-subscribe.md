# Follow new recordings: email and RSS  (nav id: public-subscribe, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/HomeScreen.tsx:26-34,49-57,197-235,523-596`, `types.ts:96-108`
(line cites are HomeScreen.tsx unless stated). Lives at the bottom of Home (`#/`).
Who can open it: everyone.

## What it is for
Lets a resident get an email notice when the channel publishes a recording, or use RSS/podcast feed links without giving any personal data. Email uses a confirm-by-link step and an unsubscribe link.

## What the user sees
Heading "Follow new recordings" (529); text "Get a notice when this channel publishes a recording, or subscribe to the public RSS and podcast feeds without sharing personal data." (532-534); an "Email address" field (placeholder `resident@example.org`, required) and a "Subscribe" button; a result box; two feed links; small print.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Email address | the address to notify | none | none | `type=email`, required (538-545) |
| Subscribe | sends the signup | `POST /api/public/subscribe/email` body `{email, target_type:'channel', target_id:'government'}` (221-225) | none | label becomes "Sending link" while busy (552); the channel is hard-coded `government` |
| Channel RSS feed | link to `/api/public/subscribe/rss/channel/government.xml` (581) | RSS | none | |
| Podcast RSS feed | link to `/api/public/podcast/government.xml` (587) | RSS | none | |
| Test one-click unsubscribe | link `/?subscription=unsubscribe&token=<t>` shown only after a successful signup returns an unsubscribe token (567-574) | on click Home calls `GET /api/public/subscribe/unsubscribe?token=` (197-204) | none | label reads like a developer test control |
Confirmation link (from the email, content UNVERIFIED): `/?subscription=confirm&token=<t>` -> Home calls `GET /api/public/subscribe/confirm?token=` (200-204).

## States
- Result box (555-576): shows server `message` (bold) and `next_step`. `role=status` normally, `role=alert` on error.
- Server statuses: `pending_confirmation`, `confirmed`, `unsubscribed` (`types.ts:97`). Client-only: `submitting`, `invalid_token`, `error`, `idle`.
- Signup failure: message = server error text or "Subscription failed."; next step "Check the email address and try again. Contact the station if it still fails." (232-233).
- Bad/expired confirm or unsubscribe link: message = server error; next step "Use the signup form to request a fresh confirmation link." (211-213).
- Small print: "RSS does not create a subscriber row. Email uses double opt-in, one-click unsubscribe, and no tracking pixels." (592-594).

## Typical task flows
1. Resident types email, clicks Subscribe, sees server message ("pending_confirmation"), opens email, clicks link, lands on Home with a confirmed message.
2. Resident clicks an unsubscribe link in a later email: Home shows the unsubscribed message.
3. Resident right-clicks a feed link and pastes it into a podcast/RSS app.

## Statuses and words on this screen
`pending_confirmation` / `confirmed` / `unsubscribed` are shown through the server-provided `message` text, not as fixed client strings. UNVERIFIED: the exact server wording (`civiccast` backend not read).

## Related settings / env / CLI / API
`/api/public/subscribe/email|confirm|unsubscribe`, `/api/public/subscribe/rss/channel/government.xml`, `/api/public/podcast/government.xml`. Whether the station can actually send email depends on an outbound-mail setting (UNVERIFIED which).

## Help-text findings
- [HELP-11] `HomeScreen.tsx:572` "Test one-click unsubscribe" — developer wording shown to residents after signup; suggest "Unsubscribe from this list" or remove (the token is only needed for testing).
- [HELP-12] `HomeScreen.tsx:224,581,587` subscription target and feed URLs are hard-coded to a channel named `government`, while the schedule's default channel is `public` (`router.ts:53`) and contributions use channel `public` (`HomeScreen.tsx:273`). If a station has no channel called `government`, the feeds and signup point at nothing. Needs owner/coder check; docs must not promise a specific feed URL until confirmed.
- [HELP-13] `HomeScreen.tsx:531-534` does not say what "this channel" is or how often mail is sent, nor that the first email is a confirmation request that must be clicked. Suggest adding "You will get one email asking you to confirm."
- [HELP-14] "RSS", "double opt-in", "tracking pixels" (592-594) are jargon for residents; suggest "We will not track whether you open our emails. You can unsubscribe in one click."

## Screenshot plan
Form idle; after Subscribe showing the pending-confirmation message with the unsubscribe test link; error state (stop mail service or use an invalid address); the confirm-link landing result.

## UNVERIFIED / open questions
- UNVERIFIED: server message text, whether email delivery is configured on a new station, whether `government` exists by default.
