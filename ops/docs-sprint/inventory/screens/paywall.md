# Subscription paywall  (nav id: paywall, section: Setup, sidebar label "Paywall")
Source files (under `civiccast\apps\portal-operator\src\`): `screens\PaywallScreen.tsx` (PaywallScreen role gate, PaywallBody, PaywallEditor, ConfigCard, TiersSection, GrantsSection, helpers `generateSigningSecret` 118, `isStripePriceShape` 134, `deriveGrantId` 945, `isoFromDate` 969), `api\client.ts:3546-3700` (PAYWALL = `/api/staff/paywall`, line 3621), `screens\contribution-format.ts` (`hasRole`), `routes.ts:41,62` (`/paywall`; old `/subscribers` redirects here), `App.tsx:309`.
Backend: `civiccast\paywall\router.py` (staff routes 268-480, public 483-740), `paywall\service.py` (decide 230-262, webhook 503-535), `paywall\store.py` (`upsert_config` 198, `delete_config` 233), `paywall\models.py` (PaywallConfig, PaywallTier, AccessGrant), `app.py:3306-3327` (wiring), public consumer `apps\portal-public\src\api.ts:90-215` and `PaywallGate.tsx`.
Who can open it: sidebar shows it to `setup_admin` only (`Sidebar.tsx:114`, `requiredRoles: ['setup_admin']`). The screen repeats the check (`ADMIN_ROLES = ['setup_admin']`, PaywallScreen.tsx:70,183) and others see "Forbidden — the subscription paywall is a setup-admin surface. Ask your station admin for access." (188-189). Every staff route requires `setup_admin` (`_CONFIG`, router.py:156; GET/PUT/PATCH/DELETE config and POST/DELETE grants). Because `admin` and `operator` token scopes expand to all five roles, a first-admin token passes; a token minted only as `meeting_operator`, `publish_operator`, `records_clerk` or `support_admin` does not.

## What it is for
Optional paid access to recordings. When switched on, some content can be held behind a subscription (Stripe monthly or yearly price) or a free "comp" pass issued by staff to a named email. It is OFF by default and, when off, the station behaves as if the feature did not exist. The screen only configures; it never shows card numbers.

## What the user sees
H1 "Subscription paywall" with the line "Optional, opt-in monetization. Default OFF — when off, every asset is public and the paywall code path is inert. Stripe-hosted Checkout only; no card or PAN data ever touches CivicCast (DC-4)." (409-414). Then three cards: "Config", "Tiers", "Comp access grants". When the box is off, Tiers and Grants are greyed (opacity 0.6) and not clickable or tabbable (`inert`, 776, 1015).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Banner (green/blue) | "Paywall is ON. Tier-based gating active." or "Paywall is OFF. All content is public — no subscription required to view." | none (follows the local checkbox, not the saved state) | | Changes the moment the box is ticked, before Save (557-561) |
| Enable paywall (checkbox) + "Default off (DC-1)." | Master switch | saved with Save (`enabled`) | `setup_admin` | Server: `enabled=False` makes every access check return open (models.py `PaywallConfig` docstring; service.py:230-262) |
| Provider (select) | Options "stripe (Stripe-hosted Checkout)" and "mock (contract tests / lab)" (591-592) | saved with Save | `setup_admin` | `mock` is for tests; no warning on a live station if chosen (UNVERIFIED what `mock` does at runtime; only the model literal `PaywallProvider = stripe or mock` was read, models.py:63-64) |
| Signing secret (HMAC) (password box; placeholder "base64 secret; rotate via Generate") | Text of the per-station secret | saved with Save as `signing_secret` | `setup_admin` | Starts EMPTY on every page load: the server never returns the secret, only a hidden flag (router.py:268-293; models `signing_secret_present`) and the screen does not read that flag |
| Show / Hide (aria "Show signing secret" / "Hide signing secret") | Reveals the typed text | browser only | | |
| Generate new secret (aria "Generate a new signing secret") | Fills the box with 32 random bytes as base64 (44 characters) | browser only until Save | `setup_admin` | If the box is empty it fills at once; otherwise turns into "Confirm regenerate" / "Cancel" and warns "Confirming will overwrite the current secret. All unredeemed magic links stop working and Stripe webhook verification will fail until you update Stripe's webhook secret." (659-664). Because the box is always empty after reload the confirm step almost never appears |
| Warning line under the secret | "Rotating this invalidates all unredeemed magic links and breaks webhook verification until Stripe is updated." (655-658) | none | | |
| Save (aria "Save paywall config"; busy "Saving…") | Sends the WHOLE form: config id, station id, enabled, provider, the tiers list, and the secret | `PUT /api/staff/paywall/config` (router.py:296-323; `upsert_config` store.py:198) | `setup_admin` | **A blank secret box is sent as `null` (PaywallScreen.tsx:352) and the store writes it as the new secret, so saving with the box empty erases any stored secret** (store.py:198; the GET never returns it, so the box is empty after every reload). Success "Saved."; failure shows the server text or "Could not save the config." A second config id for the same station gives 409 |
| Delete config -> "Confirm delete" (busy "Deleting…") / Cancel | Removes the stored config row | `DELETE /api/staff/paywall/config/{config_id}` (router.py:399-422; store.py:233) | `setup_admin` | Text: "Confirming will remove the paywall config entirely and disable gating until you re-create it." (713-716). Grants and subscriptions are not touched by this call (UNVERIFIED that no cascade exists in the DB schema; the migration was not opened). If nothing was ever saved the server answers 404 "Paywall config 'paywall-default' not found." |
| Tiers table ("Existing tiers"): Tier ID, Name, Stripe price, Interval, Actions | Lists tiers held in the form | none | | Empty: "No tiers configured yet. Add one below; each tier maps to an existing Stripe price id." |
| Remove (aria "Remove tier <id>") | Drops the row from the form only | none until Save | `setup_admin` | Footnote: "Tier changes are local until you click Save in the Config section above." |
| Tier ID (slug) (placeholder "basic"), Display name ("Basic monthly"), Stripe price id ("price_1A2bcDeFgHiJkLmN"), Interval radios Monthly / Yearly | New-tier form | none until Add tier + Save | `setup_admin` | Hint "Stripe price IDs start with price_." turns amber if wrong. Server pattern for the slug: lowercase letters, digits, `_`, `-`, starting with a letter or digit, max 120 (models.py:36); the screen does not check this, so a bad slug fails only at Save |
| Add tier | Appends the row to the form | none until Save | `setup_admin` | Disabled until id, name and a "price_…" id are filled and the id is not already in the list (737-743) |
| Comp grants table ("Recently issued grants"): Email, Scope, Expires, Actions | Rows issued in THIS browser session only | none (list is not loaded from the server) | | Heading note: "Showing grants issued in this session. Server-side grant history is a follow-up." Empty: "No grants issued in this session yet." Expiry shows an ISO timestamp or "never"; scope shows "all content" or "asset: <id>" / "series: <id>" |
| Email (placeholder "viewer@example.gov") | Who gets access | in the grant POST | `setup_admin` | Lower-cased; server checks it looks like user@host.tld (models.py:44-47) |
| Scope kind (select: asset, series, all (catch-all)) | What the pass opens | same | | "all" hides Scope ID |
| Scope ID (placeholder "asset-2026-01 / series-council") | Asset or series id | same | | Blank is allowed for asset or series (becomes "unscoped" in the grant id); no check that the id exists (UNVERIFIED server-side) |
| Expires at (optional) (date) | Last valid day, end of day UTC | `expires_at` | | Unreadable date: "That expiry date could not be read, so no grant was issued. Re-enter it, or clear it to grant access that never expires." (385) |
| Issue grant (aria "Issue comp grant"; busy "Issuing…") | Creates a comp grant | `POST /api/staff/paywall/grants` (router.py:425-451), `granted_via: "comp"` | `setup_admin` | Grant id is built from email + scope + time (945-959). Success adds a row and clears the form. Error: server text or "Could not issue the grant." (409 if id exists) |
| Revoke -> "Confirm revoke" (busy "Revoking…") / Cancel | Deletes the grant | `DELETE /api/staff/paywall/grants/{grant_id}` (router.py:454-480) | `setup_admin` | Only possible for rows still on the screen; after a reload there is no way to revoke from this page |

## States
- Loading: "Loading…" (identity), "Loading paywall config…".
- Identity failure: "Could not load your staff identity (<server text>). Check that you are signed in and the local API is running, then retry."
- Config failure: "Could not load the paywall config (<server text>)." 503 "Durable storage is not ready yet." (router.py:152).
- No saved config: the server returns a 200 default (config id `paywall-default`, disabled, provider stripe, no tiers; router.py:174-188, 276-293), so the screen opens in edit mode. Its 404-to-empty mapping (212) is never needed.
- Off: Tiers and Grants cards greyed with "Save with the enable toggle on to manage tiers and grants." Note this follows the CHECKBOX, so ticking the box unlocks them before saving, while the text says to save first.
- Saved banner "Saved." hides when any later edit is made.

## Typical task flows
1. Look: open Paywall; read the banner. Nothing changes unless Save is clicked.
2. Turn on (as the code is written): create the recurring prices in the Stripe website first; tick Enable paywall; Generate new secret; add a tier per price; Save. Then Stripe must be pointed at the station's Stripe webhook route (handler `stripe_webhook`, router.py:699; the public URL path was not traced, see UNVERIFIED).
3. Give a free pass: tick Enable (and Save); Issue comp grant with email and scope; keep the page open, because the list is not saved.
4. Turn off: untick Enable; Save. Content becomes public again.
5. Remove everything: Delete config -> Confirm delete.

## What actually happens for viewers (code behind the page)
- Public check: `GET /api/public/paywall/access` returns allow or block for an email + asset/series (router.py:483-526). It trusts the email passed in the request; nothing proves the caller owns it (the magic-link steps below exist to prove it, but are not required by this route).
- Magic link: `POST /api/public/paywall/magic-link` creates a signed link (564-625), but the email sender is a no-op by default, so no email is sent (`_default_email_sender`, 237-255). The link is therefore not delivered to the viewer.
- Verify link: `GET /api/public/paywall/verify` (637-675) turns a good link into a grant.
- Stripe webhook verifies the `Stripe-Signature` header using the same `signing_secret` and reconciles subscriptions (688-740; service.py:503-535).
- The public site (`portal-public\src\api.ts:90-215`) also calls `/api/public/paywall/tiers` and `/api/public/paywall/checkout`; no such routes were found in `paywall\router.py` (UNVERIFIED anywhere else; searched the paywall package and `app.py` wiring only).
- No server code was found that blocks the media file itself; gating is a decision the public page asks for (`PaywallGate.tsx`). UNVERIFIED for HLS and download routes.

## Statuses and words on this screen
Only "Paywall is ON / OFF", "Saved.", tier interval words `month` / `year`, grant scope words asset / series / all. Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`CIVICCAST_STATION_ID` (server's station for the config lookup, default `civiccast-station`, router.py:163-166; the screen sends `civiccast-station` unless the loaded config says otherwise). Staff routes: `GET|PUT /api/staff/paywall/config`, `PATCH|DELETE /api/staff/paywall/config/{config_id}` (PATCH not used by this screen), `POST /api/staff/paywall/grants`, `DELETE /api/staff/paywall/grants/{grant_id}`. Public routes: `/api/public/paywall/access`, `/magic-link`, `/verify`; Stripe webhook. Rate limit on public routes and 1 MiB webhook cap (router.py:76-150). Spec tag S26. The `stripe` Python package: see UNVERIFIED.

## Help-text findings
- [HELP-01] PaywallScreen.tsx:352 and 596-598 — Save sends `null` when the secret box is blank, and the box is ALWAYS blank after a reload because the server hides the secret; so changing any other setting (a tier, the switch) and clicking Save silently deletes the stored signing secret. Magic links and Stripe webhook checks then stop working — fix: send "leave unchanged" when the box was not touched, and show "A secret is saved" from `signing_secret_present`.
- [HELP-02] PaywallScreen.tsx:604 and 655 — the secret is described as "base64 secret; rotate via Generate" and the warning mentions "update Stripe's webhook secret", but the screen never says where to find the Stripe webhook secret, and Stripe makes its own `whsec_` value for each webhook endpoint; the code verifies Stripe signatures with THIS field (service.py:503-535), so Generate is probably the wrong value to use for Stripe (UNVERIFIED against Stripe docs) — fix: say "paste the Signing secret from your Stripe webhook endpoint" or split into two fields.
- [HELP-03] PaywallScreen.tsx:409-414 — "every asset is public" and "Tier-based gating active" imply content is protected once ON; the code found does not block media at the server, and the public site's checkout and tiers routes are not present in the server package, and magic-link emails are not sent — the page promises a working paywall; the feature looks unfinished — fix: add a visible "Beta: not ready for live use" line or hold the sidebar entry back until the delivery path works.
- [HELP-04] PaywallScreen.tsx:413, 576, 597, 851, 1147 — "PAN", "DC-4", "DC-1", "HMAC", "Scope kind", "Tier ID (slug)", "catch-all", "comp" are jargon or internal requirement codes — fix: "no card numbers are ever stored here", remove DC codes, "Pass applies to: one recording / one series / everything", "Free pass (comp)".
- [HELP-05] PaywallScreen.tsx:787, 1033 — "Save with the enable toggle on to manage tiers and grants." but the sections unlock as soon as the box is ticked (before saving); and the grants form posts to the server immediately, regardless of whether the paywall is saved ON — fix: reword to "Tick Enable paywall to edit tiers and grants."
- [HELP-06] PaywallScreen.tsx:1029-1032 — "Server-side grant history is a follow-up." is a developer note; staff cannot see, search or revoke passes issued earlier, and the page does not say so beyond that line — fix: "Passes you issued before today are not listed here."
- [HELP-07] PaywallScreen.tsx:591-592 — the "mock (contract tests / lab)" option is selectable on a live station with no warning — fix: hide `mock` unless the station is in lab mode.
- [HELP-08] PaywallScreen.tsx:889 — "Stripe price IDs start with price_." is the only guidance; it never says the price must already exist in Stripe, which currency/tax rules apply, or that the station never creates prices (that is only in a code comment, 10-14) — fix: add one sentence "Create your price in the Stripe dashboard, then paste its id here."
- [HELP-09] PaywallScreen.tsx:713-716 — Delete config says gating is disabled until re-created but does not say whether existing subscribers and passes are kept (UNVERIFIED) — fix: state the result.
- [HELP-10] PaywallScreen.tsx:202-205, 139 — code comments claim a 404 maps to an empty form, but the server now returns 200 (router.py:276); harmless to users, noted so the manual does not describe a "no config" error.

## Screenshot plan
1. Fresh station: Config card with blue "Paywall is OFF" banner, Tiers and Grants greyed.
2. Enable ticked: green banner, secret box empty with Show / Generate buttons and the amber rotation warning.
3. Tier form with a mistyped id showing the amber "price_" hint, then a tier row in the table.
4. "Confirm regenerate" state (needs a typed secret first) and "Confirm delete" state.
5. Comp grant issued: row in the table with "never", then the "Confirm revoke" state.
6. Non-admin view ("Forbidden — ...") using a token from `civiccast token issue --scopes meeting_operator`.
Setup: lab station only; use the `mock` provider and invented emails (example.gov); do NOT enter a real Stripe key or price.

## UNVERIFIED / open questions
- UNVERIFIED: what the `mock` provider changes at run time (only its allowed value was read).
- UNVERIFIED: the Stripe webhook URL path as the outside world sees it (router prefix not read) and whether Stripe's own endpoint secret must be the same string as this field.
- UNVERIFIED: that the `stripe` Python package ships in the packaged build (it is not a base dependency in what was read).
- UNVERIFIED: whether any server code (HLS, download or media routes) enforces the paywall; none found in the paywall package.
- UNVERIFIED: whether `/api/public/paywall/tiers` and `/checkout` exist outside `civiccast\paywall\`.
- UNVERIFIED: whether deleting the config cascades to grants or subscriptions (migration not opened).
- UNVERIFIED: whether the page can be reached by `support_admin` (sidebar and routes say no; not run).
