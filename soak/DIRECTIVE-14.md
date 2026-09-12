# Attach a fresh measured soak to the working playout

Startup diagnostic efb1cc0a at 2026-09-12T05:36Z shows all three channels
ON_AIR with PIDs public10324, education1188 and government3644. Current worker
tails show new-leg preroll and programme commits. Historical worker errors in
these append-only logs are not automatically errors from the new attempt.
R2's measured collector failed before this state and remains a failed attempt.

Execute AUTORUN-SEP11-FIXED-BETA-PHYSICAL-SOAK-R3.ps1 once. R3 attaches its ON
measurement to the already published R2 schedule and current playout, without
replacing the schedule or stopping/restarting the initial ON phase. It verifies
the candidate identity, three configured channels, fallback-disabled setting,
captions ON and live ON_AIR workers before beginning the full 120-minute clock.
The subsequent OFF phase performs the planned mode-change restart and then
measures another full 120 minutes. Both phases keep five-minute boundaries.

The existing R2 plan is bound to source39e7 and has 180 published slots through
2026-09-12T10:21:32Z. R3 refuses attachment unless the remaining horizon covers
both complete phases plus 15 minutes. Each measured phase start is published
immediately in job.json with its actual begin and planned end, so a job launch
cannot be confused with measured playout again.

The general startup allowance now begins after the first programme becomes
due (or now, if already due), and allows five minutes to reach ON_AIR. Startup
state snapshots and failure log deltas are saved. Measured duration and
boundary/worker/transport acceptance remain unchanged.

Task: CivicCast-FixedBeta-39e7-PhysicalSoak-R3, six-hour limit, once only.
Under C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c, new paths are
physical-soak-r3-bin, physical-soak-r3, return-repo-r3,
physical-soak-r3-job.json/log and physical-soak-r3-publish-error.txt.
Evidence returns to soak/fixed-beta-39e7/physical-soak-r3/job.json and evidence.zip.
Preserve R1/R2 evidence, tasks, original installed identity and all once-only
markers; keep the three CivicCastSoak coordination tasks. No installer change.
Candidate39e7 remains unpublished until physical acceptance.
