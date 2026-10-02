## Coordinator verdict - C11 8h rung (2026-09-27 22:37:28 -> 2026-09-28 06:37:28, -06:00): FAIL on 1 real defect

Bytes: C11 = automation 7b4e4f18, daemon 0d723536, preparer b19b7a43, engine 8a3722c9, graph 309ffac7, pipeline e3d7767a
(installed 22:29:05). Service pid 28580 throughout - no restarts, no worker exits.

- verify: 44/45 OK. #19 (01:53:14) public caption_decode_back FAIL, classified no-speech pre-roll at the head of the
  Sep 8 Council recording (evidence VERIFY-19-NOTE.md; confirmed by #20 PASS). Excused, counted.
- loudness: 16/16 PASS.
- changeovers: 51 scored, 50 CLEAN, 1 HOLE.
  - HOLE: public 06:24:14 reload_id=16, switch-at-shorter-leg bound EXCEEDED spread=3.133 s (video_end 28424.333,
    audio_end 28427.467), fail-open no trim -> 2.000 s video gap between seg000014211 and seg000014212, audio
    continuous. Pre-switch chain-in video ~25-27 fps for ~15 s, audio nominal. Same signature as C9 government
    19:15 (4.148 s). Leg = 2183.4 s (plan accepted 05:42:29: 595 s Sep 8 Council tail + Senior Citizens Advisory
    Board June 0-~1588 s, i.e. a mid-file slice end, not end of file). Fixture: fixtures\C11-public-0624.
  - All other 50: spread 0.576-0.824 s, trimmed, video_max 0.033 s, relay rewinds 0.
  - Coordinator miss: changeover watch v1 printed CLEAN for 06:24 (intra-segment steps only; the gap straddled a
    segment boundary). Watch v2 (cross-segment check) GREEN on the fixture (HOLE 2.000 s), live from 06:28.
    Worker logs confirm no other C11 changeover exceeded the bound, so v1's blind spot hid only this one.
- slate: none (0 'plan EOS' lines on any channel). Short legs 460-667 s on education handled in time.
- preparation: repeat preps of already-seen titles 198-398 s all night (U61 case); tightest margin ~4.8 min
  (government 04:57:48). All in time.
- observations -> POST-BETA10-BACKLOG.md: caption tap lag up to ~12 s under conform load; decode-back cannot tell
  room tone from speech; Aug 11 Council leveling misses the 4-min gate in the preparer (on-air loudness PASS).

Milestones on C11: 30 min, 2 h, 4 h clean. 8 h FAILS on the 06:24 hole.
Recurrence: 2 fail-open holes in ~110 changeovers (C9 + C11). Mechanism still unknown; C12 carries U59 round 4's
detector (ingress-rate WARN with leg/offset/queue/QoS detail) to capture the next one.
Next: install C12 (U61 + U59r4), confirmation rung on C12; brief U59 round 5 with this second fixture.

Rung tool END 06:38:07: 'verdict FAIL verifies 45 loudness 16 failures 1' - the tool's 1 failure is verify #19 (excused above); the tool does not score changeovers, so the 06:24 hole is the coordinator's finding on top.
