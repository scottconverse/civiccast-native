# Cable Commissioning  (nav id: commissioning, section: Setup)
Source files (under `civiccast\apps\portal-operator\src\`): `screens\CommissioningWizardScreen.tsx` (screen + FirstRunChecksStep, ChannelSetupStep, OutputProofStep, CommissioningReportStep), `components\ConfirmDialog.tsx`, `screens\SystemHealthScreen.tsx:1226-1313` (SupportBundlePanel, embedded in Screen 11), `screens\CableVerificationCard.tsx` (NOT on this screen; see below), `api\client.ts` (`getCommissioningState` 950, `runCommissioningOutputProof` 973, `buildCommissioningReport` 982, `listChannelProfiles` 1483, `listHeadendProfiles` 2563).
Backend: `civiccast\installer\commissioning_router.py` (`/api/staff/cable/commissioning/*`), `civiccast\installer\commissioning.py`, `civiccast\installer\station_state.py:470-560` (state saved in station-state.json), `civiccast\egress\headend.py`, `civiccast\egress\compliance.py`, `civiccast\cable\router.py:164`, `civiccast\installer\router.py:911-957` (support bundle).
Who can open it: sidebar shows it to `setup_admin` and `support_admin` (`Sidebar.tsx:107-111`). The screen repeats the check (`READ_ROLES`, line 40); others see "Cable Commissioning requires the setup admin or support admin role. Ask your station admin for access." (562-563). Only `setup_admin` can press anything (`canWrite`, line 41); support_admin sees everything disabled.

## What it is for
A four-step wizard for a station that sends a channel to a cable company's headend: (8) check this computer, (9) record which channel/output format/headend/destination is being used, (10) push a test pattern at the channel's configured output for a set time while an analyzer (TSDuck) checks it, (11) produce a report. Progress is stored on the station so it resumes after leaving.

## What the user sees
H1 "Cable Commissioning" with the line "Screens 8-11 of the commissioning wizard (S3): first-run cable checks, channel output setup, output proof, and the final report. Progress is saved after each step, so leaving and returning resumes where you left off." (577-581). Then four cards titled "Screen 8: First-run cable checks", "Screen 9: Channel output setup", "Screen 10: Output proof", "Screen 11: Commissioning report" (`StepCard`, 108-110). Cards 9-11 show a grey locked sentence until the step before is done.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Screen 8: Station name (aria "Station name for commissioning report") (134) | Name stored with the check report | sent in checks request | `setup_admin` | Optional |
| Run cable checks (151) | Runs 11 checks and saves the result | `POST /api/staff/cable/commissioning/checks` with `deployment_profile: 'peg-cable'` hard-coded (126) | UI: `setup_admin`; server also allows `support_admin` (router.py:74) | Busy "Running checks…". Result banner "Ready to continue." or "Not ready -- fix the failing checks below."; list of rows with status in capitals (PASS/FAIL/WARNING/SKIPPED), detail, "Next step:" |
| Screen 9: Channel (222) | Choose a channel ("Choose a channel…"); fills channel name from its display name | `GET /api/staff/cable/channels` (any signed-in role) | | |
| Output format (244) | 720p30, 1080i60, 1080p30 (default), SD480i60 | saved in channel setup | | Raw codes, no explanation |
| Headend profile (261) | "Choose a headend profile…" then: Generic CBR SPTS over UDP; Comcast MTD - SD (MPEG-2, CableLabs SD numbers); Comcast MTD - HD (H.264); TelVue HyperCaster - IP transport stream input; Harmonic Spectrum - transport stream ingest; Leightronix UltraNEXUS - file handoff; Local rehearsal (web preview, HLS) (egress\headend.py) | `GET /api/staff/egress/headend-profiles` | | |
| Destination address:port (280) | Free text, placeholder "192.168.1.100:5000" | saved | | Not reachability-tested (port check is optional and not called, commissioning.py:`port_reachable` never passed by the router) |
| SDI device (optional) (292) | Free text device name | saved | | Server refuses it unless the DeckLink/BMD SDK is present: "An SDI device was selected but this station's GStreamer engine does not have the DeckLink/BMD Desktop Video SDK ready (...)" (commissioning.py:455) |
| Fill policy (303) | Slate / Loop / Silence | saved | | |
| Checkbox "CEA-708 caption passthrough (verified in the output proof below when enabled)" (323) | Asks the proof step to also run a caption embed/decode-back test | saved | | |
| Save and continue (335) | Validates and saves Screen 9 choices | `POST .../channel-setup` | `setup_admin` | Disabled until channel, headend profile and destination filled. Success "Channel setup saved."; error 422 text e.g. "Unknown headend profile 'x'. Choose one from the headend profile catalog." |
| Screen 10: Test pattern (383) | "Bars + tone", "Live", "Slate" | | | "Live" is treated like bars by the generator (commissioning.py:484: only "slate" differs) |
| Duration (seconds) (397) | 1-1800, default 60; non-numeric falls back to 60 | | | |
| Start proof run (415) -> dialog "Start the output proof run?" with button "Start proof run" / "Cancel" | Runs a test pattern to the channel's UDP output and a TSDuck probe at the same time, then (if ticked) the caption check | `POST .../output-proof` | `setup_admin` | Dialog body: "This pushes a bars + tone test pattern to channel <id> through the live GStreamer engine for <n> seconds, replacing the channel's real output for the duration. The call blocks until it finishes." (421). 404 "No egress config for channel '<id>'." / 503 "Durable storage is not ready; the output proof needs the channel's egress config." |
| Screen 11: Station name (471) + Generate report (488) | Builds and saves the final report | `POST .../report?station_name=` | `setup_admin` | 409 "Run the first-run checks, channel setup, and output proof steps before the report." Shows "Ready for broadcast" or "Commissioning incomplete", Channel / Headend profile / Output format, "Next steps" list |
| Support bundle (panel inside Screen 11): Short note (1257), Create support bundle (1275), Download support bundle (1297) | Makes a redacted diagnostic JSON and downloads it as `<bundle id>.json`; shows path, "SHA-256 ..." and next step | `POST /api/staff/installer/support-bundle`, `GET .../support-bundle/{id}/download` | server: `support_admin` only (router.py:911,937) | UI enables it for `setup_admin` (`canCreate={canWrite}`); see findings |

### Cable verification card (`CableVerificationCard.tsx`) — rendered on Channels, not here
Section "Cable verification" with pill "Ready" / "Not set up" / "Checking…". Not installed text: "Turn this on and CivicCast downloads the free TSDuck toolkit for you — no separate setup, no admin rights — so it can run a bounded transport check on your cable channels before provider validation." Installed text: "CivicCast can run a bounded TSDuck transport check before provider validation." Button "Enable cable verification" (busy: "Downloading TSDuck… this can take a few minutes") -> `POST /api/staff/installer/tsduck/install` (`setup_admin` or `support_admin`; Windows: pinned portable zip with SHA-256 check, no admin; other OS: returns a command to run). Disabled text: "Enabling cable verification requires setup admin or support admin." Rendered at `ChannelOpsScreen.tsx:2045`. Not rendered anywhere in this wizard.

## States
- Loading: "Loading…"; "Loading commissioning progress…". Identity error: AuthRequiredState text (see station-profile inventory). Wrong role: blue note above. Progress load error: "Could not load commissioning progress." or server text.
- Locked texts: Screen 9 "Complete the first-run cable checks first (all pass or Continue-anyway on warnings)."; Screen 10 "Save the channel output setup first."; Screen 11 "Run the output proof first."
- Failure texts: "Could not run the cable checks.", "Could not save the channel setup.", "The output proof failed to start.", "Could not build the commissioning report."
- Output proof result: banner "Verdict: pass|partial|fail", detail "TSDuck verdict: ...", blockers (yellow lines), and lines starting "(boundary) " such as "The output proof drives a bounded ffmpeg SMPTE-bars+tone generator ... it is a headend connectivity/format proof, not a physical SDI/DeckLink hardware proof (that remains rung 3, MASTER §13.2, gated on real DeckLink hardware)."
- If the channel has no UDP output: the proof fails with "channel '<id>' has no udp-ts sink to verify — apply a headend delivery profile first" (compliance.py:548).

## The 11 Screen 8 checks (commissioning.py:196-400)
Operating system (warning if not Windows/Linux/macOS); Disk space (FAIL under 100 GB free); GStreamer playout engine (FAIL if missing/base not OK); DeckLink / BMD Desktop Video SDK (warning; skipped unless profile peg-cable, which this screen always sends); TSDuck (warning if not installed, optional); Database (FAIL unless durable storage ready: "Open Setup and prepare durable storage before commissioning."); Event bus (in-process) (warning); Backup destination (warning: "Configure a backup destination in the installer."); Timezone (warning if UTC: "Set the station's real local timezone in Station Profile."); Release integrity (always skipped); CasparCG co-process (skipped or warning). Only FAIL rows block (`ready = no fail`). Screen 9 unlocks from the saved `first_run_checks.ready` flag.

## Typical task flows
1. Run cable checks -> fix any FAIL -> Save channel output setup -> Start proof run (confirm) -> wait the full duration -> Generate report -> optional support bundle.
2. Return later: state is reloaded from the station (`GET .../commissioning/state`), steps already done stay unlocked. Re-running a step overwrites its saved result.

## Statuses and words on this screen
Check statuses: pass, fail, warning, skipped (shown raw, upper-case). Verdicts: pass, partial, fail (shown raw). Report: "Ready for broadcast" / "Commissioning incomplete". Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`civiccast` CLI also writes the same report (`cli.py:655`). Station-state key `commissioning` in `station-state.json`. Channels screen applies headend profiles to the real egress config. TSDuck managed dir (`managed_tsduck_dir`).

## Help-text findings
- [HELP-01] CommissioningWizardScreen.tsx:218 — "Complete the first-run cable checks first (all pass or Continue-anyway on warnings)." — there is no "Continue anyway" button; the step unlocks automatically when no check says FAIL — fix: "Run the cable checks. This step opens when no check fails (warnings are allowed)."
- [HELP-02] CommissioningWizardScreen.tsx:126 — "Run cable checks" always sends profile `peg-cable`, so even a public-meetings station gets "DeckLink / BMD Desktop Video SDK" and cable wording — and nothing on screen says this wizard is only for stations that feed a cable headend; the sidebar entry is visible to every setup_admin — fix: add an opening paragraph "Only needed if this station sends a channel to a cable company."
- [HELP-03] CommissioningWizardScreen.tsx:259-276 and 277-288 — Screen 9 looks like it configures the channel (headend profile, destination, format, fill policy), but it only saves the choices to the station record; nothing outside the CLI report reads `channel_setup` (grep of `civiccast\**\*.py`), and the proof sends to the channel's existing UDP output set on the Channels screen — fix: say "This records your choices for the report. Apply the headend profile on the Channels screen first, or the proof will fail with 'no udp-ts sink'."
- [HELP-04] CommissioningWizardScreen.tsx:375-376 and 421 — "through the GStreamer engine" / "through the live GStreamer engine ... replacing the channel's real output" — code drives an ffmpeg test-pattern generator straight to the UDP address (commissioning.py:484), it does not replace on-air output but sends a second stream to the same address; the dialog's warning is still right to scare on-air users, but it names the wrong component and doesn't say "do not run while the channel is on air" — fix: "Sends a test signal to the cable-headend address for N seconds. Do not run this while the channel is live."
- [HELP-05] CommissioningWizardScreen.tsx:578 — "Screens 8-11 of the commissioning wizard (S3)" — "Screens 1-7" do not exist on this page, "S3" is an internal spec tag; the step cards are titled "Screen 8..11" — fix: number them Step 1-4.
- [HELP-06] SystemHealthScreen.tsx:1279 — "Support bundles require support admin." appears on this screen to a signed-in support_admin (because `canCreate` is `setup_admin`), while a setup_admin-only token is allowed to click and gets 403 from the server (router.py:911). The single local admin (scope `admin` = all roles) works — fix: pass `canCreate` from the real server rule.
- [HELP-07] CommissioningWizardScreen.tsx:171-176 and 310-312 — Output format codes (720p30, 1080i60...) and Fill policy "Slate / Loop / Silence" have no explanation (what a slate is, what fill policy covers); "SDI device (optional)" has no example — fix: one help line each.
- [HELP-08] CommissioningWizardScreen.tsx:389-391 — Test pattern "Live" is offered but behaves exactly like bars + tone in code; fix: remove or implement.
- [HELP-09] CommissioningWizardScreen.tsx:81, 435 — check statuses and the verdict show raw "FAIL / WARNING / SKIPPED / partial" instead of the five standard readiness phrases from `status-language.ts` — fix: route through `readinessLabel`.
- [HELP-10] Output proof messages end with "(boundary) The output proof drives a bounded ffmpeg SMPTE-bars+tone generator ... (that remains rung 3, MASTER §13.2, gated on real DeckLink hardware)" — internal planning vocabulary shown to the operator — fix: "This test checks the network signal only, not SDI hardware."
- [HELP-11] The whole screen never says what passing means (e.g. "Ready for broadcast" has no definition; per code it also requires the proof to have no blockers, so a "partial" verdict can never read as ready, commissioning.py:713) — fix: define in a sentence.

## Screenshot plan
1. Setup_admin, fresh station: Screen 8 enabled, 9-11 showing locked messages.
2. After Run cable checks with a mix of PASS/WARNING/FAIL rows and the "Not ready" banner.
3. Screen 9 filled in (channel dropdown open to show options; headend profile list open).
4. The "Start the output proof run?" dialog.
5. Proof result: pass, and a fail with blocker text (use a channel without a UDP sink).
6. Screen 11 report "Commissioning incomplete" with Next steps, plus the Support bundle panel ready state.
7. support_admin view (all disabled) and the Channels screen's Cable verification card.
Setup: a configured station; a safe UDP destination (loopback) and a channel NOT on air for the proof; do not run during a live meeting.

## UNVERIFIED / open questions
- UNVERIFIED: that nothing consumes saved `channel_setup` (searched `civiccast\**\*.py` only; non-Python launchers not searched).
- UNVERIFIED: what an operator sees on a plain-Windows station if the test-pattern step starts while the channel is genuinely on air (code shows no on-air guard in `run_output_proof` or the router).
- UNVERIFIED: whether `listChannelProfiles` returns only the three seed channels or also any channels the station added (`default_channel_profiles()`+`resolve_live_outputs`).
- UNVERIFIED: browser/proxy behavior for the output-proof call, which can block up to 1800 s (the client sets no timeout for it, client.ts:973-980; intermediaries not checked).
