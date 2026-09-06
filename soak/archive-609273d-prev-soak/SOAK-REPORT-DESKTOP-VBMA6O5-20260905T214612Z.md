# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T214612Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 0.62 h of 2
- egress probes: 2, failing: 1
- heartbeats: 103
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 36184): cpu%= cpu_seconds_total=34.140625 rss_mb=3535.8
- python (pid 38092): cpu%= cpu_seconds_total=15.859375 rss_mb=3537.6
- python (pid 39764): cpu%= cpu_seconds_total=82.875 rss_mb=3560.7
- python (pid 44056): cpu%=17.69 cpu_seconds_total=7982.453125 rss_mb=966.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=77374; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39764, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=41844; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36184, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=41997; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33876, relaunches_total=1, relaunched_this_cycle=True, last_errors=
