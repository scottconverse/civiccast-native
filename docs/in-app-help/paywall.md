> Historical beta.10 audit snapshot dated 2026-10-03; its general review is not current UI or user guidance. The signing-secret rows were updated for beta.12 slice #10.

# Subscription paywall (nav id: paywall)

Sidebar: Setup > **Paywall**; page H1 "Subscription paywall". Manual authority: `docs/USER-MANUAL.md` Chapter 11, "Configure the Paywall" (`#configuration-paywall`); corresponding chapter source: `docs/manual/src/22-configuration.md`. Related manual sections: `16-station-business.md` ("Turn on paid access") and `15-publishing.md` ("The paywall: optional paid access"). The manual tells readers to leave the paywall off in beta.10.

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/PaywallScreen.tsx` (PaywallScreen, PaywallEditor, ConfigCard, TiersSection, GrantsSection). Server behaviour: `civiccast/paywall/router.py`, `store.py`. This inventory was refreshed for beta.12 slice #10.

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Subscription paywall"; "Optional, opt-in monetization. Default OFF — when off, every asset is public and the paywall code path is inert. Stripe-hosted Checkout only; no card or PAN data ever touches CivicCast (DC-4)." | H1 and intro | PaywallScreen.tsx:424, 426-428 |
| "Forbidden — the subscription paywall is a setup-admin surface. Ask your station admin for access."; "Loading…"; "Could not load your staff identity (<text>). Check that you are signed in and the local API is running, then retry."; "Loading paywall config…"; "Could not load the paywall config (<text>)." | gate and states | 188-189, 168, 176, 224, 232 |
| "Config" | card title | 611 |
| "Paywall is ON. Tier-based gating active." / "Paywall is OFF. All content is public — no subscription required to view." | banner (follows the box, before Save) | 615-616 |
| "Enable paywall"; "Default off (DC-1)." | switch | 629, 632 |
| "Provider": "stripe (Stripe-hosted Checkout)" / "mock (contract tests / lab)" | select | 637, 647-648 |
| "Signing secret (HMAC)"; saved-secret status; "Show signing secret" / "Hide signing secret"; "Generate new secret" / "Confirm replacement"; "Clear saved secret" / "Confirm clear"; replacement and clear warnings | secret | PaywallScreen.tsx secret field, generate/confirm and clear controls |
| "Save" / "Saving…" (aria "Save paywall config"); "Saved."; "Could not save the config." | save | 784, 790, 832, 443 |
| "Delete config"; "Confirm delete" / "Deleting…"; "Confirming will remove the paywall config entirely and disable gating until you re-create it."; "Could not delete the config." | delete | 821, 802, 827, 446 |
| "Tiers"; "Save with the enable toggle on to manage tiers and grants."; table "Existing tiers" (Tier ID, Name, Stripe price, Interval, Actions); "No tiers configured yet. Add one below; each tier maps to an existing Stripe price id."; "Remove"; "Tier changes are local until you click Save in the Config section above." | tiers | 897, 900, 904, 922-923, 1050 |
| "Add tier"; "Tier ID (slug)"; "Display name"; "Stripe price id" (placeholder price_1A2bcDeFgHiJkLmN); "Stripe price IDs start with price_."; "Interval" Monthly / Yearly | add-tier form | 959, 964, 976, 989, 1000, 1004, 1018, 1029, 1038-1044 |
| "Comp access grants"; "Showing grants issued in this session. Server-side grant history is a follow-up."; "Save with the enable toggle on to manage tiers and grants."; "Recently issued grants" (Email, Scope, Expires, Actions); "No grants issued in this session yet." | grants | 1126, 1136, 1143, 1148, 1154-1155, 1172 |
| "Issue comp grant"; "Email" (placeholder viewer@example.gov); "Scope kind" (asset, series, all (catch-all)); "Scope ID" (placeholder asset-2026-01 / series-council); "Expires at (optional)"; "Issue grant" / "Issuing…"; "Revoke" / "Confirm revoke"; "Could not issue the grant."; "That expiry date could not be read, so no grant was issued. Re-enter it, or clear it to grant access that never expires." | grant form | 1243, 1260, 1280, 1294, 1314, 1201, 1089, 1113, 400 |

## What the screen really does
It edits the station's one paywall record: an on/off box, a provider, a signing secret, a list of tiers (each tied to a price you create in the Stripe website) and free "comp" passes for named email addresses. It is off by default. Do not rely on it in beta.10. In the code: the sign-in email is sent by a function that does nothing, so a resident never gets a link; the public site's tier-list and checkout routes do not exist on the station; the video file itself is not protected, only a gate shown in front of the player; turning the paywall on does not choose particular recordings, the Watch page asks every resident for a pass on every recording; and the access check trusts the email address it is given. The secret field stays blank because the server never returns the secret, and an ordinary save omits it so the stored value is preserved. Every replacement, pasted or generated, must be confirmed after its exact value is in the field; an edit clears confirmation, and Cancel discards the pending value. Clearing requires the separate confirmed clear action and a save. The grants table lists only passes issued in this browser session.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | Save with a blank "Signing secret (HMAC)" box | Resolved in beta.12 slice #10: ordinary UI saves omit the secret; PUT preserves the stored secret when the value is omitted or null. Clearing requires a confirmed UI action and explicit empty-string request | fixed |
| HELP-02 | "base64 secret; rotate via Generate" and "update Stripe's webhook secret" (604, 661-663) | Never says where Stripe's webhook secret is; Stripe makes its own `whsec_` value per endpoint, and the code checks Stripe's header with THIS field (service.py:503-535), so Generate may be the wrong value (UNVERIFIED against Stripe docs) | misleading |
| HELP-03 | Intro and banner: "every asset is public"; "Tier-based gating active." (411-413, 559) | The paywall is unfinished: no email, no tiers or checkout route, no server block of the media file; every recording is gated, not chosen ones | blocks work |
| HELP-04 | "PAN", "DC-4", "DC-1", "HMAC", "Scope kind", "Tier ID (slug)", "catch-all", "comp" | Jargon and internal requirement codes | cosmetic |
| HELP-05 | "Save with the enable toggle on to manage tiers and grants." (787, 1035) | Sections unlock when the box is ticked, before Save; the grant form posts to the server at once, whether or not the paywall is saved on | misleading |
| HELP-06 | "Server-side grant history is a follow-up." (1030) | Developer note; passes issued earlier cannot be seen or revoked | misleading |
| HELP-07 | Provider "mock (contract tests / lab)" (592) | Selectable on a live station with no warning; what `mock` does at run time is UNVERIFIED | misleading |
| HELP-08 | "Stripe price IDs start with price_." (887) | Does not say the price must already exist in Stripe; CivicCast never creates a price | misleading |
| HELP-09 | "Confirming will remove the paywall config entirely..." (714-715) | Does not say whether subscribers and passes are kept (UNVERIFIED) | misleading |
| HELP-10 | (Code comments say a 404 maps to an empty form) | The server returns 200 with a default config; no "no config" error exists | cosmetic |
| NEW-1 | "Generate new secret" for a previously saved value | Resolved in beta.12 slice #10: GET's `signing_secret_present` flag drives the saved state. A pasted or generated replacement requires confirmation after the exact value is in the field; editing it invalidates confirmation | fixed |

## Proposed text
Honest text for now, then "after fix".
**Intro:** "What this is for: optional paid access to recordings through Stripe, plus free passes for named people. Who can use this: Setup admin. **Not ready for live use in this version. Leave this off.** If you turn it on, every recording asks every resident for a pass, no email is sent so residents cannot sign in, and residents cannot subscribe. The video file itself is not locked; only a screen in front of the player is." After fix: remove the warning once email, tiers, checkout and server-side blocking work.
**Banner when box ticked:** "Paywall is ON (test use only). Every recording will ask residents for a pass." **When off:** "Paywall is OFF. All recordings are public."
**Secret field:** label "Signing secret"; explain that a saved value is never returned and blank keeps it. A pasted or generated replacement must be confirmed after its exact value is in the field; editing it invalidates confirmation, and Cancel discards it. Clearing requires a separate confirmed action followed by Save.
**Generate (now):** "Fills the box with a new random secret. When replacing a saved value, confirm the exact value shown in the field before you press Save; editing it clears confirmation. Stripe's own webhook secret is a different value created in the Stripe website; ask IT which one to use."
**Provider:** hide "mock" unless the station is in lab mode; otherwise "mock (testing only — no payments)".
**Tiers:** "A tier is a price level, for example Basic monthly. Create the price in the Stripe website first, then paste its id here (it starts with price_). CivicCast never creates prices and never stores card numbers." Locked text: "Tick Enable paywall to edit tiers and grants. Tier changes are not saved until you press Save in Config." Footnote unchanged.
**Grants:** "A free pass lets one email address watch without paying. Pass applies to: one recording, one series, or everything." Replace "Scope kind" with "Pass applies to" and "Scope ID" with "Recording or series id". Expiry: "Last valid day (end of that day, UTC). Leave blank for no end." Table note: "Passes you issued before this page was opened are not listed here and cannot be revoked here." Grant is created at once, even if the paywall is not saved on.
**Delete confirm:** "This removes the paywall settings and turns the paywall off. Passes and subscriptions are not deleted by this button" (replace after HELP-09 is checked).
**Remove jargon:** "no card numbers are ever stored here"; drop "DC-1", "DC-4", "PAN", "HMAC".

## Notes for the coder
- Files: `PaywallScreen.tsx`, `civiccast/paywall/models.py`, `civiccast/paywall/router.py`, `tests/paywall/test_router.py`, and `PaywallScreen.test.tsx`. The screen reads `signing_secret_present`; PUT preserves omitted/null values and accepts explicit empty string to clear.
- Pins: `PaywallScreen.test.tsx` covers both paywall banners, the signing-secret field, confirmation of typed and generated replacement values, invalidation after edits, cancellation, clear confirmation, omitted secret on ordinary save, delete confirmation, tiers and grants. Search before renaming user-facing strings.
- Code fix still needed outside slice #10: email sender (default no-op), public tiers and checkout routes, server-side blocking of media, per-recording gating, and server-side grant history remain open (HELP-03, HELP-06). Until then consider hiding the sidebar entry.
