# Emergency Alerts (nav id: eas)

Sidebar: System Health > **Emergency Alerts**. Manual authority: `docs/manual/src/17-something-wrong.md` section "Understand emergency alerts" (`#understand-emergency-alerts-emergency-alerts`) and `26-integrations.md`.

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/EasScreen.tsx` (457 lines), `components/EasPostureBanner.tsx`, `components/AuthRequiredState.tsx`, `ConfirmDialog.tsx`. Server: `civiccast/eas/router.py`, `service.py`, `workers.py`, `civiccast/app.py:526-585, 1721-1750`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Emergency Alerts"; "Ingest and display CAP/IPAWS, NWS, and AMBER public-safety alerts on your channels." | H1 and intro | EasScreen.tsx:360, 362 |
| "Public-safety display — not an EAS device"; "CivicCast ingests and displays public-safety alerts (CAP/IPAWS, NWS, and AMBER) as on-channel information — a crawl, an overlay, or an operator-confirmed slate. It is not an EAS device: it does not relay the FCC Part 11 EAS signal, generates no SAME headers, and never automatically pre-empts programming. The mandatory Part 11 relay remains the cable operator's certified headend equipment." | permanent banner | EasPostureBanner.tsx:24-31 |
| "The Emergency Alerts console requires the setup admin, support admin, or meeting operator role. Ask your station admin for access."; "Loading…"; AuthRequiredState text | gate | EasScreen.tsx:350, 334; AuthRequiredState.tsx:8-10 |
| "Channel" (dropdown of channel ids, default `gov`); "(read-only — displaying alerts requires the meeting operator or setup admin role)" | picker | 372, 295, 402 |
| "Alert sources"; "Loading sources…"; "No alert sources are configured yet. Add an NWS, AMBER, or IPAWS (COG) feed to begin ingesting public-safety alerts."; source line "<name> (<kind> · ≥ <severity>)" with "polling" / "disabled"; "Could not load sources." | sources | 95, 97, 100-101, 118, 408 |
| "Active alerts"; "Loading alerts…"; "No active alerts."; severity badge extreme / severe / moderate / minor / unknown; "Could not load alerts." | active alerts | 218, 220, 223, 72, 414 |
| Buttons "Show crawl on <channel>", "Show overlay"; tick box "Confirm full-screen takeover" with button "Forced slate" (disabled until ticked, tick resets after each use); "Could not display the alert." | alert row | 167, 175, 183, 195, 192, 368 |
| "On-channel now"; "Loading…"; "Nothing is being displayed."; each line "<channel id> <mode>" (crawl, overlay, forced_slate); button "Clear" | on-channel list | 256, 258, 261, 282 |
| Clear dialog: "Take this <mode> down on <channel>?"; "This ends the full-screen public-safety takeover immediately. Residents watching that channel go back to regular programming." / "This removes the public-safety alert from the channel immediately. Residents watching lose it until it is displayed again."; "Clear alert" | confirm | 430-435 |

## What the screen really does
It lists public-safety alerts that CivicCast has pulled in from configured feeds (National Weather Service, IPAWS, AMBER) and lets an operator show one on a channel as a crawl (scrolling line of text), an overlay (a message box over the picture) or a forced slate (a full-screen message that replaces the programme), and take it down again with Clear. As installed in beta.10 nothing is polled: the page says "No alert sources are configured yet", and the screen has no form to add a feed (only an IT person with the Setup admin role can, through the programming interface). Polling starts only if IT sets `CIVICCAST_EAS`; severe alerts then go on every on-air channel as a crawl and extreme alerts as an overlay by themselves only if IT also sets `CIVICCAST_EAS_AUTO_SURFACE`. A forced slate is never automatic. In testing we could not confirm that a crawl, overlay or slate is drawn onto the picture that goes out to cable or the stream: the station records a decision and serves it at `/api/public/cg/emergency-overlay?channel_id=<id>`, and no code was found that draws it into the playout picture. CivicCast is not an EAS device.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | "Add an NWS, AMBER, or IPAWS (COG) feed to begin ingesting" (100) | No form exists; feeds are added through the API by a Setup admin (`PUT /api/staff/eas/sources/{id}`); "COG" and "IPAWS" are undefined | blocks work |
| HELP-02 (corrected by manual) | Banner says only "never automatically pre-empts programming" | Once IT turns on `CIVICCAST_EAS` and `CIVICCAST_EAS_AUTO_SURFACE`, every active severe alert airs by itself on every on-air channel as a crawl and every extreme alert as an overlay; nothing on the page says so. Both settings are off by default (app.py:1723, 1734) | misleading |
| HELP-03 | "on your channels" / "on-channel" (362; banner) | UNVERIFIED that a crawl, overlay or slate reaches cable or the stream; the resident site's emergency box shows a generic placeholder and only when the address ends `?emergency=1` (manual) | blocks work (an operator may promise the city something untested) |
| HELP-04 | Default channel `gov` (295) | Hard-coded guess; the dropdown lists it even if no such channel exists | misleading |
| HELP-05 | Buttons "Show crawl", "Show overlay", "Forced slate" | No success message; crawl, overlay and slate are not explained; the list shows raw `forced_slate` | misleading |
| HELP-06 | Forced slate uses a tick box (183-195) | `Clear` uses `ConfirmDialog`; the tick label does not say it covers the whole picture for residents | misleading |
| HELP-07 | AuthRequiredState advice | Retired handoff; real step is Admin sign-in | blocks work |
| HELP-08 | "polling" (118) | Only means the source is switched on; a failing feed still says polling (it raises an alert "eas source unavailable" that has no rule and notifies nobody) | misleading |
| HELP-09 | H1 `text-lg`, section headings `text-sm` | Different from other System Health screens | cosmetic |
| NEW-1 | Page says nothing about who may display | Display and Clear need Setup admin or Meeting operator; Support admin can read only | cosmetic |

## Proposed text
**Intro:** "What this is for: show public-safety alerts (weather, AMBER, federal alerts) on a channel, and take them down. Who can use this: Setup admin and Meeting operator can show and clear alerts; Support admin can read. **CivicCast is not an Emergency Alert System (EAS) device.** It does not send the national EAS signal. Your cable operator's equipment does that."
**Empty sources (now):** "No alert feeds are set up. In this version feeds are added by your IT person; nothing is polled until they turn it on. Alerts will not appear here until then." After fix: an "Add a feed" form with plain names (National Weather Service, AMBER, federal IPAWS).
**New note under the banner:** "If your IT person has turned on automatic display, every severe alert goes on every channel that is on air as a scrolling line, and every extreme alert as a message box, without anyone pressing a button. Use Clear to take one down. A full-screen takeover is never automatic."
**What the three displays mean:** Crawl "A line of text that scrolls across the screen." Overlay "A message box over the picture." Forced slate "A full-screen message that replaces the programme for everyone watching that channel."
**Tick box:** "I confirm a full-screen takeover. It replaces the picture for everyone watching this channel."
**On-air caveat (until tested):** "CivicCast records which alert is shown on which channel. We have not confirmed that it is drawn on the picture that goes out to cable or the web stream. Test it on your own channel before you rely on it."
**Success text (after fix):** "Showing a crawl on <channel>." appears as a toast.
**polling:** replace with "switched on" / "switched off"; add "A feed that is failing still says switched on. A failing feed raises an alert on the Alerts screen."
**Channel default:** pick the first real channel; "Choose a channel" if none.
**Severity words:** show Extreme, Severe, Moderate, Minor, Unknown (capitalised) and "Full-screen takeover" for `forced_slate`.

## Notes for the coder
- Files: `EasScreen.tsx`, `EasPostureBanner.tsx`, `civiccast/app.py:526-585, 1721-1750`. The unfinished on-air path (`egress/supervisor.py:182, 188` hooks, no caller from an EAS decision) needs an engineer's check before any text promises it.
- Pins: `EasScreen.test.tsx` pins "Show crawl on" and "Forced slate"; no test pins the intro, banner, empty-state text or the Clear dialog.
- Code fix needed, not text: a console form for adding, editing and disabling feeds (`upsertEasSource`, `deleteEasSource`, `createManualEasAlert` exist in `api/client.ts:1792-1813` but no screen calls them); a switch or visible status for `CIVICCAST_EAS` and auto display; confirmation that crawl and overlay reach the output picture; default channel from the channel list.
