# U47 (U41 session) - a relaunch / cold start is dark for the whole preparation. Put the slate on air first.

Installed now: your U41 (b38e5a3b minus the carve) + U40/U42/U43 preparer/ride. OBSERVED live, public, 11:19:40:
worker exit 1 (U44's switch-path video stall) -> daemon relaunch -> "start source preparation queued" for
`Parks & Recreation Advisory Board - April 2026.mp4` -> NOTHING on air until preparation completes (still dark at
11:20:29, relay "live window has not advanced"). Same shape at 01:59 (public dark ~11 min, evidence
`evidence\public-exit0-0159\`). Evidence for this one: `evidence\public-exit1-1119\` + control-plane log 11:19-.

Rule (engineering, final): an ACTIVE channel is never dark while its program is being prepared. On any start/relaunch,
the daemon starts the worker IMMEDIATELY on the fallback slate (the existing slate leg / fallback source), then hands
the prepared program in with the normal seamless reload when preparation completes. Preparation failure keeps the
slate and retries per the existing policy.

## Work (new worktree `civiccast-ds-u47`, branch `beta10-u47` from `b38e5a3b`; own `.venv`)
1. Find the start/relaunch path that waits for preparation before launching (file:line), and the existing slate/
   fallback machinery. Implement the rule. Keep the persistent flag (CIVICCAST_WORKER_PERSISTENT) on the slate launch.
2. Tests red then green: unit (relaunch with slow preparation -> worker launched on slate at once; reload issued on
   completion; failure keeps slate) and one real-worker run with runtime root `C:\Program Files\CivicCast (Native)\runtime`
   (slate output within 5 s of start, then the program after a delayed preparation, no worker exit).
3. Gates after checking no other `pytest tests/egress` is running; ruff; mypy. Stage `staging\U47` like U41 (bases =
   live sha256s; engine.py only if touched, minus the STALL_DIAG carve). Do not install. Report `reports\U47.md`.
READ the "Live-station read rule" at the end of PROJECT-BRIEF.md first: never open live-hls with ffmpeg; copy
finished segments first. U44 (engine) and U46 (captions/daemon/worker) are working from the same base: keep hunks
minimal and list them for a mechanical merge.
