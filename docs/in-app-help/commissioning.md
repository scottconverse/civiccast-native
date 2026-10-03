# Cable Commissioning (nav id: commissioning)

Sidebar: Setup > **Cable Commissioning**. Manual authority: `docs/manual/src/22-configuration.md` section "Run Cable Commissioning" (`#configuration-commissioning`). Needed only by a station that sends a channel to a cable company's headend.

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/CommissioningWizardScreen.tsx` (605 lines: FirstRunChecksStep, ChannelSetupStep, OutputProofStep, CommissioningReportStep) and `SystemHealthScreen.tsx:1226-1313` (the Support bundle panel embedded at Screen 11, `CommissioningWizardScreen.tsx:519`). Server text from `civiccast/installer/commissioning.py`, `commissioning_router.py`, `egress/compliance.py`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Cable Commissioning"; "Screens 8-11 of the commissioning wizard (S3): first-run cable checks, channel output setup, output proof, and the final report. Progress is saved after each step, so leaving and returning resumes where you left off." | H1 and intro | CommissioningWizardScreen.tsx:576, 578-580 |
| "Cable Commissioning requires the setup admin or support admin role. Ask your station admin for access."; "Loading…"; "Loading commissioning progress…"; "Could not load commissioning progress." | gate and load states | 562-563, 547, 586, 589 |
| Card titles "Screen 8: First-run cable checks", "Screen 9: Channel output setup", "Screen 10: Output proof", "Screen 11: Commissioning report" | `StepCard` | 108-110 (step 8 title 131, step 9 title 218, step 10 title 370, step 11 title 468) |
| Screen 8: "Station name"; "Run cable checks" / "Running checks…"; "Ready to continue." / "Not ready -- fix the failing checks below."; row "Next step: <text>"; status words PASS, FAIL, WARNING, SKIPPED; "Could not run the cable checks." | step 1 | 134, 151, 158, 84, 81 (status shown upper-case), 154 |
| Screen 9 locked: "Complete the first-run cable checks first (all pass or Continue-anyway on warnings)." | locked card | 218 |
| Screen 9: "Choose a channel…"; "Output format" (720p30, 1080i60, 1080p30, SD480i60); "Headend profile" ("Choose a headend profile…"); "Destination address:port"; "SDI device (optional)"; "Fill policy" (Slate, Loop, Silence); "CEA-708 caption passthrough (verified in the output proof below when enabled)"; "Save and continue"; "Channel setup saved."; "Could not save the channel setup." | step 2 | 234, 243-245, 260-269, 278, 290, 301-312, 323, 335, 326, 325 |
| Screen 10 locked: "Save the channel output setup first."; "Generating test <pattern> on channel <id> through the GStreamer engine, verified with a concurrent TSDuck probe. This call blocks for the full duration." | step 3 | 372, 375-376 |
| "Test pattern" (Bars + tone, Live, Slate); "Duration (seconds)"; "Start proof run" / "Running proof…" | step 3 | 380, 389-391, 395, 415 |
| Dialog "Start the output proof run?" / "This pushes a <pattern> test pattern to channel <id> through the live GStreamer engine for <n> seconds, replacing the channel's real output for the duration. The call blocks until it finishes." / "Start proof run" | confirm | 420-422 |
| "Verdict: pass|partial|fail"; blocker lines; "(boundary) <line>" | proof result | 435-445 |
| "The output proof failed to start." | error | 431 |
| Screen 11 locked: "Run the output proof first."; "Station name"; "Generate report" / "Building report…"; "Ready for broadcast" / "Commissioning incomplete"; "Next steps"; "Could not build the commissioning report." | step 4 | 468, 471, 488, 495, 508, 491 |
| Support bundle panel: "Support bundle"; "Generate a redacted troubleshooting file for tester support."; "Short note"; "Create support bundle"; "Support bundles require support admin."; "Download support bundle" | embedded panel | SystemHealthScreen.tsx:1251, 1253, 1257, 1275, 1279, 1297 |

## What the screen really does
A four-step wizard saved on the station so it resumes. Step 1 runs 11 checks (OS, disk space, GStreamer, DeckLink SDK, TSDuck, database, event bus, backup folder, time zone, release integrity, CasparCG helper); only a FAIL stops you. The screen always sends the `peg-cable` profile, so DeckLink wording appears on every station. Step 2 only records your choices (channel, format, headend profile, destination, SDI device, fill policy, caption test) for the report; it does not configure the channel. Step 3 sends a test pattern (bars and tone) to the channel's existing UDP output for the chosen seconds while TSDuck checks the stream, then optionally a caption test; the call holds the page until it ends and nothing stops it on a channel that is on air. Step 4 builds the report; "Ready for broadcast" needs a proof with no blockers.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | "all pass or Continue-anyway on warnings" (218) | No Continue-anyway button; the step opens by itself when no check says FAIL | misleading |
| HELP-02 | No opening explanation; the sidebar shows this to every Setup admin | Wizard is only for stations that feed a cable headend, and always sends `peg-cable` (126) | misleading |
| HELP-03 | Screen 9 looks like it configures the channel | Choices go only to the station record for the report; apply the headend profile on Channels first, or the proof fails with "has no udp-ts sink" (compliance.py:548) | blocks work |
| HELP-04 | "through the live GStreamer engine ... replacing the channel's real output" (421) | The code drives an ffmpeg test-pattern generator straight to the UDP address and sends a second stream to the same address; no check refuses to run on an on-air channel; the dialog never says "do not run while the channel is live" | misleading (can disturb a live feed) |
| HELP-05 | "Screens 8-11 ... (S3)" and card titles "Screen 8..11" (578, 108) | Screens 1-7 do not exist on this page; "S3" is an internal spec tag | cosmetic |
| HELP-06 | "Support bundles require support admin." (SystemHealthScreen.tsx:1279) | Shown to a signed-in Support admin because `canCreate` follows `setup_admin` (519), while a Setup-admin-only token is allowed to click and gets 403 (router.py:911). The first admin (all roles) works | misleading |
| HELP-07 | Output format codes, "Fill policy", "SDI device (optional)" unexplained (172-176, 310-312) | Jargon | cosmetic |
| HELP-08 | Test pattern "Live" (389-391) | Behaves exactly like bars + tone (commissioning.py:484) | misleading |
| HELP-09 | Raw "PASS / FAIL / WARNING / SKIPPED" and "Verdict: pass / partial / fail" (81, 435) | Not the five readiness phrases | cosmetic |
| HELP-10 | "(boundary) The output proof drives a bounded ffmpeg SMPTE-bars+tone generator ... rung 3, MASTER §13.2 ..." | Internal planning vocabulary | cosmetic |
| HELP-11 | "Ready for broadcast" never defined | Needs a proof with no blockers; a "partial" verdict never reads ready (commissioning.py:713) | misleading |
| NEW-1 | "Destination address:port" | Not tested for reachability (no port check is called) | misleading |
| NEW-2 | "SDI device (optional)" | Server refuses it unless the DeckLink/BMD SDK is present (commissioning.py:455) | misleading |

## Proposed text
**Intro:** "What this is for: a four-step test for a station that sends a channel to a cable company's headend (the cable company's equipment that receives your signal). If your station only serves residents on the web, you do not need it. Who can use this: Setup admin runs the steps; Support admin can read. Progress is saved after each step."
**Step titles:** "Step 1: Check this computer", "Step 2: Record the channel's output settings", "Step 3: Send a test signal", "Step 4: Report".
**Step 1 locked text for Step 2:** "Run the checks in Step 1. This step opens when no check fails. Warnings do not stop you."
**Step 2 intro:** "This records your choices for the report. It does not change the channel. Before Step 3, apply the same headend profile on the Channels screen, or the test will fail with 'has no udp-ts sink'." Field helps: Output format "Picture size and speed your cable company asked for; 1080p30 is the default." Fill policy "What plays between programs: a slate (a still card), a loop of earlier video, or silence." SDI device "Name of a Blackmagic DeckLink card, if you use one. Leave blank if not." Destination "Where the cable company's receiver listens, as address:port, for example 192.168.1.100:5000. CivicCast does not check that it can reach it."
**Step 3 dialog:** title "Send a test signal to the cable headend address?" body "CivicCast will send a bars-and-tone test signal to <address> for <n> seconds and check it with TSDuck (a stream analyser). This sends a second stream to the same address as the channel's real output. Do not run this while the channel is on air. The page waits until it finishes." Confirm "Send test signal". After fix: refuse to run on an on-air channel.
**Test pattern options:** remove "Live" or label it "Same as bars + tone".
**Result words:** "Passed", "Partly passed", "Failed" and "Ready for broadcast" with the line "This means the network signal passed the test and no blockers remain. It is not a test of SDI hardware." Replace "(boundary) ..." with "This test checks the network signal only, not SDI hardware."
**Check words:** use "Passed / Check before meeting / Do not broadcast yet / Not set up yet" via `readinessLabel`.
**Support bundle:** "A support bundle is a redacted troubleshooting file for CivicCast support. Only the Support admin role can make one." Replace "tester support".

## Notes for the coder
- Files: `CommissioningWizardScreen.tsx`; `SystemHealthScreen.tsx:1226-1313` (shared with Readiness, so keep both screens' wording consistent); server `commissioning.py:196-400, 455, 484, 713`.
- Pins: `CommissioningWizardScreen.test.tsx` pins "Run cable checks", "Save and continue", "Generate report" and "Verdict:"; `ControlRoomScreen.test.tsx` pins "Support bundles require support admin."; `tests/egress/test_automation.py` has "(boundary)" in server text. No test pins "Screens 8-11", "Continue-anyway", the dialog title or the locked messages.
- Code fix needed, not text: refuse the proof on an on-air channel (HELP-04); pass `canCreate` from the real server rule (HELP-06); remove or implement "Live" (HELP-08); optional port check for the destination; send the real deployment profile instead of `peg-cable` (HELP-02).
