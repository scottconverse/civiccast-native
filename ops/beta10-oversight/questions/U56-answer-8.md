# U56 round 7 - C7 (U56e) is LIVE; now the 0.733 s VIDEO hole, with a new live clue

C7 = staging\U56e (engine.py b4c1fdff) installed 2026-09-27 09:35:11, service pid 34956, all 3 ON_AIR 09:40.
Rung 8h-post-c7 is running. Coordinator audit of round 6: ACCEPTED for live trial (log 09:34).

## Coordinator re-run of your round 6 (OBSERVED, evidence\coord-r6-rerun-0945.txt; out_shortv.ts, filesrc)
| tree | arm | video max | audio max | verdict |
|---|---|---|---|---|
| fix8 (C6) | AF in_avoff700 | 0.733 | 0.072 (dropout) | HOLE |
| fix13 (C7) | AF in_avoff700 | 0.733 | 0.041 | HOLE (video only) |
| fix8 (C6) | VF incoming.ts | 0.033 | 0.029 | ok |
| fix13 (C7) | VF incoming.ts | 0.033 | 0.041 | audio over harness 0.030, under U57 0.05 |
`mux-tail-released-by-segment` fired in both C7 arms. No rewind in either of my C7 runs, but YOUR C7 AF run showed
audio back=1 at -0.093344 s (3602.560 -> 3602.467 = retiring audio aired 0.093 s past the switch). That is racy.
Explain it: on live it would be a small C5-style rewind (relay 'Invalid timestamps' ~4).

