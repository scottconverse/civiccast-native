# DIRECTIVE 7 — STANDBY (supersedes ALL prior directives)

Status of prior work: the LPM-rehearsal mission (DIRECTIVES 5/5b/6) is COMPLETE and its
soak verdict was PASS. Do NOT re-run any part of it. Do NOT install, uninstall, wipe,
format, or touch the station currently on this machine. Do NOT touch any USB drive.

Your only job right now:
1. Commit soak/ACK-STANDBY.md to your working branch
   (tester/lpm-rehearsal-407e507-DESKTOP-VBMA6O5): timestamp + "standing by per
   DIRECTIVE 7" + one line stating whether the station on this box currently answers
   http://127.0.0.1:8000/api/health (a plain observation, change nothing).
2. Then poll THIS branch (tester/soak8h-99db2c6-directives) every 10 minutes for
   DIRECTIVE-8, which will arrive later with the next mission (a card-only GUI install
   acceptance run for a new candidate). Record polls in soak/POLL.md (overwrite each
   time, one line).
3. `git fetch origin` before every poll decision, always.

Nothing else. Honest and idle beats busy and wrong.
