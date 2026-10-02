# U56 round 5 - coordinator redirect (05:48): your is-live RED is not the live station's path

Read `questions\U56-answer-4.md` again, including its three addenda (04:21, 05:16). You may not have seen them.

## 1. Live program legs are NOT live sources
Installed `civiccast\egress\gst\bridge.py:214-247`: "A pre-conformed file segment is a `filesrc`". Every live changeover
tonight is a prepared plan file, so the source is `filesrc ! decodebin`. The engine's own selector comment,
`engine.py` ~1633, says: "The program legs are non-live (filesrc->decodebin): their running time is segment-derived".
Your K/`--incoming-live` RED uses `is-live=True` test sources, a different path. It also prints no
`switch-at-shorter-leg` line, and the live station prints one at EVERY changeover. Keep it as a note. It is NOT the RED
for this unit.

## 2. Live facts to explain (7 changeovers on C5)
- The outgoing video airs fully to the switch point (the shorter leg's end).
- The incoming leg's video is missing from the switch point until about the OLD AUDIO END. Examples: public
  04:16 1798.400 -> ~1799.2 (old audio end 1799.147); government 04:19 1799.433 -> ~1800.05 (old audio end 1800.000).
  The incoming audio is continuous.
- The selector logged `new-leg-selector-first-buffer stream=video running_time=<switch point>`. That is a sink-side
  probe, so the frames reached the selector's INPUT.
- 1 of 7 was clean (public 05:15, trimmed 0.577), so it is a race.

## 3. Hypothesis to test first (coordinator, from the installed code; not proven)
`_SELECTOR_PROPS` = `sync-streams=True, sync-mode=0 (active-segment), cache-buffers=False, drop-backwards=True`.
With `drop-backwards=True`, input-selector drops buffers whose running time is behind the last running time it
output. If the video selector's notion of "last output" for the retiring pad reached the OLD AUDIO END, then every
incoming video buffer below that point is dropped as "backwards", and video resumes at the old audio end. That is
exactly the live signature. Ways it could reach there:
- the retiring video pad's segment `stop`/`position`;
- a GAP event;
- videorate's closing-duplicate stretched to the leg's end;
- `sync-streams` active-segment carrying the old AUDIO segment's position.

The race would be whether that advance lands before or after the handoff.

## Work
1. Instrument, on a real worker with a `filesrc` incoming leg (the live path), the video selector's src pad. Log
   first-out running time after the switch, any drop, and the retiring video pad's last segment/position/GAP events.
   Confirm or kill the hypothesis. If the harness filesrc path stays clean, find what differs from live on THAT path.
   Candidates: real-time pacing of the whole pipeline (live sinks sync to the clock); the live output branch; the
   caption injector.
2. RED on C5 bytes (f1883d04) on the filesrc path. Fix without synthetic frames. GREEN, 2/2, U57 packet-PTS method.
   The RED transcript MUST show the `switch-at-shorter-leg` line.
3. Stage `staging\U56d\` from LIVE bytes (base f1883d04). Report Part V, plain English first, receipt last. No
   station action.

## Addendum 06:15 (coordinator, OBSERVED) - live emitted AUDIO is in order and not overlapped
> **RETRACTED — see the Correction at the end of this file (round 6, 2026-09-27).** The measurement
> below is real but it was taken on the relay's *repaired* output, so its conclusion is wrong: the
> C5 engine DID air the retiring audio tail, rewound. The heading and the body are left as written,
> for provenance.
fixtures\C5-public-0416, packet PTS in EMISSION order (no sorting): seg898 audio 94 packets, seg899 128 packets,
0 backward steps. seg899 spans 1799.416->2125.322 = 2.709 s / 0.02133 s = ~127 frames, so no extra or overlapping
audio. The old audio tail past the switch is NOT emitted on live. If your audio fence sees no buffers, the retiring
audio is being stopped elsewhere, which is fine. Do not "fix" audio. The defect is video only: incoming video from
the switch point to ~old audio end never airs.

---

## Correction to the 06:15 addendum (coordinator, round 6, 2026-09-27)

The coordinator retracted the addendum above, in his own words (round-6 work order):

> "Also correct my 06:15 addendum in `U56-answer-5.md`. It said 'audio not overlapped on live', but I had
> measured AFTER the relay's timestamp repair. The relay stderr shows the rewind at every C5 changeover,
> with length equal to the trim. You were right."

**What survives and what falls.**

- **Falls:** the conclusion "live emitted audio is in order and not overlapped, so the C5 engine does not air
  the retiring audio tail." The packet PTS in `fixtures\C5-public-0416` *are* a clean lattice — but those
  files are the **hls-relay's** output, written **after** the relay repaired the non-monotonic timestamps it
  was fed. A repair that succeeds leaves no trace in the segments; it leaves it in the relay's stderr.
- **Stands, and is now the corroborating evidence:** the C5 station **did** air the retiring audio tail past
  the switch point and then rewound. The direct measurement is the relay's own stderr:
  **27–35 `Invalid timestamps` at every C5 changeover**, and **0** at every C6 changeover once the round-5
  mux-tail fence was installed. The rewind's length is the trim.
- **Consequence for round 5's conclusions:** the harness RED (clean video, one backward audio step of exactly
  the trim, `−1.038667 s`) is **not** a harness-only symptom that live does not share. Live shared it, and the
  relay hid it in the fixtures. The two faces — live's video hole and the harness's audio rewind — remain one
  commit-ordering defect; what changes is that the audio half is now measured on live too.

**Not claimed by this correction:** the *magnitude* of the live rewind has not been read off a relay log by me
— the 27–35 count and the "length equal to the trim" are the coordinator's figures, carried here as his
statement, not as my own observation.
