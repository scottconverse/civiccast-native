# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T001616Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 3.12 h of 2
- egress probes: 7, failing: 6
- heartbeats: 108
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 13376): cpu%= cpu_seconds_total=0.671875 rss_mb=23.8
- python (pid 8344): cpu%= cpu_seconds_total=48.046875 rss_mb=5026.8
- python (pid 40032): cpu%= cpu_seconds_total=63.046875 rss_mb=2498.5
- python (pid 44056): cpu%=16.12 cpu_seconds_total=9258.828125 rss_mb=70.5
- python (pid 47368): cpu%= cpu_seconds_total=15.703125 rss_mb=6785.3

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=, pid=, relaunches_total=4, relaunched_this_cycle=False, last_errors=No valid source plan is available; generated fallback slate.
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39468, relaunches_total=6, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4668; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41112, relaunches_total=4, relaunched_this_cycle=True, last_errors=
