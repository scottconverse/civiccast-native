# U56 round 4 - coordinator ruling on Part III: U56b NOT installed; close the hole at the switch point

## Audit of Part III (coordinator, OBSERVED)
Your Item 1 ordering holds and I re-checked it on a fresh live changeover. Education, commit 02:38:06:
```
85464: CTRL reload: outgoing EOS observed stream=video (1/2 stream(s))      <- video EOS BEFORE the reference line
85465: rebase-reference reload_id=5 ... ends=[video=8998.836,audio=8999.467] switch_running_time=8999.467
85470: stage=rebase-drain-drained waited=1.265s reload_id=5
```
Emitted hole (coordinator watch, keeper copy seg000004499.ts): **0.631 s**, which is exactly 8999.467 - 8998.836.
In live, the retiring video is COMPLETE (EOS'd) and the hole equals the outgoing programme's own
video-end vs audio-end difference. It is a media end asymmetry. It is not delivery lag.

C4 live tally: 4 clean, 10 HOLE (0.136-0.769 s), audio clean every time. Clean ones are plausibly assets whose
legs end together.

**Ruling:** `staging\U56b` is NOT installed. Its wait cannot help when the video leg has already EOS'd, which
is the live case (your own test `..._retiring_leg_that_has_already_eosed_is_done`). It would cost a restart
for no measured effect.

## Remedy - engineering call (mine): your Part III option 2/3 alternative, no synthetic frames
The switch point must be the END OF THE SHORTER LEG of the outgoing programme, not the audio end:
- switch_running_time = min(video_end, audio_end), using the FINAL ends (after the EOS of each leg), not the
  arm-time estimate. In live, video EOS'd before the arm; handle both orders.
- The longer leg's tail past that point (normally <= ~0.8 s of outgoing audio) is DROPPED by the existing C4
  value fence. That is the cutoff you already have, moved.
- Log it every time:
  `CTRL reload diagnostic: switch-at-shorter-leg reload_id=N video_end=X audio_end=Y trimmed=<stream>:<s>`.
- Bound: if the difference is > 2.0 s, do NOT trim. Keep today's behaviour and log a WARN (a truly broken asset
  must stay visible).
- Result required: no picture gap AND no audio gap at the join, A/V offset unchanged after the switch
  (new leg applied_offset = the new switch point for both streams), no synthetic frames.

## Work
1. Measure first: for 3 live prepared assets that produced holes (public 02:35, education 02:38, government
   02:47), find the prepared file(s) in the prep cache. Report the video and audio stream end PTS (ffprobe on a
   COPY). Say whether the asymmetry is in the source asset or introduced by preparation. If preparation
   introduces it, say where. Report only; the switch-point fix is the remedy either way, because cached
   assets already carry it.
2. RED/GREEN on a real worker: `clips\out_shortv.ts` (your deterministic 0.572 s RED) must go to maxgap
   <= 0.034 s video AND audio packet steps <= 0.050 s across the join (packet PTS, the U57 method). Also
   rerun a symmetric-clip changeover (outgoing.ts) to show no regression. 2/2 each. `start /low`,
   <= 10 min per run.
3. Unit tests: min-end selection (both EOS orders), the 2.0 s bound, and the log line.
4. Stage `staging\U56c\` from LIVE bytes (base 7509ed0a, NOT the U56b candidate), `installed-base.sha256` in
   the usual format. Report Part IV, plain-English summary first, receipt last. No station action. An 8 h rung
   is live; keep load small.
