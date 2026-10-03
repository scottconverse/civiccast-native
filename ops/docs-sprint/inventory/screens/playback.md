# Playback policy  (nav id: playback, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/PlaybackPolicyScreen.tsx` (line numbers below are this file unless noted),
`.../components/EmptyState.tsx`, `.../api/client.ts:2001-2023`.
Backend: `civiccast/playback_policy/router.py`, `models.py`, `store.py`, `entitlements.py`; consumers `civiccast/podcast/router.py:44-95`,
`civiccast/app_platform/router.py:880-925`.
Who can open it: nav entry has no `requiredRoles` (`Sidebar.tsx:164`), so every signed-in operator sees it and the screen does no role check of its own.
- Viewing a policy and the decision log: any valid staff token (`router.py:69-77,111-121` have no role dependency).
- Saving a policy: `publish_operator` or `support_admin` (`router.py:94`). `setup_admin` and `meeting_operator` get a 403 on Save with the server text
  "This action requires one of these CivicCast roles: ..." (shown in the red box, lines 453-461).
- Issuing a signed viewer token (`POST /api/staff/playback-policy/viewer-tokens`, same two roles, `router.py:80-87`): no button for it exists on this screen.

## What it is for
It stores, per channel or per single recording, who is supposed to be allowed to watch (everyone, any signed-in resident account, or members of one invite group),
an optional "public record" lock, and up to four short "prerolls" (a graphic or video card shown before playback). It also shows the last eight allow/block decisions the
policy engine made. IMPORTANT (see HELP-01): in this repository the only things that read the policy are the podcast feed, the app-catalog metadata, and a public
"evaluate" API; the web portal's video player does not call it.

## What the user sees (top to bottom)
1. Header: h1 "Playback policy", subtitle "Access gates, public-record locks, prerolls, and decision audit." and the button "Save policy" (lines 437-451).
2. Red alert box when loading or saving fails (lines 453-461).
3. Panel 1: "Policy target" tabs Channel / Asset, text box "Target ID" (default `government`), a box "Updated {date}" or "Updated Never"; "Access tier" tabs Public / Authenticated / Invite only; boxes "Invite group" and "OIDC provider"; checkboxes "Authenticated RSS", "Public-record asset", "Public archive complete" (lines 463-548).
4. Panel 2: checkbox "Preroll enabled", button "Add preroll", and one editor per preroll (Creative ID, Kind Graphic/Video, Asset URL, Accessible label, Duration seconds, Skip after seconds, Transcript URL, Remove) (lines 550-610).
5. Panel 3: h2 "Decision audit", button "Refresh", then the last 8 decisions newest first (lines 612-675).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Policy target: Channel / Asset | Chooses whether the policy applies to a whole channel or one recording | selects `GET/POST /api/staff/playback-policy/{channel|asset}/{id}` | any to view | An asset policy wins over its channel's policy (`store.py:109-120`) |
| Target ID | Which channel id or asset id | debounced 400 ms (line 372) then GET | | Default `government`. Must be lowercase letters, digits, `_`, `-` (slug, `models.py:133`) or Save returns 422. No dropdown of real channels/assets |
| Access tier: Public / Authenticated / Invite only | Sets `access_tier` | saved on Save | publish_operator / support_admin | See HELP-01 on what is actually enforced |
| Invite group | Name of the invite group residents must belong to | `invite_group_id` | | Enabled only for Invite only; Save disabled while empty (line 419). Not stored for other tiers |
| OIDC provider | Id of an external sign-in provider | `oidc_provider_id` | | Enabled for Authenticated and Invite only. Free text; no provider list exists in this screen |
| Authenticated RSS | Allows the podcast feed for this channel to be fetched with a viewer token | `authenticated_rss_enabled` | | Disabled when tier is Public (line 520); forced off by the two locks below |
| Public-record asset | Locks the policy to public: sets tier Public and turns Authenticated RSS off | lines 526-535 | | Server also rejects any public-record policy that is gated (`models.py:226-232`) |
| Public archive complete | Same lock, meaning the archive is finished | lines 536-545 | | Also stored; used by the app catalog (`app_platform/router.py:904-912`) |
| Preroll enabled | Turns prerolls on | `preroll.enabled` | | When on, at least one complete preroll is required to Save (lines 420-427) |
| Add preroll | Adds a blank preroll row | local | | Max 4 rows (line 562); disabled until Preroll enabled |
| Remove | Deletes that row from the form | local | | Not saved until "Save policy" |
| Creative ID / Asset URL / Accessible label / Duration seconds / Skip after seconds / Transcript URL | Fields of one preroll | stored in `preroll.creatives` | | Required: Creative ID (a slug, unique), Asset URL, Accessible label, Duration > 0. Server limits: duration 1-600 s, skip window cannot exceed duration (`models.py:160-180`). Duration and Skip accept digits only |
| Save policy (line 449) | Saves everything above for the chosen target | `POST /api/staff/playback-policy/{type}/{id}` | publish_operator / support_admin | No confirmation dialog. Label becomes "Saving". Takes effect at once for later decisions (state file `playback-policy-state.json`, `store.py:25,136-156`) |
| Refresh (Decision audit) | Re-reads the log | `GET /api/staff/playback-policy/audit/events` | any | Shows only the last 8 events (line 639); file keeps the last 500 (`store.py:147`) |

