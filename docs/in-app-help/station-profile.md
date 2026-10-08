> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Station Profile (nav id: station-profile)

Sidebar: Setup > **Station Profile**. Manual authority: `docs/manual/src/22-configuration.md` section "Set the Station Profile" (`#configuration-profile`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/StationProfileScreen.tsx` (851 lines: StationIdentityPanel, StationBoxProfilePanel, SecurityPanel, RegeneratedKitPanel), `components/AuthRequiredState.tsx`, `screens/manual-link.ts`. Server text from `civiccast/installer/service.py:1028-1034` (session messages) and `civiccast/platform/station_box_profile.py` (readiness rows). Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Station Profile"; "The station's identity (name, timezone, storage roots) and its computed cable/PEG appliance-readiness report -- separate concerns, per S1: identity is what you edit, readiness is what the box actually detects." | H1 and intro | StationProfileScreen.tsx:837, 839-841 |
| "Station Profile requires the setup admin, meeting operator, or support admin role. Ask your station admin for access." | role gate | 827-828 |
| "Loading…"; "Loading station identity…"; "Probing station hardware and playout-engine readiness…" | loading | 811-812, 225, 459 |
| "No station identity yet -- complete First Setup to create the station profile before editing it here."; "Could not load the station identity."; "No station identity is available yet."; "Could not load the station box profile."; "No station box profile is available yet." | empty and error | 235-236, 240, 245, 464, 468 |
| "Station identity"; "read-only" | card heading and tag | 263, 266 |
| Fields "Station name", "Timezone (IANA name, or "local")", "Default channel id", "Public base URL (optional)" (placeholders America/New_York, https://watch.example.gov) | form | 278, 289, 301, 312 |
| "Media library", "Recordings", "Backups"; button "Copy path" / "Copied" | storage roots | 338, 350, 362, 100 |
| "These are the Windows service account's own paths, not your personal C:\Users\... folders — that is why browsing to them yourself may not work. You do not need file access to find a recording: use Assets instead. ... Read more in the manual. An env-var override (CIVICCAST_STATION_TZ, ...) always wins over what is saved here — this form shows the value currently in effect." | storage note | 374-387 (manual link 381) |
| "Show live captions on air"; "Off when the station is installed in this beta: with live captions on, the picture can freeze for 25–30 seconds and then catch up in a burst every minute or two, and rarely a channel restarts itself. ... Captions on recordings you publish are produced separately and are not affected by this setting."; "More about live captions in the manual" | live-captions switch | 409, 412-420, 425 |
| "Save" / "Saving…" (aria "Save station profile"); "Station profile saved."; "Could not save the station profile." | save | 441, 435, 274, 272 |
| "Station box profile (S1)"; CPU, RAM, "Recommended tier", "Playout engine", "AI summary default"; "Cable-grade OS: <server text>" (e.g. "Single-Windows-PC certification for 24/7 cable is pending the soak result — see MASTER §13.1."); "PEG readiness"; badge GREEN / YELLOW / RED | box card | 478, 483-497, 508, 513, 112-121 |
| "Security"; "Sessions"; "A routine sign-in never signs out other already-open browsers or devices, so a lost or stolen laptop's session otherwise stays signed in indefinitely. Use this to end every OTHER operator-console session right now -- this browser stays signed in." | security card | 668, 678, 681-683 |
| "Sign out other sessions"; "This immediately signs out every other browser and device signed in as this admin."; "Confirm — sign out other sessions"; "Could not sign out other sessions. Try again." | sessions | 700, 706, 717, 690 |
| "Recovery kit"; "If the recovery kit from first-run setup was lost, never saved, or you just want a fresh set, mint a new one now. This requires being signed in with the current admin password -- it is not a way back in if you are locked out." | kit box | 733, 735-738 |
| "Regenerate recovery kit"; "This permanently invalidates every existing recovery code and replaces them with 8 new ones."; "Confirm — regenerate kit"; "Could not regenerate the recovery kit. Try again." | regenerate | 756, 762-763, 776, 746 |
| "New recovery kit ready"; "This is the only time these 8 codes are shown. Every code from the previous kit stopped working the moment this kit was created. Save or print now."; "Print kit", "Save kit", "I have saved or printed the new recovery codes and stored them away from this computer.", "Use Print kit or Save kit first.", "Done" / "Recording confirmation…" | new kit | 582-585, 606, 614, 625, 628, 641 |
| "Sessions and recovery-kit actions require the setup admin role." | read-only roles | 792 |
| "Could not verify your staff identity (...). Sign in again from the CivicCast installer handoff ..." | identity failure | 819 (text: AuthRequiredState.tsx:8-10) |

## What the screen really does
It shows and edits the station's name, time zone, default channel, public web address, three folder paths and the live-captions switch, in one Save. It also reports what this computer has (CPU, memory, playout engine, clock, SDI card, backup, AI memory). Two Setup-admin actions sit in the Security card: end every other signed-in browser, and replace the 8 recovery codes (old codes stop working at once). The station name shows in the console and on the community-board graphic. The time zone `local` means UTC in the running service. The three folder fields and the public web address are stored but nothing uses them. Live captions default to off in beta.10.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | Folder fields are editable with Save and "this form shows the value currently in effect" (339-387) | Nothing reads the saved paths to choose where files go; editing does not move anything (station_state.py:385-399; manual) | blocks work (a clerk will think files moved) |
| HELP-02 | "Cable-grade OS: ... see MASTER §13.1." (508) | Internal document reference; cable claim shown to every station although the row says "Not required" for public meetings | cosmetic |
| HELP-03 | "Station box profile (S1)", "per S1", "PEG readiness", "Recommended tier" (478, 839-841, 513) | Internal spec names; PEG never defined | cosmetic |
| HELP-04 | "Timezone (IANA name, or "local")", "Default channel id" (289, 301) | No list of valid values; non-technical users do not know IANA names | misleading |
| HELP-05 | Live-captions text opens with failure modes (412-420) | Honest but alarming; the current state (off) is not stated first | cosmetic |
| HELP-06 | "This requires being signed in with the current admin password" (737) | The server needs only a Setup admin session; and nothing warns that leaving the page loses the new codes (the first-run kit survives reloads, this one does not) | misleading |
| HELP-07 | "Sign out other sessions" (700) | Returns 401 "Invalid staff bearer token." if you signed in with a staff token rather than the admin password; text never explains | misleading |
| HELP-08 | "Public base URL (optional)" (312) | Stored but unused (RSS and federation use `CIVICCAST_PUBLIC_BASE_URL`; the portal link uses `CIVICCAST_RESIDENT_PORTAL_URL`). The screen sends nothing for a blank box and the server treats that as "leave unchanged", so an existing URL cannot be cleared | misleading |
| HELP-09 | Badge "GREEN / YELLOW / RED" (120, 135) | Every other screen uses the five phrases | cosmetic |
| HELP-10 | AuthRequiredState advice (819) | Retired handoff; real step is Admin sign-in | blocks work |
| NEW-1 | Default timezone `local`, helper says "IANA name, or local" | `local`, blank and unknown names all give UTC; auto-schedule dayparts run in UTC until a real zone is set and the service is restarted (manual) | misleading |
| NEW-2 | "Station name" | The Station Profile does not set the public site's title; channel and app names are set on Channels | cosmetic |

## Proposed text
**Intro:** "What this is for: the station's name, time zone and captions switch, and what this computer can do. Who can use this: Setup admin changes it; Meeting operator and Support admin can read it." Remove "per S1" wording.
**Card names:** "Station identity" stays. Rename "Station box profile (S1)" to "This computer".
**Timezone help:** "Type a time zone name such as America/Denver. Without a valid name CivicCast uses UTC, a world-standard clock, and daypart schedules (for example 'prime time 18:00') run on UTC. Save, then restart the CivicCast service so the schedule compiler reads the new zone." After fix: a dropdown that defaults to the computer's zone.
**Default channel help:** "The channel used for the first-run sample content. Choose public, education or government." After fix: dropdown.
**Public base URL help:** "Saved with the station record but not used in this version. Your resident website address is set by your IT person in the service settings." After fix: used for RSS, federation and preview links, and can be cleared.
**Folder fields:** make them read-only or label them "Where CivicCast keeps files (shown for information; changing these does not move any file)". Replace "this form shows the value currently in effect" with: "Service settings can override these values. To find a recording, use Assets." After fix: fields control the real folders or are removed.
**Live captions:** lead with: "Live captions are off in this version. Turn them on only if your computer has spare capacity. When on, CivicCast writes captions in real time for one channel at a time; on a station with several channels on air the others are paused most of the time. If the picture stutters or a channel restarts, turn this off; the picture and sound always come first. Captions on published recordings are made separately and are not affected." Keep the manual link (`/help#live-captions-what-the-settings-change`).
**Cable-grade line:** show only for cable stations; remove "MASTER §13.1". Text: "Cable-grade operating system: not certified yet for 24/7 cable on a single Windows computer."
**Readiness badge:** show "Ready / Check before meeting / Do not broadcast yet" instead of GREEN/YELLOW/RED.
**Security > Sessions:** "Signs out every other browser and device that is signed in. This browser stays signed in. Works only if you signed in with the admin password; otherwise you will see 'Invalid staff bearer token'." Translate that error to: "This sign-in was made with a staff token, which cannot end other sessions. Sign in with the admin password."
**Security > Recovery kit:** "Make a fresh set of 8 recovery codes. The old codes stop working at once. You must be signed in. Do not leave this page until you have saved or printed the new codes: they cannot be shown again. A new kit lists the codes only, not the password."
**Footer line:** "Help: Configuring the station, Set the Station Profile" -> `/help#configuration-profile`.

## Notes for the coder
- Files: `StationProfileScreen.tsx` (text and, for dropdowns, Timezone and Default channel fields); server `station_box_profile.py` for the "Cable-grade OS" rationale text.
- Pins: `StationProfileScreen.test.tsx` pins "Sign out other sessions", "Regenerate recovery kit", "Confirm — regenerate kit", "Copy path", the label "Show live captions on air" (regex), "Station profile saved", and the manual links `/help#where-recordings-live` (line 258) and `/help#live-captions-switch` (line 366). Those two anchors do not exist in the new manual; see `help.md`.
- Code fix needed, not text: storage paths wired to real folders or removed (HELP-01); Public base URL read and clearable (HELP-08); time zone validation and a picker; the 401 on Sign out other sessions for token sign-ins (HELP-07).
