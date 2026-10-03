# Alerts & monitoring (nav id: alerts)

Sidebar: System Health > **Alerts**; page H1 "Alerts & monitoring"; small label "Operations". Manual authority: `docs/manual/src/17-something-wrong.md` section "Watch for alerts (Alerts)" (`#watch-for-alerts-alerts`), including "What happens in beta.10 when no destination is wired" (`#what-happens-in-beta.10-when-no-destination-is-wired`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/AlertsScreen.tsx` (785 lines), `alerts-format.ts` (condition names, severity colours), `status-language.ts`. Server: `civiccast/alerting/router.py`, `models.py`, `evaluator.py`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Operations"; "Alerts & monitoring"; "See what the watch box has flagged, tune which problems raise an alert, and choose where alerts are sent." | header | AlertsScreen.tsx:773, 775, 777 |
| "Alerts"; buttons "Active" / "Resolved"; "Loading alerts..."; "Alerts could not load."; "Could not acknowledge the alert." | alert list | 148, 161, 168, 173, 178 |
| "No active alerts. Everything the watch box monitors is healthy." / "No resolved alerts in the recent history." | empty states | 184-185 |
| Row: title from `CONDITION_LABEL`, severity pill (CRITICAL / WARNING / INFO), "seen N×", "first seen <time> · last seen <time>", "Acknowledged by <name> on <date>"; buttons "Acknowledge" / "Acknowledging..." | alert row | 86-118; alerts-format.ts:7-38 |
| "Alert rules"; "Decide which problems raise an alert, how loud they are, and how often CivicCast re-notifies you while the problem persists."; "Loading rules..."; "Alert rules could not load."; "Could not save the rule." | rules section | 317, 319, 328, 333, 338 |
| Rule card: grey tag with the rule id; "Enabled"; "Severity"; "Re-alert after (minutes)"; "Notify on resolve"; "Save" | rule card | 239, 245, 248, 261, 272, 285 |
| "Managing alert rules requires the setup admin or support admin role. Active alerts remain visible to you above." (and "...alert destinations...") | access note | 33-34, 323, 709 |
| "Where alerts go"; "Email, text-message, or webhook destinations that receive alerts. Connection secrets are stored on the station and never shown back; the destination address is shown in full."; "Add destination" / "Close" | destinations header | 690-694, 704 |
| Form: "Type" (Email / Text message (SMS) / Webhook); "Name" (ph "Example: Station manager email"); "Where to send (email, phone, or webhook URL)" (ph "Example: ops@city.gov or https://hooks.example/alerts"); "Quiet hours start (UTC, HH:MM)" / "end" (ph 22:00 / 07:00); "Use 24-hour HH:MM, e.g. 22:00 (or leave blank)."; "Enabled"; "Connection secret (optional — never shown again after saving)"; "Add secret field"; "Remove"; "Create destination" / "Save changes" | destination form | 424, 437, 441, 447, 451, 457, 471, 467, 481, 487, 490, 503, 533, 523 |
| Destination card: kind pill, "disabled", last delivery pill Sent / Failed / Undeliverable / Suppressed; "Edit" / "Close"; "Delete" / "Confirm delete?" / "Removing..." | destination card | 587-608, 629 |
| "No alert destinations yet. Add one so the station can reach you when something needs attention."; "Loading destinations..."; "Destinations could not load."; "The destination change could not be saved." | states | 738, 727, 733 |

## What the screen really does
It lists problems the station has flagged (Active, refreshed every 10 seconds, or Resolved), lets you Acknowledge one ("I have seen this"; it does not fix or close the alert), shows one rule card for each of the 14 alert kinds that come with a rule, and lists notification destinations (email, text message, webhook) you can create, edit and delete. **In beta.10 no alert is sent anywhere.** A new install ships every rule with no destinations; the rule editor has no way to choose destinations; creating a destination does not attach it to a rule. When an alert fires with no live destination the station only writes a "suppressed" delivery note that no screen shows. The alert does still appear on this screen and in the red and yellow counts on Readiness. Some alert kinds ("Automatic self-check did not pass", "eas source unavailable", "asrun outbox degraded", "caption tier degraded") have no rule at all.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | "choose where alerts are sent" (777); "Where alerts go ... receive alerts" (692); "Add one so the station can reach you" (738) | Empty destination list on every rule (evaluator.py:156-160); rule editor never sends `channel_ids` (router.py:232); creating a destination attaches it to nothing; an operator can follow the page and never receive an alert | blocks work (most serious finding on this screen) |
| HELP-02 | "requires the setup admin or support admin role" (34, 765) | Server accepts changes from `setup_admin` only (router.py:284, 378, 403, 430); a Support admin sees the editors and gets 403 on Save | misleading |
| HELP-03 | "Active alerts remain visible to you above." (34) | False for Records clerk and Publish operator: the server refuses them (router.py:453) although the nav shows the screen | misleading |
| HELP-04 | "watch box" (184, 777) | Undefined jargon; it means the station's own monitor | misleading |
| HELP-05 | "Quiet hours ... (UTC, HH:MM)" (457, 471) | Local time is not shown; nothing says critical alerts ignore quiet hours (models.py:166) | misleading |
| HELP-06 | Titles for 15 conditions (alerts-format.ts:15-38) | Nine server conditions have no label and show as raw text; they also have no rule card, so they cannot be tuned here | misleading |
| HELP-07 | "the destination address is shown in full" (693) | Contradicts the API field `target_redacted` and its doc "never raw PII" (models.py:151-155); which is true is UNVERIFIED | misleading |
| HELP-08 | "Re-alert after (minutes)", "Notify on resolve" (261, 272) | Not explained; what 0 means is UNVERIFIED; the grey rule-id tag is internal | cosmetic |
| HELP-09 | Delete: "Confirm delete?" (630) | Armed by one click, stays armed with no cancel or timeout; other screens use `ConfirmDialog` | misleading (data loss) |
| HELP-10 | No "Send test alert" | You cannot prove a destination works; only the Readiness self-check "Alert delivery ready" is related | misleading |
| HELP-11 | Small label "Operations" (773) | Sidebar section is "System Health" | cosmetic |
| NEW-1 | "Acknowledge" (118) | Success is silent apart from the new "Acknowledged by" line | cosmetic |

## Proposed text
Honest text for now, then "after fix".
**Header:** H1 "Alerts"; label "System Health". Intro: "What this is for: see the problems CivicCast has flagged, mark them as seen, and tune how serious each kind is. Who can use this: Setup admin, Support admin and Meeting operator can read the list; only Setup admin can change rules and destinations. **In this version CivicCast does not send email, text or webhook messages unless your IT person has attached a destination to a rule.** Check this page and Readiness before every meeting and at the start of every shift."
After fix: "Choose where alerts are sent" works from each rule card; remove the warning.
**Empty text:** "No active alerts. Nothing the station monitors is reporting a problem right now."
**Access notes:** "Rules can be changed by the Setup admin only. You can look but not change." For roles that cannot read: "Your role cannot see alerts. Setup admin, Support admin and Meeting operator can."
**Destinations intro (now):** "Destinations are the email addresses, phone numbers and web addresses that alerts are meant to reach. Adding one here does not attach it to a rule, so nothing is sent to it yet. Ask your IT person to attach it to the rules you want. The address you type is stored as typed; secrets are stored on the station and never shown again." (Replace the "shown in full" claim until HELP-07 is checked.) After fix: each rule card lists destinations with tick boxes, and a **Send test alert** button on each destination.
**Quiet hours:** "Quiet hours use UTC (a world-standard clock), not local time. They hold back Warning and Info alerts. Critical alerts are always sent." After fix: show the local-time equivalent.
**Rule fields:** "Re-alert after (minutes): how long CivicCast waits before it notifies you again while the problem continues." "Notify on resolve: also notify when the problem goes away."
**Delete:** open a `ConfirmDialog`: "Delete the destination '<name>'? Alerts will no longer be sent to it. This cannot be undone." Buttons "Delete destination", "Cancel".
**Acknowledge help:** "Acknowledge means 'I have seen this'. It does not fix the problem. The alert closes by itself when the problem goes away."
**Missing condition labels (derive from the condition code; confirm each meaning with its owner before shipping):** remote-contribution-coprocess-down "Remote guest helper is down"; remote-contribution-turn-unreachable "Remote guest relay is unreachable"; remote-contribution-guest-drop "A remote guest dropped"; eas-source-unavailable "Emergency alert feed is unreachable"; scheduled-recording-failure "A scheduled recording failed"; scheduled-recording-dropout "A scheduled recording had a gap"; asrun-outbox-degraded "On-air log delivery is behind"; channel-automation-failure "Channel automation failed"; caption-tier-degraded "Captions are running in a reduced mode".
**Eyebrow:** replace "Operations" with "System Health".

## Notes for the coder
- Files: `AlertsScreen.tsx` (text at 33-34, 184-185, 690-694, 738, 777; delete button 612-630), `alerts-format.ts` (`CONDITION_LABEL`), `civiccast/alerting/router.py` (rule write already accepts `channel_ids` at line 232), `models.py` (conditions 42-110).
- Pins: `AlertsScreen.test.tsx` pins "Create destination", "Confirm delete?" and a test named "requires two clicks to delete" (line 161); no test pins the intro, the access notes or "watch box". `tests/test_user_manual_render.py` contains the word "Operations" for the manual, not this screen. Converting Delete to `ConfirmDialog` needs that test updated.
- Code fix needed, not text: destination picker on the rule card (HELP-01); give the 9 unlabeled conditions rules and labels (HELP-06); Setup-admin-only note and server-aligned role gates (HELP-02, HELP-03: hide the nav entry for Records clerk and Publish operator or show a note); Send test alert (HELP-10); UTC to local display (HELP-05); verify what `target_redacted` returns (HELP-07).