## States
- Loading: no special text; the form shows defaults (public, prerolls off, one blank card "station-card" / "Station announcement") until data arrives.
- Never saved: "Updated Never" (line 155); the server answers with a default public policy (`store.py:55-68`).
- Error: red box with the server detail, else "Playback policy request failed." (line 459). Audit failure: "Audit log request failed." (line 629).
- Incomplete preroll while enabled: red alert "Preroll 2 is missing required fields." or "Prerolls 2, 3 are missing required fields." followed by "Fill in every field (or remove the row) before saving -- an incomplete row would otherwise be silently dropped." (lines 576-588). Note: the "required" check only needs Creative ID, Asset URL, Accessible label and Duration (lines 111-118), not "every field".
- Audit empty: headline "No playback decisions yet." body "Every time the player allows or blocks a viewer under this policy, the decision is logged here. Decisions appear as soon as residents start watching." (lines 633-636)
- Offline / not configured: no special state; the 400 ms debounce and React Query defaults apply. UNVERIFIED what a lost connection looks like (no code for it on this screen).

## Typical task flows
1. Gate a podcast feed: Policy target Channel, Target ID = the channel id, Access tier Authenticated, tick Authenticated RSS, Save. The feed then answers 403 "Authenticated RSS is not enabled for this channel." if the box is off, or 401 "A signed viewer token is required for this podcast feed." without a token (`podcast/router.py:52-80`). Producing a viewer token has no button here.
2. Lock a recording as a public record: Asset, Target ID = asset id, tick Public-record asset, Save.
3. Add an announcement preroll: tick Preroll enabled, fill the card, Save. It is stored with `apply_to_archive_exports: false` always (line 146); the server rejects `true`.
4. Review decisions: read Decision audit; press Refresh.

## Statuses and words on this screen
Decision badges: `allowed` (green) / `blocked` (red), raw lowercase displayed upper-case (lines 659-666). Reasons from the engine: "Playback is public.", "Sign in with a viewer account to play this content.", "Viewer account is authenticated for playback.", "Viewer account has the required invite.", "This content requires a matching invite." (`store.py:168-181`). Audit row title is `{asset_id} / {channel_id}`; podcast feed checks appear as `{channel}-podcast-feed / {channel}` (`podcast/router.py:70`).
Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`CIVICCAST_PLAYBACK_POLICY_STATE_PATH` (state file; native build sets it, `scripts/build_native_app_payload.py:633`), `CIVICCAST_ALLOW_EPHEMERAL_STORES=1` (no persistence, `store.py:163`).
Subscription secrets file for signing tokens (`playback_policy/entitlements.py:369`, `subscribe.secrets`).
API: `/api/staff/playback-policy/...`; public `POST /api/public/playback-policy/evaluate` (takes `asset_id`, `channel_id`, optional `viewer_token`).
Related screens: Paywall (setup_admin) and Federation are separate; Publish > Podcast surface is "coming in a future release".

