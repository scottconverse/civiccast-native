# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T042613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 26 h of 2
- egress probes: 53, failing: 53
- heartbeats: 164
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 37156): cpu%= cpu_seconds_total=0.03125 rss_mb=25.3
- python (pid 29360): cpu%= cpu_seconds_total=13.890625 rss_mb=763
- python (pid 30280): cpu%= cpu_seconds_total=6.34375 rss_mb=773.5
- python (pid 35072): cpu%= cpu_seconds_total=26.796875 rss_mb=748.6
- python (pid 45040): cpu%=19.49 cpu_seconds_total=27198.78125 rss_mb=1833.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3629; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30280, relaunches_total=52, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3633; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29360, relaunches_total=51, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43104, relaunches_total=52, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
