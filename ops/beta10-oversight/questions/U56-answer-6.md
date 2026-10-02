# U56 round 6 - C6 (U56d) is live: 3 of 4 clean. The failing case is AUDIO-EOS-FIRST

C6 = staging\U56d (engine.py 77251b70) installed 2026-09-27 07:04:48, service pid 31260, live hash verified.
Your mux-tail fence works: 0 hls-relay 'Invalid timestamps' at every C6 changeover (C5: 27-35 at every one).

Also correct my 06:15 addendum in `U56-answer-5.md`. It said "audio not overlapped on live", but I had measured AFTER the
relay's timestamp repair. The relay stderr shows the rewind at every C5 changeover, with length equal to the trim.
You were right.

## C6 live changeovers (coordinator, OBSERVED; worker stderr order + emitted packet PTS in emission order)
| changeover | first outgoing EOS | mux-tail-armed vs rebase-ref | drain | result |
|---|---|---|---|---|
| education r1 07:20:34 | VIDEO (1/2) | armed before ref, released waited=0.031 | 0.438 s | CLEAN v0.033 a0.021 |
| public r1 07:36:04 | VIDEO | same | 0.703 s | CLEAN v0.033 a0.028 |
| government r1 07:36:04 | VIDEO | same | 0.438 s | CLEAN v0.033 a0.028 |
| **education r2 07:50:36** | **AUDIO (1/2)** | same, released waited=0.062 | 0.438 s | **HOLE v0.733 a0.068** |

The failing one, verbatim (education worker stderr ~line 89265):
```
outgoing EOS observed stream=audio (1/2 stream(s))
stage=mux-tail-armed pads=sink_66 target={'sink_66': 2667999999999} cutoff=2667300000000 reload_id=2
rebase-reference reload_id=2 ... ends=[video=2667.300,audio=2668.000] switch_running_time=2667.300
switch-at-shorter-leg ... trimmed=audio:0.700
rebase-drain-wait pads=sink_66=6 ; outgoing EOS observed stream=video (2/2) ; rebase-drain-drained waited=0.438s
switching-selector ; mux-tail-wait seen={'sink_66': 2667978666666} ; holds-released ; selector-handoff-confirmed
retiring-tail-release-entered ; retiring-tail-released video ; retiring-tail-released audio ; old-tail-detached
new-leg-first-buffer audio ... running_time=0 ; new-leg-selector-first-buffer audio pad=sink_3 running_time=2667.300
new-leg-first-buffer video ... ; new-leg-selector-first-buffer video pad=sink_3 running_time=2667.300
rebase-observer-disarmed pad=sink_66 stream=audio arrived=14 ; old-leg-disposed ; committed elements=52
mux-tail-released waited=0.062s arrived=True seen={'sink_66': 2668021333333}
```
Emitted (fixtures\C6-education-0750\seg000001330..1335.ts, emission order, emitted = running + 1.400):
video seg1333 `2668.700000 -> 2669.433322` (+0.733, i.e. running 2667.300 -> ~2668.033 = the old audio end + 1 frame);
audio seg1333 `2668.674656 -> 2668.742656` (+0.068 step, no backward).

C5 for reference: the EOS order did NOT predict the result there (1/17 clean, both orders holed). On C6 it separates
3/3 vs 1/1. The sample is small, so treat it as the lead, not as proof.

## Work
1. Explain the audio-EOS-first path on C6 bytes. Why is incoming video between the switch point and the old audio
   end still lost, and where does the 0.068 s audio step come from, when the old audio tail no longer airs? Candidates
   in the log: the mux-tail target is the old audio end (2668.000), and the mux-tail-wait / release happens after the
   handoff, so the mux's audio pad may hold back the incoming AUDIO until 'arrived'. With `sync-streams`, the video
   may be held behind audio, or dropped behind it.
2. RED: force audio-EOS-first on the filesrc harness (an outgoing clip whose AUDIO ends before its video's EOS
   reaches the selector, or pacing). It must reproduce video hole ~= spread plus a small audio step, on C6 bytes
   77251b70, with the switch-at-shorter-leg AND mux-tail lines in the transcript, emission-order verdicts. Then fix
   and GREEN 2/2 in BOTH orders. Video-first must stay clean (it is clean on live now; do not regress it).
3. Stage `staging\U56e\` from LIVE bytes (base 77251b70). Report Part VI, plain English first, receipt last. No
   station action. A C6 8 h rung is live.

## Addendum 08:06 - 5th C6 changeover, plus the audio join step
government r2 08:05:03: first_eos=video -> CLEAN video 0.033; relay rewind 0. Tally: video-first 4/4 clean,
audio-first 0/1.
Audio max step at the JOIN on the CLEAN C6 changeovers: 0.021 (education 07:20), 0.028 (public 07:36), 0.028
(government 07:36), 0.035 (government 08:05). C5 and earlier: 0.021. The U57 audio bar in
capture_emitted_hls_audio_proof is 0.030, so a loudness window spanning a join like 08:05 would FAIL. Your
harness GREEN showed `minstep=+0.006656s @ 3602.560->3602.567`: the incoming audio's first frame is not on the
outgoing frame lattice. Find and close this too (a join step <= 0.030 s, ideally ~0.021 s), without resampling or
synthetic audio.
CORRECTION (08:07): the U57 audio bar is `_AUDIO_HOLE_SECONDS = 0.05` (capture_emitted_hls_audio_proof.py:694), not
0.030. The 0.028-0.035 s join steps pass it. Treat the join step as secondary: report it, and fix it only if cheap.
Priority is the audio-EOS-first video hole.

## Addendum 08:17 - 2nd audio-EOS-first changeover: HOLE with a BIGGER audio gap
public 08:15:29: first_eos=audio, trimmed=audio:0.576 -> video hole 0.733 s AND audio gap 0.213 s (an audible dropout).
Relay rewind 0. Copies: fixtures\C6-public-0815\seg000002077..2082.ts. Tally on C6: video-first 4/4 clean,
audio-first 0/2 (audio gap 0.068 then 0.213). On C5, audio never had a gap. So C6's mux-tail fence creates an AUDIO
dropout on the audio-first path. This is now the top priority.
- 08:35 government first_eos=audio -> HOLE v0.733 a0.137 (audio-first now 0/3; video-first 5/5 incl. education 08:20)
