## Coordinator stop - 2026-09-27 ~22:33 (-06:00): stopped to install C11 (U60 look-ahead warm + revert of the U59 preparer pass) - not a pass verdict

Ran 20:51:50 -> ~22:33. C10 = C9 + U59 preparer pass (preparer 7f2fcef6). Service pid 34440 throughout.
- verify: 9/9 OK (#4 government CAPTION_QUIET during the in-worker slate, no speech, excused by the tool).
- loudness: 3/3 PASS.
- changeovers: 13 scored (commits education 4, government 4, public 5 incl. the 20:49 post-restart one) - video clean
  13/13; relay 'Invalid timestamps' 5 at the two slate->program switches (education 21:22:33, government 21:24:10),
  U60 measured the largest single displacement 62 ms and emitted step-backs 18-19 ms; 0 elsewhere.
- SCHEDULE: government in-worker slate ~21:22:29-21:24:08 (~100 s), education a few seconds, caused by post-restart
  short legs (116-667 s) shorter than the 690 s lead with cache-miss conforms of 284-384 s (U60 Work 1: runway law,
  automation.py:2193-2196). Egress state stayed ON_AIR with the previous program's label during the slate (U60 Work 4).
- Preparations 16-459 s after 21:24, all in time (worst 458.5 s = 67 % of lead).
Why stopped: U59 round 2 proved the preparer pass is not the fix and drops the final frame on ~40 % of 1800 s pieces
(%g tail guard), and U60 staged the fix for the slate. C11 = automation 7b4e4f18 + daemon 0d723536 (U60) + preparer
b19b7a43 (C9 aafb0b5d + U60 hunks, pass removed). The acceptance run must be on the final bytes.
