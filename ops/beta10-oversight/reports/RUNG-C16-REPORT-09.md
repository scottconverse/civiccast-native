# C16 final 8-hour run - report 9 (16:30 - 20:55, 2026-10-01; 4.4 h of 8)

TL;DR: Healthy. Loudness 9/9, every program change clean, no errors, no restarts, no slate, no caption drops in the last 80 minutes.
The education-outage trigger (a very short tail at a program boundary) showed up once on public at 20:36 and the station handled it correctly.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 23 run: 22 OK (one with a "quiet" note), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip) |
| Loudness 240 s windows | 9 of 9 PASS on all three channels |
| Program changes scored | all clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 9 in 4.4 h (7 were the 18:40-18:43 cluster from my disk scans); none since 19:34 |
| Preparations | 26, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 40 GB of the 60 GB limit; free disk 822 GB |

Short-tail rollover seen live: 20:36:17 public "rollover resolved to a 3.3 s tail ... using the plan due where that tail ends instead (1800 s)".
The next preparation was queued 3 s later and public's program change at 20:47:15 scored clean. This is the U63 path that sits next to the one
that failed on education (0.0 s tail), so it is real-world evidence the neighbouring case works; the exact 0.0 s case has not recurred.

No-speech council breaks: none seen. Coder work in progress: none. Next report ~21:30. Run ends ~00:30 on 2026-10-02.
