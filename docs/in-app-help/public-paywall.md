> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Subscription gate (shown in place of the video on a Watch page when a paywall is on)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/PaywallGate.tsx` unless noted. The gate is off unless a setup administrator turns on the Paywall screen; then it shows on every recording (see Mismatches).

## Where the text lives now
`PaywallGate.tsx` (lines 48-61, 197-198, 276-298, 336-340, 383-629). Calls are in `src/api.ts:107-203`. The gate is used only on Watch pages (`src/screens/WatchScreen.tsx:149-155`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Checking access… | Small label above the video while checking | 448 |
| Subscription required | Card heading | 501 |
| This content is for subscribers. | Reason (also the fallback) | 51, 59 |
| Please sign in to continue. | Reason `sign_in_required` | 53 |
| Your subscription has expired. Renew or sign in again. | Reason `expired` | 55 |
| A paid tier is required to view this content. | Reason `tier_required` | 57 |
| Sign in by email; you@example.com | Label; placeholder | 507; 515 |
| Email me a sign-in link / Sending… | Button | 524 |
| Please enter your email. | Empty email | 276 |
| We could not send a sign-in link right now. Please try again in a moment. | Failure | 286 |
| Check your inbox for a link. | After pressing the button | 534 |
| New here? | Line above plans | 545 |
| Choose a plan; `<name>` (monthly) or (yearly) `<price note>` | Plan list | 553; 573-579 |
| Tier selection isn't configured yet on this station. Contact them for subscription details. | No plans | 594-595 |
| Subscribe / Opening checkout… | Button | 605 |
| Enter your email above before subscribing. | No email typed | 298 |
| This station hasn't finished setting up subscriptions yet. Please contact them. | Subscribe refused (HTTP 400-499) | 336 |
| We could not start the subscription flow. Please try again in a moment. | Other failure | 340 |
| Already signed in as `<email>`? Switch email | Bottom line and button | 616-623 |
| Signing you in… | While a sign-in link is checked | 391 |
| Sign-in link unavailable / This link has expired or already been used. Request a new one. / We could not verify that link. Please request a new one. / Request a new sign-in link | Bad link card | 413; 197; 198; 421 |
| We could not check whether this content is available right now. Refresh the page, then contact the station if the problem continues. | Check failed | 465-466 |

## What the page really does
Before showing the video the gate asks the server if this email may watch this recording (`/api/public/paywall/access`). With no paywall it says yes and the video plays. With the paywall on, the server says no to everyone without a pass, for every recording (`civiccast/paywall/service.py:238-251`). The resident then sees this card. In beta.10 neither way in works: the sign-in email is never sent, and the plan list and checkout do not exist on the server.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-paywall/NEW-1 | "Check your inbox for a link." | The server accepts the request but sends nothing: the default sender does nothing (`civiccast/paywall/router.py:225-235`) and the app does not replace it (no override in `app.py`). A resident waits for mail that never comes, and cannot sign in. | High |
| public-paywall/NEW-2 | Plan list and "Subscribe" | The portal asks for `/api/public/paywall/tiers` and `/checkout`; the server has only `access`, `magic-link` and `verify` (`paywall/router.py:483,564,637`). So the plan list is always empty and "Subscribe" always ends in "This station hasn't finished setting up subscriptions yet." A paying resident has no way in. | High |
| public-paywall/NEW-3 | "Subscription required" | With the paywall on, every recording asks for a pass, not just chosen ones (`service.py:238-251`). The gate is only a screen in front of the player; the video file is not protected (manual chapter 15). | High |
| public-paywall/HELP-36 | "New here?" with Subscribe | The only email box is "Sign in by email" above; Subscribe takes its email from there (296). Not said. | Medium |
| public-paywall/HELP-37 | "Enter your email above before subscribing." | The only hint for that link. | Low |
| public-paywall/HELP-38 | "A paid tier is required" | "Tier" is jargon (57). | Low |
| public-paywall/HELP-39 | "Contact them" (594, 336) | No contact details anywhere in the portal; the server sends `support_url` (default `/support`, a page that does not exist, `app_platform/store.py:254`) but the portal ignores it. | High |
| public-paywall/HELP-40 | (missing) | Nothing says what happens after Stripe checkout. Return path UNVERIFIED. | Medium |
| public-paywall/NEW-4 | Reason line when no email | The first reason is "Please sign in to continue." (53) while sign-in cannot finish (NEW-1). | Medium |
| public-paywall/NEW-5 | Rate limit | The server allows 5 link requests per minute per address; a 429 shows "could not send a sign-in link right now" with no wait advice (`paywall/router.py` Q-5 note; 284-287). | Low |

## Proposed text
Beta.10 text (until sign-in mail and checkout work) is first; "after fix" follows.

| Replace | With |
| --- | --- |
| 501 | This recording is for subscribers |
| 51, 59 | This recording is for subscribers. |
| 57 | A paid plan is required to watch this recording. |
| 53 | Please sign in to watch. |
| 507 | Sign in with your email |
| 534, today | We got your request. In this version the sign-in email may not arrive. If it does not, please contact the station. |
| 534, after fix | Check your email for a sign-in link. If you do not see it soon, look in your spam folder. |
| 286 | We could not send the link. Please wait a minute and try again. If it keeps happening, contact the station. |
| 545 | New subscriber? |
| Under "New subscriber?" (new) | Enter your email in the box above, then press Subscribe. |
| 594-595, today | Subscriptions are not open yet on this website. Please contact the station to subscribe. |
| 594-595, after fix | (show the plan list) |
| 298 | Please enter your email in the box above first. |
| 336 | Subscriptions are not open yet. Please contact the station. |
| 340 | We could not open the payment page. Please try again in a moment. |
| 616-623 | Signed in as `<email>`. Not you? Use a different email |
| 197 | This sign-in link has expired or was already used. Please ask for a new one. |
| 198 | We could not use that link. Please ask for a new one. |
| 465-466 | We could not check if you can watch this. Please reload the page. If it keeps happening, contact the station. |
| New contact line (after fix, from the station's support link) | Questions? Contact the station: `<support link>`. |

**After checkout (new, after fix):** "You paid on a secure page run by Stripe. CivicCast never sees your card number. When you come back, press Watch again." (owner to confirm return flow.)

**Best fix for now (owner decision):** do not turn the paywall on until sign-in mail and checkout work; the gate cannot be completed by a resident today.

**Accessibility.** Focus moves to the "Subscription required" heading when the gate shows (`gateHeadingRef`, 367-371) and to "Sign-in link unavailable" on a bad link (362-366); keep. The email box has a real label (506-508) and `autocomplete="email"` (517); keep. Plans are radio buttons in a "Choose a plan" group with arrow-key use; keep. The "Checking access…" label is announced politely (444-447). The "Switch email" button is a plain underlined button; give it 44 px height.

## Notes for the coder
- Edit `PaywallGate.tsx`. Code fixes (not text): send the sign-in mail (`paywall/router.py:225-235` needs a real sender); add `/api/public/paywall/tiers` and `/checkout`; gate only chosen recordings; protect the video file, not just the screen; show a station contact from `support_url`. Also the access check trusts the email typed in the address query (`api.ts:111`, `paywall/router.py:483`); depth of that risk is UNVERIFIED.
- Tests that pin strings: `PaywallGate.test.tsx:105,118,138,160,186,233,253,278` (texts "Subscription required", "Checking access", names `/sign-in link/i`, "Request a new sign-in link", "Subscribe", "Switch email").
- Not verified: the Stripe return page, the session length, and the magic-link email wording (no email is built).
