# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T125613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 58.5 h of 2
- egress probes: 118, failing: 118
- heartbeats: 229
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 5336): cpu%= cpu_seconds_total=19.3125 rss_mb=765.1
- python (pid 38060): cpu%= cpu_seconds_total=4.359375 rss_mb=774.4
- python (pid 45040): cpu%=31.99 cpu_seconds_total=60403.359375 rss_mb=1852.1
- python (pid 47792): cpu%= cpu_seconds_total=39.09375 rss_mb=726.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=5336, relaunches_total=117, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47792, relaunches_total=116, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3633; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9572, relaunches_total=116, relaunched_this_cycle=True, last_errors=System.Object[]
