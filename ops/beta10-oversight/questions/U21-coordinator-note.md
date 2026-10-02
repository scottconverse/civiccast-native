# U21 - coordinator note added while you were running (2026-09-25 01:07 MDT)

Read this before finalizing section A/C of your report.

1. The LIVE relay argv (captured via the elevated helper, `evidence\government-relay-freeze-0104\relay-cmdlines.txt`):
   `ffmpeg -y -fflags +genpts -analyzeduration 6000000 -probesize 6000000 -i udp://127.0.0.1:<port>?overrun_nonfatal=1&fifo_size=50000000 -map 0:v:0 -map 0:a:0 -c:v copy -c:a aac -f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list+program_date_time+independent_segments ...`
   Video is COPIED (keeps the input's timestamps, including any jump or ffmpeg discontinuity correction) while audio
   is RE-ENCODED through the AAC encoder (whose output timestamps follow the decoded-sample count/filter timeline).
   Test explicitly whether an input PTS jump (worker restart; slate entry) shifts video by the jump while audio stays
   continuous - that alone would produce a constant a-v offset equal to the jump for the relay's lifetime.
2. Second live case, government 01:03-01:06: after a program->program deferred switch (reload_id=3, elements=52,
   symmetric diagnostics) the relay stopped writing while the worker kept producing; the daemon's self-heal DID
   restart the relay at 01:04:34 (new pid, argv above) but the new relay wrote nothing until the coordinator's full
   channel restart at 01:06 (fresh at 01:06:32, a-v 0.005). Evidence: `evidence\government-relay-freeze-0104\`.
   Explain why a freshly restarted relay can sit without writing while the engine output is flowing (probe/
   analyzeduration on a mid-stream join? `append_list` with a stale playlist? stale segments of older sessions sit
   in the HLS dir: seg000013301 (10:46), seg000014671-77 (08:13)).
