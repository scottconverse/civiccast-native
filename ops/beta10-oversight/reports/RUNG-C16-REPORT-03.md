# C16 final 8-hour run - report 3 (16:30 - 18:00, 2026-10-01; 1.5 h of 8)

TL;DR: Still clean. Every check passed, 0 errors, 0 restarts, 0 slate. The only blemish in 90 minutes is the one 30 s
caption audio drop on education at 16:54, and none since.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 8 of 8 OK (16:30, 16:41, 16:54, 17:05, 17:16, 17:27, 17:38, 17:49) |
| Loudness 240 s windows | 3 of 3 PASS on all three channels (16:45, 17:16, 17:46) |
| Program changes scored | 6 of 6 clean (public 16:57 and 17:27; education 16:59 and 17:29; government 16:59 and 17:29): picture <= 0.033 s (one frame), sound <= 0.037 s, 0 audio lost. The ~17:57-18:00 round is landing now and goes in report 4 |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 1 in 90 min (education 30 s at 16:54, CPU ~98%, Defender confounder). C15 had 3 in 8 h |
| Preparations | 9, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 33 GB of 60 GB limit, no eviction; free disk 838 GB |

No-speech council breaks: none seen yet. Coder work in progress: none.
Next report ~18:30. Run ends ~00:30 on 2026-10-02.
