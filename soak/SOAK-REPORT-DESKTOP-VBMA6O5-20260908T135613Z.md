# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T135613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 59.5 h of 2
- egress probes: 120, failing: 120
- heartbeats: 231
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 32680): cpu%= cpu_seconds_total=0.015625 rss_mb=25.3
- python (pid 20084): cpu%= cpu_seconds_total=33.140625 rss_mb=723.6
- python (pid 31080): cpu%= cpu_seconds_total=2.390625 rss_mb=774.9
- python (pid 31528): cpu%= cpu_seconds_total=36.296875 rss_mb=708.8
- python (pid 45040): cpu%=24.92 cpu_seconds_total=61401.484375 rss_mb=1873.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31528, relaunches_total=119, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25056, relaunches_total=117, relaunched_this_cycle=True, last_errors=System.Object[]
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2586; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31080, relaunches_total=118, relaunched_this_cycle=True, last_errors=System.Object[]
