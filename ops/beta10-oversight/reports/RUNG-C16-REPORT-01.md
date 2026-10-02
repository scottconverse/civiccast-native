# C16 final 8-hour run - report 1 (16:30 - 16:57, 2026-10-01)

TL;DR: Healthy so far. 3 of 3 checks passed, loudness passed on all channels, 0 errors, 0 restarts. One caption
audio drop (30 s on education) while all three channels prepared their next programs at once and the machine sat
at ~98% CPU. That is the one item to watch.

## Numbers
| Item | Result |
|---|---|
| Service | same process (pid 20668) since the C16 install at 16:22:41; no restart |
| Channels | education, government, public all ON_AIR on real programs the whole time; no slate/filler since startup |
| Captions/timing/playback checks | verify #1 16:30 OK, #2 16:41 OK, #3 16:54 OK (3/3) |
| Loudness 240 s windows | #1 16:45 PASS on education, government, public (1/1) |
| Program changes scored | none yet in this window |
| Errors / watchdog firings / aborted | 0 / 0 / 0 |
| Caption audio drops | 1: education 30 s at 16:54:08 (C15 had 5 s, 20 s, 50 s over 8 h) |
| Preparations | public 265 s (ready 16:50), government 329 s (16:54), education 389 s (16:54); all inside the ~11 min lead |
| Prepared-file cache | 15.1 GB of the new 60 GB limit; free disk 854 GB |

## The one item: the caption drop
All three channels prepared their next programs at the same moment (16:48-16:54, each 4-6 min), and the machine ran
~95-98% CPU. Part of that load is not the station: Windows Defender (MsMpEng) was at ~87% of a core, almost certainly
scanning during Scott's disk cleanup, plus other background processes. So this drop has a confounder; I'm counting it
but not blaming the station on one sample. If drops continue when the machine is quiet, D5 (give the caption tap
priority over preparation) becomes a fix; it is NOT started.

## Coder work this stretch
U66 (rung checker) and U67 (education rollover fix) both finished, audited by me, installed. Nothing in progress.

## Mistakes logged this stretch
- mkjob.py corrupted a folder name (backslash-b became a backspace) - caught before the install job ran, fixed.
- My notes had the cache setting spelled CIVICAST_...; the code reads CIVICCAST_CONFORM_CACHE_GB.
- First deletion-safety pass checked one direction only (what the folders depend on, not what depends on them).

Next report ~17:30.
