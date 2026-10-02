# C16 final 8-hour run - report 5 (16:30 - 19:05, 2026-10-01; 2.5 h of 8)

TL;DR: Station still healthy (no errors, no restarts, no slate, loudness 5/5, every program change clean). One thing got worse
and I caused part of it: 7 caption-audio drops across all three channels between 18:40 and 18:43 (175 s of audio), exactly when I
was running disk-size scans at normal priority on this box while your deletions were also running. That window is confounded.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 14 run: 13 OK (one with a "quiet" note), 1 raw FAIL (#11 at 18:23, adjudicated as a sampling blip, evidence in the run folder) |
| Loudness 240 s windows | 5 of 5 PASS on all three channels |
| Program changes scored | all clean so far: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost, 0 holes |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 8 in 2.5 h: education 30 s (16:54), then at 18:40-18:43 government 40+10 s, education 30+40+15 s, public 20+20 s |
| Preparations | 15, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 37 GB of the 60 GB limit, nothing evicted; free disk 827 GB |

## What I got wrong in this stretch (logged)
1. **I loaded the machine during the run.** My disk-size scans (du over the station's data and large trees) started about 18:39 at normal
   priority, with your deletions running too. The 7 drops at 18:40-18:43 line up with that. The same mistake cost C15 a 5 s drop at 08:12.
   I will not run heavy scans while the run is live; any further drop in that window is counted but marked as self-inflicted.
2. **My problem-events watch was blind from 17:00 to 19:05.** A pipe into `cut` buffered its output, so it delivered nothing. My 10-minute
   checks still read the log directly, which is how this was found, but I did not catch the 18:40 drops until 19:05. Fixed (unbuffered).

## Not yet decided (D5)
If caption drops continue after the machine is quiet, the fix (give captions priority over preparation) goes to a coder unit. Not started.

No-speech council breaks: none seen. Coder work in progress: none. Next report ~19:30. Run ends ~00:30 on 2026-10-02.
