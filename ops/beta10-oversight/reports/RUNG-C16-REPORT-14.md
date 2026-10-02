# C16 final 8-hour run - report 14 (16:30 - 23:34, 2026-10-01; 7.1 h of 8)

TL;DR: Video and sound healthy; captions are the weak spot. Loudness 14/14, every program change clean, no restarts, no slate, no errors. Caption audio drops: 13 events in 7.1 h, three of them since report 13 (23:08-23:09), clustered around public's 281 s cold preparation. Nothing since 23:09.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Verify checks | 36 run: 35 OK, 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 14 of 14 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s, sound <= 0.040 s, 0 holes |
| Errors / watchdog firings | 0 / 0 |
| Aborted first attempts | 2 total (government 22:23 timeout, 22:55 error); both recovered in about 3 s, no on-air effect |
| Known piece-join single-frame drop | 1 (government ~22:50, 0.033 s) |
| Caption audio drops | 13 events: 16:54 edu 30 s; seven 18:40-18:43 (my disk scans); 19:34 edu 35 s; 21:31 public 25 s; 23:08 edu 10 s + public 40 s; 23:09 edu 20 s |
| Cache / disk | cache 46 GB of 60 GB; disk 811 GB free |

Caption finding I am not going to soften: verify #35 passed overall, but its per-segment decode found many segments with no embedded caption cue
(listed per segment in verify-35.txt). That matches the caption-tap drops. Quiet-machine drops total 140 s of audio on education and public over 7 h;
C15 had 5/20/50 s over 8 h. C16 is not better on captions. Root cause (tap falls behind during long cold preparations) is on the post-release backlog (D5 option A).

Next: report 15 ~00:00; run ends ~00:30. Then VERDICT-NOTE.md and the tag recommendation (push/merge/tag/release stay Scott's).
No-speech council breaks: none seen. Coder work in progress: none.
