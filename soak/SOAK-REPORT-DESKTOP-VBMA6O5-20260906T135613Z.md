# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T135613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 11.5 h of 2
- egress probes: 24, failing: 24
- heartbeats: 135
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 20216): cpu%= cpu_seconds_total=6.59375 rss_mb=773.9
- python (pid 28960): cpu%= cpu_seconds_total=5.265625 rss_mb=773.8
- python (pid 33072): cpu%= cpu_seconds_total=11.296875 rss_mb=777.3
- python (pid 45040): cpu%=35.59 cpu_seconds_total=15510.890625 rss_mb=2008.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3087; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35904, relaunches_total=23, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2688; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24288, relaunches_total=22, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29392, relaunches_total=23, relaunched_this_cycle=True, last_errors=
