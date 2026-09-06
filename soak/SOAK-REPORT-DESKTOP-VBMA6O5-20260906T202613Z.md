# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T202613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 18 h of 2
- egress probes: 37, failing: 37
- heartbeats: 148
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 44632): cpu%= cpu_seconds_total=3.703125 rss_mb=346.4
- python (pid 38124): cpu%= cpu_seconds_total=13.84375 rss_mb=767.5
- python (pid 45040): cpu%=19.69 cpu_seconds_total=21129.03125 rss_mb=1993.2
- python (pid 45856): cpu%= cpu_seconds_total=21.578125 rss_mb=443.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45856, relaunches_total=36, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38640, relaunches_total=35, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4739; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=12832, relaunches_total=36, relaunched_this_cycle=True, last_errors=
