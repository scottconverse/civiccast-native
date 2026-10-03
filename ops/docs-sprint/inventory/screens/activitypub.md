# Federation  (nav id: activitypub, section: System Health)
Source files (under `civiccast/apps/portal-operator/src/`): `screens/ActivityPubScreen.tsx`, `screens/manual-link.ts`, `components/ConfirmDialog.tsx`, `api/client.ts` (:2222-2291).
Server: `civiccast/activitypub/router.py`, `activitypub/config.py`.
Route: `#/activitypub`. Nav label `Federation`; page h1 `ActivityPub federation` (:582), eyebrow `Federation`.
Who can open it: everyone signed in (`Sidebar.tsx:180`, no `requiredRoles`). The screen has no role gating of its own; the server does (below).

## What it is for
Optional, off by default. When switched on, other servers on the "fediverse" (Mastodon and similar) can follow the station and see
when a meeting is published. This screen has two modes: **off** (explains it and offers `Generate station key`) and **on** (follower
approval, policy summary, delivery retry queue, recent outbox and delivery evidence). The console cannot switch it on or off.

## What the user sees (top to bottom)
Header (h1, "Station follows, moderation, policy controls, and signed delivery evidence share one operator surface." :584), then:
- **Loading:** three grey placeholder bars. **Error:** red card `Could not load federation status.` + detail + "**Next step.** Retry the request. If it fails again, check the API server logs and staff-token state." + button `Retry`.
- **Federation off** (`DisabledPanel` :108): heading `Federation is off`; "The station actor is not advertised and the public inbox is unavailable."; green tag `Default-safe`; paragraph "Federation lets other services that speak the ActivityPub protocol — the network behind Mastodon and similar sites, sometimes called "the fediverse" — follow this station and see when a new meeting is published, the same way someone might follow a page on a social network. **Most stations do not need this** and can leave it off." + link `Read more in the manual` (-> `/help#provider-federation`); if a key file exists "A station key already exists on disk. Generating again reuses it — it will not create a second, different identity."; button `Generate station key`.
- **Federation on:** summary tiles (Mode, Pending, Accepted, Blocked, Rejected, Removed, Outbox, Deliveries); policy panel (Station actor, Fetch policy, Domain policy); filter tabs `Pending` `Accepted` `Blocked` `Rejected` `Removed` with counts; follower list; `Delivery retry queue`; `Outbox evidence` and `Delivery attempts`.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Generate station key` -> dialog `Generate the station key?` -> `Generate key` | Creates (or reuses) the station's federation identity key on disk and shows the settings to apply | `POST /api/staff/activitypub/keygen` | server `setup_admin` only (`activitypub/router.py:398`) | Dialog body: no key yet "This creates the station's permanent federation identity key on disk. Other fediverse services will recognize the station by this key once federation is enabled."; key exists "A station key already exists on disk, so generating reuses it — the station keeps the same federation identity." Does **not** turn federation on (`router.py:401-427` docstring) |
| result block: `Station key generated.` / `Station key found.`, server `next_step` text, list of `CIVICCAST_ACTIVITYPUB_*` settings, `Copy settings` (-> `Copied`) | Copies `KEY=value` lines to the clipboard | clipboard only | none | `next_step`: "The station key is ready. Give these settings to whoever manages this station's CivicCast environment file, then restart CivicCast to turn federation on." Settings: `MODE=approval-only`, `BASE_URL`, `HANDLE` (default `council`), `PRIVATE_KEY_PATH`, `AUTHORIZED_FETCH=1` |
| filter tabs (`role=tab`) | Lists followers by status | `GET /api/staff/activitypub/followers?status=` | none found on server | Only requested when federation is on |
| `Approve` (pending only) | Accepts the follow request | `POST .../followers/approve` `{actor}` | server `publish_operator` or `support_admin` (`_MODERATION_ROLES`, `router.py:55`) | No confirm. UI shows the button to every role |
| `Reject` (pending only) | Rejects the request | `POST .../followers/reject` | same | ConfirmDialog `Reject <actor>?` body "This rejects the pending follow request. The instance stops receiving future publish activity from this station.", confirm `Reject follower` |
| `Block` (any status except blocked) | Blocks the follower | `POST .../followers/block` | same | ConfirmDialog `Block <actor>?` body "This blocks the follower permanently — it stops receiving future publish activity and cannot re-follow until unblocked.", confirm `Block follower`. **No unblock control exists** |
| `Replay delivery` (dead-letter rows) | Retries a failed delivery | `POST .../delivery-retries/{id}/replay` | same | Error text shown from server or `Replay failed.` |
| `Retry` (error card) | Reloads status | refetch | none | |

Note: setup admins who lack `publish_operator`/`support_admin` get a 403 on Approve/Reject/Block. The first-admin token holds all five roles, so this only bites role-limited tokens.

## States
| State | Text |
|---|---|
| Off | `Federation is off` card (see above); nothing else is requested |
| Loading | placeholder bars; `followersQuery` same |
| Empty followers | `No <status> followers.` e.g. `No pending followers.` |
| Empty retry queue | `No pending or dead-lettered deliveries.` |
| Empty outbox / deliveries | `No local federation activities yet.` / `No signed delivery attempts recorded.` |
| Moderation failed | `Federation moderation failed. Check the API logs, then retry the follower action.` (always this text, even for a permission error, `:650`) |
| Key generation failed | server detail or `The station key could not be generated.` |
| Status error | the red `Could not load federation status.` card (status, followers, outbox or deliveries error) |

## Typical task flows
1. Learn what it is: read the `Federation is off` text; `Read more in the manual`.
2. Prepare to turn on: `Generate station key` -> confirm -> `Copy settings` -> give settings to IT -> IT edits the environment and restarts CivicCast (outside the console).
3. After it is on: `Pending` tab -> `Approve` / `Reject` -> watch `Accepted` count; `Block` a bad instance; `Replay delivery` for dead letters.

## Statuses and words on this screen
- Follower status tag (lowercase word, capitalised by CSS): pending (amber), accepted (green), blocked (red), rejected (grey), removed (blue) (`:30-44`).
- `Mode` tile shows the raw server value: `open`, `limited`, `approval-only` (`activitypub/config.py:16`).
- `Station actor`: URL or `Not exposed`. `Fetch policy`: `Signed fetch required` / `Public actor and collection fetches`. `Domain policy`: `Allow N / block N` (domain lists come only from environment/files, `config.py:75-83`; no UI to edit).
- Retry row: `Dead letter` / `Retrying`, `attempt N · HTTP code`.
- Federation is "on" only when mode is not `disabled` **and** base URL, private key path and a readable key are all present; otherwise it silently stays disabled (`config.py:64-73`).

## Related settings / env / CLI / API
Env: `CIVICCAST_ACTIVITYPUB_MODE`, `_BASE_URL` (or `CIVICCAST_PUBLIC_BASE_URL`), `_HANDLE`, `_DISPLAY_NAME`, `_PRIVATE_KEY_PATH`, `_PUBLIC_KEY_PEM`, `_AUTHORIZED_FETCH`, `_BLOCKLIST[_FILE]`, `_ALLOWLIST[_FILE]`, `_LAB_ALLOW_LOCAL`, `_INBOX_RATE_LIMIT`, `_INBOX_RATE_WINDOW_SECONDS`. CLI: `civiccast activitypub keygen` (`cli.py:2189`). Key file default: `activitypub-station-key.pem` next to `station-state.json` (`router.py:92-107`). Public endpoints: `/.well-known/webfinger`, `/.well-known/nodeinfo`, `/ap/actor`, `/ap/inbox`, `/ap/followers`, `/ap/outbox` (404 when disabled, `router.py:74-82`).

## Help-text findings
- [HELP-01] The screen never tells the operator how federation actually gets turned on. After `Generate station key` the only guidance is the server sentence about "whoever manages this station's CivicCast environment file ... then restart CivicCast". A clerk does not know what an environment file or restart is, and the manual says "no command line is required" and "See the station's ActivityPub screen for the current on/off switch" (`docsite/manual.json`, `provider-federation`) - there is no on/off switch on this screen. Fix: say plainly "Federation is turned on by your IT person editing settings and restarting the CivicCast service" and name this the last step; fix the manual.
- [HELP-02] Manual names the screen "ActivityPub" ("open ActivityPub in the console"); the nav entry is `Federation`. Fix: say "Federation".
- [HELP-03] ActivityPubScreen.tsx:650 error text blames "the API logs" for every moderation failure, including a role/permission failure (server allows only `publish_operator` and `support_admin`, `router.py:55`). The Approve/Reject/Block buttons are shown to every role. Fix: show the server message ("This action requires one of these CivicCast roles: ...") and name the role in plain words.
- [HELP-04] :634 "cannot re-follow until unblocked" - there is no unblock action in the console; the `Blocked` tab lists entries with no buttons (`:346` hides Block, nothing replaces it). Fix: say how to unblock or remove the sentence.
- [HELP-05] :164 and :186 "Generating again reuses it" is accurate, but nothing says that the key file path and the `CIVICCAST_ACTIVITYPUB_*` names are IT items; `Copy settings` copies raw `KEY=value` lines. Add "send this to your IT person".
- [HELP-06] Jargon on the on-screen cards: `station actor`, `inbox`, `Signed fetch`, `Domain policy Allow 0 / block 0`, `Outbox`, `dead letter`, `HTTP <code>`, `Key <id>`. The off-state explanation is good plain language; the on-state is not. Fix: one-line meanings under each tile.
- [HELP-07] `Mode` tile shows `approval-only` etc. raw; the three modes (open, limited, approval-only) are never explained on screen.
- [HELP-08] "Default-safe" (:147) is an engineer's phrase; a clerk may not know it means "off and nothing is exposed".
- [HELP-09] No success feedback after `Approve` (no toast); the tile counts change after a refetch.

## Screenshot plan
1. `Federation is off` card (default state) with `Read more in the manual`.
2. `Generate the station key?` dialog and then the result block with `Copy settings`.
3. A station with federation on (needs env set and restart): summary tiles, policy panel, one pending follower with three buttons, Block dialog.
4. Delivery retry queue with a dead-letter row (needs seeded data; UNVERIFIED if lab station has any).

## UNVERIFIED / open questions
- UNVERIFIED: what `Approve` does on the wire (sends an Accept to the follower's inbox?). `activitypub/service.py` not read.
- UNVERIFIED: whether Approve/Reject/Block for a role-limited token shows the 403 text anywhere (UI always shows the generic message).
- UNVERIFIED: how a station that has federation on would unblock a blocked follower (API not found in `router.py` role scan; no unblock route listed).
- UNVERIFIED: which meetings/events are announced to followers ("when a new meeting is published" is the product claim; publish hook not read).
- UNVERIFIED: whether the status endpoint or follower reads are limited by role (no `require_any_role` found in decorators; function bodies not fully read).