## The live clue (coordinator, OBSERVED from gst-worker.stderr.log, all 14 C6 changeovers)
`new-leg-first-buffer stream=video ... pts=` of the INCOMING leg, against the result:
- pts 0.700 or 0.401 (incoming file's picture and sound start together): **4/4 CLEAN**
  (education 07:20, public 07:36 [0.401], government 08:05, government 09:29)
- pts 0.000: **4 HOLE / 6 CLEAN** (HOLE: education 07:50, public 08:15, government 08:35, government 09:14;
  CLEAN: education 08:20, 08:50, 09:20; public 08:45, 09:15; government 07:36)
Prepared files (`C:\ProgramData\CivicCast\data\egress\<ch>\prepared\*\segment-*.ts`) very often have the first VIDEO
packet 0.1 - 2.0 s AFTER the first audio packet (e.g. public b44a96ad9430 v0=3.144 a0=1.400). Your harness clip
in_avoff700.ts is the same shape (v0=2.121, a0=1.400) and its 0.733 video gap you called "fixture geometry".
But on live the hole is ALWAYS 0.733 s, whatever the incoming file's offset, and most picture-late incoming files
air CLEAN. So live is not simply "no picture in the source yet".

## Work
1. Explain the live 0.733 s video hole. Why exactly 0.733 (22 frames at 30 fps; 0.700 + 1 frame?) every time,
   independent of trim (0.576-0.759) and of the incoming file's A/V offset? What fills picture-late starts in the
   CLEAN cases (videorate duplicate? selector? the mux's 0.700 start offset)? What makes the HOLE ones differ?
   Use the four HOLE fixtures (fixtures\C6-education-0750, C6-public-0815, C6-government-0914, C5-*) and the
   prepared files. Build a RED on C7 bytes (b4c1fdff) on filesrc from a clip whose offset matches a real HOLE
   changeover's incoming file, and prove the hole is the ENGINE's (the source had picture to show, or the station
   is supposed to hold a frame), not the clip's.
2. Explain the -0.093 s rewind in your C7 AF run, and make it impossible.
3. Fix, GREEN 2/2 on filesrc with a picture-late incoming clip AND an aligned one, no synthetic frames beyond what
   the station already does in CLEAN cases. Stage `staging\U56f\` from LIVE bytes (base b4c1fdff). Report Part VII,
   plain English first, receipt last. No station action. Live C7 changeovers will be sent to you as addenda.

## Addendum 09:47 - first C7 changeover: government 09:40:58 (reload_id=1, elements=61, first_eos=audio)
HOLE video 0.225 s (seg000000134 at +0.600), audio max 0.035 s (no dropout), relay rewind 0. Incoming pts=0.183
(new-leg-first-buffer both streams). trimmed=audio:0.733. mux-tail-wait seen=269.312 target=269.333; then
mux-tail-released waited=0.063 arrived=True seen=269.355 -- NO `mux-tail-released-by-segment` line, so the round-6
segment release did not fire; the arrival release did. Video hole is 0.225, not 0.733: a new size. Copies:
fixtures\C7-government-0940\seg000000133..135.ts. Explain this one too.

## Addendum 09:55 - C7 changeover #2: education 09:53:07 (reload_id=1, elements=52, first_eos=audio)
HOLE video 0.124 s (seg000000500 at +1.467), audio max 0.037 s (no dropout), relay rewind 0. Incoming pts=0.481.
trimmed=audio:0.667. This time `mux-tail-released-by-segment` DID fire (incoming_start=0.481 held_start=0.572),
then mux-tail-released waited=0.032. Copies: fixtures\C7-education-0953\seg000000499..501.ts.
C7 so far: 2/2 audio clean, 2/2 video holes but SMALLER and VARIABLE (0.225, 0.124) vs C6's fixed 0.733.
- 10:00 government 09:59:03 CLEAN v0.033 a0.028 relay 0, first_eos=audio (an audio-first CLEAN - first ever on C6/C7).
  (09:59 incoming pts=0.700 = A/V-aligned file: fits the clue, aligned incoming now 5/5 CLEAN across C6+C7.)
- 10:07 public 10:06:29 CLEAN v0.033 a0.029 relay 0, first_eos=video.
- 10:15 government 10:13:54 CLEAN v0.033 a0.024 relay 0, first_eos=audio.
- 10:25 education 10:23:11 HOLE video 0.515 s (seg000001399 at +1.367), audio 0.033 (clean), relay 0, first_eos=audio,
  incoming pts=0.000, segment release fired (incoming_start=0 held_start=0.481). Copies fixtures\C7-education-1023\
  seg000001398..1400.ts. Likely incoming file: education\prepared\6f6ac8b455ff\segment-0001.ts (prepared 10:11:43),
  first video 2.595 vs first audio 1.400 = picture 1.195 s late. The hole (0.515) is NOT the file's offset (1.195).
  C7 tally: 3 CLEAN (all A/V-aligned incoming, pts 0.700) / 3 video holes 0.225, 0.124, 0.515 (all picture-late incoming,
  pts 0.000-0.481); audio clean 6/6; relay rewinds 0.
- 10:44 public 10:42:42 HOLE video 0.733 s (seg000001986 at +0.567) - the full C6-size hole is back on C7 - audio 0.027
  (clean), relay 0, first_eos=video, incoming pts=0.000, segment release fired (incoming_start=0 held_start=0.700).
  Likely incoming file public\prepared\3c214e0e94a5\segment-0001.ts (prepared 10:31): picture 1.376 s late.
  Copies fixtures\C7-public-1042\seg000001985..1987.ts. C7 tally: 3 CLEAN (aligned) / 4 holes (picture-late)
  0.225, 0.124, 0.515, 0.733; audio 7/7 clean; relay 0.
- 10:45 government 10:43:56 CLEAN v0.033 a0.040 relay 0 first_eos=audio.
- 10:54 education 10:53:08 CLEAN v0.033 a0.040 relay 0 first_eos=video.
  (10:53 incoming pts=0.000, i.e. picture-late - the first CLEAN picture-late change on C7; C7 picture-late now 1 CLEAN / 4 HOLE.)
- 11:14 public 11:12:40 CLEAN v0.033 a0.032 relay 0 first_eos=video.
  (11:12 incoming pts=0.000 picture-late; C7 picture-late now 2 CLEAN / 4 HOLE; aligned 4/4 CLEAN.)
- 11:15 government 11:13:54 CLEAN v0.033 a0.025 relay 0 first_eos=audio incoming pts=0.700.
- 11:24 education 11:23:09 CLEAN v0.033 a0.041 relay 0 first_eos=video incoming pts=0.000.
- 11:44 public 11:42:38 CLEAN v0.033 a0.032 relay 0 first_eos=video incoming pts=0.000.
- 11:45 government 11:43:51 HOLE video 0.733 s (seg000003821 at +1.867), audio 0.035 clean, relay 0, first_eos=audio,
  incoming pts=0.000 (picture-late), segment release fired (incoming_start=0 held_start=0.700). Copies
  fixtures\C7-government-1143\seg000003820..3822.ts. C7 tally: 9 CLEAN / 5 HOLE; aligned 5/5 clean; picture-late 4/9
  clean; audio 14/14 clean; relay 0. Note: both 0.733 holes on C7 (public 10:42, government 11:43) had held_start=0.700
  and incoming_start=0 at the segment release; the smaller holes did not (09:53 held 0.572/in 0.481; 10:23 held 0.481/in 0).
