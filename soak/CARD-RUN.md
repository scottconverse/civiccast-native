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

## Findings

1. **Step 2 — card-gap:** The card covers SmartScreen but not the Windows elevation consent prompt that appeared before installation; a no-experience operator needs an instruction for this screen.
2. **Step 2 — agent-limitation:** The secure-desktop elevation prompt cannot be read or clicked by the available Windows automation surface, so the run cannot advance past the literal non-silent launch without human interaction.
