# verify #11 (18:22:22-18:23:21) - education freshness FAIL: adjudicated as a sampling blip, not a stall

Raw: verify-11.json channels.education.freshness = FAIL: media-sequence 3372 did not advance between the verifier's two
bounded samples; government (3555->3556) and public (3441->3442) advanced.

Evidence it was NOT a real stall:
1. The rung's own 30 s sampler (samples.txt): education playlist age 4 s at 18:21:44, 5 s at 18:22:15, 1 s at 18:23:52,
   1 s at 18:24:24 (ok, audio+video, a-v <= 0.017 s). A stall long enough to matter would show age >> 20 s (DARK).
2. Segment arithmetic: media-sequence 3372 at ~18:22:25; 3519 at 18:27:18 (playlist read) = 147 segments in ~293 s
   = 1.99 s/segment, the channel's normal cadence. A stall of even 10 s would leave the count ~5 short.
3. Control plane log: education ON_AIR on the same source and worker pid the whole window; no relay restart, no slate.
4. Same verify: timestamp continuity PASS on all channels; the other 10 verifies all passed freshness on all channels.
Limit: there is a ~97 s gap in the 30 s sampler while the verifier ran (18:22:15 -> 18:23:52), so a sub-5 s hiccup
inside the verifier's own two samples cannot be excluded by direct observation. Verdict: BORDERLINE-benign; counted
as 1 raw FAIL in the final tally and listed here. If another freshness FAIL appears on any channel, escalate.
