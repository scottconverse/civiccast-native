# DIRECTIVE 8 — the STRANGER TEST: card-only GUI install acceptance of candidate #16

Mission: prove (or disprove) that a person with NO knowledge of this product can go from
USB kit to running station using ONLY the one-page quickstart card. You play that
person. THE CARD IS YOUR ONLY INSTRUCTION SOURCE during the install phases — this
directive tells you how to set up the test and how to report, never how to install.

New working branch (yours alone): `tester/stranger-test-4eca729-DESKTOP-VBMA6O5`
(from origin/main; pull-rebase before every push; poll THIS directives branch every
10 min; POLL.md rule stands).

## Phase 0 — make this machine virgin (NOT part of the card test)
1. Commit soak/ACK-8.md (timestamp, mission understood).
2. Uninstall the current station via the registry QuietUninstallString (as before),
   verify service gone + :8000 dark. THEN delete C:\ProgramData\CivicCast entirely
   (this is the one time data destruction is ordered — the machine must be virgin).
   Also remove any CivicCast Start Menu/Desktop shortcuts left from prior installs.
   Verify all gone; commit soak/VIRGIN.md with the checks.
3. Fetch kit #16 over LAN into C:\CivicCastSoak\kit16 (delete any old kit dirs first):
   http://192.168.0.135:8765/4eca7292c93a5395b337d6b404fc2bf0a6383003/
   Verify 16 files incl. QUICKSTART-OPERATOR.md; commit soak/KIT-16.md (count, bytes).
   (In the real scenario this folder IS the USB stick.)

## Phase 1 — THE CARD RUN
1. Open C:\CivicCastSoak\kit16\QUICKSTART-OPERATOR.md. Read it once. From this moment,
   act ONLY on what the card says, as a first-time operator would.
2. GUI honesty: the card says double-click the setup program — launch it EXACTLY as the
   card implies (non-silent: `Start-Process "<setup exe path>"` with NO /S flag). The
   installer opens a GUI window. Drive it only as far as your capabilities honestly
   allow:
   - If you can read/interact with the window (screenshots, UI automation), do what the
     card says and nothing more.
   - If you CANNOT see or drive the GUI, do not fake it and do not fall back to silent
     install. Instead: wait and observe the SIDE EFFECTS the card promises (the
     install-progress log advancing, the station answering on :8000, shortcuts
     appearing) and record which card steps you could not perform and why. An honest
     "I could not click X because I cannot see the window" is a valid finding about
     agent-driveability, NOT a product failure — label it clearly as such.
3. FINDINGS LOG (the deliverable): soak/CARD-RUN.md, updated and pushed at every step:
   for each card step — what the card said, what actually happened, timestamps, and a
   verdict per step: MATCHES CARD / DEVIATES (how) / COULD-NOT-PERFORM (why). ANY
   knowledge you needed that is not on the card = a numbered FINDING. Any wait longer
   than the card's stated expectation = a FINDING. Any error shown = a FINDING with the
   exact text.
4. Success criteria for the run: station healthy on :8000, operator console reachable
   the way the card describes, shortcuts present (the card mentions them), and zero
   network downloads during install (all packs from the kit — check the installer's
   staging log for satisfied_online entries; any online fetch = FINDING).
5. First Setup: follow the card. If the handoff flow blocks you (you are not a GUI
   user), record precisely where and how — this is the flow the recovery fixes target;
   its behavior evidence is gold either way.

## Phase 2 — verdict
soak/stranger-verdict.json (validate JSON round-trips before committing):
{schema:"stranger-test-v1", candidate:"4eca729...", card_steps_total, steps_matching,
findings:[{n,step,class:"card-gap|product-bug|agent-limitation",text}],
install_offline:true/false, station_healthy:true/false, verdict:"PASS|FAIL|PARTIAL"}
PASS only if: station healthy + zero card-gap/product-bug findings. Agent-limitation
findings alone → PARTIAL (a human retest decides). Honest failures over silent success.
