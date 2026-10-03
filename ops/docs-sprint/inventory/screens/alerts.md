# Alerts & monitoring  (nav id: alerts, section: System Health)
Source files (under `civiccast/apps/portal-operator/src/`): `screens/AlertsScreen.tsx`, `screens/alerts-format.ts`, `screens/status-language.ts`
(`toneForDeliveryStatus` :192, `stateLabel` :252). Server: `civiccast/alerting/router.py`, `alerting/models.py`, `alerting/evaluator.py`.
Route: `#/alerts`. Nav label `Alerts`; page h1 `Alerts & monitoring` (`AlertsScreen.tsx:775`); eyebrow `Operations` (:773).
Who can open it: everyone signed in (`Sidebar.tsx:178`, no `requiredRoles`). What loads depends on role (see Controls). `kit-pending`: nav locked (not in the Manual exception).

## What it is for
Shows problems the station has flagged (active or resolved), lets an admin tune each alert rule, and lets an admin create "destinations"
(email, text message, webhook) that are supposed to receive alerts. Alerts also feed the red/amber counts on Readiness.

## What the user sees (top to bottom)
1. Header: `Alerts & monitoring`, "See what the watch box has flagged, tune which problems raise an alert, and choose where alerts are sent." (:777).
2. Section `Alerts` (h2, :148): segmented buttons `Active` / `Resolved`; list of alert rows (auto-refreshes every 10 s for Active, :134).
3. Section `Alert rules` (:317) + text "Decide which problems raise an alert, how loud they are, and how often CivicCast re-notifies you while the problem persists." (:319). Admins see one card per rule; others see the access note.
4. Section `Where alerts go` (:690) + text "Email, text-message, or webhook destinations that receive alerts. Connection secrets are stored on the station and never shown back; the destination address is shown in full." (:692-694). Button `Add destination` (admins only).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Active` / `Resolved` | Switches the list | `GET /api/staff/alert-events?state=firing|resolved&limit=200` | server: `support_admin`,`setup_admin`,`meeting_operator` (`alerting/router.py:453`) | UI shows list to all roles; a role outside those three gets the red error `Alerts could not load.` or the server text "This action requires one of these CivicCast roles: ..." |
| `Acknowledge` (Active only; becomes `Acknowledging...`) | Marks one alert as seen by you | `POST /api/staff/alert-events/{id}/ack` | server same three roles (`router.py:470`) | Then shows pill `acknowledged` and "Acknowledged by `<name>` on `<date>`". Invalidates alerts, runtime-safe-to-air and system-health queries. No confirm. Does not resolve the alert |
| rule: `Enabled` checkbox, `Severity` (Critical / Warning / Info), `Re-alert after (minutes)`, `Notify on resolve`, `Save` | Edit one rule | `PUT /api/staff/alert-rules/{rule_id}` body `{enabled,severity,re_alert_after_seconds,notify_on_resolve}` | server **`setup_admin` only** (`router.py:284`); list read allows `setup_admin`,`support_admin` (:266). UI `canManage` = `setup_admin` or `support_admin` (:765-768) | `Save` is disabled until a value changes and minutes >= 0; shows `Saving...`. No success message |
| `Add destination` / `Close` | Opens the create form | - | UI admins | |
| form `Type` (Email / Text message (SMS) / Webhook), `Name` (ph `Example: Station manager email`), `Where to send (email, phone, or webhook URL)` (ph `Example: ops@city.gov or https://hooks.example/alerts`), `Quiet hours start (UTC, HH:MM)` (ph `22:00`), `Quiet hours end (UTC, HH:MM)` (ph `07:00`), `Enabled`, `Connection secret (optional - never shown again after saving)` with `Add secret field` / `Remove` (inputs ph `key (e.g. smtp_password)`, `value`) | Creates `POST /api/staff/alert-channels` (button `Create destination`) or updates `PUT /api/staff/alert-channels/{id}` (`Save changes`) | server **`setup_admin` only** (:378, :403); list read `setup_admin`,`support_admin` (:311) | `Create`/`Save` disabled until Name and Where-to-send are filled and quiet hours are `HH:MM` or empty (inline text "Use 24-hour HH:MM, e.g. 22:00 (or leave blank)."). Secret values go to the station credential store, never returned |
| destination `Edit` / `Close` | Opens edit form | - | UI admins | |
| destination `Delete` -> `Confirm delete?` | Two clicks to delete (no dialog) | `DELETE /api/staff/alert-channels/{id}` | server `setup_admin` | Second click deletes at once; the armed red button stays armed until clicked again (no timeout, no cancel) (:612-630). Shows `Removing...` |

Access note shown to non-admins instead of rules/destinations: "Managing alert rules requires the setup admin or support admin role. Active alerts remain visible to you above." / "...alert destinations..." (:31-36).

## States
| State | Text |
|---|---|
| Loading | `Loading alerts...`, `Loading rules...`, `Loading destinations...` |
| Empty Active | `No active alerts. Everything the watch box monitors is healthy.` (:184) |
| Empty Resolved | `No resolved alerts in the recent history.` |
| No destinations | `No alert destinations yet. Add one so the station can reach you when something needs attention.` (:738) |
| Errors | `Alerts could not load.`, `Could not acknowledge the alert.`, `Alert rules could not load.`, `Could not save the rule.`, `Destinations could not load.`, `The destination change could not be saved.` (each with server detail when present) |
| Storage not ready | server 503 "Durable storage is not ready yet." shown as the error text |
| Not an admin | access note above; rules/destinations are not requested (`enabled: canManage`) |
| Offline | no dedicated state; browser error text |

