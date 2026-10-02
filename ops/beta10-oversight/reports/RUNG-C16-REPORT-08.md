# C16 final 8-hour run - report 8 (16:30 - 20:25, 2026-10-01; 4 h of 8, halfway)

TL;DR: Halfway and healthy. No errors, no restarts, no slate, loudness 8/8, every program change clean, and no caption drops in the
last 50 minutes.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 21 run: 20 OK (one with a "quiet" note), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 8 of 8 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 9 in 4 h (7 of them were the 18:40-18:43 cluster caused by my disk scans); none since 19:34 |
| Preparations | 23, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 38 GB of the 60 GB limit, flat; free disk 824 GB |

The education watchdog (the fix for the 34-hour dead air) has not needed to fire; the boundary re-resolve path has handled every education
rollover. There is no evidence yet of the original trigger (a 0-second tail) recurring.

No-speech council breaks: none seen. Coder work in progress: none. Next report ~21:00. Run ends ~00:30 on 2026-10-02.
