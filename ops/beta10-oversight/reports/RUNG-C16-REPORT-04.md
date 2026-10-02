# C16 final 8-hour run - report 4 (16:30 - 18:30, 2026-10-01; 2 h of 8)

TL;DR: Two hours in, the station is healthy: no errors, no restarts, no slate, loudness 4/4, program changes 10/10 clean.
There is one raw FAIL to disclose: verify #11 (18:23) flagged education's playlist as "not advancing" at one sample.
I adjudicated it as a sampling blip with evidence, but I could not directly observe the 97 s my sampler was blocked.

| Item | Result |
|---|---|
| Service | same process (pid 20668) the whole time; no restart or crash |
| Channels | all three on air on real programs; no slate or filler after startup |
| Captions / timing / playback checks | 11 run: 10 OK (one with a "quiet" note), 1 raw FAIL (#11, below) |
| Loudness 240 s windows | 4 of 4 PASS on all three channels (16:45, 17:16, 17:46, 18:16) |
| Program changes scored | 10 of 10 clean: picture <= 0.033 s (one frame), sound <= 0.040 s, 0 audio lost |
| Errors / watchdog firings / aborted starts | 0 / 0 / 0 |
| Caption audio drops | 1 in 2 h (education 30 s at 16:54); C15 had 3 in 8 h |
| Preparations | 12, all inside the ~11 min lead, longest 389 s |
| Prepared-file cache | 36 GB of the 60 GB limit, nothing evicted; free disk 835 GB |

## The two items to know about
1. **Verify #9 (18:00), education:** passed, with a note "caption quiet: 0 captions in 60 s". It was ~1 minute after education's
   17:59 program change. Captions were flowing normally by 18:09 (file updated, live council speech) and verify #10 was clean.
2. **Verify #11 (18:23), education freshness FAIL:** the verifier's two close samples saw the same playlist sequence number
   (3372) on education while government and public advanced. Evidence it was not a stall: my 30 s sampler read education fresh
   (age 5 s at 18:22:15, 1 s at 18:23:52); the sequence then reached 3519 by 18:27:18, i.e. 147 segments in ~293 s, exactly the
   normal 2 s cadence (a stall would show short); the station log shows education on air on the same worker; continuity passed.
   Limit: my sampler is blocked while the verifier runs (a 97 s gap), so I cannot rule out a hiccup of a few seconds inside the
   verifier's own samples. Written up in the run folder: ADJUDICATION-verify-11-education-freshness.md. It stays counted as a raw
   FAIL; if any channel shows another freshness FAIL I will escalate.

No-speech council breaks: none seen. Coder work in progress: none. Next report ~19:00. Run ends ~00:30 on 2026-10-02.