## Typical task flows
1. See what is wrong: Alerts -> `Active` -> read the title (condition), severity pill, summary, resource, first/last seen -> `Acknowledge`.
2. Add where alerts go: `Add destination` -> Type, Name, address, optional quiet hours and secret -> `Create destination`. **The UI offers no way to attach the destination to any rule** (see HELP-01).
3. Quiet an alert type: find rule -> untick `Enabled` or change `Severity` -> `Save`.

## Statuses and words on this screen
- Severity pill: `critical` (red), `warning` (amber), `info` (blue) (`alerts-format.ts:7-11`), shown in capitals.
- State pill: `Firing`/`Resolved` via `stateLabel`; `seen N×` when an alert repeated; `acknowledged`.
- Destination pill: kind (`email`/`sms`/`webhook`), `disabled`, and last delivery: `Sent` (green), `Failed`, `Undeliverable` (= `dead_letter`), `Suppressed` (amber). Backend values: sent, failed, suppressed, dead_letter (`alerting/models.py:113`).
- Condition titles (`CONDITION_LABEL`, `alerts-format.ts:15-38`): Channel off air, Encoder stopped, Server crashed, Data format out of date, Relay blocked, Cable compliance check failed, Missing media file, Save to database failed, Live takeover stuck over 2 hours, AI engine is down, Disk space low, Computer clock out of sync, Database unreachable, CivicCast service is down, Automatic self-check did not pass. Any other condition is shown as its code with dashes turned into spaces, e.g. "eas source unavailable".
- Server-defined conditions with no label (`alerting/models.py:42-110`): remote-contribution-coprocess-down, remote-contribution-turn-unreachable, remote-contribution-guest-drop, eas-source-unavailable, scheduled-recording-failure, scheduled-recording-dropout, asrun-outbox-degraded, channel-automation-failure, caption-tier-degraded.

## Related settings / env / CLI / API
`/api/staff/alert-events`, `/api/staff/alert-rules`, `/api/staff/alert-channels`; credential store (secret handle); default rules are seeded with no destinations (`alerting/evaluator.py:156-160`).

## Help-text findings
- [HELP-01] AlertsScreen.tsx:207-296, :690-694 - the screen says "choose where alerts are sent", but a new install seeds every rule with an empty destination list (`evaluator.py:156-160`), the rule editor never sends `channel_ids` (the API supports it, `router.py:232`), and creating a destination does not attach it to a rule (`router.py:374-389`). With no destination wired, the server only writes a "suppressed" delivery row (`evaluator.py:430-445`) that no screen shows. Result: an operator can follow the page exactly and never receive an alert. This is the most serious finding on this screen. Fix: either wire destinations to rules in the UI (and say so), or state plainly on screen that rules need destinations attached by IT.
- [HELP-02] :31-36 and :765 say `setup admin or support admin` can manage rules/destinations, but the server allows changes only for `setup_admin` (`router.py:284,378,403,430`). A support admin sees the editors, edits, and gets a 403 on `Save`. Fix: reads for both, edits for setup admin only, and say so.
- [HELP-03] :31-36 "Active alerts remain visible to you above." - false for `records_clerk` and `publish_operator` (they are not allowed to read events, `router.py:453`) although the nav shows them the screen. Fix: hide the nav entry for them or show a clear access note.
- [HELP-04] :184 and :777 "watch box" - undefined jargon. Fix: "the station monitor" or say what is watched (channels, disk, database, service, AI engine).
- [HELP-05] :457-483 `Quiet hours ... (UTC, HH:MM)` - a clerk thinks in local time; nothing says critical alerts ignore quiet hours (server comment: "critical alerts always send; warning/info held", `models.py:166`). Fix: show local-time equivalent and the critical exception.
- [HELP-06] `alerts-format.ts:15-38` lacks labels for nine server conditions (list above) so operators will see raw text such as "asrun outbox degraded" or "caption tier degraded". Also those conditions have no rule card (unseeded, `models.py:80-110`), so they cannot be tuned here.
- [HELP-07] :692-694 "the destination address is shown in full" contradicts the API field name `target_redacted` and the server doc "Reads return target_redacted ... never raw PII" (`models.py:151-155`). UNVERIFIED which is true; check what the list endpoint returns for a saved email.
- [HELP-08] :261 `Re-alert after (minutes)` - no explanation of what 0 means, nor of "dedupe". `Notify on resolve` is not explained. The rule card shows `rule_id` (e.g. `off-air`-style code) as a grey tag.
- [HELP-09] :612-630 Delete is armed by one click and stays armed with no cancel/timeout, unlike every other destructive action (shared `ConfirmDialog`). Fix: use ConfirmDialog.
- [HELP-10] No `Send test alert` button, so there is no way to prove a destination works; the only related text is the self-check item `Alert delivery ready` on Readiness (`SystemHealthScreen.tsx:405`).
- [HELP-11] Eyebrow `Operations` (:773) does not match the sidebar section `System Health`.

## Screenshot plan
1. Active alerts with a critical alert and an acknowledged alert.
2. Empty Active state (healthy station).
3. Rule cards (admin).
4. Add-destination form with a validation message on quiet hours; a saved destination with a `Sent` or `Suppressed` pill.
5. Non-admin view showing the two access notes (needs a `meeting_operator`-only token).
Setup: raise an alert (e.g. stop a channel feed) or seed events; a CLI-issued role-limited token for step 5.

## UNVERIFIED / open questions
- UNVERIFIED: that no other code attaches new destinations to rules automatically (searched `channel_ids` in `alerting/` and the installer; found none).
- UNVERIFIED: whether `target_redacted` is stored/returned in full (HELP-07).
- UNVERIFIED: how `Re-alert after = 0` and `dedupe_window_seconds` behave (`evaluator.py` `_should_send` not read).
- UNVERIFIED: whether Resolved list is capped by time (server default `limit=200`, no date filter in UI).
