> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Federation (nav id: activitypub)

Sidebar: System Health > **Federation**; page H1 "ActivityPub federation"; small label "Federation". Manual authority: `docs/manual/src/17-something-wrong.md` section "Understand federation (Federation)" (`#understand-federation-federation`), `26-integrations.md` (`#federation-activitypub`) and the Warning in `15-publishing.md` about public notices.

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/ActivityPubScreen.tsx` (670 lines: ErrorState, DisabledPanel, summary tiles, policy panel, follower list, DeliveryRetryPanel, outbox panels), `manual-link.ts`, `ConfirmDialog.tsx`. Server: `civiccast/activitypub/router.py` (keygen next-step text at 453-457), `config.py`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "ActivityPub federation"; "Station follows, moderation, policy controls, and signed delivery evidence share one operator surface." | H1 and intro | ActivityPubScreen.tsx:582, 584 |
| "Could not load federation status."; "Next step. Retry the request. If it fails again, check the API server logs and staff-token state."; "Retry" | error card | 75, 80, 88 |
| "Federation is off"; "The station actor is not advertised and the public inbox is unavailable."; tag "Default-safe" | off panel | 138, 140, 147 |
| "Federation lets other services that speak the ActivityPub protocol — the network behind Mastodon and similar sites, sometimes called "the fediverse" — follow this station and see when a new meeting is published, the same way someone might follow a page on a social network. Most stations do not need this and can leave it off."; "Read more in the manual" | off panel | 151-157 |
| "A station key already exists on disk. Generating again reuses it — it will not create a second, different identity."; "Generate station key" / "Generating..." | off panel | 163-164, 178 |
| Dialog "Generate the station key?": "This creates the station's permanent federation identity key on disk. Other fediverse services will recognize the station by this key once federation is enabled." or "A station key already exists on disk, so generating reuses it — the station keeps the same federation identity."; "Generate key" | confirm | 183-189 |
| "Station key generated." / "Station key found."; server text "The station key is ready. Give these settings to whoever manages this station's CivicCast environment file, then restart CivicCast to turn federation on."; the `CIVICCAST_ACTIVITYPUB_*` lines; "Copy settings" / "Copied"; "The station key could not be generated." | result | 208, router.py:453-457, 229, 202 |
| Summary tiles Mode (raw `open` / `limited` / `approval-only`), Pending, Accepted, Blocked, Rejected, Removed, Outbox, Deliveries; "Station actor" ("Not exposed"); "Fetch policy" ("Signed fetch required" / "Public actor and collection fetches"); "Domain policy" ("Allow N / block N") | on-state | 240-246, 278-288 |
| Follower tabs Pending, Accepted, Blocked, Rejected, Removed; "No <status> followers."; buttons "Approve", "Reject", "Block" | follower list | 31-35, 379, 333, 342, 354 |
| Reject dialog "Reject <actor>?": "This rejects the pending follow request. The instance stops receiving future publish activity from this station." ("Reject follower"); Block dialog "Block <actor>?": "This blocks the follower permanently — it stops receiving future publish activity and cannot re-follow until unblocked." ("Block follower") | confirm | 630-636 |
| "Delivery retry queue"; "No pending or dead-lettered deliveries."; "Dead letter" / "Retrying"; "Replay delivery"; "Replay failed." | retries | 418, 432, 443, 460, 408 |
| "Outbox evidence"; "No local federation activities yet."; "Delivery attempts"; "No signed delivery attempts recorded." | evidence | 485, 488, 505, 508 |
| "Federation moderation failed. Check the API logs, then retry the follower action." | any moderation failure | 650 |

## What the screen really does
Federation is optional and off by default. When it is off the screen explains it and offers "Generate station key", which creates (or reuses) the station's permanent identity key and shows the settings to hand to IT; it does not turn federation on. The console has no on/off switch: an IT person must set the `CIVICCAST_ACTIVITYPUB_*` settings and restart CivicCast, and federation silently stays off if the web address or key file is missing. When on, the screen shows follower counts, follower requests with Approve, Reject and Block, a retry queue and delivery evidence. Every approved publish also posts a public notice, "New CivicCast recording published: <title>.", to followers; a notice that has gone out cannot be taken back (manual ch. 6). Approve, Reject and Block need the Publish operator or Support admin role; the buttons show to every role. There is no Unblock control.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | After keygen: "Give these settings to whoever manages this station's CivicCast environment file, then restart CivicCast" | Never says plainly that federation is turned on by IT editing service settings; the old manual points to a switch that does not exist; a clerk does not know what an environment file is | blocks work |
| HELP-02 | Nav "Federation" vs H1 "ActivityPub federation" | Two names for one screen | cosmetic |
| HELP-03 | "Federation moderation failed. Check the API logs" (650) | Shown for every failure, including a role refusal (server allows only `publish_operator` and `support_admin`, router.py:55) | misleading |
| HELP-04 | "cannot re-follow until unblocked" (634) | No Unblock action exists in the console; the Blocked tab has no buttons | misleading |
| HELP-05 | Settings block and "Copy settings" | Raw `KEY=value` lines; no note that they are for IT | misleading |
| HELP-06 | `station actor`, `inbox`, `Signed fetch`, `Domain policy`, `Outbox`, `dead letter`, `HTTP <code>` | On-state jargon with no definitions (the off text is plain) | misleading |
| HELP-07 | Mode tile `approval-only` | Raw word; the three modes (open, limited, approval-only) are never explained | misleading |
| HELP-08 | "Default-safe" (147) | Engineer's phrase | cosmetic |
| HELP-09 | Approve gives no confirmation | Counts change only after a refetch | cosmetic |
| NEW-1 | "see when a new meeting is published" (151-154) | Every approved publish posts a public notice to followers that cannot be recalled; the Publish screen does not mention it either | misleading |
| NEW-2 | "check the API server logs and staff-token state" (80) | Jargon; a clerk cannot do either | cosmetic |

## Proposed text
**Header:** H1 "Federation"; label "System Health". Intro: "What this is for: optional. Lets other websites that use the ActivityPub standard (Mastodon and similar sites, sometimes called the fediverse) follow this station and see when a recording is published. Who can use this: everyone can open it. Setup admin makes the station key. Publish operator and Support admin approve, reject and block followers."
**Off panel:** keep the existing plain paragraph. Replace the tag "Default-safe" with "Off. Nothing is shared." Add: "Federation is turned on by your IT person: they apply the settings below to the CivicCast service and restart it. It stays off if the web address or key file is missing."
**Key dialog (new key):** "This makes the station's permanent federation identity key. Other sites will recognise the station by it. Making a key does not turn federation on."
**Result block:** "Send these settings to your IT person. They go in the CivicCast service settings, then CivicCast restarts." Label "Copy settings for IT".
**Public notice warning (on-state, above the follower list):** "When federation is on, every recording you publish to the portal also posts a public notice to the sites that follow you. A notice that has gone out cannot be taken back."
**Tile helps:** Mode "How follow requests are handled: approval-only means you approve each follower." Station actor "The station's address on the network." Signed fetch "Other sites must prove who they are." Domain policy "Sites you always allow or always block." Outbox "Notices CivicCast has made." Dead letter "A notice that could not be delivered after several tries."
**Block dialog:** "Block <site>? It stops receiving your notices and cannot follow again. This cannot be undone from the console; ask IT to remove a block." After fix: add Unblock.
**Moderation failure:** show the server text; for a role refusal: "You need the Publish operator or Support admin role to do this."
**Retry on load error:** "Could not load federation status. Click Retry. If it keeps failing, tell your IT person."

## Notes for the coder
- Files: `ActivityPubScreen.tsx`, `civiccast/activitypub/router.py:453-457` (next-step sentence), `config.py` (on/off rule at 64-73).
- Pins: `e2e/activitypub.spec.ts` pins the H1 "ActivityPub federation" (line 168), the sidebar button name "Federation", "Federation is off", "Default-safe" (273), `/most stations do not need this/i`, "Generate station key", "Generate key", "Station key generated.", the `approval-only` tile, "Signed fetch required", "Outbox evidence", "Delivery attempts", "Delivery retry queue", "Replay delivery", dialog names "Reject <actor>?" and "Block <actor>?", and "Could not load federation status."; `ActivityPubScreen.test.tsx` pins "Station key generated" and `approval-only`; `tests/activitypub/test_activitypub_keygen.py` pins the server key text. No test pins "Federation moderation failed".
- Code fix needed, not text: an on/off switch (or visible status explaining why it is off); an Unblock action; show the server's role message on a moderation failure; success feedback after Approve.
