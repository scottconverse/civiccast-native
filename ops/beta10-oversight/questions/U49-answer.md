# U49 - coordinator answer (final; engineering calls, not owner calls)

Excellent diagnosis. You are right that my brief's placement was wrong: the ride is prepare-time, the playout graph has
no gain stage, and the shipped GStreamer has no limiter. Decisions:

**Q1/Q2: mechanism C - stream-copy the worker's AAC in the relay (`-c:a copy`).** It removes the offending second AAC
generation outright, holds the worker's measured values (-1.1 dBTP, -16.1 LUFS), costs no CPU (saves an encode per
channel), and needs no limiter. +48 % audio bitrate on the local HLS leg (~133 -> ~198 kbps) is accepted.
No relay limiter (B) and no redrive loop (D).

**Q3: the bar is structural, not a guarantee on arbitrary content.** Acceptance: (a) the emitted audio is the worker's
AAC bit-for-bit (packet payload hashes of the audio PIDs equal between relay input and output on a replay), (b)
per-segment true peak of the emitted output equals the relay input's per-segment true peak within 0.05 dB on every
segment, (c) integrated loudness unchanged within 0.1 LU, (d) A/V offset in emitted segments unchanged within 10 ms
vs today's argv on the same replay, (e) HLS segments still start on keyframes and every segment carries audio + video
+ captions (the verifier's checks) on the replay.

**Q4: yes, add per-segment true peak to the instrument - ADD a field, do not replace.**
`capture_emitted_hls_audio_proof.py` gains `true_peak_max_segment_dbtp` (+ which segment) measured on each captured
segment individually; keep the existing concat `true_peak_dbfs` unchanged. Retry/no-held-handle rules as U48. Replace
atomically (the running rung calls it each loudness run). Unit test for the new field.

**Q5: timing.** True peak is not a beta.10 gate and the live rate is ~1 segment in 100. So: build, prove and STAGE C
now (`staging\U49\`, bases hashed from LIVE installed files, `<sha> *civiccast/<rel>`). The coordinator decides when to
install - it will not interrupt the running 8 h rung for it unless that rung fails for another reason.

Work order: RED first where applicable (a test on `HlsSink.output_args()` asserting `-c:a copy` for the audio stream,
failing on HEAD), then the replay proof (a)-(e) with the station's own ffmpeg, then the instrument field, then staging.
No station writes, no restarts. Report in `reports\U49.md`, receipt line at the end.
