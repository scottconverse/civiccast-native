# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T035612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 1.5 h of 2
- egress probes: 4, failing: 4
- heartbeats: 115
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 46760): cpu%= cpu_seconds_total=0.046875 rss_mb=26.6
- python (pid 14136): cpu%= cpu_seconds_total=15.1875 rss_mb=555.5
- python (pid 18236): cpu%= cpu_seconds_total=9.453125 rss_mb=777.3
- python (pid 41316): cpu%= cpu_seconds_total=13.59375 rss_mb=554.4
- python (pid 45040): cpu%=15.62 cpu_seconds_total=7965.375 rss_mb=1826.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=8257; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14232, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=88580; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31848, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=21978; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=22760, relaunches_total=3, relaunched_this_cycle=True, last_errors=
