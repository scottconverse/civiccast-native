# Disk cleanup report - 2026-10-01 (approved by Scott in chat)

TL;DR: I deleted about 25 GB of my own finished work. Free space is still ~35 GB because the station's own
prepared-file cache has grown to ~21 GB and is churning. The biggest remaining space is NOT mine.

## What I deleted (all CivicCast beta.10 coder work, all mine)
| What | Size | Why it was safe |
|---|---|---|
| scratch\U59-2 big video files (10 x .ts) | 12.86 GB | Test media from a finished unit; scripts + result text kept (reports\U59.md cites them) |
| 23 finished-unit work folders `civiccast-ds-{gst,int,u21,u23,u25fix,u26,u27,u29,u30,u31,u32,u33,u34,u36,u37,u41,u44,u46,u47,u59,u59e,u61,u62}` | ~10.8 GB (estimate from 19 measured at 9.0 GB) | Each was checked clean (no uncommitted changes) before removal, using `git worktree remove` without force. Every unit's branch `beta10-*` is still in the repo (31 branches), so any of them can be checked out again |
| scratch\U59, scratch\u56r4 big video files (9 x .ts) | 1.26 GB | Test media only; logs and scripts kept |
Total about 25 GB.

## What I kept on purpose
- Work folders with uncommitted changes: u56, u59d, u60, u63. Not mine to guess at.
- u64 (parked candidate) and u65 (will be the base for C16).
- All reports, logs, briefs, evidence, coder records (runs\ 2.5 GB of text logs, coder-config 1 GB), the handoff.
- Everything under C:\ProgramData\CivicCast (the live station) and C:\Program Files\CivicCast (Native).

## Why free space did not jump (35 GB now, was 77 GB this morning)
The station's prepared-file cache `...\egress\conform-cache` is 21 GB and rising (three files of 5-7 GB each being
built, one at 15:25 still a .tmp). That is the known cache-budget problem (20 GB cap vs ~11 GB per long meeting):
the station keeps deleting and rebuilding. It also grew while education and government re-prepared after today's
14:22 restart. The three channels' working folders hold another ~15.5 GB.

## Not mine - for Scott's own audit list (not touched)
C:\cc-nb\build (247 GB), C:\CivicCastTester (170 GB), Recycle Bin (75 GB), C:\tmp (60 GB), LM Studio models (58 GB).
Those are by far the largest and untouched.

## Not done, on purpose
- Did not clear the station's conform cache: the station is on air and preparing from it right now.
- Did not touch the 115 GB ProgramData uploads folder (the station's imported media).

## State right now (15:25)
Service pid 32116 (restarted 14:22). education, government, public all ON_AIR (education on the Aug 11 council meeting).
