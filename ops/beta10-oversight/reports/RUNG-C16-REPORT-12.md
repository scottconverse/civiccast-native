# C16 final 8-hour run - report 12 (16:30 - 22:25, 2026-10-01; 6 h of 8)

TL;DR: Healthy, with one event to disclose: at 22:23 government's hand-off to its next program timed out on the first try, the station
re-armed it by itself 3 seconds later, and the program went on air at 22:24 with no gap. Loudness 12/12, every program change clean, no restarts.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 31 run: 30 OK (two with a "quiet" note), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 12 of 12 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.041 s, 0 audio lost, 0 holes |
| Errors / watchdog firings | 0 / 0 |
| Aborted first attempts | 1: government 22:23:58 (reload timed out; "retry 1 of 2" accepted 22:24:01; on air 22:24:17 on the next program; outgoing program kept airing) |
| Caption audio drops | 10 events in 6 h (7 were my 18:40-18:43 disk scans); none since 21:31 |
| Preparations | 37, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 44 GB of the 60 GB limit; free disk 817 GB |

The aborted first attempt is the same behaviour C15 showed twice (04:22 and 04:54 on 9/29); it is on the backlog as the daemon's "first-attempt short-tail
abort". It is recoverable by design and did not affect what viewers saw. Also noted: the station logged two more speech-leveling gate notes
(Serving Locally 1.94 LU worst stretch; Longmont Weather Report 1.39 LU worst stretch, 22:23); loudness windows have passed regardless.

Next: report 13 ~23:00; run ends ~00:30. Then VERDICT-NOTE.md and the tag recommendation to Scott (push/merge/tag/release stay his).
No-speech council breaks: none seen. Coder work in progress: none.
