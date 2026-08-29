# Candidate #16 card-only run

- Card read once: 2026-08-29T13:46:55Z
- Instruction source from this point: `C:\CivicCastSoak\kit16\QUICKSTART-OPERATOR.md` only
- GUI mode: non-silent, first-time operator behavior

## Step 1 — Plug in the USB kit

- Card says: plug the CivicCast USB stick into the station computer.
- Observed at 2026-08-29T13:47:00Z: the supplied test kit is available as `C:\CivicCastSoak\kit16`, the fixture that represents the USB stick for this run.
- Verdict: **MATCHES CARD** (test-fixture equivalent supplied by the mission).

## Step 2 — Double-click the setup program

- Card says: open the USB drive, double-click the CivicCast setup program, and if Windows shows the blue "Windows protected your PC" screen, click **More info** and **Run anyway**.
- Action at 2026-08-29T13:48:26Z: launched `CivicCast (Native)_1.0.0-beta.1_x64-setup.exe` non-silently with no command-line flags, the automation equivalent of the instructed double-click.
- Observed: Windows opened a secure-desktop elevation consent prompt (`consent.exe`, PID 16524). No targetable CivicCast installer window or product side effect appeared.
- The card does not mention this elevation prompt or tell a no-experience operator what to select.
- The Windows automation surface cannot read or operate secure-desktop security dialogs, so the requested choice could not be made honestly and no silent/elevated fallback was used.
- Verdict: **COULD-NOT-PERFORM** after the literal launch because the secure-desktop prompt is not agent-driveable.
- 2026-08-29T14:06:20Z — **SUBSTITUTED: elevated launch = human's UAC Yes (per DIRECTIVE 8b)**. No other card step is substituted; strict card-only behavior resumes when the normal installer window exists.
- Elevated non-silent launch completed at 2026-08-29T14:08:07Z with no arguments. A normal `CivicCast (Native) Setup` window appeared.
- Verdict after the authorized substitution: **MATCHES CARD** for reaching the normal installer window; findings 1 and 2 remain as accepted boundary evidence.

## Step 3 — Wait

- Card says: setup does everything on its own after launch, the screen stays active and shows its current step, and the operator should wait without closing it.
- Observed from 2026-08-29T14:08:47Z through 2026-08-29T14:10:10Z: the installer remained on a static **Welcome to CivicCast (Native) Setup** wizard page. It instructed the operator to click **Next** to continue and exposed **Next >** and **Cancel** buttons.
- The card never instructs the operator to click **Next** and explicitly says setup does everything on its own. Clicking **Next** would require knowledge outside the card, so it was not clicked.
- Side-effect check after the wait: `CivicCastSupervisor` absent; `C:\ProgramData\CivicCast` absent; no listener on port 8000.
- Verdict: **DEVIATES** — setup did not begin or advance on its own, and the card omits the required wizard action.

## Steps 4–6

- **COULD-NOT-PERFORM:** Step 3 never advanced past the unmentioned **Next >** gate, so there was no completed install, no **Open operator console** button, no First Setup page, and no live station.

## Findings

1. **Step 2 — card-gap:** The card covers SmartScreen but not the Windows elevation consent prompt that appeared before installation; a no-experience operator needs an instruction for this screen.
2. **Step 2 — agent-limitation:** The secure-desktop elevation prompt cannot be read or clicked by the available Windows automation surface, so the run cannot advance past the literal non-silent launch without human interaction.
3. **Step 3 — card-gap:** The normal installer opens on a wizard welcome page that requires **Next >**, while the card says setup does everything on its own and contains no instruction to click **Next**. Strict card-only execution therefore stops before installation begins.
