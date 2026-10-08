> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Subscription paywall (nav id: paywall)

Sidebar: Setup > **Paywall**; page H1 "Subscription paywall". Manual authority: `docs/manual/src/22-configuration.md` section "Configure the Paywall" (`#configuration-paywall`), `16-station-business.md` ("Turn on paid access") and `15-publishing.md` ("The paywall: optional paid access"). The manual tells readers to leave the paywall off in beta.10.

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/PaywallScreen.tsx` (1208 lines: PaywallScreen, PaywallEditor, ConfigCard, TiersSection, GrantsSection). Server behaviour: `civiccast/paywall/router.py`, `store.py`. Lines confirmed by opening the file (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Subscription paywall"; "Optional, opt-in monetization. Default OFF — when off, every asset is public and the paywall code path is inert. Stripe-hosted Checkout only; no card or PAN data ever touches CivicCast (DC-4)." | H1 and intro | PaywallScreen.tsx:409, 411-413 |
| "Forbidden — the subscription paywall is a setup-admin surface. Ask your station admin for access."; "Loading…"; "Could not load your staff identity (<text>). Check that you are signed in and the local API is running, then retry."; "Loading paywall config…"; "Could not load the paywall config (<text>)." | gate and states | 188-189, 168, 176, 224, 232 |
| "Config" | card title | 555 |
| "Paywall is ON. Tier-based gating active." / "Paywall is OFF. All content is public — no subscription required to view." | banner (follows the box, before Save) | 559-560 |
| "Enable paywall"; "Default off (DC-1)." | switch | 573, 576 |
| "Provider": "stripe (Stripe-hosted Checkout)" / "mock (contract tests / lab)" | select | 581, 591-592 |
| "Signing secret (HMAC)" (placeholder "base64 secret; rotate via Generate"); "Show signing secret" / "Hide signing secret"; "Generate new secret"; "Confirm regenerate"; "Confirming will overwrite the current secret. All unredeemed magic links stop working and Stripe webhook verification will fail until you update Stripe's webhook secret."; "Rotating this invalidates all unredeemed magic links and breaks webhook verification until Stripe is updated." | secret | 597, 604, 613, 651, 632, 661-663, 656-657 |
| "Save" / "Saving…" (aria "Save paywall config"); "Saved."; "Could not save the config." | save | 677, 671, 719, 426 |
| "Delete config"; "Confirm delete" / "Deleting…"; "Confirming will remove the paywall config entirely and disable gating until you re-create it."; "Could not delete the config." | delete | 708, 689, 714-715, 429 |
| "Tiers"; "Save with the enable toggle on to manage tiers and grants."; table "Existing tiers" (Tier ID, Name, Stripe price, Interval, Actions); "No tiers configured yet. Add one below; each tier maps to an existing Stripe price id."; "Remove"; "Tier changes are local until you click Save in the Config section above." | tiers | 784, 787, 791-797, 809-810, 831, 937 |
| "Add tier"; "Tier ID (slug)"; "Display name"; "Stripe price id" (placeholder price_1A2bcDeFgHiJkLmN); "Stripe price IDs start with price_."; "Interval" Monthly / Yearly | add-tier form | 846, 851, 863, 876, 881, 887, 891-916 |
| "Comp access grants"; "Showing grants issued in this session. Server-side grant history is a follow-up."; "Save with the enable toggle on to manage tiers and grants."; "Recently issued grants" (Email, Scope, Expires, Actions); "No grants issued in this session yet." | grants | 1023, 1030-1031, 1035, 1041-1047, 1059 |
| "Issue comp grant"; "Email" (placeholder viewer@example.gov); "Scope kind" (asset, series, all (catch-all)); "Scope ID" (placeholder asset-2026-01 / series-council); "Expires at (optional)"; "Issue grant" / "Issuing…"; "Revoke" / "Confirm revoke"; "Could not issue the grant."; "That expiry date could not be read, so no grant was issued. Re-enter it, or clear it to grant access that never expires." | grant form | 1130, 1134, 1147, 1160-1162, 1167, 1181, 1113, 1089, 1201, 486, 385 |

## What the screen really does
It edits the station's one paywall record: an on/off box, a provider, a signing secret, a list of tiers (each tied to a price you create in the Stripe website) and free "comp" passes for named email addresses. It is off by default. Do not rely on it in beta.10. In the code: the sign-in email is sent by a function that does nothing, so a resident never gets a link; the public site's tier-list and checkout routes do not exist on the station; the video file itself is not protected, only a gate shown in front of the player; turning the paywall on does not choose particular recordings, the Watch page asks every resident for a pass on every recording; and the access check trusts the email address it is given. **Save sends the whole form. A blank secret box is saved as "no secret" and erases the stored one, and the box is always blank after a reload.** The grants table lists only passes issued in this browser session.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | Save with a blank "Signing secret (HMAC)" box (352, 596-598) | Sends `null`; the store writes it as the new secret (store.py:198), erasing the stored one. Changing any other setting and pressing Save does this. Magic links and Stripe signature checks then stop | blocks work (silent data loss) |
| HELP-02 | "base64 secret; rotate via Generate" and "update Stripe's webhook secret" (604, 661-663) | Never says where Stripe's webhook secret is; Stripe makes its own `whsec_` value per endpoint, and the code checks Stripe's header with THIS field (service.py:503-535), so Generate may be the wrong value (UNVERIFIED against Stripe docs) | misleading |
| HELP-03 | Intro and banner: "every asset is public"; "Tier-based gating active." (411-413, 559) | The paywall is unfinished: no email, no tiers or checkout route, no server block of the media file; every recording is gated, not chosen ones | blocks work |
| HELP-04 | "PAN", "DC-4", "DC-1", "HMAC", "Scope kind", "Tier ID (slug)", "catch-all", "comp" | Jargon and internal requirement codes | cosmetic |
| HELP-05 | "Save with the enable toggle on to manage tiers and grants." (787, 1035) | Sections unlock when the box is ticked, before Save; the grant form posts to the server at once, whether or not the paywall is saved on | misleading |
| HELP-06 | "Server-side grant history is a follow-up." (1030) | Developer note; passes issued earlier cannot be seen or revoked | misleading |
| HELP-07 | Provider "mock (contract tests / lab)" (592) | Selectable on a live station with no warning; what `mock` does at run time is UNVERIFIED | misleading |
| HELP-08 | "Stripe price IDs start with price_." (887) | Does not say the price must already exist in Stripe; CivicCast never creates a price | misleading |
| HELP-09 | "Confirming will remove the paywall config entirely..." (714-715) | Does not say whether subscribers and passes are kept (UNVERIFIED) | misleading |
| HELP-10 | (Code comments say a 404 maps to an empty form) | The server returns 200 with a default config; no "no config" error exists | cosmetic |
| NEW-1 | "Generate new secret": confirm step explained (651-663) | The box is always empty after reload, so the "Confirm regenerate" step almost never appears and the overwrite warning is not shown | misleading |

## Proposed text
Honest text for now, then "after fix".
**Intro:** "What this is for: optional paid access to recordings through Stripe, plus free passes for named people. Who can use this: Setup admin. **Not ready for live use in this version. Leave this off.** If you turn it on, every recording asks every resident for a pass, no email is sent so residents cannot sign in, and residents cannot subscribe. The video file itself is not locked; only a screen in front of the player is." After fix: remove the warning once email, tiers, checkout and server-side blocking work.
**Banner when box ticked:** "Paywall is ON (test use only). Every recording will ask residents for a pass." **When off:** "Paywall is OFF. All recordings are public."
**Secret box (now):** label "Signing secret"; help "CivicCast never shows this again after you save. **If this box is empty when you press Save, the saved secret is erased.** Paste the secret again every time you press Save." After fix: show "A secret is saved" and send nothing when the box is untouched ("leave blank to keep it").
**Generate (now):** "Fills the box with a new random secret. It is not saved until you press Save. Stripe's own webhook secret is a different value created in the Stripe website; ask IT which one to use."
**Provider:** hide "mock" unless the station is in lab mode; otherwise "mock (testing only — no payments)".
**Tiers:** "A tier is a price level, for example Basic monthly. Create the price in the Stripe website first, then paste its id here (it starts with price_). CivicCast never creates prices and never stores card numbers." Locked text: "Tick Enable paywall to edit tiers and grants. Tier changes are not saved until you press Save in Config." Footnote unchanged.
**Grants:** "A free pass lets one email address watch without paying. Pass applies to: one recording, one series, or everything." Replace "Scope kind" with "Pass applies to" and "Scope ID" with "Recording or series id". Expiry: "Last valid day (end of that day, UTC). Leave blank for no end." Table note: "Passes you issued before this page was opened are not listed here and cannot be revoked here." Grant is created at once, even if the paywall is not saved on.
**Delete confirm:** "This removes the paywall settings and turns the paywall off. Passes and subscriptions are not deleted by this button" (replace after HELP-09 is checked).
**Remove jargon:** "no card numbers are ever stored here"; drop "DC-1", "DC-4", "PAN", "HMAC".

## Notes for the coder
- Files: `PaywallScreen.tsx` (handleSave at 345-355 must send "unchanged" when untouched; labels at 597, 1147, 1167); `civiccast/paywall/store.py:198` (upsert must not overwrite `signing_secret` with `None`); `router.py:268-293` (return `signing_secret_present`, which the screen does not read).
- Pins: `PaywallScreen.test.tsx` pins "Paywall is ON", "Paywall is OFF", "Save with the enable toggle", "Delete config" and the label regex `/Signing secret \(HMAC\)/i` (line 167) plus aria "Show signing secret"; `AlertsScreen.test.tsx`-style "Confirm delete" strings also exist in other screens, so search before renaming. No test pins the intro or the grant labels.
- Code fix needed, not text: secret erase (HELP-01); email sender (default no-op), public tiers and checkout routes, server-side blocking of media, per-recording gating, and server-side grant history are all missing (HELP-03, HELP-06). Until then consider hiding the sidebar entry.
