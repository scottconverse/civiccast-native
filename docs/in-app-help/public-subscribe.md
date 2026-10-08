> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Follow new recordings: email and feeds (section at the bottom of Home, `#/`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/HomeScreen.tsx` unless noted. Server texts are in `civiccast/subscribe/service.py` and `civiccast/subscribe/router.py`.

## Where the text lives now
Form and links: `HomeScreen.tsx:523-596`. Result sentences after signup come from the server (`subscribe/service.py:45-66, 174-220`). The page also reads `/?subscription=confirm|unsubscribe&token=<t>` (lines 49-57, 197-215).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Follow new recordings | Heading | 529 |
| Get a notice when this channel publishes a recording, or subscribe to the public RSS and podcast feeds without sharing personal data. | Intro | 532-533 |
| Email address; resident@example.org | Label; placeholder | 537; 544 |
| Subscribe / Sending link | Button | 552 |
| Subscription is waiting for confirmation. + Open the confirmation link sent to this address. | Result after signup (server) | `service.py:54, 61` |
| Subscription failed. + Check the email address and try again. Contact the station if it still fails. | Signup failed | 232-233 |
| Subscription confirmed. + You will receive a notice when a matching recording publishes. | After the email link (server) | `service.py:196-197` |
| This subscription was already confirmed. + No action is needed. Future matching recordings will send a notice. | Server | `service.py:188-189` |
| Subscription unsubscribed. + You will not receive future notices for this subscription. | After unsubscribe (server) | `service.py:218-219` |
| Confirmation link is invalid. Request a new signup link. / Unsubscribe link is invalid. Request a new link from the station. + Use the signup form to request a fresh confirmation link. | Bad link | `service.py:180,207`; 213 |
| Test one-click unsubscribe | Link in the result box | 572 |
| Channel RSS feed; Podcast RSS feed | Links | 583; 589 |
| RSS does not create a subscriber row. Email uses double opt-in, one-click unsubscribe, and no tracking pixels. | Small print | 592-593 |

## What the page really does
Pressing Subscribe sends the address to the station for the channel `government` (the code fixes it, line 224) and shows the server's answer. The station records a pending signup and tries to mail a confirmation link. The two links open `/api/public/subscribe/rss/channel/government.xml` and `/api/public/podcast/government.xml` as raw feed pages. Opening a confirm or unsubscribe link with `?subscription=...&token=...` on Home asks the server to finish that action and shows the answer in the same box (197-215). In beta.10 none of the email path works end to end (see Mismatches).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-subscribe/NEW-1 | "Get a notice when this channel publishes a recording"; "You will receive a notice when a matching recording publishes." | Nothing sends notices. The only code that mails subscribers is a staff test route (`subscribe/router.py:224`, `dispatch_notifications`); publishing a recording never calls it. The Publish screen marks "Subscriber notifications" as a future release (manual chapter 15). | High |
| public-subscribe/NEW-2 | "Open the confirmation link sent to this address." | By default the mail goes to an in-memory box on the station computer (`subscribe/delivery.py:23-39`, default provider is local) and leaves nowhere. With real mail on, the link written in the email is only `/subscribe/confirm?token=...` (`service.py:131-134`): no web address, and not the `/?subscription=confirm&token=...` form the portal reads (49-57). A path like that opens Home, which does nothing with it. A resident cannot finish confirming. | High |
| public-subscribe/NEW-3 | "Channel RSS feed" | A valid but empty feed (`subscribe/router.py:196-209`). "Podcast RSS feed" lists only episodes that exist (`podcast/router.py:56-95`); the Podcast step on Publish is not available yet. | High |
| public-subscribe/HELP-12 | "this channel" | The signup and both feeds always use `government` (224, 581, 587). That channel exists in the default setup (`cable/channel.py:323`), but the page never names it, and a station that renamed or removed it gets nothing. | Medium |
| public-subscribe/HELP-11 | "Test one-click unsubscribe" | Developer wording shown to residents (572). It works as an unsubscribe link for this signup. | Medium |
| public-subscribe/HELP-13 | (missing) | Not said: the first email is a request to confirm, and how often mail is sent. | Medium |
| public-subscribe/HELP-14 | "RSS", "double opt-in", "tracking pixels", "subscriber row" | Jargon (592-593). | Medium |
| public-subscribe/NEW-4 | Result after the email link | The confirm or unsubscribe answer appears in the "Follow new recordings" box lower on Home, with no scroll or focus move, and only after Home has finished loading (the section is hidden while loading, 397). A resident who clicks the link sees the top of Home and may think nothing happened. | Medium |
| public-subscribe/NEW-5 | Feed links | They open raw feed code in the browser. Nothing says to copy the address into a feed or podcast app. | Medium |
| public-subscribe/NEW-6 | Server sentences | Words like "matching recordings" and "notices" show unchanged in the result box; they promise mail (see NEW-1). | Medium |

## Proposed text
Beta.10 text (honest while mail does not work) first; "after fix" follows.

| Replace | With |
| --- | --- |
| 529 | Follow new recordings |
| 532-533, today | Email signup is not working yet in this version. You can use the feed links below instead. |
| 532-533, after fix | Get an email when the `<channel name>` channel posts a new recording. We will first send you one email asking you to confirm. |
| 552 | Subscribe / Sending… |
| Result sentence, today (replace the server text) | We got your request. In this version, emails may not be sent yet. |
| Result sentence, after fix | Please check your email and press the link to confirm. |
| 232-233 | We could not sign you up. Check the email address and try again. If it keeps happening, contact the station. |
| 213 | This link did not work. Please sign up again to get a new link. |
| 572 | Unsubscribe |
| 583 | Channel feed (for a feed reader) |
| 589 | Podcast feed (for a podcast app) |
| New line above the feed links | Feed links are for a feed reader or podcast app. Copy the link address into the app. |
| Today, new line under the Channel feed | The channel feed has no items yet. |
| 592-593 | We do not track whether you open our emails. You can unsubscribe in one click. Feeds do not ask for your email. |

**Confirm landing (after fix):** show the answer at the top of the page, or move focus to the box and scroll to it; say "You are signed up." only after the server confirms.

**Accessibility.** The email box has a visible label and `type="email"` (537-545); add `autocomplete="email"`. The result box uses `role="status"` normally and `role="alert"` for errors (557); keep. The button is 44 px high. Put the feed links in a list with plain names so a screen reader announces "link, Podcast feed (for a podcast app)".

## Notes for the coder
- Edit `HomeScreen.tsx` (523-596) and the server sentences in `subscribe/service.py`.
- Code fixes (not text): write a full `https://<station>/?subscription=confirm&token=...` address into the email (`service.py:131-134`; the router has a base-address helper, `router.py:152-190`); switch mail on by default or hide the signup; send notices on publish; fill the channel feed; read the channel from the station config instead of the fixed `government`; scroll or focus on the result; do not show the unsubscribe test link to residents (or rename it).
- Tests that pin strings: `e2e/a11y.spec.ts:604-609` (field "Email address", "Subscribe", "Subscription is waiting for confirmation.", "Open the confirmation link sent to this address.", link "Test one-click unsubscribe"), `a11y.spec.ts:616-626,633-634,642-643` (server sentences), `a11y.spec.ts:656-657` (links "Channel RSS feed", "Podcast RSS feed"). Server tests in `civiccast/tests` may pin the server sentences (not searched).
- Not verified: which mail provider a real station uses (`CIVICCAST_PROVIDER_MAIL`, manual chapter 15); no signup was run here.
