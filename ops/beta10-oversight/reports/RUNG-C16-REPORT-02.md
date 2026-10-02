# C16 final 8-hour run - report 2 (16:30 - 17:30, 2026-10-01; hour 1 of 8)

TL;DR: Clean hour. Every check passed, no errors, no restarts, no slate. One caption audio drop (30 s on education at 16:54)
and nothing since.

| Item | Result |
|---|---|
| Service | same process (pid 20668) for the whole hour; no restart or crash |
| Channels | education, government, public on air on real programs the whole hour; no slate/filler after startup |
| Captions / timing / playback checks | 6 of 6 OK (16:30, 16:41, 16:54, 17:05, 17:16, 17:27) |
| Loudness 240 s windows | 2 of 2 PASS on all three channels (16:45, 17:16) |
| Program changes scored | 3 of 3 clean so far (public 16:57, education 16:59, government 16:59): picture <= 0.033 s (one frame), sound <= 0.037 s, 0 audio lost. Later changes are due ~17:27-17:30 and land in report 3 |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 1 (education 30 s, 16:54:08, CPU ~98% with Defender at ~87% of a core). None since |
| Preparations | 6, all inside the ~11 min lead: public 265 s and 224 s; government 329 s; education 389 s and 265 s (plus one more government) |
| Prepared-file cache | 27 GB of the new 60 GB limit (the old limit was 20 GB, so it is no longer evicting) |
| Disk free | 845 GB |

No-speech council breaks: none seen yet. If one fails the caption check I will list it with the transcript evidence.

Coder work in progress: none. Everything staged is installed.

Next report ~18:00. Run ends ~00:30 on 2026-10-02.
