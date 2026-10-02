# U59 round 3 - find why the retiring leg's video ingress fell to 23.00 fps for its last 21 s

Round 2 ACCEPTED (coordinator 21:58): the pass is not the fix, the ~0.7 s baseline is the 720p per-piece pad, the
government 19:15 freeze is 4.4 s of video media that never arrived (chain-in: in at 23.00 fps for the last 21.0 s).
Decision: the U59 preparer pass will be REVERTED to the C9 preparer (aafb0b5d) at the next install (coordinator
stages it; you do not need to fix the %g tail guard).

## Work (no station action; keep runs low priority and short; an 8 h rung is live until ~04:52)
1. Is the 23 fps stretch IN THE MEDIA? Scan the Council conform in `C:\ProgramData\CivicCast\data\egress\conform-cache\`
   (find the entry whose media duration matches the 14998.6 s source
   `...\uploads\lpmrot-02-city\City_Council_Regular_Session_-_September_8__2026.mp4`) and the source itself for video
   packet-pts gaps and low-rate stretches (any window where video < 29.5 pkts/s, or any gap > 0.1 s). Report each
   stretch's position and length. Then locate the retiring leg's in-point: the leg ran 2169.4 s and followed the
   1800 s legs of the same title that aired from 14:28 onward (control_plane lines "rollover lead for government ...
   City Council Regular Session - September 8, 2026.mp4 (1800s ...)" and the 18:28 "(592s ...)"), so work out which
   source offset the leg's last 21 s came from, and whether a stretch sits there.
2. If the media is clean there: test contention. Replay the retiring shape through your run-leg.py harness at
   production caps with a CPU load running (e.g. one ASR-like busy process per core pair, or the real caption tap's
   faster-whisper on a fixture), and see whether chain-in video drops below 30 fps while audio stays nominal.
3. Whichever it is, say what the station should do: if the source has no picture there, holding the last frame is
   faithful and the fail-open bound is right (say so); if it is contention, propose the smallest guard (priority,
   queue sizing, decoder threading) with a RED/GREEN.
Report under "Round 3" in reports\U59.md, plain English first, receipt last.
