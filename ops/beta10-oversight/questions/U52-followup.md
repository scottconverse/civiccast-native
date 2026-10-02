# U52 follow-up (coordinator 18:14) - it is not only education; preparation time blew up on all three channels

Content-reload source preparation times today (control_plane-app.log):
17:23 gov 6.3 s | 17:35 pub 137.9 s (3 seg) | 17:44 pub 74.0 s (3 seg) | 17:46 edu 6.4 s | 17:52 gov 11.7 s |
17:59 edu 112.2 s | **18:05 pub 341.5 s** | **18:10 edu 224.5 s** | **18:12 gov 485.8 s**.
Government: automation "rollover horizon for government is past due by 192s / 253s / 314s but the seamless reload is
still settling; waiting" (18:10-18:12), reload accepted 18:12:37 -> government was ~5 min late too. verify-27 (18:12:39)
government caption FAIL: last worker caption receipt 316 s old (what aired on government 18:07-18:12 - held last
frame, slate, or plan-EOS hold? say which, from the logs).
CPU during the window: host load 87 % at 18:12 (coder test suites were also running on this box - quantify whether
preparation is CPU-starved: ffmpeg prep command, its realtime factor at idle vs now).
Add to the U52 diagnosis: (a) what makes preparation take 100-500 s now vs 6 s earlier (first-airing items? loudness
2-pass? concurrency of 3 channels preparing at once?); (b) whether preparation is started early enough that even a
500 s prep lands before the item is due. The fix must make a slow preparation invisible on air.

Addendum 18:20 - loudness-10 (rung 8h-post-u47): emitted-HLS timestamp jumps AT the changeovers:
government segment 73 PTS delta 361006 ticks (4.01 s) vs expected 87000 (0.97 s), capture started 18:10:28 -> ~18:12:54,
i.e. at the late 18:12:37 government reload; public segment 22 delta 198960 (2.21 s) vs 147000 (1.63 s), capture
started 18:06:07 -> ~18:06:50, at public's changeover after its 341 s prep. rung_check labelled both INSTRUMENT_ERROR,
but they are station timeline jumps. Include them in the diagnosis: the late/slow reload path skips timeline.

Addendum 18:31 - contrast case: public 18:25:23 automation "issued a seamless plan rollover ... the live plan ends in 685s"; prep 283.3 s done 18:30:11; reload accepted switch_at_end_of_current=True -> no slate. So the normal rollover path gives ~11 min of lookahead and absorbs a slow prep; the education 18:06 path ("a scheduled program is due", 0.7 s-tail rule) prepared AT due time with no lookahead. Find why education/government took the at-due path.
