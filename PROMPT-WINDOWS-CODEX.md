# Paste this into the Codex desktop agent on the tester box (Windows, nothing else installed)

You are a Codex agent with a shell on a Windows 11 box for a CivicCast fleet
soak test. Run every command yourself with PowerShell 5.1 (no WSL, no
python assumed) — if your execution mode needs a one-time approval to run
shell commands, ask Scott for that approval once now, then proceed without
asking again for the rest of this mission.

MISSION: soak72-9573d4a
YOUR BRANCH (push only here): tester/soak72-9573d4a-<YOUR-HOSTNAME>
DIRECTIVES BRANCH (read only, never push): soak72-9573d4a-directives
REPO: https://github.com/scottconverse/civiccast-native.git
KIT (LAN, HALO, port 8766, firewall open): http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/
KIT CHECKSUM FILE (live now, 20 entries, covers everything):
  http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/SHA256SUMS.txt

Do this in order:

1. If `git --version` fails, install it:
     winget install --id Git.Git -e --scope user
   then open a new shell (PATH refresh) and confirm `git --version`.

2. Clone the directives branch and read the current directive:
     git clone --single-branch --branch soak72-9573d4a-directives https://github.com/scottconverse/civiccast-native.git C:\CivicCastSoak\directives
     git -C C:\CivicCastSoak\directives show origin/soak72-9573d4a-directives:LATEST-TEST-DIRECTIVE.md
   That names the current directive file (right now: soak/DIRECTIVE-1.md).
   Read it in full:
     git -C C:\CivicCastSoak\directives show origin/soak72-9573d4a-directives:soak/DIRECTIVE-1.md

3. DIRECTIVE-1.md is the complete instruction set — it is self-contained
   and assumes a bare box exactly like this one: it covers the kit fetch
   (a PowerShell function you paste in, since http.server has no recursive
   fetch), SHA256SUMS.txt verification, the installer + first-run steps,
   the three-channel soak scenario with the real sample videos, the 30-min
   heartbeat loop, the 4-hour rollup reports, the 24h checkpoint, the
   halfway crash-recovery test, and the 48h final verdict. Follow it
   exactly, start to finish, without waiting for anyone to click along.

4. Before doing anything from DIRECTIVE-1.md's own step 1.3, create your
   branch and push an immediate ack (DIRECTIVE-1.md section 1.3 has the
   exact commands) so the coordinator sees you're alive.

5. Re-read the directives branch every 15 minutes, forever, for new
   directives — a published verdict at T+48h ends this mission's data
   collection, not your polling duty.

Trigger: START NOW
