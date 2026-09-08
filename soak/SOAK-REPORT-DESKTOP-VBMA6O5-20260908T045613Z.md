# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T045613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 50.5 h of 2
- egress probes: 102, failing: 102
- heartbeats: 213
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 23496): cpu%= cpu_seconds_total=0.078125 rss_mb=20.6
- python (pid 29524): cpu%= cpu_seconds_total=11.78125 rss_mb=762.5
- python (pid 37036): cpu%= cpu_seconds_total=24.984375 rss_mb=749.7
- python (pid 45040): cpu%=29.44 cpu_seconds_total=51670.78125 rss_mb=1847.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29524, relaunches_total=101, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2696; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30068, relaunches_total=100, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2221; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42920, relaunches_total=100, relaunched_this_cycle=True, last_errors=System.Object[]
