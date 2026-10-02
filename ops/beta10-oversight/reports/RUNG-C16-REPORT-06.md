# C16 final 8-hour run - report 6 (16:30 - 19:30, 2026-10-01; 3 h of 8)

TL;DR: A quiet, clean 45 minutes after my disk scans stopped: no caption drops, no errors, no restarts, no slate, every check passing.
Three hours in: loudness 6/6, program changes all clean, one raw FAIL (verify #11) already adjudicated.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 16 run: 15 OK (one with a "quiet" note), 1 raw FAIL (#11, adjudicated as a sampling blip) |
| Loudness 240 s windows | 6 of 6 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 8 in 3 h, none since 18:44 (7 of them 18:40-18:43 while I was running disk scans) |
| Preparations | 18, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 37 GB of the 60 GB limit, not growing now (the programs are cached); free disk 825 GB |
| Machine CPU at this moment | ~65% with all three channels preparing/playing |

Evidence the self-inflicted-load reading holds: zero drops in the 47 minutes since my scans stopped, versus 7 in the 3 minutes they ran.

Not started: D5 (caption priority fix). Decision rule: if drops recur on a quiet machine, brief it; if not, record that C16 does not need it.
No-speech council breaks: none seen. Coder work in progress: none. Next report ~20:00. Run ends ~00:30 on 2026-10-02.
