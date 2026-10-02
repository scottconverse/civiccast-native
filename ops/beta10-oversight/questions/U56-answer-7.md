# U56 round 6 - coordinator redirect (08:40): stop the is-live arms; test this hypothesis on filesrc

C6 live tally: video-EOS-first 5/5 CLEAN; audio-EOS-first 0/3. Those three had video 0.733 s holes and audio
DROPOUTS of 0.068 / 0.213 / 0.137 s. C5 never dropped audio, so C6's mux-tail fence is involved. Your T/U arms use
clock-timed legs (`rebase_new_leg=False`), which is not the live path again. Stop them.

## Coordinator hypothesis (from the live log order; not yet proven)
Audio-first live (education 07:50, public 08:15):
```
outgoing EOS observed stream=audio (1/2)               <- the retiring AUDIO has fully passed; its tail is already gone
stage=mux-tail-armed pads=sink_66 target=<old audio end> cutoff=<switch point>
... switching ... new-leg-selector-first-buffer audio running_time=<switch point>
stage=mux-tail-wait seen=<just below target>
stage=mux-tail-released waited=0.05-0.06s arrived=True seen=<target + 1 audio frame>
```
When the retiring audio EOSes BEFORE the fence is armed, no retiring audio buffer is left to arrive at the mux pad. The
fence (armed on `sink_66`, dropping by running time > cutoff until something reaches `target`) then sees the NEW leg's
audio. The new leg starts at running time = cutoff (the switch point), so its first ~spread of audio is dropped as if
it were the retiring tail. The fence is released only when a NEW buffer reaches the old audio end. That is the audio
dropout. The video hole of the same length follows from the mux/selector keeping the streams in sync. In the
video-first case the retiring audio is still in flight when armed, reaches the target itself, and releases the fence
before any new-leg buffer shows up, so it is clean.

## Work
1. Prove or kill this. On the FILESRC harness, force audio-EOS-first by delaying only the outgoing VIDEO EOS: for
   example, a probe on the outgoing video subchain that holds the EOS event for ~300-800 ms, or pacing the last
   video buffers. The RED on C6 bytes (77251b70) must show `first EOS = audio`, the mux-tail lines, and video hole
   ~= spread plus an audio dropout, in emission order.
2. Fix. The fence must only ever drop buffers of the RETIRING leg. Tell them apart by origin (pad/leg identity,
   segment seqnum, or a leg tag set on the retiring leg's buffers), never by running time alone. If the retiring
   audio has already EOS'd or reached the target when the fence would be armed, do not arm it (or release it at
   once). GREEN 2/2 in BOTH orders (audio-first and video-first), no synthetic frames.
3. Stage `staging\U56e\` from LIVE bytes (base 77251b70). Report Part VI, plain English first, receipt last. No
   station action.

## Addendum 08:47 - picture-first public 08:45:26: CLEAN by 0.070 bar but video max 0.067 s (ONE dropped frame) + audio join 0.037. U57 VIDEO_HOLE bar is 2 x frame interval (0.0667) so this is at the edge. GREEN must show video max 0.033 at the join in both orders.

## CORRECTION 09:16 (coordinator, OBSERVED) - EOS order is NOT the discriminator
government r4 09:14:28 (worker elements=61):
```
outgoing EOS observed stream=video (1/2)       <- VIDEO first
mux-tail-armed target=7700.979 cutoff=7700.333 ; rebase-reference ends=[video=7700.333,audio=7700.979]
outgoing EOS observed stream=audio (2/2) ; rebase-drain-drained waited=0.641s
mux-tail-wait seen=7700.957 ; new-leg-selector-first-buffer video/audio running_time=7700.333
rebase-observer-disarmed arrived=18 ; committed elements=61 ; mux-tail-released waited=0.062s seen=7701.000
```
-> HOLE: video 7701.733->7702.467 emitted (running 7700.333 -> 7701.067), audio DROPOUT 0.229 s at emitted
7701.781->7702.011 (running 7700.381 -> 7700.611). Copies: fixtures\C6-government-0914\seg000003846..3851.ts.
C6 tally: 7 clean, 4 HOLE (3 audio-first, 1 video-first). My 08:40 hypothesis ("fence armed after the retiring audio
has EOS'd") is at best partial: here the retiring audio was still in flight when the fence was armed. Note that
mux-tail-released `seen` is always target + ~1 audio frame, in CLEAN ones too (e.g. education 07:20 seen 868.757
vs target 868.736). Compare CLEAN and HOLE runs on what reaches the mux audio pad between arm and release (origin
of each buffer), and on what the VIDEO path does in that window. The C6 fixtures (0750, 0815, 0914 HOLE) plus a
CLEAN one are your live ground truth. Fix whatever drops NEW-leg media; RED must reproduce on filesrc.
