# U59 round 4 - instrument the next occurrence (diagnostic only)

Round 3 ACCEPTED (coordinator 23:12): the 23 fps stretch is not in the media (source + conforms clean at every
offset) and 8x normal-priority 1080p load does not reproduce it; the station's ordinary contention dips BOTH streams
to ~0.92 together, the 19:15 collapse was video-only at 0.79. Mechanism unknown, one occurrence in ~60 C9/C10
changeovers. We will not guess a guard.

## Work (stage only; C11 is live with an 8 h rung until ~06:37; no station action)
1. In the LIVE engine bytes (C11 engine = 8a3722c9), add a diagnostic that fires when a leg's chain-in VIDEO rate
   falls below 0.9 x nominal for 2 consecutive CTRL output polls while its audio stays >= 0.97 x nominal. On fire,
   log ONE WARN line per episode with: reload_id, leg source path, the leg's running time and position in its piece,
   per-element queue levels (current-level-buffers/time) on that leg's video branch, decodebin/decoder element names,
   and any QoS messages seen on the leg in the last 30 s. Rate-limit to 1 line per 10 s; no behaviour change.
2. Reword the bound-exceeded WARN so it does not assert the asset is broken: state the measured video_end/audio_end
   and "video delivery fell short at the end of the leg" when the diagnostic fired in the last 60 s.
3. RED/GREEN in tests (a synthetic leg whose video pad is throttled). Stage `staging\U59d\` from LIVE engine bytes.
   Report "Round 4" in reports\U59.md, plain English first, receipt last.