## Help-text findings
- [HELP-01] lines 490-499 ("Access tier: Public / Authenticated / Invite only") and the empty-state text lines 635 — the screen reads as if choosing "Invite only" stops uninvited people watching. Code search of `civiccast/` shows `evaluate`/`effective_policy` consumers only in: the podcast RSS route, the app-catalog builder (it copies the tier into catalog metadata as `entitlement_required`), and the public `/evaluate` endpoint. The resident web player (`apps/portal-public/src/HlsPlayer.tsx`) and the media/HLS route (`stream/media_router.py`) never call it; no TypeScript, Swift or Kotlin client in the repo calls `/api/public/playback-policy`. So the video itself is not blocked by this setting, and the decision log stays empty because nothing calls `/evaluate` (except podcast-feed checks). Fix before documenting as a feature: either wire enforcement or relabel the screen "Planned access rules (not yet enforced on video)". The manual must not promise resident sign-in gating.
- [HELP-02] lines 501-512 "Invite group", "OIDC provider" — no explanation what these are or where the groups/providers are created. Viewer accounts and invite groups exist only inside signed tokens (`entitlements.py:352-370`); there is no screen to create them or issue a token. Add: "Invite group: a short name (lowercase, no spaces) that you put into residents' sign-in tokens."
- [HELP-03] line 434-441 Target ID — default `government` is unexplained, and a typo silently creates a new policy for a channel that does not exist (the server accepts any slug). Use a drop-down of real channels/assets and say "Use the channel or recording ID shown on Channels / Assets."
- [HELP-04] lines 517-545 — "Public-record asset" and "Public archive complete" are jargon and clicking either silently flips Access tier to Public and clears Authenticated RSS. Add helper text: "Public records can never be restricted. Ticking this sets access to Public."
- [HELP-05] lines 555-575 — "Preroll" is not defined; say "A short card or clip shown to residents before the recording starts. Prerolls play for viewers only; they are never added to archive copies." Also "Skip after seconds" has no "blank = cannot skip" note (blank sends null, line 129-131).
- [HELP-06] lines 634-636 empty-state sentence "Decisions appear as soon as residents start watching" — see HELP-01; likely false for video.
- [HELP-07] lines 322-345 field labels "Duration seconds", "Skip after seconds", "Asset URL" with placeholder `/media/preroll/station-card.png` — no statement of where the file must live or that a relative path is read by the player; UNVERIFIED that any player loads prerolls (see below).
- [HELP-08] line 449 "Save policy" has no success message; the only sign is "Updated {time}" changing (line 484). Add a "Saved" notice.
- [HELP-09] lines 453-461 — a 403 for roles without publish_operator/support_admin is shown as raw server text after the person has typed everything; hide or disable Save and say "Only Publish operators and Support admins can change playback rules" up front.

## Screenshot plan
1. Fresh state (Channel / government, Public, prerolls off).
2. Invite only selected with an Invite group typed, and the Save button state when the group is empty (disabled).
3. Public-record asset ticked (Access tier snaps to Public).
4. Preroll enabled with one complete card, and one with a missing field (red alert, Save disabled).
5. Decision audit with at least two rows (create by calling the podcast feed of a gated channel or `POST /api/public/playback-policy/evaluate`), and the empty state.
Setup: a publish_operator token; for audit rows, a gated channel with Authenticated RSS on.

## UNVERIFIED / open questions
- UNVERIFIED: whether any shipped player (Roku/tvOS/Android shells under `apps/app-platform-shells`, `apps/ott-native`, `apps/ctv-reference`) reads `entitlement_required` or the preroll list and enforces it. grep shows no use of `entitlement_required` or `preroll` in the portal-public source; shells not read in full.
- UNVERIFIED: whether the web portal injects prerolls at all (no match found in `apps/portal-public/src`).
- UNVERIFIED: how residents would obtain a viewer token in production (only the staff-only issue endpoint was found).
- UNVERIFIED: persistence location on a normal install (`default_storage_dir()`, not read here).
