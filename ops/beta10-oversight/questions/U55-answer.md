# U55 round 2 (U57 work in this session) - the checker is blind to a mid-segment video hole

Round 1 audit: PASS. NO_SPEECH_SOURCE is listed beside the OK with its numbers (same convention as CAPTION_QUIET),
the ablation RED and the flakiness RED are real, atomic replace confirmed. Doubt 4 (whole-file read of active.vtt)
accepted for now.

## New work: packet-level video continuity in the verifier's evidence
U56 found and the coordinator re-measured (copies in `%TEMP%\u56\hot\`): at every seamless programme change the
emitted video has a ~0.6 s hole while audio is continuous:
```
public/seg000003655     vpkts 35 span 1.700 maxgap 0.600 at +0.833   audio maxgap 0.021
government/seg000003711 vpkts 60 span 2.515 maxgap 0.581 at +1.933   audio maxgap 0.021
neighbours              vpkts 60 span 1.967 maxgap 0.033
```
The rung's PTS-continuity arithmetic (`scripts\capture_emitted_hls_audio_proof.py`, delta vs previous
`stream=duration`, +/-3000 ticks) only sees a hole at a segment TAIL; both holes above PASS it. See
`reports\U56.md` §1-2.

1. Add a per-segment packet-level check to the loudness capture's continuity block (and to verify, if cheap):
   `ffprobe -select_streams v:0 -show_entries packet=pts_time` (and a:0) on the snapshot copies; FAIL
   `VIDEO_HOLE(seg, gap_s at +offset)` when any inter-packet video gap > 2 frame intervals (derive the frame
   interval from the stream's r_frame_rate; do not hard-code 30), and `AUDIO_HOLE` likewise for audio
   (> 0.05 s). Keep the existing tail check. Print holes with their numbers.
2. RED-first: fixtures = plain copies of the two boundary segments above plus their neighbours (copy them into the
   oversight test fixtures now, before %TEMP% is cleaned). The current code must PASS them (that is the RED: it
   misses the hole); the new code must FAIL them with the right gap. A clean window must still PASS.
3. Cost: the rung calls loudness every 30 min over ~120 segments x 3 channels; measure the added time and keep it
   under 60 s per call. Atomic replace; the rung (8h-post-c3) is running and calls it.
4. Report `reports\U55.md` Part II (or `reports\U57.md` if cleaner), receipt at the end. Do not touch the station;
   never open live-hls with ffmpeg.
