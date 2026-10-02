# PROJECT BRIEF - CivicCast beta.10 (read this at the start of every unit)

You are the CODER. A coordinator (Claude) writes your briefs, answers your questions, and audits every
unit by re-running your checks itself. Scott (the owner) makes product decisions. You write code and
tests; you do not make product decisions.

## Goal
CivicCast is a municipal TV station app (Python, Windows-native). Scott needs three channels
(public, government, education) airing real programming at the same time, continuously, with live
captions in the output, audio/video aligned, audio loudness at -16 +/- 1 LUFS, proven by watched
runs of 30 min, then 2, 4 and 8 hours. Right now channels go dark when one channel's next program
takes a long time to prepare: the shared automation loop stalls and the other channels miss their
own program handovers ("rollover") and hit end-of-stream with nothing queued.

## Where things are
- Your worktree (the ONLY place you may write): `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds`
  Branch `beta10-ds`. Base commit 35d60b75 + commit "Snapshot uncommitted beta.10 work" + commit
  "Back out HOLD GC graph-reference patch".
- Python: `.venv\Scripts\python.exe` inside the worktree (already on your PATH as `python`).
  Run tests as `python -m pytest <paths> -q -p no:randomly`.
- Baseline (coordinator, 2026-09-24 14:10 MDT): `python -m pytest tests/egress -q -p no:randomly`
  -> 1 failed, 1611 passed, 40 skipped. The 1 failure is
  `tests/egress/test_hls_sink_captions.py::test_packaged_gstreamer_to_hls_sink_preserves_captions_and_cadence`
  ("packaged GStreamer runtime unavailable" - environment, not code). Treat it as pre-existing.
- READ-ONLY references (never write to these):
  - Installed runtime that is actually on air: `C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\`
    (it DIFFERS from your worktree; when a brief asks about live behavior, read the installed file).
  - Live station data and logs: `C:\ProgramData\CivicCast\` (main log: `logs\control_plane-app.log`).
  - Scott's main checkout: `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native`.
  - Previous team's notes: `C:\Users\scott\Documents\Codex\2026-09-20\you-x20\outputs\`.
- Oversight folder: `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight`
  You write ONLY `reports\<unit>.md` and `questions\<unit>.md` there, plus a `staging\<unit>\` folder
  when (and only when) that unit's brief explicitly tells you to create one.

## The repo's own CLAUDE.md / AGENTS.md
They were written for an earlier release and say an agent may push, merge, tag and publish.
THAT DOES NOT APPLY TO YOU. This brief overrides them. Use them only for code conventions.

## Rules (all mandatory)
1. Never push, tag, release, merge, rebase, or touch any other repo or folder than your worktree
   (plus the two oversight subfolders above). Never touch the live station: do not start/stop/restart
   services or processes, do not write under `C:\ProgramData\CivicCast` or `C:\Program Files`, do not
   run anything under `C:\dev\ClaudeElevatedHelper`, do not use `schtasks`, `sc`, or `wsl`.
2. Small local commits. Never amend. Run `git status --porcelain` before each commit and commit only
   the files you meant to change. No scratch files in the worktree (put scratch in your system temp).
3. Red before green: for every behavior change, show the new test FAILING first (quote the command and
   the failing output), then PASSING after the change.
4. Report only numbers you read from real command output, and quote the command that produced them.
   Never estimate a pass count or say "should pass".
5. If a brief rests on a false premise, or you hit a product question (what the station SHOULD do),
   write `questions\<unit>.md` in the oversight folder and STOP. Do not invent answers.
6. End every unit with `reports\<unit>.md`: commits (hash + message), each proof command with its raw
   result, what you did NOT do or could not verify, and your doubts.
7. Keep observation and inference separate in reports: label each claim OBSERVED (with file:line or
   log line quoted) or INFERRED.

## Live-station read rule (added 2026-09-26 10:38 after an incident)
NEVER open anything under `C:\ProgramData\CivicCast\data\egress\live-hls\` with ffmpeg/ffprobe or any long-lived
reader, and never read `playlist.m3u8` in place. On Windows an open handle blocks the relay's atomic playlist
replace: at 10:36:53 a coder's three `ffmpeg -i ...\live-hls\<ch>\playlist.m3u8 -t 90` froze ALL THREE channels for
viewers for ~50 s. To inspect emitted output: COPY finished `seg*.ts` files (older than the newest two) to %TEMP%
with a plain file copy, then analyse the copies. The only sanctioned live readers are the coordinator's rung scripts.
