# C16 final 8-hour run - report 11 (16:30 - 21:55, 2026-10-01; 5.4 h of 8)

TL;DR: Healthy. Loudness 11/11, every program change clean, no errors, no restarts, no slate. One more caption drop (public 25 s, 21:31)
since report 10; none since.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 28 run: 27 OK (two with a "quiet" note: education 18:00, government 21:47), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 11 of 11 PASS on all three channels (including government while airing the "Serving Locally" episode that had the 1.94 LU worst-stretch note) |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 10 events in 5.4 h: education 30 s (16:54); seven 18:40-18:43 (my disk scans); education 35 s (19:34); public 25 s (21:31, as government's cold 344 s preparation finished). None since 21:31 |
| Preparations | 32, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 43 GB of the 60 GB limit; free disk 817 GB |

The "quiet" notes (education 18:00, government 21:47) were both a very short window with no captions while the caption worker was receiving audio; the
next verify after each was clean and the caption files are updating normally.

Next: report 12 ~22:30; run ends ~00:30. Then VERDICT-NOTE.md and the tag recommendation to Scott (push/merge/tag/release stay his).
No-speech council breaks: none seen. Coder work in progress: none.
