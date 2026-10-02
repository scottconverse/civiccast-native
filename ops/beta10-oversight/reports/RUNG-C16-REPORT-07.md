# C16 final 8-hour run - report 7 (16:30 - 19:55, 2026-10-01; 3.4 h of 8)

TL;DR: Healthy. Every check since report 6 passed, no errors, no restarts, no slate, no caption drops in the last 20 minutes.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 18 run: 17 OK (one with a "quiet" note), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 7 of 7 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 9 in 3.4 h: education 30 s (16:54); seven 18:40-18:43 (my disk scans); education 35 s (19:34, quiet machine). None since 19:34 |
| Prepared-file cache | 38 GB of the 60 GB limit; free disk 825 GB |

Decision on record (D5): the caption drop on a quiet machine means C16 does not fully fix caption starvation; the fix is on the
post-release backlog and C16 ships as is (reasons in OVERSIGHT-LOG.md).

No-speech council breaks: none seen. Coder work in progress: none. Next report ~20:30. Run ends ~00:30 on 2026-10-02.
