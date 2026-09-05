# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T191614Z

- soak start (UTC): 2026-09-05T18:40:36.1571827Z
- elapsed: 0.59 h of 2
- egress probes: 2, failing: 2
- heartbeats: 98
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 37280): cpu%= cpu_seconds_total=0.21875 rss_mb=22.9
- python (pid 25260): cpu%=289.97 cpu_seconds_total=9441.625 rss_mb=988.5
- python (pid 25916): cpu%= cpu_seconds_total=839.09375 rss_mb=825.2
- python (pid 37688): cpu%= cpu_seconds_total=855.796875 rss_mb=829.2
- python (pid 41188): cpu%=57.57 cpu_seconds_total=1230.609375 rss_mb=362.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=8887; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25916, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=16714; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37688, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=121931; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=41188, relaunches_total=0, relaunched_this_cycle=False, last_errors=
