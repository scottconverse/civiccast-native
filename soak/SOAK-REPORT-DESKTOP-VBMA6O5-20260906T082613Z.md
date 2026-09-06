# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T082613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 6 h of 2
- egress probes: 13, failing: 13
- heartbeats: 124
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 41352): cpu%= cpu_seconds_total=0.046875 rss_mb=21.1
- python (pid 1672): cpu%= cpu_seconds_total=11.015625 rss_mb=778
- python (pid 26616): cpu%= cpu_seconds_total=29.21875 rss_mb=749.4
- python (pid 45040): cpu%=17 cpu_seconds_total=10887.421875 rss_mb=1824.2

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27956, relaunches_total=12, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1218; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18912, relaunches_total=12, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=608, relaunches_total=12, relaunched_this_cycle=True, last_errors=
