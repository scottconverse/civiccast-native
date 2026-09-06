# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T224614Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 1.62 h of 2
- egress probes: 4, failing: 3
- heartbeats: 105
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 41080): cpu%= cpu_seconds_total=422.890625 rss_mb=389.6
- python (pid 44056): cpu%=15.38 cpu_seconds_total=8559.96875 rss_mb=438.3
- python (pid 46652): cpu%= cpu_seconds_total=69.15625 rss_mb=337.6
- python (pid 48020): cpu%= cpu_seconds_total=118.359375 rss_mb=339.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=57171; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=48020, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=34904; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46652, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=18807; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=41080, relaunches_total=3, relaunched_this_cycle=True, last_errors=
