# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T072613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 5 h of 2
- egress probes: 11, failing: 11
- heartbeats: 122
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 36020): cpu%= cpu_seconds_total=0.0625 rss_mb=20.3
- python (pid 1776): cpu%= cpu_seconds_total=16.78125 rss_mb=763.9
- python (pid 9260): cpu%= cpu_seconds_total=12.828125 rss_mb=778.5
- python (pid 29328): cpu%= cpu_seconds_total=20.875 rss_mb=768
- python (pid 45040): cpu%=19.37 cpu_seconds_total=10294.15625 rss_mb=1826.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9260, relaunches_total=10, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=1776, relaunches_total=10, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29328, relaunches_total=10, relaunched_this_cycle=True, last_errors=
