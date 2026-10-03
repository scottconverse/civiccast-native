# Playback policy (nav id: playback)

Console group: Publish. Spec for the in-app help of the Playback policy screen. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/PlaybackPolicyScreen.tsx` unless stated.

## Where the help text lives now
- Heading 437; subtitle 439; Save policy 449; error box 453-461 (fallback text 459).
- Policy target panel: "Policy target" 469; "Target ID" 479 (default `government`, state default near 65); "Updated {date}" 484; "Access tier" 491; "Invite group" 502; "OIDC provider" 508; "Authenticated RSS" 518; "Public-record asset" 527; "Public archive complete" 537.
- Preroll panel: "Preroll enabled" 556; "Add preroll" 573; "Preroll {n}" 294; field labels 300-345 and placeholder 324; incomplete-row alert 576-588.
- Decision audit: heading 617; Refresh 624; audit error 629; empty text 634-635.
- Server: `civiccast/playback_policy/models.py:133,160-180,226-232`; consumers `civiccast/podcast/router.py:44-95`, `civiccast/app_platform/router.py:880-925`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Access gates, public-record locks, prerolls, and decision audit." | Subtitle | :439 |
| "Policy target" (Channel / Asset); "Target ID" | Panel 1 | :469, 479 |
| "Updated {date}" / "Updated Never" | Panel 1 | :484 |
| "Access tier" (Public / Authenticated / Invite only) | Panel 1 | :491 |
| "Invite group"; "OIDC provider" | Panel 1, no help | :502, 508 |
| "Authenticated RSS"; "Public-record asset"; "Public archive complete" | Panel 1 checkboxes, no help | :518, 527, 537 |
| "Preroll enabled"; "Add preroll"; "Skip after seconds"; "Asset URL" (placeholder "/media/preroll/station-card.png") | Panel 2 | :556, 573, 324 |
| "Preroll {n} is missing required fields." / "Fill in every field (or remove the row) before saving -- an incomplete row would otherwise be silently dropped." | Panel 2 alert | :583-586 |
| "Save policy" / "Saving" (no confirmation message) | Button | :449 |
| "Playback policy request failed." (or the server's raw role sentence) | Error box | :459 |
| "No playback decisions yet." / "Every time the player allows or blocks a viewer under this policy, the decision is logged here. Decisions appear as soon as residents start watching." | Decision audit empty | :634-635 |
| "Audit log request failed." | Audit error | :629 |

## What the screen really does
It saves a policy record for one channel or one recording: an access tier (Public, Authenticated, Invite only), an invite group, a sign-in provider name, a public-record lock, and up to four prerolls. A policy on a recording wins over the policy on its channel. In beta.10 the access tier is read in only three places: a channel's podcast feed, the app listing (copied as information) and a public "evaluate" service. The resident portal's video player and the video file server never read it, so choosing Authenticated or Invite only does not stop anyone from watching a video on the portal. The public-record lock is enforced when you save: a public-record policy cannot be gated. We found nothing in the portal that plays prerolls. The Decision audit fills only when something asks for a decision, which today is the podcast feed, so it is usually empty. Save needs publish_operator or support_admin; other roles can type but are refused on Save with the server's role sentence. Anyone signed in can look.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | Access tier, "Access gates", and "Decisions appear as soon as residents start watching" | Not enforced on portal video; log stays empty (`podcast/router.py:44-95`, `app_platform/router.py:880-925`; `HlsPlayer.tsx` and `stream/media_router.py` never call it) | blocks work |
| HELP-02 | "Invite group", "OIDC provider" with no help | Groups and providers exist only inside signed tokens; no screen creates them or issues a token (`entitlements.py:352-370`) | misleading |
| HELP-03 | "Target ID" default `government`, unexplained | A typo silently creates a policy for nothing; the server accepts any lowercase slug | misleading |
| HELP-04 | "Public-record asset", "Public archive complete" | Ticking either sets tier to Public and clears Authenticated RSS silently (`:526-545`) | misleading |
| HELP-05 | "Preroll" undefined; "Skip after seconds" | Blank skip means cannot skip; prerolls are never added to archive copies | cosmetic |
| HELP-06 | Empty-state sentence | See HELP-01 | misleading |
| HELP-07 | Field labels and placeholder path | Nothing says where the file must live; UNVERIFIED that any player loads prerolls | misleading |
| HELP-08 | Save policy | No success message; only "Updated {time}" changes | cosmetic |
| HELP-09 | Save shown to every role | Wrong role gets raw "This action requires one of these CivicCast roles: …" | misleading |
| NEW-1 | Subtitle lists "prerolls"; "Preroll enabled" | Prerolls are saved but nothing in the portal plays them (manual ch.15) | misleading |

## Proposed text
What this is for (new, under heading): "Rules for who should be allowed to watch a channel or a recording. Beta.10 does not enforce them on the resident portal's video. Treat this screen as notes, except for the podcast feed and the public-record lock."
Who can use it (new): "Anyone signed in can look. Only a publish operator or support admin can save changes."
Warning banner (new, top of page, honest for now): "These settings do not stop anyone from watching a video on the resident portal. Choosing Authenticated or Invite only does not put a lock in front of the Watch page. To hide a recording, use Remove from portal on the recording's Assets page."
After fix (if enforcement is added): "These rules are applied when residents watch."
Subtitle: "Access rules, public-record locks, prerolls and a log of decisions."
Target ID helper: "The ID of the channel or recording, copied from the Channels or Assets screen. A recording's rule overrides its channel's rule. CivicCast accepts any ID in lowercase letters, numbers, - and _, even one that does not exist, so check your spelling."
Access tier helpers: Public = "Anyone." Authenticated = "Only people with a signed viewer token. In beta.10 this is enforced only for the channel's podcast feed." Invite only = "Only people whose token names the invite group below. Same limit."
Invite group helper: "A short name, lowercase, no spaces, that appears in viewers' tokens. The console cannot create groups or issue tokens."
OIDC provider helper: "The name of an outside single-sign-on service. Leave blank if you do not use one."
Authenticated RSS helper: "Lets the channel's podcast feed be fetched with a viewer token. This is the one access setting beta.10 enforces."
Public-record asset helper: "A public record can never be restricted. Ticking this sets access to Public." Public archive complete: same sentence, with "Use when the archive copy is finished."
Preroll helper: "A short card or clip meant to play before a recording. In beta.10 the resident portal does not play prerolls. Prerolls are never added to archive copies. Leave Skip after seconds blank if viewers must not skip."
Preroll alert: "Preroll {n} needs a Creative ID, an Asset URL, an Accessible label and a Duration. Fill them in or remove the row before saving."
Save: after saving show "Saved." Role refusal: "Only a publish operator or support admin can change these rules. Ask your station administrator."
Decision audit empty: "No decisions yet. In beta.10 this log fills only when someone fetches a podcast feed that is gated."

## Notes for the coder
- Edit `PlaybackPolicyScreen.tsx` (labels use a shared field component near line 300-345 and 463-548).
- Tests that pin strings (verified by grep): `screens/PlaybackPolicyScreen.test.tsx` ("missing required fields", "Playback policy"). "Access gates" and "No playback decisions" are not pinned.
- Code fixes, not text fixes: enforce the policy in the portal player and media route, or relabel the screen as planned rules (HELP-01); a drop-down of real channels and recordings (HELP-03); a viewer-token issue button or removal of the token wording (HELP-02); Save success message and role-based disable (HELP-08/09); a portal preroll player (NEW-1).
- UNVERIFIED in the inventory: whether any device app (`apps/app-platform-shells`, `apps/ott-native`, `apps/ctv-reference`) enforces `entitlement_required` or plays prerolls; how residents would get a viewer token; the storage location on a normal install.
