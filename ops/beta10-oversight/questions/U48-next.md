# U48 follow-on - caption decode-back window is too short (coordinator call, final)

OBSERVED: verify #4 (13:10:02) government + education caption_decode_back FAIL on 4 segments (~8 s) while both
channels injected 14-17 captions/min (worker `CTRL caption` counters) and government's sidecar reads "take a five
-minute break" (a recess); my own decode of education's newest 5 finished segments found 4 cues. An 8 s window fails
on any speech pause, so an 8 h rung will fail on noise.

Change `verify_beta10_live_hls_media.py` caption_decode_back to decode the newest ~60 s of FINISHED segments (copy
them first per the Live-station read rule; exclude the newest two), PASS if >= 1 cue in that span, and record the
span seconds + cue count in detail. Also make rung_check report a channel's caption FAIL only when that channel's
worker `CTRL caption <ch>: received=0` for the same 60 s OR two consecutive verifies decode 0 cues (a real outage),
otherwise `CAPTION_QUIET(<detail>)` listed but not failed. Tests; re-run on verify-04 of rung-8h-post-u44.
Report as Part II of reports\U48.md.
