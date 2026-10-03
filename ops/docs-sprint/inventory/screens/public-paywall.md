# Subscription gate (paywall)  (nav id: public-paywall, section: Public)
Source files: `civiccast/apps/portal-public/src/PaywallGate.tsx` (line cites), `api.ts:91-203`
Used by: the watch page player only (`screens/WatchScreen.tsx:149-155`). Who can open it: everyone; the gate only appears if the station has configured a paywall for the recording.

## What it is for
If the station restricts a recording to paying subscribers, residents see a gate instead of the video. It offers a sign-in link by email and a Subscribe button that sends them to a Stripe-hosted checkout page. No card details are ever typed on the portal (`PaywallGate.tsx:4-8`). With no paywall configured the server answers "allowed" and the video plays normally (10-13).

## What the user sees
- Checking: the video renders under a small label "Checking access…" (448).
- Allowed: just the video.
- Denied: card with H2 "Subscription required" (501), a reason line, "Sign in by email" form, a "New here?" block, an optional plan list, "Subscribe", and "Already signed in as `<email>`? Switch email".

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Sign in by email (field, placeholder "you@example.com") | email to send the link to | none | none | |
| Email me a sign-in link | requests a one-time link | `POST /api/public/paywall/magic-link` `{email, scope_kind:'asset', scope_id}` | none | "Sending…" while busy; success "Check your inbox for a link." (533); failure "We could not send a sign-in link right now. Please try again in a moment." (286); empty "Please enter your email." (276) |
| Choose a plan (radio list) | picks a plan | `GET /api/public/paywall/tiers?asset_id=` | none | each option: name, "(monthly)" or "(yearly)", optional price note; first plan preselected (255-257,550-587) |
| Subscribe | starts Stripe checkout | `POST /api/public/paywall/checkout` then the browser navigates to the returned `checkout_url` (323-329) | none | "Opening checkout…" while busy; uses the email typed in the sign-in field, or the remembered email; if none: "Enter your email above before subscribing." (298) |
| Switch email | forgets the remembered email and reloads | removes `sessionStorage civiccast.paywall.email` (347-353) | none | |
Magic-link return: the emailed URL carries `?token=`; the page shows "Signing you in…" (391), calls `GET /api/public/paywall/verify?token=`, stores the email in sessionStorage, removes the token from the address bar, then re-checks access (176-204).

## Reasons shown (humanizeReason, 48-61)
`subscription_required` and unknown -> "This content is for subscribers."; `sign_in_required` -> "Please sign in to continue."; `expired` -> "Your subscription has expired. Renew or sign in again."; `tier_required` -> "A paid tier is required to view this content."

## States
- Expired/used link: card "Sign-in link unavailable" with "This link has expired or already been used. Request a new one." (HTTP 401/410) or "We could not verify that link. Please request a new one." and button "Request a new sign-in link" (197-198,413-422).
- Access check failed: "We could not check whether this content is available right now. Refresh the page, then contact the station if the problem continues." (465)
- No plans configured (tier list empty/404/410/501): "Tier selection isn't configured yet on this station. Contact them for subscription details." (594) and Subscribe sends no plan; a 4xx reply shows "This station hasn't finished setting up subscriptions yet. Please contact them." (336); server errors show "We could not start the subscription flow. Please try again in a moment." (340)
- Dev builds only add " (Local dev: see server logs.)" (539).

## Typical task flows
1. Denied resident enters email, clicks "Email me a sign-in link", opens email, clicks link, video plays.
2. New subscriber picks a plan, enters email, clicks Subscribe, pays on Stripe, returns (UNVERIFIED how the return URL and activation work: server side).

## Related settings / env / CLI / API
`/api/public/paywall/access|magic-link|verify|checkout|tiers`; Stripe configuration is operator-side (not in this inventory).

## Help-text findings
- [HELP-36] `PaywallGate.tsx:545` "New here?" then a Subscribe button, with the email taken from the sign-in field above; a first-time resident does not know that the "Sign in by email" box is also where to type the email for Subscribe. Suggest a separate "Your email" field or a hint under the button.
- [HELP-37] `PaywallGate.tsx:298` "Enter your email above before subscribing." is the only guidance for that dependency.
- [HELP-38] "tier" appears in `tier_required` text (57): "A paid tier is required" — jargon; suggest "A paid plan is required."
- [HELP-39] A station that has not set up payments still shows the gate with "Contact them" but gives no contact details; the portal has no station contact info anywhere. Missing.
- [HELP-40] After checkout, nothing on this page explains what happens next (UNVERIFIED).

## Screenshot plan
Gate with plan list; gate with "not configured" text; expired-link card; Checking access flash (slow network). Setup: station with a paywall configured (operator side).

## UNVERIFIED / open questions
- UNVERIFIED: how a station enables paywall and Stripe, magic-link email wording, session length, checkout return page.
