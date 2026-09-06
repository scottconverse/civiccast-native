# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T152612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 13 h of 2
- egress probes: 27, failing: 27
- heartbeats: 138
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 26416): cpu%= cpu_seconds_total=24.09375 rss_mb=767.5
- python (pid 37908): cpu%= cpu_seconds_total=14.453125 rss_mb=767
- python (pid 40608): cpu%= cpu_seconds_total=13.703125 rss_mb=777.8
- python (pid 45040): cpu%=22.79 cpu_seconds_total=16753.1875 rss_mb=1827.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2959; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26416, relaunches_total=26, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2897; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26856, relaunches_total=25, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39972, relaunches_total=26, relaunched_this_cycle=True, last_errors=
